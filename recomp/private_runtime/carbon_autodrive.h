/* Native player AI, installed only by the opt-in local-player constructor hook.
 * 0065C2C0 is the registered ForceAIControl(int) script command: zero selects
 * the first local player, nonzero the last; its human-AI interface +08 tests
 * control, +0C sets it. Split has exactly two local players.
 * 0076C1D0 publishes INIS at B4D964. Never change suspension while it exists.
 */
#include "host.h"
#include <math.h>
#include <stdlib.h>
#include <string.h>
#include "carbon_census.h"

extern int diag_on;
extern void diag_event(const char *, ...);
extern void user32_autoreturn(void);
extern int carbon_soak_hold_results(void);

static uint32_t carbon_autodrive_sim;
static uint64_t carbon_autodrive_second;
static double carbon_autodrive_distance, carbon_autodrive_top;
static float carbon_autodrive_previous[3];
static int carbon_autodrive_position_valid;
static uint32_t carbon_autodrive_present_target, carbon_autodrive_present_callback;

extern int carbon_splitworld_rect(uint32_t, uint32_t *);
extern unsigned carbon_spliteffects_resources(void);
extern unsigned threads_handle_count(void);
static int carbon_autodrive_split_finished, carbon_autodrive_split_solo;

/* Passive split acceptance snapshots. Native 006449D0 sets racer +46 on
 * finishing; 006121E0 supplies the +18/384 racer array. Resolve identity by
 * keyed Simable, never by the finish byte or list order. */
static void carbon_autodrive_splitflow(uint64_t now) {
    if (!diag_on || pad_count() != 2) return;
    static uint64_t next;
    static uint32_t last_flow = ~0u, last_count = ~0u, last_finished = ~0u, last_package;
    uint32_t flow = M32(0x00A99BBCu), count = M32(0x00A9FF64u), list = M32(0x00A9FF5Cu);
    uint32_t wrapper = M32(0x00A97A78u), engine = wrapper && wrapper != 0xFFFFFF28u ? M32(wrapper) : 0;
    uint32_t package = 0;
    if (engine && engine != 0xFFFFFF28u) {
        unsigned limit = 128;
        for (uint32_t p = M32(engine + 0xE4); p && limit--; p = M32(p + 8))
            if (M32(p + 0x20)) { package = p; break; }
    }
    uint32_t sims[2] = {0}, racers[2] = {0}, finished = 0;
    double velocity[2] = {0};
    uint32_t race = M32(0x00A98284u), objects = M32(0x00AA26B4u), objects_count = M32(0x00AA26BCu);
    for (unsigned i = 0; list && count <= 2 && i < count; ++i) {
        uint32_t player = M32(list + 4*i), slot = player ? M32(player + 0x18) : 2;
        if (player < 8 || slot > 1) continue;
        uint32_t sim = sims[slot] = M32(player - 8), body = sim ? M32(sim + 0x4C) : 0;
        uint32_t holder = body ? M32(body + 0x30) : 0, state = holder ? M32(holder) : 0;
        if (state) {
            double x = MF32(state + 0x20), y = MF32(state + 0x24), z = MF32(state + 0x28);
            velocity[slot] = sqrt(x*x + y*y + z*z);
        }
        unsigned n = race ? M32(race + 0x6A08) : 0;
        if (objects && objects_count <= 16384 && n <= 30) for (unsigned r = 0; r < n; ++r) {
            uint32_t info = race + 0x18 + 0x384*r, key = M32(info), lo = 0, hi = objects_count;
            while (lo < hi) {
                uint32_t mid = lo + (hi - lo)/2;
                if (M32(objects + 8*mid) < key) lo = mid + 1; else hi = mid;
            }
            if (key && lo < objects_count && M32(objects + 8*lo) == key && M32(objects + 8*lo + 4) == sim) {
                racers[slot] = info;
                if (M8(info + 0x46)) finished |= 1u << slot;
                break;
            }
        }
    }
    uint32_t manager = M32(0x00B4CFE0u), mode = M32(0x00B4D854u);
    unsigned views = !!carbon_splitworld_rect(0x00B4AF90u, NULL) + !!carbon_splitworld_rect(0x00B4B010u, NULL);
    unsigned captures = carbon_spliteffects_resources();
    carbon_autodrive_split_finished = flow == 6 && mode == 1 && count == 2 && finished == 3 &&
        racers[0] && racers[1] && M32(racers[0] + 0x4C) >= 2 && M32(racers[1] + 0x4C) >= 2;
    carbon_autodrive_split_solo = flow == 6 && mode == 0 && count == 1 && !views && !captures &&
        manager && M32(manager + 0x24) == 3 && sims[0] && !sims[1] && velocity[0] > 1;
    if (now < next && flow == last_flow && count == last_count && finished == last_finished && package == last_package) return;
    next = now + 1000000000ull; last_flow = flow; last_count = count; last_finished = finished; last_package = package;
    uint32_t name = package ? M32(package + 0x0C) : 0;
    diag_event("carbon splitflow: flow=%u state=%u mode=%u locals=%u views=%u captures=%u handles=%u race=%08X package=%.63s",
               flow, manager ? M32(manager + 0x24) : 0, mode, count, views,
               captures, threads_handle_count(), race, name ? (char *)gptr(name) : "none");
    for (unsigned p = 0; p < 2; ++p) if (sims[p])
        diag_event("carbon splitflow: player=%u sim=%08X racer=%08X finished=%u velocity=%.3f lap=%u",
                   p + 1, sims[p], racers[p], !!(finished & (1u << p)), velocity[p], racers[p] ? M32(racers[p] + 0x4C) + 1 : 0);
}

