/* Copied binary observations shared by the recorder and optional verbose mirror.
 * No guest calls or writes. Only the reader in carbon_blackbox_fe.c touches G. */
#ifndef CARBON_FE_PROBE_H
#define CARBON_FE_PROBE_H
#define CARBON_FE_PROBE_FRAMES 600
#define CARBON_FE_PACKAGES 24

typedef struct {
    BlackboxFE value;
    uint32_t valid;
    char screen[32], next[32];
} CarbonFEManager;
typedef struct {
    uint32_t address, control;
    char name[32];
} CarbonFEPackage;
typedef struct {
    CarbonFEManager manager[3];
    BlackboxLoad load;
    uint32_t load_valid, count, truncated;
    CarbonFEPackage package[CARBON_FE_PACKAGES];
} CarbonFEState;

static int carbon_fe_probe_enabled(void) {
    static int state = -1;
    if (state < 0) {
        const char *e = getenv("NFS_CARBON_FE_PROBE");
        state = e && *e == '1';
    }
    return diag_on && state;
}
static int carbon_fe_probe_manager(char *out, size_t size, const char *label, const CarbonFEManager *m) {
    const BlackboxFE *v = &m->value;
    if (!m->valid) return snprintf(out, size, " %s=none", label);
    return snprintf(out, size, " %s=%08X vt=%08X state=%d start=%d prev=%d screen='%s' next='%s' pending=%u wait=%d child=%08X",
                    label, v->address, v->vtable, (int)v->state, (int)v->start, (int)v->previous,
                    m->screen, m->next, v->pending, (int)v->wait, v->child);
}
static void carbon_fe_probe(const CarbonFEState *s, uint32_t flow) {
    static uint32_t last_flow = ~0u;
    static uint64_t last_log, seen, window_end;
    static char last[1536];
    if (flow == 3 && last_flow != 3) { seen = perf_nframes; window_end = seen + CARBON_FE_PROBE_FRAMES; }
    last_flow = flow;
    uint64_t now_frames = perf_nframes;
    if (seen < window_end) {
        if (now_frames - seen > PERF_RING) seen = now_frames - PERF_RING;
        for (; seen < now_frames && seen < window_end; ++seen)
            diag_event("fe-probe: draws frame=%llu n=%u", (unsigned long long)(seen + CARBON_FE_PROBE_FRAMES - window_end),
                       perf_frames[seen % PERF_RING].draws);
    }
    char line[1536];
    const BlackboxLoad *l = &s->load;
    size_t n = snprintf(line, sizeof line, "flow=%u mask=%X loader busy=%u want=%d have=%d+%d garage_ready=%u", flow,
                        l->mask, l->busy, (int)l->want, (int)l->have, (int)l->queued, l->garage_ready);
    const char *labels[] = {"root", "child", "grand"};
    for (unsigned i = 0; i < 3; ++i)
        n += carbon_fe_probe_manager(line + n, sizeof line - n, labels[i], &s->manager[i]);
    for (unsigned i = 0; i < s->count; ++i) {
        n += snprintf(line + n, sizeof line - n, " pkg%u='%s'%s", i, s->package[i].name, s->package[i].control ? "*" : "");
        if (n >= sizeof line - 64) break;
    }
    uint64_t now = host_ticks();
    if (strcmp(line, last) || (flow == 3 && now - last_log >= 1000000000ull)) {
        snprintf(last, sizeof last, "%s", line);
        last_log = now;
        diag_event("fe-probe: %s", line);
    }
}
#endif
