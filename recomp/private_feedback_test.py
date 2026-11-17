"""Translated Carbon IFeedback, native tick/eligibility/collision and shared model.

Baseline: 15 return-only originals, model output 0. Acceptance: 17 balanced ABIs;
Begin/End=1/1, Speed/Skid/Slip=4/4/4; collision/shift/NOS >0; hardware opens/writes=0.
Failure controls (measured by this driver): wheel bypass 4->0 speed calls;
collision at +38 17->15 balanced ABIs; collection +4 0.1->0 native speed output.
Each broken binary must exit 1, versus good 0. Missing private outputs: exit 3.
"""
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
PRIVATE = HERE/'private_runtime'
sys.path.insert(0, str(HERE))
import build_all
import private_hooks
import private_hooks_test
import recomp

SLOTS = ((0x04,0),(0x08,0),(0x0C,0),(0x10,0),(0x14,0),(0x18,3),(0x1C,3),(0x20,3),
         (0x24,3),(0x28,1),(0x2C,2),(0x30,1),(0x34,1),(0x38,1),(0x3C,1),(0x40,1),(0x44,2))


# Function fragments from the unmodified translated image, with only the
# hook definition name normalized. No history or whole-source baseline.
BASELINE_SHA = {
    0x00762000: "7840b863f70b846697bb3302b7bda9a87ee5ff54f08c7dc6dd1aec9a6b304783",
    0x00761F60: "3998db3dd993a71a9a81e5b607a7d2e95d6bea1ba8f321dfcd73537f1d5c846d",
    0x00765240: "89c2619b662c1acaea7b64d87149956e83d34e1eaf909ccd6d93103dee5e8420",
    0x00463A80: "3a764e85e38decb461ed1688b8e5c39c50558983895d25f0fd8dc35d21b5d443",
}
STUBS_SHA = "e361b6e6fcaee8867b5bd2200c987ac520f2089988b595e9f2b0764b607eb991"


def run(args, expected=0):
    result = subprocess.run(list(map(str,args)), capture_output=True, text=True)
    if result.returncode != expected and args and str(args[0]).endswith('/good'):
        import shutil
        shutil.copytree(Path(args[0]).parent,HERE/'out/carbon-feedback-debug',dirs_exist_ok=True)
    assert result.returncode == expected, (result.returncode, args[:3], result.stdout[-2500:], result.stderr[:3000]+result.stderr[-1000:])
    return result