int carbon_autodrive_split_ready(const char *stage) {
    if (!diag_on || pad_count() != 2) return 0;
    carbon_autodrive_splitflow(host_ticks());
    if (!strcmp(stage, "finished")) return carbon_autodrive_split_finished;
    return !strcmp(stage, "solo") && carbon_autodrive_split_solo;
}

/* The original player getter and rigid-body readers are witnessed before any
 * indirect layout is followed. Position +10 and velocity +20 are physics SI
 * vectors (006C6FF0, 006C7000, speed magnitude 006C7020).
 */
static uint32_t carbon_autodrive_player(void) {
    uint32_t list = M32(0x00A9FF5Cu), count = M32(0x00A9FF64u);
    if (!list || !count || count > 2) return 0;
    uint32_t player = M32(list), vt = player ? M32(player) : 0;
    if (player < 8 || !vt || M32(vt + 4) != 0x0076E810u) return 0;
    return M32(player - 8);
}

static void carbon_autodrive_sample(uint32_t sim, uint64_t now) {
    uint32_t vt = M32(sim);
    if (!vt || M32(vt + 0x60) != 0x006D7EA0u) return;
    uint32_t body = M32(sim + 0x4C), bv = body ? M32(body) : 0;
    if (!bv || M32(bv + 0x20) != 0x006C6FF0u) return;
    uint32_t holder = M32(body + 0x30), state = holder ? M32(holder) : 0;
    if (!state) return;
    float position[3], velocity[3];
    memcpy(position, gptr(state + 0x10), sizeof position);
    memcpy(velocity, gptr(state + 0x20), sizeof velocity);
    double squared = 0, delta = 0;
    for (unsigned k = 0; k < 3; ++k) {
        if (!isfinite(position[k]) || !isfinite(velocity[k])) return;
        squared += (double)velocity[k] * velocity[k];
        double d = position[k] - carbon_autodrive_previous[k];
        delta += d * d;
    }
    double speed = sqrt(squared), step = sqrt(delta);
    /* Respawns/teleports are not distance driven. Sample every presented frame,
     * rather than joining sparse one-second chords through corners. */
    if (carbon_autodrive_position_valid && step < 20)
        carbon_autodrive_distance += step;
    memcpy(carbon_autodrive_previous, position, sizeof position);
    carbon_autodrive_position_valid = 1;
    if (speed > carbon_autodrive_top) carbon_autodrive_top = speed;
    if (!diag_on || (carbon_autodrive_second && now - carbon_autodrive_second < 1000000000ull)) return;
    carbon_autodrive_second = now;
    carbon_census_sample();
    /* GRaceStatus::GetRacerInfo 006121E0: +18, stride 384; native
     * NotifyLapFinished 0065E010 / 00647B80 update +4C completed laps.
     * Resolve the racer handle through the native keyed Simable collection,
     * as 00656980 does; finish flag +46 is not player identity. */
    uint32_t race = M32(0x00A98284u), racers = race ? M32(race + 0x6A08) : 0;
    uint32_t objects = M32(0x00AA26B4u), count = M32(0x00AA26BCu);
    unsigned lap = 0;
    if (objects && count <= 16384 && racers <= 30) for (unsigned i = 0; i < racers; ++i) {
        uint32_t info = race + 0x18 + 0x384 * i;
        uint32_t key = M32(info), lo = 0, hi = count;
        while (lo < hi) {
            uint32_t mid = lo + (hi - lo) / 2;
            if (M32(objects + 8 * mid) < key) lo = mid + 1;
            else hi = mid;
        }
        if (key && lo < count && M32(objects + 8 * lo) == key &&
            M32(objects + 8 * lo + 4) == sim) {
            lap = M32(info + 0x4C) + 1; break;
        }
    }
    diag_event("autodrive: speed=%.3f_mps mph=%.2f distance=%.3f_m top_mph=%.2f lap=%u racers=%u position=%.3f,%.3f,%.3f",
               speed, speed * 2.2369362921, carbon_autodrive_distance,
               carbon_autodrive_top * 2.2369362921, lap, racers, position[0], position[1], position[2]);
}

/* Continue results and in-game prompts with bounded retries per appearance.
 * The package names are Carbon's native names, not the other image's names. */
