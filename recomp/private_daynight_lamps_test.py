"""Scoped street-flare curve, car flares, cone parking, queued diagnostics and
exact stack restoration.

Good: 246 checks / 0 failures (exit 0). Factor always one: 251 checks /
56 failures. Wrong scope (the original missed scene path): 250 / 29.
All scene kinds scaled: 244 / 15. Dusk-gain=1: 246 / 24.
Missing restoration: 246 / 4. Cones always native (old code): 243 / 17.
Car flares always native (old code): 250 / 16.
Every broken variant and the original provider exit 1.
The native scene batch executes; the flare callee models queue rejection and native
in-place intensity attenuation. Pinned translated fragments establish the ABI
and actual queue counter. Missing private inputs: exit 3. No game is launched.
"""
from pathlib import Path
import hashlib
import json
import re
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
from build_private import ignored_output
from recomp import PE
import private_hooks


PINS = (
    ('0074D330: push ebp', '0074D333:', 'c38481cd2c53768063231a35a680a8617cf97b5618d8ef14ae1c8f81bf12cca0'),
    ('0074DB4F:', '0074DB57:', '668c00e448a586e164de01887bed31686d4d7347fa141322363f4e799da28979'),
    ('00750A78:', '00750AAF:', 'b6004dfc14f51fa935dce7f4d9ecb4004280a87be23965eef36385e48c8a2a60'),
    ('0074E0FB:', '0074E105:', '7dacbf0ba79134ae3ae398e17611d1d326366a55350fe735572ce5ac2754532c'),
    ('00749D2D:', '00749D33:', 'e6fab4b7c02f3aeb74da13219db907efc205fdcffb3e7f7b494534713d4e613e'),
)


