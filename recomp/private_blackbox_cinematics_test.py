"""Carbon frozen-clock report proof through the production adapter and recorder.

Premise on inherited main: 0/1; fixed: 1/1; removed feed: 0/1.
Covers carbon_blackbox_cinematics.c, carbon_blackbox.c, carbon_addons_gameplay.c,
features/blackbox_cinematics.json, features/blackbox.json,
features/addons_gameplay.json, runtime/blackbox.c, runtime/blackbox.h,
runtime/docs/blackbox.md and runtime/docs/diagnostics-3.md.
No game, audio, controllers or GPU. Image witnesses exit 3 without private assets.
"""
from pathlib import Path
import hashlib
import json
import os
import runpy
import statistics
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
PRIVATE = HERE / 'private_runtime'
RUNTIME = ROOT / 'runtime'
CORE = runpy.run_path(str(RUNTIME / 'blackbox_test.py'))

FIXTURE = r'''
#include "host.h"
#include "blackbox.h"
#include <assert.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
uint8_t *G;
static uint64_t fake_ns = 100000000000ull;
static unsigned clock_calls;
static int fixture_clock(clockid_t id, struct timespec *t) {
    (void)id; ++clock_calls; t->tv_sec=fake_ns/1000000000ull; t->tv_nsec=fake_ns%1000000000ull; return 0;
}
#define clock_gettime fixture_clock
#include "blackbox.c"
#undef clock_gettime
void carbon_blackbox_fe(uint64_t f, uint32_t flow, uint64_t now) { (void)f; (void)flow; (void)now; }
void blackbox_input(uint64_t f, uint64_t now) { (void)f; (void)now; }
#ifndef BENCH
static unsigned guest_reads, clock_reads;
static uint32_t cin_read32(uint32_t a) {
    assert(a <= 0x1000000-4); ++guest_reads;
    if (a==0x6020 || a==0x6028) ++clock_reads;
    uint32_t v; memcpy(&v,G+a,4); return v;
}
static uint8_t cin_read8(uint32_t a) { assert(a<0x1000000); ++guest_reads; return G[a]; }
#undef M32
#undef M8
#define M32(a) cin_read32(a)
#define M8(a) cin_read8(a)
#endif
#include "tap.inc"
#ifndef BENCH
#undef M32
#undef M8
#define M32(a) (*(u32a *)(G+(uint32_t)(a)))
#define M8(a) (*(u8a *)(G+(uint32_t)(a)))
#endif
#include "adapter.inc"
int diag_on;
static unsigned original_calls;
static int settings_get(const char *key) { (void)key; return 0; }
void diag_event(const char *fmt, ...) { (void)fmt; abort(); }
static int cadd_title_seen;
#include "provider.inc"
static void original(Cpu *c) { ++original_calls; c->eax=17; c->esp+=4; }
static uint64_t real_ns(void) {
    struct timespec t; clock_gettime(CLOCK_MONOTONIC,&t); return (uint64_t)t.tv_sec*1000000000ull+t.tv_nsec;
}
int main(int argc, char **argv) {
    (void)argc; (void)argv; (void)real_ns;
#ifndef BENCH
    if (!blackbox_enabled()) {
        G=(void *)1; carbon_blackbox_movie_request(0x2000);
        carbon_blackbox_cinematics(1,fake_ns);
        assert(!guest_reads && !clock_calls);
    }
#endif
    G=calloc(1, 0x1000000); assert(G);
    M32(0xA97BB4)=0x2000; M32(0x2000)=0x9D0000;
    M32(0x2120)=3; M32(0x2124)=4;
    strcpy((char *)G+0x201C, "PRIVATE_DRIVER/movie.vp6");
    M32(0xB4D964)=0x4000; M32(0x4000)=0x9EC6E8;
    M32(0x42E0)=5; M32(0x4390)=0x6000; M32(0x6000)=0x9C5FE0;
    MF32(0x6020)=2.5f; MF32(0x6028)=12.0f;
#ifdef BENCH
    if (argc>1 && !strcmp(argv[1],"idle")) { M32(0xA97BB4)=0; M32(0xB4D964)=0; }
    uint64_t start=real_ns();
    for (unsigned f=1; f<=500000; ++f) {
        fake_ns+=5000000ull;
        blackbox_game_frame(f,6,&(BlackboxTiming){.draws=132,.ticks=1});
    }
    printf("%.3f\n",(real_ns()-start)/500000.0); free(G); return 0;
#endif
    Cpu c={0}; c.ecx=0x2000; c.eax=99; c.esp=0x9000;
    Cpu expected=c; expected.eax=17; expected.esp+=4;
    carbon_addons_movie(&c,original);
    assert(original_calls==1 && !memcmp(&c,&expected,sizeof c));
    if (!blackbox_enabled()) {
        assert(!clock_calls); blackbox_export_at(stdout,BB_HANG,fake_ns); free(G); return 0;
    }
    uint8_t *before=malloc(0x1000000); assert(before); memcpy(before,G,0x1000000);
    for (unsigned f=1; f<=8000; ++f) {
        fake_ns+=5000000ull;
#ifndef BENCH
        guest_reads=0;
#endif
        blackbox_game_frame(f, 6, &(BlackboxTiming){.draws=132,.ticks=1});
#ifndef BENCH
        assert(guest_reads<=80);
#endif
    }
    assert(!memcmp(before,G,0x1000000)); free(before);
#ifndef BENCH
    unsigned stream_clock_reads=clock_reads;
#endif
    /* Both latest cinematic slots must outlive unrelated event-ring wrap. */
    for (unsigned i=0;i<4097;++i)
        blackbox_record_fe(&(BlackboxFE){.index=0,.state=i},1,8000,fake_ns);
    blackbox_menu_at(1,fake_ns);
    fake_ns+=80000000000ull;
    puts("F10_BEGIN"); blackbox_export_at(stdout,BB_F10,fake_ns); puts("F10_END");
    blackbox_menu_at(0,fake_ns);
    puts("HANG_BEGIN"); blackbox_export_at(stdout,BB_HANG,fake_ns); puts("HANG_END");
    /* Clock progress resets the age; unsupported classes expose no guessed fields. */
    MF32(0x6020)=3.0f; fake_ns+=250000000ull;
    blackbox_game_frame(8001,6,&(BlackboxTiming){0});
    puts("PROGRESS_BEGIN"); blackbox_export_at(stdout,BB_STALL,fake_ns); puts("PROGRESS_END");
    M32(0x4000)=0xBADCAFE; M32(0x42E0)=0xFEED;
    fake_ns+=250000000ull; blackbox_game_frame(8002,6,&(BlackboxTiming){0});
    puts("UNKNOWN_BEGIN"); blackbox_export_at(stdout,BB_STALL,fake_ns); puts("UNKNOWN_END");
    M32(0x4000)=0x9EC6E8; M32(0x6020)=0x7FC00000;
    fake_ns+=250000000ull; blackbox_game_frame(8003,6,&(BlackboxTiming){0});
    puts("INVALID_BEGIN"); blackbox_export_at(stdout,BB_STALL,fake_ns); puts("INVALID_END");
    M32(0xA97BB4)=0xFFFFF000; M32(0xB4D964)=0xFFFFFFF0;
    fake_ns+=250000000ull; blackbox_game_frame(8004,6,&(BlackboxTiming){0});
    /* No following frame: request must still survive in the hang history. */
    c.ecx=0x2000; carbon_addons_movie(&c,original);
    puts("EDGE_BEGIN"); blackbox_export_at(stdout,BB_HANG,fake_ns); puts("EDGE_END");
#ifndef BENCH
    printf("CLOCK_READS %u\n",stream_clock_reads);
#endif
    free(G);
}
'''


