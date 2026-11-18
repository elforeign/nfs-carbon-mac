"""Native route quantization, restored barrier probe and road-end A* (no game).

Native 20 km: stock u16=14464 (3616 m), scale1 u16=20000 (20000 m).
Omitted-write/restore mutants exit 1; parser rejects 16 broken cases.
Live open: stock/scale1 counts 50/150/207 and ordered hashes equal; medium
control .125 overflows at 85568 ticks and changes count150 to192 and hash.
Road-end emulator inserts 163/1019/1088; refuse-connectors mutant finds 0/3.
Exit 3 without the private executable and translated fragments.
"""
import argparse
import copy
import hashlib
import heapq
import json
import math
from pathlib import Path
import re
import struct
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
PRIVATE = HERE / 'private_runtime'
IMAGE_SHA = 'baaaaec33873d4ba7e4dbae6a5212049ffdcf9679a35d865d7625b4189952fd3'
FRAGMENTS = {
    0x00806180: (47, '002d941234a5f17cf9fd19691297d8300a16ac72434375d1e456cfb450fea1a1'),
    0x007EA900: (46, 'ef86c63e97b7b9a8ab6012aacd72bf8075b8d049d250b04faf8dd863360245dd'),
    0x007F62E0: (46, '4b601b9d8153a427df932b83e26eb1c97c31535ab0dcc27903df741825514abd'),
    0x0087EAC0: (52, '8a57fc42130caa60ed8421cb1d5da190a9fe9861da15b652a28973e67a972158'),
}
PAIRS = {'short': (203, 534, 1999.9999995343387),
         'medium': (1347, 2544, 8000.015257159248),
         'long': (1521, 2342, 9851.331347366795)}


def fragment(address, chunk):
    source = (HERE / f'out/carbon-base/NFSC_{chunk:02d}.c').read_text()
    pattern = rf'void (?:f_|carbon_orig_){address:08X}\(Cpu [^)]*\)\s*\{{'
    match = re.search(pattern, source)
    assert match, hex(address)
    text = source[match.start():source.index('\n}', match.end()) + 2]
    return text.replace(f'carbon_orig_{address:08X}(', f'f_{address:08X}(', 1)


def parse_log(text, scale):
    rows = {'asis': {}, 'open': {}, 'restore': {}}
    for line in text.splitlines() if isinstance(text, str) else text:
        if 'carbon_route: ' not in line:
            continue
        record = line.split('carbon_route: ', 1)[1]
        fields = dict(re.findall(r'(\w+)=([^\s]+)', record))
        if record.startswith('blocked '):
            assert 'blocked' not in rows, 'duplicate blocked record'
            blocked = [int(fields[k]) for k in ('seg1000', 'seg2000')]
            barriers = list(map(int, fields['barriers'].split('/')))
            assert len(barriers) == 2 and 0 <= barriers[0] <= barriers[1]
            assert min(blocked) >= 0
            rows['blocked'] = blocked + barriers
            continue
        if record.startswith('restore '):
            name = fields['pair']
            assert name in PAIRS and name not in rows['restore'], 'duplicate/unknown restore'
            assert re.fullmatch('[0-9a-f]{16}', fields['before'])
            assert fields['before'] == fields['after'], ('flags not restored', name)
            rows['restore'][name] = fields['before']
            continue
        if not record.startswith('pair='):
            continue
        name, mode = fields['pair'], fields['mode']
        assert mode in ('asis', 'open') and name in PAIRS
        assert name not in rows[mode], ('duplicate pair/mode', name, mode)
        assert fields['nodes'] == ','.join(map(str, PAIRS[name][:2]))
        row = {key: float(fields[key]) for key in ('scale', 'metres', 'max_f', 'max_ticks')}
        row.update({key: int(fields[key]) for key in ('status', 'count', 'first', 'last', 'samples')})
        assert re.fullmatch('[0-9a-f]{16}', fields['hash'])
        row['hash'] = fields['hash']
        assert all(math.isfinite(row[key]) and row[key] >= 0
                   for key in ('scale', 'metres', 'max_f', 'max_ticks'))
        assert row['scale'] == scale and row['samples'] > 0
        assert math.isclose(row['max_f'] / scale, row['max_ticks'], rel_tol=2e-8, abs_tol=1e-5)
        assert 0 <= row['count'] <= 510 and 0 <= row['status'] <= 3
        if row['status'] == 3:
            assert row['count'] > 0 and max(row['first'], row['last']) < 32768
        rows[mode][name] = row
    assert 'blocked' in rows, 'missing blocked record'
    for mode in ('asis', 'open', 'restore'):
        assert set(rows[mode]) == set(PAIRS), ('missing records', mode)
    assert len(set(rows['restore'].values())) == 1, 'flags changed between queries'
    return rows


