typedef struct {
    int initialized, context, controller;
    uint32_t buttons, directions, previous_buttons, previous_directions;
} CarbonPadGuard;
static CarbonPadGuard carbon_pad_guards[2];

/* Direction bits represent signed stick halves and the four POV directions.
 * A half stays blocked until it returns to neutral or crosses to the other half.
 * Keep trigger pressures analog, including a half-travel hold during capture. */
static uint32_t carbon_pad_filter(int idx, PadState *st, uint32_t phys) {
    if (idx < 0 || idx >= 2) return 0;
    CarbonPadGuard *guard = &carbon_pad_guards[idx];
    int context = carbon_pad_context(), controller = carbon_pad_capture_controller();
    float *axes[6] = {&st->lx, &st->ly, &st->rx, &st->ry, &st->lt, &st->rt};
    uint32_t directions = 0;
    for (int i = 0; i < 6; ++i) {
        if (*axes[i] > 0) directions |= 1u << (2 * i);
        if (i < 4 && *axes[i] < 0) directions |= 2u << (2 * i);
    }
    int pov = st->pov;
    if (pov >= 0) {
        if (pov >= 31500 || pov <= 4500) directions |= 1u << 12;
        if (pov >= 4500 && pov <= 13500) directions |= 1u << 13;
        if (pov >= 13500 && pov <= 22500) directions |= 1u << 14;
        if (pov >= 22500 && pov <= 31500) directions |= 1u << 15;
    }
    /* Driving must use held input immediately, including after pause or capture. */
    if (context == CARBON_PAD_DRIVING) {
        guard->buttons = 0;
        guard->directions = 0;
    } else if (guard->initialized && (context != guard->context || controller != guard->controller)) {
        guard->buttons |= phys & guard->previous_buttons;
        guard->directions |= directions & guard->previous_directions;
    }
    guard->previous_buttons = phys;
    guard->previous_directions = directions;
    guard->initialized = 1;
    guard->context = context;
    guard->controller = controller;
    guard->buttons &= phys;
    guard->directions &= directions;
    phys &= ~guard->buttons;
    for (int i = 0; i < 6; ++i)
        if (guard->directions & (3u << (2 * i))) *axes[i] = 0;
    uint32_t dpad = directions & ~guard->directions;
    int x = !!(dpad & (1u << 13)) - !!(dpad & (1u << 15));
    int y = !!(dpad & (1u << 12)) - !!(dpad & (1u << 14));
    static const int angles[3][3] = {{22500, 27000, 31500}, {18000, -1, 0}, {13500, 9000, 4500}};
    st->pov = angles[x + 1][y + 1];
    pad_mode = context == CARBON_PAD_CAPTURE ? "remap" : context == CARBON_PAD_DRIVING ? "driving" : "menus";
    pad_ctl = fe_package_in_control();
    return phys;
}