def visible(report):
    return all(s in report for s in (
        'CARBON MOVIE edge=state valid=1 player=00002000 class=009D0000 state=3',
        'CARBON NIS edge=state valid=1 interface=00004000 class=009EC6E8 state=5',
        'elapsed=2.500 length=12.000 playback_unchanged_for=39.995s',
    ))


# Native image fragments, each tied to a decoded field or consumer.
WITNESSES = {
    0x0057F3B0: 'a1b47ba90085c0741b8b802001000083f803740a83f804740583f8057506b801000000c333c0c3',
    0x0059528F: '898620010000898624010000',  # MoviePlayer state/next
    0x005952CE: '8d461c50',  # inline filename
    0x0076D780: 'c74640e8c69e00',  # INIS interface vtable at root+40
    0x00766933: '8b86e0020000',  # interface state
    0x0076310C: '8b8690030000',  # interface track
    0x00763491: '8bbed0030000',  # root track = interface+390
    0x0076349B: '8b078bcfff5028d95c240c8b178bcfff5224d85c240c',  # compare length/elapsed
    0x0045D740: 'd94120c3', 0x0045D750: 'd94128c3',  # float getters
    0x0045D5DB: 'c700e05f9c00',  # track class
    0x009C6004: '50d7450040d74500',  # track virtual getters +24/+28
    0x00455CC4: '8b3564d9b400',  # global INIS pointer
}


def witnesses():
    image = HERE/'out/carbon-base/image.json'
    if not image.is_file():
        print('SKIP: private image witnesses required'); return False
    meta = json.loads(image.read_text())
    if not Path(meta['exe']).is_file():
        print('SKIP: supported private image required'); return False
    sys.path.insert(0,str(HERE))
    from recomp import PE
    pe = PE(meta['exe'],expected_sha256=meta['sha256'])
    for address, fragment in WITNESSES.items():
        assert pe.read(address,len(bytes.fromhex(fragment))).hex()==fragment, hex(address)
    for name in ('blackbox','blackbox_cinematics','addons_gameplay'):
        registry=json.loads((PRIVATE/'features'/f'{name}.json').read_text())
        assert registry['image_sha256']==meta['sha256']
        for binding in registry['bindings'].values():
            assert binding['sha256']==hashlib.sha256((PRIVATE/binding['source']).read_bytes()).hexdigest()
    print(f'native layout witnesses: {len(WITNESSES)} pinned fragments')
    return True


