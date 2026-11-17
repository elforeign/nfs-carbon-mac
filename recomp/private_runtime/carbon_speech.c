/* Optional console police, crew and UCAP recordings. File imports are the
 * only hook; compressed MicroTalk payloads and indexed extents stay intact. */
#include <stdint.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <strings.h>
#include <dirent.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <pthread.h>
#include "x360audio.h"
extern const char *game_dir;
#include "roots.h"
extern int diag_on;
extern void diag_event(const char *, ...);

enum { CS_BIG, CS_CSI, CS_EVT, CS_IDX, CS_FILES };
typedef struct {
    const char *name;
    unsigned count,evt_limit,banks,streams,stereo,six;
    size_t sizes[CS_FILES];
} CSSpec;
static const CSSpec cs_specs[]={
    {"COPSPEECH",268,0x3440,716,14063,131,0,{433741824,6564,25257,89376}},
    {"UCAPAUDIO",6,0x128,6,72,0,8,{4261888,180,555,528}}
};
static const char *const cs_ext[]={"BIG","CSI","EVT","IDX"};
static uint32_t cs_u32(const uint8_t *p,int be) {
    return be?(uint32_t)p[0]<<24|(uint32_t)p[1]<<16|(uint32_t)p[2]<<8|p[3]
             :(uint32_t)p[3]<<24|(uint32_t)p[2]<<16|(uint32_t)p[1]<<8|p[0];
}
static unsigned cs_u16(const uint8_t *p,int be) { return be?p[0]*256u+p[1]:p[1]*256u+p[0]; }
static void cs_put(uint8_t *p,uint32_t v) {for(unsigned i=0;i<4;i++)p[i]=(uint8_t)(v>>(8*i));}
static void cs_swap(const uint8_t *s,uint8_t *d,size_t at,unsigned n) {
    for(unsigned i=0;i<n;i++)d[at+i]=s[at+n-i-1];
}
/* Exact relative components, as in the music/GIN source selection. */
static int cs_find(const char *root,const char *rel,char *out,size_t n) {
    if(!root || snprintf(out,n,"%s",root)>=(int)n)return 0;
    while(*rel) {
        const char *end=strchr(rel,'/');size_t len=end?(size_t)(end-rel):strlen(rel);
        if(!len || (len==1 && *rel=='.') || (len==2 && !strncmp(rel,"..",2)))return 0;
        DIR *dir=opendir(out);if(!dir)return 0;
        struct dirent *e;char component[256]={0};
        while((e=readdir(dir)))if(strlen(e->d_name)==len && !strncasecmp(e->d_name,rel,len)) {
            snprintf(component,sizeof component,"%s",e->d_name);break;
        }
        closedir(dir);size_t used=strlen(out);
        if(!component[0] || snprintf(out+used,n-used,"/%s",component)>=(int)(n-used))return 0;
        rel=end?end+1:rel+len;
    }
    return 1;
}
static uint8_t *cs_map(const char *path,size_t expected) {
    int fd=open(path,O_RDONLY|O_NONBLOCK|O_CLOEXEC);struct stat st;void *data=MAP_FAILED;
    if(fd>=0 && !fstat(fd,&st) && S_ISREG(st.st_mode) && st.st_size==(off_t)expected)
        data=mmap(NULL,expected,PROT_READ,MAP_PRIVATE,fd,0);
    if(fd>=0)close(fd);
    return data==MAP_FAILED?NULL:data;
}
/* CSI v3: same 12-byte symbol rows as v2. Carbon's IDX bank header is
 * 16 bytes: id:u16, attrs:u8, samples:u8, mask:u32, flags:u8, sector:u8,
 * end:u16, reserved:u32; followed by BE offsets/byte selectors and attributes.
 * EVT +8 is a byte field here; only +12/+14 are build/checksum differences. */
