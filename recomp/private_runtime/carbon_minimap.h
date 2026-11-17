/* Scoped HUD calibration. Native calls are synchronous and may nest; every
 * scope restores its entry bits, including a surrounding HUD scope's tuple.
 * World-map TrackInfo fields use a different vertical-origin convention.
 */
#include "host.h"
#include <math.h>
#include <stdlib.h>
#include <string.h>

extern int diag_on;
extern void diag_event(const char *, ...);
extern int private_carbon_player_position(float *);

/* BEGIN GENERATED HUD CALIBRATION */
static const struct { float bx, by, k; } carbon_minimap_calibration[] = {
    {-0x1.3238ec0000000p+10f, -0x1.8dc9460000000p+10f, 0x1.3aeb560000000p-13f},
    {-0x1.c840000000000p+12f, -0x1.b500000000000p+12f, 0x1.8f9c180000000p-15f},
};
/* END GENERATED HUD CALIBRATION */

#ifndef CARBON_MINIMAP_TEST_SHIFT
#define CARBON_MINIMAP_TEST_SHIFT 0
#endif

static int carbon_minimap_mode(void) {
    static int mode = -1;
    if (mode >= 0) return mode;
    const char *value = getenv("NFS_CARBON_MINIMAP");
    if (!value || !*value || !strcmp(value, "off")) mode = 0;
    else if (!strcmp(value, "rockport")) mode = 1;
    else if (!strcmp(value, "atlas")) mode = 2;
    else {
        fprintf(stderr, "NFS_CARBON_MINIMAP: expected off, rockport or atlas\n");
        exit(2);
    }
    return mode;
}

static void carbon_minimap_log(uint32_t hud, unsigned track, int mode,
                                float bx, float by, float k) {
    static uint64_t last;
    if (!diag_on) return;
    uint64_t now = host_ticks();
    if (last && now - last < 1000000000ull) return;
    float position[3];
    if (!hud || !private_carbon_player_position(position)) return;
    last = now;
    double u = MF32(hud + 0xAC), v = MF32(hud + 0xB0);
    int tile = isfinite(u) && isfinite(v) && u >= 0 && u < 1 && v >= 0 && v < 1
        ? 16 * (int)floor(v * 16) + (int)floor(u * 16) : -1;
    /* 005E15B0 gates tile visibility with manager +80/+94, per-tile +98,
     * and HUD +D4. These observations distinguish projection from tile loading. */
    uint32_t manager = M32(0x00A97DE0u);
    unsigned resident = manager && tile >= 0 ? M8(manager + 0x98 + tile) : 0;
    /* 00626F90 caps allocation at 256. +2FC is the active partition of the
     * +2F8 allocations in +300; 0061DEA0 selects flags bits 0 and 1.
     * Raw vault Position.x >7000 separates the two regions. */
    uint32_t icons = M32(0x00A98294u);
    unsigned listed = icons ? M32(icons + 0x2FC) : 0, shown = 0;
    unsigned alloc = icons ? M32(icons + 0x2F8) : 0, rock = 0, rock_shown = 0;
    for (unsigned i = 0; i < alloc && i < 256; ++i) {
        uint32_t icon = M32(M32(icons + 0x300) + 4 * i);
        if (!icon) continue;
        int visible = (M8(icon + 1) & 3) == 3;
        shown += i < listed && visible;
        if (MF32(icon + 0x10) > 7000) {
            ++rock;
            rock_shown += visible;
        }
    }
    diag_event("carbon_minimap: track=%u mode=%s bx=%.12g by=%.12g k=%.15g u=%.12g v=%.12g tile=%d render=%.9g,%.9g,%.9g hud=%08X mutant=%d manager=%08X loading=%u pending=%d resident=%u hud_ready=%u pack=%.63s icons=%u shown=%u alloc=%u rock=%u rock_shown=%u",
               track, mode == 2 ? "atlas" : mode == 1 ? "rockport" : "off",
               (double)bx, (double)by, (double)k, u, v, tile,
               (double)position[0], (double)position[1], (double)position[2], hud,
               CARBON_MINIMAP_TEST_SHIFT, manager,
               manager ? M8(manager + 0x80) : 0,
               manager ? (int32_t)M32(manager + 0x94) : 0,
               resident, M8(hud + 0xD4), manager ? gptr(manager + 0x40) : "", listed, shown,
               alloc, rock, rock_shown);
}

