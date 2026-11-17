"""Private COM audio/input and WinMM test, no game, GPU, window or audio device.

Good: null_live=0, cursor_advanced=1, MW reads=0, plus native buffer/input/timer
checks. Broken: disabled cursor exits 1; restored MW policy exits 2 after counted
MW reads (no host fault). Private builds absent: skip 3.
"""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
from build_private import ignored_output
from private_render import replace_body
from private_render import body
from private_media import verify_media


def build(root,out,mutant):
    dst=root/'runtime';harness=out/'test.c';harness.write_text(r'''#include "host.h"
#include "dsound_host.h"
#include <stdlib.h>
#include <sys/mman.h>
#include <stdarg.h>
#include <unistd.h>
const uint32_t guest_func_addr[]={0};void (*const guest_func_ptr[])(Cpu*)={0};const unsigned guest_func_count=0;const uint32_t speed_entry=0;
/* This host-only fixture must never enter native startup completion. */
void f_0059B1B0(Cpu *c){(void)c;abort();}
const char speed_exe_fingerprint[]="",speed_exe_sha256[]="",speed_exe_region_sha256[4][65]={{0}};
const struct ExeRegion {const char *name;uint32_t rva,size;} speed_exe_regions[3]={{0}};
const struct {uint32_t slot;const char *name;} speed_imports[]={{0,0}};const unsigned speed_import_count=0;
extern void threads_init(void);extern int win32_dsound(Cpu*,const char*),win32_dinput(Cpu*,const char*),private_win32(Cpu*,const char*);
extern DsDevice *dsound_current_device(void);extern uint8_t di_keys[256],di_mouse_btn[8];extern int di_mouse_dx,di_mouse_dy,di_mouse_dz;
static unsigned checks,enums;
extern unsigned private_audio_mw_reads;
#define CHECK(v) do{++checks;if(!(v)){fprintf(stderr,"MEDIA CHECK %u line %d failed: %s\n",checks,__LINE__,#v);exit(2);}}while(0)
static uint32_t invoke(Cpu*c,uint32_t self,unsigned slot,int n,...){c->esp=0x100000;M32(c->esp)=0xfeed;M32(c->esp+4)=self;va_list ap;va_start(ap,n);for(int i=1;i<n;i++)M32(c->esp+4+4*i)=va_arg(ap,uint32_t);va_end(ap);dispatch(c,M32(M32(self)+4*slot));CHECK(c->esp==0x100004+4*(uint32_t)n);return c->eax;}
static uint32_t api(Cpu*c,int(*fn)(Cpu*,const char*),const char*name,int n,...){c->esp=0x100000;M32(c->esp)=0xfeed;va_list ap;va_start(ap,n);for(int i=0;i<n;i++)M32(c->esp+4+4*i)=va_arg(ap,uint32_t);va_end(ap);CHECK(fn(c,name));CHECK(c->esp==0x100004+4*(uint32_t)n);return c->eax;}
static int enumeration(Cpu*c){CHECK(M32(arg(c,0))==580);CHECK(arg(c,1)==123);++enums;RET(1,2);}
int main(void){G=mmap(NULL,1ull<<32,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANON,-1,0);CHECK(G!=MAP_FAILED);threads_init();Cpu c={0};c.fs_base=0x7000;
 CHECK(api(&c,win32_dsound,"DirectSoundCreate",3,0u,0x3000u,0u)==0);uint32_t device=M32(0x3000);DsDevice*shared=dsound_current_device();CHECK(device&&shared);DsOutputMode mode;int live=99;uint64_t underruns=0;CHECK(ds_device_output_info(shared,&mode,&live,&underruns)==0&&live==0);
 CHECK(invoke(&c,device,6,3,0u,2u)==0);M32(0x3100)=96;CHECK(invoke(&c,device,4,2,0x3100u)==0);CHECK(M32(0x3100)==96);
 M16(0x3200)=1;M16(0x3202)=2;M32(0x3204)=48000;M32(0x3208)=192000;M16(0x320c)=4;M16(0x320e)=16;M16(0x3210)=0;
 M32(0x3300)=20;M32(0x3304)=DSBCAPS_CTRLVOLUME|DSBCAPS_CTRLPAN|DSBCAPS_CTRLFREQUENCY|DSBCAPS_CTRLPOSITIONNOTIFY;M32(0x3308)=192000;M32(0x3310)=0x3200;
 CHECK(invoke(&c,device,3,4,0x3300u,0x3004u,0u)==0);uint32_t buffer=M32(0x3004);CHECK(buffer!=0);M32(0x3400)=20;CHECK(invoke(&c,buffer,3,2,0x3400u)==0&&M32(0x3408)==192000);
 CHECK(invoke(&c,buffer,5,4,0x3500u,64u,0x3540u)==0);CHECK(M32(0x3540)==18&&M16(0x3502)==2&&M32(0x3504)==48000);
 CHECK(invoke(&c,buffer,15,2,(uint32_t)-1000)==0);CHECK(invoke(&c,buffer,6,2,0x3600u)==0&&(int32_t)M32(0x3600)==-1000);
 CHECK(invoke(&c,buffer,16,2,(uint32_t)-500)==0);CHECK(invoke(&c,buffer,7,2,0x3604u)==0&&(int32_t)M32(0x3604)==-500);
 CHECK(invoke(&c,buffer,17,2,48000u)==0);CHECK(invoke(&c,buffer,8,2,0x3608u)==0&&M32(0x3608)==48000);
 CHECK(invoke(&c,buffer,11,8,191992u,16u,0x3700u,0x3704u,0x3708u,0x370cu,0u)==0);CHECK(M32(0x3704)==8&&M32(0x370c)==8&&M32(0x3700)==M32(0x3708)+191992);memset(G+M32(0x3700),0,8);memset(G+M32(0x3708),0,8);CHECK(invoke(&c,buffer,19,5,M32(0x3700),8u,M32(0x3708),8u)==0);
 CHECK(invoke(&c,buffer,13,2,0u)==0);CHECK(invoke(&c,buffer,4,3,0x3800u,0x3804u)==0);uint32_t first=M32(0x3800);CHECK(invoke(&c,buffer,12,4,0u,0u,DSBPLAY_LOOPING)==0);
 int moved=0;for(int k=0;k<500;k++){CHECK(invoke(&c,buffer,4,3,0x3800u,0x3804u)==0);if(M32(0x3800)!=first){moved=1;break;}usleep(10000);}CHECK(moved);CHECK(M32(0x3800)<192000&&M32(0x3804)<192000&&!(M32(0x3800)&3)&&!(M32(0x3804)&3));CHECK(invoke(&c,buffer,4,3,0u,0u)==0);
 DsStats stats;CHECK(ds_device_get_stats(shared,&stats)==0&&stats.frames_written>0);CHECK(invoke(&c,buffer,9,2,0x3900u)==0&&(M32(0x3900)&DSBSTATUS_PLAYING));CHECK(invoke(&c,buffer,18,1)==0);CHECK(invoke(&c,buffer,20,1)==0);
 CHECK(invoke(&c,device,5,3,buffer,0x3008u)==0);uint32_t duplicate=M32(0x3008);CHECK(duplicate&&duplicate!=buffer);M32(0x3a00)=0xb0210783;CHECK(invoke(&c,buffer,0,3,0x3a00u,0x300cu)==0);uint32_t notify=M32(0x300c);CHECK(notify!=0);CHECK(invoke(&c,notify,3,3,0u,0u)==0);invoke(&c,notify,2,1);invoke(&c,duplicate,2,1);invoke(&c,buffer,2,1);invoke(&c,device,2,1);CHECK(dsound_current_device()==NULL);
 CHECK(api(&c,win32_dinput,"DirectInput8Create",5,0u,0x800u,0u,0x4000u,0u)==0);uint32_t input=M32(0x4000);uint32_t callback=host_fn(enumeration,"synthetic keyboard enumeration");CHECK(invoke(&c,input,4,5,3u,callback,123u,0u)==0&&enums==1);
 for(int mouse=0;mouse<2;mouse++){M32(0x4100)=mouse?0x6f1d2b60:0x6f1d2b61;M16(0x4104)=0xd5a0;M16(0x4106)=0x11cf;const unsigned char tail[]={0xbf,0xc7,0x44,0x45,0x53,0x54,0,0};memcpy(G+0x4108,tail,8);CHECK(invoke(&c,input,3,4,0x4100u,0x4004u,0u)==0);uint32_t key=M32(0x4004);CHECK(key!=0);M32(0x4200)=44;CHECK(invoke(&c,key,3,2,0x4200u)==0);CHECK(invoke(&c,key,11,2,0x4300u)==0);CHECK(invoke(&c,key,13,3,0u,0u)==0);CHECK(invoke(&c,key,7,1)==0);
 memset(G+0x4400,0xa5,300);if(mouse){di_mouse_dx=7;di_mouse_dy=-3;di_mouse_dz=1;di_mouse_btn[0]=0x80;}else di_keys[0x1e]=0x80;
 CHECK(invoke(&c,key,9,3,mouse?20u:256u,0x4400u)==0);if(mouse){CHECK((int32_t)M32(0x4400)==7&&(int32_t)M32(0x4404)==-3&&M8(0x440c)==0x80);CHECK(di_mouse_dx==0&&di_mouse_dy==0&&di_mouse_dz==0);CHECK(M8(0x4414)==0xa5);}else{CHECK(M8(0x441e)==0x80&&M8(0x4500)==0xa5);di_keys[0x1e]=0;}
 M32(0x4600)=1;CHECK(invoke(&c,key,10,5,16u,0x4700u,0x4600u,0u)==0&&M32(0x4600)==0);CHECK(invoke(&c,key,8,1)==0);invoke(&c,key,2,1);}
 invoke(&c,input,2,1);CHECK(api(&c,private_win32,"timeBeginPeriod",1,1u)==0);uint32_t t0=api(&c,private_win32,"timeGetTime",0);usleep(20000);uint32_t t1=api(&c,private_win32,"timeGetTime",0);CHECK((uint32_t)(t1-t0)>0);CHECK(api(&c,private_win32,"timeEndPeriod",1,1u)==0);
 if(private_audio_mw_reads)fprintf(stderr,"blocked MW reads=%u\n",private_audio_mw_reads);CHECK(private_audio_mw_reads==0);printf("PRIVATE MEDIA PASS checks=%u null_live=%d cursor_advanced=%d enumerations=%u mw_reads=%u\n",checks,live,moved,enums,private_audio_mw_reads);return 0;}
''')
    flags=['-O1','-g','-w','-I',str(dst),'-I',str(HERE),'-I',str(root),'-I',str(HERE.parent/'host/audio'),'-DNFS_GAME=2','-I',str(HERE.parent/'runtime')]
    sources=[(harness,out/'fixture.o',[]),(dst/'boot.c',out/'boot_test.o',['-Dmain=private_boot_main'])]
    ds_source=(dst/'dsound.c').read_text()
    if mutant=='quarantine':ds_source=replace_body(ds_source,'b_GetCurrentPosition','{ (void)c; return 0; }')
    if mutant=='unsafe':ds_source=replace_body(ds_source,'b_GetCurrentPosition',body((HERE.parent/'runtime/dsound.c').read_text(),'b_GetCurrentPosition').replace('#if NFS_GAME == NFS_GAME_MW', '#if 1'))
    # Instrument the original native adapter only, without a faulting page or
    # a host signal: both source-policy controls remain safe unattended checks.
    guard='''#include "host.h"
unsigned private_audio_mw_reads;
static u32a *private_audio_word(uint32_t a){static uint32_t denied;
 /* Permit the native policy globals; this fixture has no simulation object. */
 if(a>=0x00400000u && a<0x10000000u && a!=0x00B4CFE0u && a!=0x00A99BBCu){++private_audio_mw_reads;return (u32a*)&denied;}
 return (u32a*)(G+a);}
#undef M32
#define M32(a) (*private_audio_word((uint32_t)(a)))
'''
    path=out/'fixture_dsound.c';path.write_text(guard+ds_source);sources.append((path,out/'fixture_dsound.o',[]))
    for source,obj,extra in sources:
        r=subprocess.run(['clang',*flags,*extra,'-c',str(source),'-o',str(obj)],capture_output=True,text=True)
        if r.returncode:raise RuntimeError(r.stderr[-2500:])
    command=json.loads((root/'link_command.json').read_text());new=[];i=0
    while i<len(command):
        arg=command[i]
        if arg=='-o':new+=['-o',str(out/'test')];i+=2;continue
        if arg.endswith('/boot.c.o'):new.append(str(out/'boot_test.o'))
        elif arg.endswith('/imports.c.o'):pass
        elif arg.endswith('/dsound.c.o'):new.append(str(out/'fixture_dsound.o'))
        elif arg.endswith('.a') and Path(arg).parent==root:new.append(str(out/'fixture.o'))
        else:new.append(arg)
        i+=1
    r=subprocess.run(new,capture_output=True,text=True)
    if r.returncode:raise RuntimeError(r.stderr[-2500:])
    return out/'test'


