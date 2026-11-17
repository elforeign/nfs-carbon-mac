/* Optional home speaker geometry; native gain order C, FR, BR, BL, FL, LFE. */
#include "runtime.h"
#include "game_image.h"
#include <stdlib.h>

static int carbon_posaudio_enabled(void) {
    static int enabled = -1;
    if (enabled < 0) {
        const char *value = getenv("NFS_CARBON_POS_LAYOUT");
        enabled = value && !strcmp(value, "itu");
    }
    return enabled;
}

/* Nearest 16-bit turns to 0, +30, +110, -110, -30 degrees. Using the
 * same anchors for the panner and defaults puts a fixed source on one speaker. */
static void carbon_posaudio_gains(uint16_t azimuth, float gains[6]) {
    static const unsigned angles[] = {0, 5461, 20025, 45511, 60075, 65536};
    memset(gains, 0, 6 * sizeof *gains);
    for (unsigned i = 0; i < 5; ++i) {
        if (azimuth >= angles[i] && azimuth < angles[i + 1]) {
            double phase = (azimuth - angles[i]) * (1.57079632679489661923 /
                                                      (angles[i + 1] - angles[i]));
            gains[i] = (float)cos(phase);
            gains[(i + 1) % 5] = (float)sin(phase);
            break;
        }
    }
}

static uint16_t carbon_posaudio_default(uint16_t angle) {
    switch (angle) {
        case 0x2000: return 5461;
        case 0x6000: return 20025;
        case 0xA000: return 45511;
        case 0xE000: return 60075;
        default: return angle;
    }
}

void carbon_posaudio_pan(Cpu *c, void (*original)(Cpu *)) {
#if PRIVATE_CARBON_SKIPFE
    if (carbon_posaudio_enabled() && M8(0x00BBF357u) == 5) {
        uint16_t azimuth = M16(c->esp + 4);
        uint32_t output = M32(c->esp + 8);
        float gains[6];
        /* Retain native scratch writes, return state and calling convention. */
        original(c);
        carbon_posaudio_gains(azimuth, gains);
        memcpy(G + output, gains, sizeof gains);
        return;
    }
#endif
    original(c);
}

void carbon_posaudio_initialize(Cpu *c, void (*original)(Cpu *)) {
    original(c);
#if PRIVATE_CARBON_SKIPFE
    if (!carbon_posaudio_enabled()) return;
    MF32(0x00BBF44Cu) = 30.0f;
    MF32(0x00BBF450u) = 110.0f;
    MF32(0x00BBF454u) = 250.0f;
    MF32(0x00BBF458u) = 330.0f;
    /* Native stereo, quad and six-channel word rows. Centre/LFE stay zero. */
    for (unsigned channels = 2; channels <= 6; channels += 2) {
        uint32_t row = 0x00BBF3CCu + channels * 12;
        for (unsigned i = 0; i < channels; ++i)
            M16(row + i * 2) = carbon_posaudio_default(M16(row + i * 2));
    }
#endif
}

void carbon_posaudio_stream_defaults(Cpu *c, void (*original)(Cpu *)) {
#if PRIVATE_CARBON_SKIPFE
    uint32_t stream = M32(c->esp + 4);
#endif
    original(c);
#if PRIVATE_CARBON_SKIPFE
    if (!carbon_posaudio_enabled()) return;
    unsigned channels = M8(stream + 0x23);
    if (channels != 2 && channels != 4 && channels != 6) return;
    uint32_t children = M32(0x00BBF3D0u);
    for (unsigned i = 0; i < channels; ++i) {
        int16_t index = (int16_t)M16(stream + 4 + i * 2);
        uint32_t angle = children + (uint32_t)((int32_t)index * 0x84) + 0x1C;
        M16(angle) = carbon_posaudio_default(M16(angle));
    }
#endif
}
