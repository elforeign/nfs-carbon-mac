    {   /* Front-end effects are laid out for 4:3; their passes get the wide correction. */
        extern int carbon_fe_scope;
        carbon_fe_scope = !strcmp(fx->name, "IDI_FE_FX") || !strcmp(fx->name, "IDI_FE_MASK_FX");
    }
