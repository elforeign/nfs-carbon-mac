"""Carbon pkg steps through the generated native runtime and synthetic guest bytes.

Good: 12 cases / 0 failures (control transfer: 851). Broken first-loaded
reader: fails check 428 / exit 1. Real parser, fake wall clock, no game/window/GPU.
Strict/non-strict 1800-tick limits, prefix/case, retry/release, null manager,
control transfer and dialog precedence run in fresh processes. Absent build: 3.
Split waits send zero keys through timeout; omitting the barrier sends one and fails.
Diagnostic fixtures check each key's own tick, copied native UTF-16 labels
after pending storage is freed, dialog replacement, unchanged guest bytes at
key sampling and silence when disabled. Missing-key/wrong-source producers
fail at checks 15/17, each exit 1.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import private_input_test as fixture
from build_private import ignored_output

# Reuse the Win32 fixture's real key/message path and generated link selection.
HARNESS = fixture.HARNESS.split('int main(int argc,char**argv)')[0] + r'''
static unsigned done, timeouts, diag_records, dialog_records;
static uint64_t control_tick;
static const char *expected_control;
static const char *expected_dialog="Native dialog Ω\\nSecond line";
static char last_control[128], last_dialog[512];
void private_script_event(const char *format, ...) {
 char line[512];va_list ap;va_start(ap,format);vsnprintf(line,sizeof line,format,ap);va_end(ap);
 ++diag_records;
 if(!strncmp(line,"screen: ",8)){control_tick=fake_ns;snprintf(last_control,sizeof last_control,"%s",line+8);}
 if(!strncmp(line,"dialog: text=",13)){++dialog_records;snprintf(last_dialog,sizeof last_dialog,"%s",line+13);}
 if(expected_control&&!strncmp(line,"scripted key ",13)) {
  CHECK(control_tick==fake_ns);CHECK(!strcmp(last_control,expected_control));
  if(!strcmp(expected_control,"FeDialog.fng"))CHECK(!strcmp(last_dialog,expected_dialog));
 }
 if(strstr(line,"script step ")&&strstr(line," done after "))++done;
 if(strstr(line,"script: package timeout want="))++timeouts;
 if(strstr(line,"script: splitwait:")&&strstr(line," timeout; input stopped"))++timeouts;
 puts(line);
}
static void tick(Cpu *c,unsigned n) {
 for(unsigned i=0;i<n;i++){fake_ns+=16666667;fixture_present();messages(c);}
}
static void packages(void) {
 /* Load order A -> B -> dialog; control order dialog -> B -> A. */
 M32(0x00A97A78)=0x8000;M32(0x8000)=0x9000;
 M32(0x90E0)=0xA000;M32(0xA004)=0xA100;M32(0xA104)=0xA200;
 M32(0x90E4)=0xA200;M32(0xA208)=0xA100;M32(0xA108)=0xA000;
 M32(0xA00C)=0xB000;strcpy((char*)G+0xB000,"FeMainMenu.fng");
 M32(0xA10C)=0xB100;strcpy((char*)G+0xB100,"FeMainMenu_Sub.fng");
 M32(0xA20C)=0xB200;strcpy((char*)G+0xB200,"FeDialog.fng");
 M32(0xA220)=1;
}
static void dialog(void) {
 M32(0x00A97B18)=0xE000;M32(0xE010)=0xD000;
 const char *text="Native dialog ?\nSecond line";
 for(unsigned i=0;i<=strlen(text);++i)M16(0xD000+2*i)=text[i]=='?'?0x3A9:(uint8_t)text[i];
}
void carbon_script_dialog_init(Cpu *,void (*)(Cpu *));
static unsigned init_calls;
static void native_dialog_init(Cpu *c) {
 CHECK(c->eax==0x12345678);++init_calls;c->eax=0x87654321;
 /* Like the native initializer, consume and free the pending label. */
 M32(0x00A97B18)=0;memset(G+0xD000,0,128);memset(G+0xE000,0,0x20);
}
int main(int argc,char **argv) {
 CHECK(argc==2);G=mmap(NULL,1ull<<32,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANON,-1,0);CHECK(G!=MAP_FAILED);
 threads_init();Cpu c={0};c.fs_base=0x7000;
 M32(0x3000)=48;M32(0x3008)=host_fn(wndproc,"synthetic script window");
 uint32_t atom=api(&c,win32_user32,"RegisterClassExA",1,0x3000u);CHECK(atom);
 hwnd=api(&c,win32_user32,"CreateWindowExA",12,0u,atom,0u,0u,0u,0u,640u,480u,0u,0u,0u,0u);CHECK(hwnd);messages(&c);
 extern int diag_on;diag_on=1;
 if(!strcmp(argv[1],"witness")||!strcmp(argv[1],"replacement")||!strcmp(argv[1],"frame_witness")||!strcmp(argv[1],"quiet")) {
  packages();dialog();
  if(!strcmp(argv[1],"quiet"))diag_on=0;
  else expected_control="FeDialog.fng";
  c.eax=0x12345678;carbon_script_dialog_init(&c,native_dialog_init);
  CHECK(init_calls==1&&c.eax==0x87654321&&M32(0x00A97B18)==0);
  unsigned char before[0x8000];memcpy(before,G+0x8000,sizeof before);
  tick(&c,2);CHECK(downs==1&&ups==0);CHECK(!memcmp(before,G+0x8000,sizeof before));
  if(diag_on){CHECK(dialog_records>=1);CHECK(!strcmp(last_dialog,expected_dialog));}
  if(!strcmp(argv[1],"replacement")) {
   dialog();const char *text="Different dialog";
   for(unsigned i=0;i<=strlen(text);++i)M16(0xD000+2*i)=(uint8_t)text[i];
   expected_dialog=text;c.eax=0x12345678;carbon_script_dialog_init(&c,native_dialog_init);
   CHECK(init_calls==2&&c.eax==0x87654321);CHECK(!strcmp(last_dialog,expected_dialog));
  } else {
   /* Move control before release: a transition-only observer is stale. */
   M32(0xA220)=0;M32(0xA020)=1;expected_control=diag_on?"FeMainMenu.fng":NULL;
  }
  tick(&c,5);CHECK(downs==1&&ups==1);
  if(diag_on)CHECK(!strcmp(last_control,expected_control));
  else CHECK(diag_records==0);
 } else if(!strcmp(argv[1],"control")) {
  packages();tick(&c,200);CHECK(done==0&&downs==0);
  /* The menu behind a controlling dialog must not satisfy the step. */
  M32(0xA020)=1;tick(&c,200);CHECK(done==0&&downs==0);
  M32(0xA220)=0;tick(&c,10);CHECK(done==1&&downs==1&&ups==1);
  CHECK(timeouts==0);
 } else if(!strcmp(argv[1],"retry")) {
  packages();tick(&c,150);CHECK(downs==0&&done==0);
  tick(&c,1);CHECK(downs==1&&ups==0&&done==0);
  tick(&c,4);CHECK(ups==1);
  tick(&c,145);CHECK(downs==1);
  tick(&c,1);CHECK(downs==2);
  tick(&c,4);CHECK(ups==2);
  M32(0xA220)=0;M32(0xA020)=1;tick(&c,10);CHECK(done==1&&downs==3&&ups==3);
 } else if(!strcmp(argv[1],"splitwait")) {
  packages();tick(&c,1800);CHECK(done==0&&downs==0&&timeouts==0);
  tick(&c,1);CHECK(done==0&&downs==0&&timeouts==1);
  tick(&c,50);CHECK(done==0&&downs==0&&timeouts==1);
 } else if(!strcmp(argv[1],"strict")||!strcmp(argv[1],"nonstrict")) {
  packages();tick(&c,1800);CHECK(done==0&&timeouts==0);
  tick(&c,1);
  if(!strcmp(argv[1],"strict")){CHECK(done==0&&timeouts==1);tick(&c,500);CHECK(downs==0&&done==0&&timeouts==1);}
  else{CHECK(done==1&&timeouts==0);tick(&c,10);CHECK(downs==1&&ups==1);}
 } else if(!strcmp(argv[1],"null")) {
  tick(&c,100);CHECK(done==0&&downs==0);
  M32(0x00A97A78)=0x8000;M32(0x8000)=0xFFFFFF28;tick(&c,100);CHECK(done==0);
  packages();tick(&c,10);CHECK(done==1&&downs==1&&ups==1);
 } else if(!strcmp(argv[1],"order")) {
  packages();M32(0xA020)=1;tick(&c,10);CHECK(done==1&&downs==1&&ups==1);
 } else if(!strcmp(argv[1],"cycle")) {
  packages();M32(0xA220)=0;M32(0xA008)=0xA200;tick(&c,100);CHECK(done==0&&downs==0);
  M32(0xA120)=1;tick(&c,10);CHECK(done==1&&downs==1&&ups==1);
 } else CHECK(0);
 printf("PRIVATE SCRIPT PASS %s checks=%u done=%u timeout=%u keys=%u/%u\n",argv[1],checks,done,timeouts,downs,ups);
 return 0;
}
'''


def main():
    root = HERE / 'out/carbon'
    if not all((root / name).is_file() for name in ('link_command.json', 'NFSC.a', 'runtime/disabled_providers.m.o')):
        print('SKIP: private runtime build absent'); return 3
    command = json.loads((root / 'link_command.json').read_text())
    if [Path(x).resolve() for x in command if x.endswith('/NFSC.a')] != [(root / 'NFSC.a').resolve()]:
        print('SKIP: private runtime belongs to another checkout'); return 3
    # These are the production inputs staged by features/script.json.
    for name in ('game_script.h', 'carbon_fe_control.h'):
        assert (root / 'runtime' / name).read_bytes() == (HERE / 'private_runtime' / name).read_bytes(), 'rebuild Carbon: ' + name
    registry = json.loads((HERE / 'private_runtime/features' / 'script.json').read_text())
    assert registry['bindings']['carbon_fe_control.h']['sha256'] == hashlib.sha256((HERE / 'private_runtime/carbon_fe_control.h').read_bytes()).hexdigest()
    # The fixture's initializer must also be installed on the native entry.
    hook = json.loads((HERE / 'private_runtime/hooks/fresh_start.json').read_text())
    assert len(hook['hooks']) == 1
    record = hook['hooks'][0]
    assert record['address'] == '005C5330' and record['provider'] == 'carbon_script_dialog_init'
    assert record['image_sha256'] == json.loads((root / 'image.json').read_text())['sha256']
    out = ignored_output(root / 'script_test')
    original_selected = fixture.selected_source
    fixture.HARNESS = HARNESS
    for mutant in ('good', 'first_loaded', 'no_key_witness', 'wrong_dialog_label', 'no_split_wait'):
        def selected(path):
            source = original_selected(path)
            if path.name == 'user32.m':
                reader = (root / 'runtime/carbon_fe_control.h').read_text()
                if mutant == 'first_loaded':
                    reader = reader.replace('M32(engine + 0xE4)', 'M32(engine + 0xE0)').replace('M32(p + 8)', 'M32(p + 4)').replace('if (M32(p + 0x20))', 'if (1)')
                if mutant == 'wrong_dialog_label':
                    assert 'M32(pending + 0x10)' in reader
                    reader = reader.replace('M32(pending + 0x10)', 'M32(pending + 0x14)')
                source = source.replace('#include "carbon_fe_control.h"', reader)
                source = source.replace('#include "carbon_soak.h"', (root / 'runtime/carbon_soak.h').read_text())
                source = 'extern void private_script_event(const char *, ...);\n' + source.replace('diag_event(', 'private_script_event(')
                if mutant == 'no_key_witness':
                    assert 'if (diag_on) carbon_script_key_witness();' in source
                    source = source.replace('if (diag_on) carbon_script_key_witness();', '')
                if mutant == 'no_split_wait':
                    assert '!strncmp(tok, "splitwait:", 10)' in source
                    source = source.replace('!strncmp(tok, "splitwait:", 10)', '0')
            return source
        fixture.selected_source = selected
        folder = out / mutant; folder.mkdir(exist_ok=True)
        binary = fixture.build(root, folder, 'good')
        cases = ('control', 'retry', 'strict', 'nonstrict', 'null', 'order', 'cycle', 'witness', 'replacement', 'frame_witness', 'quiet', 'splitwait') if mutant == 'good' else ('control',) if mutant == 'first_loaded' else ('splitwait',) if mutant == 'no_split_wait' else ('witness',)
        for case in cases:
            want = {'null': 'FeDialog', 'order': 'FeDialog', 'cycle': 'FeMainMenu_Sub', 'witness': 'FeDialog', 'replacement': 'FeDialog', 'quiet': 'FeDialog'}.get(case, 'fEmAiNmEnU.fnG' if case in ('control', 'retry') else 'NeverAppears')
            spec = 'seq:pkg:' + want + (':RETURN' if case == 'retry' else '') + ',RETURN'
            if case == 'frame_witness': spec = '2:RETURN'
            if case == 'splitwait': spec = 'seq:splitwait:unknown,RETURN'
            env = dict(os.environ, BOOT_HEADLESS='1', BOOT_KEYS=spec, BOOT_KEYS_STRICT='0' if case == 'nonstrict' else '1', BOOT_USERDATA=str(folder / 'userdata'), NFS_AUDIO='null', NFS_RUMBLE='off')
            run = subprocess.run([str(binary), case], env=env, capture_output=True, text=True, timeout=30)
            (folder / (case + '.log')).write_text(run.stdout + run.stderr)
            print(mutant + '/' + case + ': exit=' + str(run.returncode) + ' ' + (run.stdout.strip().splitlines()[-1] if run.returncode == 0 else run.stderr.strip().splitlines()[-1]))
            assert run.returncode == (0 if mutant == 'good' else 1), run.stderr[-3000:]
            if mutant != 'good': assert 'INPUT CHECK' in run.stderr
            if case == 'strict': assert 'script: package timeout want=NeverAppears actual=FeDialog.fng; input stopped' in run.stderr
    return 0


if __name__ == '__main__':
    sys.exit(main())
