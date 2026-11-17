/* Optional capture detail. The retained allocator owns fallback data and errors.
 * 0070DE55/83: device slot 25, managed fallback / render-target cube.
 * 0070DECE: slot 29, six matching depths. 0071AD20 builds view descriptors
 * from A63AE0 after allocation. 0072ECFA..ED19 visits all six capture views.
 * CarShader and CARNORMALMAP bind 0070D9B0's cube via parameter 0x38
 * (0073E180 / 0073E200) in flow 6; flow 3 uses the managed fallback.
 * NFS_CARBON_REFLECT_HDR (on unless 0; needs the lacquer) allocates the same capture as
 * D3DFMT_A16B16G16R16F (113) in place of A8R8G8B8 (21) and gives the two lamp sprite
 * programs their energy on its faces: carbon_coat.h expands their output by
 * 1 / (1 - c30.x m); here c30.x = 1 - 1/K on a capture face and 0 on every other target.
 * K = 64: a lamp that reached display white carries 64 x white. The game's own draws sum
 * to 1.67 x at most; 25 x is the least a 4 % coat returns to white. "ldr" keeps the
 * 8-bit capture under the same lamp programs (the control for the format).
 */
#ifndef CARBON_ENVCUBE_FIXTURE
#include "render_internal.h"
#endif
#include <math.h>

extern char diag_fx_pass[];
static int carbon_envcube_on, carbon_envcube_hdr, carbon_envcube_float, carbon_envcube_allocating;
#define CARBON_ENVCUBE_LAMP_K 64.f
static uint32_t carbon_envcube_cube, carbon_envcube_pending;
static uint32_t carbon_envcube_depths[6];
static uint32_t carbon_envcube_original[119], carbon_envcube_callback[119];
static unsigned carbon_envcube_faces, carbon_envcube_samples, carbon_envcube_generations;
static unsigned carbon_envcube_stale, carbon_envcube_face_draws[6];

static void carbon_envcube_request(uint32_t *edge, uint32_t *levels,
                                   uint32_t usage, uint32_t format, uint32_t caller) {
    if (carbon_envcube_on && carbon_envcube_allocating && usage == 1 &&
        format == 21 && caller == 0x0070DE86u) {
        *edge = 1024;
        *levels = 0; /* D3D9's full chain: 1024 through 1, eleven levels. */
    }
}

static int carbon_envcube_create(Cpu *c) {
    uint32_t edge=arg(c,1), levels=arg(c,2), usage=arg(c,3), format=arg(c,4);
    uint32_t caller=M32(c->esp), output=arg(c,6);
    carbon_envcube_request(&edge,&levels,usage,format,caller);
    M32(c->esp+8)=edge; M32(c->esp+12)=levels;
    if (carbon_envcube_float && carbon_envcube_allocating && usage==1 && format==21 && caller==0x0070DE86u)
        M32(c->esp+20)=113;
    dispatch(c,carbon_envcube_original[25]);
    if (!c->eax && carbon_envcube_allocating && usage==1 && caller==0x0070DE86u) {
        carbon_envcube_cube=M32(output); carbon_envcube_pending=0;
        Obj *t=obj(carbon_envcube_cube);
        if (diag_on && t) diag_event("carbon envcube: create cube=%08X edge=%u levels=%u format=%u usage=%u on=%d",
            t->guest,t->w,t->levels,t->fmt,t->usage,carbon_envcube_on);
    }
    return 1;
}

static int carbon_envcube_depth(Cpu *c) {
    if (carbon_envcube_on && carbon_envcube_allocating) {
        M32(c->esp+8)=1024; M32(c->esp+12)=1024;
    }
    dispatch(c,carbon_envcube_original[29]); return 1;
}

