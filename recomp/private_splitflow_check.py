#!/usr/bin/env python3
"""












"""
import argparse
import json
import math
from pathlib import Path
import re


def settings():
    """Print a game_run recipe; all progression remains native menu input."""
    start = ('padlayout:xbox,wait:450,RETURN,wait:400,RETURN,wait:400,'
             'pkg:FeMainMenu.fng,RIGHT,wait:180,RIGHT,wait:180,RIGHT,wait:180,RETURN,wait:300,RETURN,wait:300,'
             'pkg:FeQuickRaceOptions.fng,RIGHT,wait:60,RIGHT,wait:120,RETURN,wait:300,'
             'pkg:FeCarSelect.fng,RETURN,wait:240,RETURN,wait:240,RETURN,wait:240,'
             'pkg:FePressStart.fng,pad2:128:30,wait:120,pkg:FeCarSelect.fng,'
             'pad2:1:30,wait:240,pad2:1:30,wait:240,pad2:1:30,wait:240,wait:600,C,splitwait:finished')
    solo = ('pkg:FePostRaceResults.fng,shot,pkg:FeWorldMapQuickList.fng:RETURN,'
            'pkg:FeQuickRaceOptions.fng:RETURN,wait:180,shot,'
            'pkg:FeCarSelect.fng:RETURN,wait:240,RETURN,wait:240,RETURN,wait:240,RETURN,wait:240,'
            'splitwait:solo,shot,wait:600')
    return {'image': 'carbon', 'label': 'cpad2-splitflow-acceptance', 'seconds': 300,
            'settings': ['BOOT_SEED=carbon', 'BOOT_PAD=sim:xbox', 'BOOT_PAD2=sim', 'NFS_PADS=2',
                         'NFS_CARBON_RES=1280x720', 'NFS_CARBON_FE_PROBE=1', 'NFS_CARBON_SKIP_MOVIES=1',
                         'BOOT_AUTODRIVE=1', 'BOOT_KEYS_STRICT=1', 'BOOT_DIAG_SHOT_EVERY=12000',
                         'BOOT_DIAG_SIMSHOTS=30,35,45', 'BOOT_REG=FirstTime=0,g_PerformanceLevel=5,g_FSAALevel=1,'
                         'g_CarEnvironmentMapEnable=3,g_RoadReflectionEnable=2,g_MotionBlurEnable=1,'
                         'g_ParticleSystemEnable=1,g_WorldLodLevel=3,g_CarLodLevel=1,g_RainEnable=1,'
                         'g_TextureFiltering=2,g_VisualTreatment=1,g_ShadowDetail=2,g_ShaderDetailLevel=3',
                         'BOOT_KEYS=seq:' + start + ',' + solo]}


def snapshots(path):
    current = None
    phase, racing = 0, False
    with Path(path).open(errors='replace') as stream:
        for line, raw in enumerate(stream, 1):
            if 'carbon splitflow:' not in raw:
                continue
            fields = dict(re.findall(r'(\w+)=([^\s]+)', raw))
            if 'player' not in fields:
                if current is not None:
                    yield current
                if fields.get('flow') == '6':
                    if not racing:
                        phase += 1
                    racing = True
                else:
                    racing = False
                current = {'line': line, 'phase': phase, 'state': fields, 'players': {}}
            elif current is not None:
                current['players'][fields['player']] = fields
    if current is not None:
        yield current


def check(path, emit=print):
    path = Path(path)
    if path.is_dir():
        path = path / 'diag/events.log'
    rows = list(snapshots(path)) if path.is_file() else []
    passed = 0
    cursor = 0
    stages = ('split-ownership', 'p1-moving', 'p2-moving', 'p1-finished',
              'p2-finished', 'results', 'cleanup', 'single-player-moving')

    def nonzero(value):
        return bool(re.fullmatch(r'[0-9A-Fa-f]{8}', value or '') and int(value, 16))

    def state(row, **wanted):
        return all(row['state'].get(k) == str(v) for k, v in wanted.items())

    def player(row, slot, done=None, moving=False):
        p = row['players'].get(str(slot), {})
        try:
            return nonzero(p.get('sim')) and nonzero(p.get('racer')) and \
                (done is None or p.get('finished') == str(done)) and \
                (done != 1 or int(p.get('lap', '0')) >= 3) and \
                (not moving or (math.isfinite(float(p.get('velocity', 'nan'))) and float(p['velocity']) > 1))
        except ValueError:
            return False

    def seek(predicate):
        nonlocal cursor, passed
        for i in range(cursor, len(rows)):
            if predicate(rows[i]):
                cursor = i + 1
                emit(f'PASS {stages[passed]} line={rows[i]["line"]}')
                passed += 1
                return rows[i]
        raise LookupError

    try:
        split = seek(lambda r: state(r, flow=6, state=3, mode=1, locals=2, views=2)
                     and player(r, 1, done=0) and player(r, 2, done=0)
                     and r['players']['1']['sim'] != r['players']['2']['sim']
                     and r['players']['1']['racer'] != r['players']['2']['racer']
                     and int(r['state'].get('captures', '0')) > 0
                     and int(r['state'].get('handles', '0')) > 0)
        race = split['state']['race']
        phase = split['phase']
        handles = int(split['state']['handles'])

        def same_race(r):
            return r['phase'] == phase and state(r, flow=6, mode=1, locals=2, race=race) and all(
                r['players'].get(p, {}).get(k) == split['players'][p][k]
                for p in ('1', '2') for k in ('sim', 'racer'))

        # Movement and finish order are independent. Preserve the same split
        # interval while seeking each player's evidence from its beginning.
        start = cursor - 1
        seek(lambda r: same_race(r) and player(r, 1, moving=True))
        cursor = start
        seek(lambda r: same_race(r) and player(r, 2, moving=True))
        cursor = start
        p1 = seek(lambda r: same_race(r) and player(r, 1, done=1))
        cursor = start
        p2 = seek(lambda r: same_race(r) and player(r, 2, done=1))
        cursor = max(rows.index(p1), rows.index(p2))
        seek(lambda r: r['phase'] == phase and state(r, race=race, package='FePostRaceResults.fng'))
        seek(lambda r: state(r, flow=3, locals=0, views=0, captures=0) and not r['players']
             and 0 < int(r['state'].get('handles', '0')) <= handles)
        seek(lambda r: r['phase'] == phase + 1 and state(r, flow=6, state=3, mode=0, locals=1, views=0, captures=0)
             and 0 < int(r['state'].get('handles', '0')) <= handles
             and player(r, 1, moving=True) and '2' not in r['players'])
    except (LookupError, KeyError, ValueError):
        emit(f'FAIL {stages[passed]} {passed}/8')
        return False
    emit('CARBON SPLITFLOW PASS 8/8')
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--check', type=Path, help='events.log or game_run scratch directory')
    mode.add_argument('--settings', action='store_true', help='print the game_run recipe as JSON')
    args = parser.parse_args()
    if args.settings:
        print(json.dumps(settings(), indent=2))
        return 0
    return 0 if check(args.check) else 1


if __name__ == '__main__':
    raise SystemExit(main())
