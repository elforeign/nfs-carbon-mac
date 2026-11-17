"""Build and independently reread a complete native-coordinate track pair offline.

Checks use the written pair and source archives, never proof.json or conversion
counters. Source files establish existing visibility absences, reference misses,
and unchanged world coordinates. Outputs belong in a new external scratch dir.
"""
import argparse
from collections import Counter, defaultdict
import json
import math
import os
from pathlib import Path
import shutil
import statistics
import struct
import sys
import tempfile

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(HERE))
import rockport_track as track
import collision
import visibility
import convert
import classify
import ground
import props
import region
import texanim
import closure as dependencies
import zones as zone_tables
import districts
from formats import Chunk, Section, TrackIndex, chunks, require, u32
from merge import DEFAULT_MW, DEFAULT_CARBON, load_index, read_section
from validate import validate_section, validate_resources, validate_translation

BITMAP_BYTES = 350  # 007A260E..007A262C: 0xaf0 bits, 0x57 dwords + one word
POOL_BYTES = 0x445c000
RESIDENTS = set(track.ALWAYS_LOADED)
COLLISION = {0x3b801, 0x3b802}
WITHOUT = {'events': 0x80036000, 'emitters': 0x3bc00,
           'resident-textures': 0xb3300000}
SENTINELS = {0, 0xbe43edbb, 0x90f70174}
KEEP = {0x34112, 0x80034147, 0x34250, 0x8003b000, 0x34110,
        0x34113, 0x34111, 0x34108, 0x34109, 0x3b800, 0x3414d}


def children(chunk):
    return chunks(chunk.payload, chunk.offset + 8)


def record(old, offset, size):
    """Retain all metadata, including opaque +32/+52; rewrite only +20/+24/+28."""
    raw = bytearray(old.raw)
    struct.pack_into('<III', raw, 20, offset, size, size)
    return Section(bytes(raw))


def omit(data, number, classes):
    """Replace dropped chunks with equal-size padding, preserving inner alignment."""
    kinds = {WITHOUT[c] for c in classes if c != 'resident-textures' or number in RESIDENTS}
    return b''.join(Chunk(0, bytes(len(c.payload))).encode() if c.kind in kinds else c.encode()
                    for c in chunks(data))


def resource_view(data):
    return b''.join(Chunk(0, bytes(len(c.payload))).encode() if c.kind in COLLISION else c.encode()
                    for c in chunks(data))


def assemble(source, source_stream, template, converted, *, without=(), shift_number=None,
             shift_x=0, additions=None, rows='providers-first'):
    """Convert all indexed sections; the shift arguments are failure controls."""
    require(set(without) <= WITHOUT.keys(), 'unknown omitted class')
    providers, _ = classify.source_providers(source, source_stream)
    providers = providers, {s.number for s in source.sections}
    animation = texanim.inventory_source(source, source_stream)
    prop_import = props.Import(source,source_stream,template)
    if additions is None:
        inventory = Inventory(source, source_stream)
        census = dependencies.census_sources(Path(source_stream).parent, dependencies.wanted_keys(inventory))
        additions = dependencies.resident_additions(dependencies.classify(inventory, census), census)
    # Reuse the collision-only composition, including the exact native scaffold.
    base_index, base_stream = track.build(template, converted)
    resident = {s.number: base_stream[s.offset:s.offset + s.size]
                for s in TrackIndex(base_index).sections}
    metadata = {s.number: s for s in template.sections if s.number in RESIDENTS}
    stream, records, sizes = convert.Builder(0), [], []
    for old in source.sections:
        raw = read_section(source_stream, old)
        data, stats = convert.convert_section(raw, old.number,
            shift_x=shift_x if old.number == shift_number else 0,
            source_number=old.number, providers=providers, animation_inventory=animation)
        data = prop_import.section(data)
        for kind in (props.SPAWNS,props.BINDINGS):
            stats.omitted.pop(f'{kind:08x}',None)
        converted_size = len(data)
        if old.number in (2500, 2600):
            combined = convert.Builder(0)
            combined.data += resident[old.number]
            combined.pad(128)
            combined.data += data
            data = bytes(combined.data)
        if additions.get(old.number):
            combined = convert.Builder(0)
            combined.data += data
            for extra in additions[old.number]:
                combined.pad(128)
                writer = convert.convert_tpk if extra.kind == 0xb3300000 else convert.convert_list
                combined.data += writer(extra, combined.position, stats)
            data = bytes(combined.data)
        data = omit(data, old.number, without)
        sizes.append(dict(number=old.number, source=old.size, converted=converted_size,
                          written=len(data), omitted=dict(stats.omitted)))
        stream.pad(2048)
        records.append(record(metadata.get(old.number, old), stream.position, len(data)))
        stream.data += data
    index = convert.Builder(0)
    for top in template.parts:
        if top.kind == visibility.CONTAINER:
            index.pad(16)
            index.add(top.kind, visibility.convert(source, rows=rows))
        elif top.kind in props.GLOBALS:
            prop_import.append_global(index,top.kind)
        elif top.kind in KEEP:
            index.pad(16)
            if top.kind == 0x34110:
                index.add(top.kind, b''.join(s.raw for s in records))
            elif top.kind == 0x3b800:
                index.add(top.kind, converted.map_data, 16)
            else:
                index.add(top.kind, top.payload)
    for kind in sorted(props.GLOBALS-{c.kind for c in template.parts}):
        prop_import.append_global(index,kind)
    return bytes(index.data), bytes(stream.data), sizes


