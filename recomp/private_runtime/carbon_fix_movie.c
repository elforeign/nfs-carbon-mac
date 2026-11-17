#include "host.h"
#include "carbon_fix_checks.h"

/* Startup observation only; the premise run must precede any audio wait. */
void carbon_fix_movie_start(Cpu *c, void (*original)(Cpu *)) {
    if (!diag_on) { original(c); return; }
    uint32_t self = c->ecx;
    int starting = M32(self + 0x1CC) == 1 && M32(self + 0x180);
    uint32_t before = starting ? M32(self + 0x8C) : 0;
    if (starting)
        diag_event("CARBON K17 start self=%08x stream=%08x entry_bytes=%d connected_before=%u",
                   self, M32(self + 0x180), (int32_t)M32(M32(self + 0x180) + 0xC), before);
    original(c);
    if (starting)
        diag_event("CARBON K17 end self=%08x connected_before=%u connected_after=%u delta=%u state=%u",
                   self, before, M32(self + 0x8C), M32(self + 0x8C) - before,
                   M32(self + 0x1CC));
}
