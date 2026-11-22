"""World daylight: nine retail VS entries / six identities, native RGB endpoints.

Good: 3,024 checks (216 Metal comparisons), max error 5.96e-8. Missing N.L:
54 failures / max .600000024; ignored night: 108 / .622814953. Lost submission
restoration fails active=1, count-restored=0. A later pass overwriting constants
fails native check 8; good noon/dusk/midnight each pass 70 assertions, seven
uploads. Unlinked Off passes four assertions; unlinked On exits 2 explicitly.
The fixture links the complete shared math unit with NFS_GAME=2 and executes
production bytecode/callbacks. The free clock completes a day in 60 minutes.
Carbon cycle/rate=10 advances 5.000000000 h over 50 s; the pinned old
advance ignores rate and advances .333333333 h, failing the same assertion.
Fixed/hour=21 holds 21.000000000 h. State checks cover race hold, pause,
paused phase edits, loading/object replacement, seed and test-hour priority.
Private assets absent: exit 3; no game is launched.
"""
from pathlib import Path
import os
import io
import json
import hashlib
from contextlib import redirect_stdout
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
from build_private import ignored_output

SHADER_HARNESS = r'''
#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#include "sm_translate.h"
#include "tests/sm_interp.h"
#include <cmath>
#include <cstdio>
#include <vector>
#include <set>
#include "variant.inc"
static unsigned checks, failures, gpu_checks;
static float max_error;
struct ShaderEntry { uint32_t *tokens, ntokens; };
static bool submit_on;
static unsigned compiled;
uint32_t *carbon_daynight_shader(const uint32_t *tokens,uint32_t count,uint32_t *patched_count) {
    return submit_on ? carbon_dn_shader_variant(tokens,count,patched_count) : nullptr;
}
uint32_t *carbon_coat_shader(const uint32_t *,uint32_t,uint32_t *) { return nullptr; } /* the paint programs are not in this corpus */
uint32_t *carbon_road_headlight_shader(const uint32_t *,uint32_t,const uint32_t *,uint32_t,uint32_t *) { return nullptr; } /* covered by private_road_headlight_test */
static void compile_entry(ShaderEntry *entry) {
    ++compiled;
    SmOptions options; sm_default_options(&options); SmResult result = {};
    if (sm_translate(entry->tokens,entry->ntokens,&options,&result)) abort();
    sm_result_free(&result);
}
static void shader_submit(ShaderEntry *e)
#include "submit.inc"
static void check(float got, float expected) {
    ++checks;
    float error = std::fabs(got - expected);
    if (std::isnan(got) && std::isnan(expected)) error = 0;
    if (got == expected) error = 0;
    if (!(error <= 0.000002f)) ++failures;
    max_error = fmaxf(max_error, error);
}
int main(int argc, char **argv) { @autoreleasepool {
    bool gpu = !getenv("CODEX_SANDBOX") || getenv("NFS_GPU_SANDBOX");
    id<MTLDevice> device = gpu ? MTLCreateSystemDefaultDevice() : nil;
    if (gpu && !device) return 2;
    id<MTLCommandQueue> queue = [device newCommandQueue];
    unsigned programs = 0; std::set<uint64_t> identities;
    for (int a = 1; a < argc; ++a) {
        FILE *file = fopen(argv[a], "rb"); if (!file) return 2;
        fseek(file, 0, SEEK_END); size_t size = ftell(file); rewind(file);
        std::vector<uint32_t> blob((size+3)/4); fread(blob.data(), 1, size, file); fclose(file);
        for (size_t k = 0; k < size/4; ++k) {
            if (blob[k] != (0xfffe0000u|0x0200u) && blob[k] != (0xfffe0000u|0x0300u)) continue;
            size_t count = sm_token_count(blob.data()+k, size/4-k); if (!count) continue;
            auto tokens = blob.data()+k; ++programs; identities.insert(carbon_dn_shader_key(tokens, count));
            for (bool active : {false,true}) {
                submit_on = active; compiled = 0;
                ShaderEntry entry = {tokens,(uint32_t)count};
                shader_submit(&entry);
                if (compiled != 1 || entry.tokens != tokens || entry.ntokens != count) {
                    fprintf(stderr,"SUBMISSION FAIL active=%d compiled=%u restored=%d/%d\n",active,compiled,entry.tokens==tokens,entry.ntokens==count);
                    return 1;
                }
            }
            uint32_t patched_count = 0;
            uint32_t *patched = carbon_dn_shader_variant(tokens, count, &patched_count);
            if (!patched || patched_count != count+18) return 2;
            sm::Shader old_shader, new_shader;
            if (!sm::parse(tokens, count, old_shader) || !sm::parse(patched, patched_count, new_shader)) return 2;
            SmOptions options; sm_default_options(&options); options.emit_test_kernel = 1;
            SmResult result = {}; if (sm_translate(patched, patched_count, &options, &result)) return 2;
            unsigned normal = 16;
            for (int i = 0; i < result.n_inputs; ++i)
                if (result.inputs[i].usage == SM_USAGE_NORMAL) normal = result.inputs[i].reg;
            if (normal >= 16 || result.float_rel || result.float_max != 243) return 2;
            for (int c = 240; c <= 242; ++c)
                if (!(result.float_used[c/32] & (1u << (c%32)))) return 2;
            id<MTLComputePipelineState> pipeline = nil;
            if (gpu) {
                NSError *error = nil; MTLCompileOptions *co = [MTLCompileOptions new]; co.mathMode = MTLMathModeRelaxed;
                id<MTLLibrary> lib = [device newLibraryWithSource:[NSString stringWithUTF8String:result.msl] options:co error:&error];
                pipeline = [device newComputePipelineStateWithFunction:[lib newFunctionWithName:@"sm_test_kernel"] error:&error];
                if (!pipeline) { fprintf(stderr, "%s\n", error.localizedDescription.UTF8String); return 2; }
            }
            for (int sign : {-1, 1}) for (float n : {0.0f, 0.5f, 1.0f}) {
                float constants[256][4] = {}; int integers[16][4] = {}, booleans[16] = {};
                for (int i = 0; i < 240; ++i) for (int j = 0; j < 4; ++j) constants[i][j] = 0.25f;
                constants[240][0] = 0.6f; constants[240][2] = 0.8f;
                constants[241][0] = 0.6f; constants[241][1] = 0.48f; constants[241][2] = 0.22f; constants[241][3] = n;
                constants[242][0] = 0.19f; constants[242][1] = 0.24f; constants[242][2] = 0.32f;
                interp::Context context; context.c = &constants[0][0]; context.ci = &integers[0][0]; context.cb = booleans; context.opt = options;
                interp::VSIn input = {}; for (auto &v : input.v) v = {0.2f, 0.3f, 0.4f, 1.0f};
                input.v[normal] = {sign*0.6f, 0, sign*0.8f, 0};
                interp::VSOut before = {}, after = {};
                if (!interp::run_vs(old_shader, context, input, before) || !interp::run_vs(new_shader, context, input, after)) return 2;
                for (int j = 0; j < 3; ++j) {
                    float daylight = constants[242][j] + constants[241][j] * (sign > 0 ? 1 : 0);
                    check(after.col[0][j], n == 1 ? before.col[0][j] : daylight + n*(before.col[0][j]-daylight));
                }
                check(after.col[0][3], before.col[0][3]);
                for (int j = 0; j < 4; ++j) { check(after.pos[j],before.pos[j]); check(after.col[1][j],before.col[1][j]); check(after.fog[j],before.fog[j]); check(after.psize[j],before.psize[j]); }
                for (int i = 0; i < 8; ++i) for (int j = 0; j < 4; ++j) check(after.tex[i][j],before.tex[i][j]);
                if (gpu) {
                    SmPSAux aux = {};
                    id<MTLBuffer> in = [device newBufferWithBytes:&input length:sizeof input options:MTLResourceStorageModeShared];
                    id<MTLBuffer> out = [device newBufferWithLength:13*16 options:MTLResourceStorageModeShared];
                    id<MTLCommandBuffer> command = [queue commandBuffer]; id<MTLComputeCommandEncoder> enc = [command computeCommandEncoder];
                    [enc setComputePipelineState:pipeline]; [enc setBuffer:in offset:0 atIndex:0]; [enc setBuffer:out offset:0 atIndex:1];
                    [enc setBytes:constants length:sizeof constants atIndex:2]; [enc setBytes:integers length:sizeof integers atIndex:3];
                    [enc setBytes:booleans length:sizeof booleans atIndex:4]; [enc setBytes:&aux length:sizeof aux atIndex:5];
                    [enc dispatchThreads:MTLSizeMake(1,1,1) threadsPerThreadgroup:MTLSizeMake(1,1,1)]; [enc endEncoding]; [command commit]; [command waitUntilCompleted];
                    if (command.error) return 2;
                    float *values = (float *)out.contents;
                    for (int j = 0; j < 4; ++j) { check(values[4+j],after.col[0][j]); ++gpu_checks; }
                }
            }
            // A byte outside the reviewed identity must decline, even if the shader still parses.
            std::vector<uint32_t> changed(tokens,tokens+count); changed[0] ^= 1; uint32_t ignored = 0;
            if (carbon_dn_shader_variant(changed.data(),changed.size(),&ignored)) return 2;
            sm_result_free(&result); free(patched); k += count-1;
        }
    }
    if (programs != 9 || identities.size() != 6) return 2;
    printf("DAYLIGHT SHADERS entries=%u identities=%zu checks=%u GPU=%u failures=%u max_error=%.9g\n",programs,identities.size(),checks,gpu_checks,failures,max_error);
    return failures ? 1 : 0;
} }
'''


