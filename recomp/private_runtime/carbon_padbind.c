#include "host.h"
#include "carbon_pad_state.h"
#include "carbon_pad_layout.h"
#include "carbon_padguest.h"

int user32_pad_native(void);

enum { PB_KEY = 1, PB_BUTTON, PB_POV, PB_AXIS_LO, PB_AXIS_HI, PB_ROT_LO, PB_ROT_HI };
typedef struct { uint32_t type, object; } PadBinding;
typedef struct { unsigned action; PadBinding primary, secondary; float low; } PadAction;

/* Only persistent driving slots. Menu bindings never enter this directory. */
static uint32_t carbon_padbind_record(unsigned action, unsigned slot) {
    return M32(0x00A98704u + 8u * action) + 12u * slot;
}

static int carbon_padbind_native(unsigned pad) {
    if (!pad) return user32_pad_native();
    int kind = pad_identity_n((int)pad, NULL, 0);
    return kind == PAD_KIND_DUALSENSE || kind == PAD_KIND_DUALSHOCK4 || kind == PAD_KIND_EDGE;
}

/* Public builds use authored positions; private recipe data stays optional. */
#if !defined(NFS_PUBLIC) && __has_include("carbon_padbind_ps3.inc") && __has_include("carbon_padbind_x360.inc")
#include "carbon_padbind_ps3.inc"
#include "carbon_padbind_x360.inc"
#else
#define CARBON_PADBIND_PORT 1
#include "carbon_padbind_port.h"
#endif
#define PADBIND_MENU_COUNT (sizeof menu / sizeof *menu)
#define PADBIND_CONSOLE_PROMPTS(pad) (carbon_pad_layout_resolve(pad).layout != CARBON_LAYOUT_PC)

/* Property calls use a copied CPU and scratch below the caller's stack. */
static unsigned carbon_padbind_property(Cpu *c, unsigned property, unsigned player) {
    Cpu read = *c;
    uint32_t out = read.esp - 16;
    M32(out) = 0xFFFFFFFFu;
    read.esp -= 32;
    read.ecx = 0x00A8AD30u;
    uint32_t args[] = {property, out, player, 0xFFFFFFFFu, 0xFFFFFFFFu};
    call_guest(&read, 0x004A0490u, 5, args);
    return M32(out);
}

static unsigned carbon_padbind_number(unsigned index, unsigned analog) {
    if (index > 4 || analog > 1) return 1;
    return index + 1 + (analog ? 0 : 5);
}

static unsigned carbon_padbind_config(Cpu *c, unsigned pad) {
#ifdef CARBON_PADBIND_PORT
    (void)c; (void)pad;
    return 1;
#else
    unsigned families = carbon_pad_layout_resolve(pad).layout == CARBON_LAYOUT_XBOX ? 6 : 5;
    unsigned index = carbon_padbind_property(c, 0x13A9, 0), analog = carbon_padbind_property(c, 0x13A7, 0);
    if (index >= families || analog > 1) return 1;
    return index + 1 + (analog ? 0 : families);
#endif
}

#ifndef CARBON_PADBIND_PORT
static PadAction carbon_padbind_action(unsigned config, unsigned action) {
    PadAction row = {action, {0,0}, {0,0}, 0};
    unsigned column = (config - 1) % 5;
    for (unsigned i = 0; i < 13; ++i)
        if (driving[column][i].action == action) row = driving[column][i];
    for (unsigned i = 0; i < sizeof shared / sizeof *shared; ++i)
        if (shared[i].action == action) row = shared[i];
    if (config > 5)
        for (unsigned i = 0; i < sizeof digital / sizeof *digital; ++i)
            if (digital[i].action == action) row = digital[i];
    return row;
}
#endif

#include "carbon_pad_layout_bindings.h"

static void carbon_padbind_apply(Cpu *c, unsigned pad) {
    unsigned config = carbon_padbind_config(c, pad);
    for (unsigned action = 0; action <= 48; ++action) {
        if ((action > 28 && action < 47) || action == 23) continue;
#ifdef CARBON_PADBIND_PORT
        if (!carbon_padbind_port_has(action)) continue;
#endif
        PadAction row = carbon_padbind_selected(pad, config, action);
        PadBinding bindings[] = {row.primary, row.secondary};
        for (unsigned s = 0; s < 2; ++s) {
            uint32_t record = carbon_padbind_record(action, 2 + 2 * pad + s);
            M32(record) = bindings[s].type;
            M32(record + 4) = bindings[s].type ? pad : 0;
            M32(record + 8) = bindings[s].object;
        }
    }
    if (diag_on) diag_event("padbind cfg=%u idx=%u analog=%u map=AD37E45A", config,
                            carbon_padbind_property(c, 0x13A9, 0),
                            carbon_padbind_property(c, 0x13A7, 0));
}

