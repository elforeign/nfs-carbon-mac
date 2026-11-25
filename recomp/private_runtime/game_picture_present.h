{
    extern int *carbon_frame_limit_choice;
    void carbon_picture_wait(void);
    int carbon_simrate_enabled(void);
    present();
    void carbon_lan_menu_tick(Cpu *);
    carbon_lan_menu_tick(c);
    if (diag_on) (void)aa_game_get();
    if (*carbon_frame_limit_choice || carbon_simrate_enabled()) carbon_picture_wait();
    gil_yield(c);
    RET(D3D_OK, 5);
}
