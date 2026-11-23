"""Offline Carbon regressions for file_overlay.h, carbon_minimap.h, boot.c,
game_diagnostics.h, report.m, carbon_daynight.h, daynight.c and daynight_clock.c.
Stock projection u: old .3811, fixed .5000. A saved Atlas with both HUD
packs selects u=.3811 only after the settings load.
15-second idle watch: old 1 false hang, fixed 0; first frame clears idle.
Career Game/Cycle hours: old 9/9, fixed 15/9. Normal's directional term
at 05:59:59.964 / 06:00:00.036: old .5000/0, fixed .000007/0.
"""
from pathlib import Path
import os
import subprocess
import tempfile

RECOMP = Path(__file__).resolve().parent
RUNTIME = RECOMP.parent / 'runtime'
PRIVATE = RECOMP / 'private_runtime'


def fragment(path, signature, end='\n}'):
    source = path.read_text()
    start = source.index(signature)
    stop = source.index(end, start)
    return source[start:stop + len(end)]


def run_case(tmp, name, source, args=(), extra_sources=(), expected=0, overlay=None):
    c_file = tmp / (name + '.c')
    c_file.write_text(source)
    exe = tmp / name
    build = subprocess.run(['clang', '-std=c11', '-D_DARWIN_C_SOURCE', '-DNFS_GAME=2', '-O1',
                            '-I', str(PRIVATE), '-I', str(RUNTIME), '-I', str(RECOMP),
                            str(c_file), *map(str, extra_sources), '-o', str(exe)],
                           capture_output=True, text=True)
    assert build.returncode == 0, build.stderr[-4000:]
    env = {key: val for key, val in os.environ.items() if not key.startswith(('NFS_', 'BOOT_'))}
    if overlay is not None:
        env['NFS_CARBON_TRACK_OVERLAY'] = str(overlay)
    result = subprocess.run([str(exe), *map(str, args)], env=env, capture_output=True, text=True)
    print(name + ': ' + result.stdout.strip(), flush=True)
    assert result.returncode == expected, (result.returncode, result.stderr[-2000:])


ATLAS_PRE = r'''
#include "host.h"
#include "game_select.h"
#include <errno.h>
#include <fcntl.h>
#include <math.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>
uint8_t *G;
int diag_on;
const char *game_dir;
uint64_t host_ticks(void) { return 0; }
uint64_t diag_current_frame(void) { return 0; }
void diag_event(const char *fmt, ...) { (void)fmt; }
int private_carbon_player_position(float *p) { (void)p; return 0; }
#include "carbon_minimap.h"
static int samples;
static double u;
static void project(Cpu *c) {
    (void)c;
    u = (700.0 - MF32(0x009D5F10u)) * MF32(0x009D5F0Cu);
    ++samples;
}
const char *app_start(int argc, char **argv) { return argc > 1 ? argv[1] : NULL; }
static void private_settings_init(void) {}
void settings_init(void) { setenv("NFS_CARBON_MINIMAP", "atlas", 1); }
static void private_world_init(void) {}
'''
ATLAS_END = r'''
    G = calloc(1, 0xA80000);
    M32(0x00A7A1A8u) = 5000;
    M32(0x009D5F10u) = 0xc5e42000;
    M32(0x009D5F08u) = 0xc4fa0000;
    M32(0x009D5F0Cu) = 0x3883126f;
    Cpu c = {0};
    carbon_minimap_icons(&c, project);
    double want = atof(argv[2]);
    printf("decoded point u=%.4f expected=%.4f overlay=%u\n", u, want, private_track_enabled);
    free(G);
    return samples != 1 || fabs(u - want) > .00005 || private_track_enabled != atoi(argv[3]);
}
'''