static int cs_sidecar(unsigned kind, const CSSpec *p, const uint8_t *s, size_t n, uint8_t *d) {
    if (!s || !d || s==d || kind<CS_CSI || kind>CS_IDX || n!=p->sizes[kind]) return 0;
    memcpy(d,s,n);
#define SW(o,w) do { size_t at_=(o); if (at_>n || (w)>n-at_) return 0; cs_swap(s,d,at_,w); } while (0)
    if (kind==CS_CSI) {
        if (memcmp(s,"MOIR\0\3\0\0",8) || s[8]!=5 || cs_u16(s+10,1)!=p->count) return 0;
        d[8]=0; // Csis platform: X360 -> PC, not a speech-content change.
        for (size_t off=10;off<40;off+=2) SW(off,2);
        for (unsigned i=0;i<p->count;i++) {
            size_t off=40+i*12;
            SW(off,4); SW(off+4,4); SW(off+8,2); SW(off+10,2);
            unsigned name=cs_u32(s+off+4,1);
            if (name<40+p->count*12 || name>=n || !memchr(s+name,0,n-name)) return 0;
        }
    } else if (kind==CS_EVT) {
        if (memcmp(s,"\3\24\74\7",4) || cs_u32(s+4,1)!=p->evt_limit || cs_u16(s+16,1)!=p->count) return 0;
        SW(4,4);
        for (size_t off=12;off<24;off+=2) SW(off,2);
        for (unsigned i=0;i<p->count;i++) {
            size_t index=24+i*2, e=cs_u16(s+index,1)*4u;
            SW(index,2);
            if (e<((24+p->count*2+3)&~3u) || e+12>p->evt_limit) return 0;
            SW(e,2); SW(e+2,2); SW(e+4,2);
            if (e+12+s[e+6]*2u>p->evt_limit) return 0;
            for (unsigned j=0;j<s[e+6];j++) {
                size_t at=e+12+j*2, sub=e+cs_u16(s+at,1)*4u;
                SW(at,2);
                if (sub<e+12 || sub+8>p->evt_limit) return 0;
                unsigned parts=s[sub+2]>>2, attrs=s[e+8]>>4;
                if (sub+8+((parts+3)&~3u)+attrs*4>p->evt_limit) return 0;
                for (unsigned k=0;k<attrs;k++) SW(sub+8+((parts+3)&~3u)+k*4,4);
                for (unsigned k=0;k<parts;k++) {
                    size_t bank=sub+s[sub+8+k]*4u;
                    if (bank<sub+8 || bank+8>p->evt_limit || bank+8+s[bank+4]*8u>p->evt_limit) return 0;
                    SW(bank,2); SW(bank+6,2);
                    for (unsigned a=0;a<s[bank+4];a++) SW(bank+8+a*8,4);
                }
            }
        }
        for (unsigned i=0;i<p->count;i++) {
            size_t at=p->evt_limit+i*32;
            SW(at,4); SW(at+4,2); SW(at+6,2);
        }
        // Keep the X360 build checksum at +14. The PC loader never compares it.
    } else {
        if (cs_u32(s,1)!=1 || cs_u32(s+4,1)!=p->banks || cs_u32(s+0x54,1)!=p->banks) return 0;
        for (size_t off=0;off<0x58+p->banks*16;off+=4) SW(off,4);
        for (unsigned i=0;i<p->banks;i++) {
            size_t t=0x58+i*16, bank=cs_u32(s+t+8,1), len=cs_u32(s+t+4,1);
            if (bank<0x58+p->banks*16 || bank>n || len>n-bank || len<16) return 0;
            SW(bank,2); SW(bank+4,4); SW(bank+10,2); SW(bank+12,4);
            unsigned attrs=s[bank+2]&127, samples=s[bank+3];
            size_t tail=((attrs+2)*samples+19)&~3u;
            if (tail+attrs*4>len) return 0;
            for (unsigned j=0;j<attrs;j++) SW(bank+tail+j*4,4);
            // The 2-byte sample offsets are explicitly BE on BOTH platforms
            // (the native bank reader), followed by byte selectors. Never word-swap them.
        }
    }
#undef SW
    return 1;
}

typedef struct { size_t at; uint32_t value; } CSWord;
typedef struct { size_t begin,end; unsigned bank,sample,channels; } CSStream;
typedef struct {
    const CSSpec *spec;
    const uint8_t *big;
    uint8_t *side[CS_FILES];
    CSWord *words;
    size_t word_count,word_capacity;
    CSStream *streams;
    uint8_t *seen;
} CSBank;
static CSBank cs_banks[2];
static pthread_once_t cs_once=PTHREAD_ONCE_INIT;
static pthread_mutex_t cs_log_lock=PTHREAD_MUTEX_INITIALIZER;
static int cs_ready;
static uint8_t *cs_memory;
static size_t cs_memory_size;

