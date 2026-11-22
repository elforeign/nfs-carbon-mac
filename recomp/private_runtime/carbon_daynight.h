/* Optional daylight for native world effects; all original fog/alpha survives. */
#include "host.h"
#include "daynight.h"
#include "daynight_clock.h"
#include <math.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include "carbon_daynight_shader.h"
#if __has_include("carbon_worldreflect_shader.inc")
#include "carbon_worldreflect_shader.inc"
#define CARBON_WORLDREFLECT 1
#else
#define CARBON_WORLDREFLECT 0
static uint32_t *carbon_worldreflect_shader_variant(const uint32_t *original,
    uint32_t count, const uint32_t *current, uint32_t current_count, uint32_t *patched_count) {
    (void)original; (void)count; (void)current; (void)current_count; (void)patched_count;
    return NULL;
}
#endif

/* Resolve the shared pure functions once when enabled. This keeps Off linkable
 * while the shared integration has not selected its math unit for this image. */
#include <dlfcn.h>
static double (*carbon_dn_wrap)(double);
static void (*carbon_dn_sample)(double, float, float, DaynightSample *);
static void (*carbon_dn_mix)(DaynightRecord *, const DaynightRecord *, float);
static void (*carbon_dn_night_record)(DaynightRecord *);
static void (*carbon_dn_step)(DaynightClock *, const DaynightClockInput *,
                              DaynightMode, double, double, double, DaynightClockOutput *);
extern int diag_on;
extern void diag_event(const char *, ...);

static int carbon_dn_configured, carbon_dn_enabled, carbon_dn_fixed;
static double carbon_dn_fixed_hour;
static DaynightClock carbon_dn_policy;
static struct {
    uint32_t object;
    double hour;
    float phase, weight;
    int ready, blended;
    DaynightSample sample;
    DaynightRecord record;
} carbon_dn_clock;

static int carbon_dn_on(void) {
    if (carbon_dn_configured) return carbon_dn_enabled;
    carbon_dn_configured = 1;
    const char *setting = getenv("NFS_DAYNIGHT");
    carbon_dn_enabled = setting && (!strcmp(setting,"1") || !strcasecmp(setting,"on"));
    if (!carbon_dn_enabled) return 0;
    carbon_dn_wrap = (double (*)(double))dlsym(RTLD_DEFAULT,"daynight_wrap");
    carbon_dn_sample = (void (*)(double,float,float,DaynightSample *))dlsym(RTLD_DEFAULT,"daynight_sample");
    carbon_dn_mix = (void (*)(DaynightRecord *,const DaynightRecord *,float))dlsym(RTLD_DEFAULT,"daynight_mix");
    carbon_dn_night_record = (void (*)(DaynightRecord *))dlsym(RTLD_DEFAULT,"daynight_night_record");
    carbon_dn_step = (void (*)(DaynightClock *,const DaynightClockInput *,DaynightMode,
                              double,double,double,DaynightClockOutput *))dlsym(RTLD_DEFAULT,"daynight_clock_step");
    if (!carbon_dn_wrap || !carbon_dn_sample || !carbon_dn_mix || !carbon_dn_night_record || !carbon_dn_step) {
        fprintf(stderr,"NFS_DAYNIGHT: shared daylight math is not linked for this image\n");
        exit(2);
    }
    setting = getenv("NFS_TEST_DAYNIGHT_HOUR");
    if (setting && *setting) {
        char *end;
        double hour = strtod(setting,&end);
        if (!*end && isfinite(hour) && hour >= 0 && hour <= 24) {
            carbon_dn_fixed = 1;
            carbon_dn_fixed_hour = carbon_dn_wrap(hour);
        }
    }
    return 1;
}

static float carbon_dn_float(uint32_t address) {
    float value;
    memcpy(&value, gptr(address), sizeof value);
    return value;
}
static void carbon_dn_write(uint32_t address, float value) {
    memcpy(G + address, &value, sizeof value);
}

