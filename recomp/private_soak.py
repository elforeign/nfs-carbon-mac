"""Seeded career route and a conservative, offline soak verdict.

Frames are mapped to wall seconds using diagnostic frame_times.tsv (stats.log
is a fallback). Autodrive position is a world coordinate, never race standing.
Only adjacent active free-roam samples count; loading/menu gaps do not count.
"""
import argparse
import bisect
from collections import Counter
import hashlib
from pathlib import Path
import re
import sys

HERE = Path(__file__).resolve().parent

# Decoded from the seeded premise: Career opens with WORLD MAP selected;
# RIGHT selects FREE ROAM. The same package controls both Career menus.
# Both roam and racing report none; the native observer gates this map row on
# active free roam before any race. Keep the initial 70-second dwell, then retry
# after five seconds in control and every ten seconds until a map takes control.
CAREER_ROWS = [
    ('none', 'M', 300, 600),
    ('Loading.fng', '-', 0, 0),
    ('Loading_Tips.fng', '-', 0, 0),
    ('FeMainMenu_Sub.fng', 'RETURN', 300, 300),
    ('FeDialog.fng', 'RETURN', 120, 300),
    ('WorldMapMain.fng', 'SPACE', 150, 0),
    ('FeWorldMapQuickList.fng', 'RETURN', 150, 0),
    ('FESubtitler.fng', 'RETURN', 150, 0),
    ('FePostRaceResults.fng', 'RETURN', 150, 150),
    ('FePostStages.fng', 'RETURN', 150, 150),
    # Native Busted menu starts at its first available option: pay, then marker.
    # Payment can continue through the owned-car selector (00844140 state 5).
    ('FeBusted.fng', 'RETURN', 150, 150),
    ('FeCarSelect.fng', 'RETURN', 150, 150),
]

MODE_EVENTS = {'duel': 'qr.3.1:0:1', 'boss': '4.duel:3:1', 'crew': 'tn.3.1:0:1'}
MODE_ROWS = [
    ('none', '-', 0, 0),
    ('Loading.fng', '-', 0, 0),
    ('Loading_Tips.fng', '-', 0, 0),
    ('Loading_Controller.fng', '-', 0, 0),
    ('FESubtitler.fng', 'RETURN', 150, 0),
    ('FeDialog.fng', 'RETURN', 150, 300),
    ('FePostStages.fng', 'RETURN', 150, 150),
    ('FePostRaceResults.fng', '-', 0, 0),
]


def write_route(table, route='career'):
    table = table.resolve()
    if ',' in str(table) or len('soak:' + str(table)) > 127:
        raise ValueError('table path must fit one 127-character script token without commas')
    table.parent.mkdir(parents=True, exist_ok=True)
    rows = CAREER_ROWS if route == 'career' else MODE_ROWS
    # A62064 binds the crew ability to Right Control. Retry only in gameplay;
    # loading, subtitles and results retain their own rows.
    if route == 'crew':
        rows = [('none', 'RCTRL', 1200, 600) if row[0] == 'none' else row for row in rows]
    table.write_text('# screen\tkey\tticks in control before key\trepeat ticks\n' +
                     ''.join('\t'.join(map(str, row)) + '\n' for row in rows))
    if route != 'career':
        return 'seq:soak:' + str(table)
    return ('seq:pkg:FeMainMenu.fng:RETURN,pkg:FeMainMenu_Sub.fng:RETURN,'
            'wait:300,RETURN,wait:300,RIGHT,wait:30,RETURN,wait:4200,soak:' + str(table))


