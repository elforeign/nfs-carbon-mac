{
    draw_impl(type,prims,indexed,base_vertex,min_index,num_vertices,start,up_vertices,up_stride,up_indices,up_index_fmt);
    if((!carbon_ao_on && !carbon_lamplight_on) || M32(0x00A99BBCu)!=6 || !prims || q_active)return;
    /* Only the primary scene: reflection views can share the same depth object. */
    RenderTex *world=carbon_hdr_rt(M32(0x00AB04F4u)),*zr=surface_rt(dev.ds);
    if(!world || surface_rt(dev.rt[0])!=world || zr!=carbon_hdr_rt(M32(0x00AB04F8u)))return;
    NSUInteger lv,sl;
    id<MTLTexture> color=surface_target(dev.rt[0],&lv,&sl),z=surface_target(dev.ds,&lv,&sl);
    if(!color || !z || color.width!=z.width || color.height!=z.height ||
        color.sampleCount!=z.sampleCount || !ssao_prepare(z))return;
    if(ssao_serial!=frame_serial || ssao_depth!=zr->tex){
        ssao_depth=zr->tex;ssao_coverage_z=ssao_half_depth;ssao_serial=frame_serial;ssao_cleared=0;
        ssao_rec=rt_render_list_new();memset(&ssao_eb,0,sizeof ssao_eb);
    }
    extern char diag_fx_pass[];
    int kind=(dev.rs[168]&7)?carbon_ao_protected(diag_fx_pass,dev.rs[27]?dev.rs[20]:0):0;
    if(!kind)return;
    /* An additive world decal protects only where it has alpha: INVSRCALPHA coverage. */
    ssao_replay_dst=kind==2?6:1;
    ssao_record(type,prims,indexed,base_vertex,min_index,num_vertices,start,up_vertices,up_stride,up_indices,up_index_fmt);
    ssao_replay_dst=1;
}
static id<MTLTexture> carbon_ao_receiver(id<MTLTexture> depth) {
    static uint64_t built_serial=~0ull;
    static id<MTLTexture> built_depth;
    if(ssao_serial!=frame_serial || ssao_depth!=depth)return nil;
    if(built_serial==frame_serial && built_depth==depth)return ssao_mask.tex;
    if(!ssao_depth_prepare(depth))return nil;
    ssao_open(ssao_half_depth,0);
    rt_render_list_replay(ssao_rec,enc);end_pass();memset(&ssao_eb,0,sizeof ssao_eb);
    built_serial=frame_serial;built_depth=depth;
    return ssao_mask.tex;
}
