"""Coast link deck: both end rows on a non-planar steep road, a continuous twisted deck.

Synthetic road at each end: 14 % (Palmont) and -16 % (Rockport) across the deck
with a 0.28 m sag over 32 m, the shape measured at nodes 1014 and 784. The deck's
worst junction step over 129 samples is 0.000 m at the end rows (limit 0.10 m);
the broken control, a planar deck end through the two road edges (the flat-piece
design), leaves 0.28 m and fails. Copies meet with no height step at every seam.
The donor map takes a 0.2 degree wedge to fractions 0/1 on its own cuts.
Scenery removal: a dropped instance's physics spawn goes and its override row
points at the absent scene 0, every later instance's row shifts down by the
dropped ones before it (unchanged rows would name the wrong instance: 2 of 4
rows in the control). A rail standing 0-1.4 m on the deck is in the driving
volume; the same rail with its top 0.5 m under the deck is not.
Rail collision: walls at the rails' inner face cover both edges 100 % (built pair: 2 x 180 walls);
copies without them (pair_c, where a car left the deck over its left edge) cover 0 %.
Synthetic checks run without archives; drive-three controls also decode private archives when available.

Second-drive controls: the fixed 6 % tangent against a 1 % road breaks by 2.86 degrees;
the measured tangent is continuous. A donor-spaced end bridges a 30 mm crown depression;
the sampled collision follows it within 8 mm. Full-length rails occupy both road openings;
trimmed rails do not. The resident reflection sky's old 0x480 flags pass the scenery gate;
its new flags exclude both gates while retaining the model and transform.
The old 30 cm driving-volume floor misses a 6 cm runoff overlap (0 hits);
the 3 cm floor detects it (1 hit), while a surface below the deck is clear.
Query-cell control: the unfiltered neighbouring face reports 0.20 m; the selected
cell reports 0 m. Long-triangle control misses the curve by 0.8 m; refinement
limits it to 0.01 m. Written outer-cut control without the overlap breaks by
11.902 degrees at the curb sliver; the final overlap gives 0.744 degrees.

Far-view controls, cross-checked against the saved pre-change pair: required
scene memberships missing 30 -> 0 across five rows; Rockport's beach dependency
1 -> 0. The completed rows peak at 66,730,856 bytes (limit 71,680,000);
an otherwise complete row at 71,680,001 is rejected. A secondary-LOD model
and an unindexed texture each produce one provider failure, versus zero for
the closed fixture. The old primary-only/known-textures-only scan misses both.
Precull control: the native terrain masks hide 6,602 instance/camera pairs over
18,675 corridor camera points; the open corridor hides 0. Synthetic bit control: 1 -> 0.
Pack header control: borrowed-scenery solid packs (sections 1940, 1980, 1982-1989) with an
80-byte 0x134002 chunk (the game writes 144 bytes there and corrupts the next chunks, so
quitting calls a freed mesh): 10 -> 0 short headers.

Drive-three archive checks: surface misses 0/3,131 (outward-cut control 612);
unjoined corner gap 0.000 m (control 1.8566 m); carriageway overpaint 0.00 m2
(straight-cut control approximately 65.76 m2). Near panorama wall overlaps 0
(control 366 triangle pairs); borrowed yellow cards 0 (control 100 quads).
Known-provider misses 0 per affected row (control 55); every row stays within
71,680,000 bytes. Each control is exercised against decoded native geometry.

Scale-1 route 1031@1013 to 12330@8990, after three frontier pops:
pinned parent walk 3 -> 501 -> 501, split walk 3 -> 4303 -> 1 -> 0xffff.
Across 4,264 ordinary junction arrivals, duplicate keys: pinned 4, split 0.
"""
from collections import Counter
import math
import hashlib
import inspect
import shutil
import struct
import tempfile
from pathlib import Path
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(HERE))

import c3_coast_link as C


class Hit:
    def __init__(self, height):
        self.height = height


class Road:
    """Two road ends 745 m apart; each 14 %/-16 % across the deck, sagging 0.28 m."""

    def __init__(self, nodes):
        self.origin, self.length, self.x, self.z = C.frame(nodes)

    def find_face_below(self, x, z, below):
        d = (x-self.origin[0], z-self.origin[2])
        s, l = d[0]*self.x[0]+d[1]*self.x[2], d[0]*self.z[0]+d[1]*self.z[2]
        sag = .28*(1-(l/16.)**2)
        if s < 100:
            return Hit(8.8+.14*l-sag+.01*s)
        return Hit(25.6-.16*l-sag+.01*(self.length-s))


def nodes():
    out = [(0., 0., 0.)]*6000
    out[C.PALMONT] = (1668.689, 8.792, 3167.140)
    out[C.ROCKPORT] = (1921.698, 25.633, 2465.631)
    return out


def step(deck, road, s, planar=False):
    worst = 0.
    for i in range(129):
        l = -16.+32.*i/128
        if planar:
            ends = [road.find_face_below(*deck.point(s, e)[0::2], 1e9).height for e in (-16., 16.)]
            h = ends[0]+(ends[1]-ends[0])*(l+16.)/32.
        else:
            h = deck.height(s, l)
        q = deck.point(s, l)
        worst = max(worst, abs(h-road.find_face_below(q[0], q[2], 1e9).height))
    return worst


class DeckTest(unittest.TestCase):
    def setUp(self):
        self.road = Road(nodes())
        self.deck = C.Deck(self.road, nodes())

    def test_left_overlap_is_a_seam_control_one_false_obstacle(self):
        """20 mm overlap false obstacles: 1 -> 0; a face beyond it still reports 1."""
        deck = self.deck
        def triangle(edge):
            return [deck.point(deck.s0+30, -16., .06), deck.point(deck.s0+31, -16., .06),
                    deck.point(deck.s0+30, edge, .06)]
        frozen = 'abs(l) < 15.9975'
        self.assertEqual(hashlib.sha256(frozen.encode()).hexdigest(), '34766356fdc4eaaa05a804ef891f79188488704ff8e39362fbb76257f0cc87eb')
        env = dict(C.__dict__)
        exec(inspect.getsource(C._in_volume).replace('-15.9795 < l < 15.9975', frozen), env)
        self.assertTrue(env['_in_volume'](deck, triangle(-15.98)))
        self.assertFalse(C._in_volume(deck, triangle(-15.98)))
        self.assertTrue(C._in_volume(deck, triangle(-15.97)))

    def test_end_rows_follow_the_road(self):
        for s in (self.deck.s0, self.deck.s1):
            self.assertLessEqual(step(self.deck, self.road, s), .10)

    def test_measured_tangents_remove_the_fixed_grade_break(self):
        for s, grade in ((self.deck.s0, .01), (self.deck.s1, -.01)):
            for l in (-12., -4., 0., 4., 12.):
                ds = (self.deck.height(s+.001, l)-self.deck.height(s-.001, l))/.002
                # The endpoint derivative is one-sided: outside the deck is the native road.
                if s == self.deck.s0:
                    ds = (self.deck.height(s+.001, l)-self.deck.height(s, l))/.001
                else:
                    ds = (self.deck.height(s, l)-self.deck.height(s-.001, l))/.001
                self.assertLess(abs(math.degrees(math.atan(ds))-math.degrees(math.atan(grade))), .001)
                outward = -.3 if s == self.deck.s0 else .3
                exterior = (self.deck.height(s+outward, l)-self.deck.height(s, l))/outward
                self.assertLess(abs(math.degrees(math.atan(exterior))-math.degrees(math.atan(grade))), .001)
        fixed = math.degrees(math.atan(.06))-math.degrees(math.atan(.01))
        self.assertGreater(fixed, 2.)

    def test_curb_step_does_not_extend_as_a_narrow_ridge(self):
        from types import SimpleNamespace
        class Curb(Road):
            def find_face_below(self, x, z, below):
                h = super().find_face_below(x,z,below).height
                dx,dz = x-self.origin[0], z-self.origin[2]
                s,l = dx*self.x[0]+dz*self.x[2], dx*self.z[0]+dz*self.z[2]
                hit = Hit(h+(.1 if s>self.length-C.ROCKPORT_INSET+.2 and 5<l<7 else 0))
                # Every face at the cut has the same along grade; a later query can hit a curb.
                grade = .01 if s<100 else -.01
                hit.face = SimpleNamespace(vertices=((x,h,z),(x+self.x[0],h+grade,z+self.x[2]),
                                                     (x+self.z[0],h,z+self.z[2])))
                return hit
        road = Curb(nodes())
        deck = C.Deck(road,nodes())
        self.assertLess(max(deck.gb)-min(deck.gb), 1e-10)
        q = deck.point(deck.s1,6.)
        control = road.find_face_below(q[0]+deck.x[0],q[2]+deck.x[2],100).height-road.find_face_below(q[0],q[2],100).height
        self.assertGreater(abs(control-C.interp(deck.gb,6.)), .09)

    def test_planar_end_control_fails(self):
        worst = step(self.deck, self.road, self.deck.s0, planar=True)
        self.assertGreater(worst, .10)
        self.assertAlmostEqual(worst, .28, places=2)

    def test_twist_runs_between_end_slopes(self):
        cross = [(self.deck.height(s, 8.)-self.deck.height(s, -8.))/16.
                 for s in (self.deck.s0, self.deck.s1)]
        self.assertAlmostEqual(cross[0], .14, places=3)
        self.assertAlmostEqual(cross[1], -.16, places=3)

    def test_copies_meet_at_every_seam(self):
        starts, length = C.pieces(self.deck)
        self.assertEqual(len(starts), 19)  # the asphalt cut extends beyond the native node
        donor = C.Donor(*cuts(.1))
        moves = [C.mapper(self.deck, donor, s, length) for s in starts]
        high, low = cuts(.1)
        for a, b in zip(moves, moves[1:]):
            for p, q in zip(high, low):
                self.assertLess(math.dist(a(p), b(q)), 1e-6)

    def test_collision_strips_share_one_point(self):
        """The shipped donor stores one vertex in two strips 1/128 m apart in height (and a few mm
        apart across), and its cuts 0.07 m short of 0/1. On the deck: the residual map gives a
        7.8 mm step and a 7 cm gap at the seam (control); the collision map gives neither."""
        starts, length = C.pieces(self.deck)
        high, low = cuts(.1)
        donor = C.Donor(high, low)
        a, b = (10., .66, 2.), (10.004, .66+1/128, 2.003)       # one vertex, two strips
        end = (40.-.07, 2.64-.07*.066, 6.)                       # a cut vertex 0.07 m short of f = 1
        vertices = [*high, *low, a, b, end]
        def old(p):             # the bake before the fix: donor residual kept, cuts where they lie
            f, l, h = donor.canonical(p)
            return self.deck.point(starts[0]+f*length, l, h)
        self.assertGreater(abs(old(a)[1]-old(b)[1]), .007)
        new = [C.collision_mapper(self.deck, donor, s, length, vertices) for s in starts[:2]]
        self.assertEqual(new[0](a), new[0](b))
        self.assertEqual(new[0](end), new[1]((-.05, -.05*.066, 6.07)))     # the next copy's cut vertex
        self.assertGreater(math.dist(old(end), self.deck.point(starts[1], 6.)), .06)
        for p in (a, end):      # on the deck surface itself
            q = new[0](p)
            s, l = C._sl(self.deck, q)
            self.assertAlmostEqual(q[1], self.deck.height(s, l), places=9)


