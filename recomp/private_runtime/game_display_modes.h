static const uint32_t modes[][2] = {{640, 480}, {800, 600}, {1024, 768}, {1280, 720}, {1280, 960}, {1280, 1024}, {1360, 768},
                                    {1600, 900}, {1600, 1200}, {1920, 1080}, {1920, 1200}, {2560, 1440}, {3840,2160}};
// The adapter's modes: the common ones above plus widescreen.c's six slots (which follow the display), so the game
// finds every slot it offers among them.
static uint32_t adapter_modes[sizeof modes / sizeof *modes + 6][2], nmodes_;
static uint32_t nmodes(void) {
    if (!nmodes_) {
        for (unsigned i = 0; i < sizeof modes / sizeof *modes; ++i) { adapter_modes[nmodes_][0] = modes[i][0]; adapter_modes[nmodes_++][1] = modes[i][1]; }
        for (int s = 0; s < 6; ++s) {
            uint32_t w, h, k = 0;
            widescreen_mode(s, &w, &h);
            while (k < nmodes_ && (adapter_modes[k][0] != w || adapter_modes[k][1] != h)) ++k;
            if (w && k == nmodes_) { adapter_modes[nmodes_][0] = w; adapter_modes[nmodes_++][1] = h; }
        }
    }
    return nmodes_;
}
