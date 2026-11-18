#include "blackbox.h"
#include "host.h"
#include <stdlib.h>
#include "private_frame_shots.h"
#include "game_image.h"
#include "private_mix_stats.h"
// diag.c - diagnostic mode: one run records everything needed to diagnose it afterwards.
//
//   BOOT_DIAG=<dir> ./boot <game>
//
// <dir>/events.log     every import and host (COM) call: frame, thread, name, arguments, result, call site
// <dir>/frames.log     one line per frame: draws, time, bump heap; game-flow state changes
// <dir>/calls.txt      calls per import and per COM method so far (rewritten every 30 s), e.g. to see which stubs run
// <dir>/mem.log        every 10 s: rss, footprint, malloc, Metal allocations, the guest heaps, Metal copies by kind, render
//                      caches, the guest's D3D objects by kind (live/retired/with a Metal copy, guest MB)
// <dir>/stats.log      once a second: fps, frame time p50/p99/max, process RSS, bump/resource/game heap use and
//                      high-water marks, live GPU textures/buffers, mix RMS per channel (FL FR C LFE BL BR), game-flow state (3 front end, 6 racing),
//                      the game's shared string pool (sstr: strings, bytes of 32768, peaks), the DualSense's adaptive trigger modes and lightbar colour as last decided (padfx.m). BOOT_DIAG_DRAWS also takes
//                      race+N: N frames after the game-flow state first becomes 6, sim+S: the frame after the race's
//                      sim time passes S s (as BOOT_DIAG_SIMSHOTS), key+N: N frames after the last
//                      scripted key press (BOOT_KEYS), e.g. a fixed time after a scripted menu change, probe: the
//                      base and signature passes of BOOT_DIAG_PROBE (probe.m), e.g. the forced-shadow frame.
// <dir>/frame_NNNNN.png  the back buffer every BOOT_DIAG_SHOT_EVERY frames (default 300), and for the frames in
//                      BOOT_DIAG_SHOTS=f1,race+N,...
// <dir>/draws_NNNNN.txt  every draw of the frames in BOOT_DIAG_DRAWS=f1,f2,... (state, shaders, textures)
// <dir>/tex_NNNNN/     the textures those frames sample
// <dir>/stall_N.txt    a frame late by BOOT_DIAG_STALL ms (default 500, after frame 600; at most 5): same contents
// <dir>/hang_N.txt     no frame for BOOT_DIAG_HANG seconds (default 5): every game thread's host backtrace
//                      and the last events (guest registers/stacks and symbol names are unsupported); a hang that
//                      lasts is reported again 10 s and 20 s later (a loop shows different stacks)
// <dir>/hd_compare/   X360 HD texture validation: PC texture | X360 level at the PC size, one PNG per texture hash
// <dir>/timeline.log  loading and the race start in game time: events, messages, sim tasks, milestones (below)
// <dir>/profile_N.txt  where the game thread spent a frame slower than BOOT_DIAG_PROFILE ms (default 100)
// <dir>/profile_session.txt  where the game thread spent the whole session (diag_profile.h)
// <dir>/probe.txt      BOOT_DIAG_PROBE=<features>: does each render feature's output reach the presented frame (probe.m)
// <dir>/crash.txt      the same on a crash, a stop on an unimplemented import/method, or a runtime error
//
// The last 64k events are always kept in memory (cheap) and written into hang/crash reports.
#include "temporal_state.h"
#include <CoreGraphics/CoreGraphics.h>
#include <ImageIO/ImageIO.h>
#include <ctype.h>
#include <dlfcn.h>
#include <mach/mach.h>
#include <malloc/malloc.h>
#include <math.h>
#include <execinfo.h>
#include <pthread.h>
#include <signal.h>
#include <stdarg.h>
#include <stdlib.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

#include "host.h"
#include "diag_car.h"
#include "underglow_render.h"
#include "underglow_light.h"
#include "framelate.h"

int diag_on;
int diag_fixed_step;
const char *diag_dir;
static FILE *events_f, *frames_f;
static uint64_t frame_now, last_frame_ns;
static int idle_now;                     // diag_idle
static int exiting;
void diag_profile_session_write(void);   // diag_profile.h
void diag_begin_exit(void) { __atomic_store_n(&exiting, 1, __ATOMIC_RELEASE); diag_profile_session_write(); }
static int shot_every = 3600;            // periodic overview shots (frame_NNNNN.jpg, small); 0 = none
static FILE *timeline_f;                 // timeline.log (below)
static float timeline_race0 = -1, timeline_secs = 60;
void diag_timeline(const char *fmt, ...) __attribute__((format(printf, 1, 2)));
static void diag_warp_init(void);

