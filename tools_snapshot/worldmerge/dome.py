"""Resident texture closure for the imported sky solid."""
import struct
from functools import lru_cache
from pathlib import Path

import closure
import convert
from formats import chunks, require, u32
from merge import load_index, read_section

SOURCE_KEY = 0xed85ba82
TARGET_KEY = 0x1f389568


def texture_keys(data, key):
    found = []
    for root in chunks(data):
        if root.kind != 0x80134000:
            continue
        for solid in closure.children(root):
            if solid.kind != 0x80134010:
                continue
            parts = closure.children(solid)
            header = convert.aligned_payload(closure.one(parts, 0x134011))
            if u32(header, 16) == key:
                found.append({k for k, _ in struct.iter_unpack('<II', closure.one(parts, 0x134012).payload)})
    require(len(found) == 1, 'sky solid identity/count differs')
    return found[0]


@lru_cache(maxsize=4)
def source_providers(mw_root):
    """Read the solid's complete directory and its shipped global provider."""
    index, stream, _ = load_index(Path(mw_root), 'L2RA')
    section = next(s for s in index.sections if s.number == 2400)
    keys = texture_keys(read_section(stream, section), SOURCE_KEY)
    path = Path(mw_root).parent/'GLOBAL/InGameA.bun'
    census = closure.Census()
    for view, data in closure.decoded_views(path.read_bytes(), census):
        for match in closure.ROOT_TAGS.finditer(data):
            p = match.start()
            if p % 4 or p + 8 > len(data) or u32(data, p) != 0xb3300000:
                continue
            size = u32(data, p+4)
            if size > len(data)-p-8:
                continue
            root = closure.Chunk(0xb3300000, data[p+8:p+8+size], p)
            try:
                closure.one(closure.children(root), 0xb3310000)
            except ValueError:
                continue
            closure._texture(root, keys, dict(file='GLOBAL/InGameA.bun', view=view,
                             pack_offset=p, in_track=False), census)
    providers = tuple(census.choose('textures', k) for k in sorted(keys))
    require(all(providers), 'sky texture has no decoded source global provider')
    return providers


def append(out, mw_root):
    pack = closure.texture_pack(source_providers(Path(mw_root)))
    out.pad(128)
    out.data += convert.convert_tpk(pack, out.position, convert.Stats(pack_section=TARGET_KEY))


def check(index, stream, mw_root):
    section = next(s for s in index.sections if s.number == 2100)
    keys = texture_keys(read_section(stream, section), TARGET_KEY)
    providers = {p.key: p for p in source_providers(Path(mw_root))}
    require(keys == providers.keys(), 'sky texture directory differs from source')
    found = closure._target_textures(index, stream, keys, section=2100)
    missing = keys-found.keys()
    require(not missing, 'sky sentinel lookups: ' + ','.join(f'{k:08X}' for k in sorted(missing)))
    for key in keys:
        require(len(found[key]) == 1, 'sky texture provider count differs')
        closure._check_texture(providers[key], found[key][0])
    return dict(textures=[f'{k:08X}' for k in sorted(keys)], sentinel_lookups=len(missing), section=2100)
