"""Check both directions of the Carbon coast link using guarded drive logs.

Each drive must reach the two native approaches in order through the coast
corridor. Its vehicle census must see traffic on each approach. The same
nonzero local pursuit must have live cops at every pursuit sample from the
source mouth to the destination mouth. Cop IDs in that pursuit at both mouths
are reported separately from destination reinforcements.
Exit 0 PASS, 1 FAIL, 3 without the private coast pair or retail Carbon tracks.
"""
import argparse
from bisect import bisect_right
import math
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import private_c1load

COAST_PAIR_SHA256 = {
    'L5RA.BUN': '1dff6d0bf0da21c468e746f9d590a699faee83d827e43389ccc19978855b77e0',
    'STREAML5RA.BUN': 'aa2e88e2180a1f614baf71e774b2128b583601f9b94e23c8daba4a4e2636d6fb',
}
# Physics XZ of road nodes 1014 and 5387 in the pinned coast pair. The first
# deck node lies 8 m beyond 1014. Rockport ties into 5387 at the asphalt cut.
PALMONT = (1668.6893310546875, 3167.1396484375)
ROCKPORT = (1921.6982421875, 2465.630126953125)
DX, DZ = (b - a for a, b in zip(PALMONT, ROCKPORT))
LENGTH = math.hypot(DX, DZ)
PALMONT_CUT = 8.
DECK_HALF_WIDTH = 17.
MOUTH_RADIUS = 160.
DIRECTIONS = {'forward': ('palmont', 'rockport'), 'reverse': ('rockport', 'palmont')}
MOUTHS = {'palmont': PALMONT, 'rockport': ROCKPORT}

CAR = re.compile(r'^([0-9a-f]{8})@(-?[\d.]+),(-?[\d.]+),(-?[\d.]+)(\*?)$')
PURSUIT_ID = re.compile(r'[0-9a-f]{8}')
OVERLAY = re.compile(r'PRIVATE TRACK OPEN TRACKS/(\w+\.BUN) status=ok -> (.+)')


def station(position):
    x, _, z = position
    x, z = x - PALMONT[0], z - PALMONT[1]
    return (x * DX + z * DZ) / LENGTH, (x * DZ - z * DX) / LENGTH


def near_mouth(position, city):
    x, _, z = position
    mx, mz = MOUTHS[city]
    return math.hypot(x - mx, z - mz) <= MOUTH_RADIUS


def on_approach(position, city, include_shore_roads=False):
    s, lateral = station(position)
    shore = s <= PALMONT_CUT if city == 'palmont' else s >= LENGTH
    return near_mouth(position, city) and (
        shore or (include_shore_roads and abs(lateral) > DECK_HALF_WIDTH))


def cars(field):
    if field == '-':
        return []
    result = []
    for item in field.split(';'):
        match = CAR.fullmatch(item)
        if not match:
            raise ValueError(f'malformed vehicle {item!r}')
        result.append(dict(id=match[1], position=tuple(map(float, match.groups()[1:4])),
                           chased=bool(match[5])))
    return result


def evidence(lines):
    tick_lines, vehicles, pursuits, opened = [], [], [], set()
    for number, line in enumerate(lines, 1):
        if 'c3tick:' in line:
            tick_lines.append(line)
            continue
        if 'PRIVATE TRACK OPEN ' in line:
            match = OVERLAY.search(line.rstrip())
            if match:
                opened.add((match[1], Path(match[2]).resolve()))
            continue
        if 'vehicles:' in line:
            tag = 'vehicles:'
        elif 'carbon_pursuit:' in line and ' live=' in line:
            tag = 'carbon_pursuit:'
        else:
            continue
        frame = private_c1load.FRAME.match(line)
        if not frame:
            raise ValueError(f'line {number}: {tag} frame missing')
        fields = dict(re.findall(r'(\w+)=(\S+)', line.split(tag, 1)[1]))
        try:
            if tag == 'vehicles:':
                vehicles.append((int(frame[1]), cars(fields['T']), cars(fields['C'])))
            else:
                # The diagnostic's player field is the player's native Pursuit pointer.
                ident = fields['player']
                if not PURSUIT_ID.fullmatch(ident):
                    raise ValueError('invalid pursuit ID')
                pursuits.append((int(frame[1]), ident, int(fields['live']),
                                 int(fields['pursuits'])))
        except (KeyError, ValueError) as error:
            raise ValueError(f'line {number}: malformed {tag} {error}') from error
    try:
        ticks = private_c1load.parse(tick_lines)['ticks']
    except KeyError as error:
        raise ValueError(f'malformed c3tick: missing {error}') from error
    for frames in ([tick['frame'] for tick in ticks], [v[0] for v in vehicles], [p[0] for p in pursuits]):
        if any(a > b for a, b in zip(frames, frames[1:])):
            raise ValueError('coast evidence frames out of order')
    return ticks, vehicles, pursuits, opened


def crossing(ticks, source, destination):
    """Return the approach tick indices bounding a continuous deck drive."""
    start = None
    previous = None
    middle = False
    for index, tick in enumerate(ticks):
        position = tick['position']
        if tick['wheels'] > 0 and on_approach(position, source):
            start, previous, middle = index, position, False
        elif start is not None:
            s, lateral = station(position)
            interior = 40. < s < LENGTH - 40.
            if (math.dist(previous, position) > 40. or
                    (interior and (abs(lateral) > DECK_HALF_WIDTH or not 0. < position[1] < 45.))):
                start = None
                continue
            if tick['wheels'] > 0 and middle and on_approach(position, destination):
                return start, index
            middle |= interior and tick['wheels'] > 0
            previous = position
    return None


