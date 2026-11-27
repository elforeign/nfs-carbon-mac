/* Image-specific sampling; the host transport never reads guest addresses. */
#include <math.h>
#include <stdlib.h>
#include <pthread.h>
#include <stdatomic.h>
#include "host.h"
#include "setting_bool.h"
#include "carbon_pad_state.h"
#include "carbon_padfx.h"
#include "carbon_feedback_bindings.h"

static pthread_mutex_t fx_mu = PTHREAD_MUTEX_INITIALIZER;
static uint64_t fx_generation, fx_tick[2];
static uint32_t fx_player[2];
static void *fx_controller[2];
static unsigned fx_holds;
static int fx_closed;
static _Atomic int fx_triggers = -1, fx_road = -1;
static CarbonPadfxFrame fx_sample[2];
static int fx_fresh(unsigned slot, uint64_t now) {
    return slot < 2 && !fx_holds && !fx_closed && fx_tick[slot] &&
        now >= fx_tick[slot] && now - fx_tick[slot] < 300000000ull;
}
int carbon_padfx_lock(unsigned slot, uint64_t token, int active) {
    pthread_mutex_lock(&fx_mu);
    if (token != fx_generation || (active && !fx_fresh(slot, host_ticks()))) {
        pthread_mutex_unlock(&fx_mu); return 0;
    }
    return 1;
}
void carbon_padfx_unlock(void) { pthread_mutex_unlock(&fx_mu); }
static int fx_switch(const char *name) {
    int value = setting_bool_parse(getenv(name)); return value < 0 ? 1 : value;
}
static int fx_triggers_on(void) {
    /* The virtual device evaluates desired recipes with physical outputs Off.
     * Live native toggles still apply to the virtual device after selection. */
    if (fx_triggers < 0) fx_triggers = carbon_padfx_fake() ? 1 : fx_switch("NFS_PAD_TRIGGERS");
    return fx_triggers;
}
int padfx_wanted(void) { return fx_triggers_on() || diag_on; }
int padfx_road_wanted(void) {
    if (fx_road < 0) fx_road = carbon_padfx_fake() ? 1 : fx_switch("NFS_PAD_ROAD");
    return fx_triggers_on() && fx_road;
}

/* Carbon's action directory holds pointers, each to 12-byte source records.
 * Slots 2+2*port / 3+2*port are that controller's effective bindings.
 * Gas/brake precede shift, then other/unbound, as in the shared recipe model. */
static int carbon_padfx_role(unsigned port, int right) {
    if (M32(0x00A98948u) <= port) return PADBIND_ROLE_NONE;
    int best = PADBIND_ROLE_NONE;
    for (unsigned action = 0; action <= 28; ++action) {
        uint32_t row = M32(0x00A98704u + 8u * action);
        if (!row) continue;
        for (unsigned slot = 2 + 2 * port; slot < 4 + 2 * port; ++slot) {
            uint32_t r = row + 12u * slot, type = M32(r), device = M32(r + 4), object = M32(r + 8);
            if (device != port || !((type == (right ? 7u : 5u) && object == 2) ||
                            (type == 2 && object == (right ? 11u : 10u)))) continue;
            int role = action == 0 ? PADBIND_ROLE_GAS : action == 1 ? PADBIND_ROLE_BRAKE :
                action == 7 || action == 8 ? PADBIND_ROLE_SHIFT : PADBIND_ROLE_OTHER;
            if (role < best) best = role;
        }
    }
    return best;
}

/* The address-free recipes are kept equal to padfx.m by an executable oracle. */
static float q20(float v) { return roundf(fminf(fmaxf(v, 0), 1) * 20) / 20; }
static Trig trig(int mode, float a, float b, float c, float d) {
    return (Trig){.mode=mode, .a=q20(a), .b=q20(b), .c=q20(c), .d=q20(d)};
}
static Trig vibration(float level, float freq, float floor) {
    return trig(T_VIBRATION, 0, floor + (1 - floor) * level, freq, 0);
}
static Trig pedal_spring(int role, float load) {
    Trig t = {.mode=T_POSITIONAL};
    for (int i = 0; i < 10; ++i) {
        float travel = (float)i / 9;
        float strength = role == PADBIND_ROLE_GAS ? 0.10f + 0.15f * travel :
            (travel <= 0.60f ? 0.15f + 0.25f * travel : 0.30f + 1.25f * (travel - 0.60f));
        t.strength[i] = q20(strength + load * (role == PADBIND_ROLE_GAS ? 1 : 0.5f));
    }
    return t;
}
static Trig trigger_for(int role, int racing, float self, float other_pedal, const float slip[2], float load) {
    if (!racing) return trig(T_OFF, 0, 0, 0, 0);
    float level = fmaxf(slip[0], slip[1]);
    switch (role) {
    case PADBIND_ROLE_GAS:
        if (self > 0.1f && other_pedal < 0.1f && level >= 0.05f) return vibration(level, 0.2f, 0.3f);
        return pedal_spring(role, load);
    case PADBIND_ROLE_BRAKE:
        if (self > 0.1f && other_pedal < 0.1f && level >= 0.05f) return vibration(level, 0.3f, 0.35f);
        return pedal_spring(role, load);
    case PADBIND_ROLE_SHIFT: return trig(T_WEAPON, 0.25f, 0.5f, 0.6f, 0);
    default: return trig(T_OFF, 0, 0, 0, 0);
    }
}

