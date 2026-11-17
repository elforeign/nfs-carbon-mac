"""Scripted pursuit observer, parser and live-log acceptance controls (no game).

Native fixture: unset reads=0; request order=enable/heat/force; Cpu preserved;
readiness reset and one retry; observed guest writes=0. Mutants that skip
native work or count inactive vehicles must fail. Stored run excerpts below
are from the OFF, ON and deliberately disabled game runs.
ON: first live at 1.005 s, peak 4, lasted 132.646 s, checker exit 0.
Disabled control: pursuit 1, peak live 0, disabled 1, checker exit 1.
End broken control: pre-change checker on the legacy projection of BUST:
PURSUIT PASS request_t=20.001 start_after=1.000 peak_live=1 lasted=5.000 attempts=1
No end field (end=none); the new end=bust assertion fails, exit 1.
New checker on BUST:
PURSUIT PASS request_t=20.001 start_after=1.000 peak_live=1 lasted=5.000 attempts=1 end=bust end_t=6.000 end_line=4
The end=bust assertion passes, exit 0.
"""
from pathlib import Path
import json
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import private_pursuit as pursuit

# Stored live excerpts: RUN1 OFF is the corrected spare (tool launch 2);
# RUN2 ON is tool launch 3; RUN3 disabled control is tool launch 4.
# The original loading-hook launch had no pursuit lines and failed.
RUN1 = '''f257 t1 carbon_pursuit: t=-1.000 attempt=0 pursuits=0 player=00000000 live=0 unknown=0 onroad=0 pool=0 heat=1.000 disabled=1 nonew=0
f5322 t1 carbon_pursuit: t=-1.000 attempt=0 pursuits=0 player=00000000 live=0 unknown=0 onroad=0 pool=0 heat=1.000 disabled=1 nonew=0
f11223 t1 carbon_pursuit: t=-1.000 attempt=0 pursuits=0 player=00000000 live=0 unknown=0 onroad=0 pool=0 heat=1.000 disabled=1 nonew=0'''
RUN2 = '''f298 t1 carbon_pursuit: t=-1.000 attempt=0 pursuits=0 player=00000000 live=0 unknown=0 onroad=0 pool=0 heat=1.000 disabled=1 nonew=0
f4736 t1 carbon_pursuit: request t=20.004 attempt=1 enabled=1
f4880 t1 carbon_pursuit: t=1.005 attempt=1 pursuits=1 player=50083bb0 live=1 unknown=0 onroad=1 pool=1 heat=1.001 disabled=0 nonew=0
f18748 t1 carbon_pursuit: t=106.523 attempt=1 pursuits=1 player=50083bb0 live=4 unknown=0 onroad=4 pool=4 heat=1.420 disabled=0 nonew=0
f21890 t1 carbon_pursuit: t=133.651 attempt=1 pursuits=1 player=50083bb0 live=4 unknown=0 onroad=4 pool=4 heat=1.533 disabled=0 nonew=0'''
RUN3 = '''f292 t1 carbon_pursuit: t=-1.000 attempt=0 pursuits=0 player=00000000 live=0 unknown=0 onroad=0 pool=0 heat=1.000 disabled=1 nonew=0
f4213 t1 carbon_pursuit: request t=20.008 attempt=1 enabled=0
f4325 t1 carbon_pursuit: t=1.004 attempt=1 pursuits=1 player=50083bb0 live=0 unknown=0 onroad=0 pool=0 heat=1.001 disabled=1 nonew=0
f6006 t1 carbon_pursuit: t=16.092 attempt=1 pursuits=1 player=50083bb0 live=0 unknown=0 onroad=0 pool=0 heat=1.050 disabled=1 nonew=0
f9060 t1 carbon_pursuit: t=41.269 attempt=1 pursuits=1 player=50083bb0 live=0 unknown=0 onroad=0 pool=0 heat=1.050 disabled=1 nonew=0'''

