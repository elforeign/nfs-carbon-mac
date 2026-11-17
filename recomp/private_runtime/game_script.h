#include "carbon_fe_control.h"
#include "carbon_soak.h"

static void carbon_script_press(const char *name, int down, uint64_t real_frame) {
    if (diag_on) carbon_script_key_witness();
    /* A62064: retail GAME_ACTION_CREWDEFENSIVE keyboard binding, DIK_RCONTROL. */
    if (!strcmp(name, "RCTRL")) {
        key_event(focus_hwnd, 0xA3, 0x9D, down, 0);
        if (diag_on) diag_event("scripted key RCTRL %s", down ? "down" : "up");
        return;
    }
    press(name, down, real_frame);
}

static void script_seq(const char *spec, uint64_t real_frame, uint64_t draws) {
    carbon_soak_screen();
    if (diag_on) carbon_script_dialog_witness(0);
    static int step = 0, sequence_failed;
    if(sequence_failed)return;
    static uint64_t step_start = 0, last_draws = ~0ull, same_since = 0, release_at = 0;
    static char held[16];
    // script clock: 1/60 s ticks of wall time; in a race with NFS_LOCKSTEP one tick of the sim rate per frame, so a slow
    // frame can't shorten a step (pacing.c)
    static uint64_t wall_ns, prev_ns;
    uint64_t now_ns = host_ticks();
    if (!prev_ns) prev_ns = now_ns;
    wall_ns += now_ns - prev_ns;
    prev_ns = now_ns;
    uint64_t frame = 1 + wall_ns * 60 / 1000000000ull;
    if (release_at && frame >= release_at) {
        float diag_car_speed(void);
        if (!strcmp(held, "pad")) { script_pad = script_raw = 0; script_axis[0] = 0; if (diag_on) diag_event("scripted pad up"); }
        else if (!strcmp(held, "pad2")) { script_pad2 = script_raw2 = 0; script_axis2[0] = 0; }
        else if (!strcmp(held, "triggers")) {
            script_trigger_pair = 0; script_lt = script_rt = 0; ++script_trigger_step;
            if (diag_on) diag_event("scripted padtriggers up");
            release_at = 0;
            return;                       // give the released pair its own device poll
        }
        else carbon_script_press(held, 0, real_frame);
        release_at = 0;
    }
    if (draws != last_draws) { same_since = frame; last_draws = draws; }
    uint64_t same = frame - same_since;
    if (release_at) return;
    // find step `step`
    const char *p = spec;
    for (int k = 0; k < step && p; ++k) { p = strchr(p, ','); if (p) ++p; }
    if (!p || !*p) {
        // Strict runs end with their script (a menu left open sits in view until the guard); a driving run ends by itself.
        static uint64_t ended_at;
        const char *st = getenv("BOOT_KEYS_STRICT");
        if (st && !strcmp(st, "1") && !getenv("BOOT_AUTODRIVE") && !getenv("BOOT_RACE")) {
            if (!ended_at) ended_at = frame;
            if (frame - ended_at >= 120) {
                fprintf(stderr, "scripted keys: script ended, closing (strict)\n");
                if (diag_on) diag_event("scripted keys: script ended, closing (strict)");
                [NSApp terminate:nil];   // the menu's quit path
            }
        }
        return;
    }
    char tok[128];
    int n = 0;
    while (p[n] && p[n] != ',' && n < 127) { tok[n] = p[n]; ++n; }
    tok[n] = 0;
    if (!step_start) step_start = frame;
    if (!strncmp(tok, "skipmovies", 10)) {
        fprintf(stderr, "private input: unsupported MW script step %s\n", tok);
        if (diag_on) diag_event("private input: unsupported MW script step %s", tok);
        exit(2);
    } else if (!strncmp(tok, "unfocus:", 8) || !strncmp(tok, "hide:", 5)) {
        // Focus loss for N seconds: unfocus = another app takes over (Cmd-Tab), hide = Cmd-H (off screen too). The
        // window's delegate gets the focus changes directly (AppKit won't activate an app the user isn't using);
        // the game stops drawing while inactive, so the way back is timed, not counted in frames.
        Win *w = win(focus_hwnd);
        if (w && w->ns) {
            int hide = tok[0] == 'h';
            GameWindowDelegate *d = (GameWindowDelegate *)w->ns.delegate;
            if (hide) [NSApp hide:nil];
            [d windowDidResignKey:nil];
            dispatch_after(dispatch_time(DISPATCH_TIME_NOW, (int64_t)(atof(strchr(tok, ':') + 1) * 1e9)), dispatch_get_main_queue(), ^{
                if (hide) [NSApp unhide:nil];
                [d windowDidBecomeKey:nil];
            });
        }
        if (diag_on) diag_event("script: %s", tok);
        ++step; step_start = 0;
    } else if (!strncmp(tok, "carnm:", 6)) {
        fprintf(stderr, "private input: unsupported MW script step %s\n", tok);
        if (diag_on) diag_event("private input: unsupported MW script step %s", tok);
        exit(2);
    } else if (!strncmp(tok, "flake:", 6)) {
        fprintf(stderr, "private input: unsupported MW script step %s\n", tok);
        if (diag_on) diag_event("private input: unsupported MW script step %s", tok);
        exit(2);
    } else if (!strcmp(tok, "cliprec")) {   // test only: the F10 Video clip row's action (start, or stop and save)
        void cliprec_action(int unused), cliprec_status(char *buf, int size);
        char st[160]; cliprec_status(st, sizeof st);
        cliprec_action(0);
        if (diag_on) diag_event("script: cliprec (row was \"%s\")", st);
        ++step; step_start = 0;
    } else if (!strncmp(tok, "sweep:", 6)) {
        void live_picture_sweep_step(const char *phase);
        live_picture_sweep_step(tok + 6);
        ++step; step_start = 0;
    } else if (!strcmp(tok, "livego")) {   // test only: Go live to the loopback fake ingest (NFS_TEST_LIVE_FAKE, live_fake.m)
        void live_fake_go(void);
        if (diag_on) live_fake_go();
        if (diag_on) diag_event("script: livego");
        ++step; step_start = 0;
    } else if (!strcmp(tok, "replayarm") || !strcmp(tok, "replaysave")) {
        void replay_arm_action(int), replay_save_action(int);
        if(!strcmp(tok,"replayarm")) replay_arm_action(0); else replay_save_action(0);
        if(diag_on) diag_event("script: %s",tok);
        ++step; step_start=0;
    } else if (!strncmp(tok, "gameplay:", 9)) {
        int carbon_addons_gameplay_script(const char *);
        if (diag_on && carbon_addons_gameplay_script(tok+9)) { ++step; step_start=0; }
        else if (frame-step_start >= 1800) {
            const char *strict=getenv("BOOT_KEYS_STRICT");
            if (strict && !strcmp(strict,"1")) {
                sequence_failed=1;
                if (diag_on) diag_event("script: gameplay action unavailable; input stopped");
                [NSApp terminate:nil];
            }
        }
    } else if (!strncmp(tok, "set:", 4)) {   // private diagnostics only: an F10 row set live, "set:graphics.look_reflections=pc"
#ifndef NFS_PUBLIC
        if (diag_on) {
            char id[96], *eq = strchr(tok + 4, '=');
            Setting *row = NULL;
            if (eq && (size_t)(eq - tok - 4) < sizeof id) {
                snprintf(id, sizeof id, "%.*s", (int)(eq - tok - 4), tok + 4);
                row = settings_find(id);
            }
            int v = -1;
            if (row) { for (int i = 0; i < row->nchoices || (row->type == SET_TOGGLE && i < 2); ++i) {
                char sp[32]; const char *l = row->values ? row->values[i] : row->choices ? row->choices[i] : i ? "on" : "off";
                snprintf(sp, sizeof sp, "%s", l); if (!strcasecmp(sp, eq + 1)) { v = i; break; } } }
            int changed = row && v >= 0 ? settings_set(row, v) : -1;
            diag_event("script: %s -> %d", tok, changed);
        }
#endif
        ++step; step_start = 0;
    } else if (!strcmp(tok, "shot")) {
        diag_shot_request(real_frame + 3);   // a full-size frame shot a few frames on (diag runs)
        if (diag_on) diag_event("script: shot of frame %llu", (unsigned long long)real_frame + 3);
        ++step; step_start = 0;
    } else if (!strncmp(tok, "mousemove:", 10)) {
        // A mouse movement of DX,DY pixels over the window (scripted runs drop real mouse events): the game's
        // WM_MOUSEMOVE and DirectInput deltas, and the input hand-over (prompts_mouse_moved).
        int dx = 0, dy = 0;
        sscanf(tok + 10, "%d,%d", &dx, &dy);
        Win *w = win(focus_hwnd);
        if (w) {
            int l, t, r, b;
            frame_insets(w->style, &l, &t, &r, &b);
            mouse_x += dx; mouse_y += dy;
            int cx = mouse_x - w->x - l, cy = mouse_y - w->y - t;
            di_mouse_dx += dx; di_mouse_dy += dy;
            post(hwnd_of(w), 0x0200, 0, ((uint32_t)(int16_t)cy << 16) | (uint16_t)(int16_t)cx);   // WM_MOUSEMOVE
            prompts_mouse_moved((float)(abs(dx) + abs(dy)));
        }
        if (diag_on) diag_event("script: %s", tok);
        ++step; step_start = 0;
    } else if (!strncmp(tok, "cmdopt:", 7)) {
        // A menu shortcut, as the pump hands Cmd keys to the menu bar (scripted runs drop real key events).
        NSString *k = [[NSString stringWithUTF8String:tok + 7] lowercaseString];
        NSEvent *e = [NSEvent keyEventWithType:NSEventTypeKeyDown location:NSZeroPoint
                                 modifierFlags:NSEventModifierFlagCommand | NSEventModifierFlagOption timestamp:0 windowNumber:0
                                       context:nil characters:k charactersIgnoringModifiers:k isARepeat:NO keyCode:0];
        BOOL done = [NSApp.mainMenu performKeyEquivalent:e];
        if (diag_on) diag_event("script: %s %s", tok, done ? "handled by the menu" : "not a menu shortcut");
        ++step; step_start = 0;
    } else if (!strncmp(tok, "padlayout:", 10)) {
        script_layout = !strcasecmp(tok + 10, "auto") ? -1 : !strcasecmp(tok + 10, "xbox");
        if (diag_on) diag_event("script: %s", tok);
        ++step; step_start = 0;
    } else if (!strcmp(tok, "padbindps")) {
        void padbind_test_player_triggers(void);
        padbind_test_player_triggers();
        if (diag_on) diag_event("script: %s", tok);
        ++step; step_start = 0;
    } else if (!strncmp(tok, "padtriggers:", 12)) {
        script_lt = script_rt = 0;
        sscanf(tok + 12, "%f/%f", &script_lt, &script_rt);
        script_lt = fminf(1, fmaxf(0, script_lt)); script_rt = fminf(1, fmaxf(0, script_rt));
        script_trigger_pair = 1; ++script_trigger_step;
        snprintf(held, sizeof held, "triggers");
        const char *hold = strchr(tok + 12, ':');
        release_at = frame + (hold && atoi(hold + 1) > 0 ? (uint64_t)atoi(hold + 1) : 6);
        float diag_car_speed(void);
        if (diag_on) diag_event("scripted %s down", tok);
        ++step; step_start = 0;
    } else if (!strncmp(tok, "pad:", 4) || !strncmp(tok, "padraw:", 7) || !strncmp(tok, "padaxis:", 8) ||
               !strncmp(tok, "pad2:", 5) || !strncmp(tok, "pad2raw:", 8) || !strncmp(tok, "pad2axis:", 9)) {
        int second = tok[3] == '2';
        const char *op = tok + 3 + second;
        if (!second || pad_count() == 2) {
            if (op[0] == ':') *(second ? &script_pad2 : &script_pad) = (uint32_t)strtoul(op + 1, NULL, 0);
            else if (op[0] == 'r') *(second ? &script_raw2 : &script_raw) = (uint32_t)strtoul(op + 4, NULL, 0);
            else snprintf(second ? script_axis2 : script_axis, sizeof script_axis, "%s", op + 5);
        }
        snprintf(held, sizeof held, "%s", second ? "pad2" : "pad");
        const char *hold = strchr(strchr(tok, ':') + 1, ':');   // pad:MASK:N etc.: held N ticks
        release_at = frame + (hold && atoi(hold + 1) > 0 ? (uint64_t)atoi(hold + 1) : 6);
        fprintf(stderr, "boot: scripted %s at frame %llu\n", tok, (unsigned long long)real_frame);
        float diag_car_speed(void);
        if (diag_on) diag_event("scripted %s down", tok);   // gate.sh's pad smoke check
        void diag_scripted_key(uint64_t frame);
        diag_scripted_key(real_frame);
        ++step; step_start = 0;
    } else if (!strncmp(tok, "sim:", 4)) {
        fprintf(stderr, "private input: unsupported MW script step %s\n", tok);
        if (diag_on) diag_event("private input: unsupported MW script step %s", tok);
        exit(2);
    } else if (!strncmp(tok, "padtype:", 8)) {   // BOOT_PAD=sim's identity from now on (a controller-type change)
        sim_kind = kind_of_word(tok + 8);
        if (diag_on) diag_event("script: %s", tok);
        ++step; step_start = 0;
    } else if (!strncmp(tok, "underglow:", 10)) {
        int underglow_ui_step(const char *, uint64_t, const char *, const char **);
        const char *key = NULL;
        int result = underglow_ui_step(tok + 10, frame - step_start, fe_package_in_control(), &key);
        if (result < 0) { sequence_failed = 1; return; }
        if (result > 0) { ++step; step_start = 0; }
        else if (key) {
            carbon_script_press(key, 1, real_frame);
            snprintf(held, sizeof held, "%s", key);
            release_at = frame + 4;
        }
    } else if (!strncmp(tok, "soak:", 5)) {
        const char *key = NULL;
        if (strchr(p, ',') || (n == 127 && p[n])) {
            carbon_soak_error("soak must be the last step with a complete file path");
            sequence_failed = 1; return;
        }
        if (carbon_soak_tick(tok + 5, frame, &key) < 0) { sequence_failed = 1; return; }
        if (key) {
            carbon_script_press(key, 1, real_frame);
            snprintf(held, sizeof held, "%s", key);
            release_at = frame + 4;
        }
    } else if (!strncmp(tok, "pkg:", 4)) {
        static uint64_t last_pkg_key;
        char want[32], *key;
        snprintf(want, sizeof want, "%s", tok + 4);
        if ((key = strchr(want, ':'))) *key++ = 0;
        const char *ctl = carbon_script_package_in_control();
        static int strict = -1;
        if (strict < 0) { const char *v = getenv("BOOT_KEYS_STRICT"); strict = v && !strcmp(v, "1"); }
        int result = script_pkg_result(ctl, want, frame - step_start, strict);
        if (result < 0) {
            sequence_failed = 1;
            fprintf(stderr, "script: package timeout want=%s actual=%s; input stopped\n", want, ctl ? ctl : "none");
            if (diag_on) diag_event("script: package timeout want=%s actual=%s; input stopped", want, ctl ? ctl : "none");
            [NSApp terminate:nil];   // strict only (script_pkg_result): a timed-out package ends the run
            return;
        }
        if (result > 0) {
            if (diag_on) carbon_script_dialog_witness(1);
            if (diag_on) diag_event("script step %d %s done after %llu frames (%s)", step, tok, (unsigned long long)(frame - step_start), ctl ? ctl : "none");
            ++step; step_start = 0;
        } else if (key && frame - step_start >= 150 && frame - last_pkg_key >= 150) {
            last_pkg_key = frame;
            carbon_script_press(key, 1, real_frame);
            snprintf(held, sizeof held, "%s", key);
            release_at = frame + 4;
        }
    } else if (!strncmp(tok, "race:", 5)) {
        fprintf(stderr, "private input: unsupported MW script step %s\n", tok);
        if (diag_on) diag_event("private input: unsupported MW script step %s", tok);
        exit(2);
    } else if (!strncmp(tok, "frame:", 6)) {
        if (real_frame >= strtoull(tok + 6, NULL, 10)) { ++step; step_start = 0; }
    } else if (!strncmp(tok, "wait:", 5)) {
        if (frame - step_start >= (uint64_t)atoi(tok + 5)) { ++step; step_start = 0; }
    } else if (!strncmp(tok, "idle:", 5)) {
        uint64_t want = (uint64_t)atoi(tok + 5);
        if ((same >= want && draws > 2) || frame - step_start >= 20 * want) {
            if (diag_on) diag_event("script step %d %s done after %llu frames", step, tok, (unsigned long long)(frame - step_start));
            ++step; step_start = 0;
        }
    } else {
        carbon_script_press(tok, 1, real_frame);
        snprintf(held, sizeof held, "%s", tok);
        release_at = frame + 4;
        ++step; step_start = 0;
    }
}

/* The caller's frame/key-file forms use the same diagnostic edge observer. */
#define press carbon_script_press
