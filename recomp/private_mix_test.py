"""Private BOOT_DIAG mix plumbing, no game/GPU/audio device.

Good: 2 once-per-second lines, six RMS channels at 0.000125 steps, buffers=3/playing=2.
Broken three-decimal meter: loses precision, fails (exit 1).
Per-Present timestamps: 3 rows (frames 10/20/30), disabled diagnostics: 0 rows.
Broken: disconnected shared meter or wrong voice-state offset -> check fails (exit 1).
Broken timestamp write: 0 rows, fails (exit 1).
Source counter/peaks: 1536/2/4/1.5 -> 0/0/0.89; disconnected stats exits 1 (good 0).
Required-body guards also reject each of the three mix readers/counters disabled.
Image identity: wrong-image fixture 0 reads/lines (exit 0); removing its guard
reads the guest state and meter (exit 1).
Game normal/muted evidence is recorded separately in the branch notes.
Shared stats stream: good 6/6 ordered lines (3 mixrms + 3 overlay); original
independent "w" streams fail: 5/6 markers survive, one in a NUL-corrupted row.
"""
from pathlib import Path
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / 'private_runtime'))
from private_render import body
from private_media import verify_media


def shared_stats(fixture, root):
    host = (HERE.parent / 'runtime/host.h').read_text()
    perf = host[host.index('enum { IDLE_SLEEP'):host.index('void perf_gpu_done')]
    overlay = (HERE / 'private_runtime/game_overlay_diagnostics.h').read_text()
    writers = overlay[overlay.index('static int private_overlay_compare'):]
    prefix = fixture.split('int main(', 1)[0].replace(
        'void diag_frame(uint64_t frame,uint64_t draws)',
        'void private_overlay_base_frame(uint64_t frame,uint64_t draws)')
    source = prefix + '\n#include <math.h>\n' + perf + r'''
PerfFrame perf_frames[PERF_RING];
volatile uint64_t perf_nframes;
uint64_t diag_idle_ns[IDLE_N];
static FILE *stats_f;
static const char *diag_dir;
static void overlay_frame(void) {}
uint32_t private_report_flow(void) { return 3; }
void report_frame(uint64_t frame, uint32_t flow) { (void)frame; (void)flow; }
''' + writers + r'''
int main(int argc, char **argv) {
    if (argc != 2) return 2;
    diag_dir = argv[1];
    private_mix_init(diag_dir);
    for (unsigned second = 1; second <= 3; ++second) {
        now = second * 1000000000ull;
        diag_frame(second * 60, 0);
    }
    /* stats_f may alias the mix stream; close each stream exactly once. */
    if (stats_f && stats_f != private_mix_file) fclose(stats_f);
    fclose(private_mix_file); fclose(private_frame_times);
    return 0;
}
'''
    # Labelled original control: the overlay independently truncates stats.log.
    old_open = '''char path[4096];
            snprintf(path, sizeof path, "%s/stats.log", diag_dir);
            stats_f = fopen(path, "w");'''
    assert source.count('stats_f = private_mix_file;') == 1
    for control in (False, True):
        code = source.replace('stats_f = private_mix_file;', old_open) if control else source
        path = root / 'shared-stats.c'
        path.write_text(code)
        executable = root / 'shared-stats'
        result = subprocess.run(['clang', '-O1', '-fsanitize=address,undefined',
                                 str(path), '-o', str(executable)], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr[-2000:]
        (root / 'stats.log').write_text('stale session\n')
        result = subprocess.run([str(executable), str(root)], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr[-2000:]
        lines = (root / 'stats.log').read_text().splitlines()
        mix = sum(' mixrms ' in line for line in lines)
        overlay_count = sum(' fps ' in line for line in lines)
        # Independent of either production formatter: six complete ordered rows.
        expected = [(second * 60, kind) for second in range(1, 4)
                    for kind in ('mixrms', 'fps')]
        actual = [(int(parts[3]), parts[4]) for line in lines
                  if len(parts := line.split()) >= 5 and parts[0] == 't']
        good = (len(lines) == 6 and mix == overlay_count == 3
                and actual == expected and not any('\0' in line for line in lines))
        print(f'SHARED STATS {"original control" if control else "production"}: '
              f'mixrms={mix}/3 overlay={overlay_count}/3 ordered={actual == expected}')
        assert good == (not control), lines
        if control:
            assert (mix, overlay_count) == (2, 3) and '\0' in '\n'.join(lines)


def main():
    for name in ('dsound_mix_rms', 'dsound_mix_levels', 'private_mix_buffers'):
        inventory = {'dsound.c': [{'name': name, 'reason': 'deliberately disabled'}], 'dinput.c': [], 'boot.c': []}
        try:
            verify_media(inventory)
        except ValueError:
            pass
        else:
            raise AssertionError('required mix body lost: ' + name)
    print('PRIVATE MIX REQUIRED BODY PASS rejects=3')
    helper = (HERE / 'private_runtime/mix_stats.h').read_text()
    fixture = r'''
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define PRIVATE_CARBON_SKIPFE 1
static unsigned flow=6,calls;
static uint64_t now=1000000000ull,frame_now,last_frame_ns;
static int diag_on=1;
static unsigned char voice_data[0x84*3];
#define M32(a) ((a)==0x00A99BBCu?flow:0x1000u)
#define M16(a) (3u)
#define M8(a) (voice_data[(a)-0x1000u])
uint64_t host_ticks(void){return now;}
void diag_idle(int idle){(void)idle;}
static pthread_t game_thread;static int have_game_thread;   // diag_profile.h's, set by diag_frame
int dsound_mix_rms(double rms[6],uint64_t *clip,uint64_t *lim,double *min_gain){
 if(min_gain)return 0;
 ++calls;for(int i=0;i<6;i++)rms[i]=0.000125*(i+1);*clip=7;*lim=9;return 1;
}
void private_mix_buffers(unsigned *b,unsigned *p){*b=3;*p=2;}
void private_carbon_audio_stats(uint64_t c[5],double p[2]){
 c[0]=1536;c[1]=2;c[2]=4;c[3]=0;c[4]=0;p[0]=1.5;p[1]=.89;
}
''' + helper + '\nvoid diag_frame(uint64_t frame,uint64_t draws)' + body((HERE / 'private_runtime/game_diagnostics.h').read_text(), 'diag_frame') + r'''
int main(int argc,char **argv){
 if(argc!=2)return 2;private_mix_init(argv[1]);
 voice_data[0x69]=1;voice_data[0x23]=1;voice_data[0x84+0x69]=2;voice_data[0x84+0x23]=2;
 diag_on=0;diag_frame(1,0);if(calls || frame_now!=1)return 3;
 diag_on=1;diag_frame(10,0);now+=500000000ull;diag_frame(20,0);
 now+=500000000ull;diag_frame(30,0);fclose(private_mix_file);fclose(private_frame_times);
 char path[4096],line[1024];snprintf(path,sizeof path,"%s/stats.log",argv[1]);
 FILE *f=fopen(path,"r");unsigned n=0;
 while(fgets(line,sizeof line,f)){
   if(!strstr(line,"mixrms 0.000125 0.000250 0.000375 0.000500 0.000625 0.000750 clip 7 limit_samples 9 flow 6 buffers 3 playing 2 voices 2/3 voice_channels 3 pre_samples 1536 pre_clip 2 pre_limit 4 pre_peak 1.500000000 out_over 0 out_clip 0 out_peak 0.890000000"))return 1;
   ++n;
 }fclose(f);if(calls!=2 || n!=2)return 4;
 snprintf(path,sizeof path,"%s/frame_times.tsv",argv[1]);f=fopen(path,"r");if(!f)return 1;
 unsigned long long tick,frame;unsigned state;n=0;
 while(fscanf(f,"%llu\t%llu\t%u",&tick,&frame,&state)==3){
  if(n>=3 || tick!=1000000000ull+n*500000000ull || frame!=10+n*10 || state!=6)return 1;
  ++n;
 }fclose(f);if(n!=3)return 1;
 printf("PRIVATE MIX PASS lines=2 shared_meter_calls=%u frame_timestamps=%u channels=6 buffers=3 playing=2\n",calls,n);return 0;
}
'''
    with tempfile.TemporaryDirectory(prefix='private-mix-') as td:
        root = Path(td)
        shared_stats(fixture, root)
        for broken in ('good', 'meter', 'voices', 'timestamps', 'precision', 'audio-stats'):
            source = fixture
            if broken == 'meter':
                source = source.replace('int have=dsound_mix_rms(rms,&clipped,&limited,NULL);', 'int have=0;')
            if broken == 'voices':
                source = source.replace('M8(v+0x69u)', 'M8(v+0x68u)')
            if broken == 'timestamps':
                source = source.replace('if(private_frame_times)fprintf', 'if(0)fprintf')
            if broken == 'audio-stats':
                source = source.replace('private_carbon_audio_stats(ac,ap);', '(void)ac;(void)ap;')
            if broken == 'precision':
                source = source.replace('%.6f', '%.3f')
            path = root / 'mix.c'
            path.write_text(source)
            result = subprocess.run(['clang', '-O1', '-fsanitize=address,undefined', str(path), '-o', str(root/'test')], capture_output=True, text=True)
            if result.returncode:
                raise RuntimeError(result.stderr[-2000:])
            result = subprocess.run([str(root/'test'), td], capture_output=True, text=True)
            print(broken + f': exit={result.returncode} ' + result.stdout.strip())
            assert result.returncode == (0 if broken == 'good' else 1), result.stderr
        # An unrecognised image has no decoded mixer binding.
        wrong = fixture.split('int main(', 1)[0].replace(
            '#define PRIVATE_CARBON_SKIPFE 1', '#define PRIVATE_CARBON_SKIPFE 0') + r'''
int main(int argc, char **argv) {
    if (argc != 2) return 2;
    private_mix_init(argv[1]);
    private_mix_frame(10);
    fflush(private_mix_file); fflush(private_frame_times);
    int failed = calls != 0 || ftell(private_mix_file) != 0 || ftell(private_frame_times) != 0;
    fclose(private_mix_file); fclose(private_frame_times);
    return failed;
}
'''
        for broken in (False, True):
            source = wrong.replace('#if PRIVATE_CARBON_SKIPFE', '#if 1') if broken else wrong
            path = root / 'wrong-image.c'; path.write_text(source)
            result = subprocess.run(['clang', '-O1', '-fsanitize=address,undefined',
                                     str(path), '-o', str(root/'wrong-image')], capture_output=True, text=True)
            assert result.returncode == 0, result.stderr[-2000:]
            result = subprocess.run([str(root/'wrong-image'), td], capture_output=True, text=True)
            assert result.returncode == int(broken), result.stderr
            print('wrong-image' + (' broken guard' if broken else '') + f': exit={result.returncode}')



if __name__ == '__main__':
    main()
