"""Carbon overlay: baseline 3 disabled providers -> 0; synthetic Compact/stats
40.0 fps / 30.00 p50 / 40.00 p99; broken MW counter 0 -> 1 rejected read.
Compiles the production snapshot reduction, panel formatter and stats writer.
Compact rate: selected 120 -> 120; restored-60 control exit=1, good exit=0.
Diagnostics-off report feed: 3 callbacks; removed-hook control 0, rejected.
Missing private build outputs exit 3. No game or timing claims.
"""
from pathlib import Path
import json
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'recomp/out/carbon'
sys.path.insert(0, str(ROOT / 'recomp/private_runtime'))
from layers import load_manifest, disabled_exports, audit_unit, build_owned, check_audits



# Independent F10 row/callback contract, consumed by private_settings_test.py.
SETTINGS_ROWS = {'display.overlay': {'apply': 'overlay_set_level', 'get': 'overlay_level'}}
SETTINGS_PROVIDERS = {'overlay_set_level': 'overlay.m', 'overlay_level': 'overlay.m'}
SETTINGS_FIXTURE = """
static int fixture_overlay;
int overlay_level(void) { return fixture_overlay; }
void overlay_set_level(int value) { fixture_overlay=value; }
"""


def compiled_metrics(td, broken_rate=False, broken_report=False):
    overlay = (ROOT / 'runtime/overlay.m').read_text()
    host = (ROOT / 'runtime/host.h').read_text()
    diag = (ROOT / 'recomp/private_runtime/game_overlay_diagnostics.h').read_text()
    perf = host[host.index('enum { IDLE_SLEEP'):host.index('void perf_gpu_done')]
    snap = overlay[overlay.index('typedef struct {\n    double t;'):overlay.index('} Snap;') + len('} Snap;')]
    reduction = overlay[overlay.index('static void snapshot('):overlay.index('    // the graph\'s scale:')] + '}\n'
    lines = overlay[overlay.index('typedef struct { char label'):overlay.index('static CTFontRef font(')]
    if broken_rate:
        original = 's->fps, s->p50, s->p99, s->sim_hz);'
        assert lines.count(original) == 1
        lines = lines.replace(original, 's->fps, s->p50, s->p99, 60);')
    stats = diag[diag.index('static int private_overlay_compare'):diag.index('void diag_frame(')]
    producer = diag[diag.index('void diag_frame('):]
    if broken_report:
        producer = producer.replace('    report_frame(frame, private_report_flow());', '')
    gpu = diag[diag.index('void perf_gpu_done('):diag.index('static int private_overlay_compare')]
    source = r'''
#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <assert.h>
#include <math.h>
#define NFS_GAME 2
#define NFS_GAME_MW 1
enum { OVERLAY_OFF, OVERLAY_COMPACT, OVERLAY_FULL, OVERLAY_NOTICE };
''' + perf + '''
PerfFrame perf_frames[PERF_RING];
volatile uint64_t perf_nframes;
float perf_gpu_ms[PERF_RING];
volatile uint64_t perf_gpu_serial;
static void *layer;
static double backing_scale(void) { return 1; }
static uint64_t test_now = 1000000000;
static int fixture_hz = 60;
int carbon_sim_hz(void) { return fixture_hz; }
static uint64_t host_ticks(void) { return test_now; }
static double notice_until;
static char notice_text[64];
static int cmp_f(const void *a, const void *b) { float x=*(const float *)a,y=*(const float *)b; return (x>y)-(x<y); }
''' + snap + reduction + lines + stats + gpu + r'''
static uint32_t native_ticks;
#define M32(a) (assert((a)==0x00B4CFD4u), native_ticks)
static int diag_on, overlay_calls, report_calls;
uint32_t private_report_flow(void) { return 3; }
void report_frame(uint64_t frame, uint32_t flow) {
    assert(!diag_on && flow==3 && frame==(uint64_t)++report_calls);
}
static const char *diag_dir;
static FILE *stats_f;
static FILE *private_mix_file;
uint64_t diag_idle_ns[IDLE_N];
static void private_overlay_base_frame(uint64_t f, uint64_t d) { (void)f; (void)d; }
static void overlay_frame(void) { ++overlay_calls; }
''' + producer + r'''
int main(void) {
    /* Wrap the ring twice; the newest forty frames total exactly one second. */
    perf_nframes = PERF_RING * 2;
    for (int i=0; i<PERF_RING; ++i) {
        perf_frames[i].frame_ms = (i%4+1)*10;
        perf_frames[i].busy_ms = 5;
        perf_frames[i].draws = 12;
        perf_frames[i].ticks = i%3;
    }
    Snap s; snapshot(&s, OVERLAY_COMPACT);
    assert(s.n==40 && s.fps==40 && s.p50==30 && s.p99==40);
    Line l[32]; assert(panel_lines(&s,OVERLAY_COMPACT,l)==1);
    float fps,p50,p99; int hz;
    assert(sscanf(l[0].text,"%f fps %f ms p50 %f p99 sim %d Hz",&fps,&p50,&p99,&hz)==4);
    assert(fps==40 && p50==30 && p99==40 && hz==60);
    fixture_hz=120;snapshot(&s,OVERLAY_COMPACT);
    assert(s.sim_hz==120 && panel_lines(&s,OVERLAY_COMPACT,l)==1);
    if(!strstr(l[0].text,"sim 120 Hz"))return 1;fixture_hz=60;
    FILE *f=tmpfile(); assert(f); private_overlay_stats(f,2000,1000000000); rewind(f);
    char text[512]; assert(fgets(text,sizeof text,f)); fclose(f);
    float logfps, log50, log99;
    assert(sscanf(text,"t %*f frame %*u fps %f ms p50 %f p99 %f",&logfps,&log50,&log99)==3);
    assert(fps==logfps && p50==log50 && p99==log99);
    s.bw=1920;s.bh=1080;s.ww=1920;s.wh=1080;s.sim_hz=60;s.audio_live=-2;s.msaa=4;
    int n=panel_lines(&s,OVERLAY_FULL,l), flags=0;
    for(int i=0;i<n;++i) {
        assert(!strstr(l[i].text,"bump") && !strstr(l[i].text,"gmalloc") && !strstr(l[i].text,"heap"));
        assert(!strstr(l[i].text,"vinyl") && !strstr(l[i].text,"skins") && !strstr(l[i].text,"post ") && !strstr(l[i].text,"shadows"));
        if(strstr(l[i].text,"GPU textures"))flags|=1;
        if(strstr(l[i].text,"MSAA 4x"))flags|=2;
        if(!strcmp(l[i].label,"game thread"))flags|=4;
        if(!strcmp(l[i].label,"input"))flags|=8;
        if(!strcmp(l[i].label,"rumble"))flags|=16;
        if(!strcmp(l[i].label,"audio"))flags|=32;
    }
    assert(flags==63);
    perf_nframes=0; snapshot(&s,OVERLAY_COMPACT); assert(s.fps==0 && s.p50==0 && s.p99==0);
    native_ticks=100; diag_frame(1,9);
    assert(perf_nframes==1 && perf_frames[0].frame_ms==0 && perf_frames[0].ticks==0);
    test_now+=10000000; native_ticks+=2; diag_idle_ns[IDLE_SLEEP]=2000000;
    diag_frame(2,17);
    assert(perf_nframes==2 && perf_frames[1].frame_ms==10 && perf_frames[1].busy_ms==8);
    assert(perf_frames[1].draws==17 && perf_frames[1].ticks==2 && overlay_calls==2);
    test_now+=10000000; native_ticks=0; diag_frame(3,1);
    assert(perf_frames[2].ticks==0 && report_calls==3);
    perf_gpu_done(PERF_RING+7,2.5); assert(perf_gpu_serial==PERF_RING+7 && perf_gpu_ms[7]==2.5);
    puts("metrics: Compact=stats.log=40.0 fps / 30.00 p50 / 40.00 p99; full host rows present, MW rows absent; empty ring=0");
}
'''
    path=td/'metrics.c'; path.write_text(source)
    result=subprocess.run(['clang','-std=c11','-Wall','-Werror','-Wno-unused-function','-Wno-unused-variable',str(path),'-o',str(td/'metrics')],capture_output=True,text=True)
    assert result.returncode==0,result.stderr[-4000:]
    result=subprocess.run([str(td/'metrics')],capture_output=True,text=True)
    print('compact rate', 'restored-60' if broken_rate else 'good', 'report hook removed='+str(int(broken_report)), 'exit='+str(result.returncode))
    if broken_report:
        assert result.returncode != 0 and 'report_calls==3' in result.stderr, result.stderr[-2000:]
    else:
        assert result.returncode == (1 if broken_rate else 0), result.stderr[-2000:]



