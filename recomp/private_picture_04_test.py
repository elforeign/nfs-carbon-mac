"""Native clock/hold and deterministic absolute-deadline fixtures, no game/GPU.

20-second 30/60/120/uncapped(240) fixtures: 1200/1200/1200/1200 units
(one-unit floating-point boundary tolerance); minimum-one mutant gives
1200/1200/2400/4800 and fails. Held 10 seconds: zero units; resumed one
second: 59 units (native carry boundary), close-menu catch-up zero. Sticky-hold mutant resumes zero
units and fails. Startup without an apply callback follows the loaded row;
detached startup-value mutant exit=1. Good exit=0; three native mutants exit=1.
AA diagnostic polls: disabled=0, enabled=1; removed-poll mutant exit=1.
SMS sound restoration: old code/mutant leaves 34 (one sound call), fixed code
restores 32 (two calls); genuine native-pause overlap retains its sound bit.
Held LOOK_AB variants: zero ticks; missing-hold mutant 59 ticks, rejected.
Translated originals and their constant bytes are pinned independently of
the implementation registry. Native pause ownership, wraparound, x87 carry,
register/stack parity and cap Off/change/stall/GIL ordering are covered.
The native long-frame timestep clamp is retained, independently of host pacing.
Exit 3 without Carbon outputs. Dependencies: game_menu_hold.h,
game_pacing_settings.h, game_picture_present.h, carbon_picture_clock.c,
features/picture_04.json and hooks/picture_04.json.
"""
from pathlib import Path
import hashlib
import json
import re
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
PRIVATE = HERE / 'private_runtime'
SETTINGS_ROWS = {'graphics.frame_rate_limit': {'apply': 'carbon_frame_limit_apply'}}
SETTINGS_PROVIDERS = {'carbon_frame_limit_apply': 'carbon_picture_clock.c'}
SETTINGS_FIXTURE = 'static int is_open, fixture_limit; int *carbon_frame_limit_choice=&fixture_limit; void carbon_frame_limit_apply(int v) { (void)v; }'
FRAGMENTS = {
    '006AB7A0': 'b229abe81194391bd8cdccc17a83ae5c0074cbb7928010583de97c95c220e3bf',
    '006B4CB0': 'b2f8b163a9000b3665bac5762f93da4042edafa734403934538f1a55532fe5aa',
    '0087EAC0': '613c584ed1cb82b7014a6eca36763dae6aec8f78e3feb2d21d5d02ee0a30312c',
}


def original(address):
    for path in (HERE / 'out/carbon-base').glob('NFSC_*.c'):
        source = path.read_text()
        match = re.search(r'void (?:f_|carbon_orig_)' + address + r'\(Cpu [^)]*\)\s*\{', source)
        if match:
            fragment = source[match.start():source.index('\n}', match.end()) + 2]
            fragment = re.sub(r'void (?:f_|carbon_orig_)' + address,
                              'void native_' + address, fragment, count=1)
            assert hashlib.sha256(fragment.encode()).hexdigest() == FRAGMENTS[address], address
            return fragment
    raise AssertionError('missing original ' + address)


