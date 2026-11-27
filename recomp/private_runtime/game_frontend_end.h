static int e_EndPass(Cpu *c) {
    extern int carbon_fe_scope;
    Effect *fx = FX;
    fx->in_pass = 0;
    /* The object scope drains its last batch before restoring the entry clip;
     * ending a mask pass must not discard ownership before its colour pass. */
    carbon_fe_scope = 0;
    snprintf(diag_fx_pass, sizeof diag_fx_pass, "(no effect pass)");
    RET(D3D_OK, 1);
}