def run(command, *, expected=0, timeout=180):
    result = subprocess.run(list(map(str, command)), capture_output=True, text=True, timeout=timeout)
    if result.returncode != expected:
        raise RuntimeError(f'exit {result.returncode}, expected {expected}: {result.stdout[-1800:]} {result.stderr[-1800:]}')
    return (result.stdout + result.stderr).strip()


def shader_fixture(out, corpus):
    shaders = ROOT/'host/shaders'
    library = shaders/'build/libsmtranslate.a'
    fixture = out/'shaders.mm'; fixture.write_text(SHADER_HARNESS)
    source = (HERE/'private_runtime/carbon_daynight_shader.h').read_text()
    submit = (HERE/'private_runtime/game_compat_shader_submit.h').read_text()
    controls = {
        'good': source,
        'no-normal': source.replace('0x90e40000u | normal', '0xa0ff00f0u'),
        'night-ignored': source.replace('output, 0xa0ff00f1u', 'output, 0xa0ff00f0u'),
        'lost-restoration': source,
    }
    for name, text in controls.items():
        (out/'variant.inc').write_text(text)
        (out/'submit.inc').write_text(submit.replace('e->ntokens = count;', '/* lost restoration */') if name == 'lost-restoration' else submit)
        binary = out/name
        run(['clang++', '-std=c++17', '-O1', '-fobjc-arc', '-I', shaders, fixture,
             shaders/'tests/sm_interp.cpp', library, '-framework', 'Foundation', '-framework', 'Metal', '-o', binary])
        print(name+': '+run([binary, *corpus], expected=0 if name == 'good' else 1))


