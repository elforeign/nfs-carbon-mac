"""











































"""
from pathlib import Path
import array
import ast
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = ROOT / 'recomp/private_runtime'


def shader(source, name):
    text = source.split('static const char *' + name + ' =', 1)[1].split(';\n', 1)[0]
    return ''.join(ast.literal_eval(m[0]) for m in re.finditer(r'"(?:[^"\\]|\\.)*"', text))


def simshot_fixture(tmp):
    source = (PRIVATE / 'game_diagnostics.h').read_text()
    body = source.split('int diag_simshot_due(char *path, size_t n) {', 1)[1].split('\n}', 1)[0]
    fixture = r'''
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <math.h>
#include <string.h>
static uint8_t guest[0xc00000];
#define M32(a) (*(uint32_t *)(guest+(a)))
#define MF32(a) (*(float *)(guest+(a)))
#define diag_event(...) ((void)0)
static int diag_on;
static FILE *events_f;
static const char *diag_dir="fixture";
int diag_simshot_due(char *path,size_t n){BODY
}
int main(void){char path[80];setenv("BOOT_DIAG_SIMSHOTS","20,30",1);
 if(diag_simshot_due(path,sizeof path))return 1;diag_on=1;
 M32(0xA99BBC)=5;MF32(0xB4CFD8)=25;if(diag_simshot_due(path,sizeof path))return 1;
 M32(0xA99BBC)=6;MF32(0xB4CFD8)=19.99;if(diag_simshot_due(path,sizeof path))return 1;
 MF32(0xB4CFD8)=20;if(!diag_simshot_due(path,sizeof path)||strcmp(path,"fixture/simshot_020.00.png"))return 1;
 if(diag_simshot_due(path,sizeof path))return 1;MF32(0xB4CFD8)=NAN;if(diag_simshot_due(path,sizeof path))return 1;
 MF32(0xB4CFD8)=30;if(!diag_simshot_due(path,sizeof path)||strcmp(path,"fixture/simshot_030.00.png"))return 1;
 if(diag_simshot_due(path,sizeof path))return 1;return 0;
}
'''
    for label, implementation, expected in [('simshot', body, 0), ('simshot-stub', 'return 0;', 1)]:
        path = tmp / (label + '.c')
        path.write_text(fixture.replace('BODY', implementation))
        build = subprocess.run(['clang', '-I', str(PRIVATE), '-O1', str(path), '-o', str(tmp / label)], capture_output=True, text=True)
        assert build.returncode == 0, build.stderr[-1000:]
        assert subprocess.run([str(tmp / label)]).returncode == expected


