"""CPU FE colour/MVP diagnostic, no GPU/game; source copied before quarantine.

Good: 12 checks. Broken alpha extraction fails check 2; omitted projection
fails check 1; bbox-only coverage fails check 4 (exit 1 each).
Diagnostic insertion retains the draw-frame gate.
Effect-input evidence: disabled/unselected 0 reads/events, selected 1/1;
removing its gate fails check 1 with 1 unexpected read/event (exit 1).
"""
from pathlib import Path
import subprocess
import sys
import tempfile
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
sys.path.insert(0,str(HERE/"private_runtime"))
from layers import selected_source


def effect_evidence():
    evidence=(HERE/'private_runtime/game_effect_evidence.h').read_text()
    fixture=r'''
#include <stdint.h>
#include <string.h>
#include <stdio.h>
#include <stdarg.h>
static int diag_on,wanted,reads,events;
static char message[256];
typedef struct {unsigned bytes;const char *name;float values[4];} Param;
uint64_t diag_current_frame(void){return 9;}
int diag_frame_wanted(uint64_t f,const char*n){return f==9&&!strcmp(n,"BOOT_DIAG_DRAWS")&&wanted;}
static void get_floats(Param*p,float*v,unsigned n){++reads;memcpy(v,p->values,n*4);}
void diag_event(const char*fmt,...){++events;va_list ap;va_start(ap,fmt);vsnprintf(message,sizeof message,fmt,ap);va_end(ap);}
static void sample(void){
 Param value={16,"Diffuse",{1,2,3,4}},*p=&value;
 int ps=1;unsigned ri=2,nreg=1;float regs[1][4]={{5,6,7,8}};
 EVIDENCE
}
int main(void){
 wanted=1;sample();if(reads||events){puts("FX EVIDENCE CHECK 1 failed");return 1;}
 diag_on=1;wanted=0;sample();if(reads||events){puts("FX EVIDENCE CHECK 2 failed");return 1;}
 wanted=1;sample();if(reads!=1||events!=1||strcmp(message,"PRIVATE FX INPUT ps Diffuse reg=2 count=1 value=1,2,3,4 packed=5,6,7,8")){puts("FX EVIDENCE CHECK 3 failed");return 1;}
 puts("FX EVIDENCE PASS checks=3 off=0 selected=1");return 0;
}
'''
    gate='if(diag_on && diag_frame_wanted(diag_current_frame(),"BOOT_DIAG_DRAWS"))'
    assert evidence.count(gate)==1
    with tempfile.TemporaryDirectory(prefix='private-fx-evidence-') as td:
        out=Path(td)
        for broken in (False,True):
            selected=evidence.replace(gate,'if(1)') if broken else evidence
            source=out/'test.c';source.write_text(fixture.replace('EVIDENCE',selected,1))
            r=subprocess.run(['clang','-O1','-fsanitize=address,undefined',str(source),'-o',str(out/'test')],capture_output=True,text=True)
            assert r.returncode==0,r.stderr[-2000:]
            r=subprocess.run([str(out/'test')],capture_output=True,text=True)
            print(('broken: ' if broken else 'good: ')+r.stdout.strip())
            assert r.returncode==(1 if broken else 0),r.stderr


def main():
    prepared=selected_source(HERE.parent/'runtime/render.m')
    from private_render import body
    UP_SUMMARY='typedef struct { int valid, black, full; float amin,amax,xmin,xmax,ymin,ymax; } PrivateUpSummary;\nstatic PrivateUpSummary private_up_summary(const void *data, unsigned stride, unsigned count, const Elem *elements, int nel, const float matrix[4][4])'+body(prepared,'private_up_summary')
    assert 'if (texdump_frame())' in prepared and 'PRIVATE BLACK FULLSCREEN INPUT' in prepared
    assert prepared.count('if(getenv("BOOT_DIAG_CONSTANTS_ONLY"))return;')==2
    fixture=r'''
#include <stdint.h>
#include <string.h>
#include <math.h>
#include <stdio.h>
typedef struct { uint8_t stream,type,usage,index;uint16_t offset; } Elem;
SUMMARY
static unsigned checks;
#define CHECK(x) do{++checks;if(!(x)){fprintf(stderr,"FRONTEND CHECK %u failed: %s\n",checks,#x);return 1;}}while(0)
int main(void){
 struct {float x,y,z;uint32_t color;} v[4]={{0,0,0,0xa0000000},{640,0,0,0xa0000000},{0,480,0,0xa0000000},{640,480,0,0xa0000000}};
 Elem e[2]={{0,2,0,0,0},{0,4,10,0,12}};
 float m[4][4]={{1.0f/320,0,0,-1},{0,-1.0f/240,0,1},{0,0,1,0},{0,0,0,1}};
 PrivateUpSummary s=private_up_summary(v,sizeof *v,4,e,2,m);
 CHECK(s.valid&&s.full&&s.black);
 CHECK(fabsf(s.amin-160.0f/255)<1e-6f&&s.amax==s.amin);
 CHECK(fabsf((1-s.amin)-95.0f/255)<1e-6f);
 CHECK(!private_up_summary(v,sizeof *v,3,e,2,m).full);
 v[0].color|=255;s=private_up_summary(v,sizeof *v,4,e,2,m);CHECK(s.valid&&s.full&&!s.black);
 v[0].color=0x80000000;s=private_up_summary(v,sizeof *v,4,e,2,m);CHECK(s.amin==128.0f/255&&s.amax==160.0f/255);
 v[0].x=320;v[2].x=320;s=private_up_summary(v,sizeof *v,4,e,2,m);CHECK(s.valid&&!s.full);
 CHECK(!private_up_summary(v,12,4,e,2,m).valid);
 CHECK(!private_up_summary(v,sizeof *v,9,e,2,m).valid);
 e[1].stream=1;CHECK(!private_up_summary(v,sizeof *v,4,e,2,m).valid);e[1].stream=0;
 m[3][3]=0;CHECK(!private_up_summary(v,sizeof *v,4,e,2,m).valid);m[3][3]=1;
 v[0].x=NAN;CHECK(!private_up_summary(v,sizeof *v,4,e,2,m).valid);
 printf("PRIVATE FRONTEND PASS checks=%u alpha=160/255 background=95/255\n",checks);return 0;
}
'''
    with tempfile.TemporaryDirectory(prefix='private-frontend-') as td:
        out=Path(td)
        for mutant in ('good','alpha','matrix','coverage'):
            helper=UP_SUMMARY
            if mutant=='alpha':helper=helper.replace('(color>>24)','(color&255)')
            if mutant=='matrix':helper=helper.replace('matrix[row][c]','(row==c)')
            if mutant=='coverage':helper=helper.replace('s.full=corners==15','s.full=s.xmin<=-0.99f && s.xmax>=0.99f && s.ymin<=-0.99f && s.ymax>=0.99f')
            path=out/'test.c';path.write_text(fixture.replace('SUMMARY',helper))
            r=subprocess.run(['clang','-O1','-g','-fsanitize=address,undefined',str(path),'-o',str(out/'test')],capture_output=True,text=True)
            if r.returncode:raise RuntimeError(r.stderr[-2000:])
            r=subprocess.run([str(out/'test')],capture_output=True,text=True)
            print(mutant+f': exit={r.returncode} '+r.stdout.strip()+r.stderr.strip())
            assert r.returncode==(0 if mutant=='good' else 1)
    effect_evidence()
    return 0


if __name__=='__main__':sys.exit(main())
