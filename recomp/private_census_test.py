"""Streaming census fixture and event-summary acceptance (no game).

Good: loaded=3 (statuses 3/4), bytes=600; wrong status offset +10 instead of
+0C: loaded=0, exits 1 against required 3. Native largest-free agrees for
dirty and clean pools; observer changes 0 guest bytes. Unset/0/diag-off: 0
reads, 0 lines. Zone-change negative control: 0 < required 3, exit 1.
The line ends with slot 0's streaming position (+D0, three floats); a
two-value or nonfinite position is malformed, exit 1.
Engine fixture: slot ages 7/19 and player wheels 2, then 0; unknown getter
reports -1. Invalid wheel count 5 is rejected. All modes off still read 0 bytes.
The line carries slot 0's velocity (+E0) and the player's getter address
(00000000 when the handle is not reached), so a -1 names the class it met:
Traffic 006FB690 reports wheels -1 with suspension 006FB690. Velocity read
from +D0 instead (the streaming position) prints 1234.500,... and fails.
Loading: original called once per evaluation, post-call flag 1/0/1 yields 2,
next sample 0; pre-call-read control yields 1 and fails. Off: zero reads.
Heading: (-3,-4) emits (-.6,0,-.8); before-native mutant leaves (1,0,0)
and fails. Exactly 12 output bytes change; five malformed headings exit 2.
Vehicles: traffic 1 active of 4 (one inactive, one null, one bad vtable =
unknown 1), cops 2/2 with the pursuit member starred, exact positions, 0 guest
bytes changed; no managers = no line. ISimable read at the IVehicle (v, not
v-94) fails the witness: traffic 0/4, unknown 4, exit 1.
Exit 3 without translated private originals used for the query cross-check.
"""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
PRIVATE = HERE / 'private_runtime'
sys.path.insert(0, str(HERE))
import private_census as census
from private_hooks_test import body

