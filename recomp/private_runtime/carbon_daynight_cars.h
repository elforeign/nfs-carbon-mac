/* In-game cars by day: Most Wanted's sun-relative rig through Carbon's own light builder. */
#include "host.h"
#include "lighting_colour.h"
#include <math.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>

extern float carbon_daynight_night(void);
extern int carbon_daynight_d65_rig(float *sun, float *ambient);
extern int diag_on;
extern void diag_event(const char *, ...);

/* Most Wanted rig 008F2E70 slots 1-3, all kind 2 (sun-relative): azimuth and
 * elevation offsets, RGB, intensity. Key = sun raised 10 degrees; the fills
 * light from the far side, below the horizon. */
static const float carbon_dn_cars_mw[3][6] = {
    {0,350,.85f,.90f,1,.83f}, {50,220,.55f,.60f,1,.40f}, {310,220,.65f,.70f,1,.45f}};

/* NFS_DAYNIGHT_CARS: On unless 0/off. */
static int carbon_dn_cars_on(void) {
    static int configured, enabled;
    if (!configured) {
        configured = 1;
        const char *setting = getenv("NFS_DAYNIGHT_CARS");
        enabled = !(setting && (!strcmp(setting,"0") || !strcasecmp(setting,"off")));
    }
    return enabled;
}

static float carbon_dn_cars_wrap(float degrees) {
    degrees = fmodf(degrees,360);
    return degrees < 0 ? degrees+360 : degrees;
}

/* Rig slot k at +4+1C*k: kind, azimuth, elevation, RGB, intensity. Carbon
 * zeroes kinds 2/3; its kind 0 is SphericalToCartesian(azimuth+180, 90-elevation),
 * the tail Most Wanted's kind 2 uses after azimuth = atan2(y,x) + offset and
 * elevation = polar + 90 + offset of the sun vector. So the rig is kind 0. */
static int carbon_dn_cars_rig(uint8_t *rig, const uint8_t *native, const float sun[3]) {
    float length = sqrtf(sun[0]*sun[0]+sun[1]*sun[1]+sun[2]*sun[2]);
    if (!(length > 0)) return 0;
    float azimuth = atan2f(sun[1],sun[0])*57.2957795f;
    float polar = acosf(fmaxf(-1,fminf(1,sun[2]/length)))*57.2957795f;
    memcpy(rig,native,0xA0);
    for (unsigned k=0;k<3;++k) {
        uint8_t *slot = rig+4+0x1c*k;
        const float *mw = carbon_dn_cars_mw[k];
        float values[6] = {carbon_dn_cars_wrap(azimuth+mw[0]),
            carbon_dn_cars_wrap(polar+90+mw[1]),mw[2],mw[3],mw[4],mw[5]};
        uint32_t kind = 0;
        memcpy(slot,&kind,4);
        memcpy(slot+4,values,sizeof values);
    }
    memset(rig+4+0x1c*3+0x18,0,4);
    return 1;
}

/* Carbon's car pixel shader reads the light colours (+10..3B, one RGB row per
 * light 0-2) only for its specular lobes, pow(R.L,40) x cvSpecularRange (8 on
 * paint) x colour, one per light; diffuse comes from the harmonics. Its in-game
 * rigs keep each light at .05-.20. Most Wanted's car shader never reads its rig
 * colours for specular: one highlight from the key light, scaled by the
 * material. Fed raw, its fills (.22-.45, below the horizon) put x8 white lobes
 * on down-facing panels. So the specular matrix gets Carbon's own key colour
 * (native slot 0) on the sun-relative key and none on the fills; the
 * harmonics keep Most Wanted's rig. */
static void carbon_dn_cars_specular(uint8_t *out, const uint8_t *native) {
    float intensity, rgb[3];
    memcpy(&intensity,native+4+0x18,4);
    memcpy(rgb,native+4+0x0c,sizeof rgb);
    for (unsigned i=0;i<3;++i) rgb[i] *= intensity;
    memcpy(out+0x10,rgb,sizeof rgb);
    memset(out+0x20,0,12);
    memset(out+0x30,0,12);
}

static float carbon_dn_cars_get(const uint8_t *at) {
    float value;
    memcpy(&value,at,sizeof value);
    return value;
}

static float carbon_dn_cars_luma(const uint8_t *row) {
    return .299f*carbon_dn_cars_get(row)+.587f*carbon_dn_cars_get(row+4)+.114f*carbon_dn_cars_get(row+8);
}

/* 00746A00(context, rig, position, local, view matrix, view), cdecl, returns 1.
 * Writes light colours +10..3B, directions +50/+60/+70 (x/y/z per light) and
 * harmonics +130..1CF. Day weight d = 1 - night: 1 builds from the private rig
 * only; between, a private build into a scratch context first (the native call
 * last leaves the builder's globals as native), then colours and harmonics mix
 * linearly and directions by luminance. d = 0 (night, clock absent, other
 * rigs) is the native call alone. */
