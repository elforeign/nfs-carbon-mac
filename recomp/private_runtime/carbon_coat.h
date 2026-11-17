/* Lacquer reflection for the car paint programs (on by default; NFS_CARBON_COAT=0 keeps retail).
 *
 * Ten exact programs (FNV-1a 64 of the bytecode): car t0/t2/lowlod and car_normalmap t0/t2.
 * The same programs draw every car material, so paint is selected per draw from the
 * material record the game already uploads: cvVinylScales.x == 0 and .z == 0 (the gloss,
 * metallic, pearl, candy and iridescent paint families; chrome paint has .z = .75) with a
 * non-zero retail reflection weight (matte paint has none). Every other record keeps the
 * retail arithmetic bit for bit.
 *
 * Vertex program: one more interpolant, xyz = the reflection without the horizon pull in
 * view space, w = F = .04 + .96 (1 - N.V)^5.
 * Pixel program, paint only: the cube is read along that vector, the reflection weight
 * becomes F (the retail doubling is cancelled) and the layer below is scaled by 1 - F.
 *
 * NFS_CARBON_MATERIALS (on by default, 0 keeps retail; needs the lacquer on) gives four more record
 * families the same treatment, selected from the record constants the vertex program
 * already receives and carried to the pixel program in the same interpolant (w + 2, or
 * + 4 for clear glass):
 *   chrome       cvEnvmapMin (.5,.5,.5), range >= 0: conductor Fresnel, F0 .5545
 *   wheel paint  cvEnvmapMin 1, range -.8: the paint lacquer, F0 .04
 *   glass        cvPowers (1,1,1), envmap clamp < 1: pane reflectance 2F/(1+F), F0 .0432;
 *                transmittance .75 for the clear record (alpha .5), the record's own
 *                1 - alpha for tint films; the tint colour fills the absorbed share
 *                brake-light covers use the tinted path; texture alpha and bulbs stay native
 *   chrome paint cvVinylScales.x == 0, .z > 0 (pixel side): F0 .5545 x the record tint
 * Matte paint and every other record keep the retail arithmetic. */
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

static int carbon_coat_materials;
#define CM_D(reg, mask) (0x80000000u | ((uint32_t)(mask) << 16) | (reg))   /* temporary, write mask */
#define CM_R(reg, swizzle) (0x80000000u | ((uint32_t)(swizzle) << 16) | (reg))
#define CM_C(reg, swizzle) (0xa0000000u | ((uint32_t)(swizzle) << 16) | (reg))
#define CM_NEG 0x01000000u
enum { CM_X = 0x00, CM_Y = 0x55, CM_Z = 0xaa, CM_W = 0xff, CM_A = 0xe4 };
enum { CM_ADD = 0x03000002, CM_MUL = 0x03000005, CM_MAD = 0x04000004, CM_RCP = 0x02000006, CM_MIN = 0x0300000a,
       CM_MAX = 0x0300000b, CM_SLT = 0x0300000c, CM_SGE = 0x0300000d, CM_LRP = 0x04000012, CM_ABS = 0x02000023,
       CM_DP3 = 0x03000008, CM_MOV = 0x02000001, CM_CMP = 0x04000058 };

static unsigned carbon_coat_type(uint32_t token) {
    return ((token >> 28) & 7) | ((token >> 8) & 24);
}
static int carbon_coat_plain(uint32_t token, unsigned type) {
    return carbon_coat_type(token) == type && (token & 0x0fff0000u) == 0x00e40000u;
}
static uint32_t carbon_coat_length(uint32_t token) {
    return (token & 0xffff) == 0xfffe ? (token >> 16) & 0x7fff : (token >> 24) & 15;
}

/* Copies tokens[0..at) then the insertion; returns the new write position. */
static uint32_t carbon_coat_put(uint32_t *out, uint32_t n, const uint32_t *words, size_t bytes) {
    memcpy(out + n, words, bytes);
    return n + (uint32_t)(bytes / sizeof *words);
}