static void carbon_envcube_flush(void) {
    if (!carbon_envcube_on || !carbon_envcube_pending) return;
    Obj *t=obj(carbon_envcube_cube);
    if (!t || t->levels!=11) return;
    end_pass(); ensure_cmd();
    RenderTex *g=gpu_tex(t);
    if (!g || !g->tex || g->tex.mipmapLevelCount!=11) return;
    id<MTLBlitCommandEncoder> b=[cmd blitCommandEncoder];
    if (!b) return;
    [b generateMipmapsForTexture:g->tex];
    [b endEncoding];
    carbon_envcube_pending=0;
    if (diag_on) ++carbon_envcube_generations;
}

static int carbon_envcube_target(Cpu *c) {
    if (arg(c,1)==0) {
        Obj *old=obj(dev.rt[0]), *next=obj(arg(c,2));
        if (carbon_envcube_cube && old && old->parent==carbon_envcube_cube &&
            (!next || next->parent!=carbon_envcube_cube)) carbon_envcube_flush();
    }
    dispatch(c,carbon_envcube_original[37]); return 1;
}

#ifndef CARBON_ENVCUBE_FIXTURE
/* Diagnostic boots only: the largest channel of every level-0 texel, read after the frame completes. */
static float carbon_envcube_half(uint16_t h) {
    unsigned e=(h>>10)&31, m=h&1023;
    float v=e==0 ? ldexpf((float)m,-24) : e==31 ? (m ? 0 : INFINITY) : ldexpf((float)(m+1024),(int)e-25);
    return h&0x8000 ? -v : v;
}
/* One readback buffer, kept; one readback in flight; the scan and the file write run on a background queue.
 * The blit joins the frame's own end: Present follows at once and ends the pass anyway. */
static void carbon_envcube_stats(Obj *t) {
    static id<MTLBuffer> data; static volatile int busy; static dispatch_queue_t queue;
    if (busy) return;
    RenderTex *g=gpu_tex(t);
    id<MTLTexture> cube=g ? g->tex : nil;
    int half=cube && cube.pixelFormat==MTLPixelFormatRGBA16Float;
    if (!cube || (!half && cube.pixelFormat!=MTLPixelFormatBGRA8Unorm)) return;
    NSUInteger edge=cube.width, pixel=half?8:4, row=edge*pixel, face=row*edge;
    if (!data || data.length<face*6) data=[cube.device newBufferWithLength:face*6 options:MTLResourceStorageModeShared];
    if (!data) return;
    if (!queue) queue=dispatch_queue_create("carbon.envcube.stats",DISPATCH_QUEUE_SERIAL);
    end_pass(); ensure_cmd();
    id<MTLBlitCommandEncoder> b=[cmd blitCommandEncoder];
    for (NSUInteger f=0;f<6;++f)
        [b copyFromTexture:cube sourceSlice:f sourceLevel:0 sourceOrigin:MTLOriginMake(0,0,0)
            sourceSize:MTLSizeMake(edge,edge,1) toBuffer:data destinationOffset:f*face
            destinationBytesPerRow:row destinationBytesPerImage:face];
    [b endEncoding];
    unsigned long long frame=dev.frames;
    NSString *path=[NSString stringWithFormat:@"%s/cubestats.log",diag_dir];
    id<MTLBuffer> buf=data;
    busy=1;
    [cmd addCompletedHandler:^(id<MTLCommandBuffer> done) {
        unsigned long status=(unsigned long)done.status;
        dispatch_async(queue,^{
            const uint8_t *p=buf.contents;
            unsigned n50=0,n90=0,n1=0,over=0,n4=0,n25=0; float peak=0;
            for (NSUInteger i=0;i<edge*edge*6;++i) {
                float m=0;
                for (unsigned k=0;k<3;++k) {
                    uint16_t h; float v;
                    if (half) { memcpy(&h,p+i*8+k*2,2); v=carbon_envcube_half(h); } else v=p[i*4+k]/255.f;
                    if (v>m) m=v;
                }
                if (m>peak) peak=m;
                n50+=m>=.5f; n90+=m>=.9f; n1+=m>=1; over+=m>1; n4+=m>=4; n25+=m>=25;
            }
            FILE *f=fopen(path.UTF8String,"a");
            if (f) {
                fprintf(f,"frame=%llu status=%lu format=%s edge=%lu peak=%.4f ge0.5=%u ge0.9=%u ge1=%u gt1=%u ge4=%u ge25=%u\n",
                    frame,status,half?"rgba16f":"bgra8",(unsigned long)edge,peak,n50,n90,n1,over,n4,n25);
                fclose(f);
            }
            busy=0;
        });
    }];
}
#endif

