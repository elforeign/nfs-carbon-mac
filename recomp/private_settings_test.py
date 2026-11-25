"""Selected menu/settings contract: good=0; each of five broken policies=1.

Independent eight base rows plus four later rows (12 rows / 14 callbacks), initialized six-slot outputs,
43 private includes used once and one selected support unit, image/source provenance and actual compiler
MW-access rejection. Missing Carbon runtime outputs: exit 3.
Feature dependencies: picture_01.json picture_02.json picture_03.json picture_04.json
picture_05.json picture_06.json picture_07.json picture_08.json (feature).
Baseline rows=0; accepted base rows=8, total rows=12; unwritten mode outputs=0 -> initialized outputs=2.
"""
from pathlib import Path
import ast
import copy
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
PRIVATE = HERE / 'private_runtime'
sys.path.insert(0, str(PRIVATE))
from layers import load_manifest, audit_unit, build_owned, check_audits, disabled_exports

# Derived from selected host providers, not the registration being checked.
EXPECTED = {
    'display.window': {'apply': 'private_window_apply', 'get': 'private_window_get'},
    'display.fullscreen': {'apply': 'private_fullscreen_apply'},
    'graphics.hdr_output': {},
    'graphics.hdr_status': {'value_text': 'private_hdr_status'},
    'diag.full_logging': {},
    'diag.logs_open': {'apply': 'private_logs_open'},
    'diag.quit_game': {'apply': 'app_quit_game'},
    'display.notch': {'apply': 'private_notch_apply'},
}
PROVIDERS = {
    'private_window_apply': 'game_settings.h',
    'private_window_get': 'game_settings.h',
    'private_fullscreen_apply': 'game_settings.h',
    'private_notch_apply': 'game_settings.h',
    'private_hdr_status': 'game_settings.h',
    'private_logs_open': 'game_settings.h',
    'app_quit_game': 'app.m',
}
# One ownership record per job; also declares the fixture's source dependencies.
SEAMS = {
    1: 'game_menu_capture.h game_menu_present.h game_menu_support.c game_menu_title.h game_settings.h game_menu_policy.h game_menu_shortcut.h game_menu_text.h game_menu_report.h game_menu_state.h game_menu_event.h game_menu_replay.h',
    2: 'game_mode_provider.h game_display_bindings.h game_display_settings.h game_display_modes.h game_display_aa.h',
    3: 'game_widescreen.h game_frontend_matrix.h game_frontend_begin.h game_frontend_end.h game_frontend_clip.h',
    4: 'game_pacing_settings.h game_menu_hold.h game_picture_present.h',
    5: 'game_picture_shader_submit.h game_shader_publish.h game_shader_catalogue.h game_shader_cache_policy.h game_shader_fixed_warm.h',
    6: 'game_pipeline_loading.h game_pipeline_recipes.h game_pipeline_prewarm.h',
    7: 'game_hdr_begin.h game_hdr_target.h game_hdr_promote_size.h game_hdrclip_init.h game_hdrclip_select.h game_hdrclip_finish.h',
    8: 'game_hdr_prewarm.h game_tone_settings.h game_hdr_compose.h game_hdr_present_end.h game_hdr_recipes.h',
}
SHARED = 'game_bindings.h boot.c portmenu.m settings_port.c d3d9.m d3dx_effect.c render.m pipeline_cache.m hdrclip.m'.split()


def callbacks(source):
    rows = re.findall(r'\{\s*\.id="([^"]+)"(.*?)\n', source)
    actual = {name: dict(re.findall(r'\.(apply|get|value_text)\s*=\s*(\w+)', row)) for name, row in rows}
    if actual != EXPECTED:
        raise ValueError('unsupported row/callback: ' + repr(actual))
    if '__attribute__((constructor))' in source:
        raise ValueError('settings initialization must be explicit')


