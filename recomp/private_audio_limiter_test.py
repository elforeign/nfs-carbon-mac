"""Translated DAC/clamp/converter and six native volume getters; no device.

Default regression: OLD exit 1 (1 failure, unset); NEW exit 0 (20 positive cases, 10 mutants).
The pinned original enable function also fails on every run with unset.
Live DSP: both starting states, On/Off/On and Off/On/Off, final PCM .250000;
maximum transition sample step .007812500 (Off start) / .006679714 (On start),
0 failures. Removing reset or ramp each exits 1 from both starts (good 0).
The reset control fails the final PCM check; the ramp control fails continuity.
Stereo and surround overloads both use the shared six-channel limiter.
Broken stereo bypass: exit 1 vs good 0; 1412 clips become 0.
Good overload: original clipped samples >0, limited clipped samples=0,
peak <=0.891251+1/32767, linked ratios error <2e-6, delay=rate/500 <=2 ms.
Bypass off/movie/unrelated caller/wrong image: 0 changed guest/CPU bytes.
Broken post-clamp placement: ratio error 0.499100536 vs 2.25454677e-8;
exit 1 vs good 0 (both peaks 0.891250908).
Broken caller acceptance: exit 1 (good 0; bypass changed bytes >0).
Broken rate=44100: exit 1 (good 0; requested 48000, observed 44100;
delays 96 vs 88 frames). Broken raw float bits: 1195081728 vs 48000 Hz,
rejected by the API, exit 1 vs good 0. Native rate setter supplies the field.
Broken counter/diagnostic guard/getter master multiply: exit 1 (good 0).
Counter, silence and diagnostics-off controls reject disconnected instrumentation.
Log-check controls: active windows 0 vs required 5; headroom 1.5 vs .89125;
level delta +2.279 vs -.915 dB; muted RMS .001 vs 0; each rejects its mutant.
--game-logs A/stats.log B/stats.log C/stats.log reports live acceptance, including
the 1 dB median comparison (unless gain reduction covers >50% of samples).
Exit 3 without private build outputs or the pinned executable.
"""
import argparse
import hashlib
import math
import json
import os
from pathlib import Path
import re
import statistics
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from recomp import PE, Recompiler
import private_audio

OLD_ENABLED = '''static int private_carbon_limiter_enabled(void) {
    static int enabled=-1;
    if(enabled<0){const char *v=getenv("NFS_CARBON_LIMITER");enabled=v&&!strcmp(v,"1");}
    return enabled;
}'''

EXTRA = (
    (0x008A867C, 0xc6, '234b7638c46d6ed40328274343f85f072bafccb574b0b8e38fe4e51b9a73953d'),
    (0x008B033D, 0xae, '41c354bc1c623fa3d493627df6bccff0e3dc16febf0b4bdc11bfeed43534ae40'),
    (0x004A3DA0, 0x1e, '6bbd2a2214ae613cccbce020555e3485642feb10037f3945a0a0195afba4768f'),
    (0x004A3DE0, 0x29, 'e1e66118c589b47d8d979ad8affa2684053102c30e4579e5c69ea78b86da9bd2'),
    (0x004A3E30, 0x29, 'a32f70759250bae3887e26d670114c3548fccb8e8b1b5749b8b03d8b0c83d0c7'),
    (0x004A3E80, 0x29, 'ace7280643d7803b2c965d91ef1306f41c491b3d2aa02e4384f933902879987d'),
    (0x004A3ED0, 0x29, '4a51d268621a12b99dccf9288c2b49b3732ee1cb9ab417e2b3baef2cf1bc26ae'),
    (0x004A3F70, 0x29, 'ded938a12968f19e563b37ec0615881ecd717b23d463b3a08b9409bfdb74b50a'),
)

