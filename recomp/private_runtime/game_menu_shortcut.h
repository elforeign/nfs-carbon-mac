/* A missing menu-choice row keeps this image's existing automatic shortcut. */
static inline int carbon_menu_shortcut_choice(int choice) { return choice < 0 ? 0 : choice; }

static GuideShortcutResult carbon_addons_host_guide_shortcut(GuideShortcut *state, double now,
        uint32_t physical, int home, int touch, int has_touchpad, int choice, int enabled, int menu_open) {
    return guide_shortcut(state, now, physical, home, touch, has_touchpad,
                          carbon_menu_shortcut_choice(choice), enabled, menu_open);
}
#define guide_shortcut carbon_addons_host_guide_shortcut
