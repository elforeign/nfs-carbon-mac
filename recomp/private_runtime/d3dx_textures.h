/* Private-image D3DX texture utilities. Included after the shared D3D resource
 * implementation, so resources, pitches, mip storage and vtables are shared. */
#import <ImageIO/ImageIO.h>
#include <math.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/stat.h>
#include <errno.h>
#define PX_INVALID 0x8876086cu
#define PX_DATA 0x88760b59u
#define PX_UNSUPPORTED 0x8876086au
extern int private_resolve(const char *,char *,size_t);
extern int private_surface_readback(uint32_t,uint32_t,uint32_t);
extern int private_surface_upload(uint32_t,uint32_t,uint32_t);
static uint32_t px_u32(const uint8_t *p){uint32_t v;memcpy(&v,p,4);return v;}
static void px_put(uint8_t *p,uint32_t v){memcpy(p,&v,4);}
static int px_range(uint32_t p,uint64_t n){return p && (uint64_t)p+n<=0x100000000ull;}
static int px_format(uint32_t f){return is_dxt(f)||f==20||f==21||f==22||f==23||f==25||f==26||f==28||f==32||f==33||f==36||f==50||f==51||(f>=111&&f<=116);}
typedef struct {uint32_t w,h,d,n,fmt,pitch;uint64_t off[96],row[16],bytes[16];} PxDDS;
static int px_dds(const uint8_t *p,uint32_t size,int cube,PxDDS *v){
    if(size<128||memcmp(p,"DDS ",4)||px_u32(p+4)!=124||px_u32(p+76)!=32)return 0;
    memset(v,0,sizeof *v);v->w=px_u32(p+16);v->h=px_u32(p+12);v->d=cube?1:px_u32(p+24);v->n=px_u32(p+28);if(!v->n)v->n=1;
    uint32_t caps=px_u32(p+112),pf=px_u32(p+80),cc=px_u32(p+84),bits=px_u32(p+88);
    if(cube?((caps&0xfe00)!=0xfe00||v->w!=v->h||(caps&0x200000)):(!(caps&0x200000)||(caps&0x200)))return 0;
    if(!v->w||!v->h||!v->d||v->w>16384||v->h>16384||v->d>2048||v->n>16)return 0;
    uint32_t max=v->w>v->h?v->w:v->h;if(v->d>max)max=v->d;unsigned levels=1;while(max>1){++levels;max>>=1;}if(v->n>levels)return 0;
    if(pf&4)v->fmt=cc;
    else if((pf&0x40)&&bits==32&&px_u32(p+92)==0xff0000&&px_u32(p+96)==0xff00&&px_u32(p+100)==0xff)v->fmt=(pf&1)?21:22;
    else if((pf&0x40)&&bits==32&&px_u32(p+92)==0xff&&px_u32(p+96)==0xff00&&px_u32(p+100)==0xff0000)v->fmt=(pf&1)?32:33;
    else if((pf&0x40)&&bits==24&&px_u32(p+92)==0xff0000&&px_u32(p+96)==0xff00&&px_u32(p+100)==0xff)v->fmt=20;
    else if((pf&0x40)&&bits==16&&px_u32(p+92)==0xf800&&px_u32(p+96)==0x7e0&&px_u32(p+100)==31)v->fmt=23;
    else if((pf&0x40)&&bits==16&&px_u32(p+92)==0x7c00&&px_u32(p+96)==0x3e0&&px_u32(p+100)==31&&px_u32(p+104)==0x8000)v->fmt=25;
    else if((pf&0x40)&&bits==16&&px_u32(p+92)==0xf00&&px_u32(p+96)==0xf0&&px_u32(p+100)==15&&px_u32(p+104)==0xf000)v->fmt=26;
    else if((pf&0x20000)&&bits==8)v->fmt=50;
    else if((pf&0x20000)&&bits==16)v->fmt=51;
    else if((pf&2)&&bits==8)v->fmt=28;
    if(!px_format(v->fmt))return 0;
    uint64_t off=128;
    for(unsigned f=0;f<(cube?6:1);++f)for(unsigned l=0;l<v->n;++l){
        uint32_t w=mipdim(v->w,l),h=mipdim(v->h,l),d=mipdim(v->d,l);
        uint64_t row=level_pitch(v->fmt,w);if(!l&&(px_u32(p+8)&8)&&!is_dxt(v->fmt)){uint32_t pitch=px_u32(p+20);if(pitch<row)return 0;row=pitch;}
        uint64_t bytes=row*level_rows(v->fmt,h)*d;if(off+bytes>size)return 0;
        v->off[f*16+l]=off;v->row[l]=row;v->bytes[l]=bytes;off+=bytes;
    }return 1;
}
static uint32_t px_create(uint32_t device,uint32_t src,uint32_t size,uint32_t output,int cube){
    if(!px_range(output,4))return PX_INVALID;M32(output)=0;
    Obj *devobj=obj(device);if(!devobj||devobj->kind!=K_DEVICE||!px_range(src,size))return PX_INVALID;
    PxDDS v;if(!px_dds(G+src,size,cube,&v))return PX_DATA;
    Obj *t=make_texture(cube?K_CUBE:K_VOLUME,cube?vt_cube:vt_volume,v.w,v.h,v.d,v.n,0,v.fmt,1);
    for(unsigned f=0;f<(cube?6:1);++f)for(unsigned l=0;l<v.n;++l){
        uint32_t rows=level_rows(v.fmt,mipdim(v.h,l)),depth=mipdim(v.d,l),pitch=t->pitch[l];
        for(unsigned z=0;z<depth;++z)for(unsigned y=0;y<rows;++y)
            memcpy(G+t->mem[f*16+l]+((uint64_t)z*rows+y)*pitch,G+src+v.off[f*16+l]+((uint64_t)z*rows+y)*v.row[l],pitch);
    }t->dirty=1;M32(output)=t->guest;return 0;
}
static float px_half(uint16_t h){_Float16 f;memcpy(&f,&h,2);return (float)f;}
static uint16_t px_to_half(float v){_Float16 h=(_Float16)v;uint16_t u;memcpy(&u,&h,2);return u;}
static uint32_t px_byte(float f){return isnan(f)||f<=0?0:f>=1?255:(uint32_t)lrintf(f*255);}
static void px_565(uint16_t v,float *c){c[0]=((v>>11)&31)/31.f;c[1]=((v>>5)&63)/63.f;c[2]=(v&31)/31.f;c[3]=1;}
static void px_pixel(uint32_t fmt,const uint8_t *p,unsigned x,unsigned y,uint32_t pitch,float *c){
    c[0]=c[1]=c[2]=0;c[3]=1;
    if(is_dxt(fmt)){
        const uint8_t *block=p+(y/4)*pitch+(x/4)*fmt_bpp(fmt),*color=block+(fmt==0x31545844?0:8);uint16_t a,b;memcpy(&a,color,2);memcpy(&b,color+2,2);float colors[4][4];px_565(a,colors[0]);px_565(b,colors[1]);
        for(int k=0;k<4;k++){colors[2][k]=a>b||fmt!=0x31545844?(2*colors[0][k]+colors[1][k])/3:(colors[0][k]+colors[1][k])/2;colors[3][k]=a>b||fmt!=0x31545844?(colors[0][k]+2*colors[1][k])/3:0;}
        unsigned i=(y%4)*4+x%4;memcpy(c,colors[(px_u32(color+4)>>(2*i))&3],16);
        if(fmt==0x32545844||fmt==0x33545844)c[3]=((block[i/2]>>(4*(i%2)))&15)/15.f;
        if(fmt==0x34545844||fmt==0x35545844){uint64_t bits=0;for(int k=0;k<6;k++)bits|=(uint64_t)block[2+k]<<(8*k);unsigned code=(bits>>(3*i))&7;float alpha[8]={block[0]/255.f,block[1]/255.f};for(int k=2;k<8;k++)alpha[k]=block[0]>block[1]?((8-k)*alpha[0]+(k-1)*alpha[1])/7:k<6?((6-k)*alpha[0]+(k-1)*alpha[1])/5:k==6?0:1;c[3]=alpha[code];}
        if(fmt==0x32545844||fmt==0x34545844){if(c[3]>0)for(int k=0;k<3;k++)c[k]/=c[3];}return;
    }
    p+=y*pitch+x*fmt_bpp(fmt);uint16_t u;memcpy(&u,p,fmt_bpp(fmt)>=2?2:1);
    if(fmt==21||fmt==22||fmt==20){c[0]=p[2]/255.f;c[1]=p[1]/255.f;c[2]=p[0]/255.f;if(fmt==21)c[3]=p[3]/255.f;}
    else if(fmt==32||fmt==33){for(int k=0;k<3;k++)c[k]=p[k]/255.f;if(fmt==32)c[3]=p[3]/255.f;}
    else if(fmt==23)px_565(u,c);
    else if(fmt==25){c[0]=((u>>10)&31)/31.f;c[1]=((u>>5)&31)/31.f;c[2]=(u&31)/31.f;c[3]=u>>15;}
    else if(fmt==26){c[0]=((u>>8)&15)/15.f;c[1]=((u>>4)&15)/15.f;c[2]=(u&15)/15.f;c[3]=(u>>12)/15.f;}
    else if(fmt==28)c[3]=p[0]/255.f;
    else if(fmt==50||fmt==51){c[0]=c[1]=c[2]=p[0]/255.f;if(fmt==51)c[3]=p[1]/255.f;}
    else if(fmt==36){for(int k=0;k<4;k++){memcpy(&u,p+2*k,2);c[k]=u/65535.f;}}
    else if(fmt>=111&&fmt<=113){unsigned count=fmt==111?1:fmt==112?2:4;for(unsigned k=0;k<count;k++){memcpy(&u,p+2*k,2);c[k]=px_half(u);}}
    else if(fmt>=114&&fmt<=116)memcpy(c,p,fmt_bpp(fmt));
}
static void px_store(uint32_t fmt,uint8_t *p,const float *c){
    uint32_t r=px_byte(c[0]),g=px_byte(c[1]),b=px_byte(c[2]),a=px_byte(c[3]);uint16_t u;
    if(fmt==21||fmt==22||fmt==20){p[0]=b;p[1]=g;p[2]=r;if(fmt!=20)p[3]=fmt==22?255:a;}
    else if(fmt==32||fmt==33){p[0]=r;p[1]=g;p[2]=b;p[3]=fmt==33?255:a;}
    else if(fmt==23||fmt==25||fmt==26){u=fmt==23?((r>>3)<<11)|((g>>2)<<5)|(b>>3):fmt==25?((a>>7)<<15)|((r>>3)<<10)|((g>>3)<<5)|(b>>3):((a>>4)<<12)|((r>>4)<<8)|((g>>4)<<4)|(b>>4);memcpy(p,&u,2);}
    else if(fmt==28)p[0]=a;
    else if(fmt==50||fmt==51){p[0]=r;if(fmt==51)p[1]=a;}
    else if(fmt==36){for(int k=0;k<4;k++){float f=c[k];u=isnan(f)||f<=0?0:f>=1?65535:(uint16_t)lrintf(f*65535);memcpy(p+2*k,&u,2);}}
    else if(fmt>=111&&fmt<=113){for(unsigned k=0;k<fmt_bpp(fmt)/2;k++){u=px_to_half(c[k]);memcpy(p+2*k,&u,2);}}
    else if(fmt>=114&&fmt<=116)memcpy(p,c,fmt_bpp(fmt));
}
static uint32_t px_fill(Cpu *c,uint32_t texture,uint32_t callback,uint32_t user){
    Obj *t=obj(texture);if(!t||t->kind!=K_VOLUME||!callback)return PX_INVALID;
    if(!px_format(t->fmt)||is_dxt(t->fmt))return PX_UNSUPPORTED;
    uint32_t tmp=gmalloc(64);if(!tmp)return 0x8007000e;
    for(unsigned l=0;l<t->levels;++l){unsigned w=mipdim(t->w,l),h=mipdim(t->h,l),d=mipdim(t->d,l),pitch=t->pitch[l];float step[]={1.f/w,1.f/h,1.f/d};memcpy(G+tmp+32,step,12);
        for(unsigned z=0;z<d;z++)for(unsigned y=0;y<h;y++)for(unsigned x=0;x<w;x++){
            float pos[]={(x+.5f)/w,(y+.5f)/h,(z+.5f)/d};memset(G+tmp,0,16);memcpy(G+tmp+16,pos,12);uint32_t args[]={tmp,tmp+16,tmp+32,user};Cpu cb=*c;call_guest(&cb,callback,4,args);float color[4];memcpy(color,G+tmp,16);px_store(t->fmt,G+t->mem[l]+((uint64_t)z*h+y)*pitch+x*fmt_bpp(t->fmt),color);
        }
    }gfree(tmp);t->dirty=1;return 0;
}
typedef struct {unsigned x,y,w,h;} PxRect;
static int px_rect(uint32_t p,Obj *s,PxRect *r){int32_t a[4]={0,0,(int32_t)s->w,(int32_t)s->h};if(p){if(!px_range(p,16))return 0;memcpy(a,G+p,16);}if(a[0]<0||a[1]<0||a[2]<=a[0]||a[3]<=a[1]||(uint32_t)a[2]>s->w||(uint32_t)a[3]>s->h)return 0;*r=(PxRect){a[0],a[1],a[2]-a[0],a[3]-a[1]};return 1;}
static uint32_t px_surface(Obj *s,uint32_t *pitch){uint32_t m=surface_mem(s,pitch);if(!m)return 0;Obj *parent=s->parent?obj(s->parent):NULL;if((s->usage&1)||(parent&&(parent->usage&1))||s->guest==dev.backbuffer)if(!private_surface_readback(s->guest,m,*pitch))return 0;return m;}
static int px_dirty(Obj *s,uint32_t memory,uint32_t pitch){Obj *p=s->parent?obj(s->parent):NULL;(p?p:s)->dirty=1;if((s->usage&1)||(p&&(p->usage&1))||s->guest==dev.backbuffer)return private_surface_upload(s->guest,memory,pitch);return 1;}
static unsigned px_index(int i,unsigned n,int mirror){if(mirror){int period=2*(int)n;i%=period;if(i<0)i+=period;return i<(int)n?(unsigned)i:(unsigned)(period-1-i);}return i<0?0:i>=(int)n?n-1:(unsigned)i;}
static void px_sample(const float *colors,unsigned sw,unsigned sh,unsigned dw,unsigned dh,unsigned x,unsigned y,unsigned mode,unsigned flags,float *c){
    if(mode<=2){unsigned xx=mode==1?x:(uint64_t)(2*x+1)*sw/(2*dw),yy=mode==1?y:(uint64_t)(2*y+1)*sh/(2*dh);memcpy(c,colors+4*((size_t)yy*sw+xx),16);return;}
    float sx=(float)sw/dw,sy=(float)sh/dh,cx=(x+.5f)*sx-.5f,cy=(y+.5f)*sy-.5f;
    float rx=mode==4?fmaxf(1,sx):1,ry=mode==4?fmaxf(1,sy):1;
    int x0=mode==5?(int)floorf(x*sx):(int)floorf(cx - rx),x1=mode==5?(int)ceilf((x+1)*sx):(int)ceilf(cx+rx);
    int y0=mode==5?(int)floorf(y*sy):(int)floorf(cy-ry),y1=mode==5?(int)ceilf((y+1)*sy):(int)ceilf(cy+ry);
    float sum=0;memset(c,0,16);
    for(int j=y0;j<y1;j++)for(int i=x0;i<x1;i++){
        float wx=mode==5?fmaxf(0,fminf(i+1,(x+1)*sx)-fmaxf(i,x*sx)):fmaxf(0,1-fabsf(i-cx)/rx);
        float wy=mode==5?fmaxf(0,fminf(j+1,(y+1)*sy)-fmaxf(j,y*sy)):fmaxf(0,1-fabsf(j-cy)/ry);float weight=wx*wy;
        unsigned xx=px_index(i,sw,flags&0x10000),yy=px_index(j,sh,flags&0x20000);for(int k=0;k<4;k++)c[k]+=colors[4*((size_t)yy*sw+xx)+k]*weight;sum+=weight;
    }if(sum)for(int k=0;k<4;k++)c[k]/=sum;
}
/* DXT1 block encoder for D3DXLoadSurfaceFromSurface into a DXT1 surface (the game composites car skins in 32-bit
 * and converts them this way). Colour endpoints are the per-channel box of the opaque texels; alpha below one half
 * is DXT1's transparent index 3 (three-colour mode), which keeps the skin's vinyl mask. */
