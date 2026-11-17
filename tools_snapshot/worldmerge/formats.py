"""Bounded, lossless chunk and streaming-index structures for private experiments."""
from dataclasses import dataclass
import math
import struct


class FormatError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise FormatError(message)


def render_shift(shift_x, shift):
    """Resolve render metres; an explicit XY pair supersedes legacy scalar X."""
    value = (shift_x, 0) if shift is None else shift
    require(isinstance(value, (tuple, list)) and len(value) == 2,
            'render shift must contain two components (dx, dy)')
    require(all(isinstance(v, (int, float)) and math.isfinite(v) for v in value),
            'non-finite render shift')
    return tuple(value)


def u32(data, offset=0):
    require(0 <= offset <= len(data) - 4, 'truncated integer')
    return struct.unpack_from('<I', data, offset)[0]


@dataclass(frozen=True)
class Chunk:
    kind: int
    payload: bytes
    offset: int = 0

    def encode(self):
        return struct.pack('<II', self.kind, len(self.payload)) + self.payload


def chunks(data, base=0):
    """Parse envelopes only. Compressed container contents are never guessed."""
    result, offset = [], 0
    while offset < len(data):
        require(len(data) - offset >= 8, 'truncated chunk header')
        kind, size = struct.unpack_from('<II', data, offset)
        require(size <= len(data) - offset - 8, f'chunk {kind:08x} crosses parent')
        result.append(Chunk(kind, bytes(data[offset + 8:offset + 8 + size]), base + offset))
        offset += 8 + size
    return result


def encode_chunks(items):
    return b''.join(c.encode() for c in items)


@dataclass(frozen=True)
class Section:
    raw: bytes

    def __post_init__(self):
        require(len(self.raw) == 92, 'section record must contain 92 bytes')

    @property
    def number(self):
        return struct.unpack_from('<h', self.raw, 8)[0]

    @property
    def name(self):
        return f'{chr(64 + self.number // 100)}{self.number % 100:02d}'

    @property
    def offset(self):
        return u32(self.raw, 20)

    @property
    def size(self):
        return u32(self.raw, 24)

    @property
    def position(self):
        return struct.unpack_from('<3f', self.raw, 40)

    @property
    def scenery(self):
        return 100 <= self.number < 2100

    def replace(self, *, number=None, offset=None, size=None, shift_x=0):
        raw = bytearray(self.raw)
        if number is not None:
            require(100 <= number < 2100, 'scenery number outside A-T')
            struct.pack_into('<h', raw, 8, number)
            # Display/debug name and loading priority use the same section number.
            raw[:4] = (f'{chr(64 + number // 100)}{number % 100:02d}'.encode() + b'\0')
            struct.pack_into('<I', raw, 36, 10000 + number)
        if offset is not None:
            struct.pack_into('<I', raw, 20, offset)
        if size is not None:
            struct.pack_into('<III', raw, 24, size, size, 0)
            # The reference's plain records leave these auxiliary words zero.
            # Do not retain the source signature for a rebuilt section.
            struct.pack_into('<I', raw, 52, 0)
        if shift_x:
            struct.pack_into('<f', raw, 40, self.position[0] + shift_x)
        return Section(bytes(raw))


