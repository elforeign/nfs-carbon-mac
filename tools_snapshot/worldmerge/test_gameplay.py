"""Core icon overlay proof (private inputs; exit 3 when absent).

Live BIN-only attempt: alloc=145, rock=0, rock_shown=0.
Matched no-gameplay control: alloc=145, rock=0, rock_shown=0 (38 samples).
Paired overlay before the name-relocation fix: startup frame 2 hung.
Corrected pair live, shop bin 32: alloc=199, rock=54, rock_shown=0.
Shop bin = the destination's highest race bin (35): rock_shown=8 in 259
samples (the 8 shops; HUD minimap only). Offline: 8/8 shops carry 35;
the converter that wrote 32 fails with 'shop bin'.
Check: rock_shown > 0, alloc <= 256; removing gameplay must give rock=0.
Offline: 54/54 shifted triggers, 0/54 in the unshifted broken control;
original vault buffers preserved; only four native array fixups redirected;
parent keys retained,
collection-key/export clashes rejected before writing output.
Place-data proof: baseline has 0/4 house premises, 4/4 gate arrays,
0/15 resolved exit markers and 0/15 garage subtypes. Fixed: 4/4 houses,
8/8 shop premises, 3/3 genuine lots, 16/16 and 7/7 memberships,
15/15 markers and subtypes. Broken controls: inherited Template=1 accepts
0/4 houses; no append retains 4/4; omitted markers resolve 0/15.
Premises must ship with the separate save-compatibility change.
Standalone overlay harness: 12/13 pass with the optional sound callback
unlinked (exit 1); its no-sound fixture supplies that dependency: 13/13, exit 0.
"""
import argparse
from collections import Counter
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import gameplay as g
from formats import FormatError

MW = g.DEFAULT_MW.parent/'GLOBAL/GAMEPLAY.BIN'
CARBON = g.DEFAULT_CARBON.parent/'GLOBAL/gameplay.bin'
ASSETS = MW.is_file() and CARBON.is_file() and all(
    (HERE.parents[1]/'recomp/out/carbon-base'/f'NFSC_{n:02}.c').is_file() for n in (4, 26, 27))


def live_counts(path):
    rows = []
    with Path(path).open() as stream:
        for line in stream:
            if 'carbon_minimap: ' in line:
                fields = dict(re.findall(r'(\w+)=([^\s]+)', line))
                rows.append(tuple(int(fields[k]) for k in ('alloc', 'rock', 'rock_shown')))
    assert rows, 'no minimap diagnostic samples'
    return rows


def check_live(on, off):
    enabled, disabled = live_counts(on), live_counts(off)
    assert all(0 <= shown <= rock <= alloc <= 256 for alloc, rock, shown in enabled)
    assert max(shown for _, _, shown in enabled) > 0, 'no visible appended icons'
    assert all(rock == shown == 0 and alloc <= 256 for alloc, rock, shown in disabled), 'control contains appended icons'
    return {'overlay': sorted(set(enabled)), 'without_gameplay': sorted(set(disabled)),
            'samples': [len(enabled), len(disabled)]}


def check_records(source, output):
    expected = {c.key: c for _, c in source.triggers()}
    template = {c.key: t for t, c in source.triggers()}
    # The highest bin, read from the destination's own race_bin records.
    bins = [struct.unpack('<I', f[3])[0] for c in output.collections.values()
            if c.parent in output.collections and output.collections[c.parent].name == b'race_bin\0'
            for f in c.fields if f[0] == 0x6CE23062]
    assert len(bins) == 6 and max(bins) == 35
    actual = {c.key: c for _, c in output.triggers() if c.key in expected}
    assert set(actual) == set(expected) and len(actual) == 54
    counts = Counter()
    for key, before in expected.items():
        after = actual[key]
        assert (after.parent, after.cls, after.export) == (before.parent, before.cls, before.export)
        assert after.layout == before.layout and len(after.layout) == 8
        assert after.name == before.name and after.name not in (None, b'\0')
        old = {f[0]: f for f in before.fields}
        new = {f[0]: f for f in after.fields}
        shop = template[key] == 0x4698966B
        place = template[key] != 0xB05871D3
        assert set(new) == set(old) | {0x9995178A} | ({0xF3EA3201} if shop else set())
        assert new[0x9995178A][1:] == (0xA3F0C234, 0x40, b'muscle\0') if place else (
            new[0x9995178A][1:] == (0xA3F0C234, 0x40, bytes(4)))
        if shop:
            assert new[0xF3EA3201][1:] == (0xA3F0C234, 0x40, b'safehouse\0')
        for field, (_, typ, flags, payload) in old.items():
            converted = new[field]
            assert converted[1] == typ
            assert converted[2] == (0x40 if flags == 0x20 else flags)
            if field == 0x6CE23062:
                shop = template[key] == 0x4698966B
                assert converted[3] == struct.pack('<I', max(bins) if shop else 32), 'shop bin'
                counts['shop_bin'] += shop
            elif field == 0x9F743A0E:
                x, y, z = struct.unpack('<3f', payload)
                assert converted[3] == struct.pack('<3f', x+8192, y, z), 'position shift missing'
                counts['shifted'] += struct.unpack('<f', converted[3][:4])[0] > 7000
            elif field == 0xF3EA3201 and shop:
                assert converted[3] == b'safehouse\0'
            else:
                assert converted[3] == payload
    assert counts['shifted'] == 54 and counts['shop_bin'] == 8


