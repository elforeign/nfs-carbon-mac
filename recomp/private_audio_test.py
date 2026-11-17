"""Native surround seed and image-byte replay; no game/device/emulator.

Default regression: OLD exit 1 (1 failure, unset); NEW exit 0 (13 seed cases).
The pinned original startup function also fails on every run with unset.
Unset/empty/1/2 enable; only 0 disables.
Good: on = one 4-byte store, value 2 at A63E70; off/wrong image = 0 stores.
Broken value=1: exit 1; broken address=A63E74: exit 1 (good: exit 0).
Replay: option 1 -> mode 1 -> 2 channels/mask 3; option 2 -> mode 3 ->
6 channels/mask 63, 48 kHz/int16/block 12. Missing six-channel capability
falls back to stereo. Broken channel table and mask each exit 1 (good: 0).
Full-function SHA witnesses bind fresh translations to the inspected bytes.
Exit 3 without this checkout's private build outputs or executable.
Feature-bound staging accepts the correct image (1) and rejects a wrong image (0).
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from build_private_runtime import prepare, CARBON_SKIPFE_SHA256
from recomp import PE, Recompiler

WITNESSES = (
    (0x504530, 0x69, '406b2787dd4c79f2fa38fddf8b3954704a17bd2f623f97e0c548492589405dc3'),
    (0x8A8560, 0x11c, '9b903cbb61bb1b144510e1aa0c74c5fa07ac4e8ba85d39a41a3be8f738b623f7'),
    (0x8A7931, 0x205, '0e9e8edbd5c98a8df5b14e7708ec7d11107908e61deee2982a800aa5b4e48fa9'),
)

OLD_SEED = '''static void private_carbon_audio_setup(void) {
    const char *value = getenv("NFS_CARBON_SURROUND");
    if (!PRIVATE_CARBON_SKIPFE || !value || strcmp(value, "1")) return;
    M32(0x00A63E70) = 2;
}'''

SEED = r'''
#include "runtime.h"
#include <stdio.h>
#include <stdlib.h>
uint8_t *G;
static unsigned stores;
static u32a *word(uint32_t address) { ++stores; return (u32a *)(G+address); }
#undef M32
#define M32(a) (*word(a))
#include "audio.inc"
int main(int argc,char **argv) {
    G=malloc(0xC00000);uint8_t *expected=malloc(0xC00000);
    memset(G,0xA5,0xC00000);*(uint32_t *)(G+0xA63E70)=1;
    memcpy(expected,G,0xC00000);int active=atoi(argv[1]);
    if(active) *(uint32_t *)(expected+0xA63E70)=2;
    private_carbon_audio_setup();
    int bad=stores!=(unsigned)active || memcmp(G,expected,0xC00000);
    free(G);free(expected);return !!bad;
}
'''

REPLAY = r'''
#include "runtime.h"
#include <stdio.h>
#include <stdlib.h>
uint8_t *G;
#define CHECK(x) do { if(!(x)){fprintf(stderr,"AUDIO CHECK %d: %s\n",__LINE__,#x);exit(1);} } while(0)
void guest_divide_error(Cpu *c,uint32_t at){CHECK(0);}
static float request;
static unsigned channels,mask,align,rate,bits,creates;
void f_00899352(Cpu *c){c->esp+=4;}
void f_00899369(Cpu *c){c->esp+=4;}
void f_008999E5(Cpu *c){CHECK(M32(c->esp+4)==1);request=MF32(M32(c->esp+8));c->esp+=12;}
void f_0087EAC0(Cpu *c){c->eax=(uint32_t)ST(0);x87_pop(c);c->esp+=4;}
void f_008A790C(Cpu *c){CHECK(0);}
void f_008A80AC(Cpu *c){CHECK(0);}
void f_008A7394(Cpu *c){CHECK(0);}
void f_00899242(Cpu *c){memset(G+M32(c->esp+4),M32(c->esp+8),M32(c->esp+12));c->esp+=4;}
void dispatch(Cpu *c,uint32_t target){
 if(target==0x100) {
   uint32_t desc=M32(c->esp+8),out=M32(c->esp+12);
   CHECK(M32(desc)==0x24);++creates;
   if(M32(desc+4)==0x18000){uint32_t fmt=M32(desc+0x10);
     channels=M16(fmt+2);rate=M32(fmt+4);align=M16(fmt+12);bits=M16(fmt+14);mask=M32(fmt+20);
   }else CHECK(M32(desc+4)==1);
   M32(out)=0x5000; c->eax=0;c->esp+=20;
 }else if(target==0x104){c->eax=0;c->esp+=12;}
 else CHECK(0);
}
TRANSLATED
int main(int argc,char **argv){
 CHECK(argc==2);G=calloc(1,0xC00000);FILE *f=fopen(argv[1],"rb");CHECK(f);
 CHECK(fread(G,1,0xC00000,f)==0xC00000);fclose(f);
 CHECK(M32(0xA63E70)==1);
 for(unsigned option=1;option<=2;++option){
  Cpu c={0};c.esp=0x10000;c.ecx=0x2000;M32(c.esp+4)=option;M32(0xA631B8)=1;
  f_00504530(&c);CHECK(c.esp==0x10008);CHECK(request==(option==2?3.0f:1.0f));
  for(unsigned fallback=0;fallback<2;++fallback){
   c=(Cpu){0};c.esp=0x10000;M32(c.esp+4)=0x3000;M32(0x3004)=0x4000;MF32(0x3008)=request;
   M8(0xBC0EC8)=fallback?1:2;M32(0xBC0E80)=1;M32(0xBC0E84)=3;M8(0xBBF608)=0;
   f_008A8560(&c);CHECK(c.esp==0x10004);
   unsigned want=option==2&&!fallback?6:2;CHECK(M8(0xBBF605)==want);
   c=(Cpu){0};c.esp=0x10000;c.ecx=0x4000;M32(c.esp+4)=M8(0xBBF605);
   M32(c.esp+8)=48000;M32(c.esp+12)=0;M32(0x4044)=0x6000;
   M32(0x6000)=0x6100;M32(0x610C)=0x100;M32(0x5000)=0x6200;M32(0x6238)=0x104;
   creates=0;f_008A7931(&c);CHECK(c.esp==0x10010);CHECK(c.eax==1&&creates==2);
   CHECK(channels==want&&mask==(want==6?63:3)&&align==want*2&&bits==16&&rate==48000);
  }
 }
 free(G);return 0;
}
'''


def compile_run(tmp, source, name, args=(), env=None):
    path = tmp / (name + '.c'); path.write_text(source)
    binary = tmp / name
    result = subprocess.run(['clang', '-O1', '-Wno-parentheses-equality', '-fsanitize=address,undefined', '-I', str(HERE),
                             str(path), '-o', str(binary)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr[-2000:]
    return subprocess.run([str(binary), *args], env=env, capture_output=True, text=True)


def main():
    out = HERE / 'out/carbon'
    if not all((out / name).is_file() for name in ('image.json', 'NFSC.a', 'boot_carbon')):
        print('SKIP: private audio build outputs absent'); return 3
    image = json.loads((out / 'image.json').read_text())
    if not Path(image['exe']).is_file():
        print('SKIP: private executable absent'); return 3
    pe = PE(image['exe'], expected_sha256=CARBON_SKIPFE_SHA256)
    for address, size, digest in WITNESSES:
        assert hashlib.sha256(pe.read(address, size)).hexdigest() == digest
    rc = Recompiler(pe=pe, functions={a:a+n for a,n,_ in WITNESSES}, mw_patches=False)
    # Named host boundaries stand in for locks, queue delivery, float conversion,
    # memset and device reopen; retain the native request/selection/format code.
    rc.functions.update({a:a+1 for a in (0x899352, 0x899369, 0x8999E5, 0x87EAC0,
                                       0x8A790C, 0x8A80AC, 0x8A7394, 0x899242)})
    rc.calls = True
    translated = []
    for address, size, _ in WITNESSES:
        code, why = rc.translate(address, address+size)
        assert code is not None, why
        translated.append(code)
    source = (HERE / 'private_runtime/carbon_audio.h').read_text()
    assert hashlib.sha256(OLD_SEED.encode()).hexdigest() == '14a148a16ec0576d41d0fa24280ff545d7d5baccfd29cdca40717ec46d95ef79'
    env = {k:v for k,v in os.environ.items() if k != 'NFS_CARBON_SURROUND'}
    with tempfile.TemporaryDirectory(prefix='private-audio-') as td:
        tmp = Path(td)
        for variant, code, identity in (
                ('good', source, 1), ('wrong-image', source, 0),
                ('old-default', OLD_SEED, 1),
                ('wrong-value', source.replace(' = 2;', ' = 1;'), 1),
                ('wrong-address', source.replace('0x00A63E70', '0x00A63E74'), 1)):
            (tmp/'audio.inc').write_text(f'#define PRIVATE_CARBON_SKIPFE {identity}\n'+code)
            cases = (None, '', '0', '1', '2') if variant in ('good','wrong-image') else ((None,) if variant=='old-default' else ('1',))
            for value in cases:
                active = int(identity and value != '0')
                setting = {} if value is None else {'NFS_CARBON_SURROUND':value}
                r = compile_run(tmp, SEED, 'seed', [str(active)], dict(env,**setting))
                bad = variant=='old-default' or (variant.startswith('wrong-') and variant!='wrong-image')
                assert r.returncode == int(bad), (variant,r.stderr)
            print(f'AUDIO {variant} cases={len(cases)} exit={r.returncode}')
        memory = bytearray(0xC00000)
        for _, _, va, size, raw in pe.sections:
            memory[pe.base+va:pe.base+va+size] = pe.data[raw:raw+size]
        memory_path = tmp/'image.bin';memory_path.write_bytes(memory)
        replay = REPLAY.replace('TRANSLATED','\n'.join(translated))
        for variant, code in (
                ('good', replay),
                ('wrong-mask', replay.replace('(uint32_t)0x3Fu','(uint32_t)0x33u')),
                ('wrong-channels', replay)):
            changed = bytearray(memory)
            if variant == 'wrong-channels': changed[0xA0426F]=2
            memory_path.write_bytes(changed)
            r = compile_run(tmp, code, 'replay', [str(memory_path)])
            assert r.returncode == int(variant!='good'), (variant,r.stderr)
            print(f'AUDIO replay {variant} exit={r.returncode}')
        tables=tmp/'tables';tables.mkdir()
        for digest, expected in ((CARBON_SKIPFE_SHA256,1),('0'*64,0)):
            target=tmp/f'bound{expected}';target.mkdir()
            (target/'image.json').write_text(json.dumps({'sha256':digest,'exe':'fixture.exe','imports':{}}))
            (target/'imports.c').write_text('/* fixture */\n')
            try:
                staged=prepare(target,tables)
            except ValueError as error:
                # Image-bound feature registries reject a different executable
                # before staging. The standalone wrong-image seed still runs above.
                assert expected==0 and 'feature image digest differs' in str(error), str(error)
                print('AUDIO preparation wrong-image rejected before staging')
                print('AUDIO feature image: good accepted=1 / wrong image rejected=1')
                continue
            boot=(staged/'boot.c').read_text()
            assert f'#define PRIVATE_CARBON_SKIPFE {expected}' in (staged/'game_image.h').read_text()
            assert (staged/'private_carbon_audio.h').read_text()==source
            assert boot.count('    private_carbon_audio_setup();')==1
            assert boot.index('memcpy(G + 0x400000 + va, pe + raw, rs);') < boot.index('    private_carbon_audio_setup();') < boot.index('dispatch(c, speed_entry);')
            selected=subprocess.run(['unifdef','-DNFS_GAME=1','-DNFS_GAME_MW=1','-DNFS_GAME_PRIVATE=2'],input=boot,capture_output=True,text=True)
            assert 'private_carbon_audio_setup();' not in selected.stdout
    print('PRIVATE AUDIO PASS seed_cases=13 mutants=5 replay_cases=4 image_bindings=2')
    return 0


if __name__ == '__main__':
    sys.exit(main())
