/* 00813850/00813920 finish native MAP/TILE binding before observation.
 * 00B77EB8 owns the manager; 007E9D10 grid +18/+1C/+20 is rows/cols/table.
 * No guest state or Cpu register is changed by this diagnostic.
 */
#include "host.h"
#include <stdlib.h>
#include <string.h>

extern int diag_on;
extern void diag_event(const char *, ...);

static void carbon_c1grid_sample(const char *event) {
    static int enabled = -1;
    if (!diag_on) return;
    if (enabled < 0) {
        const char *value = getenv("NFS_CARBON_GRID_PROBE");
        enabled = value && !strcmp(value, "1");
    }
    if (!enabled) return;
    uint32_t manager = M32(0x00B77EB8u);
    if (!manager) return;
    uint32_t grid = M32(manager), rect = M32(manager + 0x10);
    uint32_t rows = grid ? M32(grid + 0x18) : 0;
    uint32_t columns = grid ? M32(grid + 0x1C) : 0;
    uint32_t table = grid ? M32(grid + 0x20) : 0, bound = 0;
    /* The native cell id is u16. Refuse an invalid diagnostic traversal. */
    if (table && rows && columns && (uint64_t)rows * columns <= 65536)
        for (uint32_t i = 0; i < rows * columns; ++i)
            bound += M32(table + 4 * i) != 0;
    float cell;
    uint32_t bits = M32(manager + 0x40);
    memcpy(&cell, &bits, sizeof cell);
    diag_event("carbon_grid: event=%s tile=%u cgrd=%ux%u grid=%ux%u cell=%.9g rect=%u,%u,%u,%u,%u bound=%u",
               event, M32(manager + 0x0C), M32(manager + 0x38), M32(manager + 0x3C),
               rows, columns, cell, rect ? M16(rect) : 0,
               rect ? M16(rect + 2) : 0, rect ? M16(rect + 4) : 0,
               rect ? M16(rect + 6) : 0, rect ? M16(rect + 8) : 0, bound);
}

void carbon_c1grid_map(Cpu *c, void (*original)(Cpu *)) {
    original(c);
    carbon_c1grid_sample("map");
}

void carbon_c1grid_tile(Cpu *c, void (*original)(Cpu *)) {
    original(c);
    carbon_c1grid_sample("tile");
}
