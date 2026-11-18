/* Synthetic guest ABI fixture; never loads or executes a game image. */
#include "host.h"
#include <assert.h>
#include <errno.h>
#include <math.h>
#include <stdlib.h>
#include <stdarg.h>
#include <sys/mman.h>
uint8_t *G;
int diag_on,boot_trace;
const char *game_dir=".";
__thread uint32_t last_error;
static uint32_t next=0x10000;
static uint32_t sizes[1<<20];
uint32_t galloc(uint32_t n) { uint32_t a=next;next=(next+n+15)&~15u;assert(next<(1<<20));sizes[a/16]=n;memset(G+a,0,n);return a; }
uint32_t gmalloc(uint32_t n) { return galloc(n); }
uint32_t gmalloc_size(uint32_t a) { return sizes[a/16]; }
void gfree(uint32_t a) { sizes[a / 16] = 0; }
uint32_t gstr(const char *s) { uint32_t a=galloc(strlen(s)+1);strcpy((char *)G+a,s);return a; }
void diag_event(const char *fmt,...) { (void)fmt; }
void diag_begin_exit(void) { }
void app_restart_game_exited(int successful) { (void)successful; }
int private_crt(Cpu *, const char *);
enum { THREAD_GUEST = 0x410000, THREAD_STACK = 0x9000, THREAD_CYCLES = 5000 };
static unsigned registrations, callbacks, freed_at_entry;
static HostFn trampoline;
uint32_t host_fn(HostFn fn, const char *name) {
    assert(!strcmp(name, "CRT thread entry"));
    trampoline = fn;
    /* Count all registrations so the old code can run beyond the real table limit. */
    return HOSTFN_BASE + 4 * registrations++;
}
uint32_t call_guest(Cpu *c, uint32_t fn, int n, const uint32_t *args) {
    if (fn == THREAD_GUEST) {
        assert(n == 1 && args[0] == callbacks);
        ++callbacks;
        freed_at_entry += !gmalloc_size(M32(THREAD_STACK + 4));
        if (args[0] & 1) {
            M32(THREAD_STACK - 4) = 42;
            c->esp = THREAD_STACK - 8;
            private_crt(c, "_endthreadex");
            abort();
        }
        return 42;
    }
    assert(n == 2);
    return strcmp((char *)G + args[0], (char *)G + args[1]);
}
int private_resolve(const char *s,char *out,size_t n) { snprintf(out,n,"%s",s);return 0; }
int win32_heap(Cpu *c,const char *fn) { (void)c;(void)fn;abort(); }
int private_win32(Cpu *c,const char *fn) { (void)c;(void)fn;return 0; }
int win32_threads(Cpu *c, const char *fn) {
    assert(!strcmp(fn, "ExitThread"));
    pthread_exit((void *)(uintptr_t)arg(c, 0));
}
static void *run_trampoline(void *opaque) {
    Cpu *c = opaque;
    assert(trampoline(c) && c->esp == THREAD_STACK + 8);
    return (void *)(uintptr_t)c->eax;
}
uint32_t private_thread_create(uint32_t stack, uint32_t start, uint32_t param,
                               uint32_t flags, uint32_t *tid) {
    assert(!stack && !flags && start >= HOSTFN_BASE && (start - HOSTFN_BASE) / 4 < registrations);
    Cpu thread = {.esp = THREAD_STACK};
    M32(THREAD_STACK + 4) = param;
    pthread_t child;
    void *result;
    assert(!pthread_create(&child, NULL, run_trampoline, &thread));
    assert(!pthread_join(child, &result) && (uintptr_t)result == 42);
    *tid = callbacks;
    return 17;
}
uint32_t private_import_data(const char *);
static unsigned checks;
static void check(int yes,const char *why) { ++checks;if(!yes){fprintf(stderr,"FAIL %s (check %u)\n",why,checks);exit(1);} }
static uint32_t invoke(Cpu *c,const char *name,int n,...) {
    c->esp=0x8000;M32(c->esp)=0x12345678;
    va_list args;va_start(args,n);for(int i=0;i<n;i++)M32(c->esp+4+4*i)=va_arg(args,uint32_t);va_end(args);
    check(private_crt(c,name),name);
    check(c->esp==0x8004,"cdecl preserves caller arguments");
    return c->eax;
}
static void thread_cycles(Cpu *c) {
    uint32_t tid = galloc(4);
    for (uint32_t i = 0; i < THREAD_CYCLES; ++i) {
        uint32_t handle = invoke(c, "_beginthreadex", 6, 0u, 0u, (uint32_t)THREAD_GUEST, i, 0u, tid);
        check(handle == 17 && M32(tid) == i + 1, "CRT thread result and thread ID");
    }
    printf("CRT thread cycles=%u, dispatch slots=%u, contexts freed before entry=%u\n",
           callbacks, registrations, freed_at_entry);
    check(registrations == 1 && callbacks == THREAD_CYCLES && freed_at_entry == THREAD_CYCLES,
          "CRT trampoline is registered once and releases its context before guest entry");
}
static void strtol_width(Cpu *c) {
    static const struct {
        const char *text;
        uint32_t base, result;
        int error;
    } cases[] = {
        {"100000000!", 16, INT32_MAX, ERANGE},
        {"2147483648!", 10, INT32_MAX, ERANGE},
        {"-2147483649!", 10, (uint32_t)INT32_MIN, ERANGE},
        {"99999999999999999999999999!", 10, INT32_MAX, ERANGE},
        {"-99999999999999999999999999!", 10, (uint32_t)INT32_MIN, ERANGE},
        {"2147483647!", 10, INT32_MAX, 0},
        {"-2147483648!", 10, (uint32_t)INT32_MIN, 0},
        {"   -0x13!", 0, (uint32_t)-19, 0},
        {"0x7fffffff!", 0, INT32_MAX, 0},
    };
    unsigned passed = 0, count = sizeof cases / sizeof *cases;
    uint32_t end = galloc(4);
    for (unsigned i = 0; i < count; ++i) {
        uint32_t text = gstr(cases[i].text);
        errno = 0;
        uint32_t result = invoke(c, "strtol", 3, text, end, cases[i].base);
        uint32_t guest_errno = invoke(c, "_errno", 0);
        if (result == cases[i].result && M32(end) == text + strlen(cases[i].text) - 1 &&
            (int)M32(guest_errno) == cases[i].error) ++passed;
    }
    printf("CRT strtol cases=%u/%u\n", passed, count);
    check(passed == count, "Win32 strtol result, end pointer and errno");
}
int main(int argc, char **argv) {
    G=calloc(1,1<<20);assert(G);Cpu c={0};
    if (argc == 2) {
        if (!strcmp(argv[1], "thread")) thread_cycles(&c);
        else if (!strcmp(argv[1], "strtol")) strtol_width(&c);
        else abort();
        free(G);
        return 0;
    }
    uint32_t p=invoke(&c,"malloc",1,32u);memcpy(G+p,"abcdef",7);
    check(p&&!(p&15),"guest allocation");
    check(invoke(&c,"strlen",1,p)==6,"guest strlen");
    check(invoke(&c,"memmove",3,p+1,p,5u)==p+1,"memmove destination");
    check(!memcmp(G+p,"aabcde",6),"overlapping guest memcpy");
    uint32_t q=invoke(&c,"realloc",2,p,96u);check(!memcmp(G+q,"aabcde",6),"realloc preserves guest bytes");
    uint32_t aligned=invoke(&c,"_aligned_malloc",2,33u,256u);check(!(aligned&255),"large guest alignment");
    strcpy((char *)G+aligned,"aligned payload");uint32_t ar=invoke(&c,"_aligned_realloc",3,aligned,512u,512u);
    check(!(ar&511)&&!strcmp((char *)G+ar,"aligned payload"),"aligned realloc payload and alignment");
    uint32_t text=gstr("AbCdEF");check(invoke(&c,"_strnicmp",3,text,gstr("abcdxy"),4u)==0,"case folding");
    uint32_t wide=galloc(16);M16(wide)='A';M16(wide+2)=0x20ac;M16(wide+4)=0;
    check(invoke(&c,"wcslen",1,wide)==2,"guest wchar is 16 bits");
    uint32_t wd=galloc(16);invoke(&c,"wcscpy",2,wd,wide);check(!memcmp(G+wd,G+wide,6),"UTF-16 copy");
    invoke(&c,"srand",1,1u);uint32_t r1=invoke(&c,"rand",0),r2=invoke(&c,"rand",0);
    check(r1==41&&r2==18467,"MS CRT random sequence");
    invoke(&c,"srand",1,1u);check(invoke(&c,"rand",0)==r1,"srand resets shared state");
    uint32_t buf=galloc(128),fmt=gstr("%s:%I64u:%.2f"),va=galloc(20);M32(va)=gstr("guest");M64(va+4)=4294967297ull;
    double d=1.25;memcpy(G+va+12,&d,8);
    check(invoke(&c,"vsprintf",3,buf,fmt,va)==21,"mixed x86 vararg count");
    check(!strcmp((char *)G+buf,"guest:4294967297:1.25"),"32-bit va_list decoding");
    memset(G+buf,0xcc,128);check(invoke(&c,"_snprintf",4,buf,5u,gstr("%s"),text)==UINT32_MAX,"bounded MS snprintf result");
    check(!memcmp(G+buf,"AbCdE",5)&&G[buf+5]==0xcc,"bounded formatting guard byte");
    check(invoke(&c,"_snprintf",5,buf,128u,gstr("%.*s"),UINT32_MAX,text)==6&&!strcmp((char *)G+buf,"AbCdEF"),"negative precision is omitted");
    c.cw=0x27f;uint32_t cw=invoke(&c,"_controlfp",2,0x200u,0x300u);check((cw&0x300)==0x200&&(c.cw&0xC00)==0x800,"MS control flags map to x87 rounding");
    c.top=4;c.st[4]=3.0;c.st[5]=2.0;invoke(&c,"_CIpow",0);check(c.top==5&&c.st[5]==8.0,"binary x87 intrinsic operand order");
    uint32_t sorted=galloc(12);memcpy(G+sorted,"ccc\0aaa\0bbb",12);
    invoke(&c,"qsort",4,sorted,3u,4u,1u);check(!memcmp(G+sorted,"aaa\0bbb\0ccc",12),"native qsort calls guest comparator");
    uint32_t object=galloc(28),copy=galloc(28),longtext=gstr("a long string above the SSO capacity");
    c.ecx=object;c.esp=0x8000;M32(c.esp+4)=longtext;
    check(private_crt(&c,"??0?$basic_string@DU?$char_traits@D@std@@V?$allocator@D@2@@std@@QAE@PBD@Z")&&c.esp==0x8008,"C++ string constructor thiscall cleanup");
    check(M32(object+20)==strlen((char *)G+longtext)&&M32(object+24)>=16&&!strcmp((char *)G+M32(object+4),(char *)G+longtext),"VC7 string long representation");
    c.ecx=copy;c.esp=0x8000;M32(c.esp+4)=object;
    check(private_crt(&c,"??0?$basic_string@DU?$char_traits@D@std@@V?$allocator@D@2@@std@@QAE@ABV01@@Z")&&M32(copy+4)!=M32(object+4)&&!strcmp((char *)G+M32(copy+4),(char *)G+longtext),"C++ string copy owns separate storage");
    c.ecx=copy;c.esp=0x8000;check(private_crt(&c,"??1?$basic_string@DU?$char_traits@D@std@@V?$allocator@D@2@@std@@QAE@XZ")&&c.esp==0x8004,"C++ string destructor thiscall cleanup");
    uint32_t scan=gstr("-7 42 2.5"),sf=gstr("%ld %I64u %lf"),results=galloc(24);
    check(invoke(&c,"sscanf",5,scan,sf,results,results+8,results+16)==3,"scanf conversions");
    memcpy(&d,G+results+16,8);check((int32_t)M32(results)==-7&&M32(results+4)==0&&M64(results+8)==42&&d==2.5,"Windows long and 64-bit scanf layouts");
    uint32_t a=invoke(&c,"__p__fmode",0);M32(a)=17;check(invoke(&c,"__p__fmode",0)==a,"stable guest CRT data accessor");
    check(private_import_data("msvcr71.dll!_iob")!=0,"data import has guest storage");
    c.top=3;c.st[3]=1.0;c.esp=0x8000;check(private_crt(&c,"_CIacos"),"x87 intrinsic");check(c.top==3&&fabs(c.st[3])<1e-10&&c.esp==0x8004,"x87 intrinsic stack convention");
    c.esp=0x8000;check(!private_crt(&c,"longjmp")&&c.esp==0x8000,"unsupported unwinding fails before state changes");
    uint32_t jump=galloc(80),seh=galloc(16);memset(G+jump,0xa5,80);
    c.fs_base=0x7000;M32(c.fs_base)=UINT32_MAX;
    c.ebp=0x10203040;c.ebx=0x50607080;c.edi=0x90a0b0c0;c.esi=0xd0e0f001;c.ecx=42;
    check(invoke(&c,"_setjmp3",2,jump+4,0u)==0,"setjmp initial return");
    check(M32(jump+4)==c.ebp&&M32(jump+8)==c.ebx&&M32(jump+12)==c.edi&&M32(jump+16)==c.esi,"setjmp saved registers");
    check(M32(jump+20)==0x8000&&M32(jump+24)==0x12345678,"setjmp saved stack and continuation");
    check(M32(jump+28)==UINT32_MAX&&M32(jump+32)==UINT32_MAX&&M32(jump+36)==0x56433230&&M32(jump+40)==0,"setjmp no SEH registration");
    check(c.edx==jump+4&&c.ecx==42,"setjmp volatile register effects without SEH");
    check(M32(jump)==0xa5a5a5a5&&M32(jump+44)==0xa5a5a5a5&&M32(jump+68)==0xa5a5a5a5,"setjmp untouched unwind data and canaries");
    M32(c.fs_base)=seh;M32(seh+12)=7;c.ecx=99;
    check(invoke(&c,"_setjmp3",2,jump+4,0u)==0&&M32(jump+28)==seh&&M32(jump+32)==7&&c.ecx==0,"setjmp registered SEH try level");
    c.esp=0x8000;M32(c.esp+4)=jump+4;M32(c.esp+8)=1;M32(jump+4)=0xfeed;
    check(!private_crt(&c,"_setjmp3")&&c.esp==0x8000&&M32(jump+4)==0xfeed,"extended setjmp fails before state changes");
    printf("CRT ABI PASS checks=%u\n",checks);
    thread_cycles(&c);
    strtol_width(&c);
    free(G);
    return 0;
}
