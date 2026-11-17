"""Carbon native float storage: explicit opt-in, classified owners and transport.

GPU fixture uses production promotion, MSAA resolve and quad copy code at full
size plus all three pyramid levels, 1x/4x: 263,430 inspected pixels. Over-white
(4,2,1.5): good clipped channels=0, nonfinite=0, exit 0; deliberate UNORM first
destination: 198,918 clipped channels, nonfinite=0, exit 1 (trusted GPU run).
MSAA quarter-ULP boundary: removing the conservative resolve loses 9 channels
(exit 1); the production rule loses 0. No measurement threshold is relaxed.
Also executes private init/phase wrappers: unset/off/HDR-only do not promote;
On promotes 12 owners once; reset reallocations promote again; unclassified
small textures stay UNORM. Renderer-owned backbuffer/depth guards: good 0
failures, removed-guard control 2 failures / exit 1. This fixture requires
private generated outputs.
"""
from pathlib import Path
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent
PRIVATE = ROOT / 'recomp/private_runtime'
sys.path.insert(0, str(ROOT / 'runtime'))
import float_scene_copy_test as shared
sys.path.insert(0, str(PRIVATE))

# Independent native route inventory (three texture families, three levels).
TARGETS = [0xAB08F8, 0xAB0690, 0xAB0694] + [b + 4*i for b in (0xB42F48, 0xB42F54, 0xB42F60) for i in range(3)]
HOOKS = {0x71AAE0: 'allocate', 0x712D40: 'allocate', 0x73C340: 'allocate',
         0x72EBA0: 'world', 0x729770: 'dispatch', 0x713020: 'texture'}

NATIVE_FRAGMENTS = {'0071AAE0': '43bd25a471735cf0245941a228849e49856b2a150697581b90fe205229c9e35a', '00712D40': 'd8c6da5ec945f60cdaaf341e422fc76a55c9244c3bcda818028c99114bc9ffe3', '0073C340': 'bb5afed952a8502565f39b3bc3a0940dcd58602c8186837655a8833497ebcf48', '0072EBA0': 'd550100e592e7eca1eb0e989fb84731709ad9b5f22833785011305ad94b98abb', '00729770': '4b52c63742dbb341bdd1fb1c9cef4ce39a76cee1bb0e366dc44b39784c4f8491', '00713020': '2abdcd4156f901fd9a9c8181d88767ef2c9c6c73f421dc5fe04615098864e70b'}

