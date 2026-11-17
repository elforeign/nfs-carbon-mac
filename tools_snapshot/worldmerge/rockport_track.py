"""Build a collision-only Rockport track (SkipFE track 2000) offline.

Uses the L5RB index scaffold, the whole-grid converter, and region's aligned
chunk writers. Only sections 2400/2500/2600 are needed: empty X00, the complete
tile in Y00, and unchanged packs in Z00. No scenery is included. Native loading
and driving still require separate game proof.

The single spawn-clearance parameter defaults to 0.81 m [I], from one settled
car observation; the native spawn-height rule has not been decoded. Eight
octant targets lie halfway from the road-bounds centre to its bounding ellipse
at 45-degree intervals. Each chooses the nearest strictly grounded road node.
"""
import argparse
import hashlib
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
import collision
import ground
from formats import Chunk, FormatError, TrackIndex, chunks, require, u32
from merge import DEFAULT_MW, DEFAULT_CARBON, load_index
from region import (Builder, append_collision, collision_body,
                    collision_cells, collision_tags, one)

ROOT = HERE.parents[1]
ALWAYS_LOADED = (2500, 2400, 2600)  # 007A4680
SPAWN_CLEARANCE = .81  # [I], not a decoded spawn-height policy
D2 = {
    'status': 'no fixed array, cap or tile-byte check in the two inspected bodies',
    '007E9D10': {
        'decomp': 'NFSC_007d3030.c:16142',
        'translated': 'NFSC_46.c:34849',
        'evidence': '007E9D5F..007E9DA4: allocate/reuse rows*columns*4; clear rows*columns slots'},
    '00800050': {
        'decomp': 'NFSC_007f5030.c:6421',
        'translated': 'NFSC_47.c:25851',
        'evidence': '00800083..00800099: pass bound cells, rectangle and stride to 007F5F60'},
    'rectangle_slots': 8800, 'pointer_bytes': 35200,
    'limit_of_evidence': 'static body inspection; runtime allocation/loading unproved',
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def source_proof(path, role):
    path = Path(path).resolve()
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(8 << 20), b''):
            digest.update(block)
    return dict(role=role, path=str(path), bytes=path.stat().st_size, sha256=digest.hexdigest())


def empty_visibility(position):
    """Native directory shape from region.visibility, with zero scenery rows."""
    out = Builder(position + 8)
    out.add(0x34151, struct.pack('<II', 40, 0) + bytes(1024))
    out.add(0x34152, b'')
    out.add(0x34156, b'', 16)
    out.add(0x34155, b'')
    out.add(0x34153, b'')
    return bytes(out.data)


def build(template, converted):
    """Serialize a track pair; section records retain L5RB resident metadata."""
    payload = Builder(0)
    append_collision(payload, converted.tile, converted.packs)
    split = next(c.offset for c in chunks(payload.data) if c.kind == 0x3b801)
    sections = {2400: Chunk(0, b'').encode(), 2500: bytes(payload.data[:split]),
                2600: bytes(payload.data[split:])}
    stream = Builder(0)
    records = []
    for old in template.sections:
        if old.number in sections:
            stream.pad(2048)
            data = sections[old.number]
            records.append(old.replace(offset=stream.position, size=len(data)))
            stream.data += data
    require({s.number for s in records} == set(ALWAYS_LOADED), 'template resident section absent')
    # Same conservative scaffold selection as region.region_index. Visibility
    # has no scenery references; the resident sections are requested natively.
    keep = {0x34112, 0x80034147, 0x34250, 0x8003b000, 0x34110,
            0x34113, 0x34111, 0x34108, 0x34109, 0x3b800, 0x3414d}
    index = Builder(0)
    for top in template.parts:
        if top.kind == 0x80034150:
            index.pad(16)
            index.add(top.kind, empty_visibility(index.position))
        elif top.kind in keep:
            index.pad(16)
            if top.kind == 0x34110:
                index.add(top.kind, b''.join(s.raw for s in records))
            elif top.kind == 0x3b800:
                index.add(top.kind, converted.map_data, 16)
            else:
                index.add(top.kind, top.payload)
    return bytes(index.data), bytes(stream.data)


