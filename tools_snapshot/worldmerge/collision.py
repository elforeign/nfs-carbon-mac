"""Whole-grid collision conversion; private inputs are always read-only.

Plan: inventory every indexed source section, preserve opaque pack/road bytes,
replace flat CDat cells with one rectangle and an Arti tile, then export only
under ignored worktree scratch. This is a collision component, not a track.

``cell`` defaults to the source spacing; ``shift`` is physics (x, z), default
zero; ``id_map`` maps pack selectors, default identity. Re-binning conservatively
copies references to every overlapping target cell. Shift moves the grid origin
only: a later world converter must also translate pack geometry and RNgp. Those
opaque payloads are deliberately retained here, including undecoded surfaces
and family-3 semantics. The large rectangle/tile still needs reader proof (D2).
"""
import argparse
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import shutil
import struct
import sys
import tempfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from formats import FormatError, chunks, require, u32
from convert import Builder
from merge import DEFAULT_MW, DEFAULT_CARBON, load_index, read_section
from region import collision_body, collision_tags, collision_cells, one, append_collision

ROOT = HERE.parents[1]
SCRATCH = ROOT / 'recomp' / 'out' / 'rockgrid-scratch'
CDAT, RNGP = 0x43446174, 0x524e6770
CGRD, CGCN, RECT = 0x43477264, 0x4347636e, 0x636c0000
TILE_SECTION = 2500


@dataclass(frozen=True)
class Collision:
    """Unwrapped CARP map, tile (with its 16-byte header), and resident packs.

    A track builder puts map_data in 0x3b800, tile in section 2500/0x3b802,
    and packs in section 2600/0x3b801, aligning each body to 16 bytes.
    """
    map_data: bytes
    tile: bytes
    packs: tuple
    report: dict


def tag_data(raw, tag):
    _, flags, count, offset = tag
    return raw[offset:offset + (flags >> 8)] if count else b''


def families(record):
    start = 20
    result = []
    for count in record[8:12]:
        result.append(record[start:start + 4 * count])
        start += 4 * count
    return result


def rebin(records, rows, columns, old_cell, cell):
    """Cover old cell footprints, rather than assigning their centres.

    Preserve the first four opaque header bytes; refuse to merge unlike values.
    Per-family duplicate words are coalesced only when spacing actually changes.
    """
    if cell == old_cell:
        return records, rows, columns
    new_rows = math.ceil(rows * old_cell / cell)
    new_columns = math.ceil(columns * old_cell / cell)
    require(new_rows * new_columns <= 65536, 're-binned cell ids exceed u16')
    bins = {}
    for record in records:
        row, col = divmod(struct.unpack_from('<H', record, 4)[0], columns)
        r0, c0 = math.floor(row * old_cell / cell), math.floor(col * old_cell / cell)
        r1 = math.ceil((row + 1) * old_cell / cell)
        c1 = math.ceil((col + 1) * old_cell / cell)
        for r in range(r0, r1):
            for c in range(c0, c1):
                prefix, refs = bins.setdefault(r * new_columns + c, (record[:4], [{} for _ in range(4)]))
                require(prefix == record[:4], 'unclassified cell prefixes cannot be merged')
                for dest, source in zip(refs, families(record)):
                    for p in range(0, len(source), 4):
                        dest[source[p:p + 4]] = None
    result = []
    for cid, (prefix, refs) in sorted(bins.items()):
        counts = [len(ref) for ref in refs]
        require(max(counts) <= 255, 're-binned reference family exceeds u8')
        offsets = [4 * sum(counts[:k]) for k in range(4)]
        result.append(prefix + struct.pack('<HH4B4H', cid, 0, *counts, *offsets)
                      + b''.join(word for ref in refs for word in ref))
    return result, new_rows, new_columns


def make_tile(records):
    data = b''.join(records)
    require(len(data) < 1 << 24, 'tile tag byte extent exceeds u24')
    raw = bytearray(256)
    struct.pack_into('<4I', raw, 0, 0x43415250, 0x2a, 0, 1)
    struct.pack_into('<4I', raw, 16, 0x41727469, 0x12, 2, 1)
    struct.pack_into('<4I', raw, 32, CGCN, (len(data) << 8) | 2, len(records), 224)
    name = (256 + len(data) + 15) // 16 * 16
    struct.pack_into('<4I', raw, 48, 0x4e616d65, 0x602, 0, name - 48)
    raw += data + bytes(name - 256 - len(data)) + b'L2RA\0\0'
    raw += bytes(-len(raw) % 16)
    return struct.pack('<4I', len(raw), TILE_SECTION, 0, 0) + raw


