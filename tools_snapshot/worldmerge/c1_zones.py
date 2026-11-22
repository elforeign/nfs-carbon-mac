"""Merge global tables while preserving native bucket and list prefixes.

The independent reader checks original record bytes with only decoded spatial,
track-selector, boundary-identity and traffic pattern fields changed.
"""
from collections import Counter
from dataclasses import replace
from pathlib import Path
import struct
import sys

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(HERE))
import districts
import zones
from formats import require, u32


def merge_districts(carbon_index, source_index, shift, carbon_root):
    """Add Rockport traffic polygons to Carbon's existing type-9 bucket."""
    native = zones.read(zones.select(carbon_index))
    keys = districts.key_map(source_index, carbon_root)
    moved = zones.read(zones.convert(source_index, shift=shift, key_map=keys))
    added = (zone for zone in moved.zones if zone.kind == 9)
    merged = tuple(sorted((*native.zones, *added), key=lambda zone: zone.kind))
    return next(c for c in replace(native, zones=merged).encode() if c.kind == zones.ZONES)


def reread_districts(chunks, carbon_index, source_index, shift, carbon_root):
    """Prove the final coast archive against both sources and Carbon's vault."""
    measured = zones.check(chunks)
    actual = zones.read(chunks)
    native = zones.read(zones.select(carbon_index))
    source = zones.read(zones.select(source_index))
    require(tuple(c.kind for c in actual.parts) == tuple(c.kind for c in native.parts),
            'native global chunk order changed')
    require([(c.kind, None if c.kind == zones.POLYGONS else c.payload) for c in actual.children] ==
            [(c.kind, None if c.kind == zones.POLYGONS else c.payload) for c in native.children],
            'native polygon container children changed')
    require(actual.markers == native.markers and actual.marker_padding == native.marker_padding,
            'native markers changed')
    require(actual.barriers == native.barriers, 'native barriers changed')
    originals = [zone for zone in source.zones if zone.kind == 9]
    start = sum(zone.kind <= 9 for zone in native.zones)
    end = start + len(originals)
    appended = actual.zones[start:end]
    require(actual.zones[:start] + actual.zones[end:] == native.zones and
            len(appended) == len(originals) and all(zone.kind == 9 for zone in appended),
            'expected only a complete Rockport type-9 suffix in the native zone table')
    patterns = districts.traffic_patterns(carbon_root)
    resolved = sum(zone.key in patterns for zone in appended)
    require(resolved == len(originals), f'Rockport traffic patterns resolve {resolved}/{len(originals)}')
    targets = {districts.bstring_hash(name): target for name, target in districts.ROCKPORT_TO_CARBON.items()}
    for original, written in zip(originals, appended):
        require(patterns[written.key] == targets.get(original.key), 'wrong Rockport traffic pattern')
        expected = bytearray(original.encode())
        struct.pack_into('<I', expected, 48, written.key)
        for first in (4, 32, 40, *range(68, len(expected), 8)):
            for offset, delta in ((first, shift[1]), (first + 4, -shift[0])):
                if delta:
                    coordinate = struct.unpack_from('<f', expected, offset)[0]
                    struct.pack_into('<f', expected, offset, coordinate + delta)
        require(written.encode() == expected, 'Rockport district translation/source bytes differ')
    return dict(**measured, mode='districts', rockport_districts=len(originals),
                resolved_rockport_districts=resolved)


def merge(carbon_index, source_index, mapping):
    """Return three replacement chunks at the native chunks' residues.

    00799650 needs contiguous type buckets. 0079D890 appends markers in file
    order; native (key, ordinal) lookups therefore require a native prefix.
    Type-6 +48..63 are boundary identities consumed by 007A44B0, not hashes.
    """
    native = zones.read(zones.select(carbon_index))
    moved = zones.read(zones.convert(source_index, shift=(20480., 0.), track=2000))
    identities = {int(k): v for k, v in mapping.items()}
    added = []
    for zone in moved.zones:
        if zone.kind == 6:
            header = bytearray(zone.header)
            for p in range(48, 64, 4):
                old = u32(header, p)
                if old:
                    require(old in identities, f'unmapped type-6 boundary identity {old}')
                    new = identities[old]
                    require(isinstance(new, int) and 0 < new <= 0xffffffff,
                            'mapped type-6 identity must be a nonzero u32')
                    struct.pack_into('<I', header, p, new)
            zone = replace(zone, header=bytes(header))
        added.append(zone)
    result = replace(native,
                     zones=tuple(sorted((*native.zones, *added), key=lambda z: z.kind)),
                     markers=native.markers + moved.markers,
                     barriers=native.barriers + moved.barriers).encode()
    zones.check(result)
    return result


def _shared(native, source, offset):
    left = Counter(u32(row, offset) for row in native)
    right = Counter(u32(row, offset) for row in source)
    return [dict(key=f'{key:08x}', carbon=left[key], rockport=right[key])
            for key in sorted(left.keys() & right.keys())]


