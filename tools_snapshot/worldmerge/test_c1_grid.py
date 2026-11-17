"""Single collision grid proof, independent source inventory and face queries.

Baseline two grids: 167x159 at 96 m + 103x92 at 64 m; 2,412 + 2,779 cells.
One grid: 167x365 = 60,955 slots; 2,412 + 1,753 = 4,165 occupied;
family maxima 60/0/0/88, 0 unresolved; strict grounded 2,522 + 2,319 unchanged,
same node lists, maximum height difference 0 m (tolerance 0.002 m).
Those queries use exact offsets. Rounding shifted node X to float32 changes
the strict grounded list: 2,510 (644 lost / 632 gained). Querying the source
at the same rounded coordinates also gives 2,510, identical lists/heights:
this is node quantisation and strict-ceiling sensitivity, not moved geometry.
Broken: unshifted packs 0/4,385 grounded (correct 2,522); missing offset
17,344/17,344 source family-3 words wrong; duplicate pack id rejected;
64 m / 251x540 = 135,540 slots rejected (>65,536); dropped native cell
4,164 instead of 4,165 rejected. Each is a serialized, otherwise valid mutant.
Private inputs absent: synthetic checks run, exit 3. No game or residency proof.
"""
from dataclasses import replace
from fractions import Fraction
import json
import math
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(HERE))
import c1_grid as c
import ground as g
import merge as m
import region as r
from convert import Builder
from formats import Chunk, FormatError, chunks, require, u32
from test_ground import carp, pack_bytes

SHIFT = (20480., 0.)
ASSETS = all((root / name).is_file() for root, base in ((m.DEFAULT_MW, 'L2RA'), (m.DEFAULT_CARBON, 'L5RA'))
             for name in (base+'.BUN', 'STREAM'+base+'.BUN'))


def inventory(index, stream):
    """Read originals directly; no merge/read_city/report-derived expectations."""
    raw = r.collision_body(r.one(index.parts, 0x3b800))
    tags = r.collision_tags(raw, c.CDAT)
    desc = c.tag_data(raw, tags[c.CGRD])
    records = list(r.collision_cells(raw, tags[c.CGCN])) if c.CGCN in tags else []
    packs = {}
    for section in index.sections:
        for chunk in chunks(m.read_section(stream, section)):
            if chunk.kind == 0x3b801:
                pack = r.collision_body(chunk)
                require(u32(pack, 4) not in packs, 'source duplicate pack')
                packs[u32(pack, 4)] = pack
            elif chunk.kind == 0x3b802:
                body = r.collision_body(chunk)[16:]
                records.extend(r.collision_cells(body, r.collision_tags(body, c.ARTI)[c.CGCN]))
    return SimpleNamespace(descriptor=desc, records=records, packs=packs)


def tile_records(result):
    body = result.tile[16:]
    return r.collision_cells(body, r.collision_tags(body, c.ARTI)[c.CGCN])


def words(record, family):
    start = 20+4*sum(record[8:8+family])
    return tuple(v[0] for v in struct.iter_unpack('<I', record[start:start+4*record[8+family]]))


