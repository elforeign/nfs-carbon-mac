"""Check simultaneous visibility-row completion during a driven distance.

The default observation ends at the first odometer sample reaching 1,000 m.
That whole sample is retained: the distance boundary is bracketed, never
interpolated or used to discard a failure. Time bounds use player POSITION
host clocks, never a frame-rate assumption. Every mode-2 draw window wholly
after the fixed settling bound is checked, including incomplete-zone visits.
Route/pool checks opt into single-sample exit checks and extra summary fields;
without either flag the original summary is preserved.
The new map-agreement and pool bounds cover every census sample in the log;
route changes use the same requested-distance boundary as census changes.
Route zones are judged at the census's streaming position when it carries
one: the point the engine classifies (the active camera, 4.49..5.68 m behind
the car over a recorded W0 drive), with the lag rule and bound unchanged.
That drive: 256/256 samples agree, 0 lag cases, 27 = 27 zone changes. With
one census zone corrupted (f8466, 1814 -> 1627): 1 map failure and 26 < 27.
The same log judged at the car: 1 map failure (f35202) and 27 < 28.
The expected zone follows the engine (007A44B0/007A3290): an overpass
boundary's selector alternate, and inside STREAMER_PREDICTION track-path
zones the section at stream + velocity * t when the zone lists it. Stock
drive (earlier rock-drive log, no velocity): 19 -> 17 failures with selectors
(f5286/f5399 are 639 over 606); the 17 are all inside prediction zones.
Fresh stock drive with velocity (5,743 m): 0 of 115; the same log judged by
the old rule (no selectors, no velocity): 15 of 115 (13 predicted, 2 overpass).
Zone-lag acceptance reports placeholder counts but delegates their verdict to
the paired private_sentinel --stock check; legacy modes retain zero allowance.
With --stock, each measured entry has the stock run's longest engine-entry
to row-completion interval, in diagnostic frames (no multiplier). COMPLETE events fill
the census intervals; each census replaces residency rather than accumulating
its sections. Windows extending beyond the retained distance tick are open
at the end and are reported without a completion verdict.
"""
import argparse
import bisect
import json
import math
from pathlib import Path
import re
import sys

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(HERE))
import private_census

FRAME = re.compile(r'^f(\d+) t\d+ ')
POSITION = re.compile(r'PRIVATE WORLD POSITION time=(\S+) render=\S+ source=player0(?:\s|$)')
DISTANCE = re.compile(r'autodrive:.*?\bdistance=(\S+)_m(?:\s|$)')
COMPLETE = re.compile(r'PRIVATE WORLD COMPLETE track=\d+ section=(\d+) status=[34](?:\s|$)')
DRIVE_POSITION = re.compile(r'\bposition=(\S+)(?:\s|$)')
SETTLE_SECONDS = 3.03
SENTINEL_ALLOWANCE = 0
COUNTERS = ('add', 'sentinel', 'meshes', 'scenery_add', 'scenery_sentinel',
            'scenery_meshes', 'scenery_overflow')


PREDICTION_TYPE = 6          # STREAMER_PREDICTION (zone-type name table 009EE9F0)
PREDICTION_MAX_SPEED = 178.8109130859375   # 009EEB48
PREDICTION_SECONDS, PREDICTION_METRES = 1.5, 100.  # 009EE794, 009EE7EC


def plane_height(triangle, x, y):
    """007A0010: height of a selector triangle's plane at (x, y)."""
    (x0, y0, z0), (x1, y1, z1), (x2, y2, z2) = triangle
    ax, ay, az, bx, by, bz = x1 - x0, y1 - y0, z1 - z0, x2 - x0, y2 - y0, z2 - z0
    nx, ny, nz = ay * bz - az * by, az * bx - ax * bz, ax * by - ay * bx
    return z0 - (nx * (x - x0) + ny * (y - y0)) / nz if nz else -math.inf


