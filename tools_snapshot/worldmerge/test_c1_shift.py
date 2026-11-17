"""Render XY proof: baseline 0/720 records placeable on Y -> 720/720.

Independent float32/whole-byte oracle; all 515 boundaries must also translate.
The nearby physics shift (4096,-8192) is also checked as render (-8192,-4096):
30/30 synthetic spatial components match, with untouched height/other bytes.
Intact -> broken controls: wrong axis 720/720 -> 114/720 pass (606 rejected,
618978 scalar fields differ, including boundaries); events 415/415 -> 0/415;
boundaries 515/515 -> 0/515; non-periodic precull 606/606 accepted before the
guard -> 0/606 accepted. Synthetic controls each accept 1/1 good and 0/1 bad.
Synthetic controls always run; missing private archives exits 3 afterwards.
"""
from collections import Counter
import json
import math
from pathlib import Path
import struct
import sys
import unittest

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(HERE))
import classify
import convert
import emitters
import events
import formats
import texanim
import validate
from merge import DEFAULT_MW, load_index, read_section
from test_scenery2 import fixture, with_events
from test_emitters import synthetic as emitter_fixture

ASSETS = all((DEFAULT_MW / n).is_file() for n in ('L2RA.BUN', 'STREAML2RA.BUN'))
SHIFT = (0, -20480)


def body_offset(chunk):
    return (chunk.offset + 23) & ~15


def fields(data):
    """Target offsets decoded from disk strides, independent of writer helpers.

    Yield one world XYZ vector for each bound endpoint/center/translation.
    Extents, rotations, radii and model-local geometry are excluded.
    """
    result = []
    for root in formats.chunks(data):
        if root.kind == 0x80034100:
            for part in formats.chunks(root.payload, root.offset + 8):
                if part.kind not in (0x34103, 0x34105):
                    continue
                start, end = body_offset(part), part.offset + 8 + len(part.payload)
                stride, offsets, family = ((96, (0, 16, 32), 'instances') if part.kind == 0x34103
                                           else (48, (0, 16), 'tree_nodes'))
                formats.require((end - start) % stride == 0, 'oracle scenery stride')
                result.extend((family, p + q) for p in range(start, end, stride) for q in offsets)
        elif root.kind == 0x3bc00:
            start = body_offset(root)
            count, = struct.unpack_from('<I', data, start + 8)
            p = start + 16
            for _ in range(count):
                triggers, = struct.unpack_from('<H', data, p + 10)
                result.append(('emitters', p + 64))
                p += 80
                result.extend(('emitter_triggers', p + 48 * i + 16) for i in range(triggers))
                p += 48 * triggers
            formats.require(p == root.offset + 8 + len(root.payload), 'oracle emitter extent')
        elif root.kind == 0x80036000:
            for part in formats.chunks(root.payload, root.offset + 8):
                if part.kind not in (0x36002, 0x36003):
                    continue
                start, end = body_offset(part) + 16, part.offset + 8 + len(part.payload)
                stride = 48 if part.kind == 0x36002 else 32
                if part.kind == 0x36003:
                    end += 16  # sphere center +16, rather than a tree header
                formats.require((end - start) % stride == 0, 'oracle event stride')
                result.extend(('event_nodes' if stride == 48 else 'event_spheres', p)
                              for p in range(start, end, stride))
    return result


def expected_bytes(before, locations, shift, dimensions=3):
    expected, maximum = bytearray(before), 0.
    for _, p in locations:
        for axis in range(dimensions):
            delta = shift[axis] if axis < 2 else 0
            value, = struct.unpack_from('<f', before, p + axis * 4)
            if delta:
                struct.pack_into('<f', expected, p + axis * 4, value + delta)
            rounded, = struct.unpack_from('<f', expected, p + axis * 4)
            formats.require(math.isfinite(rounded), 'oracle non-finite result')
            maximum = max(maximum, abs(rounded - (value + delta)))
    return bytes(expected), maximum


