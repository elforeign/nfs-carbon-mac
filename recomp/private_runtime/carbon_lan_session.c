/* Local peer bootstrap. The UI supplies both identities and the invitation
 * ticket explicitly; no connection, account or sign-in is created implicitly.
 * GameManager packets, player descriptors, CommUDP and NetGameLink stay guest
 * code. Only their local platform/services boundary is supplied here.
 *
 * Guest layouts: GM 0095CAB0 (lists +10C/+138, callbacks +1C4), player
 * 00983030 (persona +1C, roster id +18, address +28), channel 0095F720
 * (CommUDP +10/+14, NetGameLink +0C). All addresses bind to the feature image.
 */
#include "host.h"
#include "carbon_lan.h"
#include <stdlib.h>
#include <stdarg.h>

enum { LAN_PEERS = 2, LAN_ALLOCS = 256 };
typedef struct {
    int used, host, error, hello, roster, ack, connected;
    uint32_t gm, channel, memory, logger, clock, config, users, persona[2];
    uint32_t player[2], scratch, peer_ticket, allocations[LAN_ALLOCS];
    unsigned allocated, reliable, unreliable;
    CarbonLanIdentity identity[2];
    char names[2][32], invitation[64];
} CarbonLanSession;
static CarbonLanSession lan_sessions[LAN_PEERS];
static __thread CarbonLanSession *lan_active;
static int lan_real(void) {
    const char *value=getenv("NFS_LAN_REAL");
    return value&&!strcmp(value,"1");
}
static uint32_t lan_address(uint32_t address) {return address?address:0x7F000001;}
static int lan_allowed(uint32_t address) {
    return address&&address!=UINT32_MAX&&((address>>24)==127||lan_real());
}

static uint32_t lan_call(Cpu *c, uint32_t fn, uint32_t self, int n, ...) {
    Cpu saved = *c;
    uint32_t args[8];
    va_list ap; va_start(ap,n);
    for (int i=0;i<n;++i) args[i]=va_arg(ap,uint32_t);
    va_end(ap);
    c->ecx=self;
    uint32_t result=call_guest(c,fn,n,args);
    *c=saved;
    return result;
}
static uint32_t lan_alloc(CarbonLanSession *s, uint32_t size) {
    if (!size || size>1024*1024 || s->allocated==LAN_ALLOCS) {s->error=1;return 0;}
    uint32_t p=gmalloc_try(size);
    if (!p) {s->error=1;return 0;}
    s->allocations[s->allocated++]=p;
    return p;
}
static void lan_free(CarbonLanSession *s,uint32_t p) {
    if (!p) return;
    for(unsigned i=0;i<s->allocated;++i) if(s->allocations[i]==p) {
        gfree(p);s->allocations[i]=s->allocations[--s->allocated];return;
    }
    s->error=1;
}
static int lan_memory_alloc(Cpu *c) {RET(lan_alloc(lan_active,arg(c,0)),3);}
static int lan_memory_free(Cpu *c) {lan_free(lan_active,arg(c,0));RET(0,2);}
static int lan_zero(Cpu *c) {RET(0,0);}
static int lan_one(Cpu *c) {RET(1,0);}
static int lan_two(Cpu *c) {RET(2,0);}
static int lan_buffers(Cpu *c) {RET(32,0);}
static int lan_ticks(Cpu *c) {RET(host_ticks()/1000000,0);}
static int lan_log(Cpu *c) {
    if(diag_on) diag_event("CARBON LAN %s",gptr(arg(c,0)));
    RET(0,1);
}
static int lan_log_format(Cpu *c) {
    if(diag_on) diag_event("CARBON LAN %s",gptr(arg(c,2)));
    RET(0,0); /* cdecl, including the explicit logger argument */
}
static int lan_assert(Cpu *c) {lan_active->error=1;RET(0,3);}
static uint32_t lan_function(HostFn fn,const char *name) {
    static struct {HostFn fn;uint32_t token;} functions[32];
    static unsigned count;
    for(unsigned i=0;i<count;++i)if(functions[i].fn==fn)return functions[i].token;
    if(count==32){lan_active->error=1;return 0;}
    uint32_t token=host_fn(fn,name);functions[count].fn=fn;functions[count++].token=token;return token;
}
static uint32_t lan_object(CarbonLanSession *s,unsigned bytes,unsigned slots) {
    uint32_t p=lan_alloc(s,bytes),vt=lan_alloc(s,slots*4);
    if(!p||!vt)return 0;
    M32(p)=vt;
    for(unsigned i=0;i<slots;++i) M32(vt+4*i)=lan_function(lan_zero,"LAN unused service");
    return p;
}
static void lan_method(uint32_t p,unsigned offset,HostFn fn,const char *name) {
    M32(M32(p)+offset)=lan_function(fn,name);
}
static int lan_persona_name(Cpu *c) {RET(c->ecx+0x40,0);}
static int lan_persona_id(Cpu *c) {
    c->edx=M32(c->ecx+0x3C);RET(M32(c->ecx+0x38),0);
}
static int lan_persona_address(Cpu *c) {
    uint32_t p=arg(c,0);
    M32(p)=M32(c->ecx+0x30);M16(p+4)=M16(c->ecx+0x34);M16(p+6)=0;
    RET(p,1);
}
static int lan_no_console_address(Cpu *c) {RET(0,1);}
static int lan_find_persona(Cpu *c) {
    const char *name=gptr(arg(c,0));
    for(unsigned i=0;i<2;++i) if(name&&!strcmp(name,lan_active->names[i]))
        RET(lan_active->persona[i],1);
    RET(0,1);
}
static int lan_local_persona(Cpu *c) {RET(lan_active->persona[0],0);}
static int lan_user_id(Cpu *c) {
    c->edx=(uint32_t)(lan_active->identity[0].id>>32);
    RET(lan_active->identity[0].id,0);
}
void carbon_lan_persona(Cpu *c,void (*original)(Cpu *)) {
    if(!lan_active){original(c);return;}
    CarbonLanSession *s=lan_active;
    const char *name=gptr(arg(c,1));
    uint64_t id=(uint64_t)arg(c,2)|((uint64_t)arg(c,3)<<32);
    uint32_t p=s->persona[0];int found=0;
    for(unsigned i=0;i<2;++i)if(name&&!strcmp(name,s->names[i])&&id==s->identity[i].id){p=s->persona[i];found=1;break;}
    if(!found){s->error=4;if(diag_on)diag_event("CARBON LAN rejected persona name=%s id=%016llX",name?name:"",(unsigned long long)id);}
    c->eax=p;c->esp+=20;
}

