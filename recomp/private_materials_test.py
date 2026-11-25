"""Physical chrome, wheel paint, glass and chrome paint on the ten car programs (NFS_CARBON_MATERIALS).

Every one of the 162 material records of GLOBALB.BUN (chunk 0x135200, constants built as the
game's bind does) is run through all five program pairs in the translator's interpreter at
N.V 1/.3/0; the class of a record comes from its name here, not from the code under test.
Reflection gain = white cube minus black cube (glass: x output alpha), limit 5 %; glass also
transmittance = 1 - output alpha within .01. Numbers of car t0 (the last record of each class):
  class (records)   target                                      patched            lacquer-only control
  chrome (12)       .5545 + .4455 (1 - N.V)^5                   .5545/.6294/1.0    3.0/1.6/1.0 (CHROME itself 1.0 flat)
  wheel paint (9)   .04 + .96 (1 - N.V)^5                       .0400/.2013/1.0    .40/1.12/2.00
  chrome paint (8)  .5545 x tint per channel, to 1 at grazing   .5545/.6294/1.0    3.0/3.0/3.0 (2.0 on the SM2 pairs)
  glass (27)        pane 2F/(1+F), F0 .0432                     .0828/.3389/1.0    clear .625/.725/.875, films to 3.8
    transmittance   clear .75 (1-R)/(1-R0); films 1 - alpha     clear .750/.541/0  clear .50/.50/.50
  paint (42, job 1) .04 + .96 (1 - N.V)^5                       .0400/.2013/1.0    the same (this switch leaves it)
  lowlod keeps its retail grazing gate (x .25 below N.V .15).
Brake-light covers: normal-view gain .0828 +/-5%; original control 3.0000 fails.
Texture alpha is retained at 238/255 and 105/255; separate bulbs remain bit-identical.
The other 64 records (matte paint, matte wheels, rubber, bulbs, traffic, cop, ...) must be
bit-identical to the lacquer-only programs: output RGBA, two cubes, all five pairs.
  patched: 4875 class checks, 0 failures; 1920 identity checks, 0 differ.
  control (the lacquer-only programs against the same limits): 2559 of 4875 fail, exit 1.
Private executable, data file or translator absent: exit 3; no game is launched.
"""
from pathlib import Path
import json
import hashlib
import os
import struct
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
def switch_registry(root):
    """runtime/switches.tsv, or None in a public copy. The registry is dev-only (tools/publish/denylist.txt keeps it out
    of the public repos), so only a tree without tools/publish may lack it; in the dev repo a missing file still fails."""
    path = root / 'runtime/switches.tsv'
    if path.is_file() or (root / 'tools/publish').is_dir():
        return path.read_text()
    print('skip: switch registry checks (runtime/switches.tsv is not exported to the public repo)', flush=True)
    return None

sys.path.insert(0, str(HERE))
from build_private import ignored_output

# Original glass selector: pinned independently of checkout history.
ORIGINAL_GLASS = '''        CM_ADD, CM_D(8,7), CM_C(Pw,CM_A), CM_C(K,CM_Y) | CM_NEG,
        CM_ABS, CM_D(8,7), CM_R(8,CM_A),
        CM_DP3, CM_D(8,1), CM_R(8,CM_A), CM_C(K,CM_Y),
        CM_SLT, CM_D(8,1), CM_R(8,CM_X), CM_C(C1,CM_Y),
        CM_SLT, CM_D(8,2), CM_C(Cl,CM_Y), CM_C(C3,CM_W),
        CM_MUL, CM_D(11,4), CM_R(8,CM_X), CM_R(8,CM_Y),                /* r11.z: glass */
'''
ORIGINAL_GLASS_SHA256 = '5328b96468802142f595188dacf6a358626797c50e87ec15ebedc570276236c7'

