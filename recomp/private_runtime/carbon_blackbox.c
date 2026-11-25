/* FE/load reads run once on the guest frame thread, independently of diagnostics. */
#include "blackbox.h"
void carbon_blackbox_fe(uint64_t frame, uint32_t flow, uint64_t now);
void carbon_blackbox_cinematics(uint64_t frame, uint64_t now);
void blackbox_game_frame(uint64_t frame, uint32_t flow, const BlackboxTiming *timing) {
    uint64_t now = blackbox_now_ns();
    carbon_blackbox_fe(frame, flow, now);
    carbon_blackbox_cinematics(frame, now);
    blackbox_input(frame, now);
    blackbox_record_frame(BLACKBOX_CARBON, frame, flow, timing, now);
}
