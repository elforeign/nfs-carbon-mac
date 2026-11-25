"""Append positioned core triggers to a destination-format gameplay overlay.

Only classified serialization differences are translated. Source collections
retain their identities and parent templates; race collections are excluded.
The destination pack is the loaded gameplay.bin, never its backup.
"""
import argparse
from collections import Counter
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import struct
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from formats import require
from merge import DEFAULT_MW, DEFAULT_CARBON

COLLECTION = 0x8E112EB7
GAMEPLAY = 0x5CEA9D46
POSITION = 0x9F743A0E
PROGRESSION = 0x6CE23062
EXTRA = 0x9995178A
TEMPLATES = {0x73049919: 3, 0x4698966B: 8, 0x326427BB: 4, 0xB05871D3: 39}
# 6CE23062 is the bin at which a trigger unlocks. 00635F41 shows a shop or
# speed-trap icon at construction only while the current bin (statistic
# 0x1776) is <= this field. Shops take the destination's highest bin, so the
# test holds at every career stage; the other records keep 32, a value the
# destination's own safehouses carry (their icons follow other native rules).
CARBON_VALUE = 32
SHOP = 0x4698966B
SHIFT = (8192.0, 0.0)  # Rockport's render (x, y) offset in the combined world
SAFEHOUSE = 0x326427BB
CARLOT = 0x73049919
PREMISES_SAFEHOUSE = 0x874B96D6
PREMISES_CARLOT = 0xB7F31748
PREMISES_TRIGGER = 0xD5DFD829
PREMISES_AREA = 0x70D72E20
TEMPLATE = 0x3E9156CA
ZONE_TYPE = 0xF3EA3201
RESPAWN = 0x2241F4CD
MARKER = 0xA7BCCF63
TEXT = 0xA3F0C234
KEY_TYPE = 0x6CD4B70A
ZONE_LIST = 0x64893DA8
CHILDREN = 0x916E0E78


def align(n, multiple=16):
    return (n + multiple - 1) // multiple * multiple


def u32(data, off):
    require(0 <= off <= len(data) - 4, 'word outside vault')
    return struct.unpack_from('<I', data, off)[0]


@dataclass
class Collection:
    export: int
    key: int
    cls: int
    parent: int
    reserve: int
    flags: int
    fields: list             # (key, type, flags, raw value)
    layout: bytes
    name: bytes


class Pack:
    def __init__(self, raw):
        require(raw[:4] == b'VPAK' and len(raw) >= 16, 'expected VPAK gameplay file')
        self.raw = raw
        n, so, ss = struct.unpack_from('<3I', raw, 4)
        require(16 + n * 20 <= so and so + ss <= len(raw), 'VPAK directory extent')
        self.vaults = {}
        for i in range(n):
            no, bs, vs, bo, vo = struct.unpack_from('<5I', raw, 16 + 20*i)
            end = raw.find(b'\0', so + no, so + ss)
            require(no < ss and end >= 0 and bo + bs <= len(raw) and vo + vs <= len(raw),
                    'VPAK vault extent')
            name = raw[so+no:end].decode('ascii')
            require(name not in self.vaults, 'duplicate vault name')
            self.vaults[name] = (16 + 20*i, raw[bo:bo+bs], raw[vo:vo+vs])

    def core(self, carbon):
        require('gpcore' in self.vaults, 'gpcore vault absent')
        _, binary, vault = self.vaults['gpcore']
        return Vault(binary, vault, carbon)

    def replace_core(self, binary, vault):
        # Leave all other vaults, offsets and padding untouched. Only gpcore's
        # directory entry points at the appended replacement buffers.
        out = bytearray(self.raw)
        out += bytes(align(len(out)) - len(out))
        bo = len(out)
        out += binary
        out += bytes(align(len(out)) - len(out))
        vo = len(out)
        out += vault
        entry = self.vaults['gpcore'][0]
        struct.pack_into('<4I', out, entry+4, len(binary), len(vault), bo, vo)
        return bytes(out)


