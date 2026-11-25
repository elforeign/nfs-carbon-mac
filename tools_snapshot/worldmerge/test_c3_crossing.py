"""Fixed seam: 11 overlapping pairs -> 0; intact-220 control 0 -> 2 pairs.

Good builds accepted 2/2 (globals off/on); intact-220 builds accepted 0/2,
refused by the existing rule with 220/326 and 220/1238. Written outlines:
0 m uncovered, 0 m covered by both cities over 1,360.516 m at 1 m samples;
326 for 147 m, then 220. Containing sets change for 0/8,988 road nodes.
Each of seven missing cuts and two missing row additions must be rejected.
Default and (4096,-8192), off/on, retain all eight pinned archive hashes.
Facade source-identity repin changes the four stream pins; four indexes stay exact.
Crossing panorama 283 in zone 326: main row 0 FAIL -> rebuilt 1 PASS;
21 -> 22 entries, resident bytes 51,825,324 -> 51,832,116.
Frozen c3dropr1 f1636 draw replay at 960x540: main sky below horizon
2,693 FAIL -> panorama 283 1,009 PASS; left 1,757 -> 73, right 936 -> 936.
Synthetic cases always run; absent private archives exit 3. No game runs.
"""
from collections import Counter
from dataclasses import replace
import math
import shutil
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(HERE))
import c1_world as w
import c3_crossing as seam
import c3_link as link
from formats import Boundary, FormatError, TrackIndex
from test_c1_world import rebuilt_visibility

ASSETS = all((root/name).is_file() for root, base in
             ((w.DEFAULT_MW, 'L2RA'), (w.DEFAULT_CARBON, 'L5RA'))
             for name in (base+'.BUN', 'STREAM'+base+'.BUN'))


def outline(number, polygon):
    raw = bytearray(48)
    struct.pack_into('<hB', raw, 8, number, len(polygon))
    xs, ys = zip(*polygon)
    struct.pack_into('<6f', raw, 24, min(xs), min(ys), max(xs), max(ys),
                     (min(xs)+max(xs))/2, (min(ys)+max(ys))/2)
    return Boundary(bytes(raw)+b''.join(struct.pack('<2f', *p) for p in polygon), True)


def zone_lookup(boundaries):
    rings = [(b.number, b.bounds, b.vertices) for b in boundaries if w.numbers.zone(b.number)]
    def containing(x, z):
        return frozenset(n for n, (z0, nx0, z1, nx1), ring in rings
                         if z0 <= z <= z1 and nx0 <= -x <= nx1
                         and w.numbers.inside((z, -x), ring))
    return containing


