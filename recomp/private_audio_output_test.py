"""Native DAC request provider and fake-HDMI live output, no game or real audio.

Provider removed (the old native-only path): exit 1, choices 0 vs required 1.
Good: exit 0, 7 native requests / 5 API calls; repeated options add 0 calls.
F10 uses the same native option and DAC chain from both Stereo and Surround;
its frozen setter control exits 1 (good 0). Requests wait for native audio readiness.
Thiscall regression: original hook exit 1, null-this control exit 1, fixed exit 0;
missing manager/object/audio readiness: 0 deliveries, then 1 pending delivery.
The replay executes the real 008999E5 vtable dispatch; lock stubs validate this.
Default tests are in private_audio_test and private_audio_limiter_test.
Native option 2 with startup request 1 still chooses auto; option 1 stereo,
option 2 auto; NFS_AUDIO set (including empty) means 0 provider API calls.
Fake TV: TrueHD 5.1 -> Stereo -> TrueHD 5.1, live and across recreation.
Production cursor polls: launch reopens required 1, disabled-policy control 0
(exit 1). Front end and initial SkipFE drive each reopen once; paused/loading
and missing in-game simulation reopen 0 times, including after returning to drive.
Exit 3 without Carbon outputs, executable or host audio archives.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
from recomp import PE, Recompiler
from private_audio_test import REPLAY, WITNESSES
import private_hooks

WITNESSES = (*WITNESSES,
    (0x50E050, 0x3a, 'fdf1db51726afca80c6fe6552e3c40afe8f901a8027da9a96c2fb2237d48ed5f'),
    (0x8999E5, 9, '98e85c1463d8d53fde01546ff7b0904cf99d27bd3e0d5086005aeeb9a70d560d'))

# Frozen crashing frame, bound independently of the current provider.
OLD_FRAME = '''void carbon_audio_output_frame(void) {
    if (carbon_audio_pending < 0 || !M32(0x00A631B8u)) return;
    uint32_t option = (uint32_t)carbon_audio_pending;
    carbon_audio_pending = -1;
    M32(0x00A63E70u) = option;
    static uint32_t stack;
    if (!stack) stack = galloc(65536);
    Cpu c = {0}; c.esp = stack + 65536; c.cw = 0x37F;
    call_guest(&c, 0x00504530u, 1, &option);
}
'''

DRIVER = r'''
static unsigned choice_calls;
static unsigned guest_calls;
static uint32_t saved_mode;
static const char *last_choice;
void boot_reg_set_dword(const char *key,uint32_t option){
 CHECK(!strcmp(key,"g_AudioMode"));saved_mode=option;
}
extern void host_choice(const char *);
void test_output_choice(const char *s){++choice_calls;last_choice=s;host_choice(s);}
#define ds_set_output_choice test_output_choice
PROVIDER
uint32_t call_guest(Cpu *c,uint32_t fn,int n,const uint32_t *args){
 ++guest_calls;
 CHECK(c->ecx==0x2000 && fn==0x0050E050u && n==1);
 uint32_t esp=c->esp;
 c->esp-=8;M32(c->esp)=0;M32(c->esp+4)=args[0];
 f_0050E050(c);CHECK(c->esp==esp);return c->eax;
}
#undef ds_set_output_choice
void fixture_init(const char *path){
 G=calloc(1,0xC00000);FILE *f=fopen(path,"rb");CHECK(f);
 CHECK(fread(G,1,0xC00000,f)==0xC00000);fclose(f);
 M32(0xA8BA38)=0x1800;M32(0x1874)=0x2000;
 M32(0x2004)=0x2400;M32(0x200C)=0x2500;
 M32(0x2500)=0x2600;M32(0x2604)=0x108;
}
void fixture_pending(void){
 unsigned calls=guest_calls,option=M32(0xA63E70);
 M32(0xA631B8)=1;M32(0xA8BA38)=0;M32(0x74)=0x2000;
 carbon_audio_surround_set(1);carbon_audio_output_frame();
 CHECK(guest_calls==calls && M32(0xA63E70)==option);
 M32(0xA8BA38)=0x1800;M32(0x1874)=0;carbon_audio_output_frame();
 CHECK(guest_calls==calls && M32(0xA63E70)==option);
 M32(0x1874)=0x2000;M32(0xA631B8)=0;carbon_audio_output_frame();
 CHECK(guest_calls==calls && M32(0xA63E70)==option);
 M32(0xA631B8)=1;carbon_audio_output_frame();
 CHECK(guest_calls==calls+1 && M32(0xA63E70)==2);
 CHECK(M32(0x205C)==2 && request==3.0f);
 carbon_audio_output_frame();CHECK(guest_calls==calls+1);
 puts("OUTPUT pending deliveries=0 missing_manager+missing_object+not_ready; ready=1 repeated=0");
}
unsigned fixture_calls(void){return choice_calls;}
const char *fixture_choice(void){return last_choice;}
unsigned fixture_request(unsigned option, int startup){
 M32(0xA631B8)=0;
 carbon_audio_surround_set(option==2);carbon_audio_output_frame();
 M32(0xA631B8)=1;carbon_audio_output_frame();
 CHECK(M32(0xA63E70)==option);
 CHECK(saved_mode==option && carbon_audio_surround_get()==(option==2));
 CHECK(M32(0x205C)==option);
 CHECK(request==(option==1?1.0f:3.0f));
 Cpu c={0};c.esp=0x10000;c.ecx=0x2000;M32(c.esp+4)=startup?1:option;
 f_00504530(&c);CHECK(c.esp==0x10008);
 CHECK(request==(startup||option==1?1.0f:3.0f));
 c=(Cpu){0};c.esp=0x10000;M32(c.esp+4)=0x3000;
 M32(0x3004)=0x4000;MF32(0x3008)=request;
 M8(0xBC0EC8)=2;M32(0xBC0E80)=1;M32(0xBC0E84)=3;M8(0xBBF608)=0;
 f_008A8560(&c);CHECK(c.esp==0x10004);
 unsigned want=startup||option==1?2:6;CHECK(M8(0xBBF605)==want);
 c=(Cpu){0};c.esp=0x10000;c.ecx=0x4000;M32(c.esp+4)=want;
 M32(c.esp+8)=48000;M32(c.esp+12)=0;M32(0x4044)=0x6000;
 M32(0x6000)=0x6100;M32(0x610C)=0x100;M32(0x5000)=0x6200;M32(0x6238)=0x104;
 creates=0;f_008A7931(&c);CHECK(c.esp==0x10010&&c.eax==1&&creates==2);
 CHECK(channels==want&&mask==(want==6?63:3)&&align==want*2&&bits==16&&rate==48000);
 return channels;
}
void fixture_done(void){free(G);}
'''

CURSOR = r'''
#include "dsound.c"
int diag_on, boot_trace;
int movies_playing(void){return 0;}
static uint32_t bump=0x70000;
uint32_t galloc(uint32_t n){uint32_t a=bump;bump+=(n+63)&~63u;return a;}
uint32_t gmalloc(uint32_t n){return galloc(n);}
void gfree(uint32_t a){(void)a;}
void diag_event(const char *f,...){(void)f;}
uint32_t diag_thread_id(void){return 0;}
uint64_t host_ticks(void){return 0;}
uint32_t host_fn(HostFn fn,const char *name){(void)fn;(void)name;return 0;}
const char *app_pref(const char *k){(void)k;return NULL;}
void threads_set_event_async(uint32_t h){(void)h;}
void threads_wait_desc(uint32_t t,char *b,size_t n){(void)t;if(n)*b=0;}
static DsObj *cursor;
void fixture_cursor_init(DsDevice *d,DsBuffer *b){
 cursor=new_obj(2,0);cursor->dev=d;cursor->buf=b;
}
void fixture_cursor_state(unsigned flow,unsigned state,int present){
 M32(0x00A99BBCu)=flow;M32(0x00B4CFE0u)=present?0x90000:0;
 M32(0x90024)=state;
}
int fixture_cursor_poll(void){
 Cpu c={0};c.esp=0x80000;M32(c.esp+4)=cursor->guest;
 M32(c.esp+8)=0x81000;M32(c.esp+12)=0x81004;
 return b_GetCurrentPosition(&c)&&c.esp==0x80010&&c.eax==DS_OK;
}
'''

DEVICE = r'''
#include "dsound_host.h"
#include <chrono>
#include <thread>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>
#include <atomic>
extern "C" {
void fixture_init(const char *);
unsigned fixture_calls(void),fixture_request(unsigned,int);
const char *fixture_choice(void);
void fixture_done(void);
void fixture_pending(void);
void fixture_cursor_init(DsDevice *,DsBuffer *);
void fixture_cursor_state(unsigned,unsigned,int);
int fixture_cursor_poll(void);
void host_choice(const char *s){ds_set_output_choice(s);}
}
#define CHECK(x) do{if(!(x)){fprintf(stderr,"OUTPUT CHECK %d: %s (calls=%u)\n",__LINE__,#x,fixture_calls());exit(1);}}while(0)
static void wait_mode(DsDevice *d,DsOutputMode want){
 int live=0;DsOutputMode mode=DS_OUT_PCM51;uint64_t under;
 for(unsigned i=0;i<200;++i){
  CHECK(ds_device_output_info(d,&mode,&live,&under)==DS_OK);
  if(mode==want&&live==1)return;
  std::this_thread::sleep_for(std::chrono::milliseconds(20));
 }
 fprintf(stderr,"mode=%d live=%d want=%d\n",mode,live,want);CHECK(false);
}
struct Stream {
 DsDevice *d=nullptr;DsBuffer *p=nullptr,*b=nullptr;std::vector<unsigned char> memory;
 void open(unsigned channels){
  CHECK(ds_device_create(nullptr,&d)==DS_OK);
  CHECK(ds_device_set_cooperative_level(d,DSSCL_PRIORITY)==DS_OK);
  CHECK(ds_device_create_buffer(d,DSBCAPS_PRIMARYBUFFER,0,nullptr,nullptr,&p)==DS_OK);
  unsigned char fmt[40]={};
  auto w16=[&](int at,uint16_t v){memcpy(fmt+at,&v,2);};
  auto w32=[&](int at,uint32_t v){memcpy(fmt+at,&v,4);};
  w16(0,0xfffe);w16(2,channels);w32(4,48000);w32(8,48000*channels*2);
  w16(12,channels*2);w16(14,16);w16(16,22);w16(18,16);w32(20,channels==6?63:3);
  const unsigned char pcm[]={1,0,0,0,0,0,0x10,0,0x80,0,0,0xaa,0,0x38,0x9b,0x71};memcpy(fmt+24,pcm,16);
  CHECK(ds_buffer_set_format(p,fmt)==DS_OK);memory.assign(48000*channels*2,0);
  CHECK(ds_device_create_buffer(d,DSBCAPS_GLOBALFOCUS|DSBCAPS_GETCURRENTPOSITION2,memory.size(),fmt,memory.data(),&b)==DS_OK);
  CHECK(ds_buffer_play(b,DSBPLAY_LOOPING)==DS_OK);
 }
 void close(){ds_buffer_release(b);ds_buffer_release(p);ds_device_release(d);d=nullptr;}
};
static std::atomic<unsigned> launch_reopens{0};
static void launch_log(const char *line){
 if(strstr(line,"audio: launch reopen done "))++launch_reopens;
}
int main(int argc,char **argv){
 CHECK(argc>=2);setenv("NFS_AUDIO_FAKE_DEVICE","1",1);setenv("NFS_AUDIO_LAUNCH_REOPEN","0",1);
 fixture_init(argv[1]);
 if(argc==3&&!strncmp(argv[2],"launch-",7)){
  unsetenv("NFS_AUDIO");unsetenv("NFS_AUDIO_LAUNCH_REOPEN");ds_set_log(launch_log);
  const char *state=argv[2]+7;
  bool fe=!strcmp(state,"fe"),paused=!strcmp(state,"paused");
  bool loading=!strcmp(state,"loading"),missing=!strcmp(state,"missing");
  unsigned want=!(paused||loading||missing);
  fixture_cursor_state(fe?3:loading?5:6,paused?4:3,!fe&&!missing);
  Stream stream;stream.open(6);wait_mode(stream.d,DS_OUT_TRUEHD);
  fixture_cursor_init(stream.d,stream.b);
  for(unsigned i=0;i<300;++i){
   CHECK(fixture_cursor_poll());
   std::this_thread::sleep_for(std::chrono::milliseconds(20));
  }
  // A startup suppression consumes the one-shot; later resume must not rearm it.
  fixture_cursor_state(6,3,1);
  for(unsigned i=0;i<20;++i){CHECK(fixture_cursor_poll());
   std::this_thread::sleep_for(std::chrono::milliseconds(20));}
  wait_mode(stream.d,DS_OUT_TRUEHD);
  printf("OUTPUT %s launch_reopens=%u required=%u\n",argv[2],launch_reopens.load(),want);
  CHECK(launch_reopens==want);stream.close();fixture_done();return 0;
 }
 fixture_pending();
 if(argc==3){
  setenv("NFS_AUDIO",argv[2],1);ds_set_output_choice("dd");DsConfig before,after;
  ds_config_default(&before);
  for(unsigned option:{2,1,2})fixture_request(option,0);
  ds_config_default(&after);CHECK(fixture_calls()==0);
  CHECK(before.mode==after.mode&&before.sink==after.sink&&before.auto_mode==after.auto_mode);
  printf("OUTPUT env='%s' requests=3 calls=0\n",argv[2]);fixture_done();return 0;
 }
 unsetenv("NFS_AUDIO");Stream stream;unsigned previous=0,calls=0;
 for(unsigned option:{2,2,1,1,2,1,2}){
  unsigned channels=fixture_request(option,previous==0);calls+=option!=previous;
  CHECK(fixture_calls()==calls);CHECK(!strcmp(fixture_choice(),option==1?"stereo":"auto"));
  DsOutputMode want=option==1?DS_OUT_STEREO:DS_OUT_TRUEHD;
  if(stream.d){wait_mode(stream.d,want);stream.close();}
  stream.open(channels);wait_mode(stream.d,want);
  printf("OUTPUT option=%u guest_channels=%u host=%s output_channels=%u calls=%u\n",option,channels,
    want==DS_OUT_TRUEHD?"TrueHD":"Stereo",want==DS_OUT_TRUEHD?6:2,calls);
  previous=option;
 }
 CHECK(calls==5);stream.close();fixture_done();return 0;
}
'''


def run(command, **kwargs):
    r = subprocess.run(list(map(str, command)), capture_output=True, text=True, **kwargs)
    assert r.returncode == 0, r.stderr[-3000:]
    return r


def main():
    out = HERE/'out/carbon'
    required = [out/n for n in ('image.json','NFSC.a','boot_carbon')]
    required += [ROOT/'host/audio/build'/n for n in ('libhostaudio.a','libmedia.a')]
    if not all(p.is_file() for p in required):
        print('SKIP: private output or host audio archive absent');return 3
    image = json.loads((out/'image.json').read_text())
    if not Path(image['exe']).is_file():
        print('SKIP: private executable absent');return 3
    pe = PE(image['exe'], expected_sha256=image['sha256'])
    functions = {a:a+n for a,n,_ in WITNESSES}
    boundaries=(0x899352,0x899369,0x87EAC0,0x8A790C,0x8A80AC,0x8A7394,0x899242)
    rc = Recompiler(pe=pe, functions=functions, mw_patches=False)
    rc.functions.update({a:a+1 for a in boundaries});rc.calls=True
    # Load the real row through a single-row registry, retaining production validation.
    row=json.loads((HERE/'private_runtime/hooks/audio_output.json').read_text())
    translations=[]
    with tempfile.TemporaryDirectory(prefix='private-audio-output-') as td:
        tmp=Path(td);registry=tmp/'hooks';registry.mkdir()
        (registry/'audio_output.json').write_text(json.dumps(row))
        hooks=private_hooks.load_registry(pe,[(a,a+n,'fixture') for a,n,_ in WITNESSES],registry)
        assert set(hooks)=={0x8A8560}
        for a,n,digest in WITNESSES:
            assert hashlib.sha256(pe.read(a,n)).hexdigest()==digest
            code,why=rc.translate(a,a+n);assert code is not None,why
            if a in hooks:code=private_hooks.wrap(a,code,hooks[a])
            translations.append(code)
        declarations='void carbon_audio_output_request(Cpu *, void (*)(Cpu *));\nvoid f_008999E5(Cpu *);\n'
        replay=REPLAY[:REPLAY.index('int main(')]
        # The request-only stub hid the null receiver. Keep the real
        # virtual thunk and validate its receiver at the simulated DAC boundary.
        replay=replay.replace('void f_008999E5(Cpu *c){CHECK(M32(c->esp+4)==1);request=MF32(M32(c->esp+8));c->esp+=12;}\n','')
        for address in ('00899352','00899369'):
            replay=replay.replace(f'void f_{address}(Cpu *c){{c->esp+=4;}}',
                                 f'void f_{address}(Cpu *c){{CHECK(c->ecx==0x2400);c->esp+=4;}}')
        replay=replay.replace(' if(target==0x100) {', ''' if(target==0x108){
   CHECK(c->ecx==0x2500 && M32(c->esp+4)==1);
   request=MF32(M32(c->esp+8));c->esp+=12;
 }else if(target==0x100) {''')
        code=replay.replace('TRANSLATED',declarations+'\n'.join(translations))
        provider=(HERE/'private_runtime/carbon_audio_output.c').read_text()
        # Compile the production provider against the same real host API, recording calls.
        code+=DRIVER.replace('PROVIDER',provider)
        assert hashlib.sha256(OLD_FRAME.encode()).hexdigest()=='8bbb144e8ad0b923e5f687b27cce00c8bec70843ff27a9f96ac54689322a4787'
        old_provider=provider[:provider.index('void carbon_audio_output_frame')]+OLD_FRAME
        memory=bytearray(0xC00000)
        for _,_,va,size,raw in pe.sections:memory[pe.base+va:pe.base+va+size]=pe.data[raw:raw+size]
        (tmp/'image.bin').write_bytes(memory);(tmp/'device.cpp').write_text(DEVICE)
        env={k:v for k,v in os.environ.items() if not k.startswith('NFS_AUDIO')}
        ff=ROOT/'third_party/ffmpeg/lib'
        libs=[ROOT/'host/audio/build/libhostaudio.a',ROOT/'host/audio/build/libmedia.a']
        libs += [ff/('lib'+n+'.a') for n in ('avformat','avcodec','swscale','swresample','avutil')]
        policy=(HERE/'private_runtime/game_audio_policy.h').read_text()
        (tmp/'cursor.c').write_text(CURSOR.replace('"dsound.c"',json.dumps(str(ROOT/'runtime/dsound.c'))))
        for variant,source in (
                ('good',code),
                ('original-hook',code.replace(provider,old_provider)),
                ('null-this',code.replace('c.ecx = audio;', 'c.ecx = 0;')),
                ('missing-object',code.replace('if (!audio) return;', '(void)audio;')),
                ('f10-frozen',code.replace('carbon_audio_pending = on ? 2 : 1;', '(void)on;')),
                ('provider-removed',code.replace('carbon_audio_output_request(c, carbon_orig_008A8560);','carbon_orig_008A8560(c);')),
                ('reversed',code.replace('option==1?"stereo":"auto"','option==1?"auto":"stereo"')),
                ('repeat',code.replace(' && option!=applied',''))):
            assert variant=='good' or source!=code,variant
            (tmp/'fixture.c').write_text(source)
            (tmp/'game_audio_policy.h').write_text(policy)
            run(['clang','-O1','-DNFS_GAME=2','-I',tmp,'-I',out/'runtime','-I',HERE,
                 '-I',ROOT/'runtime','-c',tmp/'cursor.c','-o',tmp/'cursor.o'])
            run(['clang','-O1','-Wno-parentheses-equality','-I',HERE,'-I',ROOT/'runtime','-c',tmp/'fixture.c','-o',tmp/'fixture.o'])
            run(['clang++','-std=c++17','-O1','-I',ROOT/'host/audio',tmp/'device.cpp',tmp/'fixture.o',tmp/'cursor.o',*libs,
                 '-lz','-framework','AudioToolbox','-framework','CoreAudio','-framework','CoreFoundation','-o',tmp/'fixture'])
            r=subprocess.run([str(tmp/'fixture'),str(tmp/'image.bin')],env=env,capture_output=True,text=True,timeout=40)
            assert r.returncode==int(variant!='good'),(variant,r.stdout[-1500:],r.stderr[-2500:])
            print(f'OUTPUT {variant} exit={r.returncode}\n'+r.stdout.strip())
            if variant=='good':
                for state in ('fe','skipfe','paused','loading','missing'):
                    r=run([tmp/'fixture',tmp/'image.bin','launch-'+state],env=env,timeout=20)
                    print(r.stdout.strip())
                for value in ('null','stereo','pcm51',''):
                    r=run([tmp/'fixture',tmp/'image.bin',value],env=env,timeout=15)
                    print(r.stdout.strip())
                disabled=policy.replace('game_sound_can_startup_reopen(void) { return 1; }',
                                        'game_sound_can_startup_reopen(void) { return 0; }')
                assert disabled!=policy
                (tmp/'game_audio_policy.h').write_text(disabled)
                run(['clang','-O1','-DNFS_GAME=2','-I',tmp,'-I',out/'runtime','-I',HERE,
                     '-I',ROOT/'runtime','-c',tmp/'cursor.c','-o',tmp/'cursor.o'])
                run(['clang++','-std=c++17','-O1','-I',ROOT/'host/audio',tmp/'device.cpp',tmp/'fixture.o',tmp/'cursor.o',*libs,
                     '-lz','-framework','AudioToolbox','-framework','CoreAudio','-framework','CoreFoundation','-o',tmp/'disabled'])
                r=subprocess.run([str(tmp/'disabled'),str(tmp/'image.bin'),'launch-skipfe'],
                                 env=env,capture_output=True,text=True,timeout=20)
                assert r.returncode==1 and 'launch_reopens=0 required=1' in r.stdout,(r.stdout,r.stderr[-2500:])
                print('OUTPUT disabled-policy exit=1 '+r.stdout.strip())
        # Run the existing HDMI recreation/loss/recovery tests in the same offline job.
        run(['clang++','-std=c++17','-O1',ROOT/'host/audio/dstest.cpp',*libs,
             '-lz','-framework','AudioToolbox','-framework','CoreAudio','-framework','CoreFoundation','-o',tmp/'dstest'])
        r=run([tmp/'dstest','fake'],env=env,timeout=90)
        print('OUTPUT existing fake HDMI: '+r.stdout.strip().splitlines()[-1])
    print('PRIVATE AUDIO OUTPUT PASS requests=7 api_calls=5 env_cases=4 mutants=7 pending_delivery=1 fake_hdmi=live+recreated')
    return 0


if __name__=='__main__':
    sys.exit(main())
