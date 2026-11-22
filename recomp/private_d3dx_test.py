"""Six private D3DX APIs through native imports and shared resources, no GPU/game.

Good: 97 checks with real hard links; 94 when file-link is denied (case SKIP).
Synthetic DDS, mips/faces/depth, fill callback, surface copy (including 32-bit into
DXT1, the car skin composite: the loader before the encoder fails check 85, 82 passed),
ID3DXBuffer and scratch saves. Disabled APIs fail checks 5/18/33/38/43/52, exit 1.
Install-directory JPEG rejection returns 80070005 in both builds. The original
code fails check 62 with 1 readback call and 1 ImageIO finalization. The fix counts
0 and 0. An allowed JPEG save still exercises both counters once.
Two runs in one tree: the 2nd PASSES before and after the fix (reproduction not seen here; scratch now cleared anyway).
Exit 3 when private build artifacts are absent.
"""
import json
import shutil
import errno
import os
from pathlib import Path
import subprocess
import sys
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
from build_private import ignored_output
sys.path.insert(0, str(HERE / "private_runtime"))
from layers import selected_source

NAMES=['D3DXCreateVolumeTextureFromFileInMemory','D3DXCreateCubeTextureFromFileInMemory','D3DXFillVolumeTexture','D3DXLoadSurfaceFromSurface','D3DXSaveSurfaceToFileInMemory','D3DXSaveSurfaceToFileA']
HARNESS=r'''#include "d3d9_internal.h"
#import <ImageIO/ImageIO.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <stdarg.h>
#include <unistd.h>
const uint32_t guest_func_addr[]={0};void (*const guest_func_ptr[])(Cpu*)={0};const unsigned guest_func_count=0;const uint32_t speed_entry=0;
/* This host-only fixture must never enter native startup completion. */
void f_0059B1B0(Cpu *c){(void)c;abort();}
const char speed_exe_fingerprint[]="",speed_exe_sha256[]="",speed_exe_region_sha256[4][65]={{0}};
const struct ExeRegion {const char *name;uint32_t rva,size;} speed_exe_regions[3]={{0}};
IMPORT_TABLE
extern void threads_init(void);extern uint32_t private_fixture_device(void),private_fixture_surface(uint32_t,unsigned,unsigned);
extern const char *game_dir;
static unsigned checks,callbacks;
unsigned fixture_readbacks, fixture_encodes;
#define CHECK(v) do{++checks;if(!(v)){fprintf(stderr,"D3DX CHECK %u line %d failed: %s\n",checks,__LINE__,#v);return 1;}}while(0)
static uint32_t api(Cpu*c,unsigned i,unsigned n,...){c->esp=0x100000;M32(c->esp)=0xfeed;va_list ap;va_start(ap,n);for(unsigned k=0;k<n;k++)M32(c->esp+4+4*k)=va_arg(ap,uint32_t);va_end(ap);host_import(c,0x100+4*i);if(c->esp!=0x100004+4*n){fprintf(stderr,"bad D3DX stdcall\n");exit(2);}return c->eax;}
static uint32_t com(Cpu*c,uint32_t self,unsigned slot,unsigned n,...){c->esp=0x100000;M32(c->esp)=0xfeed;M32(c->esp+4)=self;va_list ap;va_start(ap,n);for(unsigned k=1;k<n;k++)M32(c->esp+4+4*k)=va_arg(ap,uint32_t);va_end(ap);dispatch(c,M32(M32(self)+4*slot));if(c->esp!=0x100004+4*n)exit(2);return c->eax;}
static void put(uint32_t p,uint32_t v){M32(p)=v;}
static unsigned dds(uint32_t p,int cube){memset(G+p,0,512);memcpy(G+p,"DDS ",4);put(p+4,124);put(p+8,0x80100f);put(p+12,2);put(p+16,2);put(p+20,cube?8:12);put(p+24,cube?0:2);put(p+28,2);put(p+76,32);put(p+80,0x41);put(p+88,32);put(p+92,0xff0000);put(p+96,0xff00);put(p+100,0xff);put(p+104,0xff000000);put(p+108,0x401008);put(p+112,cube?0xfe00:0x200000);
 unsigned pos=p+128;for(unsigned f=0;f<(cube?6:1);f++){for(unsigned z=0;z<(cube?1:2);z++)for(unsigned y=0;y<2;y++){for(unsigned x=0;x<2;x++)put(pos+4*x,0xff000000u|f*0x10000u|z*0x1000u|y*0x100u|x);pos+=cube?8:12;}put(pos,0xffabcdefu+f);pos+=4;}return pos-p;}
static int fill(Cpu*c){uint32_t color=arg(c,0),pos=arg(c,1),step=arg(c,2),user=arg(c,3);float v[4];memcpy(v,G+pos,12);v[3]=1;memcpy(G+color,v,16);float size;memcpy(&size,G+step,4);if(!(size>0&&size<=1))exit(2);++M32(user);++callbacks;c->ebx=0xbaad;c->esi=0xbaad;RET(0,4);}
static int run(int argc,char**argv){CHECK(argc==3);game_dir=argv[2];G=mmap(NULL,1ull<<32,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANON,-1,0);CHECK(G!=MAP_FAILED);threads_init();Cpu c={0};c.fs_base=0x7000;uint32_t device=private_fixture_device();CHECK(device&&obj(device)->kind==K_DEVICE);CHECK(mtl==nil);
 unsigned size=dds(0x4000,0);CHECK(api(&c,0,4,device,0x4000u,size,0x4800u)==0);uint32_t volume=M32(0x4800);Obj *v=obj(volume);CHECK(v&&v->kind==K_VOLUME&&v->w==2&&v->h==2&&v->d==2&&v->levels==2&&v->pitch[0]==8);
 for(unsigned z=0;z<2;z++)for(unsigned y=0;y<2;y++)for(unsigned x=0;x<2;x++)CHECK(M32(v->mem[0]+z*16+y*8+x*4)==(0xff000000u|z*0x1000u|y*0x100u|x));CHECK(M32(v->mem[1])==0xffabcdefu);
 // Header and all mip payload bounds are checked before constructing a resource.
 CHECK(api(&c,0,4,device,0x4000u,size-1,0x4804u)!=0&&M32(0x4804)==0);M32(0x401c)=17;CHECK(api(&c,0,4,device,0x4000u,size,0x4804u)!=0);M32(0x401c)=2;
 size=dds(0x5000,1);CHECK(api(&c,1,4,device,0x5000u,size,0x4804u)==0);uint32_t cube=M32(0x4804);Obj *q=obj(cube);CHECK(q&&q->kind==K_CUBE&&q->levels==2);
 for(unsigned f=0;f<6;f++){CHECK(M32(q->mem[f*16])==(0xff000000u|f*0x10000u));CHECK(M32(q->mem[f*16+1])==0xffabcdefu+f);}
 M32(0x5070)=0x200;CHECK(api(&c,1,4,device,0x5000u,size,0x4808u)!=0);M32(0x5070)=0xfe00;
 uint32_t callback=host_fn(fill,"synthetic volume fill");c.ebx=0x11;c.esi=0x22;CHECK(api(&c,2,3,volume,callback,0x4900u)==0);CHECK(c.ebx==0x11&&c.esi==0x22&&callbacks==9&&M32(0x4900)==9);CHECK(M32(v->mem[0])==0xff404040u&&M32(v->mem[0]+28)==0xffbfbfbfu&&M32(v->mem[1])==0xff808080u&&v->dirty);
 CHECK(api(&c,2,3,cube,callback,0u)!=0);
 // Each surface test starts from distinct synthetic cube DDS face data.
 uint32_t src=private_fixture_surface(cube,3,0);uint32_t dst=private_fixture_surface(cube,4,0);CHECK(src&&dst);
 CHECK(api(&c,3,8,dst,0u,0u,src,0u,0u,1u,0u)==0);CHECK(!memcmp(G+q->mem[4*16],G+q->mem[3*16],16));
 put(0x4a00,0);put(0x4a04,0);put(0x4a08,1);put(0x4a0c,1);CHECK(api(&c,3,8,dst,0u,0x4a00u,src,0u,0u,2u,0u)==0);CHECK(M32(q->mem[4*16])==M32(q->mem[3*16]+12));put(0x4a08,3);CHECK(api(&c,3,8,dst,0u,0x4a00u,src,0u,0u,1u,0u)!=0);
 CHECK(api(&c,4,5,0x4808u,4u,src,0u,0u)==0);uint32_t buffer=M32(0x4808),ptr=com(&c,buffer,3,1),len=com(&c,buffer,4,1);CHECK(len==144&&!memcmp(G+ptr,"DDS ",4)&&M32(ptr+16)==2&&!memcmp(G+ptr+128,G+q->mem[3*16],16));CHECK(com(&c,buffer,1,1)==2);CHECK(com(&c,buffer,2,1)==1);CHECK(com(&c,buffer,2,1)==0);
 CHECK(api(&c,4,5,0x4808u,3u,src,0u,0u)==0);buffer=M32(0x4808);ptr=com(&c,buffer,3,1);len=com(&c,buffer,4,1);CHECK(len>8&&!memcmp(G+ptr,"\x89PNG\r\n\x1a\n",8));CFDataRef data=CFDataCreate(NULL,G+ptr,len);CGImageSourceRef image=CGImageSourceCreateWithData(data,NULL);CHECK(image&&CGImageSourceGetCount(image)==1);CGImageRef decoded=CGImageSourceCreateImageAtIndex(image,0,NULL);CHECK(decoded&&CGImageGetWidth(decoded)==2&&CGImageGetHeight(decoded)==2);CGImageRelease(decoded);CFRelease(image);CFRelease(data);com(&c,buffer,2,1);
 char path[4096];snprintf(path,sizeof path,"%s/saved.dds",argv[1]);strcpy((char*)G+0x6000,path);CHECK(api(&c,5,5,0x6000u,4u,src,0u,0u)==0);FILE*f=fopen(path,"rb");CHECK(f!=NULL);uint8_t encoded[144];CHECK(fread(encoded,1,144,f)==144&&!memcmp(encoded,"DDS ",4)&&!memcmp(encoded+128,G+q->mem[3*16],16));fclose(f);
 snprintf(path,sizeof path,"%s/../escape.dds",argv[1]);strcpy((char*)G+0x6000,path);CHECK(api(&c,5,5,0x6000u,4u,src,0u,0u)==0x80070005u);
 snprintf(path,sizeof path,"%s/link/escape.dds",argv[1]);strcpy((char*)G+0x6000,path);CHECK(api(&c,5,5,0x6000u,4u,src,0u,0u)==0x80070005u);
 snprintf(path,sizeof path,"%s/asset.dds",argv[2]);strcpy((char*)G+0x6000,path);CHECK(api(&c,5,5,0x6000u,4u,src,0u,0u)==0x80070005u);
 // A render target goes through the same readback and JPEG encoder as the back buffer.
 uint32_t usage=obj(src)->usage;
 obj(src)->usage|=1;
 snprintf(path,sizeof path,"%s/saved.jpg",argv[1]);
 strcpy((char*)G+0x6000,path);
 fixture_readbacks=fixture_encodes=0;
 CHECK(api(&c,5,5,0x6000u,1u,src,0u,0u)==0);
 CHECK(fixture_readbacks==1&&fixture_encodes==1);
 f=fopen(path,"rb");
 CHECK(f!=NULL);
 size_t jpeg_header=fread(encoded,1,2,f);
 fclose(f);
 CHECK(jpeg_header==2&&encoded[0]==0xff&&encoded[1]==0xd8);

 strcpy((char*)G+0x6000,"C:\\NFSMWnfscarbon000.jpg");
 fixture_readbacks=fixture_encodes=0;
 uint32_t denied=api(&c,5,5,0x6000u,1u,src,0u,0u);
 printf("denied JPEG: hr=%08x readbacks=%u encodes=%u\n",denied,fixture_readbacks,fixture_encodes);
 CHECK(denied==0x80070005u&&fixture_readbacks==0&&fixture_encodes==0);
 obj(src)->usage=usage;
 snprintf(path,sizeof path,"%s/invalid.jpg",argv[1]);
 strcpy((char*)G+0x6000,path);
 CHECK(api(&c,5,5,0x6000u,1u,0u,0u,0u)==0x8876086cu);
 CHECK(access(path,F_OK)==-1&&errno==ENOENT);
 int hardlink=getenv("PRIVATE_D3DX_HARDLINK")&&!strcmp(getenv("PRIVATE_D3DX_HARDLINK"),"1");
 if(hardlink){snprintf(path,sizeof path,"%s/hardlink.dds",argv[1]);strcpy((char*)G+0x6000,path);CHECK(api(&c,5,5,0x6000u,4u,src,0u,0u)==0);
  snprintf(path,sizeof path,"%s/../outside/keep.bin",argv[1]);FILE*keep=fopen(path,"rb");CHECK(keep!=NULL);char sentinel[64]={0};size_t n=fread(sentinel,1,sizeof sentinel,keep);fclose(keep);CHECK(n==sizeof("outside scratch must survive")-1&&!memcmp(sentinel,"outside scratch must survive",sizeof("outside scratch must survive")-1));}
 // Depth, rather than width/height, determines the maximum volume mip count.
 dds(0x7000,0);put(0x7000+12,1);put(0x7000+16,1);put(0x7000+20,4);put(0x7000+24,4);put(0x7000+28,3);CHECK(api(&c,0,4,device,0x7000u,156u,0x4810u)==0);Obj *deep=obj(M32(0x4810));CHECK(deep&&deep->levels==3&&deep->d==4&&deep->mem[2]);
 CHECK(api(&c,2,3,deep->guest,callback,0x4900u)==0);
 // Float16 volume fill uses the actual pitched 3D storage at every mip.
 dds(0x7000,0);put(0x7000+20,16);put(0x7000+80,4);put(0x7000+84,113);CHECK(api(&c,0,4,device,0x7000u,200u,0x4810u)==0);Obj *half=obj(M32(0x4810));CHECK(half&&half->fmt==113&&half->pitch[0]==16);CHECK(api(&c,2,3,half->guest,callback,0x4900u)==0);CHECK(M16(half->mem[0])==0x3400&&M16(half->mem[0]+6)==0x3c00&&M16(half->mem[1])==0x3800);
 // A block-compressed synthetic cube is preserved and decoded for surface copy.
 dds(0x7000,1);put(0x7000+8,0x81007);put(0x7000+12,4);put(0x7000+16,4);put(0x7000+20,8);put(0x7000+28,1);put(0x7000+80,4);put(0x7000+84,0x31545844);for(unsigned f=0;f<6;f++){M16(0x7080+8*f)=0xf800;M16(0x7082+8*f)=0;M32(0x7084+8*f)=0;}
 CHECK(api(&c,1,4,device,0x7000u,176u,0x4814u)==0);Obj *bc=obj(M32(0x4814));CHECK(bc&&bc->fmt==0x31545844&&bc->pitch[0]==8);uint32_t bc_surface=private_fixture_surface(bc->guest,2,0);CHECK(api(&c,3,8,dst,0u,0u,bc_surface,0u,0u,2u,0u)==0);CHECK(M32(q->mem[4*16])==0xffff0000u);
 CHECK(api(&c,4,5,0x4818u,4u,bc_surface,0u,0u)==0);buffer=M32(0x4818);ptr=com(&c,buffer,3,1);CHECK(com(&c,buffer,4,1)==136&&M32(ptr+84)==0x31545844&&M16(ptr+128)==0xf800);com(&c,buffer,2,1);
 CHECK(api(&c,4,5,0x4818u,7u,src,0u,0u)!=0&&M32(0x4818)==0);
 M32(q->mem[3*16])=0xffff0000;M32(q->mem[3*16]+4)=0xff00ff00;M32(q->mem[3*16]+8)=0xff0000ff;M32(q->mem[3*16]+12)=0xffffffff;put(0x4a08,1);
 for(unsigned filter=3;filter<=5;filter++){CHECK(api(&c,3,8,dst,0u,0x4a00u,src,0u,0u,filter,0u)==0);CHECK(M32(q->mem[4*16])==0xff808080u);}
 CHECK(api(&c,3,8,dst,0u,0u,src,0u,0u,1u,0xff0000ffu)==0);CHECK(M32(q->mem[4*16]+8)==0x000000ffu);
 // A 32-bit surface converts into a DXT1 surface (the car skin composite; rejected before, leaving the skin's old
 // texels): solid 4x4 blocks round-trip exactly and alpha below one half is the transparent texel, the vinyl mask.
 dds(0x9000,1);put(0x9000+8,0x81007);put(0x9000+12,8);put(0x9000+16,8);put(0x9000+20,32);put(0x9000+28,1);put(0x9000+80,4);put(0x9000+84,0x31545844);
 CHECK(api(&c,1,4,device,0x9000u,320u,0x481cu)==0);Obj *skin=obj(M32(0x481c));CHECK(skin&&skin->fmt==0x31545844&&skin->w==8);uint32_t skin_surface=private_fixture_surface(skin->guest,0,0);
 M32(q->mem[3*16]+8)=0x000000ffu;CHECK(api(&c,3,8,skin_surface,0u,0u,src,0u,0u,2u,0u)==0);CHECK(api(&c,3,8,dst,0u,0u,skin_surface,0u,0u,2u,0u)==0);
 CHECK(M32(q->mem[4*16])==0xffff0000u&&M32(q->mem[4*16]+4)==0xff00ff00u&&M32(q->mem[4*16]+8)==0u&&M32(q->mem[4*16]+12)==0xffffffffu);
 uint32_t mixed=private_fixture_surface(bc->guest,3,0);CHECK(api(&c,3,8,mixed,0u,0u,src,0u,0u,2u,0u)==0);CHECK(api(&c,3,8,dst,0u,0u,mixed,0u,0u,2u,0u)==0);
 CHECK(M32(q->mem[4*16])>>24==0xffu&&M32(q->mem[4*16]+4)>>24==0xffu&&M32(q->mem[4*16]+8)>>24==0u&&M32(q->mem[4*16]+12)==0xffffffffu);
 printf("PRIVATE D3DX PASS checks=%u APIs=6 callback_voxels=%u scratch_escape_rejected=3 hardlink_case=%s GPU=0\n",checks,callbacks,hardlink?"PASS":"SKIP");return 0;}
int main(int argc,char**argv){@autoreleasepool{return run(argc,argv);}}
'''


