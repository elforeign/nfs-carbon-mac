"""Image-byte panner/initializer/stream replay, ASan/UBSan; no device/emulator.

Native: 256 gain rows, unit peaks include 0/+45/+135/-135/-45 degrees;
LFE=0 in 256/256. Byte quantization produces flat peak neighbourhoods.
Game/wrong-image: all guest bytes and returned Cpu match all three originals
for 256 inputs each (768 comparisons per environment). Non-five-output panning
also preserves every byte. ITU: 65,536 explicit azimuths, power error <=1e-6,
LFE=0, five unit peaks at nearest 16-bit 0/+30/+110/-110/-30 angles.
Stereo/quad/six-channel child defaults and all initializer rows reach the
intended native channel indices, including the native dedicated-LFE dispatch (008A00BC).
Measured power error 8.21521837224e-8; game comparisons=5376, mode bypass=1280.
Good exit 0; native panner, missing stream remap and reversed channel order
each exit 1 (three mutants).
Exit 3 without the private image/build outputs. --premise prints all 256 rows.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from recomp import PE, Recompiler
import private_audio
import private_hooks

# Complete native gain-table builder and its arithmetic/trig helpers; the three
# production hook witnesses are separately pinned in private_audio.py.
EXTRA = (
    (0x008A00BC, 0x60, '8f5274c1c4975cbd03fe838b5d6888bcc45c905ab6355dca81a2d9aa00b8a4a5'),
    (0x008A4980, 0x2e3, '856e58b3f2917f88f85c09126280847a91d5d5ecb71d21096ef82fe90ba90614'),
    (0x008A4931, 0x4f, '27dd62f08ac13504788057763f55c844a999a31905ca74d6ef085eea0ed07939'),
    (0x008ACE08, 0x7f, '028c8532d7076f7fc8b2e5c4809f869a908365c93e610f354db7686b08c559fa'),
    (0x008ACE87, 0x8a, '00d393fd5fb56b94cf18e6765ea89e5524d5c0db3575d56f084ed68a9c6bec0f'),
)

HARNESS = r'''
#include "runtime.h"
#include <stdio.h>
#include <stdlib.h>
uint8_t *G;
#define SIZE 0xC00000
#define CHECK(x) do {if(!(x)){fprintf(stderr,"POS CHECK %d: %s\n",__LINE__,#x);exit(1);}}while(0)
void dispatch(Cpu *c,uint32_t at){CHECK(0);}
void guest_divide_error(Cpu *c,uint32_t at){CHECK(0);}
/* Lock/allocation host boundaries only; gain math and trig remain native. */
static unsigned deliveries;
void f_0089D6D6(Cpu *c){CHECK(M32(c->esp+4)<=11);++deliveries;c->esp+=4;}
void f_0089B383(Cpu *c){c->esp+=4;}
void f_0089B38F(Cpu *c){c->esp+=4;}
void f_00897973(Cpu *c){CHECK(M32(c->esp+8)==5*256);c->eax=0x30000;c->esp+=4;}
PROTOTYPES
HELPER
TRANSLATED
static Cpu cpu(unsigned input){
    Cpu c={0};c.esp=0x10000;c.cw=0x37f;c.eax=0x12340000+input;
    c.ebx=0x7654;c.esi=0x2345;c.edi=0x3456;c.ebp=0x4567;
    c.ecx=0x5678;c.edx=0x6789;c.mxcsr=0x1f80;
    for(unsigned i=0;i<8;++i){c.st[i]=i+.125;c.mm[i]=0x12345678u+i;}
    return c;
}
static void args(Cpu c,unsigned angle,unsigned channels){
    M32(c.esp)=0x12345678;M32(c.esp+4)=angle;M32(c.esp+8)=0x20000;
    M8(0x4023)=channels;M32(0xBBF3D0)=0x50000;
    /* Nonconsecutive IDs distinguish source index from native channel order. */
    for(unsigned i=0;i<6;++i){
        M16(0x4004+i*2)=11-i*2;
        /* Native six-channel constructors mark only the last child as LFE. */
        M8(0x50000+(11-i*2)*0x84+0x1f)=channels==6&&i==5;
    }
}
static void native_setup(void){
    M8(0xBBF357)=5;Cpu c=cpu(0);carbon_orig_008A4CC8(&c);
    c=cpu(0);f_008A4980(&c);CHECK(c.esp==0x10004);
}
static void premise(int print){
    native_setup();float peaks[5]={0};unsigned peak_masks=0;
    const float native_angles[5]={0,45,135,225,315};
    for(unsigned k=0;k<5;++k)CHECK(MF32(0xBBF448+k*4)==native_angles[k]);
    const unsigned centers[5]={0,32,96,160,224};
    for(unsigned i=0;i<256;++i){
        Cpu c=cpu(i);args(c,i<<8,2);carbon_orig_008A4C63(&c);
        if(print)printf("%3u %10.6f",i,i*360.0/256);
        for(unsigned k=0;k<6;++k){
            float gain=MF32(0x20000+k*4);
            if(print)printf(" %.9g",gain);
            if(k<5){CHECK(isfinite(gain)&&gain>=0&&gain<=1);
                if(gain>peaks[k])peaks[k]=gain;
                if(i==centers[k]&&gain==1)peak_masks|=1u<<k;
            }else CHECK(gain==0&&!signbit(gain));
        }
        if(print)puts("");
    }
    CHECK(peak_masks==31);
    for(unsigned k=0;k<5;++k)CHECK(peaks[k]==1);
    puts("POS NATIVE rows=256 peaks=C:0,FR:45,BR:135,BL:-135,FL:-45 LFE_zero=256");
}
static void identical(void){
    void (*const orig[])(Cpu*)={carbon_orig_008A4C63,carbon_orig_008A4CC8,carbon_orig_0089E2FE};
    void (*const wrapped[])(Cpu*)={f_008A4C63,f_008A4CC8,f_0089E2FE};
    uint8_t *base=G,*other=malloc(SIZE);CHECK(other);unsigned comparisons=0;
    for(unsigned f=0;f<3;++f)for(unsigned i=0;i<256;++i){
        G=base;Cpu expected=cpu(i),actual=expected;args(expected,(i<<8)|(255-i),i%7);
        if(f==2)M32(expected.esp+4)=0x4000;
        memcpy(other,base,SIZE);orig[f](&expected);G=other;wrapped[f](&actual);
        CHECK(!memcmp(&expected,&actual,sizeof actual));CHECK(!memcmp(base,other,SIZE));++comparisons;
    }
    G=base;free(other);
    printf("POS ORIGINAL comparisons=%u guest_bytes_per_case=%u cpu_bytes=%zu\n",comparisons,SIZE,sizeof(Cpu));
}
static void unit(const float *g,unsigned channel){
    for(unsigned k=0;k<6;++k)CHECK(g[k]==(k==channel?1.0f:0.0f));
}
static void enabled(void){
    const unsigned angles[6]={0,5461,20025,45511,60075,0};
    unsigned maxima_at[5]={0};float maxima[5]={0};double worst=0;
    for(unsigned a=0;a<65536;++a){
        float gains[6];carbon_posaudio_gains((uint16_t)a,gains);double power=0;
        for(unsigned k=0;k<5;++k){
            CHECK(isfinite(gains[k])&&gains[k]>=0&&gains[k]<=1);
            power+=(double)gains[k]*gains[k];
            if(gains[k]>maxima[k]){maxima[k]=gains[k];maxima_at[k]=a;}
        }
        double error=fabs(power-1);if(error>worst)worst=error;
        CHECK(error<=1e-6);CHECK(gains[5]==0&&!signbit(gains[5]));
    }
    for(unsigned k=0;k<5;++k){
        float g[6];carbon_posaudio_gains((uint16_t)angles[k],g);unit(g,k);
        /* Float rounding can flatten the last few input steps of a peak. */
        CHECK(maxima[k]==1&&abs((int)maxima_at[k]-(int)angles[k])<=4);
    }
    /* The native wrapper must use all sixteen input bits, and native ordering. */
    for(unsigned a=0;a<65536;++a){
        Cpu c=cpu(a);args(c,a,6);float want[6];carbon_posaudio_gains((uint16_t)a,want);
        f_008A4C63(&c);CHECK(c.esp==0x10004);CHECK(!memcmp(G+0x20000,want,sizeof want));
    }
    Cpu c=cpu(0);f_008A4CC8(&c);
    CHECK(MF32(0xBBF448)==0&&MF32(0xBBF44C)==30&&MF32(0xBBF450)==110);
    CHECK(MF32(0xBBF454)==250&&MF32(0xBBF458)==330);
    /* Independently named native speaker order for each interleaved source row.
     * Six-channel source is FL,C,FR,BL,BR,LFE; panner output is C,FR,BR,BL,FL,LFE. */
    const unsigned stereo[2]={4,1},quad[4]={4,1,3,2},six[6]={4,0,1,3,2,5};
    unsigned stream_cases=0,init_cases=0;
    M32(0xBBF468)=0x60000;M8(0xBBF45C)=6;deliveries=0;
    for(unsigned channels=2;channels<=6;channels+=2){
        const unsigned *expected=channels==2?stereo:channels==4?quad:six;
        for(unsigned i=0;i<channels;++i){
            uint32_t row=channels==2?0xBBF3E4:channels==4?0xBBF3FC:0xBBF414;
            CHECK(M16(row+i*2)==angles[expected[i]]);++init_cases;
        }
        c=cpu(0);args(c,0,channels);M32(c.esp+4)=0x4000;f_0089E2FE(&c);
        for(unsigned i=0;i<channels;++i){
            uint32_t at=0x50000+(11-i*2)*0x84+0x1c;
            CHECK(M16(at)==angles[expected[i]]);
            c=cpu(i);M32(c.esp+4)=11-i*2;f_008A00BC(&c);
            float g[6];memcpy(g,G+0x60000+(11-i*2)*24,sizeof g);
            unit(g,expected[i]);++stream_cases;
        }
    }
    /* The native caller bypasses the panner for the LFE child. */
    CHECK(M16(0xBBF41E)==0&&deliveries==12);
    for(unsigned a=0;a<65536;++a){
        unsigned expected=a==0x2000?5461:a==0x6000?20025:a==0xA000?45511:a==0xE000?60075:a;
        CHECK(carbon_posaudio_default((uint16_t)a)==expected);
    }
    /* Other output modes still replay the original panner byte for byte. */
    uint8_t *base=G,*other=malloc(SIZE);CHECK(other);unsigned bypass=0;
    for(unsigned count=0;count<5;++count)for(unsigned a=0;a<256;++a){
        G=base;M8(0xBBF357)=count;Cpu expected=cpu(a),actual=expected;args(expected,a<<8,2);
        memcpy(other,base,SIZE);carbon_orig_008A4C63(&expected);G=other;f_008A4C63(&actual);
        CHECK(!memcmp(base,other,SIZE)&&!memcmp(&expected,&actual,sizeof actual));++bypass;
    }
    G=base;M8(0xBBF357)=5;free(other);
    printf("POS ITU azimuths=65536 wrapper_azimuths=65536 power_error=%.12g stream_defaults=%u initializer_defaults=%u bypass=%u\n",worst,stream_cases,init_cases,bypass);
}
int main(int argc,char **argv){
    CHECK(argc==3);G=malloc(SIZE);CHECK(G);FILE *f=fopen(argv[1],"rb");CHECK(f);
    CHECK(fread(G,1,SIZE,f)==SIZE);fclose(f);premise(!strcmp(argv[2],"premise"));
    if(!strcmp(argv[2],"identical"))identical();
    if(!strcmp(argv[2],"enabled"))enabled();
    free(G);return 0;
}
'''


def run_fixture(tmp, source, name, mode, memory, env):
    path = tmp / (name + '.c')
    path.write_text(source)
    binary = tmp / name
    result = subprocess.run(['clang', '-O1', '-Wno-parentheses-equality',
                             '-fsanitize=address,undefined', '-I', str(HERE), '-I', str(tmp),
                             str(path), '-o', str(binary)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr[-2000:]
    result = subprocess.run([str(binary), str(memory), mode], env=env, capture_output=True, text=True)
    assert 'AddressSanitizer' not in result.stderr and 'runtime error:' not in result.stderr, result.stderr[-2000:]
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--premise', action='store_true')
    options = parser.parse_args()
    out = HERE / 'out/carbon'
    if not all((out / p).is_file() for p in ('image.json', 'NFSC.a', 'boot_carbon')):
        print('SKIP: private positional build outputs absent'); return 3
    image = json.loads((out / 'image.json').read_text())
    if not Path(image['exe']).is_file():
        print('SKIP: private executable absent'); return 3
    private_audio.validate(image)
    pe = PE(image['exe'], expected_sha256=private_audio.CARBON_SHA256)
    witnesses = private_audio.POS_WITNESSES + EXTRA
    functions = {a:a+n for a,n,_ in witnesses}
    functions.update({a:a+1 for a in (0x89B383, 0x89B38F, 0x897973, 0x89D6D6)})
    rc = Recompiler(pe=pe, functions=functions, mw_patches=False); rc.calls = True
    manifest = json.loads((HERE/'private_runtime/hooks/posaudio.json').read_text())
    records = {int(row['address'],16):row for row in manifest['hooks']}
    assert set(records) == {a for a,_,_ in private_audio.POS_WITNESSES}
    originals = []
    for address, length, digest in witnesses:
        assert hashlib.sha256(pe.read(address,length)).hexdigest() == digest
        code, why = rc.translate(address,address+length); assert code is not None, why
        if address in records:
            row = records[address]
            assert row['image_sha256'] == image['sha256']
            assert row['witness'] == {'start':f'{address:08X}', 'length':length, 'sha256':digest}
            code = private_hooks.wrap(address, code, dict(row,record='posaudio fixture'))
        originals.append(code)
    prototypes = ''.join(f'void f_{a:08X}(Cpu *);\n' for a in functions)
    helper = (HERE/'private_runtime/carbon_posaudio.h').read_text()
    source = HARNESS.replace('PROTOTYPES', prototypes).replace('HELPER',helper).replace('TRANSLATED','\n'.join(originals))
    memory = bytearray(0xC00000)
    for _,_,va,size,raw in pe.sections:
        memory[pe.base+va:pe.base+va+size] = pe.data[raw:raw+size]
    env = {k:v for k,v in os.environ.items() if k != 'NFS_CARBON_POS_LAYOUT'}
    with tempfile.TemporaryDirectory(prefix='private-posaudio-') as td:
        tmp = Path(td); memfile = tmp/'image.bin';memfile.write_bytes(memory)
        (tmp/'game_image.h').write_text('#define PRIVATE_CARBON_SKIPFE 1\n')
        if options.premise:
            result = run_fixture(tmp,source,'premise','premise',memfile,env)
            assert result.returncode == 0,result.stderr
            print(result.stdout,end='');return 0
        for token in (None, '', 'game', '0', 'ITU', 'invalid'):
            setting = env if token is None else dict(env,NFS_CARBON_POS_LAYOUT=token)
            result = run_fixture(tmp,source,'game','identical',memfile,setting)
            assert result.returncode == 0,(token,result.stderr)
            print(f'POS game token={token!r} exit=0 comparisons=768')
        result = run_fixture(tmp,source,'itu','enabled',memfile,dict(env,NFS_CARBON_POS_LAYOUT='itu'))
        assert result.returncode == 0,result.stderr
        print(result.stdout,end='')
        for name,broken in (
                ('native-panner',helper.replace('if (carbon_posaudio_enabled() && M8(0x00BBF357u) == 5) {','if (0) {')),
                ('missing-stream-remap',helper.replace('M16(angle) = carbon_posaudio_default(M16(angle));','M16(angle) = M16(angle);')),
                ('wrong-channel-order',helper.replace('gains[i] = (float)cos(phase);','gains[i == 1 ? 4 : i == 4 ? 1 : i] = (float)cos(phase);').replace('gains[(i + 1) % 5] = (float)sin(phase);','unsigned next = (i + 1) % 5; gains[next == 1 ? 4 : next == 4 ? 1 : next] = (float)sin(phase);'))):
            assert broken != helper
            result = run_fixture(tmp,source.replace(helper,broken),name,'enabled',memfile,dict(env,NFS_CARBON_POS_LAYOUT='itu'))
            assert result.returncode == 1 and 'POS CHECK' in result.stderr,(name,result.returncode,result.stderr)
            print(f'POS mutant={name} exit=1 rejected')
        (tmp/'game_image.h').write_text('#define PRIVATE_CARBON_SKIPFE 0\n')
        result = run_fixture(tmp,source,'wrong-image','identical',memfile,dict(env,NFS_CARBON_POS_LAYOUT='itu'))
        assert result.returncode == 0,result.stderr
        print('POS wrong-image exit=0 comparisons=768')
    print('PRIVATE POSAUDIO PASS environments=8 original_comparisons=5376 mutants=3')
    return 0


if __name__ == '__main__':
    sys.exit(main())
