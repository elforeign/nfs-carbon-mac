/* Optional source treatment arithmetic. The surrounding pass retains its own
 * bloom, vignette, exposure and fades. s7 is the point/clamp curve texture;
 * c26..28 carry luminance, desaturation/black terms and tint/colour intensity.
 * The filtered input is adapted from the native bloom RGB, not its alpha
 * (which is not the source treatment's filtered-luminance contract). */
/* The table comes from Most Wanted's attributes.bin: a Carbon-only build has none, so the grade stays off. */
#if __has_include("gen/look_pc.inc")
#include "gen/look_pc.inc"
#else
static const float LOOK_PC[5][14];
#define CARBON_MW_GRADE_NO_TABLE 1
#endif

static int carbon_dn_retail_mw(void);
static int carbon_mw_grade_on(void) {
#ifdef CARBON_MW_GRADE_NO_TABLE
    return 0;
#endif
    const char *setting = getenv("NFS_DAYNIGHT_MW_GRADE");
    if (!setting || (strcmp(setting,"1") && strcasecmp(setting,"on"))) return 0;
    return carbon_dn_on() && carbon_dn_retail_mw() && carbon_dn_grade_on();
}

/* Normal race uses collection EEC2271A, layout record 3 (zero based).
 * The heat/effect blend is deliberately not mapped onto another image. */
static void carbon_mw_grade_constants(const float *look, float params[3][4]) {
    const float values[3][4] = {{.6125f,.5154f,.0721f,0},
        {1-look[4],look[4],look[5],1-look[5]},
        {look[0],look[1],look[2],look[3]}};
    memcpy(params,values,sizeof values);
}

/* 006C3B20: float-step accumulation, cubic row .y, clamp, *255, truncate.
 * Only R/G are consumed by the final grade; detail B belongs to another pass. */
static void carbon_mw_grade_spline(const float *look, uint32_t pixels[256]) {
    float step = 0;
    for (unsigned i=0;i<256;++i,step+=1.f/255.f) {
        unsigned channel[2];
        double t=step, s=1-t;
        for (unsigned k=0;k<2;++k) {
            const float *p=look+6+4*k;
            double v=t*t*t*p[3]+s*s*s*p[0]+(t*p[2]+s*p[1])*s*t*3;
            channel[k]=(unsigned)(fmin(1,fmax(0,v))*255);
        }
        pixels[i]=0xff000000u | channel[0]<<16 | channel[1]<<8;
    }
}

/* Both retail signatures are checked by the caller. Save the ungraded scene
 * before the ordinary pass adds bloom. Enhanced saves its native DOF result.
 * Replace enhanced desaturation too, before its bloom/fade/exposure tail. */
