"""Resource proof, derived from indexed source records independently of writers.

Standalone writer: 710 accepted; scenery resolves 53779/99452 slots.
Resources raise closure to 99297/99452 slots (16941->19269 distinct keys).
Resource completeness: 114/114 pass; missing solid list: 1/1 rejected;
missing texture record: 1/1 rejected; reopened TPK-child acceptance: 1/1 rejected.
The broken writers run in memory; no game runs or source archive writes.
Missing private archives exits 3.
"""
from collections import Counter
from pathlib import Path
import struct
import sys
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import classify
import convert
import resources
from formats import Chunk, FormatError, Section, chunks, encode_chunks, require, u32
from merge import DEFAULT_MW, load_index, read_section
from validate import validate_resources, validate_section

ASSETS = all((DEFAULT_MW / n).is_file() for n in ('L2RA.BUN', 'STREAML2RA.BUN'))
SENTINELS = {0, 0xbe43edbb, 0x90f70174}


def children(c):
    return chunks(c.payload, c.offset + 8)


def one(items, kind):
    found = [c for c in items if c.kind == kind]
    require(len(found) == 1, 'inventory singleton')
    return found[0]


def aligned(c, alignment=16):
    pad = -(c.offset + 8) % alignment
    require(c.payload[:pad] == b'\x11' * pad, 'inventory alignment')
    return c.payload[pad:]


def inventory(raw, target=False):
    """Read actual solid headers and texture records, never writer statistics.

    Source keys also reconcile against their directory hash tables. Target
    texture records have a variable name tail instead of the source's stride.
    """
    solids, textures, refs = Counter(), Counter(), Counter()
    for root in chunks(raw):
        if root.kind == 0x80134000:
            parts = children(root)
            hp = children(one(parts, 0x80134001))
            table = one(hp, 0x134003).payload
            keys = [v[0] for v in struct.iter_unpack('<II', table)]
            actual = [u32(aligned(one(children(c), 0x134011)), 16)
                      for c in parts if c.kind == 0x80134010]
            require(actual == keys, 'inventory solid directory/records')
            solids.update(actual)
        elif root.kind == 0xb3300000:
            hp = children(one(children(root), 0xb3310000))
            table = one(hp, 0x33310002).payload
            keys = [v[0] for v in struct.iter_unpack('<II', table)]
            records = one(hp, 0x33310004).payload
            actual, p = [], 0
            while p < len(records):
                if target:
                    require(len(records) - p >= 90, 'inventory texture record truncated')
                    actual.append(u32(records, p + 12))
                    p += (89 + records[p + 88] + 3) // 4 * 4
                else:
                    require(len(records) - p >= 124, 'inventory source texture record truncated')
                    actual.append(u32(records, p + 36))
                    p += 124
            require(p == len(records), 'inventory texture extent')
            require(actual == keys, 'inventory texture directory/records')
            textures.update(actual)
        elif root.kind == 0x80034100:
            rows = one(children(root), 0x34102).payload
            require(len(rows) % 72 == 0, 'inventory scenery table stride')
            refs.update(u32(rows, i + k) for i in range(0, len(rows), 72)
                        for k in (24, 28, 32, 36) if u32(rows, i + k) not in SENTINELS)
    return solids, textures, refs


def complete(source, target):
    old_solids, old_textures, _ = inventory(source)
    new_solids, new_textures, _ = inventory(target, True)
    old_solids = Counter({0x1f389568 if k == 0xed85ba82 else k: v for k,v in old_solids.items()})
    require(old_solids == new_solids, 'resource solid completeness')
    require(old_textures == new_textures, 'resource texture completeness')


def with_extra_child(tpk):
    return Chunk(tpk.kind, encode_chunks(
        Chunk(c.kind, c.payload + Chunk(0x123456, bytes(16)).encode())
        if c.kind == 0xb3320000 else c for c in children(tpk)), tpk.offset)


class SyntheticTests(unittest.TestCase):
    def test_empty_and_unknown_resources_rejected(self):
        for raw in (b'', Chunk(0, bytes(16)).encode(), Chunk(0x123456, b'').encode()):
            with self.subTest(raw=raw), self.assertRaises(FormatError):
                convert.convert_section(raw, 2201)
            with self.subTest(raw=raw), self.assertRaises(FormatError):
                validate_resources(raw, 2201)


