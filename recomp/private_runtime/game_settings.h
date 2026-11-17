#include "host.h"
#include "settings.h"
#include "carbon_pad_layout.h"
#include "game_basic_rows.h"
#include "carbon_report_settings.h"
int user32_fullscreen(void);
void user32_toggle_fullscreen(void), user32_fullscreen_mode_changed(void);
void app_quit_game(int);
void portmenu_open_folder(const char *);
const char *log_dir(void);
extern int diag_on;
extern const char *diag_dir;
const char *render_hdr_output_status(void);
static int private_window_get(void) { return user32_fullscreen() ? 0 : 1; }
static void private_window_apply(int v) { if (private_window_get() != v) user32_toggle_fullscreen(); }
static void private_fullscreen_apply(int v) { (void)v; user32_fullscreen_mode_changed(); }
static void private_hdr_status(char *b, int n) { snprintf(b, (size_t)n, "%s", render_hdr_output_status()); }
static void private_logs_open(int v) { (void)v; portmenu_open_folder(diag_on && diag_dir ? diag_dir : log_dir()); }
static const char *const private_window_choices[]={"Full screen", "Window"}, *const private_window_values[]={"1", "0"};
static const char *const private_fullscreen_choices[]={"Borderless", "Native", "Auto"}, *const private_fullscreen_values[]={"borderless", "native", "auto"};
static const char *const private_hdr_choices[]={"Auto", "Off", "On"}, *const private_hdr_values[]={"auto", "off", "edr"};
static Setting private_rows[]={
 {.id="display.window", .category=SET_DISPLAY, .order=10, .label="Window mode", .help="Switch between a resizable window and full screen.", .type=SET_CHOICE, .choices=private_window_choices, .values=private_window_values, .nchoices=2, .env="NFS_FULLSCREEN", .pref="", .own_pref=1, .apply=private_window_apply, .get=private_window_get},
 {.id="display.fullscreen", .category=SET_DISPLAY, .order=11, .label="Full screen", .help="Borderless, a native Space, or automatic display selection.", .type=SET_CHOICE, .choices=private_fullscreen_choices, .values=private_fullscreen_values, .nchoices=3, .env="NFS_FULLSCREEN_MODE", .live_env=1, .apply=private_fullscreen_apply},
 {.id="graphics.hdr_output", .category=SET_PICTURE, .order=20, .label="HDR output", .help="Auto follows display support; On requests HDR with SDR fallback. Restart to apply.", .type=SET_CHOICE, .choices=private_hdr_choices, .values=private_hdr_values, .nchoices=3, .env="NFS_HDR_OUTPUT", .restart=1},
 {.id="graphics.hdr_status", .category=SET_PICTURE, .order=21, .label="HDR status", .help="The current shared output transport.", .type=SET_INFO, .value_text=private_hdr_status},
 {.id="diag.full_logging", .category=SET_DIAGNOSTICS, .order=90, .label="Full diagnostic logging", .help="Write detailed logs from the next launch. Restart to apply.", .type=SET_TOGGLE, .env="BOOT_DIAG", .pref="diag_logging", .own_pref=1, .restart=1},
 {.id="diag.logs_open", .category=SET_DIAGNOSTICS, .order=100, .label="Show logs in Finder", .help="Open this run's log folder.", .type=SET_ACTION, .pref="", .apply=private_logs_open},
 {.id="diag.quit_game", .category=SET_DISPLAY, .order=49, .label="Quit game", .help="Press twice within four seconds to save settings and quit.", .type=SET_ACTION, .pref="", .apply=app_quit_game},
};
#include "carbon_unlock_settings.h"
#include "carbon_port_settings.h"
void carbon_addons_gameplay_init(void);
void carbon_addons_language_init(void);
void carbon_addons_cards_init(void);
#include "carbon_addons_host_settings.h"
void private_settings_init(void) {
    for (unsigned i=0; i<sizeof private_rows/sizeof *private_rows; ++i) settings_add(&private_rows[i]);
#include "carbon_pad_layout_settings.h"
#include "game_display_settings.h"
#include "game_pacing_settings.h"
#include "game_tone_settings.h"
#include "game_overlay_settings.h"
    private_basic_rows_init();
    private_report_settings_init();
    carbon_unlock_settings_init();
    carbon_port_settings_init();
    carbon_addons_gameplay_init();
    carbon_addons_language_init();
    carbon_addons_cards_init();
    carbon_addons_host_settings_init();
}
