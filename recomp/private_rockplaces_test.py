"""Fixed lot scope: good 3/3 imported, 0/22 territories, 0/4 native lots,
0 area-less safehouses; all-true scope control exits 1 (good exits 0).
Production hooks compiled in a guest-call fixture: native pass first, SetOwner
only for three lots, map append 3/3, missing objects 0/3, switch 0 additions=0.
Save fixture: retained native codec, 32 owner bytes versus broken 96 (+64);
legacy -> overlay -> save -> reload and overlay-off compare every fixture byte.
Both switch values: 0/1,440 world-byte differences, 0 cursor displacement;
switch-gated protection control: +64 displacement, acceptance exits 1 (good 0).
Initialization rebuilds 23 premises inside the loader.
Converted pack: tracks/zones/areas 73/22/4 and 23 premises, 8 at or below
BFC67884, counted from the converter output (the positional save sections);
with one imported record re-parented under territory_zone the count reads
23 zones and the check fails (good 22, broken 23). No real profiles or I/O.
Does not prove live ownership, menus or rendering.
Icon exhaustion: native 0/3 lot gates; recovery 15/15 places, 3/3 lots,
allocated=256, 15 disposable evictions. Native 0061DEA0 with all icons visible:
new code 256 visible / 0 table overflow writes; pinned 75bee61d recovery fragment
259 visible / 1 first overflowing write (entry 257), exit 42 versus good 0.
No-candidate, partial-capacity, allocator-null, deferred-trigger, inactive-partition
and repeat-refresh fixtures preserve the native cap and retained pointers.
Recovery-disabled and wrong-caller controls fail; diagnostics-off helpers abort
if called. Native construction, removal partitions and menu gates execute.
Near three lots diagnostics emit 6/6 active lines, 0 within-second repeats,
0 far-away lines. Object pool teardown is stubbed; table removal is native.
Private gameplay inputs absent: exit 3. Automatically run by offline_tests.sh.
Feature dependencies: rockplaces.json (feature and hook).
"""
from pathlib import Path
import json
import hashlib
import os
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = ROOT / 'recomp/private_runtime'
sys.path.insert(0, str(ROOT / 'tools_snapshot/worldmerge'))
import gameplay as g


def derived_keys():
    """Read original packs, never converter additions or the hook's key table."""
    target = g.DEFAULT_CARBON.parent / 'GLOBAL/gameplay.bin'
    source = g.DEFAULT_MW.parent / 'GLOBAL/gameplay.bin'
    if not target.is_file() or not source.is_file():
        return None
    native = g.Pack(target.read_bytes()).core(True)
    imported = g.Pack(source.read_bytes()).core(False)

    def template(vault, name):
        return next(c.key for c in vault.collections.values() if c.name == name + b'\0')

    def inherits(vault, c, parent):
        while c.parent:
            if c.parent == parent:
                return True
            c = vault.collections[c.parent]
        return False

    def field(vault, c, key):
        while True:
            for k, _, _, raw in c.fields:
                if k == key:
                    assert raw is not None and len(raw) == 4
                    return int.from_bytes(raw, 'little')
            if not c.parent:
                return 0
            c = vault.collections[c.parent]

    territory = template(native, b'territory_zone')
    carlot = template(native, b'premises_carlot')
    safehouse = template(native, b'premises_safehouse')
    zones = [c.key for c in native.collections.values() if inherits(native, c, territory)]
    lots = [field(native, c, 0xD5DFD829) for c in native.collections.values()
            if inherits(native, c, carlot) and field(native, c, 0x70D72E20)]
    houses = [field(native, c, 0xD5DFD829) for c in native.collections.values()
              if inherits(native, c, safehouse) and not field(native, c, 0x70D72E20)
              and field(native, c, 0xD5DFD829)]
    positives = []
    for parent, c in imported.triggers():
        name = imported.collections[parent].name
        if name == b'zone_carlot\0':
            positives.append(c.key)
        elif name in (b'zone_safehouse\0', b'zone_customshop\0'):
            houses.append(c.key)
    assert len(zones) == 22 and len(lots) == 4 and len(houses) == 13
    assert set(positives) == {0xDAF7164E, 0x2F8CA402, 0xE925D054}
    return positives, zones, lots, houses


def converted_counts(zone_parent=False):
    """Positional save sections counted in the converter output, not the harness."""
    source = g.DEFAULT_MW.parent / 'GLOBAL/GAMEPLAY.BIN'
    target = g.DEFAULT_CARBON.parent / 'GLOBAL/gameplay.bin'
    original = g.place_premises
    if zone_parent:
        def broken(records, dst):
            rows = original(records, dst)
            rows[0][1].parent = 0x885D0650
            return rows
        g.place_premises = broken
    try:
        result, _ = g.convert(source.read_bytes(), target.read_bytes())
    finally:
        g.place_premises = original
    vault = g.Pack(result).core(True)

    def below(c, template):
        while c.parent:
            if c.parent == template:
                return True
            c = vault.collections.get(c.parent)
            if c is None:
                return False
        return False
    count = lambda key: sum(below(c, key) for c in vault.collections.values())
    premises = [c for c in vault.collections.values() if c.parent in (0x874B96D6, 0xB7F31748)]
    assert all(below(c, 0xF21D1E85) for c in premises)
    return (count(0x8F5815D6), count(0x885D0650), count(0xDA2CF0F5), len(premises),
            sum(c.key <= 0xBFC67884 for c in premises))