def frame_clock(diag):
    frames, seconds = [], []
    path = diag / 'frame_times.tsv'
    if path.is_file():
        with path.open(errors='replace') as stream:
            for line in stream:
                fields = line.split()
                if len(fields) < 2:
                    continue
                try:
                    ns, frame = int(fields[0]), int(fields[1])
                except ValueError:
                    continue
                if not frames or frame > frames[-1]:
                    frames.append(frame); seconds.append(ns / 1e9)
    if not frames and (diag / 'stats.log').is_file():
        with (diag / 'stats.log').open(errors='replace') as stream:
            for line in stream:
                match = re.match(r't ([\d.]+) frame (\d+) ', line)
                if match and (not frames or int(match[2]) > frames[-1]):
                    frames.append(int(match[2])); seconds.append(float(match[1]))

    def stamp(frame):
        if not frames or frame < frames[0] or frame > frames[-1]:
            return None
        index = bisect.bisect_left(frames, frame)
        if frames[index] == frame:
            return seconds[index]
        fraction = (frame - frames[index - 1]) / (frames[index] - frames[index - 1])
        return seconds[index - 1] + fraction * (seconds[index] - seconds[index - 1])
    return stamp, bool(frames)


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def count_fatals(line, stubs, untranslated):
    for marker, counts in (('PRIVATE STUB ', stubs), ('reached untranslated function', untranslated)):
        if marker in line:
            counts[line.split(marker, 1)[1].strip()] += 1


def summarize(run, seed):
    run = run.resolve()
    diag = run if run.name == 'diag' else run / 'diag'
    run = diag.parent
    events, output = diag / 'events.log', run / 'diag.out'
    missing = [str(path) for path in (events, output, seed) if not path.is_file()]
    stamp, has_clock = frame_clock(diag)
    if not has_clock:
        missing.append('diagnostic wall clock')
    stub_lines, untranslated_lines = Counter(), Counter()
    event_stub_lines, event_untranslated_lines = Counter(), Counter()
    if output.is_file():
        with output.open(errors='replace') as stream:
            for line in stream:
                count_fatals(line, stub_lines, untranslated_lines)
    reports = sorted(str(path.relative_to(run)) for path in run.rglob('*')
                     if path.is_file() and re.fullmatch(r'(?:crash.*|hang_\d+|stall_\d+)\.txt', path.name))
    unknown, errors, screens = [], [], []
    roam = 0.0
    previous_roam = None
    started = finished = 0
    racing = False
    race_finished = False
    position = standing = None
    if events.is_file():
        with events.open(errors='replace') as stream:
            for line in stream:
                # Most lines are imports; avoid regex work for those.
                if not any(word in line for word in ('screen: ', 'autodrive:', 'soak:',
                                                     'package timeout', 'PRIVATE STUB ',
                                                     'reached untranslated function')):
                    continue
                # Fatal evidence can appear in events even when stderr is absent.
                if 'PRIVATE STUB ' in line or 'reached untranslated function' in line:
                    count_fatals(line, event_stub_lines, event_untranslated_lines)
                match = re.match(r'f(\d+) t\d+ (.*)', line)
                if not match:
                    continue
                frame, message = int(match[1]), match[2].rstrip()
                if message.startswith('screen: '):
                    name = message[8:]
                    screens.append(name)
                    if name == 'Loading_Tips.fng':
                        racing = False
                        previous_roam = None
                    if name == 'FePostRaceResults.fng' and started > finished and not race_finished:
                        finished += 1; race_finished = True
                elif message.startswith('soak: unknown screen '):
                    unknown.append(message[len('soak: unknown screen '):].split(';')[0])
                elif message.startswith('soak: error ') or message.startswith('script: package timeout '):
                    errors.append(message)
                elif message.startswith('autodrive: waiting '):
                    previous_roam = None
                elif message.startswith('autodrive: speed='):
                    sample = re.search(r' racers=(\d+)\b', message)
                    if not sample:
                        continue
                    racers = int(sample[1])
                    now = stamp(frame)
                    if racers == 0:
                        if now is not None and previous_roam is not None:
                            elapsed = now - previous_roam
                            if 0 <= elapsed <= 2.5:
                                roam += elapsed
                        previous_roam = now
                        racing = False
                    else:
                        previous_roam = None
                        if not racing:
                            started += 1; racing = True; race_finished = False
                    coordinate = re.search(r' position=([^ ]+)', message)
                    if coordinate:
                        position = coordinate[1]
                    rank = re.search(r' (?:race_position|standing)=(\d+)\b', message)
                    if rank:
                        standing = int(rank[1])
    # Do not compare the launcher's extra copy outside Carbon's native save root.
    saves = sorted((run / 'diag.user' / 'Carbon' / 'NFS Carbon').glob('*/*'))
    saves = [path for path in saves if path.is_file() and path.name == path.parent.name]
    save = next((path for path in saves if path.name == seed.name), None)
    if save is None and len(saves) == 1:
        save = saves[0]
    if save is None and len(saves) > 1:
        missing.append('ambiguous native save profile')
    # Mirrored messages count once per occurrence; distinct messages from
    # different outputs are still separate fatal lines.
    stub = sum((stub_lines | event_stub_lines).values())
    untranslated = sum((untranslated_lines | event_untranslated_lines).values())
    seed_hash = sha256(seed) if seed.is_file() else None
    save_hash = sha256(save) if save else None
    changed = bool(save_hash and seed_hash and save_hash != seed_hash)
    passed = (not missing and not stub and not untranslated and not reports and
              not unknown and not errors and roam >= 60 and finished >= 1 and changed)
    return dict(stub=stub, untranslated=untranslated, reports=reports, unknown=unknown,
                errors=errors, missing=missing, screens=screens, roam_seconds=roam,
                races_started=started, races_finished=finished, standing=standing,
                position=position, save=str(save) if save else None, seed_sha256=seed_hash,
                save_sha256=save_hash, save_changed=changed, passed=passed)


