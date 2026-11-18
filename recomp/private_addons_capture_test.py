"""Carbon rows -> saved resolution -> actual clip/replay Metal, mixer and decoder.
Uses cliprec.mm clip_packets.mm replay.mm replay_export.mm live_encode.mm
live_seg.mm livestream.mm stream_key.m carbon_addons_host_settings.h.
Good: 36 decoded moving frames / 28,800 stereo sample frames; replay
30.000000 s / 1,448,896 decoded stereo sample frames. Original presentation
no-op fails before recording any frame; original replay Arm creates no buffer.
The interval ends just after the last submitted frame and is latched before
the encoder watermark catches up. A request 0.2 s earlier correctly fails
warm-up because the oldest retained GOP starts after that request's interval.
"""
from pathlib import Path
import hashlib,os,subprocess,sys,tempfile
ROOT=Path(__file__).resolve().parents[1];RT=ROOT/'runtime';PRIVATE=ROOT/'recomp/private_runtime'

ORIGINAL_PRESENT = 'void cliprec_present(id<MTLCommandBuffer> __unsafe_unretained cb, id<MTLTexture> __unsafe_unretained src, id<CAMetalDrawable> __unsafe_unretained drawable, float headroom) { }\n'
ORIGINAL_ARM = 'void replay_arm_action(int unused) { }\n'
assert hashlib.sha256(ORIGINAL_PRESENT.encode()).hexdigest() == '9dedf486d04dfc052c554dd47e3a2faf9c4dc8fe2ec16ea79b9f80064f4baf0f'
assert hashlib.sha256(ORIGINAL_ARM.encode()).hexdigest() == '12a2f4c39d515d4930a5112e14a297fa1390cd21f3e36c10e240bd58aba49b31'

