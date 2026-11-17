"""C1 proof: baseline 1,002 zones wanted / 780 available; no prior plan.

Acceptance: 1/1 data plan, 775 primary / 780 zone identities, duplicate IDs 0.
Six broken variants: 0/6 accepted, 6/6 rejected on synthetic AND private plans. Synthetic checks
always run; private indexes/streams absent => exit 3. No game runs.
"""
from copy import deepcopy
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(HERE))
import c1_numbers as c1
from formats import Chunk, FormatError, TrackIndex, encode_chunks
import visibility as vis

PATHS = [vis.DEFAULT_MW, vis.DEFAULT_CARBON]
ASSETS = all(p.is_file() and p.with_name('STREAM' + p.name).is_file() for p in PATHS)


def fixture(numbers, extended):
    """Independent minimal native-layout bytes, including an absent row entry."""
    boundaries, rows, records = bytearray(), bytearray(), bytearray()
    for n in numbers:
        raw = bytearray(48 if extended else 36)
        struct.pack_into('<hBB', raw, 8, n, 4, 0)
        struct.pack_into('<6f', raw, 24 if extended else 12, -1, -1, 1, 1, 0, 0)
        raw += struct.pack('<8f', -1, -1, 1, -1, 1, 1, -1, 1)
        boundaries += raw
        row = bytearray(28)
        struct.pack_into('<hBBhhh', row, 12, n, 2, 4, 2, n + 40, 2099)
        rows += row
        record = bytearray(92)
        struct.pack_into('<h', record, 8, n + 40)
        struct.pack_into('<I', record, 24, 1000)
        records += record
    drive = struct.pack('<II', 40, len(numbers)) + struct.pack(f'<{len(numbers)}h', *numbers)
    parts = [Chunk(vis.DRIVE, drive), Chunk(vis.BOUNDARIES, bytes(boundaries)),
             Chunk(vis.ROWS, bytes(rows)), Chunk(vis.LOADING, b'')]
    if extended:
        # Absolute selector alignment: container begins at 0, payload at 8.
        p = 8 + sum(8 + len(part.payload) for part in parts)
        parts.append(Chunk(vis.SELECTORS, bytes(-(p + 8) % 16)))
    return TrackIndex(encode_chunks([Chunk(vis.CONTAINER, encode_chunks(parts)),
                                     Chunk(0x34110, bytes(records))]))


def accepted():
    doc = c1.plan(fixture([101, 201], False), fixture([101], True))
    # Pack IDs are an independent namespace; a pack can share a section ID.
    doc['sources']['palmont']['packs'] = [101]
    doc['sources']['rockport']['packs'] = [101, 102]
    doc['packs'] = c1.pack_allocation(doc['sources'])
    doc['counts'] = c1.census(doc['sources'])
    # Move an otherwise free pair so leaving its partner behind is observable
    # independently of the duplicate-number check.
    doc['numbers']['rockport']['201'] = 301
    doc['numbers']['rockport']['241'] = 341
    return doc


def mutate(doc, kind):
    broken = deepcopy(doc)
    mapping = broken['numbers']['rockport']
    if 'composition' in broken:
        composition = broken['composition']
        group = next(g for g in composition['groups'] if any(n != g['number'] for n in g['members']))
        old = next(n for n in group['members'] if n != group['number'])
        if kind == 'two_zones':
            mapping[str(old)] = next(g['number'] for g in composition['groups'] if g != group)
        elif kind == 'x40':
            group['number'] = 340
        elif kind == 'letter_U':
            group['number'] = 2101
        elif kind == 'row_385':
            composition['rows'][0]['entries'] = [141] * 385
        elif kind == 'pack_2700':
            broken['packs']['rockport']['101'] = 2700
        elif kind == 'old_partner':
            mapping[str(old + 40)] = old + 40
        else:
            raise ValueError(kind)
        return broken
    if kind == 'two_zones':
        mapping['201'] = mapping['101']
    elif kind == 'x40':
        mapping['201'] = 340
    elif kind == 'letter_U':
        mapping['201'] = 2101
    elif kind == 'row_385':
        broken['sources']['rockport']['rows'][0][2] = [141] * 385
        broken['counts'] = c1.census(broken['sources'])
    elif kind == 'pack_2700':
        broken['packs']['rockport']['101'] = 2700
    elif kind == 'old_partner':
        mapping['241'] = 241
    else:
        raise ValueError(kind)
    return broken


VARIANTS = [('two_zones', 'duplicate number'), ('x40', 'zone outside'),
            ('letter_U', 'zone outside'), ('row_385', '384 entries'),
            ('pack_2700', 'pack ID outside'), ('old_partner', 'partner left behind')]