static void carbon_minimap_scope(Cpu *c, void (*original)(Cpu *), int centre) {
    int mode = carbon_minimap_mode();
    if (!mode && !diag_on) { original(c); return; }
    /* A7A1A8 is the current world track (the native world selector's value),
     * not the SkipFE request and not any TrackInfo calibration field. */
    unsigned track = M32(0x00A7A1A8u);
    int active = mode == 2 || (mode == 1 && track == 2000);
    uint32_t saved_bx = M32(0x009D5F10u), saved_by = M32(0x009D5F08u);
    uint32_t saved_k = M32(0x009D5F0Cu), hud = c->ecx;
    if (active) {
        unsigned row = mode == 2 ? 1 : 0;
        MF32(0x009D5F10u) = carbon_minimap_calibration[row].bx;
        MF32(0x009D5F08u) = carbon_minimap_calibration[row].by;
        MF32(0x009D5F0Cu) = carbon_minimap_calibration[row].k;
#if CARBON_MINIMAP_TEST_SHIFT
        /* Deliberate one-tile error, enabled only in the negative-control build. */
        MF32(0x009D5F10u) += 1.0f / (16.0f * carbon_minimap_calibration[row].k);
#endif
    }
    float bx = 0, by = 0, k = 0;
    if (centre && diag_on) {
        bx = MF32(0x009D5F10u); by = MF32(0x009D5F08u); k = MF32(0x009D5F0Cu);
    }
    original(c);
    if (active) {
        M32(0x009D5F10u) = saved_bx;
        M32(0x009D5F08u) = saved_by;
        M32(0x009D5F0Cu) = saved_k;
    }
    if (centre && diag_on) carbon_minimap_log(hud, track, mode, bx, by, k);
}

void carbon_minimap_icons(Cpu *c, void (*original)(Cpu *)) {
    carbon_minimap_scope(c, original, 0);
}
void carbon_minimap_roads(Cpu *c, void (*original)(Cpu *)) {
    carbon_minimap_scope(c, original, 0);
}
void carbon_minimap_tiles(Cpu *c, void (*original)(Cpu *)) {
    carbon_minimap_scope(c, original, 0);
}
void carbon_minimap_centre(Cpu *c, void (*original)(Cpu *)) {
    carbon_minimap_scope(c, original, 1);
}

static void carbon_worldmap_log(uint32_t streamer, int mode,
                                uint32_t xmax, uint32_t ymin, uint32_t hi) {
    static uint64_t last;
    uint64_t now = host_ticks();
    if (last && now - last < 1000000000ull) return;
    last = now;
    diag_event("carbon_worldmap: mode=%s cur=%.9g,%.9g des=%.9g,%.9g extent=%.9g,%.9g..%.9g,%.9g lim=%08X,%08X,%08X",
               mode == 2 ? "atlas" : mode == 1 ? "rockport" : "off",
               (double)MF32(streamer + 0x80), (double)MF32(streamer + 0xAC),
               (double)MF32(streamer + 0x88), (double)MF32(streamer + 0xB4),
               (double)MF32(streamer + 0xDC), (double)MF32(streamer + 0xE0),
               (double)MF32(streamer + 0xE4), (double)MF32(streamer + 0xE8),
               xmax, ymin, hi);
}

/* Only the atlas overhang changes: the other three limits stay native.
 * Save entry bits on the stack so recursive calls and HUD scopes compose. */
static void carbon_worldmap_scope(Cpu *c, void (*original)(Cpu *), int stream) {
    int mode = carbon_minimap_mode();
    if (mode != 2 && !(stream && diag_on)) { original(c); return; }
    uint32_t xmax = M32(0x009CEE48u), ymin = M32(0x009CEE3Cu);
    uint32_t hi = M32(0x009CEDC4u), streamer = c->ecx;
    if (mode == 2) {
        M32(0x009CEE48u) = 0x4008B880u; /* 2.136261 */
        M32(0x009CEE3Cu) = 0xBE08F430u; /* -0.133744 */
        M32(0x009CEDC4u) = 0x4018E493u; /* 2.388951 */
    }
    original(c);
    if (stream && diag_on)
        carbon_worldmap_log(streamer, mode, M32(0x009CEE48u),
                           M32(0x009CEE3Cu), M32(0x009CEDC4u));
    if (mode == 2) {
        M32(0x009CEE48u) = xmax;
        M32(0x009CEE3Cu) = ymin;
        M32(0x009CEDC4u) = hi;
    }
}

void carbon_worldmap_input_a(Cpu *c, void (*original)(Cpu *)) {
    carbon_worldmap_scope(c, original, 0);
}
void carbon_worldmap_input_b(Cpu *c, void (*original)(Cpu *)) {
    carbon_worldmap_scope(c, original, 0);
}
void carbon_worldmap_input_c(Cpu *c, void (*original)(Cpu *)) {
    carbon_worldmap_scope(c, original, 0);
}
void carbon_worldmap_streamer(Cpu *c, void (*original)(Cpu *)) {
    carbon_worldmap_scope(c, original, 1);
}
