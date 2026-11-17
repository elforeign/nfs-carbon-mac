# Host add-ons

Plan: reuse the host Guide, capture, replay and secure live implementations via additive private-target policies. Register Carbon rows with the existing settings store; use the decoded Carbon input context and keyboard binding directory. Share controller note entry and adapt the decoded native field at A604B8 + 27C, preserving its own validators and accept/cancel notifications. Preserve Most Wanted source membership and defaults. Verify staged callbacks with broken controls, both builds, impacted offline checks and guarded Carbon menu/capture runs.

Report submission and Discord require a reviewed Carbon destination and application identity. No Carbon-specific identity was found in the existing declarations; do not invent one or send Carbon status as Most Wanted.

The native text fixture executes eleven translated functions, with 66 passing checks; removing the bridge gives 36 failures and removing generation invalidation gives two. The host fixture has 66,144 passing checks; original Guide/note/binding/context no-ops give 1/5/22,033/1 failures.

The existing supervised game sandbox permits only scratch writes. Carbon capture uses its trusted NFS_GAME_SCRATCH root when present, appending Movies/NFSC; ordinary launches still use the user's Movies/NFSC. The offline fixture verifies both path choices.


## Builds and production checks

Both runtimes build. Carbon: 88 runtime objects, zero unavailable MW hooks, zero MW address reads/writes, 98 approved private accesses (baseline 74 objects / 96 accesses). Regenerated Carbon base archive: 63,179 functions, 63,102 translated, 77 existing undecodable stubs, zero compiler errors; the native text Begin wrapper is present. The three edited shared implementation files (portmenu.m, onscreen_keyboard.c, cliprec.mm) produce exactly the same preprocessed MW tokens as before the change.

The native fixture now has 66 passing checks. Original missing capture gives 36 failures; missing generation invalidation gives two; allowing another controller to take ownership gives one. The capture fixture has 36 moving decoded frames and 28,800 stereo sample frames; a 30.000000-second replay has 1,448,896 decoded stereo sample frames. Original no-op presentation/Arm definitions are SHA-256-pinned and rejected. Carbon secure key and full stream-live fixtures pass against the existing loopback fake, including all their negative controls; no real ingest was used.

## Guarded game observations

The host add-on checks cover settings registration, Guide navigation, controller note entry and local report capture. Native game-field presentation still requires a visual check.

- 1-host-guide-capture: all new rows and hidden Off shortcut appear in settings_rows.txt. Capture/replay cannot record in this supervisor: the real host AAC factory returns 1718449215. The shared implementation reports the error and publishes no clip. The first UI script also used unsupported key aliases and did not reach the intended views; that script was corrected in later runs.
- 2-host-help-keyboard: Guide opens; controller note writes `1`. A complete local report is saved with report.txt, screenshot.png, stats.txt, events.txt, log.txt and settings.txt; report.txt contains category Other and note 1. app.txt persists 1080p, replay key enabled, F7 and L1+R1+L3. No report is submitted externally.
- 3-host-visible-text: menu_12025.png shows Guide at 0%; menu_14134.png at 58%; menu_15765.png shows Licences; keyboard_17039.png shows the controller keyboard with Note 1/256 and the entered `1`. The native Career attempt remained at Start Career, so a native game-field visual check is still needed; the native validator/edit/accept/cancel paths are proven by the translated-function fixture.

AAC recording, live picture-and-sound synchronization and driving replay shortcuts still require game verification with AAC encoding available. The common NOTICE displayed by Licences mentions the MW PC 1.3 requirement.

## Integration boundary

The shared registration edits are additive only: runtime_sources.json target-local source policies/units and media header classification; game_settings.h include/init call; offline_tests.sh discovery comment; VERSIONS.md appended block. Existing NFS_GAME_SCRATCH confines supervised captures; no new switch was introduced. Direct callback hooks: game_menu_hold.h drains text, carbon_padprompts.m preserves prompt tracking and forwards to the keyboard, and portmenu.m ends accepted/cancelled note editing. Their feature hashes and affected fixtures were updated. No pad layout implementation was changed.

New tests are automatically discovered; private_addons_stream_test is appended to offline_serial.txt because its reused fixtures have short deadlines. The scheduler's omission test includes it. private_settings_test has independent row/provider expectations for the new rows; the basic-rows-only fixture isolates its pre-existing 20 rows. Existing keyboard/key-privacy fixtures now preserve a newline and complete preprocessor guards when composing their real source fragments.

