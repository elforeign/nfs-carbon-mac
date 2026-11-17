"""Offline collision-face proof, with no asset writes and synthetic parser checks.

Reference pair: baseline no answer; correct oracle 2/2 (24.860024694 m / none).
Triangle-cache guard: shipped rows refused 0/15,258; original orthogonal
tilted acceptance 1 face -> refused, including every nonzero flag value tested.
Broken scores: scale 1/64 = 0/2, omitted strip 3 = 1/2, swapped X/Z = 1/2.
Literal double-precision band 0 <= node Y - face Y <= 2 m, no ceiling epsilon:
Rockport 2522/4385 (57.5143%); Palmont 2319/4603 (50.3802%).
Misses (surface above <=1mm / only above >1mm / lower layer >2m / no face):
Rockport 1844/2/7/10; Palmont 1924/346/4/10. A separately labelled +1mm
ceiling allowance gives 4366/4385 (99.5667%) and 4243/4603 (92.1790%).

Twelve Palmont miss examples, node id: physics (x,y,z), decoded cause:
1: (-2154.078125,.545134,-2036.647949), surface above by 8.04e-9 m.
6: (-2170.523193,16.286217,-2333.542725), above by 5.28e-7 m.
12: (-1936.872803,17.979969,-1556.272095), above by 1.63e-7 m.
2: (-2098.501221,7.276061,-1994.727417), all faces above, nearest +.226703 m.
11: (-1877.911255,15.563265,-1564.323242), all above, nearest +.288068 m.
15: (-2045.883911,21.976343,-1592.660889), all above, nearest +.348594 m.
1321: (-1288.005493,45.480003,3312.170898), lower layer 10.968900 m below.
1726: (198.856201,44.790897,3474.251465), lower layer 12.874800 m below.
1811: (-1302.054810,46.517700,3322.003906), lower layer 11.237256 m below.
2676: (-12642.875977,18.518906,3853.658447), no projected face (edge .012750 m away).
2759: (-10661.854492,620.599243,3281.316895), no face (edge .064538 m away).
2795: (-12196.097656,59.750896,-4114.845215), no face (edge .064733 m away).
These are geometric classifications, not claims of absent streamed assets.
Missing either game's private archives exits 3 after running synthetic checks.
"""
from dataclasses import replace
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(HERE))
import ground as g
import merge as m
from formats import Chunk, FormatError

SCRATCH = HERE.parents[1] / 'recomp' / 'out' / 'ground-scratch'
MW = Path(os.environ.get('GROUND_MW_TRACKS', str(m.DEFAULT_MW)))
CARBON = Path(os.environ.get('GROUND_CARBON_TRACKS', str(m.DEFAULT_CARBON)))
ASSETS = all((root / name).is_file() for root, base in ((MW, 'L2RA'), (CARBON, 'L5RA'))
             for name in (base+'.BUN', 'STREAM'+base+'.BUN'))


def carp(group, entries):
    """Minimal native relative directory, entirely synthetic."""
    raw = bytearray(32+16*len(entries))
    struct.pack_into('<4I', raw, 0, 0x43415250, 0x2a, 0, 1)
    struct.pack_into('<4I', raw, 16, group, 0x12, len(entries), 1)
    for i, (key, count, data) in enumerate(entries):
        raw += bytes(-len(raw) % 16)
        p = 32+16*i
        struct.pack_into('<4I', raw, p, key, len(data)<<8 | 2, count, len(raw)-p)
        raw += data
    return bytes(raw)


def article(strips):
    raw = bytearray(16+16*len(strips))
    struct.pack_into('<H', raw, 0, len(strips))
    for i, (center, vertices, flags, disabled) in enumerate(strips):
        p = 16+16*i
        struct.pack_into('<3fHH', raw, p, *center, 1000, len(raw)-16)
        for j, v in enumerate(vertices):
            attr = len(vertices) if j == 0 else flags if j == 1 else 0x0800 if j in disabled else 0
            raw += struct.pack('<3hH', *v, attr)
    return bytes(raw)


TRI = [(0, 0, 0), (128, 128, 0), (0, 256, 128)]


