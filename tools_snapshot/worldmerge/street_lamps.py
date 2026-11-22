"""Optional imported street-lamp bulb markers and authored highway tunnel lights.

Markers use the target's type 6, identity basis and default flare selector.
The native producer subtracts the solid pivot before the instance transform.
Each inserted suffix occupies 128 bytes, preserving every old alignment.
"""
from collections import Counter
import math
from pathlib import Path
import shutil
import struct
import sys

from formats import Chunk, chunks, require, u32
from merge import load_index, read_section
from convert import aligned_payload

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import daynight_inventory as inventory
import daynight_lamps as geometry

SOLIDS, SOLID, HEADER, MARKERS = 0x80134000, 0x80134010, 0x134011, 0x13401a
BULBS = ('bright', 'storelit', 'obj_light_', 'obj_lightglobe_', 'obj_lgt_')
HIGHWAY_ARCHIVE = 1375
HIGHWAY_ROWS = (1334, 1335)  # Both tunnel visibility rows load the same archive.
HIGHWAY_CONTEXTS = ('trn_ct_road_highway4aux_', 'trn_ct_props_highway4aux_')
TUNNEL_LIGHT_PREFIX = b'x360_tunnel_'


def coast_tunnel_lights(shift):
    from c3_crossing import COAST_SHIFT
    if shift != COAST_SHIFT:
        return ()
    import x360_auxlights
    archive = x360_auxlights.DEFAULT_X360 / 'STREAML2RA_PERM.BUN'
    if not archive.is_file():
        return ()
    contexts = x360_auxlights.extract_contexts(archive)
    # The road and wall contexts reference the same emitters. Merge by the
    # original eight float words so overlapping contexts cannot double energy.
    lights = {light for name, records in contexts if name.lower().startswith(HIGHWAY_CONTEXTS)
              for light in records}
    require(lights, 'missing authored highway tunnel contexts')
    return tuple(sorted(lights))


def _tunnel_tree(records):
    # Carbon LIGHT_TREE (e.g. L5RA archive 1045): a 16-byte header followed
    # by 48-byte nodes. Positive counts index nodes, negative counts index
    # lights. The query uses only the first matching leaf (0069FB80/0069FAD0).
    capacity = 10
    points = [struct.unpack_from('<4f', records, off + 16)
              for off in range(0, len(records), 96)]
    require(0 < len(points) <= capacity**2, 'highway light tree exceeds two branch levels')
    order = sorted(range(len(points)), key=lambda i: points[i][0])
    groups = [order[i:i + capacity] for i in range(0, len(order), capacity)]

    def node(center, extent, parent, count, refs):
        return struct.pack('<3fHh3f10h', *center, parent, count, *extent,
                           *refs, *([0] * (capacity - len(refs))))

    def branch(indices, parent, refs):
        lights = [points[i] for i in indices]
        # Round outward so the stored float box encloses each child even
        # when the midpoint of the child bounds needs float32 rounding.
        lo = [math.floor(min(p[axis] - p[3] for p in lights)) for axis in range(3)]
        hi = [math.ceil(max(p[axis] + p[3] for p in lights)) for axis in range(3)]
        center = [(a + b) * .5 for a, b in zip(lo, hi)]
        extent = [(b - a) * .5 for a, b in zip(lo, hi)]
        return node(center, extent, parent, len(refs), refs)

    branches = len(groups) + 1
    tree = bytearray(struct.pack('<4x4H4x', len(points), branches, branches + len(points), 3))
    tree += branch(order, 0xffff, range(1, branches))
    first_leaf = branches
    for group in groups:
        tree += branch(group, 0, range(first_leaf, first_leaf + len(group)))
        first_leaf += len(group)

    for parent, group in enumerate(groups, 1):
        for index in group:
            *center, radius = points[index]
            # Another light can reach this leaf even when its own leaf is
            # visited later. Include all overlapping range boxes and let
            # Carbon apply the spherical range test to each reference.
            refs = [index]
            for other, (*xyz, other_radius) in enumerate(points):
                if other != index and all(abs(a - b) <= radius + other_radius
                                          for a, b in zip(center, xyz)):
                    refs.append(other)
            require(len(refs) <= capacity, 'too many overlapping highway light ranges')
            tree += node(center, (radius,) * 3, parent, -len(refs), refs)
    return tree