def contracts(canonical, features, shared):
    manifest = load_manifest(features=features, private_runtime=canonical)
    callbacks((canonical / 'game_settings.h').read_text())
    feature_sources = {original for path in Path(features).glob('*.json')
                       for original in json.loads(path.read_text())['staged_sources'].values()}
    all_sources = '\n'.join(shared.values()) + '\n' + '\n'.join(
        (canonical / name).read_text() for name in sorted(feature_sources))
    for job, names in SEAMS.items():
        feature = json.loads((features / f'picture_{job:02d}.json').read_text())
        if not set(names.split()).issubset(feature['sources']):
            raise ValueError('job source ownership differs: ' + str(job))
        for name in names.split():
            if name not in manifest['targets']['private']['staged_sources']:
                raise ValueError('unregistered plug-in: ' + name)
            count = len(re.findall(r'^\s*#include "' + re.escape(name) + '"', all_sources, re.M))
            if feature['sources'][name]['kind'] == 'unit':
                if count or manifest['targets']['private']['extra_units'].count(name) != 1:
                    raise ValueError('support unit membership differs: ' + name)
            elif count != 1:
                raise ValueError('plug-in include count differs: ' + name)
    boot = shared['boot.c']
    if boot.index('    private_settings_init();') >= boot.index('    settings_init();'):
        raise ValueError('settings registered too late')
    return manifest


def later_settings_contracts():
    """Later jobs extend the independent expectation in their own test only.

    Literal SETTINGS_ROWS maps IDs to callbacks, SETTINGS_PROVIDERS maps callback
    names to staged owners, and SETTINGS_FIXTURE supplies their host fixture APIs.
    Read test data with literal_eval; never import another test or inspect the
    registration under test to derive expected rows.
    """
    rows, providers, fixture = dict(EXPECTED), dict(PROVIDERS), ''
    paths = [HERE / 'private_pad_layout_test.py'] + [HERE / f'private_picture_{job:02d}_test.py' for job in range(2, 9)]
    paths.append(HERE / 'private_overlay_test.py')
    paths.append(HERE / 'private_basic_rows_test.py')
    paths.append(HERE / 'private_report_test.py')
    paths.append(HERE / 'private_unlock_test.py')
    paths.append(HERE / 'private_port_settings_test.py')
    paths.append(HERE / 'private_addons_gameplay_test.py')
    paths.append(HERE / 'private_addons_host_test.py')
    for path in paths:
        if not path.is_file():
            continue
        values = {}
        for node in ast.parse(path.read_text()).body:
            if isinstance(node, ast.Assign):
                for name in node.targets:
                    if isinstance(name, ast.Name) and name.id in ('SETTINGS_ROWS', 'SETTINGS_PROVIDERS', 'SETTINGS_FIXTURE'):
                        values[name.id] = ast.literal_eval(node.value)
        additions = values.get('SETTINGS_ROWS', {})
        owners = values.get('SETTINGS_PROVIDERS', {})
        if rows.keys() & additions.keys() or providers.keys() & owners.keys():
            raise ValueError('duplicate independent settings expectation: ' + path.name)
        rows.update(additions); providers.update(owners)
        fixture += values.get('SETTINGS_FIXTURE', '') + '\n'
    if {cb for callbacks in rows.values() for cb in callbacks.values()} - providers.keys():
        raise ValueError('independent callback expectation has no selected owner')
    return rows, providers, fixture


def provider_closure(manifest, out, providers):
    audits = json.loads((out / 'layer_audits.json').read_text())
    check_audits(audits, manifest, manifest['targets']['private']['extra_sources'], require_complete=True)
    declarations = [r for u in audits for r in u['declarations']]
    selected = {r['name']: r for r in declarations}
    disabled = {r['name'] for r in disabled_exports(manifest)}
    for name, owner in providers.items():
        if name not in selected or Path(selected[name]['source']).name != owner:
            raise ValueError('callback owner not selected: ' + name)
        pending, seen = [name], set()
        while pending:
            callee = pending.pop()
            if callee in seen:
                continue
            seen.add(callee)
            if callee in disabled:
                raise ValueError('callback reaches disabled provider: ' + name + ' -> ' + callee)
            row = selected.get(callee)
            if row:
                pending.extend(row['calls'] + row['references'])
    print(f'callbacks selected={len(providers)} disabled dependencies=0')


