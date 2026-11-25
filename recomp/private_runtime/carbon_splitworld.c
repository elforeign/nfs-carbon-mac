/* Two main views share a target, but own descriptors, cameras and projections.
 * 0071BCA0 runs before the camera loop; 007103C0 already culls both active
 * views. 0072EBA0 retains frame preparation, captures and final dispatch once.
 * Its 0072E5B0 call submits raw geometry for both views; late captures/effects
 * are excluded until they have view ownership. */
#include "carbon_splitworld.h"
#include <stdlib.h>

#define CS_P1 0x00B4AF90u
#define CS_P2 0x00B4B010u
static uint32_t storage, descriptors[2], native_descriptors[2], rectangles[2][4];
static uint8_t native_active[2];
static int installed, in_frame, cleared;
static uint32_t probe_camera, native_camera;

/* A rendering-only probe for jobs preceding the two-player front end. It uses
 * a copy of the live camera, shifted eight metres sideways. It does
 * not create a second player or change simulation/input ownership. */
static int cs_probe(void) {
    static int enabled = -1;
    if (!diag_on) return 0;
    if (enabled < 0) {
        const char *e = getenv("BOOT_DIAG_SPLITWORLD");
        enabled = e && !strcmp(e, "1");
    }
    return enabled;
}

int carbon_splitworld_rect(uint32_t view, uint32_t rect[4]) {
    if (!installed || (view != CS_P1 && view != CS_P2)) return 0;
    if (rect) memcpy(rect, rectangles[view == CS_P2], sizeof rectangles[0]);
    return 1;
}

/* Native initialization assigns both players to the primary target. Keep that
 * full-size descriptor intact: mirrors, frame clears and reset still use it. */
void carbon_splitworld_layout(Cpu *c, void (*original)(Cpu *)) {
    if (native_camera && M32(CS_P2 + 0x40) == probe_camera) M32(CS_P2 + 0x40) = native_camera;
    native_camera = 0;
    if (installed) {
        for (unsigned i = 0; i < 2; ++i) {
            uint32_t view = CS_P1 + 0x80u * i;
            if (M32(view + 0x50) == descriptors[i]) {
                M32(view + 0x50) = native_descriptors[i];
                M8(view + 0xC) = native_active[i];
            }
        }
        installed = 0;
    }
    original(c);
    /* 007655D0 creates two local players only for simulation mode 1. */
    if (M32(0x00A99BBCu) != 6) return;
    int probe = cs_probe() && M32(0x00B4D854u) != 1;
    if (M32(0x00B4D854u) != 1 && !probe) return;
    if (!M32(CS_P1) || !M32(CS_P2) || !M32(CS_P1 + 0x40) || !M32(CS_P2 + 0x40)) return;
    uint32_t source = M32(CS_P1 + 0x50);
    if (!source || !M8(CS_P1 + 0xC)) return;
    uint32_t w = M32(source + 0x14), h = M32(source + 0x18);
    if (!w || h < 2) return;
    if (!storage) storage = galloc(0xA0);
    if (!storage) return;
    if (probe) {
        if (!probe_camera) probe_camera = galloc(0x100);
        if (!probe_camera) return;
        native_camera = M32(CS_P2 + 0x40);
        memcpy(G + probe_camera, G + M32(CS_P1 + 0x40), 0x100);
        MF32(probe_camera + 0x30) -= 8.0f;
        M32(CS_P2 + 0x40) = probe_camera;
    }
    for (unsigned i = 0; i < 2; ++i) {
        uint32_t view = CS_P1 + 0x80u * i, d = storage + 0x20u * i;
        native_descriptors[i] = M32(view + 0x50);
        native_active[i] = M8(view + 0xC);
        descriptors[i] = d;
        memcpy(G + d, G + source, 0x1C);
        rectangles[i][0] = 0; rectangles[i][1] = i ? h / 2 : 0;
        rectangles[i][2] = w; rectangles[i][3] = i ? h - h / 2 : h / 2;
        /* 00727230 and shader setup index view/platform state by descriptor+4. */
        M32(d + 4) = M32(view + 8);
        M32(d + 0x10) = 1;
        M32(d + 0x14) = w; M32(d + 0x18) = rectangles[i][3];
        M32(view + 0x50) = d; M8(view + 0xC) = 1;
    }
    installed = 1;
}

static void cs_device(Cpu *c, uint32_t method, int n, const uint32_t *args) {
    call_guest(c, M32(M32(args[0]) + method), n, args);
}
static void cs_bounds(Cpu *c, const uint32_t r[4], int clip) {
    uint32_t p = storage + 0x40, device = M32(0x00AB0ABCu);
    memcpy(G + p, r, 16); M32(p + 16) = 0; MF32(p + 20) = 1;
    uint32_t vp[2] = {device, p}; cs_device(c, 0xBC, 2, vp);
    M32(p + 24) = r[0]; M32(p + 28) = r[1];
    M32(p + 32) = r[0] + r[2]; M32(p + 36) = r[1] + r[3];
    uint32_t scissor[2] = {device, p + 24}; cs_device(c, 0x12C, 2, scissor);
    uint32_t state[3] = {device, 174, (uint32_t)clip}; cs_device(c, 0xE4, 3, state);
}