def main():
    base = HERE/'out/carbon-base'
    if not all((base/p).is_file() for p in ('image.json','table.c','funcs.h','NFSC_41.c')):
        print('SKIP: private feedback requires Carbon image/build outputs')
        return 3
    image = json.loads((base/'image.json').read_text())
    attributes = Path(image['exe']).parent/'GLOBAL/attributes.bin'
    if not Path(image['exe']).is_file() or not attributes.is_file():
        print('SKIP: private feedback requires Carbon image/attributes')
        return 3
    pe = recomp.PE(image['exe'], expected_sha256=image['sha256'])
    native_slots = struct.unpack('<18I',pe.read(0x009E2188,72))
    stubs = [address for address in native_slots[1:] if pe.read(address,1) in (b'\xc3',b'\xc2')]
    assert len(stubs)==15
    for (slot,n), address in zip(SLOTS,native_slots[1:]):
        if address in stubs:
            assert pe.read(address,1 if n==0 else 3)==(b'\xc3' if n==0 else b'\xc2'+struct.pack('<H',n*4)), hex(address)
    assert bytes.fromhex('8B 46 54') in pe.read(0x00762000,0x30)
    starts=[int(v.strip().removesuffix('u'),16) for v in re.search(
        r'guest_func_addr\[\] = \{([^}]+)',(base/'table.c').read_text())[1].split(',')]
    sources={}
    def body(address):
        chunk=starts.index(address)//build_all.CHUNK
        if chunk not in sources:sources[chunk]=(base/f'NFSC_{chunk:02d}.c').read_text()
        text=sources[chunk]
        name=private_hooks.original_name(address)
        return private_hooks_test.body(text,name if f'void {name}(' in text else f'f_{address:08X}')
    for address,digest in BASELINE_SHA.items():
        original=body(address).replace(private_hooks.original_name(address),f'f_{address:08X}',1)
        assert hashlib.sha256(original.encode()).hexdigest()==digest, f'baseline fragment changed: {address:08X}'
    assert hashlib.sha256('\n'.join(body(a) for a in stubs).encode()).hexdigest()==STUBS_SHA
    addresses=(*stubs,0x00762000,0x00761F60,0x00765240,0x00463A80)
    native='\n'.join(body(a) for a in addresses)
    if 'void carbon_orig_00762000(' not in native:
        native=native.replace('void f_00762000(', 'void carbon_orig_00762000(',1)
    # Use the actual emitted wrapper when present; the same registry writer
    # also permits checking older, unhooked private build outputs.
    record=json.loads((PRIVATE/'hooks/feedback.json').read_text())['hooks'][0]
    assert record['provider']=='carbon_feedback_tick' and record['address']=='00762000'
    assert record['image_sha256']==pe.sha256
    assert record['witness']['sha256']==hashlib.sha256(pe.read(0x762000,16)).hexdigest()
    wrapped=private_hooks.wrap(0x762000,body(0x762000).replace('carbon_orig_00762000','f_00762000',1),record)
    wrapper=wrapped[wrapped.index('\n__attribute__((noinline))'):]
    native+='\nvoid carbon_feedback_tick(Cpu *, void (*)(Cpu *));\n'+wrapper+'\n'
    expected=[0]+[n for _,n in SLOTS]
    fixture=(PRIVATE/'carbon_feedback_fixture.h').read_text()
    fixture='static const unsigned expected_arguments[18]={'+','.join(map(str,expected))+'};\n'+fixture
    with tempfile.TemporaryDirectory(prefix='private-feedback-',dir=HERE/'out') as td:
        tmp=Path(td)
        (tmp/'game_image.h').write_text('extern int carbon_fixture_image_match;\n#define PRIVATE_CARBON_SKIPFE carbon_fixture_image_match\n')
        (tmp/'fixture.c').write_text(fixture)
        (tmp/'native.c').write_text('#include "funcs.h"\n'+native)
        mapped=bytearray(0x1000000)
        for _,_,va,size,offset in pe.sections:
            mapped[pe.base+va:pe.base+va+size]=pe.data[offset:offset+size]
        (tmp/'image.bin').write_bytes(mapped)
        (tmp/'exe.bin').write_bytes(Path(image['exe']).read_bytes())
        # Image-bound, native cobble speed records. Pin the decoded first record
        # and leave the three absent slots empty.
        curves=attributes.read_bytes()[0x3FFE8:0x40008]+bytes(96)
        curve=struct.unpack('<8f',curves[:32])
        assert all(abs(a-b)<1e-6 for a,b in zip(curve,(0,0,.1,5,0,0,.1,50))),curve
        (tmp/'curves.bin').write_bytes(curves)
        flags=['clang','-std=c11','-D_DARWIN_C_SOURCE','-DNFS_GAME=2','-DRECOMP_ABICHECK', '-O1','-g',
               '-fsanitize=address,undefined','-I',tmp,'-I',PRIVATE,'-I',ROOT/'runtime','-I',HERE,'-I',base]
        run([*flags,'-c',tmp/'native.c','-o',tmp/'native.o'])
        run([*flags,'-c',PRIVATE/'carbon_feedback_transport.c','-o',tmp/'transport.o'])
        def execute(label, mutate=None, native_source=None):
            for p in PRIVATE.glob('carbon_feedback*.h'):
                if p.name!='carbon_feedback_fixture.h':(tmp/p.name).write_bytes(p.read_bytes())
            if mutate:mutate(tmp)
            if native_source is not None:
                (tmp/'mutant.c').write_text('#include "funcs.h"\n'+native_source)
                run([*flags,'-c',tmp/'mutant.c','-o',tmp/'mutant.o'])
            obj=tmp/('mutant.o' if native_source else 'native.o')
            run([*flags,tmp/'fixture.c',obj,tmp/'transport.o','-o',tmp/label])
            result=run([tmp/label,tmp/'image.bin',tmp/'curves.bin',tmp/'exe.bin'],0 if label=='good' else 1)
            assert 'FEEDBACK '+('PASS' if label=='good' else 'FAIL') in result.stdout
            print(label+': '+result.stdout.strip().replace('\n','; '))
            return result
        execute('good')
        def bypass(tmp):
            p=tmp/'carbon_feedback_provider.h';s=p.read_text();s=s.replace('if (gamepad && self) M32(self + 0x54) = 0;', '(void)gamepad;');p.write_text(s)
        execute('broken-wheel-bypass',bypass)
        def collision(tmp):
            p=tmp/'carbon_feedback_provider.h';s=p.read_text();s=s.replace('{0x38,1,carbon_feedback_slot38,"Slot38"}', '{0x44,1,carbon_feedback_slot38,"Slot38"}').replace('{0x44,2,fb_collision,"Collision"}','{0x38,2,fb_collision,"Collision"}');p.write_text(s)
        execute('broken-collision-slot',collision)
        accessor=body(0x463A80)
        broken_accessor=accessor.replace('M32((uint32_t)(c->ecx))','M32((uint32_t)(c->ecx + 4u))',1)
        assert broken_accessor!=accessor
        execute('broken-surface-collection',native_source=native.replace(accessor,broken_accessor))
    print('PRIVATE FEEDBACK PASS slots=17 stubs=15 mutants=3 hardware=0/0')
    return 0


if __name__=='__main__':
    sys.exit(main())
