
        extern uint64_t diag_current_frame(void);
        if(diag_on && diag_frame_wanted(diag_current_frame(),"BOOT_DIAG_DRAWS")){
            float input[4]={0};get_floats(p,input,p->bytes/4<4?p->bytes/4:4);
            diag_event("PRIVATE FX INPUT %s %s reg=%u count=%u value=%g,%g,%g,%g packed=%g,%g,%g,%g",
                       ps?"ps":"vs",p->name,ri,nreg,input[0],input[1],input[2],input[3],regs[0][0],regs[0][1],regs[0][2],regs[0][3]);
        }
