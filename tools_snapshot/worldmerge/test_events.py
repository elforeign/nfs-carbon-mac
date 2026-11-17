"""Event conversion proof with independent layout and translation checks.

Carbon structural control: 480/480; source inspection: 415/415.
Production conversion: baseline 0/415 -> 415/415 at shifts 0 and 20000.
Broken production variant omitting all tree-bound shifts: 415/415 rejected.
Other controls: tree count +1 rejected 415/415; corrupt target version 480/480.
Round trips preserve event counts, float32 X translations and mapped sections.
Both sound consumers compare +0, with 0 corpus matches to their five constants;
the unread +8 word matches those constants 12182/13144 and 16168/16302 times.
No game runs or archive writes. Missing assets exits 3.
"""
import argparse
from collections import Counter
from dataclasses import dataclass
import math
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import events
from convert import Builder, Stats
from formats import Chunk, FormatError, chunks, require
from merge import DEFAULT_MW, DEFAULT_CARBON, load_index, read_section

MW_ROOT, CARBON_ROOT = DEFAULT_MW, DEFAULT_CARBON

# Comparison immediates in the native sound consumers, not corpus record bytes.
SOUND_COMPARISONS = (0xf40a48ef, 0x72f66b23, 0xb6bd9c95, 0xf3abe1c2, 0x001d5d4f)


@dataclass(frozen=True)
class Checked:
    section: int
    event_count: int
    node_count: int
    bodies: tuple
    # Offset of each directly decoded world X within its aligned child payload.
    x_fields: tuple


def carbon_layout(c):
    """Independent structural checker of the target loader/query's memory reads.

    It does not call the production decoder or converter. The header fixups and
    version follow the target loader at 0x7a19f0. The 48-byte node addressing,
    signed counts and box coordinates follow 0x69fad0/0x69fb80; the 32-byte
    spheres and leaf indices follow 0x7a3660. Unread words remain uninterpreted;
    authoring metadata is cross-checked against independent extents/the graph.
    """
    require(c.kind == 0x80036000, 'target event envelope')
    children = chunks(c.payload, c.offset + 8)
    require([p.kind for p in children] == [0x36001, 0x36002, 0x36003],
            'target event child sequence')
    bodies = []
    for child in children:
        filler = (16 - ((child.offset + 8) & 15)) & 15
        require(child.payload[:filler] == b'\x11' * filler, 'target alignment')
        bodies.append(child.payload[filler:])
    head, tree, records = bodies
    require(len(head) == 32, 'target header size')
    words = struct.unpack('<8I', head)
    require(words[2] == 2, 'target header version')
    require(all(words[i] == 0 for i in (0, 1, 5, 6, 7)), 'target header fixups')
    require(len(records) > 0 and len(records) % 32 == 0, 'target sphere stride')
    event_count = len(records) // 32
    require(words[4] == event_count, 'target header event count')
    require(len(tree) > 16 and (len(tree) - 16) % 48 == 0, 'target tree stride')
    node_count = (len(tree) - 16) // 48
    require(struct.unpack_from('<I', tree)[0] == 0, 'target tree fixup')
    event_rows = list(struct.iter_unpack('<4I4f', records))
    require(all(all(math.isfinite(v) for v in r[4:]) and r[7] > 0 for r in event_rows),
            'target event sphere')
    node_rows = list(struct.iter_unpack('<3fhh3f10h', tree[16:]))
    parents = {}
    leaves, branches, owners = 0, 0, []
    for index, row in enumerate(node_rows):
        count = row[4]
        require(count != 0 and abs(count) <= 10, 'target signed node count')
        require(all(math.isfinite(v) for v in row[:3] + row[5:8]) and
                min(row[5:8]) > 0, 'target event box')
        refs = row[8:8 + abs(count)]
        require(not any(row[8 + abs(count):]), 'target inactive node slots')
        if count > 0:
            branches += 1
            for ref in refs:
                require(0 < ref < node_count and ref not in parents, 'target branch index')
                parents[ref] = index
        else:
            leaves += 1
            require(all(0 <= ref < event_count for ref in refs), 'target sphere index')
            owners.append(refs[0])
            sphere = event_rows[refs[0]]
            require(row[:3] == sphere[4:7] and row[5:8] == (sphere[7],) * 3,
                    'target leaf sphere')
    require(sorted(owners) == list(range(event_count)), 'target sphere owner coverage')
    require(set(parents) == set(range(1, node_count)), 'target tree reachability')
    max_depth = 0
    for index, row in enumerate(node_rows):
        require(row[3] == parents.get(index, -1), 'target parent inference')
        visited, current = set(), index
        while current in parents:
            require(current not in visited, 'target tree cycle')
            visited.add(current)
            current = parents[current]
        require(current == 0, 'target root')
        max_depth = max(max_depth, len(visited) + 1)
    require(struct.unpack_from('<4H', tree, 4) == (leaves, branches, node_count, max_depth),
            'target tree record count/depth')
    require(leaves == event_count, 'target leaf count')
    x_fields = tuple([(1, 16 + 48 * i) for i in range(node_count)] +
                     [(2, 16 + 32 * i) for i in range(event_count)])
    return Checked(words[3], event_count, node_count, tuple(bodies), x_fields)


