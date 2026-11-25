"""Actual FF synthesis/translation and native token execution; no Metal device.

Good: 15 assertions: screen/viewport/depth/RHW, XYZ, declaration/cache semantics.
Broken: old rejection -> assertion 1/exit 1; omit RHW -> assertion 4/exit 1.
"""
from pathlib import Path
import subprocess
import sys
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
from build_private import ignored_output
from private_render import body,replace_body

sys.path.insert(0,str(HERE/"private_runtime"))
from layers import selected_source

def main():
    lib=HERE.parent/'host/shaders/build/libsmtranslate.a'
    if not lib.exists():print('SKIP: shader translator absent');return 3
    render=selected_source(HERE.parent/'runtime/render.m')
    assert 'POSITIONT data feeding a vs position input' in render
    ff=render[render.index('enum { RT_TEMP ='):]
    ff=ff[:ff.index('// Float constants of stage 0')]
    # The shared warm-up calls Metal compilation; this fixture executes tokens.
    ff=replace_body(ff,'ff_shader_warm','{}')
    source=r'''#include "d3d9_internal.h"
#include "sm_translate.h"
#include <math.h>
#include <stdlib.h>
Device dev;uint8_t *G;static Obj declaration;
int carbon_fe_scope;float carbon_fe_kx(void){return 1;}float carbon_fe_ky(void){return 1;}
Obj *obj(uint32_t g){return g==0x3000?&declaration:NULL;}
typedef struct {uint8_t stream,type,usage,index;uint16_t offset;} Elem;
'''+ 'static int decl_elems(Elem*out)'+body(render,'decl_elems')+'\n'+ff+r'''
static unsigned checks;
#define CHECK(v) do{++checks;if(!(v)){fprintf(stderr,"POSITIONT CHECK %u line %d failed: %s\n",checks,__LINE__,#v);return 1;}}while(0)
static int near4(const float*a,const float*b){for(int i=0;i<4;i++)if(fabsf(a[i]-b[i])>1e-5f)return 0;return 1;}
static void execute(Obj*vs,float c[256][4],const float*position,float*out){
 float r[8][256][4]={0};memcpy(r[RT_CONST],c,256*16);memcpy(r[RT_INPUT][0],position,16);
 for(unsigned i=1;i<vs->ntokens;){unsigned op=vs->tokens[i++]&0xffff;if(op==0xffff)break;if(op==31){i+=2;continue;}
  if(op!=1&&op!=5&&op!=6&&op!=9){fprintf(stderr,"unexpected FF opcode %u\n",op);exit(2);}
  uint32_t d=vs->tokens[i++];float a[2][4]={{0}};unsigned ns=(op==5||op==9)?2:1;
  for(unsigned s=0;s<ns;s++){uint32_t t=vs->tokens[i++];unsigned ty=((t>>28)&7)|((t>>11)&3)<<3;for(int k=0;k<4;k++)a[s][k]=r[ty][t&0x7ff][(t>>(16+2*k))&3];}
  float v[4];for(int k=0;k<4;k++){v[k]=op==1?a[0][k]:op==6?1/a[0][0]:op==5?a[0][k]*a[1][k]:0;if(op==9)for(int j=0;j<4;j++)v[k]+=a[0][j]*a[1][j];}
  for(int k=0;k<4;k++)if(d&(1u<<(16+k)))r[(d>>28)&7][d&0x7ff][k]=v[k];
 }memcpy(out,r[RT_RASTOUT][0],16);
}
static int translates(Obj*s){SmOptions opt;sm_default_options(&opt);SmResult result={0};int rc=sm_translate(s->tokens,s->ntokens,&opt,&result);if(rc)fprintf(stderr,"FF translation: %s\n",result.error);sm_result_free(&result);return rc==0;}
int main(void){G=calloc(1,65536);dev.fvf=0x104;dev.viewport[2]=dev.viewport[3]=64;float depth=1;memcpy(&dev.viewport[5],&depth,4);
 for(int i=0;i<512;i++)for(int k=0;k<16;k++)dev.transform[i][k]=(k%5==0);
 dev.tss[0][1]=dev.tss[0][2]=dev.tss[0][4]=dev.tss[0][5]=2;dev.tss[1][1]=1;
 Obj *vs,*ps;float vc[256][4]={0},pc[224][4]={0},out[4];CHECK(ff_shaders(&vs,&ps,vc,pc)==1);CHECK(translates(vs)&&translates(ps));CHECK(nff_cache==1);Obj *screen_vs=vs;
 float vertex[]={16,8,.25,.5},want[]={-1,1.5,.5,2};execute(vs,vc,vertex,out);CHECK(near4(out,want));
 // Offset viewport, depth remap, non-unit RHW; T&L matrices are ignored.
 dev.viewport[0]=10;dev.viewport[1]=20;dev.viewport[2]=100;dev.viewport[3]=80;depth=.25;memcpy(&dev.viewport[4],&depth,4);depth=.75;memcpy(&dev.viewport[5],&depth,4);memset(dev.transform,0,sizeof dev.transform);
 CHECK(ff_shaders(&vs,&ps,vc,pc)==1&&vs==screen_vs&&nff_cache==1);float shifted[]={35,40,.5,2},wanted[]={-.25,.25,.25,.5};execute(vs,vc,shifted,out);CHECK(near4(out,wanted));
 // The inverse viewport plus the existing VS half-pixel adjustment puts x/y
 // back at input pixel coordinates +0.5 in Metal's viewport.
 float sx=dev.viewport[0]+(out[0]/out[3]+1+1.0f/dev.viewport[2])*dev.viewport[2]/2;
 float sy=dev.viewport[1]+(1-out[1]/out[3]+1.0f/dev.viewport[3])*dev.viewport[3]/2;CHECK(fabsf(sx-35.5)<1e-5&&fabsf(sy-40.5)<1e-5);
 // XYZ still uses W/V/P and must not reuse the POSITIONT shader cache entry.
 dev.fvf=0x102;for(int i=0;i<512;i++)for(int k=0;k<16;k++)dev.transform[i][k]=(k%5==0);CHECK(ff_shaders(&vs,&ps,vc,pc)==1&&vs!=screen_vs&&nff_cache==2);CHECK(translates(vs));float clip[]={-.5,.5,.25,1};execute(vs,vc,clip,out);CHECK(near4(out,clip));
 // Explicit POSITIONT vertex declarations take the same conversion path.
 dev.decl=0x3000;declaration.decl_mem=0x4000;declaration.decl_n=3;M16(0x4000)=0;M8(0x4004)=3;M8(0x4006)=SM_USAGE_POSITIONT;M16(0x4008)=0;M16(0x400a)=16;M8(0x400c)=1;M8(0x400e)=SM_USAGE_TEXCOORD;M16(0x4010)=0xffff;
 CHECK(ff_shaders(&vs,&ps,vc,pc)==1&&vs==screen_vs);execute(vs,vc,shifted,out);CHECK(near4(out,wanted));
 dev.rs[137]=1;CHECK(ff_shaders(&vs,&ps,vc,pc)==1);dev.decl=0;CHECK(ff_shaders(&vs,&ps,vc,pc)==0);
 dev.decl=0x3000;dev.rs[137]=0;dev.viewport[2]=0;CHECK(ff_shaders(&vs,&ps,vc,pc)==0);
 printf("PRIVATE POSITIONT PASS checks=%u translation=VS+PS viewport_depth_rhw=1 cache_isolated=1\n",checks);return 0;}
'''
    out=ignored_output(HERE/'out/carbon/positiont_test')
    for mutant in ('good','reject','rhw'):
        text=source
        if mutant=='reject':text=text.replace('has_pos = has_pos_t = 1;', 'return 0;')
        if mutant=='rhw':text=text.replace('v[n++] = 6; v[n++] = ff_dst(RT_TEMP, 1, 8, 0);', 'v[n++] = 1; v[n++] = ff_dst(RT_TEMP, 1, 8, 0);')
        path=out/(mutant+'.m');binary=out/mutant;path.write_text(text)
        r=subprocess.run(['clang','-O1','-g','-fsanitize=address,undefined','-I',str(HERE),'-I',str(HERE.parent/'runtime'),'-I',str(HERE.parent/'host/shaders'),str(path),str(lib),'-lc++','-framework','Foundation','-o',str(binary)],capture_output=True,text=True)
        if r.returncode:raise RuntimeError(r.stderr[-2500:])
        r=subprocess.run([str(binary)],capture_output=True,text=True);(out/(mutant+'.log')).write_text(r.stdout+r.stderr)
        print(mutant+': exit='+str(r.returncode)+' '+r.stdout.strip()+r.stderr.strip());assert r.returncode==(0 if mutant=='good' else 1)
        if mutant!='good':assert 'POSITIONT CHECK' in r.stderr
    return 0


if __name__=='__main__':sys.exit(main())
