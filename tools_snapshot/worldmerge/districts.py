"""Bind source district names to traffic patterns read from the destination vault."""
import argparse
import json
from pathlib import Path
import struct
import sys

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(HERE))
from formats import require, u32
from merge import DEFAULT_MW, DEFAULT_CARBON, load_index
import zones

ROCKPORT_TO_CARBON = {
    'downtown': 'muscle',
    'cityhighway': 'highway',
    'collegehighway': 'highway',
    'collegesouth': 'tuner',
    'collegenorth': 'exotic',
    'coastalnorth': 'santafe',
    'coastalsouth': 'santafe',
}


def bstring_hash(name):
    value = 0xffffffff
    for byte in name.encode('ascii'):
        value = (value * 33 + byte) & 0xffffffff
    return value


def traffic_patterns(carbon_root=DEFAULT_CARBON):
    """Read class 20D08342 CollectionName at layout +0, using pointer fixups.

    Carbon exports are 16 bytes; collection exports have type 8E112EB7.
    CollectionLoadData +28 points to the layout, whose first word points to
    the name text. Neither collection keys nor raw string searches are names.
    """
    raw = (Path(carbon_root).parent / 'GLOBAL/attributes.bin').read_bytes()

    def span(data, offset, size):
        require(0 <= offset <= len(data) and 0 <= size <= len(data) - offset,
                'attributes span outside buffer')
        return data[offset:offset + size]

    def text(data, offset):
        span(data, offset, 1)
        end = data.find(b'\0', offset)
        require(end >= offset, 'unterminated attributes string')
        return data[offset:end].decode('ascii')

    require(span(raw, 0, 4) == b'VPAK', 'attributes is not VPAK')
    count, names_offset, names_size = struct.unpack('<III', span(raw, 4, 12))
    names = span(raw, names_offset, names_size)
    directory = span(raw, 16, count * 20)
    databases = []
    for name, bin_size, vault_size, bin_offset, vault_offset in struct.iter_unpack('<5I', directory):
        if text(names, name) == 'db':
            databases.append((span(raw, vault_offset, vault_size), span(raw, bin_offset, bin_size)))
    require(len(databases) == 1, 'expected one db vault')
    buffers = databases[0]  # dependency 0: vlt, dependency 1: bin
    vault = buffers[0]
    chunks, offset = {}, 0
    while offset < len(vault):
        kind, size = struct.unpack('<4sI', span(vault, offset, 8))
        require(size >= 8 and kind not in chunks, 'invalid attributes chunk')
        chunks[kind] = (offset, span(vault, offset, size))
        offset += size
    require(b'NrtP' in chunks and b'NpxE' in chunks, 'missing attributes fixups/exports')
    fixups, base = {}, 0
    pointers = chunks[b'NrtP'][1]
    terminated = False
    for offset in range(8, len(pointers) - 11, 12):
        field, kind, dependency, value = struct.unpack_from('<IHHI', pointers, offset)
        if kind == 0:
            terminated = True
            break
        if kind == 2:
            base = dependency
        elif kind == 3:
            require((base, field) not in fixups, 'duplicate attributes pointer')
            fixups[base, field] = dependency, value
    require(terminated, 'unterminated attributes fixups')

    def dereference(dependency, offset):
        require((dependency, offset) in fixups, 'missing CollectionName pointer')
        target, position = fixups[dependency, offset]
        require(target in (0, 1), 'external CollectionName pointer')
        span(buffers[target], position, 4)
        return target, position

    exports = chunks[b'NpxE'][1]
    count = u32(exports, 8)
    entries = span(exports, 12, count * 16)
    result = {}
    for _key, kind, size, offset in struct.iter_unpack('<4I', entries):
        if kind != 0x8e112eb7:
            continue
        collection = span(vault, offset, size)
        require(len(collection) >= 32, 'truncated collection')
        if u32(collection, 4) != 0x20d08342:
            continue
        dependency, layout = dereference(0, offset + 28)
        dependency, position = dereference(dependency, layout)
        name = text(buffers[dependency], position)
        require(bool(name), 'empty traffic pattern name')
        hashed = bstring_hash(name)
        require(hashed not in result, 'duplicate traffic pattern name/hash')
        result[hashed] = name
    require(bool(result), 'trafficpattern class has no collections')
    return result


def key_map(source_index, carbon_root=DEFAULT_CARBON):
    patterns = traffic_patterns(carbon_root)
    mapping = {}
    for source, target in ROCKPORT_TO_CARBON.items():
        hashed = bstring_hash(target)
        require(patterns.get(hashed) == target, f'target traffic pattern absent: {target}')
        mapping[bstring_hash(source)] = hashed
    tables = zones.read(zones.select(source_index))
    for zone in tables.zones:
        if zone.kind == 9:
            require(zone.key in mapping, f'unmapped type-9 district key: {zone.key:08X}')
        elif zone.kind == 11:
            require(zone.key not in mapping, 'district key occurs outside type-9: type-11')
    require(not any(u32(row, 8) in mapping for row in tables.markers),
            'district key occurs outside type-9: marker')
    require(not any(u32(row, 20) in mapping for row in tables.barriers),
            'district key occurs outside type-9: barrier')
    return mapping


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--list', action='store_true', required=True)
    parser.add_argument('--mw-root', type=Path, default=DEFAULT_MW)
    parser.add_argument('--carbon-root', type=Path, default=DEFAULT_CARBON)
    args = parser.parse_args(argv)
    try:
        source, _, _ = load_index(args.mw_root, 'L2RA')
        mapping = key_map(source, args.carbon_root)
        print(json.dumps([dict(source=name, target=target, source_key=f'{bstring_hash(name):08X}',
                               target_key=f'{mapping[bstring_hash(name)]:08X}')
                          for name, target in ROCKPORT_TO_CARBON.items()], sort_keys=True))
    except FileNotFoundError as exc:
        print(f'SKIP: private assets absent: {exc}', file=sys.stderr)
        return 3
    except (OSError, ValueError, KeyError, struct.error) as exc:
        print(f'FAIL: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
