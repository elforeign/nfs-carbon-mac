"""Reference-only proof: integrated hooks accept 720/720; X00 closes 136/146 slots.

Native control: 4/40809 empty meshes, 9/962 sections without local solids.
MW controls: 19/19 empty meshes emitted, 15/15 affected sections accepted.
All 19 MW and 4 native empty solids use the same float-limit sentinel;
the integrated validator accepts the empty case and keeps populated bounds strict.
Closed synthetic scenery: 1/1 accepted; vertices without materials, missing
solid and dropped instance list: 1/1 rejected each. Deliberately bypassing the
three guards makes those same broken variants pass (3/3 detected mutations).
Archive closure: X00 absent/present = 0/146 -> 136/146 referenced slots.
Missing private archives exits 3. No archive writes.
"""
from collections import Counter, defaultdict
import argparse
import inspect
from pathlib import Path
import struct
import sys
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import classify
import convert
import refonly
import validate
from formats import Chunk, FormatError, chunks, require, u32
from merge import DEFAULT_MW, DEFAULT_CARBON, load_index, read_section

ASSETS = all((root / name).is_file() for root, names in (
    (DEFAULT_MW, ('L2RA.BUN', 'STREAML2RA.BUN')),
    (DEFAULT_CARBON, ('L5RA.BUN', 'STREAML5RA.BUN')))
    for name in names)
CENSUS_OUT = None


def children(c):
    return chunks(c.payload, c.offset + 8)


def one(parts, kind):
    found = [c for c in parts if c.kind == kind]
    require(len(found) == 1, 'proof singleton')
    return found[0]


def body(c, alignment=16):
    pad = -(c.offset + 8) % alignment
    require(c.payload[:pad] == b'\x11' * pad, 'proof filler')
    return c.payload[pad:]


def inventory(raw):
    """Read solid headers and reconcile their keys with the source directory."""
    solids, scenes, meshes = [], [], []
    for root in chunks(raw):
        if root.kind == 0x80034100:
            scenes.append(root)
        elif root.kind == 0x80134000:
            parts = children(root)
            table = one(children(one(parts, 0x80134001)), 0x134003).payload
            expected = [row[0] for row in struct.iter_unpack('<II', table)]
            actual = []
            for solid in parts:
                if solid.kind != 0x80134010:
                    continue
                sp = children(solid)
                actual.append(u32(body(one(sp, 0x134011)), 16))
                meshes.append(one(sp, 0x80134100))
            require(actual == expected, 'proof solid directory/header keys')
            solids.extend(actual)
    return solids, scenes, meshes


def empty_bounds(raw):
    result = []
    for root in chunks(raw):
        if root.kind != 0x80134000:
            continue
        for solid in children(root):
            if solid.kind != 0x80134010:
                continue
            parts = children(solid)
            mesh = one(parts, 0x80134100)
            if u32(body(one(children(mesh), 0x134900)), 16) == 0:
                header = body(one(parts, 0x134011))
                result.append((struct.unpack_from('<3f', header, 32),
                               struct.unpack_from('<3f', header, 48)))
    return result


