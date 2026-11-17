"""Carbon rear-view mirror target: texels per screen pixel of the mirror quad (production sizing).

3840x2160 (retail target 1024x512): port 1260x630 = 1.08 x 1.00 texels per pixel; retail size 0.88 x 0.81 (exit 1).
The quad comes from the decoded composite vertices (x +/-0.40625, y .629166722...920833349 of the 4:3 canvas,
the middle half of the target's height sampled), independently of the provider's front-end-unit constants.

World detail and view (production carbon_mirror_pass_flag / carbon_mirror_view_matrix): with NFS_MIRROR_DETAIL=full
the mirror view's pass flag AB0B98 (1 = both readers, 00723600 and 00748B83, pick lowlod) becomes 0 and every
other view keeps it; the old code (no change: the mirror keeps lowlod) exits 1. NFS_MIRROR_VIEW=60 at 3840x2160:
shown picture 3.714:1 in a 3.714:1 quad (error 0.0 %); the retail projection (m00 1.2502, m11 2.5075) is 4.011:1,
8.0 % off, the picture 7.4 % narrower (exit 1).
"""
from pathlib import Path
import hashlib
import json
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
PRIVATE = HERE / 'private_runtime'
sys.path.insert(0, str(HERE))
from private_render import body


def main():
    source = (PRIVATE / 'carbon_mirror.c').read_text()
    hooks = json.loads((PRIVATE / 'hooks/mirror.json').read_text())['hooks']
    assert [(h['address'], h['provider']) for h in hooks] == [('0070DAB0', 'carbon_mirror_allocate'),
        ('0072E070', 'carbon_mirror_view_setup'), ('0070F2F0', 'carbon_mirror_projection')]
    feature = json.loads((PRIVATE / 'features/mirror.json').read_text())
    assert feature['bindings']['carbon_mirror.c']['sha256'] == hashlib.sha256(source.encode()).hexdigest()
    sizing = body(source, 'carbon_mirror_size')
    fixture = r'''
#include <math.h>
#include <stdint.h>
#include <stdio.h>
static void carbon_mirror_size(uint32_t bw, uint32_t bh, uint32_t w0, uint32_t h0, int pct,
                               uint32_t *w, uint32_t *h) ''' + sizing + r'''
static uint32_t retail(uint32_t v) { uint32_t p = 1; while (p * 2 <= v / 3) p *= 2; return p; }  // 0070DAB0
int main(int argc, char **argv) {
    (void)argv;
    static const uint32_t out[][2] = {{3840,2160},{2560,1440},{1920,1080},{1280,1024},{1024,768},{3440,1440},{1280,720}};
    double worst = 9;
    for (unsigned i = 0; i < sizeof out / sizeof *out; ++i) {
        uint32_t bw = out[i][0], bh = out[i][1], w0 = retail(bw), h0 = retail(bh), w = w0, h = h0;
        if (argc < 2) carbon_mirror_size(bw, bh, w0, h0, 100, &w, &h);
        double canvas = bh * 4.0 / 3.0 < bw ? bh * 4.0 / 3.0 : bw;
        double qw = .40625 * canvas, qh = (.920833349 - .629166722) / 2 * bh;
        double tx = w / qw, ty = h / 2.0 / qh;
        if (bw == 3840) printf("3840x2160: target %ux%u, texels per pixel %.2f x %.2f\n", w, h, tx, ty);
        if (tx < worst) worst = tx;
        if (ty < worst) worst = ty;
        if (w < w0 || h < h0 || (uint64_t)w * h0 != (uint64_t)h * w0) return 2;   // never smaller, aspect kept
        if (argc < 2 && w > w0 && (tx < ty ? tx : ty) > 1.01) return 3;         // the smallest factor that covers
        uint32_t pw, ph;
        carbon_mirror_size(bw, bh, w0, h0, 0, &pw, &ph);                       // pc: retail
        if (pw != w0 || ph != h0) return 4;
    }
    printf("worst texels per pixel %.3f\n", worst);
    return worst < .999 ? 1 : 0;
}
'''
    with tempfile.TemporaryDirectory(prefix='private-cmirror-') as td:
        path = Path(td) / 'fixture.c'
        binary = Path(td) / 'fixture'
        path.write_text(fixture)
        subprocess.run(['clang', '-O1', '-Wall', '-Wextra', '-Werror', str(path), '-o', str(binary)], check=True)
        for name, args, expected in [('port', [], 0), ('retail', ['retail'], 1)]:
            r = subprocess.run([str(binary), *args], capture_output=True, text=True)
            print(name + ': ' + r.stdout.strip().replace('\n', '; ') + ' exit=' + str(r.returncode))
            assert r.returncode == expected, (name, r.returncode)
    detail(source)