/* Local roster service. Membership is supplied by the invitation, not by an
 * online activation result. Keep the native player reader at 00983250 and its
 * descriptor codec at 00983640; reject IDs outside the invited roster. */
void carbon_lan_roster_player(Cpu *c,void (*original)(Cpu *)) {
    if(!lan_active){original(c);return;}
    CarbonLanSession *s=lan_active;
    uint32_t reader=arg(c,0),id=s->scratch+0xA00;
    M32(id)=0x009F4DC0;M32(id+4)=0;
    lan_call(c,0x008E9170,reader,1,id);
    unsigned index=M32(id+4)==(uint32_t)s->identity[1].id?1:0;
    if(M32(id+4)!=(uint32_t)s->identity[index].id){s->error=4;if(diag_on)diag_event("CARBON LAN rejected roster id=%08X expected=%08X/%08X",M32(id+4),(uint32_t)s->identity[0].id,(uint32_t)s->identity[1].id);}
    uint32_t p=s->player[index];
    lan_call(c,0x00983250,p,4,s->gm,0x009F4DC0u,M32(id+4),reader);
    c->eax=p;c->esp+=8;
}

/* Hooks are inert outside an explicit bootstrap call. No startup/offline or
 * online service is replaced for the ordinary game. */
void carbon_lan_memory(Cpu *c,void (*original)(Cpu *)) {
    if(!lan_active){original(c);return;}c->eax=lan_active->memory;c->esp+=4;
}
void carbon_lan_users(Cpu *c,void (*original)(Cpu *)) {
    if(!lan_active){original(c);return;}c->eax=lan_active->users;c->esp+=4;
}
void carbon_lan_config(Cpu *c,void (*original)(Cpu *)) {
    if(!lan_active){original(c);return;}c->eax=lan_active->config;c->esp+=4;
}
void carbon_lan_logger(Cpu *c,void (*original)(Cpu *)) {
    if(!lan_active){original(c);return;}c->eax=lan_active->logger;c->esp+=4;
}
void carbon_lan_clock(Cpu *c,void (*original)(Cpu *)) {
    if(!lan_active){original(c);return;}c->eax=lan_active->clock;c->esp+=4;
}
void carbon_lan_tick_clock(Cpu *c,void (*original)(Cpu *)) {
    if(!lan_active){original(c);return;}c->eax=host_ticks()/1000000;c->esp+=4;
}
void carbon_lan_local_address(Cpu *c,void (*original)(Cpu *)) {
    if(!lan_active){original(c);return;}c->eax=lan_address(lan_active->identity[0].address);c->esp+=4;
}
void carbon_lan_allocator(Cpu *c,void (*original)(Cpu *)) {
    if(!lan_active){original(c);return;}c->eax=lan_active->memory;c->esp+=4;
}
void carbon_lan_dirty_alloc(Cpu *c,void (*original)(Cpu *)) {
    if(!lan_active){original(c);return;}c->eax=lan_alloc(lan_active,arg(c,0));c->esp+=4;
}
void carbon_lan_dirty_free(Cpu *c,void (*original)(Cpu *)) {
    if(!lan_active){original(c);return;}lan_free(lan_active,arg(c,0));c->esp+=4;
}

