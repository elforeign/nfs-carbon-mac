#include "private_carbon_audio_limiter.h"
void private_mix_buffers(unsigned *buffers,unsigned *playing) {
    *buffers=0;*playing=0;
    for(unsigned i=0;i<nobjs;++i){
        DsObj *b=objs[i];
        if(!b || b->kind!=2 || !b->buf || !b->refs || !b->bytes)continue;
        ++*buffers;uint32_t status=0;
        if(ds_buffer_get_status(b->buf,&status)>=0 && (status&DSBSTATUS_PLAYING))++*playing;
    }
}
