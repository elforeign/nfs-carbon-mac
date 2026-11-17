"""Movie-start and culling diagnostic proof on a pinned translated original.

Retail delayed audio: 0 connections / 1 poll; acceptance exits 1 (1/5 failures).
No wait repair: two startup runs have audio at every native decision point.
Movie controls: 33 checks / 0 failures; counters: 12 / 0, 2 hidden groups / 11.
Wrong-poll-site mutant: 1/11 failures; omitted-hidden total: 1/12; both exit 1.
Exit 3 without the Carbon image/build. No emulation, game or device I/O.
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
IMAGE_SHA = 'baaaaec33873d4ba7e4dbae6a5212049ffdcf9679a35d865d7625b4189952fd3'
BASELINE = 'f7ce690eb862310e571568b46ddf61a61287634893da542638e7a9318659d36f'


def run(args, expected=0):
    result = subprocess.run(list(map(str, args)), capture_output=True, text=True)
    assert result.returncode == expected, (args[:3], result.returncode,
                                          result.stdout[-2500:], result.stderr[-3500:])
    return result


def main():
    base = HERE / 'out/carbon-base'
    if not all((base / n).is_file() for n in ('image.json', 'funcs.h', 'NFSC.a')):
        print('SKIP: movie fixture needs Carbon build outputs')
        return 3
    image = json.loads((base / 'image.json').read_text())
    if not Path(image['exe']).is_file():
        print('SKIP: movie fixture needs its pinned image')
        return 3
    sys.path.insert(0, str(HERE))
    import private_hooks
    import private_hooks_test
    import recomp

    pe = recomp.PE(image['exe'], expected_sha256=IMAGE_SHA)
    assert image['sha256'] == IMAGE_SHA
    assert pe.read(0x888908, 19) == bytes.fromhex(
        '8b 8e 80 01 00 00 3b cb 74 51 e8 89 b3 04 00 85 c0 7e 48')
    rows = json.loads((PRIVATE / 'hooks/fixes2.json').read_text())['hooks']
    owned = {int(r['address'], 16): r for r in rows}
    assert set(owned) == {0x8887F3, 0x8D3CA0, 0x7BDB60}
    for address, row in owned.items():
        assert row['image_sha256'] == IMAGE_SHA
        w = row['witness']
        assert hashlib.sha256(pe.read(int(w['start'], 16), w['length'])).hexdigest() == w['sha256']
    address = 0x8887F3
    source = (base / 'NFSC_53.c').read_text()
    name = private_hooks.original_name(address)
    if f'void {name}(' not in source:
        name = f'f_{address:08X}'
    body = private_hooks_test.body(source, name).replace(name, f'f_{address:08X}', 1)
    assert hashlib.sha256(body.encode()).hexdigest() == BASELINE
    native = private_hooks.wrap(address, body, owned[address])
    feature = json.loads((PRIVATE / 'features/fixes2.json').read_text())
    assert feature['image_sha256'] == IMAGE_SHA
    implementations = {n: (PRIVATE / n).read_text() for n in feature['sources']}
    assert set(implementations) == {'carbon_fix_movie.c', 'carbon_fix_checks.h'}
    for name, source in implementations.items():
        assert feature['bindings'][name]['sha256'] == hashlib.sha256(source.encode()).hexdigest()
    variants = {
        'good': None,
        'poll': ('carbon_fix_checks.h', 'caller == 0x00888917u', 'caller == 0x00888918u'),
        'cull': ('carbon_fix_checks.h', '++hidden;', '(void)hidden;'),
    }
    with tempfile.TemporaryDirectory(prefix='private-fixes2-') as directory:
        tmp = Path(directory)
        (tmp / 'native.inc').write_text(native + '\n')
        (tmp / 'fixture.c').write_bytes((PRIVATE / 'carbon_fix_movie_fixture.h').read_bytes())
        for variant, mutation in variants.items():
            for name, source in implementations.items():
                if mutation and name == mutation[0]:
                    assert source.count(mutation[1]) == 1
                    source = source.replace(mutation[1], mutation[2])
                (tmp / name).write_text(source)
            binary = tmp / variant
            run(['clang', '-O1', '-g', '-DRECOMP_ABICHECK', '-fsanitize=address,undefined',
                 '-I', HERE, '-I', base, '-I', ROOT / 'runtime', tmp / 'fixture.c', '-o', binary])
            cases = ('movie', 'counts', 'retail') if variant == 'good' else ('counts',)
            for case in cases:
                expected = 1 if variant != 'good' or case == 'retail' else 0
                result = run([binary, case], expected)
                print(f'{variant}/{case}: exit={result.returncode}\n{result.stdout.strip()}')
    print('PRIVATE FIXES2 PASS: pinned retail failure, identity control, rejected broken diagnostics')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
