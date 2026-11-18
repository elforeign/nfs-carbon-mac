/* Exact world programs only. RGB changes; alpha/fog/inputs stay native. */
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

static uint64_t carbon_dn_shader_key(const uint32_t *tokens, uint32_t count) {
    uint64_t hash = 1469598103934665603ull;
    const unsigned char *bytes = (const unsigned char *)tokens;
    for (size_t k = 0; k < (size_t)count * 4; ++k)
        hash = (hash ^ bytes[k]) * 1099511628211ull;
    return hash;
}

static unsigned carbon_dn_register_type(uint32_t token) {
    return ((token >> 28) & 7) | ((token >> 8) & 24);
}

/* Source effect 5 retains the native glass inputs, with its own ambient and
 * additive reflection contract. c243.w / pixel c31.x are the day weight of
 * tagged draws, blending that contract over the native colour.
 * A zero weight executes the original native program without RGB changes. */
static uint32_t *carbon_facade_shader_variant(const uint32_t *tokens, uint32_t count,
                                              uint32_t *patched_count) {
    uint64_t key = carbon_dn_shader_key(tokens, count);
    uint32_t output = 0, colour = 2;
    int pixel = 0, legacy = 0;
    switch (key) {
        case 0x6eecdbee856b7096ull: output = 0xe0070001u; break;
        case 0x7d48583d0e4407d9ull: output = 0xd0070000u; break;
        case 0xab265f28baa17c1cull: output = 0xd0070000u; colour = 1; break;
        case 0x3767c01635c2bca6ull: output = 0xd0070000u; break;
        case 0xe1e01a64dc43cf1full:
        case 0x045c4f88d6510c65ull: pixel = 1; break;
        case 0xa391a8caa6c366acull: pixel = legacy = 1; break;
        default: return NULL; /* The low-LOD PS already multiplies diffuse RGB. */
    }
    if (!count || tokens[count-1] != 0xffffu) return NULL;
    uint32_t extra[20], n = 0, insert = count-1, copy = 0;
    if (!pixel) {
        /* The native colour has one write, a multiply; repeat it into r10. */
        unsigned writes = 0;
        for (uint32_t i=2; i+2<count; ++i)
            if (tokens[i] == output && (tokens[i-1] & 0xffffu) == 5) { copy=i; ++writes; }
        if (writes != 1) return NULL;
        const uint32_t tail[] = {
            0x02010029u, 0xa0ff00f3u, 0xa1ff00f3u, /* if_gt c243.w,-c243.w */
            0x03000005u, 0x8007000bu, 0x90e40000u | colour, 0xa0e400f3u,
            0x04000012u, output, 0xa0ff00f3u, 0x80e4000bu, 0x80e4000au,
            0x0000002bu
        };
        memcpy(extra, tail, sizeof tail); n = sizeof tail / 4;
    } else {
        const uint32_t lrp[] = {0x04000012u,0x802f0000u,0x80ff0001u,0x80e40002u,0x80e40003u};
        const uint32_t old_lrp[] = {0x00000012u,0x800f0000u,0x80ff0000u,0xb0e40001u,0xb0e40000u};
        const uint32_t *pattern = legacy ? old_lrp : lrp;
        unsigned matches = 0;
        for (uint32_t i=1; i+5<count; ++i)
            if (!memcmp(tokens+i,pattern,sizeof lrp)) { insert=i+5; ++matches; }
        if (matches != 1) return NULL;
        /* Preserve native output alpha. The legacy lrp consumes its own alpha
         * register, so save the saturated texture alpha before that operation.
         * The additive result goes to a free temporary (legacy r1, else r5). */
        uint32_t temp = legacy ? 1 : 5;
        const uint32_t tail[] = {
            0x02010029u, 0xa000001fu, 0xa100001fu, /* if_gt c31.x,-c31.x */
            0x04000004u, 0x80070000u | temp, 0x80ff0001u,
            legacy ? 0xb0e40001u : 0x80e40002u,
            legacy ? 0xb0e40000u : 0x80e40003u,
            0x04000012u, 0x80070000u, 0xa000001fu, 0x80e40000u | temp, 0x80e40000u,
            0x0000002bu
        };
        memcpy(extra,tail,sizeof tail); n = sizeof tail / 4;
    }
    uint32_t added = n + (legacy ? 3 : 0) + (copy ? 4 : 0);
    uint32_t *out = (uint32_t *)malloc((size_t)(count+added)*4);
    if (!out) return NULL;
    uint32_t before = insert - (legacy ? 5 : 0);
    uint32_t at = 0;
    if (copy) {
        memcpy(out,tokens,(size_t)(copy+3)*4); at = copy+3;
        out[at++]=0x03000005u; out[at++]=0x8007000au;
        out[at++]=tokens[copy+1]; out[at++]=tokens[copy+2];
        memcpy(out+at,tokens+copy+3,(size_t)(before-copy-3)*4); at += before-copy-3;
    } else {
        memcpy(out,tokens,(size_t)before*4); at = before;
    }
    if (legacy) {
        out[at++]=0x02000001u; out[at++]=0x80180001u; out[at++]=0xb0ff0000u;
        memcpy(out+at,tokens+before,5*4); at+=5;
    }
    memcpy(out+at,extra,n*4); at+=n;
    memcpy(out+at,tokens+insert,(size_t)(count-insert)*4);
    *patched_count=count+added;
    return out;
}

