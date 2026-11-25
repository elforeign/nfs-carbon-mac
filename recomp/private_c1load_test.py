"""C1 load checker and read-only post-bind probe (no game).

Good fixture: bound 4,165, 167x365; shortened rectangle: bound 2,412,
167x159, rejected. Checker mutations cover bytes, zones, pool, missing rows,
heap, Y00 allocation, overlay, grid and Rockport coordinates independently.
Live control: good bound 4,165 vs broken 2,412; ground misses 0/95 vs 63/64.
Unset/0/diag-off probe: zero guest reads and zero logs; original called once.
Exit 3 when the private pair or generated host headers are absent.
"""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import private_c1load as check

# Six retained part-4 actual-car samples (the original has no c3tick lines).
BROKEN_C3 = '''f11336 t1 autodrive: speed=33.974_mps mph=76.00 distance=816.292_m top_mph=83.18 lap=0 racers=0 position=-2639.316,211.976,7223.067
f11706 t1 autodrive: speed=34.686_mps mph=77.59 distance=832.962_m top_mph=83.18 lap=0 racers=0 position=-2635.126,215.054,7207.239
f12515 t1 autodrive: speed=34.506_mps mph=77.19 distance=839.894_m top_mph=83.18 lap=0 racers=0 position=-2633.427,215.397,7200.530
f13298 t1 autodrive: speed=29.302_mps mph=65.55 distance=845.755_m top_mph=83.18 lap=0 racers=0 position=-2630.360,215.028,7195.585
f14087 t1 autodrive: speed=29.819_mps mph=66.70 distance=851.689_m top_mph=83.18 lap=0 racers=0 position=-2627.145,213.944,7190.722
f14780 t1 autodrive: speed=3.169_mps mph=7.09 distance=858.112_m top_mph=83.18 lap=0 racers=0 position=-2623.805,212.038,7185.582
'''

HARNESS = r'''
#include "host.h"
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
uint8_t *G;
int diag_on = 1;
static unsigned reads, logs, calls, calls_at_log;
static char line[1024];
static uint32_t r32(uint32_t a) { uint32_t v; ++reads; memcpy(&v,G+a,4); return v; }
static uint16_t r16(uint32_t a) { uint16_t v; ++reads; memcpy(&v,G+a,2); return v; }
#undef M32
#undef M16
#define M32(a) r32(a)
#define M16(a) r16(a)
#include "carbon_c1grid.h"
void diag_event(const char *f,...) { va_list a; va_start(a,f); vsnprintf(line,sizeof line,f,a); va_end(a); ++logs; calls_at_log=calls; }
#define CHECK(v) do { if(!(v)) { fprintf(stderr,"GRID CHECK %d: %s [%s]\n",__LINE__,#v,line); return 1; } } while(0)
static void put32(uint32_t a,uint32_t v) { memcpy(G+a,&v,4); }
static void put16(uint32_t a,uint16_t v) { memcpy(G+a,&v,2); }
static void original(Cpu *c) { ++calls; c->eax=0x12345678; c->esp+=4; }
int main(int argc,char **argv) {
    CHECK(argc==2);
    if(!strcmp(argv[1],"off")) unsetenv("NFS_CARBON_GRID_PROBE");
    else setenv("NFS_CARBON_GRID_PROBE",!strcmp(argv[1],"zero")?"0":"1",1);
    if(!strcmp(argv[1],"diag-off")) diag_on=0;
    Cpu c={0}; c.esp=0x2000;
    int on=!strcmp(argv[1],"on")||!strcmp(argv[1],"broken");
    if(!on) {
        /* Null G makes accidental off-path reads fail immediately. */
        carbon_c1grid_map(&c,original);
        CHECK(calls==1&&c.eax==0x12345678&&c.esp==0x2004&&reads==0&&logs==0);
        return 0;
    }
    G=calloc(1,0xC00000); CHECK(G);
    put32(0xB77EB8,0x1000); put32(0x1000,0x3000); put32(0x100C,2600);
    put32(0x1010,0x4000); put32(0x1038,167); put32(0x103C,365); put32(0x1040,0x42C00000);
    unsigned cols=!strcmp(argv[1],"broken")?159:365, bound=cols==159?2412:4165;
    put32(0x3018,167); put32(0x301C,cols); put32(0x3020,0x5000);
    put16(0x4000,2600); put16(0x4006,cols); put16(0x4008,167);
    for(unsigned i=0;i<bound;++i) put32(0x5000+4*i,0xB00000+i);
    uint8_t *before=malloc(0xC00000); CHECK(before); memcpy(before,G,0xC00000);
    carbon_c1grid_map(&c,original); CHECK(logs==1&&calls_at_log==1&&calls==1&&c.eax==0x12345678&&c.esp==0x2004);
    CHECK(strstr(line,"event=map tile=2600 cgrd=167x365"));
    carbon_c1grid_tile(&c,original); CHECK(logs==2&&calls_at_log==2&&calls==2&&c.esp==0x2008);
    CHECK(strstr(line,"event=tile")); CHECK(!memcmp(before,G,0xC00000));
    CHECK(strstr(line,cols==159?"grid=167x159":"grid=167x365"));
    CHECK(strstr(line,cols==159?"bound=2412":"bound=4165"));
    puts(line); free(before); free(G); return 0;
}
'''


