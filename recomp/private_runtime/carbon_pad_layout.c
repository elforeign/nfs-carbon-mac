#include "host.h"
#include "carbon_pad_layout.h"
#include "settings.h"
#include <strings.h>
#include <stdlib.h>
#include <stdatomic.h>


/* Resolved by ordinary controller/prompt paths, never by recorder sampling. */
static _Atomic int observed_layout;
int carbon_pad_layout_observed(void) { return atomic_load_explicit(&observed_layout,memory_order_relaxed); }
static const char *const tokens[] = {"playstation", "xbox", "pc"};
static const char *const names[] = {"PlayStation", "Xbox", "PC"};
int carbon_pad_layout_parse(const char *token) {
    if (token && *token) for (int i = 0; i < 3; ++i)
        if (!strcasecmp(token, tokens[i])) return i;
    return -1;
}
const char *carbon_pad_layout_name(CarbonPadLayout layout) { return names[layout]; }
const char *carbon_pad_layout_origin(CarbonPadLayoutOrigin origin) {
    static const char *const origins[] = {"automatic", "app", "environment"};
    return origins[origin];
}
CarbonPadLayoutChoice carbon_pad_layout_resolve(unsigned pad) {
    int kind = pad_identity_n((int)pad, NULL, 0);
    CarbonPadLayoutChoice choice = {
        kind == PAD_KIND_DUALSENSE || kind == PAD_KIND_DUALSHOCK4 || kind == PAD_KIND_EDGE ?
        CARBON_LAYOUT_PLAYSTATION : CARBON_LAYOUT_XBOX, CARBON_LAYOUT_AUTOMATIC, kind};
    const char *saved = app_pref("pad_layout"), *env = getenv("NFS_PAD_LAYOUT");
    int value = carbon_pad_layout_parse(env), preference = carbon_pad_layout_parse(saved);
    if (preference >= 0) { choice.layout = preference; choice.origin = CARBON_LAYOUT_APP; }
    if (value >= 0) { choice.layout = value; choice.origin = CARBON_LAYOUT_ENV; }
    if (!pad) atomic_store_explicit(&observed_layout,choice.layout+1,memory_order_relaxed);
    Setting *row = settings_find("controls.pad_layout");
    if (!pad && row) row->value = choice.layout;
    if (diag_on) {
        static int last[16], initialized[16];
        int stamp = choice.layout + 4 * choice.origin + 16 * kind;
        if (pad < 16 && (!initialized[pad] || last[pad] != stamp)) {
            initialized[pad] = 1; last[pad] = stamp;
            diag_event("pad layout=%s origin=%s pad=%u identity=%d variant=native-profile (custom edits reseeded on switch)",
                       names[choice.layout], carbon_pad_layout_origin(choice.origin), pad, kind);
            if (!pad && diag_dir && row) {
                char path[1100]; snprintf(path,sizeof path,"%s/settings_rows.txt",diag_dir); settings_dump(path);
            }
            if (env && *env && value < 0) diag_event("pad layout: invalid environment token '%s'; using next source", env);
            if (saved && *saved && preference < 0) diag_event("pad layout: invalid app token '%s'; using automatic", saved);
        }
    }
    return choice;
}
int carbon_pad_layout_get(void) { return carbon_pad_layout_resolve(0).layout; }
void carbon_pad_layout_set(int value) {
    if (value >= 0 && value < 3) app_pref_set("pad_layout", tokens[value]);
}
void carbon_pad_layout_reset(void) { app_pref_set("pad_layout", ""); }
void carbon_pad_layout_reason(char *buffer, int size) {
    CarbonPadLayoutChoice c = carbon_pad_layout_resolve(0);
    snprintf(buffer, (size_t)size, "%s: %s",
             c.origin == CARBON_LAYOUT_AUTOMATIC ? "Automatic" : carbon_pad_layout_origin(c.origin), names[c.layout]);
}