HARNESS = r'''
#include "host.h"
#include "settings.h"
#include <stdlib.h>
#include <math.h>
uint8_t *G;
int diag_on;
int carbon_simrate_enabled(void) { return 0; }
int carbon_sim_hz(void) { return 60; }
void diag_event(const char *fmt,...) { (void)fmt; }
void diag_warp_pass(Cpu *c) { (void)c; }
static int is_open, sound_calls;
static uint64_t fake_now=1000000000ull, waited;
static int released, waits;
static unsigned clock_reads, limit_queries;
uint64_t host_ticks(void) { ++clock_reads; return fake_now; }
PerfFrame perf_frames[PERF_RING]; volatile uint64_t perf_nframes;   /* carbon_fe_probe.h, never reached with diag off */
void gil_release(void) { if(released) abort(); released=1; }
void gil_acquire(void) { if(!released) abort(); released=0; }
static double limit_ms;
double render_loop_limit_ms(void) { ++limit_queries; return limit_ms; }
#define mach_wait_until fixture_wait
#include "clock.c"
#undef mach_wait_until
void osk_pass(Cpu *c) { (void)c; }
#include "hold.inc"
static Setting *registered_limit;
void settings_add(Setting *s) { registered_limit=s; }
static void register_limit(void) {
#include "pacing.inc"
}
#define CHECK(x) do { if(!(x)) { fprintf(stderr,"CLOCK CHECK %d: %s\n",__LINE__,#x); exit(1); } } while(0)
kern_return_t fixture_wait(uint64_t when) {
    CHECK(released); waited=when; ++waits;
    /* Test interrupted waits retry the identical deadline. */
    if(waits==1)return KERN_ABORTED;
    mach_timebase_info_data_t tb; mach_timebase_info(&tb);
    fake_now=when*tb.numer/tb.denom; return KERN_SUCCESS;
}
uint32_t call_guest(Cpu *c,uint32_t fn,int n,const uint32_t *a) {
    CHECK(fn==0x50C370 && n==2 && a[1]==1); ++sound_calls;
    if(a[0])M32(0xA8BAE4)|=2; else M32(0xA8BAE4)&=~2u;
    memset(c,0x5A,sizeof *c); return 0;
}
void f_007AA370(Cpu *c) { c->eax=0;c->esp+=4; }
void f_006B3B30(Cpu *c) { (void)c; abort(); }
void f_006B38B0(Cpu *c) { (void)c; abort(); }
void native_0087EAC0(Cpu *c);
void f_0087EAC0(Cpu *c) { native_0087EAC0(c); }
ORIGINALS
static int presentations, yields;
static unsigned aa_polls;
int aa_game_get(void) { ++aa_polls;return 0; }
static void present(void) { ++presentations; }
void gil_yield(Cpu *c) { (void)c; ++yields; }
void carbon_lan_menu_tick(Cpu *c) { (void)c; }
#define D3D_OK 0
static int device_present(Cpu *c)
#include "present.inc"
static Cpu cpu(void) {
    Cpu c={0};c.esp=0x80000;c.cw=0x37f;c.ebx=17;c.esi=29;c.edi=31;c.ebp=37;return c;
}
static void reset(void) {
    memset(G+0xA62000,0,0x100000);
    CONSTANTS
    M32(0xA99BBC)=6; M32(0xB4CFE0)=0x100000;M32(0x100024)=3;
    MF32(0xA62EF8)=8;M32(0xA62EE4)=1;is_open=0;
}
static void advance(float dt) {
    Cpu c=cpu(); MF32(0xA99A5C)=dt;
    carbon_advance_real_time(&c,native_006AB7A0);
    CHECK(c.esp==0x80004 && c.ebx==17 && c.esi==29 && c.edi==31 && c.ebp==37 && c.top==0);
}
static void prepare(float dt) {
    Cpu c=cpu();MF32(c.esp+4)=dt;
    carbon_prepare_real_timestep(&c,native_006B4CB0);
    CHECK(c.esp==0x80004 && c.ebx==17 && c.esi==29 && c.edi==31 && c.ebp==37 && c.top==0);
}
int main(void) {
    G=calloc(1,0xC00000);CHECK(G);
    const int rates[]={30,60,120,240};
    int rates_ok=1;
    for(unsigned k=0;k<4;k++) {
        reset();int hz=rates[k];
        for(int i=0;i<20*hz;i++)advance(1.0f/hz);
        printf("rate=%d real=%u timer=%u loops=%u\n",hz,M32(0xA62EE8),M32(0xA99C60),M32(0xA996F0));
        rates_ok &= abs((int)M32(0xA62EE8)-1200)<=1;CHECK(M32(0xA996F0)==20u*hz);
    }
    CHECK(rates_ok);
    /* Same native state/register result except the three intentionally repaired counters. */
    reset();MF32(0xA99A5C)=1.0f/240;Cpu a=cpu(),b=a;
    native_006AB7A0(&a);float carry=MF32(0xA996E8);uint32_t timer=M32(0xA99C60);
    reset();MF32(0xA99A5C)=1.0f/240;carbon_advance_real_time(&b,native_006AB7A0);
    CHECK(!memcmp(&a,&b,sizeof a));CHECK(MF32(0xA996E8)==carry && M32(0xA99C60)==timer);
    reset();M32(0xA62EE8)=0xFFFFFFFFu;advance(0);CHECK(M32(0xA62EE8)==0xFFFFFFFFu);
    advance(1.0f/60);CHECK(M32(0xA62EE8)==0);
    reset();prepare(2.0f);CHECK(MF32(0xA99A5C)>0.13f && MF32(0xA99A5C)<0.14f);
    reset();is_open=1;
    for(int i=0;i<600;i++){prepare(1.0f/60);CHECK(MF32(0xA99A5C)==0);advance(MF32(0xA99A5C));}
    CHECK(M32(0xA62EE8)==0 && (M32(0xA8BAE4)&2));
    is_open=0;prepare(1.0f/60);
    CHECK(MF32(0xA99A5C)<=1.0f/60+0.0003f);
    CHECK(!(M32(0xA8BAE4)&2));advance(MF32(0xA99A5C));
    for(int i=1;i<60;i++){prepare(1.0f/60);advance(MF32(0xA99A5C));}
    printf("held=0 resumed=%u close_catchup=0\n",M32(0xA62EE8));
    CHECK(abs((int)M32(0xA62EE8)-60)<=1);
    /* Diagnostic held-shot: freeze native counters, then resume without catchup.
     * Broken control: omitting the diagnostic hold advances 59 ticks (native carry boundary). */
    reset();diag_on=1;setenv("BOOT_DIAG_LOOK_AB","lamplightoff,lamplightshift",1);
    char shot[512]="/tmp/frame_12345.png";
    CHECK(postfx_look_listed("lamplightshift"));CHECK(!postfx_ab_shot(shot,sizeof shot));
    for(int i=0;i<60;i++){prepare(1.0f/60);advance(MF32(0xA99A5C));}
    printf("look_hold_ticks=%u\n",M32(0xA62EE8));
    CHECK(M32(0xA62EE8)==0);CHECK(postfx_look_variant("lamplightoff"));
    CHECK(postfx_ab_shot(shot,sizeof shot));CHECK(!strcmp(shot,"/tmp/frame_12345_lamplightoff.png"));
    prepare(1.0f/60);CHECK(postfx_look_variant("lamplightshift"));
    CHECK(postfx_ab_shot(shot,sizeof shot));CHECK(!strcmp(shot,"/tmp/frame_12345_lamplightshift.png"));
    prepare(1.0f/60);CHECK(!postfx_look_variant("lamplightshift"));
    for(int i=0;i<60;i++){prepare(1.0f/60);advance(MF32(0xA99A5C));}
    printf("look_resume_ticks=%u\n",M32(0xA62EE8));CHECK(M32(0xA62EE8)==59);diag_on=0;
    /* A native SMS already holds the simulation without PauseMenu sound. */
    reset();M32(0x100024)=2;M32(0xA8AD18)=1;M32(0xA8BAE4)=32;sound_calls=0;
    is_open=1;prepare(0.01f);CHECK(M32(0xA8BAE4)==34);
    is_open=0;prepare(0.01f);
    printf("sms_sound=%u expected=32 calls=%d\n",M32(0xA8BAE4),sound_calls);
    CHECK(M32(0xA8BAE4)==32 && sound_calls==2);
    CHECK(M32(0x100024)==2 && M32(0xA8AD18)==1);
    /* Reopening over the same modal must not inherit stale ownership. */
    is_open=1;prepare(0.01f);is_open=0;prepare(0.01f);
    CHECK(M32(0xA8BAE4)==32 && sound_calls==4);
    reset();M32(0x100024)=2;M32(0xA8BAE4)=34;sound_calls=0;
    is_open=1;prepare(0.01f);is_open=0;prepare(0.01f);
    CHECK(M32(0xA8BAE4)==34 && sound_calls==0);
    /* Native pause before F10; then F10 before native pause. */
    reset();M32(0xA8BAE4)=2;M32(0x100024)=2;sound_calls=0;
    is_open=1;prepare(0.01f);is_open=0;prepare(0.01f);
    CHECK(sound_calls==0 && M32(0xA8BAE4)==2);
    reset();is_open=1;prepare(0.01f);M32(0x100024)=2;is_open=0;prepare(0.01f);
    CHECK(M32(0xA8BAE4)==2);M32(0xA8BAE4)=0;M32(0x100024)=3;
    is_open=1;prepare(0.01f);is_open=0;prepare(0.01f);CHECK(M32(0xA8BAE4)==0);
    is_open=1;prepare(0.01f);M32(0xA8BAE4)=0;prepare(0.01f);
    CHECK(M32(0xA8BAE4)==2);is_open=0;prepare(0.01f);CHECK(M32(0xA8BAE4)==0);
    reset();Cpu c=cpu(),saved=c;is_open=1;portmenu_pass(&c);CHECK(!memcmp(&c,&saved,sizeof c));
    is_open=0;portmenu_pass(&c);
    /* Fake monotonic clock, real ns-to-Mach conversion; no wall-clock deadline. */
    limit_ms=1000.0/60;carbon_frame_limit_apply(2);carbon_picture_wait();
    CHECK(waits==2 && !released && carbon_deadline==1016666667ull);
    uint64_t old=carbon_deadline;fake_now+=1000000;carbon_picture_wait();
    CHECK(carbon_deadline==old+16666667ull);
    fake_now+=1000000000;carbon_picture_wait();CHECK(carbon_deadline>fake_now-100);
    limit_ms=1000.0/120;old=fake_now;carbon_picture_wait();CHECK(carbon_deadline==old+8333333ull);
    carbon_frame_limit_apply(0);CHECK(!*carbon_frame_limit_choice && !carbon_deadline);
    limit_ms=0;int calls=waits;carbon_picture_wait();CHECK(waits==calls);
    unsigned clocks=clock_reads, queries=limit_queries;
    c=cpu();for(int i=0;i<128;i++)CHECK(device_present(&c)==1);
    CHECK(clock_reads==clocks && limit_queries==queries && waits==calls);
    CHECK(presentations==128 && yields==128);
    /* Startup load changes value without calling apply, just like settings_init. */
    register_limit();CHECK(registered_limit && carbon_frame_limit_choice==&registered_limit->value);
    registered_limit->value=2;limit_ms=1000.0/60;calls=waits;c=cpu();
    CHECK(device_present(&c)==1 && waits>calls);
    CHECK(aa_polls==0);diag_on=1;CHECK(device_present(&c)==1&&aa_polls==1);diag_on=0;
    puts("CLOCK PASS ownership, native ABI/carry, cap change/stall/Off, interrupted wait");free(G);return 0;
}
'''


