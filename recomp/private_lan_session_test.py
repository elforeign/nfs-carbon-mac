"""Account-free local sessions through pinned translated Carbon networking.

Red bootstrap removed: transport=2, hello=0, roster=0 (exit 1).
Green: two session cycles, hello=2 and roster=2 each, reliable=8 and unreliable=2
per cycle, callbacks=21 after each close/reopen, native player state=6.
Independent processes exchange eight reliable and eight unreliable messages.
Forcing unreliable packets to reliable gives 10/0 deliveries and eight failures.
Missing identity/name/ticket are rejected before sockets; wrong ticket and both
version-3 hello controls reject joining. Native personas and two roster IDs
must agree, and queued packets must preserve both payload and delivery class.
The fixture supplies only the host CPU/import boundary; packets and SDK state
machines execute translated bodies. Real sockets bind exclusively to loopback.
Exit 3 without the private image/translation. Run via the offline test runner.
"""
from pathlib import Path
import hashlib
import json
import re
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import build_all
import private_hooks
from recomp import PE

HOOKS = {
    0x008DEE70: 'memory', 0x008DEFF0: 'users', 0x008DF480: 'config',
    0x008F3B90: 'logger', 0x00936A20: 'clock', 0x008F3F90: 'allocator',
    0x008F3FD0: 'dirty_alloc', 0x008F4000: 'dirty_free',
    0x009766C0: 'socket_open', 0x009767B0: 'socket_close',
    0x00976820: 'socket_bind', 0x00976CE0: 'socket_info',
    0x00976EF0: 'socket_callback', 0x00976B50: 'socket_recv', 0x00976A80: 'socket_send',
    0x0098A8C0: 'connect_address',
    0x0094C790: 'tick_clock',
    0x00977750: 'local_address',
    0x0095B790: 'roster_player',0x0092EF10: 'persona',
}
PINS = {
    0x00955FD0: '03f754e7aa7a10539c5ce59673322dc3ac3b34c49ae656e88487b5b8ce7856e2',
    0x00956B40: '8aa9e919105359685f92ce64cbb21a77a81370687832a376f6b3facfed46c3db',
    0x0095C300: 'a1874f0e7bc6ecc1c00fb60da3df3da5f57e7f8081582d6d2c0b26f61a487690',
    0x0095C520: '6af389227c6f45113858d98a0727a6cbd2104281e3e552eff11e857efb2215e1',
    0x0095F720: '2c065e0e94e35ac0e79e46e394ba2f3a34ee01531bd629e8ea24ae89c9eb98ce',
    0x0098B640: '3d182c698524b01dabdad619df8d55591f3307b491a38468e67cc928d149a8e9',
    0x0095A520: 'dd46e2bacaeafc665a65a403db6ee69a274eaa507a2643f189b56e68ddd10cd0',
    0x0095F520: '7889fbb7e95b1e7c9e8fcbd4a55c8f2e5e56be866899020ef361a95879141c07',
    0x0098B900: 'b7f7fd44224899eb65a44023856fed33b60c13f4c85ed2a816859a1339b7365f',
    0x009828C0: '7287fe6fd786c7bc988756ec9c4b7154ec71ede15de9c151d338ba853dd6e6e4',
    0x00983640: '1d628716f5edb71bee1e04d891153ac73328187c1c0cb03110e3ea87713002d2',
}