def check_bytes(before, after, locations, shift, dimensions=3):
    expected, maximum = expected_bytes(before, locations, shift, dimensions)
    formats.require(after == expected, 'oracle spatial or preserved byte mismatch')
    return maximum


def differing_fields(expected, actual, locations, dimensions=3):
    return sum(expected[p + axis * 4:p + axis * 4 + 4] != actual[p + axis * 4:p + axis * 4 + 4]
               for _, p in locations for axis in range(dimensions))


def restore_family(before, after, locations, families):
    raw = bytearray(after)
    for family, p in locations:
        if family in families:
            raw[p:p + 12] = before[p:p + 12]
    return bytes(raw)


def boundary_fields(boundary):
    return [('boundaries', p) for p in (24, 32, 40, *range(48, len(boundary.raw), 8))]


def synthetic():
    source = fixture((101,))
    roots = formats.chunks(source)
    scene = roots[-1]
    raw = bytearray(scene.payload)
    inst = next(p for p in formats.chunks(scene.payload, scene.offset + 8) if p.kind == 0x34103)
    offset = body_offset(inst) - (scene.offset + 8)
    for q, xyz in ((0, (-12.25, -8.5, 1)), (12, (12.5, 8.25, 4)), (32, (.1, -3000.125, 2))):
        struct.pack_into('<3f', raw, offset + q, *xyz)
    node = struct.pack('<6fH5h', -12.25, -8.5, 1, 12.5, 8.25, 4, 0, 0, 0, 0, 0, 0)
    raw += formats.Chunk(0x34105, node).encode()
    raw += formats.Chunk(0x34107, bytes(128)).encode()
    source = source[:scene.offset] + formats.Chunk(scene.kind, bytes(raw)).encode()
    source = with_events(source)
    out = convert.Builder(0)
    out.data += source
    out.pad(128)
    out.data += emitter_fixture().encode()
    return bytes(out.data)


def synthetic_boundary():
    raw = bytearray(36 + 3 * 8)
    struct.pack_into('<hBB6f', raw, 8, 101, 3, 0, -12.25, -8.5, 12.5, 8.25, .125, -.125)
    struct.pack_into('<6f', raw, 36, -12.25, -8.5, 12.5, -8.5, 0, 8.25)
    return formats.Boundary(bytes(raw), False)


