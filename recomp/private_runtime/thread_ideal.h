/* Included by the private copy of threads.c after its private KObj definition. */
uint32_t private_set_thread_ideal(uint32_t h, uint32_t ideal) {
    static uint32_t main_ideal = 32;
    if (ideal > 32) { last_error = 87; return UINT32_MAX; }
    uint32_t *value;
    if (h == 0xFFFFFFFEu && !self) value = &main_ideal;
    else {
        KObj *t = h == 0xFFFFFFFEu ? self : kget(h);
        if (!t || t->type != K_THREAD) { last_error = 6; return UINT32_MAX; }
        value = &t->private_ideal;
    }
    uint32_t previous = *value; *value = ideal;
    return previous; /* advisory hint; host scheduling stays native */
}
