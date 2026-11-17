"""Offline proof and failure controls; synthetic fixtures contain no game bytes.

Original indexes: 720/962 records round-trip; merged: 963, duplicate and past-end
mutants rejected. Geometry/texture/scenery mutants are checked independently.
Measured merge proof: 13 tests pass; 44 deliberately broken cases fail; 765 spatial
components match within 0.0009765625 m, below the fixed 0.002 m limit.
Region addition: 6 tests pass; target present = 1 valid record, target removed = 0
records and rejected. Seven new broken controls fail, including missing textures,
scenery, visibility, grid coverage/stride and reflect vertex stride.
Asset checks use only in-memory buffers. Missing private assets exits 3.
Collision: 51 cells, families [355,0,0,259], 11 packs; nine broken layouts fail.
The checkpoint's transposed 95-cell selection is rejected by native slot bounds.
GlossyWindow: diffuse-capable records old/new 0/1 -> 1/1; retained effect-6
control rejected. All 3,201 glossy draws in 260 source lists validate as effect
25, retaining position, UV0, colour and normal in the native declaration order.
"""
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import formats as f
import convert as c
import merge as m
import validate as v
import audit


def record(number=101, offset=0, size=16):
    raw = bytearray(92)
    struct.pack_into('<h', raw, 8, number)
    struct.pack_into('<II', raw, 20, offset, size)
    return f.Section(bytes(raw))


def synthetic_index(*rows):
    return f.Chunk(0x34110, b''.join(r.raw for r in rows)).encode()


CONTAINERS = {0xb3300000, 0xb3310000, 0xb3320000, 0x80134000, 0x80134001,
              0x80134010, 0x80134100, 0x80034100, 0x80034150}


def walk(data, base=0):
    for item in f.chunks(data, base):
        yield item
        if item.kind in CONTAINERS:
            yield from walk(item.payload, item.offset + 8)


def field_offset(data, kind, field=0, align=16):
    item = next(x for x in walk(data) if x.kind == kind)
    return item.offset + 8 + (-(item.offset + 8) % align) + field


def changed(data, offset, code, value):
    raw = bytearray(data)
    struct.pack_into(code, raw, offset, value)
    return bytes(raw)


def glossy_mesh(effect=5):
    """One source material and triangle; no private model bytes."""
    head, row = bytearray(48), bytearray(104)
    struct.pack_into('<I', head, 16, 1)
    struct.pack_into('<I', head, 24, 1)
    struct.pack_into('<I', head, 44, 3)
    struct.pack_into('<I', row, 48, effect)
    row[24:28] = bytes((1, 3, 1, 2))
    struct.pack_into('<III', row, 60, 3, 1, 0)
    struct.pack_into('<I', row, 92, 3)
    out = c.Builder(8)
    out.add(0x134900, head, 16)
    out.add(0x134b02, row, 16)
    out.add(0x134b03, struct.pack('<4H', 0, 1, 2, 0), 16)
    vertices = b''.join(struct.pack('<6fI2f', x, 0, 0, 0, 0, 1,
                                   0xff203040, .25, .75) for x in range(3))
    if effect == 1:
        vertices = b''.join(struct.pack('<6fI8f', x, 0, 0, 0, 0, 1, 0x7f203040, .25, .75, 4, 5, 1, 0, 0, 1) for x in range(3))
    out.add(0x134b01, vertices, 128)
    out.add(0x134c02, b'glossy\0')
    return f.Chunk(0x80134100, bytes(out.data))


def effect_parameters(path):
    """Read top-level FX parameter typedefs through the PE resource tree."""
    from test_tail import image_reader
    read = image_reader(path)
    data = path.read_bytes()
    pe = f.u32(data, 60)
    root = 0x400000 + f.u32(data, pe + 24 + 112)
    word = lambda address: f.u32(read(address, 4))
    def entries(address):
        named, ids = struct.unpack('<HH', read(address + 12, 4))
        return struct.iter_unpack('<II', read(address + 16, (named + ids) * 8))
    rcdata = next(root + (off & 0x7fffffff) for key, off in entries(root) if key == 10)
    result = {}
    for key, off in entries(rcdata):
        if not key & 0x80000000:
            continue
        address = root + (key & 0x7fffffff)
        length, = struct.unpack('<H', read(address, 2))
        name = read(address + 2, length * 2).decode('utf-16le')
        leaf = root + (off & 0x7fffffff)
        if off & 0x80000000:
            leaf = root + (word(leaf + 20) & 0x7fffffff)
        blob = read(0x400000 + word(leaf), word(leaf + 4))
        if blob[:4] != struct.pack('<I', 0xfeff0901):
            continue
        body, cursor = blob[8:], f.u32(blob, 4)
        count = f.u32(body, cursor)
        cursor += 16
        names = set()
        for _ in range(count):
            typedef, _, _, annotations = struct.unpack_from('<4I', body, cursor)
            start = f.u32(body, typedef + 8)
            names.add(body[start + 4:start + 4 + f.u32(body, start)].rstrip(b'\0').decode())
            cursor += 16 + annotations * 8
        result[name] = names
    return result


