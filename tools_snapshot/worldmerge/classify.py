"""Read-only section census, with an independently indexed completeness audit.

Counts describe the writer and indexed source providers, not runtime drawing.
Material draws are called draw meshes; solid mesh containers are counted too.
Opaque leaf payloads have envelopes accounted, but are not claimed decoded.
"""
import argparse
from collections import Counter, defaultdict
import csv
import json
from pathlib import Path
import struct
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import convert
import events
import texanim
from formats import FormatError, chunks, require, u32
from merge import DEFAULT_MW, load_index, read_section

SCRATCH = HERE.parents[1] / 'recomp' / 'out' / 'rocksections-scratch'
# Startup world share, excluding cars/auxiliary allocations and mode additions.
# startup world pool estimate; NFSC_006a9a70.c:10327 (startup allocation).
WORLD_POOL_BASE = 0x445c000
POOL_SOURCE = ('startup world pool estimate; '
               'NFSC_006a9a70.c:10327-10341; '
               'Y00 heap exception: NFSC_00794240.c:5980-5989')

# These are envelope directories, including the source-only animation root.
# The copied list sidecar is an empty directory in this source, not vertex data.
CONTAINERS = {0x80134000, 0x80134001, 0x80134008, 0x80134010, 0x80134100,
              0x80034100, 0xb3300000, 0xb3310000, 0xb3320000,
              0x80036000, 0xb0300100}
ROOT_SUPPORTED = {0x80134000, 0x80034100, 0xb3300000, 0x3bc00, 0x80036000}
ROOT_OMITTED = {0x34159: 'helicopter sheets', 0x34027: 'ordinary scenery physics spawns',
                0x3b801: 'streamed collision packs',
                texanim.DIRECTORY: 'texture animation (ordinary textures remain static)'}
SCENE_CHILDREN = {0x34101, 0x34102, 0x34103, 0x34105, 0x34106, 0x34107}
MESH_CHILDREN = {0x134900, 0x134b02, 0x134b03, 0x134b01, 0x134c02}
# Only directories known to be accepted by each writer are whitelisted.
CHILDREN = {
    0x80134000: {0, 0x80134001, 0x80134010},
    0x80134001: {0x134002, 0x134003, 0x80134008},
    0x80134010: {0x134011, 0x134012, 0x80134100, 0x134013, 0x13401a},
    0x80134100: MESH_CHILDREN,
    0x80034100: SCENE_CHILDREN,
    0xb3300000: {0, 0xb3310000, 0xb3320000},
    0xb3310000: {0x33310001, 0x33310002, 0x33310004, 0x33310005},
    0xb3320000: {0, 0x33320001, 0x33320002},
    0x80036000: {0x36001, 0x36002, 0x36003},
}
LABELS = {0x80036000: 'world event directories',
          0xb0300100: 'undecoded streamed directory',
          0x3bc00: 'world emitter placements', 0x34106: 'scenery override references'}


def one(items, kind):
    found = [c for c in items if c.kind == kind]
    require(len(found) == 1, f'census singleton {kind:08x}: {len(found)}')
    return found[0]


def policy(kind, parent, inherited):
    if inherited in ('omitted_reported', 'fail_closed', 'silently_dropped'):
        return inherited
    if kind == 0:
        return 'padding_rebuilt'
    if parent is None:
        if kind in ROOT_OMITTED:
            return 'omitted_reported'
        return 'supported' if kind in ROOT_SUPPORTED else 'fail_closed'
    if parent == 0x80034100 and kind == 0x34106:
        return 'omitted_reported'
    return 'supported' if kind in CHILDREN.get(parent, set()) else 'fail_closed'


def walk(data, base=0, parent=None, inherited='supported'):
    for c in chunks(data, base):
        disposition = policy(c.kind, parent, inherited)
        yield c, parent, disposition
        if c.kind in CONTAINERS:
            yield from walk(c.payload, c.offset + 8, c.kind, disposition)


def metrics():
    return {name: Counter() for name in ('chunks', 'chunk_bytes', 'leaf_bytes',
                                        'layouts', 'layout_vertices', 'layout_containers',
                                        'effects', 'effect_vertices', 'effect_containers',
                                        'layout_effects', 'layout_effect_vertices',
                                        'textures', 'texture_bytes')}


