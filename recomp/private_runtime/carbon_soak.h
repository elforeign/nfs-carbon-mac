#include <math.h>

/* 00434FC0 -> 0042B530 registers AIWingman objects in AA269C/AA26A4.
 * 0040CA10 tests +6C == 2 (active); 0041AC30 changes 1 -> 2 only when
 * ready +74 is set. Observe those native transitions without invoking them. */
static void carbon_soak_crew(void) {
    uint32_t list = M32(0x00AA269Cu), count = M32(0x00AA26A4u);
    static uint32_t previous[8][5];
    if (!list || count > 8) return;
    for (unsigned i = 0; i < count; ++i) {
        uint32_t obj = M32(list + 4 * i), vt = obj ? M32(obj) : 0;
        if (!vt || M32(vt + 0x14) != 0x0040CA10u ||
            M32(vt + 0x1C) != 0x0040CA20u) continue;
        uint32_t state[] = {obj, M32(obj + 8), M32(obj + 0x6C),
                            M32(obj + 0x70), M8(obj + 0x74)};
        if (memcmp(previous[i], state, sizeof state)) {
            memcpy(previous[i], state, sizeof state);
            diag_event("soak: crew ability=%08x vehicle=%08x state=%u role=%u ready=%u",
                       state[0], state[1], state[2], state[3], state[4]);
        }
    }
}

/* The mode table holds final results. Autodrive may still continue the first
 * canyon leg, whose results package has the same name as final results. */
int carbon_soak_hold_results(void) {
    if (!diag_on) return 0;
    const char *event = getenv("NFS_CARBON_SKIPFE_EVENT"), *keys = getenv("BOOT_KEYS");
    if (!event || !*event || !keys || strncmp(keys, "seq:soak:", 9)) return 0;
    uint32_t r = M32(0x00A98284u), e = r ? M32(r + 0x6A1C) : 0;
    uint32_t a = e ? M32(e + 4) : 0;
    uint32_t result = r ? M32(r + 0xBCE4) : 0;
    return a && (M8(a + 0x2B) != 13 || M8(r + 0xBCBA) == 0 ||
                 result == 2 || result == 4 || result == 5);
}

/* Read-only screen observer shared by package and soak sequence dispatch. */
static void carbon_soak_screen(void) {
    if (!diag_on) return;
    carbon_soak_crew();
    /* 006136A0/0063E120 read the cloned event's attributes. A phase of 3
     * without an event is also the free-roam reset, not boss evidence. */
    uint32_t r = M32(0x00A98284u), e = r ? M32(r + 0x6A1C) : 0;
    uint32_t a = e ? M32(e + 4) : 0;
    uint32_t state[] = {
        r ? M32(r + 0x6A18) : ~0u, e,
        a ? (uint32_t)(int32_t)(int8_t)M8(a + 0x2B) : ~0u,
        a ? !!(M32(a + 0x18) & 0x20) : 0,
        r ? M32(r + 0x6A14) : 0, r ? M8(r + 0xBCBA) : 0,
        r ? M32(r + 0xBCE4) : 0, e ? M8(e + 0x1F) : 0,
        M32(0x00AA26A4u)
    };
    static uint32_t last_state[sizeof state / sizeof *state];
    static int mode_seen;
    if (!mode_seen || memcmp(last_state, state, sizeof state)) {
        memcpy(last_state, state, sizeof state); mode_seen = 1;
        diag_event("soak: mode phase=%u event=%08x attrs=%08x kind=%d boss=%u started=%u stage=%u result=%u clone=%u abilities=%u",
                   state[0], e, a, (int32_t)state[2], state[3], state[4],
                   state[5], state[6], state[7], state[8]);
    }
    static char previous[128];
    static int seen;
    const char *name = carbon_script_package_in_control();
    if (!name || !*name) name = "none";
    if (!seen || strcmp(previous, name)) {
        snprintf(previous, sizeof previous, "%s", name);
        seen = 1;
        diag_event("screen: %s", previous);
    }
}

/* INIS is the cinematic object's +40 interface (0076D72A). 00763300
 * completes playback when 0045D740's elapsed +20 reaches 0045D750's
 * length +28, then enters state 7 and notifies its native listener.
 * Read that clock, never the merely advancing render-frame counter. */