HARNESS = r'''
#include "sm_translate.h"
#include "tests/sm_interp.h"
#include <cmath>
#include <cstdio>
#include <cstring>
#include <map>
#include <vector>
#include "coat.inc"
static uint64_t key_of(const uint32_t *tokens, size_t count) {
    uint64_t key = 1469598103934665603ull;
    const unsigned char *bytes = (const unsigned char *)tokens;
    for (size_t k = 0; k < count * 4; ++k) key = (key ^ bytes[k]) * 1099511628211ull;
    return key;
}
struct Pair { const char *name; uint64_t vs, ps; int eye, pull, record, vinyl, powers; float grazing_gate; };
static const Pair pairs[] = {
    {"car t0", 0xb0fa697e82074657ull, 0x3c185b9815aee740ull, 19, 20, 21, 10, 9, 1},
    {"car t2", 0x5f097ccbab4310d2ull, 0x63c39e750b34dff3ull, 19, 20, 21, 9, 8, 1},
    {"car lowlod", 0x4c70062f23adfc25ull, 0xc35feb322f2add1cull, 17, -1, 18, 2, -1, 0.25f},
    {"car_normalmap t0", 0x02ad8c64c66fc529ull, 0x107be5ec81ba9635ull, 19, 20, 21, 10, 9, 1},
    {"car_normalmap t2", 0x32db3da103f82cacull, 0xeab92bd8c08134bcull, 19, 20, 21, 7, 6, 1},
};
enum { OTHER, PAINT, CHROME, WHEEL, GLASS, CLEAR_GLASS, CHROME_PAINT, BRAKE_GLASS, CLASSES };
static const char *class_names[] = {"other", "paint", "chrome", "wheel paint", "glass", "clear glass", "chrome paint", "brake-light glass"};
struct Record { const char *name; int kind; float vs[7][4], vinyl[4]; };
#include "records.inc"
struct Program { std::vector<uint32_t> tokens; sm::Shader shader; };
struct Colour { float c[4]; };
static interp::Texture solid(int type, int faces, float r, float g, float b, float a) {
    interp::Texture t; t.type = type; t.d = faces;
    for (int k = 0; k < faces; ++k) { t.texels.push_back(r); t.texels.push_back(g); t.texels.push_back(b); t.texels.push_back(a); }
    return t;
}
/* One vertex shaded by the pair; cube: 0 black, 1 white, 2 = +x 3 / -z 1. */
static Colour shade(const Pair &p, const Program &vs, const Program &ps, const Record &m, float nv, int cube_kind, float coverage, bool *ok) {
    float vc[256][4] = {}, pc[256][4] = {}; int integers[16][4] = {}, booleans[16] = {};
    vc[0][0] = vc[0][1] = vc[0][2] = 1;
    for (int k = 0; k < 4; ++k) vc[10+k][k] = 1;
    for (int k = 0; k < 3; ++k) vc[14+k][k] = 1;
    vc[p.eye][2] = 5;
    if (p.pull >= 0) vc[p.pull][0] = 0.4f;
    memcpy(vc[p.record], m.vs, sizeof m.vs);
    memcpy(pc[p.vinyl], m.vinyl, sizeof m.vinyl);
    if (p.powers >= 0) pc[p.powers][1] = m.vs[4][1];
    SmOptions options; sm_default_options(&options);
    interp::Context vctx; vctx.c = &vc[0][0]; vctx.ci = &integers[0][0]; vctx.cb = booleans; vctx.opt = options;
    interp::VSIn in = {};
    in.v[0] = {0, 0, 0, 1};
    in.v[1] = {std::sqrt(1 - nv*nv), 0, nv, 0};
    in.v[3] = {0, 1, 0, 1};
    interp::VSOut out = {};
    Colour result = {};
    if (!interp::run_vs(vs.shader, vctx, in, out)) { *ok = false; return result; }
    interp::Texture flat = solid(SM_TEX_2D, 1, 0.5f, 0.5f, 0.5f, coverage), volume = solid(SM_TEX_3D, 1, 0.5f, 0.5f, 0.5f, 0.5f);
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
    if (!interp::run_ps(ps.shader, pctx, pin, pout)) { *ok = false; return result; }
    for (int k = 0; k < 4; ++k) result.c[k] = pout.oc[0][k];
    return result;
}
static bool load(const std::vector<uint32_t> &blob, size_t size, int materials, std::map<uint64_t, Program> &programs) {
    carbon_coat_materials = materials;
    for (size_t k = 0; k < size/4; ++k) {
        uint32_t version = blob[k];
        uint32_t kind = version >> 16, level = version & 0xffff;
        if ((kind != 0xfffe && kind != 0xffff) || (level != 0x0200 && level != 0x0300)) continue;
        size_t count = sm_token_count(blob.data()+k, size/4-k); if (!count) continue;
        uint64_t key = key_of(blob.data()+k, count);
        bool wanted = false;
        for (const Pair &p : pairs) wanted |= key == p.vs || key == p.ps;
        if (!wanted || programs.count(key)) continue;
        uint32_t patched_count = 0;
        uint32_t *variant = carbon_coat_variant(blob.data()+k, count, &patched_count);
        if (!variant) { fprintf(stderr, "program %016llx declined\n", (unsigned long long)key); return false; }
        Program &n = programs[key];
        n.tokens.assign(variant, variant+patched_count); free(variant);
        if (!sm::parse(n.tokens.data(), n.tokens.size(), n.shader)) return false;
        if (sm_token_count(n.tokens.data(), n.tokens.size()) != n.tokens.size()) return false;
        SmOptions options; sm_default_options(&options); SmResult result = {};
        if (sm_translate(n.tokens.data(), n.tokens.size(), &options, &result)) { fprintf(stderr, "translate: %s\n", result.error); return false; }
        sm_result_free(&result);
    }
    return programs.size() == 10;
}
int main(int argc, char **argv) {
    if (argc != 3) return 2;
    bool control = !strcmp(argv[2], "control");
    bool lamp_control = !strcmp(argv[2], "original-lamp");
    FILE *file = fopen(argv[1], "rb"); if (!file) return 2;
    fseek(file, 0, SEEK_END); size_t size = ftell(file); rewind(file);
    std::vector<uint32_t> blob((size+3)/4); if (fread(blob.data(), 1, size, file) != size) return 2; fclose(file);
    std::map<uint64_t, Program> lacquer, materials;
    if (!load(blob, size, 0, lacquer) || !load(blob, size, 1, materials)) return 2;
    std::map<uint64_t, Program> &tested = control ? lacquer : materials;
    unsigned checks[CLASSES] = {}, failures[CLASSES] = {}, exact = 0, differing = 0; bool ok = true;
    const float r0 = 2 * 0.0432f / 1.0432f;
    for (const Pair &p : pairs) {
        float shown[CLASSES][3] = {}, shown_t[3] = {};
        for (const Record &m : records) {
            if (lamp_control && m.kind != BRAKE_GLASS) continue;
            int n = 0;
            for (float nv : {1.0f, 0.3f, 0.0f}) {
                const float x5 = std::pow(1 - nv, 5.0f), gate = nv < 0.15f ? p.grazing_gate : 1;
                const bool glass = m.kind == GLASS || m.kind == CLEAR_GLASS || m.kind == BRAKE_GLASS;
                const float coverage = glass ? 1.0f : 0.0f;
                if (m.kind == OTHER) {
                    for (int cube : {1, 2}) {
                        Colour a = shade(p, lacquer[p.vs], lacquer[p.ps], m, nv, cube, 1, &ok), b = shade(p, materials[p.vs], materials[p.ps], m, nv, cube, 1, &ok);
                        ++exact; if (memcmp(&a, &b, sizeof a)) { if (!differing) fprintf(stderr, "differs: %s %s\n", p.name, m.name); ++differing; }
                    }
                    ++n; continue;
                }
                Colour white = shade(p, tested[p.vs], tested[p.ps], m, nv, 1, coverage, &ok), black = shade(p, tested[p.vs], tested[p.ps], m, nv, 0, coverage, &ok);
                for (int k = 0; k < 3; ++k) {
                    float gain = (white.c[k] - black.c[k]) * (glass ? white.c[3] : 1), want = 0;
                    if (m.kind == PAINT || m.kind == WHEEL) want = 0.04f + 0.96f * x5;
                    if (m.kind == CHROME) want = 0.5545f + 0.4455f * x5;
                    if (m.kind == CHROME_PAINT) { float f0 = 0.5545f * std::fmin(m.vs[2][k], 1.0f); want = f0 + (1 - f0) * x5; }
                    if (glass) { float f = 0.0432f + 0.9568f * x5; want = 2 * f / (1 + f); }
                    want *= gate;
                    ++checks[m.kind]; if (!(std::fabs(gain - want) <= 0.05f * want)) ++failures[m.kind];
                    if (!k) shown[m.kind][n] = gain;
                }
                if (glass) {
                    float f = 0.0432f + 0.9568f * x5, r = 2 * f / (1 + f);
                    float t0 = m.kind == CLEAR_GLASS ? 0.75f : 1 - m.vs[0][3], want = t0 * (1 - r) / (1 - r0), got = 1 - white.c[3];
                    ++checks[m.kind]; if (!(std::fabs(got - want) <= 0.01f)) ++failures[m.kind];
                    if (m.kind == CLEAR_GLASS) shown_t[n] = got;
                }
                if (m.kind == BRAKE_GLASS) {
                    for (float a : {238.0f/255, 105.0f/255}) {
                        Colour w = shade(p, tested[p.vs], tested[p.ps], m, nv, 1, a, &ok);
                        Colour b = shade(p, tested[p.vs], tested[p.ps], m, nv, 0, a, &ok);
                        ++checks[m.kind];
                        if (std::fabs(w.c[3] - a) > 0.00001f) ++failures[m.kind];
                        float f = 0.0432f + 0.9568f * x5, want = 2*f/(1+f) * gate * a;
                        float got = (w.c[0] - b.c[0]) * w.c[3];
                        ++checks[m.kind];
                        if (std::fabs(got - want) > 0.05f * want) ++failures[m.kind];
                    }
                }
                ++n;
            }
        }
        printf("%-17s", p.name);
        for (int k = PAINT; k < CLASSES; ++k) printf(" %s %.4f/%.4f/%.4f", class_names[k], shown[k][0], shown[k][1], shown[k][2]);
        printf(" clear T %.3f/%.3f/%.3f\n", shown_t[0], shown_t[1], shown_t[2]);
    }
    if (!ok) return 2;
    unsigned total = 0, failed = 0;
    for (int k = PAINT; k < CLASSES; ++k) { total += checks[k]; failed += failures[k]; printf("  %-12s checks=%u failures=%u\n", class_names[k], checks[k], failures[k]); }
    printf("MATERIALS %s checks=%u failures=%u other-records=%u differing=%u\n", control ? "control" : lamp_control ? "original-lamp" : "patched", total, failed, exact, differing);
    return failed || differing ? 1 : 0;
}
'''

