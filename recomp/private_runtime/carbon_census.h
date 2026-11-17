/* 006B6F28: ECX=00B70650 before 007A42E0. 007A4680 reads zones
 * +11A and +1AA (48 shorts apart). 0079E780/0079E670 set loaded states
 * 3/4; 0079E700 frees +4C and resets +0C. This observer never writes G.
 * 0079A170 stores slot 0's streaming position at +D0 (00490A00 passes the
 * active camera's position, not the car's); 007A4850 classifies that point.
 */
#include "host.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>

extern int diag_on;
extern void diag_event(const char *, ...);
static uint32_t carbon_autodrive_player(void);

static unsigned carbon_census_loading;
static int carbon_census_enabled(void) {
    static int enabled = -1;
    if (!diag_on) return 0;
    if (enabled < 0) {
        const char *value = getenv("NFS_CARBON_CENSUS");
        enabled = value && !strcmp(value, "1");
    }
    return enabled;
}

/* Native 007A8505/007A8515 store this byte on both return paths. */
void carbon_census_evaluate(Cpu *c, void (*original)(Cpu *)) {
    original(c);
    if (carbon_census_enabled() && M8(0x00B7420Cu)) ++carbon_census_loading;
}

/* 007A97B0 cdecl outputs physics position (arg0) and forward (arg1).
 * Its marker path reads yaw u16 at marker+20, then 007A9A4B/50/53
 * writes (-cos(yaw),0,sin(yaw)). Override only this spawn direction. */
void carbon_c3_start(Cpu *c, void (*original)(Cpu *)) {
    const char *value = getenv("NFS_CARBON_C3_HEADING");
    const char *start = getenv("NFS_CARBON_SKIPFE_START");
    const char *skip = getenv("NFS_CARBON_SKIPFE");
    if (!value || !*value || !start || !*start || !skip || strcmp(skip, "1")) {
        original(c);
        return;
    }
    double x, z;
    char extra;
    if (sscanf(value, "%lf,%lf%c", &x, &z, &extra) != 2 ||
        !isfinite(x) || !isfinite(z) || !isfinite(hypot(x,z)) || hypot(x,z) == 0) {
        fprintf(stderr, "NFS_CARBON_C3_HEADING: expected finite nonzero physics x,z direction\n");
        exit(2);
    }
    uint32_t direction = M32(c->esp + 8);
    float heading[3] = {(float)(x/hypot(x,z)), 0, (float)(z/hypot(x,z))};
    original(c);
    memcpy(gptr(direction), heading, sizeof heading);
    if (diag_on) diag_event("c3_start: heading=%.6f,%.6f,%.6f", heading[0],heading[1],heading[2]);
}

/* 0060CB50/0060C1B0: sorted {IHandle,interface} map, no guest calls.
 * ISuspension 00403CE0, interface at +44; chassis physics 006DEAD0 calls
 * vtable +4C as the contact count (0 = airborne). Of the five factory
 * classes (creators 00707C40..00707E40) the player uses Simple 006FC8C0
 * (+B4, written by 006FCA30) or Racer 006F8A60 (+9C, 006FA390); Traffic
 * 006FB690 +94, Trailer 006FDA00 +84 and Sline 006FEA50 +88 report -1.
 * The census names the getter, so a -1 says which class it met. */