HARNESS = r'''
#include "funcs.h"
#include "host.h"
#include <stdarg.h>
#include <stdlib.h>
#include <time.h>
#include <unistd.h>
#include <sys/wait.h>
#include "game_ws2.h"
#include "carbon_lan_session.c"
uint8_t *G;
int diag_on=0,boot_trace=0;
__thread uint32_t last_error;
static unsigned checks,failures,imports,allocations_live;
static uint32_t heap=0x1000000;
static HostFn callbacks[1024];
static unsigned callback_count;
static int fail_allocation;
#define CHECK(x) do {++checks;if(!(x)){++failures;fprintf(stderr,"LAN check %d: %s\n",__LINE__,#x);}}while(0)
uint32_t gmalloc_try(uint32_t n){if(fail_allocation){fail_allocation=0;return 0;}uint32_t p=heap;heap+=(n+63)&~63u; if(heap>=0x3F00000)abort();memset(G+p,0,n);++allocations_live;return p;}
uint32_t gmalloc(uint32_t n){return gmalloc_try(n);}
uint32_t gmalloc_size(uint32_t p){(void)p;return 0;}
uint32_t galloc(uint32_t n){return gmalloc(n);}
void gfree(uint32_t p){if(p)--allocations_live;}
uint32_t gstr(const char *s){uint32_t p=galloc(strlen(s)+1);strcpy((char *)G+p,s);return p;}
uint64_t host_ticks(void){struct timespec ts;clock_gettime(CLOCK_MONOTONIC,&ts);return (uint64_t)ts.tv_sec*1000000000+ts.tv_nsec;}
void diag_event(const char *fmt,...){va_list ap;va_start(ap,fmt);vfprintf(stderr,fmt,ap);fputc('\n',stderr);va_end(ap);}
void gil_yield(Cpu *c){(void)c;}
void gil_release(void){}
void gil_acquire(void){}
int threads_close(uint32_t h){(void)h;abort();}
uint32_t threads_event_new(int a,int b){(void)a;(void)b;abort();}
int threads_event_set(uint32_t h,int b){(void)h;(void)b;abort();}
uint64_t threads_event_generation(uint32_t h){(void)h;abort();}
void threads_set_event_generation_async(uint32_t h,uint64_t g){(void)h;(void)g;abort();}
uint32_t threads_wait(Cpu *c,uint32_t n,const uint32_t *h,int all,uint32_t ms){(void)c;(void)n;(void)h;(void)all;(void)ms;abort();}
void diag_begin_exit(void){abort();}
void app_restart_game_exited(int ok){(void)ok;abort();}
int private_resolve(const char *s,char *out,size_t n){(void)s;(void)out;(void)n;abort();}
int private_win32(Cpu *c,const char *n){(void)c;(void)n;abort();}
int win32_threads(Cpu *c,const char *n){(void)c;(void)n;abort();}
int win32_heap(Cpu *c,const char *n){(void)c;(void)n;abort();}
uint32_t private_thread_create(uint32_t a,uint32_t b,uint32_t d,uint32_t e,uint32_t *f){(void)a;(void)b;(void)d;(void)e;(void)f;abort();}
uint32_t host_fn(HostFn fn,const char *name){
    (void)name;for(unsigned i=0;i<callback_count;++i)if(callbacks[i]==fn)return HOSTFN_BASE+4*i;
    if(callback_count==1024)abort();callbacks[callback_count]=fn;return HOSTFN_BASE+4*callback_count++;
}
void untranslated(Cpu *c,uint32_t a){(void)c;fprintf(stderr,"untranslated %08X\n",a);exit(2);}
void guest_breakpoint(Cpu *c,uint32_t a){untranslated(c,a);}
void guest_divide_error(Cpu *c,uint32_t a){untranslated(c,a);}
void bad_jump(Cpu *c,uint32_t a){(void)c;fprintf(stderr,"bad jump %08X\n",a);exit(2);}
void abi_violation(Cpu *c,uint32_t f,uint32_t a,uint32_t b,uint32_t d,uint32_t e,uint32_t sp){
    (void)c;(void)a;(void)b;(void)d;(void)e;(void)sp;fprintf(stderr,"ABI %08X\n",f);exit(2);
}
static void unexpected(Cpu *c,uint32_t a){fprintf(stderr,"unexpected %08X ra=%08X ecx=%08X\n",a,M32(c->esp),c->ecx);exit(2);}
static const char *import_name(uint32_t slot){switch(slot){ /* IMPORT_NAMES */ default:return "unknown";}}
void host_import(Cpu *c,uint32_t slot){
    const char *name=import_name(slot);++imports;
    extern int private_crt(Cpu *,const char *);
    if(private_crt(c,name))return;
    if(!strcmp(name,"GetTickCount")){c->eax=host_ticks()/1000000;c->esp+=4;return;}
    if(!strcmp(name,"GetCurrentThreadId")){c->eax=1;c->esp+=4;return;}
    if(!strcmp(name,"InterlockedExchange")){uint32_t p=arg(c,0);c->eax=M32(p);M32(p)=arg(c,1);c->esp+=12;return;}
    if(!strcmp(name,"InitializeCriticalSection")||!strcmp(name,"DeleteCriticalSection")||
       !strcmp(name,"EnterCriticalSection")||!strcmp(name,"LeaveCriticalSection")||
       !strcmp(name,"TryEnterCriticalSection")){c->eax=1;c->esp+=8;return;}
    if(private_ws2(c,name))return;
    fprintf(stderr,"unexpected import %s slot=%08X\n",name,slot);exit(2);
}
void dispatch(Cpu *c,uint32_t target){
    if(target>=THUNK_BASE&&target<HOSTFN_BASE){host_import(c,target-THUNK_BASE);return;}
    if(target>=HOSTFN_BASE&&target<HOSTFN_BASE+4*callback_count){callbacks[(target-HOSTFN_BASE)/4](c);return;}
    switch(target){ /* DISPATCH */ default:unexpected(c,target);}
}
uint32_t call_guest(Cpu *c,uint32_t fn,int n,const uint32_t *args){
    uint32_t sp=c->esp;for(int i=n-1;i>=0;--i){c->esp-=4;M32(c->esp)=args[i];}
    c->esp-=4;M32(c->esp)=0xFEEDF00D;dispatch(c,fn);c->esp=sp;return c->eax;
}
/* Native security-cookie checker has no networking effect. */
void f_009914B0(Cpu *c){c->esp+=4;}
static void pump(Cpu *c,unsigned a,unsigned b){carbon_lan_session_tick(c,a);carbon_lan_session_tick(c,b);}
static int message(Cpu *c,unsigned a,unsigned b,const unsigned char *expected,unsigned n,int reliable){
    unsigned char received[512];int kind=-1;unsigned size=0;
    uint64_t deadline=host_ticks()+500000000ull;
    do{pump(c,a,b);size=carbon_lan_session_receive(b,received,sizeof received,&kind);if(size)break;usleep(1000);}while(host_ticks()<deadline);
    return size==n&&kind==reliable&&!memcmp(received,expected,n);
}
static void payload(unsigned char *out,unsigned seq){for(unsigned i=0;i<24;++i)out[i]=(unsigned char)(i*11+seq);out[0]=0;}
static void released(void){
    CHECK(allocations_live==0);
    CHECK(!lan_active&&M32(0x00BCC5C4)==0);
    for(unsigned i=0;i<8;++i)CHECK(!lan_sockets[i].guest);
    for(unsigned i=0;i<LAN_PEERS;++i)CHECK(!lan_sessions[i].used&&!lan_sessions[i].allocated);
}
static void passthrough(Cpu *c){++c->eax;c->esp+=4;}
static void socket_boundary(Cpu *c,unsigned handle){
    CarbonLanSession *s=&lan_sessions[handle-1];lan_active=s;
    for(unsigned i=0;i<8;++i)if(lan_sockets[i].owner==s){
        uint32_t addr=s->scratch+0xF10,len=s->scratch+0xF20;M32(len)=16;
        CHECK(lan_ws(c,"getsockname",3,lan_sockets[i].socket,addr,len)==0);
        CHECK(M32(addr+4)==0x0100007F&&__builtin_bswap16(M16(addr+2))==s->identity[0].port);
        M32(addr+4)=0x010200C0; /* TEST-NET, deliberately rejected before the socket shim. */
        Cpu probe=*c;uint32_t args[6]={lan_sockets[i].guest,s->scratch+0x1000,1,0,addr,16};
        for(unsigned j=0;j<6;++j)M32(probe.esp+4+4*j)=args[j];
        carbon_lan_socket_send(&probe,passthrough);CHECK(probe.eax==0xFFFFFFFB&&probe.esp==c->esp+4);
    }
    lan_active=NULL;
}
typedef struct {int pid;unsigned failed,hello,roster,reliable,unreliable,callbacks;} PeerReport;
static int process_pair(Cpu *c,CarbonLanIdentity a,CarbonLanIdentity b){
    int ready[2],report[2];if(pipe(ready)||pipe(report))return 2;
    pid_t child=fork();if(child<0)return 2;
    int host=child!=0;
    if(host){close(ready[0]);close(report[1]);}
    else{close(ready[1]);close(report[0]);char byte;if(read(ready[0],&byte,1)!=1)_exit(2);close(ready[0]);}
    unsigned handle=carbon_lan_session_open(c,host?&a:&b,host?&b:&a,"process-invitation",host);
    if(host){char byte=1;write(ready[1],&byte,1);close(ready[1]);}
    CHECK(handle!=0);if(!handle)return 2;
    uint64_t deadline=host_ticks()+2000000000ull;int joined=0;
    do{joined=carbon_lan_session_tick(c,handle);if(joined)break;usleep(1000);}while(host_ticks()<deadline);
    CHECK(joined==1);
    if(joined==1)socket_boundary(c,handle);
    if(joined==1)for(unsigned i=0;i<8;++i){
        unsigned char data[24];payload(data,i+100);int reliable=i%2;
        if(host)CHECK(carbon_lan_session_send(c,handle,data,sizeof data,reliable));
        CHECK(message(c,handle,handle,data,sizeof data,reliable));
        if(!host)CHECK(carbon_lan_session_send(c,handle,data,sizeof data,reliable));
    }
    CarbonLanSession *s=&lan_sessions[handle-1];
    CHECK(s->reliable==4&&s->unreliable==4);
    PeerReport me={(int)getpid(),failures,(unsigned)s->hello,(unsigned)s->roster,s->reliable,s->unreliable,callback_count};
    carbon_lan_session_close(c,handle);released();me.failed=failures;
    if(!host){write(report[1],&me,sizeof me);close(report[1]);_exit(failures?1:0);}
    PeerReport peer={0};CHECK(read(report[0],&peer,sizeof peer)==sizeof peer);close(report[0]);
    int status=0;CHECK(waitpid(child,&status,0)==child&&WIFEXITED(status)&&WEXITSTATUS(status)==0);
    CHECK(peer.pid==child&&peer.pid!=me.pid&&!peer.failed);
    CHECK(peer.hello==1&&peer.roster==1&&peer.reliable==4&&peer.unreliable==4);
    printf("LAN processes=%d/%d hello=%u roster=%u reliable=%u unreliable=%u callbacks=%u/%u failures=%u\n",
        me.pid,peer.pid,me.hello+peer.hello,me.roster+peer.roster,me.reliable+peer.reliable,
        me.unreliable+peer.unreliable,me.callbacks,peer.callbacks,failures);
    return failures?1:0;
}
int main(int argc,char **argv){
    if(argc<2)return 2;G=calloc(1,0x4000000);FILE *f=fopen(argv[1],"rb");
    if(!f||fread(G,1,0xC00000,f)!=0xC00000)return 2;fclose(f);
    /* IMPORT_PATCHES */
    /* Prove the provider's own bind/send boundary without the shim override. */
    unsetenv("NFS_LAN_LOOPBACK");unsetenv("NFS_LAN_REAL");
    Cpu c={0};c.esp=0x3F00000;c.cw=0x37F;
    CarbonLanIdentity a={101,"Local Alpha",31000},b={202,"Local Beta",31001};
    /* FALLBACK_CALLS */
    CarbonLanIdentity missing=a;missing.id=0;
    CHECK(!carbon_lan_session_open(&c,&missing,&b,"local-invitation",1));
    missing=a;missing.id=65536;
    CHECK(!carbon_lan_session_open(&c,&missing,&b,"local-invitation",1));
    missing=a;missing.id=65535;
    CHECK(!carbon_lan_session_open(&c,&missing,&b,"local-invitation",1));
    missing=a;missing.name="";
    CHECK(!carbon_lan_session_open(&c,&missing,&b,"local-invitation",1));
    CHECK(!carbon_lan_session_open(&c,&a,&b,"",1));
    CHECK(!carbon_lan_session_open(&c,&a,&a,"local-invitation",1));
    CHECK(!carbon_lan_session_open(&c,NULL,&b,"local-invitation",1));
    fail_allocation=1;CHECK(!carbon_lan_session_open(&c,&a,&b,"local-invitation",1));released();
    if(argc>2&&!strcmp(argv[2],"process")){int result=process_pair(&c,a,b);free(G);return result;}
    int reject=argc>2?atoi(argv[2]):0;
    unsigned registered=0;
    for(unsigned cycle=0;cycle<(reject?1u:2u);++cycle){
    unsigned sa=carbon_lan_session_open(&c,&a,&b,"local-invitation",1);
    CarbonLanIdentity client=b;if(reject==4)client.id=303;
    unsigned sb=carbon_lan_session_open(&c,&client,&a,reject==3?"wrong-invitation":"local-invitation",0);
    CHECK(sa&&sb&&sa!=sb);
    if(!sa||!sb)return 1;
    CHECK(!carbon_lan_session_send(&c,sa,"early",5,1));
    uint64_t deadline=host_ticks()+2000000000ull;
    int ca=0,cb=0;
    while(host_ticks()<deadline&&(!ca||!cb)) {
        ca=carbon_lan_session_tick(&c,sa);cb=carbon_lan_session_tick(&c,sb);
        if(ca<0||cb<0)break;usleep(1000);
    }
    if(reject){
        CHECK((ca==-1||cb==-1)&&!(lan_sessions[sa-1].roster&&lan_sessions[sb-1].roster));
        CHECK(lan_sessions[sa-1].error==reject||lan_sessions[sb-1].error==reject);
        printf("LAN reject=%d transport=%d/%d hello=%d/%d roster=%d/%d failures=%u\n",reject,
            lan_sessions[sa-1].connected,lan_sessions[sb-1].connected,lan_sessions[sa-1].hello,lan_sessions[sb-1].hello,
            lan_sessions[sa-1].roster,lan_sessions[sb-1].roster,failures);
        carbon_lan_session_close(&c,sa);carbon_lan_session_close(&c,sb);released();free(G);return failures?1:0;
    }
    CHECK(ca==1&&cb==1);
    CHECK(lan_sessions[sa-1].hello&&lan_sessions[sb-1].hello);
    CHECK(lan_sessions[sa-1].roster&&lan_sessions[sb-1].roster);
    if(ca!=1||cb!=1){printf("LAN failed transport=%d/%d hello=%d/%d roster=%d/%d\n",lan_sessions[sa-1].connected,lan_sessions[sb-1].connected,
        lan_sessions[sa-1].hello,lan_sessions[sb-1].hello,lan_sessions[sa-1].roster,lan_sessions[sb-1].roster);
        carbon_lan_session_close(&c,sa);carbon_lan_session_close(&c,sb);return 1;}
    if(!cycle)registered=callback_count;
    CHECK(callback_count==registered);
    for(unsigned h=sa;h<=sb;++h){
        socket_boundary(&c,h);
        CarbonLanSession *s=&lan_sessions[h-1];
        CHECK(M32(s->gm+0x128)==s->player[0]-8&&M32(s->player[0]-4)==s->player[1]-8);
        for(unsigned i=0;i<2;++i){
            CHECK(M32(s->player[i]+0x18)==s->identity[i].id);
            CHECK(M32(s->player[i]+0x1C)==s->persona[i]);
            CHECK(M32(s->player[i]+0x24)==6);
            CHECK(M64(s->persona[i]+0x38)==s->identity[i].id);
        }
        CHECK(!s->error);
    }
    unsigned handles[2]={sa,sb};
    for(unsigned direction=0;direction<2;++direction){
        unsigned from=handles[direction],to=handles[1-direction];unsigned char data[24],next[24];
        for(unsigned seq=0;seq<3;++seq){payload(data,seq+direction*10);
            int reliable=seq!=1;CHECK(carbon_lan_session_send(&c,from,data,sizeof data,reliable));
            CHECK(message(&c,from,to,data,sizeof data,reliable));
        }
        payload(data,30+direction);payload(next,40+direction);
        CHECK(carbon_lan_session_send(&c,from,data,sizeof data,1));
        CHECK(carbon_lan_session_send(&c,from,next,sizeof next,1));
        for(unsigned i=0;i<8;++i){pump(&c,from,to);usleep(1000);}
        CHECK(message(&c,from,to,data,sizeof data,1));
        CHECK(message(&c,from,to,next,sizeof next,1));
    }
    CHECK(lan_sessions[sa-1].reliable==4&&lan_sessions[sb-1].reliable==4);
    CHECK(lan_sessions[sa-1].unreliable==1&&lan_sessions[sb-1].unreliable==1);
    CHECK(!carbon_lan_session_send(&c,sa,"x",512,1));
    printf("LAN cycle=%u transport=2 hello=2 roster=2 reliable=%u unreliable=%u callbacks=%u native=%u/%u/%u/%u/%u/%u\n",
        cycle,lan_sessions[sa-1].reliable+lan_sessions[sb-1].reliable,lan_sessions[sa-1].unreliable+lan_sessions[sb-1].unreliable,
        callback_count,native_counts[0],native_counts[1],native_counts[2],native_counts[3],native_counts[4],native_counts[5]);
    carbon_lan_session_close(&c,sa);carbon_lan_session_close(&c,sb);
    released();
    }
    CHECK(native_counts[0]==2&&native_counts[1]==2&&native_counts[2]==2&&native_counts[3]==2&&native_counts[4]==4&&native_counts[5]==4);
    printf("LAN %s checks=%u failures=%u sign-in=0\n",failures?"FAIL":"PASS",checks,failures);
    free(G);return failures?1:0;
}
'''


