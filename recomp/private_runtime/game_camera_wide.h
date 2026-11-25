/* Keep the native 4:3 vertical angle on wider outputs. Both projections must
 * change before multiplication: the primary product also supplies culling. */
#include "host.h"
#include <math.h>
#if defined(NFS_GAME) && NFS_GAME == NFS_GAME_PRIVATE
#include "carbon_splitworld.h"
#endif
static uint32_t carbon_camera_view;
/* 0071B780 is thiscall: ECX platform, first stack argument native view.
 * Capture here because the builder reuses EBP for the projection pointer. */
void carbon_camera_setup(Cpu *c, void (*original)(Cpu *)) {
    uint32_t saved = carbon_camera_view;
    carbon_camera_view = M32(c->esp + 4);
    original(c);
    carbon_camera_view = saved;
}
static void carbon_camera_correct(Cpu *c, uint32_t view, uint32_t proj) {
    uint32_t vp = M32(view + 0x50u), camera = M32(view + 0x40u);
    uint32_t w = M32(0x00AB06FCu), h = M32(0x00AB0700u);
    if (!vp || !camera || !w || !h) return;
#if defined(NFS_GAME) && NFS_GAME == NFS_GAME_PRIVATE
    uint32_t rect[4];
    if (carbon_splitworld_rect(view, rect)) { w = rect[2]; h = rect[3]; }
    else
#endif
    if (view != 0x00B4B110u && (M32(vp + 0x14) != w || M32(vp + 0x18) != h)) return;
    float kx = (4.0f / 3.0f) * (float)h / (float)w;
    if (kx >= 1.0f) return;
    uint32_t type = M32(view + 8);
    float f43 = 0.75f;
    if (type == 1 || type == 2 || type == 4 || type == 5) f43 *= 1.15f;
    if (type == 9 || type == 10) f43 = 0.60024011135f; /* native 3F19A956 */
    /* 0071B8E4..0071B909: truncate the vertical half-angle to native units,
     * retain the sine's float rounding and the native cosine approximation.
     * atan/tan reconstructed from m00 loses the angle quantization. */
    double vertical = x87_round(c, (double)M16(camera + 0xE4) * (double)f43);
    uint32_t angle = (uint32_t)x87_round(c, vertical * 0.5);
    Cpu trig = *c;
    call_guest(&trig, 0x0046DC30u, 1, &angle);
    float sine = (float)trig.st[trig.top];
    x87_pop(&trig);
    call_guest(&trig, 0x0046DCF0u, 1, &angle);
    double tangent = x87_round(c, (double)sine / trig.st[trig.top]);
    float m11 = -(float)x87_round(c, 1.0 / tangent);
    for (unsigned i = 0; i < 2; ++i) {
        uint32_t matrix = proj + i * 0x80u;
        MF32(matrix) *= kx;
        MF32(matrix + 20) = m11;
    }
    MF32(view + 0x10) *= kx;
}
void widescreen_projection(Cpu *c, uint32_t proj) {
    if (M32(c->esp) != 0x0071B99Du || !carbon_camera_view) return;
    uint32_t view = carbon_camera_view;
    uint32_t vp = M32(view + 0x50u), platform = proj - 0x40u;
    if (!vp) return;
    carbon_camera_correct(c, view, proj);
    if (diag_on) {
        static uint32_t seen[64][3];
        static unsigned count;
        uint32_t type = M32(view + 8), w = M32(vp + 0x14), h = M32(vp + 0x18);
        for (unsigned i = 0; i < count; ++i)
            if (seen[i][0] == type && seen[i][1] == w && seen[i][2] == h) return;
        if (count == 64) return;
        seen[count][0] = type; seen[count][1] = w; seen[count++][2] = h;
        diag_event("carbon camera: view=%08x type=%u viewport=%ux%u primary=%.9g,%.9g biased=%.9g,%.9g ppu=%.9g",
                   view, type, w, h, MF32(proj), MF32(proj + 20),
                   MF32(platform + 0xC0), MF32(platform + 0xD4), MF32(view + 0x10));
    }
}
