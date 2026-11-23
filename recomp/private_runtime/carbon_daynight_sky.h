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

#if __has_include("carbon_c3fog.h")
static int carbon_c3fog_neutral_horizon(Cpu *c, float rgb[3]);
#endif

/* Native dome gradient, cloud scroll and moon sampling. */
static uint32_t *carbon_dn_sky_variant(const uint32_t *tokens, uint32_t count,
                                      uint32_t *patched_count) {
    if (count != 441 || tokens[0] != 0xffff0300u ||
        carbon_dn_shader_key(tokens,count) != 0xb03ae6d5fda81119ull) return NULL;
    int neutral = lighting_mode_d65();
    const uint32_t horizon[] = {
        0x03000005u, 0x8007000bu, 0x80e40001u, 0x80ff0000u, /* mul night,r1,r0.w */
        0x04000012u, 0x8007000bu, 0x90000003u, 0x80e4000bu, 0xa0e40010u, /* lrp night,clear,night,fog */
    };
    unsigned extra = neutral ? sizeof horizon / sizeof *horizon : 0;
    uint32_t *out = (uint32_t *)malloc((count+24+extra)*sizeof *out);
    if (!out) return NULL;
    memcpy(out,tokens,(count-1)*sizeof *out);
    out[434] = (tokens[434] & 0x0fff0000u) | 0x8000000bu;
    const uint32_t tail[] = {
        0x03000005u, 0x8011000au, 0x90aa0002u, 0xa0ff0010u, /* mul_sat r10.x,v2.z,c16.w */
        0x04000012u, 0x8007000au, 0x8000000au, 0xa0e4000eu, 0xa0e4000fu, /* lrp day,height,sky,haze */
        0x04000012u, 0x8007000au, 0x80aa0002u, 0xa0ff000du, 0x80e4000au, /* lrp day,density,cloud light (0.5),day */
        0x04000012u, 0x8007000au, 0x90000003u, 0x80e4000au, 0xa0e40010u, /* lrp day,clear,day,fog */
        0x04000012u, 0x80070800u, 0xa0ff000eu, 0x80e4000bu, 0x80e4000au, /* lrp oC0.rgb,n,native,day */
        0x0000ffffu
    };
    if (neutral) memcpy(out+count-1,horizon,sizeof horizon);
    memcpy(out+count-1+extra,tail,sizeof tail);
    *patched_count = count+24+extra;
    return out;
}

static void carbon_dn_sky_constants(Cpu *c) {
    if (!carbon_dn_on()) return;
    float constants[3][4] = {{0,0,0,carbon_daynight_night()}, {0,0,0,1}, {0,0,0,1.0f/7000}};
    uint32_t tod = M32(0x00B77F34u);
    if (tod && constants[0][3] < 1) {
        memcpy(constants[0],gptr(tod+0x70),3*sizeof(float));
        memcpy(constants[1],gptr(tod+0x80),3*sizeof(float));
        memcpy(constants[2],constants[1],3*sizeof(float));
    }
    if (lighting_mode_d65()) {
        uint32_t fog = M32(0x00B4295Cu);
        if (fog) memcpy(constants[2],gptr(fog),3*sizeof(float));
        lighting_colour_d65(constants[2]);
#if __has_include("carbon_c3fog.h")
        carbon_c3fog_neutral_horizon(c,constants[2]);
#endif
        memcpy(constants[1],constants[2],3*sizeof(float));
    }
    uint32_t device = M32(0x00AB0ABCu), vt = device ? M32(device) : 0;
    if (!vt) return;
    Cpu upload = *c;
    upload.esp -= sizeof constants;
    memcpy(G+upload.esp,constants,sizeof constants);
    uint32_t args[] = {device,14,upload.esp,3};
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
    if (fog && lighting_mode_d65()) {
        float rgb[3];
        memcpy(rgb,gptr(fog),sizeof rgb);
        lighting_colour_d65(rgb);
        memcpy(gptr(fog),rgb,sizeof rgb);
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

static int carbon_dn_imported_view;

void carbon_daynight_view(Cpu *c, void (*original)(Cpu *)) {
    carbon_dn_imported_view = 0;
    const char *overlay = getenv("NFS_CARBON_TRACK_OVERLAY");
    uint32_t view = M32(c->esp + 4), mode = M32(c->esp + 8);
    if (carbon_dn_on() && overlay && *overlay && M32(0x00A99BBCu) == 6 &&
        M32(0x00A73358u) && view && mode && mode < 5) {
        uint32_t camera = M32(view + 0x40);
        if (camera) {
            Cpu work = *c;
            work.esp -= 512;
            work.ecx = 0x00B69CD0u;
            uint32_t position = camera + 0x40;
            uint32_t row = call_guest(&work, 0x007A3290u, 1, &position);
            unsigned count = row ? M16(row + 0x10) : 0;
            for (unsigned i = 0; i < count && i < 384; ++i)
                carbon_dn_imported_view |= M16(row + 0x12 + 2*i) == 2100;
        }
    }
    original(c);
}
