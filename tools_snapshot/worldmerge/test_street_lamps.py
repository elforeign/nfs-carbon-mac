"""Bulb markers: old coast build 0/120, opt-in 120/120; Cb LODs 0/3 -> 3/3.

Independent source geometry and all referenced LODs are required. Missing marker,
omitted C LOD, omitted pivot, wrong type/hash/anchor and stale eligibility cache
are rejected. Synthetic tests run without assets; private census exits 3 when
the original archives are absent. Default output remains covered by test_c1_world.
Highway road sample: 0 contributing point records in the marker-only control,
2 in range and facing the road after importing 88 distinct X360 records.
Highway car query at both captured poses: shipped empty tree (0, 0), native
tree (1, 1). The empty tree fails the positive-count check at both poses.
"""
import math
from pathlib import Path
import struct
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import street_lamps as lamps
import c1_world as world
from formats import Chunk, FormatError, chunks
from convert import aligned_payload


def solid(key, position=16):
    header = bytearray(168)
    struct.pack_into('<I', header, 16, key)
    struct.pack_into('<3f', header, 112, 100., 200., 300.)
    out = world.convert.Builder(position+8)
    out.add(lamps.HEADER, header, 16)
    out.add(0x134012, bytes(8))
    return Chunk(lamps.SOLID, bytes(out.data), position)


def fixture():
    out = world.convert.Builder(8)
    out.add(0, b'')
    for key in (11, 12, 13, 99):
        out.data += solid(key, out.position).encode()
    return Chunk(lamps.SOLIDS, bytes(out.data)).encode()