static int carbon_envcube_car(void) {
    return !strncmp(diag_fx_pass,"IDI_CAR_FX/",11) ||
           !strncmp(diag_fx_pass,"IDI_CARNORMALMAP_FX/",20);
}

/* The bound pixel program is one of the two lamp sprite programs (FNV-1a 64 of the bytecode). */
static int carbon_envcube_lamp(void) {
    static uint32_t handle, count; static const uint32_t *tokens; static int lamp;
    Obj *ps=obj(dev.ps);
    if (!ps || !ps->tokens) return 0;
    if (ps->guest!=handle || ps->tokens!=tokens || ps->ntokens!=count) {
        uint64_t key=1469598103934665603ull;
        const unsigned char *bytes=(const unsigned char *)ps->tokens;
        for (size_t k=0;k<(size_t)ps->ntokens*4;++k) key=(key^bytes[k])*1099511628211ull;
        handle=ps->guest; tokens=ps->tokens; count=ps->ntokens;
        lamp=key==0xB53B3A3B390249B4ull || key==0x89AA56E4826EC0D2ull;
    }
    return lamp;
}

static int carbon_envcube_draw(Cpu *c, unsigned slot) {
    Obj *rt=obj(dev.rt[0]);
    int capture=carbon_envcube_cube && rt && rt->parent==carbon_envcube_cube && rt->face<6;
    if (capture) {
        carbon_envcube_pending=1;
        if (diag_on) {
            carbon_envcube_faces|=1u<<rt->face; ++carbon_envcube_face_draws[rt->face];
#ifndef CARBON_ENVCUBE_FIXTURE
            static unsigned lamp_lines;
            Obj *ps=obj(dev.ps);
            if (lamp_lines<8 && ps && ps->tokens && strstr(diag_fx_pass,"flares")) {
                uint64_t key=1469598103934665603ull;
                const unsigned char *bytes=(const unsigned char *)ps->tokens;
                for (size_t k=0;k<(size_t)ps->ntokens*4;++k) key=(key^bytes[k])*1099511628211ull;
                ++lamp_lines;
                diag_event("carbon envcube: lamp draw face=%u pass=%s program=%016llX tokens=%u blend=%u,%u",
                    rt->face,diag_fx_pass,(unsigned long long)key,ps->ntokens,dev.rs[19],dev.rs[20]);
            }
#endif
        }
    }
    uint32_t saved[16][14], mask=0;
    if (!capture && carbon_envcube_car()) for (unsigned s=0;s<16;++s) {
        if (!carbon_envcube_cube || dev.tex[s]!=carbon_envcube_cube) continue;
        carbon_envcube_flush();
        uint32_t native_min=dev.ss[s][6], native_mip=dev.ss[s][7], native_bias=dev.ss[s][8];
        if (carbon_envcube_on) {
            memcpy(saved[s],dev.ss[s],sizeof saved[s]); mask|=1u<<s;
            dev.ss[s][5]=dev.ss[s][6]=dev.ss[s][7]=2;
            dev.ss[s][8]=dev.ss[s][9]=0;
        }
        if (diag_on) {
            if (!carbon_envcube_samples && dev.frames%120==0)
                diag_event("carbon envcube: sampler frame=%llu stage=%u min=%u mag=%u mip=%u bias=%08X native_min=%u native_mip=%u native_bias=%08X effect=%s",
                    (unsigned long long)dev.frames,s,dev.ss[s][6],dev.ss[s][5],dev.ss[s][7],dev.ss[s][8],
                    native_min,native_mip,native_bias,diag_fx_pass);
            ++carbon_envcube_samples;
            if (carbon_envcube_on && carbon_envcube_pending) ++carbon_envcube_stale;
        }
    }
    float energy[4];
    int lamp=carbon_envcube_hdr && carbon_envcube_lamp();
    if (lamp) {
        memcpy(energy,dev.psc[30],sizeof energy);
        memset(dev.psc[30],0,sizeof energy);
        if (capture) dev.psc[30][0]=1.f-1.f/CARBON_ENVCUBE_LAMP_K;
        ++dev.ver_psc;
    }
    dispatch(c,carbon_envcube_original[slot]);
    if (lamp) { memcpy(dev.psc[30],energy,sizeof energy); ++dev.ver_psc; }
    for (unsigned s=0;s<16;++s) if (mask&(1u<<s)) memcpy(dev.ss[s],saved[s],sizeof saved[s]);
    return 1;
}
static int carbon_envcube_draw81(Cpu *c) { return carbon_envcube_draw(c,81); }
static int carbon_envcube_draw82(Cpu *c) { return carbon_envcube_draw(c,82); }
static int carbon_envcube_draw83(Cpu *c) { return carbon_envcube_draw(c,83); }
static int carbon_envcube_draw84(Cpu *c) { return carbon_envcube_draw(c,84); }

