"""Carbon keyboard adapter executes native validation/edit/accept/cancel bodies.
Dependencies: carbon_addons_host_text.c onscreen_keyboard.c "addons_host_text.json".
No emulation, window or game. Begin witnesses bind the archive hook to the image.
Good 66 checks / 0 failures; original missing bridge 41 / 36, missing
generation invalidation 67 / 2. Controller ownership has an independent control. Native accept=1 and cancel=2; both original=0.
"""
from pathlib import Path
import re, subprocess, sys, tempfile
ROOT=Path(__file__).resolve().parents[1];RT=ROOT/'runtime';PRIVATE=ROOT/'recomp/private_runtime'
FUNCTIONS=['00570340','005702E0','00570310','005BAE30','005836C0','00583760','005BAD00','005C5260','005A0030','005A00B0','00570250']
HARNESS=r'''
#include "funcs.h"
#include "host.h"
#include "onscreen_keyboard.h"
#include <stdlib.h>
#include <stdio.h>
static int failures,checks,physical_input=1,menu,accepted,cancelled;
static uint64_t ticks;
uint8_t *G;
int diag_on;
#define CHECK(x) do{++checks;if(!(x)){++failures;fprintf(stderr,"FAIL %d %s\n",__LINE__,#x);}}while(0)
int prompts_last_input(void){return physical_input;}
void prompts_input(int p){physical_input=p;}
int portmenu_is_open(void){return menu;}
uint64_t host_ticks(void){return ticks;}
void diag_event(const char *fmt,...){(void)fmt;}
void bad_jump(Cpu *c,uint32_t t){(void)c;fprintf(stderr,"jump %x\n",t);exit(2);}
void abi_violation(Cpu *c,uint32_t fn,uint32_t b,uint32_t s,uint32_t i,uint32_t p,uint32_t sp){(void)c;(void)b;(void)s;(void)i;(void)p;(void)sp;fprintf(stderr,"ABI %x\n",fn);exit(2);}
void f_00471840(Cpu *c){uint32_t s=arg(c,0),n=0;while(M16(s+2*n))++n;c->eax=n;c->esp+=4;}
void f_005AFF30(Cpu *c){(void)c;}
void f_006A1590(Cpu *c){(void)c;}
void f_005F77C0(Cpu *c){c->esp+=8;}
void f_005F2960(Cpu *c){unsigned message=arg(c,0);if(message==0xDA5B8712)++accepted;else if(message==0xC9D30688)++cancelled;else CHECK(0);c->esp+=20;}
void dispatch(Cpu *c,uint32_t f){CHECK(f==0x00570250);f_00570250(c);}
#include "native.inc"
uint32_t call_guest(Cpu *c,uint32_t f,int n,const uint32_t *args){
 c->esp-=128+4*n;M32(c->esp)=0;for(int i=0;i<n;i++)M32(c->esp+4+4*i)=args[i];
 switch(f){case 0x570340:f_00570340(c);break;case 0x5C5260:f_005C5260(c);break;case 0x5A00B0:f_005A00B0(c);break;case 0x5A0030:f_005A0030(c);break;case 0x5BAD00:f_005BAD00(c);break;default:CHECK(0);}return c->eax;
}
#include "onscreen_keyboard.c"
#include "carbon_addons_host_text.c"
static Cpu cpu(void){return (Cpu){.esp=0x800000,.cw=0x37f};}
static void pass(void){Cpu c=cpu();osk_pass(&c);}
static void original_begin(Cpu *c){(void)c;M32(TEXT_HOST+0x27C)=0x100000;}
static void begin(unsigned type,unsigned limit,const char *initial){
 M32(0x100000)=0;M32(0x100004)=type;M32(0x100008)=0x110000;M32(0x10000C)=156;M32(0x100010)=limit;M32(0x100018)=0;
 unsigned n=0;do{M16(0x110000+2*n)=initial[n];}while(initial[n++]);M32(0x10001C)=n-1;
 M32(TEXT_HOST)=0x120000;M32(0x120000)=0x570250;M32(TEXT_HOST+0x280)=31;
 Cpu c=cpu();c.ecx=TEXT_HOST;carbon_addons_host_text_begin(&c,original_begin);pass();
}
static void event(int action,unsigned ch){osk_queue(osk_capture()->generation,action,ch);pass();}
static void text(const char *expected){CHECK(osk_capture()->active);CHECK(osk_capture()->length==strlen(expected));CHECK(!strcmp(osk_capture()->text,expected));}
int main(void){
 G=calloc(1,0x1000000);CHECK(G!=NULL);M32(0xA97A78)=0x200000;M32(0x200000)=0x210000;M32(0x210000+0xE0)=0x220000;M32(0x220004)=0;
 osk_pad(0,0,0,0,0,0,0,0,1,0);begin(6,7,"");CHECK(osk_visible());
 for(const char *p="padtestextra";*p;p++)event(OSK_TYPE,*p);text("PADTEST");
 event(OSK_DELETE,0);text("PADTES");event(OSK_TYPE,'@');text("PADTES");
 event(OSK_TYPE,'T');text("PADTEST");event(OSK_ACCEPT,0);CHECK(accepted==1 && !osk_capture()->active);
 begin(4,20,"a@b");text("a@b");CHECK(osk_capture()->allowed['@']);CHECK(!osk_capture()->allowed['!']);
 uint64_t old=osk_capture()->generation;begin(6,20,"NEXT");osk_queue(old,OSK_TYPE,'Z');pass();text("NEXT");
 event(OSK_CANCEL,0);CHECK(cancelled==1 && !osk_capture()->active);
 begin(2,20,"secret");text("******");event(OSK_CANCEL,0);CHECK(cancelled==2);
 begin(6,20,"ABCDEF");M32(0x10001C)=2;pass();text("ABCDEF");event(OSK_CLEAR,0);text("");
 begin(6,20,"OWNER");int owner=osk_capture()->owner;
 osk_pad(1,1,0,0,0,0,0,0,1,1);pass();CHECK(osk_capture()->owner==owner);text("OWNER");
 begin(6,20,"FOCUS");physical_input=0;event(OSK_TYPE,'X');physical_input=1;pass();text("FOCUS");
 printf("native text: %d checks, %d failures; accept=%d cancel=%d\n",checks,failures,accepted,cancelled);free(G);return failures?1:0;
}
'''

