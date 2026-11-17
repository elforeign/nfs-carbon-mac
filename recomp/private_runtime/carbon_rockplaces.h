/* Fixed-owned imported premises retain the native positional save layout. */
#include "host.h"
#include "game_select.h"
#include <stdlib.h>

#if NFS_GAME == NFS_GAME_PRIVATE
extern int private_carbon_player_position(float *);
static void carbon_rockplaces_trace(Cpu *c);
static void carbon_rockplaces_icons(Cpu *c);
static unsigned carbon_rockplaces_pending;
/* Pure scope shared by ownership and map enumeration. */
static int carbon_rockplaces_scope(uint32_t key) {
    return key == 0xDAF7164Eu || key == 0x2F8CA402u || key == 0xE925D054u;
}

static int carbon_rockplaces_enabled(void) {
    const char *value = getenv("NFS_CARBON_ROCKPLACES");
    return !(value && !strcmp(value, "0"));
}

/* 00632490 and 006486B0 serialize one crew key per sorted premises node,
 * without a key/count. The eight native elements end at BFC67884; the fifteen
 * fixed-owned additions sort after them. End only these two codec walks at
 * that boundary. In particular, 006486B0 rebuilds the full tree internally:
 * initialization, normalization and its final ownership refresh must see all
 * entries. The gameplay fixture pins the native keys and reserved-range count.
 * Keep codec protection independent of the ownership/map switch: an expanded
 * premises tree still needs the native save layout when those features are off.
 * The native refresh restores area-less houses and the lot exception below;
 * initialization has already normalized their previous-owner/change flags. */
void carbon_rockplaces_successor(Cpu *c, void (*original)(Cpu *)) {
    uint32_t caller = M32(c->esp);
    original(c);
    /* Only 00648090 calls the 0062F840 lookup. Its premises-tree walk has
     * no cached icon-array iterator; constructors are already complete. */
    if (carbon_rockplaces_pending && caller == 0x0062F883u)
        carbon_rockplaces_icons(c);
    if (diag_on) carbon_rockplaces_trace(c);
    if (caller != 0x006326F0u && caller != 0x00648A1Fu) return;
    uint32_t manager = M32(0x00A982B8u), node = c->eax;
    if (manager && node && node != manager + 0x70 && M32(node + 0x10) > 0xBFC67884u)
        c->eax = manager + 0x70;
}

/* Premises inherit an Attrib instance at +4. D5DFD829 is its trigger key,
 * not its own collection key. Missing fields decline the exception. */
static uint32_t carbon_rockplaces_trigger(Cpu *c, uint32_t premises) {
    c->ecx = premises + 4;
    uint32_t args[] = {0xD5DFD829u, 0};
    uint32_t field = call_guest(c, 0x00463A80u, 2, args);
    return field ? M32(field) : 0;
}

/* Reuse the existing tree-successor hook: it is visited during roaming as
 * well as loading. No new guest hook or world/archive regeneration is needed.
 * Calls below can themselves walk trees, so exclude diagnostic recursion. */
