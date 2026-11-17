"""Audit-only isolation: unsafe source is rejected and never edited.

Real x360 MW implementations and its graphics write are rejected;
real lamp constructor has 1 forbidden initializer section, selected host has 0.
Macro/global/alias fixture: original 3 MW reads rejected, selected 0 reads;
FILETIME remains 10,000,000 and passes the same 4 executable value checks.
C++ engine implementations are rejected; original owner installs 1 forbidden
initializer section, explicit disabled owner with no static destruction has 0.
Reintroduced rewrite call: good 0 / broken 1 rejected (also game_layers_test).
"""
from pathlib import Path
import argparse
import subprocess
import sys
import tempfile
HERE=Path(__file__).resolve().parent
ROOT=HERE.parent
sys.path.insert(0,str(HERE/'private_runtime'))
from quarantine import quarantine, checked_engine_initializers
from layers import audit_unit, check_audits, audit_preparations


def rejects(action, expected):
    try:action()
    except ValueError as error:
        assert expected in str(error),str(error)
        return str(error)
    raise AssertionError('accepted unsafe source: '+expected)


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--tables',type=Path,default=ROOT/'runtime/gen');args=ap.parse_args()
    if not (args.tables/'x360_engine.inc').is_file():
        print('SKIP: generated MW host tables absent');return 3
    with tempfile.TemporaryDirectory(prefix='private-runtime-isolation-') as td:
        tmp=Path(td)
        flags=['-O1','-w','-fobjc-arc','-I',str(ROOT/'runtime'),'-I',str(HERE),'-I',str(args.tables.parent)]
        ranges=[(0x401000,0x1000000)]
        # Inspect real engine source, including macro expansion and constructors.
        for name,expected in [('x360.m','included MW implementation:'),('lampglow.c','forbidden constructor:')]:
            path=tmp/name;path.write_bytes((ROOT/'runtime'/name).read_bytes());original=path.read_bytes()
            error=rejects(lambda:quarantine(path,flags,ranges),expected)
            assert path.read_bytes()==original
            if name=='x360.m':
                assert 'graphics_reset_request' in error and '0x00982C39' in error
                assert 'shadow_options' in error and 'x360_shadow_map_size' in error
            obj=tmp/(name+'.o')
            r=subprocess.run(['clang',*flags,'-c',str(path),'-o',str(obj)],capture_output=True,text=True)
            assert r.returncode==0,r.stderr[-2000:]
            if name=='lampglow.c':rejects(lambda:checked_engine_initializers([obj]),'1 initializer sections')
            else:checked_engine_initializers([obj])
        portable=tmp/'boot.c'
        original='''#include "host.h"
static const uint32_t target=0x900004;
#define OLD_FIELD 0x900008
uint32_t old_global(void){return M32(target);}
uint32_t old_macro(void){return M32(OLD_FIELD);}
uint32_t old_alias(void){uint8_t *base=G;return *(uint32_t *)(base+target);}
uint32_t time_value(void){uint32_t unit=10000000;M32(16)=unit;return M32(16);}
'''
        portable.write_text(original)
        before=audit_unit(portable,flags,ranges)['declarations']
        assert {r['name'] for r in before if r['accesses']}=={'old_global','old_macro','old_alias'}
        assert not next(r for r in before if r['name']=='time_value')['accesses']
        error=rejects(lambda:quarantine(portable,flags,ranges),'MW address read:')
        assert error.count('MW address read:')==3 and portable.read_text()==original
        # Explicit compile-time disabled policy fixture, never a quarantine rewrite.
        portable.write_text('''#include "game_select.h"
#if NFS_GAME == NFS_GAME_MW
'''+original+'''#else
#include "host.h"
uint32_t old_global(void){return 0;}
uint32_t old_macro(void){return 0;}
uint32_t old_alias(void){return 0;}
uint32_t time_value(void){uint32_t unit=10000000;M32(16)=unit;return M32(16);}
#endif
''')
        selected_flags=flags+['-DNFS_GAME=2']
        assert quarantine(portable,selected_flags,ranges)==[]
        after=audit_unit(portable,selected_flags,ranges)['declarations']
        assert not any(r['accesses'] for r in after)
        fixture=tmp/'portable.c';fixture.write_text('''#include "host.h"
#include <sys/mman.h>
uint8_t *G;uint32_t old_global(void),old_macro(void),old_alias(void),time_value(void);
int main(void){G=mmap(NULL,1ull<<32,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANON|MAP_NORESERVE,-1,0);if(G==MAP_FAILED)return 2;
M32(0x900004)=123;M32(0x900008)=456;
int fail=old_global()!=0||old_macro()!=0||old_alias()!=0||time_value()!=10000000;
printf("portable address/value checks=%s\\n",fail?"FAIL":"4/4");munmap(G,1ull<<32);return fail;}
''')
        binary=tmp/'portable'
        r=subprocess.run(['clang',*selected_flags,str(portable),str(fixture),'-o',str(binary)],capture_output=True,text=True)
        assert r.returncode==0,r.stderr[-2000:]
        r=subprocess.run([str(binary)],capture_output=True,text=True);assert r.returncode==0,r.stderr;print(r.stdout.strip())
        # The C++ boundary rejects implementations rather than inventing return values.
        engine=tmp/'engine.mm';engine.write_text('''#include <vector>
#include <memory>
static std::unique_ptr<int> dormant_owner;
enum class EngineMode { off, on };
EngineMode engine_mode(){return EngineMode::on;}
std::vector<int> engine_entries(){return {7};}
std::unique_ptr<int> engine_owner(){return std::make_unique<int>(7);}
int &engine_reference(){static int value=7;return value;}
''')
        audit=audit_unit(engine,flags,ranges)
        policy={'sources':{'engine.mm':{'class':'mw','constructors':'forbidden'}},'targets':{'private':{'extra_sources':{}}}}
        error=rejects(lambda:check_audits([audit],policy),'included MW implementation:')
        assert all(name in error for name in ('engine_mode','engine_entries','engine_owner','engine_reference'))
        original=engine.read_bytes()
        rejects(lambda:quarantine(engine,flags,ranges,portable=False),'engine implementation selected')
        assert engine.read_bytes()==original
        obj=tmp/'engine.o'
        cmd=['clang++',*flags,'-c',str(engine),'-o',str(obj)]
        r=subprocess.run(cmd,capture_output=True,text=True);assert r.returncode==0,r.stderr[-2000:]
        rejects(lambda:checked_engine_initializers([obj]),'1 initializer sections')
        r=subprocess.run(cmd[:1]+['-fno-c++-static-destructors']+cmd[1:],capture_output=True,text=True)
        assert r.returncode==0,r.stderr[-2000:];checked_engine_initializers([obj])
        audit_preparations()
        rejects(lambda:audit_preparations({'private_positiont.py':'def obsolete(s):\n return s.replace("a","b")\n'}),'production rewrite call:')
    print('PRIVATE RUNTIME ISOLATION PASS original=3 selected=0 reads FILETIME=0 findings; C++ owner initializers 1/0; rewrite mutant 1 rejected')
    return 0


if __name__=='__main__':raise SystemExit(main())