def tunnel_pack(base, source_lights, shift):
    import zlib
    from convert import Builder
    records = bytearray()
    dx, dy = shift[1], -shift[0]
    for source in source_lights:
        x, y, z, radius, r, g, b, intensity = struct.unpack('<8f', source)
        rgb = [round(v * 255) for v in (r, g, b)]
        require(1 <= radius <= 100 and intensity > 0 and all(0 <= v <= 255 for v in rgb),
                'invalid source tunnel light')
        key = zlib.crc32(source)
        row = bytearray(96)
        struct.pack_into('<I4B', row, 0, key, 2, 0, 0, 1)
        struct.pack_into('<3B', row, 12, *rgb)
        struct.pack_into('<4f', row, 16, x + dx, y + dy, z, radius)
        struct.pack_into('<f', row, 44, intensity)
        name = TUNNEL_LIGHT_PREFIX + f'{key:08x}'.encode('ascii')
        row[62:62 + len(name)] = name
        records += row
    pack = Builder(base + 8)
    pack.add(0x135001, struct.pack('<8xH2xI12xI', 4, HIGHWAY_ARCHIVE, len(source_lights)), 16)
    pack.add(0x135002, _tunnel_tree(records), 16)
    pack.add(0x135003, records, 16)
    return Chunk(inventory.LIGHT_PACK, bytes(pack.data), base).encode()


def source_solids(root, wanted):
    _, stream, _ = load_index(root, 'L2RA')
    found = {}
    for top in inventory.stream_tops(stream):
        if top.kind != SOLIDS:
            continue
        for solid in chunks(top.payload, top.offset+8):
            if solid.kind != SOLID:
                continue
            h = aligned_payload(next(p for p in chunks(solid.payload, solid.offset+8) if p.kind == HEADER))
            key = u32(h, 16)
            if key in wanted:
                value = (h, geometry.mesh_draws(solid, False))
                if key in found:
                    require(found[key][0] == h, 'conflicting lamp solid')
                found[key] = value
    require(wanted <= found.keys(), 'missing referenced lamp LOD geometry')
    return found


def specifications(root):
    """Writer inventory: named source placements, all four referenced LOD slots."""
    index, stream, _ = load_index(root, 'L2RA')
    wanted = set()
    for section in index.sections:
        for scene in chunks(read_section(stream, section)):
            if scene.kind != 0x80034100:
                continue
            _, rows = inventory.model_candidates(scene)
            models = next(p.payload for p in chunks(scene.payload, scene.offset+8) if p.kind == 0x34102)
            for row in rows:
                wanted.update(k for k in struct.unpack_from('<4I', models, row['model_index']*72+24) if k)
    result = {}
    for key, (header, draws) in source_solids(root, wanted).items():
        bulbs = [v for name, v in draws if any(t in name.lower() for t in BULBS)]
        if bulbs:
            points = geometry.np.concatenate(bulbs)
            anchor = (points.min(axis=0)+points.max(axis=0))/2
        else:
            anchor = geometry.head_candidates(draws)['mesh_arm_end']
        pivot = struct.unpack_from('<3f', header, 112)
        result[key] = tuple(float(a)+p for a, p in zip(anchor, pivot))
    return result


def marker(key, position):
    matrix = [1.,0.,0.,0., 0.,1.,0.,0., 0.,0.,1.,0., *position,1.]
    return struct.pack('<4I16f', key, 6, 0, 0, *matrix)