def pack_bytes(strips=None, basis=None, translation=(0., 0., 0.)):
    raw = bytearray(64)
    basis = basis or ((1., 0., 0.), (0., 0., 1.))
    struct.pack_into('<3f', raw, 0, *basis[0])
    struct.pack_into('<3f', raw, 32, *basis[1])
    struct.pack_into('<H', raw, 18, 0)
    struct.pack_into('<3f', raw, 48, *translation)
    body = carp(0x41727469, [(0x63690000, 1, raw),
                (0x63610000, 1, article(strips if strips is not None else [((0., 0., 0.), TRI, 2, set())]))])
    return struct.pack('<4I', len(body), 101, 0, 0)+body


def world_fixture(ref=101 << 16):
    desc = struct.pack('<4f2f4I', -4., 0., -8., 1., 4., .25, 6, 3, 0, 1)
    cell = struct.pack('<IHH4B4HI', 0, 3, 0, 1, 0, 0, 0, 0, 4, 4, 4, ref)
    raw = carp(0x43446174, [(0x43477264, 1, desc), (0x4347636e, 1, cell)])
    idx = SimpleNamespace(parts=[Chunk(0x3b800, bytes(8)+raw)], sections=[SimpleNamespace(number=1)])
    p = pack_bytes()
    with patch.object(g, 'read_section', return_value=Chunk(0x3b801, bytes(8)+p).encode()):
        return g.World(idx, None)


