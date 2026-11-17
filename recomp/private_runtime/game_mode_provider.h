/* Six persistent indices: do not sort them when the display changes. */
static uint32_t carbon_modes[6][2] = {
    {640,480}, {1280,720}, {1920,1080}, {2560,1440}, {3840,2160}, {1600,900}
};
static void carbon_modes_init(void) {
    static int initialized;
    if (initialized) return;
    int w = 0, h = 0;
    user32_display_pixels(&w, &h);
    if (w >= 640 && w <= 8192 && h >= 480 && h <= 4096) {
        carbon_modes[5][0] = (uint32_t)w;
        carbon_modes[5][1] = (uint32_t)h;
    }
    initialized = 1;
}
void widescreen_mode(int i, uint32_t *w, uint32_t *h) {
    *w = 0;
    *h = 0;
    if (i < 0 || i >= 6) return;
    carbon_modes_init();
    *w = carbon_modes[i][0];
    *h = carbon_modes[i][1];
}
static void carbon_modes_publish(void) {
    carbon_modes_init();
    for (unsigned i = 0; i < 6; ++i) {
        M32(0x00A63E28u + 4*i) = carbon_modes[i][0];
        M32(0x00A63E40u + 4*i) = carbon_modes[i][1];
    }
}
static unsigned carbon_mode_index(void) {
    unsigned i = M32(0x00A65388u);
    if (i >= 6) { i = 0; M32(0x00A65388u) = i; }
    return i;
}
int carbon_aa_levels(void);
#include "game_first_resolution.h"
/* The file-backed registry exposes one game-key handle per userdata profile.
 * Bind native load/save to that handle, as F10's boot_reg_set_dword does. */
void carbon_display_registry_key(Cpu *c, void (*original)(Cpu *)) {
    original(c);
    static uint32_t key;
    if (!key) key = gstr("Software\\EA Games\\Need for Speed Most Wanted");
    c->eax = key;
}
void carbon_display_load(Cpu *c, void (*original)(Cpu *)) {
    /* Startup classified this launch before writing its in-progress registry
     * marker. Loading that marker must not trigger hardware defaults again. */
    uint32_t first = M32(0x00A6538Cu);
    original(c);
    M32(0x00A6538Cu) = first;
}
void carbon_mode_enumerate(Cpu *c, void (*original)(Cpu *)) {
    carbon_modes_publish();
    original(c);
    carbon_first_mode(c);
    M32(0x00A653E4u) = (uint32_t)carbon_aa_levels();
}
void carbon_mode_validate(Cpu *c, void (*original)(Cpu *)) {
    carbon_mode_index();
    original(c);
    carbon_mode_index();
}
void carbon_mode_read(Cpu *c, void (*original)(Cpu *)) {
    uint32_t w = M32(c->esp + 4), h = M32(c->esp + 8);
    unsigned i = carbon_mode_index();
    carbon_modes_init();
    original(c);
    M32(w) = carbon_modes[i][0];
    M32(h) = carbon_modes[i][1];
}
/* Draw retains native navigation; its FEString receives the actual dimensions. */
void carbon_mode_label(Cpu *c, void (*original)(Cpu *)) {
    uint32_t self = c->ecx;
    original(c);
    uint32_t label = M32(self + 0x1C);
    if (!label) return;
    unsigned i = carbon_mode_index();
    uint32_t w, h;
    widescreen_mode((int)i, &w, &h);
    extern int private_carbon_resolution_active(void);
    extern void private_carbon_resolution_write(uint32_t, uint32_t);
    if (private_carbon_resolution_active()) {
        uint32_t scratch = c->esp - 32;
        private_carbon_resolution_write(scratch, scratch + 4);
        w = M32(scratch); h = M32(scratch + 4);
    }
    char text[48];
    snprintf(text, sizeof text, "%u x %u", w, h);
    static uint32_t buffer;
    if (!buffer) buffer = galloc(2 * sizeof text);
    /* 00583B10 takes UTF-16, including for numeric resolution labels. */
    for (unsigned k = 0; k <= strlen(text); ++k) M16(buffer + 2*k) = (uint8_t)text[k];
    Cpu draw = *c;
    uint32_t args[] = {label, buffer};
    call_guest(&draw, 0x00583B10u, 2, args);
}
