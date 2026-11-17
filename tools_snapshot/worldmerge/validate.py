"""Loader-shaped checks independent of the source-to-target field writers."""
from collections import Counter
import math
import struct

from formats import chunks, render_shift, require, u32
import emitters
import events
import sidecars
import tail


STRIDES = {0: 36, 1: 52, 0x00010001: 52, 3: 52, 6: 24, 25: 36, 0x00050019: 36, 0x00060000: 36, **tail.TARGET_STRIDES}


def payload(c, alignment=16):
    start = -(c.offset + 8) % alignment
    require(start <= len(c.payload), 'target alignment outside chunk')
    require(c.payload[:start] == b'\x11' * start, 'target alignment filler')
    return c.payload[start:]


def inside(point, lo, hi, tolerance=.015):
    return all(math.isfinite(v) and a - tolerance <= v <= b + tolerance
               for v, a, b in zip(point, lo, hi))


def box(raw, low, high):
    lo, hi = struct.unpack_from('<3f', raw, low), struct.unpack_from('<3f', raw, high)
    require(all(math.isfinite(v) for v in (*lo, *hi)), 'non-finite box')
    require(all(a <= b for a, b in zip(lo, hi)), 'inverted box')
    return lo, hi


def validate_section(data, number, *, providers=None):
    """Validate a scenery section; absent scenery remains a missing-data error."""
    return _validate_section(data, number, resource_only=False, providers=providers)


def validate_resources(data, number):
    """Validate standalone resource bundles without requiring scenery/instances."""
    return _validate_section(data, number, resource_only=True)