static uint32_t *carbon_coat_vertex(const uint32_t *t, uint32_t count, uint32_t *patched_count, unsigned record) {
    unsigned sm3 = (t[0] & 0xff00) >= 0x300, position = 16, normal = 16, eye = 256, view = 256;
    unsigned materials = carbon_coat_materials, colour = sm3 ? 256 : 0, alphas = 0;
    uint32_t first = 0, alpha = 0;
    for (uint32_t i = 1; i < count - 1;) {
        unsigned op = t[i] & 0xffff;
        uint32_t length = carbon_coat_length(t[i]);
        if (i + length >= count) return NULL;
        if (op != 0xfffe && !first) first = i;
        if (op == 31 && length == 2 && carbon_coat_type(t[i+2]) == 1) {
            unsigned usage = t[i+1] & 31, index = (t[i+1] >> 16) & 15;
            if (usage == 0 && !index) position = t[i+2] & 2047;
            if (usage == 3 && !index) normal = t[i+2] & 2047;
        } else if (op == 31 && length == 2 && carbon_coat_type(t[i+2]) == 6) {
            if ((t[i+2] & 2047) == 11 || (t[i+1] & 0x000f001f) == 0x00070005) return NULL;
            if ((t[i+1] & 0x000f001f) == 0x0000000a) colour = t[i+2] & 2047;
        } else if (op == 2 && length == 3 && eye == 256) { /* add r, cEye, -vPos (either order) */
            for (int k = 0; k < 2; ++k)
                if (carbon_coat_plain(t[i+2+k], 2) && t[i+3-k] == (0x91e40000u | position))
                    eye = t[i+2+k] & 2047;
        } else if (op == 8 && length == 3 && view == 256 && carbon_coat_type(t[i+1]) == 6 &&
                   (t[i+1] & 0x000f0000u) == 0x00010000u && carbon_coat_plain(t[i+3], 2)) {
            view = t[i+3] & 2047; /* dp3 oReflection.x, r, cmWorldView[0] */
        } else if (op != 0xfffe && op != 81 && op != 31) {
            unsigned type = carbon_coat_type(t[i+1]), number = t[i+1] & 2047;
            if (type == 0 && number >= 10) return NULL;
            if (!sm3 && type == 6 && number == 7) return NULL;
            if (materials) { /* the one write of the diffuse alpha; r8/r9 and c96..c99 must be free */
                if (type == (sm3 ? 6u : 5u) && number == colour && (t[i+1] & 0x00080000u)) { alpha = i; ++alphas; }
                if (type == 0 && number >= 8) return NULL;
                for (uint32_t k = 2; k <= length; ++k)
                    if (carbon_coat_type(t[i+k]) == 2 && (t[i+k] & 2047) >= 95) return NULL;
            }
        }
        i += 1 + length;
    }
    if (!first || position >= 16 || normal >= 16 || eye >= 95 || view >= 93) return NULL;
    if (materials && (alphas != 1 || alpha < first)) return NULL;
    const uint32_t P = position, N = normal, E = eye, W = view, K = 95, O = sm3 ? 11 : 7;
    const uint32_t head[] = {
        0x05000051u, 0xa00f0000u | K, 0x00000000u, 0x3f800000u, 0x3d23d70au, 0x3f75c28fu, /* 0,1,.04,.96 */
        0x0200001fu, 0x80070005u, 0xe00f000bu,                    /* dcl_texcoord7 o11 (SM3 only) */
    };
    const uint32_t tail[] = {
        0x03000002u, 0x8007000au, 0xa0e40000u | E, 0x91e40000u | P,   /* add r10.xyz, cEye, -vPos */
        0x02000024u, 0x8007000bu, 0x80e4000au,                        /* nrm r11.xyz, r10 */
        0x03000008u, 0x8008000au, 0x80e4000bu, 0x90e40000u | N,       /* dp3 r10.w, r11, vN */
        0x03000002u, 0x8008000bu, 0x80ff000au, 0x80ff000au,           /* add r11.w, r10.w, r10.w */
        0x04000004u, 0x8007000au, 0x90e40000u | N, 0x80ff000bu, 0x81e4000bu, /* mad r10.xyz, vN, r11.w, -r11 */
        0x03000008u, 0xe0010000u | O, 0x80e4000au, 0xa0e40000u | W,   /* dp3 o.x, r10, view[0] */
        0x03000008u, 0xe0020000u | O, 0x80e4000au, 0xa0e40000u | (W+1),
        0x03000008u, 0xe0040000u | O, 0x80e4000au, 0xa0e40000u | (W+2),
        0x0300000bu, 0x8008000au, 0x80ff000au, 0xa0000000u | K,       /* max r10.w, r10.w, 0 */
        0x03000002u, 0x8008000au, 0xa0550000u | K, 0x81ff000au,       /* add r10.w, 1, -r10.w */
        0x03000005u, 0x8008000bu, 0x80ff000au, 0x80ff000au,           /* mul r11.w, r10.w, r10.w */
        0x03000005u, 0x8008000bu, 0x80ff000bu, 0x80ff000bu,           /* mul r11.w, r11.w, r11.w */
        0x03000005u, 0x8008000au, 0x80ff000au, 0x80ff000bu,           /* mul r10.w, r10.w, r11.w */
        0x04000004u, 0xe0080000u | O, 0x80ff000au, 0xa0ff0000u | K, 0xa0aa0000u | K, /* mad o.w, r10.w, .96, .04 */
        0x0000ffffu
    };
    /* Record constants: cvDiffuseMin, +2 cvEnvmapMin, +3 cvEnvmapRange, +4 cvPowers, +5 cvClampAndScales. */
    const uint32_t Dm = record, Em = record + 2, Er = record + 3, Pw = record + 4, Cl = record + 5, C1 = 96, C2 = 97, C3 = 98, C4 = 99;
    const uint32_t constants[] = {
        0x05000051u, 0xa00f0000u | C1, 0x3f000000u, 0x3c23d70au, 0x3f4ccccdu, 0x3f266666u, /* .5, .01, .8, .65 */
        0x05000051u, 0xa00f0000u | C2, 0x3f0df3b6u, 0x3ee41893u, 0x3d30f27cu, 0x3f74f0d8u, /* .5545, .4455, .0432, .9568 */
        0x05000051u, 0xa00f0000u | C3, 0x3f400000u, 0x3f8b8efcu, 0x40000000u, 0x3f7d70a4u, /* .75, 1/(1 - .08282), 2, .99 */
        0x05000051u, 0xa00f0000u | C4, 0x3fc00000u, 0x40200000u, 0x00000000u, 0x00000000u, /* 1.5, 2.5, 0, 0 */
    };
    const uint32_t classes[] = { /* r10.w = (1 - N.V)^5 on entry */
        CM_ADD, CM_D(11,3), CM_C(Em,0xa8), CM_C(C1,CM_X) | CM_NEG,     /* cvEnvmapMin.xz - .5 */
        CM_ABS, CM_D(11,3), CM_R(11,CM_A),
        CM_ADD, CM_D(11,1), CM_R(11,CM_X), CM_R(11,CM_Y),
        CM_SLT, CM_D(11,1), CM_R(11,CM_X), CM_C(C1,CM_Y),
        CM_SGE, CM_D(11,2), CM_C(Er,CM_X), CM_C(C1,CM_Y) | CM_NEG,
        CM_MUL, CM_D(11,1), CM_R(11,CM_X), CM_R(11,CM_Y),              /* r11.x: chrome */
        CM_ADD, CM_D(11,2), CM_C(Em,CM_X), CM_C(K,CM_Y) | CM_NEG,
        CM_ADD, CM_D(11,4), CM_C(Er,CM_X), CM_C(C1,CM_Z),
        CM_ABS, CM_D(11,6), CM_R(11,CM_A),
        CM_ADD, CM_D(11,2), CM_R(11,CM_Y), CM_R(11,CM_Z),
        CM_SLT, CM_D(11,2), CM_R(11,CM_Y), CM_C(C1,CM_Y),              /* r11.y: wheel paint */
        CM_ADD, CM_D(8,7), CM_C(Pw,CM_A), CM_C(K,CM_Y) | CM_NEG,
        CM_ABS, CM_D(8,7), CM_R(8,CM_A),
        CM_DP3, CM_D(8,1), CM_R(8,CM_A), CM_C(K,CM_Y),
        CM_SLT, CM_D(8,1), CM_R(8,CM_X), CM_C(C1,CM_Y),
        CM_SLT, CM_D(8,2), CM_C(Cl,CM_Y), CM_C(C3,CM_W),
        CM_MUL, CM_D(11,4), CM_R(8,CM_X), CM_R(8,CM_Y),                /* r11.z: glass */
        /* Brake-light cover: exact env minimum (1.5,1.5,1.5), zero range,
         * powers (1,2.5,1). Its native alpha 1 selects tinted glass (T0=0). */
        CM_ADD, CM_D(8,7), CM_C(Em,CM_A), CM_C(C4,CM_X) | CM_NEG,
        CM_ABS, CM_D(8,7), CM_R(8,CM_A),
        CM_DP3, CM_D(8,8), CM_R(8,CM_A), CM_C(K,CM_Y),
        CM_ABS, CM_D(8,7), CM_C(Er,CM_A),
        CM_DP3, CM_D(8,1), CM_R(8,CM_A), CM_C(K,CM_Y),
        CM_ADD, CM_D(8,8), CM_R(8,CM_W), CM_R(8,CM_X),
        CM_MOV, CM_D(8,7), CM_C(K,CM_Y),
        CM_MOV, CM_D(8,2), CM_C(C4,CM_Y),
        CM_ADD, CM_D(8,7), CM_C(Pw,CM_A), CM_R(8,CM_A) | CM_NEG,
        CM_ABS, CM_D(8,7), CM_R(8,CM_A),
        CM_DP3, CM_D(8,1), CM_R(8,CM_A), CM_C(K,CM_Y),
        CM_ADD, CM_D(8,8), CM_R(8,CM_W), CM_R(8,CM_X),
        CM_SGE, CM_D(8,8), CM_C(K,CM_X), CM_R(8,CM_W),
        CM_MAX, CM_D(11,4), CM_R(11,CM_Z), CM_R(8,CM_W),
        CM_SLT, CM_D(11,8), CM_C(Dm,CM_W), CM_C(C1,CM_W),              /* r11.w: clear glass */
        CM_MAD, CM_D(10,1), CM_R(10,CM_W), CM_C(K,CM_W), CM_C(K,CM_Z),   /* r10.x: lacquer F */
        CM_MAD, CM_D(10,2), CM_R(10,CM_W), CM_C(C2,CM_Y), CM_C(C2,CM_X), /* r10.y: chrome F */
        CM_MAD, CM_D(10,4), CM_R(10,CM_W), CM_C(C2,CM_W), CM_C(C2,CM_Z), /* r10.z: glass surface F */
        CM_ADD, CM_D(8,1), CM_R(10,CM_Z), CM_C(K,CM_Y),
        CM_RCP, CM_D(8,1), CM_R(8,CM_X),
        CM_MUL, CM_D(8,1), CM_R(8,CM_X), CM_R(10,CM_Z),
        CM_ADD, CM_D(8,1), CM_R(8,CM_X), CM_R(8,CM_X),                 /* r8.x: pane R = 2F/(1+F) */
        CM_ADD, CM_D(8,2), CM_C(K,CM_Y), CM_C(Dm,CM_W) | CM_NEG,
        CM_LRP, CM_D(8,2), CM_R(11,CM_W), CM_C(C3,CM_X), CM_R(8,CM_Y), /* normal transmittance */
        CM_ADD, CM_D(8,4), CM_C(K,CM_Y), CM_R(8,CM_X) | CM_NEG,
        CM_MUL, CM_D(8,2), CM_R(8,CM_Y), CM_R(8,CM_Z),
        CM_MUL, CM_D(8,2), CM_R(8,CM_Y), CM_C(C3,CM_Y),                /* T = T0 (1 - R)/(1 - R0) */
        CM_ADD, CM_D(8,2), CM_C(K,CM_Y), CM_R(8,CM_Y) | CM_NEG,
        CM_MAX, CM_D(8,2), CM_R(8,CM_Y), CM_C(C1,CM_Y),                /* r8.y: alpha = 1 - T */
        CM_RCP, CM_D(8,4), CM_R(8,CM_Y),
        CM_MUL, CM_D(8,4), CM_R(8,CM_Z), CM_R(8,CM_X),
        CM_MIN, CM_D(8,4), CM_R(8,CM_Z), CM_C(K,CM_Y),                 /* r8.z: R / alpha */
        CM_ADD, CM_D(10,2), CM_R(10,CM_Y), CM_R(10,CM_X) | CM_NEG,
        CM_ADD, CM_D(10,2), CM_R(10,CM_Y), CM_C(C3,CM_Z),
        CM_MAD, CM_D(10,8), CM_R(11,CM_X), CM_R(10,CM_Y), CM_R(10,CM_X),
        CM_MAD, CM_D(10,8), CM_R(11,CM_Y), CM_C(C3,CM_Z), CM_R(10,CM_W),
        CM_ADD, CM_D(8,8), CM_R(8,CM_Z), CM_R(10,CM_X) | CM_NEG,
        CM_ADD, CM_D(8,8), CM_R(8,CM_W), CM_C(C3,CM_Z),
        CM_MAD, CM_D(8,8), CM_R(11,CM_W), CM_C(C3,CM_Z), CM_R(8,CM_W),
        CM_MAD, 0xe0080000u | O, CM_R(11,CM_Z), CM_R(8,CM_W), CM_R(10,CM_W), /* o.w = F, or class weight + 2 (+ 4 clear glass) */
        CM_LRP, CM_D(9,8), CM_R(11,CM_Z), CM_R(8,CM_Y), CM_R(9,CM_W),
        CM_MOV, materials ? t[alpha+1] & 0xff0fffffu : 0, CM_R(9,CM_A),  /* the diffuse alpha, glass: 1 - T */
        0x0000ffffu
    };
    size_t head_bytes = sm3 ? sizeof head : 6 * sizeof *head;
    uint32_t *out = (uint32_t *)malloc(count * sizeof *out + head_bytes + sizeof tail + sizeof constants + sizeof classes);
    if (!out) return NULL;
    memcpy(out, t, first * sizeof *out);
    uint32_t n = carbon_coat_put(out, first, head, head_bytes);
    if (materials) n = carbon_coat_put(out, n, constants, sizeof constants);
    uint32_t moved = n - first;
    n = carbon_coat_put(out, n, t + first, (count - 1 - first) * sizeof *t);
    if (!materials) {
        *patched_count = carbon_coat_put(out, n, tail, sizeof tail);
        return out;
    }
    out[alpha + moved + 1] = (t[alpha+1] & 0x00ff0000u) | 0x80000009u;  /* same mask and saturate, into r9 */
    n = carbon_coat_put(out, n, tail, sizeof tail - 6 * sizeof *tail);
    *patched_count = carbon_coat_put(out, n, classes, sizeof classes);
    return out;
}

