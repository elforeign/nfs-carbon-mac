"""Carbon LAN: bound discovery, native session and retained room notifications.

Red controls run before green: absent discovery/entry/session, expired entry,
incompatible protocol/image, cancelled invitation and frozen Ready. Each must
exit 1; production must exit 0. Networking executes the pinned translated J2
GameManager/CommUDP bodies, with real loopback sockets and no account service.
The room constructor, push/pop adapters and destructor are translated too;
the fixture supplies FE rendering/queue storage, never session state.
Exit 3 without private inputs. Dependencies: carbon_lan.h carbon_lan_session.c
carbon_lan_discovery.c carbon_lan_menu.c carbon_port_settings.h
features/lan_menu.json hooks/lan_menu.json game_picture_present.h
private_lan_session_test.py
Measured: 191 green checks / 0 failures across six scenarios; ten broken
controls exit 1 with 1/1/2/1/1/2/2/1/1/7 failed assertions respectively.
Rejection fixtures poll for actual UDP delivery before feeding the production
decoder/consumer; a missing datagram is a test failure, never a rejection pass.
"""
from pathlib import Path
import hashlib
import json
import re
import subprocess
import sys
import tempfile

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent
sys.path.insert(0,str(HERE))
import private_lan_session_test as session
from recomp import PE

MENU_HOOKS={0x005C7A60:'construct',0x005CC140:'notification',0x005BEBE0:'destroy'}
FE_NATIVE=set(MENU_HOOKS)|{0x005F71C0,0x005F71E0}
FE_STUBS={0x005B25F0,0x005A9320,0x005BEC70,0x00584160,0x005F2AC0,
          0x005A0910,0x005983F0,0x005F3760,0x005A9440,0x005B9060,0x004A04E0}

