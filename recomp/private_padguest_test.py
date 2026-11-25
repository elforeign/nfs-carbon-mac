"""Hardware-free Carbon guest input/FE lifecycle, native IO and queue primitives.

Good: 0/2664 failures, actual translated x87 converter and ring operations.
Broken controls: missing x87 value 22/2664, null dialog owner 3/2664,
one device 327/2668, null allocation 2/2668, one queue 5/2440, wrong column
17/2664, missing identities 2340/2664, connection fallback 1/2664,
leaked queue 5/2655, repeated unplug 2/2666, root overwrite 2/2672.
ASan/UBSan, no hardware. Press/release values straddle the native .5 threshold.
The padbind companion proves 72 scalar channels and authored menu ownership.
Exit 3 without the private image and translated output.
"""
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
PRIVATE = HERE / 'private_runtime'
# Actual native ring operations and IO constructor, with only host boundaries fake.
NATIVE = (0x6892B0, 0x56FF80, 0x572AC0, 0x678900, 0x678960, 0x680310, 0x680320, 0x680350, 0x6891E0, 0x87EAC0)
HARNESS = r'''
#include "funcs.h"
#include "host.h"
#include <stdlib.h>
uint8_t *G;
int diag_on;
static unsigned checks, failures, originals, backend_calls, init_calls, factories;
static unsigned allocs, frees, destructs, fail_alloc, factory_fail, modal;
static int pads=2, connected[2]={1,1};
#define IO 0xA991D8u
#define FE 0x300000u
#define DB 0x310000u
#define PORTS 0x320000u
#define STACK 0x500000u
#define CHECK(x) do { ++checks; if (!(x)) {if(failures<8)fprintf(stderr,"FAIL %d %s\n",__LINE__,#x); ++failures;} } while(0)
int pad_count(void){return pads;}
int pad_read_n(int n,PadState *s){memset(s,0,sizeof *s);s->connected=connected[n];return s->connected;}
void diag_event(const char *f,...){(void)f;}
#include "native.inc"
#include "carbon_padguest.c"
static Cpu cpu(uint32_t self) {Cpu c={0};c.ecx=self;c.esp=STACK;c.esi=IO;c.fs_base=0x700000;M32(STACK)=0xFEEDF00D;return c;}
static void original(Cpu *c){++originals;c->esp+=4;}
static void backend(Cpu *c){++backend_calls;c->esp+=4;}
static void init(Cpu *c){
    if(!M32(c->ecx+0x24)){++init_calls;M32(c->ecx+0x18)=c->ecx+0x34;M32(c->ecx+0x1C)=c->ecx+0x1034;M32(c->ecx+0x20)=c->ecx+0x1434;}
    c->esp+=4;
}
void f_0067A680(Cpu *c){carbon_padguest_backend(c,backend);}
void f_00606B60(Cpu *c){
    uint32_t a=arg(c,0);const char *s=(char *)G+a;
    c->eax=!strcmp(s,"GameDevice")?1:!strcmp(s,"MouseDevice")?2:!strcmp(s,"KeyboardDevice")?3:a;c->esp+=4;
}
void f_006959A0(Cpu *c){++destructs;M32(c->ecx+0x298)=0xDEAD;c->esp+=4;}
void f_00609E80(Cpu *c){CHECK(c->ecx==0xA99720);CHECK(arg(c,1)==0x29C);CHECK(M32(arg(c,0)+0x298)==0xDEAD);++frees;c->esp+=16;}
void f_006A1590(Cpu *c){CHECK(arg(c,0)==FE);c->esp+=4;}
void f_00694C50(Cpu *c){carbon_padguest_initialize(c,init);}
static void reset(void){
    carbon_padguest_second=carbon_padguest_fe=0;memset(G,0,0xC00000);
    pads=2;allocs=frees=destructs=fail_alloc=factory_fail=backend_calls=init_calls=factories=modal=0;
    connected[0]=connected[1]=1;
    strcpy((char *)G+0x9E2398,"GameDevice");strcpy((char *)G+0x9E238C,"MouseDevice");strcpy((char *)G+0x9E237C,"KeyboardDevice");
    M32(0xA989A0)=0x80000;
    for(unsigned p=0;p<3;++p){uint32_t r=0x80000+12*p;M32(r)=p+1;M32(r+4)=0x11111110+p;M32(r+8)=p<2?r+12:0;}
    for(unsigned a=0;a<72;++a)M32(0xA98700+8*a)=0x40000+16*a;
    M32(0xA97A78)=0x330000;M32(0x330000)=0xFFFFFF28u;MF32(0x9C2888)=.5f;M32(0xA97814)=FE;M32(0xA97A7C)=DB;M32(DB+0xCC)=PORTS;M32(DB+0xC8)=~0u;M8(PORTS)=0;M8(PORTS+1)=1;M32(0xA99BBC)=6;
    M32(0xA604B8)=0x81000;M32(0x81000)=0x22222220;
    for(unsigned r=0;r<16;++r){M32(0xA5E038+28*r)=r+0x30;M32(0xA5E044+28*r)=0x11110000+r;M32(0xA5E048+28*r)=0x22220000+r;}
}
static void io_init(void){Cpu c=cpu(IO);native_006892B0(&c);CHECK(c.esp==STACK+4);}
static uint32_t make_fe(void){Cpu c=cpu(FE);carbon_padguest_construct(&c,original);CHECK(c.esp==STACK+4);CHECK(c.eax==FE);return carbon_padguest_queue(FE,1);}
static void device_proof(void){
    for(unsigned broken=0;broken<2;++broken){reset();factory_fail=broken;io_init();
        CHECK(backend_calls==1);CHECK(init_calls==1);CHECK(M32(IO+4)==4);CHECK(M32(IO+8)==0x100000);
        CHECK(M32(IO+12)==(broken?0:0x102000));CHECK(M32(IO+16)==0x200000);CHECK(M32(IO+20)==0x210000);CHECK(M32(IO+0x48)==(broken?13:15));
        if(broken)continue;
        uint32_t d=M32(IO+12);CHECK(M32(d+0x24)==1);CHECK(M32(d+0x18)==d+0x34);CHECK(M32(d+0x1C)==d+0x1034);CHECK(M32(d+0x20)==d+0x1434);CHECK(M32(d+0x1838)==72);
        for(unsigned a=0;a<72;++a){uint32_t r=M32(d+0x18)+16*a;CHECK(M32(r)==1);CHECK(M32(r+4)==0x40000+16*a);CHECK(M32(r+8)==d+0x1034+4*a);CHECK(M32(r+12)==d+0x1434+4*a);}
        for(unsigned a=0;a<0x800;++a)CHECK(M8(d+0x1034+a)==0);
    }
    reset();pads=1;io_init();CHECK(M32(IO+4)==3);CHECK(M32(IO+12)==0x200000);CHECK(M32(IO+16)==0x210000);CHECK(factories==1);
}
static void push(uint32_t q,unsigned id,float value){M32(q)=1;M32(q+8)=0;M32(q+12)=50;M32(q+16)=id;M32(q+20)=0;MF32(q+24)=value;}
static void event_proof(void){
    reset();io_init();uint32_t q1=make_fe(),q0=M32(FE);CHECK(q1!=0);if(!q1)return;
    CHECK(M32(q0+0x268)==0);CHECK(M32(q1+0x268)==1);CHECK(!M32(FE+4)&&!M32(FE+8));CHECK(M32(FE+12)==0x82D21520);
    for(unsigned r=0;r<16;++r){
        uint32_t p0=M32(0xA5E044+28*r);push(q1,r+0x30,1);Cpu c=cpu(FE);carbon_padguest_events(&c,original);
        CHECK(c.esp==STACK+4);CHECK(M32(0xA5E044+28*r)==p0);CHECK(M32(0xA5E048+28*r)==1);CHECK(M32(q1)==0);
    }
    push(q0,0x30,1);Cpu c=cpu(FE);carbon_padguest_events(&c,original);CHECK(M32(0xA5E044)==1);
    for(unsigned p=0;p<2;++p)for(unsigned i=0;i<4;++i){
        float value=i==0?0:i==1?.49f:i==2?.5f:1;
        uint32_t q=p?q1:q0,other=0xA5E044+4*(1-p),before=M32(other);
        push(q,0x30,value);c=cpu(FE);Cpu saved=c;carbon_padguest_events(&c,original);
        CHECK(M32(0xA5E044+4*p)==(i>=2));CHECK(M32(other)==before);
        saved.esp+=4;CHECK(!memcmp(&c,&saved,sizeof c));
    }
    M8(q1+0x28C)=0;push(q1,0x30,0);c=cpu(FE);carbon_padguest_events(&c,original);
    for(unsigned r=0;r<16;++r)CHECK(M32(0xA5E048+28*r)==0);CHECK(M32(0xA5E044)==1);
    M32(q1+0x26C)=0;push(q1,0x89,1);c=cpu(FE);carbon_padguest_events(&c,original);CHECK(M32(q1+0x26C)==1);
    M32(STACK+4)=1;M32(STACK+8)=1;c=cpu(FE);carbon_padguest_disable(&c,original);CHECK(c.esp==STACK+12);CHECK(!M32(q1+0x26C));CHECK(M32(q0+0x26C)==1);
    c=cpu(FE);M32(STACK+4)=4;carbon_padguest_enable(&c,original);CHECK(M32(q0+0x26C)&&M32(q1+0x26C));
    for(unsigned port=0;port<9;++port){c=cpu(FE);M32(STACK+4)=port;carbon_padguest_connected(&c,original);CHECK(c.esp==STACK+8);c=cpu(FE);carbon_padguest_enabled(&c,original);CHECK(c.esp==STACK+8);}
    c=cpu(q0);M32(STACK)=0x5840CA;push(q1,0x30,1);carbon_padguest_queue_flush(&c,native_006891E0);CHECK(M32(q1)==0);for(unsigned r=0;r<16;++r)CHECK(!M32(0xA5E048+28*r));
    c=cpu(q0);M32(STACK)=0xFEEDF00D;push(q1,0x30,1);carbon_padguest_queue_flush(&c,native_006891E0);CHECK(M32(q1)==1);
    c=cpu(FE);carbon_padguest_destroy(&c,native_0056FF80);CHECK(frees==2&&destructs==2);CHECK(!M32(FE));CHECK(!carbon_padguest_queue(FE,1));
    c=cpu(FE);carbon_padguest_destroy(&c,native_0056FF80);CHECK(frees==2);
    reset();io_init();make_fe();c=cpu(FE);M32(STACK+4)=1;carbon_padguest_destroy(&c,native_00572AC0);CHECK(frees==2&&destructs==2);CHECK(c.esp==STACK+8);
}
static void failures_proof(void){
    for(unsigned fail=1;fail<=2;++fail){reset();io_init();fail_alloc=fail;uint32_t q1=make_fe();CHECK(allocs==2);CHECK(!!M32(FE)==(fail!=1));CHECK(!!q1==(fail!=2));CHECK(!memcmp(G,(unsigned char[0x400]){0},0x400));
        Cpu c=cpu(FE);M32(STACK+4)=4;M32(STACK+8)=1;carbon_padguest_enable(&c,original);c=cpu(FE);carbon_padguest_required(&c,original);
        CHECK(!M32(FE+8));CHECK(M32(FE+12)==0x82D21520);c=cpu(FE);carbon_padguest_destroy(&c,native_0056FF80);CHECK(frees==1&&destructs==1);
    }
    reset();factory_fail=1;io_init();CHECK(!make_fe());CHECK(allocs==1);
    for(unsigned port=0;port<2;++port){Cpu c=cpu(0x100000+0x2000*port);if(port)M32(c.ecx+0x24)=1;connected[port]=0;carbon_padguest_device_connected(&c,original);if(port)CHECK(!(c.eax&255));CHECK(c.esp==STACK+4);}
    reset();io_init();uint32_t q1=make_fe();if(!q1)return;M8(q1+0x28C)=0;Cpu c=cpu(FE);carbon_padguest_required(&c,original);CHECK(M8(FE+5)==1);CHECK(M8(q1+0x28D)==1);CHECK(M32(DB+0xC8)==1);CHECK(modal==1);CHECK(M32(FE)==carbon_padguest_queue(FE,0));CHECK(M8(PORTS)==0&&M8(PORTS+1)==1);
    c=cpu(FE);carbon_padguest_required(&c,original);CHECK(!M8(FE+5));CHECK(!M8(q1+0x28D));CHECK(modal==1);
    M8(q1+0x28C)=1;c=cpu(FE);carbon_padguest_required(&c,original);CHECK(!M8(FE+5));
    for(unsigned port=2;port<8;++port){M8(PORTS)=port;M8(PORTS+1)=0xFF;c=cpu(FE);carbon_padguest_required(&c,original);CHECK(M32(FE+12)==0x82D21520);CHECK(M32(IO+4)==4);}
}
void dispatch(Cpu *c,uint32_t a){
    if(a>=0x11111110&&a<=0x11111112){unsigned kind=a-0x11111110,port=arg(c,0);
        if(!kind){++factories;c->eax=port&&factory_fail?0:0x100000+0x2000*port;if(c->eax){memset(G+c->eax,0xA5,0x1860);M32(c->eax)=0x9E2138;M32(0x9E2144)=0x694C50;M32(0x9E2158)=0x22222221;M32(c->eax+0x24)=port;}}
        else{CHECK(port==(pads==2?kind+1:kind));c->eax=kind==1?0x200000:0x210000;M32(c->eax)=0x82000;M32(0x82020)=0x22222221;}
        c->esp+=4;return;
    }
    switch(a){
    case 0x606B60:f_00606B60(c);return;
    case 0x6893D0:{unsigned p=arg(c,0);M32(c->esp+4)=p;dispatch(c,0x11111110);return;}
    case 0x694C50:f_00694C50(c);return;
    case 0x60BA70:CHECK(c->ecx==0xA99720);CHECK(arg(c,0)==0x29C);++allocs;c->eax=allocs==fail_alloc?0:0x600000+0x400*allocs;c->esp+=12;return;
    case 0x696D30:{unsigned q=c->ecx;CHECK(arg(c,1)==0x82D21520);CHECK(arg(c,2)==0x9D0550);M32(q+0x268)=arg(c,0);M8(q+0x28C)=1;M32(q+12)=50;c->eax=q;c->esp+=20;return;}
    case 0x694A50:M32(c->ecx+0x26C)=arg(c,0);c->esp+=8;return;
    case 0x678900:carbon_padguest_queue_connected(c,native_00678900);return;
    case 0x678960:carbon_padguest_queue_enabled(c,native_00678960);return;
    case 0x680310:native_00680310(c);return;
    case 0x680320:native_00680320(c);return;
    case 0x680350:native_00680350(c);return;
    case 0x6891E0:carbon_padguest_queue_flush(c,native_006891E0);return;
    case 0x6959A0:f_006959A0(c);return;
    case 0x609E80:f_00609E80(c);return;
    case 0x87EAC0:native_0087EAC0(c);return;
    case 0x22222221:c->esp+=4;return;
    case 0x22222220:c->eax=1;c->esp+=4;return;
    case 0x4A0490:M32(arg(c,1))=0;c->esp+=4;return;
    case 0x75CF70:c->eax=0;c->esp+=4;return;
    case 0x680510:c->eax=IO;c->esp+=4;return;
    case 0x5913C0:++modal;CHECK(c->ecx==M32(0xA97A78));CHECK(arg(c,0)==0x9D00FC);c->esp+=16;return;
    default:fprintf(stderr,"unexpected dispatch %08X self=%08X caller=%08X\n",a,c->ecx,M32(c->esp));abort();
    }
}
uint32_t call_guest(Cpu *c,uint32_t a,int n,const uint32_t *args){unsigned sp=c->esp;for(int i=n-1;i>=0;--i){c->esp-=4;M32(c->esp)=args[i];}c->esp-=4;M32(c->esp)=0xFEEDF00D;dispatch(c,a);c->esp=sp;return c->eax;}
int main(void){G=calloc(1,0xC00000);if(!G)return 2;device_proof();event_proof();failures_proof();printf("private_padguest checks=%u failures=%u\n",checks,failures);free(G);return failures?1:0;}
'''


