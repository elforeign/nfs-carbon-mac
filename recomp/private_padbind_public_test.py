"""Table-free layouts through the production resolver and native PC evaluator.

The console includes are absent from every include search path. The fixture
uses translated defaults/evaluation and the actual binding hook; no emulator,
device or GPU. Exit 3 without Carbon outputs. Original forced-PC and display-only
controls use a SHA-256-pinned original adapter fragment. Both must fail actual
bindings, even when selection/display is repaired. Good 790 checks / 0 failures;
original forced-PC 87/710 (76/410 bindings), display-only 76/710 (76/410
bindings). Setup flag with private tables present: 790 checks / 0 failures.
"""
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
PRIVATE = HERE / 'private_runtime'
TABLES = ('carbon_padbind_ps3.inc', 'carbon_padbind_x360.inc')
# Original public adapter at the existing include boundary; no console data.
ORIGINAL = '''typedef struct { unsigned type, object, mode; float low, high; } XboxSource;
typedef struct { int action; XboxSource source[2]; } XboxAction;
static const PadAction driving[5][13], shared[1], digital[1], menu[1];
static const XboxAction xbox_driving[12][24], xbox_menu[1];
static CarbonPadLayoutChoice carbon_padbind_pc_layout(unsigned pad) {
    CarbonPadLayoutChoice choice = carbon_pad_layout_resolve(pad);
    choice.layout = CARBON_LAYOUT_PC;
    return choice;
}
#define carbon_pad_layout_resolve carbon_padbind_pc_layout
'''
ORIGINAL_SHA = '18256c137650fa379dfcc2117ccff5d357737e139ca146c101ecdcb73436e6be'

# Only PC function identities and port-authored host stubs. No private table
# fixture dependency: this test can also run in an exported tree.
IMAGE_SHA = 'baaaaec33873d4ba7e4dbae6a5212049ffdcf9679a35d865d7625b4189952fd3'
NATIVE = {0x00689550: 'native_defaults', 0x00692240: 'native_evaluate',
          0x006924F0: 'native_rows', 0x006796D0: 'native_text',
          0x0067A340: 'f_0067A340', 0x004710B0: 'f_004710B0',
          **{a: f'f_{a:08X}' for a in (0x004A4380,0x004A43E0,0x004A0490,0x004A04E0,0x004A5700)},
          0x0049DBA0:'native_resolve', **{a:f'f_{a:08X}' for a in (0x004A4C00,0x004A4BA0,0x0049DBF0,0x0049DCC0)}}


def body(source, name):
    match = re.search(rf'^void {name}\(Cpu [^\n]+', source, re.M)
    assert match, name
    return source[match.start():source.index('\n}', match.end()) + 2]