def cuts(skew):
    """A 32 x 40 m donor rising 6.6 %, its cuts +-skew degrees off square."""
    t = math.tan(math.radians(skew))
    low = [(-l*t, 0., l) for l in (-16., -14., -10., -6., -2., 2., 6., 10., 14., 16.)]
    high = [(40.+l*t, 2.64, l) for l in (-16., -14., -10., -6., -2., 2., 6., 10., 14., 16.)]
    return high, low


class DonorTest(unittest.TestCase):
    def test_wedge_maps_to_fractions(self):
        high, low = cuts(.1)
        donor = C.Donor(high, low)
        for p in low:
            self.assertAlmostEqual(donor.canonical(p)[0], 0., places=9)
            self.assertAlmostEqual(donor.canonical(p)[2], 0., places=9)
        for p in high:
            self.assertAlmostEqual(donor.canonical(p)[0], 1., places=9)


class Root:
    def __init__(self, payload, kind=0x34027, offset=8):
        self.kind, self.payload, self.offset = kind, payload, offset


class DropTest(unittest.TestCase):
    DROP = {1833: {56: 'XT_CT_Tree_Windbreak1', 243: 'XS_Speed60'}}

    def setUp(self):
        self.rows = b''.join(struct.pack('<3H', *r, 0) for r in
                             ((1833, 22), (1833, 243), (1833, 244), (925, 243), (1833, 57)))

    def test_rows_rebased_and_tombstoned(self):
        orig = C.DROP
        try:
            C.DROP = self.DROP
            rows = [struct.unpack_from('<2H', C.rebased_overrides(self.rows), p) for p in range(0, 30, 6)]
        finally:
            C.DROP = orig
        self.assertEqual(rows, [(1833, 22), (0, 0), (1833, 242), (925, 243), (1833, 56)])
        control = [struct.unpack_from('<2H', self.rows, p) for p in range(0, 30, 6)]
        self.assertEqual(sum(a != b and a != (0, 0) for a, b in zip(rows, control)), 2)

    def test_spawn_of_dropped_instance_removed(self):
        records = [bytes(40)+struct.pack('<I', o)+bytes(20) for o in range(5)]
        header = bytearray(16)
        struct.pack_into('<H', header, 10, 5)
        orig = C.DROP
        try:
            C.DROP = self.DROP
            out = C.drop_spawns(Root(bytes(header)+b''.join(records)), self.rows)
        finally:
            C.DROP = orig
        raw = out.payload
        self.assertEqual(struct.unpack_from('<H', raw, 10)[0], 4)
        self.assertEqual([struct.unpack_from('<I', raw, 16+64*k+40)[0] for k in range(4)], [0, 2, 3, 4])


class RailTest(unittest.TestCase):
    def test_rails_line_both_edges_on_the_deck(self):
        deck = C.Deck(Road(nodes()), nodes())
        source = bytes(96)
        rows = C.rail_rows(deck, source, 7, 3)
        per_side = len(rows)//2
        self.assertEqual(per_side, math.ceil((deck.s1-deck.s0)/C.RAIL_LENGTH))
        for side, block in ((-1, rows[:per_side]), (1, rows[per_side:])):
            reach = deck.s0
            for row in block:
                a, b = (C.physics((x, 0., 0.), row) for x in (0., C.RAIL_LENGTH))
                for p in (a, b):
                    s, l = C._sl(deck, p)
                    self.assertAlmostEqual(l, side*C.RAIL_LATERAL, places=3)
                    self.assertAlmostEqual(p[1], deck.height(s, l), places=3)
                s0, s1 = sorted(C._sl(deck, p)[0] for p in (a, b))
                self.assertAlmostEqual(s0, reach, places=3)
                reach = s1
                up = C.physics((0., 0., 1.), row)
                self.assertAlmostEqual(up[1]-a[1], 1., places=3)        # posts stand vertical
                self.assertEqual(struct.unpack_from('<hh', row, 84)[0], 7)
            self.assertAlmostEqual(reach, deck.s1, places=3)

    def test_rails_and_walls_open_the_native_roads(self):
        deck = C.Deck(Road(nodes()), nodes())
        deck.rail_ranges = {-1: (deck.s0+14., deck.s1-18.), 1: (deck.s0+11., deck.s1-23.)}
        rows = C.rail_rows(deck, bytes(96), 0, 0)
        for row in rows:
            ends = [C._sl(deck, C.physics((x, 0., 0.), row)) for x in (0., C.RAIL_LENGTH)]
            side = -1 if ends[0][1] < 0 else 1
            start, end = deck.rail_ranges[side]
            self.assertGreaterEqual(ends[0][0], start-.001)
            self.assertLessEqual(ends[1][0], end+.001)
        for s in C.pieces(deck)[0]:
            for a, b, _, _ in C.rail_walls(deck, s, C.pieces(deck)[1]):
                sa, la = C._sl(deck, a)
                sb, _ = C._sl(deck, b)
                start, end = deck.rail_ranges[-1 if la < 0 else 1]
                self.assertGreaterEqual(min(sa, sb), start-.001)
                self.assertLessEqual(max(sa, sb), end+.001)
        control = C.Deck(Road(nodes()), nodes())
        old = C.rail_rows(control, bytes(96), 0, 0)
        self.assertTrue(any(C._sl(deck, C.physics((0., 0., 0.), r))[0] < deck.s0+10 for r in old))


def fixture_pack(strips):
    row, article = C.surface_copy(bytes(16), strips, 0)
    body = C.link.carp([(C.grid.CI, 1, row), (0x636f0000, 0, b''), (0x63610000, 1, article)])
    return C.Pack(struct.pack('<4I', len(body), 1, 0, 0)+body)


