static unsigned hc_select(unsigned stage) {
    if(!hdrclip_on)return HC_STAGES;
    if(!hc_frame && M32(0x00A99BBCu)==6 && MF32(0x00B4CFD8u)>=15.0f)hc_frame=frame_serial;
    if(hc_finished || hc_frame!=frame_serial)return HC_STAGES;
    /* Native shaders share the world/export instrumentation; post stays other. */
    if(stage==HC_OTHER && carbon_hdr_world_phase)return HC_WORLD;
    return stage;
}