def bodies(base, starts):
    result = {}
    # Only networking and its serialization/address/CRT support. Everything
    # outside this boundary traps if reached, rather than silently succeeding.
    ranges = ((0x008E1B00, 0x008E2800), (0x008E7900, 0x008E9200),
              (0x00954000, 0x00960100), (0x00982300, 0x00983E00),
              (0x00988F00, 0x0098BC00), (0x0087DD00, 0x0087F300),
              (0x0094C790, 0x0094C930))
    ranges += ((0x0093F150,0x0093F230),(0x00938E20,0x00938EC0))
    selected = {a for a in starts if any(lo <= a < hi for lo, hi in ranges)}
    selected |= {0x00981280, 0x0092EF10, 0x00964900, 0x00964970,
                 0x008F4030, 0x008F4040, 0x008F4080, 0x0093F150,0x0093F1A0,
                 0x00818050, 0x00818070, 0x008180A0,0x008E0FE0,
                 0x009649B0,0x00964EA0,0x00988EA0,0x008E0E70}
    selected -= {0x009914B0}
    for chunk in sorted({starts.index(a)//build_all.CHUNK for a in selected}):
        source = (base / f'NFSC_{chunk:02d}.c').read_text()
        for match in re.finditer(r'void (?:f_|carbon_orig_)([0-9A-F]{8})\(Cpu [^)]*\)\s*\{', source):
            address = int(match[1], 16)
            if address not in selected:
                continue
            if address in result and not match[0].startswith('void carbon_orig_'):
                continue
            line_end = source.index('\n', match.end())
            end = line_end if '}' in source[match.end():line_end] else source.index('\n}',match.end())+2
            body = source[match.start():end]
            body = re.sub(r'void carbon_orig_', 'void f_', body, count=1)
            result[address] = body
    assert set(result) == selected
    return result


def main():
    base = HERE / 'out/carbon-base'
    if not (base/'image.json').is_file():
        print('SKIP: private LAN needs translated private image');return 3
    image = json.loads((base/'image.json').read_text())
    if not Path(image['exe']).is_file():
        print('SKIP: private LAN image unavailable');return 3
    pe = PE(image['exe'], expected_sha256=image['sha256'])
    starts = [int(v.removesuffix('u'),16) for v in re.search(
        r'guest_func_addr\[\] = \{([^}]+)',(base/'table.c').read_text())[1].split(',')]
    native = bodies(base, starts)
    for a,pin in PINS.items():
        assert hashlib.sha256(native[a].encode()).hexdigest()==pin,f'native body changed {a:08X}'
    limits=[(a,starts[i+1] if i+1<len(starts) else a+1,'') for i,a in enumerate(starts)]
    records=private_hooks.load_registry(pe,limits)
    assert {a:r['provider'].removeprefix('carbon_lan_') for a,r in records.items()
            if r['job']=='J2.local-session'}==HOOKS
    provider=HERE/'private_runtime/carbon_lan_session.c'
    feature=json.loads((HERE/'private_runtime/features/lan_session.json').read_text())
    assert feature['bindings'][provider.name]['sha256']==hashlib.sha256(provider.read_bytes()).hexdigest()
    counted = [0x00955FD0,0x00956B40,0x0095C300,0x0095C520,0x0095F720,0x0098B640]
    for i,a in enumerate(counted):
        native[a]=native[a].replace('{\n',f'{{\n    ++native_counts[{i}];\n',1)
    needed = {int(a,16) for code in native.values() for a in re.findall(r'\bf_([0-9A-F]{8})\(c\)',code)}
    traps = needed - native.keys() - HOOKS.keys() - {0x009914B0}
    retained = {a: native.pop(a).replace(f'void f_{a:08X}',f'void lan_orig_{a:08X}',1)
                for a in list(native.keys() & HOOKS.keys())}
    wrappers = '\n'.join(f'void f_{a:08X}(Cpu *c){{carbon_lan_{p}(c,{"lan_orig_"+format(a,"08X") if a in retained else "lan_original"});}}'
                         for a,p in HOOKS.items())
    harness = HARNESS.replace('/* DISPATCH */','\n'.join(
        f'case 0x{a:08X}: f_{a:08X}(c);return;' for a in sorted(native.keys()|HOOKS.keys())))
    harness = harness.replace('/* IMPORT_NAMES */','\n'.join(
        f'case {slot}: return {json.dumps(name.split("!")[-1])};' for slot,name in image['imports'].items()))
    harness = harness.replace('/* IMPORT_PATCHES */','\n'.join(
        f'M32({slot})=THUNK_BASE+{slot};' for slot in image['imports']))
    harness = harness.replace('/* FALLBACK_CALLS */','\n'.join(
        f'{{Cpu before=c;carbon_lan_{name}(&c,passthrough);CHECK(c.eax==before.eax+1&&c.esp==before.esp+4);c=before;}}'
        for name in HOOKS.values()))
    with tempfile.TemporaryDirectory(prefix='private-lan-') as td:
        tmp=Path(td)
        memory=bytearray(0xC00000)
        for _,_,va,size,raw in pe.sections:
            memory[pe.base+va:pe.base+va+size]=pe.data[raw:raw+size]
        (tmp/'image.bin').write_bytes(memory)
        source=tmp/'fixture.c'
        source.write_text('#include "funcs.h"\n#include "host.h"\n#include <stdlib.h>\n#include <stdio.h>\nstatic unsigned native_counts[6];\n'+
            '\n'.join(f'void carbon_lan_{p}(Cpu *,void (*)(Cpu *));' for p in HOOKS.values())+
            '\nstatic void lan_original(Cpu *c){fprintf(stderr,"unexpected native fallback ra=%08X\\n",M32(c->esp));exit(2);}\n'+
            '\n'.join(retained.values())+'\n'+wrappers+
            '\n'.join(native.values())+'\n'+
            '\n'.join(f'void f_{a:08X}(Cpu *c){{fprintf(stderr,"unexpected leaf {a:08X} ra=%08X\\n",M32(c->esp));exit(2);}}' for a in sorted(traps))+
            '\n'+harness)
        args=['clang','-O0','-w','-DNFS_GAME=2','-I'+str(HERE),'-I'+str(base),
              '-I'+str(ROOT/'runtime'),'-I'+str(HERE/'private_runtime'),str(source),
              str(ROOT/'runtime/ws2_32.c'),str(HERE/'private_runtime/crt.c'),'-o',str(tmp/'fixture')]
        canonical=source.read_text()
        production=provider.read_text()
        (tmp/provider.name).write_text(production)
        evidence=[]
        def build_run(label,code=canonical,implementation=production,reject=None,expected=0,opt='-O0'):
            source.write_text(code);(tmp/provider.name).write_text(implementation)
            command=args.copy();command[1]=opt
            built=subprocess.run(command,capture_output=True,text=True)
            assert built.returncode==0,built.stderr[-5000:]
            command=[str(tmp/'fixture'),str(tmp/'image.bin')]
            if reject is not None:command.append(str(reject))
            result=subprocess.run(command,capture_output=True,text=True,timeout=15)
            evidence.append(label+':\n'+result.stdout)
            assert result.returncode==expected,(label,result.returncode,result.stdout,result.stderr[-5000:])
            return result.stdout
        removed=production.replace('if(s->connected&&!s->host&&!s->hello&&!s->ack)', 'if(0)')
        assert removed!=production
        red=build_run('bootstrap removed',implementation=removed,expected=1)
        assert 'transport=1/1 hello=0/0 roster=0/0' in red,red
        good=build_run('native local sessions',opt='-O1')
        assert 'LAN PASS' in good
        # Same binary/codec with a different invitation must not join.
        for reject,label in ((3,'ticket mismatch'),(4,'identity mismatch')):
            result=subprocess.run([str(tmp/'fixture'),str(tmp/'image.bin'),str(reject)],capture_output=True,text=True,timeout=15)
            evidence.append(label+':\n'+result.stdout)
            assert result.returncode==0,(result.stdout,result.stderr)
        result=subprocess.run([str(tmp/'fixture'),str(tmp/'image.bin'),'process'],capture_output=True,text=True,timeout=15)
        evidence.append('independent processes:\n'+result.stdout)
        assert result.returncode==0,(result.stdout,result.stderr)
        for a,label in ((0x00955FD0,'client protocol'),(0x00956B40,'host protocol')):
            changed=native[a].replace('uint32_t v = 0x4u;', 'uint32_t v = 0x3u;',1)
            assert changed!=native[a]
            build_run(label,code=canonical.replace(native[a],changed,1),reject=2)
        reliable=production.replace('0u,(uint32_t)!!reliable,0u','0u,1u,0u')
        assert reliable!=production
        build_run('unreliable forced reliable',implementation=reliable,expected=1)
        proof='\n'.join(evidence)
        (HERE/'out/carbon-lan-session-proof.txt').write_text(proof)
        print(proof,end='')
    return 0


if __name__=='__main__':
    sys.exit(main())
