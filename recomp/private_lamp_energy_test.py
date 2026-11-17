"""Lamp energy on the two lamp sprite programs (NFS_CARBON_REFLECT_HDR, on by default).

Production bytecode of particles flares and streak_flares, original and patched,
run in the translator's interpreter with a white texture and vertex colour
(s, s/2, s/4, 1) for s = 1 / .9 / .5:
  patched, c30.x = 1 - 1/64: largest channel times alpha m -> rgb / (1 - c30.x m),
           expected from the original program's own output; both give
           64.00 / 7.89 / 0.98, alpha unchanged; limit 0.1 %, 24 checks, 0 failures;
  patched, c30.x = 0: bit-identical to the original (6 checks);
  control (the unpatched tokens against the same limit): 1.00 / 0.90 / 0.50,
           18 failures, exit 1.
Also: a changed byte declines; the switch at 0 declines both programs; unset keeps them on.
Live: HDR and lacquer take 24 transitions total across two starting states
and two programs. 72 output/alpha/cache checks, zero failures; restored entries and
RGBA are exact. Old lookup identity: 16 failures, exit 1 vs good 0.
Private executable or translator absent: exit 3; no game is launched.
"""
from pathlib import Path
import json
import os
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
from build_private import ignored_output
from private_coat_test import HARNESS as COAT_HARNESS