static uint32_t carbon_census_getter;
static int carbon_census_wheels(void) {
    carbon_census_getter = 0;
    uint32_t sim = carbon_autodrive_player(), map = sim ? M32(sim + 4) : 0;
    if (!map) return -1;
    uint32_t begin = M32(map), end = M32(map + 4);
    if (!begin || end < begin || (end - begin) % 8 || (end - begin) / 8 > 1024) return -1;
    uint32_t lo = 0, hi = (end - begin) / 8;
    while (lo < hi) {
        uint32_t mid = lo + (hi - lo) / 2;
        if (M32(begin + mid * 8) < 0x00403CE0u) lo = mid + 1;
        else hi = mid;
    }
    uint32_t entry = begin + lo * 8;
    if (entry >= end || M32(entry) != 0x00403CE0u) return -1;
    uint32_t suspension = M32(entry + 4), vt = suspension ? M32(suspension) : 0;
    uint32_t getter = vt ? M32(vt + 0x4C) : 0;
    carbon_census_getter = getter;
    uint32_t offset = 0;
    if (getter == 0x006F8A60u) offset = 0x9C;
    if (getter == 0x006FC8C0u) offset = 0xB4;
    if (!offset) return -1;
    uint32_t wheels = M32(suspension + offset);
    return wheels <= 4 ? (int)wheels : -1;
}

/* Read-only equivalent of the pool-7 callback 007A2520 -> 0079E2B0.
 * Unlike the native query, do not update its dirty bit or cached maximum. */
static uint32_t carbon_census_largest(uint32_t pool) {
    if (!pool) return 0;
    if (!M8(pool + 0x1C)) return M32(pool + 0x18);
    uint32_t head = pool + 0x28, largest = 0;
    for (uint32_t node = M32(head), guard = 0; node != head; node = M32(node)) {
        if (!node || ++guard > 65536) return 0;
        uint32_t size = M32(node + 0x0C);
        if (!M8(node + 0x10) && size > largest) largest = size;
    }
    return largest;
}

/* Traffic and cop positions, read-only. 00440CD0 stores A9E868 = traffic
 * manager+40 (vehicles +5C, count +64, inactive reusable ones included) and
 * A9E874 = cop manager+4C (pool +BC/+C4; pursuit list +140, count +148:
 * next +0, payload +8; a pursuit's vehicles +4C/+54). Active = IVehicle
 * vtable +9C 006D80C0 -> v+A8. IVehicle vtable +4 006D7EE0 returns v-94,
 * the ISimable; then the player's witnessed body reads. A failed witness
 * counts as unknown and prints no position. Each car prints IVehicle@x,y,z;
 * "*" = in a pursuit. */
static int carbon_census_vehicle(uint32_t v, float out[3]) {
    uint32_t vt = v ? M32(v) : 0;
    if (!vt || M32(vt + 0x9C) != 0x006D80C0u || M32(vt + 4) != 0x006D7EE0u) return -1;
    if (!M32(v + 0xA8)) return 0;
    uint32_t sim = v - 0x94, st = M32(sim);
    if (!st || M32(st + 0x60) != 0x006D7EA0u) return -1;
    uint32_t body = M32(sim + 0x4C), bv = body ? M32(body) : 0;
    if (!bv || M32(bv + 0x20) != 0x006C6FF0u) return -1;
    uint32_t holder = M32(body + 0x30), state = holder ? M32(holder) : 0;
    if (!state) return -1;
    for (unsigned k = 0; k < 3; ++k) {
        uint32_t bits = M32(state + 0x10 + 4 * k);
        memcpy(&out[k], &bits, 4);
        if (!isfinite(out[k]) || fabsf(out[k]) > 1e6f) return -1;
    }
    return 1;
}

static int carbon_census_chased(uint32_t base, uint32_t v) {
    uint32_t head = base + 0x140, node = M32(head), count = M32(base + 0x148);
    for (unsigned i = 0; node && node != head && i < count && i < 64; ++i, node = M32(node)) {
        uint32_t p = M32(node + 8), list = p ? M32(p + 0x4C) : 0, n = p ? M32(p + 0x54) : 0;
        for (unsigned j = 0; list && j < n && j < 64; ++j)
            if (M32(list + 4 * j) == v) return 1;
    }
    return 0;
}