KINDS = (('CHROMEPAINT', 'CHROME_PAINT'), ('MATTEPAINT', 'OTHER'), ('REGPAINT', 'PAINT'), ('METPAINT', 'PAINT'),
         ('CANDYPAINT', 'PAINT'), ('IRIDPAINT', 'PAINT'), ('PEARLPAINT', 'PAINT'), ('MAGCHROME', 'CHROME'),
         ('MAGLIP', 'CHROME'), ('GRILLCHROME', 'CHROME'), ('MAGMET', 'WHEEL'), ('MAGSILVER', 'WHEEL'),
         ('WINDSHIELD_TINT', 'GLASS'), ('WINDOWMASK', 'GLASS'))
EXACT = {'CHROME': 'CHROME', 'WINDSHIELD': 'CLEAR_GLASS', 'BRAKELIGHTGLASS': 'BRAKE_GLASS'}


def records(data):
    """The 236-byte material records, as the constants FUN_0071E030 uploads."""
    found = []

    def walk(at, end):
        while at + 8 <= end:
            ident, size = struct.unpack_from('<II', data, at)
            if ident == 0x135200:
                found.append(data[at+8:at+8+size])
            elif ident & 0x80000000:
                walk(at + 8, at + 8 + size)
            at += 8 + size
    walk(0, len(data))
    rows = []
    for raw in found:
        if len(raw) != 236:
            raise RuntimeError(f'record size {len(raw)}')
        f = lambda offset: struct.unpack_from('<f', raw, offset)[0]
        name = raw[0x14:0x54].split(b'\0')[0].decode('ascii')
        kind = EXACT.get(name) or next((k for prefix, k in KINDS if name.startswith(prefix)), 'OTHER')
        dmin = [f(0x68 + 4*k) * f(0x64) for k in range(3)] + [f(0x84)]
        dmax = [f(0x78 + 4*k) * f(0x74) for k in range(3)] + [f(0x88)]
        emin = [f(0xc8 + 4*k) * f(0xc4) * 0.5 for k in range(3)]
        emax = [f(0xd8 + 4*k) * f(0xd4) * 0.5 for k in range(3)]
        inverse = lambda v: 1 / max(v, 1e-6)
        vs = [dmin, [b - a for a, b in zip(dmin, dmax)], emin + [0], [b - a for a, b in zip(emin, emax)] + [0],
              [f(0x54), f(0x8c), f(0xb8), 0], [f(0x58), f(0xbc), inverse(f(0x58)), inverse(f(0xbc))],
              [f(0x5c), f(0x90), f(0xe4), f(0xe8) - f(0xe4)]]
        rows.append((name, kind, vs, [f(0x60), f(0x94), f(0xc0), 0]))
    return rows


