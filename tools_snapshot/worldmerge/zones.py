"""Convert global polygons, position markers and barrier lines offline.

shift is physics (X,Z); all serialized horizontal pairs use (Z,-X).
Returned chunks assume 16-byte-aligned top-level headers. Marker padding is
therefore eight bytes; rewrite_index preserves every existing header mod 128.
key_map replaces explicit hash fields only: polygon +48 for types 9/11,
marker +8, barrier +20. Polygon type 6's +48..63 section IDs stay opaque.
No traffic-pattern binding or gameplay policy is inferred here.
"""
import argparse
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(HERE))
from formats import Chunk, TrackIndex, chunks, encode_chunks, require, u32
from merge import DEFAULT_MW, DEFAULT_CARBON

ZONES, POLYGONS, MARKERS, BARRIERS = 0x80034147, 0x3414a, 0x34146, 0x3414d
KINDS = (ZONES, MARKERS, BARRIERS)
BUCKETS = 18


@dataclass(frozen=True)
class Zone:
    header: bytes
    vertices_raw: bytes

    @property
    def kind(self):
        return u32(self.header)

    @property
    def key(self):
        return u32(self.header, 48)

    @property
    def bounds(self):
        return struct.unpack_from('<4f', self.header, 32)

    @property
    def vertices(self):
        return tuple(struct.iter_unpack('<2f', self.vertices_raw))

    def encode(self):
        # Retain float bits, runtime words and the type-dependent union.
        return self.header + self.vertices_raw


@dataclass(frozen=True)
class Tables:
    parts: tuple
    children: tuple
    zones: tuple
    marker_padding: bytes
    markers: tuple
    barriers: tuple

    def encode(self):
        """Rebuild envelopes and rows, preserving native alignment bytes."""
        child = tuple(Chunk(c.kind, b''.join(z.encode() for z in self.zones))
                      if c.kind == POLYGONS else c for c in self.children)
        payloads = {ZONES: encode_chunks(child),
                    MARKERS: self.marker_padding + b''.join(self.markers),
                    BARRIERS: b''.join(self.barriers)}
        return tuple(Chunk(c.kind, payloads[c.kind], c.offset) for c in self.parts)


def select(index):
    """Extract the three global chunks, retaining absolute marker alignment."""
    return tuple(c for c in index.parts if c.kind in KINDS)


def read(items):
    """Reread serialized bytes using the executable's strides, never a writer.

    0079DBA0: nested 3414a, signed +66 stride, barrier length / 0x18.
    0079D890..0079D8DB: align(header+8,16), marker stride 0x30.
    0079DC60: bounds +32/+40, polygon vertices +68, signed count +64.
    Reject partial tails that the native integer division would silently drop.
    """
    parts = tuple(items)
    require(len(parts) == 3 and {c.kind for c in parts} == set(KINDS),
            'expected exactly one of each global chunk')
    by_kind = {c.kind: c for c in parts}
    children = tuple(chunks(by_kind[ZONES].payload))
    arrays = [c for c in children if c.kind == POLYGONS]
    require(len(arrays) == 1, 'expected one polygon array')
    raw, p, zones = arrays[0].payload, 0, []
    while p < len(raw):
        require(len(raw) - p >= 68, 'truncated zone header')
        count, stride = struct.unpack_from('<hh', raw, p + 64)
        require(count >= 3, 'invalid signed zone vertex count')
        require(stride >= 68 and stride == 68 + 8 * count,
                'zone vertex count disagrees with signed stride')
        require(stride <= len(raw) - p, 'zone stride crosses array end')
        zones.append(Zone(raw[p:p + 68], raw[p + 68:p + stride]))
        p += stride
    marker = by_kind[MARKERS]
    pad = -(marker.offset + 8) % 16
    require(len(marker.payload) >= pad, 'truncated marker alignment')
    require((len(marker.payload) - pad) % 48 == 0, 'partial marker record')
    markers = tuple(marker.payload[p:p + 48] for p in range(pad, len(marker.payload), 48))
    raw = by_kind[BARRIERS].payload
    require(len(raw) % 24 == 0, 'partial barrier record')
    barriers = tuple(raw[p:p + 24] for p in range(0, len(raw), 24))
    return Tables(parts, children, tuple(zones), marker.payload[:pad], markers, barriers)


