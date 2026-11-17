    extern void carbon_frame_limit_apply(int);
    extern int *carbon_frame_limit_choice;
    static const char *const limits[] = {"Off", "120", "60", "40"};
    static const char *const values[] = {"off", "120", "60", "40"};
    static Setting limit = {.id="graphics.frame_rate_limit", .category=SET_DISPLAY, .order=20, .label="Frame rate limit",
        .help="Caps the frames shown, live: at 120 Hz choose 120, 60 or 40 fps (at 60 Hz, 40 gives 30 fps), while the simulation keeps real time.",
        .type=SET_CHOICE, .choices=limits, .values=values, .nchoices=4, .env="NFS_FRAME_LIMIT", .apply=carbon_frame_limit_apply};
    carbon_frame_limit_choice = &limit.value;
    settings_add(&limit);
