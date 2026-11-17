/* Carbon's Xenon v8 TPKs: variable TextureInfo records and 32-byte platforms.
 * Read player-supplied files, never transplant a platform record into the PC ABI.
 * The existing extra-texture root selects the extract; absent/partial data keeps keycaps. */
#include "roots.h"


typedef struct { uint8_t *pixels; unsigned width,height; } XboxSurface;
static uint32_t xbox_hashes[GLYPHS],xbox_textures[GLYPHS],xbox_diagrams[2];
static int xbox_state=-1;
static uint32_t xb_word(const uint8_t *p) {uint32_t n;memcpy(&n,p,4);return n;}
/* Bounded JDLZ v2 byte stream; no engine entry points or platform records. */
static unsigned xb_jdlz(const uint8_t *in,unsigned size,uint8_t *out,unsigned capacity) {
    if(size<18 || memcmp(in,"JDLZ",4) || in[4]!=2)return 0;
    unsigned count=xb_word(in+8),stored=xb_word(in+12);
    if(count>capacity || stored<18 || stored>size)return 0;
    unsigned p=18,o=0,literals=in[16]|256u,matches=in[17]|256u;
    while(p<stored) {
        if(!(literals&1)) {
            if(o<count)out[o++]=in[p++];
            else ++p; /* Shipped blocks include terminal literal padding. */
        } else {
            if(stored-p<2)return 0;
            unsigned a=in[p++],b=in[p++],length,distance;
            if(matches&1) {length=((a&240)<<4|b)+3;distance=(a&15)+1;}
            else {length=(a&31)+3;distance=((a&224)<<3|b)+17;}
            if(distance>o || length>count-o)return 0;
            for(unsigned i=0;i<length;++i) {out[o]=out[o-distance];++o;}
            matches>>=1;
        }
        literals>>=1;
        if(literals==1 && p<stored)literals=in[p++]|256u;
        if(matches==1 && p<stored)matches=in[p++]|256u;
    }
    return o==count?count:0;
}
static uint8_t *xb_file(const char *root,const char *name,size_t *size) {
    char path[2400];snprintf(path,sizeof path,"%s/%s",root,name);
    FILE *f=fopen(path,"rb");if(!f)return NULL;
    if(fseek(f,0,SEEK_END)) {fclose(f);return NULL;}
    long n=ftell(f);if(n<=0 || n>64*1024*1024 || fseek(f,0,SEEK_SET)) {fclose(f);return NULL;}
    uint8_t *p=malloc((size_t)n);
    if(!p || fread(p,1,(size_t)n,f)!=(size_t)n) {free(p);fclose(f);return NULL;}
    fclose(f);*size=(size_t)n;return p;
}
static unsigned xb_tiled(unsigned x,unsigned y,unsigned width) {
    unsigned macro=((x>>5)+(y>>5)*((width+31u)>>5))<<9;
    unsigned micro=((x&7)+((y&6)<<2))<<2;
    unsigned off=macro+((micro&~15u)<<1)+(micro&15)+((y&8)<<5)+((y&1)<<4);
    return (((off&~511u)<<3)+((off&448)<<2)+(off&63)+((y&16)<<7)+(((((y&8)>>2)+(x>>3))&3)<<6))>>2;
}
static int xb_pixels(const uint8_t *data,size_t size,const uint8_t *record,
                     const uint8_t *platform,XboxSurface *out) {
    unsigned w=record[40]|record[41]<<8,h=record[42]|record[43]<<8;
    /* This source set uses tiled 8888, 8-in-32 endian swap. Reject other ABIs. */
    uint32_t format=xb_word(platform+20);
    if(!w || !h || w>256 || h>256 || (w&(w-1)) || (h&(h-1)) ||
       (format&0x1FFu)!=0x186u)return 0;
    uint8_t *pixels=malloc(w*h*4);if(!pixels)return 0;
    for(unsigned y=0;y<h;++y)for(unsigned x=0;x<w;++x) {
        size_t off=(size_t)xb_tiled(x,y,w)*4;
        if(off>size || size-off<4) {free(pixels);return 0;}
        for(unsigned k=0;k<4;++k)pixels[4*(y*w+x)+k]=data[off+(k^3u)];
    }
    *out=(XboxSurface){pixels,w,h};return 1;
}
static const char *xb_name(unsigned i) {
    const char *name=glyphs[i].name;
    if(!strcmp(name,"SELECT"))return "BACK";
    if(!strcmp(name,"L3"))return "LEFT_ANALOG";
    if(!strcmp(name,"L1_LOADING"))return "L1";
    if(!strcmp(name,"R1_LOADING"))return "R1";
    return name;
}
static void xb_pack(const uint8_t *b,size_t begin,size_t end,XboxSurface *surfaces,unsigned depth) {
    if(depth>8)return;
    for(size_t p=begin;p+8<=end;) {
        uint32_t id=xb_word(b+p),n=xb_word(b+p+4);
        if(n>end-p-8)return;
        size_t stop=p+8+n;
        if(id==0xB3300000u) {
            size_t info=0,infos=0,platform=0,platforms=0,data=0,bytes=0;
            for(size_t q=p+8;q+8<=stop;) {
                uint32_t kind=xb_word(b+q),sz=xb_word(b+q+4);if(sz>stop-q-8)break;
                if(kind==0xB3310000u || kind==0xB3320000u) {
                    for(size_t r=q+8;r+8<=q+8+sz;) {
                        uint32_t tag=xb_word(b+r),len=xb_word(b+r+4);if(len>q+8+sz-r-8)break;
                        if(tag==0x33310004u) {info=r+8;infos=len;}
                        if(tag==0x33310005u) {platform=r+8;platforms=len;}
                        if(tag==0x33320002u || tag==0x33320003u) {data=r+8;bytes=len;}
                        r+=8+len;
                    }
                }
                q+=8+sz;
            }
            if(info && platform && data) {
                size_t first=data;while(first<data+bytes && b[first]==0x11)++first;
                size_t base=p+((first-p)&~4095u);if(base<data)base=data;
                unsigned index=0;
                for(size_t r=info;r+89<=info+infos;) {
                    unsigned names=b[r+88],len=(89+names+3)&~3u;
                    if(!names || len>info+infos-r || (size_t)(index+1)*32>platforms)break;
                    const uint8_t *rec=b+r,*pl=b+platform+index*32;
                    const char *name=(const char *)rec+89;
                    if(!memchr(name,0,names))break;
                    unsigned off=xb_word(rec+20),size=xb_word(rec+36);
                    if(off<=data+bytes-base && size<=data+bytes-base-off &&
                       xb_word(rec+12)==prompt_hash(name)) {
                        for(unsigned i=0;i<GLYPHS;++i)if(!surfaces[i].pixels && !strcmp(name,xb_name(i)))
                            xb_pixels(b+base+off,size,rec,pl,surfaces+i);
                    }
                    r+=len;++index;
                }
            }
        } else if(id&0x80000000u)xb_pack(b,p+8,stop,surfaces,depth+1);
        p=stop;
    }
}
/* Streaming envelopes contain bounded, non-overlapping JDLZ blocks. The table's
 * unpacked size includes the trailing 124-byte record and 32-byte platform. */
