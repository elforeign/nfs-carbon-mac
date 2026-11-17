#include "host.h"
#include <strings.h>

/* The stock type table has 95 inline directory names at stride 0xD0.
 * The native loader uses the first string, not the display name at +0x10. */
static int carbon_fix_model_probe(Cpu *c, uint32_t type) {
    char path[128];
    uint32_t table = M32(0x00B74CCCu);
    int n = snprintf(path, sizeof path, "CARS\\%s\\TEXTURES.BIN", gptr(table + type * 0xD0u));
    if (n < 0 || (size_t)n >= sizeof path) return 1;
    /* A private CPU and a bounded buffer below the live stack preserve the
     * caller's registers and arguments. The native probe is a cdecl call. */
    Cpu probe = *c;
    probe.esp -= sizeof path;
    uint32_t buffer = probe.esp;
    unsigned char saved[sizeof path];
    memcpy(saved, G + buffer, sizeof saved);
    memcpy(G + buffer, path, (size_t)n + 1);
    uint32_t args[] = {buffer};
    int present = call_guest(&probe, 0x006B2360u, 1, args) != 0;
    memcpy(G + buffer, saved, sizeof saved);
    return present;
}

void carbon_fix_model_load(Cpu *c, void (*original)(Cpu *)) {
    uint32_t ride = arg(c, 0), type = M32(ride);
    if (carbon_fix_model_probe(c, type)) {
        original(c);
        return;
    }
    uint32_t table = M32(0x00B74CCCu), replacement = 95;
    for (uint32_t i = 0; i < 95; ++i) {
        if (!strcasecmp(gptr(table + i * 0xD0u), "viper")) {
            replacement = i;
            break;
        }
    }
    if (replacement < 95 && carbon_fix_model_probe(c, replacement)) {
        static int reported;
        if (!reported) {
            fprintf(stderr, "CARBON missing car textures: using stock Viper\n");
            reported = 1;
        }
        M32(ride) = replacement;
        original(c);
        M32(ride) = type;
    } else {
        /* No usable stock model: preserve the native failure. */
        original(c);
    }
}
