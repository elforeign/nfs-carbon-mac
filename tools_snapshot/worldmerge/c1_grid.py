"""Offline single-grid collision component; never writes a track pair.

Grid axes are physics X (column), Z (row), with Y height. A shift (dx,dz)
is render (dz,-dx,0). Cell footprints are intersected with the *destination*
grid: rebinning at the old origin first would change both coverage and counts.
Instance inverse translations move; local bounds/radii and articles do not.
Road arrays belong to the road converter; only their family-3 selectors move
here. Their consumer semantics and runtime tile residency remain unproven.
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
sys.dont_write_bytecode = True
sys.path.insert(0, str(HERE))
from collision import CDAT, CGRD, CGCN, RECT, RNGP, families, make_tile, tag_data
from convert import Builder
from formats import FormatError, chunks, require, u32
from merge import DEFAULT_CARBON, DEFAULT_MW, load_index, read_section
from region import collision_body, collision_cells, collision_tags, one

ROOT = HERE.parents[1]
ARTI, CI, RNSG = 0x41727469, 0x63690000, 0x524e7367
PACK_LIMIT, SEGMENT_LIMIT = 2700, 12328
GROUP_LIMIT = 4096


@dataclass(frozen=True)
class Grid:
    """Standalone native components; pack_ids maps all source pack selectors.

    Section defaults are provisional. The numbering plan must supply both the
    cell section word and tile home section before any track integration.
    """
    descriptor: bytes
    rectangle: bytes
    tile: bytes
    packs: tuple
    pack_ids: dict
    report: dict


@dataclass(frozen=True)
class City:
    descriptor: bytes
    cells: tuple
    packs: dict
    rectangles: tuple
    tiles: tuple
    segments: int


def grid_fields(descriptor):
    require(len(descriptor) in (36, 40), 'grid descriptor stride')
    origin = struct.unpack_from('<3f', descriptor)
    cell = struct.unpack_from('<f', descriptor, 16)[0]
    rows, columns = struct.unpack_from('<2I', descriptor, 24)
    require(all(math.isfinite(v) for v in (*origin, cell)) and cell > 0,
            'nonfinite grid origin/spacing')
    require(0 < rows <= 65535 and 0 < columns <= 65535 and rows*columns <= 65536,
            'grid address space exceeds u16')
    return origin, cell, rows, columns


def highest_group(packs):
    """Highest scenery-group number any instance of these packs carries."""
    top = 0
    for pack in packs:
        tag = instance_tag(pack)
        for p in range(16+tag[3], 16+tag[3]+(tag[1] >> 8), 64):
            top = max(top, struct.unpack_from('<H', pack, p+24)[0])
    return top


def instance_tag(pack):
    require(u32(pack) == len(pack)-16, 'pack extent')
    tag = collision_tags(pack[16:], ARTI)[CI]
    require(tag[2] > 0 and tag[1] >> 8 == 64*tag[2], 'pack instance stride')
    return tag


def read_city(index, stream):
    """Walk indexed sections and directories, including every streamed tile."""
    raw = collision_body(one(index.parts, 0x3b800))
    tags = collision_tags(raw, CDAT)
    require(tags[CGRD][2] == 1, 'grid descriptor count')
    descriptor = tag_data(raw, tags[CGRD])
    _, _, rows, columns = grid_fields(descriptor)
    rectangles = tuple(rect for key, tag in tags.items() if key >> 16 == 0x636c
                       for rect in struct.iter_unpack('<5H', tag_data(raw, tag)))
    cells = list(collision_cells(raw, tags[CGCN])) if CGCN in tags else []
    packs, tiles = {}, []
    for section in index.sections:
        for chunk in chunks(read_section(stream, section)):
            if chunk.kind == 0x3b801:
                pack = collision_body(chunk)
                key = u32(pack, 4)
                require(0 < key < PACK_LIMIT and key not in packs, 'pack id invalid/duplicate')
                instance_tag(pack)
                packs[key] = pack
            elif chunk.kind == 0x3b802:
                tile = collision_body(chunk)
                home = u32(tile, 4)
                require(u32(tile) == len(tile)-16, 'tile extent')
                body = tile[16:]
                records = collision_cells(body, collision_tags(body, ARTI)[CGCN])
                for record in records:
                    cid, region = struct.unpack_from('<HH', record, 4)
                    row, col = divmod(cid, columns)
                    require(region == home and any(s in (home, 65535) and r <= row < r+h
                            and c <= col < c+w for s, r, c, w, h in rectangles),
                            'source cell outside tile rectangle')
                tiles.append((home, len(records)))
                cells.extend(records)
    ids = [struct.unpack_from('<H', r, 4)[0] for r in cells]
    require(ids and len(set(ids)) == len(ids) and max(ids) < rows*columns,
            'source cell ids invalid/duplicate')
    segments = collision_tags(raw, RNGP)[RNSG][2]
    counts = {key: instance_tag(pack)[2] for key, pack in packs.items()}
    for record in cells:
        refs = families(record)
        for value, in struct.iter_unpack('<I', refs[0]):
            require(value >> 16 in counts and (value & 65535) < counts[value >> 16],
                    'source pack instance unresolved')
        require(all(v < segments for v, in struct.iter_unpack('<I', refs[3])),
                'source family-3 outside segment array')
    return City(descriptor, tuple(cells), packs, rectangles, tuple(tiles), segments)


def allocate_ids(carbon, source, requested=None):
    """Keep noncolliding selectors; allocate sorted collisions lowest-free first."""
    mapping = {} if requested is None else dict(requested)
    require(mapping.keys() <= source.keys(), 'pack_ids contains absent source pack')
    require(all(type(v) is int and 0 < v < PACK_LIMIT and v not in carbon
                for v in mapping.values()), 'requested pack id invalid/reserved')
    for key in source:
        if key not in carbon and key not in mapping:
            mapping[key] = key
    require(len(set(mapping.values())) == len(mapping), 'two packs on one id')
    used = set(carbon) | set(mapping.values())
    free = iter(n for n in range(1, PACK_LIMIT) if n not in used)
    for key in sorted(source):
        if key not in mapping:
            target = next(free, None)
            require(target is not None, 'pack table exhausted')
            mapping[key] = target
    return dict(sorted(mapping.items()))


def move_pack(pack, key, shift, group_base=0):
    """Rebase world->local translation, retaining local extents and articles.

    Inverse basis vectors occupy +0/+32, middle is their cross product.
    +48 is inverse translation: t' = t - B^T * (dx,0,dz).
    Native 007E87F0 derives world center from these fields. Native 007F5030
    compares local query X/Z with +/- extents at +12/+44; 008127B0 uses the
    same center and local radius +60 (and +20 for tilted instances). Thus no
    bound field stores an absolute world position requiring another addition.
    +24 is the u16 scenery-group number indexing a 4096-entry table; group_base
    lifts every non-zero number above the target city's own numbers so the
    source's groups are never switched on by the target's scenery.
    """
    out = bytearray(pack)
    struct.pack_into('<I', out, 4, key)
    tag = instance_tag(pack)
    for p in range(16+tag[3], 16+tag[3]+(tag[1] >> 8), 64):
        f = struct.unpack_from('<3f', pack, p)
        g = struct.unpack_from('<3f', pack, p+32)
        t = struct.unpack_from('<3f', pack, p+48)
        values = tuple(t[k] - f[k]*shift[0] - g[k]*shift[1] for k in range(3))
        require(all(math.isfinite(v) and abs(v) < 3.4028235e38 for v in values),
                'shifted instance translation not float32')
        struct.pack_into('<3f', out, p+48, *values)
        group, = struct.unpack_from('<H', pack, p+24)
        if group and group_base:
            require(group+group_base < GROUP_LIMIT, 'shifted group number exceeds table')
            struct.pack_into('<H', out, p+24, group+group_base)
    return bytes(out)


def cell_record(prefix, cid, section, refs):
    counts = [len(family) for family in refs]
    require(max(counts) <= 255, 'reference family exceeds u8')
    offsets = [4*sum(counts[:k]) for k in range(4)]
    return (prefix + struct.pack('<HH4B4H', cid, section, *counts, *offsets)
            + b''.join(struct.pack('<I', v) for family in refs for v in family))


def merge(carbon_index, carbon_stream, mw_index, mw_stream, *, shift=(20480.0, 0.0),
          segment_offset=5790, pack_ids=None, cell_section=2500, tile_section=2500):
    """Return one native 96 m grid plus both cities' packs, all in memory.

    Carbon keeps its segment selectors. Source family 3 follows Carbon's RNsg
    array; a different offset requires a matching road converter contract.
    Rectangle section matches cell_section; tile_section is the file's home.
    They are separate parameters for the numbering plan, not stream placement.
    """
    require(len(shift) == 2 and all(math.isfinite(v) for v in shift), 'finite physics x,z shift required')
    require(all(type(v) is int and 0 <= v < 32768 for v in (cell_section, tile_section)),
            'section outside positive signed u16')
    carbon, source = read_city(carbon_index, carbon_stream), read_city(mw_index, mw_stream)
    co, spacing, cr, cc = grid_fields(carbon.descriptor)
    so, old_cell, sr, sc = grid_fields(source.descriptor)
    require(len(carbon.descriptor) == 40 and spacing == 96.0, 'native grid must be 40-byte / 96 m')
    require(carbon.descriptor[36:] == struct.pack('<I', 1), 'native descriptor extension differs')
    require(type(segment_offset) is int and segment_offset == carbon.segments,
            'family-3 offset must follow native segment array')
    require(segment_offset + source.segments <= SEGMENT_LIMIT, 'combined segment array exceeds limit')
    mapping = allocate_ids(carbon.packs, source.packs, pack_ids)
    group_base = highest_group(carbon.packs.values())
    # Expand on Carbon's lattice, enclosing both *full* source descriptors.
    ox = co[0] + min(0, math.floor((so[0]+shift[0]-co[0])/spacing))*spacing
    oz = co[2] + min(0, math.floor((so[2]+shift[1]-co[2])/spacing))*spacing
    columns = math.ceil((max(co[0]+cc*spacing, so[0]+shift[0]+sc*old_cell)-ox)/spacing)
    rows = math.ceil((max(co[2]+cr*spacing, so[2]+shift[1]+sr*old_cell)-oz)/spacing)
    require(0 < rows*columns <= 65536, 'merged grid address space exceeds u16')
    bins, source_bins = {}, set()
    for city, delta, native in ((carbon, (0., 0.), True), (source, shift, False)):
        origin, step, _, cols = grid_fields(city.descriptor)
        for record in city.cells:
            row, col = divmod(struct.unpack_from('<H', record, 4)[0], cols)
            x = origin[0]+delta[0]+col*step-ox
            z = origin[2]+delta[1]+row*step-oz
            refs = [list(v[0] for v in struct.iter_unpack('<I', fam)) for fam in families(record)]
            if not native:
                refs[0] = [(mapping[v >> 16] << 16) | (v & 65535) for v in refs[0]]
                refs[3] = [v+segment_offset for v in refs[3]]
            for r in range(math.floor(z/spacing), math.ceil((z+step)/spacing)):
                for c in range(math.floor(x/spacing), math.ceil((x+step)/spacing)):
                    cid = r*columns+c
                    require(0 <= r < rows and 0 <= c < columns, 're-binned cell outside grid')
                    if not native:
                        source_bins.add(cid)
                    if cid not in bins:
                        # Native lists are byte-exact, including any duplicates.
                        bins[cid] = (record[:4], [list(fam) for fam in refs])
                    else:
                        prefix, dest = bins[cid]
                        require(prefix == record[:4], 'unclassified cell prefixes cannot be merged')
                        for a, b in zip(dest, refs):
                            a.extend(v for v in b if v not in a)
                    if not native:
                        prefix, dest = bins[cid]
                        bins[cid] = (prefix, [list(dict.fromkeys(fam)) for fam in dest])
    records = [cell_record(prefix, cid, cell_section, refs) for cid, (prefix, refs) in sorted(bins.items())]
    descriptor = bytearray(carbon.descriptor)
    struct.pack_into('<3f', descriptor, 0, ox, co[1], oz)
    struct.pack_into('<2I', descriptor, 24, rows, columns)
    descriptor[32:36] = bytes(4)
    rectangle = struct.pack('<5H', cell_section, 0, 0, columns, rows)
    tile = bytearray(make_tile(records))
    struct.pack_into('<I', tile, 4, tile_section)
    packs = tuple(carbon.packs[k] for k in sorted(carbon.packs)) + tuple(
        move_pack(source.packs[k], mapping[k], shift, group_base) for k in sorted(source.packs))
    source_maxima = [max(len(bins[cid][1][k]) for cid in source_bins) for k in range(4)]
    report = dict(cell=spacing, origin=[ox, co[1], oz], rows=rows, columns=columns,
                  addressable=rows*columns, id_margin=65536-rows*columns,
                  carbon_cells=len(carbon.cells), mw_cells=len(source.cells),
                  rebinned_mw_cells=len(source_bins), occupied=len(records),
                  mw_family_maxima=source_maxima, tile_bytes=len(tile),
                  pack_ids_reassigned=sum(k != v for k, v in mapping.items()),
                  physics_shift=list(shift), group_base=group_base, render_shift=[shift[1], -shift[0], 0.],
                  segment_offset=segment_offset, cell_section=cell_section, tile_section=tile_section,
                  opaque=['surfaces/scenery groups and scene activation', 'family-3 consumer inferred',
                          '365-column runtime rectangle acceptance and residency not tested'])
    result = Grid(bytes(descriptor), rectangle, bytes(tile), packs, mapping, report)
    report.update(check(result, cell_section=cell_section, tile_section=tile_section))
    return result


def check(result, *, cell_section=None, tile_section=None, segment_limit=SEGMENT_LIMIT):
    """Independent structural re-read; source completeness is tested separately.

    Reads serialized bytes only, never trusts report counts or returned ids.
    A range check cannot prove a missing family-3 offset: the source comparison
    in test_c1_grid is required as well as this structural check.
    """
    require(len(result.descriptor) == 40, 'native descriptor must be 40 bytes')
    _, spacing, rows, columns = grid_fields(result.descriptor)
    require(spacing == 96.0, 'merged spacing must be 96 m')
    require(result.descriptor[32:] == struct.pack('<2I', 0, 1), 'descriptor pointer/extension')
    require(len(result.rectangle) == 10, 'one rectangle required')
    section, r0, c0, width, height = struct.unpack('<5H', result.rectangle)
    require(width > 0 and height > 0 and r0+height <= rows and c0+width <= columns,
            'rectangle outside descriptor')
    require(cell_section is None or section == cell_section, 'rectangle section differs')
    tile = result.tile
    require(u32(tile) == len(tile)-16, 'tile extent differs')
    require(tile_section is None or u32(tile, 4) == tile_section, 'tile home section differs')
    body = tile[16:]
    tag = collision_tags(body, ARTI)[CGCN]
    records = collision_cells(body, tag)
    providers = {}
    for pack in result.packs:
        key = u32(pack, 4)
        require(0 < key < PACK_LIMIT and key not in providers, 'pack id invalid/duplicate')
        providers[key] = instance_tag(pack)[2]
    ids, totals, maxima = set(), [0]*4, [0]*4
    for record in records:
        cid, region = struct.unpack_from('<HH', record, 4)
        row, col = divmod(cid, columns)
        require(cid < rows*columns and cid not in ids and region == section,
                'cell id/section invalid or duplicate')
        require(r0 <= row < r0+height and c0 <= col < c0+width, 'cell outside rectangle')
        ids.add(cid)
        for k, count in enumerate(record[8:12]):
            require(count <= 255, 'family count exceeds u8')
            totals[k] += count
            maxima[k] = max(maxima[k], count)
        refs = families(record)
        for value, in struct.iter_unpack('<I', refs[0]):
            require(value >> 16 in providers and (value & 65535) < providers[value >> 16],
                    'pack reference unresolved')
        require(all(v < segment_limit for v, in struct.iter_unpack('<I', refs[3])),
                'family-3 word outside merged segment array')
    require(ids and providers, 'empty collision component')
    return dict(cells=len(ids), packs=len(providers), instances=sum(providers.values()),
                reference_families=totals, family_maxima=maxima,
                family_margins=[255-n for n in maxima], unresolved=0)


def write_outputs(result, output):
    """Atomically export a new directory outside this checkout and both inputs."""
    output = Path(output).resolve()
    require(all(not output.is_relative_to(root.resolve()) for root in (ROOT, DEFAULT_MW, DEFAULT_CARBON)),
            'output must be outside checkout and private inputs')
    require(not output.exists(), 'output already exists')
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.c1-grid-', dir=output.parent))
    try:
        for name in ('descriptor', 'rectangle', 'tile'):
            (stage / (name+'.bin')).write_bytes(getattr(result, name))
        out = Builder(0)
        for pack in result.packs:
            out.add(0x3b801, pack, 16)
        (stage / 'packs.bin').write_bytes(out.data)
        (stage / 'pack_ids.json').write_text(json.dumps(result.pack_ids, sort_keys=True) + '\n')
        (stage / 'proof.json').write_text(json.dumps(result.report, indent=2, sort_keys=True) + '\n')
        os.rename(stage, output)
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mw-root', type=Path, default=DEFAULT_MW)
    parser.add_argument('--carbon-root', type=Path, default=DEFAULT_CARBON)
    parser.add_argument('--out', type=Path, required=True, help='new directory outside checkout')
    parser.add_argument('--shift', nargs=2, type=float, default=(20480., 0.), metavar=('X', 'Z'))
    parser.add_argument('--segment-offset', type=int, default=5790)
    parser.add_argument('--cell-section', type=int, default=2500)
    parser.add_argument('--tile-section', type=int, default=2500)
    parser.add_argument('--pack-ids', type=Path, help='JSON source selector -> target selector')
    args = parser.parse_args(argv)
    paths = [root / name for root, base in ((args.carbon_root, 'L5RA'), (args.mw_root, 'L2RA'))
             for name in (base+'.BUN', 'STREAM'+base+'.BUN')]
    if not all(p.is_file() for p in paths):
        print('SKIP: private collision archives absent')
        return 3
    carbon, cs, _ = load_index(args.carbon_root, 'L5RA')
    mw, ms, _ = load_index(args.mw_root, 'L2RA')
    mapping = {int(k): v for k, v in json.loads(args.pack_ids.read_text()).items()} if args.pack_ids else None
    result = merge(carbon, cs, mw, ms, shift=args.shift, segment_offset=args.segment_offset,
                   pack_ids=mapping, cell_section=args.cell_section, tile_section=args.tile_section)
    output = args.out.resolve()
    require(all(not output.is_relative_to(root.resolve()) for root in (args.mw_root, args.carbon_root)),
            'output must be outside supplied private inputs')
    write_outputs(result, output)
    print(json.dumps(result.report, sort_keys=True))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (FormatError, OSError, ValueError, KeyError, struct.error) as error:
        raise SystemExit(str(error))