def expected_cells(result, carbon, source, mapping):
    """Exact rational footprint intersections, independent of converter floats.

    Inclusive last target slot is ceil(upper boundary)-1; a cell touching only
    the next grid boundary must not occupy that next slot. Preserve native
    family list multiplicity, coalesce only the re-binned source lists.
    """
    ox, _, oz = struct.unpack_from('<3f', result.descriptor)
    columns = u32(result.descriptor, 28)
    expected, native_ids, source_ids = {}, set(), set()
    for city, dx, dz, native in ((carbon, 0., 0., True), (source, *SHIFT, False)):
        sx, _, sz = struct.unpack_from('<3f', city.descriptor)
        step = struct.unpack_from('<f', city.descriptor, 16)[0]
        cols = u32(city.descriptor, 28)
        for record in city.records:
            row, col = divmod(struct.unpack_from('<H', record, 4)[0], cols)
            left = Fraction(sx)+Fraction(dx)+col*Fraction(step)-Fraction(ox)
            bottom = Fraction(sz)+Fraction(dz)+row*Fraction(step)-Fraction(oz)
            refs = [list(words(record, k)) for k in range(4)]
            if not native:
                refs[0] = [(mapping[v >> 16] << 16) | (v & 65535) for v in refs[0]]
                refs[3] = [v+5790 for v in refs[3]]
            for row in range(math.floor(bottom/96), math.ceil((bottom+Fraction(step))/96)):
                for col in range(math.floor(left/96), math.ceil((left+Fraction(step))/96)):
                    cid = row*columns+col
                    (native_ids if native else source_ids).add(cid)
                    require(native or cid not in native_ids, 'test placement overlaps native city')
                    if cid not in expected:
                        expected[cid] = (record[:4], [list(fam) for fam in refs])
                    else:
                        prefix, dest = expected[cid]
                        require(prefix == record[:4], 'source prefix ambiguity')
                        for a, b in zip(dest, refs):
                            a.extend(v for v in b if v not in a)
                    if not native:
                        prefix, dest = expected[cid]
                        expected[cid] = (prefix, [list(dict.fromkeys(fam)) for fam in dest])
    return expected, native_ids, source_ids


def source_check(result, carbon, source):
    """Check completeness, every word, deterministic allocation and pack bytes."""
    require(struct.unpack_from('<3f', result.descriptor) == (-13440., 0., -7488.), 'origin differs')
    require(struct.unpack_from('<2I', result.descriptor, 24) == (167, 365), 'dimensions differ')
    require(result.rectangle == struct.pack('<5H', 2500, 0, 0, 365, 167), 'rectangle differs')
    c.check(result, cell_section=2500, tile_section=2500)
    # Source-derived allocator: all identities reserved before collision moves.
    taken = set(carbon.packs) | set(source.packs)
    mapping = {key: key for key in source.packs}
    for key in sorted(set(carbon.packs) & set(source.packs)):
        target = min(set(range(1, 2700))-taken)
        mapping[key] = target
        taken.add(target)
    require(result.pack_ids == mapping, 'returned pack mapping differs')
    expected, native_ids, source_ids = expected_cells(result, carbon, source, mapping)
    actual = {struct.unpack_from('<H', record, 4)[0]: record for record in tile_records(result)}
    require(actual.keys() == expected.keys(), 'cell completeness differs')
    for cid, record in actual.items():
        prefix, refs = expected[cid]
        require(record[:4] == prefix, 'opaque cell prefix differs')
        for k in range(4):
            require(words(record, k) == tuple(refs[k]), f'family-{k} source coverage differs')
    packs = {u32(pack, 4): pack for pack in result.packs}
    require(packs.keys() == set(carbon.packs) | set(mapping.values()), 'pack completeness differs')
    require(all(packs[key] == pack for key, pack in carbon.packs.items()), 'native pack bytes differ')
    for key, pack in source.packs.items():
        moved = packs[mapping[key]]
        ci = r.collision_tags(pack[16:], c.ARTI)[c.CI]
        expected_pack = bytearray(pack)
        struct.pack_into('<I', expected_pack, 4, mapping[key])
        for p in range(16+ci[3], 16+ci[3]+64*ci[2], 64):
            # All retail source bases are identity (also asserted below). The
            # independent byte oracle therefore needs no matrix formula here.
            require(struct.unpack_from('<3f', pack, p) == (1., 0., 0.) and
                    struct.unpack_from('<3f', pack, p+32) == (0., 0., 1.) and
                    not struct.unpack_from('<H', pack, p+18)[0] & 3, 'retail basis changed')
            tx = struct.unpack_from('<f', pack, p+48)[0]
            struct.pack_into('<f', expected_pack, p+48, tx-20480.)
        require(moved == expected_pack, 'shifted pack bytes/bounds differ')
    return expected, native_ids, source_ids


