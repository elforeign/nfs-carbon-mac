"""Decode missing world dependencies from source providers, never from raw hash hits.

The census opens every source file and its nested compression envelopes with the
existing bounded readers. Only a matching directory AND decoded object count as
a provider. A literal occurrence in scenery, a material, or a car is not one.
"""
import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass, field
import hashlib
import json
from itertools import zip_longest
from pathlib import Path
import re
import struct
import sys

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import carbon_car
import texture_compare
import convert
from formats import Chunk, chunks, encode_chunks, require, u32
from merge import DEFAULT_MW, load_index

ROOT_TAGS = re.compile(b'\x00\x40\x13\x80|\x00\x00\x30\xb3')
COMPRESSION = re.compile(b'JDLZ\x02\x10|HUFF\x01\x10')
CLASSES = ('absent-in-source', 'converter-gap', 'shared-global')
READERS = ('formats.chunks', 'texture_compare.jdlz_blobs',
           'texture_compare.unblock', 'carbon_car.unpack_entry')
LOOKUPS = {
    'models': '005018f0 eFindSolid: no loaded hash-table entry returns NULL',
    'textures': '005051d0 calls 00503400 GetTextureInfo(hash,1,0): '
                'no pack/registered texture returns DefaultTextureInfo',
}
# Only decoded metadata/pixels are retained, never installation-sized buffers.
# Every census rereads and hashes every source byte before using an entry.
_DECODED_FILES = {}


def children(c):
    return chunks(c.payload, c.offset + 8)


def one(parts, kind):
    found = [c for c in parts if c.kind == kind]
    require(len(found) == 1, f'closure singleton {kind:08x}')
    return found[0]


@dataclass
class Provider:
    kind: str
    key: int
    location: dict
    info: bytes
    record: bytes = b''
    platform: bytes = b''
    pixels: bytes = b''
    palette: bytes = b''
    data_header: bytes = b''
    solid: object = None
    model_list: object = None
    list_header: tuple = ()


@dataclass
class Census:
    providers: dict = field(default_factory=lambda: {
        'models': defaultdict(list), 'textures': defaultdict(list)})
    summary: dict = field(default_factory=lambda: dict(
        files=0, source_bytes=0, compressed_blocks=0, expanded_bytes=0, packs=0,
        readers=list(READERS)))

    def choose(self, kind, key):
        candidates = self.providers[kind].get(key, ())
        return min(candidates, key=lambda p: (
            not p.location['in_track'], p.location['view'] != 'raw',
            not p.location['file'].upper().startswith('GLOBAL/'),
            p.location['file'], p.location['pack_offset'])) if candidates else None


def compression_offsets(data):
    """Offsets paired with jdlz_blobs' existing skip-over-compressed-bytes rule."""
    end = 0
    for match in COMPRESSION.finditer(data):
        p = match.start()
        if p < end:
            continue
        require(p + 16 <= len(data), 'closure short compression envelope')
        yield p
        end = p + u32(data, p + 12) + (16 if data[p] == ord('H') else 0)


def decoded_views(data, census, label='raw', depth=0):
    require(depth <= 4, 'closure compression nesting exceeds budget')
    yield label, data
    if data[:4] == b'\x22\x11\x44\x55':
        expanded = texture_compare.unblock(data)
        census.summary['expanded_bytes'] += len(expanded)
        yield from decoded_views(expanded, census, label + '/unblock', depth + 1)
        # Individual blocks are fragments; the reconstructed section is the view.
        return
    for p, expanded in zip_longest(compression_offsets(data), texture_compare.jdlz_blobs(data)):
        require(p is not None and expanded is not None, 'closure compressed reader coverage')
        census.summary['compressed_blocks'] += 1
        census.summary['expanded_bytes'] += len(expanded)
        kind = data[p:p + 4].decode('ascii')
        yield from decoded_views(expanded, census, f'{label}/{kind}@{p:x}', depth + 1)


