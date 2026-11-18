"""Console police/crew and UCAP through the production file hook/native decoder.

Good: 14,135/14,135 native decodes at 36 kHz (14,063 speech + 72 UCAP).
Broken control omits IDX endian conversion: 0/8 files served, 0/14,135 decodes,
exit 1 versus exit 0. All eight UCAP six-channel clips have six nonzero,
pairwise distinct PCM channels; their six channels are preserved.
Default/off, absent and incomplete sources keep every byte of PC speech through
production Win32 imports, including the native small-file cache.
Cache-patch control: only 2/6 cached sidecars match versus 6/6, exit 1.
Copied link manifest: old fixture link exits 1 (missing _speed_imports),
relocated fixture link exits 0.
No audio output; scratch only; exit 3 without assets.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
from private_carbon_music_test import carbon_sound_test_inputs

# Only the executed native parser/decoder dependency closure, not whole outputs.
DECODERS = {
    "008BA348": "6c3e0a9fd47be45b0d5597305da32da006b54a1e095d2176332ca11152ba1fc4",
    "008BA380": "63071032524b8adc624369400bf72cd5ccd8d72104d81ee9ebce16f46b38f409",
    "008BA3B5": "8717eb4945a658ec10a2b69b508b930af7e23b6ca1aff9979bc8f789e5fc6bab",
    "008BA4DF": "13fb1ed32c8125d24695dac5b69acb38663a7717815676c78f11c1b2cd2ee915",
    "008BA516": "8809c94834fa284ddc1088e1cc5b73409a1a871d35707e04dfb0ac8c1fcc32d7",
    "008BA5A2": "fff17a1d439194010975e8e50cf527847f813379ba09468a7c09d38cf40ad803",
    "008BAC7A": "b41dc3cb15bcf8e83d5c25db3b8c65a1a15a3c9ed5b87f2dca4b6030f8274e5c",
    "008BAD41": "67f1449d2bd2172bbb54041a80d0e2665acf7768210e349b19abe90d679a084e",
    "008BAFBE": "0a2282502e9e5b1808eb5eeb2430d380f73be18a5d514b5e3c73bd2357ac4098",
    "008BAFF9": "2725c78ad51b7b81ae0e13647a49fa2d5053f7a8d3a19f429a406582e071a471",
    "008BB0BD": "3e290de19d90f9fb250de839e1e98dc0d21e6f65fb0a9452b4e5c97688640bce",
    "008A0CFE": "135e1dcda233fefaae2bd80048d8182352edce8b813a746f872794bfb7b6f9be",
    "008A692E": "e474dcffdc902c313a30eb6db57cf45d547a7f934e8d395fd639a4fe5239126d",
    "0089D3F0": "f54654ba1fdc85471fec95d8b61e66c12dd6be6474d6ece8448e8e1f21f3c572",
    "008A1090": "8eed4f33af4383167ee5e74607d2a249cf407233616e69c88801b800c95b51c5",
    "008AD46E": "2a23b376c0bafe89f77fa263389c095396ab5ea97f4130838a2b0af3c83a054c"
}

HARNESS = r'''
#include "runtime.h"
#include <stdlib.h>
#include <stdarg.h>
#include <math.h>
#include "selected_speech.c"
uint8_t *G;
const char *game_dir;
int diag_on;
void diag_event(const char *fmt,...) {(void)fmt;}
void f_008BAFBE(Cpu *);void f_008BAFF9(Cpu *);void f_008BB0BD(Cpu *);void f_008A0CFE(Cpu *);
/* Native host services only; all codec/parser work is translated game code. */
void dispatch(Cpu *c,uint32_t target) {
    if(target!=M32(0xa7ecc0))abort();
    uint32_t dst=M32(c->esp+4),src=M32(c->esp+8),n=M32(c->esp+12);
    memmove(G+dst,G+src,n);c->eax=dst;c->esp+=4;
}
void guest_divide_error(Cpu *c,uint32_t at){(void)c;(void)at;abort();}
void f_00897973(Cpu *c){(void)c;abort();}
void f_00898F99(Cpu *c){(void)c;abort();}
void f_008A69AA(Cpu *c){(void)c;abort();}
#define CHECK(v) do{if(!(v)){fprintf(stderr,"SPEECH FAIL line %d: %s\n",__LINE__,#v);return 1;}}while(0)
static uint32_t word(const uint8_t *p,int be) {
    uint32_t v=0;for(unsigned i=0;i<4;i++)v=v*256+p[be?i:3-i];return v;
}
static unsigned half(const uint8_t *p,int be){return be?p[0]*256u+p[1]:p[1]*256u+p[0];}
static unsigned attr(const uint8_t *p,unsigned wanted) {
    for(unsigned at=12;at<word(p+4,0);) {
        unsigned tag=p[at++];if(tag==255)break;if(tag>=252)continue;
        unsigned w=p[at++],v=0;for(unsigned i=0;i<w;i++)v=v*256+p[at++];
        if(tag==wanted)return v;
    }
    return wanted==0x82?1:0;
}
static uint8_t *file(const char *root,const char *name,size_t *size) {
    char path[4096];if(!cs_find(root,name,path,sizeof path))return NULL;
    FILE *f=fopen(path,"rb");if(!f)return NULL;
    fseek(f,0,SEEK_END);*size=(size_t)ftell(f);rewind(f);
    uint8_t *data=malloc(*size);if(!data || fread(data,1,*size,f)!=*size)abort();fclose(f);return data;
}
/* Oracle reads the ORIGINAL source IDX, independently of the production index
 * conversion/enumerator. The two-byte offsets remain BE on both platforms. */
static void extent(const uint8_t *idx,unsigned bank,unsigned sample,int be,size_t *start,size_t *end) {
    size_t row=88+16*bank,b=word(idx+row+8,be);
    unsigned stride=2+(idx[b+2]&127),scale=256*(1+idx[b+9]);
    *start=word(idx+row+12,be)+(size_t)half(idx+b+16+stride*sample,1)*scale;
    *end=word(idx+row+12,be)+(size_t)(sample+1<idx[b+3]?half(idx+b+16+stride*(sample+1),1):half(idx+b+10,be))*scale;
}
static unsigned six_decoded;
static unsigned long long decoded_frames;
static int decode(const uint8_t *p,size_t n) {
    unsigned channels=attr(p,0x82),samples=attr(p,0x85),total=0,blocks=0;
    CHECK(attr(p,0x84)==36000 && attr(p,0xa0)==22 && attr(p,0x80)==2 && p[10]==0);
    memcpy(G+0x1020000,p,word(p+4,0));
    Cpu header={0};header.cw=0x37f;header.esp=0x10ff000;
    const uint32_t args[]={0,0x1020008,0x1060400,0x1060410,0x1060500,0x1060520};
    for(unsigned j=0;j<6;j++)M32(header.esp+4+4*j)=args[j];
    f_008A0CFE(&header);
    CHECK(M16(0x1060400)==36000 && M8(0x1060402)==channels && M8(0x1060403)==22);
    CHECK(M32(0x1060500)==samples && M8(0x1060416)==2);
    for(unsigned ch=0;ch<channels;ch++) {
        memset(G+0x1010000+ch*0x1000,0,0x1000);
        Cpu c={0};c.cw=0x37f;c.ecx=0x1010000+ch*0x1000;c.esp=0x10ff000;f_008BAFBE(&c);
    }
    int16_t *pcm=channels==6?calloc(samples*channels,sizeof *pcm):NULL;
    double energy[6]={0};
    for(size_t at=word(p+4,0)+12;at+8<=n;) {
        unsigned size=word(p+at+4,0);if(!memcmp(p+at,"SCEl",4))break;
        unsigned count=word(p+at+8,0),payload=12+4*channels;
        CHECK(count && count<=16384 && count<=samples-total && size<=n-at);
        for(unsigned ch=0;ch<channels;ch++) {
            unsigned start=word(p+at+12+4*ch,0),end=ch+1<channels?word(p+at+16+4*ch,0):size-payload;
            CHECK(end>start+1 && end-start<0x10000-64);
            uint32_t state=0x1010000+ch*0x1000,input=0x1020000,output=0x1040000,cursor=0x1060000;
            memcpy(G+input,p+at+payload+start+1,end-start-1);memset(G+input+end-start-1,0,64);
            M32(state+0xd5c)=!blocks;
            Cpu c={0};c.cw=0x37f;c.ecx=state;c.esp=0x10ff000;
            M32(c.esp+4)=input;M32(c.esp+8)=count*4;M32(c.esp+12)=count;f_008BAFF9(&c);CHECK(!c.eax);
            M32(cursor)=output;c.ecx=state;c.esp=0x10ff000;
            M32(c.esp+4)=cursor;M32(c.esp+8)=count;f_008BB0BD(&c);
            CHECK(c.eax==count && !M32(state+0xd54));
            for(unsigned i=0;i<count;i++) {
                float v=MF32(output+4*i);CHECK(isfinite(v));
                int s=(int)fmax(-32768,fmin(32767,v));energy[ch]+=(double)s*s;
                if(pcm)pcm[ch*samples+total+i]=(int16_t)s;
            }
        }
        total+=count;blocks++;at+=size;
    }
    CHECK(total==samples);
    if(channels==6) {
        unsigned minimum=samples;
        for(unsigned ch=0;ch<6;ch++)CHECK(energy[ch]>0);
        for(unsigned a=0;a<6;a++)for(unsigned b=a+1;b<6;b++) {
            unsigned different=0;for(unsigned i=0;i<samples;i++)different+=pcm[a*samples+i]!=pcm[b*samples+i];
            CHECK(different>0);if(different<minimum)minimum=different;
        }
        printf("UCAP PCM six=%u frames=%u distinct_pairs=15/15 minimum_different=%u min_energy=%.0f\n",
            ++six_decoded,samples,minimum,fmin(fmin(energy[0],energy[1]),fmin(fmin(energy[2],energy[3]),fmin(energy[4],energy[5]))));
    }
    free(pcm);decoded_frames+=samples;return 0;
}
int main(int argc,char **argv) {
    CHECK(argc==6);game_dir=argv[1];int want=atoi(argv[4]),full=atoi(argv[5]);
    const char *names[]={"COPSPEECH","UCAPAUDIO"},*extensions[]={"BIG","CSI","EVT","IDX"};
    const unsigned banks[]={716,6},expected[]={14063,72};
    X360MusicHandle handles[2][4]={0};unsigned served=0,native=0,streams=0,stereo=0,six=0;
    for(unsigned k=0;k<2;k++)for(unsigned kind=0;kind<4;kind++) {
        char path[4096];snprintf(path,sizeof path,"%s/SOUND/SPEECH/%s.%s",game_dir,names[k],extensions[kind]);
        served+=carbon_speech_open(path,&handles[k][kind]);
    }
    printf("SPEECH served=%u/8 native_decoded=%u/14135\n",served,native);fflush(stdout);
    CHECK(served==(want?8:0));if(!want)return 0;
    X360MusicHandle cache={0};char cache_path[4096];
    snprintf(cache_path,sizeof cache_path,"%s/GLOBAL/InGameMemoryFile.bin",game_dir);
    CHECK(carbon_speech_open(cache_path,&cache));
    size_t cache_size;uint8_t *cache_pc=file(game_dir,"GLOBAL/InGameMemoryFile.bin",&cache_size);
    CHECK(cache_pc && cache_size==cache.size);
    uint8_t *expected_cache=malloc(cache_size);CHECK(expected_cache);memcpy(expected_cache,cache_pc,cache_size);
    const uint8_t *cached_idx[2]={0};unsigned cached=0;
    for(unsigned k=0;k<2;k++)for(unsigned kind=1;kind<4;kind++) {
        char path[96];snprintf(path,sizeof path,"SOUND\\SPEECH\\%s.%s",names[k],extensions[kind]);
        uint32_t hash=UINT32_MAX;for(const char *p=path;*p;p++)hash=hash*33+(uint8_t)*p;
        unsigned found=0;
        for(unsigned i=0;i<word(cache_pc+12,0);i++) {
            const uint8_t *row=cache_pc+16+20*i;if(word(row,0)!=hash)continue;
            unsigned off=word(row+4,0),size=word(row+8,0);CHECK(size==handles[k][kind].size);
            CHECK(size==word(row+12,0) && off<=cache_size && size<=cache_size-off);
            cached+=!memcmp(cache.data+off,handles[k][kind].data,size);
            memcpy(expected_cache+off,handles[k][kind].data,size);
            if(kind==3)cached_idx[k]=cache.data+off;
            found++;
        }
        CHECK(found==1);
    }
    printf("SPEECH cached_sidecars=%u/6 directory_and_other_files_unchanged=%d\n",cached,!memcmp(cache.data,expected_cache,cache_size));fflush(stdout);
    CHECK(cached==6 && !memcmp(cache.data,expected_cache,cache_size));
    free(cache_pc);free(expected_cache);
    G=calloc(1,0x2000000);CHECK(G);
    FILE *image=fopen(argv[3],"rb");CHECK(image);CHECK(fread(G,1,0x1000000,image)==0x1000000);fclose(image);
    for(unsigned k=0;k<2;k++) {
        char name[96];size_t xs,ps;
        snprintf(name,sizeof name,"SOUND/SPEECH/%s.IDX",names[k]);
        uint8_t *xidx=file(argv[2],name,&xs),*pidx=file(game_dir,name,&ps);CHECK(xidx && pidx && xs==ps);
        snprintf(name,sizeof name,"SOUND/SPEECH/%s.BIG",names[k]);
        char path[4096];CHECK(cs_find(argv[2],name,path,sizeof path));
        FILE *raw=fopen(path,"rb");CHECK(raw);
        unsigned count=0;
        for(unsigned bank=0;bank<banks[k];bank++) {
            size_t b=word(xidx+88+16*bank+8,1);
            CHECK(word(handles[k][3].data+88+16*bank+8,0)==b);
            for(unsigned sample=0;sample<xidx[b+3];sample++) {
                size_t off,end,poff,pend,actual,limit;extent(xidx,bank,sample,1,&off,&end);extent(pidx,bank,sample,0,&poff,&pend);
                extent(cached_idx[k],bank,sample,0,&actual,&limit);CHECK(actual==off && limit==end);
                size_t n=end-off;uint8_t *p=malloc(n),*original=malloc(n);CHECK(p && original);
                CHECK(x360music_seek(&handles[k][0],(int64_t)off,0)==(int64_t)off);
                CHECK(x360music_read(&handles[k][0],p,n)==n);
                CHECK(!fseek(raw,(long)off,SEEK_SET) && fread(original,1,n,raw)==n);
                unsigned channels=attr(p,0x82),samples=attr(p,0x85);stereo+=channels==2;six+=channels==6;
                CHECK(channels==attr(original,0x82) && samples==attr(original,0x85));
                /* Match duration against PC, allowing only its rate rounding. */
                snprintf(name,sizeof name,"SOUND/SPEECH/%s.BIG",names[k]);CHECK(cs_find(game_dir,name,path,sizeof path));
                FILE *pc=fopen(path,"rb");uint8_t ph[48];CHECK(pc && !fseek(pc,(long)poff,SEEK_SET) && fread(ph,1,48,pc)==48);fclose(pc);
                unsigned pc_rate=attr(ph,0x84);if(!pc_rate)pc_rate=22050;
                CHECK(fabs((double)samples/36000-(double)attr(ph,0x85)/pc_rate)<1.0/pc_rate);
                size_t at=word(p+4,0);CHECK(at==word(original+4,0));at+=12;
                while(at+8<=n && memcmp(p+at,"SCEl",4)) {
                    unsigned size=word(p+at+4,0),skip=12+4*channels;
                    CHECK(!memcmp(p+at+skip,original+at+skip,size-skip));at+=size;
                }
                if(!sample)for(unsigned edge=1;edge<=7;edge++) {
                    uint8_t part[8];size_t at=word(p+4,0)+7;
                    CHECK(x360music_seek(&handles[k][0],(int64_t)(off+at),0)==(int64_t)(off+at));
                    CHECK(x360music_read(&handles[k][0],part,edge)==edge && !memcmp(part,p+at,edge));
                }
                if(full){CHECK(!decode(p,n));native++;}
                free(p);free(original);count++;streams++;
            }
        }
        CHECK(count==expected[k]);free(xidx);free(pidx);fclose(raw);
    }
    printf("SPEECH indexed=%u/14135 native_decoded=%u/14135 stereo=%u six=%u frames=%llu\n",
        streams,native,stereo,six,decoded_frames);
    CHECK(streams==14135 && stereo==131 && six==8 && (!full || (native==14135 && six_decoded==8)));
    free(G);return 0;
}
'''

# Same real Win32 import fixture/linker used by the GIN/overlay regression.
# A separate executable avoids sharing process-lifetime selection state.
IMPORT_MAIN = r'''
static unsigned checks;
#define CHECK(v) do{++checks;if(!(v)){fprintf(stderr,"SPEECH IMPORT FAIL %u line %d: %s\n",checks,__LINE__,#v);return 1;}}while(0)
static uint32_t api(Cpu *c,unsigned i,unsigned n,...) {
    c->esp=0x100000;M32(c->esp)=0xfeed;va_list ap;va_start(ap,n);
    for(unsigned k=0;k<n;k++)M32(c->esp+4+4*k)=va_arg(ap,uint32_t);va_end(ap);
    host_import(c,0x100+4*i);if(c->esp!=0x100004+4*n)abort();return c->eax;
}
static uint32_t open_speech(Cpu *c,const char *name) {
    strcpy((char *)G+0x3000,name);return api(c,0,7,0x3000u,0x80000000u,1u,0u,3u,0u,0u);
}
int main(int argc,char **argv) {
    CHECK(argc==3);game_dir=argv[1];int want=atoi(argv[2]);
    G=mmap(NULL,1ull<<32,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANON,-1,0);CHECK(G!=MAP_FAILED);
    threads_init();Cpu c={0};c.fs_base=0x7000;
    const char *names[]={"copspeech","ucapaudio"},*extensions[]={"big","csi","evt","idx"};
    const unsigned xsize[2][4]={{433741824,6564,25257,89376},{4261888,180,555,528}};
    unsigned pc_files=0,xfiles=0;unsigned long long pc_bytes=0;
    for(unsigned k=0;k<2;k++)for(unsigned kind=0;kind<4;kind++) {
        char name[128],host[4096];snprintf(name,sizeof name,"SOUND/SPEECH/%s.%s",names[k],extensions[kind]);
        CHECK(private_resolve(name,host,sizeof host)==0);
        FILE *pc=fopen(host,"rb");CHECK(pc);fseek(pc,0,SEEK_END);unsigned ps=(unsigned)ftell(pc);rewind(pc);
        uint32_t h=open_speech(&c,name);CHECK(h!=UINT32_MAX);
        unsigned size=api(&c,1,2,h,0u);CHECK(size==(want?xsize[k][kind]:ps));
        uint32_t second=open_speech(&c,name);CHECK(second!=UINT32_MAX && second!=h);
        if(!want) {
            uint8_t bytes[65536];unsigned got=0;
            while(got<ps) {
                unsigned n=ps-got;if(n>sizeof bytes)n=sizeof bytes;
                CHECK(fread(bytes,1,n,pc)==n);
                CHECK(api(&c,2,5,h,0x200000u,n,0x4100u,0u)==1 && M32(0x4100)==n && !memcmp(bytes,G+0x200000,n));
                got+=n;
            }
            pc_bytes+=got;pc_files++;
        } else {
            CHECK(api(&c,2,5,h,0x200000u,48u,0x4100u,0u)==1 && M32(0x4100)==48);
            if(kind==0)CHECK(!memcmp(G+0x200000,"SCHl",4) && M16(0x20000a)==0);
            if(kind==1)CHECK(!memcmp(G+0x200000,"MOIR\0\3\0\0",8) && M8(0x200008)==0);
            if(kind==3)CHECK(M32(0x200000)==1 && M32(0x200004)==(k?6:716));
            CHECK(api(&c,6,5,h,0x200000u,4u,0x4100u,0u)==0 && !M32(0x4100));
            xfiles++;
        }
        CHECK(api(&c,2,5,h,0x200000u,16u,0x4100u,0u)==1 && M32(0x4100)==(want?16:0));
        CHECK(api(&c,2,5,second,0x210000u,16u,0x4100u,0u)==1 && M32(0x4100)==16);
        CHECK(api(&c,3,4,h,0u,0u,0u)==0);
        CHECK(api(&c,2,5,h,0x200000u,16u,0x4100u,0u)==1 && !memcmp(G+0x200000,G+0x210000,16));
        CHECK(api(&c,4,1,h)==1 && api(&c,4,1,second)==1);fclose(pc);
    }
    const char *cache_name="GLOBAL/InGameMemoryFile.bin";char cache_host[4096];
    CHECK(private_resolve(cache_name,cache_host,sizeof cache_host)==0);
    FILE *pc=fopen(cache_host,"rb");CHECK(pc);fseek(pc,0,SEEK_END);unsigned size=(unsigned)ftell(pc);rewind(pc);
    uint8_t *original=malloc(size);CHECK(original && fread(original,1,size,pc)==size);fclose(pc);
    uint32_t h=open_speech(&c,cache_name);CHECK(h!=UINT32_MAX && api(&c,1,2,h,0u)==size);
    CHECK(api(&c,2,5,h,0x220000u,size,0x4100u,0u)==1 && M32(0x4100)==size);
    CHECK((!memcmp(original,G+0x220000,size))==!want);
    CHECK(api(&c,4,1,h)==1);free(original);
    if(want)xfiles++;else {pc_files++;pc_bytes+=size;}
    printf("SPEECH IMPORT x360=%u/9 PC_byte_identical=%u/9 bytes=%llu checks=%u\n",xfiles,pc_files,pc_bytes,checks);
    return 0;
}
'''


def main():
    output = HERE / 'out/carbon'
    paths = [output / 'NFSC_54.c', output / 'NFSC_55.c']
    if not all(p.is_file() for p in paths) or not (output / 'link_command.json').is_file():
        print('SKIP: private decoder/runtime build absent')
        return 3
    with tempfile.TemporaryDirectory(prefix='carbon-speech-') as directory:
        scratch = Path(directory)
        inputs = carbon_sound_test_inputs(scratch / 'import')
        if not inputs:
            print('SKIP: private Carbon source assets absent')
            return 3
        pc, console = inputs
        import recomp
        image = json.loads((output / 'image.json').read_text())
        pe = recomp.PE(image['exe'], expected_sha256=image['sha256'])
        memory = bytearray(0x1000000)
        for _, _, va, size, raw in pe.sections:
            memory[pe.base+va:pe.base+va+size] = pe.data[raw:raw+size]
        (scratch / 'image.bin').write_bytes(memory)
        funcs = {m[1]: m[0] for path in paths for m in re.finditer(
            r'void f_([0-9A-F]{8})\(Cpu \*restrict c\) \{.*?\n}', path.read_text(), re.S)}
        for address, digest in DECODERS.items():
            assert hashlib.sha256(funcs[address].encode()).hexdigest() == digest
        (scratch / 'decoder.c').write_text('#include "runtime.h"\n' + '\n'.join(
            'void f_' + a + '(Cpu *);' for a in list(DECODERS) + ['00897973', '00898F99', '008A69AA']) +
            '\n' + '\n'.join(funcs[a] for a in DECODERS))
        production = (HERE / 'private_runtime/carbon_speech.c').read_text()
        feature = json.loads((HERE / 'private_runtime/features/speech.json').read_text())
        assert feature['bindings']['carbon_speech.c']['sha256'] == hashlib.sha256(production.encode()).hexdigest()
        assert (ROOT / 'runtime/boot.c').read_text().count('carbon_speech_open(host, &music)') == 1
        (scratch / 'test.c').write_text(HARNESS)
        env = dict(os.environ, NFS_X360_FILES=str(console), NFS_CARBON_X360_SPEECH='on',
                   NFS_ROOTS=str(scratch / 'no-roots'), BOOT_USERDATA=str(scratch),
                   BOOT_HEADLESS='1', NFS_AUDIO='null')
        for name in ('BOOT_DIAG', 'NFS_CARBON_TRACK_OVERLAY', 'NFS_CARBON_X360_MUSIC', 'NFS_CARBON_X360_GIN'):
            env.pop(name, None)

        import private_files_test as imports
        fixture_header = imports.HARNESS.split('static unsigned checks;', 1)[0]
        imports.HARNESS = fixture_header + IMPORT_MAIN
        folder = scratch / 'imports'
        folder.mkdir()
        # Exercise a manifest whose absolute archive path differs from the
        # staged output path, including when the test runs in the build checkout.
        staged_output = scratch / 'copied-build'
        staged_output.symlink_to(output, target_is_directory=True)
        binary = imports.build(staged_output, folder, 'good')

        def build(text):
            (scratch / 'selected_speech.c').write_text(text)
            command = ['clang', '-std=c11', '-D_DARWIN_C_SOURCE', '-O1', '-g', '-w',
                       '-fsanitize=address,undefined', '-I', str(ROOT / 'runtime'), '-I', str(HERE),
                       str(scratch / 'test.c'), str(scratch / 'decoder.c'),
                       str(HERE / 'private_runtime/carbon_music.c'), '-o', str(scratch / 'test')]
            r = subprocess.run(command, capture_output=True, text=True)
            assert r.returncode == 0, r.stderr[-2000:]

        def run(want, full=0, **changes):
            r = subprocess.run([str(scratch / 'test'), str(pc), str(console), str(scratch / 'image.bin'),
                                str(want), str(full)], env=dict(env, **changes),
                               capture_output=True, text=True, timeout=1800)
            print(r.stdout.strip(), r.stderr[-1200:].strip(), flush=True)
            return r

        build(production)
        assert run(1, full=1).returncode == 0
        cache_patch = '            if(ok)ok=cs_memory_patch(rel,pc,b->side[kind],p->sizes[kind]);'
        assert production.count(cache_patch) == 1
        build(production.replace(cache_patch, '/* broken: cached PC metadata retained */'))
        result = run(1)
        assert result.returncode == 1 and 'cached_sidecars=2/6' in result.stdout
        broken = '    memcpy(d,s,n);'
        assert production.count(broken) == 1
        build(production.replace(broken, broken + '\n    if(kind==CS_IDX)return 1; /* broken: no endian conversion */'))
        result = run(1)
        assert result.returncode == 1 and 'served=0/8 native_decoded=0/14135' in result.stdout

        def imported(want, unset=False, **changes):
            child = dict(env, **changes)
            if unset:
                child.pop('NFS_CARBON_X360_SPEECH', None)
            r = subprocess.run([str(binary), str(pc), str(want)], env=child,
                               capture_output=True, text=True, timeout=120)
            print(r.stdout.strip(), r.stderr[-1200:].strip(), flush=True)
            assert r.returncode == 0

        imported(1)
        imported(0, unset=True)
        for value in ('', 'off', '0', 'pc'):
            imported(0, NFS_CARBON_X360_SPEECH=value)
        absent = scratch / 'absent'
        absent.mkdir()
        imported(0, NFS_X360_FILES=str(absent))
        partial = scratch / 'partial/SOUND/SPEECH'
        partial.mkdir(parents=True)
        for p in (console / 'SOUND/SPEECH').iterdir():
            if p.name != 'UCAPAUDIO.IDX':
                (partial / p.name).symlink_to(p)
        imported(0, NFS_X360_FILES=str(partial.parents[1]))
        print('PASS: 14135 native decodes using cached IDX, real six-channel UCAP, endian/cache controls and byte-identical PC fallbacks')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