def reread(chunks, carbon_index, source_index, mapping):
    """Prove a complete merge from original bytes, independently of its writer.

    Never calls merge, zones.convert/move/rekey or an allocation plan. Exact
    float32 forward rounding is checked instead of subtracting the translation.
    Coalesced source identities may repeat within Rockport, never across cities.
    """
    chunks = tuple(chunks)
    measured = zones.check(chunks)
    actual = zones.read(chunks)
    native = zones.read(zones.select(carbon_index))
    source = zones.read(zones.select(source_index))
    require(len(actual.zones) == len(native.zones) + len(source.zones),
            'incomplete merged zone count')
    require([c.kind for c in actual.parts] == [c.kind for c in native.parts],
            'global chunk order differs')
    require([(c.kind, None if c.kind == zones.POLYGONS else c.payload) for c in actual.children] ==
            [(c.kind, None if c.kind == zones.POLYGONS else c.payload) for c in native.children],
            'native polygon container children changed')
    require(actual.marker_padding == native.marker_padding,
            'native marker alignment bytes changed')
    identities = {int(k): v for k, v in mapping.items()}
    words = changed = 0
    native_ids, source_ids = set(), set()
    for kind in range(zones.BUCKETS):
        before = [z for z in native.zones if z.kind == kind]
        incoming = [z for z in source.zones if z.kind == kind]
        written = [z for z in actual.zones if z.kind == kind]
        require(len(written) == len(before) + len(incoming),
                f'bucket {kind}: incomplete merged zone count')
        require([z.encode() for z in written[:len(before)]] == [z.encode() for z in before],
                f'bucket {kind}: native zone prefix changed')
        if kind == 6:
            native_ids.update(u32(z.header, p) for z in before for p in range(48, 64, 4)
                              if u32(z.header, p))
        for original, appended in zip(incoming, written[len(before):]):
            expected = bytearray(original.encode())
            # Physics (X+20480,Z) becomes serialized (Z,-X-20480).
            # The other component is zero: preserve its exact bits, even -0.
            for p in (8, 36, 44, *range(72, len(expected), 8)):
                value = struct.unpack_from('<f', original.encode(), p)[0]
                expected[p:p+4] = struct.pack('<f', value - 20480.)
            if kind == 6:
                for p in range(48, 64, 4):
                    old = u32(original.header, p)
                    if old:
                        require(old in identities, f'unmapped source type-6 boundary identity {old}')
                        new = identities[old]
                        require(isinstance(new, int) and 0 < new <= 0xffffffff,
                                'mapped source type-6 identity must be a nonzero u32')
                        struct.pack_into('<I', expected, p, new)
                        source_ids.add(new)
                        words += 1
                        changed += old != new
            require(appended.encode() == expected,
                    f'bucket {kind}: Rockport zone translation/identity/source bytes differ')
    require(not native_ids & source_ids, 'cross-city duplicate type-6 boundary identities')
    require(len(actual.markers) == len(native.markers) + len(source.markers),
            'incomplete merged marker count')
    require(actual.markers[:len(native.markers)] == native.markers,
            'native marker prefix/order changed')
    for original, appended in zip(source.markers, actual.markers[len(native.markers):]):
        expected = bytearray(original)
        expected[20:24] = struct.pack('<f', struct.unpack_from('<f', original, 20)[0] - 20480.)
        if u32(original, 36):
            struct.pack_into('<I', expected, 36, 2000)
        require(appended == expected, 'Rockport marker translation/selector/source bytes differ')
    require(len(actual.barriers) == len(native.barriers) + len(source.barriers),
            'incomplete merged barrier count')
    require(actual.barriers[:len(native.barriers)] == native.barriers,
            'native barrier prefix/order changed')
    for original, appended in zip(source.barriers, actual.barriers[len(native.barriers):]):
        expected = bytearray(original)
        for p in (4, 12):
            expected[p:p+4] = struct.pack('<f', struct.unpack_from('<f', original, p)[0] - 20480.)
        require(appended == expected, 'Rockport barrier translation/source bytes differ')
    # Reproduce 0079DA60's key/selector filter and every native ordinal.
    tracks = {0, 2000, 5000} | {u32(row, 36) for row in native.markers}
    for track in tracks:
        for key in {u32(row, 8) for row in native.markers}:
            before = [row for row in native.markers if u32(row, 8) == key and u32(row, 36) in (0, track)]
            after = [row for row in actual.markers if u32(row, 8) == key and u32(row, 36) in (0, track)]
            require(after[:len(before)] == before, 'native marker key/ordinal lookup changed')
    return dict(**measured, mode='merged',
                polygon_bytes=dict(carbon=sum(len(z.encode()) for z in native.zones),
                                   rockport=sum(len(z.encode()) for z in source.zones)),
                source_type6_words=words, mapped_type6_words=words, changed_type6_words=changed,
                cross_city_type6_duplicates=len(native_ids & source_ids),
                native_marker_lookups_preserved=len(native.markers),
                marker_lookup_tracks=sorted(tracks),
                shared_marker_keys=_shared(native.markers, source.markers, 8),
                shared_barrier_groups=_shared(native.barriers, source.barriers, 20))
