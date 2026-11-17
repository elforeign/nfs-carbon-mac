"""Append two native road graphs in one CARP map, without connecting them.

Inputs and return values are unwrapped 0x3b800 CARP bytes, as returned by
region.collision_body. The first graph's IDs are stable. ``shift`` is physics
(X,Z); render XYZ = (physics Z, -physics X, physics Y). Coordinates are native
float32: exact encoded translation is checked separately from inverse rounding.
Only RNgp directory entries and its suffix are rebuilt; other map bytes survive.
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
sys.path.insert(0, str(HERE))
from formats import FormatError, require
from merge import DEFAULT_CARBON, DEFAULT_MW, load_index
from region import collision_body, collision_tags, one

RNGP = 0x524e6770
HEADER, NODES, PROFILES, ROADS, SEGMENTS = (
    0x524e6864, 0x524e6e64, 0x524e7066, 0x524e7264, 0x524e7367)
TABLES = ((NODES, 'nodes', 32, 1), (SEGMENTS, 'segments', 22, 2),
          (PROFILES, 'profiles', 64, 0), (ROADS, 'roads', 8, 4))
DEFAULT_SHIFT = (20480.0, 0.0)
ROOT = HERE.parents[1]


def _shift(value):
    require(len(value) == 2 and all(math.isfinite(v) for v in value),
            'shift must be two finite physics X,Z values')
    return tuple(value)


def _limits(counts):
    for key in ('nodes', 'segments', 'profiles'):
        require(0 <= counts[key] <= 32768, f'{key} exceeds signed-short capacity 32768')
    require(0 <= counts['roads'] <= 16382, 'roads exceeds A* capacity 16382')


def _source(raw):
    """Writer-side directory/extent checks; the checker uses its own reader."""
    tags = collision_tags(raw, RNGP)
    require(set(tags) == {HEADER, NODES, SEGMENTS, PROFILES, ROADS}, 'RNgp tag set differs')
    h = tags[HEADER]
    require(h[2] == 1 and h[1] >> 8 == 14, 'RNhd must be one 14-byte header')
    header = struct.unpack_from('<7H', raw, h[3])
    require(header[3] == header[5] == header[6] == 0, 'unsupported RNhd intersection/reserved words')
    counts = {name: header[word] for _, name, _, word in TABLES}
    _limits(counts)
    data = {HEADER: raw[h[3]:h[3] + 14]}
    for key, name, stride, _ in TABLES:
        q, flags, count, p = tags[key]
        require(count == counts[name] and flags >> 8 == count * stride,
                f'{name} count/stride differs')
        data[key] = raw[p:p + count * stride] if count else b''
    for q, flags, count, p in tags.values():
        require(flags & 0xff == 2, 'unsupported RNgp flags')
        require(not count or p % 16 == 0, 'unaligned RNgp payload')
    return tags, counts, data


def _suffix_start(raw, road_tags):
    """Prove the directory and other groups precede the replaced road suffix."""
    start = min(t[3] for t in road_tags.values() if t[2])
    groups = (struct.unpack_from('<I', raw, 4)[0] >> 5) + struct.unpack_from('<I', raw, 8)[0]
    p = struct.unpack_from('<I', raw, 12)[0] * 16
    require(16 <= p <= start - 16 * groups, 'CARP group directory crosses road suffix')
    for g in range(p, p + 16 * groups, 16):
        key, _, n, relative = struct.unpack_from('<4I', raw, g)
        first = g + relative * 16
        require(0 <= first <= start - 16 * n, 'CARP tag directory crosses road suffix')
        if key != RNGP:
            for q in range(first, first + 16 * n, 16):
                _, flags, count, relative = struct.unpack_from('<4I', raw, q)
                require(not count or 0 <= q + relative <= start - (flags >> 8),
                        'non-road payload overlaps RNgp suffix')
    spans = sorted((p, p + (flags >> 8)) for _, flags, n, p in road_tags.values() if n)
    require(all(a[1] <= b[0] for a, b in zip(spans, spans[1:])), 'overlapping road arrays')
    return start


def merge(carbon_map, mw_map, *, shift=DEFAULT_SHIFT):
    """Return Carbon's map with Carbon-first arrays and appended shifted IDs.

    Node/segment/profile/road offsets are the first graph's respective counts.
    Degree bounds active adjacency; inactive slots, -1 sentinels, flags, speech
    IDs, profile descriptors and all other record bytes are retained verbatim.
    """
    shift = _shift(shift)
    ct, cc, ca = _source(carbon_map)
    _, mc, ma = _source(mw_map)
    counts = {name: cc[name] + mc[name] for _, name, _, _ in TABLES}
    _limits(counts)
    nodes, segments = bytearray(ma[NODES]), bytearray(ma[SEGMENTS])
    for j in range(mc['nodes']):
        p = j * 32
        require(struct.unpack_from('<H', nodes, p + 12)[0] == j, 'source node self ID differs')
        for axis, distance in ((0, shift[0]), (2, shift[1])):
            if distance:
                value = struct.unpack_from('<f', nodes, p + axis * 4)[0] + distance
                require(math.isfinite(value) and abs(value) <= 3.4028234663852886e38,
                        'translated position exceeds float32')
                struct.pack_into('<f', nodes, p + axis * 4, value)
        struct.pack_into('<H', nodes, p + 12, j + cc['nodes'])
        profile = struct.unpack_from('<h', nodes, p + 14)[0]
        require(-1 <= profile < mc['profiles'], 'source profile reference outside graph')
        if profile != -1:
            struct.pack_into('<h', nodes, p + 14, profile + cc['profiles'])
        degree = nodes[p + 16]
        require(degree <= 7, 'source degree exceeds seven slots')
        for slot in range(degree):
            q = p + 18 + slot * 2
            segment = struct.unpack_from('<H', nodes, q)[0]
            require(segment < mc['segments'], 'source adjacency outside graph')
            struct.pack_into('<H', nodes, q, segment + cc['segments'])
    for i in range(mc['segments']):
        p = i * 22
        require(struct.unpack_from('<H', segments, p + 8)[0] == i, 'source segment self ID differs')
        for q in (p, p + 2):
            node = struct.unpack_from('<H', segments, q)[0]
            require(node < mc['nodes'], 'source endpoint outside graph')
            struct.pack_into('<H', segments, q, node + cc['nodes'])
        road = struct.unpack_from('<h', segments, p + 6)[0]
        require(-1 <= road < mc['roads'], 'source road reference outside graph')
        if road != -1:
            struct.pack_into('<h', segments, p + 6, road + cc['roads'])
        struct.pack_into('<H', segments, p + 8, i + cc['segments'])
    arrays = {NODES: ca[NODES] + nodes, SEGMENTS: ca[SEGMENTS] + segments,
              PROFILES: ca[PROFILES] + ma[PROFILES], ROADS: ca[ROADS] + ma[ROADS],
              HEADER: struct.pack('<7H', counts['profiles'], counts['nodes'],
                                  counts['segments'], 0, counts['roads'], 0, 0)}
    out = bytearray(carbon_map[:_suffix_start(carbon_map, ct)])
    tag_counts = {key: counts[name] for key, name, _, _ in TABLES}
    tag_counts[HEADER] = 1
    for key, (q, flags, _, _) in ct.items():
        out += bytes(-len(out) % 16)
        payload = arrays[key]
        require(len(payload) < 1 << 24, 'RNgp extent exceeds directory encoding')
        n = tag_counts[key]
        struct.pack_into('<4I', out, q, key, len(payload) << 8 | (flags & 0xff), n,
                         len(out) - q if n else 0)
        out += payload
    out += bytes(-len(out) % 16)
    result = bytes(out)
    check(result, carbon_map, mw_map, shift=shift)
    return result


def _reader(raw):
    """Independent native reader: no writer parser, traversal or validation.

    NFSC_007d3030.c:16235-16251 reads degree +16 and u16 slots +18.
    NFSC_007f5030.c:747-762 uses signed node self +12, stride 32;
    :837-864 uses signed segment indices. NFSC_007d3030.c:16749-16775
    reads endpoint u16s, node stride 32 and signed profile +14/stride 64.
    """
    def words(p, n):
        require(0 <= p <= len(raw) - 4 * n, 'reader directory truncated')
        return struct.unpack_from('<' + 'I' * n, raw, p)

    magic, packed, extra, relative = words(0, 4)
    require(magic == 0x43415250, 'reader CARP magic differs')
    start, groups = relative * 16, (packed >> 5) + extra
    require(16 <= start <= len(raw) - groups * 16, 'reader group directory truncated')
    directories, found = [], []
    for p in range(start, start + groups * 16, 16):
        key, _, count, rel = words(p, 4)
        q = p + rel * 16
        require(0 <= q <= len(raw) - count * 16, 'reader tag directory truncated')
        directories.append((p, p + 16))
        directories.append((q, q + count * 16))
        if key == RNGP:
            found.append((q, count))
    require(len(found) == 1, 'reader requires exactly one RNgp group')
    q, n = found[0]
    tags, data, spans = {}, {}, []
    for p in range(q, q + n * 16, 16):
        key, flags, count, rel = words(p, 4)
        size = flags >> 8
        offset = p + rel
        require(key not in tags and flags & 255 == 2, 'reader duplicate tag/unsupported flags')
        require((count != 0 or size == 0) and
                (not count or (offset % 16 == 0 and 0 <= offset <= len(raw) - size)),
                'reader payload extent/alignment differs')
        tags[key] = (p, flags, count, offset if count else 0)
        data[key] = raw[offset:offset + size] if count else b''
        if count:
            spans.append((offset, offset + size))
    require(set(tags) == {HEADER, NODES, SEGMENTS, PROFILES, ROADS}, 'reader RNgp tables differ')
    spans.sort()
    require(all(a[1] <= b[0] for a, b in zip(spans, spans[1:])), 'reader arrays overlap')
    require(all(b <= spans[0][0] for _, b in directories), 'reader arrays overlap directory')
    require(tags[HEADER][2] == 1 and len(data[HEADER]) == 14, 'reader RNhd extent differs')
    profiles, nodes, segments, intersections, roads, zero1, zero2 = struct.unpack('<7H', data[HEADER])
    require(intersections == zero1 == zero2 == 0, 'reader unsupported RNhd words')
    require(nodes <= 32768 and segments <= 32768 and profiles <= 32768 and roads <= 16382,
            'reader count exceeds signed-index/A* capacity')
    counts = dict(nodes=nodes, segments=segments, profiles=profiles, roads=roads)
    for key, count, stride in ((NODES, nodes, 32), (SEGMENTS, segments, 22),
                               (PROFILES, profiles, 64), (ROADS, roads, 8)):
        require(tags[key][2] == count and len(data[key]) == count * stride,
                'reader count/stride differs')
    ns = list(struct.iter_unpack('<3fHhBB7H', data[NODES]))
    ss = list(struct.iter_unpack('<3Hh4H6b', data[SEGMENTS]))
    for i, node in enumerate(ns):
        require(all(math.isfinite(v) for v in node[:3]), 'reader nonfinite node position')
        require(node[3] == i, 'reader duplicated or misplaced node self ID')
        require(-1 <= node[4] < profiles and node[5] <= 7, 'reader profile/degree outside graph')
        active = node[7:7 + node[5]]
        require(len(set(active)) == len(active), 'reader duplicate adjacency slot')
        for segment in active:
            require(segment < segments and i in ss[segment][:2], 'reader adjacency not reciprocal')
    for i, segment in enumerate(ss):
        require(segment[4] == i, 'reader duplicated or misplaced segment self ID')
        require(-1 <= segment[3] < roads, 'reader road reference outside graph')
        for node_id in segment[:2]:
            require(node_id < nodes, 'reader endpoint outside graph')
            node = ns[node_id]
            require(i in node[7:7 + node[5]], 'reader endpoint not reciprocal')
    return counts, data, ns, ss, tags


def check(merged, carbon_map, mw_map, *, shift=DEFAULT_SHIFT):
    """Reread bytes, enforce capacities/reciprocity, then undo ID offsets.

    All source bytes except shifted float32 positions must recover bit-exact.
    Positions must equal the exact IEEE float32 encoding of source + shift.
    Report separately whether subtracting shift also recovers original bits.
    Custom translations must pass the same explicit ``shift`` as merge().
    """
    shift = _shift(shift)
    cc, ca, _, _, ct = _reader(carbon_map)
    mc, ma, _, _, _ = _reader(mw_map)
    counts, data, ns, ss, tags = _reader(merged)
    require(counts == {k: cc[k] + mc[k] for k in cc}, 'merged counts differ from source sums')
    # Outside RNgp's suffix and directory entries, the original container stays exact.
    first = min(t[3] for t in ct.values() if t[2])
    require(min(t[3] for t in tags.values() if t[2]) == first, 'road suffix start moved')
    old, new = bytearray(carbon_map[:first]), bytearray(merged[:first])
    for key in ct:
        require(ct[key][0] == tags[key][0], 'road directory moved')
        p = ct[key][0]
        old[p:p + 16] = new[p:p + 16] = bytes(16)
    require(old == new, 'non-road container bytes changed')
    inverse = {}
    for key, name, stride, _ in TABLES:
        boundary = cc[name] * stride
        require(data[key][:boundary] == ca[key], f'first graph {name} bytes changed')
        inverse[key] = bytearray(data[key][boundary:])
    rounded, inverse_errors, steps = 0, [], []
    for j, node in enumerate(ns[cc['nodes']:]):
        # Reconstruct a whole independent reader record, including inactive slots.
        values = list(node)
        values[3] -= cc['nodes']
        if values[4] != -1:
            values[4] -= cc['profiles']
        for slot in range(values[5]):
            values[7 + slot] -= cc['segments']
        original = ma[NODES][j * 32:(j + 1) * 32]
        for axis, distance in ((0, shift[0]), (2, shift[1])):
            before = struct.unpack_from('<f', original, axis * 4)[0]
            target = struct.pack('<f', before + distance) if distance else original[axis * 4:axis * 4 + 4]
            actual = struct.pack('<f', values[axis])
            require(actual == target, 'shifted position differs from float32(source + shift)')
            back = struct.pack('<f', values[axis] - distance) if distance else actual
            rounded += int(back != original[axis * 4:axis * 4 + 4])
            inverse_errors.append(abs((values[axis] - distance) - before))
            if distance and values[axis]:
                steps.append(2.0 ** max(-149, math.floor(math.log2(abs(values[axis]))) - 23))
            values[axis] = before
        inverse[NODES][j * 32:(j + 1) * 32] = struct.pack('<3fHhBB7H', *values)
    for i, segment in enumerate(ss[cc['segments']:]):
        values = list(segment)
        values[0] -= cc['nodes']
        values[1] -= cc['nodes']
        if values[3] != -1:
            values[3] -= cc['roads']
        values[4] -= cc['segments']
        require(min(values[0], values[1], values[4]) >= 0 and values[3] >= -1,
                'appended segment points into first graph')
        inverse[SEGMENTS][i * 22:(i + 1) * 22] = struct.pack('<3Hh4H6b', *values)
    for key, name, _, _ in TABLES:
        require(inverse[key] == ma[key], f'appended {name} do not recover source bytes')
    longest_segment = max((s[2] for s in ss), default=0) * 1000.0 / 65535
    longest_road = max((v[1] for v in struct.iter_unpack('<4H', data[ROADS])), default=0) * 4000.0 / 65535
    return {
        'counts': counts, 'reference_errors': 0, 'duplicate_ids': 0,
        'array_bytes': sum(len(data[k]) for k, _, _, _ in TABLES),
        'limits': {'nodes': 32768, 'segments': 32768, 'profiles': 32768, 'roads': 16382},
        'margins': {k: limit - counts[k] for k, limit in
                    (('nodes', 32768), ('segments', 32768), ('profiles', 32768), ('roads', 16382))},
        'offsets': cc, 'shift_physics_xyz': [shift[0], 0.0, shift[1]],
        'shift_render_xyz': [shift[1], -shift[0], 0.0],
        'recovery': {'first_graph_bit_exact': True, 'appended_nonposition_bytes_bit_exact': True,
                     'positions_exact_float32_translation': True,
                     'subtract_shift_bit_exact': rounded == 0,
                     'rounded_coordinates': rounded,
                     'max_inverse_error_m': max(inverse_errors, default=0),
                     'float32_steps_m': sorted(set(steps))},
        'longest_segment_m': longest_segment, 'segment_encoding_max_m': 1000,
        'longest_road_m': longest_road, 'road_encoding_max_m': 4000,
        'astar_states': 2 * counts['roads'] + 4,
        'bridge_segments': 0,
        'opaque_unreconciled': ['segment flags', 'road speech IDs', 'road byte +5'],
        'unverified': ['native loader acceptance', 'directed routes', 'speech banks'],
        'sha256': hashlib.sha256(merged).hexdigest(),
    }


def write_outputs(merged, summary, output):
    """Atomically publish a new directory outside the checkout; never overwrite."""
    output = Path(output).resolve()
    require(not output.is_relative_to(ROOT.resolve()), 'output must be outside the checkout')
    require(not output.exists(), 'output already exists')
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.c1-roads-', dir=output.parent))
    try:
        (stage / 'map.carp').write_bytes(merged)
        (stage / 'summary.json').write_text(json.dumps(summary, indent=2, sort_keys=True) + '\n')
        os.rename(stage, output)
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--carbon-root', type=Path, default=DEFAULT_CARBON)
    parser.add_argument('--mw-root', type=Path, default=DEFAULT_MW)
    parser.add_argument('--shift', nargs=2, type=float, default=DEFAULT_SHIFT, metavar=('X', 'Z'))
    parser.add_argument('--out', type=Path, required=True, help='new directory outside the checkout')
    args = parser.parse_args(argv)
    inputs = [(args.carbon_root, 'L5RA'), (args.mw_root, 'L2RA')]
    if not all((root / name).is_file() for root, base in inputs
               for name in (base + '.BUN', 'STREAM' + base + '.BUN')):
        print('SKIP: private track archives unavailable')
        return 3
    maps = [collision_body(one(load_index(root, base)[0].parts, 0x3b800)) for root, base in inputs]
    merged = merge(*maps, shift=args.shift)
    summary = check(merged, *maps, shift=args.shift)
    write_outputs(merged, summary, args.out)
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (FormatError, OSError, OverflowError, struct.error) as error:
        raise SystemExit(str(error))