def read_log(path, scale):
    # Stream large diagnostic logs; retain only the ten probe records.
    with path.open() as stream:
        return parse_log(stream, scale)


def acceptance(stock, enlarged, control):
    assert sum(stock['blocked'][:2]) > 0, ('barrier premise refuted', stock['blocked'])
    short = stock['asis']['short']
    assert (short['status'], short['count'], short['hash']) == (3, 50, '7084cd26c264468d')
    assert all(stock['asis'][name]['status'] == 0 for name in ('medium', 'long'))
    for run in (enlarged, control):
        assert run['blocked'] == stock['blocked'], 'barrier counts changed'
        assert run['restore'] == stock['restore'], 'baseline flags changed'
    compared = []
    for name, (_, _, expected) in PAIRS.items():
        a, b = stock['open'][name], enlarged['open'][name]
        assert a['status'] == 3, ('barrier premise refuted: open route failed', name, a)
        assert abs(a['metres'] / expected - 1) <= .01, ('baseline metres', name, a['metres'])
        assert b['status'] == 3 and b['max_ticks'] <= 65535, ('scale1 capacity/status', name, b)
        assert (a['status'], a['count'], a['hash']) == (b['status'], b['count'], b['hash']), ('route differs', name)
        assert abs(b['metres'] / expected - 1) <= .01, ('scale1 metres', name)
        compared.append(name)
    a, b = control['open']['medium'], stock['open']['medium']
    assert a['max_ticks'] > 65535, 'control did not overflow'
    assert a['status'] != 3 or a['hash'] != b['hash'], ('control overflow returned the same route', a['max_ticks'], a['hash'])
    return {'below_limit_equal': compared, 'control': 'medium overflow changed status or hash',
            'stock_overflow': 'unproven: merged Palmont/Rockport pair required'}


def graph_fixtures():
    sys.path.insert(0, str(ROOT / 'tools_snapshot/worldmerge'))
    import c1_roads as roads
    index, _, _ = roads.load_index(roads.DEFAULT_CARBON, 'L5RA')
    raw = roads.collision_body(roads.one(index.parts, 0x3b800))
    counts, _, nodes, segments, _ = roads._reader(raw)
    unit = struct.unpack('<f', struct.pack('<f', 1000 / 65535))[0]
    adjacency = [[] for _ in nodes]
    for a, b, length, *_ in segments:
        adjacency[a].append((b, length * unit))
        adjacency[b].append((a, length * unit))
    diameter = (-1, -1, -1)
    fixtures = {}
    for source in range(len(nodes)):
        distance = [math.inf] * len(nodes)
        distance[source] = 0
        queue = [(0, source)]
        while queue:
            d, a = heapq.heappop(queue)
            if d != distance[a]:
                continue
            for b, length in adjacency[a]:
                candidate = d + length
                if candidate < distance[b]:
                    distance[b] = candidate
                    heapq.heappush(queue, (candidate, b))
        for destination, d in enumerate(distance[source + 1:], source + 1):
            if math.isfinite(d) and d > diameter[0]:
                diameter = (d, source, destination)
        for name, (a, b, expected) in PAIRS.items():
            if a == source:
                assert abs(distance[b] - expected) < 1e-6, (name, distance[b])
                fixtures[name] = {'nodes': [a, b], 'metres': distance[b],
                                  'chord': math.dist(nodes[a][:3], nodes[b][:3])}
    assert diameter == (PAIRS['long'][2], *PAIRS['long'][:2]), diameter
    return {'counts': counts, 'diameter': diameter, 'pairs': fixtures}


