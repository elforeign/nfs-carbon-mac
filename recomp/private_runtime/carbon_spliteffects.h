#pragma once
/* Screen-space consumers reconstruct in local view UVs. Only texture reads
 * map into the shared scene; half-texel bounds exclude the other player. */
#if defined(NFS_GAME) && NFS_GAME == NFS_GAME_PRIVATE
int carbon_splitworld_rect(uint32_t view, uint32_t rect[4]);
int carbon_splitworld_position(uint32_t view, float position[3]);
uint32_t carbon_splitworld_effect_view(void);
#endif
static uint32_t carbon_effect_view(unsigned index, uint32_t rect[4], NSUInteger w, NSUInteger h) {
#if defined(NFS_GAME) && NFS_GAME == NFS_GAME_PRIVATE
    uint32_t current=carbon_splitworld_effect_view();
    if(current) {
        if(index)return 0;
        rect[0]=rect[1]=0;rect[2]=(uint32_t)w;rect[3]=(uint32_t)h;return current;
    }
    if (carbon_splitworld_rect(0x00B4AF90u, NULL)) {
        uint32_t view = 0x00B4AF90u + 0x80u * index;
        return index < 2 && carbon_splitworld_rect(view, rect) ? view : 0;
    }
#endif
    if (index) return 0;
    rect[0] = rect[1] = 0; rect[2] = (uint32_t)w; rect[3] = (uint32_t)h;
    return 0x00B4AF90u;
}
static void carbon_effect_bounds(const uint32_t r[4], NSUInteger w, NSUInteger h,
                                 float rect[4], float bounds[4]) {
    rect[0]=(float)r[0]/w; rect[1]=(float)r[1]/h;
    rect[2]=(float)r[2]/w; rect[3]=(float)r[3]/h;
    bounds[0]=(r[0]+0.5f)/w; bounds[1]=(r[1]+0.5f)/h;
    bounds[2]=(r[0]+r[2]-0.5f)/w; bounds[3]=(r[1]+r[3]-0.5f)/h;
}
static void carbon_effect_clip(id<MTLRenderCommandEncoder> e, const uint32_t r[4]) {
    [e setViewport:(MTLViewport){r[0],r[1],r[2],r[3],0,1}];
    [e setScissorRect:(MTLScissorRect){r[0],r[1],r[2],r[3]}];
}

#if defined(CARBON_SPLITEFFECTS_IMPLEMENTATION) && defined(NFS_GAME) && NFS_GAME == NFS_GAME_PRIVATE
/* The guest keeps its resource handles and reset ownership. During one view's
 * capture/world/post sequence, each referenced target has private backing.
 * Full-size backing keeps the native post UV convention; only the completed
 * image is reduced into the view rectangle. No post tap can reach its peer. */
/* hdrclip is included before the renderer's private helper definitions. */
static MTLTextureDescriptor *texture_descriptor(id<MTLTexture> t);
static int is_depth_fmt(uint32_t f);
static int64_t live_tex,live_tex_bytes,live_rt,live_rt_bytes;
static uint64_t ssao_serial;
#define CSE_TARGETS 64
static struct {
    RenderTex *source;
    RenderTex view[2];
} carbon_effect_targets[CSE_TARGETS];
static unsigned carbon_effect_target_count;
static int carbon_effect_bank = -1;

unsigned carbon_spliteffects_resources(void) { return 2 * carbon_effect_target_count; }