def marker_matches(raw, key, position):
    """Reader's native schema check, independent of the marker serializer."""
    if len(raw) != 80 or struct.unpack_from('<4I', raw) != (key, 6, 0, 0):
        return False
    basis = struct.unpack_from('<12f', raw, 16)
    xyz, affine = struct.unpack_from('<3f', raw, 64), struct.unpack_from('<f', raw, 76)[0]
    quantized = struct.unpack('<3f', struct.pack('<3f', *position))
    return basis == (1,0,0,0,0,1,0,0,0,0,1,0) and xyz == quantized and affine == 1


def cache_words(root, specs):
    """Source +60 is a hash; target 0079A910 uses its low bits as a lazy cache."""
    index, stream, _ = load_index(root, 'L2RA')
    result = {}
    for section in index.sections:
        for scene in chunks(read_section(stream, section)):
            if scene.kind != 0x80034100:
                continue
            models = next(p.payload for p in chunks(scene.payload, scene.offset+8) if p.kind == 0x34102)
            for off in range(0, len(models), 72):
                row = models[off:off+72]
                if any(k in specs for k in struct.unpack_from('<4I', row, 24)):
                    require(row[:40] not in result or result[row[:40]] == u32(row, 60),
                            'conflicting source lamp cache word')
                    result[row[:40]] = u32(row, 60)
    return result


def _suffix(key, xyz, offset):
    body = b'\x11' * (-(offset+8) % 16) + marker(key, xyz)
    leaf = Chunk(MARKERS, body).encode()
    return leaf + Chunk(0, bytes(128-len(leaf)-8)).encode()


def transform(raw, specs, *, remove=False, caches=None):
    """Change only solid suffixes and ancestor extents; retain old payload bytes."""
    def visit(part):
        if part.kind == 0x80034100 and caches:
            children = []
            for child in chunks(part.payload, part.offset+8):
                body = bytearray(child.payload)
                if child.kind == 0x34102:
                    for off in range(0, len(body), 72):
                        identity = bytes(body[off:off+40])
                        if identity in caches:
                            word = u32(body, off+60)
                            if remove:
                                require(word & 3 == 0, 'lamp flare eligibility cache not reset')
                            value = (word & ~3) | (caches[identity] & 3 if remove else 0)
                            struct.pack_into('<I', body, off+60, value)
                children.append(Chunk(child.kind, bytes(body)).encode())
            return Chunk(part.kind, b''.join(children)).encode()
        if part.kind == SOLID:
            children = chunks(part.payload, part.offset+8)
            header = aligned_payload(next(p for p in children if p.kind == HEADER))
            key = u32(header, 16)
            if key not in specs:
                return part.encode()
            if remove:
                require(len(children) >= 2 and children[-2].kind == MARKERS and children[-1].kind == 0,
                        f'lamp {key:08x}: missing marker suffix')
                require(len(children[-2].encode())+len(children[-1].encode()) == 128,
                        'lamp suffix extent differs')
                raw_marker = aligned_payload(children[-2])
                require(len(raw_marker) == 80, 'lamp marker count differs')
                require(marker_matches(raw_marker, key, specs[key]), f'lamp {key:08x}: marker identity/geometry differs')
                require(not any(children[-1].payload), 'lamp suffix filler differs')
                body = part.payload[:-128]
            else:
                require(not any(p.kind == MARKERS for p in children), 'source lamp already has markers')
                body = part.payload + _suffix(key, specs[key], part.offset+8+len(part.payload))
            return Chunk(part.kind, body).encode()
        if part.kind == SOLIDS:
            return Chunk(part.kind, b''.join(visit(p) for p in chunks(part.payload, part.offset+8))).encode()
        return part.encode()
    return b''.join(visit(p) for p in chunks(raw))