def check_translation(source, target, shift_x, section=None):
    """Byte equality except the mapped section and every world X as float32."""
    before, after = carbon_layout(source), carbon_layout(target)
    require(before.x_fields == after.x_fields, 'target spatial field coverage')
    expected = [bytearray(body) for body in before.bodies]
    if section is not None:
        struct.pack_into('<I', expected[0], 12, section)
    if shift_x:
        for child, off in before.x_fields:
            x = struct.unpack_from('<f', before.bodies[child], off)[0]
            struct.pack_into('<f', expected[child], off, x + shift_x)
    require(tuple(bytes(b) for b in expected) == after.bodies,
            'target shift or non-position bytes differ')


def converted(c, shift_x, position=0, section=None, omit_tree_shift=False):
    """Call the real writer; optionally break its tree shifts for a failure proof."""
    stats = Stats()
    if omit_tree_shift:
        remaining = carbon_layout(c).node_count
        original = events.translate_float

        def broken_shift(raw, offset, shift):
            nonlocal remaining
            if remaining:
                remaining -= 1
            else:
                original(raw, offset, shift)

        with patch.object(events, 'translate_float', side_effect=broken_shift):
            raw = events.convert_events(c, position, stats, shift_x, section=section)
        require(remaining == 0, 'mutant did not visit every tree node')
    else:
        raw = events.convert_events(c, position, stats, shift_x, section=section)
    roots = chunks(raw, position)
    require(len(roots) == 1, 'writer root count')
    return roots[0], stats


def change_body(c, child_index, field, value):
    payload = bytearray(c.payload)
    part = chunks(c.payload, c.offset + 8)[child_index]
    aligned = (part.offset + 23) & ~15
    offset = aligned - (c.offset + 8) + field
    struct.pack_into('<I' if child_index == 0 else '<H', payload, offset, value)
    return Chunk(c.kind, bytes(payload), c.offset)


def synthetic():
    output = Builder(8)
    output.add(0x36001, struct.pack('<8I', 0, 0, 2, 101, 1, 0, 0, 0), 16)
    tree = bytearray(struct.pack('<I4HI', 0, 1, 1, 2, 2, 0))
    for parent, count, refs in ((-1, 1, [1]), (0, -1, [0])):
        tree += struct.pack('<3fhh3f10h', 1, 2, 3, parent, count, 4, 4, 4,
                            *(refs + [0] * (10 - len(refs))))
    output.add(0x36002, tree, 16)
    output.add(0x36003, struct.pack('<4I4f', 0x1234, 0x10007, 0x2222, 3, 1, 2, 3, 4), 16)
    return Chunk(0x80036000, bytes(output.data))