BRIDGE = r'''
#include "peak_limiter.h"
static PeakLimiter limiter;
static int rate_seen,calls,enabled=1;
static unsigned generation,seen;
extern "C" {
void *dsound_current_device(void){return (void *)1;}
void ds_device_limit_game_mix(void *d,float *p,size_t n,int rate){
    if(!d || rate<8000 || rate>192000)return;
    ++calls;rate_seen=rate;
    if(!enabled)return;
    if(seen!=generation || limiter.rate()!=rate){limiter.reset(rate);seen=generation;}
    limiter.process(p,n,true);
}
void ds_set_peak_limiter(int on){if(enabled!=on){enabled=on;++generation;}}
void test_reset(void){limiter=PeakLimiter();calls=rate_seen=0;}
int test_rate(void){return rate_seen;}
int test_calls(void){return calls;}
}
'''

HARNESS = r'''
#include "runtime.h"
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
uint8_t *G;
static int diag_on=1,muted;
static int game_sound_mix_muted(void){return muted;}
extern void *dsound_current_device(void);
extern void ds_device_limit_game_mix(void *,float *,size_t,int);
extern int test_rate(void),test_calls(void);
extern void test_reset(void);
extern void ds_set_peak_limiter(int);
#define CHECK(x) do {if(!(x)){fprintf(stderr,"LIMITER CHECK %d: %s\n",__LINE__,#x);exit(1);}}while(0)
void diag_event(const char *format,...){(void)format;}
void guest_divide_error(Cpu *c,uint32_t at){CHECK(0);}
void dispatch(Cpu *c,uint32_t target){CHECK(0);}
void f_0087EAC0(Cpu *c){c->eax=(uint32_t)lrint(ST(0));x87_pop(c);c->esp+=4;}
void f_00572B90(Cpu *c){CHECK(M32(c->esp+4)==0);c->eax=0x20000;c->esp+=8;}
static const float ratios[6]={1,.5f,-.8f,.25f,-.4f,.125f};
static unsigned block;
static float input(unsigned frame,unsigned channel){
    return frame<32?0:ratios[channel]*(frame%47<20?2.4f:1.6f);
}
void f_008B084D(Cpu *c){
    CHECK(M32(c->esp+4)==0xBBF680&&M32(c->esp+12)==CHANNELS&&M32(c->esp+16)==256);
    for(unsigned i=0;i<256;++i)for(unsigned k=0;k<CHANNELS;++k)
        MF32(0xBBF680+(i*CHANNELS+k)*4)=input(block*256+i,k);
    c->esp+=4;
}
void f_0089995B(Cpu *c){c->eax=0x8000;c->esp+=4;}
void f_008A709A(Cpu *c){CHECK(MF32(c->esp+4)==RATE);c->esp+=8;}
void f_008A790C(Cpu *c){CHECK(0);}
void f_008A80AC(Cpu *c){CHECK(0);}
void f_0089EC76(Cpu *c){c->eax=0x30000;c->esp+=4;}
void f_0089EC7D(Cpu *c){c->eax=1;c->esp+=4;}
void f_0089EC5E(Cpu *c){c->eax=0x30000;c->esp+=4;}
void f_0089EC73(Cpu *c){c->esp+=4;}
void f_0089EC84(Cpu *c){c->esp+=4;}
void f_008A579B(Cpu *c){c->esp+=4;}
void f_008A710F(Cpu *c){CHECK(0);}
void f_008B0409(Cpu *c){CHECK(0);}
void f_00899242(Cpu *c){CHECK(0);}
HELPER
TRANSLATED
static Cpu cpu(void){Cpu c={0};c.esp=0x10000;c.ecx=0x4000;c.cw=0x37f;return c;}
static void setup(Cpu *c){
    M32(c->esp)=0x1234;M32(c->esp+4)=0x40000;M32(c->esp+8)=1;
    M8(0xBBF605)=CHANNELS;MF32(0x9C2914)=-1;
    /* Replay the native rate setter, with the pinned 48 kHz float constant. */
    M32(0xA03990)=0x473B8000u;
    M8(0xBBF606)=1;MF32(0xBC0E90)=RATE==48000?MF32(0xA03990):(float)RATE;
    M32(0x7004)=0x4000;MF32(0x7008)=RATE-1;
    Cpu r=cpu();r.esp=0x12000;M32(r.esp+4)=0x7000;
    f_008A867C(&r);CHECK(r.esp==0x12004&&MF32(0x4030)==RATE);
}
static void clamp_args(Cpu *c,uint32_t caller){
    M32(c->esp)=caller;M32(c->esp+4)=0xBBF680;
    MF32(c->esp+8)=-1;MF32(c->esp+12)=1;M32(c->esp+16)=(256*CHANNELS);
}
int main(int argc,char **argv){
    if(argc==4){
        int start=atoi(argv[1]);
        G=calloc(1,0xC00000);MF32(0x4030)=RATE;M8(0xBBF605)=CHANNELS;
        private_carbon_limiter_set(start);
        private_carbon_audio_enter(0x4000);
        for(unsigned i=0;i<256*CHANNELS;++i)MF32(0xBBF680+4*i)=2;
        private_carbon_audio_before(0x8A767B,0xBBF680,256*CHANNELS);
        float last=fminf(1,MF32(0xBBF680+4*(255*CHANNELS)));
        double max_step=0;
        for(int k=0;k<3;++k){
            int on=k%2 ? start : !start;
            private_carbon_limiter_set(on);
            CHECK(private_carbon_limiter_enabled()==on);
            for(unsigned i=0;i<256*CHANNELS;++i)MF32(0xBBF680+4*i)=.25f;
            private_carbon_audio_before(0x8A767B,0xBBF680,256*CHANNELS);
            CHECK(fabsf(MF32(0xBBF680)-last)<1e-6f);
            for(unsigned i=0;i<256;++i){
                float value=MF32(0xBBF680+4*i*CHANNELS);
                double step=fabsf(value-last);if(step>max_step)max_step=step;last=value;
            }
            CHECK(fabsf(last-.25f)<1e-6f); /* fresh history, no stale gain/delay */
            if(on && k<2){
                for(unsigned i=0;i<256*CHANNELS;++i)MF32(0xBBF680+4*i)=2;
                private_carbon_audio_before(0x8A767B,0xBBF680,256*CHANNELS);
                last=fminf(1,MF32(0xBBF680+4*(255*CHANNELS)));
            }
        }
        CHECK(max_step<.02);
        printf("live limiter start=%d transitions=3 max_step=%.9f final=%.6f\n",start,max_step,last);
        free(G);return 0;
    }
    CHECK(argc==3);int enabled=atoi(argv[1]);int movie=atoi(argv[2]);
    G=calloc(1,0xC00000);CHECK(G);
    M32(0xA97BB4)=movie?0x5000:0;M32(0x5120)=5;
    for(unsigned i=0;i<6;++i)MF32(0x20000+0x24230+i*4)=.2f+.1f*i;
    MF32(0x20000+0x24248)=.9f;
    void (*getters[])(Cpu *)={f_004A3DA0,f_004A3DE0,f_004A3E30,f_004A3E80,f_004A3ED0,f_004A3F70};
    const unsigned offsets[]={0x24230,0x24234,0x24238,0x2423c,0x24240,0x24248};
    for(unsigned j=0;j<6;++j){
        Cpu c=cpu();M32(c.esp+4)=0x6000;getters[j](&c);CHECK(c.esp==0x10008);
        float want=MF32(0x20000+offsets[j])*(j?MF32(0x44230):1);
        CHECK(fabs(MF32(0x6000)-want)<1e-7);
    }
    /* Counter off never accumulates; enabled diagnostic mute measures zero floats. */
    Cpu c=cpu();setup(&c);uint64_t saved=private_carbon_audio_enter(c.ecx);
    for(unsigned i=0;i<(256*CHANNELS);++i)MF32(0xBBF680+i*4)=2;
    uint64_t counts[5];double peaks[2];
    diag_on=0;private_carbon_audio_before(0x8A767B,0xBBF680,(256*CHANNELS));
    private_carbon_audio_stats(counts,peaks);CHECK(counts[0]==0&&peaks[0]==0);
    diag_on=1;muted=1;private_carbon_audio_before(0x8A767B,0xBBF680,(256*CHANNELS));
    private_carbon_audio_stats(counts,peaks);
    CHECK(counts[0]==(IDENTITY?(256*CHANNELS):0));
    if(IDENTITY){
        int silent=enabled&&!movie;
        CHECK(counts[1]==(silent?0:(256*CHANNELS))&&counts[2]==(silent?0:(256*CHANNELS)));
        CHECK(peaks[0]==(silent?0:2));
    }
    muted=0;
    private_carbon_audio_leave(saved);test_reset();
    /* Wrong call site must preserve every guest byte and every CPU register. */
    for(unsigned i=0;i<(256*CHANNELS);++i)MF32(0xBBF680+i*4)=2;
    c=cpu();clamp_args(&c,0x11111111);Cpu original=c;
    unsigned char *memory=malloc(0xC00000);memcpy(memory,G,0xC00000);
    saved=private_carbon_audio_enter(0x4000);
    f_008B074C(&c);private_carbon_audio_leave(saved);
    unsigned char *result=malloc(0xC00000);memcpy(result,G,0xC00000);Cpu result_cpu=c;
    memcpy(G,memory,0xC00000);f_008B074C_audio_original(&original);
    CHECK(!memcmp(result,G,0xC00000)&&!memcmp(&original,&result_cpu,sizeof c));
    CHECK(test_calls()==0);
    free(result);free(memory);
    unsigned clipped=0,first=~0u,over=0;double peak=0,ratio_error=0;
    uint64_t pre_clip=0,pre_limit=0,total=0;
    for(block=0;block<4;++block){
        c=cpu();setup(&c);original=c;
        memory=malloc(0xC00000);memcpy(memory,G,0xC00000);
        f_008A74DD(&c);CHECK(c.esp==0x1000c);CHECK(private_audio_context==0);
        if(!enabled||movie||!IDENTITY){
            result=malloc(0xC00000);memcpy(result,G,0xC00000);result_cpu=c;
            memcpy(G,memory,0xC00000);f_008A74DD_audio_original(&original);
            CHECK(!memcmp(result,G,0xC00000)&&!memcmp(&original,&result_cpu,sizeof c));free(result);
        }
        free(memory);
        private_carbon_audio_stats(counts,peaks);total+=counts[0];pre_clip+=counts[1];pre_limit+=counts[2];
        for(unsigned i=0;i<256;++i){
            unsigned frame=block*256+i;float *p=(float *)(G+0xBBF680+i*CHANNELS*4);
            if(first==~0u && p[0]!=0)first=frame;
            for(unsigned k=0;k<CHANNELS;++k){
                double v=fabs(p[k]);if(v>peak)peak=v;
                clipped+=v==1;over+=v>0.891251+1.0/32767;
                if(enabled&&!movie&&IDENTITY&&frame>=RATE/500){
                    double error=fabs(p[k]-p[0]*ratios[k]);
                    if(error>ratio_error)ratio_error=error;
                }
            }
        }
    }
    printf("overload enabled=%d movie=%d rate=%d observed_rate=%d pre_samples=%llu pre_clip=%llu pre_limit=%llu peak=%.9f clipped=%u over=%u ratio_error=%.9g onset=%u\n",
      enabled,movie,RATE,test_rate(),(unsigned long long)total,(unsigned long long)pre_clip,
      (unsigned long long)pre_limit,peak,clipped,over,ratio_error,first);
    CHECK(total==(IDENTITY?4*(256*CHANNELS):0));
    if(enabled&&!movie&&IDENTITY){
        CHECK(test_calls()==4&&test_rate()==RATE);
        CHECK(peak<=0.891251+1.0/32767&&clipped==0&&over==0);
        CHECK(ratio_error<2e-6);CHECK(first==32+RATE/500&&first-32<=RATE*.002);
    }else{CHECK(test_calls()==0);CHECK(clipped>0&&peak==1&&first==32);}
    if(IDENTITY){
        unsigned expected_clip=0,expected_limit=0;
        for(unsigned f=0;f<1024;++f)for(unsigned k=0;k<CHANNELS;++k){
            expected_clip+=fabs(input(f,k))>1;expected_limit+=fabs(input(f,k))>0.891251;
        }
        CHECK(pre_clip==expected_clip&&pre_limit==expected_limit);
    }
    free(G);return 0;
}
'''