def _texture(c, wanted, location, census):
    parts = children(c)
    hp = children(one(parts, 0xb3310000))
    info = one(hp, 0x33310001).payload
    require(len(info) == 124 and u32(info) == 5, 'closure source TPK version/header')
    location = dict(location, pack=info[32:96].split(b'\0')[0].decode('latin-1'))
    tables = [p for p in hp if p.kind in (0x33310002, 0x33310003)]
    for table in tables:
        stride = 8 if table.kind == 0x33310002 else 24
        require(len(table.payload) % stride == 0, 'closure texture table stride')
        keys = [u32(table.payload, p) for p in range(0, len(table.payload), stride)]
        selected = wanted.intersection(keys)
        if not selected:
            continue
        dp = children(one(parts, 0xb3320000))
        data_header = one(dp, 0x33320001).payload
        if table.kind == 0x33310002:
            rs, ps = one(hp, 0x33310004), one(hp, 0x33310005)
            require(len(rs.payload) == 124 * len(keys) and len(ps.payload) == 32 * len(keys),
                    'closure texture directory/record counts')
            pixels = convert.aligned_payload(one(dp, 0x33320002), 128)
            for slot, key in enumerate(keys):
                if key not in selected:
                    continue
                r = rs.payload[slot * 124:(slot + 1) * 124]
                pl = ps.payload[slot * 32:(slot + 1) * 32]
                require(u32(r, 36) == key, 'closure texture directory/record key')
                off, size = u32(r, 48), u32(r, 56)
                require(off <= len(pixels) and 0 < size <= len(pixels) - off,
                        'closure texture source pixel extent')
                palette = b''
                if u32(pl, 20) == 41:
                    poff, psize = u32(r, 52), u32(r, 60)
                    require(psize == 1024 and poff + psize <= len(pixels), 'closure P8 palette extent')
                    palette = pixels[poff:poff + psize]
                where = dict(location, chunk=f'{table.kind:08x}',
                             entry_offset=table.offset + 8 + slot * stride,
                             record_offset=rs.offset + 8 + slot * 124,
                             texture=r[12:36].split(b'\0')[0].decode('latin-1'),
                             format=pl[20:24].decode('ascii') if pl[20:24] in
                             (b'DXT1', b'DXT3', b'DXT5') else str(u32(pl, 20)))
                census.providers['textures'][key].append(Provider(
                    'textures', key, where, info, r, pl, pixels[off:off + size], palette, data_header))
        else:
            # Compressed TPK entries point into a logical layout. The existing
            # texture reader identifies each decoded object's trailing record.
            decoded = {}
            for blob in texture_compare.jdlz_blobs(one(dp, 0x33320003).payload):
                if len(blob) >= 156:
                    r, pl = blob[-156:-32], blob[-32:]
                    key = u32(r, 36)
                    if key in selected:
                        require(texture_compare.info(r, '<', pl) is not None,
                                'closure compressed texture record')
                        require(u32(r, 56) <= len(blob) - 156, 'closure compressed texture extent')
                        decoded[key] = (r, pl, blob[:u32(r, 56)])
            require(selected <= decoded.keys(), 'closure compressed texture provider not decoded')
            for key in sorted(selected):
                slot = keys.index(key)
                r, pl, pixels = decoded[key]
                where = dict(location, chunk='33310003', entry_offset=table.offset + 8 + slot * stride,
                             texture=r[12:36].split(b'\0')[0].decode('latin-1'),
                             format=pl[20:24].decode('latin-1'))
                census.providers['textures'][key].append(Provider(
                    'textures', key, where, info, r, pl, pixels, b'', data_header))


def _models(c, data, wanted, location, census):
    parts = children(c)
    hp = children(one(parts, 0x80134001))
    info = one(hp, 0x134002).payload
    location = dict(location, pack=info[16:72].split(b'\0')[0].decode('latin-1'))
    for table in (p for p in hp if p.kind in (0x134003, 0x134004)):
        stride = 8 if table.kind == 0x134003 else 24
        require(len(table.payload) % stride == 0, 'closure solid index stride')
        selected = [(p, u32(table.payload, p)) for p in range(0, len(table.payload), stride)
                    if u32(table.payload, p) in wanted]
        if not selected:
            continue
        plain = {}
        for solid in (p for p in parts if p.kind == 0x80134010):
            header = convert.aligned_payload(one(children(solid), 0x134011))
            plain[u32(header, 16)] = solid
        for p, key in selected:
            if table.kind == 0x134004:
                entry = struct.unpack_from('<6I', table.payload, p)
                decoded = carbon_car.unpack_entry(data, entry)
                objects = chunks(decoded)
                solid = one(objects, 0x80134010)
                require(u32(convert.aligned_payload(one(children(solid), 0x134011)), 16) == key,
                        'closure compressed solid key')
            else:
                require(key in plain, 'closure indexed solid has no decoded object')
                solid = plain[key]
            where = dict(location, chunk=f'{table.kind:08x}', entry_offset=table.offset + 8 + p)
            census.providers['models'][key].append(Provider(
                'models', key, where, info, solid=solid, model_list=c, list_header=tuple(hp)))


