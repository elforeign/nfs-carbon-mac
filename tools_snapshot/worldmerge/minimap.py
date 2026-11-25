"""Offline HUD atlas conversion, with a bounded independent serialized checker.

Input roots may be game roots or TRACKS directories. Output must be outside a
checkout and the input trees. No executable, TrackInfo or source asset changes.
The manifest records HUD and world-map calibrations separately: their vertical
origins use different conventions. The reference PNGs are offline check inputs,
not textures to install. Missing private inputs produce CLI exit status 3.
"""
import argparse
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import struct
import sys

import numpy as np
from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path[:0] = [str(HERE), str(HERE.parent)]
import carbon_car as cc
import x360_tex as xt
from formats import FormatError, require
from c3_link import SHIFT as WORLD_SHIFT  # Rockport's physics (X, Z) in the combined world

BASES = tuple('MINI_MAP_CASINOTOWN_' + s for s in ('LOCKED', 'UNLOCKED'))
ROCKPORT = (-1224.889404296875, -1591.1448974609375, 6659.33203125)
PALMONT = (-7300., -2000., 16000.)
SHARED = (-7300., -6992., 20992.)
LINK_WIDTH = 16.  # metres: the 4-pixel stroke of Palmont's own art where the connecting road ends
SIDE, TILE, PIXELS, RECORD = 4096, 256, 65536, 148
EXAMPLE = (-160., 45., 2912.)  # Physics XYZ; render (2912, 160, 45).
PALMONT_EXAMPLE = (-6000., 0., 1000.)
SHARED_EXAMPLES = ((.8767149064, .6592987932, 174), (.3953887048, .3810975840, 102))
REGION = {'rockport': 'L2RA', 'shared': 'L5RA'}  # the track folder each layout's world loads


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def f32(value):
    return struct.unpack('<f', struct.pack('<f', value))[0]


def name_hash(name):
    value = 0xffffffff
    for byte in name.encode('ascii'):
        value = (33 * value + byte) & 0xffffffff
    return value


def tile_name(base, tile):
    return f'{base}_CHOP{tile}'


def case_path(root, *parts):
    path = Path(root)
    for part in parts:
        matches = [p for p in path.iterdir() if p.name.upper() == part.upper()]
        if not matches:
            raise FileNotFoundError(path / part)
        require(len(matches) == 1, 'ambiguous input path')
        path = matches[0]
    return path


def tracks_root(root):
    root = Path(root)
    return root if root.name.upper() == 'TRACKS' else case_path(root, 'TRACKS')


def inputs(mw_root, carbon_root):
    mw, carbon = tracks_root(mw_root), tracks_root(carbon_root)
    return case_path(mw, 'L2RA', 'MINI_MAP.BIN'), [
        case_path(carbon, 'L5RA', base + '.bin') for base in BASES]


def source_canvas(path):
    raw = Path(path).read_bytes()
    parts = list(cc.children(raw))
    require(len(parts) == 64, 'source tile count differs from 64')
    canvas = np.zeros((1024, 1024, 4), np.uint8)
    seen = set()
    for cid, off, size in parts:
        require(cid == 0x3a100 and raw[off+8:off+12] == b'JDLZ', 'source tile envelope')
        rows = list(xt.textures_in(xt.jdlz(raw[off+8:off+8+size]), 128))
        require(len(rows) == 1, 'source texture count')
        name, _, w, h, fmt, pix = rows[0]
        require(name.startswith('MINI_MAP_CHOP') and name[13:].isdigit(), 'source tile name')
        tile = int(name[13:])
        require(tile not in seen and 0 <= tile < 64, 'source duplicate/tile id')
        require((w, h, fmt, len(pix)) == (128, 128, 0x33545844, 16384), 'source tile format')
        row, col = divmod(tile, 8)
        canvas[row*128:(row+1)*128, col*128:(col+1)*128] = xt.decode_preview('DXT3', w, h, pix)
        seen.add(tile)
    return Image.fromarray(canvas)


@dataclass
class Pack:
    raw: bytes
    base: str
    entries: list
    index_offset: int
    data_offset: int
    data_size: int
    container_offset: int
    blobs: dict


