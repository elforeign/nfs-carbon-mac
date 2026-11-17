"""Native ABI: ten serialized collections accepted; raw-copy control 0/10.

MASS +16 / 8-byte StringKey pass 10/10; source +20 / 16-byte copies
fail 10/10. Existing collections and their complete BIN buffer are unchanged.
Synthetic StringKey checks always run. Retail fixtures exit 3 when absent.
"""
from pathlib import Path
import struct
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import prop_attributes as a
from wheel_attrib import Wheels
from formats import FormatError

NAMES = ('mediummetalpost', 'largemetalpost', 'golfcart', 'glass', 'lightwoodenpost',
         'propanetank', 'sailboat', 'hugemetalbreakable', 'wood', 'mediumwoodenpost')
ASSETS = all((root.parent/'GLOBAL/attributes.bin').is_file() for root in (a.DEFAULT_MW, a.DEFAULT_CARBON))


def native_values(raw, key):
    """Independent native header/layout decoder; no Database.value calls."""
    pack = a.Pack(raw)
    _, binary, vault = pack.vaults['db']
    chunks, pos = {}, 0
    while pos < len(vault):
        tag, size = struct.unpack_from('<4sI', vault, pos)
        assert size >= 8 and pos+size <= len(vault)
        chunks[tag] = (pos, size)
        pos += size
    start, size = chunks[b'NpxE']
    count = struct.unpack_from('<I', vault, start+8)[0]
    collections = [row for row in struct.iter_unpack('<4I', vault[start+12:start+12+16*count])
                   if row[1] == 0x8e112eb7 and struct.unpack_from('<II', vault, row[3]) == (key, 0xce70d7db)]
    assert len(collections) == 1
    _, _, size, off = collections[0]
    nt, padded = struct.unpack_from('<HH', vault, off+24)
    assert padded == (nt+1)//2*2 and 32+padded*4+12*struct.unpack_from('<I', vault, off+20)[0] <= size
    fixes, base = {}, 0
    start, size = chunks[b'NrtP']
    for at in range(start+8, start+size-11, 12):
        field, kind, dep, value = struct.unpack_from('<IHHI', vault, at)
        if not kind: break
        if kind == 2: base = dep
        elif kind == 3: fixes[base, field] = (dep, value)
    dep, layout = fixes[0, off+28]
    assert dep == 1
    mass = struct.unpack_from('<f', binary, layout+16)[0]
    sequence_hash, placeholder = struct.unpack_from('<II', binary, layout)
    assert placeholder == 0
    dep, text = fixes[1, layout+4]
    assert dep == 1
    sequence = binary[text:binary.index(b'\0', text)]
    assert a.hash32(sequence) == sequence_hash
    dep, text = fixes[1, layout+8]
    assert dep == 1
    name = binary[text:binary.index(b'\0', text)].decode('ascii')
    cost = struct.unpack_from('<I', binary, layout+24)[0]
    return mass, sequence_hash, name, cost


class Synthetic(unittest.TestCase):
    def test_stringkey_reduces_hash64_and_relocates_text(self):
        text = b'metalpost_seq\0'
        source = a.Value(struct.pack('<4I', 123, 456, a.hash32(text[:-1]), 0), strings=((12, text),))
        value = a.translated(source, (a.STRINGKEY, 0, 16, 1, 6, 3), (a.STRINGKEY, 0, 8, 1, 6, 2))
        self.assertEqual(value, a.Value(struct.pack('<II', a.hash32(text[:-1]), 0), strings=((4, text),)))
        with self.assertRaisesRegex(FormatError, 'hash/text'):
            a.translated(a.Value(bytes(16), strings=((12, text),)),
                         (a.STRINGKEY, 0, 16, 1, 6, 3), (a.STRINGKEY, 0, 8, 1, 6, 2))
        with self.assertRaisesRegex(FormatError, 'size'):
            a.translated(source, (a.STRINGKEY, 0, 16, 1, 6, 3), (a.STRINGKEY, 0, 16, 1, 6, 2))


