"""Verify a merged-pair load against serialized rows and native diagnostics.

Live proof: both merged spawns bind 4,165 cells in 167x365; the 159-column
control binds 2,412 in 167x159 and is rejected despite zero byte mismatches.
Ground misses: good Rockport 0/95, broken 63/64 (the car falls).
The control retains CGrd and all cells, shortening only the bound rectangle.
Full observations are kept with the private Carbon notes.
C3 requires every sample through arrival: loading=missing=skipped=0.
Offline controls: good 0/0/0; injected loading 1 or missing 1 fails;
an incomplete drive also fails even with all three counters zero.
Route offset: on-line fixture 0 m passes, lateral control 12.001 m fails
at the fixed 12.0 m limit; the polyline comes only from archive road nodes.
Landing lip: first actual-car sample at s>=34.05 (forward) / s<=0.2
(reverse) must have Y>=213.22 / 213.27. Good fixture 213.22 / 213.27;
retained broken forward: never reached the landing lip: furthest s 30.93,
height 212.04; arrival also FAIL. No height or lateral window is applied.
"""
import argparse
import bisect
import hashlib
import json
import math
from pathlib import Path
import re
import struct
import subprocess
import sys

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / 'tools_snapshot/worldmerge'))
import private_census
from formats import TrackIndex, Chunk
import visibility

PAIR_SHA256 = {
    'L5RA.BUN': 'cc154fc5746163678b855231301857105de67c50644527171228973172fa3b7e',
    'STREAML5RA.BUN': '0ccd820a2d83a1a6c95b3393f26d59cd030644e244cf06c2c7e0f419de9148b7',
}
# C3 pair includes converted prop rows and GlossyWindow GLASS_REFLECT with
# retained/reordered normals and the source-effect-5/1 identity words.
C3_PAIR_SHA256 = {
    'L5RA.BUN': '574ddbe77352a8c6d0b315612a0578ec0c9f4a013f9aee5a5b416d08ec8b3228',
    'STREAML5RA.BUN': '567d4487620828b792befddcad3c434b9070f12b025f4bca9ff22227dbafe5c8',
}
POOL, WORLD_SHARE, HEAP_MIB = 139059200, 71680000, 752
FRAME = re.compile(r'^f(\d+) t\d+ ')
GRID = re.compile(r'carbon_grid: event=(map|tile) tile=(\d+) cgrd=(\d+)x(\d+) '
                  r'grid=(\d+)x(\d+) cell=(\S+) rect=(\d+(?:,\d+){4}) bound=(\d+)\s*$')
MALLOC = re.compile(r'!malloc\(([0-9A-Fa-f]+),.*?\) -> ([0-9A-Fa-f]+) @0047668A')


def verify_pair(tracks, hashes=PAIR_SHA256):
    for name, expected in hashes.items():
        digest = hashlib.sha256()
        with (tracks / name).open('rb') as stream:
            for block in iter(lambda: stream.read(1 << 20), b''):
                digest.update(block)
        actual = digest.hexdigest()
        if actual != expected:
            raise ValueError(f'{name} SHA-256 {actual} != {expected}')


def world_rows(tracks, pinned=True):
    if pinned:
        verify_pair(tracks)
    index = TrackIndex((tracks / 'L5RA.BUN').read_bytes())
    index.validate((tracks / 'STREAML5RA.BUN').stat().st_size)
    table = visibility.read(visibility.payload_of(index))
    sizes = {s.number: s.size for s in index.sections}
    rows = {}
    for row in table.rows:
        if row.number in rows:
            raise ValueError(f'duplicate visibility row {row.number}')
        rows[row.number] = frozenset(row.entries) & sizes.keys()
    if 2500 not in sizes or not rows:
        raise ValueError('Y00 and visibility rows required')
    return rows, sizes


