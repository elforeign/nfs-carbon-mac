"""Bounded 0x3bc00 world-emitter conversion; no external key resolution.

Both native readers use a 16-byte header, then 80-byte library placements
with inline 48-byte triggers. Only matrix translation XY and trigger center XY
change. Native references and inferred fields are noted beside each record type below.
"""
from collections import Counter
from dataclasses import dataclass
import math
import struct

from formats import Chunk, render_shift, require


@dataclass(frozen=True)
class EmitterLayout:
    raw: bytes
    section: int
    records: tuple
    triggers: tuple
    library_keys: Counter


def decode_emitters(c):
    """Accept only the observed disk schema; runtime/unknown fields fail closed."""
    require(c.kind == 0x3bc00, 'expected emitter chunk 0x3bc00')
    require(isinstance(c.offset, int) and c.offset >= 0, 'invalid emitter source offset')
    pad = -(c.offset + 8) % 16
    require(len(c.payload) >= pad + 16, 'truncated emitter header')
    require(c.payload[:pad] == b'\x11' * pad, 'invalid emitter alignment filler')
    raw = c.payload[pad:]
    swapped, version, count, section = struct.unpack_from('<4I', raw)
    require(swapped == 0, 'emitter endian/runtime state not decoded yet')
    require(version == 5, 'emitter header version not decoded yet')
    require(0 < section <= 0xffff, 'emitter section not decoded yet')
    require(count <= (len(raw) - 16) // 80, 'emitter record count exceeds extent')
    records, triggers, keys = [], [], Counter()
    p = 16
    for _ in range(count):
        require(p + 80 <= len(raw), 'truncated emitter record')
        key, reserved, owner, nt, runtime = struct.unpack_from('<IIHHI', raw, p)
        require(reserved == 0, 'emitter record +4 not decoded yet')
        require(owner == section, 'emitter record section not decoded yet')
        require(runtime == 0, 'emitter live group pointer is not disk data')
        matrix = struct.unpack_from('<16f', raw, p + 16)
        require(all(math.isfinite(v) for v in matrix), 'non-finite emitter matrix')
        require(tuple(matrix[i] for i in (3, 7, 11, 15)) == (0, 0, 0, 1),
                'non-affine emitter matrix not decoded yet')
        records.append(p)
        keys[key] += 1
        p += 80
        require(nt <= (len(raw) - p) // 48, 'emitter trigger count exceeds extent')
        for _ in range(nt):
            next_node, prev_node, library = struct.unpack_from('<3I', raw, p)
            require((next_node, prev_node, library) == (3, 3, 0),
                    'emitter trigger link placeholders not decoded yet')
            radius, x, y, z, reserved, cooldown = struct.unpack_from('<6f', raw, p + 12)
            require(all(math.isfinite(v) for v in (radius, x, y, z, reserved, cooldown)),
                    'non-finite emitter trigger')
            require(radius >= 0 and cooldown >= 0, 'negative emitter trigger radius/cooldown')
            require(raw[p + 28:p + 32] == bytes(4), 'emitter trigger +28 not decoded yet')
            _, state, flags, timer, reserved = struct.unpack_from('<HBBII', raw, p + 36)
            require((state, flags, timer) == (1, 0, 0), 'emitter trigger runtime state not disk data')
            require(reserved == 0, 'emitter trigger +44 not decoded yet')
            triggers.append(p)
            p += 48
    require(p == len(raw), 'emitter record count/extent mismatch')
    return EmitterLayout(raw, section, tuple(records), tuple(triggers), keys)


def convert_emitters(c, position, stats, shift_x=0, *, shift=None):
    """Return an encoded target chunk at position, retaining section IDs and keys.

    Stats gains emitter_chunks, emitters, emitter_triggers and an
    emitter_library_keys Counter only after the whole conversion succeeds.
    Keys are opaque external emittergroup collection references, not resolved
    assets. Section renumbering, if required, is a separate caller policy.
    """
    require(isinstance(position, int) and position >= 0, 'invalid emitter output position')
    dx, dy = render_shift(shift_x, shift)
    layout = decode_emitters(c)
    raw = bytearray(layout.raw)
    for axis, delta in ((0, dx), (4, dy)):
        if delta:
            for p in (*[r + 64 for r in layout.records], *[t + 16 for t in layout.triggers]):
                value = struct.unpack_from('<f', raw, p + axis)[0] + delta
                require(math.isfinite(value) and abs(value) <= 3.4028234663852886e38,
                        'emitter position shift overflows float32')
                struct.pack_into('<f', raw, p + axis, value)
    pad = -(position + 8) % 16
    out = Chunk(0x3bc00, b'\x11' * pad + bytes(raw)).encode()
    for name, count in (('emitter_chunks', 1), ('emitters', len(layout.records)),
                        ('emitter_triggers', len(layout.triggers))):
        setattr(stats, name, getattr(stats, name, 0) + count)
    if not hasattr(stats, 'emitter_library_keys'):
        stats.emitter_library_keys = Counter()
    stats.emitter_library_keys.update(layout.library_keys)
    return out
