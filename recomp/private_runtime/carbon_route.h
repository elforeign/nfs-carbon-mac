/* Route priorities are u16 F=G+H, in units of A7AD34 (stock 0.25 m).
 * 00806180 finishes allocating the unchanged 16-byte search states.
 * The diagnostic observes both native F stores, before conversion; it never
 * changes the unit while a search is pending. Result storage stays 510 u16s.
 */
#include "host.h"
#include <errno.h>
#include <inttypes.h>
#include <math.h>
#include <stdlib.h>
#include <string.h>

static int carbon_route_initialized, carbon_route_measuring, carbon_route_done;
static double carbon_route_max_f, carbon_route_max_ticks;
static unsigned carbon_route_samples;
static uint32_t carbon_route_present_target, carbon_route_present_callback;

static void carbon_route_score(float f) {
    double ticks = (double)f / MF32(0x00A7AD34u);
    if (f > carbon_route_max_f) carbon_route_max_f = f;
    if (ticks > carbon_route_max_ticks) carbon_route_max_ticks = ticks;
    ++carbon_route_samples;
}

void carbon_route_insert(Cpu *c, void (*original)(Cpu *)) {
    /* 007F6333 loads entry ESP+14, then divides at 007F634C. */
    if (carbon_route_measuring) carbon_route_score(argf(c, 4));
    original(c);
}

void carbon_route_set(Cpu *c, void (*original)(Cpu *)) {
    /* 007EA905 loads entry ESP+10, then divides at 007EA925. */
    if (carbon_route_measuring) carbon_route_score(argf(c, 3));
    original(c);
}

static uint32_t carbon_route_call(Cpu *c, uint32_t self, uint32_t fn,
                                  int count, const uint32_t *args) {
    c->ecx = self;
    return call_guest(c, fn, count, args);
}

/* "gps": engage the native GPS (00433AB0, what script NavigatePlayerTo
 * 0064B8C0 calls) from the player to the probe's Rockport node 5691, then log
 * its state. GPS object A83E3C: +40 goal, +6C state (2 = route found,
 * 00433A8C), road navigator at +70 (count +374, list +378). */
static unsigned carbon_route_frames, carbon_route_engaged;

static void carbon_route_gps(Cpu *live) {
    uint32_t gps = M32(0x00A83E3Cu), nodes = M32(0x00B77EC8u);
    ++carbon_route_frames;
    if (!gps || !nodes || M32(0x00B77E84u) <= 5790) return;
    if (!carbon_route_engaged && carbon_route_frames % 60 == 0) {
        Cpu query = *live;
        uint32_t goal = gmalloc(16);
        memcpy((void *)gptr(goal), gptr(nodes + 32 * 5691), 12);
        uint32_t args[] = {goal, 0x43160000u, 1};
        unsigned ok = call_guest(&query, 0x00433AB0u, 3, args) & 255;
        gfree(goal);
        carbon_route_engaged = ok;
        diag_event("carbon_route: gps engage=%u try=%u state=%u count=%u goal=%.1f,%.1f,%.1f",
                   ok, carbon_route_frames / 60, M32(gps + 0x6C), M32(gps + 0x374),
                   (double)MF32(gps + 0x40), (double)MF32(gps + 0x44), (double)MF32(gps + 0x48));
    }
    if (carbon_route_engaged && carbon_route_frames % 600 == 0)
        diag_event("carbon_route: gps state=%u count=%u at=%.1f,%.1f,%.1f",
                   M32(gps + 0x6C), M32(gps + 0x374),
                   (double)MF32(gps + 0x50), (double)MF32(gps + 0x54), (double)MF32(gps + 0x58));
}

static uint64_t carbon_route_flags(uint32_t segments, unsigned count,
                                   unsigned char *saved, int action) {
    uint64_t hash = UINT64_C(14695981039346656037);
    for (unsigned i = 0; i < count; ++i) {
        uint32_t address = segments + 22 * i + 0xB;
        if (action == 1) {
            saved[i] = M8(address);
            /* Native 007EB230 clears exactly the two barrier bits. */
            M8(address) &= 0xCF;
        } else if (action == 2) M8(address) = saved[i];
        unsigned char value = action == 1 ? saved[i] : M8(address);
        hash = (hash ^ value) * UINT64_C(1099511628211);
    }
    return hash;
}

