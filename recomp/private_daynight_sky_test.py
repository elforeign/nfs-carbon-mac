"""Dome scattering, original-gradient broken control and protected endpoints.

Source-domain Y': 143.7020721 (minimum 140), original gradient 72.7290649;
original fails 220 checks, source passes 4,756 with 864 Metal comparisons.
Source cloud coordinate (unscaled v1, u-only scroll) on a 4x4 alpha map: error
0 fixed; the native 2.77x density the old branch kept errs 0.0541986 (3 checks).
The 108 protected native/night GPU outputs are byte-identical to the pinned
original gradient. Native uploads cover overlay/city/clock/FE resets. Alpha,
fog coordinates, native cloud coverage and absent-clock tokens survive.
Night (native path, imported dome key 1F389568, c17.w=1): error against the
pinned program at the source coordinate 0 fixed; the 2.77x night sample the old
code kept differs by 0.0507360 (3 checks; native check 1 fails with the night flag unset); own domes (c17.w=0) byte-identical.
Private inputs absent: 3. No game is launched.
"""
from pathlib import Path
import hashlib
import io
import json
import os
import struct
import subprocess
import sys
from contextlib import redirect_stdout

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
from build_private import ignored_output
from recomp import PE


def run(args, expected=0, env=None):
    r = subprocess.run(list(map(str, args)), capture_output=True, text=True,
                       timeout=180, env=env)
    if r.returncode != expected:
        raise RuntimeError(f'exit {r.returncode}, expected {expected}: {r.stdout[-2000:]} {r.stderr[-2000:]}')
    return (r.stdout + r.stderr).strip()


# Pinned pre-scattering height-gradient function; no history is read by the test.
OLD_GRADIENT = r'''static uint32_t *carbon_dn_sky_variant(const uint32_t *tokens, uint32_t count,
                                      uint32_t *patched_count) {
    if (count != 441 || tokens[0] != 0xffff0300u ||
        carbon_dn_shader_key(tokens,count) != 0xb03ae6d5fda81119ull) return NULL;
    uint32_t *out = (uint32_t *)malloc((count+24)*sizeof *out);
    if (!out) return NULL;
    memcpy(out,tokens,(count-1)*sizeof *out);
    out[434] = (tokens[434] & 0x0fff0000u) | 0x8000000bu;
    const uint32_t tail[] = {
        0x03000005u, 0x8011000au, 0x90aa0002u, 0xa0ff0010u, /* mul_sat r10.x,v2.z,c16.w */
        0x04000012u, 0x8007000au, 0x8000000au, 0xa0e4000eu, 0xa0e4000fu, /* lrp day,height,sky,haze */
        0x04000012u, 0x8007000au, 0x80aa0002u, 0xa0ff000du, 0x80e4000au, /* lrp day,density,cloud light (0.5),day */
        0x04000012u, 0x8007000au, 0x90000003u, 0x80e4000au, 0xa0e40010u, /* lrp day,clear,day,fog */
        0x04000012u, 0x80070800u, 0xa0ff000eu, 0x80e4000bu, 0x80e4000au, /* lrp oC0.rgb,n,native,day */
        0x0000ffffu
    };
    memcpy(out+count-1,tail,sizeof tail);
    *patched_count = count+24;
    return out;
}

'''
OLD_GRADIENT_SHA256 = 'af9bd0ef56b391d688e18d087cc94cf76cf1edc601b3143eac0218e6082e947d'