// ---------------- symbols: the game's function names (decomp/functions.tsv) ----------------
typedef struct { uint32_t addr; char *name; } Sym;
static Sym *syms;
static int nsyms;
static pthread_once_t symbols_once = PTHREAD_ONCE_INIT;
static char symbols_path[1200];
static void load_symbols_once(void) { /* Unsupported engine diagnostic. */ }
static void load_symbols(void) { /* Unsupported engine diagnostic. */ }
// BGRA8 pixels (rows `pitch` bytes apart) to a PNG. keep_alpha 0 for render targets and the back buffer, whose
// alpha D3D9 doesn't display (often 0 where draws mask it out).
// A path ending in .jpg writes an overview: scaled down to at most 960 pixels wide, JPEG quality 0.8 (~50-100 KB
// instead of several MB at 4K); anything else is a full-size PNG.
void diag_png(const char *path, const void *bgra, uint32_t w, uint32_t h, uint32_t pitch, int keep_alpha) {
    diag_capture_begin();
    size_t n = strlen(path);
    int small = n > 4 && !strcmp(path + n - 4, ".jpg");
    CGColorSpaceRef cs = CGColorSpaceCreateDeviceRGB();
    CGContextRef ctx = CGBitmapContextCreate((void *)bgra, w, h, 8, pitch, cs,
                                             (keep_alpha ? kCGImageAlphaPremultipliedFirst : kCGImageAlphaNoneSkipFirst) | kCGBitmapByteOrder32Little);
    CGImageRef img = ctx ? CGBitmapContextCreateImage(ctx) : NULL;
    if (img && small && w > 960) {
        size_t sw = 960, sh = (size_t)h * 960 / w;
        CGContextRef s = CGBitmapContextCreate(NULL, sw, sh, 8, 0, cs, kCGImageAlphaNoneSkipFirst | kCGBitmapByteOrder32Little);
        if (s) {
            CGContextSetInterpolationQuality(s, kCGInterpolationMedium);
            CGContextDrawImage(s, CGRectMake(0, 0, (CGFloat)sw, (CGFloat)sh), img);
            CGImageRelease(img);
            img = CGBitmapContextCreateImage(s);
            CGContextRelease(s);
        }
    }
    CFURLRef url = CFURLCreateFromFileSystemRepresentation(NULL, (const UInt8 *)path, (CFIndex)n, false);
    CGImageDestinationRef dst = img ? CGImageDestinationCreateWithURL(url, small ? CFSTR("public.jpeg") : CFSTR("public.png"), 1, NULL) : NULL;
    if (dst) {
        float quality = 0.8f;
        CFNumberRef q = CFNumberCreate(NULL, kCFNumberFloatType, &quality);
        const void *k[1] = {kCGImageDestinationLossyCompressionQuality}, *v[1] = {q};
        CFDictionaryRef opt = small ? CFDictionaryCreate(NULL, k, v, 1, &kCFTypeDictionaryKeyCallBacks, &kCFTypeDictionaryValueCallBacks) : NULL;
        CGImageDestinationAddImage(dst, img, opt);
        CGImageDestinationFinalize(dst);
        if (opt) CFRelease(opt);
        CFRelease(q);
        CFRelease(dst);
    }
    if (img) CGImageRelease(img);
    if (ctx) CGContextRelease(ctx);
    CFRelease(url);
    CGColorSpaceRelease(cs);
    diag_capture_end();
}

const char *diag_symbol(uint32_t a, uint32_t *off) { if(off)*off=0;return NULL; }

// ---------------- reports ----------------
#include "diag_threads.h"

void threads_wait_desc(uint32_t tid, char *buf, size_t n);   // threads.c
static void guest_state(FILE *f, Cpu *c, uint32_t tid) { /* Unsupported engine diagnostic. */ }
// Writes host backtraces for all game threads and the event ring; guest state is unsupported.
void diag_report(const char *file, const char *why) {
    // Exit can begin after the watchdog sampled time.
    if (__atomic_load_n(&exiting, __ATOMIC_ACQUIRE) &&
        (!strncmp(file, "hang", 4) || !strncmp(file, "stall", 5))) return;
    extern void diag_flush(void);
    char path[4096];
    snprintf(path, sizeof path, "%s/%s", diag_dir ? diag_dir : userdata_dir(), file);
    FILE *f = fopen(path, "w");
    if (!f) return;
    fprintf(f, "%s\nframe: %llu\n",
            why, (unsigned long long)__atomic_load_n(&frame_now, __ATOMIC_ACQUIRE));
    blackbox_export(f, !strncmp(file, "stall", 5) ? BB_STALL : !strncmp(file, "hang", 4) ? BB_HANG : BB_CRASH);
    report_f = f;
    fprintf(f, "\n-- reporting thread --\n");
    write_backtrace(f);
    Cpu *cpus[64];
    uint32_t tids[64];
    report_thread_backtraces(cpus, tids);
    dump_ring(f, 4000);
    report_f = NULL;
    fclose(f);
    diag_flush();
    if (!strcmp(file, "crash.txt") || !strncmp(file, "hang", 4)) report_auto(why, path);
}

static void crash_signal(int sig) { /* Unsupported engine diagnostic. */ }

// ---------------- game-thread CPU profiles: profile_N.txt, profile_session.txt ----------------
#include "diag_profile.h"

