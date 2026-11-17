"""Global tables: empty scaffold 0/0/0 -> 705 zones/328 markers/1376 barriers.

Native re-encoding: 3/3 byte-identical; valid converted tables 1/1 accepted.
Broken controls: split native/source type ranges, vertex count +1, missed
selector retarget to 2600, barrier one byte short: each 0/1 accepted (4/4
rejected). Source order itself is valid (1/1 accepted); all nine original
selectors already equal the default 2000, so the selector control uses 2600.
The current whole-world checker rejects the extra marker scaffold kind;
that separately owned integration is recorded as a real rejection, not PASS.
Synthetic checks run without private assets; the script then exits 3.
"""
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import math
from pathlib import Path
import struct
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(HERE))
import zones as z
from formats import Chunk, FormatError, TrackIndex, chunks, encode_chunks, u32

ASSETS = all(path.is_file() for path in (z.DEFAULT_MW / 'L2RA.BUN',
    z.DEFAULT_CARBON / 'L5RA.BUN', z.DEFAULT_CARBON.parent / 'GLOBAL/attributes.bin'))
WORLD_ASSETS = ASSETS and all((root / name).is_file()
    for root, names in ((z.DEFAULT_MW, ('STREAML2RA.BUN',)),
                        (z.DEFAULT_CARBON, ('STREAML5RA.BUN', 'L5RB.BUN', 'STREAML5RB.BUN')))
    for name in names)


def polygon(kind=9, key=0x12345678):
    header = bytearray(68)
    struct.pack_into('<I5f', header, 0, kind, -0.0, 1.25, 0.5, -0.5, 42)
    struct.pack_into('<4f', header, 32, -1.5, -2.25, 3.5, 4.25)
    struct.pack_into('<4I', header, 48, key, 17, 18, 19)
    struct.pack_into('<hh', header, 64, 4, 100)
    return bytes(header) + struct.pack('<8f', -1.5, -2.25, 3.5, -2.25, 3.5, 4.25, -1.5, 4.25)


def fixture(order=(9, 3, 9), *, offset=0):
    marker = bytearray(48)
    struct.pack_into('<4I', marker, 0, 11, 11, 0x12345678, 7)
    struct.pack_into('<4f', marker, 16, -0.0, 2.25, 3.5, -0.0)
    struct.pack_into('<II', marker, 32, 0xaabbccdd, 2000)
    barrier = struct.pack('<4fII', -0.0, 2.25, 3.5, -1.5, 0x11223344, 0x12345678)
    return (Chunk(z.ZONES, Chunk(z.POLYGONS, b''.join(polygon(k) for k in order)).encode()),
            Chunk(z.MARKERS, b'\x11' * (-(offset + 8) % 16) + marker, offset),
            Chunk(z.BARRIERS, barrier))


def index_of(parts):
    class Index:
        pass
    index = Index()
    index.parts = list(parts)
    return index


def replace_part(parts, kind, payload):
    return tuple(Chunk(c.kind, payload, c.offset) if c.kind == kind else c for c in parts)


def replace_polygons(parts, raw):
    return replace_part(parts, z.ZONES, Chunk(z.POLYGONS, raw).encode())


