/* The local report actions use the shared capture and writer. */
void report_save_async(const char *, const char *);
const char *report_last_path(void);
void portmenu_open_folder(const char *);
static Setting h_report = {.id = "diag.h_report", .category = SET_DIAGNOSTICS, .order = 30, .label = "Report a problem", .type = SET_HEADING,
    .help = "Saves a local folder with a game-frame screenshot, recent stats, the log and settings. Saving sends nothing; public posting requires a separate review and explicit consent."};
static const char *const kCat[] = {"Audio", "Graphics", "Controls", "Gameplay", "Crash / freeze", "Other"};
static const char *const kCatV[] = {"Audio", "Graphics", "Controls", "Gameplay", "Crash-freeze", "Other"};
static Setting s_cat = {.id = "diag.report_category", .category = SET_DIAGNOSTICS, .order = 40, .label = "What's wrong",
    .help = "Pick the kind of problem; it goes on the report's first lines.", .type = SET_CHOICE, .choices = kCat, .values = kCatV,
    .nchoices = (sizeof kCat / sizeof *kCat), .def = 5, .pref = ""};
static Setting s_note = {.id = "diag.report_note", .category = SET_DIAGNOSTICS, .order = 50, .label = "Note", .type = SET_TEXT,
    .help = "Select to type up to 256 characters. Controller: hold Circle to delete, R3 clears all. Keyboard: Cmd+Backspace clears all."};
static void report_save(int v) {
    (void)v;
    Setting *c = settings_find("diag.report_category");
    report_save_async(c ? kCatV[c->get ? c->get() : c->value] : "Other", settings_text("diag.report_note"));
}
static void report_saved_text(char *buf, int n) {
    const char *p = report_last_path(), *slash = p ? strstr(p, "/reports/") : NULL;
    snprintf(buf, (size_t)n, "%s", slash ? slash + 1 : "");
}
static Setting s_save = {.id = "diag.report_save", .category = SET_DIAGNOSTICS, .order = 60, .label = "Save report", .type = SET_ACTION,
    .help = "Writes a local folder in reports/ with the saved game frame, recent stats/events, log and settings. Review text before sending; screenshot sharing starts Off and requires viewing the saved frame.",
    .apply = report_save, .value_text = report_saved_text};
static void open_reports(int v) {
    (void)v;
    char dir[1100];
    snprintf(dir, sizeof dir, "%s/reports", userdata_dir());
    portmenu_open_folder(dir);
}
static Setting s_open = {.id = "diag.report_open", .category = SET_DIAGNOSTICS, .order = 70, .label = "Show reports in Finder", .type = SET_ACTION,
    .help = "Opens the reports folder.", .apply = open_reports};

static void private_report_settings_init(void) {
    settings_add(&h_report); settings_add(&s_cat); settings_add(&s_note);
    settings_add(&s_save); settings_add(&s_open);
}