static void carbon_rockplaces_trace(Cpu *c) {
    static uint64_t last;
    static int busy;
    if (busy) return;
    uint64_t now = host_ticks();
    if (last && now - last < 1000000000ull) return;
    last = now;
    float position[3];
    if (!private_carbon_player_position(position)) return;
    uint32_t manager = M32(0x00A982B8u);
    if (!manager) return;
    busy = 1;
    Cpu work = *c;
    work.esp -= 256;
    uint32_t player = M32(manager + 0xDC);
    uint32_t node = M32(manager + 0x74);
    for (unsigned count = 0; node && node != manager + 0x70 && count < 128; ++count) {
        uint32_t premises = M32(node + 0x14);
        unsigned type = premises ? M32(premises + 0x20) : 0;
        if (premises && (type == 1 || type == 2) && MF32(premises + 0x2C) > 7000) {
            /* Premises cache physics XYZ; the player reader returns render XYZ. */
            float dx = -position[1] - MF32(premises + 0x24);
            float dy = position[2] - MF32(premises + 0x28);
            float dz = position[0] - MF32(premises + 0x2C);
            float distance2 = dx*dx + dy*dy + dz*dz;
            if (distance2 <= 100) {
                uint32_t key = carbon_rockplaces_trigger(&work, premises);
                uint32_t head = M32(0x00A98170u), trigger = head, found = 0;
                for (unsigned i = 0; trigger && i < 4096; ++i) {
                    work.ecx = trigger + 4;
                    if (call_guest(&work, 0x004613E0u, 0, NULL) == key) {
                        found = trigger;
                        break;
                    }
                    trigger = M32(trigger + 0x20);
                    if (trigger == head) break;
                }
                uint32_t icon = found ? M32(found + 0x9C) : 0;
                uint32_t icons = M32(0x00A98294u);
                unsigned active = 0, listed = icons ? M32(icons + 0x2FC) : 0;
                for (unsigned i = 0; icon && i < listed && i < 256; ++i)
                    active |= M32(M32(icons + 0x300) + i*4) == icon;
                unsigned mask = found ? M16(found + 0x14) : 0;
                uint32_t owner = M32(premises + 0x14);
                unsigned allow = icons ? M8(icons + 0x30D) : 0;
                unsigned lua_active = call_guest(&work, 0x0064B410u, 1, &found) & 0xFF;
                const char *first = owner != player ? "owner" : !found ? "trigger" :
                    !M32(found + 0x70) ? "registration" : !(mask & 0xE000) ? "mask" :
                    !icon ? "icon" : !active ? "active-list" :
                    !(type == 2 && icons ? M8(icons + 0x30C) : allow) ? "allow" : "lua-unobserved";
                diag_event("rockplaces_gate: key=%08X type=%u premises=%08X distance2=%.6g owner=%08X player=%08X trigger=%08X registered=%u mask=%04X icon=%08X icon_flags=%02X active=%u icon_manager=%08X allocated=%u allow30D=%u allow30C=%u lua_IsActiveMenuGate=%u first=%s",
                    key, type, premises, (double)distance2, owner, player, found,
                    found ? M32(found + 0x70) : 0, mask, icon, icon ? M8(icon + 1) : 0,
                    active, icons, icons ? M32(icons + 0x2F8) : 0, allow,
                    icons ? M8(icons + 0x30C) : 0, lua_active, first);
            }
        }
        node = call_guest(&work, 0x00472980u, 1, &node);
    }
    busy = 0;
}

/* 00626F90 caps allocation at 256; 0061DEA0 and both map callers have
 * fixed 256-entry stack tables. Recover all imported places by removing the
 * last disposable hiding/breaker icon through 0062DBF0, preserving the native
 * pool and active partition. Array malloc/free (006A1560/006A15A0) is untouched.
 * 00635760 supplies the native lot, shop and safehouse type/color/art below. */
static void carbon_rockplaces_icons(Cpu *c) {
    static const uint32_t keys[] = {
        0xDAF7164Eu, 0x2F8CA402u, 0xE925D054u,
        0xDAA53BEFu, 0x7443133Du, 0xBEF9B20Bu, 0xAC50BE69u,
        0x77505801u, 0xCF399E40u, 0xA8BA10E0u, 0x01E4F9A6u,
        0x4806D478u, 0xC9C85245u, 0xEB9E71EBu, 0x0FE75EDFu
    };
    uint32_t manager = M32(0x00A98294u);
    if (!manager || !M32(manager + 0x300)) return;
    Cpu work = *c;
    work.esp -= 128;
    for (unsigned i = 0; i < sizeof(keys)/sizeof(*keys); ++i) {
        if (!(carbon_rockplaces_pending & (1u << i))) continue;
        work.ecx = manager;
        uint32_t trigger = call_guest(&work, 0x00614450u, 1, keys + i);
        unsigned mask = i < 3 ? 0x2000 : i < 7 ? 0x8000 : 0x4000;
        if (!trigger || !(M16(trigger + 0x14) & mask)) continue;
        uint32_t before = M32(trigger + 0x9C);
        unsigned evicted_type = 0;
        if (!before) {
            unsigned count = M32(manager + 0x2F8);
            if (count > 256) continue;
            work.ecx = trigger + 4;
            uint32_t field_args[] = {0x9F743A0Eu, 0};
            uint32_t position = call_guest(&work, 0x00463A80u, 2, field_args);
            if (!position) continue;
            if (count == 256) {
                unsigned index = count;
                while (index) {
                    uint32_t icon = M32(M32(manager + 0x300) + (--index)*4);
                    if (icon && (M8(icon + 1) & 0x10) &&
                        (M8(icon) == 0x0D || M8(icon) == 0x0E)) {
                        evicted_type = M8(icon);
                        work.ecx = manager;
                        call_guest(&work, 0x0062DBF0u, 1, &index);
                        break;
                    }
                }
                if (!evicted_type) continue;
            }
            uint32_t args[] = {i < 3 ? 0xBu : i < 7 ? 0xAu : 0xCu, position, 0, 0};
            work.ecx = manager;
            uint32_t icon = call_guest(&work, 0x00626F90u, 4, args);
            if (!icon) continue;
            M32(icon + 0x20) = i < 3 ? 0xFF00A0C6u : i < 7 ? 0xFF66BA44u : 0xFFF0C000u;
            uint32_t name = i < 3 ? 0x009D8A00u : i < 7 ? 0x009D89D8u : 0x009D89E8u;
            M32(icon + 0x24) = call_guest(&work, 0x00471050u, 1, &name);
            M8(icon + 1) |= 3;
            M32(trigger + 0x9C) = icon;
        }
        if (diag_on)
            diag_event("rockplaces_icons: key=%08X before=%08X icon=%08X allocated=%u evicted_type=%02X",
                keys[i], before, M32(trigger + 0x9C), M32(manager + 0x2F8), evicted_type);
        carbon_rockplaces_pending &= ~(1u << i);
    }
}

