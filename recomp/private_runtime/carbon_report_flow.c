/* Native game-flow state, shared with the input context classifier. */
#include "host.h"
uint32_t private_report_flow(void) { return M32(0x00A99BBCu); }

#include <stdio.h>
int private_carbon_player_pose(float *, float *);
int private_report_position(float pos[3], float forward[3], char track[64]) {
    if (!private_carbon_player_pose(pos, forward)) return 0;
    // Native streaming manager's current pack name, also used by the minimap diagnostic.
    uint32_t manager = M32(0x00A97DE0u);
    if (manager) snprintf(track, 64, "%.63s", G + manager + 0x40);
    return 1;
}
