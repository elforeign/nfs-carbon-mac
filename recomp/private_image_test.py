"""Private-image pipeline/CRT ABI checks, using synthetic code only.

Good: pipeline/archive succeeds and 89 native CRT checks pass. The compiler
control reports 2 failed chunks and no archive. Broken cdecl cleanup: fixture exits
1 on check 2 (caller stack corruption). Runtime namespace: good object 0 stray
symbols; broken object 1 stray symbol rejected. All controls run in this driver.
Import-thunk fixture: 4 native assertions pass; disabled resolver exits 4 at the
unknown call before the host handler. Unregistered slots/truncated thunks stay traps.
Unaligned data callback: 1 frame-prologue callback found, 1 interior pointer
rejected; legacy aligned-only control fails the same callback-presence check.
Broken setjmp save: exits 1 at check 81 (saved nonvolatile registers).
"""
from pathlib import Path
import subprocess
import sys
import tempfile
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import build_all
import recomp
from build_private_runtime import checked_runtime_symbols
from build_private import image_functions


def main():
    with tempfile.TemporaryDirectory(prefix='private-image-test-') as td:
        tmp=Path(td)
        class CallbackPE:
            base=0x400000
            sections=[(b'.text',64,0x1000,64,0),(b'.data',8,0x2000,8,64)]
            data=bytes(10)+bytes.fromhex('558bec83ec10c9c3')+bytes(46)+(0x40100a).to_bytes(4,'little')+(0x40100b).to_bytes(4,'little')
            def read(self,a,n):
                offset=a-0x401000
                return self.data[offset:offset+n] if 0<=offset<64 else None
        manifest=tmp/'functions.tsv'
        manifest.write_text('00401000\tfixture\t10\tfalse\n')
        found=image_functions(CallbackPE(),manifest)
        assert {a for a,_,_ in found}=={0x401000,0x40100a}
        legacy=image_functions(CallbackPE(),manifest,frame_callbacks=False)
        try:assert 0x40100a in {a for a,_,_ in legacy}
        except AssertionError:pass
        else:raise AssertionError('aligned-only mutant unexpectedly found callback')
        class PE:
            fingerprint='0'*64
            sha256='0'*64
            imports={}
            def read(self,a,n):
                # Synthetic code at an MW-patch site must remain generic.
                return {0x004F6D65:bytes.fromhex('a1c4428f00c3')}.get(a,b'')[:n]
        pe=PE()
        # rd() sites are bypassed only for a generic build, even when a private
        # image happens to use the same numeric addresses as MW.
        rc=recomp.Recompiler(pe=pe,mw_patches=False);rc.calls=True
        i=next(rc.md.disasm(pe.read(0x004F6D65,6),0x004F6D65))
        assert 'extratrax' not in rc.rd(i,i.operands[1])
        broken=recomp.Recompiler(pe=pe,mw_patches=True);broken.calls=True
        assert 'extratrax' in broken.rd(i,i.operands[1])
        class TinyPE:
            fingerprint='0'*64
            sha256='0'*64
            imports={0x3000:'fixture!answer'}
            def read(self,a,n):
                if 0x2000<=a<0x2006:
                    return bytes.fromhex('ff2500300000')[a-0x2000:a-0x2000+n]
                code=bytes.fromhex('e8fb0f0000c3');offset=a-0x1000
                return code[offset:offset+n] if 0<=offset<len(code) else None
        result=build_all.build_image([(0x1000,0x1006,'synthetic')],TinyPE(),str(tmp),'tiny',jobs=1,mw_patches=False)
        assert result['translated']==1 and (tmp/'tiny.a').is_file()
        assert 'mw_' not in (tmp/'table.c').read_text()
        harness=tmp/'thunk_fixture.c'
        harness.write_text('''#include "runtime.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
uint8_t *G;
void f_00001000(Cpu *);
void untranslated(Cpu *c,uint32_t a) {(void)c;(void)a;exit(4);}
void host_import(Cpu *c,uint32_t slot) {
    assert(slot==0x3000);assert(c->esp==0x3ffc&&M32(c->esp)==0x1005);
    c->eax=42;c->esp+=4;
}
int main(void) {G=calloc(1,65536);Cpu c={0};c.esp=0x4000;M32(c.esp)=0xfeed;
    f_00001000(&c);assert(c.eax==42);assert(c.esp==0x4004);free(G);
    puts("IMPORT THUNK PASS checks=4");return 0;}
''')
        for disabled in (False,True):
            if disabled:
                rc=recomp.Recompiler(pe=TinyPE(),functions={0x1000:0x1006},mw_patches=False)
                rc.calls=True;code,why=rc.translate(0x1000,0x1006)
                assert code is not None
                (tmp/'tiny_00.c').write_text('#include "funcs.h"\n'+code)
            binary=tmp/'thunk_fixture'
            command=['clang','-I',str(HERE),'-I',str(tmp),str(tmp/'tiny_00.c'),str(harness),'-o',str(binary)]
            subprocess.run(command,capture_output=True,check=True)
            r=subprocess.run([str(binary)],capture_output=True,text=True)
            assert r.returncode==(4 if disabled else 0)
            if not disabled:print(r.stdout.strip())
        other=TinyPE();other.imports={}
        rc=recomp.Recompiler(pe=other,functions={0x1000:0x1006},mw_patches=False,import_thunks=True)
        rc.calls=True;code,_=rc.translate(0x1000,0x1006)
        assert 'call to unknown target' in code
        class ShortThunk(TinyPE):
            def read(self,a,n):
                return bytes.fromhex('ff25003000')[:n] if a==0x2000 else super().read(a,n)
        rc=recomp.Recompiler(pe=ShortThunk(),functions={0x1000:0x1006},mw_patches=False,import_thunks=True)
        rc.calls=True;code,_=rc.translate(0x1000,0x1006)
        assert 'call to unknown target' in code
        # The failure path must remove a stale archive and keep full compiler
        # diagnostics. A deliberately invalid compiler option is deterministic.
        import os
        original=os.environ.get('RECOMP_CFLAGS')
        os.environ['RECOMP_CFLAGS']='-private-image-deliberate-invalid-option'
        try:
            try:build_all.build_image([(0x1000,0x1006,'synthetic')],TinyPE(),str(tmp),'tiny',jobs=1,mw_patches=False)
            except SystemExit as e:assert e.code==1
            else:raise AssertionError('compiler failure accepted')
        finally:
            if original is None:os.environ.pop('RECOMP_CFLAGS',None)
            else:os.environ['RECOMP_CFLAGS']=original
        assert not (tmp/'tiny.a').exists()
        assert 'unknown argument' in (tmp/'tiny_00.c.log').read_text()
        for broken in (False, True):
            path=tmp/'namespace.c'
            path.write_text('void '+('f_00001000' if broken else 'mw_f_00001000')+'(void *c) {(void)c;}\n')
            obj=tmp/'namespace.o'
            subprocess.run(['clang','-c',str(path),'-o',str(obj)],check=True,capture_output=True)
            try:checked_runtime_symbols([obj])
            except ValueError:
                assert broken
            else:assert not broken
        for mutant in ('good','cdecl','setjmp'):
            source=(HERE/'private_runtime/crt.c').read_text()
            if mutant=='cdecl':source=source.replace('#define CR(v) RET(v, 0)','#define CR(v) RET(v, 1)')
            if mutant=='setjmp':
                assert source.count('M32(buffer)=c->ebp;')==1
                source=source.replace('M32(buffer)=c->ebp;','M32(buffer)=0;')
            path=tmp/(mutant+'.c');path.write_text(source)
            binary=tmp/mutant
            command=['clang','-std=c11','-Wall','-Wextra','-Wno-unused-parameter','-g','-fsanitize=address,undefined',
                     '-I',str(HERE),'-I',str(HERE/'private_runtime'),'-I',str(HERE.parent/'runtime'),str(path),str(HERE/'private_runtime/crt_harness.c'),'-o',str(binary)]
            r=subprocess.run(command,capture_output=True,text=True)
            if r.returncode:raise RuntimeError(r.stderr[-3000:])
            r=subprocess.run([str(binary)],capture_output=True,text=True)
            print(mutant+': '+(r.stdout+r.stderr).strip()[-1600:])
            assert r.returncode==(0 if mutant=='good' else 1)
            if mutant=='cdecl':assert 'cdecl preserves caller arguments' in r.stderr
            if mutant=='setjmp':assert 'setjmp saved registers' in r.stderr
    print('PRIVATE IMAGE PASS: translation/archive, compiler control, CRT ABI, broken cdecl/setjmp controls')


if __name__=='__main__':main()
