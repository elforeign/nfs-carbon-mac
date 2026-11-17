/* Presentation slots follow the explicit fixed step, or the native limiter. */
#include "host.h"
#include <stdlib.h>
#include <mach/mach_time.h>
#include <mach/kern_return.h>
#include "looppace.h"

int carbon_simrate_enabled(void), carbon_sim_hz(void);

/* Interrupted waits retain the same absolute deadline. */
static void pacewait_until(uint64_t deadline) {
    while (mach_wait_until(deadline) == KERN_ABORTED) {}
}

/* Carbon has no shared post chain, but diagnostic shots use its held-variant
 * protocol. Keep parser state entirely on the host; no guest clock when Off. */
static char carbon_look_vars[16][16],carbon_look_base[512];
static int carbon_look_count=-1,carbon_look_state,carbon_look_index;
static int carbon_look_init(void) {
    if(carbon_look_count<0) {
        carbon_look_count=0;
        const char *p=diag_on?getenv("BOOT_DIAG_LOOK_AB"):NULL;
        while(p && *p && carbon_look_count<16) {
            size_t n=strcspn(p,",");
            if(n && n<sizeof carbon_look_vars[0]) {
                memcpy(carbon_look_vars[carbon_look_count],p,n);
                carbon_look_vars[carbon_look_count++][n]=0;
            }
            p+=n+(p[n]==',');
        }
    }
    return carbon_look_count>0;
}
int postfx_look_variant(const char *v) {
    return diag_on && carbon_look_state==2 && !strcmp(carbon_look_vars[carbon_look_index],v);
}
int postfx_look_listed(const char *v) {
    if(!diag_on || !carbon_look_init())return 0;
    for(int i=0;i<carbon_look_count;i++)if(!strcmp(carbon_look_vars[i],v))return 1;
    return 0;
}
int postfx_ab_shot(char *path,size_t n) {
    if(!diag_on || !carbon_look_init())return 0;
    if(carbon_look_state==2) {
        snprintf(path,n,"%.*s_%s.png",(int)(strlen(carbon_look_base)-4),carbon_look_base,carbon_look_vars[carbon_look_index]);
        carbon_look_state=3;return 1;
    }
    if(carbon_look_state==0 && strlen(path)>4) {
        snprintf(carbon_look_base,sizeof carbon_look_base,"%s",path);carbon_look_state=1;
    }
    return 0;
}
int postfx_ab_hold(void) {
    if(!diag_on)return 0;
    if(carbon_look_state==1) {carbon_look_index=0;carbon_look_state=2;}
    else if(carbon_look_state==3) {carbon_look_state=++carbon_look_index<carbon_look_count?2:0;return 1;}
    return carbon_look_state==2;
}

int portmenu_hold(void);
void portmenu_pass(Cpu *);
void gil_release(void), gil_acquire(void);
double render_loop_limit_ms(void);

static int carbon_initial_limit;
int *carbon_frame_limit_choice = &carbon_initial_limit;
static uint64_t carbon_deadline, carbon_period;
static uint32_t carbon_previous_ticks;
static uint64_t carbon_frames, carbon_one, carbon_zero, carbon_multi;

void carbon_frame_limit_apply(int value) {
    *carbon_frame_limit_choice = value;
    carbon_deadline = carbon_period = 0;
}

void carbon_picture_wait(void) {
    double ms = render_loop_limit_ms();
    int simrate = carbon_simrate_enabled();
    uint32_t ran = 0;
    if (simrate || diag_on) {
        uint32_t ticks = M32(0x00B4CFD4u);
        ran = ticks >= carbon_previous_ticks ? ticks - carbon_previous_ticks : 0;
        carbon_previous_ticks = ticks;
        if (diag_on && M32(0x00A99BBCu) == 6 && !portmenu_hold()) {
            ++carbon_frames;
            carbon_one += ran == 1; carbon_zero += ran == 0; carbon_multi += ran > 1;
        }
    }
    if (!simrate && !(ms > 0)) { carbon_deadline = carbon_period = 0; return; }
    uint64_t now = host_ticks(), period = (uint64_t)(ms * 1000000.0 + 0.5);
    if (simrate) {
        float step = 1.0f / (float)carbon_sim_hz();
        float frac = MF32(0x00B4D7ECu) / step;
        carbon_deadline = looppace_deadline(carbon_deadline, now, step, frac, ms / 1000.0, ran, 0);
    } else {
        if (!carbon_deadline || period != carbon_period || now > carbon_deadline + period * 4)
            carbon_deadline = now;
        carbon_period = period;
        carbon_deadline += period;
    }
    if (carbon_deadline <= now) return;
    static mach_timebase_info_data_t timebase;
    if (!timebase.denom) mach_timebase_info(&timebase);
    uint64_t deadline = carbon_deadline / timebase.numer * timebase.denom +
        carbon_deadline % timebase.numer * timebase.denom / timebase.numer;
    gil_release();
    pacewait_until(deadline);
    gil_acquire();
}

/* 006AB822 pops the UNFORCED whole-frame result into ECX. Keep the original
 * x87 rounding/carry, 4000 Hz timer, loop count, registers and stack behavior. */
void carbon_advance_real_time(Cpu *c, void (*original)(Cpu *)) {
    original(c);
    if (c->ecx == 0) {
        M32(0x00A62EE8u) -= 1;
        M32(0x00A62EECu) = M32(0x00A62EE8u);
        M32(0x00A62EF0u) = 0;
    }
}

void carbon_prepare_real_timestep(Cpu *c, void (*original)(Cpu *)) {
    portmenu_pass(c);
    int held = portmenu_hold();
    if (diag_on) { int postfx_ab_hold(void); held |= postfx_ab_hold(); }
    /* The caller already updated its ticker. Consume time through the native
     * preparer even while held, then suppress its output (including debug dt). */
    original(c);
    if (held) MF32(0x00A99A5Cu) = 0;
    if (diag_on) {
        void diag_warp_pass(Cpu *);
        diag_warp_pass(c);
        static uint64_t sampled;
        uint64_t now = host_ticks();
        if (!sampled || now - sampled >= 1000000000ull) {
            sampled = now;
            fprintf(stderr, "boot: picture-clock: wall=%.9f real=%u elapsed=%u sim=%.9f held=%d flow=%u sound=%u frames=%llu one=%llu zero=%llu multi=%llu\n",
                now / 1e9, M32(0x00A62EE8u), M32(0x00A62EF0u),
                (double)MF32(0x00B4CFD8u), held, M32(0x00A99BBCu), M32(0x00A8BAE4u),
                (unsigned long long)carbon_frames, (unsigned long long)carbon_one,
                (unsigned long long)carbon_zero, (unsigned long long)carbon_multi);
        }
    }
}
