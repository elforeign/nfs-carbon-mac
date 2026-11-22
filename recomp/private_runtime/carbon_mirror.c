/* Rear-view mirror target: resolution and anti-aliasing (NFS_MIRROR_SIZE, NFS_MIRROR_MSAA, as Most Wanted).
 *
 * 0070DAB0 (from 0071AAE0, before 0071AD20 copies the size into target table entry 4 at 00AB0540) sizes the
 * mirror as 2^floor(log2(w / 3)) x 2^floor(log2(h / 3)) of the back buffer (00AB0AC8/00AB0ACC) into
 * 00A63AD0/00A63AD4, then creates its depth 00AB091C (device +0x74, no multisampling), the texture 00AB0914
 * (+0x5C, one level, render target) and the texture's surface 00AB0918. At 3840x2160 that is 1024x512. The
 * composite (RVMPIP, 00750C30) shows the middle half of its height in a quad of 260x70 front-end units
 * (x +/-0.40625, y .6292...9208 of the 4:3 canvas): 1170x315 px at 2160p from 1024x256 texels, sampled
 * bilinear without anti-aliasing. The view's projection follows the target's aspect, its level of detail the
 * back buffer's width.
 *
 * NFS_MIRROR_SIZE=pc|<percent> (default 100): when the quad would get fewer texels than that percentage of its
 * pixels, the three objects are made again at the retail size times one factor (aspect kept, so the projection
 * is the retail one), never smaller than retail. NFS_MIRROR_MSAA=on|off (default on): the texture and depth get
 * the back buffer's sample count (render_target_msaa; render.m resolves each pass into the texture).
 *
 * Gameplay's native Rearview Mirror option gates the pass and composite. When enabled, the mirror
 * uses the Xbox 360 scenery registration policy and full world techniques. Clear the low-detail
 * pass flag before 0072E070 flushes the sky dome. Reset the mirror depth after the dome so
 * its colour remains behind the depth-tested scenery. Reflection and env-map passes retain
 * their original techniques and depth.
 *
 * View. 0071B780 (thiscall, ECX = the view's platform, M32(view)) builds the mirror's projection with
 * 0070F2F0 into platform+0x40 and the depth-biased one into +0xC0, m00 = 1/tan(fov/2), m11 = 1/tan(fov/2 *
 * back-buffer h/w): 77.3 x 43.5 deg at 16:9 (m00 1.2502, m11 2.5075). The composite shows the middle half of
 * the target's height in the quad, so the picture's shape is (2/m00) : (1/m11) = 4.01:1 in a 3.71:1 quad at
 * 16:9 (7.4 % narrower than true); it follows the game's own angle arithmetic at every aspect (at 4:3 the
 * shown 2.9:1 is stretched into the same quad), not a port framing error. NFS_MIRROR_VIEW=<hfov deg>|pc
 * (default pc, env only): m00 = 1/tan(hfov/2), m11 = m00 * quad aspect / 2 on both projections, before
 * 0071B780 multiplies them, so culling follows; the pixel scale (view+0x10, LOD) stays retail.
 */
#include "host.h"
#include <math.h>
#include <stdlib.h>

#define CARBON_MIRROR_W 0x00A63AD0u
#define CARBON_MIRROR_H 0x00A63AD4u
#define CARBON_MIRROR_DEPTH_FMT 0x00A63ADCu
#define CARBON_MIRROR_COLOR_FMT 0x00A63AD8u
#define CARBON_MIRROR_TEXTURE 0x00AB0914u
#define CARBON_MIRROR_SURFACE 0x00AB0918u
#define CARBON_MIRROR_DEPTH 0x00AB091Cu
#define CARBON_DEVICE 0x00AB0ABCu
#define CARBON_BACK_W 0x00AB0AC8u
#define CARBON_BACK_H 0x00AB0ACCu

/* The size that gives the quad pct % of a texel per pixel on both axes; retail when it already does. */
static void carbon_mirror_size(uint32_t bw, uint32_t bh, uint32_t w0, uint32_t h0, int pct,
                               uint32_t *w, uint32_t *h) {
    *w = w0; *h = h0;
    if (pct <= 0 || !bw || !bh || !w0 || !h0) return;
    double canvas = bh * 4.0 / 3.0 < bw ? bh * 4.0 / 3.0 : bw;
    double qw = 260.0 / 640.0 * canvas * pct / 100.0, qh = 70.0 / 480.0 * bh * pct / 100.0;
    double s = fmax(qw / w0, 2.0 * qh / h0);   /* the composite reads half of the height */
    if (s <= 1.0) return;
    if (w0 >= h0) { *h = (uint32_t)ceil(h0 * s - 1e-6); *w = *h * (w0 / h0); }
    else { *w = (uint32_t)ceil(w0 * s - 1e-6); *h = *w * (h0 / w0); }
}

