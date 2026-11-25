"""Carbon glow coverage must compile at load, including a fresh profile.

Production catalogue/lookup/cache/submission with a counting compiler double:
fixed cold draw compiles 0; original catalogue (warmup removed) 3, exit 1.
Warm history: fixed glow records 3; original whitelist 0, exit 1.
Synthetic SM2/SM3 programs; no game image, Metal device or history reads.
Autodiscovered by offline_tests.sh. Private source absent: exit 3.
"""
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'recomp'))
sys.path.insert(0, str(ROOT / 'recomp/private_runtime'))
from private_render import body
from layers import selected_source

PRELUDE = r'''
#import <Foundation/Foundation.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "host/shaders/sm_translate.h"
#include "recomp/private_runtime/carbon_ao_glow.h"
enum { HL_RECEIVER=0x10000, HL_CASTER=0x20000, HL_VARIANTS=0x30000 };
enum { MAT_VARIANT_WATER=0x100, MAT_VARIANT_GLASS, MAT_VARIANT_TREES,
 MAT_VARIANT_BONE, MAT_VARIANT_SOFT_SMOKE, MAT_VARIANT_SOFT_SMOKE_RESOLVED,
 MAT_VARIANT_SOFT_SMOKE_LATE, MAT_VARIANT_CARBON_LAMP, MAT_VARIANT_HEADLAMP_CLEAR,
 MAT_VARIANT_ROAD_FILM, MAT_VARIANT_REAL_GLASS, MAT_VARIANT_REAL_CHROME,
 MAT_VARIANT_CLEARCOAT, MAT_VARIANT_RAIN_COVER=0x110,
 MAT_VARIANT_RAIN_COVER_FILM, MAT_VARIANT_AUX=0x200 };
typedef struct {
 uint64_t key; SmResult refl; volatile int pending; int ok; dispatch_semaphore_t ready;
 uint32_t *tokens, ntokens; SmOptions opt; uint32_t variant;
} ShaderEntry;
typedef struct {
 uint64_t tokens_hash,last_key,memo_key[2]; int last_idx,memo_next;
 uint8_t memo_opt[2][48]; uint32_t memo_variant[2],vc_serial;
 uint32_t *tokens,ntokens;
} Obj;
static ShaderEntry **shaders;
static int nshaders,capshaders,diag_on,loading=1,draw_compiles;
static unsigned long long stat_sync_shader;
static dispatch_queue_t shader_q,shader_workers[4];
static const char *scratch;
static const char *userdata_dir(void) { return scratch; }
static void diag_event(const char *fmt,...) {}
static int headlights_enabled(void) { return 0; }
static int rain_cover_on(void) { return 0; }
static int roadfilm_enabled(void) { return 0; }
static int realworld_materials_mode(void) { return 0; }
static int roadfilm_shader_hash(uint64_t h) { return 0; }
static int clearcoat_shader_hash(uint64_t h) { return 0; }
uint32_t carbon_coat_cache_variant(uint64_t h,uint32_t v) { return v; }
void carbon_coat_record_key(uint64_t b,uint64_t h,uint32_t v) {}
uint32_t *carbon_daynight_shader(const uint32_t *t,uint32_t n,uint32_t *p) { return NULL; }
uint32_t *carbon_coat_shader(const uint32_t *t,uint32_t n,uint32_t *p) { return NULL; }
uint32_t *carbon_road_headlight_shader(const uint32_t *t,uint32_t n,const uint32_t *c,uint32_t k,uint32_t *p) { return NULL; }
static void compile_entry(ShaderEntry *e) {
 if (!loading) ++draw_compiles;
 e->ok=1;
 __atomic_store_n(&e->pending,0,__ATOMIC_RELEASE);
 dispatch_semaphore_signal(e->ready);
}
static char *shader_replacement(ShaderEntry *e) {
 return e->variant==MAT_VARIANT_AO_GLOW ? carbon_ao_glow_shader(e->refl.msl) : NULL;
}
static void shader_catalogue_warm(void) {}
'''

