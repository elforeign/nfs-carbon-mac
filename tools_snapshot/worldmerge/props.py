"""Ordinary scenery physics: native spawns, bounds, hierarchies and overrides.

008179B0 reads the short count at +10 and 64-byte rows; 007A73F0
binds six-byte overrides through four-byte scenery references. Spawn words
are model +28, bounds +32, attributes +36, override +40, linkage identity +44,
and modes +48; runtime words +52..63 start zero. Bounds remain model-local. Five source fence-post placements have no supplied bounds.
"""
from collections import defaultdict
import hashlib
import struct
import zlib

from formats import Chunk, chunks, require, u32
import convert

SPAWNS, SCENE, HEADER, MODELS, INSTANCES = 0x34027, 0x80034100, 0x34101, 0x34102, 0x34103
BINDINGS, OVERRIDES, BOUNDS, HIERARCHIES = 0x34106, 0x34108, 0x8003b900, 0x8003410b
GLOBALS = {BOUNDS, HIERARCHIES, OVERRIDES}
# Decoded shared keys have different shapes / hierarchy child order.
BOUND_KEYS = {k: zlib.crc32(f'rockport-bound:{k:08x}'.encode()) for k in
              (0x83a9bad6, 0xb21a3f48, 0xd4a1f964)}
HIERARCHY_KEYS = {0x3393b8e2: zlib.crc32(b'rockport-hierarchy:3393b8e2')}
SOURCE_HOLES = {0xbab2fd8b, 0x1c194c84}


def one(parts, kind):
    found = [p for p in parts if p.kind == kind]
    require(len(found) == 1, f'prop singleton {kind:08x}: {len(found)}')
    return found[0]


def spawn_data(chunk, *, native):
    raw = convert.aligned_payload(chunk)
    require(len(raw) >= 16, 'prop header truncated')
    count = struct.unpack_from('<h' if native else '<I', raw, 10 if native else 12)[0]
    require(0 <= count < 32768 and len(raw) == 16+64*count, 'prop count/payload differs')
    return struct.unpack_from('<H', raw, 8)[0], [raw[p:p+64] for p in range(16,len(raw),64)]


def _roots(index, stream):
    """Read scenery/physics payloads without copying unrelated mesh archives."""
    length = stream.stat().st_size
    with stream.open('rb') as file:
        for section in index.sections:
            require(0 < section.size <= 256 << 20, 'prop section exceeds size budget')
            require(0 <= section.offset <= length and section.size <= length-section.offset,
                    'prop section outside stream')
            cursor, end = section.offset, section.offset+section.size
            while cursor < end:
                file.seek(cursor)
                header = file.read(8)
                require(len(header) == 8 and cursor+8 <= end, 'truncated prop section chunk')
                kind, size = struct.unpack('<II',header)
                require(size <= end-cursor-8, 'prop chunk crosses section')
                if kind in (SCENE,SPAWNS):
                    raw = file.read(size)
                    require(len(raw) == size, 'short prop section read')
                    yield section.number, Chunk(kind,raw,cursor-section.offset)
                cursor += 8+size


