/* Warm street lamps on cars: the car half of NFS_CARBON_LAMP_WARM under Neutral D65. */
#include "host.h"
#include "lighting_colour.h"
#include <math.h>
#include <stdlib.h>
#include <string.h>

extern int diag_on;
extern void diag_event(const char *, ...);

/* 00746A00 calls the gatherer 00746230(list, position) at 00746C3C. The list
 * holds record pointers at +0 and radius fades at +60; kind 2 reaches the car
 * as bytes(+c) x fade x 009EA494 / 255, and the list dies inside that call
 * (the buffer becomes the harmonics). The emitter caller (0075A1D0) is left alone. */
#define CARBON_LAMP_CARS_RETURN 0x00746C41u
#define CARBON_LAMP_CARS_SLOTS 24u
#define CARBON_LAMP_CARS_K 2700.f

static int carbon_lamp_cars_on(void) {
    static int selected = -1;
    if (selected < 0) {
        const char *e = getenv("NFS_CARBON_LAMP_WARM");
        selected = !(e && !strcmp(e,"off")) && lighting_mode_d65();
    }
    return selected;
}

/* Street record test as the road half applies it: kind 2, enabled, name
 * containing "street", not an imported tunnel. */
static int carbon_lamp_cars_street(uint32_t r) {
    if (M8(r+7) != 1 || M8(r+4) != 2) return 0;
    char name[35];
    for (unsigned j=0; j<34; ++j) {
        unsigned ch = M8(r+0x3eu+j);
        name[j] = (ch>='A' && ch<='Z') ? ch+('a'-'A') : ch;
    }
    name[34] = 0;
    return strncmp(name,"x360_tunnel_",12) && strstr(name,"street");
}

/* The 2700 K white (shared helper, 15 % D65 mix) scaled to a top byte of 255;
 * the over-255 part rides on the fade as Y(authored) / Y(shadow). */
static void carbon_lamp_cars_white(uint8_t bytes[3], float *y) {
    float w[3], top = 0, b[3];
    lighting_colour_white(CARBON_LAMP_CARS_K,w);
    for (unsigned j=0; j<3; ++j) top = fmaxf(top,w[j]);
    for (unsigned j=0; j<3; ++j) {
        bytes[j] = (uint8_t)lrintf(255*w[j]/top);
        b[j] = bytes[j]/255.f;
    }
    *y = lighting_colour_luminance(b);
}

void carbon_lamplight_cars(Cpu *c, void (*original)(Cpu *)) {
    uint32_t back = M32(c->esp), list = M32(c->esp+4);
    original(c);
    if (back != CARBON_LAMP_CARS_RETURN || !carbon_lamp_cars_on() || !list) return;
    static uint32_t shadow;
    static uint8_t warm[3];
    static float warm_y;
    if (!shadow) {
        shadow = galloc(CARBON_LAMP_CARS_SLOTS*0x60);
        carbon_lamp_cars_white(warm,&warm_y);
    }
    unsigned n = c->eax < CARBON_LAMP_CARS_SLOTS ? c->eax : CARBON_LAMP_CARS_SLOTS, changed = 0;
    for (unsigned i=0; i<n; ++i) {
        uint32_t r = M32(list+4*i), s = shadow+0x60*i, rgb;
        if (!r || !carbon_lamp_cars_street(r)) continue;
        rgb = M32(r+0xc);
        float authored[3] = {(rgb&255)/255.f,((rgb>>8)&255)/255.f,((rgb>>16)&255)/255.f};
        float y = lighting_colour_luminance(authored);
        if (!(y > 0)) continue;
        memcpy(G+s,G+r,0x60);
        M32(s+0xc) = (rgb&0xff000000u) | warm[0] | (uint32_t)warm[1]<<8 | (uint32_t)warm[2]<<16;
        MF32(list+0x60+4*i) *= y/warm_y;
        M32(list+4*i) = s;
        ++changed;
    }
    if (diag_on && changed) {
        static unsigned recorded;
        if (recorded < 4) {
            ++recorded;
            diag_event("lamplight cars warm=%u/%u bytes=%u/%u/%u",changed,n,warm[0],warm[1],warm[2]);
        }
    }
}
