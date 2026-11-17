"""Proof gates for empty meshes and scenery using external solid resources.

No production dispatch is installed here. The closure input maps actual source
solid-header keys to their indexed section numbers, independently of output or
writer statistics. Accepted sections must have passed whole-section conversion.
"""
from collections import Counter
import struct

from formats import Chunk, chunks, require, u32


def _one(parts, kind):
    found = [p for p in parts if p.kind == kind]
    require(len(found) == 1, f'refonly singleton {kind:08x}')
    return found[0]


def _aligned(c, alignment=16):
    pad = -(c.offset + 8) % alignment
    require(pad <= len(c.payload) and c.payload[:pad] == b'\x11' * pad,
            'refonly alignment filler')
    return c.payload[pad:]


def convert_empty_mesh(c, position, stats):
    """Write only the proved zero-material, zero-payload mesh shape.

    Native empty meshes have a 52-byte header and empty material/index leaves;
    there are no vertex or material-name leaves. Nonempty meshes belong to the
    ordinary writer and must not be passed here.
    """
    from convert import Builder

    require(c.kind == 0x80134100, 'refonly mesh kind')
    parts = chunks(c.payload, c.offset + 8)
    kinds = Counter(p.kind for p in parts)
    require(set(kinds) <= {0x134900, 0x134b02, 0x134b03, 0x134b01, 0x134c02},
            'refonly undecoded mesh child')
    head = _aligned(_one(parts, 0x134900))
    require(len(head) == 48 and u32(head, 16) == 0,
            'refonly requires zero source materials')
    # Check payload before header consistency so a lost material table cannot
    # turn a populated mesh into a silently accepted empty resource.
    vertices = [_aligned(p, 128) for p in parts if p.kind == 0x134b01]
    require(not any(vertices) and not u32(head, 20) and not u32(head, 24),
            'refonly missing payload: vertices without materials')
    indices = _aligned(_one(parts, 0x134b03))
    require(not indices and not u32(head, 44),
            'refonly missing payload: indices without materials')
    require(not _aligned(_one(parts, 0x134b02)),
            'refonly material payload with zero count')
    require(kinds == Counter({0x134900: 1, 0x134b02: 1, 0x134b03: 1}),
            'refonly unproved empty mesh leaves')
    require(u32(head, 8) == 18 and not any(head[:8] + head[12:]),
            'refonly unproved empty mesh header')
    out = Builder(position + 8)
    out.add(0x134900, head + bytes(4), 16)
    out.add(0x134b02, b'', 16)
    out.add(0x134b03, b'', 16)
    return Chunk(c.kind, bytes(out.data)).encode()


def require_section_geometry(source, target, stats, solid_sections, accepted_sections):
    """Keep the ordinary guard, or prove every reference-only instance closed.

    The source inventory, not emitted resources or stats, supplies providers.
    Every nonsentinel LOD key used by an instance must have an accepted provider.
    Sentinel-only rows have no proved solid provider and remain refused.
    Compare source and target scene/model/instance arrays before checking closure
    so dropping a list cannot make the dependency check vacuously true.
    """
    old_roots, new_roots = chunks(source), chunks(target)
    if any(c.kind == 0x80134000 for c in old_roots):
        require(stats.solids and stats.instances, 'section lacks geometry or instances')
        return
    require(not stats.solids and not any(c.kind == 0x80134000 for c in new_roots),
            'refonly unexpected local solids')
    old = [c for c in old_roots if c.kind == 0x80034100]
    new = [c for c in new_roots if c.kind == 0x80034100]
    require(old and len(old) == len(new), 'refonly scenery list changed')
    wanted, count, without_model = set(), 0, 0
    for before, after in zip(old, new):
        a, b = chunks(before.payload, before.offset + 8), chunks(after.payload, after.offset + 8)
        models = _one(a, 0x34102).payload
        expected = bytearray(models)
        for p in range(0, len(models), 72):
            for off in (24, 28, 32, 36):
                if u32(models, p+off) == 0xed85ba82:
                    struct.pack_into('<I', expected, p+off, 0x1f389568)
        require(len(models) % 72 == 0 and expected == _one(b, 0x34102).payload,
                'refonly model list changed')
        src, dst = _aligned(_one(a, 0x34103)), _aligned(_one(b, 0x34103))
        require(len(src) % 64 == 0 and len(dst) == len(src) // 64 * 96,
                'refonly instance list changed')
        for i in range(len(src) // 64):
            index = struct.unpack_from('<h', src, i * 64 + 62)[0]
            require(0 <= index < len(models) // 72, 'refonly instance model index')
            require(index == struct.unpack_from('<h', dst, i * 96 + 84)[0],
                    'refonly instance model changed')
            keys = {u32(models, index * 72 + off) for off in (24, 28, 32, 36)
                    if u32(models, index * 72 + off) not in (0, 0xbe43edbb, 0x90f70174)}
            wanted.update(keys)
            without_model += not keys
        count += len(src) // 64
    require(count and stats.instances == count, 'refonly instance list changed')
    missing = sorted(key for key in wanted
                     if not (set(solid_sections.get(key, ())) & set(accepted_sections)))
    require(not missing, 'refonly unresolved solids: ' + ','.join(f'{k:08x}' for k in missing))
    require(not without_model, f'refonly instances without a solid key: {without_model}')