def make_map(raw, descriptor, rectangle):
    """Keep the source RNgp suffix byte-exact, including opaque alignment.

    The group/tag directory stays in place; only CDat tags and relative RNgp
    pointers change. No interpretation of RNgp tables or their padding is needed.
    """
    tags = collision_tags(raw, CDAT)
    road = collision_tags(raw, RNGP)
    require(set(tags) == {CGCN, CGRD, 0x636f0000}, 'unsupported source CDat directory')
    require(not collision_tags(raw, 0x4d617020), 'unclassified Map data must not be discarded')
    require(tags[0x636f0000][2] == 0, 'unclassified collision overrides present')
    first = tags[CGCN][3]
    require(first == 256 and all(t[0] < first for t in (*tags.values(), *road.values())),
            'unsupported source collision directory extent')
    road_start = min(t[3] for t in road.values() if t[2])
    require(road_start >= tags[CGRD][3] + 36 and road_start % 16 == 0,
            'source RNgp is not a separate aligned suffix')
    require(all(t[3] >= road_start for t in road.values() if t[2]), 'RNgp payload order')
    out = bytearray(raw[:first])
    out += descriptor + bytes(-len(descriptor) % 16)
    rect_offset = len(out)
    out += rectangle + bytes(-len(rectangle) % 16)
    new_road = len(out)
    out += raw[road_start:]
    # Carbon's native cl0000 flags are 0xa03, one 10-byte record.
    for q, key, flags, p in ((tags[CGCN][0], CGRD, 0x2802, first),
                             (tags[CGRD][0], RECT, 0xa03, rect_offset)):
        struct.pack_into('<4I', out, q, key, flags, 1, p - q)
    for q, _, count, p in road.values():
        if count:
            struct.pack_into('<I', out, q + 12, p - road_start + new_road - q)
    return bytes(out)


def convert(source, source_stream, carbon, *, cell=None, shift=(0, 0), id_map=None):
    """Convert every source collision cell and every indexed pack, in memory."""
    raw = collision_body(one(source.parts, 0x3b800))
    tags = collision_tags(raw, CDAT)
    require(tags[CGRD][1] >> 8 == 36 and tags[CGRD][2] == 1, 'source descriptor must be 36 bytes')
    descriptor = bytearray(tag_data(raw, tags[CGRD]))
    old_cell = struct.unpack_from('<f', descriptor, 16)[0]
    rows, columns = struct.unpack_from('<II', descriptor, 24)
    require(0 < rows and 0 < columns and rows * columns <= 65536
            and math.isfinite(old_cell) and old_cell > 0, 'source grid dimensions')
    require(len(shift) == 2 and all(math.isfinite(v) for v in shift), 'shift must be finite physics x,z')
    cell = old_cell if cell is None else cell
    require(math.isfinite(cell) and cell > 0, 'cell must be positive and finite')
    records = collision_cells(raw, tags[CGCN])
    ids = [struct.unpack_from('<H', c, 4)[0] for c in records]
    require(ids and len(set(ids)) == len(ids) and max(ids) < rows * columns, 'source cell ids invalid/duplicate')
    source_families = [sum(c[8 + k] for c in records) for k in range(4)]
    packs = {}
    for section in source.sections:
        for chunk in chunks(read_section(source_stream, section)):
            if chunk.kind == 0x3b801:
                pack = collision_body(chunk)
                key = u32(pack, 4)
                require(0 < key < 2700 and key not in packs, 'source pack id invalid/duplicate')
                require(u32(pack) == len(pack) - 16, 'source pack extent')
                packs[key] = pack
    require(packs, 'source collision packs absent')
    mapping = {} if id_map is None else dict(id_map)
    require(mapping.keys() <= packs.keys(), 'id_map contains absent source pack')
    targets = {key: mapping.get(key, key) for key in packs}
    require(all(isinstance(v, int) and 0 < v < 2700 for v in targets.values())
            and len(set(targets.values())) == len(targets), 'mapped pack ids invalid/duplicate')
    road = collision_tags(raw, RNGP)
    # RNsg's measured count bounds family 3; its consumer/meaning remains inferred.
    limit = road[0x524e7367][2]
    for record in records:
        refs = families(record)
        for value, in struct.iter_unpack('<I', refs[0]):
            key, instance = value >> 16, value & 0xffff
            require(key in packs, 'source reference has no pack')
            tag = collision_tags(packs[key][16:], 0x41727469)[0x63690000]
            require(instance < tag[2], 'source reference instance outside pack')
        require(all(value < limit for value, in struct.iter_unpack('<I', refs[3])), 'source family-3 word outside RNsg count')
    records, rows, columns = rebin(records, rows, columns, old_cell, cell)
    output_cells = []
    for record in records:
        out = bytearray(record)
        struct.pack_into('<H', out, 6, TILE_SECTION)
        for p in range(20, 20 + 4 * out[8], 4):
            ref = u32(out, p)
            struct.pack_into('<I', out, p, (targets[ref >> 16] << 16) | (ref & 0xffff))
        output_cells.append(bytes(out))
    output_packs = []
    for key, pack in sorted(packs.items()):
        out = bytearray(pack)
        struct.pack_into('<I', out, 4, targets[key])
        output_packs.append(bytes(out))
    ox, oy, oz = struct.unpack_from('<3f', descriptor)
    struct.pack_into('<3f', descriptor, 0, ox + shift[0], oy, oz + shift[1])
    struct.pack_into('<f', descriptor, 16, cell)
    struct.pack_into('<II', descriptor, 24, rows, columns)
    descriptor[32:36] = bytes(4)  # serialized pointer, ignored by native grid reader
    native = collision_body(one(carbon.parts, 0x3b800))
    native_tag = collision_tags(native, CDAT)[CGRD]
    require(native_tag[1] >> 8 == 40, 'native Carbon grid must be 40 bytes')
    extension = tag_data(native, native_tag)[36:40]
    require(extension == struct.pack('<I', 1), 'native descriptor extension differs')
    descriptor += extension
    coords = [divmod(struct.unpack_from('<H', c, 4)[0], columns) for c in output_cells]
    r0, r1 = min(r for r, _ in coords), max(r for r, _ in coords)
    c0, c1 = min(c for _, c in coords), max(c for _, c in coords)
    rectangle = struct.pack('<5H', TILE_SECTION, r0, c0, c1 - c0 + 1, r1 - r0 + 1)
    map_data = make_map(raw, descriptor, rectangle)
    tile = make_tile(output_cells)
    report = {'source_cells': len(ids), 'cells': len(output_cells), 'source_reference_families': source_families,
              'reference_families': [sum(c[8 + k] for c in output_cells) for k in range(4)],
              'packs': len(output_packs), 'pack_bytes': sum(map(len, output_packs)),
              'rectangle': list(struct.unpack('<5H', rectangle)), 'descriptor_bytes': len(descriptor),
              'rngp_payload_bytes': sum(len(tag_data(raw, t)) for t in road.values()),
              'rngp_suffix_bytes': len(raw) - min(t[3] for t in road.values() if t[2]),
              'tile_bytes': len(tile), 'cell': cell, 'shift': list(shift), 'id_map': mapping,
              'inferred': ['family-3 meaning; words retained', 'whole-grid rectangle/tile reader acceptance (D2)'],
              'opaque': ['RNgp and pack payloads retained; shift changes grid only',
                         'surfaces and scenery-group semantics', 'descriptor +36 copied from native data']}
    return Collision(map_data, tile, tuple(output_packs), report)


