"""Two-view submission, odd rectangles/projections and shared-target preservation.

Native split regression: pinned 0071BCA0 leaves both main views inactive with
the PC render selector at zero. Current-branch control: 0 split descriptors,
exit 1; fixed: 2 active views, 2 worlds, 1105+1170 pixels, 3+3 car callbacks,
diag/probe off. Reinstating the inactive-P1 guard fails the same check (exit 1).

The native 0070DD30 fragment is SHA-pinned and executed, with COM calls recorded.
Red on the predecessor: one world/camera, full-height rectangles/projections,
and the second native clear erases P1 (three independent rejected controls).
The frame spy keeps preparation and final dispatch at one invocation; all view
state and ABI results are checked on return to single-player and after resize.
Good: two worlds/cameras, 1105 P1 + 1170 P2 pixels, one full clear; shader owner
control fails on P2; omitted batch drain fails before the next stage.
This fixture explicitly forces the raw-world allocation fallback; native
view-owned captures/post are exercised by private_spliteffects_test.
Raw sky/scenery/model/route/animated stages run in both views; late effects
are refused by the call spy. Full-target shared composition and its final
update run once. Odd-height projection error 5.96046448e-8; predecessor
error .714756966, exit 1. Allocation, missing camera, front end and probe cleanup
also pass. The probe preserves simulation mode 0 and restores the native camera.
GPU: 48/48 direct/replay, 1x/4x configurations pass; ignored-boundary control
rejects 4 configurations with 4096 bad pixels (exit 1).
Vehicles: pinned 007CCA20/007BF7C0 execute both native lists: 3 callbacks per
view (2 ordinary + 1 extra), 0 per view without the vehicle call (exit 1).
Live native menu split: 197.82 simulation seconds, separate cameras/post states,
both worlds drawn without the shifted-camera probe; no hang/stall/failed draw.
Single-player Viper free-roam control reached 73.53 s with no split dispatch
or failed draws; stored-image references cover unchanged single-player rendering.
An actual SP event race remains pending (the five-run game cap was reached).
P2's loaded car passed native culling and submission, but literal blur targets
selected P1's shader camera. private_spliteffects_test pins those native paths
and rejects the original shader-owner and blur-view failures. Live 35 s proof:
run_shots/carbon_native_split_cars_visible.jpg. The original failure remains
run_shots/carbon_native_split_worlds_p2_car_missing.jpg.
"""
from pathlib import Path
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
PRIVATE = HERE / 'private_runtime'
sys.path.insert(0, str(HERE))
import private_picture_03_test as camera

# Main frame body is pinned independently of the production hook implementation.
FRAME_SHA = 'd550100e592e7eca1eb0e989fb84731709ad9b5f22833785011305ad94b98abb'
VEHICLE_SHA = {'007CCA20': 'da731d786b5c0d6a3433787ecb1ef622a550bbf77f1d1d211dd9dd01e16c3ea6', '007BF7C0': 'f3baaf51cd2705cbca542c56de1dad90489c83089e24a584e8cd9caa9e5aeb49'}
WORLD_SHA = '3396db792c5c7e178b2722f8ee62acd5ce85cc9b1c055fe2d3aee8c3699f79c9'
BIND_SHA = '58326850e7dd96f00c89c39c9656d75ed76b194d91bab9ab0bedaeb11b8dde97'
LAYOUT_SHA = '4571d235a97f338e6a6a74f384833b869644d77de2ba8daed8e8614a3839710a'


def fragment(address):
    for path in (HERE / 'out/carbon-base').glob('NFSC_*.c'):
        source = path.read_text()
        match = re.search(r'void (?:f_|carbon_orig_)' + address + r'\(Cpu [^)]*\)\s*\{', source)
        if match:
            result = source[match.start():source.index('\n}', match.end()) + 2]
            return re.sub(r'void (?:f_|carbon_orig_)' + address, 'void native_' + address, result, count=1)
    raise FileNotFoundError('Carbon translated inputs missing')