def read_mix_log(text):
    pattern = (r't ([0-9.]+) frame (\d+) mixrms (?:\(n/a\) )?([0-9. ]+) '
               r'clip (\d+) limit_samples (\d+) flow (\d+).*?'
               r'pre_samples (\d+) pre_clip (\d+) pre_limit (\d+) pre_peak ([0-9.]+) '
               r'out_over (\d+) out_clip (\d+) out_peak ([0-9.]+)')
    rows=[]
    for line in text.splitlines():
        match=re.fullmatch(pattern,line)
        assert match, 'unrecognised private mix line: '+line[:120]
        v=match.groups()
        rms=list(map(float,v[2].split()));assert len(rms)==6
        rows.append(dict(frame=int(v[1]),rms=rms,host_clip=int(v[3]),limited=int(v[4]),
                         flow=int(v[5]),samples=int(v[6]),pre_clip=int(v[7]),pre_limit=int(v[8]),
                         pre_peak=float(v[9]),out_over=int(v[10]),out_clip=int(v[11]),out_peak=float(v[12])))
    assert rows, 'no mix samples'
    return rows


def mix_summary(rows):
    world=[r for r in rows if r['flow']==6]
    assert world, 'no world samples'
    result={key:sum(r[key] for r in world) for key in
            ('samples','pre_clip','pre_limit','out_over','out_clip','host_clip','limited')}
    result.update({key:max(r[key] for r in world) for key in ('pre_peak','out_peak')})
    result['windows']=len(world)
    result['rms']=[statistics.median(r['rms'][k] for r in world) for k in range(6)]
    result['active']=[sum(r['rms'][k]>1e-4 for r in world) for k in range(6)]
    return result


