"""Independent single-section writer. The community reference is never an input."""
from collections import Counter
from dataclasses import InitVar, dataclass, field
import math
import struct
import zlib

from formats import Chunk, FormatError, chunks, encode_chunks, render_shift, require, u32
from resources import convert_resources
import emitters
import sidecars
import tail
import refonly
import texanim


def aligned_payload(c, alignment=16):
    pad = -(c.offset + 8) % alignment
    require(pad <= len(c.payload), 'alignment exceeds payload')
    require(all(v == 0x11 for v in c.payload[:pad]), 'invalid alignment filler')
    return c.payload[pad:]


class Builder:
    def __init__(self, base):
        self.base = base
        self.data = bytearray()

    @property
    def position(self):
        return self.base + len(self.data)

    def add(self, kind, payload, alignment=1):
        pad = -(self.position + 8) % alignment
        self.data += Chunk(kind, b'\x11' * pad + bytes(payload)).encode()

    def pad(self, alignment):
        count = -self.position % alignment
        if count:
            if count < 8:
                count += alignment
            self.add(0, bytes(count - 8))


# Classified declarations: diffuse is unchanged; normal-map loses the unused
# second UV pair. No-fog has no later equivalent
# and uses the ordinary diffuse declaration (appearance remains unverified).
# Reflect uses the same source declaration as normal-map: UV1 is absent from
# the later reflect declaration, while tangent XYZW remains after primary UV.
# GlossyWindow -> GLASS_REFLECT: diffuse plus environment reflection; the
# declaration moves UV0 before colour and normal (position/UV0/colour/normal).
# The loader indexes the effect with the low ushort at +30, but groups buffers
# by the full word. The high ushort retains the source lighting contract.
FACADE_EFFECT = (5 << 16) | 25
# WORLDREFLECT uses diffuse/normal/specular indices at +18/+19/+1B.
# Keep those bytes and distinguish its lighting contract from native effect 1.
REFLECT_EFFECT = (1 << 16) | 1
# Tree foliage loads as native effect 0; the tag keeps its source tree
# lighting contract (wrapped, doubled sun) for the day-weighted draw.
TREE_EFFECT = 6 << 16
EFFECTS = {0: (36, 0, 36), 1: (60, REFLECT_EFFECT, 52), 3: (60, 3, 52), 5: (36, FACADE_EFFECT, 36), 6: (36, TREE_EFFECT, 36), **tail.EFFECTS}
TARGET_STRIDES = {0: 36, 1: 52, REFLECT_EFFECT: 52, 3: 52, 6: 24, 25: 36, FACADE_EFFECT: 36, TREE_EFFECT: 36, **tail.TARGET_STRIDES}

# Shared dome key, different geometry: 141 source vertices versus 166 native.
SOLID_KEYS = {0xed85ba82: zlib.crc32('rockport-solid:ed85ba82'.encode())}


def solid_models(raw):
    out = bytearray(raw)
    for p in range(0, len(raw), 72):
        for off in (24, 28, 32, 36):
            key = u32(raw, p + off)
            struct.pack_into('<I', out, p + off, SOLID_KEYS.get(key, key))
    return bytes(out)


@dataclass
class Stats:
    # Pack identity is writer context, not a reported conversion counter.
    __slots__ = ('_pack_section', '__dict__')
    solids: int = 0
    draws: int = 0
    vertices: int = 0
    triangles: int = 0
    textures: int = 0
    instances: int = 0
    nodes: int = 0
    effects: Counter = field(default_factory=Counter)
    omitted: Counter = field(default_factory=Counter)
    pack_section: InitVar[int] = 0

    def __post_init__(self, pack_section):
        self._pack_section = pack_section


def convert_vertices(raw, effect, count):
    require(effect in EFFECTS, f'undecoded source effect {effect}')
    if effect == 19:
        return tail.convert_vertices(raw, effect, count)
    stride, _, _ = EFFECTS[effect]
    require(len(raw) == stride * count, 'source vertex count/stride mismatch')
    out = bytearray()
    for p in range(0, len(raw), stride):
        v = raw[p:p + stride]
        require(all(math.isfinite(x) for x in struct.unpack_from('<6f', v)), 'non-finite vertex')
        if effect in (1, 3):
            out += v[:36] + v[44:60]
        elif effect == 5:
            out += v[:12] + v[28:36] + v[24:28] + v[12:24]
        else:
            out += v
    return bytes(out)


