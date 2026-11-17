/* Optional console recordings under the unchanged PC v5.2 score graphs.
 * No guest addresses: file imports are the only integration point. */
#include <stdint.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <strings.h>
#include <errno.h>
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

static uint32_t cm_word(const uint8_t *p, int be) {
    return be ? (uint32_t)p[0]<<24 | (uint32_t)p[1]<<16 | (uint32_t)p[2]<<8 | p[3]
              : (uint32_t)p[3]<<24 | (uint32_t)p[2]<<16 | (uint32_t)p[1]<<8 | p[0];
}
static void cm_put(uint8_t *p, uint32_t v) {
    for (unsigned i=0;i<4;i++) p[i]=(uint8_t)(v>>(8*i));
}
static int cm_on(const char *name) {
    const char *v=getenv(name);
    return v && (!strcmp(v,"1") || !strcmp(v,"on") || !strcmp(v,"x360"));
}
/* Case-insensitive components, never a basename search or a path outside root. */
static int cm_find(const char *root,const char *rel,char *out,size_t n) {
    if (!root || snprintf(out,n,"%s",root)>=(int)n) return 0;
    while (*rel) {
        const char *end=strchr(rel,'/'); size_t len=end?(size_t)(end-rel):strlen(rel);
        if (!len || (len==1 && *rel=='.') || (len==2 && !strncmp(rel,"..",2))) return 0;
        DIR *d=opendir(out); if (!d) return 0;
        struct dirent *e; char component[256]={0};
        while ((e=readdir(d))) if (strlen(e->d_name)==len && !strncasecmp(e->d_name,rel,len)) {
            snprintf(component,sizeof component,"%s",e->d_name); break;
        }
        closedir(d);
        size_t used=strlen(out);
        if (!component[0] || snprintf(out+used,n-used,"/%s",component)>=(int)(n-used)) return 0;
        rel=end?end+1:rel+len;
    }
    return 1;
}
/* host was already normalized by resolve(); exact game-root paths only. */
static const char *cm_relative(const char *host) {
    if (!game_dir) return NULL;
    size_t n=strlen(game_dir); while (n && game_dir[n-1]=='/') --n;
    if (strncmp(host,game_dir,n) || host[n]!='/') return NULL;
    host+=n; while (*host=='/') ++host;
    return host;
}

int carbon_gin_path(char *host,size_t n,uint32_t access,uint32_t disp) {
    if (!cm_on("NFS_CARBON_X360_GIN")) return 0;
    const char *rel=cm_relative(host); if (!rel) return 0;
    static const char *const names[]={"EN_ACL_11.GIN","EN_ACL_25.GIN","EN_ACL_68.GIN","EN_DCL_11.GIN","EN_DCL_68.GIN"};
    static const uint32_t frames[]={438417,634776,591950,220762,519000};
    static const uint32_t sizes[]={262423,378891,353269,131925,309869};
    for (unsigned i=0;i<5;i++) {
        char expected[96],path[4096];
        snprintf(expected,sizeof expected,"SOUND/ENGINE/GIN/%s",names[i]);
        if (strcasecmp(rel,expected)) continue;
        if ((access&0x40000000u) || disp!=3) {errno=EACCES;return -1;}
        if (!cm_find(roots_x360_files(),expected,path,sizeof path)) return 0;
        int fd=open(path,O_RDONLY|O_NONBLOCK|O_CLOEXEC); struct stat st; uint8_t h[32];
        int ok=fd>=0 && !fstat(fd,&st) && S_ISREG(st.st_mode) && st.st_size==sizes[i] &&
            pread(fd,h,sizeof h,0)==sizeof h && !memcmp(h,"Gnsu20",6) &&
            cm_word(h+24,0)==frames[i] && cm_word(h+28,0)==48000;
        if (fd>=0) close(fd);
        if (!ok || strlen(path)>=n) return 0;
        strcpy(host,path);
        if (diag_on) diag_event("carbon_gin: serve %s rate=48000 frames=%u",names[i],frames[i]);
        return 1;
    }
    return 0;
}

typedef struct { size_t at; uint32_t value; } CMWord;
typedef struct {
    size_t offset, source, begin, end;
    unsigned header_size, channels;
    uint8_t header[48];
} CMSegment;
typedef struct {
    uint8_t *map,*mus;
    size_t maps,muss,served_size;
    unsigned table,count;
    CMSegment *segments;
    CMWord *words;
    size_t word_count,word_capacity;
} CarbonMusic;
static CarbonMusic cm_pairs[4];
static pthread_once_t cm_once=PTHREAD_ONCE_INIT;
static pthread_mutex_t cm_log_lock=PTHREAD_MUTEX_INITIALIZER;
static uint8_t cm_seen[4][991];
static int cm_ready;

