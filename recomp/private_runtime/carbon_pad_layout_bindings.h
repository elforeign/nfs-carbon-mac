/* Selected-layout policy behind the existing binding hook seam. */
static int carbon_padbind_console(unsigned pad) {
    return carbon_pad_layout_resolve(pad).layout != CARBON_LAYOUT_PC;
}
#ifndef CARBON_PADBIND_PORT
static const XboxAction *carbon_padbind_xbox(unsigned config, int action) {
    if (!config || config > 12) config = 1;
    for (unsigned i = 0; i < 24; ++i)
        if (xbox_driving[config-1][i].action == action) return &xbox_driving[config-1][i];
    return NULL;
}
static PadAction carbon_padbind_selected(unsigned pad, unsigned config, unsigned action) {
    if (carbon_pad_layout_resolve(pad).layout != CARBON_LAYOUT_XBOX)
        return carbon_padbind_action(config, action);
    const XboxAction *x = carbon_padbind_xbox(config, (int)action);
    PadAction row = {action,{0,0},{0,0},0};
    if (x) {
        row.primary = (PadBinding){x->source[0].type,x->source[0].object};
        row.secondary = (PadBinding){x->source[1].type,x->source[1].object};
        row.low = x->source[0].low;
    }
    return row;
}
static PadAction carbon_padbind_menu(unsigned pad, unsigned action) {
    PadAction row = {action,{0,0},{0,0},0};
    if (carbon_pad_layout_resolve(pad).layout == CARBON_LAYOUT_XBOX) {
        for (unsigned i = 0; i < sizeof xbox_menu / sizeof *xbox_menu; ++i) {
            const XboxAction *x = &xbox_menu[i];
            if (x->action == (int)action) {
                row.primary = (PadBinding){x->source[0].type,x->source[0].object};
                row.secondary = (PadBinding){x->source[1].type,x->source[1].object};
                row.low = x->source[0].low;
            }
            /* The PC has one Cancel consumer: Back is its alternative source. */
            if (action == 38 && x->action == -3)
                row.secondary = (PadBinding){x->source[0].type,x->source[0].object};
        }
    } else for (unsigned i = 0; i < sizeof menu / sizeof *menu; ++i)
        if (menu[i].action == action) row = menu[i];
    return row;
}
/* PC fe applies its own .3 directional low after these logical scalars.
 * Encode each Xbox source's .4 low ahead of that stage exactly once. */
static float carbon_padbind_menu_value(unsigned pad, unsigned action, unsigned slot, float value) {
    if (carbon_pad_layout_resolve(pad).layout != CARBON_LAYOUT_XBOX || action < 29 || action > 36) return value;
    for (unsigned i = 0; i < sizeof xbox_menu / sizeof *xbox_menu; ++i) {
        const XboxAction *x = &xbox_menu[i];
        if (x->action == (int)action) {
            float low = x->source[slot].low;
            return value > low ? .3f + .7f * (value-low)/(1-low) : 0;
        }
    }
    return 0;
}
static float carbon_padbind_xbox_edge(unsigned pad, unsigned action, float value, unsigned config) {
    static float previous[16][49];
    const XboxAction *x = carbon_padbind_xbox(config, (int)action);
    unsigned mode = x ? x->source[0].mode : 0;
    float old = previous[pad][action];
    previous[pad][action] = value;
    if (mode == 1) return value > .5f && old <= .5f ? value : 0;
    if (mode == 2) return value <= .5f && old > .5f ? 1 : 0;
    return value;
}
#endif
static int carbon_padbind_last[16], carbon_padbind_kind[16], carbon_padbind_seen[16];
static unsigned carbon_padbind_remembered[16][3];
static void carbon_padbind_seeded(unsigned pad) {
    CarbonPadLayoutChoice choice = carbon_pad_layout_resolve(pad);
    carbon_padbind_last[pad] = choice.layout; carbon_padbind_kind[pad] = choice.kind;
    carbon_padbind_seen[pad] = 1;
}
static void carbon_padbind_store(Cpu *c, unsigned index, unsigned analog) {
    Cpu write = *c;
    write.ecx = 0x00A8AD30u;
    uint32_t idx[] = {0x13A9,index,0,0xFFFFFFFFu,0xFFFFFFFFu};
    uint32_t steer[] = {0x13A7,analog,0,0xFFFFFFFFu,0xFFFFFFFFu};
    call_guest(&write, 0x004A04E0u, 5, idx);
    write.ecx = 0x00A8AD30u;
    call_guest(&write, 0x004A04E0u, 5, steer);
}
/* The sixth Xbox index is valid only for Xbox. Never let a saved pair
 * select the PC's stored drive6 collection when entering native PC mode. */
