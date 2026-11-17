static int e_EndPass(Cpu *c) {
    extern int carbon_fe_scope;
    Effect *fx = FX;
    fx->in_pass = 0;
    carbon_fe_scope = 0;
    snprintf(diag_fx_pass, sizeof diag_fx_pass, "(no effect pass)");
    RET(D3D_OK, 1);
}
