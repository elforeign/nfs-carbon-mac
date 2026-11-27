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
Live Neutral upload cards (world/normal map, glass, road, facade, tree):
1,080 cards across PC/X360, both treatment quartets, five weather weights,
three high-sun weights and noon/+5 deg; max dxy 1.54e-8 (limit .003), max
RGB error 2.99e-8 versus the actual MW Neutral setters. Frozen-noon direct
control dxy .0795883, 120 failed cards per dataset (same .003 limit).
Retail MW (NFS_WORLD_LIGHTING=original): the same 540 cards per dataset
against the authored record as MW Original uploads it: max dxy 1.26e-8,
RGB error 2.98e-8; the old always-Neutral blend fails 536/540, max dxy .1766.
Cards isolate direct/ambient before bake, fog, specular and post composition;
retail shader transport and Metal checks above prove the material gains.
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
    bool d65 = lighting_mode_d65();
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
            if (!patched || patched_count != count+(d65 ? 43 : 18)) return 2;
            sm::Shader old_shader, new_shader;
            if (!sm::parse(tokens, count, old_shader) || !sm::parse(patched, patched_count, new_shader)) return 2;
            SmOptions options; sm_default_options(&options); options.emit_test_kernel = 1;
            SmResult result = {}; if (sm_translate(patched, patched_count, &options, &result)) return 2;
            unsigned normal = 16;
            for (int i = 0; i < result.n_inputs; ++i)
                if (result.inputs[i].usage == SM_USAGE_NORMAL) normal = result.inputs[i].reg;
            if (normal >= 16 || result.float_rel || result.float_max != (d65 ? 250 : 243)) return 2;
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
                if (d65) {
                    for (int j = 0; j < 3; ++j) {
                        constants[241][j] = .80642f;
                        constants[242][j] = .235146f;
                    }
                    constants[249][0] = .2126f;
                    constants[249][1] = .7152f;
                    constants[249][2] = .0722f;
                    constants[249][3] = n * .034318f;
                }
                interp::Context context; context.c = &constants[0][0]; context.ci = &integers[0][0]; context.cb = booleans; context.opt = options;
                interp::VSIn input = {}; for (auto &v : input.v) v = {0.2f, 0.3f, 0.4f, 1.0f};
                input.v[normal] = {sign*0.6f, 0, sign*0.8f, 0};
                interp::VSOut before = {}, after = {};
                if (!interp::run_vs(old_shader, context, input, before) || !interp::run_vs(new_shader, context, input, after)) return 2;
                for (int j = 0; j < 3; ++j) {
                    float daylight = constants[242][j] + constants[241][j] * (sign > 0 ? 1 : 0);
                    float bake = before.col[0][j];
                    if (d65) bake = .2126f*before.col[0][0] + .7152f*before.col[0][1] + .0722f*before.col[0][2];
                    float moon = sign > 0 ? constants[249][3] : 0;
                    float expected = (n == 1 ? bake : daylight + n*(bake-daylight)) + moon;
                    if (d65 && (tokens[0]&0xff00)==0x200)
                        expected = fminf(1,fmaxf(0,expected)); /* SM2 oD0 colour clamp. */
                    if (d65 && fabsf(after.col[0][j]-expected)>2e-6f)
                        fprintf(stderr,"world %016llx n=%g sign=%d channel=%d native=%g,%g,%g got=%g want=%g\n",
                            (unsigned long long)carbon_dn_shader_key(tokens,count),n,sign,j,
                            before.col[0][0],before.col[0][1],before.col[0][2],after.col[0][j],expected);
                    check(after.col[0][j],expected);
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
                    for (int j = 0; j < 4; ++j) {
                        if (d65 && fabsf(values[4+j]-after.col[0][j])>2e-6f)
                            fprintf(stderr,"Metal %016llx n=%g sign=%d channel=%d got=%g want=%g\n",
                                (unsigned long long)carbon_dn_shader_key(tokens,count),n,sign,j,values[4+j],after.col[0][j]);
                        check(values[4+j],after.col[0][j]); ++gpu_checks;
                    }
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


def run(command, *, expected=0, timeout=180, env=None):
    result = subprocess.run(list(map(str, command)), capture_output=True, text=True, timeout=timeout, env=env)
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
        run(['clang++', '-std=c++17', '-O1', '-fobjc-arc', '-I', shaders, '-I', ROOT/'runtime', fixture,
             shaders/'tests/sm_interp.cpp', library, '-framework', 'Foundation', '-framework', 'Metal', '-o', binary])
        env = {k: v for k, v in os.environ.items() if k != 'NFS_WORLD_LIGHTING'}
        print(name+': '+run([binary, *corpus], expected=0 if name == 'good' else 1, env=env))
        if name == 'good':
            print('neutral-d65: '+run([binary, *corpus], env=dict(env, NFS_WORLD_LIGHTING='neutral-d65')))


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
static float uploaded[3][4], neutral[4], disc[2][4];
static unsigned uploads, original_calls, checks;
uint64_t host_ticks(void) { return 0; }
uint64_t diag_current_frame(void) { return 0; }
void diag_event(const char *format,...) {(void)format;}
uint32_t call_guest(Cpu *c,uint32_t fn,int n,const uint32_t *args) {
    /* Both native world and current sky callbacks upload three float4 registers. */
    assert(n==4 && args[0]==0x3000);
    if (args[1]==249) {
        assert(fn==0xf1001234u && args[3]==1u);
        memcpy(neutral,G+args[2],sizeof neutral);
        c->eax=0x777; c->esp+=80; return 0;
    }
    if (args[1]==17) {
        assert(fn==0xf1005678u && args[3]==2u);
        memcpy(disc,G+args[2],sizeof disc);
        c->eax=0x777; c->esp+=80; return 0;
    }
    assert(args[3]==3u);
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
    const float noon[] = {1,.8f,.3f};
    memcpy(G+c->ecx+0x20,lighting_mode_d65() ? noon : sun,sizeof sun);
    memcpy(G+c->ecx+0x30,ambient,sizeof ambient);
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
    if (argc==2 && !strcmp(argv[1],"d65")) {
        diag_on = 1;
        carbon_daynight_advance(&c,native_advance);
        carbon_daynight_blend(&c,native_blend);
        c.esp=0x9000;
        carbon_daynight_sky(&c,native_pass);
        CHECK(uploads==1);
        for (int k=0;k<3;++k) {
            CHECK(fabsf(disc[0][k] + 83666.00265f * carbon_dn_clock.sample.sun[k]) < .005f);
            CHECK(disc[1][k] == .992098f);
        }
        CHECK(disc[0][3] == 1);
        for (int k=1;k<3;++k) {
            CHECK(uploaded[1][k]==uploaded[1][0]);
            CHECK(uploaded[2][k]==uploaded[2][0]);
        }
        CHECK(uploaded[1][0]>0 && uploaded[2][0]>0);
        float sun, ambient;
        CHECK(carbon_daynight_d65_rig(&sun,&ambient) && sun>0 && ambient>0);
        CHECK(neutral[3]>=0);
        float y = neutral[0]+neutral[1]+neutral[2];
        CHECK(fabsf(y-(getenv("NFS_TEST_DAYNIGHT_MOON_ONLY") ? 0 : 1))<1e-6f);
        if (carbon_dn_clock.hour == 0) CHECK(fabsf(neutral[3]-.034318f)<1e-6f);
        printf("D65 upload hour %.6f day=%.6f ambient=%.6f moon=%.6f bake weight=%.6f\n",
            carbon_dn_clock.hour,uploaded[1][0],uploaded[2][0],neutral[3],y);
        free(G); return 0;
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
            CHECK(fabsf(uploaded[1][k]-weight*carbon_dn_clock.record.diffuse[k])<0.000001f);
            CHECK(fabsf(uploaded[2][k]-carbon_dn_clock.record.ambient[k])<0.000001f);
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
    (out/'carbon_mw_grade.h').write_bytes((HERE/'private_runtime/carbon_mw_grade.h').read_bytes())
    (out/'native.c').write_text(NATIVE_HARNESS)
    controls = {'good': source, 'late-pass-overwrite': source.replace('carbon_dn_constants(c); \\\n', '/* missing refresh */ \\\n')}
    assert controls['late-pass-overwrite'] != source
    base = ['clang', '-DNFS_GAME=2', '-O1', '-g', '-w', '-fsanitize=address,undefined', '-I', ROOT/'runtime', '-I', HERE, '-I', out, '-I', HERE/'out/carbon/runtime', out/'native.c']
    old = dict(os.environ)
    try:
        for key in ('NFS_DAYNIGHT_MODE','NFS_DAYNIGHT_HOUR','NFS_TEST_DAYNIGHT_START','NFS_TEST_DAYNIGHT_RATE','NFS_TEST_DAYNIGHT_HOUR'):
            os.environ.pop(key,None)
        for name, text in controls.items():
            (out/'native.inc').write_text(text)
            binary = out/('native-'+name)
            run([*base, ROOT/'runtime/daynight.c', ROOT/'runtime/daynight_clock.c', '-o', binary])
            os.environ['NFS_DAYNIGHT'] = 'off'
            print(name+': '+run([binary]))
            os.environ['NFS_DAYNIGHT'] = 'on'
            for hour, n, phase in [(12, 0, 0.5), (0, 1, 0.05), (18, 0.5, 0.95), (24, 1, 0.05)]:
                os.environ['NFS_TEST_DAYNIGHT_HOUR'] = str(hour)
                if hour == 12: os.environ.pop('NFS_DAYNIGHT', None)
                else: os.environ['NFS_DAYNIGHT'] = 'on'
                print(name+': '+run([binary, n, phase], expected=0 if name == 'good' else 1))
        (out/'native.inc').write_text(source)
        for hour, isolate in ((12,False), (6.379999,False), (0,False), (0,True)):
            env = dict(os.environ, NFS_WORLD_LIGHTING='neutral-d65', NFS_TEST_DAYNIGHT_HOUR=str(hour))
            if isolate: env['NFS_TEST_DAYNIGHT_MOON_ONLY'] = '1'
            print(run([out/'native-good', 'd65'], env=env))
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
        os.environ['NFS_DAYNIGHT'] = 'off'
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



COLOUR_HARNESS = r'''
#include "host.h"
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
uint8_t *G;
int diag_on;
uint64_t host_ticks(void) { return 0; }
uint64_t diag_current_frame(void) { return 0; }
void diag_event(const char *fmt,...) { (void)fmt; }
static float vs[256][4], ps[256][4];
uint32_t call_guest(Cpu *c,uint32_t f,int n,const uint32_t *a) {
    (void)c; (void)n;
    if (f==94 || f==109) memcpy((f==94?vs:ps)[a[1]],G+a[2],16*a[3]);
    return 0;
}
#include "native.inc"
static float rf(uint32_t a) { return carbon_dn_float(a); }
#define SUN_SCALE 0x9018C4u
#define GAMEFLOW_STATE 0x925E90u
static int wl_mode(void) { return 1; }
static const char *kTunnelV[]={"pc","keep","sky"};
static struct { int value; } s_tunnel;
#include "mw_reference.inc"
#include "colour_records.inc"
static void native(Cpu *c) { (void)c; }
static double max_dxy, control_dxy, max_rgb_error;
static unsigned cards, failures;
static void xy(const float *rgb,double out[2]) {
    double X=.4124564*rgb[0]+.3575761*rgb[1]+.1804375*rgb[2];
    double Y=.2126729*rgb[0]+.7151522*rgb[1]+.0721750*rgb[2];
    double Z=.0193339*rgb[0]+.1191920*rgb[1]+.9503041*rgb[2];
    out[0]=X/(X+Y+Z); out[1]=Y/(X+Y+Z);
}
static void card(const float *got,const float *reference,float gain) {
    float a[3],b[3];
    for (int k=0;k<3;++k) {
        a[k]=gain*got[k]; b[k]=gain*reference[k];
        double e=fabs(a[k]-b[k]); if(e>max_rgb_error) max_rgb_error=e;
    }
    double x[2],y[2]; xy(a,x);xy(b,y);
    double d=hypot(x[0]-y[0],x[1]-y[1]);
    if (!isfinite(d) || d>.003) ++failures;
    if(d>max_dxy) max_dxy=d;
    ++cards;
}
int main(void) {
    G=calloc(1,1<<24); if(!G) return 2;
    M32(0xA99BBC)=M32(GAMEFLOW_STATE)=6;
    M32(0xAB0ABC)=0x3000;M32(0x3000)=0x4000;
    M32(0x4000+94*4)=94;M32(0x4000+109*4)=109;
    uint32_t tod=0x200000, ref=0x600000;
    M32(0xB77F34)=tod;
    carbon_dn_on();
    carbon_dn_clock.ready=1;carbon_dn_clock.object=tod;
    carbon_dn_write(SUN_SCALE,1);
    const char *choice=getenv("NFS_LIGHT_DATA");
    int data=choice && !strcmp(choice,"pc") ? 0 : 1;
    /* Retail MW: the reference is the authored record, as MW Original setters upload it. */
    const char *profile=getenv("NFS_WORLD_LIGHTING");
    int retail_mw=profile && !strcmp(profile,"original");
    for (int quartet=0;quartet<2;++quartet) {
        M32(0xA65394)=quartet==0;
        for(int r=0;r<4;++r) {
            uint32_t layout=0x700000+r*0x80;
            M32(tod+(quartet==0?0xc0:0x100)+16*r+4)=layout;
            for(int f=0;f<3;++f)
                memcpy(G+layout+(f==0?0x10:f==1?0x20:0),records[0][quartet][r][f],16);
        }
        for(int hour=0;hour<2;++hour) for(int weather=0;weather<5;++weather)
        for(int low=0;low<3;++low) {
            float w=.25f*weather, high=.5f*low;
            /* +5 degrees with the reference tilt .5; use the actual shared orbit. */
            double h=hour ? 12+12/acos(-1.0)*acos(sin(5*acos(-1.0)/180)/cos(.5)) : 12;
            carbon_dn_sample(h,0,.5f,&carbon_dn_clock.sample);
            carbon_dn_clock.weight=fminf(1,fabsf(carbon_dn_clock.sample.sun[2])/DAYNIGHT_SUN_HEIGHT);
            carbon_dn_write(tod+0x140,w);carbon_dn_write(tod+0x144,high);
            float ambient[4]={.19f,.24f,.32f,4}, direct[3]={1,.8f,.3f};
            memcpy(G+tod+0x20,direct,12);memcpy(G+tod+0x30,ambient,16);
            memcpy(G+tod+0x160,carbon_dn_clock.sample.light,12);
            unsigned char saved[0x180];memcpy(saved,G+tod,sizeof saved);
            Cpu c={0};c.ecx=tod;c.esp=0x9000;
            carbon_daynight_blend(&c,native);
            if(memcmp(saved,G+tod,sizeof saved)) return 2;
            DaynightRecord expected={0}, night;
            float *fields[]={expected.diffuse,expected.ambient,expected.specular};
            for(int f=0;f<3;++f) for(int k=0;k<3;++k) {
                const float (*r)[3][4]=records[data][quartet];
                float a=r[0][f][k]+w*(r[2][f][k]-r[0][f][k]);
                float b=r[1][f][k]+w*(r[3][f][k]-r[1][f][k]);
                fields[f][k]=b+high*(a-b);
            }
            expected.ambient[3]=4;
            daynight_night_record(&night);
            daynight_mix(&expected,&night,carbon_dn_clock.sample.night);
            for(int k=0;k<3;++k)expected.diffuse[k]*=carbon_dn_clock.weight;
            memcpy(G+ref+0x20,expected.diffuse,12);memcpy(G+ref+0x30,expected.ambient,16);
            memcpy(G+ref+0x180,carbon_dn_clock.sample.light,12);
            float D[3],A[3];neutral_sun(ref,D);ambient_rgb(ref,A);
            if(retail_mw) for(int k=0;k<3;++k){D[k]=expected.diffuse[k];A[k]=expected.ambient[k];}
            carbon_dn_constants(&c);
            card(vs[241],D,.18f);card(vs[242],A,.18f); /* world + normal map */
            card(vs[241],D,.09f);card(vs[242],A,.09f); /* glass */
            c.ecx=0x8000;M32(0x8004)=1;
            M32(c.esp+16)=0x8100;M32(0x811c)=0x8200;M32(0x8230)=0x10001;
            carbon_reflect_draw(&c,native);
            card(ps[22],D,.18f*2);
            float roadA[3];for(int k=0;k<3;++k)roadA[k]=ps[21][k]/expected.ambient[3];
            card(roadA,A,.18f*2*.27f*expected.ambient[3]);
            M32(0x8004)=25;M32(0x8230)=0x50019;
            carbon_facade_draw(&c,native);
            float facadeA[3];for(int k=0;k<3;++k)facadeA[k]=vs[243][k]/(2*expected.ambient[3]);
            card(facadeA,A,.18f*2*expected.ambient[3]);
            M32(0x8004)=0;M32(0x8230)=0x60000;
            /* Capture before the draw resets the tree constants. */
            carbon_tree_draw(&c,tree_capture);
            float treeD[3],treeA[3];for(int k=0;k<3;++k){treeD[k]=tree_vs[0][k]/(2*1.2f)*carbon_dn_clock.weight;treeA[k]=tree_vs[1][k]/(2*.13f*expected.ambient[3]);}
            card(treeD,D,.18f*2*1.2f);card(treeA,A,.18f*2*.13f*expected.ambient[3]);
            if(hour && weather==0 && low==2 && quartet==0) {
                float frozen[3]={.532102f,.476753f,.452102f};
                double a[2],b[2];xy(frozen,a);xy(D,b);control_dxy=hypot(a[0]-b[0],a[1]-b[1]);
            }
        }
    }
    printf("%s CARDS data=%s cards=%u max_dxy=%.9g max_rgb_error=%.9g frozen_noon_dxy=%.9g failures=%u\n",retail_mw?"RETAIL-MW":"NEUTRAL",data?"x360":"pc",cards,max_dxy,max_rgb_error,control_dxy,failures);
    free(G);
    return failures || !(control_dxy>.003) || max_rgb_error>2e-6 ? 1 : 0;
}
'''


def colour_fixture(out):
    import struct
    from recomp import EXE
    from private_render import body
    attributes = Path(EXE).parent/'GLOBAL/ATTRIBUTES.BIN'
    raw = attributes.read_bytes()
    # Decode the eight PC collection layouts by key, independently of runtime offsets.
    sys.path.insert(0,str(ROOT/'tools_snapshot/vaults'))
    from vaultlib import Vault, read_vpak
    quartets=((0x3dcfa673,0xb902cfad,0x59c373c3,0xd835d0c8),
              (0xa01a3942,0x0e1c797c,0x94abdff0,0x919b6689))
    found={}
    for name,binary,vlt,bo,vo in read_vpak(attributes):
        vault=Vault(name,binary,vlt,'<',bo,vo)
        for key,kind,size,offset in vault.exports:
            if kind!=0x8e112eb7 or vault.u32(vlt,offset+4)!=0x399ed882:continue
            key=vault.u32(vlt,offset)
            dep,layout=vault.deref(0,offset+0x1c)
            found[key]=[list(struct.unpack_from('<4f',vault.bufs[dep],layout+field))
                        for field in (0x10,0x20,0)]
    pc=[[found[key] for key in quartet] for quartet in quartets]
    import copy
    selected = copy.deepcopy(pc)
    keys = (0x3dcfa673,0xb902cfad,0x59c373c3,0xd835d0c8)
    table = ROOT/'runtime/gen/vaults/attrib_field_diffs.tsv'
    lines = [line.split('\t') for line in table.read_text().splitlines()]
    for vals in lines[1:]:
        row=dict(zip(lines[0],vals))
        if row['class'].lower()!='0x399ed882' or int(row['collection'],16) not in keys:continue
        field=int(row['field_hash'],16)
        if field not in (0x7623feb2,0x52194d72,0x5855b1e7):continue
        f=(0x7623feb2,0x52194d72,0x5855b1e7).index(field)
        r=keys.index(int(row['collection'],16))
        selected[0][r][f]=list(map(float,row['x360_value'].split(',')))
    def literal(v):
        if isinstance(v,list):return '{'+','.join(literal(x) for x in v)+'}'
        return float.hex(v)+'f'
    (out/'colour_records.inc').write_text('static const float records[2][2][4][3][4]='+literal([pc,selected])+';\n')
    mw=(ROOT/'runtime/lighting.c').read_text()
    def mw_body(name):
        start=mw.index('static int neutral_sun' if name=='neutral_sun' else 'static void '+name)
        return body(mw[start:mw.index('\n}\n',start)+3],name)
    reference='static void sun_white(float elevation,float out[3])'+mw_body('sun_white')
    reference+='\nstatic int neutral_sun(uint32_t tod,float out[3])'+mw_body('neutral_sun')
    reference+='\nstatic void ambient_rgb(uint32_t tod,float out[3])'+mw_body('ambient_rgb')
    (out/'mw_reference.inc').write_text(reference)
    source=(HERE/'private_runtime/carbon_daynight.h').read_text()
    harness=COLOUR_HARNESS.replace('static void native(Cpu *c)',
        'static float tree_vs[2][4];\nstatic void tree_capture(Cpu*c){memcpy(tree_vs,vs[250],sizeof tree_vs);}\nstatic void native(Cpu *c)')
    (out/'colour.c').write_text(harness)
    controls={'good':source,'frozen-noon':source.replace('record->diffuse[k] = weight>0 ? white[k]*scale/weight : 0;',
        'record->diffuse[k] = (float[]){.532102f,.476753f,.452102f}[k];')}
    for name,text in controls.items():
        assert name=='good' or text!=source
        (out/'native.inc').write_text(text)
        binary=out/('colour-'+name)
        run(['clang','-DNFS_GAME=2','-O1','-g','-w','-fsanitize=address,undefined',
             '-I',ROOT/'runtime','-I',HERE,'-I',out, '-I',HERE/'out/carbon/runtime',
             out/'colour.c',ROOT/'runtime/daynight.c',ROOT/'runtime/daynight_clock.c','-o',binary])
        for data in ('pc','x360'):
            env=dict(os.environ,NFS_DAYNIGHT='on',NFS_LIGHT_DATA=data,NFS_WORLD_LIGHTING='neutral')
            print(name+': '+run([binary],env=env,expected=0 if name=='good' else 1))
            if name=='good':
                env['NFS_WORLD_LIGHTING']='original'
                print('retail-mw: '+run([binary],env=env))
    # Retail MW broken control: the old blend, Neutral at every profile.
    always=source.replace('if (!carbon_dn_retail_mw()) carbon_dn_neutral(record);','carbon_dn_neutral(record);')
    assert always!=source
    (out/'native.inc').write_text(always)
    binary=out/'colour-always-neutral'
    run(['clang','-DNFS_GAME=2','-O1','-g','-w','-fsanitize=address,undefined',
         '-I',ROOT/'runtime','-I',HERE,'-I',out, '-I',HERE/'out/carbon/runtime',
         out/'colour.c',ROOT/'runtime/daynight.c',ROOT/'runtime/daynight_clock.c','-o',binary])
    for data in ('pc','x360'):
        env=dict(os.environ,NFS_DAYNIGHT='on',NFS_LIGHT_DATA=data,NFS_WORLD_LIGHTING='original')
        print('always-neutral retail-mw: '+run([binary],env=env,expected=1))
    (out/'native.inc').write_text(source)

def main(effects=HERE/'out/carbon/effects'):
    corpus = [next(iter(effects.glob('*'+name+'*.bin')), None) for name in
              ('IDI_WORLD_FX_', 'IDI_WORLDNORMALMAP_FX_', 'IDI_WORLDREFLECT_FX_')]
    if any(p is None for p in corpus) or not (ROOT/'host/shaders/build/libsmtranslate.a').exists():
        print('SKIP: private world effect corpus / translator absent'); return 3
    from recomp import EXE
    if not (Path(EXE).parent/'GLOBAL/ATTRIBUTES.BIN').is_file() or not (ROOT/'runtime/gen/vaults/attrib_field_diffs.tsv').is_file():
        print('SKIP: reference lighting source bytes absent'); return 3
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
        colour_fixture(out)
    (out/"proof.txt").write_text(capture.getvalue())
    print(capture.getvalue(), end="")
    print('PRIVATE DAYNIGHT PASS')
    return 0


if __name__ == '__main__':
    sys.exit(main())