class SyntheticTests(unittest.TestCase):
    def test_sort_and_rebuild_18_ranges(self):
        output = z.convert(index_of(fixture()))
        measured = z.check(output)
        self.assertEqual([r['count'] for r in measured['ranges']],
                         [0, 0, 0, 1, 0, 0, 0, 0, 0, 2, 0, 0, 0, 0, 0, 0, 0, 0])
        self.assertEqual(measured['ranges'][9], dict(type=9, count=2, first=100, end=300))
        with self.assertRaisesRegex(FormatError, 'first/last'):
            z.check(fixture())
        # Source data already grouped by type must remain accepted.
        z.check(fixture((3, 9, 9)))

    def test_identity_preserves_float_bits_and_opaque_words(self):
        source = fixture((3, 6, 9, 11), offset=4)
        output = z.convert(index_of(source))
        before, after = z.read(source), z.read(output)
        self.assertEqual([r.encode() for r in before.zones], [r.encode() for r in after.zones])
        self.assertEqual(before.markers, after.markers)
        self.assertEqual(before.barriers, after.barriers)
        self.assertEqual(after.zones[0].header[4:8], struct.pack('<f', -0.0))

    def test_reencoding_retains_absolute_marker_padding(self):
        for offset in (0, 4, 8, 12, 16):
            parts = fixture((3, 9), offset=offset)
            rebuilt = z.read(parts).encode()
            self.assertEqual([c.encode() for c in rebuilt], [c.encode() for c in parts])
            self.assertEqual(len(z.read(rebuilt).markers), 1)

    def test_shift_uses_physics_to_planar_basis(self):
        source = fixture((9,))
        shifted = z.read(z.convert(index_of(source), shift=(16, 32)))
        before = z.read(source)
        # Physics (X+16,Z+32) becomes planar (x+32,y-16).
        self.assertEqual(shifted.zones[0].vertices,
                         tuple((x + 32, y - 16) for x, y in before.zones[0].vertices))
        self.assertEqual(struct.unpack_from('<3f', shifted.markers[0], 16), (32, -13.75, 3.5))
        self.assertEqual(struct.unpack_from('<4f', shifted.barriers[0]), (32, -13.75, 35.5, -17.5))
        self.assertEqual(shifted.zones[0].header[12:32], before.zones[0].header[12:32])
        self.assertEqual(shifted.markers[0][24:], before.markers[0][24:])
        self.assertEqual(shifted.barriers[0][16:], before.barriers[0][16:])

    def test_rekey_only_decoded_hash_fields_and_retarget_selectors(self):
        source = fixture((6, 9, 11))
        output = z.convert(index_of(source), track=2600, key_map={0x12345678: 0x87654321, 17: 99})
        table = z.read(output)
        self.assertEqual([r.key for r in table.zones], [0x12345678, 0x87654321, 0x87654321])
        self.assertTrue(all(u32(r.header, 52) == 17 for r in table.zones))
        self.assertEqual((u32(table.markers[0], 8), u32(table.markers[0], 12)), (0x87654321, 7))
        self.assertEqual(u32(table.barriers[0], 20), 0x87654321)
        z.check(output, track=2600)
        bad = bytearray(output[1].payload)
        struct.pack_into('<I', bad, 8 + 36, 2000)
        with self.assertRaisesRegex(FormatError, 'foreign track'):
            z.check(replace_part(output, z.MARKERS, bytes(bad)), track=2600)
        wildcard = bytearray(source[1].payload)
        struct.pack_into('<I', wildcard, 8 + 36, 0)
        out = z.convert(index_of(replace_part(source, z.MARKERS, bytes(wildcard))), track=2600)
        self.assertEqual(u32(z.read(out).markers[0], 36), 0)

    def test_broken_extents_and_geometry_fail(self):
        parts = z.convert(index_of(fixture((3, 9))))
        raw = bytearray(b''.join(row.encode() for row in z.read(parts).zones))
        struct.pack_into('<h', raw, 64, 5)
        with self.assertRaisesRegex(FormatError, 'count.*stride'):
            z.check(replace_polygons(parts, bytes(raw)))
        with self.assertRaisesRegex(FormatError, 'partial barrier'):
            z.check(replace_part(parts, z.BARRIERS, parts[2].payload[:-1]))
        with self.assertRaisesRegex(FormatError, 'partial marker'):
            z.check(replace_part(parts, z.MARKERS, parts[1].payload[:-1]))
        raw = bytearray(b''.join(row.encode() for row in z.read(parts).zones))
        struct.pack_into('<f', raw, 68, 1000)
        with self.assertRaisesRegex(FormatError, 'outside stored bounds'):
            z.check(replace_polygons(parts, bytes(raw)))
        struct.pack_into('<f', raw, 68, math.nan)
        with self.assertRaisesRegex(FormatError, 'nonfinite'):
            z.check(replace_polygons(parts, bytes(raw)))

    def test_reject_signed_counts_duplicate_chunks_and_unknown_types(self):
        parts = fixture((3,))
        raw = bytearray(z.read(parts).zones[0].encode())
        for off, value in ((64, -1), (66, -100)):
            bad = bytearray(raw)
            struct.pack_into('<h', bad, off, value)
            with self.assertRaises(FormatError):
                z.check(replace_polygons(parts, bytes(bad)))
        with self.assertRaises(FormatError):
            z.check(parts + (parts[0],))
        with self.assertRaisesRegex(FormatError, '18 buckets'):
            z.check(fixture((18,)))
        with self.assertRaisesRegex(FormatError, '15 buckets'):
            z.convert(index_of(fixture((15,))))
        for kwargs in (dict(shift=(math.nan, 0)), dict(track=32768), dict(key_map={1: -1})):
            with self.assertRaises(FormatError):
                z.convert(index_of(parts), **kwargs)

    def test_insert_markers_preserves_all_later_alignments_and_payloads(self):
        # Include a 4-byte growth delta to exercise the small-padding case.
        for extra in (b'', bytes(4), bytes(120), bytes(128)):
            empty = Chunk(z.POLYGONS, b'').encode()
            baseline = encode_chunks((Chunk(z.ZONES, empty), Chunk(0, bytes(8)),
                Chunk(0x34110, b''), Chunk(0xabc, extra), Chunk(z.BARRIERS, b''),
                Chunk(0xdef, b'opaque later contents')))
            converted = z.convert(index_of(fixture((3, 9))))
            rewritten = z.rewrite_index(baseline, converted)
            before, after = chunks(baseline), chunks(rewritten)
            for old in before:
                if old.kind == 0:
                    continue
                new = next(c for c in after if c.kind == old.kind)
                self.assertEqual(old.offset % 128, new.offset % 128)
                if old.kind not in (z.ZONES, z.BARRIERS):
                    self.assertEqual(old.payload, new.payload)
            marker = next(c for c in after if c.kind == z.MARKERS)
            self.assertEqual(marker.offset % 16, 0)
            self.assertEqual([c.kind for c in after if c.kind][:2], [z.ZONES, z.MARKERS])
            self.assertEqual(z.check(z.select(TrackIndex(rewritten)))['zones'], 2)
            self.assertEqual(TrackIndex(rewritten).encode(), rewritten)
            alternate = z.convert(index_of(fixture((3, 9))), track=2600)
            changed_track = z.rewrite_index(baseline, alternate, track=2600)
            z.check(z.select(TrackIndex(changed_track)), track=2600)

    def test_district_search_is_aligned_and_labelled_as_lead(self):
        key = struct.pack('<I', 0x12345678)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'attributes.bin'
            path.write_bytes(b'x' + key + bytes(3))
            row, = z.districts(index_of(fixture((9,))), path)
            self.assertFalse(row['carbon_aligned_raw_occurrence'])
            path.write_bytes(bytes(4) + key)
            row, = z.districts(index_of(fixture((9,))), path)
            self.assertTrue(row['carbon_aligned_raw_occurrence'])
            self.assertIn('binding unproved', row['meaning'])

    def test_missing_private_assets_exit_three_and_no_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with redirect_stderr(io.StringIO()) as err:
                code = z.main(['--districts', '--mw-root', str(root / 'absent')])
            self.assertEqual(code, 3)
            self.assertIn('private assets absent', err.getvalue())