ROWS=r'''
#include <stdio.h>
#include <string.h>
#include "settings.h"
#include "carbon_addons_host_settings.h"
static char saved[64];
int diag_on;
void diag_event(const char *fmt,...){(void)fmt;}
const char *app_pref(const char *key){return !strcmp(key,"display.clip_resolution")?"4k":NULL;}
void app_pref_set(const char *key,const char *value){if(!strcmp(key,"display.clip_resolution"))snprintf(saved,sizeof saved,"%s",value);}
int roots_x360_has(const char *f){(void)f;return 1;}
void report_live(float *a,float *b,float *c){*a=*b=*c=0;}
const char *report_audio_device(void){return "fixture";}
int dsound_output_info(const char **s,int *live,uint64_t *u){*s="PCM";*live=1;*u=0;return 1;}
void carbon_addons_test_init(void){carbon_addons_host_settings_init();settings_init();settings_set(settings_find("display.clip_resolution"),0);}
int carbon_addons_test_saved(void){return !strcmp(saved,"1080p");}
void carbon_addons_test_action(const char *id){Setting *s=settings_find(id);if(s && s->apply)s->apply(0);}
'''
MAIN=r'''
#import <QuartzCore/QuartzCore.h>
static double actionClock;
static double actionNow(void){return actionClock;}
#define CACurrentMediaTime actionNow
#include "audio-fixture.mm"
#undef CACurrentMediaTime
extern "C" void carbon_addons_test_init(void);
extern "C" int carbon_addons_test_saved(void);
extern "C" void carbon_addons_test_action(const char *);
static const char *fixtureUserdata;
extern "C" const char *userdata_dir(void){return fixtureUserdata;}
int main(int argc,char **argv){@autoreleasepool{
 require(argc==2,"scratch output folder");fixtureUserdata=argv[1];outputFolder=[NSString stringWithUTF8String:argv[1]];
 gpu=MTLCreateSystemDefaultDevice();require(gpu!=nil,"Metal device");commands=[gpu newCommandQueue];
 require([cliprec_movies_folder() hasSuffix:@"/Movies/NFSC"],"Carbon output folder");
 setenv("NFS_GAME_SCRATCH",argv[1],1);
 require([cliprec_movies_folder() isEqual:[outputFolder stringByAppendingPathComponent:@"Movies/NFSC"]],"supervised captures stay in scratch");
 unsetenv("NFS_GAME_SCRATCH");
 carbon_addons_test_init();require(carbon_addons_test_saved(),"resolution persisted as 1080p");
 oracle.clear();auto audio=std::make_unique<AudioFixture>();
 carbon_addons_test_action("display.cliprec");ClipSession *s=current;require(s && active,"registered clip starts capture");
 require(s->resolution==0,"saved resolution reaches recording consumer");audio->render(4096);
 auto cb=[commands commandBuffer];cliprec_present(cb,pattern(0),drawable(),1);[cb commit];[cb waitUntilCompleted];syncWork(s);
 require(s->ready,"production presenter prepares capture");
 double epoch=ticksToSeconds(oracle.front().meta.first_sample_host_time)+0.0507;
 for(unsigned i=0;i<N;++i){audio->through(epoch+(i+2)/60.0);frame(s,i,epoch+i/60.0);}
 carbon_addons_test_action("display.cliprec");finishedOK(s);
 auto video=decode(s->destination);auto pcm=decodeAudio(s->destination);
 require(video.valid && video.count==N && video.markerError==0,"recorded moving frames decode");
 double energy=0;for(float x:pcm.pcm)energy+=x*x;
 require(pcm.tracks==1 && pcm.channels==2 && (pcm.pcm.size()/2)>1000 && energy>0.00001,"recorded stereo game mix decodes");
 printf("Carbon registered clip: frames=%u audio=%zu energy=%.6f resolution=%u\n",video.count,(pcm.pcm.size()/2),energy,s->resolution);fflush(stdout);
 audio.reset();oracle.clear();audio=std::make_unique<AudioFixture>();
 carbon_addons_test_action("display.replay_arm");s=current;require(s && active && s->replayOnly,"registered replay Arm starts buffer");
 require(s->resolution==0,"saved resolution reaches replay consumer");audio->render(4096);
 cb=[commands commandBuffer];cliprec_present(cb,pattern(0),drawable(),1);[cb commit];[cb waitUntilCompleted];syncWork(s);require(s->ready,"replay presentation prepares capture");
 epoch=ticksToSeconds(oracle.front().meta.first_sample_host_time)+0.0507;
 for(unsigned i=0;i<=320;++i){audio->through(epoch+(i+2)/10.0);frame(s,i%N,epoch+i/10.0);}
 actionClock=epoch+32.123333333;carbon_addons_test_action("display.replay_save");syncWork(s);
 for(unsigned i=321;i<=325;++i){audio->through(epoch+(i+2)/10.0);frame(s,i%N,epoch+i/10.0);}
 require(replayExport && replayExport->wait(30),"registered replay export finishes");
 require(replayExport->status().find("Replay saved:")==0,"replay action publishes file");
 NSArray *files=[NSFileManager.defaultManager contentsOfDirectoryAtPath:outputFolder error:nil];NSString *replayPath=nil;
 for(NSString *file in files)if([file hasPrefix:@"Replay-"])replayPath=[outputFolder stringByAppendingPathComponent:file];
 require(replayPath!=nil,"replay output exists");auto asset=[AVURLAsset URLAssetWithURL:[NSURL fileURLWithPath:replayPath] options:nil];
 require(fabs(CMTimeGetSeconds(asset.duration)-30)<1.0/60000,"replay duration is 30 seconds");
 pcm=decodeAudio(replayPath);require(pcm.tracks==1 && pcm.channels==2 && (pcm.pcm.size()/2)>1000000,"replay stereo audio decodes");
 printf("Carbon registered replay: seconds=%.6f audio=%zu\n",CMTimeGetSeconds(asset.duration),(pcm.pcm.size()/2));fflush(stdout);
 carbon_addons_test_action("display.replay_arm");cliprec_shutdown();return 0;
}}
'''

