#!/usr/bin/env python3
"""Native Xbox fallback pixel oracle and production texture lookup, no game files.

Good: 24/24 nonempty, 22 distinct images plus two loading aliases, 4/4 face
colour families; default/on 24 drawn, off/0 0. Broken controls: PlayStation
under Xbox names yields 0/4 face families; missing DPAD_UP yields 23/24,
both rejected. Original branch: 0/24, rejected.
MW's independent drawing spec also checks every shared glyph byte-for-byte.
"""
from pathlib import Path
import os
import hashlib
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = ROOT / 'recomp/private_runtime'
# Native vocabulary, independent of the production catalogue.
NAMES = ('CROSS TRIANGLE CIRCLE SQUARE L1 R1 L2 R2 L3 R3 START SELECT DPAD '
         'DPAD_UP DPAD_DOWN DPAD_LEFT DPAD_RIGHT DPAD_LEFTRIGHT LEFT_ANALOG '
         'RIGHT_ANALOG RIGHT_ANALOG_UP RIGHT_ANALOG_DOWN L1_LOADING R1_LOADING').split()
# Original missing-assets branch, pinned as a function fragment.
ORIGINAL_XBOX = '    if(carbon_pad_layout_get()==CARBON_LAYOUT_XBOX) {\n        if(!xbox_assets())return 0;\n        return carbon_texture_ready(c,xbox_textures[i])?xbox_textures[i]:0;\n    }\n'
ORIGINAL_SHA = 'b4a56907f98c785bcd0e2fa2cdd439dd4e0e68fac98e1a99cceb9841dee62a0b'
PRE = r'''
#include "host.h"
#include <stdlib.h>
uint8_t *G;
const char *game_dir;
int diag_on;
void user32_hide_pointer(void) {}
int carbon_addons_host_osk_pad(int p,uint32_t b,int u,int d,int l,int r,float x,float y,int c,int xb) { (void)p;(void)b;(void)u;(void)d;(void)l;(void)r;(void)x;(void)y;(void)c;(void)xb;return 0; }

static unsigned heap=0x1000000, uploads;
static int layout=1;
int carbon_pad_layout_get(void) {return layout;}
void diag_event(const char *fmt,...) {(void)fmt;}
uint32_t gmalloc(uint32_t n) {unsigned p=heap;heap=(heap+n+63)&~63u;return p;}
uint32_t call_guest(Cpu *c,uint32_t fn,int n,const uint32_t *a) {
    (void)n;(void)a;if(fn!=0x00725C80u)abort();
    M32(M32(c->ecx)+0x10)=++uploads;return 0;
}
'''
POST = r'''
static void save(const char *folder,const char *name,const uint8_t *pixels) {
    char path[2048];snprintf(path,sizeof path,"%s/%s.bgra",folder,name);
    FILE *f=fopen(path,"wb");if(!f)abort();fwrite(pixels,1,CT_SIZE,f);fclose(f);
}
int main(int argc,char **argv) {
    if(argc!=3)return 2;
    G=calloc(1,64u<<20);M32(0xAB0ABC)=1;Cpu c={0};
    initialize();prompts_input(1);
    if(xbox_assets())abort(); /* No player files are needed. */
    unsigned count=0;
    for(unsigned i=0;i<GLYPHS;++i) {
        uint32_t ti=glyph_texture(&c,i);
        if(!ti)continue;
        ++count;save(argv[1],glyphs[i].name,G+M32(ti+CT_PIXELS));
        if(!console_layout() || ti!=glyph_texture(&c,i) || M32(ti+CT_HASH)!=xbox_hashes[i])abort();
        if(M16(ti+CT_WIDTH)!=32 || M16(ti+CT_HEIGHT)!=32)abort();
        M32(M32(ti)+0x10)=0;
        unsigned before=uploads;if(glyph_texture(&c,i)!=ti || uploads!=before+1)abort();
        layout=0;uint32_t ps=glyph_texture(&c,i);if(!ps || ps==ti)abort();layout=1;
        c.esp=0x800000;M32(c.esp+4)=private_hashes[i];
        carbon_padprompts_lookup(&c,NULL);if(c.eax!=ti)abort();
    }
    if((count!=0)!=!!console_layout())abort();
    /* Automatic input: no controller activity means PC; forced-PC always wins. */
    prompt_mode=2;prompts_pad_seen(0);if(console_layout())abort();
    prompts_input(1);if((count!=0)!=!!console_layout())abort();
    prompt_mode=0;if(console_layout())abort();prompt_mode=1;
    /* Complete console assets always win, including with the switch disabled. */
    xbox_state=1;
    for(unsigned i=0;i<GLYPHS;++i) {
        uint8_t sentinel[CT_SIZE];memset(sentinel,73,sizeof sentinel);
        xbox_textures[i]=carbon_texture_new(xbox_hashes[i],glyphs[i].name,sentinel);
        uint32_t ti=glyph_texture(&c,i);
        if(ti!=xbox_textures[i] || memcmp(G+M32(ti+CT_PIXELS),sentinel,CT_SIZE))abort();
    }
    if(!console_layout())abort();
    printf("drawn=%u console-priority=24 reset=%u\n",count,count);
    /* Reference drawing: independent MW function and native-name translation. */
    for(unsigned i=0;i<GLYPHS;++i) {
        const char *name=glyphs[i].name,*ref=name;
        if(!strcmp(name,"L1") || !strcmp(name,"L1_LOADING"))ref="L2";
        else if(!strcmp(name,"R1") || !strcmp(name,"R1_LOADING"))ref="R2";
        else if(!strcmp(name,"L2"))ref="L1";
        else if(!strcmp(name,"R2"))ref="R1";
        else if(!strcmp(name,"SELECT"))ref="BACK";
        else if(!strcmp(name,"L3"))ref="LEFT_ANALOG";
        else if(!strcmp(name,"DPAD_UP"))ref="DPAD_DOWN";
        uint8_t pixels[CT_SIZE]={0};
        CGColorSpaceRef cs=CGColorSpaceCreateDeviceRGB();
        CGContextRef g=CGBitmapContextCreate(pixels,32,32,8,128,cs,kCGImageAlphaPremultipliedFirst|kCGBitmapByteOrder32Little);
        CGContextScaleCTM(g,.5,.5);
        if(!strcmp(name,"DPAD_UP")) {CGContextTranslateCTM(g,64,64);CGContextRotateCTM(g,M_PI);}
        draw_reference(g,ref);
        if(!strcmp(name,"L3")) {
            CGContextSetRGBStrokeColor(g,.95,.95,.95,1);CGContextSetLineWidth(g,2);
            CGContextStrokeEllipseInRect(g,CGRectMake(10,10,44,44));
        }
        CGContextFlush(g);
        CGContextRelease(g);CGColorSpaceRelease(cs);
        for(unsigned p=0;p<1024;++p) {uint8_t *q=pixels+4*p,a=q[3];if(a && a<255)for(int k=0;k<3;++k)q[k]=(q[k]*255+a/2)/a;}
        save(argv[2],name,pixels);
    }
    free(G);return 0;
}
'''