@unittest.skipUnless(ASSETS, 'private track archives absent')
class ArchiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index, cls.stream, _ = load_index(DEFAULT_MW, 'L2RA')
        cls.sources, cls.outputs, cls.source_keys, cls.output_keys = {}, {}, {}, {}
        cls.resource_numbers, cls.failed_resources = [], []
        cls.tpk_count, cls.unexpected_tpk_data = 0, 0
        cls.refs = Counter()
        for section in cls.index.sections:
            raw = read_section(cls.stream, section)
            for root in chunks(raw):
                if root.kind == 0xb3300000:
                    cls.tpk_count += 1
                    kinds = Counter(c.kind for c in children(one(children(root), 0xb3320000)) if c.kind)
                    cls.unexpected_tpk_data += kinds != Counter({0x33320001: 1, 0x33320002: 1})
            keys = inventory(raw)
            cls.source_keys[section.number] = keys
            cls.refs.update({0x1f389568 if k == 0xed85ba82 else k: v for k, v in keys[2].items()})
            is_resource = not any(c.kind == 0x80034100 for c in chunks(raw))
            try:
                generated, _ = convert.convert_section(raw, section.number, 0)
            except FormatError:
                if is_resource:
                    cls.failed_resources.append(section.number)
                continue
            cls.outputs[section.number] = generated
            cls.output_keys[section.number] = inventory(generated, True)
            if is_resource:
                cls.resource_numbers.append(section.number)
                cls.sources[section.number] = raw

    def mixed_section(self):
        return next(n for n in self.resource_numbers if all(self.source_keys[n][:2]))

    def test_all_indexed_resource_records_survive_and_validate(self):
        self.assertEqual(len(self.outputs), 710)
        self.assertEqual(len(self.resource_numbers), 114)
        self.assertEqual(len(self.failed_resources), 0)
        solids, textures = Counter(), Counter()
        for number in self.resource_numbers:
            source, target = self.sources[number], self.outputs[number]
            with self.subTest(number=number):
                complete(source, target)
                totals, _ = validate_resources(target, number)
                self.assertFalse(totals.get('instances', 0))
                self.assertEqual(totals.get('solids', 0), sum(self.source_keys[number][0].values()))
                self.assertEqual(totals.get('textures', 0), sum(self.source_keys[number][1].values()))
            solids.update(self.source_keys[number][0])
            textures.update(self.source_keys[number][1])
        print(f'RESOURCES: 114/114 complete and loader-valid; solids={sum(solids.values())} '
              f'({len(solids)} keys); textures={sum(textures.values())} ({len(textures)} hashes)')

    def test_reference_closure_before_and_after(self):
        baseline, accepted = set(), set()
        for number, (solids, _, _) in self.output_keys.items():
            accepted.update(solids)
            if number not in self.resource_numbers:
                baseline.update(solids)
        before = sum(count for key, count in self.refs.items() if key in baseline)
        after = sum(count for key, count in self.refs.items() if key in accepted)
        self.assertEqual(sum(self.refs.values()), 99452)
        self.assertEqual(len(self.refs), 19293)
        self.assertEqual((len(baseline), before, len(baseline & self.refs.keys())), (17147, 53779, 16941))
        self.assertEqual((len(accepted), after, len(accepted & self.refs.keys())), (19813, 99297, 19269))
        # Independently obtain the same accepted key set from indexed sources.
        source_accepted = set().union(*(self.source_keys[n][0].keys() for n in self.outputs))
        source_accepted = {0x1f389568 if k == 0xed85ba82 else k for k in source_accepted}
        self.assertEqual(accepted, source_accepted)
        print(f'CLOSURE: accepted={len(self.outputs) - len(self.resource_numbers)}->{len(self.outputs)}; '
              f'slots={before}->{after}/{sum(self.refs.values())}; '
              f'referenced keys={len(baseline & self.refs.keys())}->{len(accepted & self.refs.keys())}; '
              f'accepted solid keys={len(baseline)}->{len(accepted)}')

    def test_caller_number_is_not_renumbered(self):
        number = self.mixed_section()
        target, _ = convert.convert_section(self.sources[number], 1234, 999)
        self.assertEqual(target, resources.convert_resources(chunks(self.sources[number]), 1234)[0])
        self.assertEqual(target, self.outputs[number])
        validate_resources(target, 1234)
        with self.assertRaisesRegex(FormatError, 'target geometry/instances absent'):
            validate_section(target, 1234)
        with self.assertRaisesRegex(FormatError, 'scenery in target resource section'):
            validate_resources(self.outputs[1503], 1503)

    def test_dropped_solid_list_writer_fails_completeness(self):
        number = self.mixed_section()
        with patch.object(convert, 'convert_list', return_value=b''):
            broken, _ = convert.convert_section(self.sources[number], number)
        # A remaining TPK is structurally valid; only source completeness sees loss.
        validate_resources(broken, number)
        with self.assertRaisesRegex(FormatError, 'resource solid completeness'):
            complete(self.sources[number], broken)
        print('SOLID-LIST CONTROL: original=1 pass; dropped list=1 rejected')

    def test_omitted_texture_writer_fails_completeness(self):
        number = self.mixed_section()
        original, changed = convert.convert_tpk, []

        def omit(c, position, stats):
            generated = original(c, position, stats)
            root = chunks(generated, position)[0]
            parts = children(root)
            hp = children(one(parts, 0xb3310000))
            rows = one(hp, 0x33310004).payload
            starts, p = [], 0
            while p < len(rows):
                starts.append(p)
                p += (89 + rows[p + 88] + 3) // 4 * 4
            if changed or len(starts) < 2:
                return generated
            changed.append(True)
            replacements = {0x33310002: one(hp, 0x33310002).payload[:-8],
                            0x33310004: rows[:starts[-1]],
                            0x33310005: one(hp, 0x33310005).payload[:-24]}
            header = encode_chunks(Chunk(c.kind, replacements.get(c.kind, c.payload)) for c in hp)
            dp = children(one(parts, 0xb3320000))
            out = convert.Builder(position + 8)
            out.add(0, bytes(48)); out.add(0xb3310000, header); out.pad(128)
            body = convert.Builder(out.position + 8)
            body.add(0x33320001, one(dp, 0x33320001).payload)
            body.add(0x33320002, aligned(one(dp, 0x33320002), 128), 128)
            out.add(0xb3320000, body.data)
            return Chunk(0xb3300000, bytes(out.data)).encode()

        with patch.object(convert, 'convert_tpk', side_effect=omit):
            broken, _ = convert.convert_section(self.sources[number], number)
        self.assertEqual(len(changed), 1)
        validate_resources(broken, number)
        with self.assertRaisesRegex(FormatError, 'resource texture completeness'):
            complete(self.sources[number], broken)
        print('TEXTURE CONTROL: original=1 pass; omitted record=1 rejected')

    def test_extra_tpk_child_and_reopened_acceptance_fail(self):
        number = self.mixed_section()
        tpk = next(c for c in chunks(self.sources[number]) if c.kind == 0xb3300000)
        changed = with_extra_child(tpk)
        with self.assertRaisesRegex(FormatError, 'source TPK data children/counts'):
            convert.convert_tpk(changed, 0, convert.Stats())
        original = convert.convert_tpk

        def accept_extra(c, position, stats):
            stripped = Chunk(c.kind, encode_chunks(
                Chunk(p.kind, encode_chunks(q for q in children(p) if q.kind != 0x123456))
                if p.kind == 0xb3320000 else p for p in children(c)), c.offset)
            return original(stripped, position, stats)

        raw = changed.encode()
        record = bytearray(92)
        struct.pack_into('<h', record, 8, number)
        struct.pack_into('<II', record, 24, len(raw), len(raw))
        with patch.object(convert, 'convert_tpk', side_effect=accept_extra):
            with self.assertRaisesRegex(FormatError, 'converter passed despite census blockers'):
                classify.section_census(raw, Section(bytes(record)))
        print('TPK CONTROL: extra child=1 rejected; reopened acceptance=1 rejected by census')

    def test_tpk_data_singletons_and_padding(self):
        self.assertEqual((self.tpk_count, self.unexpected_tpk_data), (477, 0))
        number = self.mixed_section()
        tpk = next(c for c in chunks(self.sources[number]) if c.kind == 0xb3300000)
        for kind in (0x33320001, 0x33320002):
            for duplicate in (False, True):
                parts = []
                for p in children(tpk):
                    if p.kind == 0xb3320000:
                        dp = children(p)
                        body = (dp + [one(dp, kind)] if duplicate else [q for q in dp if q.kind != kind])
                        p = Chunk(p.kind, encode_chunks(body))
                    parts.append(p)
                with self.subTest(kind=kind, duplicate=duplicate), self.assertRaisesRegex(
                        FormatError, 'source TPK data children/counts'):
                    convert.convert_tpk(Chunk(tpk.kind, encode_chunks(parts), tpk.offset), 0, convert.Stats())
        padded = Chunk(tpk.kind, encode_chunks(
            Chunk(p.kind, p.payload + Chunk(0, bytes(16)).encode()) if p.kind == 0xb3320000 else p
            for p in children(tpk)), tpk.offset)
        generated = convert.convert_tpk(padded, 0, convert.Stats())
        complete(tpk.encode(), generated)
        validate_resources(generated, number)
        with self.assertRaisesRegex(FormatError, 'target TPK children/counts'):
            validate_resources(with_extra_child(chunks(generated)[0]).encode(), number)


if __name__ == '__main__':
    result = unittest.main(exit=False, verbosity=2).result
    if not result.wasSuccessful():
        raise SystemExit(1)
    if not ASSETS:
        raise SystemExit(3)
    print('RESOURCES PASS: source-index completeness, closure and three broken writers checked')