def track_path_zones(data, kind=PREDICTION_TYPE):
    """Track-path zones (0x80034147 / 0x0003414A, records sized at +42)."""
    import struct
    result = []

    def walk(blob):
        offset = 0
        while offset + 8 <= len(blob):
            tag, size = struct.unpack_from('<II', blob, offset)
            if size > len(blob) - offset - 8:
                raise ValueError(f'chunk {tag:08x} crosses parent')
            body = blob[offset + 8:offset + 8 + size]
            if tag == 0x80034147:
                walk(body)
            elif tag == 0x0003414A:
                p = 0
                while p + 0x44 <= len(body):
                    count, length = struct.unpack_from('<hh', body, p + 0x40)
                    if length < 0x44 + 8 * count or p + length > len(body):
                        raise ValueError('malformed track-path zone')
                    if struct.unpack_from('<i', body, p)[0] == kind:
                        result.append(dict(
                            elevation=struct.unpack_from('<f', body, p + 0x14)[0],
                            bounds=struct.unpack_from('<4f', body, p + 0x20),
                            sections=frozenset(n for n in struct.unpack_from('<4i', body, p + 0x30) if n),
                            vertices=[struct.unpack_from('<2f', body, p + 0x44 + 8 * i)
                                      for i in range(count)]))
                    p += length
            offset += 8 + size
    walk(data)
    return tuple(result)


class WorldRows(dict):
    """Visibility requirements with independently decoded index metadata."""

    def __init__(self, rows, sizes, boundaries, selectors=(), prediction=()):
        super().__init__(rows)
        self.sizes = sizes
        self.boundaries = boundaries
        self.selectors = selectors    # (id, triangle) level selectors, chunk 00034156
        self.prediction = prediction  # STREAMER_PREDICTION zones

    def section_at(self, x, y, up):
        """007A3290 on serialized (x, y, up): the first containing polygon,
        then its overpass alternate when 007A00F0's highest selector triangle
        below the point carries the boundary's +10/+14 id (+0C/+0E section)."""
        import struct
        from rockport_world import point_in_polygon
        for boundary in self.boundaries:
            lx, ly, hx, hy = boundary.bounds
            if lx <= x <= hx and ly <= y <= hy and point_in_polygon((x, y), boundary.vertices):
                first, second, first_id, second_id = struct.unpack_from('<hhii', boundary.raw, 12)
                if first and self.selectors:
                    best, chosen = -999., 0
                    for ident, triangle in self.selectors:
                        if point_in_polygon((x, y), [v[:2] for v in triangle]):
                            height = plane_height(triangle, x, y)
                            if best < height < up:
                                best, chosen = height, ident
                    if chosen and chosen == first_id:
                        return first
                    if chosen and chosen == second_id:
                        return second
                return boundary.number
        return None

    def zone_at(self, position):
        # Autodrive physics (X,Y,Z) becomes serialized horizontal (Z,-X), up Y.
        return self.section_at(position[2], -position[0], position[1])

    def engine_zone(self, stream, velocity=None):
        """007A44B0 on slot 0: inside a STREAMER_PREDICTION zone (elevation
        +14 bounds the slot height), the section at stream + velocity * t
        (t = 1.5 s, at most 100 m, none above 178.8 m/s) wins when the zone
        lists it; otherwise the section at the streaming position."""
        from rockport_world import point_in_polygon
        x, y, up = stream
        if velocity is not None:
            for zone in self.prediction:
                lx, ly, hx, hy = zone['bounds']
                h = zone['elevation']
                if not (lx <= x <= hx and ly <= y <= hy and point_in_polygon((x, y), zone['vertices'])):
                    continue
                if not ((h <= 0 or h <= up) and (h >= 0 or up <= abs(h))):
                    continue
                speed = math.sqrt(sum(v * v for v in velocity))
                t = 0. if speed > PREDICTION_MAX_SPEED else (
                    PREDICTION_SECONDS if speed * PREDICTION_SECONDS <= PREDICTION_METRES
                    else PREDICTION_METRES / speed)
                ahead = self.section_at(*(p + v * t for p, v in zip(stream, velocity)))
                if ahead in zone['sections']:
                    return ahead
        return self.section_at(x, y, up)

    def zone_distance(self, number, position):
        """Horizontal metres to the independently serialized census polygon."""
        from rockport_world import point_in_polygon
        point = position[2], -position[0]
        polygons = [b.vertices for b in self.boundaries if b.number == number]
        if not polygons:
            return math.inf
        distances = []
        for vertices in polygons:
            if point_in_polygon(point, vertices):
                return 0.
            for a, b in zip(vertices, (*vertices[1:], vertices[0])):
                dx, dy = b[0] - a[0], b[1] - a[1]
                length = dx * dx + dy * dy
                t = max(0., min(1., ((point[0] - a[0]) * dx +
                                     (point[1] - a[1]) * dy) / length)) if length else 0.
                distances.append(math.hypot(point[0] - a[0] - t * dx,
                                            point[1] - a[1] - t * dy))
        return min(distances, default=math.inf)


