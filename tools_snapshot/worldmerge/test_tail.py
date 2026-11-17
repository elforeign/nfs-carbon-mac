"""Sky proof: baseline 0/1 -> converted 1/1 meshes, 141/141 vertices.

Native controls: 3/3 meshes, 7/7 sky draws, 4/4 buffers, 604/604 vertices.
Stride-40 source: valid 1/1, broken 1/1 rejected; target: same 1/1 and 1/1.
Changed position/normal/colour/UV0/UV1: intact 1/1, broken 5/5 rejected.
Directory: six chunks / three sections; native controls 0. The integrated
writer counts their classified omissions; no target directory is emitted.
Whole X00 acceptance is 1/1 with the integrated empty-material hook.
Dome namespace: source solid/directory 1/1, all 3/3 source LOD references
renamed; native key unchanged (one-LOD broken-pair proof in test_c1_world).
Archives are read-only; missing private assets exits 3.
"""
import argparse
from collections import Counter
from contextlib import contextmanager
import hashlib
import math
from pathlib import Path
import struct
import sys
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import classify
import convert
import tail
import validate
from formats import Chunk, FormatError
from merge import DEFAULT_MW, DEFAULT_CARBON, load_index, read_section

MW, CARBON = DEFAULT_MW, DEFAULT_CARBON
EXPECTED = ((0, 0, 2, 0, 0, 0), (0, 12, 2, 0, 3, 0),
            (0, 24, 4, 0, 10, 0), (0, 28, 1, 0, 5, 0),
            (0, 36, 1, 0, 5, 1))
# Pin only the predecessor guard, not a whole file or repository history.
BASELINE_GUARD = "require(effect in EFFECTS, f'undecoded source effect {effect}')\n"
BASELINE_SHA256 = '65297b15b2f5ae50c81ee04609602640ce0a67405a606ffce4feff0355bf3995'


class CheckError(ValueError):
    pass


def demand(condition, message):
    if not condition:
        raise CheckError(message)


def word(raw, offset):
    return struct.unpack_from('<I', raw, offset)[0]


def envelopes(data, base=0):
    """Independent envelope reader, used for both inventories and readback."""
    off = 0
    while off < len(data):
        demand(off + 8 <= len(data), 'short envelope')
        kind, size = struct.unpack_from('<II', data, off)
        demand(off + 8 + size <= len(data), 'envelope extent')
        yield Chunk(kind, data[off + 8:off + 8 + size], base + off)
        off += 8 + size


def body(c, alignment=16):
    pad = (-(c.offset + 8)) % alignment
    demand(pad <= len(c.payload) and c.payload[:pad] == bytes([17]) * pad, 'filler')
    return c.payload[pad:]


def walk(data, base=0):
    for c in envelopes(data, base):
        yield c
        if c.kind & 0x80000000:
            yield from walk(c.payload, c.offset + 8)


