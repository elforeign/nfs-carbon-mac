"""Optional startup sign-in through five pinned translated native bodies.

Good: requests=0, notice creations=0, screen-text lookups=0, completion=1.
Hook removed: requests=1, notice creations=1, screen-text lookups=1; exit 1.
The real request, failure callback, state pump, error renderer and exit handler
run; only the unavailable SDK, language lookup and dialog allocation are sinks.
Native options-off and hooked startup have identical manager state and preserved
registers. Explicit requests and unrelated errors retain native behavior.
Premise captures: six notice-bearing frames, 9540..10440 at 180-frame spacing;
the next Return (10600) closes it. Fresh/FirstTime=0 acceptance: zero notice
lookups, one native offline completion each, no key after that completion.
Unproven online menu paths found in the decode: game selection 00593CC0 and
00593D60 (both request type 1 via 0071FCC0); sign-in screen 00716D80 and login
actions 00723FF0; explicit connection error callback 005A70C0. The startup hook
does not remove these menu items or replace their failures.
Rockport banner: with the track overlay set, 9F3316E5 resolves to "CENTRAL ROSEWOOD"
(capitals: the HUD font has no lowercase; a mixed-case string drew only "C   R" on screen)
(old code: the native lookup's 0x9100 fallback, i.e. DEFAULT STRING in the game); no overlay: native.
Exit 3 without the private translated outputs/image. No game or emulation.
"""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import build_all
import private_hooks
from recomp import PE

PINS = {
    '005A7E00': '1b9db478638778489547894c8b1f183168c6e1a79eba3d60010e79879fa5f4cd',
    '0059B1B0': '9bf3f0777be4a8c650d524c34c70224fb6b4f9beef0426fc92e9a962a9be3726',
    '005A8240': '0937fbe823b1eaff5d6c4998831ca779c7820567faf93f382478a5f2759d04fe',
    '005CFFA0': 'c46d71b2d7da9147d0231dc1e535332af951c293195f1e849e10db0530d99735',
    '005BE360': 'a1549841e451f0db30b1f2597b88356395885667ead85b1fbe0cc7886b7e7d3e',
}

