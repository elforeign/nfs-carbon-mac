"""Native private Win32/translated SEH check without any game bytes.

Good: 123 notification, stdcall/SEH, diagnostic-off, SID/RNG and API checks pass.
Broken: pop only three RaiseException arguments -> same translated fixture fails check 6, exit 1.
Broken: zero RNG output -> check 113, exit 1.
"""
from pathlib import Path
import subprocess
import sys
import tempfile
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import build_all


class PE:
    base=0x400000;fingerprint='0'*64;sha256='0'*64
    imports={0x3000:'kernel32.dll!RaiseException'}
    def __init__(self):
        # Own synthetic SEH registration, one protected import, and restoration.
        self.code=bytes.fromhex('558bec6aff6800200000680012400064ff35000000006489250000000083ec1053565768002100006a046a006888136d40ff1500300000c745fcffffffff8b4df064890d000000005f5e5b8be55dc20400')
    def read(self,a,n):
        if 0x401000<=a<0x401000+len(self.code):return self.code[a-0x401000:a-0x401000+n]
        if 0x401100<=a<0x401106:return bytes.fromhex('b8ffffffffc3')[a-0x401100:a-0x401100+n]
        return b''


def main():
    pe=PE()
    with tempfile.TemporaryDirectory(prefix='private-win32-') as td:
        out=Path(td);result=build_all.build_image([(0x401000,0x401100,'seh'),(0x401100,0x401106,'filter')],pe,str(out),'fixture',mw_patches=False,jobs=1)
        assert result['compile_errors']==0
        native=out/'win32.c';fixture=out/'test.c'
        fixture.write_text(r'''#include "host.h"
#include <stdlib.h>
#include <stdarg.h>
#include <assert.h>
uint8_t *G;int diag_on,boot_trace;__thread uint32_t last_error;
static unsigned checks,events,frees,filter_calls;static char event[512];static int emulate_filter;
#define CHECK(v) do{++checks;if(!(v)){fprintf(stderr,"check %u line %d failed\n",checks,__LINE__);exit(1);}}while(0)
uint32_t diag_thread_id(void){return 7;}
void diag_event(const char*fmt,...){++events;va_list ap;va_start(ap,fmt);vsnprintf(event,sizeof event,fmt,ap);va_end(ap);}
static uint32_t alloc_next=0x10000;
uint32_t gmalloc(uint32_t n){uint32_t p=alloc_next;alloc_next+=(n+15)&~15;return p;}
void gfree(uint32_t p){CHECK(p>=0x10000);++frees;}
typedef struct {unsigned type;uint32_t private_ideal;} KObj;
#define K_THREAD 1
static KObj helper_thread={K_THREAD,32},other={2,32};static KObj *self;
static KObj*kget(uint32_t h){return h==0x42?&helper_thread:h==0x43?&other:NULL;}
#include "thread_ideal.h"
int private_win32_extra(Cpu*,const char*);
void f_00401000(Cpu*),f_00401100(Cpu*);
void untranslated(Cpu*c,uint32_t p){(void)c;(void)p;exit(9);}
void dispatch(Cpu*c,uint32_t p){(void)c;(void)p;exit(9);}
void host_import(Cpu*c,uint32_t slot){CHECK(slot==0x3000);CHECK(M32(c->fs_base)==0x7fec);
 if(emulate_filter){Cpu filter=*c;filter.esp=0x9000;f_00401100(&filter);CHECK(filter.eax==UINT32_MAX);CHECK(filter.esp==0x9004);++filter_calls;}
 CHECK(private_win32_extra(c,"RaiseException"));}
static uint32_t invoke(Cpu*c,const char*name,int n,...){c->esp=0x8000;M32(c->esp)=0xfeed;va_list ap;va_start(ap,n);for(int i=0;i<n;++i)M32(c->esp+4+4*i)=va_arg(ap,uint32_t);va_end(ap);CHECK(private_win32_extra(c,name));CHECK(c->esp==0x8004+4*(uint32_t)n);return c->eax;}
int main(void){G=calloc(1,1<<20);CHECK(G!=NULL);Cpu c={0};
 M32(0x2100)=0x1000;M32(0x2104)=0x2200;M32(0x2108)=UINT32_MAX;M32(0x210c)=0;strcpy((char*)G+0x2200,"synthetic thread");
 for(int k=0;k<2;++k){c=(Cpu){0};c.esp=0x8000;c.fs_base=0x5000;c.ebx=11;c.esi=22;c.edi=33;c.ebp=44;c.eax=55;M32(c.fs_base)=0x6000;M32(c.esp)=0xfeed;M32(c.esp+4)=0x777;diag_on=k;emulate_filter=k;events=0;f_00401000(&c);
 CHECK(c.esp==0x8008);CHECK(c.ebx==11&&c.esi==22&&c.edi==33&&c.ebp==44);CHECK(M32(c.fs_base)==0x6000);CHECK(M32(0x7ff8)==UINT32_MAX);CHECK(events==(unsigned)k);if(k)CHECK(strstr(event,"tid=7 name=synthetic thread"));}
 CHECK(filter_calls==1);
 c.esp=0x8000;M32(c.esp+4)=0xc0000005;M32(c.esp+8)=0;M32(c.esp+12)=4;M32(c.esp+16)=UINT32_MAX;Cpu before=c;CHECK(!private_win32_extra(&c,"RaiseException"));CHECK(!memcmp(&c,&before,sizeof c));
 M32(c.esp+4)=0x406d1388;M32(c.esp+12)=3;CHECK(!private_win32_extra(&c,"RaiseException"));M32(c.esp+12)=4;M32(c.esp+16)=0x2100;
 M32(0x210c)=1;CHECK(!private_win32_extra(&c,"RaiseException"));M32(0x210c)=0;M32(0x2100)=0x1001;CHECK(!private_win32_extra(&c,"RaiseException"));M32(0x2100)=0x1000;
 events=0;diag_on=0;M32(0x2104)=UINT32_MAX;invoke(&c,"RaiseException",4,0x406d1388u,0u,4u,0x2100u);CHECK(events==0);M32(0x2104)=0x2200;M32(0x2108)=123;diag_on=1;invoke(&c,"RaiseException",4,0x406d1388u,0u,4u,0x2100u);CHECK(strstr(event,"tid=123 "));
 CHECK(invoke(&c,"SetThreadIdealProcessor",2,0xfffffffeu,1u)==32);CHECK(invoke(&c,"SetThreadIdealProcessor",2,0xfffffffeu,32u)==1);
 CHECK(invoke(&c,"SetThreadIdealProcessor",2,0x42u,3u)==32&&helper_thread.private_ideal==3);self=&helper_thread;CHECK(invoke(&c,"SetThreadIdealProcessor",2,0xfffffffeu,2u)==3);self=NULL;
 CHECK(invoke(&c,"SetThreadIdealProcessor",2,0x43u,2u)==UINT32_MAX&&last_error==6);CHECK(invoke(&c,"SetThreadIdealProcessor",2,0x42u,33u)==UINT32_MAX&&last_error==87&&helper_thread.private_ideal==2);
 memset(G+0x2300,0xa5,256);M32(0x2400)=1;CHECK(!invoke(&c,"GetComputerNameA",2,0x2300u,0x2400u)&&last_error==111&&M32(0x2400)>1&&M8(0x2300)==0xa5);M32(0x2400)=256;
 CHECK(invoke(&c,"GetComputerNameA",2,0x2300u,0x2400u));CHECK(M32(0x2400)==strlen((char*)G+0x2300)&&M32(0x2400)<=15);CHECK(M8(0x2300+M32(0x2400)+1)==0xa5);
 memset(G+0x2300,0xa5,256);unsigned required=invoke(&c,"GetSystemDirectoryA",2,0x2300u,1u);CHECK(required>1&&M8(0x2300)==0xa5);CHECK(invoke(&c,"GetSystemDirectoryA",2,0x2300u,required)==required-1);CHECK(!strcmp((char*)G+0x2300,"C:\Windows\System32"));
 CHECK(!invoke(&c,"CoCreateGuid",1,0x2500u));CHECK((M8(0x2507)&0xf0)==0x40&&(M8(0x2508)&0xc0)==0x80);CHECK(invoke(&c,"CoCreateGuid",1,0u)==0x80070057u);
 M32(0x2500)=0x11223344;M16(0x2504)=0x5566;M16(0x2506)=0x7788;for(int k=0;k<8;k++)M8(0x2508+k)=0x90+k;
 CHECK(!invoke(&c,"UuidToStringA",2,0x2500u,0x2400u));CHECK(!strcmp((char*)G+M32(0x2400),"11223344-5566-7788-9091-929394959697"));CHECK(!invoke(&c,"RpcStringFreeA",1,0x2400u));CHECK(M32(0x2400)==0&&frees==1);
 CHECK(!invoke(&c,"UuidToStringA",2,0u,0x2400u));CHECK(!strcmp((char*)G+M32(0x2400),"00000000-0000-0000-0000-000000000000"));
 memset(G+0x2600,0,6);M8(0x2605)=5;
 CHECK(invoke(&c,"AllocateAndInitializeSid",11,0x2600u,2u,32u,545u,0u,0u,0u,0u,0u,0u,0x2610u));uint32_t sid=M32(0x2610);CHECK(M8(sid)==1&&M8(sid+1)==2&&M8(sid+7)==5&&M32(sid+8)==32&&M32(sid+12)==545);
 CHECK(invoke(&c,"CheckTokenMembership",3,0u,sid,0x2620u)&&M32(0x2620)==1);M32(sid+12)=999;CHECK(invoke(&c,"CheckTokenMembership",3,0u,sid,0x2620u)&&M32(0x2620)==0);CHECK(!invoke(&c,"CheckTokenMembership",3,0x99u,sid,0x2620u)&&last_error==6);CHECK(invoke(&c,"FreeSid",1,sid)==0);
 CHECK(!invoke(&c,"AllocateAndInitializeSid",11,0x2600u,9u,0u,0u,0u,0u,0u,0u,0u,0u,0x2610u)&&M32(0x2610)==0);
 CHECK(invoke(&c,"CryptAcquireContextA",5,0x2700u,0u,0u,1u,0xf0000000u));uint32_t provider=M32(0x2700);CHECK(provider!=0);memset(G+0x2800,0,33);M8(0x2820)=0xa5;
 CHECK(invoke(&c,"CryptGenRandom",3,provider,32u,0x2800u));unsigned nonzero=0;for(unsigned k=0;k<32;k++)nonzero|=M8(0x2800+k);CHECK(nonzero&&M8(0x2820)==0xa5);
 CHECK(invoke(&c,"CryptReleaseContext",2,provider,0u));CHECK(!invoke(&c,"CryptGenRandom",3,provider,32u,0x2800u)&&last_error==6);CHECK(!invoke(&c,"CryptAcquireContextA",5,0x2700u,0u,0u,1u,0u)&&M32(0x2700)==0);
 CHECK(!private_win32_extra(&c,"unsupported synthetic import"));free(G);printf("PRIVATE WIN32 PASS checks=%u filter_calls=%u\n",checks,filter_calls);return 0;}
''')
        original=(HERE/'private_runtime/win32.c').read_text().replace('#include "security.h"',(HERE/'private_runtime/security.h').read_text())
        for broken in ('good','stack','rng'):
            selected=original
            if broken=='stack':selected=selected.replace('c->esp+=20;','c->esp+=16;')
            if broken=='rng':selected=selected.replace('arc4random_buf(G+p,n);','memset(G+p,0,n);')
            native.write_text(selected)
            command=['clang','-O1','-g','-fsanitize=address,undefined','-I',str(HERE),'-I',str(HERE.parent/'runtime'),'-I',str(HERE/'private_runtime'),str(native),str(fixture),str(out/'fixture.a'),'-o',str(out/'test')]
            r=subprocess.run(command,capture_output=True,text=True)
            if r.returncode:raise RuntimeError(r.stderr[-2500:])
            r=subprocess.run([str(out/'test')],capture_output=True,text=True)
            print(broken+': '+r.stdout.strip()+r.stderr.strip());assert r.returncode==(0 if broken=='good' else 1)
    print('PRIVATE WIN32/SEH PASS (broken stdcall pop exits 1)')


if __name__=='__main__':main()
