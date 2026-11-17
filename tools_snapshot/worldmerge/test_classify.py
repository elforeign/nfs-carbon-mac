"""Census proof: index/walk = 720/720 sections, 531897380/531897380 bytes.

Failure controls: skipped chunk = 1/1 rejected; wrong 36->40 stride = 1/1
rejected (also rejects a forged stride histogram with unchanged grand totals).
O03 local layout draw meshes: 36=19, 60=8, converter=19/8; closed region:
36=30, 60=16, converter=30/16. No private data literals or generated tables.
Tests exercise classify.py; no game runs or archive writes. Missing data exits 3.
"""
from collections import Counter
import copy
import csv
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import classify as c
import convert
from formats import Chunk, FormatError, Section, chunks
from merge import DEFAULT_MW, DEFAULT_CARBON, load_index, read_section

ASSETS = all((DEFAULT_MW / name).is_file() for name in ('L2RA.BUN', 'STREAML2RA.BUN'))
REGION_ASSETS = ASSETS and all((DEFAULT_CARBON / name).is_file()
                             for name in ('L5RA.BUN', 'L5RB.BUN', 'STREAML5RA.BUN', 'STREAML5RB.BUN'))


def section(number, size):
    raw = bytearray(92)
    struct.pack_into('<h', raw, 8, number)
    struct.pack_into('<II', raw, 24, size, size)
    return Section(bytes(raw))


def converter_layouts(stats):
    counts = Counter()
    for effect_pair, count in stats.effects.items():
        source_effect = int(effect_pair.split('->')[0])
        counts[str(convert.EFFECTS[source_effect][0])] += count
    return counts