def broken_index(tracks, out, *, hashes=PAIR_SHA256):
    """Change exactly the serialized rectangle width; clone the stream."""
    verify_pair(tracks, hashes)
    from collision import CDAT, RECT
    from region import collision_body, collision_tags
    index = TrackIndex((tracks / 'L5RA.BUN').read_bytes())
    maps = [i for i, c in enumerate(index.parts) if c.kind == 0x3B800]
    if len(maps) != 1:
        raise ValueError('one MAP required')
    i, = maps
    part = index.parts[i]
    raw = collision_body(part)
    tag = collision_tags(raw, CDAT)[RECT]
    offset = len(part.payload) - len(raw) + tag[3]
    data = bytearray(part.payload)
    if struct.unpack_from('<5H', data, offset) != (2600, 0, 0, 365, 167):
        raise ValueError('merged rectangle required')
    struct.pack_into('<H', data, offset + 6, 159)
    index.parts[i] = Chunk(part.kind, bytes(data), part.offset)
    out.mkdir(parents=True, exist_ok=True)
    (out / 'L5RA.BUN').write_bytes(index.encode())
    subprocess.run(['cp', '-c', str(tracks / 'STREAML5RA.BUN'),
                    str(out / 'STREAML5RA.BUN')], check=True)
    return out


def broken_c3(tracks, out):
    """Remove only 220/260 from row 326, retaining its stride and spare bytes."""
    verify_pair(tracks, C3_PAIR_SHA256)
    index = TrackIndex((tracks / 'L5RA.BUN').read_bytes())
    container = next(c for c in index.parts if c.kind == visibility.CONTAINER)
    raw = bytearray(container.payload)
    # Locate the row in its serialized child rather than rebuilding the pair.
    from formats import chunks
    child = next(c for c in chunks(container.payload, base=container.offset + 8)
                 if c.kind == visibility.ROWS)
    pos = child.offset - (container.offset + 8) + 8
    for row in visibility.read_rows(child.payload):
        if row.number == 326:
            if not {220, 260} <= set(row.entries):
                raise ValueError('row 326 must contain both control sections')
            entries = tuple(n for n in row.entries if n not in (220, 260))
            struct.pack_into('<h', raw, pos + 16, len(entries))
            struct.pack_into(f'<{len(entries)}h', raw, pos + 18, *entries)
            break
        pos += len(row.encode())
    else:
        raise ValueError('row 326 absent')
    index.parts[index.parts.index(container)] = Chunk(container.kind, bytes(raw), container.offset)
    original = (tracks / 'L5RA.BUN').read_bytes()
    changed = index.encode()
    before = visibility.read(container.payload)
    after = visibility.read(visibility.payload_of(TrackIndex(changed)))
    if len(original) != len(changed) or len(before.rows) != len(after.rows):
        raise ValueError('control changed archive layout')
    for a, b in zip(before.rows, after.rows):
        if a.number == 326:
            if b.entries != tuple(n for n in a.entries if n not in (220, 260)):
                raise ValueError('control row delta differs')
        elif a != b:
            raise ValueError('control changed another row')
    allowed = set(range(container.offset + 8 + pos + 16,
                        container.offset + 8 + pos + 18 + 2 * len(row.entries)))
    delta = [p for p, (a, b) in enumerate(zip(original, changed)) if a != b]
    if not delta or not set(delta) <= allowed:
        raise ValueError('control changed unrelated bytes')
    out.mkdir(parents=True, exist_ok=True)
    (out / 'L5RA.BUN').write_bytes(changed)
    subprocess.run(['cp', '-c', str(tracks / 'STREAML5RA.BUN'),
                    str(out / 'STREAML5RA.BUN')], check=True)
    verify_pair(out, dict(C3_PAIR_SHA256, **{'L5RA.BUN': hashlib.sha256(changed).hexdigest()}))
    return dict(out=str(out), changed_bytes=len(delta), first_byte=min(delta), last_byte=max(delta),
                removed=[220, 260], other_bytes_identical=True)


