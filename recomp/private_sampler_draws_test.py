"""Carbon draw diagnostic, native fixture without a game or GPU.

Good: 3 selected / 3 unselected frame checks; disabled = 0 parser calls.
Good: 4 reported stages (ps0/ps3/ps7/vs2), 3 shader reads, exact bias bits,
anisotropy 16/1 and mip chains 10/9/1/6 including a missing bound object.
Broken selector stub, missing anisotropy, W address or vertex stages each exit 1.
Missing private output exits 3. Registered by offline_tests.sh autodiscovery.
"""
from pathlib import Path
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from private_render import body


def main():
    if not (HERE / 'out/carbon/runtime/render.m').is_file():
        print('SKIP private sampler diagnostic: no Carbon outputs')
        return 3
    selector = body((HERE / 'private_runtime/game_diagnostics.h').read_text(),
                    'diag_draw_frame_wanted')
    fields = (HERE / 'private_runtime/sampler_draws.h').read_text()
    frames = (HERE / 'private_runtime/frame_shots.h').read_text().split('static int private_shot_due')[0]
    source = r'''
#import <Foundation/Foundation.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
@interface FixtureTexture : NSObject
@property NSUInteger mipmapLevelCount;
@end
@implementation FixtureTexture
@end
typedef struct { FixtureTexture *tex; } RenderTex;
typedef struct { unsigned w,h,d,levels; int kind; RenderTex *gpu; } Obj;
typedef struct { int n_samplers; struct { unsigned reg; } samplers[16]; } SmResult;
typedef struct { SmResult refl; } Shader;
static struct { uint32_t ss[20][14],tex[20]; } dev;
static Obj objects[3];
static Obj *obj(unsigned g) { return g>=1 && g<=3 ? &objects[g-1] : NULL; }
static int diag_on,parser_calls;
''' + frames.replace('const char *p=getenv(list_env);', '++parser_calls; const char *p=getenv(list_env);') + r'''
int diag_draw_frame_wanted(uint64_t frame)
''' + selector + r'''
static void dump(FILE *df, Shader *pse, Shader *vse)
''' + fields + r'''
int main(void) { @autoreleasepool {
 setenv("BOOT_DIAG_DRAWS","10,20,30",1);
 if(diag_draw_frame_wanted(10) || parser_calls)return 1;
 diag_on=1;
 for(unsigned i=10;i<=30;i+=10) {
   if(!diag_draw_frame_wanted(i) || !diag_draw_frame_wanted(i))return 1;
   if(diag_draw_frame_wanted(i+1))return 1;
 }
 if(parser_calls!=6)return 1;
 FILE *df=tmpfile();if(!df)return 2;
 Shader ps={.refl={.n_samplers=2,.samplers={{0},{7}}}};
 Shader vs={.refl={.n_samplers=1,.samplers={{2}}}};
 FixtureTexture *texture=[FixtureTexture new]; texture.mipmapLevelCount=9;
 RenderTex gpu={texture};
 objects[0]=(Obj){512,512,1,10,3,&gpu};
 objects[1]=(Obj){256,128,1,1,3,NULL};
 objects[2]=(Obj){32,32,32,6,5,NULL};
 dev.tex[0]=1;dev.tex[3]=2;dev.tex[7]=99;dev.tex[18]=3;
 for(int s=0;s<20;++s){
   dev.ss[s][5]=2;dev.ss[s][6]=3;dev.ss[s][7]=2;dev.ss[s][10]=16;
   dev.ss[s][1]=1;dev.ss[s][2]=3;dev.ss[s][3]=2;dev.ss[s][8]=0xbf400000;
 }
 dev.ss[3][10]=1;
 dump(df,&ps,&vs);rewind(df);char output[4096]={0};fread(output,1,sizeof output-1,df);fclose(df);
 if(!strstr(output,"sampler ps0 read=1 tex=00000001 kind=3 size=512x512x1 levels=10 gpu_levels=9 min=3 mag=2 mip=2 aniso=16 bias=-0.75 bias_bits=BF400000 maxmip=0 addr=1,3,2\n"))return 1;
 if(!strstr(output,"sampler ps3 read=0") || !strstr(output,"aniso=1 ") ||
    !strstr(output,"sampler ps7 read=1 tex=00000063 kind=0 size=0x0x0 levels=0 gpu_levels=0") ||
    !strstr(output,"sampler vs2 read=1 tex=00000003 kind=5 size=32x32x32 levels=6"))return 1;
 unsigned rows=0;for(char *p=output;*p;++p)if(*p=='\n')++rows;
 if(rows!=4)return 1;
 printf("PRIVATE SAMPLER PASS selected=3 unselected=3 parser_calls=%d stages=%u reads=3\n",parser_calls,rows);
 return 0;
}}
'''
    with tempfile.TemporaryDirectory(prefix='private-sampler-') as td:
        root = Path(td)
        for variant in ('good', 'stub', 'anisotropy', 'address-w', 'vertex'):
            mutant = source
            if variant == 'stub':
                mutant = mutant.replace(selector, '{ return 0; }')
            elif variant == 'anisotropy':
                mutant = mutant.replace('state[10], bias', '1u, bias')
            elif variant == 'address-w':
                mutant = mutant.replace('state[2], state[3]', 'state[2], state[2]')
            elif variant == 'vertex':
                mutant = mutant.replace('slot < 20', 'slot < 16')
            path = root / 'fixture.m'
            path.write_text(mutant)
            build = subprocess.run(['clang', '-fobjc-arc', '-O1', '-fsanitize=address,undefined',
                                    '-framework', 'Foundation', str(path), '-o', str(root / 'fixture')],
                                   capture_output=True, text=True)
            assert build.returncode == 0, build.stderr[-2000:]
            result = subprocess.run([str(root / 'fixture')], capture_output=True, text=True)
            assert result.returncode == (0 if variant == 'good' else 1), result.stderr[-2000:]
            print(f'{variant}: exit={result.returncode} {result.stdout.strip()}')
    renderer = (HERE.parent / 'runtime/render.m').read_text()
    assert '#if NFS_GAME == NFS_GAME_PRIVATE\n#include "private_sampler_draws.inc"\n#endif' in renderer
    assert 'if (texdump_frame()) {' in renderer
    return 0


if __name__ == '__main__':
    sys.exit(main())
