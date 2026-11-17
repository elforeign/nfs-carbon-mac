"""Clone native world-map images into a paired frontend overlay.

SAFEHOUSEINDICATOR_4..7 serve the imported houses, 8..15 the shops,
in stable premises-key order above the original maximum BFC67884.
The gameplay converter supplies that ordering; this pack supplies the slots.
Shops reuse resource 15. No texture, ownership or map-append hook is added.
"""
import argparse
from pathlib import Path
import struct
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from formats import Chunk, chunks, encode_chunks, require, u32
from merge import DEFAULT_CARBON
from minimap import jdlz_encode, native_jdlz_extent, xt

SAFEHOUSES = tuple(f'SAFEHOUSEINDICATOR_{i}' for i in range(4, 16))
CARLOTS = tuple(f'CAR_LOT_{i}' for i in range(5, 8))
NAMES = SAFEHOUSES + CARLOTS


def name_hash(name):
    value = 0xffffffff
    for byte in name.encode('ascii'):
        value = (value * 33 + byte) & 0xffffffff
    return value


def records(raw, start=0, end=None):
    """FNG uses four-byte tags with payload lengths, including container tags."""
    end = len(raw) if end is None else end
    require(0 <= start <= end <= len(raw), 'FNG container bounds')
    result = []
    while start < end:
        require(start + 8 <= end, 'truncated FNG record')
        size = u32(raw, start + 4)
        require(size <= end - start - 8, 'FNG record crosses container')
        result.append((raw[start:start+4], start, start+8+size))
        start += 8 + size
    return result


def one(rows, tag):
    selected = [row for row in rows if row[0] == tag]
    require(len(selected) == 1, f'expected one {tag!r}')
    return selected[0][1:]


def objects(raw):
    root, end = one(records(raw), b'FEn\xe7')
    start, stop = one(records(raw, root+8, end), b'Obj\xcc')
    rows = records(raw, start+8, stop)
    require(rows[0][0] == b'Butn', 'missing object-list header')
    require(all(tag == b'FOb\xea' for tag, _, _ in rows[1:]), 'unexpected object record')
    return start, stop, [raw[a:b] for _, a, b in rows[1:]]


def clone_screen(raw):
    start, stop, originals = objects(raw)
    require(len(raw) == 174464 and len(originals) == 576, 'expected retail world map')
    ids = {u32(row, 0x24) for row in originals}
    hashes = {u32(row, 0x1c) for row in originals}
    require(len(ids) == len(originals), 'duplicate native object ID')
    require(not hashes.intersection(map(name_hash, NAMES)), 'new image name already present')
    additions = []
    for names, sibling, resource in ((SAFEHOUSES, 'SAFEHOUSEINDICATOR_0', 15),
                                      (CARLOTS, 'CAR_LOT_1', 16)):
        matches = [row for row in originals if u32(row, 0x1c) == name_hash(sibling)]
        require(len(matches) == 1, 'missing native sibling')
        template = matches[0]
        require(len(template) == 184 and template[8:12] == b'ObjD' and
                u32(template, 12) == 0x8c and u32(template, 0x14) == 1 and
                u32(template, 0x30) == resource and template[0x9c:0xa0] == b'Scrp',
                'native image layout changed')
        for name in names:
            row = bytearray(template)
            uid = max(ids) + 1
            require(uid <= 0xffffffff, 'object ID overflow')
            ids.add(uid)
            for offset, value in ((0x1c, name_hash(name)), (0x24, uid), (0x28, name_hash(name))):
                struct.pack_into('<I', row, offset, value)
            additions.append(bytes(row))
    added = b''.join(additions)
    result = bytearray(raw[:stop] + added + raw[stop:])
    struct.pack_into('<I', result, start+4, stop-start-8+len(added))
    struct.pack_into('<I', result, 4, len(result)-8)
    require(len(objects(result)[2]) == 591, 'clone count')
    return bytes(result)


def worldmap(pack):
    matches = []
    for index, part in enumerate(chunks(pack)):
        if part.kind != 0x30210 or part.payload[4:8] != b'JDLZ':
            continue
        raw = xt.jdlz(part.payload, 4)
        if raw[0x28:0x39] == b'WorldMapMain.fng\0':
            matches.append((index, raw))
    require(len(matches) == 1, 'expected one WorldMapMain.fng')
    return matches[0]


def convert(binary, companion):
    require(xt.jdlz(companion) == binary, 'frontend pair differs')
    parts = chunks(binary)
    index, raw = worldmap(binary)
    encoded = jdlz_encode(clone_screen(raw))
    native_jdlz_extent(encoded)
    old = parts[index]
    payload = old.payload[:4] + encoded
    # Preserve every following native chunk's alignment modulo 128. Padding
    # stays outside the JDLZ extent, as in the original compressed chunks.
    payload += bytes((len(old.payload)-len(payload)) % 128)
    parts[index] = Chunk(old.kind, payload)
    result = encode_chunks(parts)
    startup = jdlz_encode(result)
    native_jdlz_extent(startup)
    require(xt.jdlz(startup) == result, 'frontend companion round trip')
    return result, startup


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--carbon', type=Path, default=DEFAULT_CARBON.parent/'GLOBAL')
    parser.add_argument('--out', type=Path, required=True, help='overlay GLOBAL directory')
    args = parser.parse_args()
    require(args.out.resolve() != args.carbon.resolve(), 'output must differ from retail directory')
    binary, companion = convert((args.carbon/'GLOBALB.BUN').read_bytes(),
                                (args.carbon/'GlobalB.lzc').read_bytes())
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out/'GLOBALB.BUN').write_bytes(binary)
    (args.out/'GLOBALB.LZC').write_bytes(companion)
    print(f'WorldMapMain.fng: 576 -> 591 objects; 174464 -> 177224 bytes; resources=58')
    for name, row in zip(NAMES, objects(worldmap(binary)[1])[2][-15:]):
        print(f'{name} ID={u32(row, 0x24):08X}')


if __name__ == '__main__':
    main()
