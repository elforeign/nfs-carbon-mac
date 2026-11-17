"""Offline C1 proof: baseline 2 separate graphs -> 1 graph, no bridge.

Acceptance: 8988 nodes / 12328 segments / 1524 profiles / 2148 roads;
0 reference errors, 0 duplicate IDs; valid=1, required broken=5/5 rejected:
unshifted endpoint ID, duplicated self ID, cross-graph adjacency, synthetic
32769-node count, twice-applied translation. Synthetic tests also run bare;
missing private archives exits 3. Native float32 translation rounds 3984/4385
X coordinates: <=0.0009765625 m inverse error, not bit-exact inverse XYZ.
"""
import contextlib
import io
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(HERE))
import c1_roads as c
from formats import FormatError
from region import collision_body, collision_tags, one


def container(nodes, segments, profiles=b'', roads=b''):
    """Independent two-group fixture; no private payload bytes embedded."""
    assert len(nodes) % 32 == len(segments) % 22 == len(profiles) % 64 == len(roads) % 8 == 0
    nn, ns, np, nr = len(nodes) // 32, len(segments) // 22, len(profiles) // 64, len(roads) // 8
    entries = [(0x43477264, 1, b'non-road bytes!!'),
               (0x524e6864, 1, struct.pack('<7H', np, nn, ns, 0, nr, 0, 0)),
               (0x524e6e64, nn, nodes), (0x524e7066, np, profiles),
               (0x524e7264, nr, roads), (0x524e7367, ns, segments)]
    raw = bytearray(144)
    struct.pack_into('<4I', raw, 0, 0x43415250, 0x4a, 0, 1)
    struct.pack_into('<4I', raw, 16, 0x43446174, 0x12, 1, 2)
    struct.pack_into('<4I', raw, 32, 0x524e6770, 0x12, 5, 2)
    for i, (key, count, data) in enumerate(entries):
        raw += bytes(-len(raw) % 16)
        q = 48 + i * 16
        struct.pack_into('<4I', raw, q, key, len(data) << 8 | 2, count,
                         len(raw) - q if count else 0)
        raw += data
    return bytes(raw) + bytes(-len(raw) % 16)


def fixture():
    nodes = b''
    for i, (xyz, profile, slots) in enumerate([
            ((1.0000001192092896, 2., -0.), 0, [0]),
            ((7.25, 3., -2.5), -1, [0, 1]),
            ((20., 4., 0.), 0, [1])]):
        nodes += struct.pack('<3fHhBB7H', *xyz, i, profile, len(slots), 0xaa,
                             *(slots + [0xaaaa] * (7 - len(slots))))
    segments = b''.join(struct.pack('<3Hh4H6b', i, i + 1, 2500 + i, road,
                                    i, 0x9abc, 123, 456, -127, 0, 127, 7, -8, 9)
                        for i, road in enumerate((0, -1)))
    return container(nodes, segments, bytes(range(64)), struct.pack('<HHBBH', 256, 12345, 255, 0x9b, 0xffff))


def payload(raw, key):
    _, flags, count, p = collision_tags(raw, 0x524e6770)[key]
    return raw[p:p + (flags >> 8)] if count else b''


def change(raw, key, relative, fmt, *values):
    out = bytearray(raw)
    p = collision_tags(raw, 0x524e6770)[key][3]
    struct.pack_into(fmt, out, p + relative, *values)
    return bytes(out)


def oversized():
    """A structurally complete u16 graph that violates signed consumers."""
    nodes = b''.join(struct.pack('<3fHhBB7H', 0., 0., 0., j, -1, 0, 0xaa,
                                 *([0xaaaa] * 7)) for j in range(32769))
    return container(nodes, b'')