def main():
    root=HERE/'out/carbon'
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
    inventory=json.loads((root/'runtime_isolation.json').read_text());verify_media(inventory)
    inventory['dsound.c'].append({'name':'b_GetCurrentPosition','reason':'deliberately disabled'})
    try:verify_media(inventory)
    except ValueError:print('MEDIA REQUIRED BODY PASS: disabled handler rejected')
    else:raise AssertionError('disabled required cursor handler accepted')
    out=ignored_output(root/'media_test')
    for mutant in ('good','quarantine','unsafe'):
        folder=out/mutant;folder.mkdir(exist_ok=True);binary=build(root,folder,mutant)
        env={**os.environ,'NFS_AUDIO':'null','BOOT_HEADLESS':'1','BOOT_USERDATA':str(folder/'userdata'),'NFS_RUMBLE':'off','NFS_PAD_TRIGGERS':'off','NFS_PAD_LIGHT':'off'}
        r=subprocess.run([str(binary)],capture_output=True,text=True,env=env,timeout=30);(folder/'run.log').write_text(r.stdout+r.stderr)
        print(mutant+': exit='+str(r.returncode)+' '+r.stdout.strip())
        if r.returncode!={'good':0,'quarantine':1,'unsafe':2}[mutant]:raise RuntimeError(r.stderr[-2500:])
        if mutant=='quarantine':assert 'IDirectSoundBuffer::GetCurrentPosition' in r.stderr
        if mutant=='unsafe':assert 'private_audio_mw_reads==0' in r.stderr
    print('PRIVATE MEDIA REGRESSION PASS (disabled cursor and MW access rejected)');return 0


if __name__=='__main__':sys.exit(main())
