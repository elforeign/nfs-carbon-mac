#include "funcs.h"
#include "host.h"
#include "settings.h"
#include <stdarg.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
uint8_t *G;
int diag_on;
static unsigned requests, completions, awards, transitions, writes;
static char saved_key[128], saved_value[128];
#define CHECK(x) do { if (!(x)) { fprintf(stderr,"ADDONS CHECK %d: %s\n",__LINE__,#x);exit(1); } } while(0)
void diag_event(const char *fmt,...) { (void)fmt; }
void report_note(const char *fmt,...) { (void)fmt; }
void portmenu_status(const char *fmt,...) { (void)fmt; }
const char *app_pref(const char *key) { return !strcmp(key,saved_key) ? saved_value : NULL; }
void app_pref_set(const char *key,const char *value) { ++writes;snprintf(saved_key,sizeof saved_key,"%s",key);snprintf(saved_value,sizeof saved_value,"%s",value?value:""); }
void app_pref_batch_begin(void) { }
void app_pref_batch_end(void) { }
int roots_x360_has(const char *s) { (void)s;return 0; }
uint32_t galloc(uint32_t n) { CHECK(n==65536);return 0x300000; }
#include "carbon_addons_gameplay.c"
#include "carbon_addons_gameplay_cards.c"
static Cpu cpu(uint32_t self) { Cpu c={0};c.esp=0x280000;c.ecx=self;c.cw=0x37F;return c; }
void bad_jump(Cpu *c,uint32_t at) { (void)c;fprintf(stderr,"bad jump %x\n",at);exit(2); }
void untranslated(Cpu *c,uint32_t at) { bad_jump(c,at); }
void host_import(Cpu *c,uint32_t at) { bad_jump(c,at); }
void abi_violation(Cpu *c,uint32_t fn,uint32_t b,uint32_t s,uint32_t d,uint32_t p,uint32_t sp) { (void)b;(void)s;(void)d;(void)p;(void)sp;bad_jump(c,fn); }
void f_00888385(Cpu *c) { c->esp+=8; }
void f_0088839B(Cpu *c) { c->esp+=8; }
void f_008883B1(Cpu *c) { c->esp+=8; }
void f_00888539(Cpu *c) { ++requests;c->esp+=24; }
void f_008891C7(Cpu *c) { c->esp+=12; }
void f_008887F3(Cpu *c) { c->esp+=4; }
void f_0087EAC0(Cpu *c) { c->eax=(int32_t)ST(0);x87_pop(c);c->esp+=4; }
void f_00461A40(Cpu *c) { c->esp+=4; }
void f_004BC6D0(Cpu *c) { c->esp+=8; }
void f_006A1900(Cpu *c) { x87_push(c,1);c->esp+=8; }
void f_00576A60(Cpu *c) { c->eax=arg(c,1);c->esp+=12; }
void f_004D53A0(Cpu *c) { ++awards;c->esp+=12; }
void f_005873E0(Cpu *c) { c->eax=0x70000+arg(c,0)*32;c->esp+=8; }
void f_00587410(Cpu *c) { c->eax=0x71000+arg(c,0)*32;c->esp+=8; }
void f_005F3880(Cpu *c) { c->esp+=16; }
void f_005EA670(Cpu *c) { c->eax=123;c->esp+=4; }
void f_00598540(Cpu *c) { ++transitions;c->esp+=16; }
void f_005A02C0(Cpu *c) { c->esp+=4; }
/* Redraw, language lookup and FE printf run translated bodies. Adapt the
 * language table, object lookup, va_list formatter and final string sink. */