static uint8_t *xb_stream(const uint8_t *b,size_t size,unsigned output) {
    if(!output || output>2*1024*1024)return NULL;
    uint8_t *out=calloc(1,output);if(!out)return NULL;
    size_t p=0,written=0;uint64_t visited=0;
    while(p+24<=size && written<output) {
        if(xb_word(b+p)!=0x55441122u)break;
        unsigned n=xb_word(b+p+4),block=xb_word(b+p+8),dst=xb_word(b+p+12),relative=xb_word(b+p+16);
        size_t source=p+24;
        if(dst>=output || (dst&32767u) || n!=(output-dst<32768u?output-dst:32768u) ||
           (visited&(UINT64_C(1)<<(dst>>15))) || block<24 || block>size-p || relative!=p)break;
        visited|=UINT64_C(1)<<(dst>>15);
        if(block>=28 && !memcmp(b+source,"JDLZ",4)) {
            if(xb_jdlz(b+source,block-24,out+dst,n)!=n)break;
        } else {
            if(n>block-24)break;
            memcpy(out+dst,b+source,n);
        }
        p+=block;
        written+=n;
    }
    if(written!=output) {free(out);return NULL;}
    return out;
}
static void xb_diagram_pack(const uint8_t *b,size_t begin,size_t end,size_t whole,
                            XboxSurface *diagrams,unsigned depth) {
    if(depth>8)return;
    for(size_t p=begin;p+8<=end;) {
        unsigned id=xb_word(b+p),n=xb_word(b+p+4);if(n>end-p-8)return;
        if(id==0x33310003u && !(n%24)) {
            for(size_t q=p+8;q+24<=p+8+n;q+=24) {
                uint32_t hash=xb_word(b+q);if(hash!=0xEC3C0443u && hash!=0xEC3C0444u)continue;
                unsigned slot=hash-0xEC3C0443u,off=xb_word(b+q+4),stored=xb_word(b+q+8),size=xb_word(b+q+12);
                if(diagrams[slot].pixels || off>whole || stored>whole-off || size<156)continue;
                uint8_t *raw=xb_stream(b+off,stored,size);if(!raw)continue;
                const uint8_t *rec=raw+size-156,*pl=raw+size-32;
                if(xb_word(rec+12)==hash)xb_pixels(raw,size-156,rec,pl,diagrams+slot);
                free(raw);
            }
        } else if(id&0x80000000u)xb_diagram_pack(b,p+8,p+8+n,whole,diagrams,depth+1);
        p+=8+n;
    }
}
/* The decoded dimensions also bound each allocation. Validate the whole family
 * before a fixed-size diagram upload can read any of those buffers. */