def fixture():
    grid = ('f1 t1 carbon_grid: event=tile tile=2600 cgrd=167x365 grid=167x365 '
            'cell=96 rect=2600,0,0,365,167 bound=4165\n')
    samples = [f'f{f} t1 census: zones=309,-1 loaded=4 bytes=180114424 pool=139059200 '
               'largest=60000000 skipped=0 sections=2500,2400,2600,309\n' for f in (10, 300, 400)]
    allocation = 'f1 t1 msvcr71.dll!malloc(ABC5244, 0, 0, 0) -> 50000000 @0047668A\n'
    overlays = [f'f1 t1 PRIVATE TRACK OPEN TRACKS/{n} status=ok -> overlay/{n}\n' for n in check.PAIR_SHA256]
    drive = 'f400 t1 autodrive: speed=1_mps distance=150_m position=20000,90,1745\n'
    return check.parse([grid, *samples, allocation, *overlays, drive])


def checker_tests():
    rows = {309: frozenset((2500, 2400, 2600, 309))}
    sizes = {2500:180113824, 2400:100, 2600:200, 309:300}
    clock = [(1, 1.), (100, 10.), (200, 20.), (300, 31.), (400, 41.)]
    good = fixture()
    def result(data=good, peak=600.):
        return check.summarize(data, rows, sizes, clock, peak, rockport=True)
    assert result()['passed'], result()
    mutants = []
    for field, value in [('bytes', 1), ('zones', (309, 99)), ('pool', 1), ('skipped', 1),
                         ('sections', frozenset((2500, 2400, 2600)))]:
        data = copy.deepcopy(good)
        data['samples'][-1][field] = value
        mutants.append(data)
    for field, value in [('bound',2412), ('grid',(167,159)), ('cgrd',(167,159)), ('tile',2590)]:
        data = copy.deepcopy(good)
        data['grids'][-1][field] = value
        mutants.append(data)
    for field in ('overlays', 'chunks', 'grids', 'drives'):
        data = copy.deepcopy(good)
        data[field] = []
        mutants.append(data)
    data = copy.deepcopy(good)
    data['drives'][0]['position'] = (100, 90, 1745)
    mutants.append(data)
    assert all(not result(data)['passed'] for data in mutants)
    assert not result(peak=752.)['passed']
    assert not result(peak=None)['passed']
    over = copy.deepcopy(good)
    over_sizes = dict(sizes)
    over_sizes[309] = check.WORLD_SHARE + 1
    for sample in over['samples']:
        sample['bytes'] = sum(over_sizes.values())
    too_big = check.summarize(over, rows, over_sizes, clock, 600.)
    assert too_big['byte_errors'] == 0 and any('pool-7 bytes' in f for f in too_big['failures'])
    assert check.heap_peak(['0 0 | 0 0 0 0 | 1 2 3 640.1 5\n']) == 640.1
    assert check.clocks(['t 3.5 frame 3 fps 1\n']) == [(3, 3.5)]
    for line in ['f1 t1 census: bad\n', 'f1 t1 carbon_grid: bad\n']:
        try:
            check.parse([line])
        except ValueError:
            pass
        else:
            raise AssertionError('malformed diagnostic accepted')
    return len(mutants) + 3


