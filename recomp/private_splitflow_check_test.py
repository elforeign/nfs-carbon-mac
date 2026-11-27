#!/usr/bin/env python3
"""Acceptance parser: positive 8/8, missing P2 finish 4/8, captures 6/8.

Also reject results 5/8, handle growth 6/8 and absent solo 7/8; both finish
orders pass. These are deliberately broken recordings, not game-run claims.
The actual 006449D0 finalizer writes +46=1 with +41=0; the old-byte reader
fails at 3/8. Native owner/stride controls fail at 1/8 and 0/8.
"""
from pathlib import Path
import importlib.util
import hashlib
import json
import re
import sys
import tempfile

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('carbon_splitflow', HERE / 'private_splitflow_check.py')
flow = importlib.util.module_from_spec(spec)
spec.loader.exec_module(flow)

NATIVE_MAIN = r'''
static void finish_racer(uint32_t racer) {
 uint32_t key=M32(racer);M32(racer)=0; /* outside boundary: notify the keyed car */
 Cpu c=cpu();c.ecx=racer;f_006449D0(&c);M32(racer)=key;
 CHECK(M8(racer+0x46)==1&&M8(racer+0x41)==0);
}
int main(void) {
 setup();M32(0xA9FF64)=2;M32(0x205C)=0;M32(0x305C)=1;M32(0xB4D854)=1;
 M32(0x306A08)=2;M32(0x300018+0x4C)=0;M32(0x15008)=124;M32(0x1500C)=0x6000;M32(0xAA26BC)=2;
 uint32_t second=0x300018+0x384;M32(second)=124;
 M32(0x604C)=0xC100;M32(0xC130)=0xE100;M32(0xE100)=0xF100;
 MF32(0xF020)=0;carbon_autodrive_splitflow(now);
 M32(0x1000)=0x3044;M32(0x1004)=0x2044; /* native list order is not controller order */
 MF32(0xF020)=20;MF32(0xF120)=25;now+=1000000000ull;carbon_autodrive_splitflow(now);
 M32(0x300018+0x4C)=2;finish_racer(0x300018);now+=1000000000ull;carbon_autodrive_splitflow(now);
 M32(second+0x4C)=2;finish_racer(second);now+=1000000000ull;carbon_autodrive_splitflow(now);
 printf("NATIVE READY finished=%d unknown=%d\n",carbon_autodrive_split_ready("finished"),carbon_autodrive_split_ready("unknown"));
 M32(0xA97A78)=0x11000;M32(0x11000)=0x12000;M32(0x120E4)=0x13000;
 M32(0x13020)=1;M32(0x1300C)=0x14000;strcpy(gptr(0x14000),"FePostRaceResults.fng");
 now+=1000000000ull;carbon_autodrive_splitflow(now);
 M32(0xA99BBC)=3;M32(0xA9FF64)=0;test_split=0;test_captures=0;
 strcpy(gptr(0x14000),"FeQuickRaceOptions.fng");now+=1000000000ull;carbon_autodrive_splitflow(now);
 M32(0xA99BBC)=6;M32(0xA9FF64)=1;M32(0xB4D854)=0;M32(0x1000)=0x2044;
 strcpy(gptr(0x14000),"HUD_SingleRace.fng");now+=1000000000ull;carbon_autodrive_splitflow(now);
 printf("NATIVE READY solo=%d finished=%d\n",carbon_autodrive_split_ready("solo"),carbon_autodrive_split_ready("finished"));
 free(G);return 0;
}
'''