BASE_ADVANCE = r'''void carbon_daynight_advance(Cpu *c, void (*original)(Cpu *)) {
    if (!carbon_dn_on()) { original(c); return; }
    uint32_t tod = c->ecx;
    if (!tod || M32(0x00A99BBCu) != 6) {
        carbon_dn_clock.ready = carbon_dn_clock.blended = 0;
        original(c);
        return;
    }
    float phase = carbon_dn_float(tod+8);
    if (!carbon_dn_clock.ready || carbon_dn_clock.object != tod || phase != carbon_dn_clock.phase) {
        carbon_dn_clock.hour = 6 + 12 * (fmaxf(0.05f,fminf(0.95f,phase))-0.05f)/0.9;
        carbon_dn_clock.object = tod;
        carbon_dn_clock.ready = 1;
        carbon_dn_clock.blended = 0;
    }
    float dt = carbon_dn_float(0x00A99A5Cu);
    if (carbon_dn_fixed) carbon_dn_clock.hour = carbon_dn_fixed_hour;
    else if (isfinite(dt) && dt > 0)
        carbon_dn_clock.hour = carbon_dn_wrap(carbon_dn_clock.hour + dt/150.0);
    carbon_dn_sample(carbon_dn_clock.hour,carbon_dn_float(tod+0xc),carbon_dn_float(tod+0x10),&carbon_dn_clock.sample);
    DaynightSample *sample = &carbon_dn_clock.sample;
    carbon_dn_clock.phase = sample->phase;
    carbon_dn_write(tod+8,sample->phase);
    M32(tod+4) = 1;
    /* This image's direction/position are at +160/+150, not +180/+170. */
    memcpy(G+tod+0x160,sample->light,sizeof sample->light);
    carbon_dn_write(tod+0x16c,0);
    for (int k=0;k<3;++k) carbon_dn_write(tod+0x150+4*k,sample->light[k]*100000);
    carbon_dn_write(tod+0x15c,1);
    c->esp += 4;
}
'''
BASE_ADVANCE_SHA256 = 'c7329a60fc6c042cfae603bae2ba914c1769a7664c575c3bc2f048a0754a4a0c'

