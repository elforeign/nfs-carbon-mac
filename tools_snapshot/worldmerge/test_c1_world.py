"""Offline acceptance: 0 merged pairs -> 1 independently checked pair.

Valid: 1,433 unique records, 780 identities/rows, largest row 71, 641/704
active/serialized drivable; 8,988/12,328/1,524/2,148 roads; 60,955 slots,
4,165 occupied; 853 packs; duplicate/new-unresolved IDs 0. Actual row 1319
is 70,481,632 / 71,680,000 bytes. Exact-offset grounded 2,522 + 2,319;
serialized float32 road queries give 2,510, reported separately.
Nearby shift (4096,-8192): 192 x 194 = 37,248 slots, 4,171 occupied,
1,433 records, 951/962 native payloads exact; exact grounded 2,522/4,385,
float32 queries 2,526/4,385 (468 exact IDs lost, 472 gained). Section 1904
at the old placement: 2,518/4,385 grounded (valid 2,522/4,385); 0/1 broken
pairs accepted.
Zone overlaps: (4096,-8192) 0 pairs -> (0,-8192) 34 pairs; 0/1 unsafe
builds accepted. Both absent-option default hashes remain pinned below,
with the zones-on index hash pinned separately.
Required broken files: unshifted geometry 0/4,385 grounded (valid 2,522);
1,432 unique / 1,433 record numbers (valid 1,433); row 1319 has 47 entries
(valid 48); 512/512 drivable (valid 641/704); rectangle width 159
(valid 365). All five must fail the full pair checker, 0/5 accepted.
Synthetic checks always run. Missing private archives exits 3; no game runs.
Sky scenery submissions: exclusion bit present 0, removed 1; broken flags rejected.
Sky texture sentinel lookups: valid 0/1, import dropped 1/1; broken pair rejected.
Sky source LOD aliases: valid 0, one unchanged LOD 1; broken pair rejected 1/1.
Global tables: off 442/155/1238 -> on 1147/483/2614. Added broken pairs:
unmapped IDs 57 collisions (valid 0), unshifted source zones 705 (valid 0),
source-first markers 1 (valid 0), split bucket ranges 1 (valid 0), barriers
2613/2614, half-merged 442/328/1238 vs 1147/483/2614: 0/6 accepted.
"""
from contextlib import contextmanager
from dataclasses import replace
import json
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
import dome
import zones as z
from formats import Chunk, FormatError, Section, TrackIndex, chunks

ASSETS = all((root/name).is_file() for root,base in ((w.DEFAULT_MW,'L2RA'),(w.DEFAULT_CARBON,'L5RA'))
             for name in (base+'.BUN','STREAM'+base+'.BUN')) and all(
                 (root.parent/'GLOBAL/attributes.bin').is_file() for root in (w.DEFAULT_MW,w.DEFAULT_CARBON))


def fixture(number=101, x=0.):
    header = bytearray(68)
    struct.pack_into('<I',header,12,number)
    models = bytes(72)
    instances = bytearray()
    for i in range(2):
        row = bytearray(96)
        struct.pack_into('<3fI3f',row,0,x+i,0.,0.,0,x+i+1,1.,1.)
        struct.pack_into('<h',row,28,1)
        struct.pack_into('<3f9f',row,32,x+i,.5,.5,1.,0.,0.,0.,1.,0.,0.,0.,1.)
        struct.pack_into('<h',row,84,0)
        instances += row
    tree = bytearray(48)
    struct.pack_into('<3fI3f2h',tree,0,x,0.,0.,2,x+2,1.,1.,0,1)
    return w.Scene(bytes(header),models,bytes(instances),bytes(tree),bytes(256))


def serialized_scene(scene, position=0):
    out = w.convert.Builder(position+8)
    for kind,data,alignment in ((w.HEADER,scene.header,16),(w.MODELS,scene.models,1),
            (w.INSTANCES,scene.instances,16),(w.TREE,scene.tree,16),(w.PRECULL,scene.precull,1)):
        out.add(kind,data,alignment)
    return Chunk(w.SCENE,bytes(out.data),position)


def rebuilt_visibility(index, replacements):
    table = w.vis.read(w.vis.payload_of(index))
    out = w.convert.Builder(8)
    for part in table.parts:
        if part.kind == w.vis.SELECTORS:
            out.add(part.kind,b''.join(table.selectors),16)
        else:
            out.add(part.kind,replacements.get(part.kind,part.payload))
    for i,part in enumerate(index.parts):
        if part.kind == w.vis.CONTAINER:
            index.parts[i] = Chunk(part.kind,bytes(out.data),part.offset)
    # Preserve every subsequent chunk's absolute residue when the table shrinks.
    outer = w.convert.Builder(0)
    for part in index.parts:
        if part.kind == 0x34110:
            part = Chunk(part.kind,b''.join(s.raw for s in index.sections),part.offset)
        w.append_at_residue(outer,part)
    return bytes(outer.data)


def rebuilt_globals(index, replacements):
    replacements = {c.kind: c for c in replacements}
    out = w.convert.Builder(0)
    for part in index.parts:
        replacement = replacements.get(part.kind, part)
        w.append_at_residue(out, Chunk(part.kind, replacement.payload, part.offset))
    return bytes(out.data)


@contextmanager
def index_mutation(directory, mutate):
    path = directory/'TRACKS'/'L5RA.BUN'
    original = path.read_bytes()
    index = TrackIndex(original)
    path.write_bytes(mutate(index))
    try:
        yield
    finally:
        path.write_bytes(original)


