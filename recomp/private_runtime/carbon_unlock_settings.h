/* Saved player preference; native developer switch, purchases save normally. */
static void carbon_unlock_apply(int value) {
    M8(0x00A9E6C0u) = value ? 1 : 0;
}

static void carbon_unlock_settings_init(void) {
    static Setting row = {
        .id="gameplay.unlock_all", .category=SET_GAMEPLAY, .order=110,
        .label="Unlock All (changes your save)",
        .help="Every car, part, paint and vinyl shows as unlocked while On. What you buy while On stays in your save. Re-enter the shop to refresh its lists.",
        .type=SET_TOGGLE, .def=0, .env="NFS_CARBON_UNLOCKALL",
        .apply=carbon_unlock_apply
    };
    settings_add(&row);
}

void carbon_unlock_frame(void) {
    static int started, counted;
    if (!started) {
        started = 1;
        carbon_unlock_apply(settings_get("gameplay.unlock_all"));
    }
    if (!diag_on || counted) return;
    uint32_t manager = M32(0x00A8AD00u);
    if (!manager) return;
    counted = 1;
    /* The queries are thiscall with one stack argument and return a bool in AL.
     * A separate diagnostic stack leaves the running guest CPU untouched. */
    uint32_t stack = galloc(65536);
    int paints = 0, rims = 0;
    for (uint32_t n = 0; n < 100; ++n) {
        Cpu query = {0};
        query.esp = stack + 65536;
        query.ecx = manager;
        paints += !(call_guest(&query, 0x004B0FC0u, 1, &n) & 255);
        query = (Cpu){0};
        query.esp = stack + 65536;
        query.ecx = manager;
        rims += !(call_guest(&query, 0x004B10D0u, 1, &n) & 255);
    }
    diag_event("unlock: locked paints %d rims %d flag=%u", paints, rims, M8(0x00A9E6C0u));
}
