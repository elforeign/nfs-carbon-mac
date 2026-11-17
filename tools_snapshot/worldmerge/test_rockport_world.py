"""Whole-world proof: baseline 3 records/0 zones/0 rows -> 720/373/435.

Valid written pair: 1/1 accepted, 720 payloads independently validated, 2779
cells/390 packs/0 rejects; models 19269/19293, indexed-model textures 3086/3112
(baseline 3080/3112); 56/56 classified, first-texture risk 25 -> 10 (shared 15 -> 0).
Failure controls, CLI --check: missing drivable row 0/1 accepted; offset +2048
0/1; section shift 20000 0/1; without resident textures 0/1, closure 1280/3112
versus 3086/3112 (1806 newly absent keys); shared provider removed 0/1,
3085/3112 versus intact 3086/3112. All five controls mutate/write files;
no proof counters decide acceptance.
Global-table integration: populated pair 0/1 accepted before -> 1/1 after;
705 zones/328 markers/1376 barriers versus native scaffold 0/0/0.
Five populated CLI controls each accept 0/1 versus intact 1/1: marker before
zones, changed zone type, dropped barrier (1375 versus 1376), duplicate marker,
and populated zones with native barriers.
Provider-first rows: 378/435 changed, late V placements 1190 -> 0;
headers/spare/multisets retained. --rows verbatim pins the corresponding pair hashes;
native L5RA index/stream bytes are unchanged. Stream bytes stay identical.
Traffic binding: old preparation 0/11 -> 11/11; exactly 11 u32 words differ
from identity, all type-9 +48; markers/barriers/stream equal. Dropped downtown,
industrial target, mixed 10/11 binding and rekeyed type-11 each accept 0/1
versus intact 1/1. Identity stays accepted 1/1 with 0/11 bound.
Synthetic checks run without assets, then exit 3. No game launches.
"""
from contextlib import redirect_stdout, redirect_stderr
import io
import hashlib
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(HERE))
import rockport_world as w
import districts as d
from formats import Chunk, FormatError, Section, TrackIndex, chunks, encode_chunks
from test_visibility import fixture as visibility_fixture
from test_rockport_track import fixture as collision_fixture
from test_zones import fixture as zone_fixture, index_of

ASSETS = all((root / name).is_file()
             for root, bases in ((w.DEFAULT_MW, ('L2RA',)), (w.DEFAULT_CARBON, ('L5RA', 'L5RB')))
             for base in bases for name in (base + '.BUN', 'STREAM' + base + '.BUN'))
ASSETS = ASSETS and (w.DEFAULT_CARBON.parent / 'GLOBAL/attributes.bin').is_file()


def make_record(number, size=8):
    raw = bytearray(92)
    struct.pack_into('<h', raw, 8, number)
    return w.record(Section(bytes(raw)), 0, size)


def aligned_index(parts):
    builder = w.convert.Builder(0)
    for part in parts:
        if part.kind:
            if part.kind in w.props.GLOBALS:
                import c1_world
                c1_world.append_at_residue(builder,part)
            else:
                builder.pad(16)
                builder.add(part.kind, part.payload)
    return bytes(builder.data)