def c3_tests():
    # Read the serialized graph through c3_points, including the corrected
    # reverse start. A 1534-start regression must fail this independent pin.
    tracks = HERE/'out/c3load-overlay/TRACKS'
    if (tracks/'L5RA.BUN').is_file():
        import ground
        from formats import TrackIndex
        nodes = ground.road_nodes(TrackIndex((tracks/'L5RA.BUN').read_bytes()))
        assert check.c3_points(tracks,'reverse')[0] == nodes[9022]
        assert check.c3_points(tracks,'forward')[0] == nodes[8739]
    points = ((0,0,0), (100,0,0), (200,0,0), (110,0,0))
    rows, sizes = {326:frozenset((220,260))}, {220:10,260:20}
    def fixture(direction):
        xs = (0,50,90,110,150) if direction == 'forward' else (200,150,110,90,50)
        return dict(samples=[dict(frame=i+1, zones=(326,-1), sections=frozenset(sizes),
            bytes=30, stream=(0,-x,0), loading=0, skipped=0, largest=12345, wheels=4)
            for i,x in enumerate(xs)], drives=[dict(frame=1, position=
                (-2616.,213.22,7186.)) if direction=='forward' else
                dict(frame=1, position=(-2636.45,213.27,7214.21))])
    for direction in ('forward','reverse'):
        ps = (*points, [points[0],points[2]]) if direction == 'forward' else (
            points[2],points[1],points[0],points[3], [points[2],points[0]])
        good = fixture(direction)
        def result(data):
            return check.summarize_c3(data,rows,sizes,ps,direction)
        assert result(good)['passed'], result(good)
        assert result(good)['maximum_lateral_offset_m'] < 1e-9
        bad=copy.deepcopy(good)
        z,x,y=bad['samples'][2]['stream']
        bad['samples'][2]['stream']=(12.001,x,y)
        assert not result(bad)['passed'] and result(bad)['maximum_lateral_offset_m'] == 12.001
        bad['samples'][2]['stream']=(12.,x,y)
        assert result(bad)['passed'] and result(bad)['maximum_lateral_offset_m'] == 12.
        airborne=copy.deepcopy(good)
        airborne['samples'][2]['wheels']=0
        airborne['ticks']=copy.deepcopy(good['drives'])
        airborne['drives']=[dict(frame=s['frame'],position=(i*20.,10.,0.),
                                 speed=34.,distance=i*20.) for i,s in enumerate(airborne['samples'])]
        flight=result(airborne)['flights'][0]
        assert flight['takeoff_speed_mps'] == 34.
        assert flight['flight_chord_m'] == 40. and flight['sampled_distance_m'] == 40.
        for field,value in [('loading',1),('skipped',1),('sections',frozenset((220,))),
                            ('bytes',1),('zones',(999,-1)),('stream',(0,-500,0))]:
            bad=copy.deepcopy(good); bad['samples'][0][field]=value
            assert not result(bad)['passed'], (field,result(bad))
        bad=copy.deepcopy(good); bad['samples']=bad['samples'][:2]
        assert not result(bad)['passed'] and result(bad)['arrival_frame'] is None
        assert result(bad)['largest_at_cut'] is None
        for field in ('loading','stream'):
            bad=copy.deepcopy(good); del bad['samples'][0][field]
            try:
                result(bad)
            except ValueError:
                pass
            else:
                raise AssertionError(f'missing {field} accepted')
        # Errors after arrival do not invalidate a completed crossing.
        bad=copy.deepcopy(good); bad['samples'].append(dict(bad['samples'][-1],loading=99,frame=99))
        assert result(bad)['passed']
    broken = check.parse(BROKEN_C3.splitlines())
    landing, failure = check.c3_landing(broken, 'forward')
    assert failure == 'never reached the landing lip: furthest s 30.93, height 212.04', failure
    # Full checker also rejects arrival; use the existing incomplete census fixture.
    broken['samples'] = fixture('forward')['samples'][:2]
    ps = (*points, [points[0],points[2]])
    result = check.summarize_c3(broken, rows, sizes, ps, 'forward')
    assert result['arrival_frame'] is None and failure in result['failures']
    for direction, point in [('forward',(-2616.,213.22,7186.)),
                             ('reverse',(-2636.45,213.27,7214.21))]:
        good = dict(drives=[dict(frame=1,position=point)])
        assert check.c3_landing(good,direction)[1] is None
        x,y,z = point
        good['drives'][0]['position'] = (x,y-.001,z)
        assert check.c3_landing(good,direction)[1] is not None
        # Per-tick samples take precedence over sparse samples and keep the first height.
        line = (f'f7 t1 c3tick: tick=2 time=1.25 position={x},{y-.001},{z} '
                'velocity=1,2,3 s=999 lateral=999 heading=0 wheels=0')
        good['ticks'] = check.parse([line])['ticks']
        good['drives'][0]['position'] = point
        assert check.c3_landing(good,direction)[1] is not None
    print('C3 CHECK PASS good loading/missing/skipped=0/0/0; controls=1/0/0,0/1/0,0/0/1 FAIL; incomplete FAIL')


