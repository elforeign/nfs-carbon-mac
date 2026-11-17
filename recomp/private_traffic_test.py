"""Native traffic observer fixture; no game.

Good: attempts=3, spawned=1, alive=2 (pool=4); exit 0. At the first success
checkpoint EAX=12340001 (AL=1) gives attempts=1/spawned=1; the old whole-EAX
comparison gives attempts=1/spawned=0, exit 1. EAX=12340000 (AL=0) adds 0
spawns; deliberately counting AL==0 also fails the first checkpoint. Off: native
calls=120, guest reads=0, lines=0. Observer guest writes=0; Cpu matches original.
Missing private headers/image: exit 3.
Status includes live density=50 and disabled=0, then density=12.5/disabled=1;
stale density or disable-byte controls exit 1.
"""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
PRIVATE = HERE / 'private_runtime'
IMAGE_SHA = 'baaaaec33873d4ba7e4dbae6a5212049ffdcf9679a35d865d7625b4189952fd3'

HARNESS = r'''
#include "funcs.h"
#include "host.h"
#include <stdarg.h>
#include <stdlib.h>
uint8_t *G;
int diag_on=1;
static unsigned reads, logs, originals, patterns, statuses, spawns;
static uint32_t result;
static char line[512];
static uint32_t r32(uint32_t a){++reads;uint32_t v;memcpy(&v,G+a,4);return v;}
static float rf32(uint32_t a){++reads;float v;memcpy(&v,G+a,4);return v;}
static uint8_t r8(uint32_t a){++reads;return G[a];}
void diag_event(const char *fmt,...){
 va_list ap;va_start(ap,fmt);vsnprintf(line,sizeof line,fmt,ap);va_end(ap);++logs;
 if(strstr(line,"traffic: pattern="))++patterns;
 if(strstr(line,"traffic: status "))++statuses;
 if(strstr(line,"traffic: spawn "))++spawns;
}
#undef M32
#define M32(a) r32(a)
#undef MF32
#define MF32(a) rf32(a)
#undef M8
#define M8(a) r8(a)
#include "carbon_traffic.h"
static void put(uint32_t a,uint32_t v){memcpy(G+a,&v,4);}
static void original(Cpu *c){++originals;c->eax=result;c->ecx=0xDEAD;c->edx=0xBEEF;}
#define CHECK(x) do{if(!(x)){fprintf(stderr,"FAIL %d %s [%s] attempts=%llu spawned=%llu\n",__LINE__,#x,line,carbon_traffic_attempts,carbon_traffic_spawned);exit(1);}}while(0)
static void observe(Cpu *c,int spawn){
 c->ecx=0x10000;Cpu expected=*c;expected.eax=result;expected.ecx=0xDEAD;expected.edx=0xBEEF;
 unsigned calls=originals;
 if(spawn)carbon_traffic_spawn(c,original);else carbon_traffic_choose(c,original);
 CHECK(originals==calls+1);CHECK(!memcmp(c,&expected,sizeof *c));
}
int main(int argc,char **argv){
 CHECK(argc==2);G=calloc(1,0xC00000);CHECK(G);Cpu c={0};c.esp=0x9000;
 if(!strcmp(argv[1],"off")){
  diag_on=0;for(unsigned i=0;i<60;++i){observe(&c,0);observe(&c,1);}
  CHECK(originals==120&&!reads&&!logs&&!carbon_traffic_attempts&&!carbon_traffic_calls);
  puts("off native=120 reads=0 lines=0");free(G);return 0;
 }
 /* Independent pool: two active cars, one inactive car, one null slot. */
 put(0x10100,0x20000);put(0x20010,0xAABBCCDD);
 put(0x1005C,0x30000);put(0x10064,4);
 put(0x30000,0x31000);put(0x30004,0x32000);put(0x30008,0x33000);
 put(0x31000,0x40000);put(0x32000,0x40000);put(0x33000,0x40000);
 put(0x4009C,0x6D80C0);put(0x310A8,1);put(0x330A8,0x1234);
 float density=50;memcpy(G+0xA9E640,&density,4);
 uint8_t *before=malloc(0xC00000);CHECK(before);memcpy(before,G,0xC00000);
 observe(&c,0);CHECK(patterns==1&&statuses==0&&strstr(line,"pattern=aabbccdd"));
 result=0x12340001;observe(&c,1);
 CHECK(carbon_traffic_attempts==1&&carbon_traffic_spawned==1&&spawns==1);
 result=0x12340000;observe(&c,1);
 CHECK(carbon_traffic_attempts==2&&carbon_traffic_spawned==1&&spawns==1);
 result=2;observe(&c,1);
 CHECK(carbon_traffic_attempts==3&&carbon_traffic_spawned==1&&spawns==1);
 for(unsigned i=1;i<60;++i)observe(&c,0);
 CHECK(patterns==1&&statuses==1&&strstr(line,"attempts=3 spawned=1 alive=2 pattern=aabbccdd"));
 CHECK(strstr(line,"density=50 disabled=0"));
 CHECK(!memcmp(before,G,0xC00000));
 density=12.5f;memcpy(G+0xA9E640,&density,4);G[0xA9E644]=1;
 for(unsigned i=0;i<59;++i)observe(&c,0);CHECK(statuses==1);
 observe(&c,0);CHECK(statuses==2);
 CHECK(strstr(line,"density=12.5 disabled=1"));
 /* A collection change with the same key still logs; Cpu ECX was clobbered. */
 put(0x10100,0x21000);put(0x21010,0xAABBCCDD);observe(&c,0);CHECK(patterns==2);
 put(0x10100,0);observe(&c,0);CHECK(patterns==3&&strstr(line,"pattern=00000000"));
 /* Active is sampled anew, not accumulated; unknown is not zero. */
 put(0x310A8,0);CHECK(carbon_traffic_alive(0x10000)==1);
 put(0x4009C,0xBAD);CHECK(carbon_traffic_alive(0x10000)==-1);
 for(unsigned i=2;i<60;++i)observe(&c,0);CHECK(strstr(line,"alive=na"));
 put(0x10064,1025);CHECK(carbon_traffic_alive(0x10000)==-1);
 put(0x10064,1);put(0x1005C,0);CHECK(carbon_traffic_alive(0x10000)==-1);
 put(0x10064,0);CHECK(carbon_traffic_alive(0x10000)==0);
 puts("on attempts=3 spawned=1 alive=2 pool=4 guest-writes=0 Cpu=original cadence=60");
 free(before);free(G);return 0;
}
'''


