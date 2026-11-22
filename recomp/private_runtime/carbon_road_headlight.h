/* Converted reflective roads pass local vertex and eye positions to world-space headlights.
 * The converted material selects the transform at draw time; native draws stay retail. */
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
    const int sm3 = original[0] == 0xfffe0300u;
    /* c244..246 = world columns; c247.w = converted road, c247.z = zero.
     * The original mov supplies W and all four components on identity draws.
     * Both reviewed programs leave these constants unused. */
    const uint32_t position[] = {
        0x02010029u, 0xa0ff00f7u, 0xa0aa00f7u, /* if_gt c247.w,c247.z */
        0x03000009u, output | 0x10000u, 0x90e40000u, 0xa0e400f4u,
        0x03000009u, output | 0x20000u, 0x90e40000u, 0xa0e400f5u,
        0x03000009u, output | 0x40000u, 0x90e40000u, 0xa0e400f6u
    };
    /* The native SM3 shader exports c6 (cvLocalEyePos) in o8.xyz.
     * r0 is dead here, and the shader defines c8.w as 1.0. */
    const uint32_t eye[] = {
        0x02000001u, 0x80070000u, 0xa0e40006u, /* mov r0.xyz,c6 */
        0x02000001u, 0x80080000u, 0xa0ff0008u, /* mov r0.w,c8.w */
        0x03000009u, 0xe0010008u, 0x80e40000u, 0xa0e400f4u,
        0x03000009u, 0xe0020008u, 0x80e40000u, 0xa0e400f5u,
        0x03000009u, 0xe0040008u, 0x80e40000u, 0xa0e400f6u
    };
    const uint32_t footer[] = {0x0000002bu, 0x0000ffffu}; /* endif, end */
    const size_t size = (size_t)(current_count - 1) * sizeof(uint32_t);
    const size_t eye_size = sm3 ? sizeof eye : 0;
    uint32_t *out = (uint32_t *)malloc(size + sizeof position + eye_size + sizeof footer);
    if (!out) return NULL;
    memcpy(out, current, size);
    uint32_t *tail = out + current_count - 1;
    memcpy(tail, position, sizeof position);
    tail += sizeof position / sizeof *tail;
    memcpy(tail, eye, eye_size);
    tail += eye_size / sizeof *tail;
    memcpy(tail, footer, sizeof footer);
    *patched_count = (uint32_t)(tail - out) + sizeof footer / sizeof *tail;
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
    for (unsigned row = 0; row < 4; ++row)
        for (unsigned col = 0; col < 4; ++col) {
            if (col < 3) constants[col][row] = world[row*4+col];
        }
    /* The final material draw sets c247.w. Reset here as well, so no world
     * change can inherit a previous converted draw's selector. */
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