def check_track(index_data, stream_data):
    """Read serialized bytes using the decoded Carbon acceptance conditions.

    00813850 reads origin, spacing and row/column dimensions from CGrd.
    007F5F60 uses quotient=rowZ, remainder=columnX, section or -1 match,
    then slot=localRow*countX+localColumn. Native signed upper-bound tests
    alone allow negative locals; reject those here as unsafe pointer writes.
    Pack selectors must fit the 0xa8c table. Never use proof.json as evidence.
    """
    idx = TrackIndex(index_data)
    idx.validate(len(stream_data))
    require(idx.encode() == index_data, 'index round trip differs')
    require({s.number for s in idx.sections} == set(ALWAYS_LOADED),
            'track must contain exactly the always-loaded sections')
    raw = collision_body(one(idx.parts, 0x3b800))
    tags = collision_tags(raw, collision.CDAT)
    require(collision.CGCN not in tags, 'flat CDat cells are not native Carbon layout')
    desc = collision.tag_data(raw, tags[collision.CGRD])
    require(tags[collision.CGRD][2] == 1 and len(desc) == 40, 'descriptor must be 40 bytes')
    ox, oy, oz, _ = struct.unpack_from('<4f', desc)
    cell = struct.unpack_from('<f', desc, 16)[0]
    rows, columns = struct.unpack_from('<II', desc, 24)
    require(all(math.isfinite(v) for v in (ox, oy, oz, cell)) and cell > 0
            and 0 < rows * columns <= 65536, 'invalid descriptor dimensions')
    rt = tags[collision.RECT]
    require(rt[1] == 0xa03 and rt[2] == 1, 'one 10-byte rectangle required')
    rect = struct.unpack('<5H', collision.tag_data(raw, rt))
    section, r0, c0, nx, nz = rect
    require(section in ALWAYS_LOADED and nx > 0 and nz > 0
            and r0 + nz <= rows and c0 + nx <= columns, 'rectangle outside resident grid')
    packs, cells, tile_sections, tile_bytes = {}, [], [], 0
    for s in idx.sections:
        data = stream_data[s.offset:s.offset + s.size]
        for chunk in chunks(data):
            if chunk.kind not in (0, 0x3b801, 0x3b802):
                raise FormatError('unexpected content in collision-only section')
            if chunk.kind == 0:
                continue
            body = collision_body(chunk)
            require(u32(body) == len(body) - 16, 'collision body extent differs')
            if chunk.kind == 0x3b802:
                require(s.number in ALWAYS_LOADED and u32(body, 4) == s.number == section,
                        'tile must reside in its always-loaded section')
                tile_sections.append(s.number)
                tile_bytes += len(body)
                tile = body[16:]
                cells += collision_cells(tile, collision_tags(tile, 0x41727469)[collision.CGCN])
            else:
                key = u32(body, 4)
                require(s.number == 2600, 'pack not in resident Z00')
                require(0 < key < 0xa8c and key not in packs, 'pack id invalid or duplicate')
                ci = collision_tags(body[16:], 0x41727469)[0x63690000]
                require(ci[1] >> 8 == 64 * ci[2], 'pack instance stride differs')
                packs[key] = ci[2]
    require(tile_sections == [2500], 'one Y00 tile required')
    ids, slots, families, rejected = set(), set(), [0] * 4, 0
    roads = collision_tags(raw, collision.RNGP)
    segment_count = roads[0x524e7367][2]
    for record in cells:
        cid, cell_section = struct.unpack_from('<HH', record, 4)
        row, col = divmod(cid, columns)
        local_row, local_col = row - r0, col - c0
        accepted = ((cell_section == section or section == 0xffff)
                    and 0 <= local_row < nz and 0 <= local_col < nx)
        rejected += not accepted
        require(cid < rows * columns and cid not in ids, 'duplicate/out-of-grid cell id')
        require(accepted, f'native cell acceptance rejects {cid}')
        slot = local_row * nx + local_col
        require(slot not in slots, 'duplicate native cell slot')
        ids.add(cid); slots.add(slot)
        for k, family in enumerate(collision.families(record)):
            families[k] += len(family) // 4
            if k == 0:
                for ref, in struct.iter_unpack('<I', family):
                    require(ref >> 16 in packs and (ref & 65535) < packs[ref >> 16],
                            'unresolved collision pack reference')
            if k == 3:
                require(all(v < segment_count for v, in struct.iter_unpack('<I', family)),
                        'family-3 value exceeds preserved RNsg count')
    return dict(cells=len(ids), packs=len(packs), rejects=rejected, reference_families=families,
                rectangle=list(rect), descriptor_bytes=len(desc), tile_bytes=tile_bytes,
                pointer_slots=nx * nz, pointer_bytes=nx * nz * 4)


