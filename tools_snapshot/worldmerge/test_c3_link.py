"""Mixed connecting-road proof, read from serialized archives; no game runs.

Heading over 10 m (1 m samples): original T 60.493628 degrees FAIL;
K28/CSCSSC eight-hinge fit 9.917104 degrees PASS, unchanged limit 12 degrees.
Whole-overlap collision floor disagreement: fixed-tilt Part 3 6.181351 m
FAIL; eight-hinge K28/CSCSSC 0.299901 m PASS, unchanged limit .30 m.
Both numbers use the rebuilt archives, including collision quantization.
Every source article and solid is copied; the three curves use both shipped
collision halves. Source entry cuts have a decoded 0.11..0.12 m collision
inset at three mixed seams: 9/165 native misses and one rounded edge miss,
independently bounded by the .01 m every-vertex bake check. The
baked-versus-source height-step limit stays .02 m. The top overlap is checked separately over every collision triangle;
mixed profiles are reported rather than held to the old T's join limits.
Broken controls retain moved/lowered copies, omitted cell references,
unmapped joins, one-way flags, unopened gates and restored fence physics.
Reflection instances: original 6 FAIL -> rebuilt 0 PASS.
Pond core coverage: old left/right 0/4200 FAIL -> rebuilt 4200/4200 PASS.
Crossing overhang 534ae112: unchanged 1 FAIL -> rebuilt 0 PASS;
scene 326 instances 429 -> 428, every other row and the graph unchanged.
Crossing leg barrier clearance: original 0.000000 m FAIL -> 3.110876 m
PASS, N = 2 m (2 m car width plus 1 m centre error each side). The old
edge's inner endpoint is 0.2076 m from the transverse floor midpoint;
the segment itself crosses the midpoint line. Other pack/edge bytes and
the road map are unchanged. Offset-lane clearance with edge 2 already
removed: retained edge 1 0.000000 m FAIL -> 3.530026 m PASS, N = 2 m.
The lane is 4 m toward the retained rail from the floor midpoint, checked
where floor width >= 12 m (4 m lane offset plus the 2 m corridor each side).
The corridors do not certify every lane line.
Routing invariants: base degree-2 violations 1 / connector violations 1;
corrected 0 / 0 (4,724 degree-2 nodes, 4,264 connector nodes).
Crossing panorama 283 in zone 326: main row 0 FAIL -> rebuilt 1 PASS;
21 -> 22 entries, resident bytes 51,825,324 -> 51,832,116.
Frozen c3dropr1 f1636 draw replay at 960x540: main sky below horizon
2,693 FAIL -> panorama 283 1,009 PASS; left 1,757 -> 73, right 936 -> 936.
Synthetic checks run without assets; absent private archives exit 3.
"""
import copy
from dataclasses import replace
import hashlib
import json
import math
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0,str(HERE))
import c1_world as w
import c3_link as c
import ground as g
from formats import Chunk, FormatError
from merge import load_index, read_section
from region import collision_body, one
from test_ground import pack_bytes

ASSETS = all((root/name).is_file() for root,base in
             ((w.DEFAULT_MW,'L2RA'),(w.DEFAULT_CARBON,'L5RA'))
             for name in (base+'.BUN','STREAM'+base+'.BUN'))
SCRATCH = HERE.parents[1]/'.metal-cache'

# Exact original Pack.faces fragment that accepted orthogonal tilted rows.
# Only the vertex transform and its acceptance guard are needed by this
# control; the current parser supplies the unchanged strips and attributes.
OLD_BASIS = '''middle = cross(g, f) if flags & 3 else (0., 1., 0.)
basis = (f, middle, g)
require(all(abs(dot(a, b) - (1. if i == j else 0.)) < .002
            for i, a in enumerate(basis) for j, b in enumerate(basis)),
        'nonorthonormal collision instance')
'''
OLD_BASIS_SHA256 = '4fa11e09cf454d25c0b0353ea85ad1ec5a32a9f3ebd14d7d8ec2ca0f6fddb0a0'

# Exact previous builder selector fragment; the old pack path was unchanged.
OLD_DROP = 'DROP = (122, 356, 359, 374, 376, 393, 398, 399)\n'
OLD_DROP_SHA256 = 'd4ff8770baefe24bb8615343176c597655a1c5fab7a3901bc748d67f7fdc13ef'


# Exact opener before the retained crossing-road edge was removed.
OLD_ROUTE_OPEN = '''def open_route_pack(raw, nodes, top_cut):
    """Open the Rockport gate and the rail met by the height-fitted arc."""
    key = u32(raw, 4)
    if key == 134:
        return trim_barriers(raw, ((10, (8,), top_cut),))
    if key == 192:
        aid, edge, a, b, half = 12, 10, 8739, 8740, 16.
    else:
        return raw
    start, end = nodes[a], nodes[b]
    direction = unit((end[0]-start[0], 0., end[2]-start[2]))
    lateral = (direction[2], 0., -direction[0])
    cut = [add(start, tuple(sign*half*v for v in lateral)) for sign in (-1, 1)]
    return trim_barriers(raw, ((aid, (edge,), cut),))
'''
OLD_ROUTE_OPEN_SHA256 = '923936da18148d2628c9d1c406a15e4f0cbf8f4269c850ca0a118f675b00997f'


# Exact opener after edge 2 was removed, before the next edge was trimmed.
EDGE2_ROUTE_OPEN = '''def open_route_pack(raw, nodes, top_cut):
    """Open the Rockport gate and the rail met by the height-fitted arc."""
    key = u32(raw, 4)
    if key == 134:
        # Edge 6 ends inside the copied carriageway (edge 2 after tidying).
        return trim_barriers(raw, ((10, (6, 8), top_cut),))
    if key == 192:
        aid, edge, a, b, half = 12, 10, 8739, 8740, 16.
    else:
        return raw
    start, end = nodes[a], nodes[b]
    direction = unit((end[0]-start[0], 0., end[2]-start[2]))
    lateral = (direction[2], 0., -direction[0])
    cut = [add(start, tuple(sign*half*v for v in lateral)) for sign in (-1, 1)]
    return trim_barriers(raw, ((aid, (edge,), cut),))
'''
EDGE2_ROUTE_OPEN_SHA256 = '8bf8f90719a870040e19afc57ebf998a68d701d74cd28d989b1a635dd5edcc62'