static char cards_shown[32];
void f_005A3A30(Cpu *c) { c->esp+=4; }
void f_0046D450(Cpu *c) { c->eax=1;c->esp+=8; }
void f_005711C0(Cpu *c) { c->eax=123;c->esp+=4; }
void f_005A07B0(Cpu *c) { c->eax=0x73000;c->esp+=4; }
void f_00571040(Cpu *c) { c->esp+=4; }
void f_005A0830(Cpu *c) { c->esp+=4; }
void f_004A05D0(Cpu *c) { c->eax=0;c->esp+=28; }
void f_005786B0(Cpu *c) {
 CHECK(arg(c,0)==0x72E21D2A);
 c->eax=arg(c,0);c->esp+=4;
}
void f_005785D0(Cpu *c) {
 CHECK(c->edx==0x72E21D2A&&c->ebx==0x74000&&c->ecx==1);
 c->eax=0x72000;c->esp+=4;
}
void f_005983F0(Cpu *c) { CHECK(arg(c,0)==0x60000);c->eax=0x75000;c->esp+=8; }
void f_005F3760(Cpu *c) { CHECK(c->ecx==0x75000);c->eax=arg(c,0)==0xBA94538E?0x76000:0x76100;c->esp+=8; }
void f_00475790(Cpu *c) {
 CHECK(arg(c,0)==0xA973E8&&arg(c,1)==0x72000);
 /* Native 005A0972 constructs this guest va_list from entry esp+16:
  * package, object hash, format pointer, then the signed integer count. */
 c->eax=snprintf((char*)gptr(arg(c,0)),32,(char*)gptr(arg(c,1)),(int32_t)M32(arg(c,2)));
 c->esp+=4;
}
void f_005E9D60(Cpu *c) {
 CHECK(c->ecx==0x76000&&M32(arg(c,0)+4)==0xA973E8);
 snprintf(cards_shown,sizeof cards_shown,"%s",(char*)gptr(M32(arg(c,0)+4)));
 c->esp+=8;
}
/* Host string/number boundaries; the native FECareer codec and token cursor
 * run below. The file contains the native writer's actual text, not a memory
 * snapshot of the profile. */