class TrackIndex:
    def __init__(self, data):
        self.parts = chunks(data)
        self.original_sizes = [len(c.payload) for c in self.parts]
        tables = [i for i, c in enumerate(self.parts) if c.kind == 0x34110]
        require(len(tables) == 1, 'expected exactly one section table')
        self.table = tables[0]
        raw = self.parts[self.table].payload
        require(len(raw) % 92 == 0, 'section-table size is not divisible by 92')
        self.sections = [Section(raw[i:i + 92]) for i in range(0, len(raw), 92)]

    def encode(self):
        parts = []
        for i, old in enumerate(self.parts):
            new = Chunk(old.kind, b''.join(s.raw for s in self.sections), old.offset) if i == self.table else old
            parts.append(new)
            growth = len(new.payload) - self.original_sizes[i]
            if growth:
                # Retain every subsequent absolute alignment modulo 128.
                pad = -growth % 128
                if pad and pad < 8:
                    pad += 128
                if pad:
                    parts.append(Chunk(0, bytes(pad - 8)))
        return encode_chunks(parts)

    def validate(self, stream_size):
        numbers = [s.number for s in self.sections]
        require(len(set(numbers)) == len(numbers), 'duplicate section number')
        for s in self.sections:
            require(s.number >= 0, 'negative section number')
            require(s.offset <= stream_size and s.size <= stream_size - s.offset,
                    f'{s.name}: section outside stream')
            require(all(math.isfinite(v) for v in s.position), f'{s.name}: non-finite position')
        spans = sorted((s.offset, s.offset + s.size) for s in self.sections if s.size)
        require(all(a[1] <= b[0] for a, b in zip(spans, spans[1:])), 'overlapping stream sections')
        return len(numbers)

    def boundaries(self):
        return index_boundaries(self)

    def add_visibility(self, boundary):
        require(boundary.extended, 'later visibility boundary required')
        require(boundary.number not in {b.number for b in self.boundaries()}, 'duplicate boundary number')
        for i, top in enumerate(self.parts):
            if top.kind != 0x80034150:
                continue
            parts = chunks(top.payload, top.offset + 8)
            require(any(c.kind == 0x34156 for c in parts), 'later visibility layout required')
            for j, c in enumerate(parts):
                if c.kind == 0x34151:
                    raw = bytearray(c.payload)
                    count = u32(raw, 4)
                    require(count < (len(raw) - 8) // 2, 'drivable list capacity exhausted')
                    numbers = list(struct.unpack_from(f'<{count}h', raw, 8))
                    require(boundary.number not in numbers, 'duplicate drivable number')
                    numbers.append(boundary.number)
                    numbers.sort()
                    struct.pack_into('<I', raw, 4, count + 1)
                    struct.pack_into(f'<{count + 1}h', raw, 8, *numbers)
                    parts[j] = Chunk(c.kind, bytes(raw))
            # An isolated visibility row requests only this new section.
            # It never points at the source city's unrelated section numbers.
            row = bytearray(36)
            struct.pack_into('<hBBhh', row, 12, boundary.number, 1, 8, 1, boundary.number)
            parts.extend([Chunk(0x34152, boundary.raw), Chunk(0x34153, bytes(row))])
            self.parts[i] = Chunk(top.kind, encode_chunks(parts), top.offset)
            return
        raise FormatError('missing visibility container')


def free_number(*indices):
    used = {s.number for idx in indices for s in idx.sections}
    for idx in indices:
        used.update(b.number for b in idx.boundaries())
        for top in idx.parts:
            if top.kind == 0x80034150:
                for c in chunks(top.payload, top.offset + 8):
                    if c.kind == 0x34151:
                        require(len(c.payload) >= 8, 'truncated drivable list')
                        count = u32(c.payload, 4)
                        require(count <= (len(c.payload) - 8) // 2, 'drivable list range')
                        used.update(struct.unpack_from(f'<{count}h', c.payload, 8))
    # Keep the corresponding LOD slot free for the next rendering proof.
    return next(n for n in range(101, 2100)
                if 1 <= n % 100 < 40 and n not in used and n + 40 not in used)


@dataclass(frozen=True)
class Boundary:
    raw: bytes
    extended: bool

    @property
    def number(self):
        return struct.unpack_from('<h', self.raw, 8)[0]

    @property
    def bounds(self):
        return struct.unpack_from('<4f', self.raw, 24 if self.extended else 12)

    @property
    def vertices(self):
        return list(struct.iter_unpack('<2f', self.raw[48 if self.extended else 36:]))

    def translate(self, number, shift_x=0, *, shift=None):
        dx, dy = render_shift(shift_x, shift)
        raw = bytearray(self.raw if self.extended else self.raw[:12] + bytes(12) + self.raw[12:])
        raw[:8] = bytes(8)  # runtime linked-list pointers
        struct.pack_into('<h', raw, 8, number)
        for p in (24, 32, 40, *range(48, len(raw), 8)):
            struct.pack_into('<f', raw, p, struct.unpack_from('<f', raw, p)[0] + dx)
            if dy:
                struct.pack_into('<f', raw, p + 4, struct.unpack_from('<f', raw, p + 4)[0] + dy)
        return Boundary(bytes(raw), True)

    def validate(self):
        lo_x, lo_y, hi_x, hi_y = self.bounds
        values = [v for point in self.vertices for v in point]
        require(all(math.isfinite(v) for v in (*self.bounds, *values)), 'non-finite boundary')
        require(lo_x <= hi_x and lo_y <= hi_y, 'inverted boundary bounds')
        require(len(self.vertices) >= 3, 'boundary has fewer than three vertices')
        require(all(lo_x - .01 <= x <= hi_x + .01 and lo_y - .01 <= y <= hi_y + .01
                    for x, y in self.vertices), 'polygon outside boundary bounds')


def parse_boundaries(raw, extended):
    header, p, result = (48 if extended else 36), 0, []
    while p < len(raw):
        require(len(raw) - p >= header, 'truncated boundary header')
        nv = raw[p + 10]
        require(3 <= nv < 128, 'invalid boundary vertex count')
        size = header + nv * 8
        require(size <= len(raw) - p, 'boundary vertices cross chunk')
        b = Boundary(raw[p:p + size], extended)
        b.validate()
        result.append(b)
        p += size
    return result


def index_boundaries(index):
    # The extra visibility chunk identifies the later layout independently of
    # arbitrary names or executable details. The older index has no such chunk.
    for top in index.parts:
        if top.kind == 0x80034150:
            parts = chunks(top.payload, top.offset + 8)
            extended = any(c.kind == 0x34156 for c in parts)
            for c in parts:
                if c.kind == 0x34152:
                    yield from parse_boundaries(c.payload, extended)