EXTRA = r'''
#include <math.h>
#define HDRCLIP_IMPLEMENTATION
#undef hdrclip_scan
#include "hdrclip.h"
#define hdrclip_scan(...) ((void)0)
static uint64_t hc_frame;
static int hc_finished;
static id<MTLBuffer> hc_buffer,hc_pairs;
enum {HC_COUNTERS=HC_STAGES*2+256};
void render_float_scene_begin(void);
void hdrclip_finish(void){}
INIT
RESOLVE
static void carbon_hdr_dispatch_begin(void){}
static void carbon_hdr_copy_observe(void){carbon_hdr_copy_pending=0;}
SELECT
'''
MAIN = r'''
static void init_blit(void){
 NSError *error=nil;blit_lib=[mtl newLibraryWithSource:[NSString stringWithUTF8String:blit_src] options:nil error:&error];
 MTLRenderPipelineDescriptor *p=[MTLRenderPipelineDescriptor new];p.vertexFunction=[blit_lib newFunctionWithName:@"blit_vs"];p.fragmentFunction=[blit_lib newFunctionWithName:@"blit_fs"];p.colorAttachments[0].pixelFormat=MTLPixelFormatBGRA8Unorm;
 blit_pso=[mtl newRenderPipelineStateWithDescriptor:p error:&error];CHECK(blit_pso,"blit pipeline");
 MTLSamplerDescriptor *s=[MTLSamplerDescriptor new];s.minFilter=s.magFilter=MTLSamplerMinMagFilterNearest;blit_point=[mtl newSamplerStateWithDescriptor:s];
 s.minFilter=s.magFilter=MTLSamplerMinMagFilterLinear;blit_linear=[mtl newSamplerStateWithDescriptor:s];
}
static unsigned calls;
static void original(Cpu *c){++calls;c->eax=123;c->esp+=4;}
static void clear_texture(id<MTLTexture> t){
 MTLRenderPassDescriptor *p=[MTLRenderPassDescriptor renderPassDescriptor];p.colorAttachments[0].texture=t;
 p.colorAttachments[0].loadAction=MTLLoadActionClear;p.colorAttachments[0].storeAction=MTLStoreActionStore;
 p.colorAttachments[0].clearColor=MTLClearColorMake(4,2,1.5,1);
 [[cmd renderCommandEncoderWithDescriptor:p] endEncoding];
}
/* Two representable MSAA values average above white but below half an ULP. */
static void boundary_texture(id<MTLTexture> t){
 NSError *error=nil;
 NSString *src=@"#include <metal_stdlib>\nusing namespace metal;\nvertex float4 vs(uint v [[vertex_id]]){float2 p=float2((v<<1)&2,v&2);return float4(p*2-1,0,1);}\nfragment float4 fs(float4 p [[position]],uint sid [[sample_id]]){if(p.x<1 && p.y<1)return float4(float3(sid<2?0.99951171875f:1.0009765625f),1);return float4(4,2,1.5,1);}";
 id<MTLLibrary> l=[mtl newLibraryWithSource:src options:nil error:&error];
 MTLRenderPipelineDescriptor *d=[MTLRenderPipelineDescriptor new];d.vertexFunction=[l newFunctionWithName:@"vs"];d.fragmentFunction=[l newFunctionWithName:@"fs"];d.colorAttachments[0].pixelFormat=t.pixelFormat;d.rasterSampleCount=t.sampleCount;
 id<MTLRenderPipelineState> p=[mtl newRenderPipelineStateWithDescriptor:d error:&error];CHECK(p,"boundary pipeline");
 MTLRenderPassDescriptor *rp=[MTLRenderPassDescriptor renderPassDescriptor];rp.colorAttachments[0].texture=t;rp.colorAttachments[0].loadAction=MTLLoadActionDontCare;rp.colorAttachments[0].storeAction=MTLStoreActionStore;
 id<MTLRenderCommandEncoder> e=[cmd renderCommandEncoderWithDescriptor:rp];[e setRenderPipelineState:p];[e drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:3];[e endEncoding];
}
static unsigned long long lost,nonfinite,pixels;
static void inspect(id<MTLTexture> t){
 NSUInteger row=(t.width*8+255)&~255ul;
 id<MTLBuffer> b=[mtl newBufferWithLength:row*t.height options:MTLResourceStorageModeShared];
 id<MTLTexture> view=texture(t.width,t.height,MTLPixelFormatRGBA16Float,1);
 blit_quad(t,MTLRegionMake2D(0,0,t.width,t.height),view,0,0,MTLRegionMake2D(0,0,t.width,t.height),0);
 id<MTLBlitCommandEncoder> e=[cmd blitCommandEncoder];
 [e copyFromTexture:view sourceSlice:0 sourceLevel:0 sourceOrigin:MTLOriginMake(0,0,0) sourceSize:MTLSizeMake(t.width,t.height,1) toBuffer:b destinationOffset:0 destinationBytesPerRow:row destinationBytesPerImage:row*t.height];[e endEncoding];
 [cmd commit];[cmd waitUntilCompleted];CHECK(cmd.status==MTLCommandBufferStatusCompleted,"GPU completion");
 for(NSUInteger y=0;y<t.height;y++)for(NSUInteger x=0;x<t.width;x++){
  const _Float16 *v=(const _Float16 *)((const char *)b.contents+y*row+x*8);
  int nf=0;for(unsigned k=0;k<4;k++)nf|=!isfinite((float)v[k]);nonfinite+=nf;
  for(unsigned k=0;k<3;k++)lost+=(float)v[k]<=1; ++pixels;
 }
 cmd=[queue commandBuffer];
}
static void setup_targets(unsigned samples){
 memset(objects,0,sizeof objects);memset(copies,0,sizeof copies);
 dev.pp[0]=257;dev.pp[1]=129;
 for(unsigned i=0;i<12;i++){
  uint32_t h=4+2*i; M32(carbon_hdr_address(i))=h;
  unsigned level=i<3?0:(i-3)%3+1,w=257>>level,ht=129>>level;
  objects[h]=(Obj){.kind=i?K_TEXTURE:K_SURFACE,.fmt=21,.w=w,.h=ht,.usage=1,.gpu=&copies[h]};
  objects[h+1]=(Obj){.kind=K_SURFACE,.parent=h,.fmt=21,.w=w,.h=ht};
  copies[h]=(RenderTex){.tex=texture(w,ht,MTLPixelFormatBGRA8Unorm,1),.rt=1};
  if(!i && samples>1)copies[h].ms=new_ms_texture(MTLPixelFormatBGRA8Unorm,w,ht,samples);
  copies[h].bytes=copies[h].tex.allocatedSize;
 }
 objects[30]=(Obj){.kind=K_TEXTURE,.fmt=21,.usage=1,.gpu=&copies[30]};
 copies[30]=(RenderTex){.tex=texture(32,16,MTLPixelFormatBGRA8Unorm,1),.rt=1};copies[30].bytes=copies[30].tex.allocatedSize;
}
int main(int argc,char **argv){@autoreleasepool{
 (void)argv;mtl=MTLCreateSystemDefaultDevice();if(!mtl){puts("SKIP Metal unavailable");return 3;}
 queue=[mtl newCommandQueue];init_blit();
 CHECK(carbon_hdr_rt(dev.backbuffer)==&bb_rt,"backbuffer ownership");
 CHECK(carbon_hdr_rt(dev.autodepth)==&ad_rt,"depth ownership");
 for(unsigned samples=1;samples<=4;samples+=3){
  cmd=[queue commandBuffer];setup_targets(samples);carbon_hdr_promotions=0;
  unsetenv("NFS_FLOAT_SCENE");setenv("NFS_HDR_OUTPUT","edr",1);hdrclip_init();
  CHECK(!float_scene_on,"HDR request does not opt in");render_float_scene_begin();
  CHECK(!carbon_hdr_promotions && copies[4].tex.pixelFormat==MTLPixelFormatBGRA8Unorm,"unset remains native");
  setenv("NFS_FLOAT_SCENE","off",1);hdrclip_init();CHECK(!float_scene_on,"explicit off");
  setenv("NFS_FLOAT_SCENE","on",1);hdrclip_init();CHECK(float_scene_on,"explicit on");
  render_float_scene_begin();CHECK(carbon_hdr_promotions==12,"all twelve owners promoted");
  render_float_scene_begin();CHECK(carbon_hdr_promotions==12,"no repeat allocation");
  float_scene_copy(30,MTLPixelFormatRGBA16Float);CHECK(copies[30].tex.pixelFormat==MTLPixelFormatBGRA8Unorm,"unclassified small texture");
  for(unsigned i=0;i<12;i++){CHECK(carbon_hdr_class(4+2*i)==(int)i,"owner classification");CHECK(carbon_hdr_class(5+2*i)==(int)i,"surface parent classification");CHECK(copies[4+2*i].tex.pixelFormat==MTLPixelFormatRGBA16Float,"float owner");}
  Cpu c={0};calls=0;carbon_hdr_allocate(&c,original);carbon_hdr_world(&c,original);carbon_hdr_dispatch(&c,original);carbon_hdr_texture(&c,original);
  CHECK(calls==4 && c.eax==123 && c.esp==16,"native bodies and ABI preserved");
  hdrclip_on=1;M32(0x00A99BBCu)=5;MF32(0x00B4CFD8u)=20;hc_frame=0;hc_finished=0;frame_serial=7;
  CHECK(hc_select(HC_WORLD)==HC_STAGES,"loading not selected");M32(0x00A99BBCu)=6;MF32(0x00B4CFD8u)=14.9;
  CHECK(hc_select(HC_WORLD)==HC_STAGES,"before sim threshold");MF32(0x00B4CFD8u)=15;
  carbon_hdr_world_phase=1;CHECK(hc_select(HC_OTHER)==HC_WORLD,"world attribution");carbon_hdr_world_phase=0;
  CHECK(hc_select(HC_OTHER)==HC_OTHER,"native post attribution");hc_finished=1;CHECK(hc_select(HC_COPY)==HC_STAGES,"one frame only");hdrclip_on=0;
  CHECK((copies[4].ms?copies[4].ms.sampleCount:1)==samples,"MSAA count preserved");
  CHECK(!copies[4].ms || (copies[4].ms.usage&MTLTextureUsageShaderRead),"MSAA readable without diagnostics");
  RenderTex *world=&copies[4];if(samples>1)boundary_texture(world->ms);else clear_texture(world->tex);world->stale=world->ms!=nil;
  M32(0x00AB04F4u)=4;carbon_hdr_world_resolve();msaa_resolve(world);inspect(world->tex);
  for(unsigned i=1;i<12;i++){
   RenderTex *r=&copies[4+2*i];
   if(argc>1 && i==1)r->tex=texture(r->tex.width,r->tex.height,MTLPixelFormatBGRA8Unorm,1);
   render_stretch(4,0,5+2*i,0,1);
   NSUInteger level,slice;id<MTLTexture> sampled=surface_target(5+2*i,&level,&slice);
   CHECK(sampled==r->tex && level==0 && slice==0,"sampling sees promoted parent");inspect(sampled);
  }
  [cmd commit];[cmd waitUntilCompleted];CHECK(cmd.status==MTLCommandBufferStatusCompleted,"last completion");
  cmd=[queue commandBuffer];setup_targets(samples);unsigned previous=carbon_hdr_promotions;render_float_scene_begin();CHECK(carbon_hdr_promotions==previous+12,"reset targets repromoted");[cmd commit];[cmd waitUntilCompleted];
 }
 printf("Carbon storage pixels=%llu clipped_channels=%llu nonfinite=%llu failures=%d\n",pixels,lost,nonfinite,failures);
 return failures || lost || nonfinite ? 1:0;
}}
'''


