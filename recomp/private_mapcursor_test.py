"""Carbon world map cursor ring and direction on retained translated steps.

Direction premise: 0058F770 consumes events 41..44 (FRONTENDACTION_UP/DOWN/
LEFT/RIGHT, the image's enum at A61A90). The PC input-map collection 82D21520
binds these to FE_ACTION_UP/DOWN/LEFT/RIGHT. The port binds up to the low half
of left DI lY (padbind menu action 31); lY=0 is up, 32767.5 centre, 65535 down.
Steering left uses low lX; menus use the same low-lY up convention. Right-stick
events are 45..48 and are ignored by this step. 006A0060 at 005C8EF7 reads
the interpolated map centre (map+70 then +80/+AC), not a physical stick.
The retail PC menu default uses keyboard Up/POV up (A61C88 + 52*31);
the existing port menu bindings add the left-stick low-lY alias to that action.

Retail PC itself reverses both directions when 204*dt + 2*zoom - 2 is negative:
at far zoom 0.39 and 240 Hz, up dy=+0.370000 (down). Fixed dy=-0.545000 (up).
Good: 2390 checks / 0 failures. Unhooked input control: 2390 / 58, exit 1.
The fix scales the entire native 60 Hz step by dt*60, preserving its 60 Hz speed.
X360 822E5CC0 uses 240*dt + 2*zoom - 2; 822E5DD8..5DE4 negates UP into Y.
Its caller 822E5F1C passes that delta on; 822E622C adds it to cursor Y.
At the console's 30/60 Hz this moves up (far-zoom dy=-6.78/-2.78). That version
also has the unscaled zoom bias; its ordinary frame rate keeps the factor positive.
Decoded XEX image SHA: 41167e1fc7401925b9612d69438b19583e5aa57b962df45386beee8f532becf6.

One number: the cursor group's hidden bit after 005C8C70 with the pointer off the map
and the controller as the last input. Good: 0 (ring drawn), 37 checks / 0 failures.
Broken control (the unhooked translated step, as before the fix): 1, exit 1 (3 failures).
Keyboard and mouse keep the native result (1 off the map, 0 on it); mode 2, which
hides the cursor on entry, stays hidden for the controller too.
No emulation, game, devices or sockets. Exit 3 without private build inputs.
"""
import hashlib
import json
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
STEP, IN_RECT = 0x5C8C70, 0x570D60
INPUT = 0x58F770
# Translated originals: the mouse step and its leaf point-in-rectangle test.
BASELINES = {
    STEP: '9769cc5aa713f40b75e7dce6c39475830c45f018c36b53cb1e376a3d8d743310',
    IN_RECT: 'bb76ee676ce2eb38ca1ed033816b78389b2abd3334e6a93dee2d5634fbe13a83',
}
STICK_BASELINES = {
    0x67A340: 'bb02451d80340a7a1b619cab3e2ae8d5179e018313ea31fec43517197383a406',
    INPUT: '02925fdf7f37777102be6ed24e70f4e7c536c0fa04d36989c8da7f9d5c62db2a',
    0x5C8E90: '35cccc43b0d9f01d81b9baf74172b7b998c13f0386f9c363b60525961c390a3f',
    0x5B7940: 'b7c949b50df3d3f6eb8099fa1134871d77ff8070874ef3c7aa2a4e5d01991011',
    0x680310: '52b2f874703d4aa65ef82e035d4da5ee93edb837556a4162e29df066f0d0f4c0',
    0x680320: 'b5576b5ba5feb6a6b0c666387677cbf473e1de5f9993255a66310e0490cd682b',
    0x680350: 'c6ffe92400c89287e5c32b07fa03a069e623e63a294ef9b0c80d70f30b7494e2',
    0x6A0060: '28d0db74aa71724a0ea1d4f91e3fe125aa18d1301f948e92b800140083653b91',
    0x46F9A0: '8ed25b5655aac4876cc6b08afbb863b6f12f112541be2c4c6f4b05e9c44cc3a4',
    0x56EC30: '302ff79197d6745156e029f7dfe8bede4855d90204f4b05b88887ba6bad97259',
    0x56DF80: '7090fc07ef86693242946f215897337b44a8dc6cdf21f90a5e7dbb917b8188d6',
}
CALLEES = {'f_00471280', 'f_00572350', 'f_005C3330', 'f_005AECE0', 'f_00597A70'}
# Image constants the two bodies read: screen centre X and Y (floats), rectangle margin (double).
CONSTANTS = {0x9C778C: 4, 0x9C7784: 4, 0x9C2DF8: 8}

