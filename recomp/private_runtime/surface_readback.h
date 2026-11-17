/* Shared render-target state/command stream, private synchronous CPU readback. */
int private_surface_readback(uint32_t surface,uint32_t memory,uint32_t pitch){
    if(!mtl)return 1;
    Obj *s=obj(surface);if(!s)return 0;
    NSUInteger level=0,slice=0;end_pass();id<MTLTexture> texture=surface_target(surface,&level,&slice);
    if(texture.sampleCount>1){RenderTex *rt=surface_rt(surface);if(!rt)return 0;msaa_resolve(rt);end_pass();texture=rt->tex;level=slice=0;}
    if(!texture||is_depth_fmt(s->fmt))return 0;
    uint32_t row=(is_dxt(s->fmt)?(s->w+3)/4:s->w)*fmt_bpp(s->fmt),rows=level_rows(s->fmt,s->h);
    // Renderable formats use their native Metal byte layout here; converted
    // non-renderable resources keep their shared guest-side backing instead.
    int conv=0;MTLTextureSwizzleChannels sw;
    if(texture.pixelFormat!=mtl_format(s->fmt,&conv,&sw)||conv)return 0;
    NSUInteger stride=(row+255u)&~255u;id<MTLBuffer> data=[mtl newBufferWithLength:stride*rows options:MTLResourceStorageModeShared];if(!data)return 0;
    ensure_cmd();id<MTLBlitCommandEncoder> blit=[cmd blitCommandEncoder];
    [blit copyFromTexture:texture sourceSlice:slice sourceLevel:level sourceOrigin:MTLOriginMake(0,0,0) sourceSize:MTLSizeMake(s->w,s->h,1) toBuffer:data destinationOffset:0 destinationBytesPerRow:stride destinationBytesPerImage:stride*rows];[blit endEncoding];
    id<MTLCommandBuffer> submitted=cmd;cmd=nil;__block int okay=0;dispatch_semaphore_t done=dispatch_semaphore_create(0);
    [submitted addCompletedHandler:^(id<MTLCommandBuffer> b){okay=b.status==MTLCommandBufferStatusCompleted;dispatch_semaphore_signal(done);}];
    [submitted commit];[submitted waitUntilCompleted];dispatch_semaphore_wait(done,DISPATCH_TIME_FOREVER);if(!okay)return 0;
    for(uint32_t y=0;y<rows;y++)memcpy(G+memory+(size_t)y*pitch,(const uint8_t*)data.contents+y*stride,row);
    return 1;
}
int private_surface_upload(uint32_t surface,uint32_t memory,uint32_t pitch){
    if(!mtl)return 1;Obj *s=obj(surface);if(!s)return 0;
    int conv=0;MTLTextureSwizzleChannels sw;MTLPixelFormat fmt=mtl_format(s->fmt,&conv,&sw);if(conv||is_depth_fmt(s->fmt)||is_dxt(s->fmt))return 0;
    end_pass();NSUInteger level=0,slice=0;id<MTLTexture> dst=surface_target(surface,&level,&slice);if(!dst)return 0;
    MTLTextureDescriptor *d=[MTLTextureDescriptor texture2DDescriptorWithPixelFormat:fmt width:s->w height:s->h mipmapped:NO];d.storageMode=MTLStorageModeShared;d.usage=MTLTextureUsageShaderRead;
    id<MTLTexture> source=[mtl newTextureWithDescriptor:d];if(!source)return 0;
    [source replaceRegion:MTLRegionMake2D(0,0,s->w,s->h) mipmapLevel:0 withBytes:G+memory bytesPerRow:pitch];
    ensure_cmd();if(dst.sampleCount>1){if(fmt!=MTLPixelFormatBGRA8Unorm)return 0;MTLRegion rect=MTLRegionMake2D(0,0,s->w,s->h);blit_quad(source,rect,dst,level,slice,rect,0);RenderTex *rt=surface_rt(surface);if(rt)rt->stale=1;}
    else{id<MTLBlitCommandEncoder> blit=[cmd blitCommandEncoder];[blit copyFromTexture:source sourceSlice:0 sourceLevel:0 sourceOrigin:MTLOriginMake(0,0,0) sourceSize:MTLSizeMake(s->w,s->h,1) toTexture:dst destinationSlice:slice destinationLevel:level destinationOrigin:MTLOriginMake(0,0,0)];[blit endEncoding];}return 1;
}
