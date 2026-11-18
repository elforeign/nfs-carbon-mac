/* Native 32-bit MS CRT bridge for private PE bring-up. Not a host-ABI dlsym bridge:
 * pointers, FILEs, time_t, wchar_t, va_list and x87 values are marshalled explicitly.
 * Unsupported unwinding/format conversions fail closed through the import router.
 */
#include "host.h"
#include <ctype.h>
#include <errno.h>
#include <fcntl.h>
#include <math.h>
#include <stdlib.h>
#include <strings.h>
#include <sys/stat.h>
#include <sys/time.h>
#include <time.h>
#include <unistd.h>
#define IS(n) (!strcmp(fn, n))
#define CR(v) RET(v, 0) /* x86 __cdecl: only pop the return address */
#define A(n) arg(c, n)
#define P(n) ((char *)G + A(n))
extern int private_resolve(const char *, char *, size_t);
extern int private_win32(Cpu *, const char *);
extern int win32_threads(Cpu *, const char *);
extern uint32_t private_thread_create(uint32_t, uint32_t, uint32_t, uint32_t, uint32_t *);

#include "carbon_y00_heap.h"

static uint32_t globals;
static unsigned random_seed = 1;
static uint32_t crt_globals(void) {
    if (!globals) globals = galloc(32 + 128 * 32);
    return globals;
}
uint32_t private_import_data(const char *name) {
    const char *fn = strchr(name, '!') + 1;
    if (IS("_adjust_fdiv")) return crt_globals();
    if (IS("_iob")) return crt_globals() + 32; /* three MSVCRT FILE records (32 bytes) */
    return 0;
}
static FILE *files[128];
static uint32_t file_token(int i) { return crt_globals() + 32 + 32 * i; }
static FILE *file_ptr(uint32_t a) {
    if (!files[0]) { files[0] = stdin; files[1] = stdout; files[2] = stderr; }
    for (int i = 0; i < 128; ++i) if (a == file_token(i)) return files[i];
    return NULL;
}
static uint32_t file_new(FILE *f) {
    if (!f) return 0;
    file_ptr(0);
    for (int i = 3; i < 128; ++i) if (!files[i]) { files[i] = f; return file_token(i); }
    fclose(f); return 0;
}
static uint32_t fp_return(Cpu *c, double v) {
    c->top = (c->top - 1) & 7; c->st[c->top] = v;
    return 0;
}
static double fp_arg(Cpu *c, unsigned n) { double d; memcpy(&d, G + c->esp + 4 + n * 4, 8); return d; }
static uint32_t str_result(const char *p) { return p ? (uint32_t)((const uint8_t *)p - G) : 0; }
static uint32_t callbacks[1024];
static unsigned callback_count;
/* WinMain ends the game with msvcr71 _exit(0) (call at 006B8F59), not ExitProcess. On Windows _exit skips the CRT's
 * onexit list but the process still detaches its DLLs; the host's atexit cleanup (audio, saves, Restart game's
 * relaunch) is that layer, so a clean _exit(0) arms the relaunch and leaves through exit(). */