static double carbon_dn_number(const char *key, double fallback, double min, double max) {
    const char *text = getenv(key);
    if (!text || !*text) return fallback;
    char *end;
    double value = strtod(text, &end);
    return end != text && !*end && isfinite(value) && value >= min && value <= max ? value : fallback;
}

#include "carbon_daynight_sky.h"

/* NFS_DAYNIGHT_TREES (On unless 0/off): converted source trees (material word
 * 00060000) take the source tree day contract; Off keeps every program unchanged. */
static int carbon_dn_trees_on(void) {
    static int configured, enabled;
    if (configured) return enabled;
    configured = 1;
    const char *setting = getenv("NFS_DAYNIGHT_TREES");
    enabled = carbon_dn_on() && !(setting && (!strcmp(setting,"0") || !strcasecmp(setting,"off")));
    return enabled;
}

#include "carbon_daynight_grade.h"

/* Submission is synchronous for this image. The caller temporarily substitutes
 * these tokens only while compiling; cache identities and Off tokens survive. */
uint32_t *carbon_daynight_shader(const uint32_t *tokens, uint32_t count, uint32_t *patched_count) {
    uint32_t *facade = carbon_facade_shader_variant(tokens,count,patched_count);
    if (facade) return facade;
    if (carbon_dn_grade_on()) {
        uint32_t *grade = carbon_dn_grade_variant(tokens,count,patched_count);
        if (grade) return grade;
    }
    carbon_dn_sky_compiled(tokens,count);
    uint32_t *variant = NULL;
    uint32_t variant_count = count;
    if (carbon_dn_on()) variant = carbon_dn_world_variant(tokens,count,&variant_count,carbon_dn_trees_on());
    uint32_t *reflect = carbon_worldreflect_shader_variant(tokens,count,
        variant ? variant : tokens,variant_count,patched_count);
    if (reflect) { free(variant); return reflect; }
    if (variant) { *patched_count=variant_count; return variant; }
    return carbon_dn_on() ? carbon_dn_sky_variant(tokens,count,patched_count) : NULL;
}

/* Day weight of the converted-material paths. Zero with the clock absent,
 * unready or at night: tagged draws then keep the native result, exactly as
 * native materials do (their baked colour weight is the same night value). */
static float carbon_compat_day(void) {
    if (!carbon_dn_on() || M32(0x00A99BBCu) != 6 ||
        !carbon_dn_clock.ready || !carbon_dn_clock.blended) return 0;
    return fminf(1,fmaxf(0,1-carbon_dn_clock.sample.night));
}

/* Native effect 1: source texture handles are already resolved in draw+0C
 * (normal) and draw+14 (specular), from material bytes +19 and +1B. The
 * native techniques omit source specular. Bind it on reserved samplers;
 * native CommitChanges declares no s5/s6 and no c21..25/c31/c248. */