def convert_mesh(c, position, stats):
    parts = chunks(c.payload, c.offset + 8)
    kinds = Counter(p.kind for p in parts)
    require(set(kinds) <= {0x134900, 0x134b02, 0x134b03, 0x134b01, 0x134c02},
            'undecoded mesh child')
    require(all(kinds[k] == 1 for k in (0x134900, 0x134b02, 0x134b03)), 'mesh singleton count')
    one = lambda k: next(p for p in parts if p.kind == k)
    mh = aligned_payload(one(0x134900))
    require(len(mh) == 48, 'source mesh header is not 48 bytes')
    rs, ib = aligned_payload(one(0x134b02)), aligned_payload(one(0x134b03))
    count, ni = u32(mh, 16), u32(mh, 44)
    if count == 0:
        return refonly.convert_empty_mesh(c, position, stats)
    require(count > 0 and len(rs) == count * 104, 'source material count')
    require(len(ib) == (ni * 2 + 3) // 4 * 4 and not any(ib[ni * 2:]), 'source index count/padding')
    indices = list(struct.unpack_from(f'<{ni}H', ib))
    records = [rs[p:p + 104] for p in range(0, len(rs), 104)]
    names = [p.payload for p in parts if p.kind == 0x134c02]
    vbs = [aligned_payload(p, 128) for p in parts if p.kind == 0x134b01]
    require(len(names) == count, 'source material-name count')
    source_groups = []
    for r in records:
        effect = u32(r, 48)
        require(effect in EFFECTS, f'undecoded source effect {effect}')
        if not source_groups or effect != source_groups[-1][0]:
            source_groups.append([effect, []])
        source_groups[-1][1].append(r)
    require(len(source_groups) == len(vbs) == u32(mh, 24), 'source effect-group count')
    target_groups, rewritten, out_indices = [], [], []
    for (effect, rows), vb in zip(source_groups, vbs):
        stride, target, _ = EFFECTS[effect]
        nv = sum(u32(r, 60) for r in rows)
        require(len(vb) == nv * stride, 'source group vertex size')
        if not target_groups or target != target_groups[-1][0]:
            target_groups.append([target, bytearray(), 0])
        group = target_groups[-1]
        used = 0
        for r in rows:
            n, nt, first, size = (u32(r, p) for p in (60, 64, 68, 92))
            require(size == nt * 3 and first <= ni and size <= ni - first and size > 0,
                    'source draw index range')
            q = indices[first:first + size]
            require(min(q) >= used and max(q) < used + n, 'source draw vertex range')
            require(first == len(out_indices), 'source draws do not cover indices in order')
            dest = bytearray(144)
            dest[:60] = r[:60]
            struct.pack_into('<I', dest, 48, target)
            struct.pack_into('<I', dest, 64, n)
            struct.pack_into('<II', dest, 96, nt, len(out_indices))
            struct.pack_into('<I', dest, 124, size)
            rewritten.append(bytes(dest))
            out_indices.extend(i - used + group[2] for i in q)
            group[1] += convert_vertices(vb[used * stride:(used + n) * stride], effect, n)
            group[2] += n
            used += n
            stats.draws += 1
            stats.vertices += n
            stats.triangles += nt
            stats.effects[f'{effect}->{target}'] += 1
    require(len(out_indices) == ni and max(out_indices) < 65536, 'target index coverage/width')
    head = bytearray(mh + bytes(4))
    struct.pack_into('<I', head, 24, len(target_groups))
    out = Builder(position + 8)
    out.add(0x134900, head, 16)
    out.add(0x134b02, b''.join(rewritten), 16)
    ib = struct.pack(f'<{ni}H', *out_indices)
    out.add(0x134b03, ib + bytes(-len(ib) % 4), 16)
    for _, vb, _ in target_groups:
        out.add(0x134b01, vb, 16)
    for name in names:
        out.add(0x134c02, name)
    return Chunk(0x80134100, bytes(out.data)).encode()


def convert_solid(c, position, stats):
    parts = chunks(c.payload, c.offset + 8)
    kinds = Counter(p.kind for p in parts)
    require(set(kinds) <= {0x134011, 0x134012, 0x80134100, 0x134013, 0x13401a} and
            all(kinds[k] == 1 for k in (0x134011, 0x134012, 0x80134100)),
            'undecoded solid children')
    sidecars.validate_solid_sidecars(c)
    out = Builder(position + 8)
    for p in parts:
        if p.kind == 0x134011:
            raw = bytearray(aligned_payload(p))
            require(len(raw) >= 164 and u32(raw, 12) & 0xffff == 22, 'source solid version')
            key = u32(raw, 16)
            struct.pack_into('<I', raw, 16, SOLID_KEYS.get(key, key))
            out.add(p.kind, raw, 16)
        elif p.kind == 0x134012:
            require(len(p.payload) % 8 == 0, 'texture hash table size')
            out.add(p.kind, p.payload)
        elif p.kind in (0x134013, 0x13401a):
            out.data += sidecars.convert_sidecar(p, out.position, stats)
        else:
            out.data += convert_mesh(p, out.position, stats)
    stats.solids += 1
    return Chunk(0x80134010, bytes(out.data)).encode()


def convert_list(c, position, stats):
    parts = chunks(c.payload, c.offset + 8)
    require(set(p.kind for p in parts) <= {0, 0x80134001, 0x80134010}, 'unsupported solid-list child')
    headers = [p for p in parts if p.kind == 0x80134001]
    solids = [p for p in parts if p.kind == 0x80134010]
    require(len(headers) == 1 and solids, 'source plain solid-list structure')
    hp = chunks(headers[0].payload, headers[0].offset + 8)
    info = next(p for p in hp if p.kind == 0x134002)
    require(len(info.payload) == 144 and u32(info.payload, 8) == 29 and
            u32(info.payload, 12) == len(solids), 'source world solid-list version/count')
    require(set(p.kind for p in hp) == {0x134002, 0x134003, 0x80134008}, 'source plain list header')
    directory = next(p for p in hp if p.kind == 0x134003)
    rows = list(struct.iter_unpack('<II', directory.payload))
    require(len(rows) == len(solids), 'source solid directory count')
    renamed = sorted(((SOLID_KEYS.get(key, key), spare, solid)
                      for (key, spare), solid in zip(rows, solids)), key=lambda row: row[0])
    require(len({key for key, _, _ in renamed}) == len(rows), 'solid namespace collision')
    hp = [Chunk(p.kind, b''.join(struct.pack('<II', key, spare) for key, spare, _ in renamed))
          if p.kind == 0x134003 else p for p in hp]
    out = Builder(position + 8)
    out.pad(16)
    out.add(0x80134001, encode_chunks(hp))
    for _, _, solid in renamed:
        out.data += convert_solid(solid, out.position, stats)
    return Chunk(0x80134000, bytes(out.data)).encode()


def translate_float(raw, offset, shift):
    v = struct.unpack_from('<f', raw, offset)[0]
    require(math.isfinite(v), 'non-finite spatial field')
    struct.pack_into('<f', raw, offset, v + shift)


def convert_scenery(c, position, number, shift_x=0, stats=None, *, shift=None,
                    allow_precull_mismatch=False):
    dx, dy = render_shift(shift_x, shift)
    parts = chunks(c.payload, c.offset + 8)
    require(set(p.kind for p in parts) <= {0x34101, 0x34102, 0x34103, 0x34105, 0x34106, 0x34107},
            'undecoded scenery child')
    out = Builder(position + 8)
    for p in parts:
        if p.kind == 0x34101:
            raw = bytearray(aligned_payload(p))
            require(len(raw) == 60, 'source scenery header size')
            struct.pack_into('<I', raw, 12, number)
            out.add(p.kind, raw + bytes(8), 16)
        elif p.kind == 0x34103:
            data = aligned_payload(p)
            require(len(data) % 64 == 0, 'source instance array size')
            rows = []
            for off in range(0, len(data), 64):
                src, dst = data[off:off + 64], bytearray(96)
                dst[:12], dst[12:16], dst[16:28] = src[:12], src[24:28], src[12:24]
                dst[32:44] = src[32:44]
                rotation = struct.unpack_from('<9h', src, 44)
                struct.pack_into('<9f', dst, 44, *(v / 8192 for v in rotation))
                dst[84:88] = src[62:64] + src[30:32]
                for q in (0, 16, 32):
                    translate_float(dst, q, dx)
                    if dy:
                        translate_float(dst, q + 4, dy)
                rows.append(bytes(dst))
            stats.instances += len(rows)
            out.add(p.kind, b''.join(rows), 16)
        elif p.kind == 0x34105:
            require(len(p.payload) % 36 == 0, 'source tree array size')
            rows = []
            for off in range(0, len(p.payload), 36):
                src, dst = p.payload[off:off + 36], bytearray(48)
                dst[:12], dst[16:28], dst[28:38] = src[:12], src[12:24], src[26:36]
                struct.pack_into('<I', dst, 12, struct.unpack_from('<H', src, 24)[0])
                for q in (0, 16):
                    translate_float(dst, q, dx)
                    if dy:
                        translate_float(dst, q + 4, dy)
                rows.append(bytes(dst))
            stats.nodes += len(rows)
            out.add(p.kind, b''.join(rows), 16)
        elif p.kind == 0x34102:
            require(len(p.payload) % 72 == 0, 'scenery model table size')
            out.add(p.kind, solid_models(p.payload))
        elif p.kind == 0x34106:
            # These point into the source city's override table. The later
            # table has unrelated rows; applying those indices is unsafe.
            stats.omitted[f'{p.kind:08x}'] += len(p.payload)
        elif p.kind == 0x34107:
            # Spatial precull bits repeat every 1024 m; their exception mask
            # repeats every 4096 m. Retaining rows requires the longer period.
            require(len(p.payload) % 128 == 0, 'scenery precull array size')
            require(not p.payload or allow_precull_mismatch or
                    (dx % 4096 == 0 and dy % 4096 == 0),
                    'scenery precull shift must preserve the 4096 m period')
            out.add(p.kind, p.payload)
    return Chunk(0x80034100, bytes(out.data)).encode()


def convert_tpk(c, position, stats):
    parts = chunks(c.payload, c.offset + 8)
    require(set(p.kind for p in parts) <= {0, 0xb3310000, 0xb3320000}, 'source TPK children')
    hp = next(p for p in parts if p.kind == 0xb3310000)
    dp = next(p for p in parts if p.kind == 0xb3320000)
    hs, ds = chunks(hp.payload, hp.offset + 8), chunks(dp.payload, dp.offset + 8)
    require(Counter(p.kind for p in ds if p.kind) == Counter({0x33320001: 1, 0x33320002: 1}),
            'source TPK data children/counts')
    one = lambda k: next(p for p in hs if p.kind == k)
    require(set(p.kind for p in hs) == {0x33310001, 0x33310002, 0x33310004, 0x33310005},
            'only plain source TPK records are decoded')
    info = bytearray(one(0x33310001).payload)
    require(len(info) == 124 and u32(info) == 5, 'source TPK version')
    struct.pack_into('<I', info, 0, 8)
    # Native packs hash the uppercase filename (seed -1, multiply by 33).
    # Include the source namespace and chunk offset: output placement can change.
    name = b'Location2\\Pack%08X_%08X.tpk' % (stats._pack_section, c.offset)
    info[0x20:0x60] = name + bytes(0x40 - len(name))
    from region import pack_hash
    identity = pack_hash(name.upper())
    struct.pack_into('<I', info, 0x60, identity)
    rs, ps = one(0x33310004).payload, one(0x33310005).payload
    require(len(rs) % 124 == 0 and len(ps) == len(rs) // 124 * 32, 'source texture record counts')
    data_header = next(p for p in ds if p.kind == 0x33320001)
    require(len(data_header.payload) == 24 and
            u32(data_header.payload, 12) == u32(one(0x33310001).payload, 0x60),
            'texture data header does not name its pack')
    data_info = bytearray(data_header.payload)
    struct.pack_into('<I', data_info, 12, identity)
    pixels = next(p for p in ds if p.kind == 0x33320002)
    # The source pixel area starts on the next absolute 128-byte boundary.
    pixel_data = aligned_payload(pixels, 128)
    records, platforms = [], []
    for i in range(len(rs) // 124):
        r, pl = rs[i * 124:(i + 1) * 124], ps[i * 32:(i + 1) * 32]
        name = r[12:36].split(b'\0')[0] + b'\0'
        # The native loader steps 89 + name-length bytes per record, so the
        # length byte counts the NUL padding that keeps rows 4-byte aligned.
        name += bytes(-(89 + len(name)) % 4)
        rec = bytearray(89 + len(name))
        rec[:12], rec[12:20], rec[20:48] = r[:12], r[36:44], r[48:76]
        rec[48:88] = r[76:116]
        rec[88], rec[89:] = len(name), name
        off, size = u32(rec, 20), u32(rec, 28)
        require(off <= len(pixel_data) and size <= len(pixel_data) - off, 'source texture pixel bounds')
        require(pl[20:24] in (b'DXT1', b'DXT3', b'DXT5'), 'unsupported source pixel format')
        require(rec[46] == {b'DXT1': 0x22, b'DXT3': 0x24, b'DXT5': 0x26}[pl[20:24]], 'texture format mismatch')
        # The source placement and full mip chain are unchanged. Class keys
        # are descriptive hashes and may be preserved independently of names.
        records.append(bytes(rec))
        platforms.append(bytes(12) + pl[20:24] + bytes(8))
    header = encode_chunks([Chunk(0x33310001, bytes(info)),
                            Chunk(0x33310002, one(0x33310002).payload),
                            Chunk(0x33310004, b''.join(records)),
                            Chunk(0x33310005, b''.join(platforms))])
    out = Builder(position + 8)
    out.add(0, bytes(48))
    out.add(0xb3310000, header)
    out.pad(128)
    body = Builder(out.position + 8)
    body.add(0x33320001, data_info)
    # 005605C2 skips two children unconditionally. The third is the pixel
    # header; 00560638 aligns header+0x87 down to 128 for the pixel bytes.
    count = -body.position % 128
    count += 128 if count < 8 else 0
    body.add(0, bytes(count - 8))
    body.add(0x33320002, b'\x11' * 120 + pixel_data)
    out.add(0xb3320000, body.data)
    stats.textures += len(records)
    return Chunk(0xb3300000, bytes(out.data)).encode()


def scenery_numbers(roots, source_number=None):
    """Read ordered source identities; the secondary container belongs to N-40."""
    scenes = [c for c in roots if c.kind == 0x80034100]
    require(1 <= len(scenes) <= 2, 'only one or two scenery containers are supported')
    numbers = []
    for scene in scenes:
        headers = [p for p in chunks(scene.payload, scene.offset + 8) if p.kind == 0x34101]
        require(len(headers) == 1, 'source scenery header count')
        header = aligned_payload(headers[0])
        require(len(header) == 60, 'source scenery header size')
        numbers.append(u32(header, 12))
    require(len(numbers) == 1 or numbers[1] == numbers[0] - 40,
            'source scenery header order/offset')
    if source_number is not None:
        require(numbers == [source_number, source_number - 40] if len(numbers) == 2
                else numbers[0] in (source_number, source_number - 40),
                'source scenery/index number')
    return numbers


def reference_exceptions(data, number, providers, *, target=False):
    """Identify the classified Z00 rows without inventing source providers.

    Instances are zero-based within their scenery container. Only the two keys
    absent from the entire source index and one sentinel-only row are allowed;
    a provider which exists but failed conversion never qualifies.
    """
    solid_sections, accepted_sections = providers
    if target:
        solid_sections = {SOLID_KEYS.get(k, k): v for k, v in solid_sections.items()}
    result = []
    stride, selector = (96, 84) if target else (64, 62)
    for scene_index, scene in enumerate(c for c in chunks(data) if c.kind == 0x80034100):
        parts = chunks(scene.payload, scene.offset + 8)
        models = next(c.payload for c in parts if c.kind == 0x34102)
        rows = aligned_payload(next(c for c in parts if c.kind == 0x34103))
        require(len(models) % 72 == 0 and len(rows) % stride == 0, 'reference row extent')
        for i in range(len(rows) // stride):
            model = struct.unpack_from('<h', rows, i * stride + selector)[0]
            require(0 <= model < len(models) // 72, 'reference model index')
            keys = {u32(models, model * 72 + off) for off in (24, 28, 32, 36)} - {0, 0xbe43edbb, 0x90f70174}
            missing = sorted(k for k in keys if not set(solid_sections.get(k, ())) & set(accepted_sections))
            if not keys or missing:
                result.append({'scene': scene_index, 'instance': i, 'model': model,
                               'missing': missing, 'sentinel_only': not keys})
    if not result:
        return []
    expected = {1: [0x56b52d28], 2: [], 4: [0xf390cd1a],
                5: [0xf390cd1a], 6: [0xf390cd1a]}
    require(number == 2600 and len(result) == len(expected) and
            all(r['scene'] == 0 and r['instance'] in expected and
                r['model'] == r['instance'] and r['missing'] == expected[r['instance']] and
                r['sentinel_only'] == (r['instance'] == 2) for r in result) and
            all(not solid_sections.get(k) for r in result for k in r['missing']),
            'unclassified reference-only instance')
    return result


def omit_animation_directory(c, stats, inventory=None):
    """Omit only a classified directory whose ordinary frames are retained."""
    report = texanim.classify_omission(c, inventory)
    require(report['ordinary_textures_retained'], 'animation omission lacks ordinary textures')
    stats.omitted[f'{c.kind:08x}'] += len(c.payload)


def convert_section(data, number, shift_x=20000, *, source_number=None, providers=None,
                    animation_inventory=None, shift=None, allow_precull_mismatch=False):
    """Return generated bytes and counts; never write source archives.

    Shift world-space scenery and event transforms/bounds. Solid vertices remain
    model-local, including road models whose local coordinates happen to be
    large. This prevents translating instantiated models twice.
    Pass the original index source_number when renumbering secondary-only
    scenery; its header alone cannot identify the owning section.
    providers is (source solid-key -> section numbers, accepted section numbers).
    Omitting it preserves the standalone geometry requirement.
    Batch callers supply texanim.inventory_source's animation_inventory; without
    it the omission classifier reads its default source index and stream.
    shift=(dx, dy) specifies render metres and supersedes shift_x=(dx, 0).
    Retained precull rows require multiples of 4096 m on both axes; the explicit
    allow_precull_mismatch override supports legacy single-section experiments.
    """
    dx, dy = render_shift(shift_x, shift)
    roots = chunks(data)
    if not any(c.kind == 0x80034100 for c in roots):
        return convert_resources(roots, number, animation_inventory=animation_inventory)
    source_numbers = scenery_numbers(roots, source_number)
    if source_number is None:
        # Preserve the secondary-only case for an unchanged section. Callers
        # renumbering it must supply the original index identity explicitly.
        source_number = number if source_numbers == [number - 40] else source_numbers[0]
    numbers = iter(source_numbers)
    out, stats = Builder(0), Stats(pack_section=number)
    for c in roots:
        if c.kind == 0:
            continue
        out.pad(128)
        if c.kind == 0xb3300000:
            out.data += convert_tpk(c, out.position, stats)
        elif c.kind == 0x80134000:
            out.data += convert_list(c, out.position, stats)
        elif c.kind == 0x80034100:
            header_number = number + next(numbers) - source_number
            require(0 <= header_number <= 0xffffffff, 'target scenery number out of range')
            out.data += convert_scenery(c, out.position, header_number, dx, stats,
                shift=(dx, dy), allow_precull_mismatch=allow_precull_mismatch)
        elif c.kind == 0x3bc00:
            out.data += emitters.convert_emitters(c, out.position, stats, dx, shift=(dx, dy))
        elif c.kind == 0x80036000:
            # Events share Builder/Stats with this module; import after setup.
            from events import convert_events, decode_events
            require(decode_events(c).section == source_number, 'source event/index number')
            out.data += convert_events(c, out.position, stats, dx, shift=(dx, dy), section=number)
        elif c.kind == texanim.DIRECTORY:
            omit_animation_directory(c, stats, animation_inventory)
        elif c.kind in (0x34159, 0x34027, 0x3b801):
            # Helicopter sheets, ordinary scenery physics spawns and streamed collision need
            # independent conversion. Never present opaque old bytes as new.
            stats.omitted[f'{c.kind:08x}'] += len(c.payload)
        else:
            raise FormatError(f'undecoded section chunk {c.kind:08x}')
    if providers is None:
        require(stats.solids and stats.instances, 'section lacks geometry or instances')
    else:
        try:
            refonly.require_section_geometry(data, bytes(out.data), stats, *providers)
        except FormatError as exc:
            # The proof checks source/target arrays before raising on closure.
            # Only this exact decoded exception may pass that final refusal.
            if (source_number != 2600 or str(exc) !=
                    'refonly unresolved solids: 56b52d28,f390cd1a'):
                raise
            reference_exceptions(data, source_number, providers)
    return bytes(out.data), stats