HARNESS = r'''
#include "host.h"
#include <stdlib.h>
#include <stdarg.h>
#include <math.h>
uint8_t *G;
int diag_on;
static unsigned checks, failures, walks, flares, events, shot_queries;
static float night=1, expected_intensity=1;
static uint64_t frame=4799;
static int capture=1, visible=1, attenuate=1;
static unsigned event_count;
static unsigned street_calls, other_calls, car_calls, cone_calls, guest_calls;
static float car_expected=1;
static uint32_t guest_ecx, guest_matrix[16];
static double event_sum;
static uint64_t event_frame;
#define CHECK(x) do {++checks; if(!(x)){++failures;fprintf(stderr,"LAMP CHECK %d: %s\n",__LINE__,#x);}}while(0)
float carbon_daynight_night(void) { return M32(0x00A99BBCu)==6 ? night : 1; }
uint64_t diag_current_frame(void) { return frame; }
int diag_shot_due(uint64_t f) { ++shot_queries; CHECK(f==frame+1); return capture; }
void diag_event(const char *fmt, ...) {
    va_list ap;va_start(ap,fmt);
    event_frame=va_arg(ap,unsigned long long);
    event_count=va_arg(ap,unsigned);
    event_sum=va_arg(ap,double);
    va_end(ap);++events;
}
uint32_t call_guest(Cpu *c,uint32_t fn,int n,const uint32_t *args) {
    ++guest_calls;CHECK(fn==0x004822F0u&&n==2&&args[1]==0&&args[0]==c->esp&&c->esp+0x40<=0x10000);
    guest_ecx=c->ecx;memcpy(guest_matrix,G+args[0],sizeof guest_matrix);return 0;
}
static void cone_original(Cpu *c) { ++cone_calls;c->esp+=4; }
#include "lamps.inc"
void f_0074D330(Cpu *c);
void f_0087EAC0(Cpu *c) { c->eax=0; c->esp+=4; }
void f_0055A750(Cpu *c) { x87_push(c,1);c->esp+=4; }
void f_0047AA00(Cpu *c) { c->eax=0;c->esp+=4; }
void f_0061AAF0(Cpu *c) { c->eax=0;c->esp+=4; }
void f_004A0490(Cpu *c) { c->esp+=4; }
#include "walker.inc"
static void native_flare(Cpu *c) {
    ++flares;
    int street=M8(M32(c->esp+8)+0x2c)==13,car=M32(c->esp)==0x007CC646u;
    CHECK(MF32(c->esp+0x10)==(car?car_expected:street?expected_intensity:1));
    if(car) ++car_calls; else if(street) ++street_calls; else ++other_calls;
    /* One rejected flare proves diagnostics count queue additions, not calls. */
    if(M32(c->esp+8)!=0x00B43860u) ++M32(0x00B4CF38u);
    if(attenuate) MF32(c->esp+0x10)*=0.5f;
    c->eax=0x12345678;c->esp+=4;
}
void f_0074D330(Cpu *c) { carbon_daynight_lamps_flare(c,native_flare); }
static Cpu initial(unsigned mode) {
    Cpu c={0}; c.esp=0x10000;c.ebp=0xABCDEF;c.ebx=123;c.esi=456;c.edi=789;
    M32(c.esp+4)=0x4000;M32(0x4008)=mode;M32(c.esp+8)=0x00B43830u;return c;
}
static void world(unsigned mode,float want,unsigned want_count,double want_sum) {
    unsigned before=street_calls,other_before=other_calls,old_events=events;
    expected_intensity=want;
    Cpu c=initial(mode);
    ++walks;M32(0x00B42F1Cu)=!visible;
    carbon_daynight_lamps_world(&c,carbon_orig_007507D0);
    CHECK(c.esp==0x10004&&c.ebp==0xABCDEF&&c.ebx==123&&c.esi==456&&c.edi==789);
    CHECK(street_calls-before==((want>0&&visible)?2u:0u));
    CHECK(other_calls-other_before==(visible?1u:0u));
    if(diag_on&&capture&&mode==1&&M32(0x00A99BBCu)==6) {
        CHECK(events==old_events+1);CHECK(event_frame==frame+1);
        CHECK(event_count==want_count);CHECK(event_sum==want_sum);
    } else CHECK(events==old_events);
    ++frame;
}
int main(void) {
    G=calloc(1,0xC00000);if(!G)return 2;
    M32(0x00A6C088u)=1;M32(0x00A99BBCu)=6;
    M32(0x4040)=0x5000;MF32(0x009C2478u)=1;MF32(0x009CD824u)=1;
    M32(0x00B42EFCu)=3;
    for(unsigned i=0;i<3;++i) {
        M8(0x00B43830u+i*0x30+0x2c)=i==2?14:13;
        M32(0x00B42988u+i*4)=0xffffffffu;
    }
    /* Endpoint pass-through must preserve the native callee's stack writes. */
    for(unsigned d=0;d<2;++d) {
        diag_on=d;
        night=1;world(1,1,1,1); /* Off helper / midnight. */
        night=0;world(1,0,0,0); /* Noon: scene walk and non-street flare remain native. */
        night=0.5f;world(1,1,1,1); /* Dusk: full lamps. */
        night=0.125f;world(1,0.25f,1,0.25); /* Transition. */
        night=0.25f;world(3,0.5f,0,0);world(4,0.5f,0,0);
    }
    /* The scope must end on return, including direct/non-world flare calls. */
    expected_intensity=1;Cpu c=initial(1);MF32(c.esp+0x10)=1;
    f_0074D330(&c);CHECK(MF32(0x10010)==0.5f);
    /* Exact bit restoration while scaling, even if the native callee mutates it. */
    carbon_dn_lamps_scope.depth=1;carbon_dn_lamps_scope.factor=0.25f;
    for(unsigned i=0;i<2;++i) {
        c=initial(1);MF32(c.esp+0x10)=1;expected_intensity=0.25f;attenuate=i;
        f_0074D330(&c);CHECK(M32(0x10010)==0x3F800000u);CHECK(c.esp==0x10004);
    }
    carbon_dn_lamps_scope.depth=0;attenuate=1;
    /* No diagnostic queries when diagnostics are off. */
    diag_on=0;unsigned q=shot_queries;night=1;world(1,1,0,0);CHECK(shot_queries==q);
    diag_on=1;capture=0;night=0.125f;world(1,0.25f,0,0);
    capture=1;M32(0x00A99BBCu)=3;world(1,1,0,0);
    M32(0x00A99BBCu)=6;visible=0;unsigned old=events;
    c=initial(1);M32(0x00B42F1Cu)=1;carbon_daynight_lamps_world(&c,carbon_orig_007507D0);
    CHECK(events==old+1&&event_count==0&&event_sum==0);
    /* Car flares (007CBC40): head, and unbraked tail at exactly 0.5, follow L. */
    struct { uint32_t ret, lamp; float in, night, want; } cars[] = {
        {0x007CC646u,0x9DB90133u,1,0,0},{0x007CC646u,0xD09091C6u,1,0,0},
        {0x007CC646u,0x31A66786u,0.5f,0,0},{0x007CC646u,0xBF700A79u,0.5f,0,0},
        {0x007CC646u,0xD09091C6u,1,0.125f,0.25f},{0x007CC646u,0x31A66786u,0.5f,0.125f,0.125f},
        {0x007CC646u,0x9DB90133u,1,1,1},{0x007CC646u,0x9DB90133u,1,0.5f,1},
        {0x007CC646u,0x31A66786u,16.5f,0,16.5f},{0x007CC646u,0xA2A2FC7Cu,1,0,1},
        {0x007CC646u,0x7A5B2F25u,1,0,1},{0x00123456u,0x9DB90133u,1,0,1},
    };
    for(unsigned i=0;i<sizeof cars/sizeof *cars;++i) {
        c=initial(1);M32(c.esp)=cars[i].ret;M32(c.esp+8)=0x6000;M32(0x6008)=cars[i].lamp;M8(0x602c)=0;
        MF32(c.esp+0x10)=cars[i].in;night=cars[i].night;car_expected=cars[i].want;
        unsigned before=car_calls+other_calls;
        f_0074D330(&c);
        CHECK(c.esp==0x10004&&c.ebp==0xABCDEF&&c.ebx==123&&c.esi==456&&c.edi==789);
        CHECK(car_calls+other_calls-before==(cars[i].want>0?1u:0u));
        if(cars[i].want==0) CHECK(c.eax==0);
        else CHECK(MF32(0x10010)==(cars[i].want==cars[i].in?cars[i].in*0.5f:cars[i].in));
    }
    /* Cone slots (0074A4E0): by day both are parked, else the native fill runs. */
    for(unsigned i=0;i<4;++i) {
        static const float nights[]={0,0,0.125f,1};
        night=nights[i];M32(0x00B4B390u+0x40)=0x7000;M32(0x00B4B410u+0x40)=i==1?0x7100:0;
        memset(G+0x7000,0x11,0x200);
        c=initial(1);unsigned calls=cone_calls,guests=guest_calls;
        carbon_daynight_lamps_cones(&c,cone_original);
        CHECK(c.esp==0x10004&&c.ebp==0xABCDEF&&c.ebx==123&&c.esi==456&&c.edi==789);
        CHECK(cone_calls-calls==(night>0?1u:0u));
        CHECK(guest_calls-guests==(night>0?0u:i==1?2u:1u));
        for(unsigned k=0;k<16&&night==0;++k) CHECK(guest_matrix[k]==(k==15?0xC61C4000u:0));
        if(night==0) CHECK(guest_ecx==(i==1?0x7100u:0x7000u));
        for(unsigned k=0;k<3;++k) {
            CHECK(M32(0x7040+4*k)==(night>0?0x11111111u:0xC61C4000u));
            CHECK(M32(0x7140+4*k)==(i==1?0xC61C4000u:0x11111111u));
        }
    }
    printf("LAMPS checks=%u failures=%u walks=%u flares=%u events=%u\n",checks,failures,walks,flares,events);
    free(G);return failures?1:0;
}
'''