class SyntheticTests(unittest.TestCase):
    def test_strip_layout_scale_flags_and_triangle_count(self):
        strips = [((10., 20., 30.), TRI+[(128, 384, 128)], 0, set()),
                  ((-10., -20., -30.), TRI, 1, set()),
                  ((0., 0., 0.), TRI, 0, {2})]
        faces = list(g.Pack(pack_bytes(strips)).faces(0))
        self.assertEqual([(f.strip, f.triangle) for f in faces], [(0, 0), (0, 1), (1, 0)])
        self.assertEqual(faces[0].vertices, ((10., 20., 30.), (11., 21., 30.), (10., 22., 31.)))
        self.assertEqual(faces[1].vertices, ((10., 22., 31.), (11., 21., 30.), (11., 23., 31.)))
        self.assertEqual(faces[2].vertices[0], (-9., -19., -30.))

    def test_refuse_yaw_tilt_and_flagged_identity(self):
        # Old oracle accepted this orthogonal row (one face); the cache reads
        # it without rotation. Refusal prevents that false ground proof.
        p = g.Pack(pack_bytes(basis=((0., 0., 1.), (1., 0., 0.)), translation=(-10., -20., -30.)))
        with self.assertRaisesRegex(FormatError, 'triangle cache'):
            list(p.faces(0))
        for flag in (1, 2, 3, 0x40, 0x80):
            p = g.Pack(pack_bytes())
            raw = bytearray(p.instances)
            struct.pack_into('<H', raw, 18, flag)
            p.instances = bytes(raw)
            with self.assertRaisesRegex(FormatError, 'triangle cache'):
                list(p.faces(0))

    def test_highest_below_including_shared_edges_and_layers(self):
        w = world_fixture()
        self.assertEqual(w.cell_id(.25, .25), 7)
        # Put both layers in the selected cell; the empty neighbor must stay void.
        w.cells[7] = w.cells.pop(3)
        low = g.Face(((0., 1., 0.), (1., 1., 0.), (0., 1., 1.)), 101, 0, 0, 0, 0)
        high = replace(low, vertices=tuple((x, 3., z) for x, y, z in low.vertices), strip=1)
        w._faces[101 << 16] = (low, high)
        self.assertEqual(w.height(.25, .25), 3.)
        self.assertEqual(w.height(.25, .25, 2.), 1.)
        self.assertEqual(w.height(0., 0., 1.), 1.)
        self.assertIsNone(w.height(.25, .25, .999999))
        self.assertIsNone(w.height(.9, .9))
        self.assertIsNone(w.height(4.25, .25))
        self.assertIsNone(w.height(-100., -100.))
        self.assertIsNone(w.height(.25, .25, section=2500))

    def test_grid_row_z_column_x_and_negative_floor(self):
        w = world_fixture()
        self.assertEqual(w.cell_id(-4., -8.), 0)
        self.assertEqual(w.cell_id(-.001, -3.999), 3)
        self.assertEqual(w.cell_id(0., -4.), 4)
        self.assertIsNone(w.cell_id(-4.001, -8.))
        self.assertIsNone(w.cell_id(8., -8.))
        self.assertIsNone(w.cell_id(-4., 16.))
        with self.assertRaises(FormatError): w.cell_id(float('nan'), 0.)

    def test_height_slope_vertical_and_degenerate(self):
        f, = g.Pack(pack_bytes()).faces(0)
        self.assertAlmostEqual(f.height(.25, .25), .75)
        self.assertIsNone(f.height(2., 2.))
        self.assertIsNone(replace(f, vertices=((0., 0., 0.), (0., 1., 0.), (0., 1., 1.))).height(0., 0.))
        self.assertIsNone(replace(f, vertices=((0., 0., 0.),)*3).height(0., 0.))
        self.assertIsNone(replace(f, two_sided=False).height(.25, .25))
        self.assertAlmostEqual(replace(f, two_sided=False, vertices=f.vertices[::-1]).height(.25, .25), .75)

    def test_bad_pack_references_and_strip_extents(self):
        with self.assertRaises(FormatError): world_fixture(999 << 16)
        with self.assertRaises(FormatError): world_fixture((101 << 16) | 1)
        raw = bytearray(pack_bytes())
        struct.pack_into('<I', raw, 0, 5)
        with self.assertRaises(FormatError): g.Pack(raw)
        p = g.Pack(pack_bytes())
        a = bytearray(p.articles[0]); struct.pack_into('<H', a, 30, 65535); p.articles[0] = a
        with self.assertRaises(FormatError): list(p.faces(0))
        with self.assertRaises(FormatError): list(p.faces(1))
        p = g.Pack(pack_bytes()); p.articles.clear()
        with self.assertRaises(FormatError): list(p.faces(0))

    def test_strict_node_band_and_numerical_miss_class(self):
        w = world_fixture(); w.cells[7] = w.cells.pop(3)
        f = g.Face(((0., 1., 0.), (1., 1., 0.), (0., 1., 1.)), 101, 0, 0, 0, 0)
        w._faces[101 << 16] = (f,)
        rows = [(.25, y, .25) for y in (1., 3., 3.000001, .999999, .5)] + [(5., 1., 5.), (.9, 1., .9)]
        report = g.measure_nodes(w, rows)
        self.assertEqual(report['grounded'], 2)
        self.assertEqual(report['near_surface_1mm'], 3)
        self.assertEqual([r['cause'] for r in report['records']], ['grounded', 'grounded',
            'face_more_than_2m_below', 'surface_above_node_within_1mm', 'faces_only_above_node',
            'no_grid_cell', 'no_projected_face'])

    def test_node_files_and_cli(self):
        SCRATCH.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=SCRATCH) as tmp:
            root = Path(tmp)
            for suffix, text in [('csv', 'x,y,z\n1,2,3\n-4,5,6\n'),
                                 ('json', '[[1,2,3], {"x":-4,"y":5,"z":6}]')]:
                path = root / ('nodes.'+suffix); path.write_text(text)
                self.assertEqual(g.read_nodes(path), [(1., 2., 3.), (-4., 5., 6.)])
            path.write_text('[[1,2]]')
            with self.assertRaises(FormatError): g.read_nodes(path)
        w = world_fixture()
        with patch.object(g.World, 'load', return_value=w), patch('builtins.print') as out:
            self.assertEqual(g.main(['unused', '--base', 'L2RA', '--point', '-3', '-3']), 0)
            self.assertEqual(json.loads(out.call_args.args[0])['height'], None)


