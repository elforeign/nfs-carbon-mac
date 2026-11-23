"""Native global dome in both camera rows; pinned former-selector control.

The production view observer only classifies the colour-grade region. The
translated native submitter must retain ED85BA82 in native and imported rows,
including repeated crossings; no model destruction or rebinding is allowed.
Good: 207 checks, 0 failures; previous selector: 249 checks, 18 failures,
ending on 1F389568 instead of ED85BA82.
Private image/build absent: exit 3. No game or emulation is launched.
"""
from pathlib import Path
import hashlib
import json
import re
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
from recomp import PE
import private_hooks

PINS = {
    '007AF7F0': ('NFSC_44.c', '4220c47ea7aeaee0454c38dd4df161c58d583ca47e06946580ffceedf36a5a1d'),
    '007AFB70': ('NFSC_44.c', 'fcbebff1c90e7f859be1ad62c1f740302f4ba3d099744cac2b4195dba8b723e1'),
    '0055BF70': ('NFSC_17.c', 'f6613f6673fd76465fa439d28a895959dba116615454ff072f98d79775619a72'),
    '0055BFB0': ('NFSC_17.c', 'a0fd15e56f9e80c3935adf1d7f18f8d9aad8ec679f09d1882915be8046b19e75'),
    '0055E7E0': ('NFSC_17.c', '2e4655c824cda25098f96ed4caa27550ddf09f335dab7477f8a23efd62481548'),
}

OLD_SELECTOR = r'''void carbon_skydome_draw(Cpu *c, void (*original)(Cpu *)) {
    const char *overlay = getenv("NFS_CARBON_TRACK_OVERLAY");
    uint32_t view = M32(c->esp + 4), mode = M32(c->esp + 8);
    uint32_t model = 0x00B77910u, current = M32(model + 8);
    if (overlay && *overlay && M32(0x00A99BBCu) == 6 &&
        M32(0x00A73358u) && view && mode && mode < 5 &&
        (current == 0xED85BA82u || current == 0x1F389568u)) {
        uint32_t camera = M32(view + 0x40);
        if (camera) {
            Cpu work = *c;
            work.esp -= 512;
            /* Same row lookup as 007A4900: this=B69CD0, camera XYZ at +40.
             * Rows contain a u16 count at +10 and u16 sections at +12.
             * The combined writer reserves 2100 for imported resources and
             * adds it to every imported row; native rows retain their bytes. */
            work.ecx = 0x00B69CD0u;
            uint32_t position = camera + 0x40;
            uint32_t row = call_guest(&work, 0x007A3290u, 1, &position);
            unsigned count = row ? M16(row + 0x10) : 0, imported = 0;
            for (unsigned i = 0; i < count && i < 384; ++i)
                imported |= M16(row + 0x12 + 2*i) == 2100;
            uint32_t key = imported ? 0x1F389568u : 0xED85BA82u;
            if (key != current && call_guest(&work, 0x0055DF00u, 1, &key)) {
                /* Native destruction preserves streaming links; initialization also
                 * transfers the scenery transform and clears its LOD owners. */
                work.ecx = model;
                call_guest(&work, 0x0055BF70u, 0, NULL);
                uint32_t init[] = {model, 0x00B76EC0u, key};
                call_guest(&work, 0x007AF7F0u, 3, init);
            }
            if (diag_on && render_dump_active())
                diag_event("skydome: path=global view=%u row=%u imported=%u gate=%08X key=%08X solid=%08X camera=%.6g,%.6g,%.6g",
                    mode, row ? M16(row + 0x0c) : 0, imported,
                    M32(0x00AB0A98u), M32(model + 8), M32(model + 12),
                    (double)MF32(position), (double)MF32(position + 4), (double)MF32(position + 8));
        }
    }
    original(c);
}
'''
OLD_SELECTOR_SHA256 = '46deb442b434b16be276ab310061666a61d7106930511cfd1776c67194d9f364'

