"""Additive glow coverage: an opaque-alpha glow quad must not protect its black surround.

Reflector and street-lamp glows (SRCALPHA/ONE) carry alpha 1 over the whole quad and draw
their shape in colour. The receiver mask replays each such draw with ZERO/INVSRCALPHA into
an R8 mask cleared to 1 (1 = receiver), so coverage by alpha alone protected the whole quad:
lamp pools and contact shading cut a hard square out of the road around each reflector.
carbon_ao_glow.h patches the translated pixel shader so coverage is saturate(max(rgb)*alpha).

Fixture: 64x64 quad, alpha 1 everywhere, rgb (1,.8,.4) inside a radius-.15 core, black outside.
Fixed: surround protected 0.000, core protected 1.000 (pass: surround <= .01, core >= .95).
Original (unpatched shader = coverage by alpha): surround protected 1.000, rejected (exit 1).
A shader with two colour outputs is left unpatched (coverage by alpha is kept).
Private source absent: exit 3. Autodiscovered by offline_tests.sh.
"""
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
HEADER = ROOT / 'recomp/private_runtime/carbon_ao_glow.h'
RENDER = ROOT / 'runtime/render.m'

MSL = r'''#include <metal_stdlib>
using namespace metal;
struct VOut { float4 pos [[position]]; float2 uv; };
struct SmPSOut { float4 oc[4]; };
struct SmPSStageOut { float4 c0 [[color(0)]]; };
vertex VOut vs_full(uint v [[vertex_id]]) { float2 p = float2((v << 1) & 2, v & 2); return {float4(p * float2(2, -2) + float2(-1, 1), 0, 1), p}; }
fragment SmPSStageOut sm_main(VOut i [[stage_in]]) {
    SmPSOut so;
    float core = distance(i.uv, float2(0.5f)) < 0.15f ? 1.0f : 0.0f;
    so.oc[0] = float4(core * float3(1.0f, 0.8f, 0.4f), 1.0f);
    SmPSStageOut r;
    r.c0 = so.oc[0];
    return r;
}
'''