HARNESS = r'''
#include "host.h"
#include <stdlib.h>
#include "carbon_splitworld.h"
uint8_t *G;
int carbon_spliteffects_begin(uint32_t view){return 0;}
void carbon_spliteffects_end(uint32_t view){}
void carbon_spliteffects_reset(void){}
int diag_on;
void diag_event(const char *fmt, ...) { (void)fmt; }
static unsigned allocations, fail_alloc;
uint32_t galloc(uint32_t n) { if(fail_alloc)return 0; uint32_t p=0x500000+allocations*0x100; ++allocations; memset(G+p,0,n); return p; }
#define CHECK(x) do { if(!(x)){fprintf(stderr,"SPLIT CHECK %d: %s\n",__LINE__,#x);exit(1);} }while(0)
static uint32_t viewport[6], scissor[4], scissor_on;
static unsigned clear_count, submissions, preparations, finishes;
static uint32_t layout_w=65, layout_h=35;
static int native_split;
static uint32_t views[2], cameras[2], rects[2][4];
static unsigned pixels[65*35], pending_draw;
static void flush_pending(void){
    if(!pending_draw)return;
    for(unsigned y=viewport[1];y<viewport[1]+viewport[3];y++)for(unsigned x=viewport[0];x<viewport[0]+viewport[2];x++){
        CHECK(x<65&&y<35);pixels[y*65+x]=pending_draw;
    }
    pending_draw=0;
}
static uint32_t device_call(Cpu *c,uint32_t fn,int n,const uint32_t *a) {
    (void)c;
    if(fn==0xBC){CHECK(n==2);memcpy(viewport,G+a[1],24);}
    else if(fn==0xE4){CHECK(n==3);scissor_on=a[2];}
    else if(fn==0x12C){CHECK(n==2);memcpy(scissor,G+a[1],16);}
    else if(fn==0xAC){
        CHECK(n==7); ++clear_count;
        /* Default SP transport ignores partial viewport: a second full clear
         * is destructive even when both world submissions are otherwise right. */
        for(unsigned i=0;i<65*35;i++)pixels[i]=0;
    }else CHECK(fn==0x94 || fn==0x9C);
    return 0;
}
void native_0070DD30(Cpu *c);
void native_007CCA20(Cpu *c);
static unsigned car_calls[2];
static void body(Cpu *c);
static unsigned stages[2], shared_updates;
uint32_t call_guest(Cpu *c,uint32_t fn,int n,const uint32_t *a){
    if(fn==0x72C9B0){CHECK(!n);flush_pending();return 0;}
    if(fn==0x7CCA20){
        uint32_t sp=c->esp;c->esp-=12;M32(c->esp)=0xFEED;CHECK(n==2&&a[1]==0);
        M32(c->esp+4)=a[0];M32(c->esp+8)=a[1];native_007CCA20(c);CHECK(c->esp==sp-8);c->esp=sp;return 0;
    }
    if(fn==0x70DD30){
        uint32_t sp=c->esp;c->esp-=16;M32(c->esp)=0xFEED;
        CHECK(n==3);for(unsigned i=0;i<3;i++)M32(c->esp+4+4*i)=a[i];
        carbon_splitworld_bind(c,native_0070DD30);c->esp=sp;return 0;
    }
    if(fn==0x71BED0){CHECK(!n);scissor_on=0;return 0;}
    if(fn==0x72E070){CHECK(n==3&&a[1]==1);Cpu fake=*c;fake.esp-=8;M32(fake.esp)=0xFEED;M32(fake.esp+4)=a[0];body(&fake);return 0;}
    if(fn==0x79AFA0){CHECK(n==3&&c->ecx==0x9000&&(a[1]&0x20));CHECK(!pending_draw);stages[a[0]==0xB4B010]|=1;return 0;}
    if(fn==0x79AF60){CHECK(n==1&&c->ecx==0x9000);return 0xABBA;}
    if(fn==0x7D1C40){CHECK(n==2&&a[1]==0xABBA);stages[a[0]==0xB4B010]|=2;return 0;}
    if(fn==0x42ADF0 || fn==0x7A2380){CHECK(n==1);stages[a[0]==0xB4B010]|=fn==0x42ADF0?4:8;return 0;}
    if(fn==0x7F12A0){CHECK(n==1);return 0;}
    if(fn==0x7D2470){CHECK(n==1&&a[0]==0xB4AF90);++shared_updates;return 0;}
    if(fn>=0xF001&&fn<=0xF004){if(fn==0xF001){CHECK(n==3);M32(a[1])=1;}return 0;}
    if(fn==0xF010||fn==0xF014){CHECK(n==0&&c->ecx==0x7000);return 0;}
    if(fn==0x15C){CHECK(n==2);return 0;}
    return device_call(c,fn,n,a);
}
void dispatch(Cpu *c,uint32_t fn){
    if(fn==0xC001 || fn==0xC002){
        uint32_t view=M32(c->esp+4);CHECK(view==0xB4AF90||view==0xB4B010);
        CHECK(M32(M32(0xAB08F4)+4)==M32(view+8));CHECK(viewport[1]==(view==0xB4B010?17:0));
        ++car_calls[view==0xB4B010];c->esp+=fn==0xC001?12:8;return;
    }
    unsigned n=fn==0x94?3:fn==0x9C?2:fn==0xAC?7:fn==0xBC?2:0;
    CHECK(n);uint32_t a[7];for(unsigned i=0;i<n;i++)a[i]=M32(c->esp+4+4*i);
    device_call(c,fn,n,a);c->esp+=4+4*n;
}
void f_0072C9B0(Cpu *c){flush_pending();c->esp+=4;}
BIND_ORIGINAL
CAR_ORIGINALS
LAYOUT_ORIGINAL
void f_007AE270(Cpu *c){CHECK(0);}
void f_005E3D60(Cpu *c){CHECK(0);}
PROVIDER
static void native_layout(Cpu *c){
    uint32_t d=M32(0xB4AF90+0x50);M32(d+0x14)=layout_w;M32(d+0x18)=layout_h;
    if(native_split){native_0071BCA0(c);return;}
    M8(0xB4AF90+0xC)=1;c->esp+=4;
}
static void bind(Cpu *c,uint32_t d){
    uint32_t sp=c->esp;c->esp-=16;M32(c->esp)=0xCAFE;M32(c->esp+4)=d;M32(c->esp+8)=1;M32(c->esp+12)=0;
    carbon_splitworld_bind(c,native_0070DD30);CHECK(c->esp==sp-12);c->esp=sp;
}
static void body(Cpu *c){
    unsigned i=submissions++;CHECK(i<2);uint32_t v=M32(c->esp+4);views[i]=v;cameras[i]=M32(v+0x40);
    bind(c,M32(v+0x50));CHECK(M32(M32(0xAB08F4)+4)==M32(v+8));if(carbon_splitworld_rect(v,NULL)){CHECK(scissor_on);CHECK(scissor[0]==viewport[0]&&scissor[1]==viewport[1]&&scissor[2]==viewport[0]+viewport[2]&&scissor[3]==viewport[1]+viewport[3]);}memcpy(rects[i],viewport,16);
    CHECK(!pending_draw);pending_draw=i+1;
    c->eax=0xACED;c->esp+=4;
}
static void native_frame(Cpu *c){
    ++preparations;uint32_t sp=c->esp;c->esp-=12;M32(c->esp)=0x0072EE41;M32(c->esp+4)=0xB4AF90;M32(c->esp+8)=0x9000;
    carbon_splitworld_submit(c,body);CHECK(c->esp==sp-8&&M32(c->esp)==0xB4AF90&&M32(c->esp+4)==0x9000);c->esp=sp;
    CHECK(M32(0xB4AF90+0x50)==0xAB04EC);
    CHECK(viewport[0]==0&&viewport[1]==0&&viewport[2]==65&&viewport[3]==35&&!scissor_on);
    ++finishes;c->eax=0xFACE;c->esp+=4;
}
static Cpu initial(void){Cpu c={0};c.esp=0x10000;c.ebx=7;c.esi=8;c.edi=9;c.ebp=10;return c;}
int main(int argc,char **argv){
    CHECK(argc==2);G=calloc(1,0xC00000);CHECK(G);
    M32(0xAB0ABC)=0x1000;M32(0x1000)=0x2000;
    M32(0x2000+0x94)=0x94;M32(0x2000+0x9C)=0x9C;M32(0x2000+0xAC)=0xAC;M32(0x2000+0xBC)=0xBC;
    M32(0x2000+0xE4)=0xE4;M32(0x2000+0x12C)=0x12C;
    M32(0xB77DB4)=0x8700;M32(0xB77DBC)=2;M32(0x8700)=0x8000;M32(0x8704)=0x8100;
    M32(0x8000)=M32(0x8100)=0x8200;M32(0x8200+0xC)=0xC001;
    M32(0xAA269C)=0x8600;M32(0xAA26A4)=1;M32(0x8600)=0x8400;M32(0x8400)=0x8500;M32(0x8500+0x50)=0xC002;
    M32(0xB42FEC)=0x7000;M32(0x7000)=0x7100;M32(0x7000+0x44)=0x7200;M32(0x7200)=0x7300;
    M32(0x7100+0x10)=0xF010;M32(0x7100+0x14)=0xF014;M32(0x7300+0xFC)=0xF001;M32(0x7300+0x100)=0xF002;M32(0x7300+0x108)=0xF003;M32(0x7300+0x10C)=0xF004;
    M32(0x2000+0x15C)=0x15C;
    M32(0xAB04EC)=1;M32(0xAB04EC+4)=1;M32(0xAB04EC+8)=111;M32(0xAB04EC+12)=222;
    for(unsigned i=0;i<2;i++){uint32_t v=0xB4AF90+0x80*i;M32(v+8)=i+1;M32(v+0x50)=0xAB04EC;M32(v)=0x300000+i*0x1000;M32(v+0x40)=0x400000+i*0x1000;}
    M32(0xB4D854)=1;M32(0xA99BBC)=6;
    if(!strcmp(argv[1],"native-split")){
        native_split=1;
        M32(0xB4B160)=0x22000;M32(0xB4B0E0)=0x22020;
        unsetenv("BOOT_DIAG_SPLITWORLD");
    }
    if(!strcmp(argv[1],"alloc"))fail_alloc=1;
    if(!strcmp(argv[1],"no-camera"))M32(0xB4B010+0x40)=0;
    if(!strcmp(argv[1],"frontend"))M32(0xA99BBC)=3;
    if(!strcmp(argv[1],"probe")){diag_on=1;setenv("BOOT_DIAG_SPLITWORLD","1",1);M32(0xB4D854)=0;}
    Cpu c=initial();carbon_splitworld_layout(&c,native_layout);CHECK(c.esp==0x10004);
    if(native_split){
        CHECK(!diag_on&&M32(0xB4D854)==1);
        CHECK(carbon_splitworld_rect(0xB4AF90,NULL)&&carbon_splitworld_rect(0xB4B010,NULL));
        CHECK(M8(0xB4AF90+0xC)&&M8(0xB4B010+0xC));
        CHECK(M32(0xB4AF90+0x40)==0x400000&&M32(0xB4B010+0x40)==0x401000);
    }
    if(fail_alloc || !strcmp(argv[1],"no-camera") || !strcmp(argv[1],"frontend")){
        CHECK(!carbon_splitworld_rect(0xB4AF90,NULL));CHECK(M32(0xB4AF90+0x50)==0xAB04EC&&M8(0xB4B010+0xC)==0);
        puts("SPLIT PASS safe fallback");free(G);return 0;
    }
    if(!strcmp(argv[1],"probe")){
        CHECK(M32(0xB4D854)==0&&M32(0xB4B010+0x40)!=0x401000);
        CHECK(MF32(M32(0xB4B010+0x40)+0x30)==-8);
        c=initial();carbon_splitworld_frame(&c,native_frame);CHECK(submissions==2&&clear_count==1);
        diag_on=0;c=initial();carbon_splitworld_layout(&c,native_layout);
        CHECK(M32(0xB4B010+0x40)==0x401000&&!carbon_splitworld_rect(0xB4AF90,NULL));
        puts("SPLIT PASS probe=render-only cameras=2 mode=0 restored=1");free(G);return 0;
    }
    if(!strcmp(argv[1],"rect")){
        uint32_t r[4];CHECK(carbon_splitworld_rect(0xB4AF90,r));CHECK(r[0]==0&&r[1]==0&&r[2]==65&&r[3]==17);
        CHECK(carbon_splitworld_rect(0xB4B010,r));CHECK(r[0]==0&&r[1]==17&&r[2]==65&&r[3]==18);
        CHECK(M32(0xB4AF90+0x50)!=M32(0xB4B010+0x50));CHECK(M32(0xAB04EC+0x18)==35);
    }else if(!strcmp(argv[1],"clear")){
        c=initial();bind(&c,M32(0xB4AF90+0x50));for(unsigned i=0;i<65*17;i++)pixels[i]=7;
        bind(&c,M32(0xB4B010+0x50));for(unsigned i=0;i<65*17;i++)CHECK(pixels[i]==7);
    }else{
        c=initial();carbon_splitworld_frame(&c,native_frame);
        CHECK(preparations==1&&finishes==1&&submissions==2);CHECK(views[0]==0xB4AF90&&views[1]==0xB4B010&&cameras[0]!=cameras[1]);
        CHECK(c.esp==0x10004&&c.eax==0xFACE&&c.ebx==7&&c.esi==8&&c.edi==9&&c.ebp==10);
        CHECK(clear_count==1&&!pending_draw);for(unsigned i=0;i<65*35;i++)CHECK(pixels[i]==(i<65*17?1:2));
        CHECK(rects[0][3]==17&&rects[1][1]==17&&rects[1][3]==18);
        CHECK(stages[0]==15&&stages[1]==15&&shared_updates==1);
        CHECK(car_calls[0]==3&&car_calls[1]==3);
        if(native_split)puts("NATIVE SPLIT PASS diag=0 probe=0 active=2 worlds=2 cars=3+3 pixels=1105+1170 clears=1");
        CHECK(!scissor_on);unsigned allocated=allocations;
        layout_h=37;c=initial();carbon_splitworld_layout(&c,native_layout);CHECK(allocations==allocated);
        uint32_t resized[4];CHECK(carbon_splitworld_rect(0xB4B010,resized)&&resized[1]==18&&resized[3]==19);
        layout_h=1;c=initial();carbon_splitworld_layout(&c,native_layout);CHECK(!carbon_splitworld_rect(0xB4AF90,NULL));
        layout_h=35;c=initial();carbon_splitworld_layout(&c,native_layout);CHECK(allocations==allocated);
        native_split=0;M32(0xB4D854)=0;c=initial();carbon_splitworld_layout(&c,native_layout);
        CHECK(M32(0xB4AF90+0x50)==0xAB04EC&&M32(0xB4B010+0x50)==0xAB04EC&&M8(0xB4B010+0xC)==0);
        CHECK(!carbon_splitworld_rect(0xB4AF90,NULL));submissions=preparations=finishes=0;clear_count=0;
        c=initial();carbon_splitworld_frame(&c,native_frame);CHECK(submissions==1&&preparations==1&&finishes==1&&clear_count==1);
    }
    printf("SPLIT PASS %s submissions=%u clears=%u odd=17+18\n",argv[1],submissions,clear_count);free(G);return 0;
}
'''