HARNESS = r'''
#include "game_settings.h"
#include "game_mode_provider.h"
void osk_pass(Cpu *c) { (void)c; }
#include "game_menu_hold.h"
static Setting *registered[128]; static unsigned count;
static int fullscreen, mode_changes, notch_changes, quits; static const char *opened;
int diag_on; const char *diag_dir;
void diag_event(const char *format, ...) { (void)format; }
int user32_fullscreen(void) { return fullscreen; }
void user32_toggle_fullscreen(void) { fullscreen=!fullscreen; }
void user32_fullscreen_mode_changed(void) { ++mode_changes; }
void user32_notch_fill_changed(void) { ++notch_changes; }
int user32_notch_fill(void) { return 0; }
void app_quit_game(int v) { (void)v; ++quits; }
void portmenu_open_folder(const char *p) { opened=p; }
const char *log_dir(void) { return "log-fixture"; }
const char *userdata_dir(void) { return "profile-fixture"; }
const char *render_hdr_output_status(void) { return "SDR fixture"; }
void settings_add(Setting *s) { registered[count++]=s; }
Setting *settings_find(const char *id) { for(unsigned i=0;i<count;i++) if(!strcmp(id,registered[i]->id)) return registered[i]; return NULL; }
const char *settings_text(const char *id) { (void)id; return ""; }
int settings_get(const char *id) { for(unsigned i=0;i<count;i++) if(!strcmp(id,registered[i]->id)) return registered[i]->value; return -1; }
#define CHECK(v) do { if (!(v)) { fprintf(stderr,"SETTINGS CHECK line=%d: %s\n",__LINE__,#v); return 1; } } while(0)
int main(void) {
    CHECK(count==0); private_settings_init(); CHECK(count==8);
    const char *expected[]={"display.window","display.fullscreen","graphics.hdr_output","graphics.hdr_status","diag.full_logging","diag.logs_open","diag.quit_game","display.notch"};
    for(unsigned i=0;i<count;i++)CHECK(!strcmp(registered[i]->id,expected[i]));
    CHECK(registered[0]->get()==1); registered[0]->apply(0); CHECK(fullscreen==1);
    registered[0]->apply(0); CHECK(fullscreen==1); registered[0]->apply(1); CHECK(fullscreen==0);
    registered[1]->apply(2); CHECK(mode_changes==1);
    char text[64]; registered[3]->value_text(text,sizeof text); CHECK(!strcmp(text,"SDR fixture"));
    registered[5]->apply(0); CHECK(!strcmp(opened,"log-fixture"));
    diag_on=1;diag_dir="diag-fixture";registered[5]->apply(0);CHECK(opened==diag_dir);
    registered[6]->apply(0);CHECK(quits==1);
    registered[7]->apply(1);CHECK(notch_changes==1);
    for(int i=-1;i<8;i++){uint32_t w=0xdeadbeef,h=0xdeadbeef;widescreen_mode(i,&w,&h);CHECK(w!=0xdeadbeef&&h!=0xdeadbeef);CHECK((w==0)==(h==0));if(i<0||i>=6)CHECK(w==0&&h==0);}
    CHECK(portmenu_hold()==0);Cpu cpu={0};portmenu_pass(&cpu);
    puts("PRIVATE SETTINGS PASS rows=8 callbacks=7 mode_outputs=18 native_hold=0"); return 0;
}
'''


