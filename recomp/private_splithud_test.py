"""Authored split HUD ownership, geometry, clipping and shared/modal transitions.

Red first: the predecessor has no draw scope/clip (992 pixels overwritten).
Premise: the original two-camera probe retains HUD_SingleRace.fng; 007655D0
selects HUD types 3/4 only in a real split race. 005D4B20 chooses the two
authored packages. game_widescreen.h uses AB06FC/AB0700, without a split owner.
Good: 2046 owned pixels, 945 geometry/state/probe checks; omitted clip and wrong
owner both fail the rectangle check. Native updates: P2 speed 52 -> 97 and
lap 2 -> 3, P1's 65536 package bytes unchanged; wrong package fails check 49.
All 292 authored objects classify correctly: 279 owned, 13 shared minimap.
The first native preview rejected missing HUDs; the loader-this control below
now rejects the incorrect resource receiver. Load is scheduled with the region.
Pending batches must drain before restoring ownership/clip (omission fails).
Native load/release fragments also execute, pinning their distinct ABIs.
Live: run_shots/carbon_splithud_owned_probe.jpg, native packages 3/4, odd
rectangles 1440x540 + 1440x541; race message, score and shared map shown.
Guarded split runs reached FePauseMain.fng (opened/resumed),
FePostRaceResults.fng and FeMainMenu.fng, with zero failed draws. A separate
single-player race retained HUD_SingleRace.fng/full-output geometry and reached
results/main. Null audio and rumble off. The canyon event has no live lap
readout: lap routing is covered by the native update fixture below.
The rendering probe mirrors P1 telemetry; independent P2 values are tested
above, and a real two-player finish remains part of the split-flow job.
Private assets are read in memory, never modified. Exit 3 without them.
"""
from pathlib import Path
import hashlib
import json
import re
import struct
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
PRIVATE = HERE / 'private_runtime'
sys.path.insert(0, str(HERE))

