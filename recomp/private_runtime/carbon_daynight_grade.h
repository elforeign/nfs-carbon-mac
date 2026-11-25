/* NFS_DAYNIGHT_GRADE (On unless 0/off): by day
 * inside converted Rockport, the visual treatment's 3D colour grade is blended
 * toward identity by the day weight, so Carbon's retail grade (a blue cast made
 * for Palmont) no longer tints Rockport's daylight. Before the grade the road
 * already has Most Wanted's balance. Bloom, vignette, desaturation and fades
 * stay native. Neutral D65 opens the bypass in every treatment view and hour.
 * This is a code-value LUT bypass, separate from the presenter sRGB decode;
 * it does not establish a float scene composition contract.
 * Weight 0 keeps the grade exactly. */
static float carbon_compat_day(void);

static int carbon_dn_grade_on(void) {
    static int configured, enabled;
    if (configured) return enabled;
    configured = 1;
    const char *setting = getenv("NFS_DAYNIGHT_GRADE");
    enabled = (lighting_mode_d65() || carbon_dn_on()) &&
        !(setting && (!strcmp(setting,"0") || !strcasecmp(setting,"off")));
    return enabled;
}

#include "carbon_mw_grade.h"

/* The ordinary visual treatment samples its colour LUT after bloom, then applies vignette and exposure.
 * The enhanced visual treatment blends its two colour LUTs, then applies
 * desaturation, fade and exposure. After the grade, insert
 *   mov_sat rT.rgb, r0 ; lrp grade.rgb, c31.z, rT, grade
 * Neutral D65 omits SAT so the same bypass carries float highlights to EDR.
 * rT is unused by the program. PS c31.z is the bypass weight (c31.x/.y
 * belong to the world draws, which run earlier and reset c31 per draw). */
static uint32_t *carbon_dn_grade_variant(const uint32_t *tokens, uint32_t count,
                                        uint32_t *patched_count) {
    static const uint32_t plain[] = {0x03000042u,0x802f0001u,0x80e40000u,0xa0e40803u}; /* texld_pp r1,r0,s3 */
    static const uint32_t blend[] = {0x04000012u,0x80270005u,0xa0aa0001u,0x80e40003u,0x80e40004u}; /* lrp_pp r5.rgb,c1.z,r3,r4 */
    const uint32_t *pattern;
    uint32_t length, grade, temp;
    switch (carbon_dn_shader_key(tokens,count)) {
        case 0x3879b8c8d72df0cbull: pattern = plain; length = 4; grade = 1; temp = 3; break;
        case 0x5ad9ea49cac6d49bull: pattern = blend; length = 5; grade = 5; temp = 6; break;
        default: return NULL;
    }
    if (carbon_mw_grade_on()) return carbon_mw_grade_variant(tokens,count,patched_count,grade==5);
    if (count < 2 || tokens[0] != 0xffff0200u || tokens[count-1] != 0xffffu) return NULL;
    uint32_t insert = 0, matches = 0;
    for (uint32_t i = 1; i + length < count; ++i)
        if (!memcmp(tokens+i,pattern,length*4)) { insert = i+length; ++matches; }
    if (matches != 1) return NULL;
    const uint32_t extra[] = {
        0x02000001u, (lighting_mode_d65() ? 0x80070000u : 0x80170000u) | temp, 0x80e40000u, /* mov[_sat] rT.rgb, r0 */
        0x04000012u, 0x80070000u | grade, 0xa0aa001fu, 0x80e40000u | temp, 0x80e40000u | grade, /* lrp */
    };
    uint32_t n = sizeof extra / 4;
    uint32_t *out = (uint32_t *)malloc((size_t)(count+n)*4);
    if (!out) return NULL;
    memcpy(out,tokens,(size_t)insert*4);
    memcpy(out+insert,extra,sizeof extra);
    memcpy(out+insert+n,tokens+insert,(size_t)(count-insert)*4);
    *patched_count = count+n;
    return out;
}

/* Neutral covers both cities at every hour, independent of overlay/sky.
 * The legacy daylight bypass still requires the native dome and camera row
 * section 2100; the row identifies converted scenery without rebinding sky. */
static float carbon_dn_grade_weight(void) {
    if (lighting_mode_d65()) return 1;
    const char *overlay = getenv("NFS_CARBON_TRACK_OVERLAY");
    if (!overlay || !*overlay || !M32(0x00A73358u) || M32(0x00B77918u) != 0xED85BA82u || !carbon_dn_imported_view) return 0;
    return carbon_compat_day();
}

/* 0071D4E0(this, technique, effect) sets the final treatment's parameters; its
 * only caller, 00726AF0, then draws the full-screen pass with that effect
 * (B42FE8, the visual treatment) and no other draw in between. The program
 * declares only c0/c1, so PS c31 = (0, 0, weight, 0) set here reaches it. */
void carbon_daynight_grade_draw(Cpu *c, void (*original)(Cpu *)) {
    uint32_t effect = M32(c->esp+8);
    original(c);
    if (!carbon_dn_grade_on() || !effect || effect != M32(0x00B42FE8u)) return;
    uint32_t device = M32(0x00AB0ABCu), vt = device ? M32(device) : 0;
    if (!vt) return;
    float weight[4] = {0,0,carbon_dn_grade_weight(),0};
    if (carbon_mw_grade_on() && !carbon_mw_grade_bind(c,device,vt)) weight[2]=0;
    if (diag_on) {
        static unsigned long long day, zero;
        static uint64_t last;
        if (weight[2] > 0) ++day; else ++zero;
        uint64_t now = host_ticks();
        if (!last || now-last >= 2000000000ull) {
            last = now;
            diag_event("carbon_daynight_grade: weight=%.6g draws day=%llu zero=%llu",weight[2],day,zero);
        }
    }
    Cpu upload = *c;
    upload.esp -= 32;
    memcpy(G+upload.esp,weight,16);
    uint32_t args[] = {device,31,upload.esp,1};
    call_guest(&upload,M32(vt+109*4),4,args);
}
