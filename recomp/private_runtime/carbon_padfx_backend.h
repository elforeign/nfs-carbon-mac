/* Address-free output accounting. Fake selection precedes every output sink. */
#include <stdlib.h>
#include "carbon_padfx.h"
static pthread_once_t fx_once = PTHREAD_ONCE_INIT;
static pthread_mutex_t fx_count_mu = PTHREAD_MUTEX_INITIALIZER;
static int fx_fake;
static uint64_t fx_total[FX_COUNT], fx_second[FX_COUNT], fx_log_at;
static void fx_select(void) {
    const char *value = getenv("NFS_PADFX_FAKE");
    fx_fake = value && !strcmp(value, "1");
}
int carbon_padfx_fake(void) { pthread_once(&fx_once, fx_select); return fx_fake; }
void carbon_padfx_count(int kind) {
    if (kind < 0 || kind >= FX_COUNT) return;
    pthread_mutex_lock(&fx_count_mu);
    ++fx_total[kind]; ++fx_second[kind];
    pthread_mutex_unlock(&fx_count_mu);
}
void carbon_padfx_counts(uint64_t out[FX_COUNT]) {
    pthread_mutex_lock(&fx_count_mu);
    memcpy(out, fx_total, sizeof fx_total);
    pthread_mutex_unlock(&fx_count_mu);
}
void carbon_padfx_log(int force) {
    if (!diag_on) return;
    uint64_t now = host_ticks();
    pthread_mutex_lock(&fx_count_mu);
    if (!force && fx_log_at && now - fx_log_at < 1000000000ull) {
        pthread_mutex_unlock(&fx_count_mu); return;
    }
    fx_log_at = now;
    /* Separate short lines fit the diagnostic event ring. Zero seconds matter. */
    diag_event("padfx-fake: second enabled=%d motor=%llu gas=%llu brake=%llu shift=%llu off=%llu breaker=%llu",
        carbon_padfx_fake(), (unsigned long long)fx_second[FX_MOTOR],
        (unsigned long long)fx_second[FX_GAS], (unsigned long long)fx_second[FX_BRAKE],
        (unsigned long long)fx_second[FX_SHIFT], (unsigned long long)fx_second[FX_OFF],
        (unsigned long long)fx_second[FX_BREAKER]);
    diag_event("padfx-fake: total motor=%llu gas=%llu brake=%llu shift=%llu real_open=%llu real_write=%llu",
        (unsigned long long)fx_total[FX_MOTOR], (unsigned long long)fx_total[FX_GAS],
        (unsigned long long)fx_total[FX_BRAKE], (unsigned long long)fx_total[FX_SHIFT],
        (unsigned long long)fx_total[FX_OPEN], (unsigned long long)fx_total[FX_WRITE]);
    memset(fx_second, 0, sizeof fx_second);
    pthread_mutex_unlock(&fx_count_mu);
}
