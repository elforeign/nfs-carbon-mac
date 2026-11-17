static uint32_t simable(Cpu *c, uint32_t handle) {
    if (!handle) return 0;
    uint32_t begin = M32(SIMABLES), a[3] = {begin, begin + 8 * M32(SIMABLE_COUNT), handle}, esp = c->esp;
    uint32_t node = call_guest(c, FN_KEYED_SEARCH, 3, a);
    c->esp = esp;
    return node ? M32(node + 4) : 0;
}
