#include "carbon_pad_layout.h"
static void carbon_pad_deliver(int idx, PadState *st, uint32_t phys) {
    static int last_layout[2], initialized[2];
    CarbonPadLayoutChoice choice = carbon_pad_layout_resolve((unsigned)idx);
    if (idx < 0 || idx >= 2) return;
    int stamp = choice.layout + 4 * choice.kind;
    if (initialized[idx] && last_layout[idx] != stamp)
        carbon_pad_guards[idx].context = -1; /* Same release rule as a context transition. */
    initialized[idx] = 1; last_layout[idx] = stamp;
    /* Digital-only triggers still supply full pressure; fractional samples keep
     * their original value when the framework also marks them pressed. */
    if ((phys & (1u << P_L2)) && st->lt == 0) st->lt = 1;
    if ((phys & (1u << P_R2)) && st->rt == 0) st->rt = 1;
    phys = carbon_pad_filter(idx, st, phys);
    pad_native(st, phys);
}