@unittest.skipUnless(ASSETS, 'private global-table assets absent')
class ArchiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = TrackIndex((z.DEFAULT_MW / 'L2RA.BUN').read_bytes())
        cls.native = TrackIndex((z.DEFAULT_CARBON / 'L5RA.BUN').read_bytes())
        cls.converted = z.convert(cls.source)

    def test_native_roundtrip_three_of_three_and_exact_walk_counts(self):
        for index, expected in ((self.source, (705, 328, 1376)), (self.native, (442, 155, 1238))):
            parts = z.select(index)
            table = z.read(parts)
            self.assertEqual(tuple(map(len, (table.zones, table.markers, table.barriers))), expected)
            self.assertEqual([c.encode() for c in table.encode()], [c.encode() for c in parts])
            checked = z.check(parts)
            self.assertEqual(tuple(checked[k] for k in ('zones', 'markers', 'barriers')), expected)

    def test_converted_counts_identity_and_type_capacity(self):
        before, after = z.read(z.select(self.source)), z.read(self.converted)
        self.assertEqual([r.encode() for r in before.zones], [r.encode() for r in after.zones])
        self.assertEqual(before.markers, after.markers)
        self.assertEqual(before.barriers, after.barriers)
        checked = z.check(self.converted)
        self.assertEqual(tuple(checked[k] for k in ('zones', 'markers', 'barriers')), (705, 328, 1376))
        self.assertEqual(len(checked['ranges']), 18)
        self.assertEqual([r['count'] for r in checked['ranges'][15:]], [0, 0, 0])
        self.assertEqual(sum(u32(r, 36) != 0 for r in before.markers), 9)

    def test_all_shifted_components_float32_and_opaque_bytes(self):
        for shift in ((20480, 0), (0, 20480), (123.25, -456.5)):
            before = z.read(self.converted)
            after = z.read(z.convert(self.source, shift=shift))
            pairs = []
            for old, new in zip(before.zones, after.zones):
                offsets = (4, 8, 32, 36, 40, 44, *range(68, len(old.encode()), 4))
                pairs.append((old.encode(), new.encode(), offsets))
            pairs.extend((a, b, (16, 20)) for a, b in zip(before.markers, after.markers))
            pairs.extend((a, b, (0, 4, 8, 12)) for a, b in zip(before.barriers, after.barriers))
            tested, maximum_error = 0, 0
            for old, new, offsets in pairs:
                expected = bytearray(old)
                for i, off in enumerate(offsets):
                    delta = shift[1] if i % 2 == 0 else -shift[0]
                    value = struct.unpack_from('<f', old, off)[0]
                    if delta:
                        struct.pack_into('<f', expected, off, value + delta)
                    actual = struct.unpack_from('<f', new, off)[0]
                    maximum_error = max(maximum_error, abs(actual - value - delta))
                    tested += 1
                self.assertEqual(new, expected)
            self.assertEqual(tested, 17062)
            self.assertLessEqual(maximum_error, 0.001953125)

    def test_four_broken_archive_variants_rejected_and_source_order_valid(self):
        source = z.read(z.select(self.source))
        native = z.read(z.select(self.native))
        # The brief's source-order control is valid. A real concatenation
        # repeats shared type groups and breaks the loader's first/end ranges.
        z.check(z.select(self.source))
        combined = b''.join(r.encode() for r in (*native.zones, *source.zones))
        with self.assertRaisesRegex(FormatError, 'first/last'):
            z.check(replace_polygons(self.converted, combined))
        raw = bytearray(b''.join(r.encode() for r in source.zones))
        count = struct.unpack_from('<h', raw, 64)[0]
        struct.pack_into('<h', raw, 64, count + 1)
        with self.assertRaisesRegex(FormatError, 'count.*stride'):
            z.check(replace_polygons(self.converted, bytes(raw)))
        destination = z.convert(self.source, track=2600)
        marker = bytearray(destination[1].payload)
        selected = next(i for i, r in enumerate(z.read(destination).markers) if u32(r, 36))
        struct.pack_into('<I', marker, 8 + selected * 48 + 36, 2000)
        with self.assertRaisesRegex(FormatError, 'foreign track'):
            z.check(replace_part(destination, z.MARKERS, bytes(marker)), track=2600)
        with self.assertRaisesRegex(FormatError, 'partial barrier'):
            z.check(replace_part(self.converted, z.BARRIERS, self.converted[2].payload[:-1]))

    def test_eleven_districts_zero_raw_carbon_key_occurrences(self):
        rows = z.districts(self.source, z.DEFAULT_CARBON.parent / 'GLOBAL/attributes.bin')
        self.assertEqual(len(rows), 11)
        self.assertEqual(sum(row['carbon_aligned_raw_occurrence'] for row in rows), 0)
        with redirect_stdout(io.StringIO()) as out:
            self.assertEqual(z.main(['--districts']), 0)
        self.assertIn('raw-search lead', out.getvalue())