static uint32_t *carbon_coat_pixel(const uint32_t *t, uint32_t count, uint32_t *patched_count) {
    unsigned sm3 = (t[0] & 0xff00) >= 0x300, cube = 16;
    uint32_t first = 0, sample = 0, weigh = 0, weight_slot = 0, combine = 0, vinyl = 256;
    unsigned texel = 0, weight = 0, layer = 0;
    float gain = 0;
    for (uint32_t i = 1; i < count - 1;) {
        unsigned op = t[i] & 0xffff;
        uint32_t length = carbon_coat_length(t[i]);
        if (i + length >= count) return NULL;
        if (op != 0xfffe && !first) first = i;
        if (op == 31 && length == 2) {
            unsigned type = carbon_coat_type(t[i+2]);
            if (type == 10 && ((t[i+1] >> 27) & 15) == 3) cube = t[i+2] & 2047;
            if (sm3 && type == 1 && ((t[i+2] & 2047) == 0 || (t[i+1] & 0x000f001f) == 0x00070005)) return NULL;
            if (!sm3 && type == 3 && (t[i+2] & 2047) == 7) return NULL;
        } else if (op != 0xfffe && op != 81) {
            if (carbon_coat_type(t[i+1]) == 0 && (t[i+1] & 2047) >= 9) return NULL;
            if (carbon_coat_materials) { /* r7/r8 and c29/c30 must be free */
                if (carbon_coat_type(t[i+1]) == 0 && (t[i+1] & 2047) >= 7) return NULL;
                for (uint32_t k = 2; k <= length; ++k)
                    if (carbon_coat_type(t[i+k]) == 2 && (t[i+k] & 2047) >= 29) return NULL;
            }
            if (op == 66 && length == 3 && !(t[i] & 0x00ff0000u) && !sample && cube < 16 &&
                t[i+3] == (0xa0e40800u | cube) && carbon_coat_type(t[i+1]) == 0) {
                sample = i;
                texel = t[i+1] & 2047;
            } else if (op == 5 && length == 3 && sample && !weigh) {
                for (uint32_t k = 0; k < 2; ++k)
                    if (t[i+2+k] == (0x80e40000u | texel) && carbon_coat_plain(t[i+3-k], 1)) {
                        weigh = i;
                        weight_slot = i + 3 - k;
                        weight = t[weight_slot] & 2047;
                        layer = t[i+1] & 2047;
                    }
            } else if (op == 5 && length == 3 && weigh && !combine) {
                if ((t[i+1] & 0x00070000u) == 0x00070000u && carbon_coat_type(t[i+1]) == 0 &&
                    (t[i+2] == (0x80e40000u | layer) || t[i+3] == (0x80e40000u | layer)))
                    layer = t[i+1] & 2047;
            } else if (op == 4 && length == 4 && weigh && !combine && t[i+3] == (0x80e40000u | layer)) {
                combine = i;
                if (carbon_coat_type(t[i+2]) == 0) gain = 1;
            }
        }
        i += 1 + length;
    }
    if (!sample || !weigh || !combine) return NULL;
    for (uint32_t i = 1; i < count - 1; i += 1 + carbon_coat_length(t[i])) {
        unsigned op = t[i] & 0xffff;
        /* mad r, cvVinylScales.x, r, vWeight.w */
        if (op == 4 && vinyl == 256 && carbon_coat_type(t[i+2]) == 2 && !(t[i+2] & 0x0fff0000u) &&
            t[i+4] == (0x90ff0000u | weight))
            vinyl = t[i+2] & 2047;
        /* def of the literal the combine doubles with: 2 cancels to F with a half. */
        if (op == 81 && !gain && carbon_coat_type(t[combine+2]) == 2 &&
            (t[i+1] & 2047) == (t[combine+2] & 2047)) {
            float value;
            memcpy(&value, &t[i + 2 + ((t[combine+2] >> 16) & 3)], sizeof value);
            if (value == 2) gain = 0.5f;
        }
    }
    if (vinyl >= 31 || !gain) return NULL;
    const uint32_t K = 31, V = vinyl, Wt = 0x90e40000u | weight;
    const uint32_t F = sm3 ? 0x90000000u : 0xb0000007u; /* v0 (texcoord7) or t7 */
    uint32_t half;
    memcpy(&half, &gain, sizeof half);
    const uint32_t head[] = {
        0x05000051u, 0xa00f0000u | K, 0x00000000u, 0x3f800000u, half, 0x00000000u,
        0x0200001fu, sm3 ? 0x80070005u : 0x80000000u, sm3 ? 0x900f0000u : 0xb00f0007u,
    };
    const uint32_t before_sample[] = {
        0x03000002u, 0x8001000au, 0xa0000000u | V, 0xa0aa0000u | V,       /* add r10.x, vinyl.x, vinyl.z */
        0x04000058u, 0x8001000au, 0x8100000au, 0xa0550000u | K, 0xa0000000u | K, /* cmp r10.x, -r10.x, 1, 0 */
        0x03000008u, 0x8002000au, Wt, 0xa0550000u | K,                    /* dp3 r10.y, vWeight, 1 */
        0x04000058u, 0x8002000au, 0x8155000au, 0xa0000000u | K, 0xa0550000u | K, /* cmp r10.y, -r10.y, 0, 1 */
        0x03000005u, 0x8001000au, 0x8000000au, 0x8055000au,               /* mul r10.x, r10.x, r10.y: paint */
        0x03000005u, 0x8002000au, 0x8000000au, F | 0x00ff0000u,           /* mul r10.y, paint, F */
        0x03000002u, 0x8004000au, 0xa0550000u | K, 0x8155000au,           /* add r10.z, 1, -r10.y */
        0x03000005u, 0x8008000au, F | 0x00ff0000u, 0xa0aa0000u | K,       /* mul r10.w, F, gain */
        0x04000012u, 0x80070009u, 0x8000000au, 0x80ff000au, Wt,           /* lrp r9.xyz, paint, r10.w, vWeight */
        0x04000012u, 0x8007000bu, 0x8000000au, F | 0x00e40000u, t[sample+2], /* lrp r11.xyz, paint, vCoat, coord */
    };
    const uint32_t before_combine[] = {
        0x03000005u, 0x8007000bu, t[combine+4], 0x80aa000au,               /* mul r11.xyz, below, 1 - paint F */
    };
    /* Materials: the interpolant's w is F (paint), class weight + 2, or + 4 for clear glass. */
    const uint32_t Cc = 30, Dd = 29, Fw = F | 0x00ff0000u;
    const uint32_t constants[] = {
        0x05000051u, 0xa00f0000u | Cc, 0x3fc00000u, 0x40600000u, 0x40000000u, 0x3f0df3b6u, /* 1.5, 3.5, 2, .5545 */
        0x05000051u, 0xa00f0000u | Dd, 0x3f855555u, 0x3d23d70au, 0x00000000u, 0x00000000u, /* 1/.96, .04 */
    };
    const uint32_t classes[] = {
        CM_ADD, CM_D(10,1), CM_C(V,CM_X), CM_C(V,CM_Z),
        CM_CMP, CM_D(10,1), CM_R(10,CM_X) | CM_NEG, CM_C(K,CM_Y), CM_C(K,CM_X),
        CM_DP3, CM_D(10,2), Wt, CM_C(K,CM_Y),
        CM_CMP, CM_D(10,2), CM_R(10,CM_Y) | CM_NEG, CM_C(K,CM_X), CM_C(K,CM_Y), /* r10.y: retail weight > 0 */
        CM_MUL, CM_D(10,1), CM_R(10,CM_X), CM_R(10,CM_Y),                   /* r10.x: paint */
        CM_ADD, CM_D(10,4), Fw, CM_C(Cc,CM_X) | CM_NEG,
        CM_CMP, CM_D(10,4), CM_R(10,CM_Z), CM_C(K,CM_Y), CM_C(K,CM_X),      /* r10.z: class from the vertex program */
        CM_ADD, CM_D(10,8), Fw, CM_C(Cc,CM_Y) | CM_NEG,
        CM_CMP, CM_D(10,8), CM_R(10,CM_W), CM_C(K,CM_Y), CM_C(K,CM_X),      /* r10.w: clear glass */
        CM_ADD, CM_D(8,8), CM_R(10,CM_Z), CM_R(10,CM_W),
        CM_MAD, CM_D(8,8), CM_R(8,CM_W), CM_C(Cc,CM_Z) | CM_NEG, Fw,        /* r8.w: the weight itself */
        CM_CMP, CM_D(8,1), CM_C(V,CM_X) | CM_NEG, CM_C(K,CM_Y), CM_C(K,CM_X),
        CM_CMP, CM_D(8,2), CM_C(V,CM_Z) | CM_NEG, CM_C(K,CM_X), CM_C(K,CM_Y),
        CM_MUL, CM_D(8,1), CM_R(8,CM_X), CM_R(8,CM_Y),
        CM_MUL, CM_D(8,1), CM_R(8,CM_X), CM_R(10,CM_Y),                     /* r8.x: chrome paint */
        CM_ADD, CM_D(8,4), CM_R(8,CM_W), CM_C(Dd,CM_Y) | CM_NEG,
        CM_MUL, CM_D(8,4), CM_R(8,CM_Z), CM_C(Dd,CM_X),                     /* r8.z: (1 - N.V)^5 */
        CM_MIN, CM_D(7,7), Wt, CM_C(K,CM_Y),
        CM_MUL, CM_D(7,7), CM_R(7,CM_A), CM_C(Cc,CM_W),                     /* tint x .5545 */
        CM_LRP, CM_D(7,7), CM_R(8,CM_Z), CM_C(K,CM_Y), CM_R(7,CM_A),
        CM_LRP, CM_D(7,7), CM_R(8,CM_X), CM_R(7,CM_A), CM_R(8,CM_W),        /* r7: reflection weight */
        CM_ADD, CM_D(10,1), CM_R(10,CM_X), CM_R(10,CM_Z),
        CM_ADD, CM_D(10,1), CM_R(10,CM_X), CM_R(8,CM_X),
        CM_MIN, CM_D(10,1), CM_R(10,CM_X), CM_C(K,CM_Y),                    /* r10.x: any patched class */
        CM_MUL, CM_D(9,7), CM_R(7,CM_A), CM_C(K,CM_Z),
        CM_LRP, CM_D(9,7), CM_R(10,CM_X), CM_R(9,CM_A), Wt,                 /* r9: weight x gain, or retail */
        CM_LRP, CM_D(11,7), CM_R(10,CM_X), F | 0x00e40000u, t[sample+2],    /* r11: cube coordinate */
        CM_ADD, CM_D(7,7), CM_C(K,CM_Y), CM_R(7,CM_A) | CM_NEG,
        CM_ADD, CM_D(8,2), CM_C(K,CM_Y), CM_R(10,CM_W) | CM_NEG,
        CM_MUL, CM_D(7,7), CM_R(7,CM_A), CM_R(8,CM_Y),
        CM_LRP, CM_D(10,7), CM_R(10,CM_X), CM_R(7,CM_A), CM_C(K,CM_Y),      /* r10: layer below x (1 - weight); clear glass 0 */
    };
    const uint32_t combine_classes[] = { CM_MUL, CM_D(11,7), t[combine+4], CM_R(10,CM_A) };
    const unsigned materials = carbon_coat_materials;
    uint32_t *out = (uint32_t *)malloc(count * sizeof *out + sizeof head + sizeof constants + sizeof classes + sizeof before_combine);
    if (!out) return NULL;
    memcpy(out, t, first * sizeof *out);
    uint32_t n = carbon_coat_put(out, first, head, sizeof head);
    if (materials) n = carbon_coat_put(out, n, constants, sizeof constants);
    n = carbon_coat_put(out, n, t + first, (sample - first) * sizeof *t);
    n = materials ? carbon_coat_put(out, n, classes, sizeof classes)
                  : carbon_coat_put(out, n, before_sample, sizeof before_sample);
    uint32_t moved = n - sample;
    n = carbon_coat_put(out, n, t + sample, (combine - sample) * sizeof *t);
    out[sample + moved + 2] = 0x80e4000bu;
    out[weight_slot + moved] = 0x80e40009u;
    n = carbon_coat_put(out, n, materials ? combine_classes : before_combine, sizeof before_combine);
    moved = n - combine;
    n = carbon_coat_put(out, n, t + combine, (count - combine) * sizeof *t);
    out[combine + moved + 4] = 0x80e4000bu;
    *patched_count = n;
    return out;
}

