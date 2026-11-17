"""Pure-data number and composition plan for a combined world.

plan accepts index paths, in-memory TrackIndex objects without collision data,
or (TrackIndex, stream_path) pairs. Streams are read only to inventory pack IDs.
One number map covers records, boundaries, row keys/entries and drivable slots.
Output records have distinct targets. Source identities may share a target
only through an explicit checked zone/partner or resident composition bucket.
No merged archive is written. Its builder must coalesce scenery containers and
replace source byte budgets with measured converted payload sizes.
"""
import argparse
from collections import Counter
import json
import math
from pathlib import Path
import struct
import sys

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(HERE))
from formats import FormatError, TrackIndex, chunks, require, u32
import visibility as vis

LIMITS = dict(zones=780, bitmap=2800, drivable=512, row=384,
              row_cap=127, polygon=127, packs=2700, row_bytes=71680000)
CITIES = ('palmont', 'rockport')
DRIVABLE_SCHEME = ('chunk-owned variable array; loader 007A8880 C7:13293-13296; '
                  'position reader 007A03E0 C7:7135-7167; pointer readers '
                  '00557710 NFSC_005560a0.c:1006 and 00615F70 NFSC_0060ff00.c:4160 read offset/presence only')


def zone(n):
    return 100 <= n < 2100 and 1 <= n % 100 < 40


def zone_numbers(source):
    return {n for n, _ in source['boundaries'] if zone(n)} | {
        n for _, *aliases in source['aliases'] for n in aliases if zone(n)}


def number_class(n):
    if 100 <= n < 2100:
        remainder = n % 100
        return 'scenery', ('base' if 1 <= remainder < 40 else 'lod' if 40 <= remainder < 80
                           else 'high' if remainder >= 80 else 'zero')
    return 'resource', n // 100


def inventory(value, extended):
    stream = None
    if isinstance(value, tuple):
        index, stream = value
        stream = Path(stream)
    elif isinstance(value, TrackIndex):
        index = value
    else:
        path = Path(value)
        index = TrackIndex(path.read_bytes())
        stream = path.with_name('STREAM' + path.name)
    table = vis.read(vis.payload_of(index), extended=extended)
    require(table.lod_offset == 40, 'source LOD offset must be 40')
    packs, pack_storage = [], []
    if any(c.kind == 0x3b800 for c in index.parts):
        require(stream is not None, 'collision inventory requires (index, stream_path) or an index path')
        # Pack IDs are not section IDs or the source grid's family-3 words.
        from merge import read_section
        from region import collision_body
        for section in index.sections:
            for part in chunks(read_section(stream, section)):
                if part.kind == 0x3b801:
                    raw = collision_body(part)
                    require(u32(raw) == len(raw) - 16, 'collision pack extent')
                    packs.append(u32(raw, 4))
                    pack_storage.append([u32(raw, 4), section.number, len(part.payload) + 8, len(raw)])
    return dict(records=[[s.number, s.size] for s in index.sections],
                boundaries=[[b.number, len(b.vertices)] for b in table.boundaries],
                polygons={str(b.number): [list(p) for p in b.vertices] for b in table.boundaries},
                aliases=[[b.number, *struct.unpack_from('<2h', b.raw, 12)]
                         for b in table.boundaries if extended and any(b.raw[12:16])],
                rows=[[r.number, r.cap, list(r.entries)] for r in table.rows],
                drivable=list(table.drivable), packs=sorted(packs), pack_storage=pack_storage,
                lod_offset=table.lod_offset)


def source_numbers(source):
    numbers = {n for n, _ in source['records']} | {n for n, _ in source['boundaries']}
    numbers.update(source['drivable'])
    numbers.update(n for _, *aliases in source['aliases'] for n in aliases if n)
    for n, _, entries in source['rows']:
        numbers.add(n)
        numbers.update(entries)
    # A zone's partner identity must follow even if it has no stream record.
    numbers.update(n + 40 for n in zone_numbers(source))
    return numbers