def main():
    sys.path.insert(0, str(HERE))
    import private_padbind_test as pb
    import recomp
    import private_hooks
    base = HERE / 'out/carbon-base'
    if not (base / 'image.json').is_file():
        print('SKIP: Carbon translated output unavailable')
        return 3
    image = json.loads((base / 'image.json').read_text())
    if not Path(image['exe']).is_file():
        print('SKIP: Carbon image unavailable')
        return 3
    pe = recomp.PE(image['exe'], expected_sha256=image['sha256'])
    assert struct.unpack('<f',pe.read(0x9C2888,4))[0]==.5
    starts = [int(v.removesuffix('u'), 16) for v in re.search(r'guest_func_addr\[\] = \{([^}]+)', (base/'table.c').read_text())[1].split(',')]
    hooks = private_hooks.load_registry(pe, [(a, starts[i+1] if i+1<len(starts) else a+16, 'fixture') for i,a in enumerate(starts)])
    owned = json.loads((PRIVATE/'hooks/padguest.json').read_text())['hooks']
    assert all(hooks[int(r['address'],16)]['provider']==r['provider'] for r in owned)
    native = []
    for a in NATIVE:
        source = (base / f'NFSC_{starts.index(a)//800:02d}.c').read_text()
        name = private_hooks.original_name(a)
        if f'void {name}(' not in source:
            name = f'f_{a:08X}'
        native.append(pb.body(source, name).replace(name, f'native_{a:08X}', 1))
    implementation = (PRIVATE/'carbon_padguest.c').read_text()
    # Independently audit every static Carbon guest root, not only overlaps.
    ast = pb.command(['clang','-std=c11','-I',PRIVATE,'-I',ROOT/'runtime','-I',HERE,
                      '-fsyntax-only','-Xclang','-ast-dump=json',PRIVATE/'carbon_padguest.c'])
    sys.path.insert(0,str(PRIVATE))
    from quarantine import audit_tree
    accesses={(r['name'],kind,address) for r in audit_tree(json.loads(ast.stdout),[(0x400000,0xC00000)])
              if r['name'].startswith('carbon_padguest_') for kind,address in r['accesses']}

    manifest = json.loads((PRIVATE/'features/padguest.json').read_text())
    declared={(name,kind,address) for name,row in manifest['sources']['carbon_padguest.c']['guest_accesses'].items() for kind,addresses in row.items() for address in addresses}
    assert accesses==declared,sorted(accesses^declared)
    print(f'guest access roots: {len(accesses)}/{len(declared)}; hooks: {len(owned)}')
    for name,row in manifest['bindings'].items():
        assert row['sha256']==hashlib.sha256((PRIVATE/name).read_bytes()).hexdigest()
    with tempfile.TemporaryDirectory(prefix='private-padguest-') as td:
        tmp = Path(td)
        (tmp/'native.inc').write_text('\n\n'.join(native)+'\n')
        (tmp/'fixture.c').write_text(HARNESS)
        def execute(name, source, expected):
            (tmp/'carbon_padguest.c').write_text(source)
            binary = tmp/name
            pb.command(['clang','-std=c11','-O0','-g','-fsanitize=address,undefined','-fno-sanitize-recover=all','-I',tmp,'-I',PRIVATE,'-I',ROOT/'runtime','-I',HERE,'-I',base,tmp/'fixture.c','-o',binary])
            result = pb.command([binary],expected)
            summary = re.search(r'checks=(\d+) failures=(\d+)', result.stdout)
            assert summary and (int(summary[2])>0)==bool(expected), result.stdout
            print(f'{name}: {summary[2]}/{summary[1]} failures')
        execute('good',implementation,0)
        mutants = {
            'missing-x87-value': ('x87_push(&q, event ? (double)MF32(event + 8) : 0.0);', '/* action magnitude omitted */'),
            'null-dialog-owner': ('carbon_padguest_call(c, 0x005913C0u, wrapper, 3, args);', 'carbon_padguest_call(c, 0x005913C0u, 0, 3, args);'),
            'original-one-device': ('caller != 0x006892F0u', '1 || caller != 0x006892F0u'),
            'null-queue-construction': ('if (!q) continue;\n        uint32_t args[] = {p, M32(fe + 12)', '/* allocation guard removed */\n        uint32_t args[] = {p, M32(fe + 12)'),
            'original-one-queue': ('if (p && !M32(0x00A991E4u)) continue;', 'if (p) continue;'),
            'wrong-fe-column': ('map + 12 + 4*p', 'map + 12'),
            'lost-identity': ('if (pad_count() != 2 || M32(device + 0x24) != 1)', 'if (1 || pad_count() != 2 || M32(device + 0x24) != 1)'),
            'connection-fallback': ('c->eax = (c->eax & ~0xFFu) | !!state.connected;', 'c->eax = (c->eax & ~0xFFu) | 1;'),
            'leaked-queue': ('if (pad_count() == 2 && c->ecx == carbon_padguest_fe) carbon_padguest_dispose(c);', '/* guest queue disposal disabled */'),
            'repeated-unplug': ('if (M32(db + 0xC8) != 0xFFFFFFFFu)', 'if (0 && M32(db + 0xC8) != 0xFFFFFFFFu)'),
            'root-pointer-overwrite': ('if (p) carbon_padguest_second = q; else M32(fe) = q;', 'if (p) {carbon_padguest_second = q;M32(fe+4)=q;} else M32(fe) = q;'),
        }
        for name,(old,new) in mutants.items():
            assert old in implementation,name
            execute(name,implementation.replace(old,new,1),1)
    return 0


if __name__ == '__main__':
    sys.exit(main())