def atlas(tmp):
    startup = fragment(RUNTIME / 'boot.c', 'int main(int argc, char **argv) {', '    void car_grip_init(void);')
    startup = startup.removesuffix('    void car_grip_init(void);')
    assert startup.index('\n    settings_init();') < startup.index('\n    private_track_overlay_init();')
    scan = (PRIVATE / 'file_overlay.h').read_text().split('/* resolve()', 1)[0]
    no_validation = scan[:scan.index('    /* Atlas is built')] + '}\n'
    old_start = startup.replace('    private_track_overlay_init();\n', '')
    old_start = old_start.replace('int main(int argc, char **argv) {', 'int main(int argc, char **argv) {\n    private_track_overlay_init();')
    root = tmp / 'overlay'
    for name in ('TRACKS/L5RA.BUN', 'TRACKS/STREAML5RA.BUN',
                 'TRACKS/L5RA/MINI_MAP_CASINOTOWN_LOCKED.bin',
                 'TRACKS/L5RA/MINI_MAP_CASINOTOWN_UNLOCKED.bin',
                 'TRACKS/L5RA/TrackMaps.bin'):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'fixture')
    cases = (
        ('atlas-stock', scan, startup, .5000, 0, 0, None),
        ('old-atlas-stock', no_validation, startup, .5000, 0, 1, None),
        ('atlas-saved', scan, startup, .3811, 451, 0, root),
        ('old-atlas-order', scan, old_start, .3811, 451, 1, root),
    )
    for name, reader, boot, u, mask, expected, overlay in cases:
        run_case(tmp, name, ATLAS_PRE + reader + boot + ATLAS_END, (root, u, mask), expected=expected, overlay=overlay)
    (root / 'TRACKS/L5RA/MINI_MAP_CASINOTOWN_UNLOCKED.bin').write_bytes(b'')
    run_case(tmp, 'atlas-incomplete', ATLAS_PRE + scan + startup + ATLAS_END, (root, .5000, 3), overlay=root)


IDLE_PRE = r'''
#include "game_select.h"
#include <pthread.h>
#include <setjmp.h>
#include <stdint.h>
#include <stdio.h>
static int diag_on, idle_now, exiting, have_game_thread, pause_hangs, hangs, elapsed, resumed_idle;
static uint64_t frame_now, last_frame_ns;
static pthread_t game_thread;
static jmp_buf finished;
uint64_t host_ticks(void) { return (1ull + elapsed) * 1000000000ull; }
void diag_event(const char *fmt, ...) { (void)fmt; }
static void private_mix_frame(uint64_t frame) { (void)frame; }
void carbon_unlock_frame(void) {}
void carbon_devrows_frame(void) {}
void carbon_addons_gameplay_frame(void) {}
static void diag_report(const char *file, const char *why) { (void)file; (void)why; ++hangs; }
'''
IDLE_END = r'''
int main(int argc, char **argv) {
    (void)argv;
    diag_on = argc > 1;
    diag_frame(1, 0);
    diag_idle(1);
    if (!setjmp(finished)) watchdog(NULL);
    printf("15-second pause hangs=%d resumed idle=%d later genuine hangs=%d\n", pause_hangs, resumed_idle, hangs-pause_hangs);
    return pause_hangs != 0 || resumed_idle != 0 || hangs-pause_hangs != 1;
}
'''


def idle(tmp):
    source = PRIVATE / 'game_diagnostics.h'
    state = fragment(source, 'void diag_idle(int idle)', '\n}\n\n// Scripted').removesuffix('\n\n// Scripted')
    frame = fragment(source, 'void diag_frame(uint64_t frame')
    now = 'uint64_t diag_current_frame(void) { return frame_now; }\n'
    fake_sleep = r'''
static void fake_sleep(int seconds) {
    elapsed += seconds;
    if (elapsed == 16) {
        pause_hangs = hangs;
        diag_frame(2, 0);
        resumed_idle = diag_is_idle();
    }
    if (elapsed == 32) longjmp(finished, 1);
}
'''
    watchdog = fragment(RUNTIME / 'report.m', 'static void *watchdog(').replace('sleep(1);', 'fake_sleep(1);')
    fixed = IDLE_PRE + state + frame + now + fake_sleep + watchdog + IDLE_END
    for args in ((), ('full',)):
        run_case(tmp, 'focus-pause' + (('-' + args[0]) if args else ''), fixed, args)
    run_case(tmp, 'old-focus-pause', fixed.replace('if (idle == __atomic_load_n', 'if (!diag_on || idle == __atomic_load_n'), expected=1)
    sticky = fixed.replace('    diag_idle(0);\n', '').replace('    if (!diag_on) return;', '    if (!diag_on) return;\n    diag_idle(0);')
    run_case(tmp, 'old-focus-resume', sticky, expected=1)