/* Poll-driven DirtySock platform adapter. It uses the same named Winsock shim
 * as guest imports; bind/send stay on loopback unless real LAN was explicitly
 * enabled. Native CommUDP retains connection, sequence, ACK and retry logic.
 * DirtySock handles are private to these calls, never normal online handles. */
typedef struct {uint32_t guest,socket;CarbonLanSession *owner;int reserved;} LanSocket;
static LanSocket lan_sockets[8];
static struct {uint32_t socket,address;uint16_t port;} lan_reserved[LAN_PEERS];
static LanSocket *lan_socket(uint32_t p) {
    for(unsigned i=0;i<8;++i)if(lan_sockets[i].guest==p&&p)return &lan_sockets[i];
    return NULL;
}
static uint32_t lan_ws(Cpu *c,const char *fn,int n,...) {
    Cpu saved=*c;va_list ap;va_start(ap,n);uint32_t a[6];
    for(int i=0;i<n;++i)a[i]=va_arg(ap,uint32_t);va_end(ap);
    for(int i=n-1;i>=0;--i){c->esp-=4;M32(c->esp)=a[i];}
    c->esp-=4;M32(c->esp)=0;
    extern int private_ws2(Cpu *,const char *);
    if(!private_ws2(c,fn)){if(lan_active)lan_active->error=1;c->eax=0xFFFFFFFF;}
    uint32_t r=c->eax;*c=saved;return r;
}

/* Keep an OS-bound game endpoint alive throughout discovery and the join
 * exchange. SocketOpen adopts it, so no close/rebind gap can advertise a
 * guessed or subsequently occupied port. */
