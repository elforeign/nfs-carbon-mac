"""Pair structure: baseline guard accepts 0/341; 341/341 fragments keep IDs.

Native control: 390/390 pairs ordered [N,N-40]. Broken output controls:
second header overwritten 341/341 rejected; second dropped 341/341 rejected;
containers swapped 341/341 rejected. Intact shifted/renumbered pairs pass.
Four secondary-only source headers also retain their -40 offset.
Standalone acceptance: 710/720 with sky/empty/animation hooks; providers omitted.
Missing event X shift: 414/414 accepted event sections rejected by translation;
the correctly shifted controls validate 414/414 (plus 1/1 synthetic control).
Fragment checks isolate scenery; whole-section acceptance is counted separately.
Archive operations are read-only; missing private assets exits 3.
"""
import argparse
import hashlib
from pathlib import Path
import struct
import subprocess
import sys
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import convert
import events
import merge
import validate
from formats import Boundary, Chunk, FormatError, chunks, require, u32
from merge import DEFAULT_MW, DEFAULT_CARBON, load_index, read_section

MW, CARBON = DEFAULT_MW, DEFAULT_CARBON
BASELINE_GUARD = ("require(sum(c.kind == 0x80034100 for c in roots) == 1,\n"
                  "        'only sections with one scenery container are supported')\n")
BASELINE_SHA256 = 'd5b424a9fe65aa9aaf4b41ac0e1434df733b33bd6d407e1ed704d8beeba7b933'


def body(c, alignment=16):
    pad = -(c.offset + 8) % alignment
    require(c.payload[:pad] == bytes([17]) * pad, 'check: alignment filler')
    return c.payload[pad:]


def scenes(data):
    return [c for c in chunks(data) if c.kind == 0x80034100]


def scenery_fragment(data):
    out = convert.Builder(0)
    for scene in scenes(data):
        out.pad(128)
        out.data += scene.encode()
    return bytes(out.data)


def identities(data, size):
    result = []
    for scene in scenes(data):
        headers = [p for p in chunks(scene.payload, scene.offset + 8) if p.kind == 0x34101]
        require(len(headers) == 1, 'check: header count')
        raw = body(headers[0])
        require(len(raw) == size, 'check: header size')
        result.append(u32(raw, 12))
    return result


def mutants(data, number):
    pair = scenes(data)
    second = next(p for p in chunks(pair[1].payload, pair[1].offset + 8) if p.kind == 0x34101)
    changed = bytearray(data)
    off = second.offset + 8 + (-(second.offset + 8) % 16) + 12
    struct.pack_into('<I', changed, off, number)
    yield 'overwritten', bytes(changed)
    # Rebuild root alignment so each failure concerns identity/count/order.
    for name, replacement in (('dropped', pair[:1]), ('swapped', pair[::-1])):
        out, index = convert.Builder(0), 0
        for root in chunks(data):
            if not root.kind:
                continue
            if root.kind == 0x80034100:
                if index >= len(replacement):
                    continue
                root = replacement[index]
                index += 1
            out.pad(128)
            out.data += root.encode()
        yield name, bytes(out.data)


def container(kind, position, leaves):
    """Synthetic envelope builder with explicit source-layout alignment."""
    data = bytearray()
    for child, raw, alignment in leaves:
        filler = bytes([17]) * (-(position + 8 + len(data) + 8) % alignment)
        data += Chunk(child, filler + raw).encode()
    return Chunk(kind, bytes(data), position)