def emulate_routes():
    """Road-end A*, not node Dijkstra: 0080B9A0/00800520/00800650.

    File flags omit runtime barriers. This checks search structure and native
    u16 scores; live ordered-list equivalence is checked separately by --logs.
    """
    sys.path.insert(0, str(ROOT / 'tools_snapshot/worldmerge'))
    import c1_roads as roads
    index, _, _ = roads.load_index(roads.DEFAULT_CARBON, 'L5RA')
    counts, _, nodes, segments, _ = roads._reader(
        roads.collision_body(roads.one(index.parts, 0x3b800)))

    def f32(value):
        return struct.unpack('<f', struct.pack('<f', value))[0]

    lengths = [f32(s[2] * f32(1000 / 65535)) for s in segments]
    adjacent = [n[7:7+n[5]] for n in nodes]
    assert counts['roads'] == 840
    assert sum(bool(s[5] & 1) for s in segments) == 2027

    def search(source, destination, refuse_connectors=False, scale=.25):
        # These fixtures project to the first adjacent native road segment,
        # with a NULL destination heading. Seed both source segment endpoints.
        start, goal = adjacent[source][0], adjacent[destination][0]
        assert not (segments[start][5] & 1 or segments[goal][5] & 1)
        heuristic = [math.sqrt(f32(sum((x-y)**2 for x, y in
                                      zip(n[:3], nodes[destination][:3])))) for n in nodes]
        quantize = lambda value: int(value / scale + .5) & 65535
        h = [quantize(value) for value in heuristic]
        states, queue = {}, []
        inserts, maximum = 0, 0

        def slot(segment, node):
            a, _, _, road, *_ = segments[segment]
            end = int(node != a)
            if segment == start:
                return end
            if segment == goal:
                return 2 + end
            assert 0 <= road < counts['roads'], ('connector cannot own a slot', segment)
            return 4 + 2 * road + end

        def allowed(segment, node):
            s = segments[segment]
            return not (s[5] & 0x3000 or (s[5] & 0x40 and node != s[0]) or
                        (refuse_connectors and s[5] & 1))

        def other(segment, node):
            a, b = segments[segment][:2]
            assert node in (a, b)
            return b if node == a else a

        def insert(segment, node, score):
            nonlocal inserts, maximum
            key = slot(segment, node)
            inserts += 1
            maximum = max(maximum, score / scale)
            state = (quantize(score), -inserts, segment, node)
            states[key] = state
            heapq.heappush(queue, (*state[:2], key))

        def extend(segment, node, accumulated, current_g):
            if not allowed(segment, node):
                return
            far = other(segment, node)
            g = quantize(current_g + accumulated + lengths[segment]) * scale
            key = slot(segment, far)
            old = states.get(key)
            if old is not None and (old[0] - h[old[3]]) * scale <= g:
                return
            insert(segment, far, f32((h[far] * scale) + g))

        for node in segments[start][:2]:
            insert(start, node, f32(heuristic[node]))
        while queue:
            ticks, serial, key = heapq.heappop(queue)
            current = states[key]
            if current[:2] != (ticks, serial):
                continue
            _, _, incoming, node = current
            if incoming == goal:
                return {'found': True, 'inserts': inserts, 'max_f': maximum * scale,
                        'max_ticks': maximum}
            current_g = (ticks - h[node]) * scale
            for segment in adjacent[node]:
                if segment == incoming:
                    continue  # Native no U-turn.
                if segment == goal:
                    extend(segment, node, 0, current_g)
                    continue
                if not allowed(segment, node):
                    continue
                walking_node, walking_segment, accumulated = node, segment, 0
                if segments[segment][5] & 1:
                    # Connector hop to the single far road, adjacency order intact.
                    far = other(segment, node)
                    if goal in adjacent[far]:
                        extend(goal, far, lengths[segment], current_g)
                        continue
                    next_roads = [s for s in adjacent[far] if not segments[s][5] & 1]
                    assert len(next_roads) == 1
                    walking_node, walking_segment = far, next_roads[0]
                    accumulated = lengths[segment]
                seen = set()
                while walking_segment not in seen:
                    seen.add(walking_segment)
                    far = other(walking_segment, walking_node)
                    # 00800520 checks the goal before degree/filter, then
                    # stops at a junction without consuming that last segment.
                    if walking_segment == goal:
                        break
                    if len(adjacent[far]) < 2 or not allowed(walking_segment, walking_node):
                        walking_segment = None
                        break
                    if len(adjacent[far]) > 2:
                        break
                    accumulated = f32(accumulated + lengths[walking_segment])
                    previous = walking_segment
                    walking_node = far
                    walking_segment = next(s for s in adjacent[far] if s != previous)
                else:
                    walking_segment = None
                if walking_segment is not None and walking_segment != incoming:
                    extend(walking_segment, walking_node, accumulated, current_g)
        return {'found': False, 'inserts': inserts, 'max_f': maximum * scale,
                'max_ticks': maximum}

    results = {name: search(a, b) for name, (a, b, _) in PAIRS.items()}
    assert all(row['found'] for row in results.values()), results
    assert 150 <= results['short']['inserts'] <= 175, results['short']
    mutant = {name: search(a, b, refuse_connectors=True) for name, (a, b, _) in PAIRS.items()}
    assert all(not row['found'] for row in mutant.values()), mutant
    return {'native_road_end': results, 'refuse_connectors_mutant': mutant}


