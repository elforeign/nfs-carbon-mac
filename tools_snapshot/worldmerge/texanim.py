"""Classify source texture-animation omissions; the target loader rejects them.

The registered loader returns false before reading any directory child. There
is consequently no target writer or target-field checker here. Classification
keeps frame order and signed timing values, and reports the static textures and
stored first-texture mesh slots affected. It does not authorize an omission.
"""
from collections import Counter
from dataclasses import dataclass
import struct

from formats import Chunk, chunks, require, u32


DIRECTORY = 0xb0300100
CHILDREN = (0x30300101, 0x30300102, 0x30300103)


@dataclass(frozen=True)
class Animation:
    label: bytes
    key: int
    rate: int
    time_base: int
    frames: tuple


def decode_directory(chunk):
    """Decode the supported source records, never infer target fields.

    The source constructor partitions 16-byte entries using the counts in its
    52-byte records. Exact coverage prevents silently losing a frame. Runtime
    slots and unused words are accepted only in their observed on-disk zero
    state; their values are never synthesized or emitted.
    """
    require(chunk.kind == DIRECTORY, 'not a texture-animation directory')
    parts = chunks(chunk.payload, chunk.offset + 8)
    require(tuple(c.kind for c in parts) == CHILDREN, 'animation child order/count')
    header, records, entries = (c.payload for c in parts)
    require(len(header) == 16 and u32(header) == 1, 'animation header/version')
    require(not any(header[4:]), 'animation header runtime/unused words')
    require(records and len(records) % 52 == 0, 'animation record extent')
    require(len(entries) % 16 == 0, 'animation entry extent')
    result, first = [], 0
    for p in range(0, len(records), 52):
        record = records[p:p + 52]
        key = u32(record, 24)
        count, rate, time_base = struct.unpack_from('<iii', record, 28)
        require(key != 0 and count > 0 and rate > 0, 'animation key/count/rate')
        require(not any(record[40:]), 'animation record runtime words')
        require(count <= len(entries) // 16 - first, 'animation frame coverage')
        frames = []
        for i in range(first, first + count):
            entry = entries[i * 16:(i + 1) * 16]
            texture = u32(entry)
            require(texture != 0, 'animation zero texture hash')
            require(not any(entry[4:]), 'animation entry runtime/unused words')
            frames.append(texture)
        result.append(Animation(record[:24], key, rate, time_base, tuple(frames)))
        first += count
    require(first * 16 == len(entries), 'animation unclaimed frames')
    return tuple(result)


def _one(parts, kind):
    found = [c for c in parts if c.kind == kind]
    require(len(found) == 1, f'animation inventory singleton {kind:08x}')
    return found[0]


def _children(chunk):
    return chunks(chunk.payload, chunk.offset + 8)


def _aligned(chunk):
    pad = -(chunk.offset + 8) % 16
    require(pad <= len(chunk.payload) and chunk.payload[:pad] == b'\x11' * pad,
            'animation inventory alignment')
    return chunk.payload[pad:]


@dataclass(frozen=True)
class DirectoryContext:
    section: int
    chunk: Chunk
    textures: frozenset


@dataclass(frozen=True)
class SourceInventory:
    directories: tuple
    first_textures: Counter
    mesh_records: int
    sections: int


def inventory_source(index, stream):
    """Inventory the indexed stream without using a converter or its statistics.

    Texture keys reconcile the pack's directory with its ordinary records.
    Mesh counts refer to material +24 through that solid's own texture table.
    No scenery-instance expansion is applied.
    """
    from merge import read_section

    contexts, first_textures, mesh_records = [], Counter(), 0
    for section in index.sections:
        roots = chunks(read_section(stream, section))
        textures = set()
        for root in roots:
            if root.kind == 0xb3300000:
                header = _children(_one(_children(root), 0xb3310000))
                table = _one(header, 0x33310002).payload
                records = _one(header, 0x33310004).payload
                require(len(table) % 8 == 0 and len(records) == len(table) // 8 * 124,
                        'animation inventory texture extents')
                keys = tuple(u32(table, p) for p in range(0, len(table), 8))
                actual = tuple(u32(records, p + 36) for p in range(0, len(records), 124))
                require(keys == actual, 'animation inventory texture directory/records')
                textures.update(actual)
            elif root.kind == 0x80134000:
                for solid in _children(root):
                    if solid.kind != 0x80134010:
                        continue
                    parts = _children(solid)
                    table = _one(parts, 0x134012).payload
                    require(len(table) % 8 == 0, 'animation inventory mesh texture table')
                    keys = tuple(u32(table, p) for p in range(0, len(table), 8))
                    for mesh in (c for c in parts if c.kind == 0x80134100):
                        fields = _children(mesh)
                        header = _aligned(_one(fields, 0x134900))
                        rows = _aligned(_one(fields, 0x134b02))
                        require(len(header) == 48 and len(rows) == u32(header, 16) * 104,
                                'animation inventory mesh record extent')
                        for p in range(0, len(rows), 104):
                            slot = rows[p + 24]
                            require(slot < len(keys), 'animation inventory first texture index')
                            first_textures[keys[slot]] += 1
                            mesh_records += 1
        contexts.extend(DirectoryContext(section.number, c, frozenset(textures))
                        for c in roots if c.kind == DIRECTORY)
    return SourceInventory(tuple(contexts), first_textures, mesh_records, len(index.sections))


def classify_omission(chunk, inventory=None):
    """Report directory-only omission consequences, retaining ordinary packs.

    With no inventory, read the default private source index and stream. Batch
    callers can supply inventory_source's result to avoid repeated full scans.
    A directory must match exactly one indexed source location; changed bytes
    cannot inherit another directory's texture-resolution evidence.
    """
    animations = decode_directory(chunk)
    if inventory is None:
        from merge import DEFAULT_MW, load_index
        index, stream, _ = load_index(DEFAULT_MW, 'L2RA')
        inventory = inventory_source(index, stream)
    matches = [c for c in inventory.directories
               if c.chunk.offset == chunk.offset and c.chunk.payload == chunk.payload]
    require(len(matches) == 1, 'animation directory source location missing/ambiguous')
    source = matches[0]
    frames = tuple(key for animation in animations for key in animation.frames)
    hashes = sorted(set(frames))
    resolved = sum(key in source.textures for key in frames)
    counts = {key: inventory.first_textures[key] for key in hashes}
    return {
        'section': source.section,
        'offset': chunk.offset,
        'animations': animations,
        'texture_hashes': frames,
        'resolved_frames': resolved,
        'total_frames': len(frames),
        'ordinary_textures_retained': resolved == len(frames),
        'first_texture_meshes': sum(counts.values()),
        'first_texture_meshes_by_hash': counts,
        'consequence': 'ordinary textures remain static; frame cycling is lost',
    }
