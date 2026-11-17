/* Host actions use the same settings store and callbacks as the first image. */
#include "cliprec.h"
#include "stream_key.h"
void report_live(float *, float *, float *);
const char *report_audio_device(void);
int dsound_output_info(const char **, int *, uint64_t *);
static Setting s_replay_arm = {.id="display.replay_arm", .category=SET_DISPLAY, .order=47,
    .label="Replay buffer", .help="Arm or disarm the last 30 seconds of video and stereo sound. Always starts Off. Uses the clip resolution. Video clips and live streaming can share the capture. Disarm leaves other capture actions running.",
    .type=SET_ACTION, .pref="", .apply=replay_arm_action, .value_text=replay_status};
static Setting s_replay_save = {.id="display.replay_save", .category=SET_DISPLAY, .order=48,
    .label="Save last 30 s", .help="Saves the 30 seconds ending when selected to Movies/NFSC. Wait for warm-up; one save at a time. The buffer stays armed.",
    .type=SET_ACTION, .pref="", .apply=replay_save_action, .value_text=replay_save_status};
static const char *const kReplayKey[]={"F8", "F7", "F6"}, *const kReplayKeyV[]={"f8", "f7", "f6"};
static Setting s_replay_key_enabled = {.id="controls.replay_key_enabled", .category=SET_CONTROLS, .order=12,
    .label="Replay save key", .help="Enable the save shortcut. Off initially; arm replay separately in Display. A key assigned in the game's Controls keeps its career binding instead.",
    .type=SET_TOGGLE, .def=0, .env="NFS_REPLAY_KEY_ENABLED"};
static Setting s_replay_key = {.id="controls.replay_key", .category=SET_CONTROLS, .order=13,
    .label="Replay key", .help="F8 by default. Used only when Replay save key is On and this menu is closed. Repeated presses while held save once.",
    .type=SET_CHOICE, .choices=kReplayKey, .values=kReplayKeyV, .nchoices=3, .def=0, .env="NFS_REPLAY_KEY"};
static const char *const kReplayPad[]={"Disabled", "L1 + R1 + L3", "L1 + R1 + R3"}, *const kReplayPadV[]={"off", "l1r1l3", "l1r1r3"};
static Setting s_replay_pad = {.id="controls.replay_pad", .category=SET_CONTROLS, .order=14,
    .label="Replay save chord", .help="Disabled initially. Press all three within 150 ms; hold saves once. Solo buttons retain career actions after a short recognition delay. Menu and Guide shortcuts take priority; release every button after focus loss or reconnect.",
    .type=SET_CHOICE, .choices=kReplayPad, .values=kReplayPadV, .nchoices=3, .def=0, .env="NFS_REPLAY_PAD"};
static const char *const kClipResolution[] = {"1080p", "1440p", "4K"};
static Setting s_clip_resolution = {.id = "display.clip_resolution", .category = SET_DISPLAY, .order = 44,
    .label = "Clip resolution",
    .help = "Next clip; keeps aspect, never enlarges smaller pictures. Approx MB/min (HEVC / H.264): 1080p 75 / 113, 1440p 133 / 200, 4K 300 / 450 at 16:9; smaller pictures use less.",
    .type = SET_CHOICE, .choices = kClipResolution, .nchoices = 3, .def = CLIPREC_DEFAULT_RESOLUTION};

static Setting s_cliprec = {.id = "display.cliprec", .category = SET_DISPLAY, .order = 45, .label = "Video clip",
    .help = "Record SDR video to Movies/NFSC, including with HDR output on. Select to start or stop; select again after saving to record another clip. Stereo game sound; always starts Off.",
    .type = SET_ACTION, .pref = "", .apply = cliprec_action, .value_text = cliprec_status};
static Setting s_clips_open = {.id = "display.clips_open", .category = SET_DISPLAY, .order = 46,
    .label = "Show clips in Finder", .help = "Opens Movies/NFSC in Finder.",
    .type = SET_ACTION, .pref = "", .apply = cliprec_open_folder};