def print_summary(result):
    print('PRIVATE SOAK: stub={stub} untranslated={untranslated} reports={reports}'.format(
        **dict(result, reports=len(result['reports']))))
    print('screen order: ' + ' -> '.join(result['screens']))
    print('unknown screens ({}): {}'.format(len(result['unknown']), ', '.join(result['unknown']) or 'none'))
    print('crash / hang / stall files: ' + (', '.join(result['reports']) or 'none'))
    print('free-roam seconds: {:.3f}; races started / finished: {} / {}'.format(
        result['roam_seconds'], result['races_started'], result['races_finished']))
    print('race standing: {}; last world position: {}'.format(
        result['standing'] if result['standing'] is not None else 'not logged',
        result['position'] or 'not logged'))
    print('seed SHA-256: ' + (result['seed_sha256'] or 'missing'))
    print('save SHA-256: ' + (result['save_sha256'] or 'missing'))
    print('save changed: ' + ('yes' if result['save_changed'] else 'no'))
    for error in result['missing'] + result['errors']:
        print('error: ' + error)
    print('PASS' if result['passed'] else 'FAIL')


def summarize_mode(run, mode, cap):
    """Require native launch evidence and continuous stats, independently.

    Offline proof: good frames gap=1/last=120; broken gap=15/last=120 fails.
    Absent-event control must fail reached even when phase retains reset 3.
    Live duel PASS (run 3): reached=1, gap=1.1, last=199.3, clean results idle.
    Old boss run 4: identity=1, drove=0, gap=1.1, last=24.1, bad subtitler idle.
    Corrected boss 300: reached=1, drove=1, gap=1.1, last=185.3, clean results.
    Crew 120: spawned=1, ability active=1, gap=1.1, last=99.2 (short tail FAIL).
    Crew 300: spawned=1, ability active=1, gap=1.1, last=181.5, clean results.
    Offline absent-event control (all modes): reached=0, gap=1, last=120;
    frame rule passes, overall FAIL. Live qr.9.9: reached=0, event=0,
    gap=1.3, last=38.4; short tail and unexpected free-roam SMS also fail.
    """
    diag = run if run.name == 'diag' else run / 'diag'
    missing = [name for name in ('events.log', 'stats.log') if not (diag / name).is_file()]
    samples = []
    if (diag / 'stats.log').is_file():
        for line in (diag / 'stats.log').read_text(errors='replace').splitlines():
            # Audio appends its own frame snapshots to this same file. Only
            # the main frame producer's fps rows define frame advancement.
            m = re.match(r't ([\d.]+) frame (\d+) fps ', line)
            if m:
                samples.append((float(m[1]), int(m[2])))
    gaps = [b[0] - a[0] for a, b in zip(samples, samples[1:])]
    largest = max(gaps, default=0)
    last = samples[-1][0] - samples[0][0] if samples else 0
    advancing = len(samples) >= 2 and all(0 < gap <= 10 for gap in gaps) and all(
        b[1] > a[1] for a, b in zip(samples, samples[1:]))
    screens, states, idle, errors, unknown_logged = [], [], [], [], []
    stages, positions, speeds, crew = [], [], [], []
    ability_requests = 0
    current_screen = 'none'
    ended = False
    idle_ok = True
    if (diag / 'events.log').is_file():
        with (diag / 'events.log').open(errors='replace') as stream:
            for line in stream:
                if 'screen: ' in line:
                    m = re.match(r'f\d+ t\d+ screen: (.*)', line)
                    if m:
                        current_screen = m[1].strip(); screens.append(current_screen)
                elif 'soak: mode ' in line:
                    values = dict(re.findall(r'(\w+)=(-?[0-9a-f]+)\b', line.split('soak: mode ', 1)[1]))
                    keys = ('phase', 'event', 'attrs', 'kind', 'boss', 'started', 'stage', 'result', 'clone', 'abilities')
                    if not all(key in values for key in keys):
                        errors.append('incomplete mode line'); continue
                    state = {key: int(values[key], 16 if key in ('event', 'attrs') else 10) for key in keys}
                    states.append(state)
                    if state['event'] and state['kind'] == 13:
                        if not stages or stages[-1] != state['stage']:
                            stages.append(state['stage'])
                    if state['event'] and state['result'] in (2, 4, 5):
                        ended = True
                elif 'soak: idle ' in line:
                    screen = line.split('soak: idle ', 1)[1].strip(); idle.append(screen)
                    idle_ok &= screen == 'FePostRaceResults.fng' and (ended or
                               mode != 'duel' and current_screen == 'FePostRaceResults.fng' and
                               any(s['event'] for s in states))
                elif 'soak: crew ' in line:
                    values = dict(re.findall(r'(\w+)=([0-9a-f]+)\b', line.split('soak: crew ', 1)[1]))
                    if all(key in values for key in ('ability', 'vehicle', 'state', 'role', 'ready')):
                        crew.append({key: int(value, 16 if key in ('ability', 'vehicle') else 10)
                                     for key, value in values.items()})
                elif 'soak: key RCTRL screen=none' in line:
                    ability_requests += 1
                elif 'soak: unknown screen ' in line:
                    unknown_logged.append(line.split('soak: unknown screen ', 1)[1].split(';')[0].strip())
                elif 'soak: error ' in line or 'script: package timeout ' in line:
                    errors.append(line.strip())
                if 'autodrive: speed=' in line:
                    m = re.search(r'speed=([-\d.]+)_mps', line)
                    if m: speeds.append(float(m[1]))
                    m = re.search(r' position=([^ ]+)', line)
                    if m: positions.append(m[1].strip())
    unknown = sorted((set(screens) - {row[0] for row in MODE_ROWS}) | set(unknown_logged))
    # A terminal results screen is the native race-ended witness for circuit;
    # duel additionally requires its decoded result state.
    ended |= mode != 'duel' and 'FePostRaceResults.fng' in screens and bool(states)
    clean = bool(idle) and idle_ok
    at_cap = bool(samples) and last >= cap - 10
    frame_ok = advancing and (at_cap or clean)
    if mode == 'duel':
        two_stages = any(a == 1 and b == 0 for a, b in zip(stages, stages[1:]))
        reached = two_stages and any(s['event'] and s['kind'] == 13 and s['started'] for s in states) and (ended or at_cap)
    elif mode == 'boss':
        reached = any(s['event'] and s['attrs'] and s['kind'] == 13 and s['clone'] == 1 and
                      s['boss'] == 1 and s['phase'] == 3 and s['started'] for s in states)
    else:
        # tn.3.1 is the retail circuit (kind table A61180: circuit = 1).
        reached = any(s['event'] and s['kind'] == 1 and s['clone'] == 1 and
                      s['started'] and s['abilities'] >= 1 for s in states)
    reports = sorted(str(p.relative_to(diag.parent)) for p in diag.parent.rglob('crash*.txt') if p.is_file())
    output = diag.parent / 'diag.out'
    fatals = []
    if output.is_file():
        fatals = [line for line in output.read_text(errors='replace').splitlines()
                  if 'PRIVATE STUB ' in line or 'reached untranslated function' in line]
    drove = any(s > 1 for s in speeds) and len(set(positions)) > 1
    passed = reached and drove and frame_ok and not (missing or errors or unknown or reports or fatals) and idle_ok
    return dict(mode=mode, passed=passed, reached=reached, frame_advance=frame_ok,
                largest_gap=largest, last_sample=last, samples=len(samples),
                first_frame=samples[0][1] if samples else None,
                last_frame=samples[-1][1] if samples else None,
                states=states, stages=stages, screens=screens, idle=idle, errors=errors,
                unknown=unknown, reports=reports, fatals=fatals, missing=missing,
                ended=ended, at_cap=at_cap, drove=drove,
                crew=crew, ability_requests=ability_requests,
                crew_spawned=any(c['ability'] and c['vehicle'] for c in crew),
                ability_active=any(c['state'] == 2 for c in crew),
                last_position=positions[-1] if positions else None, max_speed=max(speeds, default=0))