static int cs_patch(CSBank *b,size_t at,uint32_t value) {
    if(b->word_count==b->word_capacity) {
        size_t cap=b->word_capacity?b->word_capacity*2:4096;
        if(cap>b->spec->sizes[CS_BIG]/4)return 0;
        CSWord *words=realloc(b->words,cap*sizeof *words);
        if(!words)return 0;
        b->words=words;b->word_capacity=cap;
    }
    b->words[b->word_count++]=(CSWord){at,value};return 1;
}
/* Normalize only platform/revision; keep all other authored PT attributes. */
static int cs_header(uint8_t *p,size_t n,unsigned *channels,unsigned *samples) {
    if(n<32 || memcmp(p,"SCHl",4) || memcmp(p+8,"PT\11\0",4))return 0;
    unsigned size=cs_u32(p+4,0),format=0,rate=0,codec=0,revision=0,ended=0;
    if((size!=32 && size!=36 && size!=40) || size>n)return 0;
    *channels=1;*samples=0;
    for(unsigned at=12;at<size;) {
        unsigned tag=p[at++];
        if(tag==255){ended=1;break;}if(tag>=252)continue;
        if(at>=size)return 0;
        unsigned width=p[at++],v=0;
        if(!width || width>4 || width>size-at)return 0;
        for(unsigned i=0;i<width;i++)v=v<<8|p[at+i];
        switch(tag) {
            case 5: if(v!=80 && v!=100)return 0;break;
            case 6: format=v;break;
            case 0x82: *channels=v;break;
            case 0x84: rate=v;break;
            case 0x85: *samples=v;break;
            case 0xa0: codec=v;break;
            case 0x8c:
                if(width!=1 || v!=4)return 0;
                p[at-2]=0x80;p[at]=2;revision=1;break;
            default: return 0;
        }
        at+=width;
    }
    if(!ended || !revision || format!=101 || codec!=22 || rate!=36000 || !*samples ||
        *samples>=0x1000000 || (*channels!=1 && *channels!=2 && *channels!=6))return 0;
    p[10]=0;return 1;
}
/* Full forward-only packet chain, bounded by this indexed stream's extent.
 * Six-channel UCAP uses six independent MicroTalk payloads, verified as PCM
 * by the offline native decoder. No downmix or compressed payload changes. */
static int cs_stream(CSBank *b,CSStream *s,uint8_t *p,size_t n) {
    unsigned channels,samples;
    if(!cs_header(p,n,&channels,&samples))return 0;
    unsigned header=cs_u32(p+4,0),blocks=0,total=0;
    size_t at=header;
    if(n-at<12 || memcmp(p+at,"SCCl",4) || cs_u32(p+at+4,0)!=12)return 0;
    unsigned declared=cs_u32(p+at+8,1);cs_put(p+at+8,declared);at+=12;
    while(n-at>=8) {
        unsigned size=cs_u32(p+at+4,0);
        if(size<8 || size>n-at)return 0;
        if(!memcmp(p+at,"SCEl",4)) {
            if(size!=8 || !blocks || blocks!=declared || total!=samples)return 0;
            s->channels=channels;
            /* Only differing 4-byte words are retained, never encoded audio. */
            for(size_t i=0;i<at+8;i+=4) {
                uint32_t v=cs_u32(p+i,0);
                if(v!=cs_u32(b->big+s->begin+i,0) && !cs_patch(b,s->begin+i,v))return 0;
            }
            return 1;
        }
        unsigned payload=12+channels*4;
        if(memcmp(p+at,"SCDl",4) || size<payload+2*channels || size>65536 || (size&3))return 0;
        unsigned count=cs_u32(p+at+8,1);
        if(!count || count>16384 || count>samples-total)return 0;
        for(unsigned ch=0;ch<channels;ch++) {
            unsigned off=cs_u32(p+at+12+4*ch,1);
            unsigned end=ch+1<channels?cs_u32(p+at+16+4*ch,1):size-payload;
            if((!ch && off) || end<=off+1 || end>size-payload || p[at+payload+off]!=(blocks==0))return 0;
        }
        cs_put(p+at+8,count);
        for(unsigned ch=0;ch<channels;ch++)cs_put(p+at+12+4*ch,cs_u32(p+at+12+4*ch,1));
        total+=count;blocks++;at+=size;
    }
    return 0;
}
static int cs_extent(const uint8_t *idx,size_t n,unsigned bank,unsigned sample,
                     size_t limit,size_t *start,size_t *end) {
    size_t t=0x58+16*bank;
    if(t>n || n-t<16)return 0;
    size_t b=cs_u32(idx+t+8,0),base=cs_u32(idx+t+12,0);
    if(b>n || n-b<16)return 0;
    unsigned count=idx[b+3],stride=(idx[b+2]&127)+2,unit=(idx[b+9]+1)*256;
    if(sample>=count || 16+count*stride>n-b)return 0;
    *start=base+(size_t)cs_u16(idx+b+16+sample*stride,1)*unit;
    *end=base+(size_t)(sample+1<count?cs_u16(idx+b+16+(sample+1)*stride,1):cs_u16(idx+b+10,0))*unit;
    return *start<*end && *end<=limit;
}
/* Match PC selectors/identities before admitting the complete pair. The only
 * IDX differences allowed are audio offsets, sector size and the end sector. */
