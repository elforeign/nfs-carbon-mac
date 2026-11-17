"""Native wide projection, front-end geometry and cursor; no game/GPU.

Runs the translated originals 004A4770 (option 13BE getter) and 00731580
(cursor) under game_widescreen.h's hooks, the selected CTAB matrix packing
of d3dx_effect.c and the selected fixed-function constants of render.m.
Premise: before this change game_widescreen.h and the front-end seams were
empty, so 13BE returned the profile byte (0) at every output and FE kx was 1.
IDI_FE_FX / IDI_FE_MASK_FX declare WorldViewProj c0-c3 as MATRIX_COLUMNS and
their vertex shaders start `dp4 oPos.x, v0, c0`, which this fixture executes.
Good: 1920x1080 and 3840x2160 -> 13BE=1, kx=0.75 (1e-6), FE clip x scaled by
kx, y unchanged; cursor inverse within 1 FE unit with consistent delta;
1440x1080 and 640x480 -> getter and cursor byte-identical to the originals.
Aspect change 16:9 -> 4:3 -> 16:9 resends NORMAL_MODE / WIDESCREEN_MODE to both
packages once each. Broken (each exit 1): fixed mask (no FF scale), row
instead of column packing, aspect change without the resend.
Camera: executes pinned 0071B780, 0070F2F0, 0070F2A0, 0046DC30/0046DCF0,
0087EAC0 and the production callback. 3276 viewport cases cover 28 view types,
3 FOVs and 3 x87 precision modes at 4:3, 16:9, 21:9 and narrower outputs.
Good max coefficient/plane error=5.96046448e-8 (<1e-5); 252 road reflections
use output aspect, 252 subviews and all <=4:3 builds stay byte-identical.
Original retail and biased-retail mutants: error=0.147983313 (exit 1);
unscaled pixels-per-unit: error=115.427002 (exit 1); fixing 4:3 changes m00
from 1.9237833 to 1.44283748 (exit 1). Subview-wide and reflection-retail
scope mutants also exit 1. The diagnostic-only production code failed.
Fragments are SHA-256 pinned. Exit 3 without Carbon generated outputs.
"""
from pathlib import Path
import hashlib
import json
import re
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
PRIVATE = HERE / 'private_runtime'
sys.path.insert(0, str(PRIVATE))
from layers import selected_source

FRAGMENTS = {'004A4770': '34c5aee22ba6ccec8d6f80fc55ce61128ea1108bbee9bf0a2c1306a5db0eb6d6', '00731580': 'b81c9d9f571b6bd723b03320d444bdcb29904e6e121ea2fa416615604ed8ed98'}


CAMERA_FRAGMENTS = {'0071B780': '6d20562933c35d25bdc13b7da7c231d1123fdd24683185968cc23a2f1189edc8', '0046DC30': '9c33b7a934ed2388ac7e4f04e631eb7b2bdf544d6d6b3db040ba94c7f0883c6d', '0046DCF0': 'dd2585a6e725ff7594a7e76128d1ad729489863b9ee78017094ff23910bc40cb', '0070F2A0': '20361827c9369c310ff1f52919b5d0dd9a3bdaf867fbf907eedfa4b44c0dec29', '0070F2F0': '9128dac145cdca4223c058a472bffad42e93dd2a3d5fcbac93e3c5a3cb4ade2a', '0087EAC0': '613c584ed1cb82b7014a6eca36763dae6aec8f78e3feb2d21d5d02ee0a30312c'}

def original(address):
    for path in (HERE / 'out/carbon-base').glob('NFSC_*.c'):
        source = path.read_text()
        match = re.search(r'void (?:f_|carbon_orig_)' + address + r'\(Cpu [^)]*\)\s*\{', source)
        if match:
            fragment = source[match.start():source.index('\n}', match.end()) + 2]
            fragment = re.sub(r'void (?:f_|carbon_orig_)' + address, 'void native_' + address, fragment, count=1)
            assert hashlib.sha256(fragment.encode()).hexdigest() == (FRAGMENTS | CAMERA_FRAGMENTS)[address], (
                address, hashlib.sha256(fragment.encode()).hexdigest())
            return fragment
    raise AssertionError('missing translated original ' + address)


