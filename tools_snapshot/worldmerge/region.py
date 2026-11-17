"""Private one-section region proof, retaining source coordinates and local IDs.

No reference conversion is read. Generated assets stay under ignored worktree
scratch; the source installations and earlier merge artifacts are read-only.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import struct
import sys
import tempfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from formats import Chunk, FormatError, TrackIndex, chunks, encode_chunks, require, u32
from convert import Builder, Stats, aligned_payload, convert_solid, convert_tpk, convert_scenery
from merge import DEFAULT_MW, DEFAULT_CARBON, load_index, read_section
from validate import validate_section, validate_translation

SCRATCH = HERE.parents[1] / 'recomp' / 'out' / 'moon3-scratch'
SENTINELS = {0, 0xbe43edbb, 0x90f70174}


def collision_body(chunk):
    return chunk.payload[-(chunk.offset + 8) % 16:]


def collision_tags(raw, group):
    """Read the native CARP directory, not a payload magic search."""
    require(u32(raw) == 0x43415250, 'collision CARP root absent')
    start = u32(raw, 12) * 16
    groups = (u32(raw, 4) >> 5) + u32(raw, 8)
    matches = [p for p in range(start, start + groups * 16, 16) if u32(raw, p) == group]
    require(len(matches) == 1, 'collision group absent or duplicate')
    p = matches[0]
    first = p + u32(raw, p + 12) * 16
    result = {}
    for q in range(first, first + u32(raw, p + 8) * 16, 16):
        key, flags, count, offset = struct.unpack_from('<4I', raw, q)
        require(key not in result and (flags & 2 or count == 0), 'collision tag addressing')
        value = q + offset if count else 0
        require(count == 0 or 0 <= value <= len(raw) - (flags >> 8), 'collision tag bounds')
        result[key] = (q, flags, count, value)
    return result


def collision_cells(raw, tag):
    _, flags, count, p = tag
    end = p + (flags >> 8)
    result = []
    for _ in range(count):
        require(p + 20 <= end, 'collision cell header truncated')
        size = 20 + 4 * sum(raw[p + 8:p + 12])
        require(p + size <= end, 'collision cell references truncated')
        offsets = [4 * sum(raw[p + 8:p + 8 + k]) for k in range(4)]
        require(list(struct.unpack_from('<4H', raw, p + 12)) == offsets,
                'collision reference-family offsets differ')
        result.append(raw[p:p + size]); p += size
    require(p == end, 'collision cell extent differs')
    return result


def collision_conversion(source, source_stream, carbon, boundary):
    """MW flat CDat -> Carbon CDat rectangle plus streamed Arti/CGcn.

    Native 00813850 reads descriptor fields through +28, ignoring +32/+36.
    +32 is a serialized pointer; clear it. The extra +36 word is 1 in L5RA
    (L5RB has the same low word plus unused high padding); copy L5RA's word.
    Cells keep all four families: only family zero contains pack selectors.
    """
    raw = collision_body(one(source.parts, 0x3b800))
    tags = collision_tags(raw, 0x43446174)
    require({0x43477264, 0x4347636e} <= tags.keys(), 'MW grid tags absent')
    _, flags, count, p = tags[0x43477264]
    require(flags >> 8 == 36 and count == 1, 'MW collision descriptor layout')
    descriptor = bytearray(raw[p:p + 36])
    ox, _, oz = struct.unpack_from('<3f', descriptor)
    cell = struct.unpack_from('<f', descriptor, 16)[0]
    rows, columns = struct.unpack_from('<II', descriptor, 24)
    lx, ly, hx, hy = boundary.bounds
    # 00763695..007636BD (MW) and 007E8DF5..007E8E1D (Carbon):
    # rows advance on physics Z, columns on physics X.
    r0, r1 = (math.floor((v - oz) / cell) for v in (lx, hx))
    c0, c1 = (math.floor((v - ox) / cell) for v in (-hy, -ly))
    require(0 <= r0 <= r1 < rows and 0 <= c0 <= c1 < columns, 'collision rectangle outside grid')
    cells = [bytearray(c) for c in collision_cells(raw, tags[0x4347636e])
             if r0 <= struct.unpack_from('<H', c, 4)[0] // columns <= r1
             and c0 <= struct.unpack_from('<H', c, 4)[0] % columns <= c1]
    families = [sum(c[8 + k] for c in cells) for k in range(4)]
    needed = {u32(c, p) >> 16 for c in cells for p in range(20, 20 + 4 * c[8], 4)}
    providers = {}
    for section in source.sections:
        for chunk in chunks(read_section(source_stream, section)):
            if chunk.kind == 0x3b801:
                pack = collision_body(chunk); key = u32(pack, 4)
                if key in needed:
                    require(key not in providers, 'duplicate MW collision pack')
                    providers[key] = (section.number, pack)
    require(set(providers) == needed, 'missing MW collision packs')
    native, native_stream, _ = load_index(carbon, 'L5RA')
    reserved = {u32(collision_body(c), 4) for s in native.sections
                for c in chunks(read_section(native_stream, s)) if c.kind == 0x3b801}
    remap = {}; used = reserved | needed
    for key in sorted(needed):
        if key in reserved:
            # 008125xx rejects selectors >= 0xa8c; this is a fixed table.
            target = next(n for n in range(1, 0xa8c) if n not in used)
            remap[key] = target; used.add(target)
    native_raw = collision_body(one(native.parts, 0x3b800))
    tail = collision_tags(native_raw, 0x43446174)[0x43477264][3]
    descriptor[32:36] = bytes(4)
    descriptor += native_raw[tail + 36:tail + 40]
    require(descriptor[36:] == b'\x01\0\0\0', 'Carbon descriptor extension differs')
    for c in cells:
        struct.pack_into('<H', c, 6, boundary.number)
        for p in range(20, 20 + 4 * c[8], 4):
            value = u32(c, p)
            struct.pack_into('<I', c, p, (remap.get(value >> 16, value >> 16) << 16) | (value & 0xffff))
    packs = []
    for key, (_, pack) in sorted(providers.items()):
        pack = bytearray(pack)
        struct.pack_into('<I', pack, 4, remap.get(key, key))
        packs.append(bytes(pack))
    # Minimal native CARP/Arti directory, matching L5RB's streamed tile.
    data = b''.join(cells)
    tile = bytearray(256)
    struct.pack_into('<4I', tile, 0, 0x43415250, 0x2a, 0, 1)
    struct.pack_into('<4I', tile, 16, 0x41727469, 0x12, 2, 1)
    struct.pack_into('<4I', tile, 32, 0x4347636e, (len(data) << 8) | 2, len(cells), 256 - 32)
    name_offset = (256 + len(data) + 15) // 16 * 16
    struct.pack_into('<4I', tile, 48, 0x4e616d65, 0x602, 0, name_offset - 48)
    tile += data + bytes(name_offset - 256 - len(data)) + b'L2RA\0\0'
    tile += bytes(-len(tile) % 16)
    tile = struct.pack('<4I', len(tile), boundary.number, 0, 0) + tile
    rectangle = struct.pack('<5H', boundary.number, r0, c0, c1 - c0 + 1, r1 - r0 + 1)
    report = {'cells': len(cells), 'references': families[0], 'reference_families': families,
              'rectangle': list(struct.unpack('<5H', rectangle)), 'packs': len(packs),
              'providers': {str(k): v[0] for k, v in sorted(providers.items())},
              'pack_remap': {str(k): v for k, v in remap.items()}, 'descriptor_extension': descriptor[36:].hex(),
              'source_rows_z': [r0, r1], 'source_columns_x': [c0, c1],
              'cell_id_stride': columns, 'cell_ids': [struct.unpack_from('<H', c, 4)[0] for c in cells]}
    return descriptor, rectangle, tile, packs, report


def append_collision(out, tile, packs):
    for kind, raw in [(0x3b802, tile), *((0x3b801, p) for p in packs)]:
        out.pad(16)
        out.add(kind, bytes(-(out.position + 8) % 16) + raw)


def check_collision(index, stream, target):
    map_raw = collision_body(one(index.parts, 0x3b800))
    tags = collision_tags(map_raw, 0x43446174)
    require({0x43477264, 0x636c0000} <= tags.keys(), 'Carbon grid/rectangle tags absent')
    _, flags, count, p = tags[0x43477264]
    require(flags >> 8 == 40 and count == 1, 'Carbon grid descriptor differs')
    columns = u32(map_raw, p + 28)
    rect = struct.unpack_from('<5H', map_raw, tags[0x636c0000][3])
    require(rect[0] == target and rect[3] and rect[4], 'collision rectangle section/extents differ')
    tiles = [c for c in chunks(stream) if c.kind == 0x3b802]
    packs = [c for c in chunks(stream) if c.kind == 0x3b801]
    require(len(tiles) == 1, 'collision tile missing or duplicate')
    tile = collision_body(tiles[0])
    require(u32(tile, 4) == target and u32(tile) == len(tile) - 16, 'collision tile header differs')
    raw = tile[16:]
    cells = collision_cells(raw, collision_tags(raw, 0x41727469)[0x4347636e])
    providers = {}
    for chunk in packs:
        pack = collision_body(chunk); key = u32(pack, 4)
        require(0 < key < 0xa8c and key not in providers, 'collision pack selector invalid/duplicate')
        require(u32(pack) == len(pack) - 16, 'collision pack length differs')
        ci = collision_tags(pack[16:], 0x41727469)[0x63690000]
        require(ci[1] >> 8 == 64 * ci[2], 'collision instance stride differs')
        providers[key] = ci[2]
    used = set(); ids = set(); families = [0] * 4
    for c in cells:
        cid, section = struct.unpack_from('<HH', c, 4)
        row, col = divmod(cid, columns)
        # 007F5FE9..007F601B: quotient is Z row; remainder is X column.
        # Rectangle words +2/+4 are rowZ/columnX, +6/+8 countX/countZ.
        require(section == target and cid not in ids and rect[2] <= col < rect[2] + rect[3]
                and rect[1] <= row < rect[1] + rect[4], 'collision cell outside rectangle or duplicate')
        ids.add(cid)
        for k in range(4): families[k] += c[8 + k]
        for q in range(20, 20 + 4 * c[8], 4):
            ref = u32(c, q); key = ref >> 16
            require(key in providers and (ref & 0xffff) < providers[key], 'collision reference unresolved')
            used.add(key)
    require(cells and used == set(providers), 'collision cells/providers differ')
    return {'cells': len(cells), 'reference_families': families, 'packs': len(packs), 'rectangle': list(rect)}


def children(c):
    return chunks(c.payload, c.offset + 8)


def one(parts, kind):
    found = [p for p in parts if p.kind == kind]
    require(len(found) == 1, f'expected singleton {kind:08x}')
    return found[0]


def inventory(index, stream):
    """Bounded source inventory; resource providers retain original chunk offsets."""
    solids, textures, candidates = {}, {}, []
    boundaries = {b.number: b for b in index.boundaries()}
    for section in index.sections:
        roots = chunks(read_section(stream, section))
        local, wanted, texture_refs, scene = set(), set(), set(), []
        for root in roots:
            if root.kind == 0x80134000:
                for solid in (c for c in children(root) if c.kind == 0x80134010):
                    sp = children(solid)
                    key = u32(aligned_payload(one(sp, 0x134011)), 16)
                    local.add(key)
                    refs = {v[0] for v in struct.iter_unpack('<II', one(sp, 0x134012).payload)}
                    texture_refs.update(refs)
                    solids.setdefault(key, (section.number, root, solid, refs))
            elif root.kind == 0xb3300000:
                hp = children(one(children(root), 0xb3310000))
                for key, _ in struct.iter_unpack('<II', one(hp, 0x33310002).payload):
                    textures.setdefault(key, (section.number, root))
            elif root.kind == 0x80034100:
                scene.append(root)
                infos = one(children(root), 0x34102).payload
                require(len(infos) % 72 == 0, 'source scenery model-table stride')
                for p in range(0, len(infos), 72):
                    wanted.update(u32(infos, p + k) for k in (24, 28, 32, 36)
                                  if u32(infos, p + k) not in SENTINELS)
        if (len(scene) == 1 and local and section.number in boundaries
                and 1 <= section.number % 100 < 40):
            candidates.append((section, scene[0], wanted | local, texture_refs))
    return solids, textures, sorted(candidates, key=lambda r: (r[0].size, r[0].number))


def dependency_closure(candidate, solids, textures):
    _, _, wanted, texture_refs = candidate
    refs = set(texture_refs)
    for key in wanted & solids.keys():
        refs.update(solids[key][3])
    return wanted, refs, wanted - solids.keys(), refs - textures.keys()


def solid_list(selected, position, stats):
    """Rebuild a plain list, excluding unrelated shared models and their refs."""
    selected = sorted(selected.items())
    template = selected[0][1][1]
    hp = children(one(children(template), 0x80134001))
    info = bytearray(one(hp, 0x134002).payload)
    require(len(info) == 144 and u32(info, 8) == 29, 'source list layout')
    struct.pack_into('<I', info, 12, len(selected))
    # Empty compressed-offset table is the native plain-list representation.
    require(not one(hp, 0x80134008).payload, 'compressed shared list unsupported')
    out = Builder(position + 8)
    out.pad(16)
    out.add(0x80134001, encode_chunks([
        Chunk(0x134002, bytes(info)),
        Chunk(0x134003, b''.join(struct.pack('<II', key, 0) for key, _ in selected)),
        Chunk(0x80134008, b'')]))
    for _, (_, _, solid, _) in selected:
        out.data += convert_solid(solid, out.position, stats)
    return Chunk(0x80134000, bytes(out.data)).encode()


def pack_hash(name):
    h = 0xffffffff
    for ch in name:
        h = (h * 33 + ch) & 0xffffffff
    return h


def texture_pack(root, wanted, position, stats, serial=0):
    """Convert only selected records, preserving exact mip-chain bytes.

    The native loader binds each pack header to the first queued data block with
    the same pack hash (info +0x60 = data header +0xC), so every pack written into
    one section needs its own file name and hash.
    """
    # Convert with the existing classified writer first. Then select target rows
    # and repack pixels; this also checks every source row's bounds and format.
    converted = convert_tpk(root, position, Stats())
    target = chunks(converted, position)[0]
    hp = children(one(children(target), 0xb3310000))
    dp = children(one(children(target), 0xb3320000))
    rows = one(hp, 0x33310004).payload
    platforms = one(hp, 0x33310005).payload
    pixels = aligned_payload(one(dp, 0x33320002), 128)
    selected, plats, hashes, data = [], [], [], bytearray()
    p, i = 0, 0
    while p < len(rows):
        size = (89 + rows[p + 88] + 3) // 4 * 4
        row = bytearray(rows[p:p + size]); key = u32(row, 12)
        if key in wanted:
            offset, length = u32(row, 20), u32(row, 28)
            data += bytes(-len(data) % 128)
            struct.pack_into('<I', row, 20, len(data))
            data += pixels[offset:offset + length]
            selected.append(bytes(row)); plats.append(platforms[i * 24:(i + 1) * 24])
            hashes.append(key)
        p += size; i += 1
    require(set(hashes) == wanted, 'texture provider does not supply selected hashes')
    info = bytearray(one(hp, 0x33310001).payload)
    name = b'Location2\\TempTextures%02d.tpk' % serial
    require(len(name) < 0x40, 'pack file name too long')
    info[0x20:0x60] = name + bytes(0x40 - len(name))
    struct.pack_into('<I', info, 0x60, pack_hash(name))
    data_header = bytearray(one(dp, 0x33320001).payload)
    require(len(data_header) == 24 and u32(data_header, 12) == u32(one(hp, 0x33310001).payload, 0x60),
            'texture data header does not name its pack')
    struct.pack_into('<I', data_header, 12, pack_hash(name))
    out = Builder(position + 8)
    out.add(0, bytes(48))
    out.add(0xb3310000, encode_chunks([
        Chunk(0x33310001, bytes(info)), Chunk(0x33310002, b''.join(struct.pack('<II', k, 0) for k in hashes)),
        Chunk(0x33310004, b''.join(selected)), Chunk(0x33310005, b''.join(plats))]))
    out.pad(128)
    body = Builder(out.position + 8)
    body.add(0x33320001, bytes(data_header))
    # Native layout: header, exactly one padding chunk, then the pixel chunk on a
    # 128-byte boundary. The loader (00560580) takes the chunk after the padding
    # as the pixel chunk and reads pixels from its header + 0x80.
    count = -body.position % 128
    count += 128 if count < 8 else 0
    body.add(0, bytes(count - 8))
    body.add(0x33320002, b'\x11' * 120 + data)
    out.add(0xb3320000, body.data)
    stats.textures += len(hashes)
    return Chunk(0xb3300000, bytes(out.data)).encode()


def visibility(boundary, position):
    boundary = boundary.translate(boundary.number, 0)
    drive = struct.pack('<IIh', 40, 1, boundary.number) + bytes(1022)
    row = bytearray(36)
    struct.pack_into('<hBBhh', row, 12, boundary.number, 1, 8, 1, boundary.number)
    out = Builder(position + 8)
    out.add(0x34151, drive)
    out.add(0x34152, boundary.raw)
    out.add(0x34156, b'', 16)
    out.add(0x34155, b'')
    out.add(0x34153, row)
    return bytes(out.data)


def region_index(template, record, boundary, stream_size, collision=None):
    """Isolated visibility with either the native empty map or converted grid.

    Rendering-only output retains its original coarse scaffold. Collision output
    installs the source descriptor and one Carbon rectangle; paths, overrides
    and gameplay scripts remain outside this conversion.
    """
    keep = {0x34112, 0x80034147, 0x34250, 0x8003b000, 0x34110,
            0x34113, 0x34111, 0x34108, 0x34109, 0x3b800, 0x3414d}
    out = Builder(0)
    for top in template.parts:
        if top.kind == 0x80034150:
            out.pad(16); out.add(top.kind, visibility(boundary, out.position))
        elif top.kind in keep:
            if top.kind == 0x34110:
                out.pad(16); out.add(top.kind, record.raw)
            elif top.kind == 0x3b800:
                # The native empty map's tag graph and all relative pointers
                # remain exact. Only descriptor origin/cell extents change.
                raw = bytearray(top.payload)
                p = raw.find(struct.pack('<I', 0x43477264))
                require(p >= 0 and u32(raw, p + 8) == 1, 'native grid tag absent')
                q = p + u32(raw, p + 12)
                require(u32(raw, p + 4) >> 8 == 40, 'native grid stride')
                if collision:
                    descriptor, rectangle = collision[:2]
                    raw[q:q + 40] = descriptor
                    tags = collision_tags(collision_body(top), 0x43446174)
                    # Tag offsets above exclude the envelope's alignment bytes.
                    pad = -(top.offset + 8) % 16
                    cl = tags[0x636c0000][3] + pad
                    raw[cl:cl + 10] = rectangle
                    out.pad(16); out.add(top.kind, raw)
                    continue
                lo_x, lo_y, hi_x, hi_y = boundary.bounds
                cell = max(hi_x - lo_x, hi_y - lo_y) + 128
                struct.pack_into('<3f', raw, q, -hi_y - 64, 0, lo_x - 64)
                struct.pack_into('<f', raw, q + 16, cell)
                # Keep 6 x 4 native empty-grid dimensions and corresponding
                # native cell metadata; the section lies inside its first cell.
                out.pad(16); out.add(top.kind, raw)
            else:
                out.pad(16); out.add(top.kind, top.payload)
    result = bytes(out.data)
    check_region(result, bytes(stream_size), record.number, structural_only=True)
    return result


def camera(scene):
    """Bounds come from transformed geometry instances, with render Z vertical."""
    raw = aligned_payload(one(children(scene), 0x34103))
    require(raw and len(raw) % 96 == 0, 'camera geometry instances absent')
    bounds = [(struct.unpack_from('<3f', raw, p), struct.unpack_from('<3f', raw, p + 16))
              for p in range(0, len(raw), 96)]
    lo = [min(a[k] for a, _ in bounds) for k in range(3)]
    hi = [max(b[k] for _, b in bounds) for k in range(3)]
    target = [(a + b) / 2 for a, b in zip(lo, hi)]
    radius = max(hi[0] - lo[0], hi[1] - lo[1], 40)
    eye = [target[0], target[1] - radius * .7, hi[2] + radius * .35]
    return {'render_eye': eye, 'render_target': target, 'geometry_bounds': [lo, hi],
            'physics_eye': [-eye[1], eye[2], eye[0]], 'height_source': 'converted instance geometry bounds Z'}


def check_region(index_data, stream_data, target, structural_only=False):
    index = TrackIndex(index_data)
    count = index.validate(len(stream_data))
    require(index.encode() == index_data, 'region round-trip differs')
    require(count == 1 and index.sections[0].number == target, 'target section missing or unexpected records')
    boundaries = list(index.boundaries())
    require(len(boundaries) == 1 and boundaries[0].number == target, 'target boundary missing')
    parts = children(one(index.parts, 0x80034150))
    drive = one(parts, 0x34151).payload
    require(u32(drive, 4) == 1 and struct.unpack_from('<h', drive, 8)[0] == target, 'target drivable entry missing')
    row = one(parts, 0x34153).payload
    require(len(row) == 36 and struct.unpack_from('<hBBhh', row, 12) == (target, 1, 8, 1, target),
            'target full-detail visibility missing')
    from audit import decode_grid
    one(index.parts, 0x3b800)
    grid = decode_grid(index)
    require(grid['descriptor_bytes'] == 40, 'region grid is not Carbon format')
    ox, _, oz = grid['origin_physics_xyz']
    lo_x, lo_y, hi_x, hi_y = boundaries[0].bounds
    require(ox <= -hi_y <= -lo_y <= ox + grid['columns'] * grid['cell_m'] and
            oz <= lo_x <= hi_x <= oz + grid['rows'] * grid['cell_m'],
            'region grid does not cover native section coordinates')
    if structural_only:
        return {'records': count}
    record = index.sections[0]
    data = stream_data[record.offset:record.offset + record.size]
    roots = chunks(data)
    collision = None
    if any(c.kind in (0x3b801, 0x3b802) for c in roots):
        collision = check_collision(index, data, target)
        # The rendering validator rejects opaque source chunks. Collision has
        # its own bounded reader above; equal-sized padding keeps draw alignment.
        data = b''.join(Chunk(0, bytes(len(c.payload))).encode() if c.kind in (0x3b801, 0x3b802)
                        else c.encode() for c in roots)
    else:
        raw = collision_body(one(index.parts, 0x3b800))
        tags = collision_tags(raw, 0x43446174)
        require(0x636c0000 in tags, 'Carbon rectangle tag absent')
        require(struct.unpack_from('<H', raw, tags[0x636c0000][3])[0] != target,
                'collision rectangle has no streamed tile')
    counts, deps = validate_section(data, target)
    require(not any(deps.values()), f'region dependencies not closed: {deps}')
    return {'records': count, 'counts': counts, 'dependencies': deps, **({'collision': collision} if collision else {})}


def prepare(mw=DEFAULT_MW, carbon=DEFAULT_CARBON, section=None, collision=False):
    source, source_stream, _ = load_index(mw, 'L2RA')
    template, _, _ = load_index(carbon, 'L5RB')
    solids, textures, candidates = inventory(source, source_stream)
    rejected = []
    chosen = None
    for candidate in candidates:
        record, scene, _, _ = candidate
        if section is not None and record.number != section:
            continue
        wanted_s, wanted_t, missing_s, missing_t = dependency_closure(candidate, solids, textures)
        if missing_s or missing_t:
            rejected.append({'section': record.name, 'bytes': record.size,
                             'missing_solids': sorted(missing_s), 'missing_textures': sorted(missing_t)})
            continue
        chosen = candidate; break
    require(chosen is not None, 'no full-detail visible section has closed source dependencies')
    record, scene, _, _ = chosen
    boundary = next(b for b in source.boundaries() if b.number == record.number)
    converted_collision = collision_conversion(source, source_stream, carbon, boundary) if collision else None
    stats, out = Stats(), Builder(0)
    groups = {}
    for key in sorted(wanted_t):
        provider, root = textures[key]
        groups.setdefault((provider, root.offset), (root, set()))[1].add(key)
    for serial, (root, keys) in enumerate(groups.values()):
        out.pad(128); out.data += texture_pack(root, keys, out.position, stats, serial)
    out.pad(128); out.data += solid_list({k: solids[k] for k in wanted_s}, out.position, stats)
    out.pad(128); out.data += convert_scenery(scene, out.position, record.number, 0, stats)
    if converted_collision:
        append_collision(out, converted_collision[2], converted_collision[3])
    out.pad(128)
    stream_data = bytes(out.data)
    new_record = record.replace(offset=0, size=len(stream_data))
    index_data = region_index(template, new_record, boundary, len(stream_data), converted_collision)
    validation = check_region(index_data, stream_data, record.number)
    converted_scene = next(c for c in chunks(stream_data) if c.kind == 0x80034100)
    # Translation validator expects the source container's absolute alignment.
    spatial = validate_translation(read_section(source_stream, record), stream_data, 0)
    report = dict(track=2000, region='L2RA', section=record.name, number=record.number,
                  source_section_bytes=record.size, index_bytes=len(index_data), stream_bytes=len(stream_data),
                  shift=[0, 0, 0], renumbered=False, validation=validation, spatial=spatial,
                  camera=camera(converted_scene), smaller_candidates_rejected=rejected,
                  resource_sections=sorted({solids[k][0] for k in wanted_s} | {textures[k][0] for k in wanted_t}),
                  index_sha256=hashlib.sha256(index_data).hexdigest(),
                  stream_sha256=hashlib.sha256(stream_data).hexdigest(),
                  collision=converted_collision[4] if converted_collision else 'empty native scaffold; rendering proof only')
    return index_data, stream_data, report


def write_outputs(out, index, stream, report, sources):
    out = Path(out).absolute()
    require(out.is_relative_to(SCRATCH) and out != SCRATCH, 'region output must be a new worktree scratch child')
    require(out.resolve().is_relative_to(SCRATCH.parent.resolve() / SCRATCH.name), 'region output symlink escapes scratch')
    require(not out.exists() and not out.is_symlink(), 'region output already exists')
    require(all(not out.resolve().is_relative_to(Path(p).resolve()) for p in sources), 'region output inside source assets')
    out.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.region-', dir=out.parent))
    try:
        tracks = stage / 'TRACKS'; tracks.mkdir()
        (tracks / 'L2RA.BUN').write_bytes(index)
        (tracks / 'STREAML2RA.BUN').write_bytes(stream)
        (stage / 'proof.json').write_text(json.dumps(report, indent=2) + '\n')
        check_region((tracks / 'L2RA.BUN').read_bytes(), (tracks / 'STREAML2RA.BUN').read_bytes(), report['number'])
        os.rename(stage, out)
    finally:
        if stage.exists(): shutil.rmtree(stage)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--mw', type=Path, default=DEFAULT_MW)
    ap.add_argument('--carbon', type=Path, default=DEFAULT_CARBON)
    ap.add_argument('--section', type=int)
    ap.add_argument('--collision', action='store_true')
    ap.add_argument('--out', type=Path, default=SCRATCH / 'region')
    ap.add_argument('--check-only', action='store_true')
    args = ap.parse_args()
    try:
        index, stream, report = prepare(args.mw, args.carbon, args.section, args.collision)
        if not args.check_only: write_outputs(args.out, index, stream, report, (args.mw, args.carbon))
        print(json.dumps(report, indent=2))
    except FileNotFoundError as exc:
        print(f'SKIP: private assets absent: {exc}', file=sys.stderr); return 3
    except (OSError, FormatError) as exc:
        print(f'FAIL: {exc}', file=sys.stderr); return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
