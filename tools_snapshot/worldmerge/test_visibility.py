"""Visibility proof: baseline 0 converted zones; accepted 373/515/435.
Valid checker 1/1; missing drivable row, 36-byte boundary header and lowered cap:
broken checker 0/3 accepted (3/3 rejected), on synthetic AND private payloads.
Read-back geometry differences 0; headers/spare/multisets equal; native 131308 bytes exact.
Provider-first: 378/435 rows changed, 1190 -> 0 late V placements; verbatim
retains source row bytes. Dropped-entry and scenery-before-V controls: 0/2
accepted versus 1/1 intact, both synthetic and private serialized payloads.
Absent references: 4052 scenery + 1481 resources = 5533 of 16265, source unchanged.
Synthetic checks always run; missing private index archives exit 3. No game runs.
"""
from dataclasses import replace
from collections import Counter
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(HERE))
import visibility as v
from formats import Chunk, FormatError, TrackIndex, chunks, encode_chunks

ASSETS = all(p.is_file() for p in (v.DEFAULT_MW, v.DEFAULT_CARBON))


def fixture():
    """An older table with an existing absent scenery/resource pair."""
    boundary = bytearray(36)
    struct.pack_into('<hBB6f', boundary, 8, 101, 4, 0, -2., -1., 2., 1., -0., 0.)
    boundary += struct.pack('<8f', -2., -1., 2., -1., 2., 1., -2., 1.)
    row = bytearray(28)
    struct.pack_into('<hBBhhhh', row, 12, 101, 3, 4, 3, 141, 102, 2251)
    # Retain nonzero unused slots and row spare bytes, too.
    drive = struct.pack('<II4h', 40, 2, 101, 101, 777, 888)
    row[-2:] = b'xy'
    payload = encode_chunks([Chunk(v.DRIVE, drive), Chunk(v.BOUNDARIES, bytes(boundary)),
                             Chunk(v.LOADING, bytes(76)), Chunk(v.ROWS, bytes(row))])
    record = bytearray(92)
    struct.pack_into('<h', record, 8, 141)
    return TrackIndex(encode_chunks([Chunk(v.CONTAINER, payload), Chunk(0x34110, bytes(record))]))


def rewrite(payload, kind, edit):
    return encode_chunks(Chunk(c.kind, edit(c.payload) if c.kind == kind else c.payload)
                         for c in chunks(payload))


def broken(payload, variant):
    """Mutate actual serialized output, never a converter intermediate."""
    if variant == 'missing_drivable_row':
        parts = {c.kind: c.payload for c in chunks(payload)}
        number = struct.unpack_from('<h', parts[v.DRIVE], 8)[0]
        raw = parts[v.ROWS]
        p, kept = 0, []
        while p < len(raw):
            end = p + 20 + raw[p + 15] * 2
            if struct.unpack_from('<h', raw, p + 12)[0] != number:
                kept.append(raw[p:end])
            p = end
        return rewrite(payload, v.ROWS, lambda _: b''.join(kept))
    if variant == 'short_boundary_header':
        return rewrite(payload, v.BOUNDARIES, lambda b: b[:12] + b[24:])
    if variant == 'lowered_cap':
        def lower(raw):
            out = bytearray(raw)
            count = struct.unpack_from('<h', out, 16)[0]
            assert count > 0
            out[15] = count - 1
            return bytes(out)
        return rewrite(payload, v.ROWS, lower)
    raise ValueError(variant)


VARIANTS = (('missing_drivable_row', 'without a row'),
            ('short_boundary_header', 'boundary'),
            ('lowered_cap', 'count exceeds signed cap'))


