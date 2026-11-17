"""The fixed crossing seam, in placed physics (X, Z) metres.

Outline vertices use (Z, -X). The 0.1 m gap avoids touching polygons;
the loader's 0.1 m outline tolerance covers the seam in either direction.
"""
import struct

from formats import Boundary
from visibility import Row

SHIFT = (0., 8192.)
# number: (physics Z limit, keep below)
CUTS = {205: (6599.95, True), 212: (6599.95, True),
        220: (6599.95, True), 533: (6599.95, True),
        326: (6600.05, False), 1238: (6600.05, False),
        1334: (6600.05, False)}
ROW_ADDITIONS = {326: (220, 260), 220: (366,)}


def apply(boundaries, rows, shift):
    """Keep ring traversal order and untouched records; only this placement cuts."""
    if tuple(shift) != SHIFT:
        return boundaries, rows
    result = []
    for boundary in boundaries:
        if boundary.number not in CUTS:
            result.append(boundary)
            continue
        limit, below = CUTS[boundary.number]
        ring, polygon = boundary.vertices, []
        for a, b in zip(ring, ring[1:] + ring[:1]):
            a_in = a[0] <= limit if below else a[0] >= limit
            b_in = b[0] <= limit if below else b[0] >= limit
            if a_in:
                polygon.append(a)
            if a_in != b_in:
                polygon.append((limit, a[1] + (b[1]-a[1])*(limit-a[0])/(b[0]-a[0])))
        raw = bytearray(boundary.raw[:48])
        raw[10] = len(polygon)
        xs, ys = zip(*polygon)
        low, high = (min(xs), min(ys)), (max(xs), max(ys))
        struct.pack_into('<6f', raw, 24, *low, *high,
                         (low[0]+high[0])/2, (low[1]+high[1])/2)
        raw += b''.join(struct.pack('<2f', *p) for p in polygon)
        cut = Boundary(bytes(raw), True)
        cut.validate()
        result.append(cut)
    edited = []
    for row in rows:
        if row.number not in ROW_ADDITIONS:
            edited.append(row)
            continue
        entries = tuple(sorted(set(row.entries) | set(ROW_ADDITIONS[row.number])))
        header = bytearray(row.header)
        header[15] = len(entries)
        struct.pack_into('<h', header, 16, len(entries))
        edited.append(Row(bytes(header), entries, bytes(2)))
    return result, edited
