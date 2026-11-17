"""Local report regression: main run 0 complete reports; enabled run 1 (six files).
Guarded atomic writes: screenshot only; direct sanitized writes: six files.
The captured startup frame is black; visible gameplay capture needs a lead run.
Keyboard note: fixed BUG / 3 characters; restored cancellation empty / 0.
Offline fixture exercises registered category/note/save callbacks and rejects
removed registration. --run DIR checks the guarded run's actual report artifacts.
Feature dependencies: report.json picture_01.json overlay.json (feature).
"""
from pathlib import Path
import struct
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = ROOT / 'recomp/private_runtime'
SETTINGS_ROWS = {
    'diag.h_report': {},
    'diag.report_category': {},
    'diag.report_note': {},
    'diag.report_save': {'apply': 'report_save', 'value_text': 'report_saved_text'},
    'diag.report_open': {'apply': 'open_reports'},
}
SETTINGS_PROVIDERS = {
    'report_save': 'carbon_report_settings.h',
    'report_saved_text': 'carbon_report_settings.h',
    'open_reports': 'carbon_report_settings.h',
}
SETTINGS_FIXTURE = r'''
void report_save_async(const char *category, const char *note) { (void)category; (void)note; }
const char *report_last_path(void) { return "fixture/reports/saved"; }
'''


def complete_reports(run):
    complete = []
    for report in run.glob('diag.user/**/reports/*/report.txt'):
        folder = report.parent
        if not all((folder / n).is_file() and (folder / n).stat().st_size
                   for n in ('screenshot.png', 'stats.txt', 'events.txt', 'log.txt', 'settings.txt')):
            continue
        png = (folder / 'screenshot.png').read_bytes()
        if png[:8] != b'\x89PNG\r\n\x1a\n' or len(png) < 1024:
            continue
        w, h = struct.unpack('>II', png[16:24])
        if w < 320 or h < 200:
            continue
        stats = (folder / 'stats.txt').read_text()
        if not any(line and not line.startswith('#') for line in stats.splitlines()):
            continue
        # The report snapshot contains value rows; actions are intentionally omitted.
        if 'diag.report_category' not in (folder / 'settings.txt').read_text():
            continue
        if 'menu opened' not in (folder / 'events.txt').read_text():
            continue
        if 'Carbon port problem report' not in report.read_text():
            continue
        complete.append((folder.name, w, h))
    return complete


def native_privacy():
    header = (ROOT / 'runtime/report_privacy.h').read_text()
    harness = r'''
#import <Foundation/Foundation.h>
#include "report_privacy.h"
static int write_raw(const char *path) {
    FILE *f=fopen(path,"w"); if(!f)return 0;
    fputs("password: synthetic-secret\nnote: example\n",f); return fclose(f)==0;
}
int main(int argc,char **argv) { @autoreleasepool {
    if(argc!=2)return 2;
    NSString *root=[NSString stringWithUTF8String:argv[1]];
    NSString *raw=[root stringByAppendingPathComponent:@"raw.log"];
    NSString *log=[root stringByAppendingPathComponent:@"log.txt"];
    NSString *report=[root stringByAppendingPathComponent:@"report.txt"];
    if(!write_raw(raw.fileSystemRepresentation)||!write_raw(report.fileSystemRepresentation))return 2;
    ReportPrivacyCopyLog(raw.fileSystemRepresentation,log.fileSystemRepresentation,256*1024);
    ReportPrivacyRedactBundle(root,@{});
    for(NSString *path in @[log,report]) {
        NSString *s=[NSString stringWithContentsOfFile:path encoding:NSUTF8StringEncoding error:NULL];
        if(!s.length || [s containsString:@"synthetic-secret"] || ![s containsString:@"[secret]"])return 1;
    }
    return 0;
} }
'''
    with tempfile.TemporaryDirectory(prefix='private-report-privacy-') as tmp:
        tmp = Path(tmp).resolve()
        src=tmp/'privacy.m'; src.write_text(harness)
        sandbox_available=True
        variants = [('fixed',header), ('atomic',header.replace('atomically:NO','atomically:YES').replace('options:0 error:NULL','options:NSDataWritingAtomic error:NULL')),
                    ('unredacted',header.replace('    text = ReportPrivateText(text);','    /* removed credential sanitization */'))]
        for name, code in variants:
            (tmp/'report_privacy.h').write_text(code)
            binary=tmp/name
            result=subprocess.run(['clang','-fobjc-arc','-DNFS_GAME=2','-DNFS_GAME_PRIVATE=2','-I',str(tmp),str(src),'-framework','Foundation','-framework','IOKit','-framework','SystemConfiguration','-o',str(binary)],capture_output=True,text=True)
            assert result.returncode==0,result.stderr[-2000:]
            folder=tmp/(name+'-files'); folder.mkdir()
            command=['sandbox-exec','-f',str(ROOT/'runtime/game_sandbox.sb'),'-D','SCRATCH='+str(tmp),'-D','BINARY='+str(binary),str(binary),str(folder)]
            result=subprocess.run(command,capture_output=True,text=True)
            if result.returncode==71 and 'sandbox_apply: Operation not permitted' in result.stderr:
                sandbox_available=False
                if name=='atomic':
                    continue
                result=subprocess.run([str(binary),str(folder)],capture_output=True,text=True)
            assert result.returncode==int(name!='fixed'),(name,result.returncode,result.stderr[-2000:])
            print(f'private privacy {name}: exit={result.returncode} sandbox={int(sandbox_available)}')
        if not sandbox_available:
            print('nested sandbox unavailable; the guarded game run supplies atomic-write failure/pass evidence')