def oracle(folder, reference):
    images = {}
    for name in NAMES:
        path = folder / (name+'.bgra')
        if not path.exists():
            return False, 'missing '+name
        px = path.read_bytes()
        if len(px)!=4096 or sum(a>128 for a in px[3::4])<50:
            return False, 'empty '+name
        images[name]=px
    for name, original in [('L1_LOADING','L1'),('R1_LOADING','R1')]:
        if images[name]!=images[original]:return False,'loading alias '+name
    if len(set(images.values()))!=22:return False,'distinct images !=22'
    families = {
        'CROSS': lambda r,g,b: g>120 and g>r*1.5 and g>b*1.5,
        'TRIANGLE': lambda r,g,b: r>150 and r>g*1.8 and r>b*1.8,
        'SQUARE': lambda r,g,b: b>150 and b>r*1.8 and b>g*1.4,
        'CIRCLE': lambda r,g,b: r>170 and g>130 and b<70,
    }
    passed=0
    for name,family in families.items():
        px=images[name]
        passed+=sum(px[i+3]>200 and family(px[i+2],px[i+1],px[i]) for i in range(0,4096,4))>=100
    if passed!=4:return False,f'face families={passed}/4'
    for path in reference.glob('*.bgra'):
        if images[path.stem]!=path.read_bytes():return False,'MW spec '+path.stem
    return True,'nonempty=24/24 distinct=22/22 families=4/4 MW-spec=24/24'


