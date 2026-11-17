"""Carbon crew member picture inside its HUD frame on a wide output, on the retained quad builder.

One number: the picture's centre minus its frame's centre, in pixels of a 3840x2160 output.
Good: 7.4 (the 1.6-unit offset the 4:3 layout has), picture 792 px wide, 20 checks / 0 failures.
Broken control (the unhooked translated builder, as before the fix): 224.3, picture 1056 px wide, exit 1.
A 4:3 output and the mirror's quad keep the native result.
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
BUILD, TO_INT = 0x750B30, 0x87EAC0
# Translated originals: the quad builder and its float-to-integer leaf.
BASELINES = {
    BUILD: 'c0b2098e7f4c7fa8432f24d2ba84eacb5620fb8cabf1bd7e5ea1a2fb89d353b2',
    TO_INT: '8a57fc42130caa60ed8421cb1d5da190a9fe9861da15b652a28973e67a972158',
}
# Image constants the builder reads: 1.0 and 255.0.
CONSTANTS = {0x9C2478: 4, 0x9C92F0: 4}
# The frame, from HUD_SingleRace.fng (GLOBAL/InGameB.bun): MAIN_GROUP (0), group 1603009E
# (x -226.28; its wide script 001EDC08, answer to message 62ED04EC, x -346.28), group
# 157C5B37 (0), PIP_BACKING (8.28), the frame art (1.0); 640x480 units from the centre.
FRAME_43, FRAME_WIDE_SHIFT = 320.0 + (-226.28 + 8.28 + 1.0), -346.28 - -226.28

FIXTURE = r'''
#include "funcs.h"
#include "host.h"
#include <stdlib.h>

uint8_t *G;
int diag_on;
void diag_event(const char *format, ...) { (void)format; }
static float kx;
float carbon_fe_kx(void) { return kx; }
#include "carbon_pipquad.c"

enum { MEMORY = 0xC00000, STACK = 0x200000, QUAD = 0x3000, NATIVE = 0x3100,
       PICTURE = 0x00750DFF, MIRROR = 0x00750D0B };
static unsigned checks, failures;
#define CHECK(x) do { ++checks; if (!(x)) { ++failures; \
    fprintf(stderr, "FAIL line %d: %s\n", __LINE__, #x); } } while (0)

void bad_jump(Cpu *c, uint32_t at) { (void)c; fprintf(stderr, "bad jump %x\n", at); abort(); }
void untranslated(Cpu *c, uint32_t at) { bad_jump(c, at); }
void guest_breakpoint(Cpu *c, uint32_t at) { bad_jump(c, at); }
void host_import(Cpu *c, uint32_t at) { bad_jump(c, at); }
void dispatch(Cpu *c, uint32_t at) { bad_jump(c, at); }   /* the HUD fade query: no HUD object here */
void abi_violation(Cpu *c, uint32_t fn, uint32_t b, uint32_t s, uint32_t d, uint32_t p, uint32_t sp) {
    (void)c; (void)b; (void)s; (void)d; (void)p; (void)sp;
    fprintf(stderr, "ABI %x\n", fn); abort();
}
#include "native.inc"

static void build(uint32_t out, uint32_t caller, float x, float y, float w, float h) {
    Cpu c = {0};
    c.esp = STACK; c.cw = 0x37F;
    c.ebx = 0xBBCC; c.esi = 0xCCDD; c.edi = 0xDDEE; c.ebp = 0xAABB;
    M32(c.esp) = caller; M32(c.esp + 4) = out;
    MF32(c.esp + 8) = x; MF32(c.esp + 12) = y; MF32(c.esp + 16) = w; MF32(c.esp + 20) = h;
    f_00750B30(&c);
    CHECK(c.esp == STACK + 4);
    CHECK(c.ebx == 0xBBCC && c.esi == 0xCCDD && c.edi == 0xDDEE && c.ebp == 0xAABB);
}
/* Left and right edge of a quad in pixels of an output `width` wide. */
static void edges(uint32_t quad, float width, float *left, float *right) {
    *left = 1e9f; *right = -1e9f;
    for (unsigned v = 0; v < 4; ++v) {
        float x = (MF32(quad + v * 0x18) + 1.0f) * 0.5f * width;
        if (x < *left) *left = x;
        if (x > *right) *right = x;
    }
}
/* Everything but the four x values equals the native quad. */
static int rest_native(void) {
    for (unsigned i = 0; i < 24; ++i)
        if (i % 6 && M32(QUAD + 4 * i) != M32(NATIVE + 4 * i)) return 0;
    return 1;
}

int main(void) {
    G = calloc(1, MEMORY); if (!G) abort();
#include "constants.inc"
    float left, right, native_left, native_right;
    /* The crew picture's own arguments (00750DE1..00750DF4) on 3840x2160. */
    kx = 0.75f;
    build(NATIVE, MIRROR, 0.026f, 0.7f, 0.275f, 0.275f);
    edges(NATIVE, 3840, &native_left, &native_right);
    CHECK(native_left > 99.5f && native_left < 100.5f && native_right > 1155.5f && native_right < 1156.5f);
    build(QUAD, PICTURE, 0.026f, 0.7f, 0.275f, 0.275f);
    edges(QUAD, 3840, &left, &right);
    float frame = 1920.0f + (FRAME_43 + FRAME_WIDE_SHIFT - 320.0f) * 6.0f * kx;
    printf("wide picture-frame centre px=%.1f width px=%.1f frame centre px=%.1f\n",
           (left + right) * 0.5f - frame, right - left, frame);
    CHECK((left + right) * 0.5f - frame > 6.5f && (left + right) * 0.5f - frame < 8.5f);
    CHECK(right - left > 791.5f && right - left < 792.5f);
    CHECK(left >= 0.0f);
    CHECK(rest_native());
    /* The mirror's quad (00750CED..00750D00) stays native on the wide output. */
    build(NATIVE, 0, 0.703125f, 0.8146f, -0.40625f, 0.1458f);
    build(QUAD, MIRROR, 0.703125f, 0.8146f, -0.40625f, 0.1458f);
    CHECK(!memcmp(G + QUAD, G + NATIVE, 0x60));
    /* A 4:3 output keeps the native picture. */
    kx = 1.0f;
    build(NATIVE, MIRROR, 0.026f, 0.7f, 0.275f, 0.275f);
    build(QUAD, PICTURE, 0.026f, 0.7f, 0.275f, 0.275f);
    CHECK(!memcmp(G + QUAD, G + NATIVE, 0x60));
    edges(QUAD, 1440, &left, &right);
    float frame43 = FRAME_43 * 1440.0f / 640.0f;
    printf("4:3 picture-frame centre px=%.1f width px=%.1f\n", (left + right) * 0.5f - frame43, right - left);
    CHECK((left + right) * 0.5f - frame43 > 3.0f && (left + right) * 0.5f - frame43 < 4.5f);
    printf("checks=%u failures=%u\n", checks, failures);
    return failures != 0;
}
'''


def run(args, expected=0):
    result = subprocess.run(list(map(str, args)), capture_output=True, text=True, timeout=120)
    assert result.returncode == expected, (args[:3], result.returncode,
                                          result.stdout[-2000:], result.stderr[-3000:])
    return result


def frame_layout(package):
    """The top-left HUD group's 4:3 and wide x, read from the package bytes."""
    data = package.read_bytes()
    at = data.index(bytes.fromhex('4f 68 04 00 9e 00 03 16'))        # object name hash 1603009E
    group = data[at:at + 0x1A0]
    # Message 62ED04EC (wide HUD) is answered with script 001EDC08.
    assert bytes.fromhex('4d 69 04 00 ec 04 ed 62 4d 43 04 00 01 00 00 00 52 69 04 00 00 00 00 00'
                         '52 75 04 00 08 dc 1e 00') in group
    def x_of(script):
        start = group.index(bytes.fromhex('53 68 10 00') + struct.pack('<I', script))
        key = group.index(bytes.fromhex('4b 64 10 00 ff ff ff ff'), start)
        return struct.unpack_from('<f', group, key + 8)[0]
    return x_of(0x001744B3), x_of(0x001EDC08)