def read_stock(path, base):
    """Writer input reader; the output checker below does not use this path."""
    raw = Path(path).read_bytes()
    chunks = {cid: (off, size) for cid, off, size in cc.walk(raw)}
    require(cc.u32(raw, chunks[0x33310001][0]+8) == 8, 'stock TPK version')
    index, size = chunks[0x33310003]
    entries = list(struct.iter_unpack('<6I', raw[index+8:index+8+size]))
    require(len(entries) == 256, 'stock tile count')
    expected = {name_hash(tile_name(base, i)) for i in range(256)}
    require([e[0] for e in entries] == sorted(expected), 'stock full-name hashes/order')
    for entry in entries:
        native_stream(raw, entry)
    blobs = {e[0]: cc.unpack_entry(raw, e) for e in entries}
    for e in entries:
        blob = blobs[e[0]]
        require(e[3:] == (PIXELS+RECORD, 0x200, 0), 'stock index layout')
        require(len(blob) == PIXELS+RECORD and struct.unpack_from('<HH', blob, PIXELS+40) == (256, 256)
                and blob[-12:-8] == b'DXT3', 'stock pixel format')
    dp, dz = chunks[0x33320002]
    return Pack(raw, base, entries, index, dp, dz, chunks[0xb3320000][0], blobs)


def jdlz_encode(blob):
    """Bounded greedy v2 encoder; both native match forms, no external codec."""
    output, positions = bytearray(16), {}
    token_bit = match_bit = 8
    cursor = 0
    while cursor < len(blob):
        if token_bit == 8:
            token_slot, token_bit = len(output), 0
            output.append(0)
        if match_bit == 8:
            match_slot, match_bit = len(output), 0
            output.append(0)
        candidates = positions.get(blob[cursor:cursor+3], ())
        length, distance = 0, 0
        for previous in reversed(candidates):
            dist = cursor-previous
            if dist > 2064:
                break
            limit = min(4098 if dist <= 16 else 34, len(blob)-cursor)
            count = 3
            while count < limit and blob[cursor+count] == blob[cursor+count-dist]:
                count += 1
            if count > length and count <= limit:
                length, distance = count, dist
                if count == limit:
                    break
        advance = max(1, length)
        if length >= 3:
            output[token_slot] |= 1 << token_bit
            if distance <= 16:
                output[match_slot] |= 1 << match_bit
                output += bytes((((length-3) >> 8) << 4 | (distance-1), (length-3) & 255))
            else:
                output += bytes((((distance-17) >> 8) << 5 | (length-3), (distance-17) & 255))
            match_bit += 1
        else:
            output.append(blob[cursor])
        for pos in range(cursor, cursor+advance):
            key = blob[pos:pos+3]
            if len(key) == 3:
                bucket = positions.setdefault(key, [])
                bucket.append(pos)
                if len(bucket) > 32:
                    del bucket[0]
        cursor += advance
        token_bit += 1
    # 0069C5D0 consumes compressed bytes, and eagerly refills exhausted flags
    # even after the final output token. Output-size-bounded readers omit this.
    if token_bit == 8:
        output.append(0)
    if match_bit == 8:
        output.append(0)
    output[:16] = b'JDLZ\x02\x10\0\0' + struct.pack('<2I', len(blob), len(output))
    return bytes(output)


def native_jdlz_extent(data):
    """Validate byte-count termination and eager flag reads in 0069C5D0."""
    require(len(data) >= 18 and data[:8] == b'JDLZ\x02\x10\0\0', 'native JDLZ header')
    size, end = struct.unpack_from('<2I', data, 8)
    require(18 <= end <= len(data), 'native JDLZ extent')
    pos, written, remaining = 18, 0, end-18
    tokens, matches = data[16] | 256, data[17] | 256
    while remaining:
        if tokens & 1:
            require(remaining >= 2 and pos+2 <= end, 'native JDLZ match extent')
            a, b = data[pos:pos+2]
            count, distance = (((a & 240) << 4 | b)+3, (a & 15)+1) if matches & 1 else ((a & 31)+3, ((a & 224) << 3 | b)+17)
            require(distance <= written, 'native JDLZ match distance')
            matches >>= 1
            pos += 2
            remaining -= 2
        else:
            # Retail streams may spend a final literal token after output is
            # full. Native decrements the byte count without advancing input.
            count = int(written < size)
            pos += count
            remaining -= 1
        written += count
        require(written <= size, 'native JDLZ output overflow')
        tokens >>= 1
        if tokens == 1:
            require(remaining > 0 and pos < end, 'native JDLZ terminal flag refill')
            tokens, pos = data[pos] | 256, pos+1
            remaining -= 1
        if matches == 1:
            require(remaining > 0 and pos < end, 'native JDLZ terminal flag refill')
            matches, pos = data[pos] | 256, pos+1
            remaining -= 1
    require(written == size, 'native JDLZ incomplete output')


