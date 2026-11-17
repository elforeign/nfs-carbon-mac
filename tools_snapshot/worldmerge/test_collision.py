"""Whole-city collision proof, source expectations derived outside the converter.

Baseline: 51 cells / 355 pack references / 259 family-3 words / 11 packs.
Acceptance: 2,779 cells / 21,112 pack references / 17,718 family-3 words /
390 packs (5,799,008 byte-equal bytes); RNgp 340,074 payload bytes equal;
CGrd 36 -> 40 bytes; rectangle (2500,3,3,88,100). Valid=1; broken=6 rejected:
dropped cell, transposed rectangle, section +6, pack id 2700, family-3 6538,
36-byte header. Opaque source bytes are read at runtime, never fixtures.
Missing private data exits 3 after synthetic tests. No game/reader proof (D2).
"""
from dataclasses import replace
from pathlib import Path
import json
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import collision as c
import formats as f
import merge as m
import region as r


def changed(raw, offset, code, value):
    out = bytearray(raw)
    struct.pack_into(code, out, offset, value)
    return bytes(out)


def ref_bytes(record, family):
    start = 20 + 4 * sum(record[8:8 + family])
    return record[start:start + 4 * record[8 + family]]


def payload(raw, tag):
    return raw[tag[3]:tag[3] + (tag[1] >> 8)] if tag[2] else b''


def source_inventory(root):
    """Walk the original index directly; never use converter reports/selection."""
    index, stream, _ = m.load_index(root, 'L2RA')
    raw = r.collision_body(r.one(index.parts, 0x3b800))
    data_tags = r.collision_tags(raw, 0x43446174)
    records = r.collision_cells(raw, data_tags[0x4347636e])
    cells = {struct.unpack_from('<H', record, 4)[0]: record for record in records}
    f.require(len(cells) == len(records), 'source duplicate cells')
    packs = {}
    for section in index.sections:
        for chunk in f.chunks(m.read_section(stream, section)):
            if chunk.kind == 0x3b801:
                body = r.collision_body(chunk)
                key = f.u32(body, 4)
                f.require(key not in packs, 'source duplicate pack')
                packs[key] = body
    roads = r.collision_tags(raw, 0x524e6770)
    return {'raw': raw, 'cells': cells, 'packs': packs, 'roads': roads,
            'descriptor': payload(raw, data_tags[0x43477264])}


