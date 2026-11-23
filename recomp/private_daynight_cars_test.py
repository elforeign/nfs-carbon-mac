"""Car rig by day: Most Wanted's sun-relative rig through Carbon's light builder.

Good: key light dot sun 0.9848 at noon; fills 21.35 degrees below the
horizon; harmonics from Most Wanted's rig (stand-in sum 2.35x native); specular colours
(the only use Carbon's car pixel shader makes of them, pow 40 x 8) are
Carbon's own key .100/.095/.090 (luma 0.0959) on the key and 0 on the fills
(exit 0). Broken: the raw Most Wanted colours as on 67349b76 give key luma
0.7441 and fill colours .22-.45, the x8 white lobes on down-facing panels
(exit 1); kind 2 left in the rig gives harmonics equal to none (exit 1);
elevation instead of polar angle gives key dot 0.9225 (exit 1). Night, clock absent,
other flows, other rigs and the switch off leave the context byte-identical
to the native call. Default case: the switch reads On when unset, "on" or
"1", Off for "0" and "off": 5 cases, 0 failures; the old Off default (On only
for on/1) fails 1 (unset). The native builder is modelled from pinned translated
fragments (kind 0 spherical tail, kind 2/3 zeroing, 16-bit angle units).
Missing private inputs: exit 3. No game is launched.
"""
from pathlib import Path
import hashlib
import json
import os
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
    ('NFSC_40.c', '00746AB9:', '00746AE6:', 'PIN_KIND0'),
    ('NFSC_40.c', '00746BD2:', '00746BD5:', 'PIN_ZERO'),
    ('NFSC_39.c', '00739370:', '007393A7:', 'PIN_SPHERE'),
)