def native_stream(raw, entry):
    """Check the in-place contract of 006AABA0, including its zero terminator.

    The last block is saved to scratch. Earlier blocks decode in reverse into
    the same allocation, so their destinations must clear all live input.
    """
    _, off, stored, size, flags, zero = entry
    require(flags == 0x200 and zero == 0, 'native streaming index flags')
    pos, end, blocks = off, off+stored, []
    require(0 <= off <= end <= len(raw), 'native streaming extent')
    while pos < end:
        require(pos+24 <= end, 'native streaming header')
        magic, usize, bsize, dst, rel, reserved = struct.unpack_from('<6I', raw, pos)
        require(magic == 0x55441122 and 24 <= bsize <= end-pos and
                rel == pos-off and reserved == 0, 'native streaming block')
        require((dst == 0) == (pos+bsize == end), 'native streaming zero-destination terminator')
        blocks.append((pos, bsize, dst, usize))
        if raw[pos+24:pos+28] == b'JDLZ':
            native_jdlz_extent(raw[pos+24:pos+bsize])
        pos += bsize
    require(blocks and stored <= size, 'native streaming allocation overflow')
    for pos, bsize, dst, usize in blocks[:-1]:
        require(pos-off+bsize <= dst and dst+usize <= size, 'native streaming live-input overlap')
    return blocks


def stream_entry(blob):
    """Native in-place order: later spans first, destination zero last."""
    blocks = bytearray()
    for dst in [*range(32768, len(blob), 32768), 0]:
        part = blob[dst:dst+32768]
        encoded = jdlz_encode(part)
        encoded += bytes(-len(encoded) % 4)
        blocks += struct.pack('<6I', 0x55441122, len(part), len(encoded)+24, dst, len(blocks), 0)
        blocks += encoded
    native_stream(blocks, (0, 0, len(blocks), len(blob), 0x200, 0))
    return bytes(blocks)


def write_pack(pack, pixels=None):
    """Rebuild index and parent lengths; preserve all stock framing and gaps.

    With no replacements this reconstructs the original compressed pack through
    the same writer. With replacements, retain native records/platform fields
    and replace only their same-sized pixels. Display strings are never hashed.
    """
    raw, start = pack.raw, pack.data_offset+8
    if pixels is not None:
        require(pixels.keys() == pack.blobs.keys() and all(len(p) == PIXELS for p in pixels.values()), 'replacement tile set/size')
    end = start+pack.data_size
    physical = sorted(pack.entries, key=lambda e: e[1])
    data, rows, cursor = bytearray(), {}, start
    for entry in physical:
        native_stream(raw, entry)
        hs, off, stored, unpacked, flags, zero = entry
        if pixels is None:
            data += raw[cursor:off]
            body = raw[off:off+stored]
        else:
            if not data:
                data += raw[start:off]
            padding = -(start+len(data)) % 64
            if padding:
                if padding < 8:
                    padding += 64
                data += struct.pack('<2I', 0, padding-8) + bytes(padding-8)
            body = stream_entry(pixels[hs] + pack.blobs[hs][-RECORD:])
        rows[hs] = (hs, start+len(data), len(body), unpacked, flags, zero)
        data += body
        cursor = off+stored
    data += raw[cursor:end] if pixels is None else struct.pack('<2I', 0, 0)
    output = bytearray(raw[:start]) + data + raw[end:]
    delta = len(data)-pack.data_size
    struct.pack_into('<I', output, 4, len(output)-8)
    struct.pack_into('<I', output, pack.container_offset+4, cc.u32(raw, pack.container_offset+4)+delta)
    struct.pack_into('<I', output, pack.data_offset+4, len(data))
    for i, entry in enumerate(pack.entries):
        struct.pack_into('<6I', output, pack.index_offset+8+24*i, *rows[entry[0]])
    return bytes(output)


def project(point, calibration, shift=(0., 0.)):
    x, _, z = point
    bx, by, size = calibration
    k = f32(1/size)
    u, v = (z+shift[1]-bx)*k, 1+(by+x+shift[0])*k
    require(0 <= u < 1 and 0 <= v < 1, 'point outside atlas')
    return {'u': u, 'v': v, 'tile': 16*math.floor(16*v)+math.floor(16*u)}