uint16_t carbon_lan_session_reserve(Cpu *c,uint32_t address) {
    address=lan_address(address);
    if(!lan_allowed(address))return 0;
    unsigned i;for(i=0;i<LAN_PEERS;++i)if(!lan_reserved[i].port)break;
    if(i==LAN_PEERS)return 0;
    uint32_t tmp=gmalloc_try(32);if(!tmp)return 0;
    uint32_t fd=lan_ws(c,"socket",3,2u,2u,0u),port=0;
    if(fd!=UINT32_MAX) {
        memset(G+tmp,0,32);M16(tmp)=2;M32(tmp+4)=__builtin_bswap32(address);
        if(lan_ws(c,"bind",3,fd,tmp,16u)==0) {
            M32(tmp+16)=16;
            if(lan_ws(c,"getsockname",3,fd,tmp,tmp+16)==0&&
               M32(tmp+4)==__builtin_bswap32(address))port=__builtin_bswap16(M16(tmp+2));
        }
        if(port) {
            M32(tmp)=1;
            if(lan_ws(c,"ioctlsocket",3,fd,0x8004667Eu,tmp)!=0)port=0;
        }
        if(!port)lan_ws(c,"closesocket",1,fd);
    }
    gfree(tmp);
    if(port){lan_reserved[i].socket=fd;lan_reserved[i].address=address;lan_reserved[i].port=port;}
    return port;
}
void carbon_lan_session_unreserve(Cpu *c,uint16_t port) {
    for(unsigned i=0;i<LAN_PEERS;++i)if(port&&lan_reserved[i].port==port) {
        lan_ws(c,"closesocket",1,lan_reserved[i].socket);memset(&lan_reserved[i],0,sizeof lan_reserved[i]);
    }
}
void carbon_lan_socket_open(Cpu *c,void (*original)(Cpu *)) {
    if(!lan_active){original(c);return;}
    uint32_t r=0;
    if(arg(c,0)==2&&arg(c,1)==2&&arg(c,2)==0)for(unsigned i=0;i<8;++i) {
        if(lan_sockets[i].guest)continue;
        unsigned held=LAN_PEERS;
        for(unsigned j=0;j<LAN_PEERS;++j)if(lan_reserved[j].port==lan_active->identity[0].port&&
            lan_reserved[j].address==lan_address(lan_active->identity[0].address)){held=j;break;}
        uint32_t fd=held<LAN_PEERS?lan_reserved[held].socket:lan_ws(c,"socket",3,2u,2u,0u);
        if(fd==0xFFFFFFFF)break;
        r=lan_alloc(lan_active,0x60);if(!r){lan_ws(c,"closesocket",1,fd);
            if(held<LAN_PEERS)memset(&lan_reserved[held],0,sizeof lan_reserved[held]);break;}
        lan_sockets[i]=(LanSocket){r,fd,lan_active,held<LAN_PEERS};
        if(held<LAN_PEERS)memset(&lan_reserved[held],0,sizeof lan_reserved[held]);
        M32(lan_active->scratch)=1;
        lan_ws(c,"ioctlsocket",3,fd,0x8004667Eu,lan_active->scratch);
        break;
    }
    c->eax=r;c->esp+=4;
}
void carbon_lan_socket_close(Cpu *c,void (*original)(Cpu *)) {
    LanSocket *p=lan_socket(arg(c,0));if(!p){original(c);return;}
    lan_ws(c,"closesocket",1,p->socket);lan_free(p->owner,p->guest);memset(p,0,sizeof *p);
    c->eax=0;c->esp+=4;
}
void carbon_lan_socket_bind(Cpu *c,void (*original)(Cpu *)) {
    LanSocket *p=lan_socket(arg(c,0));if(!p){original(c);return;}
    uint32_t addr=arg(c,1),tmp=p->owner->scratch;
    memcpy(G+tmp,G+addr,16);M32(tmp+4)=__builtin_bswap32(lan_address(p->owner->identity[0].address));
    c->eax=p->reserved?(__builtin_bswap16(M16(tmp+2))==p->owner->identity[0].port?0:UINT32_MAX):
        lan_ws(c,"bind",3,p->socket,tmp,16u);c->esp+=4;
}
void carbon_lan_socket_info(Cpu *c,void (*original)(Cpu *)) {
    LanSocket *p=lan_socket(arg(c,0));if(!p){original(c);return;}
    uint32_t out=arg(c,3),size=arg(c,4),tmp=p->owner->scratch;
    if(arg(c,1)==0x62696E64&&out&&size>=16) {
        M32(tmp)=16;c->eax=lan_ws(c,"getsockname",3,p->socket,out,tmp);
        /* CommUDP matches the requested wildcard bind to share its listener
         * with its connector. The host socket remains bound to loopback. */
        if(c->eax==0)M32(out+4)=0;
    }else c->eax=0xFFFFFFFF;
    c->esp+=4;
}
void carbon_lan_socket_callback(Cpu *c,void (*original)(Cpu *)) {
    if(!lan_socket(arg(c,0))){original(c);return;}c->eax=0;c->esp+=4;
}
void carbon_lan_socket_recv(Cpu *c,void (*original)(Cpu *)) {
    LanSocket *p=lan_socket(arg(c,0));if(!p){original(c);return;}
    uint32_t r=lan_ws(c,"recvfrom",6,p->socket,arg(c,1),arg(c,2),0u,arg(c,4),arg(c,5));
    /* SocketRecvfrom stamps the spare sockaddr bytes in network order;
     * CommUDP uses that arrival time for its native liveness/retry checks. */
    if(r!=0xFFFFFFFF&&r&&arg(c,4))M32(arg(c,4)+8)=__builtin_bswap32((uint32_t)(host_ticks()/1000000));
    c->eax=r==0xFFFFFFFF?0:r;c->esp+=4;
}
void carbon_lan_socket_send(Cpu *c,void (*original)(Cpu *)) {
    LanSocket *p=lan_socket(arg(c,0));if(!p){original(c);return;}
    uint32_t addr=arg(c,4);
    if(!addr||M16(addr)!=2||!lan_allowed(__builtin_bswap32(M32(addr+4))))c->eax=0xFFFFFFFB;
    else c->eax=lan_ws(c,"sendto",6,p->socket,arg(c,1),arg(c,2),0u,addr,arg(c,5));
    c->esp+=4;
}

