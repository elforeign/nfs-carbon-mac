/* BOOT_DIAG uses the shared mix accumulator and null sink, without a PCM tap.
 * Carbon game-flow word: 00699FA0 -> 3 (front end), 006BBDF0 -> 4 (load),
 * 006B56B0 tests 6 (world). No shared-runtime guest addresses are read here. */
static FILE *private_mix_file;
static FILE *private_frame_times;
static uint64_t private_mix_last;
static void private_mix_init(const char *dir) {
    char path[4096];
    snprintf(path,sizeof path,"%s/stats.log",dir);
    private_mix_file=fopen(path,"w");
    snprintf(path,sizeof path,"%s/frame_times.tsv",dir);
    private_frame_times=fopen(path,"w");
    private_mix_last=0;
}
static void private_mix_frame(uint64_t frame) {
#if PRIVATE_CARBON_SKIPFE
    if(!private_mix_file)return;
    uint64_t now=host_ticks();
    /* One buffered timestamp per Present permits equal wall-time windows in
     * private diagnostic A/B runs; no session timing claim is implied. */
    if(private_frame_times)fprintf(private_frame_times,"%llu\t%llu\t%u\n",
            (unsigned long long)now,(unsigned long long)frame,M32(0x00A99BBCu));
    if(private_mix_last && now-private_mix_last<1000000000ull)return;
    private_mix_last=now;
    int dsound_mix_rms(double [6],uint64_t *,uint64_t *,double *);
    void private_mix_buffers(unsigned *,unsigned *);
    double rms[6]={0};uint64_t clipped=0,limited=0;
    int have=dsound_mix_rms(rms,&clipped,&limited,NULL);
    void private_carbon_audio_stats(uint64_t [5],double [2]);
    uint64_t ac[5]={0};double ap[2]={0};
    private_carbon_audio_stats(ac,ap);
    unsigned buffers=0,playing=0;
    private_mix_buffers(&buffers,&playing);
    /* 0089F7AF allocates capacity * 0x84 common-voice records; 008A0B25
     * rejects state byte +0x69 == 0. 008A0A1E marks a stopped voice zero.
     * These are guest voices feeding the shared stream, not DSound buffers. */
    unsigned voices=0,channels=0,capacity=M16(0x00BBF378u);
    uint32_t pool=M32(0x00BBF3D0u);
    if(pool && capacity<=255 && pool<=UINT32_MAX-capacity*0x84u)
        for(unsigned i=0;i<capacity;++i){
            uint32_t v=pool+i*0x84u;
            if(M8(v+0x69u)){++voices;channels+=M8(v+0x23u);}
        }
    fprintf(private_mix_file,"t %.1f frame %llu mixrms %s%.6f %.6f %.6f %.6f %.6f %.6f clip %llu limit_samples %llu flow %u buffers %u playing %u voices %u/%u voice_channels %u pre_samples %llu pre_clip %llu pre_limit %llu pre_peak %.9f out_over %llu out_clip %llu out_peak %.9f\n",
            now/1e9,(unsigned long long)frame,have?"":"(n/a) ",
            rms[0],rms[1],rms[2],rms[3],rms[4],rms[5],
            (unsigned long long)clipped,(unsigned long long)limited,
            M32(0x00A99BBCu),buffers,playing,voices,capacity,channels,
            (unsigned long long)ac[0],(unsigned long long)ac[1],(unsigned long long)ac[2],ap[0],
            (unsigned long long)ac[3],(unsigned long long)ac[4],ap[1]);
    fflush(private_mix_file);
    if(private_frame_times)fflush(private_frame_times);
#else
    (void)frame;
#endif
}
