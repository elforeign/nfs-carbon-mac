    {   /* Package ownership spans FE/mask passes inside one native object draw.
         * Shared packages keep the existing whole-output wide correction. */
        extern int carbon_fe_scope;
        carbon_fe_scope = !strcmp(fx->name, "IDI_FE_FX") || !strcmp(fx->name, "IDI_FE_MASK_FX");
    }