class SyntheticTests(unittest.TestCase):
    def test_indexed_recount_and_skipped_chunk_control(self):
        raw = Chunk(0x80036000, Chunk(0x36001, bytes(32)).encode()).encode()
        record = section(101, len(raw))
        idx = Chunk(0x34110, record.raw).encode()
        with tempfile.TemporaryDirectory() as tmp:
            stream = Path(tmp) / 'stream'; stream.write_bytes(raw)
            reference = c.indexed_census(idx, stream)
        good = c.section_census(raw, record)
        c.reconcile([good], reference)
        broken = c.section_census(raw, record, skip_kind=0x36001)
        with self.assertRaisesRegex(FormatError, 'index/walk chunks mismatch'):
            c.reconcile([broken], reference)
        print('SKIP CONTROL: complete=1 pass; skipped child chunk=1 rejected')

    def test_unknown_nested_chunk_policy(self):
        raw = Chunk(0xb0300100, Chunk(0x36001, bytes(32)).encode()).encode()
        row = c.section_census(raw, section(101, len(raw)))
        self.assertEqual(row['unaccounted_bytes'], 0)
        self.assertEqual(row['metrics']['chunks']['b0300100/00036001'], 1)
        self.assertTrue(any(k.startswith('validation:animation:') for k in row['blockers']))
        self.assertNotIn('chunk:b0300100/00036001', row['blockers'])
        self.assertEqual(row['spans'][0][3], 'omitted_reported')
        with self.assertRaises(FormatError):
            c.section_census(raw + b'bad', section(101, len(raw) + 3))

    def test_data_body_fail_closed_and_padding_are_distinct(self):
        self.assertEqual(c.policy(0x123456, 0xb3320000, 'supported'), 'fail_closed')
        self.assertEqual(c.policy(0, 0xb3320000, 'supported'), 'padding_rebuilt')
        for kind in (0x34159, 0x34027, 0x3b801):
            self.assertEqual(c.policy(kind, None, 'supported'), 'omitted_reported')
        self.assertEqual(c.policy(0x34106, 0x80034100, 'supported'), 'omitted_reported')

    def test_event_dispatch_and_unknown_child_still_fail_closed(self):
        from test_scenery2 import fixture, with_events
        raw = with_events(fixture((101, 61)))
        good = c.section_census(raw, section(101, len(raw)))
        self.assertTrue(good['conversion']['success'])
        self.assertFalse(good['blockers'])
        event = next(root for root in chunks(raw) if root.kind == 0x80036000)
        broken = raw[:event.offset] + Chunk(event.kind,
            event.payload + Chunk(0x123456, bytes(16)).encode()).encode()
        row = c.section_census(broken, section(101, len(broken)))
        self.assertFalse(row['conversion']['success'])
        self.assertIn('chunk:80036000/00123456', row['blockers'])
        self.assertTrue(any(key.startswith('validation:80036000:') for key in row['blockers']))

    def test_missing_input_cli_exits_three(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run([sys.executable, '-I', str(HERE / 'classify.py'),
                                     '--mw', tmp], capture_output=True, text=True)
        self.assertEqual(result.returncode, 3, result.stderr)
        self.assertIn('private assets absent', result.stderr)

    def test_output_outside_scratch_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'forbidden'
            with self.assertRaisesRegex(FormatError, 'scratch child'):
                c.write_report(target, [], {})
            self.assertFalse(target.exists())


@unittest.skipUnless(ASSETS, 'private track archives absent')
class ArchiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index, cls.stream, cls.index_bytes = load_index(DEFAULT_MW, 'L2RA')
        cls.rows, cls.summary = c.classify()
        cls.reference = c.indexed_census(cls.index_bytes, cls.stream)

    def test_all_sections_and_independent_totals_reconcile(self):
        self.assertEqual(len(self.index.sections), 720)
        self.assertEqual(len(self.rows), 720)
        total = c.reconcile(self.rows, self.reference)
        self.assertEqual(total, self.summary['totals'])
        indexed_bytes = sum(s.size for s in self.index.sections)
        self.assertEqual(self.summary['bytes_walk'], indexed_bytes)
        self.assertEqual(self.summary['bytes_index'], indexed_bytes)
        self.assertEqual(self.summary['unaccounted_bytes'], 0)
        self.assertEqual(sum(total['layouts'].values()), sum(total['effects'].values()))
        self.assertEqual(sum(total['layouts'].values()), sum(total['layout_effects'].values()))
        self.assertEqual(sum(total['layout_vertices'].values()), sum(total['effect_vertices'].values()))
        self.assertEqual(self.summary['converter_successes'] + self.summary['converter_failures'], 720)
        # Per-section file sizes are also the index's decoded sizes in this data.
        self.assertTrue(all(s.size == struct.unpack_from('<I', s.raw, 28)[0] for s in self.index.sections))
        print(f"CENSUS CONTROL: index/walk=720/720; bytes={indexed_bytes}/{self.summary['bytes_walk']}; "
              f"successes={self.summary['converter_successes']}")

    def test_real_skipped_chunk_is_rejected(self):
        s = next(s for s in self.index.sections if s.number == 141)
        broken = c.section_census(read_section(self.stream, s), s, skip_kind=0x36002)
        rows = [broken if r['number'] == s.number else r for r in self.rows]
        with self.assertRaisesRegex(FormatError, 'index/walk chunks mismatch'):
            c.reconcile(rows, self.reference)

    def test_resource_policy_matches_writer(self):
        self.assertEqual(self.summary['converter_successes'], 720)
        resources = [r for r in self.rows if not r['metrics']['chunks'].get('root/80034100')]
        self.assertEqual(len(resources), 114)
        self.assertEqual(sum(r['conversion']['success'] for r in resources), 114)
        remaining = [r for r in resources if not r['conversion']['success']]
        self.assertEqual(len(remaining), 0)
        self.assertTrue(all(r['blockers'] for r in remaining))
        self.assertFalse(any('structure:resource_only' in r['blockers'] for r in self.rows))
        self.assertFalse(any('structure:scenery_count=2' in r['blockers'] for r in self.rows))

    def test_landed_decoder_policies(self):
        self.assertEqual(c.policy(0x3bc00, None, 'supported'), 'supported')
        for kind in (0x134013, 0x13401a):
            self.assertEqual(c.policy(kind, 0x80134010, 'supported'), 'supported')
        self.assertEqual(c.policy(0x80036000, None, 'supported'), 'supported')
        for kind in (0x36001, 0x36002, 0x36003):
            self.assertEqual(c.policy(kind, 0x80036000, 'supported'), 'supported')
        self.assertEqual(c.policy(0x123456, 0x80036000, 'supported'), 'fail_closed')
        self.assertEqual(c.policy(0xb0300100, None, 'supported'), 'omitted_reported')

    def test_wrong_layout_stride_is_rejected(self):
        s = next(s for s in self.index.sections if s.number == 1503)
        raw = read_section(self.stream, s)
        with self.assertRaisesRegex(FormatError, 'stride/extent mismatch'):
            c.section_census(raw, s, stride_override=(36, 40))
        # A mutant which lies in the histogram while retaining the same draw
        # and vertex grand totals must also fail the independent derivation.
        broken = copy.deepcopy(next(r for r in self.rows if r['number'] == s.number))
        for name in ('layouts', 'layout_vertices', 'layout_containers'):
            broken['metrics'][name]['40'] = broken['metrics'][name].pop('36')
        rows = [broken if r['number'] == s.number else r for r in self.rows]
        with self.assertRaisesRegex(FormatError, 'index/walk layouts mismatch'):
            c.reconcile(rows, self.reference)
        print('STRIDE CONTROL: original 36-byte layout passes; wrong 40-byte layout rejected=1/1')

    def test_o03_local_draw_meshes_equal_converter_by_layout(self):
        s = next(s for s in self.index.sections if s.number == 1503)
        _, stats = convert.convert_section(read_section(self.stream, s), 1503, 0)
        row = next(r for r in self.rows if r['number'] == 1503)
        self.assertEqual(row['metrics']['layouts'], converter_layouts(stats))
        self.assertEqual(dict(row['metrics']['layouts']), {'36': 19, '60': 8})
        self.assertEqual(sum(row['metrics']['layout_vertices'].values()), stats.vertices)
        self.assertEqual((stats.draws, stats.vertices), (27, 2102))

    @unittest.skipUnless(REGION_ASSETS, 'private region archives absent')
    def test_o03_closed_region_source_layouts_equal_converter(self):
        import region
        solids, textures, candidates = region.inventory(self.index, self.stream)
        candidate = next(r for r in candidates if r[0].number == 1503)
        wanted, _, missing_solids, missing_textures = region.dependency_closure(candidate, solids, textures)
        self.assertFalse(missing_solids or missing_textures)
        stats, measured = convert.Stats(), c.metrics()
        region.solid_list({key: solids[key] for key in wanted}, 0, stats)
        for key in wanted:
            mesh = c.one(region.children(solids[key][2]), 0x80134100)
            c.mesh_metrics(mesh, measured, set(), {})
        self.assertEqual(measured['layouts'], converter_layouts(stats))
        self.assertEqual(dict(measured['layouts']), {'36': 30, '60': 16})
        self.assertEqual(sum(measured['layout_vertices'].values()), stats.vertices)
        self.assertEqual((stats.solids, stats.draws, stats.vertices), (21, 46, 2590))
        print('O03: local census/converter layouts 36=19/19,60=8/8; closed region 36=30/30,60=16/16')

    def test_real_tpk_extra_data_chunk_fails_closed(self):
        s = next(s for s in self.index.sections if s.number == 2500)
        tpk = next(p for p in chunks(read_section(self.stream, s)) if p.kind == 0xb3300000)
        self.assertEqual(tpk.offset, 0)
        ps = chunks(tpk.payload, 8)
        marker = Chunk(0x123456, bytes(16))
        changed = Chunk(tpk.kind, b''.join(Chunk(p.kind, p.payload + marker.encode()).encode()
                        if p.kind == 0xb3320000 else p.encode() for p in ps))
        with self.assertRaisesRegex(FormatError, 'source TPK data children/counts'):
            convert.convert_tpk(changed, 0, convert.Stats())
        raw = changed.encode()
        row = c.section_census(raw, section(2500, len(raw)))
        self.assertFalse(row['conversion']['success'])
        self.assertIn('chunk:b3320000/00123456', row['blockers'])
        self.assertFalse(row['omissions'])

    def test_tsv_roundtrip_and_existing_output_guard(self):
        # Tests use a temporary directory under worktree scratch, never game roots.
        c.SCRATCH.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=c.SCRATCH) as tmp:
            out = Path(tmp) / 'report'
            c.write_report(out, self.rows, self.summary)
            with (out / 'sections.tsv').open() as f:
                sections = list(csv.DictReader(f, delimiter='\t'))
            self.assertEqual(len(sections), 720)
            self.assertEqual(sum(int(r['bytes']) for r in sections), self.summary['bytes_index'])
            self.assertEqual(sum(int(r['converter_success']) for r in sections), self.summary['converter_successes'])
            self.assertEqual(json.loads((out / 'summary.json').read_text()), self.summary)
            for name in ('layouts', 'effects', 'textures', 'layout_effects', 'chunks', 'spans'):
                self.assertGreater((out / f'{name}.tsv').stat().st_size, 0)
            with self.assertRaisesRegex(FormatError, 'output exists'):
                c.write_report(out, self.rows, self.summary)
            escape = Path(tmp) / 'escape'; escape.symlink_to(Path(tmp).parent.parent)
            with self.assertRaisesRegex(FormatError, 'scratch child'):
                c.write_report(escape / 'report', self.rows, self.summary)

    def test_rankings_cover_failures_and_examples_have_64_bytes(self):
        ranked = self.summary['blockers_ranked']
        self.assertEqual({r['class'] for r in ranked}, {key for row in self.rows for key in row['blockers']})
        for r in ranked:
            with self.subTest(blocker=r['class']):
                self.assertEqual(r['sections_affected'], sum(r['class'] in row['blockers'] for row in self.rows))
                self.assertEqual(r['sections_unblocked_alone'], sum(row['blockers'] == [r['class']] for row in self.rows))
                self.assertIsNotNone(r['example'])
                self.assertEqual(len(bytes.fromhex(r['example']['bytes64'])), 64)
        self.assertEqual(self.summary['greedy_fix_order'], [])
        self.assertEqual(self.summary['pool']['largest_section'], max(self.rows, key=lambda r: r['bytes'])['section'])


if __name__ == '__main__':
    result = unittest.main(exit=False, verbosity=2).result
    if not result.wasSuccessful():
        raise SystemExit(1)
    if not ASSETS or not REGION_ASSETS:
        raise SystemExit(3)
    print('CLASSIFY PASS: 720 sections reconciled; skipped chunk and wrong stride controls rejected; no game runs')
