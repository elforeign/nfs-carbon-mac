"""Add missing scenery-physics collections using destination vault serialization.

004682B0 reads two u16 type counts and the 0x40 inline flag. MASS is
layout +16; StringKey is hash32/text-pointer (8 bytes), not the source's
hash64/hash32/text-pointer (16 bytes). Existing buffers retain their offsets.
"""
import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import struct
import sys

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / 'vaults'))
from vaultlib import hash32
from formats import require, u32
from gameplay import Pack, align, chunk
from merge import DEFAULT_MW, DEFAULT_CARBON

SMACKABLE = hash32('smackable')
COLLECTION, CLASS = 0x8e112eb7, 0x5e970cbc
STRINGKEY, TEXT, REFSPEC = 0xa502a824, 0xa3f0c234, 0x2b936eb7
MISSING = ('mediummetalpost', 'largemetalpost', 'golfcart', 'glass',
           'lightwoodenpost', 'propanetank', 'sailboat', 'hugemetalbreakable',
           'wood', 'mediumwoodenpost')


@dataclass(frozen=True)
class Value:
    raw: bytes
    count: int = 1
    strings: tuple = ()  # (byte offset, terminated text); all other pointers null


class Database:
    """Bounds-checked db reader, with inherited fields and both collection ABIs."""
    def __init__(self, raw, modern):
        self.pack = Pack(raw)
        _, self.binary, self.raw = self.pack.vaults['db']
        self.buffers = (self.raw, self.binary)
        self.modern = modern
        self.chunks = {}
        off = 0
        while off < len(self.raw):
            require(off+8 <= len(self.raw), 'truncated attributes chunk')
            kind, size = struct.unpack_from('<II', self.raw, off)
            require(size >= 8 and off+size <= len(self.raw) and kind not in self.chunks,
                    'invalid attributes chunk extent/identity')
            self.chunks[kind] = (off, size)
            off += size
        require((0x56657273 in self.chunks) == modern, 'attributes vault revision differs')
        self.exports = []
        off, size = self.chunks[0x4578704e]
        count = u32(self.raw, off+8)
        stride = 16 if modern else 20
        require(12+count*stride <= size, 'attributes export extent')
        for i in range(count):
            r = struct.unpack_from('<4I' if modern else '<5I', self.raw, off+12+i*stride)
            require(r[-1]+r[-2] <= len(self.raw), 'attributes export data extent')
            self.exports.append((r[0], r[1], r[-2], r[-1]))
        self.fixups, self.pointer_rows = {}, []
        off, size = self.chunks[0x5074724e]
        base = 0
        for at in range(off+8, off+size-11, 12):
            row = pos, kind, dep, value = struct.unpack_from('<IHHI', self.raw, at)
            if not kind:
                break
            self.pointer_rows.append(row)
            if kind == 2:
                base = dep
            else:
                require((base, pos) not in self.fixups, 'duplicate attributes pointer')
                self.fixups[base, pos] = (kind, dep, value)
        else:
            require(False, 'attributes pointer terminator absent')
        self.collections, self.defs, self.layout_size = {}, {}, None
        self.identities = set()
        for export, kind, size, off in self.exports:
            if kind == CLASS and u32(self.raw, off) == SMACKABLE:
                count = struct.unpack_from('<H', self.raw, off+8)[0]
                dep, pos = self.pointer(0, off+12)
                self.defs = {r[0]: r[1:] for r in struct.iter_unpack(
                    '<IIHHHBB', self.span(dep, pos, count*16))}
                self.layout_size = struct.unpack_from('<H', self.raw, off+(24 if modern else 16))[0]
            elif kind == COLLECTION:
                require(size >= 32, 'short attributes collection')
                key, cls = struct.unpack_from('<II', self.raw, off)
                self.identities.add((cls, key))
                if cls != SMACKABLE:
                    continue
                require(key not in self.collections, 'duplicate smackable key')
                nt = struct.unpack_from('<H' if modern else '<I', self.raw, off+24)[0]
                padded = struct.unpack_from('<H', self.raw, off+26)[0] if modern else nt
                require(padded == (align(nt, 2) if modern else nt), 'collection type padding')
                count = u32(self.raw, off+20)
                require(32+padded*4+count*12 <= size, 'collection entries extent')
                types = struct.unpack_from('<%dI' % nt, self.raw, off+32)
                entries = {}
                for i in range(count):
                    at = off+32+padded*4+i*12
                    field, word, ti, flags, reserved = struct.unpack_from('<IIHBB', self.raw, at)
                    require(ti < nt and not reserved and field not in entries,
                            'collection entry type/reserved/duplicate')
                    entries[field] = (at, types[ti], flags)
                self.collections[key] = (off, size, entries)
        require(self.defs and self.layout_size, 'smackable class absent')

    def span(self, dep, pos, size):
        require(dep in (0, 1) and 0 <= pos <= len(self.buffers[dep]) and
                0 <= size <= len(self.buffers[dep])-pos, 'attributes value extent')
        return self.buffers[dep][pos:pos+size]

    def pointer(self, dep, pos):
        fix = self.fixups.get((dep, pos))
        if fix is None or fix[0] in (1, 5):
            return None
        require(fix[0] == 3 and fix[1] in (0, 1), 'external attributes pointer')
        self.span(fix[1], fix[2], 0)
        return fix[1:]

    def value(self, key, field, seen=()):
        require(key not in seen and len(seen) < 32, 'attribute inheritance cycle/depth')
        off, size, entries = self.collections[key]
        typ, at, esz, maximum, flags, alignment = self.defs[field]
        target = None
        if flags & 2:
            p = self.pointer(0, off+28)
            if p:
                self.span(*p, self.layout_size)
                target = p[0], p[1]+at
        elif field in entries:
            at, etype, fl = entries[field]
            require(etype == typ, 'attribute entry/class type differs')
            target = (0, at+4) if fl & (0x40 if self.modern else 0x20) else self.pointer(0, at+4)
            require(target is not None, 'attribute value pointer absent')
        if target is None:
            parent = u32(self.raw, off+8)
            return self.value(parent, field, seen+(key,)) if parent else None
        dep, pos = target
        count = 1
        if flags & 1:
            alloc, count, stride, enc = struct.unpack('<4H', self.span(dep, pos, 8))
            require(count <= alloc <= maximum and stride == esz, 'attribute array shape')
            pos += 8+(8 if enc & 0x8000 else 0)
        raw = self.span(dep, pos, count*esz)
        strings = []
        for (base, at), fix in self.fixups.items():
            if base != dep or not pos <= at < pos+len(raw):
                continue
            if fix[0] in (1, 5):
                require(raw[at-pos:at-pos+4] == bytes(4), 'nonnull source null pointer')
                continue
            require(typ in (TEXT, STRINGKEY) and fix[0] == 3, 'value pointer shape not decoded')
            td, tp = self.pointer(dep, at)
            end = self.buffers[td].find(b'\0', tp)
            require(end >= tp, 'unterminated attributes text')
            strings.append((at-pos, self.span(td, tp, end-tp+1)))
        return Value(raw, count, tuple(sorted(strings)))