def census_sources(mw_root, wanted):
    """Scan providers across the complete installation, including memory-file blobs.

    Signature search locates candidate envelopes, not keys. Envelope extents,
    directory entries and actual object identities must all decode successfully.
    No extension filter can silently exclude an asset container.
    """
    track_root = Path(mw_root).resolve()
    root = track_root.parent
    require(track_root.is_dir() and (track_root / 'L2RA.BUN').is_file(), 'closure source index absent')
    census, digest = Census(), hashlib.sha256()
    track_files = {track_root / 'L2RA.BUN', track_root / 'STREAML2RA.BUN'}
    selection = tuple((kind, tuple(sorted(keys))) for kind, keys in sorted(wanted.items()))
    for path in sorted(p for p in root.rglob('*') if p.is_file()):
        data = path.read_bytes()
        relative = path.relative_to(root).as_posix()
        content = hashlib.sha256(data).digest()
        census.summary['files'] += 1
        census.summary['source_bytes'] += len(data)
        digest.update(relative.encode() + b'\0' + content)
        cache_key = (track_root, relative, content, selection)
        decoded_file = _DECODED_FILES.get(cache_key)
        if decoded_file is None:
            decoded_file = Census()
            for view, decoded in decoded_views(data, decoded_file):
                for match in ROOT_TAGS.finditer(decoded):
                    p = match.start()
                    if p % 4 or p + 8 > len(decoded):
                        continue
                    size = u32(decoded, p + 4)
                    if size > len(decoded) - p - 8:
                        continue
                    c = Chunk(u32(decoded, p), decoded[p + 8:p + 8 + size], p)
                    # Binary pixel data may coincidentally contain an envelope
                    # tag. Require its real list/pack header before accepting it.
                    try:
                        parts = children(c)
                        header = one(parts, 0xb3310000 if c.kind == 0xb3300000 else 0x80134001)
                        children(header)
                    except ValueError:
                        continue
                    decoded_file.summary['packs'] += 1
                    location = dict(file=relative, view=view, pack_offset=p, in_track=path in track_files)
                    if c.kind == 0xb3300000:
                        _texture(c, wanted['textures'], location, decoded_file)
                    else:
                        _models(c, decoded, wanted['models'], location, decoded_file)
            if len(_DECODED_FILES) >= 4096:
                del _DECODED_FILES[next(iter(_DECODED_FILES))]
            _DECODED_FILES[cache_key] = decoded_file
        for name in ('compressed_blocks', 'expanded_bytes', 'packs'):
            census.summary[name] += decoded_file.summary[name]
        for kind, providers in decoded_file.providers.items():
            for key, values in providers.items():
                census.providers[kind][key].extend(values)
    census.summary['source_digest'] = digest.hexdigest()
    return census


def wanted_keys(inventory):
    return {kind: {int(row['key'], 16) for row in value['misses']}
            for kind, value in inventory.closure().items() if kind in ('models', 'textures')}


def classify(inventory, census):
    rows = []
    for kind, keys in wanted_keys(inventory).items():
        for key in sorted(keys):
            provider = census.choose(kind, key)
            # Indexed-model closure selects keys, then retains every directory
            # reference to each selected key (including otherwise unused solids).
            refs = inventory.model_refs[key] if kind == 'models' else inventory.texture_refs[key]
            category = ('converter-gap' if provider.location['in_track'] else 'shared-global') if provider else 'absent-in-source'
            if provider:
                where = provider.location
                evidence = (f'{where["file"]} {where["pack"]} pack+0x{where["pack_offset"]:x} '
                            f'{where["chunk"]}+0x{where["entry_offset"]:x}; {where["view"]}')
            else:
                evidence = (f'0 decoded providers / {census.summary["files"]} files / '
                            f'{census.summary["compressed_blocks"]} compressed blocks; '
                            'formats.chunks + texture_compare.jdlz_blobs/unblock + carbon_car.unpack_entry')
            row = dict(kind=kind, key=f'{key:08x}', **{'class': category}, evidence=evidence,
                       lookup=LOOKUPS[kind], references=len(refs),
                       sections=dict(Counter(r['section'] for r in refs)),
                       provider=provider.location if provider else None)
            if kind == 'models':
                row['selecting_instances'] = len({(r['section'], r['scene'], i)
                                                 for r in refs for i in r['instances']})
            else:
                row['first_texture_meshes'] = len(inventory.first_texture_refs.get(key, ()))
            rows.append(row)
    return rows