HARNESS = r'''
#include "funcs.h"
#include "host.h"
#include <stdarg.h>
#include <stdlib.h>
#include "route.inc"
uint8_t *G;
int diag_on=1;
static unsigned originals, registrations;
#define CHECK(x) do {if(!(x)){fprintf(stderr,"route FAIL %d: %s\n",__LINE__,#x);exit(1);}}while(0)
void diag_event(const char *fmt,...) {(void)fmt;}
uint32_t gmalloc(uint32_t size) {(void)size;abort();}
void gfree(uint32_t address) {(void)address;abort();}
uint32_t call_guest(Cpu *c,uint32_t fn,int n,const uint32_t *args) {(void)c;(void)fn;(void)n;(void)args;abort();}
void dispatch(Cpu *c,uint32_t target) {(void)c;(void)target;abort();}
uint32_t host_fn(HostFn fn,const char *name) {(void)fn;CHECK(!strcmp(name,"route probe"));++registrations;return 0xF1000000;}
void f_007EAAE0(Cpu *c) {c->eax=0;c->esp+=12;}
void f_007F6280(Cpu *c) {c->eax=arg(c,1);c->esp+=12;}
static void original(Cpu *c) {++originals;c->eax=123;c->esp+=4;}
static Cpu cpu(void) {Cpu c={0};c.esp=0x10000;c.ecx=0x20000;c.cw=0x37F;return c;}
static void native(float f, float scale, unsigned expected) {
 Cpu c=cpu();MF32(0xA7AD34)=scale;MF32(0x9C2888)=.5;
 M32(c.esp+4)=7;M32(c.esp+8)=12;M32(c.esp+12)=0x30000;
 M16(0x3000C)=17;MF32(c.esp+16)=f;
 carbon_route_measuring=1;carbon_route_max_f=carbon_route_max_ticks=0;carbon_route_samples=0;
 carbon_route_set(&c,f_007EA900);
 CHECK(M16(0x2000E)==expected);CHECK(M16(0x20008)==7);CHECK(M16(0x2000A)==12);CHECK(M16(0x2000C)==17);
 CHECK(c.esp==0x10014);CHECK(c.top==0);CHECK(carbon_route_max_f==f);CHECK(carbon_route_max_ticks==f/scale);CHECK(carbon_route_samples==1);
 carbon_route_measuring=0;
}
static void flags(void) {
 unsigned char saved[256], original_bytes[22*256];
 for(unsigned i=0;i<sizeof original_bytes;++i) M8(0x60000+i)=(unsigned char)(i*37+19);
 for(unsigned i=0;i<256;++i) M8(0x60000+22*i+11)=(unsigned char)i;
 memcpy(original_bytes,gptr(0x60000),sizeof original_bytes);
 uint64_t before=carbon_route_flags(0x60000,256,saved,0);
 CHECK(before==carbon_route_flags(0x60000,256,saved,1));
 for(unsigned i=0;i<sizeof original_bytes;++i)
   CHECK(M8(0x60000+i)==(i%22==11 ? (original_bytes[i]&0xCF) : original_bytes[i]));
 CHECK(before==carbon_route_flags(0x60000,256,saved,2));
 CHECK(!memcmp(original_bytes,gptr(0x60000),sizeof original_bytes));
}
static void insertion(void) {
 Cpu c=cpu();c.ecx=0x40000;
 MF32(0xA7AD34)=1;M32(0x40030)=0x20000;M32(0x40010)=1;M32(0x4000C)=0x50000;
 M32(c.esp+4)=0;M32(c.esp+8)=0;M32(c.esp+12)=12;M32(c.esp+16)=0x30000;
 MF32(c.esp+20)=20000;carbon_route_measuring=1;carbon_route_max_f=carbon_route_max_ticks=0;carbon_route_samples=0;
 carbon_route_insert(&c,f_007F62E0);
 CHECK(M16(0x2000E)==20000&&M16(0x2000A)==12&&M16(0x2000C)==17);
 CHECK(c.esp==0x10018&&carbon_route_max_f==20000&&carbon_route_max_ticks==20000&&carbon_route_samples==1);
 carbon_route_measuring=0;MF32(c.esp+20)=30000;carbon_route_insert(&c,original);
 CHECK(carbon_route_samples==1&&carbon_route_max_f==20000);
}
int main(int argc,char **argv) {
 CHECK(argc==3);G=calloc(1,0xC00000);CHECK(G);
 unsetenv("NFS_CARBON_ROUTE_PROBE");
 if(strcmp(argv[1],"unset"))setenv("NFS_CARBON_ROUTE_SCALE",argv[1],1);else unsetenv("NFS_CARBON_ROUTE_SCALE");
 MF32(0xA7AD34)=.25f;Cpu c=cpu();carbon_route_construct(&c,original);
 CHECK(originals==1&&c.eax==123&&c.esp==0x10004);CHECK(MF32(0xA7AD34)==strtof(argv[2],NULL));CHECK(!registrations);
 setenv("NFS_CARBON_ROUTE_SCALE","2",1);c=cpu();carbon_route_construct(&c,original);
 CHECK(MF32(0xA7AD34)==strtof(argv[2],NULL));CHECK(originals==2);
 setenv("NFS_CARBON_ROUTE_PROBE","1",1);M32(0xAB0ABC)=0x40000;M32(0x40000)=0x50000;M32(0x50044)=0x812345;
 c=cpu();carbon_route_construct(&c,original);CHECK(registrations==1&&M32(0x50044)==0xF1000000);CHECK(carbon_route_present_target==0x812345);
 c=cpu();carbon_route_construct(&c,original);CHECK(registrations==1);
 native(20000,.25f,14464);native(20000,1,20000);native(8000,.0625f,62464);
 native(16383.75f,.25f,65535);native(16384,.25f,0);native(65535,1,65535);native(65536,1,0);
 insertion();flags();
 puts("route native stock=3616m scale1=20000m capacity=65535m opt-in/once/ABI PASS");free(G);return 0;
}
'''


