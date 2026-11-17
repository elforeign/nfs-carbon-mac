/* The DAC owns the rate; nested calls restore the enclosing context. */
#include "game_image.h"
#include <stdatomic.h>
static _Thread_local uint64_t private_audio_context;
static _Atomic int private_audio_enabled = -1;
static _Atomic unsigned private_audio_generation;
static pthread_mutex_t private_audio_control_mutex = PTHREAD_MUTEX_INITIALIZER;
static int private_carbon_limiter_enabled(void) {
    int enabled=atomic_load(&private_audio_enabled);
    if(enabled<0){
        const char *v=getenv("NFS_CARBON_LIMITER");
        int unset=-1;
        atomic_compare_exchange_strong(&private_audio_enabled,&unset,!(v&&!strcmp(v,"0")));
        enabled=atomic_load(&private_audio_enabled);
    }
    return enabled;
}
void private_carbon_limiter_set(int on) {
    on=on!=0;
    /* The shared audio API atomically advances its generation; the mixer
     * resets delay/gain history under the device lock before the next block. */
    pthread_mutex_lock(&private_audio_control_mutex);
    ds_set_peak_limiter(on);
    if(atomic_exchange(&private_audio_enabled,on)!=on) ++private_audio_generation;
    pthread_mutex_unlock(&private_audio_control_mutex);
}
static pthread_mutex_t private_audio_mutex = PTHREAD_MUTEX_INITIALIZER;
static uint64_t private_audio_counts[5];
static double private_audio_peaks[2];
uint64_t private_carbon_audio_enter(uint32_t dac) {
    uint64_t saved=private_audio_context;
#if PRIVATE_CARBON_SKIPFE
    /* Native 008A8396 seeds a float; 008A867C selects float rate entries. */
    float rate=MF32(dac+0x30u);
    uint32_t hz=rate>=8000 && rate<=192000?(uint32_t)rate:0;
    private_audio_context=((uint64_t)dac<<32) | hz;
#endif
    return saved;
}
void private_carbon_audio_leave(uint64_t saved) { private_audio_context=saved; }
void private_carbon_audio_stats(uint64_t counts[5], double peaks[2]) {
    pthread_mutex_lock(&private_audio_mutex);
    memcpy(counts,private_audio_counts,sizeof private_audio_counts);
    memcpy(peaks,private_audio_peaks,sizeof private_audio_peaks);
    memset(private_audio_counts,0,sizeof private_audio_counts);
    memset(private_audio_peaks,0,sizeof private_audio_peaks);
    pthread_mutex_unlock(&private_audio_mutex);
}
void private_carbon_audio_before(uint32_t caller,uint32_t source,uint32_t samples) {
#if PRIVATE_CARBON_SKIPFE
    unsigned channels=M8(0x00BBF605u);
    if(caller!=0x008A767Bu || source!=0x00BBF680u ||
       (channels!=2 && channels!=6) || samples!=256*channels ||
       !(private_audio_context>>32))return;
    pthread_mutex_lock(&private_audio_control_mutex);
    int enabled=private_carbon_limiter_enabled();
    uint32_t player=enabled?M32(0x00A97BB4u):0;
    int movie=player && M32(player+0x120u)==5;
    int limit=enabled && !movie;
    /* Audio-thread history only. A 2 ms dezipper starts at the previous sample
     * on either transition, avoiding a hard step when look-ahead is reset or
     * bypassed (enable holds through the 2 ms look-ahead first). No old delayed
     * samples survive a disable/re-enable. */
    static _Thread_local float last[6], anchor[6];
    static _Thread_local unsigned seen, fade, fade_length, fade_wait;
    static _Thread_local int ready;
    unsigned generation=atomic_load(&private_audio_generation);
    if(ready && generation!=seen && !movie){
        memcpy(anchor,last,sizeof anchor);
        fade=fade_length=(unsigned)(uint32_t)private_audio_context/500u;
        if(!fade) fade=fade_length=1;
        fade_wait=enabled ? fade_length : 0;
    }
    seen=generation;
    if(diag_on){
        static int logged;
        if(!logged){logged=1;diag_event("PRIVATE AUDIO limiter=%d dac=%08X rate=%u channels=%u frames=256 movie=%d",
            enabled,(uint32_t)(private_audio_context>>32),(uint32_t)private_audio_context,channels,movie);}
    }
    float *pcm=(float *)(G+source);
    /* Diagnostic mute also reaches this new measurement boundary. The off,
     * movie and unrelated-call paths retain their original guest bytes. */
    if(limit && game_sound_mix_muted())memset(pcm,0,samples*sizeof *pcm);
    int meter=diag_on;
    if(meter)pthread_mutex_lock(&private_audio_mutex);
    if(meter)private_audio_counts[0]+=samples;
    if(meter)for(unsigned i=0;i<samples;++i){
        double v=fabs(pcm[i]);
        private_audio_counts[1]+=v>1.0;
        private_audio_counts[2]+=v>0.891251;
        if(v>private_audio_peaks[0])private_audio_peaks[0]=v;
    }
    if(limit){
        /* The shared limiter API consumes six interleaved channels. Embed the
         * native stereo mix in FL/FR, with silent remaining planes; copy only
         * FL/FR back before the native clamp. No shared mixer change needed. */
        float stereo[256*6];
        float *mix=pcm;
        if(channels==2){
            memset(stereo,0,sizeof stereo);
            for(unsigned i=0;i<256;++i){stereo[i*6]=pcm[i*2];stereo[i*6+1]=pcm[i*2+1];}
            mix=stereo;
        }
        ds_device_limit_game_mix(dsound_current_device(),mix,256,(int)(uint32_t)private_audio_context);
        if(channels==2)for(unsigned i=0;i<256;++i){pcm[i*2]=mix[i*6];pcm[i*2+1]=mix[i*6+1];}
    }
    if(!movie)for(unsigned i=0;i<256;++i){
        float weight=fade_wait ? 0.0f : fade ? (float)(fade_length-fade)/fade_length : 1.0f;
        for(unsigned k=0;k<channels;++k){
            unsigned at=i*channels+k;
            if(fade)pcm[at]=anchor[k]+weight*(pcm[at]-anchor[k]);
            last[k]=fmaxf(-1.0f,fminf(1.0f,pcm[at])); // native clamp follows
        }
        if(fade_wait)--fade_wait; else if(fade)--fade;
        ready=1;
    }
    if(meter)for(unsigned i=0;i<samples;++i){
        double v=fabs(pcm[i]);
        private_audio_counts[3]+=v>0.891251+1.0/32767;
        private_audio_counts[4]+=v>=1.0;
        if(v>private_audio_peaks[1])private_audio_peaks[1]=v;
    }
    if(meter)pthread_mutex_unlock(&private_audio_mutex);
    pthread_mutex_unlock(&private_audio_control_mutex);
#else
    (void)caller;(void)source;(void)samples;
#endif
}
