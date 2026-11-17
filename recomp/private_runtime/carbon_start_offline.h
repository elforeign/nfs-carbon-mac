/* Optional startup sign-in, 005A7E00: type +08 == 0 reads options 3A98
 * (automatic login) and 3A9F (automatic connection). With both off, the native
 * 005A7E84 path copies +AC to +B4, selects completion 3 at +18 and calls
 * 0059B1B0. Use that same completion without changing the stored preferences,
 * allocating a connection or creating its failure dialog. Explicit requests
 * (other types) retain their entire original body.
 *
 * The error is 8D824D60 in the language resources. 005CFFA0, state 27/error 2,
 * looks it up at 005D0057 and creates its dialog through 005CF440. The second
 * user of this hash is the explicit connection callback 005A70C0. Neither
 * error handler nor the shared dialog code is suppressed.
 */
#include "host.h"
#include <stdlib.h>

extern void f_0059B1B0(Cpu *);
extern int diag_on;
extern void diag_event(const char *, ...);

void carbon_start_offline(Cpu *c, void (*original)(Cpu *)) {
    uint32_t self = c->ecx;
    if (M32(self + 8) != 0) {
        original(c);
        return;
    }
    if (diag_on) diag_event("CARBON START offline optional-sign-in type=0");
    c->eax = M32(self + 0xAC);
    M32(self + 0xB4) = c->eax;
    M32(self + 0x18) = 3;
    /* Tail-call semantics: the native completion consumes our guest return. */
    f_0059B1B0(c);
}

/* Screen-text lookup. Carbon's tables lack the seven Rockport neighbourhood
 * names that the merged world's type-11 zones key (HUD updater 00761EF0), so the
 * native lookup would fall back to "DEFAULT STRING". With the Rockport track
 * overlay on, return those names as port strings (English, in capitals: Carbon's
 * HUD font has no lowercase, so mixed case shows only the capitals; reading the
 * other game's language files per player language is a reader this banner does
 * not justify). Every other key, and every run without the overlay, stays native;
 * the diagnostic line for the notice key is unchanged. No allocations or
 * logging on ordinary lookups, including when diag is off. */
static struct { uint32_t key; const char *name; uint32_t guest; } carbon_rock_names[] = {
    {0x4CA802ECu, "OCEAN HILLS", 0}, {0x2485871Eu, "DOWNTOWN ROCKPORT", 0},
    {0xCCBCE907u, "NORTH ROSEWOOD", 0}, {0x9F3316E5u, "CENTRAL ROSEWOOD", 0},
    {0x9A43A1D1u, "NORTH GRAY POINT", 0}, {0x890E0C19u, "SOUTH GRAY POINT", 0},
    {0xCAC1155Cu, "POINT CAMDEN", 0},
};

void carbon_start_notice_text(Cpu *c, void (*original)(Cpu *)) {
    uint32_t hash = M32(c->esp + 4);
    const char *root = getenv("NFS_CARBON_TRACK_OVERLAY");
    if (root && *root) {
        for (unsigned i = 0; i < sizeof carbon_rock_names / sizeof *carbon_rock_names; ++i) {
            if (carbon_rock_names[i].key != hash) continue;
            if (!carbon_rock_names[i].guest) carbon_rock_names[i].guest = gstr(carbon_rock_names[i].name);
            c->eax = carbon_rock_names[i].guest;
            c->esp += 4;
            return;
        }
    }
    original(c);
    if (diag_on && hash == 0x8D824D60u)
        diag_event("CARBON SCREEN TEXT hash=8D824D60 notice=Cannot connect to EA Nation!");
}
