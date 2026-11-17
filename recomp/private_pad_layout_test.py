"""Private three-layout selection through production settings/menu callbacks.

Good: 0/1162 failures (ASan/UBSan). Broken counts /1162:
pc-as-boolean 134, stale-automatic 226, pad-one-retargets-zero 193,
app-over-environment 165, reset-explicit-xbox 88, separate-controller-state 6,
f10-wrong-storage 1, wrong-app-directory 2; every mutant exits 1, good exits 0.
Covers every advertised Sony kind, other/Xbox and absent pads, live identity
swaps, env > saved > automatic, invalid fall-through, two-pad resolution,
reset, and real app.txt persistence using the native preference functions.
Public omission: 0/1,162 failures; original forced-PC fragment fails 418/1,162.
Exit 3 without Carbon outputs. No devices, game, GPU or emulator.
"""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent
PRIVATE = ROOT/'recomp/private_runtime'

# Independent row/callback ownership consumed by private_settings_test.py.
SETTINGS_ROWS = {'controls.pad_layout': {'get': 'carbon_pad_layout_get', 'apply': 'carbon_pad_layout_set'},
                 'controls.pad_layout_reason': {'value_text': 'carbon_pad_layout_reason'}}
SETTINGS_PROVIDERS = {'carbon_pad_layout_get': 'carbon_pad_layout.c',
                      'carbon_pad_layout_set': 'carbon_pad_layout.c',
                      'carbon_pad_layout_reason': 'carbon_pad_layout.c'}
SETTINGS_FIXTURE = """
int carbon_pad_layout_get(void) { return 1; }
void carbon_pad_layout_set(int value) { (void)value; }
void carbon_pad_layout_reason(char *buffer,int size) { snprintf(buffer,(size_t)size,"Automatic: Xbox"); }
void carbon_pad_layout_menu_init(void) { }
"""