def between(text, start, end):
    begin = text.index(start)
    return text[begin:text.index(end, begin)]


HARNESS = r'''
#include "host.h"
#include <stdlib.h>
#include <math.h>
uint8_t *G;
#define CHECK(x) do { if (!(x)) { fprintf(stderr,"WIDE CHECK %d: %s\n",__LINE__,#x); exit(1); } } while(0)
static uint32_t mode_w = 640, mode_h = 480;
void widescreen_mode(int i, uint32_t *w, uint32_t *h) { (void)i; *w = mode_w; *h = mode_h; }
static unsigned sends; static uint32_t sent_hash[16], sent_package[16], sent_this[16];
static uint32_t text_hash(uint32_t text) { return 0x11110000u ^ text; }
uint32_t call_guest(Cpu *c, uint32_t fn, int n, const uint32_t *a) {
    if (fn == 0x005EA6A0u) { CHECK(n == 1); return text_hash(a[0]); }
    CHECK(fn == 0x005F2960u && n == 5 && sends < 16);
    CHECK(a[1] == 0 && a[3] == 0xFFFFFFFCu && a[4] == 0);
    sent_hash[sends] = a[0]; sent_package[sends] = a[2]; sent_this[sends] = c->ecx; ++sends;
    return 0;
}
#include "game_widescreen.h"
static unsigned carbon_mode_index(void) { return 0; }
/* Selected CTAB matrix packing (d3dx_effect.c) with the front-end seam. */
enum { PC_SCALAR, PC_VECTOR, PC_MATRIX_ROWS, PC_MATRIX_COLUMNS };
typedef struct { char name[64]; uint32_t cls, rows, cols; } Param;
static float source_matrix[16];
static void get_matrix(Param *q, float *m, int t) { (void)q; (void)t; memcpy(m, source_matrix, 64); }
static uint32_t pack(Param *q, uint16_t ccls, float regs[256][4]) {
    uint32_t nreg = 0, nmax = 4;
    memset(regs, 0, 16 * 4);
    for (int once = 0; once < 1; ++once) {
PACKING
    }
    return nreg;
}
/* Selected fixed-function constants (render.m) with the front-end seam. */
static struct { float transform[512][16]; uint32_t viewport[6]; } dev;
static void ff_constants(int has_pos_t, float vsc[8][4]) {
FIXED
}
/* Translated originals and their callees. */
void f_00572B90(Cpu *c) { c->eax = 0x200000; c->esp += 8; }
void f_0087EAC0(Cpu *c) { c->eax = (uint32_t)(int32_t)ST(0); x87_pop(c); c->esp += 4; }
static int32_t screen_x, screen_y, client_w, client_h;
void host_import(Cpu *c, uint32_t slot) {
    uint32_t a1 = M32(c->esp + 4), a2 = M32(c->esp + 8);
    if (slot == 0x009C1458u) { M32(a1) = (uint32_t)screen_x; M32(a1 + 4) = (uint32_t)screen_y; c->esp += 8; }
    else {
        CHECK(slot == 0x009C143Cu || slot == 0x009C1440u);
        M32(a2) = 0; M32(a2 + 4) = 0; M32(a2 + 8) = (uint32_t)client_w; M32(a2 + 12) = (uint32_t)client_h; c->esp += 12;
    }
    c->eax = 1;
}
ORIGINALS
static Cpu initial(void) { Cpu c = {0}; c.esp = 0x10000; c.ebx = 7; c.esi = 8; c.edi = 9; c.ebp = 10; M32(c.esp) = 0xFEED; return c; }
static void output(uint32_t w, uint32_t h) { M32(0x00AB06FCu) = w; M32(0x00AB0700u) = h; client_w = (int32_t)w; client_h = (int32_t)h; }
static uint32_t getter(int hooked, uint8_t profile) {
    M8(0x200000 + 0x241F4) = profile;
    Cpu n = initial(); M32(n.esp + 4) = 0x3004; M32(0x3004) = 0xA5A5A5A5u;
    native_004A4770(&n);
    CHECK(M32(0x3004) == profile);
    Cpu c = initial(); M32(c.esp + 4) = 0x3000; M32(0x3000) = 0xA5A5A5A5u;
    if (hooked) carbon_wide_option(&c, native_004A4770); else native_004A4770(&c);
    CHECK(c.esp == n.esp && c.esp == 0x10008 && (c.eax & 0xFF) == 1);
    return M32(0x3000);
}
static void cursor(int hooked, int32_t x, int32_t y, uint32_t self) {
    screen_x = x; screen_y = y;
    Cpu c = initial(); c.ecx = self;
    if (hooked) carbon_wide_cursor(&c, native_00731580); else native_00731580(&c);
    CHECK(c.esp == 0x10004);
}
static void cursor_same_as_original(void) {
    for (int32_t x = 0; x <= client_w; x += 37) {
        cursor(0, x, client_h / 3, 0x5000); cursor(1, x, client_h / 3, 0x6000);
        CHECK(!memcmp(G + 0x5004, G + 0x6004, 0x18));
    }
}
static float clip_x(const float regs[256][4], const float v[4]) {   /* dp4 oPos.x, v0, c0 */
    return regs[0][0] * v[0] + regs[0][1] * v[1] + regs[0][2] * v[2] + regs[0][3] * v[3];
}
static float clip_y(const float regs[256][4], const float v[4]) {
    return regs[1][0] * v[0] + regs[1][1] * v[1] + regs[1][2] * v[2] + regs[1][3] * v[3];
}
static void wide(uint32_t w, uint32_t h) {
    output(w, h);
    float kx = carbon_fe_kx();
    CHECK(fabsf(kx - 0.75f) < 1e-6f);
    CHECK(getter(1, 0) == 1 && getter(1, 1) == 1 && getter(0, 0) == 0);
    /* Front-end WorldViewProj, as the game sets it: 640x480 units to clip space. */
    float m[16] = {1.0f / 320, 0, 0, 0,  0, -1.0f / 240, 0, 0,  0, 0, 1, 0,  -1, 1, 0, 1};
    memcpy(source_matrix, m, 64);
    Param q = {"WorldViewProj", PC_MATRIX_COLUMNS, 4, 4};
    float regs[256][4], plain[256][4];
    carbon_fe_scope = 0; CHECK(pack(&q, PC_MATRIX_COLUMNS, plain) == 4);
    carbon_fe_scope = 1; CHECK(pack(&q, PC_MATRIX_COLUMNS, regs) == 4);
    for (int i = 0; i <= 8; ++i) {
        float v[4] = {80.0f * i, 60.0f * i, 0.5f, 1};
        CHECK(fabsf(clip_x(regs, v) - kx * clip_x(plain, v)) < 1e-5f);
        CHECK(fabsf(clip_y(regs, v) - clip_y(plain, v)) < 1e-5f);
    }
    Param other = {"cvTextureOffset", PC_MATRIX_COLUMNS, 4, 4};
    pack(&other, PC_MATRIX_COLUMNS, regs); CHECK(!memcmp(regs, plain, 16 * 4));
    carbon_fe_scope = 0;
    /* Fixed-function pass of the mask effect (XYZ) and a pretransformed quad. */
    for (int i = 0; i < 512; ++i) for (int k = 0; k < 16; ++k) dev.transform[i][k] = k % 5 == 0;
    memcpy(dev.transform[3], m, 64);
    float vsc[8][4], base[8][4];
    for (int t = 0; t < 2; ++t) {
        dev.viewport[2] = w; dev.viewport[3] = h; float one = 1; memcpy(&dev.viewport[5], &one, 4);
        carbon_fe_scope = 0; ff_constants(t, base);
        carbon_fe_scope = 1; ff_constants(t, vsc);
        for (int k = 0; k < 4; ++k) { CHECK(fabsf(vsc[0][k] - kx * base[0][k]) < 1e-6f); CHECK(vsc[1][k] == base[1][k]); }
    }
    carbon_fe_scope = 0;
    /* Cursor: a target drawn at FE x lands at screen x; the inverse returns it. */
    for (int target = 0; target <= 640; target += 20) {
        int32_t sx = (int32_t)lrintf((float)w / 2 + (target - 320) / 320.0f * kx * (float)w / 2);
        cursor(1, sx, (int32_t)h / 2, 0x6000);
        int32_t fe = (int32_t)M32(0x6004), previous = (int32_t)M32(0x600C);
        CHECK(abs(fe - target) <= 1);
        CHECK((int32_t)M32(0x6014) == fe - previous);
        CHECK(abs((int32_t)M32(0x6008) - 240) <= 1);
    }
}
int main(int argc, char **argv) {
    CHECK(argc == 2); G = calloc(1, 0xC00000); CHECK(G);
    FILE *image = fopen(argv[1], "rb"); CHECK(image && fread(G, 1, 0xC00000, image) == 0xC00000); fclose(image);
    CHECK(!strcmp((char *)G + 0x009D4B98, "WIDESCREEN_MODE") && !strcmp((char *)G + 0x009D4B8C, "NORMAL_MODE"));
    CHECK(!strcmp((char *)G + 0x009D4B78, "WIDESCREEN_MODEHUD") && !strcmp((char *)G + 0x009D4B68, "NORMAL_MODEHUD"));
    /* Native package list: manager -> object; object +E0 first package, +4 next. */
    M32(0x00A97A78u) = 0x300000; M32(0x300000) = 0x310000; M32(0x3100E0) = 0x320000;
    M32(0x320004) = 0x320100; M32(0x320104) = 0; M32(0x00A99BBCu) = 3;
    /* 4:3 and narrower: exactly the originals. */
    output(1440, 1080); CHECK(carbon_fe_kx() == 1.0f);
    CHECK(getter(1, 0) == getter(0, 0)); cursor_same_as_original();
    output(640, 480); CHECK(carbon_fe_kx() == 1.0f); cursor_same_as_original();
    output(0, 0); mode_w = 1280; mode_h = 720; CHECK(fabsf(carbon_fe_kx() - 0.75f) < 1e-6f);   /* before the device */
    wide(1920, 1080);
    wide(3840, 2160);
    /* Aspect change: the native mode messages are sent again, once per package. */
    unsigned before = sends;
    output(1920, 1080); getter(1, 0); getter(1, 0); CHECK(sends == before);
    output(1440, 1080); getter(1, 0); getter(1, 0);
    CHECK(sends == before + 2);
    CHECK(sent_hash[before] == text_hash(0x009D4B8Cu) && sent_package[before] == 0x320000 && sent_package[before + 1] == 0x320100);
    CHECK(sent_this[before] == 0x310000);
    M32(0x00A99BBCu) = 6; output(3840, 2160); getter(1, 0);
    CHECK(sends == before + 4 && sent_hash[before + 2] == text_hash(0x009D4B78u));
    puts("WIDE PASS 13BE=1@16:9 kx=0.75 FE-columns=1 FF=2 cursor=33x2 4:3-identical=2 resend=2+2");
    free(G); return 0;
}
'''