void carbon_splitworld_bind(Cpu *c, void (*original)(Cpu *)) {
    uint32_t sp = c->esp, d = M32(sp + 4);
    if (!installed || (d != descriptors[0] && d != descriptors[1])) { original(c); return; }
    uint32_t clear = M32(sp + 8);
    /* Native binding clears before setting its zero-origin viewport. Both
     * players share colour AND depth; clear them once before either draws. */
    M32(sp + 8) = 0; original(c); M32(sp + 8) = clear;
    Cpu work = *c;
    if (in_frame && !cleared) {
        uint32_t full[4] = {0, 0, rectangles[0][2], rectangles[0][3] + rectangles[1][3]};
        cs_bounds(&work, full, 0);
        uint32_t args[7] = {M32(0x00AB0ABCu), 0, 0, 7, M32(sp + 12), 0x3F800000u, 0};
        cs_device(&work, 0xAC, 7, args); cleared = 1;
    }
    cs_bounds(&work, rectangles[d == descriptors[1]], 1);
}

void carbon_splitworld_frame(Cpu *c, void (*original)(Cpu *)) {
    int previous = in_frame;
    in_frame = installed; cleared = 0;
    original(c);
    if (installed) M32(CS_P1 + 0x50) = descriptors[0];
    in_frame = previous;
}

/* 0072E7C0..0072E83D: native animated-world shader scope. */
static void cs_animated(Cpu *c, uint32_t view) {
    uint32_t sh = M32(0x00B42FECu), device = M32(0x00AB0ABCu);
    M32(0x00AB0BA4u) = sh;
    c->ecx = sh; call_guest(c, M32(M32(sh) + 0x10), 0, NULL);
    uint32_t declaration[2] = {device, M32(sh + 0x48)};
    cs_device(c, 0x15C, 2, declaration);
    uint32_t effect = M32(sh + 0x44), passes = storage + 0x80;
    uint32_t begin[3] = {effect, passes, 0};
    call_guest(c, M32(M32(effect) + 0xFC), 3, begin);
    M32(sh + 0x14) = M32(passes);
    uint32_t pass[2] = {effect, 0};
    call_guest(c, M32(M32(effect) + 0x100), 2, pass);
    call_guest(c, 0x007A2380u, 1, &view);
    call_guest(c, M32(M32(effect) + 0x108), 1, &effect);
    c->ecx = sh; call_guest(c, M32(M32(sh) + 0x14), 0, NULL);
    call_guest(c, M32(M32(effect) + 0x10C), 1, &effect);
    M32(0x00AB0BA4u) = 0;
}

/* 0072E5B6..0072E6FF: sky, scenery, vehicles and route geometry, in native
 * order. Context is the frame-wide 007103C0 result, not a second preparation.
 * The later 00726430/007268E0/007D8240 paths clear shared intermediate/main
 * targets and assume a player-owned effect list. They belong to view effects. */
static void cs_world(Cpu *c, uint32_t view, uint32_t context) {
    uint32_t fx = M32(view + 0x6C), strength = M32(fx + 0x290);
    c->ecx = M32(0x00B77F34u); call_guest(c, 0x007F12A0u, 1, &strength);
    uint32_t bind[3] = {M32(view + 0x50), 1, 0};
    call_guest(c, 0x0070DD30u, 3, bind);
    call_guest(c, 0x0071BED0u, 0, NULL);
    cs_bounds(c, rectangles[view == CS_P2], 1);
    uint32_t sky[3] = {view, 1, M32(0x00A63D20u)};
    call_guest(c, 0x0072E070u, 3, sky);
    MF32(0x00A650E0u) = 1;
    call_guest(c, 0x0072C9B0u, 0, NULL);
    uint32_t scenery[3] = {view, M32(0x00AB0A98u) | 0x20u, c->ebp};
    c->ecx = context; call_guest(c, 0x0079AFA0u, 3, scenery);
    call_guest(c, 0x0072C9B0u, 0, NULL);
    c->ecx = context;
    uint32_t model[2] = {view, call_guest(c, 0x0079AF60u, 1, &view)};
    call_guest(c, 0x007D1C40u, 2, model);
    call_guest(c, 0x0072C9B0u, 0, NULL);
    call_guest(c, 0x0042ADF0u, 1, &view);
    call_guest(c, 0x0072C9B0u, 0, NULL);
    cs_animated(c, view);
    /* 0072E84E: live vehicles, including the native extra-renderable list. */
    uint32_t vehicles[2] = {view, 0};
    call_guest(c, 0x007CCA20u, 2, vehicles);
    call_guest(c, 0x0072C9B0u, 0, NULL);
}

void carbon_splitworld_submit(Cpu *c, void (*original)(Cpu *)) {
    if (!in_frame || !installed || M32(c->esp + 4) != CS_P1) { original(c); return; }
    uint32_t context = M32(c->esp + 8);
    Cpu work = *c;
    cs_world(&work, CS_P1, context);
    cs_world(&work, CS_P2, context);
    /* Retain the native shared final update once. The existing post hook still
     * composes one full atlas; no player-local effect body is repeated here. */
    uint32_t view = CS_P1;
    work.ecx = M32(0x00AB0B80u); call_guest(&work, 0x007D2470u, 1, &view);
    M32(CS_P1 + 0x50) = native_descriptors[0];
    uint32_t bind[3] = {native_descriptors[0], 0, 0};
    call_guest(&work, 0x0070DD30u, 3, bind);
    uint32_t full[4] = {0, 0, rectangles[0][2], rectangles[0][3] + rectangles[1][3]};
    cs_bounds(&work, full, 0);
    c->esp += 4; /* 0072E5B0 is cdecl; the caller retains both arguments. */
    if (diag_on) {
        static unsigned reports;
        if (reports++ < 4)
            diag_event("carbon splitworld: views=%08x,%08x cameras=%08x,%08x rectangles=0,0,%u,%u/0,%u,%u,%u submissions=2 clears=1 probe=%d",
                       CS_P1, CS_P2, M32(CS_P1 + 0x40), M32(CS_P2 + 0x40),
                       rectangles[0][2], rectangles[0][3], rectangles[1][1], rectangles[1][2], rectangles[1][3], native_camera != 0);
    }
}
