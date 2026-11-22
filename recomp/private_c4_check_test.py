"""C4 coast fixtures: both directions pass (2/2); a new destination pursuit
ID in the Rockport-to-Palmont log makes that direction fail (1/2).
"""
from pathlib import Path
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import private_c4_check as c4


# Independently decoded positions just inland of each coast mouth.
PALMONT_APPROACH = (1645., 11., 3159.)
ROCKPORT_APPROACH = (1938., 27., 2453.)


def point(s, y=25., lateral=0.):
    return (1668.689331 + .339272508 * s - .940688134 * lateral,
            y, 3167.139648 - .940688134 * s - .339272508 * lateral)


def car(ident, position, chased=False):
    return f'{ident}@{position[0]:.3f},{position[1]:.3f},{position[2]:.3f}' + ('*' if chased else '')


def tick(frame, position):
    x, y, z = position
    return (f'f{frame} t0 c3tick: tick={frame} time={frame / 60:.5f} '
            f'position={x:.6f},{y:.6f},{z:.6f} velocity=0,0,0 wheels=4')


def pursuit(frame, ident='0a000000', live=2):
    return (f'f{frame} t0 carbon_pursuit: t={frame / 60:.5f} attempt=1 pursuits=1 '
            f'player={ident} live={live} unknown=0 onroad={live} pool=4 '
            'heat=1.000 disabled=0 nonew=0 status=1 busts=0 evades=0 cash=0')


def census(frame, traffic, cops):
    return (f'f{frame} t0 vehicles: traffic={len(traffic)}/4 cops={len(cops)}/4 unknown=0 '
            f'T={";".join(traffic) or "-"} C={";".join(cops) or "-"}')


def drive(direction, destination_id='0a000000', middle_live=2, destination_traffic=True,
          read_pair=None):
    path = [PALMONT_APPROACH, *(point(s) for s in range(0, 746, 25)),
            point(745, y=26.), ROCKPORT_APPROACH]
    if direction == 'reverse':
        path.reverse()
    last = len(path) * 10
    start, finish = path[0], path[-1]
    records = [tick(i * 10, position) for i, position in enumerate(path, 1)]
    records += [pursuit(10), pursuit(last // 2, live=middle_live), pursuit(last, destination_id),
                census(10, [car('00000001', start)],
                       [car('0000000a', start, True), car('0000000b', start, True)]),
                census(last, [car('00000002', finish)] if destination_traffic else [],
                       [car('0000000b', finish, True), car('0000000c', finish, True)])]
    if read_pair is not None:
        records.extend(f'f0 t0 PRIVATE TRACK OPEN TRACKS/{name} status=ok -> {read_pair / name}'
                       for name in c4.COAST_PAIR_SHA256)
    return sorted(records, key=lambda line: int(line.split()[0][1:]))


def city(position):
    return 'palmont' if position[2] > 2800 else 'rockport'


def verdict(direction, **kwargs):
    return c4.check(drive(direction, **kwargs), city, direction)


def main():
    good = [verdict(direction) for direction in ('forward', 'reverse')]
    for passed, text in good:
        assert passed and 'traffic_palmont=1 traffic_rockport=1' in text, text
        assert 'retained=0000000b reinforcements=0000000c' in text, text
    broken = verdict('reverse', destination_id='0b000000')
    assert not broken[0] and 'pursuit ID changed' in broken[1], broken[1]
    assert sum(passed for passed, _ in good) == 2
    assert sum(passed for passed, _ in (good[0], broken)) == 1
    for args, reason in ((dict(middle_live=0), 'no live pursuit cops'),
                         (dict(destination_traffic=False), 'no rockport approach traffic')):
        passed, text = verdict('forward', **args)
        assert not passed and reason in text, text

    short = [line for line in drive('forward') if 'c3tick:' not in line or line.startswith(('f10 ', 'f330 '))]
    assert not c4.check(short, city, 'forward')[0]
    wrong_direction = c4.check(drive('reverse'), city, 'forward')
    assert not wrong_direction[0], wrong_direction[1]
    try:
        c4.check(['f1 t0 vehicles: traffic=1/1 cops=0/0 unknown=0 T=1,2,3 C=-'], city, 'forward')
    except ValueError:
        pass
    else:
        raise AssertionError('malformed vehicle accepted')

    with tempfile.TemporaryDirectory(prefix='c4-') as directory:
        tracks = Path(directory)
        command = [sys.executable, '-I', str(HERE / 'private_c4_check.py'), '--tracks', directory,
                   '--forward', '/dev/null', '--reverse', '/dev/null']
        result = subprocess.run(command, capture_output=True, text=True)
        assert result.returncode == 3, result
        assert c4.check(drive('forward', read_pair=tracks), city, 'forward', tracks)[0]
        passed, text = c4.check(drive('forward'), city, 'forward', tracks)
        assert not passed and 'missing coast pair opens' in text, text
    print('C4 CHECK TEST PASS good=2/2 changed_destination_pursuit=1/2')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
