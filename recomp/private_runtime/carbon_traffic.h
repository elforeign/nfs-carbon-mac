/* Native traffic observers; no guest writes or calls beyond the original. */
#include "host.h"
#include <stdio.h>

extern int diag_on;
extern void diag_event(const char *, ...);

static unsigned long long carbon_traffic_attempts, carbon_traffic_spawned;
static unsigned carbon_traffic_calls;
static uint32_t carbon_traffic_collection;

/* 00445080 walks this pool, including inactive reusable vehicles (00422A10).
 * IVehicle+9C == 006D80C0 returns vehicle+A8 != 0. Unknown is not zero. */
static int carbon_traffic_alive(uint32_t manager) {
    uint32_t array = M32(manager + 0x5C), count = M32(manager + 0x64);
    if (count > 1024 || (!array && count)) return -1;
    int alive = 0;
    for (unsigned i = 0; i < count; ++i) {
        uint32_t v = M32(array + i * 4), vt = v ? M32(v) : 0;
        if (!v) continue;
        if (!vt || M32(vt + 0x9C) != 0x006D80C0u) return -1;
        if (M32(v + 0xA8)) ++alive;
    }
    return alive;
}

void carbon_traffic_choose(Cpu *c, void (*original)(Cpu *)) {
    if (!diag_on) { original(c); return; }
    uint32_t manager = c->ecx;
    original(c);
    /* 00422C30 uses 004613E0 on this+100: collection pointer -> key at +10. */
    uint32_t collection = M32(manager + 0x100);
    uint32_t pattern = collection ? M32(collection + 0x10) : 0;
    if (collection != carbon_traffic_collection) {
        carbon_traffic_collection = collection;
        diag_event("traffic: pattern=%08x", pattern);
    }
    if (++carbon_traffic_calls % 60) return;
    int alive = carbon_traffic_alive(manager);
    char value[16] = "na";
    if (alive >= 0) snprintf(value, sizeof value, "%d", alive);
    diag_event("traffic: status attempts=%llu spawned=%llu alive=%s pattern=%08x density=%.6g disabled=%u",
               carbon_traffic_attempts, carbon_traffic_spawned, value, pattern,
               (double)MF32(0x00A9E640), (unsigned)M8(0x00A9E644));
}

void carbon_traffic_spawn(Cpu *c, void (*original)(Cpu *)) {
    original(c);
    if (!diag_on) return;
    ++carbon_traffic_attempts;
    if ((uint8_t)c->eax == 1) {
        ++carbon_traffic_spawned;
        diag_event("traffic: spawn attempt=%llu spawned=%llu",
                   carbon_traffic_attempts, carbon_traffic_spawned);
    }
}