def check(lines, city, direction, tracks=None):
    source, destination = DIRECTIONS[direction]
    ticks, vehicles, pursuits, opened = evidence(lines)
    label = f'{source}->{destination}'
    if tracks is not None and any((name, (tracks / name).resolve()) not in opened
                                  for name in COAST_PAIR_SHA256):
        return False, f'C4 FAIL {label} missing coast pair opens'
    bounds = crossing(ticks, source, destination)
    if bounds is None:
        return False, f'C4 FAIL {label} no continuous coast crossing (ticks={len(ticks)})'

    tick_frames = [tick['frame'] for tick in ticks]
    exit_frame, entry_frame = (tick_frames[i] for i in bounds)

    def mouth_at(frame):
        i = bisect_right(tick_frames, frame) - 1
        if i >= 0:
            position = ticks[i]['position']
            if frame <= exit_frame and on_approach(position, source):
                return source
            if frame >= entry_frame and on_approach(position, destination):
                return destination
        return None

    traffic = dict.fromkeys(MOUTHS, 0)
    for frame, traffic_cars, _ in vehicles:
        mouth = mouth_at(frame)
        if mouth:
            count = sum(on_approach(car['position'], mouth, include_shore_roads=True)
                        and city(car['position']) == mouth
                        for car in traffic_cars)
            traffic[mouth] = max(traffic[mouth], count)
    failures = [f'no {mouth} approach traffic' for mouth, count in traffic.items() if not count]

    before = [i for i, (frame, *_) in enumerate(pursuits) if mouth_at(frame) == source]
    after = [i for i, (frame, *_) in enumerate(pursuits) if mouth_at(frame) == destination]
    origin_id = destination_id = '-'
    origin_live = destination_live = 0
    pursuit_samples = minimum_live = 0
    cops = {mouth: set() for mouth in MOUTHS}
    if not before or not after:
        failures.append('missing approach pursuit sample')
    else:
        first, last = before[-1], after[0]
        _, origin_id, origin_live, _ = pursuits[first]
        _, destination_id, destination_live, _ = pursuits[last]
        span = pursuits[first:last + 1]
        pursuit_samples = len(span)
        minimum_live = min((sample[2] for sample in span), default=0)
        if pursuit_samples < 3:
            failures.append('missing pursuit sample on the link')
        if origin_id == '00000000' or any(p[1] != origin_id for p in span):
            failures.append('pursuit ID changed or absent')
        if minimum_live < 1:
            failures.append('no live pursuit cops in a crossing sample')

        pursuit_frames = [p[0] for p in pursuits]
        for frame, _, cop_cars in vehicles:
            mouth = mouth_at(frame)
            i = bisect_right(pursuit_frames, frame) - 1
            # The census star means membership in any pursuit. A single
            # active pursuit identifies those IVehicles with the player.
            if mouth and i >= 0:
                _, ident, live, count = pursuits[i]
                if ident == origin_id and ident != '00000000' and live > 0 and count == 1:
                    cops[mouth].update(car['id'] for car in cop_cars if car['chased'])
        if not all(cops.values()):
            failures.append('missing chased cop IDs at a coast mouth')

    retained = cops[source] & cops[destination]
    new = cops[destination] - cops[source]
    def ids(values):
        return ','.join(sorted(values)) or '-'

    summary = (f'traffic_palmont={traffic["palmont"]} traffic_rockport={traffic["rockport"]} '
               f'pursuit={origin_id}->{destination_id} live={origin_live}/{destination_live} '
               f'min_live={minimum_live} pursuit_samples={pursuit_samples} '
               f'source_cops={ids(cops[source])} destination_cops={ids(cops[destination])} '
               f'retained={ids(retained)} reinforcements={ids(new)}')
    return not failures, (f'C4 {"FAIL" if failures else "PASS"} {label} {summary}'
                          + (f' failures={"; ".join(failures)}' if failures else ''))


def zone_city(tracks):
    """Authenticate the pair before using its coast windows and zone polygons."""
    import private_rockdrive
    from merge import DEFAULT_CARBON
    retail = DEFAULT_CARBON / 'L5RA.BUN'
    if not all((directory / name).is_file() for directory in (retail.parent, tracks)
               for name in COAST_PAIR_SHA256):
        return None
    private_c1load.verify_pair(tracks, COAST_PAIR_SHA256)
    pair = private_rockdrive.index_rows(tracks / 'L5RA.BUN')
    palmont = {b.number for b in private_rockdrive.index_rows(retail).boundaries}

    def city(position):
        number = pair.zone_at(position)
        return None if number is None else 'palmont' if number in palmont else 'rockport'

    return city


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tracks', type=Path, required=True, help='coast pair TRACKS directory')
    parser.add_argument('--forward', type=Path, required=True, help='Palmont to Rockport events.log')
    parser.add_argument('--reverse', type=Path, required=True, help='Rockport to Palmont events.log')
    args = parser.parse_args(argv)
    try:
        city = zone_city(args.tracks)
        if city is None:
            print('SKIP: private_c4_check needs the coast pair and retail Carbon tracks')
            return 3
        total = 0
        for direction, log in (('forward', args.forward), ('reverse', args.reverse)):
            with log.open() as lines:
                passed, result = check(lines, city, direction, args.tracks)
            print(result)
            total += passed
    except (OSError, ValueError) as error:
        print(f'C4 FAIL: {error}')
        return 1
    print(f'C4 {total}/2 directions pass')
    return 0 if total == 2 else 1


if __name__ == '__main__':
    sys.exit(main())