def parse(lines):
    data = dict(samples=[], grids=[], chunks=[], drives=[], overlays=[], ticks=[])
    for number, line in enumerate(lines, 1):
        if 'census:' in line:
            frame = FRAME.match(line)
            if not frame:
                raise ValueError(f'line {number}: census frame missing')
            sample, = private_census.samples([line])
            sample['frame'] = int(frame[1])
            if data['samples'] and sample['frame'] <= data['samples'][-1]['frame']:
                raise ValueError('census frames unordered')
            data['samples'].append(sample)
        if 'carbon_grid:' in line:
            match = GRID.search(line)
            if not match:
                raise ValueError(f'line {number}: malformed grid')
            event, tile, cr, cc, gr, gc, cell, rect, bound = match.groups()
            data['grids'].append(dict(event=event, tile=int(tile), cgrd=(int(cr), int(cc)),
                grid=(int(gr), int(gc)), cell=float(cell), rect=tuple(map(int, rect.split(','))),
                bound=int(bound), line=line.strip()))
        if '@0047668A' in line:
            match = MALLOC.search(line)
            if match and int(match[2], 16):
                data['chunks'].append(int(match[1], 16))
        if 'autodrive: speed=' in line:
            distance = re.search(r'\bdistance=(\S+)_m\b', line)
            position = re.search(r'\bposition=(\S+)', line)
            if not distance or not position:
                raise ValueError('autodrive distance/position missing')
            point = tuple(map(float, position[1].split(',')))
            value = float(distance[1])
            if len(point) != 3 or not all(math.isfinite(v) for v in (*point, value)):
                raise ValueError('nonfinite autodrive sample')
            speed = re.search(r'\bspeed=(\S+)_mps\b', line)
            frame = FRAME.match(line)
            data['drives'].append(dict(distance=value, position=point,
                speed=float(speed[1]) if speed else None, frame=int(frame[1]) if frame else None))
        if 'c3tick:' in line:
            fields = dict(re.findall(r'(\w+)=([^\s]+)', line.split('c3tick:', 1)[1]))
            frame = FRAME.match(line)
            point = tuple(map(float, fields['position'].split(',')))
            velocity = tuple(map(float, fields['velocity'].split(',')))
            time = float(fields['time'])
            if (not frame or len(point) != 3 or len(velocity) != 3 or
                    not all(math.isfinite(v) for v in (*point, *velocity, time))):
                raise ValueError('invalid C3 tick')
            data['ticks'].append(dict(frame=int(frame[1]), tick=int(fields['tick']), time=time,
                position=point, velocity=velocity, wheels=int(fields['wheels'])))
        if 'PRIVATE TRACK OPEN ' in line:
            data['overlays'].append(line.strip())
    return data


def clocks(lines):
    result = []
    for line in lines:
        match = re.match(r't (\S+) frame (\d+) fps ', line)
        if match:
            time, frame = float(match[1]), int(match[2])
            if not math.isfinite(time) or (result and (time <= result[-1][1] or frame <= result[-1][0])):
                raise ValueError('diagnostic clocks unordered')
            result.append((frame, time))
    return result


def heap_peak(lines):
    values = []
    for line in lines:
        if line.startswith('#') or not line.strip():
            continue
        fields = line.split('|')
        if len(fields) != 3:
            raise ValueError('malformed heap row')
        value = float(fields[2].split()[3])
        if not math.isfinite(value) or value < 0:
            raise ValueError('invalid heap peak')
        values.append(value)
    return max(values, default=None)