def receiver_fixture(tmp, production):
    """Exercise the real draw wrapper: material/depth ownership and Off gating."""
    helper = 'static int carbon_ao_protected' + production.split('static int carbon_ao_protected', 1)[1].split('\n}', 1)[0] + '\n}'
    wrapper = (PRIVATE / 'game_compat_render_draw.h').read_text().split('\nstatic id<MTLTexture>', 1)[0]
    receiver = 'static id<MTLTexture>' + (PRIVATE / 'game_compat_render_draw.h').read_text().split('\nstatic id<MTLTexture>', 1)[1]
    original = "{\n    draw_impl(type,prims,indexed,base_vertex,min_index,num_vertices,start,up_vertices,up_stride,up_indices,up_index_fmt);\n}\n"
    # Pin the original forwarding seam alone, independently of current production.
    assert hashlib.sha256(original.encode()).hexdigest() == 'be026462b0e3a2a8f5fbed528a8d148eb6dc10e6e6eb959f543ab3a32d3be08a'
    fixture = r"""
#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
@interface FixtureSurface : NSObject
@end
@implementation FixtureSurface
-(NSUInteger)width{return 256;}-(NSUInteger)height{return 128;}-(NSUInteger)sampleCount{return 1;}
@end
static int carbon_ao_on,carbon_lamplight_on,flow=6,q_active,native,records,lists,lookups;
static uint64_t frame_serial=1,ssao_serial,ssao_cleared;
static struct{uint32_t rt[1],ds,rs[256];}dev={{1},2,{0}};
typedef struct{id<MTLTexture>tex;}RenderTex;
static RenderTex world,depth,ssao_mask;
static id<MTLTexture>ssao_depth,ssao_coverage_z,ssao_half_depth;
static id ssao_rec;static int ssao_eb;static uint32_t ssao_replay_dst=1,last_dst;
char diag_fx_pass[192]="IDI_WORLD_FX/world/p0";
#define M32(a) ((a)==0xA99BBCu?flow:(a)==0xAB04F4u?1u:2u)
#define CHECK(x) do{if(!(x)){fprintf(stderr,"receiver FAIL %s\n",#x);return 1;}}while(0)
static RenderTex*carbon_hdr_rt(uint32_t h){++lookups;return h==1?&world:h==2?&depth:NULL;}
static RenderTex*surface_rt(uint32_t h){return h==1?&world:h==2?&depth:NULL;}
static id<MTLTexture>surface_target(uint32_t h,NSUInteger*l,NSUInteger*s){(void)l;(void)s;RenderTex*r=surface_rt(h);return r?r->tex:nil;}
static int ssao_prepare(id<MTLTexture>z){return z!=nil;}
static id rt_render_list_new(void){++lists;return [NSObject new];}
#define ARGS uint32_t type,uint32_t prims,int indexed,int32_t base_vertex,uint32_t min_index,uint32_t num_vertices,uint32_t start,uint32_t up_vertices,uint32_t up_stride,uint32_t up_indices,uint32_t up_index_fmt
static void draw_impl(ARGS){++native;}
static void ssao_record(ARGS){++records;last_dst=ssao_replay_dst;}
static int prepares,replays;static id enc;
static int ssao_depth_prepare(id<MTLTexture>z){++prepares;return 1;}
static void ssao_open(id<MTLTexture>z,int cuts){}
static void rt_render_list_replay(id list,id encoder){++replays;}
static void end_pass(void){}
HELPER
RECEIVER
static void render_draw(ARGS) WRAPPER
static void draw(void){render_draw(4,1,0,0,0,0,0,0,0,0,0);}
int main(void){@autoreleasepool{
 world.tex=(id<MTLTexture>)[FixtureSurface new];depth.tex=(id<MTLTexture>)[FixtureSurface new];ssao_mask.tex=world.tex;
 draw();CHECK(native==1&&!lookups&&!records&&!lists);
 carbon_ao_on=1;flow=5;draw();CHECK(native==2&&!lookups);flow=6;dev.rs[168]=7;
 draw();CHECK(!records&&lists==1&&ssao_depth==depth.tex);
 strcpy(diag_fx_pass,"IDI_CAR_FX/car/p0");draw();CHECK(records==1);
 strcpy(diag_fx_pass,"IDI_CARNORMALMAP_FX/car_normalmap/p0");draw();CHECK(records==2);
 strcpy(diag_fx_pass,"IDI_WORLD_FX/world/p0");dev.rs[27]=1;dev.rs[20]=6;draw();CHECK(records==2); /* alpha road decal: a receiver */
 /* Additive world decal: recorded with its own alpha as coverage, then the factor is restored. */
 dev.rs[20]=2;draw();CHECK(records==3&&last_dst==6&&ssao_replay_dst==1);dev.rs[20]=6;
 strcpy(diag_fx_pass,"IDI_WORLDPRELIT_FX/world/p0");draw();CHECK(records==3);
 strcpy(diag_fx_pass,"IDI_WORLDPRELIT_FX/world/p1");draw();CHECK(records==4&&last_dst==1);
 strcpy(diag_fx_pass,"IDI_FLARES_FX/flares/p0");draw();CHECK(records==5);
 dev.rs[27]=0;strcpy(diag_fx_pass,"IDI_CAR_SHADOW_MAP_FX/car_shadow_map/p0");draw();CHECK(records==5);
 strcpy(diag_fx_pass,"IDI_CAR_FX/car/p0");q_active=1;draw();CHECK(records==5);q_active=0;
 dev.rt[0]=3;draw();CHECK(records==5);dev.rt[0]=1;
 dev.rs[168]=0;draw();CHECK(records==5);dev.rs[168]=7;
 ++frame_serial;draw();CHECK(records==6&&lists==2&&ssao_serial==frame_serial);
 CHECK(carbon_ao_receiver(depth.tex)==world.tex);CHECK(carbon_ao_receiver(depth.tex)==world.tex);CHECK(prepares==1&&replays==1);
 ++frame_serial;CHECK(!carbon_ao_receiver(depth.tex));ssao_serial=frame_serial;
 CHECK(carbon_ao_receiver(depth.tex)==world.tex);CHECK(prepares==2&&replays==2);
 carbon_ao_on=0;carbon_lamplight_on=1;draw();CHECK(records==7);
 carbon_lamplight_on=0;int before=lookups;draw();CHECK(records==7&&lookups==before);
 /* Particles are quads whose texels fade to zero alpha: smoke (INVSRCALPHA) is part of
  * what it covers; additive flares cover by their own alpha, never their whole quad. */
 carbon_lamplight_on=1;dev.rs[27]=1;dev.rs[20]=6;strcpy(diag_fx_pass,"IDI_PARTICLES_FX/fuzzz/p0");draw();
 dev.rs[20]=2;strcpy(diag_fx_pass,"IDI_PARTICLES_FX/streak_flares/p0");draw(); /* opaque-alpha glow */
 int quads_recorded=records-7;printf("particles whole_quads_recorded=%d\n",quads_recorded);CHECK(quads_recorded==0);
 strcpy(diag_fx_pass,"IDI_PARTICLES_FX/flares/p0");draw();CHECK(records==8&&last_dst==6&&ssao_replay_dst==1);
 printf("receiver materials=5 exclusions=6 alpha_coverage=1 Off lookups=0 frame_resets=2\n");return 0;
}}
"""
    original_receiver = 'static id<MTLTexture> carbon_ao_receiver(id<MTLTexture> depth) {\n    if(ssao_serial!=frame_serial || ssao_depth!=depth || !ssao_depth_prepare(depth))return nil;\n    ssao_open(ssao_half_depth,0);\n    rt_render_list_replay(ssao_rec,enc);end_pass();memset(&ssao_eb,0,sizeof ssao_eb);\n    return ssao_mask.tex;\n}\n'
    assert hashlib.sha256(original_receiver.encode()).hexdigest() == 'deec7050e66c2abb2350ad797580425dc9bc2dd2b492d67ce09402907be44846'
    # The classifier that erased every particle quad (shipped with the lamp pools On).
    quad_helper = '''static int carbon_ao_protected(const char *effect, unsigned blend) {
    if(blend==2 && !strcmp(effect,"IDI_WORLD_FX/world/p0"))return 2;
    if(blend==6 && !strcmp(effect,"IDI_WORLD_FX/world/p0"))return 0;
    return (blend && strcmp(effect,"IDI_WORLDPRELIT_FX/world/p0")) || !strncmp(effect,"IDI_CAR_FX/",11) ||
        !strncmp(effect,"IDI_CARNORMALMAP_FX/",20);
}'''
    assert hashlib.sha256(quad_helper.encode()).hexdigest() == '2c0ef0441720dc6c4b587599a9f1c28df5e352135258fd2603f5ec8a1f315d12', hashlib.sha256(quad_helper.encode()).hexdigest()
    for label, body, implementation, expected, classifier in [('receiver', wrapper, receiver, 0, helper), ('receiver-original', original, receiver, 1, helper), ('receiver-uncached', wrapper, original_receiver, 1, helper), ('receiver-particle-quads', wrapper, receiver, 1, quad_helper)]:
        path = tmp / (label + '.m')
        path.write_text(fixture.replace('HELPER', classifier).replace('RECEIVER', implementation).replace('WRAPPER', body))
        build = subprocess.run(['clang', '-I', str(PRIVATE), '-O1', '-w', '-fobjc-arc', str(path), '-framework', 'Foundation', '-o', str(tmp / label)], capture_output=True, text=True)
        assert build.returncode == 0, build.stderr[-2000:]
        run = subprocess.run([str(tmp / label)], capture_output=True, text=True)
        print(label, 'exit=' + str(run.returncode), run.stdout.strip(), run.stderr.strip())
        assert run.returncode == expected
        if label == 'receiver-particle-quads':
            assert 'whole_quads_recorded=2' in run.stdout and 'FAIL quads_recorded==0' in run.stderr, (run.stdout, run.stderr)


