"""Carbon credits consume the native Back edge before package input is enabled.

Gated career and menu close counts: 1 each with the fix, 0 each with retail.
Enabled menu credits close once through the retail callback in both builds.
Exit 3 when the private translated sources are absent.
"""
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import private_hooks
from private_hooks_test import body, command
from recomp import PE

ROOT = Path(__file__).resolve().parent.parent
BASE = ROOT / 'recomp/out/carbon-base'
PROVIDER = ROOT / 'recomp/private_runtime/carbon_credits.c'
FEATURE = ROOT / 'recomp/private_runtime/features/credits.json'
HOOK = ROOT / 'recomp/private_runtime/hooks/credits.json'
TICK = 0x600C90
FRAGMENTS = (
    (21, 0x5A52F0, 'd6caef75bac12a47be8d4b21accd5afd8e02140e20c7c50fb90ab2aed05d8229'),
    (23, 0x5E9E40, '17e1f3c66273e488d54466fb8687b53935553bf4586c96d165f7c3a9f6bae419'),
    (50, 0x8484E0, '0ca9470046d732c1ca6e5086f21e1d600327d8496b2bfa4066b476d70b2158a1'),
    (24, TICK, '89de2e586b96ee6232ce2995c7798d107593a90522f81c61f722073e1e3f334c'),
)

FIXTURE = r'''
#include "host.h"
#include <assert.h>
#include <stdlib.h>

enum {
    ENGINE = 0x1000, PACKAGE = 0x7000, INPUT = 0x7100,
    DEVICE = 0x7300, DEVICE_VTABLE = 0x7310, POLL = 0x101,
    ROOT = 0x7400, CREDITS = 0x7500, NAME = 0x7600, STACK = 0x7900,
    BACK = 0x20
};
static uint8_t memory[0xA97A80];
uint8_t *G = memory;
static unsigned closes, polls, callbacks;
static uint32_t buttons[2];

static void f_0059B1B0(Cpu *c) {
    assert(c->ecx == CREDITS);
    assert(M32(c->ecx + 0x18) == 3 && M32(c->ecx + 0xB4) == ROOT);
    ++closes;
    c->esp += 4;
}

static void f_005EB7E0(Cpu *c) { (void)c; abort(); }
static void f_005F6F90(Cpu *c) { (void)c; abort(); }
static void f_005FCDC0(Cpu *c) { (void)c; abort(); }
static void f_005FCAA0(Cpu *c) { c->esp += 4; }
static void f_006007C0(Cpu *c) { c->esp += 4; }

static void f_005FD770(Cpu *c);
#include "native.inc"

static void f_005FD770(Cpu *c) {
    assert(c->ecx == ENGINE && arg(c, 0) == PACKAGE && M8(PACKAGE + 0x28));
    if (M32(PACKAGE + 0x20) & 1u && (M32(INPUT + 4) & ~M32(INPUT) & BACK)) {
        ++callbacks;
        Cpu back = *c;
        back.ecx = CREDITS;
        f_008484E0(&back);
    }
    c->esp += 8;
}

void dispatch(Cpu *c, uint32_t address) {
    assert(address == POLL && c->ecx == DEVICE && arg(c, 0) < 2);
    ++polls;
    c->eax = buttons[arg(c, 0)];
    c->esp += 8;
}

uint32_t call_guest(Cpu *c, uint32_t address, int count, const uint32_t *args) {
    assert(address == 0x005A52F0 && count == 0 && args == NULL);
    assert(c->esp == STACK + 12);
    c->esp -= 4;
    M32(c->esp) = 0xFEEDF00D;
    f_005A52F0(c);
    assert(c->esp == STACK + 12);
    return c->eax;
}

static void setup(uint32_t mode, int enabled, uint32_t control) {
    memset(memory + ENGINE, 0, STACK + 16 - ENGINE);
    M8(ENGINE) = 1;
    M32(ENGINE + 4) = INPUT;
    M32(ENGINE + 0xD0) = 2;
    M32(ENGINE + 0xE0) = M32(ENGINE + 0xE4) = PACKAGE;
    M32(ENGINE + 0x108) = DEVICE;
    M32(DEVICE) = DEVICE_VTABLE;
    M32(DEVICE_VTABLE + 0x40) = POLL;
    M32(PACKAGE + 0xC) = NAME;
    M32(PACKAGE + 0x20) = control;
    M8(PACKAGE + 0x28) = enabled;
    memcpy(memory + NAME, "Credits.fng", sizeof "Credits.fng");
    M32(0xA97A7C) = ROOT;
    M32(ROOT + 0xB0) = CREDITS;
    M32(CREDITS) = 0x9F9200;
    M32(CREDITS + 4) = mode;
    M32(CREDITS + 0xAC) = ROOT;
    closes = polls = callbacks = buttons[0] = buttons[1] = 0;
}

static void tick(uint32_t slot0, uint32_t slot1) {
    Cpu c = {.ecx = ENGINE, .esp = STACK};
    M32(c.esp) = 0x12345678;
    buttons[0] = slot0;
    buttons[1] = slot1;
    unsigned expected_polls = polls + 2;
    f_00600C90(&c);
    assert(c.esp == STACK + 12 && M32(CREDITS) == 0x9F9200);
    assert(polls == expected_polls);
}

int main(void) {
    setup(1, 0, 1);
    tick(BACK, 0);
    unsigned career_closes = closes;
    assert(callbacks == 0 && M8(PACKAGE + 0x28) == 0);
    M32(CREDITS + 0x18) = 0;
    tick(BACK, 0);
    tick(0, 0);
    assert(closes == career_closes && callbacks == 0);

    setup(1, 1, 1);
    tick(BACK, 0);
    assert(closes == career_closes && callbacks == 1);

    setup(0, 0, 1);
    tick(BACK, 0);
    unsigned menu_closes = closes;
    assert(callbacks == 0 && M8(PACKAGE + 0x28) == 0);
    tick(BACK, 0);
    tick(0, 0);
    assert(closes == menu_closes && callbacks == 0);

    setup(0, 1, 1);
    tick(BACK, 0);
    assert(closes == 1 && callbacks == 1);

    setup(0, 0, 1);
    M8(ENGINE + 0x524C) = 1;
    tick(BACK, 0);
    assert(closes == 0 && callbacks == 0);

    setup(1, 0, 2);
    tick(BACK, 0);
    assert(closes == 0);
    tick(0, BACK);
    assert(closes == career_closes && callbacks == 0);

    setup(1, 0, 1);
    M32(CREDITS + 0x18) = 3;
    tick(BACK, 0);
    assert(closes == 0);

    setup(1, 0, 1);
    memcpy(memory + NAME, "FeDialog.fng", sizeof "FeDialog.fng");
    tick(BACK, 0);
    assert(closes == 0);

    setup(2, 0, 1);
    tick(BACK, 0);
    assert(closes == 0);

    printf("gated career closes=%u; gated menu closes=%u; enabled menu closes=1\n",
           career_closes, menu_closes);
    return career_closes != 1 || menu_closes != 1;
}
'''