def crossing_barrier_clearance(index, stream, lane_offset=0.):
    """Smallest barrier distance to the floor midpoint on leg 8988 -> 8989.

    Transverse sections of the serialized copied floor define the midpoint,
    sampled at <= 1 m along this straight graph leg. Distances to each
    midpoint chord and each barrier rectangle are continuous. Only barriers
    intersecting floor +.3..1.5 m count. This checks a central 4 m corridor:
    a 2 m car footprint plus 1 m centre error each side, well inside the
    measured floor half-width (>= 2 m even at the oblique end cuts,
    about 11.4 m near the obstruction). The offset lane checks only complete
    sections wide enough to contain that lane's same 2 m corridor. It does
    not certify all lane lines.
    """
    world = g.World(index, stream)
    start, end = (world.nodes[i] for i in (8988, 8989))
    tangent = c.unit((end[0]-start[0], 0., end[2]-start[2]))
    normal = (tangent[2], 0., -tangent[0])
    # The first copied collision pair, independent of the builder's selector.
    faces = [f for i in (0, 1) for f in world.packs[360].faces(i)]
    centers, widths = [], []
    count = math.ceil(math.dist(start, end))
    for i in range(count+1):
        p = tuple(start[k]+(end[k]-start[k])*i/count for k in range(3))
        offsets = []
        for face in faces:
            for a, b in zip(face.vertices, face.vertices[1:]+face.vertices[:1]):
                da, db = (c.dot(c.sub(v, p), tangent) for v in (a, b))
                if da*db <= 0 and abs(da-db) > 1e-10:
                    hit = tuple(a[k]+(b[k]-a[k])*da/(da-db) for k in range(3))
                    offsets.append(c.dot(c.sub(hit, p), normal))
        assert offsets, ('missing transverse floor', i)
        lo, hi = min(offsets), max(offsets)
        if lane_offset and hi-lo < 2*(abs(lane_offset)+2.):
            continue
        widths.append(hi-lo)
        x, _, z = c.add(p, tuple(((lo+hi)/2+lane_offset)*v for v in normal))
        y = c.height(faces, x, z)
        assert y is not None, ('missing midpoint floor', i)
        centers.append((x, y, z))
    assert len(centers) >= 2, 'missing car corridor'
    lower, upper = c.bounds(centers)
    nearest = (float('inf'), None)
    for key, pack in world.packs.items():
        for instance in range(len(pack.instances)//64):
            row = pack.instances[instance*64:(instance+1)*64]
            aid = struct.unpack_from('<H', row, 26)[0]
            translation = struct.unpack_from('<3f', row, 48)
            article = pack.articles[aid]
            offset = 16+struct.unpack_from('<H', article, 2)[0]
            for edge in range(struct.unpack_from('<H', article, 4)[0]):
                a, b = (c.sub(struct.unpack_from('<3f', article, offset+32*edge+p), translation)
                        for p in (0, 16))
                if any(max(a[k],b[k]) < lower[k]-12 or min(a[k],b[k]) > upper[k]+12
                       for k in (0, 2)):
                    continue
                vertices = (a, (b[0],a[1],b[2]), b, (a[0],b[1],a[2]))
                for p, q in zip(centers, centers[1:]):
                    dx, dz = q[0]-p[0], q[2]-p[2]
                    length = math.hypot(dx, dz)
                    for ids in ((0,1,2), (0,2,3)):
                        poly = c.sweep_prism(tuple(vertices[j] for j in ids),p,q,width=12.)
                        if not poly:
                            continue
                        sides = [((v[0]-p[0])*dz-(v[2]-p[2])*dx)/length for v in poly]
                        distance = max(0., min(sides), -max(sides))
                        if distance < nearest[0]:
                            nearest = distance, (key, instance, aid, edge)
    return nearest, min(widths)


# Exact pre-filter finishing function, independent of repository history.
OLD_TIDY = '''def tidy(tracks):
    import c1_world as w
    from merge import load_index, read_section
    index, stream, _ = load_index(tracks,'L5RA')
    roots = inventory(index,stream)
    road = w.scene_data(next(r for r in roots[366] if r.kind == w.SCENE and w.scene_data(r).number == 366))
    cut = leg_cut(roots,road.instances[23*96:24*96])
    rail = next(solid for section in index.sections if section.number == 2100
                for solid in solids(list(chunks(read_section(stream,section)))) if solid_key(solid) == RAIL)
    rendered = tidy_render(roots[366],cut,rail)
    shadow = w.scene_data(next(r for r in roots[366] if r.kind == w.SCENE and w.scene_data(r).number == 326))
    _,path = rail_rows(shadow,cut,rail)
    out = Builder(0)
    for root in roots[2600]:
        if root.kind == w.PACK and u32(collision_body(root),4) == 134:
            out.pad(16)
            out.add(w.PACK,tidy_collision(collision_body(root),cut,path),16)
        else:
            w.append_at_residue(out,root)
    rewrite(tracks,index,stream,{366:b''.join(r.encode() for r in rendered),2600:bytes(out.data)},{})
'''
OLD_TIDY_SHA256 = '959b73dd37413d4bbe55b30952c1210af81d51b90bb8efffefd06fe71f9b464f'


# Original bottom-pinned straight composer for the measured T control.
OLD_CHAIN = '''def chain(high, low, target):
    """The node-pinned diagnostic, including its original +0.72 degree tilt."""
    hc, lc = mean(high), mean(low)
    a, b = sub(high[-1], high[0]), sub(low[-1], low[0])
    turn = math.atan2(b[0], b[2])-math.atan2(a[0], a[2])
    step = rotation((0., 1., 0.), turn)
    delta = sub(lc, mv(step, hc))
    placements, m, t = [], IDENTITY, (0., 0., 0.)
    for _ in range(COUNT):
        placements.append((m, t))
        t, m = add(mv(m, delta), t), mm(m, step)
    displacement = sub(add(mv(m, hc), t), hc)
    forward = sub(lc, hc)
    tilt = rotation(cross((0., 1., 0.), unit((forward[0], 0., forward[2]))),
                    math.radians(.72))
    chord = mv(tilt, displacement)
    start = (-2678., target[1]-chord[1],
             target[2]+math.sqrt(chord[0]**2+chord[2]**2-(-2678.-target[0])**2))
    yaw = math.atan2(target[0]-start[0], target[2]-start[2])-math.atan2(chord[0], chord[2])
    q = mm(rotation((0., 1., 0.), yaw), tilt)
    offset = sub(start, mv(q, hc))
    return [(mm(q, m), add(mv(q, t), offset)) for m, t in placements]
'''
OLD_CHAIN_SHA256 = '12b68c44bf9530d9122745bc2718a35b6f48ee1431a7b8913bb4fa84683acbfa'

# Frozen fixed-axis composer for the independent whole-overlap control.
PART3_LAYOUT = '''def layout(roots, target):
    """Bottom-pinned straights, then the selected tail in pre-affine space.

    Output order is downhill, as the serialized graph and original copies.
    One rotation about the entry cross line fits the whole tail's height.
    Both source cut frames participate at every mixed seam.
    """
    donors = {'S': geometry(roots), 'C': curve_geometry(roots)}
    straight = chain(donors['S'][4], donors['S'][5], target)[34-RETAINED:]
    m, t = straight[0]
    entry = [add(mv(m, p), t) for p in donors['S'][4]]
    origin = mean(entry)
    tilt = rotation(sub(entry[-1], entry[0]), math.radians(TAIL_TILT))
    current, tail = entry, []
    for kind in TAIL:
        high, low = donors[kind][4:6]
        m = mm(cut_frame(current), transpose(cut_frame(low)))
        t = sub(mean(current), mv(m, mean(low)))
        tail.append((kind, mm(tilt, m), add(origin, mv(tilt, sub(t, origin)))))
        current = [add(mv(m, p), t) for p in high]
    pieces = [*reversed(tail), *(('S', m, t) for m, t in straight)]
    require(len(pieces) == COUNT, 'mixed layout count differs')
    return [(kind, mm(AFFINE, m), add(mv(AFFINE, t), OFFSET)) for kind, m, t in pieces]

'''
PART3_LAYOUT_SHA256 = 'cef93bd010f3c370d43539143ab9d6decbb7db4379bd3cae5a7b1480de52624d'

def old_basis(row):
    scope = dict(f=struct.unpack_from('<3f',row), g=struct.unpack_from('<3f',row,32),
                 flags=struct.unpack_from('<H',row,18)[0], cross=g.cross, dot=g.dot, require=c.require)
    exec(compile(OLD_BASIS,'<original-basis>','exec'),scope)
    return scope['basis']


class Synthetic(unittest.TestCase):
    def test_swept_box_includes_vertical_and_edge_hits_but_not_floor(self):
        a,b = (0.,0.,0.),(0.,0.,10.)
        self.assertTrue(c.sweep_prism(((-2.,0.,5.),(2.,0.,5.),(0.,2.,5.)),a,b))
        self.assertFalse(c.sweep_prism(((-2.,0.,5.),(2.,0.,5.),(0.,0.,7.)),a,b))
        self.assertFalse(c.sweep_prism(((2.,0.,5.),(3.,0.,5.),(2.,2.,5.)),a,b))

    def test_floor_overlap_clips_both_meshes_and_retains_sign(self):
        flat = g.Face(((0.,0.,0.),(4.,0.,0.),(0.,0.,4.)),134,26,2,0,0)
        slope = g.Face(((1.,1.,1.),(5.,5.,1.),(1.,1.,5.)),360,0,0,0,0)
        result = c.floor_overlap([slope],[flat])
        self.assertAlmostEqual(result['maximum'],3.)
        self.assertEqual(result['new_minus_old'],3.)
        self.assertEqual((result['x'],result['z']),(3.,1.))
        self.assertEqual((result['old_pack'],result['old_instance'],result['old_strip']),(134,26,2))
        reverse = c.floor_overlap([flat],[slope])
        self.assertAlmostEqual(reverse['new_minus_old'],-3.)

    def test_original_acceptance_guard_and_current_refusal(self):
        self.assertEqual(hashlib.sha256(OLD_BASIS.encode()).hexdigest(),OLD_BASIS_SHA256)
        raw = pack_bytes(basis=((0.,0.,1.),(1.,0.,0.)),translation=(-10.,-20.,-30.))
        p = g.Pack(raw)
        row = bytearray(p.instances)
        struct.pack_into('<H',row,18,1)
        self.assertEqual(old_basis(row),((0.,0.,1.),(0.,-1.,0.),(1.,0.,0.)))
        p.instances = bytes(row)
        with self.assertRaisesRegex(FormatError,'triangle cache'):
            list(p.faces(0))

    def test_nonrigid_bake_preserves_topology_quantization_and_bounds(self):
        p = g.Pack(pack_bytes())
        m,t = c.AFFINE,(-2.,3.,4.)
        row,article = c.bake(p,0,m,t,0)
        body = c.carp([(c.grid.CI,1,row),(0x636f0000,0,b''),(0x63610000,1,article)])
        baked = g.Pack(struct.pack('<4I',len(body),360,0,0)+body)
        actual, = baked.faces(0)
        original, = p.faces(0)
        error = max(c.math.dist(v,c.add(c.mv(m,u),t)) for v,u in zip(actual.vertices,original.vertices))
        self.assertLessEqual(error,.01)
        self.assertEqual((actual.strip,actual.triangle,actual.flags),
                         (original.strip,original.triangle,original.flags))
        center = tuple(-v for v in struct.unpack_from('<3f',row,48))
        extent = [struct.unpack_from('<f',row,q)[0] for q in (12,20,44)]
        self.assertTrue(all(abs(v[k]-center[k]) <= extent[k] for v in actual.vertices for k in range(3)))


@unittest.skipUnless(ASSETS,'private world archives absent')
class Private(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        SCRATCH.mkdir(exist_ok=True)
        cls.tmp = tempfile.TemporaryDirectory(prefix='c3-link-test-',dir=SCRATCH)
        cls.addClassCleanup(cls.tmp.cleanup)
        cls.root = Path(cls.tmp.name)
        cls.directory,cls.base_directory = cls.root/'mapped',cls.root/'base'
        cls.directory.mkdir()
        cls.base_directory.mkdir()
        cls.barrier_directory = cls.root/'retained-crossing-barrier'
        cls.barrier_directory.mkdir()
        assert hashlib.sha256(OLD_ROUTE_OPEN.encode()).hexdigest() == OLD_ROUTE_OPEN_SHA256
        original_opener = dict(c.__dict__)
        exec(compile(OLD_ROUTE_OPEN, '<original-route-opener>', 'exec'), original_opener)
        with patch.object(c, 'open_route_pack', original_opener['open_route_pack']):
            w._write_pair(w.DEFAULT_MW,w.DEFAULT_CARBON,cls.barrier_directory,shift=c.SHIFT)
        cls.edge1_directory = cls.root/'retained-next-barrier'
        cls.edge1_directory.mkdir()
        assert hashlib.sha256(EDGE2_ROUTE_OPEN.encode()).hexdigest() == EDGE2_ROUTE_OPEN_SHA256
        edge2_opener = dict(c.__dict__)
        exec(compile(EDGE2_ROUTE_OPEN, '<edge2-only-opener>', 'exec'), edge2_opener)
        with patch.object(c, 'open_route_pack', edge2_opener['open_route_pack']):
            w._write_pair(w.DEFAULT_MW,w.DEFAULT_CARBON,cls.edge1_directory,shift=c.SHIFT)
        w._write_pair(w.DEFAULT_MW,w.DEFAULT_CARBON,cls.base_directory,shift=c.SHIFT,_link=False)
        w._write_pair(w.DEFAULT_MW,w.DEFAULT_CARBON,cls.directory,shift=c.SHIFT)
        cls.r1_directory = cls.root/'with-r1'
        cls.r1_directory.mkdir()
        with patch.object(c, 'DROP_326', ()):
            w._write_pair(w.DEFAULT_MW,w.DEFAULT_CARBON,cls.r1_directory,shift=c.SHIFT)
        cls.r1_index, cls.r1_stream, _ = load_index(cls.r1_directory/'TRACKS', 'L5RA')
        cls.main_directory = cls.root/'main-curve'
        cls.main_directory.mkdir()
        with patch.object(c,'tidy',side_effect=lambda tracks:None):
            w._write_pair(w.DEFAULT_MW,w.DEFAULT_CARBON,cls.main_directory,shift=c.SHIFT)
        assert hashlib.sha256(OLD_TIDY.encode()).hexdigest() == OLD_TIDY_SHA256
        original_tidy = dict(c.__dict__)
        exec(compile(OLD_TIDY, '<original-crossing-finish>', 'exec'), original_tidy)
        cls.reflection_directory = cls.root/'with-reflections'
        cls.reflection_directory.mkdir()
        with patch.object(c, 'tidy', original_tidy['tidy']):
            w._write_pair(w.DEFAULT_MW,w.DEFAULT_CARBON,cls.reflection_directory,shift=c.SHIFT)
        cls.report = w.check(cls.directory,shift=c.SHIFT)
        cls.proof = cls.report['link']
        cls.index,cls.stream,_ = load_index(cls.directory/'TRACKS','L5RA')
        cls.base,cls.base_stream,_ = load_index(cls.base_directory/'TRACKS','L5RA')
        old = cls.root/'old-link'
        old.mkdir()
        assert hashlib.sha256(OLD_DROP.encode()).hexdigest() == OLD_DROP_SHA256
        self_hash = hashlib.sha256(OLD_CHAIN.encode()).hexdigest()
        assert self_hash == OLD_CHAIN_SHA256
        original = dict(c.__dict__)
        exec(compile(OLD_CHAIN,'<original-straight-chain>','exec'),original)
        exec(compile(OLD_DROP,'<original-scenery-drop>','exec'),original)
        with patch.object(c,'DROP',original['DROP']), \
             patch.object(c,'TAIL',''), patch.object(c,'RETAINED',34), \
             patch.object(c,'chain',original['chain']), \
             patch.object(c,'tidy',side_effect=lambda tracks:None), \
             patch.object(c,'open_bottom_pack',side_effect=lambda raw,cut:raw), \
             patch.object(c,'open_route_pack',side_effect=lambda raw,nodes,cut:raw):
            w._write_pair(w.DEFAULT_MW,w.DEFAULT_CARBON,old,shift=c.SHIFT)
        part3 = cls.root/'fixed-tilt'
        part3.mkdir()
        assert hashlib.sha256(PART3_LAYOUT.encode()).hexdigest() == PART3_LAYOUT_SHA256
        fixed = dict(c.__dict__, TAIL='CSCSSC', RETAINED=28,
                     TAIL_TILT=-2.3162860423326492)
        exec(compile(PART3_LAYOUT,'<fixed-axis-tail>','exec'),fixed)
        route_opener = c.open_route_pack
        with patch.object(c,'TAIL','CSCSSC'), patch.object(c,'layout',fixed['layout']), \
             patch.object(c,'tidy',side_effect=lambda tracks:None), \
             patch.object(c,'open_route_pack',side_effect=lambda raw,nodes,cut:
                          raw if c.u32(raw,4) == 134 else route_opener(raw,nodes,cut)):
            w._write_pair(w.DEFAULT_MW,w.DEFAULT_CARBON,part3,shift=c.SHIFT)
        fixed_index,fixed_stream,_ = load_index(part3/'TRACKS','L5RA')
        fixed_world = g.World(fixed_index,fixed_stream)
        fixed_pack = fixed_world.packs[360]
        cls.fixed_faces = [f for i in range(len(fixed_pack.instances)//64) for f in fixed_pack.faces(i)]
        cls.old_index,cls.old_stream,_ = load_index(old/'TRACKS','L5RA')
        cls.world,cls.base_world = g.World(cls.index,cls.stream),g.World(cls.base,cls.base_stream)
        roots = c.inventory(cls.index,cls.stream)
        before = c.inventory(cls.base,cls.base_stream)
        _,source,_,local,high,low,_ = c.geometry(before)
        cls.rigid = c.chain(high,low,cls.base_world.nodes[1534])
        cls.placements = c.mapped(cls.rigid)
        scene = w.scene_data(next(r for r in roots[366] if r.kind==w.SCENE and w.scene_data(r).number==366))
        cls.rows = [scene.instances[i*96:(i+1)*96] for i in range(23,57)]
        cls.high,cls.low = c.serialized_cuts(before,cls.rows)
        cls.centers = [c.mean(vs) for vs in cls.high]+[c.mean(cls.low[-1])]
        cls.key = cls.proof['pack_id']
        cls.pack = cls.world.packs[cls.key]
        cls.faces = [[f for j in ids for f in cls.pack.faces(j)] for ids in c.collision_ids()]
        cls.oracle = []
        for kind,m,t in c.layout(before,cls.base_world.nodes[1534]):
            pack,ids = (cls.base_world.packs[1512],(8,)) if kind == 'S' else (cls.base_world.packs[1508],(3,4))
            cls.oracle.append([g.Face(tuple(c.add(c.mv(m,v),t) for v in f.vertices),0,0,0,0,0)
                               for j in ids for f in pack.faces(j)])
        cls.original_high,cls.original_low = high,low
        print('LINK PROOF '+json.dumps(cls.proof,sort_keys=True))

    def test_heading_10m_original_T_control_and_unchanged_limit(self):
        original = c.inventory(self.old_index,self.old_stream)
        donor = c.geometry(original)
        scene = w.scene_data(next(r for r in original[366] if r.kind == w.SCENE))
        rows = [scene.instances[i*96:(i+1)*96] for i in range(23,57)]
        high = [[c.physics(v,row) for v in c.local_cut(donor,True)] for row in rows]
        low = [[c.physics(v,row) for v in c.local_cut(donor,False)] for row in rows]
        old_world = g.World(self.old_index,self.old_stream)
        centers = list(reversed([c.mean(vs) for vs in high]+[c.mean(low[-1])]))
        broken = c.heading_change(centers,c.old_road_centers(old_world),old_world.nodes[8754])
        self.assertAlmostEqual(broken,60.493628,places=5)
        with self.assertRaises(AssertionError):
            self.assertLessEqual(broken,12.)
        actual = self.proof['heading_10m']
        self.assertLessEqual(actual,12.)
        self.assertEqual((c.RETAINED,c.TAIL,c.COUNT),(28,'CSCSSC',34))
        self.assertEqual(len(self.pack.instances)//64,37)
        self.assertLessEqual(self.proof['bake_max'],.01)
        self.assertLessEqual(self.proof['render_max'],.002)
        print(f'HEADING 10m T={broken:.6f} mixed={actual:.6f} limit=12 degrees')

    def test_overlap_fixed_axis_control_fails_hinged_tail_passes(self):
        old = [f for i in (24,25,26,27,28,29) for f in self.base_world.packs[134].faces(i)]
        broken = c.floor_overlap(self.fixed_faces,old)['maximum']
        self.assertAlmostEqual(broken,6.181351059,places=6)
        with self.assertRaises(AssertionError):
            self.assertLessEqual(broken,.30)
        actual = self.proof['floor_overlap']['maximum']
        self.assertLessEqual(actual,.30)
        self.assertEqual(len(c.TAIL_HINGES),len(c.TAIL))
        self.assertEqual(len(c.UPSTREAM_HINGES),2)
        self.assertLessEqual(max(map(abs,(*c.UPSTREAM_HINGES,*c.TAIL_HINGES))),5.)
        print(f'OVERLAP fixed-axis={broken:.9f} hinged={actual:.9f} limit=.30 metres')

    def test_bottom_clearance_old_builder_fails_and_kerbs_survive(self):
        old = c.sweep(self.old_index,self.old_stream)
        opened = c.sweep(self.index,self.stream)
        self.assertEqual(old['undecoded'],[])
        self.assertEqual(opened['undecoded'],[])
        self.assertEqual((len(old['bottom_hits']),len(opened['bottom_hits'])),(3,0))
        for pack,article in ((192,12),):
            hits = lambda report: sum(h['kind'] == 'barrier' and h.get('pack') == pack
                                      and h.get('article') == article for h in report['hits'])
            self.assertEqual((hits(old),hits(opened)),(1,0))
        self.assertEqual({(h['kind'],h.get('pack'),h.get('article'),h.get('edge'))
                          for h in old['bottom_hits'] if h['kind']=='barrier'},
                         {('barrier',220,6,0)})
        self.assertEqual({h['name'] for h in old['bottom_hits'] if h['kind']=='solid'},
                         {'TRN_BLOCKING_CTPT_05_CHOP_B20_0','TRN_BLOCKING_CTPT_05_CHOP_B20_R1'})
        # Independently inspect the retained west/east endpoints and each
        # native inverse-length field; blanket article deletion cannot pass.
        before,after = self.base_world.packs[220],self.world.packs[220]
        for aid,edge,index in ((26,6,6),(6,7,6)):
            a,b = before.articles[aid],after.articles[aid]
            self.assertEqual(a[16+32*edge:16+32*edge+12] if aid==26 else a[16+32*edge+16:16+32*edge+28],
                             b[16+32*index:16+32*index+12] if aid==26 else b[16+32*index+16:16+32*index+28])
            raw=b[16+32*index:16+32*(index+1)]
            p,q = (struct.unpack_from('<3f',raw,o) for o in (0,16))
            self.assertAlmostEqual(struct.unpack_from('<f',raw,28)[0],1/c.math.hypot(p[0]-q[0],p[2]-q[2]),places=6)
            self.assertGreater(c.math.hypot(p[0]-q[0],p[2]-q[2]),5.)
        self.assertEqual(len(after.articles[26]),len(before.articles[26]))
        self.assertEqual(len(after.articles[6]),len(before.articles[6])-32)
        cut = c.bottom_cut(self.index,self.stream)
        left,right = cut[0],cut[-1]
        axis = c.unit((right[2]-left[2],0.,left[0]-right[0]))
        middle = c.mean((left,right))
        a,b = (c.add(middle,tuple(v*s for v in axis)) for s in (-5.,5.))
        half = c.math.hypot(right[0]-left[0],right[2]-left[2])/2-.01
        def mouth_edges(pack):
            hits = set()
            for aid in (6,26):
                article = pack.articles[aid]
                tr = struct.unpack_from('<3f',pack.instances,aid*64+48)
                for e in range(struct.unpack_from('<H',article,4)[0]):
                    p,q = (c.sub(struct.unpack_from('<3f',article,16+32*e+o),tr) for o in (0,16))
                    vertices = (p,(q[0],p[1],q[2]),q,(p[0],q[1],p[2]))
                    if any(c.sweep_prism(tuple(vertices[i] for i in t),a,b,half)
                           for t in ((0,1,2),(0,2,3))):
                        hits.add((aid,e))
            return hits
        self.assertEqual(mouth_edges(before),{(6,0),(6,7),(26,6)})
        self.assertEqual(mouth_edges(after),set())
        print('MOUTH SWEEP old=3 opened=0; full-width edges=3 -> 0 (6/0,6/7,26/6); '
              'full route='+str((len(old['hits']),len(opened['hits'])))+'; retained kerbs=2/2')

    def test_bottom_join_steps_and_top_profile_report_with_unmapped_control(self):
        for stats in (self.proof['joins']['bottom'],):
            self.assertEqual((stats['covered'],stats['outside_misses'],stats['step_samples']), (10,0,127))
            self.assertLessEqual(stats['max_step'],.10)
            self.assertLessEqual(stats['overlap'][0],.127)
        # Match the checkpoint's particular donor roads, rather than unioning
        # adjacent floors: the latter fills the two rigid road-57 edge holes.
        top = [f for i in (28,29) for f in self.base_world.packs[134].faces(i)]
        bottom = list(self.base_world.packs[220].faces(0))
        controls = []
        for cut,(m,t),old in ((self.original_high,self.rigid[0],top),
                              (self.original_low,self.rigid[-1],bottom)):
            points = [c.add(c.mv(m,p),t) for p in cut]
            controls.append(sum(c.height(old,p[0],p[2]) is not None for p in points))
        self.assertEqual(controls,[0,8])
        print('JOIN CONTROL unmapped road coverage='+str(controls))

    def test_every_baked_vertex_old_way_cache_error_and_oracle_control(self):
        self.assertLessEqual(self.proof['bake_max'],.01)
        source = self.base_world.packs[1512]
        original_row = source.instances[8*64:9*64]
        trans = struct.unpack_from('<3f',original_row,48)
        m,t = self.placements[16]
        transpose = tuple(zip(*m))
        old_t = c.sub(trans,c.mv(transpose,t))
        old_t = struct.unpack('<3f',struct.pack('<3f',*old_t))
        error = max(c.math.dist(c.sub(c.add(v,trans),old_t),c.add(c.mv(m,v),t))
                    for f in source.faces(8) for v in f.vertices)
        self.assertGreater(error,1.)
        # Preserve the original orthogonal tilted acceptance as a pinned
        # fragment, separately from the now non-rigid legacy-write control.
        rigid,_ = self.rigid[16]
        row = bytearray(original_row)
        struct.pack_into('<3f',row,0,*rigid[0])
        struct.pack_into('<3f',row,32,*rigid[2])
        struct.pack_into('<H',row,18,1)
        old_basis(row)
        original_faces = len(list(source.faces(8)))
        self.assertEqual(original_faces,72)
        bad = copy.copy(source)
        raw = bytearray(source.instances)
        raw[8*64:9*64] = row
        bad.instances = bytes(raw)
        with self.assertRaisesRegex(FormatError,'triangle cache'):
            list(bad.faces(8))
        refused = total = 0
        for p in self.base_world.packs.values():
            for i in range(len(p.instances)//64):
                total += 1
                try:
                    next(p.faces(i),None)
                except FormatError:
                    refused += 1
        self.assertEqual((total,refused),(15258,0))
        print(f'BAKE max={self.proof["bake_max"]:.12f} old-way-copy17={error:.12f}; '
              f'ORACLE shipped={total} refused={refused}; original tilted accepted={original_faces}, current=refused')

    def test_render_seams_with_one_moved_copy(self):
        self.assertEqual(self.proof['render_seams']['failed'],0)
        high,low = copy.deepcopy(self.high),copy.deepcopy(self.low)
        delta = tuple(v*.1 for v in c.unit(c.sub(self.centers[-1],self.centers[0])))
        high[16] = [c.add(v,delta) for v in high[16]]
        low[16] = [c.add(v,delta) for v in low[16]]
        control = c.render_seams(high,low)
        self.assertEqual(control['failed'],2)
        print('RENDER CONTROL '+json.dumps(control))

    def test_collision_seams_with_one_lowered_copy(self):
        stats = self.proof['collision_seams']
        self.assertEqual((stats['failed'],stats['unexplained_misses']),(0,0))
        self.assertEqual((stats['misses'],stats['source_misses'],stats['rounding_misses']),(10,9,1))
        p = copy.copy(self.pack)
        raw = bytearray(p.instances)
        instance = c.collision_ids()[16][0]
        y = struct.unpack_from('<f',raw,instance*64+52)[0]
        struct.pack_into('<f',raw,instance*64+52,y+.05)
        p.instances = bytes(raw)
        faces = list(self.faces)
        faces[16] = list(p.faces(instance))
        control = c.collision_seams(faces,self.high,self.low,self.oracle)
        print('COLLISION CONTROL '+json.dumps(control))
        self.assertEqual((control['failed'],control['misses']),(2,10))
        old_errors = []
        for i in range(len(c.TAIL),c.COUNT-1):
            d = c.sub(c.mean(self.low[i+1]),c.mean(self.high[i]))
            dx,dz = c.unit((d[0],0.,d[2]))[0::2]
            values = []
            for j in range(1,6):
                point = tuple(self.low[i][0][k]+(self.low[i][-1][k]-self.low[i][0][k])*j/6 for k in range(3))
                before = c.height(faces[i],point[0]-.1*dx,point[2]-.1*dz)
                after = c.height(faces[i+1],point[0]+.1*dx,point[2]+.1*dz)
                self.assertIsNotNone(before)
                self.assertIsNotNone(after)
                values.append(max(0.,abs(before-after)-.016))
            old_errors.append(max(values))
        old_failed = [i for i,error in enumerate(old_errors,len(c.TAIL)) if error > .02]
        # Two newly hinged straights, then the upper seam of lowered copy 16.
        self.assertEqual(old_failed,[6,7,15])
        print(f'COLLISION OLD-FORMULA CONTROL failed={old_failed} max={max(old_errors):.12f}')

    def test_ground_every_ten_metres_and_removed_copy_control(self):
        self.assertEqual(self.proof['ground']['misses'],0)
        self.assertEqual(self.proof['ground']['samples'],148)
        broken = copy.copy(self.world)
        ref = self.key<<16 | c.collision_ids()[16][0]
        broken.cells = {cid:{s:tuple(v for v in refs if v != ref) for s,refs in regions.items()}
                        for cid,regions in self.world.cells.items()}
        control = c.ground_samples(broken,self.centers)
        self.assertGreaterEqual(control['misses'],3)
        print('GROUND CONTROL '+json.dumps(control))

    def test_link_flags_and_restored_oneway_control(self):
        raw = collision_body(one(self.index.parts,w.MAP))
        _,_,_,segments,_ = c.roads._reader(raw)
        count = lambda ss: sum(bool(s[5] & 0x40) for s in ss[12328:12364])
        self.assertEqual(count(segments),0)
        broken = [tuple((*s[:5],s[5] | 0x40,*s[6:])) if i >= 12328 else s
                  for i,s in enumerate(segments)]
        self.assertEqual(count(broken),36)
        with self.assertRaises(AssertionError):
            self.assertEqual(count(broken),0)
        print('ONEWAY CONTROL old=36 corrected=0 restored=36 rejected')

    def test_route_gates_old_output_fails_and_other_edges_survive(self):
        old = g.World(self.old_index,self.old_stream)
        for pack_id,aid,edge in ((192,12,10),):
            before,after = old.packs[pack_id],self.world.packs[pack_id]
            original,current = before.articles[aid],after.articles[aid]
            offset = 16+struct.unpack_from('<H',original,2)[0]
            barrier = original[offset+32*edge:offset+32*(edge+1)]
            def count(article):
                n = struct.unpack_from('<H',article,4)[0]
                p = 16+struct.unpack_from('<H',article,2)[0]
                return sum(article[p+32*i:p+32*(i+1)] == barrier for i in range(n))
            self.assertEqual((count(original),count(current)),(1,0))
            with self.assertRaises(AssertionError):
                self.assertEqual(count(original),0)
            self.assertEqual(before.instances,after.instances)
            for other in before.articles:
                if other != aid:
                    self.assertEqual(before.articles[other],after.articles[other])
            n = struct.unpack_from('<H',original,4)[0]
            self.assertEqual(struct.unpack_from('<H',current,4)[0],n-1)
            self.assertEqual(current[16:16+32*(n-1)],
                             original[16:offset+32*edge]+original[offset+32*(edge+1):offset+32*n])
            self.assertEqual(current[16+32*(n-1):],original[16+32*n:])
            print(f'GATE CONTROL {pack_id}/{aid}/{edge} old=1 corrected=0; other edges/tails retained')

    def test_height_fitted_arc_rail_opening_has_failing_control(self):
        before, after = self.base_world.packs[134], self.world.packs[134]
        a,b = c.mean(self.high[1]),c.mean(self.high[0])
        def hits(pack):
            article = pack.articles[10]
            translation = struct.unpack_from('<3f',pack.instances,10*64+48)
            result = []
            for i in range(struct.unpack_from('<H',article,4)[0]):
                start = 16+32*i
                p,q = (c.sub(struct.unpack_from('<3f',article,start+offset),translation) for offset in (0,16))
                vertices = (p,(q[0],p[1],q[2]),q,(p[0],q[1],p[2]))
                if any(c.sweep_prism(tuple(vertices[j] for j in tri),a,b)
                       for tri in ((0,1,2),(0,2,3))):
                    result.append(i)
            return result
        self.assertEqual(hits(before),[8])
        self.assertEqual(hits(after),[])
        self.assertEqual(before.instances,after.instances)
        for i in before.articles:
            if i not in (10,11,26,27,28,29):
                self.assertEqual(before.articles[i],after.articles[i])
        original,current = before.articles[10],after.articles[10]
        count = struct.unpack_from('<H',original,4)[0]
        for i in range(count):
            if i not in (0,1,2,3,4,5,6,7,8,9):
                self.assertIn(original[16+32*i:16+32*(i+1)],current)
        self.assertEqual(original[16+32*count:],
                         current[16+32*struct.unpack_from('<H',current,4)[0]:])
        print('TOP RAIL CONTROL barrier 134/10/8=1 -> 0; west leg clipped, bridge floors retained')

    def test_crossing_car_corridors_clear_and_only_target_barrier_edges_change(self):
        for directory, lane, removed, nearest in (
                (self.edge1_directory, 4., (1,), (134,10,10,1)),
                (self.barrier_directory, 0., (1,2), (134,10,10,2))):
            with self.subTest(lane=lane):
                before, before_stream, _ = load_index(directory/'TRACKS','L5RA')
                old, width = crossing_barrier_clearance(before, before_stream, lane)
                actual, new_width = crossing_barrier_clearance(self.index, self.stream, lane)
                self.assertGreaterEqual(width/2, abs(lane)+2.)
                self.assertEqual(width, new_width)
                self.assertEqual(old[1], nearest)
                self.assertLess(old[0], .21)
                with self.assertRaises(AssertionError):
                    self.assertGreaterEqual(old[0], 2.)
                print(f'CROSSING BARRIER CLEARANCE lane={lane:g} m old={old[0]:.6f} FAIL -> '
                      f'new={actual[0]:.6f}; N=2 m, floor width >= {width:.6f} m; '
                      f'nearest {old[1]} -> {actual[1]}', flush=True)
                self.assertGreaterEqual(actual[0], 2.)
                self.assert_barrier_delta(before, before_stream, removed)

    def assert_barrier_delta(self, before, before_stream, removed):
        self.assertEqual(one(before.parts,w.MAP).encode(), one(self.index.parts,w.MAP).encode())
        old_packs = {g.Pack(collision_body(r)).key: collision_body(r)
                     for section in before.sections for r in c.chunks(read_section(before_stream,section))
                     if r.kind == w.PACK}
        new_packs = {g.Pack(collision_body(r)).key: collision_body(r)
                     for section in self.index.sections for r in c.chunks(read_section(self.stream,section))
                     if r.kind == w.PACK}
        self.assertEqual(old_packs.keys(), new_packs.keys())
        for key in old_packs:
            if key != 134:
                self.assertEqual(old_packs[key], new_packs[key], key)
        original, current = g.Pack(old_packs[134]), g.Pack(new_packs[134])
        self.assertEqual(original.instances, current.instances)
        self.assertEqual(original.articles.keys(), current.articles.keys())
        for aid in original.articles:
            if aid != 10:
                self.assertEqual(original.articles[aid], current.articles[aid], aid)
        a, b = original.articles[10], current.articles[10]
        n, m = (struct.unpack_from('<H',v,4)[0] for v in (a,b))
        self.assertEqual(m, n-len(removed))
        self.assertEqual(a[:4]+a[8:16], b[:4]+b[8:16])
        self.assertEqual(b[16:16+32*m], b''.join(a[16+32*i:16+32*(i+1)]
                                              for i in range(n) if i not in removed))
        self.assertEqual(a[16+32*n:], b[16+32*m:])
        print(f'CROSSING DELTA road map identical; {len(old_packs)-1} other packs identical; '
              f'pack 134 instances and other articles/edges/tail identical; removed={removed}')

    def test_each_degree_two_node_has_one_road(self):
        self._assert_single_road_nodes(connectors=False)

    def test_each_connector_node_has_one_road(self):
        self._assert_single_road_nodes(connectors=True)

    def _assert_single_road_nodes(self, *, connectors):
        raw = collision_body(one(self.index.parts, w.MAP))
        _, _, nodes, segments, _ = c.roads._reader(raw)
        failures, checked = [], 0
        for i, node in enumerate(nodes):
            adjacent = [segments[j] for j in node[7:7+node[5]]]
            selected = any(s[5] & 1 for s in adjacent) if connectors else len(adjacent) == 2
            if selected:
                checked += 1
                road_ids = {s[3] for s in adjacent if not s[5] & 1}
                if len(road_ids) != 1:
                    failures.append((i, sorted(road_ids)))
        print(f'ROAD INVARIANT connectors={connectors} checked={checked} violations={failures}')
        self.assertEqual(failures, [])

    def test_bidirectional_graph_and_missing_bottom_connector(self):
        raw = collision_body(one(self.index.parts,w.MAP))
        _,_,nodes,segments,_ = c.roads._reader(raw)
        for start,end in ((8739,1534),(1534,8739)):
            self.assertTrue(c.reachable(nodes,segments,start=start,end=end))
            self.assertFalse(c.reachable(nodes,segments,(12363,12364,12365),start=start,end=end))
        self.assertLess(c.math.dist(nodes[-1][:3],c.mean(self.low[-1])),.001)
        print('GRAPH CONTROL with connector=2/2 directions; without=0/2')

    def test_archive_delta_textures_scenery_and_byte_limits(self):
        self.assertEqual(self.proof['textures'],15)
        self.assertEqual(self.proof['pack_id'],360)
        self.assertEqual(set(self.proof['rows']),{220,326})
        self.assertLess(max(self.proof['rows'].values()),w.POOL_BYTES)
        actual = w.vis.read(w.vis.payload_of(self.index))
        before = w.vis.read(w.vis.payload_of(self.base))
        original = next(r for r in before.rows if r.number == 326)
        row = next(r for r in actual.rows if r.number == 326)
        print(f'PANORAMA 283 row326: control={original.entries.count(283)} '
              f'actual={row.entries.count(283)} entries={len(original.entries)}->{len(row.entries)}')
        self.assertNotIn(283,original.entries)
        self.assertEqual(row.entries.count(283),1)
        self.assertEqual(row.entries,tuple(sorted((*original.entries,283))))
        self.assertEqual(len(row.entries),22)
        self.assertEqual(row.cap,22)
        self.assertEqual(row.header[:15],original.header[:15])
        self.assertEqual(row.spare,original.spare)
        self.assertEqual([r.encode() for r in actual.rows if r.number != 326],
                         [r.encode() for r in before.rows if r.number != 326])
        self.assertEqual(self.proof['rows'],{326:51125052,220:55217976})
        for i in (24,25):
            self.assertEqual(list(self.world.packs[134].faces(i)),
                             list(self.base_world.packs[134].faces(i)))
        self.assertEqual([r['instance'] for r in self.proof['scenery']['bottom']],[154,156,392,404])
        # A change to an unrelated original node must fail even when the road
        # itself still passes all geometric and connectivity checks.
        idx = copy.copy(self.index)
        idx.parts = list(idx.parts)
        for j,part in enumerate(idx.parts):
            if part.kind == w.MAP:
                body = bytearray(collision_body(part))
                tags = c.collision_tags(body,c.roads.RNGP)
                p = tags[c.roads.NODES][3]
                struct.pack_into('<f',body,p,struct.unpack_from('<f',body,p)[0]+1.)
                pad = -(part.offset+8)%16
                idx.parts[j] = Chunk(part.kind,part.payload[:pad]+body,part.offset)
        with self.assertRaisesRegex(FormatError,'old graph node'):
            c.check_delta(idx,self.stream,self.base,self.base_stream)
        print('ARCHIVE CONTROL unrelated-node mutation rejected=1/1')

    def test_r1_overhang_is_absent_and_every_other_row_unchanged(self):
        """Overhang key count: unchanged 1 FAIL -> rebuilt 0 PASS."""
        def shadow(index, stream):
            return w.scene_data(next(r for r in c.inventory(index, stream)[366]
                                     if r.kind == w.SCENE and w.scene_data(r).number == 326))

        before = shadow(self.r1_index, self.r1_stream)
        after = shadow(self.index, self.stream)
        def r1_rows(scene):
            return [p for p in range(0, len(scene.instances), 96)
                    if c.u32(scene.models, struct.unpack_from('<h', scene.instances, p+84)[0]*72+24)
                    == 0x534ae112]

        broken, actual = r1_rows(before), r1_rows(after)
        print(f'R1 OVERHANG key=534ae112 unchanged={len(broken)} rebuilt={len(actual)}; '
              f'scene326 rows={len(before.instances)//96}->{len(after.instances)//96}', flush=True)
        self.assertEqual(len(broken), 1)
        with self.assertRaises(AssertionError):
            self.assertEqual(len(broken), 0)
        self.assertEqual(len(actual), 0)
        self.assertEqual((len(before.instances)//96, len(after.instances)//96), (429, 428))
        self.assertEqual(after.instances, before.instances[:broken[0]]+before.instances[broken[0]+96:])
        self.assertEqual((after.header, after.models, after.precull),
                         (before.header, before.models, before.precull))
        self.assertEqual([(e.kind,e.payload) for e in after.extras],
                         [(e.kind,e.payload) for e in before.extras])
        bindings = [e for e in after.extras if e.kind == 0x34106]
        self.assertEqual(sum(len(e.payload)//4 for e in bindings),50)
        overrides = c.one(self.index.parts,0x34108).payload
        for extra in bindings:
            for oid,instance in struct.iter_unpack('<2H',extra.payload):
                self.assertEqual(struct.unpack_from('<2H',overrides,oid*6),(326,instance))
        w._check_scene_tree(after)
        for section, previous in zip(self.index.sections, self.r1_index.sections):
            self.assertEqual(section.number, previous.number)
            current = read_section(self.stream, section)
            original = read_section(self.r1_stream, previous)
            if section.number != 366:
                self.assertEqual(current, original)
            else:
                def unchanged(data):
                    return [(r.kind, r.payload) for r in c.chunks(data) if r.kind and
                            not (r.kind == w.SCENE and w.scene_data(r).number == 326)]
                self.assertEqual(unchanged(current), unchanged(original))
        self.assertEqual([(p.kind, p.payload) for p in self.index.parts if p.kind != 0x34110],
                         [(p.kind, p.payload) for p in self.r1_index.parts if p.kind != 0x34110])

    def test_old_road_leg_side_triangles_are_zero(self):
        """Old-road triangles, render + collision: main 598 FAIL -> rebuilt 0 PASS."""
        # Frozen main geometry, independently decoded from the serialized
        # curve edge and old far rail. A millimetre excludes float32 edge
        # roundoff, far below the collision lattice's 7.8125 mm quantum.
        cut = ((-2590.031532849,6732.487249546),(-2583.021891537,6740.885449959),
               (-2575.797895510,6749.180468069),(-2568.310470794,6757.352947761),
               (-2560.559020483,6765.329003915),(-2552.595331693,6773.006227827),
               (-2544.455222470,6780.346024424),(-2536.243826220,6787.305200830),
               (-2537.939634079,6789.472863209))
        def distance(p,a,b):
            dx,dz=b[0]-a[0],b[1]-a[1]
            return ((p[0]-a[0])*dz-(p[1]-a[1])*dx)/c.math.hypot(dx,dz)
        def clip(poly,a,b):
            out=[]
            for p,q in zip(poly,poly[1:]+poly[:1]):
                dp,dq=-distance(p,a,b)-.001,-distance(q,a,b)-.001
                if dp>=0: out.append(p)
                if (dp<0)!=(dq<0):
                    out.append(tuple(x+(y-x)*dp/(dp-dq) for x,y in zip(p,q)))
            return out
        def on_leg(tri):
            below=clip([(v[0],v[2]) for v in tri],cut[-2],cut[-1])
            for a,b in zip(cut[:-2],cut[1:-1]):
                poly=clip(below,a,b)
                area=abs(sum(p[0]*q[1]-p[1]*q[0] for p,q in zip(poly,poly[1:]+poly[:1])))/2
                if area>1e-6:return True
            return False
        def count(index,stream):
            roots=c.inventory(index,stream)
            scene=w.scene_data(next(r for r in roots[366] if r.kind==w.SCENE and w.scene_data(r).number==366))
            solids={c.solid_key(s):s for s in c.solids(roots[366])}
            shadow=w.scene_data(next(r for r in roots[366] if r.kind==w.SCENE and w.scene_data(r).number==326))
            tris=[]
            for placed,ids in ((scene,(2,4,10,12)),(shadow,(159,171))):
                for i in ids:
                    if placed.number == 326 and index is self.index:
                        i -= 1  # R1 precedes both original road selectors.
                    row=placed.instances[96*i:96*(i+1)]
                    mi=struct.unpack_from('<h',row,84)[0]
                    key=c.u32(placed.models,72*mi+24)
                    tris.extend(tuple(c.physics(v,row) for v in t) for t in c.mesh(solids[key]))
            world=g.World(index,stream)
            tris.extend(f.vertices for i in range(24,30) for f in world.packs[134].faces(i))
            return sum(on_leg(tri) for tri in tris)
        before,stream,_=load_index(self.main_directory/'TRACKS','L5RA')
        broken=count(before,stream)
        actual=count(self.index,self.stream)
        self.assertEqual(broken,598)
        with self.assertRaises(AssertionError):self.assertEqual(broken,0)
        self.assertEqual(actual,0)
        reflected,reflected_stream,_=load_index(self.reflection_directory/'TRACKS','L5RA')
        self.assertEqual(count(reflected,reflected_stream),0)
        print(f'LEFT LEG TRIANGLES main={broken} rebuilt={actual}; reflection filter 0 -> 0')

    def test_pond_copy_covers_both_black_cores(self):
        """Frozen camera: old left/right 0/4200 FAIL -> new 4200/4200 PASS."""
        import numpy as np
        camera = np.array([[-.642746, -.832555, .00299515, 1214.12],
                           [.150598, -.110220, 1.68004, 148.782],
                           [.786569, -.607641, -.110372, 2797.07],
                           [.786529, -.607611, -.110367, 2797.43]])

        def triangles(index, stream):
            roots = c.inventory(index, stream)[366]
            solid = next(s for s in c.solids(roots) if c.solid_key(s) == 0xd760e0b2)
            pond = np.array(c.mesh(solid)[27:], dtype=np.float64)
            self.assertEqual(pond.shape, (125, 3, 3))
            self.assertEqual(hashlib.sha256(pond.astype('<f4').tobytes()).hexdigest(),
                             '94a1785bed62937b225780f07c74eb4a8e27f30fd0ea9830b0ea92ac6c5c7d62')
            scene = w.scene_data(next(r for r in roots if r.kind == w.SCENE and
                                      w.scene_data(r).number == 366))
            result = []
            for p in range(0, len(scene.instances), 96):
                row = scene.instances[p:p+96]
                model = struct.unpack_from('<h', row, 84)[0]*72
                if c.u32(scene.models, model+24) != 0xd760e0b2:
                    continue
                basis = np.array(struct.unpack_from('<9f', row, 44)).reshape(3, 3)
                translation = np.array(struct.unpack_from('<3f', row, 32))
                # The frozen WVP includes the original +8192 render-X shift.
                result.extend(pond @ basis + translation - (8192., 0., 0.))
            return np.array(result)

        def covered(tris, box):
            x0, y0, x1, y1 = box
            xx, yy = np.meshgrid(np.arange(x0, x1)+.5, np.arange(y0, y1)+.5)
            points = np.column_stack((xx.ravel()/960-1, 1-yy.ravel()/540))
            clip = np.concatenate((tris, np.ones((*tris.shape[:-1], 1))), axis=-1) @ camera.T
            hit = np.zeros(len(points), dtype=bool)
            for a, b, d in clip:
                if max(a[3], b[3], d[3]) <= 0:
                    continue
                e, f = b-a, d-a
                ax, bx = e[0]-points[:, 0]*e[3], f[0]-points[:, 0]*f[3]
                ay, by = e[1]-points[:, 1]*e[3], f[1]-points[:, 1]*f[3]
                rx, ry = points[:, 0]*a[3]-a[0], points[:, 1]*a[3]-a[1]
                det = ax*by-ay*bx
                ok = abs(det) > 1e-12
                u = np.divide(rx*by-ry*bx, det, out=np.zeros_like(det), where=ok)
                v = np.divide(ax*ry-ay*rx, det, out=np.zeros_like(det), where=ok)
                z, q = a[2]+u*e[2]+v*f[2], a[3]+u*e[3]+v*f[3]
                hit |= ok & (u >= -1e-7) & (v >= -1e-7) & (u+v <= 1+1e-7) & (q > 0) & (z >= 0) & (z <= q)
            return int(hit.sum())

        old, old_stream, _ = load_index(self.reflection_directory/'TRACKS', 'L5RA')
        boxes = ((640, 554, 780, 584), (1760, 585, 1900, 615))
        broken = [covered(triangles(old, old_stream), box) for box in boxes]
        actual = [covered(triangles(self.index, self.stream), box) for box in boxes]
        print(f'POND CORE COVERAGE old={broken} rebuilt={actual} required=[4200, 4200]', flush=True)
        self.assertEqual(broken, [0, 0])
        with self.assertRaises(AssertionError):
            self.assertEqual(broken, [4200, 4200])
        self.assertEqual(actual, [4200, 4200])

    def test_reflection_instances_are_zero_and_other_instances_unchanged(self):
        """Reflection instances: original 6 FAIL -> rebuilt 0 PASS."""
        from collections import Counter

        def inventory(index, stream):
            others, reflections = Counter(), []
            crossing = set(next(r.entries for r in w.vis.read(w.vis.payload_of(index)).rows
                                if r.number == 326))
            for section in index.sections:
                roots = list(c.chunks(read_section(stream, section)))
                names = {c.solid_key(s): c.aligned_payload(one(c.children(s), 0x134011))[160:]
                         .split(b'\0', 1)[0].upper() for s in c.solids(roots)}
                for root in roots:
                    if root.kind != w.SCENE:
                        continue
                    scene = w.scene_data(root)
                    w._check_scene_tree(scene)
                    for p in range(0, len(scene.instances), 96):
                        row = scene.instances[p:p+96]
                        m = struct.unpack_from('<h', row, 84)[0]*72
                        model = scene.models[m:m+72]
                        key = c.u32(model, 24)
                        if section.number in crossing and (b'REFLECTION' in names.get(key, b'') or
                                                           key == 0x75513475):
                            reflections.append((section.number, scene.number, key))
                        else:
                            # Exact row and model bytes: both count and content, across every scene.
                            others[(section.number, scene.number, model, row)] += 1
            return others, reflections

        before, before_stream, _ = load_index(self.reflection_directory/'TRACKS', 'L5RA')
        original, broken = inventory(before, before_stream)
        actual, remaining = inventory(self.index, self.stream)
        self.assertEqual(set(broken), {(366,326,0x45c3ba94), (366,326,0x45c3ba95),
                                      (366,326,0xfe3b1185), (366,326,0x40d01a71),
                                      (366,326,0x75513475), (193,193,0x0fb991f7)})
        self.assertEqual(len(broken), 6)
        with self.assertRaises(AssertionError):
            self.assertEqual(len(broken), 0)
        self.assertEqual(len(remaining), 0)
        roots = c.inventory(before, before_stream)[366]
        source = w.scene_data(next(r for r in roots if r.kind == w.SCENE and
                                   w.scene_data(r).number == 366))
        pond = bytearray(source.instances[22*96:23*96])
        for offset in (0, 16, 32):
            struct.pack_into('<f', pond, offset, struct.unpack_from('<f', pond, offset)[0]-512.)
        model = source.models[22*72:23*72]
        original[(366, 366, model, bytes(pond))] += 1
        r1 = [item for item in original if item[:2] == (366, 326) and c.u32(item[2], 24) == 0x534ae112]
        self.assertEqual(len(r1), 1)
        self.assertEqual(original.pop(r1[0]), 1)
        self.assertEqual(actual, original)
        current = w.scene_data(next(r for r in c.inventory(self.index, self.stream)[366]
                                    if r.kind == w.SCENE and w.scene_data(r).number == 366))
        self.assertEqual(current.instances, source.instances+pond)
        self.assertEqual(len(current.instances)//96, 58)
        self.assertEqual(len(current.tree), 1296)
        # Every solid, collision pack and other non-scene provider stays exact.
        for section in self.index.sections:
            previous = next(s for s in before.sections if s.number == section.number)
            providers = lambda data: [(r.kind, r.payload) for r in c.chunks(data)
                                      if r.kind and r.kind != w.SCENE]
            self.assertEqual(providers(read_section(self.stream, section)),
                             providers(read_section(before_stream, previous)))
        graph = collision_body(one(self.index.parts, w.MAP))
        self.assertEqual(graph, collision_body(one(before.parts, w.MAP)))
        counts = c.roads._reader(graph)[0]
        self.assertEqual((counts['nodes'], counts['segments']), (9023, 12366))
        print(f'REFLECTION INSTANCES original={len(broken)} rebuilt={len(remaining)} '
              f'other_instances={sum(actual.values())} graph=9023/12366 exact')

    def test_unlabelled_treeline_has_decoded_negative_vertex_height_map(self):
        """50 twin vertices flip vertically; the bounding box alone is insufficient."""
        index, stream, _ = load_index(self.reflection_directory/'TRACKS', 'L5RA')
        roots = c.inventory(index, stream)[366]
        scene = w.scene_data(next(r for r in roots if r.kind == w.SCENE and
                                 w.scene_data(r).number == 326))
        solids = {c.solid_key(s): s for s in c.solids(roots)}
        vertices = {}
        for p in range(0, len(scene.instances), 96):
            row = scene.instances[p:p+96]
            m = struct.unpack_from('<h', row, 84)[0]
            key = c.u32(scene.models, m*72+24)
            if key in (0x75513475, 0x753f1bf4):
                vertices[key] = set(c.physics(v, row) for tri in c.mesh(solids[key]) for v in tri)
        # Authored reflection stretches Y slightly as well as reversing it.
        slope, offset = -1.0492791772871626, 422.34907095029337
        matches = [(a,b) for a in vertices[0x75513475] for b in vertices[0x753f1bf4]
                   if abs(a[0]-b[0]) < .0001 and abs(a[2]-b[2]) < .0001 and
                   abs(a[1]-(slope*b[1]+offset)) < .0001]
        self.assertEqual(len(matches), 50)
        self.assertGreater(max(b[1] for a,b in matches)-min(b[1] for a,b in matches), 66.)
        self.assertLess(slope, 0.)
        self.assertLess(max(abs(a[1]-(slope*b[1]+offset)) for a,b in matches), .00003)
        print('TREELINE VERTEX FLIP matched=50 max_error<0.00003m; twin=753f1bf4')

    def test_removed_fence_physics_cannot_survive_its_render_instance(self):
        original_inventory = c.inventory
        roots = original_inventory(self.index,self.stream)
        before = original_inventory(self.base,self.base_stream)
        old_physics = one(before[220],0x34027)
        new_physics = one(roots[220],0x34027)
        self.assertEqual(c.struct.unpack_from('<H',c.aligned_payload(old_physics),10)[0],69)
        self.assertEqual(c.struct.unpack_from('<H',c.aligned_payload(new_physics),10)[0],68)
        roots[220] = [old_physics if r.kind==0x34027 else r for r in roots[220]]
        def read(index,stream):
            return roots if index is self.index else original_inventory(index,stream)
        with patch.object(c,'inventory',side_effect=read), \
             self.assertRaisesRegex(FormatError,'physics spawn removal differs'):
            c.check_delta(self.index,self.stream,self.base,self.base_stream)
        print('PHYSICS CONTROL retained fence-122 collision spawn rejected=1/1 (69 -> 68)')


if __name__ == '__main__':
    result = unittest.main(exit=False)
    if not result.result.wasSuccessful():
        raise SystemExit(1)
    if not ASSETS:
        raise SystemExit(3)
