"""Production Metal lamp pass: flat depth plane, white lamp 8 m above it.

Number: luma gain beneath the lamp minus gain 30 m away, >=8 code values.
Broken control: emission shifted 40 m sideways, must give <2 code values.
Measured numbers: 1x and 4x local gain 29.000000; shifted control -6.000000. This is a fixture,
not presented-frame game proof. Faint flare glow (receiver mask 250, alpha 2%): gain 28 (1x and 4x)
(>= local gain - 2); the pinned binary cut (mask < .999 gets no light, which drew hard-edged
flare quads into the lamp pools) gives 0, rejected (exit 1).
not presented-frame game proof. Authored colour: adapted xy (.290067899,.313228432),
no-adaptation dxy .004602300 (rejected at .003). No Metal or private image: exit 3.
"""
from pathlib import Path
import ast
import hashlib
import json
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = ROOT / 'recomp/private_runtime'


def shader(source, name):
    body = source.split('static const char *' + name + ' =', 1)[1].split(';\n', 1)[0]
    return ''.join(ast.literal_eval(m[0]) for m in re.finditer(r'"(?:[^"\\]|\\.)*"', body))


HARNESS = r'''
#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
static uint8_t guest[0xc00000];
#define M32(a) (*(uint32_t *)(guest+(a)))
#define M8(a) (*(uint8_t *)(guest+(a)))
#define MF32(a) (*(float *)(guest+(a)))
static id<MTLDevice> mtl;
static id<MTLCommandBuffer> cmd;
static int diag_on,gpt_on,lookups;
static const char *diag_dir="/tmp",*variant="";
static int proof_due;
int postfx_look_listed(const char *v){return proof_due;}
int postfx_look_variant(const char *v){return !strcmp(v,variant);}
#define diag_event(...) ((void)0)
#define gpt_render(...) ((void)0)
#define gpt_name(...) ((void)0)
uint64_t diag_current_frame(void){return 0;}
static int diag_shot_due(uint64_t n){return proof_due;}
static float lamp_level=1;
float carbon_dn_lamps_level(void){return lamp_level;}
typedef struct {id<MTLTexture> tex,ms;int stale;} RenderTex;
static RenderTex world,depth;
static id<MTLTexture> mask;
static RenderTex *carbon_hdr_rt(uint32_t h){++lookups;return h==1?&world:h==2?&depth:NULL;}
static void end_pass(void){}
static void ensure_cmd(void){}
static void msaa_resolve(RenderTex *r){}
static id<MTLTexture> carbon_ao_receiver(id<MTLTexture> z){return mask;}
static id<MTLLibrary> pipeline_library_source(NSString *s,const char *label,NSError **error){return [mtl newLibraryWithSource:s options:nil error:error];}
static id<MTLRenderPipelineState> pipeline_build(MTLRenderPipelineDescriptor *d,const char *label,NSError **error){
 NSError *e=nil;id<MTLRenderPipelineState> p=[mtl newRenderPipelineStateWithDescriptor:d error:&e];
 if(!p){fprintf(stderr,"pipeline: %s\n",e.localizedDescription.UTF8String);exit(1);}return p;
}
SHADERS
static const char *render_contact_source(int n){return contact;}
PRODUCTION
#define CHECK(x) do{if(!(x)){fprintf(stderr,"FAIL %s\n",#x);return 1;}}while(0)
static id<MTLTexture> texture(MTLPixelFormat format,unsigned samples){
 MTLTextureDescriptor *d=[MTLTextureDescriptor texture2DDescriptorWithPixelFormat:format width:256 height:128 mipmapped:NO];
 d.usage=MTLTextureUsageRenderTarget|MTLTextureUsageShaderRead;d.storageMode=MTLStorageModeShared;
 if(samples>1){d.textureType=MTLTextureType2DMultisample;d.sampleCount=samples;d.storageMode=MTLStorageModePrivate;}
 return [mtl newTextureWithDescriptor:d];
}
static void clear_targets(void){
 MTLRenderPassDescriptor *rp=[MTLRenderPassDescriptor renderPassDescriptor];
 rp.colorAttachments[0].texture=world.ms?:world.tex;rp.colorAttachments[0].loadAction=MTLLoadActionClear;rp.colorAttachments[0].storeAction=MTLStoreActionStore;rp.colorAttachments[0].clearColor=MTLClearColorMake(.25,.25,.25,.37);
 [[cmd renderCommandEncoderWithDescriptor:rp] endEncoding];
 rp=[MTLRenderPassDescriptor renderPassDescriptor];rp.depthAttachment.texture=depth.tex;rp.depthAttachment.loadAction=MTLLoadActionClear;rp.depthAttachment.storeAction=MTLStoreActionStore;
 rp.depthAttachment.clearDepth=(10000.0-10000.0/16.0)/9999.0;
 [[cmd renderCommandEncoderWithDescriptor:rp] endEncoding];
}
static unsigned char pixels[256*128*4];
static void read_pixels(void){
 if(world.ms){MTLRenderPassDescriptor *rp=[MTLRenderPassDescriptor renderPassDescriptor];rp.colorAttachments[0].texture=world.ms;rp.colorAttachments[0].resolveTexture=world.tex;rp.colorAttachments[0].loadAction=MTLLoadActionLoad;rp.colorAttachments[0].storeAction=MTLStoreActionMultisampleResolve;[[cmd renderCommandEncoderWithDescriptor:rp] endEncoding];}
 [cmd commit];[cmd waitUntilCompleted];if(cmd.status!=MTLCommandBufferStatusCompleted)exit(1);
 [world.tex getBytes:pixels bytesPerRow:256*4 fromRegion:MTLRegionMake2D(0,0,256,128) mipmapLevel:0];
}
static double luma(unsigned x){unsigned char *p=pixels+4*(64*256+x);return .2126*p[0]+.7152*p[1]+.0722*p[2];}
int main(int argc,char **argv){@autoreleasepool{
 if(argc>1)diag_dir=argv[1];
 mtl=MTLCreateSystemDefaultDevice();if(!mtl)return 3;
 id<MTLCommandQueue> queue=[mtl newCommandQueue];
 setenv("NFS_CARBON_LAMPLIGHT","off",1);carbon_lamplight_init();CHECK(!carbon_lamplight_on);carbon_lamplight_apply();CHECK(!lookups&&!carbon_lamplight_library&&!carbon_lamps);
 M32(0xA99BBC)=6;M32(0xAB04F4)=1;M32(0xAB04F8)=2;M32(0xB4AF90)=0x3000;
 for(unsigned i=0;i<4;i++)MF32(0x3000+20*i)=1;
 MF32(0x3040)=1.0f/3;MF32(0x3054)=1;MF32(0x3068)=10000.0f/9999;MF32(0x3078)=-10000.0f/9999;
 M32(0xB479D4)=0x1000;M32(0x1000)=0xB479D4;M32(0x1018)=0x2000;M32(0x101c)=1;
 M8(0x2004)=2;M8(0x2007)=1;M32(0x200c)=0xffffff;MF32(0x2018)=8;MF32(0x201c)=25;MF32(0x2030)=10;strcpy((char *)guest+0x203e,"Street_Fixture");
 unsetenv("NFS_CARBON_LAMPLIGHT");carbon_lamplight_init();CHECK(carbon_lamplight_on);
 lamp_level=0;carbon_lamplight_apply();CHECK(!lookups);lamp_level=1;
 mask=texture(MTLPixelFormatR8Unorm,1);unsigned char coverage[256*128];memset(coverage,255,sizeof coverage);[mask replaceRegion:MTLRegionMake2D(0,0,256,128) mipmapLevel:0 withBytes:coverage bytesPerRow:256];
 for(unsigned samples=1;samples<=4;samples*=4){
  if(![mtl supportsTextureSampleCount:samples])continue;
  world.tex=texture(MTLPixelFormatRGBA8Unorm,1);world.ms=samples>1?texture(MTLPixelFormatRGBA8Unorm,samples):nil;depth.tex=texture(MTLPixelFormatDepth32Float,1);
  double base[2];carbon_lamplight_on=0;cmd=[queue commandBuffer];clear_targets();carbon_lamplight_apply();read_pixels();base[0]=luma(128);base[1]=luma(208);
  double measured[2];
  for(int shifted=0;shifted<2;shifted++){
   carbon_lamplight_on=1;carbon_lamplight_shift=shifted;cmd=[queue commandBuffer];clear_targets();carbon_lamplight_apply();read_pixels();
   measured[shifted]=(luma(128)-base[0])-(luma(208)-base[1]);
   CHECK(pixels[4*(64*256+128)+3]==94);
  }
  printf("samples=%u local_gain=%.6f shifted_control=%.6f\n",samples,measured[0],measured[1]);CHECK(measured[0]>=8);CHECK(measured[1]<2);
  memset(coverage,0,sizeof coverage);[mask replaceRegion:MTLRegionMake2D(0,0,256,128) mipmapLevel:0 withBytes:coverage bytesPerRow:256];
  cmd=[queue commandBuffer];clear_targets();carbon_lamplight_shift=0;carbon_lamplight_apply();read_pixels();CHECK(luma(128)==base[0]);
  /* A flare's faint glow tail (alpha 2%, receiver mask 250) keeps the light it leaves. */
  memset(coverage,250,sizeof coverage);[mask replaceRegion:MTLRegionMake2D(0,0,256,128) mipmapLevel:0 withBytes:coverage bytesPerRow:256];
  cmd=[queue commandBuffer];clear_targets();carbon_lamplight_apply();read_pixels();
  double faint=(luma(128)-base[0])-(luma(208)-base[1]);printf("samples=%u faint_glow_gain=%.6f\n",samples,faint);CHECK(faint>=measured[0]-2);
  memset(coverage,255,sizeof coverage);[mask replaceRegion:MTLRegionMake2D(0,0,256,128) mipmapLevel:0 withBytes:coverage bytesPerRow:256];
 }
 // Authored linear record; independent double-precision XYZ reference.
 M32(0x200c)=158|(204<<8)|(240<<16);carbon_lamps_signature=0;
 CarbonLampParams colour={0};unsigned colour_overflow=0;
 CHECK(carbon_lamplight_select(0x3000,1,&colour,&colour_overflow)==1);
 double authored[]={158.0/255,204.0/255,240.0/255};
 double Y=.2126*authored[0]+.7152*authored[1]+.0722*authored[2];
 double X=.4124564*authored[0]+.3575761*authored[1]+.1804375*authored[2];
 double Z=.0193339*authored[0]+.1191920*authored[1]+.9503041*authored[2];
 double ax=.85*X+.15*.95047*Y,az=.85*Z+.15*1.08883*Y;
 double expected[]={ax/(ax+Y+az),Y/(ax+Y+az)};
 float *rgb=colour.lamps[0].rgb;
 double x=.4124564*rgb[0]+.3575761*rgb[1]+.1804375*rgb[2];
 double y=.2126729*rgb[0]+.7151522*rgb[1]+.0721750*rgb[2];
 double z=.0193339*rgb[0]+.1191920*rgb[1]+.9503041*rgb[2];
 double dxy=hypot(x/(x+y+z)-expected[0],y/(x+y+z)-expected[1]);
 double sy=.2126729*authored[0]+.7151522*authored[1]+.0721750*authored[2];
 double broken=hypot(X/(X+sy+Z)-expected[0],sy/(X+sy+Z)-expected[1]);
 printf("authored 158/204/240 adapted_linear=%.9f,%.9f,%.9f xy=%.9f,%.9f dxy=%.9f no_adaptation_dxy=%.9f\n",rgb[0],rgb[1],rgb[2],x/(x+y+z),y/(x+y+z),dxy,broken);
 CHECK(dxy<.003 && broken>.003);CHECK(fabs(lighting_colour_luminance(rgb)-Y)<1e-6);
 diag_on=1;variant="lamplightoff";lookups=0;carbon_lamplight_apply();CHECK(!lookups);
 variant="lamplightshift";CHECK(carbon_lamplight_select(0x3000,1,&colour,&colour_overflow)==1);CHECK(colour.lamps[0].position[0]==40);
 diag_on=0;CHECK(carbon_lamplight_select(0x3000,1,&colour,&colour_overflow)==1);CHECK(colour.lamps[0].position[0]==0);variant="";
 // A changed pack count invalidates the cache; keep exactly the closest 24.
 M32(0x101c)=32;
 for(unsigned i=0;i<32;i++){uint32_t r=0x2000+96*i;memset(guest+r,0,96);M8(r+4)=2;M8(r+7)=1;M32(r+0xc)=0xffffff;MF32(r+0x10)=i;MF32(r+0x18)=8;MF32(r+0x1c)=25;MF32(r+0x30)=10;strcpy((char *)guest+r+0x3e,"STREET_fixture");}
 M8(0x2000+96*30+7)=0;MF32(0x2000+96*31+0x1c)=NAN;
 CarbonLampParams selection={0};unsigned overflow=0;carbon_lamplight_shift=0;
 CHECK(carbon_lamplight_select(0x3000,1,&selection,&overflow)==24);CHECK(overflow==6&&carbon_lamps_count==30);
 CHECK(selection.lamps[0].position[0]==0&&selection.lamps[23].position[0]==23);
 // Real sidecar blit must accept the production half-size receiver mask.
 MTLTextureDescriptor *md=[MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatR8Unorm width:128 height:64 mipmapped:NO];
 md.usage=MTLTextureUsageShaderRead;md.storageMode=MTLStorageModeShared;mask=[mtl newTextureWithDescriptor:md];
 unsigned char half[128*64];memset(half,255,sizeof half);[mask replaceRegion:MTLRegionMake2D(0,0,128,64) mipmapLevel:0 withBytes:half bytesPerRow:128];
 diag_on=1;proof_due=1;cmd=[queue commandBuffer];clear_targets();carbon_lamplight_apply();read_pixels();
 char proof_path[1024];snprintf(proof_path,sizeof proof_path,"%s/lamplight_00001.lmp",diag_dir);
 FILE *proof_file=fopen(proof_path,"rb");CHECK(proof_file);fseek(proof_file,0,SEEK_END);
 CHECK(ftell(proof_file)==100+36*30+5*256*128);fseek(proof_file,100+36*30+4*256*128,SEEK_SET);
 for(unsigned i=0;i<256*128;i++)CHECK(fgetc(proof_file)==255);fclose(proof_file);proof_due=0;diag_on=0;
 printf("PASS sidecar depth plus half-size receiver mask expanded at nearest samples\n");
 M32(0xB479D4)=0xB479D4;CHECK(carbon_lamplight_select(0x3000,1,&selection,&overflow)==0&&carbon_lamps_count==0);
 printf("PASS production lamp pass, Off no lookup/allocation, day level zero, protected receiver, RGB-only blending\n");return 0;
}}
'''


