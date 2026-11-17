"""Private superset discovery, synthetic PE/native dispatch, no game/emulation.

Good: 8 entries (+6), immediate/displacement/unaligned DWORD/thunk/resync
witnesses, native return 42. Disabled pass: 2 entries and dispatch exits 9.
Interior/case/invalid seeds rejected; disabled body guard admits a case label.
Translation audit: 6 clean / 1 deliberately trapped or stubbed; missing definition rejected.
Zero-fill boundary DWORD: good 1 recovered; disabled zero-fill 0 recovered.
Stub decode trace: deliberately invalid branch reports its exact bad address.
Raw text operand coverage: 1 recovered; disabled window scan 0 recovered.
"""
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import build_all
import private_superset
from build_private import audit_superset_translation
from private_superset import expand
from private_inline_tables_test import PE as SwitchPE


class PE:
    base=0x400000;entry=0x401000;fingerprint='0'*64;sha256='0'*64;imports={}
    sections=[(b'.text',512,0x1000,512,0),(b'.data',32,0x3000,32,512)]
    def __init__(self):
        text=bytearray(b'\xcc'*512)
        text[:13]=bytes.fromhex('ba01104000b880104000ffd0c3')
        text[0x40:0x47]=bytes.fromhex('8d90a0104000c3')
        for at,value in ((0x80,42),(0xc0,43),(0x180,45),(0x160,46)):
            text[at:at+6]=b'\xb8'+struct.pack('<I',value)+b'\xc3'
        # Linear decoding crosses the actual entry and misses its immediate.
        text[0x9d:0xa0]=b'\xb8\x90\x90'
        text[0xa0:0xa5]=b'\xe9'+struct.pack('<i',0x401180-0x4010a5)
        text[0x170:0x174]=struct.pack('<I',0x401160)
        text[0xd0:0xd2]=b'\x0f\x04'
        text[0xf0:0xf5]=b'\xe9'+struct.pack('<i',0x401080-0x4010f5)
        data=bytearray(32)
        for off,target in ((1,0x4010c0),(8,0x4010d0),(12,0x401001),(20,0x4010f0)):
            data[off:off+4]=struct.pack('<I',target)
        self.data=bytes(text+data)
    def read(self,a,n):
        for _,_,va,count,raw in self.sections:
            off=a-self.base-va
            if 0<=off<count:return self.data[raw+off:raw+min(count,off+n)]
        return None