class SyntheticTests(unittest.TestCase):
    def test_all_families_and_both_axes_preserve_other_bytes(self):
        source = synthetic()
        zero, _ = convert.convert_section(source, 101, shift=(0, 0))
        locations = fields(zero)
        self.assertEqual(Counter(f for f, _ in locations), dict(instances=3, tree_nodes=2,
            emitters=1, emitter_triggers=1, event_nodes=2, event_spheres=1))
        boundary = synthetic_boundary()
        bzero = boundary.translate(101, shift=(0, 0))
        for shift in (SHIFT, (-8192, -4096), (4096, 8192), (-4096, 0), (0, 0)):
            with self.subTest(shift=shift):
                after, _ = convert.convert_section(source, 101, shift=shift)
                check_bytes(zero, after, locations, shift)
                result = validate.validate_translation(source, after, shift=shift)
                self.assertEqual(result['spatial_components_checked'], 30)
                bafter = boundary.translate(101, shift=shift)
                check_bytes(bzero.raw, bafter.raw, boundary_fields(bzero), shift, 2)
                bafter.validate()
                # An already extended boundary follows the same coordinates.
                self.assertEqual(bzero.translate(101, shift=shift), bafter)

    def test_legacy_defaults_and_explicit_precull_override(self):
        source = synthetic()
        default, _ = convert.convert_section(source, 101, allow_precull_mismatch=True)
        scalar, _ = convert.convert_section(source, 101, shift_x=20000, allow_precull_mismatch=True)
        vector, _ = convert.convert_section(source, 101, shift=(20000, 0), allow_precull_mismatch=True)
        self.assertEqual(default, scalar)
        self.assertEqual(scalar, vector)
        b = synthetic_boundary()
        self.assertEqual(b.translate(101, 20000), b.translate(101, shift=(20000, 0)))
        # No precull rows: legacy 20 km conversion remains byte-identical.
        plain = fixture((101,))
        self.assertEqual(convert.convert_section(plain, 101)[0],
                         convert.convert_section(plain, 101, shift=(20000, 0))[0])

    def test_four_broken_variants_and_missing_emitters_fail(self):
        source = synthetic()
        zero, _ = convert.convert_section(source, 101, shift=(0, 0))
        good, _ = convert.convert_section(source, 101, shift=SHIFT)
        locations = fields(good)
        wrong, _ = convert.convert_section(source, 101, shift_x=-20480)
        self.assertEqual(differing_fields(good, wrong, locations), 20)
        for bad in (wrong, restore_family(zero, good, locations, {'event_nodes', 'event_spheres'}),
                    restore_family(zero, good, locations, {'emitters', 'emitter_triggers'})):
            with self.assertRaises(formats.FormatError):
                validate.validate_translation(source, bad, shift=SHIFT)
        b = synthetic_boundary().translate(101, shift=(0, 0))
        with self.assertRaises(formats.FormatError):
            check_bytes(b.raw, b.raw, boundary_fields(b), SHIFT, 2)
        with self.assertRaisesRegex(formats.FormatError, '4096 m period'):
            convert.convert_section(source, 101, shift=(0, -20000))
        with self.assertRaisesRegex(formats.FormatError, '4096 m period'):
            convert.convert_section(source, 101)  # same guard for scalar defaults
        convert.convert_section(source, 101, shift=(0, -20000), allow_precull_mismatch=True)

    def test_direct_entry_points_and_invalid_shifts(self):
        source = synthetic()
        scene = next(c for c in formats.chunks(source) if c.kind == 0x80034100)
        zero = convert.convert_scenery(scene, 0, 101, stats=convert.Stats(), shift=(0, 0))
        moved = convert.convert_scenery(scene, 0, 101, stats=convert.Stats(), shift=SHIFT)
        check_bytes(zero, moved, fields(zero), SHIFT)
        # Empty precull arrays do not constrain otherwise valid shifts.
        parts = formats.chunks(scene.payload, scene.offset + 8)
        empty = formats.Chunk(scene.kind, b''.join(formats.Chunk(p.kind,
            b'' if p.kind == 0x34107 else p.payload).encode() for p in parts), scene.offset)
        convert.convert_scenery(empty, 0, 101, stats=convert.Stats(), shift=(1, 2))
        for bad in ((0,), (0, 1, 2), (math.inf, 0), (0, math.nan), 'xy'):
            for operation in (
                    lambda: convert.convert_section(source, 101, shift=bad),
                    lambda: convert.convert_scenery(scene, 0, 101, stats=convert.Stats(), shift=bad),
                    lambda: emitters.convert_emitters(emitter_fixture(), 0, convert.Stats(), shift=bad),
                    lambda: events.convert_events(next(c for c in formats.chunks(source)
                        if c.kind == 0x80036000), 0, convert.Stats(), shift=bad),
                    lambda: synthetic_boundary().translate(101, shift=bad),
                    lambda: validate.validate_translation(source, source, shift=bad)):
                with self.subTest(bad=bad), self.assertRaises(formats.FormatError):
                    operation()