NATIVE_HARNESS = r'''
#include "host.h"
#include <assert.h>
#include <math.h>
#include <stdlib.h>
uint8_t *G;
int diag_on;
static float uploaded[3][4];
static unsigned uploads, original_calls, checks;
uint64_t host_ticks(void) { return 0; }
void diag_event(const char *format,...) {(void)format;}
uint32_t call_guest(Cpu *c,uint32_t fn,int n,const uint32_t *args) {
    /* Both native world and current sky callbacks upload three float4 registers. */
    assert(n==4 && args[0]==0x3000 && args[3]==3u);
    if (fn==0xf1005678u) { assert(args[1]==14); }
    else { assert(fn==0xf1001234u && args[1]==240);
        memcpy(uploaded,G+args[2],sizeof uploaded); ++uploads; }
    c->eax=0x777; c->esp+=80; return 0;
}
#include "native.inc"
#define CHECK(x) do { ++checks; if (!(x)) { fprintf(stderr,"NATIVE CHECK %u failed: %s\n",checks,#x); return 1; } } while(0)
static void native_pass(Cpu *c) {
    ++original_calls; c->esp+=4; c->eax=0x42;
    for (int i=0;i<3;++i) for (int k=0;k<4;++k) uploaded[i][k]=-9;
}
static void native_advance(Cpu *c) { ++original_calls; c->esp+=4; c->eax=0x63; }
static void native_blend(Cpu *c) {
    ++original_calls; c->esp+=8;
    float sun[]={0.6f,0.48f,0.22f}, ambient[]={0.19f,0.24f,0.32f,4};
    memcpy(G+c->ecx+0x20,sun,sizeof sun); memcpy(G+c->ecx+0x30,ambient,sizeof ambient);
}
static void native_set(Cpu *c) { ++original_calls; carbon_dn_write(0x200008,0.8f); c->esp+=4; }
int main(int argc,char **argv) {
    G=calloc(1,1<<24); assert(G); Cpu c={0}; c.esp=0x9000; c.ecx=0x200000;
    M32(0xA99BBC)=6; M32(0xB77F34)=c.ecx; M32(0xAB0ABC)=0x3000;
    M32(0x3000)=0x4000; M32(0x4000+94*4)=0xf1001234; M32(0x4000+109*4)=0xf1005678;
    carbon_dn_write(c.ecx+8,0.5f); carbon_dn_write(c.ecx+0xc,0); carbon_dn_write(c.ecx+0x10,0.5f);
    carbon_dn_write(0xA99A5C,0.25f); carbon_dn_write(c.ecx+0x170,123);
    if (argc==2 && !strcmp(argv[1],"modes")) {
        carbon_dn_write(0xA99A5C,0);
        carbon_daynight_advance(&c,native_advance);
        double initial=carbon_dn_clock.hour;
        carbon_dn_write(0xA99A5C,0.25f);
        for(int i=0;i<200;++i) carbon_daynight_advance(&c,native_advance);
        double delta=carbon_dn_wrap(carbon_dn_clock.hour-initial);
        int fixed=!strcmp(getenv("NFS_DAYNIGHT_MODE"),"fixed");
        printf("DAYLIGHT MODES dt=50 advance=%.9f hour=%.9f\n",delta,carbon_dn_clock.hour);
        CHECK(fixed ? carbon_dn_clock.hour==21 && delta==0 : fabs(delta-5)<1e-10);
        CHECK(original_calls==0 && uploads==0);
        free(G); return 0;
    }
    if (argc==2 && !strcmp(argv[1],"state")) {
        carbon_dn_write(0xA99A5C,0);
        carbon_daynight_advance(&c,native_advance);
        CHECK(carbon_dn_clock.hour==9);
        M32(0xA98284)=0x400000; M32(0x406a14)=1; M32(0x406a1c)=0x500000;
        carbon_dn_write(0xA99A5C,50);
        carbon_daynight_advance(&c,native_advance); CHECK(carbon_dn_clock.hour==9);
        carbon_dn_write(c.ecx+8,.8f);
        carbon_daynight_advance(&c,native_advance); CHECK(carbon_dn_clock.hour==9);
        M32(0x406a14)=0;
        carbon_daynight_advance(&c,native_advance); CHECK(fabs(carbon_dn_clock.hour-14)<1e-10);
        M32(0xB4CFE0)=0x600000; M32(0x600024)=4;
        carbon_daynight_advance(&c,native_advance); CHECK(fabs(carbon_dn_clock.hour-14)<1e-10);
        carbon_dn_write(c.ecx+8,.5f);
        carbon_daynight_advance(&c,native_advance);
        CHECK(fabs(carbon_dn_clock.hour-12)<1e-6);
        double held=carbon_dn_clock.hour;
        M32(0x600024)=3; M32(0xA99BBC)=3;
        carbon_daynight_advance(&c,native_advance); CHECK(!carbon_dn_clock.ready);
        M32(0xA99BBC)=6; c.ecx=0x210000;
        carbon_dn_write(c.ecx+8,.8f); carbon_dn_write(0xA99A5C,0);
        carbon_daynight_advance(&c,native_advance); CHECK(carbon_dn_clock.hour==held);
        carbon_daynight_set(&c,native_set);
        carbon_daynight_advance(&c,native_advance); CHECK(carbon_dn_clock.hour==held);
        printf("DAYLIGHT STATE race/pause/slider/loading/replacement checks=%u\n",checks);
        free(G); return 0;
    }
    if (argc==2 && !strcmp(argv[1],"clock")) {
        carbon_dn_write(0xA99A5C,0);
        carbon_daynight_advance(&c,native_advance);
        double initial=carbon_dn_clock.hour;
        carbon_dn_write(0xA99A5C,0.25f);
        carbon_daynight_advance(&c,native_advance);
        double expected=initial+0.25/150.0;
        CHECK(!carbon_dn_fixed && fabs(carbon_dn_clock.hour-expected)<1e-10);
        carbon_dn_write(0xA99A5C,150);
        for (int i=0;i<24;++i) carbon_daynight_advance(&c,native_advance);
        CHECK(fabs(carbon_dn_clock.hour-expected)<1e-10);
        CHECK(original_calls==0 && uploads==0 && c.esp==0x9068);
        printf("DAYLIGHT NATIVE clock checks=%u day_seconds=3600\n",checks);
        free(G); return 0;
    }
    if (argc==1) {
        carbon_daynight_world(&c,native_pass); CHECK(uploads==0 && c.eax==0x42 && c.esp==0x9004);
        carbon_daynight_advance(&c,native_advance); CHECK(original_calls==2 && c.eax==0x63 && c.esp==0x9008);
        uint32_t count=123,token=0xfffe0000u|0x0200u; CHECK(carbon_daynight_shader(&token,1,&count)==NULL && count==123);
        CHECK(carbon_dn_float(0x200008)==0.5f);
        printf("DAYLIGHT NATIVE Off checks=%u uploads=%u\n",checks,uploads); free(G); return 0;
    }
    float n=strtof(argv[1],NULL),phase=strtof(argv[2],NULL);
    carbon_daynight_advance(&c,native_advance);
    CHECK(original_calls==0 && c.esp==0x9004 && c.eax==0);
    CHECK(fabsf(carbon_dn_float(0x200008)-phase)<0.000001f);
    CHECK(M32(0x200004)==1 && carbon_dn_float(0x200170)==123);
    float length=0; for(int k=0;k<3;++k) length+=powf(carbon_dn_float(0x200160+4*k),2);
    CHECK(fabsf(length-1)<0.000001f && carbon_dn_float(0x20015c)==1 && carbon_dn_float(0x20016c)==0);
    carbon_daynight_blend(&c,native_blend);
    CHECK(original_calls==1 && c.esp==0x900c && uploads==0);
    CHECK(carbon_dn_float(0x200020)==0.6f && carbon_dn_float(0x200030)==0.19f);
    void (*callbacks[])(Cpu *,void (*)(Cpu *))={carbon_daynight_world,carbon_daynight_normalmap,carbon_daynight_glass,carbon_daynight_reflect,carbon_daynight_sky};
    const float sun[]={0.6f,0.48f,0.22f}, night_sun[]={0.025f,0.035f,0.055f};
    const float ambient[]={0.19f,0.24f,0.32f}, night_ambient[]={0.012f,0.018f,0.035f};
    double height=fabs(cos((carbon_dn_clock.hour-12)*acos(-1.0)/12)*cos(0.5));
    float weight=(float)fmin(1,height/DAYNIGHT_SUN_HEIGHT);
    for (int i=0;i<5;++i) {
        Cpu expected=c; native_pass(&expected); unsigned calls=original_calls;
        callbacks[i](&c,native_pass); CHECK(memcmp(&c,&expected,sizeof c)==0 && original_calls==calls+1);
        CHECK(uploads==(unsigned)i+1 && uploaded[1][3]==n);
        for(int k=0;k<3;++k) {
            CHECK(fabsf(uploaded[1][k]-weight*(sun[k]+n*(night_sun[k]-sun[k])))<0.000001f);
            CHECK(fabsf(uploaded[2][k]-(ambient[k]+n*(night_ambient[k]-ambient[k])))<0.000001f);
            CHECK(uploaded[0][k]==carbon_dn_float(0x200160+4*k));
        }
        CHECK(uploaded[0][3]==0 && fabsf(uploaded[2][3]-weight)<0.000001f);
    }
    // A repeated native weather blend must not accumulate the night mix.
    float saved[3][4]; memcpy(saved,uploaded,sizeof saved);
    carbon_daynight_blend(&c,native_blend); carbon_daynight_world(&c,native_pass);
    CHECK(memcmp(uploaded,saved,sizeof saved)==0);
    carbon_daynight_set(&c,native_set); CHECK(!carbon_dn_clock.ready && !carbon_dn_clock.blended);
    carbon_daynight_advance(&c,native_advance); CHECK(fabsf(carbon_dn_float(0x200008)-phase)<0.000001f);
    // FE/loading draws retain the original bake even when startup enables variants.
    M32(0xA99BBC)=3; carbon_daynight_advance(&c,native_advance); carbon_daynight_world(&c,native_pass);
    CHECK(uploaded[1][3]==1 && uploaded[0][0]==0 && uploaded[1][0]==0 && uploaded[2][0]==0);
    printf("DAYLIGHT NATIVE On n=%.1f phase=%.2f checks=%u uploads=%u\n",n,phase,checks,uploads);
    free(G); return 0;
}
'''


