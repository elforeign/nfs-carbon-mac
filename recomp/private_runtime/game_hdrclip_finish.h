/* Native world -> resolve -> first post copy. Inspect the pair before any post
 * shader can overwrite the destination; export counts alone cannot prove loss. */
/* Conservative FP16 resolve at white: a finite average strictly above one
 * must survive as at least the next representable half. Other values retain
 * ordinary FP16 conversion. This is real scene transport, not a counter rule. */
static void carbon_hdr_world_resolve(void) {
    if(!float_scene_on)return;
    RenderTex *r=carbon_hdr_rt(M32(0x00AB04F4u));
    if(!r || !r->ms || r->tex.pixelFormat!=MTLPixelFormatRGBA16Float)return;
    end_pass();msaa_resolve(r);ensure_cmd();
    static id<MTLRenderPipelineState> pso;
    if(!pso) {
        NSString *source=@"#include <metal_stdlib>\nusing namespace metal;\nvertex float4 vs(uint v [[vertex_id]]){float2 p=float2((v<<1)&2,v&2);return float4(p*2-1,0,1);}\nfragment float4 fs(float4 pos [[position]],texture2d_ms<float,access::read> t [[texture(0)]]){float4 v=0;for(uint s=0;s<t.get_num_samples();s++)v+=t.read(uint2(pos.xy),s);v/=t.get_num_samples();v.rgb=select(v.rgb,max(v.rgb,float3(1.0009765625f)),v.rgb>1.0f);return v;}";
        NSError *error=nil;id<MTLLibrary> l=[mtl newLibraryWithSource:source options:nil error:&error];
        MTLRenderPipelineDescriptor *d=[MTLRenderPipelineDescriptor new];d.vertexFunction=[l newFunctionWithName:@"vs"];d.fragmentFunction=[l newFunctionWithName:@"fs"];d.colorAttachments[0].pixelFormat=MTLPixelFormatRGBA16Float;
        pso=pipeline_build(d,__func__,&error);
        if(!pso){if(diag_on)diag_event("float scene resolve: %s",error.localizedDescription.UTF8String);abort();}
    }
    MTLRenderPassDescriptor *rp=[MTLRenderPassDescriptor renderPassDescriptor];
    rp.colorAttachments[0].texture=r->tex;rp.colorAttachments[0].loadAction=MTLLoadActionDontCare;rp.colorAttachments[0].storeAction=MTLStoreActionStore;
    id<MTLRenderCommandEncoder> e=[cmd renderCommandEncoderWithDescriptor:rp];[e setRenderPipelineState:pso];[e setFragmentTexture:r->ms atIndex:0];[e drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:3];[e endEncoding];
    r->stale=0;
}
static id<MTLTexture> carbon_hdr_source;
static void carbon_hdr_dispatch_begin(void) {
    if(hc_select(HC_WORLD)>=HC_STAGES)return;
    uint32_t handle=M32(0x00AB04F4u);
    RenderTex *r=carbon_hdr_rt(handle); if(!r)return;
    hdrclip_scan(r->ms?:r->tex,HC_MSAA);
    msaa_resolve(r); carbon_hdr_source=r->tex;
    if(r->ms)hdrclip_pair(r->ms,r->tex,0);
    hdrclip_scan(r->tex,HC_RESOLVE);
    carbon_hdr_copy_pending=1;
}
static void carbon_hdr_copy_observe(void) {
    if(hc_select(HC_COPY)>=HC_STAGES)return;
    carbon_hdr_copy_pending=0;
    unsigned index=M32(0x00AB0B4Cu);
    if(index>1)return;
    RenderTex *r=carbon_hdr_rt(carbon_hdr_handle(1+index)); if(!r)return;
    msaa_resolve(r);
    hdrclip_pair(carbon_hdr_source,r->tex,1);
    hdrclip_scan(r->tex,HC_COPY);
}
void hdrclip_finish(void) {
    if(hc_select(HC_FINAL)>=HC_STAGES)return;
    carbon_hdr_copy_pending=0;
    uint32_t final=M32(0x00AB04D8u);
    RenderTex *fr=carbon_hdr_rt(final);
    if(final==dev.backbuffer)fr=&bb_rt;
    if(fr){hdrclip_scan(fr->ms?:fr->tex,HC_FINAL);msaa_resolve(fr);hdrclip_scan(fr->tex,HC_FINAL_RESOLVE);}
    id<MTLBuffer> targets=[mtl newBufferWithLength:12*16*sizeof(uint32_t) options:MTLResourceStorageModeShared];
    memset(targets.contents,0,targets.length);
    NSMutableData *metadata=[NSMutableData dataWithLength:12*5*sizeof(uint32_t)];
    uint32_t *meta=metadata.mutableBytes;
    for(unsigned i=0;i<12;i++) {
        uint32_t handle=carbon_hdr_handle(i);RenderTex *r=carbon_hdr_rt(handle);
        meta[i*5]=carbon_hdr_address(i);meta[i*5+1]=handle;
        if(!r)continue;
        end_pass();msaa_resolve(r);ensure_cmd();
        meta[i*5+2]=(uint32_t)r->tex.pixelFormat;meta[i*5+3]=(uint32_t)r->tex.width;meta[i*5+4]=(uint32_t)r->tex.height;
        hc_scan_texture(cmd,r->tex,targets,i);
    }
    end_pass();ensure_cmd();hc_finished=1;
    id<MTLBuffer> b=hc_buffer,pairs=hc_pairs;uint64_t frame=hc_frame;
    float sim=MF32(0x00B4CFD8u);unsigned flow=M32(0x00A99BBCu),promotions=carbon_hdr_promotions;
    NSData *families;unsigned family_count;
    @synchronized([NSProcessInfo class]) {
        family_count=hc_nfamilies;families=[NSData dataWithBytes:hc_families length:family_count*sizeof(HCFamily)];
    }
    [cmd addCompletedHandler:^(id<MTLCommandBuffer> cb){
        char path[1024];snprintf(path,sizeof path,"%s/hdrclip.csv",diag_dir);
        FILE *f=fopen(path,"w");if(!f)return;
        fprintf(f,"# frame=%llu sim=%.6f flow=%u status=%lu promotions=%u; exports precede depth/blend; white endpoints are censored\n",(unsigned long long)frame,sim,flow,(unsigned long)cb.status,promotions);
        fprintf(f,"# Carbon native post exports use other_export; MW-only stages 5-16,19-24 unused; native stored targets in hdrclip_targets.csv\n");
        fprintf(f,"stage,phase,n,rgb_hi,rgb_lo,alpha_hi,alpha_lo,nonfinite,rgb_white,alpha_white\n");
        const uint32_t *v=b.contents;
        for(unsigned s=0;s<HC_STAGES;s++)for(unsigned p=0;p<2;p++) {
            fprintf(f,"%s,%s",hc_names[s],p?(s==HC_WORLD?"sanitized_export":"stored"):"export");
            for(unsigned k=0;k<8;k++)fprintf(f,",%u",v[(s*2+p)*8+k]);fprintf(f,"\n");
        }
        fclose(f);
        snprintf(path,sizeof path,"%s/hdrclip_transport.csv",diag_dir);f=fopen(path,"w");if(!f)return;
        fprintf(f,"stage,pixels,source_rgb_hi,rgb_clipped,nonfinite\n");const uint32_t *pv=pairs.contents;
        for(unsigned s=0;s<2;s++)fprintf(f,"%s,%u,%u,%u,%u\n",s?"copy":"resolve",pv[s*4],pv[s*4+1],pv[s*4+2],pv[s*4+3]);
        fclose(f);
        snprintf(path,sizeof path,"%s/hdrclip_families.csv",diag_dir);f=fopen(path,"w");if(!f)return;
        fprintf(f,"shader,material,variant,n,rgb_hi,rgb_lo,alpha_hi,alpha_lo,nonfinite,rgb_white,alpha_white\n");
        const HCFamily *family=families.bytes;
        for(unsigned i=0;i<family_count;i++){
            fprintf(f,"%016llX,%d,%u",(unsigned long long)family[i].key,family[i].material,family[i].variant);
            for(unsigned k=0;k<8;k++)fprintf(f,",%u",v[(HC_STAGES*2+i)*8+k]);fprintf(f,"\n");
        }
        fclose(f);
        snprintf(path,sizeof path,"%s/hdrclip_targets.csv",diag_dir);f=fopen(path,"w");if(!f)return;
        fprintf(f,"address,handle,format,width,height,n,rgb_hi,rgb_lo,alpha_hi,alpha_lo,nonfinite,rgb_white,alpha_white\n");
        const uint32_t *m=metadata.bytes,*tv=targets.contents;
        for(unsigned i=0;i<12;i++){
            fprintf(f,"%08X,%08X,%u,%u,%u",m[i*5],m[i*5+1],m[i*5+2],m[i*5+3],m[i*5+4]);
            for(unsigned k=0;k<8;k++)fprintf(f,",%u",tv[(i*2+1)*8+k]);fprintf(f,"\n");
        }
        fclose(f);
    }];
}