def main():
    pe=PE();initial=[(0x401000,0x401040,'entry'),(0x401040,0x401200,'displacement')]
    good,audit,_=expand(pe,initial)
    expected={0x401000,0x401040,0x401080,0x4010a0,0x4010c0,0x4010f0,0x401160,0x401180}
    assert {a for a,_,_ in good}==expected
    rejected={row['address']:row['reason'] for row in audit['rejected']}
    assert rejected[0x401001]=='inside_baseline_body'
    assert rejected[0x4010d0]=='invalid_opcode'
    assert audit['passes']>=2
    assert any(row['address']==0x4010c0 and any(v['site']==0x403001 for v in row['witnesses']) for row in audit['entries'])
    boundary=PE();boundary.sections=[PE.sections[0],(b'.data',4,0x3000,3,512)]
    boundary.data=boundary.data[:512]+bytes.fromhex('c01040')
    filled,_,_=expand(boundary,initial)
    assert 0x4010c0 in {a for a,_,_ in filled}
    # Switch case instructions belong to the already discovered dispatch body.
    switch=SwitchPE();switch.sections=[switch.sections[0],(b'.rdata',12,0x2000,12,256)]
    switch.data+=struct.pack('<I',0x401050)
    seeds=[(a,0x401100,'known') for a in (0x401000,0x401020,0x401040)]
    found,proof,_=expand(switch,seeds)
    assert 0x401050 not in {a for a,_,_ in found}
    assert any(v['address']==0x401050 and v['reason']=='inside_baseline_body' for v in proof['rejected'])
    source=Path(private_superset.__file__).read_text();guard='if occupied[entry-lo]:'
    assert source.count(guard)==1
    mutant={**private_superset.__dict__}
    exec(compile(source.replace(guard,'if False:'),'<disabled-body-guard>','exec'),mutant)
    false,_,_=mutant['expand'](switch,seeds)
    assert 0x401050 in {a for a,_,_ in false}
    zero_fill=" + b'\\0'*max(0, virtual_size-count)"
    assert source.count(zero_fill)==1
    unfilled={**private_superset.__dict__}
    exec(compile(source.replace(zero_fill,''),'<missing-zero-fill>','exec'),unfilled)
    missing,_,_=unfilled['expand'](boundary,initial)
    assert 0x4010c0 not in {a for a,_,_ in missing}
    raw_operand="reference(int.from_bytes(blob[offset:offset+4], 'little'), 'text_dword', lo+offset)"
    assert source.count(raw_operand)==1
    hidden={**private_superset.__dict__}
    exec(compile(source.replace(raw_operand,'pass'),'<missing-raw-operand>','exec'),hidden)
    invisible,_,_=hidden['expand'](pe,initial)
    assert 0x401160 not in {a for a,_,_ in invisible}
    print('SUPERSET PROOF PASS entries=8/2 additions=6 passes>=2 unaligned=1 interior/invalid/case rejected; broken case seeds=1')
    print('SUPERSET ZERO-FILL PASS boundary entries=1/0')
    print('SUPERSET RAW OPERAND PASS entries=1/0')
    with tempfile.TemporaryDirectory(prefix='private-superset-') as td:
        out=Path(td);fixture=out/'test.c'
        fixture.write_text('''#include "runtime.h"
#include <stdlib.h>
#include <stdio.h>
uint8_t *G;extern const uint32_t guest_func_addr[];extern void (*const guest_func_ptr[])(Cpu*);extern const unsigned guest_func_count;
void f_00401000(Cpu*);
void untranslated(Cpu*c,uint32_t a){(void)c;(void)a;exit(8);}
void host_import(Cpu*c,uint32_t a){(void)c;(void)a;exit(8);}
void dispatch(Cpu*c,uint32_t a){for(unsigned i=0;i<guest_func_count;i++)if(guest_func_addr[i]==a){guest_func_ptr[i](c);return;}puts("missing superset callback");exit(9);}
int main(void){G=calloc(1,65536);Cpu c={0};c.esp=0x8000;M32(c.esp)=0xfeed;f_00401000(&c);if(c.eax!=42||c.esp!=0x8004)return 1;free(G);puts("SUPERSET DISPATCH PASS value=42");return 0;}
''')
        for bad,funcs in ((False,good),(True,initial)):
            result=build_all.build_image(funcs,pe,str(out),'fixture',jobs=1,mw_patches=False)
            assert result['compile_errors']==0
            if not bad:
                discovery={'superset':{'entries':audit['entries']}}
                report=audit_superset_translation(pe,out,'fixture',discovery)
                assert report['fully_translated']==6 and report['entries_with_failures']==0
                path=out/'fixture_00.c';original=path.read_text()
                from private_render import replace_body
                path.write_text(replace_body(original,'f_00401080','{ untranslated(c, 0x00401080u); return; /* deliberately unsupported */ }'))
                report=audit_superset_translation(pe,out,'fixture',discovery)
                assert report['fully_translated']==5 and report['entries_with_failures']==1
                path.write_text(replace_body(original,'f_00401080','{ untranslated(c, 0x00401080u); } /* fixture: deliberately unsupported */'))
                report=audit_superset_translation(pe,out,'fixture',discovery)
                assert report['fully_translated']==5 and report['entries_with_failures']==1
                import json
                detail=json.loads((out/'superset_translation.json').read_text())
                assert detail['failures'][0]['kind']=='whole_function'
                bad_branch=PE();text=bytearray(bad_branch.data)
                text[0x80:0x86]=bytes.fromhex('744ec3cccccc');bad_branch.data=bytes(text)
                path.write_text(replace_body(original,'f_00401080','{ untranslated(c, 0x00401080u); } /* fixture: undecodable */'))
                audit_superset_translation(bad_branch,out,'fixture',discovery)
                detail=json.loads((out/'superset_translation.json').read_text())
                assert detail['failures'][0]['decode_site']==0x4010d0
                assert detail['failures'][0]['bytes'].startswith('0f04')
                path.write_text(original.replace('void f_00401080(', 'void missing_00401080('))
                try:audit_superset_translation(pe,out,'fixture',discovery)
                except AssertionError:pass
                else:raise AssertionError('missing superset definition accepted')
                path.write_text(original)
                print('SUPERSET TRANSLATION AUDIT PASS clean=6 trapped=1 stubbed=1 missing=rejected')
            r=subprocess.run(['clang','-fsanitize=address,undefined','-I',str(HERE),str(fixture),str(out/'fixture.a'),'-o',str(out/'test')],capture_output=True,text=True)
            if r.returncode:raise RuntimeError(r.stderr[-2000:])
            r=subprocess.run([str(out/'test')],capture_output=True,text=True)
            print(('broken' if bad else 'good')+f': exit={r.returncode} '+r.stdout.strip())
            assert r.returncode==(9 if bad else 0),r.stderr
    return 0


if __name__=='__main__':sys.exit(main())
