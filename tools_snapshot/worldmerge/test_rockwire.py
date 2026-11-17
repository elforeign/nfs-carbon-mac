"""Writer integration: baseline 692/720 -> provider census 720/720.

Loader/translation proof: 720/720 at shift 0 and 720/720 at +20000.
Source-index closure: 19269/19293 model keys, 99297/99452 stored LOD slots;
24 absent keys/155 slots are listed; Z00 accounts for two keys/ten slots.
Broken variants: X00 sky row present/removed = 1/1 accepted, 1/1 rejected;
X00 provider present/dropped = 9/9 accepted, 9/9 rejected; populated bounds
ordered/swapped = 1/1 accepted, 1/1 rejected; Z00 original/third absent key =
1/1 accepted, 1/1 rejected. Default callers still refuse all ten reference-only
sections. Classified animation omissions retain ordinary texture packs.
Empty-bound sentinel with a declared vertex: 1/1 rejected; native empty: 1/1
accepted. Directory with/without its ordinary frames: 1/1 accepted, 1/1 refused.
Missing private archives exits 3. No game runs or source archive writes.
"""
from collections import Counter, defaultdict
import argparse
import csv
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import classify
import convert
import texanim
import validate
from formats import Chunk, FormatError, chunks, u32
from merge import DEFAULT_MW, load_index, read_section
from test_resources import inventory
from test_scenery2 import fixture

parser = argparse.ArgumentParser(add_help=False)
parser.add_argument('--mw', type=Path, default=DEFAULT_MW)
args, remaining = parser.parse_known_args()
ASSETS = all((args.mw / n).is_file() for n in ('L2RA.BUN', 'STREAML2RA.BUN'))


def descendants(raw):
    for c in chunks(raw):
        yield c
        if c.kind & 0x80000000:
            yield from nested(c)


def nested(parent):
    for c in chunks(parent.payload, parent.offset + 8):
        yield c
        if c.kind & 0x80000000:
            yield from nested(c)


class SyntheticTests(unittest.TestCase):
    def test_populated_bounds_remain_ordered(self):
        target, _ = convert.convert_section(fixture((101,)), 101, 0)
        validate.validate_section(target, 101)
        solid = next(c for c in descendants(target) if c.kind == 0x134011)
        pos = solid.offset + 8 + (-(solid.offset + 8) % 16)
        broken = bytearray(target)
        # Swap the full lower and upper XYZ bounds of the populated triangle.
        broken[pos + 32:pos + 44], broken[pos + 48:pos + 60] = (
            target[pos + 48:pos + 60], target[pos + 32:pos + 44])
        with self.assertRaisesRegex(FormatError, 'inverted box'):
            validate.validate_section(bytes(broken), 101)
        print('BOUNDS: ordered=1/1 accepted; swapped=1/1 rejected')

    def test_animation_omission_requires_ordinary_frames(self):
        record = bytearray(52)
        struct.pack_into('<Iiii', record, 24, 1234, 1, 30, 0)
        directory = Chunk(0xb0300100,
            Chunk(0x30300101, struct.pack('<4I', 1, 0, 0, 0)).encode() +
            Chunk(0x30300102, bytes(record)).encode() +
            Chunk(0x30300103, struct.pack('<4I', 5678, 0, 0, 0)).encode())
        stats = convert.Stats()
        for frames in (frozenset({5678}), frozenset()):
            context = texanim.DirectoryContext(101, directory, frames)
            inventory = texanim.SourceInventory((context,), Counter(), 0, 1)
            if frames:
                convert.omit_animation_directory(directory, stats, inventory)
                self.assertEqual(stats.omitted, {'b0300100': len(directory.payload)})
            else:
                with self.assertRaisesRegex(FormatError, 'omission lacks ordinary textures'):
                    convert.omit_animation_directory(directory, stats, inventory)
                self.assertEqual(stats.omitted, {'b0300100': len(directory.payload)})
        print('ANIMATION: ordinary frames retained=1/1 accepted; missing=1/1 rejected')