def main():
    if not (ROOT / 'recomp/out/carbon-base/image.json').is_file():
        print('SKIP private lamplight: private image absent')
        return 3
    feature = json.loads((PRIVATE / 'features/lamplight.json').read_text())
    assert feature['staged_sources']['carbon_lamplight.h'] == 'carbon_lamplight.h'
    post = (ROOT / 'runtime/render_post.m').read_text()
    ao = (PRIVATE / 'carbon_ao.h').read_text()
    production = (PRIVATE / 'carbon_lamplight.h').read_text()
    shaders = 'static const char *contact=' + json.dumps(shader(post, 'ssao_legacy_src')) + ';\n'
    shaders += 'static const char *carbon_ao_vertex=' + json.dumps(shader(ao, 'carbon_ao_vertex')) + ';\n'
    source = HARNESS.replace('SHADERS', shaders).replace('PRODUCTION', production)
    with tempfile.TemporaryDirectory(prefix='private-lamplight-') as directory:
        path = Path(directory)
        (path / 'fixture.m').write_text(source)
        build = subprocess.run(['clang', '-I', str(ROOT / 'runtime'), '-O1', '-w', '-fobjc-arc', str(path / 'fixture.m'), '-framework', 'Foundation', '-framework', 'Metal', '-o', str(path / 'fixture')], capture_output=True, text=True)
        assert build.returncode == 0, build.stderr[-4000:]
        run = subprocess.run([str(path / 'fixture'), str(path)], capture_output=True, text=True, timeout=90)
        proof = ROOT / '.metal-cache/proof-tests/lamplight.txt'
        proof.parent.mkdir(parents=True, exist_ok=True)
        proof.write_text(run.stdout + run.stderr)
        print(run.stdout, run.stderr[-3000:], end='')
        if run.returncode == 3:
            return 3
        assert run.returncode == 0, run.stderr[-3000:]
        broken = production.replace('lighting_colour_adapt(lamp.rgb);', '/* missing adaptation */')
        assert broken != production
        (path / 'fixture.m').write_text(HARNESS.replace('SHADERS', shaders).replace('PRODUCTION', broken))
        control_build = subprocess.run(['clang', '-I', str(ROOT / 'runtime'), '-O1', '-w', '-fobjc-arc', str(path / 'fixture.m'), '-framework', 'Foundation', '-framework', 'Metal', '-o', str(path / 'broken')], capture_output=True, text=True)
        assert control_build.returncode == 0, control_build.stderr[-4000:]
        control = subprocess.run([str(path / 'broken'), str(path)], capture_output=True, text=True, timeout=90)
        assert control.returncode == 1
        assert 'dxy<.003' in control.stderr, control.stderr
        print('BROKEN production without adaptation (rejected):', control.stdout.strip().splitlines()[-1])
        cut = ('"float raw=ao_depth(z,i.uv,c.k);if(raw>=0.999999||mask.sample(pt,c.k.rect.xy+i.uv*c.k.rect.zw).r<0.999)return float4(0);"\n'
               '"float3 p=ao_point(i.uv,raw,c.k),n=ao_normal(z,i.uv,c.k),energy=float3(0);"')
        assert hashlib.sha256(cut.encode()).hexdigest() == 'b41052984b48254b4928d6333ed5182c84e16ca7400b8336ec8218353fa9b3b2', hashlib.sha256(cut.encode()).hexdigest()
        weighted = production.split('"float raw=', 1)[1].split('energy=float3(0);"', 1)[0]
        cut_production = production.replace('"float raw=' + weighted + 'energy=float3(0);"', cut).replace('"return float4(energy*cover,0);}', '"return float4(energy,0);}')
        assert cut_production != production and cut_production.count('energy*cover') == 0
        (path / 'fixture.m').write_text(HARNESS.replace('SHADERS', shaders).replace('PRODUCTION', cut_production))
        cut_build = subprocess.run(['clang', '-I', str(ROOT / 'runtime'), '-O1', '-w', '-fobjc-arc', str(path / 'fixture.m'), '-framework', 'Foundation', '-framework', 'Metal', '-o', str(path / 'cut')], capture_output=True, text=True)
        assert cut_build.returncode == 0, cut_build.stderr[-4000:]
        cut_run = subprocess.run([str(path / 'cut'), str(path)], capture_output=True, text=True, timeout=90)
        assert cut_run.returncode == 1 and 'faint>=' in cut_run.stderr, (cut_run.stdout, cut_run.stderr)
        print('BROKEN binary receiver cut (rejected):', [l for l in cut_run.stdout.splitlines() if 'faint' in l][-1])
        proof.write_text(run.stdout + run.stderr + '\nBROKEN\n' + control.stdout + control.stderr)
        return 0


if __name__ == '__main__':
    sys.exit(main())