def check_game_logs(a,b,c):
    muted_rows=read_mix_log(c)
    summaries=[mix_summary(read_mix_log(text)) for text in (a,b,c)]
    a,b,c=summaries
    db=[20*math.log10(y/x) if x and y else (None if x==y else float('inf'))
        for x,y in zip(a['rms'],b['rms'])]
    reduced=b['limited']/b['samples'] if b['samples'] else 0
    checks={
        'baseline':a['pre_limit']>0,
        'headroom':b['samples']>0 and b['out_over']==b['out_clip']==0 and 0<b['out_peak']<=0.891251+1/32767,
        'content':all(b['active'][k]>=5 for k in (0,1,2,4,5)),
        'mute':c['samples']>0 and all(c[k]==0 for k in ('pre_clip','pre_limit','pre_peak','out_over','out_clip','out_peak','host_clip','limited'))
               and all(all(v==0 for v in r['rms']) for r in muted_rows),
        'levels':reduced>0.5 or all(v is None or abs(v)<=1 for v in db),
    }
    return dict(checks=checks,delta_db=db,reduced_fraction=reduced,A=a,B=b,C=c)


def log_check_fixtures():
    line=('t 1 frame 1 mixrms RMS clip 0 limit_samples 0 flow 6 buffers 21 '
          'pre_samples 1536 pre_clip PC pre_limit PL pre_peak PP '
          'out_over OO out_clip OC out_peak OP')
    def sample(rms,pc,pl,pp,oo,oc,op):
        text=line.replace('RMS',rms)
        for key,val in zip(('PC','PL','PP','OO','OC','OP'),(pc,pl,pp,oo,oc,op)):
            text=text.replace(key,str(val))
        return (text+'\n')*6
    a=sample('.1 .1 .2 0 .05 .05',4,12,1.5,12,4,1.5)
    b=sample('.09 .09 .18 0 .045 .045',4,12,1.5,0,0,.89125)
    c=sample('0 0 0 0 0 0',0,0,0,0,0,0)
    good=check_game_logs(a,b,c);assert all(good['checks'].values())
    broken=(('headroom',a,a,c),('content',a,c,c),
            ('levels',a,sample('.13 .13 .26 0 .065 .065',4,12,1.5,0,0,.89125),c),
            ('mute',a,b,c.replace('mixrms 0 0 0 0 0 0','mixrms .001 0 0 0 0 0')),
            ('baseline',c,b,c))
    for name,aa,bb,cc in broken:
        report=check_game_logs(aa,bb,cc)
        assert not report['checks'][name],name
    print('LIMITER LOG CHECK PASS controls=5; silent content active_windows=0 vs required=5; '
          'headroom=1.5 vs .89125; level_delta_db=2.279 vs -.915; muted_rms=.001 vs 0')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--game-logs',nargs=3,metavar=('A','B','C'))
    args=parser.parse_args()
    out = HERE/'out/carbon'
    if not all((out/n).is_file() for n in ('image.json','NFSC.a','boot_carbon')):
        print('SKIP: private limiter build outputs absent');return 3
    image=json.loads((out/'image.json').read_text())
    if not Path(image['exe']).is_file():
        print('SKIP: private executable absent');return 3
    private_audio.validate(image)
    if args.game_logs:
        report=check_game_logs(*(Path(p).read_text() for p in args.game_logs))
        print(json.dumps(report,indent=2))
        return int(not all(report['checks'].values()))
    log_check_fixtures()
    pe=PE(image['exe'],expected_sha256=private_audio.CARBON_SHA256)
    assert pe.read(0xA03990,4)==bytes.fromhex('00803b47')
    witnesses=private_audio.WITNESSES+EXTRA
    for address,size,digest in witnesses:
        assert hashlib.sha256(pe.read(address,size)).hexdigest()==digest
    boundaries=(0x899242,0x89ec76,0x89ec7d,0x89ec5e,0x8a579b,0x89ec73,
                0x89ec84,0x8b084d,0x8a710f,0x8b0409,0x572b90,0x87eac0,
                0x89995b,0x8a709a,0x8a790c,0x8a80ac)
    functions={a:a+n for a,n,_ in witnesses}
    functions.update({a:a+1 for a in boundaries})
    rc=Recompiler(pe=pe,functions=functions,mw_patches=False);rc.calls=True
    translations=[]
    for a,n,_ in witnesses:
        code,why=rc.translate(a,a+n);assert code is not None,why
        translations.append(code)
    translated='\n'.join(translations)
    wrapped,found=private_audio.instrument(translated,image['sha256'])
    assert set(found)==private_audio.HOOKS
    assert private_audio.instrument(translated,'0'*64)==(translated,[])
    prototypes='\n'.join('void f_%08X(Cpu *);'%a for a in functions)
    helper=(HERE/'private_runtime/carbon_audio_limiter.h').read_text()
    assert hashlib.sha256(OLD_ENABLED.encode()).hexdigest() == '8d09a383a8ec37428fcc75faf55c22142f4b742ad580e2b9ac6eefbe618b39f9'
    old_helper,count=re.subn(r'static int private_carbon_limiter_enabled\(void\) \{.*?\n\}',OLD_ENABLED,helper,count=1,flags=re.S)
    assert count==1
    env={k:v for k,v in os.environ.items() if k!='NFS_CARBON_LIMITER'}
    with tempfile.TemporaryDirectory(prefix='private-limiter-') as td:
        tmp=Path(td);(tmp/'bridge.cpp').write_text(BRIDGE)
        r=subprocess.run(['clang++','-std=c++17','-O1','-fsanitize=address,undefined','-I',str(HERE.parent/'host/audio'),'-c',str(tmp/'bridge.cpp'),'-o',str(tmp/'bridge.o')],capture_output=True,text=True)
        assert r.returncode==0,r.stderr[-2000:]
        variants=[('good',helper,wrapped,1,48000),
                  ('live-no-reset',helper.replace('ds_set_peak_limiter(on);','(void)on;'),wrapped,1,48000),
                  ('live-no-ramp',helper.replace('if(fade)pcm[at]=anchor[k]+weight*(pcm[at]-anchor[k]);','(void)weight;'),wrapped,1,48000),('stereo',helper,wrapped,1,48000),
                  ('old-default',old_helper,wrapped,1,48000),
                  ('stereo-bypass',helper.replace('(channels!=2 && channels!=6)', 'channels!=6'),wrapped,1,48000),('rate-32000',helper,wrapped,1,32000),
                  ('rate-96000',helper,wrapped,1,96000),('wrong-image',helper,wrapped,0,48000),
                  ('wrong-caller',helper.replace('caller!=0x008A767Bu || ',''),wrapped,1,48000),
                  ('wrong-rate',helper.replace('(int)(uint32_t)private_audio_context','44100'),wrapped,1,48000),
                  ('rate-bits',helper.replace('float rate=MF32(dac+0x30u);','float rate=(float)M32(dac+0x30u);'),wrapped,1,48000),
                  ('lost-counter',helper.replace('private_audio_counts[1]+=v>1.0','private_audio_counts[1]+=0'),wrapped,1,48000),
                  ('diag-off',helper.replace('int meter=diag_on;','int meter=1;'),wrapped,1,48000),
                  ('lost-mute',helper.replace('if(limit && game_sound_mix_muted())','if(0)'),wrapped,1,48000),
                  ('getter-master',helper,wrapped.replace('x87_nan((a * b), a, b)', 'x87_nan((a + b), a, b)'),1,48000)]
        # Move the exact production boundary callback after the original clamp.
        before='    private_carbon_audio_before(M32(c->esp), M32(c->esp+4), M32(c->esp+16));\n    f_008B074C_audio_original(c);'
        after='    uint32_t sp=c->esp;\n    f_008B074C_audio_original(c);\n    private_carbon_audio_before(M32(sp),M32(sp+4),M32(sp+16));'
        assert before in wrapped
        variants.append(('post-clamp',helper,wrapped.replace(before,after),1,48000))
        for name,inc,code,identity,rate in variants:
            (tmp/'game_image.h').write_text(f'#define PRIVATE_CARBON_SKIPFE {identity}\n')
            source=HARNESS.replace('HELPER',inc).replace('TRANSLATED',prototypes+'\n'+code)
            channels=2 if name.startswith('stereo') else 6
            source=f'#define CHANNELS {channels}\n#define RATE {rate}\n#define IDENTITY {identity}\n'+source
            (tmp/'fixture.c').write_text(source)
            r=subprocess.run(['clang','-O1','-Wno-parentheses-equality','-fsanitize=address,undefined','-I',str(HERE),'-I',str(tmp),'-c',str(tmp/'fixture.c'),'-o',str(tmp/'fixture.o')],capture_output=True,text=True)
            assert r.returncode==0,r.stderr[-3000:]
            r=subprocess.run(['clang++','-fsanitize=address,undefined',str(tmp/'fixture.o'),str(tmp/'bridge.o'),'-o',str(tmp/'fixture')],capture_output=True,text=True)
            assert r.returncode==0,r.stderr[-2000:]
            if name in ('good','stereo','live-no-reset','live-no-ramp'):
                for start in (0,1):
                    r=subprocess.run([str(tmp/'fixture'),str(start),'0','live'],env=env,capture_output=True,text=True)
                    bad=name.startswith('live-no-')
                    assert r.returncode==int(bad),(name,start,r.stdout,r.stderr[-2000:])
                    print(f'LIMITER live {name} start={start} exit={r.returncode} '+r.stdout.strip())
                if name.startswith('live-no-'):continue
            cases=[(0,0,'0'),(1,0,None),(1,0,''),(1,0,'1'),(1,0,'2'),(1,1,None)] if name in ('good','stereo','wrong-image') else [(1,0,'1')]
            if name=='old-default':cases=[(1,0,None)]
            for enabled,movie,value in cases:
                setting={} if value is None else {'NFS_CARBON_LIMITER':value}
                r=subprocess.run([str(tmp/'fixture'),str(enabled),str(movie)],env=dict(env,**setting),capture_output=True,text=True)
                bad=name in ('old-default','stereo-bypass','wrong-caller','wrong-rate','post-clamp','lost-counter','diag-off','lost-mute','getter-master','rate-bits')
                print(f'LIMITER {name} exit={r.returncode} '+r.stdout.strip())
                assert r.returncode==int(bad),(name,r.stderr[-3000:])
    print('PRIVATE AUDIO LIMITER PASS witnesses=10 native_getters=6 native_rate_setter=1 mutants=12 live_transitions=12')
    return 0

if __name__=='__main__':
    sys.exit(main())