def build(root,out):
    dst=root/'runtime';table='const struct {uint32_t slot;const char *name;} speed_imports[]={'+','.join('{'+str(0x100+4*i)+','+json.dumps('d3dx9_30.dll!'+name)+'}' for i,name in enumerate(NAMES))+'};const unsigned speed_import_count=6;'
    (out/'test.m').write_text(HARNESS.replace('IMPORT_TABLE',table))
    source=selected_source(dst/'d3d9.m').replace('int private_d3dx_textures(Cpu *c,const char *fn)', 'int fixture_d3dx_real(Cpu *c,const char *fn)')
    readback='private_surface_readback(s->guest,m,*pitch)'
    encode='CGImageDestinationFinalize(dest)'
    assert source.count(readback)==source.count(encode)==1
    source=source.replace(readback,'(++fixture_readbacks, '+readback+')')
    source=source.replace(encode,'(++fixture_encodes, '+encode+')')
    source='extern unsigned fixture_readbacks, fixture_encodes;\n'+source
    temp_open='openat(dir,temp,O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW,0600)'
    assert source.count(temp_open)==1
    source=source.replace(temp_open,'fixture_save_open(dir,temp,part)')
    helper='''
static int fixture_save_open(int dir,char *temp,const char *part){
    if(getenv("PRIVATE_D3DX_UNSAFE_HARDLINK")&&!strcmp(part,"hardlink.dds")){
        strcpy(temp,part);
        return openat(dir,temp,O_WRONLY|O_TRUNC|O_NOFOLLOW);
    }
    return openat(dir,temp,O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW,0600);
}
'''
    save=source.rindex('\n',0,source.index(' px_save_file('))+1
    source=source[:save]+helper+source[save:]
    source+='''
uint32_t private_fixture_device(void){d3d9_init();dev.self=new_obj(K_DEVICE,vt_device);return dev.self->guest;}
uint32_t private_fixture_surface(uint32_t t,unsigned f,unsigned l){return texture_surface(obj(t),f,l);}
int private_d3dx_textures(Cpu*c,const char*fn){const char*bad=getenv("PRIVATE_D3DX_BROKEN");if(bad&&!strcmp(fn,bad)){RET(PX_UNSUPPORTED,!strcmp(fn,"D3DXFillVolumeTexture")?3:!strcmp(fn,"D3DXLoadSurfaceFromSurface")?8:strstr(fn,"SaveSurface")?5:4);}return fixture_d3dx_real(c,fn);}
'''
    (out/'d3d9.m').write_text(source)
    flags=['-O1','-g','-w','-fsanitize=address,undefined','-fobjc-arc','-I',str(dst),'-I',str(HERE),'-I',str(root),'-DNFS_GAME=2','-I',str(HERE.parent/'runtime')]
    for src,obj,extra in [(out/'test.m',out/'fixture.o',[]),(out/'d3d9.m',out/'d3d9.o',[]),(dst/'boot.c',out/'boot.o',['-Dmain=private_boot_main'])]:
        r=subprocess.run(['clang',*flags,*extra,'-c',str(src),'-o',str(obj)],capture_output=True,text=True)
        if r.returncode:raise RuntimeError(r.stderr[-2500:])
    command=json.loads((root/'link_command.json').read_text());new=[];i=0
    while i<len(command):
        arg=command[i]
        if arg=='-o':new+=['-o',str(out/'test')];i+=2;continue
        if arg.endswith('/boot.c.o'):new.append(str(out/'boot.o'))
        elif arg.endswith('/d3d9.m.o'):new.append(str(out/'d3d9.o'))
        elif arg.endswith('/imports.c.o'):pass
        elif arg.endswith('.a') and Path(arg).parent==root:new.append(str(out/'fixture.o'))
        else:new.append(arg)
        i+=1
    new[1:1]=['-fsanitize=address,undefined']
    r=subprocess.run(new,capture_output=True,text=True)
    if r.returncode:raise RuntimeError(r.stderr[-2500:])
    return out/'test'