CAMERA_HARNESS = r'''
#include "host.h"
#include <math.h>
#include <stdlib.h>
#include <stdarg.h>
uint8_t *G;
int diag_on;
void diag_event(const char *fmt, ...) { (void)fmt; }
#define CHECK(x) do { if (!(x)) { fprintf(stderr,"CAMERA CHECK %d: %s\n",__LINE__,#x); exit(1); } } while(0)
#include "game_camera_wide.h"
ORIGINALS
/* Native camera transform is identity here; all projection/frustum code runs. */
void f_0044B400(Cpu *c) {
    uint32_t out = M32(c->esp + 4);
    for (unsigned i = 0; i < 16; ++i) MF32(out + 4*i) = i % 5 == 0;
    c->esp += 4;
}
static int corrected;
static uint16_t control_word;
void f_0086B296(Cpu *c) {
    uint32_t out = M32(c->esp + 4), a = M32(c->esp + 8), b = M32(c->esp + 12);
    CHECK(M32(c->esp) == 0x0071B99Du || M32(c->esp) == 0x0071BB9Fu);
    Cpu before = *c;
    if (corrected) widescreen_projection(c, b);
    CHECK(!memcmp(&before, c, sizeof before));
    float product[16];
    for (unsigned i = 0; i < 4; ++i) for (unsigned j = 0; j < 4; ++j) {
        double sum = 0;
        for (unsigned k = 0; k < 4; ++k) sum += MF32(a + 16*i + 4*k) * MF32(b + 16*k + 4*j);
        product[4*i+j] = (float)sum;
    }
    memcpy(G + out, product, sizeof product); c->eax = out; c->esp += 16;
}
uint32_t call_guest(Cpu *c, uint32_t fn, int n, const uint32_t *args) {
    uint32_t sp = c->esp;
    CHECK(n == 1);
    c->esp -= 8; M32(c->esp) = 0xFEEDF00D; M32(c->esp+4) = args[0];
    if (fn == 0x0046DC30u) f_0046DC30(c);
    else { CHECK(fn == 0x0046DCF0u); f_0046DCF0(c); }
    c->esp = sp; return c->eax;
}
typedef struct { float primary[16], biased[16], product[16], planes[24], ppu; } Result;
static Result build(int fix, uint32_t view, unsigned type, unsigned width, unsigned height, unsigned vw, unsigned vh, unsigned fov) {
    M32(0x00AB06FCu) = M32(0x00AB0AC8u) = width;
    M32(0x00AB0700u) = M32(0x00AB0ACCu) = height;
    M32(view + 8) = type; M32(view + 0x40) = 0x200000; M32(view + 0x50) = 0x210000;
    M32(0x210014) = vw; M32(0x210018) = vh;
    MF32(0x2000D4) = 0.5f; MF32(0x2000D8) = 10000;
    M16(0x2000E4) = fov;
    memset(G + 0x300000, 0xA5, 0x280);
    Cpu c = {0}; c.esp = 0x10000; c.ecx = 0x300000; c.ebp = 0x1234; c.cw = control_word;
    M32(c.esp) = 0xFEED; M32(c.esp + 4) = view;
    M32(c.esp + 8) = M32(c.esp + 12) = 0; M32(c.esp + 16) = 0; M32(c.esp + 20) = 1;
    corrected = fix;
    carbon_camera_setup(&c, native_0071B780);
    CHECK(c.esp == 0x10018 && c.ebp == 0x1234 && !carbon_camera_view);
    Result r;
    memcpy(r.primary, G + 0x300040, 64); memcpy(r.biased, G + 0x3000C0, 64);
    memcpy(r.product, G + 0x300080, 64); memcpy(r.planes, G + 0x300140, 96);
    r.ppu = MF32(view + 0x10); return r;
}
static float worst;
static void near(float a, float b) {
    float error = fabsf(a-b); if (error>worst) worst=error;
    if (error >= 1e-5f) fprintf(stderr,"camera actual=%.9g expected=%.9g error=%.9g\n",a,b,error);
    CHECK(error < 1e-5f);
}
int main(int argc, char **argv) {
    CHECK(argc == 2); G = calloc(1, 0xC00000); CHECK(G);
    FILE *image = fopen(argv[1], "rb"); CHECK(image && fread(G, 1, 0xC00000, image) == 0xC00000); fclose(image);
    unsigned cases = 0;
    for (unsigned precision = 0; precision < 3; ++precision) {
    control_word = precision == 0 ? 0x007F : precision == 1 ? 0x027F : 0x037F;
    for (unsigned type = 0; type <= 27; ++type) for (unsigned fov = 10000; fov <= 20000; fov += 5000) {
        Result control = build(0, 0x00B4AF90u, type, 1440,1080,1440,1080,fov);
        for (unsigned width = 1080; width <= 2520; width += 120) {
            Result retail = build(0,0x00B4AF90u,type,width,1080,width,1080,fov);
            Result fixed = build(1,0x00B4AF90u,type,width,1080,width,1080,fov);
            if (width <= 1440) {
                if (memcmp(&retail,&fixed,sizeof fixed)) fprintf(stderr,"camera control %ux1080 actual-m00=%.9g retail-m00=%.9g\n",width,fixed.primary[0],retail.primary[0]);
                CHECK(!memcmp(&retail,&fixed,sizeof fixed));
            }
            else {
                float kx = 1440.0f/width;
                near(fixed.primary[0],control.primary[0]*kx); near(fixed.primary[5],control.primary[5]);
                near(fixed.biased[0],control.biased[0]*kx); near(fixed.biased[5],control.biased[5]);
                near(fixed.ppu,retail.ppu*kx);
                for (unsigned i=0;i<16;++i) if (i!=0 && i!=5) {
                    CHECK(fixed.primary[i]==retail.primary[i] && fixed.biased[i]==retail.biased[i]);
                }
                /* Culling plane normals follow the corrected product, including widened edges. */
                float norm = sqrtf(fixed.primary[0]*fixed.primary[0]+1);
                near(fabsf(fixed.planes[0]),fabsf(fixed.primary[0])/norm);
                near(fabsf(fixed.planes[2]),1/norm);
            }
            ++cases;
        }
        Result refl = build(1,0x00B4B110u,type,1920,1080,512,512,fov);
        near(refl.primary[0],control.primary[0]*0.75f); near(refl.primary[5],control.primary[5]);
        near(refl.biased[0],control.biased[0]*0.75f); near(refl.biased[5],control.biased[5]);
        Result sub = build(0,0x00B4B190u,type,1920,1080,512,512,fov);
        Result subfix = build(1,0x00B4B190u,type,1920,1080,512,512,fov);
        CHECK(!memcmp(&sub,&subfix,sizeof sub));
    }
    }
    Cpu c={0}; c.esp=0x10000; M32(c.esp)=0x0071B99Du;
    uint8_t before[0x280]; memcpy(before,G+0x300000,sizeof before);
    widescreen_projection(&c,0x300040); CHECK(!memcmp(before,G+0x300000,sizeof before));
    carbon_camera_view=0x00B4AF90u; M32(c.esp)=0x1234;
    widescreen_projection(&c,0x300040); CHECK(!memcmp(before,G+0x300000,sizeof before));
    printf("CAMERA PASS cases=%u types=28 fovs=3 precisions=3 aspects=4:3,16:9,21:9 error=%.9g reflection=252 subview=252 frustum=1 scope=2\n",cases,worst);
    free(G); return 0;
}
'''