class SurfaceTest(unittest.TestCase):
    def test_sampler_uses_the_query_cells_references(self):
        from ground import Face
        low = Face(((0.,0.,0.),(4.,0.,0.),(0.,0.,4.)),1,0,0,0,0)
        high = Face(((0.,.2,0.),(4.,.2,0.),(0.,.2,4.)),2,0,0,0,0)
        # Neighbour-cell faces overlap in projection. Their union invents a 20 cm lip.
        self.assertAlmostEqual(C.height_sampler([low,high])(1.,1.),.2)
        query = C.height_sampler([low,high],references=lambda x,z: [1 << 16])
        self.assertAlmostEqual(query(1.,1.),0.)

    def test_long_draw_triangles_are_refined_on_the_curve(self):
        points = [(0.,0.,-16.),(40.,0.,-16.),(0.,0.,16.),(40.,0.,16.)]
        vb = b''.join(struct.pack('<6f4B6f', *C.render(p), 0.,0.,1., 80,90,100,255,
                                   p[0]/40,p[2]/32,0.,0.,0.,0.) for p in points)
        header, record = bytearray(52), bytearray(144)
        struct.pack_into('<3I',header,16,1,4,1)
        struct.pack_into('<I',header,44,6)
        struct.pack_into('<I',record,48,0x10001)
        struct.pack_into('<I',record,64,4)
        struct.pack_into('<2I',record,96,2,0)
        struct.pack_into('<I',record,124,6)
        parts = [C.Chunk(k,bytes(data),8) for k,data in ((0x134900,header),(0x134b02,record),
                 (0x134b03,struct.pack('<6H',0,1,2,1,3,2)),(0x134b01,vb))]
        row = bytearray(96)
        struct.pack_into('<9f',row,44,1.,0.,0.,0.,1.,0.,0.,0.,1.)
        move = lambda p: (p[0],p[1]+.002*p[0]**2,p[2])
        refined = C.refine_mesh(parts,row,move)
        h = C.aligned_payload(C.one(refined,0x134900))
        ib = C.aligned_payload(C.one(refined,0x134b03))
        vb = C.aligned_payload(C.one(refined,0x134b01))
        ids = struct.unpack_from(f'<{C.u32(h,44)}H',ib)
        self.assertGreater(len(ids),6)
        for i in range(0,len(ids),3):
            p = [C.physics(struct.unpack_from('<3f',vb,k*52),row) for k in ids[i:i+3]]
            centre = tuple(sum(v[k] for v in p)/3 for k in range(3))
            error = abs(move(centre)[1]-sum(move(v)[1] for v in p)/3)
            self.assertLessEqual(error,.010001)
        self.assertGreater(abs(.002*20**2-(.002*0**2+.002*40**2)/2), .3)

    def test_sampled_collision_preserves_the_end_crown(self):
        class Crown(Road):
            def find_face_below(self, x, z, below):
                h = super().find_face_below(x, z, below).height
                dx, dz = x-self.origin[0], z-self.origin[2]
                l = dx*self.z[0]+dz*self.z[2]
                return Hit(h-.03*max(0., 1-abs(l)/2.))
        deck = C.Deck(Crown(nodes()), nodes())
        high, low = cuts(0.)
        donor = C.Donor(high, low)
        points = [p for pair in zip(low, high) for p in pair]
        source = fixture_pack([(points, [len(points), 2]+[1]*(len(points)-2))])
        # sampled_copy expects shipped donor instance 8; the fixture repeats its instance row.
        source.instances = source.instances*9
        row, article = C.sampled_copy(source, donor, deck, deck.s0, C.pieces(deck)[1], 0)
        body = C.link.carp([(C.grid.CI, 1, row), (0x636f0000, 0, b''), (0x63610000, 1, article)])
        written = C.Pack(struct.pack('<4I', len(body), 2, 0, 0)+body)
        height = C.height_sampler(list(written.faces(0)))
        p = deck.point(deck.s0+.05, 0.)
        self.assertLess(abs(height(p[0], p[2])-p[1]), .008)
        q = deck.point(deck.s0-.01, 0.)
        self.assertIsNotNone(height(q[0],q[2]))  # quantized outer rows overlap the native road
        # The original four-metre gap across -2/+2 bridges the centre depression.
        old = (deck.height(deck.s0, -2.)+deck.height(deck.s0, 2.))/2
        self.assertGreater(old-deck.height(deck.s0, 0.), .03)
        self.assertEqual({f.flags for f in written.faces(0)}, {1})

    def test_native_approach_face_is_retained_only_outside_deck(self):
        deck = C.Deck(Road(nodes()), nodes())
        # Flat native face isolates clipping from the 1/128 m rounding of new edge vertices.
        a, b, c, d = [(p[0], 10., p[2]) for p in
                      (deck.point(deck.s0+s, l) for s, l in ((-2,-20), (4,-20), (-2,20), (4,20)))]
        source = fixture_pack([([a,b,c,d], [4,2,1,1])])
        body = C.link.carp([(C.grid.CI, 1, source.instances), (0x636f0000, 0, b''),
                            (0x63610000, 1, source.articles[0])])
        raw = struct.pack('<4I', len(body), 1, 0, 0)+body
        clipped = C.Pack(C.clear_road_collision(raw, deck))
        new = C.height_sampler(list(clipped.faces(0)))
        old = C.height_sampler(list(source.faces(0)))
        p = deck.point(deck.s0+2, 0.)
        self.assertIsNotNone(old(p[0],p[2]))
        self.assertIsNone(new(p[0],p[2]))
        p = deck.point(deck.s0-1, 0.)
        self.assertAlmostEqual(old(p[0],p[2]), new(p[0],p[2]), places=3)
        self.assertEqual({f.flags for f in clipped.faces(0)}, {1})

    def test_reflection_sky_is_excluded_from_both_scenery_gates(self):
        import c1_world as w
        header = bytes(12)+struct.pack('<I',2600)
        model = b'SKY_SPECULAR'.ljust(72,b'\0')
        row = bytearray(96)
        struct.pack_into('<I',row,12,0x480)
        scene = w.Scene(header, model, bytes(row)*2, b'', b'')
        hidden = C.hide_scenery(scene)
        before, after = C.u32(scene.instances,108), C.u32(hidden.instances,108)
        self.assertEqual(before & 0xc0000, 0)
        self.assertEqual(after & 0xc0100, 0xc0000)
        self.assertEqual(scene.models, hidden.models)
        self.assertEqual(scene.instances[128:], hidden.instances[128:])


class WallPack:
    """The deck copies' collision as wall_cover reads it: one barrier-free article per copy, walls optional."""

    def __init__(self, deck, walls):
        starts, step = C.pieces(deck)
        rows, self.articles = [], {}
        for i, s in enumerate(starts):
            centre = deck.point(s+step/2, 0.)
            inst = bytearray(64)
            struct.pack_into('<3f', inst, 48, *(-v for v in centre))
            struct.pack_into('<H', inst, 26, i)
            article = struct.pack('<8H', 0, 0, 0, 0, 512, 8, 0, 0)+bytes(48)
            if walls:
                inst, article = C.with_walls(bytes(inst), article, C.rail_walls(deck, s, step))
            rows.append(bytes(inst))
            self.articles[i] = article
        self.instances = b''.join(rows)


class WallTest(unittest.TestCase):
    """Rail collision: both deck edges walled over their whole length (2 x 180 walls on the pick, 100 %);
    the copies without walls (pair_c, the drive where the car left the deck at s 148-162) cover 0 %."""

    def test_walls_cover_both_edges(self):
        deck = C.Deck(Road(nodes()), nodes())
        cover = C.wall_cover(WallPack(deck, True), deck)
        for side in ('left', 'right'):
            self.assertGreater(cover[side]['covered'], .999, cover)
        self.assertEqual(C.wall_cover(WallPack(deck, False), deck), {})

    def test_wall_records_and_extents(self):
        deck = C.Deck(Road(nodes()), nodes())
        pack = WallPack(deck, True)
        article = pack.articles[0]
        _, at, count, size = struct.unpack_from('<4H', article)
        self.assertEqual((count, size, len(article)), (len(C.rail_walls(deck, *C.pieces(deck)[0][:1], C.pieces(deck)[1])),
                                                       32*count, 16+32*count+48))
        a = struct.unpack_from('<3fI3ff', article, 16+at)
        self.assertEqual(a[3], C.WALL_FLAGS)
        self.assertAlmostEqual(a[7], 1/math.hypot(a[4]-a[0], a[6]-a[2]), places=6)
        self.assertGreaterEqual(struct.unpack_from('<f', pack.instances, 20)[0], C.WALL_ABOVE)


class VolumeTest(unittest.TestCase):
    def test_low_runoff_overlap_is_visible(self):
        deck = C.Deck(Road(nodes()), nodes())
        def patch(h):
            return [deck.point(s,l,h) for s,l in ((300.,0.),(301.,0.),(300.,1.))]
        self.assertTrue(C._in_volume(deck,patch(.06)))
        self.assertFalse(C._in_volume(deck,patch(-.01)))
        self.assertFalse(.3 < .06 < 4.)  # the original volume check misses the visible overlap

    def test_rail_on_deck_counts_and_under_deck_does_not(self):
        deck = C.Deck(Road(nodes()), nodes())
        def rail(dz):
            a, b = deck.point(300., 2.), deck.point(304., 2.)
            return [(a[0], a[1]+dz, a[2]), (b[0], b[1]+dz, b[2]), (a[0], a[1]+dz+1.4, a[2])]
        self.assertTrue(C._in_volume(deck, rail(0.)))
        self.assertFalse(C._in_volume(deck, rail(-1.9)))


