/* Native UI TextureInfo (92 bytes) and platform (24 bytes), never the shared game's layout. */
enum { CT_PLATFORM=0, CT_HASH=0x0C, CT_BYTES=0x1C, CT_TOP_BYTES=0x24,
       CT_WIDTH=0x28, CT_HEIGHT=0x2A, CT_LOG_WIDTH=0x2C, CT_LOG_HEIGHT=0x2D,
       CT_DEPTH=0x2E, CT_MIPS=0x32, CT_PACK=0x4C, CT_PIXELS=0x50, CT_PALETTE=0x54,
       CT_ALPHA_USAGE=0x39, CT_BLEND=0x3A, CT_FORMAT=0x0C, CT_DEVICE_TEXTURE=0x10, CT_SIDE=32, CT_SIZE=4096 };
static uint32_t carbon_texture_new_size(uint32_t hash, const char *name, const uint8_t *pixels,
                                        unsigned width, unsigned height) {
    unsigned size=width*height*4, lw=0, lh=0;
    if(!width || !height || width>1024 || height>1024 || (width&(width-1)) || (height&(height-1)))return 0;
    for(unsigned n=width;n>1;n>>=1)++lw;
    for(unsigned n=height;n>1;n>>=1)++lh;
    uint32_t ti=gmalloc(128+24+size), pl=ti+128, data=pl+24;
    M32(ti+CT_PLATFORM)=pl;
    M32(ti+CT_HASH)=hash; M32(ti+0x18)=UINT32_MAX;
    M32(ti+CT_BYTES)=size; M32(ti+CT_TOP_BYTES)=size;
    M16(ti+CT_WIDTH)=width; M16(ti+CT_HEIGHT)=height;
    M8(ti+CT_LOG_WIDTH)=lw; M8(ti+CT_LOG_HEIGHT)=lh; M8(ti+CT_DEPTH)=32;
    M8(ti+CT_MIPS)=1;
    M8(ti+CT_ALPHA_USAGE)=2; M8(ti+CT_BLEND)=1; /* Native straight-alpha FE material. */
    M32(ti+CT_PACK)=0; M32(ti+CT_PIXELS)=data; M32(ti+CT_PALETTE)=0;
    M32(pl+CT_FORMAT)=0x15;
    snprintf((char *)G+ti+0x59,31,"%s",name);
    memcpy(G+data,pixels,size);
    return ti;
}
static uint32_t carbon_texture_new(uint32_t hash, const char *name, const uint8_t *pixels) {
    return carbon_texture_new_size(hash,name,pixels,CT_SIDE,CT_SIDE);
}
/* Native reset releases every linked platform and zeros +10. Retain CPU pixels;
 * re-enter native upload lazily, which links the platform into the new device list. */
static int carbon_texture_ready(Cpu *c, uint32_t ti) {
    uint32_t pl=M32(ti+CT_PLATFORM);
    if (M32(pl+CT_DEVICE_TEXTURE)) return 1;
    if (!M32(0x00AB0ABCu) || M8(0x00AB09ECu)) return 0;
    Cpu upload=*c; upload.esp-=128; upload.ecx=ti;
    call_guest(&upload,0x00725C80u,0,NULL);
    return M32(pl+CT_DEVICE_TEXTURE)!=0;
}
