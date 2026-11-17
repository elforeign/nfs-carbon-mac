"""Carbon sampling, shared recipes and output safety with synthetic guest memory.

Good: 2,492 checks, 0 failures; motor/gas/brake/shift=12/10/10/2, real=0/0.
Wrong-image offsets / stale generation / swapped roles: 3 failures each.
Fake bypass: 2 failures, gas/brake/shift=0/0/0; missing private fence:
2 failures, desired motors 12 -> 0. Every broken binary exits 1, good exits 0.
Both compiler-expanded transports have 0 first-game reads or constructors.
Queued fake-controller sink: 25 checks / 22 writes, real opens/writes 0/0;
stale queued epoch / late stop / discarded restoration debt fail 2/1/3 checks.
Global fake bypass traps 1 forbidden open versus the good path's 0.
Live fake gas/brake: 10,098/10,098; unset control: 0/0; real output 0/0.
Live shift is unproven: the default bindings do not request its recipe.
Every device entry point is intercepted; even NFS_RUMBLE=on cannot open hardware.
The recipe oracle compiles the actual address-free functions from padfx.m.
Missing private transport selection must fail the desired-motor check.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = ROOT / 'recomp/private_runtime'
RUNTIME = ROOT / 'runtime'
sys.path.insert(0, str(PRIVATE))
from layers import audit_unit, check_audits, load_manifest


def run(args, **kwargs):
    result = subprocess.run(list(map(str, args)), capture_output=True, text=True, **kwargs)
    if result.returncode:
        raise AssertionError(f'{args[0]} exit {result.returncode}: {result.stdout[-2000:]} {result.stderr[-3000:]}')
    return result


def function(text, name):
    match = re.search(r'^(?:static )?[^\n{};]+\b' + name + r'\([^;{}]*\)\s*\{', text, re.M)
    assert match, name
    end, depth = match.end(), 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[match.start():end]


def main():
    source = (PRIVATE / 'carbon_padfx.c').read_text()
    # Native setters independently witness the two image-specific offsets.
    base = ROOT / 'recomp/out/carbon-base'
    if not all((base / n).is_file() for n in ('NFSC_40.c', 'NFSC_41.c')):
        print('SKIP: private pad effects require translated image outputs')
        return 3
    setter = function((base / 'NFSC_40.c').read_text(), 'f_0075DB30')
    charge = function((base / 'NFSC_41.c').read_text(), 'f_00761D80')
    assert 'c->esi + 0x78u' in setter or 'c->ecx + 0x78u' in setter
    assert '0x7Cu' in charge
    manifest = load_manifest()
    feature = json.loads((PRIVATE / 'features/padfx.json').read_text())
    for name, binding in feature['bindings'].items():
        assert binding['sha256'] == hashlib.sha256((PRIVATE / name).read_bytes()).hexdigest()
    with tempfile.TemporaryDirectory(prefix='private-padfx-', dir=ROOT / 'recomp/out') as td:
        tmp = Path(td)
        for name in ('padlink.c', 'rumble.m'):
            shutil.copy2(RUNTIME / name, tmp / name)
        for path in PRIVATE.glob('carbon_padfx*'):
            shutil.copy2(path, tmp / path.name)
        framework = (RUNTIME / 'padfx_test_support.h').read_text().split('#define dispatch_async test_async', 1)[0]
        (tmp / 'fake_framework.inc').write_text(framework)
        names = ('q20', 'trig', 'vibration', 'pedal_spring', 'trigger_for')
        oracle = '\n'.join(function((RUNTIME / 'padfx.m').read_text(), name) for name in names)
        for name in names:
            oracle = re.sub(r'\b' + name + r'\b', 'oracle_' + name, oracle)
        oracle = oracle.replace('static Trig oracle_trigger_for', 'Trig oracle_trigger_for')
        (tmp / 'oracle.m').write_text('#include <math.h>\n#include "host.h"\n#include "carbon_padfx.h"\n' + oracle)
        flags = ['clang', '-O1', '-g', '-fobjc-arc', '-fblocks', '-DNFS_GAME=2',
                 '-fsanitize=address,undefined', '-I', tmp, '-I', RUNTIME, '-I', ROOT / 'recomp',
                 '-I', PRIVATE]
        run([*flags, '-c', tmp / 'oracle.m', '-o', tmp / 'oracle.o'])
        original_rumble = (RUNTIME / 'rumble.m').read_text()
        original_output = (PRIVATE / 'carbon_padfx_output.h').read_text()
        original_backend = (PRIVATE / 'carbon_padfx_backend.h').read_text()
        def execute(label, sampler=source, rumble=original_rumble, output=original_output,
                    backend=original_backend, queue=False):
            (tmp / 'carbon_padfx.c').write_text(sampler)
            (tmp / 'rumble.m').write_text(rumble)
            (tmp / 'carbon_padfx_output.h').write_text(output)
            (tmp / 'carbon_padfx_backend.h').write_text(backend)
            run([*flags, '-x', 'objective-c', tmp / 'carbon_padfx_fixture.h',
                 '-x', 'none', tmp / 'oracle.o', '-framework', 'Foundation', '-framework', 'IOKit',
                 '-lz', '-o', tmp / label])
            result = subprocess.run([tmp / label, *(['queue'] if queue else [])], text=True, capture_output=True,
                                    env=dict(os.environ, NFS_PADFX_FAKE='0' if queue else '1',
                                             NFS_PAD_TRIGGERS='on' if queue else 'off',
                                             NFS_PAD_ROAD='on' if queue else 'off'))
            assert result.returncode == (0 if label == 'good' else 1), (label, result.stdout, result.stderr[-3000:])
            assert ('PADFX PASS' if label == 'good' else 'FAIL') in result.stdout + result.stderr
            if label == 'fake-discovery-bypass':
                assert 'FAIL forbidden open=1' in result.stderr
            print(label + ': ' + (result.stdout.strip() or result.stderr.strip().splitlines()[0]))
        execute('good')
        result = run([tmp / 'good', 'queue'],
                     env=dict(os.environ, NFS_PADFX_FAKE='0', NFS_PAD_TRIGGERS='on', NFS_PAD_ROAD='on'))
        assert 'QUEUE PASS' in result.stdout
        print('real-sink fake-controller: ' + result.stdout.strip())
        execute('wrong-image-offsets', source.replace('player + 0x78', 'player + 0x80').replace('player + 0x7C', 'player + 0x84'))
        execute('stale-generation', source.replace('token == fx_generation && !fx_holds', '1 && !fx_holds'))
        execute('swapped-roles', source.replace('carbon_padfx_role(0); frame.role[1] = carbon_padfx_role(1)',
                                               'carbon_padfx_role(1); frame.role[1] = carbon_padfx_role(0)'))
        execute('fake-bypass', output=original_output.replace('if (carbon_padfx_fake()) {', 'if (0) {'))
        execute('fake-discovery-bypass', backend=original_backend.replace(
            'fx_fake = value && !strcmp(value, "1");', 'fx_fake = 0; (void)value;'))
        # A missing private selector restores the original motor path, which
        # ignores desired reports when physical rumble is disabled.
        fake_branch = '#if NFS_GAME == NFS_GAME_PRIVATE\n    if (carbon_padfx_fake()) {\n'
        assert original_rumble.count(fake_branch) == 1
        execute('missing-private-fence', rumble=original_rumble.replace(fake_branch,
                         '#if NFS_GAME == NFS_GAME_MW\n    if (carbon_padfx_fake()) {\n'))
        execute('queue-stale-epoch', sampler=source.replace('token != fx_generation ||', '0 ||'), queue=True)
        execute('queue-late-stop', output=original_output.replace('if (fx_applied_generation < token)', 'if (1)'), queue=True)
        execute('queue-lost-restoration', output=original_output.replace('[fx_debt addObject:ctl];', '(void)ctl;'), queue=True)
        # Audit the real two selected expanded units, including their includes.
        (tmp / 'carbon_padfx.c').write_text(source)
        (tmp / 'rumble.m').write_text(original_rumble)
        (tmp / 'carbon_padfx_output.h').write_text(original_output)
        audit_flags = ['-DNFS_GAME=2', '-fobjc-arc', '-I', str(tmp), '-I', str(RUNTIME), '-I', str(ROOT / 'recomp'), '-I', str(PRIVATE)]
        audits = [audit_unit(tmp / name, audit_flags, [(0x401000, 0xA79000)])
                  for name in ('padlink.c', 'rumble.m')]
        check_audits(audits, manifest)
        reads = sum(access == 'read' for unit in audits for row in unit['declarations'] for access, _ in row['accesses'])
        assert reads == 0, reads
        print('expanded shared transports: 2 units, 0 MW reads, 0 forbidden constructors')
    print('PRIVATE PADFX PASS mutants=9')
    return 0


if __name__ == '__main__':
    sys.exit(main())
