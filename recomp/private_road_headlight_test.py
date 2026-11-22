"""Road local/world mismatch, using the retail reflective-road shader corpus.

Captured midnight ROI: broken distance 8189.321..8190.367 m, attenuation 0;
world position 1.955..3.400 m, attenuation .971273...983430 (> .96).
The same <4 m / >.96 check rejects native tokens and a disabled-transform
mutation. Identity draws preserve every output bit; shifted draws preserve
every output except position XYZ and, for SM3, eye XYZ. Both SM2/SM3, optional daylight On/Off,
native SetWorld ABI, matrix transpose, exact converted-material classification
and stale-constant refresh are exercised. Native nonidentity props stay retail.
Coast world-position error 0 m (limit 0.001); old origin guard 5343.14 m.
Rockport SM3 eye-vector error 0 m (limit < 0.001 m); old patch 5343.138 m.
Stock identity SM3 eye-vector error 0 m.
Metal runs the production translated bytecode, including bitwise native/patched
output comparison for every vertex in a captured Palmont road draw (51 used
vertices, 20 triangles). Missing corpus: exit 3.
"""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import struct
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
from build_private import ignored_output
from private_render import body

SHADER = r'''
#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#include "sm_translate.h"
#include "tests/sm_interp.h"
#include <cmath>
#include <cstdio>
#include <vector>
#include <cstring>
#define CARBON_ROAD_SHADER_ONLY
#include "road.inc"
#include "carbon_daynight_shader.h"
struct ShaderEntry { uint32_t *tokens, ntokens; };
static bool day_active;
uint32_t *carbon_daynight_shader(const uint32_t *t,uint32_t n,uint32_t *out) {
    return day_active ? carbon_dn_shader_variant(t,n,out) : nullptr;
}
uint32_t *carbon_coat_shader(const uint32_t *,uint32_t,uint32_t *) { return nullptr; }
static uint32_t *submitted; static uint32_t submitted_count;
static void compile_entry(ShaderEntry *e) {
    submitted=(uint32_t *)malloc(e->ntokens*4); memcpy(submitted,e->tokens,e->ntokens*4);
    submitted_count=e->ntokens;
}
static void shader_submit(ShaderEntry *e)
#include "submit.inc"
#define CHECK(x) do { ++checks; if (!(x)) {fprintf(stderr,"FAIL line %d\n",__LINE__);return 1;} } while(0)
int main(int argc,char **argv) { @autoreleasepool {
    unsigned checks=0,programs=0,gpu_checks=0;
    bool gpu=!getenv("CODEX_SANDBOX") || getenv("NFS_GPU_SANDBOX");
    id<MTLDevice> device=gpu?MTLCreateSystemDefaultDevice():nil;
    CHECK(!gpu || device); id<MTLCommandQueue> queue=[device newCommandQueue];
    const float points[][4]={{1778.91638f,2499.70721f,147.8478f,1},
        {1778.99792f,2501.44489f,147.83517f,1},{1778.46236f,2502.80889f,147.81742f,1}};
    /* Every vertex used by the captured native section-220 road draw. */
    FILE *vf=fopen(argv[1],"rb");CHECK(vf);fseek(vf,0,SEEK_END);size_t vsz=ftell(vf);rewind(vf);
    CHECK(vsz && vsz%sizeof(interp::VSIn)==0);
    std::vector<interp::VSIn> palmont(vsz/sizeof(interp::VSIn));CHECK(fread(palmont.data(),1,vsz,vf)==vsz);fclose(vf);
    float max_distance=0,min_attenuation=1,broken_distance=0;
    double rockport_eye_error=0,stock_eye_error=0,other_eye_error=0;
    for(int a=2;a<argc;++a) {
        FILE *f=fopen(argv[a],"rb");CHECK(f);fseek(f,0,SEEK_END);size_t bytes=ftell(f);rewind(f);
        std::vector<uint32_t> blob((bytes+3)/4);CHECK(fread(blob.data(),1,bytes,f)==bytes);fclose(f);
        for(size_t k=0;k<bytes/4;++k) {
            if(blob[k]!=0xfffe0200u && blob[k]!=0xfffe0300u)continue;
            uint32_t n=(uint32_t)sm_token_count(blob.data()+k,bytes/4-k);if(!n)continue;
            uint32_t *t=blob.data()+k;++programs;
            const bool sm3=t[0]==0xfffe0300u;
            unsigned output=3; /* TEXCOORD3 semantic in both versions. */
            const unsigned eye_output=5; /* SM3 o8 carries TEXCOORD5. */
            for(bool day:{false,true}) {
                day_active=day; ShaderEntry e={t,n};shader_submit(&e);
                CHECK(e.tokens==t && e.ntokens==n);
                uint32_t baseline_count=n;
                uint32_t *base=day?carbon_dn_shader_variant(t,n,&baseline_count):nullptr;
                sm::Shader before,after;CHECK(sm::parse(base?base:t,baseline_count,before));
                CHECK(sm::parse(submitted,submitted_count,after));
                SmOptions options;sm_default_options(&options);options.emit_test_kernel=1;
                SmResult result={};CHECK(!sm_translate(submitted,submitted_count,&options,&result));
                CHECK(result.float_max==248);
                id<MTLComputePipelineState> pipeline=nil, native_pipeline=nil;
                if(gpu) {
                    NSError *error=nil;MTLCompileOptions *co=[MTLCompileOptions new];co.mathMode=MTLMathModeRelaxed;
                    id<MTLLibrary> lib=[device newLibraryWithSource:[NSString stringWithUTF8String:result.msl] options:co error:&error];
                    pipeline=[device newComputePipelineStateWithFunction:[lib newFunctionWithName:@"sm_test_kernel"] error:&error];
                    if(!pipeline)fprintf(stderr,"%s\n",error.localizedDescription.UTF8String);CHECK(pipeline);
                    SmResult native={};CHECK(!sm_translate(base?base:t,baseline_count,&options,&native));
                    lib=[device newLibraryWithSource:[NSString stringWithUTF8String:native.msl] options:co error:&error];
                    native_pipeline=[device newComputePipelineStateWithFunction:[lib newFunctionWithName:@"sm_test_kernel"] error:&error];
                    CHECK(native_pipeline);sm_result_free(&native);
                }
                for(int mode:{0,1,2,3,4}) for(size_t point=0;point<(mode?3:palmont.size());++point) {
                    const float *p=mode?points[point]:palmont[point].v[0].data();
                    float c[256][4]={};int ci[16][4]={},cb[16]={};
                    for(int j=0;j<4;++j)c[j][j]=1;
                    c[4][0]=5000;c[4][1]=.0002;c[4][2]=1;c[5][0]=1;
                    c[6][0]=1779.3;c[6][1]=2507.71;c[6][2]=149.575;
                    c[240][2]=1;c[241][0]=.025;c[241][1]=.035;c[241][2]=.055;c[241][3]=1;
                    for(int j=0;j<3;++j)c[244+j][j]=1;
                    c[244][3]=mode?8192:0;c[247][3]=mode?1:0;
                    if(mode==3) { c[244][3]=-1728;c[245][3]=-5056; }
                    if(mode==4) { c[244][3]=2734.4375f;c[245][3]=-1824.75f;c[246][3]=30.25f; }
                    if(mode==2) { /* nontranslation matrix proves column packing */
                        c[244][0]=0;c[244][1]=-1;c[245][0]=1;c[245][1]=0;c[245][3]=50;
                    }
                    interp::Context ctx;ctx.c=&c[0][0];ctx.ci=&ci[0][0];ctx.cb=cb;ctx.opt=options;
                    interp::VSIn in={};for(auto &v:in.v)v={.2f,.3f,.4f,1};
                    memcpy(in.v[0].data(),p,16);in.v[1]={0,0,1,0};
                    if(mode==0) {
                        in=palmont[point];
                        const float wvp[4][4]={{-.739212f,-.912182f,.000434141f,6866.64f},
                            {.0250835f,-.0195227f,1.69008f,-254.448f},
                            {.776818f,-.629524f,-.0188011f,-2254.98f},
                            {.776779f,-.629493f,-.0188002f,-2254.37f}};
                        memcpy(c,wvp,sizeof wvp);c[4][0]=100;c[4][1]=.01;c[4][2]=.26;c[4][3]=2;
                        c[6][0]=5435.54;c[6][1]=3122.92;c[6][2]=105.956;
                    }
                    interp::VSOut old={},now={};CHECK(interp::run_vs(before,ctx,in,old));CHECK(interp::run_vs(after,ctx,in,now));
                    auto position=now.tex[output];now.tex[output]=old.tex[output];
                    auto eye=now.tex[eye_output];
                    if(mode && sm3)
                        for(int j=0;j<3;++j)now.tex[eye_output][j]=old.tex[eye_output][j];
                    CHECK(!memcmp(&now,&old,sizeof now));
                    if(mode==1) {
                        float d=0,b=0;const float h[]={9968.37f,2501.93f,148.216f};
                        for(int j=0;j<3;++j){d+=powf(position[j]-h[j],2);b+=powf(old.tex[output][j]-h[j],2);}
                        d=sqrtf(d);b=sqrtf(b);float attenuation=powf(fmaxf(0,1-d/235),2);
                        max_distance=fmaxf(max_distance,d);min_attenuation=fminf(min_attenuation,attenuation);broken_distance=b;
                        if(!(d<4 && attenuation>.96f)) fprintf(stderr,"ROAD REJECT distance=%.6f attenuation=%.9f\n",d,attenuation);
                        CHECK(d<4 && attenuation>.96f);CHECK(b>8189 && powf(fmaxf(0,1-b/235),2)==0);
                    }
                    for(int j=0;j<3;++j) {
                        float expected=0;for(int h=0;h<4;++h)expected+=in.v[0][h]*c[244+j][h];
                        CHECK(fabsf(position[j]-expected)<=.001f);
                    }
                    if(sm3) {
                        double error_squared=0;
                        for(int j=0;j<3;++j) {
                            const float *column=c[244+j];
                            double world_eye=column[3],world_position=0;
                            for(int h=0;h<3;++h)world_eye+=(double)c[6][h]*column[h];
                            for(int h=0;h<4;++h)world_position+=(double)in.v[0][h]*column[h];
                            const double error=((double)eye[j]-position[j])-(world_eye-world_position);
                            error_squared+=error*error;
                        }
                        const double error=sqrt(error_squared);
                        if(mode==3)rockport_eye_error=fmax(rockport_eye_error,error);
                        else if(mode==0)stock_eye_error=fmax(stock_eye_error,error);
                        else other_eye_error=fmax(other_eye_error,error);
                    }
                    if(gpu) {
                        SmPSAux aux={};id<MTLBuffer> input=[device newBufferWithBytes:&in length:sizeof in options:MTLResourceStorageModeShared];
                        id<MTLBuffer> out=[device newBufferWithLength:13*16 options:MTLResourceStorageModeShared];
                        id<MTLCommandBuffer> cmd=[queue commandBuffer];id<MTLComputeCommandEncoder> enc=[cmd computeCommandEncoder];
                        [enc setComputePipelineState:pipeline];[enc setBuffer:input offset:0 atIndex:0];[enc setBuffer:out offset:0 atIndex:1];
                        [enc setBytes:c length:sizeof c atIndex:2];[enc setBytes:ci length:sizeof ci atIndex:3];
                        [enc setBytes:cb length:sizeof cb atIndex:4];[enc setBytes:&aux length:sizeof aux atIndex:5];
                        [enc dispatchThreads:MTLSizeMake(1,1,1) threadsPerThreadgroup:MTLSizeMake(1,1,1)];[enc endEncoding];[cmd commit];[cmd waitUntilCompleted];CHECK(!cmd.error);
                        float *values=(float *)out.contents;
                        for(int j=0;j<4;++j){CHECK(fabsf(values[12+output*4+j]-position[j])<=.001f);++gpu_checks;}
                        if(sm3)for(int j=0;j<3;++j) {
                            CHECK(fabsf(values[12+eye_output*4+j]-eye[j])<=.001f);++gpu_checks;
                        }
                        if(mode==0) {
                            float patched_values[52];memcpy(patched_values,values,sizeof patched_values);
                            cmd=[queue commandBuffer];enc=[cmd computeCommandEncoder];
                            [enc setComputePipelineState:native_pipeline];[enc setBuffer:input offset:0 atIndex:0];[enc setBuffer:out offset:0 atIndex:1];
                            [enc setBytes:c length:sizeof c atIndex:2];[enc setBytes:ci length:sizeof ci atIndex:3];
                            [enc setBytes:cb length:sizeof cb atIndex:4];[enc setBytes:&aux length:sizeof aux atIndex:5];
                            [enc dispatchThreads:MTLSizeMake(1,1,1) threadsPerThreadgroup:MTLSizeMake(1,1,1)];[enc endEncoding];[cmd commit];[cmd waitUntilCompleted];CHECK(!cmd.error);
                            CHECK(!memcmp(patched_values,out.contents,sizeof patched_values));
                        }
                    }
                }
                sm_result_free(&result);free(base);free(submitted);
            }
            uint32_t untouched=17;std::vector<uint32_t> wrong(t,t+n);wrong[0]^=1;
            CHECK(!carbon_road_headlight_shader(wrong.data(),n,wrong.data(),n,&untouched) && untouched==17);
            k+=n-1;
        }
    }
    CHECK(programs==5);
    printf("ROAD EYE Rockport error=%.6f m; stock identity error=%.6f m\n",rockport_eye_error,stock_eye_error);
    CHECK(rockport_eye_error<.001 && stock_eye_error==0 && other_eye_error<.001);
    printf("ROAD SHADERS programs=%u checks=%u GPU=%u distance=%.6f attenuation=%.9f broken_distance=%.6f broken_attenuation=0\n",programs,checks,gpu_checks,max_distance,min_attenuation,broken_distance);
    if(gpu) printf("PALMONT GPU: %zu used vertices / 20 triangles, native/patched outputs bit-identical, both shader versions and daylight states\n",palmont.size());
    return 0;
} }
'''

