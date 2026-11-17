"""Soak fixtures: career good exit 0; stub, unchanged save, unknown exit 1.

Mode good: reached=1, frame gap=1 s, last=120 s, exit 0. Absent-event control:
reached=0 with good frames, exit 1. A 15 s gap with reached=1 exits 1. Native
idle requests one quit at 1200 ticks; removing the end call requests zero,
and removing the freeze lets a later key through (exit 1). Mode observer:
ten changes, zero duplicates and zero guest writes. Advancing native cinematic
survives 30 seconds; frozen/invalid clocks quit after 20 seconds, an advancing
one still quits at 90. Removing progress credit fails the 30-second check.
Crew observer: three changes, no guest writes. Right Control delivers one
down/up pair at DIK 9D; removing delivery fails the key-down check.
Final-result hold: first
leg=0, final=1, circuit=1, disabled/career=0. The route contains FePostStages;
missing Busted/CarSelect rows fail their independent checks. Sequence checks
cover key release/repeat, control transfer and nonterminal soak rejection.
Map retry: swallowed first press gives 2 requests; old one-shot/table gives 1
and exit 1 at the second-request check. Good bust reentry gives request 3;
menus, racing and retained finished racers give 0 extra map presses. Removing
the native free-roam guard fails the race check (requests 4 vs 2, exit 1).
"""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import private_soak as soak
import private_input_test as fixture
import private_script_test as script_fixture


def verdict_fixtures(folder):
    seed = folder / 'seed'
    seed.write_bytes(b'original save')
    run = folder / 'run'
    diag = run / 'diag'; diag.mkdir(parents=True)
    save = run / 'diag.user/Carbon/NFS Carbon/Fixture/Fixture'
    save.parent.mkdir(parents=True)
    # An unchanged launcher convenience copy must not hide a native save update.
    copy = run / 'diag.user/NFS Carbon/Fixture/Fixture'
    copy.parent.mkdir(parents=True); copy.write_bytes(seed.read_bytes())
    clock = ''.join(f'{(1000 + frame) * 1000000000}\t{frame}\t0\n' for frame in range(110))
    (diag / 'frame_times.tsv').write_text(clock)
    events = ['f0 t1 screen: none\n']
    events += [f'f{frame} t1 autodrive: speed=1_mps racers=0 position=1,2,3\n' for frame in range(61)]
    events += ['f62 t1 autodrive: waiting flow=5 sim_state=1\n',
               'f70 t1 autodrive: speed=2_mps racers=8 position=4,5,6\n',
               'f71 t1 autodrive: speed=3_mps racers=8 position=7,8,9\n',
               'f89 t1 autodrive: waiting flow=3 sim_state=1\n',
               'f90 t1 screen: FePostRaceResults.fng\n',
               'f91 t1 autodrive: speed=0_mps racers=8 position=7,8,9\n',
               'f92 t1 screen: FePostRaceResults.fng\n']
    baseline = ''.join(events)
    cases = ('pass', 'stub', 'unchanged', 'unknown', 'untranslated', 'hang', 'gap', 'missing', 'event_stub', 'split_stubs')
    for case in cases:
        save.write_bytes(seed.read_bytes() if case == 'unchanged' else b'updated save')
        (run / 'diag.out').write_text('PRIVATE STUB example.dll!Missing\n' if case in ('stub', 'split_stubs') else
                                    'reached untranslated function 12345678\n' if case == 'untranslated' else '')
        text = baseline + ('f95 t1 soak: unknown screen Missing.fng; input stopped\n' if case == 'unknown' else '')
        if case == 'event_stub':
            text += 'f95 t1 PRIVATE STUB example.dll!Missing\n'
        if case == 'split_stubs':
            text += 'f94 t1 PRIVATE STUB example.dll!Missing\nf95 t1 PRIVATE STUB example.dll!Another\n'
        if case == 'gap':
            text = ''.join(line for line in text.splitlines(True) if 'racers=0' not in line or line.startswith(('f0 ', 'f60 ')))
        (diag / 'events.log').write_text(text)
        if case == 'hang':
            (diag / 'hang_1.txt').write_text('fixture hang')
        if case == 'missing':
            (run / 'diag.out').unlink()
        result = soak.summarize(run, seed)
        expected_stub = 2 if case == 'split_stubs' else int(case in ('stub', 'event_stub'))
        assert result['stub'] == expected_stub
        assert result['untranslated'] == (case == 'untranslated')
        assert len(result['reports']) == (case == 'hang')
        assert result['races_started'] == result['races_finished'] == 1
        assert result['standing'] is None and result['position'] == '7,8,9'
        assert result['roam_seconds'] == (0 if case == 'gap' else 60)
        assert result['passed'] == (case == 'pass'), (case, result)
        with contextlib.redirect_stdout(io.StringIO()) as printed:
            status = soak.main(['--summary', str(run), '--seed', str(seed)])
        assert status == (0 if case == 'pass' else 1)
        assert printed.getvalue().startswith('PRIVATE SOAK: stub={} untranslated={} reports={}'.format(
            expected_stub, int(case == 'untranslated'), int(case == 'hang')))
        print(f'verdict {case}: exit={status} counts={result["stub"]}/{result["untranslated"]}/{len(result["reports"])}')
        (diag / 'hang_1.txt').unlink(missing_ok=True)
    table = folder / 'route.tsv'
    spec = soak.write_route(table)
    assert spec.endswith(',soak:' + str(table.resolve()))
    assert len(table.read_text().splitlines()) == len(soak.CAREER_ROWS) + 1
    assert 'FePostStages.fng\tRETURN\t150\t150' in table.read_text().splitlines()  # Pursuit Results prompt
    old_rows = soak.CAREER_ROWS
    for package in ('FeBusted.fng', 'FeCarSelect.fng'):
        row = package + '\tRETURN\t150\t150'
        assert table.read_text().splitlines().count(row) == 1
        try:
            soak.CAREER_ROWS = [item for item in old_rows if item[0] != package]
            soak.write_route(table)
            try:
                assert table.read_text().splitlines().count(row) == 1
            except AssertionError:
                print(f'broken old route: {package} rows=0 vs 1, AssertionError')
            else:
                raise AssertionError('missing row must fail the route check: ' + package)
        finally:
            soak.CAREER_ROWS = old_rows
            soak.write_route(table)
        print(f'good route: {package} rows=1')