// ---------------- GIL waits: gilwait.log ----------------
// When the game thread waits >= BOOT_DIAG_GILWAIT ms (default 10) for the guest lock, one entry: where it waited,
// which guest thread held the lock (start address), for how long, the import/COM call it was in, and its host stack
// sampled every ~1 ms from 3 ms into the wait (recompiled guest functions show as f_00XXXXXX + the game symbol).
extern GilRec *volatile gil_holder;
extern volatile uint64_t gil_main_wait_since;
extern volatile void *gil_main_wait_site;
uint32_t threads_start_of(uint32_t tid);
#define GW_SAMPLES 1024
#define GW_DEPTH 40
static void *gw_pcs[GW_SAMPLES][GW_DEPTH];
static uint8_t gw_depth[GW_SAMPLES];
static uint32_t gw_tid[GW_SAMPLES];
static const char *gw_imp[GW_SAMPLES];
static float gw_imp_ms[GW_SAMPLES], gw_held_ms[GW_SAMPLES];
static void *gw_buf[64];
static volatile int gw_n, gw_done;
static uint64_t gw_t0;
static FILE *gw_f;
static void gw_signal(int sig) { /* Unsupported engine diagnostic. */ }
static void gw_write(uint64_t since, uint64_t end, void *site, int n, uint64_t frame) { /* Unsupported engine diagnostic. */ }
static void *gil_watch(void *p) { /* Unsupported engine diagnostic. */ return (void *){0}; }

// ---------------- hang monitor ----------------
static void *hang_monitor(void *p) {
    (void)p;
    int secs = getenv("BOOT_DIAG_HANG") ? atoi(getenv("BOOT_DIAG_HANG")) : 5;
    int stall_ms = getenv("BOOT_DIAG_STALL") ? atoi(getenv("BOOT_DIAG_STALL")) : 500;
    int reports = 0, stalls = 0, same_hang = 0;
    uint64_t reported_at = 0, stall_at = 0, last_report = 0;
    for (unsigned tick = 1;; ++tick) {
        profile_wait_100ms();
        uint64_t last, late = diag_capture_late(&last);
        uint64_t frame = __atomic_load_n(&frame_now, __ATOMIC_ACQUIRE);
        if (stall_ms > 0 && !diag_is_idle() && frame > 600 &&
            late > (uint64_t)stall_ms * 1000000ull && stall_at != last && stalls < 5) {
            stall_at = last;
            char file[64], why[128];
            snprintf(file, sizeof file, "stall_%d.txt", ++stalls);
            snprintf(why, sizeof why, "stall: no frame for %d ms after frame %llu (%.0f ms since it)",
                     stall_ms, (unsigned long long)frame, late / 1e6);
            diag_report(file, why);
        }
        if (tick % 10) continue;
        late = diag_capture_late(&last);
        uint64_t now = host_ticks();
        frame = __atomic_load_n(&frame_now, __ATOMIC_ACQUIRE);
        if (!diag_is_idle() && late > (uint64_t)secs * 1000000000ull &&
            (reported_at != last || (same_hang < 3 && now - last_report > 10000000000ull)) && reports < 6) {
            same_hang = reported_at == last ? same_hang + 1 : 1;
            reported_at = last;
            last_report = now;
            char file[64], why[128];
            snprintf(file, sizeof file, "hang_%d.txt", ++reports);
            snprintf(why, sizeof why, "hang: no frame for %d s after frame %llu", secs, (unsigned long long)frame);
            diag_report(file, why);
        }
    }
    return NULL;
}

// ---------------- frames ----------------
#define GAMEFLOW_STATE 0x00925E90u       // TheGameFlowManager's state: 3 in the front end, 6 racing
static uint64_t race_frame;              // first frame in state 6 (0: not yet)
static uint64_t key_frame;               // frame of the last scripted key press (0: none yet)
static float sim_prev = -1, sim_cur = -1;  // race sim time (s) at the last two diag_frame calls (-1: not racing yet)
void diag_scripted_key(uint64_t frame) { /* Unsupported engine diagnostic. */ }
void diag_mark_key(void) { /* Unsupported engine diagnostic. */ }   // test switches that count as a key press (x360.m)