def summarize(data, rows, sizes, clock, peak, retail=False, rockport=False):
    failures = []
    samples = data['samples']
    if not samples:
        raise ValueError('no census samples')
    if not clock:
        raise ValueError('no diagnostic host clocks')
    frames = [f for f, _ in clock]
    # Conservative bracketing: include any sample that could be >=20 s after
    # the first. Never infer wall time from frame count or interpolate clocks.
    first = bisect.bisect_left(frames, samples[0]['frame'])
    epoch_lower = clock[max(0, first - 1)][1]
    settled = [s for s in samples if
               clock[min(bisect.bisect_left(frames, s['frame']), len(clock)-1)][1] - epoch_lower >= 20]
    if not settled:
        failures.append('no samples after 20 seconds')
    byte_errors = []
    for s in samples:
        unknown = s['sections'] - sizes.keys()
        expected = sum(sizes[n] for n in s['sections'] if n in sizes)
        if unknown or s['bytes'] != expected:
            byte_errors.append(s['frame'])
    if byte_errors:
        failures.append(f'index byte mismatch: {len(byte_errors)} samples, first f{byte_errors[0]}')
    last = samples[-1]
    zone = last['zones'][0]
    missing = sorted(rows.get(zone, frozenset()) - last['sections'])
    if zone <= 0 or zone not in rows:
        failures.append(f'current zone {zone} absent')
    if missing:
        failures.append(f'missing sections: {missing}')
    if any(s['zones'][1] != -1 for s in settled):
        failures.append('second streaming position active')
    if any(s['pool'] != POOL for s in settled):
        failures.append('pool capacity differs')
    skipped = max(s['skipped'] for s in samples)
    if skipped:
        failures.append(f'skipped={skipped}')
    pool7 = max((s['bytes'] - sizes[2500] for s in settled), default=None)
    if any(2500 not in s['sections'] for s in settled):
        failures.append('Y00 absent')
    if pool7 is not None and pool7 > WORLD_SHARE:
        failures.append(f'pool-7 bytes {pool7} > {WORLD_SHARE}')
    grids = data['grids']
    grid = grids[-1] if grids else None
    if grid is None:
        failures.append('no grid observation')
    elif retail:
        bound = [g for g in grids if g['bound']]
        if not bound or any(g['tile'] not in range(2590, 2599) or g['cgrd'] != (167, 159) for g in bound):
            failures.append('retail tile/CGrd differs')
    elif (grid['tile'] != 2600 or grid['cgrd'] != (167, 365) or grid['grid'] != (167, 365)
          or grid['bound'] != 4165 or grid['rect'] != (2600, 0, 0, 365, 167) or grid['cell'] != 96):
        failures.append(f'merged grid differs: {grid["line"]}')
    if retail and data['overlays']:
        failures.append('retail overlay opened')
    if not retail and not all(any(f'PRIVATE TRACK OPEN TRACKS/{n} status=ok' in s
                                 for s in data['overlays']) for n in PAIR_SHA256):
        failures.append('both overlay opens required')
    y00 = min((n for n in data['chunks'] if n >= sizes[2500]), default=None)
    if y00 is None:
        failures.append('no Y00-sized successful @0047668A chunk')
    if peak is None or peak >= HEAP_MIB:
        failures.append(f'resource heap peak {peak} >= {HEAP_MIB} MiB or missing')
    distance = max((d['distance'] for d in data['drives']), default=0)
    if retail and distance <= 100:
        failures.append(f'track-5000 premise distance {distance} <= 100 m')
    if rockport and not data['drives']:
        failures.append('no Rockport physics samples')
    if rockport and any(d['position'][0] <= 10000 for d in data['drives']):
        failures.append('Rockport physics x <= 10000')
    return dict(passed=not failures, failures=failures, samples=len(samples), settled=len(settled),
                zone=zone, missing=missing, skipped=skipped, pool=last['pool'], pool7_bytes=pool7,
                largest=min(s['largest'] for s in samples), last_grid=grid['line'] if grid else None,
                y00_chunk=y00, heap_peak_mib=peak, distance=distance, byte_errors=len(byte_errors))


def c3_points(tracks, direction):
    import ground
    index = TrackIndex((tracks / 'L5RA.BUN').read_bytes())
    nodes = ground.road_nodes(index)
    # The original city node 1534 is outside the transverse ramp mouth.
    start, end = (8739, 1534) if direction == 'forward' else (9022, 8739)
    ids = [*range(8739,8755), *range(8988,9023), 1534]
    if direction == 'reverse':
        ids.reverse()
    return nodes[start], nodes[8754], nodes[end], nodes[8988], [nodes[n] for n in ids]