static uint32_t *carbon_mw_grade_variant(const uint32_t *tokens, uint32_t count,
                                        uint32_t *patched_count, int enhanced) {
    const uint32_t save_plain[]={0x04000004u,0x80270000u,0xa0000001u,0x80e40001u,0x80e40000u};
    const uint32_t save_enhanced[]={0x03000042u,0x802f0004u,0x80e40000u,0xa0e40805u};
    const uint32_t end_plain[]={0x03000042u,0x802f0001u,0x80e40000u,0xa0e40803u};
    const uint32_t end_enhanced[]={0x04000012u,0x80270000u,0x80ff0001u,0x80000001u,0x80e40005u};
    const uint32_t *save=enhanced?save_enhanced:save_plain, *end=enhanced?end_enhanced:end_plain;
    unsigned sn=enhanced?4:5,en=enhanced?5:4,save_at=0,end_at=0,sm=0,em=0;
    for(unsigned i=1;i+sn<count;++i) if(!memcmp(tokens+i,save,sn*4)) { save_at=i;++sm; }
    for(unsigned i=1;i+en<count;++i) if(!memcmp(tokens+i,end,en*4)) { end_at=i+en;++em; }
    if(sm!=1 || em!=1 || save_at>=end_at) return NULL;
    const uint32_t decl[]={0x0200001fu,0x90000000u,0xa00f0807u}; /* dcl_2d s7 */
    const uint32_t preserve[]={0x02000001u,0x80070006u,0x80e40000u}; /* mov r6.rgb,r0 */
    const uint32_t sample[]={
        0x03000042u,0x800f000bu,0xb0e40000u,0xa0e40802u, /* texld r11,t0,s2: native filtered RGB */
        0x03000008u,0x80010007u,0x80e4000bu,0xa0e4001au, /* dp3 r7.x,r11,c26 */
        0x03000042u,0x800f0007u,0x80000007u,0xa0e40807u, /* texld r7,r7.x,s7 */
    };
    const uint32_t desaturate[]={
        0x03000008u,0x80010008u,0x80e40006u,0xa0e4001au, /* dp3 r8.x,r6,c26 */
        0x03000005u,0x80080008u,0x80000008u,0xa055001bu, /* mul r8.w,r8.x,c27.y */
        0x04000004u,0x80070009u,0xa000001bu,0x80e40006u,0x80ff0008u, /* mad r9.rgb,c27.x,r6,r8.w */
    };
    const uint32_t colour[]={
        0x03000005u,0x80080008u,0x80550007u,0xa0ff001cu, /* mul r8.w,r7.y,c28.w */
        0x03000005u,0x8007000au,0x80ff0008u,0xa0e4001cu, /* mul r10.rgb,r8.w,c28 */
    };
    const uint32_t compose[]={
        0x04000004u,0x80080008u,0x80000007u,0xa0aa001bu,0xa0ff001bu, /* mad r8.w,r7.x,c27.z,c27.w */
        0x03000005u,0x8007000au,0x80e40006u,0x80e4000au, /* mul r10.rgb,r6,r10 */
        0x04000004u,0x8007000au,0x80e40009u,0x80ff0008u,0x80e4000au, /* mad r10.rgb,r9,r8.w,r10 */
    };
    const uint32_t blend[]={
        0x04000012u,0x80070000u,0xa0aa001fu,0x80e4000au,0x80e40000u /* lrp destination set below */
    };
    const uint32_t bloom[]={0x04000004u,0x8007000au,0xa0000001u,0x80e4000bu,0x80e4000au};
    unsigned dn=sizeof decl/4,pn=sizeof preserve/4,gn=(sizeof sample+sizeof desaturate+sizeof colour+sizeof compose+sizeof blend)/4,bn=enhanced?0:5;
    uint32_t *out=(uint32_t *)malloc((count+dn+pn+gn+bn)*4);
    if(!out) return NULL;
    unsigned at=0;
    /* Declarations precede all executable instructions (and follow comments). */
    unsigned declaration=1;
    if((tokens[1]&0xffffu)==0xfffeu) declaration+=1+((tokens[1]>>16)&0x7fffu);
    memcpy(out,tokens,declaration*4);at=declaration;
    memcpy(out+at,decl,sizeof decl);at+=dn;
    memcpy(out+at,tokens+declaration,(save_at-declaration)*4);at+=save_at-declaration;
    memcpy(out+at,preserve,sizeof preserve);at+=pn;
    memcpy(out+at,tokens+save_at,(end_at-save_at)*4);at+=end_at-save_at;
    memcpy(out+at,sample,sizeof sample);at+=sizeof sample/4;
    memcpy(out+at,desaturate,sizeof desaturate);at+=sizeof desaturate/4;
    memcpy(out+at,colour,sizeof colour);at+=sizeof colour/4;
    memcpy(out+at,compose,sizeof compose);at+=sizeof compose/4;
    /* Ordinary bloom moves around the replacement grade so it survives, while
     * the source grade still sees the raw scene. Enhanced adds it in its tail. */
    if(bn) { memcpy(out+at,bloom,sizeof bloom);at+=bn; }
    memcpy(out+at,blend,sizeof blend);
    out[at+1]=0x80070000u | (enhanced?0:1);
    out[at+4]=0x80e40000u | (enhanced?0:1);
    at+=5;
    memcpy(out+at,tokens+end_at,(count-end_at)*4);
    *patched_count=count+dn+pn+gn+bn;
    return out;
}

/* Guest resource upload, separated from the pure grade for interpreter tests. */
static int carbon_mw_grade_bind(Cpu *c, uint32_t device, uint32_t vt) {
    static uint32_t texture, texture_device;
    Cpu upload=*c; upload.esp-=128;
    uint32_t scratch=upload.esp;
    if(texture && texture_device!=device) texture=0;
    if(!texture) {
        M32(scratch)=0;
        uint32_t args[]={device,256,1,1,0,21,1,scratch,0};
        call_guest(&upload,M32(vt+23*4),9,args);
        texture=M32(scratch);
        if((int32_t)upload.eax<0 || !texture) return 0;
        texture_device=device;
        uint32_t tv=M32(texture);
        uint32_t lock[]={texture,0,scratch,0,0};
        call_guest(&upload,M32(tv+19*4),5,lock);
        if((int32_t)upload.eax<0 || !M32(scratch+4)) {
            uint32_t release[]={texture};call_guest(&upload,M32(tv+2*4),1,release);
            texture=0;return 0;
        }
        uint32_t pixels[256];carbon_mw_grade_spline(LOOK_PC[3],pixels);
        memcpy(G+M32(scratch+4),pixels,sizeof pixels);
        uint32_t unlock[]={texture,0};call_guest(&upload,M32(tv+20*4),2,unlock);
    }
    uint32_t bind[]={device,7,texture};call_guest(&upload,M32(vt+65*4),3,bind);
    const uint32_t states[][2]={{1,3},{2,3},{5,1},{6,1},{7,0}};
    for(unsigned i=0;i<sizeof states/sizeof *states;++i) {
        uint32_t args[]={device,7,states[i][0],states[i][1]};
        call_guest(&upload,M32(vt+69*4),4,args);
    }
    float params[3][4];carbon_mw_grade_constants(LOOK_PC[3],params);
    memcpy(G+scratch,params,sizeof params);
    uint32_t args[]={device,26,scratch,3};call_guest(&upload,M32(vt+109*4),4,args);
    return 1;
}