void carbon_lan_connect_address(Cpu *c,void (*original)(Cpu *)) {
    if(!lan_active){original(c);return;}
    /* 0095F720 assumes equal ports on separate machines. An explicit local
     * pair needs the advertised remote port instead of that assumption. */
    uint32_t text=lan_active->scratch+0x100,slot=c->esp+8,old=arg(c,1);
    uint32_t address=lan_address(lan_active->identity[1].address);
    snprintf((char *)G+text,256,"%u.%u.%u.%u:%u:%u#local",
             address>>24,(address>>16)&255,(address>>8)&255,address&255,
             lan_active->identity[0].port,lan_active->identity[1].port);
    M32(slot)=text;original(c);M32(slot)=old;
}

static int lan_packet_send(Cpu *c) {
    CarbonLanSession *s=lan_active;
    if(s->error)RET(0xFFFFFFFF,3);
    uint32_t writer=arg(c,0),stream=M32(writer+4);
    uint32_t data=M32(stream+4),len=M32(stream+0x408);
    if(diag_on)diag_event("CARBON LAN native send bytes=%u type=%u",len,M8(data));
    uint32_t r=lan_call(c,0x0095F520,s->channel,5,data,len,1u,1u,0u);
    RET(r,3);
}
static int lan_gm_send(Cpu *c) {return lan_packet_send(c);}
static int lan_peer_address(Cpu *c) {RET(lan_active->peer_ticket,0);}
static int lan_link_ready(Cpu *c) {
    M8(lan_active->channel+0xED)=arg(c,0)!=0;RET(0,1);
}

static int lan_activate(Cpu *c,CarbonLanSession *s) {
    /* Local activation completes the service callback after roster agreement.
     * Use the native transition and activated-member list, not just a host
     * boolean. No account activation request or response is fabricated. */
    for(unsigned i=0;i<2;++i)if(M32(s->player[i]+0x24)!=6)
        lan_call(c,0x0095A520,s->gm,1,s->player[i]);
    M8(s->channel+0xED)=1;
    return !s->error&&M32(s->player[0]+0x24)==6&&M32(s->player[1]+0x24)==6;
}

static void lan_manager(Cpu *c,CarbonLanSession *s) {
    uint32_t gm=s->gm,vt=lan_alloc(s,0xA0);
    memcpy(G+vt,G+0x00A23358,0xA0);M32(gm)=vt;
    lan_method(gm,0xC,lan_zero,"LAN peer topology");
    lan_method(gm,0x10,lan_zero,"LAN game state");
    lan_method(gm,0x18,lan_zero,"LAN private session");
    lan_method(gm,0x28,lan_zero,"LAN mesh mode");
    lan_method(gm,0x6C,lan_zero,"LAN service mode");
    lan_method(gm,0x78,lan_zero,"LAN game type");
    lan_method(gm,0x80,lan_two,"LAN roster capacity");
    lan_method(gm,0x94,lan_gm_send,"LAN native packet");
    uint32_t service=lan_object(s,4,24);M32(gm+8)=M32(service);
    lan_method(gm+8,0x14,lan_one,"LAN join allowed");
    lan_method(gm+8,0x4C,lan_two,"LAN peer count");
    /* Native list policies and growth, as initialized by 0095CAB0. */
    M32(gm+0x10C)=0x00A232C0;M32(gm+0x11C)=2;
    M32(gm+0x138)=0x00A232C0;M32(gm+0x148)=2;M8(gm+0x13C)=1;
    strcpy((char *)G+gm+0x60,s->invitation);
    uint32_t address=s->scratch+0x80;
    M32(address)=0x00A16888;M32(address+4)=lan_address(s->identity[1].address);M16(address+8)=s->identity[1].port;
    s->peer_ticket=lan_call(c,0x008E2140,0,3,address,address,0u);
    M32(gm+0xF4)=lan_object(s,4,12);
    lan_method(M32(gm+0xF4),0x1C,lan_peer_address,"LAN peer address");
    lan_method(M32(gm+0xF4),0x28,lan_link_ready,"LAN activate channel");
    for(unsigned i=0;i<2;++i) {
        uint32_t node=lan_alloc(s,0x40),p=node+8;
        if(!node){s->error=1;return;}
        M32(node)=0x00A23270;
        lan_call(c,0x00983030,p,0);
        s->player[i]=p;M32(p+0xC)=gm;M32(p+0x18)=(uint32_t)s->identity[i].id;
        M32(p+0x1C)=s->persona[i];M32(p+0x24)=5;
        uint32_t a=s->scratch+0xA0;
        M32(a)=0x00A16888;M32(a+4)=lan_address(s->identity[i].address);M16(a+8)=s->identity[i].port;
        M32(p+0x28)=lan_call(c,0x008E2140,0,3,a,a,0u);
        uint32_t pvt=lan_alloc(s,0x50);memcpy(G+pvt,G+M32(p),0x50);M32(p)=pvt;
        lan_method(p,0x48,lan_packet_send,"LAN native roster packet");
    }
    M32(s->player[0]-4)=s->player[1]-8;
    M32(gm+0x128)=s->player[0]-8;
    if(s->host){M32(gm+0x104)=s->player[0];M32(gm+0xFC)=s->player[0];M32(gm+0x108)=s->player[0];}
}

