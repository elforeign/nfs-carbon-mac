"""Convert visibility tables to the later loader layout, without moving geometry.

The returned bytes are a 0x80034150 *payload*. Place its enclosing header on a
16-byte boundary: the selector child aligns its data using absolute addresses.
The native reader retains unknown children and serialized runtime link words.
No stream files are read and no archive is written by this module.
"""
import argparse
from collections import Counter
from dataclasses import dataclass, replace
import json
from pathlib import Path
import struct
import sys

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(HERE))
from formats import (Chunk, FormatError, TrackIndex, chunks,
                     encode_chunks, parse_boundaries, require, u32)

CONTAINER = 0x80034150
DRIVE, BOUNDARIES, ROWS, LOADING, SELECTORS = 0x34151, 0x34152, 0x34153, 0x34155, 0x34156
SLOTS = 512
ROW_LIMIT = 0x180
ROW_ORDERS = ('providers-first', 'verbatim')
PARENT = HERE.parents[2]
DEFAULT_MW = PARENT / 'Need For Speed Most Wanted Black Edition' / 'TRACKS' / 'L2RA.BUN'
DEFAULT_CARBON = PARENT / 'inputs' / 'NFSC' / 'TRACKS' / 'L5RA.BUN'


@dataclass(frozen=True)
class Row:
    header: bytes
    entries: tuple
    spare: bytes

    @property
    def number(self):
        return struct.unpack_from('<h', self.header, 12)[0]

    @property
    def cap(self):
        return self.header[15]

    def encode(self):
        return self.header + struct.pack(f'<{len(self.entries)}h', *self.entries) + self.spare


def read_rows(raw):
    """007A8880: signed cap at +15 sets stride; 007A4680 reads +16/+18."""
    rows, p = [], 0
    while p < len(raw):
        require(len(raw) - p >= 20, 'truncated visibility row header')
        cap = struct.unpack_from('<b', raw, p + 15)[0]
        count = struct.unpack_from('<h', raw, p + 16)[0]
        require(0 <= count <= ROW_LIMIT, 'visibility row exceeds 384-entry copy budget')
        require(0 <= cap and count <= cap, 'visibility row count exceeds signed cap')
        end = p + 20 + cap * 2
        require(end <= len(raw), 'visibility row crosses chunk')
        entries = struct.unpack_from(f'<{count}h', raw, p + 18)
        rows.append(Row(raw[p:p + 18], entries, raw[p + 18 + count * 2:end]))
        p = end
    return tuple(rows)


@dataclass(frozen=True)
class Visibility:
    parts: tuple
    lod_offset: int
    drivable: tuple
    slots: tuple
    boundaries: tuple
    rows: tuple
    loading: tuple
    selectors: tuple
    selector_padding: bytes
    extended: bool

    def encode(self):
        """Rebuild decoded lists/records, preserving all unused bytes and order."""
        drive = struct.pack('<II', self.lod_offset, len(self.drivable))
        drive += struct.pack(f'<{len(self.slots)}h', *self.slots)
        header = 48 if self.extended else 36
        boundary_bytes = b''.join(b.raw[:header] + b''.join(struct.pack('<2f', *v)
                                                        for v in b.vertices)
                                  for b in self.boundaries)
        bodies = {DRIVE: drive, BOUNDARIES: boundary_bytes,
                  ROWS: b''.join(r.encode() for r in self.rows),
                  LOADING: b''.join(self.loading),
                  SELECTORS: self.selector_padding + b''.join(self.selectors)}
        return encode_chunks(Chunk(c.kind, bodies.get(c.kind, c.payload)) for c in self.parts)


