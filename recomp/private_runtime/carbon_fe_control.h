/* Retail control-order walk: wrapper 00A97A78 -> engine, +E4 head,
 * package +8 next, +20 control, +0C name. 00591480 scans this order;
 * 00597180 uses the first controlling package's name. No guest writes. */
static const char *carbon_script_package_in_control(void) {
    uint32_t wrapper = M32(0x00A97A78u);
    if (!wrapper || wrapper == 0xFFFFFF28u) return NULL;
    uint32_t engine = M32(wrapper);
    if (!engine || engine == 0xFFFFFF28u) return NULL;
    /* A bounded walk also stops corrupt cyclic lists during transitions. */
    uint32_t p = M32(engine + 0xE4);
    for (unsigned count = 0; p && count < 128; ++count, p = M32(p + 8)) {
        if (p == 0xFFFFFF28u) return NULL;
        if (M32(p + 0x20)) {
            uint32_t name = M32(p + 0x0C);
            return name ? gptr(name) : NULL;
        }
    }
    return NULL;
}

/* 005C5330 consumes pending +10 as UTF-16 and frees the pending object.
 * Copy that native label before calling the original. The host copy is only
 * diagnostic evidence for this dialog's later control/key samples. */
static char carbon_script_dialog_text[4096] = "UNPROVEN";
static unsigned carbon_script_dialog_epoch;

void carbon_script_dialog_init(Cpu *c, void (*original)(Cpu *)) {
    if (diag_on) {
        uint32_t pending = M32(0x00A97B18u);
        uint32_t label = pending >= 0x1000 && pending < 0xFFFFFF00u ? M32(pending + 0x10) : 0;
        unsigned length = 0;
        if (label >= 0x1000 && label < 0xFFFFF000u)
            while (length < 1024 && M16(label + 2 * length)) ++length;
        snprintf(carbon_script_dialog_text, sizeof carbon_script_dialog_text, "%s", "UNPROVEN");
        if (length && length < 1024) {
            NSString *s = [NSString stringWithCharacters:(const unichar *)gptr(label) length:length];
            s = [[s stringByReplacingOccurrencesOfString:@"\r" withString:@"\\r"]
                    stringByReplacingOccurrencesOfString:@"\n" withString:@"\\n"];
            if (s && ![s getCString:carbon_script_dialog_text maxLength:sizeof carbon_script_dialog_text encoding:NSUTF8StringEncoding])
                snprintf(carbon_script_dialog_text, sizeof carbon_script_dialog_text, "%s", "UNPROVEN");
        }
        ++carbon_script_dialog_epoch;
        diag_event("dialog: text=%s", carbon_script_dialog_text);
    }
    original(c);
}

static void carbon_script_dialog_witness(int force) {
    if (!diag_on) return;
    static unsigned seen_epoch;
    static int was_dialog;
    const char *name = carbon_script_package_in_control();
    if (!name || strcasecmp(name, "FeDialog.fng")) { was_dialog = 0; return; }
    if (force || !was_dialog || seen_epoch != carbon_script_dialog_epoch) {
        diag_event("dialog: text=%s", carbon_script_dialog_text);
        seen_epoch = carbon_script_dialog_epoch;
        was_dialog = 1;
    }
}

static void carbon_script_key_witness(void) {
    if (!diag_on) return;
    const char *name = carbon_script_package_in_control();
    diag_event("screen: %s", name && *name ? name : "none");
    carbon_script_dialog_witness(1);
}