@unittest.skipUnless(WORLD_ASSETS, 'private whole-world assets absent')
class WorldTests(unittest.TestCase):
    def test_written_pair_and_actual_world_cli_integration(self):
        import rockport_world
        with tempfile.TemporaryDirectory(prefix='zones-world-') as directory:
            root = Path(directory)
            baseline, output = root / 'baseline', root / 'converted'
            rockport_world.prepare(baseline)
            before = TrackIndex((baseline / 'TRACKS/L2RA.BUN').read_bytes())
            self.assertEqual(len(next(c for c in before.parts if c.kind == z.ZONES).payload), 8)
            self.assertFalse(any(c.kind == z.MARKERS for c in before.parts))
            self.assertEqual(len(next(c for c in before.parts if c.kind == z.BARRIERS).payload), 0)
            # Exercise the public CLI, including the real world --check subprocess.
            with redirect_stdout(io.StringIO()) as out:
                code = z.main(['--into', str(baseline), '--out', str(output)])
            import json
            report = json.loads(out.getvalue())
            self.assertEqual(report['counts'], dict(zones=705, markers=328, barriers=1376))
            written = (output / 'TRACKS/L2RA.BUN').read_bytes()
            self.assertEqual(report['index_bytes'], len(written))
            self.assertEqual(report['index_sha256'], hashlib.sha256(written).hexdigest())
            # Every original envelope, including padding, survives in order.
            # Skip only newly inserted padding and the new marker envelope.
            after = iter(chunks(written))
            for old in before.parts:
                new = next(c for c in after if c.kind == old.kind
                           and c.offset % 128 == old.offset % 128
                           and (old.kind in (z.ZONES, z.BARRIERS) or c.payload == old.payload))
                self.assertEqual(old.offset % 128, new.offset % 128)
                if old.kind not in (z.ZONES, z.BARRIERS):
                    self.assertEqual(new.payload, old.payload)
            self.assertEqual((baseline / 'TRACKS/STREAML2RA.BUN').read_bytes(),
                             (output / 'TRACKS/STREAML2RA.BUN').read_bytes())
            self.assertFalse((output / 'proof.json').exists())
            self.assertTrue((output / 'zones-proof.json').exists())
            # The owned integration can later accept these chunks. Today its
            # exact-scaffold rule must reject them; do not disguise that fact.
            if report['world_check']['returncode']:
                self.assertEqual(code, 1)
                self.assertIn('index scaffold kinds/order differ', report['world_check']['stderr'])
            else:
                self.assertEqual(code, 0)


if __name__ == '__main__':
    result = unittest.main(exit=False)
    raise SystemExit(1 if not result.result.wasSuccessful() else 0 if WORLD_ASSETS else 3)