def main():
    functions={}
    for p in (ROOT/'recomp/out/carbon').glob('NFSC_*.c'):
        text=p.read_text()
        for name in FUNCTIONS:
            found=re.search(r'void f_'+name+r'\(Cpu \*restrict c\) \{.*?\n\}',text,re.S)
            if found:functions[name]=found[0]
    if set(functions)!=set(FUNCTIONS):print('SKIP: translated Carbon functions missing');return 3
    assert all('untranslated(' not in s for s in functions.values())
    with tempfile.TemporaryDirectory(prefix='private-addons-text-') as td:
        d=Path(td);(d/'native.inc').write_text('\n'.join(functions[n] for n in FUNCTIONS))
        adapter=(PRIVATE/'carbon_addons_host_text.c').read_text()
        for name,code in [('good',adapter),('original-no-bridge',adapter.replace('if (!field) return 0;','if (1) return 0;')),('stale-generation',adapter.replace('carbon_addons_host_text_restart();','(void)0;').replace('++text_epoch;','(void)0;')),('ownership',adapter)]:
            bridge=(RT/'onscreen_keyboard.c').read_text()
            if name=='ownership':bridge=bridge.replace('        next.owner = game.owner;', '        (void)game.owner;')
            (d/'onscreen_keyboard.c').write_text(bridge)
            (d/'carbon_addons_host_text.c').write_text(code);src=d/'text.c';src.write_text(HARNESS);exe=d/'text'
            build=subprocess.run(['clang','-O1','-g','-fsanitize=address,undefined','-DNFS_GAME=2','-I'+str(d),'-I'+str(PRIVATE),'-I'+str(RT),'-I'+str(ROOT/'recomp'),'-I'+str(ROOT/'recomp/out/carbon'),str(src),str(RT/'text_fit.c'),'-o',str(exe)],capture_output=True,text=True)
            assert not build.returncode,build.stderr[-3000:]
            run=subprocess.run([str(exe)],capture_output=True,text=True,timeout=30);print(name+': '+run.stdout.strip(),flush=True)
            assert run.returncode==(0 if name=='good' else 1),run.stderr[-2500:]
    print('PRIVATE ADDONS TEXT PASS');return 0
if __name__=='__main__':sys.exit(main())