int diag_frame_wanted(uint64_t frame, const char *list_env) {
    // Environment lists are fixed for the session. Cache by name, including absent lists.
    typedef struct FrameList {
        struct FrameList *next;
        const char *value;
        uint64_t frame, race, key;
        int valid, answer;
        char name[];
    } FrameList;
    static FrameList *lists;
    FrameList *list = lists;
    for (; list; list = list->next) if (!strcmp(list->name, list_env)) break;
    if (!list) {
        list = malloc(sizeof *list + strlen(list_env) + 1);
        if (!list) return private_frame_wanted(frame, list_env);
        strcpy(list->name, list_env);
        list->value = getenv(list_env);
        list->valid = 0;
        list->next = lists;
        lists = list;
    }
    if (list->valid && list->frame == frame && list->race == race_frame && list->key == key_frame)
        return list->answer;
    list->frame = frame; list->race = race_frame; list->key = key_frame;
    list->valid = 1; list->answer = 0;
    // Same absolute-frame grammar as private_frame_wanted (':' ends a sequence list).
    const char *p = list->value;
    while (p && *p && *p != ':') {
        char *end;
        unsigned long long n = strtoull(p, &end, 10);
        if (end == p) return 0;
        if (n == frame && (!*end || *end == ',' || *end == ':')) return list->answer = 1;
        if (*end != ',') return 0;
        p = end + 1;
    }
    return 0;
}
// The common draw/COM path reads only a cached flag. Key marks can occur
// within a frame, so retain the frame-list parser's race/key invalidation.
int diag_draw_frame_wanted(uint64_t frame) {
    static int initialized, enabled, wanted;
    static uint64_t cached = ~0ull;
    if (!diag_on) return 0;
    if (!initialized) {
        const char *list = getenv("BOOT_DIAG_DRAWS");
        enabled = list && *list;
        initialized = 1;
    }
    if (!enabled) return 0;
    if (cached != frame) {
        wanted = private_frame_wanted(frame, "BOOT_DIAG_DRAWS");
        cached = frame;
    }
    return wanted;
}
// BOOT_DIAG_SIMSHOTS=s1,s2,...: the back buffer when the race's sim time (Sim::GetTime since the race started)
// passes each value, written as simshot_<s>.png. Runs at different frame or tick rates compare at equal game time.
int diag_simshot_due(char *path, size_t n) {
    static const char *list;
    static int initialized;
    if(!diag_on)return 0;
    if(!initialized){list=getenv("BOOT_DIAG_SIMSHOTS");initialized=1;}
    if(!list || !*list || M32(0x00A99BBCu)!=6)return 0;
    float now=MF32(0x00B4CFD8u);
    char *end;float want=strtof(list,&end);
    if(end==list || !isfinite(want) || !isfinite(now) || now<want)return 0;
    snprintf(path,n,"%s/simshot_%06.2f.png",diag_dir,want);
    while(*end==',' || *end==' ')++end;
    list=end;
    if(events_f)fflush(events_f);
    diag_event("simshot: sim=%.6f requested=%.6f",now,want);
    return 1;
}
// Frames asked for by the runtime itself (test switches that capture at moments found while running).
static uint64_t shot_req[32];
static int nshot_req;
void diag_shot_request(uint64_t frame) { if (nshot_req < 32) shot_req[nshot_req++] = frame; }
// 2: a frame asked for with BOOT_DIAG_SHOTS or diag_shot_request (full-size PNG), 1: a periodic overview (small
// JPEG), 0: none.
int diag_shot_due(uint64_t frame) {
    if (diag_on) for (int i = 0; i < nshot_req; ++i) if (shot_req[i] == frame) return 2;
    return private_shot_due(frame);
}

// Allocator counters: weak defaults (0 = not tracked); an allocator overrides them with its own definitions.
__attribute__((weak)) uint32_t gmalloc_used(void) { /* Unsupported engine diagnostic. */ return (uint32_t){0}; }
__attribute__((weak)) uint32_t heap_used(void) { /* Unsupported engine diagnostic. */ return (uint32_t){0}; }
__attribute__((weak)) void vinyls_live(uint32_t *nv, uint32_t *mbv, uint32_t *ns, uint32_t *mbs) { /* Unsupported engine diagnostic. */ }

uint64_t diag_idle_ns[IDLE_N];
static uint64_t stats_idle_ns[IDLE_N];   // diag_idle_ns at the start of stats.log's current second
PerfFrame perf_frames[PERF_RING];
volatile uint64_t perf_nframes;
float perf_gpu_ms[PERF_RING];
volatile uint64_t perf_gpu_serial;
void perf_gpu_done(uint64_t serial, double ms) { /* Unsupported engine diagnostic. */ }
static FILE *stats_f;
static float ft[8192];                   // frame times (ms) in the current second
static int nft;
static uint64_t sec_start_ns, sec_start_frame;
static uint32_t peak_bump, peak_gm, peak_heap;
static uint64_t peak_rss;
static int cmp_float(const void *a, const void *b) { /* Unsupported engine diagnostic. */ return (int){0}; }
static uint64_t rss_bytes(void) { /* Unsupported engine diagnostic. */ return (uint64_t){0}; }
uint64_t diag_rss_bytes(void) { /* Unsupported engine diagnostic. */ return (uint64_t){0}; }   // report.m: the session log's perf.tsv
// mem.log, every 10 s: where the process memory is, to tell a working set that plateaus from a leak. rss and
// footprint (what Activity Monitor shows: phys_footprint, includes the GPU memory the process owns); malloc (host
// heap in use, all zones); metal (MTLDevice.currentAllocatedSize: every Metal resource); the guest heaps; render.m's
// Metal copies of guest textures (tex), render targets (rt), MSAA targets, buffers, and its caches (shaders,
// pipelines, depth-stencil and sampler states); the guest's D3D objects by kind (live / retired / with a GPU copy / guest MB).
static FILE *mem_f;
static void mem_second(uint64_t frame, uint64_t now, uint32_t state) { /* Unsupported engine diagnostic. */ }
// The player car's speed in m/s, or -1 when there is none (front end): the sound engine's copy of it, which it keeps
// whoever drives (the player or BOOT_AUTODRIVE's AI): SndCamera::m_PLayerCars[0] (009142D0, NumPlayers 008EF998;
// IsPlayerGoingFastEnough 004DDE10 reads them) -> EAXCar +0x34 EAX_CarState -> velocity at +0x50/54/58
// (EAX_CarState::GetVelocityMagnitude 004AB890; the MPH variant 004AB8C0 scales it by 2.237). Guest memory is mapped
// whole, so a stale pointer reads garbage, not a fault.
float diag_car_speed(void) { /* Unsupported engine diagnostic. */ return (float){0}; }