HARNESS = r'''
#include "host.h"
#include <stdlib.h>
#include <math.h>
uint8_t *G;
static unsigned checks, calls, drains, sets;
static unsigned pending_owner;
static unsigned probe_calls,probe_updates,probe_deleted,probe_released,probe_failed;
static int split=1, notch;
static uint32_t width=65,height=35;
static uint32_t scissor[4]={2,1,64,34}, enabled=1;
int diag_on;
void diag_event(const char *fmt,...){(void)fmt;}
void carbon_worldmap_art_draw(Cpu*c,void(*original)(Cpu*)){original(c);}
uint32_t galloc(uint32_t n){(void)n;return 0x100000;}
float carbon_fe_kx(void){return notch?.75f:width*3>height*4?(4.f/3)*height/width:1.f;}
float carbon_fe_ky(void){return notch?.87f:1.f;}
int carbon_splitworld_rect(uint32_t view,uint32_t r[4]){
 if(!split || (view!=0xB4AF90 && view!=0xB4B010))return 0;
 if(r){r[0]=0;r[1]=view==0xB4AF90?0:height/2;r[2]=width;r[3]=view==0xB4AF90?height/2:height-height/2;}return 1;
}
#define CHECK(x) do{++checks;if(!(x)){fprintf(stderr,"HUD CHECK %u line=%d %s\n",checks,__LINE__,#x);exit(1);}}while(0)
void native_006B5910(Cpu*c);void native_006B7BE0(Cpu*c);
static void flush_pending(void);
static void resource_call(Cpu*c,uint32_t fn,int n,const uint32_t*a){
 uint32_t sp=c->esp;c->esp-=4*(n+1);M32(c->esp)=0xFEED;
 for(int i=0;i<n;i++)M32(c->esp+4+4*i)=a[i];
 if(fn==0x6B5910){native_006B5910(c);CHECK(c->esp==sp);}
 else{native_006B7BE0(c);CHECK(c->esp==sp-4);CHECK(M32(0x76000)==0x76000&&M32(0x76004)==0x76000);}
 c->esp=sp;
}
uint32_t call_guest(Cpu *c,uint32_t fn,int n,const uint32_t*a){
 (void)c;
 if(fn==0x72C9B0){CHECK(!n);flush_pending();++drains;return 0;}
 if(fn==0x6B32C0){CHECK(n==5&&a[0]==0x9E37A4&&a[1]==3);M32(0x75000)=M32(0x75004)=0x76000;M32(0x75030)=1;++probe_calls;return 0x75000;}
 if(fn==0x6B5910){CHECK(c->ecx==0x75000&&n==2&&!a[0]&&!a[1]);resource_call(c,fn,n,a);++probe_calls;return 0;}
 if(fn==0x6A1560){CHECK(n==1&&a[0]==0x348);++probe_calls;return probe_failed?0:0x72000;}
 if(fn==0x5E7B90){CHECK(n==4&&a[0]==4&&a[1]==0x9D6110&&a[2]==0x70000&&a[3]==1&&c->ecx==0x72000);++probe_calls;return 0x72000;}
 if(fn==0x5E6F70){CHECK(n==2&&a[0]==0x70000&&a[1]==0x3C888889&&c->ecx==0x72000);++probe_updates;return 0;}
 if(fn==0x5E6EE0){CHECK(!n&&c->ecx==0x72000);++probe_deleted;return 0;}
 if(fn==0x6B7BE0){CHECK(n==1&&a[0]==0x75000&&!M32(0x70000+0x28));resource_call(c,fn,n,a);++probe_released;return 0;}
 CHECK(n>=2&&a[0]==0x8000);
 if(fn==0x130){memcpy(G+a[1],scissor,16);}
 else if(fn==0xE8){CHECK(n==3&&a[1]==174);M32(a[2])=enabled;}
 else if(fn==0x12C){memcpy(scissor,G+a[1],16);++sets;}
 else if(fn==0xE4){CHECK(n==3&&a[1]==174);enabled=a[2];}
 else CHECK(0);
 return 0;
}
void f_00699660(Cpu*c){CHECK(c->ecx==0x75000);c->esp+=8;}
void f_006B48B0(Cpu*c){(void)c;CHECK(0);}
void f_006A84E0(Cpu*c){CHECK(c->ecx==0x75000);c->esp+=4;}
void f_006B68D0(Cpu*c){(void)c;CHECK(0);}
void f_0046F420(Cpu*c){CHECK(arg(c,1)==0x75000);c->esp+=4;}
RESOURCE_FRAGMENTS
PROVIDER
static int carbon_fe_scope=1;
static void shader_matrix(Cpu*c,float m[16]){
 struct {const char*name;}param={"WorldViewProj"},*q=&param;
 MATRIX
}
static void fixed_matrix(float vsc[8][4]){
 FIXED
}
typedef struct {const char *name;int in_pass;} Effect;
static Effect fakefx={"IDI_FE_FX",1};
static char diag_fx_pass[128];
#define FX (&fakefx)
#define D3D_OK 0
END_PASS
static void begin(const char*name){
 Effect *fx=&fakefx;fx->name=name;fx->in_pass=1;
 BEGIN_PASS
}
static int want_owner;
static uint32_t pixels[65*35];
static void paint(unsigned owner){
 for(unsigned y=0;y<height&&height==35;y++)for(unsigned x=0;x<width;x++)
  if(!enabled||(x>=scissor[0]&&x<scissor[2]&&y>=scissor[1]&&y<scissor[3]))pixels[y*width+x]=owner;
}
static void flush_pending(void){
 if(!pending_owner)return;
 float t[4];CHECK(carbon_splithud_transform(t));paint(pending_owner);pending_owner=0;
}
static void draw(Cpu*c){
 ++calls;float t[4];
 begin("IDI_FE_MASK_FX");CHECK(carbon_fe_scope);
 int own=carbon_splithud_transform(t);
#ifndef PREDECESSOR
 CHECK(own==(want_owner!=0));
#endif
 if(own){
  uint32_t r[4];carbon_splitworld_rect(want_owner==1?0xB4AF90:0xB4B010,r);
  CHECK(enabled);CHECK(scissor[1]>=r[1]&&scissor[3]<=r[1]+r[3]);
  float centre=want_owner==1?.5f:-.5f;
  float py=(1-(centre*t[1]+t[3]))*height*.5f;
  CHECK(fabsf(py-(r[1]+r[3]*.5f))<.001f);
  float m[16]={0},vsc[8][4]={{0}};
  for(int k=0;k<4;k++)m[k*4+k]=vsc[k][k]=1;
  shader_matrix(c,m);fixed_matrix(vsc);
  CHECK(m[0]==t[0]&&m[5]==t[1]&&m[12]==t[2]&&m[13]==t[3]);
  for(int k=0;k<4;k++)for(int j=0;j<4;j++)CHECK(m[k*4+j]==vsc[j][k]);
  if(width==1920){CHECK(fabsf(m[0]-.75f)<1e-6f);CHECK(fabsf(m[5]-1)<1e-6f);}
  if(width==3456){
   float top=(1-(m[5]*(want_owner==1?1.f:0.f)+m[13]))*height*.5f;
   float bottom=(1-(m[5]*(want_owner==1?0.f:-1.f)+m[13]))*height*.5f;
   CHECK(fabsf(top-(want_owner==1?72.5f:1189.5f))<.001f);
   CHECK(fabsf(bottom-(want_owner==1?1044.5f:2161.5f))<.001f);
  }
 }
 if(want_owner){
  /* Oversized message/mask primitive: only the scissor can contain it. */
#ifdef PREDECESSOR
  paint(want_owner);
#else
  CHECK(!pending_owner);pending_owner=want_owner;
#endif
 }
 if(!own){
  float m[16],expected[16],vsc[8][4]={{0}};
  for(int k=0;k<16;k++)m[k]=expected[k]=(k+1)*.17f;
  for(int k=0;k<4;k++){
   expected[k*4]*=carbon_fe_kx();expected[k*4+1]*=carbon_fe_ky();
   for(int j=0;j<4;j++)vsc[j][k]=m[k*4+j];
  }
  shader_matrix(c,m);fixed_matrix(vsc);CHECK(!memcmp(m,expected,sizeof m));
  for(int k=0;k<4;k++)for(int j=0;j<4;j++)CHECK(vsc[j][k]==expected[k*4+j]);
 }
 Cpu end=*c;CHECK(e_EndPass(&end)&&end.eax==0&&end.esp==c->esp+8);CHECK(!carbon_fe_scope);
 CHECK(carbon_splithud_transform(t)==own);
 begin("IDI_FE_FX");CHECK(carbon_fe_scope);begin("IDI_WORLD_FX");CHECK(!carbon_fe_scope);
 c->eax=0xCAFE;c->esp+=8;
}
static void invoke(Cpu*c,uint32_t pkg,uint32_t object,int owner){
 M32(0xA97B2C)=pkg;M32(c->esp+4)=object;Cpu expected=*c;expected.eax=0xCAFE;expected.esp+=8;
 uint32_t saved[4];memcpy(saved,scissor,16);uint32_t on=enabled;want_owner=owner;
 carbon_splithud_draw(c,draw);
 CHECK(!pending_owner);
 CHECK(!memcmp(c,&expected,sizeof *c));CHECK(!memcmp(scissor,saved,16)&&enabled==on);
 float t[4];CHECK(!carbon_splithud_transform(t));
 c->esp-=8;
}
static unsigned expect_type;
static void native_load(Cpu*c){c->eax=0x1234;c->esp+=4;}
static void native_type(Cpu*c){CHECK(arg(c,0)==expect_type);M32(c->ecx+0x28)=0x71000;M32(c->ecx+0x4C)=expect_type;c->eax=0x1234;c->esp+=8;}
static void native_update(Cpu*c){CHECK(c->ecx==0x71000);c->eax=0x5678;c->esp+=12;}
static void native_destroy(Cpu*c){CHECK(probe_deleted||probe_failed);M32(c->ecx+0x28)=0;c->eax=0x8765;c->esp+=4;}
static void probe_check(void){
 Cpu c={0};c.esp=0x10000;c.ecx=0x70000;M32(c.esp+4)=1;expect_type=1;
 setenv("BOOT_DIAG_SPLITWORLD","1",1);
 carbon_splithud_probe_type(&c,native_type);CHECK(c.eax==0x1234&&c.esp==0x10008&&!probe_calls);
 c.esp=0x10000;M32(c.esp+4)=1;diag_on=1;M32(0xB4D854)=1;
 carbon_splithud_probe_type(&c,native_type);CHECK(!probe_calls);
 c.esp=0x10000;M32(c.esp+4)=1;M32(0xB4D854)=0;expect_type=3;
 carbon_splithud_probe_load(&c,native_load);CHECK(c.eax==0x1234&&c.esp==0x10004&&probe_calls==2);c.esp=0x10000;
 carbon_splithud_probe_type(&c,native_type);CHECK(c.eax==0x1234&&c.esp==0x10008&&M32(0x10004)==1&&probe_calls==4);
 c.esp=0x10000;c.ecx=0x71000;M32(c.esp+4)=0x70000;M32(c.esp+8)=0x3C888889;
 carbon_splithud_probe_update(&c,native_update);CHECK(c.eax==0x5678&&c.esp==0x1000C&&probe_updates==1);
 c.esp=0x10000;c.ecx=0x70000;
 carbon_splithud_probe_destroy(&c,native_destroy);CHECK(c.eax==0x8765&&c.esp==0x10004&&probe_deleted==1&&probe_released==1);
 probe_failed=1;c.esp=0x10000;M32(c.esp+4)=1;
 carbon_splithud_probe_load(&c,native_load);c.esp=0x10000;
 carbon_splithud_probe_type(&c,native_type);CHECK(probe_calls==7);
 c.esp=0x10000;carbon_splithud_probe_destroy(&c,native_destroy);CHECK(probe_deleted==1&&probe_released==2);
 unsetenv("BOOT_DIAG_SPLITWORLD");diag_on=0;
}
int main(int argc,char**argv){
 G=calloc(1,0xC00000);CHECK(G);Cpu c={0};c.esp=0x10000;
 M32(0xAB0ABC)=0x8000;M32(0x8000)=0x8100;
 for(unsigned i=0;i<0x140;i+=4)M32(0x8100+i)=i;
 M32(0xA99BBC)=6;M32(0xAB06FC)=width;M32(0xAB0700)=height;
 strcpy((char*)G+0x20000,"HUD_Player1.fng");strcpy((char*)G+0x20100,"HUD_Player2.fng");
 M32(0x30000+0xC)=0x20000;M32(0x31000+0xC)=0x20100;
 M32(0x30000+0x4C)=0x40000;M32(0x40000+0x18)=5;M32(0x40000+0x10)=0xF365871;
 M32(0x40000+0x64)=0x41000;
 M32(0x40000+4)=0x44000;M32(0x44000+0x18)=5;M32(0x44000+0x10)=0xA1A862;
 M32(0x44000+0x64)=0x45000;M32(0x45000+0x10)=0x572181E6;
 /* One native shared map child, one owned speed/lap/message object. */
 invoke(&c,0x30000,0x42000,1);invoke(&c,0x31000,0x43000,2);
 unsigned bad_pixels=0;
 for(unsigned y=0;y<height;y++)for(unsigned x=0;x<width;x++){
  unsigned expected=x>=2&&x<64&&y>=1&&y<34?(y<height/2?1:2):0;
  bad_pixels+=pixels[y*width+x]!=expected;
 }
 printf("HUD pixels wrong=%u expected=0\n",bad_pixels);CHECK(!bad_pixels);
 invoke(&c,0x30000,0x41000,0);
 invoke(&c,0x30000,0x45000,0);
 for(const char**n=(const char*[]){"FePauseMain.fng","FePostRaceResults.fng","FeSmsMessage.fng","InGameDialog.fng",NULL};*n;n++){
  strcpy((char*)G+0x20200,*n);M32(0x32000+0xC)=0x20200;invoke(&c,0x32000,0x42000,0);
 }
 split=0;unsigned before=sets;invoke(&c,0x30000,0x42000,0);CHECK(sets==before);
 split=1;M32(0xA99BBC)=3;invoke(&c,0x31000,0x43000,0);CHECK(sets==before);M32(0xA99BBC)=6;
 for(unsigned i=0;i<3;i++){
  width=i==0?1440:i==1?1920:3456;height=i==0?1081:i==1?1080:2234;notch=i==2;
  M32(0xAB06FC)=width;M32(0xAB0700)=height;
  enabled=0;
  /* Disable pixel rasterization for large geometry-only outputs. */
  invoke(&c,0x30000,0x42000,1);invoke(&c,0x31000,0x43000,2);
 }
#ifndef PREDECESSOR
 CHECK(argc==2);FILE*f=fopen(argv[1],"rb");CHECK(f);uint8_t*asset=malloc(0xC00000);CHECK(asset&&fread(asset,1,0xC00000,f)==0xC00000);fclose(f);
 memcpy(G+0x60000,asset+0x60000,0x20000);
 unsigned classified=0,shared=0;
 for(unsigned p=0;p<2;p++){
  uint32_t root;memcpy(&root,asset+0x30000+p*0x1000+0x4C,4);
  for(unsigned i=0;i<(p?140:152);i++){
   unsigned left=512;uint32_t o=0x60000+p*0x10000+i*0x100;
   int actual=hud_map_member(root,o,0,&left);CHECK(actual==(int)M32(o+0x84));shared+=actual;++classified;
  }
 }
 printf("HUD authored owners=%u shared_minimap_objects=%u mismatches=0\n",classified,shared);free(asset);
 probe_check();
#endif
 printf("HUD PASS checks=%u owned_pixels=2046 calls=%u drains=%u state_restored=1 probe_released=%u\n",checks,calls,drains,probe_released);
 free(G);return 0;
}
'''