QUERY_SHA = '03990d2eff7acd83b011ccb167a87883f59f1587e06646c471c005c42fac8fdc'
CONTACT_SHA = {
    'f_006F8A60': '0e8df31ebbb2fd7800bcd4d6816fea95c3f7fc33d48034970dd9228f10d231a2',
    'f_006FC8C0': 'b06299d750cb27559bb9095a270c716e819f6050d022369ce3ad33f808d268e8',
}
HARNESS = r'''
#include "funcs.h"
#include "host.h"
#include <stdarg.h>
#include <stdlib.h>
uint8_t *G;
int diag_on=1;
static unsigned reads, logs;
static char line[4096];
static uint32_t r32(uint32_t a){++reads;uint32_t v;memcpy(&v,G+a,4);return v;}
static uint16_t r16(uint32_t a){++reads;uint16_t v;memcpy(&v,G+a,2);return v;}
static uint8_t r8(uint32_t a){++reads;return G[a];}
#define CHECK(x) do{if(!(x)){fprintf(stderr,"FAIL %d %s: %s\n",__LINE__,#x,line);exit(1);}}while(0)
void diag_event(const char *format,...){va_list ap;va_start(ap,format);vsnprintf(line,sizeof line,format,ap);va_end(ap);++logs;}
void abi_violation(Cpu *c,uint32_t a,uint32_t b,uint32_t s,uint32_t d,uint32_t p,uint32_t sp){(void)c;(void)a;(void)b;(void)s;(void)d;(void)p;(void)sp;abort();}
#include "native.inc"
#undef M32
#undef M16
#undef M8
#define M32(a) r32(a)
#define M16(a) r16(a)
#define M8(a) r8(a)
#include "carbon_census.h"
static uint32_t carbon_autodrive_player(void){return 0x50000;}
static void put32(uint32_t a,uint32_t v){memcpy(G+a,&v,4);}
static void put16(uint32_t a,uint16_t v){memcpy(G+a,&v,2);}
static unsigned evaluations;
static void evaluate(Cpu *c){++evaluations;G[0xB7420C]=(evaluations%2);c->eax=0x76543210;c->esp+=4;}
static unsigned starts;
static void native_start(Cpu *c){++starts;const float h[3]={1,0,0};memcpy(G+0x60000,h,12);c->eax=0x12345678;c->esp+=4;}
int main(int argc,char **argv){
 CHECK(argc==2);G=calloc(1,0xC00000);CHECK(G);
 unsetenv("NFS_CARBON_C3_HEADING");
 if(!strncmp(argv[1],"bad-heading=",12)){
   setenv("NFS_CARBON_C3_HEADING",argv[1]+12,1);setenv("NFS_CARBON_SKIPFE_START","1,2,3",1);setenv("NFS_CARBON_SKIPFE","1",1);
   Cpu spawn={0};spawn.esp=0x30000;put32(0x30008,0x60000);carbon_c3_start(&spawn,native_start);CHECK(0);
 }
 if(!strcmp(argv[1],"off"))unsetenv("NFS_CARBON_CENSUS");
 else if(!strcmp(argv[1],"zero"))setenv("NFS_CARBON_CENSUS","0",1);
 else setenv("NFS_CARBON_CENSUS","1",1);
 if(!strcmp(argv[1],"diag-off"))diag_on=0;
 Cpu evaluation={0};evaluation.esp=0x30000;
 carbon_census_evaluate(&evaluation,evaluate);
 CHECK(evaluations==1&&evaluation.eax==0x76543210&&evaluation.esp==0x30004);
 if(strcmp(argv[1],"on")){
   carbon_census_sample();carbon_census_sample();CHECK(!reads&&!logs);
   printf("OFF PASS mode=%s reads=%u lines=%u\n",argv[1],reads,logs);return 0;
 }
 carbon_census_evaluate(&evaluation,evaluate);carbon_census_evaluate(&evaluation,evaluate);
 CHECK(evaluations==3&&carbon_census_loading==2);
 /* Independent byte fixture: do not use observer offsets or constants. */
 put16(0xB7076A,101);put16(0xB707FA,202);
 put32(0xB7097C,6);put32(0xB70D84,10000);put32(0xB70D80,0x40000);
 put32(0xB70D8C,0x20000);put32(0xB70678,2);
 const unsigned numbers[]={2500,2400,2600,101,102,103};
 const unsigned statuses[]={3,4,4,0,1,2};
 for(unsigned i=0;i<6;++i){
   uint32_t record=0x10000+i*0x5C;put32(0xB70980+4*i,record);
   put16(record+8,numbers[i]);put32(record+12,statuses[i]);
   put32(record+16,0);put32(record+24,100*(i+1));put32(record+76,0x40000+128*i);
 }
 /* Two free blocks and a larger allocated block in the pool's node list. */
 put32(0x20028,0x21000);put32(0x21000,0x21100);put32(0x21100,0x21200);put32(0x21200,0x20028);
 put32(0x2100C,4096);put32(0x2110C,8192);put32(0x2120C,9000);G[0x21210]=1;G[0x2001C]=1;
 {const float point[3]={1234.5f,-678.25f,90.125f};memcpy(G+0xB70720,point,12);}
 {const float speed[3]={1.5f,-2.25f,0};memcpy(G+0xB70730,speed,12);}
 put32(0xB70770,7);put32(0xB70800,19);
 put32(0x50004,0x50100);put32(0x50100,0x50200);put32(0x50104,0x50218);
 put32(0x50200,0x403710);put32(0x50204,0x51000);
 put32(0x50208,0x403CE0);put32(0x5020C,0x52044);
 put32(0x50210,0x4087C0);put32(0x50214,0x53000);
 put32(0x52044,0x54000);put32(0x5404C,0x6F8A60);put32(0x520E0,2);
 uint8_t *before=malloc(0xC00000);CHECK(before);memcpy(before,G,0xC00000);
 carbon_census_sample();CHECK(logs==1);CHECK(!memcmp(before,G,0xC00000));
 CHECK(strstr(line,"zones=101,202 loaded=3 bytes=600 pool=10000 largest=8192 skipped=2 sections=2500,2400,2600 stream=1234.500,-678.250,90.125"));
 CHECK(strstr(line,"stream=1234.500,-678.250,90.125 vel=1.500,-2.250,0.000 zone_age=7,19 wheels=2 suspension=006F8A60"));
 CHECK(strstr(line,"loading=2")&&carbon_census_loading==0);
 put32(0x520E0,0);CHECK(carbon_census_wheels()==0);
 put32(0x5404C,0x6F8A70);CHECK(carbon_census_wheels()==-1);
 put32(0x5404C,0x6F8A60);put32(0x520E0,5);CHECK(carbon_census_wheels()==-1);
 put32(0x520E0,4);CHECK(carbon_census_wheels()==4);
 put32(0x50104,0x501FF);CHECK(carbon_census_wheels()==-1);put32(0x50104,0x50218);
 Cpu c={0};c.esp=0x30000;c.ecx=0x20000;f_0079E2B0(&c);CHECK(c.eax==8192);
 Cpu wheel={0};wheel.esp=0x30000;wheel.ecx=0x52044;f_006F8A60(&wheel);CHECK(wheel.eax==4);
 put32(0x5404C,0x6FC8C0);put32(0x520F8,3);
 wheel.esp=0x30000;wheel.ecx=0x52044;f_006FC8C0(&wheel);CHECK(wheel.eax==3);
 CHECK(carbon_census_wheels()==(int)wheel.eax);
 put32(0x520F8,0);CHECK(carbon_census_wheels()==0);
 put32(0x5404C,0x6FB690);CHECK(carbon_census_wheels()==-1&&carbon_census_getter==0x6FB690);
 put32(0x50004,0);CHECK(carbon_census_wheels()==-1&&carbon_census_getter==0);put32(0x50004,0x50100);
 put32(0x5404C,0x6F8A60);
 CHECK(carbon_census_largest(0x20000)==c.eax);
 put32(0x20018,1234);CHECK(carbon_census_largest(0x20000)==1234);
 c.esp=0x30000;c.ecx=0x20000;f_0079E2B0(&c);CHECK(c.eax==1234);
 CHECK(carbon_census_largest(0)==0);
 /* Loaded status without memory is excluded. */
 put32(0x1004C,0);carbon_census_sample();CHECK(strstr(line,"loaded=2 bytes=500"));
 CHECK(strstr(line,"loading=0"));
 /* Empty set is a complete sample, not an absent sample. */
 put32(0xB7097C,0);carbon_census_sample();CHECK(strstr(line,"loaded=0 bytes=0"));
 /* Bound the pointer storage and a malformed allocator chain. */
 put32(0xB7097C,0xFFFFFFFF);carbon_census_sample();CHECK(logs==3);
 G[0x2001C]=1;put32(0x20028,0);CHECK(carbon_census_largest(0x20000)==0);
 /* Direction output is overwritten after native placement, no position write. */
 Cpu spawn={0};spawn.esp=0x30000;put32(0x30008,0x60000);
 unsetenv("NFS_CARBON_C3_HEADING");carbon_c3_start(&spawn,native_start);
 CHECK(starts==1&&spawn.eax==0x12345678&&spawn.esp==0x30004);
 setenv("NFS_CARBON_C3_HEADING","-3,-4",1);setenv("NFS_CARBON_SKIPFE_START","1,2,3",1);setenv("NFS_CARBON_SKIPFE","1",1);
 spawn.esp=0x30000;memcpy(before,G,0xC00000);carbon_c3_start(&spawn,native_start);
 float heading[3];memcpy(heading,G+0x60000,12);
 CHECK(starts==2&&spawn.eax==0x12345678&&spawn.esp==0x30004);
 CHECK(fabs(heading[0]+.6)<.000001&&heading[1]==0&&fabs(heading[2]+.8)<.000001);
 memcpy(before+0x60000,G+0x60000,12);CHECK(!memcmp(before,G,0xC00000));
 unsetenv("NFS_CARBON_C3_HEADING");
 /* Vehicles: independent PVehicle bytes (ISimable at sim, IVehicle at sim+94). */
 put32(0xA9E868,0x100040);put32(0x10005C,0x101000);put32(0x100064,4);
 put32(0x190000+0x9C,0x6D80C0);put32(0x190004,0x6D7EE0);
 put32(0x191060,0x6D7EA0);put32(0x193020,0x6C6FF0);
 {const uint32_t sims[]={0x110000,0x120000,0x130000,0x140000,0x150000};
  const float at[][3]={{-3001.5f,188.5f,7827.5f},{1,2,3},{4,5,6},{10,20,30},{-5,6,7}};
  for(unsigned i=0;i<5;++i){uint32_t s=sims[i];
   put32(s+0x94,0x190000);put32(s+0x94+0xA8,i!=1);put32(s,0x191000);
   put32(s+0x4C,s+0x1000);put32(s+0x1000,0x193000);put32(s+0x1030,s+0x2000);put32(s+0x2000,s+0x3000);
   memcpy(G+s+0x3010,at[i],12);}
  put32(0x101000,sims[0]+0x94);put32(0x101004,sims[1]+0x94);put32(0x101008,0);put32(0x10100C,sims[2]+0x94);
  put32(sims[2]+0x94,0x196000);
  put32(0xA9E874,0x20004C);put32(0x2000BC,0x201000);put32(0x2000C4,2);
  put32(0x201000,sims[3]+0x94);put32(0x201004,sims[4]+0x94);
  put32(0x200140,0x202000);put32(0x202000,0x200140);put32(0x202008,0x203000);put32(0x200148,1);
  put32(0x20304C,0x204000);put32(0x203054,1);put32(0x204000,sims[3]+0x94);}
 put32(0xB7097C,0);memcpy(before,G,0xC00000);unsigned lines=logs;carbon_census_sample();
 CHECK(logs==lines+2&&!memcmp(before,G,0xC00000));
 CHECK(!strcmp(line,"vehicles: traffic=1/4 cops=2/2 unknown=1 T=00110094@-3001.5,188.5,7827.5 C=00140094@10.0,20.0,30.0*;00150094@-5.0,6.0,7.0"));
 put32(0xA9E868,0);put32(0xA9E874,0);lines=logs;carbon_census_sample();CHECK(logs==lines+1);
 printf("CENSUS PASS loaded=3 bytes=600 native_largest=8192 changed_guest_bytes=0\n");
 free(before);free(G);return 0;
}
'''