MAIN = r'''
int main(int argc,char **argv) { @autoreleasepool {
 scratch=argv[1];shader_cache_warm();
 Obj objects[4]={0};
 for(int i=0;i<4;++i) {
  FILE *f=fopen(argv[i+2],"rb");if(!f)return 2;
  fseek(f,0,SEEK_END);long bytes=ftell(f);rewind(f);
  uint32_t *blob=malloc(bytes+8);blob[0]=0xFEFF0901u;blob[1]=0;
  if(fread(blob+2,1,bytes,f)!=(size_t)bytes)return 2;fclose(f);
  objects[i].tokens=blob+2;objects[i].ntokens=bytes/4;
  shader_preload_blob(blob,(uint32_t)(bytes/4+2),i ? "IDI_PARTICLES_FX":"IDI_WORLD_FX");
 }
 int warm=0;
 for(int i=0;i<nshaders;++i)warm+=shaders[i]->variant==MAT_VARIANT_AO_GLOW;
 if(warm>3)return 2; // the vertex program must never get a pixel coverage variant
 loading=0;
 SmOptions opt;sm_default_options(&opt);
 for(int i=0;i<3;++i) {
  ShaderEntry *e=get_shader_variant(&objects[i],&opt,MAT_VARIANT_AO_GLOW);
  if(!e->ok || e->pending)return 2;
  // Ignore an unrelated bound cube, as on the environment-face draw path.
  opt.sampler_type[7]=SM_TEX_CUBE;
  if(get_shader_variant(&objects[i],&opt,MAT_VARIANT_AO_GLOW)!=e)return 2;
 }
 printf("cold: glow_ready=%d draw_compiles=%d\n",warm,draw_compiles);
 if(draw_compiles || warm!=3)return 1;
 // A fresh process index must accept records written by a demand lookup too.
 loading=1;nshaders=capshaders=0;shaders=NULL;memset(vcache,0,sizeof vcache);
 shader_cache_warm();warm=0;
 for(int i=0;i<nshaders;++i)warm+=shaders[i]->variant==MAT_VARIANT_AO_GLOW;
 printf("history: glow_ready=%d\n",warm);
 if(warm!=3)return 1;
 loading=0;draw_compiles=0;
 for(int i=0;i<3;++i) {
  objects[i].last_key=0;memset(objects[i].memo_key,0,sizeof objects[i].memo_key);
  if(!get_shader_variant(&objects[i],&opt,MAT_VARIANT_AO_GLOW)->ok)return 2;
 }
 printf("history: draw_compiles=%d\n",draw_compiles);
 return draw_compiles ? 1:0;
}}
'''


def main():
    if not (ROOT / 'recomp/private_runtime/carbon_ao_glow.h').is_file():
        return 3
    source = selected_source(ROOT / 'runtime/render.m')
    assert 'e->variant == MAT_VARIANT_AO_GLOW ? carbon_ao_glow_shader(e->refl.msl) :' in source

    def span(start, end):
        return source.split(start, 1)[1].split(end, 1)[0]

    code = PRELUDE
    code += 'static uint64_t fnv' + span('static uint64_t fnv', '// ').split('\n}\n', 1)[0] + '\n}\n'
    code += span('// BEGIN offline shader options test\n', '// END offline shader options test')
    code += 'static ShaderEntry *new_entry' + span('static ShaderEntry *new_entry', '// BEGIN offline shader scheduling test')
    code += 'static void shader_submit(ShaderEntry *e)' + body(source, 'shader_submit')
    code += 'static void cache_path' + span('static void cache_path', '// Lookup cache in front')
    code += 'typedef struct { uint32_t serial, variant;' + span('typedef struct { uint32_t serial, variant;', '// The game\'s fx_2_0 resources')
    code += 'static void shader_preload_finish(Obj *s, const SmOptions *opt, uint32_t variant)' + body(source, 'shader_preload_finish')
    code += 'static void shader_preload_variant(Obj *s, const SmOptions *opt, uint32_t variant)' + body(source, 'shader_preload_variant')
    code += 'static void shader_preload_blob(const uint32_t *words, uint32_t count, const char *name)' + body(source, 'shader_preload_blob')
    code += MAIN
    warm = 'if (v >> 16 == 0xFFFFu) shader_preload_variant(&s, &opt, MAT_VARIANT_AO_GLOW);'
    accept = 'if (variant == MAT_VARIANT_AO_GLOW) return 1;'
    assert warm in code and accept in code

    def run(args, expected=0):
        p = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, timeout=90)
        assert p.returncode == expected, (p.returncode, p.stdout[-2000:], p.stderr[-2000:])
        return p.stdout.strip()

    with tempfile.TemporaryDirectory(prefix='private-compilehitch-') as d:
        tmp = Path(d)
        objects = []
        for name in ('sm_parse.cpp', 'sm_msl.cpp'):
            obj = tmp / (name + '.o')
            run(['clang++', '-std=c++17', '-O1', '-c', str(ROOT / 'host/shaders' / name), '-o', str(obj)])
            objects.append(str(obj))
        fixtures = ROOT / 'host/shaders/testdata_synth/synth'
        inputs = [str(fixtures / n) for n in ('ps20_misc.bin', 'ps30_loop.bin', 'ps13_misc.bin', 'vs20_math.bin')]
        cases = [('fixed', code, 0), ('original-catalogue', code.replace(warm, ''), 1),
                 ('original-whitelist', code.replace(accept, ''), 1)]
        for label, text, expected in cases:
            path = tmp / (label + '.m'); path.write_text(text)
            exe = tmp / label
            run(['clang', '-O1', '-w', '-fobjc-arc', '-I', str(ROOT), str(path), *objects,
                 '-framework', 'Foundation', '-lc++', '-o', str(exe)])
            profile = tmp / (label + '-profile'); profile.mkdir()
            result = run([str(exe), str(profile), *inputs], expected)
            print(label + ': ' + result.replace('\n', '; '))
    print('PRIVATE COMPILE HITCH PASS')
    return 0


if __name__ == '__main__':
    sys.exit(main())
