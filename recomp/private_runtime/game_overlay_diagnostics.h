/* Keep the selected diagnostic policy; replace only its unsupported frame counters. */
#define diag_frame private_overlay_base_frame
#define perf_gpu_done private_overlay_base_gpu_done
#include "game_diagnostics.h"
#undef diag_frame
#undef perf_gpu_done

void perf_gpu_done(uint64_t serial, double ms) {
    perf_gpu_ms[serial % PERF_RING] = (float)ms;
    __atomic_store_n(&perf_gpu_serial, serial, __ATOMIC_RELEASE);
}

static int private_overlay_compare(const void *a, const void *b) {
    float x = *(const float *)a, y = *(const float *)b;
    return (x > y) - (x < y);
}
/* stats.log and the panel use the same trailing-second window, including the
 * oldest frame that crosses one second. Keep this usable without guest state. */
static void private_overlay_stats(FILE *f, uint64_t frame, uint64_t now) {
    float times[PERF_RING], sum = 0;
    uint64_t head = __atomic_load_n(&perf_nframes, __ATOMIC_ACQUIRE);
    int n = 0;
    for (; n < PERF_RING - 1 && (uint64_t)n < head && sum < 1000; ++n) {
        times[n] = perf_frames[(head - 1 - n) % PERF_RING].frame_ms;
        sum += times[n];
    }
    qsort(times, (size_t)n, sizeof *times, private_overlay_compare);
    fprintf(f, "t %.1f frame %llu fps %.1f ms p50 %.2f p99 %.2f max %.2f\n",
            now / 1e9, (unsigned long long)frame, sum > 0 ? n * 1000.0f / sum : 0,
            n ? times[n / 2] : 0, n ? times[n * 99 / 100] : 0, n ? times[n - 1] : 0);
    fflush(f);
}

uint32_t private_report_flow(void);
void diag_frame(uint64_t frame, uint64_t draws) {
    private_overlay_base_frame(frame, draws);
    static uint64_t previous, idle_previous[IDLE_N], logged;
    static uint32_t ticks_previous;
    uint64_t now = host_ticks();
    /* Native simulation increments this once per positive 0076ADA0 callback
     * step, alongside the time at B4CFD8. Native load/reset stays authoritative. */
    uint32_t ticks = M32(0x00B4CFD4u);
    PerfFrame *p = &perf_frames[perf_nframes % PERF_RING];
    p->frame_ms = previous ? (float)((now - previous) / 1e6) : 0;
    float idle = 0;
    for (int k = 0; k < IDLE_N; ++k) {
        p->idle_ms[k] = previous ? (float)((diag_idle_ns[k] - idle_previous[k]) / 1e6) : 0;
        idle_previous[k] = diag_idle_ns[k];
        idle += p->idle_ms[k];
    }
    p->busy_ms = fmaxf(0, p->frame_ms - idle);
    p->draws = (uint32_t)draws;
    p->ticks = previous && ticks >= ticks_previous ? ticks - ticks_previous : 0;
    ticks_previous = ticks;
    previous = now;
    __atomic_store_n(&perf_nframes, perf_nframes + 1, __ATOMIC_RELEASE);
    report_frame(frame, private_report_flow());
    overlay_frame();
    if (diag_on && now - logged >= 1000000000ull) {
        if (!stats_f) {
            /* diag_init opened this stream; share its position with mixrms. */
            stats_f = private_mix_file;
        }
        if (stats_f) private_overlay_stats(stats_f, frame, now);
        logged = now;
    }
}