static void carbon_padbind_initial_config(Cpu *c, unsigned pad) {
    if (pad) return;
    unsigned families = carbon_pad_layout_resolve(pad).layout == CARBON_LAYOUT_XBOX ? 6 : 5;
    unsigned index = carbon_padbind_property(c,0x13A9,0), analog = carbon_padbind_property(c,0x13A7,0);
    /* Before profile creation the property manager returns its unavailable sentinel. */
    if (index != 0xFFFFFFFFu && analog <= 1 && index >= families) {
        carbon_padbind_store(c,0,1);
        Cpu write = *c; write.ecx = 0x00A8AD30u;
        uint32_t dirty[] = {0x13A3,1,0,0xFFFFFFFFu,0xFFFFFFFFu};
        call_guest(&write,0x004A04E0u,5,dirty);
    }
}
static void carbon_padbind_cycle(Cpu *c, int direction) {
    unsigned families = carbon_pad_layout_resolve(0).layout == CARBON_LAYOUT_XBOX ? 6 : 5;
    unsigned number = carbon_padbind_config(c,0);
    number = (number - 1 + 2*families + direction) % (2*families);
    carbon_padbind_store(c,number % families,number < families);
}
static void carbon_padbind_sync(Cpu *c) {
    unsigned count = M32(0x00A98948u);
    if (count > 16) return;
    for (unsigned p = 0; p < count; ++p) {
        CarbonPadLayoutChoice choice = carbon_pad_layout_resolve(p);
        if (!carbon_padbind_seen[p]) { carbon_padbind_seeded(p); continue; }
        if (carbon_padbind_last[p] == (int)choice.layout && carbon_padbind_kind[p] == choice.kind) continue;
        /* Capture completes in its native state before any binding directory swap.
         * No slot is rewritten underneath a native in-flight capture. */
        if (carbon_pad_context() == CARBON_PAD_CAPTURE) continue;
        unsigned old = carbon_padbind_last[p];
        if (!p) {
            unsigned index = carbon_padbind_property(c,0x13A9,0), analog = carbon_padbind_property(c,0x13A7,0);
            unsigned families = old == CARBON_LAYOUT_XBOX ? 6 : 5;
            carbon_padbind_remembered[p][old] = index < families && analog <= 1 ? index+1+(analog?0:families) : 1;
            unsigned number = carbon_padbind_remembered[p][choice.layout];
            if (!number) number = 1;
            families = choice.layout == CARBON_LAYOUT_XBOX ? 6 : 5;
            carbon_padbind_store(c,(number-1)%families,number <= families);
        }
        carbon_padbind_seeded(p);
        Cpu defaults = *c;
        uint32_t args[] = {p};
        call_guest(&defaults,0x00689550u,1,args);
        defaults.ecx = 0x00A8AD30u;
        uint32_t dirty[] = {0x13A3,1,0,0xFFFFFFFFu,0xFFFFFFFFu};
        call_guest(&defaults,0x004A04E0u,5,dirty);
        /* These descriptor-only HUD slots are not rewritten by the PC initializer. */
        if (choice.layout == CARBON_LAYOUT_PC) for (unsigned a = 47; a <= 48; ++a)
            for (unsigned slot = 2+2*p; slot < 4+2*p; ++slot) {
                uint32_t r = carbon_padbind_record(a,slot);
                M32(r)=M32(r+4)=M32(r+8)=0;
            }
    }
}
