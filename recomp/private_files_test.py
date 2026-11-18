"""Native private kernel32 import routing, scratch assets only; no game/GPU.

GIN good: five authenticated console files served at 48,000 Hz; RX-8 decel
220,762 decoded frames. Broken control removes the routing hook: PC RX-8
24,000 Hz / 36,732 frames, exit 1 versus exit 0. Default/off, missing source
and all other engine paths keep their exact PC bytes. RX-8/350Z/Viper native
engineaudio string selectors independently identify the five replacements.

Two runs in one tree: before the fix the 2nd FAILS (FileExistsError), after the fix the 2nd PASSES.
Good: 409 assertions across fifteen asset paths, including optional minimaps, attributes and atlas-only world-map packs.
World-map converter: old 127 entries fails; new 128 entries, 127 original blobs
unchanged, 1048576 pixel bytes with the pinned SHA256. Disabled modes are byte-identical.
Old fourteen-name table: attributes read fails check 349/exit 1; new table redirects 1/1.
Old twelve-name table: frontend opens fail versus 2/2 redirected; disabled reads 2/2 retail.
Old four-name table: check 129/exit 1 (0/2 HUD maps versus 2/2); good exits 0.
Old eight-name table: check 217/exit 1 (0/2 world maps versus 2/2); atlas enables
14/14 assets; unset/off/rockport/other enable 12/14 and leave both world maps stock.
Good: both pairs, L2RA-only, L5RA-only, unset, empty,
and a trailing game-root slash. L2RA-only leaves both L5RA opens stock.
USERDATA fixtures live under BOOT_USERDATA/Carbon; the shared-root placement
fails check 184/exit 1 when opening USERDATA/TRACKS/L5RA.BUN.
Broken: restore MW's quarantined audio fd substitution -> check 8/exit 1.
Its excluded provider's former zero return is supplied only by this mutant fixture.
Drop L5RA index/stream -> checks 41/63, exit 1.
Drop L2RA index/stream -> checks 85/107, exit 1.
Restore trailing-separator mismatch -> check 41/exit 1.
Either missing pair member and a nonregular member -> startup exit 2, before imports.
Exit 3 when private build artifacts are absent. No guest image/archive linked.
"""
import json
import shutil
import os
from pathlib import Path
import subprocess
import sys
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
from build_private import ignored_output
sys.path.insert(0, str(HERE / "private_runtime"))
from layers import selected_source
from private_render import body,replace_body
from private_files import verify_files
from private_carbon_music_test import carbon_sound_test_inputs

