/* F10 drives the retail density selector and cheat acceptance path. */
#include "host.h"
#include "settings.h"
#include <string.h>
extern int diag_on;
extern void diag_event(const char *, ...);
extern void portmenu_status(const char *, ...);

void carbon_devrows_traffic(Cpu *c, void (*original)(Cpu *)) {
    Setting *row = settings_find("gameplay.traffic_density");
    /* An explicit startup switch retains its exact float and original scope. */
    if (!row || row->locked || row->value < 0) { original(c); return; }
    uint32_t skip = M32(0x00A9E620u), density = M32(0x00A9E640u);
    uint8_t race = M8(0x00A9E644u);
    M32(0x00A9E620u) = 1;
    MF32(0x00A9E640u) = (float)row->value;
    M8(0x00A9E644u) = 0;
    /* 00422CC0 keeps native disabled/special-state guards and its 0..1 clamp. */
    original(c);
    M32(0x00A9E620u) = skip;
    M32(0x00A9E640u) = density;
    M8(0x00A9E644u) = race;
    static int reported = -2;
    if (diag_on && reported != row->value) {
        reported = row->value;
        diag_event("carbon devrows: traffic percent=%d native_density=%.6g restored=1", row->value, ST(0));
    }
}

static unsigned carbon_devrows_pending, carbon_devrows_clear;
static void carbon_devrows_cheat(unsigned index, int value) {
    if (value) { carbon_devrows_pending |= 1u << index; carbon_devrows_clear &= ~(1u << index); }
    else {
        carbon_devrows_pending &= ~(1u << index);
        carbon_devrows_clear |= 1u << index;
    }
}
void carbon_devrows_crew(int value) { carbon_devrows_cheat(9, value); }
void carbon_devrows_nitrous(int value) { carbon_devrows_cheat(10, value); }
void carbon_devrows_speedbreaker(int value) { carbon_devrows_cheat(11, value); }

void carbon_devrows_frame(void) {
    void carbon_audio_output_frame(void);
    carbon_audio_output_frame();
    static int started;
    if (!started) {
        started = 1;
        if (settings_get("gameplay.cheat_crew") > 0) carbon_devrows_crew(1);
        if (settings_get("gameplay.cheat_nitrous") > 0) carbon_devrows_nitrous(1);
        if (settings_get("gameplay.cheat_speedbreaker") > 0) carbon_devrows_speedbreaker(1);
    }
    if (!(carbon_devrows_pending | carbon_devrows_clear)) return;
    /* A59218 is the retail cheat manager; +10/+14 are its table/count.
     * Acceptance 004B7C00 requires the native event root at A97A7C. */
    uint32_t table = M32(0x00A59228u);
    if (!table || M32(0x00A5922Cu) != 17) return;
    static uint32_t stack;
    if (!stack) stack = galloc(65536);
    for (unsigned index = 9; index <= 11; ++index) {
        uint32_t entry = table + index * 52;
        if (M32(entry + 36) != index) continue;
        /* 004AAE60 reads +30; 004AAEA0 also deactivates by clearing only
         * this byte. +31 (persistent) and +32 (enabled) are not active state.
         * No refund/refill is needed: the native consumers resume normal rules. */
        if (carbon_devrows_clear & (1u << index)) {
            M8(entry + 48) = 0;
            carbon_devrows_clear &= ~(1u << index);
        }
        if (!(carbon_devrows_pending & (1u << index)) || !M32(0x00A97A7Cu)) continue;
        carbon_devrows_pending &= ~(1u << index);
        if (!M8(entry + 50)) continue;
        Cpu query = {0}; query.esp = stack + 65536; query.ecx = 0x00A59218u; query.cw = 0x37F;
        call_guest(&query, 0x004B7C00u, 1, &index);
        query = (Cpu){0}; query.esp = stack + 65536; query.ecx = 0x00A59218u; query.cw = 0x37F;
        uint32_t active = call_guest(&query, 0x004AAE60u, 1, &index) & 255;
        static const char *const ids[] = {"gameplay.cheat_crew", "gameplay.cheat_nitrous", "gameplay.cheat_speedbreaker"};
        Setting *row = settings_find(ids[index - 9]);
        if (row && active) row->boot_value = 1;
        if (diag_on) diag_event("carbon devrows: cheat=%u accepted=%u retail_active=%u", index, M8(entry + 48), active);
    }
}