STICK_FIXTURE = r'''
#include "funcs.h"
#include "host.h"
#include <stdlib.h>
uint8_t *G;
int diag_on;
void diag_event(const char *format, ...) { (void)format; }
int prompts_last_input(void) { return 1; }
#include "carbon_mapcursor.c"
enum { MEMORY=0xC00000, STACK=0x200000, MAP=0x3000, CURSOR=0x4000,
       QUEUE=0x5000, SMOOTHER=0x6000 };
static unsigned checks, failures, moves;
#define CHECK(x) do { ++checks; if (!(x)) { ++failures; \
    fprintf(stderr,"FAIL line %d: %s\n",__LINE__,#x); } } while(0)
#define CLOSE(a,b) CHECK(fabsf((a)-(b)) < 0.0001f)
void bad_jump(Cpu *c,uint32_t at) { (void)c; fprintf(stderr,"unexpected %x\n",at); abort(); }
void untranslated(Cpu *c,uint32_t at) { bad_jump(c,at); }
void guest_breakpoint(Cpu *c,uint32_t at) { bad_jump(c,at); }
void host_import(Cpu *c,uint32_t at) { bad_jump(c,at); }
void dispatch(Cpu *c,uint32_t at) {
    /* Joystick GetState boundary: native evaluator reads the actual cached
     * DirectInput axis values from EAX, as the game's +4 vmethod returns them. */
    if(at!=0x1234)bad_jump(c,at);c->eax=0xB000;c->esp+=4;
}
void abi_violation(Cpu *c,uint32_t fn,uint32_t b,uint32_t s,uint32_t d,uint32_t p,uint32_t sp) {
    (void)b;(void)s;(void)d;(void)p;(void)sp;bad_jump(c,fn);
}
/* FE object boundaries only; input queue, vector comparison, clamping and the
 * complete map movement/arithmetic below execute their retained translations. */
void f_00597900(Cpu *c) {
    uint32_t object=arg(c,0);
    MF32(arg(c,1))=object==CURSOR ? MF32(CURSOR+0x100) : 0;
    MF32(arg(c,2))=object==CURSOR ? MF32(CURSOR+0x104) : 0;
    c->esp+=4;
}
void f_00597330(Cpu *c) { MF32(arg(c,1))=MF32(arg(c,2))=0;c->esp+=4; }
void f_00597A70(Cpu *c) {
    CHECK(arg(c,0)==CURSOR);++moves;
    M32(CURSOR+0x100)=arg(c,1);M32(CURSOR+0x104)=arg(c,2);c->esp+=4;
}
void f_005ACA90(Cpu *c) {
    MF32(arg(c,0))=MF32(arg(c,1))/1000;
    MF32(arg(c,0)+4)=MF32(arg(c,1)+4)/1000;c->esp+=12;
}
void f_0069FFE0(Cpu *c) { bad_jump(c,0x69FFE0); }
void f_005C3330(Cpu *c) { c->eax=0;c->esp+=4; }
void f_005AECE0(Cpu *c) { c->esp+=4; }
void f_0056CF70(Cpu *c) { bad_jump(c,0x56CF70); }
void f_0059DE60(Cpu *c) { bad_jump(c,0x59DE60); }
void f_005AF350(Cpu *c) { bad_jump(c,0x5AF350); }
void f_005EC760(Cpu *c) { bad_jump(c,0x5EC760); }
void f_005F3610(Cpu *c) { bad_jump(c,0x5F3610); }
#include "native.inc"

static void setup(float dt,unsigned zoom,unsigned mode) {
    memset(G+MAP,0,0x800);memset(G+SMOOTHER,0,0x114);
    MF32(0xA99A5C)=dt;M32(MAP+0x28)=CURSOR;M32(MAP+0x2C)=QUEUE;
    M32(MAP+0x70)=SMOOTHER;M32(MAP+0x80)=zoom;M32(MAP+0x94)=mode;
    MF32(MAP+0x4C)=MF32(MAP+0x50)=1000;
    MF32(MAP+0x54)=MF32(MAP+0x58)=-10000;
    MF32(MAP+0x5C)=MF32(MAP+0x60)=10000;
    MF32(SMOOTHER+0x80)=MF32(SMOOTHER+0xAC)=0.5f;
    MF32(SMOOTHER+0x28)=MF32(SMOOTHER+0x54)=1;
    MF32(CURSOR+0x100)=MF32(CURSOR+0x104)=0;moves=0;
    memset(G+QUEUE,0,0x29C);M32(QUEUE+12)=50;
}
static void event(unsigned slot,unsigned code,float value) {
    M32(QUEUE+16+12*slot)=code;MF32(QUEUE+24+12*slot)=value;
}
static void invoke(int movement) {
    Cpu c={0};c.esp=STACK;c.cw=0x37F;c.ecx=MAP;
    c.ebx=0xBBCC;c.esi=0xCCDD;c.edi=0xDDEE;c.ebp=0xAABB;
    M32(c.esp)=0xFEED;M32(c.esp+4)=0;
    uint32_t dt=M32(0xA99A5C);
    if(movement)f_005C8E90(&c);else f_0058F770(&c);
    CHECK(c.esp==STACK+(movement?8:4));
    CHECK(c.ebx==0xBBCC&&c.esi==0xCCDD&&c.edi==0xDDEE&&c.ebp==0xAABB);
    CHECK(c.top==0);CHECK(M32(0xA99A5C)==dt);CHECK(M32(QUEUE)==0);
}
static float move(unsigned direction,float dt,unsigned zoom,unsigned mode) {
    setup(dt,zoom,mode);M32(QUEUE)=1;event(0,direction,1);invoke(1);
    return MF32(CURSOR+0x104);
}
static float physical_axis(unsigned type,unsigned object,int32_t value) {
    M32(0xA986D0)=0x9000;M32(0x9000)=0xA000;M32(0xA004)=0x1234;
    M32(0xA98704+8*31)=0x7000;
    M32(0x7018)=type;M32(0x7020)=object;
    M32(0xB000+4*object)=(uint32_t)value;
    Cpu c={0};c.esp=STACK;c.cw=0x37F;M32(STACK)=0xFEED;
    M32(STACK+4)=31;M32(STACK+8)=2;f_0067A340(&c);
    CHECK(c.esp==STACK+12);return (float)c.st[c.top];
}
int main(void) {
    G=calloc(1,MEMORY);if(!G)abort();
#include "constants.inc"
    float pressure=physical_axis(4,1,0);
    CLOSE(pressure,1);CLOSE(physical_axis(4,1,65535),0);
    CLOSE(physical_axis(5,1,65535),1);CLOSE(physical_axis(5,1,0),0);
    CLOSE(physical_axis(4,0,0),1); /* steering/menu left shares the low-X sign */
    printf("DirectInput up lY=0 pressure=%.6f; down lY=65535\n",pressure);
    setup(1.0f/240,0,1);M32(QUEUE)=1;event(0,41,pressure);invoke(1);
    float up=MF32(CURSOR+0x104);
    printf("left-stick/up 240Hz dy=%.6f\n",up);CLOSE(up,-0.545f);
    /* Up/down and left/right at all native zoom levels, at normal and fast
     * rates. A zero time step must not move either axis. */
    const float rates[]={30,60,120,240,360};
    for(unsigned z=0;z<3;++z)for(unsigned r=0;r<5;++r)for(unsigned d=41;d<=44;++d) {
        float zoom=z==1?1.1f:z==2?0.68f:0.39f;
        float speed=(3.4f+2*zoom-2)*60/rates[r];
        move(d,1/rates[r],z,1);
        CLOSE(MF32(CURSOR+0x100),d==43?-speed:d==44?speed:0);
        CLOSE(MF32(CURSOR+0x104),d==41?-speed:d==42?speed:0);
    }
    for(unsigned d=41;d<=44;++d) {move(d,0,0,1);CLOSE(MF32(CURSOR+0x100),0);CLOSE(MF32(CURSOR+0x104),0);}
    move(41,1.0f/240,0,0);CLOSE(MF32(CURSOR+0x104),-0.545f);
    /* Right stick is a different event family, ignored by this cursor path. */
    for(unsigned d=45;d<=48;++d) {move(d,1.0f/240,0,1);CLOSE(MF32(CURSOR+0x104),0);CLOSE(MF32(CURSOR+0x100),0);}
    setup(1.0f/240,0,1);M32(QUEUE)=2;M32(QUEUE+8)=49;
    event(49,41,1);event(0,44,0.5f);invoke(1);
    CLOSE(MF32(CURSOR+0x104),-0.545f);CLOSE(MF32(CURSOR+0x100),0.2725f);
    /* Preserve axes absent from the queue, and fields outside browsing modes. */
    setup(1.0f/240,0,1);MF32(MAP+0x30)=7;M32(QUEUE)=1;event(0,41,1);invoke(0);
    CLOSE(MF32(MAP+0x30),7);CLOSE(MF32(MAP+0x34),-0.545f);
    setup(1.0f/240,0,1);MF32(MAP+0x30)=7;MF32(MAP+0x34)=-9;invoke(0);
    CLOSE(MF32(MAP+0x30),7);CLOSE(MF32(MAP+0x34),-9);
    setup(1.0f/240,0,2);MF32(MAP+0x34)=-9;M32(QUEUE)=1;event(0,41,1);invoke(0);
    CLOSE(MF32(MAP+0x34),-9);
    /* Equal one-second travel at 60 and 240 Hz (no edge or pan). */
    float travel[2];
    for(unsigned r=0;r<2;++r) {
        unsigned hz=r?240:60;setup(1.0f/hz,0,1);
        for(unsigned i=0;i<hz;++i) {M32(QUEUE)=1;M32(QUEUE+8)=0;event(0,41,1);invoke(1);}
        travel[r]=MF32(CURSOR+0x104);
    }
    printf("one-second up 60Hz=%.6f 240Hz=%.6f\n",travel[0],travel[1]);
    CHECK(fabsf(travel[0]+130.8f)<0.002f);CHECK(fabsf(travel[1]-travel[0])<0.002f);
    printf("stick checks=%u failures=%u\n",checks,failures);return failures!=0;
}
'''