def rewrite(directory, specs, *, remove=False, destination=None, caches=None,
            tunnel_lights=(), shift=(0., 0.)):
    """Repack indexed sections without changing their metadata or payload order."""
    import c1_world as world
    tracks = Path(directory)/'TRACKS'
    index, stream, _ = load_index(tracks, 'L5RA')
    if tunnel_lights:
        import visibility
        table = visibility.read(visibility.payload_of(index))
        visible = {row.number for row in table.rows if HIGHWAY_ARCHIVE in row.entries}
        require(set(HIGHWAY_ROWS) <= visible and any(s.number == HIGHWAY_ARCHIVE for s in index.sections),
                'highway light archive is outside tunnel visibility')
    target = Path(destination)/'TRACKS' if destination else tracks
    target.mkdir(parents=True, exist_ok=True)
    temporary = target/'STREAML5RA.BUN.lamps'
    records = []
    with temporary.open('wb') as output:
        for section in index.sections:
            raw = read_section(stream, section)
            highway = tunnel_lights and section.number == HIGHWAY_ARCHIVE
            if highway and remove:
                tail = chunks(raw)[-1]
                require(tail.encode() == tunnel_pack(tail.offset, tunnel_lights, shift),
                        'highway light pack differs from source')
                raw = raw[:tail.offset]
            raw = transform(raw, specs, remove=remove, caches=caches)
            if highway and not remove:
                require(not any(c.kind == inventory.LIGHT_PACK for c in chunks(raw)),
                        'highway light pack already present')
                raw += tunnel_pack(len(raw), tunnel_lights, shift)
            output.write(bytes(-output.tell() % 2048))
            row = bytearray(section.raw)
            struct.pack_into('<III', row, 20, output.tell(), len(raw), len(raw))
            records.append(bytes(row))
            output.write(raw)
    out = world.convert.Builder(0)
    for part in index.parts:
        if part.kind == 0x34110:
            part = Chunk(part.kind, b''.join(records), part.offset)
        world.append_at_residue(out, part)
    (target/'L5RA.BUN').write_bytes(out.data)
    temporary.replace(target/'STREAML5RA.BUN')
    if destination:
        shutil.copytree(Path(directory)/'GLOBAL', Path(destination)/'GLOBAL', dirs_exist_ok=True)


def apply(directory, mw_root, *, shift=(0., 0.)):
    specs = specifications(mw_root)
    rewrite(directory, specs, caches=cache_words(mw_root, specs),
            tunnel_lights=coast_tunnel_lights(shift), shift=shift)


def oracle(root):
    """Independent completeness/position oracle, without the writer inventory."""
    index, stream, _ = load_index(root, 'L2RA')
    lods = set()
    placements = 0
    for section in index.sections:
        for scene in chunks(read_section(stream, section)):
            if scene.kind != 0x80034100:
                continue
            parts = chunks(scene.payload, scene.offset+8)
            models = next(p.payload for p in parts if p.kind == 0x34102)
            instances = aligned_payload(next(p for p in parts if p.kind == 0x34103))
            for off in range(0, len(instances), 64):
                model = struct.unpack_from('<h', instances, off+62)[0]*72
                name = models[model:model+24].split(b'\0')[0].lower()
                if any(t in name for t in (b'streetlight', b'lightpost', b'lightpole', b'parklamp', b'ironlampstanding')):
                    placements += 1
                    lods.update(h for h in struct.unpack_from('<4I', models, model+24) if h)
    expected = {}
    for key, (header, draws) in source_solids(root, lods).items():
        selected = [v for name, v in draws if any(t in name.lower() for t in
                    ('bright', 'storelit', 'obj_light_', 'obj_lightglobe_', 'obj_lgt_'))]
        if selected:
            # Scalar extrema deliberately do not use the writer's array reduction.
            xyz = [(min(float(p[a]) for v in selected for p in v)+
                    max(float(p[a]) for v in selected for p in v))/2 for a in range(3)]
        else:
            xyz = geometry.head_candidates(draws)['mesh_arm_end']
        expected[key] = tuple(float(x)+p for x, p in zip(xyz, struct.unpack_from('<3f', header, 112)))
    return expected, placements