HARNESS = r'''
/* Image-backed native functions and hardware-free cached input. */
#include "funcs.h"
#include "host.h"
#include "carbon_pad_state.h"
#include "settings.h"
#include <stdlib.h>
uint8_t *G;
static unsigned checks, failures, reached, capture_calls, pumps, originals[4];
static Cpu evaluated_cpu;
int diag_on;
const char *diag_dir;
static char layout_pref[32];
const char *app_pref(const char *key) { return !strcmp(key,"pad_layout") ? layout_pref : NULL; }
void app_pref_set(const char *key,const char *value) { (void)key;snprintf(layout_pref,sizeof layout_pref,"%s",value); }
Setting *settings_find(const char *key) { (void)key; return NULL; }
void settings_dump(const char *path) { (void)path; }
#include "carbon_pad_layout.c"
void diag_event(const char *fmt, ...) { (void)fmt; }
static int context, kinds[2] = {PAD_KIND_DUALSENSE, PAD_KIND_DUALSENSE};
#define DEVICE 0x100000u
#define OUTPUT 0x110000u
#define PREVIOUS 0x111000u
#define JOY(p) (0x120000u + 0x1000u*(p))
#define KEYBOARD 0x130000u
#define MOUSE 0x140000u
#define STACK 0x300000u
#define PROFILE 0x40000u
#define CONFIG_INDEX (PROFILE+0x24288)
#define CONFIG_ANALOG (PROFILE+0x24280)
static unsigned redraws, dirty;
static char heading[256];
#define CHECK(x) do { ++checks; if(!(x)) { if(failures<12) fprintf(stderr,"FAIL %d: %s\n",__LINE__,#x); ++failures; } } while(0)
static Cpu cpu(void) { return (Cpu){.ecx=DEVICE,.esp=STACK,.cw=0x37F}; }
int carbon_pad_context(void) { return context; }
int user32_pad_native(void) { return kinds[0]>=PAD_KIND_DUALSENSE && kinds[0]<=PAD_KIND_EDGE; }
int pad_identity_n(int p,char *name,size_t n) { (void)name;(void)n;return p<2?kinds[p]:0; }
void bad_jump(Cpu *c,uint32_t a) { (void)c;fprintf(stderr,"bad jump %x\n",a);abort(); }
void untranslated(Cpu *c,uint32_t a) { bad_jump(c,a); }
void host_import(Cpu *c,uint32_t a) {
    if(a==0x009C1444u) { c->eax=0;c->esp+=12; }
    else if(a==0x009C1448u) { c->eax=0;c->esp+=32; }
    else bad_jump(c,a);
}
void native_defaults(Cpu *c);
void carbon_padbind_defaults(Cpu *,void (*)(Cpu *));
void dispatch(Cpu *c,uint32_t a) {
    if(a==0x11111111u) { c->eax=c->ecx+0x234; c->esp+=4; }
    else if(a==0x11111112u) { c->eax=M8(KEYBOARD+0x234+arg(c,0))!=0; c->esp+=8; }
    else if(a==0x11111113u) {
        unsigned property=arg(c,0),out=arg(c,1),player=arg(c,2);
        CHECK(property==0x13A9 || property==0x13A7);CHECK(player==0);
        Cpu read=*c;M32(read.esp+4)=out;M32(read.esp+8)=player;
        if(property==0x13A9)f_004A43E0(&read);else f_004A4380(&read);
        c->eax=read.eax;c->esp+=24;
    }
    else if(a==0x11111114u) {
        unsigned property=arg(c,0),value=arg(c,1),player=arg(c,2);
        CHECK(player==0);CHECK(property==0x13A9 || property==0x13A7 || property==0x13A3);
        if(property==0x13A9 || property==0x13A7) {
            Cpu write=*c;M32(write.esp+4)=value;M32(write.esp+8)=player;
            if(property==0x13A9)f_004A4C00(&write);else f_004A4BA0(&write);
        }
        else dirty=value;
        c->eax=1;c->esp+=24;
    }
    else if(a==0x004A0490u)f_004A0490(c);
    else if(a==0x004A04E0u)f_004A04E0(c);
    else if(a==0x004A5700u)f_004A5700(c);
    else if(a==0x0058CC20u) { ++redraws;c->esp+=4; }
    else if(a==0x00578880u)f_00578880(c);
    else if(a==0x005A0910u) {
        CHECK(arg(c,1)==0x4E11CF90);snprintf(heading,sizeof heading,"%s",(char *)G+arg(c,2));c->esp+=4;
    }
    else if(a==0x00689550u) carbon_padbind_defaults(c,native_defaults);
    else if(a==0x0067A340u) f_0067A340(c);
    else bad_jump(c,a);
}
uint32_t call_guest(Cpu *c,uint32_t a,int n,const uint32_t *args) {
    unsigned sp=c->esp;
    for(int i=n-1;i>=0;--i) { c->esp-=4;M32(c->esp)=args[i]; }
    c->esp-=4;M32(c->esp)=0xFEEDF00D;dispatch(c,a);c->esp=sp;return c->eax;
}
/* Native defaults asks DirectInput whether the device has a POV. */
void f_0067A0F0(Cpu *c) { c->eax=1; c->esp+=8; }
void f_00679D20(Cpu *c) { ++pumps;c->esp+=4; }
void f_00680E50(Cpu *c) { ++capture_calls;c->esp+=4; }
void f_00731B30(Cpu *c) { (void)c;abort(); }
void f_00890F54(Cpu *c) { memcpy(G+arg(c,0),G+arg(c,1),arg(c,2));c->esp+=4; }
/* Localization/CRT imports are not the subject of the binding-name fixture. */
void f_00471200(Cpu *c) { snprintf((char *)G+arg(c,0),arg(c,2),"%s",(char *)G+arg(c,1));c->esp+=4; }
void f_00475C30(Cpu *c) { (void)c;abort(); }
void f_00578880(Cpu *c) { CHECK(arg(c,2)==0x74B98590);snprintf((char *)G+arg(c,0),arg(c,1),"Configuration");c->esp+=4; }
void f_00572B90(Cpu *c) { CHECK(arg(c,0)==0);c->eax=PROFILE;c->esp+=8; }
void f_00588EA0(Cpu *c) { (void)c;abort(); }
void f_00679310(Cpu *c) { c->eax=0;c->esp+=4; }
void f_006A1560(Cpu *c) { c->eax=0;c->esp+=12; }
void f_006A15A0(Cpu *c) { c->eax=0;c->esp+=32; }
static char *read_tokens;
void f_0058DB00(Cpu *c) {
    uint32_t out=arg(c,1); int n=snprintf((char *)G+out,32,"%u ",arg(c,0));
    c->eax=out+n;c->esp+=4;
}
void f_004727B0(Cpu *c) { c->eax=read_tokens&&*read_tokens; c->esp+=4; }
void f_00475F90(Cpu *c) {
    c->eax=(uint32_t)strtoul(read_tokens,&read_tokens,10);
    while(*read_tokens==' ')++read_tokens;c->esp+=4;
}
#include "native.inc"
int pad_count(void){return 1;}
int pad_read_n(int n,PadState *s){(void)n;memset(s,0,sizeof *s);return 0;}
#include "carbon_padguest.c"
#include "carbon_padbind.c"
static void original_defaults(Cpu *c) { ++originals[0];native_defaults(c); }
static void original_evaluate(Cpu *c) { ++originals[1];native_evaluate(c);evaluated_cpu=*c; }
static void original_rows(Cpu *c) { ++originals[2];native_rows(c); }
static void original_text(Cpu *c) { ++originals[3];native_text(c); }
static uint32_t record(unsigned a,unsigned slot) { return M32(0xA98704+8*a)+12*slot; }
static void binding(unsigned a,unsigned slot,unsigned t,unsigned d,unsigned o) {
    unsigned r=record(a,slot);M32(r)=t;M32(r+4)=d;M32(r+8)=o;
}
static void neutral(unsigned p) {
    unsigned cache=JOY(p)+0x234; memset(G+cache,0,0x230);
    for(unsigned i=0;i<6;++i) M32(cache+(i<3?4*i:0x20C+4*(i-3)))=32767;
    M32(cache+0x220)=0xFFFFFFFF;
}
static void setup(void) {
    layout_pref[0]=0;unsetenv("NFS_PAD_LAYOUT");
    memset(carbon_padbind_seen,0,sizeof carbon_padbind_seen);
    memset(carbon_padbind_remembered,0,sizeof carbon_padbind_remembered);
    memset(G+DEVICE,0,0x1900); memset(G+OUTPUT,0,0x2000);
    memset(G+0x91F418,0,0x1000); /* Wrong-image stride mutation sentinel. */
    M32(DEVICE+0x20)=OUTPUT; M32(DEVICE+0x1C)=PREVIOUS;
    M32(0xA98948)=2; M32(0xAB0AD0)=1;
    M32(0xA986F4)=KEYBOARD;M32(KEYBOARD)=0x150000;M32(0x15001C)=0x11111112;
    M32(0xA986FC)=MOUSE;M32(MOUSE)=0x151000;M32(0x151004)=0x11111111;
    memset(G+KEYBOARD+0x234,0,256); memset(G+MOUSE+0x234,0,0x230);
    for(unsigned p=0;p<2;++p) {
        M32(0xA986D0+4*p)=JOY(p); M32(JOY(p))=0x152000;
        M32(0x152004)=0x11111111;
        strcpy((char *)G+JOY(p)+0x114,"Controller (DualSense)"); neutral(p);kinds[p]=PAD_KIND_DUALSENSE;
    }
    /* Deliberately noncontiguous allocations distinguish Carbon's directory. */
    for(unsigned a=0;a<72;++a) {
        unsigned base=0x180000+((a*17)%72)*128;
        M32(0xA98700+8*a)=M32(0xA61C88+52*a);M32(0xA98704+8*a)=base;
        memcpy(G+base,G+0xA61C8C+52*a,24);
        for(unsigned p=0;p<2;++p) {
            memcpy(G+base+24+24*p,G+0xA61CA4+52*a,24);
            M32(base+28+24*p)=p;M32(base+40+24*p)=p;
        }
    }
    M32(0xA97BAC)=0;M32(0xA97A78)=0;
    M32(CONFIG_INDEX)=0;M8(CONFIG_ANALOG)=1;
    M32(0xA8AD4C)=0x160000;M32(0x160000)=0x161000;
    M32(0x161018)=0x11111113;M32(0x16101C)=0x11111114;
    redraws=dirty=0;
    context=CARBON_PAD_MENU;
}
static void defaults(unsigned p,int hooked) {
    Cpu c=cpu();M32(c.esp+4)=p;
    if(hooked) carbon_padbind_defaults(&c,original_defaults);else native_defaults(&c);
    CHECK(c.esp==STACK+8);
}
static void evaluate(int hooked) {
    Cpu c=cpu();if(hooked)carbon_padbind_evaluate(&c,original_evaluate);else native_evaluate(&c);
    CHECK(c.esp==STACK+4);
    if(hooked)CHECK(!memcmp(&c,&evaluated_cpu,sizeof c));
}
static float value(unsigned a) { return MF32(OUTPUT+4*a); }
static float oracle(unsigned a,unsigned slot) {
    Cpu c=cpu();M32(c.esp+4)=a;M32(c.esp+8)=slot;f_0067A340(&c);CHECK(c.esp==STACK+12);
    return (float)c.st[c.top];
}
'''