class SyntheticTests(unittest.TestCase):
    def setUp(self):
        self.source = fixture()
        self.payload = v.convert(self.source)

    def check(self, payload=None, numbers=(141,)):
        return v.check(self.payload if payload is None else payload, numbers, source_index=self.source)

    def test_acceptance_and_three_broken_controls(self):
        report = self.check()
        self.assertEqual((report['drivable'], report['boundaries'], report['rows']), (2, 1, 1))
        self.assertEqual(report['absent_entries'], 2)
        self.assertEqual(report['absent_scenery_entries'], 1)
        self.assertEqual(report['absent_resource_entries'], 1)
        self.assertTrue(report['absent_entries_equal_source'])
        for variant, reason in VARIANTS:
            with self.subTest(variant=variant), self.assertRaisesRegex(FormatError, reason):
                self.check(broken(self.payload, variant))

    def test_padded_slots_rows_geometry_and_alignment(self):
        source = v.read(v.payload_of(self.source), extended=False)
        out = v.read(self.payload)
        self.assertEqual(out.slots[:4], (101, 101, 777, 888))
        self.assertEqual(out.slots[4:], (0,) * 508)
        self.assertEqual(out.drivable, source.drivable)
        self.assertEqual(out.boundaries[0].raw[:12], source.boundaries[0].raw[:12])
        self.assertEqual(out.boundaries[0].raw[12:24], bytes(12))
        self.assertEqual(out.boundaries[0].raw[24:], source.boundaries[0].raw[12:])
        self.assertEqual(out.rows[0].entries, (2251, 141, 102))
        self.assertEqual(out.rows[0].header, source.rows[0].header)
        self.assertEqual(out.rows[0].spare, source.rows[0].spare)
        selector = next(c for c in out.parts if c.kind == v.SELECTORS)
        self.assertEqual((selector.offset + 8 + len(out.selector_padding)) % 16, 0)
        self.assertFalse(out.selectors)
        self.assertFalse(out.loading)
        self.assertEqual(out.encode(), self.payload)

    def test_stable_partition_preserves_duplicates_and_other_entries(self):
        entries = (2400, 101, 2251, 2600, 2251, 102, 2201, 2500)
        self.assertEqual(v.ordered_entries(entries, 'providers-first'),
                         (2251, 2251, 2201, 2400, 101, 2600, 102, 2500))
        self.assertEqual(v.ordered_entries(entries, 'verbatim'), entries)

    def test_dropped_entry_and_wrong_order_rejected(self):
        table = v.read(self.payload)
        row = table.rows[0]
        # Keep stride valid while dropping an entry: the checker must compare
        # multisets, rather than relying on row parsing or the absence check.
        header = bytearray(row.header)
        struct.pack_into('<h', header, 16, len(row.entries) - 1)
        dropped = replace(row, header=bytes(header), entries=row.entries[:-1],
                          spare=b'\0\0' + row.spare)
        with self.assertRaisesRegex(FormatError, 'entry multiset changed'):
            self.check(replace(table, rows=(dropped,)).encode())
        wrong = replace(row, entries=(141, 2251, 102))
        with self.assertRaisesRegex(FormatError, 'V-resource after scenery'):
            self.check(replace(table, rows=(wrong,)).encode())
        verbatim = v.convert(self.source, rows='verbatim')
        v.check(verbatim, [141], source_index=self.source, rows='verbatim')
        self.assertEqual(v.read(verbatim).rows, v.read(v.payload_of(self.source), extended=False).rows)

    def test_native_encoder_uses_decoded_fields(self):
        table = v.read(self.payload)
        changed_slots = (102,) + table.slots[1:]
        encoded = replace(table, slots=changed_slots).encode()
        self.assertNotEqual(encoded, self.payload)
        self.assertEqual(v.read(encoded).drivable[0], 102)
        row = replace(table.rows[0], entries=(141, 103, 2251))
        encoded = replace(table, rows=(row,)).encode()
        self.assertEqual(v.read(encoded).rows[0].entries, (141, 103, 2251))

    def test_absence_is_row_specific_and_multiplicity_bounded(self):
        # Removing a real stream record must not turn into an allowed absence.
        with self.assertRaisesRegex(FormatError, 'new absent row entries'):
            self.check(numbers=())
        for offset, number in ((20, 103), (18, 102)):
            def edit(raw):
                out = bytearray(raw)
                struct.pack_into('<h', out, offset, number)
                return bytes(out)
            with self.subTest(offset=offset), self.assertRaisesRegex(FormatError, 'new absent row entries'):
                self.check(rewrite(self.payload, v.ROWS, edit))

    def test_missing_boundary_rejected(self):
        def edit(raw):
            out = bytearray(raw)
            struct.pack_into('<h', out, 8, 102)
            return bytes(out)
        with self.assertRaisesRegex(FormatError, 'without a boundary'):
            self.check(rewrite(self.payload, v.BOUNDARIES, edit))

    def test_drivable_boundary_outside_slot_array_still_needs_row(self):
        # Position lookup can reach this polygon even without a drivable slot.
        table = v.read(self.payload)
        raw = bytearray(table.boundaries[0].raw)
        struct.pack_into('<h', raw, 8, 103)
        payload = rewrite(self.payload, v.BOUNDARIES, lambda old: old + bytes(raw))
        with self.assertRaisesRegex(FormatError, 'without a row'):
            self.check(payload)

    def test_row_budget_signed_cap_and_extents(self):
        for field, value, reason in ((16, 385, '384-entry'), (16, -1, '384-entry'),
                                     (15, 128, 'signed cap'), (15, 127, 'crosses chunk')):
            def edit(raw):
                out = bytearray(raw)
                struct.pack_into('<h' if field == 16 else '<B', out, field, value)
                return bytes(out)
            with self.subTest(field=field, value=value), self.assertRaisesRegex(FormatError, reason):
                self.check(rewrite(self.payload, v.ROWS, edit))

    def test_directory_and_drivable_bounds(self):
        raw_parts = list(chunks(self.payload))
        with self.assertRaisesRegex(FormatError, 'duplicate visibility child'):
            self.check(self.payload + raw_parts[0].encode())
        with self.assertRaisesRegex(FormatError, 'missing visibility child'):
            self.check(encode_chunks(c for c in raw_parts if c.kind != v.SELECTORS))
        for count in (513, 0xffffffff):
            def edit(raw):
                return raw[:4] + struct.pack('<I', count) + raw[8:]
            with self.subTest(count=count), self.assertRaisesRegex(FormatError, 'slot array'):
                self.check(rewrite(self.payload, v.DRIVE, edit))
        with self.assertRaisesRegex(FormatError, 'crosses parent'):
            self.check(self.payload[:-1])

    def test_empty_aligned_selector_extent(self):
        # End before the loader's aligned data pointer would produce a bad count.
        for size, reason in ((0, 'selector alignment'), (9, 'selector record')):
            if size == 0 and not v.read(self.payload).selector_padding:
                continue
            with self.subTest(size=size), self.assertRaisesRegex(FormatError, reason):
                self.check(rewrite(self.payload, v.SELECTORS, lambda _: bytes(size)))

    def test_default_source_and_missing_archives(self):
        with tempfile.TemporaryDirectory(prefix='visibility-missing-') as temp:
            root = Path(temp)
            self.assertEqual(v.main(['--check', '--mw-index', str(root / 'source'),
                                     '--carbon-index', str(root / 'native')]), 3)
            source = root / 'source'
            source.write_bytes(self.source.encode())
            with patch.object(v, 'DEFAULT_MW', source):
                self.assertEqual(v.check(self.payload, [141])['absent_entries'], 2)


