/* Keep the outer ticker alive; timestep preparation owns the actual hold. */
int portmenu_hold(void) { return is_open && M32(0x00A99BBCu) == 6; }
void portmenu_pass(Cpu *c) {
    osk_pass(c);
    static int sound_owned, native_paused_on_take;
    int want = portmenu_hold();
    if (!want && !sound_owned) return;
    if (!(M32(0x00A8BAE4u) & 2)) sound_owned = 0;
    uint32_t system = M32(0x00B4CFE0u);
    int native_paused = system && M32(system + 0x24) != 3;
    /* A new native pause can take over our sound state; its unpause releases it.
     * A simulation hold already present when we took sound (such as an SMS)
     * does not own the PauseMenu bit we added. */
    if (!want && sound_owned && native_paused && !native_paused_on_take) { sound_owned = 0; return; }
    if (want == sound_owned || (want && (M32(0x00A8BAE4u) & 2))) return;
    uint32_t args[2] = {(uint32_t)want, 1};
    Cpu saved = *c;
    call_guest(c, 0x0050C370u, 2, args);
    *c = saved;
    sound_owned = want && !!(M32(0x00A8BAE4u) & 2);
    if (sound_owned) native_paused_on_take = native_paused;
}