/* Lamp energy for the car reflection capture (NFS_CARBON_REFLECT_HDR, on unless 0; needs the lacquer).
 * The two lamp sprite programs (particles flares and streak_flares: ps_2_0, blend SRCALPHA, ONE)
 * end in mov oC0, r0. Before it: m = min(max(r0.r, r0.g, r0.b) r0.a, 1), r0.rgb *= 1 / (1 - c30.x m),
 * the inverse of a display shoulder: the halo keeps its level, a lamp that reached white carries
 * 1 / (1 - c30.x) times white. c30.x is 0 on every target but a capture face (carbon_envcube.h sets
 * it per draw), where the factor is exactly 1. */
static uint32_t *carbon_coat_lamp(const uint32_t *t, uint32_t count, uint32_t *patched_count) {
    const char *value = getenv("NFS_CARBON_REFLECT_HDR");
    int on = !value || !strcmp(value, "1") || !strcmp(value, "ldr");
    if (!on || count < 6 || (t[0] & 0xffffff00u) != 0xffff0200u) return NULL;
    if (t[count-4] != 0x02000001u || t[count-3] != 0x800f0800u || t[count-2] != 0x80e40000u) return NULL;
    uint32_t first = 0;
    for (uint32_t i = 1; i < count - 1;) {
        unsigned op = t[i] & 0xffff;
        uint32_t length = carbon_coat_length(t[i]);
        if (i + length >= count) return NULL;
        if (op != 0xfffe && !first) first = i;
        if (op == 81 && (t[i+1] & 2047) >= 30) return NULL;              /* c30, c31 must be free */
        if (op != 0xfffe && op != 81 && op != 31)
            for (uint32_t k = 1; k <= length; ++k) {
                unsigned type = carbon_coat_type(t[i+k]), reg = t[i+k] & 2047;
                if ((type == 0 && reg >= 3) || (type == 2 && reg >= 30)) return NULL; /* and r3 */
            }
        i += 1 + length;
    }
    if (!first) return NULL;
    const uint32_t one[] = { 0x05000051u, 0xa00f001fu, 0x3f800000u, 0, 0, 0 };  /* def c31, 1, 0, 0, 0 */
    const uint32_t expand[] = {
        CM_MAX, CM_D(3,1), CM_R(0,CM_X), CM_R(0,CM_Y),
        CM_MAX, CM_D(3,1), CM_R(3,CM_X), CM_R(0,CM_Z),
        CM_MUL, CM_D(3,1), CM_R(3,CM_X), CM_R(0,CM_W),
        CM_MIN, CM_D(3,1), CM_R(3,CM_X), CM_C(31,CM_X),
        CM_MAD, CM_D(3,1), CM_R(3,CM_X), CM_C(30,CM_X) | CM_NEG, CM_C(31,CM_X),
        CM_RCP, CM_D(3,1), CM_R(3,CM_X),
        CM_MUL, CM_D(0,7), CM_R(0,CM_A), CM_R(3,CM_X),
    };
    uint32_t *out = (uint32_t *)malloc(count * sizeof *out + sizeof one + sizeof expand);
    if (!out) return NULL;
    memcpy(out, t, first * sizeof *out);
    uint32_t n = carbon_coat_put(out, first, one, sizeof one);
    n = carbon_coat_put(out, n, t + first, (count - 4 - first) * sizeof *t);
    n = carbon_coat_put(out, n, expand, sizeof expand);
    *patched_count = carbon_coat_put(out, n, t + count - 4, 4 * sizeof *t);
    return out;
}

