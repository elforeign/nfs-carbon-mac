/* Synthetic guest callbacks around the retained translated Lua/CRT bodies. */
#include "funcs.h"
#include "host.h"
#include <setjmp.h>
#include <stdlib.h>

static void observed_longjmp(jmp_buf environment,int value) __attribute__((noreturn));
#define _longjmp observed_longjmp
#include "carbon_lua_unwind.c"
#undef _longjmp

uint8_t *G;
enum { MEMORY = 0xC00000, STACK = 0x200000, STATE = 0x2000,
       CALLBACK = 0xF1000000, PANIC = 0xF1000004, SETJMP = 0xF0000000 };
static unsigned checks,failures,level,max_depth,throw_at,status,panic_calls;
static unsigned entered[4],returned[4],caught[4],jumps,after_throw;
static uint32_t handlers[4],saved_jump[10];
static int retail,no_throw,other_cpu;
static Cpu *jump_cpu;
#define CHECK(x) do { ++checks;if(!(x)) { ++failures; \
    fprintf(stderr,"FAIL line %d: %s\n",__LINE__,#x); } } while(0)

void bad_jump(Cpu *c,uint32_t at) { (void)c;fprintf(stderr,"bad jump %x\n",at);abort(); }
void untranslated(Cpu *c,uint32_t at) { bad_jump(c,at); }
void guest_breakpoint(Cpu *c,uint32_t at) { bad_jump(c,at); }
void abi_violation(Cpu *c,uint32_t fn,uint32_t b,uint32_t s,uint32_t d,uint32_t p,uint32_t sp) {
    (void)c;(void)b;(void)s;(void)d;(void)p;(void)sp;
    fprintf(stderr,"ABI %x\n",fn);abort();
}
#include "crt.inc"
void host_import(Cpu *c,uint32_t at) {
    if(at==0x9C129C && fixture_crt(c,"_setjmp3")) return;
    if(at==0x9C1298) { fprintf(stderr,"PRIVATE STUB msvcr71.dll!longjmp\n");exit(1); }
    if(at==0x9C1290) {
        CHECK(arg(c,0)==1);CHECK(panic_calls==1);
        fprintf(stderr,"PANIC original exit(1) failures=%u\n",failures);
        exit(failures?1:7);
    }
    bad_jump(c,at);
}
#include "native.inc"

static void observed_longjmp(jmp_buf environment,int value) {
    Cpu *c=jump_cpu;
    CHECK(value==1);CHECK(c->eax==1);
    CHECK(c->ebp==saved_jump[0]);CHECK(c->ebx==saved_jump[1]);
    CHECK(c->edi==saved_jump[2]);CHECK(c->esi==saved_jump[3]);
    CHECK(c->esp==saved_jump[4]+4);CHECK(M32(c->fs_base)==saved_jump[6]);
    CHECK(carbon_lua_frame && carbon_lua_frame->cpu==c);
    CHECK(carbon_lua_frame->buffer==handlers[throw_at]+4);
    ++jumps;
    _longjmp(environment,value);
}

static Cpu initial(void) {
    Cpu c={0};c.esp=STACK;c.fs_base=0x1800;c.cw=0x37F;
    c.ebp=0xAABB;c.ebx=0xBBCC;c.esi=0xCCDD;c.edi=0xDDEE;
    c.eax=0x1234;c.ecx=0x2345;c.edx=0x3456;
    M32(c.fs_base)=UINT32_MAX;M32(0x9C129C)=SETJMP;
    M32(c.esp)=0xFEED;M32(c.esp+4)=STATE;
    M32(c.esp+8)=CALLBACK;M32(c.esp+12)=0xABCDE;
    return c;
}

static void invoke(Cpu *c) {
    /* Check the returned ABI even though the throwing translated frame is gone. */
    ABI_SAVE();
    if(retail)carbon_orig_0064DAF0(c);else f_0064DAF0(c);
    c->esp-=4;ABI_CHECK(0x64DAF0);c->esp+=4;
}

void dispatch(Cpu *c,uint32_t target) {
    if(target==SETJMP) { host_import(c,0x9C129C);return; }
    if(target==PANIC) { ++panic_calls;CHECK(arg(c,0)==STATE);c->esp+=4;return; }
    if(target!=CALLBACK) bad_jump(c,target);
    ABI_SAVE();
    unsigned current=++level;
    CHECK(current<=3);CHECK(arg(c,0)==STATE);CHECK(arg(c,1)==0xABCDE);
    ++entered[current];handlers[current]=M32(STATE+0x50);
    CHECK(handlers[current]==c->ebp-0x48u);
    Cpu entry=*c;
    if(current<max_depth) {
        uint32_t sp=c->esp,previous=M32(STATE+0x50);
        c->esp-=4;M32(c->esp)=0xABCDE;
        c->esp-=4;M32(c->esp)=CALLBACK;
        c->esp-=4;M32(c->esp)=STATE;
        c->esp-=4;M32(c->esp)=0xFEED;
        invoke(c);
        caught[current+1]=c->eax;
        CHECK(c->eax==(!no_throw && current+1==throw_at?status:0));
        CHECK(M32(STATE+0x50)==previous);
        CHECK(c->esp==sp-12);c->esp+=12;
    } else if(!no_throw) {
        /* Select an ancestor too: all abandoned native callback/protected
         * frames must disappear, rather than returning through their bodies. */
        M32(STATE+0x50)=handlers[throw_at];
        memcpy(saved_jump,G+handlers[throw_at]+4,sizeof saved_jump);
        c->ebp=0xDEAD;c->ebx=0xBAD1;c->edi=0xBAD2;c->esi=0xBAD3;
        M32(c->fs_base)=0x1A00;
        c->esp-=4;M32(c->esp)=status;
        c->esp-=4;M32(c->esp)=STATE;
        c->esp-=4;M32(c->esp)=0xFEED;
        jump_cpu=c;
        if(other_cpu) { Cpu copy=*c;f_0064DAB0(&copy); }
        else if(retail)carbon_orig_0064DAB0(c);
        else f_0064DAB0(c);
        CHECK(!"throw returned");++after_throw;
        /* Keep the deliberately broken return-only control reportable. */
        *c=entry;
    }
    ++returned[current];
    if(no_throw) {
        c->eax=0xC0FFEE;c->edx=0xABCDEF;
        M32(0x3000+current*4)=current;
    }
    ABI_CHECK(CALLBACK);c->esp+=4;level=current-1;
}

__attribute__((noinline)) static uintptr_t host_sp(void) {
    uintptr_t sp;
#if defined(__aarch64__)
    __asm__ volatile("mov %0, sp" : "=r"(sp));
#elif defined(__x86_64__)
    __asm__ volatile("mov %%rsp, %0" : "=r"(sp));
#else
#error fixture needs an explicit host stack-pointer reader
#endif
    return sp;
}

static void reset(unsigned depth,unsigned destination,unsigned error) {
    memset(G,0,MEMORY);memset(entered,0,sizeof entered);
    memset(returned,0,sizeof returned);memset(caught,0,sizeof caught);
    level=0;max_depth=depth;throw_at=destination;status=error;
    no_throw=other_cpu=0;jumps=after_throw=0;
    CHECK(carbon_lua_frame==NULL);
}

static void throwing(unsigned depth,unsigned destination,unsigned error,int seh) {
    reset(depth,destination,error);Cpu c=initial(),before=c;
    /* Both the -1 SEH sentinel and a real registration must round-trip. */
    uint32_t registration=seh?0x1900:UINT32_MAX;
    M32(c.fs_base)=registration;M32(0x190C)=7;
    uint32_t previous=0x4000;M32(STATE+0x50)=previous;
    uintptr_t sp=host_sp();invoke(&c);CHECK(host_sp()==sp);
    CHECK(c.eax==(destination==1?error:0));
    CHECK(M32(STATE+0x50)==previous);
    CHECK(c.ebp==before.ebp && c.ebx==before.ebx);
    CHECK(c.esi==before.esi && c.edi==before.edi && c.esp==before.esp+4);
    CHECK(M32(c.fs_base)==registration);CHECK(M32(0x190C)==7);
    CHECK(carbon_lua_frame==NULL);CHECK(jumps==1);CHECK(after_throw==0);
    for(unsigned i=1;i<=depth;++i) {
        CHECK(entered[i]==1);CHECK(returned[i]==(i<destination));
    }
    if(destination>1)CHECK(caught[destination]==error);
    /* level tracks synthetic callbacks and is intentionally skipped by unwind. */
    level=0;
}

static void normal(void) {
    reset(3,3,2);no_throw=1;retail=1;
    Cpu original=initial(),hooked=original;
    uint8_t *start=malloc(MEMORY),*expected=malloc(MEMORY);
    if(!start || !expected)abort();memcpy(start,G,MEMORY);
    invoke(&original);memcpy(expected,G,MEMORY);
    memcpy(G,start,MEMORY);level=0;retail=0;invoke(&hooked);
    CHECK(hooked.eax==0);CHECK(!memcmp(&hooked,&original,sizeof hooked));
    CHECK(!memcmp(G,expected,MEMORY));CHECK(carbon_lua_frame==NULL);
    free(start);free(expected);
}

int main(int argc,char **argv) {
    if(argc!=2)return 2;
    G=calloc(1,MEMORY);if(!G)abort();
    if(!strcmp(argv[1],"retail")) {
        retail=1;throwing(1,1,2,0);
    } else if(!strcmp(argv[1],"panic") || !strcmp(argv[1],"unowned")) {
        Cpu c=initial();M32(c.esp+8)=2;
        M32(STATE+0x10)=0x3100;M32(0x3128)=PANIC;
        if(!strcmp(argv[1],"unowned"))M32(STATE+0x50)=0x4000;
        f_0064DAB0(&c);CHECK(!"original throw returned");
    } else if(!strcmp(argv[1],"other-cpu")) {
        reset(1,1,2);Cpu c=initial();other_cpu=1;invoke(&c);
        CHECK(!"mismatched CPU throw returned");
    } else if(!strcmp(argv[1],"depth2")) {
        throwing(2,1,2,1);
    } else if(!strcmp(argv[1],"good")) {
        for(unsigned depth=1;depth<=3;++depth)
            for(unsigned destination=1;destination<=depth;++destination)
                for(unsigned error=1;error<=5;++error)
                    for(int seh=0;seh<=1;++seh)throwing(depth,destination,error,seh);
        normal();
        uintptr_t sp=host_sp();
        for(unsigned i=0;i<10000;++i)throwing(3,i%3+1,i%5+1,i%2);
        CHECK(host_sp()==sp);CHECK(carbon_lua_frame==NULL);
        printf("status cases=60 cycles=10000 guest/host restoration=PASS normal byte identity=PASS\n");
    } else return 2;
    printf("checks=%u failures=%u\n",checks,failures);
    free(G);return failures?1:0;
}
