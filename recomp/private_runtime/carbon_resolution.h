/* Hash-bound private mode override. Retail startup owns all size consumers. */
static uint32_t private_carbon_width, private_carbon_height;

static void private_carbon_resolution_setup(void) {
    const char *value = getenv("NFS_CARBON_RES");
    if (!value || !*value) return;
    if (!PRIVATE_CARBON_SKIPFE) {
        fprintf(stderr, "NFS_CARBON_RES: unsupported private image\n");
        exit(2);
    }
    uint32_t size[2] = {0, 0};
    const unsigned char *p = (const unsigned char *)value;
    /* Bounds match the runtime's advertised MaxTextureWidth/Height. */
    const uint32_t limit[2] = {8192, 4096};
    for (unsigned i = 0; i < 2; ++i) {
        if (*p < '0' || *p > '9') goto invalid;
        do {
            unsigned digit = *p++ - '0';
            if (size[i] > (limit[i] - digit) / 10) goto invalid;
            size[i] = size[i] * 10 + digit;
        } while (*p >= '0' && *p <= '9');
        if (!size[i] || (i == 0 ? *p++ != 'x' : *p != 0)) goto invalid;
    }
    private_carbon_width = size[0];
    private_carbon_height = size[1];
    fprintf(stderr, "PRIVATE CARBON RES %ux%u reader=00712AC0\n", size[0], size[1]);
    return;
invalid:
    fprintf(stderr, "NFS_CARBON_RES: expected decimal WIDTHxHEIGHT (1..8192 x 1..4096)\n");
    exit(2);
}

int private_carbon_resolution_active(void) { return private_carbon_width != 0; }
void private_carbon_resolution_write(uint32_t width, uint32_t height) {
    M32(width) = private_carbon_width;
    M32(height) = private_carbon_height;
}

/* BOOT_DIAG evidence only: loaded FEng package, chosen animation label, and
 * the retail widescreen option (0x13be). Never select a different package. */
void private_carbon_resolution_evidence(unsigned kind, uint32_t key, uint32_t result,
                                        uint32_t caller) {
    if (!diag_on) return;
    if (kind == 1) {
        static uint32_t seen[64]; static unsigned count;
        if (!result || !key || count == 64) return;
        for (unsigned i = 0; i < count; ++i) if (seen[i] == key) return;
        seen[count++] = key;
        diag_event("PRIVATE CARBON FE package=%.*s resource=%08x caller=%08x", 120, G + key, result, caller);
    } else if (kind == 2) {
        if (key != 0x009D4B68 && key != 0x009D4B78 && key != 0x009D4B8C && key != 0x009D4B98) return;
        static unsigned count;
        if (count++ < 12) diag_event("PRIVATE CARBON FE label=%.*s hash=%08x caller=%08x", 32, G + key, result, caller);
    } else if (kind == 3) {
        static unsigned count;
        if (count++ < 12) diag_event("PRIVATE CARBON FE widescreen_option=%u caller=%08x", M32(key), caller);
    }
}