static uint32_t carbon_soak_boss_cinematic(float *elapsed, float *length) {
    uint32_t r = M32(0x00A98284u), e = r ? M32(r + 0x6A1C) : 0;
    uint32_t a = e ? M32(e + 4) : 0, nis = M32(0x00B4D964u);
    if (!a || M8(a + 0x2B) != 13 || !(M32(a + 0x18) & 0x20) ||
        !nis || M32(nis) != 0x009EC6E8u) return 0;
    uint32_t track = M32(nis + 0x390);
    if (!track || M32(track) != 0x009C5FE0u) return 0;
    memcpy(elapsed, G + track + 0x20, sizeof *elapsed);
    memcpy(length, G + track + 0x28, sizeof *length);
    if (!isfinite(*elapsed) || !isfinite(*length) || *elapsed < 0 ||
        *length <= 0 || M32(nis + 0x2E0) != 5) return 0;
    return track;
}

typedef struct {
    char screen[128], key[16];
    uint64_t delay, repeat;
} CarbonSoakRow;

static int carbon_soak_error(const char *reason) {
    fprintf(stderr, "soak: error %s; input stopped\n", reason);
    if (diag_on) diag_event("soak: error %s; input stopped", reason);
    return -1;
}

static int carbon_soak_key_valid(const char *key) {
    const char *words[] = {"-", "RETURN", "ESCAPE", "SPACE", "BACK", "UP", "DOWN",
                          "LEFT", "RIGHT", "F6", "F7", "F8", "F10", "TAB", "RCTRL"};
    for (unsigned i = 0; i < sizeof words / sizeof *words; ++i)
        if (!strcmp(key, words[i])) return 1;
    return strlen(key) == 1 && ((key[0] >= 'A' && key[0] <= 'Z') ||
                               (key[0] >= '0' && key[0] <= '9'));
}

/* Terminal sequence step. All memory read by the observer belongs to the
 * retail reader; the route owns host state and ordinary key events only.
 * A '-' key explicitly permits an idle screen; repeat 0 means once/appearance. */
