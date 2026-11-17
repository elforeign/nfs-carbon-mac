"""Emitter proof: baseline 0/290; converted 290/290; native control 211/211.

Failure controls: count off by one 1/1 rejected; unshifted position at +20000
1/1 rejected; native chunk shortened by 80 bytes 1/1 rejected. Both intact
controls pass. Source: 1535 placements / 42 triggers; native: 1100 / 0.
The independent checker reads bytes, never the converter's decoder/constants.
Missing private archives exits 3; all asset operations are read-only.
Impact discovery: before 0/2 paths scoped (exit 2); after 2/2 (exit 0).
"""
from collections import Counter
import argparse
import hashlib
import math
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import emitters
from convert import Stats
from formats import Chunk, FormatError, chunks
from merge import DEFAULT_MW, DEFAULT_CARBON, load_index, read_section

MW, CARBON = DEFAULT_MW, DEFAULT_CARBON


def demand(condition, message):
    if not condition:
        raise FormatError(message)


def inspect(data, position):
    """Independent target schema checker: envelope, alignment, counts and fields."""
    demand(len(data) >= 8, 'check: truncated envelope')
    kind, size = struct.unpack_from('<II', data)
    demand(kind == 244736 and size == len(data) - 8, 'check: envelope')
    start = ((position + 23) // 16) * 16 - position
    demand(len(data) >= start + 16, 'check: truncated header')
    demand(data[8:start] == bytes([17]) * (start - 8), 'check: alignment filler')
    raw = data[start:]
    state, version, count, section = struct.unpack_from('<IIII', raw)
    demand((state, version) == (0, 5) and 0 < section < 65536, 'check: header fields')
    records, triggers, keys = [], [], Counter()
    p = 16
    # Walk the extents first, then reconcile the independent record total.
    while p < len(raw):
        demand(len(raw) - p >= 80, 'check: incomplete record')
        key, unused, owner, nt, pointer = struct.unpack_from('<IIHHI', raw, p)
        demand(unused == pointer == 0 and owner == section, 'check: record fields')
        m = struct.unpack_from('<16f', raw, p + 16)
        demand(all(math.isfinite(v) for v in m), 'check: matrix finite')
        demand(m[3] == m[7] == m[11] == 0 and m[15] == 1, 'check: affine matrix')
        records.append(p)
        keys[key] += 1
        p += 80
        demand(p + 48 * nt <= len(raw), 'check: truncated triggers')
        for end in range(p + 48, p + 48 * nt + 1, 48):
            t = raw[end - 48:end]
            demand(struct.unpack_from('<III', t) == (3, 3, 0), 'check: trigger links')
            floats = struct.unpack_from('<6f', t, 12)
            demand(all(math.isfinite(v) for v in floats) and floats[0] >= 0 and floats[5] >= 0,
                   'check: trigger floats')
            demand(t[28:32] == bytes(4), 'check: trigger reserved float')
            demand(struct.unpack_from('<BBII', t, 38) == (1, 0, 0, 0), 'check: trigger state')
            triggers.append(end - 48)
        p += nt * 48
    demand(len(records) == count, 'check: record count')
    return raw, records, triggers, keys


def check_translation(source, output, position, shift):
    before, records, triggers, keys = inspect(source.encode(), source.offset)
    after, new_records, new_triggers, new_keys = inspect(output, position)
    demand((records, triggers, keys) == (new_records, new_triggers, new_keys),
           'check: changed topology or external keys')
    expected = bytearray(before)
    for record in records:
        struct.pack_into('<f', expected, record + 64,
                         struct.unpack_from('<f', before, record + 64)[0] + shift)
    for trigger in triggers:
        struct.pack_into('<f', expected, trigger + 16,
                         struct.unpack_from('<f', before, trigger + 16)[0] + shift)
    # Zero shift must preserve even signed-zero encodings.
    demand(after == (bytes(expected) if shift else before), 'check: spatial/preserved bytes')
    return len(records), len(triggers), keys


def synthetic(offset=0, trigger=True):
    """Invented identity transform and spherical trigger, no copied asset bytes."""
    body = bytearray(16 + 80 + (48 if trigger else 0))
    struct.pack_into('<4I', body, 0, 0, 5, 1, 123)
    struct.pack_into('<IIHHI', body, 16, 0x12345678, 0, 123, int(trigger), 0)
    for i in range(4):
        struct.pack_into('<f', body, 32 + i * 20, 1)
    struct.pack_into('<3f', body, 80, 12, -8, 4)
    if trigger:
        struct.pack_into('<3I6fHBBII', body, 96, 3, 3, 0, 5, 16, -4, 8, 0, 3,
                         65535, 1, 0, 0, 0)
    return Chunk(0x3bc00, bytes([17]) * (-(offset + 8) % 16) + body, offset)


def changed(c, offset, fmt, value):
    data = bytearray(c.payload)
    struct.pack_into(fmt, data, -(c.offset + 8) % 16 + offset, value)
    return Chunk(c.kind, bytes(data), c.offset)


def collect(root, base):
    index, stream, _ = load_index(root, base)
    found = []
    for s in index.sections:
        for c in chunks(read_section(stream, s)):
            if c.kind == 0x3bc00:
                found.append((s, c))
    return found


class SyntheticTests(unittest.TestCase):
    def test_alignment_shift_and_stats(self):
        stats = Stats()
        for source_offset in range(16):
            source = synthetic(source_offset)
            for position in range(16):
                for shift in (0, 20000, -20000):
                    output = emitters.convert_emitters(source, position, stats, shift)
                    self.assertEqual(check_translation(source, output, position, shift)[:2], (1, 1))
        self.assertEqual((stats.emitter_chunks, stats.emitters, stats.emitter_triggers), (768, 768, 768))
        self.assertEqual(stats.emitter_library_keys, Counter({0x12345678: 768}))

    def test_unknown_and_runtime_fields_refuse_without_stats_changes(self):
        source = synthetic()
        # Every uninterpreted field is pinned, rather than silently copied.
        variants = [(0, '<I', 1), (4, '<I', 6), (12, '<I', 124), (20, '<I', 1),
                    (24, '<H', 124), (28, '<I', 1), (44, '<f', 1),
                    (96, '<I', 4), (104, '<I', 1), (124, '<f', 1),
                    (134, '<B', 2), (135, '<B', 1), (136, '<I', 1), (140, '<I', 1)]
        for p, fmt, value in variants:
            with self.subTest(field=p):
                stats = Stats()
                with self.assertRaises(FormatError):
                    emitters.convert_emitters(changed(source, p, fmt, value), 0, stats, 0)
                self.assertFalse(hasattr(stats, 'emitters'))

    def test_bad_extents_floats_and_alignment(self):
        source = synthetic()
        variants = [changed(source, 8, '<I', 2), changed(source, 26, '<H', 2),
                    changed(source, 80, '<f', float('nan')),
                    changed(source, 108, '<f', -1),
                    changed(source, 128, '<f', float('inf')),
                    Chunk(source.kind, source.payload[:-1]),
                    Chunk(source.kind, b'\0' + source.payload[1:]),
                    Chunk(1, source.payload)]
        for bad in variants:
            with self.assertRaises(FormatError):
                emitters.convert_emitters(bad, 0, Stats(), 0)
        for shift in (float('inf'), 1e39):
            with self.assertRaises(FormatError):
                emitters.convert_emitters(source, 0, Stats(), shift)
        with self.assertRaises(FormatError):
            emitters.convert_emitters(source, -1, Stats(), 0)

    def test_each_position_and_preserved_byte_is_checked(self):
        source = synthetic()
        output = emitters.convert_emitters(source, 0, Stats(), 20000)
        check_translation(source, output, 0, 20000)
        for p in (80, 112):  # matrix X and trigger X, relative to the aligned header
            mutant = bytearray(output)
            struct.pack_into('<f', mutant, 16 + p, 12)
            with self.assertRaisesRegex(FormatError, 'spatial/preserved'):
                check_translation(source, bytes(mutant), 0, 20000)
        mutant = bytearray(output)
        struct.pack_into('<f', mutant, 16 + 84, 99)  # untranslated Y must stay unchanged
        with self.assertRaisesRegex(FormatError, 'spatial/preserved'):
            check_translation(source, bytes(mutant), 0, 20000)

    def test_empty_chunk_and_signed_zero(self):
        source = synthetic(trigger=False)
        source = changed(source, 80, '<f', -0.0)
        self.assertEqual(emitters.convert_emitters(source, source.offset, Stats(), 0), source.encode())
        empty = Chunk(0x3bc00, bytes([17]) * 8 + struct.pack('<4I', 0, 5, 0, 123))
        check_translation(empty, emitters.convert_emitters(empty, 4, Stats(), 20000), 4, 20000)

    def test_no_assets_exit_three(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = subprocess.run([sys.executable, '-I', str(Path(__file__).resolve()),
                                '--mw', tmp, '--carbon', tmp], capture_output=True, text=True)
        self.assertEqual(r.returncode, 3, r.stderr)
        self.assertIn('private assets absent', r.stderr)

    def test_impacted_test_discovery(self):
        root = HERE.parents[1]
        for path in ('tools_snapshot/worldmerge/emitters.py',
                     'tools_snapshot/worldmerge/test_emitters.py'):
            result = subprocess.run([sys.executable, '-I', str(root / 'runtime/impact_tests.py'), path],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('test_emitters', result.stdout.split())


class ArchiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = collect(MW, 'L2RA')
        cls.native = collect(CARBON, 'L5RA')

    def test_native_and_all_conversions(self):
        self.assertEqual((len(self.source), len(self.native)), (290, 211))
        self.assertEqual(len({len(c.payload) for _, c in self.source}), 42)
        self.assertEqual(len({len(c.payload) for _, c in self.native}), 24)
        native_records = native_triggers = 0
        for section, c in self.native:
            raw, records, triggers, _ = inspect(c.encode(), c.offset)
            self.assertEqual(struct.unpack_from('<I', raw, 12)[0], section.number)
            native_records += len(records)
            native_triggers += len(triggers)
        self.assertEqual((native_records, native_triggers), (1100, 0))
        stats = Stats()
        for section, c in self.source:
            for shift in (0, 20000):
                output = emitters.convert_emitters(c, c.offset, stats, shift)
                check_translation(c, output, c.offset, shift)
                if not shift:
                    self.assertEqual(output, c.encode())
            self.assertEqual(emitters.decode_emitters(c).section, section.number)
        self.assertEqual((stats.emitter_chunks, stats.emitters, stats.emitter_triggers), (580, 3070, 84))
        print('EMITTERS: control=211/211 (1100 records); converted=290/290 '
              '(1535 records, 42 triggers); shift 0 byte-exact=290/290; shift 20000=290/290')

    def test_three_required_broken_controls(self):
        c = self.source[0][1]
        count = struct.unpack_from('<I', c.payload, -(c.offset + 8) % 16 + 8)[0]
        wrong_count = changed(c, 8, '<I', count + 1)
        with self.assertRaises(FormatError):
            emitters.convert_emitters(wrong_count, c.offset, Stats(), 0)
        with self.assertRaises(FormatError):
            inspect(wrong_count.encode(), c.offset)
        intact = emitters.convert_emitters(c, c.offset, Stats(), 20000)
        check_translation(c, intact, c.offset, 20000)
        broken = bytearray(intact)
        p = 8 + (-(c.offset + 8) % 16) + 16 + 64
        broken[p:p + 4] = c.encode()[p:p + 4]
        with self.assertRaisesRegex(FormatError, 'spatial/preserved'):
            check_translation(c, bytes(broken), c.offset, 20000)
        c = self.native[0][1]
        inspect(c.encode(), c.offset)
        # Repair the envelope size: rejection must come from the record count.
        truncated = Chunk(c.kind, c.payload[:-80], c.offset)
        with self.assertRaisesRegex(FormatError, 'record count'):
            inspect(truncated.encode(), c.offset)
        print('BROKEN: count+1 rejected=1/1; unshifted X at +20000 rejected=1/1; '
              'native -80 bytes rejected=1/1; intact controls=2/2')

    def test_external_keys_and_absent_legacy_libraries(self):
        source_keys, native_keys, kinds = Counter(), Counter(), Counter()
        for _, c in self.source:
            source_keys.update(inspect(c.encode(), c.offset)[3])
        for _, c in self.native:
            native_keys.update(inspect(c.encode(), c.offset)[3])

        def walk(data, base=0):
            for c in chunks(data, base):
                kinds[c.kind] += 1
                if c.kind & 0x80000000:
                    walk(c.payload, c.offset + 8)

        for base in ('L5RA', 'L5RB'):
            index, stream, data = load_index(CARBON, base)
            walk(data)
            for section in index.sections:
                walk(read_section(stream, section))
        for name in ('GLOBALA.BUN', 'GLOBALB.BUN', 'InGameA.bun', 'InGameB.bun'):
            walk((CARBON.parent / 'GLOBAL' / name).read_bytes())
        self.assertEqual((sum(kinds.values()), kinds[0x3bb00]), (498857, 0))
        self.assertEqual((len(source_keys), sum(source_keys.values())), (16, 1535))
        print('LIBRARIES: 498857 target envelopes checked; 0x3bb00 chunks=0; '
              'same-key entries=0/16; external emittergroup resolution remains unverified')
        for key, count in sorted(source_keys.items()):
            print(f'KEY {key:08x}: source={count}, legacy-library=0, native-placements={native_keys[key]}')

    def test_native_reader_fragments(self):
        # The exported C omits the loader/registration; pin the actual code
        # fragments used by the decode, never an entire executable or history.
        path = CARBON.parent / 'NFSC.exe'
        if not path.is_file():
            self.skipTest('native executable absent; archive checks still run')
        data = path.read_bytes()
        fragments = [(0x75ab50, 466, 'f50c1c8dc3043f0b08ffd676fb93aa1e92b76fe1b1ab03205459f59b73481e66'),
                     (0x9b8520, 26, '5cdd7caa6076288d7df165d3e06fb5338ae248534c94d0230e846efbb1995b38')]
        pe = struct.unpack_from('<I', data, 60)[0]
        optional = pe + 24
        self.assertEqual(struct.unpack_from('<I', data, optional + 28)[0], 0x400000)
        section_table = optional + struct.unpack_from('<H', data, pe + 20)[0]
        sections = [struct.unpack_from('<4I', data, section_table + i * 40 + 8)
                    for i in range(struct.unpack_from('<H', data, pe + 6)[0])]
        for va, length, digest in fragments:
            rva = va - 0x400000
            _, start, size, offset = next(s for s in sections if s[1] <= rva < s[1] + s[2])
            self.assertLessEqual(rva + length, start + size)
            fragment = data[offset + rva - start:offset + rva - start + length]
            self.assertEqual(hashlib.sha256(fragment).hexdigest(), digest)


def main():
    global MW, CARBON
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mw', type=Path, default=MW)
    parser.add_argument('--carbon', type=Path, default=CARBON)
    args, rest = parser.parse_known_args()
    MW, CARBON = args.mw, args.carbon
    paths = [MW / name for name in ('L2RA.BUN', 'STREAML2RA.BUN')]
    paths += [CARBON / name for name in ('L5RA.BUN', 'STREAML5RA.BUN', 'L5RB.BUN', 'STREAML5RB.BUN')]
    paths += [CARBON.parent / 'GLOBAL' / name
              for name in ('GLOBALA.BUN', 'GLOBALB.BUN', 'InGameA.bun', 'InGameB.bun')]
    if not all(p.is_file() for p in paths):
        print('private assets absent', file=sys.stderr)
        return 3
    program = unittest.main(argv=[sys.argv[0], *rest], exit=False)
    return 0 if program.result.wasSuccessful() else 1


if __name__ == '__main__':
    sys.exit(main())