def census(sources):
    by_city = {}
    for city in CITIES:
        source = sources[city]
        records = dict(source['records'])
        zones = {n for n, _ in source['boundaries'] if zone(n)}
        by_city[city] = dict(zones=len(zones), zone_identities=len(zone_numbers(source)), records=len(records),
            paired_zones=sum(n + 40 in records for n in zones),
            boundaries=len(source['boundaries']), rows=len(source['rows']),
            drivable=len(source['drivable']), unique_drivable=len(set(source['drivable'])),
            packs=len(source['packs']), bitmap=max(source_numbers(source), default=-1) + 1,
            row=max((len(e) for _, _, e in source['rows']), default=0),
            polygon=max((v for _, v in source['boundaries']), default=0),
            row_bytes=max((sum(records.get(n, 0) for n in entries)
                           for _, _, entries in source['rows']), default=0))
    result = dict(cities=by_city)
    for key in ('zones', 'zone_identities', 'records', 'paired_zones', 'boundaries', 'rows', 'drivable', 'unique_drivable', 'packs'):
        result[key] = sum(c[key] for c in by_city.values())
    for key in ('bitmap', 'row', 'polygon', 'row_bytes'):
        result[key] = max(c[key] for c in by_city.values())
    a, b = (sources[c] for c in CITIES)
    result['record_collisions'] = len(dict(a['records']).keys() & dict(b['records']).keys())
    result['pack_collisions'] = len(set(a['packs']) & set(b['packs']))
    return result


def pack_allocation(sources):
    used = set(sources['palmont']['packs'])
    result = {'palmont': {str(n): n for n in used}, 'rockport': {}}
    # Reserve all noncolliding source IDs before relocating colliding IDs.
    used.update(sources['rockport']['packs'])
    free = iter(n for n in range(1, LIMITS['packs']) if n not in used)
    for n in sources['rockport']['packs']:
        target = next(free, None) if n in result['palmont'].values() else n
        require(target is not None, 'collision pack IDs exhausted')
        result['rockport'][str(n)] = target
    return result


def cross(a, b, c):
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def inside(point, polygon):
    x, y = point
    result = False
    for a, b in zip(polygon, polygon[1:] + polygon[:1]):
        if (a[1] > y) != (b[1] > y) and x < (b[0] - a[0]) * (y - a[1]) / (b[1] - a[1]) + a[0]:
            result = not result
    return result


def polygon_union(a, b):
    """Trace union boundary segments; reject disconnected, touching or holed rings.

    Split every edge at all crossings. Retain a directed segment only when its
    left/right probes differ in union membership, with interior to the left.
    Quantization is 1e-5 world units, below source float32 precision here.
    """
    rings = [a, b]
    edges = [(p, q) for ring in rings for p, q in zip(ring, ring[1:] + ring[:1]) if p != q]
    segments = set()
    for p, q in edges:
        dx, dy = q[0] - p[0], q[1] - p[1]
        length2 = dx * dx + dy * dy
        cuts = {0., 1.}
        for r, s in edges:
            rx, ry = s[0] - r[0], s[1] - r[1]
            den = dx * ry - dy * rx
            if abs(den) > 1e-8:
                t = ((r[0] - p[0]) * ry - (r[1] - p[1]) * rx) / den
                u = ((r[0] - p[0]) * dy - (r[1] - p[1]) * dx) / den
                if -1e-8 <= t <= 1 + 1e-8 and -1e-8 <= u <= 1 + 1e-8:
                    cuts.add(max(0., min(1., t)))
            elif abs(cross(p, q, r)) < 1e-4:
                for z in (r, s):
                    t = ((z[0] - p[0]) * dx + (z[1] - p[1]) * dy) / length2
                    if 0 <= t <= 1:
                        cuts.add(t)
        cuts = sorted(cuts)
        for t, u in zip(cuts, cuts[1:]):
            if u - t < 1e-8:
                continue
            start, end = (p[0] + dx * t, p[1] + dy * t), (p[0] + dx * u, p[1] + dy * u)
            mx, my = (start[0] + end[0]) / 2, (start[1] + end[1]) / 2
            ox, oy = -dy / math.sqrt(length2) * 1e-4, dx / math.sqrt(length2) * 1e-4
            left = any(inside((mx + ox, my + oy), ring) for ring in rings)
            right = any(inside((mx - ox, my - oy), ring) for ring in rings)
            if left == right:
                continue
            if right:
                start, end = end, start
            segments.add((tuple(round(x, 5) for x in start), tuple(round(x, 5) for x in end)))
    graph = {}
    for start, end in sorted(segments):
        if start in graph and graph[start] != end:
            return None
        graph[start] = end
    if not graph:
        return None
    start = min(graph)
    point, ring = start, []
    while point in graph:
        ring.append(point)
        point = graph.pop(point)
    if point != start or graph:
        return None
    ring = [p for i, p in enumerate(ring) if abs(cross(ring[i - 1], p, ring[(i + 1) % len(ring)])) > 1e-3]
    return [list(p) for p in ring] if 3 <= len(ring) <= LIMITS['polygon'] else None


