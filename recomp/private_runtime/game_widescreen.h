/* Native wide output. The retail wide option (13BE) follows the output aspect, so
 * the game's own wide HUD layout, chyron/package modes and loading screens run.
 * Front-end geometry is laid out in 640x480 units; at a wider output it is drawn
 * with kx = (4/3)/aspect, ky = 1, and the cursor uses the inverse mapping.
 * A 4:3 (or narrower) output keeps the retail behavior exactly. */
static unsigned carbon_mode_index(void);
int carbon_fe_scope;                      /* an IDI_FE_FX / IDI_FE_MASK_FX pass is open */
static void carbon_output_size(uint32_t *w, uint32_t *h) {
    *w = M32(0x00AB06FCu);                /* present parameters filled by 00710100 */
    *h = M32(0x00AB0700u);
    if (*w && *h) return;
    widescreen_mode((int)carbon_mode_index(), w, h);
}
/* kx for an output of w x h: 1 at 4:3 or narrower. */
static float carbon_wide_kx(uint32_t w, uint32_t h) {
    if (!w || !h || (float)w * 3.0f <= (float)h * 4.0f * 1.001f) return 1.0f;
    return (4.0f / 3.0f) * (float)h / (float)w;
}
/* The wide race packages occupy 853 1/3 x 480 units. A notch panel is
 * narrower than 16:9: fit that whole layer, keeping the camera strip clear.
 * Existing layouts remain unchanged with notch fill Off. */
static int carbon_notch_hud_fit(uint32_t w, uint32_t h) {
    return user32_notch_fill() && M32(0x00A99BBCu) == 6 && w && h &&
           w * 3u > h * 4u && w * 9u < h * 16u;
}
float carbon_fe_kx(void) {
    uint32_t w, h;
    carbon_output_size(&w, &h);
    if (carbon_notch_hud_fit(w, h)) return 0.75f;
    return carbon_wide_kx(w, h);
}
float carbon_fe_ky(void) {
    uint32_t w, h;
    carbon_output_size(&w, &h);
    return carbon_notch_hud_fit(w, h) ? 0.5625f * (float)w / (float)h : 1.0f;
}
/* The chyron object broadcasts its mode only when it is built (005B69F0); after
 * an aspect change, send the same native message to the same package list. */
static void carbon_wide_resend(Cpu *c, int wide) {
    uint32_t manager = M32(0x00A97A78u);
    if (!manager) return;
    uint32_t object = M32(manager);
    if (!(object + 0xD8u)) return;
    int fe = M32(0x00A99BBCu) == 3;
    uint32_t text = fe ? (wide ? 0x009D4B98u : 0x009D4B8Cu)    /* WIDESCREEN_MODE / NORMAL_MODE */
                       : (wide ? 0x009D4B78u : 0x009D4B68u);   /* WIDESCREEN_MODEHUD / NORMAL_MODEHUD */
    Cpu call = *c;
    uint32_t hash = call_guest(&call, 0x005EA6A0u, 1, &text);
    for (uint32_t package = M32(object + 0xE0u); package; package = M32(package + 4)) {
        uint32_t args[5] = {hash, 0, package, 0xFFFFFFFCu, 0};
        call = *c;
        call.ecx = M32(manager);
        call_guest(&call, 0x005F2960u, 5, args);
    }
}
/* 004A4770: stdcall getter of option 13BE, [esp+4] receives the value. */
void carbon_wide_option(Cpu *c, void (*original)(Cpu *)) {
    static int last = -1, sending;
    uint32_t out = M32(c->esp + 4);
    original(c);
    int wide = carbon_fe_kx() < 1.0f;
    M32(out) = (uint32_t)wide;
    if (wide == last || sending) return;
    int changed = last >= 0;
    last = wide;
    if (!changed) return;
    sending = 1;
    carbon_wide_resend(c, wide);
    sending = 0;
}
/* 00731580 (ECX): +4/+8 current, +C/+10 previous (copied from current first),
 * +14/+18 delta, in 640x480 units over the whole window. */
void carbon_wide_cursor(Cpu *c, void (*original)(Cpu *)) {
    uint32_t self = c->ecx;
    original(c);
    float kx = carbon_fe_kx();
    if (kx >= 1.0f) return;
    float v = (float)((int32_t)M32(self + 4) - 320) / kx;
    int32_t x = 320 + (int32_t)(v >= 0 ? v + 0.5f : v - 0.5f);
    M32(self + 4) = (uint32_t)x;
    M32(self + 0x14) = (uint32_t)(x - (int32_t)M32(self + 0xC));
    float ky = carbon_fe_ky();
    if (ky < 1.0f) {
        v = (float)((int32_t)M32(self + 8) - 240) / ky;
        int32_t y = 240 + (int32_t)(v >= 0 ? v + 0.5f : v - 0.5f);
        M32(self + 8) = (uint32_t)y;
        M32(self + 0x18) = (uint32_t)(y - (int32_t)M32(self + 0x10));
    }
}