class Synthetic(unittest.TestCase):
    def test_fixed_table_axes_winding_bounds_and_untouched_records(self):
        self.assertEqual(seam.CUTS, {205:(6599.95,True), 212:(6599.95,True),
                         220:(6599.95,True), 533:(6599.95,True),
                         326:(6600.05,False), 1238:(6600.05,False), 1334:(6600.05,False)})
        self.assertEqual(seam.ROW_ADDITIONS, {326:(220,260), 220:(366,)})
        square = [(6500., 1.), (6700., 1.), (6700., 5.), (6500., 5.)]
        for number in seam.CUTS:
            for ring in (square, list(reversed(square))):
                original = outline(number, ring)
                cut = seam.apply([original], (), (0,8192))[0][0]
                limit = 6599.95 if number in (205,212,220,533) else 6600.05
                expected = [(min(z,limit) if number in (205,212,220,533) else max(z,limit), x)
                            for z,x in ring]
                # Compare cyclic traversal, not just a set of vertices.
                rotations = [expected[i:]+expected[:i] for i in range(4)]
                self.assertIn(cut.raw, [outline(number,p).raw for p in rotations])
                self.assertEqual(cut.raw[:10]+cut.raw[11:24], original.raw[:10]+original.raw[11:24])
                cut.validate()
        untouched = outline(239, square)
        self.assertIs(seam.apply([untouched], (), seam.SHIFT)[0][0], untouched)

    def test_coast_seam_line_sides_north_cut_and_wrong_side_refused(self):
        self.assertEqual((len(seam.COAST_PALMONT), len(seam.COAST_ROCKPORT)), (29, 11))
        self.assertFalse(set(seam.COAST_PALMONT) & set(seam.COAST_ROCKPORT))
        n, c = seam.COAST_NORMAL, seam.COAST_LINE
        d = lambda p: n[0]*p[0] + n[1]*p[1] - c
        square = [(-200., -200.), (300., -200.), (300., 300.), (-200., 300.)]   # straddles the line
        for number, side in ((913, 1.), (2014, -1.)):
            cut = seam.apply([outline(number, square)], (), seam.COAST_SHIFT)[0][0]
            cut.validate()
            self.assertTrue(all(side*d(p) >= .05 - 1e-3 for p in cut.vertices))
            self.assertTrue(any(abs(side*d(p) - .05) < 1e-3 for p in cut.vertices))
            # The old crossing placement and other placements leave it untouched.
            for shift in (seam.SHIFT, (4096., -8192.)):
                self.assertEqual(seam.apply([outline(number, square)], (), shift)[0][0].raw,
                                 outline(number, square).raw)
        north = seam.apply([outline(1317, [(-900., -900.), (-500., -900.), (-500., 0.), (-900., 0.)])], (),
                           seam.COAST_SHIFT)[0][0]
        self.assertAlmostEqual(max(p[1] for p in north.vertices), seam.COAST_NORTH, places=3)
        with self.assertRaisesRegex(ValueError, 'no part on its own side'):
            seam.apply([outline(913, [(-700., -400.), (-600., -400.), (-600., -350.), (-700., -350.)])], (),
                       seam.COAST_SHIFT)

    def test_sloping_edges_interpolate_the_uncut_axis(self):
        ring = [(6500.,0.),(6700.,200.),(6700.,400.),(6500.,200.)]
        for number, limit, expected in (
                (220,6599.95,[(6500.,0.),(6599.95,99.95),(6599.95,299.95),(6500.,200.)]),
                (326,6600.05,[(6600.05,100.05),(6700.,200.),(6700.,400.),(6600.05,300.05)])):
            cut = seam.apply([outline(number,ring)], (), seam.SHIFT)[0][0]
            rotations = [expected[i:]+expected[:i] for i in range(4)]
            self.assertIn(cut.raw,[outline(number,p).raw for p in rotations])
            self.assertEqual(limit, seam.CUTS[number][0])

    def test_rows_sorted_unique_header_and_other_placements_byte_exact(self):
        rows = []
        for n, entries in ((220,(1,260)), (326,(1,366)), (239,(220,366))):
            header = bytearray(18)
            struct.pack_into('<h',header,12,n)
            header[15] = len(entries)
            struct.pack_into('<h',header,16,len(entries))
            rows.append(w.vis.Row(bytes(header), entries, bytes(2)))
        boundary = outline(220, [(6500,1),(6700,1),(6700,5),(6500,5)])
        for shift in (w.DEFAULT_SHIFT,(4096,-8192),(0,0),(0,8192.0001),(4096,8192)):
            b, r = seam.apply([boundary], rows, shift)
            self.assertIs(b[0],boundary)
            self.assertEqual([x.encode() for x in r], [x.encode() for x in rows])
        _, edited = seam.apply([boundary], rows, seam.SHIFT)
        self.assertEqual([r.entries for r in edited],[(1,260,366),(1,220,260,366),(220,366)])
        self.assertIs(edited[2], rows[2])
        for before, after in zip(rows, edited):
            self.assertEqual(before.header[:15],after.header[:15])
            self.assertEqual(w.vis.read_rows(after.encode()),(after,))

    def test_missing_inputs_exit_three_for_both_cli_forms(self):
        with tempfile.TemporaryDirectory() as tmp:
            for options in ([],['--zones']):
                run = subprocess.run([sys.executable,'-I',str(HERE/'c1_world.py'),
                    '--shift','0','8192','--mw-root',tmp,'--carbon-root',tmp,
                    '--out',str(Path(tmp)/'absent'),*options],capture_output=True,text=True)
                self.assertEqual(run.returncode,3,run.stderr)
                self.assertIn('SKIP',run.stdout)
                self.assertFalse((Path(tmp)/'absent').exists())