def fixture(numbers=(141, 101), *, with_sidecars=False):
    # One triangle, one texture hash, one instance per scenery container.
    out = convert.Builder(0)
    header = bytearray(164)
    struct.pack_into('<II', header, 12, 22, 1)
    header[25] = 1
    header[26] = int(with_sidecars)
    struct.pack_into('<3f', header, 48, 1, 1, 1)
    material = bytearray(104)
    struct.pack_into('<3f', material, 12, 1, 1, 1)
    material[29] = 0 if with_sidecars else 255
    struct.pack_into('<III', material, 60, 3, 1, 0)
    struct.pack_into('<I', material, 92, 3)
    mesh_header = bytearray(48)
    for off, value in ((16, 1), (24, 1), (44, 3)):
        struct.pack_into('<I', mesh_header, off, value)
    vertices = b''.join(struct.pack('<9f', *xyz, 0, 0, 1, 0, 0, 0)
                        for xyz in ((0, 0, 0), (1, 0, 0), (0, 1, 0)))
    info = bytearray(144)
    struct.pack_into('<II', info, 8, 29, 1)
    list_header = container(0x80134001, 8, [(0x134002, info, 1),
        (0x134003, struct.pack('<II', 1, 0), 1), (0x80134008, b'', 1)])
    solid_position = 8 + len(list_header.encode())
    leaves = [(0x134011, header, 16), (0x134012, struct.pack('<II', 2, 0), 1)]
    if with_sidecars:
        matrix = [0.] * 16
        for i in (0, 5, 10, 15):
            matrix[i] = 1.
        matrix[12:15] = [12., 23., 34.]
        leaves.extend([(0x134013, struct.pack('<II', 17, 0), 1),
                       (0x13401a, struct.pack('<4I16f', 123, 3, 0, 0, *matrix), 16)])
    solid_prefix = container(0x80134010, solid_position, leaves)
    mesh_position = solid_position + len(solid_prefix.encode())
    mesh = container(0x80134100, mesh_position, [(0x134900, mesh_header, 16),
        (0x134b02, material, 16), (0x134b03, struct.pack('<4H', 0, 1, 2, 0), 16),
        (0x134b01, vertices, 128), (0x134c02, b'triangle\0', 1)])
    solid = Chunk(0x80134010, solid_prefix.payload + mesh.encode())
    out.data += Chunk(0x80134000, list_header.encode() + solid.encode()).encode()
    for number in numbers:
        out.pad(128)
        header, instance = bytearray(60), bytearray(64)
        struct.pack_into('<I', header, 12, number)
        struct.pack_into('<3f', instance, 12, 1, 1, 1)
        struct.pack_into('<9h', instance, 44, 8192, 0, 0, 0, 8192, 0, 0, 0, 8192)
        scene = container(0x80034100, out.position, [(0x34101, header, 16),
            (0x34102, bytes(72), 1), (0x34103, instance, 16)])
        out.data += scene.encode()
    return bytes(out.data)


def with_events(source):
    from test_events import synthetic
    out = convert.Builder(0)
    out.data += source
    out.pad(128)
    out.data += synthetic().encode()
    return bytes(out.data)


def without_event_shift(c, position, stats, shift_x=0, *, section=None, shift=None):
    # Call the landed writer exactly as a broken integration hook would.
    return REAL_EVENTS(c, position, stats, 0, section=section)


REAL_EVENTS = events.convert_events


