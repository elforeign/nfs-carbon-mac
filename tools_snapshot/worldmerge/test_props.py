"""Scenery physics acceptance, with four rejected controls (0/4 accepted).

Valid: 13,484 rows / 195 owners (max 242), 263 bounds, 133 hierarchies,
0 newly misbound overrides, 5 preserved source bounds holes. Zones off/on
must agree. Native bridge output: 12,702 unchanged rows, SHA-256 pinned
from a stored pre-change fixture, independently of git history.
Broken controls: count 0 versus payload count; 262/263 shapes; 1 wrong
override selector (valid 0); one untranslated XYZ (valid 0 m error).
"""
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0,str(HERE))
import props as p
import c1_world as w
from formats import Chunk, FormatError, chunks, u32
from merge import PARENT, load_index, read_section

NATIVE_SHA256 = '495cbdf8f5eb413178292dad27d8fa96b8420ee97783e73bf2d76e190e366ffd'
ASSETS = all((root/name).is_file() for root,base in ((w.DEFAULT_MW,'L2RA'),(w.DEFAULT_CARBON,'L5RA'))
             for name in (base+'.BUN','STREAM'+base+'.BUN'))


@contextmanager
def changed_bytes(path, offset, raw):
    with path.open('r+b') as f:
        f.seek(offset)
        original = f.read(len(raw))
        f.seek(offset)
        f.write(raw)
    try:
        yield
    finally:
        with path.open('r+b') as f:
            f.seek(offset)
            f.write(original)


class Layout(unittest.TestCase):
    def test_count_moves_to_short_at_ten(self):
        raw = bytearray(80)
        struct.pack_into('<IIHH',raw,0,11,11,236,1)
        # Absolute payload alignment uses 0x11 filler, never zeros.
        chunk = Chunk(p.SPAWNS,b'\x11'*8+bytes(raw),0)
        self.assertEqual(len(p.spawn_data(chunk,native=True)[1]),1)
        old = bytearray(raw)
        struct.pack_into('<HI',old,10,0,1)
        with self.assertRaisesRegex(FormatError,'count/payload'):
            p.spawn_data(Chunk(chunk.kind,b'\x11'*8+old,0),native=True)

    def test_first_bounds_collection_wins(self):
        out = w.convert.Builder(8)
        first = struct.pack('<4I',123,1,0,0)+bytes(64)
        second = struct.pack('<4I',123,2,0,0)+bytes(112)
        out.add(0x3b901,first,16)
        out.add(0x3b901,second,16)
        index = SimpleNamespace(parts=[Chunk(p.BOUNDS,bytes(out.data),0)])
        self.assertEqual(p.collections(index,p.BOUNDS)[123],(0x3b901,first))
        index.parts = [Chunk(p.BOUNDS,Chunk(0,b'').encode()+bytes(out.data),0)]
        with self.assertRaisesRegex(FormatError,'unexpected prop collection child'):
            p.collections(index,p.BOUNDS)

    def test_hierarchy_namespace_keeps_first_child_mesh_identity(self):
        key = 0x3393b8e2
        raw = struct.pack('<6I',key,1,0x9756df79,key,0,0x0101ff00)
        importer = object.__new__(p.Import)
        importer.native = SimpleNamespace(parts=[])
        importer.hierarchies = {key:(0x3410c,raw)}
        importer.requested_hierarchies = {key}
        result = importer.global_chunk(p.HIERARCHIES,0)
        copied = p.collections(SimpleNamespace(parts=[result]),p.HIERARCHIES)[p.HIERARCHY_KEYS[key]][1]
        self.assertEqual(u32(copied),p.HIERARCHY_KEYS[key])
        self.assertEqual(copied[4:],raw[4:])

    def test_sparse_reader_preserves_offsets_and_rejects_crossing_chunks(self):
        ignored = Chunk(0x80134000,bytes(512)).encode()
        selected = Chunk(p.SCENE,b'scenery').encode()
        raw = ignored+selected
        index = SimpleNamespace(sections=[SimpleNamespace(number=276,offset=0,size=len(raw))])
        with tempfile.TemporaryDirectory() as temp:
            stream = Path(temp)/'stream'
            stream.write_bytes(raw)
            self.assertEqual(list(p._roots(index,stream)),[(276,Chunk(p.SCENE,b'scenery',len(ignored)))])
            stream.write_bytes(struct.pack('<II',p.SCENE,len(raw))+bytes(len(raw)-8))
            with self.assertRaisesRegex(FormatError,'crosses section'):
                list(p._roots(index,stream))
            index.sections[0].size = (256 << 20)+1
            with self.assertRaisesRegex(FormatError,'size budget'):
                list(p._roots(index,stream))

    def test_classified_namespaces_are_distinct(self):
        self.assertEqual(len(p.BOUND_KEYS),3)
        self.assertEqual(len(p.HIERARCHY_KEYS),1)
        self.assertFalse(set(p.BOUND_KEYS)&set(p.BOUND_KEYS.values()))
        self.assertEqual(len(set(p.BOUND_KEYS.values())),3)