HARNESS=r'''
#include "carbon_lan_discovery.c"
#include "carbon_lan_menu.c"
#include <poll.h>
static unsigned queued,fe_slots,fe_pops;
static char labels[8][256];
static char title[64],footer[32];
const char *settings_text(const char *id){(void)id;return "Room Host";}
void portmenu_status(const char *fmt,...){(void)fmt;}
static void fe_boundary(Cpu *c,uint32_t fn,unsigned pop){
    if(fn==0x005B25F0){M32(c->ecx+0xC)=M32(arg(c,0));M32(c->ecx+0x4C)=arg(c,1);M32(c->ecx+0x50)=arg(c,2);}
    else if(fn==0x005BEC70){fe_slots=M32(c->ecx+0x4C)*M32(c->ecx+0x50);}
    else if(fn==0x00584160)c->eax=1;
    else if(fn==0x005F2AC0){
        if(arg(c,0)==2){CHECK(!strcmp(gptr(arg(c,2)),"FeOnlineGameRoom.fng"));CHECK(arg(c,1)==1);queued=1;}
        else if(arg(c,0)==1){queued=2;++fe_pops;}
        else CHECK(0);
    } else if(fn==0x005A0910){
        if(arg(c,1)==0x03C458C1)snprintf(title,sizeof title,"%s",(char *)gptr(arg(c,3)));
        if(arg(c,1)==0x666D40DF)snprintf(footer,sizeof footer,"%s",(char *)gptr(arg(c,3)));
        for(unsigned i=0;i<8;++i){char name[32];snprintf(name,sizeof name,"PLAYER%u",i+1);
            if(arg(c,1)==clm_hash(name)){CHECK(!strcmp(gptr(arg(c,2)),"%s"));snprintf(labels[i],256,"%s",(char *)gptr(arg(c,3)));}}
    } else if(fn==0x005983F0||fn==0x005F3760)c->eax=0;
    c->esp+=pop;
}
static void fe_drain(Cpu *c){
    unsigned q=queued;queued=0;
    if(q==1){uint32_t info=0xD00100;M32(info)=carbon_lan_menu.text;
        Cpu save=*c;c->ecx=0xD01000;call_guest(c,0x005C7A60,1,&info);*c=save;}
    else if(q==2){Cpu save=*c;c->ecx=carbon_lan_menu.room;call_guest(c,0x005BEBE0,0,NULL);*c=save;}
}
static void lobbies(Cpu *c,CarbonLanLobby *a,CarbonLanLobby *b){
    carbon_lan_lobby_tick(c,a);carbon_lan_lobby_tick(c,b);
}
static int appears(Cpu *c,CarbonLanLobby *a,CarbonLanLobby *b){
    uint64_t stop=cdl_now()+1200;
    do{lobbies(c,a,b);if(b->count)return 1;usleep(1000);}while(cdl_now()<stop);
    return 0;
}
static int pair(Cpu *c,CarbonLanLobby *a,CarbonLanLobby *b){
    CHECK(carbon_lan_lobby_open(c,a,"Alpha",1));CHECK(carbon_lan_lobby_open(c,b,"Beta",0));
    CHECK(appears(c,a,b));return a->state==CARBON_LAN_HOST&&b->count==1;
}
static int room(Cpu *c,CarbonLanLobby *a,CarbonLanLobby *b){
    uint64_t stop=cdl_now()+2500;
    do{lobbies(c,a,b);if(a->agreed&&b->agreed)return 1;usleep(1000);}while(cdl_now()<stop);
    return 0;
}
static void clear_pair(Cpu *c,CarbonLanLobby *a,CarbonLanLobby *b){
    carbon_lan_lobby_close(c,a);carbon_lan_lobby_close(c,b);released();
    for(unsigned i=0;i<LAN_PEERS;++i)CHECK(!lan_reserved[i].port);
}
static int held(uint32_t address,unsigned port){
    int fd=socket(AF_INET,SOCK_DGRAM,0);struct sockaddr_in a=cdl_address(address,port);
    int result=bind(fd,(struct sockaddr *)&a,sizeof a);close(fd);return result<0;
}
static void raw(CarbonLanLobby *from,CarbonLanLobby *to,unsigned char *p){
    struct sockaddr_in a=cdl_address(to->address,to->control_port);
    CHECK(sendto(from->fd,p,CDL_PACKET,0,(struct sockaddr *)&a,sizeof a)==CDL_PACKET);
}
static void delivered(Cpu *c,CarbonLanLobby *l){
    struct pollfd fd={l->fd,POLLIN,0};int ready=poll(&fd,1,1000);
    CHECK(ready==1&&(fd.revents&POLLIN));if(ready!=1)return;
    unsigned char packet[CDL_PACKET+1];struct sockaddr_in from={0};socklen_t size=sizeof from;
    ssize_t n=recvfrom(l->fd,packet,sizeof packet,0,(struct sockaddr *)&from,&size);
    CHECK(n==CDL_PACKET);CarbonLanListing p;
    if(n==CDL_PACKET&&cdl_decode(packet,n,&from,&p))cdl_receive(c,l,packet,&p);
}
static void success(Cpu *c){
    CarbonLanLobby a={0},b={0};if(!pair(c,&a,&b)){clear_pair(c,&a,&b);return;}
    CHECK(b.rows[0].game_port==a.game_port&&b.rows[0].address==a.address);
    CHECK(a.address==0x7F000001&&b.address==0x7F000001);
    CHECK(held(a.address,a.game_port)&&held(b.address,b.game_port));
    CHECK(carbon_lan_lobby_join(c,&b,0));CHECK(room(c,&a,&b));
    if(a.session&&b.session){
        CHECK(held(a.address,a.game_port)&&held(b.address,b.game_port));
        CarbonLanSession *sa=&lan_sessions[a.session-1],*sb=&lan_sessions[b.session-1];
        CHECK(sa->identity[0].id==sb->identity[1].id&&sa->identity[1].id==sb->identity[0].id);
        CHECK(!strcmp(gptr(sa->persona[0]+0x40),gptr(sb->persona[1]+0x40)));
        CHECK(M64(sa->persona[0]+0x38)==a.id&&M64(sb->persona[1]+0x38)==a.id);
        CHECK((uint32_t)a.id<65535&&(uint32_t)b.id<65535);
        for(unsigned i=0;i<2;++i)CHECK(M32(sa->player[i]+0x24)==6&&M32(sb->player[i]+0x24)==6);
        carbon_lan_lobby_ready(&a,1);uint64_t stop=cdl_now()+900;
        do{lobbies(c,&a,&b);usleep(1000);}while(!b.remote_ready&&cdl_now()<stop);
        CHECK(b.remote_ready==1&&a.remote_ready==0);
        carbon_lan_lobby_ready(&b,1);carbon_lan_lobby_ready(&a,0);stop=cdl_now()+900;
        do{lobbies(c,&a,&b);usleep(1000);}while((!a.remote_ready||b.remote_ready)&&cdl_now()<stop);
        CHECK(a.remote_ready==1&&b.remote_ready==0&&a.local_ready==0&&b.local_ready==1);
    }
    printf("room=%d/%d personas=%s/%s ready=%d/%d native=%u/%u\n",a.state,b.state,a.name,b.name,a.remote_ready,b.remote_ready,native_counts[0],native_counts[1]);
    clear_pair(c,&a,&b);
}
static void expired(Cpu *c){
    CarbonLanLobby a={0},b={0};if(!pair(c,&a,&b)){clear_pair(c,&a,&b);return;}
    b.rows[0].seen=cdl_now()-CARBON_LAN_EXPIRY_MS;b.last_query=cdl_now();
    CHECK(!carbon_lan_lobby_join(c,&b,0));CHECK(!b.session&&b.state==CARBON_LAN_BROWSE);
    carbon_lan_lobby_tick(c,&b);CHECK(b.count==0);clear_pair(c,&a,&b);
}
static void incompatible(Cpu *c){
    CarbonLanLobby a={0},b={0};if(!pair(c,&a,&b)){clear_pair(c,&a,&b);return;}
    for(unsigned offset=0;offset<4;++offset){
        unsigned char p[CDL_PACKET];cdl_packet(&a,CDL_ANNOUNCE,p);
        unsigned at=offset==0?0:offset==1?8:offset==2?9:12;p[at]^=1;
        b.count=0;b.last_query=cdl_now();raw(&a,&b,p);
        delivered(c,&b);CHECK(b.count==0);
    }
    unsigned char p[CDL_PACKET];cdl_packet(&a,CDL_ANNOUNCE,p);raw(&a,&b,p);
    delivered(c,&b);CHECK(b.count==1);clear_pair(c,&a,&b);
}
static void cancelled(Cpu *c){
    CarbonLanLobby a={0},b={0};if(!pair(c,&a,&b)){clear_pair(c,&a,&b);return;}
    CHECK(carbon_lan_lobby_join(c,&b,0));unsigned char p[CDL_PACKET];cdl_packet(&b,CDL_JOIN,p);
    uint32_t address=b.address;uint16_t control=b.control_port;uint64_t nonce=a.nonce;
    carbon_lan_lobby_close(c,&b);delivered(c,&a);delivered(c,&a);
    CHECK(a.state==CARBON_LAN_HOST&&!a.session&&a.nonce!=nonce);
    int fd=socket(AF_INET,SOCK_DGRAM,0);struct sockaddr_in local=cdl_address(address,control);
    CHECK(bind(fd,(struct sockaddr *)&local,sizeof local)==0);
    struct sockaddr_in to=cdl_address(a.address,a.control_port);
    CHECK(sendto(fd,p,sizeof p,0,(struct sockaddr *)&to,sizeof to)==sizeof p);
    delivered(c,&a);CHECK(a.state==CARBON_LAN_HOST&&!a.session);
    close(fd);clear_pair(c,&a,&b);
    /* A reordered cancellation must invalidate its invitation even when the
     * host has not received the corresponding join request yet. */
    if(!pair(c,&a,&b)){clear_pair(c,&a,&b);return;}
    b.peer=b.rows[0];b.attempt=cdl_random();
    cdl_packet(&b,CDL_CANCEL,p);raw(&b,&a,p);cdl_packet(&b,CDL_JOIN,p);raw(&b,&a,p);
    delivered(c,&a);delivered(c,&a);CHECK(a.state==CARBON_LAN_HOST&&!a.session);
    clear_pair(c,&a,&b);
}
static void frontend(Cpu *c){
    M32(0xA97A78)=0xD00000;M32(0xD00000)=0xD10000;M32(0xA99BBC)=3;M32(0xA97B7C)=0;
    carbon_lan_menu_tick(c);CHECK(!allocations_live);
    carbon_lan_menu_host(0);carbon_lan_menu_tick(c);CHECK(queued==1);
    if(!queued){carbon_lan_lobby_close(c,&carbon_lan_menu.lobby);return;}
    fe_drain(c);CHECK(carbon_lan_menu.room==0xD01000&&fe_slots==8);
    CHECK(!strcmp(title,"LAN ROOM")&&!strcmp(footer,"READY"));
    CarbonLanLobby client={0},*host=&carbon_lan_menu.lobby;
    CHECK(carbon_lan_lobby_open(c,&client,"Room Client",0));CHECK(appears(c,host,&client));
    CHECK(carbon_lan_lobby_join(c,&client,0));CHECK(room(c,host,&client));
    Cpu saved=*c;c->ecx=carbon_lan_menu.room;uint32_t events[4]={0x406415E3,0,1,0}; /* PAD_ACCEPT */
    uint32_t sp=c->esp;call_guest(c,0x005CC140,4,events);CHECK(c->esp==sp);*c=saved;
    carbon_lan_lobby_ready(&client,1);uint64_t stop=cdl_now()+1000;
    do{carbon_lan_menu_tick(c);carbon_lan_lobby_tick(c,&client);usleep(1000);}while((!host->remote_ready||!client.remote_ready)&&cdl_now()<stop);
    carbon_lan_menu.draw_at=0;carbon_lan_menu_tick(c);
    CHECK(!strcmp(labels[0],"Room Host / READY")&&!strcmp(labels[1],"Room Client / READY"));
    saved=*c;c->ecx=carbon_lan_menu.room;events[0]=0x911AB364; /* PAD_BACK */
    call_guest(c,0x005CC140,4,events);*c=saved;
    CHECK(host->state==CARBON_LAN_IDLE&&!host->session);
    carbon_lan_menu_tick(c);CHECK(queued==2);fe_drain(c);
    CHECK(!carbon_lan_menu.room&&!carbon_lan_menu.text&&fe_pops==1&&M32(0xA97B7C)==0);
    carbon_lan_lobby_close(c,&client);released();
    printf("FE package=FeOnlineGameRoom.fng slots=%u pops=%u labels=%s;%s\n",fe_slots,fe_pops,labels[0],labels[1]);
}
typedef struct {uint64_t id,peer;int state,agreed,ready;unsigned failed;} LobbyReport;
static void independent(Cpu *c){
    int channel[2];CHECK(!pipe(channel));pid_t child=fork();CHECK(child>=0);if(child<0)return;
    CarbonLanLobby l={0};int host=child!=0;close(channel[host?1:0]);
    CHECK(carbon_lan_lobby_open(c,&l,host?"Process Host":"Process Client",host));
    uint64_t stop=cdl_now()+3500;
    do{
        carbon_lan_lobby_tick(c,&l);
        if(!host&&l.state==CARBON_LAN_BROWSE&&l.count)CHECK(carbon_lan_lobby_join(c,&l,0));
        if(l.state==CARBON_LAN_ROOM&&!l.local_ready)carbon_lan_lobby_ready(&l,1);
        if(l.agreed&&l.remote_ready)break;usleep(1000);
    }while(cdl_now()<stop);
    CHECK(l.state==CARBON_LAN_ROOM&&l.agreed&&l.remote_ready);
    LobbyReport me={l.id,l.peer.id,l.state,l.agreed,l.remote_ready,failures};
    if(!host){CHECK(write(channel[1],&me,sizeof me)==sizeof me);close(channel[1]);
        /* Give the host time to consume the last native Ready packet. */
        for(unsigned i=0;i<150;++i){carbon_lan_lobby_tick(c,&l);usleep(1000);}
        carbon_lan_lobby_close(c,&l);_exit(failures?1:0);}
    LobbyReport peer={0};CHECK(read(channel[0],&peer,sizeof peer)==sizeof peer);close(channel[0]);
    int status=0;CHECK(waitpid(child,&status,0)==child&&WIFEXITED(status)&&WEXITSTATUS(status)==0);
    CHECK(!peer.failed&&peer.id==me.peer&&peer.peer==me.id&&peer.agreed&&peer.ready);
    carbon_lan_lobby_close(c,&l);released();printf("independent processes=2 personas=2 ready=2 failures=%u\n",failures);
}
int main(int argc,char **argv){
    if(argc!=3)return 2;G=calloc(1,0x4000000);FILE *f=fopen(argv[1],"rb");
    if(!f||fread(G,1,0xC00000,f)!=0xC00000)return 2;fclose(f);
    /* IMPORT_PATCHES */
    unsetenv("NFS_LAN_REAL");unsetenv("NFS_LAN_LOOPBACK");
    Cpu c={0};c.esp=0x3F00000;c.cw=0x37F;
    if(!strcmp(argv[2],"expired"))expired(&c);
    else if(!strcmp(argv[2],"incompatible"))incompatible(&c);
    else if(!strcmp(argv[2],"cancelled"))cancelled(&c);
    else if(!strcmp(argv[2],"frontend"))frontend(&c);
    else if(!strcmp(argv[2],"process"))independent(&c);
    else success(&c);
    printf("LAN MENU %s case=%s checks=%u failures=%u sign-in=0\n",failures?"FAIL":"PASS",argv[2],checks,failures);
    free(G);return failures?1:0;
}
'''