BASELINE = '''
int carbon_splithud_transform(float t[4]){(void)t;return 0;}
void carbon_splithud_clip(Cpu*c){(void)c;}
void carbon_splithud_draw(Cpu*c,void(*original)(Cpu*)){original(c);}
void carbon_splithud_probe_type(Cpu*c,void(*original)(Cpu*)){original(c);}
void carbon_splithud_probe_load(Cpu*c,void(*original)(Cpu*)){original(c);}
void carbon_splithud_probe_update(Cpu*c,void(*original)(Cpu*)){original(c);}
void carbon_splithud_probe_destroy(Cpu*c,void(*original)(Cpu*)){original(c);}
'''

FRAGMENTS = {
    '005DA340': 'bdc481203a0caa553aa095cde50f6579bb319e1b7212771e1308c2c72574279f',
    '005DAA30': '09e50dfbd40749935eeb5fb83ed5e5e7d534914d3c445434d5b651c88f690ed0',
    '006B5910': '5fccaaeb112bc0a7db767d8d88ffbc03ab859c9347d08199e4a33effcdca116c',
    '006B7BE0': '850023e4f2a344bae9db1051a0af89e03bcc0d724d3ad504a4220e6d324d2697',
}


def native_fragments(addresses):
    found = {}
    for path in (HERE/'out/carbon-base').glob('NFSC_*.c'):
        source = path.read_text()
        for address, digest in FRAGMENTS.items():
            match = re.search(r'void (?:f_|carbon_orig_)'+address+r'\(Cpu [^)]*\)\s*\{', source)
            if match:
                text = source[match.start():source.index('\n}', match.end())+2]
                text = re.sub(r'void (?:f_|carbon_orig_)'+address, 'void native_'+address, text, count=1)
                assert hashlib.sha256(text.encode()).hexdigest() == digest, address
                found[address] = text
    assert set(found) == set(FRAGMENTS)
    return '\n'.join(found[a] for a in addresses)