static int lan_services(CarbonLanSession *s) {
    s->memory=lan_object(s,4,24);s->logger=lan_object(s,4,5);
    s->clock=lan_object(s,4,6);s->config=lan_alloc(s,0x20);s->users=lan_object(s,4,24);
    if(s->error)return 0;
    lan_method(s->memory,0xC,lan_memory_alloc,"LAN allocate");
    lan_method(s->memory,0x10,lan_memory_free,"LAN free");
    lan_method(s->memory,0x48,lan_buffers,"LAN input buffers");
    lan_method(s->memory,0x4C,lan_buffers,"LAN output buffers");
    lan_method(s->logger,8,lan_log,"LAN log");
    lan_method(s->logger,12,lan_log_format,"LAN formatted log");
    lan_method(s->logger,16,lan_assert,"LAN assertion");
    lan_method(s->clock,8,lan_ticks,"LAN clock");
    lan_method(s->clock,16,lan_one,"LAN receive lock");
    lan_method(s->users,0x18,lan_find_persona,"LAN find persona");
    lan_method(s->users,0x24,lan_local_persona,"LAN local persona");
    lan_method(s->users,0x38,lan_user_id,"LAN local id");
    for(unsigned i=0;i<2;++i) {
        uint32_t p=s->persona[i]=lan_object(s,0x100,24);
        if(s->error)return 0;
        M64(p+0x38)=s->identity[i].id;M16(p+0x34)=s->identity[i].port;M32(p+0x30)=lan_address(s->identity[i].address);
        strcpy((char *)G+p+0x40,s->names[i]);
        lan_method(p,0x34,lan_persona_name,"LAN persona name");
        lan_method(p,0x38,lan_persona_id,"LAN persona id");
        lan_method(p,0x44,lan_persona_address,"LAN persona address");
        lan_method(p,0x48,lan_no_console_address,"LAN internet address");
    }
    return !s->error;
}

void carbon_lan_session_close(Cpu *,unsigned);

/* API for a future lobby: return 1..2, or zero for invalid/missing invitation.
 * Identities must be distinct and stable for the session; their low 32 bits
 * are the native 16-bit roster IDs (00818050/70; zero and 65535 are reserved). Ports are explicit;
 * discovery is responsible for reserving/advertising them, never inferred.
 * Non-loopback endpoints require explicit real-LAN authorization. */