/* c240 = light.xyz/0; c241 = diffuse.rgb/night; c242 = ambient.rgb/0.
 * The six identities cover nine embedded programs across SM2/SM3 techniques.
 * No register in these programs overlaps r10/r11 or c240..242.
 * With trees, c251.w > 0 (converted source trees only) replaces the day colour
 * by the source tree contract: c250.rgb x min(max(N.L,0) + c251.w, c250.w)
 * + c251.rgb, with the source x2 folded into c250.rgb/c251.rgb. */
static uint32_t *carbon_dn_world_variant(const uint32_t *tokens, uint32_t count,
                                         uint32_t *patched_count, int trees) {
    uint64_t key = carbon_dn_shader_key(tokens, count);
    switch (key) {
        case 0x90620a402e8e771eull: case 0x43f3f983abe0f7bbull:
        case 0x198fc6c9e7ad5d79ull: case 0x0fc8245c113450afull:
        case 0x5b4881f8f96db47cull: case 0x932f3e4ad7bf792dull: break;
        default: return NULL;
    }
    if (count < 4 || (tokens[0] >> 16) != 0xfffe || tokens[count-1] != 0xffff) return NULL;
    unsigned normal = 16, colour = 16, colour_type = 5;
    if ((tokens[0] & 0xff00) >= 0x300) colour_type = 6;
    else colour = 0; /* SM2 oD0, rather than SM3's semantic output. */
    uint32_t rgb = 0;
    unsigned writes = 0;
    for (uint32_t i = 1; i < count - 1;) {
        unsigned op = tokens[i] & 0xffff;
        uint32_t length = op == 0xfffe ? (tokens[i] >> 16) & 0x7fff : (tokens[i] >> 24) & 15;
        if (!length || i + length >= count) return NULL;
        if (op == 31 && length == 2) {
            unsigned type = carbon_dn_register_type(tokens[i+2]);
            unsigned usage = tokens[i+1] & 31, index = (tokens[i+1] >> 16) & 15;
            if (type == 1 && usage == 3 && !index) normal = tokens[i+2] & 2047;
            if (type == 6 && usage == 10 && !index) colour = tokens[i+2] & 2047;
        } else if (op != 0xfffe && op != 81) {
            uint32_t dest = tokens[i+1];
            if (carbon_dn_register_type(dest) == colour_type && (dest & 2047) == colour &&
                (dest & 0x70000)) {
                if ((dest & 0xf0000) != 0x70000) return NULL;
                rgb = i + 1;
                ++writes;
            }
        }
        i += 1 + length;
    }
    if (normal >= 16 || colour >= 16 || writes != 1 || !rgb) return NULL;
    uint32_t added = trees ? 18 + 29 : 18;
    uint32_t *out = (uint32_t *)malloc((size_t)(count + added) * sizeof *out);
    if (!out) return NULL;
    memcpy(out, tokens, (size_t)(count - 1) * sizeof *out);
    uint32_t output = tokens[rgb] & ~0x00f00000u; /* Preserve native RGB clamp in r11. */
    out[rgb] = (tokens[rgb] & 0x0fff0000u) | 0x8000000bu;
    const uint32_t tail[] = {
        0x03000008u, 0x8001000au, 0x90e40000u | normal, 0xa0e400f0u, /* dp3 r10.x,vN,c240 */
        0x0300000bu, 0x8001000au, 0x8000000au, 0xa0ff00f0u,       /* max r10.x,r10.x,c240.w */
        0x04000004u, 0x8007000au, 0xa0e400f1u, 0x8000000au, 0xa0e400f2u, /* mad day,D,N.L,A */
    };
    const uint32_t tree[] = {
        0x02010029u, 0xa0ff00fbu, 0xa1ff00fbu,                     /* if_gt c251.w,-c251.w */
        0x03000008u, 0x8001000au, 0x90e40000u | normal, 0xa0e400f0u, /* dp3 r10.x,vN,c240 */
        0x0300000bu, 0x8001000au, 0x8000000au, 0xa0ff00f0u,       /* max r10.x,r10.x,c240.w */
        0x03000002u, 0x8001000au, 0x8000000au, 0xa0ff00fbu,       /* add r10.x,r10.x,wrap */
        0x0300000au, 0x8001000au, 0x8000000au, 0xa0ff00fau,       /* min r10.x,r10.x,1 */
        0x03000005u, 0x8001000au, 0x8000000au, 0xa0ff00f2u,       /* mul r10.x,r10.x,c242.w */
        0x04000004u, 0x8007000au, 0xa0e400fau, 0x8000000au, 0xa0e400fbu, /* mad day,2SD,x,2F */
        0x0000002bu
    };
    const uint32_t end[] = {
        0x04000012u, output, 0xa0ff00f1u, 0x80e4000bu, 0x80e4000au, /* lrp output,n,bake,day */
        0x0000ffffu
    };
    uint32_t at = count - 1;
    memcpy(out + at, tail, sizeof tail); at += sizeof tail / 4;
    if (trees) { memcpy(out + at, tree, sizeof tree); at += sizeof tree / 4; }
    memcpy(out + at, end, sizeof end);
    *patched_count = count + added;
    return out;
}
static uint32_t *carbon_dn_shader_variant(const uint32_t *tokens, uint32_t count,
                                         uint32_t *patched_count) {
    return carbon_dn_world_variant(tokens, count, patched_count, 0);
}