def native_fixture(out):
    source = (HERE/'private_runtime/carbon_daynight.h').read_text()
    (out/'carbon_daynight_shader.h').write_text((HERE/'private_runtime/carbon_daynight_shader.h').read_text())
    (out/'carbon_daynight_sky.h').write_text((HERE/'private_runtime/carbon_daynight_sky.h').read_text())
    (out/'carbon_worldreflect_shader.inc').write_text((HERE/'private_runtime/carbon_worldreflect_shader.inc').read_text())
    (out/'carbon_daynight_grade.h').write_text((HERE/'private_runtime/carbon_daynight_grade.h').read_text())
    (out/'native.c').write_text(NATIVE_HARNESS)
    controls = {'good': source, 'late-pass-overwrite': source.replace('carbon_dn_constants(c); \\\n', '/* missing refresh */ \\\n')}
    assert controls['late-pass-overwrite'] != source
    base = ['clang', '-DNFS_GAME=2', '-O1', '-g', '-w', '-fsanitize=address,undefined', '-I', ROOT/'runtime', '-I', HERE, '-I', out, out/'native.c']
    old = dict(os.environ)
    try:
        for key in ('NFS_DAYNIGHT_MODE','NFS_DAYNIGHT_HOUR','NFS_TEST_DAYNIGHT_START','NFS_TEST_DAYNIGHT_RATE','NFS_TEST_DAYNIGHT_HOUR'):
            os.environ.pop(key,None)
        for name, text in controls.items():
            (out/'native.inc').write_text(text)
            binary = out/('native-'+name)
            run([*base, ROOT/'runtime/daynight.c', ROOT/'runtime/daynight_clock.c', '-o', binary])
            os.environ.pop('NFS_DAYNIGHT', None)
            print(name+': '+run([binary]))
            os.environ['NFS_DAYNIGHT'] = 'on'
            for hour, n, phase in [(12, 0, 0.5), (0, 1, 0.05), (18, 0.5, 0.95), (24, 1, 0.05)]:
                os.environ['NFS_TEST_DAYNIGHT_HOUR'] = str(hour)
                print(name+': '+run([binary, n, phase], expected=0 if name == 'good' else 1))
        (out/'native.inc').write_text(source)
        os.environ.pop('NFS_TEST_DAYNIGHT_HOUR', None)
        print('good: '+run([out/'native-good', 'clock']))
        os.environ['NFS_DAYNIGHT_MODE'] = 'cycle'
        os.environ['NFS_TEST_DAYNIGHT_RATE'] = '10'
        os.environ['NFS_TEST_DAYNIGHT_START'] = '9'
        print('cycle rate=10: '+run([out/'native-good', 'modes']))
        print('state: '+run([out/'native-good', 'state']))
        os.environ['NFS_DAYNIGHT_MODE'] = 'game'
        print('game state: '+run([out/'native-good', 'state']))
        os.environ['NFS_DAYNIGHT_MODE'] = 'fixed'
        os.environ['NFS_DAYNIGHT_HOUR'] = '21'
        print('fixed hour=21: '+run([out/'native-good', 'modes']))
        os.environ['NFS_TEST_DAYNIGHT_HOUR'] = '12'
        print('test-hour priority: '+run([out/'native-good', 0, .5]))
        os.environ.pop('NFS_TEST_DAYNIGHT_HOUR')
        os.environ['NFS_DAYNIGHT_MODE'] = 'cycle'
        assert hashlib.sha256(BASE_ADVANCE.encode()).hexdigest() == BASE_ADVANCE_SHA256
        first = source.index('void carbon_daynight_advance(')
        last = source.index('\nvoid carbon_daynight_set(', first)
        (out/'native.inc').write_text(source[:first]+BASE_ADVANCE+source[last:])
        binary = out/'native-old-clock'
        run([*base, ROOT/'runtime/daynight.c', ROOT/'runtime/daynight_clock.c', '-o', binary])
        print('old clock rate=10: '+run([binary, 'modes'], expected=1))
        (out/'native.inc').write_text(source)
        binary = out/'unlinked'
        run([*base, '-o', binary])
        os.environ.pop('NFS_DAYNIGHT', None)
        print('unlinked Off: '+run([binary]))
        os.environ['NFS_DAYNIGHT'] = 'on'
        run([binary], expected=2)
        print('unlinked On: rejected with exit 2 (shared math integration required)')
        binary = out/'no-clock-symbol'
        run([*base, ROOT/'runtime/daynight.c', '-o', binary])
        run([binary], expected=2)
        print('missing clock symbol On: rejected with exit 2')
    finally:
        os.environ.clear(); os.environ.update(old)