def index_rows(index_path):
    """Read actual serialized requirements; also used for the native control."""
    import struct
    sys.path.insert(0, str(HERE.parent / 'tools_snapshot/worldmerge'))
    from formats import TrackIndex
    import visibility
    data = index_path.read_bytes()
    index = TrackIndex(data)
    index.validate(index_path.with_name('STREAM' + index_path.name).stat().st_size)
    table = visibility.read(visibility.payload_of(index))
    sizes = {s.number: s.size for s in index.sections}
    result = {}
    for row in table.rows:
        if row.number in result:
            raise ValueError(f'duplicate visibility row {row.number}')
        entries = frozenset(row.entries) & sizes.keys()
        result[row.number] = dict(entries=entries, row_entries=len(row.entries),
                                  bytes=sum(sizes[n] for n in entries))
    boundaries = tuple(b for b in table.boundaries if 100 <= b.number < 2100
                       and 1 <= b.number % 100 < table.lod_offset)
    # 007A00F0 selector records, stride 0x40: id +0, triangle xyz at +10/+20/+30.
    selectors = tuple((struct.unpack_from('<i', s)[0],
                       tuple(struct.unpack_from('<3f', s, 16 + 16 * k) for k in range(3)))
                      for s in table.selectors if len(s) == 0x40)
    return WorldRows(result, sizes, boundaries, selectors, track_path_zones(data))


def world_rows(directory):
    """Require a checked native-coordinate converted world."""
    proof = json.loads((directory / 'proof.json').read_text())
    if (proof['track'] != 2000 or proof['region'] != 'L2RA' or proof['renumbered']
            or any(proof['shift']) or proof.get('checker_failure')
            or any(proof['validation']['dependencies'].values())):
        raise ValueError('checked native-coordinate L2RA world required')
    return index_rows(directory / 'TRACKS/L2RA.BUN')


def parse(lines, route_zones=False):
    rows, clocks, drives, windows, completions = [], [], [], [], []
    previous_frame = 0
    for number, line in enumerate(lines, 1):
        if not any(tag in line for tag in ('census:', 'PRIVATE WORLD POSITION ',
                                           'PRIVATE WORLD DRAWPATH ', 'autodrive: speed=',
                                           'PRIVATE WORLD COMPLETE ')):
            continue
        match = FRAME.match(line)
        if not match:
            raise ValueError(f'line {number}: diagnostic frame prefix missing')
        frame = int(match[1])
        if 'PRIVATE WORLD COMPLETE ' in line:
            match = COMPLETE.search(line)
            if not match:
                raise ValueError(f'line {number}: malformed COMPLETE event')
            completions.append(dict(frame=frame, line=number, section=int(match[1])))
        elif 'census:' in line:
            row, = private_census.samples([line])
            row.update(frame=frame, line=number)
            rows.append(row)
        elif 'PRIVATE WORLD POSITION ' in line:
            match = POSITION.search(line)
            if not match:
                raise ValueError(f'line {number}: malformed player POSITION clock')
            value = float(match[1])
            if not math.isfinite(value) or (clocks and value <= clocks[-1]['time']):
                raise ValueError('POSITION clocks nonfinite or unordered')
            clocks.append(dict(frame=frame, line=number, time=value))
        elif 'autodrive: speed=' in line:
            match = DISTANCE.search(line)
            if not match:
                raise ValueError(f'line {number}: malformed odometer')
            value = float(match[1])
            if not math.isfinite(value) or value < 0 or (drives and value < drives[-1]['distance']):
                raise ValueError('odometer nonfinite, negative or decreasing')
            drive = dict(frame=frame, line=number, distance=value)
            if route_zones:
                match = DRIVE_POSITION.search(line)
                if not match:
                    raise ValueError(f'line {number}: missing autodrive position')
                position = tuple(float(v) for v in match[1].split(','))
                if len(position) != 3 or not all(math.isfinite(v) for v in position):
                    raise ValueError(f'line {number}: invalid autodrive position')
                drive['position'] = position
            drives.append(drive)
        else:
            values = dict(re.findall(r'(\w+)=(\S+)', line))
            if values.get('mode') != 'all':
                raise ValueError('world probe mode=all required')
            end = int(values['frame'])
            if end != frame or end <= previous_frame:
                raise ValueError('draw-window frames unordered or mismatched')
            window = dict(start=previous_frame, end=end,
                          **{key: int(values[key]) for key in COUNTERS})
            if (any(window[key] < 0 for key in COUNTERS)
                    or window['sentinel'] > window['meshes']
                    or window['scenery_sentinel'] > window['scenery_meshes']
                    or any(window['scenery_' + key] > window[key]
                           for key in ('add', 'sentinel', 'meshes'))):
                raise ValueError('invalid mesh counters')
            windows.append(window)
            previous_frame = end
    for name, items in (('census', rows), ('POSITION', clocks), ('odometer', drives)):
        if any(a['frame'] >= b['frame'] for a, b in zip(items, items[1:])):
            raise ValueError(f'{name} frames unordered')
    if any(a['frame'] > b['frame'] for a, b in zip(completions, completions[1:])):
        raise ValueError('COMPLETE frames unordered')
    return dict(rows=rows, clocks=clocks, drives=drives, windows=windows,
                completions=completions)