HARNESS = r'''
#include <assert.h>
#include <stdlib.h>
#include "host.h"
uint8_t *G;
int diag_on;
uint32_t gmalloc(uint32_t n) { (void)n; abort(); }
void gfree(uint32_t p) { (void)p; abort(); }
uint64_t host_ticks(void) { abort(); }
int private_carbon_player_position(float *p) { (void)p; abort(); }
void diag_event(const char *fmt, ...) { (void)fmt; abort(); }
#include "carbon_rockplaces.h"
#define CHECK(x) do { if (!(x)) { fprintf(stderr,"ROCKPLACES CHECK %d: %s\n",__LINE__,#x); exit(1); } } while (0)
/* FIXTURE KEYS */
enum { MANAGER=0x11000, MAP=0x12000, HOLDER=0x19000, PACKAGE=0x18000, PLAYER=0x7777 };
static int original_calls, sets, projections, constructors, calls, mode, enabled;
static unsigned heap=0x30000;
static uint32_t prem(unsigned i) { return 0x16000 + i*64; }
static uint32_t node(unsigned i) { return 0x14000 + i*32; }
static void native(Cpu *c) {
    ++original_calls;
    c->eax=0x12345678; c->ecx=0xDEADBEEF; c->edx=0x87654321; c->esp+=4;
}
uint32_t call_guest(Cpu *c, uint32_t fn, int n, const uint32_t *a) {
    CHECK(original_calls && enabled); ++calls;
    switch(fn) {
    case 0x00463A80: CHECK(n==2 && a[0]==0xD5DFD829 && a[1]==0); return c->ecx+0x2C;
    case 0x00617850:
        CHECK(n==1 && a[0]==PLAYER && carbon_rockplaces_scope(M32(c->ecx+0x30)));
        M32(c->ecx+0x18)=M32(c->ecx+0x14); M32(c->ecx+0x14)=*a;
        M8(c->ecx+0x1C)|=1; ++sets; return 0;
    case 0x005858D0: CHECK(c->ecx==0x2222 && n==1 && a[0]==0x13000); return mode==3 ? 0 : HOLDER;
    case 0x00472980: {
        CHECK(n==1); unsigned i=(*a-0x14000)/32;
        return i+1<sizeof(keys)/sizeof(*keys) ? node(i+1) : MANAGER+0x70;
    }
    case 0x005711C0: CHECK(n==2 && a[0]==0x9D4608 && a[1]>=5 && a[1]<=7); return a[1];
    case 0x005F3760: CHECK(c->ecx==PACKAGE && n==1 && *a>=5 && *a<=7); return mode==1 ? 0 : 0x20000+64*(*a);
    case 0x0056E770:
        CHECK(n==4 && a[1]==a[0]+4 && a[2]==MAP+0x44 && a[3]==MAP+0x4C);
        CHECK(MF32(a[0])>=100 && MF32(a[0])<103 && MF32(a[1])>=200 && MF32(a[1])<203);
        MF32(a[0])+=1000; MF32(a[1])+=2000; ++projections; return 0;
    case 0x006A1560: CHECK(n==1 && *a==0x30); heap+=0x40; return mode==4 ? 0 : heap;
    case 0x0059DD90:
        CHECK(n==6 && a[0]==0x02000000 && a[1]>=0x20000 && a[3]==0 && a[5]==0);
        CHECK(carbon_rockplaces_scope(a[4]) && MF32(a[2])>=1100 && MF32(a[2]+4)>=2200);
        CHECK(a[1]==0x20000+64*(a[4]==0xDAF7164E ? 5 : a[4]==0x2F8CA402 ? 6 : 7));
        M32(c->ecx+0x28)=a[4]; ++constructors; return c->ecx;
    default: CHECK(0); return 0;
    }
}
int main(int argc, char **argv) {
    enabled=strcmp(argv[1],"0")!=0; mode=atoi(argv[2]);
    G=calloc(1,0xB00000); CHECK(G);
    M32(0xA982B8)=MANAGER; M32(0xA97B40)=0x2222; M32(MANAGER+0xDC)=PLAYER;
    M32(MANAGER+0x74)=node(0); M32(MAP+0x0C)=0x13000; M8(0x13000)='x'; M32(HOLDER+0x20)=PACKAGE;
    /* Preserve one existing native map item. */
    M32(MAP+0x64)=0x29004; M32(MAP+0x68)=0x29004;
    M32(0x29004)=MAP+0x64; M32(0x29008)=MAP+0x64;
    for(unsigned j=5;j<=7;++j) M32(0x20000+64*j+0x18)=1;
    for(unsigned i=0;i<sizeof(keys)/sizeof(*keys);++i) {
        CHECK(carbon_rockplaces_scope(keys[i])==(i<3));
        M32(node(i)+0x14)=prem(i); M32(prem(i)+0x20)=1;
        M32(prem(i)+0x14)=0x9999; M32(prem(i)+0x30)=keys[i];
        MF32(prem(i)+0x2C)=100+i; MF32(prem(i)+0x24)=-200-(float)i;
        Cpu c={0}; c.ecx=prem(i); c.esp=0x90000;
        carbon_rockplaces_owner(&c,native);
        CHECK(c.eax==0x12345678 && c.ecx==0xDEADBEEF && c.edx==0x87654321 && c.esp==0x90004);
        CHECK(M32(prem(i)+0x14)==(enabled && i<3 ? PLAYER : 0x9999));
    }
    CHECK(sets==(enabled ? 3 : 0));
    CHECK(carbon_rockplaces_pending==(enabled ? 0x7FFFu : 0u));
    /* Even a matching key must stay untouched on safehouse and zone types. */
    for(unsigned type=2;type<=3;++type) {
        M32(prem(0)+0x20)=type; M32(prem(0)+0x14)=0x9999;
        Cpu c={0}; c.ecx=prem(0); c.esp=0x90000; carbon_rockplaces_owner(&c,native);
        CHECK(M32(prem(0)+0x14)==0x9999);
    }
    M32(prem(0)+0x20)=1; M32(prem(0)+0x14)=enabled ? PLAYER : 0x9999;
    if(mode==2) M32(prem(0)+0x14)=0x9999;
    Cpu c={0}; c.ecx=MAP; c.esp=0x90000; carbon_rockplaces_map(&c,native);
    CHECK(c.eax==0x12345678 && c.ecx==0xDEADBEEF && c.edx==0x87654321 && c.esp==0x90004);
    unsigned expected=!enabled || mode==1 || mode==3 || mode==4 ? 0 : mode==2 ? 2 : 3;
    CHECK(constructors==expected);
    CHECK(projections==(!enabled || mode==1 || mode==3 ? 0 : mode==2 ? 2 : 3));
    unsigned count=0; uint32_t prev=MAP+0x64;
    for(uint32_t p=M32(MAP+0x64);p!=MAP+0x64;p=M32(p)) {
        CHECK(count<4 && M32(p+4)==prev); prev=p; ++count;
    }
    CHECK(count==expected+1 && M32(MAP+0x68)==prev);
    if(!enabled) CHECK(calls==0);
    printf("scope=3/%zu owners=%d map=%d mode=%d switch=%s\n",sizeof(keys)/sizeof(*keys),sets,constructors,mode,argv[1]);
    free(G); return 0;
}
'''


# Retained translated function fragments, normalized definition names only.
# The loader has alternate entry points in its translated control flow.
SAVE_BODIES = {
    0x00472980: (5, '90bac47a39c86350429f5f5b3c3cac6a2c53f6f6cf63a3feb9d7537bf0f14964'),
    0x00617850: (25, '50342a88e76bef004c737cc3989dd25fc488b6b70c9f1a7ca55f70a64acfff9a'),
    0x00632490: (26, '9f8d12c0be4051ff01282517d36379afac63fc0873018018ac97c6e4a08ae0aa'),
    0x006486B0: (27, 'cd7c0c2b975dd64ac69310a964f7105f99bd70a5bb632304754799465055f2e9'),
    0x00648952: (27, '069420d76ef77fb8cbe369fd80666dc32558de07db68c1ec17ebc0c2131f7a37'),
    0x00648C5C: (27, '6638489fb24826a0ac8758ffbc3bcda83a01f833546a6caad78031ba6851fc1d'),
    0x00648CA0: (27, 'bc02382bd2dc2df7837c3286b9b744377fe039c3d4ac05e8c72891e293df96bb'),
    0x0062E980: (26, '0e33b10b45928f158cba077c06fbafde6d2803527a2352b17dbbeacf26e7e184'),
    0x0062E320: (26, '8edb003a447010375dafe8cdfc19ef946374137985813996eafb5a7fa4bce2bd'),
    0x0062F460: (26, 'fcb2eff3d4f3609bae47186876afeeb14f35ca1cf2fc56039401aee9af827527'),
    0x00649220: (27, '9a4af7b2c7fcf829f0311563389e630f6b46b32179660fb44c6b5784a708c657'),
    0x0061E080: (26, '44a4d60705f647c3b89054808d303721ff54f320813599fddbb3401a5a0e3780'),
    0x00636A50: (27, 'cc0b3029caf79c0aa02c5aed47493c092d31fca8b487f4e60a85a9253be1bb02'),
    0x006266B0: (26, '344e8074066a81f85c070c543a32053b534eede9903e6d42fe22f5bb9d02b085'),
}