def run(args, expected=0):
    result = subprocess.run(list(map(str, args)), capture_output=True, text=True)
    assert result.returncode == expected, (result.returncode, result.stdout[-1000:], result.stderr[-2500:])
    return result


def sample(zones='10,0', sections='2500,2400,2600', size=600, largest=8192, skipped=0):
    count = len(sections.split(',')) if sections else 0
    return (f'f12 t0 census: zones={zones} loaded={count} bytes={size} pool=10000 '
            f'largest={largest} skipped={skipped} sections={sections}\n')


def summary_tests(tmp):
    data = ('unrelated event\n' + sample() + sample('11,0', '2500,2400,2600,101', 800, 6000, 2) +
            sample('12,11', '2500,2400,2600,102', 900, 7000, 1) + sample('13,11', largest=5000))
    result = census.summarize(census.samples(data.splitlines()))
    assert result['samples'] == 4 and result['zones'] == [10, 11, 12, 13]
    assert result['zone_changes'] == 3 and result['loads'] == 2 and result['unloads'] == 2
    assert result['peak_bytes'] == 900 and result['minimum_largest_free'] == 5000
    assert result['skipped'] == 2 and result['skipped_final'] == 0 and result['skipped_samples'] == 2
    assert result['always_loaded'] == [2400, 2500, 2600]
    log = tmp / 'events.log'
    cli = [sys.executable, '-I', HERE / 'private_census.py', '--summary', log]
    log.write_text(data)
    assert json.loads(run(cli + ['--expect-zone-changes', '3']).stdout)['samples'] == 4
    run(cli + ['--expect-loaded', '3'], 1)
    # Collision-only negative control stays at 3 residents and zero zone changes.
    log.write_text(sample('0,0') * 4)
    run(cli + ['--expect-loaded', '3'])
    run(cli + ['--expect-zone-changes', '3'], 1)
    log.write_text('no census here\n')
    assert json.loads(run(cli).stdout)['samples'] == 0
    run(cli + ['--expect-loaded', '0'], 1)
    run(cli + ['--expect-zone-changes', '0'], 1)
    log.write_text(sample('0,-1', '', 0))
    empty = json.loads(run(cli + ['--expect-loaded', '0']).stdout)
    assert empty['distinct_zones'] == 0 and empty['always_loaded'] == []
    streamed = sample().rstrip() + ' stream=1234.500,-678.250,90.125\n'
    row, = census.samples([streamed])
    assert row['stream'] == (1234.5, -678.25, 90.125) and row['loaded'] == 3
    assert 'stream' not in next(census.samples([sample()]))
    engine = streamed.rstrip() + ' zone_age=7,19 wheels=0\n'
    row, = census.samples([engine])
    assert row['zone_age'] == (7, 19) and row['wheels'] == 0 and 'velocity' not in row
    moving = streamed.rstrip() + ' vel=1.500,-2.250,0.000 zone_age=7,19 wheels=0 suspension=006FB690\n'
    row, = census.samples([moving])
    assert row['velocity'] == (1.5, -2.25, 0.) and row['suspension'] == 0x6FB690
    loaded = engine.rstrip() + ' loading=2\n'
    row, = census.samples([loaded])
    assert row['loading'] == 2
    summary = census.summarize(census.samples([loaded, engine.rstrip() + ' loading=0\n']))
    assert summary['loading'] == 2 and summary['loading_samples'] == 1
    for bad in (sample().replace('loaded=3', 'loaded=4'), sample(sections='1,1,2'),
                sample().replace('pool=10000 ', ''), sample().rstrip() + ',oops\n',
                streamed.replace(',90.125', ''), streamed.replace('90.125', 'nan'),
                engine.replace('wheels=0', 'wheels=5'),
                moving.replace('vel=1.500,-2.250,0.000', 'vel=1.500,-2.250'),
                moving.replace('suspension=006FB690', 'suspension=6FB690'),
                engine.replace('zone_age=7,19', 'zone_age=-2,19'),
                loaded.replace('loading=2', 'loading=-1')):
        log.write_text(bad)
        run(cli, 1)
    print('SUMMARY PASS samples=4 zones=4 loads=2 unloads=2; broken zone_changes=0 < 3 exit=1')