SHADER = r'''
#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#include "sm_translate.h"
#include "tests/sm_interp.h"
#include <cmath>
#include <cassert>
#include <cstdio>
#include <cstring>
#include <vector>
#include "carbon_daynight_shader.h"
#include "baseline.inc"
#include "variant.inc"
struct ShaderEntry { uint32_t *tokens, ntokens; };
static bool submit_on;
static unsigned compiled;
#ifdef SKY_OLD_DOMAIN
static constexpr unsigned expected_tokens=465, expected_constants=17;
#else
static constexpr unsigned expected_tokens=531, expected_constants=20;
#endif
uint32_t *carbon_daynight_shader(const uint32_t *tokens,uint32_t count,uint32_t *patched_count) {
    return submit_on?carbon_dn_sky_variant(tokens,count,patched_count):nullptr;
}
uint32_t *carbon_coat_shader(const uint32_t *,uint32_t,uint32_t *) { return nullptr; } /* the paint programs are not in this corpus */
uint32_t *carbon_road_headlight_shader(const uint32_t *,uint32_t,const uint32_t *,uint32_t,uint32_t *) { return nullptr; } /* covered by private_road_headlight_test */
static void compile_entry(ShaderEntry *e) {
    ++compiled;assert(e->ntokens==(submit_on?expected_tokens:441u));
    SmOptions opt;sm_default_options(&opt);SmResult result={};
    assert(!sm_translate(e->tokens,e->ntokens,&opt,&result));sm_result_free(&result);
}
static void shader_submit(ShaderEntry *e)
#include "submit.inc"
static unsigned checks, failures, gpu_checks, protected_checks;
static float worst;
static void check(float got,float want) {
    ++checks; float e=fabsf(got-want); if (got==want) e=0;
    if (!(e<=0.0001f)) ++failures; worst=fmaxf(worst,e);
}
int main(int argc,char **argv) { @autoreleasepool {
    if (argc!=2) return 2;
    FILE *f=fopen(argv[1],"rb"); if(!f)return 2;
    std::vector<uint32_t> tokens(441); if(fread(tokens.data(),4,441,f)!=441)return 2; fclose(f);
    for(bool active:{false,true}) {
        submit_on=active;compiled=0;ShaderEntry e={tokens.data(),441};shader_submit(&e);
        if(compiled!=1||e.tokens!=tokens.data()||e.ntokens!=441)return 1;
    }
    uint32_t count=123;
    if(carbon_dn_sky_variant(tokens.data(),440,&count)||count!=123)return 2;
    auto altered=tokens; altered[288]^=1;
    if(carbon_dn_sky_variant(altered.data(),441,&count)||count!=123)return 2;
    uint32_t *patched=carbon_dn_sky_variant(tokens.data(),441,&count);
    if(!patched||count!=expected_tokens)return 2;
    uint32_t prior_count=0;
    uint32_t *prior_tokens=old_gradient_variant(tokens.data(),441,&prior_count);
    sm::Shader original,variant,prior;
    if(!prior_tokens||!sm::parse(prior_tokens,prior_count,prior))return 2;
    if(!sm::parse(tokens.data(),441,original)||!sm::parse(patched,count,variant))return 2;
    // Independently decode all original registers: c14..16 and r10/r11 are free.
    for(auto &i:original.code) {
        if(i.has_dst&&((i.dst.type==sm::R_TEMP&&i.dst.num>=4)||
                      (i.dst.type==sm::R_CONST&&i.dst.num>=14)))return 2;
        for(auto &s:i.src)if((s.type==sm::R_CONST&&s.num>=14)||
                            (s.type==sm::R_TEMP&&s.num>=4)||s.rel)return 2;
    }
    for(auto &e:original.ctab)if(e.set==2&&e.reg+e.count>14)return 2;
    SmOptions opt; sm_default_options(&opt); opt.emit_test_kernel=1;
    SmResult result={}; if(sm_translate(patched,count,&opt,&result))return 2;
    if(result.float_max!=expected_constants||result.float_rel)return 2;
    for(int k=14;k<expected_constants;++k)if(!(result.float_used[k/32]&(1u<<(k%32))))return 2;
    bool gpu=!getenv("CODEX_SANDBOX")||getenv("NFS_GPU_SANDBOX");
    id<MTLDevice> device=gpu?MTLCreateSystemDefaultDevice():nil;
    if(gpu&&!device)return 2;
    id<MTLCommandQueue> queue=[device newCommandQueue];
    id<MTLComputePipelineState> pipeline=nil,prior_pipeline=nil;
    id<MTLTexture> textures[2]={nil,nil}; id<MTLSamplerState> sampler=nil;
    if(gpu) {
        NSError *error=nil; MTLCompileOptions *co=[MTLCompileOptions new]; co.mathMode=MTLMathModeRelaxed;
        id<MTLLibrary> lib=[device newLibraryWithSource:[NSString stringWithUTF8String:result.msl] options:co error:&error];
        pipeline=[device newComputePipelineStateWithFunction:[lib newFunctionWithName:@"sm_test_kernel"] error:&error];
        SmResult old_result={};if(sm_translate(prior_tokens,prior_count,&opt,&old_result))return 2;
        id<MTLLibrary> old_lib=[device newLibraryWithSource:[NSString stringWithUTF8String:old_result.msl] options:co error:&error];
        prior_pipeline=[device newComputePipelineStateWithFunction:[old_lib newFunctionWithName:@"sm_test_kernel"] error:&error];
        sm_result_free(&old_result);if(!prior_pipeline)return 2;
        if(!pipeline){fprintf(stderr,"%s\n",error.localizedDescription.UTF8String);return 2;}
        MTLTextureDescriptor *td=[MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatRGBA32Float width:1 height:1 mipmapped:NO];
        td.storageMode=MTLStorageModeShared;
        for(int k=0;k<2;++k)textures[k]=[device newTextureWithDescriptor:td];
        MTLSamplerDescriptor *sd=[MTLSamplerDescriptor new]; sd.minFilter=sd.magFilter=MTLSamplerMinMagFilterNearest;
        sampler=[device newSamplerStateWithDescriptor:sd];
    }
    for(bool source:{false,true}) for(float z:{0.f,3500.f,7000.f,14000.f}) for(float alpha:{0.f,0.35f,1.f})
    for(float clear:{0.f,0.4f,1.f}) for(float n:{0.f,0.5f,1.f}) {
        float constants[256][4]={}; int integers[16][4]={},booleans[16]={};
        const float sky[]={0.12f,0.21f,0.37f,n},haze[]={0.31f,0.38f,0.42f,1},fog[]={0.27f,0.33f,0.39f,1.f/7000};
        memcpy(constants[14],sky,sizeof sky);memcpy(constants[15],haze,sizeof haze);memcpy(constants[16],fog,sizeof fog);
        float native_fog[]={0.215686f,0.305882f,0.341176f,1},bake[]={2,2,1,0.4f};
        memcpy(constants[0],native_fog,sizeof native_fog);memcpy(constants[1],bake,sizeof bake);
        if(source) {
            const float rayleigh[]={.291406572f,.384309356f,.481958865f,1},mie[]={.143051176f,.147644651f,.131309167f,0},light[]={0,0,1,1};
            memcpy(constants[17],rayleigh,16);memcpy(constants[18],mie,16);memcpy(constants[19],light,16);
        }
        constants[2][0]=1500;constants[2][1]=-2000;constants[2][2]=200;constants[3][0]=0.75f;
        interp::Texture clouds,moon;clouds.texels={0.65f,0.9f,0.2f,alpha};moon.texels={0.2f,0.75f,0.4f,1};
        interp::Context ctx;ctx.c=&constants[0][0];ctx.ci=&integers[0][0];ctx.cb=booleans;ctx.opt=opt;ctx.tex[0]=&clouds;ctx.tex[1]=&moon;
        interp::PSIn input={};input.tex[0]={0.3f,0.6f,0,1};input.tex[1]={5000,6000,z,1};input.fog={clear,0,0,0};
        interp::PSOut before={},after={},prior_out={};std::string error;
        if(!interp::run_ps(original,ctx,input,before,&error)||!interp::run_ps(variant,ctx,input,after,&error)){fprintf(stderr,"%s\n",error.c_str());return 2;}
        if(!interp::run_ps(prior,ctx,input,prior_out,&error))return 2;
        if(!source&&memcmp(after.oc,prior_out.oc,sizeof after.oc)){fprintf(stderr,"protected CPU endpoint changed n=%g\n",n);return 1;}
        float h=fminf(1,fmaxf(0,z/7000)),radius=sqrtf(5000.f*5000+6000.f*6000+(z-7000)*(z-7000));
        float density=alpha*(1-powf(fminf(1,radius/14700),4));
        for(int k=0;k<3;++k) {
            float day=haze[k]+h*(sky[k]-haze[k]);day+=density*(0.5f-day);
            day=fog[k]+clear*(day-fog[k]);
            if(source) {
                float mu=(200-z)/sqrtf(3500.f*3500+8000.f*8000+(200-z)*(200-z));
                day=fminf(1,fmaxf(0,(1+mu*mu)*constants[17][k]+constants[18][k]));
                day+=density*(.5f-day);
            }
            check(after.oc[0][k],n==1?before.oc[0][k]:day+n*(before.oc[0][k]-day));
        }
        if(source&&z==3500&&alpha==0&&clear==1&&n==0) {
            auto &v=after.oc[0];float y=255*(.2126f*v[0]+.7152f*v[1]+.0722f*v[2]);
            printf("SKY DOMAIN Y=%.7f minimum=140\n",y);check(fmaxf(y,140.f),y);
        }
        check(after.oc[0][3],before.oc[0][3]);
        for(int k=1;k<4;++k)for(int j=0;j<4;++j)check(after.oc[k][j],before.oc[k][j]);
        check(after.depth,before.depth);check(after.killed,before.killed);
        if(gpu) {
            float flat[48];memcpy(flat,&input,sizeof flat);SmPSAux aux={};
            id<MTLBuffer> in=[device newBufferWithBytes:flat length:sizeof flat options:MTLResourceStorageModeShared];
            id<MTLBuffer> out=[device newBufferWithLength:24*sizeof(float) options:MTLResourceStorageModeShared];
            id<MTLBuffer> control=[device newBufferWithLength:24*sizeof(float) options:MTLResourceStorageModeShared];
            for(int k=0;k<2;++k)[textures[k] replaceRegion:MTLRegionMake2D(0,0,1,1) mipmapLevel:0 withBytes:k?moon.texels.data():clouds.texels.data() bytesPerRow:16];
            id<MTLCommandBuffer> command=[queue commandBuffer];id<MTLComputeCommandEncoder> enc=[command computeCommandEncoder];
            [enc setComputePipelineState:pipeline];[enc setBuffer:in offset:0 atIndex:0];[enc setBuffer:out offset:0 atIndex:1];
            [enc setBytes:constants length:sizeof constants atIndex:2];[enc setBytes:integers length:sizeof integers atIndex:3];
            [enc setBytes:booleans length:sizeof booleans atIndex:4];[enc setBytes:&aux length:sizeof aux atIndex:5];
            for(int k=0;k<2;++k){[enc setTexture:textures[k] atIndex:k];[enc setSamplerState:sampler atIndex:k];}
            [enc dispatchThreads:MTLSizeMake(1,1,1) threadsPerThreadgroup:MTLSizeMake(1,1,1)];
            if(!source) {
                [enc setComputePipelineState:prior_pipeline];[enc setBuffer:control offset:0 atIndex:1];
                [enc dispatchThreads:MTLSizeMake(1,1,1) threadsPerThreadgroup:MTLSizeMake(1,1,1)];
            }
            [enc endEncoding];[command commit];[command waitUntilCompleted];
            if(command.error)return 2;
            if((!source)&&memcmp(control.contents,out.contents,4*sizeof(float))) {
                fprintf(stderr,"protected GPU endpoint changed: source=%d n=%g\n",source,n);return 1;
            }
            if(!source)++protected_checks;
            for(int k=0;k<4;++k){check(((float *)out.contents)[k],after.oc[0][k]);++gpu_checks;}
        }
    }
    {   // Cloud coordinate: 4x4 alpha map, the source branch samples unscaled v1 with a u-only scroll.
        float constants[256][4]={}; int integers[16][4]={},booleans[16]={};
        const float rayleigh[]={.291406572f,.384309356f,.481958865f,1},mie[]={.143051176f,.147644651f,.131309167f,0},light[]={0,0,1,1};
        memcpy(constants[17],rayleigh,16);memcpy(constants[18],mie,16);memcpy(constants[19],light,16);
        constants[2][0]=1500;constants[2][1]=-2000;constants[2][2]=200;constants[3][0]=0.75f;
        interp::Texture clouds,moon;clouds.w=clouds.h=4;clouds.texels.resize(64);moon.texels={0.2f,0.75f,0.4f,1};
        for(int k=0;k<16;++k){clouds.texels[4*k]=0.65f;clouds.texels[4*k+1]=0.9f;clouds.texels[4*k+2]=0.2f;clouds.texels[4*k+3]=(k+1)/17.f;}
        interp::Context ctx;ctx.c=&constants[0][0];ctx.ci=&integers[0][0];ctx.cb=booleans;ctx.opt=opt;ctx.tex[0]=&clouds;ctx.tex[1]=&moon;
        interp::PSIn input={};input.tex[0]={0.3f,0.6f,0,1};input.tex[1]={5000,6000,3500,1};input.fog={1,0,0,0};
        interp::PSOut after={};std::string error;
        if(!interp::run_ps(variant,ctx,input,after,&error))return 2;
        float u=0.3f-0.75f*0.14f,radius=sqrtf(5000.f*5000+6000.f*6000+3500.f*3500);
        float alpha=clouds.texels[4*(int(0.6f*4)*4+int(u*4))+3],density=alpha*(1-powf(radius/14700,4));
        float mu=(200-3500.f)/sqrtf(3500.f*3500+8000.f*8000+3300.f*3300),worst_cloud=0;
        for(int k=0;k<3;++k) {
            float day=fminf(1,fmaxf(0,(1+mu*mu)*constants[17][k]+constants[18][k]));day+=density*(.5f-day);
            worst_cloud=fmaxf(worst_cloud,fabsf(after.oc[0][k]-day));check(after.oc[0][k],day);
        }
        printf("SKY CLOUD UV error=%.7f (unscaled v, u-only scroll)\n",worst_cloud);
    }
    {   // Night (n=1): the native path itself samples the dome once over v, equal to the pinned program at the 2.77x-equivalent coordinate.
        float constants[256][4]={}; int integers[16][4]={},booleans[16]={};
        const float sky[]={0.12f,0.21f,0.37f,1},haze[]={0.31f,0.38f,0.42f,1},fog[]={0.27f,0.33f,0.39f,1.f/7000};
        memcpy(constants[14],sky,sizeof sky);memcpy(constants[15],haze,sizeof haze);memcpy(constants[16],fog,sizeof fog);
        const float native_fog[]={0.215686f,0.305882f,0.341176f,1},bake[]={2,2,1,0.4f};
        memcpy(constants[0],native_fog,sizeof native_fog);memcpy(constants[1],bake,sizeof bake);
        constants[2][0]=1500;constants[2][1]=-2000;constants[2][2]=200;constants[3][0]=0.75f;
        interp::Texture clouds,moon;clouds.w=clouds.h=4;clouds.texels.resize(64);moon.texels={0.2f,0.75f,0.4f,1};
        for(int k=0;k<16;++k){clouds.texels[4*k]=0.65f;clouds.texels[4*k+1]=0.9f;clouds.texels[4*k+2]=0.2f;clouds.texels[4*k+3]=k==8?1.f:0.f;}
        interp::Context ctx;ctx.c=&constants[0][0];ctx.ci=&integers[0][0];ctx.cb=booleans;ctx.opt=opt;ctx.tex[0]=&clouds;ctx.tex[1]=&moon;
        interp::PSIn input={};input.tex[0]={0.3f,0.6f,0,1};input.tex[1]={5000,6000,3500,1};input.fog={1,0,0,0};
        const float rayleigh[]={.291406572f,.384309356f,.481958865f,1},mie[]={.143051176f,.147644651f,.131309167f,0},light[]={0,0,1,1};
        interp::PSOut got={},native_dome={},want={};std::string error;
        // Own dome: c17.w=1 at night. Reference: the pinned program at the v1 whose 2.77x sample is the source coordinate (0.3-0.105, 0.6).
        memcpy(constants[17],rayleigh,16);memcpy(constants[18],mie,16);memcpy(constants[19],light,16);
        if(!interp::run_ps(variant,ctx,input,got,&error))return 2;
        interp::PSIn reference=input;reference.tex[0]={0.3f/2.77f,(0.6f+0.21f)/2.77f,0,1};
        if(!interp::run_ps(original,ctx,reference,want,&error))return 2;
        float worst_night=0;for(int k=0;k<3;++k){worst_night=fmaxf(worst_night,fabsf(got.oc[0][k]-want.oc[0][k]));check(got.oc[0][k],want.oc[0][k]);}
        // The native 2.77x night sample on the same input reads another texel.
        interp::PSOut scaled={};if(!interp::run_ps(original,ctx,input,scaled,&error))return 2;
        float scaled_gap=0;for(int k=0;k<3;++k)scaled_gap=fmaxf(scaled_gap,fabsf(scaled.oc[0][k]-want.oc[0][k]));
        if(!(scaled_gap>0.03f)){fprintf(stderr,"night control has no cloud contrast\n");return 2;}
        // Carbon's own domes (c17.w=0) run the original night path unchanged.
        memset(constants[17],0,48);
        if(!interp::run_ps(variant,ctx,input,native_dome,&error))return 2;
        for(int k=0;k<4;++k)check(native_dome.oc[0][k],scaled.oc[0][k]);
        printf("SKY NIGHT CLOUD UV error=%.7f (native night samples the pinned program's source coordinate; the 2.77x sample differs by %.7f)\n",worst_night,scaled_gap);
    }
    printf("SKY SHADER checks=%u GPU=%u protected_GPU=%u failures=%u max_error=%.9g\n",checks,gpu_checks,protected_checks,failures,worst);
    sm_result_free(&result);free(prior_tokens);free(patched);return failures?1:0;
} }
'''

