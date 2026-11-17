"""Sidecars: baseline writer 0/375 -> independent acceptance 375/375 chunks.

Control: 627/627 native chunks; own-table index failures source/control = 0/0.
Broken stride 76: 20/20 rejected; retained wrong filler: 20/20 rejected;
one-past light-material index: 355/355 rejected (native control 308/308).
No sidecar field is an index: mutate its material consumer at +29 instead.
All marker matrix bytes stay model-local. Missing private assets exits 3.
"""
import argparse
from collections import Counter
import hashlib
import math
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import sidecars
from convert import Builder, Stats, aligned_payload, convert_mesh
from formats import Chunk, FormatError, chunks, require
from merge import DEFAULT_MW, DEFAULT_CARBON, load_index, read_section

MW, CARBON = DEFAULT_MW, DEFAULT_CARBON

# Predecessor convert_solid's child guard (convert.py:150-152). Pin only this
# fragment so the baseline remains runnable after the production hook lands.
BASELINE_GUARD = (
    'parts = chunks(c.payload, c.offset + 8)\n'
    'require(Counter(p.kind for p in parts) == Counter({0x134011: 1, 0x134012: 1, 0x80134100: 1}),\n'
    "        'undecoded solid children')\n")
BASELINE_SHA256 = '2cdb8c6cfdb06c9349d134df7404ea0e5419e0e6e1382931242db50c23a3eb8a'


class CheckError(ValueError):
    pass


def demand(condition, message):
    if not condition:
        raise CheckError(message)


def envelopes(data, base=0):
    """Checker's independent envelope/extent walk, no converter helpers."""
    offset = 0
    while offset < len(data):
        demand(offset + 8 <= len(data), 'short envelope')
        kind, length = struct.unpack_from('<II', data, offset)
        end = offset + 8 + length
        demand(end <= len(data), 'crossed envelope')
        yield kind, data[offset + 8:end], base + offset
        offset = end


def unpad(payload, offset):
    start = ((offset + 23) & ~15) - (offset + 8)
    demand(start <= len(payload) and payload[:start] == bytes([17]) * start,
           'bad alignment')
    return payload[start:]


def check_leaf(kind, payload, offset):
    """Target reader model, separately encoded from the source converter."""
    if kind == 0x134013:
        demand(0 < len(payload) <= 127 * 8 and len(payload) % 8 == 0, 'light extent')
        for key, pointer in struct.iter_unpack('<II', payload):
            demand(pointer == 0, 'serialized light pointer')
        return len(payload) // 8
    demand(kind == 0x13401a, 'unknown leaf')
    records = unpad(payload, offset)
    demand(0 < len(records) <= 127 * 80 and len(records) % 80 == 0, 'marker extent')
    for record in struct.iter_unpack('<IIfI16f', records):
        key, marker_type, selector, reserved, *matrix = record
        demand(marker_type <= 8, 'marker type')
        demand(math.isfinite(selector) and 0 <= selector <= 9 and selector.is_integer(),
               'flare selector')
        demand(reserved == 0, 'reserved marker word')
        demand(all(math.isfinite(f) for f in matrix), 'marker finite')
        demand(matrix[3] == matrix[7] == matrix[11] == 0 and matrix[15] == 1,
               'marker homogeneous column')
    return len(records) // 80


def check_solid(solid, target=False):
    """Check each referencing material against THIS solid's sibling tables."""
    parts = list(envelopes(solid.payload, solid.offset + 8))
    single = lambda k: [p for p in parts if p[0] == k]
    demand(len(single(0x134011)) == len(single(0x134012)) == 1, 'solid tables')
    _, hp, ho = single(0x134011)[0]
    header = unpad(hp, ho)
    demand(len(header) >= 164, 'solid header')
    texture_count, light_count = header[25:27]
    demand(len(single(0x134012)[0][1]) == texture_count * 8, 'texture count')
    demand(len(single(0x134013)) <= 1 and len(single(0x13401a)) <= 1, 'sidecar singleton')
    actual_lights = sum(check_leaf(*p) for p in single(0x134013))
    demand(actual_lights == light_count, 'light count')
    for p in single(0x13401a):
        check_leaf(*p)  # the loader derives marker count, replacing header +27
    checked = Counter()
    width = 144 if target else 104
    for _, payload, offset in single(0x80134100):
        mesh = list(envelopes(payload, offset + 8))
        tables = [p for p in mesh if p[0] == 0x134b02]
        demand(len(tables) == 1, 'material table')
        _, raw, start = tables[0]
        records = unpad(raw, start)
        demand(len(records) % width == 0, 'material stride')
        for pos in range(0, len(records), width):
            for value in records[pos + 24:pos + 29]:
                demand(value < texture_count, 'texture index')
                checked['texture_indices'] += 1
            value = records[pos + 29]
            demand(value == 255 or value < actual_lights, 'light index')
            checked['light_slots'] += 1
            checked['light_indices' if value != 255 else 'default_lights'] += 1
    return checked


