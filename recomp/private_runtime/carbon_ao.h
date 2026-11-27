#include "carbon_spliteffects.h"
/* Native world contact shading, before the retained post dispatcher copies it.
 * 0071AAE0 gets auto-depth into AB0904; 0071AD20 assigns it to AB04F8.
 * 0071B780 builds the primary projection at *(B4AF90)+40, near/far at +D4/D8
 * of the camera. Derive near/far from that exact projection, including overrides.
 * 0071B780 first copies the camera's world-to-view matrix to *(B4AF90)+0
 * (0044B400, row vectors; view x projection goes to +80).
 */
extern const char *render_contact_source(int reference);
extern int private_carbon_player_position(float *);
static _Atomic int carbon_ao_on;
void carbon_ao_set(int on) { carbon_ao_on = on != 0; }
static id<MTLTexture> carbon_ao_receiver(id<MTLTexture> depth);
/* The native forward car shaders already combine light, reflections and lamps.
 * Preserve their result, and blended/emissive overlays, at composition only.
 * The native prelit shadow strips leave the underlying road a receiver,
 * including transparent texels outside the visible decal.
 * Additive world decals (lit window cards, event rings, light pools) protect
 * only their own lit texels: where their alpha is zero the surface under them
 * stays a receiver.
 * Alpha-blended world decals (road overlays, INVSRCALPHA) are part of the surface: receivers.
 * Particles (tyre smoke, dust, lamp flares) are camera-facing quads: erasing the
 * whole quad cut hard rectangles out of the lamp pools. Like world decals,
 * alpha-blended smoke is a receiver and additive flares protect by their own
 * alpha (it fades to zero at the quad's edge). The streak pass redraws the
 * same flare quads with an opaque-alpha glow: a receiver, its core is
 * protected by the flare pass.
 * blend: 0 for an opaque draw, else its D3D destination factor (2 = ONE).
 * Returns 0 receiver, 1 protected, 2 protected by the draw's own alpha. */
static int carbon_ao_protected(const char *effect, unsigned blend) {
    if((blend==2 || blend==6) && !strncmp(effect,"IDI_PARTICLES_FX/",17))
        return blend==2 && strcmp(effect,"IDI_PARTICLES_FX/streak_flares/p0") ? 2 : 0;
    if(blend==2 && !strcmp(effect,"IDI_WORLD_FX/world/p0"))return 2;
    if(blend==6 && !strcmp(effect,"IDI_WORLD_FX/world/p0"))return 0;
    return (blend && strcmp(effect,"IDI_WORLDPRELIT_FX/world/p0")) || !strncmp(effect,"IDI_CAR_FX/",11) ||
        !strncmp(effect,"IDI_CARNORMALMAP_FX/",20);
}
static void carbon_ao_init(void) {
    const char *e=getenv("NFS_CARBON_AO");
    carbon_ao_on=e && strcmp(e,"off");
}
static const char *carbon_ao_vertex =
"#include <metal_stdlib>\nusing namespace metal;\n"
"struct VOut {float4 pos [[position]];float2 uv;};\n"
"vertex VOut vs_full(uint v [[vertex_id]]){float2 p=float2((v<<1)&2,v&2);return {float4(p*float2(2,-2)+float2(-1,1),0,1),p};}\n";
static const char *carbon_ao_normal =
"fragment float4 fs_contact_normal(VOut i [[stage_in]],depth2d<float> z [[texture(1)]],constant AK &k [[buffer(0)]]){float2 uv=(floor(i.uv/k.size.xy)+0.5)*k.size.xy;return float4(ao_normal(z,uv,k),ao_z(ao_depth(z,uv,k),k));}\n";
/* The contact kernel. Each of eight screen directions is walked in six steps out
 * to the projected reach (c.car.w metres, at most 0.15 of the frame height) and
 * keeps its strongest occluder: height over the receiver's plane, faded to zero
 * at the reach in world space. The shade therefore ends by itself, wherever the
 * walk ends on screen. Neighbouring pixels walk half a step apart; the shared
 * blur merges them. Taps are read at their own depth pixel's centre.
 * Only the player's car occludes: a tap counts when the receiver mask marks it
 * protected (car material), lies within 3 m of the car's centre and stands at
 * least 5 cm above the receiver (world up, not the estimated normal), so kerbs,
 * rock faces, road camber and decals near the car stay unshaded. */
