{
    ++dev.frames;
    uint64_t draws=dev.frame_draws;dev.frame_draws=0;
    diag_frame(dev.frames,draws);
    if(diag_on && dev.frames<=3)diag_event("PRIVATE PRESENT frame=%llu draws=%llu",(unsigned long long)dev.frames,(unsigned long long)draws);
    render_present();
    user32_script(dev.frames,draws);
    void portmenu_frame(void);
    portmenu_frame();
}
