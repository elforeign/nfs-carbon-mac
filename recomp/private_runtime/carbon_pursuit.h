/* Opt-in scripted free-roam pursuit; native frame work always runs first. */
#include "host.h"
#include <math.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>

extern int diag_on;
extern void diag_event(const char *, ...);

static int carbon_pursuit_enabled = -1, carbon_pursuit_off, carbon_pursuit_has_heat;
static double carbon_pursuit_delay;
static float carbon_pursuit_heat;
static unsigned carbon_pursuit_attempt;
static int carbon_pursuit_seen;
static uint32_t carbon_pursuit_sim;
static uint64_t carbon_pursuit_ready, carbon_pursuit_requested, carbon_pursuit_second;

static void carbon_pursuit_config(void) {
    const char *value = getenv("NFS_CARBON_PURSUIT");
    carbon_pursuit_enabled = 0;
    if (!value || !*value) return;
    char *end;
    double delay = strtod(value, &end);
    if (end == value || !isfinite(delay) || delay < 0 || delay > 86400) return;
    if (*end == ',') {
        const char *start = end + 1;
        float heat = strtof(start, &end);
        if (end == start || !isfinite(heat) || heat < 1 || heat > 5) return;
        carbon_pursuit_heat = heat;
        carbon_pursuit_has_heat = 1;
        if (!strcmp(end, ",off")) { carbon_pursuit_off = 1; end += 4; }
    }
    if (*end) return;
    carbon_pursuit_delay = delay;
    carbon_pursuit_enabled = 1;
}

/* Same witnessed local-player reads as the native AI observer, independently.
 * 0076E810 -> 0076E740: interface-20+18 == interface-8 (simable). */
static uint32_t carbon_pursuit_player(void) {
    uint32_t list = M32(0x00A9FF5Cu), count = M32(0x00A9FF64u);
    if (!list || !count || count > 2) return 0;
    uint32_t player = M32(list), vt = player ? M32(player) : 0;
    if (player < 8 || !vt || M32(vt + 4) != 0x0076E810u) return 0;
    return M32(player - 8);
}

/* B+140 is a sentinel list: next +0, payload +8, count B+148.
 * 00435940/43/49 compare M32(M32(P+D0)+1C) with the player simable.
 * 00435A12..28 inserts the payload and increments the list count. */
static uint32_t carbon_pursuit_find(uint32_t base, uint32_t sim) {
    if (!base || !sim) return 0;
    uint32_t head = base + 0x140, count = M32(base + 0x148);
    if (count > 1024) return 0;
    uint32_t node = M32(head);
    for (unsigned i = 0; node && node != head && i < count; ++i) {
        uint32_t p = M32(node + 8), target = p ? M32(p + 0xD0) : 0;
        if (target && M32(target + 0x1C) == sim) return p;
        node = M32(node);
    }
    return 0;
}

/* Read-only equivalent of 0065C550 -> 0060CB50 -> 0060C1B0.
 * The simable's +4 points to {begin,end}; sorted 8-byte {handle,interface}
 * entries resolve IPerpetrator 004061D0. No virtual getter is called. */
static uint32_t carbon_pursuit_perp(uint32_t sim) {
    uint32_t map = sim ? M32(sim + 4) : 0;
    if (!map) return 0;
    uint32_t begin = M32(map), end = M32(map + 4);
    if (!begin || end < begin || (end - begin) % 8 || (end - begin) / 8 > 1024) return 0;
    uint32_t lo = 0, hi = (end - begin) / 8;
    while (lo < hi) {
        uint32_t mid = lo + (hi - lo) / 2;
        if (M32(begin + mid * 8) < 0x004061D0u) lo = mid + 1;
        else hi = mid;
    }
    uint32_t entry = begin + lo * 8;
    return entry < end && M32(entry) == 0x004061D0u ? M32(entry + 4) : 0;
}

