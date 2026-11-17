uint32_t extras = 0;
if (kind_native(kind)) {
    GCControllerButtonInput *lp = nil, *rp = nil;
    if (kind == PAD_KIND_EDGE) if (@available(macOS 13.0, *)) {
        lp = ctl.physicalInputProfile.buttons[GCInputLeftPaddle];
        rp = ctl.physicalInputProfile.buttons[GCInputRightPaddle];
    }
    extras = (home.pressed ? 1u << P_PS : 0) | (touch.pressed ? 1u << P_TOUCHPAD : 0) |
             (lp.pressed ? 1u << P_LPADDLE : 0) | (rp.pressed ? 1u << P_RPADDLE : 0);
    extras &= idx == 0 ? pad_game_extras(touch != nil) : 0xF000u;
}
int x = right - left, y = up - down;
static const int angles[3][3] = {{22500, 27000, 31500}, {18000, -1, 0}, {13500, 9000, 4500}};
st->pov = angles[x + 1][y + 1];
carbon_pad_deliver(idx, st, phys | extras);
