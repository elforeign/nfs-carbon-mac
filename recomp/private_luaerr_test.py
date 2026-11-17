"""Carbon Lua protected-error fixture on retained translated originals.

Retail control must exit 1 at PRIVATE STUB msvcr71.dll!longjmp.
Return-only provider must fail the depth-2 ancestor throw (exit 1).
Good: 428956 checks / 0 failures, 60 status/SEH cases, 10000 throw cycles,
0 exits. Retail: 1 throw / 1 stub exit. Return-only: 5 failures / 27 checks,
1 incorrectly returned throw / 0 host unwinds. Normal call is byte-identical.
No emulation, game, devices or sockets. Exit 3 without private build inputs.
"""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
PRIVATE = HERE / 'private_runtime'
IMAGE_SHA = 'baaaaec33873d4ba7e4dbae6a5212049ffdcf9679a35d865d7625b4189952fd3'
BASELINES = {
    0x64DAB0: '224c7d364aca9b68b4d3b9a1bd5760b62cfbdb632e2b4a89d2fed228d2516072',
    0x64DAF0: '0e71d8ecaf9a3a6a2ebc0c56888367fd5d17c72f4921cb04c6478f1c80310f75',
    0x87EF70: '81b5d19810a10f1078625bc742867de427cb0ab59f5ced997cee5ca86aff46af',
}
SAVE_SHA = 'f51084ddc94cfa258b3beebaec10e61c7ae68af6741b28ceb537a8cfa8973fb0'


def run(args, expected=0):
    result = subprocess.run(list(map(str, args)), capture_output=True, text=True, timeout=60)
    assert result.returncode == expected, (args[:3], result.returncode,
                                          result.stdout[-2000:], result.stderr[-3000:])
    return result


def main():
    base = HERE / 'out/carbon-base'
    if not all((base / n).is_file() for n in ('image.json', 'table.c', 'funcs.h')):
        print('SKIP: Lua fixture needs Carbon build outputs')
        return 3
    image = json.loads((base / 'image.json').read_text())
    if not Path(image['exe']).is_file():
        print('SKIP: Lua fixture needs its pinned image')
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
    native = []
    functions = [(a, starts[i+1] if i+1 < len(starts) else a+16, 'fixture')
                 for i, a in enumerate(starts)]
    hooks = private_hooks.load_registry(pe, functions)
    owned = json.loads((PRIVATE / 'hooks/luaerr.json').read_text())['hooks']
    assert {int(row['address'], 16) for row in owned} == {0x64DAB0, 0x64DAF0}
    for row in owned:
        assert hooks[int(row['address'], 16)]['provider'] == row['provider']
    counts = {key: 0 for key in ('throw', 'catch', 'setjmp', 'longjmp')}
    for path in base.glob('NFSC_*.c'):
        source = path.read_text()
        for key, text in [('throw', 'f_0064DAB0(c)'), ('catch', 'f_0064DAF0(c)'),
                          ('setjmp', 'f_0087EF70(c)'),
                          ('longjmp', '/* msvcr71.dll!longjmp */')]:
            counts[key] += source.count(text)
    assert counts == dict(throw=21, catch=5, setjmp=1, longjmp=1), counts
    print('image callers/sites: ' + str(counts))
    for address in (0x64DAB0, 0x64DAF0, 0x87EF70):
        source = (base / f'NFSC_{starts.index(address)//build_all.CHUNK:02d}.c').read_text()
        name = f'f_{address:08X}'
        if f'void carbon_orig_{address:08X}(' in source:
            name = f'carbon_orig_{address:08X}'
        body = private_hooks_test.body(source, name).replace(name, f'f_{address:08X}', 1)
        digest = hashlib.sha256(body.encode()).hexdigest()
        assert digest == BASELINES[address], hex(address)
        native.append(private_hooks.wrap(address, body, hooks[address])
                      if address in (0x64DAB0, 0x64DAF0) else body)
    # Use the production CRT save implementation, without unrelated CRT services.
    crt = (PRIVATE / 'crt.c').read_text()
    save = crt[crt.index('    if (IS("_setjmp3")) {'):crt.index('    if (IS("_findfirst")')]
    assert hashlib.sha256(save.encode()).hexdigest() == SAVE_SHA
    bridge = '#define IS(n) (!strcmp(fn,n))\n#define A(n) arg(c,n)\n#define CR(v) RET(v,0)\n'
    bridge += 'static int fixture_crt(Cpu *c,const char *fn) {\n' + save + 'return 0;\n}\n'
    feature = json.loads((PRIVATE / 'features/luaerr.json').read_text())
    assert feature['image_sha256'] == IMAGE_SHA
    assert set(feature['sources']) == {'carbon_lua_unwind.c'}
    provider = (PRIVATE / 'carbon_lua_unwind.c').read_text()
    assert feature['bindings']['carbon_lua_unwind.c']['sha256'] == hashlib.sha256(provider.encode()).hexdigest()
    # Independent machine-byte witness for the entire error continuation.
    assert pe.read(0x64DB18, 7) == bytes.fromhex('83 c4 08 85 c0 75 1c')
    assert pe.read(0x64DB3B, 17) == bytes.fromhex('8b 45 08 8b 4d b8 89 48 50 8b 45 fc 5e 8b e5 5d c3')
    with tempfile.TemporaryDirectory(prefix='private-luaerr-') as directory:
        tmp = Path(directory)
        (tmp / 'native.inc').write_text('\n\n'.join(native) + '\n')
        (tmp / 'crt.inc').write_text(bridge)
        (tmp / 'fixture.c').write_bytes((PRIVATE / 'carbon_lua_fixture.h').read_bytes())
        for variant in ('good', 'return-only'):
            source = provider
            if variant == 'return-only':
                needle = '_longjmp(frame->environment, 1);'
                assert source.count(needle) == 1
                source = source.replace(needle, 'return;')
            (tmp / 'carbon_lua_unwind.c').write_text(source)
            binary = tmp / variant
            run(['clang', '-O1', '-g', '-DRECOMP_ABICHECK', '-fsanitize=address,undefined',
                 '-fno-sanitize-recover=all', '-I', HERE, '-I', base, '-I', ROOT / 'runtime',
                 tmp / 'fixture.c', '-o', binary])
            cases = [('good', 0), ('retail', 1), ('panic', 7), ('unowned', 1), ('other-cpu', 1)] \
                if variant == 'good' else [('depth2', 1)]
            for case, expected in cases:
                result = run([binary, case], expected)
                if case in ('retail', 'unowned', 'other-cpu'):
                    assert 'PRIVATE STUB msvcr71.dll!longjmp' in result.stderr, result.stderr
                if case == 'panic':
                    assert 'PANIC original exit(1)' in result.stderr, result.stderr
                if variant == 'return-only':
                    assert 'throw returned' in result.stderr, result.stderr
                print(f'{variant}/{case}: exit={result.returncode}\n{result.stdout.strip()}\n{result.stderr.strip()}')
    print('PRIVATE LUAERR PASS: nested statuses, 10000 cycles, byte identity, panic and rejected controls')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
