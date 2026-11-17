"""Closure: baseline 0/56 classified -> 56/56; six real shared textures recovered.

Models 19269/19293 unchanged; textures 3080/3112 -> 3086/3112. Stored first
bindings at risk for these 32 keys: 25 -> 10; recoverable classes: 15 -> 0.
Broken controls (intact 1/1 accepted each): shared provider removed 0/1,
false absence while provider exists 0/1, synthetic first-slot miss 0/1.
Independent image check: five DXT payloads exact; P8's seven authored mips
compare to the source palette within each BC3 block's quantization bound.
Synthetic checks run first; absent private archives exit 3. No game launches.
"""
from collections import Counter
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
import struct
import sys
import tempfile
from types import SimpleNamespace
import unittest

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(HERE))
import closure as c
import rockport_world as w
from formats import Chunk, FormatError, Section, chunks, encode_chunks
from test_texanim import reference_inventory, envelopes, single, unpad
from validate import validate_resources

ASSETS = all((w.DEFAULT_MW / name).is_file() for name in ('L2RA.BUN', 'STREAML2RA.BUN'))
SHARED = {0x1b049702, 0x3394fe62, 0x4a31e2a3, 0x7b220ddf, 0x7e16a782, 0x8c58916b}


def section(number, size):
    raw = bytearray(92)
    struct.pack_into('<h', raw, 8, number)
    return w.record(Section(bytes(raw)), 0, size)


def provider(key=0x12345678, *, paletted=False):
    info = bytearray(124)
    struct.pack_into('<I', info, 0, 5)
    info[4:12] = b'fixture\0'
    info[32:44] = b'fixture.tpk\0'
    struct.pack_into('<I', info, 96, 7)
    r, pl = bytearray(124), bytearray(32)
    r[12:20] = b'fixture\0'
    struct.pack_into('<I', r, 36, key)
    struct.pack_into('<HH', r, 68, 8, 8)
    r[72:74] = bytes((3, 3))
    r[78] = 4 if paletted else 1
    if paletted:
        struct.pack_into('<I', pl, 20, 41)
        pixels = bytes((7,)) * (64 + 16 + 4 + 1)
        palette = b''.join(bytes((255, 255, 255, i)) for i in range(256))
        struct.pack_into('<III', r, 56, len(pixels), 1024, 64)
        r[74] = 8
    else:
        pl[20:24] = b'DXT1'
        pixels, palette = bytes(32), b''
        struct.pack_into('<III', r, 56, len(pixels), 0, 32)
        r[74] = 0x22
    where = dict(file='GLOBAL/fixture.bun', view='raw', pack_offset=0,
                 in_track=False, chunk='33310002', entry_offset=0,
                 pack='fixture.tpk', texture='fixture', format='41' if paletted else 'DXT1')
    return c.Provider('textures', key, where, bytes(info), bytes(r), bytes(pl), pixels, palette,
                      struct.pack('<6I', 0, 0, 1, 7, 0, 0))


def inventory(directory, *, target=False, first=0):
    """Minimal real chunks: unused missing slot becomes a first binding mutant."""
    b = w.convert.Builder(0)
    scene = w.convert.Builder(b.position + 8)
    models = bytearray(72)
    struct.pack_into('<I', models, 24, 0x11111111)
    scene.add(0x34102, models)
    scene.add(0x34103, bytes(96 if target else 64), 16)
    b.add(0x80034100, scene.data)
    solids = w.convert.Builder(b.position + 8)
    solid = w.convert.Builder(solids.position + 8)
    header = bytearray(164)
    struct.pack_into('<I', header, 16, 0x11111111)
    solid.add(0x134011, header, 16)
    solid.add(0x134012, struct.pack('<4I', 0x22222222, 0, 0x33333333, 0))
    mesh = w.convert.Builder(solid.position + 8)
    material = bytearray(144 if target else 104)
    material[24] = first
    mesh.add(0x134b02, material, 16)
    mesh.add(0x134c02, b'fixture\0')
    solid.add(0x80134100, mesh.data)
    solids.add(0x80134010, solid.data)
    b.add(0x80134000, solids.data)
    b.pad(128)
    b.data += c.texture_pack([provider(0x22222222)]).encode()
    path = Path(directory) / ('target' if target else 'source')
    path.write_bytes(b.data)
    return w.Inventory(SimpleNamespace(sections=[section(101, len(b.data))]), path, target=target)