def main():
    image_path = BASE / 'image.json'
    if not image_path.is_file():
        return 3
    image = json.loads(image_path.read_text())
    sources = {unit: BASE / f'NFSC_{unit}.c' for unit, _, _ in FRAGMENTS}
    if not all(path.is_file() for path in (*sources.values(), Path(image['exe']))):
        return 3

    native = []
    for unit, address, digest in FRAGMENTS:
        source = sources[unit].read_text()
        name = f'f_{address:08X}'
        original = private_hooks.original_name(address)
        fragment = (body(source, original).replace(original, name, 1)
                    if f'void {original}(' in source else body(source, name))
        assert hashlib.sha256(fragment.encode()).hexdigest() == digest, name
        native.append(fragment)

    pe = PE(image['exe'], expected_sha256=image['sha256'])
    feature = json.loads(FEATURE.read_text())
    assert feature['target'] == 'private' and feature['sources'][PROVIDER.name]['targets'] == ['private']
    assert feature['bindings'][PROVIDER.name]['sha256'] == hashlib.sha256(PROVIDER.read_bytes()).hexdigest()

    with tempfile.TemporaryDirectory(prefix='private-credits-') as directory:
        scratch = Path(directory)
        shutil.copy2(HOOK, scratch)
        hooks = private_hooks.load_registry(pe, [(TICK, TICK + 0x275, 'FE input tick')], scratch)
        assert hooks[TICK]['provider'] == 'carbon_credits_input'
        fixture = scratch / 'fixture.c'
        fixture.write_text(FIXTURE)
        patched = private_hooks.declarations(hooks) + private_hooks.wrap(TICK, native[-1], hooks[TICK])
        for version, handler, closes in [('fixed', patched, 1), ('retail', native[-1], 0)]:
            (scratch / 'native.inc').write_text('\n'.join([*native[:-1], handler]))
            binary = scratch / version
            command(['clang', '-std=c11', '-fsanitize=address,undefined',
                     '-I', ROOT / 'runtime', '-I', ROOT / 'recomp', fixture, PROVIDER,
                     '-o', binary])
            result = command([binary], expected=1 - closes)
            assert result.stdout.strip() == (
                f'gated career closes={closes}; gated menu closes={closes}; enabled menu closes=1'
            )
            print(f'{version} {result.stdout.strip()}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