HARNESS = r'''
#include "funcs.h"
#include <stdio.h>
#include <stdlib.h>
#include <stdarg.h>
#include <string.h>
uint8_t *G;
static uint8_t *image_memory;
int diag_on=1;
uint32_t gstr(const char *s){static uint32_t at=0xA000;uint32_t r=at;strcpy((char *)G+at,s);at+=64;return r;}
static unsigned requests, notices, lookups, completed, text_diag, dialogs;
static unsigned option_connect=1, connected;
enum {SELF=0x2000, VT=0x3000, SDK=0x4000, SDKVT=0x5000};
#define CHECK(x) do {if(!(x)){fprintf(stderr,"START CHECK %d: %s\n",__LINE__,#x);exit(1);}}while(0)
void diag_event(const char *fmt,...) {if(strstr(fmt,"CARBON SCREEN TEXT"))++text_diag;}
void bad_jump(Cpu *c,uint32_t a){(void)c;(void)a;abort();}
void untranslated(Cpu *c,uint32_t a){(void)c;(void)a;abort();}
void host_import(Cpu *c,uint32_t a){(void)c;(void)a;abort();}
static void lookup(Cpu *c){
    if(M32(c->esp+4)==0x8D824D60u){++lookups;c->eax=0x9000;}
    else c->eax=0x9100;
    c->esp+=4;
}
void f_00578830(Cpu *c){carbon_start_notice_text(c,lookup);}
void f_005CF440(Cpu *c){++dialogs;if(M32(c->esp+4)==0x9000)++notices;c->esp+=4;}
void f_004A0490(Cpu *c){
    uint32_t key=M32(c->esp+4),out=M32(c->esp+8);
    CHECK(key==0x3A98 || key==0x3A9F);
    M32(out)=key==0x3A9F?option_connect:0;c->eax=1;c->esp+=24;
}
void f_004A04E0(Cpu *c){
    CHECK(M32(c->esp+4)==0x3A9F&&M32(c->esp+8)==0);
    option_connect=0;c->esp+=24;
}
void f_0081C8B0(Cpu *c){c->eax=connected;c->esp+=4;}
void f_0081C8E0(Cpu *c){c->eax=0;c->esp+=4;}
void f_0081C920(Cpu *c){c->eax=0;c->esp+=4;}
void f_0059B0D0(Cpu *c){c->esp+=8;}
void f_00579370(Cpu *c){CHECK(M32(c->esp+4)==0x1234);c->esp+=8;}
void f_00579C10(Cpu *c){CHECK(M32(c->esp+4)==5);c->esp+=8;}
void dispatch(Cpu *c,uint32_t target){
    if(target==0x100){
        ++requests;
        /* SDK failure delivers error 2 to the real callback subobject. */
        c->ecx=M32(c->esp+4);M32(c->esp+4)=2;f_005A8240(c);
    }else if(target==0x104){++completed;c->esp+=4;}
    else if(target==0x108)f_005BE360(c);
    else if(target==0x10C)f_005CFFA0(c);
    else {fprintf(stderr,"unexpected dispatch %08X\n",target);abort();}
}
static Cpu initial(unsigned kind){
    memcpy(G,image_memory,0xC00000);requests=notices=lookups=completed=text_diag=dialogs=0;
    M32(SELF)=VT;M32(SELF+8)=kind;M32(SELF+0xAC)=0x1234;
    M32(SELF+0xC)=0x1234;M32(SELF+0xC8)=SDK;
    M32(VT+0x4C)=0x104;M32(VT+0x114)=0x108;M32(VT+0x10C)=0x10C;
    M32(SDK)=SDKVT;M32(SDKVT+4)=0x100;
    Cpu c={0};c.esp=0x10000;c.ecx=SELF;c.ebx=0x11223344;
    c.esi=0x55667788;c.edi=0x99AABBCC;c.ebp=0xCCDDEEFF;return c;
}
static void preserved(Cpu c){
    CHECK(c.esp==0x10004&&c.ebx==0x11223344&&c.esi==0x55667788);
    CHECK(c.edi==0x99AABBCC&&c.ebp==0xCCDDEEFF);
}
int main(int argc,char **argv){
    CHECK(argc>=2);G=calloc(1,0xC00000);image_memory=malloc(0xC00000);CHECK(G&&image_memory);
    FILE *file=fopen(argv[1],"rb");CHECK(file);
    CHECK(fread(image_memory,1,0xC00000,file)==0xC00000);fclose(file);
    Cpu c=initial(0);option_connect=0;f_005A7E00(&c);preserved(c);
    CHECK(completed==1&&requests==0&&notices==0);
    unsigned char native[256];memcpy(native,G+SELF,sizeof native);
    c=initial(0);option_connect=1;
    if(argc>2)f_005A7E00(&c);else carbon_start_offline(&c,f_005A7E00);
    preserved(c);
    if(M8(SELF+0xA0)){
        c.esp=0x10000;c.ecx=SELF;f_0059B1B0(&c);preserved(c);
    }
    printf("START optional requests=%u notice-creations=%u text-lookups=%u text-diag=%u completion=%u\n",
           requests,notices,lookups,text_diag,completed);
    fflush(stdout);
    CHECK(notices==0&&lookups==0&&requests==0&&text_diag==0&&completed==1);
    CHECK(option_connect==1);
    CHECK(!memcmp(native,G+SELF,sizeof native));
    /* Kinds 1 and 2 are explicit requests: native and provider are identical. */
    for(unsigned kind=1;kind<=2;++kind){
        connected=0;c=initial(kind);f_005A7E00(&c);preserved(c);
        Cpu expected=c;memcpy(native,G+SELF,sizeof native);
        c=initial(kind);carbon_start_offline(&c,f_005A7E00);preserved(c);
        CHECK(!memcmp(&c,&expected,sizeof c));CHECK(!memcmp(native,G+SELF,sizeof native));
    }
    /* The original error handler still creates both this notice and other ones. */
    c=initial(0);M32(SELF+4)=27;M32(SELF+0xCC)=2;f_005CFFA0(&c);
    CHECK(notices==1&&dialogs==1&&lookups==1&&text_diag==1);
    c=initial(0);M32(SELF+4)=27;M32(SELF+0xCC)=1;f_005CFFA0(&c);
    CHECK(notices==0&&dialogs==1&&lookups==0&&text_diag==0);
    diag_on=0;c=initial(0);M32(c.esp+4)=0x8D824D60u;f_00578830(&c);
    CHECK(c.eax==0x9000&&lookups==1&&text_diag==0&&c.esp==0x10004);
    /* Rockport banner: with the overlay set, key 9F3316E5 gives the port string; without it, the native lookup. */
    unsetenv("NFS_CARBON_TRACK_OVERLAY");
    c=initial(0);M32(c.esp+4)=0x9F3316E5u;f_00578830(&c);
    CHECK(c.eax==0x9100&&c.esp==0x10004);
    setenv("NFS_CARBON_TRACK_OVERLAY","/overlay",1);
    c=initial(0);M32(c.esp+4)=0x9F3316E5u;f_00578830(&c);
    CHECK(c.esp==0x10004&&!strcmp((char *)G+c.eax,"CENTRAL ROSEWOOD"));
    c=initial(0);M32(c.esp+4)=0x12345678u;f_00578830(&c);
    CHECK(c.eax==0x9100&&c.esp==0x10004);
    puts("ROCKBANNER 9F3316E5 -> CENTRAL ROSEWOOD (overlay), native without");
    free(image_memory);free(G);puts("START native-off equality=1 explicit-types=2 other-dialog=1 diagnostic-off=1");return 0;
}
'''


