#include "host.h"

static double carbon_fix_clock_time;

void carbon_fix_clock_tick(Cpu *c, void (*original)(Cpu *)) {
    float before = MF32(0x00B4CFD8u);
    /* All native load/unload resets remain authoritative. */
    if (before != (float)carbon_fix_clock_time) carbon_fix_clock_time = before;
    original(c);
    /* 0076AE5E returns the same float step supplied to the 19 simulation
     * callbacks. Using the return avoids evaluating the step helper twice. */
    double step = c->st[c->top];
    if (step > 0) {
        carbon_fix_clock_time += step;
        MF32(0x00B4CFD8u) = (float)carbon_fix_clock_time;
    }
}
