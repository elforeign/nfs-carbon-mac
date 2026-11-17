"""Three invisible defects, exercised on retained translated Carbon originals.

K10 retail 0/3 foreign blocks loaded -> repaired 3/3; matching ids byte-identical.
K02 retail 20010.546875 after 600 ticks -> repaired 20010.000000;
    at 600000 retail +0 -> repaired +10; 984000 ticks -> 16400 +/-0.002.
K06 retail 1 null write -> repaired 0, stock type 1 loaded, ride type restored.
Broken variants: omit id repair (loaded 0/3); float accumulator (20010.546875);
omit stand-in substitution (1 null write). Each fails acceptance with exit 1,
as do three deliberately failing retail acceptance runs; good exits 0.
Good failures 0/300; broken save 9/111, clock 5/158, model 2/25.
Exit 3 without the pinned image/build outputs. No emulation, game or device I/O.
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
# SHA-256 of individual original translated functions, normalized definition only.
BASELINES = {
    0x00595F90: 'c902770b2d0341ec075dc2e9d3e2f7ccdb5f00037d254a5659a4e09ed4be9149',
    0x00596220: '1afc282ec62d8422b2aba5ba84fd580aaf18072d7eda65cd8714c91536e5d52d',
    0x00595940: 'f613fe17298a51bdc5ce9b4aee9ccb72b7612526fde779a41dcb1f5e05efc559',
    0x005959D0: '8ead54471ae4653791b32217fe52083be605dbae9b211718f825ed4286a0118e',
    0x005958B0: '6f2aa62518bf0e38c9468b9dc1396702eba10cff3fe0937f7f735622c1913072',
    0x0058E6B0: '6c506296c59b866347255d8fa5e8f17b9c98125944bb1787325695b59bb5f89d',
    0x0076ADA0: '117ccdbfb1188d6451c370f798fa286f9fa619338301e5a6fe7be1707995e030',
    0x007E4A90: '2ada1e24a475faf3c1d0d0c68de7759f2f8a8b6bf78dacaefc9dc663ea1c3712',
}


def run(args, expected=0):
    result = subprocess.run(list(map(str, args)), capture_output=True, text=True)
    assert result.returncode == expected, (args[:3], result.returncode,
                                          result.stdout[-2500:], result.stderr[-3500:])
    return result


def main():
    base = HERE / 'out/carbon-base'
    if not all((base / name).is_file() for name in ('image.json', 'table.c', 'funcs.h', 'NFSC.a')):
        print('SKIP: private fixes fixture needs Carbon build outputs')
        return 3
    image = json.loads((base / 'image.json').read_text())
    if not Path(image['exe']).is_file():
        print('SKIP: private fixes fixture needs its pinned image')
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
    owned = {int(row['address'], 16): row
             for row in json.loads((PRIVATE / 'hooks/fixes1.json').read_text())['hooks']}
    assert set(owned) == {0x595F90, 0x76ADA0, 0x7E4A90}
    assert all(hooks[a]['provider'] == row['provider'] for a, row in owned.items())
    # Independently pin the fault-site bytes, not just provider entry witnesses.
    assert pe.read(0x59606A, 5) == bytes.fromhex('3b 56 10 75 0b')
    assert pe.read(0x76ADF1, 6) == bytes.fromhex('d9 1d d8 cf b4 00')
    assert pe.read(0x7E4ADE, 9) == bytes.fromhex('85 c0 75 05 a3 00 00 00 00')
    native = []
    cache = {}
    for address in (*BASELINES, 0x57F870, 0x57F900, 0x57F970):
        chunk = starts.index(address) // build_all.CHUNK
        if chunk not in cache:
            cache[chunk] = (base / f'NFSC_{chunk:02d}.c').read_text()
        source = cache[chunk]
        name = private_hooks.original_name(address)
        if f'void {name}(' not in source:
            name = f'f_{address:08X}'
        body = private_hooks_test.body(source, name).replace(name, f'f_{address:08X}', 1)
        if address in BASELINES:
            assert hashlib.sha256(body.encode()).hexdigest() == BASELINES[address], hex(address)
        native.append(private_hooks.wrap(address, body, hooks[address]) if address in owned else body)
    feature = json.loads((PRIVATE / 'features/fixes1.json').read_text())
    assert feature['image_sha256'] == IMAGE_SHA
    implementations = {name: (PRIVATE / name).read_text() for name in feature['sources']}
    assert set(implementations) == {'carbon_fix_save.c', 'carbon_fix_clock.c', 'carbon_fix_model.c'}
    for name, source in implementations.items():
        assert feature['bindings'][name]['sha256'] == hashlib.sha256(source.encode()).hexdigest()
    memory = bytearray(0xC00000)
    for _, _, va, raw_size, raw in pe.sections:
        memory[pe.base+va:pe.base+va+raw_size] = pe.data[raw:raw+raw_size]
    variants = {
        'good': None,
        'save': ('carbon_fix_save.c', 'if (!exact && matches == 1)', 'if (0 && !exact && matches == 1)'),
        'clock': ('carbon_fix_clock.c', 'static double carbon_fix_clock_time;', 'static float carbon_fix_clock_time;'),
        'model': ('carbon_fix_model.c', 'M32(ride) = replacement;', '(void)replacement;'),
    }
    with tempfile.TemporaryDirectory(prefix='private-fixes1-') as directory:
        tmp = Path(directory)
        (tmp / 'image.bin').write_bytes(memory)
        (tmp / 'native.inc').write_text('\n\n'.join(native) + '\n')
        (tmp / 'fixture.c').write_bytes((PRIVATE / 'carbon_fix_fixture.h').read_bytes())
        for variant, mutation in variants.items():
            for name, source in implementations.items():
                if mutation and name == mutation[0]:
                    assert source.count(mutation[1]) == 1
                    source = source.replace(mutation[1], mutation[2])
                (tmp / name).write_text(source)
            binary = tmp / variant
            run(['clang', '-O1', '-g', '-DHEAP_TEST', '-DRECOMP_ABICHECK',
                 '-fsanitize=address,undefined', '-I', HERE, '-I', base, '-I', ROOT / 'runtime',
                 tmp / 'fixture.c', ROOT / 'runtime/heap.c', '-o', binary])
            cases = ('save', 'clock', 'model') if variant == 'good' else (variant,)
            for case in cases:
                result = run([binary, tmp / 'image.bin', case], 0 if variant == 'good' else 1)
                print(f'{variant}/{case}: exit={result.returncode}\n{result.stdout.strip()}')
            if variant == 'good':
                for case in ('save', 'clock', 'model'):
                    result = run([binary, tmp / 'image.bin', f'retail-{case}'], 1)
                    print(f'retail/{case}: exit=1\n{result.stdout.strip()}')
    print('PRIVATE FIXES1 PASS: 3 native faults, 3 repairs, 3 rejected broken providers')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