static int carbon_envcube_present(Cpu *c) {
    if (diag_on) {
        Obj *t=obj(carbon_envcube_cube); RenderTex *g=t?t->gpu:NULL;
        if (t && carbon_envcube_samples && dev.frames%120==0)
            diag_event("carbon envcube: frame=%llu edge=%u levels=%u gpu_levels=%lu car_draws=%u faces=%02X face_draws=%u,%u,%u,%u,%u,%u generations=%u stale=%u on=%d",
                (unsigned long long)dev.frames,t->w,t->levels,(unsigned long)(g&&g->tex?g->tex.mipmapLevelCount:0),
                carbon_envcube_samples,carbon_envcube_faces,carbon_envcube_face_draws[0],carbon_envcube_face_draws[1],
                carbon_envcube_face_draws[2],carbon_envcube_face_draws[3],carbon_envcube_face_draws[4],carbon_envcube_face_draws[5],
                carbon_envcube_generations,carbon_envcube_stale,carbon_envcube_on);
#ifndef CARBON_ENVCUBE_FIXTURE
        if (t && dev.frames%120==0) carbon_envcube_stats(t);
#endif
        carbon_envcube_faces=carbon_envcube_samples=carbon_envcube_generations=carbon_envcube_stale=0;
        memset(carbon_envcube_face_draws,0,sizeof carbon_envcube_face_draws);
    }
    dispatch(c,carbon_envcube_original[17]); return 1;
}

static void carbon_envcube_install(uint32_t vt, unsigned slot, HostFn fn) {
    /* Another hook may sit on top of ours (or be ours): install again only on a rebuilt vtable. */
    if (carbon_envcube_callback[slot] && M32(vt+slot*4)!=carbon_envcube_original[slot]) return;
    carbon_envcube_original[slot]=M32(vt+slot*4);
    if (!carbon_envcube_callback[slot]) carbon_envcube_callback[slot]=host_fn(fn,"car capture detail");
    M32(vt+slot*4)=carbon_envcube_callback[slot];
}

/* The native video Accept flag coalesces all row/preset requests into one reset.
 * 007311B0 consumes it; 0072B370 releases the capture before device Reset and
 * recreates it with 0070DE00, then rebuilds view dimensions with 0071AD20. */
void carbon_envcube_apply(int value) {
    (void)value;
    M8(0x00AB0B25u)=1;
}

