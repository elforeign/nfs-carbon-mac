/* Old-save listing 00716690: FindFirst consumes one entry; only successful
 * FindNext calls increment MemoryCard+10. This includes dot entries. No save
 * is opened. A new Career starts the check after alias creation. Operation 7
 * enters state 20 (0059D6D0 -> 005CD247); completion
 * 0058E370 -> 005B7160 awards 2710 to property 1778 iff +10 > 0, then state E
 * shows text 84B62CBF. The native completion path owns the award and message.
 */
#include "host.h"
#include "settings.h"
#include <dirent.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>

extern int diag_on;
extern void diag_event(const char *, ...);

static void carbon_save_mw_folder(char *path, size_t size) {
    const char *test = getenv("NFS_TEST_CARBON_MW_SAVES");
    const char *base = getenv("BOOT_USERDATA");
    const char *home = getenv("HOME");
    if (test && *test) snprintf(path, size, "%s", test);
    else if (base && *base) snprintf(path, size, "%s/NFS Most Wanted", base);
    else snprintf(path, size, "%s/Library/Application Support/NFSMW-port/NFS Most Wanted", home ? home : "/tmp");
}

static uint32_t carbon_save_mw_count(const char *path) {
    DIR *dir = opendir(path);
    if (!dir) return 0;
    uint32_t count = 0;
    int first = 1;
    struct dirent *entry;
    while ((entry = readdir(dir))) {
        /* Match the shared Win32 shim's exclusion of internal save stages. */
        static const char suffix[] = ".nfs-save-";
        size_t n = strlen(entry->d_name), tail = sizeof suffix - 1 + 6;
        if (n >= tail && !memcmp(entry->d_name + n - tail, suffix, sizeof suffix - 1)) continue;
        char child[2048];
        struct stat st;
        if (snprintf(child, sizeof child, "%s/%s", path, entry->d_name) >= (int)sizeof child || stat(child, &st)) continue;
        if (first) first = 0;
        else ++count;
    }
    closedir(dir);
    return count;
}

/* Diagnostics use the same property getter as the native award, on a copied
 * CPU with scratch below the live stack; no saved profile bytes are changed. */
static uint32_t carbon_save_cash(Cpu *c) {
    Cpu read = *c;
    uint32_t out = read.esp - 16, saved = M32(out);
    M32(out) = 0;
    read.esp -= 32;
    read.ecx = 0x00A8AD30u;
    uint32_t args[] = {0x1778, out, 0xFFFFFFFFu, 0xFFFFFFFFu, 0xFFFFFFFFu};
    call_guest(&read, 0x004A0490u, 5, args);
    uint32_t value = M32(out);
    M32(out) = saved;
    return value;
}

void carbon_save_folder_list(Cpu *c, void (*original)(Cpu *)) {
    /* Underground 2 retains the original implementation and its own path. */
    if (arg(c, 0) != 0x009E8C78u) { original(c); return; }
    char path[1024];
    carbon_save_mw_folder(path, sizeof path);
    uint32_t self = c->ecx, count = carbon_save_mw_count(path);
    /* The native new-career listing/completion owns the once-only award.
     * Supply presence, never a second award, if an actual prior save is absent. */
    if (!count && settings_get("gameplay.starting_bonus") > 0) count = 1;
    uint32_t before = diag_on ? carbon_save_cash(c) : 0;
    M32(self + 0x10) += count;
    uint32_t total = M32(self + 0x10), callback = M32(M32(self) + 0x2C);
    c->ecx = self;
    uint32_t args[] = {0};
    call_guest(c, callback, 1, args);
    if (diag_on) {
        uint32_t after = carbon_save_cash(c);
        diag_event("carbon old-save folder=%s count=%u total=%u cash=%u->%u bonus=%lld callback=%08X",
                   path, count, total, before, after, (long long)after - before, callback);
    }
    c->esp += 8; /* native ret 4: return address and folder argument */
}
