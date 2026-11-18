"""Basic F10 rows: baseline 47 rows / VRR=-1; good 49 rows / VRR=0,1.
Removed registration: good exit=0 (49) / broken exit=1 (47 versus 49).
Removed include: compiler rejects the missing initializer. Shared restart body
under BOOT_BACKGROUND=1: two refusals, zero saves/confirmation/termination/state
changes. Selected callback closure has zero disabled dependencies. No game runs.
Restart game after the game's msvcr71 _exit (Carbon's WinMain ends there, not in ExitProcess):
production _exit(0) spawns 1 waiter, _exit(1) 0; the original host _exit spawns 0.
Feature dependencies: basic_rows.json picture_01.json port_settings.json (feature); carbon_devrows.c callbacks use their own fixture.
"""
from pathlib import Path
import ast
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = ROOT / 'recomp/private_runtime'
OUT = ROOT / 'recomp/out/carbon'
sys.path.insert(0, str(PRIVATE))
from layers import load_manifest, build_owned, check_audits, disabled_exports

# Independent contract consumed as literals by private_settings_test.py.
SETTINGS_ROWS = {
    'diag.restart_game': {'apply': 'app_restart_game'},
    'graphics.variable_refresh': {'apply': 'private_basic_presentation_apply'},
}
SETTINGS_PROVIDERS = {
    'app_restart_game': 'app.m',
    'private_basic_presentation_apply': 'game_basic_rows.h',
}
SETTINGS_FIXTURE = """
void app_restart_game(int value) { (void)value; }
void render_presentation_stats(RenderPresentation *out) { memset(out,0,sizeof *out); }
"""

EXPECTED_IDS = (
    'display.window', 'display.fullscreen', 'graphics.hdr_output',
    'graphics.hdr_status', 'diag.full_logging', 'diag.logs_open', 'diag.quit_game',
    'controls.pad_layout', 'controls.pad_layout_reason', 'graphics.antialiasing',
    'graphics.frame_rate_limit', 'display.overlay',
    'diag.restart_game', 'graphics.variable_refresh',
    'diag.h_report', 'diag.report_category', 'diag.report_note', 'diag.report_save', 'diag.report_open', 'gameplay.unlock_all',
    'gameplay.traffic_density', 'gameplay.cheat_nitrous', 'gameplay.cheat_speedbreaker',
    'gameplay.cheat_crew', 'world.carbon_minimap', 'audio.carbon_surround',
    'graphics.look_preset', 'graphics.carbon_coat', 'graphics.carbon_materials', 'graphics.carbon_ao',
    'graphics.carbon_envcube', 'graphics.carbon_reflect_hdr', 'graphics.daynight', 'graphics.daynight_mode', 'graphics.daynight_hour',
    'audio.carbon_limiter', 'audio.carbon_pos_layout', 'controls.adaptive_triggers',
    'gameplay.skip_movies', 'gameplay.heat', 'gameplay.no_catchup', 'gameplay.starting_bonus', 'gameplay.skip_prologue',
    'gameplay.cash_20000', 'gameplay.cash_50000', 'gameplay.cash_100000', 'gameplay.cash_amount', 'gameplay.language', 'gameplay.markers',
)


def selected_providers():
    manifest = load_manifest()
    audits = json.loads((OUT / 'layer_audits.json').read_text())
    check_audits(audits, manifest, manifest['targets']['private']['extra_sources'], require_complete=True)
    selected = {row['name']: row for unit in audits for row in unit['declarations']}
    disabled = {row['name'] for row in disabled_exports(manifest)}
    providers = dict(SETTINGS_PROVIDERS, render_presentation_stats='render_present.m')
    for name, owner in providers.items():
        assert name in selected and Path(selected[name]['source']).name == owner, (name, owner)
        pending, seen = [name], set()
        while pending:
            callee = pending.pop()
            if callee in seen:
                continue
            seen.add(callee)
            assert callee not in disabled, (name, callee)
            if callee in selected:
                pending.extend(selected[callee]['calls'] + selected[callee]['references'])
    symbols = subprocess.run(['nm', '-gU', str(OUT / 'boot_carbon')], capture_output=True, text=True, check=True).stdout
    for name in ('app_restart_game', 'render_presentation_stats'):
        assert re.search(r'\b_' + name + r'\b', symbols), name
    assert 'render_presentation_stats' in selected['private_basic_presentation_apply']['calls']
    feature = json.loads((PRIVATE / 'features/basic_rows.json').read_text())
    assert set(feature['sources']) == {'game_basic_rows.h'}
    assert feature['enabled_providers'] == []
    assert (OUT / 'runtime/game_basic_rows.h').read_bytes() == (PRIVATE / 'game_basic_rows.h').read_bytes()
    print('providers: restart + pacing callback + shared presenter selected; disabled dependencies=0')