def make_harness():
    source = shared.mw_source(ROOT / 'runtime/render.m')
    # Reuse the shared native transport harness, selecting only this job's seams.
    source = source.replace('    if(g->tex.width!=dev.pp[0] || g->tex.height!=dev.pp[1])return;\n    NSUInteger w=dev.pp[0],h=dev.pp[1];', (PRIVATE / 'game_hdr_promote_size.h').read_text())
    start = source.index('void render_float_scene_begin(void) {')
    end = source.index('void render_float_scene_final(int preserve)', start)
    source = source[:start] + 'void render_float_scene_begin(void) {\n' + (PRIVATE / 'game_hdr_begin.h').read_text() + '}\n' + source[end:]
    start=source.index('void render_float_scene_post_target(uint32_t surface) {')
    end=source.index('// END float scene routing',start)
    source=source[:start]+'void render_float_scene_post_target(uint32_t surface) {\n'+(PRIVATE/'game_hdr_target.h').read_text()+'}\n'+source[end:]
    harness = shared.make_harness(source)
    harness = harness[:harness.index('static void init_blit(void){')] + MAIN
    harness = harness.replace('static uint32_t guest[64];','static uint32_t guest[0xC00000/4];').replace('#define MF32(a) 0.0f','#define MF32(a) (*(float *)&guest[(a)/4])')
    harness = harness.replace('if(samples>1){d.textureType', 'if(samples>1){d.usage=MTLTextureUsageRenderTarget;d.textureType')
    harness = harness.replace('objects[8]','objects[32]').replace('copies[8]','copies[32]').replace('h<8','h<32')
    # Diagnostics are disabled in this transport fixture but init/select run as production.
    resolve=(PRIVATE/'game_hdrclip_finish.h').read_text().split('static void carbon_hdr_world_resolve(void) {',1)[1].split('static id<MTLTexture> carbon_hdr_source;',1)[0]
    resolve='static void carbon_hdr_world_resolve(void) {'+resolve
    init=(PRIVATE/'game_hdrclip_init.h').read_text().replace('#include "carbon_ao.h"','static void carbon_ao_init(void){}\nstatic void carbon_ao_apply(void){}')
    init=init.replace('#include "carbon_lamplight.h"','static void carbon_lamplight_init(void){}\nstatic void carbon_lamplight_apply(void){}')
    extra=EXTRA.replace('INIT',init).replace('SELECT',(PRIVATE/'game_hdrclip_select.h').read_text()).replace('RESOLVE',resolve)
    harness=harness.replace('static Map blit_pipelines;',extra+'\nstatic Map blit_pipelines;')
    return harness


