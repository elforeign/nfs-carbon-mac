/* Host diagnostics needed by the shared window and preferences callbacks. */
#include "host.h"
#include "gpuclients.h"
#include "roam_online.h"
/* No native online session is installed for this image. */
atomic_int roam_online_active;
#include <errno.h>
#include <math.h>
#include <stdarg.h>
extern int diag_on;
void diag_event(const char *, ...);
/* This image does not start the optional background GPU sampler. */
void gpuclients_cached(GPUClientsSample *out) {
    memset(out,0,sizeof *out);
    out->dev_util=out->self_ms=out->other_ms=NAN;
    snprintf(out->top,sizeof out->top,"-");
    snprintf(out->mhz,sizeof out->mhz,"-");
    snprintf(out->states,sizeof out->states,"-");
    snprintf(out->clock_status,sizeof out->clock_status,"unavailable (sampler inactive)");
}
typedef struct { const char *stage; uint64_t start; } MenuSaveSpan;
static _Thread_local MenuSaveSpan menu_save_spans[32];
static _Thread_local unsigned menu_save_depth;
unsigned save_timing_enter(const char *stage) {
    if (!diag_on || menu_save_depth==32) return UINT32_MAX;
    int error=errno; unsigned span=menu_save_depth++;
    menu_save_spans[span]=(MenuSaveSpan){stage,host_ticks()};
    errno=error; return span;
}
void save_timing_leave(unsigned span, int64_t result) {
    if (span==UINT32_MAX || span>=menu_save_depth) return;
    int error=errno; MenuSaveSpan s=menu_save_spans[span]; menu_save_depth=span;
    if (diag_on) diag_event("menu preferences: stage=%s result=%lld errno=%d duration_ns=%llu",
        s.stage,(long long)result,error,(unsigned long long)(host_ticks()-s.start));
    errno=error;
}
