"""Carbon F10: saved encodings, production selectors and live row transitions.

Good: 0 failures. Original registration: 11 missing rows; coat off-string:
2 failures; AO numeric-zero: 1 failure; unmapped preset enum: 3 failures.
Original loaded dump: 2 wrong rows; original Left: 2 failures (good: 0).
Live: 30 consumer checks, both saved starting states, plus preset members and
pending names: 0 failures. Old restart wiring: AO/mode/hour each 1 consumer
failure; limiter/triggers each 2 (exit 1 vs good 0). These controls bypass the
registration assertions so only frozen consumer state can fail them.
Every value, Reset and all six
directed preset transitions are checked across fresh processes. MW's existing
settings_look_test.c branch remains its independent preset regression.
Dependencies: runtime/portmenu.m runtime/settings.c runtime/settings_look_test.c runtime/settings.h
runtime/setting_bool.h runtime/game_select.h recomp/private_runtime/game_settings.h
recomp/private_runtime/features/port_settings.json
recomp/private_runtime/features/picture_01.json
J2: all four graphics rows export live; 54 setter transitions across nine rows
and both starting states pass; each old J2 restart wiring exits 1 vs good 0.
The Look restart notice retains only Day-night lighting.
"""
from pathlib import Path
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = ROOT / 'recomp/private_runtime'
sys.path.insert(0, str(PRIVATE))
from layers import load_manifest

# Independent registration expectation also consumed by private_settings_test.
SETTINGS_ROWS = {
    'gameplay.traffic_density': {},
    'gameplay.cheat_nitrous': {'apply': 'carbon_devrows_nitrous'},
    'gameplay.cheat_speedbreaker': {'apply': 'carbon_devrows_speedbreaker'},
    'gameplay.cheat_crew': {'apply': 'carbon_devrows_crew'},
    'world.carbon_minimap': {},
    'audio.carbon_surround': {'get': 'carbon_audio_surround_get', 'apply': 'carbon_audio_surround_set'},
    'graphics.look_preset': {'get': 'carbon_port_preset_get', 'apply': 'carbon_port_preset_apply'},
    'graphics.carbon_coat': {'apply': 'carbon_envcube_apply'},
    'graphics.carbon_materials': {},
    'graphics.carbon_ao': {'apply': 'carbon_ao_set'},
    'graphics.carbon_envcube': {'apply': 'carbon_envcube_apply'},
    'graphics.carbon_reflect_hdr': {'apply': 'carbon_envcube_apply'},
    'graphics.daynight': {},
    'graphics.daynight_mode': {},
    'graphics.daynight_hour': {},
    'audio.carbon_limiter': {'apply': 'private_carbon_limiter_set'},
    'audio.carbon_pos_layout': {},
    'controls.adaptive_triggers': {'apply': 'padfx_set_triggers'},
}
SETTINGS_PROVIDERS = {
    'carbon_envcube_apply': 'carbon_envcube.m',
    'carbon_ao_set': 'carbon_ao.h',
    'private_carbon_limiter_set': 'private_carbon_audio_limiter.h',
    'carbon_audio_surround_set': 'carbon_audio_output.c',
    'carbon_audio_surround_get': 'carbon_audio_output.c',
    'padfx_set_triggers': 'carbon_padfx.c',
    'carbon_devrows_crew': 'carbon_devrows.c',
    'carbon_devrows_nitrous': 'carbon_devrows.c',
    'carbon_devrows_speedbreaker': 'carbon_devrows.c',
    'carbon_port_preset_get': 'carbon_port_settings.h',
    'carbon_port_preset_apply': 'carbon_port_settings.h',
}
SETTINGS_FIXTURE = """
void portmenu_status(const char *fmt, ...) { (void)fmt; }
void carbon_envcube_apply(int v) { (void)v; }
void carbon_ao_set(int v) { (void)v; }
void private_carbon_limiter_set(int v) { (void)v; }
void carbon_audio_surround_set(int v) { (void)v; }
int carbon_audio_surround_get(void) { return 1; }
void carbon_audio_output_frame(void) {}
void padfx_set_triggers(int v) { (void)v; }
#include "carbon_devrows.c"
int settings_look_state(void) { return PRESET_PORT; }
int settings_look_apply(int value) { (void)value; return 0; }
"""