// The key is never a Setting.text value: only constant action/status strings cross this UI.
static Setting s_stream_heading = {.id="display.stream_heading", .category=SET_DISPLAY, .order=60,
    .label="Live streaming", .type=SET_HEADING, .pref=""};
static Setting s_stream_key = {.id="display.stream_key", .category=SET_DISPLAY, .order=61,
    .label="Enter stream key", .help="Opens a secure entry sheet. Save keeps the key in memory until quit. Entering a key does not broadcast.",
    .type=SET_ACTION, .pref="", .apply=stream_key_edit};
static Setting s_stream_forget = {.id="display.stream_forget", .category=SET_DISPLAY, .order=62,
    .label="Forget stream key", .help="Stops live streaming and clears the key from this session.",
    .type=SET_ACTION, .pref="", .apply=stream_key_forget};
static Setting s_stream_go = {.id="display.stream_go", .category=SET_DISPLAY, .order=63,
    .label="Go live", .help="Starts sending video and stereo sound to YouTube using the entered key. Always starts Off; errors require another explicit Go live.",
    .type=SET_ACTION, .pref="", .apply=stream_key_go};
static Setting s_stream_stop = {.id="display.stream_stop", .category=SET_DISPLAY, .order=64,
    .label="Stop live", .help="Stops uploads. Keeps the key until quit or Forget. Recording and replay continue.",
    .type=SET_ACTION, .pref="", .apply=stream_key_stop};
static Setting s_stream_status = {.id="display.stream_status", .category=SET_DISPLAY, .order=65,
    .label="Stream status", .type=SET_INFO, .pref="", .value_text=stream_key_status};

static void audio_now(char *buf, int n) {
    const char *mode = NULL;
    int live = -2;
    uint64_t under = 0;
    if (!dsound_output_info(&mode, &live, &under)) { snprintf(buf, (size_t)n, "no sound device yet"); return; }
    snprintf(buf, (size_t)n, "%s%s%s", live > 0 ? (mode ? mode : "?") : live == 0 ? "silent (NFS_AUDIO=null)" : "waiting for a device",
             live > 0 ? " on " : "", live > 0 ? report_audio_device() : "");
}
static Setting h_perf = {.id = "diag.h_perf", .category = SET_DIAGNOSTICS, .order = 5, .label = "Performance", .type = SET_HEADING,
    .help = "Live readouts of speed and sound; the overlay itself is in Display & performance."};
static void perf_now(char *buf, int n) {
    float fps, p99, gpu;
    report_live(&fps, &p99, &gpu);
    snprintf(buf, (size_t)n, "%.1f fps   p99 %.2f ms   GPU %.2f ms", fps, p99, gpu);
}
static Setting s_perf = {.id = "diag.perf", .category = SET_DIAGNOSTICS, .order = 10, .label = "Last second", .type = SET_INFO,
    .help = "Frame rate, 99th-percentile frame time and GPU time over the last second (the game is frozen while this menu is open in a race).",
    .value_text = perf_now};
static Setting s_audio_now2 = {.id = "diag.audio", .category = SET_DIAGNOSTICS, .order = 20, .label = "Audio output", .type = SET_INFO,
    .help = "The format the game's sound goes out in, and the output device.", .value_text = audio_now};

static void carbon_addons_host_settings_init(void) {
    settings_add(&s_clip_resolution);
    settings_add(&s_cliprec);
    settings_add(&s_clips_open);
    settings_add(&s_replay_arm);
    settings_add(&s_replay_save);
    settings_add(&s_replay_key_enabled);
    settings_add(&s_replay_key);
    settings_add(&s_replay_pad);
    settings_add(&s_stream_heading);
    settings_add(&s_stream_key);
    settings_add(&s_stream_forget);
    settings_add(&s_stream_go);
    settings_add(&s_stream_stop);
    settings_add(&s_stream_status);
    settings_add(&h_perf);
    settings_add(&s_perf);
    settings_add(&s_audio_now2);
}
