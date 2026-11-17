"""Texture-animation proof: baseline 0/6 decoded -> 6/6 omission-classified.

Source frame hashes: 29/29 resolved (25 distinct); unique affected meshes: 33.
Broken frame drop: 6/6 rejected; zero hash: 6/6; child swap: 6/6 (18/18).
Frame order and signed timing match the independent source walk, value-for-value.
The registered target loader rejects this kind; no target bytes are emitted.
Missing private archives or the target reader image exits 3. No game runs.
"""
from collections import Counter
from dataclasses import replace
from pathlib import Path
import struct
import sys
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import texanim
from convert import Stats, convert_tpk
from formats import Chunk, FormatError, chunks, encode_chunks
from merge import DEFAULT_CARBON, DEFAULT_MW, load_index
from validate import validate_resources

TARGET_EXE = DEFAULT_CARBON.parent / 'NFSC.exe'
ASSETS = all(p.is_file() for p in (DEFAULT_MW / 'L2RA.BUN',
                                   DEFAULT_MW / 'STREAML2RA.BUN', TARGET_EXE))


def envelopes(data, base=0):
    """Independent raw extent walk, without the production chunk parser."""
    p = 0
    while p < len(data):
        assert p + 8 <= len(data), 'short header'
        kind, size = struct.unpack_from('<II', data, p)
        end = p + 8 + size
        assert end <= len(data), 'child crosses parent'
        yield kind, data[p + 8:end], base + p
        p = end


def single(data, kind, base=0):
    result = [(payload, off) for k, payload, off in envelopes(data, base) if k == kind]
    assert len(result) == 1, 'reference singleton'
    return result[0]


def unpad(payload, off):
    n = (-(off + 8)) & 15
    assert payload[:n] == b'\x11' * n and n <= len(payload)
    return payload[n:]


def reference_directory(chunk):
    ps = list(envelopes(chunk.payload))
    assert [p[0] for p in ps] == [0x30300101, 0x30300102, 0x30300103]
    header, records, entries = [p[1] for p in ps]
    assert header == struct.pack('<4I', 1, 0, 0, 0)
    assert len(records) > 0 and len(records) % 52 == 0 and len(entries) % 16 == 0
    result, used = [], 0
    for (row,) in struct.iter_unpack('<52s', records):
        key, count, rate, clock = struct.unpack_from('<Iiii', row, 24)
        assert key and count > 0 and rate > 0 and row[40:] == bytes(12)
        frames = []
        for p in range(used, used + count * 16, 16):
            assert p + 16 <= len(entries)
            key_frame, a, b, c = struct.unpack_from('<4I', entries, p)
            assert key_frame and (a, b, c) == (0, 0, 0)
            frames.append(key_frame)
        used += count * 16
        result.append((row[:24], key, rate, clock, tuple(frames)))
    assert used == len(entries), 'unclaimed frame'
    return tuple(result)


def reference_inventory():
    """Raw index rows -> stored records; no writer/decoder/inventory helpers."""
    index = (DEFAULT_MW / 'L2RA.BUN').read_bytes()
    table, _ = single(index, 0x34110)
    assert len(table) % 92 == 0
    directories, texture_sets, first, packs = [], {}, Counter(), {}
    sections, mesh_records = 0, 0
    with (DEFAULT_MW / 'STREAML2RA.BUN').open('rb') as source:
        for (row,) in struct.iter_unpack('<92s', table):
            sections += 1
            number = struct.unpack_from('<h', row, 8)[0]
            offset, size = struct.unpack_from('<II', row, 20)
            source.seek(offset)
            raw = source.read(size)
            assert len(raw) == size
            textures, section_packs = set(), []
            for kind, payload, off in envelopes(raw):
                if kind == 0xb0300100:
                    directories.append((number, Chunk(kind, payload, off)))
                elif kind == 0xb3300000:
                    hp, _ = single(payload, 0xb3310000)
                    keys, _ = single(hp, 0x33310002)
                    rs, _ = single(hp, 0x33310004)
                    actual = tuple(struct.unpack_from('<I', r, 36)[0]
                                   for (r,) in struct.iter_unpack('<124s', rs))
                    assert actual == tuple(k for k, _ in struct.iter_unpack('<II', keys))
                    textures.update(actual)
                    section_packs.append((Chunk(kind, payload, off), Counter(actual)))
                elif kind == 0x80134000:
                    for solid_kind, solid, so in envelopes(payload, off + 8):
                        if solid_kind != 0x80134010:
                            continue
                        keys_raw, _ = single(solid, 0x134012)
                        keys = tuple(k for k, _ in struct.iter_unpack('<II', keys_raw))
                        hp, ho = single(solid, 0x134011, so + 8)
                        assert unpad(hp, ho)[25] == len(keys)
                        for k, mesh, mo in envelopes(solid, so + 8):
                            if k != 0x80134100:
                                continue
                            rs, ro = single(mesh, 0x134b02, mo + 8)
                            mh, ho = single(mesh, 0x134900, mo + 8)
                            rs, mh = unpad(rs, ro), unpad(mh, ho)
                            assert len(rs) == struct.unpack_from('<I', mh, 16)[0] * 104
                            for (material,) in struct.iter_unpack('<104s', rs):
                                assert material[24] < len(keys)
                                first[keys[material[24]]] += 1
                                mesh_records += 1
            texture_sets[number] = textures
            if any(n == number for n, _ in directories):
                packs[number] = section_packs
    return directories, texture_sets, first, packs, sections, mesh_records


