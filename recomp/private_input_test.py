"""Present -> shared scripts -> real Win32/DirectInput, headless native fixture.

Good: seq/frame 468 checks each, legacy 464, Xbox/PlayStation pad 313 each. Broken:
missing Present scheduling / quarantined sequence fail check 443; dropped pad
buttons fail check 303 (all exit 1). MW-only step exits 2. No guest image,
window, Metal device, controller hardware or desktop events. Absent build: SKIP 3.
Raw positional transport: good 138 checks / 0 failures; broken aliases,
forced full pressure, and missing digital promotion fail at checks 1/37/23
(one failure each, exit 1). Fractional pressures and all three selections agree.
"""
import json
import os
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from build_private import ignored_output
sys.path.insert(0, str(HERE / "private_runtime"))
from layers import selected_source
from private_input import verify_input
from private_render import body, replace_body


HARNESS = r'''
#include "host.h"
#include <stdlib.h>
#include <stdarg.h>
#include <sys/mman.h>
const uint32_t guest_func_addr[]={0};void (*const guest_func_ptr[])(Cpu*)={0};const unsigned guest_func_count=0;const uint32_t speed_entry=0;
/* This host-only fixture must never enter native startup completion. */
void f_0059B1B0(Cpu *c){(void)c;abort();}
const char speed_exe_fingerprint[]="",speed_exe_sha256[]="",speed_exe_region_sha256[4][65]={{0}};
const struct ExeRegion {const char *name;uint32_t rva,size;} speed_exe_regions[3]={{0}};
const struct {uint32_t slot;const char *name;} speed_imports[]={{0,0}};const unsigned speed_import_count=0;
extern void threads_init(void);extern int win32_dinput(Cpu*,const char*);
extern void user32_script(uint64_t,uint64_t);
static unsigned checks,downs,ups,chars,presents;
static uint32_t hwnd;
static uint64_t fake_ns=1000000000ull;
uint64_t private_input_ticks(void){return fake_ns;}
#define CHECK(x) do{++checks;if(!(x)){fprintf(stderr,"INPUT CHECK %u line %d failed: %s\n",checks,__LINE__,#x);exit(1);}}while(0)
static uint32_t api(Cpu*c,int(*fn)(Cpu*,const char*),const char*name,int n,...){c->esp=0x100000;M32(c->esp)=0xfeed;va_list ap;va_start(ap,n);for(int i=0;i<n;i++)M32(c->esp+4+4*i)=va_arg(ap,uint32_t);va_end(ap);CHECK(fn(c,name));CHECK(c->esp==0x100004+4*(uint32_t)n);return c->eax;}
static uint32_t invoke(Cpu*c,uint32_t self,unsigned slot,int n,...){c->esp=0x100000;M32(c->esp)=0xfeed;M32(c->esp+4)=self;va_list ap;va_start(ap,n);for(int i=1;i<n;i++)M32(c->esp+4+4*i)=va_arg(ap,uint32_t);va_end(ap);dispatch(c,M32(M32(self)+4*slot));CHECK(c->esp==0x100004+4*(uint32_t)n);return c->eax;}
static int wndproc(Cpu*c){uint32_t msg=arg(c,1);if(msg==0x100){CHECK(arg(c,0)==hwnd&&arg(c,2)==13);CHECK(((arg(c,3)>>16)&255)==0x1c);++downs;}if(msg==0x101){CHECK(arg(c,0)==hwnd&&arg(c,2)==13);CHECK((arg(c,3)>>30)==3);++ups;}if(msg==0x102){CHECK(arg(c,2)==13);++chars;}RET(1,4);}
static struct {uint64_t frames,frame_draws;} dev;
static void fixture_render_present(void){++presents;}
static void fixture_diag_frame(uint64_t f,uint64_t d){(void)f;(void)d;}
static void fixture_present(void) PRESENT_BODY
static void messages(Cpu*c){while(api(c,win32_user32,"PeekMessageA",5,0x6000u,0u,0u,0u,1u))api(c,win32_user32,"DispatchMessageA",1,0x6000u);}
int main(int argc,char**argv){CHECK(argc==2);G=mmap(NULL,1ull<<32,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANON,-1,0);CHECK(G!=MAP_FAILED);threads_init();Cpu c={0};c.fs_base=0x7000;
 M32(0x3000)=48;M32(0x3008)=host_fn(wndproc,"synthetic input window");uint32_t atom=api(&c,win32_user32,"RegisterClassExA",1,0x3000u);CHECK(atom!=0);
 hwnd=api(&c,win32_user32,"CreateWindowExA",12,0u,atom,0u,0u,0u,0u,640u,480u,0u,0u,0u,0u);CHECK(hwnd!=0);messages(&c);
 CHECK(api(&c,win32_dinput,"DirectInput8Create",5,0u,0x800u,0u,0x4000u,0u)==0);uint32_t input=M32(0x4000);
 M32(0x4100)=!strcmp(argv[1],"pad")?0x6f1d2b70:0x6f1d2b61;M16(0x4104)=0xd5a0;M16(0x4106)=0x11cf;const unsigned char tail[]={0xbf,0xc7,0x44,0x45,0x53,0x54,0,0};memcpy(G+0x4108,tail,8);
 CHECK(invoke(&c,input,3,4,0x4100u,0x4004u,0u)==0);uint32_t device=M32(0x4004);CHECK(device!=0);CHECK(invoke(&c,device,7,1)==0);
 int pad=!strcmp(argv[1],"pad"), legacy=!strcmp(argv[1],"legacy");
 // Hundreds of Presents at the same host time cannot consume a seq wait.
 if(!legacy){for(int k=0;k<100;k++){dev.frame_draws=9;fixture_present();}CHECK(downs==0);CHECK(invoke(&c,device,9,3,272u,0x5000u)==0);CHECK(pad?M8(0x5030)==0:M8(0x501c)==0);}
 unsigned key_samples=0,buffer_down=0,buffer_up=0,a_samples=0,b_samples=0,axis_samples=0,trigger_samples=0,full_triggers=0;
 for(int k=0;k<70;k++){
  fake_ns+=16666667;dev.frame_draws=9;fixture_present();
  memset(G+0x5000,0,300);CHECK(invoke(&c,device,9,3,pad?272u:256u,0x5000u)==0);
  if(pad){if(M8(0x5030))++a_samples;if(M8(0x5031))++b_samples;if(M32(0x5000)>48000)++axis_samples;if(M32(0x5008)>40000&&M32(0x5014)>56000&&M32(0x5008)<65535)++trigger_samples;if(M32(0x5008)==65535&&M32(0x5014)==65535){CHECK(!M8(0x503a)&&!M8(0x503b));++full_triggers;}}
  else{if(M8(0x501c))++key_samples;M32(0x5200)=4;CHECK(invoke(&c,device,10,5,16u,0x5300u,0x5200u,0u)==0);for(uint32_t j=0;j<M32(0x5200);j++){CHECK(M32(0x5300+16*j)==0x1c);if(M32(0x5304+16*j)==0x80)++buffer_down;else if(M32(0x5304+16*j)==0)++buffer_up;else CHECK(0);}}
  messages(&c);
 }
 if(pad){CHECK(a_samples==3);CHECK(b_samples==3);CHECK(axis_samples==3);CHECK(trigger_samples==3);CHECK(full_triggers==3);CHECK(!M8(0x5030)&&!M8(0x5031));CHECK(M32(0x5000)==32768&&M32(0x5008)==32768&&M32(0x5014)==32768);}
 else{CHECK(key_samples==4);CHECK(downs==1&&ups==1&&chars==1);CHECK(buffer_down==1&&buffer_up==1);CHECK((api(&c,win32_user32,"GetKeyState",1,13u)&0x8000)==0);}
 CHECK(presents==dev.frames);printf("PRIVATE INPUT PASS %s checks=%u keys=%u messages=%u/%u/%u buffer=%u/%u pad=%u/%u/%u/%u\n",argv[1],checks,key_samples,downs,ups,chars,buffer_down,buffer_up,a_samples,b_samples,axis_samples,trigger_samples);return 0;}
'''