HARNESS = r'''
#include "host.h"
#include "game_select.h"
#include "lighting_colour.h"
#include <stdlib.h>
#include <stdarg.h>
uint8_t *G;
int diag_on;
static unsigned checks, failures, queries, binds, destroys, draws, diagnostics;
static unsigned native_ready=1, imported_ready=1, dump, row=0x7000;
static uint32_t submitted, expected_position=0x5040;
#define CHECK(x) do { ++checks; if(!(x)) { ++failures; fprintf(stderr,"SKY CHECK %d: %s\n",__LINE__,#x); } } while(0)
void f_007AF7F0(Cpu *c);
void f_0055BF70(Cpu *c);
void f_0055BFB0(Cpu *c);
void f_0055E7E0(Cpu *c);
static uint32_t solid(uint32_t key) {
    return key==0xED85BA82u ? (native_ready?0x8000:0) :
        key==0x1F389568u ? (imported_ready?0x9000:0) : 0xA000;
}
int render_dump_active(void) { return dump; }
void diag_event(const char *fmt, ...) { CHECK(strstr(fmt,"path=global")!=NULL); ++diagnostics; }
uint32_t call_guest(Cpu *c,uint32_t fn,int n,const uint32_t *args) {
    uint32_t saved=c->esp;
    for(int i=n-1;i>=0;--i) {c->esp-=4;M32(c->esp)=args[i];}
    c->esp-=4;M32(c->esp)=0x12345678;
    switch(fn) {
        case 0x007A3290:
            ++queries;CHECK(c->ecx==0xB69CD0);CHECK(n==1&&arg(c,0)==expected_position);
            c->eax=row;break;
        case 0x0055DF00:CHECK(n==1);c->eax=solid(arg(c,0));break;
        case 0x0055BF70:++destroys;CHECK(n==0&&c->ecx==0xB77910);f_0055BF70(c);break;
        case 0x007AF7F0:++binds;CHECK(n==3&&arg(c,0)==0xB77910&&arg(c,1)==0xB76EC0);f_007AF7F0(c);break;
        case 0x0055E7E0:++binds;CHECK(n==1&&(c->ecx==0xB77910||(c->ecx>=0xD000&&c->ecx<0xD080)));f_0055E7E0(c);break;
        default:CHECK(0);break;
    }
    c->esp=saved;return c->eax;
}
void f_0055DF00(Cpu *c) { c->eax=solid(arg(c,0));c->esp+=4; }
void f_0079F690(Cpu *c) { CHECK(arg(c,0)==M32(0xB77918));c->eax=0xB000;c->esp+=4; }
void f_0079F640(Cpu *c) { CHECK(arg(c,0)==M32(0xB77918));c->eax=0xC000;c->esp+=4; }
void f_0070F8A0(Cpu *c) { CHECK(c->ecx==0xB000&&arg(c,0)==0xB76EC0);c->esp+=8; }
void f_005587D0(Cpu *c) { CHECK(0);c->esp+=4; }
void f_0055C830(Cpu *c) { c->eax=solid(arg(c,0));c->esp+=4; }
void f_00402850(Cpu *c) { c->eax=0x6000;c->esp+=4; }
void f_00478820(Cpu *c) {
    uint32_t p=arg(c,0);memset(G+p,0,64);
    for(unsigned i=0;i<4;++i) MF32(p+20*i)=1;
    c->esp+=4;
}
void f_0087EAC0(Cpu *c) { c->eax=0;c->esp+=4; }
void f_0070E290(Cpu *c) { c->esp+=4; }
void f_0070E040(Cpu *c) { c->esp+=4; }
void f_00729320(Cpu *c) {
    uint32_t model=arg(c,0);CHECK(model==0xB77910);
    submitted=M32(model+8);++draws;
    CHECK(M32(model+12)==solid(submitted));
    c->eax=0x87654321;c->esp+=28; /* Native 00729639: ret 0x18. */
}
#include "native.inc"
static int carbon_dn_imported_view;
static int carbon_dn_on(void) { return 1; }
#include "skydome.inc"
static float carbon_compat_day(void) { return .75f; }
#include "grade_weight.inc"
#include "submit.inc"
static void reset(void) {
    memset(G,0,0xC00000);queries=binds=destroys=draws=diagnostics=0;
    native_ready=imported_ready=1;diag_on=dump=0;row=0x7000;expected_position=0x5040;
    M32(0xA99BBC)=6;M32(0xA73358)=1;M32(0xA73388)=0xFFFFFFFF;
    for(unsigned i=0;i<5;++i) M32(0xA73374+4*i)=1;
    MF32(0x9C2478)=1;M32(0x4040)=0x5000;
    M32(0xA901A0)=M32(0xA901A4)=0xA901A0;
    for(unsigned s=0x8000;s<=0xA000;s+=0x1000) M32(s+0x88)=M32(s+0x8C)=s+0x88;
    Cpu work={0};work.esp=0x30000;work.ecx=0xB77910;
    uint32_t key=0xED85BA82;call_guest(&work,0x0055E7E0,1,&key);
    for(unsigned i=0;i<4;++i) {
        uint32_t owner=0xD000+32*i;M32(0xC028+4*i)=owner;
        work.ecx=owner;key=0x1F389568;call_guest(&work,0x0055E7E0,1,&key);
    }
    binds=0;M16(0x7010)=2;M16(0x7012)=326;M16(0x7014)=2100;
    setenv("NFS_CARBON_TRACK_OVERLAY","fixture",1);
}
static void run(uint32_t want) {
    Cpu c={0};c.esp=0x20000;c.ebp=0xABCDE;c.ebx=123;c.esi=456;c.edi=789;
    M32(c.esp+4)=0x4000;M32(c.esp+8)=1;submitted=0;
    f_007AFB70(&c);
    CHECK(c.esp==0x20004&&c.ebp==0xABCDE&&c.ebx==123&&c.esi==456&&c.edi==789);
    CHECK(submitted==want);
    uint32_t p=solid(M32(0xB77918));
    CHECK(M32(p+0x88)==0xB77910&&M32(p+0x8C)==0xB77910);
    CHECK(M32(0xB77910)==p+0x88&&M32(0xB77914)==p+0x88);
}
int main(void) {
    G=calloc(1,0xC00000);if(!G)return 2;
    reset();run(0xED85BA82);CHECK(binds==0&&destroys==0);CHECK(carbon_dn_imported_view==1);CHECK(carbon_dn_grade_weight()==.75f);
    run(0xED85BA82);CHECK(binds==0&&destroys==0);
    for(unsigned i=0;i<4;++i) CHECK(M32(0xD008+32*i)==0x1F389568);
    M16(0x7014)=2400;run(0xED85BA82);CHECK(binds==0&&destroys==0);CHECK(carbon_dn_imported_view==0);CHECK(carbon_dn_grade_weight()==0);
    M16(0x7012)=2100;run(0xED85BA82);CHECK(carbon_dn_imported_view==1);CHECK(carbon_dn_grade_weight()==.75f);
    row=0;run(0xED85BA82);CHECK(carbon_dn_imported_view==0);CHECK(carbon_dn_grade_weight()==0);
    reset();unsetenv("NFS_CARBON_TRACK_OVERLAY");run(0xED85BA82);CHECK(queries==0&&binds==0);
    reset();setenv("NFS_CARBON_TRACK_OVERLAY","",1);run(0xED85BA82);CHECK(queries==0&&binds==0);
    reset();imported_ready=0;run(0xED85BA82);CHECK(binds==0&&destroys==0);
    reset();M32(0x4040)=0;run(0xED85BA82);CHECK(queries==0);
    reset();row=0;run(0xED85BA82);CHECK(binds==0);
    reset();M16(0x7010)=0;run(0xED85BA82);CHECK(binds==0);
    reset();MF32(0x5040)=-99999;run(0xED85BA82);
    reset();M32(0xA99BBC)=3;run(0xED85BA82);CHECK(queries==0);
    reset();
    Cpu alternate={0};alternate.esp=0x30000;alternate.ecx=0xB77910;
    call_guest(&alternate,0x0055BF70,0,NULL);alternate.ecx=0xB77910;
    uint32_t night=0xBE43EDBB;call_guest(&alternate,0x0055E7E0,1,&night);
    run(0xBE43EDBB);CHECK(carbon_dn_grade_weight()==0);
    reset();M32(0xAB0A98)=0x800;run(0xED85BA82);CHECK(M32(0xAB0A98)==0x800);
    reset();diag_on=dump=1;run(0xED85BA82);CHECK(diagnostics==0);
    printf("checks=%u failures=%u final_key=%08X\n",checks,failures,submitted);
    return failures?1:0;
}
'''