void carbon_padbind_defaults(Cpu *c, void (*original)(Cpu *)) {
    unsigned pad = arg(c, 0);
    original(c);
    if (pad >= M32(0x00A98948u) || pad >= 16) return;
    carbon_padbind_initial_config(c,pad);
    carbon_padbind_seeded(pad);
    if (carbon_padbind_console(pad)) carbon_padbind_apply(c, pad);
}

void carbon_padbind_resolve(Cpu *c, void (*original)(Cpu *)) {
    unsigned which = arg(c, 0);
    if (which <= 1 && M32(0x00A98948u)) carbon_padbind_initial_config(c,0);
    if (!M32(0x00A98948u) || !carbon_padbind_console(0) || which > 1) {
        original(c);
        return;
    }
    c->eax = which ? 0xAD37E45Au : 0x26190AC6u;
    c->esp += 12; /* thiscall, two stack arguments */
}

/* The joystick's +4 vmethod returns this already-polled cache (+0x234).
 * Match the native scalar evaluator's centre, scale and diagonal POV rules. */
static float carbon_padbind_cached(unsigned pad, PadBinding binding) {
    uint32_t device = M32(0x00A986D0u + 4u * pad);
    if (!device || device == 0xFFFFFFFCu) return 0;
    uint32_t cache = device + 0x234;
    unsigned object = binding.object, type = binding.type;
    if (type == PB_BUTTON) return (float)(int32_t)M32(cache + 0xC + 4 * object) / 128.0f;
    if (type == PB_POV) {
        int32_t pov = (int32_t)M32(cache + 0x220);
        unsigned direction = object * 9000;
        return pov == (int32_t)direction || pov == (int32_t)((direction + 4500) % 36000) ||
               pov == (int32_t)((direction + 31500) % 36000) ? 1.0f : 0.0f;
    }
    if (type >= PB_AXIS_LO && type <= PB_ROT_HI) {
        unsigned offset = type >= PB_ROT_LO ? 0x20C + 4 * object : 4 * object;
        float value = (MF32(0x009E1F7Cu) - (float)(int32_t)M32(cache + offset));
        if (type == PB_AXIS_HI || type == PB_ROT_HI) value = -value;
        return value > 0 ? value * MF32(0x009CA09Cu) : 0;
    }
    return 0;
}

/* Evaluate existing keyboard/non-native records through the native evaluator.
 * A separate CPU preserves the original function's registers and x87 stack. */
static float carbon_padbind_existing(Cpu *c, unsigned action, unsigned slot) {
    uint32_t type = M32(carbon_padbind_record(action, slot));
    if (!type) return 0;
    if (pad_count() == 2 && slot >= 2) {
        uint32_t physical = M32(0x00A986D0u + 4 * (slot / 2 - 1));
        if (type == PB_KEY || !physical || physical == 0xFFFFFFFCu) return 0;
    }
    Cpu eval = *c;
    uint32_t args[] = {action, slot};
    call_guest(&eval, 0x0067A340u, 2, args);
    return (float)eval.st[eval.top];
}

static float carbon_padbind_zone(float value, float low) {
    return fminf(1.0f, fmaxf(0.0f, (value - low) / (1.0f - low)));
}

