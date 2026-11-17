"""Collision track proof: baseline no track; valid build 2779 cells/390 packs,
0 reader rejects; built grounding 2522/4385, equal to source. Broken archives:
tile moved to nonresident 2501, one referenced pack removed, duplicate cell id:
valid checker 1/1; broken checker 0/3 (each rejected). Nonresident tiles retain
2522/4385 in the geometric union oracle, so residency needs the reader checker.
Eight float32 starts: 8/8 strict faces within 2 m, exact render/physics round trip.
Missing private assets: synthetic checks run, then exit 3. No game launches.
"""
from pathlib import Path
import json
import math
import struct
import sys
import tempfile
from types import SimpleNamespace
import unittest

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(HERE))
import rockport_track as t
import collision as c
import ground as g
import merge as m
import region as r
from formats import Chunk, FormatError, Section, TrackIndex, chunks, u32

ASSETS = all((root / name).is_file()
             for root, bases in ((m.DEFAULT_MW, ('L2RA',)), (m.DEFAULT_CARBON, ('L5RA', 'L5RB')))
             for base in bases for name in (base + '.BUN', 'STREAM' + base + '.BUN'))


def carp(groups):
    """Synthetic relative CARP directory; contains no source asset literals."""
    group_start = 16
    tag_start = group_start + 16 * len(groups)
    raw = bytearray(tag_start + 16 * sum(len(tags) for _, tags in groups))
    struct.pack_into('<4I', raw, 0, 0x43415250, 0x2a, len(groups) - 1, 1)
    tag = tag_start
    for i, (key, entries) in enumerate(groups):
        q = group_start + 16 * i
        struct.pack_into('<4I', raw, q, key, 0x12, len(entries), (tag - q) // 16)
        for key, count, data in entries:
            raw += bytes(-len(raw) % 16)
            flags = 3 if key == c.RECT else 2
            struct.pack_into('<4I', raw, tag, key, len(data) << 8 | flags, count, len(raw) - tag)
            raw += data
            tag += 16
    return bytes(raw)


def fixture():
    desc = struct.pack('<6f4I', -100., 0., -100., 0., 64., 1/64, 4, 4, 0, 1)
    records = [struct.pack('<IHH4B4HI', 0, cid, 2500, 1, 0, 0, 0, 0, 4, 4, 4, 101 << 16)
               for cid in (5, 6)]
    map_data = carp([(c.CDAT, [(c.CGRD, 1, desc), (c.RECT, 1, struct.pack('<5H', 2500, 1, 1, 2, 1))]),
                     (c.RNGP, [(0x524e7367, 1, bytes(16))])])
    pack = carp([(0x41727469, [(0x63690000, 1, bytes(64))])])
    pack = struct.pack('<4I', len(pack), 101, 0, 0) + pack
    parts = [Chunk(0x34112, b''), Chunk(0x80034150, b''), Chunk(0x34110, b''), Chunk(0x3b800, b'')]
    sections = []
    for number in (2400, 2600, 2500):
        raw = bytearray(92)
        struct.pack_into('<h', raw, 8, number)
        sections.append(Section(bytes(raw)))
    return t.build(SimpleNamespace(parts=parts, sections=sections),
                   SimpleNamespace(map_data=map_data, tile=c.make_tile(records), packs=(pack,)))


def bodies(index, stream, kind):
    """Read indexed stream chunks; retain absolute body offsets for mutations."""
    for section in TrackIndex(index).sections:
        for chunk in chunks(stream[section.offset:section.offset + section.size]):
            if chunk.kind == kind:
                pad = -(chunk.offset + 8) % 16
                yield section, chunk, section.offset + chunk.offset + 8 + pad, r.collision_body(chunk)


def broken(index, stream, variant):
    idx = TrackIndex(index)
    out = bytearray(stream)
    _, _, p, tile = next(bodies(index, stream, 0x3b802))
    tile_tags = r.collision_tags(tile[16:], 0x41727469)
    cell_tag = tile_tags[c.CGCN]
    cells = r.collision_cells(tile[16:], cell_tag)
    first = p + 16 + cell_tag[3]
    if variant == 'duplicate_cell':
        struct.pack_into('<H', out, first + len(cells[0]) + 4, struct.unpack_from('<H', cells[0], 4)[0])
    elif variant == 'missing_pack':
        key = u32(cells[0], 20) >> 16
        section, chunk, _, _ = next(b for b in bodies(index, stream, 0x3b801) if u32(b[3], 4) == key)
        struct.pack_into('<I', out, section.offset + chunk.offset, 0)
    elif variant == 'nonresident_tile':
        # Change every related section field so geometry alone still passes.
        # 007A4680 never requests this section without optional/scenery slots.
        for i, section in enumerate(idx.sections):
            if section.number == 2500:
                raw = bytearray(section.raw)
                struct.pack_into('<h', raw, 8, 2501)
                idx.sections[i] = Section(bytes(raw))
        struct.pack_into('<I', out, p + 4, 2501)
        offset = first
        for record in cells:
            struct.pack_into('<H', out, offset + 6, 2501)
            offset += len(record)
        top = r.one(idx.parts, 0x3b800)
        raw = bytearray(top.payload)
        pad = -(top.offset + 8) % 16
        tag = r.collision_tags(raw[pad:], c.CDAT)[c.RECT]
        struct.pack_into('<H', raw, pad + tag[3], 2501)
        idx.parts[idx.parts.index(top)] = Chunk(top.kind, bytes(raw), top.offset)
    else:
        raise ValueError(variant)
    return idx.encode(), bytes(out)


def write_pair(directory, index, stream):
    path = Path(directory)
    (path / 'L2RA.BUN').write_bytes(index)
    (path / 'STREAML2RA.BUN').write_bytes(stream)
    return path


class SyntheticTests(unittest.TestCase):
    def test_reader_accepts_valid_synthetic_and_rejects_all_broken_archives(self):
        index, stream = fixture()
        checked = t.check_track(index, stream)
        self.assertEqual((checked['cells'], checked['packs'], checked['rejects']), (2, 1, 0))
        for variant in ('nonresident_tile', 'missing_pack', 'duplicate_cell'):
            with self.subTest(variant=variant), self.assertRaises(FormatError):
                t.check_track(*broken(index, stream, variant))

    def test_negative_local_coordinates_are_unsafe_even_with_native_signed_comparison(self):
        index, stream = fixture()
        _, _, p, tile = next(bodies(index, stream, 0x3b802))
        first = p + 16 + r.collision_tags(tile[16:], 0x41727469)[c.CGCN][3]
        out = bytearray(stream)
        struct.pack_into('<H', out, first + 4, 0)
        with self.assertRaisesRegex(FormatError, 'acceptance rejects'):
            t.check_track(index, bytes(out))

    def test_missing_inputs_exit_three(self):
        with tempfile.TemporaryDirectory(prefix='rocktrack-missing-') as temp:
            self.assertEqual(t.main(['--mw-root', temp, '--carbon-root', temp,
                                     '--out', str(Path(temp) / 'absent')]), 3)
            self.assertFalse((Path(temp) / 'absent').exists())

    def test_output_in_checkout_rejected_before_writing(self):
        index, stream = fixture()
        with self.assertRaisesRegex(FormatError, 'outside the checkout'):
            t.write_outputs(t.ROOT / 'recomp' / 'out' / 'forbidden', index, stream, {})


@unittest.skipUnless(ASSETS, 'private track archives absent')
class PrivateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index, cls.stream, cls.report = t.prepare()
        cls.source, cls.source_stream, _ = m.load_index(m.DEFAULT_MW, 'L2RA')
        cls.source_raw = r.collision_body(r.one(cls.source.parts, 0x3b800))
        tag = r.collision_tags(cls.source_raw, c.CDAT)[c.CGCN]
        cls.source_cells = {struct.unpack_from('<H', record, 4)[0]: record
                            for record in r.collision_cells(cls.source_raw, tag)}
        cls.source_packs = {}
        for section in cls.source.sections:
            for chunk in chunks(m.read_section(cls.source_stream, section)):
                if chunk.kind == 0x3b801:
                    body = r.collision_body(chunk)
                    key = u32(body, 4)
                    if key in cls.source_packs:
                        raise AssertionError('duplicate source pack')
                    cls.source_packs[key] = body

    def test_built_reader_counts_and_byte_identity_against_original_index(self):
        checked = t.check_track(self.index, self.stream)
        self.assertEqual((checked['cells'], checked['packs'], checked['rejects']), (2779, 390, 0))
        self.assertEqual(checked['reference_families'], [21112, 0, 0, 17718])
        self.assertEqual(checked['rectangle'], [2500, 3, 3, 88, 100])
        self.assertEqual(checked['tile_bytes'], 211200)
        self.assertEqual((checked['pointer_slots'], checked['pointer_bytes']), (8800, 35200))
        _, _, _, tile = next(bodies(self.index, self.stream, 0x3b802))
        cells = r.collision_cells(tile[16:], r.collision_tags(tile[16:], 0x41727469)[c.CGCN])
        actual = {}
        for record in cells:
            cid = struct.unpack_from('<H', record, 4)[0]
            self.assertEqual(struct.unpack_from('<H', record, 6)[0], 2500)
            actual[cid] = record[:6] + b'\0\0' + record[8:]
        self.assertEqual(actual, self.source_cells)
        packs = {u32(body, 4): body for _, _, _, body in bodies(self.index, self.stream, 0x3b801)}
        self.assertEqual(packs, self.source_packs)
        self.assertEqual(sum(map(len, packs.values())), 5799008)
        raw = r.collision_body(r.one(TrackIndex(self.index).parts, 0x3b800))
        for key, tag in r.collision_tags(self.source_raw, c.RNGP).items():
            built_tag = r.collision_tags(raw, c.RNGP)[key]
            self.assertEqual(tag[1:3], built_tag[1:3])
            self.assertEqual(c.tag_data(self.source_raw, tag), c.tag_data(raw, built_tag))
        suffix = lambda b: b[min(tag[3] for tag in r.collision_tags(b, c.RNGP).values() if tag[2]):]
        self.assertEqual(suffix(raw), suffix(self.source_raw))

    def test_serialized_ground_count_and_eight_nearest_octant_starts(self):
        source_measurement = g.measure_nodes(g.World(self.source, self.source_stream))
        with tempfile.TemporaryDirectory(prefix='rocktrack-proof-') as temp:
            directory = Path(temp) / 'track'
            t.write_outputs(directory, self.index, self.stream, self.report, (m.DEFAULT_MW, m.DEFAULT_CARBON))
            world = g.World.load(directory, 'L2RA')
            measured = g.measure_nodes(world)
            self.assertEqual((measured['grounded'], measured['total']), (2522, 4385))
            # Ignore region ids; geometry and strict classification must match.
            for source, built in zip(source_measurement['records'], measured['records']):
                self.assertEqual((source['node'], source['height'], source['gap'], source['cause']),
                                 (built['node'], built['height'], built['gap'], built['cause']))
            starts = self.report['starts']
            self.assertEqual(len(starts), 8)
            self.assertEqual(len({s['node'] for s in starts}), 8)
            nodes = world.nodes
            for i, start in enumerate(starts):
                tx, tz = start['target_physics_xz']
                centre = [(min(p[k] for p in nodes) + max(p[k] for p in nodes)) / 2 for k in (0, 2)]
                radii = [(max(p[k] for p in nodes) - min(p[k] for p in nodes)) / 4 for k in (0, 2)]
                self.assertEqual((tx, tz), (centre[0] + radii[0] * math.cos(i * math.pi / 4),
                                           centre[1] + radii[1] * math.sin(i * math.pi / 4)))
                nearest = min((row for row in measured['records'] if row['cause'] == 'grounded'),
                              key=lambda row: ((row['x']-tx)**2 + (row['z']-tz)**2, row['node']))
                self.assertEqual(start['node'], nearest['node'])
                rx, ry, rz = start['render_xyz']
                self.assertEqual([-ry, rz, rx], start['physics_xyz'])
                self.assertEqual([t.f32(float(v)) for v in start['skipfe_start'].split(',')], start['render_xyz'])
                height = world.height(-ry, rx, rz, section=2500)
                self.assertEqual(height, start['ground_height'])
                self.assertTrue(0 <= rz - height <= 2)
            proof = json.loads((directory / 'proof.json').read_text())
            self.assertEqual(proof, self.report)
            for name, expected in proof['outputs'].items():
                data = (directory / name).read_bytes()
                self.assertEqual((len(data), t.sha(data)), (expected['bytes'], expected['sha256']))

    def test_three_broken_built_files_fail_checker_or_grounding(self):
        self.assertEqual(t.check_track(self.index, self.stream)['rejects'], 0)
        for variant in ('nonresident_tile', 'missing_pack', 'duplicate_cell'):
            index, stream = broken(self.index, self.stream, variant)
            with self.subTest(variant=variant), self.assertRaises(FormatError):
                t.check_track(index, stream)
            with tempfile.TemporaryDirectory(prefix='rocktrack-broken-') as temp:
                tracks = write_pair(temp, index, stream)
                if variant == 'nonresident_tile':
                    measured = g.measure_nodes(g.World.load(tracks, 'L2RA'))
                    self.assertEqual((measured['grounded'], measured['total']), (2522, 4385))
                else:
                    with self.assertRaises(FormatError):
                        g.World.load(tracks, 'L2RA')

    def test_spawn_clearance_is_the_single_inferred_height_parameter(self):
        with tempfile.TemporaryDirectory(prefix='rocktrack-starts-') as temp:
            world = g.World.load(write_pair(temp, self.index, self.stream), 'L2RA')
            measured = g.measure_nodes(world)
            starts = t.select_starts(world, measured, 1.25)
            self.assertEqual([s['node'] for s in starts], [s['node'] for s in self.report['starts']])
            for start in starts:
                self.assertAlmostEqual(start['clearance'], 1.25, places=4)
            for invalid in (0, -1, 2.1, float('nan'), float('inf')):
                with self.assertRaises(FormatError):
                    t.select_starts(world, measured, invalid)


if __name__ == '__main__':
    result = unittest.main(exit=False, verbosity=2).result
    raise SystemExit(1 if not result.wasSuccessful() else 0 if ASSETS else 3)