PRE = r'''
#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static id<MTLTexture> fixture_receivers;
static id<MTLDevice> mtl;
static id<MTLCommandQueue> queue;
static id<MTLCommandBuffer> cmd;
static uint8_t guest[0xc00000];
#define M32(a) (*(uint32_t *)(guest+(a)))
#define MF32(a) (*(float *)(guest+(a)))
typedef struct {id<MTLTexture> tex,ms;int stale;} RenderTex;
static RenderTex world,depth;
static struct {uint32_t autodepth;} dev={2};
static int diag_on,gpt_on,lookups,resolves,encodes,failures;
#define diag_event(...) ((void)0)
#define gpt_render(...) ((void)0)
#define gpt_name(...) ((void)0)
#define CHECK(x) do{if(!(x)){printf("FAIL %s\n",#x);++failures;}}while(0)
static void end_pass(void){}
static void ensure_cmd(void){}
static void msaa_resolve(RenderTex *r){(void)r;++resolves;}
static RenderTex *carbon_hdr_rt(uint32_t handle){++lookups;return handle==1?&world:handle==2?&depth:NULL;}
static id<MTLRenderPipelineState> pipeline_build(MTLRenderPipelineDescriptor *d,const char *label,NSError **out){
 NSError *error=nil;id<MTLRenderPipelineState> p=[mtl newRenderPipelineStateWithDescriptor:d error:&error];
 if(!p)fprintf(stderr,"pipeline %s: %s\n",label,error.localizedDescription.UTF8String);if(out)*out=error;++encodes;return p;
}
static unsigned contact_source_compiles;
static id<MTLLibrary> pipeline_library_source(NSString *s,const char *label,NSError **error){++contact_source_compiles;return [mtl newLibraryWithSource:s options:nil error:error];}
SHADERS
static const char *render_contact_source(int reference){return reference?ssao_legacy_src:ssao_src;}
static float fixture_car[3]={0,6,-2}; /* view (0,2,6) through the fixture view below */static int fixture_has_car=1,far_car,world_wall;
int private_carbon_player_position(float *p){memcpy(p,fixture_car,sizeof fixture_car);return fixture_has_car;}
PRODUCTION
static id<MTLTexture> carbon_ao_receiver(id<MTLTexture> depth){(void)depth;return fixture_receivers;}
static id<MTLTexture> texture(MTLPixelFormat format,unsigned samples){
 MTLTextureDescriptor *d=[MTLTextureDescriptor texture2DDescriptorWithPixelFormat:format width:256 height:128 mipmapped:NO];
 d.storageMode=MTLStorageModeShared;d.usage=MTLTextureUsageRenderTarget|MTLTextureUsageShaderRead;
 if(samples>1){d.textureType=MTLTextureType2DMultisample;d.sampleCount=samples;d.storageMode=MTLStorageModePrivate;}
 return [mtl newTextureWithDescriptor:d];
}
static void clear_world(void){
 MTLRenderPassDescriptor *rp=[MTLRenderPassDescriptor renderPassDescriptor];rp.colorAttachments[0].texture=world.ms?:world.tex;
 rp.colorAttachments[0].loadAction=MTLLoadActionClear;rp.colorAttachments[0].storeAction=MTLStoreActionStore;rp.colorAttachments[0].clearColor=MTLClearColorMake(0.6,0.6,0.6,0.37);
 [[cmd renderCommandEncoderWithDescriptor:rp] endEncoding];
}
static void resolve_world(void){
 if(!world.ms)return;
 MTLRenderPassDescriptor *rp=[MTLRenderPassDescriptor renderPassDescriptor];rp.colorAttachments[0].texture=world.ms;rp.colorAttachments[0].resolveTexture=world.tex;
 rp.colorAttachments[0].loadAction=MTLLoadActionLoad;rp.colorAttachments[0].storeAction=MTLStoreActionMultisampleResolve;
 [[cmd renderCommandEncoderWithDescriptor:rp] endEncoding];
}
static float pixels[256*128*4];
static void inspect(unsigned samples){
 resolve_world();[cmd commit];[cmd waitUntilCompleted];CHECK(cmd.status==MTLCommandBufferStatusCompleted);
 [world.tex getBytes:pixels bytesPerRow:256*4*sizeof(float) fromRegion:MTLRegionMake2D(0,0,256,128) mipmapLevel:0];
 if(getenv("AO_TEST_DUMP")){FILE *dump=fopen(getenv("AO_TEST_DUMP"),"ab");CHECK(dump&&fwrite(pixels,sizeof pixels,1,dump)==1);if(dump)fclose(dump);}
 double contact=0,open=0,body=0,lamp=0,window=0,decal=0;unsigned cn=0,on=0,bn=0,ln=0,wn=0,dn=0,alpha=0;
 for(unsigned y=0;y<128;y++)for(unsigned x=0;x<256;x++){
  float *p=pixels+4*(y*256+x);if(fabsf(p[3]-0.37f)>1e-6)++alpha;
  #ifdef ZERO_STRENGTH
  CHECK(p[0]==0.6f && p[1]==0.6f && p[2]==0.6f);
  #endif
  if(x>=25 && x<45 && y==80){body+=p[0]/0.6f;++bn;}
  if(x>=46 && x<63 && y==80){lamp+=p[0]/0.6f;++ln;}
  if(x>=202 && x<229 && y==90){window+=p[0]/0.6f;++wn;}
  /* Road just in front of the car's lower face (x 156..236, rows 78..89, depth 5). */
  if(x>=181 && x<197 && y==90){contact+=p[0]/0.6f;++cn;}
  if(x>=160 && x<181 && y==90){decal+=p[0]/0.6f;++dn;}
  if(x>20 && x<70 && y>110 && y<120){open+=p[0]/0.6f;++on;}
 }
 contact/=cn;open/=on;body/=bn;lamp/=ln;window/=wn;decal/=dn;
 if(world_wall){ /* the same crease with a world wall, not the car: only the car may shade */
  printf("samples=%u world=%.8f\n",samples,contact);CHECK(contact>=0.99);cmd=[queue commandBuffer];return;
 }
 if(far_car){ /* the same receivers 40 m from the car: a contact shadow must not reach them */
  printf("samples=%u facade=%.8f\n",samples,contact);CHECK(contact>=0.99);cmd=[queue commandBuffer];return;
 }
 printf("protected body=%.8f lamp=%.8f window=%.8f\n",body,lamp,window);
 CHECK(body>=0.90);CHECK(lamp>=0.95);
 #ifndef ZERO_STRENGTH
 CHECK(window>=0.99);
 #endif
 printf("samples=%u contact=%.8f decal=%.8f open=%.8f alpha_errors=%u\n",samples,contact,decal,open,alpha);
 CHECK(alpha==0);CHECK(open>0.98 && open<1.02);
 #ifdef ZERO_STRENGTH
 CHECK(fabs(contact-1)<1e-6);CHECK(fabs(open-1)<1e-6);CHECK(contact>=0.8);
 #else
 CHECK(contact<0.9);CHECK(decal<0.9);
 #endif
 cmd=[queue commandBuffer];
}
int main(void){@autoreleasepool{
 unsetenv("NFS_CARBON_AO");carbon_ao_init();CHECK(!carbon_ao_on);carbon_ao_apply();CHECK(!lookups && !resolves && !encodes);
 setenv("NFS_CARBON_AO","off",1);carbon_ao_init();CHECK(!carbon_ao_on);carbon_ao_apply();CHECK(!lookups && !resolves && !encodes);
 setenv("NFS_CARBON_AO","on",1);carbon_ao_init();CHECK(carbon_ao_on);carbon_ao_apply();CHECK(!lookups && !resolves && !encodes);
 CHECK(carbon_ao_protected("IDI_CAR_FX/car/p0",0));
 CHECK(carbon_ao_protected("IDI_CARNORMALMAP_FX/car_normalmap/p0",0));
 CHECK(carbon_ao_protected("IDI_FLARES_FX/flares/p0",1));
 CHECK(carbon_ao_protected("IDI_PARTICLES_FX/flares/p0",2));
 CHECK(carbon_ao_protected("IDI_WORLD_FX/world/p0",6)==0);
 CHECK(!carbon_ao_protected("IDI_WORLD_FX/world/p0",0));
 CHECK(!carbon_ao_protected("IDI_CAR_SHADOW_MAP_FX/car_shadow_map/p0",0));
 mtl=MTLCreateSystemDefaultDevice();if(!mtl)return 3;queue=[mtl newCommandQueue];cmd=[queue commandBuffer];
 M32(0x00A99BBC)=6;M32(0x00AB04F4)=1;M32(0x00AB04F8)=2;M32(0x00B4AF90)=0x100000;
 MF32(0x100000)=MF32(0x100018)=MF32(0x10003C)=1;MF32(0x100024)=-1; /* view: world x->x, y->z, z (up)->-y (the floor plane y=2 faces -y) */
 MF32(0x100040)=4;MF32(0x100054)=-1; /* narrow in x: every measured region lies within 3 units of the car */MF32(0x100068)=100.0f/99.5f;MF32(0x100078)=-50.0f/99.5f;
 depth.tex=texture(MTLPixelFormatDepth32Float,1);
 fixture_receivers=texture(MTLPixelFormatR8Unorm,1);
 uint8_t receiver_bytes[256*128];memset(receiver_bytes,255,sizeof receiver_bytes);
 /* Lit car/late lamp outputs over a known occluded contact. They may occlude,
  * but must never receive the final world-colour attenuation. */
 for(unsigned y=79;y<85;y++)for(unsigned x=24;x<64;x++)receiver_bytes[y*256+x]=0;
 /* A shadow strip spans the contact, including fully transparent texels.
  * Replay uses ZERO/ZERO regardless of opacity: the material classifier must
  * leave these road pixels white. Restoring its original body proves failure. */
 if(carbon_ao_protected("IDI_WORLDPRELIT_FX/world/p0",1))
  for(unsigned y=78;y<94;y++)for(unsigned x=8;x<249;x++)receiver_bytes[y*256+x]=0;
 /* An additive world decal spans the same contact. Its texels are transparent
  * (event ring) except x 200..230, a lit window pane. Coverage by the decal's
  * own alpha (2) protects only the pane; erasing coverage (1) loses the contact;
  * no coverage (0) lets the lit pane be darkened. */
 int decal=carbon_ao_protected("IDI_WORLD_FX/world/p0",2);
 for(unsigned y=78;y<94;y++)for(unsigned x=8;x<249;x++)
  if(decal==1 || (decal==2 && x>=200 && x<231 && y>=90))receiver_bytes[y*256+x]=0;
 /* An alpha-blended road decal (INVSRCALPHA) over the contact, x 120..180: part of the surface. */
 if(carbon_ao_protected("IDI_WORLD_FX/world/p0",6))
  for(unsigned y=78;y<94;y++)for(unsigned x=120;x<181;x++)receiver_bytes[y*256+x]=0;
 uint8_t world_bytes[256*128];memcpy(world_bytes,receiver_bytes,sizeof world_bytes);
 /* The car's lower face stands on the floor: protected, so it occludes. */
 for(unsigned y=78;y<90;y++)for(unsigned x=156;x<237;x++)receiver_bytes[y*256+x]=0;
 [fixture_receivers replaceRegion:MTLRegionMake2D(0,0,256,128) mipmapLevel:0 withBytes:receiver_bytes bytesPerRow:256];
 NSString *src=[NSString stringWithFormat:@"%s\nstruct FD {float z [[depth(any)]];};fragment FD fixture_depth(VOut i [[stage_in]]) {float2 uv=i.uv;float d=8.0;if(uv.y>0.5)d=min(d,2.0/(2.0*uv.y-1.0));if(uv.x>0.40&&uv.x<0.60&&uv.y>0.40&&uv.y<0.70)d=min(d,3.0);if(uv.x>=156.0/256.0&&uv.x<237.0/256.0&&uv.y>=78.0/128.0&&uv.y<90.0/128.0)d=min(d,5.0);return {100.0/99.5-50.0/(99.5*d)};}",carbon_ao_vertex];
 NSError *error=nil;id<MTLLibrary> lib=[mtl newLibraryWithSource:src options:nil error:&error];if(!lib){fprintf(stderr,"fixture shader: %s\n",error.localizedDescription.UTF8String);return 1;}
 MTLRenderPipelineDescriptor *d=[MTLRenderPipelineDescriptor new];d.vertexFunction=[lib newFunctionWithName:@"vs_full"];d.fragmentFunction=[lib newFunctionWithName:@"fixture_depth"];d.depthAttachmentPixelFormat=MTLPixelFormatDepth32Float;
 id<MTLRenderPipelineState> p=[mtl newRenderPipelineStateWithDescriptor:d error:&error];CHECK(p!=nil);
 MTLDepthStencilDescriptor *ds=[MTLDepthStencilDescriptor new];ds.depthWriteEnabled=YES;ds.depthCompareFunction=MTLCompareFunctionAlways;
 MTLRenderPassDescriptor *rp=[MTLRenderPassDescriptor renderPassDescriptor];rp.depthAttachment.texture=depth.tex;rp.depthAttachment.loadAction=MTLLoadActionClear;rp.depthAttachment.storeAction=MTLStoreActionStore;rp.depthAttachment.clearDepth=1;
 id<MTLRenderCommandEncoder> e=[cmd renderCommandEncoderWithDescriptor:rp];[e setRenderPipelineState:p];[e setDepthStencilState:[mtl newDepthStencilStateWithDescriptor:ds]];[e drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:3];[e endEncoding];
 for(unsigned samples=1;samples<=4;samples+=3){
  world.tex=texture(MTLPixelFormatRGBA32Float,1);world.ms=samples>1?texture(MTLPixelFormatRGBA32Float,samples):nil;
  clear_world();carbon_ao_apply();inspect(samples);
  far_car=1;fixture_car[0]=40;clear_world();carbon_ao_apply();inspect(samples);far_car=0;fixture_car[0]=0;
  [fixture_receivers replaceRegion:MTLRegionMake2D(0,0,256,128) mipmapLevel:0 withBytes:world_bytes bytesPerRow:256];
  world_wall=1;clear_world();carbon_ao_apply();inspect(samples);world_wall=0;
  [fixture_receivers replaceRegion:MTLRegionMake2D(0,0,256,128) mipmapLevel:0 withBytes:receiver_bytes bytesPerRow:256];
 }
 int before=resolves;fixture_has_car=0;carbon_ao_apply();CHECK(resolves==before);fixture_has_car=1;
 printf("off target_lookups=0 resolves=0 encoders=0 failures=%d\n",failures);return failures?1:0;
}}
'''