@contextmanager
def old_section_collision(directory, number):
    """Leave one source section's packs at the old shift in an otherwise new pair."""
    carbon, cs, _ = w.load_index(w.DEFAULT_CARBON,'L5RA')
    source, ms, _ = w.load_index(w.DEFAULT_MW,'L2RA')
    native_grid, source_grid = w.grid.read_city(carbon,cs), w.grid.read_city(source,ms)
    mapping = w.grid.allocate_ids(native_grid.packs,source_grid.packs)
    section = next(s for s in source.sections if s.number == number)
    replacements = {}
    for root in chunks(w.read_section(ms,section)):
        if root.kind == w.PACK:
            pack = w.region.collision_body(root)
            target = mapping[w.u32(pack,4)]
            replacements[target] = w.grid.move_pack(pack,target,w.DEFAULT_SHIFT)
    if not replacements:
        raise AssertionError('control section has no collision packs')
    index, stream, _ = w.load_index(directory/'TRACKS','L5RA')
    resident = next(s for s in index.sections if s.number == w.RESIDENT)
    saved = []
    try:
        with stream.open('r+b') as f:
            for root in chunks(w.read_section(stream,resident)):
                if root.kind != w.PACK:
                    continue
                body = w.region.collision_body(root)
                target = w.u32(body,4)
                if target not in replacements:
                    continue
                offset = resident.offset+root.offset+8+(-(root.offset+8)%16)
                replacement = replacements[target]
                if len(replacement) != len(body):
                    raise AssertionError('pack mutation changed extent')
                saved.append((offset,body))
                f.seek(offset)
                f.write(replacement)
        if len(saved) != len(replacements):
            raise AssertionError('control did not replace every section pack')
        yield len(saved)
    finally:
        with stream.open('r+b') as f:
            for offset, body in saved:
                f.seek(offset)
                f.write(body)