def check(items, *, track=2000):
    """Apply loader ranges and spatial checks to the serialized chunks.

    00799650 builds 18 count/first/end triples, not a serialized range table.
    A split type group includes other types in its first..end interval and is
    invalid even when all individual record strides happen to be correct.
    0079DA60 compares marker +8 and +36; zero +36 is the wildcard selector.
    """
    table = read(items)
    kinds = [z.kind for z in table.zones]
    require(all(0 <= k < BUCKETS for k in kinds), 'zone type outside 18 buckets')
    ranges, offset = [], 0
    starts = []
    for z in table.zones:
        starts.append(offset)
        offset += len(z.encode())
    for kind in range(BUCKETS):
        matches = [i for i, k in enumerate(kinds) if k == kind]
        if matches:
            first, last = matches[0], matches[-1]
            require(last - first + 1 == len(matches), 'broken zone first/last type range')
            ranges.append(dict(type=kind, count=len(matches), first=starts[first],
                               end=starts[last] + len(table.zones[last].encode())))
        else:
            ranges.append(dict(type=kind, count=0, first=None, end=None))
    require(kinds == sorted(kinds), 'zone types differ from native ascending order')
    components = 0
    for z in table.zones:
        values = (*struct.unpack_from('<2f', z.header, 4), *z.bounds,
                  *(v for xy in z.vertices for v in xy))
        require(all(math.isfinite(v) for v in values), 'nonfinite zone coordinate')
        lx, ly, hx, hy = z.bounds
        require(lx <= hx and ly <= hy, 'inverted zone bounds')
        require(all(lx <= x <= hx and ly <= y <= hy for x, y in z.vertices),
                'zone polygon outside stored bounds')
        components += len(values)
    for row in table.markers:
        require(u32(row, 36) in (0, track), 'marker retains a foreign track selector')
        require(all(math.isfinite(v) for v in struct.unpack_from('<3f', row, 16)),
                'nonfinite marker position')
    for row in table.barriers:
        require(all(math.isfinite(v) for v in struct.unpack_from('<4f', row)),
                'nonfinite barrier endpoint')
    return dict(zones=len(table.zones), markers=len(table.markers), barriers=len(table.barriers),
                ranges=ranges, spatial_components=components + 3 * len(table.markers)
                + 4 * len(table.barriers))


def move(raw, offsets, delta):
    # Skipping zero is necessary to retain negative zero and all original bits.
    if delta:
        for p in offsets:
            value = struct.unpack_from('<f', raw, p)[0] + delta
            require(math.isfinite(value) and abs(value) <= 3.4028234663852886e38,
                    'translated coordinate exceeds float32')
            struct.pack_into('<f', raw, p, value)


def rekey(raw, p, key_map):
    key = u32(raw, p)
    if key and key in key_map:
        struct.pack_into('<I', raw, p, key_map[key])