// The player car's position (EAX_CarState +0x40, as frames.log's car field) and speed; 0 when there is none.
int diag_car_state(float pos[3], float *speed) { /* Unsupported engine diagnostic. */ return (int){0}; }

static void stats_second(uint64_t frame, uint64_t now, uint32_t state) { /* Unsupported engine diagnostic. */ }

// The main thread waiting for messages on purpose (an inactive window, user32.m wait_messages): no stall or hang
// reports meanwhile, and frame times restart when the next frame comes.
void diag_idle(int idle) {
    if (idle == __atomic_load_n(&idle_now, __ATOMIC_ACQUIRE)) return;
    __atomic_store_n(&last_frame_ns, host_ticks(), __ATOMIC_RELEASE);
    __atomic_store_n(&idle_now, idle, __ATOMIC_RELEASE);
    if (diag_on) diag_event(idle ? "main thread idle: waiting for messages" : "main thread drawing again");
}
uint64_t diag_last_frame_ns(void) { return __atomic_load_n(&last_frame_ns, __ATOMIC_ACQUIRE); }
int diag_is_idle(void) {
    return __atomic_load_n(&idle_now, __ATOMIC_ACQUIRE) || __atomic_load_n(&exiting, __ATOMIC_ACQUIRE);
}

// Scripted race characters (BOOT_DIAG, races): GManager::mObj (0x0091E00C) keeps the GCharacters that
// GCharacter::Spawn (00601320) has asked for in a vector at +0x80..+0x84; ServicePendingCharacters (005FDD60) walks it
// and FUN_005FD820 creates each one's PVehicle (state +0x4C: 1 asked, 2 vehicle made, 3 waiting to be placed). The
// drag races' trafficspawntrigger collections spawn their child `character` this way (a traffic car at the trigger's
// position), not through AITrafficManager::SpawnTraffic (00439A10), which is the density-driven ambient traffic.
// Logs each character the first time it is in the list (position, speed) and every change of the list's states.
static void gchar_watch(void) { /* Unsupported engine diagnostic. */ }
void diag_frame(uint64_t frame, uint64_t draws) {
    diag_idle(0);
#if defined(NFS_GAME) && NFS_GAME == NFS_GAME_PRIVATE
    void carbon_unlock_frame(void);
    carbon_unlock_frame();
    void carbon_devrows_frame(void);
    carbon_devrows_frame();
    void carbon_addons_gameplay_frame(void);
    carbon_addons_gameplay_frame();
#endif
    __atomic_store_n(&frame_now, frame, __ATOMIC_RELEASE);
    __atomic_store_n(&last_frame_ns, host_ticks(), __ATOMIC_RELEASE);
    if (!diag_on) return;
    if (!have_game_thread) { game_thread = pthread_self(); have_game_thread = 1; }   // diag_profile.h samples it
    private_mix_frame(frame);
}
uint64_t diag_current_frame(void) { return __atomic_load_n(&frame_now, __ATOMIC_ACQUIRE); }

void diag_init(void) {
    diag_warp_init();
    diag_dir = getenv("BOOT_DIAG");
    if (!diag_dir) return;
    diag_on = 1;
    mkdir(diag_dir, 0755);
    char path[4096];
    snprintf(path, sizeof path, "%s/events.log", diag_dir);
    events_f = fopen(path, "w");
    if (events_f) setvbuf(events_f, NULL, _IOLBF, 0);
    private_mix_init(diag_dir);
    if (getenv("BOOT_DIAG_PROFILE_MAX")) prof_max = atoi(getenv("BOOT_DIAG_PROFILE_MAX"));
    pthread_t t;
    int err = pthread_create(&t, NULL, hang_monitor, NULL);
    if (!err) pthread_detach(t);
    else diag_event("hang monitor start failed: %s", strerror(err));
}
void diag_flush(void) { if (events_f) fflush(events_f); }

// ---------------- NIS car grounding (BOOT_DIAG only) ----------------
// Observe 0044B040 -> 00789870 / 00691110, without issuing another ground query.
// Bounds: 512 samples/actor/play, 16384 samples/run, 64 Load/Play metadata lines/run.
typedef struct {
    float last, sumdt, mindt, maxdt;
    unsigned lines, calls, ground_fail, init_fail;
} NisActor;
typedef struct {
    int due, ground, init, ret, wheels;
    uint32_t control;
    float height, query[3], target[3], pos[3], vy;
} NisSample;
static NisActor nis_actor[16];
static _Thread_local NisSample *nis_capture;
static uint32_t nis_activity, nis_hash;
static char nis_name[64];
static unsigned nis_play, nis_lines, nis_meta;
static int nis_playing;
static uint32_t nis_scratch;             // private guest stack + query/iterator scratch, diag only