NATIVE = r'''
#include "host.h"
#include <assert.h>
#include <math.h>
#include <stdio.h>
#include "road.inc"
uint8_t *G;
static float expected[4][4], uploaded[4][4];
static unsigned calls, originals, draws;
static uint32_t stack;
static int tagged;
#define CARBON_WORLDREFLECT 0
static float carbon_compat_day(void) { return 0; }
static struct { float weight; } carbon_dn_clock = {1};
static float carbon_dn_float(uint32_t a) { float f; memcpy(&f,G+a,4); return f; }
uint32_t call_guest(Cpu *c,uint32_t fn,int n,const uint32_t *args) {
    assert(n==4 && args[0]==0x2000);
    if(fn==0xf100005e && args[1]==244) {
        assert(originals==calls+1 && args[3]==4);
        assert(!memcmp(G+args[2],expected,sizeof expected));
        assert(c->esp==stack+16-sizeof expected);
        memcpy(uploaded,G+args[2],sizeof uploaded);++calls;
    } else if(fn==0xf100005e && args[1]==247) {
        assert(args[3]==1);memcpy(uploaded[3],G+args[2],16);
    } else assert(fn==0xf100006d && args[1]==31 && args[3]==1);
    c->eax=0xbad;c->esp=0;return 0;
}
static void original(Cpu *c) { assert(c->esp==stack);++originals;c->esp+=16;c->eax=0x12345678; }
static void draw_original(Cpu *c) { ++draws;c->esp+=20;c->eax=0x23456789; }
/* DRAW_FIXTURE */
int main(void) {
    G=calloc(1,1<<25);assert(G);M32(0xab0abc)=0x2000;M32(0x2000)=0x3000;
    M32(0x3000+94*4)=0xf100005e;M32(0x3000+109*4)=0xf100006d;M32(0x6004)=1;
    const float worlds[][16]={{1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1},
        {1,0,0,0,0,1,0,0,0,0,1,0,8192,0,0,1},
        {0,1,0,0,-1,0,0,0,0,0,1,0,8192,50,0,1},
        {1,0,0,0,0,1,0,0,0,0,1,0,1024,0,0,1},
        {1,0,0,0,0,1,0,0,0,0,1,0,8192,1,0,1},
        {1,0,0,0,0,1,0,0,0,0,1,0,-1728,-5056,0,1},
        {1,0,0,0,0,1,0,0,0,0,1,0,2734.4375,-1824.75,30.25,1}};
    const unsigned materials[]={0x10001,1,0x10001,0x20001,1};
    float maximum=0,broken=0;
    for(unsigned k=0;k<sizeof worlds/sizeof *worlds;++k) {
        const float *w=worlds[k];memset(expected,0,sizeof expected);
        for(int r=0;r<4;++r)for(int col=0;col<3;++col)expected[col][r]=w[4*r+col];
        Cpu c={0};stack=c.esp=0x100000;M32(c.esp+4)=0x4000;memcpy(G+0x4000,w,64);
        carbon_road_headlight_world(&c,original);assert(c.eax==0x12345678 && c.esp==stack+16);
        assert(uploaded[3][3]==0);
        for(unsigned m=0;m<sizeof materials/sizeof *materials;++m) {
            tagged=materials[m]==0x10001;
            c.esp=stack;c.ecx=0x6000;M32(c.esp+16)=0x7000;M32(0x701c)=0x8000;M32(0x8030)=materials[m];
            assert(carbon_reflect_draw(&c,draw_original));
            assert(c.eax==0x23456789 && c.esp==stack+20 && c.ecx==0x6000);
            const float local[]={13,-7,2.5,1};float error=0;
            for(unsigned j=0;j<3;++j) {
                float world=0;for(unsigned h=0;h<4;++h)world+=local[h]*expected[j][h];
                float actual=uploaded[3][3]>uploaded[3][2]?world:local[j];
                float wanted=tagged?world:local[j];error+=(actual-wanted)*(actual-wanted);
            }
            maximum=fmaxf(maximum,sqrtf(error));
            if(k==5 && tagged) {
                /* The old origin-only selector rejects this coast matrix. */
                broken=hypotf(w[12],w[13]);
            }
        }
    }
    printf("ROAD COAST world-position error=%.6f m; origin-guard control=%.6f m; worlds=7 draws=%u\n",maximum,broken,draws);
    assert(broken>5343 && broken<5344);
    if(maximum>.001f)return 1;
    assert(calls==7 && originals==7 && draws==35);
    puts("ROAD NATIVE PASS tagged coast/deck/rotation; native materials reset; stale-selector and ABI checks pass");
    free(G);return 0;
}
'''