static uint16_t px_565_of(const float *c){return (uint16_t)(((px_byte(c[0])*31+127)/255)<<11|((px_byte(c[1])*63+127)/255)<<5|(px_byte(c[2])*31+127)/255);}
static void px_dxt1_block(const float *t,uint8_t *out){
    float lo[3]={1,1,1},hi[3]={0,0,0};int holes=0,opaque=0;
    for(int i=0;i<16;i++){if(!(t[4*i+3]>=.5f)){holes=1;continue;}opaque=1;for(int k=0;k<3;k++){lo[k]=fminf(lo[k],t[4*i+k]);hi[k]=fmaxf(hi[k],t[4*i+k]);}}
    if(!opaque)lo[0]=lo[1]=lo[2]=hi[0]=hi[1]=hi[2]=0;
    uint16_t e0=px_565_of(hi),e1=px_565_of(lo);if(holes?e0>e1:e0<e1){uint16_t s=e0;e0=e1;e1=s;}
    int four=e0>e1;float pal[4][4];px_565(e0,pal[0]);px_565(e1,pal[1]);
    for(int k=0;k<3;k++){pal[2][k]=four?(2*pal[0][k]+pal[1][k])/3:(pal[0][k]+pal[1][k])/2;pal[3][k]=four?(pal[0][k]+2*pal[1][k])/3:0;}
    uint32_t bits=0;for(int i=0;i<16;i++){unsigned best=0;
        if(holes&&!(t[4*i+3]>=.5f))best=3;
        else{float bd=INFINITY;for(unsigned j=0;j<(four?4u:3u);j++){float d=0;for(int k=0;k<3;k++){float e=t[4*i+k]-pal[j][k];d+=e*e;}if(d<bd){bd=d;best=j;}}}
        bits|=best<<(2*i);}
    memcpy(out,&e0,2);memcpy(out+2,&e1,2);memcpy(out+4,&bits,4);
}
static uint32_t px_load(uint32_t dst,uint32_t dp,uint32_t dr,uint32_t src,uint32_t sp,uint32_t sr,uint32_t filter,uint32_t key){
    Obj *d=obj(dst),*s=obj(src);PxRect a,b;if(!d||!s||d->kind!=K_SURFACE||s->kind!=K_SURFACE||!px_rect(dr,d,&a)||!px_rect(sr,s,&b))return PX_INVALID;
    unsigned mode=filter==UINT32_MAX?4:filter&0xffff;if(mode<1||mode>5||(filter!=UINT32_MAX&&(filter&~0x30007u)))return PX_INVALID;
    if(!px_format(s->fmt)||!px_format(d->fmt))return PX_UNSUPPORTED;
    uint32_t ps,pd,ms=px_surface(s,&ps),md=px_surface(d,&pd);if(!ms||!md)return PX_INVALID;
    int encode=is_dxt(d->fmt)&&!is_dxt(s->fmt)&&d->fmt==0x31545844u;
    if(encode&&((a.x|a.y)&3||((a.w%4)&&a.x+a.w!=d->w)||((a.h%4)&&a.y+a.h!=d->h)))return PX_UNSUPPORTED;
    if(is_dxt(d->fmt)&&!encode){
        if(d->fmt!=s->fmt||a.w!=b.w||a.h!=b.h||key||(a.x|a.y|b.x|b.y)&3||((a.w%4)&&a.x+a.w!=d->w)||((a.h%4)&&a.y+a.h!=d->h))return PX_UNSUPPORTED;
        unsigned row=level_pitch(d->fmt,a.w),rows=level_rows(d->fmt,a.h);uint8_t *tmp=malloc((size_t)row*rows);if(!tmp)return 0x8007000e;
        for(unsigned y=0;y<rows;y++)memcpy(tmp+y*row,G+ms+(b.y/4+y)*ps+(b.x/4)*fmt_bpp(s->fmt),row);
        for(unsigned y=0;y<rows;y++)memcpy(G+md+(a.y/4+y)*pd+(a.x/4)*fmt_bpp(d->fmt),tmp+y*row,row);free(tmp);return px_dirty(d,md,pd)?0:PX_UNSUPPORTED;
    }
    if(mode==1&&(a.w!=b.w||a.h!=b.h))return PX_INVALID;
    float *colors=malloc((size_t)b.w*b.h*16);if(!colors)return 0x8007000e;
    for(unsigned y=0;y<b.h;y++)for(unsigned x=0;x<b.w;x++){float *c=colors+4*((size_t)y*b.w+x);px_pixel(s->fmt,G+ms,b.x+x,b.y+y,ps,c);if(key&&((px_byte(c[0])<<16)|(px_byte(c[1])<<8)|px_byte(c[2]))==(key&0xffffff))c[3]=0;}
    if(encode){
        float *out=malloc((size_t)a.w*a.h*16);if(!out){free(colors);return 0x8007000e;}
        for(unsigned y=0;y<a.h;y++)for(unsigned x=0;x<a.w;x++)px_sample(colors,b.w,b.h,a.w,a.h,x,y,mode,filter==UINT32_MAX?0:filter,out+4*((size_t)y*a.w+x));
        for(unsigned by=0;by<(a.h+3)/4;by++)for(unsigned bx=0;bx<(a.w+3)/4;bx++){
            float t[64];for(unsigned i=0;i<16;i++){unsigned x=bx*4+i%4,y=by*4+i/4;if(x>=a.w)x=a.w-1;if(y>=a.h)y=a.h-1;memcpy(t+4*i,out+4*((size_t)y*a.w+x),16);}
            px_dxt1_block(t,G+md+(a.y/4+by)*pd+(a.x/4+bx)*8);
        }free(out);free(colors);return px_dirty(d,md,pd)?0:PX_UNSUPPORTED;
    }
    for(unsigned y=0;y<a.h;y++)for(unsigned x=0;x<a.w;x++){
        float c[4];px_sample(colors,b.w,b.h,a.w,a.h,x,y,mode,filter==UINT32_MAX?0:filter,c);
        px_store(d->fmt,G+md+(a.y+y)*pd+(a.x+x)*fmt_bpp(d->fmt),c);
    }free(colors);return px_dirty(d,md,pd)?0:PX_UNSUPPORTED;
}
static void px_header(uint8_t *p,unsigned w,unsigned h,uint32_t fmt,unsigned pitch){
    memset(p,0,128);memcpy(p,"DDS ",4);px_put(p+4,124);px_put(p+8,is_dxt(fmt)?0x81007:0x100f);px_put(p+12,h);px_put(p+16,w);px_put(p+20,is_dxt(fmt)?pitch*level_rows(fmt,h):pitch);px_put(p+76,32);px_put(p+108,0x1000);
    if(fmt==21||fmt==22){px_put(p+80,fmt==21?0x41:0x40);px_put(p+88,32);px_put(p+92,0xff0000);px_put(p+96,0xff00);px_put(p+100,0xff);px_put(p+104,fmt==21?0xff000000:0);}
    else{px_put(p+80,4);px_put(p+84,fmt);}
}
static uint32_t px_serialize(uint32_t surface,uint32_t palette,uint32_t rect,unsigned format,uint8_t **bytes,size_t *size){
    Obj *s=obj(surface);PxRect r;if(!s||s->kind!=K_SURFACE||!px_rect(rect,s,&r))return PX_INVALID;if(!px_format(s->fmt))return PX_UNSUPPORTED;
    uint32_t pitch,m=px_surface(s,&pitch);if(!m)return PX_INVALID;
    if(format==4){if(is_dxt(s->fmt)&&((r.x|r.y)&3||((r.w%4)&&r.x+r.w!=s->w)||((r.h%4)&&r.y+r.h!=s->h)))return PX_INVALID;
        uint32_t row=level_pitch(s->fmt,r.w),rows=level_rows(s->fmt,r.h);*size=128+(size_t)row*rows;*bytes=malloc(*size);if(!*bytes)return 0x8007000e;px_header(*bytes,r.w,r.h,s->fmt,row);
        for(unsigned y=0;y<rows;y++)memcpy(*bytes+128+y*row,G+m+((is_dxt(s->fmt)?r.y/4:r.y)+y)*pitch+(is_dxt(s->fmt)?r.x/4:r.x)*fmt_bpp(s->fmt),row);return 0;}
    if(format!=0&&format!=1&&format!=2&&format!=3&&format!=5&&format!=6)return PX_UNSUPPORTED;
    size_t n=(size_t)r.w*r.h*4;uint8_t *rgba=malloc(n);if(!rgba)return 0x8007000e;
    for(unsigned y=0;y<r.h;y++)for(unsigned x=0;x<r.w;x++){float c[4];px_pixel(s->fmt,G+m,r.x+x,r.y+y,pitch,c);for(unsigned k=0;k<4;k++)rgba[4*((size_t)y*r.w+x)+k]=px_byte(c[k]);}
    if(format==2){*size=18+n;*bytes=calloc(1,*size);if(*bytes){(*bytes)[2]=2;(*bytes)[12]=r.w;(*bytes)[13]=r.w>>8;(*bytes)[14]=r.h;(*bytes)[15]=r.h>>8;(*bytes)[16]=32;(*bytes)[17]=0x28;for(size_t i=0;i<n;i+=4){(*bytes)[18+i]=rgba[i+2];(*bytes)[19+i]=rgba[i+1];(*bytes)[20+i]=rgba[i];(*bytes)[21+i]=rgba[i+3];}}}
    else if(format==5){char head[80];int h=snprintf(head,sizeof head,"P6\n%u %u\n255\n",r.w,r.h);*size=h+(size_t)r.w*r.h*3;*bytes=malloc(*size);if(*bytes){memcpy(*bytes,head,h);for(size_t i=0,j=h;i<n;i+=4,j+=3)memcpy(*bytes+j,rgba+i,3);}}
    else{CGColorSpaceRef cs=CGColorSpaceCreateDeviceRGB();CGDataProviderRef provider=CGDataProviderCreateWithData(NULL,rgba,n,NULL);CGImageRef image=CGImageCreate(r.w,r.h,8,32,r.w*4,cs,kCGImageAlphaLast|kCGBitmapByteOrderDefault,provider,NULL,false,kCGRenderingIntentDefault);
        CFMutableDataRef data=CFDataCreateMutable(NULL,0);CFStringRef uti=format==3?CFSTR("public.png"):format==1?CFSTR("public.jpeg"):CFSTR("com.microsoft.bmp");CGImageDestinationRef dest=image?CGImageDestinationCreateWithData(data,uti,1,NULL):NULL;int ok=dest!=NULL;if(dest){CGImageDestinationAddImage(dest,image,NULL);ok=CGImageDestinationFinalize(dest);CFRelease(dest);}if(ok){size_t skip=format==6?14:0;*size=(size_t)CFDataGetLength(data);if(*size<skip)ok=0;else{*size-=skip;*bytes=malloc(*size);if(*bytes)memcpy(*bytes,CFDataGetBytePtr(data)+skip,*size);}}if(image)CGImageRelease(image);CGDataProviderRelease(provider);CGColorSpaceRelease(cs);CFRelease(data);if(!ok){free(rgba);return PX_UNSUPPORTED;}}
    free(rgba);return *bytes?0:0x8007000e;
}
/* ID3DXBuffer, its storage is guest-addressable and reference counted. */
static int px_buf_add(Cpu*c){uint32_t p=arg(c,0);RET(++M32(p+4),1);}
static int px_buf_release(Cpu*c){uint32_t p=arg(c,0),refs=--M32(p+4);if(!refs){gfree(M32(p+8));gfree(p);}RET(refs,1);}
static int px_buf_query(Cpu*c){uint32_t self=arg(c,0),iid=arg(c,1),out=arg(c,2);if(!out)RET(0x80004003u,3);M32(out)=0;const uint8_t unknown[16]={0,0,0,0,0,0,0,0,0xc0,0,0,0,0,0,0,0x46};const uint8_t buffer[16]={8,0xfb,0xa5,0x8b,0x95,0x51,0xe2,0x40,0xac,0x58,0x0d,0x98,0x9c,0x3a,1,2};if(!iid||(memcmp(G+iid,unknown,16)&&memcmp(G+iid,buffer,16)))RET(E_NOINTERFACE,3);M32(out)=self;++M32(self+4);RET(0,3);}
static int px_buf_pointer(Cpu*c){RET(M32(arg(c,0)+8),1);}
static int px_buf_size(Cpu*c){RET(M32(arg(c,0)+12),1);}
static uint32_t px_buffer(const uint8_t *bytes,size_t size){static uint32_t vt;if(size>UINT32_MAX)return 0;if(!vt){vt=galloc(20);HostFn fn[]={px_buf_query,px_buf_add,px_buf_release,px_buf_pointer,px_buf_size};const char *names[]={"QueryInterface","AddRef","Release","GetBufferPointer","GetBufferSize"};for(unsigned i=0;i<5;i++)M32(vt+4*i)=host_fn(fn[i],names[i]);}uint32_t p=gmalloc(16),data=gmalloc((uint32_t)size);if(!p||!data){gfree(p);gfree(data);return 0;}M32(p)=vt;M32(p+4)=1;M32(p+8)=data;M32(p+12)=size;memcpy(G+data,bytes,size);return p;}
static uint32_t px_save_file(const char *guest,uint32_t surface,uint32_t palette,uint32_t rect,unsigned format){
    const uint32_t denied=0x80070005u;
    const char *scratch=getenv("NFS_GAME_SCRATCH");if(!scratch||!*scratch)scratch=getenv("BOOT_USERDATA");if(!scratch||!*scratch)return denied;
    char root[4096],path[4096],rel[4096];if(!realpath(scratch,root))return denied;
    if(guest[0]=='/')snprintf(path,sizeof path,"%s",guest);else if(strchr(guest,':')||!strncasecmp(guest,"USERDATA",8))private_resolve(guest,path,sizeof path);else{snprintf(rel,sizeof rel,"%s",guest);for(char*p=rel;*p;p++)if(*p=='\\')*p='/';snprintf(path,sizeof path,"%s/%s",root,rel);}
    size_t n=strlen(root);if(strncmp(path,root,n)||path[n]!='/'||strlen(path+n+1)>=sizeof rel)return denied;strcpy(rel,path+n+1);
    int dir=open(root,O_RDONLY|O_DIRECTORY|O_NOFOLLOW);if(dir<0)return denied;
    char *state=NULL,*part=strtok_r(rel,"/",&state);
    uint32_t hr=denied;
    while(part){
        if(!strcmp(part,".")||!strcmp(part,".."))break;
        char *next=strtok_r(NULL,"/",&state);
        if(next){
            int sub=openat(dir,part,O_RDONLY|O_DIRECTORY|O_NOFOLLOW);
            close(dir);
            if(sub<0)return denied;
            dir=sub;
            part=next;
            continue;
        }
        // Reserve a fresh inode before synchronous readback. It also protects
        // any existing hard link until the complete image can replace it.
        char temp[80];
        int fd=-1;
        for(int k=0;k<10&&fd<0;k++){
            snprintf(temp,sizeof temp,".d3dx-save-%08x-%08x",arc4random(),arc4random());
            fd=openat(dir,temp,O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW,0600);
            if(fd<0&&errno!=EEXIST)break;
        }
        if(fd<0)break;

        uint8_t *bytes=NULL;
        size_t size=0;
        hr=px_serialize(surface,palette,rect,format,&bytes,&size);
        for(size_t offset=0;!hr&&offset<size;){
            ssize_t w=write(fd,bytes+offset,size-offset);
            if(w<0&&errno==EINTR)continue;
            if(w<=0){hr=denied;break;}
            offset+=(size_t)w;
        }
        free(bytes);
        if(close(fd)&&!hr)hr=denied;
        if(!hr&&renameat(dir,temp,dir,part))hr=denied;
        if(hr)unlinkat(dir,temp,0);
        break;
    }
    close(dir);
    return hr;
}
int private_d3dx_textures(Cpu *c,const char *fn){
    if(!strcmp(fn,"D3DXCreateVolumeTextureFromFileInMemory"))RET(px_create(arg(c,0),arg(c,1),arg(c,2),arg(c,3),0),4);
    if(!strcmp(fn,"D3DXCreateCubeTextureFromFileInMemory"))RET(px_create(arg(c,0),arg(c,1),arg(c,2),arg(c,3),1),4);
    if(!strcmp(fn,"D3DXFillVolumeTexture"))RET(px_fill(c,arg(c,0),arg(c,1),arg(c,2)),3);
    if(!strcmp(fn,"D3DXLoadSurfaceFromSurface"))RET(px_load(arg(c,0),arg(c,1),arg(c,2),arg(c,3),arg(c,4),arg(c,5),arg(c,6),arg(c,7)),8);
    if(!strcmp(fn,"D3DXSaveSurfaceToFileInMemory")||!strcmp(fn,"D3DXSaveSurfaceToFileA")){
        int memory=!strcmp(fn,"D3DXSaveSurfaceToFileInMemory");uint32_t output=arg(c,0);if(!output||!px_range(output,memory?4:1))RET(PX_INVALID,5);
        if(!memory)RET(px_save_file((const char*)G+output,arg(c,2),arg(c,3),arg(c,4),arg(c,1)),5);
        M32(output)=0;
        uint8_t *bytes=NULL;size_t size=0;uint32_t hr=px_serialize(arg(c,2),arg(c,3),arg(c,4),arg(c,1),&bytes,&size);
        if(!hr){M32(output)=px_buffer(bytes,size);if(!M32(output))hr=0x8007000e;}free(bytes);RET(hr,5);
    }return 0;
}