HARNESS=r'''#include "host.h"
#include <stdlib.h>
#include <sys/mman.h>
#include <stdarg.h>
#include <unistd.h>
#include <fcntl.h>
#include <sys/stat.h>
const uint32_t guest_func_addr[]={0};void (*const guest_func_ptr[])(Cpu*)={0};const unsigned guest_func_count=0;const uint32_t speed_entry=0;
/* This host-only fixture must never enter native startup completion. */
void f_0059B1B0(Cpu *c){(void)c;abort();}
const char speed_exe_fingerprint[]="",speed_exe_sha256[]="",speed_exe_region_sha256[4][65]={{0}};
const struct ExeRegion {const char *name;uint32_t rva,size;} speed_exe_regions[3]={{0}};
const struct {uint32_t slot;const char *name;} speed_imports[]={
 {0x100,"kernel32.dll!CreateFileA"},{0x104,"KERNEL32.dll!GetFileSize"},
 {0x108,"kernel32.dll!ReadFile"},{0x10c,"KERNEL32.dll!SetFilePointer"},
 {0x110,"kernel32.dll!CloseHandle"},{0x114,"kernel32.dll!GetFileTime"},
 {0x118,"kernel32.dll!WriteFile"},{0x11c,"kernel32.dll!FlushFileBuffers"},
 {0x120,"kernel32.dll!SetEndOfFile"}};const unsigned speed_import_count=9;
extern void threads_init(void),private_track_overlay_init(void);extern const char *game_dir;extern int private_resolve(const char*,char*,size_t);
static unsigned checks;
#define CHECK(v) do{++checks;if(!(v)){fprintf(stderr,"FILE CHECK %u line %d failed: %s\n",checks,__LINE__,#v);return 1;}}while(0)
static uint32_t api(Cpu*c,unsigned i,unsigned n,...){c->esp=0x100000;M32(c->esp)=0xfeed;va_list ap;va_start(ap,n);for(unsigned k=0;k<n;k++)M32(c->esp+4+4*k)=va_arg(ap,uint32_t);va_end(ap);host_import(c,0x100+4*i);if(c->esp!=0x100004+4*n){fprintf(stderr,"FILE bad stdcall stack\n");exit(2);}return c->eax;}
static uint32_t open_asset(Cpu*c,const char*p,uint32_t access,uint32_t disposition){strcpy((char*)G+0x4000,p);return api(c,0,7,0x4000u,access,1u,0u,disposition,0u,0u);}
/* Independently decode the Gnsu20 19-byte / 32-frame ADPCM units. */
static int gin_pcm(const uint8_t *p,unsigned size,unsigned expected) {
 unsigned frames;memcpy(&frames,p+24,4);if(frames!=expected)return 0;
 unsigned units=(frames+31)/32;if(units*19>size-32)return 0;
 unsigned base=size-units*19,written=0;double energy=0;
 const int coef[4][2]={{0,0},{240,0},{460,-208},{392,-220}};
 for(unsigned f=0;f<units;f++) {
  const uint8_t *b=p+base+f*19;uint32_t h;memcpy(&h,b,4);
  int a=(int16_t)(h&0xfff0),c=(int16_t)((h>>16)&0xfff0),shift=(h>>16)&15,index=h&3;
  if(written++<frames)energy+=(double)a*a;if(written++<frames)energy+=(double)c*c;
  for(unsigned j=0;j<30;j++) {
   int nib=(b[4+j/2]>>(j%2?0:4))&15;if(nib>7)nib-=16;
   int v=(nib*(1<<(20-shift))+c*coef[index][0]+a*coef[index][1])>>8;
   if(v>32767)v=32767;if(v<-32768)v=-32768;
   if(written++<frames)energy+=(double)v*v;a=c;c=v;
  }
 }
 return written>=frames && written-frames<32 && energy>0;
}
int main(int argc,char**argv){private_track_overlay_init();CHECK(argc==5||argc==6);int overlay=atoi(argv[4]);game_dir=argv[2];char mapped[4096],guest[512],image[4096];struct stat st;
 snprintf(guest,sizeof guest,"C:\\NFSMW/%s",argv[3]);private_resolve(guest,mapped,sizeof mapped);snprintf(image,sizeof image,"%s/%s",game_dir,argv[3]);CHECK(!strcmp(mapped,image)&&stat(mapped,&st)==0&&S_ISREG(st.st_mode));
 game_dir=argv[1];int z=open("/dev/null",O_RDONLY);CHECK(z>=0);CHECK(dup2(z,0)==0);if(z!=0)close(z);
 G=mmap(NULL,1ull<<32,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANON,-1,0);CHECK(G!=MAP_FAILED);threads_init();Cpu c={0};c.fs_base=0x7000;
 if(argc==6) {
  const char *names[]={"en_dcl_11.gin","en_acl_11.gin","en_acl_25.gin","en_acl_68.gin","en_dcl_68.gin"};
  const unsigned counts[]={220762,438417,634776,591950,519000};
  for(unsigned i=0;i<5;i++) {
   char name[128];snprintf(name,sizeof name,"SOUND/ENGINE/GIN/%s",names[i]);
   uint32_t h=open_asset(&c,name,0x80000000u,3);CHECK(h!=UINT32_MAX);
   unsigned size=api(&c,1,2,h,0u);CHECK(size>32 && size<0x100000);
   CHECK(api(&c,2,5,h,0x200000u,size,0x4100u,0u)==1 && M32(0x4100)==size);
   uint8_t *p=G+0x200000;unsigned rate=M32(0x20001c),frames=M32(0x200018);
   printf("GIN %s rate=%u decoded_frames=%u\n",names[i],rate,frames);
   if(overlay) {CHECK(rate==48000 && frames==counts[i]);CHECK(gin_pcm(p,size,counts[i]));}
   else {
    char pcpath[4096];CHECK(private_resolve(name,pcpath,sizeof pcpath)==0);
    FILE *pc=fopen(pcpath,"rb");CHECK(pc);uint8_t *original=malloc(size);CHECK(original);
    CHECK(fread(original,1,size,pc)==size && fgetc(pc)==EOF && !memcmp(p,original,size));fclose(pc);free(original);
   }
   CHECK(api(&c,4,1,h)==1);
  }
  /* Similar basenames and writable/save paths never receive a console file. */
  const char *untouched[]={"SOUND/ENGINE/GIN/en_dcl_25.gin","SOUND/ENGINE/GIN/en_acl_12.gin","SOUND/ENGINE/GIN/en_acl_11.gin.extra","Assets/en_acl_11.gin","USERDATA/SOUND/ENGINE/GIN/en_acl_11.gin"};
  for(unsigned i=0;i<5;i++) {
   char host[4096];private_resolve(untouched[i],host,sizeof host);char before[4096];strcpy(before,host);
   int carbon_gin_path(char*,size_t,uint32_t,uint32_t);
   CHECK(carbon_gin_path(host,sizeof host,0x80000000u,3)==0 && !strcmp(host,before));
  }
  printf("GIN PASS checks=%u selected=%d\n",checks,overlay);return 0;
 }
 char actual[4096],expected[4096];private_resolve("C:\\NFSMW/ASSETS\\sample.BIN",actual,sizeof actual);snprintf(expected,sizeof expected,"%s/Assets/Sample.bin",game_dir);CHECK(!strcmp(actual,expected));
 uint32_t h=open_asset(&c,"C:\\NFSMW/ASSETS\\sample.BIN",0x80000000u,3);CHECK(h!=UINT32_MAX);
 M32(0x4100)=0xdead;CHECK(api(&c,1,2,h,0x4100u)==16&&M32(0x4100)==0);
 CHECK(api(&c,2,5,h,0x4200u,6u,0x4100u,0u)==1);CHECK(M32(0x4100)==6&&!memcmp(G+0x4200,"012345",6));
 CHECK(api(&c,3,4,h,2u,0u,0u)==2);CHECK(api(&c,2,5,h,0x4200u,4u,0x4100u,0u)==1&&!memcmp(G+0x4200,"2345",4));
 CHECK(api(&c,3,4,h,(uint32_t)-2,0u,2u)==14);CHECK(api(&c,2,5,h,0x4200u,8u,0x4100u,0u)==1&&M32(0x4100)==2&&!memcmp(G+0x4200,"ef",2));
 CHECK(api(&c,5,4,h,0x4400u,0x4408u,0x4410u)==1);CHECK(M64(0x4410)!=0);
 uint32_t second=open_asset(&c,"Assets/Sample.bin",0x80000000u,3);CHECK(second!=UINT32_MAX&&second!=h);CHECK(api(&c,4,1,h)==1);CHECK(api(&c,1,2,second,0u)==16);CHECK(api(&c,4,1,h)==0);CHECK(api(&c,4,1,second)==1);
 CHECK(api(&c,1,2,second,0u)==UINT32_MAX);CHECK(api(&c,2,5,second,0x4200u,8u,0x4100u,0u)==0&&M32(0x4100)==0);
 CHECK(open_asset(&c,"Assets/Missing.bin",0x80000000u,3)==UINT32_MAX);
 CHECK(open_asset(&c,"Assets/Sample.bin",0x40000000u,2)==UINT32_MAX);CHECK(open_asset(&c,"Assets/New.bin",0x80000000u,1)==UINT32_MAX);
 // USERDATA remains writable through the very same kernel32 fd table.
 h=open_asset(&c,"C:\\USERDATA\\scratch.bin",0xc0000000u,2);CHECK(h!=UINT32_MAX);memcpy(G+0x4200,"ours",4);
 CHECK(api(&c,6,5,h,0x4200u,4u,0x4100u,0u)==1&&M32(0x4100)==4);CHECK(api(&c,7,1,h)==1);CHECK(api(&c,3,4,h,2u,0u,0u)==2);CHECK(api(&c,8,1,h)==1);CHECK(api(&c,1,2,h,0u)==2);CHECK(api(&c,4,1,h)==1);
 h=open_asset(&c,"USERDATA/scratch.bin",0x80000000u,3);CHECK(h!=UINT32_MAX);CHECK(api(&c,2,5,h,0x4200u,8u,0x4100u,0u)==1&&M32(0x4100)==2&&!memcmp(G+0x4200,"ou",2));CHECK(api(&c,4,1,h)==1);
 // A genuine native open is allowed to return fd zero: the table stores fd+1.
 close(0);h=open_asset(&c,"Assets/Sample.bin",0x80000000u,3);CHECK(h!=UINT32_MAX);CHECK(api(&c,1,2,h,0u)==16);CHECK(api(&c,4,1,h)==1);
 const char *paths[]={"C:\\NFSMW//tRaCkS\\./l5ra.bun","tracks\\sTrEaMl5rA.BuN","tracks/L2RA.BUN","tracks/streaml2ra.bun","TRACKS/L2RA/MINI_MAP_CASINOTOWN_LOCKED.bin","tracks/l2ra/mini_map_casinotown_unlocked.BIN","tracks/l5ra/mini_map_casinotown_locked.bin","tracks/l5ra/mini_map_casinotown_unlocked.bin","tracks/l5ra/trackmaps.BIN","TRACKS/L2RA/TrackMaps.bin","gLoBaL\\gameplay.BIN","GLOBAL/gameplay.lzc","gLoBaL\\GlobalB.bun","GLOBAL/GLOBALB.LZC","gLoBaL\\attributes.BIN"};
 const char *originals[]={"stock-index","stock-stream!","stock-L2-index","stock-L2-stream!","stock-map-locked","stock-map-unlocked","stock-L5-map-locked","stock-L5-map-unlocked","stock-L5-worldmap","stock-L2-worldmap","stock-gameplay","stock-gameplay-lzc","stock-frontend","stock-frontend-lzc","stock-attributes"};
 const char *replacements[]={"replacement-index-0123456789", "replacement-stream-abcdefghijklmnopqrstuvwxyz","region-index-0123456789","region-stream-abcdefghijklmnopqrstuvwxyz","map-locked-0123456789","map-unlocked-0123456789","L5-map-locked-0123456789","L5-map-unlocked-0123456789","L5-worldmap-0123456789","L2-worldmap-0123456789","gameplay-0123456789","gameplay-lzc-0123456789","frontend-0123456789","frontend-lzc-0123456789","attributes-0123456789"};
 for(unsigned i=0;i<15;i++){
   const char *bytes=(overlay & (1u<<i))?replacements[i]:originals[i];uint32_t size=(uint32_t)strlen(bytes);
   h=open_asset(&c,paths[i],0x80000000u,3);CHECK(h!=UINT32_MAX);
   CHECK(api(&c,1,2,h,0u)==size);
   CHECK(api(&c,2,5,h,0x4200u,7u,0x4100u,0u)==1&&M32(0x4100)==7&&!memcmp(G+0x4200,bytes,7));
   CHECK(api(&c,3,4,h,3u,0u,0u)==3);
   CHECK(api(&c,2,5,h,0x4200u,5u,0x4100u,0u)==1&&M32(0x4100)==5&&!memcmp(G+0x4200,bytes+3,5));
   CHECK(api(&c,3,4,h,(uint32_t)-4,0u,2u)==size-4);
   CHECK(api(&c,2,5,h,0x4200u,8u,0x4100u,0u)==1&&M32(0x4100)==4&&!memcmp(G+0x4200,bytes+size-4,4));
   CHECK(api(&c,2,5,h,0x4200u,8u,0x4100u,0u)==1&&M32(0x4100)==0);
   CHECK(api(&c,3,4,h,(uint32_t)-2,0u,1u)==size-2);
   CHECK(api(&c,2,5,h,0x4200u,8u,0x4100u,0u)==1&&M32(0x4100)==2&&!memcmp(G+0x4200,bytes+size-2,2));
   CHECK(api(&c,6,5,h,0x4200u,2u,0x4100u,0u)==0&&M32(0x4100)==0);
   CHECK(api(&c,8,1,h)==0);CHECK(api(&c,4,1,h)==1);
   for(uint32_t disposition=1;disposition<=5;disposition++){
     CHECK(open_asset(&c,paths[i],0xc0000000u,disposition)==UINT32_MAX);
     if(disposition!=3)CHECK(open_asset(&c,paths[i],0x80000000u,disposition)==UINT32_MAX);
   }
 }
 const char *unchanged[]={"Tracks/Other.bin","Assets/L5RA.BUN","Tracks/L5RA.BUN.extra","USERDATA/TRACKS/L5RA.BUN","Assets/L2RA.BUN","Tracks/L2RA.BUN.extra","USERDATA/TRACKS/L2RA.BUN","Tracks/L5RB.BUN","Assets/attributes.bin","USERDATA/GLOBAL/ATTRIBUTES.BIN"};
 for(unsigned i=0;i<10;i++){
   h=open_asset(&c,unchanged[i],0x80000000u,3);CHECK(h!=UINT32_MAX);
   CHECK(api(&c,1,2,h,0u)==9);
   CHECK(api(&c,2,5,h,0x4200u,9u,0x4100u,0u)==1&&M32(0x4100)==9&&!memcmp(G+0x4200,"unchanged",9));
   CHECK(api(&c,4,1,h)==1);
 }
 printf("PRIVATE FILE PASS checks=%u shared_import_table=1 asset_readonly=1 native_fd_zero=1 overlay=%d\n",checks,overlay);return 0;}
'''