def other_fixtures():
    text = ''
    for name in ('private_pad_layout_test.py', 'private_picture_02_test.py',
                 'private_picture_04_test.py', 'private_overlay_test.py', 'private_unlock_test.py', 'private_report_test.py'):
        for node in ast.parse((ROOT / 'recomp' / name).read_text()).body:
            if isinstance(node, ast.Assign) and any(isinstance(n, ast.Name) and n.id == 'SETTINGS_FIXTURE' for n in node.targets):
                text += ast.literal_eval(node.value) + '\n'
    for node in ast.parse((ROOT / 'recomp/private_addons_gameplay_test.py').read_text()).body:
        if isinstance(node, ast.Assign) and any(isinstance(n, ast.Name) and n.id == 'SETTINGS_FIXTURE' for n in node.targets):
            text += ast.literal_eval(node.value) + '\n'
    return text


HARNESS = r'''
#import <Foundation/Foundation.h>
#include <assert.h>
#include <stdarg.h>
#include "host.h"
#include "settings.h"
static int pref_writes, saves, confirmations, terminations, statuses, refreshes, observed_vrr;
static char status_text[128];
static char *restart_exe="fixture", *restart_args[]={"fixture",NULL}, *restart_vars[]={NULL};
static char **restart_argv=restart_args, **restart_env=restart_vars;
static int restart_requested, restart_clean=1, restart_guarded;
@interface BasicRowsApplication : NSObject
+ (void)terminate:(id)sender;
@end
@implementation BasicRowsApplication
+ (void)terminate:(id)sender { (void)sender; ++terminations; }
@end
#define NSApp BasicRowsApplication
static int prefs_save(void) { ++saves; return 1; }
static int confirm_twice(double *until, const char *what) { (void)until; (void)what; ++confirmations; return 1; }
void portmenu_status(const char *format, ...) {
    ++statuses; va_list args; va_start(args,format);
    vsnprintf(status_text,sizeof status_text,format,args); va_end(args);
}
/* PRODUCTION_RESTART */
/* Dedicated devrows and port-settings fixtures check these live callbacks. */
void carbon_envcube_apply(int v) { (void)v; }
void carbon_ao_set(int v) { (void)v; }
void carbon_audio_surround_set(int v) { (void)v; }
int carbon_audio_surround_get(void) { return 1; }
void private_carbon_limiter_set(int v) { (void)v; }
void padfx_set_triggers(int v) { (void)v; }
void carbon_devrows_crew(int v) { (void)v; }
void carbon_devrows_nitrous(int v) { (void)v; }
void carbon_devrows_speedbreaker(int v) { (void)v; }
#include "game_settings.h"
/* OTHER_FIXTURES */
int diag_on; const char *diag_dir;
void diag_event(const char *format, ...) { (void)format; }
void report_note(const char *format, ...) { (void)format; }
const char *app_pref(const char *key) { (void)key; return NULL; }
void app_pref_set(const char *key,const char *value) { (void)key; (void)value; ++pref_writes; }
void app_pref_batch_begin(void) { ++pref_writes; }
void app_pref_batch_end(void) { ++pref_writes; }
const char *userdata_dir(void) { return getenv("BOOT_USERDATA"); }
int user32_fullscreen(void) { return 0; }
void user32_toggle_fullscreen(void) { }
void user32_fullscreen_mode_changed(void) { }
void app_quit_game(int value) { (void)value; }
void portmenu_open_folder(const char *path) { (void)path; }
const char *log_dir(void) { return "fixture"; }
const char *render_hdr_output_status(void) { return "SDR fixture"; }
void render_presentation_stats(RenderPresentation *out) {
    ++refreshes; observed_vrr=settings_get("graphics.variable_refresh");
    memset(out,0,sizeof *out);
}
#define CHECK(v) do { if (!(v)) { fprintf(stderr,"BASIC ROWS CHECK line=%d: %s\n",__LINE__,#v); return 1; } } while(0)
int main(int argc, char **argv) {
    CHECK(argc==2); int expected_vrr=atoi(argv[1]);
    CHECK(settings_count()==0 && settings_get("graphics.variable_refresh")==-1);
    private_settings_init();
    printf("rows=%d expected=49\n",settings_count());
    CHECK(settings_count()==49);
    const char *expected[]={ /* EXPECTED_IDS */ };
    for(int i=0;i<48;++i) CHECK(!strcmp(settings_at(i)->id,expected[i]));
    settings_init();
    CHECK(settings_get("graphics.variable_refresh")==expected_vrr);
    Setting *vrr=settings_find("graphics.variable_refresh"), *restart=settings_find("diag.restart_game");
    CHECK(vrr->category==SET_DISPLAY && vrr->order==30 && vrr->type==SET_TOGGLE && vrr->def==0);
    CHECK(!strcmp(vrr->label,"Variable refresh pacing") && !strcmp(vrr->env,"NFS_VRR"));
    CHECK(vrr->apply==private_basic_presentation_apply && !vrr->get && !vrr->restart);
    CHECK(restart->category==SET_DISPLAY && restart->order==50 && restart->type==SET_ACTION);
    CHECK(!strcmp(restart->label,"Restart game") && restart->apply==app_restart_game);
    Setting *display[32]; int n=settings_rows(SET_DISPLAY,display,32), saw_vrr=0,saw_restart=0;
    for(int i=0;i<n;++i) {
        if(i) CHECK(display[i-1]->order<=display[i]->order);
        if(display[i]==vrr) ++saw_vrr;
        if(display[i]==restart) ++saw_restart;
    }
    CHECK(saw_vrr==1 && saw_restart==1);
    if(!vrr->locked) {
        CHECK(settings_set(vrr,1)==1 && settings_get(vrr->id)==1 && observed_vrr==1 && refreshes==1);
        CHECK(settings_set(vrr,0)==1 && settings_get(vrr->id)==0 && observed_vrr==0 && refreshes==2);
    } else {
        CHECK(settings_set(vrr,0)==0 && settings_get(vrr->id)==1);
        vrr->apply(1); CHECK(refreshes==1 && observed_vrr==1);
    }
    int before=pref_writes;
    CHECK(getenv("BOOT_BACKGROUND") && !getenv("BOOT_DEADLINE"));
    restart->apply(0); restart->apply(0);
    CHECK(!restart_requested && restart_clean==1 && !restart_guarded);
    CHECK(restart_argv==restart_args && restart_env==restart_vars && !strcmp(restart_exe,"fixture"));
    CHECK(!saves && !confirmations && !terminations && pref_writes==before);
    CHECK(statuses==2 && !strcmp(status_text,"Restart disabled in unattended runs."));
    printf("VRR=%d live_refreshes=%d restart_refusals=2 saves=0 confirmations=0 terminations=0\n",expected_vrr,refreshes);
    return 0;
}
'''