def inventory(index, stream, *, native):
    scenes, spawns = {}, []
    for physical, root in _roots(index,stream):
        if root.kind == SCENE:
            parts = chunks(root.payload, root.offset+8)
            number = u32(convert.aligned_payload(one(parts, HEADER)), 12)
            require(number not in scenes, 'duplicate prop scenery owner')
            models = one(parts, MODELS).payload
            instances = convert.aligned_payload(one(parts, INSTANCES))
            bindings = b''.join(c.payload for c in parts if c.kind == BINDINGS)
            scenes[number] = (len(instances)//(96 if native else 64), models, bindings)
        else:
            number, rows = spawn_data(root, native=native)
            spawns.append((physical, number, rows))
    return scenes, spawns


def collections(index, kind):
    roots = [c for c in index.parts if c.kind == kind]
    if not roots:
        return {}
    root = one(roots, kind)
    result = {}
    for c in chunks(root.payload, root.offset+8):
        require(c.kind == (0x3b901 if kind == BOUNDS else 0x3410c),
                'unexpected prop collection child')
        raw = convert.aligned_payload(c) if kind == BOUNDS else c.payload
        key = u32(raw)
        # 006D8310 inserts only the first collection for each key; later
        # rows can be coarse fallback shapes with the same identity.
        result.setdefault(key, (c.kind, raw))
    return result


def override_rows(index):
    raw = one(index.parts, OVERRIDES).payload
    require(not any(raw[len(raw)//6*6:]), 'nonzero override tail')
    return list(struct.iter_unpack('<3H', raw[:len(raw)//6*6]))


def models(raw):
    out = bytearray(raw)
    for p in range(0,len(raw),72):
        key = u32(raw,p+64)
        struct.pack_into('<I',out,p+64,HIERARCHY_KEYS.get(key,key))
    return bytes(out)


def _residue(out, offset):
    pad = (offset-out.position)%128
    if pad:
        if pad < 8:
            pad += 128
        out.add(0,bytes(pad-8))


class Import:
    """One city import; scene order matches source sections, native prefix first."""
    def __init__(self, source, ms, native, cs=None, *, mapping=None, shift=(0.,0.)):
        self.source, self.native, self.shift = source, native, shift
        self.scenes, self.original = inventory(source,ms,native=False)
        native_scenes, native_spawns = inventory(native,cs,native=True) if cs else ({}, [])
        self.mapping = mapping or {n:n for n in self.scenes}
        self.locations, counts = {}, {n:v[0] for n,v in native_scenes.items()}
        for old, (count, _, _) in self.scenes.items():
            target = self.mapping[old]
            self.locations[old] = target, counts.get(target,0)
            counts[target] = counts.get(target,0)+count
        self.override_base = len(override_rows(native))
        self.overrides = []
        self.bindings = defaultdict(list)
        source_overrides = override_rows(source)
        for section, instance, flags in source_overrides:
            target, base = self.locations[section]
            require(instance < self.scenes[section][0], 'source override instance outside scenery')
            self.overrides.append((target,base+instance,flags))
        require(self.override_base+len(self.overrides) <= 65536, 'prop override short capacity')
        for old, (_, _, refs) in self.scenes.items():
            target, base = self.locations[old]
            for override, instance in struct.iter_unpack('<2H',refs):
                require(source_overrides[override][:2] == (old,instance), 'source override misbound')
                self.bindings[target].append((self.override_base+override,base+instance))
        self.identity_base = 1+max((u32(r,44) for _,_,rows in native_spawns for r in rows),default=-1)
        self.rows = defaultdict(list)
        self.requested_bounds = set()
        for _, old, rows in self.original:
            target, _ = self.locations[old]
            for row in rows:
                dst = bytearray(64)
                dst[:28], dst[28:52] = row[:28], row[32:56]
                for off,delta in ((16,shift[0]),(24,shift[1])):
                    struct.pack_into('<f',dst,off,struct.unpack_from('<f',row,off)[0]+delta)
                key = u32(row,36)
                self.requested_bounds.add(key)
                struct.pack_into('<I',dst,32,BOUND_KEYS.get(key,key))
                override = u32(row,44)
                require(override < len(self.overrides), 'prop override outside table')
                struct.pack_into('<I',dst,40,override+self.override_base)
                struct.pack_into('<I',dst,44,u32(row,48)+self.identity_base)
                self.rows[target].append(bytes(dst))
        self.requested_hierarchies = {u32(v[1],p+64) for v in self.scenes.values()
                                     for p in range(0,len(v[1]),72)}-{0}
        self.bounds = collections(source,BOUNDS)
        self.hierarchies = collections(source,HIERARCHIES)
        require(self.requested_bounds-self.bounds.keys() <= SOURCE_HOLES, 'new source prop bounds hole')
        require(self.requested_hierarchies <= self.hierarchies.keys(), 'source hierarchy unresolved')
        for kind,keys,aliases in ((BOUNDS,self.requested_bounds,BOUND_KEYS),
                                   (HIERARCHIES,self.requested_hierarchies,HIERARCHY_KEYS)):
            existing = collections(native,kind)
            require(not (set(aliases.values()) & (existing.keys() | keys)), 'prop namespace collision')

    def section(self, data):
        """Retain converted geometry, restore its tables and append its spawns."""
        out = convert.Builder(0)
        for root in chunks(data):
            logical = None
            if root.kind == SCENE:
                parts = chunks(root.payload,root.offset+8)
                logical = u32(convert.aligned_payload(one(parts,HEADER)),12)
                model = one(parts,MODELS)
                raw = bytearray(root.payload)
                at = model.offset-root.offset
                raw[at:at+len(model.payload)] = models(model.payload)
                root = self.decorate(Chunk(SCENE,bytes(raw),root.offset))
            _residue(out,root.offset)
            out.data += root.encode()
            if logical is not None:
                self.emit(out,logical)
        return bytes(out.data)

    def decorate(self, root):
        """Converted scene bindings are appended after the composed arrays."""
        parts = chunks(root.payload,root.offset+8)
        logical = u32(convert.aligned_payload(one(parts,HEADER)),12)
        refs = self.bindings.get(logical,())
        return Chunk(SCENE,root.payload+Chunk(BINDINGS,b''.join(struct.pack('<2H',*r) for r in refs)).encode(),root.offset) if refs else root

    def emit(self, out, logical):
        rows = self.rows.get(logical)
        if rows is None:
            return
        require(len(rows) < 32768, 'coalesced prop count exceeds signed short')
        header = bytearray(16)
        struct.pack_into('<IIHH',header,0,11,11,logical,len(rows))
        out.pad(16)
        out.add(SPAWNS,header+b''.join(rows),16)

    def append_global(self, out, kind):
        native = next((c for c in self.native.parts if c.kind == kind),None)
        residue = native.offset if native else 0
        _residue(out,residue)
        out.data += self.global_chunk(kind,out.position).encode()

    def global_chunk(self, kind, position):
        native = next((c for c in self.native.parts if c.kind == kind),None)
        if kind == OVERRIDES:
            raw = one(self.native.parts,kind).payload
            body = raw[:self.override_base*6]+b''.join(struct.pack('<3H',*v) for v in self.overrides)
            return Chunk(kind,body+bytes(-len(body)%4),position)
        out = convert.Builder(position+8)
        if native:
            # Native bound children include absolute alignment filler.
            require(position%16 == native.offset%16, 'native prop collection residue differs')
            out.data += native.payload
        rows, wanted, aliases = ((self.bounds,self.requested_bounds,BOUND_KEYS) if kind == BOUNDS else
                                 (self.hierarchies,self.requested_hierarchies,HIERARCHY_KEYS))
        for key in sorted(wanted & rows.keys()):
            child, raw = rows[key]
            raw = bytearray(raw)
            struct.pack_into('<I',raw,0,aliases.get(key,key))
            out.add(child,raw,16 if kind == BOUNDS else 1)
        return Chunk(kind,bytes(out.data),position)


def check(index, stream, source, ms, native, cs=None, *, mapping=None, shift=(0.,0.), removed=(), omit_sky=False):
    """Reread tables and compare each field to its source, without Import/writers.

    The mapping comes from the world's independent geometry correspondence.
    Source order and instance counts establish composition offsets, not a plan.
    """
    original, before = inventory(source,ms,native=False)
    if omit_sky:
        count, table, refs = original[2600]
        require(count == 7 and u32(table,24) == 0xed85ba82 and not refs,
                'source sky prop layout differs')
        original[2600] = count-1, table[72:], refs
    prefix, native_spawns = inventory(native,cs,native=True) if cs else ({},[])
    actual, written = inventory(index,stream,native=True)
    mapping = mapping or {n:n for n in original}
    offsets, cursor = {}, {n:v[0] for n,v in prefix.items()}
    for old,(count,_,_) in original.items():
        target = mapping[old]
        offsets[old] = cursor.get(target,0)
        cursor[target] = offsets[old]+count
    base = len(override_rows(native))
    old_overrides, overrides = override_rows(source), override_rows(index)
    require(overrides[:base] == override_rows(native), 'native prop overrides changed')
    require(len(overrides) == base+len(old_overrides), 'prop override count differs')
    for i,(owner,instance,flags) in enumerate(old_overrides):
        require(overrides[base+i] == (mapping[owner],instance+offsets[owner],flags),
                'prop override rebase differs')
    expected_bindings = defaultdict(list)
    for logical,(_,_,refs) in prefix.items():
        expected_bindings[logical].extend(struct.iter_unpack('<2H',refs))
    for old,(_,_,refs) in original.items():
        expected_bindings[mapping[old]].extend((base+o,i+offsets[old]) for o,i in struct.iter_unpack('<2H',refs))
    for logical,(_,_,refs) in actual.items():
        decoded = list(struct.iter_unpack('<2H',refs))
        require(decoded == expected_bindings[logical], 'prop scenery binding rows differ')
        for override,instance in decoded:
            require(overrides[override][:2] == (logical,instance), 'prop scenery override misbound')
    bounds, hierarchies = collections(index,BOUNDS), collections(index,HIERARCHIES)
    source_bounds, source_hierarchies = collections(source,BOUNDS),collections(source,HIERARCHIES)
    wanted_bounds = {u32(r,36) for _,_,rows in before for r in rows}
    wanted_hierarchies = {u32(models,p+64) for _,models,_ in original.values()
                          for p in range(0,len(models),72)}-{0}
    for kind,old,wanted,aliases,found in ((BOUNDS,source_bounds,wanted_bounds,BOUND_KEYS,bounds),
                                        (HIERARCHIES,source_hierarchies,wanted_hierarchies,HIERARCHY_KEYS,hierarchies)):
        native_collections = collections(native,kind)
        old_roots = [c for c in native.parts if c.kind == kind]
        if old_roots:
            require(one(index.parts,kind).payload.startswith(old_roots[0].payload),
                    'native prop collection prefix changed')
        require(found.keys() == native_collections.keys() | {aliases.get(k,k) for k in wanted & old.keys()},
                'prop shape/hierarchy completeness differs')
        for key,value in native_collections.items():
            require(found[key] == value, 'native prop shape/hierarchy changed')
        for key in wanted & old.keys():
            child,raw = old[key]
            expected = bytearray(raw)
            struct.pack_into('<I',expected,0,aliases.get(key,key))
            require(found[aliases.get(key,key)] == (child,bytes(expected)), 'imported prop shape/hierarchy bytes differ')
    # Model-table hierarchy selectors must resolve to the namespaced collection.
    model_cursors = {n:len(v[1]) for n,v in prefix.items()}
    for old,(_,models,_) in original.items():
        target = mapping[old]
        start = model_cursors.get(target,0)
        table = actual[target][1][start:start+len(models)]
        for p in range(0,len(models),72):
            key = u32(models,p+64)
            require(u32(table,p+64) == HIERARCHY_KEYS.get(key,key), 'prop hierarchy model reference differs')
        model_cursors[target] = start+len(models)
    identity_base = 1+max((u32(r,44) for _,_,rows in native_spawns for r in rows),default=-1)
    expected = defaultdict(list)
    holes, target_pylon = 0, None
    for physical,old,rows in before:
        logical = mapping[old]
        for i,row in enumerate(rows):
            expected[logical].append((physical,old,i,row))
    incoming = {}
    native_rows = []
    for physical,logical,rows in written:
        added = [r for r in rows if u32(r,40) >= base]
        if added:
            require(logical not in incoming, 'uncoalesced prop owner')
            incoming[logical] = physical,added
        native_rows.extend(r for r in rows if u32(r,40) < base)
    require(incoming.keys() == expected.keys(), 'prop owner completeness differs')
    for logical, originals in expected.items():
        physical,rows = incoming[logical]
        require(len(rows) == len(originals), 'prop row count differs')
        for row,(old_stream,old,i,before_row) in zip(rows,originals):
            require(row[:16] == before_row[:16] and row[52:] == bytes(12), 'prop rotation/runtime fields differ')
            for axis,delta in enumerate((shift[0],0.,shift[1])):
                expected_float = struct.pack('<f',struct.unpack_from('<f',before_row,16+axis*4)[0]+delta)
                require(row[16+axis*4:20+axis*4] == expected_float, 'prop XYZ translation differs')
            for new_off,old_off in ((32,36),):
                key = u32(before_row,old_off)
                require(u32(row,new_off) == BOUND_KEYS.get(key,key), 'prop bounds reference differs')
            require(row[28:32] == before_row[32:36], 'prop model key differs')
            bound = u32(before_row,36)
            if bound not in source_bounds:
                require(bound in SOURCE_HOLES, 'new prop bounds hole')
                holes += 1
            require(row[36:40] == before_row[40:44] and row[48:52] == before_row[52:56], 'prop attributes/mode flags differ')
            override = u32(before_row,44)
            require(u32(row,40) == base+override and u32(row,44) == u32(before_row,48)+identity_base,
                    'prop override/identity rebase differs')
            owner,instance,_ = old_overrides[override]
            require(overrides[u32(row,40)][:2] == (mapping[owner],instance+offsets[owner]), 'prop spawn override misbound')
            if old_stream == 152 and i == 50:
                target_pylon = dict(stream=physical,scene=mapping[owner],instance=instance+offsets[owner],
                                    bounds=f'{u32(row,32):08X}',override=u32(row,40))
    wanted_native = [r for _,_,rows in sorted(native_spawns) for r in rows if u32(r,40) not in removed]
    require(native_rows == wanted_native, 'native prop rows changed')
    # Every spawn must follow its own scene in the same physical record.
    loaded, previous = set(), None
    for physical, root in _roots(index,stream):
        if physical != previous:
            loaded, previous = set(), physical
        if root.kind == SCENE:
            h = convert.aligned_payload(one(chunks(root.payload,root.offset+8),HEADER))
            loaded.add(u32(h,12))
        else:
            logical,_ = spawn_data(root,native=True)
            require(logical in loaded, 'prop spawns precede their scenery')
    return dict(rows=sum(len(v) for v in expected.values()),owners=len(expected),
                largest_owner=max(map(len,expected.values()),default=0),shapes=len(wanted_bounds & source_bounds.keys()),
                hierarchies=len(wanted_hierarchies),source_bounds_holes=holes,newly_misbound_overrides=0,
                native_rows=len(native_rows),native_sha256=hashlib.sha256(b''.join(native_rows)).hexdigest(),pylon=target_pylon)


def check_native(index, stream, native, cs, *, removed=()):
    """Literal native-row proof, including the bridge's one retired spawn."""
    _, expected = inventory(native,cs,native=True)
    base = len(override_rows(native))
    _, actual = inventory(index,stream,native=True)
    before = [r for _,_,rows in sorted(expected) for r in rows if u32(r,40) not in removed]
    after = [r for _,_,rows in actual for r in rows if u32(r,40)<base]
    require(after == before, 'native prop rows changed')
    return dict(native_rows=len(after),native_sha256=hashlib.sha256(b''.join(after)).hexdigest())
