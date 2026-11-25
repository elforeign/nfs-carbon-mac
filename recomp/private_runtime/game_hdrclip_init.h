#if defined(NFS_GAME) && NFS_GAME == NFS_GAME_PRIVATE
#include "carbon_splitworld.h"
#endif
/* Private native storage policy. Explicit On only; output composition is separate. */
void render_float_scene_begin(void);
static void float_scene_copy(uint32_t dst, MTLPixelFormat format);
static void carbon_hdr_world_resolve(void);
static void carbon_hdr_dispatch_begin(void);
static void carbon_hdr_copy_observe(void);
static int carbon_hdr_world_phase, carbon_hdr_copy_pending;
static uint32_t carbon_hdr_promotions;
static uint32_t carbon_hdr_address(unsigned i) {
    static const uint32_t address[12] = {0x00AB08F8u,0x00AB0690u,0x00AB0694u,0x00B42F48u,0x00B42F4Cu,0x00B42F50u,0x00B42F54u,0x00B42F58u,0x00B42F5Cu,0x00B42F60u,0x00B42F64u,0x00B42F68u};
    return i < 12 ? address[i] : 0;
}
static uint32_t carbon_hdr_handle(unsigned i) {
    switch(i) {
    case 0: return M32(0x00AB08F8u);
    case 1: return M32(0x00AB0690u);
    case 2: return M32(0x00AB0694u);
    case 3: return M32(0x00B42F48u);
    case 4: return M32(0x00B42F4Cu);
    case 5: return M32(0x00B42F50u);
    case 6: return M32(0x00B42F54u);
    case 7: return M32(0x00B42F58u);
    case 8: return M32(0x00B42F5Cu);
    case 9: return M32(0x00B42F60u);
    case 10: return M32(0x00B42F64u);
    case 11: return M32(0x00B42F68u);
    default: return 0;
    }
}
static int carbon_hdr_class(uint32_t handle) {
    Obj *o=obj(handle); if(!o)return -1;
    uint32_t owner=o->parent?o->parent:handle;
    for(unsigned i=0;i<12;i++)if(owner==carbon_hdr_handle(i))return (int)i;
    return -1;
}
static RenderTex *carbon_hdr_rt(uint32_t handle) {
    if(handle==dev.backbuffer)return &bb_rt;
    if(handle==dev.autodepth)return &ad_rt;
    Obj *o=obj(handle); if(!o)return NULL;
    if(o->parent)o=obj(o->parent);
    return o?gpu_tex(o):NULL;
}
/* The private resolve reads actual samples even without diagnostics. */
static void carbon_hdr_readable_ms(RenderTex *r) {
    if(!r || !r->ms || (r->ms.usage&MTLTextureUsageShaderRead))return;
    end_pass();msaa_resolve(r);
    MTLTextureDescriptor *d=[MTLTextureDescriptor texture2DDescriptorWithPixelFormat:r->tex.pixelFormat width:r->tex.width height:r->tex.height mipmapped:NO];
    d.textureType=MTLTextureType2DMultisample;d.sampleCount=r->ms.sampleCount;
    d.usage=MTLTextureUsageRenderTarget|MTLTextureUsageShaderRead;d.storageMode=MTLStorageModePrivate;
    id<MTLTexture> replacement=[mtl newTextureWithDescriptor:d];if(!replacement)return;
    msaa_forget(r);drop_ms_texture(r);r->ms=replacement;msaa_bytes+=(int64_t)replacement.allocatedSize;
    MTLRegion full=MTLRegionMake2D(0,0,d.width,d.height);
    blit_quad(r->tex,full,r->ms,0,0,full,0);r->stale=1;
}
static void carbon_hdr_promote_all(void) {
    if(!float_scene_on)return;
    for(unsigned i=0;i<12;i++) {
        uint32_t h=carbon_hdr_handle(i); if(!h)continue;
        RenderTex *r=carbon_hdr_rt(h); MTLPixelFormat old=r?r->tex.pixelFormat:MTLPixelFormatInvalid;
        float_scene_copy(h,MTLPixelFormatRGBA16Float);
        carbon_hdr_readable_ms(r);
        if(r && old!=r->tex.pixelFormat) {
            ++carbon_hdr_promotions;
            if(diag_on)diag_event("float scene promote: address=%08X handle=%08X %lux%lu format=%lu->%lu samples=%lu",carbon_hdr_address(i),h,(unsigned long)r->tex.width,(unsigned long)r->tex.height,(unsigned long)old,(unsigned long)r->tex.pixelFormat,(unsigned long)(r->ms?r->ms.sampleCount:1));
        }
    }
}
#include "carbon_ao.h"
#include "carbon_lamplight.h"
void hdrclip_init(void) {
    carbon_ao_init();
    carbon_lamplight_init();
    const char *fs=getenv("NFS_FLOAT_SCENE");
    float_scene_on=fs && !strcmp(fs,"on");
    if(diag_on)diag_event("float scene: requested=%s enabled=%d promotions=0",fs?fs:"off",float_scene_on);
    const char *e=diag_on?getenv("BOOT_DIAG_HDR_CLIP"):NULL;
    hdrclip_on=e && !strcmp(e,"1");
    if(hdrclip_on) {
        hc_buffer=[mtl newBufferWithLength:HC_COUNTERS*8*sizeof(uint32_t) options:MTLResourceStorageModeShared];
        hc_pairs=[mtl newBufferWithLength:8*sizeof(uint32_t) options:MTLResourceStorageModeShared];
        memset(hc_buffer.contents,0,hc_buffer.length); memset(hc_pairs.contents,0,hc_pairs.length);
    }
}
/* Wrappers always retain the translated native body and its calling convention. */
void carbon_hdr_allocate(Cpu *c,void (*original)(Cpu *)) {
    original(c); carbon_hdr_promote_all();
}
static void carbon_hdr_world_body(Cpu *c,void (*original)(Cpu *)) {
#if defined(NFS_GAME) && NFS_GAME == NFS_GAME_PRIVATE
    carbon_splitworld_frame(c, original);
#else
    original(c);
#endif
}
void carbon_hdr_world(Cpu *c,void (*original)(Cpu *)) {
    if(!float_scene_on && !hdrclip_on){carbon_hdr_world_body(c,original);return;}
    render_float_scene_begin(); carbon_hdr_world_phase=1;
    carbon_hdr_world_body(c,original); carbon_hdr_world_phase=0;
}
void carbon_hdr_dispatch(Cpu *c,void (*original)(Cpu *)) {
    carbon_hdr_world_phase=0;
    if(float_scene_on)carbon_hdr_world_resolve();
    if(hdrclip_on)carbon_hdr_dispatch_begin();
    carbon_ao_apply();
    carbon_lamplight_apply();
    original(c);
    if(hdrclip_on)hdrclip_finish();
}
void carbon_hdr_texture(Cpu *c,void (*original)(Cpu *)) {
    original(c);
    if(hdrclip_on && carbon_hdr_copy_pending)carbon_hdr_copy_observe();
}