HARNESS = r'''
#import <Cocoa/Cocoa.h>
#include "host.h"
#include "settings.h"
#include "carbon_pad_layout.h"
#include <errno.h>
#include <stdlib.h>
#include <unistd.h>
int diag_on;
const char *diag_dir, *game_dir;
static int kinds[2], failures, checks;
static char pref_directory[1024];
#define CHECK(x) do { ++checks; if(!(x)) { if(failures<12)fprintf(stderr,"FAIL %d: %s\n",__LINE__,#x);++failures; } } while(0)
int pad_identity_n(int pad,char *name,size_t size) { (void)name;(void)size;return pad<2?kinds[pad]:0; }
const char *userdata_dir(void) { return pref_directory; }
int durable_commit_with(FILE *file,const char *tmp,const char *path,int flags) {
    (void)flags;return !fclose(file) && !rename(tmp,path);
}
void diag_event(const char *fmt,...) { (void)fmt; }
void report_note(const char *fmt,...) { (void)fmt; }
int roots_x360_has(const char *feature) { (void)feature;return 1; }
/* Actual app-pref functions, extracted at their maintained offline boundary. */
#include "preferences.inc"
#include "carbon_pad_layout.c"
#include "carbon_pad_layout_menu.m"
#include "carbon_pad_layout_f10.h"
static void register_layout(void) {
#include "carbon_pad_layout_settings.h"
}
static void clear(void) { unsetenv("NFS_PAD_LAYOUT");carbon_pad_layout_reset(); }
int main(int argc,char **argv) {
    if(argc!=2)return 2;snprintf(pref_directory,sizeof pref_directory,"%s",argv[1]);
    const char *tokens[]={"playstation","xbox","pc"};
    const int identities[]={PAD_KIND_DUALSENSE,PAD_KIND_DUALSHOCK4,PAD_KIND_EDGE,PAD_KIND_OTHER,PAD_KIND_OTHER,PAD_KIND_NONE};
    const int automatic[]={0,0,0,1,1,1};
    register_layout();settings_init();
    Setting *row=settings_find("controls.pad_layout");CHECK(row&&row->nchoices==3&&row->category==SET_CONTROLS);
    CHECK(!strcmp(row->label,"Button layout"));
    CarbonLayoutMenu *menu=[CarbonLayoutMenu new];
    NSMenuItem *item=[NSMenuItem new];
    for(unsigned k=0;k<6;++k)for(int saved=-1;saved<4;++saved)for(int env=-1;env<4;++env) {
        clear();kinds[0]=identities[k];kinds[1]=PAD_KIND_EDGE;
        if(saved>=0)app_pref_set("pad_layout",saved==3?"bad":tokens[saved]);
        if(env>=0)setenv("NFS_PAD_LAYOUT",env==3?"bad":tokens[env],1);
        int want=env>=0&&env<3?env:saved>=0&&saved<3?saved:automatic[k];
        int origin=env>=0&&env<3?2:saved>=0&&saved<3?1:0;
        CarbonPadLayoutChoice result=carbon_pad_layout_resolve(0);
        CHECK((int)result.layout==want);CHECK((int)result.origin==origin);CHECK(result.kind==identities[k]);
        CHECK(settings_get("controls.pad_layout")==want);
        item.tag=want;CHECK([menu validateMenuItem:item]);
        item.action=@selector(choose:);[menu validateMenuItem:item];CHECK(item.state==NSControlStateValueOn);
        CHECK(kinds[0]==identities[k]&&kinds[1]==PAD_KIND_EDGE);
        if(origin==0)CHECK(carbon_pad_layout_resolve(1).layout==CARBON_LAYOUT_PLAYSTATION);
    }
    /* Automatic recomputes for every unplug/type change; pad 1 never retargets 0. */
    clear();kinds[0]=PAD_KIND_DUALSENSE;
    for(int i=0;i<20;++i) {
        kinds[1]=i%5;CHECK(carbon_pad_layout_resolve(0).layout==CARBON_LAYOUT_PLAYSTATION);
        kinds[0]=i%2?PAD_KIND_NONE:PAD_KIND_OTHER;CHECK(carbon_pad_layout_resolve(0).layout==CARBON_LAYOUT_XBOX);
        kinds[0]=PAD_KIND_EDGE;CHECK(carbon_pad_layout_resolve(0).layout==CARBON_LAYOUT_PLAYSTATION);
    }
    /* Controller and F10 use the same real callbacks; env still wins live. */
    clear();kinds[0]=PAD_KIND_DUALSENSE;item.tag=2;[menu choose:item];
    CHECK(settings_get(row->id)==2);CHECK(!strcmp(app_pref("pad_layout"),"pc"));
    kinds[0]=PAD_KIND_OTHER;CHECK(settings_get(row->id)==2);
    CHECK(settings_set(row,0));CHECK(carbon_pad_layout_get()==0);
    item.tag=1;[menu choose:item];CHECK(settings_get(row->id)==1);
    /* Reload the exact same private app.txt, as a second launch would. */
    prefs_loaded=0;nprefs=0;CHECK(carbon_pad_layout_get()==1);
    char path[1100],expected_path[1100];prefs_path(path,sizeof path);snprintf(expected_path,sizeof expected_path,"%s/app.txt",pref_directory);CHECK(!strcmp(path,expected_path));
    CHECK(strstr(path,"/app.txt")!=NULL);
    kinds[0]=PAD_KIND_DUALSENSE;CHECK(carbon_pad_layout_get()==1);
    setenv("NFS_PAD_LAYOUT","pc",1);CHECK(carbon_pad_layout_get()==2);
    item.tag=0;[menu choose:item];CHECK(carbon_pad_layout_get()==2);CHECK(!strcmp(app_pref("pad_layout"),"playstation"));
    CHECK(settings_set(row,1));CHECK(carbon_pad_layout_get()==2);CHECK(!strcmp(app_pref("pad_layout"),"xbox"));
    unsetenv("NFS_PAD_LAYOUT");CHECK(carbon_pad_layout_get()==1);
    settings_reset(row);CHECK(carbon_pad_layout_get()==0);CHECK(!*app_pref("pad_layout"));
    kinds[0]=PAD_KIND_OTHER;CHECK(carbon_pad_layout_get()==1);
    item.tag=2;[menu choose:item];[menu automatic:nil];CHECK(carbon_pad_layout_get()==1);
    CHECK(!*app_pref("pad_layout"));
    char reason[200];carbon_pad_layout_reason(reason,sizeof reason);CHECK(strstr(reason,"Automatic: Xbox")!=NULL);
    prefs_loaded=0;nprefs=0;CHECK(carbon_pad_layout_resolve(0).origin==CARBON_LAYOUT_AUTOMATIC);
    CHECK(app_pref("other_pad_layout")==NULL);
    item.action=@selector(automatic:);[menu validateMenuItem:item];
    CHECK(strstr(item.title.UTF8String,"Automatic: Xbox")!=NULL);
    printf("private_pad_layout checks=%d failures=%d\n",checks,failures);
    return failures?1:0;
}
'''