def command(args, expected=0):
    r = subprocess.run(list(map(str, args)), capture_output=True, text=True, timeout=180)
    if r.returncode != expected:
        raise AssertionError(f'exit {r.returncode}, expected {expected}: {r.stdout[-2000:]} {r.stderr[-2000:]}')
    return r.stdout.strip()


def main():
    base = HERE/'out/carbon-base'
    if not (base/'image.json').is_file() or not (base/'NFSC_40.c').is_file():
        print('SKIP: private lamp fixture needs the private image/build');return 3
    image = json.loads((base/'image.json').read_text())
    if not Path(image['exe']).is_file():
        print('SKIP: private lamp image unavailable');return 3
    source = (base/'NFSC_40.c').read_text()
    for start, end, digest in PINS:
        a = source.index('    /* '+start)
        b = source.index('    /* '+end, a)
        assert hashlib.sha256(source[a:b].encode()).hexdigest() == digest, start
    pe = PE(image['exe'], expected_sha256=image['sha256'])
    out = ignored_output(HERE/'out/carbon/daynight_lamps_check')
    registry = out/'hooks';registry.mkdir(exist_ok=True)
    record = HERE/'private_runtime/hooks/daynight_lamps.json'
    (registry/record.name).write_bytes(record.read_bytes())
    limits = [(a,a+0x2000,'') for a in (0x74A4E0,0x74D330,0x7507D0)]
    hooks = private_hooks.load_registry(pe, limits, registry)
    assert set(hooks)=={0x74A4E0,0x74D330,0x7507D0}
    for address, provider in ((0x74A4E0,'carbon_daynight_lamps_cones'),(0x74D330,'carbon_daynight_lamps_flare'),(0x7507D0,'carbon_daynight_lamps_world')):
        assert hooks[address]['provider']==provider
        match = re.search(rf'void (?:carbon_orig_|f_){address:08X}\(.*?\n}}',source,re.S)
        assert match
        body = match[0].replace(f'carbon_orig_{address:08X}',f'f_{address:08X}',1)
        private_hooks.wrap(address,body,hooks[address])
        if address==0x7507D0:
            (out/'walker.inc').write_text(private_hooks.wrap(address,body,hooks[address]))
    production = (HERE/'private_runtime/carbon_daynight_lamps.h').read_text()
    feature = json.loads((HERE/'private_runtime/features/daynight_lamps.json').read_text())
    assert feature['bindings']['carbon_daynight_lamps.c']['sha256']==hashlib.sha256(production.encode()).hexdigest()
    (out/'fixture.c').write_text(HARNESS)
    variants = (
        ('good', production, 0),
        ('always-one', production.replace('fminf(1.0f, carbon_dn_lamps_dusk_gain * carbon_daynight_night())','1.0f'),1),
        ('wrong-scope', production.replace('carbon_dn_lamps_scope.depth && M8(M32(c->esp + 8) + 0x2c) == 13','0'),1),
        ('all-scene', production.replace('M8(M32(c->esp + 8) + 0x2c) == 13','1'),1),
        ('gain-one', production.replace('carbon_dn_lamps_dusk_gain = 2.0f','carbon_dn_lamps_dusk_gain = 1.0f'),1),
        ('no-restore', production.replace('M32(word) = saved;', '(void)saved;'),1),
        ('cones-native', production.replace('if (carbon_dn_lamps_level() > 0) { original(c); return; }', '{ original(c); return; }'),1),
        ('cars-native', production.replace('if (M32(c->esp) == CARBON_DN_CAR_FLARE_RET && M32(c->esp + 8)) {', 'if (0) {'),1),
    )
    results=[]
    for label, text, rc in variants:
        if label!='good':assert text!=production,label
        (out/'lamps.inc').write_text(text)
        binary=out/label
        command(['clang','-std=c11','-O1','-I',ROOT/'runtime','-I',HERE,'-I',out,out/'fixture.c','-o',binary])
        result=command([binary],rc)
        assert ('failures=0 ' in result)==(rc==0),result
        results.append(f'{label}: {result} (exit {rc})')
    (out/'lamps.inc').write_text(production)
    (out/'proof.txt').write_text('\n'.join(results)+'\n')
    print('\n'.join(results));return 0


if __name__=='__main__':
    sys.exit(main())