def check_identity(result, source):
    """Independent acceptance checker of actual bytes, not the proof report.

    Native slot formula: quotient of id/columns is Z row; remainder is X col.
    cl+2/+4 are rowZ/colX; cl+6/+8 are countX/countZ. Family 3 is bounded
    by the source RNsg count without claiming its undecoded consumer semantics.
    """
    tags = r.collision_tags(result.map_data, 0x43446174)
    f.require(set(tags) == {0x43477264, 0x636c0000, 0x636f0000}, 'CDat layout/flat cells differ')
    grid = tags[0x43477264]
    f.require(grid[1] >> 8 == 40 and grid[2] == 1, 'CGrd must contain one 40-byte header')
    descriptor = payload(result.map_data, grid)
    expected = source['descriptor'][:32] + bytes(4) + struct.pack('<I', 1)
    f.require(descriptor == expected, 'grid descriptor source fields/extension differ')
    rows, columns = struct.unpack_from('<II', descriptor, 24)
    rect_tag = tags[0x636c0000]
    f.require(rect_tag[1] == 0xa03 and rect_tag[2] == 1, 'rectangle stride/count differ')
    rect = struct.unpack('<5H', payload(result.map_data, rect_tag))
    coords = [divmod(cid, columns) for cid in source['cells']]
    r0, r1 = min(row for row, _ in coords), max(row for row, _ in coords)
    c0, c1 = min(col for _, col in coords), max(col for _, col in coords)
    f.require(rect == (2500, r0, c0, c1 - c0 + 1, r1 - r0 + 1), 'rectangle differs from source occupancy')
    tile = result.tile
    f.require(f.u32(tile) == len(tile) - 16 and f.u32(tile, 4) == 2500, 'tile extent/section differ')
    raw = tile[16:]
    cells = r.collision_cells(raw, r.collision_tags(raw, 0x41727469)[0x4347636e])
    packs = {}
    instances = {}
    for body in result.packs:
        key = f.u32(body, 4)
        f.require(0 < key < 2700 and key not in packs, 'pack id outside table or duplicate')
        f.require(f.u32(body) == len(body) - 16, 'pack size differs')
        tag = r.collision_tags(body[16:], 0x41727469)[0x63690000]
        f.require(tag[1] >> 8 == 64 * tag[2], 'pack instance stride differs')
        packs[key] = body
        instances[key] = tag[2]
    f.require(packs.keys() == source['packs'].keys(), 'source pack set differs')
    f.require(packs == source['packs'], 'pack bytes differ')
    ids, slots = set(), set()
    family_counts = [0] * 4
    limit = source['roads'][0x524e7367][2]
    for record in cells:
        cid, section = struct.unpack_from('<HH', record, 4)
        f.require(section == 2500 and cid not in ids, 'cell section differs or id duplicate')
        row, col = divmod(cid, columns)
        f.require(row < rows and rect[1] <= row < rect[1] + rect[4]
                  and rect[2] <= col < rect[2] + rect[3], 'cell outside native rectangle slots')
        slots.add((row - rect[1]) * rect[3] + col - rect[2])
        ids.add(cid)
        for k in range(4):
            family_counts[k] += record[8 + k]
        for ref, in struct.iter_unpack('<I', ref_bytes(record, 0)):
            f.require(ref >> 16 < 2700 and ref >> 16 in instances
                      and (ref & 65535) < instances[ref >> 16], 'pack reference outside table/instances')
        f.require(all(word < limit for word, in struct.iter_unpack('<I', ref_bytes(record, 3))),
                  'family-3 word outside source RNsg count')
        f.require(cid in source['cells'], 'unexpected cell id')
        original = source['cells'][cid]
        f.require(record[:6] + original[6:8] + record[8:] == original, 'source cell/family bytes differ')
    f.require(ids == source['cells'].keys() and len(slots) == len(ids), 'source cell completeness differs')
    roads = r.collision_tags(result.map_data, 0x524e6770)
    f.require(roads.keys() == source['roads'].keys(), 'RNgp tag set differs')
    for key, tag in source['roads'].items():
        f.require(roads[key][1:3] == tag[1:3]
                  and payload(result.map_data, roads[key]) == payload(source['raw'], tag), 'RNgp bytes differ')
    before = min(t[3] for t in source['roads'].values() if t[2])
    after = min(t[3] for t in roads.values() if t[2])
    f.require(result.map_data[after:] == source['raw'][before:], 'opaque RNgp suffix differs')
    return len(ids), family_counts, len(packs), sum(map(len, packs.values()))


def synthetic_cell(cid, words=(1,), prefix=bytes(4)):
    return prefix + struct.pack('<HH4B4H', cid, 0, len(words), 0, 0, 0,
                                0, 4 * len(words), 4 * len(words), 4 * len(words)) + b''.join(
                                    struct.pack('<I', word) for word in words)


