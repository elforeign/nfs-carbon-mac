"""Carbon host registration, saved choices, real Guide layout and controller notes.
Production-path dependencies: carbon_addons_host_settings.h game_settings.h
carbon_addons_host_replay.c game_menu_policy.h game_menu_replay.h
 game_menu_shortcut.h game_menu_hold.h carbon_padprompts.m onscreen_keyboard.c
 guide.m cliprec.mm runtime_sources.json "addons_host.json" "carbon_addons_host_notes.md".
Good 66,144 checks / 0 failures; original Guide / note / binding / context no-ops
produce 1 / 5 / 22,033 / 1 failures respectively. Missing menu-choice fallback
and hidden Guide enable forwarding produce 2 / 1 failures. Native keyboard has its own fixture.
"""
from pathlib import Path
import hashlib
import json
import os
import plistlib
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
RT = ROOT/'runtime'
PRIVATE = ROOT/'recomp/private_runtime'
sys.path.insert(0,str(PRIVATE))
from layers import load_manifest, disabled_exports

# Independent integration expectations for private_settings_test.py.
SETTINGS_ROWS = {
    'display.clip_resolution': {},
    'display.cliprec': {'apply':'cliprec_action','value_text':'cliprec_status'},
    'display.clips_open': {'apply':'cliprec_open_folder'},
    'display.replay_arm': {'apply':'replay_arm_action','value_text':'replay_status'},
    'display.replay_save': {'apply':'replay_save_action','value_text':'replay_save_status'},
    'controls.replay_key_enabled': {}, 'controls.replay_key': {}, 'controls.replay_pad': {},
    'display.stream_heading': {}, 'display.stream_key': {'apply':'stream_key_edit'},
    'display.stream_forget': {'apply':'stream_key_forget'}, 'display.stream_go': {'apply':'stream_key_go'},
    'display.stream_stop': {'apply':'stream_key_stop'}, 'display.stream_status': {'value_text':'stream_key_status'},
    'diag.h_perf': {}, 'diag.perf': {'value_text':'perf_now'}, 'diag.audio': {'value_text':'audio_now'},
}
SETTINGS_PROVIDERS = {
    'cliprec_action':'cliprec.mm', 'cliprec_status':'cliprec.mm', 'cliprec_open_folder':'cliprec.mm',
    'replay_arm_action':'cliprec.mm', 'replay_status':'cliprec.mm', 'replay_save_action':'cliprec.mm', 'replay_save_status':'cliprec.mm',
    'stream_key_edit':'stream_key.m', 'stream_key_forget':'stream_key.m', 'stream_key_go':'stream_key.m', 'stream_key_stop':'stream_key.m', 'stream_key_status':'stream_key.m',
    'perf_now':'carbon_addons_host_settings.h', 'audio_now':'carbon_addons_host_settings.h',
}
SETTINGS_FIXTURE = r'''
void cliprec_action(int u) { (void)u; }
void cliprec_open_folder(int u) { (void)u; }
void cliprec_status(char *s,int n) { snprintf(s,n,"Off"); }
void replay_arm_action(int u) { (void)u; }
void replay_save_action(int u) { (void)u; }
void replay_status(char *s,int n) { snprintf(s,n,"Off"); }
void replay_save_status(char *s,int n) { snprintf(s,n,"Off"); }
void stream_key_edit(int u) { (void)u; }
void stream_key_forget(int u) { (void)u; }
void stream_key_go(int u) { (void)u; }
void stream_key_stop(int u) { (void)u; }
void stream_key_status(char *s,int n) { snprintf(s,n,"Off"); }
void report_live(float *f,float *p,float *g) { *f=*p=*g=0; }
const char *report_audio_device(void) { return "fixture"; }
int dsound_output_info(const char **m,int *l,uint64_t *u) { *m="PCM";*l=1;*u=0;return 1; }
'''

# Reviewed original callback fragments, rather than history or a whole-file digest.
ORIGINAL = '#define guide_scroll(lines) ((void)0)\n#define osk_note_begin(text, capacity, owner) ((void)0)\n#define replay_key_in_use(scan) 0\n'
assert hashlib.sha256(ORIGINAL.encode()).hexdigest() == 'f420fe2a26ae30333b040e6bd38c1919918ce248e7945ae564ec30d95daf0f98'

