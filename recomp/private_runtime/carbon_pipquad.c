/* Crew member picture inside its HUD frame on a wide output.
 *
 * 00750D40 draws the crew member picture as a quad at fixed screen fractions
 * (x 0.026, width 0.275: the call at 00750DFA into the quad builder 00750B30),
 * through the mirror effect, not a front-end pass. Its frame is the HUD
 * package's PIP_BACKING group, laid out in 640x480 units. On a wide output
 * the HUD runs its wide layout (message 62ED04EC moves the frame's top-left
 * group 120 units left, script 001EDC08) and front-end passes are drawn with
 * kx = (4/3)/aspect about the screen centre, so the frame moves and narrows
 * while the picture stays put, 4/3 too wide, hanging out of the frame.
 *
 * Give the picture's quad the same two steps: 120 of 320 half-width units
 * left, then kx about the centre. A 4:3 output and the mirror's quad (the
 * other caller, 00750D06) keep the native result.
 */
#include "host.h"

extern int diag_on;
extern void diag_event(const char *, ...);
extern float carbon_fe_kx(void);

void carbon_pipquad_build(Cpu *c, void (*original)(Cpu *)) {
    uint32_t caller = M32(c->esp), quad = M32(c->esp + 4);
    original(c);
    if (caller != 0x00750DFFu) return;
    float kx = carbon_fe_kx();
    if (kx >= 1.0f) return;
    float native = MF32(quad);
    for (unsigned vertex = 0; vertex < 4; ++vertex) {
        uint32_t x = quad + vertex * 0x18u;
        MF32(x) = (MF32(x) - 120.0f / 320.0f) * kx;
    }
    if (diag_on) {
        static unsigned shown;
        if (!(shown++ % 60u))
            diag_event("carbon_pipquad: crew picture left edge %.4f -> %.4f, kx %.4f (%u)",
                       (double)native, (double)MF32(quad), (double)kx, shown);
    }
}