def camera_fixture(tmp):
    bodies = '\n'.join(original(a) for a in CAMERA_FRAGMENTS)
    # Keep the builder named native_; its dependencies retain their guest symbols.
    bodies = re.sub(r'native_(?!0071B780)([0-9A-F]{8})', r'f_\1', bodies)
    prototypes = '\n'.join('void f_' + a + '(Cpu *);' for a in
                           ('0044B400','0046DC30','0046DCF0','0070F2A0','0070F2F0','0087EAC0','0086B296'))
    harness = CAMERA_HARNESS.replace('ORIGINALS', prototypes + '\n' + bodies)
    source = (PRIVATE / 'game_camera_wide.h').read_text()
    for variant in ('good', 'retail', 'biased-retail', 'ppu-retail', 'fix-43', 'subview-wide', 'reflection-retail'):
        changed = source
        if variant == 'retail':
            changed = changed.replace('    carbon_camera_correct(c, view, proj);', '')
        elif variant == 'biased-retail':
            changed = changed.replace('i < 2', 'i < 1')
        elif variant == 'ppu-retail':
            changed = changed.replace('    MF32(view + 0x10) *= kx;', '')
        elif variant == 'fix-43':
            changed = changed.replace('if (kx >= 1.0f) return;', 'if (kx > 1.0f) return;\n    if (kx == 1.0f) kx = 0.75f;')
        elif variant == 'subview-wide':
            changed = changed.replace('    if (view != 0x00B4B110u && (M32(vp + 0x14) != w || M32(vp + 0x18) != h)) return;\n', '')
        elif variant == 'reflection-retail':
            changed = changed.replace('view != 0x00B4B110u && ', '')
        assert variant == 'good' or changed != source, variant
        (tmp / 'game_camera_wide.h').write_text(changed)
        (tmp / 'camera.c').write_text(harness)
        result = subprocess.run(['clang', '-O1', '-fsanitize=address,undefined', '-I', str(tmp), '-I', str(ROOT/'runtime'),
                                 '-I', str(HERE), str(tmp/'camera.c'), '-o', str(tmp/'camera')], capture_output=True,text=True)
        assert result.returncode == 0, result.stderr[-3500:]
        result = subprocess.run([str(tmp/'camera'),str(tmp/'guest.bin')],capture_output=True,text=True)
        assert result.returncode == (0 if variant == 'good' else 1), (variant,result.returncode,result.stdout,result.stderr[-2000:])
        print('camera-' + variant, 'exit=' + str(result.returncode), (result.stdout+result.stderr).strip()[:300])