DATA = r'''
#include "host.h"
#include <stdlib.h>
#include <math.h>
uint8_t *G;
static float speeds[2]={38,52};static unsigned laps[2]={1,2};
static unsigned checks,writes[2],target_player;
#define CHECK(x) do{++checks;if(!(x)){fprintf(stderr,"HUD DATA CHECK %u line=%d %s\n",checks,__LINE__,#x);exit(1);}}while(0)
static uint32_t value(uint32_t hash,unsigned player){
 if(hash==0x7E1)return 3;
 if(hash==0xBBF)return 3;
 if(hash==0x41C)return laps[player];
 if(hash==0x41A||hash==0x41F)return player+1;
 if(hash==0xBC1)return 2;
 return 0;
}
void f_004A0490(Cpu*c){uint32_t h=arg(c,0),p=arg(c,2);M32(arg(c,1))=value(h,p<2?p:0);c->eax=1;c->esp+=24;}
void f_004A0350(Cpu*c){uint32_t h=arg(c,0),p=arg(c,2);MF32(arg(c,1))=h==2000?speeds[p<2?p:0]:h==0x7D2?3000:h==0x7D3?7000:0;c->eax=1;c->esp+=24;}
void f_005910E0(Cpu*c){
 uint32_t o=arg(c,0);if(!o){c->esp+=4;return;}CHECK(o>=0x60000&&o<0x80000);
 unsigned p=(o-0x60000)/0x10000;CHECK(p==target_player);++writes[p];
 if(arg(c,1)==0x9C34DC)M32(o+0x80)=arg(c,2);
 c->esp+=4;
}
void dispatch(Cpu*c,uint32_t t){if(t!=0xF001)fprintf(stderr,"unexpected dispatch %08X this=%08X caller=%08X\n",t,c->ecx,M32(c->esp));CHECK(t==0xF001);c->eax=M32(c->ecx+4);c->esp+=4;}
void f_0087EAC0(Cpu*c){c->eax=(uint32_t)(int32_t)ST(0);x87_pop(c);c->esp+=4;}
void f_005D3880(Cpu*c){c->eax=0;c->esp+=8;}
void f_005D3910(Cpu*c){c->esp+=8;}
void f_00570460(Cpu*c){c->esp+=4;}
void f_005704A0(Cpu*c){c->esp+=4;}
void f_00570500(Cpu*c){c->eax=1;c->esp+=4;}
void f_00570790(Cpu*c){c->esp+=4;}
void f_00570CC0(Cpu*c){c->esp+=4;}
void f_00578830(Cpu*c){c->eax=0;c->esp+=4;}
void f_004ABFD0(Cpu*c){c->esp+=8;}
void f_006A2CA0(Cpu*c){c->esp+=12;}
void f_00475C30(Cpu*c){c->esp+=4;}
void f_00401050(Cpu*c){c->esp+=4;}
FRAGMENTS
static void update(unsigned p){
 target_player=p;Cpu c={0};c.esp=0x10000;c.ecx=0x50000+p*0x1000;
 M32(c.esp+4)=0x90000+p*0x100;native_005DA340(&c);CHECK(c.esp==0x10008);
 c.esp=0x10000;c.ecx=0x52000+p*0x1000;M32(c.esp+4)=0x90000+p*0x100;native_005DAA30(&c);CHECK(c.esp==0x10008);
}
int main(int argc,char**argv){
 CHECK(argc==2);G=malloc(0xC00000);CHECK(G);FILE*f=fopen(argv[1],"rb");CHECK(f&&fread(G,1,0xC00000,f)==0xC00000);fclose(f);
 update(0);update(1);uint8_t saved[0x10000];memcpy(saved,G+0x60000,sizeof saved);
 unsigned prior=writes[0];speeds[1]=97;laps[1]=3;update(1);
 CHECK(writes[0]==prior&&!memcmp(saved,G+0x60000,sizeof saved));
 CHECK(M32(M32(0x51000+0x44)+0x80)==0);CHECK(M32(M32(0x51000+0x40)+0x80)==9);CHECK(M32(M32(0x51000+0x3C)+0x80)==7);
 CHECK(M32(M32(0x53000+0x30)+0x80)==3);
 printf("HUD DATA PASS P2 speed=97 lap=3 P1_bytes_unchanged=65536 writes=%u/%u checks=%u\n",writes[0],writes[1],checks);
 free(G);return 0;
}
'''