void app_restart_game_exited(int successful);
static void crt_exit_callbacks(Cpu *c) {
    while (callback_count) call_guest(c, callbacks[--callback_count], 0, NULL);
}
static int32_t cmp_guest(Cpu *c, uint32_t fn, uint32_t a, uint32_t b) {
    uint32_t args[] = {a, b}; return (int32_t)call_guest(c, fn, 2, args);
}
/* Guest varargs are a byte stream. Host varargs cannot consume an x86 va_list. */
static int format_guest(char *out, size_t cap, const char *fmt, uint32_t va) {
    size_t used = 0;
    for (const char *p = fmt; *p;) {
        char tmp[8192], spec[96];
        if (*p != '%') { tmp[0] = *p++; tmp[1] = 0; }
        else {
            const char *start = p++; size_t n = 0;
            if (*p == '%') { tmp[0] = *p++; tmp[1] = 0; goto append; }
            spec[n++] = '%';
            while (*p && strchr("-+ #0", *p)) { if (n >= 70) return -1; spec[n++] = *p++; }
            if (*p == '*') {
                int width = (int32_t)M32(va); va += 4; p++;
                n += snprintf(spec + n, sizeof spec - n, "%d", width);
            } else while (isdigit((unsigned char)*p)) { if (n >= 70) return -1; spec[n++] = *p++; }
            if (*p == '.') {
                size_t dot = n;
                spec[n++] = *p++;
                if (*p == '*') { int precision = (int32_t)M32(va); va += 4; p++; if(precision<0)n=dot;else n += snprintf(spec+n, sizeof spec-n, "%d", precision); }
                else while (isdigit((unsigned char)*p)) { if (n >= 70) return -1; spec[n++] = *p++; }
            }
            int wide = 0, wide_int = 0;
            if (!strncmp(p, "I64", 3)) { wide_int = 1; p += 3; }
            else if (*p == 'l') { p++; if (*p == 'l') { wide_int = 1; p++; } else wide = 1; }
            else if (*p == 'h') { p++; if (*p == 'h') p++; }
            char conv = *p++; if (!conv || n > 80 || p-start > 90) return -1;
            if (wide_int) { spec[n++]='l'; spec[n++]='l'; }
            spec[n++]=conv; spec[n]=0;
            uint32_t v = M32(va);
            int wrote;
            if (strchr("diouxX", conv)) {
                if (wide_int) { uint64_t q = M64(va); va += 8; wrote = snprintf(tmp,sizeof tmp,spec,q); }
                else { va += 4; wrote = snprintf(tmp,sizeof tmp,spec,v); }
            } else if (strchr("fFeEgGaA", conv)) { double d; memcpy(&d,G+va,8); va += 8; wrote=snprintf(tmp,sizeof tmp,spec,d); }
            else if (conv == 's' && !wide) { va+=4; wrote=snprintf(tmp,sizeof tmp,spec,v?(char *)G+v:"(null)"); }
            else if (conv == 'c' && !wide) { va+=4; wrote=snprintf(tmp,sizeof tmp,spec,v); }
            else if (conv == 'p') { va+=4; wrote=snprintf(tmp,sizeof tmp,"%08x",v); }
            else if (conv == 'n') { va+=4; if(v) M32(v)=(uint32_t)used; tmp[0]=0; wrote=0; }
            else return -1;
            if (wrote < 0 || wrote >= (int)sizeof tmp) return -1;
        }
append:;
        size_t len = strlen(tmp);
        if (used < cap) { size_t copy = len < cap-used ? len : cap-used; memcpy(out+used,tmp,copy); }
        used += len;
    }
    if (used < cap) out[used] = 0; /* MS _snprintf leaves a truncated result unterminated */
    return (int)used;
}
static uint32_t guest_tm(const struct tm *t) {
    static uint32_t a;
    if (!t) return 0;
    if (!a) a=galloc(36);
    int values[]={t->tm_sec,t->tm_min,t->tm_hour,t->tm_mday,t->tm_mon,t->tm_year,t->tm_wday,t->tm_yday,t->tm_isdst};
    memcpy(G+a,values,36); return a;
}
static struct tm host_tm(uint32_t a) {
    struct tm t={0}; int v[9]; memcpy(v,G+a,36);
    t.tm_sec=v[0];t.tm_min=v[1];t.tm_hour=v[2];t.tm_mday=v[3];t.tm_mon=v[4];t.tm_year=v[5];t.tm_wday=v[6];t.tm_yday=v[7];t.tm_isdst=v[8];return t;
}
static int begin_cdecl(Cpu *c) { /* thread trampoline consumes the Win32 single argument */
    uint32_t ctx = A(0), start = M32(ctx), args[] = {M32(ctx + 4)};
    gfree(ctx); /* The guest entry may call _endthreadex instead of returning. */
    RET(call_guest(c, start, 1, args), 1);
}
static uint32_t begin_cdecl_entry;
static void register_begin_cdecl(void) {
    begin_cdecl_entry = host_fn(begin_cdecl, "CRT thread entry");
}
static uint32_t invoke_win32(Cpu *c, const char *fn, int n, const uint32_t *args) {
    uint32_t sp=c->esp;
    for(int i=n-1;i>=0;i--){c->esp-=4;M32(c->esp)=args[i];}
    c->esp-=4;M32(c->esp)=0;
    if(!private_win32(c,fn)){c->esp=sp;return UINT32_MAX;}
    uint32_t result=c->eax;c->esp=sp;return result;
}
typedef struct {
    uint32_t handle;
    int failed;
} CareerSave;
static _Thread_local CareerSave *career_save;