static void carbon_route_probe(Cpu *live) {
    /* These are native road-node IDs, independently selected by Dijkstra.
     * +0/+4/+8 position, +C self ID, +10 degree, +12 adjacency; stride 32.
     * Segment stride 22: +0/+2 endpoints, +4 length, +8 self ID.
     */
    /* cross/back join Palmont 2342 and Rockport 5691 (Rockport IDs follow
     * Palmont's 4603), the longest merged-graph pair: retail's 5790 segments
     * mean no merged world, so those two pairs are skipped there.
     */
    static const struct { const char *name; unsigned from, to, merged; } pairs[] = {
        {"short", 203, 534, 0}, {"medium", 1347, 2544, 0}, {"long", 1521, 2342, 0},
        {"cross", 2342, 5691, 1}, {"back", 5691, 2342, 1}
    };
    Cpu query = *live;
    uint32_t nodes = M32(0x00B77EC8u), segments = M32(0x00B77ECCu);
    uint32_t manager = M32(0x00B77EFCu);
    carbon_route_call(&query, manager, 0x00810F70u, 0, NULL);
    unsigned segment_count = M32(0x00B77E84u), seg1000 = 0, seg2000 = 0;
    unsigned barriers = M32(0x00B71408u), enabled = 0;
    for (unsigned i = 0; i < segment_count; ++i) {
        seg1000 += !!(M16(segments + 22 * i + 10) & 0x1000);
        seg2000 += !!(M16(segments + 22 * i + 10) & 0x2000);
    }
    for (unsigned i = 0; i < barriers; ++i)
        enabled += !!M8(M32(0x00B7140Cu) + 0x18 * i + 0x10);
    diag_event("carbon_route: blocked seg1000=%u seg2000=%u barriers=%u/%u",
               seg1000, seg2000, enabled, barriers);
    unsigned char *saved = malloc(segment_count);
    if (!saved) return;
    for (unsigned p = 0; p < sizeof pairs / sizeof pairs[0]; ++p) {
      if (pairs[p].merged && segment_count <= 5790) continue;
      for (unsigned open = 0; open < 2; ++open) {
        uint64_t before = carbon_route_flags(segments, segment_count, saved, open);
        uint32_t storage = gmalloc(0x340), nav = storage;
        uint32_t source = storage + 0x310, direction = storage + 0x320;
        uint32_t destination = storage + 0x330;
        uint32_t a = nodes + 32 * pairs[p].from, b = nodes + 32 * pairs[p].to;
        memcpy((void *)gptr(source), gptr(a), 12);
        memcpy((void *)gptr(destination), gptr(b), 12);
        /* A stable native adjacent segment supplies a nonzero source heading.
         * Endpoint positions and heading are identical across all three runs.
         */
        uint32_t seg = segments + 22 * M16(a + 18);
        unsigned other = M16(seg) == pairs[p].from ? M16(seg + 2) : M16(seg);
        double norm = 0;
        for (unsigned k = 0; k < 3; ++k) {
            float d = MF32(nodes + 32 * other + 4 * k) - MF32(a + 4 * k);
            MF32(direction + 4 * k) = d;
            norm += (double)d * d;
        }
        norm = sqrt(norm);
        for (unsigned k = 0; k < 3; ++k) MF32(direction + 4 * k) /= norm;
        carbon_route_call(&query, nav, 0x00806820u, 0, NULL);
        uint32_t type[] = {3};
        carbon_route_call(&query, nav, 0x007EC0D0u, 1, type);
        uint32_t init[] = {source, direction, 1, 0x3F800000u};
        carbon_route_call(&query, nav, 0x0080F180u, 4, init);
        carbon_route_max_f = carbon_route_max_ticks = 0;
        carbon_route_samples = 0;
        carbon_route_measuring = 1;
        uint32_t target[] = {destination, 0, 0};
        carbon_route_call(&query, nav, 0x00811740u, 3, target);
        carbon_route_measuring = 0;
        unsigned status = M32(nav + 0x74), count = M32(nav + 0x304);
        uint32_t list = M32(nav + 0x308);
        uint64_t hash = UINT64_C(14695981039346656037);
        unsigned first = 65535, last = 65535;
        double metres = 0;
        if (list && count <= 510) {
            int started = 0, finished = 0;
            for (unsigned i = 0; i < count; ++i) {
                unsigned id = M16(list + 2 * i);
                if (!i) first = id;
                last = id;
                hash = (hash ^ (id & 255)) * UINT64_C(1099511628211);
                hash = (hash ^ (id >> 8)) * UINT64_C(1099511628211);
                if (finished) continue;
                /* Unweighted native 007ED790 reconstruction: source and
                 * destination fractions limit the included endpoint lengths.
                 */
                if (id == M16(nav + 0x8A)) started = 1;
                double begin = id == M16(nav + 0x8A) ? MF32(nav + 0x8C) : 0;
                double end = id == M16(nav + 0x2FA) ? MF32(nav + 0x2FC) : 1;
                if (started) metres += M16(segments + 22 * id + 4) *
                    (double)MF32(0x00B77F58u) * fmax(0, end - begin);
                if (id == M16(nav + 0x2FA)) finished = 1;
            }
        }
        diag_event("carbon_route: pair=%s mode=%s nodes=%u,%u scale=%.9g status=%u count=%u metres=%.6f first=%u last=%u hash=%016" PRIx64 " max_f=%.9g max_ticks=%.9g samples=%u",
                   pairs[p].name, open ? "open" : "asis", pairs[p].from, pairs[p].to,
                   (double)MF32(0x00A7AD34u), status, count, metres, first, last,
                   hash, carbon_route_max_f, carbon_route_max_ticks, carbon_route_samples);
        carbon_route_call(&query, nav, 0x007F7BF0u, 0, NULL);
        gfree(storage);
        if (open) {
            uint64_t after = carbon_route_flags(segments, segment_count, saved, 2);
            diag_event("carbon_route: restore pair=%s before=%016" PRIx64 " after=%016" PRIx64,
                       pairs[p].name, before, after);
        }
      }
    }
    free(saved);
}