def build(root, folder, mutant):
    dst = root / 'runtime'
    present = body(selected_source(dst / 'd3d9.m'), 'present')
    if mutant == 'scheduler':
        assert present.count('user32_script(dev.frames,draws);') == 1
        present = present.replace('user32_script(dev.frames,draws);', '')
    present = present.replace('render_present()', 'fixture_render_present()')
    present = present.replace('diag_frame(', 'fixture_diag_frame(')
    harness = folder / 'fixture.c'
    harness.write_text(HARNESS.replace('PRESENT_BODY', present))
    user32 = selected_source(dst / 'user32.m')
    user32 = user32.replace('#include "carbon_pad_delivery.h"', (dst/'carbon_pad_delivery.h').read_text())
    if mutant == 'quarantine':
        user32 = replace_body(user32, 'script_seq', '{}')
    if mutant == 'pad':
        user32 = replace_body(user32, 'carbon_pad_deliver', '{ st->buttons=0; }')
    if mutant == 'frame_clock':
        assert user32.count('real_frame >= strtoull(tok + 6, NULL, 10)') == 1
        user32 = user32.replace('real_frame >= strtoull(tok + 6, NULL, 10)', 'frame >= strtoull(tok + 6, NULL, 10)')
    source = folder / 'fixture_user32.m'
    source.write_text(user32)
    flags = ['-O1', '-g', '-w', '-fsanitize=address,undefined',
             '-I', str(dst), '-I', str(HERE), '-I', str(root),
             '-DNFS_GAME=2', '-I', str(HERE.parent / 'runtime')]
    sources = [(harness, 'fixture.o', []),
               (source, 'user32.o', ['-fobjc-arc', '-Dhost_ticks=private_input_ticks']),
               (dst / 'boot.c', 'boot.o', ['-Dmain=private_boot_main'])]
    for path, obj, extra in sources:
        r = subprocess.run(['clang', *flags, *extra, '-c', str(path), '-o', str(folder / obj)], capture_output=True, text=True)
        if r.returncode:
            raise RuntimeError(r.stderr[-3000:])
    command = json.loads((root / 'link_command.json').read_text())
    new = []; i = 0
    while i < len(command):
        arg = command[i]
        if arg == '-o':
            new += ['-o', str(folder / 'test')]; i += 2; continue
        if arg.endswith('/boot.c.o'): new.append(str(folder / 'boot.o'))
        elif arg.endswith('/user32.m.o'): new.append(str(folder / 'user32.o'))
        elif arg.endswith('/imports.c.o'): pass
        elif arg.endswith('.a') and Path(arg).parent == root: new.append(str(folder / 'fixture.o'))
        else: new.append(arg)
        i += 1
    new.append('-fsanitize=address,undefined')
    r = subprocess.run(new, capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(r.stderr[-3000:])
    return folder / 'test'


def layout_regression(out, source, delivery):
    """Raw positional transport is independent of the selected guest recipe."""
    selected=body(delivery,'carbon_pad_deliver')
    native=body(source,'pad_native')
    fixture=r'''#include "host.h"
#include "carbon_pad_layout.h"
#include <stdlib.h>
int diag_on; static int layout; static struct {int context;} carbon_pad_guards[2];
enum {P_CROSS,P_CIRCLE,P_SQUARE,P_TRIANGLE,P_L1,P_R1,P_CREATE,P_OPTIONS,P_L3,P_R3,P_L2,P_R2};
CarbonPadLayoutChoice carbon_pad_layout_resolve(unsigned pad) { (void)pad;return (CarbonPadLayoutChoice){layout,CARBON_LAYOUT_AUTOMATIC,PAD_KIND_OTHER}; }
static uint32_t carbon_pad_filter(int pad,PadState *state,uint32_t physical) { (void)pad;(void)state;return physical; }
void diag_event(const char*f,...){(void)f;}
static void pad_native(PadState *st,uint32_t phys) /* NATIVE_BODY */
static void carbon_pad_deliver(int idx,PadState *st,uint32_t phys) /* DELIVERY_BODY */
static unsigned checks;
#define CHECK(v) do{++checks;if(!(v)){fprintf(stderr,"LAYOUT CHECK %u failed: %s\n",checks,#v);return 1;}}while(0)
int main(void){
 const float pressures[]={0,.25f,.49f,.51f,.75f,1};
 for(layout=0;layout<3;++layout) {
  for(unsigned i=0;i<16;++i) { PadState s={0};uint32_t physical=1u<<i;
   carbon_pad_deliver(0,&s,physical);CHECK(s.buttons==(physical&~((1u<<P_L2)|(1u<<P_R2))));CHECK(s.native==1);
   if(i==P_L2)CHECK(s.lt==1);if(i==P_R2)CHECK(s.rt==1);
  }
  for(unsigned i=0;i<6;++i) {PadState s={0};s.lt=pressures[i];s.rt=pressures[5-i];
   uint32_t physical=(s.lt>0?1u<<P_L2:0)|(s.rt>0?1u<<P_R2:0);
   carbon_pad_deliver(0,&s,physical);CHECK(s.lt==pressures[i]&&s.rt==pressures[5-i]);CHECK(!s.buttons);
  }
 }
 printf("PRIVATE RAW TRANSPORT PASS checks=%u\n",checks);return 0;}
'''
    for broken in (None,'aliases','pressure','digital'):
        text=selected
        if broken=='aliases':
            assert 'pad_native(st, phys);' in text
            text=text.replace('pad_native(st, phys);','st->buttons=(phys&1u)<<1;st->native=0;')
        elif broken=='pressure':
            assert text.count('&& st->lt == 0')==1 and text.count('&& st->rt == 0')==1
            text=text.replace(' && st->lt == 0','').replace(' && st->rt == 0','')
        elif broken=='digital':
            text=text.replace('st->lt = 1;', 'st->lt = 0;').replace('st->rt = 1;', 'st->rt = 0;')
        path=out/('layout_'+(broken or 'good')+'.c');binary=path.with_suffix('')
        path.write_text(fixture.replace('/* DELIVERY_BODY */',text,1).replace('/* NATIVE_BODY */',native,1))
        r=subprocess.run(['clang','-g','-fsanitize=address,undefined','-I',str(HERE),'-I',str(HERE.parent/'runtime'),'-I',str(HERE/'private_runtime'),str(path),'-o',str(binary)],capture_output=True,text=True)
        if r.returncode:raise RuntimeError(r.stderr[-2000:])
        r=subprocess.run([str(binary)],capture_output=True,text=True)
        print(('broken '+broken if broken else 'raw transport')+': '+(r.stdout+r.stderr).strip())
        assert r.returncode==(1 if broken else 0)
        if broken:assert 'LAYOUT CHECK' in r.stderr


def main():
    root = HERE / 'out/carbon'
    # A copied link manifest is not proof of a build in this checkout.
    build_root=root
    if not all((build_root/name).is_file() for name in
               ('link_command.json','NFSC.a','runtime/disabled_providers.m.o')):
        print('SKIP: private runtime build absent for this checkout');return 3
    command=json.loads((build_root/'link_command.json').read_text())
    archives=[Path(arg).resolve() for arg in command if arg.endswith('/NFSC.a')]
    assert len(archives)==1, 'private runtime guest archive entry missing or ambiguous'
    if archives[0] != (build_root/'NFSC.a').resolve():
        print('SKIP: private runtime link belongs to another checkout');return 3
    inventory = json.loads((root / 'runtime_isolation.json').read_text())
    verify_input(inventory)
    inventory['user32.m'].append({'name': 'script_seq'})
    try: verify_input(inventory)
    except ValueError: print('INPUT REQUIRED BODY PASS: disabled scheduler rejected')
    else: raise AssertionError('disabled scheduler accepted')
    out = ignored_output(root / 'input_test')
    layout_regression(out,selected_source(root/'runtime/user32.m'),(root/'runtime/carbon_pad_delivery.h').read_text())
    for mutant in ('good', 'scheduler', 'quarantine', 'pad', 'frame_clock'):
        folder = out / mutant; folder.mkdir(exist_ok=True)
        binary = build(root, folder, mutant)
        cases = ('seq', 'frame', 'legacy', 'pad', 'pad_ps', 'unsupported') if mutant == 'good' else ('pad',) if mutant == 'pad' else ('frame',) if mutant == 'frame_clock' else ('seq',)
        for case in cases:
            mode = 'pad' if case == 'pad_ps' else case
            spec = {'seq': 'seq:wait:2,RETURN', 'frame': 'seq:frame:103,RETURN', 'legacy': '3:RETURN',
                    'pad': 'seq:wait:2,pad:1:3,wait:2,padraw:2:3,wait:2,padaxis:lx=0.5:3,wait:2,padtriggers:0.25/0.75:3,wait:2,pad:3072:3',
                    'unsupported': 'seq:sim:1'}[mode]
            env = {**os.environ, 'BOOT_HEADLESS': '1', 'BOOT_KEYS': spec,
                   'BOOT_PAD': 'sim:dualsense' if case == 'pad_ps' else 'sim:xbox', 'BOOT_USERDATA': str(folder / 'userdata'),
                   'NFS_PAD_LAYOUT': 'playstation',
                   'NFS_AUDIO': 'null', 'NFS_RUMBLE': 'off', 'NFS_PAD_TRIGGERS': 'off', 'NFS_PAD_LIGHT': 'off'}
            r = subprocess.run([str(binary), mode], capture_output=True, text=True, env=env, timeout=30)
            (folder / (case + '.log')).write_text(r.stdout + r.stderr)
            expected = 2 if case == 'unsupported' else 0 if mutant == 'good' else 1
            print(f'{mutant}/{case}: exit={r.returncode} ' + (r.stdout.strip() or r.stderr.strip().splitlines()[-1]))
            if r.returncode != expected:
                raise RuntimeError(r.stderr[-3000:])
            if mutant in ('scheduler', 'quarantine'): assert 'key_samples==4' in r.stderr
            if mutant == 'pad': assert 'a_samples==3' in r.stderr
            if mutant == 'frame_clock': assert 'key_samples==4' in r.stderr
            if case == 'unsupported': assert 'unsupported MW script step sim:1' in r.stderr
    print('PRIVATE INPUT REGRESSION PASS'); return 0


if __name__ == '__main__':
    sys.exit(main())
