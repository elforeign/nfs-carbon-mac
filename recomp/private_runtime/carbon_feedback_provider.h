#include "game_image.h"
/* Slots 38/3C/40 intentionally have no assigned event meaning. */
static int carbon_feedback_slot38(Cpu *c) { COUNT(0x38); RET(0, 1); }
static int carbon_feedback_slot3c(Cpu *c) { COUNT(0x3C); RET(0, 1); }
static int carbon_feedback_slot40(Cpu *c) { COUNT(0x40); RET(0, 1); }
static const struct { unsigned slot, arguments; HostFn function; const char *name; } carbon_feedback_slots[] = {
    {0x04,0,fb_stop,"Stop"}, {0x08,0,fb_resume,"Resume"}, {0x0C,0,fb_reset,"Reset"},
    {0x10,0,fb_begin_frame,"BeginFrame"}, {0x14,0,fb_end,"End"},
    {0x18,3,fb_speed,"Speed"}, {0x1C,3,fb_skid,"Skid"}, {0x20,3,fb_slip,"Slip"},
    {0x24,3,fb_engine_rpm,"EngineRPM"}, {0x28,1,fb_shift_kick,"ShiftKick"},
    {0x2C,2,fb_nos,"Nos"}, {0x30,1,fb_engine_damage,"EngineDamage"}, {0x34,1,fb_gear_change,"GearChange"},
    {0x38,1,carbon_feedback_slot38,"Slot38"}, {0x3C,1,carbon_feedback_slot3c,"Slot3C"},
    {0x40,1,carbon_feedback_slot40,"Slot40"}, {0x44,2,fb_collision,"Collision"}
};
void feedback_setup(void) {
    static int installed;
    static const uint32_t native[18] = {
        0x006807E0u,0x00679FA0u,0x0067A010u,0x0067A020u,0x0067A030u,0x0067A040u,
        0x0067A050u,0x0067A060u,0x0067A070u,0x0067A080u,0x0067A090u,0x0067A0A0u,
        0x0067A0B0u,0x0067A0C0u,0x0067A0E0u,0x006807C0u,0x006807D0u,0x0067A0D0u
    };
    /* Require the complete runtime executable digest, build identity and loaded
     * vtable before allocating callbacks or writing any slot. */
    if (installed || !G || !PRIVATE_CARBON_SKIPFE || !carbon_feedback_image_ok) return;
    for (unsigned i = 0; i < 18; ++i) if (M32(FEEDBACK_VTABLE + 4 * i) != native[i]) return;
    for (unsigned i = 0; i < sizeof carbon_feedback_slots / sizeof *carbon_feedback_slots; ++i) {
        M32(FEEDBACK_VTABLE + carbon_feedback_slots[i].slot) =
            host_fn(carbon_feedback_slots[i].function, carbon_feedback_slots[i].name);
    }
    installed = 1;
    if (diag_on) diag_event("feedback: installed 17 slots, collision +44; destructor retained");
}
static _Atomic int carbon_feedback_active_input = -1;
void carbon_feedback_input(int pad) { carbon_feedback_active_input = pad == 1; }
void carbon_feedback_trigger_state(unsigned slot, float slip[2], float hz[2], int *nos) {
    Feedback *f = slot < 2 ? &feedback_states[slot] : &unowned_feedback;
    if (slot >= 2 || !f->effects_valid) {
        memset(slip, 0, sizeof f->slip_pub); memset(hz, 0, sizeof f->hz_pub); *nos = 0; return;
    }
    memcpy(slip, f->slip_pub, sizeof f->slip_pub); memcpy(hz, f->hz_pub, sizeof f->hz_pub); *nos = f->nos_on;
}
void carbon_feedback_road_state(unsigned slot, float *speed, float *surface) {
    Feedback *f = slot < 2 ? &feedback_states[slot] : &unowned_feedback;
    *speed = slot < 2 && f->effects_valid ? f->road_speed_pub : 0;
    *surface = slot < 2 && f->effects_valid ? f->road_surface_pub : 0;
}
void carbon_feedback_tick(Cpu *c, void (*original)(Cpu *)) {
    if (!carbon_feedback_image_ok) { original(c); return; }
    ++carbon_feedback_ticks;
    uint32_t self = c->ecx;
    int slot = carbon_feedback_player_slot(self);
    /* Identity is cached by the input provider; no extra input poll. A wheel or
     * keyboard selection retains the original native wheel dispatch. */
    int gamepad = slot >= 0 && pad_identity_n(slot, NULL, 0) != PAD_KIND_NONE &&
        (slot != 0 || carbon_feedback_active_input != 0);
    uint32_t wheel = self ? M32(self + 0x54) : 0;
    if (gamepad && self) M32(self + 0x54) = 0;
    original(c);
    if (gamepad && self) M32(self + 0x54) = wheel;
    if (gamepad && self && padfx_wanted()) padfx_game_tick(c, self);
    /* Advance even with the physical transport disabled or not yet selected. */
    float heavy, light;
    if (slot >= 0) feedback_levels_slot((unsigned)slot, &heavy, &light);
    else feedback_poll_pause();
}