static int xb_surfaces_ready(const XboxSurface *surfaces) {
    for(unsigned i=0;i<GLYPHS+2;++i) {
        unsigned side=i<GLYPHS?32:256;
        if(!surfaces[i].pixels || surfaces[i].width!=side || surfaces[i].height!=side)return 0;
    }
    return 1;
}
static int xbox_assets(void) {
    if(xbox_state>=0)return xbox_state;
    xbox_state=0;
    const char *root=getenv("NFS_X360_EXTRA_TEXTURES");
    if(root && !strcasecmp(root,"off"))return 0;
    if(!root || !*root)root=roots_x360_files();
    XboxSurface surfaces[GLYPHS+2]={0};size_t size=0;
    uint8_t *data=xb_file(root,"GLOBAL/GLOBALB.BUN",&size);
    if(data) {xb_pack(data,0,size,surfaces,0);free(data);}
    unsigned found=0;for(unsigned i=0;i<GLYPHS;++i)found+=surfaces[i].pixels!=NULL;
    if(found==GLYPHS) {
        data=xb_file(root,"GLOBAL/DYNTEX.BIN",&size);
        if(data) {xb_diagram_pack(data,0,size,size,surfaces+GLYPHS,0);free(data);}
        if(xb_surfaces_ready(surfaces)) {
            for(unsigned i=0;i<GLYPHS;++i) {
                char name[80];snprintf(name,sizeof name,"PADPROMPT_XBOX_%s",glyphs[i].name);
                xbox_hashes[i]=prompt_hash(name);
                xbox_textures[i]=carbon_texture_new_size(xbox_hashes[i],glyphs[i].name,surfaces[i].pixels,
                                                        surfaces[i].width,surfaces[i].height);
            }
            for(unsigned i=0;i<2;++i)xbox_diagrams[i]=carbon_texture_new_size(0xEC3C0443u+i,"X360_CONTROLLER",surfaces[GLYPHS+i].pixels,256,256);
            xbox_state=1;
        }
    }
    for(unsigned i=0;i<GLYPHS+2;++i)free(surfaces[i].pixels);
    if(diag_on)diag_event("carbon Xbox assets glyphs=%u/%u diagrams=%d ready=%d",found,(unsigned)GLYPHS,
                         !!xbox_diagrams[0]+!!xbox_diagrams[1],xbox_state);
    return xbox_state;
}