NATIVE = r'''
#include "host.h"
#include <assert.h>
#include <math.h>
uint8_t *G;int diag_on;
uint64_t host_ticks(void) { return 0; }
void diag_event(const char *format,...) {(void)format;}
static float pixels[6][4];static unsigned pixel_uploads,calls,checks;
uint32_t call_guest(Cpu *c,uint32_t fn,int n,const uint32_t *args) {
    assert(n==4&&args[0]==0x3000&&args[3]==(fn==0xf1005678?6u:3u));
    if(fn==0xf1005678){assert(args[1]==14);memcpy(pixels,G+args[2],sizeof pixels);++pixel_uploads;}
    else assert(fn==0xf1001234&&args[1]==240);
    c->eax=0x777;c->esp+=80;return 0;
}
#include "native.inc"
#define CHECK(x) do{++checks;if(!(x)){fprintf(stderr,"SKY NATIVE CHECK %u: %s\n",checks,#x);return 1;}}while(0)
static void native(Cpu *c){++calls;c->eax=123;c->esp+=4;}
static void fog_original(Cpu *c) {
    uint32_t f=M32(c->esp+8);float v[]={55.f/255,78.f/255,87.f/255,1,0,880,0.23f,2,0.000258f,-1400};
    memcpy(G+f,v,sizeof v);native(c);
}
int main(int argc,char **argv) {
    G=calloc(1,1<<24);assert(G);Cpu c={0};c.esp=0x9000;c.ecx=0x200000;
    M32(0xA99BBC)=6;M32(0xB77F34)=c.ecx;M32(0xB4295C)=0x5000;
    M32(0xAB0ABC)=0x3000;M32(0x3000)=0x4000;M32(0x4000+94*4)=0xf1001234;M32(0x4000+109*4)=0xf1005678;
    float sky[]={0.12f,0.21f,0.37f},haze[]={0.31f,0.38f,0.42f};
    memcpy(G+c.ecx+0x70,sky,sizeof sky);memcpy(G+c.ecx+0x80,haze,sizeof haze);
    carbon_dn_write(c.ecx+8,0.5f);carbon_dn_write(c.ecx+0x10,0.5f);
    float n=argc>1?strtof(argv[1],NULL):1;
    CHECK(carbon_daynight_night()==1);
    if(argc>1){carbon_daynight_advance(&c,native);CHECK(carbon_daynight_night()==1);carbon_daynight_blend(&c,native);}
    CHECK(carbon_daynight_night()==n);
    for(int repeat=0;repeat<2;++repeat) {
        M32(c.esp+8)=0x5000;Cpu expected=c;fog_original(&expected);unsigned before=calls;
        float original[10];memcpy(original,G+0x5000,sizeof original);
        carbon_daynight_fog(&c,fog_original);CHECK(calls==before+1&&memcmp(&c,&expected,sizeof c)==0);
        for(int k=0;k<3;++k)CHECK(fabsf(carbon_dn_float(0x5000+4*k)-(haze[k]+n*(original[k]-haze[k])))<1e-7f);
        CHECK(memcmp(G+0x500c,original+3,7*sizeof(float))==0);
    }
    Cpu expected=c;native(&expected);unsigned before=calls;
    carbon_daynight_sky(&c,native);CHECK(calls==before+1&&!memcmp(&c,&expected,sizeof c));
    CHECK(pixel_uploads==(argc>1?1u:0u));
    if(argc>1) {
        CHECK(pixels[0][3]==n&&pixels[1][3]==1&&pixels[2][3]==1.f/7000);
        for(int k=0;k<3;++k){CHECK(pixels[0][k]==(n<1?sky[k]:0));CHECK(pixels[1][k]==(n<1?haze[k]:0));CHECK(pixels[2][k]==(n<1?haze[k]:0));}
        carbon_dn_clock.blended=0;CHECK(carbon_daynight_night()==1);carbon_dn_clock.blended=1;
        carbon_dn_clock.ready=0;CHECK(carbon_daynight_night()==1);carbon_dn_clock.ready=1;
        M32(0xA99BBC)=3;CHECK(carbon_daynight_night()==1);
        expected=c;native(&expected);carbon_daynight_sky(&c,native);CHECK(!memcmp(&c,&expected,sizeof c)&&pixels[0][3]==1);
        M32(c.esp+8)=0x5000;expected=c;fog_original(&expected);float original[10];memcpy(original,G+0x5000,sizeof original);
        carbon_daynight_fog(&c,fog_original);CHECK(!memcmp(G+0x5000,original,sizeof original)&&!memcmp(&c,&expected,sizeof c));
    }
    if(argc>1 && n==1) {
        M32(0xA99BBC)=6;M32(0xA73358)=1;M32(0xB77918)=0x1F389568;
        setenv("NFS_CARBON_TRACK_OVERLAY","fixture",1);
        carbon_dn_sky_constants(&c);CHECK(pixels[3][3]==1);
        for(unsigned other=0;other<2;++other){M32(0xB77918)=other?0xBE43EDBBu:0xED85BA82u;carbon_dn_sky_constants(&c);CHECK(pixels[3][3]==0);}
    }
    if(argc>1 && n<1) {
        M32(0xA99BBC)=6;M32(0xA73358)=1;M32(0xB77918)=0x1F389568;
        setenv("NFS_CARBON_TRACK_OVERLAY","fixture",1);
        carbon_dn_sky_constants(&c);CHECK(pixels[3][3]==1);
        for(int k=0;k<3;++k) {
            double br=sky[k]*(.0001+.0099*.01),bm=haze[k]*(.0001+.0099*.001);
            double gain=10*(1-exp(-15000*(br+bm)))/(br+bm);
            CHECK(fabs(pixels[3][k]-br*.059683103*gain)<1e-6);
            CHECK(fabs(pixels[4][k]-bm*.07957747*gain)<1e-6);
        }
        for(int state=0;state<7;++state) {
            M32(0xB77918)=state==0?0xED85BA82:state==1?0xBE43EDBB:0x1F389568;
            M32(0xA73358)=state==2?0:1;
            setenv("NFS_CARBON_TRACK_OVERLAY",state==3?"":"fixture",1);
            carbon_dn_clock.ready=state!=4;carbon_dn_clock.blended=state!=5;
            M32(0xA99BBC)=state==6?3:6;
            carbon_dn_sky_constants(&c);CHECK(pixels[3][3]==(state==4||state==5?1:0));
        }
    }
    printf("SKY NATIVE n=%.1f checks=%u uploads=%u\n",n,checks,pixel_uploads);free(G);return 0;
}
'''


