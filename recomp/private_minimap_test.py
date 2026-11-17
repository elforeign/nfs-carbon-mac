"""Scoped HUD tuples and retained native projection (no game).

Good: four wrappers restore entry bits, including nesting and track changes;
Off preserves arbitrary bits. Native x87 projection agrees within 1e-6.
Old-stock tuple: check 3/exit 1; omitted restore: check 7/exit 1 versus good rockport 178 checks/exit 0.
One-tile bx mutant u=0.558716893196 versus good 0.621216893196: delta=-0.0625,
correct-calibration error 0.0625 versus good <1e-6.
Exit 3 without the private executable or translated fragment witnesses.
Retained 006AABA0: old zero-first stream decodes 32768/65684 bytes and misses
the record hash; fixed and stock decode 65684/65684 byte-identically. Replacing
only the fixed first destination with zero reproduces the record lookup miss.
Both retained native decoders: 512/512 rewritten records byte-identical.
World-map scope: three widened words in callback; all six restored, nested
inside HUD too. Good atlas 135 checks (142 with diag)/exit 0; old no-scope
fails callback memory check 3/exit 1 (12582912 guest bytes compared).
Game f1500: old 0 tile bindings, fixed 4 (stock 4). Marker-centred 16x16
RGB mean: empty 107.27734375, fixed 120.03515625 /255, require gain >8.
World-map art: old pass-through draws 0, fixed draws 9; complete retained
005B0A50 caller, ASan/UBSan assertions across 20 runs, including all eight
native parent/depth/mode cases, invalid geometry, residency and release/reopen.
Right map-edge veil (75C4ABD4 solid + A5CA44F5 fade, mirrored group) shifted
-794 local units for its own draw only: good local x -931; unmoved control
(shift 0) fails at the veil check with x -137 (it blacked out Rockport u>=1.37).
Native fade A5CA44F5: type 9, black RGB, four-corner alpha 255,0,0,255;
150 local units (~371 screen px at default zoom), image reference 0 (the
native 0055CFD0 fallback, DEFAULTALPHA / 66994F4A), not a fade texture. Art reuses 005995E0's
linear corner-alpha ramp at quarter width (~93 px) on all four borders;
nine independently checked rectangles/UV ranges, including corner alphas.
No-fade mutant: border alpha 255 fails versus fixed 0; missing draw also fails.
Car-centred edge proof (Rec.601; rows 0..879, column differences 366..382):
before JPEG step 15.3371 / seam-row 20.8597; fade raw step .3683, art 77.4360%;
labelled JPEG step .4399, art 77.3519% (limits <=5, >=75%).
Live no-fade control (all corner alphas 255): step 13.3944, seam-row 18.9769,
art 78.8462%; same logged pan (1.2257489,.18226701), threshold >=12.
The original hard-edge JPEG supplied as the candidate fails the edge check.
Matched live pair, both atlas at the car-centred pan 1.2257489,0.18226701, ROI
[380,1368)x[72,900) inside Rockport's rect: art skipped 27398/818064 (3.35%),
art on 676131/818064 (82.65%); require control <10%, atlas >50%.
"""
import argparse
import hashlib
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
sys.path.insert(0, str(HERE))
from build_private import ignored_output
import recomp
import private_hooks

IMAGE_SHA = 'baaaaec33873d4ba7e4dbae6a5212049ffdcf9679a35d865d7625b4189952fd3'
# Complete retained function fragments, normalized only to their original name.
FRAGMENTS = {
    0x005D1F80: 'b3e62be9fd05a5b650b2f7c2b4fa21baa9adcc3bff62fd0569c9a2346cb485a5',
    0x005D23E0: 'd9b1ad24496b2593769cd4a4396d351511b63eddc4aafdbc8fd3e306438fade1',
    0x005E15B0: '4b4c536442c6599decb4e0c32105409a72bb2483137ca6693690ba4856b2ff63',
    0x005E50F0: 'ac6993cc5223e02abc143a36a5f8e48d1affb0e86e16955bf5d4ce2622e5aaf8',
    0x0056ECA0: '838ea659ff07fdeb2ebf28eff3985a626b9f5715e91a17c3779b4778c393b79b',
    0x005B7940: 'b7c949b50df3d3f6eb8099fa1134871d77ff8070874ef3c7aa2a4e5d01991011',
    0x005B7CE0: '830132c2dbc3cb0a278951bf307f70cd080c938b9071243f4a0141cc38630025',
    0x005825A0: '442056aed43bf47f2bda746445fc62432056f126de666b5816a70483928ed817',
}
FRAGMENT_UNITS = {0x0056ECA0: 18, 0x005B7940: 21, 0x005B7CE0: 21, 0x005825A0: 19}
CALIBRATIONS = ((-1224.889404296875, -1591.1448974609375, 0.00015016521501820534),
                (-7300., -6992., 0.00004763719334732741))
MANIFEST_SHA = ('9dce33c699bfae451f61eece71836405ba3417348d96bd2e3039843e1f16b873',
                '08f642a3ccdf43fbe99f8e583117850120ef1ded6f35277f376264027ddc669b')
PROVIDERS = ('icons', 'roads', 'tiles', 'centre')
WORLD_PROVIDERS = ('input_a', 'input_b', 'input_c', 'streamer')
BEGIN, END = '/* BEGIN GENERATED HUD CALIBRATION */', '/* END GENERATED HUD CALIBRATION */'


def calibration_table(rows):
    result = BEGIN + '\nstatic const struct { float bx, by, k; } carbon_minimap_calibration[] = {\n'
    for row in rows:
        result += '    {' + ', '.join(float(v).hex() + 'f' for v in row) + '},\n'
    return result + '};\n' + END


