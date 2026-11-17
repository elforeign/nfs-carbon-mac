"""Oversized Y00 backing through the production CRT and extent allocator.

Good: 141 checks; two reloads share one reservation with zero bad frees, despite >600 MiB
free in resource extents too small for the 180,113,988-byte backing request.
Pinned old malloc path: exit 1 at the fragmented-resource allocation check.
Broken matching free / clearing: exit 1 at the wrong-heap / reload-zero check.
Overlap returning 0 (80e5b20d line 45): exit 1 at check 94 (good: 141); a grow without
the memset: exit 1 at the grown-zero check.
Uses synthetic pool calls, no game assets or emulation.
"""
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = ROOT / 'recomp/private_runtime'
BASELINE = '    if (IS("malloc")) CR(gmalloc(A(0)));'
BASELINE_SHA256 = '55f53c623f6a06d7aad6bc3591297d027b7dbd339ae61a3a8f1f1edd7bc7487a'


def main():
    assert hashlib.sha256(BASELINE.encode()).hexdigest() == BASELINE_SHA256
    crt = (PRIVATE / 'crt.c').read_text()
    backing = (PRIVATE / 'carbon_y00_heap.h').read_text()
    feature = json.loads((PRIVATE / 'features/y00_heap.json').read_text())
    hook = json.loads((PRIVATE / 'hooks/y00_heap.json').read_text())['hooks']
    assert feature['bindings']['carbon_y00_heap.h']['sha256'] == hashlib.sha256(backing.encode()).hexdigest()
    assert feature['sources']['carbon_y00_heap.h']['kind'] == 'include'
    assert len(hook) == 1 and hook[0]['address'] == '00477230' and hook[0]['provider'] == 'carbon_y00_allocate'
    assert hook[0]['witness'] == {
        'start': '00477230', 'length': 23,
        'sha256': '97925324ecc5b2263939f9948afb7413691cc7648611ba378b42956b26c79b48',
    }
    current = '    if (IS("malloc")) CR(carbon_y00_malloc(c,A(0)));'
    clear = '    } else {\n        memset(G + carbon_y00_backing, 0, size);'
    live = 'if (carbon_y00_live) return gmalloc(size);'
    grow = '        memset(G + carbon_y00_backing, 0, size);\n    } else {'
    free = 'if (block && block == carbon_y00_backing) {'
    for fragment, source in ((current, crt), (clear, backing), (free, backing), (live, backing), (grow, backing)):
        assert source.count(fragment) == 1, fragment
    cases = (
        ('good', crt, backing, ''),
        ('old-malloc', crt.replace(current, BASELINE), backing,
         'oversized Y00 entered fragmented resource heap'),
        ('wrong-free', crt, backing.replace(free, 'if (0) {'),
         'free sent process backing to resource heap'),
        ('stale-bytes', crt, backing.replace(clear, '    } else {\n        (void)size;'),
         'reload reuses zeroed backing'),
        ('old-overlap', crt, backing.replace(live, 'if (carbon_y00_live) return 0;'),
         'overlap takes resource heap'),
        ('stale-grow', crt, backing.replace(grow, '    } else {'),
         'grown backing is zeroed'),
    )
    with tempfile.TemporaryDirectory(prefix='private-y00-heap-') as td:
        tmp = Path(td)
        for name, source, policy, failure in cases:
            (tmp / 'crt.c').write_text(source)
            (tmp / 'carbon_y00_heap.h').write_text(policy)
            binary = tmp / name
            result = subprocess.run([
                'clang', '-std=c11', '-O1', '-g', '-DHEAP_TEST',
                '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
                '-I', str(ROOT / 'runtime'), '-I', str(ROOT / 'recomp'),
                str(tmp / 'crt.c'), str(PRIVATE / 'carbon_y00_heap_harness.c'),
                str(ROOT / 'runtime/heap.c'), '-o', str(binary),
            ], capture_output=True, text=True)
            assert result.returncode == 0, result.stderr[-3000:]
            result = subprocess.run([str(binary)], capture_output=True, text=True)
            output = result.stdout + result.stderr
            assert result.returncode == (1 if failure else 0), (name, result.returncode, output[-3000:])
            assert (failure or 'Y00 HEAP PASS') in output, (name, output[-3000:])
            print(name + ': ' + output.strip()[-1000:])
    print('PRIVATE Y00 HEAP PASS: fragmented heap, two reloads, stock/caller/flags controls, old-path/free/clear failures')


if __name__ == '__main__':
    main()