class Inventory:
    """Read providers and references directly from indexed source or written bytes.

    Directory references include unused slots. First-texture references decode
    each material's byte +24 as an index into its own solid's 8-byte key table.
    Model entries include every LOD slot, even rows no instance selects.
    """
    def __init__(self, index, stream, *, target=False):
        self.models, self.textures = defaultdict(set), defaultdict(set)
        self.model_refs, self.texture_refs = defaultdict(list), defaultdict(list)
        self.first_texture_refs = defaultdict(list)
        self.instances = Counter()
        for section in index.sections:
            roots = chunks(read_section(stream, section))
            for scene_id, scene in enumerate(c for c in roots if c.kind == 0x80034100):
                parts = children(scene)
                table = region.one(parts, 0x34102).payload
                rows = convert.aligned_payload(region.one(parts, 0x34103))
                stride, selector = (96, 84) if target else (64, 62)
                selected = defaultdict(list)
                for p in range(0, len(rows), stride):
                    model = struct.unpack_from('<h', rows, p + selector)[0]
                    selected[model].append(p // stride)
                self.instances[section.number] += len(rows) // stride
                for p in range(0, len(table), 72):
                    for lod, off in enumerate((24, 28, 32, 36)):
                        key = u32(table, p + off)
                        if key not in SENTINELS:
                            self.model_refs[key].append(dict(section=section.number, scene=scene_id,
                                model=p // 72, lod=lod, instances=selected[p // 72]))
            for root in roots:
                if root.kind == 0xb3300000:
                    hp = children(region.one(children(root), 0xb3310000))
                    for key, _ in struct.iter_unpack('<II', region.one(hp, 0x33310002).payload):
                        self.textures[key].add(section.number)
                elif root.kind == 0x80134000:
                    for solid in (c for c in children(root) if c.kind == 0x80134010):
                        parts = children(solid)
                        key = u32(convert.aligned_payload(region.one(parts, 0x134011)), 16)
                        self.models[key].add(section.number)
                        mesh = region.one(parts, 0x80134100)
                        names = [c.payload.split(b'\0')[0].decode('utf-8', errors='replace')
                                 for c in children(mesh) if c.kind == 0x134c02]
                        keys = [k for k, _ in struct.iter_unpack('<II', region.one(parts, 0x134012).payload)]
                        materials = convert.aligned_payload(region.one(children(mesh), 0x134b02))
                        width = 144 if target else 104
                        require(len(materials) % width == 0, 'inventory material stride')
                        for material, p in enumerate(range(0, len(materials), width)):
                            slot = materials[p + 24]
                            require(slot < len(keys), 'inventory first texture index')
                            self.first_texture_refs[keys[slot]].append(dict(section=section.number,
                                solid=f'{key:08x}', mesh=0, material=material))
                        for slot, texture in enumerate(keys):
                            self.texture_refs[texture].append(dict(section=section.number,
                                solid=f'{key:08x}', mesh=0, texture_slot=slot, material_names=names))

    def closure(self):
        def summarize(refs, providers):
            missing = sorted(refs.keys() - providers.keys())
            return dict(keys=len(refs), resolved=len(refs) - len(missing),
                        misses=[dict(key=f'{k:08x}', references=refs[k]) for k in missing])
        reachable = {key: refs for key, refs in self.texture_refs.items()
                     if any(int(r['solid'], 16) in self.model_refs for r in refs)}
        return dict(models=summarize(self.model_refs, self.models),
                    textures=summarize(reachable, self.textures),
                    all_mesh_textures=summarize(self.texture_refs, self.textures))


def collision_check(index, stream, source=None, source_stream=None):
    """Project only reread collision bytes onto the existing loader-shaped checker.

    Rewrapping aligned collision roots changes no body byte. Scenery/resources
    are checked separately and the ground oracle reads the original full pair.
    """
    projection = TrackIndex(index.encode())
    records, data, actual_cells, actual_packs = [], convert.Builder(0), [], {}
    for section in index.sections:
        roots = chunks(read_section(stream, section))
        found = [c for c in roots if c.kind in COLLISION]
        require(not found or section.number in (2500, 2600), 'collision outside resident section')
        for c in found:
            body = region.collision_body(c)
            if c.kind == 0x3b802:
                actual_cells.extend(region.collision_cells(body[16:],
                    region.collision_tags(body[16:], 0x41727469)[collision.CGCN]))
            else:
                require(u32(body, 4) not in actual_packs, 'duplicate collision pack')
                actual_packs[u32(body, 4)] = body
        if section.number not in RESIDENTS:
            continue
        data.pad(2048)
        offset = data.position
        for c in found:
            data.pad(16)
            data.data += c.encode()
        if not found:
            data.add(0, b'')
        records.append(record(section, offset, data.position - offset))
    projection.sections = records
    checked = track.check_track(projection.encode(), bytes(data.data))
    if source is not None:
        raw = region.collision_body(region.one(source.parts, 0x3b800))
        tags = region.collision_tags(raw, collision.CDAT)
        expected_cells = []
        for cell in region.collision_cells(raw, tags[collision.CGCN]):
            cell = bytearray(cell)
            struct.pack_into('<H', cell, 6, 2500)
            expected_cells.append(bytes(cell))
        require(actual_cells == expected_cells, 'collision cells differ from source')
        expected_packs = {}
        for section in source.sections:
            for c in chunks(read_section(source_stream, section)):
                if c.kind == 0x3b801:
                    body = region.collision_body(c)
                    expected_packs[u32(body, 4)] = body
        require(actual_packs == expected_packs, 'collision packs differ from source')
        source_desc = collision.tag_data(raw, tags[collision.CGRD])
        built = region.collision_body(region.one(index.parts, 0x3b800))
        desc = collision.tag_data(built, region.collision_tags(built, collision.CDAT)[collision.CGRD])
        require(desc[:32] == source_desc[:32] and desc[32:] == struct.pack('<II', 0, 1),
                'collision descriptor differs from source/native layout')
    return checked


def pool_rows(index, table):
    sizes = {s.number: s.size for s in index.sections}
    rows = [dict(number=r.number, bytes=sum(sizes[n] for n in
                    ({2400, 2600} | set(r.entries)) - {2500} if n in sizes)) for r in table.rows]
    values = [r['bytes'] for r in rows]
    return dict(base_bytes=POOL_BYTES, largest=max(values, default=0),
                median=statistics.median(values) if values else 0,
                rows_over=sum(v > POOL_BYTES for v in values), rows=rows)


def point_in_polygon(point, vertices):
    x, y = point
    inside = False
    for (ax, ay), (bx, by) in zip(vertices, vertices[1:] + vertices[:1]):
        cross = (x - ax) * (by - ay) - (y - ay) * (bx - ax)
        if abs(cross) < 1e-5 and min(ax, bx) <= x <= max(ax, bx) and min(ay, by) <= y <= max(ay, by):
            return True
        if (ay > y) != (by > y) and x < ax + (y - ay) * (bx - ax) / (by - ay):
            inside = not inside
    return inside


def zone_at(index, x, y):
    require(math.isfinite(x) and math.isfinite(y), 'non-finite render position')
    table = visibility.read(visibility.payload_of(index))
    # 007A03E0 visits drivable boundaries, including those outside the slot list.
    zones = [b for b in table.boundaries if 100 <= b.number < 2100
             and 1 <= b.number % 100 < table.lod_offset and point_in_polygon((x, y), b.vertices)]
    require(zones, 'render point has no drivable zone')
    boundary = zones[0]
    row = next((r for r in table.rows if r.number == boundary.number), None)
    require(row is not None, 'drivable zone has no row')
    sizes = {s.number: s.size for s in index.sections}
    return dict(render_xy=[x, y], zone=boundary.number, entries=list(row.entries),
                entries_with_record=sum(n in sizes for n in row.entries),
                summed_bytes=sum(sizes.get(n, 0) for n in row.entries),
                overlapping_zones=[b.number for b in zones])


def check_scaffold(index, template, source, carbon_root=DEFAULT_CARBON):
    """Accept native scaffolding, source identity, or fully bound districts."""
    actual = [c for c in index.parts if c.kind]
    native = [c for c in template.parts if c.kind in KEEP | {visibility.CONTAINER} | props.GLOBALS]
    if any(c.kind in (props.BOUNDS,props.HIERARCHIES) for c in actual):
        native += [Chunk(k,b'') for k in sorted(props.GLOBALS-{c.kind for c in template.parts})]
    populated = any(c.kind == zone_tables.MARKERS for c in actual)
    expected = native
    if populated:
        expected = [part for c in native for part in
                    ((c, Chunk(zone_tables.MARKERS, b'')) if c.kind == zone_tables.ZONES else (c,))]
    require([c.kind for c in actual] == [c.kind for c in expected],
            'index scaffold kinds/order differ')
    converted = {c.kind: c.payload for c in zone_tables.convert(source)} if populated else {}
    patterns = districts.traffic_patterns(carbon_root) if populated else {}
    if populated and next(c.payload for c in actual if c.kind == zone_tables.ZONES) != converted[zone_tables.ZONES]:
        converted = {c.kind: c.payload for c in zone_tables.convert(
            source, key_map=districts.key_map(source, carbon_root))}
    for written, scaffold in zip(actual, expected):
        require(written.offset % 16 == (scaffold.offset % 16 if written.kind in props.GLOBALS else 0), 'index scaffold header misaligned')
        if written.kind in converted:
            require(written.payload == converted[written.kind],
                    f'global chunk {written.kind:#x} differs from source conversion')
        elif written.kind not in (0x34110, 0x3b800, visibility.CONTAINER, *props.GLOBALS):
            require(written.payload == scaffold.payload, 'native scaffold payload differs')
    if populated:
        measured = zone_tables.check(zone_tables.select(index))
        result = {key: measured[key] for key in ('zones', 'markers', 'barriers')}
        rows = [z for z in zone_tables.read(zone_tables.select(index)).zones if z.kind == 9]
        result['districts_bound'] = f'{sum(z.key in patterns for z in rows)}/{len(rows)}'
        return result
    return dict(zones=0, markers=0, barriers=0)


def check(directory, mw_root=DEFAULT_MW, carbon_root=DEFAULT_CARBON, *, rows='providers-first'):
    """Reread files, independently checking metadata, payloads and source identity."""
    tracks = Path(directory) / 'TRACKS'
    index, stream, raw_index = load_index(tracks, 'L2RA')
    source, source_stream, _ = load_index(mw_root, 'L2RA')
    template, _, _ = load_index(carbon_root, 'L5RB')
    old = {s.number: s for s in source.sections}
    residents = {s.number: s for s in template.sections if s.number in RESIDENTS}
    require([s.number for s in index.sections] == [s.number for s in source.sections],
            'written record identities/order differ from source')
    require(RESIDENTS <= old.keys(), 'always-loaded record missing')
    require(index.encode() == raw_index, 'index round trip differs')
    global_counts = check_scaffold(index, template, source, carbon_root)
    expected = 0
    for section in index.sections:
        require(0 <= section.number < BITMAP_BYTES * 8, 'record exceeds requested bitmap')
        expected = (expected + 2047) // 2048 * 2048
        require(section.offset == expected, f'{section.number}: noncanonical stream offset')
        require(section.size > 0 and u32(section.raw, 28) == section.size, 'plain record size differs')
        require(section.raw == record(residents.get(section.number, old[section.number]),
                                     section.offset, section.size).raw, 'copied record metadata differs')
        expected += section.size
    require(expected == stream.stat().st_size, 'unindexed stream tail')
    table_payload = visibility.payload_of(index)
    vis = visibility.check(table_payload, {s.number for s in index.sections}, source_index=source, rows=rows)
    require(vis['absent_entries_equal_source'], 'visibility absences differ from source')
    require(table_payload == visibility.convert(source, rows=rows), 'visibility differs from source conversion')
    table = visibility.read(table_payload)
    require(all(0 <= n < BITMAP_BYTES * 8 for r in table.rows for n in r.entries),
            'row number exceeds requested bitmap')
    source_inventory = Inventory(source, source_stream)
    written_inventory = Inventory(index, stream, target=True)
    census = dependencies.census_sources(mw_root, dependencies.wanted_keys(source_inventory))
    classes = dependencies.classify(source_inventory, census)
    closure, baseline = written_inventory.closure(), source_inventory.closure()
    for name in ('models', 'textures'):
        refs = written_inventory.model_refs if name == 'models' else written_inventory.texture_refs
        before = source_inventory.model_refs if name == 'models' else source_inventory.texture_refs
        expected_keys = {0x1f389568 if name == 'models' and k == 0xed85ba82 else k for k in before}
        require(refs.keys() == expected_keys, f'{name} reference keys changed')
        missing = {r['key'] for r in closure[name]['misses']}
        expected_missing = {r['key'] for r in classes if r['kind'] == name and r['class'] == 'absent-in-source'}
        require(missing == expected_missing,
                f'{name} closure fell: resolved {closure[name]["resolved"]}/{closure[name]["keys"]}; '
                f'source {baseline[name]["resolved"]}/{baseline[name]["keys"]}')
        by_key = {r['key']: r for r in classes if r['kind'] == name}
        for row in closure[name]['misses']:
            row.update({k: v for k, v in by_key[row['key']].items() if k not in ('kind', 'references', 'sections')})
    classification = dependencies.check_providers(index, stream, source_inventory, written_inventory, classes, census)
    counts, translation = Counter(), Counter()
    providers = written_inventory.models, set(old)
    for section in index.sections:
        data = resource_view(read_section(stream, section))
        scenes = any(c.kind == 0x80034100 for c in chunks(data))
        measured, _ = (validate_section(data, section.number, providers=providers) if scenes
                       else validate_resources(data, section.number))
        counts.update(measured)
        # Events/emitters may be deliberately dropped; spatial scenery never is.
        source_data = read_section(source_stream, old[section.number])
        absent = {kind for kind in (0x80036000, 0x3bc00)
                  if not any(c.kind == kind for c in chunks(data))}
        source_data = b''.join(Chunk(0, bytes(len(c.payload))).encode() if c.kind in absent else c.encode()
                               for c in chunks(source_data))
        checked = validate_translation(source_data, data, 0,
                                      source_number=section.number, target_number=section.number)
        translation['spatial_components_checked'] += checked['spatial_components_checked']
        translation['maximum_translation_error_m'] = max(translation['maximum_translation_error_m'],
                                                       checked['maximum_translation_error_m'])
    prop_report = props.check(index,stream,source,source_stream,template)
    collisions = collision_check(index, stream, source, source_stream)
    original_world = ground.World(source, source_stream)
    original_measurement = ground.measure_nodes(original_world)
    world = ground.World(index, stream)
    require(world.nodes == original_world.nodes, 'road nodes differ from source')
    measurement = ground.measure_nodes(world)
    require(track.summary(measurement) == track.summary(original_measurement), 'node grounding differs from source')
    starts = track.select_starts(world, measurement)
    pool = pool_rows(index, table)
    require(not pool['rows_over'], 'visibility row exceeds base pool')
    return dict(records=len(index.sections), props=prop_report, visibility=vis, collision=collisions, zones=global_counts,
                closure=closure, classification=classification, pool=pool, counts=dict(counts), translation=dict(translation),
                ground=track.summary(measurement), starts=starts,
                start_zero_zone=zone_at(index, *starts[0]['render_xyz'][:2]),
                outputs={name: track.source_proof(tracks / name, 'written output')
                         for name in ('L2RA.BUN', 'STREAML2RA.BUN')})


def prepare(output, mw_root=DEFAULT_MW, carbon_root=DEFAULT_CARBON, *, without=(), zones=False,
            rows='providers-first'):
    out = Path(output).expanduser().resolve()
    roots = (Path(mw_root).resolve(), Path(carbon_root).resolve())
    require(not out.is_relative_to(track.ROOT.resolve()), 'outputs must be outside the checkout')
    require(not any((p / '.git').exists() for p in (out, *out.parents)), 'outputs must be outside every checkout')
    require(all(not out.is_relative_to(r) and not r.is_relative_to(out) for r in roots), 'output overlaps source')
    require(not out.exists(), 'output already exists')
    source, source_stream, _ = load_index(mw_root, 'L2RA')
    district_map = districts.key_map(source, carbon_root) if zones else None
    inventory = Inventory(source, source_stream)
    census = dependencies.census_sources(mw_root, dependencies.wanted_keys(inventory))
    classes = dependencies.classify(inventory, census)
    additions = dependencies.resident_additions(classes, census)
    native, _, _ = load_index(carbon_root, 'L5RA')
    template, _, _ = load_index(carbon_root, 'L5RB')
    converted = collision.convert(source, source_stream, native)
    index, stream, sizes = assemble(source, source_stream, template, converted, without=without,
                                   additions=additions, rows=rows)
    if zones:
        index = zone_tables.rewrite_index(index, zone_tables.convert(source, key_map=district_map))
    out.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.rockworld-', dir=out.parent))
    try:
        tracks = stage / 'TRACKS'
        tracks.mkdir()
        (tracks / 'L2RA.BUN').write_bytes(index)
        (tracks / 'STREAML2RA.BUN').write_bytes(stream)
        del index, stream
        failure = None
        try:
            checked = check(stage, mw_root, carbon_root, rows=rows)
        except ValueError as exc:
            if 'resident-textures' not in without or not str(exc).startswith('textures closure fell:'):
                raise
            failure = str(exc)
            idx, stream_path, _ = load_index(tracks, 'L2RA')
            world = ground.World(idx, stream_path)
            measurement = ground.measure_nodes(world)
            checked = dict(closure=Inventory(idx, stream_path, target=True).closure(),
                           zones=check_scaffold(idx, template, source, carbon_root),
                           classification=dict(rows=classes, classified=len(classes), census=census.summary),
                           ground=track.summary(measurement), starts=track.select_starts(world, measurement),
                           outputs={name: track.source_proof(tracks / name, 'written output')
                                    for name in ('L2RA.BUN', 'STREAML2RA.BUN')})
            checked['start_zero_zone'] = zone_at(idx, *checked['starts'][0]['render_xyz'][:2])
        for name, info in checked['outputs'].items():
            info['path'] = str(out / 'TRACKS' / name)
        proof = dict(track=2000, region='L2RA', base='L2RA', renumbered=False, shift=[0, 0, 0],
                     collision_only=False, without=sorted(without), zones=zones, rows=rows, bitmap_bytes=BITMAP_BYTES,
                     sections=sizes, validation=checked, checker_failure=failure,
                     sources=[track.source_proof(Path(mw_root) / 'L2RA.BUN', 'source index'),
                              track.source_proof(source_stream, 'source stream')],
                     unproven=['Carbon loading and rendering', 'special rows 1512 / 226',
                               'stored material bindings do not count frame submissions'])
        proof.update(starts=checked['starts'], ground=checked['ground'], outputs=checked['outputs'],
                     number=checked['start_zero_zone']['zone'],
                     camera=dict(render_eye=checked['starts'][0]['render_xyz'],
                                 render_target=[checked['starts'][0]['render_xyz'][0] + 10,
                                                *checked['starts'][0]['render_xyz'][1:]]))
        # Existing probe requires these counts to be zero. O3 source misses
        # remain explicitly available in closure; a broken texture pair refuses
        # that probe precondition and carries the keys for its failure control.
        proof['validation']['dependencies'] = {
            'new_missing_' + kind: checked['closure'][kind]['keys'] - checked['closure'][kind]['resolved']
            - sum(r['kind'] == kind and r['class'] == 'absent-in-source' for r in classes)
            for kind in ('models', 'textures')}
        (stage / 'proof.json').write_text(json.dumps(proof, indent=2) + '\n')
        os.rename(stage, out)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    return proof


def compact(checked):
    return {key: ({k: v for k, v in checked[key].items() if k != 'rows'} if key == 'pool'
                  else {kind: {k: v for k, v in row.items() if k != 'misses'}
                        for kind, row in checked[key].items()} if key == 'closure'
                  else checked[key]) for key in ('records', 'visibility', 'collision', 'closure', 'pool', 'zones', 'props')
            if key in checked}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--out', type=Path)
    action.add_argument('--check', type=Path)
    parser.add_argument('--mw-root', type=Path, default=DEFAULT_MW)
    parser.add_argument('--carbon-root', type=Path, default=DEFAULT_CARBON)
    parser.add_argument('--without', default='', help='comma-separated events,emitters,resident-textures')
    parser.add_argument('--zones', action='store_true', help='populate global zones, markers and barriers; requires --out')
    parser.add_argument('--rows', choices=visibility.ROW_ORDERS, default=visibility.ROW_ORDERS[0])
    parser.add_argument('--zone-at', help='render x,y; requires --check')
    args = parser.parse_args(argv)
    try:
        without = tuple(filter(None, args.without.split(',')))
        require(set(without) <= WITHOUT.keys(), 'unknown omitted class')
        require(not args.check or not without, '--without requires --out')
        require(not args.zones or args.out, '--zones requires --out')
        require(not args.zone_at or args.check, '--zone-at requires --check')
        if args.out:
            proof = prepare(args.out, args.mw_root, args.carbon_root, without=without, zones=args.zones, rows=args.rows)
            result = compact(proof['validation'])
            result.update(output=str(args.out), without=proof['without'], checker_failure=proof['checker_failure'])
        else:
            result = compact(check(args.check, args.mw_root, args.carbon_root, rows=args.rows))
            if args.zone_at:
                x, y = map(float, args.zone_at.split(','))
                idx, _, _ = load_index(args.check / 'TRACKS', 'L2RA')
                result['zone_at'] = zone_at(idx, x, y)
        print(json.dumps(result, sort_keys=True))
    except FileNotFoundError as exc:
        print(f'SKIP: private assets absent: {exc}', file=sys.stderr)
        return 3
    except (OSError, ValueError, KeyError, StopIteration, struct.error) as exc:
        print(f'FAIL: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
