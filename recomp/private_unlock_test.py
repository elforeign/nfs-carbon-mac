"""Saved Gameplay unlock preference through runtime/settings.c.

Original session-only row: saved writes=0 vs required 2; persistence control
exits 1. Good: fresh default Off, saved On reloads, environment override wins;
On/Off each touch exactly one byte, 200 native-query boundaries once per launch.
Broken missing row/address/wide store/no saved preference each exits 1.
Native query results are also checked by private_addons_unlock_test.py.
"""
from pathlib import Path
import os
import subprocess
import sys
import tempfile

# Registry dependency: recomp/private_runtime/features/unlock.json
ROOT = Path(__file__).resolve().parents[1]
PRIVATE = ROOT / 'recomp/private_runtime'
SETTINGS_ROWS = {'gameplay.unlock_all': {'apply': 'carbon_unlock_apply'}}
SETTINGS_PROVIDERS = {'carbon_unlock_apply': 'carbon_unlock_settings.h'}
SETTINGS_FIXTURE = """
uint8_t *G;
"""

HARNESS = r'''
#include <assert.h>
#include <stdarg.h>
#include <stdlib.h>
#include "host.h"
#include "settings.h"
int diag_on;
static int reads, writes, queries, logs;
static int locked_paints, locked_rims, logged_flag;
uint8_t *G;
uint32_t galloc(uint32_t size) { assert(size==65536); return 0x10000; }
uint32_t call_guest(Cpu *c, uint32_t fn, int n, const uint32_t *a) {
    assert(c->ecx==0x1234 && c->esp==0x20000 && n==1 && *a<100);
    assert(fn==0x004B0FC0u || fn==0x004B10D0u); ++queries;
    return M8(0xA9E6C0u) ? 1 : *a%2;
}
void diag_event(const char *fmt, ...) {
    if (!strcmp(fmt,"unlock: locked paints %d rims %d flag=%u")) {
        va_list ap; va_start(ap,fmt);
        locked_paints=va_arg(ap,int); locked_rims=va_arg(ap,int);
        logged_flag=va_arg(ap,unsigned); va_end(ap);
    }
    ++logs;
}
void report_note(const char *fmt, ...) { (void)fmt; }
const char *app_pref(const char *key) {
    (void)key; ++reads; static char value[32];
    FILE *f=fopen(getenv("CADD_PREF_FILE"),"r");if(!f)return NULL;
    size_t n=fread(value,1,sizeof value-1,f);value[n]=0;fclose(f);return value;
}
void app_pref_set(const char *key, const char *v) {
    assert(!strcmp(key,"gameplay.unlock_all"));++writes;
    FILE *f=fopen(getenv("CADD_PREF_FILE"),"w");assert(f);fputs(v?v:"",f);fclose(f);
}
void app_pref_batch_begin(void) { }
void app_pref_batch_end(void) { }
int roots_x360_has(const char *feature) { (void)feature; return 1; }
#include "carbon_unlock_settings.h"
#define CHECK(x) do { if(!(x)) { fprintf(stderr,"UNLOCK CHECK line=%d: %s\n",__LINE__,#x); return 1; } } while(0)
static int changed_bytes(void) {
    int changed=0;
    for(unsigned i=0;i<0xB00000;i++) changed += G[i]!=0xA5;
    return changed;
}
int main(int argc, char **argv) {
    int env_on=argc>1 && atoi(argv[1])==1, loaded=argc>1 && atoi(argv[1])==2;
    G=malloc(0xB00000); CHECK(G); memset(G,0xA5,0xB00000);
    /* REGISTER */ carbon_unlock_settings_init();
    settings_init();
    CHECK(settings_count()==1);
    Setting *s=settings_find("gameplay.unlock_all"); CHECK(s);
    CHECK(s->category==SET_GAMEPLAY && s->type==SET_TOGGLE && s->def==0);
    CHECK(!strcmp(s->label,"Unlock All (changes your save)"));
    CHECK(!s->pref && !s->restart && s->apply==carbon_unlock_apply);
    CHECK(!strcmp(s->env,"NFS_CARBON_UNLOCKALL") && s->saved==loaded && reads==!env_on);
    CHECK(settings_get(s->id)==(env_on||loaded));
    M32(0xA8AD00u)=0;
    carbon_unlock_frame(); CHECK(M8(0xA9E6C0u)==(env_on||loaded) && queries==0);
    M32(0xA8AD00u)=0x1234;
    carbon_unlock_frame(); CHECK(queries==0); /* BOOT_DIAG off costs no queries. */
    diag_on=1; carbon_unlock_frame(); carbon_unlock_frame();
    CHECK(queries==200 && logs==1);
    CHECK(locked_paints==((env_on||loaded) ? 0 : 50) && locked_rims==((env_on||loaded) ? 0 : 50));
    CHECK(logged_flag==(env_on||loaded));
    if(!env_on) {
        settings_set(s,0);unsigned before_writes=writes;
        memset(G,0xA5,0xB00000);
        CHECK(settings_set(s,1)==1);
        CHECK(changed_bytes()==1 && M8(0xA9E6C0u)==1);
        memset(G,0xA5,0xB00000);
        CHECK(settings_set(s,0)==1);
        CHECK(changed_bytes()==1 && M8(0xA9E6C0u)==0);
        CHECK(writes==before_writes+2 && s->saved);
        puts("rows=1 default=Off saved=1 changed bytes: On=1 Off=1; queries=200 once");
    } else CHECK(s->locked && M8(0xA9E6C0u)==1);
    free(G); return 0;
}
'''