static uint32_t *carbon_coat_variant(const uint32_t *tokens, uint32_t count, uint32_t *patched_count) {
    uint64_t key = 1469598103934665603ull;
    const unsigned char *bytes = (const unsigned char *)tokens;
    for (size_t k = 0; k < (size_t)count * 4; ++k)
        key = (key ^ bytes[k]) * 1099511628211ull;
    int vertex;
    unsigned record = 21; /* cvDiffuseMin */
    switch (key) {
        case 0x4c70062f23adfc25ull: record = 18; vertex = 1; break;
        case 0xb0fa697e82074657ull: case 0x5f097ccbab4310d2ull:
        case 0x02ad8c64c66fc529ull: case 0x32db3da103f82cacull: vertex = 1; break;
        case 0x3c185b9815aee740ull: case 0x63c39e750b34dff3ull: case 0xc35feb322f2add1cull:
        case 0x107be5ec81ba9635ull: case 0xeab92bd8c08134bcull: vertex = 0; break;
        case 0xb53b3a3b390249b4ull: case 0x89aa56e4826ec0d2ull:
            return carbon_coat_lamp(tokens, count, patched_count);
        default: return NULL;
    }
    if (count < 4 || tokens[count-1] != 0xffff || (tokens[0] >> 16) != (vertex ? 0xfffeu : 0xffffu)) return NULL;
    return vertex ? carbon_coat_vertex(tokens, count, patched_count, record)
                  : carbon_coat_pixel(tokens, count, patched_count);
}