void carbon_rockplaces_owner(Cpu *c, void (*original)(Cpu *)) {
    uint32_t premises = c->ecx;
    original(c);
    if (!carbon_rockplaces_enabled() || M32(premises + 0x20) != 1) return;
    Cpu work = *c;
    work.esp -= 128;
    uint32_t key = carbon_rockplaces_trigger(&work, premises);
    if (!carbon_rockplaces_scope(key)) return;
    uint32_t manager = M32(0x00A982B8u);
    uint32_t player = manager ? M32(manager + 0xDC) : 0;
    if (!player) return;
    work.ecx = premises;
    call_guest(&work, 0x00617850u, 1, &player);
    carbon_rockplaces_pending = 0x7FFFu;
}

static void carbon_rockplaces_append(Cpu *c, uint32_t map, uint32_t premises,
                                     uint32_t key, uint32_t package) {
    unsigned number = key == 0xDAF7164Eu ? 5 : key == 0x2F8CA402u ? 6 : 7;
    uint32_t hash_args[] = {0x009D4608u, number}; /* native CAR_LOT_%d */
    uint32_t hash = call_guest(c, 0x005711C0u, 2, hash_args);
    c->ecx = package;
    uint32_t object = call_guest(c, 0x005F3760u, 1, &hash);
    if (!object || M32(object + 0x18) != 1) return;

    /* 00620BE0 caches render XYZ at +24; 004B5900 returns raw XY as
     * (+2C, -[+24]). Use exactly that pair with native map projection. */
    uint32_t xy = c->esp;
    MF32(xy) = MF32(premises + 0x2C);
    MF32(xy + 4) = -MF32(premises + 0x24);
    uint32_t projection[] = {xy, xy + 4, map + 0x44, map + 0x4C};
    call_guest(c, 0x0056E770u, 4, projection);
    uint32_t size = 0x30;
    uint32_t item = call_guest(c, 0x006A1560u, 1, &size);
    if (!item) return;
    c->ecx = item;
    uint32_t args[] = {0x02000000u, object, xy, 0, key, 0};
    item = call_guest(c, 0x0059DD90u, 6, args);
    /* Native intrusive list append at 005AD925. Constructor returns this. */
    uint32_t node = item + 4, tail = M32(map + 0x68);
    M32(tail) = node;
    M32(map + 0x68) = node;
    M32(node + 4) = tail;
    M32(node) = map + 0x64;
}

void carbon_rockplaces_map(Cpu *c, void (*original)(Cpu *)) {
    uint32_t map = c->ecx;
    original(c);
    if (!carbon_rockplaces_enabled()) return;
    uint32_t manager = M32(0x00A982B8u), name = M32(map + 0x0C);
    if (!manager || !name || !M8(name)) return;
    Cpu work = *c;
    work.esp -= 128; /* scratch XY above all nested guest calls */
    work.ecx = M32(0x00A97B40u);
    uint32_t package = call_guest(&work, 0x005858D0u, 1, &name);
    package = package ? M32(package + 0x20) : 0;
    if (!package) return;
    uint32_t player = M32(manager + 0xDC);
    if (!player) return;
    /* Same sorted premises tree as 0062E3C0: +70 sentinel, +74 first,
     * node +14 premises. No areas/zones are created or modified. */
    for (uint32_t node = M32(manager + 0x74); node != manager + 0x70;) {
        uint32_t premises = M32(node + 0x14);
        if (premises && M32(premises + 0x20) == 1 && M32(premises + 0x14) == player) {
            uint32_t key = carbon_rockplaces_trigger(&work, premises);
            if (carbon_rockplaces_scope(key))
                carbon_rockplaces_append(&work, map, premises, key, package);
        }
        node = call_guest(&work, 0x00472980u, 1, &node);
    }
}
#endif