FIXTURE = r'''#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "carbon_ao_glow.h"
int main(int argc, char **argv) {
    @autoreleasepool {
        int patch = argc > 2 && !strcmp(argv[2], "fixed");
        NSString *base = [NSString stringWithContentsOfFile:@(argv[1]) encoding:NSUTF8StringEncoding error:nil];
        if (!base) return 2;
        char *two = malloc(strlen(base.UTF8String) * 2 + 64);
        sprintf(two, "%s%s", base.UTF8String, "    r.c0 = so.oc[0];\n");
        char *rejected = carbon_ao_glow_shader(two);
        printf("two_outputs_patched=%d\n", rejected != NULL);
        if (rejected) return 1;
        char *patched = patch ? carbon_ao_glow_shader(base.UTF8String) : NULL;
        if (patch && !patched) { printf("patch refused\n"); return 1; }
        id<MTLDevice> dev = MTLCreateSystemDefaultDevice();
        if (!dev) return 3;
        NSError *err = nil;
        id<MTLLibrary> lib = [dev newLibraryWithSource:@(patched ? patched : base.UTF8String) options:nil error:&err];
        if (!lib) { printf("compile: %s\n", err.localizedDescription.UTF8String); return 2; }
        MTLRenderPipelineDescriptor *d = [MTLRenderPipelineDescriptor new];
        d.vertexFunction = [lib newFunctionWithName:@"vs_full"]; d.fragmentFunction = [lib newFunctionWithName:@"sm_main"];
        d.colorAttachments[0].pixelFormat = MTLPixelFormatR8Unorm;
        d.colorAttachments[0].blendingEnabled = YES;   /* the receiver replay: rs[19]=ZERO, rs[20]=INVSRCALPHA */
        d.colorAttachments[0].sourceRGBBlendFactor = d.colorAttachments[0].sourceAlphaBlendFactor = MTLBlendFactorZero;
        d.colorAttachments[0].destinationRGBBlendFactor = d.colorAttachments[0].destinationAlphaBlendFactor = MTLBlendFactorOneMinusSourceAlpha;
        id<MTLRenderPipelineState> pso = [dev newRenderPipelineStateWithDescriptor:d error:&err];
        if (!pso) return 2;
        MTLTextureDescriptor *td = [MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatR8Unorm width:64 height:64 mipmapped:NO];
        td.usage = MTLTextureUsageRenderTarget; td.storageMode = MTLStorageModeShared;
        id<MTLTexture> mask = [dev newTextureWithDescriptor:td];
        id<MTLCommandQueue> q = [dev newCommandQueue]; id<MTLCommandBuffer> cmd = [q commandBuffer];
        MTLRenderPassDescriptor *rp = [MTLRenderPassDescriptor renderPassDescriptor];
        rp.colorAttachments[0].texture = mask; rp.colorAttachments[0].loadAction = MTLLoadActionClear;
        rp.colorAttachments[0].clearColor = MTLClearColorMake(1, 1, 1, 1); rp.colorAttachments[0].storeAction = MTLStoreActionStore;
        id<MTLRenderCommandEncoder> e = [cmd renderCommandEncoderWithDescriptor:rp];
        [e setRenderPipelineState:pso]; [e drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:3]; [e endEncoding];
        [cmd commit]; [cmd waitUntilCompleted];
        uint8_t px[64 * 64]; [mask getBytes:px bytesPerRow:64 fromRegion:MTLRegionMake2D(0, 0, 64, 64) mipmapLevel:0];
        double surround = 0, core = 0; int ns = 0, nc = 0;
        for (int y = 0; y < 64; ++y) for (int x = 0; x < 64; ++x) {
            double u = (x + .5) / 64 - .5, v = (y + .5) / 64 - .5, r = sqrt(u * u + v * v), p = 1 - px[y * 64 + x] / 255.0;
            if (r > .2) { surround += p; ++ns; } else if (r < .1) { core += p; ++nc; }
        }
        surround /= ns; core /= nc;
        printf("surround_protected=%.3f core_protected=%.3f\n", surround, core);
        return surround <= .01 && core >= .95 ? 0 : 1;
    }
}
'''


def main():
    if not HEADER.is_file():
        print('private source absent: skipped')
        return 3
    render = RENDER.read_text()
    # The draw path swaps in the glow variant only for additive draws recorded by their own alpha.
    assert 'e->variant == MAT_VARIANT_AO_GLOW ? carbon_ao_glow_shader(e->refl.msl) :' in render
    assert 'if(ssao_replay_dst==6 && !pse->mat' in render and 'get_shader_variant(ps,&po,MAT_VARIANT_AO_GLOW)' in render
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        (tmp / 'glow.metal').write_text(MSL)
        (tmp / 'fixture.m').write_text(FIXTURE)
        build = subprocess.run(['clang', '-O1', '-w', '-fobjc-arc', '-I', str(HEADER.parent), str(tmp / 'fixture.m'),
                                '-framework', 'Foundation', '-framework', 'Metal', '-o', str(tmp / 'fixture')],
                               capture_output=True, text=True)
        if build.returncode:
            print(build.stderr)
            return 1
        results = {}
        for label in ('fixed', 'original'):
            run = subprocess.run([str(tmp / 'fixture'), str(tmp / 'glow.metal'), label], capture_output=True, text=True)
            if run.returncode == 3:
                print('no Metal device: skipped')
                return 3
            print(label, run.stdout.strip().replace('\n', ' '))
            results[label] = run.returncode
        if results['fixed'] != 0:
            print('FAIL: the fixed coverage protects the glow surround or drops the core')
            return 1
        if results['original'] != 1:
            print('FAIL: the original coverage-by-alpha control was not rejected')
            return 1
    print('PASS')
    return 0


if __name__ == '__main__':
    sys.exit(main())