def census(directory, expected, *, validate=True):
    """C-LOD marker coverage plus conservative loaded-row scene-flare demand."""
    import visibility
    index, stream, _ = load_index(Path(directory)/'TRACKS', 'L5RA')
    markers, seen, scenes = {}, Counter(), {}
    for section in index.sections:
        raw = read_section(stream, section)
        for root in chunks(raw):
            if root.kind == SOLIDS:
                for solid in chunks(root.payload, root.offset+8):
                    if solid.kind != SOLID:
                        continue
                    parts = chunks(solid.payload, solid.offset+8)
                    key = u32(aligned_payload(next(p for p in parts if p.kind == HEADER)), 16)
                    records = [aligned_payload(p) for p in parts if p.kind == MARKERS]
                    markers[key] = sum(len(p)//80 for p in records)
                    if key in expected:
                        correct = len(records) == 1 and marker_matches(records[0], key, expected[key])
                        if validate:
                            require(correct, f'lamp {key:08x}: missing or incorrect marker')
                        if correct:
                            seen[key] += 1
            elif root.kind == 0x80034100:
                parts = chunks(root.payload, root.offset+8)
                models = next(p.payload for p in parts if p.kind == 0x34102)
                if validate:
                    for p in range(0, len(models), 72):
                        if any(k in expected for k in struct.unpack_from('<4I', models, p+24)):
                            require(u32(models, p+60) & 3 == 0, 'lamp flare eligibility cache not reset')
                rows = aligned_payload(next(p for p in parts if p.kind == 0x34103))
                scenes[section.number] = scenes.get(section.number, []) + [
                    struct.unpack_from('<I', models, 72*struct.unpack_from('<h', rows, p+84)[0]+32)[0]
                    for p in range(0, len(rows), 96)]
    if validate:
        require(set(seen) == set(expected), 'missing referenced lamp LOD (including C)')
    table = visibility.read(visibility.payload_of(index))
    rows = []
    for row in table.rows:
        keys = [key for n in set(row.entries)|{2400,2500,2600} for key in scenes.get(n, [])]
        rows.append(dict(row=row.number, imported=sum(k in seen for k in keys),
                         expected_imported=sum(k in expected for k in keys),
                         total=sum(markers.get(k, 0) for k in keys)))
    densest = max(rows, key=lambda r: r['total'])
    return dict(lod_solids=len(seen), marker_copies=sum(seen.values()),
                coast=next(r for r in rows if r['row'] == 1833),
                densest=densest, densest_imported=max(rows, key=lambda r: r['imported']), native_scene_cap=300,
                count_kind='loaded C-LOD upper bound before native culling; not simultaneous allocations')


def check(directory, mw_root, carbon_root, stripped, *, shift=(0., 0.)):
    expected, placements = oracle(mw_root)
    # Additions must never match a native solid, even if a future source archive
    # happens to reuse a lamp hash. Stripping alone cannot prove that distinction.
    _, native_stream, _ = load_index(carbon_root, 'L5RA')
    for root in inventory.stream_tops(native_stream):
        if root.kind != SOLIDS:
            continue
        for solid in chunks(root.payload, root.offset+8):
            if solid.kind == SOLID:
                header = next(p for p in chunks(solid.payload, solid.offset+8) if p.kind == HEADER)
                require(u32(aligned_payload(header), 16) not in expected, 'lamp hash aliases native solid')
    report = census(directory, expected)
    tunnel_lights = coast_tunnel_lights(shift)
    rewrite(directory, expected, remove=True, destination=stripped, caches=cache_words(mw_root, expected),
            tunnel_lights=tunnel_lights, shift=shift)
    report['source_placements'] = placements
    report['x360_tunnel_lights'] = len(tunnel_lights)
    return report