static void carbon_census_vehicles(void) {
    uint32_t traffic = M32(0x00A9E868u), cops = M32(0x00A9E874u);
    if (!traffic && !cops) return;
    char text[2][2048];
    unsigned active[2] = {0, 0}, total[2] = {0, 0}, unknown = 0;
    for (unsigned kind = 0; kind < 2; ++kind) {
        uint32_t holder = kind ? cops : traffic, offset = kind ? 0x4C : 0x40;
        uint32_t base = holder >= offset ? holder - offset : 0;
        uint32_t array = base ? M32(base + (kind ? 0xBC : 0x5C)) : 0;
        uint32_t count = base ? M32(base + (kind ? 0xC4 : 0x64)) : 0;
        size_t length = 0;
        text[kind][0] = 0;
        if (count > 256 || (!array && count)) { ++unknown; continue; }
        total[kind] = count;
        for (unsigned i = 0; i < count; ++i) {
            uint32_t v = M32(array + 4 * i);
            float p[3];
            int state = v ? carbon_census_vehicle(v, p) : 0;
            if (state < 0) ++unknown;
            if (state <= 0) continue;
            ++active[kind];
            if (length < sizeof text[kind] - 48)
                length += (size_t)snprintf(text[kind] + length, sizeof text[kind] - length, "%s%08x@%.1f,%.1f,%.1f%s",
                                           length ? ";" : "", v, p[0], p[1], p[2],
                                           kind && carbon_census_chased(base, v) ? "*" : "");
        }
    }
    diag_event("vehicles: traffic=%u/%u cops=%u/%u unknown=%u T=%s C=%s",
               active[0], total[0], active[1], total[1], unknown,
               *text[0] ? text[0] : "-", *text[1] ? text[1] : "-");
}

static void carbon_census_sample(void) {
    if (!carbon_census_enabled()) return;
    const uint32_t streamer = 0x00B70650u;
    uint32_t count = M32(streamer + 0x32C), loaded = 0;
    /* Pointer storage ends before the +730 pool base. */
    if (count > (0x730 - 0x330) / 4) return;
    unsigned long long bytes = 0;
    char sections[2048];
    size_t length = 0;
    sections[0] = 0;
    for (uint32_t i = 0; i < count; ++i) {
        uint32_t record = M32(streamer + 0x330 + 4 * i);
        if (!record) continue;
        uint32_t status = M32(record + 0x0C);
        if ((status != 3 && status != 4) || !M32(record + 0x4C)) continue;
        unsigned number = M16(record + 8);
        length += (size_t)snprintf(sections + length, sizeof sections - length,
                                   "%s%u", loaded ? "," : "", number);
        ++loaded;
        bytes += M32(record + 0x18);
    }
    uint32_t pool = M32(streamer + 0x73C);
    /* Slot 0 +E0: the velocity 007A44B0 projects (at most 1.5 s or 100 m)
     * inside STREAMER_PREDICTION track-path zones (type 6). */
    float stream[3], velocity[3];
    for (unsigned i = 0; i < 3; ++i) {
        uint32_t bits = M32(streamer + 0xD0 + 4 * i);
        memcpy(&stream[i], &bits, 4);
        bits = M32(streamer + 0xE0 + 4 * i);
        memcpy(&velocity[i], &bits, 4);
    }
    int wheels = carbon_census_wheels();
    diag_event("census: zones=%d,%d loaded=%u bytes=%llu pool=%u largest=%u skipped=%u sections=%s stream=%.3f,%.3f,%.3f vel=%.3f,%.3f,%.3f zone_age=%d,%d wheels=%d suspension=%08X loading=%u",
               (int)(int16_t)M16(streamer + 0x11A), (int)(int16_t)M16(streamer + 0x1AA),
               loaded, bytes, M32(streamer + 0x734), carbon_census_largest(pool),
               M32(streamer + 0x28), sections, stream[0], stream[1], stream[2],
               velocity[0], velocity[1], velocity[2],
               (int32_t)M32(streamer + 0x120), (int32_t)M32(streamer + 0x1B0),
               wheels, carbon_census_getter, carbon_census_loading);
    carbon_census_loading = 0;
    carbon_census_vehicles();
}