def link_lines(world, mw_root, carbon_root):
    """Road-graph segments the combined world adds to the two games' own."""
    import c1_roads
    import ground
    from formats import TrackIndex
    from merge import load_index
    from region import collision_body, one
    own = sum(len(ground.road_nodes(load_index(tracks_root(root), base)[0]))
              for root, base in ((carbon_root, 'L5RA'), (mw_root, 'L2RA')))
    index = TrackIndex(case_path(tracks_root(world), 'L5RA.BUN').read_bytes())
    nodes = ground.road_nodes(index)
    arrays = c1_roads._source(collision_body(one(index.parts, 0x3b800)))[2]
    lines = [(nodes[a], nodes[b]) for a, b in struct.iter_unpack('<2H18x', arrays[c1_roads.SEGMENTS])
             if max(a, b) >= own]
    require(lines, 'combined world adds no road')
    return lines


def world_shift(world):
    """Rockport's physics (X, Z) in a built combined world, from the proof its builder wrote beside TRACKS."""
    if world is None:
        return WORLD_SHIFT
    proof = Path(world).parent/'proof.json'
    require(proof.is_file(), 'combined world proof.json absent')
    x, y, z = json.loads(proof.read_text())['roads']['shift_physics_xyz']
    require(y == 0 and all(math.isfinite(v) for v in (x, z)), 'combined world shift')
    return (float(x), float(z))


def rockport_inside(shift):
    """Rockport's square under this shift must lie inside the shared canvas the runtime calibrates."""
    left, top = ROCKPORT[0]+shift[1]-SHARED[0], SHARED[1]+SHARED[2]-ROCKPORT[1]-ROCKPORT[2]+shift[0]
    require(0 <= left and left+ROCKPORT[2] <= SHARED[2] and 0 <= top and top+ROCKPORT[2] <= SHARED[2],
            'Rockport outside the shared atlas')


def composite(native, rockport, link=(), shift=WORLD_SHIFT):
    """Map pixel centres through world coordinates; no integer placement drift."""
    rockport_inside(shift)
    canvas = Image.new('RGBA', (SIDE, SIDE), (0, 0, 0, 255))
    palmont = None
    for image, (bx, by, size), shift in ((native, PALMONT, (0., 0.)), (rockport, ROCKPORT, shift)):
        left = (bx+shift[1]-SHARED[0])/SHARED[2]*SIDE
        top = (SHARED[1]+SHARED[2]-by-size+shift[0])/SHARED[2]*SIDE
        extent = size/SHARED[2]*SIDE
        box = (math.floor(left), math.floor(top), math.ceil(left+extent), math.ceil(top+extent))
        scale = image.width/extent
        placed = image.transform((box[2]-box[0], box[3]-box[1]), Image.Transform.AFFINE,
            (scale, 0, (box[0]-left)*scale, 0, scale, (box[1]-top)*scale),
            Image.Resampling.BILINEAR, fillcolor=(0, 0, 0, 255))
        canvas.paste(placed, box[:2])
        palmont = palmont or (placed, box[:2])
    # The squares may overlap (the coast link): Palmont's drawn roads stay above Rockport's opaque square.
    placed, corner = palmont
    canvas.paste(placed, corner, Image.fromarray((np.asarray(placed)[:, :, :3].max(2) > 0).astype(np.uint8)*255))
    draw = ImageDraw.Draw(canvas)
    for line in link:
        draw.line([((z-SHARED[0])/SHARED[2]*SIDE, (1+(SHARED[1]+x)/SHARED[2])*SIDE) for x, _, z in line],
                  fill=(255, 255, 255, 255), width=round(LINK_WIDTH/SHARED[2]*SIDE))
    return canvas


def encode_canvas(canvas, base):
    pixels = {}
    array = np.asarray(canvas)
    for i in range(256):
        row, col = divmod(i, 16)
        pixels[name_hash(tile_name(base, i))] = xt.encode_dxt('DXT3', array[row*256:(row+1)*256, col*256:(col+1)*256])
    return pixels


def safe_output(out, roots):
    out = Path(out).resolve()
    for parent in (out, *out.parents):
        require(not (parent/'.git').exists(), 'output must be outside every checkout')
    for root in roots:
        root = Path(root).resolve()
        root = root.parent if root.name.upper() == 'TRACKS' else root
        require(not out.is_relative_to(root), 'output must be outside input trees')
    return out


