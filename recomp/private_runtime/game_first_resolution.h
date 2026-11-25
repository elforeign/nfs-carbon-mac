/* Query the same file-backed game key as native load/save. FirstTime is not
 * enough: an interrupted first launch can have a marker but no saved mode. */
static uint32_t carbon_registry_call(Cpu *c, uint32_t slot, unsigned n, const uint32_t *args) {
    Cpu query = *c;
    query.esp -= 192;
    for (unsigned i = 0; i < n; ++i) M32(query.esp + 4 + 4*i) = args[i];
    host_import(&query, slot);
    return query.eax;
}
static int carbon_saved_mode(Cpu *c, uint32_t *slot) {
    static uint32_t name;
    if (!name) name = gstr("g_RacingResolution");
    Cpu query = *c;
    uint32_t key = call_guest(&query, 0x00732D90u, 0, NULL);
    uint32_t out = c->esp - 48;
    uint32_t open[] = {0x80000002u, key, 0, 0x20019u, out};
    if (carbon_registry_call(c, 0x009C100Cu, 5, open)) return 0;
    uint32_t handle = M32(out);
    M32(out + 12) = 4;
    uint32_t read[] = {handle, name, 0, out + 4, out + 8, out + 12};
    uint32_t error = carbon_registry_call(c, 0x009C1018u, 6, read);
    carbon_registry_call(c, 0x009C1010u, 1, &handle);
    if (error || M32(out + 4) != 4 || M32(out + 12) != 4) return 0;
    *slot = M32(out + 8);
    return 1;
}
static uint32_t carbon_startup_mode;
static int carbon_startup_selected, carbon_startup_detection;
static void carbon_first_mode(Cpu *c) {
    if (carbon_startup_selected) return;
    carbon_modes_init();
    if (!carbon_saved_mode(c, &carbon_startup_mode)) {
        int dw = 0, dh = 0;
        user32_display_pixels(&dw, &dh);
        uint32_t area = 0;
        carbon_startup_mode = 0;
        for (unsigned i = 0; i < 6; ++i) {
            uint32_t w = carbon_modes[i][0], h = carbon_modes[i][1];
            int notch_native = user32_notch_fill() && w == (uint32_t)dw && h == (uint32_t)dh &&
                               (uint64_t)w * h <= 3840u * 2160u;
            if (w > 3840 || (h > 2160 && !notch_native) || w > (uint32_t)dw || h > (uint32_t)dh) continue;
            if (w*h > area) { area = w*h; carbon_startup_mode = i; }
        }
        void boot_reg_set_dword(const char *, uint32_t);
        boot_reg_set_dword("g_RacingResolution", carbon_startup_mode);
    }
    M32(0x00A65388u) = carbon_startup_mode;
    carbon_startup_selected = 1;
}
/* Hardware detection runs after the first device exists. Apply first-launch
 * quality only here; later native preset edits retain their own rules. */
void carbon_first_mode_detect(Cpu *c, void (*original)(Cpu *)) {
    int startup = carbon_startup_selected && !carbon_startup_detection && M32(0x00A6538Cu) == 1;
    carbon_startup_detection = 1;
    original(c);
    if (!startup) return;
    M32(0x00A65388u) = carbon_startup_mode;
    M32(0x00AB0AE8u) = 5; /* Custom keeps the individual settings. */
    static const uint32_t details[] = {
        0x00A65340u, 0x00A65358u, 0x00A65360u, 0x00A6536Cu,
        0x00A65370u, 0x00A65378u, 0x00A6537Cu, 0x00A65380u,
        0x00A65384u, 0x00A65394u, 0x00A65398u
    };
    for (unsigned i = 0; i < sizeof details / sizeof details[0]; ++i) {
        uint32_t address = details[i], cap = M32(address + 0x68u);
        M32(address) = address == 0x00A6537Cu && cap > 1 ? 1 : cap;
        if (diag_on) diag_event("carbon first quality: %08X=%u cap=%u", address, M32(address), cap);
    }
    M32(0x00A63E60u) = 3;
    Cpu quality = *c;
    /* The native loader reads the supplied registry overrides before saving.
     * With no overrides it must not reload the detection's older defaults. */
    if (getenv("BOOT_REG")) call_guest(&quality, 0x00711810u, 0, NULL);
    uint32_t shader = M32(0x00A63E60u);
    call_guest(&quality, 0x0073E7E0u, 1, &shader);
    call_guest(&quality, 0x007112F0u, 0, NULL);
    call_guest(&quality, 0x00711BD0u, 0, NULL);
    M8(0x00AB0B25u) = 1; /* Recreate the first device with the selected AA. */
    if (diag_on) diag_event("carbon first quality: shader=%u performance=%u AA=%u",
                           M32(0x00A63E60u), M32(0x00AB0AE8u), M32(0x00A6537Cu));
}