def read(payload, *, extended=True, base=8):
    """Read a native payload with loader strides, independent of conversion.

    base is the absolute payload offset (only its low four bits matter).
    Loading-section tails and selector records remain opaque, but bounded.
    """
    parts = tuple(chunks(payload, base))
    by_kind = {}
    for part in parts:
        if part.kind in (DRIVE, BOUNDARIES, ROWS, LOADING, SELECTORS):
            require(part.kind not in by_kind, f'duplicate visibility child {part.kind:08x}')
            by_kind[part.kind] = part
    required = {DRIVE, BOUNDARIES, ROWS, LOADING} | ({SELECTORS} if extended else set())
    require(required <= by_kind.keys(), 'missing visibility child')
    require(extended or SELECTORS not in by_kind, 'source already has the later layout')
    raw = by_kind[DRIVE].payload
    require(len(raw) >= 8 and len(raw) % 2 == 0, 'truncated drivable list')
    count = u32(raw, 4)
    slots = struct.unpack_from(f'<{(len(raw) - 8) // 2}h', raw, 8)
    require(count <= len(slots), 'drivable count exceeds slot array')
    boundaries = tuple(parse_boundaries(by_kind[BOUNDARIES].payload, extended))
    rows = read_rows(by_kind[ROWS].payload)
    raw = by_kind[LOADING].payload
    require(len(raw) % 0x4c == 0, 'loading-section record crosses chunk')
    loading = tuple(raw[p:p + 0x4c] for p in range(0, len(raw), 0x4c))
    padding, selectors = b'', ()
    if extended:
        part = by_kind[SELECTORS]
        pad = -(part.offset + 8) % 16
        require(len(part.payload) >= pad, 'truncated selector alignment')
        padding, raw = part.payload[:pad], part.payload[pad:]
        require(len(raw) % 64 == 0, 'selector record crosses chunk')
        selectors = tuple(raw[p:p + 64] for p in range(0, len(raw), 64))
    return Visibility(parts, u32(by_kind[DRIVE].payload), slots[:count], slots,
                      boundaries, rows, loading, selectors, padding, extended)


def payload_of(index):
    parts = [c for c in index.parts if c.kind == CONTAINER]
    require(len(parts) == 1, 'expected one visibility container')
    return parts[0].payload