class Markers(unittest.TestCase):
    def setUp(self):
        self.specs = {k: (100.5, 198., 309.) for k in (11, 12, 13)}
        self.raw = fixture()

    def test_suffix_roundtrip_and_untouched_solid(self):
        added = lamps.transform(self.raw, self.specs)
        self.assertEqual(len(added)-len(self.raw), 3*128)
        self.assertEqual(lamps.transform(added, self.specs, remove=True), self.raw)
        before = chunks(chunks(self.raw)[0].payload, 8)[-1]
        after = chunks(chunks(added)[0].payload, 8)[-1]
        self.assertEqual(before.encode(), after.encode())
        self.assertEqual(before.offset % 128, after.offset % 128)

    def test_old_missing_and_c_lod_controls_fail(self):
        with self.assertRaisesRegex(FormatError, 'missing marker'):
            lamps.transform(self.raw, self.specs, remove=True)
        added = lamps.transform(self.raw, {k:v for k,v in self.specs.items() if k != 12})
        with self.assertRaisesRegex(FormatError, 'missing marker'):
            lamps.transform(added, self.specs, remove=True)

    def test_hash_type_pivot_and_anchor_controls_fail(self):
        good = lamps.transform(self.raw, self.specs)
        expected = lamps.marker(11, self.specs[11])
        for offset, value in ((0, 44), (4, 5), (64, .5), (68, 200.), (72, 999.)):
            bad = bytearray(good)
            start = good.index(expected)
            struct.pack_into('<I' if offset < 16 else '<f', bad, start+offset, value)
            with self.subTest(offset=offset), self.assertRaisesRegex(FormatError, 'identity/geometry'):
                lamps.transform(bytes(bad), self.specs, remove=True)

    def test_reader_rejects_a_broken_marker_serializer(self):
        serializer = lamps.marker
        def wrong(key, xyz):
            row = bytearray(serializer(key,xyz))
            struct.pack_into('<I',row,4,5)
            return bytes(row)
        with patch.object(lamps,'marker',side_effect=wrong):
            bad = lamps.transform(self.raw,self.specs)
            with self.assertRaisesRegex(FormatError,'identity/geometry'):
                lamps.transform(bad,self.specs,remove=True)

    def test_no_option_transform_is_exact_and_source_guard_retains_type_limit(self):
        self.assertEqual(lamps.transform(self.raw, {}), self.raw)
        import sidecars
        p = Chunk(lamps.MARKERS, lamps.marker(11, self.specs[11]), 8)
        with self.assertRaisesRegex(FormatError, 'source marker type'):
            sidecars.convert_sidecar(p, 8, world.convert.Stats())

    def test_native_schema_translation_and_bulb_not_arm(self):
        row = lamps.marker(11, self.specs[11])
        self.assertEqual(struct.unpack_from('<4I', row), (11,6,0,0))
        matrix = struct.unpack_from('<16f', row, 16)
        self.assertEqual(tuple(matrix[i] for i in (0,5,10,15)), (1,1,1,1))
        self.assertEqual(tuple(matrix[12+i]-(100.,200.,300.)[i] for i in range(3)), (.5,-2.,9.))
        self.assertIn('obj_lightglobe_', lamps.BULBS)

    def test_coast_coverage_zero_to_120_and_missing_c_control(self):
        import visibility
        model = bytearray(72)
        struct.pack_into('<4I', model, 24, 11,11,12,13)
        header = bytearray(68)
        struct.pack_into('<I', header, 12, 1833)
        scene = world.convert.Builder(8)
        scene.add(0x34101, header, 16)
        scene.add(0x34102, model)
        scene.add(0x34103, bytes(96*120), 16)
        raw_scene = Chunk(world.SCENE, bytes(scene.data)).encode()
        index = SimpleNamespace(sections=[SimpleNamespace(number=1),SimpleNamespace(number=1833)])
        table = SimpleNamespace(rows=[SimpleNamespace(number=1833,entries=(1833,1))])
        for enabled in (False, True):
            raw = lamps.transform(self.raw, self.specs) if enabled else self.raw
            def read(stream, section):
                return raw if section.number == 1 else raw_scene
            with patch.object(lamps, 'load_index', return_value=(index,None,None)), \
                    patch.object(lamps, 'read_section', side_effect=read), \
                    patch.object(visibility, 'payload_of', return_value=None), \
                    patch.object(visibility, 'read', return_value=table):
                count = lamps.census('unused', self.specs, validate=False)['coast']
                self.assertEqual((count['imported'],count['expected_imported']), (120 if enabled else 0,120))
                if enabled:
                    self.assertEqual(lamps.census('unused', self.specs)['lod_solids'], 3)
                else:
                    with self.assertRaisesRegex(FormatError, 'missing or incorrect marker'):
                        lamps.census('unused', self.specs)

    def test_source_hash_cache_bits_clear_and_restore_exactly(self):
        models = bytearray(144)
        models[:24] = b'fixture-lamp'.ljust(24,b'\0')
        struct.pack_into('<4I', models, 24, 11,11,12,13)
        struct.pack_into('<I', models, 60, 0x925f2389)
        struct.pack_into('<I', models, 132, 0xabcdef03)
        original = Chunk(world.SCENE, Chunk(world.MODELS,bytes(models)).encode()).encode()
        caches = {bytes(models[:40]):0x925f2389}
        changed = lamps.transform(original, {}, caches=caches)
        row = chunks(chunks(changed)[0].payload)[0].payload
        self.assertEqual(struct.unpack_from('<I',row,60)[0],0x925f2388)
        self.assertEqual(row[72:],models[72:])
        self.assertEqual(lamps.transform(changed,{},remove=True,caches=caches),original)
        with self.assertRaisesRegex(FormatError,'eligibility cache'):
            lamps.transform(original,{},remove=True,caches=caches)

    def test_native_hash_collision_is_rejected_before_stripping(self):
        native = chunks(self.raw)[0]
        with patch.object(lamps,'oracle',return_value=(self.specs,120)), \
                patch.object(lamps,'load_index',return_value=(None,None,None)), \
                patch.object(lamps.inventory,'stream_tops',return_value=(native,)):
            with self.assertRaisesRegex(FormatError,'aliases native solid'):
                lamps.check('unused','source','native','stripped')


HIGHWAY_POSES = ((-1600.667725, -2987.735352, 221.434174),
                 (-1637.125854, -2961.203613, 223.287460))


def native_light_tree(pack):
    parts = {part.kind: part for part in chunks(pack.payload, pack.offset + 8)}
    return aligned_payload(parts[0x135002]), aligned_payload(parts[0x135003])


def tree_node(tree, index):
    pos = 16 + 48 * index
    center = struct.unpack_from('<3f', tree, pos)
    parent, count = struct.unpack_from('<Hh', tree, pos + 12)
    extent = struct.unpack_from('<3f', tree, pos + 16)
    refs = struct.unpack_from(f'<{abs(count)}h', tree, pos + 28)
    return center, extent, parent, count, refs


