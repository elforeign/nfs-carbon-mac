/* Synthetic guest state and fake host queue; no controller discovery. */
#include "fake_framework.inc"
#define CARBON_PADFX_OUTPUT_TEST
#define dispatch_async test_async
#define NSThread TestThread
#define IOHIDManagerCreate test_manager_create
#define IOHIDDeviceSetReport test_set_report
#include "carbon_padfx.c"
#include "padlink.c"
#include "rumble.m"
#undef dispatch_async
#undef NSThread

uint8_t *G;
int diag_on;
static uint64_t clock_ns = 1000000000ull;
static int context = CARBON_PAD_DRIVING, interrupt_sample;
static float model_heavy = .6f, model_light = .2f, model_slip[2], model_speed = 30, model_surface = .5f;
static float model_slip2[2];
static float model_heavy2, model_light2;
static unsigned guest_calls, invalidations;
static uint64_t counter[FX_COUNT];
uint64_t host_ticks(void) {
    if (interrupt_sample) { interrupt_sample = 0; padfx_stop(); }
    return clock_ns;
}
int carbon_pad_context(void) { return context; }
void feedback_trigger_state(float slip[2], float hz[2], int *nos) {
    memcpy(slip, model_slip, sizeof model_slip); hz[0] = hz[1] = 10; *nos = 0;
}
void carbon_feedback_trigger_state(unsigned slot, float slip[2], float hz[2], int *nos) {
    feedback_trigger_state(slip,hz,nos);
    if (slot==1) memcpy(slip,model_slip2,sizeof model_slip2);
}
void carbon_feedback_road_state(unsigned slot, float *speed, float *surface) {
    (void)slot; *speed=model_speed; *surface=model_surface;
}
void feedback_road_state(float *speed, float *surface) { *speed = model_speed; *surface = model_surface; }
void feedback_levels(float *heavy, float *light) { *heavy = model_heavy; *light = model_light; }
void feedback_invalidate_effects(void) { ++invalidations; model_heavy = model_light = 0; }
void feedback_levels_slot(unsigned slot, float *heavy, float *light) {
    if (slot == 0) feedback_levels(heavy, light); else { *heavy=model_heavy2; *light=model_light2; }
}
void feedback_invalidate_slot(unsigned slot) {
    if (slot == 0) feedback_invalidate_effects();
    else { model_heavy2=model_light2=0; ++invalidations; }
}
void report_note(const char *fmt, ...) { (void)fmt; }
void diag_event(const char *fmt, ...) { (void)fmt; }
IOHIDManagerRef test_manager_create(CFAllocatorRef a, IOOptionBits b) {
    (void)a; (void)b; ++real_opens; fprintf(stderr,"FAIL forbidden open=%d\n",real_opens); exit(1);
}
IOReturn test_set_report(IOHIDDeviceRef a, IOHIDReportType b, CFIndex c, const uint8_t *d, CFIndex e) {
    (void)a;(void)b;(void)c;(void)d;(void)e;++real_writes;
    fprintf(stderr,"FAIL forbidden write=%d\n",real_writes); exit(1);
}
Trig oracle_trigger_for(int, int, float, float, const float[2], float);
static void clear_bindings(void) {
    for (unsigned a = 0; a <= 28; ++a) {
        uint32_t row = 0x20000 + a * 128;
        M32(0xA98704 + 8*a) = row;
        memset(G + row, 0, 96);
    }
    M32(0xA98948) = 1;
}
static void bind(unsigned action, int right, unsigned slot) {
    uint32_t row = M32(0xA98704 + 8*action) + 12*slot;
    M32(row) = right ? 7 : 5; M32(row+4) = 0; M32(row+8) = 2;
}
static void one_player(void) {
    M32(0xA9FF5C)=0x18000; M32(0xA9FF64)=1;
    M32(0x18000)=0x10044; M32(0x1005C)=0;
}
static void tick(void) { Cpu c = {.ecx=0x10000}; ++guest_calls; padfx_game_tick(&c,c.ecx); }
static void update(void) { padfx_update(NULL,1,.8f,0); rumble_update(); drain(); carbon_padfx_counts(counter); }
static uint64_t sustained(void) {
    carbon_padfx_counts(counter); return counter[FX_MOTOR]+counter[FX_GAS]+counter[FX_BRAKE]+counter[FX_SHIFT];
}
static void stopped(void) {
    uint64_t before = sustained();
    for (int i=0;i<8;++i) update();
    CHECK(sustained()==before); CHECK(!fx_tick[0]); CHECK(blocks.count==0);
}
static GCController *fake_controller(void) {
    GCController *ctl=[GCController new]; ctl.fake=YES;
    ctl.extendedGamepad=[GCDualSenseGamepad new];
    ctl.extendedGamepad.leftTrigger=[GCDualSenseAdaptiveTrigger new];
    ctl.extendedGamepad.rightTrigger=[GCDualSenseAdaptiveTrigger new];
    ctl.extendedGamepad.leftTrigger.fake=ctl.extendedGamepad.rightTrigger.fake=YES;
    return ctl;
}
static void split_tick(void) {
    if (!fx_holds && !fx_closed) { model_heavy=.6f; model_light=.2f; model_heavy2=.3f; model_light2=.1f; }
    Cpu c={.ecx=0x11000}; padfx_game_tick(&c,c.ecx); tick();
}
static void split_update(GCController *a, GCController *b) {
    /* Different raw pedals: P1 brakes, P2 accelerates. */
    padfx_player_update(0,(__bridge void *)a); padfx_player_update(1,(__bridge void *)b);
    padfx_update((__bridge void *)a,1,.8f,0);
    padfx_update((__bridge void *)b,1,0,.8f);
}
static void both_off(GCController *a, GCController *b) {
    CHECK(a.extendedGamepad.leftTrigger.mode==T_OFF && a.extendedGamepad.rightTrigger.mode==T_OFF);
    CHECK(b.extendedGamepad.leftTrigger.mode==T_OFF && b.extendedGamepad.rightTrigger.mode==T_OFF);
    CHECK(model_heavy==0 && model_light==0 && model_heavy2==0 && model_light2==0);
}
static void split_queue(void) {
    GCController *a=fake_controller(), *b=fake_controller();
    G=calloc(1,0x1000000); CHECK(G); clear_bindings(); bind(0,1,2); bind(1,0,2);
    M32(0xA98948)=2; bind(0,1,4); bind(1,0,4);
    for(unsigned action=0;action<2;++action) M32(M32(0xA98704+8*action)+12*4+4)=1;
    M32(0xA9FF5C)=0x18000; M32(0xA9FF64)=2;
    M32(0x18000)=0x11044; M32(0x18004)=0x10044;
    M32(0x1005C)=0; M32(0x1105C)=1;
    padfx_player_update(0,(__bridge void *)a); padfx_player_update(1,(__bridge void *)b);
    model_slip[0]=model_slip2[0]=.4f;
    Cpu p2={.ecx=0x11000}; padfx_game_tick(&p2,p2.ecx); split_update(a,b); drain();
    CHECK(a.extendedGamepad.leftTrigger.mode==T_OFF && b.extendedGamepad.rightTrigger.mode==T_VIBRATION);
    padfx_stop(); split_tick(); split_update(a,b);
    CHECK(blocks.count==2); drain();
    CHECK(a.extendedGamepad.leftTrigger.mode==T_VIBRATION && a.extendedGamepad.rightTrigger.mode==T_POSITIONAL);
    CHECK(b.extendedGamepad.leftTrigger.mode==T_POSITIONAL && b.extendedGamepad.rightTrigger.mode==T_VIBRATION);
    model_slip[0]=0; split_tick(); split_update(a,b); drain();
    CHECK(a.extendedGamepad.leftTrigger.mode==T_POSITIONAL && b.extendedGamepad.rightTrigger.mode==T_VIBRATION);
    model_slip[0]=.4f;
    /* Binding roles also belong to each native action-directory pair. */
    bind(0,0,4); bind(1,1,4);
    for(unsigned action=0;action<2;++action) M32(M32(0xA98704+8*action)+12*4+4)=1;
    split_tick(); split_update(a,b); drain();
    CHECK(b.extendedGamepad.rightTrigger.mode==T_VIBRATION && b.extendedGamepad.rightTrigger.c==.3f);
    bind(0,1,4); bind(1,0,4);
    for(unsigned action=0;action<2;++action) M32(M32(0xA98704+8*action)+12*4+4)=1;
    for(unsigned hold=1;hold<=8;hold<<=1) {
        padfx_suppress(hold,1); drain(); both_off(a,b);
        unsigned before=fake_writes; split_tick(); split_update(a,b); drain(); CHECK(fake_writes==before);
        padfx_suppress(hold,0); split_tick(); split_update(a,b); drain();
        CHECK(a.extendedGamepad.leftTrigger.mode==T_VIBRATION && b.extendedGamepad.rightTrigger.mode==T_VIBRATION);
    }
    /* Reassign while both old frames are queued, then reject those frames. */
    split_tick(); split_update(a,b);
    padfx_player_update(0,(__bridge void *)b); padfx_player_update(1,(__bridge void *)a);
    drain(); both_off(a,b);
    split_tick(); split_update(b,a); drain();
    CHECK(b.extendedGamepad.leftTrigger.mode==T_VIBRATION && a.extendedGamepad.rightTrigger.mode==T_VIBRATION);
    a.extendedGamepad.leftTrigger.detached=a.extendedGamepad.rightTrigger.detached=YES;
    padfx_disconnect((__bridge void *)a); drain();
    CHECK(b.extendedGamepad.leftTrigger.mode==T_OFF && b.extendedGamepad.rightTrigger.mode==T_OFF);
    CHECK([fx_debt containsObject:a]);
    a.extendedGamepad.leftTrigger.detached=a.extendedGamepad.rightTrigger.detached=NO;
    padfx_connect((__bridge void *)a); drain(); both_off(a,b);
    split_tick(); split_update(b,a); drain();
    padfx_disconnect(NULL); drain(); both_off(a,b);
    split_tick(); split_update(b,a); drain();
    CHECK(b.extendedGamepad.leftTrigger.mode==T_VIBRATION && a.extendedGamepad.rightTrigger.mode==T_VIBRATION);
    /* A missed notification has a known slot on the next pad read. */
    padfx_player_update(1,NULL); drain();
    CHECK([fx_debt containsObject:a] && ![fx_detached containsObject:b]);
    padfx_connect((__bridge void *)a); drain(); both_off(a,b);
    padfx_player_update(1,(__bridge void *)a); split_tick(); split_update(b,a); drain();
    /* Mode exit retires both immediately, before the stale-frame timeout. */
    M32(0xA9FF64)=0; padfx_poll(); drain(); both_off(a,b);
    M32(0xA9FF64)=2; split_tick(); split_update(b,a); drain();
    clock_ns+=300000001ull; padfx_poll(); drain(); both_off(a,b);
    split_tick(); split_update(b,a); drain();
    padfx_close(); drain(); both_off(a,b);
    CHECK(real_opens==0 && real_writes==0);
    printf("SPLIT PADFX %s checks=%d failures=%d opens=%d real_writes=%d\n",failures?"FAIL":"PASS",checks,failures,real_opens,real_writes);
    free(G);
}
static void real_queue(void) {
    GCController *ctl = [GCController new]; ctl.fake=YES;
    ctl.extendedGamepad=[GCDualSenseGamepad new];
    ctl.extendedGamepad.leftTrigger=[GCDualSenseAdaptiveTrigger new];
    ctl.extendedGamepad.rightTrigger=[GCDualSenseAdaptiveTrigger new];
    ctl.extendedGamepad.leftTrigger.fake=YES; ctl.extendedGamepad.rightTrigger.fake=YES;
    G=calloc(1,0x1000000); CHECK(G); one_player(); clear_bindings(); bind(0,1,2); bind(1,0,2);
    padfx_player_update(0,(__bridge void *)ctl);
    CHECK(!carbon_padfx_fake());
    tick();
    for(int i=0;i<100;++i) padfx_update((__bridge void *)ctl,1,.8f,0);
    CHECK(blocks.count==1); CHECK(fake_writes==0);
    padfx_stop(); tick(); drain(); CHECK(fake_writes==0); /* Cancel the old queued frame. */
    tick(); padfx_update((__bridge void *)ctl,1,.8f,0); drain();
    CHECK(fake_writes==2 && fx_owner[0]==ctl);
    CHECK(ctl.extendedGamepad.leftTrigger.mode==T_POSITIONAL);
    CHECK(ctl.extendedGamepad.rightTrigger.mode==T_POSITIONAL);
    model_slip[0]=.4f; model_slip[1]=.1f;
    padfx_update((__bridge void *)ctl,1,.8f,0); drain();
    CHECK(ctl.extendedGamepad.leftTrigger.mode==T_VIBRATION);
    CHECK(ctl.extendedGamepad.leftTrigger.c==.3f);
    padfx_update((__bridge void *)ctl,1,0,.8f); drain();
    CHECK(ctl.extendedGamepad.rightTrigger.mode==T_VIBRATION);
    CHECK(ctl.extendedGamepad.rightTrigger.c==.2f);
    padfx_update((__bridge void *)ctl,1,.8f,.8f); drain();
    CHECK(ctl.extendedGamepad.leftTrigger.mode==T_POSITIONAL && ctl.extendedGamepad.rightTrigger.mode==T_POSITIONAL);
    model_slip[0]=model_slip[1]=0;
    padfx_suppress(FEEDBACK_FOCUS,1); drain();
    CHECK(ctl.extendedGamepad.leftTrigger.mode==T_OFF && ctl.extendedGamepad.rightTrigger.mode==T_OFF);
    unsigned before=fake_writes; tick(); padfx_update((__bridge void *)ctl,1,.8f,0); drain();
    CHECK(fake_writes==before);
    padfx_suppress(FEEDBACK_FOCUS,0); tick(); padfx_update((__bridge void *)ctl,1,.8f,0); drain();
    CHECK(ctl.extendedGamepad.rightTrigger.mode==T_POSITIONAL);
    /* A removed controller ignores setters: debt must survive until reconnect. */
    ctl.extendedGamepad.leftTrigger.detached=YES; ctl.extendedGamepad.rightTrigger.detached=YES;
    padfx_disconnect((__bridge void *)ctl); drain(); CHECK([fx_debt containsObject:ctl]);
    CHECK(ctl.extendedGamepad.rightTrigger.mode==T_POSITIONAL);
    ctl.extendedGamepad.leftTrigger.detached=NO; ctl.extendedGamepad.rightTrigger.detached=NO;
    padfx_connect((__bridge void *)ctl); drain();
    CHECK(ctl.extendedGamepad.rightTrigger.mode==T_OFF && ![fx_debt containsObject:ctl]);
    tick(); padfx_update((__bridge void *)ctl,1,.8f,0);
    clock_ns+=300000001ull; drain(); CHECK(ctl.extendedGamepad.rightTrigger.mode==T_OFF);
    padfx_poll();
    /* A late release from an old epoch cannot clear a newer applied frame. */
    on_main=NO; padfx_stop(); on_main=YES;
    tick(); padfx_update((__bridge void *)ctl,1,.8f,0);
    dispatch_block_t late=blocks[0]; [blocks removeObjectAtIndex:0]; drain(); late();
    CHECK(ctl.extendedGamepad.rightTrigger.mode==T_POSITIONAL);
    padfx_stop(); tick(); padfx_update((__bridge void *)ctl,1,.8f,0);
    padfx_stop(); tick(); padfx_update((__bridge void *)ctl,1,.8f,0);
    before=fake_writes;
    dispatch_block_t stale=blocks[0]; [blocks removeObjectAtIndex:0]; stale();
    CHECK(fake_writes==before); drain();
    CHECK(ctl.extendedGamepad.rightTrigger.mode==T_POSITIONAL);
    padfx_close(); drain(); CHECK(ctl.extendedGamepad.rightTrigger.mode==T_OFF);
    CHECK(real_opens==0 && real_writes==0);
    printf("QUEUE %s checks=%d failures=%d fake_writes=%d opens=%d real_writes=%d\n",
        failures?"FAIL":"PASS",checks,failures,fake_writes,real_opens,real_writes);
    free(G);
}
int main(int argc, char **argv) { @autoreleasepool {
    (void)argv;
    if(argc>1) { if(!strcmp(argv[1],"split")) split_queue(); else real_queue(); return failures!=0; }
    setenv("NFS_RUMBLE","on",1); /* Fake mode must beat discovery even when requested. */
    G = calloc(1,0x1000000); CHECK(G);
    one_player();
    CHECK(carbon_padfx_fake()); CHECK(padfx_wanted());
    clear_bindings(); bind(0,1,2); bind(1,0,2);
    /* Opposing MW fields ensure a wrong-image offset cannot accidentally pass. */
    M8(0x10078)=1; MF32(0x1007c)=.625f;
    M8(0x10080)=0; MF32(0x10084)=.125f;
    tick(); CHECK(fx_sample[0].breaker==1); CHECK(fx_sample[0].charge==.625f);
    CHECK(fx_sample[0].role[0]==PADBIND_ROLE_BRAKE); CHECK(fx_sample[0].role[1]==PADBIND_ROLE_GAS);
    update(); CHECK(counter[FX_GAS]>0 && counter[FX_BRAKE]>0 && counter[FX_MOTOR]>0);
    CHECK(counter[FX_BREAKER]==1);
    clear_bindings(); bind(7,0,2); bind(8,1,3); tick(); update();
    CHECK(counter[FX_SHIFT]==2);
    CHECK(fx_sample[0].role[0]==PADBIND_ROLE_SHIFT && fx_sample[0].role[1]==PADBIND_ROLE_SHIFT);
    clear_bindings(); tick(); uint64_t before=sustained(); update();
    CHECK(sustained()==before+1); /* motor only; neither unbound trigger is active */
    CHECK(fx_sample[0].role[0]==PADBIND_ROLE_NONE && fx_sample[0].role[1]==PADBIND_ROLE_NONE);
    bind(0,0,2); bind(1,0,3); bind(7,0,3); tick(); CHECK(fx_sample[0].role[0]==PADBIND_ROLE_GAS);
    /* A record from controller 1 cannot assign the first controller's trigger. */
    clear_bindings(); bind(0,1,2); M32(M32(0xA98704)+28)=1;
    tick(); CHECK(fx_sample[0].role[1]==PADBIND_ROLE_NONE);
    /* Executable shared-model oracle: roles, travel, slip, load and off paths. */
    for (int role=PADBIND_ROLE_GAS;role<=PADBIND_ROLE_NONE;++role)
      for (int racing=0;racing<2;++racing)
        for (int pressure=0;pressure<=10;++pressure)
          for (int other=0;other<2;++other)
            for (int slip=0;slip<=10;++slip) {
                float s[2]={slip/10.f,.01f}, load=pressure/50.f;
                Trig actual=trigger_for(role,racing,pressure/10.f,other,s,load);
                Trig expected=oracle_trigger_for(role,racing,pressure/10.f,other,s,load);
                CHECK(!memcmp(&actual,&expected,sizeof actual));
            }
    /* Every independent hold and both edges require a new native tick. */
    clear_bindings(); bind(0,1,2); bind(1,0,2);
    for (unsigned hold=1;hold<=8;hold<<=1) {
        model_heavy=.6f; tick(); update(); padfx_suppress(hold,1); stopped();
        tick(); CHECK(!fx_tick[0]); padfx_suppress(hold,0); stopped();
        model_heavy=.6f; tick(); update(); CHECK(fx_tick[0]!=0);
    }
    model_heavy=.6f; tick(); padfx_disconnect(NULL); stopped(); padfx_connect(NULL); stopped();
    tick(); clock_ns+=300000001ull; padfx_poll(); stopped();
    /* Stop while sampling: never publish the old epoch even with a new clock. */
    padfx_stop(); interrupt_sample=1; tick(); CHECK(fx_tick[0]==0); stopped();
    model_heavy=.6f; tick(); context=CARBON_PAD_MENU; clock_ns+=300000001ull;
    padfx_poll(); tick(); stopped(); context=CARBON_PAD_DRIVING;
    model_heavy=.6f; tick(); update(); padfx_close(); stopped(); tick(); stopped();
    CHECK(real_opens==0 && real_writes==0 && fake_writes==0);
    CHECK(counter[FX_OPEN]==0 && counter[FX_WRITE]==0); CHECK(invalidations>0 && guest_calls>0);
    printf("PADFX %s checks=%d failures=%d motor=%llu gas=%llu brake=%llu shift=%llu opens=%d writes=%d\n",
        failures?"FAIL":"PASS",checks,failures,(unsigned long long)counter[FX_MOTOR],
        (unsigned long long)counter[FX_GAS],(unsigned long long)counter[FX_BRAKE],
        (unsigned long long)counter[FX_SHIFT],real_opens,real_writes);
    free(G); return failures!=0;
} }