static int carbon_route_present(Cpu *c) {
    dispatch(c, carbon_route_present_target);
    const char *probe = getenv("NFS_CARBON_ROUTE_PROBE");
    int in_game = M32(0x00A99BBCu) == 6 && M32(0x00B77EFCu) && M32(0x00B77EC8u) && M32(0x00B77ECCu);
    if (in_game && probe && !strcmp(probe, "gps")) carbon_route_gps(c);
    else if (!carbon_route_done && in_game) {
        carbon_route_done = 1;
        carbon_route_probe(c);
    }
    return 1;
}

void carbon_route_construct(Cpu *c, void (*original)(Cpu *)) {
    original(c);
    if (!carbon_route_initialized) {
        carbon_route_initialized = 1;
        const char *setting = getenv("NFS_CARBON_ROUTE_SCALE");
        if (setting && *setting) {
            char *end;
            errno = 0;
            float scale = strtof(setting, &end);
            if (!errno && !*end && isfinite(scale) && scale > 0)
                MF32(0x00A7AD34u) = scale;
            else if (diag_on) diag_event("carbon_route: invalid scale=%s", setting);
        }
    }
    const char *probe = getenv("NFS_CARBON_ROUTE_PROBE");
    if (!diag_on || !probe || (strcmp(probe, "1") && strcmp(probe, "gps"))) return;
    uint32_t device = M32(0x00AB0ABCu), vt = device ? M32(device) : 0;
    if (vt && (!carbon_route_present_callback || M32(vt + 0x44) == carbon_route_present_target)) {
        carbon_route_present_target = M32(vt + 0x44);
        if (!carbon_route_present_callback)
            carbon_route_present_callback = host_fn(carbon_route_present, "route probe");
        M32(vt + 0x44) = carbon_route_present_callback;
    }
}
