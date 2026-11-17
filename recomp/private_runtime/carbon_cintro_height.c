#include "host.h"
#include <stdlib.h>

/* 004809C0 is the height query behind the scene-camera elevation correction.
 * It probes from the point plus 4 m, so a road more than ~4 m above the point
 * (a sloped grid, camera far behind it) misses and the correction is zero,
 * which puts the camera under the road. Every retail hit is kept; only a miss
 * asks 00455110, which probes from far above, and keeps the retail result if
 * that misses too. */
static int carbon_cintro_off = -1;
static int carbon_cintro_logged;

/* 00455110(pos, &height, &normal): pos is (-y, height, x) of the game point. */
static int carbon_cintro_probe(Cpu *c, uint32_t point, float *height) {
    Cpu probe = *c;
    probe.esp -= 32;
    uint32_t buffer = probe.esp;
    unsigned char saved[32];
    memcpy(saved, G + buffer, sizeof saved);
    MF32(buffer) = -MF32(point + 4);
    MF32(buffer + 4) = MF32(point + 8);
    MF32(buffer + 8) = MF32(point);
    uint32_t args[] = {buffer, buffer + 16, buffer + 20};
    int hit = (call_guest(&probe, 0x00455110u, 3, args) & 0xFFu) != 0;
    if (hit) *height = MF32(buffer + 16);
    memcpy(G + buffer, saved, sizeof saved);
    return hit;
}

void carbon_cintro_height(Cpu *c, void (*original)(Cpu *)) {
    if (carbon_cintro_off < 0) {
        const char *e = getenv("NFS_CARBON_CINTRO_FIX");
        carbon_cintro_off = e && !strcmp(e, "0");
    }
    uint32_t point = arg(c, 0), caller = M32(c->esp);
    original(c);
    /* Race flow 6 with no road face found by the native probe. */
    int miss = M32(0x00A99BBCu) == 6 && !(M32(0x00A8AAC0u) & 1u);
    float retail = (float)c->st[c->top], fixed = retail, found = 0;
    int recovered = 0;
    if (!carbon_cintro_off && miss && carbon_cintro_probe(c, point, &found)) {
        fixed = found;
        recovered = 1;
        c->st[c->top] = found;
    }
    if (diag_on && carbon_cintro_logged < 2000 && M32(0x00A99BBCu) == 6) {
        /* Road height under the point from the far-above probe, hit or miss. */
        float road = 0;
        int have = carbon_cintro_probe(c, point, &road);
        carbon_cintro_logged++;
        diag_event("cintro: ra=%08x z=%.3f retail=%.3f final=%.3f miss=%d recovered=%d road=%.3f have=%d origin=%.3f",
                   caller, MF32(point + 8), retail, fixed, miss, recovered, road, have, MF32(0x00A87DF0u));
    }
}
