"""Global merge: 442/155/1238 -> 1147/483/2614; omitted types 0.

Type-6 words 514/514 mapped, cross-city duplicates 57 -> 0; polygon bytes
59512 + 74628. Native marker ordinals 155/155 preserved. Six serialized
pair controls in test_c1_world: 57 unmapped collisions (valid 0), unshifted
705 zones (valid 0), source-first 1 marker (valid 0), split 1 type range
(valid 0), 2613/2614 barriers, half merge 442/328/1238 vs 1147/483/2614.
All six must be rejected, 0/6 accepted. Synthetic cases always run;
private inputs absent exits 3. No game runs.
Coast districts: mapped keys resolve 11/11; original MW keys resolve 0/11.
"""
from collections import Counter
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import struct
import sys
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(HERE))
import c1_zones as c
import c1_world as w
import districts
import zones as z
from formats import Chunk, FormatError, TrackIndex, u32
from test_zones import polygon

ASSETS = all((root/name).is_file() for root, base in ((w.DEFAULT_MW, 'L2RA'),
    (w.DEFAULT_CARBON, 'L5RA')) for name in (base+'.BUN', 'STREAM'+base+'.BUN'))
CARBON_VAULT = (w.DEFAULT_CARBON.parent/'GLOBAL/attributes.bin').is_file()


def fixture(native):
    rows = []
    for kind in ((3, 6, 9, 11, 16) if native else (3, 6, 9, 11, 14)):
        raw = bytearray(polygon(kind, 0x12345678))
        if kind == 6:
            struct.pack_into('<4I', raw, 48, *((11, 12, 0, 14) if native else (101, 102, 0, 104)))
        rows.append(bytes(raw))
    marker = bytearray(48)
    struct.pack_into('<I3f', marker, 8, 0x12345678, 0., 2., 3.)
    markers = []
    for i in range(3):
        struct.pack_into('<II', marker, 32, i + (0 if native else 10), 0 if native or i < 2 else 2000)
        markers.append(bytes(marker))
    barriers = [struct.pack('<4fII', -0., 2., 3., 4., i, 0xabcdef01) for i in range(2)]
    parts = (Chunk(z.ZONES, Chunk(z.POLYGONS, b''.join(rows)).encode()),
             Chunk(z.MARKERS, b'\x11'*8 + b''.join(markers)),
             Chunk(z.BARRIERS, b''.join(barriers)))
    return SimpleNamespace(parts=list(parts))