HARNESS = r'''
#include "sm_translate.h"
#include "tests/sm_interp.h"
#include <cmath>
#include <cstdio>
#include <cstring>
#include <map>
#include <vector>
#include "coat.inc"
LOOKUP_SUPPORT
static const uint64_t keys[2] = {0xb53b3a3b390249b4ull, 0x89aa56e4826ec0d2ull};
static const char *const names[2] = {"flares", "streak_flares"};
struct Program { std::vector<uint32_t> tokens; sm::Shader shader; };
static uint64_t key_of(const uint32_t *tokens, size_t count) {
    uint64_t key = 1469598103934665603ull;
    const unsigned char *bytes = (const unsigned char *)tokens;
    for (size_t k = 0; k < count * 4; ++k) key = (key ^ bytes[k]) * 1099511628211ull;
    return key;
}
static bool shade(const Program &ps, float s, float energy, float out[4]) {
    float pc[256][4] = {}; int integers[16][4] = {}, booleans[16] = {};
    pc[0][0] = 1;                                                        /* cvBaseAlphaRef */
    pc[30][0] = energy;
    SmOptions options; sm_default_options(&options);
    interp::Texture white; white.type = SM_TEX_2D; white.d = 1;
    for (int k = 0; k < 4; ++k) white.texels.push_back(1);
    interp::Context ctx; ctx.c = &pc[0][0]; ctx.ci = &integers[0][0]; ctx.cb = booleans; ctx.opt = options;
    for (const auto &instruction : ps.shader.code)
        if (instruction.op == sm::OP_DCL && instruction.dst.type == sm::R_SAMPLER) ctx.tex[instruction.dst.num] = &white;
    interp::PSIn in = {};
    in.col[0] = {s, s / 2, s / 4, 1};
    for (int k = 0; k < 8; ++k) in.tex[k] = {0.5f, 0.5f, 0.5f, 1};
    interp::PSOut result = {};
    if (!interp::run_ps(ps.shader, ctx, in, result)) return false;
    for (int k = 0; k < 4; ++k) out[k] = result.oc[0][k];
    return true;
}
static int live(std::map<uint64_t,Program> &original) {
    unsigned checks=0,failures=0;SmOptions options;sm_default_options(&options);
    for(uint64_t key:keys)for(unsigned row=0;row<2;++row)for(unsigned start=0;start<2;++start){
        Program &o=original[key];Obj ps={};ps.tokens=o.tokens.data();ps.ntokens=o.tokens.size();
        ShaderEntry *first=nullptr;float first_rgba[4]={};
        for(unsigned step=0;step<4;++step){
            unsigned value=(step&1)?!start:start;
            setenv("NFS_CARBON_COAT",row==1&&!value?"0":"1",1);
            setenv("NFS_CARBON_REFLECT_HDR",row==0&&!value?"0":"1",1);
            ShaderEntry *e=get_shader_variant(&ps,&options,0);
            Program p;p.tokens=e->compiled_tokens;if(!sm::parse(p.tokens.data(),p.tokens.size(),p.shader))return 2;
            float out[4],base[4];if(!shade(p,1,1-1/64.f,out)||!shade(p,1,0,base))return 2;
            ++checks;if(fabs(out[0]-(value?64.f:1.f))>.001f)++failures;
            ++checks;if(base[0]!=1||base[3]!=out[3]||e->variant)++failures;
            if(!step){first=e;memcpy(first_rgba,out,sizeof out);}
            if(step==2){++checks;if(first!=e||memcmp(first_rgba,out,sizeof out))++failures;}
        }
    }
    printf("LIVE lamp rows=2 starts=2 programs=2 transitions=24 checks=%u failures=%u exact restore=8\n",checks,failures);
    return failures?1:0;
}
int main(int argc, char **argv) {
    if (argc != 3) return 2;
    bool control = !strcmp(argv[2], "control"), off = !strcmp(argv[2], "off");
    FILE *file = fopen(argv[1], "rb"); if (!file) return 2;
    fseek(file, 0, SEEK_END); size_t size = ftell(file); rewind(file);
    std::vector<uint32_t> blob((size+3)/4); if (fread(blob.data(), 1, size, file) != size) return 2; fclose(file);
    std::map<uint64_t, Program> original, patched;
    for (size_t k = 0; k < size/4; ++k) {
        if (blob[k] != 0xffff0200u) continue;
        size_t count = sm_token_count(blob.data()+k, size/4-k); if (!count) continue;
        uint64_t key = key_of(blob.data()+k, count);
        if ((key != keys[0] && key != keys[1]) || original.count(key)) continue;
        uint32_t *tokens = blob.data()+k, patched_count = 0;
        uint32_t *variant = carbon_coat_variant(tokens, count, &patched_count);
        if (off) { if (variant) return 2; original[key]; continue; }
        if (!variant) { fprintf(stderr, "program %016llx declined\n", (unsigned long long)key); return 2; }
        Program &o = original[key], &n = patched[key];
        o.tokens.assign(tokens, tokens+count); n.tokens.assign(variant, variant+patched_count); free(variant);
        if (!sm::parse(o.tokens.data(), o.tokens.size(), o.shader) || !sm::parse(n.tokens.data(), n.tokens.size(), n.shader)) return 2;
        if (sm_token_count(n.tokens.data(), n.tokens.size()) != n.tokens.size()) return 2;
        SmOptions options; sm_default_options(&options); SmResult result = {};
        if (sm_translate(n.tokens.data(), n.tokens.size(), &options, &result)) { fprintf(stderr, "translate: %s\n", result.error); return 2; }
        sm_result_free(&result);
        std::vector<uint32_t> changed(o.tokens); changed[0] ^= 1; uint32_t ignored = 0;
        if (carbon_coat_variant(changed.data(), changed.size(), &ignored)) return 2;
    }
    if (original.size() != 2) { fprintf(stderr, "programs found: %zu of 2\n", original.size()); return 2; }
    if (off) { puts("OFF: both programs decline"); return 0; }
    if (!strcmp(argv[2],"live")) return live(original);
    const float energy = 1 - 1 / 64.f, levels[3] = {1, 0.9f, 0.5f};
    unsigned checks = 0, failures = 0, same = 0;
    for (int p = 0; p < 2; ++p) {
        const Program &o = original[keys[p]], &n = control ? o : patched[keys[p]];
        printf("%s:", names[p]);
        for (float s : levels) {
            float base[4], lit[4], dark[4];
            if (!shade(o, s, energy, base) || !shade(n, s, energy, lit) || !shade(n, s, 0, dark)) return 2;
            float m = std::fmin(std::fmax(base[0], std::fmax(base[1], base[2])) * base[3], 1.f);
            if (!(m > 0)) { fprintf(stderr, "%s: no light at s=%.2f\n", names[p], s); return 2; }
            for (int k = 0; k < 3; ++k) {
                float expected = base[k] / (1 - energy * m);
                ++checks; failures += !(std::fabs(lit[k] - expected) <= 0.001f * expected);
            }
            ++checks; failures += lit[3] != base[3];
            same += !memcmp(dark, base, sizeof base);
            printf(" %.2f", lit[0]);
        }
        puts("");
    }
    printf("%s: %u checks, %u failures; energy 0 identical %u of 6\n", control ? "control" : "patched", checks, failures, same);
    return failures || same != 6;
}
'''


