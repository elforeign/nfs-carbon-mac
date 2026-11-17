"""Build one combined track pair and verify its serialized bytes offline.

The checker reads the pair and original archives, not a saved allocation plan
or writer counters. It recovers zone compositions from translated instances,
then checks source row unions, polygon unions, providers, collision and roads.
Private inputs are read-only; output must be a new directory outside checkouts.
"""
import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from fractions import Fraction
import hashlib
import itertools
import json
import math
import os
from pathlib import Path
import shutil
import struct
import sys
import tempfile

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(HERE))
import c1_numbers as numbers
import c1_roads as roads
import c1_grid as grid
import c1_zones
import c3_crossing
import classify
import convert
import dome
import emitters
import events
import ground
import props
import prop_attributes
import region
import texanim
import visibility as vis
import zones as zone_tables
from formats import Boundary, Chunk, FormatError, Section, TrackIndex, chunks, require, u32
from merge import DEFAULT_MW, DEFAULT_CARBON, load_index, read_section

ROOT = HERE.parents[1]
SCENE, HEADER, MODELS, INSTANCES, TREE, PRECULL = 0x80034100, 0x34101, 0x34102, 0x34103, 0x34105, 0x34107
MAP, PACK, TILE = 0x3b800, 0x3b801, 0x3b802
RESIDENT = 2600
DEFAULT_SHIFT = (20480., 0.)
RENDER_SHIFT = (DEFAULT_SHIFT[1], -DEFAULT_SHIFT[0])
POOL_BYTES = 71680000


def _physics_shift(value):
    require(isinstance(value, (tuple, list)) and len(value) == 2 and
            all(isinstance(v, (int, float)) and math.isfinite(v) for v in value),
            'shift must contain two finite physics components (X Z)')
    for axis, component in zip(('X', 'Z'), value):
        require(component % 4096 == 0,
                f'shift {axis}={component:g} m must be a multiple of 4096 m')
    return tuple(float(v) for v in value)


def _polygons_intersect(a, b):
    """Closed polygons: crossings, shared edges/vertices and containment count."""
    if any(max(p[k] for p in a) < min(p[k] for p in b) or
           max(p[k] for p in b) < min(p[k] for p in a) for k in (0, 1)):
        return False
    def on(p, q, r):
        return numbers.cross(p, q, r) == 0 and all(
            min(p[k], q[k]) <= r[k] <= max(p[k], q[k]) for k in (0, 1))
    for p, q in zip(a, a[1:]+a[:1]):
        for r, t in zip(b, b[1:]+b[:1]):
            x, y = numbers.cross(p, q, r), numbers.cross(p, q, t)
            z, v = numbers.cross(r, t, p), numbers.cross(r, t, q)
            if ((x > 0 > y or y > 0 > x) and (z > 0 > v or v > 0 > z) or
                    on(p, q, r) or on(p, q, t) or on(r, t, p) or on(r, t, q)):
                return True
    return numbers.inside(a[0], b) or numbers.inside(b[0], a)


def _zone_overlaps(native, incoming):
    return [(a.number, b.number) for a in native if numbers.zone(a.number)
            for b in incoming if numbers.zone(b.number) and
            _polygons_intersect(a.vertices, b.vertices)]


def _placement_grid(carbon, source, shift):
    """Enclose full descriptors; bin occupied footprints before testing distance."""
    co, spacing, cr, cc = grid.grid_fields(carbon.descriptor)
    so, step, sr, sc = grid.grid_fields(source.descriptor)
    ox = co[0]+min(0, math.floor((so[0]+shift[0]-co[0])/spacing))*spacing
    oz = co[2]+min(0, math.floor((so[2]+shift[1]-co[2])/spacing))*spacing
    columns = math.ceil((max(co[0]+cc*spacing, so[0]+shift[0]+sc*step)-ox)/spacing)
    rows = math.ceil((max(co[2]+cr*spacing, so[2]+shift[1]+sr*step)-oz)/spacing)
    require(0 < rows*columns <= 65536,
            f'placement grid {rows} x {columns} = {rows*columns} slots exceeds 65536 slots')
    occupied = []
    for city, delta in ((carbon, (0., 0.)), (source, shift)):
        origin, cell, _, cols = grid.grid_fields(city.descriptor)
        bins = set()
        for record in city.cells:
            r, c = divmod(struct.unpack_from('<H', record, 4)[0], cols)
            x, z = origin[0]+delta[0]+c*cell-ox, origin[2]+delta[1]+r*cell-oz
            bins.update((rr, col) for rr in range(math.floor(z/spacing), math.ceil((z+cell)/spacing))
                        for col in range(math.floor(x/spacing), math.ceil((x+cell)/spacing)))
        occupied.append(bins)
    native, incoming = occupied
    for r, c in sorted(incoming):
        for dr in range(-2, 3):
            for dc in range(-2, 3):
                require((r+dr, c+dc) not in native,
                        f'collision cells within two cells: Palmont ({r+dr},{c+dc}), '
                        f'Rockport ({r},{c}) on the {spacing:g} m grid')
    return rows, columns, len(native | incoming)


def _check_placement(carbon, cs, source, ms, groups, shift):
    render = (shift[1], -shift[0])
    native = vis.read(vis.payload_of(carbon))
    old = {b.number: b for b in vis.read(vis.payload_of(source), extended=False).boundaries}
    incoming = [union_boundary(old[g['members'][0]], g['number'], g['polygon'], shift=render)
                for g in groups]
    native_bounds, _ = c3_crossing.apply(native.boundaries, (), shift)
    incoming, _ = c3_crossing.apply(incoming, (), shift)
    overlaps = _zone_overlaps(native_bounds, incoming)
    require(not overlaps, 'zone-class polygon overlap (Palmont/Rockport): ' +
            ', '.join(f'{a}/{b}' for a, b in overlaps[:8]) +
            (f' ({len(overlaps)} pairs total)' if overlaps else ''))
    return _placement_grid(grid.read_city(carbon, cs), grid.read_city(source, ms), shift)


@dataclass(frozen=True)
class Scene:
    header: bytes
    models: bytes
    instances: bytes
    tree: bytes
    precull: bytes
    extras: tuple = ()

    @property
    def number(self):
        return u32(self.header, 12)


def scene_data(root, *, native=True):
    parts = region.children(root)
    allowed = {HEADER, MODELS, INSTANCES, TREE, PRECULL, 0x34106} | ({0x3410a, 0x3410d} if native else set())
    require(set(c.kind for c in parts) <= allowed, 'unexpected scenery child')
    def data(kind, aligned=False):
        found = [c for c in parts if c.kind == kind]
        require(len(found) <= 1, 'duplicate scenery child')
        require(found or kind in (TREE, PRECULL), 'missing scenery child')
        return (convert.aligned_payload(found[0]) if aligned else found[0].payload) if found else b''
    extras = tuple(c for c in parts if c.kind not in {HEADER,MODELS,INSTANCES,TREE,PRECULL})
    return Scene(data(HEADER, True), data(MODELS), data(INSTANCES, True),
                 data(TREE, native), data(PRECULL), extras)


def append_at_residue(out, chunk):
    """Moving a root preserves all nested absolute alignments modulo 128."""
    pad = (chunk.offset - out.position) % 128
    if pad:
        if pad < 8:
            pad += 128
        out.add(0, bytes(pad-8))
    out.data += chunk.encode()


def mapped_provider(root, target):
    """Only owning section words change; keys and dispatch words stay intact."""
    if root.kind == 0x3bc00:
        layout = emitters.decode_emitters(root)
        raw = bytearray(layout.raw)
        struct.pack_into('<I', raw, 12, target)
        for p in layout.records:
            struct.pack_into('<H', raw, p+8, target)
        pad = -(root.offset+8) % 16
        return Chunk(root.kind, b'\x11'*pad + raw, root.offset)
    if root.kind == 0x80036000:
        parts = region.children(root)
        first = parts[0]
        raw = bytearray(first.payload)
        struct.pack_into('<I', raw, -(first.offset+8) % 16 + 12, target)
        parts[0] = Chunk(first.kind, bytes(raw), first.offset)
        return Chunk(root.kind, b''.join(c.encode() for c in parts), root.offset)
    return root


