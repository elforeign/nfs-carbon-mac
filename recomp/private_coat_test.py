"""Lacquer reflection on the ten car paint programs (NFS_CARBON_COAT).

Reflection gain with a unit cube at N.V 1/.3/0, production bytecode run in the
translator's interpreter (vertex program feeding its pixel program):
  patched: .0400/.2013/1.0000 on car t0, car t2 and both car_normalmap pairs,
           .0400/.2013/.2500 on lowlod (its retail grazing gate of .25 is kept);
           limit: within 5 % of .04 + .96 (1 - N.V)^5, 35 checks, 0 failures.
  control (the unpatched tokens against the same limit): .5000/1.1817/2.0000
           (car_normalmap .2500/.5909/1.0000: it never doubled), 28 failures, exit 1.
Also: the layer below is scaled by 1 - F, the cube is read without the horizon
pull, chrome, chrome paint, matte paint and glass records are bit-identical to
retail on all five pairs, a changed byte declines, NFS_CARBON_COAT=0 declines (unset is on).
Live lookup: 2 rows x 2 starting states x 5 VS/PS pairs, 60 transitions;
360 checks, recipe/prewarm/lookup identities agree, exact entry/output restoration,
0 failures. Original cache identity: 140 failures, exit 1 vs good 0.
Original recipe keys without resolution: 40 failures, exit 1 vs good 0.
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

HARNESS = r'''
#include "sm_translate.h"
#include "tests/sm_interp.h"
#include <cmath>
#include <cstdio>
#include <cstring>
#include <map>
#include <vector>
#include "coat.inc"
struct ShaderEntry { uint32_t *tokens, ntokens; uint64_t key; SmOptions opt; uint32_t variant; std::vector<uint32_t> compiled_tokens; };
struct Obj {
    uint32_t *tokens, ntokens; uint64_t tokens_hash, memo_key[2], last_key;
    uint32_t memo_variant[2], memo_next, last_idx, vc_serial;
    unsigned char memo_opt[2][48];
};
static std::vector<ShaderEntry *> shaders;
static unsigned nshaders;
static uint64_t fnv(const void *p,size_t n,uint64_t hash) {
    const unsigned char *b=(const unsigned char *)p;
    for(size_t i=0;i<n;++i)hash=(hash^b[i])*1099511628211ull;
    return hash;
}
static int shader_shape(const uint32_t *,uint32_t,uint64_t) { return 0; }
static SmOptions shader_options(int,const SmOptions *opt) { return *opt; }
static ShaderEntry *new_entry(uint64_t key,const uint32_t *tokens,uint32_t n,const SmOptions *opt,uint32_t variant) {
    ShaderEntry *e=new ShaderEntry{};e->tokens=(uint32_t *)malloc(n*4);memcpy(e->tokens,tokens,n*4);
    e->key=key;e->ntokens=n;e->opt=*opt;e->variant=variant;shaders.push_back(e);++nshaders;return e;
}
static void cache_append(const ShaderEntry *e) { if(e->variant)abort(); }

static unsigned compiled;
uint32_t *carbon_daynight_shader(const uint32_t *, uint32_t, uint32_t *) { return nullptr; }
uint32_t *carbon_road_headlight_shader(const uint32_t *,uint32_t,const uint32_t *,uint32_t,uint32_t *) { return nullptr; } /* covered by private_road_headlight_test */
static void compile_entry(ShaderEntry *e) { ++compiled; e->compiled_tokens.assign(e->tokens,e->tokens+e->ntokens); }
static void shader_submit(ShaderEntry *e)
#include "submit.inc"
#include "lookup.inc"
static uint64_t key_of(const uint32_t *tokens, size_t count) {
    uint64_t key = 1469598103934665603ull;
    const unsigned char *bytes = (const unsigned char *)tokens;
    for (size_t k = 0; k < count * 4; ++k) key = (key ^ bytes[k]) * 1099511628211ull;
    return key;
}
struct Pair { const char *name; uint64_t vs, ps; int eye, pull, record, vinyl, powers; float below, grazing_gate; };
static const Pair pairs[] = {
    {"car t0", 0xb0fa697e82074657ull, 0x3c185b9815aee740ull, 19, 20, 21, 10, 9, 1, 1},
    {"car t2", 0x5f097ccbab4310d2ull, 0x63c39e750b34dff3ull, 19, 20, 21, 9, 8, 1, 1},
    {"car lowlod", 0x4c70062f23adfc25ull, 0xc35feb322f2add1cull, 17, -1, 18, 2, -1, 1, 0.25f},
    {"car_normalmap t0", 0x02ad8c64c66fc529ull, 0x107be5ec81ba9635ull, 19, 20, 21, 10, 9, 0.5f, 1},
    {"car_normalmap t2", 0x32db3da103f82cacull, 0xeab92bd8c08134bcull, 19, 20, 21, 7, 6, 0.5f, 1},
};
struct Record { float vinyl_x, vinyl_z, env_min, env_range, alpha; };
struct Program { std::vector<uint32_t> tokens; sm::Shader shader; };
static interp::Texture solid(int type, int faces, float r, float g, float b, float a) {
    interp::Texture t; t.type = type; t.d = faces;
    for (int k = 0; k < faces; ++k) { t.texels.push_back(r); t.texels.push_back(g); t.texels.push_back(b); t.texels.push_back(a); }
    return t;
}
/* Red output of one vertex shaded by the pair; cube: 0 black, 1 white, 2 = +x 3 / -z 1. */
static float shade(const Pair &p, const Program &vs, const Program &ps, const Record &m, float nv, float diffuse, int cube_kind, bool *ok) {
    float vc[256][4] = {}, pc[256][4] = {}; int integers[16][4] = {}, booleans[16] = {};
    vc[0][0] = vc[0][1] = vc[0][2] = 1;                                  /* constant ambient term */
    for (int k = 0; k < 4; ++k) vc[10+k][k] = 1;                         /* WorldViewProj */
    for (int k = 0; k < 3; ++k) vc[14+k][k] = 1;                         /* cmWorldView */
    vc[p.eye][2] = 5;
    if (p.pull >= 0) vc[p.pull][0] = 0.4f;
    const int r = p.record;
    for (int k = 0; k < 3; ++k) { vc[r][k] = diffuse; vc[r+2][k] = m.env_min; vc[r+3][k] = m.env_range; }
    vc[r][3] = m.alpha;
    vc[r+4][0] = 1.5f; vc[r+4][1] = 40; vc[r+4][2] = 1;                  /* cvPowers */
    vc[r+5][0] = 0.35f; vc[r+5][1] = 0.54995f; vc[r+5][2] = 1/0.35f; vc[r+5][3] = 1.81835f;
    vc[r+6][1] = 0.1f; vc[r+6][2] = 0.2f; vc[r+6][3] = 0.8f;             /* cvFlakes */
    pc[p.vinyl][0] = m.vinyl_x; pc[p.vinyl][2] = m.vinyl_z;
    if (p.powers >= 0) pc[p.powers][1] = 40;
    SmOptions options; sm_default_options(&options);
    interp::Context vctx; vctx.c = &vc[0][0]; vctx.ci = &integers[0][0]; vctx.cb = booleans; vctx.opt = options;
    interp::VSIn in = {};
    in.v[0] = {0, 0, 0, 1};
    in.v[1] = {std::sqrt(1 - nv*nv), 0, nv, 0};
    in.v[3] = {0, 1, 0, 1};
    interp::VSOut out = {};
    if (!interp::run_vs(vs.shader, vctx, in, out)) { *ok = false; return 0; }
    interp::Texture flat = solid(SM_TEX_2D, 1, 0.5f, 0.5f, 0.5f, 0), volume = solid(SM_TEX_3D, 1, 0.5f, 0.5f, 0.5f, 0.5f);
    float c = cube_kind == 1 ? 1.0f : 0.0f;
    interp::Texture cube = solid(SM_TEX_CUBE, 6, c, c, c, 1);
    if (cube_kind == 2) { cube.texels[0] = 3; cube.texels[5*4] = 1; }
    interp::Context pctx; pctx.c = &pc[0][0]; pctx.ci = &integers[0][0]; pctx.cb = booleans; pctx.opt = options;
    for (const auto &instruction : ps.shader.code)
        if (instruction.op == sm::OP_DCL && instruction.dst.type == sm::R_SAMPLER)
            pctx.tex[instruction.dst.num] = instruction.tex_type == 3 ? &cube : instruction.tex_type == 4 ? &volume : &flat;
    interp::PSIn pin = {};
    for (int k = 0; k < 2; ++k) pin.col[k] = out.col[k];
    for (int k = 0; k < 8; ++k) pin.tex[k] = out.tex[k];
    pin.fog = out.fog;
    interp::PSOut pout = {};
    if (!interp::run_ps(ps.shader, pctx, pin, pout)) { *ok = false; return 0; }
    return pout.oc[0][0];
}
static Program live_program(ShaderEntry *e) {
    Program p;p.tokens=e->compiled_tokens;
    if(!sm::parse(p.tokens.data(),p.tokens.size(),p.shader))abort();
    return p;
}
static int live(std::map<uint64_t,Program> &original) {
    unsigned checks=0,failures=0;
    SmOptions options;sm_default_options(&options);
    const Record paint={0,0,1,-.75f,1}, chrome={1,0,.5f,0,1};
    for(unsigned row=0;row<2;++row)for(unsigned start=0;start<2;++start)for(const Pair &p:pairs){
        Program &ovs=original[p.vs],&ops=original[p.ps];
        Obj vs={},ps={};vs.tokens=ovs.tokens.data();vs.ntokens=ovs.tokens.size();ps.tokens=ops.tokens.data();ps.ntokens=ops.tokens.size();
        ShaderEntry *first_vs=nullptr,*first_ps=nullptr;
        float results[4]={};bool ok=true;
        for(unsigned step=0;step<4;++step){
            unsigned value=(step&1)?!start:start;
            setenv("NFS_CARBON_COAT",(row==0?!value:false)?"0":"1",1);
            setenv("NFS_CARBON_MATERIALS",(row==1?!value:false)?"0":"1",1);
            ShaderEntry *v=get_shader_variant(&vs,&options,0),*q=get_shader_variant(&ps,&options,0);
            Program pv=live_program(v),pp=live_program(q);
            const Record &record=row==0?paint:chrome;
            float gain=shade(p,pv,pp,record,1,0,1,&ok)-shade(p,pv,pp,record,1,0,0,&ok);
            results[step]=gain;
            float want;
            if(value)want=row==0?.04f:.5545f;
            else if(row==0)want=shade(p,ovs,ops,record,1,0,1,&ok)-shade(p,ovs,ops,record,1,0,0,&ok);
            else {
                carbon_coat_materials=0;uint32_t nv=0,np=0;
                uint32_t *tv=carbon_coat_variant(vs.tokens,vs.ntokens,&nv),*tp=carbon_coat_variant(ps.tokens,ps.ntokens,&np);
                Program ev,ep;ev.tokens.assign(tv,tv+nv);ep.tokens.assign(tp,tp+np);free(tv);free(tp);
                if(!sm::parse(ev.tokens.data(),ev.tokens.size(),ev.shader)||!sm::parse(ep.tokens.data(),ep.tokens.size(),ep.shader))abort();
                want=shade(p,ev,ep,record,1,0,1,&ok)-shade(p,ev,ep,record,1,0,0,&ok);
            }
            ++checks;if(!ok||fabs(gain-want)>.05f*want+1e-6f)++failures;
            ++checks;if(memcmp(vs.tokens,ovs.tokens.data(),vs.ntokens*4)||memcmp(ps.tokens,ops.tokens.data(),ps.ntokens*4))++failures;
            ++checks;if(warm_key(vs.tokens,vs.ntokens,&options,0)!=v->key||warm_key(ps.tokens,ps.ntokens,&options,0)!=q->key)++failures;
            Recipe recipe=live_recipe({fnv(&options,sizeof options,vs.tokens_hash),fnv(&options,sizeof options,ps.tokens_hash)});
            ++checks;if(recipe.vertex!=v->key||recipe.fragment!=q->key)++failures;
            if(!step){first_vs=v;first_ps=q;}
            if(step==2){++checks;if(v!=first_vs||q!=first_ps||results[0]!=gain)++failures;}
        }
        ++checks;if(results[0]==results[1]||results[1]!=results[3])++failures;
    }
    printf("LIVE shader rows=2 starts=2 pairs=5 transitions=60 checks=%u failures=%u exact restore=20\n",checks,failures);
    return failures?1:0;
}
int main(int argc, char **argv) {
    if (argc != 3) return 2;
    bool retail = !strcmp(argv[2], "retail");
    FILE *file = fopen(argv[1], "rb"); if (!file) return 2;
    fseek(file, 0, SEEK_END); size_t size = ftell(file); rewind(file);
    std::vector<uint32_t> blob((size+3)/4); if (fread(blob.data(), 1, size, file) != size) return 2; fclose(file);
    std::map<uint64_t, Program> original, patched;
    for (size_t k = 0; k < size/4; ++k) {
        uint32_t version = blob[k];
        uint32_t kind = version >> 16, level = version & 0xffff;
        if ((kind != 0xfffe && kind != 0xffff) || (level != 0x0200 && level != 0x0300)) continue;
        size_t count = sm_token_count(blob.data()+k, size/4-k); if (!count) continue;
        uint64_t key = key_of(blob.data()+k, count);
        bool wanted = false;
        for (const Pair &p : pairs) wanted |= key == p.vs || key == p.ps;
        if (!wanted || original.count(key)) continue;
        uint32_t *tokens = blob.data()+k, patched_count = 0;
        uint32_t *variant = carbon_coat_variant(tokens, count, &patched_count);
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
        /* NFS_CARBON_COAT=0 in this process: the submit hook compiles and restores the original. */
        ShaderEntry entry = {tokens, (uint32_t)count}; compiled = 0;
        shader_submit(&entry);
        if (compiled != 1 || entry.tokens != tokens || entry.ntokens != count || carbon_coat_shader(tokens, count, &ignored)) return 2;
    }
    if (!strcmp(argv[2],"live")) return live(original);
    if (original.size() != 10) { fprintf(stderr, "programs found: %zu of 10\n", original.size()); return 2; }
    const Record paint = {0, 0, 1, -0.75f, 1}, chrome = {1, 0, 0.5f, 0, 1}, chrome_paint = {0, 0.75f, 1.5f, 0, 1},
                 matte = {0, 0, 0, 0, 1}, glass = {1, 0, 0.875f, -0.25f, 0.5f};
    unsigned checks = 0, failures = 0, exact = 0, exact_failures = 0; bool ok = true;
    for (const Pair &p : pairs) {
        const Program &ovs = original[p.vs], &ops = original[p.ps];
        const Program &vs = retail ? ovs : patched[p.vs], &ps = retail ? ops : patched[p.ps];
        float gains[3], below[3], pulled = 0; int n = 0;
        for (float nv : {1.0f, 0.3f, 0.0f}) {
            float fresnel = 0.04f + 0.96f * std::pow(1 - nv, 5.0f);
            float want = fresnel * (nv < 0.15f ? p.grazing_gate : 1);
            gains[n] = shade(p, vs, ps, paint, nv, 0, 1, &ok);
            below[n] = shade(p, vs, ps, paint, nv, 0.5f, 0, &ok) / (0.5f * p.below);
            ++checks; if (!(std::fabs(gains[n] - want) <= 0.05f * want)) ++failures;
            ++checks; if (!(std::fabs(below[n] - (1 - fresnel)) <= 0.05f)) ++failures;
            if (nv == 0.3f) {
                pulled = shade(p, vs, ps, paint, nv, 0, 2, &ok); /* -z face (1) without the pull, +x (3) with it */
                ++checks; if (!(std::fabs(pulled - want) <= 0.05f * want)) ++failures;
            }
            for (const Record *m : {&chrome, &chrome_paint, &matte, &glass}) for (int cube : {1, 2}) {
                float a = shade(p, ovs, ops, *m, nv, 0.5f, cube, &ok), b = shade(p, patched[p.vs], patched[p.ps], *m, nv, 0.5f, cube, &ok);
                ++exact; if (memcmp(&a, &b, sizeof a)) ++exact_failures;
            }
            ++n;
        }
        printf("%-17s gain %.4f/%.4f/%.4f  below %.4f/%.4f/%.4f  pull-face %.4f\n", p.name, gains[0], gains[1], gains[2], below[0], below[1], below[2], pulled);
    }
    if (!ok) return 2;
    printf("COAT %s checks=%u failures=%u other-records=%u differing=%u\n", retail ? "retail" : "patched", checks, failures, exact, exact_failures);
    return failures || exact_failures ? 1 : 0;
}
'''


def run(command, *, expected=0, timeout=180):
    env = dict(os.environ, NFS_CARBON_COAT='0', NFS_CARBON_MATERIALS='0')
    result = subprocess.run(list(map(str, command)), capture_output=True, text=True, timeout=timeout, env=env)
    if result.returncode != expected:
        raise RuntimeError(f'exit {result.returncode}, expected {expected}: {result.stdout[-1800:]} {result.stderr[-1800:]}')
    return (result.stdout + result.stderr).strip()


def main():
    feature=json.loads((HERE/'private_runtime/features/coat.json').read_text())
    assert feature['staged_sources']['carbon_coat.c']=='carbon_coat.h'
    image = HERE/'out/carbon/image.json'
    shaders = ROOT/'host/shaders'
    library = shaders/'build/libsmtranslate.a'
    if not image.is_file() or not library.is_file():
        print('SKIP: private outputs / translator absent'); return 3
    exe = Path(json.loads(image.read_text())['exe'])
    if not exe.is_file():
        print('SKIP: private executable absent'); return 3
    switches = (ROOT/'runtime/switches.tsv').read_text()
    assert '\nNFS_CARBON_COAT\tprivate\t1\t' in switches
    out = ignored_output(HERE/'out/carbon/coat_check')
    (out/'coat.inc').write_bytes((HERE/'private_runtime/carbon_coat.h').read_bytes())
    (out/'submit.inc').write_bytes((HERE/'private_runtime/game_compat_shader_submit.h').read_bytes())
    render=(ROOT/'runtime/render.m').read_text()
    start=render.index('typedef struct { uint32_t serial, variant; uint8_t opt[48]; ShaderEntry *e; } VariantCache;')
    end=render.index('static ShaderEntry *get_shader(Obj *s',start)
    lookup=render[start:end]
    warm_start=render.index('            uint64_t hash = fnv(t, 4 * (size_t)n, 1469598103934665603ull);')
    warm_end=render.index('            int dup = 0;',warm_start)
    warm='static uint64_t warm_key(uint32_t *t,uint32_t n,const SmOptions *requested,uint32_t variant) {\nSmOptions opt=*requested;\n'+render[warm_start:warm_end]+'return key;\n}\n'
    prewarm=(HERE/'private_runtime/game_pipeline_prewarm.h').read_text()
    mapping=prewarm[prewarm.index('            extern uint64_t carbon_coat_recipe_key'):prewarm.index('            NSData *key=')]
    lookup+=warm+'struct Recipe { uint64_t vertex,fragment; };\nstatic Recipe live_recipe(Recipe r) {\n'+mapping+'return r;\n}\n'
    (out/'lookup.inc').write_text(lookup)
    (out/'coat.cpp').write_text(HARNESS)
    binary = out/'coat'
    run(['clang++', '-std=c++17', '-O1', '-w', '-DNFS_GAME=2', '-DNFS_GAME_PRIVATE=2', '-I', shaders, '-I', out, out/'coat.cpp',
         shaders/'tests/sm_interp.cpp', library, '-framework', 'Foundation', '-framework', 'Metal', '-o', binary])
    print(run([binary, exe, 'live']))
    old_lookup=lookup.replace('variant = carbon_coat_cache_variant(s->tokens_hash, variant);','(void)0;')
    assert old_lookup!=lookup
    (out/'lookup.inc').write_text(old_lookup)
    run(['clang++', '-std=c++17', '-O1', '-w', '-DNFS_GAME=2', '-DNFS_GAME_PRIVATE=2', '-I', shaders, '-I', out, out/'coat.cpp',
         shaders/'tests/sm_interp.cpp', library, '-framework', 'Foundation', '-framework', 'Metal', '-o', out/'old-cache'])
    print(run([out/'old-cache', exe, 'live'], expected=1))
    (out/'lookup.inc').write_text(lookup.replace('r.vertex=carbon_coat_recipe_key(r.vertex);','r.vertex=r.vertex;').replace('r.fragment=carbon_coat_recipe_key(r.fragment);','r.fragment=r.fragment;'))
    run(['clang++', '-std=c++17', '-O1', '-w', '-DNFS_GAME=2', '-DNFS_GAME_PRIVATE=2', '-I', shaders, '-I', out, out/'coat.cpp',
         shaders/'tests/sm_interp.cpp', library, '-framework', 'Foundation', '-framework', 'Metal', '-o', out/'old-prewarm'])
    print(run([out/'old-prewarm', exe, 'live'], expected=1))
    (out/'lookup.inc').write_text(lookup)
    print(run([binary, exe, 'patched']))
    print(run([binary, exe, 'retail'], expected=1))
    print('PRIVATE COAT PASS')
    return 0


if __name__ == '__main__':
    sys.exit(main())