class Synthetic(unittest.TestCase):
    def setUp(self):
        self.carbon, self.source = fixture(True), fixture(False)
        self.mapping = {101: 201, 102: 202, 104: 204}

    def test_stable_prefixes_shift_mapping_and_independent_reader(self):
        result = c.merge(self.carbon, self.source, self.mapping)
        with patch.object(c, 'merge', side_effect=AssertionError('reader used writer')), \
             patch.object(z, 'convert', side_effect=AssertionError('reader used conversion')):
            report = c.reread(result, self.carbon, self.source, self.mapping)
        self.assertEqual((report['zones'], report['markers'], report['barriers']), (10, 6, 4))
        self.assertEqual((report['source_type6_words'], report['mapped_type6_words'],
                          report['cross_city_type6_duplicates']), (3, 3, 0))
        self.assertEqual(report['shared_marker_keys'], [dict(key='12345678', carbon=3, rockport=3)])
        self.assertEqual(report['shared_barrier_groups'], [dict(key='abcdef01', carbon=2, rockport=2)])
        actual = z.read(result)
        native, source = z.read(z.select(self.carbon)), z.read(z.select(self.source))
        self.assertEqual([r.kind for r in actual.zones], [3, 3, 6, 6, 9, 9, 11, 11, 14, 16])
        for kind in (3, 6, 9, 11):
            self.assertEqual(next(r.encode() for r in actual.zones if r.kind == kind),
                             next(r.encode() for r in native.zones if r.kind == kind))
        self.assertEqual(actual.zones[1].bounds, (-1.5, -20482.25, 3.5, -20475.75))
        self.assertEqual(actual.markers[:3], native.markers)
        self.assertEqual(actual.barriers[:2], native.barriers)
        self.assertEqual([u32(r, 36) for r in actual.markers], [0, 0, 0, 0, 0, 2000])
        self.assertEqual(actual.markers[3][16:20], source.markers[0][16:20])
        strings = c.merge(self.carbon, self.source, {str(k): v for k, v in self.mapping.items()})
        self.assertEqual(strings, result)

    def test_missing_mapping_and_cross_city_identity_collisions(self):
        with self.assertRaisesRegex(FormatError, 'unmapped type-6'):
            c.merge(self.carbon, self.source, {101: 201})
        result = c.merge(self.carbon, self.source, self.mapping)
        with self.assertRaisesRegex(FormatError, 'unmapped source type-6'):
            c.reread(result, self.carbon, self.source, {101: 201})
        colliding = {101: 11, 102: 202, 104: 204}
        with self.assertRaisesRegex(FormatError, 'cross-city duplicate'):
            c.reread(c.merge(self.carbon, self.source, colliding), self.carbon, self.source, colliding)
        for value in (0, -1, 1 << 32):
            with self.subTest(value=value), self.assertRaisesRegex(FormatError, 'nonzero u32'):
                c.merge(self.carbon, self.source, {**self.mapping, 101: value})

    def test_record_corruption_native_prefixes_and_incomplete_forms(self):
        table = z.read(c.merge(self.carbon, self.source, self.mapping))
        variants = []
        for field, pos in (('markers', 20), ('barriers', 12)):
            rows = list(getattr(table, field))
            raw = bytearray(rows[-1])
            struct.pack_into('<f', raw, pos, 1.)
            rows[-1] = bytes(raw)
            variants.append(replace(table, **{field: tuple(rows)}))
        variants += [replace(table, markers=table.markers[3:4]+table.markers[:3]+table.markers[4:]),
                     replace(table, barriers=table.barriers[:-1]),
                     replace(table, zones=z.read(z.select(self.carbon)).zones)]
        zones_ = list(table.zones)
        header = bytearray(zones_[3].header)
        struct.pack_into('<I', header, 48, 101)
        zones_[3] = replace(zones_[3], header=bytes(header))
        variants.append(replace(table, zones=tuple(zones_)))
        for i, bad in enumerate(variants):
            with self.subTest(variant=i), self.assertRaises(FormatError):
                c.reread(bad.encode(), self.carbon, self.source, self.mapping)