def entry_completions(data, world, end_frame):
    """Replay residency from the engine's zone-entry frame, not the census.

    Age includes the entry update (1), so entry = sample - age + 1.
    Replay earlier COMPLETE events too: a row can finish before its first
    census. Census snapshots replace residency; they never accumulate.
    """
    visits, previous, initial = [], set(), True
    for row in data['rows']:
        if row['frame'] > end_frame:
            break
        if 'zone_age' not in row:
            raise ValueError(f'census f{row["frame"]}: engine zone_age required')
        zones = {z for z in row['zones'] if z > 0}
        for zone in sorted(zones - previous):
            if zone not in world or not world[zone]['entries']:
                raise ValueError(f'zone {zone}: no visibility row with records')
            age = row['zone_age'][row['zones'].index(zone)]
            if age < 1 or (age > row['frame'] + 1 and (not initial or age < 1000)):
                raise ValueError(f'census f{row["frame"]}: invalid zone entry age {age}')
            if initial and age > row['frame'] + 1:
                # Forced startup uses 1000, not an actual entry timestamp.
                # Retain that baseline explicitly without inventing a clock.
                visits.append(dict(zone=zone, frame=None, sample_frame=row['frame'],
                                   zone_age=age, bootstrap=True, complete_frame=None,
                                   frames_to_complete=None,
                                   missing=sorted(world[zone]['entries'] - row['sections'])))
                continue
            visits.append(dict(zone=zone, frame=row['frame'] - age + 1,
                               sample_frame=row['frame'], zone_age=age,
                               complete_frame=None, frames_to_complete=None, missing=[]))
        previous = zones
        initial = False
    # A same-frame census is authoritative, including any unloads at entry.
    events = [(v['frame'], math.inf, 'entry', v) for v in visits if v['frame'] is not None]
    events += [(r['frame'], r['line'], 'census', r) for r in data['rows']
               if r['frame'] <= end_frame]
    events += [(c['frame'], c['line'], 'complete', c) for c in data.get('completions', ())
               if c['frame'] <= end_frame]
    resident, pending = set(), []
    for frame, _, kind, event in sorted(events, key=lambda e: e[:2]):
        if kind == 'entry':
            pending.append(event)
        elif kind == 'census':
            resident = set(event['sections'])
        else:
            resident.add(event['section'])
        for visit in pending[:]:
            visit['missing'] = sorted(world[visit['zone']]['entries'] - resident)
            if not visit['missing']:
                visit['complete_frame'] = frame
                visit['frames_to_complete'] = frame - visit['frame']
                pending.remove(visit)
    return visits


def completion_verdict(data, world, end_frame, limit):
    if not math.isfinite(limit) or limit < 0:
        raise ValueError('completion frame limit must be finite and nonnegative')
    visits = entry_completions(data, world, end_frame)
    failures = []
    for visit in visits:
        if visit.get('bootstrap'):
            visit.update(deadline_frame=None, open_at_end=False, passed=None)
            continue
        visit['deadline_frame'] = visit['frame'] + limit
        visit['open_at_end'] = visit['deadline_frame'] > end_frame
        visit['passed'] = None if visit['open_at_end'] else (
            visit['frames_to_complete'] is not None and visit['frames_to_complete'] <= limit)
        if visit['passed'] is False:
            failures.append(f'zone {visit["zone"]} f{visit["frame"]}: row completion '
                            f'{visit["frames_to_complete"]} frames exceeds {limit:g}; '
                            f'missing sections={visit["missing"]}')
    return dict(limit_frames=limit, longest_frames=max(
        (v['frames_to_complete'] for v in visits if v['frames_to_complete'] is not None), default=None),
        entries=visits, open_at_end=sum(v['open_at_end'] for v in visits),
        judged=sum(v['passed'] is not None for v in visits),
        bootstrap=sum(v.get('bootstrap', False) for v in visits), failures=failures)