def reference_selecting_instances():
    """Read raw source selectors directly; no production reference inventory."""
    table, _ = single((w.DEFAULT_MW / 'L2RA.BUN').read_bytes(), 0x34110)
    selected = {}
    with (w.DEFAULT_MW / 'STREAML2RA.BUN').open('rb') as stream:
        for (record,) in struct.iter_unpack('<92s', table):
            number = struct.unpack_from('<h', record, 8)[0]
            offset, size = struct.unpack_from('<II', record, 20)
            stream.seek(offset)
            scene = 0
            for kind, payload, off in envelopes(stream.read(size)):
                if kind != 0x80034100:
                    continue
                models, _ = single(payload, 0x34102)
                raw, ro = single(payload, 0x34103, off + 8)
                rows = unpad(raw, ro)
                assert len(rows) % 64 == 0
                for i, (instance,) in enumerate(struct.iter_unpack('<64s', rows)):
                    model = struct.unpack_from('<h', instance, 62)[0]
                    assert 0 <= model < len(models) // 72
                    for key in struct.unpack_from('<4I', models, model * 72 + 24):
                        selected.setdefault(key, set()).add((number, scene, i))
                scene += 1
    return selected


class SyntheticTests(unittest.TestCase):
    def test_first_texture_miss_cannot_hide_in_an_unused_directory_slot(self):
        with tempfile.TemporaryDirectory() as directory:
            source = inventory(directory)
            control = inventory(directory, target=True)
            rows = c.classify(source, c.Census())
            self.assertEqual(c.check_first_textures(source, control, rows)['before'], 0)
            broken = inventory(directory, target=True, first=1)
            self.assertEqual(control.closure(), broken.closure())
            self.assertEqual(len(broken.first_texture_refs[0x33333333]), 1)
            with self.assertRaisesRegex(FormatError, 'first-texture material binding changed'):
                c.check_first_textures(source, broken, rows)

    def test_source_provider_classification_opens_compression_and_checks_false_absence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tracks = root / 'TRACKS'
            tracks.mkdir()
            (tracks / 'L2RA.BUN').write_bytes(b'')
            source = inventory(root)
            p = provider(0x33333333)
            pack = c.texture_pack([p]).encode()
            wanted = c.wanted_keys(source)
            # The source index itself can hold a provider which stream-only
            # inventory overlooks. HUFF uses the shared bounded native reader.
            compressed = c.texture_compare.native_huff.fixture(pack)
            (tracks / 'L2RA.BUN').write_bytes(compressed)
            census = c.census_sources(tracks, wanted)
            rows = c.classify(source, census)
            self.assertEqual(rows[0]['class'], 'converter-gap')
            self.assertEqual(census.summary['compressed_blocks'], 1)
            self.assertIn('HUFF@0', rows[0]['provider']['view'])
            c.verify_classes(rows, c.classify(source, census))
            wrong = deepcopy(rows)
            wrong[0]['class'] = 'absent-in-source'
            with self.assertRaisesRegex(FormatError, 'classification differs'):
                c.verify_classes(wrong, c.classify(source, census))
            (tracks / 'L2RA.BUN').write_bytes(b'')
            (root / 'shared.bun').write_bytes(pack)
            global_census = c.census_sources(tracks, wanted)
            self.assertEqual(c.classify(source, global_census)[0]['class'], 'shared-global')
            # Cache reuse still rereads/hashes content: a same-length provider
            # replacement cannot retain the old key's decoded classification.
            replacement = c.texture_pack([provider(0x44444444)]).encode()
            self.assertEqual(len(replacement), len(pack))
            (root / 'shared.bun').write_bytes(replacement)
            changed = c.census_sources(tracks, wanted)
            self.assertEqual(c.classify(source, changed)[0]['class'], 'absent-in-source')
            (root / 'shared.bun').unlink()
            absent = c.classify(source, c.census_sources(tracks, wanted))
            self.assertEqual(absent[0]['class'], 'absent-in-source')

    def test_existing_tpk_converter_and_independent_content_reader(self):
        for paletted in (False, True):
            with self.subTest(paletted=paletted), tempfile.TemporaryDirectory() as directory:
                p = provider(paletted=paletted)
                source = c.texture_pack([p])
                stats = w.convert.Stats()
                target = w.convert.convert_tpk(source, 0, stats)
                validate_resources(target, 2500)
                index = SimpleNamespace(sections=[section(2500, len(target))])
                path = Path(directory) / 'stream'
                path.write_bytes(target)
                actual = c._target_textures(index, path, {p.key})[p.key][0]
                checked = c._check_texture(p, actual)
                self.assertEqual(checked['exact'], not paletted)
                self.assertEqual(stats.textures, 1)
                r, pl, pixels = actual
                with self.assertRaisesRegex(FormatError, 'pixels changed|quantization bounds'):
                    c._check_texture(p, (r, pl, bytes((255,)) * len(pixels)))

    def test_raw_hash_occurrence_is_not_a_provider_and_cli_missing_assets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tracks = root / 'TRACKS'
            tracks.mkdir()
            (tracks / 'L2RA.BUN').write_bytes(struct.pack('<I', 0x33333333))
            source = inventory(root)
            rows = c.classify(source, c.census_sources(tracks, c.wanted_keys(source)))
            self.assertEqual(rows[0]['class'], 'absent-in-source')
            with redirect_stderr(io.StringIO()):
                self.assertEqual(c.main(['--proof', str(root / 'absent.json')]), 3)