def add_metrics(dst, src):
    for name in dst:
        dst[name].update(src[name])


def mesh_metrics(c, out, blockers, examples, stride_override=None):
    ps = chunks(c.payload, c.offset + 8)
    header = convert.aligned_payload(one(ps, 0x134900))
    records = convert.aligned_payload(one(ps, 0x134b02))
    require(len(header) == 48 and len(records) == u32(header, 16) * 104,
            'census material header/count')
    if not records and not empty_mesh_supported(c):
        key = 'mesh:empty_materials'
        blockers.add(key); examples.setdefault(key, one(ps, 0x134900))
    groups = []
    for off in range(0, len(records), 104):
        r = records[off:off + 104]
        effect, nv = u32(r, 48), u32(r, 60)
        if not groups or groups[-1][0] != effect:
            groups.append((effect, []))
        groups[-1][1].append(nv)
    buffers = [p for p in ps if p.kind == 0x134b01]
    require(len(groups) == len(buffers) == u32(header, 24), 'census VB/group count')
    seen_layouts, seen_effects = set(), set()
    for (effect, vertices), vb in zip(groups, buffers):
        raw = convert.aligned_payload(vb, 128)
        nv = sum(vertices)
        require(nv > 0 and len(raw) % nv == 0, 'census fractional stride')
        stride = len(raw) // nv
        if stride_override and stride == stride_override[0]:
            stride = stride_override[1]
        require(stride * nv == len(raw), 'census stride/extent mismatch')
        layout = str(stride)
        out['layouts'][layout] += len(vertices)
        out['layout_vertices'][layout] += nv
        out['effects'][str(effect)] += len(vertices)
        out['effect_vertices'][str(effect)] += nv
        pair = f'{stride}/{effect}'
        out['layout_effects'][pair] += len(vertices)
        out['layout_effect_vertices'][pair] += nv
        seen_layouts.add(layout); seen_effects.add(str(effect))
        if stride not in {row[0] for row in convert.EFFECTS.values()}:
            key = f'layout:{stride}'
            blockers.add(key); examples.setdefault(key, vb)
        if effect not in convert.EFFECTS:
            key = f'effect:{effect}'
            blockers.add(key); examples.setdefault(key, vb)
        elif stride != convert.EFFECTS[effect][0]:
            key = f'effect_layout:{effect}/{stride}'
            blockers.add(key); examples.setdefault(key, vb)
    out['layout_containers'].update(seen_layouts)
    out['effect_containers'].update(seen_effects)