static void carbon_padbind_driving(Cpu *c, uint32_t device) {
    unsigned count = M32(0x00A98948u), configs[16];
    if (count > 16) return;
    int any = 0;
    for (unsigned p = 0; p < count; ++p) {
        configs[p] = 0;
        if (!carbon_padguest_owns(device, p)) continue;
        configs[p] = carbon_padbind_console(p) ? carbon_padbind_config(c, p) : 0;
        any |= configs[p] != 0;
    }
    if (!any) return;
    uint32_t output = M32(device + 0x20);
    for (unsigned a = 0; a <= 48; ++a) {
        if ((a > 28 && a < 47 && a != 37) || a == 23) continue;
        int adjust = a == 37;
        for (unsigned p = 0; p < count; ++p)
            if (carbon_padguest_owns(device, p) && carbon_pad_layout_resolve(p).layout == CARBON_LAYOUT_XBOX) adjust = 1;
        for (unsigned p = 0; p < count; ++p)
            if (configs[p] && carbon_padbind_selected(p, configs[p], a).low > 0) adjust = 1;
        if (!adjust) continue;
        float value = carbon_padguest_keyboard(device) ?
            fmaxf(carbon_padbind_existing(c, a, 0), carbon_padbind_existing(c, a, 1)) : 0;
        for (unsigned p = 0; p < count; ++p) {
            if (!carbon_padguest_owns(device, p)) continue;
            float pad = fmaxf(carbon_padbind_existing(c, a, 2 + 2*p),
                              carbon_padbind_existing(c, a, 3 + 2*p));
            if (configs[p]) {
                if (a == 37) pad = carbon_padbind_cached(p, (PadBinding){PB_BUTTON,0});
                else {
                    PadAction row = carbon_padbind_selected(p, configs[p], a);
                    pad = carbon_padbind_zone(pad, row.low);
                    if (carbon_pad_layout_resolve(p).layout == CARBON_LAYOUT_XBOX)
                        pad = carbon_padbind_xbox_edge(p, a, pad, configs[p]);
                }
            }
            value = fmaxf(value, pad);
        }
        MF32(output + 4*a) = value;
    }
}

/* The native page has exactly 29 inline backups (+E0..+397). A 30th
 * overwrites its flags/controller index. Use the specified left/right fallback,
 * and show the configuration in the page's device heading (4E11CF90, written
 * natively by 005B66E0). Binding captures still belong to the native page. */
static void carbon_padbind_controls(Cpu *c, uint32_t output) {
#ifdef CARBON_PADBIND_PORT
    (void)c; (void)output;
    return; /* Native binding editor, without a retail configuration selector. */
#else
    static int held;
    uint32_t page = M32(0x00A97BACu), wrapper = M32(0x00A97A78u);
    if (!page || M32(page + 0xDC) != 3 || M32(page + 0x39C) != 0 ||
        !carbon_padbind_console(0) || !wrapper || wrapper == 0xFFFFFF28u) { held = 0; return; }
    /* 0xFFFFFF28 is a null pointer moved back by 0xD8 (no owner): test it before
     * any read through the wrapper. */
    uint32_t engine = M32(wrapper);
    if (!engine || engine == 0xFFFFFF28u) { held = 0; return; }
    uint32_t seen[128], count = 0, package = 0;
    for (uint32_t p = M32(engine + 0xE4); p; p = M32(p + 8)) {
        if (p == 0xFFFFFF28u || count == 128) { held = 0; return; }
        for (unsigned i = 0; i < count; ++i)
            if (seen[i] == p) { held = 0; return; }
        seen[count++] = p;
        if (!package && M32(p + 0x20)) package = p;
    }
    if (!package || !M32(package + 0xC) || !M32(page + 0xC) ||
        strcmp((char *)G + M32(package + 0xC),
               (char *)G + M32(page + 0xC))) { held = 0; return; }
    int direction = (MF32(output + 4*30) > 0.5f) - (MF32(output + 4*29) > 0.5f);
    if (direction && !held) {
        Cpu cycle = *c;
        uint32_t args[] = {(uint32_t)direction, 0, 0};
        carbon_padbind_cycle(&cycle, direction);
        carbon_padbind_apply(c, 0);
        uint32_t dirty[] = {0x13A3, 1, 0, 0xFFFFFFFFu, 0xFFFFFFFFu};
        cycle.ecx = 0x00A8AD30u;
        call_guest(&cycle, 0x004A04E0u, 5, dirty);
        cycle.ecx = page;
        call_guest(&cycle, 0x0058CC20u, 0, NULL);
    }
    held = direction != 0;
    /* Consume the arrows so the native page keeps its selected binding cell. */
    MF32(output + 4*29) = MF32(output + 4*30) = 0;
    Cpu label = *c;
    uint32_t buffer = label.esp - 528, formatted = label.esp - 264;
    label.esp -= 560;
    uint32_t args[] = {buffer, 256, 0x74B98590u};
    call_guest(&label, 0x00578880u, 3, args);
    snprintf((char *)G + formatted, 256, "%.*s %u  (Left/Right)",
             180, (char *)G + buffer, carbon_padbind_config(c, 0));
    uint32_t heading[] = {M32(page + 0xC), 0x4E11CF90u, formatted};
    call_guest(&label, 0x005A0910u, 3, heading);
#endif
}