@unittest.skipUnless(ASSETS, 'private track archives absent')
class ArchiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index, cls.stream, _ = w.load_index(w.DEFAULT_MW, 'L2RA')
        cls.inventory = w.Inventory(cls.index, cls.stream)
        cls.census = c.census_sources(w.DEFAULT_MW, c.wanted_keys(cls.inventory))
        cls.rows = c.classify(cls.inventory, cls.census)

    def test_all_keys_have_decoded_evidence_and_independent_first_texture_counts(self):
        classes = {(r['kind'], r['class']): 0 for r in self.rows}
        for row in self.rows:
            classes[row['kind'], row['class']] += 1
            self.assertTrue(row['evidence'])
            self.assertIn('005018f0' if row['kind'] == 'models' else '00503400', row['lookup'])
        self.assertEqual(len(self.rows), 56)
        self.assertEqual(classes, {('models', 'absent-in-source'): 24,
                                  ('textures', 'absent-in-source'): 26,
                                  ('textures', 'shared-global'): 6})
        self.assertEqual({int(r['key'], 16) for r in self.rows if r['class'] == 'shared-global'}, SHARED)
        self.assertEqual(sum(r['references'] for r in self.rows if r['kind'] == 'models'), 155)
        self.assertEqual(sum(r['references'] for r in self.rows if r['kind'] == 'textures'), 1698)
        _, _, first, _, sections, meshes = reference_inventory()
        self.assertEqual((sections, meshes), (720, 46351))
        self.assertEqual(Counter({key: len(refs) for key, refs in self.inventory.first_texture_refs.items()}), first)
        self.assertEqual(sum(r.get('first_texture_meshes', 0) for r in self.rows), 25)
        self.assertEqual(sum(r.get('first_texture_meshes', 0) for r in self.rows
                             if r['class'] == 'shared-global'), 15)
        # Selecting an instance is a set of (section, scene, instance), even if
        # a model key occurs in more than one stored LOD slot of its row.
        selected = reference_selecting_instances()
        for row in (r for r in self.rows if r['kind'] == 'models'):
            self.assertEqual(row['selecting_instances'], len(selected.get(int(row['key'], 16), ())))

    def test_all_six_providers_convert_and_written_content_matches_source(self):
        additions = c.resident_additions(self.rows, self.census)
        self.assertFalse(additions[2400])
        self.assertEqual(len(additions[2500]), 3)
        out = w.convert.Builder(0)
        for pack in additions[2500]:
            out.pad(128)
            out.data += w.convert.convert_tpk(pack, out.position, w.convert.Stats())
        counts, _ = validate_resources(bytes(out.data), 2500)
        self.assertEqual(counts['textures'], 6)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'stream'
            path.write_bytes(out.data)
            index = SimpleNamespace(sections=[section(2500, len(out.data))])
            actual = c._target_textures(index, path, SHARED)
            self.assertEqual(set(actual), SHARED)
            for key in SHARED:
                self.assertEqual(len(actual[key]), 1)
                result = c._check_texture(self.census.choose('textures', key), actual[key][0])
                if key == 0x4a31e2a3:
                    self.assertEqual(result['stored_mips'], 7)
                    self.assertEqual(result['maximum_channel_error'], [0, 0, 0, 11])
                else:
                    self.assertTrue(result['exact'])

    def test_false_absence_with_real_provider_is_rejected(self):
        c.verify_classes(self.rows, c.classify(self.inventory, self.census))
        wrong = deepcopy(self.rows)
        row = next(r for r in wrong if r['class'] == 'shared-global')
        row['class'] = 'absent-in-source'
        with self.assertRaisesRegex(FormatError, 'classification differs'):
            c.verify_classes(wrong, c.classify(self.inventory, self.census))


if __name__ == '__main__':
    result = unittest.main(exit=False, verbosity=2).result
    raise SystemExit(1 if not result.wasSuccessful() else 0 if ASSETS else 3)
