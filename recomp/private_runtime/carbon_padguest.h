#pragma once

/* Keep the second queue outside the 16-byte FE root: +4..+B are flags. */
static inline int carbon_padguest_owns(uint32_t device, unsigned pad) {
    return pad_count() != 2 || M32(device + 0x24) == pad;
}
static inline int carbon_padguest_keyboard(uint32_t device) {
    return pad_count() != 2 || M32(device + 0x24) == 0;
}
void carbon_padguest_evaluate(Cpu *c, void (*original)(Cpu *));
uint32_t carbon_padguest_queue(uint32_t fe, unsigned port);