def texture_metrics(c, out, blockers, examples):
    ps = chunks(c.payload, c.offset + 8)
    hs = chunks(one(ps, 0xb3310000).payload)
    rs, platforms = one(hs, 0x33310004).payload, one(hs, 0x33310005).payload
    require(len(rs) % 124 == 0 and len(platforms) == len(rs) // 124 * 32,
            'census texture record extents')
    for i in range(len(rs) // 124):
        pl = platforms[i * 32:(i + 1) * 32]
        fmt = pl[20:24].hex()
        out['textures'][fmt] += 1
        out['texture_bytes'][fmt] += u32(rs, i * 124 + 56)
        if pl[20:24] not in (b'DXT1', b'DXT3', b'DXT5'):
            key = f'texture_format:{fmt}'
            blockers.add(key); examples.setdefault(key, c)


def empty_mesh_supported(c):
    try:
        convert.refonly.convert_empty_mesh(c, 0, convert.Stats())
        return True
    except FormatError:
        return False


def section_census(raw, section, *, skip_kind=None, stride_override=None, providers=None,
                   animation_inventory=None):
    out = metrics()
    nodes = list(walk(raw))
    require(sum(8 + (len(c.payload) if c.kind not in CONTAINERS else 0)
                for c, _, _ in nodes) == len(raw), 'walk does not cover section end')
    blockers, examples, omissions, spans = set(), {}, Counter(), []
    roots = chunks(raw)
    scenes = sum(c.kind == 0x80034100 for c in roots)
    if scenes > 2:
        key = f'structure:scenery_count={scenes}'
        blockers.add(key)
        examples[key] = next((c for c in roots if c.kind), roots[0])
    elif scenes:
        try:
            convert.scenery_numbers(roots, section.number)
        except FormatError as exc:
            key = f'validation:scenery:{exc}'
            blockers.add(key); examples[key] = next(c for c in roots if c.kind == 0x80034100)
    for c, parent, disposition in nodes:
        if c.kind == skip_kind:
            continue
        path = f'{parent:08x}/{c.kind:08x}' if parent is not None else f'root/{c.kind:08x}'
        out['chunks'][path] += 1
        out['chunk_bytes'][path] += len(c.payload)
        if c.kind not in CONTAINERS:
            out['leaf_bytes'][path] += len(c.payload)
            spans.append((c.offset + 8, len(c.payload), path, disposition))
        if disposition == 'fail_closed' and (parent is None or parent in CHILDREN):
            # Descendants of unknown roots share their ancestor's blocker.
            key = f'chunk:{path}'
            blockers.add(key); examples.setdefault(key, c)
        if disposition in ('omitted_reported', 'silently_dropped'):
            omissions[f'{disposition}:{path}'] += len(c.payload)
        if c.kind == 0x80134100:
            mesh_metrics(c, out, blockers, examples, stride_override)
            try:
                convert.convert_mesh(c, 0, convert.Stats())
            except FormatError as exc:
                # Missing effects/layouts already have actionable identities.
                if not str(exc).startswith(('undecoded source effect', 'source group vertex size',
                                            'undecoded mesh child', 'source material count')):
                    key = f'validation:mesh:{exc}'
                    blockers.add(key); examples.setdefault(key, c)
        elif c.kind == 0xb3300000:
            texture_metrics(c, out, blockers, examples)
        elif parent is None and c.kind == texanim.DIRECTORY:
            try:
                convert.omit_animation_directory(c, convert.Stats(), animation_inventory)
            except FormatError as exc:
                key = f'validation:animation:{exc}'
                blockers.add(key); examples.setdefault(key, c)
        # Execute each supported root even when an earlier root fails closed.
        if parent is None and c.kind in ROOT_SUPPORTED:
            fn = {0x80134000: lambda: convert.convert_list(c, 0, convert.Stats()),
                  0x80034100: lambda: convert.convert_scenery(c, 0, section.number, 0, convert.Stats()),
                  0xb3300000: lambda: convert.convert_tpk(c, 0, convert.Stats()),
                  0x3bc00: lambda: convert.emitters.convert_emitters(c, 0, convert.Stats(), 0),
                  0x80036000: lambda: events.convert_events(c, 0, convert.Stats(), 0,
                                                          section=section.number)}[c.kind]
            try:
                fn()
            except FormatError as exc:
                if not str(exc).startswith(('undecoded source effect', 'source group vertex size',
                                            'undecoded mesh child', 'source material count',
                                            'undecoded solid children')):
                    key = f'validation:{c.kind:08x}:{exc}'
                    blockers.add(key); examples.setdefault(key, c)
    if scenes and not out['layouts'] and providers is None:
        blockers.add('structure:no_geometry')
        examples['structure:no_geometry'] = next(c for c in roots if c.kind == 0x80034100)
    instances = sum(len(convert.aligned_payload(c)) // 64 for c, _, _ in nodes if c.kind == 0x34103)
    if scenes and not instances:
        blockers.add('structure:no_instances')
    try:
        generated, stats = convert.convert_section(raw, section.number, 0, source_number=section.number,
            providers=providers, animation_inventory=animation_inventory)
    except FormatError as exc:
        conversion = {'success': False, 'error': str(exc)}
        if not blockers:
            key = f'validation:section:{exc}'
            blockers.add(key); examples[key] = roots[0]
    else:
        conversion = {'success': True, 'bytes': len(generated),
                      'draws': stats.draws, 'vertices': stats.vertices,
                      'effects': dict(stats.effects), 'omitted': dict(stats.omitted)}
        require(not blockers, f'converter passed despite census blockers: {sorted(blockers)}')
        require(stats.draws == sum(out['layouts'].values()) and
                stats.vertices == sum(out['layout_vertices'].values()), 'converter/census geometry mismatch')
    samples = {}
    for key, c in examples.items():
        start = c.offset + 8
        if key.startswith(('layout:', 'effect:')):
            start += -start % 128
        samples[key] = {'section': section.name, 'number': section.number,
                        'chunk': f'{c.kind:08x}', 'section_offset': start,
                        'stream_offset': section.offset + start,
                        'bytes64': raw[start:start + 64].hex(),
                        'sample_bytes': min(64, len(raw) - start),
                        'chunk_payload_bytes': len(c.payload),
                        'sample_note': '64 section bytes from offset; may cross a short leaf boundary'}
    exceptions = (convert.reference_exceptions(raw, section.number, providers)
                  if conversion['success'] and scenes and providers is not None and
                  not out['chunks'].get('root/80134000') else [])
    return {'number': section.number, 'section': section.name, 'offset': section.offset,
            'bytes': len(raw), 'decoded_bytes': u32(section.raw, 28), 'metrics': out, 'blockers': sorted(blockers),
            'omissions': dict(omissions), 'conversion': conversion,
            'samples': samples, 'spans': spans, 'reference_exceptions': exceptions,
            'world_pool_base_bytes': WORLD_POOL_BASE,
            'world_pool_base_fraction': len(raw) / WORLD_POOL_BASE,
            'heap_exception_literal_2500': section.number == 2500,
            'unaccounted_bytes': 0}


def indexed_census(index_bytes, stream):
    """Second derivation: raw index records -> independent envelope stack.

    Does not call section_census, walk, mesh_metrics or texture_metrics. Uses
    direct extents from the index, with material and VB grouping derived afresh.
    Per-section comparisons prevent cancellation of two incorrect section rows.
    """
    table = one(chunks(index_bytes), 0x34110).payload
    require(len(table) % 92 == 0, 'reference index record extent')
    result = {}
    with stream.open('rb') as source:
        for row in struct.iter_unpack('<92s', table):
            record = row[0]
            number = struct.unpack_from('<h', record, 8)[0]
            offset, size = struct.unpack_from('<II', record, 20)
            source.seek(offset); data = source.read(size)
            require(len(data) == size, 'reference short read')
            out, header_bytes, leaves = metrics(), 0, 0
            stack = [(0, size, None)]
            meshes, tpks = [], []
            while stack:
                start, end, parent = stack.pop()
                p = start
                while p < end:
                    require(p + 8 <= end, 'reference truncated envelope')
                    kind, n = struct.unpack_from('<II', data, p)
                    q = p + 8; stop = q + n
                    require(stop <= end, 'reference envelope crosses parent')
                    path = f'{parent:08x}/{kind:08x}' if parent is not None else f'root/{kind:08x}'
                    out['chunks'][path] += 1; out['chunk_bytes'][path] += n
                    header_bytes += 8
                    if kind & 0x80000000:
                        stack.append((q, stop, kind))
                    else:
                        out['leaf_bytes'][path] += n; leaves += n
                    if kind == 0x80134100:
                        meshes.append((q, stop))
                    if kind == 0xb3300000:
                        tpks.append((q, stop))
                    p = stop
                require(p == end, 'reference unparsed tail')
            require(header_bytes + leaves == size, 'reference byte coverage')
            for start, end in meshes:
                p, rows, buffers, mh = start, [], [], None
                while p < end:
                    kind, n = struct.unpack_from('<II', data, p)
                    q = p + 8
                    if kind == 0x134900:
                        mh = data[q + (-q % 16):q + n]
                    elif kind == 0x134b02:
                        payload = data[q + (-q % 16):q + n]
                        require(len(payload) % 104 == 0, 'reference draw extent')
                        rows = [(struct.unpack_from('<I', r, 48)[0],
                                 struct.unpack_from('<I', r, 60)[0])
                                for (r,) in struct.iter_unpack('<104s', payload)]
                    elif kind == 0x134b01:
                        buffers.append(n - (-q % 128))
                    p = q + n
                require(mh is not None and len(mh) == 48 and len(rows) == u32(mh, 16),
                        'reference mesh header')
                groups = []
                for effect, nv in rows:
                    if not groups or effect != groups[-1][0]:
                        groups.append([effect, 0, 0])
                    groups[-1][1] += nv; groups[-1][2] += 1
                require(len(buffers) == len(groups) == u32(mh, 24), 'reference vertex groups')
                layouts, effects = set(), set()
                for n, (effect, nv, draws) in zip(buffers, groups):
                    require(nv and n % nv == 0, 'reference fractional stride')
                    layout, key = str(n // nv), str(effect)
                    out['layouts'][layout] += draws; out['layout_vertices'][layout] += nv
                    out['effects'][key] += draws; out['effect_vertices'][key] += nv
                    pair = f'{layout}/{key}'
                    out['layout_effects'][pair] += draws
                    out['layout_effect_vertices'][pair] += nv
                    layouts.add(layout); effects.add(key)
                out['layout_containers'].update(layouts); out['effect_containers'].update(effects)
            for start, end in tpks:
                # Locate the header directory directly, then its two fixed arrays.
                p, rs, ps = start, None, None
                while p < end:
                    kind, n = struct.unpack_from('<II', data, p); q = p + 8
                    if kind == 0xb3310000:
                        h = q
                        while h < q + n:
                            k, length = struct.unpack_from('<II', data, h)
                            if k == 0x33310004: rs = data[h + 8:h + 8 + length]
                            if k == 0x33310005: ps = data[h + 8:h + 8 + length]
                            h += 8 + length
                    p = q + n
                require(rs is not None and ps is not None and len(rs) % 124 == 0 and
                        len(ps) == len(rs) // 124 * 32, 'reference texture extents')
                for i, (platform,) in enumerate(struct.iter_unpack('<32s', ps)):
                    key = platform[20:24].hex()
                    out['textures'][key] += 1
                    out['texture_bytes'][key] += struct.unpack_from('<I', rs, i * 124 + 56)[0]
            require(number not in result, 'reference duplicate section')
            result[number] = (size, out)
    return result


def reconcile(rows, reference):
    require(len(rows) == len(reference) and {r['number'] for r in rows} == set(reference),
            'index/walk section set mismatch')
    totals = metrics(); indexed_totals = metrics()
    for r in rows:
        size, expected = reference[r['number']]
        require(r['bytes'] == size and r['unaccounted_bytes'] == 0, 'index/walk byte mismatch')
        for name in expected:
            require(r['metrics'][name] == expected[name],
                    f"{r['section']}: index/walk {name} mismatch")
        add_metrics(totals, r['metrics']); add_metrics(indexed_totals, expected)
    require(totals == indexed_totals, 'index/walk total mismatch')
    return totals


def ranking(rows):
    affected = defaultdict(set)
    for r in rows:
        for key in r['blockers']:
            affected[key].add(r['number'])
    ranked = []
    for key, sections in affected.items():
        sole = [r['number'] for r in rows if r['blockers'] == [key]]
        sample = next((r['samples'][key] for r in rows if key in r['samples']), None)
        ranked.append({'class': key, 'sections_affected': len(sections),
                       'sections_unblocked_alone': len(sole), 'example': sample})
    return sorted(ranked, key=lambda r: (-r['sections_unblocked_alone'], -r['sections_affected'], r['class']))


def greedy_order(rows):
    """Hypothetical capability fixes; other checks and dependencies may still fail."""
    fixed, steps = set(), []
    failed = [r for r in rows if r['blockers']]
    keys = set().union(*(set(r['blockers']) for r in failed))
    while keys:
        def gain(key):
            return sum(set(r['blockers']) <= fixed | {key} and
                       not set(r['blockers']) <= fixed for r in failed)
        key = min(keys, key=lambda k: (-gain(k),
                  -sum(k in r['blockers'] for r in failed), k))
        count = gain(key)
        fixed.add(key); keys.remove(key)
        steps.append({'class': key, 'additional_sections': count,
                      'cumulative_converter_sections': sum(not r['blockers'] or
                          set(r['blockers']) <= fixed for r in rows)})
    return steps


def summarize(rows, totals):
    largest = max(rows, key=lambda r: r['bytes'])
    omitted = Counter()
    for r in rows: omitted.update(r['omissions'])
    omission_rows = []
    for path, payload_bytes in sorted(omitted.items()):
        parent_path = path.split(':', 1)[1]
        kind = int(parent_path.split('/')[-1], 16)
        omission_rows.append({'path': path, 'name': ROOT_OMITTED.get(kind, LABELS.get(kind, 'unreported body data')),
                              'chunks': totals['chunks'][parent_path], 'payload_bytes': payload_bytes,
                              'sections': sum(path in r['omissions'] for r in rows),
                              'successful_sections': sum(r['conversion']['success'] and path in r['omissions'] for r in rows)})
    return {'sections_index': len(rows), 'sections_walk': len(rows),
            'bytes_index': sum(r['bytes'] for r in rows),
            'stored_and_decoded_sizes_equal': all(r['bytes'] == r['decoded_bytes'] for r in rows),
            'bytes_walk': sum(sum(r['metrics']['leaf_bytes'].values()) +
                              8 * sum(r['metrics']['chunks'].values()) for r in rows),
            'unaccounted_bytes': sum(r['unaccounted_bytes'] for r in rows),
            'converter_successes': sum(r['conversion']['success'] for r in rows),
            'converter_failures': sum(not r['conversion']['success'] for r in rows),
            'successes_with_omissions': sum(r['conversion']['success'] and bool(r['omissions']) for r in rows),
            'successes_without_chunk_omissions': sum(r['conversion']['success'] and not r['omissions'] for r in rows),
            'distinct_chunk_ids': len({k.split('/')[1] for k in totals['chunks']}),
            'mesh_containers': sum(v for k, v in totals['chunks'].items() if k.endswith('/80134100')),
            'blocker_combinations': dict(Counter(' + '.join(r['blockers']) or 'SUCCESS' for r in rows)),
            'greedy_fix_order': greedy_order(rows),
            'o03_local': next({k: r[k] for k in ('metrics', 'conversion')} for r in rows if r['number'] == 1503),
            'scenery_numbered_sections': sum(100 <= r['number'] < 2100 for r in rows),
            'totals': totals, 'blockers_ranked': ranking(rows),
            'omitted_payload_bytes_by_path': dict(omitted),
            'data_omissions': omission_rows,
            'omission_names': {f'{k:08x}': v for k, v in ROOT_OMITTED.items()} |
                              {'00034106': 'scenery override references'},
            'unreported_nonpadding_drop_paths': [k for k in omitted if k.startswith('silently_dropped:')],
            'padding_policy': 'zero-id padding and alignment filler are regenerated, not semantic source data',
            'pool': {'world_base_bytes': WORLD_POOL_BASE, 'source': POOL_SOURCE,
                     'scope': 'world share before mode additions; not free headroom or a per-section hard cap',
                     'largest_section': largest['section'], 'largest_bytes': largest['bytes'],
                     'largest_fraction': largest['bytes'] / WORLD_POOL_BASE,
                     'largest_heap_exception': largest['heap_exception_literal_2500'],
                     'sections_above_world_base': [r['section'] for r in rows if r['bytes'] > WORLD_POOL_BASE]},
            'limitations': ['success means convert_section returned bytes, including its reported omissions',
                            'source-index providers close reference-only sections except listed Z00 rows',
                            'no load/draw or streaming proof; classified texture animation is omitted',
                            'resource sections allow no scenery/instances and optional geometry',
                            'opaque leaf spans are listed; envelope coverage is not a semantic decode',
                            'greedy gains assume each class is implemented together with its structural requirements',
                            'container counts per layout/effect overlap when a mesh uses multiple classes']}


def tsv(path, header, rows):
    with path.open('x', newline='') as f:
        writer = csv.writer(f, delimiter='\t'); writer.writerow(header); writer.writerows(rows)


def write_report(out, rows, summary):
    out = out.absolute()
    require(SCRATCH.resolve().is_relative_to(HERE.parents[1].resolve()) and
            out.is_relative_to(SCRATCH) and out != SCRATCH and
            out.resolve().is_relative_to(SCRATCH.parent.resolve() / SCRATCH.name), 'output must be a scratch child')
    require(not out.exists() and not out.is_symlink(), 'output exists')
    out.mkdir(parents=True)
    tsv(out / 'sections.tsv', ['section', 'number', 'stream_offset', 'bytes', 'decoded_bytes', 'converter_success',
                             'converted_bytes', 'converter_error', 'blockers', 'omissions',
                             'world_base_fraction', 'heap_exception', 'unaccounted_bytes'],
        ([r['section'], r['number'], r['offset'], r['bytes'], r['decoded_bytes'], int(r['conversion']['success']),
          r['conversion'].get('bytes', ''), r['conversion'].get('error', ''),
          json.dumps(r['blockers']), json.dumps(r['omissions']),
          r['world_pool_base_fraction'], int(r['heap_exception_literal_2500']), r['unaccounted_bytes']]
         for r in rows))
    all_rows = rows + [{'section': 'TOTAL', 'metrics': summary['totals']}]
    for name in ('layouts', 'effects', 'textures', 'layout_effects'):
        verts = {'layouts': 'layout_vertices', 'effects': 'effect_vertices', 'textures': 'texture_bytes', 'layout_effects': 'layout_effect_vertices'}[name]
        containers = {'layouts': 'layout_containers', 'effects': 'effect_containers'}.get(name)
        tsv(out / f'{name}.tsv', ['section', 'class', 'draws_or_textures', 'vertices_or_mip_bytes',
                                'mesh_containers', 'writer_support'],
            ([r['section'], key, value, r['metrics'][verts][key],
              r['metrics'][containers][key] if containers else '',
              (int(key) in {v[0] for v in convert.EFFECTS.values()} if name == 'layouts' else
               int(key) in convert.EFFECTS if name == 'effects' else
               tuple(map(int, key.split('/'))) in {(v[0], k) for k, v in convert.EFFECTS.items()} if name == 'layout_effects' else
               bytes.fromhex(key) in (b'DXT1', b'DXT3', b'DXT5'))]
             for r in all_rows for key, value in sorted(r['metrics'][name].items())))
    def chunk_rows():
        for r in all_rows:
            for key, count in sorted(r['metrics']['chunks'].items()):
                parent, kind = key.split('/')
                p = None if parent == 'root' else int(parent, 16)
                yield [r['section'], key, count, r['metrics']['chunk_bytes'][key],
                       r['metrics']['leaf_bytes'][key], policy(int(kind, 16), p, 'supported')]
    tsv(out / 'chunks.tsv', ['section', 'parent/chunk', 'count', 'inclusive_payload_bytes',
                            'exclusive_leaf_bytes', 'local_policy'], chunk_rows())
    tsv(out / 'spans.tsv', ['section', 'section_offset', 'stream_offset', 'payload_bytes',
                           'parent/chunk', 'policy', 'decode_scope'],
        ([r['section'], p, r['offset'] + p, n, key, disposition,
          'envelope accounted; payload semantics opaque or only partly decoded']
         for r in rows for p, n, key, disposition in r['spans']))
    tsv(out / 'reference_exceptions.tsv', ['section', 'number', 'scene', 'instance', 'model',
                                         'missing_keys', 'sentinel_only', 'classification'],
        ([r['section'], r['number'], e['scene'], e['instance'], e['model'],
          ','.join(f'{k:08x}' for k in e['missing']), int(e['sentinel_only']),
          'Z00 source key absent' if e['missing'] else 'Z00 sentinel-only instance']
         for r in rows for e in r['reference_exceptions']))
    tsv(out / 'closure_misses.tsv', ['model_key', 'stored_lod_slots', 'sections', 'classification'],
        ([r['key'], r['slots'], ','.join(r['sections']), r['classification']]
         for r in summary['source_index_closure']['misses']))
    (out / 'summary.json').write_text(json.dumps(summary, indent=2, sort_keys=True) + '\n')
    lines = [f"Index/walk: {summary['sections_index']}/{summary['sections_walk']} sections, "
             f"{summary['bytes_index']}/{summary['bytes_walk']} bytes; unaccounted=0.",
             f"Existing converter returns: {summary['converter_successes']}/720; "
             f"fails closed: {summary['converter_failures']}.",
             f"Successful outputs with omitted data: {summary['successes_with_omissions']}; "
             f"without chunk omissions: {summary['successes_without_chunk_omissions']}.",
             'Rank: sections unblocked by this class alone, then sections affected (overlapping):']
    lines += [f"{r['sections_unblocked_alone']} alone; {r['sections_affected']} affected: {r['class']}"
              for r in summary['blockers_ranked']]
    lines += ['Greedy capability order: ' + json.dumps(summary['greedy_fix_order'])]
    lines += ['Pool: ' + json.dumps(summary['pool']), 'Data omissions: ' + json.dumps(summary['data_omissions'])]
    lines += ['Metrics totals: ' + json.dumps(summary['totals'])]
    lines += ['Decode examples (section offsets, stream offsets and 64 bytes):']
    lines += [json.dumps({'class': r['class'], **r['example']}) for r in summary['blockers_ranked'] if r['example']]
    lines += summary['limitations']
    (out / 'summary.txt').write_text('\n'.join(lines) + '\n')


def source_providers(index, stream):
    """Reconcile solid header keys against directories in the source index.

    No output bytes or writer counts participate in provider discovery.
    """
    providers, local = defaultdict(set), set()
    for section in index.sections:
        for root in chunks(read_section(stream, section)):
            if root.kind != 0x80134000:
                continue
            local.add(section.number)
            parts = chunks(root.payload, root.offset + 8)
            directory = one(parts, 0x80134001)
            table = one(chunks(directory.payload, directory.offset + 8), 0x134003).payload
            expected = [r[0] for r in struct.iter_unpack('<II', table)]
            actual = []
            for solid in (c for c in parts if c.kind == 0x80134010):
                head = one(chunks(solid.payload, solid.offset + 8), 0x134011)
                actual.append(u32(convert.aligned_payload(head), 16))
            require(actual == expected, 'source solid directory/header keys')
            for key in actual:
                providers[key].add(section.number)
    return dict(providers), local


def source_reference_closure(index, stream, solid_sections, accepted):
    """Count stored model LOD slots directly from indexed source arrays.

    This includes every model-table row, independently of instance expansion.
    Missing providers are reported even in sections with ordinary local solids;
    the reference-only exception never makes those keys appear resolved.
    """
    refs, owners = Counter(), defaultdict(set)
    for section in index.sections:
        for scene in (c for c in chunks(read_section(stream, section)) if c.kind == 0x80034100):
            parts = chunks(scene.payload, scene.offset + 8)
            models = one(parts, 0x34102).payload
            require(len(models) % 72 == 0, 'closure source model-table extent')
            for p in range(0, len(models), 72):
                for off in (24, 28, 32, 36):
                    key = u32(models, p + off)
                    if key not in (0, 0xbe43edbb, 0x90f70174):
                        refs[key] += 1
                        owners[key].add(section.name)
    missing = {k for k in refs if not set(solid_sections.get(k, ())) & accepted}
    return {'model_keys': len(refs), 'stored_lod_slots': sum(refs.values()),
            'resolved_model_keys': len(refs) - len(missing),
            'resolved_stored_lod_slots': sum(n for k, n in refs.items() if k not in missing),
            'misses': [{'key': f'{k:08x}', 'slots': refs[k], 'sections': sorted(owners[k]),
                        'classification': 'source key absent' if not solid_sections.get(k)
                        else 'source providers refused conversion'} for k in sorted(missing)]}


def classify(source=DEFAULT_MW):
    index, stream, index_bytes = load_index(source, 'L2RA')
    solid_sections, local = source_providers(index, stream)
    animation_inventory = texanim.inventory_source(index, stream)
    # Local providers must pass whole-section conversion before any external
    # reference can use them. X00 therefore participates before the nine LODs.
    first = {s.number: section_census(read_section(stream, s), s,
                                     animation_inventory=animation_inventory)
             for s in index.sections if s.number in local}
    accepted = {n for n, r in first.items() if r['conversion']['success']}
    providers = solid_sections, accepted
    rows = [first[s.number] if s.number in first else
            section_census(read_section(stream, s), s, providers=providers,
                           animation_inventory=animation_inventory)
            for s in index.sections]
    reference = indexed_census(index_bytes, stream)
    totals = reconcile(rows, reference)
    summary = summarize(rows, totals)
    summary['source_index_closure'] = source_reference_closure(index, stream, solid_sections,
        {r['number'] for r in rows if r['conversion']['success']})
    return rows, summary


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--mw', type=Path, default=DEFAULT_MW)
    ap.add_argument('--out', type=Path, default=SCRATCH / 'census')
    args = ap.parse_args()
    try:
        rows, summary = classify(args.mw)
        write_report(args.out, rows, summary)
        print(f"CLASSIFY PASS: {len(rows)} sections; {summary['converter_successes']} converter successes; "
              f"{summary['bytes_walk']} bytes accounted; output {args.out}")
    except FileNotFoundError as exc:
        print(f'SKIP: private assets absent: {exc}', file=sys.stderr); return 3
    except (FormatError, OSError) as exc:
        print(f'FAIL: {exc}', file=sys.stderr); return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
