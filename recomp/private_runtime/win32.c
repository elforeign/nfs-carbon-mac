/* Address-independent additions for a private image. The thread-name exception
 * is a debugger notification only; other exception codes still fail closed.
 */
#include "host.h"
#include <ctype.h>
#include <stdlib.h>
#include <unistd.h>
extern uint32_t diag_thread_id(void);
extern uint32_t private_set_thread_ideal(uint32_t, uint32_t);
#define IS(n) (!strcmp(fn, n))
#include "security.h"

int private_win32_extra(Cpu *c, const char *fn) {
    if(private_security(c,fn))return 1;
    if (IS("RaiseException")) {
        uint32_t code=arg(c,0), flags=arg(c,1), count=arg(c,2), p=arg(c,3);
        if (code!=0x406D1388u || flags || count!=4 || !p || p>UINT32_MAX-15 ||
            M32(p)!=0x1000 || !M32(p+4) || M32(p+12)) {
            if(diag_on)diag_event("PRIVATE EXCEPTION code=%08X flags=%X count=%u (unhandled)",code,flags,count);
            return 0;
        }
        if (diag_on) {
            uint32_t tid=M32(p+8);if(tid==UINT32_MAX)tid=diag_thread_id();
            /* Bound the diagnostic to avoid reading beyond an unterminated name.
             * No name read, formatting or host call occurs when diagnostics are off. */
            uint32_t name=M32(p+4);unsigned n=0;
            while(n<255 && (uint64_t)name+n<=UINT32_MAX && M8(name+n))++n;
            diag_event("PRIVATE THREAD NAME tid=%u name=%.*s",tid,(int)n,(const char *)G+name);
        }
        /* The supported notification resumes at the caller's next instruction.
         * Its translated SEH epilogue removes its registration normally. */
        c->esp+=20;return 1;
    }
    if (IS("SetThreadIdealProcessor")) RET(private_set_thread_ideal(arg(c,0),arg(c,1)),2);
    if (IS("GetComputerNameA")) {
        uint32_t dest=arg(c,0), size=arg(c,1);
        if(!size){last_error=87;RET(0,2);}
        char name[256];if(gethostname(name,sizeof name)){last_error=31;RET(0,2);}
        name[sizeof name-1]=0;size_t n=strcspn(name,".");if(n>15)n=15;
        for(size_t k=0;k<n;++k)name[k]=(char)toupper((unsigned char)name[k]);name[n]=0;
        if(!dest || M32(size)<=n){M32(size)=(uint32_t)n+1;last_error=111;RET(0,2);}
        memcpy(G+dest,name,n+1);M32(size)=(uint32_t)n;RET(1,2);
    }
    if (IS("GetSystemDirectoryA")) {
        /* Guest DLL names live in the emulated Windows namespace. */
        const char path[]="C:\Windows\System32";uint32_t dest=arg(c,0), cap=arg(c,1);
        if(!dest || cap<sizeof path)RET(sizeof path,2);
        memcpy(G+dest,path,sizeof path);RET(sizeof path-1,2);
    }
    if (IS("CoCreateGuid")) {
        uint32_t p=arg(c,0);if(!p)RET(0x80070057u,1);
        arc4random_buf(G+p,16);M8(p+7)=(M8(p+7)&15)|0x40;M8(p+8)=(M8(p+8)&63)|0x80;
        RET(0,1);
    }
    if (IS("UuidToStringA")) {
        uint32_t p=arg(c,0), out=arg(c,1);if(!out)RET(87,2);
        uint32_t dest=gmalloc(37);if(!dest)RET(14,2);
        if(!p)memcpy(G+dest,"00000000-0000-0000-0000-000000000000",37);
        else snprintf((char *)G+dest,37,"%08x-%04x-%04x-%02x%02x-%02x%02x%02x%02x%02x%02x",
            M32(p),M16(p+4),M16(p+6),M8(p+8),M8(p+9),M8(p+10),M8(p+11),M8(p+12),M8(p+13),M8(p+14),M8(p+15));
        M32(out)=dest;RET(0,2);
    }
    if (IS("RpcStringFreeA")) {
        uint32_t p=arg(c,0);if(p){if(M32(p))gfree(M32(p));M32(p)=0;}RET(0,1);
    }
    return 0;
}