def f32(value):
    return struct.unpack('<f', struct.pack('<f', value))[0]


def select_starts(world, measurement, spawn_clearance=SPAWN_CLEARANCE):
    require(math.isfinite(spawn_clearance) and 0 < spawn_clearance <= 2,
            'spawn clearance must be finite and within (0,2] metres')
    nodes = world.nodes
    lo = [min(p[k] for p in nodes) for k in (0, 2)]
    hi = [max(p[k] for p in nodes) for k in (0, 2)]
    centre = [(a + b) / 2 for a, b in zip(lo, hi)]
    radii = [(b - a) / 4 for a, b in zip(lo, hi)]
    grounded = [r for r in measurement['records'] if r['cause'] == 'grounded']
    require(grounded, 'no strictly grounded road nodes')
    starts = []
    for octant in range(8):
        angle = octant * math.pi / 4
        target = [centre[0] + radii[0] * math.cos(angle), centre[1] + radii[1] * math.sin(angle)]
        nearest = min(grounded, key=lambda r: ((r['x'] - target[0]) ** 2
                                               + (r['z'] - target[1]) ** 2, r['node']))
        x, z, height = nearest['x'], nearest['z'], f32(nearest['height'] + spawn_clearance)
        render = [z, -x, height]
        physics = [-render[1], render[2], render[0]]
        require(physics == [x, height, z], 'render/physics round trip differs')
        hit = world.find_face_below(x, z, height, section=2500)
        require(hit is not None and 0 <= height - hit.height <= 2
                and hit.height == nearest['height'], 'start does not sit above its oracle ground')
        starts.append(dict(octant=octant, target_physics_xz=target, node=nearest['node'],
                           road_physics_xyz=list(nodes[nearest['node']]), physics_xyz=physics,
                           render_xyz=render, skipfe_start=','.join(format(v, '.9g') for v in render),
                           ground_height=hit.height, clearance=height - hit.height,
                           cell=hit.cell, face={k: v for k, v in vars(hit.face).items() if k != 'vertices'}))
    require(len({s['node'] for s in starts}) == 8, 'octant targets select duplicate starts')
    return starts


def summary(measurement):
    return {k: v for k, v in measurement.items() if k != 'records'}


def write_outputs(output, index, stream, report, sources=()):
    """Atomically create an external scratch directory; never replace outputs."""
    out = Path(output).expanduser().resolve()
    require(not out.is_relative_to(ROOT.resolve()), 'outputs must be outside the checkout')
    require(not any((p / '.git').exists() for p in (out, *out.parents)),
            'outputs must be outside every checkout')
    for root in sources:
        root = Path(root).resolve()
        require(not out.is_relative_to(root) and not root.is_relative_to(out), 'output overlaps source tree')
    require(not out.exists(), 'output already exists')
    check_track(index, stream)
    out.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.rockport-', dir=out.parent))
    try:
        (stage / 'L2RA.BUN').write_bytes(index)
        (stage / 'STREAML2RA.BUN').write_bytes(stream)
        check_track((stage / 'L2RA.BUN').read_bytes(), (stage / 'STREAML2RA.BUN').read_bytes())
        world = ground.World.load(stage, 'L2RA')
        measured = ground.measure_nodes(world)
        require(summary(measured) == report['ground'], 'serialized grounding differs')
        require(select_starts(world, measured, report['spawn_clearance_m']) == report['starts'],
                'serialized starts differ')
        (stage / 'proof.json').write_text(json.dumps(report, indent=2) + '\n')
        os.rename(stage, out)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    return out


