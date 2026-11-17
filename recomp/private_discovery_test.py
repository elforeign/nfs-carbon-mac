"""Static callback closure + quarantine identity regression (synthetic PE only).

Good: 5/5 static entries, forwarded callback returns 44, shared-address
Carbon/MW bodies return 42/stay inert, table-only method returns 43. Broken: omit the code-only callback
from the very same native fixture -> dispatch exits 9 (unknown target).
Table boundaries: good 0 false entries; remove the boundary guard -> 1 false entry.
"""
from pathlib import Path
import subprocess
import sys
import tempfile
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import build_all
from private_discovery import complete
sys.path.insert(0,str(HERE/'private_runtime'))
from quarantine import quarantine
import private_discovery


class PE:
    base=0x400000;entry=0x401000;fingerprint='0'*64;sha256='0'*64;imports={}
    sections=[(b'.text',160,0x1000,160,0),(b'.data',8,0x2000,8,160)]
    def __init__(self):
        text=bytearray(b'\xcc'*160)
        text[:24]=bytes.fromhex('b9301040006888104000b800204000e84c00000083c404c3')
        text[0x30:0x36]=bytes.fromhex('b82a000000c3')
        text[0x40:0x44]=bytes.fromhex('31c09090')
        text[0x44:0x4a]=bytes.fromhex('b82b000000c3')
        text[0x60:0x65]=bytes.fromhex('ff542404c3')
        text[0x84:0x88]=bytes.fromhex('31c09090')
        text[0x88:0x8e]=bytes.fromhex('b82c000000c3')
        self.data=bytes(text)+(0x401060).to_bytes(4,'little')+(0x401044).to_bytes(4,'little')
    def read(self,a,n):
        for _,vs,va,rs,raw in self.sections:
            offset=a-self.base-va
            if 0<=offset<rs:return self.data[raw+offset:raw+min(offset+n,rs)]
        return None


def main():
    pe=PE();funcs,audit=complete(pe,[(0x401000,0x4010a0,'entry')])
    expected={0x401000,0x401030,0x401044,0x401060,0x401088}
    assert {a for a,_,_ in funcs}==expected
    assert not audit['uncovered_enumerated_targets']
    # A referenced word array is not necessarily a vtable: stop when a word
    # points into an instruction's immediate rather than an entry boundary.
    decoy=PE()
    decoy.sections=[PE.sections[0],(b'.data',12,0x2000,12,160)]
    decoy.data=decoy.data[:164]+(0x401031).to_bytes(4,'little')+(0x401044).to_bytes(4,'little')
    found,_=complete(decoy,[(0x401000,0x4010a0,'entry')])
    assert 0x401031 not in {a for a,_,_ in found}
    mutant={**private_discovery.__dict__}
    source=Path(private_discovery.__file__).read_text()
    old='if target not in starts and target not in accepted:break'
    assert source.count(old)==1
    exec(compile(source.replace(old,'if False:break'),'<broken table boundary>','exec'),mutant)
    broken,_=mutant['complete'](decoy,[(0x401000,0x4010a0,'entry')])
    assert 0x401031 in {a for a,_,_ in broken}
    print('TABLE BOUNDARY PASS false entries: good=0 broken=1')
    with tempfile.TemporaryDirectory(prefix='callback-closure-') as td:
        out=Path(td);host=out/'boot.c'
        host.write_text('#include "runtime.h"\nvoid mw_f_00401030(Cpu *c){c->eax=999;}\n')
        flags=['-I',str(HERE)]
        original=host.read_bytes()
        try:quarantine(host,flags,[(0x401000,0x4010a0)])
        except ValueError as error:assert 'engine implementation selected:' in str(error)
        else:raise AssertionError('MW host implementation accepted')
        assert host.read_bytes()==original
        host.write_text('#include "runtime.h"\nvoid mw_f_00401030(Cpu *c){(void)c;}\n')
        fixture=out/'fixture.c'
        fixture.write_text('''#include "runtime.h"
#include <stdlib.h>
#include <stdio.h>
uint8_t *G;extern const uint32_t guest_func_addr[];extern void (*const guest_func_ptr[])(Cpu*);extern const unsigned guest_func_count;
void f_00401000(Cpu*),f_00401030(Cpu*),f_00401044(Cpu*),mw_f_00401030(Cpu*);
void untranslated(Cpu*c,uint32_t a){(void)c;(void)a;exit(8);}
void host_import(Cpu*c,uint32_t a){(void)c;(void)a;exit(8);}
void dispatch(Cpu*c,uint32_t a){for(unsigned i=0;i<guest_func_count;i++)if(guest_func_addr[i]==a){guest_func_ptr[i](c);return;}puts("unknown callback rejected");exit(9);}
int main(void){G=calloc(1,65536);Cpu c={0};c.esp=0x8000;M32(c.esp)=0xfeed;
 f_00401000(&c);if(c.eax!=44||c.esp!=0x8004)return 1;
 c.esp=0x8000;f_00401030(&c);if(c.eax!=42)return 4;
 mw_f_00401030(&c);if(c.eax!=42)return 2;
 c.esp=0x8000;f_00401044(&c);if(c.eax!=43)return 3;
 free(G);puts("CALLBACK/IDENTITY PASS entries=5 values=44/42/43");return 0;}
''')
        for broken in (False,True):
            selected=[f for f in funcs if not (broken and f[0]==0x401088)]
            result=build_all.build_image(selected,pe,str(out),'fixture',jobs=1,mw_patches=False)
            assert result['compile_errors']==0
            binary=out/'fixture'
            cmd=['clang','-I',str(HERE),str(fixture),str(host),str(out/'fixture.a'),'-o',str(binary)]
            r=subprocess.run(cmd,capture_output=True,text=True)
            if r.returncode:raise RuntimeError(r.stderr[-2000:])
            r=subprocess.run([str(binary)],capture_output=True,text=True)
            print(('broken: ' if broken else 'good: ')+r.stdout.strip());assert r.returncode==(9 if broken else 0),r.stderr
    print('PRIVATE DISCOVERY PASS (code callbacks, direct closure, table entries, identity collision)')


if __name__=='__main__':main()