void padfx_game_tick(Cpu *c, uint32_t player) {
    (void)c;
    int slot = carbon_feedback_player_slot(player);
    if (slot < 0) return;
    pthread_mutex_lock(&fx_mu);
    uint64_t token = fx_generation;
    int held = fx_holds || fx_closed;
    pthread_mutex_unlock(&fx_mu);
    if (held || !player || carbon_pad_context() != CARBON_PAD_DRIVING) return;
    CarbonPadfxFrame frame = {.breaker = M8(player + 0x78) != 0, .charge = MF32(player + 0x7C)};
    frame.role[0] = carbon_padfx_role((unsigned)slot, 0); frame.role[1] = carbon_padfx_role((unsigned)slot, 1);
    uint64_t now = host_ticks();
    pthread_mutex_lock(&fx_mu);
    if (token == fx_generation && !fx_holds && !fx_closed) {
        if (frame.breaker != fx_sample[slot].breaker && carbon_padfx_fake()) carbon_padfx_count(FX_BREAKER);
        fx_sample[slot] = frame; fx_tick[slot] = now; fx_player[slot] = player;
    }
    pthread_mutex_unlock(&fx_mu);
}
void carbon_padfx_update(unsigned slot, void *gc, int dualsense, float lt, float rt) {
    if (slot >= 2) return;
    pthread_mutex_lock(&fx_mu);
    uint64_t token = fx_generation;
    int racing = fx_fresh(slot, host_ticks()) && gc == fx_controller[slot];
    CarbonPadfxFrame frame = fx_sample[slot];
    int enabled = fx_triggers_on();
    pthread_mutex_unlock(&fx_mu);
    if (!racing) { padfx_poll(); return; }
    float slip[2], hz[2], speed, surface, p[2] = {lt, rt}, pedal[2] = {0,0}; int nos;
    carbon_feedback_trigger_state(slot, slip, hz, &nos);
    carbon_feedback_road_state(slot, &speed, &surface);
    for (int i = 0; i < 2; ++i) {
        if (frame.role[i] == PADBIND_ROLE_GAS) pedal[0] = fmaxf(pedal[0], p[i]);
        if (frame.role[i] == PADBIND_ROLE_BRAKE) pedal[1] = fmaxf(pedal[1], p[i]);
    }
    float load = padfx_road_wanted() ? 0.1f * fminf(fmaxf(speed, 0) / 60.0f, 1) +
        0.1f * fminf(fmaxf(surface, 0), 1) : 0;
    for (int i = 0; i < 2; ++i)
        frame.trigger[i] = trigger_for(frame.role[i], enabled && dualsense, p[i],
            frame.role[i] == PADBIND_ROLE_GAS ? pedal[1] : pedal[0], slip, load);
    carbon_padfx_output(slot, gc, frame, token);
}
void padfx_update(void *gc, int dualsense, float lt, float rt) {
    pthread_mutex_lock(&fx_mu);
    unsigned slot = gc && gc == fx_controller[1] ? 1 : 0;
    pthread_mutex_unlock(&fx_mu);
    carbon_padfx_update(slot, gc, dualsense, lt, rt);
}
void padfx_stop(void) {
    pthread_mutex_lock(&fx_mu);
    uint64_t token = ++fx_generation;
    memset(fx_tick, 0, sizeof fx_tick);
    memset(fx_player, 0, sizeof fx_player);
    pthread_mutex_unlock(&fx_mu);
    for (unsigned slot = 0; slot < 2; ++slot) {
        feedback_invalidate_slot(slot); rumble_stop_slot(slot);
    }
    carbon_padfx_release(token);
}
void padfx_suppress(unsigned reason, int on) {
    pthread_mutex_lock(&fx_mu);
    unsigned old = fx_holds;
    fx_holds = on ? fx_holds | reason : fx_holds & ~reason;
    int changed = old != fx_holds;
    pthread_mutex_unlock(&fx_mu);
    if (changed) padfx_stop();
}
void padfx_poll(void) {
    pthread_mutex_lock(&fx_mu);
    uint64_t now = host_ticks();
    int stale = 0;
    for (unsigned slot = 0; slot < 2; ++slot)
        if (fx_tick[slot] && (!fx_fresh(slot, now) ||
            carbon_feedback_player_slot(fx_player[slot]) != (int)slot)) stale = 1;
    pthread_mutex_unlock(&fx_mu);
    if (stale) padfx_stop();
    carbon_padfx_log(0);
}
void padfx_close(void) {
    pthread_mutex_lock(&fx_mu); fx_closed = 1; pthread_mutex_unlock(&fx_mu);
    padfx_stop(); carbon_padfx_log(1);
}
/* A polling fallback has no device identity: stop both, but do not mark the
 * still-connected peer detached. player_update retires the known lost slot. */
void padfx_disconnect(void *gc) { if (gc) carbon_padfx_attach(gc, 0); padfx_stop(); }
void padfx_connect(void *gc) { carbon_padfx_attach(gc, 1); }
void padfx_set_triggers(int on) {
    pthread_mutex_lock(&fx_mu); fx_triggers = on != 0; pthread_mutex_unlock(&fx_mu);
    padfx_stop();
}
void padfx_set_road(int on) { fx_road = on != 0; padfx_stop(); }
/* These outputs require separate image-specific look bindings. */
void padfx_set_light(int on) { (void)on; }
void padfx_set_players(int on) { (void)on; }
void padfx_player_update(int slot, void *gc) {
    if (slot < 0 || slot > 1) return;
    pthread_mutex_lock(&fx_mu);
    void *previous = fx_controller[slot];
    int changed = fx_controller[slot] != gc;
    if (changed) {
        fx_controller[slot] = gc;
        if (gc && fx_controller[1 - slot] == gc) fx_controller[1 - slot] = NULL;
    }
    pthread_mutex_unlock(&fx_mu);
    if (changed && previous && !gc) carbon_padfx_attach(previous, 0);
    if (changed) padfx_stop();
}