def compiled_controls(td):
    overlay=(ROOT/'runtime/overlay.m').read_text()
    controls=overlay[overlay.index('static int level = -1;'):overlay.index('// A message for NOTICE_S')]
    setter=overlay[overlay.index('void overlay_set_level('):overlay.index('// ---------------- the counters snapshot')]
    source=r'''#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <assert.h>
enum { OVERLAY_OFF, OVERLAY_COMPACT, OVERLAY_FULL };
static int diag_on, saves;
static char saved[16]="full";
static const char *app_pref(const char *key) { assert(!strcmp(key,"overlay")); return saved; }
static void app_pref_set(const char *key,const char *value) { assert(!strcmp(key,"overlay")); snprintf(saved,sizeof saved,"%s",value);++saves; }
static void diag_event(const char *format,...) { (void)format; }
''' + controls + setter + r'''
int main(void) {
    unsetenv("NFS_OVERLAY"); assert(overlay_level()==2);
    overlay_set_level(1); assert(overlay_level()==1 && !strcmp(saved,"compact") && saves==1);
    overlay_set_level(0); assert(overlay_level()==0 && !strcmp(saved,"off") && saves==2);
    overlay_set_level(3); assert(overlay_level()==0 && saves==2);
    for(int i=0;i<3;++i) {
        level=-1;setenv("NFS_OVERLAY",level_names[i],1);assert(overlay_level()==i);
    }
    level=-1;setenv("NFS_OVERLAY","invalid",1);assert(overlay_level()==0);
    puts("controls: saved overlay and Off/Compact/Full environment selection PASS");
}
'''
    path=td/'controls.c';path.write_text(source)
    result=subprocess.run(['clang',str(path),'-o',str(td/'controls')],capture_output=True,text=True)
    assert result.returncode==0,result.stderr[-2000:]
    subprocess.run([str(td/'controls')],check=True)