def convert(mw_root, carbon_root, out, layout='rockport', world=None):
    require(layout in ('rockport', 'shared'), 'unknown layout')
    out = safe_output(out, (mw_root, carbon_root))
    source, targets = inputs(mw_root, carbon_root)
    rockport = source_canvas(source)
    packs = [read_stock(path, base) for path, base in zip(targets, BASES)]
    # Complete the premise and stock round trip before creating output files.
    require(all(write_pack(pack) == pack.raw for pack in packs), 'stock round trip differs')
    cal, shift = (ROCKPORT, (0., 0.)) if layout == 'rockport' else (SHARED, world_shift(world))
    link = link_lines(world, mw_root, carbon_root) if world and layout == 'shared' else ()
    manifest = {'schema': 1, 'layout': layout, 'canvas_size': [SIDE, SIDE],
        'hud': {'bx': cal[0], 'by': cal[1], 'k': f32(1/cal[2])},
        'world_map': {'+AC': cal[0], '+B0': f32(-cal[1]-cal[2]), '+B4': cal[2]},
        'shift_physics_xz': list(shift), 'link_segments': len(link),
        'examples': {'rockport': {'physics_xyz': list(EXAMPLE), **project(EXAMPLE, cal, shift)}},
        'packs': {}}
    if layout == 'shared':
        manifest['examples']['palmont'] = {'physics_xyz': list(PALMONT_EXAMPLE), **project(PALMONT_EXAMPLE, cal)}
    destination = out/'TRACKS'/REGION[layout]
    planned = [out/'calibration.json'] + [destination/(base+'.bin') for base in BASES] + [
        out/f'reference-{base}.png' for base in BASES]
    require(all(path.resolve().is_relative_to(out) for path in planned), 'output child escapes export tree')
    destination.mkdir(parents=True, exist_ok=True)
    for pack in packs:
        canvas = (rockport.resize((SIDE, SIDE), Image.Resampling.BILINEAR) if layout == 'rockport'
                  else composite(stock_canvas(pack), rockport, link, shift))
        pixels = encode_canvas(canvas, pack.base)
        written = write_pack(pack, pixels)
        (destination/(pack.base+'.bin')).write_bytes(written)
        reference = f'reference-{pack.base}.png'
        # Before encoding, at the requested 1024-square comparison resolution.
        small = rockport if layout == 'rockport' else canvas.resize((1024, 1024), Image.Resampling.BOX)
        small.save(out/reference)
        manifest['packs'][pack.base] = {'size': len(written), 'sha256': digest(written),
            'reference': reference, 'reference_sha256': digest((out/reference).read_bytes()),
            'tile_sha256': [digest(pixels[name_hash(tile_name(pack.base, i))]) for i in range(256)]}
    (out/'calibration.json').write_text(json.dumps(manifest, indent=2)+'\n')
    return check(out)