# Original initialization fragment, pinned independently of git/history or the
# production header. There was no port-controls registration in this body.
ORIGINAL_INIT = '''void private_settings_init(void) {
    for (unsigned i=0; i<sizeof private_rows/sizeof *private_rows; ++i) settings_add(&private_rows[i]);
#include "carbon_pad_layout_settings.h"
#include "game_display_settings.h"
#include "game_pacing_settings.h"
#include "game_tone_settings.h"
#include "game_overlay_settings.h"
    private_basic_rows_init();
    private_report_settings_init();
    carbon_unlock_settings_init();
}
'''
ORIGINAL_SHA256 = '98b570b0bca859ddd3d98ef81678058cec259ed3866ae11f51b1d415642b33e5'


# Pre-fix diagnostic readback and input paths; no history dependency.
ORIGINAL_DUMP = r'''void settings_dump(const char *path) {
    FILE *f = fopen(path, "w");
    if (!f) return;
    Setting *rows[128];
    for (int c = 0; c < SET_NCATEGORIES; ++c) {
        int n = settings_rows(c, rows, 128);
        for (int i = 0; i < n; ++i) {
            char v[64];
            fprintf(f, "%s\t%s\t%s\n", settings_category_names[c], rows[i]->id, has_value(rows[i]) ? settings_value_name(rows[i], rows[i]->value, v, sizeof v) : "");
        }
    }
    for (int i = 0; i < nall; ++i) if (all[i]->hidden) {
        char v[64];
        fprintf(f, "%s\t%s\t%s\n", x360_unavailable(all[i]) ? "hidden" : "preset", all[i]->id,
            x360_unavailable(all[i]) ? "(needs X360 files not in roots.txt; PC in effect)" : settings_value_name(all[i], all[i]->value, v, sizeof v));
    }
    fclose(f);
}'''
ORIGINAL_DUMP_SHA256 = '55cdf0d4fd208a2dfe8736a5e83e8602696ab054d364f8b451b2616ded332e96'

ORIGINAL_CHANGE = '''static void change(Setting *s, int d) {
    if (!s || s->locked) return;
    if (s->type == SET_CHOICE || s->type == SET_TOGGLE) {
        int n = s->type == SET_TOGGLE && !s->choices ? 2 : s->nchoices;
        int v = !strcmp(s->id, "graphics.look_preset") ? settings_look_choice() : value_of(s);
        if (settings_set(s, (v + d + n) % n)) changed(s);
    } else if (s->type == SET_SLIDER) {
        if (settings_set(s, value_of(s) + d * (s->step > 0 ? s->step : 1))) changed(s);
    }
}'''
ORIGINAL_CHANGE_SHA256 = '7d309cbc14ef99656ded0e3e4732b9747cf31a5b31609c2cb47e2b21716f95fa'


def function(path, signature):
    source = (ROOT / path).read_text()
    start = source.index(signature)
    brace = source.index('{', start)
    depth = 1
    end = brace + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]


