/* Reuse the retained world-map image for one resident atlas draw. */
#include "host.h"
#include <math.h>
#include <stdlib.h>
#include <string.h>

static uint32_t carbon_art_owner, carbon_art_image;

static int carbon_art_active(void) {
    const char *mode = getenv("NFS_CARBON_MINIMAP");
    return mode && !strcmp(mode, "atlas");
}

void carbon_worldmap_art_retain(Cpu *c, void (*original)(Cpu *)) {
    uint32_t owner = c->ecx;
    original(c);
    if (!carbon_art_active() || !owner) return;
    uint32_t image = M32(owner + 0x14);
    if (!image) return;
    if (carbon_art_owner == owner) { carbon_art_image = image; return; }
    /* The owner has the same lifetime as its native texture request list. */
    carbon_art_owner = owner;
    carbon_art_image = image;
    Cpu request = *c;
    request.esp -= 64;
    uint32_t hash = request.esp;
    M32(hash) = 0x0F365871u;
    uint32_t args[] = {hash, 1, 0, 0, M32(owner + 0xC), UINT32_MAX};
    call_guest(&request, 0x00560080u, 6, args);
}

void carbon_worldmap_art_release(Cpu *c, void (*original)(Cpu *)) {
    if (carbon_art_owner && c->ecx == carbon_art_owner) {
        Cpu release = *c;
        release.esp -= 64;
        uint32_t hash = release.esp;
        M32(hash) = 0x0F365871u;
        uint32_t list = carbon_art_owner + 0xEC;
        call_guest(&release, 0x0055CF50u, 1, &list);
        uint32_t args[] = {hash, 1};
        call_guest(&release, 0x0055CF30u, 2, args);
        carbon_art_owner = carbon_art_image = 0;
    }
    original(c);
}

/* Carbon's right map-edge veil (solid 75C4ABD4 + fade A5CA44F5, one mirrored map-space group) starts its
 * fade at u 1.370850, inside Rockport's rect. Move it to start at Rockport's right edge u 2.146261:
 * 0.775411 u x 1024 local units per u, negative because the group is mirrored. Draw-time only. */
#define CARBON_ART_VEIL_SHIFT (-794.0f)

static int carbon_art_veil(uint32_t object) {
    uint32_t hash = M32(object + 0x10);
    return hash == 0x75C4ABD4u || hash == 0xA5CA44F5u;
}

void carbon_worldmap_art_draw(Cpu *c, void (*original)(Cpu *)) {
    uint32_t renderer = c->ecx, image = M32(c->esp + 4);
    uint32_t veil = carbon_art_active() && carbon_art_owner && carbon_art_veil(image) ? M32(image + 0x2C) : 0;
    if (veil) {
        float x = MF32(veil + 0x1C);
        MF32(veil + 0x1C) = x + CARBON_ART_VEIL_SHIFT;
        M32(image + 0x1C) |= 0x02400000u;
        original(c);
        MF32(veil + 0x1C) = x;
        M32(image + 0x1C) |= 0x02400000u;
        return;
    }
    original(c);
    if (!carbon_art_active() || !carbon_art_owner || image != carbon_art_image) return;
    uint32_t t = M32(image + 0x2C), cache = M32(image + 0x58);
    if (!t || !cache) return;
    double ul[2] = {MF32(t + 0x44), MF32(t + 0x48)};
    double lr[2] = {MF32(t + 0x4C), MF32(t + 0x50)};
    double centre[2] = {MF32(t + 0x1C), MF32(t + 0x20)};
    double size[2] = {MF32(t + 0x38), MF32(t + 0x3C)};
    const double lo[2] = {1.089223904, -0.145743989};
    const double hi[2] = {2.146260734, 0.911292841};
    float new_centre[2], new_size[2];
    for (unsigned i = 0; i < 2; ++i) {
        double span = lr[i] - ul[i];
        if (!isfinite(span) || span <= 0 || !isfinite(centre[i]) || !isfinite(size[i]) || size[i] <= 0) return;
        new_centre[i] = centre[i] + size[i] * (((lo[i] + hi[i]) * .5 - ul[i]) / span - .5);
        new_size[i] = size[i] * (hi[i] - lo[i]) / span;
        if (!isfinite(new_centre[i]) || !isfinite(new_size[i]) || new_size[i] <= 0) return;
    }
    /* Type 9 uses the native veil's four-corner alpha interpolation (005995E0),
     * not a fade texture. A5CA44F5 is 150 local units wide; quarter scale keeps
     * the border narrow enough to retain the map detail. Width follows zoom. */
    const double border = (150.0 / 4.0) / (1024.0 * (hi[0] - lo[0]));
    const double cuts[] = {0, border, 1 - border, 1};
    Cpu draw = *c;
    draw.esp -= 512;
    uint32_t resolve[] = {0x0F365871u, 0, 0};
    if (!call_guest(&draw, 0x0055CFD0u, 3, resolve)) return;
    uint32_t patch = c->esp - 384;
    uint32_t texture = M32(image + 0x24), flags = M32(image + 0x1C);
    memcpy(G + patch, G + t, 0x54);
    M32(image + 0x2C) = patch;
    M32(image + 0x24) = 0x0F365871u;
    for (unsigned y = 0; y < 3; ++y) for (unsigned x = 0; x < 3; ++x) {
        MF32(patch + 0x1C) = new_centre[0] + new_size[0] * ((cuts[x] + cuts[x+1]) * .5 - .5);
        MF32(patch + 0x20) = new_centre[1] + new_size[1] * ((cuts[y] + cuts[y+1]) * .5 - .5);
        MF32(patch + 0x38) = new_size[0] * (cuts[x+1] - cuts[x]);
        MF32(patch + 0x3C) = new_size[1] * (cuts[y+1] - cuts[y]);
        MF32(patch + 0x44) = cuts[x]; MF32(patch + 0x48) = cuts[y];
        MF32(patch + 0x4C) = cuts[x+1]; MF32(patch + 0x50) = cuts[y+1];
        /* Native corner order: UL, UR, LR, LL. RGB is inherited unchanged. */
        for (unsigned k = 0; k < 4; ++k) {
            unsigned cx = x + (k == 1 || k == 2), cy = y + (k >= 2);
            uint32_t color = patch + 0x54 + 16*k;
            M32(color) = M32(color + 4) = M32(color + 8) = 255;
            M32(color + 12) = cx && cx < 3 && cy && cy < 3 ? 255 : 0;
        }
        M32(image + 0x1C) = flags | 0x02400000u;
        draw = *c; draw.esp -= 512; draw.ecx = renderer;
        uint32_t args[] = {image, cache};
        call_guest(&draw, 0x005995E0u, 2, args);
    }
    M32(image + 0x2C) = t;
    M32(image + 0x24) = texture;
    M32(image + 0x1C) = flags | 0x02400000u;
}
