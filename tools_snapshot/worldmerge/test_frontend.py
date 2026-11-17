"""Offline screen proof; rendering requires a career game check.

Retail/no-clone control: 576 objects, 0/15 added names. Converted: 591,
15/15 names and distinct IDs, 174464 -> 177224 bytes, still 58 resources.
The design's 177276-byte experiment included a 52-byte new shop resource;
this variant retains native art. All 235 other BUN chunks are byte-identical.
The pre-feature twelve-path overlay control is exercised by private_files_test.py.
Exit 3 without private inputs. No game, image archive or GPU is run.
"""
from pathlib import Path
import struct
import sys
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import frontend as f
from formats import FormatError, chunks, u32

ROOT = f.DEFAULT_CARBON.parent/'GLOBAL'
ASSETS = all((ROOT/name).is_file() for name in ('GLOBALB.BUN', 'GlobalB.lzc'))


def check_screen(before, after):
    # Derive required names independently of the converter's name table.
    names = [*(f'SAFEHOUSEINDICATOR_{i}' for i in range(4, 16)),
             *(f'CAR_LOT_{i}' for i in range(5, 8))]
    old = f.objects(before)[2]
    rows = f.objects(after)[2]
    assert len(rows) == 591, f'object count {len(rows)}, expected 591'
    assert len(after) == 177224
    assert rows[:576] == old
    ids = [u32(row, 0x24) for row in rows]
    assert len(set(ids)) == 591, 'duplicate object ID'
    assert {u32(row, 0x1c) for row in rows[-15:]} == {f.name_hash(n) for n in names}
    for name, row in zip(names, rows[-15:]):
        sibling = 'CAR_LOT_1' if name.startswith('CAR_LOT') else 'SAFEHOUSEINDICATOR_0'
        template = next(r for r in old if u32(r, 0x1c) == f.name_hash(sibling))
        assert u32(row, 0x1c) == u32(row, 0x28) == f.name_hash(name)
        assert u32(row, 0x24) not in {u32(r, 0x24) for r in old}
        restored = bytearray(row)
        for offset in (0x1c, 0x24, 0x28):
            restored[offset:offset+4] = template[offset:offset+4]
        assert restored == template, 'parent, flags, resource, state or script changed'
    # Only root/object container sizes and appended objects may change.
    start, stop, _ = f.objects(before)
    normalized = bytearray(after[:stop] + after[stop+15*184:])
    for offset in (4, start+4):
        normalized[offset:offset+4] = before[offset:offset+4]
    assert normalized == before
    resource, end = f.one(f.records(after, 8), b'Res\xcc')
    rq, _ = f.one(f.records(after, resource+8, end), b'RsRq')
    assert u32(after, rq+8) == 58
    return rows[-15:]


class FramingTests(unittest.TestCase):
    def test_bounded_records(self):
        for raw in (b'x', b'ObjD'+struct.pack('<I', 184)+b'x'):
            with self.assertRaises(FormatError):
                f.records(raw)
        self.assertEqual(f.name_hash('SAFEHOUSEINDICATOR_0'), 0x3750c9ee)
        self.assertEqual(f.name_hash('CAR_LOT_1'), 0x008ba2d3)


@unittest.skipUnless(ASSETS, 'private frontend pair absent')
class RetailTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.binary = (ROOT/'GLOBALB.BUN').read_bytes()
        cls.companion = (ROOT/'GlobalB.lzc').read_bytes()
        cls.index, cls.before = f.worldmap(cls.binary)
        cls.converted, cls.startup = f.convert(cls.binary, cls.companion)

    def test_baseline_and_no_clone_control(self):
        parts = chunks(self.binary)
        self.assertEqual(parts[self.index].offset, 0xb766e0)
        self.assertEqual(parts[self.index].kind, 0x30210)
        self.assertEqual(f.xt.jdlz(self.companion), self.binary)
        self.assertEqual(len(self.before), 174464)
        rows = f.objects(self.before)[2]
        self.assertEqual(len(rows), 576)
        hashes = {u32(row, 0x1c) for row in rows}
        self.assertTrue(all(f.name_hash(f'SAFEHOUSEINDICATOR_{i}') in hashes for i in range(4)))
        self.assertTrue(all(f.name_hash(f'CAR_LOT_{i}') in hashes for i in range(1, 5)))
        self.assertFalse(any(f.name_hash(f'SHOP_{i}') in hashes for i in range(16)))
        with self.assertRaisesRegex(AssertionError, 'object count 576'):
            check_screen(self.before, self.before)
        print('NO CLONE rejected: objects=576 added=0/15; native houses=4 lots=4 shops=0')

    def test_clones_and_paired_repack(self):
        index, after = f.worldmap(self.converted)
        self.assertEqual(index, self.index)
        rows = check_screen(self.before, after)
        self.assertEqual(f.xt.jdlz(self.startup), self.converted)
        self.assertEqual(f.worldmap(f.xt.jdlz(self.startup))[1], after)
        old, new = chunks(self.binary), chunks(self.converted)
        self.assertEqual(len(old), len(new))
        untouched = 0
        for i, (a, b) in enumerate(zip(old, new)):
            self.assertEqual(a.offset % 128, b.offset % 128)
            if i != index:
                self.assertEqual(a.encode(), b.encode())
                untouched += 1
        self.assertEqual(untouched, 235)
        self.assertEqual(new[index].payload[:4], old[index].payload[:4])
        f.native_jdlz_extent(new[index].payload[4:])
        for name, row in zip(f.NAMES, rows):
            print(f'{name} ID={u32(row, 0x24):08X}')
        print(f'FRONTEND PASS: objects=591 added=15/15 resources=58 untouched_chunks={untouched} FNG=177224')

    def test_broken_identity_and_state_rejected(self):
        after = bytearray(f.clone_screen(self.before))
        _, stop, _ = f.objects(after)
        last = stop-184
        for offset, value, message in ((0x24, u32(self.before, 0x6ae4+0x24), 'duplicate'),
                                       (0x38, 0, 'parent'), (0x30, 58, 'parent')):
            broken = bytearray(after)
            struct.pack_into('<I', broken, last+offset, value)
            with self.assertRaisesRegex(AssertionError, message):
                check_screen(self.before, broken)

    def test_reject_mismatched_pair_and_duplicate_application(self):
        with self.assertRaisesRegex(FormatError, 'pair differs'):
            f.convert(self.binary+b'x', self.companion)
        with self.assertRaisesRegex(FormatError, 'retail world map'):
            f.clone_screen(f.worldmap(self.converted)[1])


if __name__ == '__main__':
    result = unittest.main(exit=False)
    sys.exit(1 if not result.result.wasSuccessful() else 0 if ASSETS else 3)