def translated(value, source_def, target_def):
    """Translate only classified field differences, including nested strings."""
    typ, _, src_size, maximum, flags, _ = source_def
    dt, _, dst_size, dm, df, _ = target_def
    require(typ == dt and maximum == dm and flags & 1 == df & 1,
            'unclassified attribute type/count change')
    if typ == STRINGKEY:
        require((src_size, dst_size) == (16, 8), 'StringKey size change')
        raw = b''.join(struct.pack('<II', u32(value.raw, i*16+8), 0) for i in range(value.count))
        strings = tuple((at//16*8+4, text) for at, text in value.strings)
        require(all(at % 16 == 12 for at, _ in value.strings), 'StringKey pointer offset')
        for at, text in strings:
            require(u32(raw, at-4) == hash32(text[:-1]), 'StringKey hash/text differs')
        return Value(raw, value.count, strings)
    require(src_size == dst_size, 'unclassified field size change')
    return value


def convert(source, destination):
    src, dst = Database(source, False), Database(destination, True)
    require(dst.defs[hash32('MASS')][1] == 16 and dst.defs[0x5aab860f][2] == 8,
            'destination smackable ABI differs')
    require(src.defs[hash32('MASS')][1] == 20 and src.defs[0x5aab860f][2] == 16,
            'source smackable ABI differs')
    missing = {hash32(n) for n in MISSING}
    require(missing <= src.collections.keys() and not missing & dst.collections.keys(),
            'expected missing smackable set changed')
    data_off, data_size = dst.chunks[0x4461744e]
    data = bytearray(dst.raw[data_off+8:data_off+data_size])
    binary = bytearray(dst.binary)
    fixes, additions = [(0, 2, 0, 0)], []

    def allocate(value, alignment):
        binary.extend(bytes(align(len(binary), alignment)-len(binary)))
        start = len(binary)
        binary.extend(value.raw)
        for at, text in value.strings:
            text_at = len(binary)
            binary.extend(text)
            fixes.extend(((0, 2, 1, 0), (start+at, 3, 1, text_at), (0, 2, 0, 0)))
        return start

    for name in MISSING:
        key = hash32(name)
        values = {}
        for field, definition in src.defs.items():
            require(field in dst.defs, 'source field absent from destination class')
            value = src.value(key, field)
            if value is not None:
                values[field] = translated(value, definition, dst.defs[field])
        # RefSpec is {class, collection, cached-pointer}; cache starts null.
        rigid = values[0x7c90bb38].raw
        require(len(rigid) == 12 and not u32(rigid, 8) and
                struct.unpack_from('<II', rigid) in dst.identities,
                'rigidbodyspecs reference absent from destination')
        fields = [f for f in sorted(values) if not dst.defs[f][4] & 2]
        types = list(dict.fromkeys(dst.defs[f][0] for f in fields))
        data.extend(bytes(align(data_off+8+len(data), 8)-data_off-8-len(data)))
        off = data_off+8+len(data)
        body = bytearray(struct.pack('<6IHHI', key, SMACKABLE, 0, len(fields), 0, len(fields),
                                     len(types), align(len(types), 2), 0))
        body.extend(struct.pack('<%dI' % len(types), *types))
        body.extend(bytes(align(len(body), 8)-len(body)))
        layout = bytearray(dst.layout_size)
        layout_strings = []
        for f, value in values.items():
            typ, at, size, maximum, flags, alignment = dst.defs[f]
            if flags & 2:
                require(not flags & 1 and len(value.raw) == size and at+size <= len(layout),
                        'layout field extent/array')
                layout[at:at+size] = value.raw
                layout_strings.extend((at+p, text) for p, text in value.strings)
        layout_at = allocate(Value(bytes(layout), strings=tuple(layout_strings)), 4)
        fixes.append((off+28, 3, 1, layout_at))
        for f in fields:
            typ, _, size, maximum, flags, alignment = dst.defs[f]
            value = values[f]
            if flags & 1:
                payload = Value(struct.pack('<4H', value.count, value.count, size, 0)+value.raw,
                                strings=tuple((8+p, text) for p, text in value.strings))
                at = allocate(payload, max(4, 1 << alignment))
                fl, word = 2, 0
            elif size <= 4 and not value.strings:
                fl, word, at = 0x40, int.from_bytes(value.raw, 'little'), None
            else:
                at = allocate(value, max(4, 1 << alignment))
                fl, word = 0, 0
            if at is not None:
                fixes.append((off+len(body)+4, 3, 1, at))
            body.extend(struct.pack('<IIHBB', f, word, types.index(typ), fl, 0))
        export = hash32('smackable/'+name)
        require(export not in {r[0] for r in dst.exports}, 'attributes export collision')
        additions.append((export, COLLECTION, len(body), off))
        data.extend(body)
    data.extend(bytes(align(data_off+8+len(data))-data_off-8-len(data)))
    exports = dst.exports+additions
    exp = struct.pack('<I', len(exports))+b''.join(struct.pack('<4I', *r) for r in exports)
    exp += bytes(align(8+len(exp))-8-len(exp))
    ptr = b''.join(struct.pack('<IHHI', *r) for r in dst.pointer_rows+fixes+[(0, 0, 0, 0)])
    ptr += bytes(align(8+len(ptr))-8-len(ptr))
    out = bytearray()
    for kind, (off, size) in dst.chunks.items():
        payload = {0x4461744e: data, 0x4578704e: exp, 0x5074724e: ptr}.get(kind)
        out.extend(dst.raw[off:off+size] if payload is None else chunk(kind, payload))
    pack = bytearray(destination)
    pack.extend(bytes(align(len(pack))-len(pack)))
    bo = len(pack)
    pack.extend(binary)
    pack.extend(bytes(align(len(pack))-len(pack)))
    vo = len(pack)
    pack.extend(out)
    struct.pack_into('<4I', pack, dst.pack.vaults['db'][0]+4, len(binary), len(out), bo, vo)
    result = bytes(pack)
    verify(source, destination, result)
    return result


def verify(source, destination, result):
    src, dst, got = Database(source, False), Database(destination, True), Database(result, True)
    require(got.collections.keys() == dst.collections.keys() | {hash32(n) for n in MISSING},
            'added collection identities differ')
    for key, (off, size, _) in dst.collections.items():
        require(got.raw[off:off+size] == dst.raw[off:off+size], 'native collection changed')
    do, ds = dst.chunks[0x4461744e]
    require(got.raw[do+8:do+ds] == dst.raw[do+8:do+ds], 'native data buffer changed')
    require(got.binary[:len(dst.binary)] == dst.binary, 'native value buffer changed')
    require(got.pointer_rows[:len(dst.pointer_rows)] == dst.pointer_rows, 'native fixups changed')
    require(got.exports[:len(dst.exports)] == dst.exports, 'native exports changed')
    for name in MISSING:
        key = hash32(name)
        for field in src.defs:
            value = src.value(key, field)
            expected = translated(value, src.defs[field], dst.defs[field]) if value else None
            require(got.value(key, field) == expected, f'resolved field differs: {name}/{field:08X}')
    return dict(added=len(MISSING), native_unchanged=len(dst.collections),
                mass_offset=dst.defs[hash32('MASS')][1], stringkey_bytes=dst.defs[0x5aab860f][2])


def write_overlay(mw_root, carbon_root, out):
    """Only a generated combined track directory may receive this overlay."""
    out = Path(out)
    require(all((out/'TRACKS'/n).is_file() for n in ('L5RA.BUN', 'STREAML5RA.BUN')),
            'attributes overlay needs a generated combined pair')
    require(not any(out.resolve().is_relative_to(Path(p).resolve().parent)
                    for p in (mw_root, carbon_root)), 'attributes output overlaps source installation')
    target = out/'GLOBAL/ATTRIBUTES.BIN'
    require(target.parent.resolve().is_relative_to(out.resolve()),
            'attributes output escapes combined directory')
    require(not target.exists(), 'attributes overlay already exists')
    source = (Path(mw_root).parent/'GLOBAL/attributes.bin').read_bytes()
    destination = (Path(carbon_root).parent/'GLOBAL/attributes.bin').read_bytes()
    result = convert(source, destination)
    target.parent.mkdir(exist_ok=True)
    target.write_bytes(result)
    return verify(source, destination, result)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mw-root', type=Path, default=DEFAULT_MW)
    parser.add_argument('--carbon-root', type=Path, default=DEFAULT_CARBON)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = write_overlay(args.mw_root, args.carbon_root, args.out)
    except FileNotFoundError as exc:
        print(f'SKIP: private attributes absent: {exc}')
        return 3
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