// Read-only getters on a CPU copy/private stack preserve the live registers, x87 and caller's stack.
// Never request a load, zone switch or additional ground query.
static uint32_t nis_read(Cpu *c, uint32_t self, uint32_t fn, int n, const uint32_t *args) { /* Unsupported engine diagnostic. */ return (uint32_t){0}; }
static uint32_t nis_header(int section) { /* Unsupported engine diagnostic. */ return (uint32_t){0}; }
static void nis_residency(Cpu *c, const float pos[3], int *zone, int *loaded, char *packs, size_t size) { /* Unsupported engine diagnostic. */ }


// ---------------- timeline: loading and the race start in game time ----------------
// <dir>/timeline.log: every game event the Event queue fires (FUN_00633EF0: vtable[0] of each queued Event, i.e.
// its type), every Hermes message posted (kind and channel CRCs), sim tasks created (rate and delay, in ticks), slow
// resource-loading steps and a few milestones (game-flow states, gameplay begin, NIS play/skip, countdown), each with
// the frame, the sim tick, Sim::GetTime, the time since the race started (the first frame in game-flow state 6),
// wall time and the game's RealTimer/WorldTimer (1/4000 s). Runs at different tick rates line up on these columns:
// whatever starts at a different game time after loading counts ticks or frames somewhere. Racing lines stop 60 s
// into the race (or BOOT_DIAG_TIMELINE=<seconds>; 0 = no timeline).
static int timeline_lines;
int diag_timeline_on(void) { /* Unsupported engine diagnostic. */ return (int){0}; }
void diag_timeline(const char *fmt, ...) { /* Unsupported engine diagnostic. */ }
static const char *timeline_name(uint32_t fn, char *buf, size_t n) { /* Unsupported engine diagnostic. */ return (const char *){0}; }
uint32_t call_guest(Cpu *c, uint32_t fn, int n, const uint32_t *args);
// The Event queue (cdecl, called after every tick and frame): the same loop as the game's, naming each event.
// Hermes::Message::Post(UCrc32 channel) (thiscall; the message's kind CRC at +0)
// Milestones: logged with their caller.
// Car rendering in BOOT_DIAG_DRAWS frames, written into the frame's draw dump (`car:` lines, before the flush that
// draws them): every CarRenderInfo::Render (0074E160: view, flags, reflection flag, LOD range, result) and RenderPart
// (007387E0: the part slot as its offset in the CarRenderInfo, decoded for the body parts table +0xB84 (part x 0x14 +
// LOD x 4), the eModel's name hash, the part matrix's up axis and position), so each view's car parts and LODs show.
unsigned diag_car1[4];   // this frame: view-1 CarRenderInfo::Render calls, true, frame-malloc failed during it; view-4 calls
static inline float car_f32(uint32_t a) { /* Unsupported engine diagnostic. */ return (float){0}; }
FILE *dump_file(void);
void materials_car_diagnostics(Cpu *c) { /* Unsupported engine diagnostic. */ }
void materials_car_part_diagnostics(Cpu *c) { /* Unsupported engine diagnostic. */ }
// Countdown::Update (the HUD's 3-2-1, per HUD update): its first call per HUD and every change of its digit (+0x44)
// FEngHud::DetermineHudFeatures (0057CA60, thiscall, arg IPlayer*; hooked in pacing.c, which calls this after it):
// the HUD's elements (the countdown among them) only update while it returns non-zero. Logs the number of calls per
// HUD at each change of the result, and while it is 0, which of its conditions fail (bits, in the order it tests
// them): 1 player slot, 2 restarting, 4 pause request, 8 Sim state != 3, 0x10/0x20/0x40 Pause_Main/MC_Main/
// PostRace_Results pushed, 0x80 hud-off flag, 0x100 HUD resources not loaded, 0x200 INIS, 0x400 HUD type !=
// FEDatabase's, 0x800 ICE manager, 0x1000 game flow loading; 0x8000: held off by pacing.c (the 60 Hz set-up time).
// c->eax:edx hold the result the game sees; the registers are restored after the checks.
void diag_hud_features(Cpu *c, uint32_t self, uint32_t player, int held) { /* Unsupported engine diagnostic. */ }
// WaitForResourceLoadingComplete (the per-frame step, cdecl): steps over 20 ms, with the first delayed callback it
// ran (DelayedResourceCallbacks 00925688) and the resource list's head (ResourceFileList 009259A4).

// RECOMP_ABICHECK builds: a translated function returned with a callee-saved register or esp changed.
void abi_violation(Cpu *c, uint32_t fn, uint32_t ebx, uint32_t esi, uint32_t edi, uint32_t ebp, uint32_t esp) { /* Unsupported engine diagnostic. */ }