void carbon_career_save(Cpu *c, void (*original)(Cpu *)) {
    uint32_t self = c->ecx;
    if (M32(self + 0x70) != 0xb || !M32(self + 0x4e4)) {
        original(c);
        return;
    }
    CareerSave save = { .handle = UINT32_MAX };
    CareerSave *previous = career_save;
    career_save = &save;
    original(c);
    career_save = previous;
    // The retail task clears its status after _close. Restore its failed-open result for state 0xc.
    if (save.failed) {
        M32(self + 0x4d8) = 1;
        M32(self + 0x4dc) = 7;
    }
}
static int32_t file_time32(uint32_t a) {
    uint64_t t=M64(a);return t?(int32_t)(t/10000000ull-11644473600ull):-1;
}
typedef struct { Cpu *cpu; uint32_t fn; } SortContext;
static int sort_compare(void *opaque,const void *a,const void *b) {
    SortContext *ctx=opaque;
    return cmp_guest(ctx->cpu,ctx->fn,(uint32_t)((const uint8_t *)a-G),(uint32_t)((const uint8_t *)b-G));
}
static uint32_t ms_control(uint16_t cw) {
    uint32_t v=0;
    if(cw&1)v|=0x10;if(cw&2)v|=0x80000;if(cw&4)v|=8;
    if(cw&8)v|=4;if(cw&16)v|=2;if(cw&32)v|=1;
    v|=(cw&0xC00)>>2;
    v|=(cw&0x300)==0?0x20000:(cw&0x300)==0x200?0x10000:0;
    return v;
}
static uint16_t x87_control(uint32_t ms,uint16_t old) {
    uint16_t cw=old&~0xF3F;
    if(ms&0x10)cw|=1;if(ms&0x80000)cw|=2;if(ms&8)cw|=4;
    if(ms&4)cw|=8;if(ms&2)cw|=16;if(ms&1)cw|=32;
    cw|=(ms&0x300)<<2;
    cw|=(ms&0x30000)==0x20000?0:(ms&0x30000)==0x10000?0x200:0x300;
    return cw;
}
static void find_data(uint32_t dest,uint32_t win) {
    M32(dest)=M32(win);M32(dest+4)=file_time32(win+4);M32(dest+8)=file_time32(win+12);
    M32(dest+12)=file_time32(win+20);M32(dest+16)=M32(win+32);
    memcpy(G+dest+20,G+win+44,260);
}
static uint32_t find_buffer;
static int exception_destruct(Cpu *c) { if(M32(c->ecx+8)&&M32(c->ecx+4))gfree(M32(c->ecx+4));RET(c->ecx,0); }