HARNESS = r'''
#include "host.h"
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include "rig.h"
uint8_t *G;
int diag_on;
static float night=1;
static unsigned checks, failures, calls;
static uint32_t seen_rig, seen_context;
#define CHECK(x) do {++checks; if(!(x)){++failures;fprintf(stderr,"CARS CHECK %d: %s\n",__LINE__,#x);}}while(0)
float carbon_daynight_night(void) { return M32(0x00A99BBCu)==6 ? night : 1; }
int carbon_daynight_d65_rig(float *sun, float *ambient) {
    if (M32(0x00A99BBCu) != 6) return 0;
    *sun = night ? .043f : 1;
    *ambient = night ? .08f : 1;
    return 1;
}
void diag_event(const char *f, ...) { (void)f; }
#include "cars.inc"
#define TOD 0x00200000u
#define RIG 0x00A6CC20u
static const float SUN[3]={.0661443f,-.474841f,.877583f};
/* 00746A00 as pinned: skip intensity 0; kind 0/1 = (sin b cos a, sin b sin a, cos b),
 * a = az+180, b = 90-el in 16-bit units (truncated /360); kinds 2/3 zero the
 * intensity in place but still count; colour = RGB x intensity. Harmonics are
 * a linear stand-in. The callee frame is clobbered below esp. */
static float angle(float degrees) {
    int units=(int)(degrees*65536.0f)/360;
    return (uint16_t)units*6.28318531f/65536;
}
static void native(Cpu *c) {
    uint32_t context=M32(c->esp+4), rig=M32(c->esp+8);
    ++calls;seen_rig=rig;seen_context=context;
    memset(G+c->esp-0x600,0xcd,0x600);
    if(!context){c->eax=0xffffffffu;c->esp+=4;return;}
    unsigned n=0;
    for(unsigned k=0;k<4;++k) {
        uint32_t s=rig+4+0x1c*k;
        if(MF32(s+0x18)==0) continue;
        float dir[3]={0};
        if(M32(s)<2) {
            float a=angle(MF32(s+4)+180), b=angle(90-MF32(s+8));
            dir[0]=sinf(b)*cosf(a);dir[1]=sinf(b)*sinf(a);dir[2]=cosf(b);
        } else if(M32(s)<4) MF32(s+0x18)=0;
        for(unsigned i=0;i<3;++i) {
            MF32(context+0x10+0x10*n+4*i)=MF32(s+0xc+4*i)*MF32(s+0x18);
            MF32(context+0x50+0x10*i+4*n)=dir[i];
        }
        MF32(context+0x1c+0x10*n)=0;
        ++n;
    }
    for(unsigned j=0;j<40;++j) {
        float sum=0;
        for(unsigned l=0;l<n;++l)
            sum+=MF32(context+0x10+0x10*l+4*(j%3))*MF32(context+0x50+0x10*(j%3)+4*l)*(j+1);
        MF32(context+0x130+4*j)=sum;
    }
    c->eax=1;c->esp+=4;
}
static Cpu frame(uint32_t context, uint32_t rig) {
    Cpu c={0};c.esp=0x10000;c.ebp=0xABCDEF;c.ebx=123;c.esi=456;c.edi=789;
    M32(c.esp)=0xDEAD0001u;M32(c.esp+4)=context;M32(c.esp+8)=rig;
    M32(c.esp+12)=0x31000;M32(c.esp+16)=0;M32(c.esp+20)=0x32000;M32(c.esp+24)=0;
    return c;
}
static uint8_t reference[0x1d0], native_rig[0xa0];
static void native_reference(uint32_t rig) {
    Cpu r=frame(0x40000,rig);memset(G+0x40000,0x5a,0x1d0);native(&r);
    memcpy(reference,G+0x40000,0x1d0);
}
/* One hooked call; returns the number of native calls. */
static unsigned hooked(uint32_t rig) {
    Cpu c=frame(0x30000,rig);memset(G+0x30000,0x5a,0x1d0);
    unsigned before=calls;
    carbon_daynight_cars(&c,native);
    CHECK(c.esp==0x10004&&c.ebp==0xABCDEF&&c.ebx==123&&c.esi==456&&c.edi==789&&c.eax==1);
    CHECK(M32(0x10004)==0x30000&&M32(0x10008)==rig&&M32(0x1000C)==0x31000&&M32(0x10014)==0x32000);
    CHECK(!memcmp(G+RIG,native_rig,0xa0));
    return calls-before;
}
static void unchanged(const char *what) {
    native_reference(RIG);
    unsigned n=hooked(RIG);
    CHECK(n==1&&seen_rig==RIG&&seen_context==0x30000);
    if(memcmp(G+0x30000,reference,0x1d0)){++failures;fprintf(stderr,"CARS %s differs from native\n",what);}
    ++checks;
}
int main(int argc, char **argv) {
    G=calloc(1,0xC00000);if(!G)return 2;
    memcpy(G+RIG,RIG_BYTES,0xa0);memcpy(native_rig,RIG_BYTES,0xa0);
    M32(0x00A99BBCu)=6;M32(0x00B77F34u)=TOD;memcpy(G+TOD+0x160,SUN,12);
    if (lighting_mode_d65()) {
        for (int midnight=0; midnight<=1; ++midnight) {
            night=midnight;
            CHECK(hooked(RIG)==1 && seen_rig!=RIG);
            float key = MF32(0x30010);
            CHECK(key>0 && key==MF32(0x30014) && key==MF32(0x30018));
            CHECK(fabsf(key-.095702f*(midnight?.043f:1))<1e-6f);
            for (unsigned k=0;k<3;++k) {
                uint32_t slot=seen_rig+0x10+0x1c*k;
                CHECK(MF32(slot)>0 && MF32(slot)==MF32(slot+4) && MF32(slot)==MF32(slot+8));
                float expected_gain=carbon_dn_cars_mw[k][5]*(midnight?(k?.08f:.043f):1);
                CHECK(fabsf(MF32(slot+12)-expected_gain)<1e-6f);
            }
        }
        printf("CARS D65 noon and midnight checks=%u failures=%u\n",checks,failures);
        free(G);return failures?1:0;
    }
    if(argc>1) { /* switch off: noon stays native */
        night=0;unchanged("switch off");
        printf("CARS off checks=%u failures=%u\n",checks,failures);
        return failures?1:0;
    }
    night=1;unchanged("night");
    night=0;M32(0x00A99BBCu)=3;unchanged("front end");M32(0x00A99BBCu)=6;
    M32(0x00B77F34u)=0;unchanged("clock absent");M32(0x00B77F34u)=TOD;
    memcpy(G+0x00A6D000u,RIG_BYTES,0xa0);
    {native_reference(0x00A6D000u);unsigned n=hooked(0x00A6D000u);
     CHECK(n==1&&seen_rig==0x00A6D000u&&!memcmp(G+0x30000,reference,0x1d0));}
    {Cpu c=frame(0,RIG);unsigned before=calls;carbon_daynight_cars(&c,native);
     CHECK(calls-before==1&&seen_rig==RIG&&c.eax==0xffffffffu&&c.esp==0x10004);}
    /* Noon: one call with the private rig into the real context. */
    night=0;
    unsigned n=hooked(RIG);
    CHECK(n==1&&seen_rig!=RIG&&seen_rig<0x10000&&seen_context==0x30000);
    float dot=0,luma=.299f*MF32(0x30010)+.587f*MF32(0x30014)+.114f*MF32(0x30018);
    for(unsigned i=0;i<3;++i) dot+=MF32(0x30050+0x10*i)*SUN[i];
    static const float want[3][3]={{.1f,.095f,.09f},{0,0,0},{0,0,0}};
    for(unsigned k=0;k<3;++k) for(unsigned i=0;i<3;++i)
        CHECK(fabsf(MF32(0x30010+0x10*k+4*i)-want[k][i])<1e-4f);
    CHECK(fabsf(dot-.9848f)<1e-3f);CHECK(fabsf(luma-.0959f)<1e-3f);
    /* Diffuse stays Most Wanted's: the stand-in harmonics carry the rig's
     * colours (MW .7055/.747/.83 + fills against Carbon's .10/.15/.05). */
    float hday=0,hnative=0;
    native_reference(RIG);
    for(uint32_t at=0x130;at<0x1d0;at+=4){float a;memcpy(&a,reference+at,4);hnative+=fabsf(a);hday+=fabsf(MF32(0x30000+at));}
    CHECK(hday>2*hnative);
    float fill=asinf(MF32(0x30074))*57.29578f, fill2=asinf(MF32(0x30078))*57.29578f;
    CHECK(fabsf(fill+21.35f)<.1f&&fabsf(fill2+21.35f)<.1f);
    uint8_t day[0x1d0];memcpy(day,G+0x30000,0x1d0);
    /* Dusk weight .5: private into scratch, then native; mixed. */
    native_reference(RIG);night=.5f;
    n=hooked(RIG);CHECK(n==2&&seen_rig==RIG&&seen_context==0x30000);
    for(uint32_t at=0x10;at<0x3c;at+=4) {
        float a,b;memcpy(&a,reference+at,4);memcpy(&b,day+at,4);
        CHECK(fabsf(MF32(0x30000+at)-(.5f*a+.5f*b))<1e-6f);
    }
    for(uint32_t at=0x130;at<0x1d0;at+=4) {
        float a,b;memcpy(&a,reference+at,4);memcpy(&b,day+at,4);
        CHECK(fabsf(MF32(0x30000+at)-(.5f*a+.5f*b))<1e-5f*(1+fabsf(a)+fabsf(b)));
    }
    for(unsigned k=0;k<3;++k) {
        float length=0;
        for(unsigned i=0;i<3;++i) length+=MF32(0x30050+0x10*i+4*k)*MF32(0x30050+0x10*i+4*k);
        CHECK(fabsf(length-1)<1e-4f);
    }
    printf("CARS key_dot=%.4f key_luma=%.4f fill_elevation=%.2f harmonics=%.2fx checks=%u failures=%u\n",
        dot,luma,fill,hnative>0?hday/hnative:0,checks,failures);
    free(G);return failures?1:0;
}
'''