def car_point_lights(tree, records, pose):
    # Carbon 0069FB80/0069FAD0 returns the first matching leaf. 00746230's
    # pack loop then submits its references to 007381A0 for range and kind.
    def leaf(index):
        center, extent, _, count, refs = tree_node(tree, index)
        if not all(abs(v - c) < e for v, c, e in zip(pose, center, extent)):
            return None
        if count <= 0:
            return refs
        for child in refs:
            found = leaf(child)
            if found is not None:
                return found
        return None

    selected = []
    for index in leaf(0) or ():
        pos = 96 * index
        x, y, z, radius = struct.unpack_from('<4f', records, pos + 16)
        if (records[pos + 4] == 2 and records[pos + 7] == 1 and
                math.dist(pose, (x, y, z)) < radius):
            selected.append(index)
            if len(selected) == 10:
                break
    return selected


def check_highway_car_query(pack):
    tree, records = native_light_tree(pack)
    # The shipped tree chunk has a 16-byte header with count 1 and one zero node.
    empty = bytes.fromhex('00000000000000000100000000000000') + bytes(48)
    baseline = tuple(len(car_point_lights(empty, records, pose)) for pose in HIGHWAY_POSES)
    counts = tuple(len(car_point_lights(tree, records, pose)) for pose in HIGHWAY_POSES)
    assert baseline == (0, 0)
    assert min(counts) >= 1, f'Highway car query: empty {baseline}, generated {counts}'
    print(f'HIGHWAY car point lights {baseline}->{counts}')
    return tree, records


def check_highway_tree(tree, records):
    # L5RA archive 1045, el_LHT_SecretTunnelA_1b_P1_541. Decode stock bytes
    # with the same reader and confirm its node slots drive a car lookup.
    index, stream, _ = world.load_index(world.DEFAULT_CARBON, 'L5RA')
    section = next(s for s in index.sections if s.number == 1045)
    stock_pack = next(p for p in chunks(world.read_section(stream, section))
                      if p.kind == lamps.inventory.LIGHT_PACK)
    stock, stock_records = native_light_tree(stock_pack)
    assert struct.unpack_from('<4H', stock, 4) == (29, 8, 37, 3)
    assert len(stock) == 16 + 48 * 37
    assert tree_node(stock, 0)[2:] == (0xffff, 10, tuple(range(1, 11)))
    center, extent, parent, count, refs = tree_node(stock, 1)
    assert (extent, parent, count, refs[0]) == ((44., 44., 44.), 0, -9, 0)
    assert center == struct.unpack_from('<3f', stock_records, 16)
    assert 0 in car_point_lights(stock, stock_records, center)

    assert struct.unpack_from('<4H', tree, 4) == (88, 10, 98, 3)
    assert len(tree) == 16 + 48 * 98
    nodes = [tree_node(tree, i) for i in range(98)]
    assert nodes[0][2:] == (0xffff, 9, tuple(range(1, 10)))
    assert sum(n[3] > 0 for n in nodes) == 10
    children, anchors = [], []
    lights = [struct.unpack_from('<4f', records, off + 16) for off in range(0, len(records), 96)]
    for i, (center, extent, _, count, refs) in enumerate(nodes):
        assert 1 <= abs(count) <= 10 and all(e > 0 for e in extent)
        if count > 0:
            for child in refs:
                assert i < child < len(nodes) and nodes[child][2] == i
                child_center, child_extent = nodes[child][:2]
                assert all(abs(c - v) + r <= e
                           for c, v, r, e in zip(center, child_center, child_extent, extent))
            children.extend(refs)
        else:
            anchor = refs[0]
            assert len(set(refs)) == len(refs) and all(0 <= j < len(lights) for j in refs)
            assert (*center, extent[0]) == lights[anchor] and extent == (extent[0],) * 3
            anchors.append(anchor)
            for j, (*xyz, radius) in enumerate(lights):
                # Minimum distance from the emitter to this leaf's box.
                closest = [min(c + e, max(c - e, p)) for c, e, p in zip(center, extent, xyz)]
                assert math.dist(xyz, closest) >= radius or j in refs
    assert sorted(children) == list(range(1, 98))
    assert sorted(anchors) == list(range(88))