@unittest.skipUnless(ASSETS, 'private visibility indexes absent')
class PrivateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = TrackIndex(v.DEFAULT_MW.read_bytes())
        cls.native = TrackIndex(v.DEFAULT_CARBON.read_bytes())
        cls.payload = v.convert(cls.source)

    def test_counts_and_native_roundtrip(self):
        report = v.proof(self.source, self.native)
        self.assertEqual(report['source_counts'], [373, 515, 435, 39])
        self.assertEqual(report['native_counts'], [450, 642, 572, 94])
        self.assertEqual((report['drivable'], report['boundaries'], report['rows']), (373, 515, 435))
        self.assertEqual(report['lod_offset'], 40)
        self.assertEqual(report['drivable_without_row'], 0)
        self.assertEqual(report['largest_row'], 68)
        self.assertLessEqual(report['largest_row'], 384)
        self.assertEqual(report['row_entries'], 16265)
        self.assertEqual(report['absent_scenery_entries'], 4052)
        self.assertEqual(report['absent_resource_entries'], 1481)
        self.assertEqual(report['absent_entries'], 5533)
        self.assertTrue(report['absent_entries_equal_source'])
        self.assertEqual(report['native_payload_bytes'], 131308)
        self.assertTrue(report['native_roundtrip_byte_exact'])
        self.assertEqual(report['boundary_differences'], 0)
        self.assertFalse(report['rows_byte_identical'])
        self.assertTrue(report['row_multisets_equal'])
        self.assertEqual((report['rows_changed'], report['v_after_scenery_before'],
                          report['v_after_scenery']), (378, 1190, 0))
        self.assertTrue(v.proof(self.source, self.native, rows='verbatim')['rows_byte_identical'])

    def test_private_order_and_multiset_negative_controls(self):
        table = v.read(self.payload)
        i = next(i for i, r in enumerate(table.rows) if r.number == 811)
        row = table.rows[i]
        header = bytearray(row.header)
        struct.pack_into('<h', header, 16, len(row.entries) - 1)
        dropped = replace(row, header=bytes(header), entries=row.entries[:-1], spare=b'\0\0' + row.spare)
        wrong_entries = list(row.entries)
        a = next(j for j, n in enumerate(wrong_entries) if n // 100 == 22)
        b = next(j for j, n in enumerate(wrong_entries) if 100 <= n < 2100)
        wrong_entries[a], wrong_entries[b] = wrong_entries[b], wrong_entries[a]
        for broken, reason in ((dropped, 'entry multiset changed'),
                               (replace(row, entries=tuple(wrong_entries)), 'V-resource after scenery')):
            rows = list(table.rows)
            rows[i] = broken
            with self.assertRaisesRegex(FormatError, reason):
                v.check(replace(table, rows=tuple(rows)).encode(),
                        [s.number for s in self.source.sections], source_index=self.source)

    def test_three_broken_private_controls(self):
        numbers = [s.number for s in self.source.sections]
        for variant, reason in VARIANTS:
            with self.subTest(variant=variant), self.assertRaisesRegex(FormatError, reason):
                v.check(broken(self.payload, variant), numbers, source_index=self.source)

    def test_independent_byte_walk_of_every_polygon_bound_and_row(self):
        def children(payload):
            result, p = {}, 0
            while p < len(payload):
                kind, size = struct.unpack_from('<II', payload, p)
                self.assertLessEqual(p + 8 + size, len(payload))
                result[kind] = payload[p + 8:p + 8 + size]
                p += 8 + size
            self.assertEqual(p, len(payload))
            return result
        src = children(v.payload_of(self.source))
        dst = children(self.payload)
        # Walk serialized rows independently of the ordering helper/checker.
        p = q = changed = 0
        while p < len(src[v.ROWS]):
            a, b = src[v.ROWS], dst[v.ROWS]
            count = struct.unpack_from('<h', a, p + 16)[0]
            stride = 20 + 2 * a[p + 15]
            self.assertEqual(a[p:p+18], b[q:q+18])
            old = struct.unpack_from(f'<{count}h', a, p + 18)
            new = struct.unpack_from(f'<{count}h', b, q + 18)
            self.assertEqual(Counter(old), Counter(new))
            self.assertEqual(a[p+18+count*2:p+stride], b[q+18+count*2:q+stride])
            self.assertEqual(tuple(n for n in old if 2200 <= n < 2300),
                             tuple(n for n in new if 2200 <= n < 2300))
            self.assertEqual(tuple(n for n in old if not 2200 <= n < 2300),
                             tuple(n for n in new if not 2200 <= n < 2300))
            self.assertFalse(any(100 <= n < 2100 for j, n in enumerate(new)
                                 if any(2200 <= x < 2300 for x in new[j+1:])))
            changed += old != new
            p += stride
            q += stride
        self.assertEqual((p, q, changed), (len(src[v.ROWS]), len(dst[v.ROWS]), 378))
        a, b, differences, count = src[v.BOUNDARIES], dst[v.BOUNDARIES], 0, 0
        p, q = 0, 0
        while p < len(a):
            nv = a[p + 10]
            self.assertEqual(a[p + 8:p + 12], b[q + 8:q + 12])
            self.assertEqual(b[q + 12:q + 24], bytes(12))
            old = a[p + 12:p + 36 + nv * 8]
            new = b[q + 24:q + 48 + nv * 8]
            differences += sum(x != y for x, y in zip(struct.unpack(f'<{len(old)//4}f', old),
                                                       struct.unpack(f'<{len(new)//4}f', new)))
            self.assertEqual(old, new)  # also preserve float bit patterns, including signed zero
            p += 36 + nv * 8
            q += 48 + nv * 8
            count += 1
        self.assertEqual((p, q, count, differences), (len(a), len(b), 515, 0))
        # Native control must retain the five nonzero alternate-zone/hash headers.
        native = v.read(v.payload_of(self.native))
        self.assertEqual([b.number for b in native.boundaries if any(b.raw[12:24])],
                         [514, 606, 628, 903, 1038])


if __name__ == '__main__':
    result = unittest.main(exit=False, verbosity=2).result
    raise SystemExit(1 if not result.wasSuccessful() else 0 if ASSETS else 3)