def command(args, expected=0, env=None):
    r = subprocess.run(list(map(str, args)), capture_output=True, text=True, timeout=180, env=env)
    if r.returncode != expected:
        raise AssertionError(f'exit {r.returncode}, expected {expected}: {r.stdout[-2000:]} {r.stderr[-2000:]}')
    return r.stdout.strip()


DEFAULT = r'''
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include "cars_on.inc"
int main(int argc, char **argv) {
    if (argc > 1) setenv("NFS_DAYNIGHT_CARS", argv[1], 1);
    printf("%d\n", carbon_dn_cars_on());
    return 0;
}
'''


def default_case(out, function):
    """Unset/on/1 read On, 0/off read Off; returns the failure count."""
    (out/'cars_on.inc').write_text(function)
    (out/'default.c').write_text(DEFAULT)
    binary = out/'default'
    command(['clang', '-O1', '-I', out, out/'default.c', '-o', binary])
    expected = {None: '1', 'on': '1', '1': '1', '0': '0', 'off': '0'}
    return sum(command([binary] + ([value] if value is not None else []),
                       env={k: v for k, v in os.environ.items() if k != 'NFS_DAYNIGHT_CARS'}) != want
               for value, want in expected.items())


def fragment(source, start, end):
    a = source.index('    /* '+start)
    return source[a:source.index('    /* '+end, a)]


