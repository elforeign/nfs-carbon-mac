/* Retained movie startup; only stream services/renderers are synthetic. */
#include "funcs.h"
#include "host.h"
#include <stdarg.h>
#include <stdlib.h>
#include "carbon_fix_movie.c"

uint8_t *G;
int diag_on;
enum { MEMORY=0xC00000, STACK=0x200000, SELF=0x2000, AUDIO=0x4000 };
static unsigned checks, failures, polls, pumps, connects, ended, ready=3;
static unsigned audio_logs, movie_logs, cull_logs, counted_hidden;
static uint64_t ticks;
static char last_cull[512];
#define CHECK(x) do { ++checks; if (!(x)) { ++failures; \
    fprintf(stderr,"FAIL line %d: %s\n",__LINE__,#x); } } while (0)

uint64_t host_ticks(void) { return ticks; }
void diag_event(const char *fmt, ...) {
    char text[512]; va_list ap; va_start(ap,fmt);
    vsnprintf(text,sizeof text,fmt,ap); va_end(ap);
    if (strstr(text,"audio_poll")) { ++audio_logs; CHECK(strstr(text,"bytes=0")); }
    if (strstr(text,"K17 end")) ++movie_logs;
    if (strstr(text,"K27")) {
        ++cull_logs;strcpy(last_cull,text);
        char *p=strstr(text,"hidden=");if(p)counted_hidden=(unsigned)strtoul(p+7,NULL,10);
    }
}
void bad_jump(Cpu *c,uint32_t at) { (void)c;fprintf(stderr,"bad jump %x\n",at);abort(); }
void untranslated(Cpu *c,uint32_t at) { bad_jump(c,at); }
void host_import(Cpu *c,uint32_t at) { bad_jump(c,at); }
void abi_violation(Cpu *c,uint32_t fn,uint32_t b,uint32_t s,uint32_t d,uint32_t p,uint32_t sp) {
    (void)c;(void)b;(void)s;(void)d;(void)p;(void)sp;
    fprintf(stderr,"ABI %x\n",fn);abort();
}

static Cpu cpu(void) {
    Cpu c={0};c.esp=STACK;c.ecx=SELF;c.cw=0x37F;
    c.ebx=0xAA;c.esi=0xBB;c.edi=0xCC;c.ebp=0xDD;
    M32(c.esp)=0xFEED;return c;
}
static void reset(void) {
    memset(G,0,MEMORY);polls=pumps=connects=ended=0;ready=3;ticks=0;diag_on=0;
    M32(SELF+0x1CC)=1;M32(SELF+0x180)=AUDIO;
    M32(SELF+0x40)=0x5000;M32(0x5000)=0x6000;M32(0x600C)=0xFF000001;
    M32(SELF+0x4C)=0x7000;M32(0x7000)=0x8000;M32(0x8008)=0xFF000002;
}
static void buffered(Cpu *c) {
    CHECK(c->ecx==AUDIO);++polls;
    c->eax=!ended && polls>=ready?64:0;c->esp+=4;
}
void f_008D3CA0(Cpu *c) { carbon_fix_audio_poll(c,buffered); }
void f_008D3CF0(Cpu *c) { CHECK(c->ecx==AUDIO);c->eax=ended?2:0;c->esp+=4; }
void f_008D5CD0(Cpu *c) {
    CHECK(M32(arg(c,0))==0);++pumps;ticks+=1000000000ull;c->esp+=4;
}
void f_008D3BF0(Cpu *c) { bad_jump(c,0x8D3BF0); }
void f_008D57C0(Cpu *c) { bad_jump(c,0x8D57C0); }
void f_0088A905(Cpu *c) { bad_jump(c,0x88A905); }
void f_0088A951(Cpu *c) { bad_jump(c,0x88A951); }
void f_0088A49D(Cpu *c) { bad_jump(c,0x88A49D); }
void f_0088A918(Cpu *c) { ++connects;c->esp+=8; }
void f_0088A964(Cpu *c) { CHECK(arg(c,0)==AUDIO);c->esp+=12; }
void f_0088A4B0(Cpu *c) { c->esp+=8; }
void f_0088A4D6(Cpu *c) { c->esp+=12; }
void f_0088A92B(Cpu *c) { bad_jump(c,0x88A92B); }
void f_0088A97D(Cpu *c) { bad_jump(c,0x88A97D); }
void f_0088AED0(Cpu *c) { c->esp+=28; }
void f_0088A4EF(Cpu *c) { c->esp+=12; }
void f_0088A51E(Cpu *c) { c->esp+=12; }
void f_0088A607(Cpu *c) { x87_push(c,0);c->esp+=4; }
void dispatch(Cpu *c,uint32_t target) {
    if(target==0xFF000001) { c->eax=0;c->esp+=4; }
    else if(target==0xFF000002) { c->eax=0;c->esp+=8; }
    else bad_jump(c,target);
}
uint32_t call_guest(Cpu *c,uint32_t fn,int n,const uint32_t *args) {
    uint32_t esp=c->esp;
    for(int i=n-1;i>=0;--i) { c->esp-=4;M32(c->esp)=args[i]; }
    c->esp-=4;M32(c->esp)=0xFEED;
    if(fn==0x8D3CA0)f_008D3CA0(c);
    else if(fn==0x8D3CF0)f_008D3CF0(c);
    else if(fn==0x8D5CD0)f_008D5CD0(c);
    else bad_jump(c,fn);
    c->esp=esp;return c->eax;
}

#include "native.inc"

static void culler(Cpu *c) {
    for(unsigned i=0;i<11;++i)M8(c->ecx+0x18+0x20*i)=i!=0 && i!=10;
    c->eax=0xBEEF;c->esp+=16;
}
static void test_counts(void) {
    reset();diag_on=1;Cpu c=cpu();f_008887F3(&c);
    CHECK(audio_logs==1);CHECK(movie_logs==1);CHECK(connects==0);CHECK(polls==1);
    M32(0xA99BBC)=6;ticks=1000000000ull;c=cpu();carbon_fix_cull_check(&c,culler);
    CHECK(c.eax==0xBEEF);CHECK(c.esp==STACK+16);
    ticks=2000000000ull;c=cpu();carbon_fix_cull_check(&c,culler);
    CHECK(cull_logs==1);CHECK(counted_hidden==2);
    CHECK(strstr(last_cull,"groups=1,0,0,0,0,0,0,0,0,0,1"));
    /* Diagnostics off: delegate without dereferencing self or sampling time. */
    diag_on=0;ticks=3000000000ull;c=cpu();carbon_fix_cull_check(&c,culler);
    CHECK(cull_logs==1);
    printf("diagnostics: audio polls=%u movie ends=%u hidden=%u/11\n",audio_logs,movie_logs,counted_hidden);
}
static void test_movie(int retail) {
    reset();Cpu c=cpu();carbon_orig_008887F3(&c);
    CHECK(M32(SELF+0x8C)==0);CHECK(connects==0);CHECK(polls==1);
    printf("K17 retail delayed connects=%u polls=%u\n",connects,polls);
    if(retail) { CHECK(M32(SELF+0x8C)==1);return; }
    /* The premise-only wrapper deliberately preserves retail startup. */
    reset();c=cpu();f_008887F3(&c);
    CHECK(M32(SELF+0x8C)==0);CHECK(connects==0);CHECK(polls==1);CHECK(pumps==0);
    reset();ready=1;c=cpu();f_008887F3(&c);
    CHECK(M32(SELF+0x8C)==1);CHECK(connects==1);CHECK(polls==1);CHECK(pumps==0);
    /* Empty ended stream: both paths return without connecting or waiting. */
    for(unsigned fixed=0;fixed<2;++fixed) {
        reset();ended=1;c=cpu();
        if(fixed)f_008887F3(&c);else carbon_orig_008887F3(&c);
        CHECK(M32(SELF+0x8C)==0);CHECK(connects==0);CHECK(pumps==0);
        CHECK(ticks==0);CHECK(c.esp==STACK+4);CHECK(M32(SELF+0x1CC)==2);
    }
    /* No stream: compare every guest byte and all returned CPU state. */
    reset();M32(SELF+0x180)=0;c=cpu();Cpu native=c;
    uint8_t *saved=malloc(MEMORY),*expected=malloc(MEMORY);if(!saved||!expected)abort();
    memcpy(saved,G,MEMORY);carbon_orig_008887F3(&native);memcpy(expected,G,MEMORY);
    memcpy(G,saved,MEMORY);f_008887F3(&c);
    CHECK(!memcmp(&c,&native,sizeof c));CHECK(!memcmp(G,expected,MEMORY));
    CHECK(polls==0);CHECK(pumps==0);free(saved);free(expected);
}
int main(int argc,char **argv) {
    if(argc!=2)return 2;G=calloc(1,MEMORY);if(!G)return 2;
    if(!strcmp(argv[1],"counts"))test_counts();
    else if(!strcmp(argv[1],"movie"))test_movie(0);
    else if(!strcmp(argv[1],"retail"))test_movie(1);
    else return 2;
    printf("checks=%u failures=%u\n",checks,failures);free(G);return failures?1:0;
}