static int carbon_reflect_draw(Cpu *c, void (*original)(Cpu *)) {
    uint32_t draw=M32(c->esp+16), mesh=draw?M32(draw+0x1c):0;
    if (!mesh || (M32(mesh+0x30)&0xffffu)!=1 || M32(c->ecx+4)!=1) return 0;
    float day=CARBON_WORLDREFLECT && M32(mesh+0x30)==0x00010001u ? carbon_compat_day() : 0;
    uint32_t device=M32(0x00AB0ABCu), vt=device?M32(device):0;
    if (vt) {
        /* SetWorld retained c244..246 even when the effect omitted cmWorldMat.
         * Classification belongs to this material, independent of placement,
         * clock and day weight. Reset on native reflective draws too. */
        float road[4]={0,0,0,M32(mesh+0x30)==0x00010001u ? 1.f : 0.f};
        Cpu road_upload=*c; road_upload.esp-=sizeof road;
        memcpy(G+road_upload.esp,road,sizeof road);
        uint32_t road_args[]={device,247,road_upload.esp,1};
        call_guest(&road_upload,M32(vt+94*4),4,road_args);
        /* c31.y blends the source transport over the native result. */
        float selector[4]={0,day,0,0};
        Cpu upload=*c; upload.esp-=128;
        memcpy(G+upload.esp,selector,16);
        uint32_t select[]={device,31,upload.esp,1};
        call_guest(&upload,M32(vt+109*4),4,select);
        if (day>0) {
            uint32_t tod=M32(0x00B77F34u);
            float params[5][4]={{4*.220097f,4*.236764f,4*.263431f,4},
                {.532102f,.476753f,.452102f,0},{.58f,.52f,.41f,0},{0},{2,-1,11,0}};
            for (int k = 0; k < 3; ++k) {
                params[1][k] *= carbon_dn_clock.weight;
                params[2][k] *= carbon_dn_clock.weight;
            }
            /* Match the native dryroad/raining_on_road selector (00748B50).
             * A650E0 is a render-pass brightness, unrelated to weather. */
            uint32_t active=M32(0x00AB08F4u);
            uint32_t view=active?M32(0x00B4AF7Cu+M32(active+4)*0x80u):0;
            params[2][3]=view?fminf(1,fmaxf(0,carbon_dn_float(view+0x28c))):0;
            memcpy(G+upload.esp,params,sizeof params);
            uint32_t pa[]={device,21,upload.esp,5};
            call_guest(&upload,M32(vt+109*4),4,pa);
            float light[4]={0,0,1,0};
            if(tod) memcpy(light,G+tod+0x160,12);
            memcpy(G+upload.esp,light,16);
            uint32_t va[]={device,248,upload.esp,1};
            call_guest(&upload,M32(vt+94*4),4,va);
            for(unsigned sampler=5;sampler<=6;++sampler) {
                uint32_t ta[]={device,sampler,M32(draw+(sampler==5?0x14:0xc))};
                call_guest(&upload,M32(vt+65*4),3,ta);
                /* Source UVs repeat, with the same maximum-quality filtering. */
                for(unsigned state=1;state<=10;++state) {
                    if(state==4 || state==9) continue;
                    uint32_t value=state<=3?1:state==5?2:state==6?3:state==7?2:state==10?16:0;
                    uint32_t sa[]={device,sampler,state,value};
                    call_guest(&upload,M32(vt+69*4),4,sa);
                }
            }
        }
    }
    original(c);return 1;
}

/* 0071ECB0(effect, vertex count, first index, triangles, draw): the final
 * indexed mesh draw, after native effect/world/material setup. draw+1C is
 * the 144-byte material, whose +30 low ushort is the native effect ID.
 * CommitChanges only uploads the program's declared constants, below these
 * reserved registers. Reset both blend weights on every draw, including native. */
/* Source tree leaves (lightmaterial treeleaves: floor .13, scale 1.2, wrap
 * .24) under the source X360 sun .6/.48/.22; the source x2 is folded in.
 * VS c250/c251 are set only around tagged draws, so every other draw sees
 * c251.w = 0 and keeps the native day colour. */
static int carbon_tree_draw(Cpu *c, void (*original)(Cpu *)) {
    uint32_t draw=M32(c->esp+16), mesh=draw?M32(draw+0x1c):0;
    if (!mesh || M32(mesh+0x30)!=0x00060000u || M32(c->ecx+4)!=0 ||
        !carbon_dn_trees_on() || carbon_compat_day()<=0) return 0;
    uint32_t device=M32(0x00AB0ABCu), vt=device?M32(device):0;
    if (!vt) return 0;
    float tree[2][4]={{2*1.2f*.6f,2*1.2f*.48f,2*1.2f*.22f,1},{2*.13f,2*.13f,2*.13f,.24f}};
    float none[2][4]={{0},{0}};
    Cpu upload=*c; upload.esp-=64;
    memcpy(G+upload.esp,tree,sizeof tree);
    memcpy(G+upload.esp+32,none,sizeof none);
    uint32_t on[]={device,250,upload.esp,2}, off[]={device,250,upload.esp+32,2};
    call_guest(&upload,M32(vt+94*4),4,on);
    original(c);
    upload=*c; upload.esp-=64;
    memcpy(G+upload.esp,none,sizeof none);
    off[2]=upload.esp;
    call_guest(&upload,M32(vt+94*4),4,off);
    return 1;
}

