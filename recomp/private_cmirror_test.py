"""Carbon rear-view mirror target: texels per screen pixel of the mirror quad (production sizing).

3840x2160 (retail target 1024x512): port 1260x630 = 1.08 x 1.00 texels per pixel; retail size 0.88 x 0.81 (exit 1).
The quad comes from the decoded composite vertices (x +/-0.40625, y .629166722...920833349 of the 4:3 canvas,
the middle half of the target's height sampled), independently of the provider's front-end-unit constants.

Gameplay Rearview Mirror On clears AB0B98 before mirror view setup and registers admitted 32 px
scenery at model slot +0x30. Bypassing the providers leaves AB0B98 = 1 and selects +0x34.
The depth-only clear happens after the sky flush, with the mirror target active.
The native profile option is live, and other views retain their original setup.

Casino Town at simulation tick 1440, 3840x2160, native Mirror On: 2,779 depth-tested City Hall
lower-wall pixels in the fixed mirror crop and 0 in the deliberately broken retail render.
The count compares each resolved target with a same-frame replay omitting the grey-brick
walls and door submesh where present. The middle half of each target is resampled to the
1170x315 aperture before comparing RGB. Repeating the full pass was pixel-identical.
Submission 0x01 at 0079AFA0 produced the same image as 0x81. The sky dome wrote depth before
the walls drew. Clearing only that depth after 0072E070 kept the sky colour and restored
the lower walls seen in the reverse-heading main view. Native Off gave 0 mirror draws and
0 composites.

NFS_MIRROR_VIEW=60 at 3840x2160 shows 3.714:1 in a 3.714:1 quad (error 0.0 %). The retail
projection (m00 1.2502, m11 2.5075) shows 4.011:1 (error 8.0 %, exit 1).
"""
from pathlib import Path
import hashlib
import json
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
PRIVATE = HERE / 'private_runtime'
sys.path.insert(0, str(HERE))
from private_render import body


def main():
    source = (PRIVATE / 'carbon_mirror.c').read_text()
    hooks = json.loads((PRIVATE / 'hooks/mirror.json').read_text())['hooks']
    assert [(h['address'], h['provider']) for h in hooks] == [('0070DAB0', 'carbon_mirror_allocate'),
        ('0072E070', 'carbon_mirror_view_setup'), ('0070F2F0', 'carbon_mirror_projection'),
        ('0079AE80', 'carbon_mirror_register_scenery')]
    feature = json.loads((PRIVATE / 'features/mirror.json').read_text())
    assert feature['bindings']['carbon_mirror.c']['sha256'] == hashlib.sha256(source.encode()).hexdigest()
    sizing = body(source, 'carbon_mirror_size')
    fixture = r'''
#include <math.h>
#include <stdint.h>
#include <stdio.h>
static void carbon_mirror_size(uint32_t bw, uint32_t bh, uint32_t w0, uint32_t h0, int pct,
                               uint32_t *w, uint32_t *h) ''' + sizing + r'''
static uint32_t retail(uint32_t v) { uint32_t p = 1; while (p * 2 <= v / 3) p *= 2; return p; }  // 0070DAB0
int main(int argc, char **argv) {
    (void)argv;
    static const uint32_t out[][2] = {{3840,2160},{2560,1440},{1920,1080},{1280,1024},{1024,768},{3440,1440},{1280,720}};
    double worst = 9;
    for (unsigned i = 0; i < sizeof out / sizeof *out; ++i) {
        uint32_t bw = out[i][0], bh = out[i][1], w0 = retail(bw), h0 = retail(bh), w = w0, h = h0;
        if (argc < 2) carbon_mirror_size(bw, bh, w0, h0, 100, &w, &h);
        double canvas = bh * 4.0 / 3.0 < bw ? bh * 4.0 / 3.0 : bw;
        double qw = .40625 * canvas, qh = (.920833349 - .629166722) / 2 * bh;
        double tx = w / qw, ty = h / 2.0 / qh;
        if (bw == 3840) printf("3840x2160: target %ux%u, texels per pixel %.2f x %.2f\n", w, h, tx, ty);
        if (tx < worst) worst = tx;
        if (ty < worst) worst = ty;
        if (w < w0 || h < h0 || (uint64_t)w * h0 != (uint64_t)h * w0) return 2;   // never smaller, aspect kept
        if (argc < 2 && w > w0 && (tx < ty ? tx : ty) > 1.01) return 3;         // the smallest factor that covers
        uint32_t pw, ph;
        carbon_mirror_size(bw, bh, w0, h0, 0, &pw, &ph);                       // pc: retail
        if (pw != w0 || ph != h0) return 4;
    }
    printf("worst texels per pixel %.3f\n", worst);
    return worst < .999 ? 1 : 0;
}
'''
    with tempfile.TemporaryDirectory(prefix='private-cmirror-') as td:
        path = Path(td) / 'fixture.c'
        binary = Path(td) / 'fixture'
        path.write_text(fixture)
        subprocess.run(['clang', '-O1', '-Wall', '-Wextra', '-Werror', str(path), '-o', str(binary)], check=True)
        for name, args, expected in [('port', [], 0), ('retail', ['retail'], 1)]:
            r = subprocess.run([str(binary), *args], capture_output=True, text=True)
            print(name + ': ' + r.stdout.strip().replace('\n', '; ') + ' exit=' + str(r.returncode))
            assert r.returncode == expected, (name, r.returncode)
    detail(source)
    native_option(source)


