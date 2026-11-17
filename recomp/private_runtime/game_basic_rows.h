/* Explicit startup registration; the presentation policy is shared. */
void app_restart_game(int);
static void private_basic_presentation_apply(int value) {
    (void)value;
    RenderPresentation presentation;
    render_presentation_stats(&presentation);
}
static void private_basic_rows_init(void) {
    static Setting restart = {
        .id="diag.restart_game", .category=SET_DISPLAY, .order=50,
        .label="Restart game", .type=SET_ACTION,
        .help="Saves settings and restarts after a second press within 4 seconds, losing race progress since the last save.",
        .apply=app_restart_game
    };
    static Setting vrr = {
        .id="graphics.variable_refresh", .category=SET_DISPLAY, .order=30,
        .label="Variable refresh pacing",
        .help="Asks macOS for adaptive refresh pacing when the display and a full screen window support it; availability is recorded in session logs.",
        .type=SET_TOGGLE, .env="NFS_VRR", .apply=private_basic_presentation_apply
    };
    settings_add(&restart);
    settings_add(&vrr);
}