def stock_completion(data, world):
    """Calibrate from all stock entries, using the same completion decoder."""
    if not data['rows']:
        raise ValueError('stock completion has no census samples')
    end = data['rows'][-1]['frame']
    entries = entry_completions(data, world, end)
    longest = max((v['frames_to_complete'] for v in entries
                   if v['frames_to_complete'] is not None), default=None)
    if longest is None:
        raise ValueError('stock completion has no completed entries')
    result = completion_verdict(data, world, end, longest)
    if result['failures']:
        raise ValueError('stock completion: ' + '; '.join(result['failures']))
    return result


def ground_verdict(text, world, lower=0.3763124999999974, upper=4.264134765625002):
    """Keep the collision/band/distance checks; engine contact decides elevation.

    Every autodrive sample must have a same-frame census with a known wheel
    count. Zero contacts permits an elevated sample; any contact rejects it.
    No sparse-sample acceleration or fitted fall classifier is used.
    """
    import private_world
    result = private_world.ground_summary(text, world, lower, upper, 'autodrive')
    data = parse((line for line in text.splitlines()
                  if 'census:' in line or 'autodrive: speed=' in line), route_zones=True)
    rows = {r['frame']: r for r in data['rows']}
    elevated = []
    for drive in data['drives']:
        frame = drive['frame']
        row = rows.get(frame)
        if row is None or row.get('wheels', -1) not in range(5):
            raise ValueError(f'autodrive f{frame}: engine wheels required')
        x, height, z = drive['position']
        hit = world.find_face_below(x, z, height)
        projected = hit if hit is not None else world.find_face_below(x, z)
        if projected is not None and height - projected.height > upper:
            elevated.append(dict(frame=frame, gap=height - projected.height,
                                 wheels=row['wheels'], airborne=row['wheels'] == 0))
    high = [s for s in elevated if not s['airborne']]
    failures = [f for f in result['failures'] if not f.startswith('height above band:')]
    if high:
        failures.append(f'height above band with wheel contact: {len(high)} samples; '
                        f'first f{high[0]["frame"]} gap={high[0]["gap"]:.6f} '
                        f'wheels={high[0]["wheels"]}')
    result.update(passed=not failures, failures=failures, high=len(high),
                  elevated=elevated, airborne=sum(s['airborne'] for s in elevated),
                  contact_source='engine wheels', engine_samples=len(data['drives']))
    return result


