"""Actual runtime effect-parser corpus check; no GPU or game execution.

Good: every private effect blob parses. Broken: zero the effect magic in the
same first blob -> parser rejected/exit 1. Missing private corpus skips (3).
"""
from pathlib import Path
import subprocess
import sys
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
from build_private import ignored_output
sys.path.insert(0,str(HERE/"private_runtime"))
from layers import selected_source


def main():
    root=HERE/'out/carbon';files=sorted((root/'effects').glob('*.bin'))
    if not files:print('SKIP: private effect corpus absent');return 3
    out=ignored_output(root/'effect_check')
    source=selected_source(HERE.parent/'runtime/d3dx_effect.c').split('// ---------------- pool (shared parameters)',1)[0]
    assert 'static int parse_effect(' in source and source.rstrip().endswith('}')
    fixture=out/'test.c';fixture.write_text(source+r'''
#include <assert.h>
uint8_t *G;static uint32_t allocated=0x1000;
uint32_t galloc(uint32_t n){uint32_t p=allocated;allocated+=(n+15)&~15u;assert(allocated<(1<<26));return p;}
uint32_t gstr(const char*s){uint32_t p=galloc((uint32_t)strlen(s)+1);strcpy((char*)G+p,s);return p;}
int main(int argc,char**argv){G=calloc(1,1<<26);assert(G);unsigned params=0,techs=0,passes=0;
 for(int k=1;k<argc;k++){FILE*f=fopen(argv[k],"rb");assert(f);fseek(f,0,SEEK_END);long n=ftell(f);rewind(f);uint8_t*d=malloc(n);assert(fread(d,1,n,f)==(size_t)n);fclose(f);Effect fx={0};if(!parse_effect(&fx,d,(uint32_t)n)){puts("effect parser rejected input");return 1;}params+=fx.nparams;techs+=fx.ntechs;for(int t=0;t<fx.ntechs;t++)passes+=fx.techs[t].npasses;free(d);}
 printf("PRIVATE EFFECT PASS effects=%d parameters=%u techniques=%u passes=%u\n",argc-1,params,techs,passes);free(G);return 0;}
''')
    r=subprocess.run(['clang','-O1','-w','-I',str(HERE),'-I',str(HERE.parent/'runtime'),str(fixture),'-o',str(out/'test')],capture_output=True,text=True)
    if r.returncode:raise RuntimeError(r.stderr[-2000:])
    r=subprocess.run([str(out/'test'),*map(str,files)],capture_output=True,text=True)
    print('good: '+r.stdout.strip());assert r.returncode==0,r.stderr
    bad=out/'broken.bin';data=bytearray(files[0].read_bytes());data[:4]=b'\0'*4;bad.write_bytes(data)
    r=subprocess.run([str(out/'test'),str(bad)],capture_output=True,text=True)
    print('broken: '+r.stdout.strip()+' exit='+str(r.returncode));assert r.returncode==1
    return 0


if __name__=='__main__':sys.exit(main())