def merge_groups(source, count):
    polygons = {n: source['polygons'][str(n)] for n in zone_numbers(source)}
    groups = {n: dict(members=[n], tree=n, polygon=polygon) for n, polygon in polygons.items()}
    bounds = {n: (min(p[0] for p in poly), min(p[1] for p in poly),
                  max(p[0] for p in poly), max(p[1] for p in poly)) for n, poly in polygons.items()}
    centers = {n: ((a + c) / 2, (b + d) / 2) for n, (a, b, c, d) in bounds.items()}
    numbers = sorted(groups)
    sizes = dict(source['records'])
    visible = {n: {row for row, _, entries in source['rows'] if n in entries or n + 40 in entries}
               for n in numbers}
    def cost(a, b):
        extra = ((sizes.get(a, 0) + sizes.get(a + 40, 0)) * len(visible[b] - visible[a]) +
                 (sizes.get(b, 0) + sizes.get(b + 40, 0)) * len(visible[a] - visible[b]))
        return extra, math.dist(centers[a], centers[b])
    edges = sorted((cost(a, b), a, b)
                   for i, a in enumerate(numbers) for b in numbers[i + 1:]
                   if bounds[a][0] <= bounds[b][2] and bounds[b][0] <= bounds[a][2]
                   and bounds[a][1] <= bounds[b][3] and bounds[b][1] <= bounds[a][3])
    parent = {n: n for n in numbers}
    def root(n):
        while parent[n] != n:
            n = parent[n]
        return n
    for _, a, b in edges:
        if len(groups) <= count:
            break
        a, b = root(a), root(b)
        if a == b or len(groups[a]['members']) + len(groups[b]['members']) > 3:
            continue
        polygon = polygon_union(groups[a]['polygon'], groups[b]['polygon'])
        if polygon is None:
            continue
        left, right = groups[a], groups.pop(b)
        groups[a] = dict(members=sorted(left['members'] + right['members']),
                         tree=[left['tree'], right['tree']], polygon=polygon)
        parent[b] = a
    require(len(groups) <= count, 'not enough bounded polygon unions; no infeasibility claim')
    return sorted(groups.values(), key=lambda g: min(g['members']))


