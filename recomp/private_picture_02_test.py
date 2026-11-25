"""Native modes and AA through translated originals, no game/GPU.

First-run quality: prior startup fragment exit=1; AA-Off mutant exit=1; good exit=0.
Twelve fields, full/lower caps, saved profile, BOOT_REG and process restart covered.
First-run display selection: old-code exit=1; smallest-slot mutant exit=1; good exit=0.
3840x2160 -> slot4; 5120x2880 -> slot4; 3456x2234 -> slot3 Off / slot5 On;
saved slot2 unchanged. Notch first-launch slot survives native save/reload.
Fresh marker-only, saved without marker, BOOT_REG and second-process persistence covered.
Six legacy slots / zero HD targets -> six valid slots / two HD targets.
Good exit=0; unwritten sixth slot exit=1; F10 omits g_FSAALevel write exit=1.
Unbound native registry key exit=1; original key accepted=0 / bound key=1.
ASCII resolution/AA label mutants exit=1 each; native UTF-16 setter good=0.
AA diagnostic actual=2 / requested=4: good exit=0, requested-count mutant exit=1;
changed-only snapshots use the live getter and keep the cached row at it, so a
later dump records it (restart run: kept=4x; old restore=Off, checker exit 1).
Reloading the startup FirstTime marker: good launch classification=0;
broken repeated hardware-detection flag=1, fixture exit=1.
Off/2x/4x native, F10, requested and present samples: 0/1, 1/2, 2/4.
Fragments are SHA-256 pinned independently of the hook registry. Exit 3 without
Carbon generated outputs. Also checks game_display_settings.h,
game_display_modes.h, game_display_aa.h, game_display_bindings.h,
game_mode_provider.h, game_first_resolution.h, features/picture_02.json and hooks/picture_02.json.
First-device premise: 00A65388 starts 00000000; 00712ADD bytes
c70080020000c701e0010000 output 640/480. Later 0071D0A0 hardware
detection applies 007115D0 preset2 -> slot1, AA0, then 00711BD0 saves.
Premise witnesses: 00712AC0 a18853a60083f805 reads the six-slot index;
004A525F 83f802 caps the native AA cycler at two. The image's width/height
arrays at 00A63E28/00A63E40 decode to the six legacy pairs asserted below.
Decompile NFSC_006f7580.c:14018-14036 builds MSAA type/quality at 00710100;
15062 and 15175 load/save g_FSAALevel. NFSC_004a3620.c:1797-1812 cycles AA.
Before this change game_display_aa.h:1-2 returned zero/did nothing;
private_resolution.py:13 lists the retained override and three FE witnesses.
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
SETTINGS_ROWS = {'graphics.antialiasing': {'get': 'aa_game_get', 'apply': 'aa_game_apply'}}
SETTINGS_PROVIDERS = {'aa_game_get': 'game_display_aa.h', 'aa_game_apply': 'game_display_aa.h'}
SETTINGS_FIXTURE = r'''
#include <stdlib.h>
int aa_game_get(void) { return 0; }
void aa_game_apply(int v) { (void)v; }
int carbon_aa_levels(void) { return 2; }
void user32_display_pixels(int *w,int *h) { *w=3024; *h=1896; }
int private_carbon_resolution_active(void) { return 0; }
void private_carbon_resolution_write(uint32_t w,uint32_t h) { (void)w;(void)h; }
uint32_t galloc(uint32_t n) { (void)n; return 0; }
uint32_t gstr(const char *s) { (void)s; return 0; }
uint32_t call_guest(Cpu *c,uint32_t fn,int n,const uint32_t *a) { (void)c;(void)fn;(void)n;(void)a;return 0; }
void host_import(Cpu *c, uint32_t slot) { (void)c; (void)slot; abort(); }
void boot_reg_set_dword(const char *name, uint32_t value) { (void)name; (void)value; abort(); }
uint8_t *G;
'''

# Main startup enumeration fragment before first-run selection.
OLD_ENUMERATE = 'void carbon_mode_enumerate(Cpu *c, void (*original)(Cpu *)) {\n    carbon_modes_publish();\n    original(c);\n    M32(0x00A653E4u) = (uint32_t)carbon_aa_levels();\n}'
assert hashlib.sha256(OLD_ENUMERATE.encode()).hexdigest() == 'dd1c3d2f0669e7896fcaf1bc3ea572891d1ad34b2c9840d1703ea1a8acb55ee8'

# Startup detection fragment before first-run quality defaults.
OLD_DETECT = '/* Hardware detection runs after the first device exists. Retain its detail/AA\n * defaults, but save the resolution used to create that device. Only startup\n * detection is intercepted; later native preset edits keep their own rules. */\nvoid carbon_first_mode_detect(Cpu *c, void (*original)(Cpu *)) {\n    int startup = carbon_startup_selected && !carbon_startup_detection && M32(0x00A6538Cu) == 1;\n    carbon_startup_detection = 1;\n    original(c);\n    if (startup) M32(0x00A65388u) = carbon_startup_mode;\n}\n'
assert hashlib.sha256(OLD_DETECT.encode()).hexdigest() == '4a6e4d1d45173b32c28fddd613cef5ea34b0b43259cdc6cd87feac94c4d7681d'

# Filled from normalized translated original function fragments, never whole files.
FRAGMENTS = {'007115D0': '57d48599d171300fb01e484c978b0628e12c839727ff08feadcdb5866c353259', '0071D0A0': 'c7baaa11f7eedbec76cc21f53b0a619aa684270c081a12f8560bafa1f449d8b7', '00712AC0': '4808541ed13ce057d2594622ea426fb1986884b208d351b9f6ccf3ab26c262e9', '0072BF90': '0f399890432676c27f346ea91100a988caa560e228b94889ac1d5470f6675275', '007112F0': 'ceff90b6bb6ba7cf01f5a21168b4f58a18948694ac5bc6c4287c7d4d88cc2d76', '004A5230': '0205fdbd6c7b382eafea57c3f294e5cf8d69921912e6cc1df5345e8b89efb19e', '00710100': 'bca544f587ed3a419c87f5d08eeb977fad63f633ea1969139fafaf5765892282', '00732D90': '6eb5084cbc37cbb71e3c31ce82bb1101fac9c112169b2fa56560d5918f97161b', '00711810': '5da4d58acba9d1af9939c3b6501ef58718ca0a362df49447d7639f69c1f08695', '00711BD0': '5acd055d09ffbdffa84fe9670d8115646a26efae5e6a2c33691489ba9d3d9a28', '00583B10': '3b70706bebc4481b293780953f1796e028895438a5b21ce1cecce607f2dd4828', '005F8430': 'e2e68b4dba7e821eea0a3fefdaf516c15669ad5f8f089ea266c0adee9acf5e15', '005EE940': '05a0a57114875a2f62fdaa7dff91d22f5823edef95a6425831a736ce40f556de'}

def original(address):
    for path in (HERE / 'out/carbon-base').glob('NFSC_*.c'):
        source = path.read_text()
        match = re.search(r'void (?:f_|carbon_orig_)' + address + r'\(Cpu [^)]*\)\s*\{', source)
        if match:
            fragment = source[match.start():source.index('\n}', match.end()) + 2]
            fragment = re.sub(r'void (?:f_|carbon_orig_)' + address, 'void native_' + address, fragment, count=1)
            assert hashlib.sha256(fragment.encode()).hexdigest() == FRAGMENTS[address], address
            return fragment
    raise AssertionError('missing translated original ' + address)

HARNESS = r'''
#include "host.h"
#include "settings.h"
#include <stdlib.h>
#include <errno.h>
#include <strings.h>
#include <stdarg.h>
#include "durable.h"
uint8_t *G;
int diag_on;
const char *diag_dir;
static int actual_samples=1, sample_queries, aa_events, event_level, event_samples;
int render_msaa_samples(void) { ++sample_queries; return actual_samples; }
void diag_event(const char *format,...) {
 if(!strcmp(format,"PRIVATE CARBON AA level=%u samples=%d")) {
  va_list args;va_start(args,format);event_level=(int)va_arg(args,unsigned);event_samples=va_arg(args,int);va_end(args);++aa_events;
 }
}
#define PRIVATE_CARBON_SKIPFE 1
#include "carbon_resolution.h"
#define CHECK(x) do { if (!(x)) { fprintf(stderr,"PICTURE CHECK %d: %s\n",__LINE__,#x); exit(1); } } while(0)
static unsigned supported=3, alloc_next=0x90000;
static uint32_t msaa_counts[3]={2,4,8};
static char label_text[64];
void native_00583B10(Cpu *c);
static const char *profile;
const char *userdata_dir(void) { return profile; }
const char *settings_game_language(void) { return "English US"; }
HOST_REGISTRY
IMPORT_SLOTS
static int display_w=3024, display_h=1896;
static int notch;
void user32_display_pixels(int *w,int *h) { *w=display_w; *h=display_h; }
int user32_notch_fill(void) { return notch; }
uint32_t render_msaa_levels(uint32_t *counts) { if(counts)for(unsigned i=0;i<supported;i++)counts[i]=2u<<i; return supported; }
uint32_t galloc(uint32_t n) { uint32_t a=alloc_next;alloc_next+=n;return a; }
uint32_t gstr(const char *s) { uint32_t a=galloc((uint32_t)strlen(s)+1);strcpy((char*)G+a,s);return a; }
void f_00732D90(Cpu *c);
void native_007112F0(Cpu *c);
void native_00711810(Cpu *c);
void native_00711BD0(Cpu *c);
void f_0073E7E0(Cpu *c);
static unsigned quality_clamps,quality_saves,shader_applied;
uint32_t call_guest(Cpu *c,uint32_t fn,int n,const uint32_t *a) {
 if(fn!=0x583B10) {
  uint32_t sp=c->esp;
  for(int i=n-1;i>=0;--i){c->esp-=4;M32(c->esp)=a[i];}
  c->esp-=4;M32(c->esp)=0xFEED;
  switch(fn) {
  case 0x732D90: f_00732D90(c);break;
  case 0x7112F0: ++quality_clamps;native_007112F0(c);break;
  case 0x711810: native_00711810(c);break;
  case 0x711BD0: ++quality_saves;native_00711BD0(c);break;
  case 0x73E7E0: f_0073E7E0(c);break;
  default: abort();
  }
  c->esp=sp;return c->eax;
 }
 CHECK(fn==0x583B10 && n==2 && a[0]==0x5000);
 M32(0x5018)=2;M32(0x501C)=0;M32(0x5064)=0x5200;M32(0x5068)=64;memset(G+0x5200,0,128);
 Cpu text=*c;
 for(int i=n-1;i>=0;--i){text.esp-=4;M32(text.esp)=a[i];}
 text.esp-=4;M32(text.esp)=0xFEED;native_00583B10(&text);
 CHECK((M32(0x501C)&0x400002)==0x400002);
 unsigned i=0;for(;i<sizeof label_text-1&&M16(0x5200+2*i);++i){CHECK(M16(0x5200+2*i)<128);label_text[i]=(char)M16(0x5200+2*i);}
 CHECK(M16(0x5200+2*i)==0);label_text[i]=0;return 0;
}
void host_import(Cpu *c,uint32_t slot) {
 unsigned args=0;c->eax=0;
 switch(slot) {
 case SLOT_RegOpenKeyExA: {
  args=5;int k=reg_open(arg(c,0),gptr(arg(c,1)),0);c->eax=k?0:2;
  if(k)M32(arg(c,4))=REG_HKEY_BASE+4*k;break;
 }
 case SLOT_RegCreateKeyA: {
  args=3;int k=reg_open(arg(c,0),gptr(arg(c,1)),1);c->eax=k?0:2;
  if(k)M32(arg(c,2))=REG_HKEY_BASE+4*k;break;
 }
 case SLOT_RegQueryValueExA: {
  args=6;RegValue *v=reg_find(arg(c,0),gptr(arg(c,1)));if(!v){c->eax=2;break;}
  unsigned n=v->type==4?4:(unsigned)strlen(v->sz)+1;
  if(arg(c,3))M32(arg(c,3))=v->type;
  if(arg(c,4)){if(v->type==4)M32(arg(c,4))=v->dw;else memcpy(G+arg(c,4),v->sz,n);}
  if(arg(c,5))M32(arg(c,5))=n;break;
 }
 case SLOT_RegSetValueExA: args=6;reg_set(arg(c,0),gptr(arg(c,1)),arg(c,3),arg(c,4),arg(c,5));break;
 case SLOT_GlobalMemoryStatusEx: args=1;M32(arg(c,0)+8)=0;M32(arg(c,0)+12)=4;c->eax=1;break;
 case SLOT_RegCloseKey: args=1;reg_flush();break;
 case SLOT_GetLongPathNameA: args=3;c->eax=(uint32_t)strlen(gptr(arg(c,0)));memmove(G+arg(c,1),G+arg(c,0),c->eax+1);break;
 case SLOT__getcwd: args=0;strcpy((char*)G+arg(c,0),"C:\\NFSMW");c->eax=arg(c,0);break;
 default: abort();
 }
 c->esp+=4+4*args;
}
void bad_jump(Cpu *c,uint32_t at) { abort(); }
void untranslated(Cpu *c,uint32_t at) { abort(); }
void native_007115D0(Cpu *c);
void native_007112F0(Cpu *c);
void f_007115D0(Cpu *c) { native_007115D0(c); }
void f_007112F0(Cpu *c) { native_007112F0(c); }
void f_0087EAC0(Cpu *c) { x87_pop(c);c->eax=1600000000;c->esp+=4; }
void f_0073E7E0(Cpu *c) { shader_applied=arg(c,0);c->esp+=4; }
void f_00711200(Cpu *c) { M32(arg(c,0))=4;c->eax=1;c->esp+=4; }
void f_00712A50(Cpu *c) { c->eax=0;c->esp+=4; }
void f_0072A990(Cpu *c) { abort(); }
#include "game_mode_provider.h"
#include "game_display_modes.h"
#include "game_display_aa.h"
#include "game_display_bindings.h"
static Setting *row;
Setting *settings_find(const char *id) { return row && !strcmp(id,row->id) ? row : NULL; }
static int aa_dumps, dumped_value;
void settings_dump(const char *path) { CHECK(!strcmp(path,"fixture/settings_rows.txt"));++aa_dumps;dumped_value=row->value; }
void settings_add(Setting *s) { CHECK(!row);row=s; }
static void register_row(void) {
#include "game_display_settings.h"
}
/* Adapter responses only; slot matching and availability writes are native C. */
void dispatch(Cpu *c,uint32_t fn) {
 if(fn>=0x9C0000){host_import(c,fn);return;}
 unsigned args=0;c->eax=0;
 switch(fn) {
 case 0x38: args=4;break;
 case 0x14: args=4;break;
 case 0x18: args=3;c->eax=nmodes();break;
 case 0x28: args=7;c->eax=1;break;
 case 0x1C: {
  args=5;unsigned i=arg(c,3);uint32_t p=arg(c,4);CHECK(i<nmodes());
  M32(p)=adapter_modes[i][0];M32(p+4)=adapter_modes[i][1];M32(p+8)=60;M32(p+12)=22;break;
 }
 default: abort();
 }
 c->esp+=4+4*args;
}
ORIGINALS
READER_WRAPPER
void f_00732D90(Cpu *c) { carbon_display_registry_key(c,native_00732D90); }
void f_005F8430(Cpu *c) { native_005F8430(c); }
void f_005EE940(Cpu *c) { native_005EE940(c); }
void f_005F4470(Cpu *c) { abort(); }
void f_005E9D60(Cpu *c) { abort(); }
SAMPLE_MAPPING
static Cpu initial(void) { Cpu c={0};c.esp=0x10000;c.ebx=7;c.esi=8;c.edi=9;c.ebp=10;return c; }
static void no_label_original(Cpu *c) { c->esp+=4; }
static const struct { uint32_t address,maximum; const char *name; } quality_fields[] = {
 {0xA65340,3,"g_CarEnvironmentMapEnable"}, {0xA65358,2,"g_RoadReflectionEnable"},
 {0xA65360,1,"g_MotionBlurEnable"}, {0xA6536C,1,"g_ParticleSystemEnable"},
 {0xA65370,3,"g_WorldLodLevel"}, {0xA65378,1,"g_CarLodLevel"},
 {0xA6537C,2,"g_FSAALevel"}, {0xA65380,1,"g_RainEnable"},
 {0xA65384,2,"g_TextureFiltering"}, {0xA65394,1,"g_VisualTreatment"},
 {0xA65398,2,"g_ShadowDetail"}, {0xA63E60,3,"g_ShaderDetailLevel"}
};
static void untouched_detect(Cpu *c) { c->esp+=4; }
int main(int argc,char **argv) {
 CHECK(argc==3||argc==4);profile=argv[1];G=calloc(1,0xC00000);CHECK(G);
 FILE *image=fopen(argv[2],"rb");CHECK(image&&fread(G,1,0xC00000,image)==0xC00000);fclose(image);
 PATCH_IMPORTS
 M32(0xAB0AD4)=0;
 if(argc==4 && strncmp(argv[3],"quality:",8)==0) {
  int low,saved,over;CHECK(sscanf(argv[3],"quality:%d:%d:%d",&low,&saved,&over)==3);
  if(saved)setenv("BOOT_REG","FirstTime=0,g_RacingResolution=2,g_PerformanceLevel=2,g_FSAALevel=0",1);
  if(over)setenv("BOOT_REG","FirstTime=1,g_PerformanceLevel=2,g_FSAALevel=0,g_WorldLodLevel=1,g_ShaderDetailLevel=1",1);
  reg_load();
  if(saved)for(unsigned i=0;i<12;i++)boot_reg_set_dword(quality_fields[i].name,0);
  M32(0xA6538C)=!saved;
  boot_reg_set_dword("FirstTime",1);
  M32(0xAB02D8)=0x10DE;M32(0xAB02DC)=0x91;
  for(unsigned i=0;i<6;i++)M32(0xAB0658+4*i)=1;
  M32(0xAB0AB8)=0x3000;M32(0x3000)=0x3100;
  for(unsigned i=0;i<0x40;i+=4)M32(0x3100+i)=i;
  M32(0xB1EB74)=0x40000;M32(0xB1EB78)=0x80000;
  Cpu c=initial();carbon_mode_enumerate(&c,native_0072BF90);
  for(unsigned i=0;i<11;i++)M32(quality_fields[i].address+0x68)=low?0:quality_fields[i].maximum;
  if(saved){c=initial();carbon_display_load(&c,native_00711810);}
  c=initial();M32(c.esp+4)=1;
  carbon_first_mode_detect(&c,saved?untouched_detect:native_0071D0A0);
  CHECK(c.esp==0x10004&&c.ebx==7&&c.esi==8&&c.edi==9&&c.ebp==10);
  CHECK(M32(0xAB0AE8)==(saved||over?2:5));
  CHECK(quality_clamps==!saved&&quality_saves==!saved);
  if(!saved)CHECK(shader_applied==(over?1:3)&&M8(0xAB0B25)==1);
  for(unsigned i=0;i<12;i++) {
   uint32_t cap=i==11?3:M32(quality_fields[i].address+0x68);
   uint32_t want=saved?0:i==6?(cap>1?1:cap):cap;
   if(over&&(i==6||i==4||i==11))want=i==6?0:1;
   CHECK(M32(quality_fields[i].address)==want);
   RegValue *v=reg_find(0x3004,quality_fields[i].name);CHECK(v&&v->dw==want);
   printf("QUALITY %s=%u cap=%u\n",quality_fields[i].name,want,cap);
  }
  if(!saved) {
   CHECK(reg_find(0x3004,"FirstTime")->dw==0);
   /* Reload after deliberately losing every live setting. */
   for(unsigned i=0;i<12;i++)M32(quality_fields[i].address)=99;
   c=initial();carbon_display_load(&c,native_00711810);
   for(unsigned i=0;i<12;i++)CHECK(M32(quality_fields[i].address)==reg_find(0x3004,quality_fields[i].name)->dw);
  }
  puts("QUALITY PASS caps, Custom, shader setter, clamp/save, reload, saved/override policy");free(G);return 0;
 }
 if(argc==4 && !strcmp(argv[3],"quality-restart")) {
  reg_load();M32(0xA6538C)=0;Cpu c=initial();carbon_display_load(&c,native_00711810);
  CHECK(M32(0xAB0AE8)==5&&M32(0xA6538C)==0);
  for(unsigned i=0;i<12;i++)CHECK(M32(quality_fields[i].address)==(i==6?1:quality_fields[i].maximum));
  puts("QUALITY RESTART PASS all twelve native registry values preserved");free(G);return 0;
 }
 if(argc==4 && strncmp(argv[3],"native-restart:",15)==0) {
  unsigned expected=(unsigned)atoi(argv[3]+15);
  reg_load();CHECK(reg_find(0x3004,"FirstTime")->dw==0);
  Cpu c=initial();carbon_display_load(&c,native_00711810);
  CHECK(M32(0xA65388)==expected&&M32(0xAB0AE8)==5&&M32(0xA6537C)==1);
  carbon_first_mode(&c);CHECK(M32(0xA65388)==expected);
  printf("FIRST RESTART PASS slot=%u detail=5 AA=1\n",expected);free(G);return 0;
 }
 if(argc==4 && strncmp(argv[3],"first:",6)==0) {
  int saved, expected;
  int fields=sscanf(argv[3],"first:%d:%d:%d:%d:%d",&display_w,&display_h,&saved,&expected,&notch);
  CHECK(fields==4||fields==5);
  reg_load();
  if(saved>=0)boot_reg_set_dword("g_RacingResolution",(uint32_t)saved);
  /* Emulate the startup marker even on a fresh registry. */
  boot_reg_set_dword("FirstTime",1);M32(0xA6538C)=1;
  M32(0xAB02D8)=0x10DE;M32(0xAB02DC)=0x91;
  for(unsigned i=0;i<6;i++)M32(0xAB0658+4*i)=1;
  M32(0xAB0AB8)=0x3000;M32(0x3000)=0x3100;
  for(unsigned i=0;i<0x40;i+=4)M32(0x3100+i)=i;
  M32(0xB1EB74)=0x40000;M32(0xB1EB78)=0x80000;
  Cpu c=initial();carbon_mode_enumerate(&c,native_0072BF90);
  CHECK(M32(0xA65388)==(uint32_t)expected);
  c=initial();M32(c.esp+4)=0x2000;M32(c.esp+8)=0x2004;f_00712AC0(&c);
  uint32_t w=M32(0x2000),h=M32(0x2004);
  CHECK(w==carbon_modes[expected][0]&&h==carbon_modes[expected][1]);
  CHECK(w<=3840&&(h<=2160||(notch&&w==(uint32_t)display_w&&h==(uint32_t)display_h&&w*h<=3840u*2160u))&&w<=(uint32_t)display_w&&h<=(uint32_t)display_h);
  c=initial();M32(c.esp+4)=1;carbon_first_mode_detect(&c,native_0071D0A0);
  CHECK(M32(0xA65388)==(uint32_t)expected&&M32(0xAB0AE8)==5&&M32(0xA6537C)==1);
  c=initial();native_00711BD0(&c);
  CHECK(reg_find(0x3004,"g_RacingResolution")->dw==(uint32_t)expected);
  CHECK(reg_find(0x3004,"FirstTime")->dw==0);
  /* A later user preset change follows the original instead of startup policy. */
  c=initial();M32(c.esp+4)=1;carbon_first_mode_detect(&c,native_0071D0A0);CHECK(M32(0xA65388)==1);
  printf("FIRST MODE PASS display=%dx%d slot=%d size=%ux%u saved=%d detail=5 AA=1\n",display_w,display_h,expected,w,h,saved);
  free(G);return 0;
 }
 if(argc==4) {
  reg_load();M32(0xA6538C)=reg_find(0x3004,"FirstTime")==NULL;boot_reg_set_dword("FirstTime",1);
  Cpu reload=initial();carbon_display_load(&reload,native_00711810);
  CHECK(M32(0xA65388)==4&&M32(0xA6537C)==2&&M32(0xA6538C)==0);
  puts("PICTURE RESTART PASS second-process resolution=4 AA=2");free(G);return 0;
 }
 Cpu key=initial();native_00732D90(&key);CHECK(reg_open(0x80000002,gptr(key.eax),0)==0);
 key=initial();carbon_display_registry_key(&key,native_00732D90);CHECK(reg_open(0x80000002,gptr(key.eax),0)==1);
 setenv("BOOT_REG","FirstTime=0,g_RacingResolution=4,g_FSAALevel=2",1);reg_load();
 M32(0xA6538C)=0;boot_reg_set_dword("FirstTime",1);
 Cpu load=initial();carbon_display_load(&load,native_00711810);CHECK(M32(0xA65388)==4&&M32(0xA6537C)==2&&M32(0xA6538C)==0);
 unsetenv("BOOT_REG");Cpu save=initial();native_00711BD0(&save);
 M32(0xA65388)=M32(0xA6537C)=0;reg_put("g_RacingResolution")->dw=0;reg_put("g_FSAALevel")->dw=0;
 reg_load();load=initial();carbon_display_load(&load,native_00711810);CHECK(M32(0xA65388)==4&&M32(0xA6537C)==2);
 static const unsigned legacy[6][2]={{640,480},{800,600},{1024,768},{1280,960},{1280,1024},{1600,1200}};
 for(unsigned i=0;i<6;i++) {
  Cpu c=initial();M32(0xA65388)=i;M32(c.esp+4)=0x2000;M32(c.esp+8)=0x2004;
  native_00712AC0(&c);CHECK(M32(0x2000)==legacy[i][0]&&M32(0x2004)==legacy[i][1]);CHECK(c.esp==0x1000C);
 }
 /* The unmodified F10 baseline returned zero and wrote neither reset nor registry. */
 M32(0xAB0AB8)=0x3000;M32(0x3000)=0x3100;
 M32(0xAB02D8)=0x10DE;M32(0xAB02DC)=0x91;
 for(unsigned i=0;i<0x40;i+=4)M32(0x3100+i)=i;
 M32(0xB1EB74)=0x40000;M32(0xB1EB78)=0x80000;
 Cpu enumerate=initial();carbon_mode_enumerate(&enumerate,native_0072BF90);CHECK(enumerate.esp==0x10004);
 CHECK(M32(0xA653E4)==2);
 static const unsigned expected[6][2]={{640,480},{1280,720},{1920,1080},{2560,1440},{3840,2160},{3024,1896}};
 for(unsigned i=0;i<6;i++) {
  CHECK(M32(0xA63E28+4*i)==expected[i][0]&&M32(0xA63E40+4*i)==expected[i][1]);
  if(M32(0xAB0658+4*i)!=1||M32(0xAB08D4+4*i)!=60)fprintf(stderr,"mode %u available=%u refresh=%u\n",i,M32(0xAB0658+4*i),M32(0xAB08D4+4*i));
  CHECK(M32(0xAB0658+4*i)==1&&M32(0xAB08D4+4*i)==60);
  Cpu c=initial();M32(0xA65388)=i;M32(c.esp+4)=0x2000;M32(c.esp+8)=0x2004;
  f_00712AC0(&c);CHECK(M32(0x2000)==expected[i][0]&&M32(0x2004)==expected[i][1]);CHECK(c.esp==0x1000C);
  c=initial();c.ecx=0x6000;M32(c.ecx+0x1C)=0x5000;carbon_mode_label(&c,no_label_original);
  char text[64];snprintf(text,sizeof text,"%u x %u",expected[i][0],expected[i][1]);CHECK(!strcmp(label_text,text));
 }
 for(unsigned i=0;i<3;i++) {
  M32(0xA65388)=i==0?6:i==1?0xFFFFFFFF:0x7FFFFFFF;
  Cpu c=initial();carbon_mode_validate(&c,native_007112F0);CHECK(M32(0xA65388)==0);
 }
 register_row();CHECK(row&&row->nchoices==3&&!strcmp(row->choices[2],"4x"));
 for(unsigned level=0;level<3;level++) {
  M32(0xA6537C)=99;M8(0xAB0B25)=0;reg_put("g_FSAALevel")->dw=99;
  row->apply(level);CHECK(row->get()==level&&M32(0xA6537C)==level&&reg_find(0x3004,"g_FSAALevel")->dw==level&&M8(0xAB0B25)==1);
  CHECK(M32(0xAB0AE8)==5&&reg_find(0x3004,"g_PerformanceLevel")->dw==5);
  load=initial();carbon_display_load(&load,native_00711810);CHECK(row->get()==level);
  CHECK(game_diag_aa_requested()==level&&game_diag_aa_active()==2);
  Cpu c=initial();M32(c.esp+4)=3840;M32(c.esp+8)=2160;
  carbon_aa_present(&c,native_00710100);CHECK(M32(0xAB06FC)==3840&&M32(0xAB0700)==2160);
  CHECK(M32(0xAB070C)==!!level&&M32(0xAB0710)==level);
  CHECK(render_msaa_count(M32(0xAB070C),M32(0xAB0710))==(level?1u<<level:1));
  c=initial();M32(c.esp+4)=1;carbon_aa_cycle(&c,native_004A5230);CHECK(row->get()==(level+1)%3);
  c=initial();M32(c.esp+4)=0xFFFFFFFF;carbon_aa_cycle(&c,native_004A5230);CHECK(row->get()==level);
  c=initial();c.ecx=0x6000;M32(c.ecx+0x74)=0x13CD;carbon_aa_label(&c,no_label_original);CHECK(!strcmp(label_text,row->choices[level]));
 }
 /* Reverse from Off may never select the adapter's third (8x) quality. */
 M32(0xA6537C)=0;M32(0xA653E4)=3;Cpu cycle=initial();M32(cycle.esp+4)=0xFFFFFFFF;
 carbon_aa_cycle(&cycle,native_004A5230);CHECK(row->get()==2&&M32(0xA6537C)==2);
 for(supported=0;supported<3;supported++) {CHECK(carbon_aa_levels()==supported);row->apply(2);CHECK(row->get()==supported);}
 setenv("NFS_CARBON_RES","1920x1080",1);private_carbon_resolution_setup();
 for(unsigned i=0;i<6;i++) {
  Cpu c=initial();M32(0xA65388)=i;M32(c.esp+4)=0x2000;M32(c.esp+8)=0x2004;f_00712AC0(&c);
  CHECK(M32(0x2000)==1920&&M32(0x2004)==1080);
  c=initial();c.ecx=0x6000;carbon_mode_label(&c,no_label_original);CHECK(!strcmp(label_text,"1920 x 1080"));
 }
 /* Diagnostic samples come from the actual target, including a pending reset. */
 CHECK(sample_queries==0);M32(0xA6537C)=2;row->value=0;actual_samples=2;diag_on=1;diag_dir="fixture";
 CHECK(aa_game_get()==2&&aa_events==1&&event_level==2&&event_samples==2);
 CHECK(aa_dumps==1&&dumped_value==2&&row->value==2);
 CHECK(aa_game_get()==2&&aa_events==1&&aa_dumps==1);
 actual_samples=4;CHECK(aa_game_get()==2&&aa_events==2&&event_samples==4&&aa_dumps==2);
 M32(0xA6537C)=0;actual_samples=1;CHECK(aa_game_get()==0&&aa_events==3&&event_level==0&&event_samples==1);
 diag_on=0;sample_queries=0;CHECK(aa_game_get()==0&&sample_queries==0&&aa_events==3);
 puts("PICTURE PASS legacy=6 HD-before=0 valid-after=6 HD-after=2 AA=0/1,1/2,2/4 labels=15 override=6 registry=0->1 restart=4/2 diagnostic_actual=2/requested4");free(G);return 0;
}
'''

def main():
    if not (HERE / 'out/carbon-base/image.json').is_file():
        print('SKIP: Carbon outputs absent'); return 3
    bodies = '\n'.join(original(a) for a in FRAGMENTS)
    target = (ROOT / 'runtime/render_target.m').read_text()
    mapping = target[target.index('uint32_t render_msaa_count('):target.index('\nint render_msaa_samples(')]
    sys.path.insert(0, str(HERE))
    from private_resolution import instrument, CARBON_SHA256
    wrapper, found = instrument('void f_00712AC0(Cpu *c) { carbon_mode_read(c, native_00712AC0); }', CARBON_SHA256)
    assert found == [0x712AC0]
    boot = (ROOT / 'runtime/boot.c').read_text()
    registry = boot[boot.index('#define REG_HKEY_BASE'):boot.index('// d3d9.m: is this the first run')]
    registry += boot[boot.index('static int reg_open('):boot.index('// ---- code the game loads at run time')]
    import recomp
    image = json.loads((HERE/'out/carbon-base/image.json').read_text())
    pe = recomp.PE(image['exe'],expected_sha256=image['sha256'])
    assert pe.read(0xA65388, 4) == bytes(4)
    assert pe.read(0x712ADD, 12).hex() == 'c70080020000c701e0010000'
    wanted = ['RegOpenKeyExA','RegCreateKeyA','RegQueryValueExA','RegSetValueExA','RegCloseKey','GetLongPathNameA','_getcwd','GlobalMemoryStatusEx']
    slots = {name:next(a for a,n in pe.imports.items() if n.endswith('!'+name)) for name in wanted}
    defs = '\n'.join(f'#define SLOT_{name} 0x{a:08X}u' for name,a in slots.items())
    patches = '\n'.join(f'M32(0x{a:08X}u)=0x{a:08X}u;' for a in slots.values())
    declarations = '\n'.join('void f_'+a+'(Cpu *c);' for a in ('00732D90','005F8430','005EE940','005F4470','005E9D60'))
    harness = HARNESS.replace('ORIGINALS', declarations+'\n'+bodies).replace('SAMPLE_MAPPING', mapping).replace('READER_WRAPPER', wrapper)
    harness = harness.replace('HOST_REGISTRY',registry).replace('IMPORT_SLOTS',defs).replace('PATCH_IMPORTS',patches)
    with tempfile.TemporaryDirectory(prefix='private-picture-02-') as tmp:
        tmp = Path(tmp)
        blob = bytearray(0xC00000)
        for name,_,va,size,raw in pe.sections:
            if name.rstrip(b'\0') in (b'.rdata',b'.data'): blob[pe.base+va:pe.base+va+size]=pe.data[raw:raw+size]
        (tmp/'guest.bin').write_bytes(blob)
        names = ['game_first_resolution.h','game_mode_provider.h','game_display_modes.h','game_display_aa.h','game_display_settings.h','game_display_bindings.h']
        good = {n:(PRIVATE/n).read_text() for n in names}
        for variant in ('good','unwritten-slot','f10-no-write','unbound-registry','ascii-mode-label','ascii-aa-label','startup-marker','firstres-old','firstres-smallest','quality-old','quality-aa-off','diag-requested-samples'):
            source = dict(good)
            if variant == 'quality-old':
                source['game_first_resolution.h'] = source['game_first_resolution.h'].split('/* Hardware detection')[0] + OLD_DETECT
            elif variant == 'quality-aa-off':
                source['game_first_resolution.h'] = source['game_first_resolution.h'].replace('cap > 1 ? 1 : cap', 'cap > 1 ? 0 : cap')
            elif variant == 'unwritten-slot':
                source['game_mode_provider.h'] = source['game_mode_provider.h'].replace('i < 6; ++i', 'i < 5; ++i')
            elif variant == 'f10-no-write':
                source['game_display_aa.h'] = source['game_display_aa.h'].replace('    M32(0x00A6537Cu) = (uint32_t)level;', '    (void)level;')
            elif variant == 'diag-requested-samples':
                source['game_display_aa.h'] = source['game_display_aa.h'].replace('render_msaa_samples()', '(level ? 1 << level : 1)')
            elif variant == 'unbound-registry':
                source['game_mode_provider.h'] = source['game_mode_provider.h'].replace('    c->eax = key;', '    (void)key;')
            elif variant == 'ascii-mode-label':
                source['game_mode_provider.h'] = source['game_mode_provider.h'].replace(
                    'for (unsigned k = 0; k <= strlen(text); ++k) M16(buffer + 2*k) = (uint8_t)text[k];',
                    'memcpy(G + buffer, text, strlen(text) + 1);')
            elif variant == 'ascii-aa-label':
                source['game_display_aa.h'] = source['game_display_aa.h'].replace(
                    'memcpy(G + labels[i], text[i], sizeof text[i]);',
                    'memcpy(G + labels[i], "Off", 4);')
            elif variant == 'startup-marker':
                source['game_mode_provider.h'] = source['game_mode_provider.h'].replace(
                    '    M32(0x00A6538Cu) = first;', '    (void)first;')
            elif variant == 'firstres-old':
                current = re.search(r'void carbon_mode_enumerate\([^}]+}', source['game_mode_provider.h'])[0]
                source['game_mode_provider.h'] = source['game_mode_provider.h'].replace(current, OLD_ENUMERATE)
                source['game_first_resolution.h'] = source['game_first_resolution.h'].replace(
                    '    if (startup) M32(0x00A65388u) = carbon_startup_mode;', '    (void)startup;')
            elif variant == 'firstres-smallest':
                source['game_first_resolution.h'] = source['game_first_resolution.h'].replace('if (w*h > area)', 'if (w*h < area)')
            for name,text in source.items(): (tmp/name).write_text(text)
            (tmp/'carbon_resolution.h').write_text((PRIVATE/'carbon_resolution.h').read_text())
            (tmp/'fixture.c').write_text(harness)
            command = ['clang','-O1','-fsanitize=address,undefined','-I',str(tmp),'-I',str(ROOT/'runtime'),'-I',str(HERE),str(tmp/'fixture.c'),'-o',str(tmp/'fixture')]
            result = subprocess.run(command,capture_output=True,text=True)
            assert result.returncode == 0, result.stderr[-2500:]
            profile = tmp/variant;profile.mkdir()
            if variant in ('good','quality-old','quality-aa-off'):
                for scenario in ('quality:0:0:0','quality:1:0:0','quality:0:1:0','quality:0:0:1'):
                    fresh=profile/scenario.replace(':','-');fresh.mkdir()
                    result=subprocess.run([str(tmp/'fixture'),str(fresh),str(tmp/'guest.bin'),scenario],capture_output=True,text=True,
                        env={k:v for k,v in os.environ.items() if k not in ('BOOT_REG','NFS_CARBON_RES')})
                    assert result.returncode==(0 if variant=='good' else 1),(variant,scenario,result.returncode,result.stderr[-1800:])
                    print(variant,scenario,'exit='+str(result.returncode),result.stdout.strip())
                    if variant!='good':break
                    if scenario=='quality:0:0:0':
                        result=subprocess.run([str(tmp/'fixture'),str(fresh),str(tmp/'guest.bin'),'quality-restart'],capture_output=True,text=True,
                            env={k:v for k,v in os.environ.items() if k not in ('BOOT_REG','NFS_CARBON_RES')})
                        assert result.returncode==0,result.stderr[-1800:]
                        print(result.stdout.strip())
                if variant!='good':continue
            if variant in ('good','firstres-old','firstres-smallest'):
                for scenario in ('first:3840:2160:-1:4','first:5120:2880:-1:4','first:3456:2234:-1:3',
                                 'first:3456:2234:2:2','first:3024:1896:-1:5','first:3456:2234:-1:5:1'):
                    fresh=profile/scenario.replace(':','-');fresh.mkdir()
                    result=subprocess.run([str(tmp/'fixture'),str(fresh),str(tmp/'guest.bin'),scenario],capture_output=True,text=True,
                        env={k:v for k,v in os.environ.items() if k not in ('BOOT_REG','NFS_CARBON_RES')})
                    expected=0 if variant=='good' else 1
                    assert result.returncode==expected,(variant,scenario,result.returncode,result.stderr[-1800:])
                    print(variant,scenario,'exit='+str(result.returncode),result.stdout.strip())
                    if variant!='good':break
                    restart=subprocess.run([str(tmp/'fixture'),str(fresh),str(tmp/'guest.bin'),'native-restart:'+scenario.split(':')[4]],
                        capture_output=True,text=True,env={k:v for k,v in os.environ.items() if k not in ('BOOT_REG','NFS_CARBON_RES')})
                    assert restart.returncode==0,(scenario,restart.stderr[-1800:])
                    print(restart.stdout.strip())
                if variant!='good':continue
            result = subprocess.run([str(tmp/'fixture'),str(profile),str(tmp/'guest.bin')],capture_output=True,text=True,
                                    env={k:v for k,v in os.environ.items() if k not in ('BOOT_REG','NFS_CARBON_RES')})
            expected = 0 if variant == 'good' else 1
            assert result.returncode == expected, (variant,result.returncode,result.stdout,result.stderr[-2000:])
            print(variant, 'exit='+str(result.returncode),result.stdout.strip())
            if variant == 'good':
                result = subprocess.run([str(tmp/'fixture'),str(profile),str(tmp/'guest.bin'),'restart'],capture_output=True,text=True,
                                        env={k:v for k,v in os.environ.items() if k not in ('BOOT_REG','NFS_CARBON_RES')})
                assert result.returncode == 0, result.stderr[-2000:]
                print(result.stdout.strip())
    return 0

if __name__ == '__main__':
    sys.exit(main())
