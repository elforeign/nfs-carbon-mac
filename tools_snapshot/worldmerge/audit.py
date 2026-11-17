"""Read-only structural comparison of retail archives and an untrusted oracle.

Reports contain structures and numbers. No oracle payload reaches the writer.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import re
import struct
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from formats import chunks, require, u32
from merge import DEFAULT_MW, DEFAULT_CARBON, PARENT, load_index, read_section

DEFAULT_ORACLE = PARENT / 'ext_untrusted' / 'carbon_rockport_mod' / 'extract' / 'Rockport v1.0' / 'Tracks'


def aligned_payload(item):
    pad = -(item.offset + 8) % 16
    require(pad <= len(item.payload), 'audit alignment outside payload')
    require(all(v in (0, 0x11) for v in item.payload[:pad]), 'audit alignment filler')
    return item.payload[pad:]


def decode_grid(index):
    top = next(c for c in index.parts if c.kind == 0x3b800)
    raw = top.payload
    magic = struct.pack('<I', 0x43477264)
    p = raw.find(magic)
    require(0 <= p <= len(raw) - 16, 'grid tag absent or truncated')
    _, flags, count, value = struct.unpack_from('<4I', raw, p)
    require(flags & 2 and count == 1, 'unsupported grid tag addressing/count')
    q = p + value
    require(0 <= q <= len(raw) - 32, 'grid descriptor outside world chunk')
    origin = struct.unpack_from('<3f', raw, q)
    cell = struct.unpack_from('<f', raw, q + 16)[0]
    rows, columns = struct.unpack_from('<II', raw, q + 24)
    require(0 < rows <= 4096 and 0 < columns <= 4096 and 0 < cell < 10000, 'invalid grid dimensions')
    return {'origin_physics_xyz': origin, 'cell_m': cell, 'rows': rows, 'columns': columns,
            'descriptor_bytes': flags >> 8, 'world_chunk_bytes': len(raw)}


def inventory(index, stream, bridge_candidates=False):
    result = {k: Counter() for k in ('top_chunks', 'list_versions', 'solid_versions', 'tpk_versions',
                                    'material_effects', 'instance_strides')}
    totals = Counter()
    bridges = {}
    extended_layout = decode_grid(index)['descriptor_bytes'] == 40
    for section in index.sections:
        raw = read_section(stream, section)
        for root in chunks(raw):
            if root.kind == 0:
                continue
            result['top_chunks'][f'{root.kind:08x}'] += 1
            if root.kind == 0x80134000:
                lp = chunks(root.payload, root.offset + 8)
                for header in (c for c in lp if c.kind == 0x80134001):
                    hp = chunks(header.payload, header.offset + 8)
                    info = next(c for c in hp if c.kind == 0x134002)
                    require(len(info.payload) >= 16, 'solid-list info truncated')
                    result['list_versions'][u32(info.payload, 8)] += 1
                for solid in (c for c in lp if c.kind == 0x80134010):
                    sp = chunks(solid.payload, solid.offset + 8)
                    sh = aligned_payload(next(c for c in sp if c.kind == 0x134011))
                    require(len(sh) >= 160, 'solid header truncated')
                    result['solid_versions'][u32(sh, 12) & 0xffff] += 1
                    mesh = next((c for c in sp if c.kind == 0x80134100), None)
                    if mesh:
                        mp = chunks(mesh.payload, mesh.offset + 8)
                        mh = aligned_payload(next(c for c in mp if c.kind == 0x134900))
                        rb = aligned_payload(next(c for c in mp if c.kind == 0x134b02))
                        stride = 104 if len(mh) == 48 else 144
                        require(len(mh) in (48, 52) and len(rb) % stride == 0, 'mesh array layout')
                        for p in range(0, len(rb), stride):
                            result['material_effects'][u32(rb, p + 48)] += 1
            elif root.kind == 0xb3300000:
                tp = chunks(root.payload, root.offset + 8)
                header = next(c for c in tp if c.kind == 0xb3310000)
                info = next(c for c in chunks(header.payload, header.offset + 8) if c.kind == 0x33310001)
                result['tpk_versions'][u32(info.payload)] += 1
            elif root.kind == 0x80034100:
                sp = chunks(root.payload, root.offset + 8)
                h = aligned_payload(next(c for c in sp if c.kind == 0x34101))
                extended = len(h) == 68
                require(len(h) in (60, 68), 'scenery header layout')
                width = 96 if extended else 64
                instances = next((aligned_payload(c) for c in sp if c.kind == 0x34103), b'')
                require(len(instances) % width == 0, 'instance array range')
                result['instance_strides'][width] += len(instances) // width
                if bridge_candidates and not extended:
                    infos = next((c.payload for c in sp if c.kind == 0x34102), b'')
                    require(len(infos) % 72 == 0, 'source model-table range')
                    for p in range(0, len(instances), 64):
                        r = instances[p:p + 64]
                        model = struct.unpack_from('<h', r, 62)[0]
                        require(0 <= model < len(infos) // 72, 'source bridge model index')
                        name = infos[model * 72:model * 72 + 24].split(b'\0')[0].decode('ascii', errors='replace')
                        if re.search('bridge|jump|endgame|final|escape', name, re.I):
                            lo, hi = struct.unpack_from('<3f', r, 0), struct.unpack_from('<3f', r, 12)
                            center = tuple((a + b) / 2 for a, b in zip(lo, hi))
                            key = (name, tuple(round(v, 1) for v in center))
                            row = bridges.setdefault(key, {'name': name, 'render_center_xyz': center,
                                                           'render_bounds': [lo, hi], 'sections': [],
                                                           'scenery_section_numbers': []})
                            row['sections'].append(section.name)
                            if u32(h, 12) not in row['scenery_section_numbers']:
                                row['scenery_section_numbers'].append(u32(h, 12))
            elif root.kind == 0x34027:
                data = aligned_payload(root)
                require(len(data) >= 16, 'pursuit-breaker header truncated')
                count = struct.unpack_from('<H', data, 10 if extended_layout else 12)[0]
                require(16 + count * 64 == len(data), 'pursuit-breaker record count/size')
                totals['pursuit_breaker_records'] += count
                totals['pursuit_headers_section_zero'] += struct.unpack_from('<H', data, 8)[0] == 0
                key_offset = 28 if extended_layout else 32
                for p in range(16, len(data), 64):
                    for q in (key_offset, key_offset + 4):
                        totals['pursuit_small_reference_words'] += u32(data, p + q) < 256
        totals['sections_read'] += 1
        totals['section_bytes_read'] += len(raw)
    output = {k: dict(sorted(v.items())) for k, v in result.items()}
    output.update(totals)
    if bridge_candidates:
        output['bridge_candidates'] = list(bridges.values())
    return output


def compare(mw=DEFAULT_MW, carbon=DEFAULT_CARBON, oracle=DEFAULT_ORACLE):
    inputs = {'source': (mw, 'L2RA'), 'target': (carbon, 'L5RA'), 'oracle': (oracle, 'L5RA')}
    indices, reports = {}, {}
    for name, (root, base) in inputs.items():
        index, stream, raw = load_index(root, base)
        indices[name] = index
        reports[name] = {'index_bytes': len(raw), 'stream_bytes': stream.stat().st_size,
                         'section_records': len(index.sections), 'roundtrip_exact': index.encode() == raw,
                         'index_chunks': dict(Counter(f'{c.kind:08x}' for c in index.parts if c.kind)),
                         'grid': decode_grid(index), 'inventory': inventory(index, stream, name == 'source')}
    source = {s.number: s for s in indices['source'].sections}
    converted = {s.number: s for s in indices['oracle'].sections}
    common = source.keys() & converted.keys()
    require(common, 'oracle shares no section numbers with source')
    reports['comparison'] = {
        'same_section_number_sets': source.keys() == converted.keys(),
        'same_streamer_positions': sum(source[n].position == converted[n].position for n in common),
        'compared_records': len(common),
        'max_streamer_coordinate_delta': max(abs(a - b) for n in common for a, b in zip(source[n].position, converted[n].position)),
        'same_override_chunk': next(c.payload for c in indices['source'].parts if c.kind == 0x34108) ==
                               next(c.payload for c in indices['oracle'].parts if c.kind == 0x34108),
        'oracle_used_for_generation': False,
    }
    candidates = reports['source']['inventory']['bridge_candidates']
    reports['old_bridge'] = {
        'status': 'geometry decoded; finale escape trigger not decoded yet',
        'geometry': [r for r in candidates if r['name'].startswith('XO_OldBridgeBase')],
        'nearby_final_road_models': sum('Road_Final' in r['name'] for r in candidates),
    }
    return reports


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mw', type=Path, default=DEFAULT_MW)
    parser.add_argument('--carbon', type=Path, default=DEFAULT_CARBON)
    parser.add_argument('--oracle', type=Path, default=DEFAULT_ORACLE)
    args = parser.parse_args()
    print(json.dumps(compare(args.mw, args.carbon, args.oracle), indent=2))


if __name__ == '__main__':
    main()