def main():
    base=ROOT/'recomp/out/carbon-base'
    if not all((base/n).is_file() for n in ('image.json','NFSC.a','funcs.h')):
        print('SKIP: private layout fixture needs Carbon outputs')
        return 3
    image=json.loads((base/'image.json').read_text())
    assert image['sha256']=='baaaaec33873d4ba7e4dbae6a5212049ffdcf9679a35d865d7625b4189952fd3'
    app=(ROOT/'runtime/app.m').read_text()
    prefs=app.split('// BEGIN offline prefs:',1)[1].split('\n',1)[1].split('// END offline prefs',1)[0]
    assert '"%s/app.txt", userdata_dir()' in prefs
    source=(PRIVATE/'carbon_pad_layout.c').read_text()
    menu=(PRIVATE/'carbon_pad_layout_menu.m').read_text()
    settings=(PRIVATE/'carbon_pad_layout_settings.h').read_text()
    assert '.get=carbon_pad_layout_get, .apply=carbon_pad_layout_set' in settings
    assert 'carbon_pad_layout_set((int)item.tag)' in menu and 'carbon_pad_layout_reset()' in menu
    assert 'controls.pad_layout' in settings and 'carbon_pad_layout_settings.h' in (PRIVATE/'game_settings.h').read_text()
    with tempfile.TemporaryDirectory(prefix='private-pad-layout-') as directory:
        tmp=Path(directory);(tmp/'fixture.m').write_text(HARNESS);(tmp/'preferences.inc').write_text(prefs)
        def execute(name,text,expect,setting_text=settings,menu_text=menu,prefs_text=prefs,public=False):
            (tmp/'preferences.inc').write_text(prefs_text)
            (tmp/'carbon_pad_layout.c').write_text(text)
            (tmp/'carbon_pad_layout_settings.h').write_text(setting_text)
            (tmp/'carbon_pad_layout_menu.m').write_text(menu_text)
            if public:
                (tmp/'carbon_pad_layout.h').write_bytes((PRIVATE/'carbon_pad_layout.h').read_bytes())
                (tmp/'carbon_pad_layout_f10.h').write_bytes((PRIVATE/'carbon_pad_layout_f10.h').read_bytes())
            (tmp/'fixture.m').write_text(HARNESS)
            binary=tmp/name
            args=['clang','-O1','-g','-fsanitize=address,undefined','-fno-sanitize-recover=all',
                  '-I',tmp,'-I',PRIVATE,'-I',ROOT/'runtime','-I',ROOT/'recomp',tmp/'fixture.m',
                  ROOT/'runtime/settings.c','-framework','Cocoa','-o',binary]
            if public:
                at=args.index(PRIVATE); del args[at-1:at+1]
            result=subprocess.run(list(map(str,args)),capture_output=True,text=True)
            assert result.returncode==0,result.stderr[-4000:]
            profile=tmp/(name+'-userdata');profile.mkdir()
            result=subprocess.run([str(binary),str(profile)],capture_output=True,text=True)
            assert result.returncode==expect,(name,result.returncode,result.stdout[-1200:],result.stderr[-2000:])
            print(name+': '+result.stdout.strip())
            return result.stdout.strip()
        execute('public-port',source,0,public=True)
        # Original table-free resolver fragment, pinned independently of production.
        fallback = '#if !__has_include("carbon_padbind_ps3.inc") || !__has_include("carbon_padbind_x360.inc")\n    choice.layout = CARBON_LAYOUT_PC;\n#endif\n'
        assert hashlib.sha256(fallback.encode()).hexdigest() == 'ff81ab5d1f543c4b6d332f814cba82e5d242cef8ba3adf2bf93ae41a792afa02'
        execute('public-original-forced-pc',source.replace('    Setting *row =',fallback+'    Setting *row ='),1,public=True)
        execute('good',source,0)
        variants={
            'pc-as-boolean':('return i;','return i == 2 ? 1 : i;'),
            'stale-automatic':('int kind = pad_identity_n((int)pad, NULL, 0);','static int first = -1; if(first < 0) first = pad_identity_n((int)pad,NULL,0); int kind = first;'),
            'pad-one-retargets-zero':('pad_identity_n((int)pad, NULL, 0)','pad_identity_n(1, NULL, 0)'),
            'app-over-environment':('if (value >= 0) {','if (value >= 0 && preference < 0) {'),
            'reset-explicit-xbox':('app_pref_set("pad_layout", "");','app_pref_set("pad_layout", "xbox");'),
        }
        for name,(old,new) in variants.items():
            assert old in source,name
            execute(name,source.replace(old,new),1)
        execute('separate-controller-state',source,1,menu_text=menu.replace('carbon_pad_layout_set((int)item.tag);','(void)item;'))
        execute('f10-wrong-storage',source,1,setting_text=settings.replace('.pref="pad_layout"','.pref="other_pad_layout"'))
        execute('wrong-app-directory',source,1,prefs_text=prefs.replace('"%s/app.txt", userdata_dir()', '"%s/wrong/app.txt", userdata_dir()'))
    print('private_pad_layout_test: PASS')
    return 0

if __name__=='__main__':
    sys.exit(main())
