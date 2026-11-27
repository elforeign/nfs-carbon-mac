#pragma once
#define FEEDBACK_VTABLE 0x009E2188u
#define FN_GET_ATTRIBUTE 0x00463A80u
#define SIMABLES 0x00AA26B4u
#define SIMABLE_COUNT 0x00AA26BCu
#define FN_KEYED_SEARCH 0x0060CBA0u
#define FN_QUERY_VEHICLE 0x0040E650u
#define SIMABLE_LINEAR_VELOCITY 0x68
/* 0076FB20 publishes complete+44 in this local IPlayer vector.
 * 0075DDC0 returns IPlayer+0C (feedback), 0076E730 returns +18 (port).
 * 007655D0 assigns the native FE ports; vector order is not pad order. */
#define CARBON_FEEDBACK_PLAYERS 0x00A9FF5Cu
#define CARBON_FEEDBACK_PLAYER_COUNT 0x00A9FF64u
static int carbon_feedback_player_slot(uint32_t self) {
    uint32_t list = G ? M32(CARBON_FEEDBACK_PLAYERS) : 0;
    uint32_t count = G ? M32(CARBON_FEEDBACK_PLAYER_COUNT) : 0;
    for (uint32_t i = 0; list && i < count; ++i) {
        uint32_t player = M32(list + i * 4);
        if (self && player == self + 0x44 && M32(player + 0x18) < 2)
            return (int)M32(player + 0x18);
    }
    return -1;
}