SAVE_HARNESS = r'''
#include "funcs.h"
#include "host.h"
#include <stdlib.h>
uint8_t *G;
int diag_on;
uint32_t gmalloc(uint32_t n) { (void)n; abort(); }
void gfree(uint32_t p) { (void)p; abort(); }
uint64_t host_ticks(void) { abort(); }
int private_carbon_player_position(float *p) { (void)p; abort(); }
void diag_event(const char *fmt, ...) { (void)fmt; abort(); }
#include "carbon_rockplaces.h"
#define CHECK(x) do { if (!(x)) { fprintf(stderr,"ROCKSAVE CHECK %d: %s\n",__LINE__,#x); exit(1); } } while (0)
/* SAVE KEYS */
enum { M=0x20000, FE=0x21000, VT=0x22000, ACT=0xA1000, STACK=0x200000,
       DATA=0x100000, CURSOR=0x180000, RESULT=0x180010, SCRATCH=0x190000 };
static int overlay, init_calls, owner_sets, vm_reads;
static uint32_t nodes=0x30000, world_at, load_end, format_calls, active_cursor;
static uint32_t crew(unsigned i) { return 0x70000+i*0x100; }
static uint32_t track(unsigned i) { return 0x40000+i*0x80; }
static uint32_t zone(unsigned i) { return 0x50000+i*0x80; }
static uint32_t area(unsigned i) { return 0x60000+i*0x80; }
static uint32_t premises(unsigned i) { return 0x80000+i*0x80; }
static uint32_t member(unsigned i) { return 0x78000+i*0x80; }
static uint32_t align16(uint32_t n) { return (n+15)&~15u; }
static void empty(uint32_t s) {
    M32(s)=s; M32(s+4)=s; M32(s+8)=0; M32(s+16)=0;
}
/* Native tree: right +0, left +4, parent +8, key +10, value +14.
 * Header sentinel carries last/first/root, followed by its count. */
static uint32_t insert(uint32_t s,uint32_t key,uint32_t value) {
    uint32_t parent=s, p=M32(s+8), link=s+8;
    while(p) {
        if(M32(p+16)==key) return p;
        parent=p; link=p+(key<M32(p+16)?4:0); p=M32(link);
    }
    p=nodes; nodes+=32; memset(G+p,0,32);
    M32(p+8)=parent; M32(p+16)=key; M32(p+20)=value; M32(link)=p;
    if(M32(s+4)==s || key<M32(M32(s+4)+16)) M32(s+4)=p;
    if(M32(s)==s || key>M32(M32(s)+16)) M32(s)=p;
    ++M32(s+16); return p;
}
static uint32_t find(uint32_t s,uint32_t key) {
    uint32_t p=M32(s+8);
    while(p && M32(p+16)!=key) p=M32(p+(key<M32(p+16)?4:0));
    return p?p:s;
}
static Cpu cpu(uint32_t self) {
    Cpu c={0}; c.esp=STACK; c.ecx=self; c.fs_base=0x1000; c.cw=0x37F;
    c.ebx=0x11223344;c.esi=0x55667788;c.edi=0x8899AABB;c.ebp=0xCCDDEEFF;
    return c;
}
static uint32_t invoke(Cpu *c,void (*fn)(Cpu *),unsigned n,const uint32_t *a) {
    uint32_t esp=c->esp;
    for(unsigned i=n;i;--i) {c->esp-=4;M32(c->esp)=a[i-1];}
    c->esp-=4;M32(c->esp)=0xFEED;fn(c);
    c->esp=esp;return c->eax;
}
static void init_world(int populated) {
    ++init_calls; nodes=0x30000;
    memset(G+M,0,0x200); memset(G+0x40000,0,0x50000);
    M32(0xA982B8)=M;M32(0xA98294)=FE;M32(M+0xDC)=crew(0);
    M32(VT+4)=0x617850;M32(VT+12)=0x62E980;
    M32(VT+32+12)=0xFF000001;M32(VT+64+4)=0xFF000002;
    for(unsigned s=0;s<7;++s) {
        const unsigned offsets[]={0x54,0x38,0x1C,0x70,0xA8,0x8C,0xC4};
        empty(M+offsets[s]);
    }
    for(unsigned i=0;i<4;++i) {
        uint32_t p=crew(i);M32(p)=VT+32;M32(p+4)=0x10203040+i;
        empty(p+0x78);insert(M+0xA8,M32(p+4),p);
    }
    M32(0xA982D4)=M32(crew(1)+4);M32(0xA9832C)=0;
    for(unsigned i=0;i<73;++i) {
        uint32_t p=track(i);M32(p)=VT+32;
        insert(M+0x54,0x200000+i,p);
        if(populated) {M32(p+0x14)=crew(i%4);M32(p+0x18)=crew((i+1)%4);M8(p+0x1C)=2*(i%64);}
    }
    for(unsigned i=0;i<22;++i) {
        uint32_t p=zone(i);M32(p)=VT+32;insert(M+0x38,0x300000+i,p);
        if(populated) {M32(p+0x14)=crew(1+i%3);M32(p+0x18)=crew((i+2)%4);
            M8(p+0x1C)=2*i;M32(p+0x60)=0x73620000+i;}
    }
    for(unsigned i=0;i<4;++i) {
        uint32_t p=area(i);M32(p)=VT+32;insert(M+0x1C,0x400000+i,p);
        if(populated) {M32(p+0x14)=crew(i);M32(p+0x18)=crew((i+1)%4);
            M8(p+0x1C)=2*i;M32(p+0x40)=0xABCD0000+i;M32(p+0x44)=0xDEAD0000+i;}
    }
    unsigned count=overlay?23:8;
    for(unsigned i=0;i<count;++i) {
        uint32_t p=premises(i);M32(p)=VT;M32(p+4)=place_keys[i];
        M32(p+0x20)=place_types[i];M32(p+0x34)=trigger_keys[i];
        /* Native places retain an independent territory owner. */
        if(i<8) {M32(p+0x38)=p+0x40;M32(p+0x40+0x14)=crew(1+i%3);M32(p+0x40+0x20)=p+0x40;}
        insert(M+0x70,place_keys[i],p);
    }
    for(unsigned i=0;i<5;++i) {
        uint32_t p=member(i);M32(p)=VT+64;M32(p+4)=0xABC100+i;
        insert(M+0x8C,M32(p+4),p);
    }
    Cpu c=cpu(M);c.esp-=0x4000;invoke(&c,f_0062E320,0,NULL);
    c=cpu(M);c.esp-=0x4000;invoke(&c,f_0062F460,0,NULL);
    if(populated) {
        for(unsigned i=0;i<5;++i) {
            uint32_t p=member(i),s=i<2?crew(0)+0x78:i==2?M+0xC4:crew(1)+0x78;
            insert(s,M32(p+4),p);M32(p+0x14)=i==2?0:i<2?crew(0):crew(1);
        }
        M32(M+0xE0)=7;M32(M+0xE4)=9;M32(M+0xF4)=3;
        M32(M+0x100)=0xDEADBEEF;M32(M+0xF8)=0xCAFE1234;
        M32(M+0xEC)=member(0);M32(M+0x114)=0xFEDCBA98;
    }
}
void bad_jump(Cpu *c,uint32_t at) {(void)c;fprintf(stderr,"unexpected guest %x\n",at);exit(1);}
void untranslated(Cpu *c,uint32_t at) {bad_jump(c,at);}
void host_import(Cpu *c,uint32_t at) {bad_jump(c,at);}
void abi_violation(Cpu *c,uint32_t fn,uint32_t b,uint32_t s,uint32_t d,uint32_t p,uint32_t sp) {
    fprintf(stderr,"ABI %x ebx=%x/%x esi=%x/%x edi=%x/%x ebp=%x/%x esp=%x/%x\n",
            fn,c->ebx,b,c->esi,s,c->edi,d,c->ebp,p,c->esp,sp);exit(1);
}
/* Resource and allocation boundaries only; all save cursor arithmetic,
 * tree iteration, SetOwner, refresh and normalization execute native bodies. */
void f_004613E0(Cpu *c) {c->eax=M32(c->ecx);c->esp+=4;}
void f_004B82B0(Cpu *c) {
    uint32_t out=arg(c,0);M32(out)=find(c->ecx+4,M32(arg(c,1)));
    c->eax=out;c->esp+=12;
}
void f_006351F0(Cpu *c) {
    c->eax=insert(c->ecx+4,M32(arg(c,0)),0)+20;c->esp+=8;
}
void f_00475350(Cpu *c) {bad_jump(c,0x475350);}
void f_00609E80(Cpu *c) {bad_jump(c,0x609E80);}
void f_0087EAC0(Cpu *c) {bad_jump(c,0x87EAC0);}
void f_0062E900(Cpu *c) {c->eax=M32(c->ecx+0x38);c->esp+=4;}
void f_004AAE60(Cpu *c) {c->eax=0;c->esp+=8;}
void f_0062E3C0(Cpu *c) {load_end=M32(active_cursor);c->esp+=4;}
void f_00646520(Cpu *c) {
    uint32_t ret=M32(c->esp);CHECK(ret==0x6486C0);
    active_cursor=M32(c->esp+44);
    init_world(0);CHECK(M32(M+0x80)==(overlay?23:8));c->esp+=4;
}
void f_004AC040(Cpu *c) {
    uint32_t key=arg(c,0);int found=key==fallback_key;
    for(unsigned i=0;i<15;++i) if(spawn_keys[i]==key) found=overlay;
    memset(G+c->ecx,0,16);M32(c->ecx)=found?0x90000:0;
    c->eax=c->ecx;c->esp+=12;
}
void f_00469870(Cpu *c) {c->esp+=4;}
void f_00475C10(Cpu *c) {
    CHECK(arg(c,1)==0x9D871C && !strcmp(gptr(arg(c,2)),"l2ra"));
    strcpy((char*)G+arg(c,0),"career_start_l2ra");
    ++format_calls;c->eax=20;c->esp+=4;
}
void f_00463C10(Cpu *c) {CHECK(!strcmp(gptr(arg(c,0)),"career_start_l2ra"));c->eax=fallback_key;c->esp+=4;}
void f_006AACC0(Cpu *c) {c->esp+=12;}
void f_006AAD40(Cpu *c) {c->eax=SCRATCH;c->esp+=4;}
void f_00636930(Cpu *c) {
    CHECK(vm_reads<2 && arg(c,0)==activity_keys[vm_reads] && arg(c,1)==32 && arg(c,2)==1);
    uint32_t p=0xA0000+64*vm_reads,previous=nodes;nodes=0xB0000+32*vm_reads;
    memset(G+p,0,64);M32(p)=arg(c,0);M32(p+4)=arg(c,1);
    insert(ACT+0x58,M32(p),p);nodes=previous;++vm_reads;c->eax=p+8;c->esp+=16;
}
void f_0061D320(Cpu *c) {CHECK(!arg(c,1));c->esp+=12;}
void f_006370C0(Cpu *c) {CHECK(!arg(c,1));c->esp+=12;}
void f_00614A50(Cpu *c) {CHECK(!arg(c,1));c->esp+=12;}
void f_00614B30(Cpu *c) {CHECK(!arg(c,1));c->esp+=12;}
void f_00625E90(Cpu *c) {c->eax=0;c->esp+=8;}
void f_0062DCE0(Cpu *c) {CHECK(!arg(c,1));c->esp+=12;}

#include "save_native.inc"

void dispatch(Cpu *c,uint32_t fn) {
    switch(fn) {
    case 0x617850: ++owner_sets;f_00617850(c);break;
    case 0x62E980: f_0062E980(c);break;
    case 0xFF000001: c->esp+=4;break;
    case 0xFF000002: M32(c->ecx+0x14)=arg(c,0);c->esp+=8;break;
    case 0xFF000003: c->esp+=4;break;
    default:bad_jump(c,fn);
    }
}
uint32_t call_guest(Cpu *c,uint32_t fn,int n,const uint32_t *a) {
    if(fn==0x463A80) {CHECK(n==2 && a[0]==0xD5DFD829);return c->ecx+0x30;}
    if(fn==0x617850) return invoke(c,f_00617850,n,a);
    if(fn==0x472980) return invoke(c,f_00472980,n,a);
    bad_jump(c,fn);return 0;
}
static uint32_t save(uint32_t at) {
    M32(CURSOR)=at;uint32_t a[]={CURSOR,0,0,RESULT};Cpu c=cpu(M);
    invoke(&c,f_00632490,4,a);CHECK((c.eax&255)==1);
    CHECK(M32(CURSOR)==at+M32(RESULT));return M32(RESULT);
}
static void load(uint32_t at) {
    M32(CURSOR)=at;uint32_t a[]={CURSOR,0xC00};Cpu c=cpu(M);
    invoke(&c,f_006486B0,2,a);CHECK((c.eax&255)==1);load_end=M32(CURSOR);
}
static unsigned differences(const uint8_t *a,const uint8_t *b,unsigned n) {
    unsigned d=0;for(unsigned i=0;i<n;++i)d+=a[i]!=b[i];return d;
}
/* Logical state comparison includes every decoded field of 73 tracks,
 * 22 zones, 4 areas, eight native premises and both membership lists. */
static unsigned state(uint8_t *out) {
    unsigned n=0;
    const unsigned fields[]={0xE0,0xE4,0xF4,0x100,0xF8,0xEC,0x114};
    for(unsigned i=0;i<7;++i) {memcpy(out+n,G+M+fields[i],4);n+=4;}
    for(unsigned group=0;group<4;++group) {
        unsigned count=group==0?73:group==1?22:group==2?4:8;
        for(unsigned i=0;i<count;++i) {
            uint32_t p=group==0?track(i):group==1?zone(i):group==2?area(i):premises(i);
            memcpy(out+n,G+p+0x14,9);n+=9;
            if(group==1) {memcpy(out+n,G+p+0x60,4);n+=4;}
            if(group==2) {memcpy(out+n,G+p+0x40,8);n+=8;}
        }
    }
    const uint32_t lists[]={crew(0)+0x78,M+0xC4,crew(1)+0x78};
    for(unsigned i=0;i<3;++i) {
        uint32_t s=lists[i],p=M32(s+4);memcpy(out+n,G+s+16,4);n+=4;
        while(p!=s) {memcpy(out+n,G+p+16,4);n+=4;Cpu c=cpu(0);p=invoke(&c,f_00472980,1,&p);}
    }
    for(unsigned i=0;i<5;++i) {memcpy(out+n,G+member(i)+0x14,4);n+=4;}
    return n;
}
static void fixed_places(void) {
    for(unsigned i=8;i<23;++i) {
        CHECK(M32(premises(i)+0x14)==crew(0));
        CHECK(M32(premises(i)+0x18)==crew(0));CHECK(!(M8(premises(i)+0x1C)&1));
    }
}
static void iterator_scope(void) {
    uint32_t p=find(M+0x70,place_keys[7]);Cpu a=cpu(0),b=a;
    uint32_t args[]={p};a.esp-=8;M32(a.esp)=0xDEADBEEF;M32(a.esp+4)=p;b=a;
    /* unrelated callers retain the complete CPU state of the original */
    unfiltered_successor(&a);f_00472980(&b);CHECK(!memcmp(&a,&b,sizeof a));
    uint32_t first=place_keys[8];for(unsigned i=9;i<23;++i)if(place_keys[i]<first)first=place_keys[i];
    CHECK(M32(b.eax+16)==first);
    (void)args;
}
int main(int argc,char **argv) {
    CHECK(argc==2);G=calloc(1,0xC00000);CHECK(G);setenv("NFS_CARBON_ROCKPLACES",argv[1],1);
    int enabled=strcmp(argv[1],"0")!=0;
    printf("save fixture switch=%s\n",argv[1]);
    uint8_t legacy[4096],expected[4096],actual[4096],written[4096];
    overlay=1;init_world(0);if(enabled)fixed_places();
    overlay=0;init_world(1);memset(G+DATA,0xA5,4096);
    unsigned size=save(DATA);CHECK(size==0x5A0);memcpy(legacy,G+DATA,size);
    CHECK(M8(DATA)==0xBC);CHECK(M32(DATA+0x540)==M32(crew(1)+4));
    load(DATA);unsigned n=state(expected);CHECK(load_end==DATA+size);
    overlay=1;load(DATA);unsigned m=state(actual);
    unsigned displacement=load_end-(DATA+size);
    printf("legacy-load owner section=32 cursor displacement=%u state differences=%u/%u\n",
           displacement,differences(expected,actual,n),n);fflush(stdout);
    CHECK(displacement==0);CHECK(n==m && !memcmp(expected,actual,n));
    if(enabled)fixed_places();iterator_scope();
    memset(G+DATA,0xA5,4096);unsigned on_size=save(DATA);
    printf("overlay-save owner section=%u displacement=%u world differences=%u/%u bytes\n",
           32+on_size-size,on_size-size,differences(legacy,G+DATA,size),size);fflush(stdout);
    CHECK(on_size==size);CHECK(!memcmp(legacy,G+DATA,size));memcpy(written,G+DATA,size);
    for(unsigned repeat=0;repeat<3;++repeat) {
        load(DATA);CHECK(load_end==DATA+size);
        CHECK(state(actual)==n && !memcmp(expected,actual,n));if(enabled)fixed_places();
    }
    printf("overlay reloads=3 state differences=0/%u bytes; cursor displacement=0\n",3*n);
    overlay=0;load(DATA);CHECK(state(actual)==n && !memcmp(expected,actual,n));
    CHECK(load_end==DATA+size);memset(G+DATA,0xA5,4096);CHECK(save(DATA)==size);
    printf("no-overlay world differences=%u/%u bytes; cursor displacement=0\n",
           differences(written,G+DATA,size),size);
    CHECK(!memcmp(written,G+DATA,size));
    load(DATA);CHECK(load_end==DATA+size);CHECK(state(actual)==n && !memcmp(expected,actual,n));
    printf("roundtrip unrelated state differences=0/%u; world bytes=0/%u; native owners=8/8, tracks/zones/areas=73/22/4\n",n,size);
    /* GameplayData envelope. Digest/resource boundaries are mocked, native
     * counted/aligned section walk and marker validation are retained. */
    unsigned accepted=0,rejected=0,fallbacks=0,envelope_bytes=0;
    for(unsigned i=0;i<15;++i) for(unsigned on=0;on<2;++on) {
        overlay=on;memset(G+DATA,0,4096);M32(DATA+0x10)=0x656D6147;M32(DATA+0x14)=12;
        M32(DATA+0x18)=2;uint32_t p=DATA+0x80;
        for(unsigned j=0;j<2;++j) {
            M32(p)=activity_keys[j];M32(p+4)=32;
            for(unsigned k=0;k<32;++k)M8(p+8+k)=(uint8_t)(1+j*33+k);
            p+=48;
        }
        M32(p)=spawn_keys[i];M32(p+16)=spawn_keys[i];world_at=p+32;
        memcpy(G+world_at,written,size);uint8_t envelope[4096];
        unsigned length=world_at-DATA+size;memcpy(envelope,G+DATA,length);
        memset(G+FE,0,0x400);M32(FE)=VT+96;M32(VT+96+16)=0xFF000003;
        M32(FE+0x244)=M32(FE+0x248)=fallback_key;M32(0xB69BA0)=0x23000;
        strcpy((char*)G+0x23040,"l2ra");empty(ACT+0x58);
        Cpu c=cpu(FE);uint32_t a[]={DATA,length};vm_reads=0;
        invoke(&c,f_00649220,2,a);CHECK((c.eax&255)==1 && vm_reads==2);
        CHECK(load_end==world_at+size);CHECK(!memcmp(envelope,G+DATA,length));envelope_bytes+=length;
        M32(CURSOR)=SCRATCH;uint32_t vm_args[]={CURSOR,SCRATCH,4096,RESULT};
        c=cpu(ACT);CHECK((invoke(&c,f_006266B0,4,vm_args)&255)==1 && M32(RESULT)==2);
        CHECK(M32(CURSOR)==SCRATCH+96 && !memcmp(G+SCRATCH,G+DATA+0x80,96));
        CHECK(state(actual)==n && !memcmp(expected,actual,n));
        CHECK(M32(FE+0x244)==(on?spawn_keys[i]:fallback_key));
        CHECK(M32(FE+0x248)==(on?spawn_keys[i]:fallback_key));
        c=cpu(FE);CHECK(invoke(&c,f_0061E080,0,NULL)==(on?spawn_keys[i]:fallback_key));
        if(on)++accepted;else {
            ++rejected;
            /* Also exercise native career_start fallback if defaults vanished. */
            M32(FE+0x244)=M32(FE+0x248)=spawn_keys[i];
            for(unsigned selected=0;selected<2;++selected) {
                M8(FE+0x24C)=selected;M32(FE+0x244)=spawn_keys[i];c=cpu(FE);
                CHECK(invoke(&c,f_0061E080,0,NULL)==fallback_key);
                CHECK(M32(FE+0x244)==fallback_key);
            }
            ++fallbacks;
        }
    }
    CHECK(accepted==15 && rejected==15 && fallbacks==15 && format_calls==30);
    printf("spawn on=15/15 off rejected=15/15 valid fallback=15/15 (both slots); envelope differences=0/%u bytes\n",envelope_bytes);
    printf("ROCKSAVE PASS: initialized inside loader %d times, repeated ownership flags unchanged\n",init_calls);
    free(G);return 0;
}
'''