@unittest.skipUnless(ASSETS, 'private world archives absent')
class Private(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.carbon, cs, _ = w.load_index(w.DEFAULT_CARBON, 'L5RA')
        cls.source, ms, _ = w.load_index(w.DEFAULT_MW, 'L2RA')
        cls.mapping = w.numbers.plan((cls.source, ms), (cls.carbon, cs))['numbers']['rockport']

    def test_census_and_every_source_record(self):
        result = c.merge(self.carbon, self.source, self.mapping)
        with patch.object(c, 'merge', side_effect=AssertionError('reader used merger')), \
             patch.object(z, 'convert', side_effect=AssertionError('reader used converter')), \
             patch.object(w.numbers, 'plan', side_effect=AssertionError('reader used plan')):
            report = c.reread(result, self.carbon, self.source, self.mapping)
        self.assertEqual((report['zones'], report['markers'], report['barriers']), (1147, 483, 2614))
        expected = {3:112, 4:202, 5:202, 6:377, 7:13, 8:60, 9:17, 10:15,
                    11:8, 12:22, 13:3, 14:3, 15:1, 16:56, 17:56}
        self.assertEqual({r['type']: r['count'] for r in report['ranges'] if r['count']}, expected)
        self.assertEqual(report['polygon_bytes'], dict(carbon=59512, rockport=74628))
        self.assertEqual((report['source_type6_words'], report['mapped_type6_words'],
                          report['cross_city_type6_duplicates']), (514, 514, 0))
        self.assertEqual((len(report['shared_marker_keys']), len(report['shared_barrier_groups'])), (5, 215))
        self.assertEqual(report['native_marker_lookups_preserved'], 155)
        native, source = (z.read(z.select(i)) for i in (self.carbon, self.source))
        self.assertEqual((len(native.zones), len(source.zones)), (442, 705))
        self.assertEqual(Counter(u32(r, 36) for r in source.markers), {0:319, 2000:9})
        ids = lambda t: {u32(r.header, p) for r in t.zones if r.kind == 6
                         for p in range(48, 64, 4) if u32(r.header, p)}
        self.assertEqual(len(ids(native) & ids(source)), 57)
        print('ACCEPT zones/markers/barriers 1147/483/2614; 514/514 IDs mapped; 57 -> 0 collisions; 155/155 native lookups')

    def test_zone_bounds_match_world_render_translation(self):
        # One polygon is interpreted both as a zone and as a visibility
        # boundary: the two independent writers must agree on render bounds.
        source = z.read(z.select(self.source)).zones[0]
        prefix = sum(r.kind == source.kind for r in z.read(z.select(self.carbon)).zones)
        moved = [r for r in z.read(c.merge(self.carbon, self.source, self.mapping)).zones
                 if r.kind == source.kind][prefix]
        template = next(self.source.boundaries())
        boundary = w.union_boundary(template, 101, source.vertices)
        self.assertEqual(moved.bounds, boundary.bounds)
        self.assertEqual(moved.vertices, tuple(boundary.vertices))

    @unittest.skipUnless(CARBON_VAULT, 'private Carbon vault absent')
    def test_coast_districts_resolve_carbon_patterns(self):
        shift = w.c3_crossing.COAST_SHIFT
        chunk = c.merge_districts(self.carbon, self.source, shift, w.DEFAULT_CARBON)
        result = tuple(chunk if part.kind == z.ZONES else part for part in z.select(self.carbon))
        with patch.object(c, 'merge_districts', side_effect=AssertionError('reader used writer')), \
             patch.object(z, 'convert', side_effect=AssertionError('reader used converter')):
            report = c.reread_districts(result, self.carbon, self.source, shift, w.DEFAULT_CARBON)
        # 461 = 453 + Rockport's 8 type-11 neighbourhoods (the banner's zone query 00761EF0 type 0xB);
        # the old coast merge carried type 9 only: 453 zones, no type 11, no banner in Rockport.
        self.assertEqual((report['zones'], report['markers'], report['barriers']), (461, 155, 1238))
        self.assertEqual((report['resolved_rockport_districts'], report['rockport_districts']), (11, 11))
        self.assertEqual(report['rockport_neighbourhoods'], 8)

        table = z.read(result)
        native = z.read(z.select(self.carbon))
        source = z.read(z.select(self.source))
        self.assertEqual(table.markers, native.markers)
        self.assertEqual(Counter(u32(row, 36) for row in source.markers)[2000], 9)
        self.assertFalse(any(u32(row, 36) == 2000 for row in table.markers))
        start = sum(zone.kind <= 9 for zone in native.zones)
        originals = [zone for zone in source.zones if zone.kind == 9]
        end = start + len(originals)
        patterns = districts.traffic_patterns(w.DEFAULT_CARBON)
        control = tuple(replace(written, header=written.header[:48] + original.header[48:52] + written.header[52:])
                        for original, written in zip(originals, table.zones[start:end]))
        self.assertEqual(sum(zone.key in patterns for zone in control), 0)
        broken = replace(table, zones=table.zones[:start] + control + table.zones[end:])
        with self.assertRaisesRegex(FormatError, 'Rockport traffic patterns resolve 0/11'):
            c.reread_districts(broken.encode(), self.carbon, self.source, shift, w.DEFAULT_CARBON)
        names = [zone.key for zone in table.zones if zone.kind == 11]
        self.assertEqual(names, [zone.key for zone in source.zones if zone.kind == 11])
        self.assertTrue({0x4CA802EC, 0x2485871E, 0xCCBCE907, 0x9F3316E5, 0x9A43A1D1, 0x890E0C19,
                         0xCAC1155C} <= set(names))
        dropped = replace(table, zones=tuple(zone for zone in table.zones if zone.kind != 11))
        with self.assertRaisesRegex(FormatError, 'type-11 suffix'):
            c.reread_districts(dropped.encode(), self.carbon, self.source, shift, w.DEFAULT_CARBON)
        print('ACCEPT coast districts resolve 11/11, neighbourhoods 8/8; original MW keys resolve 0/11')


if __name__ == '__main__':
    result = unittest.main(exit=False)
    sys.exit(1 if not result.result.wasSuccessful() else 0 if ASSETS else 3)
