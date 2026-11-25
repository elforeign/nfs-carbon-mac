/* The retained FeOnlineGameRoom screen supplies its package, eight authored
 * slots, FE input and destruction. Only explicit LAN entry replaces its
 * online service notifications; ordinary online/startup paths pass through.
 * 005D0420 selects this package in states 8/10 (host/client); 005C7A60
 * constructs it, 005CC140 receives notifications, 005BEBE0 destroys it.
 * The FE engine queues push/pop through 005F71C0/005F71E0. */
#include "carbon_lan.h"
#include "settings.h"
#include <stdlib.h>

void portmenu_status(const char *,...);
static struct {
    CarbonLanLobby lobby;
    unsigned action,selected;
    uint32_t room,text;
    int loading,closing;
    uint64_t deadline,draw_at;
} carbon_lan_menu;

static uint32_t clm_call(Cpu *c,uint32_t fn,uint32_t self,int n,const uint32_t *a) {
    Cpu work=*c;work.esp-=256;work.ecx=self;return call_guest(&work,fn,n,a);
}
static uint32_t clm_hash(const char *name) {
    uint32_t hash=UINT32_MAX;for(;*name;++name)hash=hash*33+(unsigned char)*name;return hash;
}
static uint32_t clm_engine(void) {
    uint32_t wrapper=M32(0x00A97A78);return wrapper?M32(wrapper):0;
}
static void clm_request(unsigned action) {
    carbon_lan_menu.action=action;
    portmenu_status("Close settings to enter or leave the LAN room.");
}
void carbon_lan_menu_host(int value) {(void)value;clm_request(1);}
void carbon_lan_menu_browse(int value) {(void)value;clm_request(2);}
void carbon_lan_menu_leave(int value) {(void)value;clm_request(3);}
void carbon_lan_menu_status(char *buffer,int n) {
    snprintf(buffer,n,"%s",carbon_lan_menu.lobby.status[0]?carbon_lan_menu.lobby.status:"Offline - choose Host LAN or Browse LAN.");
}
static void clm_text(Cpu *c,uint32_t package,uint32_t hash,const char *text) {
    uint32_t p=carbon_lan_menu.text;snprintf((char *)G+p+128,256,"%s",text);
    uint32_t a[]={package,hash,p+64,p+128};clm_call(c,0x005A0910,0,4,a);
}
static void clm_visible(Cpu *c,uint32_t package,uint32_t hash,int visible) {
    uint32_t object=clm_call(c,0x005983F0,0,1,&package);
    if(object)object=clm_call(c,0x005F3760,object,1,&hash);
    if(object)M32(object+0x1C)=(M32(object+0x1C)&~1u)|0x02400000u|!visible;
}
static void clm_draw(Cpu *c) {
    uint32_t room=carbon_lan_menu.room;if(!room||!carbon_lan_menu.text)return;
    CarbonLanLobby *l=&carbon_lan_menu.lobby;uint32_t package=M32(room+0xC);
    char text[256],name[40];
    clm_text(c,package,clm_hash("TITLE"),l->state==CARBON_LAN_BROWSE?"LAN GAMES":"LAN ROOM");
    /* Retained room ObjD: title subtitle group, two footer label groups,
     * race settings panel/header, and the three online-only footer actions. */
    clm_text(c,package,0xEE60FFCA,"LOCAL NETWORK");
    clm_text(c,package,0x666D40DF,l->state==CARBON_LAN_BROWSE?"JOIN":"READY");
    clm_text(c,package,0x59AF1946,l->state==CARBON_LAN_BROWSE?"JOIN":"READY");
    clm_visible(c,package,0x498C629C,0);
    clm_visible(c,package,0xFA1B25AA,0);
    clm_visible(c,package,0x1D4CB506,0);
    clm_visible(c,package,0x64035FE5,0);
    clm_visible(c,package,0xCFA78975,0);
    if(carbon_lan_menu.selected>=l->count)carbon_lan_menu.selected=0;
    for(unsigned i=0;i<8;++i) {
        int visible=l->state==CARBON_LAN_BROWSE?i<l->count:i<(l->peer.id?2u:1u);
        snprintf(name,sizeof name,"PLAYER_SLOT_%u",i+1);clm_visible(c,package,clm_hash(name),visible);
        if(!visible)continue;
        if(l->state==CARBON_LAN_BROWSE)snprintf(text,sizeof text,"%s%s",i==carbon_lan_menu.selected?"> ":"  ",l->rows[i].name);
        else snprintf(text,sizeof text,"%s / %s",i?l->peer.name:l->name,
             l->state==CARBON_LAN_ROOM?(i?(l->agreed?(l->remote_ready?"READY":"NOT READY"):"SYNCING"):
                                                     (l->local_ready?"READY":"NOT READY")):"WAITING");
        snprintf(name,sizeof name,"PLAYER%u",i+1);clm_text(c,package,clm_hash(name),text);
    }
    /* This is the room's existing status banner (005A9440). */
    snprintf((char *)G+carbon_lan_menu.text+128,256,"%s",l->status);
    uint32_t status=carbon_lan_menu.text+128;
    clm_call(c,0x005A9440,room,1,&status);
}
void carbon_lan_menu_construct(Cpu *c,void (*original)(Cpu *)) {
    uint32_t self=c->ecx;original(c);
    if(!carbon_lan_menu.loading)return;
    carbon_lan_menu.loading=0;carbon_lan_menu.room=self;carbon_lan_menu.draw_at=0;
    if(diag_on)diag_event("CARBON LAN FeOnlineGameRoom constructed=%08X",self);
    clm_draw(c);
}
void carbon_lan_menu_destroy(Cpu *c,void (*original)(Cpu *)) {
    uint32_t text=0;
    if(c->ecx==carbon_lan_menu.room&&carbon_lan_menu.room) {
        carbon_lan_lobby_close(c,&carbon_lan_menu.lobby);
        carbon_lan_menu.room=0;carbon_lan_menu.loading=carbon_lan_menu.closing=0;
        text=carbon_lan_menu.text;
        carbon_lan_menu.text=0;
        if(diag_on)diag_event("CARBON LAN FeOnlineGameRoom closed");
    }
    original(c);
    if(text)gfree(text);
}
void carbon_lan_menu_notification(Cpu *c,void (*original)(Cpu *)) {
    if(!carbon_lan_menu.room||c->ecx!=carbon_lan_menu.room){original(c);return;}
    CarbonLanLobby *l=&carbon_lan_menu.lobby;uint32_t event=arg(c,0);
    if(event==0x406415E3) { /* PAD_ACCEPT */
        if(l->state==CARBON_LAN_BROWSE)carbon_lan_lobby_join(c,l,carbon_lan_menu.selected);
        else if(l->state==CARBON_LAN_ROOM)carbon_lan_lobby_ready(l,!l->local_ready);
    } else if(event==0x911AB364) { /* PAD_BACK */
        /* Cancellation closes the invitation before queuing package removal. */
        carbon_lan_lobby_close(c,l);carbon_lan_menu.action=3;
    } else if(l->state==CARBON_LAN_BROWSE&&l->count) {
        if(event==0x72619778)carbon_lan_menu.selected=(carbon_lan_menu.selected+l->count-1)%l->count;
        else if(event==0x911C0A4B)carbon_lan_menu.selected=(carbon_lan_menu.selected+1)%l->count;
    }
    carbon_lan_menu.draw_at=0;c->esp+=20;
}
/* Called from the existing Carbon Present provider after settings input. */
void carbon_lan_menu_tick(Cpu *c) {
    if(!carbon_lan_menu.action&&!carbon_lan_menu.room&&!carbon_lan_menu.loading)return;
    unsigned action=carbon_lan_menu.action;
    uint32_t engine=clm_engine();uint64_t now=host_ticks()/1000000;
    if(action==3) {
        carbon_lan_menu.action=0;
        carbon_lan_lobby_close(c,&carbon_lan_menu.lobby);
        if((carbon_lan_menu.room||carbon_lan_menu.loading)&&!carbon_lan_menu.closing&&engine) {
            carbon_lan_menu.closing=1;clm_call(c,0x005F71E0,engine,0,NULL);
        }
        return;
    }
    if(action) {
        carbon_lan_menu.action=0;
        if(carbon_lan_menu.room||carbon_lan_menu.loading||M32(0x00A99BBC)!=3||!engine||M32(0x00A97B7C)) {
            portmenu_status("Choose LAN from the main menu after closing other screens.");return;
        }
        if(!carbon_lan_lobby_open(c,&carbon_lan_menu.lobby,settings_text("network.persona"),action==1)) {
            portmenu_status("%s",carbon_lan_menu.lobby.status);
            carbon_lan_lobby_close(c,&carbon_lan_menu.lobby);return;
        }
        uint32_t text=gmalloc_try(512);
        if(!text){carbon_lan_lobby_close(c,&carbon_lan_menu.lobby);return;}
        carbon_lan_menu.text=text;strcpy((char *)G+text,"FeOnlineGameRoom.fng");strcpy((char *)G+text+64,"%s");
        carbon_lan_menu.loading=1;carbon_lan_menu.closing=0;carbon_lan_menu.selected=0;carbon_lan_menu.deadline=now+10000;
        uint32_t mask=clm_call(c,0x00584160,M32(0x00A97A78),0,NULL),a[]={text,mask};
        clm_call(c,0x005F71C0,engine,2,a);
    }
    if(carbon_lan_menu.loading&&now>=carbon_lan_menu.deadline) {
        carbon_lan_menu.action=3;portmenu_status("The LAN room did not load.");return;
    }
    if(carbon_lan_menu.closing)return;
    carbon_lan_lobby_tick(c,&carbon_lan_menu.lobby);
    if(!carbon_lan_menu.draw_at||now-carbon_lan_menu.draw_at>=250) {
        clm_draw(c);carbon_lan_menu.draw_at=now;
        if(diag_on&&carbon_lan_menu.lobby.state==CARBON_LAN_ROOM)
            diag_event("CARBON LAN room personas=%s/%s ready=%d/%d agreed=%d",
                       carbon_lan_menu.lobby.name,carbon_lan_menu.lobby.peer.name,
                       carbon_lan_menu.lobby.local_ready,carbon_lan_menu.lobby.remote_ready,carbon_lan_menu.lobby.agreed);
    }
}
