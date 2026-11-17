                {   /* Front-end WorldViewProj: scale the logical output-x column before packing. */
                    extern int carbon_fe_scope;
                    extern float carbon_fe_kx(void);
                    if (carbon_fe_scope && !strcmp(q->name, "WorldViewProj")) {
                        float kx = carbon_fe_kx();
                        if (kx < 1.0f) for (int k = 0; k < 4; ++k) m[k * 4] *= kx;
                    }
                }