def texture_bytes(provider):
    """Normalize one existing texture for the ordinary TPK converter.

    DXT bytes pass through exactly. Paletted input uses the existing texture
    transcoder on EACH stored mip, without synthesizing a new mip or artwork.
    The independent checker compares decoded output to the source palette.
    """
    r, pl = bytearray(provider.record), bytearray(provider.platform)
    pixels = provider.pixels
    if pl[20:24] in (b'DXT1', b'DXT3', b'DXT5'):
        return r, pl, pixels
    require(u32(pl, 20) == 41 and len(provider.palette) == 1024,
            'shared texture needs an unsupported converter: ' + provider.location['format'])
    import numpy as np
    import x360_tex
    palette = np.frombuffer(provider.palette, np.uint8).reshape(256, 4)[:, [2, 1, 0, 3]]
    width, height = struct.unpack_from('<HH', r, 68)
    require(width > 0 and height > 0 and 0 < r[78] <= max(width, height).bit_length(),
            'shared P8 dimensions/mips')
    levels, p = [], 0
    for level in range(r[78]):
        w, h = max(1, width >> level), max(1, height >> level)
        require(p + w * h <= len(pixels), 'shared P8 mip extent')
        image = palette[np.frombuffer(pixels[p:p + w * h], np.uint8)].reshape(h, w, 4)
        levels.append(x360_tex.encode_dxt('DXT5', image))
        p += w * h
    require(p == len(pixels), 'shared P8 trailing pixels')
    pixels = b''.join(levels)
    struct.pack_into('<I', r, 52, 0xffffffff)  # no palette in the normalized DXT input
    struct.pack_into('<III', r, 56, len(pixels), 0, len(levels[0]))
    r[74], pl[20:24] = 0x26, b'DXT5'
    return r, pl, pixels


def texture_pack(providers):
    """Subset a decoded source pack; preserve its identity and sampler records."""
    providers = sorted(providers, key=lambda p: p.key)
    require(providers and len({p.info for p in providers}) == 1, 'shared pack identity differs')
    rows, platforms, pixels = [], [], bytearray()
    for provider in providers:
        r, pl, image = texture_bytes(provider)
        pixels += bytes(-len(pixels) % 128)
        struct.pack_into('<I', r, 48, len(pixels))
        rows.append(bytes(r))
        platforms.append(bytes(pl))
        pixels += image
    header = encode_chunks([
        Chunk(0x33310001, providers[0].info),
        Chunk(0x33310002, b''.join(struct.pack('<II', p.key, 0) for p in providers)),
        Chunk(0x33310004, b''.join(rows)), Chunk(0x33310005, b''.join(platforms))])
    out = convert.Builder(8)
    out.add(0xb3310000, header)
    out.pad(128)
    body = convert.Builder(out.position + 8)
    body.add(0x33320001, providers[0].data_header)
    body.add(0x33320002, pixels, 128)
    out.add(0xb3320000, body.data)
    return Chunk(0xb3300000, bytes(out.data))


def resident_additions(rows, census):
    """Source chunks for the existing converters; global resources are resident."""
    groups, models = defaultdict(list), {}
    for row in rows:
        if row['class'] == 'absent-in-source':
            continue
        provider = census.choose(row['kind'], int(row['key'], 16))
        require(provider is not None, 'classified provider disappeared')
        where = provider.location
        identity = (where['file'], where['view'], where['pack_offset'])
        if row['kind'] == 'textures':
            groups[identity].append(provider)
        else:
            models[identity] = provider.model_list
    return {2500: [texture_pack(groups[k]) for k in sorted(groups)],
            2400: [models[k] for k in sorted(models)]}


