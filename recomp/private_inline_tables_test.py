"""Synthetic inline-table/vtable boundary regression; no private image bytes.

Good: referenced method after a bounded inline switch table is discovered and
native dispatch returns 43. Disable the rule: method absent, same dispatch exits 9.
Unbounded/wrong-index dispatch, absent witnesses and interior pointers do not seed an entry.
"""
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import build_all
import private_inline_tables
from private_discovery import complete


class PE:
    base=0x400000;entry=0x401000;fingerprint='0'*64;sha256='0'*64;imports={}
    sections=[(b'.text',256,0x1000,256,0),(b'.rdata',8,0x2000,8,256)]
    def __init__(self):
        text=bytearray(b'\xcc'*256)
        text[:21]=bytes.fromhex('b800000000e836000000b9002040008b4104ffd0c3')
        text[0x20:0x26]=bytes.fromhex('b82a000000c3')
        text[0x40:0x4c]=bytes.fromhex('83f8027724ff248574104000')
        text[0x50:0x56]=bytes.fromhex('b80a000000c3')
        text[0x56:0x5c]=bytes.fromhex('b80b000000c3')
        text[0x63:0x69]=bytes.fromhex('b80c000000c3')
        text[0x69]=0xc3
        for p,target in zip((0x74,0x78,0x7c),(0x401050,0x401056,0x401063)):text[p:p+4]=target.to_bytes(4,'little')
        text[0x80:0x88]=bytes.fromhex('8b01b82b000000c3')
        self.data=bytes(text)+(0x401020).to_bytes(4,'little')+(0x401080).to_bytes(4,'little')
    def read(self,a,n):
        for _,_,va,rs,raw in self.sections:
            offset=a-self.base-va
            if 0<=offset<rs:return self.data[raw+offset:raw+min(offset+n,rs)]
        return None


def main():
    pe=PE();initial=[(0x401000,0x401100,'entry')]
    good,audit=complete(pe,initial);known={a for a,_,_ in good}
    assert 0x401080 in known and audit['inline_table_recovered_entries']==[0x401080]
    assert not ({0x401050,0x401056,0x401063}&known)
    with patch.object(private_inline_tables,'boundaries',return_value=[]):broken,_=complete(pe,initial)
    assert 0x401080 not in {a for a,_,_ in broken}
    for mutation in ('wrong-index','no-guard','interior-pointer','no-witness'):
        other=PE();data=bytearray(other.data)
        if mutation=='wrong-index':data[0x41]=0xf9
        if mutation=='no-guard':data[0x43:0x45]=b'\x90\x90'
        if mutation=='interior-pointer':data[260:264]=(0x401081).to_bytes(4,'little')
        if mutation=='no-witness':data[260:264]=b'\0'*4
        other.data=bytes(data);funcs,proof=complete(other,initial)
        assert 0x401080 not in proof['inline_table_recovered_entries']
        assert 0x401080 not in {a for a,_,_ in funcs}
        assert 0x401081 not in {a for a,_,_ in funcs}
    print('INLINE TABLE PROOF PASS good=1 disabled=0 false seeds=0 (4 controls)')
    with tempfile.TemporaryDirectory(prefix='inline-table-discovery-') as td:
        out=Path(td);fixture=out/'test.c';fixture.write_text('''#include "runtime.h"
#include <stdlib.h>
#include <stdio.h>
uint8_t *G;extern const uint32_t guest_func_addr[];extern void (*const guest_func_ptr[])(Cpu*);extern const unsigned guest_func_count;
void f_00401000(Cpu*);
void untranslated(Cpu*c,uint32_t a){(void)c;(void)a;exit(8);}
void host_import(Cpu*c,uint32_t a){(void)c;(void)a;exit(8);}
void bad_jump(Cpu*c,uint32_t a){(void)c;(void)a;exit(7);}
void dispatch(Cpu*c,uint32_t a){for(unsigned i=0;i<guest_func_count;i++)if(guest_func_addr[i]==a){guest_func_ptr[i](c);return;}puts("unknown inline-table callback");exit(9);}
int main(void){G=calloc(1,0x403000);M32(0x402000)=0x401020;M32(0x402004)=0x401080;Cpu c={0};c.esp=0x8000;M32(c.esp)=0xfeed;f_00401000(&c);if(c.eax!=43||c.esp!=0x8004)return 1;free(G);puts("INLINE TABLE DISPATCH PASS value=43");return 0;}
''')
        for bad,funcs in ((False,good),(True,broken)):
            result=build_all.build_image(funcs,pe,str(out),'fixture',jobs=1,mw_patches=False)
            assert result['compile_errors']==0
            command=['clang','-fsanitize=address,undefined','-I',str(HERE),str(fixture),str(out/'fixture.a'),'-o',str(out/'test')]
            r=subprocess.run(command,capture_output=True,text=True)
            if r.returncode:raise RuntimeError(r.stderr[-2000:])
            r=subprocess.run([str(out/'test')],capture_output=True,text=True)
            print(('broken' if bad else 'good')+': exit='+str(r.returncode)+' '+r.stdout.strip());assert r.returncode==(9 if bad else 0),r.stderr
    return 0


if __name__=='__main__':sys.exit(main())