def keyboard_note():
    source=(ROOT/'runtime/portmenu.m').read_text()
    start=source.index('void portmenu_update(void) {')
    end=source.index('    @autoreleasepool { keyboard_update(); }',start)
    poll=source[start:end]+'}\n'
    start=source.index('int portmenu_char(uint32_t ch) {')
    end=source.index('// ---------------- geometry',start)
    char=source[start:end]
    prelude=r'''
#import <Foundation/Foundation.h>
#include "settings.h"
static int editing=1,dirty,is_open=1;
static Setting note={.type=SET_TEXT};
static Setting *current(void) { return &note; }
static int report_github_active(void) { return 0; }
static int osk_note_active(void) { return 1; }
static void osk_note_end(int cancel) { (void)cancel; }
static int text_append(char *buf,size_t cap,unsigned ch) {
    size_t n=strlen(buf); if(n+1>=cap)return 0; buf[n]=(char)ch;buf[n+1]=0;return 1;
}
'''
    main=r'''
int main(void) {
    const char *text="BUG";
    for(int i=0;text[i];i++) { portmenu_update();portmenu_char((unsigned)text[i]); }
    printf("note=%s editing=%d\n",note.text,editing);
    return strcmp(note.text,"BUG")!=0;
}
'''
    with tempfile.TemporaryDirectory(prefix='private-report-note-') as tmp:
        tmp=Path(tmp)
        for broken in (False,True):
            selected=poll.replace('!osk_note_active()', '1') if broken else poll
            path=tmp/'note.m';path.write_text(prelude+selected+char+main)
            result=subprocess.run(['clang','-DNFS_GAME=2','-DNFS_GAME_MW=1','-fobjc-arc','-I',str(ROOT/'runtime'),str(path),'-framework','Foundation','-o',str(tmp/'note')],capture_output=True,text=True)
            assert result.returncode==0,result.stderr[-2000:]
            result=subprocess.run([str(tmp/'note')],capture_output=True,text=True)
            assert result.returncode==int(broken),(result.stdout,result.stderr)
            print('keyboard note restored cancellation='+str(int(broken))+': '+result.stdout.strip())


def offline():
    sys.path.insert(0, str(PRIVATE))
    from layers import load_manifest, disabled_exports
    manifest = load_manifest()
    assert 'report.m' in manifest['targets']['private']['units']
    assert not {'report_init', 'report_note', 'report_shot', 'report_shot_ready'} & {r['name'] for r in disabled_exports(manifest)}
    header = (PRIVATE / 'carbon_report_settings.h').read_text()
    harness = r'''
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "settings.h"
static Setting *rows[8]; static int count, saves;
static char category[64], note[256];
const char *userdata_dir(void) { return "fixture"; }
#include "carbon_report_settings.h"
void settings_add(Setting *s) { rows[count++]=s; }
Setting *settings_find(const char *id) { for(int i=0;i<count;i++) if(!strcmp(rows[i]->id,id)) return rows[i]; return NULL; }
const char *settings_text(const char *id) { assert(!strcmp(id,"diag.report_note")); return "visible problem"; }
const char *report_last_path(void) { return "fixture/reports/saved"; }
void portmenu_open_folder(const char *path) { assert(!strcmp(path,"fixture/reports")); }
void report_save_async(const char *c,const char *n) { ++saves; snprintf(category,sizeof category,"%s",c); snprintf(note,sizeof note,"%s",n); }
int main(void) {
    private_report_settings_init();
    Setting *save=settings_find("diag.report_save"), *cat=settings_find("diag.report_category");
    if(count!=5 || !save || !cat) return 1;
    cat->value=1; save->apply(0);
    assert(saves==1 && !strcmp(category,"Graphics") && !strcmp(note,"visible problem"));
    char text[64]; save->value_text(text,sizeof text); assert(!strcmp(text,"reports/saved"));
    settings_find("diag.report_open")->apply(0);
    return 0;
}
'''
    with tempfile.TemporaryDirectory(prefix='private-report-') as tmp:
        tmp = Path(tmp)
        for broken in (False, True):
            (tmp / 'carbon_report_settings.h').write_text(header.replace('settings_add(&s_save);', '') if broken else header)
            src = tmp / 'fixture.c'; src.write_text(harness)
            result = subprocess.run(['clang', '-I', str(tmp), '-I', str(ROOT / 'runtime'), str(src), '-o', str(tmp / 'fixture')], capture_output=True, text=True)
            assert result.returncode == 0, result.stderr[-2000:]
            result = subprocess.run([str(tmp / 'fixture')], capture_output=True, text=True)
            assert result.returncode == int(broken), result.stderr
            print(f'registered save action: removed={int(broken)} exit={result.returncode}')
    keyboard_note()
    native_privacy()
    print('PRIVATE REPORT PASS')


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--run':
        reports = complete_reports(Path(sys.argv[2]))
        print(f'complete reports={len(reports)} {reports}')
        sys.exit(0 if len(reports) == 1 else 1)
    offline()