def convert(source_index, *, shift=(0.0, 0.0), track=2000, key_map=None):
    """Retain numeric type IDs 0..14 in the 18-bucket destination capacity.

    No enum permutation is evidenced by the loaders. Buckets 15..17 remain
    empty. Stable sorting preserves the ordering within each original group.
    Track selectors are IDs, not hashes; retarget every nonzero +36 word.
    """
    require(len(shift) == 2 and all(math.isfinite(v) for v in shift), 'invalid physics shift')
    require(isinstance(track, int) and 0 < track <= 32767, 'track must fit positive signed short')
    key_map = {} if key_map is None else dict(key_map)
    require(all(isinstance(k, int) and isinstance(v, int) and 0 <= k <= 0xffffffff
                and 0 <= v <= 0xffffffff for k, v in key_map.items()), 'key map must contain u32 pairs')
    source = read(select(source_index))
    require(all(z.kind < 15 for z in source.zones), 'source type outside 15 buckets')
    dx, dy = shift[1], -shift[0]
    polygons = []
    for zone in sorted(source.zones, key=lambda z: z.kind):
        raw = bytearray(zone.encode())
        move(raw, (4, 32, 40, *range(68, len(raw), 8)), dx)
        move(raw, (8, 36, 44, *range(72, len(raw), 8)), dy)
        if zone.kind in (9, 11):
            rekey(raw, 48, key_map)
        polygons.append(bytes(raw))
    markers = []
    for row in source.markers:
        raw = bytearray(row)
        move(raw, (16,), dx)
        move(raw, (20,), dy)
        rekey(raw, 8, key_map)
        if u32(raw, 36):
            struct.pack_into('<I', raw, 36, track)
        markers.append(bytes(raw))
    barriers = []
    for row in source.barriers:
        raw = bytearray(row)
        move(raw, (0, 8), dx)
        move(raw, (4, 12), dy)
        rekey(raw, 20, key_map)
        barriers.append(bytes(raw))
    children = [Chunk(c.kind, b''.join(polygons)) if c.kind == POLYGONS else c
                for c in source.children]
    result = (Chunk(ZONES, encode_chunks(children)),
              Chunk(MARKERS, bytes(8) + b''.join(markers)),
              Chunk(BARRIERS, b''.join(barriers)))
    check(result, track=track)
    return result


def rewrite_index(index_data, converted, *, track=2000):
    """Replace the two scaffold chunks, insert markers just after polygons.

    As in TrackIndex.encode, compensate each size delta with chunk padding to
    a multiple of 128 (padding envelopes require at least eight bytes). This
    also preserves absolute alignment of opaque later chunk interiors.
    """
    check(converted, track=track)
    replacements = {c.kind: c for c in converted}
    original = chunks(index_data)
    require(sum(c.kind == ZONES for c in original) == 1, 'expected one scaffold zone chunk')
    require(sum(c.kind == BARRIERS for c in original) == 1, 'expected one scaffold barrier chunk')
    require(not any(c.kind == MARKERS for c in original), 'scaffold already contains markers')
    output, position = [], 0

    def add(part):
        nonlocal position
        output.append(part)
        position += 8 + len(part.payload)

    def padding(size):
        if size:
            require(size >= 8, 'padding envelope too short')
            add(Chunk(0, bytes(size - 8)))

    for old in original:
        require(position % 128 == old.offset % 128, 'later chunk alignment changed')
        new = replacements.get(old.kind, old)
        add(new)
        delta = len(new.payload) - len(old.payload)
        if delta:
            pad = -delta % 128
            padding(pad + 128 if 0 < pad < 8 else pad)
        if old.kind == ZONES:
            # The marker did not exist in the scaffold; insert a whole 128-byte
            # multiple, including its own header and any leading alignment.
            begin = position
            pad = -position % 16
            padding(pad + 16 if 0 < pad < 8 else pad)
            require(position % 16 == 0, 'inserted marker header misaligned')
            add(replacements[MARKERS])
            pad = -(position - begin) % 128
            padding(pad + 128 if 0 < pad < 8 else pad)
    result = encode_chunks(output)
    check(select(TrackIndex(result)), track=track)
    return result