static int cs_match_index(const uint8_t *x,const uint8_t *pc,const CSSpec *p) {
    size_t n=p->sizes[CS_IDX];uint8_t *compare=malloc(n);if(!compare)return 0;
    memcpy(compare,x,n);
    for(unsigned i=0;i<p->banks;i++) {
        size_t t=0x58+16*i,b=cs_u32(x+t+8,0);
        if(b>n || n-b<16 || cs_u32(pc+t+8,0)!=b) {free(compare);return 0;}
        unsigned stride=(x[b+2]&127)+2,count=x[b+3];
        if(16+stride*count>n-b){free(compare);return 0;}
        memcpy(compare+t+12,pc+t+12,4);memcpy(compare+b+9,pc+b+9,3);
        for(unsigned j=0;j<count;j++)memcpy(compare+b+16+j*stride,pc+b+16+j*stride,2);
    }
    int same=!memcmp(compare,pc,n);free(compare);return same;
}
static int cs_build(CSBank *b) {
    const CSSpec *p=b->spec;const uint8_t *idx=b->side[CS_IDX];size_t maximum=0,previous=0;
    unsigned count=0,stereo=0,six=0;
    b->streams=calloc(p->streams,sizeof *b->streams);b->seen=calloc(p->streams,1);
    if(!b->streams || !b->seen)return 0;
    for(unsigned i=0;i<p->banks;i++) {
        size_t bank=cs_u32(idx+0x58+16*i+8,0);
        for(unsigned j=0;j<idx[bank+3];j++) {
            size_t start,end;
            if(count>=p->streams || !cs_extent(idx,p->sizes[CS_IDX],i,j,p->sizes[CS_BIG],&start,&end) ||
                start<previous || (!count && start))return 0;
            CSStream *s=b->streams+count++;*s=(CSStream){.begin=start,.end=end,.bank=i,.sample=j};
            if(end-start>maximum)maximum=end-start;previous=end;
        }
    }
    if(count!=p->streams || maximum>0x400000)return 0;
    uint8_t *buffer=malloc(maximum);if(!buffer)return 0;
    for(unsigned i=0;i<count;i++) {
        CSStream *s=b->streams+i;size_t n=s->end-s->begin;
        memcpy(buffer,b->big+s->begin,n);
        if(!cs_stream(b,s,buffer,n)){free(buffer);return 0;}
        stereo+=s->channels==2;six+=s->channels==6;
    }
    free(buffer);
    return stereo==p->stereo && six==p->six;
}
static size_t cs_read_at(void *source,void *dst,size_t n,size_t pos) {
    CSBank *b=source;
    if(pos>=b->spec->sizes[CS_BIG])return 0;
    if(n>b->spec->sizes[CS_BIG]-pos)n=b->spec->sizes[CS_BIG]-pos;
    memcpy(dst,b->big+pos,n);
    size_t lo=0,hi=b->word_count;
    while(lo<hi){size_t mid=(lo+hi)/2;if(b->words[mid].at+4<=pos)lo=mid+1;else hi=mid;}
    for(size_t i=lo;i<b->word_count && b->words[i].at<pos+n;i++) {
        CSWord w=b->words[i];
        for(unsigned j=0;j<4;j++)if(w.at+j>=pos && w.at+j<pos+n)
            ((uint8_t *)dst)[w.at+j-pos]=(uint8_t)(w.value>>(8*j));
    }
    if(diag_on && n) {
        lo=0;hi=b->spec->streams;
        while(lo<hi){size_t mid=(lo+hi)/2;if(b->streams[mid].begin<pos)lo=mid+1;else hi=mid;}
        pthread_mutex_lock(&cs_log_lock);
        for(size_t i=lo;i<b->spec->streams && b->streams[i].begin<pos+n;i++)if(!b->seen[i]) {
            b->seen[i]=1;CSStream *s=b->streams+i;
            diag_event("carbon_speech: stream served %s bank=%u sample=%u source=X360 rate=36000 channels=%u bytes=%zu",
                b->spec->name,s->bank,s->sample,s->channels,n);
        }
        pthread_mutex_unlock(&cs_log_lock);
    }
    return n;
}
/* The native filesystem serves small sidecars from this PC cache before it
 * tries loose files. Its 20-byte directory rows use the uppercase path hash,
 * byte offset, stored size, plain size and an opaque native field. Retain the
 * directory and every other cached file byte-for-byte; replace only the six
 * authenticated, same-size speech sidecars. Otherwise BIG and IDX disagree. */