@unittest.skipUnless(ASSETS, 'private track archives absent')
class ArchiveTests(unittest.TestCase):
    def test_every_record_boundary_and_four_broken_variants(self):
        index, stream, _ = load_index(DEFAULT_MW, 'L2RA')
        providers, _ = classify.source_providers(index, stream)
        options = dict(providers=(providers, {s.number for s in index.sections}),
                       animation_inventory=texanim.inventory_source(index, stream))
        counts, broken = Counter(), Counter()
        maximum, wrong_fields, checked = 0., 0, 0
        for section in index.sections:
            source = read_section(stream, section)
            zero, _ = convert.convert_section(source, section.number, shift=(0, 0), **options)
            good, _ = convert.convert_section(source, section.number, shift=SHIFT, **options)
            locations = fields(zero)
            self.assertEqual(fields(good), locations)
            maximum = max(maximum, check_bytes(zero, good, locations, SHIFT))
            counts.update(family for family, _ in locations)
            proof = validate.validate_translation(source, good, shift=SHIFT,
                source_number=section.number, target_number=section.number)
            self.assertEqual(proof['spatial_components_checked'], len(locations) * 3)
            maximum = max(maximum, proof['maximum_translation_error_m'])
            checked += 1
            wrong, _ = convert.convert_section(source, section.number, shift_x=-20480, **options)
            differences = differing_fields(good, wrong, locations)
            wrong_fields += differences
            if differences:
                with self.assertRaises(formats.FormatError):
                    validate.validate_translation(source, wrong, shift=SHIFT)
                broken['wrong_axis_records'] += 1
            if any(f.startswith('event_') for f, _ in locations):
                bad = restore_family(zero, good, locations, {'event_nodes', 'event_spheres'})
                with self.assertRaisesRegex(formats.FormatError, 'event world translation'):
                    validate.validate_translation(source, bad, shift=SHIFT)
                broken['events_omitted'] += 1
            carries_precull = any(p.kind == 0x34107 and p.payload
                for c in formats.chunks(source) if c.kind == 0x80034100
                for p in formats.chunks(c.payload, c.offset + 8))
            if carries_precull:
                with self.assertRaisesRegex(formats.FormatError, '4096 m period'):
                    convert.convert_section(source, section.number, shift=(0, -20000), **options)
                broken['precull_mismatch'] += 1
        boundary_count, boundary_wrong_fields = 0, 0
        for boundary in index.boundaries():
            zero = boundary.translate(boundary.number, shift=(0, 0))
            good = boundary.translate(boundary.number, shift=SHIFT)
            locations = boundary_fields(zero)
            maximum = max(maximum, check_bytes(zero.raw, good.raw, locations, SHIFT, 2))
            good.validate()
            counts['boundaries'] += len(locations)
            with self.assertRaises(formats.FormatError):
                check_bytes(zero.raw, zero.raw, locations, SHIFT, 2)
            broken['boundaries_omitted'] += 1
            wrong = boundary.translate(boundary.number, shift_x=-20480)
            boundary_wrong_fields += differing_fields(good.raw, wrong.raw, locations, 2)
            boundary_count += 1
        self.assertEqual((checked, boundary_count), (720, 515))
        self.assertEqual(dict(counts), dict(instances=233349, tree_nodes=39156,
            emitters=1535, emitter_triggers=42, event_nodes=16426, event_spheres=13144,
            boundaries=5837))
        self.assertEqual(dict(broken), dict(wrong_axis_records=606, events_omitted=415,
            boundaries_omitted=515, precull_mismatch=606))
        self.assertEqual((wrong_fields, boundary_wrong_fields), (607304, 11674))
        self.assertLessEqual(maximum, .001953125)
        print('C1_SHIFT ' + json.dumps(dict(records=checked, boundaries=boundary_count,
            vectors=dict(counts), spatial_components=sum(v * (2 if k == 'boundaries' else 3)
                for k, v in counts.items()), maximum_error_m=maximum,
            maximum_error_after_float32_m=0, wrong_axis_fields=wrong_fields,
            wrong_axis_boundary_fields=boundary_wrong_fields, broken=dict(broken)), sort_keys=True))


if __name__ == '__main__':
    result = unittest.main(exit=False, verbosity=2).result
    if not result.wasSuccessful():
        raise SystemExit(1)
    if not ASSETS:
        print('private assets absent: synthetic controls passed; corpus unavailable', file=sys.stderr)
        raise SystemExit(3)
