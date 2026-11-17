#include "host.h"

static uint32_t carbon_fix_save_size(uint32_t handler) {
    switch (M32(handler)) {
        case 0x009D22B8u: return 0x23FA4u;
        case 0x009D22D0u: return 0x10000u;
        case 0x009D22F8u: return 0x12C4u;
        default: return 0;
    }
}

static void carbon_fix_save_records(uint32_t self) {
    uint32_t header = M32(self + 0x7C), base = M32(self + 0x84);
    if (!header || !base) return;
    if (M32(0x00A9E684u) &&
        (M32(header + 8) != 6 || M32(header + 12) != M32(self + 0x1C))) return;

    uint32_t head = M32(0x00A97D40u), node = head;
    if (!head) return;
    /* Validate the complete list before changing any record. Unknown handlers
     * and malformed/cyclic lists retain the native admission policy. */
    unsigned count = 0;
    while (node != 0x00A97D40u) {
        if (node < 4 || ++count > 1024 || !carbon_fix_save_size(node - 4)) return;
        node = M32(node);
    }
    uint32_t length = M32(header + 4);
    if (length < 0x30 || base > UINT32_MAX - length) return;
    uint32_t end = base + length, record = base + 0x30;
    while (record < end) {
        if (end - record < 0x10) return;
        uint32_t id = M32(record), size = M32(record + 4), data = record + 0x10;
        if (size > end - data) return;
        unsigned matches = 0;
        uint32_t candidate = 0;
        int exact = 0;
        for (node = head; node != 0x00A97D40u; node = M32(node)) {
            uint32_t handler = node - 4;
            if (carbon_fix_save_size(handler) != size) continue;
            ++matches;
            candidate = handler;
            if (M32(handler + 0x10) == id) exact = 1;
        }
        if (!exact && matches == 1) M32(record) = M32(candidate + 0x10);
        record = data + size;
    }
}

void carbon_fix_save_load(Cpu *c, void (*original)(Cpu *)) {
    carbon_fix_save_records(c->ecx);
    original(c);
}