def compiled_rows(td):
    # Copy only the settings includes; mutants never alter the checkout or audits.
    for path in [*PRIVATE.glob('*.h'), *PRIVATE.glob('*.inc')]:
        shutil.copy2(path, td / path.name)
    # Add-on rows have independent integration and capture fixtures.
    (td / 'carbon_addons_host_settings.h').write_text('static void carbon_addons_host_settings_init(void) {}\n')
    app = (ROOT / 'runtime/app.m').read_text()
    restart = app[app.index('void app_restart_game(int unused) {'):app.index('\n@interface AppDelegate')]
    harness = HARNESS.replace('/* PRODUCTION_RESTART */', restart).replace('/* OTHER_FIXTURES */', other_fixtures())
    harness = harness.replace('/* EXPECTED_IDS */', ','.join(json.dumps(row) for row in EXPECTED_IDS))
    (td / 'rows.m').write_text(harness)
    command = ['clang', '-DNFS_GAME=2', '-I', str(td), '-I', str(PRIVATE),
               '-I', str(ROOT / 'runtime'), '-I', str(ROOT / 'recomp'),
               str(td / 'rows.m'), str(ROOT / 'runtime/settings.c'),
               '-framework', 'Foundation', '-Wl,-dead_strip', '-o', str(td / 'rows')]
    def build():
        return subprocess.run(command, capture_output=True, text=True)
    env = {k: v for k, v in os.environ.items() if not k.startswith(('NFS_', 'BOOT_'))}
    env.update(BOOT_BACKGROUND='1', BOOT_USERDATA=str(td))
    def run(value):
        current = dict(env)
        if value:
            current['NFS_VRR'] = '1'
        return subprocess.run([str(td / 'rows'), str(value)], env=current, capture_output=True, text=True)
    result = build()
    assert result.returncode == 0, result.stderr[-4000:]
    for value in (0, 1):
        result = run(value)
        assert result.returncode == 0, result.stdout + result.stderr
        assert result.stderr.count('boot: restart skipped (BOOT_DEADLINE/BOOT_BACKGROUND)') == 2
        print(result.stdout.strip())
    settings = td / 'game_settings.h'; original = settings.read_text()
    assert original.count('#include "game_basic_rows.h"') == 1
    assert original.count('    private_basic_rows_init();') == 1
    settings.write_text(original.replace('    private_basic_rows_init();', ''))
    result = build(); assert result.returncode == 0, result.stderr[-4000:]
    result = run(0)
    assert result.returncode == 1 and 'rows=47 expected=49' in result.stdout, result.stdout + result.stderr
    assert 'settings_count()==49' in result.stderr, result.stderr
    print('negative registration: good exit=0 rows=49 / broken exit=1 rows=47 expected=49')
    settings.write_text(original.replace('#include "game_basic_rows.h"', ''))
    result = build()
    assert result.returncode != 0 and 'private_basic_rows_init' in result.stderr, result.stderr[-4000:]
    print('negative include: good compiler exit=0 / broken compiler exit=1')