class Vault:
    def __init__(self, binary, raw, carbon):
        self.binary, self.raw, self.carbon = binary, raw, carbon
        self.chunks = {}
        off = 0
        while off < len(raw):
            require(off + 8 <= len(raw), 'truncated vault chunk')
            kind, size = struct.unpack_from('<II', raw, off)
            require(size >= 8 and off + size <= len(raw), 'vault chunk extent')
            require(kind not in self.chunks, 'duplicate vault chunk')
            self.chunks[kind] = (off, size)
            off += size
        self.exports = []
        off, size = self.chunks[0x4578704E]  # ExpN
        count, stride = u32(raw, off+8), 16 if carbon else 20
        require(12 + count*stride <= size, 'export table extent')
        for i in range(count):
            words = struct.unpack_from('<4I' if carbon else '<5I', raw, off+12+i*stride)
            self.exports.append((words[0], words[1], words[-2], words[-1]))
        self.fixups, self.pointer_rows = {}, []
        off, size = self.chunks[0x5074724E]  # PtrN
        base = 0
        for at in range(off+8, off+size-11, 12):
            row = pos, kind, dep, value = struct.unpack_from('<IHHI', raw, at)
            if kind == 0:
                break
            self.pointer_rows.append(row)
            if kind == 2:
                base = dep
            else:
                require((base, pos) not in self.fixups, 'duplicate pointer fixup')
                self.fixups[base, pos] = (kind, dep, value)
        else:
            require(False, 'pointer terminator absent')
        self.collections = {}
        for export, kind, size, off in self.exports:
            if kind != COLLECTION:
                continue
            require(off + size <= len(raw) and size >= 32, 'collection extent')
            key, cls, parent, reserve, flags, count = struct.unpack_from('<6I', raw, off)
            nt = struct.unpack_from('<H' if carbon else '<I', raw, off+24)[0]
            padded = struct.unpack_from('<H', raw, off+26)[0] if carbon else nt
            # 004682B0 reads the padded count at +1A; +18 is the true u16 count.
            require(padded == (align(nt, 2) if carbon else nt), 'collection type padding')
            types = struct.unpack_from('<%dI' % nt, raw, off+32)
            entries = off + 32 + 4*padded
            require(entries + count*12 <= off+size, 'collection entries extent')
            fields = []
            for i in range(count):
                at = entries + 12*i
                field, value, ti, fl, reserved = struct.unpack_from('<IIHBB', raw, at)
                require(ti < nt and reserved == 0, 'field type index/reserved')
                if fl & (0x40 if carbon else 0x20):
                    payload = struct.pack('<I', value)
                    # Text is an inline char pointer: the relocation replaces
                    # the entry's zero word, unlike indirect vector/array data.
                    fixup = self.fixups.get((0, at+4))
                    if types[ti] == TEXT and fixup:
                        require(fixup[:2] == (3, 1), 'inline text pointer not decoded yet')
                        target = fixup[2]
                        end = binary.find(b'\0', target)
                        require(0 <= target <= end, 'inline text extent')
                        payload = binary[target:end+1]
                else:
                    fixup = self.fixups.get((0, at+4))
                    require(fixup is not None and fixup[:2] == (3, 1), 'field pointer not decoded yet')
                    target = fixup[2]
                    # These are the only indirect field shapes in the selected
                    # trigger records. Do not guess the extent of other fields.
                    if field == POSITION:
                        length = 12
                    elif field in (CHILDREN, ZONE_LIST):
                        require(target + 8 <= len(binary), 'trigger array header')
                        alloc, n, stride, enc = struct.unpack_from('<4H', binary, target)
                        require(alloc == n and stride == 4 and enc == 0, 'trigger array not decoded yet')
                        length = 8 + n*stride
                    else:
                        payload = None
                        fields.append((field, types[ti], fl, payload))
                        continue
                    require(target + length <= len(binary), 'trigger value extent')
                    payload = binary[target:target+length]
                fields.append((field, types[ti], fl, payload))
            require(key not in self.collections, 'collection-key clash within vault')
            layout = name = None
            fixup = self.fixups.get((0, off+28))
            if cls == GAMEPLAY and fixup and fixup[0] == 3:
                require(fixup[1] == 1 and fixup[2]+8 <= len(binary), 'gameplay layout extent')
                # Both class definitions have the identical 8-byte layout:
                # CollectionName (9CA1C8F9, Text) at +0 and 9E8910EF at +4.
                layout = binary[fixup[2]:fixup[2]+8]
                name_fix = self.fixups.get((1, fixup[2]))
                if name_fix and name_fix[:2] == (3, 1):
                    end = binary.find(b'\0', name_fix[2])
                    require(0 <= name_fix[2] <= end, 'collection name extent')
                    name = binary[name_fix[2]:end+1]
            self.collections[key] = Collection(export, key, cls, parent, reserve, flags, fields, layout, name)

    def triggers(self):
        result = []
        parents = {c.parent for c in self.collections.values()}
        for c in self.collections.values():
            if c.cls != GAMEPLAY or c.key in parents or POSITION not in {f[0] for f in c.fields}:
                continue
            p, seen = c.parent, set()
            while p and p not in TEMPLATES:
                require(p not in seen and p in self.collections, 'trigger parent chain')
                seen.add(p)
                p = self.collections[p].parent
            if p in TEMPLATES:
                result.append((p, c))
        return result