class FarViewTest(unittest.TestCase):
    def setUp(self):
        self.rows = {n: {998, 1940, 1094, 1096, 1916, 1980, 1982, 1983, 1984, 1985, 1986, 1987, 1988} for n in (924, 925, 913, 2014, 1833, 1835, 1838)}
        for n in (924, 925, 913):
            self.rows[n].update({1597, 1897, 1898, 1900})
        self.rows[2014].update({1897, 1898, 1900, 1908, 1989})
        self.rows[1833].update({1095, 1897, 1898, 1900, 1908, 1989})
        for n in (1835, 1838):
            self.rows[n].update({1095, 1989})
        self.rows.update({1337: {1989}, 1636: {1989}})
        self.required = set.union(*self.rows.values())
        self.keys = {0xc3c0a500+i for i in range(19)} | {0x5b2dad40}
        self.scenes = {n: (n, set()) for n in self.required | {965}}
        self.scenes[1900] = (1900, self.keys.copy())
        self.solids = {k: {1900: {123}} for k in self.keys}
        self.textures = {123: {2400}}
        self.sizes = {n: 128 for n in self.required | {2400, 2500, 2600, 965}}

    def check_rows(self):
        import c1_world as w
        ix = SimpleNamespace(sections=[SimpleNamespace(number=n, size=s) for n, s in self.sizes.items()])
        rows = SimpleNamespace(rows=[SimpleNamespace(number=n, entries=e) for n, e in self.rows.items()])
        with patch.object(C, 'resource_inventory', return_value=(self.textures, self.solids, self.scenes)), \
             patch.object(w.vis, 'payload_of', return_value=b''), patch.object(w.vis, 'read', return_value=rows):
            return C.check_far_rows(ix, None)

    def test_all_rows_have_far_scenes_deck_and_closed_providers(self):
        self.assertEqual(len(self.check_rows()), 9)

    def test_link_rows_select_downtown(self):
        """Downtown scenes per link row: 0/2 before, 2/2 after."""
        for number in (913, 924, 925, 2014, 1833):
            with self.subTest(row=number):
                self.assertEqual(C.far_scenes(number) & {1897, 1898}, {1897, 1898})

    def test_native_precull_bit_control(self):
        row = bytearray(96)
        masks = bytearray(128)
        masks[0] = 1
        sc = SimpleNamespace(instances=bytes(row), precull=bytes(masks))
        self.assertEqual(C.precull_hidden(sc, [(0., 0.), (32., 0.)]), 1)
        sc.precull = bytes(128)
        self.assertEqual(C.precull_hidden(sc, [(0., 0.), (32., 0.)]), 0)

    def test_scene_split_preserves_transforms_lods_and_rebases_native_bindings(self):
        import c1_world as w
        from formats import Chunk
        header = bytearray(68)
        struct.pack_into('<I', header, 12, 965)
        models = bytearray(3*72)
        for m in range(3):
            struct.pack_into('<4I', models, m*72+24, *(100+m*10+k for k in range(4)))
        rows = []
        for i, model in enumerate((0, 2, 1)):
            row = bytearray(96)
            struct.pack_into('<3f', row, 32, i*40., 8.+i, 12.)
            struct.pack_into('<h', row, 84, model)
            rows.append(bytes(row))
        extras = (Chunk(0x3410d, b''.join(bytes([i])*32 for i in range(3))),
                  Chunk(0x34106, struct.pack('<6H', 50, 0, 51, 1, 52, 2)))
        original = w.Scene(bytes(header), bytes(models), b''.join(rows), b'', bytes(128), extras)
        moved = C.scene_subset(original, {1, 2}, 1900)
        self.assertEqual(moved.number, 1900)
        for new, old in enumerate((1, 2)):
            row = moved.instances[new*96:(new+1)*96]
            self.assertEqual(row[:84]+row[86:], rows[old][:84]+rows[old][86:])
            before = struct.unpack_from('<h', rows[old], 84)[0]
            after = struct.unpack_from('<h', row, 84)[0]
            self.assertEqual(moved.models[after*72:(after+1)*72], original.models[before*72:(before+1)*72])
        self.assertEqual(moved.extras[0].payload, bytes([1])*32+bytes([2])*32)
        self.assertEqual(list(struct.iter_unpack('<2H', moved.extras[1].payload)), [(51, 0), (52, 1)])
        # Naively retaining old model indices after compacting leaves one reference outside the table.
        self.assertEqual(sum(struct.unpack_from('<h', rows[i], 84)[0] >= 2 for i in (1, 2)), 1)

    def test_current_row_memberships_fail(self):
        # Projection of the saved rows onto the required set, not writer constants.
        before = {n: {998} if n in (924, 925, 913) else {1597} for n in self.rows}
        self.assertGreater(sum(len(self.rows[n]-e) for n, e in before.items()), 0)
        for n in self.rows:
            old = self.rows[n]
            self.rows[n] = before[n]
            with self.assertRaisesRegex(ValueError, 'missing scenes'):
                self.check_rows()
            self.rows[n] = old

    def test_beach_host_control_rejected(self):
        self.rows[1833].add(965)
        with self.assertRaisesRegex(ValueError, 'beach host'):
            self.check_rows()

    def test_all_deck_copies_and_rails_required(self):
        for key in (0xc3c0a512, 0x5b2dad40):
            self.scenes[1900][1].remove(key)
            with self.assertRaisesRegex(ValueError, 'deck copies/rails'):
                self.check_rows()
            self.scenes[1900][1].add(key)

    def test_provider_archive_must_be_loaded(self):
        self.solids[0xc3c0a500] = {1999: {123}}
        with self.assertRaisesRegex(ValueError, 'missing model'):
            self.check_rows()

    def test_unindexed_texture_is_an_error(self):
        self.textures.clear()
        with self.assertRaisesRegex(ValueError, 'missing texture'):
            self.check_rows()

    def test_world_allowance_not_combined_pool(self):
        self.sizes[1900] = 71680001-sum(self.sizes[n] for n in self.rows[1833] | {2400, 2600} if n != 1900)
        with self.assertRaisesRegex(ValueError, 'exceeds 71680000'):
            self.check_rows()
        self.sizes[1900] -= 1
        self.assertEqual(max(r['bytes'] for r in self.check_rows().values()), 71680000)

    def test_dependency_scan_checks_secondary_lod_and_unknown_texture(self):
        # Primary model has no texture need. The second LOD's texture is unindexed.
        inventory = ({}, {1: {1900: set()}, 2: {1900: {123}}}, {1900: (1900, {1, 2})})
        with self.assertRaisesRegex(ValueError, 'unresolved texture 0000007B'):
            C.dependency_closure({1900}, {1900}, inventory, {1900: 128})
        inventory[1].pop(2)
        with self.assertRaisesRegex(ValueError, 'unresolved model 00000002'):
            C.dependency_closure({1900}, {1900}, inventory, {1900: 128})

    def test_inventory_reads_four_slots_and_reconciles_texture_records(self):
        import c1_world as w
        import merge
        from formats import Chunk
        header = bytearray(68)
        struct.pack_into('<I', header, 12, 1900)
        models = bytearray(72)
        struct.pack_into('<4I', models, 24, 11, 22, 33, 44)
        scene = w.Scene(bytes(header), bytes(models), b'', b'', b'', ())
        raw = C.link.scene_chunk(scene, 0).encode()
        ix = SimpleNamespace(sections=[SimpleNamespace(number=1900)])
        with patch.object(merge, 'read_section', return_value=raw):
            self.assertEqual(C.resource_inventory(ix, None)[2][1900][1], {11, 22, 33, 44})
        record = bytearray(92)
        struct.pack_into('<I', record, 12, 123)
        record[88] = 3
        pack = Chunk(0xb3300000, Chunk(0xb3310000, b''.join(c.encode() for c in (
            Chunk(0x33310002, struct.pack('<2I', 123, 0)), Chunk(0x33310004, bytes(record))))).encode())
        with patch.object(merge, 'read_section', return_value=pack.encode()):
            self.assertEqual(C.resource_inventory(ix, None)[0], {123: {1900}})
        record[12] = 124
        broken = Chunk(0xb3300000, Chunk(0xb3310000, b''.join(c.encode() for c in (
            Chunk(0x33310002, struct.pack('<2I', 123, 0)), Chunk(0x33310004, bytes(record))))).encode())
        with patch.object(merge, 'read_section', return_value=broken.encode()):
            with self.assertRaisesRegex(ValueError, 'directory/record identity'):
                C.resource_inventory(ix, None)

    def test_replaced_rows_remove_host_without_corrupting_capacity(self):
        from formats import Chunk
        import visibility as vis
        # Exercise real row serialization with spare capacity and an actual removal.
        h = bytearray(18)
        struct.pack_into('<h', h, 12, 1833)
        h[15] = 5
        struct.pack_into('<h', h, 16, 3)
        row = vis.Row(bytes(h), (965, 1597, 1833), bytes(6))
        table = SimpleNamespace(rows=(row,), selectors=(),
                                parts=(Chunk(vis.ROWS, row.encode()),))
        with patch.object(vis, 'read', return_value=table):
            written = C.rows_replaced(b'', {1833: {1597, 1833, 1900}})
        decoded = vis.read_rows(C.chunks(written)[0].payload)[0]
        self.assertEqual(decoded.entries, (1597, 1833, 1900))
        self.assertEqual(decoded.cap, 5)


# Frozen original clipping planes, independent of history and the current writer.
BROKEN_CUT = '''planes = (lambda v: point(v)[0]-deck.s0+.002, lambda v: deck.s1+.002-point(v)[0],
                  lambda v: point(v)[1]+16.002, lambda v: 16.002-point(v)[1])
        '''


# Frozen drive-six selection, independent of history.
ORIGINAL_FAR = 'def original_far_scenes(number):\n    selected = {998, 999, 1094, 1096, 1916}\n    if number in (924, 925, 913):\n        selected.add(1597)\n    else:\n        if number in (2014, 1833):\n            selected.add(1908)\n        if number != 2014:\n            selected.add(1095)\n    if number in (924, 925, 913, 2014, 1833):\n        selected.add(1900)\n    return selected\n'
ORIGINAL_FAR_SHA = 'ce8e94bbb1ce38675aa45e6cda67f204b648b1b3e8a11cce04015ffd4e106d9a'

def projected_area(poly):
    return abs(sum(a[0]*b[1]-a[1]*b[0] for a, b in zip(poly, (*poly[1:], poly[0]))))/2 if poly else 0.


def triangle_overlap(a, b):
    """Projected polygon intersection, independent of material selection and the row writer."""
    orient = (b[1][0]-b[0][0])*(b[2][1]-b[0][1])-(b[1][1]-b[0][1])*(b[2][0]-b[0][0])
    poly = list(a)
    for p, q in zip(b, (*b[1:], b[0])):
        poly = C.link.clip_values(poly, lambda v: orient*((q[0]-p[0])*(v[1]-p[1])-(q[1]-p[1])*(v[0]-p[0])))
        if len(poly) < 3:
            return 0.
    return projected_area(poly)


def ordinary_key(segment, node):
    return 4 + 2 * segment[3] + int(node == segment[1])


def duplicate_junction_keys(nodes, segments):
    arrivals = Counter(ordinary_key(segments[sid], node)
                       for node, row in enumerate(nodes) if row[5] > 2
                       for sid in row[7:7+row[5]] if segments[sid][3] >= 0)
    return {key for key, count in arrivals.items() if count > 1}