def main():
    source=(PRIVATE/'carbon_padprompts.m').read_text().split('static int diagram_analog(')[0]
    mw=(ROOT/'runtime/padprompts.c').read_text()
    ref=mw[mw.index('static void draw_xbox_art('):mw.index('// One drawn glyph:')].replace('draw_xbox_art','draw_reference')
    # Carbon and MW helpers have the same drawing spec; pin the new renderer against MW.
    assert hashlib.sha256(ORIGINAL_XBOX.encode()).hexdigest()==ORIGINAL_SHA
    start=source.index('    if(carbon_pad_layout_get()==CARBON_LAYOUT_XBOX) {',source.index('static uint32_t glyph_texture('))
    end=source.index('    if (!textures[i]) {',start)
    original=source[:start]+ORIGINAL_XBOX+source[end:]
    original=original.replace('(xbox_assets() || xbox_prompt_art())','xbox_assets()')
    variants={
        'original':original,
        'good':source,
        'wrong-family':source.replace('if(xbox)draw_xbox_art(g,xbox);else draw_art(g,art);','draw_art(g,art);'),
        'missing-glyph':source.replace('if(!xbox_textures[i]) {','if(!strcmp(glyphs[i].name,"DPAD_UP"))return 0;\n            if(!xbox_textures[i]) {'),
    }
    assert all(v!=source for k,v in variants.items() if k!='good')
    with tempfile.TemporaryDirectory(prefix='carbon-xboxart-') as tmp:
        work=Path(tmp)
        for variant,current in variants.items():
            fixture=work/'fixture.m';exe=work/'fixture'
            fixture.write_text(PRE+current+ref+POST)
            result=subprocess.run(['clang','-O1','-g','-fsanitize=address,undefined','-fno-sanitize-recover=all',
                '-I'+str(ROOT/'runtime'),'-I'+str(ROOT/'recomp'),'-I'+str(PRIVATE),str(fixture),
                '-framework','CoreGraphics','-framework','CoreText','-framework','CoreFoundation','-o',str(exe)],capture_output=True,text=True)
            assert result.returncode==0,result.stderr[-3000:]
            switches=['unset','on','off','0','1','invalid'] if variant=='good' else ['on']
            for switch in switches:
                folder=work/(variant+'-'+switch);folder.mkdir()
                reference=work/(variant+'-'+switch+'-ref');reference.mkdir()
                env={**os.environ,'NFS_X360_EXTRA_TEXTURES':'off','NFS_BUTTON_PROMPTS':'console','ASAN_OPTIONS':'detect_leaks=0'}
                env.pop('NFS_XBOX_PROMPT_ART',None)
                if switch!='unset':env['NFS_XBOX_PROMPT_ART']=switch
                result=subprocess.run([str(exe),str(folder),str(reference)],env=env,capture_output=True,text=True)
                assert result.returncode==0,(variant,result.returncode,result.stderr[-2000:])
                ok,detail=oracle(folder,reference)
                if variant!='good':assert not ok,variant+' escaped oracle'
                elif switch in ('off','0'):
                    assert 'drawn=0 ' in result.stdout and not list(folder.glob('*.bgra')),result.stdout
                else:assert ok and 'drawn=24 ' in result.stdout,(detail,result.stdout)
                print(variant,switch,result.stdout.strip(),detail)
    print('PASS: Carbon Xbox art 24 on / 0 off; wrong-family and missing-glyph rejected')


if __name__=='__main__':main()
