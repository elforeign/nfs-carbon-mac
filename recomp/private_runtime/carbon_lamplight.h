/* Optional local world lighting from loaded street and imported tunnel records. */
#include "lighting_colour.h"
extern int postfx_look_variant(const char *);
extern float carbon_dn_lamps_level(void);
extern uint64_t diag_current_frame(void);
static int carbon_lamplight_on,carbon_lamplight_shift;
static void carbon_lamplight_init(void) {
    const char *e=getenv("NFS_CARBON_LAMPLIGHT");
    carbon_lamplight_on=!(e && !strcmp(e,"off"));
    e=diag_on?getenv("BOOT_DIAG_LAMPLIGHT_SHIFT"):NULL;
    carbon_lamplight_shift=e && !strcmp(e,"1");
}
/* LMP2 uses inner < 0 to store the imported tunnel's negative intensity. */
typedef struct {float position[3],inner,outer,rgb[3];uint32_t hash;} CarbonLamp;
static CarbonLamp *carbon_lamps;
static size_t carbon_lamps_count,carbon_lamps_capacity;
static uint64_t carbon_lamps_signature;
/* The loader links the aligned 32-byte pack header itself. +1c is its
 * record count; +18 is replaced with the aligned 96-byte record array. */
static void carbon_lamplight_refresh(void) {
    uint64_t signature=1469598103934665603ull;
    uint32_t head=0x00B479D4u,node=M32(head);
    unsigned packs=0;
    for(;node && node!=head && packs<4096;node=M32(node),++packs) {
        uint32_t words[]={node,M32(node+0x0c),M32(node+0x18),M32(node+0x1c)};
        for(unsigned i=0;i<4;i++)signature=(signature^words[i])*1099511628211ull;
    }
    if(node!=head)return;
    if(signature==carbon_lamps_signature)return;
    carbon_lamps_count=0;
    for(node=M32(head);node!=head;node=M32(node)) {
        uint32_t base=M32(node+0x18),count=M32(node+0x1c);
        if(!base || count>65536 || (uint64_t)base+96ull*count>UINT32_MAX)continue;
        for(unsigned i=0;i<count;i++) {
            uint32_t r=base+96*i;
            if(M8(r+7)!=1 || M8(r+4)!=2)continue;
            char name[35];
            for(unsigned j=0;j<34;j++) {unsigned c=M8(r+0x3eu+j);name[j]=(c>='A'&&c<='Z')?c+('a'-'A'):c;}
            name[34]=0;
            int tunnel=!strncmp(name,"x360_tunnel_",12);
            if(!tunnel && !strstr(name,"street"))continue;
            CarbonLamp lamp={.position={MF32(r+0x10),MF32(r+0x14),MF32(r+0x18)},
                .inner=tunnel?-MF32(r+0x2c):MF32(r+0x30),.outer=MF32(r+0x1c),.hash=M32(r)};
            if(!isfinite(lamp.position[0])||!isfinite(lamp.position[1])||!isfinite(lamp.position[2])||
                !isfinite(lamp.outer)||lamp.outer<1||lamp.outer>100||!isfinite(lamp.inner))continue;
            if(tunnel && !(lamp.inner<0))continue;
            uint32_t rgb=M32(r+0xc);
            for(unsigned j=0;j<3;j++)lamp.rgb[j]=((rgb>>(j*8))&255)/255.0f;
            if(!tunnel) {
                lamp.inner=fminf(lamp.outer,fmaxf(0,lamp.inner));
                lighting_colour_adapt(lamp.rgb);
            }
            if(carbon_lamps_count==carbon_lamps_capacity) {
                size_t capacity=carbon_lamps_capacity?carbon_lamps_capacity*2:256;
                CarbonLamp *next=realloc(carbon_lamps,capacity*sizeof *next);
                if(!next)abort();carbon_lamps=next;carbon_lamps_capacity=capacity;
            }
            carbon_lamps[carbon_lamps_count++]=lamp;
        }
    }
    carbon_lamps_signature=signature;
    if(diag_on)diag_event("lamplight packs=%u records=%zu",packs,carbon_lamps_count);
}
#define CARBON_LAMPLIGHT_GAIN 0.8f
/* Main-view scene flare (0074D330): linear fade in squared camera distance. */
static const float carbon_lamp_fade_start2=30000.f,carbon_lamp_fade_end2=40000.f;
/* rgb.w holds the squared inner radius; range.x holds tunnel intensity. */
typedef struct {float position[4],rgb[4],range[4];} CarbonLampGPU;
typedef struct {float proj[4],size[4],rect[4],bounds[4],tune[4];CarbonLampGPU lamps[24];} CarbonLampParams;
static unsigned carbon_lamplight_select(uint32_t platform,float level,CarbonLampParams *k,unsigned *overflow) {
    carbon_lamplight_refresh();
    float m[16],camera[3],distances[24];size_t indices[24];unsigned count=0,candidates=0;
    for(unsigned i=0;i<16;i++) {m[i]=MF32(platform+4*i);if(!isfinite(m[i]))return 0;}
    for(unsigned j=0;j<3;j++)camera[j]=-(m[12]*m[j*4]+m[13]*m[j*4+1]+m[14]*m[j*4+2]);
    for(size_t i=0;i<carbon_lamps_count;i++) {
        const CarbonLamp *lamp=&carbon_lamps[i];float d2=0;
        if(!(level>0) && lamp->inner>=0)continue;
        for(unsigned j=0;j<3;j++){float d=lamp->position[j]-camera[j];d2+=d*d;}
        if(d2>=carbon_lamp_fade_end2)continue;
        ++candidates;
        unsigned at=count;
        if(at==24){if(d2>=distances[23])continue;at=23;}
        while(at && d2<distances[at-1]){if(at<24){distances[at]=distances[at-1];indices[at]=indices[at-1];}--at;}
        distances[at]=d2;indices[at]=i;if(count<24)++count;
    }
    int shift=carbon_lamplight_shift || (diag_on && postfx_look_variant("lamplightshift"));
    *overflow=candidates-count;
    for(unsigned i=0;i<count;i++) {
        const CarbonLamp *lamp=&carbon_lamps[indices[i]];CarbonLampGPU *out=&k->lamps[i];
        int tunnel=lamp->inner<0;
        float fade=fminf(1,(carbon_lamp_fade_end2-distances[i])/
                            (carbon_lamp_fade_end2-carbon_lamp_fade_start2));
        if(!tunnel)fade*=level;
        for(unsigned j=0;j<3;j++) {
            /* The diagnostic control moves only emission, not native flares. */
            out->position[j]=(lamp->position[0]+(shift?40:0))*m[j]+lamp->position[1]*m[4+j]+lamp->position[2]*m[8+j]+m[12+j];
            out->rgb[j]=lamp->rgb[j]*fade;
        }
        out->position[3]=lamp->outer*lamp->outer;
        out->rgb[3]=tunnel?0:lamp->inner*lamp->inner;
        out->range[0]=tunnel?-lamp->inner:0;
        if(diag_on && diag_shot_due(diag_current_frame()+1))
            diag_event("lamplight source=%08X xyz=%.4f,%.4f,%.4f camera_distance=%.4f inner=%.3f outer=%.3f rgb=%.4f,%.4f,%.4f",lamp->hash,lamp->position[0],lamp->position[1],lamp->position[2],sqrtf(distances[i]),lamp->inner,lamp->outer,lamp->rgb[0],lamp->rgb[1],lamp->rgb[2]);
    }
    k->tune[0]=(float)count;k->tune[1]=CARBON_LAMPLIGHT_GAIN;
    return count;
}
static const char *carbon_lamplight_shader =
"struct Lamp {float4 position;float4 rgb;float4 range;};\n"
"struct LK {AK k;Lamp lamps[24];};\n"
"fragment float4 fs_lamplight(VOut i [[stage_in]],depth2d<float> z [[texture(1)]],texture2d<float> mask [[texture(3)]],constant LK &c [[buffer(0)]]){"
"constexpr sampler pt(coord::normalized,filter::nearest,address::clamp_to_edge);"
// Receiver weight, not a cut: protected texels (cars) are 0, a flare's glow
// keeps the light it leaves (1-alpha), so its faint tail shows no edge.
"float raw=ao_depth(z,i.uv,c.k),cover=mask.sample(pt,c.k.rect.xy+i.uv*c.k.rect.zw).r;if(raw>=0.999999||cover<=0.0)return float4(0);"
"float3 p=ao_point(i.uv,raw,c.k),n=ao_normal(z,i.uv,c.k),energy=float3(0);"
"for(uint j=0;j<uint(c.k.tune.x);++j){Lamp light=c.lamps[j];float3 delta=light.position.xyz-p;float d2=dot(delta,delta);"
"if(d2>=light.position.w)continue;"
"float incidence=max(dot(n,delta)*rsqrt(max(d2,1e-6)),0.0);"
// X360 09C0DE10 diffuse lobe. The overlay stores its authored radius and
// intensity, and these highway contexts all use the same first-light gain.
"if(light.range.x>0.0){energy+=light.rgb.xyz*float3(1.0,0.65,0.15)*incidence*(3.0*light.range.x/(2.0*d2+light.range.x));continue;}"
"float fade=d2<=light.rgb.w?1.0:clamp((light.position.w-d2)/max(light.position.w-light.rgb.w,1e-6),0.0,1.0);"
"energy+=light.rgb.xyz*c.k.tune.y*fade*incidence*(36.0/max(d2,36.0));}"
"return float4(energy*cover,0);}\n";
static id<MTLLibrary> carbon_lamplight_library;
static id<MTLRenderPipelineState> carbon_lamplight_pso[3][9];
static id<MTLRenderPipelineState> carbon_lamplight_pipeline(MTLPixelFormat format,NSUInteger samples) {
    if(!carbon_lamplight_library) {
        NSError *error=nil;
        NSString *source=[NSString stringWithFormat:@"%s%s%s",carbon_ao_vertex,render_contact_source(1),carbon_lamplight_shader];
        carbon_lamplight_library=pipeline_library_source(source,"lamplight",&error);
        if(!carbon_lamplight_library){fprintf(stderr,"lamplight shader: %s\n",error.localizedDescription.UTF8String);abort();}
    }
    unsigned slot=format==MTLPixelFormatBGRA8Unorm?0:format==MTLPixelFormatRGBA8Unorm?1:2;
    if((slot==2 && format!=MTLPixelFormatRGBA16Float)||samples>8)return nil;
    if(!carbon_lamplight_pso[slot][samples]) {
        MTLRenderPipelineDescriptor *d=[MTLRenderPipelineDescriptor new];
        d.vertexFunction=[carbon_lamplight_library newFunctionWithName:@"vs_full"];
        d.fragmentFunction=[carbon_lamplight_library newFunctionWithName:@"fs_lamplight"];
        d.colorAttachments[0].pixelFormat=format;d.rasterSampleCount=samples;
        d.colorAttachments[0].blendingEnabled=YES;
        d.colorAttachments[0].sourceRGBBlendFactor=MTLBlendFactorDestinationColor;
        d.colorAttachments[0].destinationRGBBlendFactor=MTLBlendFactorOne;
        d.colorAttachments[0].writeMask=MTLColorWriteMaskRed|MTLColorWriteMaskGreen|MTLColorWriteMaskBlue;
        carbon_lamplight_pso[slot][samples]=pipeline_build(d,"lamplight",NULL);
    }
    return carbon_lamplight_pso[slot][samples];
}
/* Loading prewarm: build the pass for every target format it can meet, so the first night frame builds nothing. */
void render_carbon_lamplight_prewarm(void) {
    if(!carbon_lamplight_on)return;
    const char *e=getenv("NFS_PSO_PREWARM");
    if(e && !atoi(e))return;
    for(NSNumber *format in @[@(MTLPixelFormatBGRA8Unorm),@(MTLPixelFormatRGBA8Unorm),@(MTLPixelFormatRGBA16Float)])
        for(NSUInteger samples=1;samples<=8;samples*=2)
            if([mtl supportsTextureSampleCount:samples])
                carbon_lamplight_pipeline(format.unsignedIntegerValue,samples);
}
/* Matched-shot sidecar: actual receiver depth/mask plus every cached street
 * position, so patch distances need no assumed road plane or selected subset.
 * LMP2 header: width,height,count,sim; view[16],proj[4]; then count CarbonLamp,
 * tightly packed float depth and R8 receiver mask. Diagnostic captures only. */
