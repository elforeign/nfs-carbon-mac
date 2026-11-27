                {   /* Front-end WorldViewProj: scale the logical output-x column before packing. */
                    extern int carbon_fe_scope;
                    extern float carbon_fe_kx(void);
                    extern float carbon_fe_ky(void);
                    extern int carbon_splithud_transform(float *);
                    extern void carbon_splithud_clip(Cpu *);
                    if (carbon_fe_scope && !strcmp(q->name, "WorldViewProj")) {
                        float t[4];
                        if (carbon_splithud_transform(t)) {
                            for (int k = 0; k < 4; ++k) {
                                m[k * 4] = m[k * 4] * t[0] + m[k * 4 + 3] * t[2];
                                m[k * 4 + 1] = m[k * 4 + 1] * t[1] + m[k * 4 + 3] * t[3];
                            }
                            /* Pass states are applied before CTAB uploads. */
                            carbon_splithud_clip(c);
                        } else {
                            float kx = carbon_fe_kx(), ky = carbon_fe_ky();
                            for (int k = 0; k < 4; ++k) { m[k * 4] *= kx; m[k * 4 + 1] *= ky; }
                        }
                    }
                }