unsigned carbon_lan_session_open(Cpu *c,const CarbonLanIdentity *local,
        const CarbonLanIdentity *remote,const char *ticket,int host) {
    if(!local||!remote||!(uint32_t)local->id||!(uint32_t)remote->id||
       (uint32_t)local->id>=65535||(uint32_t)remote->id>=65535||
       (uint32_t)local->id==(uint32_t)remote->id||
       !local->name||!remote->name||!local->name[0]||!remote->name[0]||
       strlen(local->name)>=32||strlen(remote->name)>=32||
       !strcmp(local->name,remote->name)||!ticket||!ticket[0]||strlen(ticket)>=64||
       !local->port||!remote->port||!lan_allowed(lan_address(local->address))||
       !lan_allowed(lan_address(remote->address))||
       (local->port==remote->port&&lan_address(local->address)==lan_address(remote->address)))return 0;
    unsigned index;for(index=0;index<LAN_PEERS;++index)if(!lan_sessions[index].used)break;
    if(index==LAN_PEERS)return 0;
    CarbonLanSession *s=&lan_sessions[index];memset(s,0,sizeof *s);s->used=1;s->host=!!host;
    s->identity[0]=*local;s->identity[1]=*remote;
    strcpy(s->names[0],local->name);strcpy(s->names[1],remote->name);strcpy(s->invitation,ticket);
    s->identity[0].name=s->names[0];s->identity[1].name=s->names[1];
    lan_active=s;
    s->scratch=lan_alloc(s,0x1400);s->gm=lan_alloc(s,0x900);s->channel=lan_alloc(s,0xF0);
    if(!s->error)lan_services(s);
    if(!s->error)lan_manager(c,s);
    /* Channel constructor + scalar setup (0095F430/0095FA90). */
    if(!s->error) {
        M32(s->channel+8)=lan_alloc(s,0x40);
        M16(s->channel+0xB0)=local->port;M8(s->channel+0xB8)=host!=0;
        strcpy((char *)G+s->channel+0x88,"local");
        uint32_t addr=s->scratch+0x40;
        M32(addr+0xC)=lan_address(remote->address);M16(addr+0x10)=remote->port;
        lan_call(c,0x0095F720,s->channel,1,host?0u:addr);
        uint32_t listener=M32(s->channel+(host?0x10:0x14));
        if(!listener||M32(listener+0x98)!=3)s->error=1;
    }
    lan_active=NULL;
    if(s->error){carbon_lan_session_close(c,index+1);return 0;}
    return index+1;
}

static int lan_decode(Cpu *c,CarbonLanSession *s,uint32_t data,unsigned length) {
    uint32_t reader=s->scratch+0x400,out=s->scratch+0x900;
    lan_call(c,0x008E8F00,reader,2,data,(uint32_t)length);
    lan_call(c,0x008E9030,reader,1,out);
    unsigned type=M8(out);
    if(type==0&&s->host&&!s->hello) {
        /* Use the native reader for the version and invitation. There is no
         * remote account activation: the invitation already supplies the peer
         * identity that FESL activation would otherwise have looked up. */
        lan_call(c,0x008E8440,reader,1,out);
        if(M32(M32(reader+4)+0x414)||M16(out)!=4){s->error=2;return 0;}
        lan_call(c,0x008E9040,reader,2,out,128u);
        if(M32(M32(reader+4)+0x414)||strcmp(gptr(out),s->invitation)){s->error=3;return 0;}
        s->hello=1;
        lan_call(c,0x00956B40,s->gm,1,s->player[1]);
    }else if(type==2&&!s->host&&!s->hello) {
        /* Preflight before the native decoder: its version assertion alone
         * logs a mismatch and continues, which is insufficient for joining. */
        uint32_t pos=M32(M32(reader+4)+0x410);
        lan_call(c,0x008E8440,reader,1,out);
        if(M32(M32(reader+4)+0x414)||M16(out)!=4){s->error=2;return 0;}
        M32(M32(reader+4)+0x410)=pos;
        lan_call(c,0x0095C300,s->gm,3,2u,0u,reader);
        if(s->error||M32(M32(reader+4)+0x414)){if(diag_on)diag_event("CARBON LAN host hello rejected error=%d reader=%u",s->error,M32(M32(reader+4)+0x414));if(!s->error)s->error=1;return 0;}
        /* Keep the invited roster visible to native roster iterators. The
         * decoder's temporary generic node pool is not online membership. */
        M32(s->gm+0x128)=s->player[0]-8;
        s->hello=1;
    }else if(type==3&&!s->host&&s->hello&&!s->roster) {
        lan_call(c,0x0095C520,s->gm,3,3u,0u,reader);
        if(s->error||M32(M32(reader+4)+0x414)){if(!s->error)s->error=1;return 0;}
        s->roster=M32(s->gm+0x174)==2&&M32(s->gm+0x108)!=0&&lan_activate(c,s);
    }else if(type==4&&s->host&&s->hello&&!s->roster) {
        s->ack=1;s->roster=lan_activate(c,s);
    }else {s->error=1;return 0;}
    return !s->error;
}