def assets():
    image = HERE/'out/carbon-base/image.json'
    if not image.exists():
        return None
    exe = Path(json.loads(image.read_text())['exe'])
    bundle = exe.parent/'GLOBAL/InGameSplitScreen.bun'
    if not exe.is_file() or not bundle.is_file():
        return None
    sys.path.insert(0, str(ROOT/'tools_snapshot/worldmerge'))
    import frontend as f
    from recomp import PE
    pe = PE(str(exe), expected_sha256='baaaaec33873d4ba7e4dbae6a5212049ffdcf9679a35d865d7625b4189952fd3')
    memory = bytearray(0xC00000)
    for _, size, va, raw_size, _ in pe.sections:
        if va+pe.base < len(memory):
            data = pe.read(pe.base+va, min(size, raw_size))
            if data is not None:
                memory[pe.base+va:pe.base+va+len(data)] = data
    packages = []
    for chunk in f.chunks(bundle.read_bytes()):
        if chunk.kind == 0x30210:
            raw = f.xt.jdlz(chunk.payload, 4)
            packages.append((raw, f.objects(raw)[2]))
    assert [len(rows) for _, rows in packages] == [152, 140]
    for p, (raw, rows) in enumerate(packages):
        assert raw[0x28:0x38].split(b'\0')[0] == f'HUD_Player{p+1}.fng'.encode()
        by_hash = {f.u32(row, 0x1C): 0x60000+p*0x10000+i*0x100 for i,row in enumerate(rows)}
        assert (0x0F365871 in by_hash) == (p == 0), 'authored shared minimap'
        assert (0x00A1A862 in by_hash) == (p == 0), 'authored custom minimap root'
        if p == 0:
            custom = next(row for row in rows if f.u32(row,0x1C)==0x572181E6)
            parent = next(row for row in rows if f.u32(row,0x24)==f.u32(custom,0x38))
            assert f.u32(parent,0x1C)==0x00A1A862
        def put(a, v):
            struct.pack_into('<I', memory, a, v)
        for i,row in enumerate(rows):
            o = 0x60000+p*0x10000+i*0x100
            put(o+0x10,f.u32(row,0x1C));put(o+0x18,f.u32(row,0x14))
        by_id = {f.u32(row,0x24):row for row in rows}
        siblings = {}
        for row in rows:
            parent = f.u32(row,0x38) if row[0x34:0x38]==b'PA\4\0' else 0
            siblings.setdefault(parent,[]).append(row)
            ancestors = [row]
            while parent:
                ancestors.append(by_id[parent])
                parent_row=by_id[parent]
                parent=f.u32(parent_row,0x38) if parent_row[0x34:0x38]==b'PA\4\0' else 0
            shared = p==0 and any(f.u32(a,0x1C) in (0x0F365871,0x00A1A862) for a in ancestors)
            put(by_hash[f.u32(row,0x1C)]+0x84,int(shared))
        for parent,group in siblings.items():
            head=by_hash[f.u32(group[0],0x1C)]
            put(by_hash[f.u32(by_id[parent],0x1C)]+0x64 if parent else 0x30000+p*0x1000+0x4C,head)
            for a,b in zip(group,group[1:]):
                put(by_hash[f.u32(a,0x1C)]+4,by_hash[f.u32(b,0x1C)])
        speed = 0x50000+p*0x1000
        for offset,name in ((0x3C,'SPEED_DIGIT_1'),(0x40,'SPEED_DIGIT_2'),(0x44,'SPEED_DIGIT_3')):
            put(speed+offset,by_hash[f.name_hash(name)])
        # Remaining strings are independently bound to the same authored package.
        for offset,name in ((0x28,'MAIN_RPM_METER'),(0x48,'KMH_GROUP')):
            put(speed+offset,by_hash.get(f.name_hash(name),0))
        # Native 005E5FD0 binds these seven stat/lap fields in this order.
        hashes = [0x30D9802E,0x44EB106B,0x864ED45E,0x0F84EB22,0xA390C1C2,
                  f.name_hash('POSITION_TEXT'),f.name_hash('RACERNUMBERS')]
        for offset,h in zip(range(0x28,0x44,4),hashes):
            put(0x52000+p*0x1000+offset,by_hash[h])
        root = next(row for row in rows if f.u32(row,0x1C)==0x5D0101F1)
        sad = root.index(b'SAD\0')
        assert struct.unpack_from('<3f',root,sad+32) == (209.,49. if p==0 else 276.,130.)
        put(0x90000+p*0x100,0x90200);put(0x90000+p*0x100+4,p);put(0x90200+0x1C,0xF001)
    return memory