def build(root,out,broken):
    dst=root/'runtime';source=selected_source(dst/'boot.c')
    entry = body(source,'main')
    assert entry.index('\n    settings_init();') < entry.index('\n    private_track_overlay_init();')
    if broken=='fake_fd':
        opener=body(source,'file_open')
        native='    fd = open(s ? s->temp : host, s ? fl & ~(O_CREAT | O_EXCL) : fl, 0644);'
        assert opener.count(native)==1
        # Restore just the MW substitution, preserving the current save policy.
        opener=opener.replace(native,'''    fd = !s && fl == O_RDONLY ? x360audio_open(win, host) : -1;
    if (fd < 0) fd = open(s ? s->temp : host, s ? fl & ~(O_CREAT | O_EXCL) : fl, 0644);''')
        source=replace_body(source,'file_open',opener)
    elif broken in ('index','stream','region_index','region_stream'):
        matcher=body(source,'private_track_overlay_path')
        old='if (strcasecmp(rel, private_track_names[i])) continue;'
        assert matcher.count(old)==1
        matcher=matcher.replace(old,'if (i == '+str({'index':0,'stream':1,'region_index':2,'region_stream':3}[broken])+' || strcasecmp(rel, private_track_names[i])) continue;')
        source=replace_body(source,'private_track_overlay_path',matcher)
    elif broken=='old_map_table':
        # Restore the original four-name table and its two loop bounds.
        names='''"TRACKS/L2RA.BUN", "TRACKS/STREAML2RA.BUN",
    "TRACKS/L2RA/MINI_MAP_CASINOTOWN_LOCKED.bin",
    "TRACKS/L2RA/MINI_MAP_CASINOTOWN_UNLOCKED.bin",
    "TRACKS/L5RA/MINI_MAP_CASINOTOWN_LOCKED.bin",
    "TRACKS/L5RA/MINI_MAP_CASINOTOWN_UNLOCKED.bin",
    "TRACKS/L5RA/TrackMaps.bin", "TRACKS/L2RA/TrackMaps.bin",
    "GLOBAL/GAMEPLAY.BIN", "GLOBAL/GAMEPLAY.LZC",
    "GLOBAL/GLOBALB.BUN", "GLOBAL/GLOBALB.LZC",
    "GLOBAL/ATTRIBUTES.BIN"'''
        assert source.count(names)==1
        source=source.replace(names,'"TRACKS/L2RA.BUN", "TRACKS/STREAML2RA.BUN"')
        source=source.replace('private_track_paths[15]', 'private_track_paths[4]')
        init=body(source,'private_track_overlay_init').replace('pair < 8;', 'pair < 2;')
        source=replace_body(source,'private_track_overlay_init',init)
        matcher=body(source,'private_track_overlay_path').replace('i < 15;', 'i < 4;')
        source=replace_body(source,'private_track_overlay_path',matcher)
    elif broken=='old_art_table':
        source=source.replace('pair < 8;', 'pair < 4;').replace('i < 15;', 'i < 8;')
    elif broken=='old_gameplay_table':
        source=source.replace('i < 15;', 'i < 10;')
    elif broken=='old_frontend_table':
        source=source.replace('pair < 8;', 'pair < 6;').replace('i < 15;', 'i < 12;')
    elif broken=='old_attributes_table':
        source=source.replace('i < 15;', 'i < 14;')
    elif broken=='trailing':
        old="    while (*rel == '/') ++rel;"
        assert source.count(old)==1
        source=source.replace(old,'')
    elif broken=='pc_gin':
        old='int gin = carbon_gin_path(host, n, access, disp);'
        assert source.count(old)==1
        source=source.replace(old,'int gin = 0; /* original PC routing */')
    fixture=HARNESS
    if broken=='fake_fd':
        # Whole-file selection omits this provider from production. Reproduce
        # its former quarantined return only for the original negative control.
        fixture+='\nint x360audio_open(const char *win,const char *host){(void)win;(void)host;return 0;}\n'
    (out/'boot.c').write_text(source);(out/'test.c').write_text(fixture)
    flags=['-O1','-g','-w','-I',str(dst),'-I',str(HERE),'-I',str(root),'-DNFS_GAME=2','-I',str(HERE.parent/'runtime')]
    for src,obj,extra in [(out/'test.c',out/'fixture.o',[]),(out/'boot.c',out/'boot.o',['-Dmain=private_boot_main'])]:
        r=subprocess.run(['clang',*flags,*extra,'-c',str(src),'-o',str(obj)],capture_output=True,text=True)
        if r.returncode:raise RuntimeError(r.stderr[-2000:])
    command=json.loads((root/'link_command.json').read_text());new=[];i=0
    archives=[Path(arg) for arg in command if Path(arg).name=='NFSC.a']
    assert len(archives)==1, 'private runtime guest archive entry missing or ambiguous'
    archive=archives[0]
    # Copied Carbon outputs keep the original checkout's absolute link paths.
    # Use the staged objects and libraries from the checkout under test.
    build_checkout=archive.parents[3]  # recomp/out/carbon/NFSC.a
    while i<len(command):
        arg=command[i]
        path=Path(arg)
        if arg=='-o':new+=['-o',str(out/'test')];i+=2;continue
        if path==archive:new.append(str(out/'fixture.o'))
        elif path==archive.parent/'runtime/boot.c.o':new.append(str(out/'boot.o'))
        elif path==archive.parent/'runtime/imports.c.o':pass
        elif path.is_absolute() and path.is_relative_to(build_checkout):
            new.append(str(HERE.parent/path.relative_to(build_checkout)))
        else:new.append(arg)
        i+=1
    r=subprocess.run(new,capture_output=True,text=True)
    if r.returncode:raise RuntimeError(r.stderr[-2000:])
    return out/'test'