def expect_failure(function, *args):
    try:
        function(*args)
    except (AssertionError, KeyError, ValueError):
        return
    raise AssertionError('deliberately broken case passed')


def parser_checks():
    def log(scale):
        lines = ['carbon_route: blocked seg1000=13 seg2000=0 barriers=6/1238']
        for name, (a, b, d) in PAIRS.items():
            for mode in ('asis', 'open'):
                status, count = (0, 0) if mode == 'asis' and name != 'short' else (3, 50)
                lines.append(f'carbon_route: pair={name} mode={mode} nodes={a},{b} scale={scale} status={status} count={count} metres={d} first=1 last=2 hash=7084cd26c264468d max_f={d*1.15} max_ticks={d*1.15/scale} samples=100')
            lines.append(f'carbon_route: restore pair={name} before=0123456789abcdef after=0123456789abcdef')
        return '\n'.join(lines)
    stock, enlarged, control = (parse_log(log(scale), scale) for scale in (.25, 1, .125))
    expect_failure(acceptance, stock, enlarged, control)
    control['open']['medium']['hash'] = 'fedcba9876543210'
    assert acceptance(stock, enlarged, control)['below_limit_equal'] == list(PAIRS)
    mutants = [enlarged, enlarged, enlarged, stock, stock]
    changes = [('open', 'short', {'hash': 'fedcba9876543210'}),
               ('open', 'long', {'max_ticks': 65536}),
               ('open', 'medium', {'status': 0, 'count': 0}),
               ('open', 'medium', {'metres': 5000}),
               ('asis', 'medium', {'status': 3})]
    for template, (mode, name, change) in zip(mutants, changes):
        broken = copy.deepcopy(template)
        broken[mode][name].update(change)
        expect_failure(acceptance, broken if template is stock else stock,
                       broken if template is enlarged else enlarged, control)
    broken = copy.deepcopy(stock)
    broken['blocked'][:2] = [0, 0]
    expect_failure(acceptance, broken, enlarged, control)
    bad_logs = ['', log(.25)+'\n'+log(.25),
                log(.25).replace('max_f=', 'max_f=nan'),
                log(.25).replace('after=0123456789abcdef', 'after=fedcba9876543210'),
                log(.25).replace('mode=open', 'mode=other'),
                '\n'.join(log(.25).splitlines()[1:]),
                '\n'.join(line for line in log(.25).splitlines() if 'restore pair=long' not in line),
                log(.25).replace('mode=open', 'mode=asis')]
    for bad in bad_logs:
        expect_failure(parse_log, bad, .25)
    expect_failure(acceptance, stock, enlarged, enlarged)
    print('route parser: equivalent=3/3; rejected mutants=16/16 (including unchanged overflow and restore)')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--graph', action='store_true')
    ap.add_argument('--emulate', action='store_true')
    ap.add_argument('--logs', nargs=3, type=Path, metavar=('STOCK', 'SCALE1', 'CONTROL'))
    args = ap.parse_args()
    if args.logs:
        print(json.dumps(acceptance(*(read_log(p, s) for p, s in zip(args.logs, (.25, 1, .125)))), indent=2))
        return 0
    image = HERE / 'out/carbon-base/image.json'
    if not image.is_file():
        print('SKIP: route test needs private translated outputs')
        return 3
    executable = Path(json.loads(image.read_text())['exe'])
    if not executable.is_file():
        print('SKIP: route test needs private executable')
        return 3
    assert hashlib.sha256(executable.read_bytes()).hexdigest() == IMAGE_SHA
    sys.path.insert(0, str(HERE))
    import recomp
    pe = recomp.PE(str(executable), expected_sha256=IMAGE_SHA)
    assert pe.read(0xA7AD34, 4) == bytes.fromhex('0000803e')
    fragments = {}
    for address, (chunk, digest) in FRAGMENTS.items():
        fragments[address] = fragment(address, chunk)
        assert hashlib.sha256(fragments[address].encode()).hexdigest() == digest, hex(address)
        assert 'untranslated(c,' not in fragments[address]
    parser_checks()
    source = (PRIVATE / 'carbon_route.h').read_text()
    probe = source[source.index('static uint64_t carbon_route_flags('):source.index('static int carbon_route_present(')]
    assert hashlib.sha256(probe.encode()).hexdigest() == '59ba20b0355146361d618675d3849dd29cbfdd86d3a17e770aa3a35048fa06b1'
    feature = json.loads((PRIVATE / 'features/route.json').read_text())
    assert hashlib.sha256(source.encode()).hexdigest() == feature['bindings']['carbon_route.c']['sha256']
    with tempfile.TemporaryDirectory(prefix='route-test-') as temp:
        out = Path(temp)
        (out / 'native.c').write_text('#include "funcs.h"\n' + '\n'.join(fragments[a] for a in (0x007EA900, 0x007F62E0, 0x0087EAC0)))
        (out / 'harness.c').write_text(HARNESS)
        for broken in ('', 'scale', 'restore'):
            selected = source
            if broken == 'scale':
                selected = source.replace('MF32(0x00A7AD34u) = scale;', '(void)scale;')
            elif broken == 'restore':
                selected = source.replace('else if (action == 2) M8(address) = saved[i];', 'else if (action == 2) (void)saved[i];')
            (out / 'route.inc').write_text(selected)
            command = ['clang', '-std=c11', '-O0', '-I'+str(HERE), '-I'+str(ROOT/'runtime'),
                       '-I'+str(HERE/'out/carbon-base'), str(out/'native.c'), str(out/'harness.c'), '-o', str(out/'check')]
            result = subprocess.run(command, capture_output=True, text=True)
            assert result.returncode == 0, result.stderr[-3500:]
            cases = [('1', '1')] if broken else [('unset','.25'),('1','1'),('.0625','.0625'),('nan','.25'),('0','.25'),('-1','.25'),('1junk','.25')]
            for setting, expected in cases:
                result = subprocess.run([str(out/'check'), setting, expected], capture_output=True, text=True)
                assert result.returncode == int(bool(broken)), (setting, broken, result.stdout, result.stderr)
        print('route wrapper/native: good cases=7/7; omitted-write/restore controls exit=1; flag bytes=256/256; pinned fragments=4/4')
    try:
        emulated = emulate_routes()
    except FileNotFoundError:
        print('SKIP: road-end emulator needs private road file')
        return 3
    if args.emulate:
        print(json.dumps(emulated, indent=2))
    else:
        print('route road-end: inserts=' + '/'.join(str(r['inserts']) for r in
              emulated['native_road_end'].values()) + '; refused-connectors found=0/3')
    if args.graph:
        print(json.dumps(graph_fixtures(), indent=2))
    print('private_route_test PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