def mode_fixtures(folder):
    """Good=gap 1/last 120; broken gap=15/last 120, absent reached=0."""
    run = folder / 'mode'; diag = run / 'diag'; diag.mkdir(parents=True)
    (run / 'diag.out').write_text('')
    good_stats = ''.join(f't {1000+t}.0 frame {t*60} fps 60\n' for t in range(121))
    def state(frame, kind, boss, phase, stage, result=0, event='01000000', abilities=0):
        return (f'f{frame} t1 soak: mode phase={phase} event={event} attrs=01010000 '
                f'kind={kind} boss={boss} started=1 stage={stage} result={result} clone=1 abilities={abilities}\n')
    for mode in ('duel', 'boss', 'crew'):
        baseline = 'f0 t1 screen: none\n'
        baseline += state(60, 1 if mode == 'crew' else 13, int(mode == 'boss'),
                          3 if mode == 'boss' else 0, 1, abilities=int(mode == 'crew'))
        baseline += state(120, 1 if mode == 'crew' else 13, int(mode == 'boss'),
                          3 if mode == 'boss' else 0, 0, abilities=int(mode == 'crew'))
        baseline += ('f180 t1 autodrive: speed=2_mps racers=2 position=1,2,3\n'
                     'f240 t1 autodrive: speed=3_mps racers=2 position=4,5,6\n')
        if mode == 'crew':
            baseline += ('f180 t1 soak: crew ability=01020000 vehicle=01030000 state=1 role=2 ready=1\n'
                         'f200 t1 soak: key RCTRL screen=none ticks=1200\n'
                         'f210 t1 soak: crew ability=01020000 vehicle=01030000 state=2 role=2 ready=1\n')
        for case in ('pass', 'absent', 'gap', 'frozen', 'short', 'unknown', 'unknown_log', 'error', 'crash', 'idle', 'results', 'still', 'audio', 'wrong_mode', 'not_started'):
            (diag / 'stats.log').write_text(''.join(line for t, line in enumerate(good_stats.splitlines(True))
                if not (case == 'gap' and 30 < t < 45) and not (case == 'short' and t > 100)))
            if case == 'frozen':
                (diag / 'stats.log').write_text(good_stats.replace('frame 3600 ', 'frame 3540 '))
            if case == 'audio':
                (diag / 'stats.log').write_text(good_stats + 't 1015.0 frame 900 mixrms 0\n')
            events = baseline
            if case == 'still': events = baseline.split('f180 t1 autodrive:', 1)[0]
            if case == 'not_started': events = baseline.replace('started=1', 'started=0')
            if case == 'wrong_mode':
                events = baseline.replace('stage=0', 'stage=1') if mode == 'duel' else (
                    baseline.replace('boss=1', 'boss=0') if mode == 'boss' else
                    baseline.replace('abilities=1', 'abilities=0'))
            if case == 'absent': events = state(0, -1, 0, 3, 0, event='00000000')
            if case == 'unknown': events += 'f300 t1 screen: Missing.fng\n'
            if case == 'unknown_log': events += 'f300 t1 soak: unknown screen Missing.fng; input stopped\n'
            if case == 'error': events += 'f300 t1 soak: error fixture\n'
            if case == 'idle': events += 'f300 t1 soak: idle FeDialog.fng\n'
            if case == 'results':
                events += state(300, 1 if mode == 'crew' else 13, int(mode == 'boss'),
                                3 if mode == 'boss' else 0, 0, 2, abilities=int(mode == 'crew'))
                events += 'f301 t1 screen: FePostRaceResults.fng\nf1500 t1 soak: idle FePostRaceResults.fng\n'
                (diag / 'stats.log').write_text(''.join(good_stats.splitlines(True)[:26]))
            (diag / 'events.log').write_text(events)
            if case == 'crash': (diag / 'crash.txt').write_text('fixture')
            result = soak.summarize_mode(run, mode, 120)
            assert result['passed'] == (case in ('pass', 'results', 'audio')), (mode, case, result)
            if case == 'absent': assert not result['reached']
            if case == 'gap': assert result['largest_gap'] == 15 and not result['frame_advance']
            if mode == 'crew' and case == 'pass':
                assert result['crew_spawned'] and result['ability_active'] and result['ability_requests'] == 1
            (diag / 'crash.txt').unlink(missing_ok=True)
            print(f'mode {mode}/{case}: reached={int(result["reached"])} gap={result["largest_gap"]} last={result["last_sample"]} pass={int(result["passed"])}')
        table = folder / 'mode.tsv'
        spec = soak.write_route(table, mode)
        assert spec == 'seq:soak:' + str(table.resolve()) and 'race:' not in spec
        assert len(table.read_text().splitlines()) == 9
        if mode == 'crew': assert 'none\tRCTRL\t1200\t600\n' in table.read_text()