def selectors():
    """Compile the expressions the production paths actually execute.

    Shader, audio-device and controller transports are stubbed here; their
    dedicated tests cover the backend behavior. Boolean, number, mode and
    cached selectors are copied without replacements.
    """
    coat = function('recomp/private_runtime/carbon_coat.h', 'uint32_t *carbon_coat_shader(')
    ao = function('recomp/private_runtime/carbon_ao.h', 'static void carbon_ao_init(')
    limiter = function('recomp/private_runtime/carbon_audio_limiter.h', 'static int private_carbon_limiter_enabled(')
    pos = function('recomp/private_runtime/carbon_posaudio.h', 'static int carbon_posaudio_enabled(')
    number = function('recomp/private_runtime/carbon_daynight.h', 'static double carbon_dn_number(')
    cube = function('recomp/private_runtime/carbon_envcube.h', 'void carbon_envcube_allocate(')
    refl = cube[cube.index('    value=getenv("NFS_CARBON_REFLECT_HDR");'):cube.index('    value=getenv("NFS_CARBON_COAT")')]
    cube = cube[cube.index('{') + 1:cube.index('    /* Off')]
    day = function('recomp/private_runtime/carbon_daynight.h', 'static int carbon_dn_on(')
    day = day[day.index('{') + 1:day.index('    carbon_dn_wrap =')]
    clock = (PRIVATE / 'carbon_daynight.h').read_text()
    mode = clock[clock.index('    const char *mode_text ='):clock.index('    double hour = carbon_dn_number(')]
    trigger = '\n'.join(function('recomp/private_runtime/carbon_padfx.c', sig) for sig in
        ('static int fx_switch(', 'static int fx_triggers_on(', 'void padfx_set_triggers('))
    ao += '\n' + function('recomp/private_runtime/carbon_ao.h', 'void carbon_ao_set(')
    limiter += '\n' + function('recomp/private_runtime/carbon_audio_limiter.h', 'void private_carbon_limiter_set(')
    return '''#include <stdatomic.h>
#include <pthread.h>
#include "setting_bool.h"
static _Atomic int carbon_ao_on;
static int carbon_coat_materials, carbon_envcube_on, carbon_envcube_float, carbon_envcube_hdr;
static int carbon_dn_configured, carbon_dn_enabled;
static _Atomic int private_audio_enabled = -1;
static _Atomic unsigned private_audio_generation;
static pthread_mutex_t private_audio_control_mutex = PTHREAD_MUTEX_INITIALIZER;
static _Atomic int fx_triggers = -1;
static pthread_mutex_t fx_mu = PTHREAD_MUTEX_INITIALIZER;
static int carbon_padfx_fake(void) { return 0; }
static void padfx_stop(void) {}
static void ds_set_peak_limiter(int on) { (void)on; }
static void carbon_audio_surround_set(int on) { (void)on; }
static int carbon_audio_surround_get(void) { return 1; }
static void carbon_envcube_apply(int on) { (void)on; }
enum { DAYNIGHT_GAME, DAYNIGHT_CYCLE, DAYNIGHT_FIXED };
typedef int DaynightMode;
static uint32_t *carbon_coat_variant(const uint32_t *p,uint32_t n,uint32_t *out) {
    (void)p; (void)n; (void)out; static uint32_t token; return &token;
}
''' + '\n'.join([coat, ao, limiter, pos, number, trigger]) + '''
static int port_cube_selector(void) {''' + cube + '''return carbon_envcube_on; }
static int port_reflect_selector(void) {const char *value;''' + refl + '''return carbon_envcube_float; }
static int port_daynight_selector(void) {''' + day + '''return carbon_dn_enabled; }
static int port_clock_mode(void) {''' + mode + '''return mode; }
'''


def menu_fixture(body):
    return """
static int menu_changes;
static int value_of(const Setting *s) { return s->get ? s->get() : s->value; }
static void changed(Setting *s) { (void)s; ++menu_changes; }
""" + body + "\n"


