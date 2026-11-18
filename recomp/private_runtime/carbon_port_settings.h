/* Port additions only; native Video and Audio retain their own preferences. */
#include "settings.h"
void portmenu_status(const char *, ...);

static const char *const carbon_port_bool[] = {"0", "1"};
static const char *const carbon_port_switch[] = {"off", "on"};
static const char *const carbon_port_modes[] = {"Game", "Cycle", "Fixed"};
static const char *const carbon_port_mode_values[] = {"game", "cycle", "fixed"};
static const char *const carbon_port_layouts[] = {"Game", "ITU"};
static const char *const carbon_port_layout_values[] = {"game", "itu"};
static const char *const carbon_port_presets[] = {"Port (recommended)", "PC retail", "My picks"};
static const char *const carbon_port_preset_values[] = {"port", "pc", "mine"};
static const int carbon_port_preset_map[] = {PRESET_PORT, PRESET_PC, PRESET_MINE};

static int carbon_port_preset_get(void) {
    int state = settings_look_state();
    return state == PRESET_PORT ? 0 : state == PRESET_PC ? 1 : 2;
}
static void carbon_port_preset_apply(int value) {
    int pending = settings_look_apply(carbon_port_preset_map[value]);
    if (pending < 0) portmenu_status("No saved picks yet: change a graphics row first.");
    else if (!pending) portmenu_status("Look applied.");
    else {
        static const char *const ids[] = {"graphics.daynight"};
        char names[256] = "";
        for (unsigned i=0; i<sizeof ids/sizeof *ids; ++i) {
            Setting *s=settings_find(ids[i]);
            if (!s || !s->restart || s->value==s->boot_value) continue;
            size_t n=strlen(names);
            snprintf(names+n,sizeof names-n,"%s%s",n?", ":"",s->label);
        }
        portmenu_status("Restart game: %s.", names);
    }
}

void carbon_ao_set(int), private_carbon_limiter_set(int), carbon_audio_surround_set(int), padfx_set_triggers(int);
int carbon_audio_surround_get(void);
void carbon_envcube_apply(int);
void carbon_devrows_crew(int), carbon_devrows_nitrous(int), carbon_devrows_speedbreaker(int);
static const char *const carbon_port_maps[] = {"Off", "Rockport", "Atlas"};
static const char *const carbon_port_map_values[] = {"off", "rockport", "atlas"};

