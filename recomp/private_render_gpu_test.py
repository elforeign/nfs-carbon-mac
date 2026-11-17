"""Metal check of the private D3D COM/draw/Present/PNG path.

No game image is loaded or linked. Both render-thread modes wait for the
submitted frame's GPU completion serial before independent queue readback.
Shader compilation is synchronous (NFS_ASYNC_SHADERS=0). The FF fixture uses
both XYZ/TEX1 and XYZRHW/TEX1 vertices, including the screen-to-clip path.
Good: clear and textured triangle pixels plus
first-frame PNGs. Broken: omit triangle draw -> pixel assertion fails. Exit 3
Also samples a synthetic DDS volume via the real 3D upload path and saves its
in-flight backbuffer through D3DX synchronous readback, then tests a CPU-to-rendered
surface copy; four PNGs. Broken controls: absent draw, wrong volume, omitted copy.
when private runtime artifacts or a Metal device are absent. --build-only does
not create a device and is safe for the offline compilation check.
"""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
from build_private import ignored_output
sys.path.insert(0,str(HERE/"private_runtime"))
from layers import selected_source


def build(out):
    root=out.parent
    dst=root/'runtime'
    source=selected_source(HERE.parent/'runtime/d3d9.m')
    def index(array,name):
        data=re.search(r'\b'+array+r'\[\]\s*=\s*\{(.*?)\};',source,re.S)[1]
        values=re.findall(r'"([^"]+)"',data)
        return values.index(name)
    defs='\n'.join(f'#define SLOT_{n} {index("n_device",n)}' for n in ('Clear','Present','CreateTexture','SetTexture','SetTextureStageState','SetRenderState','SetFVF','DrawPrimitiveUP'))
    harness=out/'test.m'
    harness.write_text(r'''#include "d3d9_internal.h"
#import <ImageIO/ImageIO.h>
#include <sys/mman.h>
#include <unistd.h>
#include <stdarg.h>
const uint32_t guest_func_addr[]={0};void (*const guest_func_ptr[])(Cpu*)={0};const unsigned guest_func_count=0;const uint32_t speed_entry=0;
/* This host-only fixture must never enter native startup completion. */
void f_0059B1B0(Cpu *c){(void)c;abort();}
const char speed_exe_fingerprint[]="",speed_exe_sha256[]="",speed_exe_region_sha256[4][65]={{0}};
const struct ExeRegion {const char *name;uint32_t rva,size;} speed_exe_regions[3]={{0}};
const struct {uint32_t slot;const char *name;} speed_imports[]={{0,0}};const unsigned speed_import_count=0;
extern int win32_d3d9(Cpu*,const char*);extern void threads_init(void);extern void diag_init(void);
extern int private_d3dx_textures(Cpu*,const char*);
extern uint64_t frame_serial,done_serial;extern void wait_serial(uint64_t);
#define CHECK(v) do{if(!(v)){fprintf(stderr,"GPU CHECK line %d failed: %s\n",__LINE__,#v);return 1;}}while(0)
'''+defs+r'''
static uint32_t invoke(Cpu*c,uint32_t self,unsigned slot,int n,...){c->esp=0x100000;M32(c->esp)=0xfeed;M32(c->esp+4)=self;va_list ap;va_start(ap,n);for(int i=1;i<n;i++)M32(c->esp+4+4*i)=va_arg(ap,uint32_t);va_end(ap);dispatch(c,M32(M32(self)+4*slot));if(c->esp!=0x100004+4*(uint32_t)n){fprintf(stderr,"GPU bad stdcall stack\n");exit(1);}return c->eax;}
static uint32_t texture_api(Cpu*c,const char*name,unsigned n,...){c->esp=0x100000;M32(c->esp)=0xfeed;va_list ap;va_start(ap,n);for(unsigned k=0;k<n;k++)M32(c->esp+4+4*k)=va_arg(ap,uint32_t);va_end(ap);if(!private_d3dx_textures(c,name)||c->esp!=0x100004+4*n)exit(2);return c->eax;}
static int await_present(void){uint64_t submitted=frame_serial-1;gil_release();wait_serial(submitted);gil_acquire();return __atomic_load_n(&done_serial,__ATOMIC_ACQUIRE)>=submitted;}
static int png_pixel(const char*path,unsigned x,unsigned y,uint32_t expected){
 for(int k=0;k<5000;k++){@autoreleasepool{
  CFURLRef url=CFURLCreateFromFileSystemRepresentation(NULL,(const UInt8*)path,strlen(path),false);
  CGImageSourceRef src=CGImageSourceCreateWithURL(url,NULL);CGImageRef image=NULL;
  if(src && CGImageSourceGetStatus(src)==kCGImageStatusComplete)image=CGImageSourceCreateImageAtIndex(src,0,NULL);
  int valid=image && CGImageGetWidth(image)==64 && CGImageGetHeight(image)==64,okay=0;
  if(valid){uint32_t pixels[64*64]={0};CGColorSpaceRef cs=CGColorSpaceCreateDeviceRGB();CGContextRef ctx=CGBitmapContextCreate(pixels,64,64,8,256,cs,kCGImageAlphaNoneSkipFirst|kCGBitmapByteOrder32Little);if(ctx){CGContextDrawImage(ctx,CGRectMake(0,0,64,64),image);okay=(pixels[y*64+x]&0xffffff)==(expected&0xffffff);CGContextRelease(ctx);}CGColorSpaceRelease(cs);}
  if(image)CGImageRelease(image);if(src)CFRelease(src);CFRelease(url);if(valid)return okay;
 }usleep(1000);}return 0;
}
static int run(const char*folder,int mutant,int positiont){
 if(!MTLCreateSystemDefaultDevice()){puts("SKIP: Metal device unavailable");return 3;}
 G=mmap(NULL,1ull<<32,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANON,-1,0);CHECK(G!=MAP_FAILED);threads_init();diag_init();Cpu c={0};c.fs_base=0x7000;
 c.esp=0x100000;M32(c.esp)=0xfeed;M32(c.esp+4)=32;CHECK(win32_d3d9(&c,"Direct3DCreate9"));uint32_t d3d=c.eax;
 uint32_t pp=0x4000;M32(pp)=64;M32(pp+4)=64;M32(pp+8)=21;M32(pp+12)=1;M32(pp+24)=1;M32(pp+32)=1;M32(pp+36)=1;M32(pp+40)=75;
 CHECK(invoke(&c,d3d,16,7,0u,1u,0u,2u,pp,0x4100u)==0);uint32_t device=M32(0x4100);CHECK(device&&mtl&&queue);
 CHECK(invoke(&c,device,SLOT_Clear,7,0u,0u,1u,0xffff0000u,0x3f800000u,0u)==0);
 CHECK(invoke(&c,device,SLOT_Present,5,0u,0u,0u,0u)==0);
 CHECK(await_present());
 id<MTLCommandBuffer> wait=[queue commandBuffer];[wait commit];[wait waitUntilCompleted];CHECK(wait.status==MTLCommandBufferStatusCompleted);
 char path[4096];snprintf(path,sizeof path,"%s/frame_00001.png",folder);CHECK(png_pixel(path,8,8,0xffff0000u));
 id<MTLBuffer> read=[mtl newBufferWithLength:64*64*4 options:MTLResourceStorageModeShared];id<MTLCommandBuffer> cb=[queue commandBuffer];id<MTLBlitCommandEncoder> blit=[cb blitCommandEncoder];extern id<MTLTexture> backbuffer_tex;
 [blit copyFromTexture:backbuffer_tex sourceSlice:0 sourceLevel:0 sourceOrigin:MTLOriginMake(0,0,0) sourceSize:MTLSizeMake(64,64,1) toBuffer:read destinationOffset:0 destinationBytesPerRow:256 destinationBytesPerImage:16384];[blit endEncoding];[cb commit];[cb waitUntilCompleted];CHECK(((uint32_t*)read.contents)[8*64+8]==0xffff0000u);
 CHECK(invoke(&c,device,SLOT_CreateTexture,9,1u,1u,1u,0u,21u,1u,0x4200u,0u)==0);uint32_t texture=M32(0x4200);CHECK(invoke(&c,texture,19,5,0u,0x4300u,0u,0u)==0);M32(M32(0x4304))=0xff00ff00;CHECK(invoke(&c,texture,20,2,0u)==0);
 CHECK(invoke(&c,device,SLOT_SetTexture,3,0u,texture)==0);CHECK(invoke(&c,device,SLOT_SetFVF,2,positiont?0x104u:0x102u)==0);
 CHECK(invoke(&c,device,SLOT_SetRenderState,3,7u,0u)==0);CHECK(invoke(&c,device,SLOT_SetRenderState,3,22u,1u)==0);CHECK(invoke(&c,device,SLOT_SetRenderState,3,137u,0u)==0);
 CHECK(invoke(&c,device,SLOT_SetTextureStageState,4,0u,1u,2u)==0);CHECK(invoke(&c,device,SLOT_SetTextureStageState,4,0u,2u,2u)==0);CHECK(invoke(&c,device,SLOT_SetTextureStageState,4,0u,4u,2u)==0);CHECK(invoke(&c,device,SLOT_SetTextureStageState,4,0u,5u,2u)==0);
 // XYZ + TEX1, identity W/V/P: clip corners map to screen (0,0),(64,0),(0,64).
 float vertices[]={-1,1,0,0,0, 1,1,0,1,0, -1,-1,0,0,1};
 float screen[]={0,0,0,1,0,0, 64,0,0,1,1,0, 0,64,0,1,0,1};
 if(positiont)memcpy(G+0x5000,screen,sizeof screen);else memcpy(G+0x5000,vertices,sizeof vertices);
 CHECK(invoke(&c,device,SLOT_Clear,7,0u,0u,1u,0xff0000ffu,0x3f800000u,0u)==0);
 if(mutant!=1)CHECK(invoke(&c,device,SLOT_DrawPrimitiveUP,5,4u,1u,0x5000u,positiont?24u:20u)==0);
 CHECK(invoke(&c,device,SLOT_Present,5,0u,0u,0u,0u)==0);CHECK(await_present());cb=[queue commandBuffer];blit=[cb blitCommandEncoder];[blit copyFromTexture:backbuffer_tex sourceSlice:0 sourceLevel:0 sourceOrigin:MTLOriginMake(0,0,0) sourceSize:MTLSizeMake(64,64,1) toBuffer:read destinationOffset:0 destinationBytesPerRow:256 destinationBytesPerImage:16384];[blit endEncoding];[cb commit];[cb waitUntilCompleted];CHECK(cb.status==MTLCommandBufferStatusCompleted);
 if(((uint32_t*)read.contents)[8*64+8]!=0xff00ff00u)fprintf(stderr,"GPU draw pixel=%08X background=%08X submitted=%llu completed=%llu\n",((uint32_t*)read.contents)[8*64+8],((uint32_t*)read.contents)[56*64+56],(unsigned long long)(frame_serial-1),(unsigned long long)__atomic_load_n(&done_serial,__ATOMIC_ACQUIRE));
 CHECK(((uint32_t*)read.contents)[8*64+8]==0xff00ff00u);CHECK(((uint32_t*)read.contents)[56*64+56]==0xff0000ffu);
 snprintf(path,sizeof path,"%s/frame_00002.png",folder);CHECK(png_pixel(path,8,8,0xff00ff00u));CHECK(png_pixel(path,56,56,0xff0000ffu));
 // A one-voxel green volume, loaded from DDS through the same native objects.
 uint32_t dds=0x8000;memset(G+dds,0,132);memcpy(G+dds,"DDS ",4);M32(dds+4)=124;M32(dds+8)=0x80100f;M32(dds+12)=M32(dds+16)=M32(dds+24)=1;M32(dds+20)=4;M32(dds+28)=1;M32(dds+76)=32;M32(dds+80)=0x41;M32(dds+88)=32;M32(dds+92)=0xff0000;M32(dds+96)=0xff00;M32(dds+100)=0xff;M32(dds+104)=0xff000000;M32(dds+108)=0x1000;M32(dds+112)=0x200000;M32(dds+128)=0xff00ff00;
 if(mutant==2)M32(dds+128)=0xffff0000u;
 CHECK(texture_api(&c,"D3DXCreateVolumeTextureFromFileInMemory",4,device,dds,132u,0x4210u)==0);CHECK(invoke(&c,device,SLOT_SetTexture,3,0u,M32(0x4210))==0);
 CHECK(invoke(&c,device,SLOT_Clear,7,0u,0u,1u,0xff0000ffu,0x3f800000u,0u)==0);CHECK(invoke(&c,device,SLOT_DrawPrimitiveUP,5,4u,1u,0x5000u,positiont?24u:20u)==0);
 // Readback must submit and wait for the current render-thread recording;
 // this happens BEFORE Present, while the 3D-textured triangle is in flight.
 CHECK(texture_api(&c,"D3DXSaveSurfaceToFileInMemory",5,0x4214u,4u,dev.backbuffer,0u,0u)==0);uint32_t buffer=M32(0x4214);uint32_t data=invoke(&c,buffer,3,1);CHECK(invoke(&c,buffer,4,1)==128+64*64*4);CHECK(M32(data+128+4*(8*64+8))==0xff00ff00u&&M32(data+128+4*(56*64+56))==0xff0000ffu);invoke(&c,buffer,2,1);
 CHECK(invoke(&c,device,SLOT_Present,5,0u,0u,0u,0u)==0);CHECK(await_present());snprintf(path,sizeof path,"%s/frame_00003.png",folder);CHECK(png_pixel(path,8,8,0xff00ff00u)&&png_pixel(path,56,56,0xff0000ffu));
 // A CPU texture copied into a rendered surface must upload to Metal, retaining
 // the red background outside its rectangle. This also exercises a pending Clear.
 CHECK(invoke(&c,device,SLOT_Clear,7,0u,0u,1u,0xffff0000u,0x3f800000u,0u)==0);CHECK(invoke(&c,texture,18,3,0u,0x4218u)==0);M32(0x8300)=M32(0x8304)=8;M32(0x8308)=M32(0x830c)=24;
 if(mutant!=3)CHECK(texture_api(&c,"D3DXLoadSurfaceFromSurface",8,dev.backbuffer,0u,0x8300u,M32(0x4218),0u,0u,2u,0u)==0);
 CHECK(texture_api(&c,"D3DXSaveSurfaceToFileInMemory",5,0x4214u,4u,dev.backbuffer,0u,0u)==0);buffer=M32(0x4214);data=invoke(&c,buffer,3,1);CHECK(M32(data+128+4*(16*64+16))==0xff00ff00u&&M32(data+128+4*(56*64+56))==0xffff0000u);invoke(&c,buffer,2,1);
 CHECK(invoke(&c,device,SLOT_Present,5,0u,0u,0u,0u)==0);CHECK(await_present());snprintf(path,sizeof path,"%s/frame_00004.png",folder);CHECK(png_pixel(path,16,16,0xff00ff00u)&&png_pixel(path,56,56,0xffff0000u));
 puts("PRIVATE GPU PASS: clear + 2D/3D triangles + D3DX readback/upload + 4 PNGs");return 0;}
int main(int argc,char**argv){@autoreleasepool{if(argc!=4)return 2;return run(argv[1],atoi(argv[2]),atoi(argv[3]));}}
''')
    obj=out/'fixture.o';boot=out/'boot_test.o';flags=['-O1','-g','-w','-I',str(dst),'-I',str(HERE),'-I',str(root),'-DNFS_GAME=2','-I',str(HERE.parent/'runtime')]
    for path,target,extra in [(harness,obj,['-fobjc-arc']), (dst/'boot.c',boot,['-Dmain=private_boot_main'])]:
        r=subprocess.run(['clang',*flags,*extra,'-c',str(path),'-o',str(target)],capture_output=True,text=True)
        if r.returncode:raise RuntimeError(r.stderr[-2500:])
    command=json.loads((root/'link_command.json').read_text());new=[];i=0
    while i<len(command):
        arg=command[i]
        if arg=='-o':new+=['-o',str(out/'test')];i+=2;continue
        if arg.endswith('/boot.c.o'):new.append(str(boot))
        elif arg.endswith('/imports.c.o'):pass
        elif arg.endswith('.a') and Path(arg).parent==root:new.append(str(obj))
        else:new.append(arg)
        i+=1
    r=subprocess.run(new,capture_output=True,text=True)
    if r.returncode:raise RuntimeError(r.stderr[-2500:])
    return out/'test'


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--out',type=Path,default=HERE/'out/carbon/render_gpu_test');ap.add_argument('--build-only',action='store_true');args=ap.parse_args()
    # A copied link manifest is not proof of a build in this checkout.
    build_root=args.out.parent
    if not all((build_root/name).is_file() for name in
               ('link_command.json','NFSC.a','runtime/disabled_providers.m.o')):
        print('SKIP: private runtime build absent for this checkout');return 3
    command=json.loads((build_root/'link_command.json').read_text())
    archives=[Path(arg).resolve() for arg in command if arg.endswith('/NFSC.a')]
    assert len(archives)==1, 'private runtime guest archive entry missing or ambiguous'
    if archives[0] != (build_root/'NFSC.a').resolve():
        print('SKIP: private runtime link belongs to another checkout');return 3
    out=ignored_output(args.out);binary=build(out)
    if args.build_only:print('PRIVATE GPU CHECK BUILT (not executed)');return 0
    for positiont,threaded,mutant in ((p,t,m) for p in (0,1) for t in (0,1) for m in (0,1,2,3)):
        label=('positiont' if positiont else 'xyz')+'_thread_'+str(threaded)
        folder=out/(('broken_'+str(mutant)+'_' if mutant else 'good_')+label);folder.mkdir(exist_ok=True)
        for path in folder.glob('frame_*.png'):path.unlink()
        env={**os.environ,'BOOT_DIAG':str(folder),'BOOT_USERDATA':str(folder/'userdata'),'BOOT_DIAG_SHOTS':'1,2,3,4','BOOT_DIAG_SHOT_EVERY':'0','NFS_ASYNC_SHADERS':'0','BOOT_DIAG_MSL':'1','NFS_RENDER_THREAD':str(threaded)}
        r=subprocess.run([str(binary),str(folder),str(mutant),str(positiont)],capture_output=True,text=True,env=env,timeout=60)
        (folder/'run.log').write_text(r.stdout+r.stderr)
        if r.returncode==3:print('SKIP: Metal device unavailable');return 3
        print(('broken '+str(mutant)+' ' if mutant else 'good ')+label+': exit='+str(r.returncode)+' '+r.stdout.strip())
        if r.returncode!=(1 if mutant else 0):raise RuntimeError(r.stderr[-2000:])
    print('PRIVATE GPU REGRESSION PASS (missing triangle rejected)');return 0


if __name__=='__main__':sys.exit(main())