def pack_fixture(carbon_root):
    import hashlib
    import struct
    import private_worldmap_art as art
    cc=art.cc
    sys.path.insert(0,str(HERE.parent/'tools_snapshot/worldmerge'))
    from merge import DEFAULT_MW
    mw=DEFAULT_MW/'L2RA/TrackMaps.bin'
    target=carbon_root/'TRACKS/L5RA/TrackMaps.bin'
    if not mw.is_file() or not target.is_file():
        print('SKIP: private world-map source packs absent');return False
    source,stock=mw.read_bytes(),target.read_bytes()
    before=cc.index(stock,0x33310003)
    def check(result):
        rows=cc.index(result,0x33310003)
        assert len(rows)==128, 'world-map entry count: expected 128'
        assert rows==sorted(rows) and len({e[0] for e in rows})==128
        entry=next(e for e in rows if e[0]==0x0F365871)
        assert entry==(0x0F365871,0x001FFE80,0x00100094,0x00100094,0,0)
        assert [e for e in rows if e[0]!=entry[0]]==before
        hashes=list(struct.iter_unpack('<II',cc.payload(result,0x33310002)))
        assert hashes==[(e[0],0) for e in rows]
        for e in before:
            assert result[e[1]:e[1]+e[2]]==stock[e[1]:e[1]+e[2]]
        blob=cc.unpack_entry(result,entry)
        assert len(blob[:-148])==1048576
        assert hashlib.sha256(blob[:-148]).hexdigest()==art.PIXEL_SHA256
        native=next(cc.unpack_entry(source,e) for e in cc.index(source,0x33310003) if e[0]==entry[0])
        assert blob[:-148]==native[:-156]
        r=native[-156:-24];v=blob[-148:-24]
        assert v[:12]==r[:12] and v[12:20]==r[36:44]
        assert v[24:48]==r[52:76] and v[48:51]==r[76:79] and v[60:88]==r[88:116]
        donor=next(cc.unpack_entry(stock,e) for e in before if e[0]==cc.name_hash('TRACK_MAP_UNLOCK_1'))
        assert v[51:60]==donor[-148:-24][51:60]
        assert cc.u32(v,20)==0x00B35580 and struct.unpack_from('<HH',v,40)==(1024,1024)
        assert v[46]==0x24 and v[88:]==bytes([35])+b'TRACK_MAP\0'.ljust(35,b'\0')
        assert blob[-24:]==bytes(12)+b'DXT3'+bytes(8)
        assert cc.payload(result,0x33310001)==cc.payload(stock,0x33310001)
        assert cc.u32(result,0x44)==cc.u32(stock,0x44)+32
        gap=0x10DC
        assert cc.u32(result,gap)==0 and cc.u32(result,gap+4)==28
        assert cc.u32(result,4)==len(result)-8
        for cid in (0xB3320000,0x33320002):
            off,size=cc.find(stock,cid);assert cc.u32(result,off+4)==size+len(blob)
        assert len(list(cc.walk(result)))==len(list(cc.walk(stock)))
    check(art.convert(source,stock,'atlas'))
    try:check(stock)
    except AssertionError as error:
        assert 'entry count' in str(error)
        print('old world-map pack rejected: entries=127; fixed=128 preserved=127 pixels=1048576')
    else:raise AssertionError('old world-map pack accepted')
    for mode in (None,'','off','rockport','other'):
        assert art.convert(b'',stock,mode)==stock
    return True