def place_triggers(core):
    return {c.key: (t, c) for t, c in core.triggers() if t in (0x326427BB, 0x4698966B, 0x73049919)}


def field_value(core, collection, field):
    """Read bytes using raw field entries and relocation rows, independently."""
    _, _, _, off = next(r for r in core.exports if r[0] == collection.export)
    n = struct.unpack_from('<I', core.raw, off+20)[0]
    nt = struct.unpack_from('<H' if core.carbon else '<I', core.raw, off+24)[0]
    padded = (nt+1) & ~1 if core.carbon else nt
    for i in range(n):
        at = off+32+padded*4+12*i
        key, val, ti, flags, _ = struct.unpack_from('<IIHBB', core.raw, at)
        if key != field:
            continue
        typ = struct.unpack_from('<I', core.raw, off+32+ti*4)[0]
        fixup = core.fixups.get((0, at+4))
        if flags & (0x40 if core.carbon else 0x20) and not (typ == 0xA3F0C234 and fixup):
            return struct.pack('<I', val)
        kind, dep, target = fixup
        assert (kind, dep) == (3, 1)
        if field in (0x64893DA8, 0x916E0E78):
            alloc, count, stride, enc = struct.unpack_from('<4H', core.binary, target)
            assert alloc == count and stride == 4 and enc == 0
            return core.binary[target:target+8+count*4]
        assert typ == 0xA3F0C234
        assert flags == (0x40 if core.carbon else 0x20), 'text must be an inline relocated pointer'
        end = core.binary.index(b'\0', target)
        return core.binary[target:end+1]
    raise AssertionError(f'missing field {field:08X}')