static uint8_t *cm_map(const char *path,size_t *size,size_t maximum) {
    int fd=open(path,O_RDONLY|O_NONBLOCK|O_CLOEXEC); struct stat st; uint8_t *p=MAP_FAILED;
    if (fd>=0 && !fstat(fd,&st) && S_ISREG(st.st_mode) && st.st_size>=72 && (uint64_t)st.st_size<=maximum) {
        *size=(size_t)st.st_size; p=mmap(NULL,*size,PROT_READ|PROT_WRITE,MAP_PRIVATE,fd,0);
    }
    if (fd>=0) close(fd);
    return p==MAP_FAILED?NULL:p;
}
/* Preserve all authored fields, including volume/priority and loop tags.
 * PT09 omits its implicit rate/revision. The normalized header grows by at
 * most four bytes; a virtual file inserts one 128-byte sector per segment.
 * Encoded audio remains in the original read-only file mapping. */
static int cm_header(const uint8_t *p,size_t n,CMSegment *s,unsigned *samples) {
    if (n<32 || memcmp(p,"SCHl",4)) return 0;
    unsigned size=cm_word(p+4,0);
    if ((size!=32 && size!=40) || size>n || memcmp(p+8,"PT\11\0",4)) return 0;
    uint8_t *h=s->header; memset(h,0,sizeof s->header);memcpy(h,p,12);h[10]=0;
    unsigned dst=12,format=0,revision=0,priority=0,ended=0;s->channels=1;*samples=0;
    for (unsigned pos=12;pos<size;) {
        unsigned start=pos,id=p[pos++];
        if (id==0xff) {ended=1;break;}
        if (id>=0xfc) {if(dst>=sizeof s->header)return 0;h[dst++]=(uint8_t)id;continue;}
        if (pos>=size) return 0;
        unsigned w=p[pos++],v=0;
        if (!w || w>4 || w>size-pos) return 0;
        for (unsigned j=0;j<w;j++) v=v<<8|p[pos++];
        if (id==0x13) priority=(v==127);
        else if (id==6) format=v;
        else if (id==0x82) s->channels=v;
        else if (id==0x85) *samples=v;
        else if (id==0x8c) {if(v!=4 || w!=1)return 0;revision=1;}
        else if (id!=0x9c && id!=0x9d) return 0;
        if (pos-start>sizeof s->header-dst) return 0;
        memcpy(h+dst,p+start,pos-start);
        if (id==0x8c) {h[dst]=0x80;h[dst+2]=2;}
        dst+=pos-start;
    }
    if (!ended || format!=101 || !revision || !priority || !*samples ||
        (s->channels!=2 && s->channels!=4) || sizeof s->header-dst<5) return 0;
    h[dst++]=0x84;h[dst++]=2;h[dst++]=0xac;h[dst++]=0x44;h[dst++]=0xff;
    s->header_size=(dst+3)&~3u;cm_put(h+4,s->header_size);return 1;
}
static int cm_patch(CarbonMusic *p,size_t at,uint32_t value) {
    if (p->word_count==p->word_capacity) {
        size_t capacity=p->word_capacity?p->word_capacity*2:4096;
        if (capacity>p->muss/4) return 0;
        CMWord *words=realloc(p->words,capacity*sizeof *words);
        if (!words) return 0;
        p->words=words;p->word_capacity=capacity;
    }
    p->words[p->word_count++]=(CMWord){at,value};return 1;
}
/* Complete forward-only chains, packet counts and channel extents, bounded by
 * the next independently supplied segment offset. Only packet scalar patches
 * are retained; payload bytes never enter writable storage. */