def run(args, expected=0):
    p = subprocess.run(list(map(str, args)), capture_output=True, text=True, timeout=180)
    if p.returncode != expected:
        raise RuntimeError(f'exit {p.returncode}, expected {expected}: {p.stdout[-2000:]} {p.stderr[-2000:]}')
    return (p.stdout + p.stderr).strip()


def palmont_fixture(out, carbon):
    """Read the actual native draw, without copying asset arrays into source."""
    if carbon is None:
        image = json.loads((HERE/'out/carbon/image.json').read_text())
        carbon = Path(image['exe']).parent
    tracks = carbon/'TRACKS'
    sys.path.insert(0, str(ROOT/'tools_snapshot/worldmerge'))
    from formats import TrackIndex, chunks, FormatError
    from convert import aligned_payload
    index = TrackIndex((tracks/'L5RA.BUN').read_bytes())
    section = next(s for s in index.sections if s.number == 220)
    with (tracks/'STREAML5RA.BUN').open('rb') as stream:
        stream.seek(section.offset)
        data = stream.read(section.size)

    def walk(data, base=0):
        try: parts = chunks(data, base)
        except FormatError: return
        for part in parts:
            if part.kind == 0x80134100:
                mesh = chunks(part.payload, part.offset+8)
                for item in mesh:
                    if item.kind != 0x134b01: continue
                    vertices = aligned_payload(item)
                    if len(vertices) != 917*52: continue
                    first = struct.unpack_from('<3f', vertices)
                    if not (5390 < first[0] < 5450 and 3030 < first[1] < 3120): continue
                    indices = aligned_payload(next(p for p in mesh if p.kind == 0x134b03))
                    # Captured draw: 20 triangles at first index 543, full group 917.
                    used = sorted(set(struct.unpack_from('<60H', indices, 543*2)))
                    assert max(used) < 917
                    inputs = bytearray()
                    for i in used:
                        vertex = vertices[i*52:(i+1)*52]
                        attrs = [[0., 0., 0., 0.] for _ in range(16)]
                        attrs[0] = [*struct.unpack_from('<3f', vertex), 1.]
                        attrs[1] = [*struct.unpack_from('<3f', vertex, 12), 1.]
                        b, g, r, a = vertex[24:28]
                        attrs[2] = [r/255, g/255, b/255, a/255]
                        attrs[3] = [*struct.unpack_from('<2f', vertex, 28), 0., 1.]
                        attrs[4] = list(struct.unpack_from('<4f', vertex, 36))
                        inputs.extend(struct.pack('<64f', *(v for attr in attrs for v in attr)))
                    yield inputs
            elif part.kind >> 31:
                yield from walk(part.payload, part.offset+8)

    candidates = list(walk(data))
    assert len(candidates) == 1, 'native road draw identity must be unique'
    path = out/'palmont-inputs.bin'
    path.write_bytes(candidates[0])
    return path


