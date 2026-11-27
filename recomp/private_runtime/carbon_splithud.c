/* Keep the native package selection and update destinations. Only the drawing
 * scope changes: authored offsets already place the two HUDs in their halves.
 * The map exists in the first package only and remains shared at the divider.
 * Menus, messages in separate packages and results retain the shared FE path. */
#include "carbon_splithud.h"
#include "carbon_splitworld.h"
#include <math.h>
#include <stdlib.h>

extern float carbon_fe_kx(void);
extern void carbon_worldmap_art_draw(Cpu *, void (*)(Cpu *));
static unsigned hud_owner;
static uint32_t clip_rect[4], scratch;

int carbon_splithud_transform(float transform[4]) {
    uint32_t r[4];
    if (!hud_owner || !carbon_splitworld_rect(hud_owner == 2 ? 0x00B4B010u : 0x00B4AF90u, r)) return 0;
    uint32_t w = M32(0x00AB06FCu), h = M32(0x00AB0700u);
    if (!w || !h) return 0;
    float authored_width = carbon_fe_kx() < 1.0f ? 640.0f * 4.0f / 3.0f : 640.0f;
    float scale = fminf(r[2] / authored_width, r[3] / 240.0f);
    transform[0] = scale * 640.0f / w;
    transform[1] = scale * 480.0f / h;
    transform[2] = (2.0f * r[0] + r[2]) / w - 1.0f;
    transform[3] = 1.0f - (2.0f * r[1] + r[3]) / h - transform[1] * (hud_owner == 2 ? -0.5f : 0.5f);
    return 1;
}

/* The guest call must preserve the draw's registers, result and stack slots. */
static void hud_device(Cpu *c, uint32_t offset, int count, uint32_t *args) {
    Cpu work = *c;
    call_guest(&work, M32(M32(args[0]) + offset), count, args);
}
static void hud_drain(Cpu *c) {
    Cpu work = *c;
    call_guest(&work, 0x0072C9B0u, 0, NULL);
}

void carbon_splithud_clip(Cpu *c) {
    if (!hud_owner || !scratch) return;
    uint32_t device = M32(0x00AB0ABCu), a[3] = {device, scratch, 0};
    memcpy(G + scratch, clip_rect, 16);
    hud_device(c, 0x12C, 2, a);
    a[1] = 174; a[2] = 1;
    hud_device(c, 0xE4, 3, a);
}

/* Refresh from the live package on every draw: no FE pointers survive a race,
 * reload or allocator reuse. Bound the native tree walk, including siblings. */
static int hud_map_member(uint32_t node, uint32_t object, int in_map, unsigned *left) {
    for (; node && *left; node = M32(node + 4)) {
        --*left;
        uint32_t hash = M32(node + 0x10);
        int shared = in_map || hash == 0x0F365871u || hash == 0x00A1A862u;
        if (shared && node == object) return 1;
        if (M32(node + 0x18) == 5 && hud_map_member(M32(node + 0x64), object, shared, left)) return 1;
    }
    return 0;
}

void carbon_splithud_draw(Cpu *c, void (*original)(Cpu *)) {
    uint32_t r[4];
    if (M32(0x00A99BBCu) != 6 || !carbon_splitworld_rect(0x00B4AF90u, NULL) ||
        !carbon_splitworld_rect(0x00B4B010u, NULL)) { carbon_worldmap_art_draw(c, original); return; }
    uint32_t package = M32(0x00A97B2Cu), name = package ? M32(package + 0xC) : 0;
    const char *text = gptr(name);
    unsigned owner = text && !strcmp(text, "HUD_Player1.fng") ? 1 :
                     text && !strcmp(text, "HUD_Player2.fng") ? 2 : 0;
    if (!owner) { carbon_worldmap_art_draw(c, original); return; }
    unsigned remaining = 512;
    if (owner == 1 && hud_map_member(M32(package + 0x4C), arg(c, 0), 0, &remaining)) {
        carbon_worldmap_art_draw(c, original); return;
    }
    if (!carbon_splitworld_rect(owner == 2 ? 0x00B4B010u : 0x00B4AF90u, r)) { carbon_worldmap_art_draw(c, original); return; }
    uint32_t device = M32(0x00AB0ABCu);
    if (!device) { carbon_worldmap_art_draw(c, original); return; }
    if (!scratch) scratch = galloc(20);
    if (!scratch) { carbon_worldmap_art_draw(c, original); return; }
    hud_drain(c);
    uint32_t saved[5], previous_rect[4], previous_owner = hud_owner;
    memcpy(previous_rect, clip_rect, 16);
    uint32_t a[3] = {device, scratch, 0};
    hud_device(c, 0x130, 2, a);
    a[1] = 174; a[2] = scratch + 16;
    hud_device(c, 0xE8, 3, a);
    memcpy(saved, G + scratch, 20);
    clip_rect[0] = r[0]; clip_rect[1] = r[1]; clip_rect[2] = r[0] + r[2]; clip_rect[3] = r[1] + r[3];
    if (saved[4]) {
        for (unsigned i = 0; i < 2; ++i) {
            if (clip_rect[i] < saved[i]) clip_rect[i] = saved[i];
            if (clip_rect[i + 2] > saved[i + 2]) clip_rect[i + 2] = saved[i + 2];
            if (clip_rect[i + 2] < clip_rect[i]) clip_rect[i + 2] = clip_rect[i];
        }
    }
    hud_owner = owner;
    carbon_splithud_clip(c);
    if (diag_on) {
        static unsigned reported;
        if (!(reported & (1u << owner))) {
            reported |= 1u << owner;
            float t[4]; carbon_splithud_transform(t);
            diag_event("carbon splithud: package=%s owner=%u rect=%u,%u,%u,%u transform=%.9g,%.9g,%.9g,%.9g",
                       text, owner, r[0], r[1], r[2], r[3], t[0], t[1], t[2], t[3]);
        }
    }
    carbon_worldmap_art_draw(c, original);
    hud_drain(c);
    memcpy(G + scratch, saved, 16);
    a[1] = scratch; hud_device(c, 0x12C, 2, a);
    a[1] = 174; a[2] = saved[4]; hud_device(c, 0xE4, 3, a);
    hud_owner = previous_owner;
    memcpy(clip_rect, previous_rect, 16);
}