static int cs_memory_load(void) {
    char path[4096];struct stat st;
    if(!cs_find(game_dir,"GLOBAL/InGameMemoryFile.bin",path,sizeof path) || stat(path,&st) ||
        st.st_size<16 || st.st_size>0x400000)return 0;
    cs_memory_size=(size_t)st.st_size;
    uint8_t *raw=cs_map(path,cs_memory_size);if(!raw)return 0;
    cs_memory=malloc(cs_memory_size);
    if(cs_memory)memcpy(cs_memory,raw,cs_memory_size);
    munmap(raw,cs_memory_size);if(!cs_memory)return 0;
    unsigned count=cs_u32(cs_memory+12,0);
    if(cs_u32(cs_memory+8,0)!=0x53219999 || !count || count>(cs_memory_size-16)/20)return 0;
    size_t previous=16+20*count;
    for(unsigned i=0;i<count;i++) {
        const uint8_t *row=cs_memory+16+20*i;
        size_t off=cs_u32(row+4,0),n=cs_u32(row+8,0);
        if(off<previous || off>cs_memory_size || n>cs_memory_size-off)return 0;
        previous=off+n;
    }
    return 1;
}
static int cs_memory_patch(const char *name,const uint8_t *pc,const uint8_t *normalized,size_t n) {
    uint32_t hash=UINT32_MAX;
    for(const char *p=name;*p;p++)hash=hash*33+(uint8_t)(*p=='/'?'\\':*p);
    unsigned found=0,count=cs_u32(cs_memory+12,0);
    for(unsigned i=0;i<count;i++) {
        const uint8_t *row=cs_memory+16+20*i;
        if(cs_u32(row,0)!=hash)continue;
        size_t off=cs_u32(row+4,0);
        if(++found!=1 || cs_u32(row+8,0)!=n || cs_u32(row+12,0)!=n || memcmp(cs_memory+off,pc,n))return 0;
        memcpy(cs_memory+off,normalized,n);
    }
    return found==1;
}
static void cs_init(void) {
    char rel[96],path[4096];
    if(!cs_memory_load())goto fail;
    for(unsigned k=0;k<2;k++) {
        CSBank *b=cs_banks+k;const CSSpec *p=cs_specs+k;b->spec=p;
        for(unsigned kind=CS_CSI;kind<CS_FILES;kind++) {
            snprintf(rel,sizeof rel,"SOUND/SPEECH/%s.%s",p->name,cs_ext[kind]);
            if(!cs_find(roots_x360_files(),rel,path,sizeof path))goto fail;
            uint8_t *x=cs_map(path,p->sizes[kind]);if(!x)goto fail;
            b->side[kind]=malloc(p->sizes[kind]);
            int ok=b->side[kind] && cs_sidecar(kind,p,x,p->sizes[kind],b->side[kind]);
            munmap(x,p->sizes[kind]);if(!ok)goto fail;
            if(!cs_find(game_dir,rel,path,sizeof path))goto fail;
            uint8_t *pc=cs_map(path,p->sizes[kind]);if(!pc)goto fail;
            if(kind==CS_CSI)ok=!memcmp(b->side[kind],pc,p->sizes[kind]);
            else if(kind==CS_EVT)ok=!memcmp(b->side[kind],pc,12) &&
                !memcmp(b->side[kind]+16,pc+16,p->sizes[kind]-16);
            else ok=cs_match_index(b->side[kind],pc,p);
            if(ok)ok=cs_memory_patch(rel,pc,b->side[kind],p->sizes[kind]);
            munmap(pc,p->sizes[kind]);if(!ok)goto fail;
        }
        snprintf(rel,sizeof rel,"SOUND/SPEECH/%s.BIG",p->name);
        if(!cs_find(roots_x360_files(),rel,path,sizeof path) || !(b->big=cs_map(path,p->sizes[CS_BIG])) || !cs_build(b))goto fail;
    }
    cs_ready=1;
    if(diag_on)diag_event("carbon_speech: ready 14063 police/crew + 72 UCAP, CSI v3, 722 IDX banks, rate=36000, 8 native six-channel streams, 6 cached sidecars normalized");
    return;
fail:
    free(cs_memory);cs_memory=NULL;cs_memory_size=0;
    for(unsigned k=0;k<2;k++) {
        CSBank *b=cs_banks+k;
        if(b->big)munmap((void *)b->big,cs_specs[k].sizes[CS_BIG]);
        for(unsigned kind=CS_CSI;kind<CS_FILES;kind++)free(b->side[kind]);
        free(b->words);free(b->streams);free(b->seen);memset(b,0,sizeof *b);
    }
    if(diag_on)diag_event("carbon_speech: incomplete or invalid source; all PC speech kept");
}
int carbon_speech_open(const char *host,X360MusicHandle *out) {
    const char *v=getenv("NFS_CARBON_X360_SPEECH");
    if(!v || (strcmp(v,"1") && strcmp(v,"on") && strcmp(v,"x360")) || !game_dir)return 0;
    size_t root=strlen(game_dir);while(root && game_dir[root-1]=='/')--root;
    if(strncmp(host,game_dir,root) || host[root]!='/')return 0;
    const char *rel=host+root;while(*rel=='/')++rel;
    if(!strcasecmp(rel,"GLOBAL/InGameMemoryFile.bin")) {
        pthread_once(&cs_once,cs_init);if(!cs_ready)return 0;
        *out=(X360MusicHandle){.data=cs_memory,.size=cs_memory_size};
        if(diag_on)diag_event("carbon_speech: serve GLOBAL/InGameMemoryFile.bin cached_sidecars=6 source=X360 rate=36000");
        return 1;
    }
    for(unsigned k=0;k<2;k++)for(unsigned kind=0;kind<CS_FILES;kind++) {
        char name[96];snprintf(name,sizeof name,"SOUND/SPEECH/%s.%s",cs_specs[k].name,cs_ext[kind]);
        if(strcasecmp(rel,name))continue;
        pthread_once(&cs_once,cs_init);if(!cs_ready)return 0;
        CSBank *b=cs_banks+k;
        *out=(X360MusicHandle){.data=b->side[kind],.size=b->spec->sizes[kind],
            .read_at=kind==CS_BIG?cs_read_at:NULL,.source=kind==CS_BIG?b:NULL};
        if(diag_on)diag_event("carbon_speech: serve %s source=X360 rate=36000 streams=%u",name,b->spec->streams);
        return 1;
    }
    return 0;
}