def polyline_offset(point, line):
    """XZ distance to the independently serialized road-node polyline."""
    if len(line) < 2:
        raise ValueError('C3 graph polyline needs at least two nodes')
    distances = []
    for a,b in zip(line,line[1:]):
        dx,dz = b[0]-a[0],b[2]-a[2]
        length2 = dx*dx+dz*dz
        t = max(0.,min(1.,((point[0]-a[0])*dx+(point[2]-a[2])*dz)/length2)) if length2 else 0.
        distances.append(math.hypot(point[0]-a[0]-t*dx,point[2]-a[2]-t*dz))
    return min(distances)


def c3_landing(data, direction):
    """First actual-car height at/past the decoded landing lip; no window."""
    samples = data.get('ticks') or data['drives']
    limit, deck = (34.05, 213.22) if direction == 'forward' else (.2, 213.27)
    observed = []
    for sample in samples:
        x, y, z = sample['position']
        along = (x + 2635.271)*.5383 - (z - 7214.961)*.8428
        observed.append((along, y))
        if (along >= limit if direction == 'forward' else along <= limit):
            failure = None if y >= deck else f'landing lip height {y:.2f} < {deck:.2f} m'
            return dict(height_m=y, s=along, frame=sample['frame'], deck_m=deck), failure
    furthest = (max(observed) if direction == 'forward' else min(observed)) if observed else None
    failure = ('never reached the landing lip: furthest s %.2f, height %.2f' % furthest
               if furthest else 'never reached the landing lip: no actual-car samples')
    return dict(height_m=None, deck_m=deck, furthest_s=furthest[0] if furthest else None,
                furthest_height_m=furthest[1] if furthest else None), failure


