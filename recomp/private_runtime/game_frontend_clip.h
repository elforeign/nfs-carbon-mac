    {   /* A fixed-function pass of a front-end effect: the same wide correction, once. */
        extern int carbon_fe_scope;
        extern float carbon_fe_kx(void);
        if (carbon_fe_scope) {
            float kx = carbon_fe_kx();
            if (kx < 1.0f) for (int k = 0; k < 4; ++k) vsc[0][k] *= kx;
        }
    }
