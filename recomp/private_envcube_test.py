"""Retained allocator and actual Metal mips, no game or window.

Good: retail asks 256/1, opt-in asks 1024/0 -> 11 levels; 6 depths match.
Off without diagnostics installs 0 observers and preserves all guest/CPU bytes.
On: 60 mip/face checks read 128 (+/-1); 4 draw entry points sample trilinearly
and restore all 14 sampler words. Other effects, fallback and caller untouched.
Broken size=256: fixture exit 1 vs good 0 (edge 256 vs 1024).
Broken omitted generation: fixture exit 1 vs good 0 (mip texel 255 vs 128).
NFS_CARBON_REFLECT_HDR on (unset or 1): the render-target cube request carries format 113, else 21.
Broken float (format write removed): fixture exit 1 vs good 0 (format 21 vs 113).
Live: 18 same-process transitions, 3 rows x 2 starting states x 3 changes;
edge/format/mips/depths restore, old cube/fallback/depth refcounts reach zero,
all owned device bindings are cleared; original no-op reset exits 1 vs good 0.
The original 0070DE00 function is independently pinned, not a whole source file.
Exit 3 without Carbon outputs and the pinned executable.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
from recomp import PE

HARNESS = r'''
#include "render_internal.h"
#include <assert.h>
#include <stdarg.h>
uint8_t *G;
Device dev;
id<MTLDevice> mtl;
id<MTLCommandBuffer> cmd;
static id<MTLCommandQueue> fixture_queue;
int diag_on;
char diag_fx_pass[192];
static Obj objects[256];
static unsigned nobjects, nhost, ncubes, ndepths, ndraws, encoders;
static HostFn hosts[32];
static unsigned wanted, fail_creation;
static int hdr_wanted(void) { const char *v=getenv("NFS_CARBON_REFLECT_HDR"); const char *coat=getenv("NFS_CARBON_COAT");return (!coat||strcmp(coat,"0"))&&(!v||!strcmp(v,"1")); }
static uint32_t allocate_object(int kind) {
    assert(nobjects<256); Obj *o=&objects[nobjects++];
    o->guest=0x30000+nobjects*0x1000; o->kind=kind; o->refs=1; M32(o->guest)=0x4000;M32(0x4000+8)=0x20000008; return o->guest;
}
Obj *obj(uint32_t h) { for(unsigned i=0;i<nobjects;i++)if(objects[i].guest==h)return &objects[i];return NULL; }
RenderTex *gpu_tex(Obj *t) { return t->gpu; }
void end_pass(void) { ++encoders; }
void ensure_cmd(void) { if(!cmd)cmd=[fixture_queue commandBuffer]; }
void diag_event(const char *fmt,...) { (void)fmt; }
uint32_t host_fn(HostFn fn,const char *name) { (void)name;assert(nhost<32);hosts[nhost]=fn;return 0xf1000000+4*nhost++; }
#define CHECK(x) do{if(!(x)){fprintf(stderr,"CUBE CHECK line %d: %s\n",__LINE__,#x);exit(1);}}while(0)
static Obj *owner(uint32_t h) { Obj *o=obj(h); return o&&o->parent ? obj(o->parent) : o; }
static void bind(uint32_t *slot,uint32_t h) {
    if(*slot==h)return;
    Obj *o=owner(h);if(o)++o->refs;
    o=owner(*slot);if(o){CHECK(o->refs>0);--o->refs;}
    *slot=h;
}
static int device_call(Cpu *c,unsigned slot) {
    if(slot==25) {
        ++ncubes;
        if(fail_creation){RET(0x80004005,8);}
        uint32_t h=allocate_object(K_CUBE);Obj *o=obj(h);
        o->w=o->h=arg(c,1);o->levels=arg(c,2);o->usage=arg(c,3);o->fmt=arg(c,4);o->pool=arg(c,5);
        if(!o->levels){o->levels=1;for(uint32_t e=o->w;e>1;e>>=1)++o->levels;}
        M32(h)=0x4000;M32(0x4000+0x48)=0x20000048;M32(0x4000+8)=0x20000008;
        M32(arg(c,6))=h;
        if(o->usage==0)CHECK(o->w==256&&o->levels==1&&o->fmt==0x31545844&&o->pool==1);
        else CHECK(o->w==(wanted?1024:256)&&o->levels==(wanted?11:1)&&o->fmt==(hdr_wanted()?113u:21u));
        RET(0,8);
    }
    if(slot==29) {
        ++ndepths;CHECK(arg(c,1)==(wanted?1024:256)&&arg(c,2)==arg(c,1));
        uint32_t h=allocate_object(K_SURFACE);obj(h)->w=obj(h)->h=arg(c,1);M32(arg(c,7))=h;RET(0,9);
    }
    if(slot==37){bind(&dev.rt[arg(c,1)],arg(c,2));RET(0,3);}
    if(slot==39){bind(&dev.ds,arg(c,1));RET(0,2);}
    if(slot==65){bind(&dev.tex[arg(c,1)],arg(c,2));RET(0,3);}
    if(slot>=81&&slot<=84){++ndraws;RET(0,slot==81?4:slot==82?7:slot==83?5:9);}
    if(slot==17){++dev.frames;RET(0,5);}
    CHECK(0);return 0;
}
void dispatch(Cpu *c,uint32_t target) {
    if(target>=0xf1000000&&target<0xf1000000+4*nhost){CHECK(hosts[(target-0xf1000000)/4](c));return;}
    if(target>=0x10000000&&target<0x10000000+119*4){CHECK(device_call(c,(target-0x10000000)/4));return;}
    if(target==0x20000048){
        Obj *parent=obj(arg(c,0));CHECK(parent);
        uint32_t h=allocate_object(K_SURFACE);Obj *s=obj(h);
        s->parent=parent->guest;++parent->refs;s->face=arg(c,1);s->level=arg(c,2);s->w=s->h=parent->w;
        M32(arg(c,3))=h;c->eax=0;c->esp+=20;return;
    }
    if(target==0x20000008){Obj *o=owner(arg(c,0));CHECK(o&&o->refs>0);c->eax=--o->refs;c->esp+=8;return;}
    CHECK(0);
}
uint32_t call_guest(Cpu *c,uint32_t target,int n,const uint32_t *args) {
    uint32_t stack=c->esp;c->esp-=4*(n+1);M32(c->esp)=0;
    for(int i=0;i<n;++i)M32(c->esp+4+4*i)=args[i];
    dispatch(c,target);uint32_t result=c->eax;c->esp=stack;return result;
}
#define CARBON_ENVCUBE_FIXTURE 1
FEATURE
ORIGINAL
static Cpu initial(void) {
    Cpu c={0};c.esp=0x10000;c.ebx=123;c.esi=234;c.edi=345;c.ebp=456;return c;
}
static void reset(void) {
    memset(G,0,0xc00000);memset(objects,0,sizeof objects);memset(&dev,0,sizeof dev);
    nobjects=nhost=ncubes=ndepths=ndraws=encoders=0;
    memset(carbon_envcube_original,0,sizeof carbon_envcube_original);
    memset(carbon_envcube_callback,0,sizeof carbon_envcube_callback);
    carbon_envcube_cube=carbon_envcube_pending=carbon_envcube_allocating=0;
    carbon_envcube_samples=carbon_envcube_faces=carbon_envcube_generations=carbon_envcube_stale=0;
    M32(0xAB0ABC)=0x1000;M32(0x1000)=0x2000;
    for(unsigned i=0;i<119;i++)M32(0x2000+i*4)=0x10000000+i*4;
    M8(0xA63E77)=1;M32(0xA65340)=3;
    M32(0xA63AEC)=0x31545844;M32(0xA63AE4)=21;M32(0xA63AE8)=75;
}
static void invoke(unsigned slot) {
    Cpu c=initial();M32(c.esp+4)=0x1000;dispatch(&c,M32(0x2000+4*slot));
}
static void gpu_check(Obj *t) {
    MTLTextureDescriptor *d=[MTLTextureDescriptor textureCubeDescriptorWithPixelFormat:MTLPixelFormatBGRA8Unorm size:1024 mipmapped:YES];
    d.storageMode=MTLStorageModeShared;d.usage=MTLTextureUsageRenderTarget|MTLTextureUsageShaderRead;
    id<MTLTexture> texture=[mtl newTextureWithDescriptor:d];CHECK(texture&&texture.mipmapLevelCount==11);
    static RenderTex g;g.tex=texture;t->gpu=&g;
    uint8_t *bytes=malloc(1024*1024*4);CHECK(bytes);
    for(unsigned l=0;l<11;l++){
        unsigned edge=1024>>l;
        for(unsigned y=0;y<edge;y++)for(unsigned x=0;x<edge;x++){
            unsigned i=(y*edge+x)*4;
            bytes[i]=l?255:((x^y)&1?255:0);bytes[i+1]=l?0:bytes[i];bytes[i+2]=l?255:bytes[i];bytes[i+3]=255;
        }
        for(unsigned f=0;f<6;f++)[texture replaceRegion:MTLRegionMake2D(0,0,edge,edge) mipmapLevel:l slice:f withBytes:bytes bytesPerRow:edge*4 bytesPerImage:edge*edge*4];
    }
    /* First capture draw dirties the cube; switching to another face must wait.
     * Leaving the cube generates once, before any receiver can sample it. */
    dev.rt[0]=M32(0xAB0924);invoke(82);CHECK(carbon_envcube_pending);
    Cpu c=initial();M32(c.esp+4)=0x1000;M32(c.esp+8)=0;M32(c.esp+12)=M32(0xAB0928);
    dispatch(&c,M32(0x2000+37*4));CHECK(carbon_envcube_pending&&carbon_envcube_generations==0);
    c=initial();M32(c.esp+4)=0x1000;M32(c.esp+8)=0;M32(c.esp+12)=0;
    dispatch(&c,M32(0x2000+37*4));CHECK(!carbon_envcube_pending&&carbon_envcube_generations==(unsigned)diag_on);
    [cmd commit];[cmd waitUntilCompleted];CHECK(cmd.status==MTLCommandBufferStatusCompleted);cmd=nil;
    unsigned checked=0;
    for(unsigned l=1;l<11;l++)for(unsigned f=0;f<6;f++){
        unsigned edge=1024>>l;
        [texture getBytes:bytes bytesPerRow:edge*4 bytesPerImage:edge*edge*4 fromRegion:MTLRegionMake2D(0,0,edge,edge) mipmapLevel:l slice:f];
        for(unsigned i=0;i<edge*edge;i++)for(unsigned k=0;k<3;k++)CHECK(abs((int)bytes[i*4+k]-128)<=1);
        ++checked;
    }
    CHECK(checked==60);free(bytes);
    printf("GPU mip_faces=%u edge=%u levels=%u generations=%u\n",checked,t->w,t->levels,carbon_envcube_generations);
}
/* The translated native release runs before the host reset callback. */
static void f_007133A0(Cpu *c) { c->esp+=4; } /* unrelated post targets are absent */
NATIVE_RELEASE
static unsigned transitions;
static void transition(Cpu *c) {
    uint32_t old=M32(0xAB0920),backup=M32(0xAB0954),depth=M32(0xAB093C),face=M32(0xAB0924);
    bind(&dev.tex[3],old);bind(&dev.tex[7],backup);bind(&dev.rt[0],face);bind(&dev.ds,depth);
    carbon_envcube_pending=1;
    Cpu saved=*c;carbon_envcube_apply(0);CHECK(M8(0xAB0B25)==1);carbon_envcube_apply(1);CHECK(M8(0xAB0B25)==1);
    c->esp-=4;M32(c->esp)=0;native_release(c);saved=*c;live_picture_on_reset(c);CHECK(!memcmp(c,&saved,sizeof saved));
    CHECK(!M32(0xAB0954)&&!carbon_envcube_cube&&!carbon_envcube_pending);
    CHECK(owner(old)->refs==0&&owner(backup)->refs==0&&owner(depth)->refs==0);
    for(unsigned i=0;i<16;++i)CHECK(dev.tex[i]!=old&&dev.tex[i]!=backup);
    for(unsigned i=0;i<4;++i)CHECK(dev.rt[i]!=face);
    CHECK(dev.ds!=depth);
    M8(0xAB0B25)=0;carbon_envcube_allocate(c,carbon_orig_0070DE00);
    Obj *next=obj(M32(0xAB0920));CHECK(next&&next->guest!=old&&next->w==(wanted?1024:256));
    CHECK(next->fmt==(hdr_wanted()&&strcmp(getenv("NFS_CARBON_COAT"),"0")?113:21));
    CHECK(next->levels==(wanted?11:1)&&M32(0xA63AE0)==next->w);
    CHECK(carbon_envcube_cube==next->guest&&!carbon_envcube_pending);
    for(unsigned i=0;i<6;++i){Obj *d=obj(M32(0xAB093C+4*i));CHECK(d&&d->w==next->w);}
    ++transitions;
}
static int live(void) {
    G=calloc(1,0xc00000);CHECK(G);diag_on=0;
    for(unsigned row=0;row<3;++row)for(unsigned start=0;start<2;++start){
        reset();wanted=0;
        setenv("NFS_CARBON_COAT","1",1);setenv("NFS_CARBON_REFLECT_HDR","1",1);setenv("NFS_CARBON_ENVCUBE","0",1);
        const char *name=row==0?"NFS_CARBON_ENVCUBE":row==1?"NFS_CARBON_REFLECT_HDR":"NFS_CARBON_COAT";
        setenv(name,start?"1":"0",1);if(row==0)wanted=start;
        Cpu c=initial();carbon_envcube_allocate(&c,carbon_orig_0070DE00);
        unsigned initial_edge=obj(carbon_envcube_cube)->w, initial_format=obj(carbon_envcube_cube)->fmt;
        for(unsigned step=0;step<3;++step){
            unsigned value=step==1?start:!start;setenv(name,value?"1":"0",1);if(row==0)wanted=value;
            transition(&c);
            if(step==1)CHECK(obj(carbon_envcube_cube)->w==initial_edge&&obj(carbon_envcube_cube)->fmt==initial_format);
        }
    }
    printf("LIVE capture transitions=%u starts=2 rows=3 stale=0 format/edge/depth/mips restored\n",transitions);return 0;
}
int main(int argc,char **argv) { @autoreleasepool {
    if(argc==2&&!strcmp(argv[1],"live"))return live();
    CHECK(argc==3);wanted=!strcmp(argv[1],"1");diag_on=atoi(argv[2]);
    if(!strcmp(argv[1],"unset"))unsetenv("NFS_CARBON_ENVCUBE");else setenv("NFS_CARBON_ENVCUBE",argv[1],1);
    G=calloc(1,0xc00000);CHECK(G);reset();Cpu c=initial(), expected=c;
    if(!wanted&&!diag_on){
        carbon_orig_0070DE00(&expected);uint8_t *snapshot=malloc(0xc00000);memcpy(snapshot,G,0xc00000);
        reset();carbon_envcube_allocate(&c,carbon_orig_0070DE00);
        CHECK(!memcmp(snapshot,G,0xc00000)&&!memcmp(&c,&expected,sizeof c)&&nhost==0);free(snapshot);
    }else carbon_envcube_allocate(&c,carbon_orig_0070DE00);
    CHECK(c.eax==1&&c.esp==0x10004&&c.ebx==123&&c.esi==234&&c.edi==345&&c.ebp==456);
    CHECK(ncubes==2&&ndepths==6&&M32(0xA63AE0)==(wanted?1024:256));
    if(!wanted&&!diag_on){puts("OFF bytes_changed=0 observers=0 edge=256 levels=1");return 0;}
    Obj *t=obj(carbon_envcube_cube);CHECK(t&&t->w==(wanted?1024:256)&&t->levels==(wanted?11:1));
    if(wanted){mtl=MTLCreateSystemDefaultDevice();if(!mtl)return 3;fixture_queue=[mtl newCommandQueue];gpu_check(t);}
    dev.rt[0]=0;dev.tex[3]=t->guest;
    for(unsigned k=0;k<14;k++)dev.ss[3][k]=50+k;
    uint32_t saved[14];memcpy(saved,dev.ss[3],sizeof saved);
    /* Inspect state inside the forwarded draw, not just the override helper. */
    for(unsigned mode=0;mode<3;mode++){
        snprintf(diag_fx_pass,sizeof diag_fx_pass,"%s",mode==0?"IDI_CAR_FX/car/p0":mode==1?"IDI_CARNORMALMAP_FX/car_normalmap/p0":"IDI_WORLD_FX/world/p0");
        for(unsigned slot=81;slot<=84;slot++){
            unsigned before=carbon_envcube_samples;invoke(slot);
            CHECK(carbon_envcube_samples==before+(mode<2&&diag_on));
            CHECK(!memcmp(saved,dev.ss[3],sizeof saved));
        }
    }
    CHECK(!carbon_envcube_stale);
    uint32_t edge=256,levels=1;carbon_envcube_allocating=1;
    carbon_envcube_request(&edge,&levels,0,21,0x0070DE86);CHECK(edge==256&&levels==1);
    carbon_envcube_request(&edge,&levels,1,21,0x12345678);CHECK(edge==256&&levels==1);
    snprintf(diag_fx_pass,sizeof diag_fx_pass,"IDI_CAR_FX/car/p0");
    dev.tex[3]=M32(0xAB0954);unsigned samples=carbon_envcube_samples;
    invoke(82);CHECK(carbon_envcube_samples==samples&&!memcmp(saved,dev.ss[3],sizeof saved));
    printf("ALLOC edge=%u levels=%u depths=%u draws=%u samples=%u restored=14\n",t->w,t->levels,ndepths,ndraws,carbon_envcube_samples);
    reset();fail_creation=1;c=initial();carbon_envcube_allocate(&c,carbon_orig_0070DE00);
    CHECK(c.eax==0&&c.esp==0x10004&&M8(0xA63E77)==0&&M32(0xA65340)==0);
    CHECK(!carbon_envcube_cube&&M32(0xA63AE0)==256);
    puts("ALLOC failure: retained native disable/cleanup");
    return 0;
}}
'''


def run(args, expected=0, hdr='0'):
    env = {k: v for k, v in os.environ.items() if k != 'NFS_CARBON_REFLECT_HDR'}
    if hdr != 'unset':
        env['NFS_CARBON_REFLECT_HDR'] = hdr
    result = subprocess.run(list(map(str, args)), capture_output=True, text=True, env=env)
    assert result.returncode == expected, (args[:3], result.returncode, result.stdout[-1000:], result.stderr[-2000:])
    return result.stdout.strip()


def main():
    out = HERE / 'out/carbon'
    base_source = HERE / 'out/carbon-base/NFSC_37.c'
    if not (out / 'image.json').is_file() or not base_source.is_file() or not (out / 'NFSC.a').is_file():
        print('SKIP: Carbon outputs absent')
        return 3
    image = json.loads((out / 'image.json').read_text())
    if not Path(image['exe']).is_file():
        print('SKIP: Carbon executable absent')
        return 3
    pe = PE(image['exe'], expected_sha256='baaaaec33873d4ba7e4dbae6a5212049ffdcf9679a35d865d7625b4189952fd3')
    assert hashlib.sha256(pe.read(0x0070DE00, 0x159)).hexdigest() == '4e1df4d5d4ab441e4bc2b208fb1cb9988402a8d30d1f3f5bd6758063adf9593e'
    hook = json.loads((HERE / 'private_runtime/hooks/envcube.json').read_text())['hooks']
    feature_policy = json.loads((HERE / 'private_runtime/features/envcube.json').read_text())
    assert len(hook) == 1 and hook[0]['address'] == '0070DE00'
    assert hook[0]['provider'] == 'carbon_envcube_allocate'
    assert feature_policy['staged_sources']['carbon_envcube.m'] == 'carbon_envcube.h'
    assert feature_policy['sources']['carbon_envcube.m']['kind'] == 'unit'
    # World preparation overrides only its affected units in the base archive.
    # Unit 37 remains the base member; an old staged .c is not its provenance.
    text = base_source.read_text()
    assert 'carbon_envcube_allocate(c, carbon_orig_0070DE00);' in text, 'allocator bypasses private hook'
    symbols = run(['nm', '-gU', out / 'NFSC.a'])
    assert re.search(r'\b_f_0070DE00\b', symbols) and re.search(r'\b_carbon_orig_0070DE00\b', symbols)
    match = re.search(r'void (?:carbon_orig_0070DE00|f_0070DE00)\(Cpu \*restrict c\) \{', text)
    assert match, 'retained allocator absent'
    original = text[match.start():text.index('\n}', match.end()) + 2]
    original = re.sub(r'void f_0070DE00\(', 'void carbon_orig_0070DE00(', original, count=1)
    assert hashlib.sha256(pe.read(0x0071B1B0,0x212)).hexdigest() == 'e494a78a0b14b75fdf38b5162cefa9f79d614814716b92420a98877942631a1a'
    # Native Accept releases old effects (and their held texture parameters),
    # resets the capture/device, then recreates views. Keep that lifetime witness
    # separate from the host callback's reference-count fixture.
    assert hashlib.sha256(pe.read(0x007311B0,0x364)).hexdigest() == 'a2199da218bfdcbac645d2f599a058363de309e2ca9609db1bb7cf814c357d42'
    assert hashlib.sha256(pe.read(0x0072B370,0x233)).hexdigest() == 'b976ec96487c4a084b95f014558fc9e83ee658d71be0d5b6e092d2de0e890cdf'
    assert hashlib.sha256(pe.read(0x0073E700,0x37)).hexdigest() == '2ff923f6b42810286db0cb3d4e4dcba4052436cfde292262e6ab65bd87befd73'
    release_text=(HERE/'out/carbon-base/NFSC_38.c').read_text()
    release_start=release_text.index('void f_0071B1B0(Cpu *restrict c) {')
    release=release_text[release_start:release_text.index('\n}',release_start)+2].replace('f_0071B1B0(', 'native_release(',1)
    feature = (HERE / 'private_runtime/carbon_envcube.h').read_text()
    # The draw checker executes inside dispatch, before sampler restoration.
    checker = '''if(dev.tex[3] && dev.tex[3]!=M32(0xAB0954) && !strncmp(diag_fx_pass,"IDI_CAR",7)) {
        if(wanted)CHECK(dev.ss[3][5]==2&&dev.ss[3][6]==2&&dev.ss[3][7]==2&&dev.ss[3][8]==0&&dev.ss[3][9]==0);
        else CHECK(dev.ss[3][5]==55&&dev.ss[3][6]==56&&dev.ss[3][7]==57);
    }'''
    harness = HARNESS.replace('if(slot>=81&&slot<=84){++ndraws;', 'if(slot>=81&&slot<=84){'+checker+'++ndraws;')
    with tempfile.TemporaryDirectory(prefix='carbon-envcube-') as directory:
        temp = Path(directory)
        def build(name, code):
            path = temp / (name + '.m')
            path.write_text(harness.replace('FEATURE', code).replace('ORIGINAL', original).replace('NATIVE_RELEASE', release))
            binary = temp / name
            run(['clang', '-O1', '-w', '-fobjc-arc', '-I', HERE, '-I', ROOT/'runtime',
                 '-I', ROOT/'host/shaders', path, '-framework', 'Metal', '-framework', 'Foundation', '-o', binary])
            return binary
        good = build('good', feature)
        print(run([good, 'live']))
        old_reset='void live_picture_on_reset(Cpu *c)'
        begin=feature.index(old_reset); end=feature.index('\nstatic void carbon_envcube_allocated',begin)
        old=feature[:begin]+'void live_picture_on_reset(Cpu *c) { (void)c; }\n'+feature[end:]
        run([build('old_reset',old),'live'],expected=1)
        print('OLD reset: live lifetime check exit=1 (good=0)')
        for option in ('unset', '0', '2'):
            print(run([good, option, '0']))
        print(run([good, '0', '1']))
        print(run([good, '1', '1']))
        print(run([good, '1', '0']))
        for option, diag in (('1', '0'), ('0', '1'), ('1', '1')):
            run([good, option, diag], hdr='1')
        run([good, '1', '1'], hdr='0')
        run([good, '1', '1'], hdr='unset')
        print('HDR cube format=113 (three selections); 0 keeps 21')
        assert feature.count('M32(c->esp+20)=113;') == 1
        run([build('float', feature.replace('M32(c->esp+20)=113;', '(void)0;')), '1', '1'], expected=1, hdr='1')
        print('BROKEN float: exit=1 (good=0)')
        mutations = {'size': ('*edge = 1024;', '*edge = 256;'),
                     'generation': ('[b generateMipmapsForTexture:g->tex];', '(void)b;')}
        for name, (before, after) in mutations.items():
            assert feature.count(before) == 1
            binary = build(name, feature.replace(before, after))
            run([binary, '1', '1'], expected=1)
            print(f'BROKEN {name}: exit=1 (good=0)')
    print('PRIVATE ENVCUBE PASS')
    return 0


if __name__ == '__main__':
    sys.exit(main())
