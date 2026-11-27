    {   /* A fixed-function pass of a front-end effect: the same wide correction, once. */
        extern int carbon_fe_scope;
        extern float carbon_fe_kx(void);
        extern float carbon_fe_ky(void);
        extern int carbon_splithud_transform(float *);
        if (carbon_fe_scope) {
            float t[4];
            if (carbon_splithud_transform(t)) {
                for (int k = 0; k < 4; ++k) {
                    vsc[0][k] = vsc[0][k] * t[0] + vsc[3][k] * t[2];
                    vsc[1][k] = vsc[1][k] * t[1] + vsc[3][k] * t[3];
                }
            } else {
                float kx = carbon_fe_kx(), ky = carbon_fe_ky();
                for (int k = 0; k < 4; ++k) { vsc[0][k] *= kx; vsc[1][k] *= ky; }
            }
        }
    }