def stock_canvas(pack):
    canvas = Image.new('RGBA', (SIDE, SIDE))
    for i in range(256):
        blob = pack.blobs[name_hash(tile_name(pack.base, i))]
        tile = Image.fromarray(xt.decode_preview('DXT3', TILE, TILE, blob[:PIXELS]))
        canvas.paste(tile, ((i%16)*TILE, (i//16)*TILE))
    return canvas


def checked_pack(raw, base):
    """Independent bounded walker and streaming reader, not cc.unpack_entry.

    Validate every source/destination span before copying or decoding. Native
    JDLZ and generated RAWW share only their bounded decompression primitive.
    """
    def walk(lo, hi):
        while lo < hi:
            require(lo+8 <= hi, 'truncated checked chunk')
            cid, size = struct.unpack_from('<II', raw, lo)
            require(size <= hi-lo-8, 'checked chunk extent')
            yield cid, lo, size
            if cid & 0x80000000:
                yield from walk(lo+8, lo+8+size)
            lo += 8+size
    require(len(raw) >= 8 and struct.unpack_from('<2I', raw) == (0xb3300000, len(raw)-8), 'checked TPK root')
    chunks = {}
    for cid, off, size in walk(0, len(raw)):
        if cid:
            require(cid not in chunks, 'duplicate checked chunk')
            chunks[cid] = off, size
    require(all(cid in chunks for cid in (0x33310001, 0x33310002, 0x33310003, 0x33320002)), 'missing checked chunk')
    require(struct.unpack_from('<I', raw, chunks[0x33310001][0]+8)[0] == 8, 'checked version')
    ip, iz = chunks[0x33310003]
    require(iz == 256*24, 'checked tile count differs from 256')
    entries = list(struct.iter_unpack('<6I', raw[ip+8:ip+8+iz]))
    names = {name_hash(tile_name(base, i)): i for i in range(256)}
    require([e[0] for e in entries] == sorted(names), 'checked full-name hashes/order')
    hp, hz = chunks[0x33310002]
    require(hz == 256*8 and list(struct.iter_unpack('<2I', raw[hp+8:hp+8+hz])) ==
            [(hs, 0) for hs in sorted(names)], 'checked hash table')
    dp, dz = chunks[0x33320002]
    extents, tiles = [], {}
    for hs, off, stored, size, flags, zero in entries:
        require((size, flags, zero) == (PIXELS+RECORD, 0x200, 0), 'checked index format')
        require(dp+8 <= off and 0 < stored <= min(len(raw), dp+8+dz)-off, 'checked block extent')
        native_stream(raw, (hs, off, stored, size, flags, zero))
        extents.append((off, off+stored))
        pos, end, spans = off, off+stored, []
        blob = bytearray(size)
        first = True
        while pos < end:
            require(pos+24 <= end, 'checked streaming header extent')
            magic, usize, bsize, dst, rel, reserved = struct.unpack_from('<6I', raw, pos)
            require(magic == 0x55441122 and reserved == 0 and rel == pos-off and
                    (not first or rel == 0), 'checked streaming identity')
            require(0 < usize <= 32768 and 40 <= bsize <= end-pos and dst <= size-usize, 'checked streaming extent')
            compressed = raw[pos+24:pos+bsize]
            if compressed[:4] == b'RAWW':
                require(compressed[4:8] == b'\x01\x10\0\0' and
                        struct.unpack_from('<2I', compressed, 8) == (usize, usize) and
                        len(compressed) == usize+16, 'checked RAWW envelope')
                part = compressed[16:]
            elif compressed[:4] == b'JDLZ':
                decoded_size, compressed_size = struct.unpack_from('<2I', compressed, 8)
                require(decoded_size == usize and 16 <= compressed_size <= len(compressed) and
                        len(compressed)-compressed_size < 4, 'checked JDLZ envelope')
                part = xt.jdlz(compressed[:compressed_size])
            elif compressed[:4] == b'HUFF':
                decoded_size, compressed_size = struct.unpack_from('<2I', compressed, 8)
                compressed_size += 16  # HUFF's stored-size word excludes its envelope.
                require(decoded_size == usize and 16 <= compressed_size <= len(compressed) and
                        len(compressed)-compressed_size < 4, 'checked HUFF envelope')
                part = xt.huff(compressed[:compressed_size], 0)
            else:
                raise FormatError('unsupported checked compression')
            require(len(part) == usize, 'checked block decoded size')
            blob[dst:dst+usize] = part
            spans.append((dst, dst+usize))
            pos += bsize
            first = False
        coverage = 0
        for lo, hi in sorted(spans):
            require(lo == coverage, 'checked destination hole/overlap')
            coverage = hi
        require(coverage == size, 'checked destination incomplete')
        record, platform = blob[PIXELS:PIXELS+124], blob[-24:]
        require(struct.unpack_from('<I', record, 12)[0] == hs, 'checked record hash')
        require(struct.unpack_from('<I', record, 28)[0] == PIXELS and
                struct.unpack_from('<HH', record, 40) == (TILE, TILE) and
                record[44:46] == b'\x08\x08' and record[50] == 1 and platform[12:16] == b'DXT3', 'checked tile format/mips')
        tiles[names[hs]] = bytes(blob[:PIXELS])
    require(all(a[1] <= b[0] for a, b in zip(sorted(extents), sorted(extents)[1:])), 'checked source overlap')
    return tiles


def decoded_canvas(tiles):
    canvas = Image.new('RGBA', (SIDE, SIDE))
    for i, pix in tiles.items():
        canvas.paste(Image.fromarray(xt.decode_preview('DXT3', TILE, TILE, pix)), ((i%16)*TILE, (i//16)*TILE))
    return canvas


def check(out):
    out = Path(out)
    manifest = json.loads((out/'calibration.json').read_text())
    layout = manifest['layout']
    require(layout in ('rockport', 'shared') and manifest['schema'] == 1, 'checked layout/schema')
    bx, by, size = ROCKPORT if layout == 'rockport' else SHARED
    hud, world = manifest['hud'], manifest['world_map']
    require(manifest['canvas_size'] == [4096, 4096] and
            all(math.isclose(a, b, rel_tol=0, abs_tol=1e-10) for a, b in
                zip((hud['bx'], hud['by'], hud['k']), (bx, by, f32(1/size)))), 'checked HUD calibration/vertical flip')
    require(world == {'+AC': bx, '+B0': f32(-by-size), '+B4': size}, 'checked world-map calibration')
    shift = manifest['shift_physics_xz']
    if layout == 'rockport':
        require(shift == [0., 0.], 'checked physics shift')
    else:
        rockport_inside(shift)
        # An export written into a built world must use that world's own shift.
        if (out/'proof.json').is_file():
            require(shift == list(world_shift(out/'TRACKS')), 'checked physics shift against the world proof')
    expected = ((.6212168932, .7370389700, 185) if layout == 'rockport' else
                SHARED_EXAMPLES[0] if shift == list(WORLD_SHIFT) else None)
    points = {'rockport': (EXAMPLE, shift, expected)}
    if layout == 'shared':
        points['palmont'] = (PALMONT_EXAMPLE, (0., 0.), SHARED_EXAMPLES[1])
    for name, (point, (dx, dz), expected) in points.items():
        # Spell out the native map-plane transform, independently of project().
        u = (point[2]+dz-hud['bx'])*hud['k']
        v = 1+(hud['by']-(-point[0]-dx))*hud['k']
        tile = 16*int(v*16)+int(u*16)
        row = manifest['examples'][name]
        # Pinned constants exist for the fixed layouts; another shift is checked against the spelled-out transform.
        expected = expected or (u, v, tile)
        require(row['physics_xyz'] == list(point) and tile == expected[2] == row['tile'] and
                abs(u-expected[0]) < 1e-6 and abs(v-expected[1]) < 1e-6 and
                abs(row['u']-u) < 1e-10 and abs(row['v']-v) < 1e-10, 'checked fixed-point projection')
    results = {}
    for base in BASES:
        raw = (out/'TRACKS'/REGION[layout]/(base+'.bin')).read_bytes()
        tiles = checked_pack(raw, base)
        row = manifest['packs'][base]
        require(len(row['tile_sha256']) == 256 and all(digest(tiles[i]) == row['tile_sha256'][i] for i in range(256)), 'checked tile spatial witness')
        require(len(raw) == row['size'] and digest(raw) == row['sha256'], 'checked pack fingerprint')
        require(row['reference'] == f'reference-{base}.png', 'checked reference path')
        ref = out/row['reference']
        require(digest(ref.read_bytes()) == row['reference_sha256'], 'checked reference fingerprint')
        with Image.open(ref) as image:
            require(image.size == (1024, 1024) and image.mode == 'RGBA', 'checked reference format')
            reference = np.asarray(image).astype(np.int16)
        small = np.asarray(decoded_canvas(tiles).resize((1024, 1024), Image.Resampling.BOX)).astype(np.int16)
        mae = np.abs(small-reference).mean((0, 1)).tolist()
        require(max(mae) < 4, f'checked canvas MAE {mae} exceeds 4')
        results[base] = {'tiles': len(tiles), 'size': len(raw), 'sha256': digest(raw), 'mae_rgba': mae}
    return {'layout': layout, 'examples': manifest['examples'], 'packs': results}


def main():
    from merge import DEFAULT_MW, DEFAULT_CARBON
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mw', type=Path, default=DEFAULT_MW)
    parser.add_argument('--carbon', type=Path, default=DEFAULT_CARBON)
    parser.add_argument('--layout', choices=('rockport', 'shared'), default='rockport')
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--world', type=Path, help='combined TRACKS folder: draws its connecting road (shared layout)')
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    try:
        result = check(args.out) if args.check else convert(args.mw, args.carbon, args.out, args.layout, args.world)
    except FileNotFoundError as exc:
        print(f'private inputs/output absent: {exc.filename or exc}', file=sys.stderr)
        return 3
    except (ValueError, KeyError, struct.error) as exc:
        print(f'FAIL: {exc}', file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    sys.exit(main())