def main():
    base = HERE/'out/carbon-base'
    if not (base/'image.json').is_file() or not (base/'NFSC_40.c').is_file():
        print('SKIP: private car-light fixture needs the private image/build');return 3
    image = json.loads((base/'image.json').read_text())
    if not Path(image['exe']).is_file():
        print('SKIP: private car-light image unavailable');return 3
    sources = {name: (base/name).read_text() for name in ('NFSC_39.c', 'NFSC_40.c')}
    digests = {
        'PIN_KIND0': '3058bb2bf38d0d446cf7c522c6ac1a38039f1d5d2fe1f896fce7bd5e4696d082',
        'PIN_ZERO': '608d12fa21f1b08ccecbefaccdcbea7b5a0d92d0748bf5a3a54586abfe5f00a7',
        'PIN_SPHERE': 'aed706bf06d2a3963291dba0e407a6521c44139f8b614028df9404786977c2b5',
    }
    for name, start, end, key in PINS:
        assert hashlib.sha256(fragment(sources[name], start, end).encode()).hexdigest() == digests[key], key
    pe = PE(image['exe'], expected_sha256=image['sha256'])
    out = ignored_output(HERE/'out/carbon/daynight_cars_check')
    registry = out/'hooks';registry.mkdir(exist_ok=True)
    record = HERE/'private_runtime/hooks/daynight_cars.json'
    (registry/record.name).write_bytes(record.read_bytes())
    hooks = private_hooks.load_registry(pe, [(0x746A00, 0x747300, '')], registry)
    assert set(hooks) == {0x746A00} and hooks[0x746A00]['provider'] == 'carbon_daynight_cars'
    match = re.search(r'void (?:carbon_orig_|f_)00746A00\(.*?\n}', sources['NFSC_40.c'], re.S)
    assert match
    private_hooks.wrap(0x746A00, match[0].replace('carbon_orig_00746A00', 'f_00746A00', 1), hooks[0x746A00])
    production = (HERE/'private_runtime/carbon_daynight_cars.h').read_text()
    feature = json.loads((HERE/'private_runtime/features/daynight_cars.json').read_text())
    assert feature['bindings']['carbon_daynight_cars.c']['sha256'] == hashlib.sha256(production.encode()).hexdigest()
    start = production.index('static int carbon_dn_cars_on(void) {')
    function = production[start:production.index('\n}\n', start) + 3]
    on_rule = '!(setting && (!strcmp(setting,"0") || !strcasecmp(setting,"off")))'
    assert function.count(on_rule) == 1
    failures = default_case(out, function)
    old_default = default_case(out, function.replace(
        on_rule, 'setting && (!strcmp(setting,"1") || !strcasecmp(setting,"on"))'))
    print(f'default: failures={failures}; old Off default: failures={old_default}')
    if failures or old_default != 1:
        print('PRIVATE DAYNIGHT CARS FAIL: default'); return 1
    rig = pe.read(0xA6CC20, 0xA0)
    (out/'rig.h').write_text('static const uint8_t RIG_BYTES[0xa0]={%s};\n' % ','.join(str(b) for b in rig))
    (out/'fixture.c').write_text(HARNESS)
    variants = (
        ('good', production, 0),
        ('rawcolours', production.replace('    carbon_dn_cars_specular(G+(d < 1 ? scratch : context),G+rig);\n', ''), 1),
        ('kind2', production.replace('uint32_t kind = 0;', 'uint32_t kind = 2;'), 1),
        ('elevation', production.replace('acosf(fmaxf(-1,fminf(1,sun[2]/length)))',
                                         'asinf(fmaxf(-1,fminf(1,sun[2]/length)))'), 1),
    )
    env = dict(os.environ, NFS_DAYNIGHT_CARS='on')
    off = dict(os.environ, NFS_DAYNIGHT_CARS='off')
    results = []
    for label, text, rc in variants:
        if label != 'good': assert text != production, label
        (out/'cars.inc').write_text(text)
        binary = out/label
        command(['clang','-std=c11','-O1','-I',ROOT/'runtime','-I',HERE,'-I',out,out/'fixture.c','-o',binary])
        result = command([binary], rc, env)
        assert ('failures=0' in result) == (rc == 0), result
        results.append(f'{label}: {result} (exit {rc})')
        if label == 'good':
            results.append('neutral-d65: '+command([binary], 0, dict(env, NFS_WORLD_LIGHTING='neutral-d65')))
            results.append(f'off: {command([binary, "off"], 0, off)} (exit 0)')
    (out/'cars.inc').write_text(production)
    (out/'proof.txt').write_text('\n'.join(results)+'\n')
    print('\n'.join(results));return 0


if __name__ == '__main__':
    sys.exit(main())
