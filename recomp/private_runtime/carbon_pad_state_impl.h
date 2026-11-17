#include "carbon_pad_state.h"

/* Validate the entire control-order chain, including its noncontrolling tail.
 * A missing front end is a transition, whereas a valid empty chain has no menu.
 * The bounded walk also rejects cycles without trusting the load-order links. */
static uint32_t carbon_pad_package(int *valid) {
    uint32_t wrapper = M32(0x00A97A78u);
    *valid = 0;
    if (!wrapper || wrapper == 0xFFFFFF28u) return 0;
    uint32_t engine = M32(wrapper);
    if (!engine || engine == 0xFFFFFF28u) return 0;
    uint32_t seen[128], count = 0, selected = 0;
    for (uint32_t p = M32(engine + 0xE4); p; p = M32(p + 8)) {
        if (p == 0xFFFFFF28u || count == 128) return 0;
        for (uint32_t i = 0; i < count; ++i) if (seen[i] == p) return 0;
        seen[count++] = p;
        if (!selected && M32(p + 0x20)) selected = p;
    }
    *valid = 1;
    return selected;
}

static const char *fe_package_in_control(void) {
    int valid;
    uint32_t package = carbon_pad_package(&valid);
    uint32_t name = package ? M32(package + 0x0C) : 0;
    return valid && name ? gptr(name) : NULL;
}

static uint32_t carbon_pad_capture_device(void) {
    uint32_t device = M32(0x00A991E0u);
    return device && M8(device + 0x183C) && M32(device + 0x1840) == 3 ? device : 0;
}

int carbon_pad_capture_controller(void) {
    uint32_t device = carbon_pad_capture_device();
    return device ? (int)M32(device + 0x1844) : -1;
}

int carbon_pad_context(void) {
    if (carbon_pad_capture_device()) return CARBON_PAD_CAPTURE;
    if (M32(0x00A99BBCu) != 6) return CARBON_PAD_MENU;
    uint32_t sim = M32(0x00B4CFE0u);
    if (!sim || M32(sim + 0x24) != 3) return CARBON_PAD_MENU;
    int valid;
    uint32_t package = carbon_pad_package(&valid);
    if (!valid) return CARBON_PAD_MENU;
    if (!package) return CARBON_PAD_DRIVING;
    uint32_t name = M32(package + 0x0C);
    if (!name) return CARBON_PAD_MENU;
    const char *text = gptr(name);
    return !strcmp(text, "HUD_SingleRace.fng") || !strcmp(text, "HUD_Player1.fng") ||
           !strcmp(text, "HUD_Player2.fng") ? CARBON_PAD_DRIVING : CARBON_PAD_MENU;
}