def main():
    if not (ROOT/'recomp/out/carbon-base/image.json').is_file():
        print('SKIP private assets absent');return 3
    # Compare the generated retained originals with pinned retail fragments.
    for address,digest in NATIVE_FRAGMENTS.items():
        found=False
        for path in sorted((ROOT/'recomp/out/carbon-base').glob('NFSC_*.c')):
            source=path.read_text()
            match=re.search(r'void carbon_orig_'+address+r'\(Cpu [^)]*\)\s*\{',source)
            if not match:continue
            fragment=source[match.start():source.index('\n}',match.end())+2]
            fragment=fragment.replace('void carbon_orig_','void native_',1)
            assert hashlib.sha256(fragment.encode()).hexdigest()==digest,address
            found=True;break
        assert found,'missing retained native original '+address
    hooks=json.loads((PRIVATE/'hooks/picture_07.json').read_text())['hooks']
    assert {int(h['address'],16):h['provider'] for h in hooks} == {a:'carbon_hdr_'+n for a,n in HOOKS.items()}
    actual=[int(a,16) for a in re.findall(r'case \d+: return M32\(0x([0-9A-F]+)u\)',(PRIVATE/'game_hdrclip_init.h').read_text())]
    assert actual==TARGETS
    with tempfile.TemporaryDirectory(prefix='private-picture-07-') as directory:
        tmp=Path(directory);fixture=tmp/'fixture.m';exe=tmp/'fixture';fixture.write_text(make_harness())
        shared.checked_run(['clang','-O1','-w','-fobjc-arc','-I',ROOT/'runtime','-I',ROOT/'recomp',fixture,ROOT/'runtime/post_cuts.c','-framework','Foundation','-framework','Metal','-o',exe])
        good=subprocess.run([str(exe)],capture_output=True,text=True,timeout=180)
        print('GOOD',good.stdout,good.stderr,end='')
        if good.returncode==3:return 3
        assert good.returncode==0,(good.returncode,good.stderr)
        bad=subprocess.run([str(exe),'unorm'],capture_output=True,text=True,timeout=180)
        print('UNORM',bad.stdout,bad.stderr,end='')
        assert bad.returncode==1 and 'clipped_channels=0 ' not in bad.stdout,(bad.returncode,bad.stdout,bad.stderr)
        boundary=make_harness().replace('v.rgb=select(v.rgb,max(v.rgb,float3(1.0009765625f)),v.rgb>1.0f);','')
        fixture.write_text(boundary)
        shared.checked_run(['clang','-O1','-w','-fobjc-arc','-I',ROOT/'runtime','-I',ROOT/'recomp',fixture,ROOT/'runtime/post_cuts.c','-framework','Foundation','-framework','Metal','-o',exe])
        boundary_bad=subprocess.run([str(exe)],capture_output=True,text=True,timeout=180)
        print('BOUNDARY',boundary_bad.stdout,boundary_bad.stderr,end='')
        assert boundary_bad.returncode==1 and 'clipped_channels=9 ' in boundary_bad.stdout
        # Regression control for native special surfaces: ordinary lazy allocation
        # is invalid for the renderer-owned backbuffer/depth handles.
        mutant=make_harness().replace('    if(handle==dev.backbuffer)return &bb_rt;','').replace('    if(handle==dev.autodepth)return &ad_rt;','')
        fixture.write_text(mutant)
        shared.checked_run(['clang','-O1','-w','-fobjc-arc','-I',ROOT/'runtime','-I',ROOT/'recomp',fixture,ROOT/'runtime/post_cuts.c','-framework','Foundation','-framework','Metal','-o',exe])
        surface_bad=subprocess.run([str(exe)],capture_output=True,text=True,timeout=180)
        print('SURFACE',surface_bad.stdout,surface_bad.stderr,end='')
        assert surface_bad.returncode==1 and 'backbuffer ownership' in surface_bad.stderr and 'depth ownership' in surface_bad.stderr

    report=Path(os.environ.get('NFS_METAL_CACHE',ROOT/'.metal-cache'))/'private_picture_07_test.log'
    report.parent.mkdir(parents=True,exist_ok=True)
    report.write_text('GOOD '+good.stdout+good.stderr+'UNORM '+bad.stdout+bad.stderr+'SURFACE '+surface_bad.stdout+surface_bad.stderr+'BOUNDARY '+boundary_bad.stdout+boundary_bad.stderr)
    print('PASS private_picture_07_test');return 0

if __name__=='__main__':raise SystemExit(main())