DETAIL = r'''
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#define CARBON_MIRROR_VIEW 0x00B4B090u
static uint32_t carbon_mirror_pass_flag(uint32_t view, uint32_t flag, int full) PASS
static void carbon_mirror_view_matrix(float hfov, float aspect, float *m00, float *m11) MATRIX
static int lowlod(uint32_t flag) { return flag == 1; }   /* 00723600 and 00748B83: cmp [AB0B98], 1 */
int main(int argc, char **argv) {
    (void)argv;
    int view_only = argc > 1;
    static const uint32_t others[] = {0x00B4AF90u, 0x00B4B110u, 0x00B4BA10u};
    if (!view_only) {
        if (lowlod(carbon_mirror_pass_flag(CARBON_MIRROR_VIEW, 1, 1))) { printf("mirror full: still lowlod\n"); return 1; }
        if (!lowlod(carbon_mirror_pass_flag(CARBON_MIRROR_VIEW, 1, 0))) return 2;      /* pc: retail */
        for (unsigned i = 0; i < 3; ++i) if (!lowlod(carbon_mirror_pass_flag(others[i], 1, 1))) return 3;
        if (carbon_mirror_pass_flag(CARBON_MIRROR_VIEW, 0, 1) != 0) return 4;
        printf("mirror full: lowlod off; pc, main, reflection, env faces: lowlod kept\n");
    }
    double canvas = 2160 * 4.0 / 3.0, qa = (.40625 * canvas) / ((.920833349 - .629166722) / 2 * 2160);
    float m00 = 1.2502f, m11 = 2.5075f;                     /* retail, live diag */
    if (!view_only || argc > 2) carbon_mirror_view_matrix(60.0f, (float)qa, &m00, &m11);
    double shown = (2.0 / m00) / (1.0 / m11), err = fabs(shown / qa - 1.0);
    printf("view: shown %.3f:1 in a %.3f:1 quad, error %.1f %%, %.1f deg across\n", shown, qa, err * 100, 2 * atan(1 / m00) * 180 / M_PI);
    return err > .001;
}
'''


def detail(source):
    fixture = DETAIL.replace('PASS', body(source, 'carbon_mirror_pass_flag')).replace(
        'MATRIX', body(source, 'carbon_mirror_view_matrix'))
    broken = DETAIL.replace('PASS', '{ (void)view; (void)full; return flag; }').replace(
        'MATRIX', body(source, 'carbon_mirror_view_matrix'))
    with tempfile.TemporaryDirectory(prefix='private-cmirror-') as td:
        for name, text, args, expected in [('detail+view', fixture, [], 0), ('old detail', broken, [], 1),
                                           ('retail view', fixture, ['retail'], 1), ('view 60', fixture, ['v', '60'], 0)]:
            path, binary = Path(td) / 'detail.c', Path(td) / 'detail'
            path.write_text(text)
            subprocess.run(['clang', '-O1', '-Wall', '-Wextra', '-Werror', str(path), '-o', str(binary)], check=True)
            r = subprocess.run([str(binary), *args], capture_output=True, text=True)
            print(name + ': ' + r.stdout.strip().replace('\n', '; ') + ' exit=' + str(r.returncode))
            assert r.returncode == expected, (name, r.returncode)


if __name__ == '__main__':
    main()
