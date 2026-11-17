"""Actual Carbon effect -> native constant setters, no GPU/window/game.

Good: 31 checks; zero exposure fails check 8 and wrong matrix packing fails
check 13 (exit 1 each). The daylight c240..242 upload preserves neighbors and
increments the device version; shifting it to c239 fails check 25. Pixel
c14..16 upload through slot 109 preserves c13/c17 and increments ver_psc;
shifting it to c13 fails check 29. Six HDR
formats map without conversion; replacing
RGBA16Float by BGRA8 fails format 113. No Metal device is created.
Missing private effect corpus skips with exit 3.
"""
from pathlib import Path
import os
import subprocess
import sys
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
from build_private import ignored_output
sys.path.insert(0,str(HERE/"private_runtime"))
from layers import selected_source
from private_render import body


def main():
    root=HERE/'out/carbon';files=sorted((root/'effects').glob('*.bin'))
    if not files:print('SKIP: private effect corpus absent');return 3
    hdr=next(p for p in files if b'finalhdrpass\0' in p.read_bytes())
    car=next(p for p in files if b'car\0' in p.read_bytes() and b'cvVinylScales\0' in p.read_bytes())
    source=selected_source(root/'runtime/d3dx_effect.c')
    prefix=source.split('// commit: CommitChanges',1)[0]
    driver=selected_source(HERE.parent/'runtime/d3d9.m')
    constants=driver.split('#define CONST_FN(',1)[1].split('static int v_SetStreamSource',1)[0]
    constants='#define CONST_FN('+constants
    setter='static Effect *fixture_fx;\n#define FX fixture_fx\nstatic int e_SetFloat(Cpu*c)'+body(source,'e_SetFloat')
    setter+='\nstatic int set_matrix_common(Cpu*c,int transpose,int array,int pointers)'+body(source,'set_matrix_common')
    harness=r'''
#include <assert.h>
#include <math.h>
uint8_t *G;int boot_trace,diag_on;static uint32_t allocated=0x10000;static unsigned checks;
int carbon_fe_scope;float carbon_fe_kx(void){return 1;}
uint64_t diag_current_frame(void){return 0;}int diag_frame_wanted(uint64_t f,const char*n){(void)f;(void)n;return 0;}
void diag_event(const char*fmt,...){(void)fmt;}
uint32_t galloc(uint32_t n){uint32_t p=allocated;allocated+=(n+15)&~15u;assert(allocated<(1<<26));return p;}
uint32_t gstr(const char*s){uint32_t p=galloc(strlen(s)+1);strcpy((char*)G+p,s);return p;}
float lighting_inv_shadow_strength(float f){(void)f;return 0;}
static struct {float vsc[256][4],psc[224][4];int32_t vsi[16][4],psi[16][4];uint32_t vsb[16],psb[16];uint32_t ver_vsc,ver_psc,ver_vsi,ver_psi,ver_vsb,ver_psb;} dev;
CONSTANTS
uint32_t call_guest(Cpu*c,uint32_t fn,int n,const uint32_t*a){uint32_t saved=c->esp;c->esp-=4*(n+1);M32(c->esp)=0xfeed;for(int k=0;k<n;k++)M32(c->esp+4+4*k)=a[k];
 unsigned slot=fn-0xf1000000u;int done=1;
 switch(slot){case 94:done=v_SetVertexShaderConstantF(c);break;case 109:done=v_SetPixelShaderConstantF(c);break;case 96:done=v_SetVertexShaderConstantI(c);break;case 111:done=v_SetPixelShaderConstantI(c);break;case 98:done=v_SetVertexShaderConstantB(c);break;case 113:done=v_SetPixelShaderConstantB(c);break;default:break;}
 assert(done);c->esp=saved;return 0;}
SETTERS
#define CHECK(x) do{++checks;if(!(x)){fprintf(stderr,"LIGHT INPUT CHECK %u failed: %s\n",checks,#x);return 1;}}while(0)
static int load(Effect*fx,const char*path){FILE*f=fopen(path,"rb");assert(f);fseek(f,0,SEEK_END);long n=ftell(f);rewind(f);void*b=malloc(n);assert(fread(b,1,n,f)==n);fclose(f);if(!parse_effect(fx,b,n))return 0;fx->device=galloc(16);uint32_t vt=galloc(120*4);M32(fx->device)=vt;for(unsigned k=0;k<120;k++)M32(vt+k*4)=0xf1000000u+k;return 1;}
static State *pixel(Effect*fx){Pass*p=&fx->techs[0].passes[0];for(int k=0;k<p->nstates;k++)if(p->states[k].op==OP_SHADER+1)return &p->states[k];return NULL;}
int main(int argc,char**argv){CHECK(argc==3);G=calloc(1,1<<26);CHECK(G!=NULL);Cpu c={0};Effect hdr={0},car={0};CHECK(load(&hdr,argv[1]));CHECK(load(&car,argv[2]));
 fixture_fx=&hdr;Param*p=find_param(hdr.params,hdr.nparams,"cfMiddleGray");CHECK(p!=NULL);c.esp=0x8000;M32(c.esp+8)=p->handle;float exposure=0.18f;memcpy(G+c.esp+12,&exposure,4);CHECK(e_SetFloat(&c)&&c.eax==0&&c.esp==0x8010);State*ps=pixel(&hdr);CHECK(ps!=NULL);upload_ctab(&c,&hdr,ps,1,0);CHECK(fabsf(dev.psc[0][0]-exposure)<1e-7f);
 printf("HDR constant input=%g device.ps.c0.x=%g\n",exposure,dev.psc[0][0]);
 fixture_fx=&car;p=find_param(car.params,car.nparams,"cmLocalColourMatrix");CHECK(p!=NULL);float matrix[16];for(int k=0;k<16;k++)matrix[k]=k+0.25f;uint32_t m=galloc(64);memcpy(G+m,matrix,64);c.esp=0x8000;M32(c.esp+8)=p->handle;M32(c.esp+12)=m;CHECK(set_matrix_common(&c,0,0,0)&&c.esp==0x8010);ps=pixel(&car);CHECK(ps!=NULL);upload_ctab(&c,&car,ps,1,0);
 for(int col=0;col<3;col++)for(int row=0;row<4;row++)CHECK(dev.psc[3+col][row]==matrix[row*4+col]);
 printf("CAR matrix input 4x4 -> device.ps.c3=%g,%g,%g,%g c4=%g,%g,%g,%g c5=%g,%g,%g,%g\n",dev.psc[3][0],dev.psc[3][1],dev.psc[3][2],dev.psc[3][3],dev.psc[4][0],dev.psc[4][1],dev.psc[4][2],dev.psc[4][3],dev.psc[5][0],dev.psc[5][1],dev.psc[5][2],dev.psc[5][3]);
 float daylight[3][4]={{0.6f,0,0.8f,0},{0.6f,0.48f,0.22f,0.5f},{0.19f,0.24f,0.32f,0}};
 uint32_t light=galloc(sizeof daylight);memcpy(G+light,daylight,sizeof daylight);
 dev.vsc[239][0]=123;dev.vsc[243][0]=456;uint32_t version=dev.ver_vsc;
 uint32_t args[]={car.device,240,light,3};CHECK(call_guest(&c,0xf1000000u+94,4,args)==0);
 CHECK(!memcmp(dev.vsc+240,daylight,sizeof daylight));CHECK(dev.ver_vsc==version+1);
 CHECK(dev.vsc[239][0]==123&&dev.vsc[243][0]==456);
 float sky[3][4]={{0.27f,0.46f,1,0.5f},{0.18f,0.24f,0.37f,1},{0.18f,0.24f,0.37f,1.f/7000}};
 uint32_t sky_data=galloc(sizeof sky);memcpy(G+sky_data,sky,sizeof sky);
 dev.psc[13][0]=123;dev.psc[17][0]=456;version=dev.ver_psc;
 uint32_t sky_args[]={car.device,14,sky_data,3};CHECK(call_guest(&c,0xf1000000u+109,4,sky_args)==0);
 CHECK(!memcmp(dev.psc+14,sky,sizeof sky));CHECK(dev.ver_psc==version+1);
 CHECK(dev.psc[13][0]==123&&dev.psc[17][0]==456);
 printf("PRIVATE LIGHTING INPUTS PASS checks=%u\n",checks);return 0;}
'''
    out=ignored_output(root/'lighting_inputs_test')
    for mutant in ('good','exposure','matrix','daylight-registers','sky-registers'):
        selected=prefix
        sets=setter
        constant_setters=constants
        if mutant=='exposure':sets=sets.replace('float f = argf(c, 2);','float f = 0;')
        if mutant=='matrix':selected=selected.replace('int as_cols = ccls == PC_MATRIX_COLUMNS || (ccls != PC_MATRIX_ROWS && q->cls == PC_MATRIX_COLUMNS);','int as_cols = 0;')
        if mutant=='daylight-registers':constant_setters=constant_setters.replace('uint32_t s = arg(c, 1), n = arg(c, 3);','uint32_t s = arg(c, 1)==240 ? 239 : arg(c, 1), n = arg(c, 3);')
        if mutant=='sky-registers':constant_setters=constant_setters.replace('uint32_t s = arg(c, 1), n = arg(c, 3);','uint32_t s = arg(c, 1)==14 ? 13 : arg(c, 1), n = arg(c, 3);')
        code=selected+harness.replace('CONSTANTS',constant_setters).replace('SETTERS',sets)
        path=out/'test.c';path.write_text(code)
        r=subprocess.run(['clang','-O1','-g','-w','-fsanitize=address,undefined','-I',str(HERE),'-I',str(HERE.parent/'runtime'),str(path),'-o',str(out/'test')],capture_output=True,text=True)
        if r.returncode:raise RuntimeError(r.stderr[-2500:])
        r=subprocess.run([str(out/'test'),str(hdr),str(car)],capture_output=True,text=True,env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'})
        (out/(mutant+'.log')).write_text(r.stdout+r.stderr)
        print(mutant+f': exit={r.returncode} '+r.stdout.strip()+r.stderr.strip())
        if r.returncode!=(0 if mutant=='good' else 1):raise RuntimeError(r.stderr[-2000:])
    mapping=body(selected_source(HERE.parent/'runtime/render.m'),'mtl_format')
    format_fixture=r'''#import <Metal/Metal.h>
#include <stdio.h>
static MTLPixelFormat mtl_format(uint32_t f,int*conv,MTLTextureSwizzleChannels*sw) MAPPING
int main(void){unsigned formats[]={111,112,113,114,115,116};MTLPixelFormat expected[]={MTLPixelFormatR16Float,MTLPixelFormatRG16Float,MTLPixelFormatRGBA16Float,MTLPixelFormatR32Float,MTLPixelFormatRG32Float,MTLPixelFormatRGBA32Float};
 for(int k=0;k<6;k++){int conv=-1;MTLTextureSwizzleChannels sw;MTLPixelFormat actual=mtl_format(formats[k],&conv,&sw);if(actual!=expected[k]||conv){fprintf(stderr,"HDR FORMAT FAIL fmt=%u metal=%lu converted=%d\n",formats[k],(unsigned long)actual,conv);return 1;}}
 puts("HDR FORMAT PASS maps=6 conversion=0 device=none");return 0;}
'''
    for broken in (False,True):
        selected=mapping.replace('case 113: return MTLPixelFormatRGBA16Float;','case 113: return MTLPixelFormatBGRA8Unorm;') if broken else mapping
        path=out/'formats.m';path.write_text(format_fixture.replace('MAPPING',selected))
        r=subprocess.run(['clang','-O1','-fobjc-arc',str(path),'-framework','Metal','-framework','Foundation','-o',str(out/'formats')],capture_output=True,text=True)
        if r.returncode:raise RuntimeError(r.stderr[-2000:])
        r=subprocess.run([str(out/'formats')],capture_output=True,text=True)
        print(('broken format' if broken else 'formats')+f': exit={r.returncode} '+r.stdout.strip()+r.stderr.strip())
        assert r.returncode==(1 if broken else 0)
    return 0


if __name__=='__main__':sys.exit(main())