def main():
    if not (HERE / 'out/carbon-base/image.json').is_file():
        print('SKIP: Carbon outputs absent'); return 3
    bodies = '\n'.join(original(a) for a in FRAGMENTS)
    sys.path.insert(0, str(HERE))
    import recomp
    image = json.loads((HERE / 'out/carbon-base/image.json').read_text())
    pe = recomp.PE(image['exe'], expected_sha256=image['sha256'])
    # Only constants consumed by the pinned native fragments, not a whole image.
    constants = [0x9C7D08, 0x9CBC14, 0x9C5DB4, 0x9C2888, 0x9CD824, 0x9D6354, 0x9C2664, 0x9E31E0, 0x9E31E4]
    data = b''.join(pe.read(a, 4) for a in constants)
    assert hashlib.sha256(data).hexdigest() == '9f9b050986b726d0a63c9cee032315ee884a87d1827a40da6efac05928620ddc'
    initializers = '\n'.join(f'M32(0x{a:X})=0x{int.from_bytes(pe.read(a,4), "little"):08X}u;' for a in constants)
    harness = HARNESS.replace('ORIGINALS', bodies).replace('CONSTANTS', initializers)
    source = (PRIVATE / 'carbon_picture_clock.c').read_text()
    assert 'carbon_fe_probe' not in source, 'FE sampling belongs to the frame adapter'
    hold = (PRIVATE / 'game_menu_hold.h').read_text()
    present = (PRIVATE / 'game_picture_present.h').read_text()
    assert 'if (*carbon_frame_limit_choice || carbon_simrate_enabled()) carbon_picture_wait();' in present
    assert present.index('present();') < present.index('carbon_picture_wait();', present.index('present();'))
    for variant in ('good', 'minimum-one', 'sticky-hold', 'startup-latch', 'aa-no-poll', 'no-look-hold', 'prepaused-sound-leak'):
        with tempfile.TemporaryDirectory(prefix='picture04-') as td:
            tmp = Path(td)
            selected = source
            pacing = (PRIVATE / 'game_pacing_settings.h').read_text()
            selected_present = present
            selected_hold = hold
            if variant == 'minimum-one':
                selected = selected.replace('if (c->ecx == 0)', 'if (0)')
            elif variant == 'sticky-hold':
                selected = selected.replace('int held = portmenu_hold();', 'static int held; held |= portmenu_hold();')
            elif variant == 'startup-latch':
                pacing = pacing.replace('carbon_frame_limit_choice = &limit.value;', '/* broken: no loaded-value binding */')
            elif variant == 'no-look-hold':
                selected = selected.replace('held |= postfx_ab_hold();', '(void)0;')
            elif variant == 'aa-no-poll':
                selected_present = selected_present.replace('    if (diag_on) (void)aa_game_get();', '')
            elif variant == 'prepaused-sound-leak':
                selected_hold = hold.replace(' && !native_paused_on_take', '')
                assert selected_hold != hold, 'sound ownership mutant must change the guard'
            (tmp / 'clock.c').write_text(selected)
            (tmp / 'hold.inc').write_text(selected_hold)
            (tmp / 'present.inc').write_text(selected_present)
            (tmp / 'pacing.inc').write_text(pacing)
            (tmp / 'fixture.c').write_text(harness)
            command = ['clang', '-O1', '-fsanitize=address,undefined', '-I', str(tmp), '-I', str(ROOT / 'runtime'), '-I', str(HERE), '-I', str(PRIVATE), str(tmp / 'fixture.c'), '-o', str(tmp / 'fixture')]
            built = subprocess.run(command, capture_output=True, text=True)
            assert built.returncode == 0, built.stderr[-6000:]
            result = subprocess.run([str(tmp / 'fixture')], capture_output=True, text=True)
            print(variant, 'exit=' + str(result.returncode), result.stdout.strip())
            if variant == 'good':
                assert result.returncode == 0, result.stderr[-4000:]
            else:
                assert result.returncode == 1 and 'CLOCK CHECK' in result.stderr, result.stderr[-4000:]
                if variant == 'prepaused-sound-leak':
                    assert 'sms_sound=34 expected=32 calls=1' in result.stdout, result.stdout
    print('PRIVATE PICTURE 04 PASS native clock/hold/cap and diagnostic poll; six mutants rejected')
    return 0


if __name__ == '__main__':
    sys.exit(main())
