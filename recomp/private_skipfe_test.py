"""Retail SkipFE settings: native memory fixture, no game or GPU.

Good: 23 cases preserve or change exactly the decoded bytes; 53 invalid inputs
exit 2 before writes. Nine broken enable/movie/track/car/start/traffic/event/opponents/mode writes fail (exit 1).
Traffic good: requested=50, observed=50; skipped-write control retains the
0xA5A5A5A5 sentinel instead of float 50 and exits 1. Unset preserves every byte.
The rigid-body axis mutant also fails; sampling has a late-read mutant.
Height controls span 0.2 and 20 m.
Generated boot orders PE copy < setup < entry and binds the executable hash.
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
from build_private_runtime import prepare, CARBON_SKIPFE_SHA256
import private_world as world

HARNESS = r'''
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static uint8_t *G, *expected;
#define M32(a) (*(uint32_t *)(G+(a)))
static uint32_t allocations;
static uint32_t galloc(uint32_t n) { ++allocations; return 0xB00000 + (allocations - 1) * 0x100; }
#include "skipfe.inc"
#define CHECK(x) do { if (!(x)) { fprintf(stderr,"SKIPFE CHECK line %d: %s\n",__LINE__,#x);exit(1); } } while(0)
static void unchanged(void) { CHECK(!allocations); CHECK(!memcmp(G,expected,0xC00000)); }
int main(int argc, char **argv) {
 CHECK(argc==7);
 G=malloc(0xC00000);expected=malloc(0xC00000);CHECK(G&&expected);
 memset(G,0,0xC00000);float pos[3];CHECK(!private_carbon_player_position(pos));
 M32(0xA9FF64)=1;M32(0xA9FF5C)=0x3000;M32(0x3000)=0x4000;
 M32(0x4000)=0x9EC8C0;M32(0x9EC8C4)=0x76E810;
 M32(0x3ff8)=0x5000;M32(0x5000)=0x9E4BB0;M32(0x9E4C10)=0x6D7EA0;
 M32(0x504c)=0x6000;M32(0x6000)=0x9E3DD0;M32(0x9E3DF0)=0x6C6FF0;
 M32(0x6030)=0x7000;M32(0x7000)=0x8000;
 float physics[3]={-20,30,10};memcpy(G+0x8010,physics,12);
 if(PRIVATE_CARBON_SKIPFE)CHECK(private_carbon_player_position(pos)&&pos[0]==10&&pos[1]==20&&pos[2]==30);
 M32(0x9E3DF0)=0;CHECK(!private_carbon_player_position(pos));M32(0x9E3DF0)=0x6C6FF0;
 M32(0x6030)=0;CHECK(!private_carbon_player_position(pos));M32(0x6030)=0x7000;
 M32(0xA9FF64)=3;CHECK(!private_carbon_player_position(pos));M32(0xA9FF64)=1;
 M32(0x4000)=0;CHECK(!private_carbon_player_position(pos));
 memset(G,0xA5,0xC00000);
 M32(0xA9E620)=0;M32(0xA9E6D8)=0;M32(0xA6313C)=5000;M32(0xA63144)=0x9C94B4;
 strcpy((char*)G+0x9C94B4,"viper");memcpy(expected,G,0xC00000);
 if (!strcmp(argv[1],"invalid")) { atexit(unchanged); private_carbon_skipfe_setup(); return 9; }
 private_carbon_skipfe_setup();
 int active=atoi(argv[1]);
 CHECK(allocations==(unsigned)(active&&*argv[3])+(unsigned)(active&&*argv[6]));
 if(active) {
   *(uint32_t*)(expected+0xA9E620)=1;*(uint32_t*)(expected+0xA9E6D8)=1;
   *(uint32_t*)(expected+0xA6313C)=(uint32_t)strtoul(argv[2],NULL,10);
   if(*argv[3]) {
     CHECK(M32(0xA63144)==0xB00000);
     *(uint32_t*)(expected+0xA63144)=0xB00000;
     strcpy((char*)expected+0xB00000,argv[3]);
   }
   if(*argv[6]) {
     char id[64];unsigned mode,opponents;CHECK(sscanf(argv[6],"%63[^:]:%u:%u",id,&mode,&opponents)==3);
     uint32_t name=0xB00000+(*argv[3]?0x100:0);CHECK(M32(0xA63140)==name);
     *(uint32_t*)(expected+0xA63140)=name;strcpy((char*)expected+name,id);
     *(uint32_t*)(expected+0xA9E630)=opponents;*(uint32_t*)(expected+0xA9E648)=mode;
   }
   if(*argv[4]) {
     float x,y,z; CHECK(sscanf(argv[4],"%f,%f,%f",&x,&y,&z)==3);
     memcpy(expected+0xA9E6E0,&x,4);memcpy(expected+0xA9E6E4,&y,4);memcpy(expected+0xA9E6E8,&z,4);
   }
   if(*argv[5]) {
     float density=strtof(argv[5],NULL);
     memcpy(expected+0xA9E640,&density,4);
   }
 }
 CHECK(!memcmp(G,expected,0xC00000));
 puts("SKIPFE PASS exact memory and allocation checks");free(expected);free(G);return 0;
}
'''


def check_position_probe(tmp):
    """Good: 1 Hz, original player argument. Broken: post-override sampling fails.

    Flat trace span=0.2 m; falling trace span=20 m. A 10 s trace and reversed
    timestamps are rejected, so seven lifecycle signals alone prove no height.
    """
    body = 'void f_00001000(Cpu *c) { c->eax=7; }'
    wrapped, _ = world.instrument(body, {'predict': {'address': 0x1000}})
    harness = r'''
#include "runtime.h"
#include <stdlib.h>
#include <stdarg.h>
#include <stdio.h>
uint8_t *G; int private_world_on=0,diag_on=1; static unsigned logs; static uint64_t ticks=1000000000;
void private_world_prop_player(const float *position){}
static uint32_t original=0x2000;
int private_carbon_player_position(float *out){memcpy(out,G+original,12);return 1;}
uint64_t host_ticks(void){return ticks;}
void diag_event(const char *format,...){va_list ap;va_start(ap,format);double t=va_arg(ap,double);
 double x=va_arg(ap,double),y=va_arg(ap,double),z=va_arg(ap,double);va_end(ap);
 if(x!=10 || y!=20 || z!=30 || t!=ticks/1e9)exit(1);++logs;}
void private_world_before(Cpu *c,unsigned h){M32(c->esp+8)=0x3000;original=0x3000;}
void private_world_after(Cpu*c,unsigned h,uint32_t sp,uint32_t self){}
WRAPPED
int main(void){G=calloc(1,65536);Cpu c={0};c.esp=0x1000;M32(c.esp+8)=0x2000;
 MF32(0x2000)=10;MF32(0x2004)=20;MF32(0x2008)=30;
 f_00001000(&c);if(logs || c.eax!=7)return 1;
 private_world_on=1;f_00001000(&c);if(logs!=1)return 1;
 M32(c.esp+8)=0x2000;f_00001000(&c);if(logs!=1)return 1;
 ticks+=1000000000;M32(c.esp+4)=1;f_00001000(&c);if(logs!=1)return 1;
 M32(c.esp+4)=0;M32(c.esp+8)=0x2000;original=0x2000;f_00001000(&c);if(logs!=2)return 1;
 free(G);return 0;}
'''
    for name, source in [('good', wrapped), ('late', wrapped.replace(
            '    private_world_position_sample(c);\n    private_world_before(c, 6);',
            '    private_world_before(c, 6);\n    private_world_position_sample(c);'))]:
        (tmp/'position.c').write_text(harness.replace('WRAPPED', source))
        subprocess.run(['clang','-O1','-fsanitize=address,undefined','-I',str(HERE),
                        str(tmp/'position.c'),'-o',str(tmp/'position')],check=True,capture_output=True)
        r = subprocess.run([str(tmp/'position')],capture_output=True,text=True)
        assert r.returncode == (0 if name == 'good' else 1), (name,r.stderr)
    def trace(falling=False):
        return '\n'.join(f'PRIVATE WORLD POSITION time={s} render=10,20,{40-s if falling else 40+(s%2)*.2} source=player0' for s in range(31))
    flat, fall = world.height_summary(trace()), world.height_summary(trace(True))
    assert flat['flat'] and abs(flat['span']-.2)<1e-6 and fall['span']==20 and not fall['flat']
    for bad in ('', '\n'.join(trace().splitlines()[:10]), '\n'.join(reversed(trace().splitlines()))):
        try: world.height_summary(bad)
        except ValueError: pass
        else: raise AssertionError('broken height trace accepted')
    print('POSITION PASS native pre-override/1Hz; late-read mutant=1; flat=0.2m fall=20m; invalid=3')


def main():
    source = (HERE / 'private_runtime/carbon_skipfe.h').read_text()
    keys = ['NFS_CARBON_SKIPFE', 'NFS_CARBON_SKIPFE_TRACK', 'NFS_CARBON_SKIPFE_CAR', 'NFS_CARBON_SKIPFE_START', 'NFS_CARBON_SKIPFE_TRAFFIC', 'NFS_CARBON_SKIPFE_EVENT']
    env = {k: v for k, v in os.environ.items() if k not in keys}
    cases = [({}, ['0', '5000', '']),
             ({keys[0]: '0'}, ['0', '5000', '']),
             (dict.fromkeys(keys, ''), ['0', '5000', '']),
             ({keys[0]: '1'}, ['1', '5000', '']),
             ({keys[1]: '2000'}, ['1', '2000', '']),
             ({keys[1]: '5000'}, ['1', '5000', '']),
             ({keys[2]: 'bmwm3gtre46'}, ['1', '5000', 'bmwm3gtre46']),
             (dict(zip(keys, ['0', '2000', 'corvettez06'])), ['1', '2000', 'corvettez06']),
             ({keys[1]: '4294967295', keys[2]: 'x'*63}, ['1', '4294967295', 'x'*63])]
    cases = [(settings, args + ['']) for settings, args in cases]
    cases += [({keys[3]: value}, ['1','5000','',value]) for value in ('2880,0,40', '-1.25,2e1,.5')]
    cases = [(settings, args + ['']) for settings, args in cases]
    cases += [({keys[4]: value}, ['1','5000','','',value]) for value in ('0','50','100','12.5','5e1')]
    cases += [({keys[0]:'1',keys[4]:''}, ['1','5000','','',''])]
    invalid = [{keys[0]: v} for v in ('yes', '2', '-1')]
    invalid += [{keys[1]: v} for v in ('0', '-1', ' 2000', '2000 ', '2k', '4294967296', '99999999999999999999')]
    invalid += [{keys[2]: v} for v in ('x'*64, 'viper other', '../viper', 'viper=1')]
    invalid += [{keys[3]: v} for v in ('0,0,0','1,2','1,2,3,4','1,2,','1,2,nan','inf,2,3',
                                     '1e99,2,3',' 1,2,3','1, 2,3','1,2,3 ','1;2;3')]
    invalid += [{keys[4]: v} for v in ('-1','101','100.5','nan','inf','1e99',' 50','50 ','50x','+','1e-99')]
    cases = [(settings, args + ['']) for settings, args in cases]
    cases += [({keys[5]: value}, ['1','5000','','','',value]) for value in
              ('qr.3.1:0:1','4.duel:3:1','tn.3.1:0:1','qr.9.9:0:1','x'*63+':0:7')]
    cases += [({keys[2]:'rx8',keys[5]:'qr.3.1:0:1'}, ['1','5000','rx8','','','qr.3.1:0:1'])]
    invalid += [{keys[5]: v} for v in ('qr.3.1','qr.3.1:0','qr.3.1:0:1:x',':0:1',
                'QR.3.1:0:1','../x:0:1','x'*64+':0:1','x:-1:1','x:4:1','x:0:0',
                'x:0:8','x:0:4294967296','x:4294967296:1','x: 0:1','x:0:1 ', 'x::1','x:0:')]
    variants = {'good': source}
    for name, write in [('enable', 'M32(0x00A9E620) = 1;'), ('movies', 'M32(0x00A9E6D8) = 1;'),
                        ('track', 'M32(0x00A6313C) = number;'), ('car', 'M32(0x00A63144) = name;'),
                        ('start', 'memcpy(G + 0x00A9E6E0, position, sizeof position);'),
                        ('traffic', 'memcpy(G + 0x00A9E640, &density, sizeof density);'),
                        ('event', 'M32(0x00A63140) = name;'),
                        ('opponents', 'M32(0x00A9E630) = opponents;'),
                        ('mode', 'M32(0x00A9E648) = event_mode;'),
                        ('position', 'position[2] = physics[1];')]:
        assert source.count(write) == 1
        variants[name] = source.replace(write, 'position[2] = physics[0];' if name == 'position' else '(void)0;')
    with tempfile.TemporaryDirectory(prefix='private-skipfe-') as td:
        tmp = Path(td)
        check_position_probe(tmp)
        (tmp / 'test.c').write_text(HARNESS)
        for name, selected in variants.items():
            (tmp / 'skipfe.inc').write_text('#define PRIVATE_CARBON_SKIPFE 1\n' + selected)
            r = subprocess.run(['clang', '-O1', '-fsanitize=address,undefined', str(tmp/'test.c'),
                                '-o', str(tmp/'test')], capture_output=True, text=True)
            if r.returncode: raise RuntimeError(r.stderr[-2000:])
            chosen = cases if name == 'good' else [(dict(zip(keys, ['1', '2000', 'corvettez06', '2880,0,40', '50', '4.duel:3:1'])), ['1', '2000', 'corvettez06', '2880,0,40', '50', '4.duel:3:1'])]
            for settings, args in chosen:
                r = subprocess.run([str(tmp/'test'), *args], env=dict(env, **settings), capture_output=True, text=True)
                assert r.returncode == (0 if name == 'good' else 1), (name, settings, r.stderr)
            if name == 'good':
                for settings in invalid:
                    r = subprocess.run([str(tmp/'test'), 'invalid', '', '', '', '', ''], env=dict(env, **settings), capture_output=True, text=True)
                    assert r.returncode == 2, (settings, r.stderr)
            print(f'{name}: {len(chosen)} memory cases exit={0 if name == "good" else 1}')
        # A different private executable must fail closed before any guest write.
        (tmp/'skipfe.inc').write_text('#define PRIVATE_CARBON_SKIPFE 0\n' + source)
        subprocess.run(['clang', '-O1', str(tmp/'test.c'), '-o', str(tmp/'test')], check=True, capture_output=True)
        r = subprocess.run([str(tmp/'test'), 'invalid', '', '', '', '', ''], env=dict(env, NFS_CARBON_SKIPFE='1'), capture_output=True, text=True)
        assert r.returncode == 2, r.stderr
        # Exercise the actual builder transformation with synthetic image metadata.
        tables = tmp/'tables'; tables.mkdir()
        for sha, expected in ((CARBON_SKIPFE_SHA256, 1), ('0'*64, 0)):
            out = tmp/f'image{expected}'; out.mkdir()
            (out/'image.json').write_text(json.dumps({'sha256':sha, 'exe':'fixture.exe', 'imports':{}}))
            (out/'imports.c').write_text('/* synthetic import table */\n')
            try:
                dst = prepare(out, tables)
            except ValueError as error:
                # The standalone wrong-image helper above remains inert; an
                # image-bound feature additionally prevents runtime preparation.
                assert expected == 0 and 'feature image digest differs' in str(error), str(error)
                print('SKIPFE preparation wrong-image rejected before staging')
                print('SKIPFE feature image: good accepted=1 / wrong image rejected=1')
                continue
            boot = (dst/'boot.c').read_text()
            assert f'#define PRIVATE_CARBON_SKIPFE {expected}' in (dst/'game_image.h').read_text()
            assert boot.count('    private_carbon_skipfe_setup();') == 1
            assert 'private_cars_error(' not in __import__('subprocess').run(['unifdef','-DNFS_GAME=2','-DNFS_GAME_MW=1','-DNFS_GAME_PRIVATE=2'],input=boot,capture_output=True,text=True).stdout
            assert 'MW car-catalog diagnostic disabled' in boot
            assert 'private_world_camera_logged && getenv("NFS_CARBON_SKIPFE_START")' in (dst/'game_world.inc').read_text()
            assert boot.index('memcpy(G + 0x400000 + va, pe + raw, rs);') < boot.index('    private_carbon_skipfe_setup();') < boot.index('dispatch(c, speed_entry);')
    print(f'PRIVATE SKIPFE PASS valid={len(cases)} invalid={len(invalid)} mutants=10 image_bindings=2')
    return 0


if __name__ == '__main__':
    sys.exit(main())