def _target_textures(index, stream, wanted, *, section=2500):
    """Independent target-record read, including actual written pixel bytes."""
    from merge import read_section
    found = defaultdict(list)
    for record in index.sections:
        if record.number != section:
            continue
        for root in chunks(read_section(stream, record)):
            if root.kind != 0xb3300000:
                continue
            parts = children(root)
            hp = children(one(parts, 0xb3310000))
            table = one(hp, 0x33310002).payload
            keys = [key for key, _ in struct.iter_unpack('<II', table)]
            records, platforms = one(hp, 0x33310004).payload, one(hp, 0x33310005).payload
            pixels = convert.aligned_payload(one(children(one(parts, 0xb3320000)), 0x33320002), 128)
            p = 0
            for slot, key in enumerate(keys):
                require(p + 89 <= len(records), 'closure target texture record')
                size = 89 + records[p + 88]
                r = records[p:p + size]
                require(len(r) == size and u32(r, 12) == key, 'closure target texture key/extent')
                if key in wanted:
                    off, total = u32(r, 20), u32(r, 28)
                    require(off + total <= len(pixels), 'closure target texture pixels')
                    found[key].append((r, platforms[slot * 24:(slot + 1) * 24], pixels[off:off + total]))
                p += size
    return found


def _check_texture(provider, actual):
    """Check record mapping and image identity without running the TPK writer."""
    r, pl, pixels = actual
    source = provider.record
    expected = bytearray(source[:12] + source[36:44] + source[48:116])
    struct.pack_into('<I', expected, 20, u32(r, 20))
    require(u32(r, 20) % 128 == 0, 'shared texture placement alignment')
    name = source[12:36].split(b'\0')[0]
    require(r[89:].split(b'\0')[0] == name, 'shared texture name changed')
    if provider.platform[20:24] in (b'DXT1', b'DXT3', b'DXT5'):
        require(r[:88] == expected and pl[12:16] == provider.platform[20:24],
                'shared texture record changed')
        require(pixels == provider.pixels, 'shared texture pixels changed')
        return dict(format=pl[12:16].decode(), pixel_bytes=len(pixels), exact=True)
    require(u32(provider.platform, 20) == 41 and pl[12:16] == b'DXT5', 'shared P8 target format')
    struct.pack_into('<I', expected, 24, 0xffffffff)
    struct.pack_into('<III', expected, 28, len(pixels), 0, u32(r, 36))
    expected[46] = 0x26
    require(r[:88] == expected, 'shared P8 record changed')
    import numpy as np
    import x360_tex
    palette = np.frombuffer(provider.palette, np.uint8).reshape(256, 4)[:, [2, 1, 0, 3]]
    width, height = struct.unpack_from('<HH', source, 68)
    p, q, maximum = 0, 0, np.zeros(4, dtype=np.int32)
    for level in range(source[78]):
        w, h = max(1, width >> level), max(1, height >> level)
        size = max(1, (w + 3) // 4) * max(1, (h + 3) // 4) * 16
        require(q + size <= len(pixels), 'shared P8 target mip extent')
        before = palette[np.frombuffer(provider.pixels[p:p + w * h], np.uint8)].reshape(h, w, 4)
        after = x360_tex.decode_preview('DXT5', w, h, pixels[q:q + size])
        error = np.abs(before.astype(np.int32) - after.astype(np.int32))
        maximum = np.maximum(maximum, error.max(axis=(0, 1)))
        # BC3 stores eight alpha values spanning each block's minimum/maximum.
        # Bound quantization from that source block, rather than assuming the
        # top mip's measured error applies to every authored smaller mip.
        bh, bw = (h + 3) // 4, (w + 3) // 4
        alpha = np.pad(before[:, :, 3].astype(np.int32),
                       ((0, bh * 4 - h), (0, bw * 4 - w)), mode='edge')
        blocks = alpha.reshape(bh, 4, bw, 4).transpose(0, 2, 1, 3)
        span = blocks.max(axis=(2, 3)) - blocks.min(axis=(2, 3))
        bound = (((span + 6) // 7 + 1) // 2).repeat(4, 0).repeat(4, 1)[:h, :w]
        require(int(error[:, :, :3].max()) <= 8 and np.all(error[:, :, 3] <= bound),
                'shared P8 transcode exceeds BC3 quantization bounds')
        p, q = p + w * h, q + size
    require(q == len(pixels) and p == len(provider.pixels), 'shared P8 mip coverage')
    return dict(format='P8->DXT5', pixel_bytes=len(pixels), exact=False,
                maximum_channel_error=maximum.tolist(), stored_mips=source[78])


def check_first_textures(source, written, rows):
    """A changed first binding cannot hide behind unchanged directory closure."""
    def solid(key):
        return '1f389568' if key == 'ed85ba82' else key
    def bindings(inv, source=False):
        return Counter((r['section'], solid(r['solid']) if source else r['solid'], r['mesh'], r['material'], key)
                       for key, refs in inv.first_texture_refs.items() for r in refs)
    before, after = bindings(source, True), bindings(written)
    require(not (before - after), 'first-texture material binding changed')
    # Recovered global models may introduce additional stored draw records.
    source_solids = {(r['section'], solid(r['solid'])) for refs in source.first_texture_refs.values() for r in refs}
    require(not any((r[0], r[1]) in source_solids for r in after - before),
            'first-texture material binding changed')
    textures = [row for row in rows if row['kind'] == 'textures']
    original = sum(row['first_texture_meshes'] for row in textures)
    remaining = sum(len(written.first_texture_refs.get(int(row['key'], 16), ()))
                    for row in textures if int(row['key'], 16) not in written.textures)
    recoverable = sum(len(written.first_texture_refs.get(int(row['key'], 16), ()))
                      for row in textures if row['class'] != 'absent-in-source'
                      and int(row['key'], 16) not in written.textures)
    require(recoverable == 0, 'shared/gap first-texture miss')
    return dict(before=original, after=remaining, recoverable_after=recoverable,
                all_mesh_before=sum(len(refs) for key, refs in source.first_texture_refs.items()
                                    if key not in source.textures),
                all_mesh_after=sum(len(refs) for key, refs in written.first_texture_refs.items()
                                   if key not in written.textures))


def check_providers(index, stream, source, written, rows, census):
    """Verify source classifications against actual resident provider objects."""
    expected = classify(source, census)
    verify_classes(rows, expected)
    wanted = {int(r['key'], 16) for r in rows if r['kind'] == 'textures'
              and r['class'] != 'absent-in-source'}
    found = _target_textures(index, stream, wanted)
    images = {}
    for row in rows:
        if row['class'] == 'absent-in-source':
            continue
        key, kind = int(row['key'], 16), row['kind']
        provider = census.choose(kind, key)
        if kind == 'models':
            require(2400 in written.models.get(key, ()), 'shared/gap model not resident')
        else:
            require(len(found[key]) == 1, f'shared/gap texture {key:08x} not uniquely resident')
            images[row['key']] = _check_texture(provider, found[key][0])
    first = check_first_textures(source, written, rows)
    counts = {kind: {category: sum(r['kind'] == kind and r['class'] == category for r in rows)
                     for category in CLASSES} for kind in ('models', 'textures')}
    return dict(rows=rows, classified=len(rows), counts=counts, census=census.summary,
                first_texture_meshes=first, shared_images=images)


def verify_classes(actual, expected):
    left = {(r['kind'], r['key']): r['class'] for r in actual}
    right = {(r['kind'], r['key']): r['class'] for r in expected}
    require(len(left) == len(actual) and left == right, 'closure classification differs from decoded providers')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--proof', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        import rockport_world as world
        proof = json.loads(args.proof.read_text())
        source = next(s for s in proof['sources'] if s['role'] == 'source index')
        mw_root = Path(source['path']).parent
        index, stream, _ = load_index(mw_root, 'L2RA')
        inventory = world.Inventory(index, stream)
        census = census_sources(mw_root, wanted_keys(inventory))
        rows = classify(inventory, census)
        saved = proof.get('validation', {}).get('classification')
        if saved:
            verify_classes(saved['rows'], rows)
        print('kind key class selecting-instances/first-texture-meshes decoded evidence')
        for row in rows:
            count = row.get('selecting_instances', row.get('first_texture_meshes'))
            evidence = row['evidence'] if row['provider'] else (
                f'0 providers; {census.summary["files"]} files, '
                f'{census.summary["compressed_blocks"]} blocks (jdlz_blobs/unblock); '
                + ('005018f0=NULL' if row['kind'] == 'models' else '005051d0/00503400=DefaultTextureInfo'))
            print(f'{row["kind"][:-1]:7} {row["key"]} {row["class"]:16} {count:5} {evidence}')
        require(len(rows) == sum(len(v) for v in wanted_keys(inventory).values()) and
                all(r['class'] in CLASSES for r in rows), 'unclassified closure key')
    except FileNotFoundError as exc:
        print(f'SKIP: private assets absent: {exc}', file=sys.stderr)
        return 3
    except (OSError, ValueError, KeyError, StopIteration, struct.error) as exc:
        print(f'FAIL: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
