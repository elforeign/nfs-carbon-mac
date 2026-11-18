"""Converted effect-5 glass: white 115.6511 +/- .5; old 5->25 is 14.8234 and fails.

Executes production shader bytecode and the native draw weight. Tagged glass
uploads the shared day weight (0 with the clock absent or at night: native
result); native glass uploads 0. The always-on draw mutant uploads 1 and fails;
half weight is the mean of native and source RGB, the unblended mutant fails.
H/R/fog/alpha are retained; GPU kernels compare original/modified native RGB.
Private assets absent: exit 3. No game launch.
"""
from pathlib import Path
import json
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
from build_private import ignored_output
from private_render import body

HARNESS = r'''
#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#include "sm_translate.h"
#include "tests/sm_interp.h"
#include <cmath>
#include <cstdio>
#include <cstring>
#include <vector>
#include "variant.inc"
#define CHECK(x) do{++checks;if(!(x)){fprintf(stderr,"FACADE FAIL line=%d: %s\n",__LINE__,#x);return 1;}}while(0)
int main(int argc,char **argv){ @autoreleasepool {
 bool old_control=argc>2;
 unsigned checks=0,programs=0,gpu_checks=0; float fixed=0,broken=0,native_delta=0;
 bool gpu=!getenv("CODEX_SANDBOX")||getenv("NFS_GPU_SANDBOX");
 id<MTLDevice> dev=gpu?MTLCreateSystemDefaultDevice():nil;CHECK(!gpu||dev);
 id<MTLCommandQueue> queue=[dev newCommandQueue];
 FILE *f=fopen(argv[1],"rb");CHECK(f);fseek(f,0,SEEK_END);size_t size=ftell(f);rewind(f);
 std::vector<uint32_t> blob((size+3)/4);CHECK(fread(blob.data(),1,size,f)==size);fclose(f);
 for(size_t k=0;k<size/4;++k){
  if(blob[k]!=0xfffe0101u&&blob[k]!=0xfffe0200u&&blob[k]!=0xfffe0300u&&blob[k]!=0xffff0101u&&blob[k]!=0xffff0200u&&blob[k]!=0xffff0300u)continue;
  uint32_t n=sm_token_count(blob.data()+k,size/4-k);if(!n)continue;
  auto t=blob.data()+k;uint32_t pn=0;auto p=carbon_facade_shader_variant(t,n,&pn);
  if(!p){k+=n-1;continue;}++programs;
  sm::Shader old,now;CHECK(sm::parse(t,n,old));CHECK(sm::parse(p,pn,now));
  SmOptions opt;sm_default_options(&opt);opt.emit_test_kernel=1;
  SmResult result={};CHECK(!sm_translate(p,pn,&opt,&result));
  id<MTLComputePipelineState> pipeline=nil,baseline=nil;
  if(gpu){NSError *error=nil;MTLCompileOptions *co=[MTLCompileOptions new];co.mathMode=MTLMathModeRelaxed;
   id<MTLLibrary> lib=[dev newLibraryWithSource:[NSString stringWithUTF8String:result.msl] options:co error:&error];
   if(!lib)fprintf(stderr,"%s\n",error.localizedDescription.UTF8String);CHECK(lib);
   pipeline=[dev newComputePipelineStateWithFunction:[lib newFunctionWithName:@"sm_test_kernel"] error:&error];CHECK(pipeline);
   SmResult original={};CHECK(!sm_translate(t,n,&opt,&original));
   lib=[dev newLibraryWithSource:[NSString stringWithUTF8String:original.msl] options:co error:&error];CHECK(lib);
   baseline=[dev newComputePipelineStateWithFunction:[lib newFunctionWithName:@"sm_test_kernel"] error:&error];CHECK(baseline);sm_result_free(&original);
  }
  for(float tagged:{0.f,1.f,.5f})for(float alpha:{0.f,.2f})for(float fog:{1.f,.83f})for(int side:{-1,1}){
   float c[256][4]={};int ci[16][4]={},cb[16]={};
   for(int j=0;j<4;++j){c[j][j]=1;c[4+j][j]=1;}
   c[8][0]=100;c[8][1]=.01;c[8][2]=1;c[8][3]=2;c[9][0]=1;
   c[10][0]=2;c[10][1]=1;c[4][0]=2;c[4][1]=1;
   c[11][0]=5;c[11][1]=4;c[11][2]=3;
   c[243][0]=8*.220097f;c[243][1]=8*.236764f;c[243][2]=8*.263431f;c[243][3]=tagged;
   c[31][0]=tagged;
   interp::VSIn vi={};for(auto &v:vi.v)v={.3f,.4f,.5f,1};vi.v[1]={0,0,1,1};
   unsigned col=carbon_dn_shader_key(t,n)==0xab265f28baa17c1cull?1:2;
   float bake=.2410915f+side*sqrtf(.0581309f-.2410915f*.2410915f);
   vi.v[col]={bake,bake,bake,.7f};
   interp::PSIn pi={};pi.col[0]={.424508f,.456654f,.508088f,.7f};
   pi.tex[1]={0,0,1,1};pi.tex[2]={0,0,1,1};pi.tex[3]={5,4,3,1};pi.fog={fog,fog,fog,fog};
   interp::Texture tex[3];
   for(int s=0;s<3;++s){tex[s].type=s==1?SM_TEX_CUBE:SM_TEX_2D;tex[s].d=s==1?6:1;
    for(int d=0;d<tex[s].d;++d)for(int j=0;j<4;++j)tex[s].texels.push_back(s==0?(j==3?alpha:1.f):s==1?.1f:0.f);}
   if(now.ps){for(auto &v:c)for(float &x:v)x=.2f;c[31][0]=tagged;
    for(int j=0;j<3;++j){c[j][0]=c[j][1]=c[j][2]=0;c[j][j]=1;}
   }
   interp::Context ctx;ctx.c=&c[0][0];ctx.ci=&ci[0][0];ctx.cb=cb;ctx.opt=opt;
   for(int s=0;s<3;++s)ctx.tex[s]=&tex[s];
   float expected[52]={},native[52]={};
   if(!now.ps){interp::VSOut a={},b={};CHECK(interp::run_vs(old,ctx,vi,a));CHECK(interp::run_vs(now,ctx,vi,b));
    memcpy(expected,&b,sizeof b);memcpy(native,&a,sizeof a);
    if(tagged&&!old_control){for(int j=0;j<3;++j)CHECK(fabsf(b.col[0][j]-(tagged*vi.v[col][j]*c[243][j]+(1-tagged)*a.col[0][j]))<1e-6);
     for(int j=0;j<3;++j)b.col[0][j]=a.col[0][j];CHECK(!memcmp(&a,&b,sizeof a));}
    else CHECK(!memcmp(&a,&b,sizeof a));
    if(tokens_version_placeholder){}
    if(carbon_dn_shader_key(t,n)==0x6eecdbee856b7096ull&&alpha==0&&fog==1){
     float y=255*(.2126f*expected[4]+.7152f*expected[5]+.0722f*expected[6]);if(tagged==1)fixed+=.5f*y;else if(!tagged)broken+=.5f*y;}
   }else{interp::PSOut a={},b={};CHECK(interp::run_ps(old,ctx,pi,a));CHECK(interp::run_ps(now,ctx,pi,b));
    memcpy(expected,b.oc,sizeof b.oc);memcpy(native,a.oc,sizeof a.oc);
    CHECK(b.oc[0][3]==a.oc[0][3]);if(!tagged||old_control)CHECK(!memcmp(a.oc,b.oc,sizeof a.oc));
    else{bool sm3=t[0]==0xffff0300u;for(int j=0;j<3;++j){float value=pi.col[0][j]+alpha*.1f;
      if(sm3)value=fog*value+(1-fog)*.2f;value=tagged*value+(1-tagged)*a.oc[0][j];CHECK(fabsf(b.oc[0][j]-value)<2e-6);}}
   }
   if(gpu){
    id<MTLTexture> textures[3]={nil};id<MTLSamplerState> samplers[3]={nil};
    for(int s=0;s<result.n_samplers;++s){int r=result.samplers[s].reg;
     MTLTextureDescriptor *td=[MTLTextureDescriptor new];td.pixelFormat=MTLPixelFormatRGBA32Float;td.width=td.height=1;
     td.textureType=tex[r].type==SM_TEX_CUBE?MTLTextureTypeCube:MTLTextureType2D;td.storageMode=MTLStorageModeShared;
     textures[r]=[dev newTextureWithDescriptor:td];CHECK(textures[r]);
     for(int d=0;d<tex[r].d;++d)[textures[r] replaceRegion:MTLRegionMake2D(0,0,1,1) mipmapLevel:0 slice:d withBytes:tex[r].texels.data()+4*d bytesPerRow:16 bytesPerImage:16];
     MTLSamplerDescriptor *sd=[MTLSamplerDescriptor new];sd.minFilter=sd.magFilter=MTLSamplerMinMagFilterNearest;samplers[r]=[dev newSamplerStateWithDescriptor:sd];}
    float gpu_native[52]={};
    for(int which:{0,1}){id<MTLBuffer> in=[dev newBufferWithBytes:now.ps?(void*)&pi:(void*)&vi length:now.ps?sizeof pi:sizeof vi options:MTLResourceStorageModeShared];
     id<MTLBuffer> out=[dev newBufferWithLength:sizeof expected options:MTLResourceStorageModeShared];
     id<MTLCommandBuffer> cmd=[queue commandBuffer];id<MTLComputeCommandEncoder> enc=[cmd computeCommandEncoder];
     [enc setComputePipelineState:which?pipeline:baseline];[enc setBuffer:in offset:0 atIndex:0];[enc setBuffer:out offset:0 atIndex:1];
     [enc setBytes:c length:sizeof c atIndex:2];[enc setBytes:ci length:sizeof ci atIndex:3];[enc setBytes:cb length:sizeof cb atIndex:4];SmPSAux aux={};[enc setBytes:&aux length:sizeof aux atIndex:5];
     for(int s=0;s<3;++s)if(textures[s]){[enc setTexture:textures[s] atIndex:s];[enc setSamplerState:samplers[s] atIndex:s];}
     [enc dispatchThreads:MTLSizeMake(1,1,1) threadsPerThreadgroup:MTLSizeMake(1,1,1)];[enc endEncoding];[cmd commit];[cmd waitUntilCompleted];CHECK(!cmd.error);
     float *got=(float*)out.contents;float *ref=which?expected:native;unsigned width=now.ps?16:52;
     for(unsigned j=0;j<width;++j){if(std::isfinite(ref[j]))CHECK(fabsf(got[j]-ref[j])<.00002f);++gpu_checks;}
     if(!which)memcpy(gpu_native,got,sizeof gpu_native);else if(!tagged){for(unsigned j=0;j<width;++j)if(std::isfinite(gpu_native[j])){float delta=fabsf(gpu_native[j]-got[j]);CHECK(delta<.00002f);if((now.ps&&j<3)||(!now.ps&&j>=4&&j<7))native_delta=fmaxf(native_delta,255*delta);}}
    }
   }
  }
  sm_result_free(&result);free(p);k+=n-1;
 }
 printf("FACADE white fixed=%.6f old=%.6f programs=%u checks=%u GPU=%u native_RGB_delta=%.9g\n",fixed,broken,programs,checks,gpu_checks,native_delta);
 CHECK(programs==7);CHECK(fabsf(fixed-115.6511f)<=.5f);CHECK(fabsf(broken-14.8234f)<.01f);CHECK(fabsf(broken-115.6511f)>.5f);
 return 0;
}}
'''.replace('    if(tokens_version_placeholder){}\n', '')