def broken_variants(merged, first, second):
    """Mutate actual native bytes, independently of the writer/checker."""
    nn = len(payload(first, c.NODES)) // 32
    ns = len(payload(first, c.SEGMENTS)) // 22
    endpoint = struct.unpack_from('<H', payload(second, c.SEGMENTS))[0]
    yield 'unshifted endpoint', change(merged, c.SEGMENTS, ns * 22, '<H', endpoint)
    yield 'duplicated self ID', change(merged, c.NODES, (nn + 1) * 32 + 12, '<H', nn)
    nodes = payload(second, c.NODES)
    j = next(j for j in range(len(nodes) // 32) if nodes[j * 32 + 16])
    yield 'cross-graph adjacency', change(merged, c.NODES, (nn + j) * 32 + 18, '<H', 0)
    yield '32769 nodes', oversized()
    twice = bytearray(merged)
    p = collision_tags(twice, 0x524e6770)[c.NODES][3]
    for j in range(nn, len(payload(merged, c.NODES)) // 32):
        q = p + j * 32
        struct.pack_into('<f', twice, q, struct.unpack_from('<f', twice, q)[0] + 20480.)
    yield 'shift applied twice', bytes(twice)


class Synthetic(unittest.TestCase):
    def setUp(self):
        self.a = fixture()
        self.b = fixture()
        self.merged = c.merge(self.a, self.b)

    def test_order_offsets_sentinels_opaque_bytes(self):
        result = c.check(self.merged, self.a, self.b)
        self.assertEqual(result['counts'], dict(nodes=6, segments=4, profiles=2, roads=2))
        nodes = payload(self.merged, c.NODES)
        self.assertEqual(nodes[:96], payload(self.a, c.NODES))
        self.assertEqual(struct.unpack_from('<Hh', nodes, 96 + 12), (3, 1))
        self.assertEqual(struct.unpack_from('<h', nodes, 128 + 14)[0], -1)
        self.assertEqual(struct.unpack_from('<7H', nodes, 96 + 18), (2,) + (0xaaaa,) * 6)
        segments = payload(self.merged, c.SEGMENTS)
        self.assertEqual(struct.unpack_from('<HH', segments, 44), (3, 4))
        self.assertEqual(struct.unpack_from('<hH', segments, 44 + 6), (1, 2))
        self.assertEqual(struct.unpack_from('<h', segments, 66 + 6)[0], -1)
        for key in (c.PROFILES, c.ROADS):
            self.assertEqual(payload(self.merged, key), payload(self.a, key) + payload(self.b, key))
        # Height, signed zero Z, padding and the opaque segment tail survive.
        self.assertEqual(nodes[96 + 4:96 + 12], payload(self.b, c.NODES)[4:12])
        self.assertEqual(segments[44 + 10:66], payload(self.b, c.SEGMENTS)[10:22])
        self.assertFalse(result['recovery']['subtract_shift_bit_exact'])
        self.assertEqual(result['bridge_segments'], 0)

    def test_five_required_mutations(self):
        rejected = 0
        for name, raw in broken_variants(self.merged, self.a, self.b):
            with self.subTest(name=name), self.assertRaises(FormatError):
                c.check(raw, self.a, self.b)
            rejected += 1
        self.assertEqual(rejected, 5)

    def test_opaque_and_container_corruptions_fail(self):
        for key, relative, fmt, value in (
                (c.SEGMENTS, 44 + 10, '<H', 0),
                (c.ROADS, 8 + 5, '<B', 0),
                (c.ROADS, 8 + 6, '<H', 0),
                (c.PROFILES, 64 + 10, '<B', 255)):
            with self.subTest(key=key, relative=relative), self.assertRaises(FormatError):
                c.check(change(self.merged, key, relative, fmt, value), self.a, self.b)
        out = bytearray(self.merged)
        # Non-road payload location from its own directory entry.
        p = 48 + struct.unpack_from('<I', out, 60)[0]
        out[p] ^= 1
        with self.assertRaisesRegex(FormatError, 'container'):
            c.check(bytes(out), self.a, self.b)

    def test_capacity_checked_before_stride(self):
        with self.assertRaisesRegex(FormatError, 'capacity'):
            c.check(oversized(), self.a, self.b)
        with self.assertRaisesRegex(FormatError, 'capacity'):
            c.merge(self.a, oversized())

    def test_combined_road_budget_boundary(self):
        # Each source fits alone; one extra appended road overflows A* states.
        for nr, valid in ((16381, True), (16382, False)):
            second = container(payload(self.b, c.NODES), payload(self.b, c.SEGMENTS),
                               payload(self.b, c.PROFILES), bytes(nr * 8))
            if valid:
                result = c.check(c.merge(self.a, second), self.a, second)
                self.assertEqual(result['margins']['roads'], 0)
                self.assertEqual(result['astar_states'], 32768)
            else:
                with self.assertRaisesRegex(FormatError, 'capacity'):
                    c.merge(self.a, second)

    def test_custom_physics_xz_and_zero_shift(self):
        for shift in ((0., 0.), (-4096., 1024.)):
            merged = c.merge(self.a, self.b, shift=shift)
            result = c.check(merged, self.a, self.b, shift=shift)
            self.assertEqual(result['shift_physics_xyz'], [shift[0], 0., shift[1]])
            self.assertEqual(result['shift_render_xyz'], [shift[1], -shift[0], 0.])
            if shift == (0., 0.):
                self.assertTrue(result['recovery']['subtract_shift_bit_exact'])
        for shift in ((float('nan'), 0.), (0., float('inf'))):
            with self.assertRaises(FormatError):
                c.merge(self.a, self.b, shift=shift)

    def test_bad_source_stride_range_and_reciprocity(self):
        invalid = [change(self.b, c.NODES, 18, '<H', 2),
                   change(self.b, c.NODES, 14, '<h', -2),
                   change(self.b, c.NODES, 16, '<B', 8),
                   change(self.b, c.SEGMENTS, 6, '<h', 1),
                   change(self.b, c.NODES, 0, '<f', float('nan'))]
        out = bytearray(self.b)
        q = collision_tags(out, 0x524e6770)[c.NODES][0]
        struct.pack_into('<I', out, q + 4, 95 << 8 | 2)
        invalid.append(bytes(out))
        for i, raw in enumerate(invalid):
            with self.subTest(i=i), self.assertRaises(FormatError):
                c.merge(self.a, raw)

    def test_cli_exports_and_missing_assets(self):
        with tempfile.TemporaryDirectory(prefix='c1-roads-') as temp:
            root = Path(temp)
            output = root / 'export'
            c.write_outputs(self.merged, c.check(self.merged, self.a, self.b), output)
            self.assertEqual((output / 'map.carp').read_bytes(), self.merged)
            self.assertEqual(json.loads((output / 'summary.json').read_text())['counts']['nodes'], 6)
            with self.assertRaisesRegex(FormatError, 'exists'):
                c.write_outputs(self.merged, {}, output)
            with self.assertRaisesRegex(FormatError, 'outside'):
                c.write_outputs(self.merged, {}, HERE / 'c1-output-forbidden')
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(c.main(['--carbon-root', str(root), '--mw-root', str(root),
                                         '--out', str(root / 'missing')]), 3)


INPUTS = ((c.DEFAULT_CARBON, 'L5RA'), (c.DEFAULT_MW, 'L2RA'))
ASSETS = all((root / name).is_file() for root, base in INPUTS
             for name in (base + '.BUN', 'STREAM' + base + '.BUN'))


@unittest.skipUnless(ASSETS, 'private track archives unavailable')
class Native(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.maps = [collision_body(one(c.load_index(root, base)[0].parts, 0x3b800))
                    for root, base in INPUTS]
        cls.merged = c.merge(*cls.maps)

    def test_acceptance(self):
        result = c.check(self.merged, *self.maps)
        self.assertEqual(result['counts'], dict(nodes=8988, segments=12328, profiles=1524, roads=2148))
        self.assertEqual(result['offsets'], dict(nodes=4603, segments=5790, profiles=814, roads=840))
        self.assertEqual(result['margins'], dict(nodes=23780, segments=20440, profiles=31244, roads=14234))
        self.assertEqual(result['array_bytes'], 673552)
        self.assertEqual(result['reference_errors'], 0)
        self.assertEqual(result['duplicate_ids'], 0)
        self.assertEqual(result['astar_states'], 4300)
        self.assertEqual(result['recovery']['rounded_coordinates'], 3984)
        self.assertEqual(result['recovery']['max_inverse_error_m'], .0009765625)
        self.assertEqual(result['recovery']['float32_steps_m'], [.0009765625, .001953125])
        self.assertLess(result['longest_segment_m'], 1000.)
        self.assertLess(result['longest_road_m'], 4000.)
        print('C1 native: valid=1; ' + json.dumps(result, sort_keys=True))

    def test_five_required_mutations(self):
        for name, raw in broken_variants(self.merged, *self.maps):
            with self.subTest(name=name), self.assertRaises(FormatError):
                c.check(raw, *self.maps)
        print('C1 native: required broken=5/5 rejected')

    def test_cli(self):
        with tempfile.TemporaryDirectory(prefix='c1-roads-cli-') as temp:
            output = Path(temp) / 'export'
            run = subprocess.run([sys.executable, '-I', str(HERE / 'c1_roads.py'), '--out', str(output)],
                                 capture_output=True, text=True, check=False)
            self.assertEqual(run.returncode, 0, run.stderr[-2000:])
            self.assertEqual((output / 'map.carp').read_bytes(), self.merged)
            summary = json.loads((output / 'summary.json').read_text())
            self.assertEqual(json.loads(run.stdout), summary)


if __name__ == '__main__':
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__]))
    if not result.wasSuccessful():
        raise SystemExit(1)
    if not ASSETS:
        print('SKIP: private track archives unavailable; synthetic checks passed')
        raise SystemExit(3)