/* The two-camera diagnostic has one simulated player. Exercise the actual
 * split packages/constructors without inventing another player or changing
 * simulation mode. Its second HUD explicitly mirrors the first car's data.
 * Native two-player races never take this path. */
static uint32_t probe_player, probe_native_hud, probe_hud, probe_bundle;
static int hud_probe(void) {
    if (!diag_on || M32(0x00B4D854u) == 1) return 0;
    const char *value = getenv("BOOT_DIAG_SPLITWORLD");
    return value && !strcmp(value, "1");
}
void carbon_splithud_probe_load(Cpu *c, void (*original)(Cpu *)) {
    /* Schedule alongside the region's other bundles. Its final load callback
     * precedes player/HUD construction; starting I/O in SetHUDType is too late. */
    if (hud_probe() && !probe_bundle) {
        Cpu work = *c;
        uint32_t load[5] = {0x009E37A4u, 3, 0, 0, 0}, wait[2] = {0, 0};
        probe_bundle = call_guest(&work, 0x006B32C0u, 5, load);
        if (probe_bundle) {
            work = *c; work.ecx = probe_bundle;
            call_guest(&work, 0x006B5910u, 2, wait);
        }
    }
    original(c);
}
void carbon_splithud_probe_type(Cpu *c, void (*original)(Cpu *)) {
    if (arg(c, 0) != 1 || !hud_probe() || !probe_bundle) { original(c); return; }
    uint32_t self = c->ecx, slot = c->esp + 4;
    M32(slot) = 3;
    original(c);
    M32(slot) = 1;
    probe_native_hud = M32(self + 0x28);
    if (!probe_native_hud) return;
    probe_player = self;
    Cpu work = *c;
    uint32_t size = 0x348;
    uint32_t allocation = call_guest(&work, 0x006A1560u, 1, &size);
    if (!allocation) return;
    uint32_t args[4] = {4, 0x009D6110u, self, 1};
    work = *c; work.ecx = allocation;
    probe_hud = call_guest(&work, 0x005E7B90u, 4, args);
    if (diag_on) diag_event("carbon splithud probe: HUD_Player1.fng=%08X HUD_Player2.fng=%08X telemetry=mirrored simulation_unchanged=1",
                            probe_native_hud, probe_hud);
}
void carbon_splithud_probe_update(Cpu *c, void (*original)(Cpu *)) {
    if (!probe_hud) { original(c); return; }
    uint32_t self = c->ecx, args[2] = {arg(c, 0), arg(c, 1)};
    original(c);
    if (probe_hud && self == probe_native_hud) {
        Cpu work = *c; work.ecx = probe_hud;
        call_guest(&work, 0x005E6F70u, 2, args);
        if (diag_on) {
            static unsigned reports;
            if (reports++ < 3) {
                diag_event("carbon splithud probe update: type=%u,%u main=%08X,%08X resource_state=%u resource_type=%u",
                           M32(probe_native_hud + 0x28), M32(probe_hud + 0x28), M32(probe_native_hud + 0x2E0), M32(probe_hud + 0x2E0),
                           M32(0x00A60C28u), M32(0x00A60C34u));
                uint32_t manager = M32(0x00A97A78u), engine = manager ? M32(manager) : 0;
                unsigned left = 32;
                for (uint32_t p = engine ? M32(engine + 0xE0) : 0; p && left--; p = M32(p + 4))
                    diag_event("carbon splithud probe package: %.64s", gptr(M32(p + 0xC)));
            }
        }
    }
}
void carbon_splithud_probe_destroy(Cpu *c, void (*original)(Cpu *)) {
    int owns = probe_player && c->ecx == probe_player;
    if (owns) {
        uint32_t hud = probe_hud;
        probe_player = probe_native_hud = probe_hud = 0;
        if (hud) { Cpu work = *c; work.ecx = hud; call_guest(&work, 0x005E6EE0u, 0, NULL); }
    }
    original(c);
    if (owns && probe_bundle) {
        Cpu work = *c; uint32_t bundle = probe_bundle; probe_bundle = 0;
        call_guest(&work, 0x006B7BE0u, 1, &bundle);
    }
}
