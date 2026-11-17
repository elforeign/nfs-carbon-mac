extern int aa_game_get(void), carbon_aa_levels(void);
extern void aa_game_apply(int);
static const char *const aa_choices[] = {"Off", "2x", "4x"};
static Setting aa = {.id="graphics.antialiasing", .category=SET_PICTURE, .order=15,
    .label="Anti-aliasing", .help="The game's Video options setting. Applies with a display reset.",
    .type=SET_CHOICE, .choices=aa_choices, .nchoices=3, .def=0, .pref="",
    .get=aa_game_get, .apply=aa_game_apply};
aa.nchoices = carbon_aa_levels() + 1;
settings_add(&aa);