static void carbon_mirror_release(Cpu *c, uint32_t slot) {
    uint32_t o = M32(slot);
    if (!o) return;
    call_guest(c, M32(M32(o) + 8), 1, &o);
    M32(slot) = 0;
}

static uint32_t carbon_mirror_create(Cpu *c, uint32_t w, uint32_t h) {
    uint32_t device = M32(CARBON_DEVICE), vt = M32(device);
    uint32_t depth[] = {device, w, h, M32(CARBON_MIRROR_DEPTH_FMT), 0, 0, 0, CARBON_MIRROR_DEPTH, 0};
    uint32_t texture[] = {device, w, h, 1, 1, M32(CARBON_MIRROR_COLOR_FMT), 0, CARBON_MIRROR_TEXTURE, 0};
    if (call_guest(c, M32(vt + 0x74), 9, depth) || call_guest(c, M32(vt + 0x5C), 9, texture)) return 1;
    uint32_t t = M32(CARBON_MIRROR_TEXTURE), surface[] = {t, 0, CARBON_MIRROR_SURFACE};
    return call_guest(c, M32(M32(t) + 0x48), 3, surface);
}

void carbon_mirror_allocate(Cpu *c, void (*original)(Cpu *)) {
    original(c);
    const char *e = getenv("NFS_MIRROR_SIZE");
    int pct = !e || !*e ? 100 : atoi(e) > 0 ? atoi(e) : 0;   /* pc (or 0): retail */
    if (pct > 100) pct = 100;
    e = getenv("NFS_MIRROR_MSAA");
    int msaa = !e || !*e || strcmp(e, "off");
    uint32_t bw = M32(CARBON_BACK_W), bh = M32(CARBON_BACK_H), w0 = M32(CARBON_MIRROR_W), h0 = M32(CARBON_MIRROR_H);
    uint32_t w, h;
    carbon_mirror_size(bw, bh, w0, h0, pct, &w, &h);
    if ((w != w0 || h != h0) && M32(CARBON_DEVICE) && M32(CARBON_MIRROR_TEXTURE)) {
        carbon_mirror_release(c, CARBON_MIRROR_DEPTH);
        carbon_mirror_release(c, CARBON_MIRROR_SURFACE);
        carbon_mirror_release(c, CARBON_MIRROR_TEXTURE);
        if (carbon_mirror_create(c, w, h)) {   /* keep the retail target */
            carbon_mirror_release(c, CARBON_MIRROR_DEPTH);
            carbon_mirror_release(c, CARBON_MIRROR_SURFACE);
            carbon_mirror_release(c, CARBON_MIRROR_TEXTURE);
            w = w0; h = h0;
            carbon_mirror_create(c, w, h);
        }
        M32(CARBON_MIRROR_W) = w; M32(CARBON_MIRROR_H) = h;
    }
    int samples = msaa ? render_msaa_samples() : 1, applied = 0;
    if (samples > 1)
        applied = render_target_msaa(M32(CARBON_MIRROR_TEXTURE), M32(CARBON_MIRROR_DEPTH), samples);
    if (diag_on) {
        double canvas = bh * 4.0 / 3.0 < bw ? bh * 4.0 / 3.0 : bw;
        double qw = 260.0 / 640.0 * canvas, qh = 70.0 / 480.0 * bh;
        diag_event("carbon mirror: target %ux%u (retail %ux%u, size %d%%), quad %.0fx%.0f px, "
                   "texels per pixel %.2f x %.2f, MSAA %dx%s", w, h, w0, h0, pct, qw, qh,
                   qw > 0 ? w / qw : 0, qh > 0 ? h / 2.0 / qh : 0, applied ? samples : 1,
                   samples > 1 && !applied ? " (not applied)" : "");
    }
}

#define CARBON_MIRROR_VIEW 0x00B4B090u
#define CARBON_ACTIVE_TARGET 0x00AB08F4u
#define CARBON_MIRROR_TARGET 0x00AB0540u
#define CARBON_LOWLOD_PASS 0x00AB0B98u
#define CARBON_PROFILE_MANAGER 0x00A97A7Cu