def prepare(mw_root=DEFAULT_MW, carbon_root=DEFAULT_CARBON, **options):
    source, stream, _ = load_index(mw_root, 'L2RA')
    carbon, _, _ = load_index(carbon_root, 'L5RA')
    return convert(source, stream, carbon, **options)


def write_outputs(result, output):
    """Publish a new component directory atomically, confined to local scratch."""
    output = Path(output).resolve()
    scratch = SCRATCH.resolve()
    require(scratch.is_relative_to(ROOT.resolve()) and scratch != ROOT.resolve(), 'scratch escapes worktree')
    require(output != scratch and output.is_relative_to(scratch), 'output must be inside collision scratch')
    require(not output.exists(), 'output already exists')
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.collision-', dir=output.parent))
    try:
        (stage / 'map.carp').write_bytes(result.map_data)
        (stage / 'tile.bin').write_bytes(result.tile)
        out = Builder(0)
        append_collision(out, result.tile, result.packs)
        (stage / 'collision-stream.bin').write_bytes(out.data)
        (stage / 'proof.json').write_text(json.dumps(result.report, indent=2) + '\n')
        os.rename(stage, output)
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mw-root', type=Path, default=DEFAULT_MW)
    parser.add_argument('--carbon-root', type=Path, default=DEFAULT_CARBON)
    parser.add_argument('--out', type=Path, default=SCRATCH / 'whole-city')
    parser.add_argument('--cell', type=float)
    parser.add_argument('--shift', nargs=2, type=float, default=(0, 0), metavar=('X', 'Z'))
    parser.add_argument('--id-map', type=Path, help='JSON source pack id -> target pack id')
    args = parser.parse_args()
    mapping = {int(k): v for k, v in json.loads(args.id_map.read_text()).items()} if args.id_map else None
    result = prepare(args.mw_root, args.carbon_root, cell=args.cell, shift=args.shift, id_map=mapping)
    write_outputs(result, args.out)
    print(json.dumps(result.report, sort_keys=True))


if __name__ == '__main__':
    try:
        main()
    except (FormatError, OSError, ValueError) as error:
        raise SystemExit(str(error))
