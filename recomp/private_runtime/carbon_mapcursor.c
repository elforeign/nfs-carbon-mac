/* World map cursor ring with a controller.
 *
 * 005C8C70 is the world map's mouse step. While the map is browsed (mode
 * +94 is 0 or 1) it shows the cursor group (FE object F156F6C5, kept at map
 * +28) only when the mouse pointer is over the map, and hides it otherwise:
 * 005C8E7C sets flag bit 0 at object +1C. The stick step 005C8E90 moves that
 * same object, and the icon snap 005C3330 skips a hidden cursor, so a
 * controller player sees no ring and cannot pick an event by moving over it.
 *
 * With the controller as the last input the ring stays shown while browsing,
 * the way the game's own show branch (005C8DCC) does it. Keyboard and mouse
 * keep the native behaviour, and so does mode 2, whose entry (005CDBF0) hides
 * the cursor on purpose.
 *
 * 0058F770 consumes FRONTENDACTION_UP/DOWN/LEFT/RIGHT (41..44), fed by
 * FE_ACTION_UP/DOWN/LEFT/RIGHT: the left stick, not the right stick. Up is
 * DirectInput lY below centre, just as in menus. 006A0060 in 005C8E90 reads
 * the map's interpolated centre, not a physical stick.
 * The PC step scales motion by 204*dt + 2*zoom - 2. At far zoom (0.39),
 * dt=1/240 makes that -0.37: up moves down and right moves left. Scale the
 * whole native 60 Hz displacement by elapsed time, keeping its 60 Hz speed
 * and native event handling. Mouse coordinates never pass through this step.
 */
#include "host.h"

extern int diag_on;
extern void diag_event(const char *, ...);
extern int prompts_last_input(void);

void carbon_mapcursor_input(Cpu *c, void (*original)(Cpu *)) {
    uint32_t map = c->ecx, queue = M32(map + 0x2Cu);
    unsigned axes = 0;
    if (queue && M32(map + 0x94u) <= 1u) {
        /* The native input map is a ring of 12-byte events; 00680320 wraps
         * the read index at capacity, including queues spanning the end. */
        uint32_t count = M32(queue), index = M32(queue + 8u), capacity = M32(queue + 12u);
        for (uint32_t i = 0; i < count; ++i) {
            uint32_t event = M32(queue + 16u + 12u * index);
            if (event == 41u || event == 42u) axes |= 2u;
            if (event == 43u || event == 44u) axes |= 1u;
            if (++index >= capacity) index = 0;
        }
    }
    if (!axes) { original(c); return; }
    uint32_t saved_dt = M32(0x00A99A5Cu);
    float frames = MF32(0x00A99A5Cu) * 60.0f;
    MF32(0x00A99A5Cu) = 1.0f / 60.0f;
    original(c);
    M32(0x00A99A5Cu) = saved_dt;
    /* Only rescale axes actually written by the native event consumer.
     * Missing directions and empty queues retain the native stored values. */
    if (axes & 1u) MF32(map + 0x30u) *= frames;
    if (axes & 2u) MF32(map + 0x34u) *= frames;
}

void carbon_mapcursor_mouse(Cpu *c, void (*original)(Cpu *)) {
    uint32_t map = c->ecx;
    original(c);
    if (prompts_last_input() != 1 || M32(map + 0x94u) > 1u) return;
    uint32_t cursor = M32(map + 0x28u);
    if (!cursor || !(M32(cursor + 0x1Cu) & 1u)) return;
    M32(cursor + 0x1Cu) = (M32(cursor + 0x1Cu) & ~1u) | 0x02400000u;
    if (diag_on) {
        static unsigned shown;
        if (!(shown++ & 0xFFu)) diag_event("carbon_mapcursor: ring kept for the controller (%u)", shown);
    }
}