class SyntheticTests(unittest.TestCase):
    def test_rebin_covers_footprints_and_keeps_families(self):
        records = [synthetic_cell(0, (1, 2)), synthetic_cell(1, (2, 3))]
        out, rows, columns = c.rebin(records, 1, 2, 64, 96)
        self.assertEqual((rows, columns), (1, 2))
        self.assertEqual([struct.unpack_from('<H', rec, 4)[0] for rec in out], [0, 1])
        self.assertEqual([tuple(v for v, in struct.iter_unpack('<I', ref_bytes(rec, 0))) for rec in out],
                         [(1, 2, 3), (2, 3)])
        small, rows, columns = c.rebin([synthetic_cell(0)], 1, 1, 64, 32)
        self.assertEqual((rows, columns, len(small)), (2, 2, 4))
        self.assertEqual({struct.unpack_from('<H', rec, 4)[0] for rec in small}, {0, 1, 2, 3})

    def test_rebin_refuses_opaque_prefix_conflicts_and_count_overflow(self):
        with self.assertRaisesRegex(f.FormatError, 'prefix'):
            c.rebin([synthetic_cell(0), synthetic_cell(1, prefix=b'abcd')], 1, 2, 64, 128)
        with self.assertRaisesRegex(f.FormatError, 'u8'):
            c.rebin([synthetic_cell(0, range(200)), synthetic_cell(1, range(100, 300))], 1, 2, 64, 128)

    def test_scratch_export_and_path_guards(self):
        c.SCRATCH.mkdir(parents=True, exist_ok=True)
        result = c.Collision(b'map', b'tile', (), {'cells': 0})
        with tempfile.TemporaryDirectory(dir=c.SCRATCH) as temp:
            root = Path(temp)
            dest = root / 'export'
            c.write_outputs(result, dest)
            self.assertEqual((dest / 'map.carp').read_bytes(), b'map')
            self.assertEqual(json.loads((dest / 'proof.json').read_text()), {'cells': 0})
            with self.assertRaises(f.FormatError):
                c.write_outputs(result, dest)
            for bad in (c.SCRATCH, c.ROOT / 'bad-collision-output', root / '..' / '..' / 'escape'):
                with self.assertRaises(f.FormatError):
                    c.write_outputs(result, bad)
            (root / 'escape-link').symlink_to(c.ROOT, target_is_directory=True)
            with self.assertRaises(f.FormatError):
                c.write_outputs(result, root / 'escape-link' / 'bad')
            with patch.object(c.os, 'rename', side_effect=OSError('injected publish failure')):
                with self.assertRaises(OSError):
                    c.write_outputs(result, root / 'failed')
            self.assertFalse((root / 'failed').exists())
            self.assertFalse(list(root.glob('.collision-*')))


ASSETS = all(path.is_file() for path in (m.DEFAULT_MW / 'L2RA.BUN', m.DEFAULT_MW / 'STREAML2RA.BUN',
                                        m.DEFAULT_CARBON / 'L5RA.BUN', m.DEFAULT_CARBON / 'STREAML5RA.BUN'))