def composed_allocation(sources):
    """A data composition schedule; output records have unique numbers."""
    native = source_numbers(sources['palmont'])
    slots = [n for n in range(101, 2040) if zone(n) and n not in native and n + 40 not in native]
    groups = merge_groups(sources['rockport'], len(slots))
    mapping = {}
    numbers = dict(palmont={str(n): n for n in sorted(native)}, rockport=mapping)
    used = set(native)
    for group, target in zip(groups, slots):
        group['number'] = target
        for n in group['members']:
            mapping[str(n)], mapping[str(n + 40)] = target, target + 40
        used.update((target, target + 40))
    # Keep the native global model resident small. The older model resident is
    # requested explicitly by every older-city row, at unused resource U00.
    require(2100 not in used, 'U00 already occupied')
    mapping.update({'2400': 2100, '2500': 2500, '2600': 2600})
    used.add(2100)
    for n in sorted(source_numbers(sources['rockport'])):
        if str(n) in mapping:
            continue
        if n not in used:
            target = n
        else:
            target = next((v for v in range(100, 2800) if v not in used and
                           (v % 100 >= 80 and v < 2100 if n < 2100 else v >= 2101)), None)
        require(target is not None, 'number allocation exhausted')
        mapping[str(n)] = target
        used.add(target)
    buckets = {}
    removed = Counter()
    for _, section, size, _ in sources['rockport']['pack_storage']:
        removed[section] += size
    for city in CITIES:
        for n, size in sources[city]['records']:
            target = numbers[city][str(n)]
            item = buckets.setdefault(target, dict(number=target, members=[], bytes=0))
            item['members'].append([city, n])
            size -= removed[n] if city == 'rockport' else 0
            require(size >= 0, 'pack chunks exceed source section')
            item['bytes'] += (size + 127) // 128 * 128 + 128
    pack_bytes = sum((size + 8 + 15) // 16 * 16 for _, _, _, size in sources['rockport']['pack_storage'])
    buckets[2600]['bytes'] += pack_bytes
    for group in groups:
        n = group['number']
        group['scene_owners'] = [[n, n if n in buckets else n + 40], [n + 40, n + 40]]
    records = sorted(buckets.values(), key=lambda r: r['number'])
    sizes = {r['number']: r['bytes'] for r in records}
    rows = []
    for city in CITIES:
        original = {n: entries for n, _, entries in sources[city]['rows']}
        sets = [(n, [n]) for n in original] if city == 'palmont' else [(g['number'], g['members']) for g in groups]
        for number, members in sets:
            entries = ([numbers[city][str(n)] for n in original[number]] if city == 'palmont' else
                       sorted({numbers[city][str(n)] for old in members for n in original[old]} | {2100}))
            requested = set(entries) | {2400, 2500, 2600}
            rows.append(dict(city=city, number=number, members=members, entries=sorted(entries),
                             pool_bytes=sum(sizes.get(n, 0) for n in requested if n != 2500)))
            if city == 'palmont':
                rows[-1]['entries'] = entries
    drivable = list(sources['palmont']['drivable'])
    drivable += sorted({mapping[str(n)] for n in sources['rockport']['drivable']})
    return numbers, dict(groups=groups, records=records, rows=rows, drivable=drivable,
        drivable_slots=max(512, (len(drivable) + 63) // 64 * 64),
        drivable_scheme=DRIVABLE_SCHEME,
        pack_resident_bytes=pack_bytes,
        composition='Union polygons/rows; coalesce scenery across both buckets by mapped N/N+40 identity and scene_owners. Keep providers in their buckets; every base request also requests its partner. Move all source collision packs to 2600.',
        resources='U00 carries the older X00 and is explicit in every older-city row; Y00/Z00 compose both residents; other resource collisions use free non-scenery IDs.',
        bytes_basis='Source sizes minus relocated pack chunks, rounded to 128 plus 128 per source record; packs at 2600 padded to 16. Scene bytes may migrate between paired buckets; rows request both when base is needed. Includes X00/Z00, excludes main-heap Y00. Converted sizes require readback.')


def plain_allocation(sources):
    """Small-input control: no merges, fixed offset and fixed native identities."""
    native = source_numbers(sources['palmont'])
    result = {'palmont': {str(n): n for n in sorted(native)}, 'rockport': {}}
    mapping, used = result['rockport'], set(native)
    available = [n for n in range(101, 2040) if zone(n)]
    for n in sorted(zone_numbers(sources['rockport'])):
        target = next((v for v in [n] + available if v not in used and v + 40 not in used), None)
        require(target is not None, 'zone/partner slots exhausted')
        mapping[str(n)], mapping[str(n + 40)] = target, target + 40
        used.update((target, target + 40))
    for n in sorted(source_numbers(sources['rockport'])):
        if str(n) in mapping:
            continue
        # Do not change resource-letter semantics or cross the native classes.
        def same_class(v):
            if 100 <= n < 2100:
                return 100 <= v < 2100 and ((n % 100) // 40 == (v % 100) // 40) and v % 100 != 0
            return n // 100 == v // 100
        require(n not in (2400, 2500, 2600) or n not in used,
                'resident payload composition required; cannot renumber a resident')
        target = next((v for v in [n] + list(range(100, 2800)) if same_class(v) and v not in used), None)
        require(target is not None, 'section number class exhausted')
        mapping[str(n)] = target
        used.add(target)
    return result


def plan(mw_index, carbon_index):
    sources = dict(palmont=inventory(carbon_index, True), rockport=inventory(mw_index, False))
    counts = census(sources)
    if counts['zone_identities'] > LIMITS['zones']:
        numbers, composition = composed_allocation(sources)
    else:
        numbers = plain_allocation(sources)
        composition = None
    result = dict(version=1, outcome='A', feasible=True,
                  lod_offset=40, limits=dict(LIMITS), sources=sources, counts=counts,
                  numbers=numbers, packs=pack_allocation(sources))
    if composition is not None:
        result['composition'] = composition
    check(result)
    return result


def check_composition(document):
    sources, numbers = document['sources'], document['numbers']
    composition = document['composition']
    require(composition['drivable_scheme'] == DRIVABLE_SCHEME, 'variable-array reader evidence missing')
    groups = composition['groups']
    covered, targets = set(), set()
    allowed = {2500: {('palmont', 2500), ('rockport', 2500)},
               2600: {('palmont', 2600), ('rockport', 2600)}}
    def replay(tree):
        if type(tree) is int:
            require(zone(tree) and str(tree) in sources['rockport']['polygons'], 'invalid merge tree leaf')
            return sources['rockport']['polygons'][str(tree)], [tree]
        require(isinstance(tree, list) and len(tree) == 2, 'invalid merge tree')
        left, a = replay(tree[0])
        right, b = replay(tree[1])
        polygon = polygon_union(left, right)
        require(polygon is not None, 'merge polygon is disconnected, holed or exceeds 127 vertices')
        return polygon, a + b
    for group in groups:
        target, members = group['number'], group['members']
        require(zone(target), 'zone outside A..T / 01..39 (x40 and U forbidden)')
        require(target not in targets and target + 40 not in targets, 'duplicate output zone number')
        require(1 <= len(members) <= 3 and len(set(members)) == len(members), 'invalid merge members')
        require(not covered.intersection(members), 'source zone merged twice')
        polygon, leaves = replay(group['tree'])
        require(sorted(leaves) == members, 'merge tree differs from members')
        require(group['polygon'] == polygon and 3 <= len(polygon) <= 127, 'merged polygon differs from source union')
        for n in members:
            require(numbers['rockport'][str(n)] == target, 'zone assigned outside declared merge (duplicate number)')
            require(numbers['rockport'][str(n + 40)] == target + 40, 'N+40 partner left behind')
        allowed[target] = {('rockport', n) for n in members}
        allowed[target + 40] = {('rockport', n + 40) for n in members}
        covered.update(members)
        targets.update((target, target + 40))
    require(covered == zone_numbers(sources['rockport']), 'zone merge coverage incomplete')
    owners = {}
    for city in CITIES:
        for old, target in numbers[city].items():
            require(type(target) is int and 0 <= target < LIMITS['bitmap'], 'number outside 2800-bit bitmap')
            owners.setdefault(target, set()).add((city, int(old)))
            if city == 'rockport' and int(old) not in covered and int(old) - 40 not in covered:
                require((100 <= target < 2100 and target % 100 >= 80) if int(old) < 2100
                        else 2100 <= target < 2800, 'section/resource class changed')
    for target, members in owners.items():
        if len(members) > 1:
            require(members == allowed.get(target), 'duplicate number outside explicit composition')
    require(numbers['rockport']['2400'] == 2100 and numbers['rockport']['2500'] == 2500 and
            numbers['rockport']['2600'] == 2600, 'resident composition/relocation changed')
    expected_records = {}
    removed = Counter()
    for _, section, size, _ in sources['rockport']['pack_storage']:
        removed[section] += size
    for city in CITIES:
        for n, size in sources[city]['records']:
            target = numbers[city][str(n)]
            bucket = expected_records.setdefault(target, dict(members=[], bytes=0))
            bucket['members'].append([city, n])
            size -= removed[n] if city == 'rockport' else 0
            require(size >= 0, 'pack chunks exceed source section')
            bucket['bytes'] += (size + 127) // 128 * 128 + 128
    pack_bytes = sum((size + 8 + 15) // 16 * 16 for _, _, _, size in sources['rockport']['pack_storage'])
    expected_records[2600]['bytes'] += pack_bytes
    require(composition['pack_resident_bytes'] == pack_bytes, 'resident pack byte accounting changed')
    for group in groups:
        n = group['number']
        require(group['scene_owners'] == [[n, n if n in expected_records else n + 40], [n + 40, n + 40]],
                'scenery identity has wrong physical owner')
    records = composition['records']
    require(len({r['number'] for r in records}) == len(records), 'duplicate output record number')
    require({r['number'] for r in records} == expected_records.keys(), 'record bucket coverage incomplete')
    for record in records:
        expected = expected_records[record['number']]
        require(record['members'] == expected['members'] and record['bytes'] == expected['bytes'],
                'record composition members/bytes changed')
        require(record['bytes'] < 2**32, 'record byte extent exceeds u32')
    rows = composition['rows']
    expected_keys = {('palmont', n) for n, _, _ in sources['palmont']['rows']}
    expected_keys.update(('rockport', g['number']) for g in groups)
    require(len({r['number'] for r in rows}) == len(rows), 'duplicate output row number')
    require({(r['city'], r['number']) for r in rows} == expected_keys, 'row coverage incomplete')
    groups_by_target = {g['number']: g for g in groups}
    for row in rows:
        city = row['city']
        original = {n: entries for n, _, entries in sources[city]['rows']}
        members = ([row['number']] if city == 'palmont' else groups_by_target[row['number']]['members'])
        require(row['members'] == members, 'row provenance differs')
        entries = ([numbers[city][str(n)] for n in original[row['number']]] if city == 'palmont' else
                   sorted({numbers[city][str(n)] for member in members for n in original[member]} | {2100}))
        require(len(row['entries']) <= 384, 'row exceeds 384 entries')
        require(len(row['entries']) <= 127, 'row exceeds signed cap 127')
        require(row['entries'] == entries, 'row entries differ from mapped source union')
        require(all(n + 40 in entries for n in entries if n in groups_by_target),
                'base scenery request lacks partner providers')
        source_records = dict(sources[city]['records'])
        for member in members:
            for old in original[member]:
                require(numbers[city][str(old)] in expected_records or old not in source_records,
                        'new absent row entry')
        requested = set(entries) | {2400, 2500, 2600}
        pool_bytes = sum(expected_records.get(n, {}).get('bytes', 0) for n in requested if n != 2500)
        require(row['pool_bytes'] == pool_bytes, 'row byte accounting changed')
        require(pool_bytes <= LIMITS['row_bytes'], 'row exceeds pool byte budget')
    native_drive = sources['palmont']['drivable']
    expected_drive = native_drive + sorted({numbers['rockport'][str(n)] for n in sources['rockport']['drivable']})
    require(composition['drivable'] == expected_drive, 'drivable entry coverage changed')
    require(all(zone(n) for n in expected_drive), 'drivable number outside zone range')
    slots = max(512, (len(expected_drive) + 63) // 64 * 64)
    require(composition['drivable_slots'] == slots and 8 + slots * 2 < 2**32, 'drivable chunk capacity invalid')
    native_zone_count = len(zone_numbers(sources['palmont']))
    require(native_zone_count + len(groups) <= 780, 'more than 780 zone identities')
    native_bounds = {n for n, _ in sources['palmont']['boundaries']}
    other_bounds = {numbers['rockport'][str(n)] for n, _ in sources['rockport']['boundaries'] if not zone(n)}
    require(not (targets & native_bounds or targets & other_bounds or native_bounds & other_bounds),
            'duplicate output boundary number')
    counts = dict(zones=document['counts']['cities']['palmont']['zones'] + len(groups),
        zone_identities=native_zone_count + len(groups), records=len(records),
        boundaries=len(native_bounds) + len(groups) + len(other_bounds), rows=len(rows),
        bitmap=max(owners, default=-1) + 1, drivable=len(expected_drive), drivable_slots=slots,
        packs=document['counts']['packs'], row=max(len(r['entries']) for r in rows),
        polygon=max(max(nv for _, nv in sources['palmont']['boundaries']), max(len(g['polygon']) for g in groups)),
        row_bytes=max(r['pool_bytes'] for r in rows), merges=len(covered) - len(groups))
    return dict(outcome='A', feasible=True, duplicate_numbers=0, counts=counts)


def check(document):
    """Validate output identities and declared many-to-one compositions.

    Source identity namespaces are separate between cities and between sections
    and collision packs. Repeated references to one identity are not duplicates.
    """
    require(document['version'] == 1 and document['limits'] == LIMITS, 'unsupported schema/limits')
    require(document['lod_offset'] == 40, 'LOD offset changes native pairs')
    require(set(document['sources']) == set(CITIES), 'city inventory incomplete')
    sources = document['sources']
    counts = census(sources)
    require(document['counts'] == counts, 'census differs from source inventory')
    for city in CITIES:
        source = sources[city]
        require(source['lod_offset'] == 40, 'source offset differs')
        for field in ('records', 'boundaries', 'rows'):
            keys = [row[0] for row in source[field]]
            require(len(set(keys)) == len(keys), f'duplicate source {field}')
        require(all(type(size) is int and size >= 0 for _, size in source['records']), 'invalid record bytes')
        require(all(3 <= nv <= LIMITS['polygon'] for _, nv in source['boundaries']), 'polygon exceeds 127 vertices')
        require(set(source['polygons']) == {str(n) for n, _ in source['boundaries']}, 'source polygon inventory incomplete')
        require(all(len(source['polygons'][str(n)]) == nv and
                    all(math.isfinite(x) for point in source['polygons'][str(n)] for x in point)
                    for n, nv in source['boundaries']), 'source polygon count/coordinates differ')
        records = dict(source['records'])
        bounds = dict(source['boundaries'])
        rows = {n for n, _, _ in source['rows']}
        zones = zone_numbers(source)
        require((zones | set(source['drivable'])) <= rows, 'drivable zone without a row')
        alias_numbers = {n for _, *aliases in source['aliases'] for n in aliases if n}
        require(all(n in bounds for n, *_ in source['aliases']), 'alias has no primary boundary')
        require(all(zone(n) for n in alias_numbers), 'alternate zone outside zone range')
        require(set(source['drivable']) <= bounds.keys() | alias_numbers, 'drivable entry without boundary')
        require(all(zone(n) for n in source['drivable']), 'source drivable number outside zone range')
        for _, cap, entries in source['rows']:
            require(len(entries) <= LIMITS['row'], 'row exceeds 384 entries')
            require(len(entries) <= cap <= LIMITS['row_cap'], 'row exceeds signed cap 127')
            require(sum(records.get(n, 0) for n in entries) <= LIMITS['row_bytes'], 'row exceeds pool byte budget')
        universe = source_numbers(source)
        require(all(type(n) is int and 0 <= n < LIMITS['bitmap'] for n in universe), 'source exceeds 2800-bit bitmap')
        require(set(document['numbers'][city]) == {str(n) for n in universe}, 'number map incomplete')
        packs = source['packs']
        require(len(set(packs)) == len(packs) and all(0 < n < LIMITS['packs'] for n in packs), 'source pack IDs invalid')
        require(set(document['packs'][city]) == {str(n) for n in packs}, 'pack map incomplete')
        storage = source['pack_storage']
        if storage or 'composition' in document:
            require(sorted(n for n, *_ in storage) == sorted(packs), 'pack storage inventory incomplete')
            require(all(section in records and 0 < size <= records[section] and 16 <= raw_size < size
                        for _, section, size, raw_size in storage), 'invalid pack storage extent')

    pack_targets = []
    for city in CITIES:
        for old, target in document['packs'][city].items():
            require(type(target) is int and 0 < target < LIMITS['packs'], 'pack ID outside 1..2699')
            require(city != 'palmont' or target == int(old), 'native pack changed')
            pack_targets.append(target)
    require(len(set(pack_targets)) == len(pack_targets), 'duplicate pack number')
    require(len(pack_targets) < LIMITS['packs'], 'pack table exhausted')
    for old, target in document['numbers']['palmont'].items():
        require(target == int(old), 'native number changed')

    require(document['outcome'] == 'A' and document['feasible'] is True, 'unsupported allocation outcome')
    if 'composition' in document:
        return check_composition(document)
    require(counts['zone_identities'] <= LIMITS['zones'], 'more than 780 zones')
    require(counts['drivable'] <= LIMITS['drivable'], 'more than 512 drivable slots')
    owners = {}
    target_records = set()
    for city in CITIES:
        mapping = document['numbers'][city]
        for old, target in mapping.items():
            require(type(target) is int and 0 <= target < LIMITS['bitmap'], 'number outside 2800-bit bitmap')
            require(target not in owners, 'duplicate number assigned to two identities')
            owners[target] = city, int(old)
        for old in zone_numbers(sources[city]):
            target = mapping[str(old)]
            require(zone(target), 'zone outside A..T / 01..39 (x40 and U forbidden)')
            require(mapping[str(old + 40)] == target + 40, 'N+40 partner left behind')
        for old, target in mapping.items():
            require(number_class(int(old)) == number_class(target), 'number changes section/resource class')
            require(int(old) not in (2400, 2500, 2600) or target == int(old), 'hardcoded resident changed')
        target_records.update(mapping[str(n)] for n, _ in sources[city]['records'])
    for city in CITIES:
        records = dict(sources[city]['records'])
        mapping = document['numbers'][city]
        source_absent = Counter((row, n) for row, _, entries in sources[city]['rows']
                                for n in entries if n not in records)
        target_absent = Counter((row, n) for row, _, entries in sources[city]['rows']
                                for n in entries if mapping[str(n)] not in target_records)
        require(source_absent == target_absent, 'row entry resolution/absence changed')
    require(len(target_records) <= LIMITS['bitmap'], 'record count exceeds bitmap')
    return dict(outcome='A', feasible=True, duplicate_numbers=0, counts=counts)


def summary(document):
    verdict = check(document)
    counts = verdict['counts']
    composed = document.get('composition')
    groups = len(composed['groups']) if composed else counts['cities']['rockport']['zones']
    merges = counts.get('merges', 0)
    return [
        'outcome A; pure data; feasible=True',
        f"source primary zones {document['counts']['zones']}/780",
        f"output primary zones {counts['zones']}; identities {counts['zone_identities']}/780",
        f"records {counts['records']}; bitmap extent {counts['bitmap']}/2800 bits; duplicate numbers 0",
        (f"drivable {counts['drivable']}/{counts['drivable_slots']} slots; chunk-owned array, linked-list reader"
         if composed else f"drivable {counts['drivable']}/512 slots"),
        f"rows {counts['rows']}; largest {counts['row']}/384; signed cap 127",
        f"largest polygon {counts['polygon']}/127 vertices",
        f"largest per-row pool budget {counts['row_bytes']}/71680000 bytes",
        f"packs {counts['packs']}/2700; duplicate allocated IDs 0",
        f"Rockport zone groups {groups}; merges {merges}; at most 3 source zones/group",
        'N/N+40 pairs compose together; LOD offset stays 40',
        ('Palmont numbers stay; Y00/Z00 compose; Rockport X00 moves to explicitly requested U00'
         if composed else 'Palmont numbers stay; no payload composition needed'),
        '17 C7 offset references audited; no larger offset or executable hook',
        'byte budgets use padded source sizes; converted sizes need builder readback',
        'number/composition plan only; merged archives are the next job',
    ]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mw-index', type=Path, default=vis.DEFAULT_MW)
    parser.add_argument('--carbon-index', type=Path, default=vis.DEFAULT_CARBON)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(argv)
    paths = [args.mw_index, args.carbon_index]
    paths += [p.with_name('STREAM' + p.name) for p in paths]
    if not all(p.is_file() for p in paths):
        print('private index/stream assets absent', file=sys.stderr)
        return 3
    try:
        output = args.out.resolve()
        checkout = HERE.parents[1]
        require(not output.is_relative_to(checkout), '--out must be outside the checkout')
        require(not any(output.is_relative_to(p.parent.resolve()) for p in paths), 'output overlaps private inputs')
        document = plan(args.mw_index, args.carbon_index)
        with output.open('x') as f:
            json.dump(document, f, sort_keys=True, separators=(',', ':'))
            f.write('\n')
        print('\n'.join(summary(document)))
    except (FormatError, OSError) as exc:
        print(f'number plan failed: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
