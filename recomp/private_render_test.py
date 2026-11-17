"""Private rendering dispatch/PNG checks, no Metal device or game image.

Good: 19 native assertions, private Present body/menu frames, selectors and real PNG.
Menu dispatch: good 2 calls / deliberately removed 0 calls (check 3/exit 1).
Broken: drop render_present -> check 3/exit 1; drop PNG writer -> check 14/exit 1;
restore included MW diagnostic -> forbidden MW address rejected; disable draw/stretch -> rejected.
"""
from pathlib import Path
import re
import subprocess
import sys
import tempfile
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
from private_render import body,verify_renderer

sys.path.insert(0,str(HERE/"private_runtime"))
from layers import selected_source

def main():
    d3d=selected_source(HERE.parent/'runtime/d3d9.m')
    render=selected_source(HERE.parent/'runtime/render.m')
    submit=body(render,'shader_submit')
    assert submit.count('compile_entry(e);')==1 and 'dispatch_async' not in submit
    # The daylight fixture executes this seam On/Off and rejects lost restoration.
    assert 'carbon_daynight_shader(original,count,&e->ntokens)' in submit
    assert 'e->tokens = original;' in submit and 'e->ntokens = count;' in submit
    assert 'if (pse->mat)' not in body(render,'draw_impl')
    assert not re.search(r'\bMF32\(0x',body(render,'render_stretch'))
    hdr=(HERE.parent/'runtime/hdrclip.m').read_text()
    private_hdr=selected_source(HERE.parent/'runtime/hdrclip.m')
    pattern=r'\b(?:M32|MF32)\(0x'
    assert len(re.findall(pattern,hdr))==3
    # Job 7 selects native Carbon storage/flow/sim reads; MW reads stay forbidden.
    native_addresses={0xAB08F8,0xAB0690,0xAB0694,0xAB04F4,0xAB04D8,0xAB0B4C,
                      0xA99BBC,0xB4CFD8} | {b+4*i for b in (0xB42F48,0xB42F54,0xB42F60) for i in range(3)}
    def native_hdr_only(source):
        addresses={int(value,16) for value in re.findall(r'\b(?:M32|MF32)\(0x([0-9A-Fa-f]+)u?\)',source)}
        assert addresses==native_addresses,(addresses-native_addresses,native_addresses-addresses)
    native_hdr_only(private_hdr)
    try:native_hdr_only(private_hdr+'\nfloat broken=MF32(0x009885D8u);')
    except AssertionError:pass
    else:raise AssertionError('restored MW diagnostic read accepted')
    good={n:[] for n in ('d3d9.m','render.m','render_present.m','pipeline_cache.m','diag.c')}
    verify_renderer(good)
    for name in ('draw_impl','render_stretch'):
        good['render.m']=[{'name':name,'reason':'MW address dependency disabled'}]
        try:verify_renderer(good)
        except ValueError:pass
        else:raise AssertionError('required renderer loss accepted: '+name)
    good['render.m']=[]
    for name in ('pipeline_library_source','pipeline_build_device','pipeline_cached'):
        good['pipeline_cache.m']=[{'name':name,'reason':'engine implementation disabled'}]
        try:verify_renderer(good)
        except ValueError:pass
        else:raise AssertionError('required pipeline loss accepted: '+name)
    png=body((HERE.parent/'runtime/diag.c').read_text(),'diag_png')
    source='''#include "host.h"
#include <stdlib.h>
#include <CoreGraphics/CoreGraphics.h>
#include <ImageIO/ImageIO.h>
int diag_on=1;static unsigned checks,presents,yields,events,menus;static uint64_t last_frame,last_draws;
static struct {uint64_t frames,frame_draws;} dev;
#define D3D_OK 0
#define CHECK(x) do{++checks;if(!(x)){fprintf(stderr,"failed check %u line %d\\n",checks,__LINE__);return 1;}}while(0)
void render_present(void){++presents;}
void portmenu_frame(void){++menus;}
void user32_script(uint64_t f,uint64_t d){(void)f;(void)d;}
void gil_yield(Cpu*c){(void)c;++yields;}
static int limit_choice;
int *carbon_frame_limit_choice=&limit_choice;
void carbon_picture_wait(void){abort();}
int carbon_simrate_enabled(void){return 0;}
int aa_game_get(void){return 0;}
void diag_frame(uint64_t f,uint64_t d){last_frame=f;last_draws=d;}
void diag_event(const char*fmt,...){(void)fmt;++events;}
// Capture clock behavior is exercised by diag_capture_test; this fixture checks PNG bytes.
void diag_capture_begin(void){}
void diag_capture_end(void){}
'''+(HERE/'private_runtime/frame_shots.h').read_text()+'\nstatic void present(void)'+body(d3d,'present')+'\nstatic int v_Present(Cpu*c)'+body(d3d,'v_Present')+'\nvoid diag_png(const char*path,const void*bgra,uint32_t w,uint32_t h,uint32_t pitch,int keep_alpha)'+png+'''
int main(int argc,char**argv){CHECK(argc==2);Cpu c={0};c.esp=0x8000;dev.frame_draws=9;CHECK(v_Present(&c)==1);CHECK(presents==1&&yields==1&&menus==1);CHECK(c.esp==0x8018);CHECK(dev.frames==1&&dev.frame_draws==0&&last_frame==1&&last_draws==9);CHECK(events==1);
 diag_on=0;c.esp=0x8000;CHECK(v_Present(&c)==1&&events==1&&dev.frames==2&&presents==2&&menus==2);CHECK(private_shot_due(1)==0);diag_on=1;
 unsetenv("BOOT_DIAG_SHOTS");unsetenv("BOOT_DIAG_SHOT_EVERY");CHECK(private_shot_due(1)==2&&private_shot_due(3)==2&&private_shot_due(4)==0&&private_shot_due(300)==2);
 setenv("BOOT_DIAG_SHOTS","2,9,30",1);CHECK(private_shot_due(1)==0&&private_shot_due(2)==2&&private_shot_due(9)==2&&private_shot_due(30)==2);setenv("BOOT_DIAG_SHOT_EVERY","0",1);CHECK(private_shot_due(300)==0);
 setenv("BOOT_DIAG_SEQ","1:3",1);CHECK(private_frame_wanted(1,"BOOT_DIAG_SEQ")==1&&private_frame_wanted(3,"BOOT_DIAG_SEQ")==0);setenv("BOOT_DIAG_SEQ","race+1:3",1);CHECK(!private_frame_wanted(1,"BOOT_DIAG_SEQ"));
 uint32_t pixels[]={0xffff0000,0xff00ff00,0xff0000ff,0xffffffff};diag_png(argv[1],pixels,2,2,8,0);
 CFURLRef url=CFURLCreateFromFileSystemRepresentation(NULL,(const UInt8*)argv[1],strlen(argv[1]),false);CGImageSourceRef input=CGImageSourceCreateWithURL(url,NULL);CHECK(input!=NULL);CGImageRef image=CGImageSourceCreateImageAtIndex(input,0,NULL);CHECK(image&&CGImageGetWidth(image)==2&&CGImageGetHeight(image)==2);
 unsigned char data[16]={0};CGColorSpaceRef cs=CGColorSpaceCreateDeviceRGB();CGContextRef ctx=CGBitmapContextCreate(data,2,2,8,8,cs,kCGImageAlphaNoneSkipFirst|kCGBitmapByteOrder32Little);CHECK(ctx!=NULL);CGContextDrawImage(ctx,CGRectMake(0,0,2,2),image);unsigned sums[3]={0};for(int k=0;k<4;k++)for(int c=0;c<3;c++)sums[c]+=data[k*4+c];CHECK(sums[0]==510&&sums[1]==510&&sums[2]==510);CHECK(data[0]==0&&data[1]==0&&data[2]==255);
 CGContextRelease(ctx);CGColorSpaceRelease(cs);CGImageRelease(image);CFRelease(input);CFRelease(url);unsetenv("BOOT_DIAG_DRAWS");CHECK(!private_frame_wanted(9,"BOOT_DIAG_DRAWS"));printf("PRIVATE RENDER/PNG PASS checks=%u presents=%u\\n",checks,presents);return 0;}
'''
    with tempfile.TemporaryDirectory(prefix='private-render-') as td:
        out=Path(td)
        for mutant in ('good','present','menu','png'):
            selected=source
            if mutant=='present':selected=selected.replace('    render_present();','    /* broken: no render present */')
            if mutant=='menu':selected=selected.replace('    portmenu_frame();','    /* broken: no menu frame */')
            if mutant=='png':selected=selected.replace(png,'{}')
            path=out/'test.c';binary=out/'test';path.write_text(selected)
            cmd=['clang','-O1','-g','-fsanitize=address,undefined','-I',str(HERE),'-I',str(HERE.parent/'runtime'),str(path),'-framework','CoreGraphics','-framework','CoreFoundation','-framework','ImageIO','-o',str(binary)]
            r=subprocess.run(cmd,capture_output=True,text=True)
            if r.returncode:raise RuntimeError(r.stderr[-2000:])
            shot=out/(mutant+'.png');r=subprocess.run([str(binary),str(shot)],capture_output=True,text=True)
            print(mutant+': '+r.stdout.strip()+r.stderr.strip());assert r.returncode==(0 if mutant=='good' else 1)
    print('PRIVATE RENDER PASS required-body guard rejects=5 (deliberately disabled draw/stretch/pipeline)')


if __name__=='__main__':main()