def pe_read(data, address, size):
    pe = struct.unpack_from('<I', data, 60)[0]
    count, opt_size = struct.unpack_from('<H', data, pe + 6)[0], struct.unpack_from('<H', data, pe + 20)[0]
    base = struct.unpack_from('<I', data, pe + 52)[0]
    for p in range(pe + 24 + opt_size, pe + 24 + opt_size + count * 40, 40):
        va, raw_size, raw = struct.unpack_from('<III', data, p + 12)
        if va <= address - base and address - base + size <= va + raw_size:
            start = raw + address - base - va
            return data[start:start + size]
    raise AssertionError('reader fragment outside PE sections')


class SyntheticTests(unittest.TestCase):
    def test_multiple_records_partition_frames_and_preserve_signed_clock(self):
        records = b''.join(bytes(24) + struct.pack('<Iiii3I', key, n, rate, clock, 0, 0, 0)
                           for key, n, rate, clock in ((11, 2, 7, -9), (21, 1, 3, 1)))
        entries = b''.join(struct.pack('<4I', key, 0, 0, 0) for key in (11, 12, 21))
        c = Chunk(0xb0300100, encode_chunks([
            Chunk(0x30300101, struct.pack('<4I', 1, 0, 0, 0)),
            Chunk(0x30300102, records), Chunk(0x30300103, entries)]))
        actual = texanim.decode_directory(c)
        self.assertEqual(tuple((a.label, a.key, a.rate, a.time_base, a.frames) for a in actual),
                         reference_directory(c))
        ps = chunks(c.payload)
        ps[2] = Chunk(ps[2].kind, entries + struct.pack('<4I', 31, 0, 0, 0))
        with self.assertRaisesRegex(FormatError, 'unclaimed frames'):
            texanim.decode_directory(Chunk(c.kind, encode_chunks(ps)))