void carbon_daynight_cars(Cpu *c, void (*original)(Cpu *)) {
    uint32_t context = M32(c->esp+4), rig = M32(c->esp+8), tod = M32(0x00B77F34u);
    float d = carbon_dn_cars_on() && tod && context ? 1-carbon_daynight_night() : 0;
    float sun_ratio, ambient_ratio;
    int d65 = lighting_mode_d65() && carbon_dn_cars_on() &&
        carbon_daynight_d65_rig(&sun_ratio,&ambient_ratio);
    if (d65 && tod && context) d = 1;
    if (!(d > 0) || (rig != 0x00A6CC20u && rig != 0x00A6CCC0u && rig != 0x00A6CD60u)) {
        original(c);
        return;
    }
    if (d > 1) d = 1;
    uint32_t base = (c->esp-0x300) & ~15u, own = base+0x20, scratch = base+0x100;
    float sun[3];
    memcpy(sun,G+tod+0x160,sizeof sun);
    if (!carbon_dn_cars_rig(G+own,G+rig,sun)) { original(c); return; }
    if (d65) {
        for (unsigned k=0; k<3; ++k) {
            uint8_t *slot = G+own+4+0x1c*k;
            float values[4];
            memcpy(values,slot+0x0c,sizeof values);
            lighting_colour_d65(values);
            values[3] *= k ? ambient_ratio : sun_ratio;
            memcpy(slot+0x0c,values,sizeof values);
        }
    }
    Cpu call = *c;
    call.esp = base;
    M32(base) = M32(c->esp);
    for (unsigned k=1;k<=6;++k) M32(base+4*k) = M32(c->esp+4*k);
    M32(base+8) = own;
    if (d < 1) {
        memcpy(G+scratch,G+context,0x1d0);
        M32(base+4) = scratch;
    }
    original(&call);
    carbon_dn_cars_specular(G+(d < 1 ? scratch : context),G+rig);
    if (d65) {
        float rgb[3];
        memcpy(rgb,G+context+0x10,sizeof rgb);
        lighting_colour_d65(rgb);
        for (unsigned k=0; k<3; ++k) rgb[k] *= sun_ratio;
        memcpy(G+context+0x10,rgb,sizeof rgb);
    }
    if (diag_on) {
        static int recorded;
        if (!recorded) {
            recorded = 1;
            uint32_t out = d < 1 ? scratch : context;
            diag_event("carbon_daynight: cars day=%.6f rig=%08x sun=%.6f,%.6f,%.6f key=%.6f,%.6f,%.6f colour=%.6f,%.6f,%.6f",
                d,rig,sun[0],sun[1],sun[2],MF32(out+0x50),MF32(out+0x60),MF32(out+0x70),
                MF32(out+0x10),MF32(out+0x14),MF32(out+0x18));
            if (d65) {
                float slots[3][3];
                for (unsigned k=0; k<3; ++k) {
                    float gain;
                    memcpy(slots[k],G+own+0x10+0x1c*k,sizeof slots[k]);
                    memcpy(&gain,G+own+0x1c+0x1c*k,sizeof gain);
                    for (unsigned j=0; j<3; ++j) slots[k][j] *= gain;
                }
                diag_event("carbon_daynight: d65 rig key=%.9g,%.9g,%.9g fill1=%.9g,%.9g,%.9g fill2=%.9g,%.9g,%.9g",
                    slots[0][0],slots[0][1],slots[0][2], slots[1][0],slots[1][1],slots[1][2],
                    slots[2][0],slots[2][1],slots[2][2]);
            }
        }
    }
    if (d >= 1) {
        uint32_t esp = c->esp;
        *c = call;
        c->esp = esp+4;
        return;
    }
    /* The native call's frame reuses the scratch stack: keep a host copy. */
    uint8_t day[0x1d0];
    memcpy(day,G+scratch,sizeof day);
    original(c);
    for (unsigned k=0;k<3;++k) {
        float wn = (1-d)*carbon_dn_cars_luma(G+context+0x10+0x10*k);
        float wp = d*carbon_dn_cars_luma(day+0x10+0x10*k);
        float v[3], length = 0;
        for (unsigned i=0;i<3;++i) {
            uint32_t at = 0x50+0x10*i+4*k;
            v[i] = wn*MF32(context+at)+wp*carbon_dn_cars_get(day+at);
            length += v[i]*v[i];
        }
        if (length > 0) {
            length = 1/sqrtf(length);
            for (unsigned i=0;i<3;++i) MF32(context+0x50+0x10*i+4*k) = v[i]*length;
        }
    }
    for (uint32_t at=0x10;at<0x3c;at+=4)
        MF32(context+at) = (1-d)*MF32(context+at)+d*carbon_dn_cars_get(day+at);
    for (uint32_t at=0x130;at<0x1d0;at+=4)
        MF32(context+at) = (1-d)*MF32(context+at)+d*carbon_dn_cars_get(day+at);
}
