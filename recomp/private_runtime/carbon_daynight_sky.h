/* Exact dome pixel program; native cloud density and fog coordinate survive. */
float carbon_daynight_night(void) {
    if (!carbon_dn_on() || M32(0x00A99BBCu) != 6 ||
        !carbon_dn_clock.ready || !carbon_dn_clock.blended) return 1;
    return carbon_dn_clock.sample.night;
}

static void carbon_dn_sky_compiled(const uint32_t *tokens, uint32_t count) {
    if (!diag_on || count != 441 || tokens[0] != 0xffff0300u) return;
    static uint64_t keys[16];
    static unsigned used;
    uint64_t key = carbon_dn_shader_key(tokens,count);
    for (unsigned k=0;k<used;++k) if (keys[k] == key) return;
    if (used < 16) keys[used++] = key;
    diag_event("carbon_daynight: sky_program key=%016llx flow=%u",
        (unsigned long long)key,M32(0x00A99BBCu));
}

/* c14 = sky.rgb/night, c15 = haze.rgb/1, c16 = fog.rgb/1/7000.
 * c17/c18 = source Rayleigh/Mie terms with extinction, c17.w enables them;
 * c19 = normalized local light. The source noon atmosphere is isotropic.
 * The pinned program uses c0..13 and r0..3. At its end r2.z still holds
 * the faded s0 alpha density, v2.z the dome height, v3.x the clear fraction.
 * Preserve its RGB write (including precision) in r11 and its alpha in oC0.
 * The native program samples s0 at v1*2.77 with a 2D scroll; the source dome
 * maps its cloud picture once over v (top 0, horizon 1), so the source branch
 * re-samples at unscaled v1 with the source's u-only scroll (r2.x keeps the
 * native distance fade). The same dome at night runs the native path, so
 * the native sample (instruction at token 349) is switched in place by c17.w,
 * which the constants set for this dome at any hour; native domes keep the
 * original mad. */
static uint32_t *carbon_dn_sky_variant(const uint32_t *tokens, uint32_t count,
                                      uint32_t *patched_count) {
    if (count != 441 || tokens[0] != 0xffff0300u ||
        carbon_dn_shader_key(tokens,count) != 0xb03ae6d5fda81119ull) return NULL;
    uint32_t *out = (uint32_t *)malloc((count+120)*sizeof *out);
    if (!out) return NULL;
    memcpy(out,tokens,(count-1)*sizeof *out);
    out[434] = (tokens[434] & 0x0fff0000u) | 0x8000000bu;
    const uint32_t cloud_uv[] = {
        0x02010029u, 0xa0ff0011u, 0xa1ff0011u, /* if_gt c17.w,-c17.w */
        0x03000002u, 0x80010000u, 0x80000000u, 0x90000001u, /* add r0.x,r0.x,v1.x: u-only scroll */
        0x02000001u, 0x80020000u, 0x90550001u, /* mov r0.y,v1.y: the source dome's unscaled v */
        0x0000002au, /* else */
        0x04000004u, 0x80030000u, 0x90e40001u, 0xa0ff0005u, 0x80e40000u, /* mad r0.xy,v1,c5.w,r0: native 2.77x */
        0x0000002bu /* endif */
    };
    const unsigned cloud_at = 349, cloud_old = 5, cloud_new = sizeof cloud_uv/sizeof *cloud_uv;
    memmove(out+cloud_at+cloud_new,out+cloud_at+cloud_old,(count-1-cloud_at-cloud_old)*sizeof *out);
    memcpy(out+cloud_at,cloud_uv,sizeof cloud_uv);
    const uint32_t tail[] = {
        0x03000005u, 0x8011000au, 0x90aa0002u, 0xa0ff0010u, /* mul_sat r10.x,v2.z,c16.w */
        0x04000012u, 0x8007000au, 0x8000000au, 0xa0e4000eu, 0xa0e4000fu, /* lrp day,height,sky,haze */
        0x04000012u, 0x8007000au, 0x80aa0002u, 0xa0ff000du, 0x80e4000au, /* lrp day,density,cloud light (0.5),day */
        0x04000012u, 0x8007000au, 0x90000003u, 0x80e4000au, 0xa0e40010u, /* lrp day,clear,day,fog */
        0x02010029u, 0xa0ff0011u, 0xa1ff0011u, /* if_gt c17.w,-c17.w */
        0x03000002u, 0x8007000cu, 0xa0e40002u, 0x91e40002u, /* add r12.xyz,c2,-v2 */
        0x03000008u, 0x8008000cu, 0x80e4000cu, 0x80e4000cu, /* dp3 r12.w,r12,r12 */
        0x02000007u, 0x8008000cu, 0x80ff000cu, /* rsq r12.w,r12.w */
        0x03000005u, 0x8007000cu, 0x80e4000cu, 0x80ff000cu, /* mul r12.xyz,r12,r12.w */
        0x03000008u, 0x8008000cu, 0x80e4000cu, 0xa0e40013u, /* dp3 r12.w,r12,c19 */
        0x04000004u, 0x8008000cu, 0x80ff000cu, 0x80ff000cu, 0xa0ff0013u, /* mad r12.w,mu,mu,1 */
        0x04000004u, 0x8017000au, 0x80ff000cu, 0xa0e40011u, 0xa0e40012u, /* mad_sat day,1+mu^2,Rayleigh,Mie */
        0x04000004u, 0x8001000cu, 0xa0000003u, 0xa0000009u, 0x90000001u, /* mad r12.x,c3.x,c9.x,v1.x: u-only scroll */
        0x02000001u, 0x8002000cu, 0x90550001u, /* mov r12.y,v1.y: the source dome's unscaled v */
        0x03000042u, 0x800f000cu, 0x80e4000cu, 0xa0e40800u, /* texld r12,r12,s0 */
        0x03000005u, 0x8008000cu, 0x80000002u, 0x80ff000cu, /* mul r12.w,fade,alpha */
        0x04000012u, 0x8007000au, 0x80ff000cu, 0xa0ff000du, 0x80e4000au, /* lrp day,source density,cloud light (0.5),day */
        0x0000002bu, /* endif: native city and night execute the original path */
        0x04000012u, 0x80070800u, 0xa0ff000eu, 0x80e4000bu, 0x80e4000au, /* lrp oC0.rgb,n,native,day */
        0x0000ffffu
    };
    memcpy(out+count-1+cloud_new-cloud_old,tail,sizeof tail);
    *patched_count = count-1+cloud_new-cloud_old+sizeof tail/sizeof *tail;
    return out;
}