static void carbon_autodrive_popup(uint64_t now) {
    static uint32_t last_package;
    static uint64_t since;
    static unsigned attempts;
    static char last_name[64];
    uint32_t wrapper = M32(0x00A97A78u);
    uint32_t engine = wrapper && wrapper != 0xFFFFFF28u ? M32(wrapper) : 0;
    uint32_t package = 0;
    if (engine && engine != 0xFFFFFF28u) {
        unsigned remaining = 128;
        for (uint32_t p = M32(engine + 0xE4); p && remaining--; p = M32(p + 8))
            if (M32(p + 0x20)) { package = p; break; }
    }
    uint32_t name = package ? M32(package + 0x0C) : 0;
    const char *text = name ? gptr(name) : "";
    if (package != last_package || strcmp(text, last_name)) {
        /* A key being sent is not evidence that a native modal accepted it. */
        if (attempts && diag_on) diag_event("autodrive: dismissed %s after %u attempts", last_name, attempts);
        last_package = package; since = now; attempts = 0;
        snprintf(last_name, sizeof last_name, "%s", text);
        if (diag_on) diag_event("autodrive: package in control %s", text);
    }
    if (!name || attempts >= 4 || now - since < 1500000000ull) return;
    if (!strcmp(text, "FePostRaceResults.fng") && carbon_soak_hold_results()) return;
    const char *keys = getenv("BOOT_KEYS");
    if (!strcmp(text, "FePostRaceResults.fng") && keys && strstr(keys, "pkg:FePostRaceResults.fng")) return;
    if (!strcmp(text, "FePostRaceResults.fng") || !strcmp(text, "FePostStages.fng") || !strcmp(text, "FeBusted.fng") ||
        (M32(0x00A99BBCu) == 6 && (!strcmp(text, "InGameDialog.fng") ||
         !strcmp(text, "FeDialog.fng") || !strcmp(text, "FeSmsMessage.fng")))) {
        user32_autoreturn();
        since = now;
        ++attempts;
        if (diag_on) diag_event("autodrive: Return attempt %u/4 for %s", attempts, text);
    }
}

#include "carbon_c3drive.h"

static void carbon_autodrive_frame(Cpu *c) {
    uint64_t now = host_ticks();
    uint32_t sim = carbon_autodrive_player();
    if (sim != carbon_autodrive_sim) {
        carbon_autodrive_sim = sim;
        carbon_autodrive_position_valid = 0;
        carbon_autodrive_distance = carbon_autodrive_top = 0;
        carbon_autodrive_second = 0;
    }
    uint32_t manager = M32(0x00B4CFE0u);
    uint32_t flow = M32(0x00A99BBCu), state = manager ? M32(manager + 0x24) : 0;
    uint32_t nis = M32(0x00B4D964u);
    if (!sim || flow != 6 || state != 3 || nis) {
        if (diag_on && (!carbon_autodrive_second || now - carbon_autodrive_second >= 1000000000ull)) {
            carbon_autodrive_second = now;
            diag_event("autodrive: waiting flow=%u sim_state=%u nis=%08x player=%08x", flow, state, nis, sim);
        }
        return;
    }
    Cpu drive = *c;
    uint32_t args[] = {0};
    /* The native command is idempotent: SetAiControl is called once while its
     * flag remains set. Native race, road navigation and recovery stay intact. */
    if (!carbon_c3drive_frame(sim,now)) {
        call_guest(&drive, 0x0065C2C0u, 1, args);
        /* Drive the second native human-AI interface too. Scripted pedal
         * presses depend on the profile's live bindings, which may be custom. */
        if (M32(0x00A9FF64u) == 2) {
            drive = *c;
            args[0] = 1;
            call_guest(&drive, 0x0065C2C0u, 1, args);
        }
    }
    if (diag_on) carbon_autodrive_sample(sim, now);
}

/* Simulation tasks stop in modal prompts. Present still runs, so only the
 * opt-in device's Present slot forwards to this prompt observer. Native
 * rendering, scripts and the guest COM return convention run first. */
static int carbon_autodrive_present(Cpu *c) {
    dispatch(c, carbon_autodrive_present_target);
    if (diag_on) carbon_autodrive_splitflow(host_ticks());
    /* A log-only crossing trace never answers a prompt for the player. */
    if (!carbon_c3drive_logging()) carbon_autodrive_popup(host_ticks());
    carbon_autodrive_frame(c);
    return 1;
}

void carbon_autodrive_construct(Cpu *c, void (*original)(Cpu *)) {
    original(c);
    const char *enabled = getenv("BOOT_AUTODRIVE");
    if ((!enabled || strcmp(enabled, "1")) && !carbon_c3drive_logging()) return;
    /* AB0ABC is the native device, confirmed by its native COM calls in
     * 00710220; IDirect3DDevice9 slot 17 is Present. Reset retains its device. */
    uint32_t device = M32(0x00AB0ABCu), vt = device ? M32(device) : 0;
    /* Install again only on a rebuilt vtable: another hook may sit on top of ours. */
    if (vt && (!carbon_autodrive_present_callback || M32(vt + 0x44) == carbon_autodrive_present_target)) {
        carbon_autodrive_present_target = M32(vt + 0x44);
        if (!carbon_autodrive_present_callback)
            carbon_autodrive_present_callback = host_fn(carbon_autodrive_present, "autodrive prompts");
        M32(vt + 0x44) = carbon_autodrive_present_callback;
        if (diag_on) diag_event("autodrive: installed native local-player ForceAIControl=0065C2C0");
    }
}
