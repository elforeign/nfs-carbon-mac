/* Street flares follow the existing clock only during the native scene batch;
 * car flares and the headlight cones follow it at their own callers. */
#include "host.h"
#include <math.h>
#include <stdlib.h>
#include <strings.h>

extern float carbon_daynight_night(void);
extern uint64_t diag_current_frame(void);

/* The night blend is one half at dusk; lamps are already fully on then. */
static const float carbon_dn_lamps_dusk_gain = 2.0f;
enum {
    CARBON_DN_CAR_FLARE_RET = 0x007CC646u, /* 007CBC40's flare call */
    CARBON_DN_LEFT_HEAD = 0x9DB90133u, CARBON_DN_RIGHT_HEAD = 0xD09091C6u,
    CARBON_DN_LEFT_BRAKE = 0x31A66786u, CARBON_DN_RIGHT_BRAKE = 0xBF700A79u,
};
float carbon_dn_lamps_level(void) {
    return fminf(1.0f, carbon_dn_lamps_dusk_gain * carbon_daynight_night());
}
static struct CarbonLampScope {
    unsigned depth;
    float factor;
} carbon_dn_lamps_scope;
static struct CarbonLampMeasure {
    int active;
    unsigned queued;
    double sum;
} carbon_dn_lamps_measure;

void carbon_daynight_lamps_world(Cpu *c, void (*original)(Cpu *)) {
    float factor = carbon_dn_lamps_level();
    struct CarbonLampScope saved = carbon_dn_lamps_scope;
    struct CarbonLampMeasure saved_measure;
    int diagnostics = diag_on;
    uint64_t frame = 0;
    int measure = 0;
    if (diagnostics && M32(0x00A99BBCu) == 6 && M32(M32(c->esp + 4) + 8) == 1) {
        /* Present increments its counter before capturing the rendered frame. */
        static uint64_t recorded;
        frame = diag_current_frame() + 1;
        if (frame != recorded && diag_shot_due(frame)) {
            recorded = frame;
            measure = 1;
        }
    }
    if (diagnostics) {
        saved_measure = carbon_dn_lamps_measure;
        carbon_dn_lamps_measure = (struct CarbonLampMeasure){measure, 0, 0};
    }
    carbon_dn_lamps_scope = (struct CarbonLampScope){saved.depth + 1, factor};
    original(c); /* Other scene flare kinds retain their native behavior. */
    if (diagnostics) {
        if (measure)
            diag_event("carbon_daynight_lamps: frame=%llu queued=%u intensity_sum=%.9g",
                (unsigned long long)frame, carbon_dn_lamps_measure.queued, carbon_dn_lamps_measure.sum);
        carbon_dn_lamps_measure = saved_measure;
    }
    carbon_dn_lamps_scope = saved;
}

void carbon_daynight_lamps_flare(Cpu *c, void (*original)(Cpu *)) {
    /* Native scene type 13 is the street-light flare. The scene batch also
     * contains markers and other effects; vehicle flares use another caller. */
    int street = carbon_dn_lamps_scope.depth && M8(M32(c->esp + 8) + 0x2c) == 13;
    float factor = carbon_dn_lamps_scope.factor;
    if (M32(c->esp) == CARBON_DN_CAR_FLARE_RET && M32(c->esp + 8)) {
        /* Record+8 names the lamp: head flares, and tail flares while
         * unbraked (exactly 0.5); braked, reverse and cop lamps stay native. */
        uint32_t lamp = M32(M32(c->esp + 8) + 8);
        float in;
        memcpy(&in, G + c->esp + 0x10, sizeof in);
        street = lamp == CARBON_DN_LEFT_HEAD || lamp == CARBON_DN_RIGHT_HEAD ||
                 ((lamp == CARBON_DN_LEFT_BRAKE || lamp == CARBON_DN_RIGHT_BRAKE) && in == 0.5f);
        factor = carbon_dn_lamps_level();
    }
    int scale = street && factor < 1;
    int measure = diag_on && street && carbon_dn_lamps_measure.active &&
                  M32(c->esp) != CARBON_DN_CAR_FLARE_RET;
    if (scale && factor == 0) {
        c->eax = 0;
        c->esp += 4; /* Native cdecl flare return; caller retains its arguments. */
        return;
    }
    if (!scale && !measure) { original(c); return; }
    /* 0074D330 pushes ebp, then reads arg 4 through ebp+14: entry esp+10. */
    uint32_t word = c->esp + 0x10, saved = M32(word);
    float intensity;
    memcpy(&intensity, &saved, sizeof intensity);
    if (scale) {
        intensity *= factor;
        memcpy(G + word, &intensity, sizeof intensity);
    }
    /* 0074E0FB selects this queue; 00749D30 increments its +10 count only
     * after the renderer's visibility/type/size and queue-capacity checks. */
    uint32_t before = measure ? M32(0x00B4CF38u) : 0;
    original(c);
    if (scale) M32(word) = saved;
    if (measure) {
        unsigned queued = M32(0x00B4CF38u) - before;
        carbon_dn_lamps_measure.queued += queued;
        carbon_dn_lamps_measure.sum += queued * (double)intensity;
    }
}

void carbon_daynight_lamps_cones(Cpu *c, void (*original)(Cpu *)) {
    if (carbon_dn_lamps_level() > 0) { original(c); return; }
    /* By day both headlight cone slots take 0074A4E0's own unused-slot path:
     * an all-zero matrix with element 15 at -10000 and the position parked. */
    static const uint32_t slots[] = {0x00B4B390u, 0x00B4B410u};
    for (unsigned k = 0; k < 2; ++k) {
        uint32_t light = M32(slots[k] + 0x40);
        if (!light) continue;
        Cpu call = *c;
        call.esp -= 0x40;
        memset(G + call.esp, 0, 0x40);
        M32(call.esp + 0x3c) = 0xC61C4000u;
        call.ecx = light;
        uint32_t args[] = {call.esp, 0};
        call_guest(&call, 0x004822F0u, 2, args);
        for (unsigned i = 0; i < 3; ++i) M32(light + 0x40 + 4 * i) = 0xC61C4000u;
    }
    c->esp += 4; /* Native void return; no arguments. */
}

void carbon_daynight_lamps_traffic_quad(Cpu *c, void (*original)(Cpu *)) {
    static int enabled = -1;
    if (enabled < 0) {
        const char *setting = getenv("NFS_DAYNIGHT_DAYLAMPS");
        enabled = !setting || !(!strcmp(setting, "0") || !strcasecmp(setting, "off"));
    }
    if (enabled && carbon_dn_lamps_level() == 0) {
        /* 007BE170 emits the 2PLAYERHEADLIGHT1 ground quad. Its void
         * ret 0xC pops three arguments as well as the return address. */
        c->esp += 0x10;
        return;
    }
    original(c);
}