def prepare(mw_root=DEFAULT_MW, carbon_root=DEFAULT_CARBON, *, spawn_clearance=SPAWN_CLEARANCE):
    source, source_stream, _ = load_index(mw_root, 'L2RA')
    native, _, _ = load_index(carbon_root, 'L5RA')
    template, _, _ = load_index(carbon_root, 'L5RB')
    converted = collision.convert(source, source_stream, native)
    index, stream = build(template, converted)
    checked = check_track(index, stream)
    world = ground.World(source, source_stream)
    measured = ground.measure_nodes(world)
    # Check the bytes through J2's file reader, including indexed section extents.
    with tempfile.TemporaryDirectory(prefix='rockport-check-') as temp:
        tracks = Path(temp)
        (tracks / 'L2RA.BUN').write_bytes(index)
        (tracks / 'STREAML2RA.BUN').write_bytes(stream)
        built_world = ground.World.load(tracks, 'L2RA')
        built_measurement = ground.measure_nodes(built_world)
        require(summary(built_measurement) == summary(measured), 'built/source grounding differs')
        starts = select_starts(built_world, built_measurement, spawn_clearance)
    require(checked['cells'] == converted.report['cells'] and checked['packs'] == converted.report['packs']
            and checked['reference_families'] == converted.report['reference_families'], 'build lost collision data')
    files = [(Path(mw_root) / 'L2RA.BUN', 'source index and RNgp'),
             (source_stream, 'source packs'), (Path(carbon_root) / 'L5RA.BUN', 'native descriptor extension'),
             (Path(carbon_root) / 'L5RB.BUN', 'index scaffold and resident section metadata')]
    conversion = dict(converted.report)
    conversion['inferred'] = [v for v in conversion['inferred'] if '(D2)' not in v]
    report = dict(track=2000, base='L2RA', collision_only=True, sources=[source_proof(p, role) for p, role in files],
                  checker=checked, ground=summary(measured), d2=D2,
                  conversion=conversion, spawn_clearance_m=spawn_clearance,
                  spawn_clearance_status='[I] single observed settling height; native spawn rule not decoded',
                  start_selection='nearest strict grounded node to eight ellipse octant centres; 0 = +physicsX',
                  starts=starts, map_sha256=sha(converted.map_data), tile_sha256=sha(converted.tile),
                  packs_sha256=sha(b''.join(converted.packs)),
                  outputs={'L2RA.BUN': dict(bytes=len(index), sha256=sha(index)),
                           'STREAML2RA.BUN': dict(bytes=len(stream), sha256=sha(stream))},
                  unproven=['Carbon loading and residency', 'AI driving and native spawn behavior',
                            'surface/group semantics', 'design runs A/B and eight live starts'])
    return index, stream, report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mw-root', type=Path, default=DEFAULT_MW)
    parser.add_argument('--carbon-root', type=Path, default=DEFAULT_CARBON)
    parser.add_argument('--out', type=Path, required=True, help='new directory in external scratch')
    parser.add_argument('--spawn-clearance', type=float, default=SPAWN_CLEARANCE, help='metres above oracle face [I]')
    args = parser.parse_args(argv)
    try:
        index, stream, report = prepare(args.mw_root, args.carbon_root, spawn_clearance=args.spawn_clearance)
        write_outputs(args.out, index, stream, report, (args.mw_root, args.carbon_root))
        print(json.dumps(dict(output=str(args.out), checker=report['checker'], ground=report['ground'],
                              files=report['outputs']), sort_keys=True))
    except FileNotFoundError as exc:
        print(f'SKIP: private assets absent: {exc}', file=sys.stderr)
        return 3
    except (OSError, ValueError, KeyError, struct.error) as exc:
        print(f'FAIL: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