def run(args, expected=0):
    result = subprocess.run(list(map(str, args)), capture_output=True, text=True)
    assert result.returncode == expected, (args, result.returncode, result.stderr[-2500:])
    return result


def main():
    base = HERE / 'out/carbon-base'
    if not (base / 'funcs.h').is_file() or not (base / 'image.json').is_file():
        print('SKIP: traffic fixture needs private generated headers/image')
        return 3
    image = json.loads((base / 'image.json').read_text())
    if not Path(image['exe']).is_file():
        print('SKIP: traffic fixture needs pinned private image')
        return 3
    sys.path.insert(0, str(HERE))
    from recomp import PE
    from private_hooks import load_registry
    pe = PE(image['exe'], expected_sha256=IMAGE_SHA)
    rows = json.loads((PRIVATE / 'hooks/traffic.json').read_text())['hooks']
    expected = {0x42CE70: 'carbon_traffic_choose', 0x42C950: 'carbon_traffic_spawn'}
    assert {int(r['address'], 16): r['provider'] for r in rows} == expected
    for row in rows:
        address = int(row['address'], 16)
        assert row['image_sha256'] == IMAGE_SHA
        witness = row['witness']
        assert witness['start'] == row['address'] and witness['length'] == 16
        assert hashlib.sha256(pe.read(address, 16)).hexdigest() == witness['sha256']
    # Pin the two read-only equivalents independently of the observer's constants.
    assert pe.read(0x6D80C0, 14).hex() == '8b91a800000033c085d20f95c0c3'
    assert pe.read(0x4613E0, 13).hex() == '8b0185c074048b4010c333c0c3'
    feature = json.loads((PRIVATE / 'features/traffic.json').read_text())
    assert feature['image_sha256'] == IMAGE_SHA
    assert set(feature['sources']) == {'carbon_traffic.c'}
    assert feature['staged_sources'] == {'carbon_traffic.c': 'carbon_traffic.h'}
    source = (PRIVATE / 'carbon_traffic.h').read_text()
    assert feature['bindings']['carbon_traffic.c']['sha256'] == hashlib.sha256(source.encode()).hexdigest()
    with tempfile.TemporaryDirectory(prefix='traffic-test-') as directory:
        tmp = Path(directory)
        (tmp / 'traffic.json').write_text(json.dumps({'version': 1, 'hooks': rows}))
        registry = load_registry(pe, [(a, a + 16, '') for a in expected], tmp)
        assert set(registry) == set(expected)
        (tmp / 'fixture.c').write_text(HARNESS)
        variants = {'good': source,
                    'whole-register': source.replace('(uint8_t)c->eax == 1', 'c->eax == 1'),
                    'wrong-success': source.replace('(uint8_t)c->eax == 1', '(uint8_t)c->eax == 0'),
                    'skip-original': source.replace('    original(c);', '    (void)original;'),
                    'pool-is-alive': source.replace('if (M32(v + 0xA8))', 'if (v)'),
                    'stale-density': source.replace('(double)MF32(0x00A9E640)', '0.0'),
                    'stale-disabled': source.replace('(unsigned)M8(0x00A9E644)', '0u'),
                    'wrong-key': source.replace('M32(collection + 0x10)', 'collection')}
        for name, text in variants.items():
            assert name == 'good' or text != source
            (tmp / 'carbon_traffic.h').write_text(text)
            binary = tmp / name
            run(['clang', '-O1', '-g', '-fsanitize=address,undefined', '-I', HERE,
                 '-I', HERE.parent / 'runtime', '-I', base, '-I', tmp,
                 tmp / 'fixture.c', '-o', binary])
            for mode in (('off', 'on') if name == 'good' else ('on',)):
                result = run([binary, mode], 0 if name == 'good' else 1)
                print(f'{name}/{mode}: {(result.stdout or result.stderr).strip()[:400]}')
    print('private_traffic_test PASS witnesses=2 mutants=7')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