#if __has_include("carbon_c3fog.h")
#include "carbon_c3fog.h"
#endif

void carbon_facade_draw(Cpu *c, void (*original)(Cpu *)) {
    if (carbon_reflect_draw(c,original)) return;
#if __has_include("carbon_c3fog.h")
    if (carbon_c3fog_draw(c,original)) return;
#endif
    if (carbon_tree_draw(c,original)) return;
    uint32_t draw = M32(c->esp+16), mesh = draw ? M32(draw+0x1c) : 0;
    if (!mesh || (M32(mesh+0x30) & 0xffffu) != 25 || M32(c->ecx+4) != 25) {
        original(c);
        return;
    }
    float day = M32(mesh+0x30) == 0x00050019u ? carbon_compat_day() : 0;
    float vertex[4] = {8*.220097f,8*.236764f,8*.263431f,day};
    float pixel[4] = {day,0,0,0};
    uint32_t device = M32(0x00AB0ABCu), vt = device ? M32(device) : 0;
    if (vt) {
        Cpu upload = *c;
        upload.esp -= 32;
        memcpy(G+upload.esp,vertex,16);
        memcpy(G+upload.esp+16,pixel,16);
        uint32_t va[] = {device,243,upload.esp,1};
        uint32_t pa[] = {device,31,upload.esp+16,1};
        call_guest(&upload,M32(vt+94*4),4,va);
        call_guest(&upload,M32(vt+109*4),4,pa);
    }
    original(c);
}