def gin_regression(root, out, image):
    import hashlib
    inputs = carbon_sound_test_inputs(out / 'gin-import')
    if not inputs:
        print('SKIP: private GIN source assets absent')
        return False
    pc, console = inputs
    # Resolve the game's own named engineaudio strings, rather than deriving
    # the expected coverage from the runtime's replacement table.
    sys.path.insert(0, str(HERE.parent / 'tools'))
    from setup_kit.car_audio import AudioAttributes, ENGINE
    from setup_kit.car_convert import hash32
    attributes = AudioAttributes((pc / 'GLOBAL/attributes.bin').read_bytes())
    wanted = {'maz_rx8': ('en_acl_11.gin', 'en_dcl_11.gin'),
              'nis_350z_a': ('en_acl_25.gin', 'en_dcl_25.gin'),
              'dodg_viper_a': ('en_acl_68.gin', 'en_dcl_68.gin')}
    for name, pair in wanted.items():
        selected = tuple(attributes.field(ENGINE, hash32(name), field)['values'][0]['text']
                         for field in (0x2cee0a54, 0x3a7c2f3d))
        assert selected == pair
    print('GIN selectors: RX-8=11, 350Z=25, Viper=68; 350Z deceleration stays PC')
    snapshots = {p: hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in (pc / 'SOUND/ENGINE/GIN').iterdir() if p.is_file()}
    env = dict(os.environ, NFS_X360_FILES=str(console), NFS_CARBON_X360_GIN='on',
               BOOT_USERDATA=str(out / 'gin-user'), NFS_ROOTS=str(out / 'no-roots'),
               BOOT_HEADLESS='1', NFS_AUDIO='null')
    env.pop('BOOT_DIAG', None)
    env.pop('NFS_CARBON_TRACK_OVERLAY', None)
    env.pop('NFS_CARBON_X360_MUSIC', None)
    for broken in ('good', 'pc_gin'):
        folder = out / ('gin-' + broken)
        folder.mkdir()
        binary = build(root, folder, broken)

        def run(label, selected, **changes):
            result = subprocess.run([str(binary), str(pc), str(pc), image.name, str(selected), 'gin'],
                                    capture_output=True, text=True, env=dict(env, **changes), timeout=30)
            (folder / (label + '.log')).write_text(result.stdout + result.stderr)
            print('GIN ' + broken + '/' + label + ': exit=' + str(result.returncode) + ' ' +
                  result.stdout.strip() + result.stderr.strip())
            return result

        r = run('enabled', 1)
        assert r.returncode == (0 if broken == 'good' else 1)
        assert 'rate=48000 decoded_frames=220762' in r.stdout if broken == 'good' else \
               'rate=24000 decoded_frames=36732' in r.stdout
        if broken == 'good':
            for value in ('', 'off', '0', 'pc'):
                assert run('mode-' + str(value), 0, NFS_CARBON_X360_GIN=value).returncode == 0
            absent = out / 'gin-absent'
            absent.mkdir()
            assert run('absent-source', 0, NFS_X360_FILES=str(absent)).returncode == 0
            unset = dict(env)
            unset.pop('NFS_CARBON_X360_GIN')
            r = subprocess.run([str(binary), str(pc), str(pc), image.name, '0', 'gin'],
                               capture_output=True, text=True, env=unset, timeout=30)
            assert r.returncode == 0, r.stderr[-1000:]
    assert all(hashlib.sha256(p.read_bytes()).hexdigest() == digest for p, digest in snapshots.items())
    return True