def main():
    settings = (PRIVATE / 'game_settings.h').read_text()
    assert settings.count('#include "carbon_unlock_settings.h"') == 1
    assert settings.count('    carbon_unlock_settings_init();') == 1
    diag = (PRIVATE / 'game_diagnostics.h').read_text()
    assert diag.count('carbon_unlock_frame();') == 1
    source = (PRIVATE / 'carbon_unlock_settings.h').read_text()
    with tempfile.TemporaryDirectory(prefix='private-unlock-') as td:
        td = Path(td)
        path = td / 'carbon_unlock_settings.h'
        path.write_text(source)
        harness = td / 'test.c'; harness.write_text(HARNESS)
        binary = td / 'test'
        cmd = ['clang', '-DNFS_GAME=2', '-I', str(td), '-I', str(ROOT / 'runtime'),
               '-I', str(ROOT / 'recomp'), str(harness), str(ROOT / 'runtime/settings.c'),
               '-Wl,-dead_strip', '-o', str(binary)]
        env = {k:v for k,v in os.environ.items() if not k.startswith(('NFS_', 'BOOT_'))}
        def run(value=0):
            result = subprocess.run(cmd, capture_output=True, text=True)
            assert result.returncode==0, result.stderr[-3000:]
            current = dict(env)
            pref=td/'prefs';pref.unlink(missing_ok=True)
            if value==2: pref.write_text('on')
            if value==1: pref.write_text('off')
            current['CADD_PREF_FILE']=str(pref)
            if value==1: current['NFS_CARBON_UNLOCKALL']='1'
            return subprocess.run([str(binary),str(value)], env=current, capture_output=True, text=True)
        for value in (0,1,2):  # fresh default, env over saved Off, saved On
            result=run(value); assert result.returncode==0, result.stdout+result.stderr
            if result.stdout: print(result.stdout.strip())
        for label, old, new in (
            ('missing-registration','/* REGISTER */ carbon_unlock_settings_init();','/* no row in baseline */'),
            ('session-only','.def=0, .env=','.def=0, .pref="", .env='),
            ('wrong-address','M8(0x00A9E6C0u) =','M8(0x00A9E6C1u) ='),
            ('wide-store','M8(0x00A9E6C0u) =','M32(0x00A9E6C0u) ='),
        ):
            path.write_text(source.replace(old,new))
            harness.write_text(HARNESS.replace(old,new))
            result=run(); assert result.returncode==1 and 'UNLOCK CHECK' in result.stderr, label+result.stderr
            print(f'negative {label}: good exit=0 / broken exit=1')
        print('PRIVATE UNLOCK PASS: original writes=0 / required=2; saved byte toggle')
    return 0


if __name__=='__main__':
    sys.exit(main())