@unittest.skipUnless(ASSETS, 'private track archives absent')
class ArchiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index, cls.stream, _ = load_index(args.mw, 'L2RA')
        cls.animation_inventory = texanim.inventory_source(cls.index, cls.stream)
        cls.rows, cls.summary = classify.classify(args.mw)
        cls.accepted = {r['number'] for r in cls.rows if r['conversion']['success']}
        cls.source_keys, cls.providers, cls.refs = {}, defaultdict(set), Counter()
        cls.no_local, cls.saved = [], {}
        # This inventory reads source solid headers and source directory tables;
        # neither emitted resources nor conversion statistics define closure.
        for section in cls.index.sections:
            raw = read_section(cls.stream, section)
            solids, textures, refs = inventory(raw)
            cls.source_keys[section.number] = solids, textures
            cls.refs.update(refs)
            for key in solids:
                cls.providers[key].add(section.number)
            if refs and not solids:
                cls.no_local.append(section.number)
            if section.number in (2400, 2600) or (refs and not solids):
                cls.saved[section.number] = raw
        cls.context = dict(cls.providers), cls.accepted

    def test_census_and_every_output_at_both_shifts(self):
        self.assertEqual(self.summary['converter_successes'], 720)
        self.assertEqual(self.summary['converter_failures'], 0)
        self.assertEqual(self.summary['bytes_walk'], 531897380)
        checked, omitted = Counter(), Counter()
        for section in self.index.sections:
            source = read_section(self.stream, section)
            scenes = any(c.kind == 0x80034100 for c in chunks(source))
            for shift in (0, 20000):
                with self.subTest(section=section.name, shift=shift):
                    target, stats = convert.convert_section(source, section.number, shift,
                        source_number=section.number, providers=self.context,
                        animation_inventory=self.animation_inventory, allow_precull_mismatch=True)
                    if scenes:
                        validate.validate_section(target, section.number, providers=self.context)
                    else:
                        validate.validate_resources(target, section.number)
                    validate.validate_translation(source, target, shift,
                        source_number=section.number, target_number=section.number)
                    solids, textures = self.source_keys[section.number]
                    renamed = Counter({0x1f389568 if k == 0xed85ba82 else k: v for k,v in solids.items()})
                    self.assertEqual(inventory(target, True)[:2], (renamed,textures))
                    refs = inventory(source)[2]
                    expected = Counter({0x1f389568 if k == 0xed85ba82 else k: v for k,v in refs.items()})
                    self.assertEqual(expected, inventory(target, True)[2])
                    directories = [c for c in chunks(source) if c.kind == 0xb0300100]
                    self.assertFalse(any(c.kind == 0xb0300100 for c in chunks(target)))
                    self.assertEqual(stats.omitted['b0300100'], sum(len(c.payload) for c in directories))
                    if shift == 0:
                        omitted['directories'] += len(directories)
                        omitted['bytes'] += stats.omitted['b0300100']
                    checked[shift] += 1
        self.assertEqual(checked, {0: 720, 20000: 720})
        self.assertEqual(omitted, {'directories': 6, 'bytes': 1016})
        print('SECTIONS: shift 0=720/720 loader+translation pass; +20000=720/720 pass; '
              'animation omissions=6 directories/1016 payload bytes; no refusals')

    def test_source_index_closure_and_classified_instances(self):
        available = set().union(*(self.source_keys[n][0] for n in self.accepted))
        resolved = set(self.refs) & available
        misses = {k: n for k, n in self.refs.items() if k not in available}
        self.assertEqual((len(self.refs), sum(self.refs.values())), (19293, 99452))
        self.assertEqual((len(resolved), sum(n for k, n in self.refs.items() if k in available)),
                         (19269, 99297))
        self.assertEqual((len(misses), sum(misses.values())), (24, 155))
        self.assertEqual({k: n for k, n in misses.items() if k in (0x56b52d28, 0xf390cd1a)},
                         {0x56b52d28: 1, 0xf390cd1a: 9})
        closure = self.summary['source_index_closure']
        self.assertEqual((closure['model_keys'], closure['stored_lod_slots']), (19293, 99452))
        self.assertEqual({int(r['key'], 16): r['slots'] for r in closure['misses']}, misses)
        self.assertTrue(all(r['classification'] == 'source key absent' for r in closure['misses']))
        z00 = next(r for r in self.rows if r['number'] == 2600)
        exceptions = z00['reference_exceptions']
        self.assertEqual([e['instance'] for e in exceptions], [1, 2, 4, 5, 6])
        self.assertEqual([e['instance'] for e in exceptions if e['sentinel_only']], [2])
        classify.SCRATCH.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=classify.SCRATCH) as tmp:
            out = Path(tmp) / 'report'
            classify.write_report(out, self.rows, self.summary)
            with (out / 'reference_exceptions.tsv').open() as f:
                rows = list(csv.DictReader(f, delimiter='\t'))
            self.assertEqual([int(r['instance']) for r in rows], [1, 2, 4, 5, 6])
            self.assertTrue(all(r['section'] == 'Z00' for r in rows))
        print('CLOSURE: 19269/19293 keys; 99297/99452 slots; 24 absent keys/155 slots listed; '
              'Z00 misses=56b52d28:1,f390cd1a:9; instances=1,2(sentinel),4,5,6')

    def test_sky_row_removed_refuses_x00(self):
        target, stats = convert.convert_section(self.saved[2400], 2400, 0, providers=self.context)
        validate.validate_resources(target, 2400)
        self.assertEqual(stats.effects['19->15'], 1)
        self.assertEqual(stats.solids, 2331)
        predecessor = {k: v for k, v in convert.EFFECTS.items() if k != 19}
        with patch.object(convert, 'EFFECTS', predecessor):
            with self.assertRaisesRegex(FormatError, 'undecoded source effect 19'):
                convert.convert_section(self.saved[2400], 2400, 0, providers=self.context)
        print('SKY ROW: X00 present=1/1 accepted; removed=1/1 rejected')

    def test_dropped_x00_provider_refuses_nine_sections(self):
        numbers = [n for n in self.no_local if n != 2600]
        names = {s.name for s in self.index.sections if s.number in numbers}
        self.assertEqual(names, {'E51', 'E52', 'A87', 'C81', 'C82', 'C86', 'C87', 'P83', 'S98'})
        dropped = {k: sections - {2400} for k, sections in self.context[0].items()}
        for number in numbers:
            convert.convert_section(self.saved[number], number, 0, providers=self.context)
            with self.assertRaisesRegex(FormatError, 'refonly unresolved solids'):
                convert.convert_section(self.saved[number], number, 0,
                    providers=(self.context[0], self.accepted - {2400}))
            with self.assertRaisesRegex(FormatError, 'refonly unresolved solids'):
                convert.convert_section(self.saved[number], number, 0,
                    providers=(dropped, self.accepted))
        print('PROVIDERS: X00 accepted=9/9 pass; dropped from provider map/accepted set=9/9 rejected each')

    def test_empty_sentinel_cannot_hide_declared_vertices(self):
        target, _ = convert.convert_section(self.saved[2400], 2400, 0)
        validate.validate_resources(target, 2400)
        mesh = next(c for c in descendants(target) if c.kind == 0x134900 and
                    u32(validate.payload(c), 16) == 0)
        pos = mesh.offset + 8 + (-(mesh.offset + 8) % 16)
        broken = bytearray(target)
        struct.pack_into('<I', broken, pos + 20, 1)
        with self.assertRaisesRegex(FormatError, 'inverted box'):
            validate.validate_resources(bytes(broken), 2400)
        print('EMPTY BOUNDS: native empty=1/1 accepted; declared vertex=1/1 rejected')

    def test_default_callers_keep_geometry_guard(self):
        self.assertEqual(len(self.no_local), 10)
        for number in self.no_local:
            with self.assertRaisesRegex(FormatError, 'section lacks geometry or instances'):
                convert.convert_section(self.saved[number], number, 0)

    def test_third_absent_z00_key_refuses(self):
        source = self.saved[2600]
        target, _ = convert.convert_section(source, 2600, 0, providers=self.context)
        validate.validate_section(target, 2600, providers=self.context)
        for data, checker in ((source, 'source'), (target, 'target')):
            table = next(c for c in descendants(data) if c.kind == 0x34102)
            broken = bytearray(data)
            struct.pack_into('<I', broken, table.offset + 8 + 24, 0x12345678)
            with self.assertRaises(FormatError):
                if checker == 'source':
                    convert.convert_section(bytes(broken), 2600, 0, providers=self.context)
                else:
                    validate.validate_section(bytes(broken), 2600, providers=self.context)
        print('Z00: original=1/1 accepted; third absent key=1/1 writer and 1/1 validator rejected')


if __name__ == '__main__':
    result = unittest.main(argv=[sys.argv[0]] + remaining, exit=False, verbosity=2).result
    if not result.wasSuccessful():
        raise SystemExit(1)
    if not ASSETS:
        print('SKIP: private track archives absent')
        raise SystemExit(3)