def main():
    assert hashlib.sha256(ORIGINAL_DUMP.encode()).hexdigest() == ORIGINAL_DUMP_SHA256
    assert hashlib.sha256(ORIGINAL_CHANGE.encode()).hexdigest() == ORIGINAL_CHANGE_SHA256
    assert hashlib.sha256(ORIGINAL_INIT.encode()).hexdigest() == ORIGINAL_SHA256
    settings = (PRIVATE / 'game_settings.h').read_text()
    init = settings[settings.index('void private_settings_init(void)'):]
    # Rows registered after this one by later features are checked by their own tests.
    for call in ('carbon_port_settings_init', 'carbon_addons_gameplay_init', 'carbon_addons_language_init', 'carbon_addons_cards_init', 'carbon_addons_host_settings_init'):
        assert init.count(f'    {call}();\n') == 1, call
        init = init.replace(f'    {call}();\n', '')
    assert init == ORIGINAL_INIT
    assert settings.count('#include "carbon_port_settings.h"') == 1
    manifest = load_manifest()
    assert 'carbon_port_settings.h' in manifest['targets']['private']['staged_sources']
    header = (PRIVATE / 'carbon_port_settings.h').read_text()
    assert 'NFS_SIMHZ' not in header
    # Extra imported lighting and diagnostic overlay switches remain outside this menu.
    for switch in ('NFS_DAYNIGHT_TREES', 'NFS_DAYNIGHT_GRADE', 'NFS_CARBON_TRACK_OVERLAY'):
        assert switch not in header
    env = {k: v for k, v in os.environ.items() if not k.startswith(('NFS_', 'BOOT_'))}
    with tempfile.TemporaryDirectory(prefix='port-settings-') as name:
        td = Path(name)
        selector_source = selectors()
        menu_source = function('runtime/portmenu.m', 'static void change(')
        (td / 'carbon_port_selectors.h').write_text(selector_source + menu_fixture(menu_source))
        (td / 'carbon_port_settings.h').write_text(header)
        binary = td / 'test'
        command = ['clang', '-std=c11', '-D_POSIX_C_SOURCE=200809L', '-DNFS_GAME=2',
                   '-Wall', '-Wextra', '-Werror', '-I', str(td), '-I', str(PRIVATE),
                   '-I', str(ROOT / 'runtime'), '-I', str(ROOT / 'recomp'),
                   str(ROOT / 'runtime/settings_look_test.c'), str(ROOT / 'runtime/settings.c'),
                   '-o', str(binary)]

        def build(extra=()):
            result = subprocess.run(command + list(extra), capture_output=True, text=True)
            assert result.returncode == 0, result.stderr[-5000:]

        runs = 0

        def run(store, op, *args, fails=False, overrides=None):
            nonlocal runs
            result = subprocess.run([str(binary), str(td / store), op, *map(str, args)],
                                    capture_output=True, text=True, env=dict(env, **(overrides or {})))
            runs += 1
            assert result.returncode == int(fails), result.stdout + result.stderr
            return result

        build()
        run('fresh', 'defaults')
        for start in (0, 1):
            for index in (0,1,2,3,4,6,7,8,10):
                value=(19 if index==7 else 2 if index==6 else 1) if start else (12 if index==7 else 0)
                run(f'live-{start}', 'save', index, value)
            run(f'live-{start}', 'live', start)
        print('live setters: starts=2 transitions=54 consumer failures=0')
        for name, before, after in (
            ('coat', '.env="NFS_CARBON_COAT", .live_env=1, .apply=carbon_envcube_apply', '.env="NFS_CARBON_COAT", .restart=1'),
            ('materials', '.env="NFS_CARBON_MATERIALS", .live_env=1', '.env="NFS_CARBON_MATERIALS", .restart=1'),
            ('cube', '.env="NFS_CARBON_ENVCUBE", .live_env=1, .apply=carbon_envcube_apply', '.env="NFS_CARBON_ENVCUBE", .restart=1'),
            ('HDR', '.env="NFS_CARBON_REFLECT_HDR", .live_env=1, .apply=carbon_envcube_apply', '.env="NFS_CARBON_REFLECT_HDR", .restart=1'),
            ('AO', '.apply=carbon_ao_set', '.restart=1'),
            ('mode', '.env="NFS_DAYNIGHT_MODE", .live_env=1', '.env="NFS_DAYNIGHT_MODE", .restart=1'),
            ('hour', '.env="NFS_DAYNIGHT_HOUR", .live_env=1', '.env="NFS_DAYNIGHT_HOUR", .restart=1'),
            ('limiter', '.apply=private_carbon_limiter_set', '.restart=1'),
            ('triggers', '.apply=padfx_set_triggers', '.restart=1'),
        ):
            assert before in header
            (td/'carbon_port_settings.h').write_text(header.replace(before,after))
            build()
            bad=run('broken-'+name, 'live', 0, fails=True)
            print('old '+name+' wiring: consumer failures='+str(bad.stderr.count('FAIL line='))+' exit=1; good=0')
        (td/'carbon_port_settings.h').write_text(header)
        build()
        # All legal values, including all 25 hours, each saved then reloaded by
        # an independent process that executes the production selector.
        values = [range(2)] * 6 + [range(3), range(25)] + [range(2)] * 3
        for index, choices in enumerate(values):
            for value in choices:
                store = f'row-{index}-{value}'
                run(store, 'save', index, value)
                run(store, 'verify', index, value)
                run(store, 'reset', index, value)
                run(store, 'verify', index, [1, 1, 0, 0, 1, 0, 0, 12, 1, 0, 1][index])
        for source in range(3):
            for target in range(3):
                if source == target:
                    continue
                store = f'preset-{source}-{target}'
                run(store, 'custom')
                run(store, 'preset', source)
                run(store, 'preset_verify', source)
                run(store, 'preset', target)
                run(store, 'preset_verify', target)
        run('reset-preset', 'custom')
        run('reset-preset', 'preset_reset')
        run('reset-preset', 'preset_verify', 0)
        run('locked', 'custom')
        run('locked', 'preset', 1)
        run('locked', 'locked', overrides={'NFS_CARBON_COAT': '1'})
        for source in range(3):
            for direction in (-1, 1):
                store = f'cycle-{source}-{direction}'
                run(store, 'custom')
                run(store, 'preset', source)
                run(store, 'preset_verify', source)
                run(store, 'cycle', source, direction)
        print(f'good: failures=0 fresh processes={runs} values=44 resets=44 preset transitions=6 cycles=6')

        # The original dump is the broken readback path: a fresh process has
        # cached UI index zero even with a saved PC/My picks choice.
        shared_path = str(ROOT / 'runtime/settings.c')
        shared = (ROOT / 'runtime/settings.c').read_text()
        dump = function('runtime/settings.c', 'void settings_dump(')
        (td / 'settings.c').write_text(shared.replace(dump, ORIGINAL_DUMP))
        command[command.index(shared_path)] = str(td / 'settings.c')
        build()
        for choice in (1, 2):
            store = f'old-dump-{choice}'
            run(store, 'custom')
            run(store, 'preset', choice)
            result = run(store, 'preset_verify', choice, fails=True)
            assert result.stderr.count('FAIL line=') == 1, result.stderr
        print('original loaded dump: wrong rows=2 exit=1 (good=0)')
        command[command.index(str(td / 'settings.c'))] = shared_path
        (td / 'carbon_port_selectors.h').write_text(selector_source + menu_fixture(ORIGINAL_CHANGE))
        build()
        run('old-left', 'custom')
        run('old-left', 'preset', 1)
        result = run('old-left', 'cycle', 1, -1, fails=True)
        assert result.stderr.count('FAIL line=') == 2, result.stderr
        print('original Left: value/event failures=2 exit=1 (good=0)')
        (td / 'carbon_port_selectors.h').write_text(selector_source + menu_fixture(menu_source))

        # Original initializer has no port-settings call. Execute that same
        # absence with the pinned initializer as its independent witness.
        build(['-DPORT_SETTINGS_ORIGINAL', '-Wno-unused-function'])
        result = run('original', 'defaults', fails=True)
        assert result.stderr.count('s!=NULL') == 11, result.stderr
        print('original registration: missing rows=11 exit=1 (good=0)')
        for mutant, before, after, row in (
            ('coat off-string', 'carbon_port_bool[] = {"0", "1"}', 'carbon_port_bool[] = {"off", "1"}', 0),
            ('AO numeric-zero', '.values=carbon_port_switch, .def=0, .env="NFS_CARBON_AO"',
             '.values=carbon_port_bool, .def=0, .env="NFS_CARBON_AO"', 2),  # On is the saved value now
        ):
            assert header.count(before) == 1
            (td / 'carbon_port_settings.h').write_text(header.replace(before, after))
            build()
            value = 1 if row == 2 else 0   # Off is AO's default, which stores no spelling to mis-encode
            result = run(mutant, 'save', row, value, fails=True)
            result = run(mutant, 'verify', row, value, fails=True)
            failures = result.stderr.count('FAIL line=')
            assert failures == (1 if row == 2 else 2), result.stderr
            print(f'{mutant}: restarted selector/encoding failures={failures} exit=1 (good=0)')
        (td / 'carbon_port_settings.h').write_text(header)
        shared = (ROOT / 'runtime/settings.c').read_text()
        start = shared.index('    int look_value = v;')
        end = shared.index('    if (v == current(s)', start)
        shared = shared[:start] + shared[end:]
        shared = shared.replace('look_value == settings_look_choice()', 'v == settings_look_choice()')
        (td / 'settings.c').write_text(shared)
        command[command.index(str(ROOT / 'runtime/settings.c'))] = str(td / 'settings.c')
        build()
        run('unmapped-enum', 'custom')
        run('unmapped-enum', 'preset', 1)
        result = run('unmapped-enum', 'locked', overrides={'NFS_CARBON_COAT': '1'}, fails=True)
        assert result.stderr.count('FAIL line=') == 3, result.stderr
        print('unmapped preset enum: restore failures=3 exit=1 (good=0)')
    print('PRIVATE PORT SETTINGS PASS')
    return 0


if __name__ == '__main__':
    sys.exit(main())
