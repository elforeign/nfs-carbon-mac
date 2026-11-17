/* FeBonusCards: six {type,param,selected} entries at +E0, stride C, +DC
 * count. 0084E090 notification, 0084E1D0 navigation, 0084E220 selection and
 * 0084DEE0 completion inline a limit of two. Retain all native paths at Game;
 * custom counts use the same award, array-scroller and completion operations.
 * 0084E600 redraw receives self+28. Its 0084E8E6 mov eax,2 / 0084E8EB
 * sub eax,edx leaves remaining picks below the language hash at 0084E8F3.
 * The lookup returns a format string; 0084E902 consumes the retained count
 * as the fourth argument. Refresh that text for custom counts. */
#include "host.h"
#include "settings.h"

static const char *const cadd_cards_choices[] = {"Game (2)","1","2","3","4","5","6"};
static const char *const cadd_cards_values[] = {"game","1","2","3","4","5","6"};
void carbon_addons_cards_init(void) {
    static Setting row = {.id="gameplay.markers", .category=SET_GAMEPLAY, .order=10,
        .label="Reward cards per boss", .help="Cards you turn after a boss victory. Game keeps the original two of six.",
        .type=SET_CHOICE, .choices=cadd_cards_choices, .values=cadd_cards_values,
        .nchoices=7, .env="NFS_CARBON_CARDS"};
    settings_add(&row);
}
static unsigned cadd_cards_count(uint32_t self) {
    unsigned count = M32(self + 0xDC), selected = 0;
    if (count > 6) count = 6;
    for (unsigned i = 0; i < count; ++i)
        selected += M32(self + 0xE0 + 12*i) && M8(self + 0xE8 + 12*i);
    return selected;
}
static unsigned cadd_cards_limit(uint32_t self) {
    int value = settings_get("gameplay.markers");
    unsigned count = M32(self + 0xDC), limit = value > 0 ? (unsigned)value : 2;
    return count < limit ? count : limit;
}
static uint32_t cadd_cards_call(Cpu *c, uint32_t self, uint32_t fn, int n, const uint32_t *args) {
    c->ecx = self;
    return call_guest(c,fn,n,args);
}
void carbon_addons_cards_redraw(Cpu *c, void (*original)(Cpu *)) {
    if (settings_get("gameplay.markers") <= 0) { original(c); return; }
    uint32_t self = c->ecx - 0x28;
    original(c);
    Cpu work = *c; work.esp -= 256;
    uint32_t args[4] = {0x72E21D2Au,cadd_cards_limit(self)-cadd_cards_count(self)};
    uint32_t text = cadd_cards_call(&work,0,0x00578830u,2,args);
    /* Native pops only the lookup hash, retaining this int for FE printf. */
    args[3] = args[1];
    args[0] = M32(self+0xC); args[1] = 0xBA94538Eu; args[2] = text;
    cadd_cards_call(&work,0,0x005A0910u,4,args);
}
void carbon_addons_cards_complete(Cpu *c, void (*original)(Cpu *)) {
    if (settings_get("gameplay.markers") <= 0) { original(c); return; }
    unsigned limit = cadd_cards_limit(c->ecx);
    c->eax = limit && cadd_cards_count(c->ecx) >= limit;
    c->esp += 4;
}
void carbon_addons_cards_navigation(Cpu *c, void (*original)(Cpu *)) {
    if (settings_get("gameplay.markers") <= 0) { original(c); return; }
    if (cadd_cards_count(c->ecx) >= cadd_cards_limit(c->ecx)) {
        c->eax = arg(c,1) == 4 ? 4 : UINT32_MAX;
        c->esp += 12;
    } else {
        /* Native tail target when fewer than two have been chosen. */
        uint32_t esp=c->esp, args[2]={arg(c,0),arg(c,1)};
        c->eax=call_guest(c,0x00576A60u,2,args);
        c->esp=esp+12;
    }
}
void carbon_addons_cards_select(Cpu *c, void (*original)(Cpu *)) {
    if (settings_get("gameplay.markers") <= 0) { original(c); return; }
    uint32_t self = c->ecx, index = arg(c,0), entry = self + 0xE0 + 12*index;
    Cpu work = *c; work.esp -= 256;
    if (index < 6 && index < M32(self + 0xDC) && !M8(entry + 8) &&
        cadd_cards_count(self) < cadd_cards_limit(self)) {
        M8(entry + 8) = 1;
        uint32_t args[4] = {M32(entry),M32(entry + 4)};
        cadd_cards_call(&work,M32(0x00A8AD04u),0x004D53A0u,2,args);
        uint32_t item = cadd_cards_call(&work,self+0x28,0x005873E0u,1,&index);
        M32(item + 0x10) = self + 0x128;
        item = cadd_cards_call(&work,self+0x28,0x00587410u,1,&index);
        M8(item + 0x14) = 0;
        cadd_cards_call(&work,self+0x28,M32(M32(self+0x28)+8),0,NULL);
        if (cadd_cards_count(self) >= cadd_cards_limit(self) && M32(self+0x14)) {
            args[0]=0; args[1]=0; args[2]=1;
            cadd_cards_call(&work,M32(self+0x14),0x005F3880u,3,args);
            args[0]=0x009F9A18u;
            uint32_t hash = cadd_cards_call(&work,0,0x005EA670u,1,args);
            args[0]=hash; args[1]=M32(self+0xC); args[2]=0;
            cadd_cards_call(&work,M32(0x00A97A78u),0x00598540u,3,args);
            args[0]=M32(self+0xC); args[1]=0x7C73CA77u; args[2]=0x5079C8F8u; args[3]=1;
            cadd_cards_call(&work,0,0x005A02C0u,4,args);
        }
    }
    c->esp += 8;
}
void carbon_addons_cards_notification(Cpu *c, void (*original)(Cpu *)) {
    if (settings_get("gameplay.markers") <= 0) { original(c); return; }
    uint32_t self = c->ecx, args[4] = {arg(c,0),arg(c,1),arg(c,2),arg(c,3)};
    Cpu work = *c; work.esp -= 256;
    if (cadd_cards_count(self) < cadd_cards_limit(self)) {
        if (args[0] == 0x0C407210u) M8(self+0xD8) = 1;
        else if (args[0] == 0x6C699F5Fu) {
            M8(self+0xD8) = 0;
            uint32_t other = M32(self+0x40); uint32_t message[4] = {0x0C407210u,args[1],args[2],args[3]};
            cadd_cards_call(&work,other,M32(M32(other)+8),4,message);
        } else {
            if (!M8(self+0xD8)) cadd_cards_call(&work,self+0x28,0x005CA560u,4,args);
            if (args[0] == 0xABC08912u && args[1]) {
                uint32_t found=0, zero=0;
                uint32_t count=cadd_cards_call(&work,self+0x30,0x0046D450u,1,&zero);
                for (uint32_t i=0;i<count;++i) {
                    uint32_t item=cadd_cards_call(&work,self+0x28,0x005873E0u,1,&i);
                    if (item && M32(item+0xC) && M32(item+0xC)==args[1]) {
                        found=cadd_cards_call(&work,self+0x28,0x00587410u,1,&i); break;
                    }
                }
                uint32_t select[2]={found,M32(self+0x44)};
                cadd_cards_call(&work,self+0x28,0x005A3850u,2,select);
            }
        }
    }
    cadd_cards_call(&work,self,0x005A1B10u,4,args);
    c->esp += 20;
}