def converted_scene(source_root, target_root, number):
    """Carry the decoded short precull selector omitted by the base converter.

    Instance +0x1c is a signed short in the native 0079FA60 consumer. The
    existing converter leaves it zero; composition must preserve and rebase it.
    """
    before, after = scene_data(source_root, native=False), scene_data(target_root)
    header, instances = bytearray(after.header), bytearray(after.instances)
    struct.pack_into('<I', header, 12, number)
    require(len(before.instances)//64 == len(instances)//96, 'converted instance count')
    for i in range(len(instances)//96):
        instances[i*96+28:i*96+30] = before.instances[i*64+28:i*64+30]
        model = struct.unpack_from('<h', instances, i*96+84)[0]
        if u32(before.models, model*72+24) == 0xed85ba82:
            # 0079AFA0 excludes 80000 with a nonzero sky gate and 40000
            # with a zero gate (unless 100 is set). The global sky owns this
            # instance; retain its lookup/transform but never submit scenery.
            flags = u32(instances, i*96+12)
            require(flags & 0x80000 and not flags & 0x100, 'sky scenery flags differ')
            struct.pack_into('<I', instances, i*96+12, flags | 0x40000)
    return Scene(bytes(header), props.models(after.models), bytes(instances), after.tree, after.precull)


def combine_scenes(contributions, number, position):
    """Concatenate arrays, rebase signed selectors and join roots at node zero."""
    require(1 <= len(contributions) <= 5, 'scenery composition exceeds root fanout')
    require(not any(s.extras for s in contributions[1:]), 'cannot coalesce trailing scenery sidecars')
    # 007A73F0's 0x3410d loader uses this chunk's own /32 count and binds
    # instance +0x5c in prefix order. Retain native prefix rows verbatim;
    # appended converted instances have a zero +0x5c and no such sidecar.
    extras = contributions[0].extras
    require(all(c.kind == 0x3410d and len(c.payload) == len(contributions[0].instances)//96*32
                for c in extras), 'cannot coalesce undecoded scenery sidecars')
    head = bytearray(contributions[0].header)
    require(len(head) == 68, 'native scenery header size')
    struct.pack_into('<I', head, 12, number)
    models, instances, precull = bytearray(), bytearray(), bytearray()
    trees = bytearray(48 if len(contributions) > 1 else 0)
    roots = []
    for scene in contributions:
        require(len(scene.models)%72 == len(scene.instances)%96 == len(scene.tree)%48 == len(scene.precull)%128 == 0,
                'scenery array stride')
        mo, io, po, to = len(models)//72, len(instances)//96, len(precull)//128, len(trees)//48
        require(scene.tree, 'scenery composition needs a tree')
        roots.append(to)
        for p in range(0, len(scene.instances), 96):
            row = bytearray(scene.instances[p:p+96])
            model, prec = struct.unpack_from('<h', row, 84)[0], struct.unpack_from('<h', row, 28)[0]
            require(0 <= model < len(scene.models)//72 and 0 <= prec < len(scene.precull)//128,
                    'scenery selector outside source array')
            require(model+mo < 32768 and prec+po < 32768, 'scenery selector exceeds signed short')
            struct.pack_into('<h', row, 84, model+mo)
            struct.pack_into('<h', row, 28, prec+po)
            instances += row
        for p in range(0, len(scene.tree), 48):
            node = bytearray(scene.tree[p:p+48])
            count = u32(node, 12)
            require(0 < count <= 5, 'tree child count')
            for k in range(count):
                value = struct.unpack_from('<h', node, 28+2*k)[0]
                value = value+io if value >= 0 else value-to
                require(-32768 < value < 32768, 'tree selector exceeds signed short')
                struct.pack_into('<h', node, 28+2*k, value)
            trees += node
        models += scene.models
        precull += scene.precull
    if len(contributions) > 1:
        lows = [struct.unpack_from('<3f', s.tree) for s in contributions]
        highs = [struct.unpack_from('<3f', s.tree, 16) for s in contributions]
        struct.pack_into('<3fI3f', trees, 0, *(min(v[k] for v in lows) for k in range(3)),
                         len(roots), *(max(v[k] for v in highs) for k in range(3)))
        struct.pack_into(f'<{len(roots)}h', trees, 28, *(-r for r in roots))
    require(len(instances)//96 < 32768 and len(trees)//48 < 32768, 'scenery array exceeds signed selectors')
    out = convert.Builder(position+8)
    for kind, raw, align in ((HEADER, head, 16), (MODELS, models, 1), (INSTANCES, instances, 16),
                             *((c.kind,c.payload,1) for c in extras),
                             (TREE, trees, 16), (PRECULL, precull, 1)):
        out.add(kind, raw, align)
    return Chunk(SCENE, bytes(out.data), position)


def union_boundary(template, number, polygon, shift=None):
    shift = RENDER_SHIFT if shift is None else shift
    raw = bytearray(template.raw[:12] + bytes(12) + template.raw[12:36])
    raw[:8] = bytes(8)
    struct.pack_into('<hB', raw, 8, number, len(polygon))
    xs, ys = zip(*polygon)
    low, high = (min(xs), min(ys)), (max(xs), max(ys))
    struct.pack_into('<6f', raw, 24, low[0]+shift[0], low[1]+shift[1],
                     high[0]+shift[0], high[1]+shift[1],
                     (low[0]+high[0])/2+shift[0], (low[1]+high[1])/2+shift[1])
    raw += b''.join(struct.pack('<2f', x+shift[0], y+shift[1]) for x, y in polygon)
    result = Boundary(bytes(raw), True)
    result.validate()
    return result


def visibility_bytes(document, carbon, source, *, shift=RENDER_SHIFT):
    schedule = document['composition']
    native = vis.read(vis.payload_of(carbon))
    old = vis.read(vis.payload_of(source), extended=False)
    boundaries = {b.number: b for b in old.boundaries}
    added = [union_boundary(boundaries[g['members'][0]], g['number'], g['polygon'], shift=shift)
             for g in schedule['groups']]
    added += [b.translate(document['numbers']['rockport'][str(b.number)], shift=shift)
              for b in old.boundaries if not numbers.zone(b.number)]
    original_rows = {r.number: r for r in old.rows}
    rows = list(native.rows)
    for row in schedule['rows']:
        if row['city'] == 'palmont':
            continue
        entries = row['entries']
        header = bytearray(original_rows[row['members'][0]].header)
        header[:12] = bytes(12)
        struct.pack_into('<h', header, 12, row['number'])
        header[15] = len(entries)
        struct.pack_into('<h', header, 16, len(entries))
        rows.append(vis.Row(bytes(header), tuple(entries), bytes(2)))
    boundaries, rows = c3_crossing.apply([*native.boundaries, *added], rows, (-shift[1], shift[0]))
    drive = schedule['drivable']
    slots = schedule['drivable_slots']
    replacements = {vis.DRIVE: struct.pack('<II', 40, len(drive)) + struct.pack(f'<{slots}h',
                         *(drive + [0]*(slots-len(drive)))),
                    vis.BOUNDARIES: b''.join(b.raw for b in boundaries),
                    vis.ROWS: b''.join(r.encode() for r in rows)}
    out = convert.Builder(8)
    for part in native.parts:
        if part.kind == vis.SELECTORS:
            out.add(part.kind, b''.join(native.selectors), 16)
        else:
            out.add(part.kind, replacements.get(part.kind, part.payload))
    return bytes(out.data)


def map_bytes(road_map, descriptor, rectangle):
    """Keep road addresses; compact CDat to descriptor, rectangle and overrides."""
    out = bytearray(road_map)
    tags = region.collision_tags(out, grid.CDAT)
    desc, rect = tags[grid.CGRD], tags[grid.RECT]
    require(desc[1] >> 8 == 40 and rect[1] >> 8 == 10, 'native grid schema')
    out[desc[3]:desc[3]+40] = descriptor
    out[rect[3]:rect[3]+10] = rectangle
    require(len(tags) == 11 and tags[0x636f0000][2] == 0, 'native CDat directory schema')
    group = _group_offset(road_map, grid.CDAT)
    struct.pack_into('<I', out, group+8, 3)
    # The remaining old directory slots become unreferenced bytes. RNgp's
    # independently relative directory and every road address remain in place.
    struct.pack_into('<4I', out, rect[0]+16, 0x636f0000, tags[0x636f0000][1], 0, 0)
    return bytes(out)


def _group_offset(raw, key):
    start = u32(raw, 12)*16
    found = [p for p in range(start,start+16*((u32(raw,4)>>5)+u32(raw,8)),16) if u32(raw,p) == key]
    require(len(found) == 1, 'CARP group missing/duplicate')
    return found[0]


def record_bytes(original, target, offset, size, *, moved=False, shift=RENDER_SHIFT):
    raw = bytearray(original.raw)
    if target != original.number:
        raw[:4] = f'{chr(64+target//100)}{target%100:02d}'.encode()+b'\0'
        struct.pack_into('<h', raw, 8, target)
        struct.pack_into('<I', raw, 36, 10000+target)
    struct.pack_into('<III', raw, 20, offset, size, size)
    if moved:
        x, y, z = original.position
        struct.pack_into('<3f', raw, 40, x+shift[0], y+shift[1], z)
    return Section(bytes(raw))


def _output_path(out, roots):
    out = Path(out).resolve()
    require(not any(out.is_relative_to(Path(r).resolve()) for r in (ROOT, *roots)),
            'output must be outside checkout and private inputs')
    require(not any((p/'.git').exists() for p in (out, *out.parents)),
            'output must be outside every checkout')
    require(not out.exists(), 'output already exists')
    return out


def _write_pair(mw_root, carbon_root, stage, *, zones=False, shift=DEFAULT_SHIFT, _link=True):
    shift = _physics_shift(shift)
    render = (shift[1], -shift[0])
    carbon, cs, _ = load_index(carbon_root, 'L5RA')
    source, ms, _ = load_index(mw_root, 'L2RA')
    document = numbers.plan((source, ms), (carbon, cs))
    require('composition' in document, 'combined source needs the composition schedule')
    schedule, mapping = document['composition'], document['numbers']['rockport']
    _check_placement(carbon, cs, source, ms, schedule['groups'], shift)
    globals_ = {c.kind: c for c in _merge_globals(carbon, source, mapping, shift)} if zones else {}
    component = grid.merge(carbon, cs, source, ms,
                           pack_ids={int(k): v for k, v in document['packs']['rockport'].items()},
                           cell_section=RESIDENT, tile_section=RESIDENT, shift=shift)
    road_map = roads.merge(region.collision_body(region.one(carbon.parts, MAP)),
                           region.collision_body(region.one(source.parts, MAP)), shift=shift)
    combined_map = map_bytes(road_map, component.descriptor, component.rectangle)
    providers, _ = classify.source_providers(source, ms)
    providers = providers, {s.number for s in source.sections}
    animations = texanim.inventory_source(source, ms)
    prop_import = props.Import(source, ms, carbon, cs,
        mapping={int(k):v for k,v in mapping.items()}, shift=shift)
    scenes = defaultdict(list)
    scene_owners = {logical: home for g in schedule['groups'] for logical, home in g['scene_owners']}
    converted = stage/'converted'
    converted.mkdir()
    for section in source.sections:
        raw = read_section(ms, section)
        data, _ = convert.convert_section(raw, section.number, source_number=section.number,
                    shift=render, providers=providers, animation_inventory=animations)
        originals = iter(c for c in chunks(raw) if c.kind == SCENE)
        out = convert.Builder(0)
        for root in chunks(data):
            if root.kind == SCENE:
                original = next(originals)
                old_number = scene_data(original, native=False).number
                target = mapping[str(old_number)]
                scenes[target].append(converted_scene(original, root, target))
            elif root.kind:
                append_at_residue(out, mapped_provider(root, mapping[str(section.number)]))
        if section.number == 2400:
            dome.append(out, mw_root)
        (converted/str(section.number)).write_bytes(out.data)
    # Common residents share a logical scenery identity too. Native arrays lead.
    native_common = {}
    for section in carbon.sections:
        if section.number not in (2500, 2600):
            continue
        for root in chunks(read_section(cs, section)):
            if root.kind == SCENE:
                scene = scene_data(root)
                if scene.number in scenes:
                    scenes[scene.number].insert(0, scene)
                    native_common[scene.number] = section.number
    homes = defaultdict(list)
    for logical in scenes:
        homes[scene_owners.get(logical, native_common.get(logical, logical))].append(logical)
    metadata = {('palmont', s.number): s for s in carbon.sections}
    metadata.update({('rockport', s.number): s for s in source.sections})
    tracks = stage/'TRACKS'
    tracks.mkdir()
    written = []
    with (tracks/'STREAML5RA.BUN').open('wb') as stream:
        for bucket in schedule['records']:
            target = bucket['number']
            out = convert.Builder(0)
            emitted = set()
            for city, old in bucket['members']:
                if city == 'palmont':
                    raw = read_section(cs, metadata[(city, old)])
                    for root in chunks(raw):
                        if root.kind == SCENE and scene_data(root).number in native_common:
                            logical = scene_data(root).number
                            out.pad(128)
                            out.data += prop_import.decorate(combine_scenes(scenes[logical], logical, out.position)).encode()
                            prop_import.emit(out, logical)
                            emitted.add(logical)
                        else:
                            # Keep old tile bytes inert, so only their kind changes.
                            if root.kind == TILE:
                                root = Chunk(0, root.payload, root.offset)
                            append_at_residue(out, root)
                else:
                    for root in chunks((converted/str(old)).read_bytes()):
                        if root.kind:
                            append_at_residue(out, root)
            for logical in sorted(set(homes[target])-emitted, reverse=True):
                out.pad(128)
                out.data += prop_import.decorate(combine_scenes(scenes[logical], logical, out.position)).encode()
                prop_import.emit(out, logical)
            if target == RESIDENT:
                out.pad(16)
                out.add(TILE, component.tile, 16)
                native_pack_ids = {int(k) for k in document['packs']['palmont']}
                for pack in component.packs:
                    if u32(pack, 4) not in native_pack_ids:
                        out.pad(16)
                        out.add(PACK, pack, 16)
            require(out.data, f'empty output record {target}')
            stream.write(bytes(-stream.tell()%2048))
            first_city, first_old = bucket['members'][0]
            written.append(record_bytes(metadata[(first_city, first_old)], target,
                         stream.tell(), len(out.data), moved=first_city == 'rockport', shift=render))
            stream.write(out.data)
    index = convert.Builder(0)
    for part in carbon.parts:
        if part.kind == vis.CONTAINER:
            index.pad(16)
            index.add(part.kind, visibility_bytes(document, carbon, source, shift=render))
        elif part.kind == 0x34110:
            index.pad(16)
            index.add(part.kind, b''.join(s.raw for s in written))
        elif part.kind == MAP:
            index.pad(16)
            index.add(part.kind, combined_map, 16)
        elif part.kind in props.GLOBALS:
            prop_import.append_global(index,part.kind)
        elif part.kind in globals_:
            replacement = globals_[part.kind]
            if part.kind == zone_tables.MARKERS:
                rows = zone_tables.read(tuple(globals_.values())).markers
                # append_at_residue preserves the old residue; derive the pad
                # from the new absolute header offset, as the loader does.
                offset = index.position + (part.offset-index.position) % 128
                pad = -(offset+8) % 16
                replacement = Chunk(part.kind, part.payload[:pad] + b''.join(rows), part.offset)
            append_at_residue(index, replacement)
        else:
            append_at_residue(index, part)
    (tracks/'L5RA.BUN').write_bytes(index.data)
    shutil.rmtree(converted)
    if _link and shift == c3_crossing.SHIFT:
        import c3_link
        c3_link.apply(tracks)
    prop_attributes.write_overlay(mw_root, carbon_root, stage)


def build(mw_root, carbon_root, out, *, zones=False, shift=DEFAULT_SHIFT):
    """Atomically write a new pair, publishing it only after independent check."""
    shift = _physics_shift(shift)
    out = _output_path(out, (mw_root, carbon_root))
    out.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.c1-world-', dir=out.parent))
    try:
        _write_pair(mw_root, carbon_root, stage, zones=zones, shift=shift)
        report = check(stage, mw_root, carbon_root, shift=shift)
        (stage/'proof.json').write_text(json.dumps(report, indent=2, sort_keys=True)+'\n')
        os.rename(stage, out)
        return report
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def _source_instance(raw, native, shift=RENDER_SHIFT):
    """Independent byte oracle, separate from section/scenery conversion."""
    if native:
        return bytes(raw)
    out = bytearray(96)
    out[:12], out[12:16], out[16:28] = raw[:12], raw[24:28], raw[12:24]
    out[28:30], out[32:44] = raw[28:30], raw[32:44]
    struct.pack_into('<9f', out, 44, *(v/8192 for v in struct.unpack_from('<9h', raw, 44)))
    out[84:88] = raw[62:64]+raw[30:32]
    for p in (0, 16, 32):
        for axis, delta in enumerate(shift):
            if delta:
                q = p+axis*4
                struct.pack_into('<f', out, q, struct.unpack_from('<f', out, q)[0]+delta)
    return bytes(out)


def _instance_key(row, models):
    model = struct.unpack_from('<h', row, 84)[0]
    require(0 <= model < len(models)//72, 'model reference unresolved')
    # Exclude selectors that depend on concatenation offsets, retaining every
    # bound, flag, translation, matrix and the model's complete key record.
    return row[:28]+row[32:84]+models[model*72:(model+1)*72]


def _check_scene_tree(scene):
    require(len(scene.header) == 68 and len(scene.models)%72 == len(scene.instances)%96 ==
            len(scene.tree)%48 == len(scene.precull)%128 == 0, 'written scenery stride')
    ni, nt = len(scene.instances)//96, len(scene.tree)//48
    require(0 < ni < 32768 and 0 < nt < 32768, 'written scenery signed selector capacity')
    for p in range(0, len(scene.instances), 96):
        _instance_key(scene.instances[p:p+96], scene.models)
        prec = struct.unpack_from('<h', scene.instances, p+28)[0]
        require(0 <= prec < len(scene.precull)//128, 'precull reference unresolved')
    visited, leaves, active = set(), Counter(), set()
    def visit(i):
        require(0 <= i < nt and i not in active, 'scenery tree cycle/range')
        require(i not in visited, 'scenery tree node has two parents')
        active.add(i)
        visited.add(i)
        p = i*48
        lo, hi = struct.unpack_from('<3f', scene.tree, p), struct.unpack_from('<3f', scene.tree, p+16)
        require(all(math.isfinite(v) for v in (*lo, *hi)) and all(a <= b for a, b in zip(lo, hi)),
                'invalid scenery tree bounds')
        count = u32(scene.tree, p+12)
        require(0 < count <= 5, 'written tree child count')
        for ref in struct.unpack_from(f'<{count}h', scene.tree, p+28):
            if ref < 0:
                child_low, child_high = visit(-ref)
            else:
                require(ref < ni, 'tree instance reference unresolved')
                leaves[ref] += 1
                child_low = struct.unpack_from('<3f', scene.instances, ref*96)
                child_high = struct.unpack_from('<3f', scene.instances, ref*96+16)
            require(all(a-.02 <= b and c <= d+.02 for a,b,c,d in zip(lo,child_low,child_high,hi)),
                    'scenery tree does not enclose child')
        active.remove(i)
        return lo, hi
    visit(0)
    require(len(visited) == nt and set(leaves) == set(range(ni)) and max(leaves.values()) == 1,
            'scenery tree lost/duplicated instances or nodes')


def _check_scene_sources(actual, sources, target, shift=RENDER_SHIFT):
    """Undo concatenation offsets, comparing every original array byte."""
    require(len(sources) <= 5, 'too many source scenery roots')
    joined = len(sources) > 1
    mo = io = po = 0
    to = int(joined)
    native_changes = 0
    for scene, native in sources:
        width = 96 if native else 64
        ni, nm, np, nt = len(scene.instances)//width, len(scene.models)//72, len(scene.precull)//128, len(scene.tree)//(48 if native else 36)
        expected_models = bytearray(scene.models)
        if not native:
            for p in range(0,len(expected_models),72):
                for off in (24,28,32,36):
                    key = u32(expected_models,p+off)
                    struct.pack_into('<I',expected_models,p+off,
                                     0x1f389568 if key == 0xed85ba82 else key)
                key = u32(expected_models,p+64)
                struct.pack_into('<I',expected_models,p+64,props.HIERARCHY_KEYS.get(key,key))
        require(actual.models[mo*72:(mo+nm)*72] == expected_models, 'scenery model bytes/provenance differ')
        require(actual.precull[po*128:(po+np)*128] == scene.precull, 'scenery precull bytes/provenance differ')
        for i in range(ni):
            original = scene.instances[i*width:(i+1)*width]
            expected = bytearray(_source_instance(original, native, shift))
            if not native:
                model = struct.unpack_from('<h', expected, 84)[0]
                if u32(scene.models, model*72+24) == 0xed85ba82:
                    struct.pack_into('<I', expected, 12, u32(expected,12) | 0x40000)
            struct.pack_into('<h', expected, 84, struct.unpack_from('<h', expected, 84)[0]+mo)
            struct.pack_into('<h', expected, 28, struct.unpack_from('<h', expected, 28)[0]+po)
            row = actual.instances[(io+i)*96:(io+i+1)*96]
            require(row == expected, 'scenery instance translation/selector/provenance differs')
            if native:
                native_changes += sum(a != b for a, b in zip(original, row))
        for i in range(nt):
            before = scene.tree[i*(48 if native else 36):(i+1)*(48 if native else 36)]
            if native:
                expected = bytearray(before)
            else:
                expected = bytearray(48)
                expected[:12], expected[16:28], expected[28:38] = before[:12], before[12:24], before[26:36]
                struct.pack_into('<I', expected, 12, struct.unpack_from('<H', before, 24)[0])
                for p in (0, 16):
                    for axis, delta in enumerate(shift):
                        if delta:
                            q = p+axis*4
                            struct.pack_into('<f', expected, q, struct.unpack_from('<f', expected, q)[0]+delta)
            count = u32(expected, 12)
            for k in range(count):
                ref = struct.unpack_from('<h', expected, 28+k*2)[0]
                struct.pack_into('<h', expected, 28+k*2, ref+io if ref >= 0 else ref-to)
            row = actual.tree[(to+i)*48:(to+i+1)*48]
            require(row == expected, 'scenery tree translation/reference/provenance differs')
            if native:
                native_changes += sum(a != b for a, b in zip(before, row))
        mo, io, po, to = mo+nm, io+ni, po+np, to+nt
    require((len(actual.models), len(actual.instances), len(actual.precull), len(actual.tree)) ==
            (mo*72, io*96, po*128, to*48), 'scenery composition has extra/missing array bytes')
    first, native = sources[0]
    require([_digest(c) for c in actual.extras if c.kind != props.BINDINGS] ==
            ([_digest(c) for c in first.extras if c.kind != props.BINDINGS] if native else []),
            'native scenery sidecar bytes differ')
    expected = bytearray(first.header if native else first.header+bytes(8))
    struct.pack_into('<I', expected, 12, target)
    require(actual.header == expected, 'scenery header mapped fields differ')
    if joined:
        roots, cursor = [], 1
        for scene, native in sources:
            roots.append(-cursor)
            cursor += len(scene.tree)//(48 if native else 36)
        require(u32(actual.tree, 12) == len(roots) and
                struct.unpack_from(f'<{len(roots)}h', actual.tree, 28) == tuple(roots),
                'scenery join does not point at source roots')
    return native_changes


def _recover_mapping(source, stream, actual_scenes, native_numbers, shift=RENDER_SHIFT):
    """Infer each old zone's destination from actual translated instance bytes.

    No allocation plan, sidecar, writer report or stored group membership is
    consulted. Full array checks subsequently prove every inferred match.
    """
    lookup = defaultdict(set)
    for logical, (home, scene) in actual_scenes.items():
        if logical in native_numbers and logical != 2600:
            continue
        for p in range(0, len(scene.instances), 96):
            lookup[_instance_key(scene.instances[p:p+96], scene.models)].add(logical)
    recovered, source_scenes = {}, []
    for section in source.sections:
        for root in chunks(read_section(stream, section)):
            if root.kind != SCENE:
                continue
            scene = scene_data(root, native=False)
            models = bytearray(scene.models)
            for m in range(0,len(models),72):
                for off in (24,28,32,36):
                    if u32(models,m+off) == 0xed85ba82:
                        struct.pack_into('<I',models,m+off,0x1f389568)
            possibilities = None
            for p in range(0, len(scene.instances), 64):
                row = bytearray(_source_instance(scene.instances[p:p+64], False, shift))
                model = struct.unpack_from('<h',row,84)[0]
                if u32(scene.models,model*72+24) == 0xed85ba82:
                    struct.pack_into('<I',row,12,u32(row,12) | 0x40000)
                key = _instance_key(bytes(row), models)
                candidates = lookup.get(key, set())
                possibilities = set(candidates) if possibilities is None else possibilities & candidates
                if possibilities is not None and len(possibilities) <= 1:
                    break
            require(possibilities and len(possibilities) == 1,
                    f'scenery {scene.number}: translated source identity unresolved/ambiguous')
            target = next(iter(possibilities))
            require(scene.number not in recovered, 'duplicate source scenery identity')
            recovered[scene.number] = target
            source_scenes.append((section.number, scene, target))
    source_inventory = numbers.inventory((source, stream), False)
    native = set(native_numbers)
    mapping, groups = {}, defaultdict(list)
    for n in sorted(numbers.zone_numbers(source_inventory)):
        require(n in recovered, 'source zone scene missing')
        target = recovered[n]
        require(numbers.zone(target) and recovered.get(n+40,target+40) == target+40, 'scene zone/partner mapping differs')
        mapping[n], mapping[n+40] = target, target+40
        groups[target].append(n)
    slots = [n for n in range(101, 2040) if numbers.zone(n) and n not in native and n+40 not in native]
    ordered = sorted(groups.items(), key=lambda pair: min(pair[1]))
    require([n for n, _ in ordered] == slots and all(1 <= len(m) <= 3 for _, m in ordered),
            'source groups do not fill reserved zone pairs in source order')
    mapping.update({2400: 2100, 2500: 2500, 2600: 2600})
    used = native | set(mapping.values())
    for old in sorted(numbers.source_numbers(source_inventory)):
        if old in mapping:
            continue
        target = old if old not in used else next((n for n in range(100, 2800) if n not in used and
                    (n < 2100 and n%100 >= 80 if old < 2100 else n >= 2101)), None)
        require(target is not None, 'source resource mapping exhausted')
        mapping[old] = target
        used.add(target)
    require(all(mapping[n] == target for n, target in recovered.items()), 'resource/scenery mapping differs')
    return mapping, dict(ordered), source_scenes


def _rings_equal(actual, polygon, shift=RENDER_SHIFT):
    encoded = [struct.unpack('<2f', struct.pack('<2f', x+shift[0], y+shift[1])) for x, y in polygon]
    return actual == encoded


def _check_visibility(index, carbon, source, mapping, groups, shift=RENDER_SHIFT):
    table, native, old = (vis.read(vis.payload_of(i), extended=e) for i, e in
                          ((index, True), (carbon, True), (source, False)))
    physics_shift = (-shift[1], shift[0])
    native_bounds, native_rows = c3_crossing.apply(native.boundaries, native.rows, physics_shift)
    require(Counter(c.kind for c in table.parts) == Counter(c.kind for c in native.parts),
            'visibility child schema changed')
    require(table.lod_offset == 40, 'LOD offset changed')
    expected_drive = list(native.drivable)+sorted({mapping[n] for n in old.drivable})
    require(list(table.drivable) == expected_drive and len(table.slots) == 704,
            'drivable array coverage/capacity differs (704 slots required)')
    require(not any(table.slots[len(table.drivable):]), 'nonzero unused drivable slots')
    require(table.loading == native.loading and table.selectors == native.selectors,
            'native loading/selector records changed')
    for kind in set(c.kind for c in native.parts)-{vis.DRIVE,vis.BOUNDARIES,vis.ROWS,vis.SELECTORS}:
        require([c.payload for c in table.parts if c.kind == kind] ==
                [c.payload for c in native.parts if c.kind == kind], 'opaque native visibility child differs')
    bounds = {b.number: b for b in table.boundaries}
    require(len(bounds) == len(table.boundaries), 'duplicate boundary identity')
    require([b.raw for b in table.boundaries[:len(native.boundaries)]] == [b.raw for b in native_bounds],
            'native boundaries changed')
    old_bounds = {b.number: b for b in old.boundaries}
    other = {mapping[b.number]: b for b in old.boundaries if not numbers.zone(b.number)}
    require(set(bounds) == {b.number for b in native.boundaries} | groups.keys() | other.keys(),
            'boundary completeness differs')
    for target, members in groups.items():
        rings = [old_bounds[n].vertices for n in members]
        candidates = []
        for order in itertools.permutations(rings):
            result = order[0]
            for ring in order[1:]:
                result = numbers.polygon_union(result, ring)
                if result is None:
                    break
            if result is not None:
                candidates.append(result)
        matched = False
        for polygon in candidates:
            expected = bytearray(old_bounds[members[0]].raw[:12]+bytes(12)+old_bounds[members[0]].raw[12:36])
            expected[:8] = bytes(8)
            struct.pack_into('<hB',expected,8,target,len(polygon))
            xs,ys = zip(*polygon)
            x0,y0,x1,y1 = min(xs),min(ys),max(xs),max(ys)
            struct.pack_into('<6f',expected,24,x0+shift[0],y0+shift[1],x1+shift[0],y1+shift[1],
                             (x0+x1)/2+shift[0],(y0+y1)/2+shift[1])
            expected += b''.join(struct.pack('<2f',x+shift[0],y+shift[1]) for x,y in polygon)
            cut, _ = c3_crossing.apply([Boundary(bytes(expected), True)], (), physics_shift)
            matched |= bounds[target].raw == cut[0].raw
        require(matched, f'boundary {target}: float32 source polygon union/bounds/center/header differs')
    for target, before in other.items():
        require(bounds[target].raw == before.translate(target, shift=shift).raw,
                'nonzone boundary translation/number differs')
    aliases = [n for b in table.boundaries for n in struct.unpack_from('<2h', b.raw, 12) if n]
    primary = [b.number for b in table.boundaries if numbers.zone(b.number)]
    identities = primary + aliases
    require(len(set(identities)) == len(identities) and len(identities) <= 780,
            'duplicate/excess zone identity')
    rows = {r.number: r for r in table.rows}
    require(len(rows) == len(table.rows), 'duplicate row identity')
    require([r.encode() for r in table.rows[:len(native.rows)]] == [r.encode() for r in native_rows],
            'native visibility row bytes/order changed')
    require(set(rows) == {r.number for r in native.rows} | groups.keys(), 'row completeness differs')
    source_rows = {r.number: r for r in old.rows}
    present = {s.number for s in index.sections}
    before_present = {s.number for s in source.sections}
    allowed_absences = Counter()
    for row in native.rows:
        allowed_absences.update((row.number,n) for n in row.entries if n not in present)
    for target, members in groups.items():
        expected = sorted({mapping[n] for member in members for n in source_rows[member].entries} | {2100})
        if physics_shift == c3_crossing.SHIFT:
            expected = sorted(set(expected) | set(c3_crossing.ROW_ADDITIONS.get(target, ())))
        require(list(rows[target].entries) == expected, f'row {target}: source entry union differs')
        for member in members:
            for n in source_rows[member].entries:
                require(n not in before_present or mapping[n] in present, 'new unresolved row reference')
                if n not in before_present and mapping[n] not in present:
                    allowed_absences[(target,mapping[n])] = 1
    absent = vis.absent_entries(table, present)
    require(absent == allowed_absences, 'row source presence/absence differs')
    require(set(table.drivable) <= set(identities) and set(identities) <= rows.keys(),
            'zone/drivable boundary or row unresolved')
    sizes = {s.number: s.size for s in index.sections}
    row_sizes = [(sum(sizes.get(n,0) for n in set(r.entries)|{2400,2600} if n != 2500),r.number)
                 for r in table.rows]
    worst, worst_row = max(row_sizes)
    require(worst <= POOL_BYTES, f'row {worst_row}: actual {worst} bytes exceeds {POOL_BYTES}')
    largest = max(len(r.entries) for r in table.rows)
    capacity = max(r.cap for r in table.rows)
    polygon = max(len(b.vertices) for b in table.boundaries)
    require(largest <= 127 and largest <= 384 and polygon <= 127, 'row/polygon signed cap exceeded')
    referenced = present | set(bounds) | set(aliases) | {n for r in table.rows for n in r.entries} | {n+40 for n in identities}
    extent = max(referenced)+1
    require(min(referenced) >= 0 and extent <= 2800, 'requested bitmap exceeded')
    return dict(zones=len(primary),zone_identities=len(identities),boundaries=len(bounds),rows=len(rows),
                largest_row=largest,row_margin=384-largest,signed_row_margin=127-largest,
                largest_row_capacity=capacity,row_capacity_margin=127-capacity,
                polygon_max=polygon,polygon_margin=127-polygon,bitmap_extent=extent,bitmap_margin=2800-extent,
                drivable=len(table.drivable),drivable_slots=len(table.slots),drivable_margin=len(table.slots)-len(table.drivable),
                worst_row=worst_row,worst_row_bytes=worst,row_byte_limit=POOL_BYTES,row_byte_margin=POOL_BYTES-worst,
                source_absent_entries=sum(absent.values()),new_unresolved_references=0)


def _digest(root):
    return root.kind, hashlib.sha256(root.payload).digest()


def _check_records(index, stream, carbon, cs, source, ms, mapping, actual_scenes, source_scenes, pack_homes,
                   shift=RENDER_SHIFT):
    """Source buckets reconstructed from recovered mappings, never the plan."""
    expected = defaultdict(list)
    for city, idx in ((False,carbon),(True,source)):
        for section in idx.sections:
            expected[mapping[section.number] if city else section.number].append((city,section))
    require([s.number for s in index.sections] == sorted(expected), 'record bucket coverage/order differs')
    providers, _ = classify.source_providers(source, ms)
    providers = providers,{s.number for s in source.sections}
    animations = texanim.inventory_source(source, ms)
    contributions = defaultdict(list)
    native_metadata_changes = native_tile_changes = 0
    native_payload_bytes = native_metadata_bytes = 0
    native_prefix_changes = native_added_bytes = native_records_changed = 0
    for section in carbon.sections:
        for root in chunks(read_section(cs, section)):
            if root.kind == SCENE:
                scene = scene_data(root)
                contributions[scene.number].append((scene,True))
    for old, scene, target in source_scenes:
        contributions[target].append((scene,False))
    require(contributions.keys() == actual_scenes.keys(), 'scenery completeness differs')
    native_scene_changes = 0
    for logical, sources in contributions.items():
        home, actual = actual_scenes[logical]
        expected_home = logical if logical in expected else logical+40
        require(home == expected_home, 'scenery physical owner differs from base/partner presence')
        native_scene_changes += _check_scene_sources(actual, sources, logical, shift)
    for section in index.sections:
        actual_data = read_section(stream,section)
        members = expected[section.number]
        first_moved, first = members[0]
        raw = bytearray(first.raw)
        if first.number != section.number:
            raw[:4] = f'{chr(64+section.number//100)}{section.number%100:02d}'.encode()+b'\0'
            struct.pack_into('<h',raw,8,section.number)
            struct.pack_into('<I',raw,36,10000+section.number)
        struct.pack_into('<III',raw,20,section.offset,section.size,section.size)
        if first_moved:
            x,y,z = first.position
            struct.pack_into('<3f',raw,40,x+shift[0],y+shift[1],z)
        require(section.raw == raw, 'record metadata changed outside mapped fields')
        if not first_moved:
            native_metadata_changes += sum(a != b for a,b in zip(first.raw,section.raw))
            native_metadata_bytes += 92
        wanted = []
        for moved, before in members:
            data = read_section(ms if moved else cs,before)
            if not moved:
                native_payload_bytes += len(data)
                prefix = actual_data[:len(data)]
                require(len(prefix) == len(data), 'native record truncated')
                if data != prefix:
                    native_prefix_changes += sum(a != b for a,b in zip(data,prefix))
                joined_scene = any(c.kind == SCENE and len(contributions[scene_data(c).number]) > 1
                                   for c in chunks(data))
                if not joined_scene:
                    unchanged = bytearray(data)
                    for c in chunks(data):
                        if c.kind == TILE:
                            unchanged[c.offset:c.offset+4] = bytes(4)
                    require(prefix == unchanged, 'native record bytes changed outside retired tile kinds')
                require(len(members) > 1 or len(actual_data) == len(data), 'native record has unexpected added bytes')
                native_added_bytes += len(actual_data)-len(data)
                native_records_changed += int(actual_data != data)
                for c in chunks(data):
                    if c.kind == PACK:
                        require(pack_homes[u32(region.collision_body(c),4)] == before.number,
                                'native collision pack physical owner changed')
                native_tile_changes += sum(sum(a != b for a,b in zip(struct.pack('<I',TILE),bytes(4)))
                                           for c in chunks(data) if c.kind == TILE)
                roots = chunks(data)
            else:
                data,_ = convert.convert_section(data,before.number,source_number=before.number,
                            shift=shift,providers=providers,animation_inventory=animations)
                if before.number == 2400:
                    extra = convert.Builder(len(data))
                    dome.append(extra, Path(ms).parent)
                    data += extra.data
                roots = [mapped_provider(c,section.number) for c in chunks(data)]
            wanted.extend(_digest(c) for c in roots if c.kind not in (0,SCENE,PACK,TILE,props.SPAWNS))
        actual = []
        for root in chunks(actual_data):
            if root.kind == 0x80036000:
                require(events.decode_events(root).section == section.number, 'event owner reference unresolved')
            elif root.kind == 0x3bc00:
                require(emitters.decode_emitters(root).section == section.number, 'emitter owner reference unresolved')
            if root.kind not in (0,SCENE,PACK,TILE,props.SPAWNS):
                actual.append(_digest(root))
        require(actual == wanted, f'record {section.number}: provider bytes/source bucket differs')
    return dict(metadata_changed_bytes=native_metadata_changes,metadata_bytes=native_metadata_bytes,
                payload_source_bytes=native_payload_bytes,payload_array_and_kind_changed_bytes=native_scene_changes+native_tile_changes,
                payload_prefix_changed_bytes=native_prefix_changes,payload_added_bytes=native_added_bytes,
                records_with_changed_payload=native_records_changed,
                records_total=len(carbon.sections),records_byte_exact=len(carbon.sections)-native_records_changed,
                scenery_selector_changed_bytes=native_scene_changes,retired_tile_kind_changed_bytes=native_tile_changes,
                unchanged_provider_payloads=True,
                explanation='Literal comparisons count differences within each original record extent and additions separately. '
                            'Source correspondence verifies all original arrays/providers: only shared-resident tree selectors '
                            'and nine retired tile kinds change. Envelope lengths/alignment change around inserted resident '
                            'arrays; index records change stream extents. Native global zone records stay exact in each '
                            'bucket, and native marker/barrier lists stay exact prefixes; optional Rockport tables append.')


def _check_collision_sources(result, carbon, source, shift=DEFAULT_SHIFT):
    """Exact rational footprint oracle, not the grid merger's float binning."""
    co, spacing, cr, cc = grid.grid_fields(carbon.descriptor)
    so, old_spacing, sr, sc = grid.grid_fields(source.descriptor)
    ox = co[0]+min(0,math.floor((so[0]+shift[0]-co[0])/spacing))*spacing
    oz = co[2]+min(0,math.floor((so[2]+shift[1]-co[2])/spacing))*spacing
    columns = math.ceil((max(co[0]+cc*spacing,so[0]+shift[0]+sc*old_spacing)-ox)/spacing)
    rows = math.ceil((max(co[2]+cr*spacing,so[2]+shift[1]+sr*old_spacing)-oz)/spacing)
    expected_descriptor = bytearray(carbon.descriptor)
    struct.pack_into('<3f',expected_descriptor,0,ox,co[1],oz)
    struct.pack_into('<2I',expected_descriptor,24,rows,columns)
    expected_descriptor[32:36] = bytes(4)
    require(result.descriptor == expected_descriptor, 'grid descriptor union differs')
    require(result.rectangle == struct.pack('<5H',2600,0,0,columns,rows), 'rectangle union dimensions differ')
    used = set(carbon.packs) | set(source.packs)
    pack_mapping = {n:n for n in source.packs}
    for n in sorted(set(carbon.packs) & set(source.packs)):
        target = next(v for v in range(1,2700) if v not in used)
        used.add(target)
        pack_mapping[n] = target
    packs = {u32(p,4):p for p in result.packs}
    require(packs.keys() == set(carbon.packs) | set(pack_mapping.values()), 'pack completeness differs')
    for key, pack in carbon.packs.items():
        require(packs[key] == pack, 'native collision pack bytes changed')
    for old, pack in source.packs.items():
        expected = bytearray(pack)
        struct.pack_into('<I',expected,4,pack_mapping[old])
        tag = region.collision_tags(pack[16:],grid.ARTI)[grid.CI]
        for p in range(16+tag[3],16+tag[3]+64*tag[2],64):
            # Both physics axes contribute through the inverse basis. The
            # original local geometry and height components stay untouched.
            for axis in range(3):
                value = struct.unpack_from('<f',pack,p+48+axis*4)[0]
                basis_x = struct.unpack_from('<f',pack,p+axis*4)[0]
                basis_z = struct.unpack_from('<f',pack,p+32+axis*4)[0]
                struct.pack_into('<f',expected,p+48+axis*4,value-basis_x*shift[0]-basis_z*shift[1])
        require(packs[pack_mapping[old]] == expected, 'source collision pack translation/id differs')
    expected_cells = {}
    native_cells, source_cells = set(), set()
    for city, delta, native in ((carbon,(0.,0.),True),(source,shift,False)):
        origin, step, _, cols = grid.grid_fields(city.descriptor)
        for record in city.cells:
            row,col = divmod(struct.unpack_from('<H',record,4)[0],cols)
            x,z = Fraction(origin[0])+Fraction(delta[0])+col*Fraction(step)-Fraction(ox), Fraction(origin[2])+Fraction(delta[1])+row*Fraction(step)-Fraction(oz)
            refs = [[v[0] for v in struct.iter_unpack('<I',fam)] for fam in grid.families(record)]
            if not native:
                refs[0] = [(pack_mapping[v>>16]<<16)|(v&65535) for v in refs[0]]
                refs[3] = [v+carbon.segments for v in refs[3]]
            for rr in range(math.floor(z/Fraction(spacing)),math.ceil((z+Fraction(step))/Fraction(spacing))):
                for col in range(math.floor(x/Fraction(spacing)),math.ceil((x+Fraction(step))/Fraction(spacing))):
                    cid = rr*columns+col
                    (native_cells if native else source_cells).add(cid)
                    if cid not in expected_cells:
                        expected_cells[cid] = record[:4],[list(f) for f in refs]
                    else:
                        prefix,dest = expected_cells[cid]
                        require(prefix == record[:4], 'collision source prefix ambiguity')
                        for a,b in zip(dest,refs):
                            a.extend(v for v in b if v not in a)
                    if not native:
                        prefix,dest = expected_cells[cid]
                        expected_cells[cid] = prefix,[list(dict.fromkeys(f)) for f in dest]
    body = result.tile[16:]
    records = region.collision_cells(body,region.collision_tags(body,grid.ARTI)[grid.CGCN])
    actual = {struct.unpack_from('<H',r,4)[0]:r for r in records}
    require(actual.keys() == expected_cells.keys(), 'collision cell completeness differs')
    for cid, record in actual.items():
        prefix,refs = expected_cells[cid]
        require(record[:4] == prefix, 'collision cell prefix differs')
        require([[v[0] for v in struct.iter_unpack('<I',fam)] for fam in grid.families(record)] == refs,
                'collision source family/offset differs')
    return pack_mapping,dict(rows=rows,columns=columns,slots=rows*columns,slot_margin=65536-rows*columns,
                              native_cells=len(native_cells),source_cells=len(source_cells),occupied=len(actual))


def _grounded(world, nodes):
    ids, heights = [], []
    for i,(x,y,z) in enumerate(nodes):
        h = world.height(x,z,y)
        heights.append(h)
        if h is not None and 0 <= y-h <= 2.:
            ids.append(i)
    return ids,heights


def _check_ground(index, stream, carbon, cs, source, ms, shift=DEFAULT_SHIFT):
    combined = ground.World(index,stream)
    report = {}
    for city,old,old_stream,delta in (('palmont',carbon,cs,(0.,0.)),('rockport',source,ms,shift)):
        nodes = ground.road_nodes(old)
        before,bh = _grounded(ground.World(old,old_stream),nodes)
        after,ah = _grounded(combined,[(x+delta[0],y,z+delta[1]) for x,y,z in nodes])
        require(before == after, f'{city}: exact-offset grounded node list changed ({len(before)} -> {len(after)})')
        require(all((a is None) == (b is None) for a,b in zip(bh,ah)), f'{city}: missing-height list changed')
        maximum = max((abs(a-b) for a,b in zip(bh,ah) if a is not None),default=0.)
        require(maximum <= .002, f'{city}: collision height changed')
        report[city] = dict(before=len(before),after=len(after),same_nodes=True,max_height_difference_m=maximum)
    # Explicitly measure the road writer's quantization, without loosening the
    # exact-offset geometry proof or substituting the rounded query's list.
    native_count = len(ground.road_nodes(carbon))
    serialized = ground.road_nodes(index)[native_count:]
    rounded_ids,_ = _grounded(combined,serialized)
    report['rockport_serialized_float32'] = dict(grounded=len(rounded_ids),
                exact_offset_grounded=report['rockport']['after'],same_list_as_exact_offset=rounded_ids == after,
                lost_from_exact_offset=len(set(after)-set(rounded_ids)),
                gained_from_exact_offset=len(set(rounded_ids)-set(after)))
    return report


def _merge_globals(carbon, source, mapping, shift):
    """Reuse identity allocation; replace spatial bytes from a fresh conversion.

    The global merger has a fixed placement. Reading original source records
    again avoids applying a second float32 translation to its rounded output.
    """
    merged = c1_zones.merge(carbon, source, mapping)
    if shift == DEFAULT_SHIFT:
        return merged
    base = zone_tables.read(merged)
    native = zone_tables.read(zone_tables.select(carbon))
    moved = zone_tables.read(zone_tables.convert(source, shift=shift, track=2000))
    polygons = []
    for kind in range(zone_tables.BUCKETS):
        bucket = [z for z in base.zones if z.kind == kind]
        count = sum(z.kind == kind for z in native.zones)
        incoming = [z for z in moved.zones if z.kind == kind]
        require(len(bucket) == count+len(incoming), 'global placement bucket count differs')
        polygons.extend(bucket[:count])
        for mapped, fresh in zip(bucket[count:], incoming):
            if kind == 6:
                fresh = replace(fresh, header=fresh.header[:48]+mapped.header[48:64]+fresh.header[64:])
            polygons.append(fresh)
    result = replace(base, zones=tuple(polygons), markers=native.markers+moved.markers,
                     barriers=native.barriers+moved.barriers).encode()
    zone_tables.check(result)
    return result


def _canonical_globals(actual, carbon, source, shift):
    """Check new spatial bytes, then reuse the fixed-placement provenance reader.

    Only fields already compared to independently rounded original coordinates
    are replaced by their default-placement encodings. Every unchecked byte,
    native prefix, identity and ordering remains for c1_zones.reread to prove.
    No merger, converter, inverse translation or proof sidecar is consulted.
    """
    zone_tables.check(actual)
    table = zone_tables.read(actual)
    native = zone_tables.read(zone_tables.select(carbon))
    original = zone_tables.read(zone_tables.select(source))
    render = (shift[1], -shift[0])
    def spatial(before, written, offsets, reason):
        require(len(before) == len(written), reason)
        restored = bytearray(written)
        for axis, locations in enumerate(offsets):
            for p in locations:
                value = struct.unpack_from('<f', before, p)[0]
                expected = struct.pack('<f', value+render[axis]) if render[axis] else before[p:p+4]
                require(written[p:p+4] == expected, reason)
                restored[p:p+4] = (struct.pack('<f', value+RENDER_SHIFT[axis])
                                   if RENDER_SHIFT[axis] else before[p:p+4])
        return bytes(restored)
    polygons = []
    for kind in range(zone_tables.BUCKETS):
        bucket = [z for z in table.zones if z.kind == kind]
        incoming = [z for z in original.zones if z.kind == kind]
        count = sum(z.kind == kind for z in native.zones)
        require(len(bucket) == count+len(incoming), f'bucket {kind}: incomplete merged zone count')
        polygons.extend(bucket[:count])
        for before, written in zip(incoming, bucket[count:]):
            raw = spatial(before.encode(), written.encode(),
                          ((4,32,40,*range(68,len(before.encode()),8)),
                           (8,36,44,*range(72,len(before.encode()),8))),
                          f'bucket {kind}: Rockport zone translation/identity/source bytes differ')
            polygons.append(zone_tables.Zone(raw[:68], raw[68:]))
    arrays = []
    for name, offsets in (('markers', ((16,),(20,))), ('barriers', ((0,8),(4,12)))):
        before, written, prefix = getattr(original,name), getattr(table,name), getattr(native,name)
        require(len(written) == len(prefix)+len(before), f'incomplete merged {name[:-1]} count')
        arrays.append(written[:len(prefix)]+tuple(spatial(a,b,offsets,
                      f'Rockport {name[:-1]} translation/source bytes differ')
                      for a,b in zip(before,written[len(prefix):])))
    return replace(table, zones=tuple(polygons), markers=arrays[0], barriers=arrays[1]).encode()


def _check_globals(index, carbon, source, mapping, shift=DEFAULT_SHIFT):
    """Accept exactly native tables or a complete source-proven merged form."""
    require([c.kind for c in index.parts if c.kind] == [c.kind for c in carbon.parts if c.kind],
            'native global chunk kinds/order changed')
    replaced = {vis.CONTAINER, 0x34110, MAP, *zone_tables.KINDS, *props.GLOBALS}
    require([_digest(c) for c in index.parts if c.kind and c.kind not in replaced] ==
            [_digest(c) for c in carbon.parts if c.kind and c.kind not in replaced],
            'native global scaffold changed')
    actual, native = zone_tables.select(index), zone_tables.select(carbon)
    if [_digest(c) for c in actual] == [_digest(c) for c in native]:
        return dict(**zone_tables.check(actual), mode='off')
    if shift != DEFAULT_SHIFT:
        actual = _canonical_globals(actual, carbon, source, shift)
    return c1_zones.reread(actual, carbon, source, mapping)


def check(directory, mw_root=DEFAULT_MW, carbon_root=DEFAULT_CARBON, *, shift=DEFAULT_SHIFT, _link=True):
    """Independently re-read the written pair and original source provenance."""
    shift = _physics_shift(shift)
    if _link and shift == c3_crossing.SHIFT:
        import c3_link
        report = c3_link.check(directory, mw_root, carbon_root)
        index,stream,_ = load_index(Path(directory)/'TRACKS','L5RA')
        native,cs,_ = load_index(carbon_root,'L5RA')
        report['sky_dome'] = dome.check(index, stream, mw_root)
        report['props'].update(props.check_native(index,stream,native,cs,removed=(18842,)))
        return report
    render = (shift[1], -shift[0])
    tracks = Path(directory)/'TRACKS'
    index,stream,raw_index = load_index(tracks,'L5RA')
    carbon,cs,_ = load_index(carbon_root,'L5RA')
    source,ms,_ = load_index(mw_root,'L2RA')
    require(index.encode() == raw_index, 'written index round trip differs')
    position = 0
    scenes,tiles,packs = {},[],[]
    pack_homes = {}
    for section in index.sections:
        position = (position+2047)//2048*2048
        require(section.offset == position and section.size > 0 and u32(section.raw,28) == section.size,
                'record offset/plain extent differs')
        position += section.size
        for root in chunks(read_section(stream,section)):
            if root.kind == SCENE:
                scene = scene_data(root)
                require(scene.number not in scenes, 'duplicate logical scenery identity')
                _check_scene_tree(scene)
                scenes[scene.number] = section.number,scene
            elif root.kind == TILE:
                require(section.number == 2600, 'merged tile is not always resident')
                tiles.append(region.collision_body(root))
            elif root.kind == PACK:
                pack = region.collision_body(root)
                key = u32(pack,4)
                require(key not in pack_homes, 'duplicate collision pack id')
                pack_homes[key] = section.number
                packs.append(pack)
    require(position == stream.stat().st_size, 'unindexed stream tail')
    require(len(tiles) == 1, 'expected one merged collision tile')
    dome_report = dome.check(index, stream, mw_root)
    native_inventory = numbers.inventory((carbon,cs),True)
    native_numbers = numbers.source_numbers(native_inventory)
    mapping,groups,source_scenes = _recover_mapping(source,ms,scenes,native_numbers,render)
    prop_report = props.check(index,stream,source,ms,carbon,cs,mapping=mapping,shift=shift)
    zone_report = _check_globals(index,carbon,source,mapping,shift)
    visibility_report = _check_visibility(index,carbon,source,mapping,groups,render)
    native_changes = _check_records(index,stream,carbon,cs,source,ms,mapping,scenes,source_scenes,pack_homes,render)
    raw = region.collision_body(region.one(index.parts,MAP))
    tags = region.collision_tags(raw,grid.CDAT)
    descriptor = grid.tag_data(raw,tags[grid.CGRD])
    rectangles = [r for key,tag in tags.items() if key>>16 == 0x636c
                  for r in struct.iter_unpack('<5H',grid.tag_data(raw,tag))]
    require(len(rectangles) == 1, 'expected one grid rectangle')
    result = grid.Grid(descriptor,struct.pack('<5H',*rectangles[0]),tiles[0],tuple(packs),{}, {})
    grid_report = grid.check(result,cell_section=2600,tile_section=2600)
    native_grid,source_grid = grid.read_city(carbon,cs),grid.read_city(source,ms)
    pack_mapping,grid_counts = _check_collision_sources(result,native_grid,source_grid,shift)
    require(all(pack_homes[key] == 2600 for key in pack_mapping.values()), 'source pack is not always resident')
    # Restore only the separately verified CDat fields for the road checker,
    # which intentionally demands an otherwise identical native container.
    native_raw = region.collision_body(region.one(carbon.parts,MAP))
    old_tags = region.collision_tags(native_raw,grid.CDAT)
    require(tags.keys() == {grid.CGRD,grid.RECT,0x636f0000}, 'CDat directory keys differ')
    sanitized = bytearray(raw)
    group = _group_offset(native_raw,grid.CDAT)
    require(_group_offset(raw,grid.CDAT) == group and u32(raw,group+8) == 3,
            'CDat group directory differs')
    sanitized[group+8:group+12] = native_raw[group+8:group+12]
    for key in (grid.CGRD,grid.RECT):
        tag = old_tags[key]
        q,flags,count,p = tag
        require(tags[key] == tag, 'CDat descriptor/rectangle directory differs')
        if key == grid.CGRD:
            sanitized[p:p+40] = native_raw[p:p+40]
        else:
            sanitized[p:p+10] = native_raw[p:p+10]
    q = old_tags[grid.RECT][0]+16
    require(tags[0x636f0000] == (q,old_tags[0x636f0000][1],0,0), 'override directory differs')
    sanitized[q:q+16] = native_raw[q:q+16]
    road_report = roads.check(bytes(sanitized),native_raw,
                             region.collision_body(region.one(source.parts,MAP)), shift=shift)
    grounding = _check_ground(index,stream,carbon,cs,source,ms,shift)
    files = {}
    for path in (tracks/'L5RA.BUN',stream):
        digest = hashlib.sha256()
        with path.open('rb') as f:
            for block in iter(lambda:f.read(4<<20),b''):
                digest.update(block)
        files[path.name] = dict(bytes=path.stat().st_size,sha256=digest.hexdigest())
    require(len(index.sections) == 1433 and visibility_report['zone_identities'] == 780 and
            visibility_report['rows'] == 780 and visibility_report['drivable'] == 641,
            'combined world census differs from accepted source set')
    return dict(records=len(index.sections),duplicate_ids=0,new_unresolved_references=0,
                duplicate_counts=dict(records=0,zone_identities=0,scenery=0,packs=0,
                                      road_nodes=0,road_segments=0,cells=0),
                visibility=visibility_report,roads=road_report,grid={**grid_report,**grid_counts,
                    'tile_bytes':len(tiles[0]),'packs_limit':2700,'pack_margin':2699-len(packs),
                    'largest_pack_id':max(pack_homes),'pack_id_margin':2699-max(pack_homes)},
                grounded=grounding,props=prop_report,palmont_bytes=native_changes,files=files,zones=zone_report,
                sky_dome=dome_report,
                unverified=['native loader acceptance and resident-tile binding','two-position pool peaks/fragmentation'])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mw-root',type=Path,default=DEFAULT_MW)
    parser.add_argument('--carbon-root',type=Path,default=DEFAULT_CARBON)
    parser.add_argument('--out',type=Path,required=True,help='new directory outside all checkouts')
    parser.add_argument('--shift', nargs=2, type=float, default=DEFAULT_SHIFT, metavar=('X', 'Z'),
                        help='physics translation in metres (default: 20480 0)')
    parser.add_argument('--zones',action='store_true',help='append translated Rockport global tables')
    args = parser.parse_args(argv)
    if not all((root/name).is_file() for root,base in ((args.mw_root,'L2RA'),(args.carbon_root,'L5RA'))
               for name in (base+'.BUN','STREAM'+base+'.BUN')) or not all(
                   (root.parent/'GLOBAL/attributes.bin').is_file() for root in (args.mw_root,args.carbon_root)):
        print('SKIP: private track archives absent')
        return 3
    report = build(args.mw_root,args.carbon_root,args.out,zones=args.zones,shift=args.shift)
    print(json.dumps(report,sort_keys=True))
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except FormatError as error:
        sys.exit(str(error))