def command(args, expected=0):
    result = subprocess.run(list(map(str, args)), capture_output=True, text=True)
    assert result.returncode == expected, (result.returncode, result.stdout[-2000:], result.stderr[-3000:])
    return result.stdout.strip()


def main():
    base = HERE/'out/carbon-base'
    if not (base/'image.json').is_file():
        print('SKIP: private sky fixture needs the private image/build');return 3
    image = json.loads((base/'image.json').read_text())
    if not Path(image['exe']).is_file() or any(not (base/f).is_file() for f, _ in PINS.values()):
        print('SKIP: private sky image/build unavailable');return 3
    out = HERE/'out/carbon/skydome_check';out.mkdir(exist_ok=True)
    fragments = {}
    for address, (filename, digest) in PINS.items():
        source = (base/filename).read_text()
        match = re.search(rf'void (?:f_|carbon_orig_){address}\(.*?\n}}',source,re.S)
        assert match,address
        body = match[0].replace(f'carbon_orig_{address}',f'f_{address}',1)
        assert hashlib.sha256(body.encode()).hexdigest()==digest,address
        fragments[address]=body
    pe = PE(image['exe'], expected_sha256=image['sha256'])
    registry = out/'hooks';registry.mkdir(exist_ok=True)
    for stale in registry.glob('*.json'): stale.unlink()
    record = HERE/'private_runtime/hooks/daynight_sky.json'
    (registry/record.name).write_bytes(record.read_bytes())
    hooks=private_hooks.load_registry(pe,[(0x7AFB70,0x7AFD68,''),(0x73E890,0x73E8A0,'')],registry)
    assert hooks[0x7AFB70]['provider']=='carbon_daynight_view'
    assert not (HERE/'private_runtime/hooks/skydome.json').exists()
    (out/'native.inc').write_text('\n'.join(fragments[a] for a in ('0055BF70','0055BFB0','0055E7E0','007AF7F0')))
    production=(HERE/'private_runtime/carbon_daynight_sky.h').read_text()
    production=re.search(r'void carbon_daynight_view\(.*?\n}',production,re.S)[0]
    assert hashlib.sha256(OLD_SELECTOR.encode()).hexdigest()==OLD_SELECTOR_SHA256
    # Independently check the native archive's visibility rows have no source marker.
    sys.path.insert(0,str(ROOT/'tools_snapshot/worldmerge'))
    from formats import TrackIndex
    import visibility
    native=Path(image['exe']).parent/'TRACKS/L5RA.BUN'
    if not native.is_file():
        print('SKIP: private sky visibility archive unavailable');return 3
    rows=visibility.read(visibility.payload_of(TrackIndex(native.read_bytes())),extended=True).rows
    assert rows and all(2100 not in r.entries for r in rows)
    print(f'native visibility rows without marker: {len(rows)}')
    (out/'fixture.c').write_text(HARNESS)
    grade=(HERE/'private_runtime/carbon_daynight_grade.h').read_text()
    (out/'grade_weight.inc').write_text(re.search(r'static float carbon_dn_grade_weight\(.*?\n}',grade,re.S)[0])
    good=private_hooks.wrap(0x7AFB70,fragments['007AFB70'],hooks[0x7AFB70])
    broken=good.replace('carbon_daynight_view(c, carbon_orig_007AFB70);','carbon_skydome_draw(c, carbon_orig_007AFB70);')
    assert good!=broken
    results=[]
    for label,code,selector,rc in [('good',good,production,0),('previous-selector',broken,production+'\n'+OLD_SELECTOR,1)]:
        (out/'skydome.inc').write_text(selector)
        (out/'submit.inc').write_text(code)
        binary=out/label
        command(['clang','-std=c11','-O1','-I',ROOT/'runtime','-I',HERE,'-I',out,
                 '-DNFS_GAME=NFS_GAME_PRIVATE',out/'fixture.c','-o',binary])
        result=command([binary],rc)
        results.append(f'{label}: {result} (exit {rc})')
    (out/'submit.inc').write_text(good)
    (out/'proof.txt').write_text('\n'.join(results)+'\n')
    print('\n'.join(results));return 0


if __name__=='__main__':
    sys.exit(main())