def fixtures(out, tokens):
    source = (HERE/'private_runtime/carbon_daynight_sky.h').read_text()
    variant = source.split('static uint32_t *carbon_dn_sky_variant', 1)[1].split('static void carbon_dn_sky_constants', 1)[0]
    variant = 'static uint32_t *carbon_dn_sky_variant'+variant
    (out/'baseline.inc').write_text(OLD_GRADIENT.replace('carbon_dn_sky_variant','old_gradient_variant'))
    (out/'tokens.bin').write_bytes(tokens)
    (out/'shader.mm').write_text(SHADER)
    (out/'submit.inc').write_bytes((HERE/'private_runtime/game_compat_shader_submit.h').read_bytes())
    (out/'native.c').write_text(NATIVE)
    (out/'native.inc').write_text((HERE/'private_runtime/carbon_daynight.h').read_text())
    (out/'carbon_daynight_shader.h').write_bytes((HERE/'private_runtime/carbon_daynight_shader.h').read_bytes())
    (out/'carbon_worldreflect_shader.inc').write_bytes((HERE/'private_runtime/carbon_worldreflect_shader.inc').read_bytes())
    (out/'carbon_daynight_grade.h').write_bytes((HERE/'private_runtime/carbon_daynight_grade.h').read_bytes())
    shaders = ROOT/'host/shaders'
    assert hashlib.sha256(OLD_GRADIENT.encode()).hexdigest() == OLD_GRADIENT_SHA256
    for name, text in [('good', variant), ('old-gradient', '#define SKY_OLD_DOMAIN 1\n'+OLD_GRADIENT), ('no-lerp', variant.replace('0x04000012u, 0x80070800u, 0xa0ff000eu, 0x80e4000bu, 0x80e4000au', '0x02000001u, 0x80070800u, 0x80e4000bu, 0x00000000u, 0x00000000u')), ('scaled-clouds', variant.replace('0x8002000cu, 0x90550001u', '0x8002000cu, 0x80550000u')), ('scaled-night', variant.replace('0x80020000u, 0x90550001u', '0x80020000u, 0x80550000u'))]:
        assert name == 'good' or text != variant
        (out/'variant.inc').write_text(text)
        binary = out/('shader-'+name)
        run(['clang++', '-std=c++17', '-O1', '-fobjc-arc', '-I', shaders, '-I', out,
             out/'shader.mm', shaders/'tests/sm_interp.cpp', shaders/'build/libsmtranslate.a',
             '-framework', 'Foundation', '-framework', 'Metal', '-o', binary])
        print(name+': '+run([binary, out/'tokens.bin'], 0 if name == 'good' else 1))
    env = dict(os.environ)
    env.pop('NFS_DAYNIGHT', None)
    for name, text in [('good', source), ('night-flag-ignored', source.replace('if (imported) constants[3][3] = 1;', '')), ('fog-night-ignored', source.replace('haze+n*(native-haze)', 'haze+0*(native-haze)').replace('fog && tod && n < 1', 'fog && tod'))]:
        assert name == 'good' or text != source
        (out/'carbon_daynight_sky.h').write_text(text)
        binary = out/('native-'+name)
        run(['clang', '-DNFS_GAME=2', '-O1', '-g', '-w', '-fsanitize=address,undefined',
             '-I', ROOT/'runtime', '-I', HERE, '-I', out, out/'native.c', ROOT/'runtime/daynight.c', ROOT/'runtime/daynight_clock.c', '-o', binary])
        if name == 'good':
            print('Off: '+run([binary], env=env))
        for hour, n in [(12, 0), (18, 0.5), (0, 1)]:
            active = {**env, 'NFS_DAYNIGHT': 'on', 'NFS_TEST_DAYNIGHT_HOUR': str(hour)}
            print(name+f' hour={hour}: '+run([binary, n], 0 if name == 'good' else 1, active))


