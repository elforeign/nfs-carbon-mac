"""District binding: identity 0/11 -> bound 11/11; 8/8 vault names decoded.

Failure controls: dropped downtown row and industrial target each accept
0/1 versus intact 1/1; type-11/marker/barrier key collisions each accept
0/1 versus intact 1/1. Malformed vaults accept 0/1 versus intact 1/1.
Names and hash pins are independent of the production mapping table.
Synthetic tests run bare; missing private assets then exit 3.
"""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(HERE))
import districts as d
from formats import FormatError
from test_zones import fixture, index_of, polygon, replace_polygons, replace_part

NAMES = {'default', 'santafe', 'drag', 'exotic', 'tuner', 'casino', 'highway', 'muscle'}
ASSETS = (d.DEFAULT_CARBON.parent / 'GLOBAL/attributes.bin').is_file() and all(
    (d.DEFAULT_MW / name).is_file() for name in ('L2RA.BUN', 'STREAML2RA.BUN'))


def vault_fixture(names=('muscle', 'highway'), *, foreign=('industrial',)):
    """Small VPAK with real export/layout pointers and an unrelated class."""
    binary = bytearray(b'\0')
    data, exports, pointers = bytearray(), bytearray(), bytearray()
    for i, name in enumerate((*names, *foreign)):
        offset = 8 + len(data)
        collection = bytearray(36)
        struct.pack_into('<II', collection, 0, 100 + i, 0x20d08342 if i < len(names) else 99)
        data += collection
        exports += struct.pack('<4I', 200 + i, 0x8e112eb7, 36, offset)
        pointers += struct.pack('<IHHI', offset + 28, 3, 0, offset + 32)
        pointers += struct.pack('<IHHI', offset + 32, 3, 1, len(binary))
        binary += name.encode() + b'\0'
    def chunk(kind, payload):
        return struct.pack('<4sI', kind, 8 + len(payload)) + payload
    vault = (chunk(b'NtaD', data)
             + chunk(b'NpxE', struct.pack('<I', len(names) + len(foreign)) + exports)
             + chunk(b'NrtP', pointers + bytes(12)))
    return (b'VPAK' + struct.pack('<III', 1, 36, 3)
            + struct.pack('<5I', 0, len(binary), len(vault), 39, 39 + len(binary))
            + b'db\0' + binary + vault)


def source_fixture(*names):
    return index_of(replace_polygons(fixture(), b''.join(polygon(9, d.bstring_hash(n)) for n in names)))