def solids(root, track):
    index, stream, _ = load_index(root, track)
    for section in index.sections:
        for top in chunks(read_section(stream, section), section.offset):
            if top.kind == 0x80134000:
                for solid in chunks(top.payload, top.offset + 8):
                    if solid.kind == 0x80134010:
                        yield solid


def with_bad_index(solid):
    """Keep all extents: point a material one past its own light table."""
    payload = bytearray(solid.payload)
    parts = list(envelopes(payload, solid.offset + 8))
    count = sum(len(p) // 8 for k, p, _ in parts if k == 0x134013)
    for kind, mesh, offset in parts:
        if kind != 0x80134100:
            continue
        for k, records, off in envelopes(mesh, offset + 8):
            if k == 0x134b02:
                raw = unpad(records, off)
                if raw:
                    index = off + 8 + len(records) - len(raw) + 29 - (solid.offset + 8)
                    payload[index] = count
                    return Chunk(solid.kind, bytes(payload), solid.offset)
    raise CheckError('missing material to mutate')


def marker(offset=0, marker_type=3):
    matrix = [1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1., 0., 12., 23., 34., 1.]
    body = struct.pack('<IIfI16f', 123, marker_type, 0., 0, *matrix)
    return Chunk(0x13401a, b'\x11' * (-(offset + 8) % 16) + body, offset)


def rebuilt_solid(solid, destination=48):
    """Test-only assembly; production convert_solid deliberately stays unwired."""
    builder, stats = Builder(destination + 8), Stats()
    for p in chunks(solid.payload, solid.offset + 8):
        if p.kind == 0x134011:
            builder.add(p.kind, aligned_payload(p), 16)
        elif p.kind == 0x134012:
            builder.add(p.kind, p.payload)
        elif p.kind in (0x134013, 0x13401a):
            builder.data += sidecars.convert_sidecar(p, builder.position, stats)
        else:
            demand(p.kind == 0x80134100, 'unexpected source solid child')
            builder.data += convert_mesh(p, builder.position, stats)
    return Chunk(solid.kind, bytes(builder.data), destination)


class SyntheticTests(unittest.TestCase):
    def test_nested_test_impact_registration(self):
        # Discovery before adding the suite's nested directory: 0/2 covered;
        # after: 2/2 covered, selecting the executable test_sidecars name.
        result = subprocess.run([
            sys.executable, '-I', str(HERE.parents[1] / 'runtime/impact_tests.py'),
            'tools_snapshot/worldmerge/sidecars.py',
            'tools_snapshot/worldmerge/test_sidecars.py'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('test_sidecars', result.stdout.split())
        self.assertNotIn('unscoped:', result.stderr)

    def test_all_destination_residues_and_model_local_bytes(self):
        stats = Stats()
        for source_offset in range(16):
            p = marker(source_offset)
            expected = unpad(p.payload, p.offset)
            for destination in range(16):
                encoded = sidecars.convert_sidecar(p, destination, stats)
                kind, raw, offset = next(envelopes(encoded, destination))
                self.assertEqual(check_leaf(kind, raw, offset), 1)
                self.assertEqual(unpad(raw, offset), expected)
        self.assertEqual(stats, Stats())
        print('ALIGNMENT: 256/256 source/destination residues; matrix bytes unchanged')

    def test_light_table_is_unaligned_and_never_treated_as_filler(self):
        raw = struct.pack('<II', 17, 0)
        for destination in range(16):
            p = Chunk(0x134013, raw, 5)
            output = sidecars.convert_sidecar(p, destination, Stats())
            self.assertEqual(output, p.encode())
            self.assertEqual(check_leaf(0x134013, output[8:], destination), 1)

    def test_unknown_fields_and_malformed_input_fail_closed(self):
        p = marker(8)
        mutations = [(4, '<I', 6), (8, '<f', 2.), (12, '<I', 1),
                     (16, '<f', float('nan')), (28, '<f', 1.)]
        for off, fmt, value in mutations:
            raw = bytearray(p.payload)
            struct.pack_into(fmt, raw, off, value)
            with self.assertRaises(FormatError):
                sidecars.convert_sidecar(Chunk(p.kind, bytes(raw), p.offset), 0, Stats())
        for p in (Chunk(0x134013, struct.pack('<II', 1, 1)),
                  Chunk(0x134013, bytes(7)), Chunk(0x134013, b''),
                  Chunk(0x13401a, b'\x11' * 8 + bytes(76)),
                  Chunk(0x13401a, bytes(8) + marker(8).payload),
                  Chunk(0x13401a, b''), Chunk(0x9999, bytes(8))):
            with self.assertRaises(FormatError):
                sidecars.convert_sidecar(p, 0, Stats())

    def test_missing_assets_exit_three(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run([sys.executable, '-I', str(Path(__file__).resolve()),
                                     '--mw', tmp, '--carbon', tmp, '--check-assets'],
                                    capture_output=True, text=True)
        self.assertEqual(result.returncode, 3, result.stderr)
        self.assertIn('private assets absent', result.stderr)


class ArchiveTests(unittest.TestCase):
    def test_complete_corpus_and_negative_controls(self):
        if not assets_present():
            self.skipTest('private track archives absent')
        self.assertEqual(hashlib.sha256(BASELINE_GUARD.encode()).hexdigest(), BASELINE_SHA256)
        predecessor = compile(BASELINE_GUARD, '<predecessor solid guard>', 'exec')
        for root, track, target, expected in ((MW, 'L2RA', False, (355, 20)),
                                               (CARBON, 'L5RA', True, (308, 319))):
            counts, accepted, fields, mutations, baseline = Counter(), 0, Counter(), Counter(), 0
            for solid in solids(root, track):
                parts = chunks(solid.payload, solid.offset + 8)
                leaves = [p for p in parts if p.kind in (0x134013, 0x13401a)]
                if not leaves:
                    continue
                fields.update(check_solid(solid, target))
                sidecars.validate_solid_sidecars(solid, target=target)
                if not target:
                    with self.assertRaisesRegex(FormatError, 'undecoded solid children'):
                        exec(predecessor, {'c': solid, 'chunks': chunks,
                                           'Counter': Counter, 'require': require})
                    baseline += len(leaves)
                    rebuilt = rebuilt_solid(solid)
                    self.assertEqual(check_solid(rebuilt, True), check_solid(solid, False))
                    sidecars.validate_solid_sidecars(rebuilt, target=True)
                    rebuilt_leaves = [p for p in chunks(rebuilt.payload, rebuilt.offset + 8)
                                      if p.kind in (0x134013, 0x13401a)]
                    self.assertEqual([p.kind for p in rebuilt_leaves], [p.kind for p in leaves])
                    for before, after in zip(leaves, rebuilt_leaves):
                        check_leaf(after.kind, after.payload, after.offset)
                        if before.kind == 0x13401a:
                            self.assertEqual(unpad(before.payload, before.offset),
                                             unpad(after.payload, after.offset))
                        else:
                            self.assertEqual(before.payload, after.payload)
                if any(p.kind == 0x134013 for p in leaves):
                    broken = with_bad_index(solid)
                    with self.assertRaisesRegex(CheckError, 'light index'):
                        check_solid(broken, target)
                    with self.assertRaisesRegex(FormatError, 'index out of range'):
                        sidecars.validate_solid_sidecars(broken, target=target)
                    mutations['one_past_index'] += 1
                for p in leaves:
                    counts[p.kind] += 1
                    if p.kind == 0x134013:
                        self.assertEqual(len(p.payload), 8)
                        self.assertEqual(len(p.payload) % 80, 8)
                    if target:
                        check_leaf(p.kind, p.payload, p.offset)
                    else:
                        # Force the target to need different filler for every marker.
                        destination = p.offset + 4
                        generated = sidecars.convert_sidecar(p, destination, Stats())
                        k, raw, off = next(envelopes(generated, destination))
                        check_leaf(k, raw, off)
                        if p.kind == 0x13401a:
                            records = unpad(p.payload, p.offset)
                            self.assertEqual(unpad(raw, off), records)
                            with self.assertRaises(CheckError):
                                check_leaf(k, p.payload, destination)
                            mutations['wrong_filler'] += 1
                            bad = b''.join(records[i:i + 76] for i in range(0, len(records), 80))
                            bad = b'\x11' * (-(destination + 8) % 16) + bad
                            with self.assertRaisesRegex(CheckError, 'marker extent'):
                                check_leaf(k, bad, destination)
                            mutations['stride_76'] += 1
                            with self.assertRaises(FormatError):
                                sidecars.convert_sidecar(Chunk(k, bad, destination), 0, Stats())
                    accepted += 1
            self.assertEqual((counts[0x134013], counts[0x13401a]), expected)
            self.assertEqual(accepted, sum(expected))
            self.assertEqual(mutations['one_past_index'], expected[0])
            if not target:
                self.assertEqual(baseline, 375)
                self.assertEqual(mutations['wrong_filler'], 20)
                self.assertEqual(mutations['stride_76'], 20)
            print(f'{track}: chunks={accepted}/{sum(expected)}; indices={dict(fields)}; '
                  f'out-of-range=0; rejected={dict(mutations)}; old writer rejected={baseline}')


def assets_present():
    return all((root / name).is_file() for root, names in (
        (MW, ('L2RA.BUN', 'STREAML2RA.BUN')),
        (CARBON, ('L5RA.BUN', 'STREAML5RA.BUN')))
               for name in names)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--mw', type=Path, default=MW)
    parser.add_argument('--carbon', type=Path, default=CARBON)
    parser.add_argument('--check-assets', action='store_true')
    args, remaining = parser.parse_known_args()
    MW, CARBON = args.mw, args.carbon
    if args.check_assets:
        if not assets_present():
            print('SKIP: private assets absent', file=sys.stderr)
            raise SystemExit(3)
        raise SystemExit(0)
    result = unittest.main(argv=[sys.argv[0], *remaining], exit=False, verbosity=2).result
    if not result.wasSuccessful():
        raise SystemExit(1)
    if not assets_present():
        raise SystemExit(3)
    print('SIDECARS PASS: 627 control + 375 converted chunks; no solid hook installed')