FIXTURE = r'''
#include "funcs.h"
#include "host.h"
#include <stdlib.h>

uint8_t *G;
int diag_on;
void diag_event(const char *format, ...) { (void)format; }
static int last_input;
int prompts_last_input(void) { return last_input; }
#include "carbon_mapcursor.c"

enum { MEMORY = 0xC00000, STACK = 0x200000, MAP = 0x3000, CURSOR = 0x4000, PACKAGE = 0x5000,
       HOLDER = 0x6000, MANAGER = 0x6100, NODE = 0x7000, FLAGS = 0x40020000 };
static unsigned checks, failures, moves;
static float moved_x, moved_y;
#define CHECK(x) do { ++checks; if (!(x)) { ++failures; \
    fprintf(stderr, "FAIL line %d: %s\n", __LINE__, #x); } } while (0)

void bad_jump(Cpu *c, uint32_t at) { (void)c; fprintf(stderr, "bad jump %x\n", at); abort(); }
void untranslated(Cpu *c, uint32_t at) { bad_jump(c, at); }
void guest_breakpoint(Cpu *c, uint32_t at) { bad_jump(c, at); }
void host_import(Cpu *c, uint32_t at) { bad_jump(c, at); }
void abi_violation(Cpu *c, uint32_t fn, uint32_t b, uint32_t s, uint32_t d, uint32_t p, uint32_t sp) {
    (void)c; (void)b; (void)s; (void)d; (void)p; (void)sp;
    fprintf(stderr, "ABI %x\n", fn); abort();
}
/* Callees outside the decision: package compare (cdecl), package-loaded query (one
 * stack argument, callee pops), icon snap, layout refresh, object move (cdecl). */
void f_00471280(Cpu *c) { c->eax = arg(c, 0) != arg(c, 1); c->esp += 4; }
void f_00572350(Cpu *c) { c->eax = 0; c->esp += 8; }
void f_005C3330(Cpu *c) { c->eax = 0; c->esp += 4; }
void f_005AECE0(Cpu *c) { c->esp += 4; }
void f_00597A70(Cpu *c) {
    ++moves; memcpy(&moved_x, G+c->esp+8, 4); memcpy(&moved_y, G+c->esp+12, 4); c->esp += 4;
}
#include "native.inc"

static unsigned step_in(int input, int mouse_x, int mouse_y, uint32_t cursor,
                        uint32_t mode, uint32_t top, uint32_t before) {
    memset(G + MAP, 0, 0x800);
    M32(0xA97A78) = HOLDER; M32(HOLDER) = MANAGER;
    M32(MANAGER + 0xD8 + 0xC) = NODE; M32(NODE + 0x20) = 1; M32(NODE + 0xC) = top;
    M32(MAP + 0xC) = PACKAGE; M32(MAP + 0x28) = cursor; M32(MAP + 0x94) = mode;
    MF32(MAP + 0x54) = -300; MF32(MAP + 0x58) = -200; MF32(MAP + 0x5C) = 300; MF32(MAP + 0x60) = 200;
    M32(0xB1F638) = (uint32_t)mouse_x; M32(0xB1F63C) = (uint32_t)mouse_y;
    M8(0xA97B38) = 0xEE; M32(CURSOR + 0x1C) = before; moves = 0; last_input = input;
    Cpu c = {0};
    c.esp = STACK; c.cw = 0x37F; c.ecx = MAP;
    c.ebx = 0xBBCC; c.esi = 0xCCDD; c.edi = 0xDDEE; c.ebp = 0xAABB;
    M32(c.esp) = 0xFEED;
    f_005C8C70(&c);
    CHECK(c.esp == STACK + 4);
    CHECK(c.ebx == 0xBBCC && c.esi == 0xCCDD && c.edi == 0xDDEE && c.ebp == 0xAABB);
    return M32(CURSOR + 0x1C);
}
static unsigned step(int input, int mouse_x, int mouse_y, uint32_t cursor) {
    return step_in(input, mouse_x, mouse_y, cursor, 1, PACKAGE, FLAGS);
}

int main(void) {
    G = calloc(1, MEMORY); if (!G) abort();
#include "constants.inc"
    unsigned flags = step(1, 0, 0, CURSOR);
    printf("controller/off-map hidden=%u\n", flags & 1);
    CHECK(!(flags & 1)); CHECK(flags == (FLAGS | 0x02400000u)); CHECK(M8(0xA97B38) == 0);
    flags = step(0, 0, 0, CURSOR);
    printf("keyboard/off-map hidden=%u\n", flags & 1);
    CHECK(flags == (FLAGS | 0x02400001u)); CHECK(M8(0xA97B38) == 0);
    flags = step(-1, 0, 0, CURSOR);
    CHECK(flags == (FLAGS | 0x02400001u));
    flags = step(1, 330, 250, CURSOR);
    printf("controller/on-map hidden=%u\n", flags & 1);
    CHECK(flags == (FLAGS | 0x02400000u)); CHECK(M8(0xA97B38) == 1); CHECK(moves == 1);
    CHECK(moved_x == 330-MF32(0x9C778C) && moved_y == 250-MF32(0x9C7784));
    flags = step(0, 330, 250, CURSOR);
    CHECK(flags == (FLAGS | 0x02400000u)); CHECK(moves == 1);
    CHECK(moved_x == 330-MF32(0x9C778C) && moved_y == 250-MF32(0x9C7784));
    flags = step(1, 0, 0, 0);
    CHECK(flags == FLAGS); CHECK(M8(0xA97B38) == 0);
    /* Mode 2 hid the cursor on entry: the controller leaves it hidden. */
    flags = step_in(1, 0, 0, CURSOR, 2, PACKAGE, FLAGS | 0x02400001u);
    printf("controller/mode-2 hidden=%u\n", flags & 1);
    CHECK(flags == (FLAGS | 0x02400001u));
    /* Hidden earlier by the mouse, another package now on top (the native step
     * returns early): browsing with the controller shows the ring again. */
    flags = step_in(1, 0, 0, CURSOR, 1, PACKAGE + 0x100, FLAGS | 0x02400001u);
    CHECK(flags == (FLAGS | 0x02400000u)); CHECK(M8(0xA97B38) == 0);
    flags = step_in(0, 0, 0, CURSOR, 1, PACKAGE + 0x100, FLAGS | 0x02400001u);
    CHECK(flags == (FLAGS | 0x02400001u));
    printf("checks=%u failures=%u\n", checks, failures);
    return failures != 0;
}
'''