def command(args, expected=0):
    r = subprocess.run(list(map(str, args)), capture_output=True, text=True, timeout=120)
    assert r.returncode == expected, (args[:3], r.returncode, r.stdout[-1500:], r.stderr[-2500:])
    return r.stdout.strip() + r.stderr.strip()


def main():
    memory = assets()
    if memory is None:
        print('SKIP: split HUD checks need the private image and authored packages')
        return 3
    source = PRIVATE / 'carbon_splithud.c'
    if '--red' in sys.argv:
        variants = {'predecessor': BASELINE}
    else:
        assert source.exists(), 'missing per-package HUD scope (predecessor)'
        feature = json.loads((PRIVATE/'features/splithud.json').read_text())
        for name, row in feature['bindings'].items():
            assert row['sha256'] == hashlib.sha256((PRIVATE/name).read_bytes()).hexdigest()
        hooks = json.loads((PRIVATE/'hooks/splithud.json').read_text())
        assert {row['provider'] for row in hooks['hooks']} == {
            'carbon_splithud_probe_type','carbon_splithud_probe_load','carbon_splithud_probe_update','carbon_splithud_probe_destroy'}
        shared_hook = json.loads((PRIVATE/'hooks/worldmap_art.json').read_text())
        assert shared_hook['hooks'][0]['provider'] == 'carbon_splithud_draw'
        provider = source.read_text()
        wrong = provider.replace('!strcmp(text, "HUD_Player2.fng") ? 2 : 0',
                                 '!strcmp(text, "HUD_Player2.fng") ? 1 : 0')
        noclip = provider.replace('carbon_splithud_clip(c);', '(void)c;')
        assert wrong != provider and noclip != provider
        variants = {'good': provider, 'predecessor': BASELINE,
                    'wrong-owner': wrong, 'missing-clip': noclip,
                    'wrong-loader-this': provider.replace('work.ecx = probe_bundle;', 'work.ecx = 0;'),
                    'wrong-release-abi': provider.replace('call_guest(&work, 0x006B7BE0u, 1, &bundle);',
                                                         'work.ecx=bundle;call_guest(&work, 0x006B7BE0u, 0, NULL);'),
                    'missing-batch-drain': provider.replace('carbon_worldmap_art_draw(c, original);\n    hud_drain(c);',
                                                           'carbon_worldmap_art_draw(c, original);')}
    with tempfile.TemporaryDirectory(prefix='private-splithud-') as td:
        out = Path(td)
        image = out/'image.bin'
        image.write_bytes(memory)
        resource_source = native_fragments(('006B5910','006B7BE0'))
        for name, provider in variants.items():
            path = out / 'test.c'
            source = HARNESS.replace('PROVIDER', provider)
            source = source.replace('RESOURCE_FRAGMENTS', resource_source)
            source = source.replace('MATRIX', (PRIVATE/'game_frontend_matrix.h').read_text())
            source = source.replace('FIXED', (PRIVATE/'game_frontend_clip.h').read_text())
            source = source.replace('END_PASS', (PRIVATE/'game_frontend_end.h').read_text())
            source = source.replace('BEGIN_PASS', (PRIVATE/'game_frontend_begin.h').read_text())
            path.write_text(source)
            command(['clang', '-O1', '-g', '-DNFS_GAME=2',
                     *(['-DPREDECESSOR'] if name=='predecessor' else []), '-include', ROOT/'runtime/game_select.h',
                     '-fsanitize=address,undefined', '-I', ROOT/'runtime', '-I', HERE, '-I', PRIVATE,
                     path, '-o', out/'test'])
            print(name + ': ' + command([out/'test', image], 0 if name == 'good' else 1))
        if '--red' not in sys.argv:
            source = DATA.replace('FRAGMENTS', native_fragments(('005DA340','005DAA30')))
            path.write_text(source)
            command(['clang', '-O1', '-g', '-fsanitize=address,undefined',
                     '-I', ROOT/'runtime', '-I', HERE, path, '-o', out/'data'])
            image.write_bytes(memory)
            print(command([out/'data', image]))
            for offset in (0x3C,0x40,0x44):
                struct.pack_into('<I', memory,0x51000+offset,struct.unpack_from('<I', memory,0x50000+offset)[0])
            image.write_bytes(memory)
            print('wrong-data-package: ' + command([out/'data', image], 1))
    return 0


if __name__ == '__main__':
    sys.exit(main())
