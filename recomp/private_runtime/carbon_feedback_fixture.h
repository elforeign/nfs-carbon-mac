/* Synthetic native interfaces around the translated image functions. All HID
 * entry points trap; this harness has no controller or game process. */
#include "funcs.h"
#include <stdarg.h>
#include <unistd.h>
#include <fcntl.h>
#include "carbon_feedback.c"
uint8_t *G;
int diag_on;
int carbon_fixture_image_match = 1;
static char summary[1024];
static unsigned activity_forwards, sampler_calls;
void prompts_input(int pad) { (void)pad;++activity_forwards; }
void prompts_mouse_moved(float points) { (void)points;++activity_forwards; }
int osk_pad(int port, uint32_t buttons, int up, int down, int left, int right,
            float lx, float ly, int connected, int xbox) {
    (void)port;(void)buttons;(void)up;(void)down;(void)left;(void)right;
    (void)lx;(void)ly;(void)connected;(void)xbox;++activity_forwards;return 0;
}
#include "carbon_feedback_input.h"
const char *diag_dir = "/nonexistent", *game_dir = "/nonexistent";
static uint64_t clock_ns = 1000000000;
static HostFn callbacks[128];
static unsigned ncallbacks, checks, failures, wheel_calls, real_opens, real_writes;
static int active_pad = 1, shift_state, nos_state;
static unsigned native_counts[18], provider_counts[18];
static float speed = 20;
#define CHECK(x) do { ++checks; if (!(x)) { ++failures; fprintf(stderr,"FAIL %d: %s\n",__LINE__,#x); } } while(0)
uint64_t host_ticks(void) { return clock_ns; }
void diag_event(const char *fmt, ...) {
    if (!strncmp(fmt,"feedback:",9)) {
        char line[192];va_list ap;va_start(ap,fmt);vsnprintf(line,sizeof line,fmt,ap);va_end(ap);
        strncat(summary,line,sizeof summary-strlen(summary)-1);
    }
}
void diag_event_ring(const char *fmt, ...) { (void)fmt; }
void padfx_stop(void) {}
/* Model-only fixture: production now selects the real shared host units. */
void rumble_stop(void) {}
void rumble_suppress(int on) { (void)on; }
void padfx_poll(void) {}
void padfx_suppress(unsigned reason, int on) { (void)reason; (void)on; }
/* Strong sampler definitions must replace the production weak link defaults. */
int padfx_wanted(void) { return 1; }
int padfx_road_wanted(void) { return 1; }
void padfx_game_tick(Cpu *c, uint32_t player) {
    (void)c;++sampler_calls;CHECK(player==0x2000);CHECK(M32(player+0x54)==0x9000);
}
int pad_identity(char *name, size_t n) { (void)name; (void)n; return active_pad ? PAD_KIND_DUALSENSE : PAD_KIND_NONE; }
/* Any output implementation accidentally selected by this fixture fails. */
int IOHIDDeviceOpen(void *device, unsigned options) { (void)device;(void)options;++real_opens;abort(); }
int IOHIDDeviceSetReport(void *device, int type, int id, const void *data, long n) {
    (void)device;(void)type;(void)id;(void)data;(void)n;++real_writes;abort();
}
uint32_t galloc(uint32_t n) { static uint32_t next=0x90000;uint32_t p=next;next+=n;return p; }
uint32_t host_fn(HostFn fn, const char *name) { (void)name;CHECK(ncallbacks<128);callbacks[ncallbacks]=fn;return HOSTFN_BASE+4*ncallbacks++; }
void bad_jump(Cpu *c,uint32_t at) { (void)c;fprintf(stderr,"bad jump %x\n",at);abort(); }
void untranslated(Cpu *c,uint32_t at) { bad_jump(c,at); }
void host_import(Cpu *c,uint32_t at) { bad_jump(c,at); }
void abi_violation(Cpu *c,uint32_t fn,uint32_t b,uint32_t s,uint32_t d,uint32_t p,uint32_t sp) {
    (void)c;(void)b;(void)s;(void)d;(void)p;(void)sp;fprintf(stderr,"ABI %x\n",fn);abort();
}
static int value0(Cpu *c) { RET(0,0); }
static int value1(Cpu *c) { RET(1,0); }
static int simable_get(Cpu *c) { RET(0x3000,0); }
static int wheel_tick(Cpu *c) { ++wheel_calls;RET(0,1); }
static int float_speed(Cpu *c) { x87_push(c,speed);RET(0,0); }
static int float_rpm(Cpu *c) { x87_push(c,3000);RET(0,0); }
static int float_low(Cpu *c) { x87_push(c,1000);RET(0,0); }
static int float_high(Cpu *c) { x87_push(c,6000);RET(0,0); }
static int float_one(Cpu *c) { x87_push(c,1);RET(0,0); }
static int wheels_count(Cpu *c) { RET(4,0); }
static int wheel_contact(Cpu *c) { RET(1,1); }
static int wheel_surface(Cpu *c) { RET(0x8000,1); }
static int wheel_scalar(Cpu *c) { x87_push(c,1);RET(0,1); }
static int shift_get(Cpu *c) { RET(shift_state,0); }
static int nos_get(Cpu *c) { RET(nos_state,0); }
static int nos_capacity(Cpu *c) { RET(nos_state,0); }
static int velocity_get(Cpu *c) { float v[3]={10,0,0};memcpy(G+arg(c,0),v,12);RET(0,1); }
static void query(Cpu *c,uint32_t object) { M32(arg(c,0))=object;c->eax=1;c->esp+=8; }
void f_0060CB50(Cpu *c) { c->eax=arg(c,0)==0x403AA0 ? 0x4000 : 0x6000;c->esp+=8; }
void f_0040E650(Cpu *c) { query(c,0x5000); }
void f_0040F020(Cpu *c) { query(c,0x7000); }
void f_0040EEC0(Cpu *c) { query(c,0x4000); }
void f_0040F1F0(Cpu *c) { query(c,0x5000); }
void f_006E6930(Cpu *c) { c->eax=0;c->esp+=8; }
void f_00761B00(Cpu *c) { (void)c;abort(); }
void f_004789A0(Cpu *c) { memcpy(G+c->ecx,G+arg(c,0),8);c->eax=c->ecx;c->esp+=8; }
void f_00469870(Cpu *c) { c->esp+=4; }
void f_004ABBA0(Cpu *c) { M32(arg(c,0))=0x6000;c->eax=1;c->esp+=8; }
void f_00402230(Cpu *c) { x87_push(c,fabsf(argf(c,0)));c->esp+=4; }
void f_00402290(Cpu *c) { x87_push(c,fminf(fmaxf(argf(c,0),argf(c,1)),argf(c,2)));c->esp+=4; }
void f_00402500(Cpu *c) { c->eax=arg(c,0)==arg(c,1);c->esp+=4; }
void f_0060CBA0(Cpu *c) { c->eax=arg(c,2)==42 ? 0xA000 : 0;c->esp+=4; }
/* The real surface accessor delegates with ECX = *surface, not surface+4.
 * Only the collection's attribute storage is synthetic. Curve bytes are read
 * from the private attributes pack by the Python driver. */