// BOOT_DIAG_STRINGS=1: <dir>/strings.tsv, hash -> string for every distinct SearchForString (0056BB80, the hash in edx,
// pointer in eax) lookup, which the FEng text labels go through (FEngSetLanguageHash 00515C00 -> the label callback). Used to find
// the real label hashes (the LANGUAGES/*.bin offsets don't index the text directly).
void fe_console_search(Cpu *c);

// The game's shared string pool (gSharedStringPool 0090E690: bInitSharedStringPool(0x8000) in InitializeEverything):
// every bFile, queued file, streaming pack and car pack keeps its name there. bSharedStringPool::Allocate (004615A0,
// thiscall (name) -> copy or NULL) returns NULL when no free block fits, and a car's solid pack allocated then keeps a
// NULL name for good (CarLoader::AllocateSolidPack 00752E00). Every failure is logged (name, pool use), with or without
// BOOT_DIAG. A string freed while still referenced reads "" (Free clears its first byte). TEST (local):
// BOOT_TEST_SHAREDSTR_EMPTY=<substring>: the first allocation of a name containing it gets "" instead, as a car pack's
// name freed under it reads (e.g. M3GTRE46\GEOMETRY: the player car's solid pack). BOOT_TEST_SHAREDSTR_FULL=<substring>:
// the first allocation of a name containing it first fills the pool with dummy strings, so it and every new name after
// it fail as in a full pool.
#define SSTR_POOL 0x0090E690u
void sstr_pool_stats(uint32_t *n, uint32_t *peak_n, uint32_t *bytes, uint32_t *peak_bytes, uint32_t *size) { /* Unsupported engine diagnostic. */ }
// bSharedStringPool::Free (004617E0, thiscall (name)): the car packs' names, with the references left (diag only). A
// name freed while a LoadedSolidPack still points at it reads "" (the race-start hang's empty-name open loop).
// TEST (local): BOOT_TEST_SHAREDSTR_POISON=1: a string freed to 0 references keeps its length as '~'s (instead of ""),
// so a later use of the dead name is visible: Allocate logs every "~~~" name with its caller, and opens show it.