def run(command, expected=0):
    r = subprocess.run(list(map(str, command)), capture_output=True, text=True, timeout=240)
    if r.returncode != expected:
        raise RuntimeError(f'exit {r.returncode}, wanted {expected}: {r.stdout[-2500:]} {r.stderr[-2500:]}')
    return r.stdout.strip()


def main():
    effects = list((HERE/'out/carbon/effects').glob('*IDI_GLASSREFLECTSHADER_FX_*.bin'))
    if not effects:
        print('SKIP: private glass effect corpus absent'); return 3
    out = ignored_output(HERE/'out/carbon/facade_check')
    variant = (HERE/'private_runtime/carbon_daynight_shader.h').read_text()
    fixture = out/'shader.mm'; fixture.write_text(HARNESS)
    shaders = ROOT/'host/shaders'
    proof = []
    unblended = variant.replace('0x04000012u, output, 0xa0ff00f3u, 0x80e4000bu, 0x80e4000au,', '0x02000001u, output, 0x80e4000bu,')
    for label, text in [('good', variant), ('old-path', variant.replace('0x02010029u, 0xa0ff00f3u, 0xa1ff00f3u', '0x02010029u, 0xa1ff00f3u, 0xa0ff00f3u').replace('0x02010029u, 0xa000001fu, 0xa100001fu', '0x02010029u, 0xa100001fu, 0xa000001fu')), ('unblended', unblended)]:
        assert label == 'good' or text != variant
        (out/'variant.inc').write_text(text)
        binary = out/label
        run(['clang++','-std=c++17','-O1','-fobjc-arc','-I',shaders,'-I',out,fixture,shaders/'tests/sm_interp.cpp',shaders/'build/libsmtranslate.a','-framework','Foundation','-framework','Metal','-o',binary])
        proof.append(label+': '+run([binary,effects[0],*(['old-control'] if label=='old-path' else [])], 0 if label=='good' else 1))
        print(proof[-1])
    source = (HERE/'private_runtime/carbon_daynight.h').read_text()
    hook = json.loads((HERE/'private_runtime/hooks/facade.json').read_text())
    assert hook['hooks'][0]['address']=='0071ECB0'
    assert source.index('carbon_facade_shader_variant(tokens,count,patched_count)') < source.index('if (carbon_dn_on()) variant =')
    code = '#include "host.h"\n#include <string.h>\n#include <stdio.h>\n#include <stdlib.h>\n#include <math.h>\n'
    code += 'static int carbon_reflect_draw(Cpu*c,void(*original)(Cpu*)){return 0;}\n'
    code += 'static int carbon_tree_draw(Cpu*c,void(*original)(Cpu*)){return 0;}\n'
    code += 'static float day;static float carbon_compat_day(void){return day;}\n'
    code += 'void carbon_facade_draw(Cpu*c,void(*original)(Cpu*))'+body(source,'carbon_facade_draw')
    code += r'''
uint8_t *G;static unsigned uploads,calls;static float vc[4],pc[4];
uint32_t call_guest(Cpu*c,uint32_t f,int n,const uint32_t*a){if(n!=4||a[3]!=1)abort();
 if(f==94&&a[1]==243)memcpy(vc,G+a[2],16);else if(f==109&&a[1]==31)memcpy(pc,G+a[2],16);else abort();++uploads;return 0;}
static void native(Cpu*c){++calls;c->eax=42;c->esp+=20;}
int main(){G=calloc(1,1<<26);M32(0xab0abc)=0x1000;M32(0x1000)=0x2000;M32(0x2000+94*4)=94;M32(0x2000+109*4)=109;
 const float days[3]={0,1,.5f};
 for(int mode=0;mode<3;++mode){day=days[mode];
 for(int tag=1;tag>=0;--tag){Cpu c={0};c.esp=0x8000;c.ecx=0x222;M32(c.esp+16)=0x3000;M32(0x301c)=0x4000;M32(0x4030)=tag?0x50019:25;M32(0x226)=25;
 float want=tag?day:0;
 carbon_facade_draw(&c,native);if(fabsf(vc[0]-1.760776f)>1e-6f||fabsf(vc[1]-1.894112f)>1e-6f||fabsf(vc[2]-2.107448f)>1e-6f||vc[3]!=want||pc[0]!=want||c.esp!=0x8014||c.eax!=42||c.ecx!=0x222)return 1;}}
 if(uploads!=12||calls!=6)return 1;
 Cpu other={0};other.esp=0x8000;other.ecx=0x222;M32(other.esp+16)=0x3000;M32(0x4030)=0;carbon_facade_draw(&other,native);
 if(uploads!=12||calls!=7)return 1;
 other.esp=0x8000;M32(0x4030)=0x50019;M32(0x226)=1;carbon_facade_draw(&other,native);
 if(uploads!=12||calls!=8)return 1;puts("FACADE DRAW weights tagged=day 0/1/.5, native=0; ABI preserved");return 0;}
'''
    path = out/'draw.c'
    binary = out/'draw'
    for label, selected in [('good',code),('missing-brightness',code.replace('8*.', '4*.')),
                            ('always-on',code.replace('? carbon_compat_day() : 0;','? 1 : 0;'))]:
        assert label=='good' or selected!=code
        path.write_text(selected)
        run(['clang','-O1','-fsanitize=address,undefined','-I',HERE,'-I',ROOT/'runtime',path,'-o',binary])
        proof.append(label+': '+run([binary],0 if label=='good' else 1))
        print(proof[-1])
    (out/"proof.txt").write_text("\n".join(proof)+"\n")
    return 0


if __name__ == '__main__':
    sys.exit(main())
