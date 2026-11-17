#include "host.h"
#include <setjmp.h>

typedef struct CarbonLuaFrame {
    struct CarbonLuaFrame *previous;
    Cpu *cpu;
    uint32_t buffer;
    jmp_buf environment;
} CarbonLuaFrame;

static _Thread_local CarbonLuaFrame *carbon_lua_frame;

void carbon_lua_protected(Cpu *c, void (*original)(Cpu *)) {
    /* 0064DAF0: push ebp; sub esp,48; buffer is [ebp-44]. */
    CarbonLuaFrame frame = { .previous = carbon_lua_frame, .cpu = c,
                             .buffer = c->esp - 0x48u };
    carbon_lua_frame = &frame;
    if (_setjmp(frame.environment) == 0) {
        original(c);
    } else {
        /* The original native C frame has been unwound. Execute its witnessed
         * 0064DB18 continuation: add esp,8; nonzero eax selects 0064DB3B.
         * The guest CRT state was restored before the host jump. */
        c->esp += 8;
        c->eax = M32(c->ebp + 8);
        c->ecx = M32(c->ebp - 0x48u);
        M32(c->eax + 0x50u) = c->ecx;
        c->eax = M32(c->ebp - 4);
        c->esi = M32(c->esp);
        c->esp = c->ebp;
        c->ebp = M32(c->esp);
        c->esp += 8; /* pop ebp; ret (cdecl arguments remain). */
    }
    carbon_lua_frame = frame.previous;
}

void carbon_lua_throw(Cpu *c, void (*original)(Cpu *)) {
    uint32_t state = arg(c, 0), status = arg(c, 1);
    uint32_t handler = M32(state + 0x50u);
    if (handler) {
        uint32_t buffer = handler + 4;
        for (CarbonLuaFrame *frame = carbon_lua_frame; frame; frame = frame->previous) {
            if (frame->cpu != c || frame->buffer != buffer) continue;
            M32(handler + 0x44u) = status;
            /* Exact inverse of private_crt's supported _setjmp3(buf,0) save.
             * Its saved esp includes the import return address. */
            c->ebp = M32(buffer);
            c->ebx = M32(buffer + 4);
            c->edi = M32(buffer + 8);
            c->esi = M32(buffer + 12);
            c->esp = M32(buffer + 16) + 4;
            M32(c->fs_base) = M32(buffer + 24);
            c->eax = 1;
            carbon_lua_frame = frame;
            _longjmp(frame->environment, 1);
        }
    }
    /* No matching protected call: retain native panic/exit or unsupported CRT. */
    original(c);
}