@unittest.skipUnless(ASSETS, 'private collision archives absent')
class ArchiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = source_inventory(m.DEFAULT_MW)
        cls.result = c.prepare()

    def test_all_source_cells_references_packs_and_roads_equal(self):
        self.assertEqual(check_identity(self.result, self.source), (2779, [21112, 0, 0, 17718], 390, 5799008))
        self.assertEqual(self.result.report['rectangle'], [2500, 3, 3, 88, 100])
        self.assertEqual(self.result.report['rngp_payload_bytes'], 340074)
        self.assertEqual(self.result.report['descriptor_bytes'], 40)
        self.assertEqual(self.result.report['tile_bytes'], 211200)

    def test_six_broken_variants_fail(self):
        result = self.result
        body = result.tile[16:]
        q, flags, count, p = r.collision_tags(body, 0x41727469)[0x4347636e]
        records = r.collision_cells(body, (q, flags, count, p))
        # Drop a cell while keeping every envelope, extent and count consistent.
        missing = len(records[-1])
        broken_body = bytearray(body)
        struct.pack_into('<II', broken_body, q + 4, ((flags >> 8) - missing) << 8 | 2, count - 1)
        broken_body[p + (flags >> 8) - missing:p + (flags >> 8)] = bytes(missing)
        with self.assertRaisesRegex(f.FormatError, 'completeness'):
            check_identity(replace(result, tile=result.tile[:16] + broken_body), self.source)
        print('BROKEN dropped cell: rejected (2778 != 2779)')
        tags = r.collision_tags(result.map_data, 0x43446174)
        rect = tags[0x636c0000][3]
        transposed = changed(result.map_data, rect + 6, '<I', 100 | (88 << 16))
        with self.assertRaisesRegex(f.FormatError, 'rectangle'):
            check_identity(replace(result, map_data=transposed), self.source)
        print('BROKEN rectangle transposed: rejected (100x88 != 88x100)')
        bad_section = changed(result.tile, 16 + p + 6, '<H', 6)
        with self.assertRaisesRegex(f.FormatError, 'section'):
            check_identity(replace(result, tile=bad_section), self.source)
        print('BROKEN cell +6=6: rejected (6 != 2500)')
        # Find actual non-empty families, without assuming the first cell has them.
        offset = p
        pack_offset = road_offset = None
        for record in records:
            if record[8] and pack_offset is None:
                pack_offset = 16 + offset + 20
            if record[11] and road_offset is None:
                road_offset = 16 + offset + 20 + 4 * sum(record[8:11])
            offset += len(record)
        bad_pack = changed(result.tile, pack_offset, '<I', 2700 << 16)
        with self.assertRaisesRegex(f.FormatError, 'pack reference'):
            check_identity(replace(result, tile=bad_pack), self.source)
        print('BROKEN pack id=2700: rejected (limit 2699)')
        bad_road = changed(result.tile, road_offset, '<I', 6538)
        with self.assertRaisesRegex(f.FormatError, 'family-3'):
            check_identity(replace(result, tile=bad_road), self.source)
        print('BROKEN family-3=6538: rejected (limit 6537)')
        old_header = changed(result.map_data, tags[0x43477264][0] + 4, '<I', 0x2402)
        with self.assertRaisesRegex(f.FormatError, '40-byte'):
            check_identity(replace(result, map_data=old_header), self.source)
        print('BROKEN CGrd=36 bytes: rejected (36 != 40)')

    def test_byte_equality_and_completeness_controls(self):
        result = self.result
        with self.assertRaisesRegex(f.FormatError, 'pack set'):
            check_identity(replace(result, packs=result.packs[:-1]), self.source)
        packs = list(result.packs)
        packs[0] = packs[0][:-1] + bytes([packs[0][-1] ^ 1])
        with self.assertRaisesRegex(f.FormatError, 'pack bytes'):
            check_identity(replace(result, packs=tuple(packs)), self.source)
        road = r.collision_tags(result.map_data, 0x524e6770)[0x524e7367][3]
        damaged = changed(result.map_data, road, '<I', f.u32(result.map_data, road) ^ 1)
        with self.assertRaisesRegex(f.FormatError, 'RNgp bytes'):
            check_identity(replace(result, map_data=damaged), self.source)
        body = result.tile[16:]
        tag = r.collision_tags(body, 0x41727469)[0x4347636e]
        records = r.collision_cells(body, tag)
        second = tag[3] + len(records[0])
        cid = struct.unpack_from('<H', records[0], 4)[0]
        duplicate = changed(result.tile, 16 + second + 4, '<H', cid)
        with self.assertRaisesRegex(f.FormatError, 'duplicate'):
            check_identity(replace(result, tile=duplicate), self.source)

    def test_parameter_identity_shift_remap_and_rebin(self):
        identity = c.prepare(cell=64, shift=(0, 0), id_map={})
        self.assertEqual((identity.map_data, identity.tile, identity.packs),
                         (self.result.map_data, self.result.tile, self.result.packs))
        shifted = c.prepare(shift=(20480, -96))
        grid = r.collision_tags(shifted.map_data, 0x43446174)[0x43477264]
        self.assertEqual(struct.unpack_from('<3f', shifted.map_data, grid[3]), (15680, 0, -1760))
        self.assertEqual((shifted.tile, shifted.packs), (identity.tile, identity.packs))
        source_id = min(self.source['packs'])
        remapped = c.prepare(id_map={source_id: 2699})
        self.assertEqual({f.u32(p, 4) for p in remapped.packs}, self.source['packs'].keys() - {source_id} | {2699})
        for pack in remapped.packs:
            key = f.u32(pack, 4)
            original_id = source_id if key == 2699 else key
            self.assertEqual(changed(pack, 4, '<I', original_id), self.source['packs'][original_id])
        body = remapped.tile[16:]
        records = r.collision_cells(body, r.collision_tags(body, 0x41727469)[0x4347636e])
        seen = set()
        for record in records:
            cid = struct.unpack_from('<H', record, 4)[0]
            expected = b''.join(struct.pack('<I', ((2699 if ref >> 16 == source_id else ref >> 16) << 16)
                                            | (ref & 65535)) for ref, in struct.iter_unpack('<I', ref_bytes(self.source['cells'][cid], 0)))
            self.assertEqual(ref_bytes(record, 0), expected)
            seen.update(ref >> 16 for ref, in struct.iter_unpack('<I', expected))
            self.assertEqual(ref_bytes(record, 3), ref_bytes(self.source['cells'][cid], 3))
        self.assertIn(2699, seen)
        rebinned = c.prepare(cell=96)
        grid = r.collision_tags(rebinned.map_data, 0x43446174)[0x43477264]
        self.assertEqual(struct.unpack_from('<II', rebinned.map_data, grid[3] + 24), (69, 62))
        body = rebinned.tile[16:]
        records = r.collision_cells(body, r.collision_tags(body, 0x41727469)[0x4347636e])
        actual = {struct.unpack_from('<H', rec, 4)[0]: rec for rec in records}
        expected = {}
        # Independent integer overlap arithmetic for 64 -> 96; no c.rebin call.
        for cid, record in self.source['cells'].items():
            row, col = divmod(cid, 92)
            for rr in range(row * 2 // 3, ((row + 1) * 2 + 2) // 3):
                for cc in range(col * 2 // 3, ((col + 1) * 2 + 2) // 3):
                    dest = expected.setdefault(rr * 62 + cc, [set() for _ in range(4)])
                    for k in range(4):
                        dest[k].update(struct.iter_unpack('<I', ref_bytes(record, k)))
        self.assertEqual(actual.keys(), expected.keys())
        for cid, refs in expected.items():
            for k in range(4):
                self.assertEqual(set(struct.iter_unpack('<I', ref_bytes(actual[cid], k))), refs[k])
        self.assertEqual(rebinned.packs, identity.packs)

    def test_invalid_conversion_parameters_fail(self):
        source_id, other = sorted(self.source['packs'])[:2]
        for options in ({'cell': 0}, {'cell': float('nan')}, {'shift': (float('inf'), 0)},
                        {'id_map': {source_id: 2700}}, {'id_map': {source_id: other}}, {'id_map': {2699: 1}}):
            with self.subTest(options=options), self.assertRaises(f.FormatError):
                c.prepare(**options)

    def test_export_readback_matches_actual_output(self):
        c.SCRATCH.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=c.SCRATCH) as temp:
            out = Path(temp) / 'export'
            c.write_outputs(self.result, out)
            roots = f.chunks((out / 'collision-stream.bin').read_bytes())
            tiles = [r.collision_body(item) for item in roots if item.kind == 0x3b802]
            packs = tuple(r.collision_body(item) for item in roots if item.kind == 0x3b801)
            self.assertEqual(len(tiles), 1)
            reread = c.Collision((out / 'map.carp').read_bytes(), tiles[0], packs, {})
            self.assertEqual(check_identity(reread, self.source), (2779, [21112, 0, 0, 17718], 390, 5799008))
            self.assertEqual((out / 'tile.bin').read_bytes(), tiles[0])


if __name__ == '__main__':
    result = unittest.main(exit=False, verbosity=2).result
    if not result.wasSuccessful():
        raise SystemExit(1)
    if not ASSETS:
        raise SystemExit(3)
    print('COLLISION PASS: 51 -> 2779 cells; six required corruptions rejected; source bytes preserved')
