/* Native player AI, installed only by the opt-in local-player constructor hook.
 * 0065C2C0 is the registered ForceAIControl(int) script command: zero selects
 * the first local player; its human-AI interface +08 tests control, +0C sets it.
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
     * as 00656980 does; finish flag +41 is not player identity. */
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
    if (!carbon_c3drive_frame(sim,now))
        call_guest(&drive, 0x0065C2C0u, 1, args);
    if (diag_on) carbon_autodrive_sample(sim, now);
}

/* Simulation tasks stop in modal prompts. Present still runs, so only the
 * opt-in device's Present slot forwards to this prompt observer. Native
 * rendering, scripts and the guest COM return convention run first. */
static int carbon_autodrive_present(Cpu *c) {
    dispatch(c, carbon_autodrive_present_target);
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
        if (diag_on) diag_event("autodrive: installed native ForceAIControl(0)=0065C2C0");
    }
}