def summarize(data, world, min_zones=3, complete_at_entry=False, metres=1000.,
              route_zones=False, pool_bytes=None, zone_lag_metres=None,
              completion_limit_frames=None):
    rows, clocks, drives = (data[k] for k in ('rows', 'clocks', 'drives'))
    failures = []
    if zone_lag_metres is not None and (not route_zones or
            not math.isfinite(zone_lag_metres) or zone_lag_metres < 0):
        raise ValueError('zone lag requires route zones and finite nonnegative metres')
    lag_cases = []
    revised = route_zones or pool_bytes is not None
    complete_after_exit = []
    cutoff = next((d for d in drives if d['distance'] >= metres), None)
    if cutoff is None:
        failures.append(f'odometer does not reach {metres:g} m')
        cutoff = drives[-1] if drives else dict(frame=0, line=0, distance=0.)
    end_frame = cutoff['frame']
    completion = None
    if completion_limit_frames is not None:
        completion = completion_verdict(data, world, end_frame, completion_limit_frames)
        failures.extend(completion['failures'])
    rows = [r for r in rows if r['frame'] <= end_frame]
    windows = [w for w in data['windows'] if w['end'] <= end_frame]
    if not rows:
        failures.append('no census samples in observation')
    if not clocks:
        failures.append('no player POSITION host clocks')
    clock_lines = [c['line'] for c in clocks]
    epoch = clocks[0]['time'] if clocks else 0.

    def bounds(row):
        i = bisect.bisect_left(clock_lines, row['line'])
        return [max(0., clocks[i - 1]['time'] - epoch) if i else 0.,
                clocks[i]['time'] - epoch if i < len(clocks) else None]

    # Distance belongs to the census/autodrive tick with the same frame. No
    # interpolation through turns or unobserved section transitions is used.
    distances = {d['frame']: d['distance'] for d in drives}
    route_changes = None
    if route_zones:
        if not isinstance(world, WorldRows) or not world.boundaries:
            raise ValueError('route zones require the serialized drivable-zone map')
        positions = {d['frame']: d.get('position') for d in drives}
        # The engine classifies slot 0's streaming position (0079A170: the
        # active camera, not the car). A census that carries it is judged
        # there; its serialized (x, y, up) is physics (z, -x, y).
        streamed = [r for r in data['rows'] if 'stream' in r]
        if streamed and len(streamed) != len(data['rows']):
            raise ValueError('census streaming position present on only some samples')
        for row in streamed:
            x, y, up = row['stream']
            positions[row['frame']] = (-y, up, x)
        route_changes, previous_zone = 0, None
        # A streamed census is judged by the engine's own rule (prediction
        # zones, overpass selectors); its velocity enables the prediction.
        mapped = [world.engine_zone(r['stream'], r.get('velocity')) if 'stream' in r
                  else world.zone_at(positions[r['frame']]) if positions.get(r['frame']) is not None
                  else None for r in data['rows']]
        predicted = sum(1 for r, zone in zip(data['rows'], mapped) if 'velocity' in r
                        and zone != world.engine_zone(r['stream']))
        for tick, row in enumerate(data['rows']):
            frame = row['frame']
            if positions.get(frame) is None:
                raise ValueError(f'census f{frame} has no matching autodrive position')
            zone = mapped[tick]
            if zone is None:
                failures.append(f'census f{frame}: position has no drivable map zone')
            elif row['zones'][0] != zone:
                distance = world.zone_distance(row['zones'][0], positions[frame]) if zone_lag_metres is not None else math.inf
                if (zone_lag_metres is not None and tick > 0 and tick + 1 < len(mapped)
                        and row['zones'][0] == mapped[tick - 1]
                        and mapped[tick + 1] is not None
                        and data['rows'][tick + 1]['zones'][0] == mapped[tick + 1]
                        and distance <= zone_lag_metres):
                    lag_cases.append(dict(frame=frame, census_zone=row['zones'][0],
                                          map_zone=zone, metres=distance))
                else:
                    failures.append(f'census f{frame}: zone {row["zones"][0]} != map zone {zone}')
            if frame not in distances:
                raise ValueError(f'census f{frame} has no matching odometer tick')
            route_changes += (previous_zone is not None and zone is not None
                              and previous_zone != zone and distances[frame] <= metres)
            previous_zone = zone
    pool7_peak = None
    if pool_bytes is not None:
        if pool_bytes < 0:
            raise ValueError('pool bytes must be nonnegative')
        if not isinstance(world, WorldRows) or 2500 not in world.sizes:
            raise ValueError('pool bytes require section 2500 size from the index')
        missing = [r['frame'] for r in data['rows'] if 2500 not in r['sections']]
        if missing:
            failures.append(f'section 2500 not loaded: {len(missing)} samples; first frames={missing[:8]}')
        values = [(r['frame'], r['bytes'] - world.sizes[2500]) for r in data['rows']]
        pool7_peak = max((value for _, value in values), default=None)
        over = [frame for frame, value in values if value > pool_bytes]
        if over:
            failures.append(f'pool7 bytes {pool7_peak} > {pool_bytes}: '
                            f'{len(over)} samples; first frames={over[:8]}')
    visits, active, previous = [], {}, None
    changes, observed_changes, unloads, observed_unloads, since_change = 0, 0, 0, 0, 0
    for tick, row in enumerate(rows):
        if row['frame'] not in distances:
            raise ValueError(f'census f{row["frame"]} has no matching odometer tick')
        zones = tuple(z for z in row['zones'] if z > 0)
        if len(set(zones)) != len(zones):
            zones = tuple(dict.fromkeys(zones))
        removed = len(previous['sections'] - row['sections']) if previous else 0
        observed_unloads += removed
        if distances[row['frame']] <= metres:
            unloads += removed
        since_change += removed
        changed = previous is not None and row['zones'] != previous['zones']
        observed_changes += changed
        changes += changed and distances[row['frame']] <= metres
        for zone in set(active) - set(zones):
            visit = active[zone]
            if revised and not visit['complete'] and tick - visit['_entry_tick'] == 1 and zones:
                next_zone = row['zones'][0]
                if next_zone in world:
                    shared = world[zone]['entries'] & world[next_zone]['entries']
                    visit['missing'] = sorted(shared - row['sections'])
                    if not visit['missing']:
                        visit['complete_after_exit'] = True
                        complete_after_exit.append(zone)
            del active[zone]
        for zone in zones:
            if zone not in world or not world[zone]['entries']:
                raise ValueError(f'zone {zone}: no visibility row with records')
            required = world[zone]['entries']
            if zone not in active:
                visit = dict(zone=zone, frame=row['frame'], time=bounds(row)[1],
                             metres=distances[row['frame']], required=len(required),
                             within_requested_distance=distances[row['frame']] <= metres,
                             row_entries=world[zone]['row_entries'],
                             loaded_at_entry=len(required & row['sections']),
                             seconds_to_complete=None, complete=False,
                             complete_frame=None, ticks_to_complete=None,
                             unloaded_since_previous_zone=since_change,
                             missing=sorted(required - row['sections']))
                visit['_entry_tick'], visit['_entry_bounds'] = tick, bounds(row)
                visits.append(visit)
                active[zone] = visit
            visit = active[zone]
            if not visit['complete'] and required <= row['sections']:
                visit['complete'] = True
                visit['complete_frame'] = row['frame']
                visit['ticks_to_complete'] = tick - visit['_entry_tick']
                if tick == visit['_entry_tick']:
                    visit['seconds_to_complete'] = 0.
                else:
                    complete_bounds = bounds(row)
                    if complete_bounds[1] is not None:
                        visit['seconds_to_complete'] = complete_bounds[1] - visit['_entry_bounds'][0]
                visit['missing'] = []
            elif not visit['complete']:
                visit['missing'] = sorted(required - row['sections'])
        if previous is None or changed:
            since_change = 0
        previous = row
    for visit in visits:
        if completion is None and not visit['complete'] and not visit.get('complete_after_exit'):
            failures.append(f'zone {visit["zone"]} f{visit["frame"]}: not COMPLETE; '
                            f'missing sections={visit["missing"]}')
        elif completion is None and visit['complete'] and complete_at_entry and visit['ticks_to_complete'] > 1:
            failures.append(f'zone {visit["zone"]}: COMPLETE after {visit["ticks_to_complete"]} ticks (>1)')
        if visit['time'] is None or (visit['complete'] and visit['seconds_to_complete'] is None):
            failures.append(f'zone {visit["zone"]}: POSITION clocks do not bound entry/completion')
        del visit['_entry_tick'], visit['_entry_bounds']
    if not visits:
        failures.append('no entered positive zones')
    required_changes = route_changes if route_zones else min_zones
    if changes < required_changes:
        failures.append(f'zone changes {changes} < {required_changes}'
                        + (' from route map' if route_zones else ''))
    if not unloads:
        failures.append('unloads=0')
    skipped = max((r['skipped'] for r in rows), default=0)
    if skipped:
        failures.append(f'skipped={skipped}')

    # The first clock at/after R1 gives a conservative whole-window boundary.
    settled = next((c for c in clocks if c['time'] - epoch >= SETTLE_SECONDS), None)
    eligible = [w for w in windows if settled and w['start'] > settled['frame']]
    bad_add = [w['end'] for w in eligible if w['scenery_add'] <= 0]
    bad_sentinel = [w['end'] for w in eligible if w['scenery_sentinel'] > SENTINEL_ALLOWANCE]
    bad_cadence = [w['end'] for w in eligible if w['end'] - w['start'] != 1]
    if not eligible:
        failures.append('no whole mode-2 windows after settling')
    elif eligible[0]['end'] > settled['frame'] + 2 or eligible[-1]['end'] < end_frame:
        failures.append('mode-2 windows do not cover the settled observation through its final tick')
    for name, frames in (('scenery add=0', bad_add),
                         ('sentinel exceeds 0', bad_sentinel if zone_lag_metres is None else []),
                         ('mode-2 frame gap', bad_cadence)):
        if frames:
            failures.append(f'{name}: {len(frames)} windows; first frames={frames[:8]}')
    if any(w['scenery_overflow'] for w in windows):
        failures.append('scenery membership table overflow')
    distances_before = [d['distance'] for d in drives if d['frame'] < end_frame]
    result = dict(passed=not failures, failures=failures, visits=visits,
                zone_changes=changes, observed_zone_changes=observed_changes,
                zones_entered=[v['zone'] for v in visits],
                unloads=unloads, observed_unloads=observed_unloads, skipped=skipped,
                minimum_largest_free=min((r['largest'] for r in rows), default=None),
                loaded_min=min((r['loaded'] for r in rows), default=None),
                loaded_max=max((r['loaded'] for r in rows), default=None),
                census_samples=len(rows), end_frame=end_frame,
                metres=cutoff['distance'], boundary_metres=[distances_before[-1] if distances_before else 0., cutoff['distance']],
                requested_metres=metres,
                metres_per_zone_change=metres / changes if changes else None,
                settling_seconds=SETTLE_SECONDS,
                settling_clock_upper=settled['time'] - epoch if settled else None,
                time_origin='first player POSITION host clock; completion times are upper bounds',
                counter_scope='scenery', sentinel_allowance=SENTINEL_ALLOWANCE,
                windows=dict(count=len(eligible),
                             first_frame=eligible[0]['end'] if eligible else None,
                             last_frame=eligible[-1]['end'] if eligible else None,
                             minimum_add=min((w['scenery_add'] for w in eligible), default=None),
                             maximum_sentinel=max((w['scenery_sentinel'] for w in eligible), default=None),
                             zero_add=len(bad_add), nonzero_sentinel=len(bad_sentinel),
                             totals={k: sum(w['scenery_' + k] for w in eligible)
                                     for k in ('add', 'sentinel', 'meshes')}))
    if revised:
        result.update(pool7_peak=pool7_peak, route_zone_changes=route_changes,
                      complete_after_exit=complete_after_exit)
        if route_zones:
            result['route_position'] = 'stream' if streamed else 'autodrive'
            result['predicted_samples'] = predicted
    if completion is not None:
        result['completion'] = completion
    if zone_lag_metres is not None:
        result.update(zone_lag_metres=zone_lag_metres, zone_lag_cases=lag_cases,
                      zone_lag_max=max((case['metres'] for case in lag_cases), default=0.),
                      sentinel_allowance=None,
                      sentinel_check='requires paired private_sentinel --stock verdict')
    return result


