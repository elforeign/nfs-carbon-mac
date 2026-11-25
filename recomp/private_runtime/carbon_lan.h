/* Explicit LAN entry only. Addresses are IPv4 host order; zero means loopback. */
#pragma once
#include "host.h"
typedef struct {
    uint64_t id;
    const char *name;
    uint16_t port;
    uint32_t address;
} CarbonLanIdentity;
unsigned carbon_lan_session_open(Cpu *,const CarbonLanIdentity *,const CarbonLanIdentity *,const char *,int);
int carbon_lan_session_tick(Cpu *,unsigned);
int carbon_lan_session_send(Cpu *,unsigned,const void *,unsigned,int);
unsigned carbon_lan_session_receive(unsigned,void *,unsigned,int *);
void carbon_lan_session_close(Cpu *,unsigned);
uint16_t carbon_lan_session_reserve(Cpu *,uint32_t);
void carbon_lan_session_unreserve(Cpu *,uint16_t);

enum { CARBON_LAN_IDLE, CARBON_LAN_BROWSE, CARBON_LAN_HOST,
       CARBON_LAN_JOINING, CARBON_LAN_ROOM, CARBON_LAN_ERROR };
enum { CARBON_LAN_ROWS=8, CARBON_LAN_EXPIRY_MS=3000 };
typedef struct {
    uint64_t id,nonce,seen;
    uint32_t address;
    uint16_t control_port,game_port;
    char name[32];
} CarbonLanListing;
typedef struct {
    int state,fd,hosting,local_ready,remote_ready,agreed;
    unsigned session,count;
    uint32_t address;
    uint16_t game_port,control_port;
    uint64_t id,nonce,attempt,remote_attempt,last_query,last_send,deadline,last_peer;
    char name[32],remote_name[32],ticket[64],status[160];
    CarbonLanListing rows[CARBON_LAN_ROWS],peer;
} CarbonLanLobby;
int carbon_lan_lobby_open(Cpu *,CarbonLanLobby *,const char *,int);
void carbon_lan_lobby_tick(Cpu *,CarbonLanLobby *);
int carbon_lan_lobby_join(Cpu *,CarbonLanLobby *,unsigned);
void carbon_lan_lobby_ready(CarbonLanLobby *,int);
void carbon_lan_lobby_close(Cpu *,CarbonLanLobby *);

/* Settings enqueue actions; the FE hook consumes them on the guest thread. */
void carbon_lan_menu_host(int),carbon_lan_menu_browse(int),carbon_lan_menu_leave(int);
void carbon_lan_menu_status(char *,int);