def table(rows):
    c = lambda values: '{' + ','.join(struct.unpack('<f', struct.pack('<f', v))[0].hex() + 'f' for v in values) + '}'
    lines = [f'{{"{name}", {kind}, {{{",".join(c(row) for row in vs)}}}, {c(vinyl)}}},' for name, kind, vs, vinyl in rows]
    return 'static const Record records[] = {\n' + '\n'.join(lines) + '\n};\n'


def run(command, *, expected=0, timeout=300):
    result = subprocess.run(list(map(str, command)), capture_output=True, text=True, timeout=timeout)
    if result.returncode != expected:
        raise RuntimeError(f'exit {result.returncode}, expected {expected}: {result.stdout[-1800:]} {result.stderr[-1800:]}')
    return (result.stdout + result.stderr).strip()


def main():
    image = HERE/'out/carbon/image.json'
    shaders = ROOT/'host/shaders'
    library = shaders/'build/libsmtranslate.a'
    if not image.is_file() or not library.is_file():
        print('SKIP: private outputs / translator absent'); return 3
    exe = Path(json.loads(image.read_text())['exe'])
    data = exe.parent/'GLOBAL/GLOBALB.BUN'
    if not exe.is_file() or not data.is_file():
        print('SKIP: private executable or data absent'); return 3
    switches = switch_registry(ROOT)
    assert switches is None or '\nNFS_CARBON_MATERIALS\tprivate\t1\t' in switches
    rows = records(data.read_bytes())
    counts = {}
    for _, kind, _, _ in rows:
        counts[kind] = counts.get(kind, 0) + 1
    assert len(rows) == 162 and counts == {'OTHER': 64, 'BRAKE_GLASS': 1, 'PAINT': 42, 'CHROME': 12, 'WHEEL': 9, 'GLASS': 25,
                                           'CLEAR_GLASS': 1, 'CHROME_PAINT': 8}, counts
    out = ignored_output(HERE/'out/carbon/materials_check')
    (out/'coat.inc').write_bytes((HERE/'private_runtime/carbon_coat.h').read_bytes())
    (out/'records.inc').write_text(table(rows))
    (out/'materials.cpp').write_text(HARNESS)
    binary = out/'materials'
    run(['clang++', '-std=c++17', '-O1', '-w', '-I', shaders, '-I', out, out/'materials.cpp',
         shaders/'tests/sm_interp.cpp', library, '-framework', 'Foundation', '-framework', 'Metal', '-o', binary])
    print(run([binary, exe, 'patched']))
    print(run([binary, exe, 'control'], expected=1))
    assert hashlib.sha256(ORIGINAL_GLASS.encode()).hexdigest() == ORIGINAL_GLASS_SHA256
    source = (out/'coat.inc').read_text()
    start = source.index('        CM_ADD, CM_D(8,7), CM_C(Pw,CM_A)')
    end = source.index('        CM_SLT, CM_D(11,8)', start)
    assert 'Brake-light cover:' in source[start:end]
    (out/'coat.inc').write_text(source[:start] + ORIGINAL_GLASS + source[end:])
    original = out/'original-materials'
    run(['clang++', '-std=c++17', '-O1', '-w', '-I', shaders, '-I', out, out/'materials.cpp',
         shaders/'tests/sm_interp.cpp', library, '-framework', 'Foundation', '-framework', 'Metal', '-o', original])
    print(run([original, exe, 'original-lamp'], expected=1))
    print('PRIVATE MATERIALS PASS')
    return 0


if __name__ == '__main__':
    sys.exit(main())
