/* Converted reflective roads pass local positions to world-space headlights.
 * Only the converter's origin translation opts in; native draws stay retail. */
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

uint32_t *carbon_road_headlight_shader(const uint32_t *original, uint32_t count,
                                      const uint32_t *current, uint32_t current_count,
                                      uint32_t *patched_count) {
    uint64_t hash = 1469598103934665603ull;
    for (size_t k = 0; k < (size_t)count * 4; ++k)
        hash = (hash ^ ((const unsigned char *)original)[k]) * 1099511628211ull;
    uint32_t output;
    switch (hash) {
        case 0x932f3e4ad7bf792dull: output = 0xe0000005u; break;
        case 0x5b4881f8f96db47cull: output = 0xe0000003u; break;
        default: return NULL;
    }
    if (!current_count || current[current_count-1] != 0xffffu) return NULL;
    uint32_t *out = (uint32_t *)malloc((size_t)(current_count + 16) * sizeof *out);
    if (!out) return NULL;
    memcpy(out, current, (size_t)(current_count-1) * sizeof *out);
    /* c244..246 = world columns; c247.w = converted road, c247.z = zero.
     * The original mov supplies W and all four components on identity draws.
     * Both reviewed programs leave these constants unused. */
    const uint32_t tail[] = {
        0x02010029u, 0xa0ff00f7u, 0xa0aa00f7u, /* if_gt c247.w,c247.z */
        0x03000009u, output | 0x10000u, 0x90e40000u, 0xa0e400f4u,
        0x03000009u, output | 0x20000u, 0x90e40000u, 0xa0e400f5u,
        0x03000009u, output | 0x40000u, 0x90e40000u, 0xa0e400f6u,
        0x0000002bu, 0x0000ffffu
    };
    memcpy(out + current_count-1, tail, sizeof tail);
    *patched_count = current_count + 16;
    return out;
}

#ifndef CARBON_ROAD_SHADER_ONLY
#include "host.h"

/* 0071E660(this, world, view, flag): unlike cmWorldMat, this argument is
 * available even when the native road program optimized that parameter out. */
void carbon_road_headlight_world(Cpu *c, void (*original)(Cpu *)) {
    uint32_t address = M32(c->esp + 4);
    float world[16], constants[4][4] = {{0}};
    memcpy(world, G + address, sizeof world);
    int translated = 1;
    for (unsigned row = 0; row < 4; ++row)
        for (unsigned col = 0; col < 4; ++col) {
            /* Native props can also use this program with nonidentity worlds.
             * Match the converted road placement exactly, without an epsilon. */
            float expected = row == col ? 1.0f : row == 3 && col == 0 ? 8192.0f : 0.0f;
            if (world[row*4+col] != expected) translated = 0;
            if (col < 3) constants[col][row] = world[row*4+col];
        }
    constants[3][3] = translated;
    original(c);
    uint32_t device = M32(0x00AB0ABCu), vt = device ? M32(device) : 0;
    if (!vt) return;
    Cpu upload = *c;
    upload.esp -= sizeof constants;
    memcpy(G + upload.esp, constants, sizeof constants);
    uint32_t args[] = {device,244,upload.esp,4};
    call_guest(&upload,M32(vt+94*4),4,args);
}
#endif