void carbon_daynight_advance(Cpu *c, void (*original)(Cpu *)) {
    if (!carbon_dn_on()) { original(c); return; }
    uint32_t tod = c->ecx;
    DaynightClockInput input = {0};
    DaynightClockOutput output = {0};
    if (!tod || M32(0x00A99BBCu) != 6) {
        carbon_dn_step(&carbon_dn_policy,&input,DAYNIGHT_GAME,12,DAYNIGHT_SECONDS_PER_HOUR,NAN,&output);
        carbon_dn_clock.ready = carbon_dn_clock.blended = 0;
        original(c);
        return;
    }
    if (carbon_dn_clock.object != tod)
        carbon_dn_clock.blended = 0;
    carbon_dn_clock.object = tod;
    /* 00647720 sets +6A14 for a race; 00641310 clears it for roaming.
     * 0064BAF0 checks +6A18 == 3 for Career. The shared input uses 2 for Career.
     * 0075CE00 reads simulation +24 (4 is paused). */
    uint32_t race = M32(0x00A98284u), sim = M32(0x00B4CFE0u);
    input.active = 1;
    input.dt = carbon_dn_float(0x00A99A5Cu);
    input.phase = carbon_dn_float(tod+8);
    input.azimuth = carbon_dn_float(tod+0xc);
    input.tilt = carbon_dn_float(tod+0x10);
    input.race = race && M32(race+0x6a14) != 0;
    input.career = race && M32(race+0x6a18) == 3 ? 2 : 0;
    input.race_id = input.race ? M32(race+0x6a1c) : 0;
    input.paused = sim && M32(sim+0x24) == 4;
    input.override = carbon_dn_fixed;
    input.override_hour = carbon_dn_fixed_hour;
    /* Hidden saved clock preferences are not registered for this image. */
    const char *mode_text = getenv("NFS_DAYNIGHT_MODE");
    DaynightMode mode = mode_text && !strcasecmp(mode_text,"cycle") ? DAYNIGHT_CYCLE :
                        mode_text && !strcasecmp(mode_text,"fixed") ? DAYNIGHT_FIXED : DAYNIGHT_GAME;
    double hour = carbon_dn_number("NFS_DAYNIGHT_HOUR",12,0,24);
    double rate = carbon_dn_number("NFS_TEST_DAYNIGHT_RATE",DAYNIGHT_SECONDS_PER_HOUR,.000001,1e9);
    double start = carbon_dn_number("NFS_TEST_DAYNIGHT_START",NAN,0,24);
    carbon_dn_step(&carbon_dn_policy,&input,mode,hour,rate,start,&output);
    carbon_dn_clock.hour = output.hour;
    carbon_dn_clock.weight = output.weight;
    carbon_dn_clock.ready = 1;
    if (diag_on) {
        static uint64_t last;
        static double sum_dt;
        static unsigned long long frames;
        ++frames;
        if (isfinite(input.dt) && input.dt > 0) sum_dt += input.dt;
        uint64_t now = host_ticks();
        if (!last || now-last >= 1000000000ull) {
            last = now;
            diag_event("carbon_daynight_clock: T=%.9f mode=%s race=%d career=%d paused=%d held=%d sum_dt=%.9f frames=%llu wall=%.6f",
                output.hour,mode == DAYNIGHT_CYCLE ? "Cycle" : mode == DAYNIGHT_FIXED ? "Fixed" : "Game",
                input.race,input.career,input.paused,input.race || input.paused || input.override || mode == DAYNIGHT_FIXED,
                sum_dt,frames,now*1e-9);
        }
    }
    carbon_dn_sample(carbon_dn_clock.hour,carbon_dn_float(tod+0xc),carbon_dn_float(tod+0x10),&carbon_dn_clock.sample);
    DaynightSample *sample = &carbon_dn_clock.sample;
    carbon_dn_clock.phase = sample->phase;
    carbon_dn_write(tod+8,sample->phase);
    M32(tod+4) = 1;
    /* This image's direction/position are at +160/+150, not +180/+170. */
    memcpy(G+tod+0x160,sample->light,sizeof sample->light);
    carbon_dn_write(tod+0x16c,0);
    for (int k=0;k<3;++k) carbon_dn_write(tod+0x150+4*k,sample->light[k]*100000);
    carbon_dn_write(tod+0x15c,1);
    c->esp += 4;
}

void carbon_daynight_set(Cpu *c, void (*original)(Cpu *)) {
    original(c); /* Native setter consumes ST(0), not a stack float. */
    if (carbon_dn_on()) carbon_dn_clock.ready = carbon_dn_clock.blended = 0;
}

void carbon_daynight_blend(Cpu *c, void (*original)(Cpu *)) {
    uint32_t tod = c->ecx;
    original(c); /* A fresh weather/view blend every time; no accumulated mix. */
    if (!carbon_dn_on() || !tod || M32(0x00A99BBCu) != 6 ||
        !carbon_dn_clock.ready || carbon_dn_clock.object != tod) return;
    DaynightRecord *record = &carbon_dn_clock.record;
    memset(record,0,sizeof *record);
    memcpy(record->diffuse,gptr(tod+0x20),sizeof record->diffuse);
    memcpy(record->ambient,gptr(tod+0x30),sizeof record->ambient);
    DaynightRecord night;
    carbon_dn_night_record(&night);
    carbon_dn_mix(record,&night,carbon_dn_clock.sample.night);
    carbon_dn_clock.blended = 1;
    /* Keep the guest block, especially fog/sky/reflection fields, unchanged. */
}

