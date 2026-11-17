/* A missing menu-choice row keeps this image's existing automatic shortcut. */
static GuideShortcutResult carbon_addons_host_guide_shortcut(GuideShortcut *state, double now,
        uint32_t physical, int home, int touch, int has_touchpad, int choice, int enabled, int menu_open) {
    return guide_shortcut(state, now, physical, home, touch, has_touchpad,
                          choice < 0 ? 0 : choice, enabled, menu_open);
}
#define guide_shortcut carbon_addons_host_guide_shortcut