def private_highway():
    from c3_crossing import COAST_SHIFT
    import ground
    import x360_auxlights

    archive = x360_auxlights.DEFAULT_X360 / 'STREAML2RA_PERM.BUN'
    if not archive.is_file() or not all((world.DEFAULT_CARBON / name).is_file()
                                         for name in ('L5RA.BUN', 'STREAML5RA.BUN')):
        print('SKIP: X360 or Carbon highway tunnel source unavailable')
        return
    shift = COAST_SHIFT
    source = lamps.coast_tunnel_lights(shift)
    assert len(source) == 88
    assert not lamps.coast_tunnel_lights(world.DEFAULT_SHIFT)
    base = 20
    pack, = chunks(lamps.tunnel_pack(base, source, shift), base)
    tree, records = check_highway_car_query(pack)
    check_highway_tree(tree, records)
    decoded = lamps.inventory.light_pack(pack)
    assert (decoded['section'], decoded['tree_records'], decoded['light_records']) == (1375, 98, 88)
    assert all(row['kind_code'] == 2 and row['enabled'] == 1 and
               row['name'].startswith('x360_tunnel_') for row in decoded['lights'])
    expected = set()
    for name, lights in x360_auxlights.extract_contexts(archive):
        if 'highway4aux' not in name.lower():
            continue
        for raw in lights:
            x, y, z, radius, red, green, blue, intensity = struct.unpack('<8f', raw)
            xyzr = struct.unpack('<4f', struct.pack('<4f', x-1728., y-5056., z, radius))
            expected.add((xyzr, bytes(round(c*255) for c in (red, green, blue)), intensity))
    actual = {(struct.unpack_from('<4f', records, p+16), records[p+12:p+15],
               struct.unpack_from('<f', records, p+44)[0]) for p in range(0, len(records), 96)}
    assert len(actual) == len(source) and actual == expected

    # Reconstruct the road point and upward normal at the captured highway
    # pose from the original collision triangles. The shift is horizontal only.
    x, y = -1402.683228, -3146.612793
    hit = ground.World.load(world.DEFAULT_MW, 'L2RA').find_face_below(-y-5056., x+1728., 212.541199)
    assert hit and abs(hit.height-211.82516)<.001
    a, b, c = hit.face.vertices
    normal = ground.cross(tuple(v-u for u,v in zip(a,b)), tuple(v-u for u,v in zip(a,c)))
    up = math.copysign(math.sqrt(ground.dot(normal, normal)), normal[1])
    normal = (normal[2]/up, -normal[0]/up, normal[1]/up)

    def contributions(lights):
        count, red = 0, 0.
        for (lx, ly, lz, radius), rgb, intensity in lights:
            delta = (lx-x, ly-y, lz-hit.height)
            d2 = ground.dot(delta, delta)
            if not 0 < d2 < radius*radius:
                continue
            incidence = max(0, ground.dot(delta, normal)/math.sqrt(d2))
            energy = rgb[0]/255 * incidence * (3*intensity/(2*d2+intensity))
            count += energy > 0
            red += energy
        return count, red

    previous = contributions(())
    assert previous == (0, 0.)
    count, red = contributions(actual)
    assert count == 2 and red > .20
    print(f'HIGHWAY road positive records {previous[0]}->{count}, red irradiance {previous[1]:.4f}->{red:.4f}')


def private_geometry():
    if not all((world.DEFAULT_MW/name).is_file() for name in ('L2RA.BUN','STREAML2RA.BUN')):
        print('SKIP: private street-lamp geometry unavailable')
        return 3
    expected, placements = lamps.oracle(world.DEFAULT_MW)
    actual = lamps.specifications(world.DEFAULT_MW)
    assert actual == expected and placements == 2558 and len(expected) == 69
    # Cb B/C/Z hashes come independently from the original solid/model inventory.
    cb = (0x13288c4a, 0x132918ab, 0x1335b562)
    assert all(k in expected for k in cb)
    meshes = lamps.source_solids(world.DEFAULT_MW, set(cb))
    for key, (header, draws) in meshes.items():
        bulb = [v for name,v in draws if 'bright' in name.lower()]
        assert bulb
        xyz = struct.unpack_from('<3f', lamps.marker(key, actual[key]), 64)
        for a in range(3):
            centre = (min(float(p[a]) for v in bulb for p in v)+max(float(p[a]) for v in bulb for p in v))/2
            pivot = struct.unpack_from('<f', header, 112+4*a)[0]
            assert abs(xyz[a]-pivot-centre) < .0002
    print('STREET LAMPS source placements=2558 LODs=69 Cb=3/3; broken missing-C=2/3 rejected')
    private_highway()
    return 0


if __name__ == '__main__':
    result = unittest.TextTestRunner().run(unittest.defaultTestLoader.loadTestsFromTestCase(Markers))
    sys.exit(private_geometry() if result.wasSuccessful() else 1)