def oracle_world(result):
    """Feed real serialized tile/packs to the unchanged face oracle reader."""
    raw = carp(c.CDAT, [(c.CGRD, 1, result.descriptor), (c.RECT, 1, result.rectangle)])
    index = SimpleNamespace(parts=[Chunk(0x3b800, bytes(8)+raw)], sections=[SimpleNamespace(number=2500)])
    stream = Builder(0)
    stream.add(0x3b802, result.tile, 16)
    for pack in result.packs:
        stream.add(0x3b801, pack, 16)
    with patch.object(g, 'read_section', return_value=bytes(stream.data)):
        return g.World(index, None)


def grounded(world, nodes):
    heights, ids = [], []
    for i, (x, y, z) in enumerate(nodes):
        height = world.height(x, z, y)
        heights.append(height)
        if height is not None and 0 <= y-height <= 2.:
            ids.append(i)
    return ids, heights


class SyntheticTests(unittest.TestCase):
    def test_lowest_free_pack_ids_and_rejected_aliases(self):
        self.assertEqual(c.allocate_ids({1: b'', 101: b''}, {101: b'', 2: b'', 105: b''}),
                         {2: 2, 101: 3, 105: 105})
        self.assertEqual(c.allocate_ids({101: b''}, {101: b'', 102: b''}, {101: 2699}),
                         {101: 2699, 102: 102})
        for mapping in ({101: 102}, {101: 0}, {101: 2700}, {101: 101}, {103: 3}, {101: True}):
            with self.subTest(mapping=mapping), self.assertRaises(FormatError):
                c.allocate_ids({101: b''}, {101: b'', 102: b''}, mapping)

    def test_tilted_rows_translate_but_ground_oracle_refuses(self):
        # Exact orthonormal nonidentity basis; all three local t components move.
        basis = ((0., .6, .8), (.6, -.64, .48))
        original = pack_bytes(basis=basis, translation=(12., 5., -9.))
        delta = (40., -24.)
        moved = c.move_pack(original, 2699, delta)
        a, b = g.Pack(original), g.Pack(moved)
        # The merger still preserves inverse translations, but a ground proof
        # must reject these rows: the retail triangle cache ignores the basis.
        self.assertEqual(struct.unpack_from('<3f',a.instances,48),(12.,5.,-9.))
        for value,expected in zip(struct.unpack_from('<3f',b.instances,48),(26.4,-34.36,-29.48)):
            self.assertAlmostEqual(value,expected,delta=1e-5)
        for pack in (a,b):
            with self.assertRaisesRegex(FormatError,'triangle cache'):
                list(pack.faces(0))
        # Bounds, radii, flags, article selectors and every article byte stay put.
        ci = r.collision_tags(original[16:], c.ARTI)[c.CI]
        off = 16+ci[3]+48
        self.assertEqual(original[8:off], moved[8:off])
        self.assertEqual(original[off+12:], moved[off+12:])
        self.assertEqual(u32(moved, 4), 2699)
        self.assertEqual(c.move_pack(original, 101, (0., 0.)), original)

    def test_u8_counts_and_bad_grid_extents(self):
        with self.assertRaisesRegex(FormatError, 'u8'):
            c.cell_record(bytes(4), 0, 2500, [list(range(256)), [], [], []])
        desc = struct.pack('<4f2f4I', 0., 0., 0., 1., 96., 1/96, 167, 365, 0, 1)
        c.grid_fields(desc)
        for rows, cols in ((251, 540), (0, 365), (1, 65536)):
            bad = bytearray(desc)
            struct.pack_into('<2I', bad, 24, rows, cols)
            with self.assertRaisesRegex(FormatError, 'u16'):
                c.grid_fields(bad)

    def test_output_guard_and_missing_assets_exit_three(self):
        stub = c.Grid(b'desc', b'rect', b'tile', (), {}, {})
        for path in (c.ROOT / 'c1-output', m.DEFAULT_MW / 'c1-output'):
            with self.assertRaisesRegex(FormatError, 'outside'):
                c.write_outputs(stub, path)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            dest = root / 'export'
            c.write_outputs(stub, dest)
            self.assertEqual((dest / 'tile.bin').read_bytes(), b'tile')
            with self.assertRaisesRegex(FormatError, 'exists'):
                c.write_outputs(stub, dest)
            (root / 'checkout-link').symlink_to(c.ROOT, target_is_directory=True)
            with self.assertRaisesRegex(FormatError, 'outside'):
                c.write_outputs(stub, root / 'checkout-link' / 'bad')
            with patch.object(c.os, 'rename', side_effect=OSError('injected failure')):
                with self.assertRaises(OSError):
                    c.write_outputs(stub, root / 'failed')
            self.assertFalse(list(root.glob('.c1-grid-*')))
            run = subprocess.run([sys.executable, '-I', str(HERE / 'c1_grid.py'),
                                  '--mw-root', temp, '--out', str(root / 'absent')],
                                 capture_output=True, text=True)
            self.assertEqual(run.returncode, 3, run.stderr)
            self.assertFalse((root / 'absent').exists())