def positive(value):
    value = float(value)
    if not math.isfinite(value) or value <= 0:
        raise argparse.ArgumentTypeError('must be finite and positive')
    return value


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--summary', required=True, type=Path, metavar='EVENTS.LOG')
    parser.add_argument('--world', required=True, type=Path)
    parser.add_argument('--min-zones', type=int, default=3, metavar='N')
    parser.add_argument('--complete-at-entry', action='store_true')
    parser.add_argument('--route-zones', action='store_true',
                        help='check every position against the map; derive required distance-bounded changes')
    parser.add_argument('--pool-bytes', type=int, metavar='N',
                        help='bound every census sample, excluding main-heap section 2500')
    parser.add_argument('--metres', type=positive, default=1000.)
    parser.add_argument('--zone-lag-metres', type=positive, metavar='M',
                        help='with route zones: bound one-sample census lag; pair with private_sentinel --stock')
    parser.add_argument('--stock', type=Path, metavar='EVENTS.LOG',
                        help='judge engine zone-entry to completion within native stock longest frames')
    parser.add_argument('--ground-tracks', type=Path, metavar='TRACKS',
                        help='also check ground using collision faces and engine wheel contact')
    parser.add_argument('--ground-base', default='L2RA', metavar='BASE')
    args = parser.parse_args(argv)
    if args.min_zones < 0:
        parser.error('--min-zones must be nonnegative')
    if args.pool_bytes is not None and args.pool_bytes < 0:
        parser.error('--pool-bytes must be nonnegative')
    if args.zone_lag_metres is not None and not args.route_zones:
        parser.error('--zone-lag-metres requires --route-zones')
    if args.stock is not None and args.complete_at_entry:
        parser.error('--stock replaces --complete-at-entry')
    try:
        world = world_rows(args.world)
        stock = None
        if args.stock is not None:
            image = json.loads((HERE / 'out/carbon/image.json').read_text())
            stock_world = index_rows(Path(image['exe']).parent / 'TRACKS/L5RA.BUN')
            # Validate native mode/track and identities with the paired checker,
            # rather than allowing a converted or broken log to set the limit.
            import private_sentinel
            with args.stock.open() as stream:
                private_sentinel.stock_control(private_sentinel.parse(stream),
                                                private_sentinel.native_stock_world(), 12)
            with args.stock.open() as stream:
                stock = stock_completion(parse(stream), stock_world)
        with args.summary.open() as stream:
            result = summarize(parse(stream, args.route_zones), world, args.min_zones,
                               args.complete_at_entry, args.metres,
                               args.route_zones, args.pool_bytes, args.zone_lag_metres,
                               stock['limit_frames'] if stock else None)
        if stock is not None:
            result['completion']['stock_longest_frames'] = stock['longest_frames']
            result['completion']['stock_entries'] = len(stock['entries'])
        if args.ground_tracks is not None:
            import private_world
            collision = private_world.load_ground_world(args.ground_tracks, args.ground_base)
            result['ground'] = ground_verdict(args.summary.read_text(), collision)
            result['failures'].extend(result['ground']['failures'])
            result['passed'] = not result['failures']
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f'rockdrive FAIL: {error}', file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True, separators=(',', ':')))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
