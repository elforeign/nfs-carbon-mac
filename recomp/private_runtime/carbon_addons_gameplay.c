/* Retail consumers: movie request 00595210 / title 00857630;
 * IPerpetrator heat setter 0040AB70 (interface +1C); catch-up 00643100;
 * SkipCareerIntro script query 0064C560; cash award 004CD3D0.
 * Settings are explicit opt-ins. Native setters, flow and serialization own
 * career changes; no save bytes or pursuit limits are rewritten here. */
#include "host.h"
#include "settings.h"
#include <limits.h>
#include <stdlib.h>
#include <string.h>

extern int diag_on;
extern void diag_event(const char *, ...);
extern void portmenu_status(const char *, ...);

static int cadd_title_seen;
static uint32_t cadd_pending_profile;
static uint64_t cadd_pending_cash;
static Setting cadd_rows[];

/* 0065C550 resolves player 0 -> simable -> IPerpetrator. The native
 * 0060CB50/0060C1B0 lookup is a lower_bound on eight-byte interface entries. */
static uint32_t cadd_player_perp(void) {
    uint32_t list = M32(0x00A9FF5Cu), count = M32(0x00A9FF64u);
    if (!list || !count || count > 2) return 0;
    uint32_t player = M32(list);
    if (player < 8 || !M32(player) || M32(M32(player) + 4) != 0x0076E810u) return 0;
    uint32_t sim = M32(player - 8), map = sim ? M32(sim + 4) : 0;
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

void carbon_addons_movie(Cpu *c, void (*original)(Cpu *)) {
    uint32_t saved = M32(0x00A9E6D8u);
    int skip = !cadd_title_seen && settings_get("gameplay.skip_movies") > 0;
    if (skip) M32(0x00A9E6D8u) = 1;
    if (diag_on) diag_event("carbon addons: movie=%s title=%d skip=%d",
                           (const char *)gptr(c->ecx + 0x1C), cadd_title_seen, skip);
    original(c);
    M32(0x00A9E6D8u) = saved;
}

void carbon_addons_title(Cpu *c, void (*original)(Cpu *)) {
    cadd_title_seen = 1; /* permanent for this process, including returning to title */
    if (diag_on) diag_event("carbon addons: title reached; story movies retained");
    original(c);
}

void carbon_addons_heat(Cpu *c, void (*original)(Cpu *)) {
    int level = settings_get("gameplay.heat");
    uint32_t address = c->esp + 4, saved = M32(address);
    if (level > 0 && c->ecx == cadd_player_perp()) MF32(address) = (float)level;
    original(c);
    M32(address) = saved;
}

void carbon_addons_catchup(Cpu *c, void (*original)(Cpu *)) {
    if (settings_get("gameplay.no_catchup") <= 0) { original(c); return; }
    c->eax &= ~255u; /* same false result as native Quick Race catch-up Off */
    c->esp += 24; /* thiscall ret 14 */
}

void carbon_addons_prologue(Cpu *c, void (*original)(Cpu *)) {
    original(c);
    unsigned native = c->eax & 255;
    if (settings_get("gameplay.skip_prologue") > 0) c->eax = (c->eax & ~255u) | 1;
    if (diag_on) diag_event("carbon addons: SkipCareerIntro native=%u effective=%u", native, c->eax & 255);
}

/* Game_IsCareerMode (0064BAF0) is race+6A18 == 3. Limit awards to active
 * career gameplay, where player 0 has a loaded user and native save support.
 * Quick Race can retain that same user, so a nonnull profile alone is unsafe. */
static uint32_t cadd_cash_profile(void) {
    uint32_t race = M32(0x00A98284u), root = M32(0x00A97A7Cu);
    if (M32(0x00A99BBCu) != 6 || !race || M32(race + 0x6A18) != 3 || !root) return 0;
    uint32_t slot = M32(root + 0xD4);
    return slot ? M32(slot) : 0;
}

static void cadd_queue_cash(uint32_t amount) {
    uint32_t profile = cadd_cash_profile();
    if (!profile) { portmenu_status("Enter Career free roam to add cash."); return; }
    if (cadd_pending_profile != profile) cadd_pending_cash = 0;
    cadd_pending_profile = profile;
    cadd_pending_cash += amount;
}
static void cadd_cash20(int v) { (void)v; cadd_queue_cash(20000); }
static void cadd_cash50(int v) { (void)v; cadd_queue_cash(50000); }
static void cadd_cash100(int v) { (void)v; cadd_queue_cash(100000); }
static void cadd_cash_typed(int v) {
    (void)v;
    Setting *row = settings_find("gameplay.cash_amount");
    uint32_t amount = 0;
    if (!row || !row->text[0]) return;
    for (const unsigned char *p = (const unsigned char *)row->text; *p; ++p) {
        if (*p < '0' || *p > '9' || amount > (9999999u - (*p - '0')) / 10) {
            portmenu_status("Enter digits from 1 to 9,999,999."); return;
        }
        amount = amount * 10 + *p - '0';
    }
    if (!amount) { portmenu_status("Enter digits from 1 to 9,999,999."); return; }
    cadd_queue_cash(amount);
    row->text[0] = 0;
}

static const char *const cadd_heat_choices[] = {"Game", "1", "2", "3", "4", "5", "6"};
static Setting cadd_rows[] = {
    {.id="gameplay.skip_movies", .category=SET_GAMEPLAY, .order=70, .label="Skip Intro Movies",
     .help="Skip startup movies until the title screen. Story movies still play.",
     .type=SET_TOGGLE, .env="NFS_CARBON_SKIP_MOVIES"},
    {.id="gameplay.heat", .category=SET_GAMEPLAY, .order=20, .label="Heat Level",
     .help="Hold player heat at this level, including during pursuits. Game returns control to the game. Level 6 is the native special pursuit level.",
     .type=SET_CHOICE, .choices=cadd_heat_choices, .nchoices=7, .env="NFS_CARBON_HEAT"},
    {.id="gameplay.no_catchup", .category=SET_GAMEPLAY, .order=30, .label="No Catch-up (no rubber banding)",
     .help="Rivals race at their own pace. Off retains the game's catch-up rules.",
     .type=SET_TOGGLE, .env="NFS_CARBON_NO_CATCHUP"},
    {.id="gameplay.starting_bonus", .category=SET_GAMEPLAY, .order=50, .label="Starting Bonus ($10,000)",
     .help="Use the native prior-game save bonus when creating a career, even without a prior save. Existing careers are unchanged.",
     .type=SET_TOGGLE, .env="NFS_CARBON_STARTING_BONUS"},
    {.id="gameplay.skip_prologue", .category=SET_GAMEPLAY, .order=60, .label="Skip Career Prologue",
     .help="Use the game's SkipCareerIntro script branch for new careers.",
     .type=SET_TOGGLE, .env="NFS_CARBON_SKIP_PROLOGUE"},
    {.id="gameplay.cash_20000", .category=SET_GAMEPLAY, .order=140, .label="+20,000",
     .type=SET_ACTION, .pref="", .apply=cadd_cash20},
    {.id="gameplay.cash_50000", .category=SET_GAMEPLAY, .order=150, .label="+50,000",
     .type=SET_ACTION, .pref="", .apply=cadd_cash50},
    {.id="gameplay.cash_100000", .category=SET_GAMEPLAY, .order=160, .label="+100,000",
     .type=SET_ACTION, .pref="", .apply=cadd_cash100},
    {.id="gameplay.cash_amount", .category=SET_GAMEPLAY, .order=170, .label="Add amount",
     .help="Enter digits from 1 to 9,999,999, then submit. Saved with your career.",
     .type=SET_TEXT, .pref="", .apply=cadd_cash_typed},
};

void carbon_addons_gameplay_init(void) {
    for (unsigned i = 0; i < sizeof cadd_rows / sizeof *cadd_rows; ++i) settings_add(&cadd_rows[i]);
}

/* Diagnostic key script invokes the same actions as F10, once Career is
 * available. No second cash path: validation, queuing and award stay above. */
int carbon_addons_gameplay_script(const char *action) {
    static const char *const actions[] = {"cash_20000","cash_50000","cash_100000","cash_amount="};
    for (unsigned i=0;i<4;++i) {
        size_t length=strlen(actions[i]);
        if (i==3 ? strncmp(action,actions[i],length) : strcmp(action,actions[i])) continue;
        if (!cadd_cash_profile()) return 0;
        Setting *row=&cadd_rows[5+i];
        if (i==3) snprintf(row->text,sizeof row->text,"%s",action+length);
        row->apply(0);
        if (diag_on) diag_event("carbon addons: F10 action %s",action);
        return 1;
    }
    if (diag_on) diag_event("carbon addons: unknown action %s",action);
    return 1;
}

void carbon_addons_gameplay_frame(void) {
    uint32_t profile = cadd_cash_profile();
    for (unsigned i = 5; i < 9; ++i) {
        cadd_rows[i].type = !profile ? SET_INFO : i == 8 ? SET_TEXT : SET_ACTION;
        cadd_rows[i].help = !profile ? "Enter Career free roam to add cash." : i == 8 ?
            "Enter digits from 1 to 9,999,999, then submit. Saved with your career." :
            "Add cash once. Saved with your career as usual.";
    }
    uint64_t amount = cadd_pending_cash;
    uint32_t target = cadd_pending_profile;
    cadd_pending_cash = 0; cadd_pending_profile = 0;
    int level = settings_get("gameplay.heat");
    uint32_t perp = level > 0 ? cadd_player_perp() : 0;
    if (!amount && (!perp || MF32(perp + 0x1C) == (float)level)) return;
    static uint32_t stack;
    if (!stack) stack = galloc(65536);
    Cpu query = {0}; query.esp = stack + 65536; query.cw = 0x37F;
    if (perp) {
        uint32_t heat; float value = (float)level; memcpy(&heat, &value, 4);
        query.ecx = perp; call_guest(&query, 0x0040AB70u, 1, &heat);
    }
    if (!amount) return;
    if (!profile || profile != target) { portmenu_status("Career changed; cash was not added."); return; }
    uint32_t before = M32(profile + 0x24330);
    if (amount > (uint64_t)INT32_MAX - 10000000u || before > INT32_MAX - 10000000u - amount) {
        portmenu_status("Cash award would exceed the supported balance."); return;
    }
    uint32_t award = (uint32_t)amount;
    /* Property 1778's additive provider. It also updates earnings/unlocks. */
    call_guest(&query, 0x004CD3D0u, 1, &award);
    uint32_t after = M32(profile + 0x24330);
    if (diag_on) diag_event("carbon addons: cash before=%u requested=%u after=%u", before, award, after);
    portmenu_status("Cash: +%u (balance %u). Save your career to keep it.", award, after);
}