static Setting carbon_port_rows[] = {
    {.id="gameplay.traffic_density", .category=SET_GAMEPLAY, .order=10, .label="Traffic density (-1: game)",
     .help="Ambient traffic 0-100%; -1 keeps the game's density. Scripted traffic is unchanged. A startup traffic switch keeps its original direct-start behavior.",
     .type=SET_SLIDER, .min=-1, .max=100, .step=1, .def=-1, .format="%d%%",
     .env="NFS_CARBON_SKIPFE_TRAFFIC", .own_pref=1},
    {.id="gameplay.cheat_nitrous", .category=SET_GAMEPLAY, .order=20, .label="Unlimited nitrous",
     .help="Uses the retail cheat, including its special-state restrictions. On and Off apply now; normal refill rules resume when Off.",
     .type=SET_TOGGLE, .apply=carbon_devrows_nitrous},
    {.id="gameplay.cheat_speedbreaker", .category=SET_GAMEPLAY, .order=21, .label="Unlimited Speedbreaker",
     .help="Uses the retail cheat, including its special-state restrictions. On and Off apply now; normal refill rules resume when Off.",
     .type=SET_TOGGLE, .apply=carbon_devrows_speedbreaker},
    {.id="gameplay.cheat_crew", .category=SET_GAMEPLAY, .order=22, .label="Crew always ready",
     .help="Uses the retail cheat, including its special-state restrictions. On and Off apply now; normal refill rules resume when Off.",
     .type=SET_TOGGLE, .apply=carbon_devrows_crew},
    {.id="world.carbon_minimap", .category=SET_WORLD, .order=10, .label="Rockport minimap / world map",
     .help="Rockport uses the imported region's map; Atlas covers both regions and expands panning. Requires imported content. Restart to apply.",
     .type=SET_CHOICE, .choices=carbon_port_maps, .values=carbon_port_map_values, .nchoices=3,
     .env="NFS_CARBON_MINIMAP", .restart=1},
    {.id="audio.carbon_surround", .category=SET_AUDIO, .order=5, .label="Surround",
     .help="Select native Stereo or Surround now. Speaker layout is a separate startup choice.",
     .type=SET_TOGGLE, .values=carbon_port_bool, .def=1, .env="NFS_CARBON_SURROUND",
     .pref="", .get=carbon_audio_surround_get, .apply=carbon_audio_surround_set},
    {.id="graphics.look_preset", .category=SET_PICTURE, .order=10, .label="Look preset",
     .help="Port restores the shipped graphics defaults. PC retail disables port graphics additions. My picks restores your choices. Live rows apply now; remaining rows show a restart notice.",
     .type=SET_CHOICE, .choices=carbon_port_presets, .values=carbon_port_preset_values, .nchoices=3,
     .pref="", .own_pref=1, .derived=1, .get=carbon_port_preset_get, .apply=carbon_port_preset_apply},
    {.id="graphics.carbon_coat", .category=SET_PICTURE, .order=30, .label="Car lacquer",
     .help="Layered paint reflections. Physical materials also require lacquer. Applies now.",
     .type=SET_TOGGLE, .values=carbon_port_bool, .def=1, .env="NFS_CARBON_COAT", .live_env=1, .apply=carbon_envcube_apply},
    {.id="graphics.carbon_materials", .category=SET_PICTURE, .order=40, .label="Physical materials",
     .help="Chrome, wheels and glass; requires Car lacquer. Applies now.",
     .type=SET_TOGGLE, .values=carbon_port_bool, .def=1, .env="NFS_CARBON_MATERIALS", .live_env=1},
    {.id="graphics.carbon_ao", .category=SET_PICTURE, .order=50, .label="Contact shadows",
     .help="Ambient contact shading; applies now.",
     .type=SET_TOGGLE, .values=carbon_port_switch, .def=0, .env="NFS_CARBON_AO", .apply=carbon_ao_set},
    {.id="graphics.carbon_envcube", .category=SET_PICTURE, .order=60, .label="Sharper reflections",
     .help="Higher resolution car reflection captures. Applies now.",
     .type=SET_TOGGLE, .values=carbon_port_bool, .env="NFS_CARBON_ENVCUBE", .live_env=1, .apply=carbon_envcube_apply},
    {.id="graphics.carbon_reflect_hdr", .category=SET_PICTURE, .order=65, .label="Real reflections",
     .help="Street lamps show in the car paint; needs Car lacquer. Applies now.",
     .type=SET_TOGGLE, .values=carbon_port_bool, .def=1, .env="NFS_CARBON_REFLECT_HDR", .live_env=1, .apply=carbon_envcube_apply},
    {.id="graphics.daynight", .category=SET_PICTURE, .order=70, .label="Day-night lighting",
     .help="Enable the daylight clock, sky, fog, car lighting and lamps. Restart to apply.",
     .type=SET_TOGGLE, .values=carbon_port_switch, .env="NFS_DAYNIGHT", .restart=1},
    {.id="graphics.daynight_mode", .category=SET_PICTURE, .order=80, .label="Day-night mode",
     .help="Game follows progress; Cycle advances in free roam; Fixed uses the hour below. Requires Day-night lighting; applies now.",
     .type=SET_CHOICE, .choices=carbon_port_modes, .values=carbon_port_mode_values, .nchoices=3,
     .env="NFS_DAYNIGHT_MODE", .live_env=1},
    {.id="graphics.daynight_hour", .category=SET_PICTURE, .order=90, .label="Fixed hour",
     .help="Hour of day for Fixed mode (24 is midnight). Requires Day-night lighting; applies now.",
     .type=SET_SLIDER, .min=0, .max=24, .step=1, .def=12, .format="%d:00",
     .env="NFS_DAYNIGHT_HOUR", .live_env=1},
    {.id="audio.carbon_limiter", .category=SET_AUDIO, .order=10, .label="Peak limiter",
     .help="Limit stereo and surround peaks before clipping. Native Audio selects stereo or surround. Applies now.",
     .type=SET_TOGGLE, .values=carbon_port_bool, .def=1, .env="NFS_CARBON_LIMITER", .apply=private_carbon_limiter_set},
    {.id="audio.carbon_pos_layout", .category=SET_AUDIO, .order=20, .label="Speaker layout",
     .help="Game keeps native geometry. ITU uses home 5.1 speaker angles; select Surround in native Audio. Restart to apply.",
     .type=SET_CHOICE, .choices=carbon_port_layouts, .values=carbon_port_layout_values, .nchoices=2,
     .env="NFS_CARBON_POS_LAYOUT", .restart=1},
    {.id="controls.adaptive_triggers", .category=SET_CONTROLS, .order=20, .label="Adaptive triggers",
     .help="Trigger resistance on supported controllers. Rumble keeps its own setting. Applies now.",
     .type=SET_TOGGLE, .values=carbon_port_switch, .def=1, .env="NFS_PAD_TRIGGERS", .apply=padfx_set_triggers},
};

static void carbon_port_settings_init(void) {
    for (unsigned i=0; i<sizeof carbon_port_rows/sizeof *carbon_port_rows; ++i)
        settings_add(&carbon_port_rows[i]);
}