BASELINE = r'''
void carbon_splitworld_layout(Cpu *c,void (*original)(Cpu *)){original(c);}
void carbon_splitworld_frame(Cpu *c,void (*original)(Cpu *)){original(c);}
void carbon_splitworld_submit(Cpu *c,void (*original)(Cpu *)){original(c);}
void carbon_splitworld_bind(Cpu *c,void (*original)(Cpu *)){original(c);}
int carbon_splitworld_rect(uint32_t v,uint32_t r[4]){(void)v;(void)r;return 0;}
'''


def compile_run(tmp, text, label, args, expected):
    path = tmp / (label + '.c')
    path.write_text(text)
    exe = path.with_suffix('')
    result = subprocess.run(['clang', '-O1', '-DNFS_GAME=2', '-include', str(ROOT/'runtime/game_select.h'), '-fsanitize=address,undefined', '-I', str(tmp),
                             '-I', str(ROOT / 'runtime'), '-I', str(HERE), str(path), '-o', str(exe)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr[-3000:]
    for arg in args:
        result = subprocess.run([str(exe), arg], capture_output=True, text=True)
        print(label, arg, 'exit=' + str(result.returncode), (result.stdout + result.stderr).strip()[:200], flush=True)
        assert result.returncode == expected, result.stderr[-2000:]



CAMERA_MAIN = r'''
int carbon_splitworld_rect(uint32_t view, uint32_t rect[4]) {
    if (M32(0xB4D854)!=1 || (view!=0xB4AF90 && view!=0xB4B010)) return 0;
    if(rect){rect[0]=0;rect[1]=view==0xB4B010?M32(0xAB0700)/2:0;
        rect[2]=M32(0xAB06FC);rect[3]=view==0xB4B010?M32(0xAB0700)-M32(0xAB0700)/2:M32(0xAB0700)/2;}
    return 1;
}
int main(int argc,char **argv){
    CHECK(argc==2);G=calloc(1,0xC00000);CHECK(G);FILE *f=fopen(argv[1],"rb");CHECK(f&&fread(G,1,0xC00000,f)==0xC00000);fclose(f);
    control_word=0x027F;
    unsigned cases=0;
    for(unsigned height=1079;height<=1081;height++)for(unsigned player=0;player<2;player++){
        unsigned rh=player?height-height/2:height/2;uint32_t view=0xB4AF90+player*0x80;
        M32(0xB4D854)=0;Result reference=build(1,view,player+1,1440,1080,1440,1080,15000);
        M32(0xB4D854)=1;Result r=build(1,view,player+1,1920,height,1920,rh,15000);
        float kx=(4.0f/3.0f)*rh/1920;
        near(r.primary[0],reference.primary[0]*kx);near(r.primary[5],reference.primary[5]);
        near(r.biased[0],reference.biased[0]*kx);near(r.biased[5],reference.biased[5]);
        float norm=sqrtf(r.primary[0]*r.primary[0]+1);
        near(fabsf(r.planes[0]),fabsf(r.primary[0])/norm);near(fabsf(r.planes[2]),1/norm);
        M32(0xB4D854)=0;Result retail=build(0,view,player+1,1920,height,1920,rh,15000);
        near(r.ppu,retail.ppu*kx);++cases;
    }
    printf("SPLIT CAMERA PASS cases=%u odd=539+540,540+541 primary=biased=frustum error=%.9g\n",cases,worst);free(G);return 0;
}
'''


def projection_fixture(tmp, red):
    import recomp
    image = json.loads((HERE/'out/carbon-base/image.json').read_text())
    pe = recomp.PE(image['exe'], expected_sha256=image['sha256'])
    blob = bytearray(0xC00000)
    for name, _, va, size, raw in pe.sections:
        if name.rstrip(b'\0') in (b'.rdata', b'.data'):
            blob[pe.base+va:pe.base+va+size] = pe.data[raw:raw+size]
    (tmp/'guest.bin').write_bytes(blob)
    bodies = '\n'.join(camera.original(a) for a in camera.CAMERA_FRAGMENTS)
    bodies = re.sub(r'native_(?!0071B780)([0-9A-F]{8})', r'f_\1', bodies)
    prototypes = '\n'.join('void f_'+a+'(Cpu *);' for a in
                           ('0044B400','0046DC30','0046DCF0','0070F2A0','0070F2F0','0087EAC0','0086B296'))
    harness = camera.CAMERA_HARNESS.replace('ORIGINALS', prototypes+'\n'+bodies)
    harness = harness[:harness.index('int main(')] + CAMERA_MAIN
    source = (PRIVATE/'game_camera_wide.h').read_text()
    predecessor = re.sub(r'#if defined\(NFS_GAME\) && NFS_GAME == NFS_GAME_PRIVATE\n    uint32_t rect\[4\];.*?#endif\n', '', source, flags=re.S)
    (tmp/'game_camera_wide.h').write_text(predecessor)
    compile_run(tmp,harness,'predecessor-camera',[str(tmp/'guest.bin')],1)
    if not red:
        (tmp/'game_camera_wide.h').write_text(source)
        compile_run(tmp,harness,'good-camera',[str(tmp/'guest.bin')],0)


def main():
    if not (HERE / 'out/carbon-base').is_dir():
        print('SKIP Carbon generated inputs missing'); return 3
    frame = fragment('0072EBA0')
    assert hashlib.sha256(frame.encode()).hexdigest() == FRAME_SHA
    assert frame.count('f_0072E5B0(c);') == 1 and '0xB4AF90u' in frame
    if '--red' not in sys.argv:
        feature = json.loads((PRIVATE/'features/splitworld.json').read_text())
        hooks = json.loads((PRIVATE/'hooks/splitworld.json').read_text())['hooks']
        assert {h['address'] for h in hooks} == {'0071BCA0', '0072E5B0', '0070DD30', '007133C0'}
        for entry in feature['bindings'].values():
            assert hashlib.sha256((PRIVATE/entry['source']).read_bytes()).hexdigest() == entry['sha256']
        hdr = (PRIVATE/'game_hdrclip_init.h').read_text()
        assert 'carbon_splitworld_frame(c, original);' in hdr
        assert hdr.count('carbon_hdr_world_body(c,original)') == 2
    assert hashlib.sha256(fragment('0072E5B0').encode()).hexdigest() == WORLD_SHA
    bind = fragment('0070DD30')
    assert hashlib.sha256(bind.encode()).hexdigest() == BIND_SHA
    layout = fragment('0071BCA0')
    assert hashlib.sha256(layout.encode()).hexdigest() == LAYOUT_SHA
    layout = 'void f_007AE270(Cpu *);\nvoid f_005E3D60(Cpu *);\n' + layout
    with tempfile.TemporaryDirectory(prefix='private-splitworld-') as td:
        tmp = Path(td)
        (tmp / 'carbon_splitworld.h').write_text((PRIVATE / 'carbon_splitworld.h').read_text() if (PRIVATE / 'carbon_splitworld.h').exists() else '')
        good = (PRIVATE / 'carbon_splitworld.c').read_text() if (PRIVATE / 'carbon_splitworld.c').exists() else BASELINE
        cars = 'void f_007BF7C0(Cpu *c);\n'
        for address, digest in VEHICLE_SHA.items():
            f = fragment(address); assert hashlib.sha256(f.encode()).hexdigest() == digest
            cars += f + '\n'
        cars += 'void f_007BF7C0(Cpu *c){native_007BF7C0(c);}'
        harness = HARNESS.replace('BIND_ORIGINAL', bind).replace('CAR_ORIGINALS', cars).replace('LAYOUT_ORIGINAL', layout)
        compile_run(tmp, harness.replace('PROVIDER', BASELINE), 'predecessor', ['world', 'rect', 'clear'], 1)
        projection_fixture(tmp, '--red' in sys.argv)
        if '--red' in sys.argv:
            return 0
        compile_run(tmp, harness.replace('PROVIDER', good), 'good', ['native-split', 'world', 'rect', 'clear', 'alloc', 'no-camera', 'frontend', 'probe'], 0)
        inactive_guard = good.replace('if (!source || (probe && !M8(CS_P1 + 0xC))) return;',
                                      'if (!source || !M8(CS_P1 + 0xC)) return;')
        assert inactive_guard != good
        compile_run(tmp, harness.replace('PROVIDER', inactive_guard), 'inactive-native-view', ['native-split'], 1)
        wrong_owner = good.replace('M32(d + 4) = M32(view + 8);', 'M32(d + 4) = 1;')
        assert wrong_owner != good
        compile_run(tmp, harness.replace('PROVIDER', wrong_owner), 'wrong-owner', ['world'], 1)
        no_vehicles = good.replace('call_guest(c, 0x007CCA20u, 2, vehicles);', '')
        assert no_vehicles != good
        compile_run(tmp, harness.replace('PROVIDER', no_vehicles), 'no-vehicles', ['world'], 1)
        no_drain = good.replace('call_guest(c, 0x0072C9B0u, 0, NULL);', '')
        assert no_drain != good
        compile_run(tmp, harness.replace('PROVIDER', no_drain), 'no-drain', ['world'], 1)
    # The trusted offline tool supplies GPU access, but intentionally strips
    # launcher environment switches. Ask the existing production viewport/clear
    # fixture explicitly for its direct/replay, 1x/4x readback matrix here.
    if os.environ.get('NFS_GPU_SANDBOX') == '1':
        gpu = subprocess.run([sys.executable, '-I', str(ROOT/'runtime/rectangle_clear_test.py')],
                             env={**os.environ, 'CODEX_GPU_CHECK': '1'}, capture_output=True, text=True)
        assert gpu.returncode == 0, (gpu.stdout+gpu.stderr)[-3000:]
        assert 'PASS GPU positive matrix: 48/48 configurations' in gpu.stdout
        assert '4096 total (exit 1)' in gpu.stdout
        for line in gpu.stdout.splitlines():
            if line.startswith('PASS GPU'): print(line, flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
