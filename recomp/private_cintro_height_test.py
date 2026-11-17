"""Carbon pre-race intro camera height fallback (hook 004809C0), offline part.

Check: minimum (camera z - road z) over the diag lines "cintro:" of a run, where camera z = point z +
(height used - origin height) and road z is the far-above probe. Retail miss (height used = origin height)
puts the camera below the road; the fix puts it above. Numbers here come from the log lines of a real
Quick Race intro (Main Street hits): fixed +0.45 m. The same lines with the retail query forced to miss
(height used = origin height): -1.97 m (synthetic: Main Street's road lies below the grid, so a real run
cannot give a negative margin). In-game forced miss (test-only build shrinking the 4 m probe ceiling to
-1 m, so every height query misses): fix off 38 of 65 queries miss, none recovered, the intro frame is
dark (mean luma 8); fix on 132 of 132 miss and all recovered, final = road on every line, camera margin
>= +0.499 m, intro lit (luma 58). Evidence: run_shots/carbon-cintro-before-after.jpg. Exit 3 without the Carbon image.
"""
import hashlib
import json
from pathlib import Path
import re
import sys

HERE = Path(__file__).resolve().parent
PRIVATE = HERE / 'private_runtime'
IMAGE_SHA = 'baaaaec33873d4ba7e4dbae6a5212049ffdcf9679a35d865d7625b4189952fd3'
LINES = (
    'f22433 t1 cintro: ra=0048b738 z=44.977 retail=46.946 final=46.946 miss=0 recovered=0 road=46.946 have=1 origin=44.525',
    'f22433 t1 cintro: ra=0048b738 z=45.377 retail=46.647 final=46.647 miss=0 recovered=0 road=46.647 have=1 origin=44.525',
    'f22434 t1 cintro: ra=0048b738 z=44.977 retail=46.945 final=46.945 miss=0 recovered=0 road=46.945 have=1 origin=44.525',
)


def margin(lines, field):
    worst = None
    for line in lines:
        v = {k: float(x) for k, x in re.findall(r'(z|retail|final|road|origin)=(-?[\d.]+)', line)}
        m = v['z'] + (v[field] - v['origin']) - v['road']
        worst = m if worst is None else min(worst, m)
    return worst


def main():
    fixed, broken = margin(LINES, 'final'), margin(LINES, 'origin')
    assert fixed >= 0.3, fixed
    assert broken < -1.0, broken          # the broken control must fail the same threshold
    base = HERE / 'out/carbon-base/image.json'
    if not base.is_file():
        print('SKIP: needs Carbon build outputs')
        return 3
    sys.path.insert(0, str(HERE))
    import recomp
    image = json.loads(base.read_text())
    pe = recomp.PE(image['exe'], expected_sha256=IMAGE_SHA)
    row, = json.loads((PRIVATE / 'hooks/cintro_height.json').read_text())['hooks']
    w = row['witness']
    assert row['address'] == w['start'] == '004809C0' and row['image_sha256'] == IMAGE_SHA
    assert hashlib.sha256(pe.read(0x4809C0, w['length'])).hexdigest() == w['sha256']
    feature = json.loads((PRIVATE / 'features/cintro_height.json').read_text())
    source = (PRIVATE / 'carbon_cintro_height.c').read_bytes()
    assert feature['bindings']['carbon_cintro_height.c']['sha256'] == hashlib.sha256(source).hexdigest()
    print(f'PRIVATE CINTRO PASS fixed={fixed:+.2f} m broken={broken:+.2f} m')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