def coast_parent_walk(nodes, segments):
    """Replay the ordinary expansion and parent slots of 0080B9A0 for this request."""
    source, goal = 1031, 12330
    start_node, goal_node = 1013, 8990
    end = 0xffff
    heuristic = [math.floor(math.dist(row[:3], nodes[goal_node][:3])+.5) for row in nodes]
    lengths = [row[2]*1000/65535 for row in segments]
    frontier = {1: (heuristic[start_node], 0)}
    records = {1: (source, start_node, heuristic[start_node], end)}
    closed = set()
    order = 0
    for _ in range(3):
        key = min(frontier, key=frontier.get)
        del frontier[key]  # 007F6400 clears open before expansion sets closed.
        incoming, node, score, _ = records[key]
        if (incoming, node) == (goal, goal_node):
            trail = []
            while key != end and key not in trail:
                trail.append(key)
                key = records[key][3]
            return (*trail, key)
        for sid in nodes[node][7:7+nodes[node][5]]:
            if sid == incoming:
                continue
            departure, distance = node, 0.
            while True:
                a, b, _, road, _, flags, *_ = segments[sid]
                assert not flags & 1, 'unexpected connector in the three-pop route'
                arrival = b if departure == a else a
                if flags & 0x3000 or (flags & 0x40 and departure != a) or nodes[arrival][5] < 2:
                    break
                if sid == goal or nodes[arrival][5] > 2:
                    if road < 0:
                        break
                    slot = 2 + int(arrival == b) if sid == goal else ordinary_key(segments[sid], arrival)
                    cost = math.floor(score-heuristic[node]+distance+lengths[sid]+.5) & 0xffff
                    if slot in frontier or slot in closed:
                        _, old_node, old_score, _ = records[slot]
                        if old_score-heuristic[old_node] <= cost:
                            break
                        closed.discard(slot)
                    estimate = (cost+heuristic[arrival]) & 0xffff
                    order -= 1
                    frontier[slot] = estimate, order
                    records[slot] = sid, arrival, estimate, key
                    break
                distance += lengths[sid]
                departure = arrival
                sid = next(s for s in nodes[arrival][7:9] if s != sid)
        closed.add(key)
    raise AssertionError('coast goal did not pop within three frontier records')


def coast_route_graph(index):
    import c1_world as w
    return C.roads._reader(C.collision_body(C.one(index.parts, w.MAP)))