def references(raw, target=False):
    slots, instances, placeholders = Counter(), 0, 0
    stride, selector = (96, 84) if target else (64, 62)
    for scene in (c for c in chunks(raw) if c.kind == 0x80034100):
        parts = children(scene)
        models = one(parts, 0x34102).payload
        rows = body(one(parts, 0x34103))
        require(len(models) % 72 == 0 and len(rows) % stride == 0, 'proof scene extents')
        for off in range(0, len(rows), stride):
            index = struct.unpack_from('<h', rows, off + selector)[0]
            require(0 <= index < len(models) // 72, 'proof model selector')
            keys = [u32(models, index * 72 + k) for k in (24, 28, 32, 36)
                    if u32(models, index * 72 + k) not in (0, 0xbe43edbb, 0x90f70174)]
            slots.update(keys)
            placeholders += not keys
            instances += 1
    return slots, instances, placeholders


def adapted(fn, old, new, **extra):
    """Clone a live function with one exact, asserted test-only hook replacement."""
    source = inspect.getsource(fn)
    require(source.count(old) == 1, f'proof call site changed: {fn.__name__}')
    env = dict(fn.__globals__, **extra)
    exec(compile(source.replace(old, new), fn.__code__.co_filename, 'exec'), env)
    return env[fn.__name__]


def empty_mesh(*, vertices=False, indices=False):
    out = convert.Builder(8)
    head = bytearray(48)
    struct.pack_into('<I', head, 8, 18)
    if vertices:
        struct.pack_into('<I', head, 24, 1)
    if indices:
        struct.pack_into('<I', head, 44, 3)
    out.add(0x134900, head, 16)
    out.add(0x134b02, b'', 16)
    out.add(0x134b03, bytes(8) if indices else b'', 16)
    if vertices:
        out.add(0x134b01, bytes(108), 128)
    return Chunk(0x80134100, bytes(out.data))


def scene_fixture(key=1234):
    from test_scenery2 import fixture
    scene = next(c for c in chunks(fixture((101,))) if c.kind == 0x80034100)
    # Both root positions are 128-aligned, so leaf alignment is unchanged.
    raw = bytearray(scene.encode())
    model = one(children(scene), 0x34102)
    struct.pack_into('<I', raw, model.offset - scene.offset + 8 + 24, key)
    return bytes(raw)


def target_scene(source):
    scene = one(chunks(source), 0x80034100)
    stats = convert.Stats()
    target = convert.convert_scenery(scene, 0, 101, 0, stats)
    return target, stats


class SyntheticTests(unittest.TestCase):
    def test_empty_native_shape_and_alignment(self):
        for position in (0, 8, 120, 128):
            raw = refonly.convert_empty_mesh(empty_mesh(), position, convert.Stats())
            mesh = chunks(raw, position)[0]
            ps = children(mesh)
            self.assertEqual([p.kind for p in ps], [0x134900, 0x134b02, 0x134b03])
            self.assertEqual(body(ps[0]), body(one(children(empty_mesh()), 0x134900)) + bytes(4))
            self.assertEqual([body(p) for p in ps[1:]], [b'', b''])

    def test_materials_removed_but_payload_kept(self):
        for variant, message in ((empty_mesh(vertices=True), 'vertices without materials'),
                                 (empty_mesh(indices=True), 'indices without materials')):
            with self.assertRaisesRegex(FormatError, message):
                refonly.convert_empty_mesh(variant, 0, convert.Stats())

    def test_unknown_or_nonempty_mesh_refused(self):
        mesh = empty_mesh()
        with self.assertRaisesRegex(FormatError, 'undecoded mesh child'):
            refonly.convert_empty_mesh(Chunk(mesh.kind, mesh.payload + Chunk(123, b'').encode()),
                                      0, convert.Stats())
        from test_scenery2 import fixture
        ordinary = inventory(fixture((101,)))[2][0]
        with self.assertRaisesRegex(FormatError, 'zero source materials'):
            refonly.convert_empty_mesh(ordinary, 0, convert.Stats())

    def test_closed_scene_and_missing_provider(self):
        raw = scene_fixture()
        target, stats = target_scene(raw)
        refonly.require_section_geometry(raw, target, stats, {1234: {77}}, {77})
        for providers, accepted in (({}, {77}), ({1234: {78}}, {77})):
            with self.assertRaisesRegex(FormatError, 'unresolved solids: 000004d2'):
                refonly.require_section_geometry(raw, target, stats, providers, accepted)
        generated, counts = convert.convert_section(raw, 101, 0, source_number=101,
                                                    providers=({1234: {77}}, {77}))
        self.assertEqual(generated, target)
        self.assertEqual(counts.instances, 1)

    def test_instance_without_a_solid_key_refused(self):
        raw = scene_fixture(0)
        target, stats = target_scene(raw)
        with self.assertRaisesRegex(FormatError, 'instances without a solid key: 1'):
            refonly.require_section_geometry(raw, target, stats, {}, set())

    def test_forged_writer_statistics_cannot_bypass_closure(self):
        raw = scene_fixture()
        target, stats = target_scene(raw)
        stats.solids = 1
        with self.assertRaisesRegex(FormatError, 'unexpected local solids'):
            refonly.require_section_geometry(raw, target, stats, {}, set())

    def test_dropped_instances_refused_even_with_forged_stats(self):
        source = scene_fixture()
        target, stats = target_scene(source)
        root = one(chunks(target), 0x80034100)
        parts = children(root)
        inst = one(parts, 0x34103)
        # Preserve offsets/filler and remove only the instance record.
        short = Chunk(root.kind, b''.join(Chunk(c.kind, c.payload[:-96] if c is inst
                                              else c.payload).encode() for c in parts)).encode()
        with self.assertRaisesRegex(FormatError, 'instance list changed'):
            refonly.require_section_geometry(source, short, stats, {1234: {77}}, {77})
        dropped = Chunk(root.kind, b''.join(c.encode() for c in parts if c is not inst)).encode()
        with self.assertRaisesRegex(FormatError, 'singleton 00034103'):
            refonly.require_section_geometry(source, dropped, stats, {1234: {77}}, {77})

    def test_guard_mutations_expose_each_broken_variant(self):
        # These are intentionally unsafe gates, exercised by the same controls.
        # A checker which accepted these mutations would miss lost resources.
        # Use a local unsafe writer for this control: blindly erase payloads.
        def erase_payload(c, position, stats):
            return refonly.convert_empty_mesh(empty_mesh(), position, stats)
        self.assertTrue(erase_payload(empty_mesh(vertices=True), 0, convert.Stats()))
        source = scene_fixture()
        target, stats = target_scene(source)
        missing_gate = adapted(refonly.require_section_geometry,
                               "require(not missing, 'refonly unresolved solids: '",
                               "require(True, 'refonly unresolved solids: '")
        self.assertIsNone(missing_gate(source, target, stats, {}, set()))
        # An implementation checking closure only on emitted instances accepts
        # an empty list; the real gate compares against the original source.
        def emitted_only(source, target, stats, providers, accepted):
            wanted, _, _ = references(target, True)
            require(all(set(providers.get(k, ())) & accepted for k in wanted), 'missing')
        root = one(chunks(target), 0x80034100)
        dropped = Chunk(root.kind, b''.join(Chunk(c.kind, c.payload[:-96] if c.kind == 0x34103
                                                else c.payload).encode() for c in children(root))).encode()
        self.assertIsNone(emitted_only(source, dropped, stats, {}, set()))
        print('MUTATIONS: vertices/missing solid/dropped list accepted by unsafe gates=3/3; real gates reject=3/3')


@unittest.skipUnless(ASSETS, 'private track archives absent')
class ArchiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index, cls.stream, cls.index_bytes = load_index(DEFAULT_MW, 'L2RA')
        cls.final_rows, cls.final_summary = classify.classify()
        cls.accepted = {r['number'] for r in cls.final_rows if r['conversion']['success']}
        cls.providers, cls.sources, cls.empty = defaultdict(set), {}, []
        for section in cls.index.sections:
            raw = read_section(cls.stream, section)
            solids, scenes, meshes = inventory(raw)
            for key in solids:
                cls.providers[key].add(section.number)
            for mesh in meshes:
                if u32(body(one(children(mesh), 0x134900)), 16) == 0:
                    cls.empty.append((section.name, mesh))
            if scenes and not solids:
                cls.sources[section.number] = raw
        cls.by_number = {r['number']: r for r in cls.final_rows}
        if CENSUS_OUT is not None:
            classify.write_report(CENSUS_OUT.absolute(), cls.final_rows, cls.final_summary)

    def test_integrated_census_and_shortfall(self):
        self.assertEqual(self.final_summary['converter_successes'], 720)
        self.assertEqual(len(self.empty), 19)
        self.assertEqual(len(self.sources), 10)
        for number in self.sources:
            self.assertTrue(self.by_number[number]['conversion']['success'])
            self.assertFalse(self.by_number[number]['blockers'])
        print('CENSUS: integrated hooks accept 720/720; ten no-local-solid sections preserved')

    def test_native_controls_and_exact_empty_header(self):
        index, stream, _ = load_index(DEFAULT_CARBON, 'L5RA')
        native, no_solids, mesh_count, native_bounds = [], [], 0, []
        for section in index.sections:
            raw = read_section(stream, section)
            solids, scenes, meshes = inventory(raw)
            native_bounds.extend(empty_bounds(raw))
            mesh_count += len(meshes)
            if scenes and not solids:
                no_solids.append(section.name)
            for mesh in meshes:
                ps = children(mesh)
                if u32(body(one(ps, 0x134900)), 16) == 0:
                    self.assertEqual([p.kind for p in ps], [0x134900, 0x134b02, 0x134b03])
                    self.assertEqual([body(p) for p in ps[1:]], [b'', b''])
                    native.append(body(ps[0]))
                    generated = refonly.convert_empty_mesh(empty_mesh(), mesh.offset, convert.Stats())
                    self.assertEqual(generated, mesh.encode())
        self.assertEqual((len(index.sections), mesh_count, len(native), len(no_solids)), (962, 40809, 4, 9))
        self.assertEqual(len(set(native)), 1)
        limit = float.fromhex('0x1.fffffep+127')
        self.assertEqual(native_bounds, [((limit,) * 3, (-limit,) * 3)] * 4)
        for _, mesh in self.empty:
            generated = chunks(refonly.convert_empty_mesh(mesh, 0, convert.Stats()))[0]
            self.assertEqual(body(one(children(generated), 0x134900)), native[0])
        print('NATIVE: empty meshes=4/40809; no-local-solid sections=9/962; MW empty=19/19 match native header')

    def test_source_index_closure_before_and_after(self):
        all_slots, all_instances, empty_rows = Counter(), 0, 0
        for number, source in self.sources.items():
            slots, instances, placeholders = references(source)
            all_slots.update(slots)
            all_instances += instances
            empty_rows += placeholders
            target, _ = convert.convert_section(source, number, 0,
                                                providers=(self.providers, self.accepted))
            slots, instances, placeholders = references(source)
            expected = Counter({0x1f389568 if k == 0xed85ba82 else k: v for k,v in slots.items()})
            self.assertEqual((expected,instances,placeholders), references(target, True))
        before = sum(n for k, n in all_slots.items() if self.providers[k] & (self.accepted - {2400}))
        after = sum(n for k, n in all_slots.items() if self.providers[k] & self.accepted)
        self.assertEqual((before, after, sum(all_slots.values()), all_instances, empty_rows),
                         (0, 136, 146, 39, 1))
        missing_from_index = {k for k in all_slots if not self.providers[k]}
        self.assertEqual(missing_from_index, {0x56b52d28, 0xf390cd1a})
        self.assertTrue(all(self.providers[k] == {2400} for k in all_slots if self.providers[k]))
        print('CLOSURE: X00 closes 136/146 reference-only slots; two absent keys and one sentinel row classified')

    def test_accepted_outputs_keep_empty_solids_and_native_bounds(self):
        newly = {s.number for s in self.index.sections if s.name in {n for n, _ in self.empty}}
        self.assertEqual(len(newly), 15)
        checked = 0
        for section in self.index.sections:
            if section.number not in newly:
                continue
            source = read_section(self.stream, section)
            target, stats = convert.convert_section(source, section.number, 0, source_number=section.number)
            # Each list is sorted independently; the namespace changes one
            # solid's position within its own list, not list concatenation.
            expected_solids = Counter(0x1f389568 if k == 0xed85ba82 else k for k in inventory(source)[0])
            self.assertEqual(expected_solids, Counter(inventory(target)[0]))
            bounds = empty_bounds(source)
            limit = float.fromhex('0x1.fffffep+127')
            self.assertTrue(bounds)
            self.assertEqual(set(bounds), {((limit,) * 3, (-limit,) * 3)})
            self.assertEqual(bounds, empty_bounds(target))
            checker = validate.validate_section if inventory(source)[1] else validate.validate_resources
            checker(target, section.number)
            slots, instances, placeholders = references(source)
            expected = Counter({0x1f389568 if k == 0xed85ba82 else k: v for k,v in slots.items()})
            self.assertEqual((expected,instances,placeholders), references(target, True))
            checked += 1
        self.assertEqual(checked, 15)
        print('OUTPUT: 15/15 sections retain solid keys/instance references/native empty bounds and validate')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--census-out', type=Path)
    args, remaining = parser.parse_known_args()
    CENSUS_OUT = args.census_out
    result = unittest.main(argv=[sys.argv[0]] + remaining, exit=False)
    if not result.result.wasSuccessful():
        sys.exit(1)
    if not ASSETS:
        print('SKIP: private track archives absent')
        sys.exit(3)