def vault_hash(text):
    """Collection name hash; the export hashes the class/name path."""
    def mix(a, b, c):
        m = 0xFFFFFFFF
        a = (a-b-c) & m ^ c >> 13; b = (b-c-a) & m ^ (a << 8) & m; c = (c-a-b) & m ^ b >> 13
        a = (a-b-c) & m ^ c >> 12; b = (b-c-a) & m ^ (a << 16) & m; c = (c-a-b) & m ^ b >> 5
        a = (a-b-c) & m ^ c >> 3; b = (b-c-a) & m ^ (a << 10) & m; c = (c-a-b) & m ^ b >> 15
        return a, b, c
    k, m = text.encode('ascii'), 0xFFFFFFFF
    a = b = 0x9E3779B9
    c, i = 0xABCDEF00, 0
    while len(k)-i >= 12:
        a = (a+int.from_bytes(k[i:i+4], 'little')) & m
        b = (b+int.from_bytes(k[i+4:i+8], 'little')) & m
        c = (c+int.from_bytes(k[i+8:i+12], 'little')) & m
        a, b, c = mix(a, b, c); i += 12
    c = (c+len(k)) & m
    rest = k[i:]
    a = (a+int.from_bytes(rest[:4], 'little')) & m
    b = (b+int.from_bytes(rest[4:8], 'little')) & m
    c = (c+(int.from_bytes(rest[8:11], 'little') << 8)) & m
    return mix(a, b, c)[2]