class DriveThreeArchives(unittest.TestCase):
    """Actual native archives supply every triangle/provider; absent private assets skip this class."""

    @classmethod
    def setUpClass(cls):
        import c1_world as w
        from merge import DEFAULT_MW, DEFAULT_CARBON, load_index, read_section
        if not all((p/n).exists() for p, n in ((DEFAULT_MW, 'L2RA.BUN'), (DEFAULT_CARBON, 'L5RA.BUN'))):
            raise unittest.SkipTest('private coast archives absent')
        cls.tmp = tempfile.TemporaryDirectory(prefix='coast-drive-three-')
        cls.addClassCleanup(cls.tmp.cleanup)
        base = Path(cls.tmp.name)/'base'
        base.mkdir()
        w._write_pair(DEFAULT_MW, DEFAULT_CARBON, base, shift=(5056., -1728.), _link=False)
        cls.index, cls.stream, _ = load_index(base/'TRACKS', 'L5RA')
        cls.parts = C.build_parts(cls.index, cls.stream)
        cls.deck = cls.parts['deck']
        cls.scenes, cls.solids = {}, {}
        for section in cls.index.sections:
            roots = C.chunks(read_section(cls.stream, section))
            for root in roots:
                if root.kind == w.SCENE:
                    scene = w.scene_data(root)
                    cls.scenes[scene.number] = (section.number, scene)
            for solid in C.link.solids(roots):
                cls.solids.setdefault(C.link.solid_key(solid), solid)
        cls.inventory = C.resource_inventory(cls.index, cls.stream)
        cls.rows = {r.number: set(r.entries) for r in w.vis.read(w.vis.payload_of(cls.index)).rows}
        after = Path(cls.tmp.name)/'after'
        shutil.copytree(base, after)
        C.apply(after/'TRACKS')
        cls.after, cls.after_stream, _ = load_index(after/'TRACKS', 'L5RA')
        # Exercise the original decoded causes together, producing serialized controls.
        assert hashlib.sha256(ORIGINAL_FAR.encode()).hexdigest() == ORIGINAL_FAR_SHA
        env = dict(C.__dict__)
        exec(ORIGINAL_FAR, env)
        fit = inspect.getsource(C.fit_mouths)
        a, b = fit.index('            residual = '), fit.index('    deck.a, deck.b = profiles')
        field = '            deck.gb_local = [g-fit for g, fit in zip(grades, tangents[-1])]\n'
        assert hashlib.sha256(field.encode()).hexdigest() == '21258a9412c425904d34ce054d9d53025746212b3d2298354e25d55ee6e8d541'
        exec(fit[:a]+field+fit[b:], env)
        clip = inspect.getsource(C.clip_floor_solid)
        exec(clip.replace('lambda v: point(v)[1]+15.98,', 'lambda v: point(v)[1]+15.998,'), env)
        before = Path(cls.tmp.name)/'before'
        shutil.copytree(base, before)
        with patch.object(C, 'far_scenes', env['original_far_scenes']), \
             patch.object(C, 'PALMONT_HORIZON_ROWS', ()), \
             patch.object(C, 'borrowed_scenery', return_value={}), \
             patch.object(C, 'fit_mouths', env['fit_mouths']), \
             patch.object(C, 'clip_floor_solid', env['clip_floor_solid']), \
             patch.object(C, 'deck_sides', side_effect=lambda records, buffers, indices, centre, deck: (buffers, indices)):
            C.apply(before/'TRACKS')
        cls.before, cls.before_stream, _ = load_index(before/'TRACKS', 'L5RA')
        cls.after_scenes, cls.draws = {}, []
        for section in cls.after.sections:
            if section.number not in (1900, 1908, 1916, 1940, 1989, 1980, 1982, 1983, 1984, 1985, 1986, 1987, 1988):
                continue
            roots = C.chunks(read_section(cls.after_stream, section))
            for root in roots:
                if root.kind == w.SCENE:
                    sc = w.scene_data(root)
                    cls.after_scenes[sc.number] = sc
            if section.number == 1900:
                solids = {C.link.solid_key(s): s for s in C.link.solids(roots)}
                sc = cls.after_scenes[1900]
                for i in range(len(sc.instances)//96):
                    row = sc.instances[i*96:(i+1)*96]
                    key = C.u32(sc.models, struct.unpack_from('<h', row, 84)[0]*72+24)
                    if key in solids:
                        cls.draws.extend(tuple(C.physics(v, row) for v in tri) for tri in C.link.mesh(solids[key]))

    def floor_triangles(self, deck, clip):
        targets, _ = C.floor_sources(self.index, self.stream)
        return [tuple(C.physics(v, row) for v in tri) for key, row in targets.items()
                for tri in C.link.mesh(clip(self.solids[key], row, deck, 0))]

    def palmont_draw_surfaces(self):
        import c1_world as w
        from ground import Face
        from merge import read_section

        roots = [root for section in self.after.sections if section.number in (924, 925, 964, 965)
                 for root in C.chunks(read_section(self.after_stream, section))]
        solids = {C.link.solid_key(s): s for s in C.link.solids(roots)}
        native, runoff = [], []
        floor_names = ('RD_MU_Road_16_CHOP', 'TD_MU_Runoff_20_CHOP', 'TN_VeniceTerrain_09_CHO')
        for scene in (w.scene_data(root) for root in roots if root.kind == w.SCENE):
            if scene.number not in (924, 925, 964):
                continue
            for i in range(len(scene.instances)//96):
                name = C.model_name(scene, i)
                if not name.startswith(floor_names):
                    continue
                row = scene.instances[i*96:(i+1)*96]
                key = C.u32(scene.models, struct.unpack_from('<h', row, 84)[0]*72+24)
                if key not in solids:
                    continue
                faces = [Face(tuple(C.physics(v, row) for v in tri), 0, 0, 0, 0, 0)
                         for tri in C.link.mesh(solids[key])]
                native.extend(faces)
                if scene.number == 924 and name.startswith('TD_MU_Runoff_20_CHOP_I2'):
                    runoff.extend(faces)
        return (C.height_sampler(Face(t, 0, 0, 0, 0, 0) for t in self.draws),
                C.height_sampler(native), C.height_sampler(runoff))

    def test_reported_palmont_render_seam(self):
        """Written deck/grass overlap at the reported heading: 124.1 to 2.2 mm (limit 10)."""
        drawn, _, grass = self.palmont_draw_surfaces()
        x, z = 1670.032837-.896494*13.17, 3154.552490-.422729*13.17
        step = abs(drawn(x, z, 12.)-grass(x, z, 12.))
        print(f'COAST reported render seam {step:.6f} m', flush=True)
        self.assertLessEqual(step, .01)

    def test_reported_palmont_collision_step(self):
        """Written collision crossing in 25 mm of travel: 113.9 to 2.8 mm (limit 10)."""
        from ground import World

        world = World(self.after, self.after_stream)
        dx, dz = .700481, .697753
        length = math.hypot(dx, dz)
        hits = [world.find_face_below(1658.280518-dx*d/length, 3150.057617-dz*d/length, below=13.)
                for d in (.400, .425, .450, .475, .500)]
        self.assertEqual([hits[0].face.pack, hits[-1].face.pack], [360, 924])
        step = max(abs(a.height-b.height) for a, b in zip(hits, hits[1:]))
        print(f'COAST reported collision step {step:.6f} m', flush=True)
        self.assertLessEqual(step, .01)

    def test_palmont_mouth_and_shoulders(self):
        """Written side sweeps: render lip 240.6 to 2.9 mm, collision step 126.8 to 5.5 mm."""
        from ground import World

        world = World(self.after, self.after_stream)
        deck, native, _ = self.palmont_draw_surfaces()

        def surface(x, z, ceiling):
            hits = (deck(x, z, ceiling), native(x, z, ceiling))
            return max((h for h in hits if h is not None), default=None)

        def at(query, s, l):
            x, h, z = self.deck.point(s, l)
            y = query(x, z, h+.45)
            self.assertIsNotNone(y, (s, l))
            self.assertLess(abs(y-h), .45, (s, l))
            return y

        def mouth(query):
            laterals = [i/2 for i in range(-34, 35)]
            return [abs(at(query, self.deck.cut(0, l)-.0125, l) -
                        at(query, self.deck.cut(0, l)+.0125, l)) for l in laterals]

        def side(inner, outer, edge, last, pad):
            start = self.deck.cut(0, edge)+.05
            direction = math.copysign(1., edge)
            stations = [start+i*.25 for i in range(math.ceil((last-start)/.25))]
            return [abs(at(inner, s, edge-pad*direction)-at(outer, s, edge+pad*direction))
                    for s in stations]

        rendered = mouth(surface)
        rendered += side(deck, native, -15.985, 16.9, .008)
        rendered += side(deck, native, 16.005, 29., .008)
        collision = mouth(world.height)
        for edge in (-15.97, 15.97):
            collision += side(world.height, world.height, edge, 16.9, .0125)
        print(f'COAST Palmont mouth/shoulders render {max(rendered):.6f} m ({len(rendered)} probes), '
              f'collision {max(collision):.6f} m ({len(collision)} probes)', flush=True)
        self.assertLessEqual(max(rendered), .01)
        self.assertLessEqual(max(collision), .01)

    def test_reported_far_rows_carry_opposite_shore(self):
        """Scene 1989 in 0/2 -> 2/2 rows, with zero added known-provider misses."""
        import c1_world as w

        sizes = {s.number: s.size for s in self.after.sections}
        rows = {r.number: set(r.entries) for r in w.vis.read(w.vis.payload_of(self.after)).rows}
        selected = sum(1989 in rows[n] for n in (1636, 1337))
        print(f'COAST reported far rows {selected}/2', flush=True)
        self.assertEqual(selected, 2)
        inventory = C.resource_inventory(self.after, self.after_stream)
        for number in (1636, 1337):
            self.assertEqual(rows[number], self.rows[number]|{1989, 2233, 2292, 2509, 2528})
            self.assertLessEqual(C.known_provider_misses(rows[number], inventory),
                                 C.known_provider_misses(self.rows[number], inventory))
            self.assertLessEqual(sum(sizes.get(n, 0) for n in rows[number]|{2400, 2600} if n != 2500),
                                 71680000)

    @staticmethod
    def surface_misses(triangles, deck, end=0):
        import numpy as np
        t = np.asarray(triangles)
        a, b, c = t[:, 0], t[:, 1], t[:, 2]
        ux, uz, vx, vz = b[:, 0]-a[:, 0], b[:, 2]-a[:, 2], c[:, 0]-a[:, 0], c[:, 2]-a[:, 2]
        det = ux*vz-uz*vx
        den = np.where(abs(det) > 1e-12, det, 1)
        misses = 0
        for l in range(-15, 16):
            for k in range(-50, 51):
                p = deck.point(deck.cut(end, l)+k*.0001, l)
                dx, dz = p[0]-a[:, 0], p[2]-a[:, 2]
                u, v = (dx*vz-dz*vx)/den, (ux*dz-uz*dx)/den
                h = a[:, 1]+u*(b[:, 1]-a[:, 1])+v*(c[:, 1]-a[:, 1])
                misses += not ((abs(det)>1e-12)&(u>=-1e-9)&(v>=-1e-9)&(u+v<=1+1e-9)&(abs(h-p[1])<.15)).any()
        return int(misses)

    @staticmethod
    def point_misses(triangles, points):
        import numpy as np
        t = np.asarray(triangles)
        a, b, c = t[:, 0], t[:, 1], t[:, 2]
        ux, uz, vx, vz = b[:, 0]-a[:, 0], b[:, 2]-a[:, 2], c[:, 0]-a[:, 0], c[:, 2]-a[:, 2]
        det = ux*vz-uz*vx
        den = np.where(abs(det) > 1e-12, det, 1)
        misses = 0
        for p in points:
            dx, dz = p[0]-a[:, 0], p[2]-a[:, 2]
            u, v = (dx*vz-dz*vx)/den, (ux*dz-uz*dx)/den
            h = a[:, 1]+u*(b[:, 1]-a[:, 1])+v*(c[:, 1]-a[:, 1])
            misses += not ((abs(det)>1e-12)&(u>=-1e-9)&(v>=-1e-9)&(u+v<=1+1e-9)&(abs(h-p[1])<.15)).any()
        return int(misses)

    def test_route_parent_walk_and_junction_keys(self):
        counts, arrays, nodes, segments, _ = coast_route_graph(self.after)
        original, original_arrays, _, original_segments, _ = coast_route_graph(self.index)
        # Restore the original segment road field, including the deck's native donor.
        deck_donor = next(s[3] for s in original_segments if C.PALMONT in s[:2])
        pinned = [(*s[:3], original_segments[i][3] if i < len(original_segments) else deck_donor, *s[4:])
                  for i, s in enumerate(segments)]
        self.assertEqual(coast_parent_walk(nodes, pinned), (3, 501, 501))
        self.assertEqual(len(duplicate_junction_keys(nodes, pinned)), 4)
        with self.subTest(check='parent walk'):
            self.assertEqual(coast_parent_walk(nodes, segments), (3, 4303, 1, 0xffff))
        with self.subTest(check='junction arrivals'):
            self.assertEqual(duplicate_junction_keys(nodes, segments), set())
        self.assertEqual(counts['roads'], original['roads']+3)
        for road, members in ((2148, range(12328, 12349)), (2149, (1031, 1032)),
                              (2150, (9759, 9760, 9761, 9762, 10211))):
            self.assertEqual([s[4] for s in segments if s[3] == road], list(members))
        for road, donor in ((248, 248), (1414, 1414), (2148, 248), (2149, 248), (2150, 1414)):
            row = struct.unpack_from('<IHH', arrays[C.roads.ROADS], road*8)
            definition, _, speech = struct.unpack_from('<IHH', original_arrays[C.roads.ROADS], donor*8)
            length = round(sum(s[2] for s in segments if s[3] == road)/4)
            self.assertEqual(row, (definition, length, speech))

    def test_left_lateral_zero_control_1128(self):
        """Left 1,128/3,131 -> 0/3,131; right and both mouths stay 0/3,131."""
        source = inspect.getsource(C.clip_floor_solid)
        # Pin only the decoded lateral plane, independent of git history.
        frozen = 'lambda v: point(v)[1]+15.998'
        self.assertEqual(hashlib.sha256(frozen.encode()).hexdigest(), 'b4a34901201ec38de4204e42caae57e19dd1cc68207356214ed9c89e71368dc6')
        env = dict(C.__dict__)
        exec(source.replace('lambda v: point(v)[1]+15.98,', frozen+','), env)
        fixed = self.draws+self.floor_triangles(self.deck, C.clip_floor_solid)
        broken = self.draws+self.floor_triangles(self.deck, env['clip_floor_solid'])
        counts = []
        for side in (-1, 1):
            points = [self.deck.point(10+i*.2, side*(15.998+k*.0001))
                      for i in range(31) for k in range(-50, 51)]
            counts.append((self.point_misses(fixed, points), self.point_misses(broken, points)))
        self.assertEqual(counts, [(0, 1128), (0, 0)])
        self.assertEqual([self.surface_misses(fixed, self.deck, e) for e in (0, 1)], [0, 0])
        print(f'COAST lateral misses fixed/control {counts}; mouths 0/3131 each', flush=True)

    def test_surface_misses_zero_control_612(self):
        # Freeze the original operation, not a whole production file.
        self.assertEqual(hashlib.sha256(BROKEN_CUT.encode()).hexdigest(), '41298f3cff22e7bffc31e27b65dc3f0fce55c056100cce8cf38dab28efd59f04')
        source = inspect.getsource(C.clip_floor_solid)
        a, b = source.index('planes = ('), source.index('for fn in planes:')
        env = dict(C.__dict__)
        exec(source[:a]+BROKEN_CUT+source[b:], env)
        old = C.Deck(self.parts['world'], self.parts['world'].nodes)
        donor = self.parts['donor']
        start, step = C.pieces(old)[0][0], C.pieces(old)[1]
        _, row, solid, _, _ = self.parts['source']
        centre = tuple(round(v*16)/16 for v in C.render(old.point(start+step/2, 0.)))
        mesh, box = C.copy_solid(solid, row, C.mapper(old, donor, start, step), lambda q: (0., 1., 0.), C.KEY_BASE, centre, 0)
        instance = C.instance_row(row, centre, box, 0, 0)
        draw = [tuple(C.physics(v, instance) for v in tri) for tri in C.link.mesh(mesh)]
        control = self.surface_misses(draw+self.floor_triangles(old, env['clip_floor_solid']), old)
        fixed = self.surface_misses(draw+self.floor_triangles(old, C.clip_floor_solid), old)
        self.assertEqual((fixed, control), (0, 612))
        actual = self.draws+self.floor_triangles(self.deck, C.clip_floor_solid)
        self.assertEqual([self.surface_misses(actual, self.deck, e) for e in (0, 1)], [0, 0])
        print(f'COAST surface misses {fixed}/3131; original control {control}/3131; shaped mouths both 0', flush=True)

    @staticmethod
    def decoded_scenes(index, stream):
        import c1_world as w
        from merge import read_section
        scenes, solids = {}, {}
        for section in index.sections:
            roots = C.chunks(read_section(stream, section))
            for root in roots:
                if root.kind == w.SCENE:
                    scene = w.scene_data(root)
                    scenes[scene.number] = (section.number, scene)
            for solid in C.link.solids(roots):
                solids.setdefault(C.link.solid_key(solid), solid)
        return scenes, solids

    def test_internal_joins_do_not_worsen(self):
        """18 internal seams retain the 145/56,358 microscopic sample misses."""
        import numpy as np
        scenes, solids = self.decoded_scenes(self.before, self.before_stream)
        native = scenes[1900][1]
        before = []
        for i in range(len(native.instances)//96):
            row = native.instances[i*96:(i+1)*96]
            key = C.u32(native.models, struct.unpack_from('<h', row, 84)[0]*72+24)
            if C.KEY_BASE <= key < C.KEY_BASE+64:
                before.extend(tuple(C.physics(v, row) for v in tri) for tri in C.link.mesh(solids[key]))
        totals = []
        for draws in (before, self.draws):
            t = np.asarray(draws)
            stations = ((t[:, :, 0]-self.deck.origin[0])*self.deck.x[0]+
                        (t[:, :, 2]-self.deck.origin[2])*self.deck.x[2])
            counts = []
            for seam in self.parts['starts'][1:]:
                near = t[(stations.min(1)<=seam+.006)&(stations.max(1)>=seam-.006)]
                points = [self.deck.point(seam+k*.0001, l) for l in range(-15, 16) for k in range(-50, 51)]
                counts.append(self.point_misses(near, points))
            totals.append(counts)
        self.assertEqual(totals[0], [9,18,6,5,4,8,8,13,13,10,7,5,9,7,3,8,3,9])
        self.assertTrue(all(a<=b for a, b in zip(totals[1], totals[0])), totals)
        print(f'COAST internal seam misses {totals[0]} -> {totals[1]}', flush=True)

    def test_borrowed_scene_identities_unused_control_two(self):
        """Native scene-ID collisions in archive-only free IDs: 2 -> 0."""
        self.assertEqual(len({1917, 1918} & self.scenes.keys()), 2)
        borrowed = self.after_scenes.keys()-{1900, 1908, 1916}
        self.assertFalse(borrowed & self.scenes.keys())
        self.assertEqual(len(borrowed), 10)

    def test_transverse_drop_control_0_387783(self):
        """Serialized 0.5 m transverse drop: 0.387783 m -> <=0.10 m (smooth fit)."""
        from ground import World
        drops = []
        for index, stream in ((self.before, self.before_stream), (self.after, self.after_stream)):
            world = World(index, stream)
            heights = []
            for lateral in (-.5, 0.):
                q = self.deck.point(730., lateral)
                hit = world.find_face_below(q[0], q[2], q[1]+2.)
                self.assertIsNotNone(hit)
                heights.append(hit.height)
            drops.append(abs(heights[0]-heights[1]))
        self.assertAlmostEqual(drops[0], .387783, places=5)
        self.assertLessEqual(drops[1], .10)
        self.assertAlmostEqual(self.deck.ha, 8.95110249205, places=7)
        self.assertAlmostEqual(self.deck.hb, 25.71436505187, places=7)
        print(f'COAST transverse collision drop {drops[0]:.6f} -> {drops[1]:.6f} m', flush=True)

    def test_island_flare_quads_zero_control_107(self):
        """Referenced island flare quads over all LODs: 107 -> 0; water, buoy, fog stay native."""
        native = self.scenes[999][1]
        def cards(scene):
            keys = {C.u32(scene.models, m+off) for m in range(0, len(scene.models), 72)
                    for off in (24, 28, 32, 36)} - {0, 0xbe43edbb, 0x90f70174}
            total = 0
            for key in keys:
                solid = self.solids[key]
                tex = [k for k, _ in struct.iter_unpack('<2I', C.one(C.children(solid), 0x134012).payload)]
                rec = C.aligned_payload(C.one(C.children(C.one(C.children(solid), 0x80134100)), 0x134b02))
                total += sum(C.u32(rec, p+96)//2 for p in range(0, len(rec), 144)
                             if tex[rec[p+24]] == 0x0319ab30)
            return total
        self.assertEqual(cards(native), 107)
        selected = self.after_scenes.get(1940, native)
        self.assertEqual(cards(selected), 0)
        self.assertEqual([C.model_name(selected, i) for i in range(4)],
                         [C.model_name(native, i) for i in (2, 3, 4, 5)])
        for new, old in enumerate((2, 3, 4, 5)):
            a, b = selected.instances[new*96:(new+1)*96], native.instances[old*96:(old+1)*96]
            self.assertEqual(a[:84]+a[86:], b[:84]+b[86:])
        print('COAST referenced island flare quads 107 -> 0; water/buoy/fog retained', flush=True)

    def test_missing_panorama_sections_zero_control_eight(self):
        """Missing panorama sections per early row: 8 -> 0; exactly 33 native instances."""
        import c1_world as w
        mapping = ((1591, 1980), (1592, 1982), (1594, 1983), (1595, 1984),
                   (1799, 1985), (1888, 1986), (1891, 1987), (1894, 1988))
        required = {dest for _, dest in mapping}
        before = {r.number: set(r.entries) for r in w.vis.read(w.vis.payload_of(self.before)).rows}
        after = {r.number: set(r.entries) for r in w.vis.read(w.vis.payload_of(self.after)).rows}
        for n in (924, 925, 913, 2014):
            self.assertEqual(sum(source not in before[n] or self.scenes[source][0] not in before[n]
                                 for source, _ in mapping), 8)
            self.assertEqual(len(required-after[n]), 0)
        count = 0
        for source, dest in mapping:
            native = self.scenes[source][1]
            expected = [i for i in range(len(native.instances)//96)
                        if C.model_name(native, i).startswith(('PAN_', 'TRN_Ocean'))]
            selected = self.after_scenes[dest]
            self.assertEqual(len(selected.instances)//96, len(expected))
            for new, old in enumerate(expected):
                a, b = selected.instances[new*96:(new+1)*96], native.instances[old*96:(old+1)*96]
                self.assertEqual(a[:84]+a[86:], b[:84]+b[86:])
            count += len(expected)
        self.assertEqual(count, 33)
        report = C.check_far_rows(self.after, self.after_stream)
        self.assertTrue(all(r['bytes'] <= 71680000 for r in report.values()))
        print(f'COAST missing panorama sections 8 -> 0 per early row; {count} native instances', flush=True)

    @staticmethod
    def side_misses(triangles, deck, stations):
        import numpy as np
        t = np.asarray(triangles)
        a, u, v = t[:, 0], t[:, 1]-t[:, 0], t[:, 2]-t[:, 0]
        misses = 0
        for s in stations:
            for side in (-1, 1):
                p = np.asarray(deck.point(s, side*18.))
                # The ray is one metre below the actual deck edge, not below an
                # extrapolated road surface two metres outside that edge.
                p[1] = deck.height(s, side*16.)-1.
                direction = np.asarray(tuple(-side*x for x in deck.z))
                h = np.cross(direction, v)
                determinant = np.sum(u*h, axis=1)
                inv = 1/np.where(abs(determinant)>1e-10, determinant, 1.)
                q = p-a
                b = inv*np.sum(q*h, axis=1)
                cross = np.cross(q, u)
                c = inv*np.sum(direction*cross, axis=1)
                distance = inv*np.sum(v*cross, axis=1)
                misses += not ((abs(determinant)>1e-10)&(b>=-1e-7)&(c>=-1e-7)&
                               (b+c<=1+1e-7)&(distance>=0)&(distance<=4)).any()
        return int(misses)

    def test_far_shore_and_sides_zero_control_69(self):
        """Far-row uncovered rays: 31 shore + 38 deck sides = 69 -> 0."""
        import c1_world as w
        points = [self.deck.point(self.deck.cut(0, l)-.25, l) for l in range(-15, 16)]
        stations = [s+self.parts['step']/2 for s in self.parts['starts']]
        counts = []
        for index, stream in ((self.before, self.before_stream), (self.after, self.after_stream)):
            scenes, solids = self.decoded_scenes(index, stream)
            entries = next(set(r.entries) for r in w.vis.read(w.vis.payload_of(index)).rows if r.number == 1833)
            shore, deck = [], []
            for home, scene in scenes.values():
                if home not in entries:
                    continue
                for i in range(len(scene.instances)//96):
                    row = scene.instances[i*96:(i+1)*96]
                    key = C.u32(scene.models, struct.unpack_from('<h', row, 84)[0]*72+24)
                    if home != 1900:
                        lo, hi = struct.unpack_from('<3f', row), struct.unpack_from('<3f', row, 16)
                        if hi[0]<3100 or lo[0]>3220 or hi[1]<-1740 or lo[1]>-1600:
                            continue
                    try:
                        mesh = C.link.mesh(solids[key])
                    except KeyError:
                        continue  # Ocean effect 26 is not floor or a vertical deck side.
                    target = deck if home == 1900 else shore
                    target.extend(tuple(C.physics(v, row) for v in tri) for tri in mesh)
            counts.append((self.point_misses(shore+deck, points), self.side_misses(deck, self.deck, stations)))
        self.assertEqual(counts, [(31, 38), (0, 0)])
        shore = self.after_scenes[1989]
        self.assertEqual(len(shore.instances)//96, 31)
        expected = []
        for source in (965, 978, 924, 925):
            native = self.scenes[source][1]
            for i in range(len(native.instances)//96):
                row = native.instances[i*96:(i+1)*96]
                key = C.u32(native.models, struct.unpack_from('<h', row, 84)[0]*72+24)
                if source in (965, 978) or key in (0xe9a19c1a, 0xe9a10fb9):
                    expected.append(row)
        for i, native in enumerate(expected):
            row = shore.instances[i*96:(i+1)*96]
            # Only model and precull selectors change; transforms/heights are bit-identical.
            self.assertEqual(row[:28]+row[30:84]+row[86:], native[:28]+native[30:84]+native[86:])
        print(f'COAST uncovered shore/side rays {counts[0]} -> {counts[1]}', flush=True)

    def test_corner_gap_zero_control_1_8566(self):
        from ground import World
        world = World(self.after, self.after_stream)
        key = next(iter(world.packs.keys()-self.parts['world'].packs.keys()))
        pack = world.packs[key]
        endpoints, edges = [], []
        for row_at in range(0, len(pack.instances), 64):
            row = pack.instances[row_at:row_at+64]
            art = pack.articles[struct.unpack_from('<H', row, 26)[0]]
            translation = struct.unpack_from('<3f', row, 48)
            _, offset, count, _ = struct.unpack_from('<4H', art)
            for i in range(count):
                edge = tuple(C.sub(struct.unpack_from('<3f', art, 16+offset+32*i+o), translation) for o in (0, 16))
                edges.append(edge)
                endpoints.extend(edge)
        gap = max(min(math.hypot(p[0]-q[0], p[2]-q[2]) for p in endpoints)
                  for anchors in self.deck.rail_joins.values() for q in anchors)
        q = self.deck.rail_joins[1][0]
        p = self.deck.point(16.5, 15.2)
        control = math.hypot(p[0]-q[0], p[2]-q[2])
        self.assertAlmostEqual(control, 1.85661, places=4)
        self.assertLess(gap, .0005)
        for anchors in self.deck.rail_joins.values():
            for end, anchor in enumerate(anchors):
                matches = [(a, b) for a, b in edges if min(math.hypot(p[0]-anchor[0], p[2]-anchor[2]) for p in (a, b)) < .0005]
                self.assertEqual(len(matches), 1)
                a, b = matches[0]
                station = C._sl(self.deck, anchor)[0]
                centre = self.deck.point(station+(1 if end == 0 else -1), 0.)
                self.assertLessEqual((b[0]-a[0])*(centre[2]-a[2])-(b[2]-a[2])*(centre[0]-a[0]), 0.)

        # The left opening is not an existing road: native asphalt begins at 758.15 m.
        self.assertGreater(self.deck.cut(1, -16.), 758.)
        self.assertGreater(self.deck.rail_ranges[-1][1], 746.)
        print(f'COAST unjoined corner gap {gap:.3f} m; original control {control:.4f} m', flush=True)

    def test_carriageway_overpaint_zero_control_65_76(self):
        # Independently intersect the native material triangles with every integer lateral.
        _, _, solid, _, _ = self.parts['source']
        targets, _ = C.floor_sources(self.index, self.stream)
        asphalt = []
        sidewalk = []
        for key, row in targets.items():
            parts = C.children(C.one(C.children(self.solids[key]), 0x80134100))
            records = C.aligned_payload(C.one(parts, 0x134b02))
            names = [p.payload.split(b'\0')[0].decode() for p in parts if p.kind == 0x134c02]
            triangles = iter(C.link.mesh(self.solids[key]))
            for off, name in zip(range(0, len(records), 144), names):
                for _ in range(C.u32(records, off+96)):
                    tri = [C._sl(self.deck, C.physics(v, row)) for v in next(triangles)]
                    if max(p[0] for p in tri) < 50:
                        if 'Pavement' in name:
                            asphalt.append(tri)
                        if 'Sidewalk' in name:
                            sidewalk.append(tri)
        cuts = []
        for l in range(-16, 17):
            intervals = [C.line_interval(t, l) for t in sidewalk]
            edge = min(v[0] for v in intervals if v and v[1]-v[0] > 1e-7 and 6 <= v[0] <= 13)
            cuts.append(math.ceil(edge*100-1e-8)/100)
        control = sum((a+b)/2-6 for a, b in zip(cuts, cuts[1:]))
        self.assertAlmostEqual(control, 65.76, places=2)
        draw = [[C._sl(self.deck, v) for v in tri] for tri in self.draws if min(C._sl(self.deck,v)[0] for v in tri) < 30]
        area = sum(triangle_overlap(t, u) for t in draw for u in asphalt)
        self.assertLess(area, .005)  # float32 serialization: rounds to zero square metres
        print(f'COAST carriageway overpaint {area:.2f} m2; original control {control:.2f} m2', flush=True)

    def test_borrowed_yellow_cards_zero_control_100(self):
        _, scene = self.scenes[1097]
        row = scene.instances[:96]
        key = C.u32(scene.models, struct.unpack_from('<h', row, 84)[0]*72+24)
        solid = self.solids[key]
        textures = [k for k, _ in struct.iter_unpack('<2I', C.one(C.children(solid), 0x134012).payload)]
        parts = C.children(C.one(C.children(solid), 0x80134100))
        records = C.aligned_payload(C.one(parts, 0x134b02))
        control = sum(C.u32(records, p+96)//2 for p in range(0, len(records), 144)
                      if textures[records[p+24]] == 0x0319ab30)
        self.assertEqual(control, 100)
        selected = self.after_scenes[1916]
        self.assertFalse(any(C.model_name(selected, i) == 'PAN_Muscle_Docklights'
                             for i in range(len(selected.instances)//96)))
        print(f'COAST borrowed yellow cards 0; original control {control}', flush=True)

    def test_near_wall_pairs_zero_control_366(self):
        import numpy as np
        detailed, panorama = [], []
        have = self.rows[1833] | {1597, 2400, 2500, 2600}
        for home, scene in self.scenes.values():
            if home not in have:
                continue
            for i in range(len(scene.instances)//96):
                row = scene.instances[i*96:(i+1)*96]
                lo, hi = struct.unpack_from('<3f', row), struct.unpack_from('<3f', row, 16)
                if hi[0]<2100 or lo[0]>2640 or hi[1]<-1900 or lo[1]>-1390:
                    continue
                name = C.model_name(scene, i)
                if name.startswith(('PAN_', 'SKY')) and name != 'PAN_CP_FishVillage_01':
                    continue
                key = C.u32(scene.models, struct.unpack_from('<h', row, 84)[0]*72+24)
                if key not in self.solids:
                    continue
                try:
                    mesh = C.link.mesh(self.solids[key])
                except KeyError:
                    continue
                target = panorama if name == 'PAN_CP_FishVillage_01' else detailed
                target.extend(tuple(C.physics(v, row) for v in t) for t in mesh)
        d = np.asarray(detailed)
        normals = np.cross(d[:, 1]-d[:, 0], d[:, 2]-d[:, 0])
        normals /= np.maximum(np.linalg.norm(normals, axis=1)[:, None], 1e-30)
        low, high = d.min(1), d.max(1)
        control = 0
        for t in np.asarray(panorama):
            normal = np.cross(t[1]-t[0], t[2]-t[0])
            size = np.linalg.norm(normal)
            if size < 1e-9:
                continue
            normal /= size
            if abs(normal[1]) > .2:
                continue
            distance = np.max(abs(np.sum((d-t[0])*normal, axis=2)), axis=1)
            mask = ((abs(np.sum(normals*normal, axis=1))>.999999)&(distance<.002)&
                    np.all((high>=t.min(0)-.002)&(low<=t.max(0)+.002), axis=1))
            axes = [k for k in range(3) if k != int(np.argmax(abs(normal)))]
            control += sum(triangle_overlap(t[:, axes].tolist(), d[i][:, axes].tolist()) > .01
                           for i in np.nonzero(mask)[0])
        self.assertEqual(control, 366)
        selected = self.after_scenes[1908]
        self.assertFalse(any(C.model_name(selected, i) == 'PAN_CP_FishVillage_01'
                             for i in range(len(selected.instances)//96)))
        print(f'COAST overlapping wall pairs 0; original control {control}', flush=True)

    def test_known_provider_misses_zero_control_55(self):
        import c1_world as w
        report = C.check_far_rows(self.after, self.after_stream)
        for n in (1833, 1835, 1838):
            self.assertEqual(C.known_provider_misses(self.rows[n], self.inventory), 55)
            self.assertEqual(report[n]['known_provider_misses'], 0)
            self.assertLessEqual(report[n]['bytes'], 71680000)
        sizes = {s.number: s.size for s in self.after.sections}
        peak = max(sum(sizes.get(n, 0) for n in set(r.entries)|{2400, 2600} if n != 2500)
                   for r in w.vis.read(w.vis.payload_of(self.after)).rows)
        self.assertLessEqual(peak, 71680000)
        print(f'COAST known-provider misses 0; original control 55; peak {peak}/71680000 bytes', flush=True)

    def test_pack_header_chunks_are_144_bytes(self):
        """Every 0x134002 chunk in the borrowed-scenery sections is 144 bytes: 10 short -> 0."""
        import c1_world as w
        from merge import read_section
        sizes = []
        for section in self.after.sections:
            if section.number not in (1940, 1980, 1982, 1983, 1984, 1985, 1986, 1987, 1988, 1989):
                continue
            for root in C.chunks(read_section(self.after_stream, section)):
                if root.kind == 0x80134000:
                    for pack in C.children(root):
                        if pack.kind == 0x80134001:
                            sizes += [len(c.payload) for c in C.children(pack) if c.kind == 0x134002]
        self.assertEqual(len(sizes), 10, sizes)
        self.assertEqual([n for n in sizes if n != 144], [])
        print(f'COAST pack header chunks {len(sizes)} all 144 bytes; old 80-byte control 10 short', flush=True)


if __name__ == '__main__':
    unittest.main()