def run(args, expected=0):
    result = subprocess.run(list(map(str, args)), capture_output=True, text=True, timeout=120)
    assert result.returncode == expected, (args[:3], result.returncode,
                                          result.stdout[-2000:], result.stderr[-3000:])
    return result


def main():
    base = HERE / 'out/carbon-base'
    if not all((base / n).is_file() for n in ('image.json', 'table.c', 'funcs.h')):
        print('SKIP: map cursor fixture needs Carbon build outputs')
        return 3
    image = json.loads((base / 'image.json').read_text())
    if not Path(image['exe']).is_file():
        print('SKIP: map cursor fixture needs its pinned image')
        return 3
    sys.path.insert(0, str(HERE))
    import build_all
    import private_hooks
    import private_hooks_test
    import recomp

    pe = recomp.PE(image['exe'], expected_sha256=IMAGE_SHA)
    assert image['sha256'] == IMAGE_SHA
    pc_attributes = ROOT.parent / 'inputs/NFSC/GLOBAL/attributes.bin'
    if not pc_attributes.is_file():
        print('SKIP: map cursor input bindings need PC attributes')
        return 3
    from private_padbind_test import ControllerVault
    sys.path.insert(0, str(ROOT / 'tools_snapshot/vaults'))
    from vaultlib import hash32
    vault = ControllerVault(pc_attributes)
    pc_up = struct.unpack('<13I', pe.read(0xA61C88 + 52*31, 52))
    assert pc_up[1:4] == (1, 200, 0) and pc_up[7:10] == (3, 0, 0)
    for event, direction in enumerate(('UP', 'DOWN', 'LEFT', 'RIGHT', 'RUP', 'RDOWN', 'RLEFT', 'RRIGHT'), 41):
        code, pointer = struct.unpack('<II', pe.read(0xA61948 + event*8, 8))
        name = pe.read(pointer, 80).split(b'\0')[0].decode()
        assert (code, name) == (event, 'FRONTENDACTION_' + direction)
        records = vault.records(0x82D21520, hash32(name))
        assert len(records) == 1 and struct.unpack_from('<I', records[0][1])[0] == hash32('FE_ACTION_' + direction)
    # These are the controller families actually installed by the existing
    # private menu evaluator; neither swaps UP and DOWN for the map.
    ps_menu = (PRIVATE / 'carbon_padbind_ps3.inc').read_text().split('static const PadAction menu[] = {')[1]
    xbox_menu = (PRIVATE / 'carbon_padbind_x360.inc').read_text().split('static const XboxAction xbox_menu[] = {')[1]
    assert re.search(r'\{31,\s*\{3,0\},\s*\{4,1\}', ps_menu)
    assert re.search(r'\{31,\{\{3,0,[^}]+\},\{4,1,', xbox_menu)
    starts = [int(v.strip().removesuffix('u'), 16) for v in re.search(
        r'guest_func_addr\[\] = \{([^}]+)', (base / 'table.c').read_text())[1].split(',')]
    functions = [(a, starts[i+1] if i+1 < len(starts) else a+16, 'fixture')
                 for i, a in enumerate(starts)]
    hooks = private_hooks.load_registry(pe, functions)
    owned = json.loads((PRIVATE / 'hooks/mapcursor.json').read_text())['hooks']
    assert {(row['address'], row['provider']) for row in owned} == {
        ('005C8C70', 'carbon_mapcursor_mouse'), ('0058F770', 'carbon_mapcursor_input')}
    assert hooks[STEP]['provider'] == 'carbon_mapcursor_mouse'
    assert hooks[INPUT]['provider'] == 'carbon_mapcursor_input'
    feature = json.loads((PRIVATE / 'features/mapcursor.json').read_text())
    provider = (PRIVATE / 'carbon_mapcursor.c').read_text()
    assert feature['image_sha256'] == IMAGE_SHA and set(feature['sources']) == {'carbon_mapcursor.c'}
    assert feature['bindings']['carbon_mapcursor.c']['sha256'] == hashlib.sha256(provider.encode()).hexdigest()
    # Machine-byte witnesses, independent of the translation: the map keeps FE object
    # F156F6C5 at +28; the step shows it over the map and hides it off the map.
    assert pe.read(0x5CD7C0, 5) == bytes.fromhex('68 c5 f6 56 f1')
    assert pe.read(0x5CD7D2, 3) == bytes.fromhex('89 46 28')
    assert pe.read(0x5C8DCC, 15) == bytes.fromhex('8b 50 1c 83 e2 fe 81 ca 00 00 40 02 89 50 1c')
    assert pe.read(0x5C8E75, 3) == bytes.fromhex('8b 76 28')
    assert pe.read(0x5C8E7C, 7) == bytes.fromhex('81 4e 1c 01 00 40 02')
    # The step decides by pointer only in modes 1 and 0; mode 2's entry hides the cursor itself.
    assert pe.read(0x5C8D0B, 15) == bytes.fromhex('8b 86 94 00 00 00 83 f8 01 74 20 3b c3 74 1c')
    assert pe.read(0x5CDBFF, 10) == bytes.fromhex('c7 86 94 00 00 00 02 00 00 00')
    assert pe.read(0x5CDC0B, 7) == bytes.fromhex('81 48 1c 01 00 40 02')
    bodies = {}
    for address, digest in (BASELINES | STICK_BASELINES).items():
        source = (base / f'NFSC_{starts.index(address)//build_all.CHUNK:02d}.c').read_text()
        name = f'f_{address:08X}'
        if f'void carbon_orig_{address:08X}(' in source:
            name = f'carbon_orig_{address:08X}'
        body = private_hooks_test.body(source, name).replace(name, f'f_{address:08X}', 1)
        assert hashlib.sha256(body.encode()).hexdigest() == digest, hex(address)
        bodies[address] = body
    called = set(re.findall(r'\b(f_[0-9A-F]{8})\(c\)', bodies[STEP] + bodies[IN_RECT]))
    assert called == CALLEES | {'f_00570D60'}, sorted(called)
    constants = ''.join(
        f'    memcpy(G + 0x{address:X}u, (const uint8_t[]){{{",".join(map(str, pe.read(address, size)))}}}, {size});\n'
        for address, size in CONSTANTS.items())
    declarations = private_hooks.declarations({STEP: hooks[STEP]})
    with tempfile.TemporaryDirectory(prefix='private-mapcursor-') as directory:
        tmp = Path(directory)
        (tmp / 'carbon_mapcursor.c').write_text(provider)
        (tmp / 'constants.inc').write_text(constants)
        (tmp / 'fixture.c').write_text(FIXTURE)
        hidden = {}
        for variant, expected in (('good', 0), ('unhooked', 1)):
            step = private_hooks.wrap(STEP, bodies[STEP], hooks[STEP]) if variant == 'good' else bodies[STEP]
            (tmp / 'native.inc').write_text(declarations + bodies[IN_RECT] + '\n\n' + step + '\n')
            binary = tmp / variant
            run(['clang', '-O1', '-g', '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                 '-I', tmp, '-I', HERE, '-I', base, '-I', ROOT / 'runtime', tmp / 'fixture.c', '-o', binary])
            result = run([binary], expected)
            hidden[variant] = int(re.search(r'^controller/off-map hidden=(\d)$', result.stdout, re.M)[1])
            print(f'{variant}: exit={result.returncode}\n{result.stdout.strip()}\n{result.stderr.strip()}')
        assert hidden == {'good': 0, 'unhooked': 1}, hidden
        # Global constants read by the pinned stick bodies, copied from the image.
        # Mutable input/time/FE memory is initialized by the fixture itself.
        reads = set()
        for body in (bodies[a] for a in STICK_BASELINES):
            for kind, address in re.findall(r'(M8|M16|M32|MF32|MF64)\(\(uint32_t\)\(0x([0-9A-F]+)u\)\)', body):
                if int(address, 16) < 0xA00000:
                    reads.add((int(address, 16), {'M8':1, 'M16':2, 'M32':4, 'MF32':4, 'MF64':8}[kind]))
        (tmp / 'constants.inc').write_text(''.join(
            f'    memcpy(G + 0x{address:X}u, (const uint8_t[]){{{",".join(map(str, pe.read(address, size)))}}}, {size});\n'
            for address, size in sorted(reads)))
        (tmp / 'fixture.c').write_text(STICK_FIXTURE)
        directions = {}
        for variant, expected in (('fixed', 0), ('input-unhooked', 1)):
            native = private_hooks.declarations({INPUT: hooks[INPUT]})
            for address in STICK_BASELINES:
                body = bodies[address]
                if address == INPUT and variant == 'fixed':
                    body = private_hooks.wrap(address, body, hooks[INPUT])
                native += body + '\n\n'
            (tmp / 'native.inc').write_text(native)
            binary = tmp / variant
            run(['clang', '-O1', '-g', '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                 '-I', tmp, '-I', HERE, '-I', base, '-I', ROOT / 'runtime', tmp / 'fixture.c', '-o', binary])
            result = run([binary], expected)
            directions[variant] = float(re.search(r'^left-stick/up 240Hz dy=([-0-9.]+)$', result.stdout, re.M)[1])
            summary = re.search(r'^stick checks=\d+ failures=\d+$', result.stdout, re.M)[0]
            print(f'{variant}: exit={result.returncode}\n{result.stdout.strip()}')
            if expected:
                print(f'broken control rejected: {summary}')
            else:
                assert not result.stderr, result.stderr[-1500:]
        assert directions == {'fixed': -0.545, 'input-unhooked': 0.37}, directions
    print('PRIVATE MAPCURSOR PASS: ring hidden=0 vs 1; stick up dy=-0.545 vs +0.370 at 240 Hz')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