@unittest.skipUnless(ASSETS, 'private collision archives absent')
class ArchiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.carbon_index, cls.carbon_stream, _ = m.load_index(m.DEFAULT_CARBON, 'L5RA')
        cls.mw_index, cls.mw_stream, _ = m.load_index(m.DEFAULT_MW, 'L2RA')
        cls.carbon = inventory(cls.carbon_index, cls.carbon_stream)
        cls.mw = inventory(cls.mw_index, cls.mw_stream)
        cls.result = c.merge(cls.carbon_index, cls.carbon_stream, cls.mw_index, cls.mw_stream)
        cls.expected, cls.native_ids, cls.source_ids = source_check(cls.result, cls.carbon, cls.mw)
        cls.world = oracle_world(cls.result)
        cls.mw_world = g.World(cls.mw_index, cls.mw_stream)
        cls.carbon_world = g.World(cls.carbon_index, cls.carbon_stream)
        cls.mw_nodes = g.road_nodes(cls.mw_index)
        cls.carbon_nodes = g.road_nodes(cls.carbon_index)
        cls.shifted_nodes = [(x+20480., y, z) for x, y, z in cls.mw_nodes]

    def test_premise_counts_references_and_limits(self):
        native = c.read_city(self.carbon_index, self.carbon_stream)
        self.assertEqual(len(native.rectangles), 9)
        self.assertEqual(native.tiles, ((2590, 1296), (2591, 76), (2592, 134), (2593, 209),
                                      (2594, 141), (2595, 133), (2596, 144), (2597, 232), (2598, 47)))
        self.assertEqual((len(self.native_ids), len(self.source_ids)), (2412, 1753))
        self.assertEqual(len(self.mw.records), 2779)
        measured = c.check(self.result)
        self.assertEqual((measured['cells'], measured['packs'], measured['instances']), (4165, 853, 15258))
        self.assertEqual(measured['unresolved'], 0)
        self.assertEqual(measured['family_maxima'], [60, 0, 0, 88])
        self.assertEqual(measured['family_margins'], [195, 255, 255, 167])
        self.assertEqual(measured['reference_families'], [42751, 0, 0, 31111])
        self.assertEqual(len(self.result.tile), 379040)
        self.assertEqual(sum(k != v for k, v in self.result.pack_ids.items()), 279)
        self.assertEqual(sum(len(p) for p in self.result.packs), 14606416)
        print('ACCEPT 167x365=60955/65536; occupied 4165; maxima 60/0/0/88; unresolved 0; tile 379040 B')

    def test_grounded_nodes_same_lists_and_heights(self):
        for label, before_world, nodes, shifted, expected in (
                ('source', self.mw_world, self.mw_nodes, self.shifted_nodes, 2522),
                ('native', self.carbon_world, self.carbon_nodes, self.carbon_nodes, 2319)):
            a, ha = grounded(before_world, nodes)
            b, hb = grounded(self.world, shifted)
            self.assertEqual(a, b, label)
            self.assertEqual(len(a), expected, label)
            self.assertEqual([v is None for v in ha], [v is None for v in hb], label)
            difference = max(abs(x-y) for x, y in zip(ha, hb) if x is not None and y is not None)
            self.assertLessEqual(difference, .002, label)
            self.assertEqual(difference, 0., label)
            print(f'GROUND {label} {len(a)}/{len(nodes)} -> {len(b)}/{len(shifted)}; equal list; max delta {difference} m')

    def test_float32_node_rounding_is_query_change(self):
        # This component does not serialize RNgp. Keep its exact-offset proof
        # distinct from the different points a float32 road converter writes.
        rounded = [(struct.unpack('<f', struct.pack('<f', x))[0], y, z)
                   for x, y, z in self.shifted_nodes]
        local = [(x-20480., y, z) for x, y, z in rounded]
        exact, _ = grounded(self.mw_world, self.mw_nodes)
        source_ids, source_heights = grounded(self.mw_world, local)
        merged_ids, merged_heights = grounded(self.world, rounded)
        self.assertEqual(source_ids, merged_ids)
        self.assertEqual(source_heights, merged_heights)
        self.assertEqual(len(merged_ids), 2510)
        self.assertEqual((len(set(exact)-set(merged_ids)), len(set(merged_ids)-set(exact))), (644, 632))
        self.assertEqual(max(abs(a[0]-b[0]) for a, b in zip(self.shifted_nodes, rounded)), .0009765625)
        print('F32 QUERY source/merged 2510/2510, identical lists/heights; exact-offset 2522; lost 644 / gained 632')

    def test_five_broken_variants_fail(self):
        result = self.result
        packs = tuple(self.carbon.packs[k] for k in sorted(self.carbon.packs)) + tuple(
            struct.pack('<2I', u32(pack), result.pack_ids[k])+pack[8:]
            for k, pack in sorted(self.mw.packs.items()))
        unshifted = replace(result, packs=packs)
        with self.assertRaisesRegex(FormatError, 'shifted pack'):
            source_check(unshifted, self.carbon, self.mw)
        ids, _ = grounded(oracle_world(unshifted), self.shifted_nodes)
        self.assertEqual(len(ids), 0)
        print('BROKEN unshifted packs: 0/4385 grounded != 2522/4385; rejected')

        records, wrong = [], 0
        for record in tile_records(result):
            cid = struct.unpack_from('<H', record, 4)[0]
            out = bytearray(record)
            if cid in self.source_ids:
                start = 20+4*sum(record[8:11])
                for p in range(start, len(record), 4):
                    struct.pack_into('<I', out, p, u32(record, p)-5790)
                    wrong += 1
            records.append(bytes(out))
        missing_offset = replace(result, tile=c.make_tile(records))
        self.assertEqual(c.check(missing_offset)['unresolved'], 0)  # range-only checks cannot catch this
        with self.assertRaisesRegex(FormatError, 'family-3'):
            source_check(missing_offset, self.carbon, self.mw)
        self.assertEqual(wrong, 17344)
        print('BROKEN no family-3 offset: 17344/17344 wrong words (valid: 0); rejected')

        duplicate = list(result.packs)
        duplicate[-1] = duplicate[-1][:4]+duplicate[0][4:8]+duplicate[-1][8:]
        with self.assertRaisesRegex(FormatError, 'duplicate'):
            c.check(replace(result, packs=tuple(duplicate)))
        print('BROKEN two packs on one id: 852 unique / 853 packs (valid: 853); rejected')

        descriptor = bytearray(result.descriptor)
        struct.pack_into('<2f', descriptor, 16, 64., 1/64)
        struct.pack_into('<2I', descriptor, 24, 251, 540)
        with self.assertRaisesRegex(FormatError, 'u16'):
            c.check(replace(result, descriptor=bytes(descriptor)))
        print('BROKEN 64 m: 135540 addressable > 65536 (valid: 60955); rejected')

        dropped = min(self.native_ids)
        records = [r for r in tile_records(result) if struct.unpack_from('<H', r, 4)[0] != dropped]
        missing_cell = replace(result, tile=c.make_tile(records))
        self.assertEqual(c.check(missing_cell)['cells'], 4164)
        with self.assertRaisesRegex(FormatError, 'completeness'):
            source_check(missing_cell, self.carbon, self.mw)
        print('BROKEN native cell dropped: 4164 occupied != 4165; rejected')

    def test_serialized_corruption_checks(self):
        result = self.result
        body = result.tile[16:]
        tag = r.collision_tags(body, c.ARTI)[c.CGCN]
        pos = 16+tag[3]
        # Keep payload extent intact while corrupting one independently checked field.
        first = tile_records(result)[0]
        mutations = [('offsets', pos+12, '<H', 4, 'offsets'),
                     ('duplicate', pos+len(first)+4, '<H', struct.unpack_from('<H', first, 4)[0], 'duplicate'),
                     ('section', pos+6, '<H', 1, 'section')]
        offset = pos
        for record in tile_records(result):
            if record[8]:
                mutations.append(('pack', offset+20, '<I', 2699 << 16 | 65535, 'unresolved'))
                break
            offset += len(record)
        offset = pos
        for record in tile_records(result):
            if record[11]:
                mutations.append(('segment', offset+20+4*sum(record[8:11]), '<I', 12328, 'family-3'))
                break
            offset += len(record)
        for label, off, fmt, value, error in mutations:
            tile = bytearray(result.tile)
            struct.pack_into(fmt, tile, off, value)
            with self.subTest(label=label), self.assertRaisesRegex(FormatError, error):
                c.check(replace(result, tile=bytes(tile)))
        rect = struct.pack('<5H', 2500, 0, 0, 1, 1)
        with self.assertRaisesRegex(FormatError, 'rectangle'):
            c.check(replace(result, rectangle=rect))
        with self.assertRaisesRegex(FormatError, 'tile extent'):
            c.check(replace(result, tile=result.tile[:-16]))

    def test_numbering_parameters_and_invalid_contracts(self):
        args = self.carbon_index, self.carbon_stream, self.mw_index, self.mw_stream
        altered = c.merge(*args, cell_section=2400, tile_section=2600,
                          pack_ids={min(self.mw.packs): 2699})
        self.assertEqual(u32(altered.tile, 4), 2600)
        self.assertEqual(struct.unpack_from('<H', altered.rectangle)[0], 2400)
        self.assertEqual(altered.pack_ids[min(self.mw.packs)], 2699)
        c.check(altered, cell_section=2400, tile_section=2600)
        for kw in ({'shift': (math.nan, 0)}, {'shift': (1e9, 0)}, {'segment_offset': 0},
                   {'cell_section': -1}, {'tile_section': 65535}, {'pack_ids': {101: 2700}}):
            with self.subTest(options=kw), self.assertRaises(FormatError):
                c.merge(*args, **kw)

    def test_cli_export_reread(self):
        with tempfile.TemporaryDirectory() as temp:
            dest = Path(temp).resolve() / 'component'
            run = subprocess.run([sys.executable, '-I', str(HERE / 'c1_grid.py'), '--out', str(dest)],
                                 capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            packs = tuple(r.collision_body(chunk) for chunk in chunks((dest / 'packs.bin').read_bytes()))
            reread = c.Grid(*( (dest / (name+'.bin')).read_bytes() for name in ('descriptor', 'rectangle', 'tile')),
                            packs, {int(k): v for k, v in json.loads((dest / 'pack_ids.json').read_text()).items()},
                            json.loads((dest / 'proof.json').read_text()))
            source_check(reread, self.carbon, self.mw)
            self.assertEqual(json.loads(run.stdout), self.result.report)
            self.assertEqual((reread.descriptor, reread.rectangle, reread.tile, reread.packs),
                             (self.result.descriptor, self.result.rectangle, self.result.tile, self.result.packs))


if __name__ == '__main__':
    result = unittest.main(exit=False, verbosity=2).result
    raise SystemExit(0 if result.wasSuccessful() and ASSETS else 3 if result.wasSuccessful() else 1)
