"""Light-material references and model-local position markers.

The hash/pointer table is *not* an aligned marker array. Only markers need new
16-byte filler at their destination. Native readers are noted per function below.
No hook is installed here; the solid writer retains responsibility for sibling
counts and material indices (validate_solid_sidecars before emitting a solid).
"""
from collections import Counter
import math
import struct

from formats import Chunk, chunks, require, u32


LIGHT_MATERIALS = 0x134013
POSITION_MARKERS = 0x13401a


def convert_sidecar(p, position, stats):
    """Return one encoded leaf at envelope offset position; draw stats unchanged.

    Only the decoded source subset is writable: marker type 0..5, zero optional
    flare selector and reserved word, affine finite matrix, unloaded pointers.
    Hashes name external resources, so they must never be treated as indices.
    """
    require(isinstance(position, int) and position >= 0, 'sidecar destination offset')
    raw = p.payload
    if p.kind == LIGHT_MATERIALS:
        require(len(raw) % 8 == 0 and 0 < len(raw) // 8 <= 127,
                'light-material entry extent/count')
        for off in range(0, len(raw), 8):
            require(u32(raw, off + 4) == 0, 'loaded light-material pointer')
        return Chunk(p.kind, bytes(raw)).encode()
    require(p.kind == POSITION_MARKERS, 'undecoded solid sidecar')
    pad = -(p.offset + 8) % 16
    require(pad <= len(raw) and raw[:pad] == b'\x11' * pad, 'marker alignment filler')
    raw = raw[pad:]
    require(len(raw) % 80 == 0 and 0 < len(raw) // 80 <= 127,
            'marker stride/count')
    for off in range(0, len(raw), 80):
        require(u32(raw, off + 4) <= 5, 'undecoded source marker type')
        require(raw[off + 8:off + 16] == bytes(8), 'undecoded source marker parameters')
        matrix = struct.unpack_from('<16f', raw, off + 16)
        require(all(math.isfinite(v) for v in matrix), 'non-finite marker matrix')
        require(tuple(matrix[i] for i in (3, 7, 11, 15)) == (0, 0, 0, 1),
                'non-affine marker matrix')
    filler = b'\x11' * (-(position + 8) % 16)
    return Chunk(p.kind, filler + raw).encode()


def validate_solid_sidecars(solid, *, target=False):
    """Validate sibling counts and own-table references before using leaf output.

    Material +24..28 index textures; +29 indexes light materials. The latter
    alone permits 255 (global default). Marker hashes/types are never indices.
    target selects 144-byte material records instead of 104-byte source records.
    This does not validate unrelated geometry or implement a solid writer.
    """
    parts = chunks(solid.payload, solid.offset + 8)
    counts = Counter(p.kind for p in parts)
    require(counts[0x134011] == counts[0x134012] == 1, 'sidecar solid table singletons')
    require(all(counts[k] <= 1 for k in (LIGHT_MATERIALS, POSITION_MARKERS)),
            'duplicate solid sidecar')
    header = next(p for p in parts if p.kind == 0x134011)
    pad = -(header.offset + 8) % 16
    require(header.payload[:pad] == b'\x11' * pad, 'solid header filler')
    h = header.payload[pad:]
    require(len(h) >= 164, 'sidecar solid header extent')
    textures = next(p.payload for p in parts if p.kind == 0x134012)
    require(len(textures) == h[25] * 8, 'solid texture table count')
    lights = next((p.payload for p in parts if p.kind == LIGHT_MATERIALS), b'')
    require(len(lights) == h[26] * 8, 'solid light-material table count')
    stride = 144 if target else 104
    for mesh in (p for p in parts if p.kind == 0x80134100):
        mp = chunks(mesh.payload, mesh.offset + 8)
        rows = [p for p in mp if p.kind == 0x134b02]
        require(len(rows) == 1, 'sidecar material table singleton')
        table = rows[0]
        pad = -(table.offset + 8) % 16
        require(table.payload[:pad] == b'\x11' * pad, 'material table filler')
        raw = table.payload[pad:]
        require(len(raw) % stride == 0, 'sidecar material table stride')
        for off in range(0, len(raw), stride):
            require(all(i < h[25] for i in raw[off + 24:off + 29]),
                    'solid texture index out of range')
            index = raw[off + 29]
            require(index == 255 or index < h[26], 'solid light-material index out of range')
