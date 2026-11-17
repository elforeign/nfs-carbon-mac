/* Absolute-frame selectors only: no assumptions about a private game's state. */
static int private_frame_wanted(uint64_t frame, const char *list_env) {
    const char *p=getenv(list_env);
    while(p && *p && *p!=':') {
        char *end;unsigned long long n=strtoull(p,&end,10);
        if(end==p)return 0;
        if(n==frame && (!*end || *end==',' || *end==':'))return 1;
        if(*end!=',')return 0;p=end+1;
    }
    return 0;
}
static int private_shot_due(uint64_t frame) {
    if(!diag_on || !frame)return 0;
    const char *list=getenv("BOOT_DIAG_SHOTS");
    if((!list && frame<=3) || private_frame_wanted(frame,"BOOT_DIAG_SHOTS"))return 2;
    const char *every=getenv("BOOT_DIAG_SHOT_EVERY");
    unsigned long long n=every?strtoull(every,NULL,10):300;
    return n && frame%n==0?2:0;
}
