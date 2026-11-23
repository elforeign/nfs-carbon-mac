"""Own userdata root and retail old-save enumeration, without a game.

Good: 4 roots (two images x BOOT_USERDATA set/unset); native/provider counts
missing=0, empty=1, one-profile=2; native cash bonus=0/10000, message=84B62CBF.
Read/write attempts=0; directory tree unchanged. Broken shared-root, file-open
and file-write variants each exit 1; good exits 0. Underground 2 delegates once.
Saved forced-bonus setting: missing prior save awards 10000; original awards 0
(acceptance exit 1). A real prior save still awards 10000, never 20000.
Exit 3 without the pinned Carbon image and generated outputs.
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
PRIVATE = HERE / 'private_runtime'
IMAGE_SHA = 'baaaaec33873d4ba7e4dbae6a5212049ffdcf9679a35d865d7625b4189952fd3'
BASELINES = {
    0x00716690: 'e51ce144a3197184084caba62105a90c0ab17fad8b9df0ac2a7c4ae7ce636f81',
    0x0058E370: '9917bb79c50afa362ab0803c811fa261fcd616310e20d0834a7dedfaef1659f3',
    0x005B7160: 'de14b918f362b721c74e36e96cdd7af4e6530a36c54fda70eb0a5623b37df650',
    0x00579C10: '73763b9127fe4960ae4767310f77e2b18d3f33b37179c13a38176cff036d6fa2',
    0x005D0D40: '9acf20f1dcd48a6a1e32cad31a2a8f8d4e8382990a6cac8dfb7ea1b79dd76ae9',
}

ROOT_DRIVER = r'''
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include "game_select.h"
ROOT_FUNCTION
int main(int argc,char **argv) {
 if(argc!=2 || strcmp(userdata_dir(),argv[1])) return 1;
 struct stat s;if(stat(argv[1],&s)||!S_ISDIR(s.st_mode)) return 1;
 return 0;
}
'''

HARNESS = r'''
#include "funcs.h"
#include "host.h"
#include <dirent.h>
#include <fnmatch.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>
uint8_t *G;
void carbon_blackbox_movie_request(uint32_t player) { (void)player; }
int diag_on=1;
__thread uint32_t last_error;
static unsigned forbidden, delegated, cash, message, dialogs, getters;
static const char *listed;
static char diagnostic[2048];
#define CHECK(x) do{if(!(x)){fprintf(stderr,"SAVE CHECK %d: %s\n",__LINE__,#x);exit(1);}}while(0)
const char *app_pref(const char *key) { return !strcmp(key,"gameplay.starting_bonus") && getenv("CADD_BONUS") ? "on" : NULL; }
void app_pref_set(const char *key,const char *value) { (void)key;(void)value; }
void app_pref_batch_begin(void) { }
void app_pref_batch_end(void) { }
void report_note(const char *format,...) { (void)format; }
void portmenu_status(const char *format,...) { (void)format; }
int roots_x360_has(const char *s) { (void)s;return 0; }
uint32_t galloc(uint32_t size) { (void)size;return 0; }
#include "carbon_addons_gameplay.c"
/* Tripwires apply to the actual provider, including deliberately broken copies.
 * They do not prohibit opening a directory for enumeration. */
#define fopen(...) (++forbidden,(FILE *)0)
#define open(...) (++forbidden,-1)
#define openat(...) (++forbidden,-1)
#define creat(...) (++forbidden,-1)
#define write(...) (++forbidden,-1)
#define pwrite(...) (++forbidden,-1)
#define unlink(...) (++forbidden,-1)
#define rename(...) (++forbidden,-1)
#define mkdir(...) (++forbidden,-1)
#include "carbon_save_folder.h"
#undef fopen
#undef open
#undef openat
#undef creat
#undef write
#undef pwrite
#undef unlink
#undef rename
#undef mkdir
void diag_event(const char *fmt,...) {
 va_list ap;va_start(ap,fmt);vsnprintf(diagnostic,sizeof diagnostic,fmt,ap);va_end(ap);
}
static int file_is_save(const char *path){(void)path;return 1;}
static void resolve(const char *win,char *out,size_t n){(void)win;snprintf(out,n,"%s",listed);}
SAVE_TEMP
FIND_HELPERS
void abi_violation(Cpu *c,uint32_t fn,uint32_t b,uint32_t s,uint32_t d,uint32_t p,uint32_t sp) {
 (void)c;(void)b;(void)s;(void)d;(void)p;(void)sp;fprintf(stderr,"ABI %x\n",fn);abort();
}
void bad_jump(Cpu *c,uint32_t at){(void)c;fprintf(stderr,"bad jump %x\n",at);abort();}
void untranslated(Cpu *c,uint32_t at){bad_jump(c,at);}
void host_import(Cpu *c,uint32_t slot) {
 switch(slot) {
 case 0x9C13F0: strcpy((char *)gptr(arg(c,4)),"C:\\USERDATA");c->eax=0;c->esp+=24;return;
 case 0x9C1058: c->eax=find_first(gptr(arg(c,0)),arg(c,1));c->esp+=12;return;
 case 0x9C1054: {int k=find_handle(arg(c,0));CHECK(k>=0);c->eax=find_next(k,arg(c,1));c->esp+=12;return;}
 case 0x9C1050: {int k=find_handle(arg(c,0));CHECK(k>=0);closedir(finds[k].d);finds[k].d=NULL;c->esp+=8;return;}
 default:bad_jump(c,slot);
 }
}
void dispatch(Cpu *c,uint32_t target) {
 switch(target) {
 case 0xFF000001: host_import(c,0x9C1054);return;
 case 0x58E370: f_0058E370(c);return;
 case 0x5B7160: f_005B7160(c);return;
 case 0x5CD120: CHECK(M32(c->ecx+4)==14);c->esp+=4;return;
 case 0x5D0D40: f_005D0D40(c);return;
 case 0x5AC6E0: c->esp+=4;return; /* no-bonus completion */
 case 0x4A0490: CHECK(arg(c,0)==0x1778);M32(arg(c,1))=cash;++getters;c->esp+=24;return;
 default:bad_jump(c,target);
 }
}
uint32_t call_guest(Cpu *c,uint32_t target,int n,const uint32_t *args) {
 uint32_t sp=c->esp;for(int i=n-1;i>=0;--i){c->esp-=4;M32(c->esp)=args[i];}
 c->esp-=4;M32(c->esp)=0xFEEDF00D;dispatch(c,target);c->esp=sp;return c->eax;
}
void f_00471430(Cpu *c) {
 char text[1024];snprintf(text,sizeof text,"%s%s",(char *)gptr(arg(c,1)),(char *)gptr(arg(c,2)));
 strcpy((char *)gptr(arg(c,0)),text);c->esp+=4;
}
void f_0069B400(Cpu *c){c->eax=0;c->esp+=4;}
void f_006B3D00(Cpu *c){c->eax=0;c->esp+=4;}
void f_004A0530(Cpu *c){CHECK(arg(c,0)==0x1778&&arg(c,1)==10000);cash+=arg(c,1);c->esp+=24;}
void f_0059D990(Cpu *c){c->esp+=4;}
void f_004A62E0(Cpu *c){c->eax=0;c->esp+=4;}
void f_00578830(Cpu *c){message=arg(c,0);c->eax=0x7000;c->esp+=4;}
void f_005CF440(Cpu *c){CHECK(arg(c,0)==0x7000);++dialogs;c->esp+=4;}
STUBS
#include "native.inc"
static void delegate(Cpu *c){++delegated;c->esp+=8;}
static Cpu setup(void) {
 Cpu c={0};c.esp=0x200000;c.ecx=0x3000;c.ebx=0x1234;c.esi=0x2345;c.edi=0x3456;c.ebp=0x4567;
 M32(c.esp+4)=0x9E8C78;M32(0x3000)=0x9E8CA8;M32(0x3010)=0;M32(0x300C)=0;M32(0x30A8)=0;
 M32(0xA97BD0)=0x3000;M32(0xA97BD8)=0x5000;M32(0x5000)=0x9D4430;M32(0x5004)=32;M32(0x5008)=7;
 M32(0x9C1054)=0xFF000001;cash=15000;message=dialogs=getters=0;return c;
}
int main(int argc,char **argv) {
 CHECK(argc==6);listed=argv[2];unsigned want=atoi(argv[3]),bonus=atoi(argv[4]);diag_on=atoi(argv[5]);
 G=calloc(1,0xC00000);CHECK(G);FILE *f=fopen(argv[1],"rb");CHECK(f);
 CHECK(fread(G,1,0xC00000,f)==0xC00000);fclose(f);
 carbon_addons_gameplay_init();settings_init();
 Cpu c=setup();
 if(!getenv("CADD_BONUS")) {
 f_00716690(&c);
 CHECK(M32(0x3010)==want);CHECK(cash==15000+bonus);CHECK(message==(bonus?0x84B62CBF:0));CHECK(dialogs==!!bonus);
 }
 c=setup();carbon_save_folder_list(&c,delegate);
 CHECK(!forbidden&&!delegated);CHECK(M32(0x3010)==want);CHECK(cash==15000+bonus);
 CHECK(message==(bonus?0x84B62CBF:0));CHECK(dialogs==!!bonus);CHECK(getters==(diag_on?2:0));
 CHECK(c.esp==0x200008&&c.ebx==0x1234&&c.esi==0x2345&&c.edi==0x3456&&c.ebp==0x4567);
 if(diag_on){CHECK(strstr(diagnostic,listed));CHECK(strstr(diagnostic,bonus?"bonus=10000":"bonus=0"));}
 c=setup();M32(c.esp+4)=0x9E8C88;carbon_save_folder_list(&c,delegate);CHECK(delegated==1);CHECK(getters==0);
 printf("SAVE PASS count=%u bonus=%u message=%08X forbidden=%u diag=%d\n",want,bonus,bonus?0x84B62CBF:0,forbidden,diag_on);
 free(G);return 0;
}
'''


def run(args, expected=0, **kwargs):
    result = subprocess.run(list(map(str, args)), capture_output=True, text=True, **kwargs)
    assert result.returncode == expected, (args[:3], result.returncode, result.stdout[-1000:], result.stderr[-2500:])
    return result


def tree(path):
    return [(str(p.relative_to(path)), p.stat().st_mode, p.stat().st_mtime_ns,
             hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None)
            for p in sorted(path.rglob('*'))]


def main():
    base = HERE / 'out/carbon-base'
    if not all((base / p).is_file() for p in ('image.json', 'table.c', 'funcs.h', 'NFSC.a')):
        print('SKIP: private_save_folder_test needs Carbon outputs')
        return 3
    image = json.loads((base / 'image.json').read_text())
    if not Path(image['exe']).is_file():
        print('SKIP: private image unavailable')
        return 3
    sys.path.insert(0, str(HERE))
    import build_all
    import private_hooks
    from private_hooks_test import body
    from recomp import PE
    pe = PE(image['exe'], expected_sha256=IMAGE_SHA)
    starts = [int(v.strip().removesuffix('u'), 16) for v in re.search(
        r'guest_func_addr\[\] = \{([^}]+)', (base / 'table.c').read_text())[1].split(',')]
    hooks = private_hooks.load_registry(pe, [(a, starts[i+1] if i+1 < len(starts) else a+16, '')
                                           for i, a in enumerate(starts)])
    assert hooks[0x716690]['provider'] == 'carbon_save_folder_list'
    native = []
    for address, digest in BASELINES.items():
        source = (base / f'NFSC_{starts.index(address)//build_all.CHUNK:02d}.c').read_text()
        name = f'f_{address:08X}'
        original = private_hooks.original_name(address)
        text = body(source, original if f'void {original}(' in source else name).replace(original, name, 1)
        assert hashlib.sha256(text.encode()).hexdigest() == digest, hex(address)
        native.append(text)
    defined = set(BASELINES) | {0x471430, 0x69B400, 0x6B3D00, 0x4A0530, 0x59D990, 0x4A62E0, 0x578830, 0x5CF440}
    dependencies = {int(a, 16) for a in re.findall(r'\bf_([0-9A-F]{8})\(c\)', '\n'.join(native))}
    stubs = '\n'.join(f'void f_{a:08X}(Cpu *c){{bad_jump(c,0x{a:08X});}}' for a in dependencies-defined)
    boot = (ROOT / 'runtime/boot.c').read_text()
    root = boot[boot.index('const char *userdata_dir(void) {'):boot.index('// BEGIN offline save scan')]
    temp = boot[boot.index('static int save_temp_name('):boot.index('// Own fd;')]
    find = boot[boot.index('#define FIND_BASE'):boot.index('// END offline save scan')]
    provider = (PRIVATE / 'carbon_save_folder.h').read_text()
    feature = json.loads((PRIVATE / 'features/save_folder.json').read_text())
    assert feature['bindings']['carbon_save_folder.c']['sha256'] == hashlib.sha256(provider.encode()).hexdigest()
    with tempfile.TemporaryDirectory(prefix='private-save-folder-', dir=HERE/'out') as directory:
        tmp = Path(directory)
        image_bytes = bytearray(0xC00000)
        for _, _, va, size, offset in pe.sections:
            image_bytes[pe.base+va:pe.base+va+size] = pe.data[offset:offset+size]
        (tmp/'image.bin').write_bytes(image_bytes)
        (tmp/'native.inc').write_text('\n\n'.join(native))
        (tmp/'fixture.c').write_text(HARNESS.replace('SAVE_TEMP', temp).replace('FIND_HELPERS', find).replace('STUBS', stubs))
        flags = ['clang', '-O1', '-g', '-fsanitize=address,undefined', '-I', tmp, '-I', base, '-I', HERE, '-I', PRIVATE, '-I', ROOT/'runtime']
        env = dict(os.environ, HOME=str(tmp/'home'))
        env.pop('BOOT_USERDATA', None)
        env.pop('NFS_TEST_CARBON_MW_SAVES', None)
        env.pop('CADD_BONUS', None)
        for variant, root_source in [('good', root), ('shared-root', root.replace('%s/Carbon', '%s').replace('NFSMW-port/Carbon', 'NFSMW-port'))]:
            (tmp/'root.c').write_text(ROOT_DRIVER.replace('ROOT_FUNCTION', root_source))
            for game in (1, 2):
                exe = tmp/f'root-{variant}-{game}'
                run([*flags, f'-DNFS_GAME={game}', tmp/'root.c', '-o', exe])
                for explicit in (False, True):
                    current = dict(env)
                    userbase = tmp/'explicit' if explicit else tmp/'home/Library/Application Support/NFSMW-port'
                    if explicit: current['BOOT_USERDATA'] = str(userbase)
                    want = userbase/'Carbon' if game == 2 else userbase
                    run([exe, want], 1 if variant == 'shared-root' and game == 2 else 0, env=current)
        # Empty/missing/profile trees are artificial; no real save is copied.
        empty, profile, missing = tmp/'empty', tmp/'NFS Most Wanted', tmp/'missing'
        empty.mkdir();(profile/'TEST').mkdir(parents=True);(profile/'TEST/TEST').write_bytes(b'fixture')
        (profile/'stage.nfs-save-ABCDEF').write_bytes(b'internal stage')
        for variant, source in [('good', provider),
                                ('file-open', provider.replace('uint32_t self =', '(void)fopen(path, "rb");\n    uint32_t self =')),
                                ('file-write', provider.replace('uint32_t self =', '(void)fopen(path, "wb");\n    uint32_t self ='))]:
            assert variant == 'good' or source != provider
            (tmp/'carbon_save_folder.h').write_text(source)
            exe = tmp/variant
            run([*flags, tmp/'fixture.c', ROOT/'runtime/settings.c', '-Wl,-dead_strip', '-o', exe])
            cases = [(missing, 0), (empty, 1), (profile, 2)] if variant == 'good' else [(profile, 2)]
            for path, count in cases:
                before = tree(tmp)
                current = dict(env, NFS_TEST_CARBON_MW_SAVES=str(path))
                for diag in (0, 1):
                    result = run([exe, tmp/'image.bin', path, count, 10000 if count else 0, diag],
                                 0 if variant == 'good' else 1, env=current)
                    if variant == 'good': print(result.stdout.strip())
                assert tree(tmp) == before, 'old-save listing modified the fixture tree'
            if variant != 'good': print(f'SAVE MUTANT {variant}: exit=1 good=0')
        # Default listing path resolves beside Carbon, independent of creating it.
        for explicit in (False, True):
            current = dict(env)
            userbase = tmp/'explicit' if explicit else tmp/'home/Library/Application Support/NFSMW-port'
            if explicit: current['BOOT_USERDATA'] = str(userbase)
            path = userbase/'NFS Most Wanted'
            path.mkdir();(path/'TEST').mkdir()
            run([tmp/'good', tmp/'image.bin', path, 2, 10000, 1], env=current)
        # Forced presence follows the same native callback and dialog, with no
        # duplicate when a real prior save is already present.
        current = dict(env, CADD_BONUS='1', NFS_TEST_CARBON_MW_SAVES=str(missing))
        run([tmp/'good', tmp/'image.bin', missing, 1, 10000, 1], env=current)
        current['NFS_TEST_CARBON_MW_SAVES'] = str(profile)
        run([tmp/'good', tmp/'image.bin', profile, 2, 10000, 1], env=current)
        original = provider.replace('if (!count && settings_get("gameplay.starting_bonus") > 0) count = 1;', '(void)count;')
        assert original != provider
        (tmp/'carbon_save_folder.h').write_text(original)
        run([*flags, tmp/'fixture.c', ROOT/'runtime/settings.c', '-Wl,-dead_strip', '-o', tmp/'original-bonus'])
        current['NFS_TEST_CARBON_MW_SAVES'] = str(missing)
        run([tmp/'original-bonus', tmp/'image.bin', missing, 1, 10000, 1], 1, env=current)
        print('STARTING BONUS PASS original=0 required=10000 actual=10000 existing-save=10000 (not 20000)')
        print('PRIVATE SAVE FOLDER PASS roots=4 shared-root=exit1 native-counts=0/1/2 native-bonus=0/10000 old-save-mutations=0')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