static void lan_packets(Cpu *c,CarbonLanSession *s) {
    if(M32(s->scratch+0xF00))return;
    uint32_t packet=s->scratch+0xC00;
    for(unsigned i=0;i<32;++i) {
        uint32_t got=lan_call(c,0x0098B900,0,3,M32(s->channel+0xC),packet,1u);
        if(!got)break;
        unsigned size=M16(packet+4),kind=M8(packet+6);
        if(diag_on)diag_event("CARBON LAN native receive bytes=%u kind=%u control=%u",size,kind,M8(packet+8));
        if(size<1||size>512||(kind!=4&&kind!=5)){s->error=1;break;}
        if(M8(packet+8))lan_decode(c,s,packet+9,size-1);
        else {
            if(!s->roster){s->error=1;break;}
            /* A lobby caller retrieves the last game payload with receive(). */
            memcpy(G+s->scratch+0x1200,G+packet+9,size-1);
            M32(s->scratch+0xF00)=size-1;M32(s->scratch+0xF04)=kind==4;
            if(kind==4)++s->reliable;else ++s->unreliable;
            break;
        }
        if(s->error)break;
    }
}

/* Pump both native CommUDP endpoints. No worker thread or alternate wire
 * format is needed: 0098A000 is the SDK's own poll callback. */
int carbon_lan_session_tick(Cpu *c,unsigned handle) {
    if(!handle||handle>LAN_PEERS||!lan_sessions[handle-1].used)return -1;
    CarbonLanSession *s=&lan_sessions[handle-1];lan_active=s;
    if(s->error){lan_active=NULL;return -1;}
    lan_call(c,0x0098A000,0,0);
    if(!s->connected) {
        uint32_t a=M32(s->channel+0x10),b=M32(s->channel+0x14);
        if(a&&b) {
            int sa=lan_call(c,0x0098A4A0,0,1,a),sb=lan_call(c,0x0098A4A0,0,1,b);
            if(sa==3||sb==3) {
                uint32_t good=sa==3?a:b,bad=sa==3?b:a;
                lan_call(c,0x0098A0F0,0,1,bad);M32(s->channel+0x10)=M32(s->channel+0x14)=0;
                M32(s->channel+0xC)=lan_call(c,0x0098B640,0,3,good,1u,0u);
                s->connected=M32(s->channel+0xC)!=0;
            }
        }
    }
    if(s->connected&&!s->host&&!s->hello&&!s->ack) {
        lan_call(c,0x00955FD0,s->gm,1,0u);s->ack=1;
    }
    if(s->connected)lan_packets(c,s);
    int result=s->error?-1:s->roster;lan_active=NULL;return result;
}

int carbon_lan_session_send(Cpu *c,unsigned handle,const void *bytes,unsigned size,int reliable) {
    if(!handle||handle>LAN_PEERS||!bytes||!size||size>511)return 0;
    CarbonLanSession *s=&lan_sessions[handle-1];if(!s->used||s->error||!s->roster)return 0;
    lan_active=s;memcpy(G+s->scratch+0x1000,bytes,size);
    uint32_t r=lan_call(c,0x0095F520,s->channel,5,s->scratch+0x1000,(uint32_t)size,0u,(uint32_t)!!reliable,0u);
    lan_active=NULL;return r==0;
}

unsigned carbon_lan_session_receive(unsigned handle,void *bytes,unsigned capacity,int *reliable) {
    if(!handle||handle>LAN_PEERS||!bytes)return 0;
    CarbonLanSession *s=&lan_sessions[handle-1];if(!s->used)return 0;
    unsigned n=M32(s->scratch+0xF00);if(n>capacity)return 0;
    memcpy(bytes,G+s->scratch+0x1200,n);M32(s->scratch+0xF00)=0;
    if(reliable)*reliable=M32(s->scratch+0xF04)!=0;return n;
}

void carbon_lan_session_close(Cpu *c,unsigned handle) {
    if(!handle||handle>LAN_PEERS)return;
    CarbonLanSession *s=&lan_sessions[handle-1];if(!s->used)return;lan_active=s;
    uint32_t link=s->channel?M32(s->channel+0xC):0;
    if(link)lan_call(c,0x0098B740,0,1,link);
    for(unsigned off=0x10;s->channel&&off<=0x14;off+=4) {
        uint32_t comm=M32(s->channel+off);if(comm)lan_call(c,0x0098A0F0,0,1,comm);
    }
    for(unsigned i=0;i<8;++i)if(lan_sockets[i].owner==s) {
        lan_ws(c,"closesocket",1,lan_sockets[i].socket);memset(&lan_sockets[i],0,sizeof lan_sockets[i]);
    }
    while(s->allocated)gfree(s->allocations[--s->allocated]);
    memset(s,0,sizeof *s);lan_active=NULL;
}
