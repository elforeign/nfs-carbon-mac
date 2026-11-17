"""Source-tree day colour on the world VS variant, interpreter only; no game.

The pinned retail programs are not in every tree, so a minimal vs_3_0 world
program (position, normal, one saturated colour write) runs the production
tail with the identity gate opened. Good: TREES PASS, 4 normals x 3 night
levels, tagged colour = 2 x (.13 + 1.2 x D x min(max(N.L,0) + .24, 1)) and
untagged (c251 = 0) equal to the trees-off variant on all four components:
120 checks, 0 failures, max error 6e-8. Broken controls fail: old variant on
the tagged draw (no tree branch): 24 failures, max error .71 (sun-facing R
.99 vs 1.70); wrap dropped: 18 failures, max error .346.
Default case: the switch reads On when unset, "on" or "1", Off for "0" and
"off": 5 cases, 0 failures; the old Off default (On only for on/1) fails 1 (unset).
Translator library absent: exit 3.
"""
from pathlib import Path
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
#include "variant.inc"
static unsigned checks, failures; static float max_error;
static void check(float got, float expected) {
    ++checks; float e = std::fabs(got-expected);
    if (!(e <= 2e-6f)) ++failures;
    if (e > max_error) max_error = e;
}
int main() {
    const uint32_t program[] = {
        0xfffe0300u,
        0x0200001fu, 0x80000000u, 0x900f0000u, /* dcl_position v0 */
        0x0200001fu, 0x80000003u, 0x900f0001u, /* dcl_normal v1 */
        0x0200001fu, 0x80000000u, 0xe00f0000u, /* dcl_position o0 */
        0x0200001fu, 0x8000000au, 0xe00f0001u, /* dcl_color o1 */
        0x02000001u, 0xe00f0000u, 0x90e40000u, /* mov o0, v0 */
        0x02000001u, 0xe0170001u, 0xa0e40000u, /* mov_sat o1.xyz, c0 (bake) */
        0x02000001u, 0xe0080001u, 0xa0e40001u, /* mov o1.w, c1 */
        0x0000ffffu };
    uint32_t count = sizeof program / 4, off_count = 0, on_count = 0;
    uint32_t *off = carbon_dn_world_variant(program, count, &off_count, 0);
    uint32_t *on = carbon_dn_world_variant(program, count, &on_count, TREES);
    if (!off || !on) { puts("variant declined"); return 2; }
    sm::Shader off_shader, on_shader;
    if (!sm::parse(off, off_count, off_shader) || !sm::parse(on, on_count, on_shader)) { puts("parse"); return 2; }
    SmOptions options; sm_default_options(&options);
    const float D[3] = {.6f,.48f,.22f}, normals[4][3] = {{0,0,1},{.6f,0,.8f},{0,1,0},{0,0,-1}};
    for (int n = 0; n < 4; ++n) for (float night : {0.0f, .5f, 1.0f}) for (int tagged : {0, 1}) {
        float c[256][4] = {};
        c[0][0] = .3f; c[0][1] = .4f; c[0][2] = .5f; c[1][3] = .7f;
        c[240][2] = 1; /* light along +z */
        c[241][0] = 1; c[241][1] = .8f; c[241][2] = .3f; c[241][3] = night;
        c[242][0] = .19f; c[242][1] = .24f; c[242][2] = .32f;
        if (tagged) {
            for (int k = 0; k < 3; ++k) { c[250][k] = 2*1.2f*D[k]; c[251][k] = 2*.13f; }
            c[250][3] = 1; c[251][3] = .24f;
        }
        int ci[16][4] = {}, cb[16] = {};
        interp::Context context; context.c = &c[0][0]; context.ci = &ci[0][0]; context.cb = cb; context.opt = options;
        interp::VSIn input = {};
        input.v[0] = {1, 2, 3, 1};
        input.v[1] = {normals[n][0], normals[n][1], normals[n][2], 0};
        interp::VSOut a = {}, b = {};
        if (!interp::run_vs(off_shader, context, input, a) || !interp::run_vs(on_shader, context, input, b)) { puts("run"); return 2; }
        float nl = fmaxf(0, normals[n][2]);
        for (int k = 0; k < 4; ++k) {
            float expected = a.col[0][k];
            if (tagged && k < 3) {
                float day = 2*(.13f + 1.2f*D[k]*fminf(nl+.24f, 1));
                float bake = fminf(1, fmaxf(0, c[0][k]));
                expected = night*bake + (1-night)*day;
            }
            check(b.col[0][k], expected);
        }
        check(b.pos[0], a.pos[0]);
    }
    printf("TREES checks=%u failures=%u max_error=%.6g\n", checks, failures, max_error);
    return failures ? 1 : 0;
}
'''


def run(command, expected):
    result = subprocess.run(list(map(str, command)), capture_output=True, text=True, timeout=180)
    if result.returncode != expected:
        raise RuntimeError(f'exit {result.returncode}, expected {expected}: {result.stdout[-1500:]} {result.stderr[-1500:]}')
    return (result.stdout + result.stderr).strip()


DEFAULT = r'''
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
static int carbon_dn_on(void) { return 1; }
#include "trees_on.inc"
int main(int argc, char **argv) {
    if (argc > 1) setenv("NFS_DAYNIGHT_TREES", argv[1], 1);
    printf("%d\n", carbon_dn_trees_on());
    return 0;
}
'''


def default_case(out, function):
    """Unset/on/1 read On, 0/off read Off; returns the failure count."""
    (out/'trees_on.inc').write_text(function)
    (out/'default.c').write_text(DEFAULT)
    binary = out/'default'
    run(['clang', '-O1', '-I', out, out/'default.c', '-o', binary], 0)
    expected = {None: '1', 'on': '1', '1': '1', '0': '0', 'off': '0'}
    return sum(run([binary] + ([value] if value is not None else []), 0) != want
               for value, want in expected.items())


def main():
    shaders = ROOT/'host/shaders'
    library = shaders/'build/libsmtranslate.a'
    if not library.exists():
        print('SKIP: shader translator library absent'); return 3
    source = (HERE/'private_runtime/carbon_daynight_shader.h').read_text()
    gate = '        default: return NULL;\n    }\n    if (count < 4'
    assert source.count(gate) == 1
    opened = source.replace(gate, '        default: break;\n    }\n    if (count < 4')
    controls = {
        'good': (opened, 1, 0),
        'old-variant': (opened, 0, 1),
        'no-wrap': (opened.replace('0x03000002u, 0x8001000au, 0x8000000au, 0xa0ff00fbu',
                                   '0x03000002u, 0x8001000au, 0x8000000au, 0xa0ff00f0u'), 1, 1),
    }
    out = ignored_output(HERE/'out/carbon/daynight_trees_check')
    unit = (HERE/'private_runtime/carbon_daynight.h').read_text()
    start = unit.index('static int carbon_dn_trees_on(void) {')
    function = unit[start:unit.index('\n}\n', start) + 3]
    on_rule = '!(setting && (!strcmp(setting,"0") || !strcasecmp(setting,"off")))'
    assert function.count(on_rule) == 1
    failures = default_case(out, function)
    old_default = default_case(out, function.replace(
        on_rule, 'setting && (!strcmp(setting,"1") || !strcasecmp(setting,"on"))'))
    print(f'default: failures={failures}; old Off default: failures={old_default}')
    if failures or old_default != 1:
        print('PRIVATE DAYNIGHT TREES FAIL: default'); return 1
    (out/'trees.cpp').write_text(HARNESS)
    for name, (text, trees, expected) in controls.items():
        (out/'variant.inc').write_text(text)
        binary = out/name
        run(['clang++', '-std=c++17', '-O1', f'-DTREES={trees}', '-I', shaders, '-I', out, out/'trees.cpp',
             shaders/'tests/sm_interp.cpp', library, '-framework', 'Foundation', '-framework', 'Metal',
             '-o', binary], 0)
        print(name + ': ' + run([binary], expected))
    print('PRIVATE DAYNIGHT TREES PASS')
    return 0


if __name__ == '__main__':
    sys.exit(main())