def mesh_data(mesh, target):
    parts = list(envelopes(mesh.payload, mesh.offset + 8))
    def one(kind):
        found = [p for p in parts if p.kind == kind]
        demand(len(found) == 1, 'mesh singleton')
        return body(found[0])
    width = 144 if target else 104
    head, raw, ib = (one(k) for k in (0x134900, 0x134b02, 0x134b03))
    demand(len(head) == (52 if target else 48), 'mesh header')
    demand(len(raw) == width * word(head, 16), 'material extent')
    rows = [raw[p:p + width] for p in range(0, len(raw), width)]
    ni = word(head, 44)
    demand(len(ib) == (ni * 2 + 3) // 4 * 4 and not any(ib[ni * 2:]), 'indices')
    indices = struct.unpack_from(f'<{ni}H', ib)
    groups = []
    for row in rows:
        effect = word(row, 48)
        if not groups or effect != groups[-1][0]:
            groups.append((effect, []))
        groups[-1][1].append(row)
    buffers = [body(p, 16 if target else 128) for p in parts if p.kind == 0x134b01]
    demand(len(groups) == len(buffers) == word(head, 24), 'effect groups')
    demand(sum(p.kind == 0x134c02 for p in parts) == len(rows), 'material names')
    return list(zip(groups, buffers)), indices


def decoded(raw, stride=44):
    demand(len(raw) % stride == 0 and stride in (36, 44), 'vertex extent')
    fmt = '<6fI4f' if stride == 44 else '<6fI2f'
    values = list(struct.iter_unpack(fmt, raw))
    demand(all(math.isfinite(v) for row in values for v in (*row[:6], *row[7:])),
           'non-finite element')
    return [(r[:3], r[3:6], r[6], r[7:9], r[9:]) for r in values]


def same_vertices(source, target):
    demand(decoded(source) == decoded(target), 'decoded elements differ')


def check_target(mesh):
    """Target mesh reads: 52-byte header, 144-byte materials, 16-aligned VBs.

    The declaration builder independently fixes sky's stride at 44; the other
    declaration in these native control meshes is ordinary diffuse (36).
    """
    groups, indices = mesh_data(mesh, True)
    counts = Counter(meshes=1)
    covered = 0
    for (effect, rows), vb in groups:
        demand(effect in (0, 15), 'checker effect')
        stride = 44 if effect == 15 else 36
        demand(len(vb) == sum(word(r, 64) for r in rows) * stride, 'vertex stride/count')
        vertices = decoded(vb, stride)
        used = 0
        for row in rows:
            nv, triangles, first, size = (word(row, p) for p in (64, 96, 100, 124))
            demand(first == covered and size == triangles * 3 and size > 0, 'draw coverage')
            q = indices[first:first + size]
            demand(len(q) == size and min(q) >= used and max(q) < used + nv, 'draw range')
            used += nv
            covered += size
        demand(used == len(vertices), 'vertex count')
        if effect == 15:
            counts.update(draws=len(rows), buffers=1, vertices=used)
    demand(covered == len(indices), 'index coverage')
    return counts


def image_reader(path):
    """Map only file-backed PE sections, without an optional PE dependency."""
    data = path.read_bytes()
    pe = word(data, 60)
    demand(data[:2] == b'MZ' and data[pe:pe + 4] == b'PE\0\0', 'PE image')
    base = word(data, pe + 52)
    n = struct.unpack_from('<H', data, pe + 6)[0]
    size = struct.unpack_from('<H', data, pe + 20)[0]
    sections = [struct.unpack_from('<IIII', data, pe + 24 + size + i * 40 + 8)
                for i in range(n)]
    def read(address, count):
        rva = address - base
        for _, va, length, offset in sections:
            if va <= rva and rva + count <= va + length:
                return data[offset + rva - va:offset + rva - va + count]
        raise CheckError('unmapped image address')
    return read


def declaration(read, table, effect, types, sizes, usages, indices):
    """Reproduce the decoded builder, deriving offsets from its size table."""
    elements, offset = [], 0
    for slot in range(16):
        kind, semantic = struct.unpack('<II', read(table + effect * 144 + 4 + slot * 8, 8))
        if kind == 8:
            return tuple(elements), offset
        dtype = read(types + kind * 4, 1)[0]
        usage = read(usages + semantic * 4, 1)[0]
        index = read(indices + semantic, 1)[0]
        elements.append((0, offset, dtype, 0, usage, index))
        offset += struct.unpack('<I', read(sizes + kind * 4, 4))[0]
    raise CheckError('unterminated declaration')


@contextmanager
def installed():
    """Only test-time hooks; unrelated effects still use the existing writer."""
    original = convert.convert_vertices
    def vertices(raw, effect, count):
        return tail.convert_vertices(raw, effect, count) if effect == 19 else original(raw, effect, count)
    with patch.dict(convert.EFFECTS, tail.EFFECTS), \
         patch.dict(convert.TARGET_STRIDES, tail.TARGET_STRIDES), \
         patch.dict(validate.STRIDES, tail.TARGET_STRIDES), \
         patch.object(convert, 'convert_vertices', vertices):
        yield


class SyntheticTests(unittest.TestCase):
    def test_finite_elements_and_extent(self):
        raw = struct.pack('<6fI4f', 1, 2, 3, 0, 0, 1, 0xff203040, .25, .75, 2, 3)
        self.assertEqual(tail.convert_vertices(raw, 19, 1), raw)
        for offset in (0, 12, 28, 36, 40):
            broken = bytearray(raw)
            struct.pack_into('<f', broken, offset, float('nan'))
            with self.assertRaisesRegex(FormatError, 'non-finite'):
                tail.convert_vertices(broken, 19, 1)
        for bad, effect, count in ((raw[:40], 19, 1), (raw, 19, 2), (raw, 0, 1), (raw, 19, -1)):
            with self.assertRaises(FormatError):
                tail.convert_vertices(bad, effect, count)


class AssetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        wanted = [MW / 'L2RA.BUN', MW / 'STREAML2RA.BUN', MW.parent / 'speed.exe',
                  CARBON / 'L5RA.BUN', CARBON / 'STREAML5RA.BUN', CARBON.parent / 'NFSC.exe']
        if not all(p.is_file() for p in wanted):
            raise unittest.SkipTest('private assets absent')
        cls.source, cls.native, cls.directories = [], [], []
        cls.native_directories = 0
        for root, base, width, effect in ((MW, 'L2RA', 104, 19), (CARBON, 'L5RA', 144, 15)):
            idx, stream, _ = load_index(root, base)
            if base == 'L5RA':
                cls.native_sections = len(idx.sections)
            for section in idx.sections:
                raw = read_section(stream, section)
                solid = None
                if base == 'L2RA' and section.number == 2400:
                    cls.x00 = (section, raw)
                for c in walk(raw):
                    if c.kind == 0x80134010:
                        solid = c
                    if c.kind == 0xb0300100:
                        if base == 'L2RA':
                            cls.directories.append((section.name, c))
                        else:
                            cls.native_directories += 1
                    if c.kind != 0x80134100:
                        continue
                    rows = body(next(p for p in envelopes(c.payload, c.offset + 8) if p.kind == 0x134b02))
                    demand(len(rows) % width == 0, 'inventory material extent')
                    if any(word(rows, p + 48) == effect for p in range(0, len(rows), width)):
                        (cls.source if base == 'L2RA' else cls.native).append(c)
                        if base == 'L2RA':
                            demand(solid is not None, 'sky solid parent')
                            cls.source_solid = solid
        demand(len(cls.source) == 1, 'source sky mesh count')
        groups, _ = mesh_data(cls.source[0], False)
        demand(len(groups) == 1 and groups[0][0][0] == 19, 'source sky groups')
        cls.vertices = groups[0][1]

    def test_declarations_from_images(self):
        source = declaration(image_reader(MW.parent / 'speed.exe'), 0x8f9b60, 19,
                             0x8fad28, 0x8fad7c, 0x8fad48, 0x8fad70)
        target = declaration(image_reader(CARBON.parent / 'NFSC.exe'), 0xa64008, 15,
                             0xa650ec, 0xa65180, 0xa65110, 0xa65168)
        self.assertEqual(source, (EXPECTED, 44))
        self.assertEqual(target, source)
        self.assertEqual(tail.SKY_DECLARATION, EXPECTED)
        self.assertEqual(tail.EFFECTS, {19: (44, 15, 44)})
        self.assertEqual(tail.TARGET_STRIDES, {15: 44})

    def test_inventory_and_native_controls(self):
        self.assertEqual((self.native_sections, self.native_directories), (962, 0))
        self.assertEqual(Counter(n for n, _ in self.directories), {'Y00': 4, 'I60': 1, 'P66': 1})
        for _, directory in self.directories:
            self.assertEqual([p.kind for p in envelopes(directory.payload, directory.offset + 8)],
                             [0x30300101, 0x30300102, 0x30300103])
        controls = sum((check_target(mesh) for mesh in self.native), Counter())
        self.assertEqual(controls, {'meshes': 3, 'draws': 7, 'buffers': 4, 'vertices': 604})
        print('NATIVE: 962 sections; directory controls=0; sky meshes/draws/buffers/vertices=3/7/4/604')

    def test_baseline_and_mesh_readback(self):
        self.assertEqual(hashlib.sha256(BASELINE_GUARD.encode()).hexdigest(), BASELINE_SHA256)
        with self.assertRaisesRegex(FormatError, 'undecoded source effect 19'):
            exec(BASELINE_GUARD, {'require': convert.require, 'effect': 19, 'EFFECTS': {0, 1, 3, 5, 6}})
        predecessor = {k: v for k, v in convert.EFFECTS.items() if k != 19}
        with patch.object(convert, 'EFFECTS', predecessor):
            with self.assertRaisesRegex(FormatError, 'undecoded source effect 19'):
                convert.convert_mesh(self.source[0], 0, convert.Stats())
        stats = convert.Stats()
        with installed():
            mesh, = envelopes(convert.convert_mesh(self.source[0], 0, stats))
        self.assertEqual(check_target(mesh), {'meshes': 1, 'draws': 1, 'buffers': 1, 'vertices': 141})
        groups, _ = mesh_data(mesh, True)
        target = groups[0][1]
        self.assertEqual(groups[0][0][0], 15)
        self.assertEqual((stats.draws, stats.vertices, stats.effects), (1, 141, {'19->15': 1}))
        same_vertices(self.vertices, target)
        self.assertEqual(tail.convert_vertices(target, 19, 141), self.vertices)
        for offset in (0, 12, 24, 28, 36):
            broken = bytearray(target)
            broken[offset] ^= 1
            with self.assertRaisesRegex(CheckError, 'decoded elements differ'):
                same_vertices(self.vertices, broken)
        print('SKY: baseline=0/1; mesh readback=1/1; vertices=141/141; element mutants=5/5 rejected')

    def test_target_validator_hook_on_sky_resource_fragment(self):
        # A single-solid list isolates this hook from unrelated empty meshes in
        # X00. This fragment is not counted as whole-section acceptance.
        sh = next(c for c in envelopes(self.source_solid.payload, self.source_solid.offset + 8)
                  if c.kind == 0x134011)
        key = 0x1f389568
        self.assertEqual(word(body(sh), 16), 0xed85ba82)
        info = bytearray(144)
        struct.pack_into('<II', info, 8, 29, 1)
        header = (Chunk(0x134002, info).encode() +
                  Chunk(0x134003, struct.pack('<II', key, 0)).encode() +
                  Chunk(0x80134008, b'').encode())
        out, stats = convert.Builder(8), convert.Stats()
        out.pad(16)
        out.add(0x80134001, header)
        with installed():
            out.data += convert.convert_solid(self.source_solid, out.position, stats)
        fragment = Chunk(0x80134000, bytes(out.data)).encode()
        predecessor = {k: v for k, v in validate.STRIDES.items() if k != 15}
        with patch.object(validate, 'STRIDES', predecessor):
            with self.assertRaisesRegex(FormatError, 'target effect declaration not decoded'):
                validate.validate_resources(fragment, 2400)
        with installed():
            counts, _ = validate.validate_resources(fragment, 2400)
        self.assertEqual((counts['solids'], counts['draws'], counts['vertices']), (1, 1, 141))
        self.assertEqual(counts['triangles'], stats.triangles)

    def test_dome_namespace_and_all_source_lods(self):
        source, stream, _ = load_index(MW, 'L2RA')
        native, native_stream, _ = load_index(CARBON, 'L5RA')
        keys = {word(body(c), 16) for idx, path in ((source, stream), (native, native_stream))
                for section in idx.sections for c in walk(read_section(path, section))
                if c.kind == 0x134011}
        self.assertNotIn(0x1f389568, keys)
        section, raw = self.x00
        converted, _ = convert.convert_section(raw, section.number)
        headers = [word(body(c), 16) for c in walk(converted) if c.kind == 0x134011]
        self.assertIn(0x1f389568, headers)
        self.assertNotIn(0xed85ba82, headers)
        directories = [key for c in walk(converted) if c.kind == 0x134003
                       for key, _ in struct.iter_unpack('<II', c.payload)]
        self.assertEqual(directories, headers)
        dome = next(c for c in walk(converted) if c.kind == 0x80134010 and
                    word(body(next(p for p in envelopes(c.payload,c.offset+8)
                                   if p.kind == 0x134011)),16) == 0x1f389568)
        mesh = next(c for c in envelopes(dome.payload,dome.offset+8) if c.kind == 0x80134100)
        groups, _ = mesh_data(mesh, True)
        self.assertEqual([(g[0][0],len(g[1])) for g in groups], [(15,6204)])
        same_vertices(self.vertices, groups[0][1])
        references = 0
        for section in source.sections:
            for root in envelopes(read_section(stream, section)):
                if root.kind != 0x80034100:
                    continue
                old = next(c.payload for c in envelopes(root.payload, root.offset+8) if c.kind == 0x34102)
                written = convert.convert_scenery(root, 0, section.number, stats=convert.Stats())
                scene, = envelopes(written)
                new = next(c.payload for c in envelopes(scene.payload, 8) if c.kind == 0x34102)
                for p in range(0, len(old), 72):
                    for off in (24, 28, 32, 36):
                        key = word(old, p+off)
                        self.assertEqual(word(new, p+off), 0x1f389568 if key == 0xed85ba82 else key)
                        references += key == 0xed85ba82
        self.assertEqual(references, 3)
        native_x00 = next(s for s in native.sections if s.number == 2400)
        native_sky = [c for c in walk(read_section(native_stream, native_x00))
                      if c.kind == 0x134011 and word(body(c), 16) == 0xed85ba82]
        self.assertEqual(len(native_sky), 1)
        print(f'DOME source solid/directory=1/1; namespaced LOD references={references}; native key unchanged')

    def test_stride_40_rejected_on_source_and_target(self):
        shortened = b''.join(self.vertices[p:p + 40] for p in range(0, len(self.vertices), 44))
        self.assertEqual(len(shortened), 141 * 40)
        with self.assertRaisesRegex(FormatError, 'stride mismatch'):
            tail.convert_vertices(shortened, 19, 141)
        with installed():
            with patch.dict(convert.EFFECTS, {19: (40, 15, 44)}):
                with self.assertRaisesRegex(FormatError, 'source group vertex size'):
                    convert.convert_mesh(self.source[0], 0, convert.Stats())
            mesh, = envelopes(convert.convert_mesh(self.source[0], 0, convert.Stats()))
        check_target(mesh)
        parts = []
        for p in envelopes(mesh.payload, mesh.offset + 8):
            if p.kind == 0x134b01:
                pad = -(p.offset + 8) % 16
                p = Chunk(p.kind, p.payload[:pad] + shortened)
            parts.append(p.encode())
        broken, = envelopes(Chunk(mesh.kind, b''.join(parts)).encode())
        with self.assertRaisesRegex(CheckError, 'vertex stride/count'):
            check_target(broken)
        print('STRIDE: source and target valid=1/1 each; stride40 rejected=1/1 each; bad source table=1/1 rejected')

    def test_census_effect_hook_keeps_other_blockers(self):
        section, raw = self.x00
        predecessor = {k: v for k, v in convert.EFFECTS.items() if k != 19}
        with patch.object(convert, 'EFFECTS', predecessor):
            before = classify.section_census(raw, section)
        self.assertEqual(before['blockers'], ['effect:19', 'layout:44'])
        with installed():
            after = classify.section_census(raw, section)
        self.assertEqual(after['blockers'], [])
        self.assertTrue(after['conversion']['success'])
        print('X00: effect/layout blockers 2->0; integrated empty mesh support; section acceptance=1/1')


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--mw', type=Path, default=DEFAULT_MW)
    ap.add_argument('--carbon', type=Path, default=DEFAULT_CARBON)
    args, rest = ap.parse_known_args()
    MW, CARBON = args.mw, args.carbon
    result = unittest.main(argv=[sys.argv[0], *rest], exit=False, verbosity=2).result
    if not result.wasSuccessful():
        raise SystemExit(1)
    if result.skipped:
        raise SystemExit(3)
    print('TAIL PASS: sky declaration and mesh proved; integrated writer counts animation omissions')