def prewarm_fixture(tmp, post, production):
    """Use the loading entry and actual race encoder, with independent variants."""
    shaders = '\n'.join('static const char *' + name + '=' + json.dumps(shader(post, name)) + ';'
                        for name in ('ssao_src', 'ssao_legacy_src'))
    warm = 'void render_post_prewarm(void) {' + post.split('void render_post_prewarm(void) {', 1)[1].split('\n}', 1)[0] + '\n}'
    stubs = r'''
#define NFS_GAME 2
#define NFS_GAME_PRIVATE 2
static id x_post_library(unsigned n){return (id)mtl;}
static int x_pipeline_init(void){return 1;}
static id x_edr_pipeline(NSString *s,NSUInteger n,int lamp){return (id)mtl;}
static id lamp_pipeline(NSUInteger n,int view){return (id)mtl;}
void render_carbon_lamplight_prewarm(void){}
'''
    source = PRE.replace('SHADERS', shaders).replace('PRODUCTION', production + '\n' + stubs + warm)
    marker = ' M32(0x00A99BBC)=6;'
    load = r'''
 if(getenv("AO_TEST_OFF"))setenv("NFS_CARBON_AO","off",1);else setenv("NFS_CARBON_AO","on",1);carbon_ao_init();
 dispatch_queue_t prewarm_queue=dispatch_queue_create("contact-prewarm-test",DISPATCH_QUEUE_SERIAL);
 dispatch_semaphore_t ready=dispatch_semaphore_create(0);
 dispatch_async(prewarm_queue,^{@autoreleasepool{render_post_prewarm();dispatch_semaphore_signal(ready);}});
 dispatch_semaphore_wait(ready,DISPATCH_TIME_FOREVER);
 unsigned loaded=encodes;
 if(getenv("AO_TEST_OFF")){carbon_ao_apply();printf("contact prewarm off builds=%u sources=%u\n",loaded,contact_source_compiles);return loaded||contact_source_compiles?1:0;}
'''
    assert source.count(marker) == 1
    source = source.replace(marker, load + marker)
    a = source.index(' for(unsigned samples=1;samples<=4;samples+=3){')
    b = source.index('\n int before=resolves;', a)
    source = source[:a] + r'''
 unsigned variants=0;
 for(NSNumber *format in @[@(MTLPixelFormatBGRA8Unorm),@(MTLPixelFormatRGBA8Unorm),@(MTLPixelFormatRGBA16Float)])
  for(unsigned samples=1;samples<=8;samples*=2)if([mtl supportsTextureSampleCount:samples]){
   world.tex=texture(format.unsignedIntegerValue,1);world.ms=samples>1?texture(format.unsignedIntegerValue,samples):nil;
   clear_world();carbon_ao_apply();++variants;
  }
 [cmd commit];[cmd waitUntilCompleted];CHECK(cmd.status==MTLCommandBufferStatusCompleted);
 unsigned misses=encodes-loaded;
 printf("contact prewarm variants=%u load_builds=%u frame_builds=%u\n",variants,loaded,misses);
 CHECK(!misses);
''' + source[b:]
    path = tmp / 'contact-prewarm.m'
    path.write_text(source)
    exe = tmp / 'contact-prewarm'
    build = subprocess.run(['clang', '-I', str(PRIVATE), '-O1', '-w', '-fobjc-arc', str(path), '-framework', 'Foundation',
                            '-framework', 'Metal', '-o', str(exe)], capture_output=True, text=True)
    assert build.returncode == 0, build.stderr[-5000:]
    env = dict(os.environ, NFS_PSO_PREWARM='1')
    env.pop('AO_TEST_OFF', None)
    run = subprocess.run([str(exe)], env=env, capture_output=True, text=True, timeout=90)
    print(run.stdout, run.stderr[-1500:], end='', flush=True)
    if run.returncode == 3:
        return 3
    assert run.returncode == 0, 'contact pipelines missing from loading prewarm'
    off = subprocess.run([str(exe)], env=dict(env, AO_TEST_OFF='1'), capture_output=True, text=True, timeout=90)
    print(off.stdout, off.stderr[-1500:], end='', flush=True)
    assert off.returncode == 0, 'contact Off built pipelines'
    disabled = subprocess.run([str(exe)], env=dict(env, NFS_PSO_PREWARM='0'), capture_output=True, text=True, timeout=90)
    print(disabled.stdout, disabled.stderr[-1500:], end='', flush=True)
    assert disabled.returncode == 1 and re.search(r'load_builds=0 frame_builds=[1-9][0-9]*', disabled.stdout), 'prewarm-disabled control escaped'
    # Omit only the production hook; keep the demand path and variant set intact.
    hook = '    render_carbon_contact_prewarm();'
    assert source.count(hook) == 1
    path.write_text(source.replace(hook, '    /* omitted contact prewarm control */'))
    broken_build = subprocess.run(['clang', '-I', str(PRIVATE), '-O1', '-w', '-fobjc-arc', str(path), '-framework', 'Foundation',
                                   '-framework', 'Metal', '-o', str(exe)], capture_output=True, text=True)
    assert broken_build.returncode == 0, broken_build.stderr[-5000:]
    broken = subprocess.run([str(exe)], env=env, capture_output=True, text=True, timeout=90)
    print(broken.stdout, broken.stderr[-1500:], end='', flush=True)
    assert broken.returncode == 1 and re.search(r'load_builds=0 frame_builds=[1-9][0-9]*', broken.stdout), 'missing contact prewarm escaped'
    return 0