def native_controls(tmp):
    """Run the production observer on the same witnessed native layout as AI tests."""
    sys.path.insert(0, str(HERE))
    import private_autodrive_test as ai
    import private_hooks_test
    base = HERE / 'out/carbon-base'
    if not (base / 'image.json').is_file():
        print('SKIP: native split observer needs Carbon translated output')
        return False
    image = json.loads((base / 'image.json').read_text())
    if not Path(image['exe']).is_file():
        print('SKIP: native split observer needs the private image')
        return False
    assert image['sha256'] == ai.IMAGE_SHA
    starts = [int(v.strip().removesuffix('u'), 16) for v in re.search(
        r'guest_func_addr\[\] = \{([^}]+)', (base / 'table.c').read_text())[1].split(',')]
    native = []
    for address, digest in ai.BASELINES.items():
        source = (base / f'NFSC_{starts.index(address)//800:02d}.c').read_text()
        body = private_hooks_test.body(source, f'f_{address:08X}')
        assert hashlib.sha256(body.encode()).hexdigest() == digest
        native.append(body)
    finish = private_hooks_test.body((base / 'NFSC_27.c').read_text(), 'f_006449D0')
    assert hashlib.sha256(finish.encode()).hexdigest() == '1fedddc773c8c4fc4fe3b53606883512b7c29a53ca782e4fd03774133b15d0f4'
    native.append(finish)
    supplied = set(ai.BASELINES) | {0x6449D0}
    for callee in sorted(set(re.findall(r'\b(f_[0-9A-F]{8})\(c\)', finish))):
        address = int(callee[2:], 16)
        if address not in supplied:
            native.append(f'void {callee}(Cpu *c){{bad_jump(c,0x{address:08X}u);}}')
    (tmp / 'native.inc').write_text('\n\n'.join(native))
    fixture = 'static unsigned test_split=1,test_captures=24;\n' + ai.HARNESS
    fixture = fixture.replace('int main(void) {', 'int legacy_main(void) {') + NATIVE_MAIN
    fixture = fixture.replace('int pad_count(void) {return 1;}', 'int pad_count(void) {return 2;}')
    fixture = fixture.replace('(void)v;(void)r;return 0;', '(void)v;(void)r;return test_split;')
    fixture = fixture.replace('carbon_spliteffects_resources(void) {return 0;}',
                              'carbon_spliteffects_resources(void) {return test_captures;}')
    fixture = fixture.replace('va_end(ap);', 'va_end(ap);if(strstr(line,"carbon splitflow:"))puts(line);')
    implementation = (ai.PRIVATE / 'carbon_autodrive.h').read_text()
    for name, text, source, accepted, passed in (
        ('native-good', fixture, implementation, True, 8),
        ('native-missing-p2-finish', fixture.replace('finish_racer(second);', '/* P2 finish omitted */'), implementation, False, 4),
        ('native-original-finish-byte', fixture, implementation.replace('M8(info + 0x46)', 'M8(info + 0x41)'), False, 3),
        ('native-wrong-owner', fixture, implementation.replace('M32(player + 0x18) : 2', 'i : 2'), False, 1),
        ('native-wrong-stride', fixture, implementation.replace('0x384*r', '0x194*r'), False, 0),
    ):
        (tmp / 'fixture.c').write_text(text)
        (tmp / 'carbon_autodrive.h').write_text(source)
        binary = tmp / name
        ai.run(['clang', '-O1', '-g', '-DRECOMP_ABICHECK', '-fsanitize=address,undefined',
                '-I', tmp, '-I', HERE, '-I', ai.PRIVATE, '-I', base, '-I', HERE.parent / 'runtime',
                tmp / 'fixture.c', '-o', binary])
        result = ai.run([binary])
        if name == 'native-good':
            assert 'NATIVE READY finished=1 unknown=0' in result.stdout
            assert 'NATIVE READY solo=1 finished=0' in result.stdout
        log = tmp / (name + '.log')
        log.write_text(result.stdout)
        output = []
        assert flow.check(log, output.append) is accepted, (name, output, result.stdout)
        assert sum(line.startswith('PASS ') for line in output) == passed, (name, output)
        print(f'{name}: {passed}/8 accepted={int(accepted)}')
    return True


def recording(winner=1):
    lines = []

    def snapshot(phase, done=(), velocity=20):
        solo = phase == 'solo'
        menu = phase == 'menu'
        lines.append(f'carbon splitflow: flow={3 if menu else 6} state=3 mode={0 if menu or solo else 1} '
                     f'locals={0 if menu else 1 if solo else 2} views={0 if menu or solo else 2} '
                     f'captures={0 if menu or solo else 24} handles=12 race=00300000 '
                     f'package={"FePostRaceResults.fng" if phase == "results" else "FeQuickRaceOptions.fng" if menu else "HUD_Player1.fng"}')
        for p in range(1, 1 if menu else 2 if solo else 3):
            lines.append(f'carbon splitflow: player={p} sim={0x5000 + p*0x1000:08X} '
                         f'racer={0x300018 + p*0x384:08X} finished={int(p in done)} velocity={velocity} lap={3 if p in done else 1}')

    snapshot('split', velocity=0)
    snapshot('split')
    snapshot('split', (winner,))
    snapshot('split', (1, 2))
    snapshot('results', (1, 2))
    snapshot('menu')
    snapshot('solo')
    return '\n'.join(lines) + '\n'


def main():
    with tempfile.TemporaryDirectory(prefix='carbon-splitflow-') as td:
        p = Path(td) / 'events.log'

        def run(name, text, expected, reached):
            p.write_text(text)
            output = []
            assert flow.check(p, output.append) is expected, (name, output)
            passes = sum(line.startswith('PASS ') for line in output)
            assert passes == reached, (name, output)
            print(f'{name}: {passes}/8 accepted={int(expected)}')

        good = recording()
        run('good-p1-first', good, True, 8)
        run('good-p2-first', recording(2), True, 8)
        missing = good.replace('player=2 sim=00007000 racer=00300720 finished=1',
                               'player=2 sim=00007000 racer=00300720 finished=0')
        run('no-p2-finish', missing, False, 4)
        dnf = '\n'.join(line.replace('lap=3', 'lap=1') if 'player=2' in line else line for line in good.splitlines())
        run('p2-incomplete-laps', dnf, False, 4)
        run('later-race-cannot-supply-finish', missing + good, False, 4)
        run('no-results', good.replace('FePostRaceResults.fng', 'HUD_Player1.fng'), False, 5)
        run('leaked-captures', good.replace('captures=0', 'captures=24'), False, 6)
        run('leaked-handles', good.replace('views=0 captures=0 handles=12', 'views=0 captures=0 handles=13'), False, 6)
        run('no-solo', good.rsplit('carbon splitflow: flow=6 state=3 mode=0', 1)[0], False, 7)
        run('no-motion', good.replace('velocity=20', 'velocity=0'), False, 1)
        run('nonfinite-motion', good.replace('velocity=20', 'velocity=inf'), False, 1)
        run('script-only', 'scripted pad2:1 down\nscripted RETURN down\n', False, 0)
        if not native_controls(Path(td)):
            return 3
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
