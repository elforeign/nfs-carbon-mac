#include "carbon_pad_state.h"
static int replay_game_blocked(void) {
    return is_open || carbon_pad_context() != CARBON_PAD_DRIVING;
}