HARNESS = r'''
#include "funcs.h"
#include "host.h"
#include <stdarg.h>
#include <stdlib.h>
uint8_t *G;
int diag_on=1;
static uint64_t now=1000000000ull;
static unsigned reads, logs, calls, originals, profile_reads;
static uint32_t addresses[8], args[8];
static char line[512];
static uint32_t r32(uint32_t a){++reads;if(a==0xA97A7C||(a>=0x40000&&a<0x70000))++profile_reads;uint32_t v;memcpy(&v,G+a,4);return v;}
static uint8_t r8(uint32_t a){++reads;return G[a];}
uint64_t host_ticks(void){return now;}
void diag_event(const char *fmt,...){va_list ap;va_start(ap,fmt);vsnprintf(line,sizeof line,fmt,ap);va_end(ap);++logs;}
uint32_t call_guest(Cpu *c,uint32_t a,int n,const uint32_t *v){
 if(!originals||n!=1||calls>=8)abort();addresses[calls]=a;args[calls++]=v[0];c->eax=0xDEAD;c->esp-=4;return 0;
}
#undef M32
#undef M8
#define M32(a) r32(a)
#define M8(a) r8(a)
#include "carbon_pursuit.h"
static void put(uint32_t a,uint32_t v){memcpy(G+a,&v,4);}
static void original(Cpu *c){++originals;c->eax=123;}
#define CHECK(x) do{if(!(x)){fprintf(stderr,"FAIL %d %s [%s]\n",__LINE__,#x,line);exit(1);}}while(0)
static void frame(Cpu *c){Cpu expected=*c;expected.eax=123;carbon_pursuit_frame(c,original);CHECK(!memcmp(c,&expected,sizeof *c));}
int main(int argc,char **argv){
 CHECK(argc==2);G=calloc(1,0xC00000);CHECK(G);Cpu c={0};c.esp=0x90000;
 if(!strcmp(argv[1],"unset")){
  unsetenv("NFS_CARBON_PURSUIT");frame(&c);frame(&c);CHECK(originals==2&&!reads&&!logs&&!calls);puts("unset reads=0 calls=0 native=2");return 0;
 }
 if(!strcmp(argv[1],"invalid")){
  setenv("NFS_CARBON_PURSUIT","20,nan",1);frame(&c);CHECK(!reads&&!logs&&!calls);return 0;
 }
 setenv("NFS_CARBON_PURSUIT",!strcmp(argv[1],"broken")?"20,1,off":"20,1",1);
 if(!strcmp(argv[1],"diag-off"))diag_on=0;
 put(0xA9FF5C,0x10000);put(0xA9FF64,1);put(0x10000,0x11020);put(0x11020,0x12000);put(0x12004,0x76E810);put(0x11018,0x20000);
 put(0xA99BBC,6);put(0xB4CFE0,0x21000);put(0x21024,3);put(0xA98284,0x22000);put(0x28A18,3);put(0xA9E874,0x3004C);put(0x30140,0x30140);
 put(0x20004,0x23000);put(0x23000,0x24000);put(0x23004,0x24018);
 put(0x24000,0x400000);put(0x24008,0x4061D0);put(0x2400C,0x25000);put(0x24010,0x500000);put(0x2501C,0x3F800000);
 frame(&c);now+=19000000000ull;frame(&c);CHECK(!calls);
 put(0xB4D964,1);frame(&c);put(0xB4D964,0);now+=1000000000ull;frame(&c);now+=19000000000ull;frame(&c);CHECK(!calls);
 now+=1000000000ull;frame(&c);CHECK(calls==3&&carbon_pursuit_attempt==1);
 CHECK(addresses[0]==0x6513E0&&addresses[1]==0x65C550&&addresses[2]==0x651430);
 CHECK(args[0]==(unsigned)(strcmp(argv[1],"broken")!=0)&&args[1]==0x3F800000&&args[2]==0);
 if(!strcmp(argv[1],"diag-off"))CHECK(!logs&&!profile_reads);
 if(!strcmp(argv[1],"success")){
  put(0x30140,0x31000);put(0x30148,1);put(0x31000,0x30140);put(0x31008,0x32000);put(0x320D0,0x33000);put(0x3301C,0x20000);
  now+=1000000000ull;frame(&c);CHECK(carbon_pursuit_seen);
  put(0x30148,0);put(0x30140,0x30140);now+=60000000000ull;frame(&c);CHECK(calls==3);
  puts("success attempts=1 after pursuit disappears");free(G);return 0;
 }
 if(!strcmp(argv[1],"end")){
  put(0xA97A7C,0x40000);put(0x400D4,0x41000);put(0x41000,0x42000);
  put(0x6B514,7);put(0x6B510,9);put(0x66330,10000);
  now+=1000000000ull;frame(&c);CHECK(strstr(line,"status=0 busts=7 evades=9 cash=10000"));
  put(0x30140,0x31000);put(0x30148,1);put(0x31000,0x30140);put(0x31008,0x32000);put(0x320D0,0x33000);put(0x3301C,0x20000);
  put(0x32298,3);now+=1000000000ull;frame(&c);CHECK(strstr(line,"status=3 busts=7"));
  put(0x32298,4);now+=1000000000ull;frame(&c);CHECK(strstr(line,"status=4 busts=7"));
  put(0xA99BBC,3);put(0xA9FF64,0);put(0x6B514,8);put(0x66330,9750);
  unsigned prior=logs;now+=1000000000ull;frame(&c);
  CHECK(logs==prior+1&&strstr(line,"player=00000000")&&strstr(line,"busts=8 evades=9 cash=9750"));
  puts("end status=3/4 counters=8/9 cash=10000/9750 not-ready-sampled=1");free(G);return 0;
 }
 now+=29000000000ull;frame(&c);CHECK(calls==3);now+=1000000000ull;frame(&c);CHECK(calls==6&&carbon_pursuit_attempt==2);
 now+=60000000000ull;frame(&c);CHECK(calls==6);
 /* Independent linked-list and vehicle fixture, two entries: inactive and unknown. */
 put(0x30140,0x31000);put(0x30148,1);put(0x31000,0x30140);put(0x31008,0x32000);put(0x320D0,0x33000);put(0x3301C,0x20000);
 put(0x3204C,0x34000);put(0x32054,2);put(0x34000,0x35000);put(0x34004,0x36000);put(0x35000,0x37000);put(0x36000,0x38000);put(0x3709C,0x6D80C0);
 uint8_t *before=malloc(0xC00000);CHECK(before);memcpy(before,G,0xC00000);
 carbon_pursuit_sample(0x3004C,0x20000,now);CHECK(!memcmp(before,G,0xC00000));
 CHECK(strstr(line,"player=00032000 live=0 unknown=1")&&strstr(line,"heat=1.000"));
 put(0x350A8,1);carbon_pursuit_sample(0x3004C,0x20000,now);CHECK(strstr(line,"live=1 unknown=1"));
 put(0x3301C,0xDEAD);CHECK(!carbon_pursuit_find(0x30000,0x20000));
 puts("observer calls=6 attempts=2 readiness-reset=1 guest-writes=0 live=1 unknown=1 heat=1");free(before);free(G);return 0;
}
'''