class SyntheticTests(unittest.TestCase):
    def test_valid_allocation_and_six_broken_variants(self):
        doc = accepted()
        verdict = c1.check(doc)
        self.assertTrue(verdict['feasible'])
        self.assertEqual(verdict['duplicate_numbers'], 0)
        self.assertEqual(len(c1.summary(doc)), 15)
        self.assertEqual(c1.check(json.loads(json.dumps(doc))), verdict)
        for variant, reason in VARIANTS:
            with self.subTest(variant=variant), self.assertRaisesRegex(FormatError, reason):
                c1.check(mutate(doc, variant))

    def test_source_absence_preserved_and_every_identity_allocated(self):
        doc = accepted()
        mapping = doc['numbers']['rockport']
        self.assertNotEqual(mapping['101'], 101)
        self.assertEqual(mapping['141'], mapping['101'] + 40)
        all_records = {doc['numbers'][city][str(n)] for city in c1.CITIES
                       for n, _ in doc['sources'][city]['records']}
        self.assertNotIn(mapping['2099'], all_records)
        self.assertNotIn(doc['numbers']['palmont']['2099'], all_records)
        del mapping['2099']
        with self.assertRaisesRegex(FormatError, 'number map incomplete'):
            c1.check(doc)

    def test_source_counts_and_evidence_are_checked(self):
        doc = accepted()
        doc['counts']['records'] += 1
        with self.assertRaisesRegex(FormatError, 'census differs'):
            c1.check(doc)
        doc = accepted()
        doc['numbers']['palmont']['101'] = 401
        with self.assertRaisesRegex(FormatError, 'native number changed'):
            c1.check(doc)
        doc = accepted()
        doc['limits']['zones'] = 1002
        with self.assertRaisesRegex(FormatError, 'schema/limits'):
            c1.check(doc)

    def test_other_decoded_limits(self):
        for field, edit, reason in [
            ('drivable', lambda s: s['drivable'] * 513, '512 drivable'),
            ('boundaries', lambda s: [[n, 128] for n, _ in s['boundaries']], '127 vertices'),
            ('records', lambda s: [[n, 71680001] for n, _ in s['records']], 'pool byte'),
            ('rows', lambda s: [[n, 128, e] for n, _, e in s['rows']], 'signed cap')]:
            doc = accepted()
            source = doc['sources']['rockport']
            source[field] = edit(source)
            doc['counts'] = c1.census(doc['sources'])
            with self.subTest(field=field), self.assertRaisesRegex(FormatError, reason):
                c1.check(doc)
        doc = accepted()
        doc['numbers']['rockport']['2099'] = 2800
        with self.assertRaisesRegex(FormatError, '2800-bit bitmap'):
            c1.check(doc)

    def test_packs_reserve_noncolliders_and_do_not_alias(self):
        doc = accepted()
        self.assertEqual(doc['packs'], {'palmont': {'101': 101},
                                       'rockport': {'101': 1, '102': 102}})
        doc['packs']['rockport']['101'] = 102
        with self.assertRaisesRegex(FormatError, 'duplicate pack'):
            c1.check(doc)

    def test_native_boundary_classification_edges(self):
        valid = [n for n in range(2800) if c1.zone(n)]
        self.assertEqual(len(valid), 780)
        self.assertEqual((valid[0], valid[-1]), (101, 2039))
        self.assertFalse(any(c1.zone(n) for n in (100, 140, 2000, 2040, 2101, 2301)))

    def test_polygon_union_preserves_coverage_and_rejects_disconnected_rings(self):
        a = [[0, 0], [2, 0], [2, 2], [0, 2]]
        adjacent = [[2, 0], [4, 0], [4, 2], [2, 2]]
        overlap = [[1, 1], [3, 1], [3, 3], [1, 3]]
        for b, area in [(adjacent, 8), (overlap, 7)]:
            ring = c1.polygon_union(a, b)
            self.assertIsNotNone(ring)
            measured = sum(p[0] * q[1] - p[1] * q[0]
                           for p, q in zip(ring, ring[1:] + ring[:1])) / 2
            self.assertAlmostEqual(measured, area)
            self.assertTrue(c1.inside((1, 1), ring))
        separate = [[5, 0], [7, 0], [7, 2], [5, 2]]
        self.assertIsNone(c1.polygon_union(a, separate))

    def test_cli_missing_private_assets_exits_three(self):
        with tempfile.TemporaryDirectory() as tmp, redirect_stderr(io.StringIO()):
            missing = str(Path(tmp) / 'absent.BUN')
            self.assertEqual(c1.main(['--mw-index', missing, '--carbon-index', missing,
                                      '--out', str(Path(tmp) / 'out.json')]), 3)


