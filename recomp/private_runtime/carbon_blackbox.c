/* FE/load reads run once on the guest frame thread, independently of diagnostics. */
#include "blackbox.h"
void carbon_blackbox_fe(uint64_t frame, uint32_t flow, uint64_t now);
void blackbox_game_frame(uint64_t frame, uint32_t flow, const BlackboxTiming *timing) {
    uint64_t now = blackbox_now_ns();
    carbon_blackbox_fe(frame, flow, now);
    blackbox_record_frame(BLACKBOX_CARBON, frame, flow, timing, now);
}