def districts(source_index, attributes):
    """A 4-aligned raw occurrence is only a lead for the separate binding job."""
    data = Path(attributes).read_bytes()
    keys = {key for (key,) in struct.iter_unpack('<I', data[:len(data) // 4 * 4])}
    return [dict(key=f'{z.key:08x}', vertices=len(z.vertices), bounds=z.bounds,
                 carbon_aligned_raw_occurrence=z.key in keys,
                 meaning='raw-search lead only; pattern binding unproved')
            for z in read(select(source_index)).zones if z.kind == 9]


def prepare(into, output, mw_root=DEFAULT_MW, carbon_root=DEFAULT_CARBON):
    """Write a new pair and run the separately owned whole-world CLI checker.

    Retain the reviewable output if that checker rejects the integration, and
    return its real exit code. Never label a rejected world as checked.
    """
    into, out = Path(into).resolve(), Path(output).resolve()
    require(into.is_dir(), 'input world directory absent')
    require(not out.exists(), 'output already exists')
    roots = (into, Path(mw_root).resolve().parent, Path(carbon_root).resolve().parent)
    require(all(not out.is_relative_to(p) and not p.is_relative_to(out) for p in roots),
            'output overlaps input assets')
    require(not any((p / '.git').exists() for p in (out, *out.parents)),
            'output must be outside every checkout')
    source = TrackIndex((Path(mw_root) / 'L2RA.BUN').read_bytes())
    baseline = (into / 'TRACKS/L2RA.BUN').read_bytes()
    written = rewrite_index(baseline, convert(source))
    out.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.zones-', dir=out.parent))
    try:
        shutil.copytree(into, stage, dirs_exist_ok=True)
        (stage / 'TRACKS/L2RA.BUN').write_bytes(written)
        # Existing proof.json describes the input pair; remove stale evidence.
        (stage / 'proof.json').unlink(missing_ok=True)
        measured = check(select(TrackIndex((stage / 'TRACKS/L2RA.BUN').read_bytes())))
        command = [sys.executable, '-I', str(HERE / 'rockport_world.py'), '--check', str(stage),
                   '--mw-root', str(mw_root), '--carbon-root', str(carbon_root)]
        checked = subprocess.run(command, capture_output=True, text=True, check=False)
        report = dict(counts={k: measured[k] for k in ('zones', 'markers', 'barriers')},
                      index_bytes=len(written), index_sha256=hashlib.sha256(written).hexdigest(),
                      world_check=dict(returncode=checked.returncode,
                                       stdout=checked.stdout.strip(), stderr=checked.stderr.strip()))
        (stage / 'zones-proof.json').write_text(json.dumps(report, indent=2) + '\n')
        os.rename(stage, out)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--into', type=Path)
    parser.add_argument('--out', type=Path)
    parser.add_argument('--districts', action='store_true')
    parser.add_argument('--mw-root', type=Path, default=DEFAULT_MW)
    parser.add_argument('--carbon-root', type=Path, default=DEFAULT_CARBON)
    args = parser.parse_args(argv)
    try:
        require(bool(args.into) == bool(args.out), '--into and --out must be supplied together')
        require(args.into or args.districts, 'supply --into/--out or --districts')
        required = [args.mw_root / 'L2RA.BUN']
        if args.districts:
            required.append(args.carbon_root.parent / 'GLOBAL/attributes.bin')
        if args.into:
            required.extend((args.into / 'TRACKS/L2RA.BUN', args.into / 'TRACKS/STREAML2RA.BUN'))
            required.extend(args.carbon_root / name for name in ('L5RB.BUN', 'STREAML5RB.BUN'))
            required.append(args.mw_root / 'STREAML2RA.BUN')
        for path in required:
            if not path.is_file():
                raise FileNotFoundError(2, 'private asset absent', str(path))
        if args.districts:
            source = TrackIndex((args.mw_root / 'L2RA.BUN').read_bytes())
            rows = districts(source, args.carbon_root.parent / 'GLOBAL/attributes.bin')
            print(json.dumps(dict(districts=rows, occurrences=sum(
                r['carbon_aligned_raw_occurrence'] for r in rows)), sort_keys=True))
        if args.into:
            report = prepare(args.into, args.out, args.mw_root, args.carbon_root)
            print(json.dumps(dict(output=str(args.out), **report), sort_keys=True))
            return 0 if report['world_check']['returncode'] == 0 else 1
    except FileNotFoundError as exc:
        print(f'SKIP: private assets absent: {exc.filename}', file=sys.stderr)
        return 3
    except (OSError, ValueError, struct.error) as exc:
        print(f'FAIL: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