def main():
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
    out=ignored_output(root/'files_test');shutil.rmtree(out);out=ignored_output(out)  # fresh scratch each run
    image=Path(json.loads((root/'image.json').read_text())['exe'])
    if not image.is_file():print('SKIP: private executable absent');return 3
    if not pack_fixture(image.parent):return 3
    verify_files(json.loads((root/'runtime_isolation.json').read_text()))
    for required in ('handle_fd','private_track_overlay_init','private_track_overlay_path'):
        try:verify_files({'boot.c':[{'name':required}]})
        except ValueError:pass
        else:raise AssertionError('disabled required file body accepted: '+required)
    for broken in ('good','fake_fd','index','stream','region_index','region_stream','trailing','old_map_table','old_art_table','old_gameplay_table','old_frontend_table','old_attributes_table'):
        folder=out/broken;folder.mkdir(exist_ok=True)
        assets=folder/'game/Assets';assets.mkdir(parents=True,exist_ok=True)
        sample=assets/'Sample.bin';sample.write_bytes(b'0123456789abcdef')
        originals={'Tracks/L5RA.BUN':b'stock-index','Tracks/STREAML5RA.BUN':b'stock-stream!',
                   'Tracks/L2RA/MINI_MAP_CASINOTOWN_LOCKED.bin':b'stock-map-locked',
                   'Tracks/L2RA/MINI_MAP_CASINOTOWN_UNLOCKED.bin':b'stock-map-unlocked',
                   'Tracks/L5RA/MINI_MAP_CASINOTOWN_LOCKED.bin':b'stock-L5-map-locked',
                   'Tracks/L5RA/MINI_MAP_CASINOTOWN_UNLOCKED.bin':b'stock-L5-map-unlocked',
                   'Tracks/L5RA/TrackMaps.bin':b'stock-L5-worldmap',
                   'Tracks/L2RA/TrackMaps.bin':b'stock-L2-worldmap',
                   'Global/gameplay.bin':b'stock-gameplay',
                   'Global/gameplay.lzc':b'stock-gameplay-lzc',
                   'Global/GlobalB.bun':b'stock-frontend',
                   'Global/GlobalB.lzc':b'stock-frontend-lzc',
                   'Global/attributes.bin':b'stock-attributes',
                   'Tracks/L2RA.BUN':b'stock-L2-index','Tracks/STREAML2RA.BUN':b'stock-L2-stream!',
                   'Assets/attributes.bin':b'unchanged','Assets/L2RA.BUN':b'unchanged','Tracks/L2RA.BUN.extra':b'unchanged','Tracks/L5RB.BUN':b'unchanged',
                   'Tracks/Other.bin':b'unchanged','Assets/L5RA.BUN':b'unchanged','Tracks/L5RA.BUN.extra':b'unchanged'}
        replacements={'TRACKS/L5RA.BUN':b'replacement-index-0123456789',
                      'TRACKS/STREAML5RA.BUN':b'replacement-stream-abcdefghijklmnopqrstuvwxyz',
                      'TRACKS/L2RA.BUN':b'region-index-0123456789',
                      'TRACKS/STREAML2RA.BUN':b'region-stream-abcdefghijklmnopqrstuvwxyz',
                      'TRACKS/L2RA/MINI_MAP_CASINOTOWN_LOCKED.bin':b'map-locked-0123456789',
                      'TRACKS/L2RA/MINI_MAP_CASINOTOWN_UNLOCKED.bin':b'map-unlocked-0123456789',
                      'TRACKS/L5RA/MINI_MAP_CASINOTOWN_LOCKED.bin':b'L5-map-locked-0123456789',
                      'TRACKS/L5RA/MINI_MAP_CASINOTOWN_UNLOCKED.bin':b'L5-map-unlocked-0123456789',
                      'TRACKS/L5RA/TrackMaps.bin':b'L5-worldmap-0123456789',
                      'TRACKS/L2RA/TrackMaps.bin':b'L2-worldmap-0123456789',
                      'GLOBAL/GAMEPLAY.BIN':b'gameplay-0123456789',
                      'GLOBAL/GAMEPLAY.LZC':b'gameplay-lzc-0123456789',
                      'GLOBAL/GLOBALB.BUN':b'frontend-0123456789',
                      'GLOBAL/GLOBALB.LZC':b'frontend-lzc-0123456789',
                      'GLOBAL/ATTRIBUTES.BIN':b'attributes-0123456789',
                      'TRACKS/Other.bin':b'must-not-be-used','TRACKS/L5RB.BUN':b'must-not-be-used'}
        snapshots={sample:b'0123456789abcdef'}
        for base,files in ((folder/'game',originals),(folder/'overlay',replacements),
                           (folder/'userdata/Carbon',{'TRACKS/L5RA.BUN':b'unchanged','TRACKS/L2RA.BUN':b'unchanged','GLOBAL/ATTRIBUTES.BIN':b'unchanged'})):
            for name,data in files.items():
                path=base/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data);snapshots[path]=data
        binary=build(root,folder,broken)
        env={**os.environ,'BOOT_USERDATA':str(folder/'userdata'),'BOOT_HEADLESS':'1','NFS_AUDIO':'null'}
        env.pop('BOOT_DIAG',None)
        env.pop('NFS_CARBON_TRACK_OVERLAY',None)
        env.pop('NFS_CARBON_WORLD_PROBE',None)
        def run(label,overlay_root=None,enabled=32767,game_root=None,mode='atlas'):
            child_env=dict(env)
            child_env.pop('NFS_CARBON_MINIMAP',None)
            if mode is not None:child_env['NFS_CARBON_MINIMAP']=mode
            if overlay_root is not None:child_env['NFS_CARBON_TRACK_OVERLAY']=str(overlay_root)
            result=subprocess.run([str(binary),game_root or str(folder/'game'),str(image.parent),image.name,str(int(enabled))],
                                  capture_output=True,text=True,env=child_env,timeout=30)
            (folder/(label+'.log')).write_text(result.stdout+result.stderr)
            print(broken+'/'+label+': exit='+str(result.returncode)+' '+result.stdout.strip()+result.stderr.strip())
            assert all(path.read_bytes()==data for path,data in snapshots.items())
            assert not (assets/'New.bin').exists()
            return result
        r=run('enabled',folder/'overlay',game_root=str(folder/'game')+'/' if broken=='trailing' else None)
        assert r.returncode==(0 if broken=='good' else 1)
        if broken=='fake_fd':assert 'api(&c,1,2,h,0x4100u)==16' in r.stderr
        elif broken!='good':assert 'api(&c,1,2,h,0u)==size' in r.stderr
        if broken=='good':
            for mode in (None,'off','rockport','other'):
                assert run('mode-'+str(mode),folder/'overlay',enabled=31999,mode=mode).returncode==0
            for region in ('L5RA','L2RA'):
                only=folder/('one-art-'+region)
                for name in ('TRACKS/L2RA.BUN','TRACKS/STREAML2RA.BUN','TRACKS/'+region+'/TrackMaps.bin'):
                    path=only/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(replacements[name])
                assert run('one-art-'+region,only,enabled=12).returncode==0
            only=folder/'only-attributes'
            for name in ('TRACKS/L2RA.BUN','TRACKS/STREAML2RA.BUN','GLOBAL/ATTRIBUTES.BIN'):
                path=only/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(replacements[name])
            assert run('only-attributes',only,enabled=12 | (1 << 14)).returncode==0
            assert run('trailing',folder/'overlay',game_root=str(folder/'game')+'/').returncode==0
            for base,mask in (('L2RA',12),('L5RA',3)):
                only=folder/('only-'+base)/'TRACKS';only.mkdir(parents=True,exist_ok=True)
                for name in (base+'.BUN','STREAM'+base+'.BUN'):
                    (only/name).write_bytes(replacements['TRACKS/'+name])
                assert run('only-'+base,only.parent,enabled=mask).returncode==0
            # Optional means each pack can be present independently; an absent
            # companion must continue to use its stock file.
            for index,variant in enumerate(('LOCKED','UNLOCKED')):
                only=folder/('one-map-'+variant)
                for name in ('TRACKS/L2RA.BUN','TRACKS/STREAML2RA.BUN',
                             'TRACKS/L2RA/MINI_MAP_CASINOTOWN_'+variant+'.bin'):
                    path=only/name;path.parent.mkdir(parents=True,exist_ok=True)
                    path.write_bytes(replacements[name])
                assert run('one-map-'+variant,only,enabled=12 | (1 << (4+index))).returncode==0
            assert run('disabled',enabled=False).returncode==0
            assert run('empty','',enabled=False).returncode==0
            for missing in ('L5RA.BUN','STREAML5RA.BUN','L2RA.BUN','STREAML2RA.BUN'):
                incomplete=folder/('missing-'+missing);tracks=incomplete/'TRACKS';tracks.mkdir(parents=True,exist_ok=True)
                for name in (('L2RA.BUN','STREAML2RA.BUN') if 'L2' in missing else ('L5RA.BUN','STREAML5RA.BUN')):
                    if name!=missing:(tracks/name).write_bytes(b'synthetic')
                r=run('missing-'+missing,incomplete)
                assert r.returncode==2 and missing in r.stderr and 'readable regular pair required' in r.stderr
            for missing in ('GAMEPLAY.BIN','GAMEPLAY.LZC','GLOBALB.BUN','GLOBALB.LZC'):
                only=folder/('missing-'+missing)
                companion={'GAMEPLAY.BIN':'GAMEPLAY.LZC','GAMEPLAY.LZC':'GAMEPLAY.BIN',
                           'GLOBALB.BUN':'GLOBALB.LZC','GLOBALB.LZC':'GLOBALB.BUN'}[missing]
                for name in ('TRACKS/L2RA.BUN','TRACKS/STREAML2RA.BUN','GLOBAL/'+companion):
                    path=only/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(replacements[name])
                r=run('missing-'+missing,only)
                assert r.returncode==2 and missing in r.stderr and 'readable regular pair required' in r.stderr
            for kind in ('directory','fifo'):
                only=folder/('invalid-attributes-'+kind)
                for name in ('TRACKS/L2RA.BUN','TRACKS/STREAML2RA.BUN'):
                    path=only/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(replacements[name])
                path=only/'GLOBAL/ATTRIBUTES.BIN';path.parent.mkdir()
                if kind=='directory':path.mkdir()
                else:os.mkfifo(path)
                r=run('invalid-attributes-'+kind,only)
                assert r.returncode==2 and 'ATTRIBUTES.BIN' in r.stderr
            invalid=folder/'invalid/TRACKS';invalid.mkdir(parents=True,exist_ok=True)
            (invalid/'L5RA.BUN').mkdir(exist_ok=True)
            r=run('nonregular',invalid.parent)
            assert r.returncode==2 and 'readable regular pair required' in r.stderr
    if not gin_regression(root,out,image):
        return 3
    print('PRIVATE FILE REGRESSION PASS: old map/art tables rejected; 15/15 atlas assets, 13/15 in other modes; five GINs decoded at 48 kHz; PC RX-8 control rejected; originals unchanged');return 0


if __name__=='__main__':sys.exit(main())
