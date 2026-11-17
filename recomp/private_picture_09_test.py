"""Fixed-step opt-in, compiled against SHA-256-pinned native fragments (no history).

120 Hz: step=0.00833333377, catch-up=16, sub-rate=0.25, every-tick delay=6.
Good exit=0; pass-through provider control exit=1 (native step=0.0166666675).
Intro wait: 120 Hz advances 1 count / 2 calls (0.5/call); unset advances
2 counts / 2 calls (1/call). Intro-only pass-through control exits 1 at 2
instead of 1; good exits 0. Unset intro guest/Cpu byte differences=0.
Unset: all guest bytes and Cpu state match the originals, including stack scratch.
Also covers 30/60/480 Hz, callback dt/mode/slow motion, task delay ownership,
accumulator carry, inactive simulation, slot policy at Off/120/60/40 and recovery.
Exit 3 without private outputs. Dependencies: carbon_simrate.c,
carbon_picture_clock.c, game_picture_present.h, features/picture_09.json,
hooks/picture_09.json, runtime/looppace.h and runtime/overlay.m.
"""
from pathlib import Path
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
PRIVATE = HERE / 'private_runtime'
FRAGMENTS = {
    '00761150': '51d9cbd9fd87dc68c8b87d799f3c8ced3a20ddb7a9aefab29a624b5738998eb1',
    '00764980': '85b286c44818228c6de6bb9b37d921185208b42631afdd00a86ac71b673a42dc',
    '0076ACE0': '1bc3e9d02d3c6cf8346a2a20d19eb4075bc7849573e6137274c7956290426ab0',
    '00760C70': '3af2fc6cf4b801f9a5bd7d5b40e7d83d7331948672f414ba0bce1796c0c05234',
    '0087EAC0': '613c584ed1cb82b7014a6eca36763dae6aec8f78e3feb2d21d5d02ee0a30312c',
    '00769A20': '5f456e30a83c3c9b8f8c3a13bd72886a112e23327545a7053611226b52ae0e0c',
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
#include "looppace.h"
#include <math.h>
#include <stdlib.h>
uint8_t *G;
#define CHECK(x) do { if(!(x)) { fprintf(stderr,"SIMRATE CHECK %d: %s\n",__LINE__,#x); exit(1); } } while(0)
static const uint32_t self=0x100000;
static uint32_t posted, batches, callback_mode=3;
static float callback_dt, callback_speed=1;
static int callbacks=1, cleanups, mode_updates;
static int intro_syncs, intro_loads, intro_starts;
int user32_display_hz(void) { return 120; }
void f_0087EAC0(Cpu *c);
void native_0087EAC0(Cpu *c);
void f_0087EAC0(Cpu *c) { native_0087EAC0(c); }
void f_00561590(Cpu *c) { CHECK(M32(c->esp+4)==0x1c);c->eax=0x200000;c->esp+=4; }
void f_00672C70(Cpu *c) { CHECK(c->ecx==0x200000);posted=M32(c->esp+8);++batches;c->esp+=24; }
void f_0060DC60(Cpu *c) { c->esp+=8; }
void f_00465930(Cpu *c) { c->eax=0;c->esp+=4; }
void f_00461340(Cpu *c) { c->esp+=12; }
void f_00463A80(Cpu *c) { (void)c;abort(); }
void f_00678410(Cpu *c) { (void)c;abort(); }
void f_0075C4B0(Cpu *c) { c->eax=0;c->esp+=4; }
void f_00761010(Cpu *c) { c->eax=0x300000;c->esp+=24; }
void f_0075CA40(Cpu *c) { c->eax=c->ecx;c->esp+=4; }
void f_0076AC90(Cpu *c) { ++cleanups;c->esp+=4; }
void f_0060CB50(Cpu *c) {
    CHECK(c->ecx==0x330000);
    uint32_t key=M32(c->esp+4);CHECK(key==0x75c250||key==0x66b500);
    c->eax=callbacks?(key==0x75c250?0x340000:0x340100):0;c->esp+=8;
}
void f_00764BC0(Cpu *c) { CHECK(c->ecx==self && M32(c->esp+4)==7);++mode_updates;c->esp+=8; }
void f_00763590(Cpu *c) { CHECK(c->ecx==self-4);++intro_syncs;c->esp+=8; }
void f_00763300(Cpu *c) { c->esp+=8; }
void f_007697A0(Cpu *c) { CHECK(c->ecx==self-4);M32(self+0x31c)=5;++intro_starts;c->esp+=4; }
void f_0045E690(Cpu *c) { CHECK(c->ecx==0x410000);++intro_loads;c->esp+=8; }
void f_0066E1A0(Cpu *c) { (void)c;abort(); }
void f_00670FA0(Cpu *c) { (void)c;abort(); }
void dispatch(Cpu *c,uint32_t fn) {
    if(fn==0x350000) {
        CHECK(c->ecx==0x340000);callback_dt=MF32(c->esp+4);
        CHECK(MF32(c->esp+8)==MF32(self+0x1c));x87_push(c,callback_speed);c->esp+=12;
    } else if(fn==0x350100) {
        CHECK(c->ecx==0x340100);c->eax=callback_mode;c->esp+=8;
    } else if(fn==0x350104) {
        CHECK(c->ecx==0x340100);c->eax=7;c->esp+=4;
    } else { fprintf(stderr,"unexpected dispatch %x\n",fn);abort(); }
}
uint32_t call_guest(Cpu *c,uint32_t fn,int n,const uint32_t *args) {
    uint32_t sp=c->esp;
    for(int i=n-1;i>=0;--i){c->esp-=4;M32(c->esp)=args[i];}
    c->esp-=4;M32(c->esp)=0xfeedf00d;
    switch(fn) {
    case 0x561590:f_00561590(c);break;
    case 0x672c70:f_00672C70(c);break;
    case 0x76ac90:f_0076AC90(c);break;
    case 0x60cb50:f_0060CB50(c);break;
    case 0x764bc0:f_00764BC0(c);break;
    default:dispatch(c,fn);break;
    }
    c->esp=sp;return c->eax;
}
ORIGINALS
#include "simrate.c"
static Cpu cpu(void) {
    Cpu c={0};c.esp=0x80000;c.ecx=self;c.fs_base=0x7000;c.cw=0x37f;
    c.ebx=17;c.esi=29;c.edi=31;c.ebp=37;return c;
}
static void reset(void) {
    memset(G,0,0xc00000);
    CONSTANTS
    MF32(0x9c2478)=1;MF32(0x9c248c)=0;
    M32(0xb4cfe0)=self;M32(self+0x28)=0x320000;M32(0x320004)=0x330000;
    M32(0x340000)=0x360000;M32(0x360004)=0x350000;
    M32(0x340100)=0x360100;M32(0x360104)=0x350100;M32(0x360108)=0x350104;
    MF32(self+0x1c)=1;MF32(0x80004)=0.2f;
    posted=batches=cleanups=mode_updates=0;callback_dt=0;callback_speed=1;callback_mode=3;callbacks=1;
    intro_syncs=intro_loads=intro_starts=0;
}
static void intro_setup(void) {
    M32(self+0x78)=0x1234;M32(0x80004)=0x1234;
    M32(self+0x31c)=3;M8(self+0x414)=1;M32(self+0x3cc)=0x410000;
}
/* Production clock with deterministic nanoseconds and interrupted Mach wait. */
#include <mach/mach_time.h>
#include <mach/kern_return.h>
int diag_on;
void diag_warp_pass(Cpu *c) { (void)c; }
static uint64_t fake_now=1000000000ull, waited;
static int released, waits, held;
static double limit_ms;
uint64_t host_ticks(void) { return fake_now; }
void diag_event(const char *fmt,...) { (void)fmt; }
PerfFrame perf_frames[PERF_RING]; volatile uint64_t perf_nframes;   /* carbon_fe_probe.h, never reached with diag off */
void gil_release(void) { CHECK(!released);released=1; }
void gil_acquire(void) { CHECK(released);released=0; }
int portmenu_hold(void) { return held; }
void portmenu_pass(Cpu *c) { (void)c; }
double render_loop_limit_ms(void) { return limit_ms; }
static kern_return_t fixture_wait(uint64_t deadline) {
    CHECK(released);waited=deadline;++waits;
    if(waits==1)return KERN_ABORTED;
    mach_timebase_info_data_t tb;mach_timebase_info(&tb);
    fake_now=deadline*tb.numer/tb.denom;return KERN_SUCCESS;
}
#define mach_wait_until fixture_wait
#include "clock.c"
#undef mach_wait_until
static void noop(Cpu *c) { (void)c; }
int main(void) {
    G=calloc(1,0xc00000);CHECK(G);
    int enabled=getenv("NFS_SIMHZ")!=NULL;
    int hz=carbon_sim_hz();float step=1.0f/hz;
    if(!enabled) {
        /* No guest byte changes added by any wrapper, including scratch stack. */
        void (*hooks[])(Cpu*,void(*)(Cpu*))={carbon_simrate_construct,carbon_simrate_task,carbon_simrate_batch,carbon_simrate_advance,carbon_simrate_intro};
        void (*native[])(Cpu*)={native_00764980,native_00760C70,native_00761150,native_0076ACE0,native_00769A20};
        uint8_t *saved=malloc(0xc00000);CHECK(saved);
        for(int k=0;k<5;++k) {
            reset();if(k==4)intro_setup();Cpu a=cpu();native[k](&a);memcpy(saved,G,0xc00000);
            reset();if(k==4)intro_setup();Cpu b=cpu();hooks[k](&b,native[k]);
            CHECK(!memcmp(&a,&b,sizeof a));CHECK(!memcmp(saved,G,0xc00000));
            reset();memcpy(saved,G,0xc00000);b=cpu();hooks[k](&b,noop);
            CHECK(!memcmp(saved,G,0xc00000));
        }
        reset();intro_setup();for(int i=0;i<2;++i){Cpu c=cpu();carbon_simrate_intro(&c,native_00769A20);}
        printf("intro two-call count=%u (unset)\n",M32(self+0x41c));CHECK(M32(self+0x41c)==2);
        free(saved);puts("unset byte differences=0");free(G);return 0;
    }
    reset();intro_setup();
    /* A full rational period measures the fractional count exactly. */
    int period=hz;while(period%60)period+=hz;period/=60;
    for(int i=0;i<period;++i){Cpu c=cpu();carbon_simrate_intro(&c,native_00769A20);CHECK(c.esp==0x8000c);}
    printf("intro count=%u calls=%d per-call=%.8g\n",M32(self+0x41c),period,(double)M32(self+0x41c)/period);
    CHECK(M32(self+0x41c)==(unsigned)(period*60/hz));
    CHECK(intro_syncs==period && intro_loads==period && !intro_starts);
    /* Native counter reset, wrong task, other state and blocked
     * resource readiness must retain their native work and branch behavior. */
    reset();intro_setup();M32(self+0x41c)=9;
    Cpu ic=cpu();M32(ic.esp+4)=0;carbon_simrate_intro(&ic,native_00769A20);CHECK(M32(self+0x41c)==9 && !intro_syncs);
    M32(0x80004)=0x1234;M32(self+0x31c)=5;ic=cpu();carbon_simrate_intro(&ic,native_00769A20);CHECK(M32(self+0x41c)==9);
    reset();intro_setup();M8(self+0x448)=1;
    for(int i=0;i<hz;++i){ic=cpu();carbon_simrate_intro(&ic,native_00769A20);}
    CHECK(M32(self+0x41c)==60 && !intro_starts && intro_loads==hz);
    M8(self+0x448)=0;ic=cpu();carbon_simrate_intro(&ic,native_00769A20);CHECK(intro_starts==1 && M32(self+0x41c)==60);
    reset();intro_setup();int intro_calls=0;
    while(!intro_starts && intro_calls<1000){ic=cpu();carbon_simrate_intro(&ic,native_00769A20);++intro_calls;}
    CHECK(intro_starts==1 && fabs((intro_calls-1.0)/hz-31.0/60)<=1.0/hz+1e-7);
    printf("intro starts after %d calls, wait=%.9g\n",intro_calls,(intro_calls-1.0)/hz);
    reset();Cpu c=cpu();carbon_simrate_construct(&c,native_00764980);
    printf("hz=%d step=%.10g\n",hz,MF32(self+0x14));
    CHECK(MF32(0x9ebb6c)==step && MF32(self+0x14)==step);
    CHECK(M32(0x9cbc14)==0x3c888889 && c.esp==0x80004);
    reset();c=cpu();MF32(c.esp+4)=1;carbon_simrate_batch(&c,native_00761150);
    printf("catch-up=%u\n",posted);CHECK(posted==8u*(unsigned)hz/60 && batches==1);
    CHECK(MF32(0xb4d7ec)==0 && c.esp==0x80004);
    reset();c=cpu();MF32(c.esp+4)=step*0.25f;
    carbon_simrate_batch(&c,native_00761150);CHECK(batches==0 && MF32(0xb4d7ec)==step*0.25f);
    c=cpu();MF32(c.esp+4)=step;carbon_simrate_batch(&c,native_00761150);
    CHECK(posted==1 && fabsf(MF32(0xb4d7ec)/step-0.25f)<1e-5f);
    reset();M32(0xb4cfe0)=0;c=cpu();carbon_simrate_batch(&c,native_00761150);CHECK(!batches && !MF32(0xb4d7ec));
    reset();c=cpu();MF32(c.esp+8)=0.5f;MF32(c.esp+16)=3;
    carbon_simrate_task(&c,native_00760C70);
    printf("task-rate=%.8g task-delay=%.8g\n",MF32(self),-MF32(self+8));
    CHECK(MF32(self)==0.5f*60/hz && MF32(self+8)==-3);
    reset();c=cpu();MF32(c.esp+8)=1;MF32(c.esp+16)=3;
    carbon_simrate_task(&c,native_00760C70);
    printf("every-tick-delay=%.8g\n",-MF32(self+8));
    CHECK(MF32(self)==1 && fabsf(MF32(self+8)+3.0f*hz/60)<1e-5f);
    for(int mode=0;mode<4;++mode) {
        reset();c=cpu();callback_speed=0.75f;
        if(mode==0)M32(self+0x28)=0;
        if(mode==1)callbacks=0;
        if(mode==2)callback_mode=2;
        carbon_simrate_advance(&c,native_0076ACE0);
        CHECK(cleanups==1 && c.esp==0x80004 && c.top==7);
        CHECK(c.ebx==17 && c.esi==29 && c.edi==31 && c.ebp==37);
        CHECK(MF32(self+0x14)==(mode<2?step:step*0.75f));
        if(mode>=2)CHECK(callback_dt==step && mode_updates==1);
        CHECK(fabs(c.st[c.top]-(mode==3?step*0.75:0))<1e-8);
    }
    /* Selected pure slot policy: Off is one step; lower limits group steps. */
    const double limits[]={0,1.0/120,1.0/60,1.0/40};
    for(int i=0;i<4;++i) {
        uint64_t now=1000000000,deadline=now;
        int k=looppace_ticks(step,limits[i]);
        uint64_t next=looppace_deadline(deadline,now,step,0.5f,limits[i],k,0);
        CHECK(next>now);
        CHECK(looppace_deadline(next,now+1000000000,step,0.5f,limits[i],k,0)==now+1000000000);
        CHECK(looppace_deadline(next,now,step,0.5f,limits[i],k+1,0)==now);
    }
    /* Execute the selected production clock, including its accumulator read. */
    for(int i=0;i<4;++i) {
        reset();limit_ms=limits[i]*1000;fake_now=1000000000ull;
        carbon_frame_limit_apply(i);carbon_previous_ticks=100;
        M32(0xb4cfd4)=100;MF32(0xb4d7ec)=step*0.25f;
        carbon_picture_wait();CHECK(carbon_deadline==fake_now);
        uint64_t now=fake_now, old=carbon_deadline;
        int k=looppace_ticks(step,limits[i]);M32(0xb4cfd4)+=k;
        uint64_t expected=looppace_deadline(old,now,step,0.25f,limits[i],k,0);
        int before=waits;carbon_picture_wait();CHECK(waits>before && !released);
        CHECK(carbon_deadline==expected && fake_now>=now);
        CHECK(waited>0);
        /* Catch-up skips sleep; the next frame can recover its slot. */
        before=waits;M32(0xb4cfd4)+=k+1;carbon_picture_wait();CHECK(waits==before);
    }
    reset();diag_on=1;M32(0xa99bbc)=6;carbon_previous_ticks=100;
    uint64_t frames=carbon_frames, one=carbon_one;M32(0xb4cfd4)=101;
    carbon_picture_wait();CHECK(carbon_frames==frames+1 && carbon_one==one+1);
    held=1;M32(0xb4cfd4)++;carbon_picture_wait();CHECK(carbon_frames==frames+1);
    held=0;M32(0xa99bbc)=3;carbon_picture_wait();CHECK(carbon_frames==frames+1);
    diag_on=0;M32(0xa99bbc)=6;carbon_picture_wait();CHECK(carbon_frames==frames+1);
    puts("SIMRATE PASS");free(G);return 0;
}
'''


def main():
    image_path = HERE / 'out/carbon-base/image.json'
    if not image_path.is_file():
        print('SKIP: Carbon outputs absent'); return 3
    sys.path.insert(0, str(HERE))
    import recomp
    image = json.loads(image_path.read_text())
    pe = recomp.PE(image['exe'], expected_sha256=image['sha256'])
    constants = (0x9EBB6C, 0x9EC0A8, 0x9CBC14, 0x9EBB68)
    raw = b''.join(pe.read(a, 4) for a in constants)
    assert hashlib.sha256(raw).hexdigest() == '3b250c4c70eb3af162242bb248dc3c7bb0bddad5f68726db1f41273de847816c'
    initializers = '\n'.join(f'M32(0x{a:X})=0x{int.from_bytes(pe.read(a,4), "little"):08X}u;' for a in constants)
    harness = HARNESS.replace('ORIGINALS', '\n'.join(original(a) for a in FRAGMENTS)).replace('CONSTANTS', initializers)
    source = (PRIVATE / 'carbon_simrate.c').read_text()
    present = (PRIVATE / 'game_picture_present.h').read_text()
    assert '*carbon_frame_limit_choice || carbon_simrate_enabled()' in present
    clock = (PRIVATE / 'carbon_picture_clock.c').read_text()
    assert 'carbon_fe_probe' not in clock, 'FE sampling belongs to the frame adapter'
    assert 'looppace_deadline(' in clock and 'MF32(0x00B4D7ECu) / step' in clock
    assert 's->sim_hz = carbon_sim_hz();' in (ROOT / 'runtime/overlay.m').read_text()
    feature = json.loads((PRIVATE / 'features/picture_09.json').read_text())
    assert feature['bindings']['carbon_simrate.c']['sha256'] == hashlib.sha256(source.encode()).hexdigest()
    hooks = json.loads((PRIVATE / 'hooks/picture_09.json').read_text())['hooks']
    assert {r['address'] for r in hooks} == set(FRAGMENTS) - {'0087EAC0'}
    for row in hooks:
        witness = row['witness']
        assert hashlib.sha256(pe.read(int(row['address'],16), witness['length'])).hexdigest() == witness['sha256']
    for variant in ('good', 'pass-through', 'intro-pass-through'):
        with tempfile.TemporaryDirectory(prefix='picture09-') as td:
            tmp = Path(td)
            selected = source
            if variant == 'pass-through':
                selected = selected.replace('if (!carbon_simrate_enabled()) { original(c); return; }', 'if (1) { original(c); return; }')
            if variant == 'intro-pass-through':
                selected = selected.replace('if (!carbon_simrate_enabled() || carbon_sim_hz() == 60)', 'if (1)')
            (tmp / 'simrate.c').write_text(selected)
            (tmp / 'clock.c').write_text(clock)
            (tmp / 'fixture.c').write_text(harness)
            command = ['clang', '-O1', '-fsanitize=address,undefined', '-I', str(tmp), '-I', str(ROOT / 'runtime'), '-I', str(HERE), '-I', str(PRIVATE), str(tmp / 'fixture.c'), '-o', str(tmp / 'fixture')]
            result = subprocess.run(command, capture_output=True, text=True)
            assert result.returncode == 0, result.stderr[-5000:]
            rates = (None, '120', '30', '60', '480', 'bad', '120suffix') if variant == 'good' else ('120',)
            for rate in rates:
                env = dict(os.environ); env.pop('NFS_SIMHZ', None)
                if rate is not None: env['NFS_SIMHZ'] = rate
                result = subprocess.run([str(tmp / 'fixture')], env=env, capture_output=True, text=True)
                print(variant, 'NFS_SIMHZ=' + str(rate), 'exit=' + str(result.returncode), result.stdout.strip())
                assert result.returncode == (0 if variant == 'good' else 1), result.stderr[-3000:]
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