class Synthetic(unittest.TestCase):
    def test_coalesce_arrays_and_signed_selectors_and_joined_tree(self):
        sources = [fixture(101,0.),fixture(201,10.),fixture(301,20.)]
        for position in (0,128,256):
            root = w.combine_scenes(sources,401,position)
            scene = w.scene_data(root)
            self.assertEqual((scene.number,len(scene.models)//72,len(scene.instances)//96,
                              len(scene.tree)//48,len(scene.precull)//128),(401,3,6,4,6))
            w._check_scene_tree(scene)
            self.assertEqual(struct.unpack_from('<3h',scene.tree,28),(-1,-2,-3))
            for i in range(6):
                self.assertEqual(struct.unpack_from('<h',scene.instances,i*96+84)[0],i//2)
                self.assertEqual(struct.unpack_from('<h',scene.instances,i*96+28)[0],1+2*(i//2))
            w._check_scene_sources(scene,[(s,True) for s in sources],401)
        single = w.scene_data(w.combine_scenes([sources[0]],101,0))
        self.assertEqual(single,sources[0])

    def test_corrupt_scenery_model_precull_tree_and_omitted_contribution(self):
        sources = [fixture(),fixture(201,10.)]
        scene = w.scene_data(w.combine_scenes(sources,301,0))
        for field,offset,value in (('instances',84,2),('instances',28,4),('tree',28,0),('tree',28,-32768)):
            data = bytearray(getattr(scene,field))
            struct.pack_into('<h',data,offset,value)
            with self.subTest(field=field,offset=offset,value=value),self.assertRaises(FormatError):
                w._check_scene_tree(replace(scene,**{field:bytes(data)}))
        missing = w.scene_data(w.combine_scenes([sources[0]],301,0))
        with self.assertRaisesRegex(FormatError,'provenance|extra/missing|join'):
            w._check_scene_sources(missing,[(s,True) for s in sources],301)
        # The base converter's lost precull selector is in range, so range
        # checks alone cannot prove it. Source-byte comparison must reject it.
        lost = bytearray(scene.instances)
        struct.pack_into('<h',lost,28,0)
        lost = replace(scene,instances=bytes(lost))
        w._check_scene_tree(lost)
        with self.assertRaisesRegex(FormatError,'source identity unresolved|instance translation/selector/provenance'):
            w._check_scene_sources(lost,[(s,True) for s in sources],301)

    def test_native_instance_sidecar_retained_only_for_native_prefix(self):
        first = replace(fixture(),extras=(Chunk(0x3410d,bytes(range(64))),))
        second = fixture(201,10.)
        scene = w.scene_data(w.combine_scenes([first,second],301,0))
        self.assertEqual([(c.kind,c.payload) for c in scene.extras],[(0x3410d,bytes(range(64)))])
        w._check_scene_sources(scene,[(first,True),(second,True)],301)
        with self.assertRaisesRegex(FormatError,'sidecar bytes differ'):
            w._check_scene_sources(replace(scene,extras=()),[(first,True),(second,True)],301)
        self.assertEqual(scene.instances[2*96+92:3*96],bytes(4))

    def test_unshifted_scenery_is_not_the_translation_oracle(self):
        raw = bytearray(64)
        struct.pack_into('<6f',raw,0,1.,2.,3.,4.,5.,6.)
        struct.pack_into('<IHH3f9hh',raw,24,0x123,1,0xffff,7.,8.,9.,8192,0,0,0,8192,0,0,0,8192,0)
        expected = w._source_instance(raw,False)
        self.assertEqual(struct.unpack_from('<3f',expected,32),(7.,-20472.,9.))
        self.assertEqual(struct.unpack_from('<h',expected,28)[0],1)
        self.assertEqual(struct.unpack_from('<I',expected,12)[0],0x123)
        self.assertNotEqual(expected[32:44],raw[32:44])

    def test_moving_roots_preserves_nested_alignment(self):
        scene = fixture()
        original = serialized_scene(scene,40)
        out = w.convert.Builder(256)
        w.append_at_residue(out,original)
        moved = next(c for c in chunks(out.data,out.base) if c.kind == w.SCENE)
        self.assertEqual(moved.offset%128,original.offset%128)
        self.assertEqual(w.scene_data(moved),scene)

    def test_output_guards_missing_inputs_and_atomic_publication(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            for path in (w.ROOT/'bad-output',w.DEFAULT_MW/'bad-output'):
                with self.assertRaisesRegex(FormatError,'outside'):
                    w._output_path(path,(w.DEFAULT_MW,w.DEFAULT_CARBON))
            (root/'other-checkout').mkdir()
            (root/'other-checkout'/'.git').write_text('gitdir: fixture\n')
            with self.assertRaisesRegex(FormatError,'every checkout'):
                w._output_path(root/'other-checkout'/'new',())
            (root/'alias').symlink_to(w.ROOT,target_is_directory=True)
            with self.assertRaisesRegex(FormatError,'outside'):
                w._output_path(root/'alias'/'new',())
            dest = root/'out'
            def write_stub(mw,carbon,stage,*,zones=False,shift=w.DEFAULT_SHIFT):
                (stage/'TRACKS').mkdir()
                (stage/'TRACKS'/'L5RA.BUN').write_bytes(b'index')
                (stage/'TRACKS'/'STREAML5RA.BUN').write_bytes(b'stream')
            with patch.object(w,'_write_pair',side_effect=write_stub),patch.object(w,'check',return_value={'ok':True}) as checked:
                with patch.object(w.os,'rename',side_effect=OSError('injected publication failure')):
                    with self.assertRaisesRegex(OSError,'injected'):
                        w.build(w.DEFAULT_MW,w.DEFAULT_CARBON,dest)
                self.assertFalse(dest.exists())
                self.assertFalse(list(root.glob('.c1-world-*')))
                self.assertEqual(w.build(w.DEFAULT_MW,w.DEFAULT_CARBON,dest),{'ok':True})
                self.assertEqual(checked.call_count,2)
            with self.assertRaisesRegex(FormatError,'exists'):
                w.build(w.DEFAULT_MW,w.DEFAULT_CARBON,dest)
            self.assertEqual((dest/'TRACKS'/'L5RA.BUN').read_bytes(),b'index')
            with patch.object(w,'_write_pair',side_effect=write_stub),patch.object(w,'check',side_effect=FormatError('bad pair')):
                with self.assertRaisesRegex(FormatError,'bad pair'):
                    w.build(w.DEFAULT_MW,w.DEFAULT_CARBON,root/'rejected')
                self.assertFalse((root/'rejected').exists())
                self.assertFalse(list(root.glob('.c1-world-*')))
            run = subprocess.run([sys.executable,'-I',str(HERE/'c1_world.py'),'--mw-root',str(root),
                                  '--out',str(root/'missing')],capture_output=True,text=True)
            self.assertEqual(run.returncode,3,run.stderr)
            self.assertIn('SKIP',run.stdout)
            self.assertFalse((root/'missing').exists())

    def test_zones_option_reaches_writer_and_missing_assets_exit_three(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            with patch.object(w, '_write_pair') as writer, patch.object(w, 'check', return_value={'ok':True}):
                self.assertEqual(w.build(root/'mw', root/'carbon', root/'out', zones=True), {'ok':True})
                self.assertEqual(writer.call_args.kwargs, {'zones':True,'shift':w.DEFAULT_SHIFT})
            run = subprocess.run([sys.executable, '-I', str(HERE/'c1_world.py'), '--zones',
                                  '--mw-root', str(root), '--out', str(root/'missing')],
                                 capture_output=True, text=True)
            self.assertEqual(run.returncode, 3, run.stderr)
            self.assertIn('SKIP', run.stdout)

    def test_shift_option_and_default_reach_writer_and_checker(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            for shift in (w.DEFAULT_SHIFT, (4096., -8192.)):
                with self.subTest(shift=shift), patch.object(w, '_write_pair') as writer, \
                        patch.object(w, 'check', return_value={'ok':True}) as checker:
                    w.build(root/'mw', root/'carbon', root/str(shift), shift=shift)
                    self.assertEqual(writer.call_args.kwargs, {'zones':False,'shift':shift})
                    self.assertEqual(checker.call_args.kwargs, {'shift':shift})
            for options, expected in (([], w.DEFAULT_SHIFT),
                                      (['--shift','4096','-8192'], [4096.,-8192.])):
                with patch.object(w, 'build', return_value={}) as build, \
                        patch.object(w.Path, 'is_file', return_value=True):
                    self.assertEqual(w.main(['--out',str(root/'cli'),*options]), 0)
                    self.assertEqual(build.call_args.kwargs['shift'], expected)

    def test_placement_period_polygon_contacts_grid_limit_and_cell_clearance(self):
        for bad in ((4095,0), (4096,-8191), (float('nan'),0), (0,float('inf')), (0,), 'XZ'):
            with self.subTest(bad=bad), self.assertRaises(FormatError):
                w._physics_shift(bad)
        square = [(0.,0.),(4.,0.),(4.,4.),(0.,4.)]
        for other in ([(1.,1.),(2.,1.),(2.,2.),(1.,2.)],
                      [(4.,1.),(5.,1.),(5.,2.),(4.,2.)],
                      [(-1.,1.),(5.,1.),(5.,2.),(-1.,2.)]):
            self.assertTrue(w._polygons_intersect(square,other))
            self.assertTrue(w._polygons_intersect(other,square))
        self.assertFalse(w._polygons_intersect(square,[(5.,0.),(6.,0.),(6.,1.),(5.,1.)]))
        def city(x, z=0.):
            descriptor = bytearray(40)
            struct.pack_into('<3f',descriptor,0,x,0.,z)
            struct.pack_into('<f',descriptor,16,96.)
            struct.pack_into('<2I',descriptor,24,1,1)
            return w.grid.City(bytes(descriptor),(bytes(8),),{},(),(),0)
        native = city(0.)
        self.assertEqual(w._placement_grid(native,city(288.),(0.,0.)),(1,4,2))
        for source in (city(192.),city(192.,192.),city(0.)):
            with self.assertRaisesRegex(FormatError,'collision cells within two cells'):
                w._placement_grid(native,source,(0.,0.))
        with self.assertRaisesRegex(FormatError,'exceeds 65536 slots'):
            w._placement_grid(native,city(96.*65536),(0.,0.))
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)/'invalid'
            with self.assertRaisesRegex(FormatError,'X=1 m must be a multiple of 4096 m'):
                w.build(Path(tmp),Path(tmp),out,shift=(1,0))
            self.assertFalse(out.exists())
            self.assertFalse(list(Path(tmp).glob('.c1-world-*')))

    def test_shifted_globals_independent_reader_and_old_coordinate_controls(self):
        from test_c1_zones import fixture as global_fixture
        carbon, source = global_fixture(True), global_fixture(False)
        mapping = {101:201,102:202,104:204}
        merged = global_fixture(True)
        for shift in ((4096.,-8192.),(-8192.,4096.),(0.,-8192.),(4096.,0.)):
            with self.subTest(shift=shift):
                merged.parts = list(w._merge_globals(carbon,source,mapping,shift))
                with patch.object(w.c1_zones,'merge',side_effect=AssertionError('reader used merger')), \
                     patch.object(z,'convert',side_effect=AssertionError('reader used converter')):
                    report = w._check_globals(merged,carbon,source,mapping,shift)
                self.assertEqual((report['zones'],report['markers'],report['barriers']),(10,6,4))
                table = z.read(z.select(merged))
                baseline = z.read(w.c1_zones.merge(carbon,source,mapping))
                for family in ('zones','markers','barriers'):
                    # Native prefixes remain intact; every appended coordinate
                    # in this family is deliberately left at the old placement.
                    bad = replace(table,**{family:getattr(baseline,family)})
                    merged.parts = list(bad.encode())
                    with self.assertRaisesRegex(FormatError,'translation'):
                        w._check_globals(merged,carbon,source,mapping,shift)
                merged.parts = list(w._merge_globals(carbon,source,mapping,shift))
                # Normalizing proven coordinates must not hide nonspatial bytes.
                rows = list(table.markers)
                raw = bytearray(rows[-1]); raw[8] ^= 1; rows[-1] = bytes(raw)
                merged.parts = list(replace(table,markers=tuple(rows)).encode())
                with self.assertRaisesRegex(FormatError,'source bytes'):
                    w._check_globals(merged,carbon,source,mapping,shift)

    def test_global_forms_and_scaffold_are_all_or_nothing(self):
        from test_c1_zones import fixture as global_fixture
        carbon, source = global_fixture(True), global_fixture(False)
        mapping = {101:201, 102:202, 104:204}
        self.assertEqual(w._check_globals(carbon,carbon,source,mapping)['mode'],'off')
        merged = global_fixture(True)
        merged.parts = list(w.c1_zones.merge(carbon,source,mapping))
        self.assertEqual(w._check_globals(merged,carbon,source,mapping)['mode'],'merged')
        partial = global_fixture(True)
        partial.parts[1] = merged.parts[1]
        with self.assertRaisesRegex(FormatError,'zone count'):
            w._check_globals(partial,carbon,source,mapping)
        reordered = global_fixture(True)
        reordered.parts.reverse()
        with self.assertRaisesRegex(FormatError,'kinds/order'):
            w._check_globals(reordered,carbon,source,mapping)
        carbon.parts.append(Chunk(0x1234,b'native scaffold'))
        merged.parts.append(Chunk(0x1234,b'changed scaffold'))
        with self.assertRaisesRegex(FormatError,'scaffold changed'):
            w._check_globals(merged,carbon,source,mapping)


@unittest.skipUnless(ASSETS,'private world archives absent')
class Private(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='c1-world-test-')
        cls.addClassCleanup(cls.temp.cleanup)
        cls.root = Path(cls.temp.name).resolve()
        cls.directory = cls.root/'valid'
        cls.report = w.build(w.DEFAULT_MW,w.DEFAULT_CARBON,cls.directory)
        cls.merged = cls.root/'zones'
        cls.zones_report = w.build(w.DEFAULT_MW,w.DEFAULT_CARBON,cls.merged,zones=True)

    def test_sky_texture_import_and_dropped_provider_control(self):
        index, stream, _ = w.load_index(self.directory/'TRACKS', 'L5RA')
        resident = next(s for s in index.sections if s.number == 2100)
        roots = chunks(w.read_section(stream, resident))
        # Decode the written solid independently, including every directory slot.
        keys = set()
        for root in roots:
            if root.kind != 0x80134000:
                continue
            for solid in chunks(root.payload, root.offset+8):
                if solid.kind != 0x80134010:
                    continue
                parts = chunks(solid.payload, solid.offset+8)
                header = next(c for c in parts if c.kind == 0x134011)
                if w.u32(w.convert.aligned_payload(header),16) == 0x1f389568:
                    table = next(c.payload for c in parts if c.kind == 0x134012)
                    keys.update(k for k, _ in struct.iter_unpack('<II',table))
        self.assertEqual(keys,{0x4a31e2a3})
        report = w.dome.check(index,stream,w.DEFAULT_MW)
        self.assertEqual(report,dict(textures=['4A31E2A3'],sentinel_lookups=0,section=2100))
        imports = []
        for root in roots:
            if root.kind != 0xb3300000:
                continue
            hp = next(c for c in chunks(root.payload,root.offset+8) if c.kind == 0xb3310000)
            table = next(c.payload for c in chunks(hp.payload,hp.offset+8) if c.kind == 0x33310002)
            if keys & {k for k, _ in struct.iter_unpack('<II',table)}:
                imports.append(root.offset)
        self.assertEqual(len(imports),1)
        offset = resident.offset+imports[0]
        with stream.open('r+b') as f:
            f.seek(offset); saved=f.read(4)
            f.seek(offset); f.write(bytes(4)) # Drop the pack without moving any record.
        try:
            with self.assertRaisesRegex(FormatError,'sky sentinel lookups: 4A31E2A3'):
                w.dome.check(index,stream,w.DEFAULT_MW)
            with self.assertRaisesRegex(FormatError,'sky sentinel lookups: 4A31E2A3'):
                w.check(self.directory)
        finally:
            with stream.open('r+b') as f:
                f.seek(offset);f.write(saved)
        print('SKY sentinel lookups valid=0/1 import-dropped=1/1; broken pair rejected')

    def test_sky_has_one_global_owner_not_a_scenery_submission(self):
        index, stream, _ = w.load_index(self.directory/'TRACKS','L5RA')
        selected = []
        for section in index.sections:
            for root in chunks(w.read_section(stream,section)):
                if root.kind != w.SCENE:
                    continue
                scene = w.scene_data(root)
                inst = next(c for c in chunks(root.payload,root.offset+8) if c.kind == w.INSTANCES)
                for p in range(0,len(scene.instances),96):
                    model = struct.unpack_from('<h',scene.instances,p+84)[0]
                    if w.u32(scene.models,model*72+24) == 0x1f389568:
                        offset = section.offset+inst.offset+8+(-(inst.offset+8)%16)+p+12
                        selected.append((offset,w.u32(scene.instances,p+12)))
        self.assertEqual(len(selected),1)
        offset,flags = selected[0]
        self.assertEqual(flags,0xc8200)
        # Exact predicates from 0079AFA0; both possible sky-gate states.
        submits = lambda f,g: (not f&0x80000 or not g) and (not f&0x40000 or g or f&0x100)
        self.assertEqual([bool(submits(flags,g)) for g in (0,1)],[False,False])
        broken = flags & ~0x40000
        self.assertEqual(bool(submits(broken,0)),True)
        with stream.open('r+b') as f:
            f.seek(offset);f.write(struct.pack('<I',broken))
        try:
            with self.assertRaisesRegex(FormatError,'source identity unresolved|instance translation/selector/provenance'):
                w.check(self.directory)
        finally:
            with stream.open('r+b') as f:
                f.seek(offset);f.write(struct.pack('<I',flags))
        print('SKY scenery submissions valid=0 exclusion-dropped=1; broken flags rejected')

    def test_one_source_dome_lod_left_on_native_key_is_rejected(self):
        index, stream, _ = w.load_index(self.directory/'TRACKS', 'L5RA')
        references, old_references, at = 0, 0, None
        domes = {}
        for section in index.sections:
            for root in w.chunks(w.read_section(stream, section)):
                if root.kind == 0x80134000:
                    for solid in w.chunks(root.payload,root.offset+8):
                        if solid.kind != 0x80134010:
                            continue
                        parts = w.chunks(solid.payload,solid.offset+8)
                        header = next(c for c in parts if c.kind == 0x134011)
                        key = w.u32(w.convert.aligned_payload(header),16)
                        if key in (0xed85ba82,0x1f389568):
                            mesh = next(c for c in parts if c.kind == 0x80134100)
                            buffers = [len(w.convert.aligned_payload(c)) for c in
                                       w.chunks(mesh.payload,mesh.offset+8) if c.kind == 0x134b01]
                            self.assertNotIn(key,domes)
                            domes[key] = (solid.encode(),buffers)
                if root.kind != w.SCENE:
                    continue
                table = next(c for c in w.chunks(root.payload, root.offset+8) if c.kind == w.MODELS)
                for p in range(0,len(table.payload),72):
                    for off in (24,28,32,36):
                        key = w.u32(table.payload,p+off)
                        old_references += key == 0xed85ba82
                        if key == 0x1f389568:
                            references += 1
                            at = section.offset+table.offset+8+p+off
        self.assertEqual(references, 3)
        self.assertGreater(old_references, 0)
        self.assertEqual(domes[0x1f389568][1],[6204])
        self.assertEqual(domes[0xed85ba82][1],[7304])
        native, native_stream, _ = w.load_index(w.DEFAULT_CARBON,'L5RA')
        native_x00 = next(s for s in native.sections if s.number == 2400)
        for root in w.chunks(w.read_section(native_stream,native_x00)):
            if root.kind == 0x80134000:
                for solid in w.chunks(root.payload,root.offset+8):
                    if solid.kind == 0x80134010:
                        header = next(c for c in w.chunks(solid.payload,solid.offset+8) if c.kind == 0x134011)
                        if w.u32(w.convert.aligned_payload(header),16) == 0xed85ba82:
                            self.assertEqual(domes[0xed85ba82][0],solid.encode())
        with stream.open('r+b') as file:
            file.seek(at)
            original = file.read(4)
            file.seek(at)
            file.write(struct.pack('<I',0xed85ba82))
        try:
            with self.assertRaisesRegex(FormatError,'scenery 2600: translated source identity unresolved/ambiguous'):
                w.check(self.directory)
        finally:
            with stream.open('r+b') as file:
                file.seek(at)
                file.write(original)
        print(f'DOME valid aliases=0; broken aliases=1 rejected; source LODs={references}; native LODs={old_references}')

    def test_combined_attributes_overlay(self):
        for output in (self.directory, self.merged):
            raw = (output/'GLOBAL/ATTRIBUTES.BIN').read_bytes()
            report = w.prop_attributes.verify(
                (w.DEFAULT_MW.parent/'GLOBAL/attributes.bin').read_bytes(),
                (w.DEFAULT_CARBON.parent/'GLOBAL/attributes.bin').read_bytes(), raw)
            self.assertEqual(report['added'], 10)
            self.assertEqual(report['mass_offset'], 16)
            self.assertEqual(report['stringkey_bytes'], 8)

    def test_default_hashes_and_complete_global_merge_without_writer_or_plan(self):
        self.assertEqual(self.report['files']['L5RA.BUN']['sha256'],
                         'c910f1278bcc3cdff202b13d88b49b04da5c2bd28ab3ddc154cd62f77acee4cc')
        self.assertEqual(self.report['files']['STREAML5RA.BUN']['sha256'],
                         '15810118ff076c9aa08a649648291d9816e80a0d60908763f52405a531eef525')
        self.assertEqual(self.zones_report['files']['L5RA.BUN']['sha256'],
                         'ae114f50e5e346ef92bc8783a2e86d8f399cf9a3a4d9d6ae2358af2457786b03')
        self.assertEqual(self.zones_report['files']['STREAML5RA.BUN'],self.report['files']['STREAML5RA.BUN'])
        self.assertEqual(self.report['zones']['mode'],'off')
        (self.merged/'proof.json').write_text('{"zones": "forged"}\n')
        with patch.object(w.numbers,'plan',side_effect=AssertionError('checker used plan')), \
             patch.object(w.c1_zones,'merge',side_effect=AssertionError('checker used merger')), \
             patch.object(z,'convert',side_effect=AssertionError('checker used zone converter')):
            report = w.check(self.merged)
        self.assertEqual(report,self.zones_report)
        self.assertEqual([report['zones'][k] for k in ('zones','markers','barriers')],[1147,483,2614])
        self.assertEqual(report['zones']['mapped_type6_words'],514)
        self.assertEqual(report['zones']['cross_city_type6_duplicates'],0)
        self.assertEqual(report['zones']['native_marker_lookups_preserved'],155)

    def test_six_serialized_global_table_failures(self):
        from dataclasses import replace
        carbon,_,_ = w.load_index(w.DEFAULT_CARBON,'L5RA')
        source,_,_ = w.load_index(w.DEFAULT_MW,'L2RA')
        native = z.read(z.select(carbon))
        original = z.read(z.select(source))
        native_count = sum(r.kind == 6 for r in native.zones)
        source_six = [r for r in original.zones if r.kind == 6]
        def variants(index):
            table = z.read(z.select(index))
            rows, nth = [], 0
            for row in table.zones:
                if row.kind == 6:
                    if nth >= native_count:
                        source_row = source_six[nth-native_count]
                        row = replace(row,header=row.header[:48]+source_row.header[48:64]+row.header[64:])
                    nth += 1
                rows.append(row)
            yield '57/0 type-6 collisions',replace(table,zones=tuple(rows)),'translation/identity'
            rows = []
            for kind in range(z.BUCKETS):
                rows.extend(r for r in native.zones if r.kind == kind)
                incoming = iter(r for r in original.zones if r.kind == kind)
                for row in [r for r in table.zones if r.kind == kind][sum(r.kind == kind for r in native.zones):]:
                    source_row = next(incoming)
                    rows.append(replace(source_row,header=source_row.header[:48]+row.header[48:64]+source_row.header[64:]))
            yield '705/0 unshifted zones',replace(table,zones=tuple(rows)),'translation/identity'
            n = len(native.markers)
            yield '1/0 source-first markers',replace(table,markers=table.markers[n:n+1]+table.markers[:n]+table.markers[n+1:]),'marker prefix'
            rows = list(table.zones)
            moved = rows.pop(next(i for i,r in enumerate(rows) if r.kind == 9))
            rows.insert(max(i for i,r in enumerate(rows) if r.kind == 16),moved)
            yield '1/0 split bucket ranges',replace(table,zones=tuple(rows)),'first/last'
            self.assertEqual(len(table.barriers),2614)
            yield '2613/2614 barriers',replace(table,barriers=table.barriers[:-1]),'barrier count'
            moved = z.read(z.convert(source,shift=(20480.,0.),track=2000))
            yield '442/328/1238 half merge',replace(native,markers=moved.markers),'zone count'
        index = TrackIndex((self.merged/'TRACKS/L5RA.BUN').read_bytes())
        rejected = 0
        for label,bad,reason in variants(index):
            with self.subTest(label=label), index_mutation(self.merged,lambda idx:rebuilt_globals(idx,bad.encode())):
                with self.assertRaisesRegex(FormatError,reason):
                    w.check(self.merged)
                rejected += 1
            print('BROKEN '+label+': full check rejected')
        self.assertEqual(rejected,6)
        print('Global broken files: 6/6 rejected; 0/6 accepted')

    def test_complete_pair_limits_provenance_and_grounded_nodes(self):
        # Forge the nonauthoritative sidecar and make plan() unusable: neither
        # may influence an independent reread of the actual pair and sources.
        (self.directory/'proof.json').write_text('{"records": 1, "forged": true}\n')
        with patch.object(w.numbers,'plan',side_effect=AssertionError('checker used writer plan')):
            report = w.check(self.directory)
        self.assertEqual(report,self.report)
        self.assertEqual([report['props'][k] for k in ('rows','shapes','hierarchies','newly_misbound_overrides')],
                         [13484,263,133,0])
        self.assertEqual(report['records'],1433)
        self.assertEqual((report['duplicate_ids'],report['new_unresolved_references']),(0,0))
        v = report['visibility']
        self.assertEqual((v['zones'],v['zone_identities'],v['rows'],v['boundaries']),(775,780,780,930))
        self.assertEqual((v['largest_row'],v['bitmap_extent'],v['polygon_max']),(71,2601,28))
        self.assertEqual((v['drivable'],v['drivable_slots']),(641,704))
        self.assertEqual((v['worst_row'],v['worst_row_bytes'],v['row_byte_margin']),(1319,70482144,1197856))
        self.assertEqual(report['roads']['counts'],dict(nodes=8988,segments=12328,profiles=1524,roads=2148))
        g = report['grid']
        self.assertEqual((g['rows'],g['columns'],g['slots'],g['occupied'],g['packs']),(167,365,60955,4165,853))
        self.assertEqual((g['tile_bytes'],g['unresolved']),(379040,0))
        self.assertEqual(g['family_maxima'],[60,0,0,88])
        for city,expected in (('palmont',2319),('rockport',2522)):
            self.assertEqual(report['grounded'][city],dict(before=expected,after=expected,same_nodes=True,max_height_difference_m=0.))
        self.assertEqual(report['grounded']['rockport_serialized_float32']['grounded'],2510)
        self.assertEqual(report['palmont_bytes']['metadata_changed_bytes'],2863)
        self.assertEqual(report['palmont_bytes']['payload_array_and_kind_changed_bytes'],29)
        self.assertEqual(report['palmont_bytes']['payload_prefix_changed_bytes'],8011553)
        self.assertEqual(report['palmont_bytes']['payload_added_bytes'],111931292)
        self.assertEqual(report['palmont_bytes']['records_with_changed_payload'],11)
        print('ACCEPT 1 pair; 1433 records; zones/rows 780; row 1319=70482144/71680000; grounded 2522+2319; duplicates/unresolved 0')

    def test_nearby_pairs_and_one_old_collision_section(self):
        shift = (4096.,-8192.)
        near = self.root/'nearby'
        report = w.build(w.DEFAULT_MW,w.DEFAULT_CARBON,near,shift=shift)
        zoned = self.root/'nearby-zones'
        with_zones = w.build(w.DEFAULT_MW,w.DEFAULT_CARBON,zoned,shift=shift,zones=True)
        self.assertEqual(report['files']['STREAML5RA.BUN'],with_zones['files']['STREAML5RA.BUN'])
        for directory, expected in ((near,report),(zoned,with_zones)):
            (directory/'proof.json').write_text('{"records":0,"shift":[20480,0]}\n')
            with patch.object(w.numbers,'plan',side_effect=AssertionError('reader used plan')), \
                 patch.object(w.c1_zones,'merge',side_effect=AssertionError('reader used merger')), \
                 patch.object(z,'convert',side_effect=AssertionError('reader used zone converter')):
                actual = w.check(directory,shift=shift)
            self.assertEqual(actual,expected)
            self.assertEqual((actual['records'],actual['duplicate_ids']),(1433,0))
            self.assertTrue(all(n == 0 for n in actual['duplicate_counts'].values()))
            g = actual['grid']
            self.assertEqual((g['rows'],g['columns'],g['slots'],g['occupied']),(192,194,37248,4171))
            self.assertEqual(actual['palmont_bytes']['records_with_changed_payload'],11)
            self.assertEqual((actual['palmont_bytes']['records_byte_exact'],
                              actual['palmont_bytes']['records_total']),(951,962))
            self.assertEqual(actual['roads']['counts'],dict(nodes=8988,segments=12328,profiles=1524,roads=2148))
            for city, count in (('rockport',2522),('palmont',2319)):
                self.assertEqual(actual['grounded'][city],dict(before=count,after=count,
                                 same_nodes=True,max_height_difference_m=0.))
            self.assertEqual(actual['grounded']['rockport_serialized_float32'],
                             dict(grounded=2526,exact_offset_grounded=2522,same_list_as_exact_offset=False,
                                  lost_from_exact_offset=468,gained_from_exact_offset=472))
        self.assertEqual(with_zones['zones']['mode'],'merged')
        self.assertEqual(tuple(with_zones['zones'][k] for k in ('zones','markers','barriers')),(1147,483,2614))
        carbon, cs, _ = w.load_index(w.DEFAULT_CARBON,'L5RA')
        source, ms, _ = w.load_index(w.DEFAULT_MW,'L2RA')
        native_bounds = w.vis.read(w.vis.payload_of(carbon)).boundaries
        index, stream, _ = w.load_index(near/'TRACKS','L5RA')
        native_ids = {b.number for b in native_bounds}
        incoming = [b for b in w.vis.read(w.vis.payload_of(index)).boundaries if b.number not in native_ids]
        self.assertEqual(w._zone_overlaps(native_bounds,incoming),[])
        for zones in (False,True):
            rejected = self.root/f'overlap-{zones}'
            with self.assertRaisesRegex(FormatError,'zone-class polygon overlap.*1104/1735.*1104/1739.*1105/1739.*1106/1739.*34 pairs total'):
                w.build(w.DEFAULT_MW,w.DEFAULT_CARBON,rejected,zones=zones,shift=(0.,-8192.))
            self.assertFalse(rejected.exists())
        nodes = [(x+shift[0],y,z+shift[1]) for x,y,z in w.ground.road_nodes(source)]
        with old_section_collision(near,1904) as packs:
            self.assertEqual(packs,1)
            index, stream, _ = w.load_index(near/'TRACKS','L5RA')
            grounded, _ = w._grounded(w.ground.World(index,stream),nodes)
            self.assertEqual(len(grounded),2518)
            with self.assertRaisesRegex(FormatError,r'grounded node list changed \(2522 -> 2518\)'):
                w._check_ground(index,stream,carbon,cs,source,ms,shift)
            with self.assertRaisesRegex(FormatError,'collision pack translation'):
                w.check(near,shift=shift)
        print('NEARBY off/on: 192x194,37248 slots,4171 occupied,1433 records,0 duplicate IDs,951/962 native exact')
        print('GROUNDED exact 2522/4385; float32 2526/4385; old section1904 2518/4385 rejected; overlaps 0 -> 34 refused')

    def test_required_serialized_broken_variants(self):
        accepted = []
        def duplicate(index):
            raw = bytearray(index.sections[-1].raw)
            struct.pack_into('<h',raw,8,index.sections[0].number)
            index.sections[-1] = Section(bytes(raw))
            return index.encode()
        def row_drop(index):
            table = w.vis.read(w.vis.payload_of(index))
            rows = []
            for row in table.rows:
                if row.number == 1319:
                    self.assertEqual(len(row.entries),48)
                    header = bytearray(row.header)
                    struct.pack_into('<h',header,16,47)
                    row = w.vis.Row(bytes(header),row.entries[1:],row.spare+bytes(2))
                rows.append(row.encode())
            return rebuilt_visibility(index,{w.vis.ROWS:b''.join(rows)})
        def drive_cut(index):
            table = w.vis.read(w.vis.payload_of(index))
            drive = struct.pack('<II512h',40,512,*table.slots[:512])
            return rebuilt_visibility(index,{w.vis.DRIVE:drive})
        def rectangle(index):
            for i,part in enumerate(index.parts):
                if part.kind == w.MAP:
                    raw = bytearray(part.payload)
                    pad = -(part.offset+8)%16
                    tag = w.region.collision_tags(raw[pad:],w.grid.CDAT)[w.grid.RECT]
                    struct.pack_into('<H',raw,pad+tag[3]+6,159)
                    index.parts[i] = Chunk(part.kind,bytes(raw),part.offset)
            return index.encode()
        for label,mutate,reason in (('1432/1433 distinct record numbers',duplicate,'duplicate section'),
                ('47/48 row entries',row_drop,'source entry union'),
                ('512/512 vs 641/704 drivable',drive_cut,'drivable array'),
                ('159/365 rectangle width',rectangle,'outside rectangle')):
            with self.subTest(label=label),index_mutation(self.directory,mutate):
                try:
                    w.check(self.directory)
                except FormatError as error:
                    self.assertIn(reason,str(error))
                else:
                    accepted.append(label)
            print('BROKEN '+label+': rejected')
        # All source render positions and collision pack transforms remain at
        # their original coordinates. The planned grid/road destinations remain
        # shifted, reproducing the integration error this checker must catch.
        bad = self.root/'unshifted'
        bad.mkdir()
        move_pack = w.grid.move_pack
        converter = w.convert.convert_section
        def unshifted(*args, **kwargs):
            return converter(*args, **dict(kwargs, shift=(0.,0.)))
        with patch.object(w.convert,'convert_section',side_effect=unshifted),patch.object(w.grid,'move_pack',
                    side_effect=lambda raw,key,shift:move_pack(raw,key,(0.,0.))):
            w._write_pair(w.DEFAULT_MW,w.DEFAULT_CARBON,bad)
        index,stream,_ = w.load_index(bad/'TRACKS','L5RA')
        source,_,_ = w.load_index(w.DEFAULT_MW,'L2RA')
        nodes = [(x+20480.,y,z) for x,y,z in w.ground.road_nodes(source)]
        grounded,_ = w._grounded(w.ground.World(index,stream),nodes)
        self.assertEqual(len(grounded),0)
        with self.assertRaisesRegex(FormatError,'translated source identity unresolved'):
            w.check(bad)
        self.assertFalse(accepted,accepted)
        print('BROKEN unshifted geometry: 0/4385 grounded vs 2522/4385; required 5/5 rejected, 0/5 accepted')

    def test_actual_byte_limit_rejects_a_larger_written_row(self):
        # Inflate a referenced record's serialized size *and physical bytes*.
        # The last record is resident 2600, charged to every row. No plan budget
        # or stored proof may mask the increased on-disk size.
        stream = self.directory/'TRACKS'/'STREAML5RA.BUN'
        size = stream.stat().st_size
        def enlarge(index):
            last = index.sections[-1]
            self.assertEqual(last.number,2600)
            raw = bytearray(last.raw)
            extra = self.report['visibility']['row_byte_margin']+1
            struct.pack_into('<II',raw,24,last.size+extra,last.size+extra)
            index.sections[-1] = Section(bytes(raw))
            with stream.open('ab') as f:
                f.write(Chunk(0,bytes(extra-8)).encode())
            return index.encode()
        try:
            with index_mutation(self.directory,enlarge):
                with self.assertRaisesRegex(FormatError,'row 1319: actual 71680001 bytes exceeds 71680000'):
                    w.check(self.directory)
        finally:
            with stream.open('r+b') as f:
                f.truncate(size)
        print('BROKEN actual row: 71680001 > 71680000; valid 70482144; rejected')


if __name__ == '__main__':
    result = unittest.main(exit=False)
    sys.exit(1 if not result.result.wasSuccessful() else 0 if ASSETS else 3)