def main():
    effects = HERE/'out/carbon/effects'
    corpus = [next(iter(effects.glob('*'+name+'*.bin')), None) for name in
              ('IDI_WORLD_FX_', 'IDI_WORLDNORMALMAP_FX_', 'IDI_WORLDREFLECT_FX_')]
    if any(p is None for p in corpus) or not (ROOT/'host/shaders/build/libsmtranslate.a').exists():
        print('SKIP: private world effect corpus / translator absent'); return 3
    feature = json.loads((HERE/'private_runtime/features/daynight.json').read_text())
    hooks = json.loads((HERE/'private_runtime/hooks/daynight.json').read_text())
    assert {row['address'] for row in hooks['hooks']} == {
        '00748B50', '00748A70', '00748AE0', '00749790', '007497F0',
        '007F1080', '007F12A0', '007F13D0'}
    for entry in feature['bindings'].values():
        assert hashlib.sha256((HERE/'private_runtime'/entry['source']).read_bytes()).hexdigest() == entry['sha256']
    out = ignored_output(HERE/'out/carbon/daynight_check')
    capture = io.StringIO()
    with redirect_stdout(capture):
        shader_fixture(out, corpus)
        native_fixture(out)
    (out/"proof.txt").write_text(capture.getvalue())
    print(capture.getvalue(), end="")
    print('PRIVATE DAYNIGHT PASS')
    return 0


if __name__ == '__main__':
    sys.exit(main())