def main():
    env = {k: v for k, v in os.environ.items() if not k.startswith(('NFS_', 'BOOT_'))}
    with tempfile.TemporaryDirectory(prefix='cinematic-proof-') as directory:
        work = Path(directory)
        adapter = (PRIVATE / 'carbon_blackbox.c').read_text()
        (work / 'adapter.inc').write_text(adapter)
        (work / 'tap.inc').write_text((PRIVATE/'carbon_blackbox_cinematics.c').read_text())
        provider=CORE['function']((PRIVATE/'carbon_addons_gameplay.c').read_text(),
                                  'void carbon_addons_movie(Cpu *c, void (*original)(Cpu *))')
        (work/'provider.inc').write_text(provider)
        (work / 'fixture.c').write_text(FIXTURE)
        cmd = ['clang', '-std=gnu11', '-O2', '-Werror', '-fsanitize=address,undefined', '-I'+str(RUNTIME),
               '-I'+str(HERE), '-I'+str(PRIVATE), str(work/'fixture.c'), '-o', str(work/'fixture')]
        compiled = subprocess.run(cmd, capture_output=True, text=True)
        if compiled.returncode:
            print(compiled.stderr[-6000:])
            return compiled.returncode
        result = subprocess.run([work/'fixture'], env=env, check=True, capture_output=True, text=True)
        report = result.stdout.split('F10_BEGIN\n')[1].split('F10_END')[0]
        number = int(visible(report))
        print(f'frozen cinematic report: {number}/1')
        if '--premise' not in sys.argv:
            assert number == 1
        assert 'PRIVATE_DRIVER' not in result.stdout and 'movie.vp6' not in result.stdout
        def section(name):
            return result.stdout.split(name+'_BEGIN\n')[1].split(name+'_END')[0]
        assert visible(section('HANG'))
        assert 'elapsed=3.000 length=12.000 playback_unchanged_for=0.000s' in section('PROGRESS')
        assert 'class=0BADCAFE state=unavailable layout=not_decoded_yet' in section('UNKNOWN')
        assert 'state=65261' not in section('UNKNOWN')
        assert 'clock_valid=0 playback_unchanged_for=unavailable' in section('INVALID')
        assert 'CARBON MOVIE edge=play valid=1 player=00002000' in section('EDGE')
        reads=int(result.stdout.split('CLOCK_READS ')[1].splitlines()[0])
        assert reads==320, reads
        # Mutate exactly the production adapter call, retain frame recording.
        call='    carbon_blackbox_cinematics(frame, now);'
        assert adapter.count(call)==1
        (work/'adapter.inc').write_text(adapter.replace(call,''))
        subprocess.run(cmd,check=True,capture_output=True,text=True)
        broken=subprocess.run([work/'fixture'],env=env,check=True,capture_output=True,text=True)
        broken_report=broken.stdout.split('F10_BEGIN\n')[1].split('F10_END')[0]
        assert not visible(broken_report)
        print(f'removed feed: {int(visible(broken_report))}/1; clock reads={reads} over 8,000 frames')
        (work/'adapter.inc').write_text(adapter)
        subprocess.run(cmd,check=True,capture_output=True,text=True)
        off=subprocess.run([work/'fixture'],env=dict(env,NFS_BLACKBOX='0'),capture_output=True,text=True)
        assert off.returncode==0, off.stderr
        assert 'disabled NFS_BLACKBOX=0' in off.stdout
        print('off: zero guest reads and recorder clocks; native CPU/result unchanged; guest writes=0')
        if '--bench' in sys.argv:
            cmd.remove('-fsanitize=address,undefined')
            cmd += ['-DBENCH']
            binaries=[]
            for label,text in (('before',adapter.replace(call,'')),('after',adapter)):
                (work/'adapter.inc').write_text(text)
                target=work/label
                build=list(cmd); build[build.index('-o')+1]=str(target)
                subprocess.run(build,check=True,capture_output=True,text=True); binaries.append(target)
            for case in ('idle','active'):
                pairs=[]
                for i in range(9):
                    order=(0,1) if i%2==0 else (1,0)
                    row={j:float(subprocess.check_output([binaries[j],case],env=env,text=True)) for j in order}
                    pairs.append(row)
                before=statistics.median(p[0] for p in pairs); after=statistics.median(p[1] for p in pairs)
                delta=statistics.median(p[1]-p[0] for p in pairs)
                print(f'{case}: {before:.1f} -> {after:.1f} ns/frame; paired median delta={delta:.1f}')
    if not witnesses(): return 3
    return 0


if __name__ == '__main__':
    sys.exit(main())