def generate(paths):
    rows = []
    for index, path in enumerate(paths):
        raw = path.read_bytes()
        assert hashlib.sha256(raw).hexdigest() == MANIFEST_SHA[index], 'calibration manifest fingerprint'
        manifest = json.loads(raw)
        assert manifest['layout'] == ('rockport', 'shared')[index]
        row = tuple(manifest['hud'][key] for key in ('bx', 'by', 'k'))
        assert row == CALIBRATIONS[index]
        rows.append(row)
    path = PRIVATE / 'carbon_minimap.h'
    source = path.read_text()
    start, end = source.index(BEGIN), source.index(END) + len(END)
    path.write_text(source[:start] + calibration_table(rows) + source[end:])
    feature = PRIVATE / 'features/minimap.json'
    if feature.is_file():
        data = json.loads(feature.read_text())
        data['bindings']['carbon_minimap.c']['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
        feature.write_text(json.dumps(data, indent=2) + '\n')


def fragment(address):
    unit = FRAGMENT_UNITS.get(address, 22)
    source = (HERE / f'out/carbon-base/NFSC_{unit}.c').read_text()
    match = re.search(rf'void (?:f_|carbon_orig_){address:08X}\(Cpu [^)]*\)\s*\{{', source)
    assert match, hex(address)
    text = source[match.start():source.index('\n}', match.end()) + 2]
    return text.replace(f'carbon_orig_{address:08X}(', f'f_{address:08X}(', 1)


def projection(point, row):
    bx, by, k = row
    u, v = (point[0]-bx)*k, 1+(by-point[1])*k
    return u, v, math.floor(v*16)*16+math.floor(u*16)


def check_log(path, mode, mutant=False):
    rows, errors, deltas = [], [], []
    with path.open() as stream:
        for line in stream:
            if 'carbon_minimap: ' not in line:
                continue
            fields = dict(re.findall(r'(\w+)=([^\s]+)', line.split('carbon_minimap: ', 1)[1]))
            assert fields['mode'] == mode
            track = int(fields['track'])
            assert track == (5000 if mode == 'off' else 2000)
            row = CALIBRATIONS[1 if mode == 'atlas' else 0] if mode != 'off' else (-7300., -2000., struct.unpack('<f', struct.pack('<f', 1/16000))[0])
            observed = tuple(float(fields[k]) for k in ('bx', 'by', 'k'))
            shift = 1 / (16*row[2]) if mutant else 0
            assert abs(observed[0]-row[0]-shift) < 1e-3
            assert abs(observed[1]-row[1]) < 1e-6 and abs(observed[2]-row[2]) < 1e-15
            assert int(fields['mutant']) == int(mutant)
            point = tuple(map(float, fields['render'].split(',')))
            expected = projection(point, row)
            u, v = float(fields['u']), float(fields['v'])
            # First entry can precede the native HUD's first active update.
            if u == 0 and v == 0:
                continue
            assert abs(u-expected[0]+(1/16 if mutant else 0)) <= 1e-4, fields
            assert abs(v-expected[1]) <= 1e-4, fields
            tile = math.floor(v*16)*16+math.floor(u*16)
            assert int(fields['tile']) == tile
            if not mutant:
                assert tile == expected[2]
            errors.append(max(abs(u-expected[0]+(1/16 if mutant else 0)), abs(v-expected[1])))
            deltas.append(u-expected[0])
            rows.append((u, v, tile, point))
    assert len(rows) >= 3, ('missing live samples', len(rows))
    return {'samples': len(rows), 'first': rows[0], 'last': rows[-1], 'max_uv_error': max(errors), 'max_tile_pixel_error': 4096*max(errors),
            'u_delta_from_correct': [min(deltas), max(deltas)], 'mutant': mutant}


def check_frame(empty, fixed, draws, stock_draws):
    from PIL import Image, ImageStat
    pattern = r'^  s0: tex [0-9A-F]+ kind 3 fmt 33545844 256x256 levels 1 '
    def bindings(path):
        with path.open() as stream:
            return sum(bool(re.match(pattern,line)) for line in stream)
    count, stock = bindings(draws), bindings(stock_draws)
    assert count > 0 and count == stock == 4, ('tile bindings',count,stock)
    patch = (224,828,240,844)
    means = []
    for path in (empty,fixed):
        with Image.open(path) as im:
            assert im.size == (1920,1080), ('capture size',im.size)
            means.append(sum(ImageStat.Stat(im.convert('RGB').crop(patch)).mean)/3)
    assert means[1]-means[0] > 8, ('road-under-marker brightness gain',means)
    return {'bindings':count,'stock_bindings':stock,'patch':patch,'mean_rgb_before_after':means}


HARNESS = r'''
#include <stdarg.h>
uint8_t *G;
int diag_on;
static unsigned checks, calls, logs;
static char icon_line[1024];
static float expected[3], point_x=2912, point_y=160;
static uint64_t clock_value=1000000000ull;
#define CHECK(v) do {++checks;if(!(v)){fprintf(stderr,"MINIMAP CHECK %u line %d: %s\n",checks,__LINE__,#v);exit(1);}} while(0)
uint64_t host_ticks(void){return clock_value;}
int private_carbon_player_position(float *p){p[0]=point_x;p[1]=point_y;p[2]=45;return 1;}
void diag_event(const char *fmt,...){va_list ap;va_start(ap,fmt);vsnprintf(icon_line,sizeof icon_line,fmt,ap);va_end(ap);++logs;}
static void check_tuple(void){CHECK(MF32(0x9D5F10u)==expected[0]);CHECK(MF32(0x9D5F08u)==expected[1]);CHECK(MF32(0x9D5F0Cu)==expected[2]);}
static void leaf(Cpu *c){check_tuple();++calls;c->eax=0x12345678;c->esp+=4;}
static void nested(Cpu *c){check_tuple();carbon_minimap_tiles(c,leaf);check_tuple();carbon_minimap_roads(c,leaf);check_tuple();carbon_minimap_icons(c,leaf);check_tuple();}
static void native_projection(Cpu *c){
 c->esi=c->ecx;c->ebp=c->ecx+0xAC;
 MF32(c->ebp)=point_x;MF32(c->esi+0xB0)=point_y;
 /* NATIVE_PROJECTION */
}
static void stock(void){MF32(0x9D5F10u)=-7300;MF32(0x9D5F08u)=-2000;MF32(0x9D5F0Cu)=1.0f/16000;}
static void snapshot(uint32_t *v){v[0]=M32(0x9D5F10u);v[1]=M32(0x9D5F08u);v[2]=M32(0x9D5F0Cu);}
static void restored(const uint32_t *v){CHECK(M32(0x9D5F10u)==v[0]);CHECK(M32(0x9D5F08u)==v[1]);CHECK(M32(0x9D5F0Cu)==v[2]);}
int main(int argc,char **argv){
 G=calloc(1,0xC00000);CHECK(G);CHECK(argc==3);int mode=atoi(argv[1]);diag_on=atoi(argv[2]);
 void (*wrappers[])(Cpu*,void(*)(Cpu*))={carbon_minimap_icons,carbon_minimap_roads,carbon_minimap_tiles,carbon_minimap_centre};
 const float rows[][3]={{-1224.889404296875f,-1591.1448974609375f,0.00015016521501820534f},{-7300,-6992,0.00004763719334732741f}};
 const unsigned tracks[]={2000,5000,2000};
 MF32(0x9C2478u)=1;
 for(unsigned t=0;t<3;t++){
  M32(0xA7A1A8u)=tracks[t];stock();uint32_t saved[3];snapshot(saved);
  int active=mode==2 || (mode==1 && tracks[t]==2000);
  if(active)memcpy(expected,rows[mode==2],sizeof expected);
  else{expected[0]=-7300;expected[1]=-2000;expected[2]=1.0f/16000;}
#if CARBON_MINIMAP_TEST_SHIFT
  if(active)expected[0]+=1.0f/(16.0f*expected[2]);
#endif
  for(unsigned w=0;w<4;w++){
   Cpu c={0};c.ecx=0x4000;c.esp=0x10000;c.cw=0x37f;Cpu direct=c;direct.eax=0x12345678;direct.esp+=4;
   wrappers[w](&c,leaf);CHECK(!memcmp(&c,&direct,sizeof c));restored(saved);
  }
  Cpu c={0};c.ecx=0x4000;c.cw=0x37f;carbon_minimap_centre(&c,nested);restored(saved);
  point_y=160;carbon_minimap_centre(&c,native_projection);restored(saved);
  double u=(point_x-(double)expected[0])*expected[2],v=1+(expected[1]-(double)point_y)*expected[2];
  CHECK(fabs(MF32(0x40AC)-u)<1e-6);CHECK(fabs(MF32(0x40B0)-v)<1e-6);
  if(mode==1 && active){
#if CARBON_MINIMAP_TEST_SHIFT
    CHECK(fabs(MF32(0x40AC)-0.6212168869)>0.06);
#else
    CHECK(fabs(MF32(0x40AC)-0.6212168869)<1e-6);CHECK(fabs(MF32(0x40B0)-0.7370389499)<1e-6);
#endif
  }
  if(mode==2){point_x=11104;carbon_minimap_centre(&c,native_projection);restored(saved);point_x=2912;
   CHECK(fabs(MF32(0x40AC)-0.8767149064)<1e-6);CHECK(fabs(MF32(0x40B0)-0.6592987932)<1e-6);
  }
 }
 if(!mode){
  // Off must preserve even non-float payloads, not rewrite the stock values.
  M32(0x9D5F10u)=0x7FC12345;M32(0x9D5F08u)=0x80000000;M32(0x9D5F0Cu)=0x12345678;
  uint32_t saved[3];snapshot(saved);Cpu c={0};
  for(unsigned w=0;w<4;w++){wrappers[w](&c,native_projection);restored(saved);}
 }
 if(diag_on){CHECK(logs==1);clock_value+=999999999;carbon_minimap_log(0x4000,2000,mode,0,0,0);CHECK(logs==1);clock_value++;carbon_minimap_log(0x4000,2000,mode,0,0,0);CHECK(logs==2);}
 else CHECK(!logs);
 // Allocated-but-inactive entries must participate in region counts. The
 // original +2FC-only walk misses the two appended-region icons below.
 M32(0xA98294)=0x5000;M32(0x52F8)=4;M32(0x52FC)=1;M32(0x5300)=0x6000;
 for(unsigned i=0;i<4;i++){M32(0x6000+4*i)=0x7000+0x28*i;M8(0x7001+0x28*i)=3;}
 MF32(0x7010)=5924;MF32(0x7038)=8890;MF32(0x7060)=10000;MF32(0x7088)=7000;
 M8(0x7051)=1;
 unsigned before=logs;clock_value+=1000000000ull;
 carbon_minimap_log(0x4000,5000,mode,0,0,0);
 if(diag_on){CHECK(logs==before+1);CHECK(strstr(icon_line,"icons=1 shown=1 alloc=4 rock=2 rock_shown=1"));}
 else {
  CHECK(logs==before);
  M32(0xA98294)=0xFFFFFFF0; // Diag off must return before reading the manager.
  carbon_minimap_log(0x4000,5000,mode,0,0,0);CHECK(logs==before);
 }
 printf("MINIMAP PASS checks=%u calls=%u mode=%d diag=%d mutant=%d\n",checks,calls,mode,diag_on,CARBON_MINIMAP_TEST_SHIFT);free(G);return 0;
}
'''


def run(args, expected=0, env=None):
    result = subprocess.run(list(map(str, args)), capture_output=True, text=True, env=env, timeout=120)
    assert result.returncode == expected, (args[:2], result.returncode, result.stdout[-1000:], result.stderr[-2000:])
    return result


def fixture(out, native, broken=None, mutant=False):
    source = (PRIVATE / 'carbon_minimap.h').read_text()
    if broken == 'restore':
        old = 'M32(0x009D5F10u) = saved_bx;'
        assert source.count(old) == 1
        source = source.replace(old, '(void)saved_bx;')
    elif broken == 'stock':
        old = 'int active = mode == 2 || (mode == 1 && track == 2000);'
        assert source.count(old) == 1
        source = source.replace(old, 'int active = 0;')
    elif broken == 'active_only':
        old = 'i < alloc && i < 256'
        assert source.count(old) == 1
        source = source.replace(old, 'i < listed && i < 256')
    code = source + HARNESS.replace('/* NATIVE_PROJECTION */', native)
    path = out / ('fixture' + ('-'+broken if broken else '-mutant' if mutant else '') + '.c')
    path.write_text(code)
    binary = path.with_suffix('')
    run(['clang', '-O1', '-g', '-fsanitize=address,undefined', '-DCARBON_MINIMAP_TEST_SHIFT='+str(int(mutant)),
         '-I', ROOT/'runtime', '-I', HERE, path, '-o', binary])
    return binary


WORLD_HARNESS = r'''
#include <stdarg.h>
uint8_t *G;
int diag_on;
static unsigned checks, calls, logs;
static uint8_t *expected;
static uint64_t clock_value=1000000000ull;
static char line[1024];
#define CHECK(v) do {++checks;if(!(v)){fprintf(stderr,"WORLDMAP CHECK %u line %d: %s\n",checks,__LINE__,#v);exit(1);}} while(0)
uint64_t host_ticks(void){return clock_value;}
int private_carbon_player_position(float *p){(void)p;return 0;}
void diag_event(const char *fmt,...){va_list ap;va_start(ap,fmt);vsnprintf(line,sizeof line,fmt,ap);va_end(ap);++logs;}
static void (*wrappers[])(Cpu*,void(*)(Cpu*))={carbon_worldmap_input_a,carbon_worldmap_input_b,carbon_worldmap_input_c,carbon_worldmap_streamer};
static void memory_ok(void){CHECK(!memcmp(G,expected,0xC00000));}
static void leaf(Cpu *c){memory_ok();++calls;c->eax=0x12345678;c->ecx=0x7000;c->esp+=4;}
static void nested(Cpu *c){
 memory_ok();
 for(unsigned w=0;w<4;w++){c->ecx=0x4000;wrappers[w](c,leaf);memory_ok();}
}
static void hud_nested(Cpu *c){
 uint32_t saved[3];const unsigned a[]={0x9D5F10,0x9D5F08,0x9D5F0C};
 for(unsigned i=0;i<3;i++)memcpy(&saved[i],expected+a[i],4);
 for(unsigned i=0;i<3;i++)memcpy(expected+a[i],G+a[i],4);
 CHECK(MF32(0x9D5F10u)==-7300);CHECK(MF32(0x9D5F08u)==-6992);
 CHECK(MF32(0x9D5F0Cu)==0.00004763719334732741f);
 carbon_worldmap_input_a(c,nested);
 for(unsigned i=0;i<3;i++)memcpy(expected+a[i],&saved[i],4);
}
static void diagnostic_leaf(Cpu *c){
 leaf(c);MF32(0x4080)=1.75f;MF32(0x40AC)=0.375f;
}
int main(int argc,char **argv){
 G=calloc(1,0xC00000);expected=malloc(0xC00000);CHECK(G&&expected);CHECK(argc==3);
 int mode=atoi(argv[1]);diag_on=atoi(argv[2]);
 const unsigned a[]={0x9CEE40,0x9CEE48,0x9CEE3C,0x9CEE44,0x9CEDBC,0x9CEDC4};
 const uint32_t stock[]={0x3D408312,0x3F7D70A4,0x3C449BA6,0x3F5EB852,0xBE883BE6,0x3F9F1077};
 MF32(0x4080)=1.25;MF32(0x40AC)=0.1875;MF32(0x4088)=1.5;MF32(0x40B4)=0.25;
 MF32(0x4084)=99;MF32(0x408C)=-99;
 MF32(0x40DC)=-1;MF32(0x40E0)=-2;MF32(0x40E4)=3;MF32(0x40E8)=4;
 for(unsigned arbitrary=0;arbitrary<2;arbitrary++){
  uint32_t saved[6];
  for(unsigned i=0;i<6;i++)M32(a[i])=saved[i]=arbitrary?0x7FC12340+i:stock[i];
  memcpy(expected,G,0xC00000);
  if(mode==2){
   uint32_t bits=0x4008B880;memcpy(expected+0x9CEE48,&bits,4);
   bits=0xBE08F430;memcpy(expected+0x9CEE3C,&bits,4);
   bits=0x4018E493;memcpy(expected+0x9CEDC4,&bits,4);
  }
  for(unsigned w=0;w<4;w++){
   Cpu c={0};c.ecx=0x4000;c.esp=0x10000;Cpu direct=c;direct.eax=0x12345678;direct.ecx=0x7000;direct.esp+=4;
   wrappers[w](&c,leaf);CHECK(!memcmp(&c,&direct,sizeof c));
   for(unsigned i=0;i<6;i++)CHECK(M32(a[i])==saved[i]);
  }
  Cpu c={0};c.ecx=0x4000;carbon_worldmap_input_b(&c,nested);
  for(unsigned i=0;i<6;i++)CHECK(M32(a[i])==saved[i]);
  if(mode==2){
   c.ecx=0x4000;carbon_minimap_tiles(&c,hud_nested);
   for(unsigned i=0;i<6;i++)CHECK(M32(a[i])==saved[i]);
   CHECK(!M32(0x9D5F10u)&&!M32(0x9D5F08u)&&!M32(0x9D5F0Cu));
  }
 }
 if(diag_on){
  CHECK(logs==1);
  CHECK(strstr(line,"cur=1.25,0.1875 des=1.5,0.25 extent=-1,-2..3,4"));
  CHECK(strstr(line,mode==2?"lim=4008B880,BE08F430,4018E493":"lim=3F7D70A4,3C449BA6,3F9F1077"));
  Cpu c={0};c.ecx=0x4000;clock_value+=999999999;
  carbon_worldmap_streamer(&c,leaf);CHECK(logs==1);
  clock_value++;c.ecx=0x4000;carbon_worldmap_streamer(&c,diagnostic_leaf);CHECK(logs==2);
  CHECK(strstr(line,"cur=1.75,0.375 des=1.5,0.25"));
 }else CHECK(!logs);
 printf("WORLDMAP PASS checks=%u calls=%u mode=%d diag=%d words=3 restored=6 memory_bytes=12582912\n",checks,calls,mode,diag_on);
 free(expected);free(G);return 0;
}
'''


def worldmap_fixture(out):
    import os
    source = (PRIVATE/'carbon_minimap.h').read_text()
    # Removing the scope's body is exactly the old pass-through behaviour.
    start = source.index('static void carbon_worldmap_scope(')
    end = source.index('\n}', start)+2
    passthrough = 'static void carbon_worldmap_scope(Cpu *c, void (*original)(Cpu *), int stream) {(void)stream;original(c);}'
    binaries = []
    for name, text in (('good',source), ('old',source[:start]+passthrough+source[end:])):
        path = out/f'worldmap-{name}.c'
        path.write_text(text+WORLD_HARNESS)
        binary = path.with_suffix('')
        run(['clang','-O1','-g','-fsanitize=address,undefined','-I',ROOT/'runtime','-I',HERE,path,'-o',binary])
        binaries.append(binary)
    env = {k:v for k,v in os.environ.items() if k != 'NFS_CARBON_MINIMAP'}
    for mode, name in enumerate(('off','rockport','atlas')):
        for diag in (0,1):
            print(run([binaries[0],mode,diag],env={**env,'NFS_CARBON_MINIMAP':name}).stdout.strip())
    print(run([binaries[0],0,0],env=env).stdout.strip()+' unset')
    result = run([binaries[1],2,0],expected=1,env={**env,'NFS_CARBON_MINIMAP':'atlas'})
    print('old no-scope rejected:',result.stderr.splitlines()[0])


STREAM_HARNESS = r'''
#include "host.h"
#include "huff.h"
#include <stdlib.h>
uint8_t *G;
static unsigned decoded;
/* NATIVE_JDLZ */
void host_import(Cpu *c,uint32_t slot){
 if(slot==0x9C1254)c->eax=0x40000;
 else if(slot!=0x9C1258)abort();
 c->esp+=4;
}
static unsigned decode_at(uint32_t src,uint32_t dst){
 unsigned n=M32(src+8),got=0;
 if(M32(src)==0x5A4C444A){
  Cpu c={0};c.esp=0xE0000;M32(c.esp+4)=src;M32(c.esp+8)=dst;
  native_jdlz(&c);got=c.eax;
 }
 else if(M32(src)==0x46465548)got=huff_native(G+src,16+M32(src+12),G+dst,n);
 else if(M32(src)==0x57574152){memcpy(G+dst,G+src+16,n);got=n;}
 if(got!=n)abort();decoded+=got;return got;
}
void f_0069C5D0(Cpu *c){c->eax=decode_at(M32(c->esp+4),M32(c->esp+8));c->esp+=4;}
void f_0069C730(Cpu *c){c->eax=decode_at(c->eax-16,M32(c->esp+4));c->esp+=4;}
void f_0069EC80(Cpu *c){(void)c;abort();}
void f_0069EDE0(Cpu *c){c->eax=decode_at(M32(c->esp+4),M32(c->esp+8));c->esp+=4;}
/* NATIVE_STREAM */
int main(int argc,char **argv){
 G=calloc(1,0x100000);if(!G)abort();
 if(argc==2){
  FILE *f=fopen(argv[1],"rb");if(!f)abort();unsigned sizes[2],count=0;
  uint8_t expected[65684];
  while(fread(sizes,4,2,f)==2){
   if(sizes[0]>0x20000 || sizes[1]!=sizeof expected)abort();
   memset(G,0,0x100000);decoded=0;
   if(fread(G+0x10000,1,sizes[0],f)!=sizes[0] || fread(expected,1,sizeof expected,f)!=sizeof expected)abort();
   Cpu c={0};c.esp=0xF0000;M32(c.esp+4)=0x10000;M32(c.esp+8)=sizeof expected;
   f_006AABA0(&c);
   if(decoded!=65684 || memcmp(G+0x10000,expected,sizeof expected))abort();
   ++count;
  }
  fclose(f);printf("STREAM CORPUS %u/%u native byte-identical\n",count,count);free(G);return count==512?0:1;
 }
 if(argc!=4)return 2;
 FILE *f=fopen(argv[1],"rb");if(!f)abort();unsigned stored=fread(G+0x10000,1,0x20000,f);fclose(f);
 uint8_t expected[65684];f=fopen(argv[2],"rb");if(!f)abort();
 if(fread(expected,1,sizeof expected,f)!=sizeof expected)abort();fclose(f);
 Cpu c={0};c.esp=0xF0000;M32(c.esp+4)=0x10000;M32(c.esp+8)=sizeof expected;
 f_006AABA0(&c);
 unsigned hash=M32(0x10000+65536+12),want;memcpy(&want,expected+65536+12,4);
 int equal=!memcmp(G+0x10000,expected,sizeof expected);
 printf("STREAM stored=%u decoded=%u/65684 hash=%08X wanted=%08X equal=%d\n",stored,decoded,hash,want,equal);
 int good=atoi(argv[3]);int ok=(good?equal && decoded==65684 && hash==want:!equal && decoded==32768 && hash!=want);
 free(G);return ok?0:1;
}
'''


def stream_fixture(out):
    """Execute the complete retained in-place decoder, with real bounded codecs."""
    sys.path.insert(0, str(ROOT/'tools_snapshot/worldmerge'))
    import minimap as m
    from merge import DEFAULT_MW, DEFAULT_CARBON
    try:
        _, targets = m.inputs(DEFAULT_MW, DEFAULT_CARBON)
    except FileNotFoundError:
        return False
    pack = m.read_stock(targets[0], m.BASES[0])
    hs = m.name_hash(m.tile_name(pack.base, 183))
    entry = next(e for e in pack.entries if e[0] == hs)
    canvas = m.source_canvas(m.inputs(DEFAULT_MW, DEFAULT_CARBON)[0]).resize((4096,4096), m.Image.Resampling.BILINEAR)
    pixels = m.xt.encode_dxt('DXT3', m.np.asarray(canvas.crop((7*256,11*256,8*256,12*256))))
    blob = pixels+pack.blobs[hs][-148:]
    source = (HERE/'out/carbon-base/NFSC_33.c').read_text()
    start = source.index('void f_006AABA0(Cpu *restrict c) {')
    native = source[start:source.index('\n}', start)+2]
    assert hashlib.sha256(native.encode()).hexdigest() == 'dc5c7b6cc13c2457f6a1ad0f4863a757256575c09901f6e1242dbef69725d5ac'
    source = (HERE/'out/carbon-base/NFSC_31.c').read_text()
    start = source.index('void f_0069C5D0(Cpu *restrict c) {')
    codec = source[start:source.index('\n}',start)+2]
    assert hashlib.sha256(codec.encode()).hexdigest() == '0f4f6d9a86556151d2074197ea0f714baf7bcac64a22de3deb7bac23dba60b2b'
    codec = codec.replace('f_0069C5D0(', 'native_jdlz(', 1)
    code = STREAM_HARNESS.replace('/* NATIVE_JDLZ */', codec).replace('/* NATIVE_STREAM */', native)
    path = out/'stream.c'; path.write_text(code)
    binary = out/'stream'
    run(['clang','-O1','-g','-fsanitize=address,undefined','-I',ROOT/'runtime','-I',HERE,path,'-o',binary])
    old = bytearray()
    for dst in range(0,len(blob),32768):
        part = blob[dst:dst+32768]
        old += struct.pack('<6I',0x55441122,len(part),len(part)+40,dst,len(old),0)
        old += b'RAWW\x01\x10\0\0'+struct.pack('<2I',len(part),len(part))+part
    fixed = m.stream_entry(blob)
    mutant = bytearray(fixed); struct.pack_into('<I',mutant,12,0)
    for name, raw, expected, good in (
            ('stock',pack.raw[entry[1]:entry[1]+entry[2]],pack.blobs[hs],1),
            ('old',old,blob,0),('fixed',fixed,blob,1),('old-field',mutant,blob,0)):
        inp, ref = out/(name+'.stream'),out/(name+'.decoded')
        inp.write_bytes(raw);ref.write_bytes(expected)
        print(name+': '+run([binary,inp,ref,good]).stdout.strip())
    pixels = m.encode_canvas(canvas, pack.base)
    corpus = out/'stream-corpus.bin'
    with corpus.open('wb') as stream:
        for target, base in zip(targets,m.BASES):
            stock = m.read_stock(target,base)
            for tile in range(256):
                pix = pixels[m.name_hash(m.tile_name(pack.base,tile))]
                tail = stock.blobs[m.name_hash(m.tile_name(base,tile))][-148:]
                blob = pix+tail
                encoded = m.stream_entry(blob)
                stream.write(struct.pack('<2I',len(encoded),len(blob))+encoded+blob)
    print(run([binary,corpus]).stdout.strip())
    return True


ART_CALLER_SHA = '707f1fbba008733b3164419f1aa177a30165aa489bd2dee4df2d0bf61cf5b357'

ART_HARNESS = r'''
uint8_t *G;
static unsigned checks, requests, resolves, draws, drains, releases, originals, depth_calls;
static int active, scenario, resident = 1;
static const uint32_t owner=0x1000, image=0x2000, t=0x4000, cache=0x6000, renderer=0x7000;
static const uint32_t veil_obj=0x8000, veil_t=0x8800;
static float veil_seen;
#define ART_CHECK(v) do { ++checks; if (!(v)) { fprintf(stderr,"ART CHECK %u line %d: %s\n",checks,__LINE__,#v);exit(1); } } while (0)
static int near(double a,double b) { return fabs(a-b)<.002; }
uint32_t call_guest(Cpu *c,uint32_t fn,int n,const uint32_t *a) {
    if(fn==0x00560080) {
        ART_CHECK(active && n==6 && M32(a[0])==0x0F365871 && a[1]==1 && a[2]==0 && a[3]==0 && a[4]==7 && a[5]==UINT32_MAX);
        ++requests;
    } else if(fn==0x0055CFD0) {
        ART_CHECK(active && n==3 && a[0]==0x0F365871 && a[1]==0 && a[2]==0);
        ++resolves; return resident?0x9000:0;
    } else if(fn==0x005995E0) {
        ART_CHECK(active && resident && n==2 && a[0]==image && a[1]==cache && c->ecx==renderer);
        uint32_t patch=M32(image+0x2C);
        ART_CHECK(patch!=t && M32(image+0x24)==0x0F365871 && (M32(image+0x1C)&0x02400000)==0x02400000);
        unsigned x=draws%3,y=draws/3;
        /* Independently derived map-space border: 37.5 of 1082.405714 local units.
         * Check each patch's projected edges, contiguous UVs and four alphas. */
        const double cut[]={0,37.5/1082.40571392,1-37.5/1082.40571392,1};
        double left=-512+1024*(1.089223904-(double)1.34545445f)/((double)2.25454521f-(double)1.34545445f);
        double right=-512+1024*(2.146260734-(double)1.34545445f)/((double)2.25454521f-(double)1.34545445f);
        double top=-512+1024*(-.145743989-(double)(-.0717708766f))/((double).837319851f-(double)(-.0717708766f));
        double bottom=-512+1024*(.911292841-(double)(-.0717708766f))/((double).837319851f-(double)(-.0717708766f));
        ART_CHECK(near(MF32(patch+0x1C)-MF32(patch+0x38)/2,left+(right-left)*cut[x]));
        ART_CHECK(near(MF32(patch+0x1C)+MF32(patch+0x38)/2,left+(right-left)*cut[x+1]));
        ART_CHECK(near(MF32(patch+0x20)-MF32(patch+0x3C)/2,top+(bottom-top)*cut[y]));
        ART_CHECK(near(MF32(patch+0x20)+MF32(patch+0x3C)/2,top+(bottom-top)*cut[y+1]));
        ART_CHECK(near(MF32(patch+0x44),cut[x]) && near(MF32(patch+0x4C),cut[x+1]));
        ART_CHECK(near(MF32(patch+0x48),cut[y]) && near(MF32(patch+0x50),cut[y+1]));
        for(unsigned k=0;k<4;++k){
            unsigned cx=x+(k==1 || k==2),cy=y+(k>=2);
            uint32_t color=patch+0x54+16*k;
            ART_CHECK(M32(color)==255 && M32(color+4)==255 && M32(color+8)==255);
            ART_CHECK(M32(color+12)==(cx && cx<3 && cy && cy<3?255u:0u));
        }
        ++draws;
    } else if(fn==0x0055CF50) {
        ART_CHECK(n==1 && a[0]==owner+0xEC); ++drains;
    } else if(fn==0x0055CF30) {
        ART_CHECK(drains==releases+1 && n==2 && M32(a[0])==0x0F365871 && a[1]==1); ++releases;
    } else ART_CHECK(0);
    memset(c,0xBC,sizeof *c); /* The providers must isolate all helper register changes. */
    return 0;
}
void f_00732940(Cpu *c) { ++depth_calls;c->esp+=4; }
void f_005B0920(Cpu *c) {
    ART_CHECK(c->ecx==renderer && M32(c->esp+4)!=0);
    if(M32(c->esp+4)==veil_obj)veil_seen=MF32(veil_t+0x1C);
    ART_CHECK(M32(image+0x24)==0xABCDEF);
    ++originals;c->eax=0x12345;c->ecx=0x98765;c->esp+=8;
}
/* RETAINED_CALLER */
static void retained(Cpu *c) { c->eax=0x12345678;c->ecx=99;c->esp+=8; }
static void destroyed(Cpu *c) {
    ART_CHECK(!carbon_art_owner && !carbon_art_image);c->eax=33;c->esp+=4;
}
static void unrelated_destroyed(Cpu *c) { c->eax=33;c->esp+=4; }
static Cpu entry(uint32_t object) {
    Cpu c={0};c.esp=0xA00000;c.ecx=object;c.eax=123;c.cw=0x37F;
    M32(c.esp)=0xFEED;M32(c.esp+4)=image;return c;
}
int main(int argc,char **argv) {
    ART_CHECK(argc==3 || argc==5);active=atoi(argv[1]);scenario=atoi(argv[2]);
    int parent=argc==5?atoi(argv[3]):0,change=argc==5?atoi(argv[4]):0;
    G=calloc(1,0xB00000);ART_CHECK(G!=NULL);
    M32(owner+0x14)=image;M32(owner+0xC)=7;
    M32(image+0x2C)=t;M32(image+0x58)=cache;
    M32(image+0x24)=0xABCDEF;M32(image+0x1C)=0x11;
    MF32(t+0x44)=1.34545445f;MF32(t+0x48)=-.0717708766f;MF32(t+0x4C)=2.25454521f;MF32(t+0x50)=.837319851f;
    MF32(t+0x38)=MF32(t+0x3C)=1024;
    M16(image+0x20)=parent;MF32(renderer+0x98)=.125f;
    MF32(t+0x24)=.25f;MF32(0xA97C98)=change?0:.25f+parent*.125f;
    Cpu c=entry(owner),expected=c;retained(&expected);
    carbon_worldmap_art_retain(&c,retained);ART_CHECK(!memcmp(&c,&expected,sizeof c));
    ART_CHECK(requests==(unsigned)active);
    c=entry(owner);carbon_worldmap_art_retain(&c,retained);ART_CHECK(requests==(unsigned)active);
    if(scenario==1)resident=0;
    if(scenario==3)M32(image+0x58)=0;
    if(scenario==4)MF32(t+0x4C)=MF32(t+0x44);
    if(scenario==5)MF32(t+0x1C)=NAN;
    if(scenario==6)MF32(t+0x3C)=INFINITY;
    if(scenario==7) {
        c=entry(owner+0x100);carbon_worldmap_art_release(&c,unrelated_destroyed);
        ART_CHECK(drains==0 && releases==0);
        c=entry(owner);carbon_worldmap_art_release(&c,active?destroyed:unrelated_destroyed);
        ART_CHECK(drains==(unsigned)active && releases==(unsigned)active);
        c=entry(owner);carbon_worldmap_art_retain(&c,retained);ART_CHECK(requests==2*(unsigned)active);
    }
    uint8_t saved[0x54];memcpy(saved,G+t,sizeof saved);
    c=entry(renderer);if(scenario==2)M32(c.esp+4)=image+0x100;
    M32(image+0x100+0x2C)=t;
    expected=c;carbon_art_native_caller(&expected);
    unsigned native_depths=depth_calls;depth_calls=0;
    MF32(0xA97C98)=change?0:.25f+parent*.125f;
    c=entry(renderer);if(scenario==2)M32(c.esp+4)=image+0x100;
    carbon_worldmap_art_draw(&c,carbon_art_native_caller);
    ART_CHECK(!memcmp(&c,&expected,sizeof c));
    ART_CHECK(originals==2 && depth_calls==native_depths && depth_calls==(unsigned)change);
    unsigned want=active && (scenario==0 || scenario==7);
    ART_CHECK(draws==9*want);
    ART_CHECK(M32(image+0x2C)==t);
    ART_CHECK(resolves==(unsigned)(active && (scenario==0 || scenario==1 || scenario==7)));
    ART_CHECK(!memcmp(saved,G+t,sizeof saved));
    ART_CHECK(M32(image+0x24)==0xABCDEF && M32(image+0x1C)==(0x11|(want?0x02400000:0)));
    /* Right map-edge veil (mirrored group, local x -137): moved 794 local units for its own draw only. */
    for(unsigned k=0;k<3;++k){
        uint32_t hash=k==0?0x75C4ABD4u:k==1?0xA5CA44F5u:0x321D3B81u; /* solid, fade, left veil untouched */
        unsigned moved=active && k<2;
        M32(veil_obj+0x10)=hash;M32(veil_obj+0x2C)=veil_t;M32(veil_obj+0x1C)=0x40000000;M16(veil_obj+0x20)=0;
        MF32(veil_t+0x1C)=-137;MF32(veil_t+0x24)=MF32(0xA97C98);
        c=entry(renderer);M32(c.esp+4)=veil_obj;expected=c;carbon_art_native_caller(&expected);
        c=entry(renderer);M32(c.esp+4)=veil_obj;carbon_worldmap_art_draw(&c,carbon_art_native_caller);
        ART_CHECK(!memcmp(&c,&expected,sizeof c));
        ART_CHECK(veil_seen==(moved?-931.0f:-137.0f) && MF32(veil_t+0x1C)==-137.0f);
        ART_CHECK(M32(veil_obj+0x1C)==(moved?0x42400000u:0x40000000u));
    }
    ART_CHECK(draws==9*want);
    c=entry(owner);expected=c;expected.eax=33;expected.esp+=4;
    carbon_worldmap_art_release(&c,active?destroyed:unrelated_destroyed);
    ART_CHECK(!memcmp(&c,&expected,sizeof c));
    ART_CHECK(drains==(unsigned)(active?(scenario==7?2:1):0) && releases==drains);
    c=entry(owner);carbon_worldmap_art_release(&c,unrelated_destroyed);ART_CHECK(releases==drains);
    printf("ART PASS checks=%u scenario=%d active=%d draws=%u requests=%u releases=%u\n",checks,scenario,active,draws,requests,releases);
    free(G);return 0;
}
'''


def art_fixture(out, pe):
    import os
    # Retail fade witness: uncompressed FE object/transform, not a generated ramp.
    sys.path.insert(0, str(ROOT/'tools_snapshot'))
    from texture_compare import jdlz_blobs
    game = Path(json.loads((HERE/'out/carbon-base/image.json').read_text())['exe']).parent
    fades = []
    for blob in jdlz_blobs((game/'GLOBAL/InGameB.bun').read_bytes()):
        offset = blob.find(struct.pack('<I', 0xA5CA44F5))
        if offset < 0:
            continue
        assert struct.unpack_from('<I', blob, offset-8)[0] == 9
        assert struct.unpack_from('<I', blob, offset+0x24)[0] == 0  # no image reference
        assert struct.unpack_from('<4I', blob, offset+0x2C) == (0,0,0,255)
        assert struct.unpack_from('<2f', blob, offset+0x64) == (150.,1480.)
        corners = struct.unpack_from('<16I', blob, offset+0x80)
        assert corners == (255,255,255,255,255,255,255,0,255,255,255,0,255,255,255,255)
        fades.append(offset)
    assert len(fades) == 1, 'retail map-edge fade witness'
    text = (HERE/'out/carbon-base/NFSC_20.c').read_text()
    match = re.search(r'void f_005995E0\(Cpu [^)]*\)\s*\{', text)
    native_fade = text[match.start():text.index('\n}',match.end())+2]
    assert hashlib.sha256(native_fade.encode()).hexdigest() == '1ce84ec9664214103d4fc07d4c2b82c35ae58e3ed8194badb7b33d87cf036e33'
    source = (PRIVATE/'carbon_worldmap_art.h').read_text()
    feature = json.loads((PRIVATE/'features/worldmap_art.json').read_text())
    assert feature['bindings']['carbon_worldmap_art.c']['sha256'] == hashlib.sha256(source.encode()).hexdigest()
    hooks = json.loads((PRIVATE/'hooks/worldmap_art.json').read_text())['hooks']
    for row in hooks:
        assert hashlib.sha256(pe.read(int(row['address'],16),16)).hexdigest()==row['witness']['sha256']
    text = (HERE/'out/carbon-base/NFSC_21.c').read_text()
    match = re.search(r'void (?:f_|carbon_orig_)005B0A50\(Cpu [^)]*\)\s*\{',text)
    native = text[match.start():text.index('\n}',match.end())+2]
    normalized = native.replace('carbon_orig_005B0A50(', 'f_005B0A50(', 1)
    assert hashlib.sha256(normalized.encode()).hexdigest() == ART_CALLER_SHA
    native = re.sub(r'void (?:f_|carbon_orig_)005B0A50\(', 'void carbon_art_native_caller(', native, count=1)
    harness = ART_HARNESS.replace('/* RETAINED_CALLER */',native)
    # A pass-through provider is exactly the original missing-draw behavior.
    begin = source.index('void carbon_worldmap_art_draw(')
    old = source[:begin]+'void carbon_worldmap_art_draw(Cpu *c,void (*original)(Cpu *)){original(c);}\n'
    binaries=[]
    # The veil left in place (the original Rockport-rect blackout): shift zero.
    assert source.count('#define CARBON_ART_VEIL_SHIFT (-794.0f)')==1
    unmoved = source.replace('#define CARBON_ART_VEIL_SHIFT (-794.0f)','#define CARBON_ART_VEIL_SHIFT (0.0f)')
    unfaded = source.replace('M32(color + 12) = cx && cx < 3 && cy && cy < 3 ? 255 : 0;', 'M32(color + 12) = 255;')
    assert unfaded != source
    for name,code in (('good',source),('old',old),('unmoved',unmoved),('unfaded',unfaded)):
        path=out/f'art-{name}.c';binary=path.with_suffix('')
        path.write_text(code+harness)
        run(['clang','-O1','-g','-fsanitize=address,undefined','-I',ROOT/'runtime','-I',HERE,path,'-o',binary])
        binaries.append(binary)
    env={k:v for k,v in os.environ.items() if k!='NFS_CARBON_MINIMAP'}
    for case in range(8):
        print(run([binaries[0],1,case],env={**env,'NFS_CARBON_MINIMAP':'atlas'}).stdout.strip())
    for active,mode in ((0,None),(1,'atlas')):
        for parent in (0,1):
            for change in (0,1):
                e=dict(env)
                if mode:e['NFS_CARBON_MINIMAP']=mode
                print(run([binaries[0],active,0,parent,change],env=e).stdout.strip()+f' parent={parent} depth_change={change}')
    for mode in (None,'off','rockport','other'):
        e=dict(env)
        if mode is not None:e['NFS_CARBON_MINIMAP']=mode
        print(run([binaries[0],0,0],env=e).stdout.strip()+' '+str(mode))
    result=run([binaries[1],1,0],expected=1,env={**env,'NFS_CARBON_MINIMAP':'atlas'})
    assert 'draws==9*want' in result.stderr
    print('old art caller rejected: draws=0; fixed=9')
    result=run([binaries[2],1,0],expected=1,env={**env,'NFS_CARBON_MINIMAP':'atlas'})
    assert 'veil_seen==' in result.stderr
    print('unmoved veil rejected: local x -137; fixed -931')
    result=run([binaries[3],1,0],expected=1,env={**env,'NFS_CARBON_MINIMAP':'atlas'})
    assert 'M32(color+12)==' in result.stderr
    print('unfaded art rejected: border alpha 255; fixed 0; nine patch placements checked')


def art_visibility(empty, fixed):
    from PIL import Image
    import numpy as np
    counts=[]
    for path in (empty,fixed):
        image=Image.open(path).convert('RGB')
        assert image.size==(1440,1080), 'world-map proof resolution'
        pixels=np.asarray(image,dtype=np.float64)[72:900,380:1368]
        luma=.2126*pixels[:,:,0]+.7152*pixels[:,:,1]+.0722*pixels[:,:,2]
        counts.append(int(np.count_nonzero(luma>40)))
    assert counts[0]/818064<.10, ('art-off control must stay dark',counts)
    assert counts[1]/818064>.50, ('atlas art share must exceed 50%',counts)
    return {'control':counts[0],'atlas':counts[1],'pixels':818064,
            'control_share':counts[0]/818064,'atlas_share':counts[1]/818064}


def art_edge_metrics(path):
    from PIL import Image
    import numpy as np
    image = Image.open(path).convert('RGB')
    assert image.width == 1440 and image.height >= 1080, 'world-map edge proof resolution'
    pixels = np.asarray(image, dtype=np.float64)[:1080]
    luma = .299*pixels[:,:,0]+.587*pixels[:,:,1]+.114*pixels[:,:,2]
    columns = luma[:880].mean(axis=0)
    return {'band_step': float(np.abs(np.diff(columns[366:383])).max()),
            'seam_row_step': float(np.abs(luma[:880,374]-luma[:880,373]).mean()),
            'left_mean': float(columns[358:366].mean()),
            'right_mean': float(columns[382:390].mean()),
            'art_share': float(np.mean(luma[72:900,380:1368]>40))}


def art_edge_visibility(before, after):
    control, fixed = art_edge_metrics(before), art_edge_metrics(after)
    assert control['band_step'] >= 12, ('hard-edge control', control)
    assert fixed['band_step'] <= 5, ('art edge must ramp', fixed)
    assert fixed['art_share'] >= .75, ('faded art must remain visible', fixed)
    return {'before': control, 'after': fixed}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--generate', nargs=2, type=Path, metavar=('ROCKPORT', 'SHARED'))
    parser.add_argument('--check-log', type=Path)
    parser.add_argument('--check-frame', nargs=2, type=Path, metavar=('EMPTY','FIXED'))
    parser.add_argument('--check-art-edge-frame', nargs=2, type=Path, metavar=('HARD','FADED'))
    parser.add_argument('--check-art-frame', nargs=2, type=Path, metavar=('UNSET','ATLAS'))
    parser.add_argument('--draws', type=Path)
    parser.add_argument('--stock-draws', type=Path)
    parser.add_argument('--mode', choices=('off', 'rockport', 'atlas'), default='rockport')
    parser.add_argument('--mutant', action='store_true')
    args = parser.parse_args()
    if args.generate:
        generate(args.generate); print('MINIMAP TABLE GENERATED from fingerprinted calibration manifests'); return 0
    if args.check_log:
        print(json.dumps(check_log(args.check_log, args.mode, args.mutant))); return 0
    if args.check_art_edge_frame:
        print(json.dumps(art_edge_visibility(*args.check_art_edge_frame)));return 0
    if args.check_art_frame:
        print(json.dumps(art_visibility(*args.check_art_frame)));return 0
    if args.check_frame:
        assert args.draws and args.stock_draws, 'frame check needs both draw captures'
        print(json.dumps(check_frame(*args.check_frame,args.draws,args.stock_draws))); return 0
    image = HERE/'out/carbon-base/image.json'
    if not image.is_file() or not all((HERE/f'out/carbon-base/NFSC_{unit}.c').is_file() for unit in (18,19,21,22,31,33)):
        print('SKIP: private translated witnesses absent'); return 3
    path = Path(json.loads(image.read_text())['exe'])
    if not path.is_file() or not (path.parent/'GLOBAL/InGameB.bun').is_file():
        print('SKIP: private executable or native map fade asset absent'); return 3
    pe = recomp.PE(str(path), expected_sha256=IMAGE_SHA)
    hooks = json.loads((PRIVATE/'hooks/minimap.json').read_text())['hooks']
    assert tuple(int(r['address'], 16) for r in hooks) == tuple(FRAGMENTS)
    for record, (address, digest) in zip(hooks, FRAGMENTS.items()):
        text = fragment(address)
        assert hashlib.sha256(text.encode()).hexdigest() == digest, hex(address)
        assert 'untranslated(c,' not in text
        index = list(FRAGMENTS).index(address)
        provider = 'carbon_minimap_'+PROVIDERS[index] if index < 4 else 'carbon_worldmap_'+WORLD_PROVIDERS[index-4]
        assert record['provider'] == provider
        assert hashlib.sha256(pe.read(address, 16)).hexdigest() == record['witness']['sha256']
        wrapped = private_hooks.wrap(address, text, record)
        assert wrapped.count('carbon_orig_'+format(address,'08X')) == 2
    source = (PRIVATE/'carbon_minimap.h').read_text()
    assert calibration_table(CALIBRATIONS) in source
    feature = json.loads((PRIVATE/'features/minimap.json').read_text())
    assert feature['bindings']['carbon_minimap.c']['sha256'] == hashlib.sha256(source.encode()).hexdigest()
    centre = fragment(0x005E50F0)
    native = centre[centre.index('    /* 005E51E3:'):centre.index('    /* 005E5213:')]
    out = ignored_output(HERE/'out/carbon/minimap_test')
    art_fixture(out, pe)
    edge = art_edge_visibility(ROOT/'run_shots/c2art_on.jpg', ROOT/'run_shots/c2edge_on.jpg')
    print('ART EDGE JPEG '+json.dumps(edge))
    try:
        art_edge_visibility(ROOT/'run_shots/c2art_on.jpg', ROOT/'run_shots/c2art_on.jpg')
    except AssertionError as error:
        assert error.args[0][0] == 'art edge must ramp'
    else:
        raise AssertionError('hard-edge frame accepted as faded art')
    worldmap_fixture(out)
    if not stream_fixture(out):
        print('SKIP: private minimap inputs absent'); return 3
    good, broken, mutant = fixture(out,native), fixture(out,native,broken='restore'), fixture(out,native,mutant=True)
    old = fixture(out,native,broken='stock')
    active_only = fixture(out,native,broken='active_only')
    import os
    env = {k:v for k,v in os.environ.items() if k != 'NFS_CARBON_MINIMAP'}
    for mode, name in enumerate(('off','rockport','atlas')):
        for diag in (0,1):
            result = run([good,mode,diag],env={**env,'NFS_CARBON_MINIMAP':name})
            print(result.stdout.strip())
    print(run([good,0,0],env=env).stdout.strip()+' unset')
    result = run([old,1,0],expected=1,env={**env,'NFS_CARBON_MINIMAP':'rockport'})
    print('old-stock tuple rejected:',result.stderr.splitlines()[0])
    result = run([broken,1,0],expected=1,env={**env,'NFS_CARBON_MINIMAP':'rockport'})
    print('omitted-restore rejected:',result.stderr.splitlines()[0])
    result = run([active_only,2,1],expected=1,env={**env,'NFS_CARBON_MINIMAP':'atlas'})
    print('active-only icon walk rejected:',result.stderr.splitlines()[0])
    result = run([mutant,1,0],env={**env,'NFS_CARBON_MINIMAP':'rockport'})
    print(result.stdout.strip()+' correct-projection rejected; delta_u=-1/16')
    run([good,0,0],expected=2,env={**env,'NFS_CARBON_MINIMAP':'invalid'})
    # Pin the decoded example, including the atlas's physics-Z shift.
    for index, point, expected in ((0,(2912,160),(0.6212168869,0.7370389499,185)),
                                   (1,(11104,160),(0.8767149064,0.6592987932,174))):
        actual = projection(point,CALIBRATIONS[index])
        assert max(abs(actual[i]-expected[i]) for i in (0,1)) < 1e-6 and actual[2] == expected[2]
    print('PRIVATE MINIMAP PASS wrappers=8 native_witnesses=8 projections=2 stock_restore=PASS negative_controls=5 worldmap_art=PASS'); return 0


if __name__ == '__main__':
    sys.exit(main())