void f_00463480(Cpu *c) {
    uint32_t key=arg(c,0), index=arg(c,1);
    c->eax=c->ecx==0x8100 && key==0xBA1297DA && index<1 ? 0x8200+32*index : 0;
    c->esp+=12;
}
void f_00679FA0(Cpu *c) { c->esp+=4; }
void f_0067A020(Cpu *c) { f_00679FA0(c); }
void carbon_orig_00762000(Cpu *c);
static const uint32_t native_slots[18] = {0x6807E0,0x679FA0,0x67A010,0x67A020,0x67A030,0x67A040,
    0x67A050,0x67A060,0x67A070,0x67A080,0x67A090,0x67A0A0,0x67A0B0,0x67A0C0,0x67A0E0,0x6807C0,0x6807D0,0x67A0D0};
void dispatch(Cpu *c,uint32_t t) {
    uint32_t sp=c->esp;
    for(unsigned i=1;i<18;++i) {
        if(t==native_slots[i]) ++native_counts[i];
        if(t==M32(FEEDBACK_VTABLE+4*i) && t>=HOSTFN_BASE) ++provider_counts[i];
    }
    if(t>=HOSTFN_BASE && (t-HOSTFN_BASE)/4<ncallbacks) callbacks[(t-HOSTFN_BASE)/4](c);
    else switch(t) {
#define NATIVE(a) case 0x##a: f_##a(c);break
        NATIVE(00679FA0); NATIVE(0067A010); NATIVE(0067A020); NATIVE(0067A030); NATIVE(0067A040);
        NATIVE(0067A050); NATIVE(0067A060); NATIVE(0067A070); NATIVE(0067A080); NATIVE(0067A090);
        NATIVE(0067A0A0); NATIVE(0067A0B0); NATIVE(0067A0C0); NATIVE(0067A0D0); NATIVE(0067A0E0);
        NATIVE(006807C0); NATIVE(006807D0); NATIVE(00463A80); NATIVE(0060CBA0); NATIVE(0040E650);
        default: fprintf(stderr,"unexpected dispatch %x ecx=%x ret=%x\n",t,c->ecx,M32(sp));abort();
    }
    /* Each individual callback must balance its own stack. The independent ABI
     * table is supplied by the driver from decoded return instructions. */
    for(unsigned i=1;i<18;++i) if(t==M32(FEEDBACK_VTABLE+4*i)) CHECK(c->esp==sp+4+4*expected_arguments[i]);
}
uint32_t call_guest(Cpu *c,uint32_t fn,int n,const uint32_t *a) {
    uint32_t sp=c->esp;
    for(int i=n-1;i>=0;--i){c->esp-=4;M32(c->esp)=a[i];}
    c->esp-=4;M32(c->esp)=0xFEEDF00D;
    dispatch(c,fn);c->esp=sp;return c->eax;
}
static void bind(uint32_t table,unsigned slot,HostFn fn) { M32(table+slot)=host_fn(fn,"fixture"); }
static Cpu initial(void) { Cpu c={0};c.esp=0x80000;c.ecx=0x2000;c.fs_base=0x1000;c.cw=0x37F;return c; }
static void tick(int hooked) {
    Cpu c=initial();clock_ns+=16000000;
    if(hooked) f_00762000(&c); else carbon_orig_00762000(&c);
    CHECK(c.esp==0x80004);CHECK(c.top==0);CHECK(M32(0x2054)==0x9000);
}
static void reset(void) {
    memset(&S,0,sizeof S);memset(ncalls,0,sizeof ncalls);memset(provider_counts,0,sizeof provider_counts);
    last_tick=clock_ns;shift_state=nos_state=0;effects_valid=0;speed=20;sampler_calls=0;
}
static unsigned unbound_calls;
static void unbound_original(Cpu *c) { CHECK(M32(c->ecx+0x54)==0x9000);++unbound_calls;c->esp+=4; }
static void collide(void) {
    Cpu c=initial();c.ecx=0x2000+0x4C;M32(c.esp+4)=0xB000;
    M32(0xB000+0x1C)=2;M32(0xB000+0x3C)=42;MF32(0xB000+0x50)=30;
    f_00765240(&c);CHECK(c.esp==0x80008);
}
static float level(void) { float l,r;clock_ns+=16000000;feedback_levels(&l,&r);return fmaxf(l,r); }
int main(int argc,char **argv) {
    CHECK(argc==4);G=calloc(1,0x1000000);CHECK(G);
    FILE *f=fopen(argv[1],"rb");CHECK(f);CHECK(fread(G,1,0x1000000,f)==0x1000000);fclose(f);
    f=fopen(argv[2],"rb");CHECK(f);CHECK(fread(G+0x8200,1,128,f)==128);fclose(f);
    f=fopen(argv[3],"rb");CHECK(f);CHECK(!fseek(f,0,SEEK_END));long raw_size=ftell(f);CHECK(raw_size>0);rewind(f);
    unsigned char *raw=malloc((size_t)raw_size);CHECK(raw);CHECK(fread(raw,1,(size_t)raw_size,f)==(size_t)raw_size);fclose(f);
    CHECK(carbon_feedback_image_validate(raw,(size_t)raw_size));
    setenv("NFS_RUMBLE","off",1);
    M32(0x2000+0x24)=0x2100;bind(0x2100,0x0C,simable_get);
    M32(0x2000+0x44)=0x2200;bind(0x2200,0x14,value1);
    M32(0x2000+0x50)=0x2300;M32(0x2300)=FEEDBACK_VTABLE;
    M32(0x2054)=0x9000;M32(0x9000)=0x9100;bind(0x9100,0x0C,value1);bind(0x9100,4,wheel_tick);
    M32(0x3000)=0x3100;M32(0x3004)=0x3000;bind(0x3100,0x68,velocity_get);
    M32(0x4000)=0x4100;bind(0x4100,4,float_rpm);bind(0x4100,8,float_high);bind(0x4100,0xC,float_rpm);
    bind(0x4100,0x10,float_low);bind(0x4100,0x1C,float_one);bind(0x4100,0x20,nos_capacity);bind(0x4100,0x2C,nos_get);
    M32(0x5000)=0x5100;bind(0x5100,0x10,value0);bind(0x5100,0x2C,shift_get);bind(0x5100,0x34,value0);
    bind(0x5100,0x68,velocity_get);bind(0x5100,0xAC,float_speed);bind(0x5100,0xD0,value0);bind(0x5100,0xF4,value0);
    M32(0x6000)=0x6100;bind(0x6100,4,value0);bind(0x6100,8,value0);bind(0x6100,0x10,value0);
    M32(0x7000)=0x7100;bind(0x7100,8,wheels_count);bind(0x7100,0x24,wheel_contact);bind(0x7100,0x44,wheel_surface);
    bind(0x7100,0x30,wheel_scalar);bind(0x7100,0x38,wheel_scalar);
    M32(0x8000)=0x8100;M32(0x8004)=0xDEAD;nsnames=1;snames[0].coll=0x8100;
    M32(0xA9E86C)=0x3000;M32(0xA9E674)=1;M32(0xA631A8)=1;
    M32(0xAA26B4)=0xA000;M32(0xAA26BC)=1;M32(0xA000)=42;M32(0xA004)=0x3000;
    /* Baseline: the unmodified translated tick short-circuits to the wheel;
     * forcing the pad route still calls fifteen inert methods, with no output. */
    for(unsigned i=1;i<18;++i) if(i!=1 && i!=3) {
        Cpu c=initial();for(unsigned a=0;a<3;++a)M32(c.esp+4+4*a)=0;
        dispatch(&c,native_slots[i]);CHECK(c.esp==0x80004+4*expected_arguments[i]);CHECK(level()==0);
    }
    memset(native_counts,0,sizeof native_counts);shift_state=3;nos_state=1;
    tick(0);CHECK(wheel_calls==1);CHECK(level()==0);
    M32(0x2054)=0;Cpu baseline=initial();carbon_orig_00762000(&baseline);M32(0x2054)=0x9000;
    collide();CHECK(native_counts[17]==1 && native_counts[10]==1 && native_counts[11]==1);
    CHECK(native_counts[6]==4 && native_counts[7]==4 && native_counts[8]==4);CHECK(level()==0);
    printf("BASELINE return-only=15 speed/skid/slip=%u/%u/%u model=0\n",native_counts[6],native_counts[7],native_counts[8]);
    uint32_t table[18];memcpy(table,G+FEEDBACK_VTABLE,sizeof table);
    unsigned before=ncallbacks;raw[0]^=1;CHECK(!carbon_feedback_image_validate(raw,(size_t)raw_size));feedback_setup();
    CHECK(ncallbacks==before);CHECK(!memcmp(table,G+FEEDBACK_VTABLE,sizeof table));
    Cpu unbound=initial();carbon_feedback_tick(&unbound,unbound_original);CHECK(unbound_calls==1 && unbound.esp==0x80004);
    CHECK(M32(0x2054)==0x9000);raw[0]^=1;
    CHECK(carbon_feedback_image_validate(raw,(size_t)raw_size));free(raw);
    carbon_fixture_image_match=0;feedback_setup();
    CHECK(ncallbacks==before);CHECK(!memcmp(table,G+FEEDBACK_VTABLE,sizeof table));carbon_fixture_image_match=1;
    M32(FEEDBACK_VTABLE)^=1;feedback_setup();
    CHECK(ncallbacks==before);CHECK(M32(FEEDBACK_VTABLE)==(table[0]^1));memcpy(G+FEEDBACK_VTABLE,table,sizeof table);
    feedback_setup();CHECK(ncallbacks==before+17);CHECK(M32(FEEDBACK_VTABLE)==table[0]);
    feedback_setup();CHECK(ncallbacks==before+17);
    /* Independently exercise all seventeen argument counts, including the
     * unknown slots that a four-wheel tick does not necessarily invoke. */
    unsigned balanced=0;
    for(unsigned i=1;i<18;++i) {
        Cpu c=initial();for(unsigned a=0;a<3;++a)M32(c.esp+4+4*a)=0;
        uint32_t sp=c.esp;unsigned count=ncalls[i];dispatch(&c,M32(FEEDBACK_VTABLE+4*i));
        CHECK(c.esp==sp+4+4*expected_arguments[i]);CHECK(ncalls[i]==count+1);
        balanced += c.esp==sp+4+4*expected_arguments[i];
    }
    diag_on=1;float l,r;feedback_levels(&l,&r);diag_on=0;
    CHECK(strstr(summary,"Slot38") && strstr(summary,"Slot3C") && strstr(summary,"Slot40") && strstr(summary,"Collision"));
    printf("ABI balanced=%u/17\n",balanced);
    if (balanced!=17) { printf("FEEDBACK FAIL balanced=%u/17\n",balanced);return 1; }
    reset();tick(1);
    CHECK(provider_counts[4]==1 && provider_counts[5]==1);
    CHECK(provider_counts[6]==4 && provider_counts[7]==4 && provider_counts[8]==4);
    CHECK(ncalls[4]==1 && ncalls[5]==1 && ncalls[6]==4 && ncalls[7]==4 && ncalls[8]==4);
    CHECK(level()>0);CHECK(wheel_calls==1);CHECK(surf_index(0x8000)==0);CHECK(sampler_calls==1);
    float road_speed,road_surface;feedback_road_state(&road_speed,&road_surface);CHECK(road_speed==20 && fabsf(road_surface-.1f)<.0001f); /* collection at +0 */
    printf("TICK Begin/End=%u/%u speed/skid/slip=%u/%u/%u model=%.3f\n",provider_counts[4],provider_counts[5],provider_counts[6],provider_counts[7],provider_counts[8],level());
    unsigned char model[sizeof S];memcpy(model,&S,sizeof S);
    for (unsigned i=9;i<17;++i) if (i==9 || i>=14) {
        Cpu c=initial();for(unsigned a=0;a<3;++a)M32(c.esp+4+4*a)=123;
        dispatch(&c,M32(FEEDBACK_VTABLE+4*i));CHECK(!memcmp(model,&S,sizeof S));
    }
    reset();active_pad=0;tick(1);CHECK(wheel_calls==2);CHECK(provider_counts[4]==0);CHECK(sampler_calls==0);active_pad=1;
    reset();prompts_input(0);tick(1);CHECK(wheel_calls==3);CHECK(provider_counts[4]==0);CHECK(sampler_calls==0);CHECK(activity_forwards==1);
    osk_pad(1,1,0,0,0,0,0,0,1,0);CHECK(carbon_feedback_active_input==0);
    osk_pad(0,1,0,0,0,0,0,0,1,0);CHECK(activity_forwards==3);CHECK(carbon_feedback_active_input==1);
    prompts_mouse_moved(1);CHECK(carbon_feedback_active_input==0);
    osk_pad(0,0,0,0,0,0,.5f,0,1,0);CHECK(carbon_feedback_active_input==1);
    osk_pad(0,0,0,0,0,0,0,0,0,0);CHECK(carbon_feedback_active_input==0);
    osk_pad(0,1,0,0,0,0,0,0,1,0);CHECK(carbon_feedback_active_input==1);
    reset();M32(0x8000)=0;shift_state=3;tick(1);float shift=level();CHECK(shift>0);
    reset();nos_state=1;tick(1);float nos=level();CHECK(nos>0);
    float slip[2],hz[2];int engaged;feedback_trigger_state(slip,hz,&engaged);CHECK(engaged==1);
    reset();tick(1);Cpu damage=initial();M32(damage.esp+4)=1;dispatch(&damage,M32(FEEDBACK_VTABLE+0x30));CHECK(level()>0);
    reset();tick(1);Cpu gear=initial();M32(gear.esp+4)=1;dispatch(&gear,M32(FEEDBACK_VTABLE+0x34));CHECK(level()>0);
    reset();tick(1);collide();float hit=level();CHECK(hit>0);CHECK(provider_counts[17]==1);
    unsigned begins=provider_counts[4];M32(0xA631A8)=0;shift_state=3;nos_state=1;tick(1);
    CHECK(!S.active && level()==0);CHECK(provider_counts[4]==begins && provider_counts[1]==1);
    CHECK(real_opens==0 && real_writes==0);
    printf("EDGES collision=%.3f shift=%.3f nos=%.3f real-opens=%u real-writes=%u\n",hit,shift,nos,real_opens,real_writes);
    printf("FEEDBACK %s checks=%u failures=%u\n",failures ? "FAIL" : "PASS",checks,failures);
    if(trace)fclose(trace);free(G);return failures ? 1 : 0;
}