# Default shift, zones off. These are the converter's independently verified pins.
GENERATED_PAIR = {
    'L5RA.BUN': 'cc154fc5746163678b855231301857105de67c50644527171228973172fa3b7e',
    'STREAML5RA.BUN': 'd557254bd412fd8033c717cde955d54f823f9330894e10e01f59e4f38bb57bcd',
}


def main(tracks=None):
    rejected = checker_tests()
    c3_tests()
    private = HERE / 'private_runtime'
    feature = json.loads((private / 'features/c1grid.json').read_text())
    hooks = json.loads((private / 'hooks/c1grid.json').read_text())
    binding = feature['bindings']['carbon_c1grid.c']
    assert binding['sha256'] == hashlib.sha256((private / binding['source']).read_bytes()).hexdigest()
    assert {h['address'] for h in hooks['hooks']} == {'00813850', '00813920'}
    headers = HERE / 'out/carbon-base'
    if tracks is None:
        tracks = HERE / 'out/c1load-overlay/TRACKS'
        hashes, expected_bytes = check.PAIR_SHA256, 69774568
    else:
        hashes, expected_bytes = GENERATED_PAIR, 69774568
    if (not all((tracks / name).is_file() for name in hashes)
            or not (headers / 'funcs.h').is_file()):
        print('C1LOAD TEST SKIP: private pair/generated headers unavailable')
        return 3
    check.verify_pair(tracks, hashes)
    rows, sizes = check.world_rows(tracks, pinned=False)
    assert len(rows) == 780 and len(sizes) == 1433
    row_bytes = sum(sizes[n] for n in rows[1319] | {2400, 2600} if n != 2500)
    assert row_bytes == expected_bytes <= check.WORLD_SHARE
    with tempfile.TemporaryDirectory(prefix='c1load-') as temporary:
        root = Path(temporary)
        (root / 'test.c').write_text(HARNESS)
        command = ['clang', '-std=c11', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                   '-I', str(HERE), '-I', str(HERE.parent / 'runtime'), '-I', str(headers), '-I', str(HERE / 'private_runtime'),
                   str(root / 'test.c'), '-o', str(root / 'test')]
        subprocess.run(command, check=True, capture_output=True, text=True)
        for mode in ('off', 'zero', 'diag-off', 'on', 'broken'):
            result = subprocess.run([str(root / 'test'), mode], capture_output=True, text=True)
            assert result.returncode == 0, (mode, result.stderr)
        broken = check.broken_index(tracks, root / 'TRACKS', hashes=hashes)
        original = (tracks / 'L5RA.BUN').read_bytes()
        changed = (broken / 'L5RA.BUN').read_bytes()
        assert len(original) == len(changed)
        assert sum(a != b for a, b in zip(original, changed)) == 2
        assert check.world_rows(broken, pinned=False) == (rows, sizes)
        try:
            check.verify_pair(broken, hashes)
        except ValueError:
            pass
        else:
            raise AssertionError('broken pair digest accepted')
    print(f'C1LOAD TEST PASS: rows={len(rows)} records={len(sizes)} row_1319_bytes={row_bytes} checker_mutants={rejected} '
          'native_modes=5 guest_writes=0 broken_width=159')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