def main(effects=HERE/'out/carbon/effects', carbon=None):
    corpus = list(effects.glob('*IDI_WORLDREFLECT_FX_*.bin'))
    library = ROOT/'host/shaders/build/libsmtranslate.a'
    if not corpus or not library.exists():
        print('SKIP: private road corpus / translator absent'); return 3
    private = HERE/'private_runtime'
    manifest = json.loads((private/'features/road_headlight.json').read_text())
    assert manifest['bindings']['carbon_road_headlight.c']['sha256'] == hashlib.sha256((private/'carbon_road_headlight.h').read_bytes()).hexdigest()
    hook = json.loads((private/'hooks/road_headlight.json').read_text())['hooks'][0]
    assert hook['address'] == '0071E660' and hook['provider'] == 'carbon_road_headlight_world'
    out = ignored_output(HERE/'out/carbon/road_headlight_check')
    try: palmont = palmont_fixture(out, carbon)
    except FileNotFoundError:
        print('SKIP: native Palmont road input absent'); return 3
    (out/'shader.mm').write_text(SHADER)
    draw_source = (private/'carbon_daynight.h').read_text()
    native = NATIVE.replace('/* DRAW_FIXTURE */', 'static int carbon_reflect_draw(Cpu *c,void (*original)(Cpu *))'+body(draw_source,'carbon_reflect_draw'))
    (out/'native.c').write_text(native)
    (out/'submit.inc').write_bytes((private/'game_compat_shader_submit.h').read_bytes())
    (out/'carbon_daynight_shader.h').write_bytes((private/'carbon_daynight_shader.h').read_bytes())
    source = (private/'carbon_road_headlight.h').read_text()
    controls = {
        'good': source,
        'disabled-transform': source.replace('0x02010029u', '0x02040029u'),
        'old-eye': source.replace('sm3 ? sizeof eye : 0', '0'),
    }
    assert all(text != source for name, text in controls.items() if name != 'good')
    proof = []
    for name, text in controls.items():
        (out/'road.inc').write_text(text)
        binary = out/name
        run(['clang++', '-std=c++17', '-O1', '-fobjc-arc', '-I', ROOT/'host/shaders', out/'shader.mm',
             ROOT/'host/shaders/tests/sm_interp.cpp', library, '-framework', 'Foundation', '-framework', 'Metal', '-o', binary])
        result = run([binary, palmont, *corpus], expected=0 if name=='good' else 1)
        if name == 'old-eye':
            assert 'ROAD EYE Rockport error=5343.137' in result and 'stock identity error=0.000000 m' in result
        proof.append(name+': '+result)
    (out/'road.inc').write_text(source)
    run(['clang', '-O1', '-g', '-fsanitize=address,undefined', '-I', ROOT/'runtime', '-I', HERE,
         out/'native.c', '-o', out/'native'])
    for day in (None, 'on'):
        old = os.environ.pop('NFS_DAYNIGHT', None)
        if day: os.environ['NFS_DAYNIGHT'] = day
        try: proof.append('daynight='+str(day)+': '+run([out/'native']))
        finally:
            os.environ.pop('NFS_DAYNIGHT', None)
            if old is not None: os.environ['NFS_DAYNIGHT'] = old
    broken = native.replace('M32(mesh+0x30)==0x00010001u ? 1.f : 0.f', '0.f')
    assert broken != native
    (out/'native-broken.c').write_text(broken)
    run(['clang', '-O1', '-I', ROOT/'runtime', '-I', HERE, out/'native-broken.c', '-o', out/'native-broken'])
    proof.append('material-selector-disabled: '+run([out/'native-broken'], expected=1))
    (out/'proof.txt').write_text('\n'.join(proof)+'\n')
    print('\n'.join(proof)); return 0


if __name__ == '__main__':
    sys.exit(main())
