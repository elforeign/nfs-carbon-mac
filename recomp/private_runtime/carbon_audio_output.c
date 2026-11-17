#include "host.h"
#include <stdlib.h>
#include "../host/audio/dsound_host.h"

void carbon_audio_output_request(Cpu *c, void (*original)(Cpu *)) {
    /* Observe the native option before the queued DAC handler can recreate its
     * buffers. Startup's temporary stereo request must not override this row.
     * Guest command delivery is serialized; no per-frame poll is needed. */
    static uint32_t applied;
    uint32_t option=M32(0x00A63E70u);
    if(!getenv("NFS_AUDIO") && (option==1 || option==2) && option!=applied){
        ds_set_output_choice(option==1?"stereo":"auto");
        applied=option;
    }
    original(c);
}

/* F10 only queues a choice. Deliver the native DAC command on the guest frame,
 * with the same option and request used by native Audio Mode (13BF). */
static int carbon_audio_pending = -1;
void carbon_audio_surround_set(int on) { carbon_audio_pending = on ? 2 : 1; }
void carbon_audio_output_frame(void) {
    if (carbon_audio_pending < 0 || !M32(0x00A631B8u)) return;
    /* 0051F84F publishes the manager; 0051F3E0 stores its Audio Mode
     * object at +0x74. 0050E050 updates that object's +0x5c and DAC. */
    uint32_t manager = M32(0x00A8BA38u);
    if (!manager) return;
    uint32_t audio = M32(manager + 0x74u);
    if (!audio) return;
    uint32_t option = (uint32_t)carbon_audio_pending;
    carbon_audio_pending = -1;
    M32(0x00A63E70u) = option;
    static uint32_t stack;
    if (!stack) stack = galloc(65536);
    Cpu c = {0}; c.esp = stack + 65536; c.cw = 0x37F; c.ecx = audio;
    call_guest(&c, 0x0050E050u, 1, &option);
}