class SyntheticTests(unittest.TestCase):
    def test_conversion_alignment_section_mapping_and_counts(self):
        source = synthetic()
        result = events.decode_events(source)
        self.assertEqual((result.section, len(result.events), len(result.nodes)), (101, 1, 2))
        self.assertEqual(carbon_layout(source).event_count, 1)
        self.assertEqual(result.events[0].opaque, struct.pack('<II', 0x2222, 3))
        for position in range(16):
            for shift in (0, 20000, -20000):
                for section in (None, 202):
                    target, stats = converted(source, shift, position, section)
                    check_translation(source, target, shift, section)
                    reread = events.decode_events(target)
                    self.assertEqual(reread.section, 101 if section is None else section)
                    self.assertEqual((len(reread.events), len(reread.nodes)), (1, 2))
                    self.assertEqual(stats.nodes, 2)
                    self.assertEqual(stats, Stats(nodes=2))
        target, _ = converted(source, 0)
        self.assertEqual(target.encode(), source.encode())

    def test_unread_bytes_copy_without_a_value_whitelist(self):
        source = synthetic()
        for unknown in (bytes(8), struct.pack('<II', 0x3333, 7)):
            payload = bytearray(source.payload)
            decoded = events.decode_events(source)
            off = decoded.events[0].offset - (source.offset + 8) + 8
            payload[off:off + 8] = unknown
            changed = Chunk(source.kind, bytes(payload))
            self.assertEqual(events.decode_events(changed).events[0].opaque, unknown)
            target, _ = converted(changed, 20000, 13)
            check_translation(changed, target, 20000)
            self.assertEqual(events.decode_events(target).events[0].opaque, unknown)
        # The unread tree-prefix word is copied even when it is nonzero.
        payload = bytearray(source.payload)
        off = events.decode_events(source).offsets[1] - 8 + 12
        struct.pack_into('<I', payload, off, 0x4444)
        changed = Chunk(source.kind, bytes(payload))
        self.assertEqual(events.decode_events(changed).tree_reserved, struct.pack('<I', 0x4444))
        target, _ = converted(changed, 20000)
        check_translation(changed, target, 20000)
        self.assertEqual(events.decode_events(target).tree_reserved, struct.pack('<I', 0x4444))

    def test_checker_controls(self):
        source = synthetic()
        for shift in (0, 20000):
            target, _ = converted(source, shift)
            check_translation(source, target, shift)
            if shift == 0:
                self.assertEqual(target.encode(), source.encode())
        for broken in (change_body(source, 1, 8, 3), change_body(source, 0, 8, 99)):
            with self.assertRaises(FormatError):
                carbon_layout(broken)
            with self.assertRaises(FormatError):
                events.decode_events(broken)
        broken, _ = converted(source, 20000, omit_tree_shift=True)
        with self.assertRaisesRegex(FormatError, 'leaf sphere'):
            carbon_layout(broken)
        with self.assertRaises(FormatError):
            check_translation(source, broken, 20000)

    def test_failed_conversion_keeps_stats_and_source_unchanged(self):
        source = synthetic()
        original = source.encode()
        stats = Stats(nodes=7)
        for position, shift, section in ((-1, 0, None), (0, math.nan, None),
                                         (0, math.inf, None), (0, 1e100, None),
                                         (0, 0, -1), (0, 0, 1 << 32)):
            with self.subTest(position=position, shift=shift, section=section):
                with self.assertRaises(FormatError):
                    events.convert_events(source, position, stats, shift, section=section)
                self.assertEqual(stats, Stats(nodes=7))
                self.assertEqual(source.encode(), original)
        events.convert_events(source, 0, stats, 20000)
        self.assertEqual(stats, Stats(nodes=9))

    def test_decoder_rejects_envelope_alignment_and_fixup_mutants(self):
        source = synthetic()
        bad_children = source.payload + Chunk(0x36004, b'').encode()
        for payload in (source.payload[:-1], bad_children):
            with self.assertRaises(FormatError):
                events.decode_events(Chunk(source.kind, payload))
        with self.assertRaisesRegex(FormatError, 'runtime fixups'):
            events.decode_events(change_body(source, 0, 24, 1))
        relocated = Chunk(source.kind, source.payload, 8)
        with self.assertRaises(FormatError):
            events.decode_events(relocated)

    def test_impacted_test_is_registered(self):
        root = HERE.parents[1]
        result = subprocess.run([sys.executable, '-I', str(root / 'runtime/impact_tests.py'),
                                 str(HERE.relative_to(root) / 'events.py'),
                                 str(HERE.relative_to(root) / 'test_events.py')],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('test_events', result.stdout.split())

    def test_missing_assets_exits_three(self):
        with tempfile.TemporaryDirectory() as empty:
            result = subprocess.run([sys.executable, '-I', str(HERE / 'test_events.py'),
                                     '--mw', empty, '--carbon', empty],
                                    capture_output=True, text=True)
        self.assertEqual(result.returncode, 3, result.stderr)
        self.assertIn('private assets absent', result.stderr)


class ArchiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.corpora = {}
        for name, root, base in (('source', MW_ROOT, 'L2RA'), ('control', CARBON_ROOT, 'L5RA')):
            index, stream, _ = load_index(root, base)
            directories = []
            for section in index.sections:
                for c in chunks(read_section(stream, section)):
                    if c.kind == 0x80036000:
                        directories.append((section.number, c))
            cls.corpora[name] = directories

    def test_premise_and_independent_layout_control(self):
        for name, expected, expected_events, expected_nodes in (
                ('source', 415, 13144, 16426), ('control', 480, 16302, 20422)):
            corpus = self.corpora[name]
            self.assertEqual(len(corpus), expected)
            totals, sizes = Counter(), [set(), set(), set()]
            for section, c in corpus:
                checked = carbon_layout(c)
                decoded = events.decode_events(c)
                self.assertEqual(checked.section, section)
                self.assertEqual(decoded.section, section)
                self.assertEqual((len(decoded.events), len(decoded.nodes)),
                                 (checked.event_count, checked.node_count))
                positions = {(1, n.offset - decoded.offsets[1]) for n in decoded.nodes}
                positions.update((2, e.offset - decoded.offsets[2] + 16) for e in decoded.events)
                self.assertEqual(set(checked.x_fields), positions)
                self.assertTrue(all(any(e.opaque[:4]) and any(e.opaque[4:])
                                    for e in decoded.events))
                for i, body in enumerate(checked.bodies):
                    sizes[i].add(len(body))
                totals.update(events=checked.event_count, nodes=checked.node_count)
            self.assertEqual(sizes[0], {32})
            self.assertEqual((totals['events'], totals['nodes']), (expected_events, expected_nodes))
            if name == 'source':
                self.assertEqual((len(sizes[1]), len(sizes[2])), (105, 88))
            print(f'{name}: structural control={len(corpus)}/{expected}; '
                  f'events={totals["events"]}; nodes={totals["nodes"]}')

    def test_production_conversion_and_roundtrip_all_source_directories(self):
        passed, event_count, x_count = 0, 0, 0
        for index, (_, c) in enumerate(self.corpora['source']):
            before = carbon_layout(c)
            zero, zero_stats = converted(c, 0, c.offset)
            self.assertEqual(zero.encode(), c.encode())
            check_translation(c, zero, 0)
            # Exercise an explicit mapping without prescribing archive allocation.
            section = before.section + 1
            target, stats = converted(c, 20000, 4096 + index % 16, section)
            check_translation(c, target, 20000, section)
            reread = events.decode_events(target)
            self.assertEqual((reread.section, len(reread.events), len(reread.nodes)),
                             (section, before.event_count, before.node_count))
            self.assertEqual(stats, Stats(nodes=before.node_count))
            self.assertEqual(zero_stats, stats)
            event_count += len(reread.events)
            x_count += len(before.x_fields)
            passed += 1
        self.assertEqual((passed, event_count, x_count), (415, 13144, 29570))
        print(f'CONVERSION: baseline=0/415 -> accepted={passed}/415 at shifts 0 and 20000; '
              f'roundtrip events={event_count}; translated X fields={x_count}; '
              f'mapped sections={passed}')

    def test_missing_tree_shift_production_variant_and_bad_counts(self):
        bad_count, bad_shift = 0, 0
        for _, c in self.corpora['source']:
            broken, _ = converted(c, 20000, omit_tree_shift=True)
            with self.assertRaisesRegex(FormatError, 'leaf sphere'):
                carbon_layout(broken)
            with self.assertRaises(FormatError):
                check_translation(c, broken, 20000)
            bad_shift += 1
            original = carbon_layout(c)
            broken = change_body(c, 1, 8, original.node_count + 1)
            with self.assertRaisesRegex(FormatError, 'count'):
                carbon_layout(broken)
            with self.assertRaisesRegex(FormatError, 'count'):
                events.decode_events(broken)
            bad_count += 1
        self.assertEqual((bad_count, bad_shift), (415, 415))
        print(f'BROKEN PRODUCTION: all tree shifts omitted={bad_shift}/415 rejected; '
              f'bad tree count={bad_count}/415 rejected')

    def test_sound_comparison_histograms_in_both_games(self):
        for name, expected in (('source', (5267, 3740, 0, 271, 2904)),
                               ('control', (1837, 1766, 0, 148, 12417))):
            words = [Counter() for _ in range(4)]
            for _, c in self.corpora[name]:
                for row in struct.iter_unpack('<4I4f', carbon_layout(c).bodies[2]):
                    for i in range(4):
                        words[i][row[i]] += 1
            compared = tuple(words[0][k] for k in SOUND_COMPARISONS)
            opaque = tuple(words[2][k] for k in SOUND_COMPARISONS)
            self.assertEqual(compared, (0,) * len(SOUND_COMPARISONS))
            self.assertEqual(opaque, expected)
            total = sum(words[0].values())
            self.assertEqual(words[1], {0x10007: total})
            self.assertEqual(words[3], {3: total})
            self.assertEqual(len(words[0]), 7507 if name == 'source' else 8821)
            print(f'SOUND {name}: +00 distinct={len(words[0])}; '
                  f'+00 matches={compared}; +08 matches={opaque}; '
                  f'+08 histogram={dict(sorted(words[2].items()))}; +0c=3 in {total}/{total}')

    def test_corrupt_control_header_field_is_rejected(self):
        rejected = 0
        for _, c in self.corpora['control']:
            with self.assertRaisesRegex(FormatError, 'header version'):
                carbon_layout(change_body(c, 0, 8, 3))
            with self.assertRaisesRegex(FormatError, 'header version'):
                events.decode_events(change_body(c, 0, 8, 3))
            rejected += 1
        self.assertEqual(rejected, 480)
        print(f'CORRUPT CONTROL: header version rejected={rejected}/480')


def main():
    global MW_ROOT, CARBON_ROOT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mw', type=Path, default=DEFAULT_MW)
    parser.add_argument('--carbon', type=Path, default=DEFAULT_CARBON)
    args, remaining = parser.parse_known_args()
    MW_ROOT, CARBON_ROOT = args.mw, args.carbon
    present = all((root / name).is_file() for root, names in (
        (MW_ROOT, ('L2RA.BUN', 'STREAML2RA.BUN')),
        (CARBON_ROOT, ('L5RA.BUN', 'STREAML5RA.BUN'))) for name in names)
    if not present:
        print('private assets absent: event corpus proof unavailable', file=sys.stderr)
        return 3
    result = unittest.main(argv=[sys.argv[0], *remaining], exit=False, verbosity=2).result
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