def main():
    image = HERE/'out/carbon/image.json'
    if not image.is_file() or not (ROOT/'host/shaders/build/libsmtranslate.a').is_file():
        print('SKIP: private image / translator absent'); return 3
    binding = json.loads(image.read_text())
    if not Path(binding['exe']).is_file():
        print('SKIP: private image absent'); return 3
    pe = PE(binding['exe'], expected_sha256=binding['sha256'])
    tokens = pe.read(0x00C0F794, 1764)
    assert struct.unpack_from('<I', tokens)[0] == (0xffff0000|0x0300)
    feature = json.loads((HERE/'private_runtime/features/daynight.json').read_text())
    for row in feature['bindings'].values():
        assert hashlib.sha256((HERE/'private_runtime'/row['source']).read_bytes()).hexdigest() == row['sha256']
    hook = json.loads((HERE/'private_runtime/hooks/daynight_sky.json').read_text())['hooks']
    assert len(hook) == 1 and hook[0]['address'] == '0073E890' and hook[0]['provider'] == 'carbon_daynight_fog'
    assert hashlib.sha256(pe.read(0x0073E890, 16)).hexdigest() == hook[0]['witness']['sha256']
    out = ignored_output(HERE/'out/carbon/daynight_sky_check')
    capture = io.StringIO()
    with redirect_stdout(capture):
        fixtures(out, tokens)
    (out/'proof.txt').write_text(capture.getvalue())
    print(capture.getvalue(), end='')
    print('PRIVATE DAYNIGHT SKY PASS')
    return 0


if __name__ == '__main__':
    sys.exit(main())