def main():
    base = HERE / 'out/carbon-base'
    if not all((base / p).is_file() for p in ('image.json', 'table.c', 'funcs.h')):
        print('SKIP: startup fixture needs private translated outputs')
        return 3
    image = json.loads((base / 'image.json').read_text())
    if not Path(image['exe']).is_file():
        print('SKIP: startup fixture needs private image')
        return 3
    pe = PE(image['exe'], expected_sha256=image['sha256'])
    starts = [int(v.removesuffix('u'), 16) for v in re.search(
        r'guest_func_addr\[\] = \{([^}]+)', (base / 'table.c').read_text())[1].split(',')]
    originals = {}
    for address, digest in PINS.items():
        path = base / f'NFSC_{starts.index(int(address, 16)) // build_all.CHUNK:02d}.c'
        source = path.read_text()
        match = re.search(rf'void (?:f_|carbon_orig_){address}\(Cpu [^)]*\)\s*\{{', source)
        assert match, address
        code = source[match.start():source.index('\n}', match.end()) + 2]
        code = code.replace(f'void carbon_orig_{address}', f'void f_{address}', 1)
        assert hashlib.sha256(code.encode()).hexdigest() == digest, address
        originals[address] = code
    registry = HERE / 'private_runtime/hooks'
    functions = [(a, starts[i + 1] if i + 1 < len(starts) else a + 1, '')
                 for i, a in enumerate(starts)]
    records = private_hooks.load_registry(pe, functions, registry)
    for address, provider in ((0x005A7E00, 'carbon_start_offline'),
                              (0x00578830, 'carbon_start_notice_text')):
        assert records[address]['provider'] == provider
    feature = json.loads((HERE / 'private_runtime/features/start_offline.json').read_text())
    source = HERE / 'private_runtime/carbon_start_offline.h'
    assert feature['image_sha256'] == pe.sha256
    assert feature['bindings']['carbon_start_offline.c']['sha256'] == hashlib.sha256(source.read_bytes()).hexdigest()
    with tempfile.TemporaryDirectory(prefix='private-start-') as td:
        tmp = Path(td)
        memory = bytearray(0xC00000)
        for _, _, va, size, raw in pe.sections:
            memory[pe.base + va:pe.base + va + size] = pe.data[raw:raw + size]
        (tmp / 'image.bin').write_bytes(memory)
        selected = {int(a, 16) for a in originals}
        defined = selected | {int(a, 16) for a in re.findall(r'void f_([0-9A-F]{8})\(', HARNESS)}
        needed = {int(a, 16) for code in originals.values()
                  for a in re.findall(r'\bf_([0-9A-F]{8})\(c\)', code)}
        traps = '\n'.join(f'void f_{a:08X}(Cpu *c){{(void)c;fprintf(stderr,"unexpected {a:08X}\\n");abort();}}'
                          for a in sorted(needed - defined))
        # Compile the unchanged native request beside the production provider.
        (tmp / 'fixture.c').write_text('#include "funcs.h"\n#include "host.h"\n#include <stdlib.h>\n' + private_hooks.declarations(records) +
            '\n'.join(originals.values()) + '\n' + traps + '\n' + HARNESS +
            '\n#include "carbon_start_offline.h"\n')
        result = subprocess.run(['clang', '-O1', '-I', str(HERE), '-I', str(base),
            '-I', str(HERE.parent / 'runtime'), '-I', str(source.parent),
            str(tmp / 'fixture.c'), '-o', str(tmp / 'fixture')], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr[-5000:]
        good = subprocess.run([str(tmp / 'fixture'), str(tmp / 'image.bin')], capture_output=True, text=True)
        assert good.returncode == 0, good.stdout + good.stderr
        print(good.stdout.strip())
        broken = subprocess.run([str(tmp / 'fixture'), str(tmp / 'image.bin'), 'hook-removed'], capture_output=True, text=True)
        assert broken.returncode == 1, broken.stdout + broken.stderr
        assert 'requests=1 notice-creations=1 text-lookups=1 text-diag=1 completion=0' in broken.stdout
        print('START removed-hook: ' + broken.stdout.strip() + ' exit=1')
    print('PRIVATE START OFFLINE PASS native-bodies=5 notices=0->1 mutants=1')
    return 0


if __name__ == '__main__':
    sys.exit(main())