void carbon_padbind_evaluate(Cpu *c, void (*original)(Cpu *)) {
    uint32_t device = c->ecx;
    int active = (M32(device + 0x24) == 0 || (pad_count() == 2 && M32(device + 0x24) == 1)) && M32(0x00AB0AD0u) && !M8(device + 0x183C);
    if (active) carbon_padbind_sync(c);
    carbon_padguest_evaluate(c, original);
    if (!active || !M32(0x00A986F4u)) return;
    if (carbon_pad_context() == CARBON_PAD_DRIVING) {
        carbon_padbind_driving(c, device);
        if (diag_on) {
            static float previous[4] = {-1,-1,-1,-1};
            const unsigned actions[] = {0,1,4,25};
            uint32_t output = M32(device + 0x20);
            int changed = 0;
            for (unsigned i = 0; i < 4; ++i) {
                float value = MF32(output + 4*actions[i]);
                if (fabsf(value - previous[i]) > .01f) changed = 1;
                previous[i] = value;
            }
            if (changed) diag_event("padbind driving gas=%.3f brake=%.3f handbrake=%.3f lookback=%.3f",
                                    previous[0], previous[1], previous[2], previous[3]);
        }
        return;
    }
    if (carbon_pad_context() != CARBON_PAD_MENU) return;
    uint32_t output = M32(device + 0x20), count = M32(0x00A98948u);
    for (unsigned i = 0; i < PADBIND_MENU_COUNT; ++i) {
        unsigned action = menu[i].action;
        float value = carbon_padguest_keyboard(device) ?
            fmaxf(carbon_padbind_existing(c, action, 0), carbon_padbind_existing(c, action, 1)) : 0;
        for (unsigned pad = 0; pad < count && pad < 16; ++pad) {
            if (!carbon_padguest_owns(device, pad)) continue;
            float primary, secondary;
            if (carbon_padbind_console(pad)) {
                PadAction row = carbon_padbind_menu(pad, action);
                primary = carbon_padbind_menu_value(pad,action,0,carbon_padbind_cached(pad, row.primary));
                secondary = carbon_padbind_menu_value(pad,action,1,carbon_padbind_cached(pad, row.secondary));
            } else {
                primary = carbon_padbind_existing(c, action, 2 + 2 * pad);
                secondary = carbon_padbind_existing(c, action, 3 + 2 * pad);
            }
            value = fmaxf(value, fmaxf(primary, secondary));
        }
        MF32(output + 4 * action) = value;
    }
    if (carbon_padguest_keyboard(device)) carbon_padbind_controls(c, output);
}

void carbon_padbind_rows(Cpu *c, void (*original)(Cpu *)) {
    unsigned kind = arg(c, 0), pad = arg(c, 1);
    original(c);
    if (kind == 3 && pad < M32(0x00A98948u) && carbon_padbind_console(pad)) c->eax = 29;
}

void carbon_padbind_text(Cpu *c, void (*original)(Cpu *)) {
    uint32_t out = arg(c, 0), size = arg(c, 1), kind = arg(c, 2), record = arg(c, 3);
    original(c);
    if (kind != 3 || !out || !size || !record || (!carbon_padbind_native(M32(record + 4)) || !PADBIND_CONSOLE_PROMPTS(M32(record + 4)))) return;
    static const char *const buttons[] = {"Cross", "Circle", "Square", "Triangle", "L1", "R1", "Create", "Options",
        "L3", "R3", "L2", "R2", "PS", "Touchpad", "Left Paddle", "Right Paddle"};
    static const char *const pov[] = {"D-Pad Up", "D-Pad Right", "D-Pad Down", "D-Pad Left"};
    static const char *const sticks[2][2][2] = {
        {{"Left Stick Left", "Left Stick Right"}, {"Left Stick Up", "Left Stick Down"}},
        {{"Right Stick Left", "Right Stick Right"}, {"Right Stick Up", "Right Stick Down"}}};
    unsigned type = M32(record), object = M32(record + 8);
    const char *text = NULL;
    if (type == PB_BUTTON && object < 16) text = buttons[object];
    else if (type == PB_POV && object < 4) text = pov[object];
    else if (type >= PB_AXIS_LO && type <= PB_ROT_HI && object < 3) {
        unsigned rot = type >= PB_ROT_LO, hi = type == PB_AXIS_HI || type == PB_ROT_HI;
        text = object == 2 ? (rot ? "R2" : "L2") : sticks[rot][object][hi];
    }
    if (text) snprintf((char *)G + out, size, "%s", text);
}