def main():
    base = HERE / 'out/carbon-base'
    if not all((base / n).is_file() for n in ('image.json', 'table.c', 'funcs.h')):
        print('SKIP: crew picture fixture needs Carbon build outputs')
        return 3
    image = json.loads((base / 'image.json').read_text())
    package = Path(image['exe']).parent / 'GLOBAL/InGameB.bun'
    if not Path(image['exe']).is_file() or not package.is_file():
        print('SKIP: crew picture fixture needs its pinned image and HUD package')
        return 3
    sys.path.insert(0, str(HERE))
    import build_all
    import private_hooks
    import private_hooks_test
    import recomp

    pe = recomp.PE(image['exe'], expected_sha256=IMAGE_SHA)
    assert image['sha256'] == IMAGE_SHA
    starts = [int(v.strip().removesuffix('u'), 16) for v in re.search(
        r'guest_func_addr\[\] = \{([^}]+)', (base / 'table.c').read_text())[1].split(',')]
    functions = [(a, starts[i+1] if i+1 < len(starts) else a+16, 'fixture')
                 for i, a in enumerate(starts)]
    hooks = private_hooks.load_registry(pe, functions)
    owned = json.loads((PRIVATE / 'hooks/pipquad.json').read_text())['hooks']
    assert [(row['address'], row['provider']) for row in owned] == [('00750B30', 'carbon_pipquad_build')]
    assert hooks[BUILD]['provider'] == 'carbon_pipquad_build'
    feature = json.loads((PRIVATE / 'features/pipquad.json').read_text())
    provider = (PRIVATE / 'carbon_pipquad.c').read_text()
    assert feature['image_sha256'] == IMAGE_SHA and set(feature['sources']) == {'carbon_pipquad.c'}
    assert feature['bindings']['carbon_pipquad.c']['sha256'] == hashlib.sha256(provider.encode()).hexdigest()
    # Machine-byte witnesses, independent of the translation: the crew picture pushes
    # h 0.275, w 0.275, y 0.7, x 0.026 and calls the builder, returning to 00750DFF;
    # the mirror's call returns to 00750D0B.
    assert pe.read(0x750DE1, 30) == bytes.fromhex(
        '68 cd cc 8c 3e 68 cd cc 8c 3e 68 33 33 33 3f 8d 54 24 10 68 f4 fd d4 3c 52 e8 31 fd ff ff')
    assert pe.read(0x750CED, 30) == bytes.fromhex(
        '68 55 55 15 3e 68 00 00 d0 be 68 89 88 50 3f 8d 44 24 10 68 00 00 34 3f 50 e8 25 fe ff ff')
    # The frame's layout numbers, from the HUD package itself.
    normal, wide = frame_layout(package)
    assert abs(normal - -226.28) < 1e-3 and abs(wide - -346.28) < 1e-3, (normal, wide)
    assert abs((wide - normal) - FRAME_WIDE_SHIFT) < 1e-3
    assert '120.0f / 320.0f' in provider
    bodies = {}
    for address in (BUILD, TO_INT):
        source = (base / f'NFSC_{starts.index(address)//build_all.CHUNK:02d}.c').read_text()
        name = f'f_{address:08X}'
        if f'void carbon_orig_{address:08X}(' in source:
            name = f'carbon_orig_{address:08X}'
        body = private_hooks_test.body(source, name).replace(name, f'f_{address:08X}', 1)
        assert hashlib.sha256(body.encode()).hexdigest() == BASELINES[address], hex(address)
        bodies[address] = body
    called = set(re.findall(r'\b(f_[0-9A-F]{8})\(c\)', bodies[BUILD] + bodies[TO_INT]))
    assert called == {'f_0087EAC0'}, sorted(called)
    constants = ''.join(
        f'    memcpy(G + 0x{address:X}u, (const uint8_t[]){{{",".join(map(str, pe.read(address, size)))}}}, {size});\n'
        for address, size in CONSTANTS.items())
    constants += f'#define FRAME_43 {FRAME_43!r}f\n#define FRAME_WIDE_SHIFT ({FRAME_WIDE_SHIFT!r}f)\n'
    declarations = private_hooks.declarations({BUILD: hooks[BUILD]})
    with tempfile.TemporaryDirectory(prefix='private-pipquad-') as directory:
        tmp = Path(directory)
        (tmp / 'carbon_pipquad.c').write_text(provider)
        (tmp / 'constants.inc').write_text(constants)
        (tmp / 'fixture.c').write_text(FIXTURE)
        offset = {}
        for variant, expected in (('good', 0), ('unhooked', 1)):
            builder = private_hooks.wrap(BUILD, bodies[BUILD], hooks[BUILD]) if variant == 'good' else bodies[BUILD]
            (tmp / 'native.inc').write_text(declarations + bodies[TO_INT] + '\n\n' + builder + '\n')
            binary = tmp / variant
            run(['clang', '-O1', '-g', '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                 '-I', tmp, '-I', HERE, '-I', base, '-I', ROOT / 'runtime', tmp / 'fixture.c', '-o', binary])
            result = run([binary], expected)
            offset[variant] = float(re.search(r'^wide picture-frame centre px=(-?[\d.]+)', result.stdout, re.M)[1])
            print(f'{variant}: exit={result.returncode}\n{result.stdout.strip()}\n{result.stderr.strip()}')
        assert 6.5 < offset['good'] < 8.5 and 223.5 < offset['unhooked'] < 225.5, offset
    print(f"PRIVATE PIPQUAD PASS: picture {offset['good']} px from its frame's centre on 3840x2160, "
          f"unhooked builder {offset['unhooked']} px")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