uint32_t *carbon_coat_shader(const uint32_t *tokens, uint32_t count, uint32_t *patched_count) {
    const char *value = getenv("NFS_CARBON_COAT");
    int on = !(value && !strcmp(value, "0"));
    value = getenv("NFS_CARBON_MATERIALS");
    carbon_coat_materials = !(value && !strcmp(value, "0"));
    return on ? carbon_coat_variant(tokens, count, patched_count) : NULL;
}

/* Lookup identity includes only switches that change this program. Default
 * keys retain the shipped pipeline recipes. The tag belongs to lookup caches,
 * never to material variants or persisted shader recipes. */
static unsigned carbon_coat_family(uint64_t hash) {
    switch (hash) {
        case 0x4c70062f23adfc25ull: case 0xb0fa697e82074657ull: case 0x5f097ccbab4310d2ull:
        case 0x02ad8c64c66fc529ull: case 0x32db3da103f82cacull:
        case 0x3c185b9815aee740ull: case 0x63c39e750b34dff3ull: case 0xc35feb322f2add1cull:
        case 0x107be5ec81ba9635ull: case 0xeab92bd8c08134bcull: return 1;
        case 0xb53b3a3b390249b4ull: case 0x89aa56e4826ec0d2ull: return 2;
        default: return 0;
    }
}
uint32_t carbon_coat_cache_variant(uint64_t hash, uint32_t variant) {
    unsigned family=carbon_coat_family(hash), state;
    if (!family) return variant;
    const char *coat=getenv("NFS_CARBON_COAT");
    int on=!(coat && !strcmp(coat,"0"));
    if (family==1) {
        const char *materials=getenv("NFS_CARBON_MATERIALS");
        state=on ? 1u+2u*!(materials && !strcmp(materials,"0")) : 0u;
        if (state==3) return variant;
    } else {
        const char *hdr=getenv("NFS_CARBON_REFLECT_HDR");
        state=on && (!hdr || !strcmp(hdr,"1") || !strcmp(hdr,"ldr"));
        if (state==1) return variant;
    }
    return variant | ((state+1u)<<24);
}

