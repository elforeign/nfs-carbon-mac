#include "host.h"

static uint32_t controlling_credits(uint32_t engine) {
    uint32_t package = M32(engine + 0xE4u);
    for (unsigned i = 0; package && package < 0xFFFFF000u && i < 128; ++i, package = M32(package + 8u)) {
        if (!M32(package + 0x20u)) continue;
        const char *name = gptr(M32(package + 0xCu));
        return name && !strcmp(name, "Credits.fng") ? package : 0;
    }
    return 0;
}

void carbon_credits_input(Cpu *c, void (*original)(Cpu *)) {
    uint32_t engine = c->ecx;
    uint32_t package = M8(engine) ? controlling_credits(engine) : 0;
    uint32_t slots = package ? M32(package + 0x20u) : 0;
    int menu_gate_closed = package && !M8(package + 0x28u) &&
                           (!M8(engine + 0x524Cu) || M8(package + 0x18u));
    original(c);
    if (!slots || !M8(engine)) return;

    /* The FE tick records pad edges before testing each package's input gate. */
    uint32_t count = M32(engine + 0xD0u);
    uint32_t input = M32(engine + 4u), back = 0;
    for (unsigned i = 0; i < count && slots; ++i, slots >>= 1, input += 0x88u) {
        if (slots & 1u) back |= (M32(input + 4u) & ~M32(input)) & 0x20u;
    }
    if (!back || controlling_credits(engine) != package) return;

    /* Follow the same live child chain as the native PAD_BACK dispatcher. */
    uint32_t manager = M32(0x00A97A7Cu);
    if (!manager) return;
    uint32_t child = M32(manager + 0xB0u);
    while (child && M32(child + 0x18u) != UINT32_MAX) {
        manager = child;
        child = M32(manager + 0xB0u);
    }
    if (M32(manager) != 0x009F9200u || M32(manager + 0x18u) != 0)
        return;

    /* Enabled menu input already has a native Back callback. */
    uint32_t mode = M32(manager + 4u);
    if (mode != 1u && (mode != 0u || !menu_gate_closed)) return;

    /* Run the native close transition after the package walk. */
    Cpu close = *c;
    close.ecx = manager;
    call_guest(&close, 0x005A52F0u, 0, NULL);
}
