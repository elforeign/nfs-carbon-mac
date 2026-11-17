/* Selected sound policy: diagnostic muting and safe startup device reopen. */
static inline int game_sound_mix_muted(void) {
    return diag_on && getenv("BOOT_DIAG_MIX_MUTE");
}
static inline int game_sound_can_startup_reopen(void) { return 1; }
static inline void game_sound_startup_reopen(DsDevice *device) {
    uint32_t system = M32(0x00B4CFE0u), state = system ? M32(system + 0x24) : 0;
    uint32_t flow = M32(0x00A99BBCu);
    /* Read under the guest lock. The initial direct drive is eligible too;
     * transitions and a nonrunning simulation must not reopen the output. */
    int loading = flow > 3 && (flow != 6 || state != 3);
    ds_device_launch_reopen_tick(device, state == 4 || loading);
}