class SyntheticTests(unittest.TestCase):
    def test_facade_source_identity(self):
        def identity():
            raw = c.convert_mesh(glossy_mesh(), 0, c.Stats())
            return f.u32(raw, field_offset(raw, 0x134b02, 48))
        self.assertEqual(identity(), 0x00050019)
        with patch.dict(c.EFFECTS, {5: (36, 25, 36)}):
            with self.assertRaises(AssertionError):
                self.assertEqual(identity(), 0x00050019)
        # Loader selects the low ushort; the source tag does not change the
        # native declaration or the full-word buffer grouping rule.
        self.assertEqual(identity() & 0xffff, 25)
        print('FACADE IDENTITY: source 5 tag retained; old 5->25 rejected')

    def test_tree_source_identity(self):
        # Source trees keep native effect 0 for the loader and declaration;
        # the high ushort selects the day-weighted tree contract.
        def identity():
            raw = c.convert_mesh(glossy_mesh(6), 0, c.Stats())
            return f.u32(raw, field_offset(raw, 0x134b02, 48))
        self.assertEqual(identity(), 0x00060000)
        self.assertEqual(identity() & 0xffff, 0)
        with patch.dict(c.EFFECTS, {6: (36, 0, 36)}):
            with self.assertRaises(AssertionError):
                self.assertEqual(identity(), 0x00060000)
        print('TREE IDENTITY: source 6 tag retained; old untagged 6->0 rejected')

    def test_reflective_source_identity_and_texture_indices(self):
        source = glossy_mesh(1)
        raw = c.convert_mesh(source, 0, c.Stats())
        row = field_offset(raw, 0x134b02)
        self.assertEqual(f.u32(raw, row + 48), 0x00010001)
        self.assertEqual(raw[row + 24:row + 28], bytes((1, 3, 1, 2)))
        self.assertEqual(f.u32(raw, row + 48) & 0xffff, 1)
        with patch.dict(c.EFFECTS, {1: (60, 1, 52)}):
            old = c.convert_mesh(source, 0, c.Stats())
        with self.assertRaises(AssertionError):
            self.assertEqual(f.u32(old, row + 48), 0x00010001)
        for slot in (25, 27):
            broken = changed(raw, row + slot, '<B', 0)
            with self.assertRaises(AssertionError):
                self.assertEqual(broken[row + 24:row + 28], bytes((1, 3, 1, 2)))
        print('REFLECT IDENTITY: 00010001, source normal/specular indices 3/2; old tag/dropped bindings rejected')

    def test_roundtrip_unknown_chunks_and_fields(self):
        row = bytearray(record().raw)
        row[60:92] = bytes(range(32))
        data = f.Chunk(0x12345678, b'opaque').encode() + synthetic_index(f.Section(bytes(row)))
        idx = f.TrackIndex(data)
        self.assertEqual(idx.encode(), data)
        self.assertEqual(idx.validate(16), 1)

    def test_record_and_envelope_failure_controls(self):
        cases = [lambda: f.Section(bytes(91)),
                 lambda: f.chunks(bytes(7)),
                 lambda: f.chunks(struct.pack('<II', 1, 100)),
                 lambda: f.TrackIndex(f.Chunk(0x34110, bytes(93)).encode()),
                 lambda: f.TrackIndex(synthetic_index(record(), record())).validate(32),
                 lambda: f.TrackIndex(synthetic_index(record(offset=33))).validate(32),
                 lambda: f.TrackIndex(synthetic_index(record(), record(102, 8))).validate(32)]
        for case in cases:
            with self.subTest(case=case), self.assertRaises(f.FormatError):
                case()

    def test_table_growth_retains_later_alignment(self):
        raw = synthetic_index(record()) + f.Chunk(0x11223344, b'other').encode()
        idx = f.TrackIndex(raw)
        idx.sections.append(record(102, 16))
        out = f.TrackIndex(idx.encode())
        before = next(x for x in idx.parts if x.kind == 0x11223344)
        after = next(x for x in out.parts if x.kind == 0x11223344)
        self.assertEqual((after.offset - before.offset) % 128, 0)
        self.assertEqual(out.validate(32), 2)

    def test_boundary_conversion_and_broken_bounds(self):
        raw = bytearray(36 + 4 * 8)
        struct.pack_into('<hBB6f', raw, 8, 1904, 4, 0, 1, 2, 3, 4, 2, 3)
        struct.pack_into('<8f', raw, 36, 1, 2, 3, 2, 3, 4, 1, 4)
        old = f.parse_boundaries(bytes(raw), False)[0]
        new = old.translate(227, 20000)
        self.assertEqual(new.bounds, (20001, 2, 20003, 4))
        self.assertEqual(new.vertices, [(20001, 2), (20003, 2), (20003, 4), (20001, 4)])
        self.assertEqual(f.parse_boundaries(new.raw, True)[0], new)
        for mutation in (changed(new.raw, 24, '<f', 30000), changed(new.raw, 32, '<f', float('nan')),
                         changed(new.raw, 10, '<B', 127)):
            with self.assertRaises(f.FormatError):
                f.parse_boundaries(mutation, True)

    def test_vertex_layout_classifications(self):
        # Position, normal, packed colour, UV0, unused UV1, tangent XYZW.
        src = struct.pack('<6fI8f', 1, 2, 3, 0, 0, 1, 0xff203040, .25, .75, 4, 5, 6, 7, 8, 9)
        self.assertEqual(len(src), 60)
        normal_map = c.convert_vertices(src, 3, 1)
        self.assertEqual(len(normal_map), 52)
        self.assertEqual(struct.unpack_from('<4f', normal_map, 36), (6, 7, 8, 9))
        glossy = c.convert_vertices(src[:36], 5, 1)
        self.assertEqual(struct.unpack('<3f2fI3f', glossy),
                         (1, 2, 3, .25, .75, 0xff203040, 0, 0, 1))
        with self.assertRaises(f.FormatError):
            c.convert_vertices(src, 0, 1)
        with self.assertRaises(f.FormatError):
            c.convert_vertices(src[:36], 77, 1)

    def test_grid_descriptor_and_pointer_failure_controls(self):
        raw = bytearray(128)
        struct.pack_into('<4I', raw, 16, 0x43477264, 0x2802, 1, 48)
        struct.pack_into('<4f', raw, 64, -10, 0, -20, 1)
        struct.pack_into('<f', raw, 80, 64)
        struct.pack_into('<2I', raw, 88, 2, 3)
        def index(data):
            return f.TrackIndex(synthetic_index() + f.Chunk(0x3b800, data).encode())
        self.assertEqual(audit.decode_grid(index(raw))['origin_physics_xyz'], (-10, 0, -20))
        for p, code, value in [(28, '<I', 99999), (24, '<I', 0), (20, '<I', 0),
                               (88, '<I', 0), (80, '<f', float('nan'))]:
            with self.subTest(field=p), self.assertRaises(f.FormatError):
                audit.decode_grid(index(changed(raw, p, code, value)))

    def test_output_guards_and_atomic_synthetic_write(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source_dir = root / 'source'
            source_dir.mkdir()
            source = source_dir / 'stream'
            source.write_bytes(b'x' * 32)
            output_root = root / 'out'
            output_root.mkdir()
            with patch.object(m, 'OUTPUT_ROOT', output_root):
                bad_paths = [root / 'source' / 'bad', output_root, output_root / '..' / 'escape']
                (output_root / 'link').symlink_to(source_dir, target_is_directory=True)
                bad_paths.append(output_root / 'link' / 'bad')
                for path in bad_paths:
                    with self.subTest(path=path), self.assertRaises(f.FormatError):
                        m.check_output(path, (source_dir,))
                data = synthetic_index(record(size=40))
                report = {'append_padding': 0, 'merged_stream_bytes': 40}
                out = output_root / 'bundle'
                m.write_outputs(out, data, b'y' * 8, source, report, (source_dir,))
                self.assertEqual((out / 'TRACKS' / 'L5RA.BUN').read_bytes(), data)
                self.assertEqual((out / 'TRACKS' / 'STREAML5RA.BUN').read_bytes(), b'x' * 32 + b'y' * 8)
                self.assertEqual(source.read_bytes(), b'x' * 32)
                with self.assertRaises(f.FormatError):
                    m.write_outputs(out, data, b'y' * 8, source, report, (source_dir,))
                with patch.object(m.os, 'rename', side_effect=OSError('injected publication failure')):
                    with self.assertRaises(OSError):
                        m.write_outputs(output_root / 'failed', data, b'y' * 8, source, report, (source_dir,))
                self.assertFalse((output_root / 'failed').exists())
                self.assertFalse(list(output_root.glob('.worldmerge-stage-*')))


ASSETS = all(p.is_file() for p in (m.DEFAULT_MW / 'L2RA.BUN', m.DEFAULT_MW / 'STREAML2RA.BUN',
                                  m.DEFAULT_CARBON / 'L5RA.BUN', m.DEFAULT_CARBON / 'STREAML5RA.BUN',
                                  m.DEFAULT_CARBON / 'L5RB.BUN', m.DEFAULT_CARBON / 'STREAML5RB.BUN'))


@unittest.skipUnless(ASSETS, 'private track archives absent')
class ArchiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index, cls.section, cls.stream, cls.report = m.prepare()
        cls.number = cls.report['target_number']
        ix, stream, _ = m.load_index(m.DEFAULT_MW, 'L2RA')
        cls.source = m.read_section(stream, next(s for s in ix.sections if s.number == 1904))

    def test_glossy_record_requires_diffuse_parameter(self):
        from test_tail import declaration, image_reader
        image = m.DEFAULT_CARBON.parent / 'NFSC.exe'
        if not image.is_file():
            self.skipTest('private image absent')
        parameters = effect_parameters(image)
        read = image_reader(image)
        def diffuse_record():
            output = c.convert_mesh(glossy_mesh(), 0, c.Stats())
            target = f.u32(output, field_offset(output, 0x134b02, 48))
            resource_address = f.u32(read(0xa64008 + (target & 0xffff) * 144 + 136, 4))
            resource = read(resource_address, 64).split(b'\0', 1)[0].decode()
            self.assertIn('DIFFUSEMAP_TEXTURE', parameters[resource])
            return target
        self.assertEqual(diffuse_record(), 0x00050019)
        with patch.dict(c.EFFECTS, {5: (36, 6, 24)}):
            with self.assertRaisesRegex(AssertionError, 'DIFFUSEMAP_TEXTURE'):
                diffuse_record()
        self.assertIn('ENVIROMAP_TEXTURE', parameters['IDI_GLASSREFLECTSHADER_FX'])
        self.assertEqual(declaration(read, 0xa64008, 25, 0xa650ec, 0xa65180,
                                     0xa65110, 0xa65168),
                         (((0, 0, 2, 0, 0, 0), (0, 12, 1, 0, 5, 0),
                           (0, 20, 4, 0, 10, 0), (0, 24, 2, 0, 3, 0)), 36))
        print('GLOSSY DIFFUSE CONTROL: old/new 0/1 -> 1/1; effect 6 rejected')

    def test_all_glossy_draws_validate_and_retain_vertex_fields(self):
        from test_tail import mesh_data
        index, stream, _ = m.load_index(m.DEFAULT_MW, 'L2RA')
        lists = draws = reflect_draws = 0
        for section in index.sections:
            for root in f.chunks(m.read_section(stream, section)):
                if root.kind != 0x80134000:
                    continue
                output = c.convert_list(root, 0, c.Stats())
                with patch.dict(c.EFFECTS, {1: (60, 1, 52), 5: (36, 25, 36)}):
                    baseline = bytearray(c.convert_list(root, 0, c.Stats()))
                for child in walk(baseline):
                    if child.kind == 0x134b02:
                        start = child.offset + 8 + (-(child.offset + 8) % 16)
                        end = child.offset + 8 + len(child.payload)
                        for row in range(start, end, 144):
                            effect = f.u32(baseline, row + 48)
                            if effect in (1, 25):
                                struct.pack_into('<I', baseline, row + 48, {1: 0x00010001, 25: 0x00050019}[effect])
                self.assertEqual(output, bytes(baseline), 'only classified effect identity may change')
                v.validate_resources(output, section.number)
                affected = False
                before = [x for x in walk(root.payload, root.offset + 8) if x.kind == 0x80134100]
                after = [x for x in walk(output) if x.kind == 0x80134100]
                self.assertEqual(len(before), len(after))
                for old, new in zip(before, after):
                    old_groups, _ = mesh_data(old, False)
                    new_groups, _ = mesh_data(new, True)
                    old_reflect = [(rows, vb) for (effect, rows), vb in old_groups if effect == 1]
                    new_reflect = [(rows, vb) for (effect, rows), vb in new_groups if effect == 0x00010001]
                    self.assertEqual(len(old_reflect), len(new_reflect))
                    for (old_rows, old_vb), (new_rows, new_vb) in zip(old_reflect, new_reflect):
                        self.assertEqual([r[24:48] for r in old_rows], [r[24:48] for r in new_rows])
                        self.assertEqual(new_vb, b''.join(old_vb[p:p + 36] + old_vb[p + 44:p + 60]
                                                        for p in range(0, len(old_vb), 60)))
                        reflect_draws += len(old_rows)
                    old_glossy = [(rows, vb) for (effect, rows), vb in old_groups if effect == 5]
                    affected |= bool(old_glossy)
                    new_glossy = [(rows, vb) for (effect, rows), vb in new_groups if effect == 0x00050019]
                    self.assertEqual(len(old_glossy), len(new_glossy))
                    for (old_rows, old_vb), (new_rows, new_vb) in zip(old_glossy, new_glossy):
                        self.assertEqual(len(old_rows), len(new_rows))
                        self.assertEqual([r[24:48] for r in old_rows], [r[24:48] for r in new_rows])
                        expected = b''.join(old_vb[p:p + 12] + old_vb[p + 28:p + 36] +
                                            old_vb[p + 24:p + 28] + old_vb[p + 12:p + 24]
                                            for p in range(0, len(old_vb), 36))
                        self.assertEqual(new_vb, expected)
                        draws += len(old_rows)
                lists += affected
        self.assertEqual((lists, draws), (260, 3201))
        self.assertEqual(reflect_draws, 9054)
        print(f'REFLECT ARCHIVES: {reflect_draws}/9054 source normal/specular bindings and vertex fields retained')
        print(f'GLOSSY ARCHIVES: {lists}/260 lists validated; {draws}/3201 draws retain all fields')

    def test_roundtrips_and_corrupt_indexes(self):
        self.assertEqual(self.report['records'], {'source': 720, 'target': 962, 'merged': 963})
        self.assertEqual(self.report['original_roundtrips'], {'source': True, 'target': True})
        self.assertEqual(len(m.negative_controls(self.index, self.report['merged_stream_bytes'])), 2)
        self.assertEqual(self.report['target_number'], 227)
        self.assertEqual(len(list(f.TrackIndex(self.index).boundaries())), 643)

    def test_geometry_and_all_spatial_components(self):
        counts, _ = v.validate_section(self.section, self.number)
        self.assertEqual(counts, {'textures': 1, 'vertices': 2667, 'draws': 34, 'triangles': 1516,
                                  'solids': 19, 'instances': 73, 'nodes': 18})
        result = v.validate_translation(self.source, self.section, 20000)
        self.assertEqual(result['spatial_components_checked'], 765)
        self.assertLessEqual(result['maximum_translation_error_m'], .002)

    def test_geometry_texture_and_scenery_failure_controls(self):
        cases = [
            ('TPK version', 0x33310001, 0, '<I', 5, 1),
            ('TPK pixel bounds', 0x33310004, 20, '<I', 0xffffffff, 1),
            ('TPK mip count', 0x33310004, 50, '<B', 20, 1),
            ('solid version', 0x134011, 12, '<I', 19, 16),
            ('solid bounds', 0x134011, 32, '<f', float('nan'), 16),
            ('mesh material count', 0x134900, 16, '<I', 1000, 16),
            ('mesh effect', 0x134b02, 48, '<I', 99, 16),
            ('mesh vertex count', 0x134b02, 64, '<I', 10000, 16),
            ('mesh index count', 0x134b02, 124, '<I', 10000, 16),
            ('index value', 0x134b03, 0, '<H', 65535, 16),
            ('vertex bound', 0x134b01, 0, '<f', 999999, 16),
            ('scenery number', 0x34101, 12, '<I', 1904, 16),
            ('instance model index', 0x34103, 84, '<h', 30000, 16),
            ('tree children', 0x34105, 28, '<h', 30000, 16),
        ]
        for name, kind, field, code, value, align in cases:
            with self.subTest(name=name):
                bad = changed(self.section, field_offset(self.section, kind, field, align), code, value)
                with self.assertRaises(f.FormatError):
                    v.validate_section(bad, self.number)
        scene = next(x for x in f.chunks(self.section) if x.kind == 0x80034100)
        with self.assertRaises(f.FormatError):
            v.validate_section(self.section + scene.encode(), self.number)
        scene = next(x for x in f.chunks(self.source) if x.kind == 0x80034100)
        with self.assertRaises(f.FormatError):
            c.convert_section(self.source + scene.encode(), self.number)

    def test_missing_or_double_world_translation_fails(self):
        p = field_offset(self.section, 0x34103, 32)
        original = struct.unpack_from('<f', self.section, p)[0]
        for delta in (-20000, 20000):
            bad = changed(self.section, p, '<f', original + delta)
            with self.assertRaises(f.FormatError):
                v.validate_translation(self.source, bad, 20000)
        p = field_offset(self.section, 0x34103, 44)
        with self.assertRaises(f.FormatError):
            v.validate_translation(self.source, changed(self.section, p, '<f', 99), 20000)

    def test_pixel_chain_is_byte_exact(self):
        def pixels(data):
            p = next(c for c in walk(data) if c.kind == 0x33320002)
            return v.payload(p, 128)
        self.assertEqual(pixels(self.source), pixels(self.section))
        self.assertEqual(len(pixels(self.section)), 87360)

    @unittest.skipUnless((audit.DEFAULT_ORACLE / 'L5RA.BUN').is_file(), 'private oracle absent')
    def test_oracle_inventory_and_old_bridge_geometry(self):
        result = audit.compare()
        self.assertTrue(result['comparison']['same_section_number_sets'])
        self.assertEqual(result['comparison']['same_streamer_positions'], 720)
        self.assertEqual(result['comparison']['max_streamer_coordinate_delta'], 0)
        self.assertEqual(result['oracle']['inventory']['tpk_versions'], {8: 477})
        self.assertEqual(result['oracle']['inventory']['instance_strides'], {96: 77783})
        self.assertEqual(result['oracle']['grid']['cell_m'], 64)
        self.assertEqual(result['oracle']['grid']['descriptor_bytes'], 40)
        self.assertEqual(result['oracle']['inventory']['pursuit_headers_section_zero'], 366)
        self.assertEqual(result['target']['inventory']['pursuit_headers_section_zero'], 0)
        self.assertNotIn('00034109', result['oracle']['index_chunks'])
        self.assertIn('00034109', result['source']['index_chunks'])
        self.assertIn('00034109', result['target']['index_chunks'])
        candidates = result['source']['inventory']['bridge_candidates']
        old_bridge = [r for r in candidates if r['name'].startswith('XO_OldBridgeBase')]
        self.assertEqual(len(old_bridge), 1)
        self.assertEqual(old_bridge[0]['sections'], ['A74'])
        self.assertEqual(old_bridge[0]['scenery_section_numbers'], [134])
        self.assertEqual(tuple(round(x, 2) for x in old_bridge[0]['render_center_xyz']), (-991.94, 2627.12, 199.87))


@unittest.skipUnless(ASSETS and (m.DEFAULT_CARBON / 'L5RB.BUN').is_file(), 'private region assets absent')
class RegionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import region
        cls.r = region
        cls.index, cls.stream, cls.proof = region.prepare()

    def test_smallest_closed_full_detail_section(self):
        self.assertEqual(self.proof['number'], 1503)
        self.assertEqual(self.proof['section'], 'O03')
        self.assertEqual(self.proof['shift'], [0, 0, 0])
        self.assertFalse(self.proof['renumbered'])
        self.assertEqual([r['section'] for r in self.proof['smaller_candidates_rejected']], ['T28', 'C10'])
        self.assertEqual(self.proof['validation']['counts']['solids'], 21)
        self.assertEqual(self.proof['validation']['counts']['textures'], 31)
        self.assertFalse(any(self.proof['validation']['dependencies'].values()))
        self.assertEqual(self.proof['spatial']['maximum_translation_error_m'], 0)
        self.assertEqual(self.proof['spatial']['spatial_components_checked'], 168)

    def test_region_roundtrip_and_removed_target_failure(self):
        self.assertEqual(self.r.check_region(self.index, self.stream, 1503)['records'], 1)
        index = f.TrackIndex(self.index)
        index.sections.clear()
        self.assertEqual(f.TrackIndex(index.encode()).validate(len(self.stream)), 0)
        with self.assertRaisesRegex(f.FormatError, 'target section missing'):
            self.r.check_region(index.encode(), self.stream, 1503)
        print('REGION TARGET CONTROL: valid=1 record; removed=0 records rejected')

    def test_texture_packs_have_distinct_bound_hashes(self):
        # Native loading binds a pack header to the first queued data block with
        # its hash; packs sharing one hash leave every texture unresolved.
        hashes = []
        for c in f.chunks(self.stream):
            if c.kind != 0xb3300000:
                continue
            parts = f.chunks(c.payload, c.offset + 8)
            header = next(x for x in parts if x.kind == 0xb3310000)
            data = next(x for x in parts if x.kind == 0xb3320000)
            info = next(x for x in f.chunks(header.payload, header.offset + 8) if x.kind == 0x33310001).payload
            dh = next(x for x in f.chunks(data.payload, data.offset + 8) if x.kind == 0x33320001).payload
            self.assertEqual(f.u32(info, 0x60), f.u32(dh, 12))
            hashes.append(f.u32(info, 0x60))
        self.assertEqual(len(hashes), 15)
        self.assertEqual(len(set(hashes)), len(hashes))

    def test_texture_data_has_native_padding_chunk(self):
        # The pack loader binds pixels from the chunk after the one following
        # the data header: header, padding chunk, 128-aligned pixel chunk.
        packs = 0
        for c in f.chunks(self.stream):
            if c.kind != 0xb3300000:
                continue
            data = next(x for x in f.chunks(c.payload, c.offset + 8) if x.kind == 0xb3320000)
            kids = f.chunks(data.payload, data.offset + 8)
            self.assertEqual([k.kind for k in kids], [0x33320001, 0, 0x33320002])
            self.assertEqual(kids[2].offset % 128, 0)
            packs += 1
        self.assertEqual(packs, 15)

    def test_texture_records_walk_at_native_stride(self):
        # FUN_0055E120 steps 0x59 + name-length bytes per record (no extra
        # padding): the walk must end exactly at the chunk and meet every key.
        for c in f.chunks(self.stream):
            if c.kind != 0xb3300000:
                continue
            header = next(x for x in f.chunks(c.payload, c.offset + 8) if x.kind == 0xb3310000)
            parts = {x.kind: x.payload for x in f.chunks(header.payload, header.offset + 8)}
            keys = [f.u32(parts[0x33310002], k) for k in range(0, len(parts[0x33310002]), 8)]
            rows, p, seen = parts[0x33310004], 0, []
            for _ in keys:
                seen.append(f.u32(rows, p + 12))
                p += 0x59 + rows[p + 0x58]
            self.assertEqual(p, len(rows))
            self.assertEqual(seen, keys)

    def test_missing_texture_and_scenery_fail(self):
        roots = f.chunks(self.stream)
        # Replacing chunks by equal-sized padding keeps later absolute alignment.
        for kind in (0xb3300000, 0x80034100):
            broken = b''.join(f.Chunk(0, bytes(len(c.payload))).encode() if c.kind == kind else c.encode()
                              for c in roots)
            with self.subTest(kind=kind), self.assertRaises(f.FormatError):
                self.r.check_region(self.index, broken, 1503)

    def test_visibility_removal_and_camera_geometry(self):
        index = f.TrackIndex(self.index)
        p = next(i for i, c in enumerate(index.parts) if c.kind == 0x80034150)
        top = index.parts[p]
        parts = [c for c in self.r.children(top) if c.kind != 0x34152]
        index.parts[p] = f.Chunk(top.kind, f.encode_chunks(parts))
        with self.assertRaises(f.FormatError):
            self.r.check_region(index.encode(), self.stream, 1503)
        camera = self.proof['camera']
        self.assertGreater(camera['render_eye'][2], camera['geometry_bounds'][1][2])
        self.assertEqual(camera['physics_eye'], [-camera['render_eye'][1], camera['render_eye'][2], camera['render_eye'][0]])
        self.assertEqual(camera['height_source'], 'converted instance geometry bounds Z')

    def test_native_grid_and_source_mip_bytes(self):
        native, _, _ = m.load_index(m.DEFAULT_CARBON, 'L5RB')
        generated = f.TrackIndex(self.index)
        old = bytearray(next(c.payload for c in native.parts if c.kind == 0x3b800))
        new = bytearray(next(c.payload for c in generated.parts if c.kind == 0x3b800))
        p = old.find(struct.pack('<I', 0x43477264)); q = p + f.u32(old, p + 12)
        for offset, size in ((q, 12), (q + 16, 4)):
            new[offset:offset + size] = old[offset:offset + size]
        self.assertEqual(new, old)
        self.assertEqual(audit.decode_grid(generated)['descriptor_bytes'], 40)
        grid_slot = next(i for i, c in enumerate(generated.parts) if c.kind == 0x3b800)
        original_grid = generated.parts[grid_slot]
        for offset, code, value in ((p + 4, '<I', 0x2402), (q, '<f', -1e9)):
            generated.parts[grid_slot] = f.Chunk(0x3b800, changed(original_grid.payload, offset, code, value))
            with self.assertRaises(f.FormatError):
                self.r.check_region(generated.encode(), self.stream, 1503)
        generated.parts[grid_slot] = original_grid
        source, stream, _ = m.load_index(m.DEFAULT_MW, 'L2RA')
        self.assertEqual(generated.sections[0].position, next(s.position for s in source.sections if s.number == 1503))
        # Independently compare all selected target mip chains with original
        # fixed v5 rows and their original pixel offsets, before any writer.
        originals = {}
        for number in self.proof['resource_sections']:
            section = next(s for s in source.sections if s.number == number)
            for root in f.chunks(m.read_section(stream, section)):
                if root.kind != 0xb3300000: continue
                hp = self.r.children(self.r.one(self.r.children(root), 0xb3310000))
                dp = self.r.children(self.r.one(self.r.children(root), 0xb3320000))
                pixels = c.aligned_payload(self.r.one(dp, 0x33320002), 128)
                rows = self.r.one(hp, 0x33310004).payload
                for p in range(0, len(rows), 124):
                    key, offset, size = (f.u32(rows, p + k) for k in (36, 48, 56))
                    originals.setdefault(key, pixels[offset:offset + size])
        checked = 0
        for root in f.chunks(self.stream):
            if root.kind != 0xb3300000: continue
            hp = self.r.children(self.r.one(self.r.children(root), 0xb3310000))
            dp = self.r.children(self.r.one(self.r.children(root), 0xb3320000))
            pixels = v.payload(self.r.one(dp, 0x33320002), 128)
            rows = self.r.one(hp, 0x33310004).payload
            p = 0
            while p < len(rows):
                key, offset, size = (f.u32(rows, p + k) for k in (12, 20, 28))
                self.assertEqual(pixels[offset:offset + size], originals[key]); checked += 1
                p += (89 + rows[p + 88] + 3) // 4 * 4
        self.assertEqual(checked, 31)

    def test_reflect_declaration_classification_and_guard(self):
        src = struct.pack('<6fI8f', 1, 2, 3, 0, 0, 1, 0xff203040, .25, .75, 4, 5, 6, 7, 8, 9)
        dest = c.convert_vertices(src, 1, 1)
        self.assertEqual(dest, src[:36] + src[44:60])
        self.assertEqual(v.STRIDES[1], 52)
        with self.assertRaises(f.FormatError):
            c.convert_vertices(src[:52], 1, 1)


@unittest.skipUnless(ASSETS and (m.DEFAULT_CARBON / 'L5RB.BUN').is_file(), 'private region assets absent')
class RegionCollisionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import region
        cls.r = region
        cls.index, cls.stream, cls.proof = region.prepare(collision=True)

    def test_native_rectangle_tile_and_preserved_source_bytes(self):
        r = self.r; proof = self.proof['collision']; index = f.TrackIndex(self.index)
        self.assertEqual((proof['cells'], proof['references'], proof['packs']), (51, 355, 11))
        self.assertEqual(proof['reference_families'], [355, 0, 0, 259])
        self.assertEqual(proof['rectangle'], [1503, 66, 70, 11, 10])
        self.assertEqual(proof['descriptor_extension'], '01000000')
        self.assertEqual(audit.decode_grid(index)['descriptor_bytes'], 40)
        self.assertEqual(audit.decode_grid(index)['origin_physics_xyz'], (-4800, 0, -1664))
        roots = f.chunks(self.stream)
        tile = r.collision_body(r.one(roots, 0x3b802))[16:]
        cells = r.collision_cells(tile, r.collision_tags(tile, 0x41727469)[0x4347636e])
        # Independent native 007F5F60 insertion formula: cl +2 is Z row,
        # +4 X column; countX at +6 is the pointer-array stride.
        slots = []
        for cell in cells:
            cid, section = struct.unpack_from('<HH', cell, 4)
            row, col = divmod(cid, 92)
            self.assertEqual(section, 1503)
            self.assertTrue(0 <= row - 66 < 10 and 0 <= col - 70 < 11)
            slots.append((row - 66) * 11 + col - 70)
        self.assertEqual(len(set(slots)), 51)
        self.assertIn(6604, proof['cell_ids'])  # render 2912,160 lies over this cell
        source, stream, _ = m.load_index(m.DEFAULT_MW, 'L2RA')
        raw = r.collision_body(r.one(source.parts, 0x3b800))
        originals = r.collision_cells(raw, r.collision_tags(raw, 0x43446174)[0x4347636e])
        originals = {struct.unpack_from('<H', c, 4)[0]: c for c in originals}
        inverse = {v: int(k) for k, v in proof['pack_remap'].items()}
        for cell in cells:
            restored = bytearray(cell)
            struct.pack_into('<H', restored, 6, 0)
            for p in range(20, 20 + cell[8] * 4, 4):
                ref = f.u32(cell, p)
                struct.pack_into('<I', restored, p, (inverse.get(ref >> 16, ref >> 16) << 16) | (ref & 0xffff))
            self.assertEqual(restored, originals[struct.unpack_from('<H', cell, 4)[0]])
        copied = {f.u32(r.collision_body(c), 4): r.collision_body(c) for c in roots if c.kind == 0x3b801}
        self.assertEqual(len(copied), 11)
        native, native_stream, _ = m.load_index(m.DEFAULT_CARBON, 'L5RA')
        reserved = {f.u32(r.collision_body(c), 4) for s in native.sections
                    for c in f.chunks(m.read_section(native_stream, s)) if c.kind == 0x3b801}
        self.assertFalse(set(copied) & reserved)
        for key, number in proof['providers'].items():
            section = next(s for s in source.sections if s.number == number)
            original = next(r.collision_body(c) for c in f.chunks(m.read_section(stream, section))
                            if c.kind == 0x3b801 and f.u32(r.collision_body(c), 4) == int(key))
            restored = bytearray(copied[proof['pack_remap'].get(key, int(key))])
            struct.pack_into('<I', restored, 4, int(key))
            self.assertEqual(restored, original)
        self.assertEqual(r.check_region(self.index, self.stream, 1503)['collision']['cells'], 51)

    def test_broken_native_collision_layouts_fail(self):
        r = self.r; roots = f.chunks(self.stream)
        tile = r.one(roots, 0x3b802); body = r.collision_body(tile)[16:]
        tag = r.collision_tags(body, 0x41727469)[0x4347636e]
        # Offsets in the envelope's payload include its alignment and tile header.
        cell = (-(tile.offset + 8) % 16) + 16 + tag[3]
        variants = []
        for kind in (0x3b802, 0x3b801):
            victim = next(c for c in roots if c.kind == kind)
            variants.append(b''.join(f.Chunk(0, bytes(len(c.payload))).encode() if c is victim else c.encode() for c in roots))
        for offset, code, value in ((cell + 6, '<H', 1504), (cell + 14, '<H', 1),
                                     (cell + 20, '<I', 2700 << 16), (cell + 4, '<H', 0)):
            payload = changed(tile.payload, offset, code, value)
            variants.append(b''.join(f.Chunk(c.kind, payload).encode() if c is tile else c.encode() for c in roots))
        for broken in variants:
            with self.assertRaises(f.FormatError): r.check_region(self.index, broken, 1503)
        index = f.TrackIndex(self.index)
        i = next(i for i, c in enumerate(index.parts) if c.kind == 0x3b800)
        top = index.parts[i]; pad = -(top.offset + 8) % 16
        cl = r.collision_tags(r.collision_body(top), 0x43446174)[0x636c0000]
        for offset, code, value in ((pad + cl[0], '<I', 0x636c0001),
                                    (pad + cl[3] + 6, '<I', (11 << 16) | 10),
                                    (pad + cl[3] + 2, '<I', (66 << 16) | 70)):
            index.parts[i] = f.Chunk(top.kind, changed(top.payload, offset, code, value), top.offset)
            with self.assertRaises(f.FormatError): r.check_region(index.encode(), self.stream, 1503)
        print('COLLISION CONTROL: 51 native slots valid; 9 corrupt layouts rejected (including checkpoint transpose)')


if __name__ == '__main__':
    result = unittest.main(exit=False, verbosity=2).result
    if not result.wasSuccessful():
        raise SystemExit(1)
    if not ASSETS:
        raise SystemExit(3)
    print('WORLD MERGE PASS: 720/962 exact round-trips; 963 valid records; corrupt inputs rejected; no asset writes')