static const char *carbon_ao_multiply =
"struct CK {AK k;float4 car;float4 up;};\n"
"fragment float2 fs_contact_kernel(VOut i [[stage_in]],depth2d<float> z [[texture(1)]],texture2d<float> mask [[texture(3)]],texture2d<float> geometry [[texture(4)]],constant CK &c [[buffer(0)]]){"
"constexpr sampler pt(coord::normalized,filter::nearest,address::clamp_to_edge);float2 t=c.k.size.xy,uv=(floor(i.uv/t)+0.5)*t;float4 dn=geometry.read(uint2(i.pos.xy));"
"float3 p=float3((uv*float2(2,-2)+float2(-1,1))*c.k.proj.xy*dn.w,dn.w);"
// A tap counts within 3 m of the car and fades to zero at the reach: farther receivers get 0 without the walk.
"if(ao_depth(z,uv,c.k)>=0.999999||distance(p,c.car.xyz)>=3.05+c.car.w)return float2(0,p.z);"
// Close to the camera the reach itself shrinks to 0.15 of the frame height, so the walk never ends on a live occluder.
"float reach=min(c.car.w,0.3*p.z*abs(c.k.proj.y));float2 radius=reach/(max(p.z,0.01)*abs(c.k.proj.xy))*0.5;"
"float phase=0.25+0.5*float((int(i.pos.x)+int(i.pos.y))&1),occ=0;"
"for(int a=0;a<8;++a){float top=0;for(int s=0;s<6;++s){"
"float2 q=(floor((uv+directions[a]*radius*((float(s)+phase)/6.0))/t)+0.5)*t;if(any(q<=0.0)||any(q>=1.0))break;"
// The half-size mask is read first: most taps are not the car and need no depth.
"if(mask.sample(pt,c.k.rect.xy+q*c.k.rect.zw).r>=0.5)continue;float qd=ao_depth(z,q,c.k);if(qd>=0.999999)continue;float3 o=ao_point(q,qd,c.k);"
"if(distance(o,c.car.xyz)>=3.0)continue;float3 v=o-p;if(dot(c.up.xyz,v)<0.05)continue;"
"top=max(top,ao_pair(dn.x,dn.y,dn.z,v.x,v.y,v.z,reach));}occ+=top;}"
"return float2(occ/8.0,p.z);}\n"
// Coverage is half-size: a cell the car's outline crosses also holds road. A pixel of
// such a cell that lies behind a nearer surface in it is that road, and is shaded.
"inline bool contact_behind(float2 uv,float2 d,float cz,depth2d<float> z,constant AK &k){"
"return ao_z(ao_depth(z,uv+d,k),k)<2.0*cz-ao_z(ao_depth(z,uv-d,k),k)-max(0.03,0.01*cz);}\n"
"fragment float4 fs_contact_multiply(VOut i [[stage_in]],depth2d<float> z [[texture(1)]],texture2d<float> ao [[texture(2)]],texture2d<float> mask [[texture(3)]],constant CK &c [[buffer(0)]]){"
"constexpr sampler pt(coord::normalized,filter::nearest,address::clamp_to_edge);"
"float raw=ao_depth(z,i.uv,c.k);if(raw>=0.999999)return float4(0,0,0,1);float cz=ao_z(raw,c.k);"
// Beyond 4.5 m of the car the result is 1: leave before the mask and the four shade reads.
"float cd=distance(ao_point(i.uv,raw,c.k),c.car.xyz);if(cd>=4.5)return float4(0,0,0,1);"
"float cover=mask.sample(pt,c.k.rect.xy+i.uv*c.k.rect.zw).r;"
"if(cover<0.999){float2 d=c.k.size.xy*(1.0-2.0*float2(int2(i.pos.xy)&1));"
"if(cover<0.1||!(contact_behind(i.uv,float2(d.x,0),cz,z,c.k)||contact_behind(i.uv,float2(0,d.y),cz,z,c.k)||contact_behind(i.uv,d,cz,z,c.k)))return float4(0,0,0,1);}"
"float sum=0,ws=0;float2 sz=float2(ao.get_width(),ao.get_height()),base=floor(i.uv*sz-0.5),f=fract(i.uv*sz-0.5);"
"for(int y=0;y<2;++y)for(int x=0;x<2;++x){float2 v=ao.sample(pt,(base+float2(x,y)+0.5)/sz).xy;float w=ao_depth_weight(cz,v.y,(x?f.x:1.0-f.x)*(y?f.y:1.0-f.y));sum+=v.x*w;ws+=w;}"
// No floor is reached and no power is taken: the shade follows the occlusion down to 0.4.
"float a=1.0-0.6*(1.0-exp(-c.k.size.z*sum/max(ws,1e-6)));"
// Contact shading belongs to the player's car: full within 3 m of it, none beyond 4.5 m.
"a=mix(a,1.0,smoothstep(3.0,4.5,cd));"
"return float4(0,0,0,a);}\n";
typedef struct {float proj[4],size[4],rect[4],bounds[4],tune[4],car[4],up[4];} CarbonAOParams;
// Strength of the shade per unit of occlusion, and how far from an occluder it reaches (metres).
#define CARBON_AO_STRENGTH 10.0f
#define CARBON_AO_REACH 0.7f
static id<MTLTexture> carbon_ao_texture(MTLPixelFormat format,NSUInteger w,NSUInteger h) {
    MTLTextureDescriptor *d=[MTLTextureDescriptor texture2DDescriptorWithPixelFormat:format width:w height:h mipmapped:NO];
    d.usage=MTLTextureUsageRenderTarget|MTLTextureUsageShaderRead;d.storageMode=MTLStorageModePrivate;
    return [mtl newTextureWithDescriptor:d];
}
static id<MTLRenderPipelineState> carbon_ao_pipeline(id<MTLLibrary> library,NSString *name,MTLPixelFormat format,NSUInteger samples,int multiply) {
    MTLRenderPipelineDescriptor *d=[MTLRenderPipelineDescriptor new];
    d.vertexFunction=[library newFunctionWithName:@"vs_full"];d.fragmentFunction=[library newFunctionWithName:name];
    d.colorAttachments[0].pixelFormat=format;d.rasterSampleCount=samples;
    if(multiply){d.colorAttachments[0].blendingEnabled=YES;d.colorAttachments[0].sourceRGBBlendFactor=MTLBlendFactorZero;d.colorAttachments[0].destinationRGBBlendFactor=MTLBlendFactorSourceAlpha;d.colorAttachments[0].writeMask=MTLColorWriteMaskRed|MTLColorWriteMaskGreen|MTLColorWriteMaskBlue;}
    return pipeline_build(d,"contact",NULL);
}
// Published after the post loading task joins; demand uses the same slots.
static struct {
    id<MTLLibrary> library,normal_library;
    id<MTLRenderPipelineState> normal,kernel,blur,multiply[3][9];
} carbon_ao_pso;
static void carbon_ao_setup(void) {
    if(!carbon_ao_pso.library) {
        NSError *error=nil;
        NSString *source=[NSString stringWithFormat:@"%s%s%s",carbon_ao_vertex,render_contact_source(0),carbon_ao_multiply];
        carbon_ao_pso.library=pipeline_library_source(source,"contact",&error);
        source=[NSString stringWithFormat:@"%s%s%s",carbon_ao_vertex,render_contact_source(1),carbon_ao_normal];
        carbon_ao_pso.normal_library=pipeline_library_source(source,"contact",&error);
        if(!carbon_ao_pso.library || !carbon_ao_pso.normal_library){fprintf(stderr,"contact shader: %s\n",error.localizedDescription.UTF8String);abort();}
        carbon_ao_pso.normal=carbon_ao_pipeline(carbon_ao_pso.normal_library,@"fs_contact_normal",MTLPixelFormatRGBA32Float,1,0);
        carbon_ao_pso.kernel=carbon_ao_pipeline(carbon_ao_pso.library,@"fs_contact_kernel",MTLPixelFormatRG16Float,1,0);
        carbon_ao_pso.blur=carbon_ao_pipeline(carbon_ao_pso.library,@"fs_ao_blur",MTLPixelFormatRG16Float,1,0);
    }
}
static id<MTLRenderPipelineState> carbon_ao_multiply_pipeline(MTLPixelFormat format,NSUInteger samples) {
    unsigned slot;
    switch(format) {
    case MTLPixelFormatBGRA8Unorm: slot=0;break;
    case MTLPixelFormatRGBA8Unorm: slot=1;break;
    case MTLPixelFormatRGBA16Float: slot=2;break;
    default: return carbon_ao_pipeline(carbon_ao_pso.library,@"fs_contact_multiply",format,samples,1);
    }
    if(samples>8)return nil;
    if(!carbon_ao_pso.multiply[slot][samples])
        carbon_ao_pso.multiply[slot][samples]=carbon_ao_pipeline(carbon_ao_pso.library,@"fs_contact_multiply",format,samples,1);
    return carbon_ao_pso.multiply[slot][samples];
}
void render_carbon_contact_prewarm(void) {
    if(!carbon_ao_on)return;
    const char *e=getenv("NFS_PSO_PREWARM");
    if(e && !atoi(e))return;
    carbon_ao_setup();
    // Native UNORM world targets and the optional floating-point scene promotion.
    for(NSNumber *format in @[@(MTLPixelFormatBGRA8Unorm),@(MTLPixelFormatRGBA8Unorm),@(MTLPixelFormatRGBA16Float)])
        for(NSUInteger samples=1;samples<=8;samples*=2)
            if([mtl supportsTextureSampleCount:samples])
                carbon_ao_multiply_pipeline(format.unsignedIntegerValue,samples);
}
static void carbon_ao_view(uint32_t view, const uint32_t requested[4]) {
    if(!carbon_ao_on)return; // Off: no target lookup, resolve, allocation or encoder.
    if(M32(0x00A99BBCu)!=6)return;
    RenderTex *world=carbon_hdr_rt(M32(0x00AB04F4u));
    RenderTex *depth=carbon_hdr_rt(M32(0x00AB04F8u));
    uint32_t platform=M32(view);
    if(!world || !depth || !platform)return;
    float px=MF32(platform+0x40),py=MF32(platform+0x54);
    float a=MF32(platform+0x68),b=MF32(platform+0x78);
    float zn=-b/a,zf=-b/(a-1);
    if(!isfinite(px)||!isfinite(py)||fabsf(px)<0.01f||fabsf(py)<0.01f||!(zn>0 && zf>zn && zf<1e7))return;
    float car[3],center[3];
    #if defined(NFS_GAME) && NFS_GAME == NFS_GAME_PRIVATE
    if(carbon_splitworld_rect(view,NULL)) {
        if(!carbon_splitworld_position(view,car))return;
    } else
#endif
    if(!private_carbon_player_position(car))return; // no player car: nothing to ground
    for(unsigned j=0;j<3;j++){
        center[j]=car[0]*MF32(platform+4*j)+car[1]*MF32(platform+16+4*j)+car[2]*MF32(platform+32+4*j)+MF32(platform+48+4*j);
        if(!isfinite(center[j]))return;
    }
    end_pass();msaa_resolve(depth);ensure_cmd();
    id<MTLTexture> z=depth->tex,target=world->ms?:world->tex;
    if(!z || !target || z.width!=target.width || z.height!=target.height)return;
    uint32_t viewport[4]; memcpy(viewport,requested,sizeof viewport);
    if(!viewport[2]){viewport[2]=(uint32_t)target.width;viewport[3]=(uint32_t)target.height;}
    id<MTLTexture> receivers=carbon_ao_receiver(z);
    if(!receivers)return;
    carbon_ao_setup();
    id<MTLRenderPipelineState> normal=carbon_ao_pso.normal,kernel=carbon_ao_pso.kernel,blur=carbon_ao_pso.blur;
    id<MTLRenderPipelineState> multiply=carbon_ao_multiply_pipeline(target.pixelFormat,target.sampleCount);
    static id<MTLTexture> geometry,ao[2],mask;
    if(!mask) {
        MTLTextureDescriptor *d=[MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatR8Unorm width:1 height:1 mipmapped:NO];
        d.usage=MTLTextureUsageShaderRead;d.storageMode=MTLStorageModeShared;mask=[mtl newTextureWithDescriptor:d];
        uint8_t white=255;[mask replaceRegion:MTLRegionMake2D(0,0,1,1) mipmapLevel:0 withBytes:&white bytesPerRow:1];
    }
    NSUInteger w=viewport[2],h=viewport[3],hw=(w+1)/2,hh=(h+1)/2;
    if(!geometry || geometry.width!=hw || geometry.height!=hh){
        geometry=carbon_ao_texture(MTLPixelFormatRGBA32Float,hw,hh);
        ao[0]=carbon_ao_texture(MTLPixelFormatRG16Float,hw,hh);ao[1]=carbon_ao_texture(MTLPixelFormatRG16Float,hw,hh);
    }
    if(!normal||!kernel||!blur||!multiply||!geometry||!ao[0]||!ao[1]||!mask)abort();
    CarbonAOParams k={.proj={1/px,1/py,zn,zf},.size={1.0f/w,1.0f/h,CARBON_AO_STRENGTH,0},.rect={0,0,1,1},
        .bounds={0.5f/w,0.5f/h,1-0.5f/w,1-0.5f/h},.tune={1.5f,0.65f,0,0},.car={center[0],center[1],center[2],CARBON_AO_REACH},
        .up={MF32(platform+32),MF32(platform+36),MF32(platform+40),0}}; /* world +Z (render up) in view space */
    carbon_effect_bounds(viewport,target.width,target.height,k.rect,k.bounds);
    for(unsigned pass=0;pass<5;pass++){
        id<MTLTexture> out=pass==0?geometry:pass==4?target:ao[pass==2];
        MTLRenderPassDescriptor *rp=[MTLRenderPassDescriptor renderPassDescriptor];
        rp.colorAttachments[0].texture=out;rp.colorAttachments[0].loadAction=pass==4?MTLLoadActionLoad:MTLLoadActionDontCare;rp.colorAttachments[0].storeAction=MTLStoreActionStore;
        k.tune[2]=pass==2?1.0f/hw:0;k.tune[3]=pass==3?1.0f/hh:0;
        if(gpt_on)gpt_render(rp,"contact %u",pass);
        id<MTLRenderCommandEncoder> e=[cmd renderCommandEncoderWithDescriptor:rp];if(gpt_on)gpt_name(e);
        if(pass==4)carbon_effect_clip(e,viewport);
        [e setRenderPipelineState:pass==0?normal:pass==1?kernel:pass==4?multiply:blur];
        [e setFragmentTexture:z atIndex:1];[e setFragmentTexture:pass==4||pass==1?receivers:mask atIndex:3];
        if(pass==1)[e setFragmentTexture:geometry atIndex:4];
        if(pass==2 || pass==3)[e setFragmentTexture:ao[pass==3] atIndex:0];
        if(pass==4)[e setFragmentTexture:ao[0] atIndex:2];
        [e setFragmentBytes:&k length:sizeof k atIndex:0];[e drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:3];[e endEncoding];
    }
    world->stale=world->ms!=nil;
    static int reported;
    if(diag_on && !reported++){diag_event("contact: depth=%08X auto=%08X world=%08X %lux%lu samples=%lu near=%.6g far=%.6g proj=%.6g,%.6g strength=%g reach=%g car=%.3f,%.3f,%.3f",M32(0x00AB04F8u),dev.autodepth,M32(0x00AB04F4u),(unsigned long)w,(unsigned long)h,(unsigned long)target.sampleCount,zn,zf,px,py,k.size[2],k.car[3],center[0],center[1],center[2]);}
}

static void carbon_ao_apply(void) {
    if(!carbon_ao_on || M32(0x00A99BBCu)!=6)return;
    uint32_t r[4];
    for(unsigned i=0;;++i) {
        uint32_t view=carbon_effect_view(i,r,0,0);
        if(!view)break;
        carbon_ao_view(view,r);
    }
}