class SyntheticTests(unittest.TestCase):
    def test_events_shift_mapping_and_missing_shift_failure(self):
        source = with_events(fixture((101, 61)))
        for shift in (0, -20000, 20000):
            with self.subTest(shift=shift):
                target, stats = convert.convert_section(source, 1234, shift, source_number=101)
                totals, _ = validate.validate_section(target, 1234)
                self.assertEqual(totals['events'], 1)
                self.assertEqual(totals['nodes'], stats.nodes)
                validate.validate_translation(source, target, shift,
                    source_number=101, target_number=1234)
                event = next(c for c in chunks(target) if c.kind == 0x80036000)
                self.assertEqual(events.decode_events(event).section, 1234)
        with patch.object(events, 'convert_events', side_effect=without_event_shift):
            bad, _ = convert.convert_section(source, 1234, 20000, source_number=101)
        # Shifting neither tree nor spheres retains internally valid bounds.
        validate.validate_section(bad, 1234)
        with self.assertRaisesRegex(FormatError, 'event world translation'):
            validate.validate_translation(source, bad, 20000,
                source_number=101, target_number=1234)
        print('EVENT HOOK: shifted=1/1 pass; missing X shift=1/1 rejected')

    def test_event_owner_count_and_opaque_fields_checked(self):
        source = with_events(fixture((101, 61)))
        target, _ = convert.convert_section(source, 1234, 20000, source_number=101)
        event = next(c for c in chunks(target) if c.kind == 0x80036000)
        head, _, records = chunks(event.payload, event.offset + 8)
        bad = bytearray(target)
        struct.pack_into('<I', bad, head.offset + 8 + (-(head.offset + 8) % 16) + 12, 1235)
        with self.assertRaisesRegex(FormatError, 'target event/index number'):
            validate.validate_section(bad, 1234)
        with self.assertRaisesRegex(FormatError, 'event world translation'):
            validate.validate_translation(source, bad, 20000, source_number=101, target_number=1234)
        bad = bytearray(target)
        bad[records.offset + 8 + (-(records.offset + 8) % 16) + 8] ^= 1
        validate.validate_section(bad, 1234)
        with self.assertRaisesRegex(FormatError, 'event world translation'):
            validate.validate_translation(source, bad, 20000, source_number=101, target_number=1234)
        bad = target[:event.offset]
        with self.assertRaisesRegex(FormatError, 'event directory count changed'):
            validate.validate_translation(source, bad, 20000)
        bad_source = with_events(fixture((102, 62)))
        with self.assertRaisesRegex(FormatError, 'source event/index number'):
            convert.convert_section(bad_source, 1234, source_number=102)

    def test_decoder_dispatch_and_model_local_sidecars(self):
        from test_emitters import synthetic, check_translation
        source = fixture((123, 83), with_sidecars=True)
        out = convert.Builder(0)
        out.data += source
        out.pad(128)
        emitter = synthetic()
        out.data += emitter.encode()
        source = bytes(out.data)
        target, stats = convert.convert_section(source, 123, 20000)
        validate.validate_section(target, 123)
        emitted = next(c for c in chunks(target) if c.kind == 0x3bc00)
        check_translation(Chunk(emitter.kind, emitter.payload, out.position - len(emitter.encode())),
                          emitted.encode(), emitted.offset, 20000)
        self.assertEqual(stats.emitter_chunks, 1)
        def sidecar_bodies(raw):
            root = next(c for c in chunks(raw) if c.kind == 0x80134000)
            solid = next(c for c in chunks(root.payload, root.offset + 8) if c.kind == 0x80134010)
            return {c.kind: body(c) if c.kind == 0x13401a else c.payload
                    for c in chunks(solid.payload, solid.offset + 8) if c.kind in (0x134013, 0x13401a)}
        self.assertEqual(sidecar_bodies(source), sidecar_bodies(target))
        self.assertEqual(len(sidecar_bodies(target)), 2)

    def test_pair_shift_renumber_and_broken_outputs(self):
        source = fixture()
        target, stats = convert.convert_section(source, 1234, 20000, source_number=141)
        self.assertEqual(identities(target, 68), [1234, 1194])
        totals, _ = validate.validate_section(target, 1234)
        self.assertEqual(totals['instances'], stats.instances)
        validate.validate_translation(source, target, 20000, source_number=141, target_number=1234)
        for name, bad in mutants(target, 1234):
            with self.subTest(mutant=name):
                # A lone primary is structurally valid; source comparison is
                # what proves that a second container has not been dropped.
                if name != 'dropped':
                    with self.assertRaises(FormatError):
                        validate.validate_section(bad, 1234)
                with self.assertRaises(FormatError):
                    validate.validate_translation(source, bad, 20000)

    def test_source_pair_order_counts_and_headers_refuse(self):
        for numbers in ((141, 141), (101, 141), (141, 102), (141, 101, 61)):
            with self.subTest(numbers=numbers), self.assertRaises(FormatError):
                convert.convert_section(fixture(numbers), 141)
        source = fixture()
        for _, bad in mutants(source, 141):
            if len(scenes(bad)) == 2:
                with self.assertRaises(FormatError):
                    convert.convert_section(bad, 141)
        with self.assertRaisesRegex(FormatError, 'out of range'):
            convert.convert_section(source, 20, source_number=141)

    def test_secondary_only_identity_and_explicit_renumbering(self):
        source = fixture((225,))
        for target_number in (265, 1234):
            target, _ = convert.convert_section(source, target_number, 0, source_number=265)
            self.assertEqual(identities(target, 68), [target_number - 40])
            validate.validate_section(target, target_number)
            validate.validate_translation(source, target, 0, source_number=265, target_number=target_number)
        target, _ = convert.convert_section(source, 265, 0)
        self.assertEqual(identities(target, 68), [225])
        bad, _ = convert.convert_section(fixture((265,)), 265, 0)
        with self.assertRaisesRegex(FormatError, 'identity offset'):
            validate.validate_translation(source, bad, 0, source_number=265, target_number=265)

    def test_missing_input_exits_three(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run([sys.executable, '-I', str(Path(__file__).resolve()),
                '--mw', tmp, '--carbon', tmp], capture_output=True, text=True)
        self.assertEqual(result.returncode, 3, result.stderr)


class ArchiveTests(unittest.TestCase):
    def test_successful_sections_validate_and_keep_every_scenery_header(self):
        if not (MW / 'L2RA.BUN').is_file():
            self.skipTest('private track archives absent')
        index, stream, _ = load_index(MW, 'L2RA')
        accepted = paired = event_sections = 0
        for section in index.sections:
            source = read_section(stream, section)
            try:
                target, _ = convert.convert_section(source, section.number, 20000,
                    source_number=section.number, allow_precull_mismatch=True)
            except FormatError:
                continue
            with self.subTest(section=section.name):
                checker = validate.validate_section if scenes(source) else validate.validate_resources
                checker(target, section.number)
                self.assertEqual(identities(source, 60), identities(target, 68))
                validate.validate_translation(source, target, 20000,
                    source_number=section.number, target_number=section.number)
                if any(c.kind == 0x80036000 for c in chunks(source)):
                    with patch.object(events, 'convert_events', side_effect=without_event_shift):
                        bad, _ = convert.convert_section(source, section.number, 20000,
                            source_number=section.number, allow_precull_mismatch=True)
                    checker(bad, section.number)
                    with self.assertRaisesRegex(FormatError, 'event world translation'):
                        validate.validate_translation(source, bad, 20000,
                            source_number=section.number, target_number=section.number)
                    event_sections += 1
            paired += len(scenes(source)) == 2
            accepted += 1
        self.assertEqual(accepted, 710)
        self.assertEqual(event_sections, 414)
        self.assertGreater(paired, 0)
        print(f'SECTIONS: generated/validated={accepted}/{accepted}; accepted pairs={paired}')
        print(f'EVENT SECTIONS: shifted={event_sections}/414 pass; missing X shift={event_sections}/414 rejected')

    def test_merge_caller_renumbers_secondary_only_sections(self):
        if not all((root / name).is_file() for root, name in ((MW, 'L2RA.BUN'), (CARBON, 'L5RA.BUN'))):
            self.skipTest('private track archives absent')
        for number in (265, 551, 764, 943):
            with self.subTest(number=number):
                source_input = load_index(MW, 'L2RA')
                source = source_input[0]
                record = next(s for s in source.sections if s.number == number)
                boundaries = list(source.boundaries())
                # These LOD sections have no native visibility row. Supply a
                # synthetic row only in this in-memory caller harness.
                self.assertNotIn(number, {b.number for b in boundaries})
                x, y, _ = record.position
                raw = bytearray(68)
                struct.pack_into('<hBB6f', raw, 8, number, 4, 0,
                                 x - 1, y - 1, x + 1, y + 1, x, y)
                struct.pack_into('<8f', raw, 36, x - 1, y - 1, x + 1, y - 1,
                                 x + 1, y + 1, x - 1, y + 1)
                boundary = Boundary(bytes(raw), False)
                boundary.validate()
                target_input = load_index(CARBON, 'L5RA')
                with patch.object(source, 'boundaries', return_value=boundaries + [boundary]), \
                     patch.object(merge, 'load_index', side_effect=[source_input, target_input]), \
                     patch.object(merge, 'convert_section', wraps=convert.convert_section) as call:
                    if number == 551:
                        # E51 remains a no-geometry census refusal. The call
                        # must still carry its index identity into the writer.
                        with self.assertRaisesRegex(FormatError, 'section lacks geometry or instances'):
                            merge.prepare(MW, CARBON, number)
                    else:
                        _, target, _, report = merge.prepare(MW, CARBON, number)
                self.assertEqual(call.call_args.kwargs['source_number'], number)
                if number != 551:
                    self.assertEqual(identities(target, 68), [report['target_number'] - 40])
                    validate.validate_section(target, report['target_number'])
        print('MERGE: source identity forwarded=4/4; outputs=3/3; E51 geometry refusal=1/1 '
              '(synthetic visibility rows)')

    def test_all_source_pairs_and_failure_controls(self):
        if not (MW / 'L2RA.BUN').is_file():
            self.skipTest('private track archives absent')
        self.assertEqual(hashlib.sha256(BASELINE_GUARD.encode()).hexdigest(), BASELINE_SHA256)
        index, stream, _ = load_index(MW, 'L2RA')
        pairs, secondary = 0, []
        for section in index.sections:
            source = scenery_fragment(read_section(stream, section))
            roots = scenes(source)
            if len(roots) == 1:
                if identities(source, 60) == [section.number - 40]:
                    secondary.append(section.name)
                    target = convert.convert_scenery(roots[0], 0, 1194, 20000, convert.Stats(),
                                                     allow_precull_mismatch=True)
                    self.assertEqual(identities(target, 68), [1194])
                    validate.validate_translation(source, target, 20000,
                        source_number=section.number, target_number=1234)
                continue
            if len(roots) != 2:
                continue
            self.assertEqual(identities(source, 60), [section.number, section.number - 40])
            with self.assertRaises(FormatError):
                exec(BASELINE_GUARD, {'roots': roots, 'require': require})
            out, stats = convert.Builder(0), convert.Stats()
            for root, number in zip(roots, (1234, 1194)):
                out.pad(128)
                out.data += convert.convert_scenery(root, out.position, number, 20000, stats,
                                                    allow_precull_mismatch=True)
            target = bytes(out.data)
            self.assertEqual(identities(target, 68), [1234, 1194])
            validate.validate_translation(source, target, 20000, source_number=section.number, target_number=1234)
            for name, bad in mutants(target, 1234):
                with self.subTest(section=section.name, mutant=name), self.assertRaises(FormatError):
                    validate.validate_translation(source, bad, 20000)
            pairs += 1
        self.assertEqual(pairs, 341)
        self.assertEqual(secondary, ['B65', 'E51', 'G64', 'I43'])
        print('PAIRS: baseline=0/341; converted=341/341; overwritten/dropped/swapped rejected=341/341 each')

    def test_native_ordered_pair_control(self):
        if not (CARBON / 'L5RA.BUN').is_file():
            self.skipTest('private track archives absent')
        index, stream, _ = load_index(CARBON, 'L5RA')
        pairs = 0
        for section in index.sections:
            raw = read_section(stream, section)
            if len(scenes(raw)) == 2:
                self.assertEqual(identities(raw, 68), [section.number, section.number - 40])
                pairs += 1
        self.assertEqual(pairs, 390)
        print('NATIVE: ordered pairs=390/390')


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--mw', type=Path, default=DEFAULT_MW)
    ap.add_argument('--carbon', type=Path, default=DEFAULT_CARBON)
    args, remaining = ap.parse_known_args()
    MW, CARBON = args.mw, args.carbon
    if ('--mw' in sys.argv or '--carbon' in sys.argv) and not all(
            (root / name).is_file() for root, name in ((MW, 'L2RA.BUN'),
            (MW, 'STREAML2RA.BUN'), (CARBON, 'L5RA.BUN'), (CARBON, 'STREAML5RA.BUN'))):
        print('SKIP: private assets absent', file=sys.stderr)
        raise SystemExit(3)
    result = unittest.main(argv=[sys.argv[0], *remaining], exit=False, verbosity=2).result
    if not result.wasSuccessful():
        raise SystemExit(1)
    if not all((root / name).is_file() for root, name in ((MW, 'L2RA.BUN'),
            (MW, 'STREAML2RA.BUN'), (CARBON, 'L5RA.BUN'), (CARBON, 'STREAML5RA.BUN'))):
        print('SKIP: private assets absent', file=sys.stderr)
        raise SystemExit(3)
    print('SCENERY2 PASS: both identities retained; three broken variants rejected')