def main(*,out_name='d3dx_test'):
    root=HERE/'out/carbon'
    # A copied link manifest is not proof of a build in this checkout.
    build_root=root
    if not all((build_root/name).is_file() for name in
               ('link_command.json','NFSC.a','runtime/disabled_providers.m.o')):
        print('SKIP: private runtime build absent for this checkout');return 3
    command=json.loads((build_root/'link_command.json').read_text())
    archives=[Path(arg).resolve() for arg in command if arg.endswith('/NFSC.a')]
    assert len(archives)==1, 'private runtime guest archive entry missing or ambiguous'
    if archives[0] != (build_root/'NFSC.a').resolve():
        print('SKIP: private runtime link belongs to another checkout');return 3
    if 'private_d3dx_textures' not in selected_source(root/'runtime/d3d9.m'):print('SKIP: private D3DX build absent');return 3
    out=ignored_output(root/out_name);shutil.rmtree(out);out=ignored_output(out)  # fresh scratch each run
    binary=build(root,out)
    for index,broken in enumerate(['',*NAMES,'unsafe-hardlink']):
        folder=out/('broken_'+str(index) if broken else 'good');scratch=folder/'scratch';scratch.mkdir(parents=True,exist_ok=True)
        game=folder/'game';game.mkdir(exist_ok=True);outside=folder/'outside';outside.mkdir(exist_ok=True)
        keep=outside/'keep.bin';keep.write_bytes(b'outside scratch must survive')
        hardlink=scratch/'hardlink.dds';hardlink.unlink(missing_ok=True)
        linked=True
        try:os.link(keep,hardlink)
        except OSError as e:
            if e.errno!=errno.EPERM:raise
            linked=False
            print('HARDLINK CASE SKIP: file-link denied (EPERM); both endpoints are in the writable test directory, target outside save root')
            if broken=='unsafe-hardlink':
                (folder/'run.log').write_text('HARDLINK CONTROL SKIP: file-link denied (EPERM)\n')
                continue
        link=scratch/'link'
        if not link.exists():link.symlink_to(outside.resolve(),target_is_directory=True)
        env={**os.environ,'NFS_GAME_SCRATCH':str(scratch),'BOOT_USERDATA':str(scratch/'userdata'),'BOOT_HEADLESS':'1','NFS_AUDIO':'null','PRIVATE_D3DX_BROKEN':broken,'PRIVATE_D3DX_HARDLINK':str(int(linked))};env.pop('BOOT_DIAG',None)
        env.pop('PRIVATE_D3DX_UNSAFE_HARDLINK',None)
        if broken=='unsafe-hardlink':env['PRIVATE_D3DX_UNSAFE_HARDLINK']='1'
        r=subprocess.run([str(binary),str(scratch),str(game)],capture_output=True,text=True,env=env,timeout=30);(folder/'run.log').write_text(r.stdout+r.stderr)
        print((broken or 'good')+': exit='+str(r.returncode)+' '+r.stdout.strip()+r.stderr.strip());assert r.returncode==(1 if broken else 0)
        if broken:assert 'D3DX CHECK' in r.stderr
        if broken=='unsafe-hardlink':
            assert 'n==sizeof("outside scratch must survive")-1' in r.stderr and keep.read_bytes()!=b'outside scratch must survive'
        else:assert keep.read_bytes()==b'outside scratch must survive'
        assert not list(scratch.glob('.d3dx-save-*'))
        assert not (folder/'escape.dds').exists() and sorted(p.name for p in outside.iterdir())==['keep.bin'] and not list(game.iterdir())
    print('PRIVATE D3DX REGRESSION PASS six disabled imports rejected');return 0


if __name__=='__main__':sys.exit(main())