def main():
    required=['runtime_selection.json','runtime_compile_flags.json','runtime_mw_ranges.json','layer_audits.json','boot_carbon']
    if any(not (OUT/p).is_file() for p in required):
        print('SKIP: build private overlay outputs first');return 3
    if not build_owned(OUT):
        print('SKIP: private runtime link belongs to another checkout');return 3
    feature=json.loads((ROOT/'recomp/private_runtime/features/overlay.json').read_text())
    assert set(feature['sources']) == {'game_overlay_diagnostics.h','game_overlay_settings.h'}
    assert feature['enabled_providers'] == []
    manifest=load_manifest()
    selection=json.loads((OUT/'runtime_selection.json').read_text())
    assert 'overlay.m' in selection['selected']
    assert (OUT/'runtime/overlay.m.o').is_file()
    exports={r['name'] for r in disabled_exports(manifest)}
    assert not exports.intersection({'overlay_level','overlay_set_level','overlay_present'})
    overlay=(ROOT/'runtime/overlay.m').read_text()
    present=overlay.split('void overlay_present(',1)[1]
    assert present.index('if ((level <= OVERLAY_OFF && !notice_live)') < present.index('os_unfair_lock_lock')
    assert (OUT/'runtime/overlay.m').read_bytes()==(ROOT/'runtime/overlay.m').read_bytes()
    flags=json.loads((OUT/'runtime_compile_flags.json').read_text())
    ranges=json.loads((OUT/'runtime_mw_ranges.json').read_text())
    audits=json.loads((OUT/'layer_audits.json').read_text())
    good=check_audits(audits,manifest,manifest['targets']['private']['extra_sources'],require_complete=True)
    assert good['MW_reads']==good['MW_writes']==0
    with tempfile.TemporaryDirectory(prefix='private-overlay-') as temp:
        td=Path(temp);compiled_metrics(td);compiled_metrics(td,broken_rate=True);compiled_metrics(td,broken_report=True);compiled_controls(td)
        mutant=td/'overlay.m'
        mutant.write_text(overlay.replace('s->rss = rss_now();','s->rss = rss_now() + M32(0x00901830u);'))
        bad=audit_unit(mutant,flags,ranges)
        changed=[bad if a['unit']=='overlay.m' else a for a in audits]
        try:
            check_audits(changed,manifest,manifest['targets']['private']['extra_sources'],require_complete=True)
        except ValueError as error:
            assert '0x00901830' in str(error),str(error)
            assert str(error).count('MW address read:')==1,str(error)
        else:
            raise AssertionError('accepted MW-only counter in Carbon snapshot')
    print('PRIVATE OVERLAY PASS: disabled providers 3 -> 0; audit reads/writes 0/0; broken MW counter exactly 1 rejected read; Off returns before lock/GPU work')
    return 0


if __name__=='__main__':sys.exit(main())