def main():
    translated = HERE / 'out/carbon-base/NFSC_43.c'
    if not translated.is_file():
        print('SKIP: private_census_test needs Carbon translated originals')
        return 3
    native = body(translated.read_text(), 'f_0079E2B0')
    assert hashlib.sha256(native.encode()).hexdigest() == QUERY_SHA
    contact = (HERE / 'out/carbon-base/NFSC_37.c').read_text()
    for name, digest in CONTACT_SHA.items():
        getter = body(contact, name)
        assert hashlib.sha256(getter.encode()).hexdigest() == digest
        native += '\n' + getter
    source = (PRIVATE / 'carbon_census.h').read_text()
    feature = json.loads((PRIVATE / 'features/autodrive.json').read_text())
    assert feature['bindings']['carbon_census.h']['sha256'] == hashlib.sha256(source.encode()).hexdigest()
    autodrive = (PRIVATE / 'carbon_autodrive.h').read_text()
    assert autodrive.count('carbon_census_sample();') == 1
    assert autodrive.index('carbon_autodrive_second = now;') < autodrive.index('carbon_census_sample();')
    with tempfile.TemporaryDirectory(prefix='private-census-') as directory:
        tmp = Path(directory)
        summary_tests(tmp)
        (tmp / 'fixture.c').write_text(HARNESS)
        (tmp / 'native.inc').write_text(native)
        variants = {'good': source, 'wrong-status': source.replace('M32(record + 0x0C)', 'M32(record + 0x10)'),
                    'pre-call': source.replace('    original(c);\n    if (carbon_census_enabled() && M8(0x00B7420Cu)) ++carbon_census_loading;',
                                              '    if (carbon_census_enabled() && M8(0x00B7420Cu)) ++carbon_census_loading;\n    original(c);'),
                    'velocity-at-stream': source.replace('M32(streamer + 0xE0 + 4 * i)', 'M32(streamer + 0xD0 + 4 * i)'),
                    'sim-at-ivehicle': source.replace('uint32_t sim = v - 0x94,', 'uint32_t sim = v,'),
                    'pre-heading': source.replace('    original(c);\n    memcpy(gptr(direction), heading, sizeof heading);',
                                                 '    memcpy(gptr(direction), heading, sizeof heading);\n    original(c);')}
        assert variants['wrong-status'] != source
        assert all(text != source for name,text in variants.items() if name != 'good')
        for name, text in variants.items():
            (tmp / 'carbon_census.h').write_text(text)
            binary = tmp / name
            run(['clang', '-O1', '-g', '-DRECOMP_ABICHECK', '-fsanitize=address,undefined',
                 '-I', HERE, '-I', ROOT / 'runtime', '-I', HERE / 'out/carbon-base', tmp / 'fixture.c', '-o', binary])
            for mode in ('off', 'zero', 'diag-off', 'on'):
                result = run([binary, mode], 1 if name != 'good' and mode == 'on' else 0)
                print(f'{name}/{mode}: {(result.stdout or result.stderr).strip()[:280]}')
            if name == 'good':
                for value in ('nan,1', '0,0', '1,2,3', '1', 'inf,0'):
                    run([binary, 'bad-heading='+value], 2)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
