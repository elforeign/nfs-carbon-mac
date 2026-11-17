"""Carbon front-end probe (NFS_CARBON_FE_PROBE), native fixture without a game or GPU.

Good: switch off 0 events over 2,702 calls; on 54 flow-3 state lines (root state 4, grand prev 8, controlling package
starred, loading-mask change seen) and 600 draws lines (frame 0..599, n=260) after game-flow becomes 3.
Forced black-screen F10 export, diagnostics OFF: tap 1/1; removed tap 0/1.
Production reader + adapter + recorder/export; unchanged state remains visible after 40s.
Also checks cyclic package walks, unknown-label privacy and guest memory unchanged.
Covers carbon_blackbox_fe.c, carbon_blackbox.c, carbon_fe_probe.h, blackbox.c,
blackbox.h and features/blackbox_fe.json; no assets or GPU required.
"""
from pathlib import Path
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
CLOCK = HERE / 'private_runtime/carbon_picture_clock.c'
ADAPTER = HERE / 'private_runtime/carbon_blackbox.c'

SOURCE = r'''
#include "host.h"
#include <stdarg.h>
#include <stdlib.h>
#include <assert.h>
#include <time.h>
int diag_on = 1;
uint8_t *G;
PerfFrame perf_frames[PERF_RING];
volatile uint64_t perf_nframes;
static unsigned diag_events;
static uint64_t fake_ns;
uint64_t host_ticks(void) { return fake_ns; }
void diag_event(const char *fmt, ...) {
    va_list ap; va_start(ap, fmt); ++diag_events; printf("EVENT "); vprintf(fmt, ap); printf("\n"); va_end(ap);
}
static int fixture_clock(clockid_t id, struct timespec *t) {
    (void)id; t->tv_sec=fake_ns/1000000000ull; t->tv_nsec=fake_ns%1000000000ull; return 0;
}
#define clock_gettime fixture_clock
#include "blackbox.c"
#undef clock_gettime
static unsigned guest_reads, max_guest_reads;
static uint32_t fixture_read32(uint32_t a) {
    assert(a <= 0x01000000u-4); ++guest_reads;
    uint32_t v; memcpy(&v, G+a, sizeof v); return v;
}
static uint8_t fixture_read8(uint32_t a) {
    assert(a < 0x01000000u); ++guest_reads; return G[a];
}
#undef M32
#undef M8
#define M32(a) fixture_read32(a)
#define M8(a) fixture_read8(a)
#include "carbon_blackbox_fe.c"
#undef M32
#undef M8
#define M32(a) (*(u32a *)(G+(uint32_t)(a)))
#define M8(a) (*(u8a *)(G+(uint32_t)(a)))
#include "adapter.inc"
#define HOOK() do { guest_reads=0; blackbox_game_frame(perf_nframes, M32(0x00A99BBCu), NULL); \
    assert(guest_reads <= 1039); if (guest_reads>max_guest_reads) max_guest_reads=guest_reads; } while (0)
static void put32(uint32_t a, uint32_t v) { M32(a) = v; }
static void put_str(uint32_t a, const char *s) { memcpy(G + a, s, strlen(s) + 1); }
int main(int argc, char **argv) {
    diag_on = !getenv("DIAG_OFF");
    G = calloc(1, 0x01000000u);
    if (!G) return 2;
    /* root 0x1000 (state 4) -> child 0x2000 (state 5) -> grand 0x3000 (state 0, prev 8, screen FeMainMenu_Sub.fng) */
    put32(0x00A97A7Cu, 0x1000); put32(0x1000 + 4, 4); put32(0x1000 + 0xB0, 0x2000);
    put32(0x2000 + 4, 5); put32(0x2000 + 0xB0, 0x3000);
    put32(0x3000 + 4, 0); put32(0x3000 + 0x14, 8); put_str(0x3000 + 0x1C, "FeMainMenu_Sub.fng");
    put32(0x00A9970Cu, 0x4000); put32(0x4000, 0x4100); put32(0x4100, 0);
    put32(0x00BBAA8Cu, 0x5000); put32(0x5000 + 0x4C, 1);
    put32(0x00B70650u + 0x32C, 4); put32(0x00B70650u + 0x28, 4);
    /* package list: wrapper -> engine -> +E4 head, next +8, name +0C, control +20 */
    put32(0x00A97A78u, 0x6000); put32(0x6000, 0x6100); put32(0x6100 + 0xE4, 0x6200);
    put32(0x6200 + 8, 0x6300); put32(0x6200 + 0xC, 0x6400); put_str(0x6400, "FeGarageMain.fng");
    put32(0x6300 + 0xC, 0x6440); put_str(0x6440, "FeMainMenu_Sub.fng"); put32(0x6300 + 0x20, 1);
    put32(0x00A99BBCu, 6);
    for (int i = 0; i < 700; ++i) {
        if (i == 50) put32(0x00A99BBCu, 3);
        if (i == 300) put32(0x00A9970Cu + 0, 0x4000), put32(0x4100, 0x40);   /* loading mask changes: one more line */
        fake_ns += 1000000ull * 20;
        perf_frames[perf_nframes % PERF_RING].draws = 260;
        ++perf_nframes;
        HOOK();
    }
    /* Persistent forced black screen: no diagnostics or probe needed for F10. */
    put_str(0x6440, "FeBlackScreen.fng"); put32(0x5000 + 0x4C, 0);
    put32(0x00B70650u + 0x1F0, 1); put32(0x00B70650u + 0x28, 2); put32(0x00B70650u + 0x24, 1);
    fake_ns += 20000000ull; HOOK();
    uint8_t *before = malloc(0x01000000u); memcpy(before, G, 0x01000000u);
    for (unsigned i=0; i<2000; ++i) { fake_ns+=20000000ull; ++perf_nframes; HOOK(); }
    assert(!memcmp(before, G, 0x01000000u)); free(before);
    blackbox_menu_at(1, fake_ns);
    puts("REPORT_BEGIN"); blackbox_export_at(stdout, BB_F10, fake_ns); puts("REPORT_END");
    blackbox_menu_at(0, fake_ns);
    /* Cycle: bounded at 24; arbitrary profile-like text must not enter blackbox.txt. */
    put32(0x6300 + 8, 0x6200); put_str(0x6440, "PRIVATE_DRIVER_SECRET.fng");
    fake_ns += 20000000ull; ++perf_nframes; HOOK();
    puts("CYCLE_BEGIN"); blackbox_export_at(stdout, BB_STALL, fake_ns); puts("CYCLE_END");
    /* Saturate every bounded string read while the package cycle remains live. */
    const char *long_name="1234567890123456789012345678901";
    put_str(0x6400,long_name); put_str(0x6440,long_name); put_str(0x6500,long_name);
    for(unsigned i=1;i<=3;++i) { put_str(i*0x1000+0x1C,long_name); put32(i*0x1000+0x9C,0x6500); }
    fake_ns+=20000000ull; ++perf_nframes; HOOK();
    /* Invalid sentinel pointers must not become unbounded guest reads. */
    put32(0x00A97A7Cu,0xFFFFF000u); put32(0x00A97A78u,0xFFFFFFF0u);
    put32(0x00A9970Cu,0xFFFFFFF0u); put32(0x00BBAA8Cu,0xFFFFFFF0u);
    fake_ns+=20000000ull; ++perf_nframes; HOOK();
    puts("INVALID_BEGIN"); blackbox_export_at(stdout,BB_STALL,fake_ns); puts("INVALID_END");
    printf("MAX_GUEST_READS %u\n", max_guest_reads);
    printf("EVENTS %u\n", diag_events);
    return 0;
}
'''