static void carbon_dn_observe(unsigned pass) {
    static unsigned seen;
    if (!diag_on || M32(0x00A99BBCu) != 6 || (seen & (1u << pass))) return;
    uint32_t tod = M32(0x00B77F34u), fog = M32(0x00B4295Cu);
    if (!tod || !fog) return;
    seen |= 1u << pass;
    uint32_t bake = 0x00A6C204u;
    diag_event("carbon_daynight: pass=%u bake=%.6g,%.6g,%.6g,%.6g fog=%.6g,%.6g,%.6g,%.6g sun=%.6g,%.6g,%.6g ambient=%.6g,%.6g,%.6g,%.6g distances=%.9g,%.9g,%.9g,%.9g,%.9g,%.9g",
        pass, carbon_dn_float(bake), carbon_dn_float(bake+4), carbon_dn_float(bake+8), carbon_dn_float(bake+12),
        carbon_dn_float(fog), carbon_dn_float(fog+4), carbon_dn_float(fog+8), carbon_dn_float(fog+12),
        carbon_dn_float(tod+0x20), carbon_dn_float(tod+0x24), carbon_dn_float(tod+0x28),
        carbon_dn_float(tod+0x30), carbon_dn_float(tod+0x34), carbon_dn_float(tod+0x38), carbon_dn_float(tod+0x3c),
        carbon_dn_float(fog+0x10),carbon_dn_float(fog+0x14),carbon_dn_float(fog+0x18),carbon_dn_float(fog+0x1c),carbon_dn_float(fog+0x20),carbon_dn_float(fog+0x24));
}

static void carbon_dn_constants(Cpu *c) {
    if (!carbon_dn_on()) return;
    float constants[3][4] = {{0},{0,0,0,1},{0}};
    if (M32(0x00A99BBCu) == 6 && carbon_dn_clock.ready && carbon_dn_clock.blended) {
        memcpy(constants[0],carbon_dn_clock.sample.light,sizeof carbon_dn_clock.sample.light);
        for (int k = 0; k < 3; ++k)
            constants[1][k] = carbon_dn_clock.record.diffuse[k] * carbon_dn_clock.weight;
        constants[1][3] = carbon_dn_clock.sample.night;
        memcpy(constants[2],carbon_dn_clock.record.ambient,3*sizeof(float));
        constants[2][3] = carbon_dn_clock.weight;
        if (diag_on) {
            static int recorded;
            if (!recorded) {
                recorded = 1;
                diag_event("carbon_daynight: constants hour=%.6g light=%.6g,%.6g,%.6g night=%.6g diffuse=%.6g,%.6g,%.6g ambient=%.6g,%.6g,%.6g",
                    carbon_dn_clock.hour, constants[0][0], constants[0][1], constants[0][2],
                    constants[1][3], constants[1][0], constants[1][1], constants[1][2],
                    constants[2][0], constants[2][1], constants[2][2]);
            }
        }
    }
    uint32_t device = M32(0x00AB0ABCu), vt = device ? M32(device) : 0;
    if (!vt) return;
    /* Upload AFTER each native effect callback. A later activation can overwrite
     * constants even when the view's time-of-day blend has not run again. */
    Cpu upload = *c;
    upload.esp -= sizeof constants;
    memcpy(G+upload.esp,constants,sizeof constants);
    uint32_t args[] = {device,240,upload.esp,3};
    call_guest(&upload,M32(vt+94*4),4,args);
}

#define CARBON_DN_PASS(name, index) \
void name(Cpu *c, void (*original)(Cpu *)) { \
    original(c); carbon_dn_observe(index); carbon_dn_constants(c); \
    if (index == 4) carbon_dn_sky_constants(c); \
}
CARBON_DN_PASS(carbon_daynight_world,0)
CARBON_DN_PASS(carbon_daynight_normalmap,1)
CARBON_DN_PASS(carbon_daynight_glass,2)
CARBON_DN_PASS(carbon_daynight_reflect,3)
CARBON_DN_PASS(carbon_daynight_sky,4)
#undef CARBON_DN_PASS
