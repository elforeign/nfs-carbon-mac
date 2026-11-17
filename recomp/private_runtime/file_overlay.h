/* Exact read-only region pairs and optional packs. Paths/descriptors never enter guest memory. */
static const char *private_track_names[] = {
    "TRACKS/L5RA.BUN", "TRACKS/STREAML5RA.BUN",
    "TRACKS/L2RA.BUN", "TRACKS/STREAML2RA.BUN",
    "TRACKS/L2RA/MINI_MAP_CASINOTOWN_LOCKED.bin",
    "TRACKS/L2RA/MINI_MAP_CASINOTOWN_UNLOCKED.bin",
    "TRACKS/L5RA/MINI_MAP_CASINOTOWN_LOCKED.bin",
    "TRACKS/L5RA/MINI_MAP_CASINOTOWN_UNLOCKED.bin",
    "TRACKS/L5RA/TrackMaps.bin", "TRACKS/L2RA/TrackMaps.bin",
    "GLOBAL/GAMEPLAY.BIN", "GLOBAL/GAMEPLAY.LZC",
    "GLOBAL/GLOBALB.BUN", "GLOBAL/GLOBALB.LZC",
    "GLOBAL/ATTRIBUTES.BIN"
};
static char private_track_paths[15][4096];
static unsigned private_track_enabled;

void private_track_overlay_init(void) {
    const char *root = getenv("NFS_CARBON_TRACK_OVERLAY");
    private_track_enabled = 0;
    if (!root || !*root) return;
    for (unsigned pair = 0; pair < 8; ++pair) {
        const char *mode = getenv("NFS_CARBON_MINIMAP");
        if (pair == 4 && (!mode || strcmp(mode, "atlas"))) continue;
        unsigned present = 0, mask = 0;
        for (unsigned i = pair * 2; i < pair * 2 + 2 && i < 15; ++i) {
            char *path = private_track_paths[i];
            int len = snprintf(path, sizeof private_track_paths[i], "%s/%s", root, private_track_names[i]);
            if (len < 0 || len >= (int)sizeof private_track_paths[i]) {
                fprintf(stderr, "NFS_CARBON_TRACK_OVERLAY: path too long for %s\n", private_track_names[i]);
                exit(2);
            }
            struct stat st;
            if (lstat(path, &st)) {
                if (errno == ENOENT) continue;
            } else {
                /* Nonblocking open makes a mistaken FIFO fail promptly. */
                int fd = open(path, O_RDONLY | O_NONBLOCK | O_CLOEXEC);
                int ok = fd >= 0 && !fstat(fd, &st) && S_ISREG(st.st_mode);
                if (fd >= 0) close(fd);
                if (ok) { ++present; mask |= 1u << i; continue; }
            }
            fprintf(stderr, "NFS_CARBON_TRACK_OVERLAY: readable regular pair required; invalid %s\n", path);
            exit(2);
        }
        if (!present) continue;
        /* Startup and streaming companions must describe one pack, including
         * the frontend package shared by GLOBALB.BUN and GLOBALB.LZC. */
        if ((pair < 2 || (pair >= 5 && pair < 7)) && present != 2) {
            fprintf(stderr, "NFS_CARBON_TRACK_OVERLAY: readable regular pair required: %s + %s\n",
                    private_track_names[pair * 2], private_track_names[pair * 2 + 1]);
            exit(2);
        }
        private_track_enabled |= mask;
    }
    if (!(private_track_enabled & 15u)) {
        fprintf(stderr, "NFS_CARBON_TRACK_OVERLAY: readable regular pair required; no complete region pair\n");
        exit(2);
    }
    fprintf(stderr, "NFS_CARBON_TRACK_OVERLAY: enabled %s pairs=%u\n", root, private_track_enabled);
}

/* resolve() handled drive/module prefixes, separators and case. Match the
 * complete path under game_dir, never a basename or a save path. */
static int private_track_overlay_path(char *host, size_t n, uint32_t access, uint32_t disp) {
    int carbon_gin_path(char *, size_t, uint32_t, uint32_t);
    int gin = carbon_gin_path(host, n, access, disp);
    if (gin < 0) { file_error(); return -1; }
    if (gin) return 0;
    if (!private_track_enabled) return 0;
    size_t root_len = strlen(game_dir);
    while (root_len && game_dir[root_len - 1] == '/') --root_len;
    if (strncmp(host, game_dir, root_len) || host[root_len] != '/') return 0;
    const char *rel = host + root_len + 1;
    while (*rel == '/') ++rel;
    for (unsigned i = 0; i < 15; ++i) {
        if (!(private_track_enabled & (1u << i))) continue;
        if (strcasecmp(rel, private_track_names[i])) continue;
        if ((access & 0x40000000u) || disp != 3 || file_flags(access, disp) != O_RDONLY) {
            errno = EACCES;
            file_error();
            return -1;
        }
        if (strlen(private_track_paths[i]) >= n) {
            errno = ENAMETOOLONG;
            file_error();
            return -1;
        }
        strcpy(host, private_track_paths[i]);
        return (int)i + 1;
    }
    return 0;
}