The final controller review found that Carbon does not yet register controls.menu_button. The shared shortcut implementation therefore needs the existing automatic choice when settings_get returns -1. game_menu_shortcut.h now normalizes only that missing choice and forwards an explicit choice and the hidden Guide enable flag unchanged. New production-header controls fail twice without normalization and once without enable forwarding (good 66,144/0). The Guide no longer advertises a menu-button choice row that this image does not expose. This small private-only integration correction followed the last permitted game run and is covered by the focused fixture; no fourth game was requested.

Stable third-run captures were inspected: Guide moves from 0% to 58%, Licences contains bundled notices, and keyboard_17039.png visibly shows Note 1/256 with the entered character. Native Career text entry was not reached within the three-run cap.

The saved-binding reader covers all slots allocated by 00679BA0, not only the first two keyboard slots: 72 actions times (2 + 2 * controller count), bounded by the native 16-device directory. 0067A340 accepts type-1 keyboard records in any slot. The fixture checks every slot for controller counts 0 through 16: 22,032 assigned-key cases; removing the priority reader fails all of them plus the malformed-count guard. The final host fixture is 66,144 checks / zero failures.

## Changed files

- VERSIONS.md
- recomp/private_basic_rows_test.py
- recomp/private_carbon_xboxart_test.py
- recomp/private_picture_04_test.py
- recomp/private_report_test.py
- recomp/private_runtime/carbon_padprompts.m
- recomp/private_runtime/features/padprompts.json
- recomp/private_runtime/features/picture_01.json
- recomp/private_runtime/features/picture_04.json
- recomp/private_runtime/game_menu_hold.h
- recomp/private_runtime/game_menu_policy.h
- recomp/private_runtime/game_menu_replay.h
- recomp/private_runtime/game_menu_shortcut.h
- recomp/private_runtime/game_settings.h
- recomp/private_settings_test.py
- runtime/carbon_padprompts_test.py
- runtime/clipcycle_test.py
- runtime/cliprec.mm
- runtime/docs/guide_carbon.md
- runtime/game_layers_test.py
- runtime/offline_serial.txt
- runtime/offline_tests.sh
- runtime/onscreen_keyboard.c
- runtime/onscreen_keyboard_test.py
- runtime/portmenu.m
- runtime/runtime_sources.json
- runtime/stream_key_test.py
- tools_snapshot/test_offline_serial.py
- recomp/private_addons_capture_test.py
- recomp/private_addons_host_test.py
- recomp/private_addons_stream_test.py
- recomp/private_addons_text_test.py
- recomp/private_runtime/carbon_addons_host_notes.md
- recomp/private_runtime/carbon_addons_host_replay.c
- recomp/private_runtime/carbon_addons_host_settings.h
- recomp/private_runtime/carbon_addons_host_text.c
- recomp/private_runtime/features/addons_host.json
- recomp/private_runtime/hooks/addons_host_text.json

## Final verification

The final selection matches runtime/impact_tests.py --diff with no unmapped paths, plus explicit media/AAC/export/presentation/publication checks: **211 selected, 201 PASS, 10 SKIP, zero remaining failures**. The two initial fixture failures (clip-cycle folder policy and the fourth classified media header) were corrected and both reran PASS. Final staged-source verification and git diff --check pass. All four new add-on tests pass, including Carbon's full secure-key and loopback fake-ingest controls.

Optional-input checks skip when the packaged installer, explicit PC input, generated headers or private effect, road and shader corpora are absent. The host add-on fixtures run without those inputs.

The actual shared AAC clip and audio tests pass through run_tests. The separate guarded game profile still reports AAC encoder unavailable (1718449215), so actual game recording/replay/live picture-and-sound synchronization remains unverified. No workaround or silent video-only fallback was added.

Remaining verification covers the Carbon Discord application identity and report destinations, native game text-field presentation, driving replay shortcuts and automatic controller-menu fallback after the capture limit. Visual and audio review remains required.

Shared input coverage:

The shared replay_input_test covers held-key, focus-loss, reconnect and chord state transitions. It supplements the host add-on, media and publication checks.