def main():
    if not (HERE / 'out/carbon-base/image.json').is_file():
        print('SKIP: Carbon outputs absent'); return 3
    bodies = '\n'.join(original(a) for a in FRAGMENTS)
    effect = selected_source(ROOT / 'runtime/d3dx_effect.c')
    packing = between(effect, '            if (q->cls == PC_MATRIX_ROWS || q->cls == PC_MATRIX_COLUMNS) {',
                      '            uint32_t cnt = q->rows * q->cols;')
    render = selected_source(ROOT / 'runtime/render.m')
    fixed = between(render, '    float *W = dev.transform[256]', '    for (int k = 0; k < 4; ++k) vsc[4][k] = 1.0f;')
    assert 'carbon_fe_scope' in packing and 'carbon_fe_scope' in fixed
    sys.path.insert(0, str(HERE))
    import recomp
    image = json.loads((HERE / 'out/carbon-base/image.json').read_text())
    pe = recomp.PE(image['exe'], expected_sha256=image['sha256'])
    with tempfile.TemporaryDirectory(prefix='private-picture-03-') as tmp:
        tmp = Path(tmp)
        blob = bytearray(0xC00000)
        for name, _, va, size, raw in pe.sections:
            if name.rstrip(b'\0') in (b'.rdata', b'.data'): blob[pe.base + va:pe.base + va + size] = pe.data[raw:raw + size]
        (tmp / 'guest.bin').write_bytes(blob)
        wide = (PRIVATE / 'game_widescreen.h').read_text()
        clip = (PRIVATE / 'game_frontend_clip.h').read_text()
        for variant in ('good', 'fixed-mask', 'row-packing', 'no-resend'):
            harness, source = HARNESS, wide
            pack, ff = packing, fixed
            if variant == 'fixed-mask':
                assert clip in ff
                ff = ff.replace(clip, '')
            elif variant == 'row-packing':
                assert 'm[k * 4] *= kx' in pack
                pack = pack.replace('m[k * 4] *= kx', 'm[k] *= kx')
            elif variant == 'no-resend':
                assert '    carbon_wide_resend(c, wide);\n' in source
                source = source.replace('    carbon_wide_resend(c, wide);\n', '')
            (tmp / 'game_widescreen.h').write_text(source)
            text = harness.replace('PACKING', pack).replace('FIXED', ff).replace('ORIGINALS', bodies)
            (tmp / 'fixture.c').write_text(text)
            command = ['clang', '-O1', '-fsanitize=address,undefined', '-I', str(tmp), '-I', str(ROOT / 'runtime'),
                       '-I', str(HERE), str(tmp / 'fixture.c'), '-o', str(tmp / 'fixture')]
            result = subprocess.run(command, capture_output=True, text=True)
            assert result.returncode == 0, result.stderr[-2500:]
            result = subprocess.run([str(tmp / 'fixture'), str(tmp / 'guest.bin')], capture_output=True, text=True)
            expected = 0 if variant == 'good' else 1
            assert result.returncode == expected, (variant, result.returncode, result.stdout, result.stderr[-2000:])
            print(variant, 'exit=' + str(result.returncode), (result.stdout + result.stderr).strip()[:200])
        camera_fixture(tmp)
    return 0


if __name__ == '__main__':
    sys.exit(main())