DETAIL = r'''
#include <math.h>
#include <stdint.h>
#include <stdio.h>
static void carbon_mirror_view_matrix(float hfov, float aspect, float *m00, float *m11) MATRIX
int main(int argc, char **argv) {
    (void)argv;
    double canvas = 2160 * 4.0 / 3.0, qa = (.40625 * canvas) / ((.920833349 - .629166722) / 2 * 2160);
    float m00 = 1.2502f, m11 = 2.5075f;                     /* retail, live diag */
    if (argc == 1) carbon_mirror_view_matrix(60.0f, (float)qa, &m00, &m11);
    double shown = (2.0 / m00) / (1.0 / m11), err = fabs(shown / qa - 1.0);
    printf("view: shown %.3f:1 in a %.3f:1 quad, error %.1f %%, %.1f deg across\n", shown, qa, err * 100, 2 * atan(1 / m00) * 180 / M_PI);
    return err > .001;
}
'''


def detail(source):
    fixture = DETAIL.replace('MATRIX', body(source, 'carbon_mirror_view_matrix'))
    with tempfile.TemporaryDirectory(prefix='private-cmirror-') as td:
        for name, text, args, expected in [('view 60', fixture, [], 0), ('retail view', fixture, ['retail'], 1)]:
            path, binary = Path(td) / 'detail.c', Path(td) / 'detail'
            path.write_text(text)
            subprocess.run(['clang', '-O1', '-Wall', '-Wextra', '-Werror', str(path), '-o', str(binary)], check=True)
            r = subprocess.run([str(binary), *args], capture_output=True, text=True)
            print(name + ': ' + r.stdout.strip().replace('\n', '; ') + ' exit=' + str(r.returncode))
            assert r.returncode == expected, (name, r.returncode)


NATIVE_OPTION = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#define CARBON_MIRROR_VIEW 0x00B4B090u
#define CARBON_ACTIVE_TARGET 0x00AB08F4u
#define CARBON_MIRROR_TARGET 0x00AB0540u
#define CARBON_DEVICE 0x00AB0ABCu
#define CARBON_LOWLOD_PASS 0x00AB0B98u
#define CARBON_PROFILE_MANAGER 0x00A97A7Cu
typedef struct { uint32_t esp; } Cpu;
static uint32_t guest[CARBON_PROFILE_MANAGER / 4 + 0x60000];
#define M32(address) guest[(address) / 4]
#define M8(address) ((uint8_t *)guest)[address]
static int diag_on;
#define diag_event(...) ((void)0)
static uint32_t setup_flag, registered_flags, setup_calls, clears;
static uint32_t call_guest(Cpu *c, uint32_t address, int argc, uint32_t *args) {
    (void)c;
    assert(address == 0x800 && argc == 7);
    assert(setup_calls == 2);
    assert(args[0] == 0x600 && args[1] == 0 && args[2] == 0);
    assert(args[3] == 2 && args[4] == 0 && args[5] == 0x3f800000u && args[6] == 0);
    ++clears;
    return 0;
}

static int carbon_mirror_enabled(void) ENABLED
void carbon_mirror_view_setup(Cpu *c, void (*original)(Cpu *)) SETUP
void carbon_mirror_register_scenery(Cpu *c, void (*original)(Cpu *)) SCENERY

static void setup(Cpu *c) {
    (void)c;
    ++setup_calls;
    setup_flag = M32(CARBON_LOWLOD_PASS);  /* 0072E070 may flush the sky here. */
}

