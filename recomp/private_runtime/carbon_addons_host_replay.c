/* Native saved keyboard bindings precede all replay shortcuts. */
#include "host.h"
#include "replay_input.h"
/* 00679BA0 allocates 72 action rows, two keyboard slots followed by
 * two slots per controller. 0067A340 accepts a keyboard record in any
 * slot, reading type at +0 and scan at +4. */
int replay_key_in_use(unsigned scan) {
    unsigned controllers = M32(0x00A98948u);
    if (controllers > 16) return 1;
    unsigned slots = 2 + 2 * controllers;
    for (unsigned action = 0; action < 72; ++action) {
        uint32_t row = M32(0x00A98704u + 8u * action);
        if (!row) continue;
        for (unsigned slot = 0; slot < slots; ++slot) {
            uint32_t binding = row + 12u * slot;
            if (M32(binding) == 1 && M32(binding + 4) == scan) return 1;
        }
    }
    return 0;
}