def ordered_entries(entries, rows):
    """Stable V-resource prefix; the remaining entries keep serialized order."""
    require(rows in ROW_ORDERS, 'unknown visibility row order')
    if rows == 'verbatim':
        return entries
    return tuple(n for n in entries if n // 100 == 22) + tuple(
        n for n in entries if n // 100 != 22)


def late_providers(rows):
    """Count V entries with any preceding scenery entry, including repeats."""
    count = 0
    for row in rows:
        scenery = False
        for n in row.entries:
            if n // 100 == 22:
                count += scenery
            scenery |= 100 <= n < 2100
    return count


def convert(source_index, *, rows='providers-first'):
    """Widen headers; order only converted source rows, preserving membership."""
    source = read(payload_of(source_index), extended=False)
    require(len(source.slots) <= SLOTS, 'source drivable slots exceed later capacity')
    drive = struct.pack('<II', source.lod_offset, len(source.drivable))
    drive += struct.pack(f'<{len(source.slots)}h', *source.slots)
    drive += bytes((SLOTS - len(source.slots)) * 2)
    boundaries = b''.join(b.raw[:12] + bytes(12) + b.raw[12:] for b in source.boundaries)
    out = [Chunk(DRIVE, drive), Chunk(BOUNDARIES, boundaries)]
    # The container header is 16-byte aligned, its payload starts at +8.
    position = 8 + sum(8 + len(c.payload) for c in out)
    out.append(Chunk(SELECTORS, b'\x11' * (-(position + 8) % 16)))
    out.extend((Chunk(LOADING, b''), Chunk(ROWS, b''.join(
        replace(r, entries=ordered_entries(r.entries, rows)).encode() for r in source.rows))))
    return encode_chunks(out)


def absent_entries(table, numbers):
    """Count occurrences by row and number, including absent resource numbers."""
    return Counter((row.number, n) for row in table.rows for n in row.entries if n not in numbers)


def check(payload, section_numbers, *, source_index=None, rows='providers-first'):
    """Apply the later loader's rules to serialized output, not writer objects.

    Missing stream references are permitted only where the source already had
    that absence, including multiplicity and row number. The optional source
    index supports isolated fixtures; by default it is read from the private
    source archive. section_numbers describes the actually written stream table.
    """
    table = read(payload)
    require(len(table.slots) == SLOTS, 'later drivable list must have 512 slots')
    require(table.lod_offset == 40, 'unexpected scenery LOD offset')
    require(not table.loading, 'converted loading sections must be empty')
    require(not table.selectors, 'converted selector table must be empty')
    # Repeated drivable slots occur in the source and do not affect lookup.
    bounds = {b.number: b for b in table.boundaries}
    by_number = {r.number: r for r in table.rows}
    require(len(bounds) == len(table.boundaries), 'duplicate boundary number')
    require(len(by_number) == len(table.rows), 'duplicate visibility row number')
    missing_bounds = set(table.drivable) - bounds.keys()
    # Position lookup walks every drivable boundary, not just the slot array
    # (007A8880 classification, then 007A03E0 and 007A4680).
    zones = {n for n in bounds if 100 <= n < 2100 and 1 <= n % 100 < table.lod_offset}
    missing_rows = (set(table.drivable) | zones) - by_number.keys()
    require(not missing_bounds, f'drivable numbers without a boundary: {sorted(missing_bounds)}')
    require(not missing_rows, f'drivable numbers without a row: {sorted(missing_rows)}')
    require(all(100 <= n < 2100 and 1 <= n % 100 < table.lod_offset
                for n in table.drivable), 'drivable number outside loader zone range')
    require(by_number.keys() <= bounds.keys(), 'row has no boundary')
    if source_index is None:
        source_index = TrackIndex(DEFAULT_MW.read_bytes())
    source = read(payload_of(source_index), extended=False)
    baseline = absent_entries(source, {s.number for s in source_index.sections})
    absent = absent_entries(table, set(section_numbers))
    extra = absent - baseline
    require(not extra, f'new absent row entries: {sum(extra.values())}')
    require(len(source.rows) == len(table.rows), 'visibility row count changed')
    for before, after in zip(source.rows, table.rows):
        require(Counter(before.entries) == Counter(after.entries),
                f'row {before.number}: entry multiset changed')
        require(before.header == after.header and before.spare == after.spare,
                f'row {before.number}: header or spare bytes changed')
    late = late_providers(table.rows)
    if rows == 'providers-first':
        require(late == 0, f'V-resource after scenery: {late} placements')
    require(all(b.entries == ordered_entries(a.entries, rows)
                for a, b in zip(source.rows, table.rows)), 'visibility row stable order changed')
    scenery = sum(count for (_, n), count in absent.items() if n < 2100)
    return dict(drivable=len(table.drivable), boundaries=len(table.boundaries), rows=len(table.rows),
                lod_offset=table.lod_offset, drivable_without_row=len(missing_rows),
                largest_row=max((len(r.entries) for r in table.rows), default=0),
                row_entries=sum(len(r.entries) for r in table.rows),
                absent_entries=sum(absent.values()), absent_scenery_entries=scenery,
                absent_resource_entries=sum(absent.values()) - scenery,
                source_absent_entries=sum(baseline.values()),
                absent_entries_equal_source=absent == baseline,
                row_order=rows, row_multisets_equal=True,
                rows_changed=sum(a.entries != b.entries for a, b in zip(source.rows, table.rows)),
                v_after_scenery_before=late_providers(source.rows), v_after_scenery=late)


def proof(source_index, native_index, *, rows='providers-first'):
    """In-memory acceptance proof; every comparison reads serialized output."""
    payload = convert(source_index, rows=rows)
    report = check(payload, [s.number for s in source_index.sections], source_index=source_index, rows=rows)
    require(report['absent_entries_equal_source'], 'source absent references changed')
    source = read(payload_of(source_index), extended=False)
    output = read(payload)
    differences = sum(a.number != b.number or a.raw[12:] != b.raw[24:]
                      for a, b in zip(source.boundaries, output.boundaries))
    differences += abs(len(source.boundaries) - len(output.boundaries))
    require(differences == 0, 'boundary coordinates or numbers changed')
    identical = [r.encode() for r in source.rows] == [r.encode() for r in output.rows]
    native_payload = payload_of(native_index)
    native = read(native_payload)
    exact = native.encode() == native_payload
    require(exact, 'native visibility did not round-trip byte-exact')
    report.update(boundary_differences=differences, rows_byte_identical=identical,
                  payload_bytes=len(payload), native_payload_bytes=len(native_payload),
                  native_roundtrip_byte_exact=exact,
                  source_counts=[len(source.drivable), len(source.boundaries), len(source.rows),
                                 len(source.loading)],
                  native_counts=[len(native.drivable), len(native.boundaries), len(native.rows),
                                 len(native.loading)])
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', required=True)
    parser.add_argument('--mw-index', type=Path, default=DEFAULT_MW)
    parser.add_argument('--carbon-index', type=Path, default=DEFAULT_CARBON)
    parser.add_argument('--rows', choices=ROW_ORDERS, default=ROW_ORDERS[0])
    args = parser.parse_args(argv)
    if not all(p.is_file() for p in (args.mw_index, args.carbon_index)):
        print('private visibility indexes absent', file=sys.stderr)
        return 3
    try:
        print(json.dumps(proof(TrackIndex(args.mw_index.read_bytes()),
                               TrackIndex(args.carbon_index.read_bytes()), rows=args.rows), sort_keys=True))
    except (FormatError, OSError) as exc:
        print(f'visibility check failed: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