def place_premises(records, dst):
    """Area-less premises, ordered after native entries: houses, shops, lots."""
    native = [c for c in dst.collections.values()
              if c.parent in (PREMISES_SAFEHOUSE, PREMISES_CARLOT)]
    donor = dst.collections[0x8D84FCE6]
    require(donor.parent == PREMISES_SAFEHOUSE and PREMISES_AREA not in {f[0] for f in donor.fields}
            and any(f[0] == TEMPLATE and f[3] == bytes(4) for f in donor.fields),
            'destination area-less safehouse donor changed')
    require(donor.name and donor.key == vault_hash(donor.name[:-1].decode('ascii')) and
            donor.export == vault_hash('gameplay/'+donor.name[:-1].decode('ascii')),
            'element key/export hash not decoded')
    prefix = donor.name[:donor.name.rindex(b'/')+1].decode('ascii')
    result, last = [], max(c.key for c in native)
    span = (0xFFFFFFFF-last)//3
    # 006351F0 sorts unsigned keys; 005AD280 assigns map objects in that order.
    # Keep all native entries first and the four houses before the eight shops.
    for group, template in enumerate((SAFEHOUSE, SHOP, CARLOT)):
        for _, trigger in sorted((r for r in records if r[0] == template), key=lambda r: r[1].name):
            base = prefix+trigger.name[:-1].decode('ascii').rsplit('/', 1)[-1]
            for n in range(1, 10000):
                name = base if n == 1 else f'{base}_{n}'
                key = vault_hash(name)
                if last+group*span < key <= last+(group+1)*span:
                    break
            else:
                require(False, 'no premises key after destination elements')
            # 00631430 -> 0061F600 rejects inherited Template=1. The native
            # highway element explicitly sets zero; 0062E980 owns type 2
            # without a zone. Type-1 lots still need a separate ownership hook.
            fields = [(PREMISES_TRIGGER, KEY_TYPE, 0x20, struct.pack('<I', trigger.key)),
                      (TEMPLATE, 0x064BEC37, 0x20, bytes(4))]
            parent = PREMISES_CARLOT if template == CARLOT else PREMISES_SAFEHOUSE
            result.append((None, Collection(vault_hash('gameplay/'+name), key, GAMEPLAY, parent,
                                            2, donor.flags, fields, donor.layout, name.encode()+b'\0')))
    return result


def append_activity_members(dst, binary, records):
    """Redirect only the two key arrays on each native menu-gate activity."""
    replacements = {}
    for activity, templates, count in ((0x3103659B, (SAFEHOUSE, SHOP), 12),
                                       (0x10874E8D, (CARLOT,), 3)):
        c = dst.collections[activity]
        added = [r.key for t, r in records if t in templates]
        require(len(added) == count, 'menu-gate trigger count')
        _, _, _, off = next(r for r in dst.exports if r[0] == c.export)
        padded = struct.unpack_from('<H', dst.raw, off+26)[0]
        for i, (field, typ, flags, payload) in enumerate(c.fields):
            if field not in (ZONE_LIST, CHILDREN):
                continue
            require(typ == KEY_TYPE and flags == 2 and payload is not None and
                    struct.unpack_from('<4H', payload) == (4, 4, 4, 0), 'native menu-gate array changed')
            binary += bytes(align(len(binary), 4)-len(binary))
            replacements[off+32+4*padded+12*i+4] = len(binary)
            binary += struct.pack('<4H', 4+count, 4+count, 4, 0)+payload[8:]
            binary += struct.pack('<%dI' % count, *added)
    require(len(replacements) == 4, 'menu-gate membership fields absent')
    rows, base = [], 0
    for pos, kind, dep, value in dst.pointer_rows:
        if kind == 2:
            base = dep
        elif base == 0 and kind == 3 and dep == 1:
            value = replacements.get(pos, value)
        rows.append((pos, kind, dep, value))
    return rows


def chunk(kind, payload):
    return struct.pack('<II', kind, 8+len(payload)) + payload


def startup_companion(raw):
    # 00614650 substitutes .LZC for startup; 0069EBF0 copies this RAWW
    # envelope's +8 bytes from +16. Streaming still reads the .BIN directory.
    return b'RAWW\x01\x10\0\0' + struct.pack('<II', len(raw), len(raw)+16) + raw


