static void ff_shader_warm(void) {
    // The effects' fixed world/environment passes use stage-0 texture/diffuse
    // modulation/selection. Use the same builder, without occupying ff_cache.
    const uint32_t ops[][2] = {{4,4}, {5,4}, {6,4}, {4,2}, {2,2}, {1,1}};
    SmOptions opt; sm_default_options(&opt);
    for (int col = 0; col <= 1; ++col) for (int tc = -1; tc < 8; ++tc) {
        for (unsigned i = 0; i < sizeof ops / sizeof *ops; ++i) {
            FFShader f = {0};
#if NFS_GAME == NFS_GAME_MW
            ff_build(&f, col, tc >= 0, tc >= 0 ? tc : 0, ops[i][0], 2, 1, ops[i][1], 2, 1);
#else
            ff_build(&f, 0, col, tc >= 0, tc >= 0 ? tc : 0, ops[i][0], 2, 1, ops[i][1], 2, 1);
#endif
            get_shader(&f.vs, &opt); get_shader(&f.ps, &opt);
            free(f.vs.tokens); free(f.ps.tokens);
        }
    }
}
