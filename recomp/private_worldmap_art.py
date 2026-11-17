"""Append the retained map image to a private v8 streaming pack, in atlas mode.

The index grows into existing header padding; every original stored blob keeps
its offset and bytes. Source files are read only. Output belongs in an overlay.
"""
import argparse
import hashlib
import os
from pathlib import Path
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools_snapshot'))
import carbon_car as cc

TRACK_MAP = 0x0F365871
PIXEL_SHA256 = 'c138900c839070bc5fbd5c420fec92b62fb02f14acb89ac2d19d47f39224ce16'


def convert(mw, carbon, mode):
    if mode != 'atlas':
        return carbon
    rows = cc.index(carbon, 0x33310003)
    cc.require(len(rows) == 127 and TRACK_MAP not in {r[0] for r in rows}, 'expected original map index')
    source = next(cc.unpack_entry(mw, e) for e in cc.index(mw, 0x33310003) if e[0] == TRACK_MAP)
    pixels, r = source[:-156], source[-156:-24]
    cc.require(len(pixels) == 1024 * 1024 and hashlib.sha256(pixels).hexdigest() == PIXEL_SHA256,
               'map pixel fingerprint')
    v = bytearray(124)
    v[:12], v[12:20], v[20:48], v[48:88] = r[:12], r[36:44], r[48:76], r[76:116]
    v[88], v[89:124] = 35, b'TRACK_MAP\0'.ljust(35, b'\0')
    struct.pack_into('<I', v, 0x14, 0x00B35580)
    donor = next(cc.unpack_entry(carbon, e) for e in rows if e[0] == cc.name_hash('TRACK_MAP_UNLOCK_1'))
    v[51:60] = donor[-148:-24][51:60]
    platform = bytearray(24)
    platform[12:16] = b'DXT3'
    blob = pixels + v + platform
    cc.require(len(carbon) == 0x001FFE80 and len(blob) == 0x00100094, 'map pack placement')
    row = (TRACK_MAP, len(carbon), len(blob), len(blob), 0, 0)
    ho, hz = cc.find(carbon, 0xB3310000)
    parts = []
    for cid, off, size in cc.children(carbon, ho + 8, ho + 8 + hz):
        payload = carbon[off + 8:off + 8 + size]
        if cid == 0x33310002:
            hashes = list(struct.iter_unpack('<II', payload)) + [(TRACK_MAP, 0)]
            payload = b''.join(struct.pack('<II', *h) for h in sorted(hashes))
        elif cid == 0x33310003:
            payload = b''.join(struct.pack('<6I', *e) for e in sorted(rows + [row]))
        parts.append(cc.chunk(cid, payload))
    header = cc.chunk(0xB3310000, b''.join(parts))
    gap = ho + 8 + hz
    cc.require(cc.u32(carbon, gap) == 0 and cc.u32(carbon, gap + 4) == 60, 'header gap')
    out = bytearray(carbon[:ho] + header + cc.chunk(0, bytes(28)) + carbon[gap + 68:])
    cc.require(len(out) == len(carbon), 'original blob positions')
    # Only these enclosing sizes change; the data header and aligned pixels stay put.
    data, _ = cc.find(carbon, 0xB3320000)
    pixel, _ = cc.find(carbon, 0x33320002)
    for off in (0, data, pixel):
        struct.pack_into('<I', out, off + 4, cc.u32(carbon, off + 4) + len(blob))
    out += blob
    return bytes(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--mw', type=Path, required=True, help='source TrackMaps.bin')
    ap.add_argument('--carbon', type=Path, required=True, help='destination-format TrackMaps.bin')
    ap.add_argument('--out', type=Path, required=True, help='overlay TrackMaps.bin')
    args = ap.parse_args()
    if args.out.resolve() in (args.mw.resolve(), args.carbon.resolve()):
        ap.error('output must be separate from the sources')
    source = args.carbon.read_bytes()
    mode = os.environ.get('NFS_CARBON_MINIMAP')
    result = convert(args.mw.read_bytes() if mode == 'atlas' else b'', source, mode)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(result)
    print(f'worldmap pack: mode={mode or "off"} bytes={len(source)}->{len(result)}')


if __name__ == '__main__':
    main()