@unittest.skipUnless(ASSETS, 'private track archives absent')
class RetailTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mw = g.World.load(MW, 'L2RA')
        cls.carbon = g.World.load(CARBON, 'L5RA')

    def reference_score(self, world):
        h = world.height(-160., 2912.)
        return int(h is not None and abs(h-24.86002) <= .001) + int(world.height(-86., 2970.) is None)

    def test_known_points(self):
        w = self.mw
        self.assertEqual(w.cell_id(-160., 2912.), 6604)
        self.assertEqual(w.cell_id(-86., 2970.), 6697)
        self.assertEqual(self.reference_score(w), 2)
        hit = w.find_face_below(-160., 2912.)
        self.assertEqual((hit.face.pack, hit.face.instance, hit.face.strip, hit.face.triangle), (1837, 8, 3, 4))
        print(f'GROUND REFERENCES: (-160,2912)={hit.height:.9f}; (-86,2970)=none; score=2/2')

    def test_three_broken_decoders(self):
        original_faces = g.Pack.faces
        # Mutate quantized vertex decode, not the golden expected height.
        original_unpack = g.unpack
        def wrong_scale(fmt, raw, offset=0):
            values = original_unpack(fmt, raw, offset)
            return tuple(2*v for v in values) if fmt == '<3h' else values
        def omit_strip(pack, instance):
            return (f for f in original_faces(pack, instance) if f.strip != 3)
        original_cell = g.World.cell_id
        original_height = g.Face.height
        scores = []
        for mutation in ('scale_1_64', 'skip_strip_3', 'swap_x_z'):
            self.mw._faces.clear()
            if mutation == 'scale_1_64':
                context = patch.object(g, 'unpack', side_effect=wrong_scale)
            elif mutation == 'skip_strip_3':
                context = patch.object(g.Pack, 'faces', omit_strip)
            else:
                # Swap consistently in both the grid lookup and triangle test.
                context = patch.object(g.World, 'cell_id', lambda w, x, z: original_cell(w, z, x))
            with context:
                if mutation == 'swap_x_z':
                    with patch.object(g.Face, 'height', lambda f, x, z: original_height(f, z, x)):
                        score = self.reference_score(self.mw)
                else:
                    score = self.reference_score(self.mw)
            self.assertEqual(score, 0 if mutation == 'scale_1_64' else 1, mutation)
            scores.append((mutation, score))
        self.mw._faces.clear()
        self.assertEqual(self.reference_score(self.mw), 2)
        print('GROUND BROKEN: correct=2/2; '+', '.join(f'{n}={s}/2' for n, s in scores))

    def test_retail_node_counts(self):
        for name, world, root, base, nodes, good, near, misses in [
                ('Rockport', self.mw, MW, 'L2RA', 4385, 2522, 4366, (1844, 2, 7, 10)),
                ('Palmont', self.carbon, CARBON, 'L5RA', 4603, 2319, 4243, (1924, 346, 4, 10))]:
            report = g.measure_nodes(world)
            self.assertEqual(report['total'], nodes)
            self.assertEqual(report['grounded'], good)
            self.assertEqual(report['near_surface_1mm'], near)
            for cause, count in zip(('surface_above_node_within_1mm', 'faces_only_above_node',
                                     'face_more_than_2m_below', 'no_projected_face'), misses):
                self.assertEqual(report['classes'][cause], count)
            self.assertEqual(sum(report['classes'].values()), nodes)
            self.assertEqual(g.read_nodes(root / (base+'.BUN')), world.nodes)
            if name == 'Palmont':
                examples = {'surface_above_node_within_1mm': (1, 6, 12),
                            'faces_only_above_node': (2, 11, 15),
                            'face_more_than_2m_below': (1321, 1726, 1811),
                            'no_projected_face': (2676, 2759, 2795)}
                for cause, ids in examples.items():
                    for i in ids:
                        row = report['records'][i]
                        self.assertEqual(row['cause'], cause)
                        print('GROUND MISS: '+json.dumps(row, sort_keys=True))
            print(name+' GROUND: '+json.dumps({k:v for k,v in report.items() if k != 'records'}, sort_keys=True))


if __name__ == '__main__':
    result = unittest.main(exit=False, verbosity=2).result
    raise SystemExit(1 if not result.wasSuccessful() else 0 if ASSETS else 3)