@unittest.skipUnless(ASSETS,'private track archives absent')
class Archives(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='props-test-')
        cls.addClassCleanup(cls.temp.cleanup)
        cls.root = Path(cls.temp.name)
        cls.source,cls.ms,_ = load_index(w.DEFAULT_MW,'L2RA')
        cls.native,cls.cs,_ = load_index(w.DEFAULT_CARBON,'L5RA')
        cls.outputs = []
        for zones in (False,True):
            stage = cls.root/str(zones)
            stage.mkdir()
            w._write_pair(w.DEFAULT_MW,w.DEFAULT_CARBON,stage,zones=zones,
                          shift=w.c3_crossing.SHIFT,_link=False)
            index,stream,_ = load_index(stage/'TRACKS','L5RA')
            scenes = {}
            for s in index.sections:
                for root in chunks(read_section(stream,s)):
                    if root.kind == w.SCENE:
                        scene = w.scene_data(root)
                        scenes[scene.number] = s.number,scene
            native_numbers = w.numbers.source_numbers(w.numbers.inventory((cls.native,cls.cs),True))
            mapping,_,_ = w._recover_mapping(cls.source,cls.ms,scenes,native_numbers,
                                             (w.c3_crossing.SHIFT[1],-w.c3_crossing.SHIFT[0]))
            cls.outputs.append((stage,mapping))
        cls.stage,cls.mapping = cls.outputs[0]

    def checked(self, stage=None, mapping=None):
        index,stream,_ = load_index((stage or self.stage)/'TRACKS','L5RA')
        with patch.object(p,'Import',side_effect=AssertionError('checker used writer')), \
             patch.object(p,'models',side_effect=AssertionError('checker used model writer')):
            return p.check(index,stream,self.source,self.ms,self.native,self.cs,
                           mapping=mapping or self.mapping,shift=w.c3_crossing.SHIFT)

    def target(self):
        index,stream,_ = load_index(self.stage/'TRACKS','L5RA')
        for s in index.sections:
            for root in chunks(read_section(stream,s)):
                if root.kind == p.SPAWNS:
                    logical,rows = p.spawn_data(root,native=True)
                    if logical == 236:
                        for i,row in enumerate(rows):
                            if u32(row,40) == 20407+8903:
                                return stream,s.offset+root.offset+8+(-(root.offset+8)%16),i,row
        self.fail('target pylon spawn absent')

    def test_z_acceptance_zones_off_and_on_and_native_fixture(self):
        results = [self.checked(stage,mapping) for stage,mapping in self.outputs]
        self.assertEqual(results[0],results[1])
        r = results[0]
        self.assertEqual([r[k] for k in ('rows','owners','largest_owner','shapes','hierarchies',
                                         'newly_misbound_overrides','source_bounds_holes')],
                         [13484,195,242,263,133,0,5])
        self.assertEqual(r['pylon'],dict(stream=276,scene=236,instance=149,bounds='2D5373CD',override=29310))
        fixture = PARENT/'.runs'/'c3_owner_build'/'c3route-open'/'TRACKS'
        if fixture.is_dir():
            index,stream,_ = load_index(fixture,'L5RA')
            stored = p.check_native(index,stream,self.native,self.cs,removed=(18842,))
            self.assertEqual(stored,dict(native_rows=12702,native_sha256=NATIVE_SHA256))
        import c3_link
        for stage,_ in self.outputs:
            c3_link.apply(stage/'TRACKS')
            index,stream,_ = load_index(stage/'TRACKS','L5RA')
            native = p.check_native(index,stream,self.native,self.cs,removed=(18842,))
            self.assertEqual(native,dict(native_rows=12702,native_sha256=NATIVE_SHA256))
        print('props zones off/on: 13484 rows, 263 shapes, 133 hierarchies, 0 misbound; '
              'native 12702 SHA256 '+NATIVE_SHA256)

    def test_old_count_offset_control(self):
        stream,header,_,_ = self.target()
        with stream.open('rb') as f:
            f.seek(header+10)
            count = struct.unpack('<H',f.read(2))[0]
        with changed_bytes(stream,header+10,struct.pack('<HI',0,count)):
            with self.assertRaisesRegex(FormatError,'count/payload'):
                self.checked()
        print(f'old count control: 0/{count} rows, rejected 1/1')

    def test_missing_shape_control(self):
        path = self.stage/'TRACKS'/'L5RA.BUN'
        index,_,_ = load_index(path.parent,'L5RA')
        root = p.one(index.parts,p.BOUNDS)
        bound = next(c for c in chunks(root.payload,root.offset+8)
                     if c.kind and u32(w.convert.aligned_payload(c)) == 0x2d5373cd)
        at = bound.offset+8+(-(bound.offset+8)%16)
        with changed_bytes(path,at,bytes(4)):
            with self.assertRaisesRegex(FormatError,'shape/hierarchy completeness'):
                self.checked()
        print('missing shape control: 262/263 imported keys, rejected 1/1')

    def test_override_rebase_control(self):
        path = self.stage/'TRACKS'/'L5RA.BUN'
        index,_,_ = load_index(path.parent,'L5RA')
        root = p.one(index.parts,p.OVERRIDES)
        at = root.offset+8+(20407+8903)*6+2
        with changed_bytes(path,at,struct.pack('<H',150)):
            with self.assertRaisesRegex(FormatError,'override rebase'):
                self.checked()
        print('override control: 1 misbound selector (149 -> 150), rejected 1/1')

    def test_xyz_translation_control(self):
        stream,header,i,row = self.target()
        before = struct.unpack_from('<3f',row,16)
        raw = struct.pack('<3f',before[0],before[1],before[2]-8192)
        with changed_bytes(stream,header+16+i*64+16,raw):
            with self.assertRaisesRegex(FormatError,'XYZ translation'):
                self.checked()
        print('XYZ control: 8192 m translation missing (valid 0), rejected 1/1')


if __name__ == '__main__':
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(1 if not result.wasSuccessful() else 0 if ASSETS else 3)