class SyntheticTests(unittest.TestCase):
    @mock.patch.object(d, 'key_map', return_value={})
    @mock.patch.object(d, 'traffic_patterns', return_value={})
    def test_exact_global_table_forms_and_unchanged_scaffold_rules(self, _patterns, _mapping):
        z = w.zone_tables
        source = index_of(zone_fixture((3, 9, 9)))
        native = TrackIndex(aligned_index([
            Chunk(0x34112, b'opaque scaffold'),
            Chunk(z.ZONES, Chunk(z.POLYGONS, b'').encode()),
            Chunk(0x34110, b''), Chunk(z.BARRIERS, b'')]))
        self.assertEqual(w.check_scaffold(native, native, source),
                         dict(zones=0, markers=0, barriers=0))
        populated = TrackIndex(z.rewrite_index(native.encode(), z.convert(source)))
        self.assertEqual(w.check_scaffold(populated, native, source),
                         dict(zones=3, markers=1, barriers=1, districts_bound='0/2'))
        # Exact source identity rejects structurally valid but foreign records.
        table = z.read(z.select(populated))
        raw = bytearray(table.zones[-1].encode())
        struct.pack_into('<I', raw, 0, 10)
        polygon_data = b''.join(p.encode() for p in table.zones[:-1]) + raw
        changed_zone = Chunk(z.ZONES, Chunk(z.POLYGONS, polygon_data).encode())
        marker = next(c for c in populated.parts if c.kind == z.MARKERS)
        changed_marker = bytearray(marker.payload)
        struct.pack_into('<I', changed_marker, 16, 0x87654321)
        cases = [
            ([c for c in populated.parts if c.kind != z.MARKERS], 'native scaffold payload differs'),
            ([changed_zone if c.kind == z.ZONES else c for c in populated.parts], 'source conversion'),
            ([Chunk(c.kind, bytes(changed_marker)) if c.kind == z.MARKERS else c
              for c in populated.parts], 'source conversion'),
            ([Chunk(c.kind, c.payload[:-24]) if c.kind == z.BARRIERS else c
              for c in populated.parts], 'source conversion'),
            ([Chunk(c.kind, b'foreign scaffold') if c.kind == 0x34112 else c
              for c in populated.parts], 'native scaffold payload differs'),
            ([*populated.parts, Chunk(0x1234, b'')], 'kinds/order differ'),
        ]
        for parts, message in cases:
            with self.subTest(message=message), self.assertRaisesRegex(FormatError, message):
                w.check_scaffold(TrackIndex(aligned_index(parts)), native, source)
        # The marker's absolute alignment still obeys the original header rule.
        parts = [Chunk(c.kind, c.payload, c.offset + 8) if c.kind == z.MARKERS else c
                 for c in populated.parts]
        with self.assertRaisesRegex(FormatError, 'header misaligned'):
            w.check_scaffold(index_of(parts), native, source)

    def test_record_rewrites_only_the_three_documented_words(self):
        raw = bytearray(range(92))
        struct.pack_into('<h', raw, 8, 101)
        changed = w.record(Section(bytes(raw)), 4096, 1024)
        self.assertEqual(changed.raw[:20], raw[:20])
        self.assertEqual(changed.raw[32:], raw[32:])
        self.assertEqual(struct.unpack_from('<III', changed.raw, 20), (4096, 1024, 1024))

    def test_omissions_preserve_extent_and_offsets(self):
        roots = [Chunk(kind, bytes(n)) for kind, n in ((0x80036000, 16), (0x3bc00, 8),
                                                     (0xb3300000, 32), (0x1234, 4))]
        data = encode_chunks(roots)
        for number in (101, 2500):
            output = w.omit(data, number, w.WITHOUT)
            self.assertEqual(len(output), len(data))
            before, after = chunks(data), chunks(output)
            self.assertEqual([c.offset for c in before], [c.offset for c in after])
            self.assertEqual([c.kind for c in after], [0, 0, 0 if number == 2500 else 0xb3300000, 0x1234])

    def test_collision_projection_reads_actual_bodies_and_rejects_missing_pack(self):
        index, stream = collision_fixture()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'stream'
            path.write_bytes(stream)
            checked = w.collision_check(TrackIndex(index), path)
            self.assertEqual((checked['cells'], checked['packs'], checked['rejects']), (2, 1, 0))
            idx = TrackIndex(index)
            out = bytearray(stream)
            pack = next(s for s in idx.sections if s.number == 2600)
            struct.pack_into('<I', out, pack.offset, 0)
            path.write_bytes(out)
            with self.assertRaisesRegex(FormatError, 'unresolved collision pack'):
                w.collision_check(idx, path)

    def test_zone_lookup_and_pool_deduplicate_residents(self):
        source = visibility_fixture()
        source.parts = [Chunk(c.kind, w.visibility.convert(source) if c.kind == w.visibility.CONTAINER
                              else c.payload, c.offset) for c in source.parts]
        source.sections = [make_record(n, size) for n, size in ((141, 30), (2400, 100), (2600, 50), (2500, 999))]
        result = w.zone_at(source, 0, 0)
        self.assertEqual((result['zone'], result['entries_with_record'], result['summed_bytes']), (101, 1, 30))
        table = w.visibility.read(w.visibility.payload_of(source))
        measured = w.pool_rows(source, table)
        self.assertEqual((measured['largest'], measured['median'], measured['rows_over']), (180, 180, 0))
        with self.assertRaisesRegex(FormatError, 'no drivable zone'):
            w.zone_at(source, 10, 10)

    def test_bitmap_boundary_and_missing_assets(self):
        self.assertEqual((w.BITMAP_BYTES * 8, 2600 // 8), (2800, 325))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tracks = root / 'TRACKS'
            tracks.mkdir()
            stream, records = w.convert.Builder(0), []
            for number in (2400, 2500, 2600, 2800):
                stream.pad(2048)
                records.append(w.record(make_record(number), stream.position, 8))
                stream.add(0, b'')
            data = Chunk(0x34110, b''.join(r.raw for r in records)).encode()
            for base in ('L2RA', 'L5RB'):
                (tracks / (base + '.BUN')).write_bytes(data)
                (tracks / ('STREAM' + base + '.BUN')).write_bytes(stream.data)
            with self.assertRaisesRegex(FormatError, 'exceeds requested bitmap'):
                w.check(root, tracks, tracks)
            with redirect_stderr(io.StringIO()) as err:
                rc = w.main(['--out', str(root / 'new'), '--mw-root', str(root / 'absent')])
            self.assertEqual(rc, 3)
            self.assertIn('private assets absent', err.getvalue())
            self.assertFalse((root / 'new').exists())
        with redirect_stderr(io.StringIO()) as err:
            rc = w.main(['--check', '/unused', '--zones'])
        self.assertEqual(rc, 1)
        self.assertIn('--zones requires --out', err.getvalue())


@unittest.skipUnless(ASSETS, 'private track archives absent')
class ArchiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='rockworld-test-')
        cls.addClassCleanup(cls.temp.cleanup)
        cls.root = Path(cls.temp.name)
        cls.output = cls.root / 'full'
        cls.native_hashes = {name: w.track.source_proof(w.DEFAULT_CARBON / name, '')['sha256']
                             for name in ('L5RA.BUN', 'STREAML5RA.BUN', 'L5RB.BUN', 'STREAML5RB.BUN')}
        cls.proof = w.prepare(cls.output)
        cls.tracks = cls.output / 'TRACKS'
        cls.index_bytes = (cls.tracks / 'L2RA.BUN').read_bytes()
        cls.index = TrackIndex(cls.index_bytes)

    def rejected_cli(self, expected):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()) as err:
            rc = w.main(['--check', str(self.output)])
        self.assertEqual(rc, 1, err.getvalue())
        self.assertIn(expected, err.getvalue())
        return err.getvalue()

    def test_default_pair_retains_scaffold_and_bytes(self):
        self.assertEqual(self.proof['validation']['zones'], dict(zones=0, markers=0, barriers=0))
        self.assertFalse(self.proof['zones'])
        for section in self.proof['sections']:
            self.assertNotIn('00034027',section['omitted'])
            self.assertNotIn('00034106',section['omitted'])
        props = self.proof['validation']['props']
        self.assertEqual([props[k] for k in ('rows','owners','shapes','hierarchies','newly_misbound_overrides')],
                         [13484,366,263,133,0])
        expected = {
            'L2RA.BUN': '6446da55c00b02dce69d7af7e1e12045fb73456d3b52752e3c5ae7173068b2a4',
            'STREAML2RA.BUN': 'cd93bcf7fb2689d76e2d9b65f848ad0beeede3293e63816d396f7bb4509733c9',
        }
        self.assertEqual({name: info['sha256'] for name, info in self.proof['outputs'].items()}, expected)
        self.assertEqual({name: w.track.source_proof(w.DEFAULT_CARBON / name, '')['sha256']
                          for name in self.native_hashes}, self.native_hashes)

    def test_verbatim_cli_pins_former_pair_and_native_bytes(self):
        native = {name: w.track.source_proof(w.DEFAULT_CARBON / name, '')['sha256']
                  for name in ('L5RA.BUN', 'STREAML5RA.BUN', 'L5RB.BUN', 'STREAML5RB.BUN')}
        output = self.root / 'verbatim'
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()) as err:
            rc = w.main(['--out', str(output), '--rows', 'verbatim'])
        self.assertEqual(rc, 0, err.getvalue())
        expected = {
            'L2RA.BUN': '4824b17dc731174fb52f7f767184f127113e58c511aef96271462a0b0ebeb0ee',
            'STREAML2RA.BUN': 'cd93bcf7fb2689d76e2d9b65f848ad0beeede3293e63816d396f7bb4509733c9',
        }
        self.assertEqual({name: w.track.source_proof(output / 'TRACKS' / name, '')['sha256']
                          for name in expected}, expected)
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()) as err:
            self.assertEqual(w.main(['--check', str(output), '--rows', 'verbatim']), 0, err.getvalue())
            self.assertEqual(w.main(['--check', str(output)]), 1)
        self.assertIn('V-resource after scenery: 1190 placements', err.getvalue())
        self.assertEqual({name: w.track.source_proof(w.DEFAULT_CARBON / name, '')['sha256']
                          for name in native}, native)

    def test_populated_cli_proof_and_five_written_failure_controls(self):
        output = self.root / 'populated'
        with redirect_stdout(io.StringIO()) as out, redirect_stderr(io.StringIO()) as err:
            rc = w.main(['--out', str(output), '--zones'])
        self.assertEqual(rc, 0, err.getvalue())
        # This assertion measures the written pair and fails 0/11 on the old hook.
        written_index = TrackIndex((output / 'TRACKS/L2RA.BUN').read_bytes())
        district_rows = [row for row in w.zone_tables.read(w.zone_tables.select(written_index)).zones
                         if row.kind == 9]
        patterns = d.traffic_patterns()
        self.assertEqual(len(district_rows), 11)
        self.assertEqual(sum(row.key in patterns for row in district_rows), 11,
                         'written pair must bind 11/11 districts (old code binds 0/11)')
        expected_counts = dict(zones=705, markers=328, barriers=1376, districts_bound='11/11')
        self.assertEqual(json.loads(out.getvalue())['zones'], expected_counts)
        proof_path = output / 'proof.json'
        proof = json.loads(proof_path.read_text())
        self.assertTrue(proof['zones'])
        self.assertEqual(proof['validation']['zones'], expected_counts)
        path = output / 'TRACKS/L2RA.BUN'
        valid = path.read_bytes()
        self.assertEqual(len(valid), 1088808)
        source, _, _ = w.load_index(w.DEFAULT_MW, 'L2RA')
        z = w.zone_tables
        identity = z.rewrite_index(self.index_bytes, z.convert(source))
        self.assertEqual(valid, z.rewrite_index(self.index_bytes, z.convert(
            source, key_map=d.key_map(source))))
        old_rows = [row for row in z.read(z.select(TrackIndex(identity))).zones if row.kind == 9]
        self.assertEqual(sum(row.key in patterns for row in old_rows), 0)
        rows = z.read(z.select(TrackIndex(valid))).zones
        self.assertEqual(sum(row.key in patterns for row in rows if row.kind == 9), 11)
        old_parts = {c.kind: c for c in chunks(identity) if c.kind in z.KINDS}
        new_parts = {c.kind: c for c in chunks(valid) if c.kind in z.KINDS}
        for kind in (z.MARKERS, z.BARRIERS):
            self.assertEqual(old_parts[kind].payload, new_parts[kind].payload)
        polygons = next(c for c in chunks(new_parts[z.ZONES].payload, new_parts[z.ZONES].offset + 8)
                        if c.kind == z.POLYGONS)
        cursor, allowed = polygons.offset + 8, []
        for row in rows:
            if row.kind == 9:
                allowed.append(cursor + 48)
            cursor += len(row.encode())
        changed = [offset for offset in range(0, len(valid), 4)
                   if identity[offset:offset + 4] != valid[offset:offset + 4]]
        self.assertEqual(changed, allowed)
        self.assertEqual(len(changed), 11)
        print(f'districts: identity 0/11 -> bound 11/11; changed u32 offsets {changed}')
        print(f'populated identity SHA256 {hashlib.sha256(identity).hexdigest()}; '
              f'bound SHA256 {hashlib.sha256(valid).hexdigest()}')
        self.assertEqual(hashlib.sha256((output / 'TRACKS/STREAML2RA.BUN').read_bytes()).hexdigest(),
                         self.proof['outputs']['STREAML2RA.BUN']['sha256'])
        # Delete the manifest: acceptance and counts must come from written files.
        proof_path.unlink()
        with redirect_stdout(io.StringIO()) as out, redirect_stderr(io.StringIO()) as err:
            rc = w.main(['--check', str(output)])
        self.assertEqual(rc, 0, err.getvalue())
        self.assertEqual(json.loads(out.getvalue())['zones'], expected_counts)
        try:
            path.write_bytes(identity)
            with redirect_stdout(io.StringIO()) as out, redirect_stderr(io.StringIO()) as err:
                rc = w.main(['--check', str(output)])
            self.assertEqual(rc, 0, err.getvalue())
            self.assertEqual(json.loads(out.getvalue())['zones']['districts_bound'], '0/11')
        finally:
            path.write_bytes(valid)
        for label, table, message in (
                ('dropped downtown', {k: v for k, v in d.ROCKPORT_TO_CARBON.items()
                                      if k != 'downtown'}, 'unmapped type-9'),
                ('industrial target', dict(d.ROCKPORT_TO_CARBON, downtown='industrial'),
                 'target traffic pattern absent: industrial')):
            broken_output = self.root / label.replace(' ', '-')
            with mock.patch.dict(d.ROCKPORT_TO_CARBON, table, clear=True):
                with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()) as err:
                    rc = w.main(['--out', str(broken_output), '--zones'])
            self.assertEqual(rc, 1, err.getvalue())
            self.assertIn(message, err.getvalue())
            self.assertFalse(broken_output.exists())
            print(f'{label}: 0/1 accepted versus intact 1/1; {err.getvalue().strip()}')
        try:
            mixed = bytearray(valid)
            mixed[allowed[0]:allowed[0] + 4] = identity[allowed[0]:allowed[0] + 4]
            cursor = polygons.offset + 8
            for row in rows:
                if row.kind == 11:
                    break
                cursor += len(row.encode())
            else:
                self.fail('source has no type-11 control record')
            bad_map = d.key_map(source)
            bad_map[row.key] = 0xB9CE05C8
            foreign11 = z.rewrite_index(self.index_bytes, z.convert(source, key_map=bad_map))
            self.assertEqual([i for i in range(0, len(valid), 4) if valid[i:i + 4] != foreign11[i:i + 4]],
                             [cursor + 48])
            for label, broken in (('mixed 10/11 binding', mixed), ('type-11 rekey', foreign11)):
                path.write_bytes(broken)
                with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()) as err:
                    rc = w.main(['--check', str(output)])
                self.assertEqual(rc, 1, err.getvalue())
                self.assertIn('differs from source conversion', err.getvalue())
                print(f'{label}: 0/1 accepted versus intact 1/1; {err.getvalue().strip()}')
        finally:
            path.write_bytes(valid)
        missing_output = self.root / 'missing-attributes'
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()) as err:
            rc = w.main(['--out', str(missing_output), '--zones', '--carbon-root',
                         str(self.root / 'missing-carbon/TRACKS')])
        self.assertEqual(rc, 3, err.getvalue())
        self.assertIn('attributes.bin', err.getvalue())
        self.assertFalse(missing_output.exists())
        parts = [c for c in chunks(valid) if c.kind]
        marker = next(c for c in parts if c.kind == z.MARKERS)
        zone = next(c for c in parts if c.kind == z.ZONES)
        barrier = next(c for c in parts if c.kind == z.BARRIERS)
        early_marker = [c for c in parts if c.kind != z.MARKERS]
        early_marker.insert(early_marker.index(zone), marker)
        zone_children = chunks(zone.payload)
        polygons = next(c for c in zone_children if c.kind == z.POLYGONS)
        changed = bytearray(polygons.payload)
        struct.pack_into('<I', changed, 0, (struct.unpack_from('<I', changed)[0] + 1) % z.BUCKETS)
        changed_zone = encode_chunks(Chunk(c.kind, bytes(changed)) if c.kind == z.POLYGONS else c
                                     for c in zone_children)
        native_barrier = next(c for c in self.index.parts if c.kind == z.BARRIERS)
        cases = [
            ('marker before zone', early_marker, 'kinds/order differ'),
            ('changed zone type', [Chunk(c.kind, changed_zone) if c.kind == z.ZONES else c for c in parts],
             'global chunk 0x80034147 differs from source conversion'),
            ('1375 barriers', [Chunk(c.kind, barrier.payload[:-24]) if c.kind == z.BARRIERS else c for c in parts],
             'global chunk 0x3414d differs from source conversion'),
            ('duplicate marker', [c for part in parts for c in ((part, marker) if part == marker else (part,))],
             'kinds/order differ'),
            ('native barriers', [native_barrier if c.kind == z.BARRIERS else c for c in parts],
             'global chunk 0x3414d differs from source conversion'),
        ]
        try:
            for name, broken, message in cases:
                with self.subTest(control=name):
                    path.write_bytes(aligned_index(broken))
                    if name == '1375 barriers':
                        self.assertEqual(z.check(z.select(TrackIndex(path.read_bytes())))['barriers'], 1375)
                    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()) as err:
                        rc = w.main(['--check', str(output)])
                    self.assertEqual(rc, 1, err.getvalue())
                    self.assertIn(message, err.getvalue())
                    print(f'{name}: 0/1 accepted versus intact 1/1; {err.getvalue().strip()}')
        finally:
            path.write_bytes(valid)

    def test_full_written_pair_and_probe_keys_without_proof_as_evidence(self):
        report = self.proof['validation']
        self.assertEqual(report['records'], 720)
        v = report['visibility']
        self.assertEqual((v['drivable'], v['boundaries'], v['rows'], v['drivable_without_row']), (373, 515, 435, 0))
        self.assertEqual((v['absent_entries'], v['row_entries']), (5533, 16265))
        self.assertTrue(v['absent_entries_equal_source'])
        self.assertTrue(v['row_multisets_equal'])
        self.assertEqual((v['rows_changed'], v['v_after_scenery_before'], v['v_after_scenery']),
                         (378, 1190, 0))
        self.assertEqual(tuple(report['collision'][k] for k in ('cells', 'packs', 'rejects')), (2779, 390, 0))
        self.assertEqual((report['closure']['models']['resolved'], report['closure']['models']['keys']), (19269, 19293))
        self.assertEqual((report['closure']['textures']['resolved'], report['closure']['textures']['keys']), (3086, 3112))
        self.assertEqual(len(report['closure']['all_mesh_textures']['misses']), 29)
        classification = report['classification']
        self.assertEqual(classification['classified'], 56)
        self.assertEqual(classification['counts'], {
            'models': {'absent-in-source': 24, 'converter-gap': 0, 'shared-global': 0},
            'textures': {'absent-in-source': 26, 'converter-gap': 0, 'shared-global': 6}})
        self.assertEqual(classification['first_texture_meshes'], {
            'before': 25, 'after': 10, 'recoverable_after': 0,
            'all_mesh_before': 28, 'all_mesh_after': 13})
        self.assertTrue(all(r['class'] == 'absent-in-source' for kind in ('models', 'textures')
                            for r in report['closure'][kind]['misses']))
        self.assertEqual(report['ground']['grounded'], 2522)
        self.assertEqual(report['ground']['total'], 4385)
        self.assertEqual(report['pool']['rows_over'], 0)
        self.assertEqual(len(report['pool']['rows']), 435)
        self.assertEqual(self.proof['shift'], [0, 0, 0])
        self.assertFalse(any(report['dependencies'].values()))
        self.assertEqual(self.proof['number'], report['start_zero_zone']['zone'])
        self.assertTrue(all(k in self.proof['camera'] for k in ('render_eye', 'render_target')))
        path = self.output / 'proof.json'
        saved = path.read_bytes()
        try:
            path.unlink()
            with redirect_stdout(io.StringIO()) as stdout, redirect_stderr(io.StringIO()) as stderr:
                rc = w.main(['--check', str(self.output), '--zone-at', ','.join(map(str, self.proof['starts'][0]['render_xyz'][:2]))])
            self.assertEqual(rc, 0, stderr.getvalue())
            self.assertEqual(json.loads(stdout.getvalue())['zone_at'], report['start_zero_zone'])
        finally:
            path.write_bytes(saved)
        for name, info in report['outputs'].items():
            self.assertEqual(info['sha256'], w.track.source_proof(self.tracks / name, '')['sha256'])
            self.assertEqual(Path(info['path']), (self.tracks / name).resolve())

    def test_missing_drivable_row_fails_cli(self):
        idx = TrackIndex(self.index_bytes)
        source = next(c for c in idx.parts if c.kind == w.visibility.CONTAINER)
        table = w.visibility.read(source.payload)
        removed = table.drivable[0]
        body = encode_chunks(Chunk(c.kind, b''.join(r.encode() for r in table.rows if r.number != removed)
                                   if c.kind == w.visibility.ROWS else c.payload) for c in chunks(source.payload))
        idx.parts[idx.parts.index(source)] = Chunk(source.kind, body, source.offset)
        path = self.tracks / 'L2RA.BUN'
        try:
            path.write_bytes(aligned_index(idx.parts))
            self.rejected_cli('without a row')
        finally:
            path.write_bytes(self.index_bytes)

    def test_offset_moved_by_one_alignment_fails_cli(self):
        idx = TrackIndex(self.index_bytes)
        s = idx.sections[-1]
        idx.sections[-1] = w.record(s, s.offset + 2048, s.size)
        path = self.tracks / 'L2RA.BUN'
        try:
            path.write_bytes(idx.encode())
            self.rejected_cli('section outside stream')
        finally:
            path.write_bytes(self.index_bytes)

    def test_shared_provider_removed_fails_cli(self):
        resident = next(s for s in self.index.sections if s.number == 2500)
        path = self.tracks / 'STREAML2RA.BUN'
        original = w.read_section(path, resident)
        packs = [c for c in chunks(original) if c.kind == 0xb3300000]
        shared = next(c for c in packs if 0x4a31e2a3 in {
            key for key, _ in struct.iter_unpack('<II', w.region.one(w.children(
                w.region.one(w.children(c), 0xb3310000)), 0x33310002).payload)})
        try:
            with path.open('r+b') as file:
                file.seek(resident.offset + shared.offset)
                file.write(struct.pack('<I', 0))
            error = self.rejected_cli('textures closure fell:')
            self.assertIn('resolved 3085/3112', error)
        finally:
            with path.open('r+b') as file:
                file.seek(resident.offset)
                file.write(original)

    def test_shifted_section_fails_cli(self):
        section = next(s for s in self.index.sections if s.number == 1904)
        path = self.tracks / 'STREAML2RA.BUN'
        original = w.read_section(path, section)
        shifted = bytearray(original)
        # Move the written scenery arrays while retaining every physics and
        # binding envelope: this isolates the existing geometry control.
        for root in chunks(original):
            if root.kind != 0x80034100:
                continue
            for child in w.children(root):
                if child.kind not in (0x34103,0x34105):
                    continue
                raw = w.convert.aligned_payload(child)
                start = child.offset+8+(-(child.offset+8)%16)
                width = 96 if child.kind == 0x34103 else 48
                for row in range(0,len(raw),width):
                    for field in ((0,16,32) if width == 96 else (0,16)):
                        at = start+row+field
                        struct.pack_into('<f',shifted,at,struct.unpack_from('<f',shifted,at)[0]+20000)
        self.assertEqual(len(shifted), section.size)
        try:
            with path.open('r+b') as file:
                file.seek(section.offset)
                file.write(shifted)
            self.rejected_cli('world translation/bounds mismatch')
        finally:
            with path.open('r+b') as file:
                file.seek(section.offset)
                file.write(original)

    def test_without_resident_textures_fails_cli_and_counts_closure(self):
        output = self.root / 'without-textures'
        proof = w.prepare(output, without=('resident-textures',))
        self.assertEqual(proof['without'], ['resident-textures'])
        self.assertIn('textures closure fell:', proof['checker_failure'])
        texture = proof['validation']['closure']['textures']
        self.assertEqual(texture['keys'], 3112)
        self.assertLess(texture['resolved'], 3080)
        self.assertEqual(texture['resolved'], 1280)
        self.assertEqual(proof['validation']['dependencies']['new_missing_textures'], 3086 - texture['resolved'])
        self.assertTrue(all(k in proof for k in ('number', 'camera', 'starts', 'outputs')))
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()) as err:
            rc = w.main(['--check', str(output)])
        self.assertEqual(rc, 1)
        self.assertIn(f'resolved {texture["resolved"]}/3112', err.getvalue())
        print(f'without resident textures: {texture["resolved"]}/3112, intact 3086/3112; rejected')


if __name__ == '__main__':
    result = unittest.main(exit=False, verbosity=2).result
    raise SystemExit(1 if not result.wasSuccessful() else 0 if ASSETS else 3)