int private_crt(Cpu *c, const char *fn) {
    if (IS("_setjmp3")) {
        /* Decoded x86 CRT save path. Extended unwind forms stay unsupported. */
        if (A(1)) return 0;
        uint32_t buffer=A(0), registration=M32(c->fs_base);
        M32(buffer)=c->ebp; M32(buffer+4)=c->ebx;
        M32(buffer+8)=c->edi; M32(buffer+12)=c->esi;
        M32(buffer+16)=c->esp; M32(buffer+20)=M32(c->esp);
        M32(buffer+24)=registration;
        M32(buffer+28)=registration==UINT32_MAX?UINT32_MAX:M32(registration+12);
        M32(buffer+32)=0x56433230u; M32(buffer+36)=0;
        c->edx=buffer;
        if (registration!=UINT32_MAX) c->ecx=0;
        CR(0);
    }
    if (IS("_findfirst") || IS("_findnext")) {
        if(!find_buffer)find_buffer=galloc(320);
        uint32_t args[]={A(0),find_buffer};
        uint32_t result=invoke_win32(c,IS("_findfirst")?"FindFirstFileA":"FindNextFileA",2,args);
        if(IS("_findfirst")){if(result!=UINT32_MAX)find_data(A(1),find_buffer);CR(result);}
        if(result)find_data(A(1),find_buffer);CR(result?0:-1);
    }
    if (IS("_findclose")) { uint32_t args[]={A(0)};CR(invoke_win32(c,"FindClose",1,args)?0:-1); }
    if (IS("__security_error_handler") || IS("_purecall") || IS("?terminate@@YAXXZ")) {
        fprintf(stderr,"private CRT fatal: %s\n",fn);if(diag_on)diag_event("private CRT fatal: %s",fn);exit(3);
    }
    if (IS("raise")) { if(!A(0))CR(0);fprintf(stderr,"private CRT raise(%u)\n",A(0));exit(128+(A(0)&127)); }
    if (IS("??0exception@@QAE@XZ") || IS("??0exception@@QAE@ABV0@@Z")) {
        static uint32_t vt;if(!vt){vt=galloc(4);M32(vt)=host_fn(exception_destruct,"CRT exception destructor");}
        uint32_t self=c->ecx;M32(self)=vt;M32(self+4)=0;M32(self+8)=0;
        if(IS("??0exception@@QAE@ABV0@@Z")){uint32_t msg=M32(A(0)+4);if(msg){uint32_t n=strlen((char *)G+msg)+1;M32(self+4)=gmalloc(n);memcpy(G+M32(self+4),G+msg,n);M32(self+8)=1;}RET(self,1);}
        RET(self,0);
    }
    if (IS("??1exception@@UAE@XZ")) return exception_destruct(c);
    if (IS("??1type_info@@UAE@XZ")) { if(M32(c->ecx+4))gfree(M32(c->ecx+4));RET(c->ecx,0); }
    if (IS("malloc")) CR(carbon_y00_malloc(c,A(0)));
    if (IS("calloc")) { uint64_t n=(uint64_t)A(0)*A(1); CR(n<=UINT32_MAX?gmalloc((uint32_t)n):0); }
    if (IS("free") || IS("_aligned_free")) { uint32_t a=A(0); if(a) carbon_y00_free(IS("free")?a:M32(a-4)); CR(0); }
    if (IS("realloc") || IS("_aligned_realloc")) {
        uint32_t old=A(0), n=A(1), base=old;
        if (IS("_aligned_realloc") && old) base=M32(old-4);
        if (!n) { if(base) carbon_y00_free(base); CR(0); }
        uint32_t align=IS("realloc")?1:A(2); if(!align || (align&(align-1))) CR(0);
        if(n>UINT32_MAX-align-4) CR(0);
        uint32_t raw=gmalloc(n+align+4), a=IS("realloc")?raw:(raw+4+align-1)&~(align-1);
        if(old) { uint32_t size=carbon_y00_size(base); uint32_t offset=old-base; size=size>offset?size-offset:0; memcpy(G+a,G+old,size<n?size:n); carbon_y00_free(base); }
        if(IS("_aligned_realloc")) M32(a-4)=raw; CR(a);
    }
    if (IS("_aligned_malloc")) { uint32_t n=A(0),align=A(1); if(!align||(align&(align-1))||n>UINT32_MAX-align-4) CR(0); uint32_t raw=gmalloc(n+align+4),a=(raw+4+align-1)&~(align-1); M32(a-4)=raw; CR(a); }
    if (IS("memcpy") || IS("memmove")) { memmove(P(0),P(1),A(2)); CR(A(0)); }
    if (IS("memset")) { memset(P(0),A(1),A(2)); CR(A(0)); }
    if (IS("memcmp")) CR(memcmp(P(0),P(1),A(2)));
    if (IS("strlen")) CR(strlen(P(0)));
    if (IS("strcmp") || IS("strcoll")) CR(strcmp(P(0),P(1)));
    if (IS("strncmp")) CR(strncmp(P(0),P(1),A(2)));
    if (IS("_strcmpi")) CR(strcasecmp(P(0),P(1)));
    if (IS("_strnicmp")) CR(strncasecmp(P(0),P(1),A(2)));
    if (IS("strncpy")) { strncpy(P(0),P(1),A(2)); CR(A(0)); }
    if (IS("_mbscpy")) { strcpy(P(0),P(1)); CR(A(0)); }
    if (IS("_mbscat")) { strcat(P(0),P(1)); CR(A(0)); }
    if (IS("strncat")) { strncat(P(0),P(1),A(2)); CR(A(0)); }
    if (IS("strchr")) CR(str_result(strchr(P(0),A(1))));
    if (IS("strrchr")) CR(str_result(strrchr(P(0),A(1))));
    if (IS("strstr")) CR(str_result(strstr(P(0),P(1))));
    if (IS("strcspn")) CR(strcspn(P(0),P(1)));
    if (IS("strtok")) CR(str_result(strtok(A(0)?P(0):NULL,P(1))));
    if (IS("strtol")) {
        char *end = P(0);
        long v = strtol(P(0), &end, A(2));
        if (v > INT32_MAX) { errno = ERANGE; v = INT32_MAX; }
        if (v < INT32_MIN) { errno = ERANGE; v = INT32_MIN; }
        if (A(1)) M32(A(1)) = str_result(end);
        CR((uint32_t)v);
    }
    if (IS("strtoul")) { char *end; uint32_t v=(uint32_t)strtoul(P(0),&end,A(2)); if(A(1))M32(A(1))=str_result(end); CR(v); }
    if (IS("atoi")) CR(atoi(P(0)));
    if (IS("abs")) CR(abs((int32_t)A(0)));
    if (IS("isdigit")) CR(isdigit((unsigned char)A(0)));
    if (IS("isprint")) CR(isprint((unsigned char)A(0)));
    if (IS("isspace")) CR(isspace((unsigned char)A(0)));
    if (IS("tolower")) CR(tolower(A(0)==UINT32_MAX?EOF:(unsigned char)A(0)));
    if (IS("toupper")) CR(toupper(A(0)==UINT32_MAX?EOF:(unsigned char)A(0)));
    if (IS("wcslen")) { uint32_t n=0; while(M16(A(0)+2*n))n++; CR(n); }
    if (IS("wcscpy")) { uint32_t n=0; do { M16(A(0)+2*n)=M16(A(1)+2*n); }while(M16(A(1)+2*n++)); CR(A(0)); }
    if (IS("rand")) { random_seed=random_seed*214013u+2531011u; CR((random_seed>>16)&32767); }
    /* srand and rand share the MS generator via a guest TLS-independent cell. */
    if (IS("srand")) { random_seed=A(0); CR(0); }
    if (IS("getenv")) { /* Host secrets are not exposed as guest environment. */
        const char *v=!strcasecmp(P(0),"TEMP")||!strcasecmp(P(0),"TMP")?getenv("TMPDIR"):NULL; CR(v?gstr(v):0);
    }
    if (IS("_errno")) { M32(crt_globals()+4)=errno; CR(crt_globals()+4); }
    if (IS("strerror")) CR(gstr(strerror((int)A(0))));
    if (IS("__p__commode")) CR(crt_globals()+8);
    if (IS("__p__fmode")) CR(crt_globals()+16);
    if (IS("__p___initenv")) CR(crt_globals()+20);
    if (IS("__getmainargs")) {
        uint32_t argv=galloc(8),env=galloc(4); M32(argv)=gstr("private.exe");
        M32(A(0))=1;M32(A(1))=argv;M32(A(2))=env;M32(crt_globals()+20)=env;CR(0);
    }
    if (IS("_initterm")) { for(uint32_t a=A(0),end=A(1);a<end;a+=4)if(M32(a))call_guest(c,M32(a),0,NULL); CR(0); }
    if (IS("_onexit") || IS("__dllonexit")) { if(callback_count==1024)CR(0);callbacks[callback_count++]=A(0);CR(A(0)); }
    if (IS("_cexit")) { crt_exit_callbacks(c); CR(0); }
    if (IS("_c_exit") || IS("__set_app_type") || IS("__setusermatherr")) CR(0);
    if (IS("_XcptFilter")) CR(0); /* EXCEPTION_CONTINUE_SEARCH */
    if (IS("exit")) { int result=A(0); crt_exit_callbacks(c); exit(result); }
    if (IS("_exit")) { int result=A(0); fprintf(stderr,"boot: _exit(%d) from the game\n",result); app_restart_game_exited(result==0); diag_begin_exit(); exit(result); }
    if (IS("_amsg_exit")) _exit((int)A(0));
    if (IS("_controlfp") || IS("_control87")) {
        uint32_t old=ms_control(c->cw),mask=A(1);if(IS("_controlfp"))mask&=~0x80000u;
        c->cw=x87_control((old&~mask)|(A(0)&mask),c->cw);CR(ms_control(c->cw));
    }
    if (IS("_isnan")) CR(isnan(fp_arg(c,0)));
#define FP(n, f) if (IS(n)) { fp_return(c,f(fp_arg(c,0))); CR(0); }
    FP("ceil",ceil) FP("floor",floor) FP("sqrt",sqrt) FP("cos",cos)
#undef FP
#define CI(n, f) if (IS(n)) { c->st[c->top]=f(c->st[c->top]); CR(0); }
    CI("_CIacos",acos) CI("_CIasin",asin) CI("_CIcosh",cosh) CI("_CIsinh",sinh) CI("_CItanh",tanh)
#undef CI
    if (IS("_CIpow") || IS("_CIfmod")) { double x=c->st[(c->top+1)&7],y=c->st[c->top]; c->top=(c->top+1)&7;c->st[c->top]=IS("_CIpow")?pow(x,y):fmod(x,y);CR(0); }
    if (IS("time") || IS("_time64")) { int64_t t=time(NULL);if(A(0)){if(IS("time"))M32(A(0))=(uint32_t)t;else M64(A(0))=(uint64_t)t;}c->edx=(uint64_t)t>>32;CR(t); }
    if (IS("clock")) CR((uint32_t)((double)clock()*1000/CLOCKS_PER_SEC));
    if (IS("_ftime")) { struct timeval tv;gettimeofday(&tv,NULL);M32(A(0))=(uint32_t)tv.tv_sec;M16(A(0)+4)=tv.tv_usec/1000;M16(A(0)+6)=0;M16(A(0)+8)=0;CR(0); }
    if (IS("localtime") || IS("gmtime") || IS("_localtime64") || IS("_gmtime64")) { time_t t=(IS("localtime")||IS("gmtime"))?(int32_t)M32(A(0)):(int64_t)M64(A(0));struct tm result;CR(guest_tm((IS("localtime")||IS("_localtime64"))?localtime_r(&t,&result):gmtime_r(&t,&result))); }
    if (IS("mktime") || IS("_mktime64")) { struct tm t=host_tm(A(0));int64_t result=mktime(&t);uint32_t a=guest_tm(&t);memcpy(P(0),G+a,36);c->edx=(uint64_t)result>>32;CR(result); }
    if (IS("qsort")) {
        SortContext ctx={c,A(3)};qsort_r(P(0),A(1),A(2),&ctx,sort_compare);CR(0);
    }
    if (IS("bsearch")) { uint32_t lo=0,hi=A(2);while(lo<hi){uint32_t mid=lo+(hi-lo)/2,p=A(1)+mid*A(3);int r=cmp_guest(c,A(4),A(0),p);if(!r)CR(p);if(r<0)hi=mid;else lo=mid+1;}CR(0); }
    if (IS("_beginthreadex")) {
        static pthread_once_t once = PTHREAD_ONCE_INIT;
        pthread_once(&once, register_begin_cdecl);
        uint32_t ctx = gmalloc(8), tid = 0;
        M32(ctx) = A(2);
        M32(ctx + 4) = A(3);
        uint32_t h = private_thread_create(A(1), begin_cdecl_entry, ctx, A(4), &tid);
        if (!h) gfree(ctx);
        if (A(5)) M32(A(5)) = tid;
        CR(h);
    }
    if (IS("_endthreadex")) return win32_threads(c,"ExitThread"); /* does not return */
    if (IS("sscanf")) {
        /* MS long is 32 bits, host long is 64; rewrite only integer lengths.
           Suppressed fields consume no pointer. Reject wide/pointer conversions. */
        char fmt[8192];size_t n=0;unsigned fields=0;
        const char *p=P(1);
        while(*p) {
            if(n>sizeof fmt-100)return 0;
            if(*p!='%'){fmt[n++]=*p++;continue;}
            fmt[n++]=*p++;if(*p=='%'){fmt[n++]=*p++;continue;}
            int suppress=*p=='*';if(suppress)fmt[n++]=*p++;
            while(isdigit((unsigned char)*p))fmt[n++]=*p++;
            int wide=0;
            if(!strncmp(p,"I64",3)){fmt[n++]='l';fmt[n++]='l';p+=3;}
            else if(*p=='l'){p++;if(*p=='l'){fmt[n++]='l';fmt[n++]='l';p++;}else wide=1;}
            else if(*p=='h'){fmt[n++]=*p++;if(*p=='h')fmt[n++]=*p++;}
            else if(*p=='L'){wide=1;p++;} /* MS long double is an 8-byte double */
            if(!*p||!strchr("diuoxXfFeEgGaAcsn[",*p)||(wide&&strchr("sc[",*p)))return 0;
            if(wide&&strchr("fFeEgGaA",*p))fmt[n++]='l';
            char conv=*p++;fmt[n++]=conv;
            if(conv=='['){if(*p=='^')fmt[n++]=*p++;if(*p==']')fmt[n++]=*p++;while(*p&&*p!=']'){if(n>=sizeof fmt-2)return 0;fmt[n++]=*p++;}if(!*p)return 0;fmt[n++]=*p++;}
            if(!suppress&&++fields>16)return 0;
        }
        fmt[n]=0;void *v[16]={0};for(unsigned i=0;i<fields;i++)v[i]=G+A(2+i);
        CR(sscanf(P(0),fmt,v[0],v[1],v[2],v[3],v[4],v[5],v[6],v[7],v[8],v[9],v[10],v[11],v[12],v[13],v[14],v[15]));
    }
    if (IS("?vswprintf@@YAHPAGIPBGPAD@Z")) {
        char fmt[8192],buf[65536];uint32_t n=0;
        while(M16(A(2)+2*n)){if(n==sizeof fmt-1||M16(A(2)+2*n)>127)return 0;fmt[n]=(char)M16(A(2)+2*n);n++;}fmt[n]=0;
        /* Numeric/ASCII formats only; wide string conversions need UTF-16
           marshalling rather than passing a guest pointer to host wchar_t. */
        for(const char *p=fmt;*p;p++)if(*p=='%'){
            p++;if(*p=='%')continue;
            while(*p&&!strchr("diuoxXfFeEgGaAcspnSC",*p))p++;
            if(!*p||strchr("sSC",*p))return 0;
        }
        int result=format_guest(buf,sizeof buf,fmt,A(3));if(result<0||result>=(int)sizeof buf) return 0;
        uint32_t cap=A(1),copy=(uint32_t)result<cap?(uint32_t)result:cap;
        for(uint32_t i=0;i<copy;i++)M16(A(0)+2*i)=(unsigned char)buf[i];
        if((uint32_t)result<cap)M16(A(0)+2*result)=0;CR((uint32_t)result<cap?result:-1);
    }
    if (IS("sprintf") || IS("vsprintf") || IS("_snprintf") || IS("_vsnprintf") || IS("printf") || IS("fprintf") || IS("vfprintf")) {
        char buf[65536];uint32_t fmt,va;size_t cap=sizeof buf;int dest=0;FILE *file=NULL;
        if(IS("printf")){fmt=A(0);va=c->esp+8;file=stdout;}
        else if(IS("fprintf")||IS("vfprintf")){fmt=A(1);va=IS("vfprintf")?A(2):c->esp+12;file=file_ptr(A(0));}
        else {dest=1;int bounded=IS("_snprintf")||IS("_vsnprintf");fmt=A(bounded?2:1);va=(IS("vsprintf")||IS("_vsnprintf"))?A(bounded?3:2):c->esp+4+4*(bounded?3:2);if(bounded&&A(1)<cap)cap=A(1);}
        int n=format_guest(buf,cap,(char *)G+fmt,va);if(n<0||n>=(int)sizeof buf)return 0;
        if(dest){size_t copy=(size_t)n<cap?(size_t)n+1:cap;if(copy)memcpy(P(0),buf,copy);}else {if(!file)CR(-1);fwrite(buf,1,n,file);}CR((dest&&cap<=(size_t)n)?-1:n);
    }
    if (IS("fopen")) { char path[4096];private_resolve(P(0),path,sizeof path);CR(file_new(fopen(path,P(1)))); }
    if (IS("fclose")) { FILE *f=file_ptr(A(0));if(!f)CR(-1);int r=fclose(f);for(int i=3;i<128;i++)if(files[i]==f)files[i]=NULL;CR(r); }
    if (IS("fflush")) CR(A(0)?(file_ptr(A(0))?fflush(file_ptr(A(0))):-1):fflush(NULL));
    if (IS("fgetc")) { FILE *f=file_ptr(A(0));CR(f?fgetc(f):EOF); }
    if (IS("fputc") || IS("ungetc")) { FILE *f=file_ptr(A(1));CR(f?(IS("fputc")?fputc(A(0),f):ungetc(A(0),f)):EOF); }
    if (IS("fread") || IS("fwrite")) { FILE *f=file_ptr(A(3));CR(f?(IS("fread")?fread(P(0),A(1),A(2),f):fwrite(P(0),A(1),A(2),f)):0); }
    // The career task uses this descriptor only for _write and _close. Share the Win32 save staging path.
    if (IS("_open") && career_save && M32(c->esp) == 0x00895263u) {
        uint32_t args[] = {A(0), 0x40000000u, 1, 0, 2, 0, 0}; /* GENERIC_WRITE, FILE_SHARE_READ, CREATE_ALWAYS */
        career_save->handle = invoke_win32(c, "CreateFileA", 7, args);
        CR(career_save->handle);
    }
    if (career_save && career_save->handle != UINT32_MAX) {
        if (IS("_write") && A(0) == career_save->handle) {
            uint32_t sp = c->esp;
            uint32_t args[] = {A(0), A(1), A(2), sp - 4, 0};
            c->esp -= 4; /* Reserve a guest slot for WriteFile's byte count. */
            M32(c->esp) = 0;
            uint32_t ok = invoke_win32(c, "WriteFile", 5, args);
            uint32_t written = M32(c->esp);
            c->esp = sp;
            if (ok != 1 || written != args[2]) career_save->failed = 1;
            CR(ok == 1 ? written : UINT32_MAX);
        }
        if (IS("_close") && A(0) == career_save->handle) {
            uint32_t ok = invoke_win32(c, "CloseHandle", 1, &career_save->handle);
            career_save->handle = UINT32_MAX;
            if (ok != 1) career_save->failed = 1;
            CR(ok == 1 ? 0 : UINT32_MAX);
        }
    }
    if (IS("_open")) { char path[4096];private_resolve(P(0),path,sizeof path);uint32_t w=A(1);int flags=(w&3)==2?O_RDWR:(w&3)==1?O_WRONLY:O_RDONLY;if(w&0x100)flags|=O_CREAT;if(w&0x200)flags|=O_TRUNC;if(w&8)flags|=O_APPEND;if(w&0x400)flags|=O_EXCL;CR(open(path,flags,0666)); }
    if (IS("_close")) CR(close(A(0)));
    if (IS("_read") || IS("_write")) CR(IS("_read")?read(A(0),P(1),A(2)):write(A(0),P(1),A(2)));
    if (IS("_lseek")) CR(lseek(A(0),(int32_t)A(1),A(2)));
    if (IS("_filelength")) { struct stat s;CR(fstat(A(0),&s)?-1:s.st_size); }
    if (IS("_mkdir") || IS("_rmdir") || IS("remove")) { char path[4096];private_resolve(P(0),path,sizeof path);CR(IS("_mkdir")?mkdir(path,0777):IS("_rmdir")?rmdir(path):remove(path)); }
    if (IS("_getcwd")) { const char *s="C:\\NFSMW";uint32_t a=A(0)?A(0):gmalloc(A(1));if(A(1)<=strlen(s))CR(0);strcpy((char *)G+a,s);CR(a); }
    if (IS("_fullpath")) { uint32_t n=A(2),a=A(0)?A(0):gmalloc(n);if(strlen(P(1))>=n)CR(0);strcpy((char *)G+a,P(1));CR(a); }
    if (IS("_getdrive")) CR(3);
    if (IS("_getdiskfree")) { M32(A(1))=0x100000;M32(A(1)+4)=0x200000;M32(A(1)+8)=8;M32(A(1)+12)=512;CR(0); }
    /* VC7.1 release std::string: allocator byte, 16-byte SSO, size, capacity. */
    if (IS("??0?$basic_string@DU?$char_traits@D@std@@V?$allocator@D@2@@std@@QAE@PBD@Z") || IS("??0?$basic_string@DU?$char_traits@D@std@@V?$allocator@D@2@@std@@QAE@ABV01@@Z")) {
        uint32_t self=c->ecx,src=A(0);if(IS("??0?$basic_string@DU?$char_traits@D@std@@V?$allocator@D@2@@std@@QAE@ABV01@@Z"))src=M32(src+24)<16?src+4:M32(src+4);
        uint32_t n=strlen((char *)G+src),dst=self+4;memset(G+self,0,28);if(n>=16){dst=gmalloc(n+1);M32(self+4)=dst;}memcpy(G+dst,G+src,n+1);M32(self+20)=n;M32(self+24)=n<16?15:n;RET(self,1);
    }
    if (IS("??1?$basic_string@DU?$char_traits@D@std@@V?$allocator@D@2@@std@@QAE@XZ")) {if(M32(c->ecx+24)>=16)gfree(M32(c->ecx+4));RET(c->ecx,0);}
    /* C++ exception construction/unwinding and non-local jumps need a separate
       guest unwinder. They remain explicit stubs; no false success is returned. */
    return 0;
}