static void carbon_pursuit_sample(uint32_t manager, uint32_t sim, uint64_t now) {
    uint32_t base = manager >= 0x4C ? manager - 0x4C : 0;
    uint32_t p = carbon_pursuit_find(base, sim), live = 0, unknown = 0;
    if (p) {
        uint32_t array = M32(p + 0x4C), count = M32(p + 0x54);
        if (count > 1024 || (!array && count)) unknown = count;
        else for (unsigned i = 0; i < count; ++i) {
            uint32_t v = M32(array + i * 4), vt = v ? M32(v) : 0;
            if (!vt || M32(vt + 0x9C) != 0x006D80C0u) ++unknown;
            else if (M32(v + 0xA8)) ++live; /* 006D80C0; destruction unproven. */
        }
    }
    uint32_t e = carbon_pursuit_perp(sim);
    char heat[32] = "na";
    if (e) snprintf(heat, sizeof heat, "%.3f", (double)MF32(e + 0x1C));
    /* 00572B90 player-0 profile; counters survive pursuit/sim teardown.
     * 004AC910 commits busts/evades; 004A0940 reads career cash. */
    uint32_t root = M32(0x00A97A7Cu), slot = root ? M32(root + 0xD4) : 0;
    uint32_t u = slot ? M32(slot) : 0;
    char busts[24] = "na", evades[24] = "na", cash[24] = "na";
    if (u) {
        snprintf(busts, sizeof busts, "%u", M32(u + 0x29514));
        snprintf(evades, sizeof evades, "%u", M32(u + 0x29510));
        snprintf(cash, sizeof cash, "%u", M32(u + 0x24330));
    }
    diag_event("carbon_pursuit: t=%.3f attempt=%u pursuits=%u player=%08x live=%u unknown=%u onroad=%u pool=%u heat=%s disabled=%u nonew=%u status=%u busts=%s evades=%s cash=%s",
               carbon_pursuit_attempt ? (now - carbon_pursuit_requested) / 1e9 : -1.,
               carbon_pursuit_attempt, base ? M32(base + 0x148) : 0, p, live, unknown,
               base ? M32(base + 0x90) : 0, base ? M32(base + 0xC4) : 0, heat,
               M32(0x00A83A50u), manager ? M8(manager + 0x5C) : 0,
               p ? M32(p + 0x298) : 0, busts, evades, cash);
}

static void carbon_pursuit_diag(uint32_t manager, uint32_t sim, uint64_t now) {
    if (diag_on && (!carbon_pursuit_second || now - carbon_pursuit_second >= 1000000000ull)) {
        carbon_pursuit_second = now;
        carbon_pursuit_sample(manager, sim, now);
    }
}

void carbon_pursuit_frame(Cpu *c, void (*original)(Cpu *)) {
    original(c);
    if (!carbon_pursuit_enabled) return;
    if (carbon_pursuit_enabled < 0) {
        carbon_pursuit_config();
        if (!carbon_pursuit_enabled) return;
    }
    uint64_t now = host_ticks();
    uint32_t sim = carbon_pursuit_player(), sm = M32(0x00B4CFE0u);
    uint32_t race = M32(0x00A98284u), manager = M32(0x00A9E874u);
    int ready = sim && M32(0x00A99BBCu) == 6 && sm && M32(sm + 0x24) == 3 &&
                !M32(0x00B4D964u) && race && !M32(race + 0x6A14) &&
                M32(race + 0x6A18) == 3 && manager;
    if (!ready || sim != carbon_pursuit_sim) carbon_pursuit_ready = 0;
    carbon_pursuit_sim = sim;
    if (!ready) {
        if (carbon_pursuit_attempt) carbon_pursuit_diag(manager, sim, now);
        return;
    }
    if (!carbon_pursuit_ready) carbon_pursuit_ready = now;
    if (carbon_pursuit_attempt && carbon_pursuit_find(manager - 0x4C, sim)) carbon_pursuit_seen = 1;
    int request = !carbon_pursuit_attempt &&
                  (now - carbon_pursuit_ready) / 1e9 >= carbon_pursuit_delay;
    if (carbon_pursuit_attempt == 1 && !carbon_pursuit_seen && now - carbon_pursuit_requested >= 30000000000ull &&
        !carbon_pursuit_find(manager - 0x4C, sim)) request = 1;
    if (request) {
        Cpu copy = *c;
        uint32_t enabled[] = {!carbon_pursuit_off}, zero[] = {0}, heat[1];
        call_guest(&copy, 0x006513E0u, 1, enabled);
        if (carbon_pursuit_has_heat) {
            memcpy(heat, &carbon_pursuit_heat, sizeof heat);
            call_guest(&copy, 0x0065C550u, 1, heat);
        }
        call_guest(&copy, 0x00651430u, 1, zero);
        ++carbon_pursuit_attempt;
        if (carbon_pursuit_attempt == 1) carbon_pursuit_requested = now;
        if (diag_on) diag_event("carbon_pursuit: request t=%.3f attempt=%u enabled=%u",
                               (now - carbon_pursuit_ready) / 1e9,
                               carbon_pursuit_attempt, enabled[0]);
        carbon_pursuit_second = 0;
    }
    carbon_pursuit_diag(manager, sim, now);
}