# The three early exits of the contact kernel and its composition, each as (current, before).
EARLY_EXITS = [
    ('// A tap counts within 3 m of the car and fades to zero at the reach: farther receivers get 0 without the walk.\n'
     '"if(ao_depth(z,uv,c.k)>=0.999999||distance(p,c.car.xyz)>=3.05+c.car.w)return float2(0,p.z);"',
     '"if(ao_depth(z,uv,c.k)>=0.999999||distance(p,c.car.xyz)>=4.5)return float2(0,p.z);"'),
    ('// The half-size mask is read first: most taps are not the car and need no depth.\n'
     '"if(mask.sample(pt,c.k.rect.xy+q*c.k.rect.zw).r>=0.5)continue;float qd=ao_depth(z,q,c.k);if(qd>=0.999999)continue;float3 o=ao_point(q,qd,c.k);"\n'
     '"if(distance(o,c.car.xyz)>=3.0)continue;float3 v=o-p;if(dot(c.up.xyz,v)<0.05)continue;"',
     '"float qd=ao_depth(z,q,c.k);if(qd>=0.999999)continue;float3 o=ao_point(q,qd,c.k);"\n'
     '"if(mask.sample(pt,c.k.rect.xy+q*c.k.rect.zw).r>=0.5||distance(o,c.car.xyz)>=3.0)continue;float3 v=o-p;if(dot(c.up.xyz,v)<0.05)continue;"'),
    ('\n// Beyond 4.5 m of the car the result is 1: leave before the mask and the four shade reads.\n'
     '"float cd=distance(ao_point(i.uv,raw,c.k),c.car.xyz);if(cd>=4.5)return float4(0,0,0,1);"', ''),
    ('"a=mix(a,1.0,smoothstep(3.0,4.5,cd));"',
     '"a=mix(a,1.0,smoothstep(3.0,4.5,distance(ao_point(i.uv,ao_depth(z,i.uv,c.k),c.k),c.car.xyz)));"'),
]