SOAK_CASES = r'''
 if(!strcmp(argv[1],"soak_mode")) {
  extern int carbon_soak_hold_results(void);
  setenv("NFS_CARBON_SKIPFE_EVENT","qr.3.1:0:1",1);
  packages();tick(&c,1);unsigned initial=mode_records;CHECK(initial==1);
  tick(&c,2);CHECK(mode_records==initial);
  M32(0xA98284)=0x1000000;M32(0x1006A18)=3;tick(&c,1);CHECK(mode_records==++initial);
  M32(0x1006A1C)=0x1100000;M32(0x1100004)=0x1200000;
  M8(0x120002B)=13;M32(0x1200018)=0x20;M8(0x110001F)=1;
  tick(&c,1);CHECK(mode_records==++initial);tick(&c,2);CHECK(mode_records==initial);
  M8(0x100BCB8)=1;tick(&c,1);CHECK(mode_records==initial);
  M32(0x1006A14)=1;M8(0x100BCBA)=1;tick(&c,1);CHECK(mode_records==++initial);
  CHECK(!carbon_soak_hold_results());
  M32(0x100BCE4)=5;CHECK(carbon_soak_hold_results());M32(0x100BCE4)=0;
  M8(0x100BCBA)=0;tick(&c,1);CHECK(mode_records==++initial);
  CHECK(carbon_soak_hold_results());
  M8(0x120002B)=1;tick(&c,1);CHECK(mode_records==++initial);
  CHECK(carbon_soak_hold_results());
  diag_on=0;CHECK(!carbon_soak_hold_results());diag_on=1;
  unsetenv("NFS_CARBON_SKIPFE_EVENT");CHECK(!carbon_soak_hold_results());
  M32(0x1200018)=0;tick(&c,1);CHECK(mode_records==++initial);
  M32(0x100BCE4)=2;tick(&c,1);CHECK(mode_records==++initial);
  M32(0xAA26A4)=1;tick(&c,1);CHECK(mode_records==++initial);
  M8(0x110001F)=0;tick(&c,1);CHECK(mode_records==++initial);
  unsigned char snapshot[0xC000];memcpy(snapshot,G+0x1000000,sizeof snapshot);
  tick(&c,5);CHECK(mode_records==initial);CHECK(!memcmp(snapshot,G+0x1000000,sizeof snapshot));
  puts("mode observer: changes=10 duplicate=0 guest writes=0");
 } else if(!strcmp(argv[1],"soak_crew")) {
  extern uint8_t di_keys[256];
  packages();M32(0xA220)=0;
  M32(0xAA269C)=0x1500000;M32(0xAA26A4)=1;M32(0x1500000)=0x1600000;
  M32(0x1600000)=0x1700000;M32(0x1700014)=0x40CA10;M32(0x170001C)=0x40CA20;
  M32(0x1600008)=0x1800000;M32(0x160006C)=1;M32(0x1600070)=2;
  tick(&c,1);CHECK(crew_records==1);tick(&c,2);CHECK(crew_records==1);
  M8(0x1600074)=1;tick(&c,1);CHECK(crew_records==2);
  M32(0x160006C)=2;tick(&c,1);CHECK(crew_records==3);
  unsigned char snapshot[0x320];memcpy(snapshot,G+0x1600000,sizeof snapshot);
  tick(&c,145);CHECK(downs==0);tick(&c,1);CHECK(downs==1&&di_keys[0x9D]==0x80);
  tick(&c,4);CHECK(ups==1&&di_keys[0x9D]==0&&chars==0);
  CHECK(crew_records==3&&!memcmp(snapshot,G+0x1600000,sizeof snapshot));
  puts("crew: 3 native changes, zero guest writes; RCTRL down/up=1/1, DIK 9D released");
 } else if(!strncmp(argv[1],"soak_cinematic",14)) {
  packages();strcpy((char*)G+0xB200,"FESubtitler.fng");
  M32(0xA98284)=0x1000000;M32(0x1006A1C)=0x1100000;M32(0x1100004)=0x1200000;
  M8(0x120002B)=13;M32(0x1200018)=0x20;
  M32(0xB4D964)=0x1300000;M32(0x1300000)=0x9EC6E8;M32(0x13002E0)=5;
  M32(0x1300390)=0x1400000;M32(0x1400000)=0x9C5FE0;
  float length=200;memcpy(G+0x1400028,&length,4);
  int invalid=strcmp(argv[1],"soak_cinematic_invalid")==0;
  if(invalid)M32(0x1400000)=0;
  for(unsigned i=0;i<1800;i++){float t=i/60.f;memcpy(G+0x1400020,&t,4);tick(&c,1);}
  CHECK(end_requests==(invalid?1:0));
  if(!invalid) {
   if(!strcmp(argv[1],"soak_cinematic_cap")) {
    for(unsigned i=1800;i<5400;i++){float t=i/60.f;memcpy(G+0x1400020,&t,4);tick(&c,1);}
    CHECK(end_requests==0);tick(&c,1);CHECK(end_requests==1);
   } else {tick(&c,1201);CHECK(end_requests==1);}
  }
  tick(&c,100);CHECK(end_requests==1);
  puts("cinematic: advancing survives 30s; frozen/invalid ends after 20s; absolute cap 90s");
 } else if(!strcmp(argv[1],"soak_idle")) {
  packages();tick(&c,1200);CHECK(end_requests==0);
  tick(&c,1);CHECK(end_requests==1);tick(&c,100);CHECK(end_requests==1);
  puts("idle: 20 seconds requests=1");
 } else if(!strcmp(argv[1],"soak_map")) {
  packages();M32(0xA220)=0;
  M32(0x00A99BBC)=6;M32(0x00B4CFE0)=0xC000;M32(0xC024)=3;
  M32(0x00A98284)=0x1000000;M32(0x1006A18)=3;
  /* The first ordinary key opens nothing: control and guest state stay put. */
  tick(&c,301);CHECK(map_downs==1);tick(&c,4);CHECK(map_ups==1);
  tick(&c,595);CHECK(map_downs==1);tick(&c,1);CHECK(map_downs==2);
  tick(&c,4);CHECK(map_ups==2);
  M32(0x1006A14)=1;tick(&c,1200);CHECK(map_downs==2);
  /* Native results may clear the start flag but retain the race's racers. */
  M32(0x1006A14)=0;M32(0x1006A08)=8;tick(&c,1200);CHECK(map_downs==2);
  M32(0x1006A08)=0;
  /* A bust transfers to a menu, then reenters a fresh free-roam session. */
  strcpy((char*)G+0xB200,"FeBusted.fng");M32(0xA220)=1;
  tick(&c,1200);CHECK(map_downs==2);
  M32(0xA220)=0;tick(&c,300);CHECK(map_downs==2);
  tick(&c,1);CHECK(map_downs==3);tick(&c,4);CHECK(map_ups==3);
  strcpy((char*)G+0xB200,"WorldMapMain.fng");M32(0xA220)=1;
  tick(&c,1200);CHECK(map_downs==3);
  /* No controlling package is insufficient during loading/pauses/NIS. */
  M32(0xA220)=0;M32(0x00A99BBC)=3;tick(&c,1200);CHECK(map_downs==3);
  M32(0x00A99BBC)=6;M32(0xC024)=1;tick(&c,1200);CHECK(map_downs==3);
  M32(0xC024)=3;M32(0x00B4D964)=0xD000;tick(&c,1200);CHECK(map_downs==3);
  M32(0x00B4D964)=0;M32(0x1006A18)=1;tick(&c,1200);CHECK(map_downs==3);
  M32(0x1006A18)=3;M32(0x00A98284)=0;tick(&c,1200);CHECK(map_downs==3);
  puts("map retry: requests=2 after swallowed first, bust reentry=3; ineligible extra=0");
 } else if(!strcmp(argv[1],"soak")) {
  packages();tick(&c,150);CHECK(downs==0);
  tick(&c,1);CHECK(downs==1&&ups==0);tick(&c,4);CHECK(ups==1);
  tick(&c,146);CHECK(downs==2);tick(&c,4);CHECK(ups==2);
  M32(0xA220)=0;M32(0xA020)=1;
  tick(&c,150);CHECK(downs==2);tick(&c,1);CHECK(downs==3);
  tick(&c,4);CHECK(ups==3);tick(&c,400);CHECK(downs==3&&ups==3&&done==0);
 } else if(!strcmp(argv[1],"soak_unknown")) {
  packages();tick(&c,1800);CHECK(downs==0);
  tick(&c,1);CHECK(downs==0);
  M32(0xA220)=0;M32(0xA020)=1;tick(&c,500);CHECK(downs==0&&done==0);
 } else if(!strcmp(argv[1],"soak_nonterminal") || !strcmp(argv[1],"soak_bad")) {
  packages();tick(&c,2400);CHECK(downs==0&&done==0);
 } else
'''


