"""C4: traffic and police in both cities, a pursuit over the C3 jump.

Reads one Carbon events.log with the census `vehicles:` lines (NFS_CARBON_CENSUS=1),
`carbon_pursuit:` samples and the follower's `c3tick:` lines. City of a car = the
crossing pair's zone polygon at its physics position: zone numbers in the retail
Carbon L5RA are Palmont, added ones Rockport, none = outside. PASS needs all of:
traffic >= 1 and police >= 1 seen in each city; the player's landing (c3_landing);
the pursuit live at the last sample before the landing; after it, end=bust|evade or
a pursuit cop seen within 100 m before the take-off lip and, within 3 samples, past
the landing lip at deck - 3 m or higher (`landed`). A cop next seen below deck - 10 m
between the lips is printed as `fell`, not judged.
Exit 0 PASS, 1 FAIL, 3 without the private pair or retail tracks (live mode).
Live, forward from the Rockport ramp (SKIPFE_TRAFFIC=50, PURSUIT=5,1): PASS traffic
Rockport 5 / Palmont 9, police 2 / 1, landing 214.44 m, live 1, end=evade after the
landing. Broken control (traffic 0, cops off): FAIL traffic 0/0, police 0/0, live 0.
"""
import argparse
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import private_c1load
import private_pursuit

FRAME = re.compile(r'^f(\d+) ')
CAR = re.compile(r'^([0-9a-f]{8})@(-?[\d.]+),(-?[\d.]+),(-?[\d.]+)(\*?)$')
# c3_landing's lip axis: forward take-off lip near along 0, landing lip 34.05.
LIPS = {'forward': (0., 34.05, 213.22), 'reverse': (34.05, .2, 213.27)}


def along(x, z):
    return (x + 2635.271) * .5383 - (z - 7214.961) * .8428


def across(x, z):
    return (x + 2635.271) * .8428 + (z - 7214.961) * .5383


def cars(field):
    if field == '-':
        return []
    result = []
    for item in field.split(';'):
        match = CAR.match(item)
        if not match:
            raise ValueError(f'malformed vehicle {item!r}')
        result.append(dict(id=match[1], position=tuple(map(float, match.groups()[1:4])),
                           chased=bool(match[5])))
    return result


def check(lines, city, direction):
    lines = list(lines)
    vehicles, pursuit = [], []
    for number, line in enumerate(lines, 1):
        frame = FRAME.match(line)
        if 'vehicles:' in line:
            fields = dict(re.findall(r'(\w+)=(\S+)', line.split('vehicles:', 1)[1]))
            if not frame or not {'traffic', 'cops', 'T', 'C'} <= fields.keys():
                raise ValueError(f'line {number}: malformed vehicles line')
            vehicles.append(dict(frame=int(frame[1]), traffic=cars(fields['T']), cops=cars(fields['C'])))
        elif 'carbon_pursuit:' in line and ' live=' in line and frame:
            pursuit.append((int(frame[1]), number, int(re.search(r' live=(\d+)', line)[1])))
    counts = {}
    for kind in ('traffic', 'cops'):
        for name in ('rockport', 'palmont'):
            counts[f'{kind}_{name}'] = max((sum(city(c['position']) == name for c in v[kind])
                                            for v in vehicles), default=0)
    failures = [f'{key} 0' for key, value in counts.items() if value < 1]
    data = private_c1load.parse(lines)
    landing, landing_failure = private_c1load.c3_landing(data, direction)
    if landing_failure:
        failures.append(landing_failure)
    land = landing.get('frame')
    before = [p for p in pursuit if land is not None and p[0] <= land]
    live = before[-1][2] if before else 0
    if land is not None and live < 1:
        failures.append(f'pursuit live {live} at the landing')
    _, summary = private_pursuit.check(lines)
    end = re.search(r'\bend=(\w+)', summary)[1]
    end_line = re.search(r'\bend_line=(\w+)', summary)[1]
    end_frame = None
    if end_line != 'na':
        match = FRAME.match(lines[int(end_line) - 1])
        end_frame = int(match[1]) if match else None
    ended = end in ('bust', 'evade') and land is not None and end_frame is not None and end_frame >= land
    takeoff, landed_lip, deck = LIPS[direction]
    sign = 1 if direction == 'forward' else -1
    landed, fell = set(), set()
    for index, sample in enumerate(vehicles):
        for cop in sample['cops']:
            x, y, z = cop['position']
            s = along(x, z)
            if not cop['chased'] or abs(across(x, z)) > 30 or not 0 <= sign * (takeoff - s) <= 100:
                continue
            for later in vehicles[index + 1:index + 4]:
                seen = [c for c in later['cops'] if c['id'] == cop['id']]
                if not seen:
                    continue
                lx, ly, lz = seen[0]['position']
                ls = along(lx, lz)
                if sign * (ls - landed_lip) >= 0 and ly >= deck - 3 and abs(across(lx, lz)) <= 30:
                    landed.add(cop['id'])
                elif sign * (ls - takeoff) > 0 and sign * (ls - landed_lip) < 0 and ly < deck - 10:
                    fell.add(cop['id'])
                break
    if land is not None and not ended and not landed:
        failures.append('pursuit neither ended nor a cop landed after the jump')
    passed = not failures and bool(vehicles)
    if not vehicles:
        failures.append('no vehicles lines')
    text = ' '.join(f'{k}={v}' for k, v in counts.items())
    return passed, (f'C4 {"PASS" if passed else "FAIL"} {text} samples={len(vehicles)} '
                    f'landing_m={landing.get("height_m")} live_at_landing={live} end={end} '
                    f'landed={len(landed)} fell={len(fell)}'
                    + (f' failures={"; ".join(failures)}' if failures else ''))


def zone_city(tracks):
    """Zone polygons of the pair; the retail Carbon L5RA names the Palmont numbers."""
    import private_rockdrive
    sys.path.insert(0, str(HERE.parent / 'tools_snapshot/worldmerge'))
    from merge import DEFAULT_CARBON
    retail = DEFAULT_CARBON / 'L5RA.BUN'
    if not retail.is_file() or not (tracks / 'L5RA.BUN').is_file():
        return None
    private_c1load.verify_pair(tracks, private_c1load.C3_PAIR_SHA256)
    pair = private_rockdrive.index_rows(tracks / 'L5RA.BUN')
    palmont = {b.number for b in private_rockdrive.index_rows(retail).boundaries}
    def city(position):
        number = pair.zone_at(position)
        return None if number is None else 'palmont' if number in palmont else 'rockport'
    return city


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('log', type=Path)
    parser.add_argument('--tracks', type=Path, required=True, help='crossing pair TRACKS directory')
    parser.add_argument('--direction', choices=sorted(LIPS), required=True)
    args = parser.parse_args(argv)
    city = zone_city(args.tracks)
    if city is None:
        print('SKIP: private_c4_check needs the crossing pair and retail Carbon tracks')
        return 3
    try:
        passed, result = check(args.log.read_text().splitlines(), city, args.direction)
    except (OSError, ValueError) as error:
        print(f'C4 FAIL: {error}')
        return 1
    print(result)
    return 0 if passed else 1


if __name__ == '__main__':
    sys.exit(main())