def _validate_section(data, number, *, resource_only, providers=None):
    totals = Counter()
    texture_hashes, wanted_textures, solid_hashes, wanted_solids = set(), set(), set(), set()
    scenery_numbers = []
    roots = chunks(data)
    scenery_count = sum(c.kind == 0x80034100 for c in roots)
    for root in roots:
        if root.kind == 0:
            continue
        if root.kind == 0xb3300000:
            parts = chunks(root.payload, root.offset + 8)
            require(Counter(c.kind for c in parts if c.kind) == Counter({0xb3310000: 1, 0xb3320000: 1}),
                    'target TPK children/counts')
            h = next(c for c in parts if c.kind == 0xb3310000)
            d = next(c for c in parts if c.kind == 0xb3320000)
            hp, dp = chunks(h.payload, h.offset + 8), chunks(d.payload, d.offset + 8)
            require(Counter(c.kind for c in hp) == Counter({0x33310001: 1, 0x33310002: 1,
                                                          0x33310004: 1, 0x33310005: 1}) and
                    Counter(c.kind for c in dp if c.kind) == Counter({0x33320001: 1, 0x33320002: 1}),
                    'target TPK children/counts')
            get = lambda k: next(c.payload for c in hp if c.kind == k)
            require(u32(get(0x33310001)) == 8, 'target TPK version')
            rows, plat = get(0x33310004), get(0x33310005)
            pixels = payload(next(c for c in dp if c.kind == 0x33320002), 128)
            hashes = [v[0] for v in struct.iter_unpack('<II', get(0x33310002))]
            p, decoded = 0, []
            while p < len(rows):
                require(len(rows) - p >= 90, 'target texture header truncated')
                name_size = rows[p + 88]
                size = (89 + name_size + 3) // 4 * 4
                require(name_size > 0 and size <= len(rows) - p, 'target texture name bounds')
                r = rows[p:p + size]
                require(r[89 + name_size - 1] == 0, 'target texture name termination')
                index = len(decoded)
                require((index + 1) * 24 <= len(plat), 'target texture platform count')
                fmt = plat[index * 24 + 12:index * 24 + 16]
                require(fmt in (b'DXT1', b'DXT3', b'DXT5'), 'target texture pixel format')
                require(r[46] == {b'DXT1': 0x22, b'DXT3': 0x24, b'DXT5': 0x26}[fmt],
                        'target texture format code')
                width, height = struct.unpack_from('<HH', r, 40)
                mips = r[50]
                require(0 < width <= 8192 and 0 < height <= 8192 and
                        1 <= mips <= max(width, height).bit_length(), 'target texture dimensions/mips')
                block = 8 if fmt == b'DXT1' else 16
                sizes = [max(1, (max(1, width >> i) + 3) // 4) *
                         max(1, (max(1, height >> i) + 3) // 4) * block for i in range(mips)]
                off, total, top = u32(r, 20), u32(r, 28), u32(r, 36)
                require(total == sum(sizes) and top == sizes[0], 'target texture mip sizes')
                require(off <= len(pixels) and total <= len(pixels) - off, 'target texture pixel bounds')
                decoded.append(u32(r, 12))
                p += size
            require(decoded == hashes and len(plat) == 24 * len(hashes), 'target texture hash/record tables')
            texture_hashes.update(hashes)
            totals['textures'] += len(hashes)
        elif root.kind == 0x80134000:
            parts = chunks(root.payload, root.offset + 8)
            header = next(c for c in parts if c.kind == 0x80134001)
            hp = chunks(header.payload, header.offset + 8)
            info = next(c.payload for c in hp if c.kind == 0x134002)
            hashes = [r[0] for r in struct.iter_unpack('<II', next(c.payload for c in hp if c.kind == 0x134003))]
            solids = [c for c in parts if c.kind == 0x80134010]
            require(u32(info, 8) == 29 and len(solids) == u32(info, 12) == len(hashes), 'target solid-list version/count')
            require(hashes == sorted(set(hashes)), 'target solid hash order/uniqueness')
            for solid, hs in zip(solids, hashes):
                sidecars.validate_solid_sidecars(solid, target=True)
                sp = chunks(solid.payload, solid.offset + 8)
                for child in sp:
                    if child.kind in (0x134013, 0x13401a):
                        sidecars.convert_sidecar(child, child.offset, None)
                sh = payload(next(c for c in sp if c.kind == 0x134011))
                require(u32(sh, 12) & 0xffff == 22 and u32(sh, 16) == hs, 'target solid version/hash')
                solid_hashes.add(hs)
                tex = next(c.payload for c in sp if c.kind == 0x134012)
                wanted_textures.update(r[0] for r in struct.iter_unpack('<II', tex))
                mesh = next(c for c in sp if c.kind == 0x80134100)
                mp = chunks(mesh.payload, mesh.offset + 8)
                mh = payload(next(c for c in mp if c.kind == 0x134900))
                rb = payload(next(c for c in mp if c.kind == 0x134b02))
                ib = payload(next(c for c in mp if c.kind == 0x134b03))
                require(len(mh) == 52 and len(rb) == u32(mh, 16) * 144, 'target mesh/material sizes')
                ni = u32(mh, 44)
                require(len(ib) == (ni * 2 + 3) // 4 * 4 and not any(ib[ni * 2:]), 'target index buffer size')
                indices = struct.unpack_from(f'<{ni}H', ib)
                rows = [rb[i:i + 144] for i in range(0, len(rb), 144)]
                groups = []
                for r in rows:
                    effect = u32(r, 48)
                    require(effect in STRIDES, 'target effect declaration not decoded')
                    if not groups or effect != groups[-1][0]:
                        groups.append([effect, []])
                    groups[-1][1].append(r)
                vbs = [payload(c) for c in mp if c.kind == 0x134b01]
                names = [c for c in mp if c.kind == 0x134c02]
                require(len(vbs) == len(groups) == u32(mh, 24) and len(names) == len(rows), 'target effect/name counts')
                empty = not rows and not vbs and not ni and not u32(mh, 20)
                limit = float.fromhex('0x1.fffffep+127')
                bounds = struct.unpack_from('<3f', sh, 32), struct.unpack_from('<3f', sh, 48)
                if empty and bounds == ((limit,) * 3, (-limit,) * 3):
                    slo, shi = bounds
                else:
                    slo, shi = box(sh, 32, 48)
                covered = 0
                for (effect, records), vb in zip(groups, vbs):
                    stride, used = STRIDES[effect], 0
                    require(len(vb) == sum(u32(r, 64) for r in records) * stride, 'target vertex stride/count')
                    for r in records:
                        nv, tri, first, count = (u32(r, q) for q in (64, 96, 100, 124))
                        require(first == covered and count == tri * 3 and count <= ni - first, 'target draw index coverage')
                        q = indices[first:first + count]
                        require(q and min(q) >= used and max(q) < used + nv, 'target draw vertex range')
                        lo, hi = box(r, 0, 12)
                        for i in set(q):
                            pos = struct.unpack_from('<3f', vb, i * stride)
                            require(inside(pos, lo, hi) and inside(pos, slo, shi), 'target vertex outside model/draw bounds')
                        used += nv
                        covered += count
                        totals['vertices'] += nv
                        totals['draws'] += 1
                        totals['triangles'] += tri
                require(covered == ni, 'target index coverage')
                totals['solids'] += 1
        elif root.kind == 0x80034100:
            require(not resource_only, 'scenery in target resource section')
            parts = chunks(root.payload, root.offset + 8)
            headers = [c for c in parts if c.kind == 0x34101]
            require(len(headers) == 1, 'target scenery header count')
            header = payload(headers[0])
            expected = number - 40 * len(scenery_numbers)
            allowed = (number, number - 40) if scenery_count == 1 else (expected,)
            require(len(scenery_numbers) < 2 and len(header) == 68 and u32(header, 12) in allowed,
                    'target scenery header/number/order')
            scenery_numbers.append(u32(header, 12))
            infos = next(c.payload for c in parts if c.kind == 0x34102)
            require(len(infos) % 72 == 0, 'target scenery model-table size')
            for i in range(0, len(infos), 72):
                wanted_solids.update(u32(infos, i + k) for k in (24, 28, 32, 36)
                                     if u32(infos, i + k) not in (0, 0xbe43edbb, 0x90f70174))
            instances = payload(next(c for c in parts if c.kind == 0x34103))
            require(len(instances) % 96 == 0, 'target scenery instance stride')
            for i in range(0, len(instances), 96):
                r = instances[i:i + 96]
                box(r, 0, 16)
                require(all(math.isfinite(v) for v in struct.unpack_from('<12f', r, 32)), 'target instance transform')
                index = struct.unpack_from('<h', r, 84)[0]
                require(0 <= index < len(infos) // 72, 'target instance model-table index')
            tree = next((payload(c) for c in parts if c.kind == 0x34105), b'')
            require(len(tree) % 48 == 0, 'target scenery tree stride')
            for i in range(0, len(tree), 48):
                r = tree[i:i + 48]
                box(r, 0, 16)
                count = u32(r, 12)
                require(count <= 5, 'target tree child count')
                for k in struct.unpack_from(f'<{count}h', r, 28):
                    require((0 <= k < len(instances) // 96) or (0 < -k < len(tree) // 48), 'target tree child range')
            totals['instances'] += len(instances) // 96
            totals['nodes'] += len(tree) // 48
        elif root.kind == 0x34027:
            import props
            props.spawn_data(root,native=True)
        elif root.kind == 0x3bc00:
            require(not resource_only, 'emitters in target resource section')
            emitters.decode_emitters(root)
        elif root.kind == 0x80036000:
            require(not resource_only, 'events in target resource section')
            directory = events.decode_events(root)
            require(directory.section == number, 'target event/index number')
            totals['nodes'] += len(directory.nodes)
            totals['events'] += len(directory.events)
        else:
            require(False, f'opaque source chunk in target: {root.kind:08x}')
    if resource_only:
        require(totals['solids'] or totals['textures'], 'target resources absent')
    else:
        require(scenery_numbers and totals['instances'] and (totals['solids'] or providers is not None),
                'target geometry/instances absent')
        if not totals['solids']:
            # Reference-only sections still need accepted, indexed providers.
            # This also checks the exact instance rows of the named exception.
            from convert import reference_exceptions
            reference_exceptions(data, number, providers, target=True)
    return dict(totals), {'external_texture_hashes': sorted(wanted_textures - texture_hashes),
                          'external_solid_hashes': sorted(wanted_solids - solid_hashes)}


def _vector_translation(before, old_offset, after, new_offset, shift, message):
    original = struct.unpack_from('<3f', before, old_offset)
    expected = (original[0] + shift[0], original[1] + shift[1], original[2])
    actual = struct.unpack_from('<3f', after, new_offset)
    require(all(math.isfinite(v) for v in (*expected, *actual)), message)
    rounded = struct.unpack('<3f', struct.pack('<3f', *expected))
    require(actual == rounded, message)
    return max(abs(a - e) for a, e in zip(actual, expected))


def _event_translation(source, target, shift, source_number, target_number):
    """Compare aligned event bytes independently of the event field writer."""
    old_roots = [c for c in chunks(source) if c.kind == 0x80036000]
    new_roots = [c for c in chunks(target) if c.kind == 0x80036000]
    require(len(old_roots) == len(new_roots), 'event directory count changed')
    checked, maximum_error = 0, 0.
    for old, new in zip(old_roots, new_roots):
        bodies = []
        for root in (old, new):
            parts = chunks(root.payload, root.offset + 8)
            require([c.kind for c in parts] == [0x36001, 0x36002, 0x36003],
                    'translation event child order')
            bodies.append([payload(c) for c in parts])
        before, after = bodies
        require([len(b) for b in before] == [len(b) for b in after],
                'event payload extents changed')
        head, tree, records = before
        require(len(head) == 32 and len(tree) >= 16 and (len(tree) - 16) % 48 == 0
                and len(records) % 32 == 0, 'translation event payload sizes')
        expected = [bytearray(b) for b in before]
        if source_number is not None:
            require(u32(head, 12) == source_number, 'translation source event/index number')
            struct.pack_into('<I', expected[0], 12, target_number)
        for index, start, stride in ((1, 16, 48), (2, 16, 32)):
            for offset in range(start, len(before[index]), stride):
                error = _vector_translation(before[index], offset, after[index], offset,
                                            shift, 'event world translation mismatch')
                for axis, delta in ((0, shift[0]), (4, shift[1])):
                    if delta:
                        value = struct.unpack_from('<f', before[index], offset + axis)[0]
                        struct.pack_into('<f', expected[index], offset + axis, value + delta)
                maximum_error = max(maximum_error, error)
                checked += 3
        require(all(a == b for a, b in zip(expected, after)),
                'event world translation/payload mismatch')
    return checked, maximum_error


def _emitter_translation(source, target, shift):
    """Walk header counts/inline triggers independently of the emitter decoder."""
    old_roots = [c for c in chunks(source) if c.kind == 0x3bc00]
    new_roots = [c for c in chunks(target) if c.kind == 0x3bc00]
    require(len(old_roots) == len(new_roots), 'emitter chunk count changed')
    checked, maximum_error = 0, 0.
    for old, new in zip(old_roots, new_roots):
        before, after = payload(old), payload(new)
        require(len(before) == len(after) and len(before) >= 16, 'emitter payload extents changed')
        expected, p = bytearray(before), 16
        for _ in range(u32(before, 8)):
            require(p + 80 <= len(before), 'translation emitter record extent')
            count = struct.unpack_from('<H', before, p + 10)[0]
            fields = [p + 64]
            p += 80
            require(p + count * 48 <= len(before), 'translation emitter trigger extent')
            fields.extend(p + 48 * i + 16 for i in range(count))
            p += 48 * count
            for offset in fields:
                maximum_error = max(maximum_error, _vector_translation(
                    before, offset, after, offset, shift, 'emitter world translation mismatch'))
                for axis, delta in ((0, shift[0]), (4, shift[1])):
                    if delta:
                        value = struct.unpack_from('<f', before, offset + axis)[0]
                        struct.pack_into('<f', expected, offset + axis, value + delta)
                checked += 3
        require(p == len(before) and expected == after, 'emitter world translation/payload mismatch')
    return checked, maximum_error


def validate_translation(source, target, shift_x=0, *, source_number=None, target_number=None,
                         shift=None):
    """Check every world-space bound, translation and rotation against input.

    Source model-local geometry is deliberately excluded: shifting both model
    coordinates and instances would move roads twice and distort other models.
    Index identities can be supplied to check secondary-only renumbering.
    """
    shift = render_shift(shift_x, shift)
    source_sc = [c for c in chunks(source) if c.kind == 0x80034100]
    target_sc = [c for c in chunks(target) if c.kind == 0x80034100]
    require((source_number is None) == (target_number is None), 'translation needs both index identities')
    require(len(source_sc) == len(target_sc), 'scenery container count changed')
    require(len(source_sc) <= 2, 'scenery container count exceeds two')
    source_numbers, target_numbers = [], []
    checked, maximum_error = 0, 0.
    for old, new in zip(source_sc, target_sc):
        old_parts, new_parts = chunks(old.payload, old.offset + 8), chunks(new.payload, new.offset + 8)
        for parts, numbers, size in ((old_parts, source_numbers, 60), (new_parts, target_numbers, 68)):
            headers = [c for c in parts if c.kind == 0x34101]
            require(len(headers) == 1, 'translation scenery header count')
            header = payload(headers[0])
            require(len(header) == size, 'translation scenery header size')
            numbers.append(u32(header, 12))
            require(len(numbers) == 1 or numbers[-1] == numbers[0] - 40,
                    'translation scenery header order/offset')
        if source_number is not None and target_number is not None:
            require(source_numbers[-1] - source_number == target_numbers[-1] - target_number,
                    'translation scenery identity offset changed')
        old_instances = payload(next(c for c in old_parts if c.kind == 0x34103))
        new_instances = payload(next(c for c in new_parts if c.kind == 0x34103))
        require(len(old_instances) // 64 == len(new_instances) // 96, 'instance count changed')
        for i in range(len(old_instances) // 64):
            a, b = old_instances[i * 64:(i + 1) * 64], new_instances[i * 96:(i + 1) * 96]
            for old_off, new_off in ((0, 0), (12, 16), (32, 32)):
                error = _vector_translation(a, old_off, b, new_off, shift,
                                            'world translation/bounds mismatch')
                maximum_error = max(maximum_error, error)
                checked += 3
            expected = tuple(v / 8192 for v in struct.unpack_from('<9h', a, 44))
            require(expected == struct.unpack_from('<9f', b, 44), 'instance rotation changed')
            require(a[62:64] + a[30:32] == b[84:88], 'instance model/context indices changed')
        old_tree = next((c.payload for c in old_parts if c.kind == 0x34105), b'')
        new_tree = next((payload(c) for c in new_parts if c.kind == 0x34105), b'')
        require(len(old_tree) // 36 == len(new_tree) // 48, 'tree node count changed')
        for i in range(len(old_tree) // 36):
            a, b = old_tree[i * 36:(i + 1) * 36], new_tree[i * 48:(i + 1) * 48]
            for old_off, new_off in ((0, 0), (12, 16)):
                error = _vector_translation(a, old_off, b, new_off, shift, 'tree translation mismatch')
                maximum_error = max(maximum_error, error)
                checked += 3
            require(struct.unpack_from('<H', a, 24)[0] == u32(b, 12) and a[26:36] == b[28:38],
                    'tree children changed')
    event_checked, event_error = _event_translation(source, target, shift, source_number, target_number)
    emitter_checked, emitter_error = _emitter_translation(source, target, shift)
    return {'spatial_components_checked': checked + event_checked + emitter_checked,
            'maximum_translation_error_m': max(maximum_error, event_error, emitter_error)}
