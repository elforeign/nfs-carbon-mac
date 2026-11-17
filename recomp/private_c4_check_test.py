"""private_c4_check on synthetic logs (no game, no private data).

Two-square city map: physics z > 6000 Rockport, else Palmont. Good forward run:
traffic 1/1 and police 1/1 per city, landing at 214.0 m, live 2, cop landed -> PASS;
the same run passes by evade alone. Broken: Rockport traffic removed (the row's
"one city's traffic off") -> traffic_rockport=0 FAIL; no cops -> FAIL; no landing
-> FAIL; neither end nor landed cop -> FAIL; the landed cop's id changed -> FAIL;
cop below the deck between the lips -> fell=1 FAIL. Exit 3 without the pair.
"""
from pathlib import Path
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import private_c4_check as c4


def point(s, y, c=0.):
    return (-2635.271 + s * .5383 + c * .8428, y, 7214.961 - s * .8428 + c * .5383)


def car(ident, p, chased=False):
    return f'{ident}@{p[0]:.1f},{p[1]:.1f},{p[2]:.1f}' + ('*' if chased else '')


def pursuit(frame, live, evades=0):
    return (f'f{frame} t0 carbon_pursuit: t={frame / 60:.3f} attempt=1 pursuits=1 player=0a000000 '
            f'live={live} unknown=0 onroad={live} pool=4 heat=1.000 disabled=0 nonew=0 '
            f'status=1 busts=0 evades={evades} cash=0')


def log(traffic_rockport=True, cops=True, land=True, landed_cop=True, evade=False, same_id=True,
        fall=False):
    rock, palm = point(-300, 190), (-3100., 104., 5000.)
    lines = ['f50 t0 carbon_pursuit: request t=5.000 attempt=1 enabled=1']
    for frame, s, y in ((100, -50, 213.), (200, 0, 213.), (300, 40 if land else 20, 214. if land else 150.)):
        x, yy, z = point(s, y)
        lines.append(f'f{frame} t0 c3tick: tick={frame} time={frame / 60:.6f} position={x:.6f},{yy:.6f},{z:.6f} '
                     f'velocity=0,0,0 wheels=4')
    lines.append(pursuit(120, 2))
    lines.append(pursuit(280, 2))
    lines.append(pursuit(400, 0 if evade else 2, 1 if evade else 0))
    traffic = [car('00000001', palm)] + ([car('00000002', rock)] if traffic_rockport else [])
    first = [car('0000000a', point(-20, 213.), True), car('0000000b', palm)] if cops else []
    after = point(30, 150.) if fall else point(50, 213.5) if landed_cop else point(-60, 213.)
    second = [car('0000000a' if same_id else '0000000c', after, True)] if cops else []
    lines.append(f'f150 t0 vehicles: traffic={len(traffic)}/4 cops={len(first)}/4 unknown=0 '
                 f'T={";".join(traffic)} C={";".join(first) or "-"}')
    lines.append(f'f250 t0 vehicles: traffic={len(traffic)}/4 cops={len(second)}/4 unknown=0 '
                 f'T={";".join(traffic)} C={";".join(second) or "-"}')
    return lines


def city(p):
    return 'rockport' if p[2] > 6000 else 'palmont'


def verdict(**kwargs):
    passed, text = c4.check(log(**kwargs), city, 'forward')
    print(text)
    return passed, text


def main():
    passed, text = verdict()
    assert passed and 'traffic_rockport=1 traffic_palmont=1 cops_rockport=1 cops_palmont=1' in text
    assert 'landed=1' in text and 'live_at_landing=2' in text
    passed, text = verdict(landed_cop=False, evade=True)
    assert passed and 'end=evade' in text and 'landed=0' in text
    for kwargs, reason in ((dict(traffic_rockport=False), 'traffic_rockport 0'),
                           (dict(cops=False), 'cops_rockport 0'),
                           (dict(land=False), 'never reached the landing lip'),
                           (dict(landed_cop=False), 'neither ended nor a cop landed'),
                           (dict(same_id=False), 'neither ended nor a cop landed'),
                           (dict(fall=True), 'neither ended nor a cop landed')):
        passed, text = verdict(**kwargs)
        assert not passed and reason in text, (kwargs, text)
    assert 'fell=1' in text
    try:
        c4.check(['f1 t0 vehicles: traffic=1/1 cops=0/0 unknown=0 T=1,2,3 C=-'], city, 'forward')
        raise AssertionError('malformed vehicle accepted')
    except ValueError:
        pass
    with tempfile.TemporaryDirectory(prefix='c4-') as directory:
        result = subprocess.run([sys.executable, '-I', str(HERE / 'private_c4_check.py'), '/dev/null',
                                 '--tracks', directory, '--direction', 'forward'], capture_output=True, text=True)
        assert result.returncode == 3, result
    print('C4 CHECK TEST PASS good=2 broken=6 (traffic_rockport=0 -> FAIL)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
