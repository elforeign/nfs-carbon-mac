"""Identity-LEA callback provenance, synthetic PE and native dispatch only.

Good: 5 entries, two dispatched callbacks return 43; disabled identity rule:
3 entries and the same native fixture exits 9 (0 callbacks resolved). Six
register variants preserve both callbacks; changed-base/displacement/index
controls leave the affected callback unknown. No private assets or emulation.
IAT value: 0 false entries; disabling the pre-binding guard admits 1 false entry.
"""
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import build_all
import private_callback_flow
from private_discovery import complete


class PE:
    base = 0x400000; entry = 0x401000; fingerprint = '0'*64; sha256 = '0'*64
    imports = {}
    sections = [(b'.text', 256, 0x1000, 256, 0)]

    def __init__(self, reg=3, lea=None):
        text = bytearray(b'\xcc'*256)
        caller = bytearray()
        for target, helper in ((0x4010c0, 0x401040), (0x4010e0, 0x401060)):
            caller += b'\x68' + struct.pack('<I', target)
            caller += b'\xe8' + struct.pack('<i', helper-(self.entry+len(caller)+5))
        caller += b'\xc3'; text[:len(caller)] = caller
        for at, r in ((0x40, reg), (0x60, 0)):
            saved = r in (3, 6, 7)
            code = bytearray(bytes([0x50+r]) if saved else b'')
            code += bytes([0x8b, 0x44+8*r, 0x24, 8 if saved else 4])
            # Six-byte alignment form: the disassembler prints [reg], even
            # though the zero displacement was encoded explicitly.
            code += lea if at == 0x40 and lea is not None else bytes([0x8d, 0x80+9*r])+b'\0'*4
            code += bytes([0xff, 0xd0+r])
            if saved: code += bytes([0x58+r])
            code += b'\xc2\x04\x00'
            text[at:at+len(code)] = code
        for at, value in ((0xc0, 42), (0xe0, 43)):
            # No frame prologue or non-fallthrough predecessor: only the
            # proven callback argument can justify these instruction entries.
            text[at-4:at] = b'\x31\xc0\x90\x90'
            text[at:at+6] = b'\xb8'+struct.pack('<I', value)+b'\xc3'
        self.data = bytes(text)

    def read(self, a, n):
        if a == 0x402000 and hasattr(self, 'iat_value'):
            return struct.pack('<I', self.iat_value)[:n]
        off = a-self.entry
        return self.data[off:off+n] if 0 <= off < len(self.data) else None


def main():
    initial = [(PE.entry, PE.entry+256, 'entry')]
    pe = PE(); good, audit = complete(pe, initial)
    expected = {0x401000, 0x401040, 0x401060, 0x4010c0, 0x4010e0}
    assert {a for a, _, _ in good} == expected
    assert audit['callback_argument_flow']['resolved_callback_targets'] == 2
    # Reproduce the actual analyzer defect, rather than deleting a discovered
    # address from a successfully analyzed result.
    source = Path(private_callback_flow.__file__).read_text()
    old = '                pass\n'
    assert source.count(old) == 1
    mutant = {**private_callback_flow.__dict__}
    exec(compile(source.replace(old, "                regs[args[0]]=frozenset()\n"), '<lost-identity-LEA>', 'exec'), mutant)
    with patch.object(private_callback_flow, 'targets', mutant['targets']):
        broken, before = complete(pe, initial)
    assert {a for a, _, _ in broken} == expected-{0x4010c0, 0x4010e0}
    assert before['callback_argument_flow']['resolved_callback_targets'] == 0
    for reg in (0, 1, 2, 3, 6, 7):
        found, _ = complete(PE(reg), initial)
        assert {a for a, _, _ in found} == expected
    for lea in (bytes.fromhex('8d9b01000000'), bytes.fromhex('8d9a00000000'),
                bytes.fromhex('8d9c0b00000000')):
        found, _ = complete(PE(3, lea), initial)
        assert 0x4010c0 not in {a for a, _, _ in found}
        assert 0x4010e0 in {a for a, _, _ in found}
    # A bound import is not the on-disk hint/name RVA. Give that RVA the same
    # numeric value as a decodable text entry to make the false seed observable.
    imported = PE(); imported.imports = {0x402000: 'example.dll!external'}
    imported.iat_value = 0x4010c0
    text = bytearray(imported.data)
    code = bytes.fromhex('538b1d002040008d9b00000000ffd35bc20400')
    text[0x40:0x60] = b'\xcc'*32; text[0x40:0x40+len(code)] = code
    imported.data = bytes(text)
    found, _ = complete(imported, initial)
    assert 0x4010c0 not in {a for a, _, _ in found}
    guard = 'if address in pe.imports:return frozenset()'
    assert source.count(guard) == 1
    unbound = {**private_callback_flow.__dict__}
    exec(compile(source.replace(guard, 'if False:return frozenset()'), '<raw-IAT-value>', 'exec'), unbound)
    with patch.object(private_callback_flow, 'targets', unbound['targets']):
        false, _ = complete(imported, initial)
    assert 0x4010c0 in {a for a, _, _ in false}
    print('IDENTITY LEA PROOF PASS entries=5/3 callbacks=2/0 registers=6 negative_controls=3')
    print('IAT VALUE PROOF PASS false entries=0/1 (disabled pre-binding guard)')
    with tempfile.TemporaryDirectory(prefix='callback-identity-lea-') as td:
        out = Path(td); fixture = out/'test.c'
        fixture.write_text('''#include "runtime.h"
#include <stdlib.h>
#include <stdio.h>
uint8_t *G;extern const uint32_t guest_func_addr[];extern void (*const guest_func_ptr[])(Cpu*);extern const unsigned guest_func_count;
void f_00401000(Cpu*);static unsigned callbacks;
void untranslated(Cpu*c,uint32_t a){(void)c;(void)a;exit(8);}
void host_import(Cpu*c,uint32_t a){(void)c;(void)a;exit(8);}
void dispatch(Cpu*c,uint32_t a){for(unsigned i=0;i<guest_func_count;i++)if(guest_func_addr[i]==a){++callbacks;guest_func_ptr[i](c);return;}puts("missing LEA callback");exit(9);}
int main(void){G=calloc(1,65536);Cpu c={0};c.esp=0x8000;M32(c.esp)=0xfeed;f_00401000(&c);if(c.eax!=43||c.esp!=0x8004||callbacks!=2)return 1;free(G);puts("IDENTITY LEA DISPATCH PASS callbacks=2 value=43");return 0;}
''')
        for bad, funcs in ((False, good), (True, broken)):
            result = build_all.build_image(funcs, pe, str(out), 'fixture', jobs=1, mw_patches=False)
            assert result['compile_errors'] == 0
            r = subprocess.run(['clang', '-fsanitize=address,undefined', '-I', str(HERE), str(fixture), str(out/'fixture.a'), '-o', str(out/'test')], capture_output=True, text=True)
            if r.returncode: raise RuntimeError(r.stderr[-2000:])
            r = subprocess.run([str(out/'test')], capture_output=True, text=True)
            print(('broken' if bad else 'good')+f': exit={r.returncode} '+r.stdout.strip())
            assert r.returncode == (9 if bad else 0), r.stderr
    return 0


if __name__ == '__main__':
    sys.exit(main())
