void feedback_poll_pause(void) {
    feedback_poll_owners();
    uint32_t sim = G ? M32(0x00B4CFE0u) : 0;
    feedback_suppress(FEEDBACK_PAUSE, sim && M32(sim + 0x24) == 4);
    padfx_poll();
}