static void carbon_dn_sky_constants(Cpu *c) {
    if (!carbon_dn_on()) return;
    float constants[6][4] = {{0,0,0,carbon_daynight_night()}, {0,0,0,1}, {0,0,0,1.0f/7000}};
    uint32_t tod = M32(0x00B77F34u);
    const char *overlay = getenv("NFS_CARBON_TRACK_OVERLAY");
    int imported = overlay && *overlay && M32(0x00A99BBCu) == 6 && M32(0x00A73358u) &&
                   M32(0x00B77918u) == 0x1F389568u;
    if (tod && constants[0][3] < 1) {
        memcpy(constants[0],gptr(tod+0x70),3*sizeof(float));
        memcpy(constants[1],gptr(tod+0x80),3*sizeof(float));
        memcpy(constants[2],constants[1],3*sizeof(float));
        if (imported) {
            /* Source noon provider: sky/haze scales 1/.1 on [.0001,.01],
             * isotropic phase, scatter 10 and 15000-m sky extinction.
             * Fold only direction-independent terms into the constants. */
            for (unsigned k=0;k<3;++k) {
                float br = constants[0][k]*(.0001f+.0099f*.01f);
                float bm = constants[1][k]*(.0001f+.0099f*.001f);
                float total = br+bm;
                float gain = total > 0 ? 10*(-expm1f(-15000*total))/total : 0;
                constants[3][k] = br*.059683103f*gain;
                constants[4][k] = bm*.07957747f*gain;
            }
            memcpy(constants[5],G+tod+0x160,3*sizeof(float));
            float length = sqrtf(constants[5][0]*constants[5][0]+
                                 constants[5][1]*constants[5][1]+
                                 constants[5][2]*constants[5][2]);
            if (length > 0) for (unsigned k=0;k<3;++k) constants[5][k] /= length;
            constants[5][3] = 1;
        }
    }
    /* c17.w also marks the dome for the cloud coordinate at night (n = 1). */
    if (imported) constants[3][3] = 1;
    uint32_t device = M32(0x00AB0ABCu), vt = device ? M32(device) : 0;
    if (!vt) return;
    Cpu upload = *c;
    upload.esp -= sizeof constants;
    memcpy(G+upload.esp,constants,sizeof constants);
    uint32_t args[] = {device,14,upload.esp,6};
    call_guest(&upload,M32(vt+109*4),4,args);
}

void carbon_daynight_fog(Cpu *c, void (*original)(Cpu *)) {
    uint32_t fog = M32(c->esp+8);
    original(c);
    float n = carbon_daynight_night();
    uint32_t tod = M32(0x00B77F34u);
    if (fog && tod && n < 1) {
        for (unsigned k=0;k<3;++k) {
            float haze = carbon_dn_float(tod+0x80+4*k);
            float native = carbon_dn_float(fog+4*k);
            carbon_dn_write(fog+4*k,haze+n*(native-haze));
        }
    }
    if (diag_on && fog && tod && M32(0x00A99BBCu) == 6) {
        static int recorded;
        if (!recorded && (!carbon_dn_on() || carbon_dn_clock.blended)) {
            recorded = 1;
            diag_event("carbon_daynight: sky_fog night=%.9g colour=%.9g,%.9g,%.9g haze=%.9g,%.9g,%.9g sky=%.9g,%.9g,%.9g distances=%.9g,%.9g,%.9g,%.9g,%.9g,%.9g",
                n,carbon_dn_float(fog),carbon_dn_float(fog+4),carbon_dn_float(fog+8),
                carbon_dn_float(tod+0x80),carbon_dn_float(tod+0x84),carbon_dn_float(tod+0x88),
                carbon_dn_float(tod+0x70),carbon_dn_float(tod+0x74),carbon_dn_float(tod+0x78),
                carbon_dn_float(fog+0x10),carbon_dn_float(fog+0x14),carbon_dn_float(fog+0x18),
                carbon_dn_float(fog+0x1c),carbon_dn_float(fog+0x20),carbon_dn_float(fog+0x24));
        }
    }
}