def early_exits(text):
    """1 when no tap reads the full-size depth before the mask, receivers out of every tap's
    reach skip the walk, and the composition leaves far pixels before its mask and shade reads."""
    kernel = text.split('fs_contact_kernel', 1)[1].split('fs_contact_multiply', 1)[0]
    taps = kernel.split('for(int s=0;s<6;++s){', 1)[1]
    multiply = text.split('fs_contact_multiply', 1)[1].split('typedef struct', 1)[0]
    leave = multiply.find('>=4.5)return float4(0,0,0,1);')
    return int(taps.index('mask.sample(') < taps.index('ao_depth(z,q') and '>=3.05+c.car.w)return float2(0,p.z);' in kernel
               and 0 <= leave < multiply.index('mask.sample(') and leave < multiply.index('ao.sample('))


def early_exit_fixture(tmp, shaders, production):
    """The early exits change no pixel. The pinned kernel before them fails the read-order check
    (early_exits 0 against 1) and renders the same six frames (1x and 4x: contact, far car, world wall)."""
    before = production
    for current, old in EARLY_EXITS:
        assert before.count(current) == 1, current
        before = before.replace(current, old)
    fragment = lambda text: 'static const char *carbon_ao_multiply =' + text.split('static const char *carbon_ao_multiply =', 1)[1].split('"return float4(0,0,0,a);}\\n";', 1)[0]
    assert hashlib.sha256(fragment(before).encode()).hexdigest() == 'cfa4e6b0b3dfca2158adf3fb8ee35878010f965a7b7fe3f44e3f64d370aa03b2'
    assert early_exits(production) == 1 and early_exits(before) == 0
    frames = []
    for label, text in (('early-exits', production), ('before-early-exits', before)):
        (tmp / 'fixture.m').write_text(PRE.replace('SHADERS', shaders).replace('PRODUCTION', text))
        build = subprocess.run(['clang', '-I', str(PRIVATE), '-O1', '-w', '-fobjc-arc', str(tmp / 'fixture.m'), '-framework', 'Foundation', '-framework', 'Metal', '-o', str(tmp / label)], capture_output=True, text=True)
        assert build.returncode == 0, build.stderr[-5000:]
        dump = tmp / (label + '.raw')
        run = subprocess.run([str(tmp / label)], env=dict(os.environ, AO_TEST_DUMP=str(dump)), capture_output=True, text=True, timeout=90)
        if run.returncode == 3:
            return 3
        assert run.returncode == 0, (label, run.stdout, run.stderr[-1500:])
        values = array.array('f')
        values.frombytes(dump.read_bytes())
        frames.append(values)
    assert len(frames[0]) == len(frames[1]) == 6 * 256 * 128 * 4, (len(frames[0]), len(frames[1]))
    shaded = sum(1 for k in range(0, len(frames[1]), 4) if frames[1][k] < 0.59)
    worst = max(abs(a - b) for a, b in zip(frames[0], frames[1]))
    print('early exits: read order 1 (before 0), %d shaded pixels, largest difference %.3g' % (shaded, worst))
    # A far pixel's factor was 1 or one float step below it; an 8-bit or half-float target stores the same value.
    assert shaded > 500 and worst <= 1e-6, (shaded, worst)
    return 0