def run(command, *, expected=0, timeout=180, hdr='1'):  # hdr 'unset' leaves the switch unset (default On)
    env = {k: v for k, v in os.environ.items() if k not in ('NFS_CARBON_REFLECT_HDR', 'NFS_CARBON_COAT')}
    if hdr != 'unset':
        env['NFS_CARBON_REFLECT_HDR'] = hdr
    result = subprocess.run(list(map(str, command)), capture_output=True, text=True, timeout=timeout, env=env)
    assert result.returncode == expected, (result.returncode, result.stdout[-1000:], result.stderr[-2000:])
    return result.stdout.strip()


def main():
    image = HERE/'out/carbon/image.json'
    shaders = ROOT/'host/shaders'
    library = shaders/'build/libsmtranslate.a'
    if not image.is_file() or not library.is_file():
        print('SKIP: private outputs / translator absent'); return 3
    exe = Path(json.loads(image.read_text())['exe'])
    if not exe.is_file():
        print('SKIP: private executable absent'); return 3
    switches = (ROOT/'runtime/switches.tsv').read_text()
    assert '\nNFS_CARBON_REFLECT_HDR\tprivate\t1\t' in switches
    out = ignored_output(HERE/'out/carbon/lamp_energy_check')
    (out/'coat.inc').write_bytes((HERE/'private_runtime/carbon_coat.h').read_bytes())
    support=COAT_HARNESS[COAT_HARNESS.index('struct ShaderEntry'):COAT_HARNESS.index('static uint64_t key_of')]
    render=(ROOT/'runtime/render.m').read_text()
    start=render.index('typedef struct { uint32_t serial, variant; uint8_t opt[48]; ShaderEntry *e; } VariantCache;')
    end=render.index('static ShaderEntry *get_shader(Obj *s',start)
    lookup=render[start:end]
    (out/'lookup.inc').write_text(lookup)
    (out/'submit.inc').write_bytes((HERE/'private_runtime/game_compat_shader_submit.h').read_bytes())
    (out/'lamp.cpp').write_text(HARNESS.replace('LOOKUP_SUPPORT',support))
    binary = out/'lamp'
    run(['clang++', '-std=c++17', '-O1', '-w', '-DNFS_GAME=2', '-DNFS_GAME_PRIVATE=2', '-I', shaders, '-I', out, out/'lamp.cpp',
         shaders/'tests/sm_interp.cpp', library, '-framework', 'Foundation', '-framework', 'Metal', '-o', binary])
    print(run([binary, exe, 'live']))
    # The previous submission cache ignores settings when choosing the compiled program.
    (out/'lookup.inc').write_text(lookup.replace('variant = carbon_coat_cache_variant(s->tokens_hash, variant);','(void)0;'))
    run(['clang++', '-std=c++17', '-O1', '-w', '-DNFS_GAME=2', '-DNFS_GAME_PRIVATE=2', '-I', shaders, '-I', out, out/'lamp.cpp',
         shaders/'tests/sm_interp.cpp', library, '-framework', 'Foundation', '-framework', 'Metal', '-o', out/'old-cache'])
    print(run([out/'old-cache', exe, 'live'], expected=1))
    (out/'lookup.inc').write_text(lookup)
    print(run([binary, exe, 'patched']))
    print(run([binary, exe, 'control'], expected=1))
    print(run([binary, exe, 'off'], hdr='0'))
    print(run([binary, exe, 'patched'], hdr='unset'))
    print('PRIVATE LAMP ENERGY PASS')
    return 0


if __name__ == '__main__':
    sys.exit(main())