def print_mode_summary(result):
    print('PRIVATE MODE {mode}: reached={reached} frame_advance={frame_advance} '
          'gap={largest_gap:.1f}s last={last_sample:.1f}s samples={samples} '
          'frames={first_frame}..{last_frame}'.format(**result))
    print('observed: ' + '; '.join(f'{key}={sorted({s[key] for s in result["states"]})}'
          for key in ('kind', 'phase', 'boss', 'started', 'stage', 'result', 'clone', 'abilities')))
    print('screens: ' + ' -> '.join(result['screens']))
    print('drove={drove} max_speed={max_speed} last_position={last_position} '
          'ended={ended} cap={at_cap} idle={idle}'.format(**result))
    if result['mode'] == 'crew':
        print('crew_spawned={crew_spawned} ability_requests={ability_requests} '
              'ability_active={ability_active}'.format(**result))
    print('; '.join(f'{key}={len(result[key])}' for key in
                   ('errors', 'unknown', 'reports', 'fatals', 'missing')))
    for key in ('errors', 'unknown', 'reports', 'fatals', 'missing'):
        for value in result[key]: print(f'{key}: {value}')
    print('PASS' if result['passed'] else 'FAIL')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--route', choices=['career', 'duel', 'boss', 'crew'])
    mode.add_argument('--summary', type=Path, metavar='RUN_DIR')
    parser.add_argument('--table', type=Path, default=HERE / 'out/carbon/career_soak.tsv')
    parser.add_argument('--seed', type=Path)
    parser.add_argument('--mode', choices=['duel', 'boss', 'crew'])
    parser.add_argument('--seconds', type=int)
    args = parser.parse_args(argv)
    if args.route:
        spec = write_route(args.table, args.route)
        if args.route != 'career':
            print('NFS_CARBON_SKIPFE=1 NFS_CARBON_SKIPFE_EVENT=' + MODE_EVENTS[args.route] +
                  ' NFS_CARBON_SKIPFE_CAR=rx8 BOOT_AUTODRIVE=1 BOOT_KEYS_STRICT=1')
            print('BOOT_KEYS=' + spec)
        else:
            print(spec)
        return 0
    if args.mode:
        if not args.seconds or args.seconds < 1:
            parser.error('--mode requires positive --seconds')
        result = summarize_mode(args.summary, args.mode, args.seconds)
        print_mode_summary(result)
        return 0 if result['passed'] else 1
    if not args.seed:
        parser.error('--summary requires --seed')
    result = summarize(args.summary, args.seed)
    print_summary(result)
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