static int cm_segment(CarbonMusic *pair,CMSegment *s,size_t off,size_t limit) {
    const uint8_t *p=pair->mus;unsigned samples;
    if (off>=limit || limit>pair->muss || !cm_header(p+off,limit-off,s,&samples)) return 0;
    size_t pos=off+cm_word(p+off+4,0);s->source=off;s->begin=pos;
    if (limit-pos<12 || memcmp(p+pos,"SCCl",4) || cm_word(p+pos+4,0)!=12) return 0;
    unsigned declared=cm_word(p+pos+8,1),blocks=0,total=0;
    if (!cm_patch(pair,pos+8,declared)) return 0;
    pos+=12;
    while (limit-pos>=8) {
        unsigned size=cm_word(p+pos+4,0);
        if (size<8 || size>limit-pos) return 0;
        if (!memcmp(p+pos,"SCEl",4)) {
            if (size!=8 || !blocks || blocks!=declared || total!=samples) return 0;
            s->end=pos+8;return 1;
        }
        unsigned payload=12+s->channels*4;
        if (memcmp(p+pos,"SCDl",4) || size<=payload) return 0;
        unsigned count=cm_word(p+pos+8,1);
        if (!count || count>16384 || count>samples-total) return 0;
        for (unsigned ch=0;ch<s->channels;ch++) {
            unsigned offset=cm_word(p+pos+12+4*ch,1);
            unsigned end=ch+1<s->channels?cm_word(p+pos+16+4*ch,1):size-payload;
            if ((!ch && offset) || end<=offset || end>size-payload || (!blocks && p[pos+payload+offset]!=0xee)) return 0;
        }
        if (!cm_patch(pair,pos+8,count)) return 0;
        for (unsigned ch=0;ch<s->channels;ch++)
            if (!cm_patch(pair,pos+12+4*ch,cm_word(p+pos+12+4*ch,1))) return 0;
        total+=count;++blocks;pos+=size;
    }
    return 0;
}
/* Overlay even a partial byte of a scalar; Win32 reads need not align. */
static void cm_copy(CarbonMusic *p,uint8_t *dst,size_t pos,size_t n) {
    memcpy(dst,p->mus+pos,n);
    size_t lo=0,hi=p->word_count;
    while (lo<hi) {size_t mid=(lo+hi)/2;if(p->words[mid].at+4<=pos)lo=mid+1;else hi=mid;}
    for (size_t i=lo;i<p->word_count && p->words[i].at<pos+n;i++) {
        CMWord w=p->words[i];
        for (unsigned j=0;j<4;j++) if (w.at+j>=pos && w.at+j<pos+n)
            dst[w.at+j-pos]=(uint8_t)(w.value>>(8*j));
    }
}
static size_t cm_read_at(void *source,void *buffer,size_t n,size_t pos) {
    CarbonMusic *p=source;uint8_t *dst=buffer;size_t written=0;
    if (pos>=p->served_size) return 0;
    if (n>p->served_size-pos) n=p->served_size-pos;
    memset(dst,0,n);
    while (written<n) {
        size_t at=pos+written,amount=n-written;
        if (at<256) {
            if(amount>256-at)amount=256-at;
            memcpy(dst+written,p->mus+at,amount);
        } else {
            unsigned lo=0,hi=p->count;
            while(lo<hi) {unsigned mid=(lo+hi)/2;if(p->segments[mid].offset<=at)lo=mid+1;else hi=mid;}
            if (!lo) {if(amount>p->segments[0].offset-at)amount=p->segments[0].offset-at;}
            else {
                CMSegment *s=p->segments+lo-1;
                size_t data=s->offset+s->header_size,end=data+s->end-s->begin;
                if (at<data) {
                    if(amount>data-at)amount=data-at;
                    memcpy(dst+written,s->header+at-s->offset,amount);
                } else if (at<end) {
                    if(amount>end-at)amount=end-at;
                    cm_copy(p,dst+written,s->begin+at-data,amount);
                } else if (lo<p->count && amount>p->segments[lo].offset-at)
                    amount=p->segments[lo].offset-at;
            }
        }
        written+=amount;
    }
    return n;
}