@unittest.skipUnless(ASSETS, 'private attributes absent')
class Retail(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (a.DEFAULT_MW.parent/'GLOBAL/attributes.bin').read_bytes()
        cls.destination = (a.DEFAULT_CARBON.parent/'GLOBAL/attributes.bin').read_bytes()
        cls.output = a.convert(cls.source, cls.destination)
        cls.src, cls.dst, cls.got = a.Database(cls.source, False), a.Database(cls.destination, True), a.Database(cls.output, True)

    def test_native_layout_and_resolved_inheritance(self):
        source = Wheels(a.DEFAULT_MW.parent/'GLOBAL/attributes.bin', 'mw', 'smackable')
        for name in NAMES:
            key = a.hash32(name)
            self.assertIn(key, source.collections)
            self.assertNotIn(key, self.dst.collections)
            mass, seq, decoded_name, cost = native_values(self.output, key)
            self.assertEqual(mass, struct.unpack('<f', source.raw(key, 'MASS'))[0])
            vault, offset, _ = source.collections[key]
            dep, layout = vault.deref(0, offset+28)
            self.assertEqual(seq, struct.unpack_from('<I', vault.bufs[dep], layout+8)[0])
            self.assertEqual(decoded_name, name)
            self.assertEqual(cost, struct.unpack('<I', source.raw(key, 'COST_TO_STATE'))[0])
        # The medium post inherits its native rigid body reference and other fields.
        key = a.hash32('mediummetalpost')
        off, _, entries = self.src.collections[key]
        self.assertNotIn(0x7c90bb38, entries)
        self.assertIsNotNone(self.src.value(key, 0x7c90bb38))
        self.assertEqual(a.verify(self.source, self.destination, self.output)['added'], 10)

    def test_every_native_collection_and_buffer_stays_identical(self):
        self.assertEqual(len(self.got.collections), len(self.dst.collections)+10)
        for key, (off, size, _) in self.dst.collections.items():
            self.assertEqual(self.got.raw[off:off+size], self.dst.raw[off:off+size])
        self.assertEqual(self.got.binary[:len(self.dst.binary)], self.dst.binary)
        self.assertEqual(self.got.exports[:-10], self.dst.exports)
        self.assertEqual(self.got.pointer_rows[:len(self.dst.pointer_rows)], self.dst.pointer_rows)
        # All untouched vaults retain their original directory entries and buffers.
        before, after = a.Pack(self.destination), a.Pack(self.output)
        self.assertEqual({n:r for n,r in before.vaults.items() if n != 'db'},
                         {n:r for n,r in after.vaults.items() if n != 'db'})

    def test_raw_source_copies_fail_the_native_parser(self):
        _, _, _, _, vo = struct.unpack_from('<5I', self.output, self.got.pack.vaults['db'][0])
        rejected = 0
        for name in NAMES:
            key = a.hash32(name)
            so, ss, _ = self.src.collections[key]
            do, ds, _ = self.got.collections[key]
            self.assertLessEqual(ss, ds)
            broken = bytearray(self.output)
            broken[vo+do:vo+do+ds] = self.src.raw[so:so+ss]+bytes(ds-ss)
            with self.assertRaises(AssertionError): native_values(broken, key)
            with self.assertRaises(FormatError): a.Database(broken, True)
            rejected += 1
        self.assertEqual(rejected, 10)
        print('ATTRIBUTES ABI: native=10/10 raw-copy=0/10; MASS +16, StringKey 8 bytes')

    def test_wrong_mass_and_string_hash_fail_value_proof(self):
        key = a.hash32('mediummetalpost')
        off = self.got.collections[key][0]
        _, _, layout = self.got.fixups[0, off+28]
        entry = self.got.pack.vaults['db'][0]
        bo = struct.unpack_from('<I', self.output, entry+12)[0]
        for relative in (0, 16):
            broken = bytearray(self.output)
            struct.pack_into('<I', broken, bo+layout+relative, 0)
            with self.assertRaises(FormatError): a.verify(self.source, self.destination, broken)

    def test_source_inline_value_flag_is_rejected(self):
        key = a.hash32('mediummetalpost')
        at, _, flag = self.got.collections[key][2][0x360552da]
        self.assertEqual(flag, 0x40)
        entry = self.got.pack.vaults['db'][0]
        vo = struct.unpack_from('<I', self.output, entry+16)[0]
        broken = bytearray(self.output)
        broken[vo+at+10] = 0x20
        with self.assertRaisesRegex(FormatError, 'value pointer absent'):
            a.verify(self.source, self.destination, broken)

    def test_output_requires_generated_pair_and_never_overwrites(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with self.assertRaisesRegex(FormatError, 'combined pair'):
                a.write_overlay(a.DEFAULT_MW, a.DEFAULT_CARBON, root)
            (root/'TRACKS').mkdir()
            for name in ('L5RA.BUN', 'STREAML5RA.BUN'): (root/'TRACKS'/name).touch()
            self.assertEqual(a.write_overlay(a.DEFAULT_MW, a.DEFAULT_CARBON, root)['added'], 10)
            self.assertEqual((root/'GLOBAL/ATTRIBUTES.BIN').read_bytes(), self.output)
            with self.assertRaisesRegex(FormatError, 'already exists'):
                a.write_overlay(a.DEFAULT_MW, a.DEFAULT_CARBON, root)
            pair, external = root/'pair', root/'external'
            (pair/'TRACKS').mkdir(parents=True)
            external.mkdir()
            for name in ('L5RA.BUN', 'STREAML5RA.BUN'): (pair/'TRACKS'/name).touch()
            (pair/'GLOBAL').symlink_to(external, target_is_directory=True)
            with self.assertRaisesRegex(FormatError, 'escapes combined'):
                a.write_overlay(a.DEFAULT_MW, a.DEFAULT_CARBON, pair)
            self.assertFalse((external/'ATTRIBUTES.BIN').exists())
            with self.assertRaisesRegex(FormatError, 'source installation'):
                a.write_overlay(a.DEFAULT_MW, a.DEFAULT_CARBON, a.DEFAULT_CARBON.parent)


if __name__ == '__main__':
    result = unittest.main(exit=False).result
    sys.exit(1 if not result.wasSuccessful() else 0 if ASSETS else 3)