ORIGINAL_CONTEXT = 'static int replay_game_blocked(void) { return 1; }\n'
assert hashlib.sha256(ORIGINAL_CONTEXT.encode()).hexdigest() == '7fa6ef874cc5907eb1873f7bc310169673472ea2207929523e995d78bf6e016b'

HARNESS = r'''
#import <Cocoa/Cocoa.h>
#include "host.h"
#include "settings.h"
#include "guide.m"
#include "carbon_addons_host_settings.h"
#include "onscreen_keyboard.c"
#include "carbon_addons_host_replay.c"
#include "carbon_addons_host_text.c"
#include "carbon_pad_state.h"
static int is_open;
#include "game_menu_replay.h"
uint8_t *G;
int diag_on;
static int checks, failures, input=1, context=CARBON_PAD_DRIVING;
static int clipActions, arms, saves, keyEdits, forgets, goes, stops;
static char savedKey[128], savedValue[128];
static uint64_t tick;
#define CHECK(x) do { ++checks; if(!(x)) { ++failures; if(failures<=8) fprintf(stderr,"FAIL %d: %s\n",__LINE__,#x); } } while(0)
uint32_t call_guest(Cpu *c, uint32_t f, int n, const uint32_t *args) { (void)c;(void)f;(void)n;(void)args;return 0; }
int carbon_pad_context(void) { return context; }
int prompts_last_input(void) { return input; }
void prompts_input(int p) { input=p; }
int portmenu_is_open(void) { return is_open; }
uint64_t host_ticks(void) { return tick; }
void diag_event(const char *fmt,...) { (void)fmt; }
void report_note(const char *fmt,...) { (void)fmt; }
const char *app_pref(const char *key) { return !strcmp(key,"display.clip_resolution") ? "4k" : NULL; }
void app_pref_set(const char *key,const char *value) { snprintf(savedKey,sizeof savedKey,"%s",key);snprintf(savedValue,sizeof savedValue,"%s",value); }
int roots_x360_has(const char *feature) { (void)feature;return 1; }
void cliprec_action(int u) { (void)u;++clipActions; }
void cliprec_open_folder(int u) { (void)u; }
void cliprec_status(char *s,int n) { snprintf(s,n,"Off"); }
void replay_arm_action(int u) { (void)u;++arms; }
void replay_save_action(int u) { (void)u;++saves; }
void replay_status(char *s,int n) { snprintf(s,n,"Off"); }
void replay_save_status(char *s,int n) { snprintf(s,n,"Off"); }
void stream_key_edit(int u) { (void)u;++keyEdits; }
void stream_key_forget(int u) { (void)u;++forgets; }
void stream_key_go(int u) { (void)u;++goes; }
void stream_key_stop(int u) { (void)u;++stops; }
void stream_key_status(char *s,int n) { snprintf(s,n,"Off"); }
void report_live(float *fps,float *p99,float *gpu) { *fps=60;*p99=17;*gpu=4; }
const char *report_audio_device(void) { return "fixture output"; }
int dsound_output_info(const char **mode,int *live,uint64_t *under) { *mode="PCM";*live=1;*under=0;return 1; }
#include "game_menu_policy.h"
#include "game_menu_shortcut.h"
static void pass(void) { Cpu c={0};osk_pass(&c); }
static void notes(void) {
    char text[257]="";
    osk_pad(0,0,0,0,0,0,0,0,1,0);osk_note_begin(text,sizeof text,0);
    CHECK(osk_note_active() && osk_visible());
    osk_pad(0,0,0,0,0,0,0,0,1,0);osk_pad(0,1,0,0,0,0,0,0,1,0);pass();
    CHECK(!strcmp(text,"1"));
    for(int i=0;i<6;i++){osk_pad(0,1,0,0,0,0,0,0,1,0);pass();} CHECK(!strcmp(text,"1"));
    osk_queue(osk_capture()->generation,OSK_TYPE,'C');pass();CHECK(!strcmp(text,"1C"));
    uint64_t stale=osk_capture()->generation;osk_note_end(1);CHECK(!text[0]);
    osk_note_begin(text,sizeof text,0);osk_queue(stale,OSK_TYPE,'X');pass();CHECK(!text[0]);
    osk_queue(osk_capture()->generation,OSK_TYPE,'B');input=0;pass();CHECK(!text[0]);input=1;
    osk_queue(osk_capture()->generation,OSK_TYPE,'C');pass();CHECK(!strcmp(text,"C"));
    osk_queue(osk_capture()->generation,OSK_ACCEPT,0);pass();CHECK(!osk_note_active());
}
static void bindings(void) {
    CHECK(!replay_key_in_use(0x42));
    for(unsigned controllers=0;controllers<=16;++controllers){
      M32(0xA98948)=controllers;
      for(unsigned a=0;a<72;++a)for(unsigned s=0;s<2+2*controllers;++s){
        uint32_t row=0x200000+512*a;M32(0xA98704+8*a)=row;
        M32(row+12*s)=1;M32(row+12*s+4)=0x42;
        CHECK(replay_key_in_use(0x42));CHECK(!replay_key_in_use(0x41));
        M32(row+12*s)=2;CHECK(!replay_key_in_use(0x42));M32(row+12*s)=0;
    }
    }
    M32(0xA98948)=17;CHECK(replay_key_in_use(0x42));M32(0xA98948)=0;
    CHECK(!replay_game_blocked());context=CARBON_PAD_CAPTURE;CHECK(replay_game_blocked());
    context=CARBON_PAD_MENU;CHECK(replay_game_blocked());context=CARBON_PAD_DRIVING;is_open=1;CHECK(replay_game_blocked());is_open=0;
}
int main(void) { @autoreleasepool {
    G=calloc(1,0x1000000);CHECK(G!=NULL);
    carbon_addons_host_settings_init();settings_init();
    CHECK(settings_get("display.clip_resolution")==2);
    CHECK(!clipActions && !arms && !saves && !keyEdits && !forgets && !goes && !stops);
    const char *actions[]={"display.cliprec","display.replay_arm","display.replay_save","display.stream_key","display.stream_forget","display.stream_go","display.stream_stop"};
    for(unsigned i=0;i<sizeof actions/sizeof *actions;++i){Setting *s=settings_find(actions[i]);CHECK(s && s->apply);if(s && s->apply)s->apply(0);}
    CHECK(clipActions==1 && arms==1 && saves==1 && keyEdits==1 && forgets==1 && goes==1 && stops==1);
    CHECK(settings_set(settings_find("display.clip_resolution"),0));CHECK(!strcmp(savedKey,"display.clip_resolution") && !strcmp(savedValue,"1080p"));
    CHECK(settings_set(settings_find("controls.replay_key_enabled"),1));CHECK(!strcmp(savedValue,"on"));
    CHECK(settings_set(settings_find("controls.replay_key"),1));CHECK(!strcmp(savedValue,"f7"));
    CHECK(settings_set(settings_find("controls.replay_pad"),2));CHECK(!strcmp(savedValue,"l1r1r3"));
    char value[256];settings_find("diag.perf")->value_text(value,sizeof value);CHECK(strstr(value,"60.0 fps") && strstr(value,"17.00 ms"));
    settings_find("diag.audio")->value_text(value,sizeof value);CHECK(!strcmp(value,"PCM on fixture output"));
    Setting *g=settings_find("help.guide");CHECK(g && g->apply);if(g)g->apply(0);CHECK(guide_active());layout(500,70);CHECK(content_height>70);double before=offset;guide_scroll(1);CHECK(offset>before);
    CHECK([document.string containsString:@"Carbon"]);guide_close();CHECK(!guide_active());
    settings_find("help.licences")->apply(0);CHECK([document.string containsString:@"Licence fixture"]);guide_close();
    GuideShortcut shortcut={0};
    CHECK(guide_shortcut(&shortcut,1,0,0,1,1,-1,0,0).action==1);
    memset(&shortcut,0,sizeof shortcut);
    CHECK(guide_shortcut(&shortcut,1,0,1,0,0,-1,0,0).action==1);
    memset(&shortcut,0,sizeof shortcut);
    CHECK(guide_shortcut(&shortcut,1,0,0,1,1,1,0,0).action==0);
    memset(&shortcut,0,sizeof shortcut);
    guide_shortcut(&shortcut,1,64,0,0,1,-1,1,0);
    guide_shortcut(&shortcut,1.1,64|512,0,0,1,-1,1,0);
    CHECK(guide_shortcut(&shortcut,1.5,64|512,0,0,1,-1,1,0).action==2);
    CHECK(settings_get("controls.guide_button")==1);
    notes();bindings();
    printf("addons host: %d checks, %d failures; scroll=%.0f clip=%d replay=%d live=%d\n",checks,failures,offset,clipActions,saves,goes);
    free(G);return failures?1:0;
} }
'''


