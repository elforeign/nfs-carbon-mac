/* Explicit fixed-step override. Without the override every hook delegates unchanged. */
#include "host.h"
#include <stdlib.h>
#include <math.h>

int user32_display_hz(void);
uint32_t call_guest(Cpu *, uint32_t, int, const uint32_t *);
static int carbon_rate_initialized, carbon_rate_enabled, carbon_rate_hz = 60;

int carbon_sim_hz(void) {
    if (!carbon_rate_initialized) {
        const char *e = getenv("NFS_SIMHZ");
        carbon_rate_enabled = e != NULL;
        int hz = e ? atoi(e) : 60;
        if (hz < 30 || hz > 480) hz = user32_display_hz();
        if (hz < 30) hz = 60;
        if (hz > 480) hz = 480;
        carbon_rate_hz = hz;
        carbon_rate_initialized = 1;
    }
    return carbon_rate_hz;
}

int carbon_simrate_enabled(void) {
    (void)carbon_sim_hz();
    return carbon_rate_enabled;
}

static float carbon_simrate_step(void) {
    float step = 1.0f / (float)carbon_sim_hz();
    MF32(0x009EBB6Cu) = step;
    return step;
}

void carbon_simrate_construct(Cpu *c, void (*original)(Cpu *)) {
    if (!carbon_simrate_enabled()) { original(c); return; }
    uint32_t self = c->ecx;
    float step = carbon_simrate_step();
    original(c);
    MF32(self + 0x14u) = step;
}

/* Rate and delay are constructor arguments, before its native min(rate,1)
 * and negated delay accumulator. Sub-rate delays must not be scaled twice. */
void carbon_simrate_task(Cpu *c, void (*original)(Cpu *)) {
    if (carbon_simrate_enabled() && carbon_sim_hz() != 60) {
        float k = 60.0f / (float)carbon_sim_hz();
        float rate = MF32(c->esp + 8), delay = MF32(c->esp + 16);
        if (rate > 0.0f && rate < 1.0f) MF32(c->esp + 8) = rate * k;
        else if (delay > 0.0f) MF32(c->esp + 16) = delay / k;
    }
    original(c);
}

/* 00769A20 waits until +41C exceeds 30 in state 3. Native code increments
 * an integer, so carry the fractional 60/hz count without skipping its task
 * callbacks. A new activity or native counter reset discards the remainder. */
void carbon_simrate_intro(Cpu *c, void (*original)(Cpu *)) {
    if (!carbon_simrate_enabled() || carbon_sim_hz() == 60) { original(c); return; }
    static uint32_t owner, written, remainder;
    uint32_t self = c->ecx, state = M32(self + 0x31Cu), count = M32(self + 0x41Cu);
    original(c);
    if (state != 3 || M32(self + 0x41Cu) != count + 1) return;
    if (self != owner || count != written) { owner = self; remainder = 0; }
    remainder += 60;
    uint32_t whole = remainder / (uint32_t)carbon_sim_hz();
    remainder -= whole * (uint32_t)carbon_sim_hz();
    M32(self + 0x41Cu) = written = count + whole;
}

/* Native 00761150 counts elapsed fixed steps, carries the remainder and posts
 * one Sim::Message. Its reciprocal 009EC0A8 and cap 8 are fixed at 60 Hz;
 * keep that original path intact and use the selected reciprocal/cap here. */
void carbon_simrate_batch(Cpu *c, void (*original)(Cpu *)) {
    if (!carbon_simrate_enabled()) { original(c); return; }
    float step = carbon_simrate_step();
    int posted = 0;
    if (M32(0x00B4CFE0u)) {
        double elapsed = (double)MF32(0x00B4D7ECu) + MF32(c->esp + 4);
        if (elapsed >= step) {
            /* Divide by the actual float step so an exact step is one tick. */
            double count = floor(elapsed / step);
            uint32_t cap = 8u * (uint32_t)carbon_sim_hz() / 60u;
            uint32_t n = count > cap ? cap : (uint32_t)count;
            MF32(0x00B4D7ECu) = count > cap ? 0.0f : (float)fmax(0, elapsed - n * (double)step);
            uint32_t id = M32(0x00B4D7E8u), alloc[] = {0x1c, 1};
            uint32_t message = call_guest(c, 0x00561590u, 2, alloc);
            if (message) {
                uint32_t args[] = {0, n, 0, 0, id};
                c->ecx = message;
                call_guest(c, 0x00672C70u, 5, args);
            }
            posted = 1;
        } else MF32(0x00B4D7ECu) = (float)elapsed;
    }
    c->eax = (c->eax & 0xFFFFFF00u) | (uint32_t)posted;
    c->esp += 4;
}

/* Same native callbacks, order and mode gate as 0076ACE0. The rate callback
 * consumes unscaled step seconds; its result scales dt for slow motion. */
void carbon_simrate_advance(Cpu *c, void (*original)(Cpu *)) {
    if (!carbon_simrate_enabled()) { original(c); return; }
    float step = carbon_simrate_step();
    uint32_t self = c->ecx;
    call_guest(c, 0x0076AC90u, 0, NULL);
    uint32_t mode = M32(self + 0x28u);
    if (!mode) {
        MF32(self + 0x1Cu) = 1.0f;
        M32(self + 0x24u) = 0;
    } else {
        uint32_t key = 0x0075C250u;
        c->ecx = M32(mode + 4);
        uint32_t callback = call_guest(c, 0x0060CB50u, 1, &key);
        if (callback) {
            uint32_t args[2];
            memcpy(&args[0], &step, sizeof step);
            args[1] = M32(self + 0x1Cu);
            c->ecx = callback;
            call_guest(c, M32(M32(callback) + 4), 2, args);
            MF32(self + 0x1Cu) = (float)ST(0); x87_pop(c);
        }
        key = 0x0066B500u;
        c->ecx = M32(M32(self + 0x28u) + 4);
        callback = call_guest(c, 0x0060CB50u, 1, &key);
        if (callback) {
            uint32_t arg = M32(self + 0x24u);
            c->ecx = callback;
            M32(self + 0x24u) = call_guest(c, M32(M32(callback) + 4), 1, &arg);
            c->ecx = callback;
            arg = call_guest(c, M32(M32(callback) + 8), 0, NULL);
            c->ecx = self;
            call_guest(c, 0x00764BC0u, 1, &arg);
        }
    }
    double dt = x87_round(c, (double)MF32(self + 0x1Cu) * step);
    MF32(self + 0x14u) = (float)dt;
    x87_push(c, M32(self + 0x24u) == 3 && dt > MF32(0x009EBB68u) ? dt : (double)MF32(0x009C248Cu));
    c->esp += 4;
}
