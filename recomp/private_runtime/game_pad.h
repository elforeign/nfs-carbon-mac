#include "carbon_pad_guard.h"

static void pad_apply_layout(int idx, PadState *st, uint32_t phys) {
    (void)idx;
    const char *layout;
    /* Main also marks analog pressures as pressed; retain their partial values. */
    if ((phys & (1u << P_L2)) && st->lt == 0) st->lt = 1;
    if ((phys & (1u << P_R2)) && st->rt == 0) st->rt = 1;
    if (pad_layout_xbox()) {
        st->buttons = (st->rt > 0.5f) | bit(phys, P_CROSS) << 1 |
            (st->lt > 0.5f) << 2 | bit(phys, P_SQUARE) << 3 |
            bit(phys, P_TRIANGLE) << 4 | bit(phys, P_CREATE) << 5 |
            bit(phys, P_CIRCLE) << 6 | bit(phys, P_OPTIONS) << 7 |
            bit(phys, P_L3) << 11;
        layout = "xbox";
    } else {
        st->buttons = phys & 0x3FFu;
        layout = "physical";
    }
    if (diag_on) {
        static uint32_t last = ~0u;
        if (st->buttons != last) {
            last = st->buttons;
            diag_event("private pad: layout=%s buttons=%03X lt=%.3f rt=%.3f", layout, st->buttons, st->lt, st->rt);
        }
    }
}