def main():
    manifest=load_manifest();target=manifest['targets']['private'];units=set(target['units']+target['extra_units'])
    expected={'guide.m','cliprec.mm','clip_packets.mm','replay.mm','replay_export.mm','replay_input.c','live_encode.mm','live_seg.mm','livestream.mm','stream_key.m','live_fake.m','onscreen_keyboard.c','carbon_addons_host_replay.c'}
    assert expected<=units,expected-units
    assert not {'cliprec_present','cliprec_action','cliprec_status','replay_arm_action','replay_save_action','stream_key_forget','stream_key_route_event','osk_visible','live_fake_go'} & {r['name'] for r in disabled_exports(manifest)}
    assert 'carbon_addons_host_settings_init();' in (PRIVATE/'game_settings.h').read_text()
    assert 'osk_pass(c);' in (PRIVATE/'game_menu_hold.h').read_text()
    assert 'return carbon_addons_host_osk_pad(' in (PRIVATE/'carbon_padprompts.m').read_text()
    with tempfile.TemporaryDirectory(prefix='private-addons-host-') as td:
        d=Path(td);app=d/'HostCheck.app';exe=app/'Contents/MacOS/HostCheck';exe.parent.mkdir(parents=True);resources=app/'Contents/Resources';resources.mkdir()
        (app/'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleExecutable':'HostCheck','CFBundleIdentifier':'test.host.addons','CFBundlePackageType':'APPL'}))
        (resources/'Guide.md').write_text((RT/'docs/guide_carbon.md').read_text());(resources/'Licences.md').write_text('Licence fixture\n')
        for name in ('carbon_addons_host_settings.h','carbon_addons_host_replay.c','game_menu_replay.h'):(d/name).write_bytes((PRIVATE/name).read_bytes())
        source=HARNESS
        mutations={
          'original-guide': ('static void notes(void)', '#undef guide_scroll\n#define guide_scroll(lines) ((void)0)\nstatic void notes(void)'),
          'original-note': ('static void notes(void)', '#undef osk_note_begin\n#define osk_note_begin(text, capacity, owner) ((void)0)\nstatic void notes(void)'),
          'original-bindings': ('static void bindings(void)', '#undef replay_key_in_use\n#define replay_key_in_use(scan) 0\nstatic void bindings(void)'),
          'original-context': ('context=CARBON_PAD_DRIVING;', 'context=CARBON_PAD_MENU;'),
          'menu-choice': ('unused','unused'),
          'guide-enabled': ('unused','unused'),
        }
        for name,mutation in [('good',None),*mutations.items()]:
            shortcut=(PRIVATE/'game_menu_shortcut.h').read_text()
            if name=='menu-choice':shortcut=shortcut.replace('choice < 0 ? 0 : choice','choice')
            if name=='guide-enabled':shortcut=shortcut.replace('choice < 0 ? 0 : choice, enabled, menu_open','choice < 0 ? 0 : choice, 0, menu_open')
            (d/'game_menu_shortcut.h').write_text(shortcut)
            (d/'game_menu_replay.h').write_text(ORIGINAL_CONTEXT if name=='original-context' else (PRIVATE/'game_menu_replay.h').read_text())
            text=source if not mutation or name=='original-context' else source.replace(*mutation)
            src=d/'host.m';src.write_text(text)
            cmd=['clang','-O1','-g','-fobjc-arc','-DNFS_GAME=2','-I'+str(d),'-I'+str(PRIVATE),'-I'+str(RT),'-I'+str(ROOT/'recomp'),'-I'+str(ROOT/'recomp/out'),str(src),str(RT/'settings.c'),str(RT/'text_fit.c'),str(RT/'offline_stubs.c'),'-framework','Cocoa','-framework','CoreText','-framework','Metal','-framework','QuartzCore','-Wl,-dead_strip','-o',str(exe)]
            build=subprocess.run(cmd,capture_output=True,text=True);assert not build.returncode,build.stderr[-2500:]
            result=subprocess.run([str(exe)],capture_output=True,text=True,env=dict(os.environ),timeout=30)
            print(name+': '+result.stdout.strip(),flush=True)
            assert result.returncode==(1 if mutation else 0),result.stderr[-2500:]
    print('PRIVATE ADDONS HOST PASS')

if __name__=='__main__':main()