def extract(base,starts,addresses):
    found={}
    for chunk in sorted({starts.index(a)//session.build_all.CHUNK for a in addresses}):
        source=(base/f'NFSC_{chunk:02d}.c').read_text()
        for match in re.finditer(r'void (?:f_|carbon_orig_)([0-9A-F]{8})\(Cpu [^)]*\)\s*\{',source):
            a=int(match[1],16)
            if a not in addresses:continue
            if a in found and not match[0].startswith('void carbon_orig_'):continue
            line_end=source.index('\n',match.end())
            end=line_end if '}' in source[match.end():line_end] else source.index('\n}',match.end())+2
            found[a]=re.sub('void carbon_orig_','void f_',source[match.start():end],count=1)
    assert found.keys()==addresses
    return found


def main():
    base=HERE/'out/carbon-base'
    if not (base/'image.json').is_file():print('SKIP: private translation absent');return 3
    image=json.loads((base/'image.json').read_text())
    if not Path(image['exe']).is_file():print('SKIP: private image absent');return 3
    pe=PE(image['exe'],expected_sha256=image['sha256'])
    starts=[int(v.removesuffix('u'),16) for v in re.search(r'guest_func_addr\[\] = \{([^}]+)',(base/'table.c').read_text())[1].split(',')]
    native=session.bodies(base,starts)
    limits=[(a,starts[i+1] if i+1<len(starts) else a+1,'') for i,a in enumerate(starts)]
    records=session.private_hooks.load_registry(pe,limits)
    assert {a:r['provider'].removeprefix('carbon_lan_menu_') for a,r in records.items()
            if r['job']=='J3.lan-menu'}==MENU_HOOKS
    assert (HERE/'private_runtime/game_picture_present.h').read_text().count('carbon_lan_menu_tick(c);')==1
    for a,pin in session.PINS.items():assert hashlib.sha256(native[a].encode()).hexdigest()==pin
    native.update(extract(base,starts,FE_NATIVE))
    stubs=extract(base,starts,FE_STUBS)
    hooks={a:'carbon_lan_'+name for a,name in session.HOOKS.items()}
    hooks.update({a:'carbon_lan_menu_'+name for a,name in MENU_HOOKS.items()})
    for i,a in enumerate([0x00955FD0,0x00956B40,0x0095C300,0x0095C520,0x0095F720,0x0098B640]):
        native[a]=native[a].replace('{\n',f'{{\n ++native_counts[{i}];\n',1)
    needed={int(a,16) for code in native.values() for a in re.findall(r'\bf_([0-9A-F]{8})\(c\)',code)}
    traps=needed-native.keys()-hooks.keys()-FE_STUBS-{0x009914B0}
    originals={a:native.pop(a).replace(f'void f_{a:08X}',f'void test_orig_{a:08X}',1) for a in list(native.keys()&hooks.keys())}
    prefix=session.HARNESS[:session.HARNESS.index('int main(')]
    # Includes resolve to staged copies, allowing explicit broken controls.
    harness=(prefix+HARNESS).replace('int diag_on=0','int diag_on=1')
    harness=harness.replace('/* DISPATCH */','\n'.join(f'case 0x{a:08X}: f_{a:08X}(c);return;' for a in sorted(native.keys()|hooks.keys()|FE_STUBS)))
    harness=harness.replace('/* IMPORT_NAMES */','\n'.join(f'case {slot}:return {json.dumps(name.split("!")[-1])};' for slot,name in image['imports'].items()))
    harness=harness.replace('/* IMPORT_PATCHES */','\n'.join(f'M32({slot})=THUNK_BASE+{slot};' for slot in image['imports']))
    stub_code=[]
    for a,body in stubs.items():
        pop=re.findall(r'c->esp \+= (\d+); return;',body)[-1]
        stub_code.append(f'void f_{a:08X}(Cpu *c){{fe_boundary(c,0x{a:08X},{pop});}}')
    source=('#include "funcs.h"\n#include "host.h"\n#include <stdlib.h>\n#include <stdio.h>\nstatic unsigned native_counts[6];\n'
        'static void fe_boundary(Cpu *,uint32_t,unsigned);\n'+
        '\n'.join(f'void {p}(Cpu *,void (*)(Cpu *));' for p in hooks.values())+
        '\nstatic void test_original(Cpu *c){fprintf(stderr,"unexpected original %08X\\n",M32(c->esp));exit(2);}\n'+
        '\n'.join(originals.values())+'\n'+
        '\n'.join(f'void f_{a:08X}(Cpu *c){{{p}(c,{"test_orig_"+format(a,"08X") if a in originals else "test_original"});}}' for a,p in hooks.items())+
        '\n'+'\n'.join(native.values())+'\n'+'\n'.join(stub_code)+'\n'+
        '\n'.join(f'void f_{a:08X}(Cpu *c){{fprintf(stderr,"unexpected leaf {a:08X}\\n");exit(2);}}' for a in sorted(traps))+'\n'+harness)
    production={name:(HERE/'private_runtime'/name).read_text() for name in ('carbon_lan_session.c','carbon_lan_discovery.c','carbon_lan_menu.c','carbon_lan.h')}
    evidence=[]
    with tempfile.TemporaryDirectory(prefix='private-lan-menu-') as directory:
        td=Path(directory);memory=bytearray(0xC00000)
        for _,_,va,size,raw in pe.sections:memory[pe.base+va:pe.base+va+size]=pe.data[raw:raw+size]
        (td/'image.bin').write_bytes(memory);(td/'fixture.c').write_text(source)
        command=['clang','-O1','-w','-DNFS_GAME=2','-I'+str(HERE),'-I'+str(base),'-I'+str(ROOT/'runtime'),'-I'+str(HERE/'private_runtime'),str(td/'fixture.c'),str(ROOT/'runtime/ws2_32.c'),str(HERE/'private_runtime/crt.c'),'-o',str(td/'fixture')]
        def build(changes):
            for name,text in production.items():(td/name).write_text(changes.get(name,text))
            result=subprocess.run(command,capture_output=True,text=True)
            assert result.returncode==0,result.stderr[-4000:]
        def run(label,case,expected):
            result=subprocess.run([str(td/'fixture'),str(td/'image.bin'),case],capture_output=True,text=True,timeout=12)
            evidence.append(label+': '+result.stdout.strip())
            assert result.returncode==expected,(label,result.returncode,result.stdout,result.stderr[-3500:])
            print(evidence[-1],flush=True)
        controls=[
            ('discovery absent','carbon_lan_discovery.c','if(type==CDL_QUERY&&l->state==CARBON_LAN_HOST)','if(0)','success'),
            ('native session absent','carbon_lan_discovery.c','l->session=carbon_lan_session_open(c,&local,&remote,l->ticket,l->hosting);','l->session=0;','success'),
            ('expiry ignored','carbon_lan_discovery.c','now-p->seen>=CARBON_LAN_EXPIRY_MS||','', 'expired'),
            ('protocol ignored','carbon_lan_discovery.c','p[9]!=4||','', 'incompatible'),
            ('image ignored','carbon_lan_discovery.c','memcmp(p+12,cdl_build,64)||','', 'incompatible'),
            ('cancelled invitation reused','carbon_lan_discovery.c','type==CDL_JOIN&&l->hosting&&p->nonce==l->nonce&&attempt','type==CDL_JOIN&&l->hosting&&attempt','cancelled'),
            ('ready frozen','carbon_lan_discovery.c','message[28]=l->local_ready;','message[28]=0;','success'),
            ('room entry absent','carbon_lan_menu.c','clm_call(c,0x005F71C0,engine,2,a);','(void)a;','frontend'),
            ('wrong native accept','carbon_lan_menu.c','event==0x406415E3','event==0x912342F6','frontend'),
            ('wrong native back','carbon_lan_menu.c','event==0x911AB364','event==0x912342F6','frontend'),
        ]
        for label,name,before,after,case in controls:
            assert production[name].count(before)==1,(label,before)
            build({name:production[name].replace(before,after,1)});run('RED '+label,case,1)
        build({})
        for case in ('success','expired','incompatible','cancelled','frontend','process'):run('GREEN',case,0)
    proof='\n'.join(evidence)+'\n';(HERE/'out/carbon-lan-menu-proof.txt').write_text(proof)
    return 0

if __name__=='__main__':raise SystemExit(main())