DAYLIGHT = r'''
#include "host.h"
#include <assert.h>
#include <stdlib.h>
#include <string.h>
uint8_t *G;
int diag_on;
uint64_t host_ticks(void) { return 0; }
uint64_t diag_current_frame(void) { return 0; }
void diag_event(const char *fmt, ...) { (void)fmt; }
static float uploaded[3][4];
uint32_t call_guest(Cpu *c, uint32_t fn, int n, const uint32_t *args) {
    (void)c;
    assert(fn == 0x123456 && n == 4 && args[1] == 240 && args[3] == 3);
    memcpy(uploaded, G + args[2], sizeof uploaded);
    return 0;
}
#include "daylight.inc"
static void retail(Cpu *c) { (void)c; }
static double race_hour(Cpu *c, const char *mode) {
    carbon_dn_policy = (DaynightClock){0};
    setenv("NFS_DAYNIGHT_MODE", mode, 1);
    M32(0x406a14) = 0;
    carbon_daynight_advance(c, retail);
    carbon_dn_write(c->ecx+8,.725f); /* Authored phase is 15h. */
    M32(0x406a14) = 1;
    carbon_daynight_advance(c, retail);
    return carbon_dn_clock.hour;
}
static float normal_term(Cpu *c, double hour, float nx) {
    carbon_dn_fixed = 1;
    carbon_dn_fixed_hour = hour;
    carbon_daynight_advance(c, retail);
    carbon_daynight_blend(c, retail);
    carbon_dn_constants(c);
    /* Normalize the weather diffuse so only the directional weight is measured. */
    return fmaxf(0,nx*uploaded[0][0]) * (1-uploaded[1][3]) *
           uploaded[1][0] / carbon_dn_clock.record.diffuse[0];
}
int main(int argc, char **argv) {
    (void)argc;
    G = calloc(1, 1u<<24);
    setenv("NFS_DAYNIGHT", "on", 1);
    setenv("NFS_TEST_DAYNIGHT_START", "9", 1);
    Cpu c = {.esp=0x9000,.ecx=0x200000};
    M32(0xA99BBC)=6; M32(0xA98284)=0x400000; M32(0x406a18)=3; M32(0x406a1c)=0x500000;
    M32(0xAB0ABC)=0x3000; M32(0x3000)=0x4000; M32(0x4000+94*4)=0x123456;
    carbon_dn_write(c.ecx+0x20, 1);
    int fail;
    if (!strcmp(argv[1],"career")) {
        double game = race_hour(&c,"game"), cycle = race_hour(&c,"cycle");
        M32(0x406a18)=2;
        double quick = race_hour(&c,"game");
        printf("career clock Game=%.4f Cycle=%.4f Quick Race Game=%.4f\n",game,cycle,quick);
        fail = fabs(game-15) > 1e-6 || cycle != 9 || quick != 9;
    } else {
        float dawn_before = normal_term(&c, 5.99999, 1), dawn_after = normal_term(&c, 6.00001, 1);
        float dusk_before = normal_term(&c, 17.99999, 1), dusk_after = normal_term(&c, 18.00001, 1);
        printf("normal term dawn %.6f -> %.6f dusk %.6f -> %.6f\n",dawn_before,dawn_after,dusk_before,dusk_after);
        fail = !isfinite(dawn_before + dawn_after + dusk_before + dusk_after) ||
               fabsf(dawn_before-dawn_after) > .00002f || fabsf(dusk_before-dusk_after) > .00002f;
    }
    free(G);
    return fail;
}
'''


def daylight(tmp):
    source = (PRIVATE / 'carbon_daynight.h').read_text()
    inputs = (RUNTIME / 'daynight.c', RUNTIME / 'daynight_clock.c')
    old_career = source.replace('    input.career = race && M32(race+0x6a18) == 3 ? 2 : 0;\n', '')
    old_light = source.replace('carbon_dn_clock.record.diffuse[k] * carbon_dn_clock.weight', 'carbon_dn_clock.record.diffuse[k]')
    for name, text, case, expected in (
        ('career-clock', source, 'career', 0),
        ('old-career-clock', old_career, 'career', 1),
        ('horizon', source, 'horizon', 0),
        ('old-horizon', old_light, 'horizon', 1),
    ):
        assert not expected or text != source
        (tmp / 'daylight.inc').write_text(text)
        run_case(tmp, name, DAYLIGHT, (case,), inputs, expected)


if __name__ == '__main__':
    with tempfile.TemporaryDirectory(prefix='private-carbon-audit-') as folder:
        tmp = Path(folder)
        atlas(tmp)
        idle(tmp)
        daylight(tmp)