// ---------------- race start placement (one-off diagnostic) ----------------
// BOOT_DIAG_WARP=<free-roam sim s>:<x>,<y>,<z>[:dir=<x>,<y>,<z>][:block].
// Position/facing are physics (UMath) coordinates, default facing +x. :block
// is the streaming-only diagnostic, leaving the vehicle where it was.
// Decoded in the private decomp and translated image: 0065B610 is the native
// warp path (GRuntimeInstance*, bool), using 0061AA40/00610900 to read vectors,
// 00764D40 to stream, 007A7E80/006B7890 to wait, then IVehicle +7C to place.
// IVehicle handle 00403D30, vtable 009E4A78 +7C = 006D1100 (ground placement).
// Reuse that path's operations with vectors directly, without fabricating a
// runtime trigger. 0075CF70 reads user mode B4D854; mode 1 takes race-grid placement.
static int diag_warp_state, diag_warp_block;
static float diag_warp_at, diag_warp_p[3], diag_warp_dir[3], diag_warp_race0 = -1, diag_warp_time;
static int diag_warp_parse(const char *e, float *at, float p[3], float d[3]) {
    if (!e || sscanf(e, "%f:%f,%f,%f", at, &p[0], &p[1], &p[2]) != 4) return 0;
    d[0] = 1.0f; d[1] = d[2] = 0.0f;
    const char *h = strstr(e, ":dir=");
    if (h && sscanf(h + 5, "%f,%f,%f", &d[0], &d[1], &d[2]) != 3) return 0;
    if (!isfinite(*at) || *at < 0) return 0;
    for (unsigned i = 0; i < 3; ++i)
        if (!isfinite(p[i]) || !isfinite(d[i])) return 0;
    return d[0] != 0 || d[1] != 0 || d[2] != 0;
}
static void diag_warp_init(void) {
    const char *e = getenv("BOOT_DIAG_WARP");
    diag_warp_state = diag_warp_parse(e, &diag_warp_at, diag_warp_p, diag_warp_dir);
    diag_warp_block = diag_warp_state && strstr(e, ":block") != NULL;
}
static int diag_warp_free_roam(void) {
    uint32_t sm = M32(0x00B4CFE0u), race = M32(0x00A98284u);
    return M32(0x00A99BBCu) == 6 && sm && M32(sm + 0x24) == 3 &&
        !M32(0x00B4D964u) && M32(0x00B4D854u) != 1 && race &&
        !M32(race + 0x6A14) && !M32(race + 0x6A08) && M32(race + 0x6A18) == 3;
}
void diag_warp_pass(Cpu *c) {
    if (!diag_warp_state || !diag_on || !diag_warp_free_roam()) return;
    float now = MF32(0x00B4CFD8u);
    if (!isfinite(now)) return;
    if (diag_warp_race0 < 0) diag_warp_race0 = now;
    if (diag_warp_state == 2) {
        if (now - diag_warp_time < 1) return;
        extern int private_carbon_player_position(float *);
        float render[3];
        if (!private_carbon_player_position(render)) return;
        float x = -render[1], y = render[2], z = render[0];
        float error = hypotf(hypotf(x - diag_warp_p[0], y - diag_warp_p[1]), z - diag_warp_p[2]);
        diag_event("warp: after %.3f sim s position=%.3f,%.3f,%.3f error=%.3f_m", now - diag_warp_time, x, y, z, error);
        diag_shot_request(diag_current_frame() + 1);
        diag_warp_state = 0;
        return;
    }
    if (diag_warp_state != 1 || now - diag_warp_race0 < diag_warp_at) return;
    uint32_t list = M32(0x00A9FF5Cu), count = M32(0x00A9FF64u);
    uint32_t player = list && count == 1 ? M32(list) : 0, vt = player ? M32(player) : 0;
    if (player < 8 || !vt || M32(vt + 4) != 0x0076E810u) return;
    uint32_t sim = M32(player - 8), map = sim ? M32(sim + 4) : 0;
    if (!map) return;
    // Private CPU/stack: guest calls must preserve the interrupted pass, including x87.
    uint32_t scratch = galloc(65536 + 32), vectors = scratch + 65536;
    Cpu warp = *c;
    warp.esp = vectors;
    uint32_t handle = 0x00403D30u;
    warp.ecx = map;
    uint32_t vehicle = call_guest(&warp, 0x0060CB50u, 1, &handle);
    uint32_t vehicle_vt = vehicle ? M32(vehicle) : 0;
    if (!vehicle_vt || M32(vehicle_vt + 0x7C) != 0x006D1100u) {
        diag_warp_state = 0;
        diag_event("warp: unsupported player vehicle; no placement");
        return;
    }
    memcpy(G + vectors, diag_warp_p, sizeof diag_warp_p);
    memcpy(G + vectors + 12, diag_warp_dir, sizeof diag_warp_dir);
    diag_warp_state = 3; // Native loading presents frames; suppress reentry before any guest call.
    diag_event("warp: at free-roam sim %.3f to %.3f %.3f %.3f facing %.3f %.3f %.3f block=%d",
               now - diag_warp_race0, diag_warp_p[0], diag_warp_p[1], diag_warp_p[2],
               diag_warp_dir[0], diag_warp_dir[1], diag_warp_dir[2], diag_warp_block);
    warp.ecx = 0x00B70650u;
    call_guest(&warp, 0x0079A3E0u, 0, NULL);
    uint32_t args[2] = {vectors, 0};
    call_guest(&warp, 0x00764D40u, 2, args);
    for (;;) {
        warp.ecx = 0x00B70650u;
        if (!(call_guest(&warp, 0x007A7E80u, 0, NULL) & 255)) break;
        call_guest(&warp, 0x006B7890u, 0, NULL);
    }
    // The native loading loop pumps input; recheck mode before placing.
    if (!diag_warp_free_roam()) {
        diag_event("warp: left free roam during loading; no placement");
        diag_warp_state = 0;
        return;
    }
    if (!diag_warp_block) {
        args[1] = vectors + 12;
        warp.ecx = vehicle;
        uint32_t placed = call_guest(&warp, 0x006D1100u, 2, args);
        diag_event("warp: SetVehicleOnGround vehicle=%08X result=%u", vehicle, placed & 255);
    }
    diag_warp_time = MF32(0x00B4CFD8u);
    diag_warp_state = 2;
}

// BOOT_DIAG carpack: the car texture loads (split-screen two-car race load, 2026-10-27). LoadAllTexturesFromPack
// 0075B7A0 (CarLoader this, pack name, flag) logs the loader's queued-layer count +AC and state +8; InternalLoadStreamingEntry
// 00500D80 (loader this; load table, pack, entry) logs each entry the pack's hash table hands out (hash, file offset, size,
// flags) with the pack's table +24/+28, and dumps the pack and the entry's neighbours when the size is implausible.
// BOOT_DIAG carpool: the car memory pool in a (split-screen) race. CarLoader+0x64 is the pool size (carved from track pool 7
// by SetMemoryPoolSize), 0x904A00 the pool number; free/largest from bCountFreeMemory 00464050 / bLargestMalloc 00464080.
// Peak use = size - lowest free seen at the logged points; __break 0045CD20 called from RemoveSomethingFromCarMemoryPool
// 00759F00 (nothing left to evict) is the eviction assert.
static uint32_t carpool_stat(Cpu *c, uint32_t fn, uint32_t pool) { /* Unsupported engine diagnostic. */ return (uint32_t){0}; }
static void carpool_log(Cpu *c, const char *what) { /* Unsupported engine diagnostic. */ }
// carpack, second stage: the entry count LoadStreamingEntry 00508560 is asked for (loader; hashes, count, cb, cbarg,
// pool), and the per-skin texture-hash counts that feed LoadAllTexturesFromPack: LoadedSkin::GetTextureHashes 007528D0
// (skin; out, max, flag: RideInfo at skin+8) and CarLoader::AllocateSkinLayers 00753060 (hashes, count, out, room, pack).
// cartex (diag_car.c): car texture hashes two streaming packs hold; a deleted pack frees them for every car.