class SyntheticTests(unittest.TestCase):
    def test_hash_pins(self):
        for name, value in (('muscle', 0xB9CE05C8), ('highway', 0x55D76E10),
                            ('downtown', 0x5358FCBF), ('tuner', 0x061FFB8D),
                            ('exotic', 0xA75920AB), ('santafe', 0x9273A861)):
            self.assertEqual(d.bstring_hash(name), value)

    def test_collection_layouts_not_raw_names_or_export_keys(self):
        with tempfile.TemporaryDirectory(prefix='district-vault-') as directory:
            root = Path(directory)
            (root / 'GLOBAL').mkdir()
            path = root / 'GLOBAL/attributes.bin'
            raw = vault_fixture()
            path.write_bytes(raw)
            self.assertEqual(d.traffic_patterns(root / 'TRACKS'),
                             {0xB9CE05C8: 'muscle', 0x55D76E10: 'highway'})
            self.assertIn(b'\0industrial\0', raw)
            for label, broken in (('truncated', raw[:-1]), ('signature', b'FAIL' + raw[4:]),
                                  ('no traffic class', vault_fixture(names=())),
                                  ('duplicate name', vault_fixture(names=('muscle', 'muscle'))),
                                  ('missing pointer', raw.replace(struct.pack('<IHHI', 36, 3, 0, 40),
                                                                  struct.pack('<IHHI', 36, 1, 0, 40), 1))):
                with self.subTest(control=label):
                    path.write_bytes(broken)
                    with self.assertRaises((FormatError, ValueError)):
                        d.traffic_patterns(root / 'TRACKS')

    @mock.patch.object(d, 'traffic_patterns', return_value={d.bstring_hash(n): n for n in NAMES})
    def test_mapping_fails_closed_and_only_type_nine_is_safe(self, _patterns):
        source = source_fixture('downtown', 'collegehighway')
        self.assertEqual(d.key_map(source)[0x5358FCBF], 0xB9CE05C8)
        missing = dict(d.ROCKPORT_TO_CARBON)
        del missing['downtown']
        with mock.patch.dict(d.ROCKPORT_TO_CARBON, missing, clear=True):
            with self.assertRaisesRegex(FormatError, 'unmapped type-9'):
                d.key_map(source)
        with mock.patch.dict(d.ROCKPORT_TO_CARBON, downtown='industrial'):
            with self.assertRaisesRegex(FormatError, 'target traffic pattern absent: industrial'):
                d.key_map(source)
        with self.assertRaisesRegex(FormatError, 'unmapped type-9'):
            d.key_map(source_fixture('unknown'))
        parts = list(source.parts)
        table = d.zones.read(parts)
        source11 = index_of(replace_polygons(parts, b''.join(z.encode() for z in table.zones)
                                           + polygon(11, 0x5358FCBF)))
        with self.assertRaisesRegex(FormatError, 'outside type-9: type-11'):
            d.key_map(source11)
        for kind, offset, message in ((d.zones.MARKERS, 8 + 8, 'marker'),
                                       (d.zones.BARRIERS, 20, 'barrier')):
            raw = bytearray(next(c.payload for c in parts if c.kind == kind))
            struct.pack_into('<I', raw, offset, 0x5358FCBF)
            with self.assertRaisesRegex(FormatError, 'outside type-9: ' + message):
                d.key_map(index_of(replace_part(parts, kind, raw)))

    def test_missing_attributes(self):
        with tempfile.TemporaryDirectory(prefix='district-missing-') as directory:
            with self.assertRaises(FileNotFoundError):
                d.traffic_patterns(Path(directory) / 'TRACKS')


@unittest.skipUnless(ASSETS, 'private district assets absent')
class ArchiveTests(unittest.TestCase):
    def test_eight_names_and_all_targets_independently_exist(self):
        patterns = d.traffic_patterns()
        self.assertEqual(set(patterns.values()), NAMES)
        attributes = (d.DEFAULT_CARBON.parent / 'GLOBAL/attributes.bin').read_bytes()
        for name in ('muscle', 'highway', 'tuner', 'exotic', 'santafe'):
            self.assertIn(b'\0' + name.encode() + b'\0', attributes)
        source, _, _ = d.load_index(d.DEFAULT_MW, 'L2RA')
        mapping = d.key_map(source)
        before = d.zones.read(d.zones.convert(source))
        after = d.zones.read(d.zones.convert(source, key_map=mapping))
        old = [z for z in before.zones if z.kind == 9]
        new = [z for z in after.zones if z.kind == 9]
        self.assertEqual((len(old), sum(z.key in patterns for z in old)), (11, 0))
        self.assertEqual((len(new), sum(z.key in patterns for z in new)), (11, 11))
        self.assertEqual(before.markers, after.markers)
        self.assertEqual(before.barriers, after.barriers)
        self.assertEqual([z.encode() for z in before.zones if z.kind != 9],
                         [z.encode() for z in after.zones if z.kind != 9])
        with redirect_stdout(io.StringIO()) as out:
            self.assertEqual(d.main(['--list']), 0)
        rows = json.loads(out.getvalue())
        self.assertEqual(len(rows), 7)
        self.assertEqual({row['target'] for row in rows}, {'muscle', 'highway', 'tuner', 'exotic', 'santafe'})
        print('districts: baseline 0/11 -> bound 11/11; 8/8 vault names, 7/7 mapping rows')


if __name__ == '__main__':
    result = unittest.main(exit=False, verbosity=2).result
    raise SystemExit(1 if not result.wasSuccessful() else 0 if ASSETS else 3)
