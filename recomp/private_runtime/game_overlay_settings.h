/* Included by the explicit private settings initialization, never a constructor. */
{
    static const char *const choices[] = {"Off", "Compact", "Full"};
    static Setting row = {
        .id="display.overlay", .category=SET_DISPLAY, .order=40,
        .label="Performance overlay",
        .help="Frame rate and timing; Full adds the graph, memory, render, audio and controller details.",
        .type=SET_CHOICE, .choices=choices, .nchoices=3,
        .env="NFS_OVERLAY", .pref="overlay", .own_pref=1,
        .apply=overlay_set_level, .get=overlay_level
    };
    settings_add(&row);
}