@unittest.skipUnless(ASSETS, 'private world archives absent')
class Private(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='c3-crossing-test-')
        cls.addClassCleanup(cls.temp.cleanup)
        cls.root = Path(cls.temp.name).resolve()
        cls.carbon, cls.cs, _ = w.load_index(w.DEFAULT_CARBON,'L5RA')
        cls.source, cls.ms, _ = w.load_index(w.DEFAULT_MW,'L2RA')
        document = w.numbers.plan((cls.source,cls.ms),(cls.carbon,cls.cs))
        cls.schedule = document['composition']
        cls.mapping = {int(k):v for k,v in document['numbers']['rockport'].items()}
        cls.groups = {g['number']:g['members'] for g in cls.schedule['groups']}
        native = w.vis.read(w.vis.payload_of(cls.carbon))
        old = {b.number:b for b in w.vis.read(w.vis.payload_of(cls.source),extended=False).boundaries}
        incoming = [w.union_boundary(old[g['members'][0]],g['number'],g['polygon'],shift=(8192,0))
                    for g in cls.schedule['groups']]
        cls.native_count = len(native.boundaries)
        cls.before = [*native.boundaries,*incoming]
        cls.directory = cls.root/'seamed'
        cls.report = w.build(w.DEFAULT_MW,w.DEFAULT_CARBON,cls.directory,shift=seam.SHIFT)
        cls.index, _, cls.index_raw = w.load_index(cls.directory/'TRACKS','L5RA')
        cls.table = w.vis.read(w.vis.payload_of(cls.index))

    def test_number_serialized_line_nodes_and_rows(self):
        self.assertEqual(len(w._zone_overlaps(self.before[:self.native_count],
                                             self.before[self.native_count:])),11)
        after = self.table.boundaries
        self.assertEqual(w._zone_overlaps(after[:self.native_count],after[self.native_count:]),[])
        g = self.report['grid']
        self.assertEqual((g['rows'],g['columns'],g['occupied']),(215,159,4163))
        before_lookup, after_lookup = zone_lookup(self.before), zone_lookup(after)
        # The connecting road appends nodes; this proof concerns the original
        # two-city nodes and keeps all eight other-placement hash pins below.
        nodes = w.ground.road_nodes(self.index)[:8988]
        self.assertEqual(len(nodes),8988)
        changed = sum(before_lookup(x,z) != after_lookup(x,z) for x,_,z in nodes)
        self.assertEqual(changed,0)
        for n in range(8739,8755):
            x,_,z = nodes[n]
            self.assertEqual(after_lookup(x,z),{239 if n < 8746 else 326})
        e, n = (-2722.1,6740.), (-3120.1,5439.)
        length = math.dist(e,n)
        self.assertAlmostEqual(length,1360.5164460600981)
        uncovered = double = 0.
        order, counts = [], Counter()
        native_ids = {b.number for b in self.before[:self.native_count]}
        for distance in range(math.ceil(length)):
            x,z = (a+(b-a)*distance/length for a,b in zip(e,n))
            hits = after_lookup(x,z)
            metres = min(1.,length-distance)
            uncovered += metres * (not hits)
            double += metres * (bool(hits & native_ids) and bool(hits - native_ids))
            counts[hits] += metres
            if not order or order[-1] != hits:
                order.append(hits)
        self.assertEqual((uncovered,double),(0.,0.))
        self.assertEqual(order,[{326},{220}])
        self.assertEqual(counts[frozenset({326})],147.)
        self.assertAlmostEqual(counts[frozenset({220})],length-147.)
        self.assertEqual(after_lookup(*n),{220})
        sizes = {s.number:s.size for s in self.index.sections}
        totals = {r.number:sum(sizes.get(n,0) for n in set(r.entries)|{2400,2600} if n!=2500)
                  for r in self.table.rows if r.number in (220,326)}
        # C3 re-pin: "Keep crossing GPS on retail road chains and complete its junction"
        # (base 6df9b36e): current serialized tile and resident scene rows.
        self.assertEqual(self.report['grid']['tile_bytes'],379872)
        self.assertEqual(totals,{326:51125052,220:55217976})
        panorama = next(r for r in self.table.rows if r.number == 326)
        self.assertEqual(panorama.entries.count(283),1)
        self.assertEqual(len(panorama.entries),22)
        self.assertTrue(all(n <= w.POOL_BYTES for n in totals.values()))
        print(f'SEAM line={length:.6f} uncovered={uncovered:g} double={double:g}; '
              f'326=147m then 220; nodes changed={changed}/{len(nodes)}; rows={totals}')

    def test_control_intact_220_refused_before_publication(self):
        cuts = {n:v for n,v in seam.CUTS.items() if n != 220}
        with patch.dict(seam.CUTS,cuts,clear=True):
            for zones in (False,True):
                out = self.root/f'refused-{zones}'
                with self.assertRaisesRegex(FormatError,
                        r'zone-class polygon overlap.*220/326, 220/1238 \(2 pairs total\)') as failure:
                    w.build(w.DEFAULT_MW,w.DEFAULT_CARBON,out,shift=seam.SHIFT,zones=zones)
                self.assertFalse(out.exists())
                print('CONTROL',failure.exception)
        self.assertFalse(list(self.root.glob('.c1-world-*')))

    def test_checker_requires_each_cut_and_row_addition(self):
        originals = {b.number:b for b in self.before}
        for number in (205,212,220,533,326,1238,1334):
            with self.subTest(outline=number):
                raw = b''.join((originals[number] if b.number==number else b).raw
                               for b in self.table.boundaries)
                index = TrackIndex(rebuilt_visibility(TrackIndex(self.index_raw),{w.vis.BOUNDARIES:raw}))
                with self.assertRaisesRegex(FormatError,'native boundaries|source polygon'):
                    w._check_visibility(index,self.carbon,self.source,self.mapping,self.groups,(8192,0))
        for number, remove in ((326,220),(326,260),(220,366)):
            with self.subTest(row=number,entry=remove):
                rows = []
                for row in self.table.rows:
                    if row.number==number:
                        entries = tuple(n for n in row.entries if n != remove)
                        # Keep the stride/cap and fill the newly unused slot.
                        header = bytearray(row.header)
                        struct.pack_into('<h',header,16,len(entries))
                        row = replace(row,header=bytes(header),entries=entries,spare=bytes(4))
                    rows.append(row.encode())
                index = TrackIndex(rebuilt_visibility(TrackIndex(self.index_raw),{w.vis.ROWS:b''.join(rows)}))
                with self.assertRaisesRegex(FormatError,'native visibility row|source entry union'):
                    w._check_visibility(index,self.carbon,self.source,self.mapping,self.groups,(8192,0))

    def test_zones_on_and_independent_full_checker(self):
        directory = self.root/'seamed-zones'
        report = w.build(w.DEFAULT_MW,w.DEFAULT_CARBON,directory,zones=True,shift=seam.SHIFT)
        self.assertEqual(report['files']['STREAML5RA.BUN'],self.report['files']['STREAML5RA.BUN'])
        for path, expected in ((self.directory,self.report),(directory,report)):
            # The link checker rebuilds an ordinary reference before reading
            # its delta. Cache that writer stage outside the reader-only
            # guard; all provenance and exact-delta checks still run inside.
            reference = self.root/f'reference-{path.name}'
            reference.mkdir()
            index, stream, _ = w.load_index(path/'TRACKS', 'L5RA')
            link.project_base(reference/'TRACKS', index, stream,
                              w.DEFAULT_CARBON, w.DEFAULT_MW)
            def cached_reference(tracks, *_):
                shutil.copytree(reference/'TRACKS', tracks)
            (path/'proof.json').write_text('{"forged":true}\n')
            with patch.object(link,'project_base',side_effect=cached_reference), \
                 patch.object(w.numbers,'plan',side_effect=AssertionError('reader used plan')), \
                 patch.object(w,'union_boundary',side_effect=AssertionError('reader used writer')), \
                 patch.object(w.c1_zones,'merge',side_effect=AssertionError('reader used merger')), \
                 patch.object(w.zone_tables,'convert',side_effect=AssertionError('reader used converter')):
                self.assertEqual(w.check(path,shift=seam.SHIFT),expected)

    def test_other_placement_hashes(self):
        pins = (
            (w.DEFAULT_SHIFT,False,'cc154fc5746163678b855231301857105de67c50644527171228973172fa3b7e',
             'd557254bd412fd8033c717cde955d54f823f9330894e10e01f59e4f38bb57bcd'),
            (w.DEFAULT_SHIFT,True,'b32d7c45a83176d464bf8f1d5518c9bebacfc8ffec3a5667d933beb4c9c48aa6',
             'd557254bd412fd8033c717cde955d54f823f9330894e10e01f59e4f38bb57bcd'),
            ((4096,-8192),False,'b28990b1deb95623b54d56f47b738aa13f83c094d505886331c5033ebbe2ec3f',
             '2481ff9cc0a007313e8f64a2a6dd3ff62538b6d283ddc4fd49eeec847c739709'),
            ((4096,-8192),True,'ac4b982d5720b9d61788f3fa13ede7cd5fe71f58221f256e68722748e00ffdbb',
             '2481ff9cc0a007313e8f64a2a6dd3ff62538b6d283ddc4fd49eeec847c739709'))
        for shift,zones,index_hash,stream_hash in pins:
            with self.subTest(shift=shift,zones=zones), tempfile.TemporaryDirectory(dir=self.root) as tmp:
                report = w.build(w.DEFAULT_MW,w.DEFAULT_CARBON,Path(tmp)/'pair',shift=shift,zones=zones)
                self.assertEqual(report['files']['L5RA.BUN']['sha256'],index_hash)
                self.assertEqual(report['files']['STREAML5RA.BUN']['sha256'],stream_hash)
        print('GUARD default/nearby off/on: all eight hashes equal pinned values')


if __name__ == '__main__':
    result = unittest.main(exit=False)
    sys.exit(1 if not result.result.wasSuccessful() else 0 if ASSETS else 3)
