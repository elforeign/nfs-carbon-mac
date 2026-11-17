static const char *const layout_choices[] = {"PlayStation", "Xbox", "PC"};
static const char *const layout_values[] = {"playstation", "xbox", "pc"};
static Setting layout = {.id="controls.pad_layout", .category=SET_CONTROLS, .order=20,
    .label="Button layout", .help="PlayStation / Xbox / native PC bindings. Automatic follows the active pad; Reset returns to Automatic.",
    .type=SET_CHOICE, .choices=layout_choices, .values=layout_values, .nchoices=3,
    .pref="pad_layout", .own_pref=1, .get=carbon_pad_layout_get, .apply=carbon_pad_layout_set};
static Setting reason = {.id="controls.pad_layout_reason", .category=SET_CONTROLS, .order=21,
    .label="Layout source", .type=SET_INFO, .pref="", .value_text=carbon_pad_layout_reason};
/* Own the override parser: invalid environment values fall through to app/auto. */
layout.def = layout.value = carbon_pad_layout_get();
settings_add(&layout);
layout.value = carbon_pad_layout_get();
settings_add(&reason);
carbon_pad_layout_menu_init();