@unittest.skipUnless(ASSETS, 'private index/stream assets absent')
class PrivateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = c1.plan(vis.DEFAULT_MW, vis.DEFAULT_CARBON)

    def test_measured_counts_and_decision(self):
        doc = self.doc
        counts = doc['counts']
        self.assertEqual(doc['outcome'], 'A')
        self.assertTrue(c1.check(doc)['feasible'])
        self.assertEqual((counts['cities']['palmont']['zones'], counts['cities']['rockport']['zones']), (567, 435))
        self.assertEqual((counts['zones'], counts['paired_zones'], counts['records']), (1002, 995, 1682))
        self.assertEqual((counts['drivable'], counts['unique_drivable'], counts['rows']), (823, 819, 1007))
        self.assertEqual((counts['packs'], counts['pack_collisions'], counts['record_collisions']), (853, 279, 488))
        self.assertEqual((counts['row'], counts['polygon'], counts['row_bytes']), (71, 16, 46229220))
        output = c1.check(doc)['counts']
        self.assertEqual(output, dict(zones=775, zone_identities=780, records=1433, boundaries=930,
            rows=780, bitmap=2601, drivable=641, drivable_slots=704, packs=853,
            row=71, polygon=28, row_bytes=71132480, merges=227))
        self.assertEqual(doc['composition']['pack_resident_bytes'], 5805248)
        # Independently recompute the partner obstruction from original bytes.
        for path, ext, city in [(vis.DEFAULT_MW, False, 'rockport'), (vis.DEFAULT_CARBON, True, 'palmont')]:
            idx = TrackIndex(path.read_bytes())
            records = {struct.unpack_from('<h', s.raw, 8)[0] for s in idx.sections}
            table = vis.read(vis.payload_of(idx), extended=ext)
            partners = sum(100 <= b.number < 2100 and 1 <= b.number % 100 <= 39 and b.number + 40 in records
                           for b in table.boundaries)
            self.assertEqual(counts['cities'][city]['paired_zones'], partners)

    def test_six_broken_private_variants(self):
        for variant, reason in VARIANTS:
            with self.subTest(variant=variant), self.assertRaisesRegex(FormatError, reason):
                c1.check(mutate(self.doc, variant))

    def test_merged_polygon_coverage_samples_against_source(self):
        def winding(point, ring):
            result = 0
            for a, b in zip(ring, ring[1:] + ring[:1]):
                side = (b[0] - a[0]) * (point[1] - a[1]) - (b[1] - a[1]) * (point[0] - a[0])
                if a[1] <= point[1] < b[1] and side > 0:
                    result += 1
                elif b[1] <= point[1] < a[1] and side < 0:
                    result -= 1
            return result != 0
        polygons = self.doc['sources']['rockport']['polygons']
        samples = 0
        for group in self.doc['composition']['groups']:
            ring = group['polygon']
            old = [polygons[str(n)] for n in group['members']]
            x0, x1 = min(p[0] for p in ring), max(p[0] for p in ring)
            y0, y1 = min(p[1] for p in ring), max(p[1] for p in ring)
            for fx in (.113, .317, .521, .733, .937):
                for fy in (.113, .317, .521, .733, .937):
                    point = x0 + (x1 - x0) * fx, y0 + (y1 - y0) * fy
                    self.assertEqual(winding(point, ring), any(winding(point, p) for p in old),
                                     f"coverage changed for {group['members']} at {point}")
                    samples += 1
        self.assertEqual(samples, 5200)

    def test_composition_payload_polygon_row_and_reader_mutations(self):
        for kind in ('record', 'polygon', 'row', 'reader', 'capacity', 'pool', 'coverage',
                     'scene_owner', 'pack_residency', 'pack_storage'):
            doc = deepcopy(self.doc)
            composition = doc['composition']
            if kind == 'record':
                composition['records'].append(deepcopy(composition['records'][0]))
            elif kind == 'polygon':
                g = next(g for g in composition['groups'] if len(g['members']) > 1)
                g['polygon'][0][0] += 1
            elif kind == 'row':
                composition['rows'][0]['entries'].pop()
            elif kind == 'reader':
                composition['drivable_scheme'] = 'assume unbounded'
            elif kind == 'capacity':
                composition['drivable_slots'] = 512
            elif kind == 'pool':
                composition['rows'][0]['pool_bytes'] -= 1
            elif kind == 'scene_owner':
                composition['groups'][0]['scene_owners'][0][1] = -1
            elif kind == 'pack_residency':
                composition['pack_resident_bytes'] = 0
            elif kind == 'pack_storage':
                doc['sources']['rockport']['pack_storage'] = []
            else:
                composition['groups'].pop()
            with self.subTest(kind=kind), self.assertRaises(FormatError):
                c1.check(doc)

    def test_cli_serialized_plan_summary_and_output_guard(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'plan.json'
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(c1.main(['--out', str(path)]), 0)
            self.assertEqual(len(output.getvalue().splitlines()), 15)
            self.assertLess(len(output.getvalue()), 10000)
            self.assertTrue(c1.check(json.loads(path.read_text()))['feasible'])
            # Refuse overwriting an existing result or any checkout file.
            with redirect_stderr(io.StringIO()):
                self.assertEqual(c1.main(['--out', str(path)]), 1)
                self.assertEqual(c1.main(['--out', str(HERE / 'should-not-exist.json')]), 1)
            self.assertFalse((HERE / 'should-not-exist.json').exists())


if __name__ == '__main__':
    result = unittest.main(exit=False, verbosity=2).result
    raise SystemExit(1 if not result.wasSuccessful() else 0 if ASSETS else 3)
