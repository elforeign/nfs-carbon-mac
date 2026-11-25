                {   /* Front-end WorldViewProj: scale the logical output-x column before packing. */
                    extern int carbon_fe_scope;
                    extern float carbon_fe_kx(void);
                    extern float carbon_fe_ky(void);
                    if (carbon_fe_scope && !strcmp(q->name, "WorldViewProj")) {
                        float kx = carbon_fe_kx(), ky = carbon_fe_ky();
                        for (int k = 0; k < 4; ++k) { m[k * 4] *= kx; m[k * 4 + 1] *= ky; }
                    }
                }