PROOF = r'''
static unsigned binding_checks, binding_failures;
#define BIND(x) do { ++binding_checks; if(!(x)) ++binding_failures; CHECK(x); } while(0)
static void button(unsigned p,unsigned b) { M32(JOY(p)+0x234+0xC+4*b)=128; }
static void pedal(unsigned p,unsigned axis,float pressure) {
    M32(JOY(p)+0x234+(axis==2?8:0x214))=(unsigned)lroundf(32767+pressure*32768);
}
static void near_value(unsigned action,float want) { BIND(fabsf(value(action)-want)<.001f); }
static void public_proof(void) {
    /* Each identity follows its own layout; explicit picks never change identity. */
    setup(); CHECK(carbon_pad_layout_get()==0);
    kinds[0]=PAD_KIND_OTHER; CHECK(carbon_pad_layout_get()==1);
    for(int pick=0;pick<3;++pick) {
        carbon_pad_layout_set(pick);CHECK(carbon_pad_layout_get()==pick);
        CHECK(kinds[0]==PAD_KIND_OTHER);
    }
    carbon_pad_layout_reset();CHECK(carbon_pad_layout_get()==1);
    for(int family=0;family<2;++family)for(int native=0;native<2;++native) {
        setup();kinds[0]=native?PAD_KIND_DUALSENSE:PAD_KIND_OTHER;
        carbon_pad_layout_set(family);M32(0xA98948)=1;
        unsigned char keyboard[72][24];
        for(unsigned a=0;a<72;++a)memcpy(keyboard[a],G+record(a,0),24);
        defaults(0,1);
        for(unsigned a=0;a<72;++a)BIND(!memcmp(keyboard[a],G+record(a,0),24));
        /* Independent manual positions, ordered by PC action name, not table order. */
        const unsigned actions[]={4,5,6,18,19,24,25,28};
        const unsigned ps[]={5,9,4,6,3,8,1,7}, xb[]={0,2,1,4,3,5,9,7};
        context=CARBON_PAD_DRIVING;
        for(unsigned i=0;i<8;++i) {
            neutral(0);button(0,family?xb[i]:ps[i]);evaluate(1);near_value(actions[i],1);
        }
        for(int step=0;step<=4;++step) {
            float gas=step*.25f,brake=(4-step)*.25f;
            neutral(0);pedal(0,5,gas);pedal(0,2,brake);evaluate(1);
            near_value(0,gas);near_value(1,brake);
        }
        /* Native rebinds remain effective on the next evaluation. */
        binding(0,2,2,0,12);neutral(0);button(0,12);evaluate(1);near_value(0,1);
        neutral(0);pedal(0,5,.5f);evaluate(1);near_value(0,0);
        /* Keyboard and another controller are never erased by the adapter. */
        binding(0,0,1,0,30);M8(KEYBOARD+0x234+30)=128;
        neutral(0);evaluate(1);near_value(0,1);M8(KEYBOARD+0x234+30)=0;
        defaults(0,1);context=CARBON_PAD_MENU;
        neutral(0);button(0,0);evaluate(1);near_value(37,1);near_value(38,0);
        neutral(0);button(0,family?1:3);evaluate(1);near_value(38,1);near_value(37,0);
        neutral(0);evaluate(1);near_value(37,0);near_value(38,0);
        /* Capture bypasses the overlay; no records are rewritten mid-capture. */
        context=CARBON_PAD_CAPTURE;
        unsigned char records[72];memcpy(records,G+record(0,0),72);
        carbon_pad_layout_set(1-family);evaluate(1);
        BIND(!memcmp(records,G+record(0,0),72));
        context=CARBON_PAD_MENU;neutral(0);evaluate(1);
        CHECK(carbon_pad_layout_get()==1-family);
        BIND(M32(record(0,2))==7 && M32(record(0,2)+8)==2);
    }
    /* Explicit PC uses the unmodified native controller defaults. */
    setup();carbon_pad_layout_set(2);defaults(0,1);context=CARBON_PAD_DRIVING;
    BIND(M32(record(0,2))==2 && M32(record(0,2)+8)==0);
    neutral(0);button(0,0);evaluate(1);near_value(0,1);
    /* Automatic live swaps reseed only this pad; pad one retains its identity. */
    setup();defaults(0,1);defaults(1,1);context=CARBON_PAD_MENU;
    unsigned char other[24];memcpy(other,G+record(0,4),24);
    kinds[0]=PAD_KIND_OTHER;neutral(0);evaluate(1);CHECK(carbon_pad_layout_get()==1);
    BIND(M32(record(4,2)+8)==0);BIND(!memcmp(other,G+record(0,4),24));
    kinds[0]=PAD_KIND_EDGE;evaluate(1);CHECK(carbon_pad_layout_get()==0);
    BIND(M32(record(4,2)+8)==5);BIND(!memcmp(other,G+record(0,4),24));
}
int main(int argc,char **argv) {
    if(argc!=2)return 2;G=calloc(1,0xC00000);if(!G)return 2;
    FILE *f=fopen(argv[1],"rb");if(!f)return 2;
    if(fread(G,1,0xC00000,f)!=0xC00000)return 2;fclose(f);
    public_proof();
    printf("public_padbind checks=%u failures=%u bindings=%u/%u\n",checks,failures,binding_failures,binding_checks);
    free(G);return failures?1:0;
}
'''


