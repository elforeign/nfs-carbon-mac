/* Diagnostics observe native results without additional guest calls/writes. */
void carbon_fix_audio_poll(Cpu *c, void (*original)(Cpu *)) {
    if (!diag_on) { original(c); return; }
    uint32_t caller = M32(c->esp), stream = c->ecx;
    original(c);
    if (caller == 0x00888917u)
        diag_event("CARBON K17 audio_poll stream=%08x bytes=%d site=00888912",
                   stream, (int32_t)c->eax);
}

void carbon_fix_cull_check(Cpu *c, void (*original)(Cpu *)) {
    if (!diag_on) { original(c); return; }
    uint32_t self = c->ecx;
    original(c);
    if (M32(0x00A99BBCu) != 6) return;
    static uint64_t second;
    static unsigned calls, hidden, groups[11];
    uint64_t now = host_ticks() / 1000000000ull;
    if (second && now != second) {
        diag_event("CARBON K27 second=%llu calls=%u hidden=%u groups=%u,%u,%u,%u,%u,%u,%u,%u,%u,%u,%u",
                   (unsigned long long)second, calls, hidden, groups[0], groups[1],
                   groups[2], groups[3], groups[4], groups[5], groups[6], groups[7],
                   groups[8], groups[9], groups[10]);
        calls = hidden = 0;
        memset(groups, 0, sizeof groups);
    }
    second = now;
    ++calls;
    for (unsigned i = 0; i < 11; ++i)
        if (!M8(self + 0x18 + 0x20 * i)) { ++hidden; ++groups[i]; }
}