static int carbon_soak_tick(const char *file, uint64_t tick, const char **key) {
    static CarbonSoakRow rows[128];
    static unsigned count;
    static int loaded, strict, fired, unknown_logged;
    static char previous[128];
    static uint64_t since, last_key, idle_since, cinematic_log;
    static uint32_t cinematic_track;
    static float cinematic_elapsed;
    static int cinematic_seen;
    *key = NULL;
    if (!loaded) {
        loaded = 1;
        const char *v = getenv("BOOT_KEYS_STRICT");
        strict = v && !strcmp(v, "1");
        FILE *f = fopen(file, "r");
        if (!f) return carbon_soak_error("cannot open table");
        char line[512];
        int bad = 0;
        while (fgets(line, sizeof line, f)) {
            if (line[0] == '#' || line[0] == '\n' || line[0] == '\r') continue;
            size_t n = strlen(line);
            if (!n || (line[n - 1] != '\n' && !feof(f))) { bad = 1; break; }
            while (n && (line[n - 1] == '\n' || line[n - 1] == '\r')) line[--n] = 0;
            char *field[4] = {line};
            for (int i = 1; i < 4; ++i) {
                char *tab = strchr(field[i - 1], '\t');
                if (!tab) { bad = 1; break; }
                *tab = 0; field[i] = tab + 1;
            }
            if (bad || count == 128 || !*field[0] || strlen(field[0]) >= sizeof rows[0].screen ||
                !carbon_soak_key_valid(field[1])) { bad = 1; break; }
            uint64_t values[2];
            for (int i = 0; i < 2; ++i) {
                char *end;
                if (!*field[i + 2] || strspn(field[i + 2], "0123456789") != strlen(field[i + 2]) ||
                    strlen(field[i + 2]) > 9) { bad = 1; break; }
                values[i] = strtoull(field[i + 2], &end, 10);
                if (*end) { bad = 1; break; }
            }
            if (bad) break;
            for (unsigned i = 0; i < count; ++i)
                if (!strcmp(rows[i].screen, field[0])) bad = 1;
            if (bad) break;
            snprintf(rows[count].screen, sizeof rows[count].screen, "%s", field[0]);
            snprintf(rows[count].key, sizeof rows[count].key, "%s", field[1]);
            rows[count].delay = values[0]; rows[count].repeat = values[1];
            ++count;
        }
        if (ferror(f)) bad = 1;
        fclose(f);
        if (bad || !count) return carbon_soak_error("invalid table");
        if (diag_on) diag_event("soak: table loaded rows=%u", count);
    }
    const char *name = carbon_script_package_in_control();
    if (!name || !*name) name = "none";
    if (!previous[0] || strcmp(previous, name)) {
        snprintf(previous, sizeof previous, "%s", name);
        since = tick; fired = unknown_logged = 0;
        idle_since = tick;
        cinematic_track = 0; cinematic_elapsed = 0; cinematic_log = 0; cinematic_seen = 0;
    }
    int subtitler = !strcmp(name, "FESubtitler.fng");
    if (subtitler && tick - since < 5400) {
        float elapsed = 0, length = 0;
        uint32_t track = carbon_soak_boss_cinematic(&elapsed, &length);
        if (track) cinematic_seen = 1;
        if (track && track == cinematic_track && elapsed > cinematic_elapsed)
            idle_since = tick;
        cinematic_track = track; cinematic_elapsed = elapsed;
        if (track && (!cinematic_log || tick - cinematic_log >= 60)) {
            cinematic_log = tick;
            if (diag_on) diag_event("soak: cinematic track=%08x elapsed=%.3f length=%.3f", track, elapsed, length);
        }
    }
    /* Tick is the script's 60 Hz wall clock. No package means driving;
     * menus (including allowed '-' rows) must make progress or end cleanly. */
    if (strcmp(name, "none") && (tick - idle_since >= 1200 ||
                                (subtitler && cinematic_seen && tick - since >= 5400))) {
        fprintf(stderr, "soak: idle %s\n", name);
        if (diag_on) diag_event("soak: idle %s", name);
        [NSApp terminate:nil];
        return -1;
    }
    const CarbonSoakRow *row = NULL;
    for (unsigned i = 0; i < count; ++i)
        if (!strcmp(rows[i].screen, name)) { row = &rows[i]; break; }
    if (!row) {
        if (tick - since >= 1800 && !unknown_logged) {
            unknown_logged = 1;
            const char *tail = strict ? "; input stopped; run ends" : "";
            fprintf(stderr, "soak: unknown screen %s%s\n", name, tail);
            if (diag_on) diag_event("soak: unknown screen %s%s", name, tail);
            if (strict) [NSApp terminate:nil];   // same clean quit as the script's livequit step
        }
        return unknown_logged && strict ? -1 : 0;
    }
    /* Both racing and free roam have no controlling package. 00647720 sets
     * GRaceStatus +6A14 when a race starts; 00641310 resets it for free roam.
     * +6A08 can retain the finished race's racers, so keep that guard too.
     * The simulation must be active (not loading, paused or in a cinematic). */
    int map = !strcmp(name, "none") && !strcmp(row->key, "M");
    uint32_t race = M32(0x00A98284u), sm = M32(0x00B4CFE0u);
    if (map && (M32(0x00A99BBCu) != 6 || !sm || M32(sm + 0x24) != 3 ||
                M32(0x00B4D964u) || !race || M32(race + 0x6A14) ||
                M32(race + 0x6A08) || M32(race + 0x6A18) != 3)) {
        since = tick; fired = 0;
        return 0;
    }
    if (!strcmp(row->key, "-") || tick - since < row->delay ||
        (fired && (!row->repeat || tick - last_key < row->repeat))) return 0;
    last_key = tick; fired = 1;
    idle_since = tick;
    *key = row->key;
    if (diag_on) {
        if (map) {
            /* 005D502F -> 004A8B00 (mode/event/phase), 00673F50 (race type),
             * 005A0D90 -> 004C5860 (pause/NIS). Snapshot only; never open a map
             * or alter the native gate on the script's behalf. */
            uint32_t gm = M32(0x00A982B8u), event = M32(race + 0x6A1C);
            uint32_t attrs = event ? M32(event + 4) : 0;
            uint32_t pursuit = M32(0x00A9E874u);
            uint32_t hud = M32(0x00A97DE4u); /* 005E502E publishes FEngHud. */
            diag_event("soak: key %s screen=%s ticks=%llu mode=%u race_phase=%u event=%08x attrs=%08x flags=%08x kind=%d pause=%u pause_state=%08x nis=%08x pursuits=%u hud=%08x mask=%08x,%08x",
                       *key, name, (unsigned long long)(tick - since),
                       gm ? M32(gm + 0x118) : ~0u, M32(race + 0x6A18), event, attrs,
                       attrs ? M32(attrs + 0x18) : 0, attrs ? (int)(int8_t)M8(attrs + 0x2B) : -1,
                       M32(0x00A8AD18u), M32(0x00A97BD8u), M32(0x00B4D964u),
                       pursuit >= 0x4C ? M32(pursuit - 0x4C + 0x148) : 0,
                       hud, hud ? M32(hud + 0x20) : 0, hud ? M32(hud + 0x24) : 0);
        } else diag_event("soak: key %s screen=%s ticks=%llu", *key, name,
                          (unsigned long long)(tick - since));
    }
    return 0;
}