def convert(source, destination, shift=SHIFT):
    mw, carbon = Pack(source), Pack(destination)
    src, dst = mw.core(False), carbon.core(True)
    records = src.triggers()
    require(Counter(t for t, _ in records) == TEMPLATES, 'expected 54 core triggers')
    marker_keys = {u32(f[3], 0) for t, c in records if t in (SAFEHOUSE, SHOP, CARLOT)
                   for f in c.fields if f[0] == RESPAWN}
    require(len(marker_keys) == 15, 'expected 15 place respawn markers')
    markers = [(None, src.collections[k]) for k in sorted(marker_keys)]
    require(all(c.parent == MARKER and c.parent in dst.collections for _, c in markers),
            'respawn marker parent changed')
    premises = place_premises(records, dst)
    # Check all destination vaults, not only gpcore, before retaining identities.
    keys, exports = set(), set()
    for _, binary, vault in carbon.vaults.values():
        parsed = Vault(binary, vault, True)
        keys.update((c.cls, c.key) for c in parsed.collections.values())
        exports.update(r[0] for r in parsed.exports)
    for _, c in markers+premises+records:
        require((c.cls, c.key) not in keys and c.export not in exports, 'collection-key clash with destination')
        require(c.parent in dst.collections, 'destination parent template absent')
        keys.add((c.cls, c.key)); exports.add(c.export)
    require(any(f[0] == PROGRESSION and f[3] == struct.pack('<I', CARBON_VALUE)
                for _, c in dst.triggers() for f in c.fields), 'destination progression donor absent')
    top_bin = max(u32(f[3], 0) for c in dst.collections.values() for f in c.fields
                  if f[0] == PROGRESSION and f[3] is not None)
    require(CARBON_VALUE <= top_bin < 0x8000, 'destination bin range')
    data_off, data_size = dst.chunks[0x4461744E]
    data = bytearray(dst.raw[data_off+8:data_off+data_size])
    binary = bytearray(dst.binary)
    native_pointers = append_activity_members(dst, binary, records)
    additions, fixes = [], [(0, 2, 0, 0)]
    # Keep the 54 triggers last for the retained native name-consumer fixture.
    for template, c in markers+premises+records:
        fields = list(c.fields)
        if template is not None:
            require(EXTRA not in {f[0] for f in fields}, 'unexpected source default field')
            # 0049D100 maps muscle to a supported garage scene for both flows.
            place = template in (SAFEHOUSE, SHOP, CARLOT)
            fields.append((EXTRA, TEXT, 0x20, b'muscle\0' if place else bytes(4)))
            if template == SHOP:
                # Ancestry retains shop HUD art; the gate callback uses this
                # string to select safehouse menu flow (005DC2E0).
                fields = [f for f in fields if f[0] != ZONE_TYPE]
                fields.append((ZONE_TYPE, TEXT, 0x20, b'safehouse\0'))
        types = list(dict.fromkeys(f[1] for f in fields))
        absolute = data_off+8+len(data)
        data += bytes(align(absolute, 8)-absolute)
        off = data_off+8+len(data)
        header = struct.pack('<6IHHI', c.key, c.cls, c.parent, max(c.reserve, len(fields)),
                             c.flags, len(fields), len(types), align(len(types), 2), 0)
        body = bytearray(header + struct.pack('<%dI' % len(types), *types))
        body += bytes(align(len(body), 8)-len(body))
        require(c.layout is not None and c.name, 'source gameplay layout/name absent')
        binary += bytes(align(len(binary), 4)-len(binary))
        layout_off = len(binary)
        fixes.append((off+28, 3, 1, layout_off))
        binary += c.layout
        name_off = len(binary)
        binary += c.name
        # CollectionName is a second-level BIN pointer. 00638430 reads it
        # directly; a copied zero placeholder would start its reverse path
        # scan at UINT32_MAX. Preserve both levels of relocation.
        fixes += [(0, 2, 1, 0), (layout_off, 3, 1, name_off), (0, 2, 0, 0)]
        for key, typ, fl, payload in fields:
            require(payload is not None and fl in (0, 2, 0x20), 'trigger field shape not decoded yet')
            if key == PROGRESSION:
                payload = struct.pack('<I', top_bin if template == SHOP else CARBON_VALUE)
            if fl & 0x20:
                if typ == TEXT and payload != bytes(4):
                    require(payload.endswith(b'\0') and b'\0' not in payload[:-1], 'inline text shape')
                    fixes.append((off+len(body)+4, 3, 1, len(binary)))
                    binary += payload
                    value = 0
                else:
                    value = u32(payload, 0)
                fl = (fl & ~0x20) | 0x40  # Destination inline-value flag.
            else:
                binary += bytes(align(len(binary), 16 if key == POSITION else 4)-len(binary))
                value = len(binary)
                if key == POSITION:
                    xyz = struct.unpack('<3f', payload)
                    require(all(math.isfinite(x) for x in xyz), 'nonfinite trigger position')
                    payload = struct.pack('<3f', xyz[0]+shift[0], xyz[1]+shift[1], xyz[2])
                binary += payload
                fixes.append((off+len(body)+4, 3, 1, value))
                value = 0
            body += struct.pack('<IIHBB', key, value, types.index(typ), fl, 0)
        additions.append((c.export, COLLECTION, len(body), off))
        data += body
    data += bytes(align(data_off+8+len(data))-data_off-8-len(data))
    export_rows = dst.exports + additions
    exp = struct.pack('<I', len(export_rows)) + b''.join(struct.pack('<4I', *r) for r in export_rows)
    exp += bytes(align(8+len(exp))-8-len(exp))
    pointers = b''.join(struct.pack('<IHHI', *r) for r in native_pointers+fixes+[(0, 0, 0, 0)])
    pointers += bytes(align(8+len(pointers))-8-len(pointers))
    out = bytearray()
    for kind, (off, size) in dst.chunks.items():
        replacement = {0x4461744E: data, 0x4578704E: exp, 0x5074724E: pointers}.get(kind)
        out += dst.raw[off:off+size] if replacement is None else chunk(kind, replacement)
    result = carbon.replace_core(binary, out)
    report = {'records': len(records), 'templates': {f'{k:08X}': n for k, n in TEMPLATES.items()},
              'premises': len(premises), 'respawn_markers': len(markers),
              'position_shift': [shift[0], shift[1], 0], '6CE23062': CARBON_VALUE, '6CE23062_shop': top_bin,
              'source_sha256': hashlib.sha256(source).hexdigest(),
              'loaded_destination_sha256': hashlib.sha256(destination).hexdigest(),
              'output_sha256': hashlib.sha256(result).hexdigest(), 'bytes': len(result)}
    return result, report


