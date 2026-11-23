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
static int carbon_padbind_settings_read[16];
static uint32_t carbon_padbind_saved_name[16];
static uint32_t carbon_padbind_name_hash(const char *name) {
    uint32_t hash = 0xFFFFFFFFu;
    for (const unsigned char *s = (const unsigned char *)name; *s; ++s) {
        int value = (int8_t)*s; /* Native bStringHashUpper sign-extends each byte. */
        if (value >= 'a' && value <= 'z') value -= 'a' - 'A';
        hash = 33u * hash + (uint32_t)value;
    }
    return hash;
}
/* The guest caches the enumeration-time name. Use a known live identity, or
 * the saved identity of the single virtual slot until detection completes. */
void carbon_padbind_hash(Cpu *c, void (*original)(Cpu *)) {
    unsigned pad = arg(c,1);
    if (arg(c,0) == 3 && pad < 16) {
        char name[64] = {0};
        int kind = pad_identity_n((int)pad,name,sizeof name);
        uint32_t hash = kind != PAD_KIND_NONE && name[0] ?
                        carbon_padbind_name_hash(name) : carbon_padbind_saved_name[pad];
        if (hash) { c->eax = hash; c->esp += 12; return; }
    }
    original(c);
}
static unsigned carbon_padbind_read_int(Cpu *c, unsigned parser) {
    c->ecx = parser;
    return call_guest(c,0x00475F90u,0,NULL);
}
/* Native admission (including its controller-name hash check) stays authoritative.
 * Once it has read the profile, first device detection must not replace its rows. */
void carbon_padbind_read(Cpu *c, void (*original)(Cpu *)) {
    unsigned count = M32(0x00A98948u), parser = arg(c,0);
    memset(carbon_padbind_saved_name,0,sizeof carbon_padbind_saved_name);
    if (count == 1 && pad_identity_n(0,NULL,0) == PAD_KIND_NONE) {
        /* Native stream: two properties, four integers per keyboard row,
         * controller count, then each controller's name hash and rows. Only
         * an unambiguous single saved pad may supply an as-yet unknown name. */
        Cpu scan = *c; scan.esp -= 32;
        uint32_t args[] = {1,0xFFFFFFFFu};
        unsigned keys = call_guest(&scan,0x006924F0u,2,args);
        unsigned cursor = M32(parser+0x160), tokens = M32(parser+0x154);
        if (keys <= 72 && cursor <= tokens && tokens-cursor >= 4+4*keys) {
            for (unsigned i = 0; i < 2+4*keys; ++i) carbon_padbind_read_int(&scan,parser);
            unsigned saved = carbon_padbind_read_int(&scan,parser);
            uint32_t hash = carbon_padbind_read_int(&scan,parser);
            /* Known port identities only; foreign devices retain native admission. */
            if (saved == 1 && (hash == carbon_padbind_name_hash("Controller (DualSense)") ||
                hash == carbon_padbind_name_hash("Controller (DualShock 4)") ||
                hash == carbon_padbind_name_hash("Controller (DualSense Edge)") ||
                hash == carbon_padbind_name_hash("Controller (XBOX 360 For Windows)")))
                carbon_padbind_saved_name[0] = hash;
            M32(parser+0x160) = cursor;
        }
    }
    original(c);
    if (count > 16) return;
    for (unsigned p = 0; p < count; ++p) carbon_padbind_settings_read[p] = 1;
}
static void carbon_padbind_seeded(unsigned pad) {
    CarbonPadLayoutChoice choice = carbon_pad_layout_resolve(pad);
    carbon_padbind_last[pad] = choice.layout; carbon_padbind_kind[pad] = choice.kind;
    carbon_padbind_seen[pad] = 1;
    carbon_padbind_settings_read[pad] = 0;
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
        /* A different device arriving in the saved slot still gets defaults. */
        int different = 0;
        if (carbon_padbind_kind[p] == PAD_KIND_NONE && choice.kind != PAD_KIND_NONE &&
            carbon_padbind_saved_name[p]) {
            char name[64] = {0};
            pad_identity_n((int)p,name,sizeof name);
            different = name[0] && carbon_padbind_name_hash(name) != carbon_padbind_saved_name[p];
        }
        /* A kind change within one layout changes prompts, not native bindings. */
        if (!different && carbon_padbind_last[p] == (int)choice.layout) {
            if (carbon_padbind_kind[p] != choice.kind) carbon_padbind_seeded(p);
            continue;
        }
        /* Automatic starts as Xbox while no device has been identified. The
         * saved directory/configuration wins when the first device arrives. */
        if (carbon_padbind_kind[p] == PAD_KIND_NONE && choice.kind != PAD_KIND_NONE &&
            choice.origin == CARBON_LAYOUT_AUTOMATIC && carbon_padbind_settings_read[p] && !different) {
            carbon_padbind_seeded(p);
            continue;
        }
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