static void carbon_lamplight_proof(id<MTLTexture> z,id<MTLTexture> mask,uint32_t platform,const CarbonLampParams *k) {
    extern int postfx_look_listed(const char *);
    if(!postfx_look_listed("lamplightoff") || !diag_shot_due(diag_current_frame()+1))return;
    NSUInteger w=z.width,h=z.height,zpitch=(w*4+255)&~255ul,mw=mask.width,mh=mask.height,mpitch=(mw+255)&~255ul;
    id<MTLBuffer> zb=[mtl newBufferWithLength:zpitch*h options:MTLResourceStorageModeShared];
    id<MTLBuffer> mb=[mtl newBufferWithLength:mpitch*mh options:MTLResourceStorageModeShared];
    if(!zb||!mb)return;
    id<MTLBlitCommandEncoder> b=[cmd blitCommandEncoder];
    [b copyFromTexture:z sourceSlice:0 sourceLevel:0 sourceOrigin:MTLOriginMake(0,0,0) sourceSize:MTLSizeMake(w,h,1)
        toBuffer:zb destinationOffset:0 destinationBytesPerRow:zpitch destinationBytesPerImage:zpitch*h
        options:z.pixelFormat==MTLPixelFormatDepth32Float_Stencil8?MTLBlitOptionDepthFromDepthStencil:MTLBlitOptionNone];
    [b copyFromTexture:mask sourceSlice:0 sourceLevel:0 sourceOrigin:MTLOriginMake(0,0,0) sourceSize:MTLSizeMake(mw,mh,1)
        toBuffer:mb destinationOffset:0 destinationBytesPerRow:mpitch destinationBytesPerImage:mpitch*mh];[b endEncoding];
    struct {char magic[4];uint32_t w,h,count;float sim,view[16],proj[4];} header={{'L','M','P','2'},(uint32_t)w,(uint32_t)h,(uint32_t)carbon_lamps_count,MF32(0x00B4CFD8u)};
    for(unsigned i=0;i<16;i++)header.view[i]=MF32(platform+4*i);
    memcpy(header.proj,k->proj,sizeof header.proj);
    NSData *records=[NSData dataWithBytes:carbon_lamps length:carbon_lamps_count*sizeof *carbon_lamps];
    NSString *path=[NSString stringWithFormat:@"%s/lamplight_%05llu%s.lmp",diag_dir,(unsigned long long)(diag_current_frame()+1),postfx_look_variant("aoglowoff")?"_aoglowoff":""];
    [cmd addCompletedHandler:^(id<MTLCommandBuffer> done){
        if(done.status!=MTLCommandBufferStatusCompleted)return;
        FILE *f=fopen(path.UTF8String,"wb");if(!f)return;
        fwrite(&header,sizeof header,1,f);fwrite(records.bytes,records.length,1,f);
        for(NSUInteger y=0;y<h;y++)fwrite((const uint8_t *)zb.contents+y*zpitch,4,w,f);
        NSMutableData *row=[NSMutableData dataWithLength:w];uint8_t *pixels=row.mutableBytes;
        for(NSUInteger y=0;y<h;y++) {
            const uint8_t *src=(const uint8_t *)mb.contents+(NSUInteger)((y+0.5)*mh/h)*mpitch;
            for(NSUInteger x=0;x<w;x++)pixels[x]=src[(NSUInteger)((x+0.5)*mw/w)];
            fwrite(pixels,1,w,f);
        }
        fclose(f);
    }];
}
static void carbon_lamplight_apply(void) {
    if(!carbon_lamplight_on)return;
    if(diag_on && postfx_look_variant("lamplightoff"))return;
    if(M32(0x00A99BBCu)!=6)return;
    float level=carbon_dn_lamps_level();
    uint32_t platform=M32(0x00B4AF90u);if(!platform)return;
    float px=MF32(platform+0x40),py=MF32(platform+0x54),a=MF32(platform+0x68),b=MF32(platform+0x78);
    float zn=-b/a,zf=-b/(a-1);
    if(!isfinite(px)||!isfinite(py)||fabsf(px)<0.01f||fabsf(py)<0.01f||!(zn>0&&zf>zn&&zf<1e7))return;
    CarbonLampParams k={0};unsigned overflow=0;
    uint64_t started=diag_on?clock_gettime_nsec_np(CLOCK_UPTIME_RAW):0;
    unsigned count=carbon_lamplight_select(platform,level,&k,&overflow);
    double selection_ms=diag_on?(clock_gettime_nsec_np(CLOCK_UPTIME_RAW)-started)*1e-6:0;
    if(!count)return;
    RenderTex *world=carbon_hdr_rt(M32(0x00AB04F4u)),*depth=carbon_hdr_rt(M32(0x00AB04F8u));
    if(!world||!depth)return;
    end_pass();msaa_resolve(depth);ensure_cmd();
    id<MTLTexture> z=depth->tex,target=world->ms?:world->tex;
    if(!z||!target||z.width!=target.width||z.height!=target.height)return;
    id<MTLTexture> receivers=carbon_ao_receiver(z);if(!receivers)return;
    id<MTLRenderPipelineState> pipeline=carbon_lamplight_pipeline(target.pixelFormat,target.sampleCount);if(!pipeline)return;
    NSUInteger w=target.width,h=target.height;
    float proj[]={1/px,1/py,zn,zf},size[]={1.0f/w,1.0f/h,0,0},rect[]={0,0,1,1},bounds[]={0.5f/w,0.5f/h,1-0.5f/w,1-0.5f/h};
    memcpy(k.proj,proj,sizeof proj);memcpy(k.size,size,sizeof size);memcpy(k.rect,rect,sizeof rect);memcpy(k.bounds,bounds,sizeof bounds);
    if(diag_on)carbon_lamplight_proof(z,receivers,platform,&k);
    MTLRenderPassDescriptor *rp=[MTLRenderPassDescriptor renderPassDescriptor];
    rp.colorAttachments[0].texture=target;rp.colorAttachments[0].loadAction=MTLLoadActionLoad;rp.colorAttachments[0].storeAction=MTLStoreActionStore;
    if(gpt_on)gpt_render(rp,"lamplight");
    id<MTLRenderCommandEncoder> e=[cmd renderCommandEncoderWithDescriptor:rp];e.label=@"lamplight";if(gpt_on)gpt_name(e);
    [e setRenderPipelineState:pipeline];[e setFragmentTexture:z atIndex:1];[e setFragmentTexture:receivers atIndex:3];
    [e setFragmentBytes:&k length:sizeof k atIndex:0];[e drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:3];[e endEncoding];
    world->stale=world->ms!=nil;
    if(diag_on) {
        static unsigned max_selected,max_overflow;
        if(count>max_selected)max_selected=count;if(overflow>max_overflow)max_overflow=overflow;
        if(diag_shot_due(diag_current_frame()+1))diag_event("lamplight frame=%llu selected=%u max_selected=%u overflow=%u max_overflow=%u selection_ms=%.6f resolution=%lux%lu level=%.4f shift=%d",(unsigned long long)(diag_current_frame()+1),count,max_selected,overflow,max_overflow,selection_ms,(unsigned long)w,(unsigned long)h,level,carbon_lamplight_shift);
    }
}
