#include "host.h"

/* Restore Game Mode value 2, then enter the retained two-player state graph.
 * 00854300 states 8/9 release P2; 00848590 opens the native join screen;
 * 0083CAF0 assigns its controller with 00572C90; state 13 starts split play.
 * Keep allocation, car lists, ready/cancel and race creation in that graph. */
static uint32_t carbon_qrsplit_call(Cpu *c, uint32_t fn, uint32_t self,
                                    unsigned count, const uint32_t *args) {
    Cpu q = *c;
    q.ecx = self;
    q.esp -= 256;
    return call_guest(&q, fn, count, args);
}

void carbon_qrsplit_memory(Cpu *c, void (*original)(Cpu *)) {
    if (pad_count() != 2 ||
        (carbon_qrsplit_call(c, 0x006999C0u, 0, 0, NULL) & 255) != 1) {
        original(c);
        return;
    }
    /* The retained split initializer selects a 1 KiB placeholder. Borrow
     * the PC car budget for its native allocation, including all reductions. */
    uint32_t saved = M32(0x00A62C4Cu);
    M32(0x00A62C4Cu) = M32(0x00A62C48u);
    original(c);
    M32(0x00A62C4Cu) = saved;
}

static uint32_t carbon_qrsplit_get(Cpu *c, uint32_t property, uint32_t owner) {
    Cpu q = *c;
    q.esp -= 256;
    uint32_t out = q.esp + 128;
    M32(out) = 0;
    q.ecx = 0x00A8AD30u;
    uint32_t args[] = {property, out, owner, ~0u, ~0u};
    call_guest(&q, 0x004A0490u, 5, args);
    return M32(out);
}

static void carbon_qrsplit_set(Cpu *c, uint32_t property, uint32_t value,
                                uint32_t owner) {
    uint32_t args[] = {property, value, owner, ~0u, ~0u};
    carbon_qrsplit_call(c, 0x004A04E0u, 0x00A8AD30u, 5, args);
}

static void carbon_qrsplit_port(Cpu *c, unsigned player, unsigned port) {
    uint32_t args[] = {player, port};
    carbon_qrsplit_call(c, 0x00572C90u, M32(0x00A97A7Cu), 2, args);
}

static void carbon_qrsplit_single(Cpu *c) {
    carbon_qrsplit_set(c, 0xBC7, 0, ~0u);
    carbon_qrsplit_port(c, 0, 0);
    carbon_qrsplit_port(c, 1, ~0u);
    M32(M32(0x00A97A7Cu) + 0xC4) = 0;
}

void carbon_qrsplit_label(Cpu *c, void (*original)(Cpu *)) {
    uint32_t row = c->ecx, options = M32(0x00BBAA54u);
    if (!options) { original(c); return; }
    uint32_t owner = M32(options + 0x164);
    unsigned value = carbon_qrsplit_get(c, 0x13E4, owner);
    if (pad_count() != 2 || value != 2) {
        /* A saved per-event split choice also survives turning Controllers
         * back to 1. Normalize it before the PC row formats its value. */
        if (pad_count() != 2 && value == 2) carbon_qrsplit_set(c, 0x13E4, 0, owner);
        original(c);
        return;
    }
    /* Reuse the authored localized Split Screen label (00853AD9). */
    uint32_t args[] = {M32(row + 0x1C), 0x37CE1D36u};
    carbon_qrsplit_call(c, 0x00583A90u, 0, 2, args);
    c->esp += 4;
}

void carbon_qrsplit_choice(Cpu *c, void (*original)(Cpu *)) {
    uint32_t row = c->ecx, options = M32(0x00BBAA54u), event = arg(c, 1);
    if (pad_count() != 2 || !options || M32(row + 0x74) != 0x13E4u || !M8(row + 0x64) ||
        (event != 0x9120409Eu && event != 0xB5971BF1u)) {
        original(c);
        return;
    }
    uint32_t owner = M32(options + 0x164);
    unsigned value = carbon_qrsplit_get(c, 0x13E4, owner);
    value = (value + (event == 0x9120409Eu ? 2 : 1)) % 3;
    carbon_qrsplit_set(c, 0x13E4, value, owner);
    carbon_qrsplit_call(c, 0x0084B6F0u, options, 0, NULL);
    carbon_qrsplit_call(c, M32(M32(row) + 0x38), row, 1, &event);
    carbon_qrsplit_call(c, M32(M32(row) + 4), row, 0, NULL);
    c->esp += 12;
}

void carbon_qrsplit_accept(Cpu *c, void (*original)(Cpu *)) {
    uint32_t qr = c->ecx;
    if (pad_count() != 2 || M32(qr + 4) != 2 ||
        carbon_qrsplit_get(c, 0x13E4, M32(qr + 0xD0)) != 2) {
        original(c);
        return;
    }
    /* Same native car-list constructor as 00863000, with the retained split
     * return state 8 instead of the PC-only single-player return state 0. */
    uint32_t size = 0xE8;
    uint32_t child = carbon_qrsplit_call(c, 0x006A1560u, 0, 1, &size);
    if (!child) { carbon_qrsplit_single(c); c->esp += 4; return; }
    carbon_qrsplit_single(c);
    carbon_qrsplit_set(c, 0xBC7, 1, ~0u);
    uint32_t args[] = {qr, 1, M32(qr + 0xD0)};
    carbon_qrsplit_call(c, 0x00862090u, child, 3, args);
    uint32_t attach[] = {child, 8, 1};
    carbon_qrsplit_call(c, 0x005A52B0u, qr, 3, attach);
    if (diag_on) diag_event("qrsplit: entry qr=%08X child=%08X state=8", qr, child);
    c->esp += 4;
}

void carbon_qrsplit_transition(Cpu *c, void (*original)(Cpu *)) {
    uint32_t qr = c->ecx, state = M32(qr + 4);
    if (pad_count() == 2 && state == 13) {
        uint32_t player = 0;
        unsigned p0 = carbon_qrsplit_call(c, 0x00572C70u, M32(0x00A97A7Cu), 1, &player) & 255;
        player = 1;
        unsigned p1 = carbon_qrsplit_call(c, 0x00572C70u, M32(0x00A97A7Cu), 1, &player) & 255;
        if (p0 != 0 || p1 != 1) {
            carbon_qrsplit_single(c);
            uint32_t args[] = {0x009CFDCCu, 2};
            carbon_qrsplit_call(c, 0x00593750u, qr, 2, args);
            c->esp += 4;
            return;
        }
    }
    original(c);
    if (pad_count() != 2) return;
    if (state == 2) carbon_qrsplit_single(c);
    if (diag_on) diag_event("qrsplit: transition state=%u active=%u", state,
                            M32(M32(0x00A97A7Cu) + 0xC4));
}

void carbon_qrsplit_destroy(Cpu *c, void (*original)(Cpu *)) {
    uint32_t state = M32(c->ecx + 4);
    /* The native start states outlive their FE manager while loading. */
    if (pad_count() == 2 && state != 13 && state != 14 && M32(0x00A99BBCu) == 3)
        carbon_qrsplit_single(c);
    original(c);
}