void carbon_spliteffects_reset(void) {
    if(carbon_effect_bank>=0 || !carbon_effect_target_count)return;
    end_pass();
    for(unsigned i=0;i<carbon_effect_target_count;i++)for(unsigned v=0;v<2;v++) {
        RenderTex *r=&carbon_effect_targets[i].view[v];
        if(r->tex){--live_tex;live_tex_bytes-=r->bytes;if(r->rt){--live_rt;live_rt_bytes-=r->bytes;}}
        drop_ms_texture(r);*r=(RenderTex){0};
    }
    memset(carbon_effect_targets,0,sizeof carbon_effect_targets);
    carbon_effect_target_count=0;
}
static int carbon_effect_add(RenderTex *r) {
    if(!r || !r->tex)return 1;
    for(unsigned i=0;i<carbon_effect_target_count;i++)if(carbon_effect_targets[i].source==r)return 1;
    if(carbon_effect_target_count==CSE_TARGETS)return 0;
    unsigned n=carbon_effect_target_count++;
    carbon_effect_targets[n].source=r;
    for(unsigned v=0;v<2;v++) {
        RenderTex *out=&carbon_effect_targets[n].view[v];
        MTLTextureDescriptor *d=texture_descriptor(r->tex);
        out->tex=[mtl newTextureWithDescriptor:d];
        if(!out->tex)return 0;
        out->w=r->w;out->h=r->h;out->fmt=r->fmt;out->rt=r->rt;out->resolve_pass=r->resolve_pass;
        out->bytes=(int64_t)out->tex.allocatedSize;
        ++live_tex;live_tex_bytes+=out->bytes;if(out->rt){++live_rt;live_rt_bytes+=out->bytes;}
        if(r->ms) {
            d=texture_descriptor(r->ms);d.sampleCount=r->ms.sampleCount;
            out->ms=[mtl newTextureWithDescriptor:d];
            msaa_bytes+=(int64_t)out->ms.allocatedSize;
            if(!out->ms)return 0;
        }
        /* Fresh history and unrefreshed faces must never inherit P1 pixels. */
        ensure_cmd();
        for(unsigned sample=0;sample<2;sample++) {
            id<MTLTexture> t=sample?out->ms:out->tex;
            if(!t)continue;
            unsigned slices=t.textureType==MTLTextureTypeCube?6:1;
            for(unsigned face=0;face<slices;face++)for(NSUInteger level=0;level<t.mipmapLevelCount;level++) {
                MTLRenderPassDescriptor *p=[MTLRenderPassDescriptor renderPassDescriptor];
                if(is_depth_pf(t.pixelFormat)) {
                    p.depthAttachment.texture=t;p.depthAttachment.level=level;p.depthAttachment.slice=face;
                    p.depthAttachment.loadAction=MTLLoadActionClear;p.depthAttachment.storeAction=MTLStoreActionStore;p.depthAttachment.clearDepth=1;
                    if(t.pixelFormat==MTLPixelFormatDepth32Float_Stencil8) {
                        p.stencilAttachment.texture=t;p.stencilAttachment.level=level;p.stencilAttachment.slice=face;
                        p.stencilAttachment.loadAction=MTLLoadActionClear;p.stencilAttachment.storeAction=MTLStoreActionStore;
                    }
                } else {
                    p.colorAttachments[0].texture=t;p.colorAttachments[0].level=level;p.colorAttachments[0].slice=face;
                    p.colorAttachments[0].loadAction=MTLLoadActionClear;p.colorAttachments[0].storeAction=MTLStoreActionStore;
                }
                [[cmd renderCommandEncoderWithDescriptor:p] endEncoding];
            }
        }
    }
    return 1;
}
static int carbon_effect_handle(uint32_t h) {
    if(!h)return 1;
    if(h==dev.backbuffer)return carbon_effect_add(&bb_rt);
    if(h==dev.autodepth)return carbon_effect_add(&ad_rt);
    Obj *o=obj(h);if(!o)return 1;
    if(o->parent)o=obj(o->parent);
    if(!o || (o->kind!=K_TEXTURE && o->kind!=K_CUBE && o->kind!=K_SURFACE) ||
       (!(o->usage&3) && !is_depth_fmt(o->fmt)))return 1;
    return carbon_effect_add(gpu_tex(o));
}
int carbon_spliteffects_begin(uint32_t view) {
    if(carbon_effect_bank>=0 || !carbon_splitworld_rect(view,NULL))return 0;
    end_pass();
    /* Native descriptors (0071AD20), allocation handles (0071AAE0/0070DE00),
     * and the post pyramid (0073C340). Aliased face/level surfaces deduplicate. */
    int ok=carbon_effect_handle(dev.backbuffer)&&carbon_effect_handle(dev.autodepth);
    for(unsigned i=0;ok && i<16;i++) {
        uint32_t d=0x00AB04D0u+0x1Cu*i;
        ok=carbon_effect_handle(M32(d+8))&&carbon_effect_handle(M32(d+12));
    }
    for(uint32_t p=0x00AB08F8u;ok && p<=0x00AB0960u;p+=4)ok=carbon_effect_handle(M32(p));
    for(uint32_t p=0x00B42F48u;ok && p<=0x00B42F78u;p+=4)ok=carbon_effect_handle(M32(p));
    for(unsigned i=0;ok && i<3;i++)ok=carbon_effect_handle(M32(0x00AB068Cu+4*i));
    if(!ok){carbon_spliteffects_reset();return 0;}
    carbon_effect_bank=view==0x00B4B010u;
    for(unsigned i=0;i<carbon_effect_target_count;i++) {
        RenderTex *r=carbon_effect_targets[i].source,*bank=&carbon_effect_targets[i].view[carbon_effect_bank];
        msaa_forget(r);RenderTex saved=*r;*r=*bank;*bank=saved;
    }
    /* Receiver recordings belong to this depth image, even in the same frame. */
    ssao_serial=~0ull;
    carbon_hdr_world_phase=1;
    return 1;
}
void carbon_spliteffects_end(uint32_t view) {
    if(carbon_effect_bank<0)return;
    end_pass();
    RenderTex *final=carbon_hdr_rt(M32(0x00AB04D8u));
    RenderTex *world=carbon_hdr_rt(M32(0x00AB04F4u));
    if(final)msaa_resolve(final);if(world)msaa_resolve(world);
    id<MTLTexture> image=final?final->tex:nil,scene=world?world->tex:nil;
    for(unsigned i=0;i<carbon_effect_target_count;i++) {
        RenderTex *r=carbon_effect_targets[i].source,*bank=&carbon_effect_targets[i].view[carbon_effect_bank];
        msaa_forget(r);RenderTex saved=*r;*r=*bank;*bank=saved;
    }
    carbon_effect_bank=-1;
    uint32_t rect[4];if(!carbon_splitworld_rect(view,rect))return;
    MTLRegion dst=MTLRegionMake2D(rect[0],rect[1],rect[2],rect[3]);
    final=carbon_hdr_rt(M32(0x00AB04D8u));world=carbon_hdr_rt(M32(0x00AB04F4u));
    if(image && final){blit_quad(image,MTLRegionMake2D(0,0,image.width,image.height),final->ms?:final->tex,0,0,dst,1);final->stale=final->ms!=nil;}
    if(scene && world && world!=final){blit_quad(scene,MTLRegionMake2D(0,0,scene.width,scene.height),world->ms?:world->tex,0,0,dst,1);world->stale=world->ms!=nil;}
    if(diag_on){static unsigned reports;if(reports++<4)diag_event("carbon spliteffects: view=%08X targets=%u viewport=%u,%u,%u,%u captures=owned post=owned",view,carbon_effect_target_count,rect[0],rect[1],rect[2],rect[3]);}
}
#endif