def save_fixture(source):
    """Synthetic career state around pinned native functions; never read a save."""
    sys.path.insert(0, str(ROOT / 'recomp'))
    import build_all
    import private_hooks
    import private_hooks_test
    import recomp

    base = ROOT / 'recomp/out/carbon-base'
    if not (base / 'image.json').is_file():
        print('SKIP: save fixture requires private translated outputs')
        return False
    image = json.loads((base / 'image.json').read_text())
    if not Path(image['exe']).is_file():
        print('SKIP: save fixture requires pinned private image')
        return False
    pe = recomp.PE(image['exe'], expected_sha256=image['sha256'])
    starts = [int(v.strip().removesuffix('u'), 16) for v in re.search(
        r'guest_func_addr\[\] = \{([^}]+)', (base / 'table.c').read_text())[1].split(',')]
    functions = [(a, starts[i+1] if i+1 < len(starts) else a+16, 'fixture')
                 for i, a in enumerate(starts)]
    hooks = private_hooks.load_registry(pe, functions)
    native = []
    filtered_iterator = plain_iterator = None
    cache = {}
    for address, (chunk, digest) in SAVE_BODIES.items():
        assert starts.index(address) // build_all.CHUNK == chunk
        if chunk not in cache:
            cache[chunk] = (base / f'NFSC_{chunk:02d}.c').read_text()
        text = cache[chunk]
        name = private_hooks.original_name(address)
        if f'void {name}(' not in text:
            name = f'f_{address:08X}'
        body = private_hooks_test.body(text, name).replace(name, f'f_{address:08X}', 1)
        assert hashlib.sha256(body.encode()).hexdigest() == digest, hex(address)
        if address == 0x472980:
            native.append(body.replace('f_00472980(', 'unfiltered_successor(', 1))
        emitted = (private_hooks.wrap(address, body, hooks[address])
                   if address in (0x472980, 0x62E980) and address in hooks else body)
        if address == 0x472980:
            filtered_iterator, plain_iterator = emitted, body
        native.append(emitted)

    dst = g.Pack((g.DEFAULT_CARBON.parent / 'GLOBAL/gameplay.bin').read_bytes()).core(True)
    src = g.Pack((g.DEFAULT_MW.parent / 'GLOBAL/gameplay.bin').read_bytes()).core(False)
    places = sorted((c for c in dst.collections.values()
                     if c.parent in (0x874B96D6, 0xB7F31748)), key=lambda c: c.key)
    assert [c.key for c in places] == [0x00D5B4E5, 0x56941DCE, 0x636C2E42, 0x834442E3,
                                     0x8D84FCE6, 0x9BEE221F, 0xA99E95F9, 0xBFC67884]
    def field(c, k):
        return next(int.from_bytes(raw, 'little') for key, _, _, raw in c.fields if key == k)
    keys = [c.key for c in places]
    types = [1 if c.parent == 0xB7F31748 else 2 for c in places]
    triggers = [field(c, 0xD5DFD829) for c in places]
    imported = sorted(((t, c) for t, c in src.triggers()
                       if t in (0x326427BB, 0x4698966B, 0x73049919)),
                      key=lambda row: ((0x326427BB, 0x4698966B, 0x73049919).index(row[0]), row[1].name))
    assert len(imported) == 15
    # Reconstruct the decoded reserved identities from source names using the
    # independently maintained vault hash, rather than the hook's threshold.
    sys.path.insert(0, str(ROOT / 'tools_snapshot/vaults'))
    from vaultlib import hash32
    donor = dst.collections[0x8D84FCE6]
    assert hash32(donor.name[:-1]) == donor.key
    prefix = donor.name[:donor.name.rindex(b'/')+1].decode('ascii')
    maximum = max(keys)
    span = (0xFFFFFFFF-maximum)//3
    additions = []
    for t, c in imported:
        group = (0x326427BB, 0x4698966B, 0x73049919).index(t)
        name = prefix+c.name[:-1].decode('ascii').rsplit('/', 1)[-1]
        candidates = (hash32(name if n == 1 else f'{name}_{n}') for n in range(1, 10000))
        additions.append(next(k for k in candidates if maximum+group*span < k <= maximum+(group+1)*span))
    assert len(set(additions)) == 15 and all(k > maximum for k in additions)
    # This checkout can precede the gameplay-data landing. Once present, bind
    # the codec assumption to the actual converter as well as the source pack.
    if hasattr(g, 'place_premises'):
        converted = g.place_premises(src.triggers(), dst)
        assert len(converted) == 15 and {c.key for _, c in converted} == set(additions)
        assert {field(c, 0xD5DFD829) for _, c in converted} == {c.key for _, c in imported}
    keys += additions
    types += [1 if t == 0x73049919 else 2 for t, _ in imported]
    triggers += [c.key for _, c in imported]
    spawns = [field(c, 0x2241F4CD) for _, c in imported]
    fallback = next(c for c in dst.collections.values() if c.name == b'career_start_l2ra\0')
    assert fallback.parent == 0xA7BCCF63 and hash32(fallback.name[:-1]) == fallback.key
    assert pe.read(0x9D871C, 16) == b'career_start_%s\0'
    assert len(set(spawns)) == 15 and types.count(1) == 7
    assert sum(k > 0xBFC67884 for k in keys) == 15
    declarations = '\n'.join('static const uint32_t '+name+'[] = {' + ','.join(hex(k) for k in values) + '};'
                             for name, values in (('place_keys', keys), ('place_types', types),
                                                  ('trigger_keys', triggers), ('spawn_keys', spawns),
                                                  ('activity_keys', [0x10874E8D, 0x3103659B])))
    declarations += f'\nstatic const uint32_t fallback_key = {hex(fallback.key)};'
    env = {k: v for k, v in os.environ.items() if not k.startswith(('NFS_', 'BOOT_'))}
    with tempfile.TemporaryDirectory(prefix='rocksave-') as directory:
        td = Path(directory)
        (td / 'carbon_rockplaces.h').write_text(source)
        (td / 'save_native.inc').write_text('\n\n'.join(native))
        (td / 'save.c').write_text(SAVE_HARNESS.replace('/* SAVE KEYS */', declarations))
        binary = td / 'save'
        command = ['clang', '-O1', '-g', '-DNFS_GAME=2', '-DRECOMP_ABICHECK',
                   '-fsanitize=address,undefined', '-I', str(td), '-I', str(base),
                   '-I', str(ROOT / 'runtime'), '-I', str(ROOT / 'recomp'),
                   str(td / 'save.c'), '-o', str(binary)]
        result = subprocess.run(command, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr[-5000:]
        for value in ('1', '0'):
            result = subprocess.run([str(binary), value], env=env, capture_output=True, text=True)
            print(result.stdout.strip(), flush=True)
            assert result.returncode == 0, result.stderr[-5000:]
        # Reintroduce the reviewed bug: the feature switch disables the codec
        # guard even though all fifteen imported premises remain in the tree.
        scope = 'if (caller != 0x006326F0u && caller != 0x00648A1Fu) return;'
        assert source.count(scope) == 1
        gated = source.replace(scope, scope + '\n    if (!carbon_rockplaces_enabled()) return;')
        (td / 'carbon_rockplaces.h').write_text(gated)
        result = subprocess.run(command, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr[-3000:]
        broken = subprocess.run([str(binary), '0'], env=env, capture_output=True, text=True)
        assert broken.returncode == 1 and 'cursor displacement=64' in broken.stdout, broken.stdout + broken.stderr[-2000:]
        print('switch-gated codec control: ' + broken.stdout.strip() + '; acceptance exit=1 (protected exit=0)')
        (td / 'carbon_rockplaces.h').write_text(source)
        # The original unwrapped iterator is exactly the rockhooks codec.
        (td / 'save_native.inc').write_text('\n\n'.join(native).replace(filtered_iterator, plain_iterator))
        result = subprocess.run(command, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr[-3000:]
        result = subprocess.run([str(binary), '1'], env=env, capture_output=True, text=True)
        assert result.returncode == 1 and 'cursor displacement=64' in result.stdout, result.stdout + result.stderr[-2000:]
        print('rockhooks original: ' + result.stdout.strip() + '; acceptance exit=1')
        # A common-iterator hook must leave initialization and other callers
        # unchanged; this mutant otherwise appears to protect the save cursor.
        (td / 'save_native.inc').write_text('\n\n'.join(native))
        (td / 'carbon_rockplaces.h').write_text(source.replace(scope, '/* broken caller scope */'))
        result = subprocess.run(command, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr[-3000:]
        result = subprocess.run([str(binary), '1'], env=env, capture_output=True, text=True)
        assert result.returncode == 1 and 'ROCKSAVE CHECK' in result.stderr, result.stderr[-2000:]
        print('negative iterator caller scope: good exit=0 / broken exit=1 (fresh ownership)')
    return True


ICON_BODIES = {
    0x0061DEA0: (26, '388cbb0535200f2b5654a60286262339094557509833cfe240d778697be7dcd4'),
    0x0062DBF0: (26, '0b19a27795fe741ebbcc78c9960ed5c2818e3232996ff4f82ccf6e3054fbc116'),
    0x00626F90: (26, 'c5665c256e263c1667b3beac59c63ad2e96b5de6cce3dae84aa73e5f8cd8d6b2'),
    0x0061FE30: (26, '141d3131aa7f0abae1be8092f6836da678ed1582be8804b2e58acc6f7ae459ae'),
    0x00614450: (25, '590f66c6e71c0dfa24746033d61bc87ffc306a73301ce3abb39348dad494b92c'),
    0x006149B0: (25, '7460c83cf5165b050a31a300165629ca7c87687693a1cb4a4d1f8c8111b344c5'),
    0x0064B410: (27, '37c0bbf133034224be31753e108f8f11bdfe3e0d95e7aea7511eefd22d97e655'),
}

ICON_HARNESS = r'''
#include "funcs.h"
#include "host.h"
#include <stdlib.h>
#include <stdarg.h>
#include <setjmp.h>
uint8_t *G;
int diag_on;
#define CHECK(x) do { if (!(x)) { fprintf(stderr,"ROCKICON CHECK %d: %s\n",__LINE__,#x); exit(1); } } while (0)
static uint64_t now=1;
static unsigned log_count,position_reads;
static float player_position[]={9173,2147,152};
uint64_t host_ticks(void) { CHECK(diag_on);return now; }
int private_carbon_player_position(float *p) {
    CHECK(diag_on);memcpy(p,player_position,sizeof player_position);++position_reads;return 1;
}
void diag_event(const char *fmt, ...) {
    CHECK(diag_on);char line[1024];va_list args;va_start(args,fmt);
    vsnprintf(line,sizeof line,fmt,args);va_end(args);
    CHECK(strstr(line," active=1 ") && strstr(line," lua_IsActiveMenuGate=1 "));
    ++log_count;
}
/* ICON KEYS */
enum { IM=0x10000, HASH=0x11000, STACK=0x90000, OUTPUT=0xA0000 };
static unsigned heap=0x200000, blocks, freed, original_calls, evictions, pool_fail;
static uint32_t removed[32];
static struct { uint32_t p,n; int live; } allocations[64];
static uint32_t trigger(unsigned i) { return 0x12000+i*0x100; }
uint32_t gmalloc(uint32_t n) {
    CHECK(blocks<64); uint32_t p=heap; heap+=(n+79)&~63u;
    allocations[blocks++]=(typeof(allocations[0])){p,n,1};
    memset(G+p,0,n); memset(G+p+n,0xA7,16); return p;
}
static void guards(void) {
    for(unsigned i=0;i<blocks;++i)
        for(unsigned j=0;j<16;++j) CHECK(M8(allocations[i].p+allocations[i].n+j)==0xA7);
}
void gfree(uint32_t p) {
    guards();
    for(unsigned i=0;i<blocks;++i) if(allocations[i].p==p) {
        CHECK(allocations[i].live); allocations[i].live=0; ++freed; return;
    }
    CHECK(0);
}
#include "carbon_rockplaces.h"
void abi_violation(Cpu *c,uint32_t fn,uint32_t b,uint32_t s,uint32_t d,uint32_t p,uint32_t sp) {
    (void)c;(void)b;(void)s;(void)d;(void)p;(void)sp;
    fprintf(stderr,"icon ABI %x\n",fn);exit(1);
}
void bad_jump(Cpu *c,uint32_t at) {(void)c;fprintf(stderr,"icon guest %x\n",at);exit(1);}
void dispatch(Cpu *c,uint32_t at) {bad_jump(c,at);}
void host_import(Cpu *c,uint32_t at) {bad_jump(c,at);}
void f_0060BA70(Cpu *c) {
    CHECK(c->ecx==0xA99720 && arg(c,0)==0x28 && arg(c,1)==0);
    c->eax=pool_fail?0:gmalloc(0x28);c->esp+=12;
}
void f_0087EAC0(Cpu *c) {c->eax=42;c->esp+=4;}
void f_00615F70(Cpu *c) {c->esp+=4;}
void f_00582C50(Cpu *c) {bad_jump(c,0x582C50);}
/* Object teardown is isolated; the retained removal body owns both partitions. */
void f_0062B000(Cpu *c) {
    CHECK(arg(c,0)==1 && evictions<32);
    CHECK((M8(c->ecx+1)&0x10) && (M8(c->ecx)==13 || M8(c->ecx)==14));
    removed[evictions++]=c->ecx;memset(G+c->ecx,0,0x28);c->esp+=8;
}
/* Observe the first access past the native 256x8 table, at its return slot.
 * No instruction/body changes: M32 retains lvalue semantics. The good reader
 * never accesses this address; entry/argument setup happens with guard off. */
static jmp_buf overflow;
static int reader_active;
static uint32_t *reader_word(uint32_t a) {
    if(reader_active && a==STACK-12) longjmp(overflow,1);
    return (uint32_t *)(G+a);
}
#undef M32
#define M32(a) (*reader_word((uint32_t)(a)))
#include "icon_native.inc"
#undef M32
#define M32(a) (*(u32a *)(G+(uint32_t)(a)))
static uint32_t invoke(Cpu *c,void (*fn)(Cpu *),int n,const uint32_t *a) {
    uint32_t sp=c->esp;
    for(int i=n-1;i>=0;--i){c->esp-=4;M32(c->esp)=a[i];}
    c->esp-=4;M32(c->esp)=0xFEEDF00D;fn(c);c->esp=sp;return c->eax;
}
static void follow_node(Cpu *c) { c->eax=M32(arg(c,0));c->esp+=4; }
static void trace_iterator(Cpu *c) { carbon_rockplaces_successor(c,follow_node); }
uint32_t call_guest(Cpu *c,uint32_t fn,int n,const uint32_t *a) {
    switch(fn) {
    case 0x614450: return invoke(c,f_00614450,n,a);
    case 0x626F90: return invoke(c,f_00626F90,n,a);
    case 0x62DBF0: return invoke(c,f_0062DBF0,n,a);
    case 0x60BA70: return invoke(c,f_0060BA70,n,a);
    case 0x61FE30: return invoke(c,f_0061FE30,n,a);
    case 0x64B410: return invoke(c,f_0064B410,n,a);
    case 0x472980: return invoke(c,trace_iterator,n,a);
    case 0x4613E0: CHECK(n==0);return M32(c->ecx);
    case 0x463A80:
        if(n==2 && a[0]==0xD5DFD829 && a[1]==0) return c->ecx+0x2C;
        CHECK(n==2 && a[0]==0x9F743A0E && a[1]==0);
        return c->ecx-4+0xB0;
    case 0x471050:
        CHECK(n==1);return a[0]==0x9D8A00?art_hash:a[0]==0x9D89D8?house_hash:a[0]==0x9D89E8?shop_hash:0;
    default: bad_jump(c,fn);return 0;
    }
}
static void original(Cpu *c) {++original_calls;c->eax=0x12345678;c->esp+=4;}
static void tick(uint32_t caller) {
    Cpu c={0};c.esp=STACK;c.fs_base=0x80000;c.ecx=0x87654321;
    M32(c.esp)=caller;
    carbon_rockplaces_successor(&c,original);
    CHECK(c.esp==STACK+4 && c.eax==0x12345678 && c.ecx==0x87654321);
}
static void visible_reader(void) {
    unsigned count=M32(IM+0x2F8);M32(IM+0x2FC)=count;
    for(unsigned i=0;i<count;++i) M8(M32(M32(IM+0x300)+i*4)+1)|=3;
    memset(G+OUTPUT,0xA7,256*4+16);
    Cpu c={0};c.esp=STACK-12;c.ecx=IM;
    M32(c.esp)=0xFEEDF00D;M32(c.esp+4)=OUTPUT;M32(c.esp+8)=0;
    if(setjmp(overflow)) {
        reader_active=0;
        printf("native 0061DEA0: visible=%u table overflow writes=1 (first at entry 257)\n",count);
        exit(42);
    }
    reader_active=1;f_0061DEA0(&c);reader_active=0;
    CHECK(c.eax==count && c.esp==STACK && M32(STACK-12)==0xFEEDF00D);
    for(unsigned i=0;i<count;++i) CHECK(M32(OUTPUT+i*4)==M32(M32(IM+0x300)+i*4));
    for(unsigned i=0;i<16;++i) CHECK(M8(OUTPUT+256*4+i)==0xA7);
    printf("native 0061DEA0: visible=%u table overflow writes=0 output guard intact\n",count);
}
int main(int argc,char **argv) {
    unsigned mode=argc>1?(unsigned)atoi(argv[1]):0, initial=mode==2?254:256;
    G=calloc(1,0xB00000);CHECK(G);
    M32(0xA98294)=IM;M32(IM+0x300)=gmalloc(256*4);
    uint32_t list=M32(IM+0x300);
    M32(IM+0x2F8)=initial;M32(IM+0x2FC)=mode==6?128:initial;
    M32(IM+0x24)=0;M32(IM+0x38)=63;M32(IM+0x3C)=63;M32(IM+0x40)=HASH;
    uint32_t retained[256];
    for(unsigned i=0;i<initial;++i) {
        retained[i]=0x500000+i*64;M32(list+i*4)=retained[i];
        M8(retained[i])=i>=200 && i<250?(i&1?13:14):1;
        M8(retained[i]+1)=mode==4?3:0x13;
    }
    /* Last slots fail either the type or disposable-flag test. */
    M8(retained[initial-1])=13;M8(retained[initial-1]+1)=3;
    M8(retained[initial-2])=14;M8(retained[initial-2]+1)=3;
    for(unsigned i=0;i<15;++i) {
        uint32_t t=trigger(i),h=HASH+(keys[i]&63)*8;
        CHECK(!M32(h));M32(h)=keys[i];M32(h+4)=t;
        M16(t+0x14)=(i<3?0x2000:i<7?0x8000:0x4000)|3;M32(t+0x70)=1;
        MF32(t+0xB0)=9173+(float)i;MF32(t+0xB4)=2147;MF32(t+0xB8)=152;
        if(mode==1 && i || mode>=7 && i>=3) M32(t+0x9C)=retained[i];
    }
    if(mode==3) M32(HASH+(keys[0]&63)*8+4)=0;
    if(mode==0) {
        Cpu c={0};c.esp=STACK;c.fs_base=0x80000;
        uint32_t a[]={11,trigger(0)+0xB0,0,0};
        for(unsigned i=0;i<3;++i) {c.ecx=IM;CHECK(invoke(&c,f_00626F90,4,a)==0);}
        printf("native exhaustion: allocated=256 lot icons=0/3\n");
    }
    carbon_rockplaces_pending=0x7FFF;
    tick(0x12345678);CHECK(M32(IM+0x2F8)==initial && carbon_rockplaces_pending==0x7FFF);
    pool_fail=mode==5;tick(0x62F883);
    if(mode==8) {visible_reader();CHECK(0);}
    if(mode==4) {
        CHECK(M32(IM+0x2F8)==256 && carbon_rockplaces_pending==0x7FFF && evictions==0);
        for(unsigned i=0;i<15;++i) CHECK(!M32(trigger(i)+0x9C));
        guards();printf("no disposable candidate: count=256 recovered=0 pending=15\n");return 0;
    }
    if(mode==5) {
        CHECK(M32(IM+0x2F8)==255 && carbon_rockplaces_pending==0x7FFF && evictions==1);
        CHECK(blocks==1 && !M8(1) && !M32(0x20) && !M32(0x24));
        for(unsigned i=0;i<15;++i) CHECK(!M32(trigger(i)+0x9C));
        pool_fail=0;tick(0x62F883);
    }
    if(mode==3) {
        CHECK(carbon_rockplaces_pending==1);
        M32(HASH+(keys[0]&63)*8+4)=trigger(0);tick(0x62F883);
    }
    unsigned made=mode==1?1:mode>=7?3:15;
    CHECK(M32(IM+0x2F8)<=256 && M32(IM+0x300)==list && !freed);
    CHECK(evictions==made-(256-initial));CHECK(!carbon_rockplaces_pending);
    CHECK(M32(IM+0x2FC)==(mode==6?128:initial-evictions));
    for(unsigned i=0;i<evictions;++i) CHECK(removed[i]==retained[249-i]);
    for(unsigned i=0;i<initial;++i) {
        int gone=0,found=0;
        for(unsigned j=0;j<evictions;++j) gone|=removed[j]==retained[i];
        for(unsigned j=0;j<M32(IM+0x2F8);++j) found|=M32(list+j*4)==retained[i];
        CHECK(found==!gone);
    }
    unsigned before=blocks;carbon_rockplaces_pending=0x7FFF;tick(0x62F883);
    CHECK(blocks==before && !carbon_rockplaces_pending);
    M32(IM+0x2FC)=M32(IM+0x2F8);
    for(unsigned i=0;i<15;++i) {
        uint32_t t=trigger(i),icon=M32(t+0x9C);CHECK(icon);
        Cpu c={0};c.esp=STACK;uint32_t a[]={t};
        CHECK((invoke(&c,f_0064B410,1,a)&255)==1);
        if(!(mode==1 && i || mode>=7 && i>=3)) {
            CHECK(M8(icon)==(i<3?11:i<7?10:12) && M8(icon+1)==3);
            CHECK(M32(icon+0x20)==(i<3?0xFF00A0C6:i<7?0xFF66BA44:0xFFF0C000));
            CHECK(M32(icon+0x24)==(i<3?art_hash:i<7?house_hash:shop_hash));
            CHECK(!memcmp(G+icon+0x10,G+t+0xB0,12));
        }
    }
    guards();printf("recovered places=15/15 lots=3/3 count=%u evicted=%u mode=%u\n",M32(IM+0x2F8),evictions,mode);
    visible_reader();
    if(mode==0) {
        M32(0xA982B8)=0x18000;M32(0x18000+0xDC)=0x7777;M32(0x18000+0x74)=0x19000;
        M32(0xA98170)=trigger(0);M8(IM+0x30C)=M8(IM+0x30D)=1;
        for(unsigned i=0;i<3;++i) {
            uint32_t node=0x19000+i*32,premise=0x1A000+i*64;
            M32(node)=i<2?node+32:0x18070;M32(node+0x14)=premise;
            M32(premise+0x14)=0x7777;M32(premise+0x20)=1;
            MF32(premise+0x24)=-2147;MF32(premise+0x28)=152;MF32(premise+0x2C)=9173+(float)i;
            M32(premise+0x30)=keys[i];M32(trigger(i)+4)=keys[i];
            M32(trigger(i)+0x20)=trigger((i+1)%3);
        }
        diag_on=1;Cpu c={0};c.esp=STACK;
        carbon_rockplaces_trace(&c);CHECK(log_count==3 && position_reads==1);
        carbon_rockplaces_trace(&c);CHECK(log_count==3 && position_reads==1);
        now+=1000000000ull;carbon_rockplaces_trace(&c);CHECK(log_count==6 && position_reads==2);
        player_position[0]+=1000;now+=1000000000ull;
        carbon_rockplaces_trace(&c);CHECK(log_count==6 && position_reads==3);
        printf("diagnostic lines=6/6 active, within-second repeats=0, far-away lines=0\n");
    }
    free(G);return 0;
}
'''


GROWTH_BASELINE_SHA256 = 'b108fdae10258d4273d93948e3c9c0c562bb1cc07093f973dba3251ae221176d'
GROWTH_BASELINE = r'''
static void carbon_rockplaces_icons(Cpu *c) {
    static const uint32_t keys[] = {0xDAF7164Eu, 0x2F8CA402u, 0xE925D054u};
    uint32_t manager = M32(0x00A98294u);
    if (!manager || !M32(manager + 0x300)) return;
    Cpu work = *c;
    work.esp -= 128;
    for (unsigned i = 0; i < 3; ++i) {
        if (!(carbon_rockplaces_pending & (1u << i))) continue;
        work.ecx = manager;
        uint32_t trigger = call_guest(&work, 0x00614450u, 1, keys + i);
        if (!trigger || !(M16(trigger + 0x14) & 0x2000)) continue;
        if (!M32(trigger + 0x9C)) {
            unsigned count = M32(manager + 0x2F8);
            if (count >= 259) continue;
            work.ecx = trigger + 4;
            uint32_t field_args[] = {0x9F743A0Eu, 0};
            uint32_t position = call_guest(&work, 0x00463A80u, 2, field_args);
            if (!position) continue;
            uint32_t args[] = {0xBu, position, 0, 0};
            uint32_t icon;
            if (count < 256) {
                work.ecx = manager;
                icon = call_guest(&work, 0x00626F90u, 4, args);
            } else {
                work.ecx = 0x00A99720u;
                uint32_t allocation[] = {0x28u, 0};
                icon = call_guest(&work, 0x0060BA70u, 2, allocation);
                if (!icon) continue;
                work.ecx = icon;
                icon = call_guest(&work, 0x0061FE30u, 3, args);
                if (count == 256) {
                    uint32_t old = M32(manager + 0x300), list = gmalloc(259 * 4);
                    memcpy(G + list, G + old, 256 * 4);
                    M32(manager + 0x300) = list;
                    gfree(old);
                }
                M32(M32(manager + 0x300) + count * 4) = icon;
                M32(manager + 0x2F8) = count + 1;
            }
            if (!icon) continue;
            M32(icon + 0x20) = 0xFF00A0C6u;
            uint32_t name = 0x009D8A00u; /* native MINIMAP_ICON_CAR_LOT */
            M32(icon + 0x24) = call_guest(&work, 0x00471050u, 1, &name);
            M8(icon + 1) |= 3;
            M32(trigger + 0x9C) = icon;
        }
        carbon_rockplaces_pending &= ~(1u << i);
    }
}
'''


def icon_fixture(source, keys):
    import private_hooks_test
    from vaultlib import hash32
    base = ROOT / 'recomp/out/carbon-base'
    native = []
    for address, (chunk, digest) in ICON_BODIES.items():
        body = private_hooks_test.body((base / f'NFSC_{chunk:02d}.c').read_text(), f'f_{address:08X}')
        assert hashlib.sha256(body.encode()).hexdigest() == digest, hex(address)
        native.append(body)
    declarations = ('static const uint32_t keys[] = {' + ','.join(hex(k) for k in keys) + '};\n'
                    + f'static const uint32_t art_hash={hash32(b"MINIMAP_ICON_CAR_LOT")};'
                    + f'static const uint32_t house_hash={hash32(b"SAFEHOUSE_ICON")};'
                    + f'static const uint32_t shop_hash={hash32(b"MINIMAP_ICON_CHOP_SHOP")};')
    with tempfile.TemporaryDirectory(prefix='rockicon-') as directory:
        td = Path(directory)
        inc = td / 'carbon_rockplaces.h'
        inc.write_text(source)
        (td / 'icon_native.inc').write_text('\n\n'.join(native))
        (td / 'icons.c').write_text(ICON_HARNESS.replace('/* ICON KEYS */', declarations))
        binary = td / 'icons'
        command = ['clang', '-O1', '-g', '-DNFS_GAME=2', '-DRECOMP_ABICHECK',
                   '-fsanitize=address,undefined', '-I', str(td), '-I', str(base),
                   '-I', str(ROOT / 'runtime'), '-I', str(ROOT / 'recomp'),
                   str(td / 'icons.c'), '-o', str(binary)]
        result = subprocess.run(command, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr[-4000:]
        for mode in range(8):
            result = subprocess.run([str(binary), str(mode)], capture_output=True, text=True)
            print(result.stdout.strip(), flush=True)
            assert result.returncode == 0, result.stderr[-4000:]
        assert hashlib.sha256(GROWTH_BASELINE.strip().encode()).hexdigest() == GROWTH_BASELINE_SHA256
        start = source.index('static void carbon_rockplaces_icons(Cpu *c) {')
        end = source.index('\nvoid carbon_rockplaces_owner', start)
        inc.write_text(source[:start] + GROWTH_BASELINE.strip() + '\n' + source[end:])
        result = subprocess.run(command, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr[-4000:]
        result = subprocess.run([str(binary), '8'], capture_output=True, text=True)
        print('75bee61d growth control: ' + result.stdout.strip(), flush=True)
        assert result.returncode == 42 and 'visible=259 table overflow writes=1' in result.stdout, result.stderr[-4000:]
        for label, old, new in (
            ('original missing-icon behavior', 'carbon_rockplaces_icons(c);', '/* no recovery */'),
            ('wrong iterator caller', 'caller == 0x0062F883u', '1'),
        ):
            assert source.count(old) == 1
            inc.write_text(source.replace(old, new))
            result = subprocess.run(command, capture_output=True, text=True)
            assert result.returncode == 0, result.stderr[-3000:]
            result = subprocess.run([str(binary), '0'], capture_output=True, text=True)
            assert result.returncode == 1 and 'ROCKICON CHECK' in result.stderr, result.stdout + result.stderr[-3000:]
            print(label + ': acceptance exit=1 (recovered exit=0); ' + result.stdout.strip())


def main():
    groups = derived_keys()
    if groups is None:
        print('private gameplay inputs absent')
        return 3
    positives, zones, lots, houses = groups
    assert converted_counts() == (73, 22, 4, 23, 8), converted_counts()
    assert converted_counts(True) != (73, 22, 4, 23, 8)
    print(f'converted pack: tracks/zones/areas/premises/native-keyed {converted_counts()}; broken {converted_counts(True)}')
    keys = positives + zones + lots + houses
    print(f'derived: imported={len(positives)}, territory zones={len(zones)}, native lots={len(lots)}, area-less safehouses={len(houses)}')
    source = (PRIVATE / 'carbon_rockplaces.h').read_text()
    if not save_fixture(source):
        return 3
    imported = g.Pack((g.DEFAULT_MW.parent / 'GLOBAL/GAMEPLAY.BIN').read_bytes()).core(False)
    place_keys = positives + [c.key for parent, c in imported.triggers()
                             if imported.collections[parent].name == b'zone_safehouse\0']
    place_keys += [c.key for parent, c in imported.triggers()
                   if imported.collections[parent].name == b'zone_customshop\0']
    assert len(place_keys) == 15 and len(set(place_keys)) == 15
    icon_fixture(source, place_keys)
    feature = json.loads((PRIVATE / 'features/rockplaces.json').read_text())
    assert feature['staged_sources'] == {'carbon_rockplaces.c': 'carbon_rockplaces.h'}
    hooks = json.loads((PRIVATE / 'hooks/rockplaces.json').read_text())['hooks']
    assert {(h['address'], h['provider']) for h in hooks} == {
        ('0062E980', 'carbon_rockplaces_owner'), ('005AD590', 'carbon_rockplaces_map'),
        ('00472980', 'carbon_rockplaces_successor')}
    harness = HARNESS.replace('/* FIXTURE KEYS */', 'static const uint32_t keys[] = {' + ','.join(hex(k) for k in keys) + '};')
    env = {k: v for k, v in os.environ.items() if not k.startswith(('NFS_', 'BOOT_'))}
    with tempfile.TemporaryDirectory(prefix='rockplaces-') as td:
        td = Path(td)
        inc = td / 'carbon_rockplaces.h'
        inc.write_text(source)
        (td / 'test.c').write_text(harness)
        binary = td / 'test'
        cmd = ['clang', '-DNFS_GAME=2', '-I', str(td), '-I', str(ROOT / 'runtime'),
               '-I', str(ROOT / 'recomp'), '-I', str(ROOT / 'recomp/out'),
               str(td / 'test.c'), '-o', str(binary)]

        def build():
            result = subprocess.run(cmd, capture_output=True, text=True)
            assert result.returncode == 0, result.stderr[-2500:]

        def run(value, mode, expected=0):
            result = subprocess.run([str(binary), value, str(mode)],
                                    env=dict(env, NFS_CARBON_ROCKPLACES=value), capture_output=True, text=True)
            assert result.returncode == expected, result.stdout + result.stderr
            return result

        build()
        for value in ('1', '0'):
            for mode in range(5):
                print(run(value, mode).stdout.strip())
        # An unset switch also defaults to On.
        result = subprocess.run([str(binary), '1', '0'], env=env, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        for label, old, new in (
            ('all-true scope', 'return key == 0xDAF7164Eu || key == 0x2F8CA402u || key == 0xE925D054u;', 'return 1;'),
            ('disabled switch ignored', 'return !(value && !strcmp(value, "0"));', 'return 1;'),
            ('missing object guard', 'if (!object || M32(object + 0x18) != 1) return;', '/* broken guard */'),
            ('projection omitted', 'call_guest(c, 0x0056E770u, 4, projection);', '/* broken projection */'),
        ):
            assert old in source
            inc.write_text(source.replace(old, new))
            build()
            result = run('0' if label == 'disabled switch ignored' else '1',
                         1 if label == 'missing object guard' else 0, 1)
            assert 'ROCKPLACES CHECK' in result.stderr
            print(f'negative {label}: good exit=0 / broken exit=1')
        # The source's game guard leaves no providers in an MW object.
        inc.write_text(source)
        obj = td / 'mw.o'
        result = subprocess.run(['clang', '-DNFS_GAME=1', '-I', str(ROOT / 'runtime'),
                                 '-I', str(ROOT / 'recomp'), '-I', str(ROOT / 'recomp/out'),
                                 '-x', 'c', '-c', str(inc), '-o', str(obj)],
                                capture_output=True, text=True)
        assert result.returncode == 0, result.stderr[-2500:]
        result = subprocess.run(['nm', '-gU', str(obj)], capture_output=True, text=True, check=True)
        assert 'carbon_rockplaces_' not in result.stdout
    print('PRIVATE ROCKPLACES PASS: exact scope, native calls, optional objects, retail Off, MW guard')
    return 0


if __name__ == '__main__':
    sys.exit(main())