def world_shift(out):
    """Rockport's render (x, y) shift for an overlay written into a built world.

    The world builder records Rockport's physics (X, 0, Z) translation in proof.json beside
    GLOBAL; render x is physics Z and render y is -X (c1_world.RENDER_SHIFT). Without a proof
    the overlay is not inside a built world and keeps SHIFT."""
    proof = Path(out).parent.parent/'proof.json'
    if not proof.is_file():
        return None
    x, y, z = json.loads(proof.read_text())['roads']['shift_physics_xyz']
    require(y == 0 and all(math.isfinite(v) for v in (x, z)), 'combined world shift')
    return (float(z), -float(x))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--mw', type=Path, default=DEFAULT_MW.parent/'GLOBAL/GAMEPLAY.BIN')
    ap.add_argument('--carbon', type=Path, default=DEFAULT_CARBON.parent/'GLOBAL/gameplay.bin')
    ap.add_argument('--out', type=Path, required=True, help='overlay GLOBAL/GAMEPLAY.BIN')
    ap.add_argument('--shift', help="Rockport's render x,y offset in the pair "
                    "(default: the world's proof.json beside GLOBAL, else %g,%g)" % SHIFT)
    args = ap.parse_args()
    world = world_shift(args.out)
    shift = tuple(float(v) for v in args.shift.split(',')) if args.shift else world or SHIFT
    require(len(shift) == 2 and all(math.isfinite(v) for v in shift), 'shift is x,y')
    require(world is None or shift == world, f'shift {shift} differs from the world proof {world}')
    require(args.carbon.name.lower() == 'gameplay.bin', 'destination must be the loaded gameplay.bin')
    require(args.out.resolve() not in (args.mw.resolve(), args.carbon.resolve()), 'output would replace an input')
    if not args.mw.is_file() or not args.carbon.is_file():
        print('SKIP: private gameplay inputs absent'); return 3
    result, report = convert(args.mw.read_bytes(), args.carbon.read_bytes(), shift)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(result)
    args.out.with_suffix('.LZC').write_bytes(startup_companion(result))
    print(json.dumps(report, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