void f_00475C10(Cpu *c) {
 char *out=(char*)gptr(arg(c,0));const char *fmt=(const char*)gptr(arg(c,1));
 c->eax=strstr(fmt,"%s") ? sprintf(out,fmt,(const char*)gptr(arg(c,2))) : sprintf(out,fmt,(int32_t)arg(c,2));c->esp+=4;
}
void f_004711B0(Cpu *c) { c->eax=(uint32_t)strlen((const char*)gptr(arg(c,0)));c->esp+=4; }
void f_00471230(Cpu *c) { strncpy((char*)gptr(arg(c,0)),(const char*)gptr(arg(c,1)),arg(c,2));c->esp+=4; }
void f_00475F90(Cpu *c) { f_00475F30(c);c->eax=(uint32_t)strtol((const char*)gptr(c->eax),NULL,0); }
void dispatch(Cpu *c,uint32_t fn) {
 switch(fn) {
 case 0x578830: f_00578830(c);return;
 case 0x5A0910: f_005A0910(c);return;
 case 0xFF000000: ++completions;c->esp+=4;return; /* FE movie completion */
 case 0xFF000004: c->esp+=4;return; /* FE movie begin */
 case 0xFF000008: c->eax=0;c->esp+=12;return; /* attribute allocator failure */
 case 0xFF00000C: c->esp+=4;return; /* card redraw */
 case 0x40AB70: f_0040AB70(c);return;
 case 0x4CD3D0: f_004CD3D0(c);return;
 case 0x576A60: f_00576A60(c);return;
 case 0x4D53A0: ++awards;c->esp+=12;return; /* native marker award boundary */
 case 0x5873E0: c->eax=0x70000+arg(c,0)*32;c->esp+=8;return;
 case 0x587410: c->eax=0x71000+arg(c,0)*32;c->esp+=8;return;
 case 0x5F3880: c->esp+=16;return;
 case 0x5EA670: c->eax=123;c->esp+=4;return;
 case 0x598540: ++transitions;c->esp+=16;return;
 case 0x5A02C0: c->esp+=4;return;
 default: bad_jump(c,fn);
 }
}
uint32_t call_guest(Cpu *c,uint32_t fn,int n,const uint32_t *args) {
 uint32_t sp=c->esp;for(int i=n-1;i>=0;--i){c->esp-=4;M32(c->esp)=args[i];}
 c->esp-=4;M32(c->esp)=0xFEED;dispatch(c,fn);c->esp=sp;return c->eax;
}
STUBS
#include "native.inc"
static void title_original(Cpu *c) { c->esp+=8; }
static void choose(const char *id,int value) { Setting *s=settings_find(id);CHECK(s);if(s->value!=value)CHECK(settings_set(s,value)); }
static void setup(void) {
 M32(0xA97A7C)=0x80000;M32(0x80000)=0x81000;M32(0x81060)=0xFF000000;M32(0x81064)=0xFF000004;M32(0x800B0)=0;
 M32(0xA97BC0)=0;M32(0xA9E6D8)=0;M32(0xA98284)=0x90000;M32(0x96A14)=0;M32(0x96A18)=3;M32(0x96A1C)=0;
 M32(0xA99604)=0x82000;M32(0x82000)=0x83000;M32(0x83000)=0xFF000008;
 M32(0xA9FF5C)=0x84000;M32(0xA9FF64)=1;M32(0x84000)=0x85008;M32(0x85000)=0x86000;M32(0x85008)=0x87000;M32(0x87004)=0x76E810;
 M32(0x86004)=0x88000;M32(0x88000)=0x89000;M32(0x88004)=0x89008;M32(0x89000)=0x4061D0;M32(0x89004)=0x8A000;
 M32(0x800D4)=0x8B000;M32(0x8B000)=0x40000;M32(0xA8AD08)=0;M32(0xA8AD68)=0;M32(0xA99BBC)=6;
}
static void movie(void) { Cpu c=cpu(0x10000);strcpy((char*)gptr(0x1001C),"story");f_00595210(&c);CHECK(c.esp==0x280004); }
static void save_reload(unsigned expected) {
 Cpu c=cpu(0x642D8);M32(c.esp+4)=0x100000;M32(c.esp+8)=0x110000;f_0049D6D0(&c);
 CHECK(c.esp==0x28000C);size_t size=c.eax-0x100000;CHECK(size>0&&size<65536);
 FILE *f=tmpfile();CHECK(f);CHECK(fwrite(gptr(0x100000),1,size,f)==size);rewind(f);
 memset(G+0x100000,0,size);CHECK(fread(gptr(0x100000),1,size,f)==size);fclose(f);M8(0x100000+size)=0;
 /* The parser's ordinary twelve-byte token descriptors point into the text.
  * Native 004727B0 / 00475F30 consume and advance these descriptors. */
 unsigned count=0;char *text=(char*)gptr(0x100000),*p=text;
 while(*p) {
  while(*p==' '||*p=='\t')++p;if(!*p)break;
  char *start=p;if(*p=='"'){start=++p;while(*p&&*p!='"')++p;}else while(*p&&*p!='\t'&&*p!=' ')++p;
  if(*p)*p++=0;
  CHECK(count<4096);uint32_t token=0x120000+12*count++;M32(token)=0;M32(token+4)=(uint32_t)(start-text);
 }
 memset(G+0x642D8,0,0x51C0);memset(G+0x140000,0,0x180);
 M32(0x140054)=0x100000;M32(0x140154)=count;M32(0x14015C)=0x120000;
 c=cpu(0x642D8);M32(c.esp+4)=0x140000;f_0049D390(&c);CHECK(c.esp==0x280008);
 CHECK(M32(0x64330)==expected);CHECK(M32(0x140160)==count);printf("native career codec reload cash=%u tokens=%u\n",expected,count);
}
static void heat(float value) { Cpu c=cpu(0x8A000);MF32(c.esp+4)=value;f_0040AB70(&c);CHECK(c.esp==0x280008); }
static unsigned skill(void) {
 Cpu c=cpu(0x90000);M32(c.esp+4)=0x11000;M32(c.esp+8)=0x12000;M32(c.esp+12)=0x13000;M32(c.esp+16)=0x14000;M32(c.esp+20)=1;
 MF32(0x1205C)=1;MF32(0x1207C)=1;MF32(0x12008)=1;MF32(0x12078)=1;
 f_00643100(&c);CHECK(c.esp==0x280018);return c.eax&255;
}
static void cards_open_original(Cpu *c) { c->esp += 4; }
static void cards_open(uint32_t self) {
 Cpu c=cpu(self);carbon_addons_cards_open(&c,cards_open_original);CHECK(c.esp==0x280004);
}
static void cards_remaining(unsigned limit,unsigned picked,int expected) {
 choose("gameplay.markers",limit);uint32_t self=0x50000;
 memset(G+self,0,0x200);M32(self+0xDC)=6;M32(self+0xC)=0x60000;
 /* A native type whose redraw uses a language hash rather than extra format arguments. */
 uint32_t type=M32(0x9F76A0);CHECK(type&&type!=0xC);
 for(unsigned i=0;i<6;i++){M32(self+0xE0+12*i)=type;M8(self+0xE8+12*i)=i<picked;}
 M32(0xA95378)=0x74000;M32(0xA95384)=1;M32(0x76018)=5;
 strcpy((char*)gptr(0x72000),"%d");
 Cpu c=cpu(self+0x28);cards_shown[0]=0;
 cards_open(self);
 /* Old three-word call reads this unrelated word as its absent fourth arg. */
 M32(c.esp+4-256)=picked?2566684:1572708;
 f_0084E600(&c);
 CHECK(c.esp==0x280004&&cards_shown[0]);
 printf("cards remaining limit=%u picked=%u shown=%s want=%d\n",limit,picked,cards_shown,expected);fflush(stdout);
 CHECK(atoi(cards_shown)==expected);
}
static void cards(unsigned want,int change_mid_screen) {
 choose("gameplay.markers",want);uint32_t self=0x50000;memset(G+self,0,0x200);M32(self+0xDC)=6;M32(self+0x14)=0x60000;
 M32(self+0x28)=0x62000;M32(0x62008)=0xFF00000C;
 for(unsigned i=0;i<6;i++){M32(self+0xE0+12*i)=0xC;M32(self+0xE4+12*i)=1000+i;}
 cards_open(self);
 unsigned before=awards, flow=transitions;
 Cpu initial=cpu(self);M32(initial.esp+8)=1;f_0084E1D0(&initial);CHECK(initial.eax==1&&initial.esp==0x28000C);
 for(unsigned i=0;i<6;i++) {
  if(i==3 && change_mid_screen)choose("gameplay.markers",0);
  Cpu c=cpu(self);M32(c.esp+4)=i;f_0084E220(&c);CHECK(c.esp==0x280008);
 }
 unsigned selected=0;for(unsigned i=0;i<6;i++)selected+=!!M8(self+0xE8+12*i);
 unsigned limit=want?want:2;
 Cpu c=cpu(self);f_0084DEE0(&c);
 printf("cards requested=%u selected=%u awards=%u completions=%u reachable=%u\n",limit,selected,awards-before,transitions-flow,c.eax);
 fflush(stdout);
 CHECK(selected==limit&&awards-before==limit&&transitions-flow==1);
 CHECK(c.eax==1&&c.esp==0x280004);
 c=cpu(self);M32(c.esp+8)=1;f_0084E1D0(&c);CHECK(c.eax==UINT32_MAX&&c.esp==0x28000C);
}
int main(int argc,char **argv) {
 CHECK(argc==3);G=calloc(1,0xC00000);CHECK(G);FILE *file=fopen(argv[1],"rb");CHECK(file);CHECK(fread(G,1,0xC00000,file)==0xC00000);fclose(file);setup();
 if(getenv("CADD_SAVED_ID")){snprintf(saved_key,sizeof saved_key,"%s",getenv("CADD_SAVED_ID"));snprintf(saved_value,sizeof saved_value,"%s",getenv("CADD_SAVED_VALUE"));}
 carbon_addons_gameplay_init();carbon_addons_cards_init();settings_init();CHECK(settings_count()==10);
 if(!strcmp(argv[2],"saved")) {
  Setting *row=settings_find(saved_key);CHECK(row&&row->saved&&row->value==atoi(getenv("CADD_SAVED_EXPECT")));
  if(!strcmp(row->id,"gameplay.heat")){heat(1);CHECK(MF32(0x8A01C)==6);}
  if(!strcmp(row->id,"gameplay.no_catchup"))CHECK(skill()==0);
  if(!strcmp(row->id,"gameplay.skip_movies")){movie();CHECK(requests==0);}
  if(!strcmp(row->id,"gameplay.skip_prologue")){Cpu c=cpu(0);f_0064C560(&c);CHECK(c.eax&255);}
  if(!strcmp(row->id,"gameplay.markers"))cards(6,0);
  printf("saved consumer %s=%s PASS\n",row->id,saved_value);
 } else if(!strcmp(argv[2],"movies")) {
  movie();CHECK(requests==1);choose("gameplay.skip_movies",1);movie();CHECK(requests==1&&M32(0xA9E6D8)==0);
  Cpu c=cpu(0x10000);carbon_addons_title(&c,title_original);movie();CHECK(requests==2);movie();CHECK(requests==3);
  printf("movies startup requests=0 story requests=2 title latch=1\n");
 } else if(!strcmp(argv[2],"heat")) {
  choose("gameplay.heat",6);carbon_addons_gameplay_frame();CHECK(MF32(0x8A01C)==6);
  for(unsigned i=0;i<10;i++){heat(i%2?1:5);CHECK(MF32(0x8A01C)==6);}
  choose("gameplay.heat",0);heat(2.5);CHECK(MF32(0x8A01C)==2.5f);
  choose("gameplay.heat",4);carbon_addons_gameplay_frame();CHECK(MF32(0x8A01C)==4);
  printf("heat native writes=10 fixed=6 Off=2.5 frame=4\n");
 } else if(!strcmp(argv[2],"catchup")) {
  CHECK(skill()==1);choose("gameplay.no_catchup",1);CHECK(skill()==0);choose("gameplay.no_catchup",0);CHECK(skill()==1);
  puts("catchup retail=1 On=0 Off=1");
 } else if(!strcmp(argv[2],"prologue")) {
  M8(0xA9E6C1)=0;Cpu c=cpu(0);f_0064C560(&c);CHECK(!(c.eax&255));choose("gameplay.skip_prologue",1);
  c=cpu(0);f_0064C560(&c);CHECK((c.eax&255)==1);choose("gameplay.skip_prologue",0);
  c=cpu(0);f_0064C560(&c);CHECK(!(c.eax&255));puts("prologue script 0/1/0");
 } else if(!strcmp(argv[2],"cash")) {
  M32(0x64330)=15000;unsigned deltas[]={20000,50000,100000,12345};const char *ids[]={"gameplay.cash_20000","gameplay.cash_50000","gameplay.cash_100000","gameplay.cash_amount"};
  unsigned total=15000;
  for(unsigned i=0;i<4;i++){carbon_addons_gameplay_frame();Setting *s=settings_find(ids[i]);CHECK(s&&s->apply);if(i==3)strcpy(s->text,"12345");if(i==0)CHECK(carbon_addons_gameplay_script("cash_20000")==1);else s->apply(0);carbon_addons_gameplay_frame();total+=deltas[i];CHECK(M32(0x64330)==total);save_reload(total);carbon_addons_gameplay_frame();CHECK(M32(0x64330)==total);}
  CHECK(M32(0x694F4)==182345);cadd_cash20(0);M32(0x8B000)=0xA0000;carbon_addons_gameplay_frame();CHECK(!M32(0xC4330));M32(0x8B000)=0x40000;
  M32(0x96A18)=0;unsigned before=M32(0x64330);cadd_cash20(0);carbon_addons_gameplay_frame();CHECK(M32(0x64330)==before);
  printf("cash deltas=20000/50000/100000/12345 final=%u repeats=0 wrong-profile=0 quick-race=0\n",total);
 } else if(!strcmp(argv[2],"cards_shown0")) { cards_remaining(6,0,6); }
 else if(!strcmp(argv[2],"cards_shown3")) { cards_remaining(6,3,3); }
 else if(!strcmp(argv[2],"cards_shown_all")) {
  for(unsigned limit=1;limit<=6;limit++)for(unsigned picked=0;picked<=limit;picked++)cards_remaining(limit,picked,limit-picked);
  cards_remaining(0,0,2);cards_remaining(0,3,-1);
 } else if(!strcmp(argv[2],"cards")) { for(unsigned i=0;i<=6;i++)cards(i,0); }
 else if(!strcmp(argv[2],"cards_latched")) { cards(6,1);cards(0,0); }
 else CHECK(0);
 free(G);return 0;
}