def main():
    base=HERE/'out/carbon-base'
    if not all((base/n).is_file() for n in ('image.json','table.c','funcs.h','NFSC.a')):
        print('SKIP: public native evaluator fixture needs Carbon outputs');return 3
    sys.path.insert(0,str(HERE))
    import recomp
    image=json.loads((base/'image.json').read_text())
    if not Path(image['exe']).is_file():
        print('SKIP: public native evaluator image absent');return 3
    pe=recomp.PE(image['exe'],expected_sha256=IMAGE_SHA)
    starts=[int(v.removesuffix('u'),16) for v in re.search(
        r'guest_func_addr\[\] = \{([^}]+)',(base/'table.c').read_text())[1].split(',')]
    native=[]
    for a,name in NATIVE.items():
        text=(base/f'NFSC_{starts.index(a)//800:02d}.c').read_text()
        # Registry's maintained name, shared with the existing full-table fixture.
        import private_hooks
        original=private_hooks.original_name(a)
        old=original if f'void {original}(' in text else f'f_{a:08X}'
        native.append(body(text,old).replace(old,name,1))
    memory=bytearray(0xC00000)
    for _,_,va,size,offset in pe.sections:
        memory[pe.base+va:pe.base+va+size]=pe.data[offset:offset+size]
    source=(PRIVATE/'carbon_padbind.c').read_text()
    resolver=(PRIVATE/'carbon_pad_layout.c').read_text()
    assert hashlib.sha256(ORIGINAL.encode()).hexdigest()==ORIGINAL_SHA
    port='#define CARBON_PADBIND_PORT 1\n#include "carbon_padbind_port.h"'
    assert source.count(port)==1
    old_adapter=source.replace(port,ORIGINAL).replace(
        '#define PADBIND_MENU_COUNT (sizeof menu / sizeof *menu)','#define PADBIND_MENU_COUNT 0')
    with tempfile.TemporaryDirectory(prefix='padbind-public-') as directory:
        tmp=Path(directory)
        # PRIVATE is deliberately never on the compiler include path.
        for path in PRIVATE.iterdir():
            if path.suffix in ('.h','.inc') and path.name not in TABLES:
                (tmp/path.name).write_bytes(path.read_bytes())
        (tmp/'native.inc').write_text('\n\n'.join(native)+'\n')
        (tmp/'image.bin').write_bytes(memory)
        (tmp/'fixture.c').write_text(HARNESS+PROOF)
        (tmp/'carbon_padguest.c').write_bytes((PRIVATE/'carbon_padguest.c').read_bytes())
        def execute(label,current,layout,expected,public=False):
            (tmp/'carbon_padbind.c').write_text(current)
            (tmp/'carbon_pad_layout.c').write_text(layout)
            binary=tmp/label
            args=['clang','-std=c11','-O0','-g','-fsanitize=address,undefined',
                  '-fno-sanitize-recover=all','-I',tmp,'-I',ROOT/'runtime','-I',HERE,'-I',base,
                  tmp/'fixture.c','-o',binary]
            if public:args.insert(1,'-DNFS_PUBLIC=1')
            result=subprocess.run(list(map(str,args)),capture_output=True,text=True)
            assert result.returncode==0,(label,result.stderr[-3000:])
            result=subprocess.run([binary,tmp/'image.bin'],capture_output=True,text=True)
            print(label+': '+result.stdout.strip(),flush=True)
            assert result.returncode==expected,(label,result.returncode,result.stderr[-2500:])
            counts=re.search(r'bindings=(\d+)/(\d+)',result.stdout)
            assert counts and (int(counts[1])>0 if expected else int(counts[1])==0)
        execute('table-free',source,resolver,0)
        execute('original-forced-pc',old_adapter,resolver.replace(
            '    Setting *row =','    choice.layout = CARBON_LAYOUT_PC;\n    Setting *row ='),1)
        execute('display-only',old_adapter,resolver,1)
        # Setup flag must select authored positions even in a private checkout.
        for name in TABLES:
            if (PRIVATE/name).is_file():(tmp/name).write_bytes((PRIVATE/name).read_bytes())
        execute('public-flag-with-optional-tables',source,resolver,0,public=True)
    print('private_padbind_public_test: PASS')
    return 0


if __name__=='__main__':
    sys.exit(main())
