"""Inspect and translate streamed event directories with identical layouts.

The loader/query closures at 0x72b130/0x72cdc0 and 0x7a19f0/0x7a3660
agree on all runtime reads. Tree authoring metadata and event words +8/+12
are unread in both closures, including dispatch, sound and unload; copy them.
Only world X and an explicitly supplied owning section number translate.
"""
from dataclasses import dataclass
import math
import struct

from convert import Builder, aligned_payload, translate_float
from formats import Chunk, chunks, render_shift, require


@dataclass(frozen=True)
class Event:
    offset: int
    selector: int
    dispatch_mask: int
    opaque: bytes               # Unread by either native consumer closure.
    position: tuple
    radius: float


@dataclass(frozen=True)
class Node:
    offset: int
    center: tuple
    parent: int                 # Authoring inference; unread at runtime.
    signed_count: int
    half_extent: tuple
    references: tuple


@dataclass(frozen=True)
class Directory:
    section: int
    offsets: tuple              # Aligned payload offsets of 0x36001/2/3.
    events: tuple
    nodes: tuple
    tree_metadata: tuple        # Authoring counts/depth inferred from the graph.
    tree_reserved: bytes        # Unread; preserved without a value whitelist.


def decode_events(c):
    """Return runtime fields and independently checked authoring inferences.

    Graph/count checks validate serialized structure. Their interpretation does
    not supply runtime semantics for the unread metadata, which stays verbatim.
    """
    require(c.kind == 0x80036000, 'expected event directory')
    parts = chunks(c.payload, c.offset + 8)
    require(tuple(p.kind for p in parts) == (0x36001, 0x36002, 0x36003),
            'event children/order not decoded yet')
    header, tree, records = (aligned_payload(p) for p in parts)
    offsets = tuple(p.offset + 8 + (-(p.offset + 8) % 16) for p in parts)
    require(len(header) == 32, 'event header extent')
    next_link, prev_link, version, section, count, relocated, tree_ptr, event_ptr = \
        struct.unpack('<8I', header)
    require(version == 2, 'event header version')
    require(not any((next_link, prev_link, relocated, tree_ptr, event_ptr)),
            'event header contains runtime fixups')
    require(count > 0 and len(records) == count * 32, 'event record count/extent')
    require(len(tree) >= 16 and (len(tree) - 16) % 48 == 0, 'event tree extent')
    pointer, leaves, branches, total, depth = struct.unpack_from('<I4H', tree)
    require(pointer == 0, 'event tree contains runtime fixup')
    require(total == (len(tree) - 16) // 48 and leaves == count and
            branches + leaves == total, 'event tree record count/extent')

    events = []
    for i in range(count):
        off = i * 32
        selector, mask = struct.unpack_from('<II', records, off)
        xyzr = struct.unpack_from('<4f', records, off + 16)
        require(all(math.isfinite(v) for v in xyzr) and xyzr[3] > 0,
                'invalid event sphere')
        events.append(Event(offsets[2] + off, selector, mask,
                            records[off + 8:off + 16], xyzr[:3], xyzr[3]))

    nodes = []
    owners = []
    for i in range(total):
        off = 16 + i * 48
        row = struct.unpack_from('<3fhh3f10h', tree, off)
        signed_count = row[4]
        require(1 <= abs(signed_count) <= 10, 'event tree reference count')
        require(all(math.isfinite(v) for v in row[:3] + row[5:8]) and
                all(v > 0 for v in row[5:8]), 'invalid event tree box')
        references = row[8:8 + abs(signed_count)]
        require(not any(row[8 + abs(signed_count):]), 'event tree inactive references')
        limit = total if signed_count > 0 else count
        require(all(0 <= ref < limit for ref in references), 'event tree reference range')
        nodes.append(Node(offsets[1] + off, row[:3], row[3], signed_count,
                          row[5:8], references))
        if signed_count < 0:
            owner = references[0]
            event = events[owner]
            require(row[:3] == event.position and row[5:8] == (event.radius,) * 3,
                    'event leaf/sphere mismatch')
            owners.append(owner)
    require(sorted(owners) == list(range(count)), 'event leaf owner coverage')
    require(sum(n.signed_count > 0 for n in nodes) == branches,
            'event tree branch count')
    seen, max_depth, pending = set(), 0, [(0, -1, 1)]
    while pending:
        index, parent, level = pending.pop()
        require(index not in seen, 'event tree cycle/shared node')
        seen.add(index)
        node = nodes[index]
        require(node.parent == parent, 'event tree parent inference mismatch')
        max_depth = max(max_depth, level)
        if node.signed_count > 0:
            pending.extend((ref, index, level + 1) for ref in node.references)
    require(len(seen) == total and max_depth == depth, 'event tree coverage/depth')
    return Directory(section, offsets, tuple(events), tuple(nodes),
                     (leaves, branches, total, depth), tree[12:16])


def convert_events(c, position, stats, shift_x=0, *, section=None, shift=None):
    """Emit aligned target bytes; count event-tree nodes after successful output.

    Rule 1: header N is a nonzero list-membership test in both loaders; sound
    compares record +0 in both games, even when category-like values are at +8.
    Rule 2: unread tree metadata and record +8/+12 remain byte-exact.
    Rule 3: shift node/sphere XY and map header +12 if section is given.
    Without a section mapping, retain the source identity. Position is a byte
    offset, never a section number. Section allocation belongs to the caller.
    """
    require(isinstance(position, int) and position >= 0, 'invalid event output position')
    dx, dy = render_shift(shift_x, shift)
    require(section is None or isinstance(section, int) and 0 <= section <= 0xffffffff,
            'invalid event target section')
    directory = decode_events(c)
    bodies = [bytearray(aligned_payload(p)) for p in chunks(c.payload, c.offset + 8)]
    if section is not None:
        struct.pack_into('<I', bodies[0], 12, section)
    if dx or dy:
        try:
            for node in directory.nodes:
                for axis, delta in ((0, dx), (4, dy)):
                    if delta:
                        translate_float(bodies[1], node.offset - directory.offsets[1] + axis, delta)
            for event in directory.events:
                for axis, delta in ((0, dx), (4, dy)):
                    if delta:
                        translate_float(bodies[2], event.offset - directory.offsets[2] + 16 + axis, delta)
        except OverflowError:
            require(False, 'event shift exceeds float32 range')
    out = Builder(position + 8)
    for kind, body in zip((0x36001, 0x36002, 0x36003), bodies):
        out.add(kind, body, 16)
    result = Chunk(c.kind, bytes(out.data)).encode()
    stats.nodes += len(directory.nodes)
    return result