@unittest.skipUnless(ASSETS, 'private archives or target reader image absent')
class ArchiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        (cls.directories, cls.textures, cls.first, cls.packs,
         cls.sections, cls.mesh_records) = reference_inventory()
        index, stream, _ = load_index(DEFAULT_MW, 'L2RA')
        cls.inventory = texanim.inventory_source(index, stream)

    def test_registered_reader_rejects_directory_before_child_reads(self):
        image = TARGET_EXE.read_bytes()
        # Small executable fragments pin the premise without emulating the game.
        self.assertEqual(pe_read(image, 0x9b53b0, 15),
                         bytes.fromhex('68900a5600688005560068000130b0'))
        self.assertEqual(pe_read(image, 0x560580, 18),
                         bytes.fromhex('8b4424048b0881f9000030b30f85e4000000'))
        self.assertEqual(pe_read(image, 0x560676, 8), bytes.fromhex('81f9000032b3750f'))
        self.assertEqual(pe_read(image, 0x56068d, 3), bytes.fromhex('33c0c3'))
        self.assertEqual(pe_read(image, 0x560ae4, 10), bytes.fromhex('81f9000130b00f94c0c3'))

    def test_all_six_classified_with_independent_frame_timing_and_counts(self):
        self.assertEqual((self.sections, self.mesh_records, len(self.directories)), (720, 46351, 6))
        self.assertEqual(self.inventory.first_textures, self.first)
        self.assertEqual((self.inventory.sections, self.inventory.mesh_records), (720, 46351))
        self.assertEqual([(d.section, d.chunk.offset, d.chunk.payload) for d in self.inventory.directories],
                         [(n, c.offset, c.payload) for n, c in self.directories])
        frames, unique, affected = 0, set(), set()
        for number, chunk in self.directories:
            ref = reference_directory(chunk)
            result = texanim.classify_omission(chunk, self.inventory)
            decoded = tuple((a.label, a.key, a.rate, a.time_base, a.frames)
                            for a in result['animations'])
            self.assertEqual(decoded, ref)
            self.assertEqual(result['section'], number)
            hashes = tuple(k for a in ref for k in a[4])
            self.assertEqual(result['texture_hashes'], hashes)
            self.assertTrue(set(hashes) <= self.textures[number])
            self.assertEqual(result['resolved_frames'], result['total_frames'])
            self.assertTrue(result['ordinary_textures_retained'])
            self.assertEqual(result['first_texture_meshes_by_hash'],
                             {k: self.first[k] for k in set(hashes)})
            self.assertEqual(result['first_texture_meshes'], sum(self.first[k] for k in set(hashes)))
            frames += len(hashes)
            unique.update(hashes)
            affected.update(k for k in hashes if self.first[k])
        self.assertEqual((frames, len(unique), sum(self.first[k] for k in affected)), (29, 25, 33))
        print('TEXANIM: 6/6 classed; frames=29/29 resolved; unique_hashes=25; affected_meshes=33')

    def test_single_argument_api_uses_indexed_source(self):
        chunk = self.directories[0][1]
        self.assertEqual(texanim.classify_omission(chunk), texanim.classify_omission(chunk, self.inventory))

    def test_ordinary_records_survive_pack_conversion_without_directory(self):
        converted = 0
        for number, packs in self.packs.items():
            actual = Counter()
            for source, expected in packs:
                output = convert_tpk(source, 0, Stats())
                totals, _ = validate_resources(output, number)
                self.assertEqual(totals['textures'], sum(expected.values()))
                root, _ = single(output, 0xb3300000)
                hp, _ = single(root, 0xb3310000)
                records, _ = single(hp, 0x33310004)
                keys, _ = single(hp, 0x33310002)
                p, got = 0, []
                while p < len(records):
                    self.assertGreaterEqual(len(records) - p, 90)
                    got.append(struct.unpack_from('<I', records, p + 12)[0])
                    p += (89 + records[p + 88] + 3) // 4 * 4
                self.assertEqual(p, len(records))
                self.assertEqual(got, [k for k, _ in struct.iter_unpack('<II', keys)])
                self.assertEqual(Counter(got), expected)
                actual.update(got)
                converted += 1
            for n, c in self.directories:
                if n == number:
                    self.assertTrue(set(texanim.classify_omission(c, self.inventory)['texture_hashes']) <= actual.keys())
        print(f'TEXANIM ORDINARY: {converted}/{converted} packs preserve every texture record')

    def test_broken_variants_fail_all_six(self):
        rejected = Counter()
        for _, chunk in self.directories:
            parts = chunks(chunk.payload)
            variants = {}
            dropped = parts.copy()
            dropped[2] = replace(parts[2], payload=parts[2].payload[:-16])
            variants['frame_drop'] = dropped, 'frame coverage'
            zeroed = parts.copy()
            zeroed[2] = replace(parts[2], payload=bytes(4) + parts[2].payload[4:])
            variants['zero_hash'] = zeroed, 'zero texture hash'
            variants['child_swap'] = [parts[0], parts[2], parts[1]], 'child order/count'
            for name, (ps, reason) in variants.items():
                broken = replace(chunk, payload=encode_chunks(ps))
                with self.subTest(offset=chunk.offset, broken=name):
                    with self.assertRaisesRegex(FormatError, reason):
                        texanim.classify_omission(broken, self.inventory)
                    with self.assertRaises(AssertionError):
                        reference_directory(broken)
                    rejected[name] += 1
        self.assertEqual(rejected, Counter(frame_drop=6, zero_hash=6, child_swap=6))
        print('TEXANIM BROKEN: frame_drop=6/6 zero_hash=6/6 child_swap=6/6 rejected')

    def test_missing_record_and_changed_valid_directory_cannot_reuse_evidence(self):
        _, chunk = self.directories[0]
        contexts = tuple(replace(c, textures=frozenset()) if c.chunk == chunk else c
                         for c in self.inventory.directories)
        missing = texanim.classify_omission(chunk, replace(self.inventory, directories=contexts))
        self.assertEqual(missing['resolved_frames'], 0)
        self.assertFalse(missing['ordinary_textures_retained'])
        ps = chunks(chunk.payload)
        changed = bytearray(ps[1].payload)
        struct.pack_into('<i', changed, 32, 99)
        ps[1] = replace(ps[1], payload=bytes(changed))
        with self.assertRaisesRegex(FormatError, 'source location'):
            texanim.classify_omission(replace(chunk, payload=encode_chunks(ps)), self.inventory)


if __name__ == '__main__':
    result = unittest.main(exit=False)
    sys.exit(1 if not result.result.wasSuccessful() else 0 if ASSETS else 3)