def run(command, expected=0):
    result = subprocess.run(list(map(str, command)), capture_output=True, text=True)
    assert result.returncode == expected, (command, result.returncode, result.stderr[-3000:])
    return result


def sample(t, player='1234', live=1, attempt=1, status=0, busts=7, evades=9, cash=10000):
    return (f'carbon_pursuit: t={t} attempt={attempt} pursuits=1 player={player} '
            f'live={live} unknown=0 onroad=1 pool=1 heat=1.000 disabled=0 nonew=0 '
            f'status={status} busts={busts} evades={evades} cash={cash}')


def main():
    hook = json.loads((HERE / 'private_runtime/hooks/pursuit.json').read_text())
    feature = json.loads((HERE / 'private_runtime/features/pursuit.json').read_text())
    assert hook['hooks'][0]['provider'] == 'carbon_pursuit_frame'
    assert hook['hooks'][0]['address'] == '006B7930'
    assert feature['staged_sources'] == {'carbon_pursuit.c': 'carbon_pursuit.h'}
    request = 'carbon_pursuit: request t=20.001 attempt=1 enabled=1'
    assert not pursuit.check(['today: no pursuit observer'])[0]
    assert pursuit.check([], True)[0]  # Unset switch emits no diagnostics.
    assert pursuit.check([request, sample(0), sample(8)])[0]
    assert not pursuit.check([request, sample(16)])[0]
    assert pursuit.check([request, sample(15)])[0]
    assert not pursuit.check([request, sample(1, live=0)])[0]
    assert not pursuit.check([sample(1)])[0]
    assert not pursuit.check([sample(1), request])[0]
    assert not pursuit.check([request, request, sample(1)])[0]
    assert not pursuit.check([request, sample(1, attempt=2)])[0]
    assert 'lasted=5.000' in pursuit.check([request, sample(1), sample(6, player='0'), sample(20)])[1]
    baseline = sample(-1, player='0', live=0, attempt=0)
    bust = [baseline, request, sample(1), sample(6, player='0', live=0, busts=8, cash=9750)]
    for reason, ending in (
            ('bust', sample(6, player='0', live=0, busts=8)),
            ('evade', sample(6, player='0', live=0, evades=10)),
            ('bust', sample(6, status=3)), ('evade', sample(6, status=4)),
            ('none', sample(6, player='0', live=0)),
            ('none', sample(6, player='0', live=0, status=3)),
            ('none', sample(6, status=2)),
            ('none', sample(6, busts=6, evades=8))):
        passed, result = pursuit.check([baseline, request, sample(1), ending])
        assert passed and f'end={reason} ' in result, result
    assert 'end=none ' in pursuit.check([request, sample(1, busts=100, evades=200)])[1]
    assert 'end=none ' in pursuit.check([baseline, sample(0, status=3)])[1]
    assert 'end=none ' in pursuit.check([request, sample(1, busts='na', evades='na'),
                                       sample(6, busts=100, evades=200)])[1]
    assert 'end=bust ' in pursuit.check([baseline, request, sample(1),
                                       sample(3, busts='na', evades='na'), bust[-1]])[1]
    assert not pursuit.check([request, sample(1)], True)[0]
    assert 'end_line=4' in pursuit.check(bust)[1]
    print('BUST:', pursuit.check(bust)[1])
    for excerpt, off, expected in ((RUN1, True, True), (RUN2, False, True), (RUN3, False, False)):
        assert excerpt and len(excerpt.splitlines()) < 20
        passed, result = pursuit.check(excerpt.splitlines(), off)
        assert passed == expected, result
        print(result)
    base = HERE / 'out/carbon-base'
    if not (base / 'funcs.h').is_file():
        print('SKIP: observer fixture needs private generated headers')
        return 3
    source = (HERE / 'private_runtime/carbon_pursuit.h').read_text()
    with tempfile.TemporaryDirectory(prefix='pursuit-test-') as tmpdir:
        tmp = Path(tmpdir)
        for label, excerpt, off, expected in (('off', RUN1, True, 0), ('on', RUN2, False, 0), ('broken', RUN3, False, 1), ('old', 'no pursuit diagnostics', False, 1)):
            log = tmp / (label + '.log')
            log.write_text(excerpt)
            command = [sys.executable, '-I', HERE / 'private_pursuit.py', log]
            if off:
                command.append('--expect-off')
            run(command, expected)
        (tmp / 'fixture.c').write_text(HARNESS)
        variants = {'good': source,
                    'skip-native': source.replace('    original(c);', '    (void)original;'),
                    'inactive-live': source.replace('else if (M32(v + 0xA8))', 'else if (v)')}
        for name, text in variants.items():
            (tmp / 'carbon_pursuit.h').write_text(text)
            binary = tmp / name
            run(['clang', '-O1', '-g', '-fsanitize=address,undefined', '-I', HERE,
                 '-I', HERE.parent / 'runtime', '-I', base, tmp / 'fixture.c', '-o', binary])
            modes = ('unset', 'invalid', 'on', 'broken', 'success', 'diag-off', 'end') if name == 'good' else ('on',)
            for mode in modes:
                result = run([binary, mode], 0 if name == 'good' else 1)
                print(f'{name}/{mode}: {(result.stdout or result.stderr).strip()[:300]}')
    print('private_pursuit_test PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