def main():
    out = HERE / 'out/carbon'
    required = ['image.json', 'layer_audits.json', 'runtime_compile_flags.json', 'runtime_mw_ranges.json']
    if any(not (out / n).is_file() for n in required):
        print('SKIP: build the Carbon runtime first')
        return 3
    if not build_owned(out):
        print('SKIP: private runtime link belongs to another checkout')
        return 3
    shared = {name: (ROOT / 'runtime' / name).read_text() for name in SHARED}
    manifest = contracts(PRIVATE, PRIVATE / 'features', shared)
    expected, providers, fixture = later_settings_contracts()
    provider_closure(manifest, out, providers)
    with tempfile.TemporaryDirectory(prefix='private-settings-') as tmp:
        tmp = Path(tmp); canonical = tmp / 'private'; canonical.mkdir()
        for feature in (PRIVATE / 'features').glob('*.json'):
            for original in json.loads(feature.read_text())['staged_sources'].values():
                target = canonical / original; target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(PRIVATE / original, target)
        features = canonical / 'features'; shutil.copytree(PRIVATE / 'features', features)
        harness = HARNESS.replace('CHECK(count==8)', f'CHECK(count=={len(expected)})')
        harness = re.sub(r'const char \*expected\[\]=\{[^;]+;',
                         lambda match: 'const char *expected[]={' + ','.join(json.dumps(row) for row in expected) + '};', harness)
        callbacks_table = 'Setting expected_callbacks[]={' + ','.join(
            '{' + (','.join('.' + field + '=' + callback for field, callback in callbacks.items()) or '0') + '}'
            for callbacks in expected.values()) + '};\n'
        harness = harness.replace('for(unsigned i=0;i<count;i++)CHECK(!strcmp(registered[i]->id,expected[i]));',
            callbacks_table + 'for(unsigned i=0;i<count;i++){CHECK(!strcmp(registered[i]->id,expected[i]));'
            'CHECK(registered[i]->apply==expected_callbacks[i].apply);'
            'CHECK(registered[i]->get==expected_callbacks[i].get);'
            'CHECK(registered[i]->value_text==expected_callbacks[i].value_text);}')
        harness = harness.replace('rows=8 callbacks=7', f'rows={len(expected)} callbacks={len(providers)}')
        harness = harness.replace('#include \"game_mode_provider.h\"', fixture + '\n#include \"game_mode_provider.h\"')
        (tmp / 'harness.c').write_text(harness)
        binary = tmp / 'settings'
        command = ['clang', '-DNFS_GAME=2', '-I', str(canonical), '-I', str(ROOT / 'runtime'), '-I', str(HERE), str(tmp / 'harness.c'), '-framework', 'CoreFoundation', '-o', str(binary)]
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError(result.stderr[-2500:])
        result = subprocess.run([str(binary)], capture_output=True, text=True)
        print(result.stdout.strip()); assert result.returncode == 0, result.stderr
        mode = canonical / 'game_mode_provider.h'; good_mode = mode.read_text()
        mode.write_text(good_mode.replace('    *w = 0;', '').replace('    *h = 0;', ''))
        broken_compile = subprocess.run(command, capture_output=True, text=True)
        assert broken_compile.returncode == 0, broken_compile.stderr
        broken_mode = subprocess.run([str(binary)], capture_output=True, text=True)
        assert broken_mode.returncode == 1 and 'SETTINGS CHECK' in broken_mode.stderr
        print('negative unwritten modes: good exit=0 / broken exit=1')
        mode.write_text(good_mode)
        original = {n.name: n.read_text() for n in features.glob('*.json')}
        settings = (canonical / 'game_settings.h').read_text()
        replay = (canonical / 'game_menu_replay.h').read_text()
        def refresh(name, job):
            path = features / f'picture_{job:02d}.json'; feature = json.loads(path.read_text())
            feature['bindings'][name]['sha256'] = hashlib.sha256((canonical / name).read_bytes()).hexdigest()
            path.write_text(json.dumps(feature))
        def check():
            return contracts(canonical, features, shared)
        for mutant in ['mw-callback', 'image-digest', 'source-digest', 'mw-read', 'missing-include']:
            for name, content in original.items(): (features / name).write_text(content)
            (canonical / 'game_settings.h').write_text(settings)
            (canonical / 'game_menu_replay.h').write_text(replay)
            broken_shared = copy.copy(shared)
            if mutant == 'mw-callback':
                (canonical / 'game_settings.h').write_text(settings.replace('.apply=app_quit_game', '.apply=x360_set_tone_curve'))
                refresh('game_settings.h', 1)
            elif mutant in ('image-digest', 'source-digest'):
                path=features / 'picture_01.json'; feature=json.loads(path.read_text())
                if mutant == 'image-digest': feature['image_sha256']='0'*64
                else: feature['bindings']['game_settings.h']['sha256']='0'*64
                path.write_text(json.dumps(feature))
            elif mutant == 'mw-read':
                (canonical / 'game_menu_replay.h').write_text('static int replay_game_blocked(void) { return M32(0x00925E90u); }\n')
                refresh('game_menu_replay.h', 1)
            else:
                broken_shared['render.m'] = shared['render.m'].replace('#include "game_frontend_clip.h"', '')
            rejected = 0
            try:
                broken = contracts(canonical, features, broken_shared)
                if mutant == 'mw-read':
                    unit = tmp / 'runtime'; unit.mkdir(exist_ok=True)
                    (tmp / 'image.json').write_text((out / 'image.json').read_text())
                    source = unit / 'portmenu.m'; source.write_text('#include "host.h"\n#include "game_menu_replay.h"\n')
                    flags=['-DNFS_GAME=2','-fobjc-arc','-I',str(canonical),'-I',str(ROOT/'runtime'),'-I',str(HERE)]
                    audit = audit_unit(source, flags, json.loads((out/'runtime_mw_ranges.json').read_text()))
                    check_audits([audit], broken, broken['targets']['private']['extra_sources'])
            except ValueError as error:
                rejected = 1
                if mutant == 'mw-read': assert 'MW address read' in str(error) and '0x00925E90' in str(error), str(error)
            print(f'negative {mutant}: good rejections=0 / broken rejections={rejected}')
            assert rejected == 1, mutant
    return 0


if __name__ == '__main__':
    sys.exit(main())