def main():
    if not (ROOT / 'recomp/out/carbon-base/image.json').is_file():
        print('SKIP private AO: private image absent')
        return 3
    post = (ROOT / 'runtime/render_post.m').read_text()
    production = (PRIVATE / 'carbon_ao.h').read_text()
    feature = json.loads((PRIVATE / 'features/ao.json').read_text())
    assert feature['bindings']['carbon_ao.h']['sha256'] == hashlib.sha256(production.encode()).hexdigest()
    for name, digest in [('ssao_src', 'b1871b4fc455b8d9edb6c3ba7d0e7ddb4dec49cd360e610866c913ea87659d0f'),
                         ('ssao_legacy_src', '7248343ed53f84b41fb36192097b6d024eb2a8b13549272dd402b1f600fc9c09')]:
        assert hashlib.sha256(shader(post, name).encode()).hexdigest() == digest, name
    # Pin the shared MW bytes; only this private caller extends the sample cap.
    assert 'render_contact_source(0)' in production
    # The private caller has its own kernel; the shared source is compiled as is.
    assert 'stringByReplacingOccurrencesOfString' not in production
    assert 'kernel=carbon_ao_pipeline(carbon_ao_pso.library,@"fs_contact_kernel"' in production
    assert 'setFragmentTexture:pass==4||pass==1?receivers:mask atIndex:3' in production
    # The shared replay takes the factor only in the private build; the wrapper sets and restores it.
    render = (ROOT / 'runtime/render.m').read_text()
    assert render.count('#if NFS_GAME == NFS_GAME_PRIVATE\n        rs[20]=ssao_replay_dst;\n') == 1  # glow coverage follows: private_ao_glow_test
    assert 'ssao_replay_dst=kind==2?6:1;' in (PRIVATE / 'game_compat_render_draw.h').read_text()
    # Emit C literals with JSON escaping, preserving the shader bytes exactly.
    shaders = '\n'.join('static const char *' + name + '=' + json.dumps(shader(post, name)) + ';' for name in ('ssao_src', 'ssao_legacy_src'))
    with tempfile.TemporaryDirectory(prefix='private-ao-') as directory:
        tmp = Path(directory)
        simshot_fixture(tmp)
        receiver_fixture(tmp, production)
        results = []
        helper = 'static int carbon_ao_protected' + production.split('static int carbon_ao_protected', 1)[1].split('\n}', 1)[0] + '\n}'
        original_helper = '''static int carbon_ao_protected(const char *effect, unsigned blended) {
    return blended || !strncmp(effect,"IDI_CAR_FX/",11) ||
        !strncmp(effect,"IDI_CARNORMALMAP_FX/",20);
}'''
        assert hashlib.sha256(original_helper.encode()).hexdigest() == '4b37c9600a11d6f7494bec85809869dc0d5f58045111cfd917a12726d7074bef'
        # The previous classifier: strips are receivers, additive world decals still protected.
        strips_helper = '''static int carbon_ao_protected(const char *effect, unsigned blended) {
    return (blended && strcmp(effect,"IDI_WORLDPRELIT_FX/world/p0")) || !strncmp(effect,"IDI_CAR_FX/",11) ||
        !strncmp(effect,"IDI_CARNORMALMAP_FX/",20);
}'''
        assert hashlib.sha256(strips_helper.encode()).hexdigest() == '9d84c3570ee9ec76926b8e4a4b1a89237b4488dd081077f2a12a292ce5a5b2da'
        # The classifier that ignored emissive texels: every additive world decal a receiver.
        ignored_helper = '''static int carbon_ao_protected(const char *effect, unsigned blend) {
    return (blend && strcmp(effect,"IDI_WORLDPRELIT_FX/world/p0") &&
            !(blend==2 && !strcmp(effect,"IDI_WORLD_FX/world/p0"))) ||
        !strncmp(effect,"IDI_CAR_FX/",11) || !strncmp(effect,"IDI_CARNORMALMAP_FX/",20);
}'''
        assert hashlib.sha256(ignored_helper.encode()).hexdigest() == '1010f6d2beee4d0c702a1065ac1a3cc7b2edc222934c69ac464f2e783b5c7839'
        # The composition without the distance-from-car term: shading reaches any receiver.
        falloff = '"a=mix(a,1.0,smoothstep(3.0,4.5,cd));"\n'
        leave = 'if(cd>=4.5)return float4(0,0,0,1);'
        assert production.count(falloff) == 1 and production.count(leave) == 1
        # The kernel skips receivers beyond the same distance; the control removes both.
        skip = '||distance(p,c.car.xyz)>=3.05+c.car.w'
        assert production.count(skip) == 1
        # Only the car occludes: a protected texel within 3 m of the car. The controls drop each term.
        car_only = 'if(mask.sample(pt,c.k.rect.xy+q*c.k.rect.zw).r>=0.5)continue;'
        near_car = 'if(distance(o,c.car.xyz)>=3.0)continue;'
        assert production.count(car_only) == 1 and production.count(near_car) == 1
        # The classifier before alpha road decals became receivers.
        particles = ('    if((blend==2 || blend==6) && !strncmp(effect,"IDI_PARTICLES_FX/",17))\n'
                     '        return blend==2 && strcmp(effect,"IDI_PARTICLES_FX/streak_flares/p0") ? 2 : 0;\n')
        assert helper.count(particles) == 1
        decal_helper = helper.replace(particles, '').replace('    if(blend==6 && !strcmp(effect,"IDI_WORLD_FX/world/p0"))return 0;\n', '')
        assert hashlib.sha256(decal_helper.encode()).hexdigest() == '6b5392340a1d1f23514e958a9b38b640813ea33658f27b6af965dbbceee8ecbb', hashlib.sha256(decal_helper.encode()).hexdigest()
        for label, text, flags in [
            ('normal', production, []),
            ('unconfined', production.replace(falloff, '').replace(leave, '').replace(skip, '').replace(near_car, ''), []),
            ('world-occluders', production.replace(car_only, ''), []),
            ('decal-protected', production.replace(helper, decal_helper), []),
            ('emissive-ignored', production.replace(helper, ignored_helper), []),
            ('shadow-protected', production.replace(helper, original_helper), []),
            ('additive-protected', production.replace(helper, strips_helper), []),
            ('zero', production.replace('1.0f/h,CARBON_AO_STRENGTH,0}', '1.0f/h,0,0}'), ['-DZERO_STRENGTH']),
            ('original-composition', production.replace('pass==4||pass==1?receivers:mask', 'pass==1?receivers:mask'), [])]:
            source = PRE.replace('SHADERS', shaders).replace('PRODUCTION', text)
            (tmp / 'fixture.m').write_text(source)
            build = subprocess.run(['clang', '-I', str(PRIVATE), '-O1', '-w', '-fobjc-arc', *flags, str(tmp / 'fixture.m'), '-framework', 'Foundation', '-framework', 'Metal', '-o', str(tmp / label)], capture_output=True, text=True)
            assert build.returncode == 0, build.stderr[-5000:]
            run = subprocess.run([str(tmp / label)], capture_output=True, text=True, timeout=90)
            print(label, run.stdout, run.stderr[-1500:], end='')
            results.append(label + '\n' + run.stdout + run.stderr)
            if run.returncode == 3:
                return 3
            assert run.returncode == (1 if label in ('original-composition', 'shadow-protected', 'additive-protected', 'emissive-ignored', 'unconfined', 'world-occluders', 'decal-protected') else 0), (label, run.returncode)
            if label == 'unconfined':
                assert run.stdout.count('FAIL contact>=0.99') == 2 and 'FAIL window' not in run.stdout, run.stdout
            if label == 'emissive-ignored':
                assert run.stdout.count('FAIL window>=0.99') == 2 and 'FAIL contact<0.9' not in run.stdout, run.stdout
            if label == 'world-occluders':
                assert run.stdout.count('FAIL contact>=0.99') == 2 and 'FAIL contact<0.9' not in run.stdout, run.stdout
            if label == 'decal-protected':
                assert run.stdout.count('FAIL decal<0.9') == 2 and 'FAIL contact<0.9' not in run.stdout, run.stdout
            if label in ('shadow-protected', 'additive-protected'):
                assert run.stdout.count('contact=1.00000000') == 2, run.stdout
        if early_exit_fixture(tmp, shaders, production) == 3:
            return 3
        log = ROOT / '.metal-cache/proof-tests/carbon-ao-kernel-proof.txt'
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(''.join(results))
    print('PRIVATE AO PASS shadow receivers, additive decals protect lit texels only, protected car/lamp, original classifiers/composition rejected, shared kernel, Off, zero, 1x/4x RGB/alpha')
    return 0


if __name__ == '__main__':
    sys.exit(main())