CRT_EXIT_HARNESS = r'''
#import <Cocoa/Cocoa.h>
#include <errno.h>
#include <fcntl.h>
#include <mach-o/dyld.h>
#include <spawn.h>
#include <sys/event.h>
#include <unistd.h>
extern char **environ;
static int app_bundled;
static int fixture_spawn(pid_t *pid, const char *path, const posix_spawn_file_actions_t *actions,
    const posix_spawnattr_t *attr, char *const *args, char *const *env) {
    (void)path; (void)actions; (void)attr; (void)env;
    printf("SPAWN %s %s\n", args[1], args[3]); fflush(stdout); *pid = 123; return 0;
}
#define posix_spawn fixture_spawn
/* APP_RESTART */
typedef struct Cpu Cpu;
static int crt_args[1];
#define IS(n) (!strcmp(fn, n))
#define A(i) crt_args[i]
static void diag_begin_exit(void) { }
static void crt_exit(Cpu *c, const char *fn) {
/* CRT_EXIT */
}
int main(int argc, char **argv) {
    if (argc != 2) return 2;
    restart_capture(argv);
    restart_requested = 1;          // the second press of Restart game
    crt_args[0] = atoi(argv[1]);
    crt_exit(NULL, "_exit");
    return 99;
}
'''


def crt_exit_restart(td, original=False):
    # The production msvcr71 _exit line and the production restart helper; the waiter spawn is the observable.
    app = (ROOT / 'runtime/app.m').read_text()
    helper = app[app.index('static char **restart_argv'):app.index('\nconst char *log_dir')]
    line = re.search(r'^    if \(IS\("_exit"\)\).*$', (PRIVATE / 'crt.c').read_text(), re.M).group(0)
    if original:
        line = '    if (IS("_exit")) _exit((int)A(0));'   # the line before the fix (host _exit: no atexit)
    (td / 'crt_exit.m').write_text(CRT_EXIT_HARNESS.replace('/* APP_RESTART */', helper).replace('/* CRT_EXIT */', line))
    subprocess.run(['clang', '-Wall', '-Werror', '-Wno-unused-function', '-fobjc-arc', str(td / 'crt_exit.m'),
                    '-framework', 'Cocoa', '-o', str(td / 'crt_exit')], check=True, capture_output=True)
    env = {k: v for k, v in os.environ.items() if k not in ('BOOT_DEADLINE', 'BOOT_BACKGROUND')}
    spawns = {}
    for code in (0, 1):
        out = subprocess.run([str(td / 'crt_exit'), str(code)], env=env, capture_output=True, text=True, timeout=20)
        assert out.returncode == code, (code, out.stdout, out.stderr)
        spawns[code] = out.stdout.count('SPAWN --port-restart-wait ')
    return spawns


def crt_exit_check(td):
    good = crt_exit_restart(td)
    assert good == {0: 1, 1: 0}, good
    broken = crt_exit_restart(td, original=True)
    assert broken == {0: 0, 1: 0}, broken
    print(f'restart after msvcr71 _exit: _exit(0) waiters={good[0]} _exit(1) waiters={good[1]}; '
          f'original host _exit(0) waiters={broken[0]}')


def main():
    if any(not (OUT / name).is_file() for name in ('boot_carbon', 'layer_audits.json', 'runtime_selection.json')):
        print('SKIP: build the Carbon runtime first')
        return 3
    if not build_owned(OUT):
        print('SKIP: private runtime link belongs to another checkout')
        return 3
    selected_providers()
    with tempfile.TemporaryDirectory(prefix='private-basic-rows-') as temp:
        compiled_rows(Path(temp))
        crt_exit_check(Path(temp))
    print('PRIVATE BASIC ROWS PASS: rows 47 -> 49; VRR -1 -> 0/1; unattended restart unchanged; restart after _exit(0) 0 -> 1 waiter')
    return 0


if __name__ == '__main__':
    sys.exit(main())