def member_keys(core, activity, field):
    payload = field_value(core, core.collections[activity], field)
    return list(struct.unpack('<%dI' % ((len(payload)-8)//4), payload[8:]))


def check_memberships(source, target, output):
    triggers = place_triggers(source)
    for activity, parents, count in ((0x3103659B, (0x326427BB, 0x4698966B), 16),
                                      (0x10874E8D, (0x73049919,), 7)):
        expected = {k for k, (t, _) in triggers.items() if t in parents}
        for field in (0x64893DA8, 0x916E0E78):
            native = member_keys(target, activity, field)
            actual = member_keys(output, activity, field)
            assert actual[:4] == native and len(native) == 4
            assert len(actual) == len(set(actual)) == count, 'membership count'
            assert set(actual[4:]) == expected, 'membership keys'


def marker_resolution(source, output):
    refs = {struct.unpack('<I', f[3])[0] for _, c in place_triggers(source).values()
            for f in c.fields if f[0] == 0x2241F4CD}
    assert len(refs) == 15
    return refs, refs & output.collections.keys()


# Complete retained consumers; no application entry point, archive or GPU.
NATIVE = {('NFSC_27.c', '00638430'): '77cae37207e7c9a4f3340763fd104b239f93a07e602440afb173086eb56a0cf6',
          ('NFSC_04.c', '00461340'): 'ff00401f38a6ab43c6f05d95700d5b8bfe4954881ab5a8f9d367ef0cb1fa220a'}
NAME_HARNESS = r'''
#include "host.h"
#include <stdlib.h>
uint8_t *G;
static unsigned count, walked, built;
static uint32_t keys[54], headers[54];
void f_00461340(Cpu *c);
static void fail(const char *s){fprintf(stderr,"NAME CHECK: %s walked=%u\n",s,walked);exit(1);}
void f_00463360(Cpu*c){c->eax=count;c->esp+=4;}
void f_00460620(Cpu*c){c->eax=0;c->esp+=4;}
void f_00460630(Cpu*c){c->eax=0;c->esp+=4;}
void f_00466810(Cpu*c){(void)c;fail("unexpected static definition");}
void f_004652E0(Cpu*c){c->eax=keys[0];c->esp+=4;}
void f_00465300(Cpu*c){uint32_t key=arg(c,0);unsigned i=0;while(i<count&&keys[i]!=key)++i;if(i==count)fail("enumeration key");c->eax=i+1<count?keys[i+1]:0;c->esp+=8;}
void f_00465930(Cpu*c){if(arg(c,0)!=0x5CEA9D46)fail("class");unsigned i=0;while(i<count&&keys[i]!=arg(c,1))++i;if(i==count)fail("collection key");c->eax=0x10000+40*i;c->esp+=4;}
void f_00469870(Cpu*c){c->esp+=4;}
void f_00678410(Cpu*c){(void)c;fail("missing layout");}
void f_004711B0(Cpu*c){uint32_t p=arg(c,0);if(!p)fail("null CollectionName: reverse scan would start at UINT32_MAX");if(p>=0xC00000)fail("name address");size_t n=strnlen((char*)G+p,256);if(!n||n==256)fail("name extent");c->eax=(uint32_t)n;c->esp+=4;}
void f_004639D0(Cpu*c){const char *p=(char*)G+arg(c,0);if(!*p||strchr(p,'/')||strchr(p,'\\'))fail("basename");c->eax=++walked;c->esp+=4;}
void f_006A1560(Cpu*c){if(arg(c,0)!=count*4)fail("allocation count");c->eax=0x50000;c->esp+=4;}
void f_006A15A0(Cpu*c){c->esp+=4;}
void f_00633B70(Cpu*c){c->esp+=4;}
void f_00622180(Cpu*c){c->eax=arg(c,1);c->esp+=4;}
void f_006365F0(Cpu*c){if(arg(c,1)!=count||arg(c,2)!=0x18)fail("result count");built=arg(c,1);c->eax=0x60000;c->esp+=16;}
/* RETAINED_CONSUMERS */
int main(int argc,char**argv){
 if(argc!=3)return 2;FILE*f=fopen(argv[1],"rb");if(!f)return 2;
 G=calloc(1,0xC00000);if(!G)return 2;
 if(fread(G,1,0xC00000,f)!=0xC00000)return 2;fclose(f);
 count=M32(0x30000);if(count!=54)return 2;
 for(unsigned i=0;i<count;i++){
  keys[i]=M32(0x30004+8*i);headers[i]=M32(0x30008+8*i);
  uint32_t layout=M32(headers[i]+28);M32(0x10000+40*i+0x18)=layout;M32(0x10000+40*i+0x1c)=1;
  if(atoi(argv[2]))M32(layout)=0; // Reproduce the omitted second-level fixup.
 }
 M32(0x801c)=0x9000;Cpu c={0};c.ecx=0x8000;c.esp=0x90000;c.fs_base=0x7000;uint32_t sp=c.esp;
 f_00638430(&c);
 if(c.esp!=sp+4||walked!=54||built!=54)fail("consumer completion");
 printf("NATIVE NAME PASS walked=%u built=%u\n",walked,built);free(G);return 0;
}
'''


def native_names(core, out):
    import hashlib
    fragments = []
    for (unit, address), digest in NATIVE.items():
        text = (HERE.parents[1]/'recomp/out/carbon-base'/unit).read_text()
        match = re.search(r'void f_'+address+r'\(Cpu [^)]*\)\s*\{', text)
        assert match
        fragment = text[match.start():text.index('\n}', match.end())+2]
        assert hashlib.sha256(fragment.encode()).hexdigest() == digest
        fragments.append(fragment)
    # Independently replay type-2/type-3 relocations into fixture memory, just
    # as 00467770 does. No production parser's resolved .name value is used.
    image = bytearray(0xC00000)
    image[0x100000:0x100000+len(core.raw)] = core.raw
    image[0x200000:0x200000+len(core.binary)] = core.binary
    bases, current = (0x100000, 0x200000), 0
    for offset, kind, dep, value in core.pointer_rows:
        if kind == 2:
            current = dep
        elif kind == 3:
            assert current in (0, 1) and dep in (0, 1)
            struct.pack_into('<I', image, bases[current]+offset, bases[dep]+value)
    rows = core.exports[-54:]
    struct.pack_into('<I', image, 0x30000, len(rows))
    for i, (_, _, _, off) in enumerate(rows):
        key = struct.unpack_from('<I', core.raw, off)[0]
        struct.pack_into('<II', image, 0x30004+8*i, key, 0x100000+off)
    data = out/'names.bin';data.write_bytes(image)
    source = out/'names.c'
    source.write_text(NAME_HARNESS.replace('/* RETAINED_CONSUMERS */', '\n'.join(fragments)))
    binary = out/'names'
    build = subprocess.run(['clang', '-O1', '-g', '-fsanitize=address,undefined',
                            '-I', str(HERE.parents[1]/'runtime'), '-I', str(HERE.parents[1]/'recomp'),
                            str(source), '-o', str(binary)], capture_output=True, text=True)
    assert build.returncode == 0, build.stderr[-2000:]
    for broken in (0, 1):
        result = subprocess.run([str(binary), str(data), str(broken)], capture_output=True, text=True, timeout=10)
        assert result.returncode == broken, result.stdout+result.stderr
        if broken:
            assert 'null CollectionName' in result.stderr
            print('old name relocation rejected: 54 null names versus fixed 0; '+result.stderr.strip())
        else:
            print(result.stdout.strip())


ENUM_NATIVE = {'00631430': '009647a2878b76a3dd40da67cfbec00b2aeba0db5b797e0367ea4993ee1c3224',
               '0061F600': 'ff54a0913e5d7c0b1b018d8be1d7a2f270ee74fe6d5afe237414a50dc5b38f0e'}
ENUM_HARNESS = r'''
#include "host.h"
#include <stdlib.h>
uint8_t *G;
static uint32_t keys[4], rows, allocation=0x60000;
void f_0061F600(Cpu*c);
static void fail(const char*s){fprintf(stderr,"PREMISES CHECK: %s\n",s);exit(1);}
static uint32_t handle(uint32_t key){
 for(unsigned i=0;i<rows;i++)if(M32(0x10000+12*i)==key)return 0x10000+12*i;
 fail("unknown collection");return 0;
}
void f_004AC040(Cpu*c){M32(c->ecx)=handle(arg(c,0));M32(c->ecx+4)=0x4000;c->esp+=12;}
void f_00461340(Cpu*c){M32(c->ecx)=arg(c,0);M32(c->ecx+4)=0x4000;c->esp+=12;}
void f_004613E0(Cpu*c){c->eax=M32(M32(c->ecx));c->esp+=4;}
void f_00463A30(Cpu*c){c->eax=M32(M32(c->ecx)+4);c->esp+=4;}
void f_00463A80(Cpu*c){
 if(arg(c,0)!=0x3E9156CA||arg(c,1))fail("template lookup");
 uint32_t h=M32(c->ecx);
 while(M32(h+8)==0xFFFFFFFF){if(!M32(h+4))fail("missing inherited template");h=handle(M32(h+4));}
 c->eax=h+8;c->esp+=12;
}
void f_004652E0(Cpu*c){c->eax=keys[0];c->esp+=4;}
void f_00465300(Cpu*c){unsigned i=0;while(i<4&&keys[i]!=arg(c,0))++i;if(i==4)fail("enum key");c->eax=i<3?keys[i+1]:0;c->esp+=8;}
void f_00465930(Cpu*c){if(arg(c,0)!=0x5CEA9D46)fail("class");c->eax=handle(arg(c,1));c->esp+=4;}
void f_00469870(Cpu*c){c->esp+=4;}
void f_00678410(Cpu*c){(void)c;fail("missing layout or template");}
void f_0060BA70(Cpu*c){if(arg(c,0)!=12||arg(c,1))fail("allocation");c->eax=allocation;allocation+=12;c->esp+=12;}
/* RETAINED_ENUMERATION */
int main(int argc,char**argv){
 if(argc!=3)return 2;FILE*f=fopen(argv[1],"rb");if(!f)return 2;
 G=calloc(1,0x100000);if(!G)return 2;
 if(fread(&rows,4,1,f)!=1||rows>4000||fread(keys,4,4,f)!=4||fread(G+0x10000,12,rows,f)!=rows)return 2;
 fclose(f);int broken=atoi(argv[2]);
 if(broken)for(unsigned i=0;i<4;i++)M32(handle(keys[i])+8)=0xFFFFFFFF; // Omitted override inherits 1.
 uint32_t list=0x8000;M32(list)=list;M32(list+4)=list;
 Cpu c={0};c.ecx=0xA000;c.esp=0x90000;c.fs_base=0x7000;M32(c.esp+4)=list;M32(c.esp+8)=0x874B96D6;
 f_00631430(&c);
 unsigned count=M32(list+8);if(count!=(broken?0:4))fail("enumerated count");
 unsigned walked=0;for(uint32_t p=M32(list);p!=list;p=M32(p)){
  unsigned i=0;while(i<4&&keys[i]!=M32(p+8))++i;if(i==4||++walked>4)fail("list key");
 }
 if(walked!=count)fail("list length");
 printf("NATIVE PREMISES PASS enumerated=%u/4 inherited-template-control=%d\n",count,broken);
 free(G);return 0;
}
'''


def native_premises(source, core, folder):
    import hashlib
    text = (HERE.parents[1]/'recomp/out/carbon-base/NFSC_26.c').read_text()
    fragments = []
    for address, digest in ENUM_NATIVE.items():
        match = re.search(r'void f_'+address+r'\(Cpu [^)]*\)\s*\{', text)
        assert match
        fragment = text[match.start():text.index('\n}', match.end())+2]
        assert hashlib.sha256(fragment.encode()).hexdigest() == digest
        fragments.append(fragment)
    houses = {k for k, (t, _) in place_triggers(source).items() if t == 0x326427BB}
    keys = [c.key for c in core.collections.values() if c.parent == 0x874B96D6 and
            struct.unpack('<I', field_value(core, c, 0xD5DFD829))[0] in houses]
    assert len(keys) == 4, 'enumeration fixture houses'
    # Supply the vault lookup API with raw keys, ancestry and explicit Template
    # values. The two retained functions do the filtering and list insertion.
    data = struct.pack('<5I', len(core.collections), *keys)
    for c in core.collections.values():
        try:
            value = struct.unpack('<I', field_value(core, c, 0x3E9156CA))[0]
        except AssertionError:
            value = 0xFFFFFFFF
        data += struct.pack('<3I', c.key, c.parent, value)
    fixture = folder/'premises.bin'; fixture.write_bytes(data)
    path = folder/'premises.c'
    path.write_text(ENUM_HARNESS.replace('/* RETAINED_ENUMERATION */', '\n'.join(fragments)))
    binary = folder/'premises'
    build = subprocess.run(['clang', '-O1', '-g', '-fsanitize=address,undefined',
                            '-I', str(HERE.parents[1]/'runtime'), '-I', str(HERE.parents[1]/'recomp'),
                            str(path), '-o', str(binary)], capture_output=True, text=True)
    assert build.returncode == 0, build.stderr[-2000:]
    for broken in (0, 1):
        run = subprocess.run([str(binary), str(fixture), str(broken)],
                             capture_output=True, text=True, timeout=10)
        assert run.returncode == 0, run.stdout+run.stderr
        print(run.stdout.strip())


@unittest.skipUnless(ASSETS, 'private gameplay inputs absent')
class GameplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source_bytes, cls.target_bytes = MW.read_bytes(), CARBON.read_bytes()
        cls.source, cls.target = g.Pack(cls.source_bytes), g.Pack(cls.target_bytes)
        cls.result, cls.report = g.convert(cls.source_bytes, cls.target_bytes)
        cls.output = g.Pack(cls.result)

    def test_trigger_values_and_native_layout(self):
        check_records(self.source.core(False), self.output.core(True))
        self.assertEqual(self.report['records'], 54)
        # The native 004682B0 reader uses +1A directly, independent of the
        # production parser's padded-count rule.
        out = self.output.core(True)
        added = out.exports[len(self.target.core(True).exports):]
        for _, _, size, off in added:
            ntypes, padded = struct.unpack_from('<HH', out.raw, off+24)
            nfields = struct.unpack_from('<I', out.raw, off+20)[0]
            self.assertEqual(padded, (ntypes+1) & ~1)
            self.assertEqual((off+32+padded*4) % 8, 0)
            self.assertEqual(size, 32+padded*4+nfields*12)

    def test_retained_native_name_consumer(self):
        with tempfile.TemporaryDirectory() as root:
            native_names(self.output.core(True), Path(root))

    def test_retained_native_premises_enumeration(self):
        with tempfile.TemporaryDirectory() as root:
            native_premises(self.source.core(False), self.output.core(True), Path(root))

    def test_preservation(self):
        old, new = self.target.core(True), self.output.core(True)
        self.assertEqual(new.exports[:len(old.exports)], old.exports)
        # Exactly four native pointer targets change: both arrays on both
        # activities. Their headers/data and every other relocation stay put.
        changed = []
        for before, after in zip(old.pointer_rows, new.pointer_rows):
            self.assertEqual(before[:3], after[:3])
            if before != after:
                self.assertEqual(before[1:3], (3, 1))
                changed.append(before[0])
        expected = []
        for activity in (0x3103659B, 0x10874E8D):
            c = old.collections[activity]
            _, _, _, off = next(r for r in old.exports if r[0] == c.export)
            padded = struct.unpack_from('<H', old.raw, off+26)[0]
            expected.extend(off+32+padded*4+12*i+4 for i, f in enumerate(c.fields)
                            if f[0] in (0x64893DA8, 0x916E0E78))
        self.assertEqual(set(changed), set(expected))
        self.assertEqual(len(changed), 4)
        self.assertEqual(new.binary[:len(old.binary)], old.binary)
        off, size = old.chunks[0x4461744E]
        self.assertEqual(new.raw[off+8:off+size], old.raw[off+8:off+size])
        for name in self.target.vaults:
            if name != 'gpcore':
                self.assertEqual(self.output.vaults[name], self.target.vaults[name])
        self.assertEqual(MW.read_bytes(), self.source_bytes)
        self.assertEqual(CARBON.read_bytes(), self.target_bytes)

    def test_place_premises_and_template_control(self):
        source, target, out = self.source.core(False), self.target.core(True), self.output.core(True)
        expected = place_triggers(source)
        premises = [c for c in out.collections.values() if c.key not in target.collections
                    and c.parent in (0x874B96D6, 0xB7F31748)]
        self.assertEqual(len(premises), 15, 'place premises')
        self.assertTrue(all(c.key > max(c.key for c in target.collections.values()
                                       if c.parent in (0x874B96D6, 0xB7F31748)) for c in premises))
        by_trigger = {struct.unpack('<I', field_value(out, c, 0xD5DFD829))[0]: c for c in premises}
        self.assertEqual(set(by_trigger), set(expected))
        order = []
        for c in sorted(premises, key=lambda c: c.key):
            fields = {f[0]: f for f in c.fields}
            self.assertNotIn(0x70D72E20, fields)
            self.assertEqual(fields[0x3E9156CA][1:], (0x064BEC37, 0x40, bytes(4)))
            trigger = struct.unpack('<I', fields[0xD5DFD829][3])[0]
            template = expected[trigger][0]
            order.append(template)
            self.assertEqual(c.parent, 0xB7F31748 if template == 0x73049919 else 0x874B96D6)
        self.assertEqual(order, [0x326427BB]*4+[0x4698966B]*8+[0x73049919]*3)
        # Removing the override reproduces the withdrawn experiment: the
        # parent chain reaches baseelement's Template=1 (0061F600).
        def inherited_template(c, broken=False):
            for key, _, _, payload in c.fields:
                if key == 0x3E9156CA and not broken:
                    return struct.unpack('<I', payload)[0]
            return inherited_template(out.collections[c.parent]) if c.parent else 0
        houses = [by_trigger[k] for k, (t, _) in expected.items() if t == 0x326427BB]
        self.assertEqual(sum(inherited_template(c) == 0 for c in houses), 4)
        self.assertEqual(sum(inherited_template(c, True) == 0 for c in houses), 0)
        print('PLACE PREMISES PASS houses=4/4 shops=8/8 lots=3/3 inherited-template-control=0/4')

    def test_activity_memberships_and_no_append_control(self):
        source, target, out = self.source.core(False), self.target.core(True), self.output.core(True)
        check_memberships(source, target, out)
        with self.assertRaisesRegex(AssertionError, 'membership count'):
            check_memberships(source, target, target)
        for activity in (0x3103659B, 0x10874E8D):
            self.assertEqual([len(member_keys(target, activity, f)) for f in (0x64893DA8, 0x916E0E78)], [4, 4])
        print('PLACE MEMBERSHIP PASS safehouse=16/16 carlot=7/7 no-append-control=4/4,4/4')

    def test_exit_markers_and_omitted_control(self):
        source, target, out = self.source.core(False), self.target.core(True), self.output.core(True)
        refs, resolved = marker_resolution(source, out)
        self.assertEqual(len(resolved), 15, 'exit marker resolutions')
        self.assertEqual(len(marker_resolution(source, target)[1]), 0)
        for key in refs:
            before, after = source.collections[key], out.collections[key]
            self.assertEqual((after.key, after.export, after.cls, after.parent, after.name, after.layout),
                             (before.key, before.export, before.cls, 0xA7BCCF63, before.name, before.layout))
            old = {f[0]: f for f in before.fields}
            new = {f[0]: f for f in after.fields}
            self.assertEqual(set(old), set(new))
            self.assertIn(0x5A6A57C6, old)  # heading
            for field, (_, typ, flags, payload) in old.items():
                if field == 0x9F743A0E:
                    x, y, z = struct.unpack('<3f', payload)
                    payload = struct.pack('<3f', x+8192, y, z)
                self.assertEqual(new[field][1:], (typ, 0x40 if flags == 0x20 else flags, payload))
        print('PLACE MARKER PASS resolved=15/15 omitted-control=0/15 positions+headings=15/15')

    def test_place_subtypes_and_shop_flow(self):
        source, out = self.source.core(False), self.output.core(True)
        places = place_triggers(source)
        self.assertEqual(len(places), 15)
        for key, (template, before) in places.items():
            after = out.collections[key]
            self.assertEqual(field_value(out, after, 0x9995178A), b'muscle\0', 'garage subtype')
            self.assertEqual(after.parent, before.parent)
            if template == 0x4698966B:
                self.assertEqual(field_value(out, after, 0xF3EA3201), b'safehouse\0')
        print('PLACE SUBTYPE PASS muscle=15/15 customshop-ancestry+safehouse-flow=8/8')

    def test_overlay_off_reads_retail_bytes(self):
        # Exercise the existing native overlay path with the full retail pack,
        # not a Python simulation of whether the switch is enabled.
        harness = r'''
#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <unistd.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <errno.h>
static const char *game_dir;
static int file_flags(uint32_t access,uint32_t disp){(void)access;(void)disp;return O_RDONLY;}
static void file_error(void){}
/* This fixture opens only GLOBAL/TRACKS; sound routing is exercised by the
 * production import-table test in recomp/private_files_test.py. */
int carbon_gin_path(char *path,size_t n,uint32_t access,uint32_t disp){
 (void)path;(void)n;(void)access;(void)disp;return 0;
}
/* EXISTING_OVERLAY */
int main(int argc,char**argv){
 if(argc!=3)return 2;game_dir=argv[1];char path[4096];
 if(snprintf(path,sizeof path,"%s",argv[2])>=(int)sizeof path)return 2;
 private_track_overlay_init();
 if(private_track_overlay_path(path,sizeof path,0x80000000u,3)<0)return 2;
 FILE*f=fopen(path,"rb");if(!f)return 2;char buf[8192];size_t n;
 while((n=fread(buf,1,sizeof buf,f)))if(fwrite(buf,1,n,stdout)!=n)return 2;
 int failed=ferror(f);fclose(f);return failed?2:0;
}
'''
        with tempfile.TemporaryDirectory() as root:
            folder = Path(root)
            overlay = folder/'overlay'
            for name, data in {'TRACKS/L2RA.BUN': b'index', 'TRACKS/STREAML2RA.BUN': b'stream',
                               'GLOBAL/GAMEPLAY.BIN': self.result,
                               'GLOBAL/GAMEPLAY.LZC': g.startup_companion(self.result)}.items():
                path = overlay/name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            path = folder/'overlay.c'
            native = (HERE.parents[1]/'recomp/private_runtime/file_overlay.h').read_text()
            path.write_text(harness.replace('/* EXISTING_OVERLAY */', native))
            binary = folder/'overlay_check'
            build = subprocess.run(['clang', '-O1', '-fsanitize=address,undefined', str(path), '-o', str(binary)],
                                   capture_output=True, text=True)
            self.assertEqual(build.returncode, 0, build.stderr[-2000:])
            env = dict(os.environ)
            env.pop('NFS_CARBON_TRACK_OVERLAY', None)
            for pack, enabled in ((CARBON, self.result),
                                  (CARBON.with_suffix('.lzc'), g.startup_companion(self.result))):
                retail = pack.read_bytes()
                for setting in (None, '', str(overlay)):
                    child = dict(env)
                    if setting is not None:
                        child['NFS_CARBON_TRACK_OVERLAY'] = setting
                    run = subprocess.run([str(binary), str(CARBON.parent.parent), str(pack)],
                                         capture_output=True, env=child, timeout=10)
                    self.assertEqual(run.returncode, 0, run.stderr[-2000:])
                    expected = enabled if setting else retail
                    self.assertTrue(run.stdout == expected, 'native overlay bytes differ')
                self.assertEqual(pack.read_bytes(), retail)
                self.assertNotEqual(retail, enabled)
                print(f'OVERLAY OFF PASS {pack.name} retail-bytes={len(retail)} unset+empty identical; enabled differs')

    def test_unshifted_control_fails(self):
        core = self.output.core(True)
        for _, c in core.triggers():
            if c.key in self.source.core(False).collections:
                for i, (key, typ, flags, payload) in enumerate(c.fields):
                    if key == 0x9F743A0E:
                        x, y, z = struct.unpack('<3f', payload)
                        c.fields[i] = (key, typ, flags, struct.pack('<3f', x-8192, y, z))
        with self.assertRaisesRegex(AssertionError, 'position shift missing'):
            check_records(self.source.core(False), core)
        source_positions = [struct.unpack('<f', f[3][:4])[0] for _, c in self.source.core(False).triggers()
                            for f in c.fields if f[0] == 0x9F743A0E]
        self.assertEqual(sum(x > 7000 for x in source_positions), 0)

    def test_collection_key_clash(self):
        dst = self.target.core(True)
        selected = self.source.core(False).triggers()[0][1]
        raw = bytearray(dst.raw)
        off = dst.exports[0][3]
        struct.pack_into('<II', raw, off, selected.key, selected.cls)
        collision = self.target.replace_core(dst.binary, raw)
        with self.assertRaisesRegex(FormatError, 'collection-key clash'):
            g.convert(self.source_bytes, collision)

    def test_export_key_clash(self):
        dst = self.target.core(True)
        selected = self.source.core(False).triggers()[0][1]
        raw = bytearray(dst.raw)
        off, _ = dst.chunks[0x4578704E]
        struct.pack_into('<I', raw, off+12, selected.export)
        with self.assertRaisesRegex(FormatError, 'collection-key clash'):
            g.convert(self.source_bytes, self.target.replace_core(dst.binary, raw))

    def test_cli_uses_loaded_file_and_rejects_backup(self):
        with tempfile.TemporaryDirectory() as root:
            out = Path(root)/'GLOBAL/GAMEPLAY.BIN'
            run = subprocess.run([sys.executable, '-I', str(HERE/'gameplay.py'), '--out', str(out)],
                                 capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(out.read_bytes(), self.result)
            companion = out.with_suffix('.LZC').read_bytes()
            self.assertEqual(companion[:8], b'RAWW\x01\x10\0\0')
            self.assertEqual(struct.unpack_from('<II', companion, 8), (len(self.result), len(companion)))
            self.assertEqual(companion[16:], self.result)
            run = subprocess.run([sys.executable, '-I', str(HERE/'gameplay.py'), '--out', str(out),
                                  '--carbon', str(CARBON.with_suffix('.bak'))], capture_output=True, text=True)
            self.assertNotEqual(run.returncode, 0)
            self.assertIn('loaded gameplay.bin', run.stderr)


    def test_cli_takes_the_built_worlds_shift(self):
        # A coast world (physics 5056, 0, -1728) needs render (-1728, -5056); the old CLI wrote its
        # fixed (8192, 0) into any world unless the shift was passed by hand.
        import json
        with tempfile.TemporaryDirectory() as root:
            world = Path(root)
            (world/'proof.json').write_text(json.dumps({'roads': {'shift_physics_xyz': [5056., 0., -1728.]}}))
            out = world/'GLOBAL/GAMEPLAY.BIN'
            cli = [sys.executable, '-I', str(HERE/'gameplay.py'), '--out', str(out)]
            run = subprocess.run(cli, capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(json.loads(run.stdout)['position_shift'], [-1728., -5056., 0])
            self.assertEqual(out.read_bytes(), g.convert(self.source_bytes, self.target_bytes, (-1728., -5056.))[0])
            run = subprocess.run(cli + ['--shift', '8192,0'], capture_output=True, text=True)
            self.assertNotEqual(run.returncode, 0)
            self.assertIn('differs from the world proof', run.stderr)
            # The Setup world's (0, 8192) gives the default render shift.
            (world/'proof.json').write_text(json.dumps({'roads': {'shift_physics_xyz': [0., 0., 8192.]}}))
            self.assertEqual(g.world_shift(out), g.SHIFT)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--on-log', type=Path)
    ap.add_argument('--off-log', type=Path)
    args, remaining = ap.parse_known_args()
    if args.on_log or args.off_log:
        assert args.on_log and args.off_log
        print(check_live(args.on_log, args.off_log))
    else:
        suite = unittest.main(argv=[sys.argv[0], *remaining], exit=False)
        sys.exit(0 if suite.result.wasSuccessful() and ASSETS else 3 if suite.result.wasSuccessful() else 1)