static void register_view(Cpu *c) {
    /* 0079AE80's type-3 branch adds 0x58. It is a thiscall with two args. */
    registered_flags = M32(c->esp + 8) | (M32(c->esp + 4) == CARBON_MIRROR_VIEW ? 0x58 : 0x18);
    c->esp += 12;
}

static int selected_lod(uint32_t flags, unsigned pixels, uint32_t instance_flags) {
    /* 0079FAD5..0079FADD and 0079FB57..0079FBB9 for ordinary mirror scenery. */
    if (((instance_flags ^ 0xffffffc0u) & flags & 0x80000ffu) || pixels < 32) return -1;
    return flags & 0x3000u ? 0x34 : 0x30;
}

int main(void) {
    const uint32_t manager = 0x200, profiles = 0x400, profile = 0x500, stack = 0x100;
    Cpu cpu = {.esp = stack};
    M32(stack + 4) = CARBON_MIRROR_VIEW;
    M32(stack + 8) = 0x2000;
    M32(CARBON_LOWLOD_PASS) = 1;
    M32(CARBON_ACTIVE_TARGET) = CARBON_MIRROR_TARGET;
    M32(CARBON_DEVICE) = 0x600;
    M32(0x600) = 0x700;
    M32(0x700 + 0xac) = 0x800;
    carbon_mirror_view_setup(&cpu, setup);
    if (setup_flag != 1 || clears) return 2; /* the profile manager is not active yet */

    M32(CARBON_PROFILE_MANAGER) = manager;
    M32(manager + 0xd4) = profiles;
    M32(profiles) = profile;
    M8(profile + 0x24209) = 1;
    carbon_mirror_view_setup(&cpu, setup);
    carbon_mirror_register_scenery(&cpu, register_view);
    int slot = selected_lod(registered_flags, 32, 0x40);
    printf("mirror On: setup flag %u, scenery model slot +0x%x, depth clears %u\n", setup_flag, slot, clears);
    if (setup_flag || slot != 0x30 || clears != 1) return 1;
    if (cpu.esp != stack + 12 || M32(stack + 8) != 0x2000) return 4;
    if (selected_lod(registered_flags, 31, 0x40) != -1 ||
        selected_lod(registered_flags, 32, 0) != -1) return 5;

    M8(profile + 0x24209) = 0;
    M32(CARBON_LOWLOD_PASS) = 1;
    cpu.esp = stack;
    carbon_mirror_view_setup(&cpu, setup);
    carbon_mirror_register_scenery(&cpu, register_view);
    if (setup_flag != 1 || selected_lod(registered_flags, 32, 0x40) != 0x34 || clears != 1) return 6;

    M8(profile + 0x24209) = 1;
    M32(stack + 4) = 0x00B4BA10u;
    cpu.esp = stack;
    carbon_mirror_view_setup(&cpu, setup);
    carbon_mirror_register_scenery(&cpu, register_view);
    if (setup_flag != 1 || registered_flags != 0x2018 || clears != 1) return 7;

    M32(stack + 4) = CARBON_MIRROR_VIEW;
    M32(CARBON_ACTIVE_TARGET) = 0;
    cpu.esp = stack;
    carbon_mirror_view_setup(&cpu, setup);
    if (setup_flag != 0 || clears != 1) return 8;
    return 0;
}
'''


def native_option(source):
    fixture = NATIVE_OPTION.replace('ENABLED', body(source.split('void carbon_mirror_view_setup', 1)[0],
                                                       'carbon_mirror_enabled'))
    setup = body(source, 'carbon_mirror_view_setup')
    scenery = body(source, 'carbon_mirror_register_scenery')
    with tempfile.TemporaryDirectory(prefix='private-cmirror-option-') as td:
        path, binary = Path(td) / 'option.c', Path(td) / 'option'
        for name, view, lod, expected in [
            ('HD', setup, scenery, 0),
            ('depth clear skipped', setup.replace('if (device &&', 'if (0 && device &&'), scenery, 1),
            ('retail', setup.replace('M32(CARBON_LOWLOD_PASS) = 0;', '').replace(
                'if (device &&', 'if (0 && device &&'), '{ original(c); }', 1),
        ]:
            path.write_text(fixture.replace('SETUP', view).replace('SCENERY', lod))
            subprocess.run(['clang', '-O1', '-Wall', '-Wextra', '-Werror', str(path), '-o', str(binary)], check=True)
            result = subprocess.run([str(binary)], capture_output=True, text=True)
            print(f'{name}: {result.stdout.strip()} exit={result.returncode}')
            assert result.returncode == expected


if __name__ == '__main__':
    main()