def native_fixtures(root, folder):
    for name in ('game_script.h', 'carbon_soak.h', 'carbon_fe_control.h'):
        assert (root / 'runtime' / name).read_bytes() == (HERE / 'private_runtime' / name).read_bytes(), 'rebuild Carbon: ' + name
    registry = json.loads((HERE / 'private_runtime/features/script.json').read_text())
    assert registry['bindings']['carbon_soak.h']['sha256'] == hashlib.sha256((HERE / 'private_runtime/carbon_soak.h').read_bytes()).hexdigest()
    original_source, original_harness = fixture.selected_source, fixture.HARNESS

    mutant = False

    harness = script_fixture.HARNESS.replace(
        'static unsigned checks,downs,ups,chars,presents;',
        'static unsigned checks,downs,ups,chars,presents,map_downs,map_ups;')
    harness = harness.replace('static unsigned done,', 'static unsigned mode_records,end_requests,crew_records;\nstatic unsigned done,')
    harness = harness.replace(' ++diag_records;', ' ++diag_records;\n if(!strncmp(line,"soak: mode ",11))++mode_records;\n if(!strncmp(line,"soak: crew ",11))++crew_records;\n if(!strcmp(line,"soak: end requested"))++end_requests;')
    harness = harness.replace('arg(c,2)==13', '(arg(c,2)==13||arg(c,2)==32||arg(c,2)==\'M\'||arg(c,2)==0xA3)')
    harness = harness.replace('==0x1c)', '==(arg(c,2)==0xA3?0x9D:arg(c,2)==\'M\'?0x32:arg(c,2)==32?0x39:0x1c))')
    harness = harness.replace('++downs;', "++downs;if(arg(c,2)=='M')++map_downs;")
    harness = harness.replace('++ups;', "++ups;if(arg(c,2)=='M')++map_ups;")
    harness = harness.replace(' if(!strcmp(argv[1],"control")) {',
                              SOAK_CASES + ' if(!strcmp(argv[1],"control")) {', 1)

    def selected(path):
        source = original_source(path)
        if path.name == 'user32.m':
            include = (root / 'runtime/carbon_soak.h').read_text()
            assert include.count('[NSApp terminate:nil];') == 2
            if mutant is True:
                include = include.replace('[NSApp terminate:nil];\n        return -1;', '[NSApp terminate:nil];\n        return 0;')
            include = include.replace('[NSApp terminate:nil];', 'private_script_event("soak: end requested");' if mutant != 'noend' else ';')
            if mutant is True:
                assert include.count('return unknown_logged && strict ? -1 : 0;') == 1
                include = include.replace('return unknown_logged && strict ? -1 : 0;', 'return 0;')
            if mutant == 'unguarded':
                assert include.count('if (map && (') == 1
                include = include.replace('if (map && (', 'if (0 && (')
            if mutant == 'oldidle':
                credit = 'elapsed > cinematic_elapsed)\n            idle_since = tick;'
                assert include.count(credit) == 1
                include = include.replace(credit, 'elapsed > cinematic_elapsed)\n            idle_since += 0;')
            source = source.replace('#include "carbon_soak.h"', include)
            if mutant == 'nocrewkey':
                assert source.count('key_event(focus_hwnd, 0xA3, 0x9D, down, 0);') == 1
                source = source.replace('key_event(focus_hwnd, 0xA3, 0x9D, down, 0);', ';')
            source = 'extern void private_script_event(const char *, ...);\n' + source.replace('diag_event(', 'private_script_event(')
        return source
    fixture.selected_source = selected
    fixture.HARNESS = harness
    try:
        binary = fixture.build(root, folder, 'good')
    finally:
        fixture.selected_source, fixture.HARNESS = original_source, original_harness
    table = folder / 'table.tsv'
    soak.write_route(table)
    env = dict(os.environ, BOOT_HEADLESS='1', BOOT_KEYS='seq:soak:' + str(table), BOOT_KEYS_STRICT='1',
               BOOT_USERDATA=str(folder / 'map_userdata'), NFS_AUDIO='null', NFS_RUMBLE='off')
    run = subprocess.run([str(binary), 'soak_map'], env=env, capture_output=True, text=True, timeout=30)
    (folder / 'soak_map.log').write_text(run.stdout + run.stderr)
    assert run.returncode == 0, run.stderr[-2500:]
    assert run.stdout.count('soak: key M screen=none') == 3
    print('good ' + next(line for line in run.stdout.splitlines() if line.startswith('map retry:')))
    # The old prefix sends one M, then its idle none row never retries it.
    table.write_text(table.read_text().replace('none\tM\t300\t600\n', 'none\t-\t0\t0\n'))
    env['BOOT_KEYS'] = 'seq:M,soak:' + str(table)
    run = subprocess.run([str(binary), 'soak_map'], env=env, capture_output=True, text=True, timeout=30)
    (folder / 'soak_map_old.log').write_text(run.stdout + run.stderr)
    assert run.returncode == 1 and 'map_downs==2' in run.stderr, run.stderr[-2500:]
    assert run.stdout.count('scripted key M down') == 1
    print('broken old map route: requests=1 vs 2, exit=1')
    for case in ('soak', 'soak_unknown', 'soak_nonterminal', 'soak_bad', 'soak_idle', 'soak_mode',
                 'soak_cinematic', 'soak_cinematic_cap', 'soak_cinematic_invalid', 'soak_crew'):
        table.write_text('FeMainMenu.fng\tRETURN\t150\t0\n' +
                         ('' if case == 'soak_unknown' else 'FeDialog.fng\tRETURN\t150\t150\n'))
        if case == 'soak_bad':
            table.write_text('FeDialog.fng\tRETURN\t-1\t150\n')
        if case in ('soak_idle', 'soak_mode'):
            table.write_text('FeDialog.fng\t-\t0\t0\n')
        if case.startswith('soak_cinematic'):
            table.write_text('FESubtitler.fng\t-\t0\t0\n')
        if case == 'soak_crew': table.write_text('none\tRCTRL\t150\t0\n')
        spec = 'seq:soak:' + str(table) + (',RETURN' if case == 'soak_nonterminal' else '')
        assert len('soak:' + str(table)) <= 127
        env = dict(os.environ, BOOT_HEADLESS='1', BOOT_KEYS=spec, BOOT_KEYS_STRICT='1',
                   BOOT_USERDATA=str(folder / 'userdata'), NFS_AUDIO='null', NFS_RUMBLE='off')
        run = subprocess.run([str(binary), case], env=env, capture_output=True, text=True, timeout=30)
        (folder / (case + '.log')).write_text(run.stdout + run.stderr)
        assert run.returncode == 0, run.stderr[-2500:]
        if case == 'soak_unknown':
            assert run.stdout.count('soak: idle FeDialog.fng') == 1
            assert run.stdout.count('soak: end requested') == 1
        if case in ('soak_bad', 'soak_nonterminal'):
            assert 'soak: error ' in run.stdout
        if case not in ('soak_unknown', 'soak_idle') and not case.startswith('soak_cinematic'):
            assert 'soak: end requested' not in run.stdout
        screen = 'none' if case == 'soak_crew' else 'FESubtitler.fng' if case.startswith('soak_cinematic') else 'FeDialog.fng'
        assert run.stdout.count('screen: ' + screen + '\n') == 1
        print(run.stdout.strip().splitlines()[-1])
    mutant = 'oldidle'
    oldidle = folder / 'oldidle'; oldidle.mkdir(exist_ok=True)
    fixture.selected_source, fixture.HARNESS = selected, harness
    try:
        binary = fixture.build(root, oldidle, 'good')
    finally:
        fixture.selected_source, fixture.HARNESS = original_source, original_harness
    table.write_text('FESubtitler.fng\t-\t0\t0\n')
    env.update(BOOT_KEYS='seq:soak:' + str(table), BOOT_USERDATA=str(oldidle / 'userdata'))
    run = subprocess.run([str(binary), 'soak_cinematic'], env=env, capture_output=True, text=True, timeout=30)
    assert run.returncode == 1 and 'end_requests==(invalid?1:0)' in run.stderr, run.stderr[-2000:]
    print('broken cinematic idle: quits by 30s, expected zero quit requests; exit=1')
    mutant = 'nocrewkey'
    nocrewkey = folder / 'nocrewkey'; nocrewkey.mkdir(exist_ok=True)
    fixture.selected_source, fixture.HARNESS = selected, harness
    try:
        binary = fixture.build(root, nocrewkey, 'good')
    finally:
        fixture.selected_source, fixture.HARNESS = original_source, original_harness
    table.write_text('none\tRCTRL\t150\t0\n')
    env.update(BOOT_KEYS='seq:soak:' + str(table), BOOT_USERDATA=str(nocrewkey / 'userdata'))
    run = subprocess.run([str(binary), 'soak_crew'], env=env, capture_output=True, text=True, timeout=30)
    assert run.returncode == 1 and 'downs==1&&di_keys[0x9D]==0x80' in run.stderr, run.stderr[-2000:]
    print('broken crew key: down/up=0/0 vs 1/1; exit=1')
    mutant = True
    broken = folder / 'unfrozen'; broken.mkdir(exist_ok=True)
    fixture.selected_source = selected
    fixture.HARNESS = harness
    try:
        binary = fixture.build(root, broken, 'good')
    finally:
        fixture.selected_source, fixture.HARNESS = original_source, original_harness
    table.write_text('FeMainMenu.fng\tRETURN\t150\t0\n')
    env = dict(os.environ, BOOT_HEADLESS='1', BOOT_KEYS='seq:soak:' + str(table), BOOT_KEYS_STRICT='1',
               BOOT_USERDATA=str(broken / 'userdata'), NFS_AUDIO='null', NFS_RUMBLE='off')
    run = subprocess.run([str(binary), 'soak_unknown'], env=env, capture_output=True, text=True, timeout=30)
    (broken / 'soak_unknown.log').write_text(run.stdout + run.stderr)
    assert run.returncode == 1 and 'downs==0&&done==0' in run.stderr, run.stderr[-2000:]
    print('broken strict freeze: exit=1 ' + run.stderr.strip().splitlines()[-1])
    mutant = 'noend'
    noend = folder / 'noend'; noend.mkdir(exist_ok=True)
    fixture.selected_source = selected
    fixture.HARNESS = harness
    try:
        binary = fixture.build(root, noend, 'good')
    finally:
        fixture.selected_source, fixture.HARNESS = original_source, original_harness
    env['BOOT_USERDATA'] = str(noend / 'userdata')
    run = subprocess.run([str(binary), 'soak_unknown'], env=env, capture_output=True, text=True, timeout=30)
    assert 'soak: end requested' not in run.stdout and 'soak: idle FeDialog.fng' in run.stdout
    print('broken end request: line logged, no end requested (the end check would fail)')
    mutant = 'unguarded'
    unguarded = folder / 'unguarded'; unguarded.mkdir(exist_ok=True)
    fixture.selected_source, fixture.HARNESS = selected, harness
    try:
        binary = fixture.build(root, unguarded, 'good')
    finally:
        fixture.selected_source, fixture.HARNESS = original_source, original_harness
    soak.write_route(table)
    env.update(BOOT_KEYS='seq:soak:' + str(table), BOOT_USERDATA=str(unguarded / 'userdata'))
    run = subprocess.run([str(binary), 'soak_map'], env=env, capture_output=True, text=True, timeout=30)
    (unguarded / 'soak_map.log').write_text(run.stdout + run.stderr)
    assert run.returncode == 1 and 'map_downs==2' in run.stderr, run.stderr[-2500:]
    assert run.stdout.count('soak: key M screen=none') == 4
    print('broken race guard: requests=4 vs 2, exit=1')


def main():
    with tempfile.TemporaryDirectory(prefix='private-soak-') as temp:
        verdict_fixtures(Path(temp))
        mode_fixtures(Path(temp))
    root = HERE / 'out/carbon'
    if not all((root / name).is_file() for name in ('link_command.json', 'NFSC.a', 'runtime/disabled_providers.m.o')):
        print('SKIP: native private runtime build absent'); return 3
    command = json.loads((root / 'link_command.json').read_text())
    if [Path(arg).resolve() for arg in command if arg.endswith('/NFSC.a')] != [(root / 'NFSC.a').resolve()]:
        print('SKIP: native private runtime belongs to another checkout'); return 3
    folder = root / 'soak_test'; folder.mkdir(exist_ok=True)
    native_fixtures(root, folder)
    print('PRIVATE SOAK PASS')
    return 0


if __name__ == '__main__':
    sys.exit(main())
