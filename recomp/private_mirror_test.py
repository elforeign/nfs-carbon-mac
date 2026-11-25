"""Original mirror quad versus the independently decoded HUD canvas.

4K quad edge error: repaired 0 px; original full viewport 195 px (exit 1).
The original viewport fragment is pinned below; no history or game run needed.
Notch HUD canvas: old composite/frame Y error 133.52 px (exit 5), fixed
error below 0.001 px (exit 0); Off and other shaders keep their old viewport.
"""
from pathlib import Path
import hashlib
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from private_render import body

ORIGINAL = '''    float vpz0, vpz1;
    memcpy(&vpz0, &dev.viewport[4], 4); memcpy(&vpz1, &dev.viewport[5], 4);
    MTLViewport vp = {dev.viewport[0], dev.viewport[1], dev.viewport[2], dev.viewport[3], vpz0, vpz1};
'''

OLD_NOTCH_CANVAS = '''{
    // RVMPIP rvm vs_2_0 / vs_1_1; neither reads WorldViewProj.
    if (shader != 0xE3D503E829EB7702ull && shader != 0x2406D3EEEE369C38ull) return vp;
    double width = vp.height * (4.0 / 3.0);
    if (width > 0 && width < vp.width) {
        vp.originX += (vp.width - width) * 0.5;
        vp.width = width;
    }
    return vp;
}'''
assert hashlib.sha256(OLD_NOTCH_CANVAS.encode()).hexdigest() == '1edbdc2c2f1d75f0bf596d8a72ac96da186e190dfd8b033fafbe4e9b254a8e6f'


def main():
    assert hashlib.sha256(ORIGINAL.encode()).hexdigest() == 'e67565fe41c6a6782beea9f9ac5a6e33d3b9fdc2f6ae70e8958bc6daee765cca'
    render = (HERE.parent / 'runtime/render.m').read_text()
    production = body(render, 'mirror_composite_viewport')
    assert 'vp = mirror_composite_viewport(vp, vs->tokens_hash);' in body(render, 'draw_impl')
    source = r'''
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef struct { double originX,originY,width,height,znear,zfar; } MTLViewport;
static struct { uint32_t viewport[6]; } dev;
static float kx=.75f,ky=1;
float carbon_fe_kx(void) {return kx;}
float carbon_fe_ky(void) {return ky;}
static MTLViewport original(void) {
''' + ORIGINAL + r'''    return vp;
}
static MTLViewport corrected(MTLViewport vp,uint64_t shader) ''' + production + r'''
static MTLViewport old_notch(MTLViewport vp,uint64_t shader) ''' + OLD_NOTCH_CANVAS + r'''
int main(int argc,char **argv) {
    int broken=argc>1 && argv[1][0]=='b';
    // 00750C30/00750B30: x = +/-0.40625, y = .6291667.. .9208333.
    // HUD FE projection applies (4/3)/aspect to x independently of this quad.
    dev.viewport[2]=3840;dev.viewport[3]=2160;dev.viewport[5]=0x3f800000;
    MTLViewport in=original(),out=broken?in:corrected(in,0xE3D503E829EB7702ull);
    double left=out.originX+(1-.40625)*out.width/2;
    double hud_left=1920-585; // 260 FE units at 2160/480, centered on 1920.
    double error=fabs(left-hud_left);
    printf("mirror quad edge error=%.6g px\n",error);
    if(error>1e-6)return 1;
    for(unsigned model=0;model<2;model++) {
        uint64_t shader=model?0x2406D3EEEE369C38ull:0xE3D503E829EB7702ull;
        for(unsigned h=480;h<=2160;h+=240)for(unsigned w=640;w<=3840;w+=320) {
            in=(MTLViewport){17,23,w,h,.125,.875};out=corrected(in,shader);
            double k=(4./3.)*h/w;if(k>1)k=1;
            // Independently project three native quad vertices with FE kx.
            for(int vertex=-1;vertex<=1;vertex++) {
                double x=vertex*.40625;
                double expected=17+w/2.+x*k*w/2.;
                double actual=out.originX+(x+1)*out.width/2.;
                if(fabs(actual-expected)>1e-6)return 2;
            }
            if(out.originY!=in.originY || out.height!=in.height ||
               out.znear!=in.znear || out.zfar!=in.zfar)return 3;
            // Original PIP shaders and ordinary world shaders are untouched.
            uint64_t other[]={0x7D2C672B8DA5A556ull,0x21DCBE59667AAA88ull,0};
            for(unsigned i=0;i<3;i++) {
                out=corrected(in,other[i]);
                if(memcmp(&in,&out,sizeof in))return 4;
            }
        }
    }
    ky=1944.0f/2234;
    in=(MTLViewport){0,0,3456,2234,0,1};
    out=argc>1?old_notch(in,0xE3D503E829EB7702ull):corrected(in,0xE3D503E829EB7702ull);
    double error_x=fabs((out.originX+(1-.40625)*out.width/2)-(1728-.40625*2592/2));
    double error_y=fabs((out.originY+(1-.9208333)*out.height/2)-(1117-.9208333*1944/2));
    printf("notch mirror/frame error x=%.6f y=%.6f px\n",error_x,error_y);
    if(error_x>.001||error_y>.001)return 5;
    return 0;
}
'''
    with tempfile.TemporaryDirectory(prefix='private-mirror-') as td:
        path = Path(td) / 'fixture.c'
        binary = Path(td) / 'fixture'
        path.write_text(source)
        subprocess.run(['clang', '-O1', '-Wall', '-Wextra', str(path), '-o', str(binary)], check=True)
        for name, args, expected in [('fixed', [], 0), ('original', ['broken'], 1),('notch-old',['notch'],5)]:
            r = subprocess.run([str(binary), *args], capture_output=True, text=True)
            print(name + ': ' + r.stdout.strip() + ' exit=' + str(r.returncode))
            assert r.returncode == expected, r.stderr


if __name__ == '__main__':
    main()
