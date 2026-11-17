/* Port-authored positions over the PC action directory, not console recipes.
 * Both layouts use separate analog pedals and right-stick vertical shifting.
 * PlayStation: R1 handbrake, L1 nitrous, R3 speedbreaker, Circle look back,
 * Select reset, Triangle crew. L3 supplies the PC camera action.
 * Xbox: A handbrake, B nitrous, X speedbreaker, right-stick click look back,
 * LB reset, RB camera, Y crew. Start pauses in either layout.
 * The host delivers the same physical position numbers for every pad kind.
 * Menu positions follow the existing family prompts: Cross/A accepts,
 * Triangle/B cancels, Circle/Y is the auxiliary face action.
 */
enum { PORT_SOUTH, PORT_EAST, PORT_WEST, PORT_NORTH, PORT_LB, PORT_RB,
       PORT_BACK, PORT_START, PORT_LCLICK, PORT_RCLICK };
enum { PORT_X_AXIS, PORT_Y_AXIS, PORT_PEDAL_AXIS };
enum { PORT_DPAD_UP, PORT_DPAD_RIGHT, PORT_DPAD_DOWN, PORT_DPAD_LEFT };
#define PORT_UNBOUND {0,0}
typedef struct {
    unsigned action;
    PadBinding playstation, xbox, alternate;
} PortPadPosition;
static const PortPadPosition port_driving[] = {
    {0, {PB_ROT_HI,PORT_PEDAL_AXIS}, {PB_ROT_HI,PORT_PEDAL_AXIS}, PORT_UNBOUND},       /* accelerator */
    {1, {PB_AXIS_HI,PORT_PEDAL_AXIS}, {PB_AXIS_HI,PORT_PEDAL_AXIS}, PORT_UNBOUND},     /* brake/reverse */
    {2, {PB_AXIS_LO,PORT_X_AXIS}, {PB_AXIS_LO,PORT_X_AXIS}, PORT_UNBOUND},     /* steer left */
    {3, {PB_AXIS_HI,PORT_X_AXIS}, {PB_AXIS_HI,PORT_X_AXIS}, PORT_UNBOUND},     /* steer right */
    {4, {PB_BUTTON,PORT_RB}, {PB_BUTTON,PORT_SOUTH}, PORT_UNBOUND},       /* handbrake */
    {5, {PB_BUTTON,PORT_RCLICK}, {PB_BUTTON,PORT_WEST}, PORT_UNBOUND},       /* speedbreaker */
    {6, {PB_BUTTON,PORT_LB}, {PB_BUTTON,PORT_EAST}, PORT_UNBOUND},       /* nitrous */
    {7, {PB_ROT_HI,PORT_Y_AXIS}, {PB_ROT_HI,PORT_Y_AXIS}, PORT_UNBOUND},      /* shift down */
    {8, {PB_ROT_LO,PORT_Y_AXIS}, {PB_ROT_LO,PORT_Y_AXIS}, PORT_UNBOUND},      /* shift up */
    {18, {PB_BUTTON,PORT_BACK}, {PB_BUTTON,PORT_LB}, PORT_UNBOUND},      /* reset */
    {19, {PB_BUTTON,PORT_NORTH}, {PB_BUTTON,PORT_NORTH}, PORT_UNBOUND},      /* crew */
    {20, {PB_POV,PORT_DPAD_UP}, {PB_POV,PORT_DPAD_UP}, PORT_UNBOUND},           /* engage event */
    {21, {PB_POV,PORT_DPAD_LEFT}, {PB_POV,PORT_DPAD_LEFT}, PORT_UNBOUND},           /* world map */
    {22, {PB_POV,PORT_DPAD_RIGHT}, {PB_POV,PORT_DPAD_RIGHT}, PORT_UNBOUND},           /* messages */
    {24, {PB_BUTTON,PORT_LCLICK}, {PB_BUTTON,PORT_RB}, PORT_UNBOUND},      /* camera */
    {25, {PB_BUTTON,PORT_EAST}, {PB_BUTTON,PORT_RCLICK}, PORT_UNBOUND},      /* look back */
    {28, {PB_BUTTON,PORT_START}, {PB_BUTTON,PORT_START}, PORT_UNBOUND},      /* pause */
    {47, {PB_BUTTON,PORT_SOUTH}, {PB_BUTTON,PORT_SOUTH}, PORT_UNBOUND}       /* skip sequence */
};
static const PortPadPosition menu[] = {
    {29, {PB_AXIS_LO,PORT_X_AXIS}, {PB_AXIS_LO,PORT_X_AXIS}, {PB_POV,PORT_DPAD_LEFT}},
    {30, {PB_AXIS_HI,PORT_X_AXIS}, {PB_AXIS_HI,PORT_X_AXIS}, {PB_POV,PORT_DPAD_RIGHT}},
    {31, {PB_AXIS_LO,PORT_Y_AXIS}, {PB_AXIS_LO,PORT_Y_AXIS}, {PB_POV,PORT_DPAD_UP}},
    {32, {PB_AXIS_HI,PORT_Y_AXIS}, {PB_AXIS_HI,PORT_Y_AXIS}, {PB_POV,PORT_DPAD_DOWN}},
    {33, {PB_ROT_LO,PORT_X_AXIS}, {PB_ROT_LO,PORT_X_AXIS}, PORT_UNBOUND},
    {34, {PB_ROT_HI,PORT_X_AXIS}, {PB_ROT_HI,PORT_X_AXIS}, PORT_UNBOUND},
    {35, {PB_ROT_LO,PORT_Y_AXIS}, {PB_ROT_LO,PORT_Y_AXIS}, PORT_UNBOUND},
    {36, {PB_ROT_HI,PORT_Y_AXIS}, {PB_ROT_HI,PORT_Y_AXIS}, PORT_UNBOUND},
    {37, {PB_BUTTON,PORT_SOUTH}, {PB_BUTTON,PORT_SOUTH}, PORT_UNBOUND},       /* accept */
    {38, {PB_BUTTON,PORT_NORTH}, {PB_BUTTON,PORT_EAST}, {PB_BUTTON,PORT_BACK}}, /* cancel/back */
    {39, {PB_BUTTON,PORT_START}, {PB_BUTTON,PORT_START}, PORT_UNBOUND},       /* start */
    {40, {PB_BUTTON,PORT_LB}, {PB_BUTTON,PORT_LB}, PORT_UNBOUND},
    {41, {PB_BUTTON,PORT_RB}, {PB_BUTTON,PORT_RB}, PORT_UNBOUND},
    {42, {PB_BUTTON,PORT_BACK}, {PB_BUTTON,PORT_BACK}, PORT_UNBOUND},
    {43, {PB_BUTTON,PORT_SOUTH}, {PB_BUTTON,PORT_SOUTH}, PORT_UNBOUND},
    {23, {PB_BUTTON,PORT_EAST}, {PB_BUTTON,PORT_NORTH}, PORT_UNBOUND},
    {44, {PB_BUTTON,PORT_RCLICK}, {PB_BUTTON,PORT_RCLICK}, PORT_UNBOUND},
    {45, {PB_BUTTON,PORT_WEST}, {PB_BUTTON,PORT_WEST}, PORT_UNBOUND},
    {46, {PB_BUTTON,PORT_EAST}, {PB_BUTTON,PORT_NORTH}, PORT_UNBOUND}
};
static PadAction carbon_padbind_port_row(unsigned pad, unsigned action,
                                        const PortPadPosition *positions, unsigned count) {
    PadAction row = {action,PORT_UNBOUND,PORT_UNBOUND,0};
    for (unsigned i = 0; i < count; ++i) if (positions[i].action == action) {
        row.primary = carbon_pad_layout_resolve(pad).layout == CARBON_LAYOUT_XBOX ?
                      positions[i].xbox : positions[i].playstation;
        row.secondary = positions[i].alternate;
        break;
    }
    return row;
}
static int carbon_padbind_port_has(unsigned action) {
    for (unsigned i = 0; i < sizeof port_driving / sizeof *port_driving; ++i)
        if (port_driving[i].action == action) return 1;
    return 0;
}
static PadAction carbon_padbind_selected(unsigned pad, unsigned config, unsigned action) {
    (void)config;
    return carbon_padbind_port_row(pad, action, port_driving, sizeof port_driving / sizeof *port_driving);
}
static PadAction carbon_padbind_menu(unsigned pad, unsigned action) {
    return carbon_padbind_port_row(pad, action, menu, sizeof menu / sizeof *menu);
}
static float carbon_padbind_menu_value(unsigned pad, unsigned action, unsigned slot, float value) {
    (void)pad; (void)action; (void)slot;
    return value;
}
static float carbon_padbind_xbox_edge(unsigned pad, unsigned action, float value, unsigned config) {
    (void)pad; (void)action; (void)config;
    return value;
}
