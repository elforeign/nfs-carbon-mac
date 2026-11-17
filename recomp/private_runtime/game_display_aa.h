#include "settings.h"
/* Native quality indices are 0=Off, 1=2x, 2=4x. Never expose an 8x index. */
int carbon_aa_levels(void) {
    uint32_t counts[8], n = render_msaa_levels(counts);
    if (!n || counts[0] != 2) return 0;
    return n > 1 && counts[1] == 4 ? 2 : 1;
}
int aa_game_get(void) {
    uint32_t level = M32(0x00A6537Cu), cap = (uint32_t)carbon_aa_levels();
    if (diag_on) {
        static uint32_t last_level = ~0u;
        static int last_samples;
        int samples = render_msaa_samples();
        if (level != last_level || samples != last_samples) {
            diag_event("PRIVATE CARBON AA level=%u samples=%d", level, samples);
            last_level = level; last_samples = samples;
            /* settings_dump writes cached values; F10 displays the live getter. Keep the
             * cache at the live level so later dumps (pad layout) record it too. */
            Setting *row = settings_find("graphics.antialiasing");
            if (row && diag_dir) {
                char path[1100];
                row->value = (int)(level > cap ? cap : level);
                snprintf(path, sizeof path, "%s/settings_rows.txt", diag_dir);
                settings_dump(path);
            }
        }
    }
    return (int)(level > cap ? cap : level);
}
void aa_game_apply(int level) {
    void boot_reg_set_dword(const char *, uint32_t);
    int cap = carbon_aa_levels();
    if (level < 0) level = 0;
    if (level > cap) level = cap;
    if (M32(0x00A6537Cu) == (uint32_t)level) return;
    M32(0x00A6537Cu) = (uint32_t)level;
    M32(0x00AB0AE8u) = 5; /* Native AA cycling selects the custom video preset. */
    boot_reg_set_dword("g_FSAALevel", (uint32_t)level);
    boot_reg_set_dword("g_PerformanceLevel", 5);
    M8(0x00AB0B25u) = 1;
}
void carbon_aa_cycle(Cpu *c, void (*original)(Cpu *)) {
    M32(0x00A653E4u) = (uint32_t)carbon_aa_levels();
    original(c);
}
void carbon_aa_present(Cpu *c, void (*original)(Cpu *)) {
    uint32_t cap = (uint32_t)carbon_aa_levels();
    if (M32(0x00A6537Cu) > cap) M32(0x00A6537Cu) = cap;
    original(c);
}
void carbon_aa_label(Cpu *c, void (*original)(Cpu *)) {
    uint32_t self = c->ecx;
    original(c);
    if (M32(self + 0x74) != 0x13CDu) return;
    uint32_t label = M32(self + 0x1C);
    if (!label) return;
    static uint32_t labels[3];
    static const uint16_t text[3][4] = {{'O','f','f',0}, {'2','x',0,0}, {'4','x',0,0}};
    if (!labels[0]) for (unsigned i = 0; i < 3; ++i) {
        labels[i] = galloc(sizeof text[i]);
        memcpy(G + labels[i], text[i], sizeof text[i]);
    }
    uint32_t args[] = {label, labels[aa_game_get()]};
    Cpu draw = *c;
    call_guest(&draw, 0x00583B10u, 2, args);
}
