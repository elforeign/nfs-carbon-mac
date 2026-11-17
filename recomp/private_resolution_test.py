"""Native mode/parser fixture, no GPU/game/private assets.

Good: unset/empty preserve all bytes and CPU state for all six retail modes;
four valid sizes write exactly two words. Invalid inputs and wrong-image use
exit 2 before any writes. Broken width/height writes and stack cleanup each
exit 1; a broken unset path exits 1. Generated boot/hash bindings are checked.
Feature-bound staging accepts the correct image (1) and rejects a wrong image (0).
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from build_private_runtime import prepare
from private_resolution import instrument, CARBON_SHA256, HOOKS

MODE = r'''
void f_00712AC0(Cpu *c) {
    static const uint32_t modes[6][2]={{640,480},{800,600},{1024,768},{1280,960},{1280,1024},{1600,1200}};
    uint32_t index=M32(0xA65388), width=M32(c->esp+4), height=M32(c->esp+8);
    if(index<6){M32(width)=modes[index][0];M32(height)=modes[index][1];}
    c->eax=width;c->ecx=height;c->esp+=12;
}
'''
HARNESS = r'''
#include "runtime.h"
#include <stdio.h>
#include <stdlib.h>
uint8_t *G; int diag_on;
static uint8_t expected[0xC00000];
void diag_event(const char *fmt,...) {}
#include "resolution.inc"
WRAPPED
#define CHECK(x) do{if(!(x)){fprintf(stderr,"RES CHECK line %d: %s\n",__LINE__,#x);exit(1);}}while(0)
static void unchanged(void){CHECK(!memcmp(G,expected,sizeof expected));CHECK(!private_carbon_width&&!private_carbon_height);}
int main(int argc,char **argv){
 CHECK(argc==3);G=malloc(sizeof expected);CHECK(G);memset(G,0xA5,sizeof expected);memcpy(expected,G,sizeof expected);
 if(!strcmp(argv[1],"invalid")){atexit(unchanged);private_carbon_resolution_setup();return 9;}
 private_carbon_resolution_setup();
 unsigned width=atoi(argv[1]),height=atoi(argv[2]);
 CHECK(private_carbon_resolution_active()==!!width);
 for(unsigned i=0;i<6;++i){
  Cpu c={0};c.esp=0x1000;c.ebx=9;c.esi=8;c.edi=7;c.ebp=6;
  M32(0xA65388)=i;M32(c.esp)=0xFEED;M32(c.esp+4)=0x2000;M32(c.esp+8)=0x2004;
  memset(G+0x2000,0xA5,8);memcpy(expected,G,sizeof expected);
  Cpu original=c;f_00712AC0_resolution_original(&original);
  if(width){M32(0x2000)=width;M32(0x2004)=height;}
  uint8_t words[8];memcpy(words,G+0x2000,8);
  memcpy(G,expected,sizeof expected);memcpy(expected+0x2000,words,8);
  f_00712AC0(&c);
  CHECK(c.esp==0x100C);CHECK(!memcmp(&c,&original,sizeof c));CHECK(!memcmp(G,expected,sizeof expected));
 }
 free(G);return 0;
}
'''


def main():
    source = (HERE/'private_runtime/carbon_resolution.h').read_text()
    wrapped, found = instrument(MODE, CARBON_SHA256)
    assert found == [0x712AC0]
    assert instrument(MODE, '0'*64) == (MODE, [])
    # All diagnostic wrappers compile with the same stack ABI; no guest calls
    # or guest state writes are added by the evidence functions.
    diagnostics = ''.join(f'void f_{a:08X}(Cpu *c) {{ c->eax=0;c->esp+=4; }}\n' for a in HOOKS if a != 0x712AC0)
    all_wrapped, found = instrument(MODE+diagnostics, CARBON_SHA256)
    assert set(found) == set(HOOKS)
    env = {k:v for k,v in os.environ.items() if k != 'NFS_CARBON_RES'}
    cases = [(None,0,0),('',0,0),('3840x2160',3840,2160),('1920x1080',1920,1080),
             ('1x1',1,1),('8192x4096',8192,4096),('00640x00480',640,480)]
    invalid = ['0x1080','1920x0','8193x2160','3840x4097','999999999999999999x1',
               '1x999999999999999999','1920X1080',' 1920x1080','1920x1080 ',
               '+1920x1080','-1x1','1.5x1','1920','x1080','1920x','1x1x1','1x1junk']
    variants = {'good': (source, all_wrapped),
                'width': (source.replace('M32(width) = private_carbon_width;', '(void)width;'), wrapped),
                'height': (source.replace('M32(height) = private_carbon_height;', '(void)height;'), wrapped),
                'stack': (source, wrapped.replace('c->esp+=12;', 'c->esp+=8;', 1)),
                'unset': (source.replace('if (!value || !*value) return;', 'if (!value || !*value) { private_carbon_width=1; return; }'), wrapped)}
    with tempfile.TemporaryDirectory(prefix='private-resolution-') as td:
        tmp = Path(td)
        for name, (include, code) in variants.items():
            (tmp/'resolution.inc').write_text('#define PRIVATE_CARBON_SKIPFE 1\n'+include)
            (tmp/'test.c').write_text(HARNESS.replace('WRAPPED', code))
            r = subprocess.run(['clang','-O1','-fsanitize=address,undefined','-I',str(HERE),str(tmp/'test.c'),'-o',str(tmp/'test')],capture_output=True,text=True)
            assert r.returncode == 0, r.stderr[-2000:]
            chosen = cases if name == 'good' else ([cases[0]] if name == 'unset' else [cases[2]])
            for value,w,h in chosen:
                setting = {} if value is None else {'NFS_CARBON_RES':value}
                r = subprocess.run([str(tmp/'test'),str(w),str(h)],env=dict(env,**setting),capture_output=True,text=True)
                assert r.returncode == (0 if name == 'good' else 1), (name,value,r.returncode,r.stderr[-1500:])
            if name == 'good':
                for value in invalid:
                    r = subprocess.run([str(tmp/'test'),'invalid','0'],env=dict(env,NFS_CARBON_RES=value),capture_output=True,text=True)
                    assert r.returncode == 2, (value,r.returncode,r.stderr[-1000:])
            print(f'RES {name}: cases={len(chosen)} exit={0 if name=="good" else 1}')
        (tmp/'resolution.inc').write_text('#define PRIVATE_CARBON_SKIPFE 0\n'+source)
        (tmp/'test.c').write_text(HARNESS.replace('WRAPPED',wrapped))
        subprocess.run(['clang','-O1','-I',str(HERE),str(tmp/'test.c'),'-o',str(tmp/'test')],check=True,capture_output=True)
        r = subprocess.run([str(tmp/'test'),'invalid','0'],env=dict(env,NFS_CARBON_RES='3840x2160'),capture_output=True,text=True)
        assert r.returncode == 2, r.stderr[-1000:]
        tables=tmp/'tables';tables.mkdir()
        for sha, binding in ((CARBON_SHA256,1),('0'*64,0)):
            out=tmp/f'image{binding}';out.mkdir()
            (out/'image.json').write_text(json.dumps({'sha256':sha,'exe':'fixture.exe','imports':{}}))
            (out/'imports.c').write_text('/* fixture */\n')
            try:
                dst=prepare(out,tables)
            except ValueError as error:
                # Registered features bind the entire preparation to their image.
                assert binding==0 and 'feature image digest differs' in str(error), str(error)
                print('RES preparation wrong-image rejected before staging')
                print('RES feature image: good accepted=1 / wrong image rejected=1')
                continue
            boot=(dst/'boot.c').read_text()
            assert f'#define PRIVATE_CARBON_SKIPFE {binding}' in (dst/'game_image.h').read_text()
            assert boot.count('    private_carbon_resolution_setup();') == 1
            assert boot.index('memcpy(G + 0x400000 + va, pe + raw, rs);') < boot.index('    private_carbon_resolution_setup();') < boot.index('dispatch(c, speed_entry);')
            assert (dst/'private_carbon_resolution.h').read_text()==source
    print(f'PRIVATE RESOLUTION PASS modes=6 good={len(cases)} invalid={len(invalid)} mutants=4 wrong-image=2 bindings=2')
    return 0


if __name__ == '__main__':
    sys.exit(main())