static void carbon_envcube_call(Cpu *c, unsigned slot, int n, const uint32_t *args) {
    uint32_t device=M32(0x00AB0ABCu);
    if (device) call_guest(c,M32(M32(device)+slot*4),n,args);
}

void live_picture_on_reset(Cpu *c) {
    Cpu saved=*c;
    uint32_t device=M32(0x00AB0ABCu), backup=M32(0x00AB0954u);
    carbon_envcube_pending=0;
    /* Device bindings own references. Unbind only this capture and its fallback;
     * effects have already released theirs in the native reset sequence. */
    for (unsigned i=0;i<16;++i) if (dev.tex[i] &&
            (dev.tex[i]==carbon_envcube_cube || dev.tex[i]==backup)) {
        uint32_t args[]={device,i,0}; carbon_envcube_call(c,65,3,args);
    }
    for (unsigned i=0;i<4;++i) {
        Obj *rt=obj(dev.rt[i]);
        if (rt && carbon_envcube_cube && rt->parent==carbon_envcube_cube) {
            uint32_t args[]={device,i,i?0:dev.backbuffer}; carbon_envcube_call(c,37,3,args);
        }
    }
    for (unsigned i=0;i<6;++i) if (dev.ds && dev.ds==carbon_envcube_depths[i]) {
        uint32_t args[]={device,dev.autodepth}; carbon_envcube_call(c,39,2,args);
    }
    /* The native allocator overwrites its managed backup without releasing it. */
    M32(0x00AB0954u)=0;
    if (backup) call_guest(c,M32(M32(backup)+8),1,&backup);
    carbon_envcube_cube=carbon_envcube_pending=0;
    memset(carbon_envcube_depths,0,sizeof carbon_envcube_depths);
    *c=saved;
}

static void carbon_envcube_allocated(void) {
    carbon_envcube_cube=M32(0x00AB0920u);
    carbon_envcube_pending=0;
    for (unsigned i=0;i<6;++i) carbon_envcube_depths[i]=M32(0x00AB093Cu+i*4);
}

void carbon_envcube_allocate(Cpu *c, void (*original)(Cpu *)) {
    const char *value=getenv("NFS_CARBON_ENVCUBE");
    carbon_envcube_on=value && !strcmp(value,"1");
    /* Off has no device observers, allocations, extra passes or sampler work.
     * Diagnostic boots alone observe the retail path for the comparison. */
    value=getenv("NFS_CARBON_REFLECT_HDR");
    carbon_envcube_float=!value || !strcmp(value,"1");
    carbon_envcube_hdr=carbon_envcube_float || (value && !strcmp(value,"ldr"));
    value=getenv("NFS_CARBON_COAT");
    if (value && !strcmp(value,"0")) carbon_envcube_hdr=carbon_envcube_float=0;
    if (!carbon_envcube_on && !carbon_envcube_hdr && !diag_on) {
        original(c); carbon_envcube_allocated(); return;
    }
    uint32_t device=M32(0x00AB0ABCu), vt=device?M32(device):0;
    if (!vt) { original(c); return; }
    carbon_envcube_install(vt,25,carbon_envcube_create);
    carbon_envcube_install(vt,29,carbon_envcube_depth);
    carbon_envcube_install(vt,37,carbon_envcube_target);
    carbon_envcube_install(vt,17,carbon_envcube_present);
    carbon_envcube_install(vt,81,carbon_envcube_draw81);
    carbon_envcube_install(vt,82,carbon_envcube_draw82);
    carbon_envcube_install(vt,83,carbon_envcube_draw83);
    carbon_envcube_install(vt,84,carbon_envcube_draw84);
    carbon_envcube_allocating=1; original(c); carbon_envcube_allocating=0;
    carbon_envcube_allocated();
    if (carbon_envcube_on && c->eax && carbon_envcube_cube) M32(0x00A63AE0u)=1024;
}