/* A recipe stores the default shader identity. Remember its untagged input so
 * prewarm can resolve the current state's immutable function and pipeline key.
 * Records are made only on compilation misses, never on the draw cache hits. */
#include <pthread.h>
typedef struct { uint64_t key, base, hash; uint32_t variant; } CarbonCoatRecipe;
static CarbonCoatRecipe *carbon_coat_recipes;
static size_t carbon_coat_recipe_count;
static pthread_mutex_t carbon_coat_recipe_mutex=PTHREAD_MUTEX_INITIALIZER;
static uint64_t carbon_coat_variant_key(uint64_t base, uint32_t variant) {
    if (variant) {
        const unsigned char *bytes=(const unsigned char *)&variant;
        for (unsigned i=0;i<4;++i) base=(base^bytes[i])*1099511628211ull;
    }
    return base;
}
void carbon_coat_record_key(uint64_t base, uint64_t hash, uint32_t variant) {
    if (!carbon_coat_family(hash)) return;
    uint64_t key=carbon_coat_variant_key(base,variant);
    pthread_mutex_lock(&carbon_coat_recipe_mutex);
    for (size_t i=0;i<carbon_coat_recipe_count;++i) if (carbon_coat_recipes[i].key==key) {
        pthread_mutex_unlock(&carbon_coat_recipe_mutex); return;
    }
    CarbonCoatRecipe *records=(CarbonCoatRecipe *)realloc(carbon_coat_recipes,(carbon_coat_recipe_count+1)*sizeof *records);
    if (records) {
        carbon_coat_recipes=records;
        records[carbon_coat_recipe_count++]=(CarbonCoatRecipe){key,base,hash,variant};
    }
    pthread_mutex_unlock(&carbon_coat_recipe_mutex);
}
uint64_t carbon_coat_recipe_key(uint64_t key) {
    pthread_mutex_lock(&carbon_coat_recipe_mutex);
    for (size_t i=0;i<carbon_coat_recipe_count;++i) if (carbon_coat_recipes[i].key==key) {
        CarbonCoatRecipe r=carbon_coat_recipes[i];
        key=carbon_coat_variant_key(r.base,carbon_coat_cache_variant(r.hash,r.variant));
        break;
    }
    pthread_mutex_unlock(&carbon_coat_recipe_mutex);
    return key;
}