static int carbon_mirror_enabled(void) {
    /* Property 0x13AF getter (004A44F0): player zero's current profile. */
    uint32_t manager = M32(CARBON_PROFILE_MANAGER);
    uint32_t profiles = manager ? M32(manager + 0xD4u) : 0;
    uint32_t profile = profiles ? M32(profiles) : 0;
    return profile && M8(profile + 0x24209u);
}

/* 0072E070 (view, index, ...), cdecl: view setup may draw the sky. */
void carbon_mirror_view_setup(Cpu *c, void (*original)(Cpu *)) {
    if (M32(c->esp + 4) != CARBON_MIRROR_VIEW || M32(CARBON_LOWLOD_PASS) != 1 ||
        !carbon_mirror_enabled()) {
        original(c);
        return;
    }
    M32(CARBON_LOWLOD_PASS) = 0;
    original(c);

    /* 007AFB70 queues the camera-centred sky. Its depth can cover distant
     * scenery. Clear only Z on the active mirror surface after the sky flush. */
    uint32_t device = M32(CARBON_DEVICE);
    if (device && M32(CARBON_ACTIVE_TARGET) == CARBON_MIRROR_TARGET) {
        Cpu clear = *c;
        uint32_t args[] = {device, 0, 0, 2, 0, 0x3f800000u, 0};  /* D3DCLEAR_ZBUFFER, Z=1 */
        call_guest(&clear, M32(M32(device) + 0xACu), 7, args);
    }
    if (diag_on) {
        static int reported;
        if (!reported) {
            reported = 1;
            diag_event("carbon mirror: full detail and sky colour behind scenery");
        }
    }
}

/* 0079AE80 thiscall: manager in ECX, then view and incoming cull flags.
 * The mirror's native registration adds 0x40, preserving admission and the
 * 32 px cutoff. Without 0x2000, 0079FA60 selects the ordinary model
 * slot +0x30, as Xbox 360 does at 82586960. */
void carbon_mirror_register_scenery(Cpu *c, void (*original)(Cpu *)) {
    uint32_t flags_arg = c->esp + 8;
    uint32_t flags = M32(flags_arg);
    if (M32(c->esp + 4) != CARBON_MIRROR_VIEW || !(flags & 0x2000u) ||
        !carbon_mirror_enabled()) {
        original(c);
        return;
    }
    M32(flags_arg) = flags & ~0x2000u;
    original(c);
    M32(flags_arg) = flags;
}

static float carbon_mirror_hfov = -1.0f;   /* 0: pc */

static void carbon_mirror_view_options(void) {
    if (carbon_mirror_hfov < 0.0f) {
        const char *v = getenv("NFS_MIRROR_VIEW");
        float d = v && *v ? (float)atof(v) : 0.0f;
        carbon_mirror_hfov = d >= 10.0f && d <= 150.0f ? d : 0.0f;
    }
}

/* m00 and m11 for a horizontal angle and the quad's on-screen aspect (the shown half of the target's height). */
static void carbon_mirror_view_matrix(float hfov, float aspect, float *m00, float *m11) {
    *m00 = 1.0f / tanf(hfov * 0.5f * (float)M_PI / 180.0f);
    *m11 = *m00 * aspect * 0.5f;
}

/* 0070F2F0 (out, m00, m11, near, far): the projection builder. */
void carbon_mirror_projection(Cpu *c, void (*original)(Cpu *)) {
    uint32_t out = M32(c->esp + 4), platform = M32(CARBON_MIRROR_VIEW);
    original(c);
    if (!platform || (out != platform + 0x40u && out != platform + 0xC0u)) return;
    carbon_mirror_view_options();
    if (carbon_mirror_hfov <= 0.0f) return;
    uint32_t bw = M32(CARBON_BACK_W), bh = M32(CARBON_BACK_H);
    if (!bw || !bh) return;
    double canvas = bh * 4.0 / 3.0 < bw ? bh * 4.0 / 3.0 : bw;
    float aspect = (float)((260.0 / 640.0 * canvas) / (70.0 / 480.0 * bh)), m00, m11;
    carbon_mirror_view_matrix(carbon_mirror_hfov, aspect, &m00, &m11);
    MF32(out) = copysignf(m00, MF32(out));
    MF32(out + 20) = copysignf(m11, MF32(out + 20));
    if (diag_on && out == platform + 0x40u) {
        static int once;
        if (!once++) diag_event("carbon mirror: view %.0f x %.1f deg (quad aspect %.3f), m00 %.4f m11 %.4f", carbon_mirror_hfov,
                                2.0 * atan(0.5 / m11) * 180.0 / M_PI, aspect, m00, m11);
    }
}