def summarize_c3(data, rows, sizes, points, direction):
    start, cut, end, next_node, polyline = points
    samples = data['samples']
    if not samples:
        raise ValueError('no census samples')
    failures, checked, missing_rows = [], [], []
    arrival = None
    for sample in samples:
        if 'stream' not in sample or 'loading' not in sample:
            raise ValueError('C3 requires streaming position and loading in every sample')
        # Serialized/render (Z,-X,height) -> physics (X,height,Z).
        z, negx, y = sample['stream']
        point = (-negx, y, z)
        needed = set()
        for zone in sample['zones']:
            if zone > 0:
                if zone not in rows:
                    failures.append(f'f{sample["frame"]}: unknown zone {zone}')
                needed.update(rows.get(zone, ()))
        if not any(z > 0 for z in sample['zones']):
            failures.append(f'f{sample["frame"]}: no active zone')
        missing = sorted(needed - sample['sections'])
        if missing:
            missing_rows.append(dict(frame=sample['frame'], zones=sample['zones'], sections=missing))
        checked.append(dict(sample, point=point))
        if math.dist(point, end) <= 60:
            arrival = sample['frame']
            break
    lateral = max(polyline_offset(s['point'],polyline) for s in checked)
    if lateral > 12.0:
        failures.append(f'maximum graph lateral offset {lateral:.3f} > 12.0 m')
    loading = sum(s['loading'] for s in checked)
    skipped = max(s['skipped'] for s in checked)
    missing = max((len(s['sections']) for s in missing_rows), default=0)
    byte_errors = sum(s['bytes'] != sum(sizes.get(n, 0) for n in s['sections'])
                      or bool(s['sections'] - sizes.keys()) for s in checked)
    tangent = (next_node[0] - cut[0], next_node[2] - cut[2])
    sign = 1 if direction == 'forward' else -1
    sides = [sign * ((s['point'][0]-cut[0])*tangent[0] +
                     (s['point'][2]-cut[2])*tangent[1]) for s in checked]
    nearest = min(checked, key=lambda s: math.dist(s['point'], cut))
    cut_distance = math.dist(nearest['point'], cut)
    passed_cut = cut_distance <= 60 and any(a <= 0 < b for a,b in zip(sides, sides[1:]))
    if math.dist(checked[0]['point'], start) > 60:
        failures.append('first sample is not within 60 m of start')
    if arrival is None:
        failures.append('incomplete drive: far end not reached within 60 m')
    if not passed_cut:
        failures.append('cut not crossed within 60 m')
    for name, value in [('loading',loading), ('missing',missing), ('skipped',skipped), ('byte_errors',byte_errors)]:
        if value:
            failures.append(f'{name}={value}')
    landing, landing_failure = c3_landing(data, direction)
    if landing_failure:
        failures.append(landing_failure)
    # Sparse contact observations bound flight; do not invent exact takeoff times.
    flights, takeoff = [], None
    drives = {d['frame']: d for d in data['drives']}
    previous = None
    for s in checked:
        drive = drives.get(s['frame'])
        if s.get('wheels') == 0 and takeoff is None and previous is not None:
            takeoff = previous
        elif s.get('wheels', -1) > 0 and takeoff is not None:
            before = drives.get(takeoff['frame'])
            flights.append(dict(takeoff_frame=takeoff['frame'], landing_frame=s['frame'],
                takeoff_speed_mps=before['speed'] if before else None,
                flight_chord_m=math.dist(before['position'],drive['position']) if before and drive else None,
                sampled_distance_m=drive['distance']-before['distance'] if drive and before else None))
            takeoff = None
        previous = s
    return dict(passed=not failures, failures=failures, direction=direction, samples=len(checked),
        loading=loading, missing=missing, skipped=skipped, missing_samples=missing_rows,
        byte_errors=byte_errors, arrival_frame=arrival, passed_cut=passed_cut,
        cut_frame=nearest['frame'], cut_distance_m=cut_distance,
        largest_at_cut=nearest['largest'] if passed_cut else None,
        end=checked[-1]['point'], end_distance_m=math.dist(checked[-1]['point'],end),
        maximum_lateral_offset_m=lateral, lateral_limit_m=12.0,
        landing_lip=landing, flights=flights, flight_measurement='one-second wheel contact and actual car position samples')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tracks', type=Path, default=HERE / 'out/c1load-overlay/TRACKS')
    parser.add_argument('--summary', type=Path, help='diagnostic directory or events.log')
    parser.add_argument('--retail', action='store_true', help='use unpinned retail L5RA index')
    parser.add_argument('--rockport', action='store_true')
    parser.add_argument('--broken-index', action='store_true')
    parser.add_argument('--c3', choices=('forward', 'reverse'))
    parser.add_argument('--broken-c3', action='store_true')
    args = parser.parse_args(argv)
    try:
        if args.broken_c3:
            print('C3LOAD control ' + json.dumps(broken_c3(args.tracks, HERE / 'out/c3load-broken/TRACKS')))
            return 0
        if args.broken_index:
            print(f'C1LOAD broken-index: {broken_index(args.tracks, HERE / "out/c1load-broken/TRACKS")}')
            return 0
        if not args.summary:
            parser.error('--summary required unless --broken-index')
        if args.c3:
            verify_pair(args.tracks, C3_PAIR_SHA256)
        rows, sizes = world_rows(args.tracks, pinned=not (args.retail or args.c3))
        diag = args.summary if args.summary.is_dir() else args.summary.parent
        with (diag / 'events.log').open() as stream:
            data = parse(stream)
        if args.c3:
            result = summarize_c3(data, rows, sizes, c3_points(args.tracks, args.c3), args.c3)
        else:
            with (diag / 'stats.log').open() as stream:
                clock = clocks(stream)
            with (diag / 'heap.log').open() as stream:
                peak = heap_peak(stream)
            result = summarize(data, rows, sizes, clock, peak, args.retail, args.rockport)
        fault_files = [p.name for pattern in ('hang_*.txt', 'stall_*.txt', '*crash*') for p in diag.glob(pattern)]
        if fault_files:
            result['failures'].append(f'fault files: {fault_files}')
            result['passed'] = False
        print(('C3LOAD ' if args.c3 else 'C1LOAD ') + ('PASS ' if result['passed'] else 'FAIL ') + json.dumps(result, sort_keys=True))
        return int(not result['passed'])
    except FileNotFoundError as error:
        print(f'C1LOAD unavailable: {error}')
        return 3
    except (OSError, ValueError, KeyError, IndexError) as error:
        print(f'C1LOAD FAIL: {error}')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