def execute(cmd,log):
    run=subprocess.run(cmd,capture_output=True,text=True,timeout=120);log.write_text(run.stdout+run.stderr)
    assert not run.returncode,(cmd[-3:],run.stderr[-3000:])

def main():
    cache=ROOT/'.metal-cache/private-addons-capture';cache.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='fixture-',dir=cache) as td:
        d=Path(td);base=(RT/'cliprec_test.mm').read_text();start=base.index('extern "C" int settings_get(const char *id) {');end=base.index('\n}',start)+2
        base=base[:start]+base[start:end].replace('int settings_get(', 'int fixture_unused_settings_get(')+base[end:]
        # Keep existing fixture helpers, but the production capture reads the real settings registry.
        (d/'cliprec_test.mm').write_text(base)
        audio=(RT/'cliprec_audio_test.mm').read_text().replace('int main(', 'int unused_audio_main(')
        (d/'audio-fixture.mm').write_text(audio);(d/'main.mm').write_text(MAIN);(d/'rows.c').write_text(ROWS)
        flags=['-O1','-g','-fobjc-arc','-DNFS_GAME=2','-DCLIPREC_PCM_CONTROL=1','-I'+str(d),'-I'+str(PRIVATE),'-I'+str(RT),'-I'+str(ROOT/'recomp'),'-I'+str(ROOT/'third_party/ffmpeg/include')]
        objects=[]
        for source in [d/'rows.c',RT/'settings.c',RT/'offline_stubs.c',RT/'stream_key.m',ROOT/'media/media.cpp',*(RT/(n+'.mm') for n in ['clip_packets','replay','replay_export','live_encode','live_seg','livestream'])]:
            obj=d/(source.name+'.o');compiler='clang++' if source.suffix in ('.mm','.cpp') else 'clang'
            execute([compiler,*flags,'-c',str(source),'-o',str(obj)],cache/(source.name+'.build.log'));objects.append(str(obj))
        common=['clang++','-std=c++17',*flags,str(d/'main.mm'),*objects]
        for lib in ['avformat','avcodec','swscale','swresample','avutil']:common.append(str(ROOT/'third_party/ffmpeg/lib'/('lib'+lib+'.a')))
        common+=['-lz']
        for framework in ['AudioToolbox','CoreAudio','CoreFoundation','Cocoa','Metal','QuartzCore','AVFoundation','VideoToolbox','CoreVideo','CoreMedia','Security']:common+=['-framework',framework]
        for name,mutant in [('good',None),('original-present',('void cliprec_present(', 'void unused_cliprec_present(')),('original-arm',('void replay_arm_action(', 'void unused_replay_arm_action('))]:
            source=(RT/'cliprec.mm').read_text();extra=''
            if mutant:
                assert source.count(mutant[0])==1
                source=source.replace(*mutant)
                extra='\nextern "C" '+(ORIGINAL_PRESENT if name=='original-present' else ORIGINAL_ARM)
            path=d/'capture.mm';path.write_text(source+extra);exe=d/name
            execute(common+['-DCLIPREC_SOURCE="'+str(path)+'"','-o',str(exe)],cache/(name+'.build.log'))
            run=subprocess.run([str(exe),str(d/(name+'-clips'))],capture_output=True,text=True,timeout=120);(cache/(name+'.log')).write_text(run.stdout+run.stderr)
            print(name+': '+run.stdout[-1800:],flush=True)
            assert run.returncode==(0 if mutant is None else 1),run.stderr[-2500:]
            if mutant:assert ('production presenter prepares capture' if name=='original-present' else 'registered replay Arm starts buffer') in run.stderr,run.stderr[-2000:]
    print('PRIVATE ADDONS CAPTURE PASS');return 0
if __name__=='__main__':sys.exit(main())