/* Copy the entire PC graph, changing only the offset member of each table row. */
static int cm_pair(CarbonMusic *pair,const uint8_t *x,size_t xs,unsigned expected,
                   unsigned *stereo,unsigned *quad) {
    uint8_t *pc=pair->map;size_t ps=pair->maps;
    if (ps<72 || xs<72 || memcmp(pc,"xDFP\5\2",6) || memcmp(x,"PFDx\5\2",6)) return 0;
    unsigned pt=cm_word(pc+52,0),xt=cm_word(x+52,1);
    if (pt<72 || xt<72 || pt>ps || xt>xs || cm_word(pc+56,0)!=ps || cm_word(x+56,1)!=xs ||
        ps-pt!=8*expected || xs-xt!=8*expected || memcmp(pc+8,x+8,10)) return 0;
    pair->segments=calloc(expected,sizeof *pair->segments);
    if (!pair->segments) return 0;
    size_t previous=0;
    for (unsigned i=0;i<expected;i++) {
        uint64_t off=(uint64_t)cm_word(x+xt+8*i,1)*128;
        uint64_t limit=i+1<expected?(uint64_t)cm_word(x+xt+8*(i+1),1)*128:pair->muss;
        unsigned duration=cm_word(pc+pt+8*i+4,0);
        CMSegment *s=pair->segments+i;
        if (!duration || duration!=cm_word(x+xt+8*i+4,1) || off<256 || off<=previous ||
            off>=limit || limit>pair->muss || !cm_segment(pair,s,(size_t)off,(size_t)limit)) return 0;
        s->offset=(size_t)off+128*i;
        cm_put(pc+pt+8*i,(uint32_t)(s->offset/128));
        *stereo+=s->channels==2;*quad+=s->channels==4;previous=(size_t)off;
    }
    pair->served_size=pair->muss+128*expected;
    pair->table=pt;pair->count=expected;return 1;
}
static void cm_init(void) {
    static const unsigned counts[]={303,383,327,991};
    char rel[64],path[4096]; unsigned stereo=0,quad=0;
    for (unsigned i=0;i<4;i++) {
        CarbonMusic *p=cm_pairs+i; uint8_t *x=NULL;size_t xs=0;
        snprintf(rel,sizeof rel,"SOUND/PFDATA/CB_MUS_%u.MPF",i);
        if (!cm_find(game_dir,rel,path,sizeof path) || !(p->map=cm_map(path,&p->maps,65536))) goto fail;
        if (!cm_find(roots_x360_files(),rel,path,sizeof path) || !(x=cm_map(path,&xs,65536))) goto fail;
        snprintf(rel,sizeof rel,"SOUND/PFDATA/CB_MUS_%u.MUS",i);
        int ok=cm_find(roots_x360_files(),rel,path,sizeof path) && (p->mus=cm_map(path,&p->muss,UINT32_MAX)) &&
            cm_pair(p,x,xs,counts[i],&stereo,&quad);
        munmap(x,xs);
        if (!ok) goto fail;
    }
    if (stereo!=2000 || quad!=4) goto fail;
    cm_ready=1;
    if (diag_on) diag_event("carbon_music: ready PC v5.2 graphs, 2004 offsets/durations, 2000 stereo + 4 quad, rate=44100, bounded SCEl chains");
    return;
fail:
    for (unsigned i=0;i<4;i++) {
        CarbonMusic *p=cm_pairs+i;
        if (p->map) munmap(p->map,p->maps);
        if (p->mus) munmap(p->mus,p->muss);
        free(p->segments);free(p->words);
        memset(p,0,sizeof *p);
    }
    if (diag_on) diag_event("carbon_music: incomplete or invalid source; all PC pairs kept");
}
int carbon_music_open(const char *host,X360MusicHandle *out) {
    if (!cm_on("NFS_CARBON_X360_MUSIC")) return 0;
    const char *rel=cm_relative(host);if (!rel) return 0;
    for (unsigned i=0;i<4;i++) for (unsigned mus=0;mus<2;mus++) {
        char name[64];snprintf(name,sizeof name,"SOUND/PFDATA/CB_MUS_%u.%s",i,mus?"MUS":"MPF");
        if (strcasecmp(rel,name)) continue;
        pthread_once(&cm_once,cm_init);
        if (!cm_ready) return 0;
        CarbonMusic *p=cm_pairs+i;
        *out=(X360MusicHandle){.data=mus?NULL:p->map,.size=mus?p->served_size:p->maps,
            .mus=mus,.source=mus?p:NULL,.read_at=mus?cm_read_at:NULL};
        if (diag_on) diag_event("carbon_music: serve %s source=X360 rate=44100 segments=%u",name,p->count);
        return 1;
    }
    return 0;
}
/* Existing import handles retain independent positions for every open. */
size_t x360music_read(X360MusicHandle *h,void *dst,size_t n) {
    size_t pos=(size_t)h->pos,left=pos<h->size?h->size-pos:0;if(n>left)n=left;
    if (n) {if(h->read_at)n=h->read_at(h->source,dst,n,pos);else memcpy(dst,h->data+pos,n);}
    if (diag_on && h->mus && n) {
        for (unsigned k=0;k<4;k++) if (h->source==cm_pairs+k) {
            CarbonMusic *p=cm_pairs+k;
            pthread_mutex_lock(&cm_log_lock);
            for (unsigned i=0;i<p->count;i++) {
                size_t off=(size_t)cm_word(p->map+p->table+8*i,0)*128;
                if (off>=pos && off+p->segments[i].header_size<=pos+n && !cm_seen[k][i]) {
                    cm_seen[k][i]=1;
                    diag_event("carbon_music: segment served bank=%u segment=%u offset=%zu rate=44100 bytes=%zu",k,i,off,n);
                }
            }
            pthread_mutex_unlock(&cm_log_lock);
        }
    }
    h->pos+=(int64_t)n;return n;
}
int64_t x360music_seek(X360MusicHandle *h,int64_t distance,unsigned method) {
    if (method>2) {errno=EINVAL;return -1;}
    int64_t base=method==0?0:method==1?h->pos:(int64_t)h->size;
    if (distance < -base || distance>INT64_MAX-base) {errno=EINVAL;return -1;}
    return h->pos=base+distance;
}
