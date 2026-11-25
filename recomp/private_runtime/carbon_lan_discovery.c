/* LAN directory and invitation exchange. The advertised game socket stays
 * bound until the native session adopts it. No sockets exist before an
 * explicit Host/Browse action. Discovery never supplies an online account. */
#include "carbon_lan.h"
#include <arpa/inet.h>
#include <fcntl.h>
#include <ifaddrs.h>
#include <net/if.h>
#include <stdlib.h>
#include <sys/socket.h>
#include <unistd.h>

enum { CDL_FIRST_PORT=42127, CDL_PORTS=8, CDL_PACKET=204,
       CDL_QUERY=1, CDL_ANNOUNCE, CDL_JOIN, CDL_OFFER, CDL_CANCEL,
       CDL_ID=76, CDL_NONCE=84, CDL_ATTEMPT=92, CDL_ADDRESS=100,
       CDL_CONTROL=104, CDL_GAME=106, CDL_NAME=108, CDL_TICKET=140 };
static const char cdl_build[]="baaaaec33873d4ba7e4dbae6a5212049ffdcf9679a35d865d7625b4189952fd3";
static uint64_t cdl_now(void) {return host_ticks()/1000000;}
static uint64_t cdl_random(void) {
    uint64_t value;do {arc4random_buf(&value,sizeof value);}while(!(uint32_t)value||(uint32_t)value==UINT32_MAX);
    return value;
}
static uint64_t cdl_identity(void) {
    uint64_t value;
    /* The persona has 64 bits; its native roster key occupies 16 bits. */
    do {value=cdl_random()&0xFFFFFFFF0000FFFFull;}while(!(uint16_t)value||(uint16_t)value==65535);
    return value;
}
static void cdl_put(unsigned char *p,uint64_t value,unsigned n) {
    for(unsigned i=0;i<n;++i){p[n-1-i]=(unsigned char)value;value>>=8;}
}
static uint64_t cdl_get(const unsigned char *p,unsigned n) {
    uint64_t value=0;for(unsigned i=0;i<n;++i)value=(value<<8)|p[i];return value;
}
static int cdl_text(const char *text,unsigned capacity) {
    unsigned i;for(i=0;i<capacity&&text[i];++i)if((unsigned char)text[i]<32||(unsigned char)text[i]>126)return 0;
    return i&&i<capacity;
}
static int cdl_real(void) {const char *v=getenv("NFS_LAN_REAL");return v&&!strcmp(v,"1");}
static uint32_t cdl_local_address(void) {
    if(!cdl_real())return INADDR_LOOPBACK;
    struct ifaddrs *all=NULL;uint32_t address=0;
    if(getifaddrs(&all))return 0;
    for(struct ifaddrs *p=all;p;p=p->ifa_next) {
        if(!p->ifa_addr||p->ifa_addr->sa_family!=AF_INET||!(p->ifa_flags&IFF_UP)||
           (p->ifa_flags&IFF_LOOPBACK))continue;
        uint32_t a=ntohl(((struct sockaddr_in *)p->ifa_addr)->sin_addr.s_addr);
        if(!a||(a>>24)>=224||(a>>24)==127)continue;
        if(!address||!strcmp(p->ifa_name,"en0"))address=a;
        if(!strcmp(p->ifa_name,"en0"))break;
    }
    freeifaddrs(all);return address;
}
static struct sockaddr_in cdl_address(uint32_t address,uint16_t port) {
    struct sockaddr_in a={0};a.sin_family=AF_INET;a.sin_addr.s_addr=htonl(address);a.sin_port=htons(port);return a;
}
static void cdl_packet(const CarbonLanLobby *l,unsigned kind,unsigned char *packet) {
    memset(packet,0,CDL_PACKET);memcpy(packet,"NFSC-LAN",8);
    packet[8]=1;packet[9]=4;packet[10]=kind;memcpy(packet+12,cdl_build,64);
    cdl_put(packet+CDL_ID,l->id,8);cdl_put(packet+CDL_NONCE,l->hosting?l->nonce:l->peer.nonce,8);
    cdl_put(packet+CDL_ATTEMPT,l->attempt,8);cdl_put(packet+CDL_ADDRESS,l->address,4);
    cdl_put(packet+CDL_CONTROL,l->control_port,2);cdl_put(packet+CDL_GAME,l->game_port,2);
    memcpy(packet+CDL_NAME,l->name,strlen(l->name));
    if(kind==CDL_OFFER)memcpy(packet+CDL_TICKET,l->ticket,strlen(l->ticket));
}
static void cdl_send(CarbonLanLobby *l,unsigned kind,uint32_t address,uint16_t port) {
    if(l->fd<0||!port||(!cdl_real()&&(address>>24)!=127))return;
    unsigned char packet[CDL_PACKET];cdl_packet(l,kind,packet);
    struct sockaddr_in to=cdl_address(address,port);
    sendto(l->fd,packet,sizeof packet,0,(struct sockaddr *)&to,sizeof to);
}
static void cdl_peer_send(CarbonLanLobby *l,unsigned kind) {
    cdl_send(l,kind,l->peer.address,l->peer.control_port);
}
static int cdl_decode(const unsigned char *p,unsigned n,const struct sockaddr_in *from,CarbonLanListing *out) {
    if(n!=CDL_PACKET||memcmp(p,"NFSC-LAN",8)||p[8]!=1||p[9]!=4||p[11]||
       memcmp(p+12,cdl_build,64)||p[10]<CDL_QUERY||p[10]>CDL_CANCEL||
       !cdl_text((const char *)p+CDL_NAME,32))return 0;
    uint32_t address=(uint32_t)cdl_get(p+CDL_ADDRESS,4);
    uint16_t port=(uint16_t)cdl_get(p+CDL_CONTROL,2);
    uint64_t id=cdl_get(p+CDL_ID,8);
    if(!(uint32_t)id||(uint32_t)id>=65535||!port||!cdl_get(p+CDL_GAME,2)||
       address!=ntohl(from->sin_addr.s_addr)||port!=ntohs(from->sin_port)||
       (!cdl_real()&&(address>>24)!=127))return 0;
    memset(out,0,sizeof *out);out->id=id;out->nonce=cdl_get(p+CDL_NONCE,8);
    out->address=address;out->control_port=port;out->game_port=cdl_get(p+CDL_GAME,2);
    memcpy(out->name,p+CDL_NAME,32);out->seen=cdl_now();return 1;
}
static int cdl_same(const CarbonLanListing *a,const CarbonLanListing *b) {
    return a->id==b->id&&a->address==b->address&&a->control_port==b->control_port&&a->game_port==b->game_port;
}
static void cdl_status(CarbonLanLobby *l,const char *text) {
    snprintf(l->status,sizeof l->status,"%s",text);
    if(diag_on)diag_event("CARBON LAN lobby state=%d %s",l->state,text);
}
static void cdl_detach(Cpu *c,CarbonLanLobby *l) {
    if(l->session)carbon_lan_session_close(c,l->session);
    carbon_lan_session_unreserve(c,l->game_port);l->session=0;l->game_port=0;
    memset(&l->peer,0,sizeof l->peer);l->attempt=l->remote_attempt=0;
    l->local_ready=l->remote_ready=l->agreed=0;l->remote_name[0]=l->ticket[0]=0;
}
static void cdl_reset(Cpu *c,CarbonLanLobby *l,const char *reason) {
    cdl_detach(c,l);l->game_port=carbon_lan_session_reserve(c,l->address);
    l->nonce=cdl_random();l->state=l->game_port?(l->hosting?CARBON_LAN_HOST:CARBON_LAN_BROWSE):CARBON_LAN_ERROR;
    cdl_status(l,reason);
}
static int cdl_open_failed(Cpu *c,CarbonLanLobby *l,const char *reason) {
    cdl_detach(c,l);if(l->fd>=0)close(l->fd);l->fd=-1;l->control_port=0;
    l->state=CARBON_LAN_ERROR;cdl_status(l,reason);return 0;
}
void carbon_lan_lobby_close(Cpu *c,CarbonLanLobby *l) {
    if(l->state==CARBON_LAN_IDLE)return;
    if(l->peer.id)cdl_peer_send(l,CDL_CANCEL);
    cdl_detach(c,l);if(l->fd>=0)close(l->fd);
    memset(l,0,sizeof *l);l->fd=-1;
}
int carbon_lan_lobby_open(Cpu *c,CarbonLanLobby *l,const char *name,int host) {
    if(l->state!=CARBON_LAN_IDLE)return 0;
    memset(l,0,sizeof *l);l->fd=-1;l->state=CARBON_LAN_ERROR;
    l->address=cdl_local_address();l->hosting=!!host;l->id=cdl_identity();l->nonce=cdl_random();
    if(name&&*name) {
        if(!cdl_text(name,32))return cdl_open_failed(c,l,"Use a name of 1-31 printable characters.");
        strcpy(l->name,name);
    } else snprintf(l->name,sizeof l->name,"DRIVER-%08X",(uint32_t)l->id);
    l->game_port=carbon_lan_session_reserve(c,l->address);
    if(!l->address||!l->game_port)return cdl_open_failed(c,l,"Could not reserve a local game port.");
    int fd=socket(AF_INET,SOCK_DGRAM,0);
    if(fd<0)return cdl_open_failed(c,l,"Could not open discovery.");
    l->fd=fd;int flags=fcntl(fd,F_GETFL,0);
    if(flags<0||fcntl(fd,F_SETFL,flags|O_NONBLOCK)<0)return cdl_open_failed(c,l,"Could not poll discovery.");
    if(cdl_real()){int yes=1;if(setsockopt(fd,SOL_SOCKET,SO_BROADCAST,&yes,sizeof yes))return cdl_open_failed(c,l,"Could not query the LAN.");}
    int bound=0;
    for(unsigned i=0;i<(host?CDL_PORTS:1);++i) {
        struct sockaddr_in a=cdl_address(host&&cdl_real()?INADDR_ANY:l->address,host?CDL_FIRST_PORT+i:0);
        if(!bind(fd,(struct sockaddr *)&a,sizeof a)){bound=1;break;}
    }
    struct sockaddr_in actual={0};socklen_t size=sizeof actual;
    if(!bound||getsockname(fd,(struct sockaddr *)&actual,&size)||!actual.sin_port) {
        return cdl_open_failed(c,l,"Discovery ports are unavailable.");
    }
    l->control_port=ntohs(actual.sin_port);l->state=host?CARBON_LAN_HOST:CARBON_LAN_BROWSE;
    cdl_status(l,host?"Hosting LAN - waiting for a driver.":"Looking for LAN games.");
    if(diag_on)diag_event("CARBON LAN bound address=%08X game=%u discovery=%u",l->address,l->game_port,l->control_port);
    return 1;
}
int carbon_lan_lobby_join(Cpu *c,CarbonLanLobby *l,unsigned row) {
    (void)c;
    if(l->state!=CARBON_LAN_BROWSE||row>=l->count)return 0;
    CarbonLanListing *p=&l->rows[row];uint64_t now=cdl_now();
    if(now-p->seen>=CARBON_LAN_EXPIRY_MS||!p->nonce||p->id==l->id||
       (uint32_t)p->id==(uint32_t)l->id||!strcmp(p->name,l->name))return 0;
    l->peer=*p;l->attempt=cdl_random();l->deadline=now+5000;l->last_send=0;
    l->state=CARBON_LAN_JOINING;cdl_status(l,"Joining LAN game...");
    cdl_peer_send(l,CDL_JOIN);return 1;
}
static int cdl_session(Cpu *c,CarbonLanLobby *l) {
    CarbonLanIdentity local={l->id,l->name,l->game_port,l->address};
    CarbonLanIdentity remote={l->peer.id,l->peer.name,l->peer.game_port,l->peer.address};
    l->session=carbon_lan_session_open(c,&local,&remote,l->ticket,l->hosting);
    if(l->session)snprintf(l->remote_name,sizeof l->remote_name,"%s",l->peer.name);
    return l->session!=0;
}
static void cdl_receive(Cpu *c,CarbonLanLobby *l,const unsigned char *packet,const CarbonLanListing *p) {
    unsigned type=packet[10];uint64_t attempt=cdl_get(packet+CDL_ATTEMPT,8),now=cdl_now();
    if((uint32_t)p->id==(uint32_t)l->id||!strcmp(p->name,l->name))return;
    if(type==CDL_QUERY&&l->state==CARBON_LAN_HOST) {
        cdl_send(l,CDL_ANNOUNCE,p->address,p->control_port);
    } else if(type==CDL_ANNOUNCE&&l->state==CARBON_LAN_BROWSE&&p->nonce) {
        unsigned i;for(i=0;i<l->count;++i)if(l->rows[i].id==p->id)break;
        if(i<CARBON_LAN_ROWS){l->rows[i]=*p;if(i==l->count)++l->count;}
    } else if(type==CDL_CANCEL&&l->hosting&&l->state==CARBON_LAN_HOST&&p->nonce==l->nonce&&attempt) {
        /* Cancel may overtake Join. Invalidate this announcement before any
         * delayed request can allocate a session for the cancelled attempt. */
        l->nonce=cdl_random();
    } else if(type==CDL_JOIN&&l->hosting&&p->nonce==l->nonce&&attempt) {
        if(l->state==CARBON_LAN_HOST) {
            l->peer=*p;l->attempt=attempt;l->deadline=now+5000;
            snprintf(l->ticket,sizeof l->ticket,"%016llX%016llX",(unsigned long long)cdl_random(),(unsigned long long)cdl_random());
            l->state=CARBON_LAN_JOINING;
            if(!cdl_session(c,l)){cdl_reset(c,l,"Join failed; waiting for a driver.");return;}
            cdl_status(l,"Driver joining...");
        }
        if(cdl_same(&l->peer,p)&&l->attempt==attempt)cdl_peer_send(l,CDL_OFFER);
    } else if(type==CDL_OFFER&&!l->hosting&&l->state==CARBON_LAN_JOINING&&
              cdl_same(&l->peer,p)&&p->nonce==l->peer.nonce&&attempt==l->attempt&&
              cdl_text((const char *)packet+CDL_TICKET,64)) {
        if(!l->session) {
            memcpy(l->ticket,packet+CDL_TICKET,64);
            if(!cdl_session(c,l))cdl_reset(c,l,"Join failed; choose a game again.");
        }
    } else if(type==CDL_CANCEL&&l->peer.id&&cdl_same(&l->peer,p)&&
              p->nonce==(l->hosting?l->nonce:l->peer.nonce)&&attempt==l->attempt) {
        cdl_reset(c,l,"Driver left the LAN game.");
    }
}
void carbon_lan_lobby_ready(CarbonLanLobby *l,int ready) {
    if(l->state==CARBON_LAN_ROOM){l->local_ready=!!ready;l->last_send=0;}
}
void carbon_lan_lobby_tick(Cpu *c,CarbonLanLobby *l) {
    if(l->state==CARBON_LAN_IDLE||l->state==CARBON_LAN_ERROR)return;
    uint64_t now=cdl_now();
    for(unsigned i=0;i<l->count;) {
        if(now-l->rows[i].seen>=CARBON_LAN_EXPIRY_MS){memmove(l->rows+i,l->rows+i+1,(--l->count-i)*sizeof *l->rows);}
        else ++i;
    }
    for(unsigned i=0;i<32;++i) {
        unsigned char packet[CDL_PACKET+1];struct sockaddr_in from={0};socklen_t size=sizeof from;
        ssize_t n=recvfrom(l->fd,packet,sizeof packet,0,(struct sockaddr *)&from,&size);
        if(n<0)break;
        CarbonLanListing p;
        if(from.sin_family==AF_INET&&cdl_decode(packet,(unsigned)n,&from,&p))cdl_receive(c,l,packet,&p);
    }
    if(l->state==CARBON_LAN_BROWSE&&(!l->last_query||now-l->last_query>=500)) {
        for(unsigned i=0;i<CDL_PORTS;++i)cdl_send(l,CDL_QUERY,cdl_real()?INADDR_BROADCAST:INADDR_LOOPBACK,CDL_FIRST_PORT+i);
        l->last_query=now;
    }
    if(l->state==CARBON_LAN_JOINING&&!l->hosting&&(!l->last_send||now-l->last_send>=250)) {
        cdl_peer_send(l,CDL_JOIN);l->last_send=now;
    }
    if(l->session) {
        int result=carbon_lan_session_tick(c,l->session);
        if(result<0){cdl_peer_send(l,CDL_CANCEL);cdl_reset(c,l,"The LAN session disconnected.");return;}
        if(result==1&&l->state==CARBON_LAN_JOINING) {
            l->state=CARBON_LAN_ROOM;l->last_peer=now;l->last_send=0;
            cdl_status(l,"LAN room - confirm to change Ready; Back to leave.");
        }
        unsigned char message[64];int reliable=0;
        unsigned n=carbon_lan_session_receive(l->session,message,sizeof message,&reliable);
        uint64_t nonce=l->hosting?l->nonce:l->peer.nonce;
        if(n==29&&reliable&&!memcmp(message,"C3LR",4)&&cdl_get(message+4,8)==l->peer.id&&
           cdl_get(message+12,8)==nonce&&cdl_get(message+20,8)==l->attempt&&message[28]<=1) {
            l->remote_ready=message[28];l->agreed=1;l->last_peer=now;
        }
        if(l->state==CARBON_LAN_ROOM&&(!l->last_send||now-l->last_send>=250)) {
            memcpy(message,"C3LR",4);cdl_put(message+4,l->id,8);cdl_put(message+12,nonce,8);
            cdl_put(message+20,l->attempt,8);message[28]=l->local_ready;
            if(carbon_lan_session_send(c,l->session,message,29,1))l->last_send=now;
        }
    }
    if((l->state==CARBON_LAN_JOINING&&now>=l->deadline)||
       (l->state==CARBON_LAN_ROOM&&now-l->last_peer>=5000)) {
        cdl_peer_send(l,CDL_CANCEL);cdl_reset(c,l,"LAN join timed out; choose a game again.");
    }
}