def run(hook, switch, work, diag=True, recorder=True):
    src = work / 'fixture.c'
    src.write_text(SOURCE)
    adapter = ADAPTER.read_text()
    if not hook: adapter = adapter.replace('    carbon_blackbox_fe(frame, flow, now);', '')
    (work / 'adapter.inc').write_text(adapter)
    binary = work / ('fixture_%d' % hook)
    subprocess.run(['clang', '-std=gnu11', '-O1', '-Wall', '-fsanitize=address,undefined', '-I', str(ROOT / 'runtime'), '-I', str(ROOT / 'recomp'),
                    '-I', str(HERE / 'private_runtime'), str(src), '-o', str(binary)], check=True)
    env = {'NFS_CARBON_FE_PROBE': '1'} if switch else {}
    if not diag: env['DIAG_OFF'] = '1'
    if not recorder: env['NFS_BLACKBOX'] = '0'
    return subprocess.run([str(binary)], env=env, capture_output=True, text=True, check=True).stdout


def main():
    assert 'carbon_fe_probe' not in CLOCK.read_text()
    adapter = ADAPTER.read_text()
    assert adapter.count('carbon_blackbox_fe(frame, flow, now);') == 1
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        off = run(True, False, work)
        on = run(True, True, work)
        removed = run(False, True, work)
        quiet = run(True, False, work, diag=False)
        missing = run(False, False, work, diag=False)
        disabled = run(True, False, work, diag=False, recorder=False)
        mirror_only = run(True, True, work, recorder=False)
    report = quiet.split('REPORT_BEGIN\n')[1].split('REPORT_END')[0]
    absent = missing.split('REPORT_BEGIN\n')[1].split('REPORT_END')[0]
    sentinels = ("control='FeBlackScreen.fng'", 'FE root valid=1', 'state=4',
                 'FE child valid=1', 'state=5', 'FE grand valid=1', 'prev=8',
                 'mask=40 loader busy=1 want=4 have=2+1 garage_ready=0')
    good = int(all(x in report for x in sentinels))
    broken = int(all(x in absent for x in sentinels))
    assert good == 1 and broken == 0, '\n'.join(l for l in report.splitlines() if any(k in l for k in (' FE ', ' LOAD ', ' PACKAGE ')))
    cycle = quiet.split('CYCLE_BEGIN\n')[1].split('CYCLE_END')[0]
    assert 'count=24 truncated=1' in cycle and 'PRIVATE_DRIVER_SECRET' not in cycle
    assert 'MAX_GUEST_READS 1039' in quiet
    invalid = quiet.split('INVALID_BEGIN\n')[1].split('INVALID_END')[0]
    assert 'FE root valid=0' in invalid and 'LOAD valid=2 mask=FFFFFFFF' in invalid
    assert quiet.endswith('EVENTS 0\n')
    assert 'MAX_GUEST_READS 0' in disabled and 'disabled NFS_BLACKBOX=0' in disabled
    assert 'fe-probe: draws frame=599 n=260' in mirror_only
    assert report.count('FE root') == 1 and report.count('LOAD ') == 1
    output = ROOT / '.metal-cache/blackbox-fe-proof'; output.mkdir(parents=True, exist_ok=True)
    (output / 'blackbox.txt').write_text(report)
    print('BLACK SCREEN F10 diagnostics=off tap=%d/1 removed=%d/1; cyclic=24; guest writes=0; %s; disabled reads=0' % (good, broken, quiet.split('MAX_GUEST_READS ')[1].splitlines()[0]))
    lines = [l for l in on.split('REPORT_BEGIN')[0].splitlines() if l.startswith('EVENT fe-probe: ') and ' draws ' not in l]
    draws = [l for l in on.splitlines() if 'fe-probe: draws' in l]
    state = [l for l in lines if 'flow=3' in l]
    ok = ('EVENTS 0' in off and 'EVENTS 0' in removed
          and len(state) == 54 and len(draws) == 600
          and 'frame=0 n=260' in draws[0] and 'frame=599 n=260' in draws[-1]
          and "root=" in state[0] and 'state=4' in state[0] and 'grand=00003000' in state[0] and 'prev=8' in state[0]
          and "pkg1='FeMainMenu_Sub.fng'*" in state[0] and "pkg0='FeGarageMain.fng' " in state[0]
          and 'mask=40' in state[-1] and 'garage_ready=1' in state[0] and 'want=4' in state[0])
    print('PRIVATE FE PROBE %s off=%s on_state_lines=%d draws_lines=%d removed=%s' % (
        'PASS' if ok else 'FAIL', off.strip().splitlines()[-1], len(state), len(draws), removed.strip().splitlines()[-1]))
    if not ok:
        print(on[:1500])
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
