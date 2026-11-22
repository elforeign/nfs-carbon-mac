"""The mixed shipped-piece connecting road at the crossing placement.

Render uses one affine map after the rigid chain. Collision bakes that map
into copied strip vertices, because the native triangle cache ignores bases.
No geometry is generated: topology, materials and strip attributes are shipped.
"""
from dataclasses import replace
import math
from pathlib import Path
import struct

from convert import Builder, aligned_payload
from formats import Chunk, chunks, require, u32
import c1_grid as grid
import c1_roads as roads
from ground import Pack, cross, dot
from region import children, collision_body, collision_cells, collision_tags, one

SHIFT = (0., 8192.)
COUNT, SOLID, SCENE = 34, 0xbd5ab32b, 366
CURVE = 0xfbe7f709
RETAINED, TAIL = 28, "CSCSSC"
UPSTREAM_HINGES = (3.463931911528, 4.993696034259)
TAIL_HINGES = (-2.564430041762, -4.999995599104, -4.975183181027,
               -4.999998700571, -1.329241588533, 4.396818262489)
DROP = (122, 356, 359, 374, 376, 390, 393, 394, 398, 399)
DROP_326 = (143,)
AFFINE = ((.8369214133, 0., .0619593397),
          (-.0170982688*.9452722347, 1.0158296790, .0170982688*.3262827031),
          (.2758131589, 0., .9054798684))
OFFSET = (-827.7485771518, -82.7556359965, 1380.1251559662)
IDENTITY = ((1., 0., 0.), (0., 1., 0.), (0., 0., 1.))


def add(a, b):
    return tuple(x+y for x, y in zip(a, b))


def sub(a, b):
    return tuple(x-y for x, y in zip(a, b))


def mv(m, v):
    return tuple(dot(r, v) for r in m)


def mm(a, b):
    return tuple(tuple(sum(a[i][k]*b[k][j] for k in range(3))
                       for j in range(3)) for i in range(3))


def unit(v):
    n = math.sqrt(dot(v, v))
    return tuple(x/n for x in v)


def rotation(axis, angle):
    a = unit(axis)
    c, s = math.cos(angle), math.sin(angle)
    skew = ((0., -a[2], a[1]), (a[2], 0., -a[0]), (-a[1], a[0], 0.))
    return tuple(tuple(c*(i == j)+(1-c)*a[i]*a[j]+s*skew[i][j]
                       for j in range(3)) for i in range(3))


def mean(vs):
    return tuple(sum(v[k] for v in vs)/len(vs) for k in range(3))


def render(v):
    return v[2], -v[0], v[1]


def physics(v, row):
    t = struct.unpack_from('<3f', row, 32)
    m = struct.unpack_from('<9f', row, 44)
    p = tuple(t[k]+sum(v[a]*m[3*a+k] for a in range(3)) for k in range(3))
    return -p[1], p[2], p[0]


def mesh(solid):
    """Read indexed FLOAT3 positions, grouped exactly as the native materials."""
    from validate import STRIDES
    parts = children(one(children(solid), 0x80134100))
    rows = aligned_payload(one(parts, 0x134b02))
    ib = aligned_payload(one(parts, 0x134b03))
    header = aligned_payload(one(parts, 0x134900))
    indices = struct.unpack_from(f'<{u32(header,44)}H', ib)
    groups = []
    for p in range(0, len(rows), 144):
        row = rows[p:p+144]
        effect = u32(row, 48)
        if not groups or groups[-1][0] != effect:
            groups.append((effect, []))
        groups[-1][1].append(row)
    buffers = [aligned_payload(c) for c in parts if c.kind == 0x134b01]
    require(len(groups) == len(buffers), 'link mesh effect groups')
    triangles = []
    for (effect, materials), vb in zip(groups, buffers):
        stride = STRIDES[effect]
        vertices = [struct.unpack_from('<3f', vb, j*stride)
                    for j in range(sum(u32(r, 64) for r in materials))]
        for r in materials:
            first, count = u32(r, 100), u32(r, 96)
            triangles.extend(tuple(vertices[k] for k in indices[first+3*j:first+3*j+3])
                             for j in range(count))
    return triangles


def solids(roots):
    return [s for r in roots if r.kind == 0x80134000
            for s in children(r) if s.kind == 0x80134010]


def solid_key(s):
    return u32(aligned_payload(one(children(s), 0x134011)), 16)


def chain(high, low, target):
    """The node-pinned diagnostic, including its original +0.72 degree tilt."""
    hc, lc = mean(high), mean(low)
    a, b = sub(high[-1], high[0]), sub(low[-1], low[0])
    turn = math.atan2(b[0], b[2])-math.atan2(a[0], a[2])
    step = rotation((0., 1., 0.), turn)
    delta = sub(lc, mv(step, hc))
    placements, m, t = [], IDENTITY, (0., 0., 0.)
    for _ in range(COUNT):
        placements.append((m, t))
        t, m = add(mv(m, delta), t), mm(m, step)
    displacement = sub(add(mv(m, hc), t), hc)
    forward = sub(lc, hc)
    tilt = rotation(cross((0., 1., 0.), unit((forward[0], 0., forward[2]))),
                    math.radians(.72))
    chord = mv(tilt, displacement)
    start = (-2678., target[1]-chord[1],
             target[2]+math.sqrt(chord[0]**2+chord[2]**2-(-2678.-target[0])**2))
    yaw = math.atan2(target[0]-start[0], target[2]-start[2])-math.atan2(chord[0], chord[2])
    q = mm(rotation((0., 1., 0.), yaw), tilt)
    offset = sub(start, mv(q, hc))
    return [(mm(q, m), add(mv(q, t), offset)) for m, t in placements]


def mapped(placements):
    return [(mm(AFFINE, m), add(mv(AFFINE, t), OFFSET)) for m, t in placements]


def cut_frame(cut):
    x = unit(sub(cut[-1], cut[0]))
    z = unit(cross(x, (0., 1., 0.)))
    y = cross(z, x)
    return tuple(zip(x, y, z))


def transpose(m):
    return tuple(zip(*m))


def curve_geometry(roots):
    import c1_world as w
    scene = w.scene_data(next(r for r in roots[1524] if r.kind == w.SCENE))
    row = scene.instances[39*96:40*96]
    solid = next(s for s in solids(roots[1524]) if solid_key(s) == CURVE)
    local = mesh(solid)
    vertices = sorted(set(physics(v, row) for tri in local for v in tri))
    ymin, ymax = min(v[1] for v in vertices), max(v[1] for v in vertices)
    low = [v for v in vertices if v[1] < ymin+.01]
    high = [v for v in vertices if v[1] > ymax-.01]
    require(len(low) == len(high) == 10, 'curve cut rows differ')
    model = struct.unpack_from('<h', row, 84)[0]
    return scene, row, solid, local, high, low, scene.models[model*72:(model+1)*72]


def layout(roots, target):
    """Bottom-pinned straights and seam-hinged tail, before the common affine.

    Each hinge rotates its piece and every later piece about the current
    entry cross line. Transporting the whole downstream chain preserves the
    shipped cut profiles and carries pitch through the following curves.
    Output order is downhill, as the serialized graph and original copies.
    """
    donors = {'S': geometry(roots), 'C': curve_geometry(roots)}
    straight = chain(donors['S'][4], donors['S'][5], target)[34-RETAINED:]
    m, t = straight[0]
    current = [add(mv(m, p), t) for p in donors['S'][4]]
    q, offset, tail = IDENTITY, (0., 0., 0.), []
    for kind, angle in zip(TAIL, TAIL_HINGES):
        require(abs(angle) <= 5., 'tail pitch hinge exceeds five degrees')
        high, low = donors[kind][4:6]
        m = mm(cut_frame(current), transpose(cut_frame(low)))
        t = sub(mean(current), mv(m, mean(low)))
        cut = [add(mv(q, p), offset) for p in current]
        origin = mean(cut)
        hinge = rotation(sub(cut[-1], cut[0]), math.radians(angle))
        offset = add(origin, mv(hinge, sub(offset, origin)))
        q = mm(hinge, q)
        tail.append((kind, mm(q, m), add(mv(q, t), offset)))
        current = [add(mv(m, p), t) for p in high]
    pieces = [*reversed(tail), *(('S', m, t) for m, t in straight)]
    if tail:
        # The two existing straights below the tail carry its pitch change
        # farther downhill. Rotate each whole uphill prefix about its own
        # entry cut; the lower copies and the bottom pin stay fixed.
        require(len(UPSTREAM_HINGES) == 2 and RETAINED >= 3,
                'upstream pitch hinge count differs')
        for index, angle in zip((len(tail)+1, len(tail)), UPSTREAM_HINGES):
            require(abs(angle) <= 5., 'upstream pitch hinge exceeds five degrees')
            _, m, t = pieces[index]
            cut = [add(mv(m, p), t) for p in donors['S'][5]]
            origin = mean(cut)
            hinge = rotation(sub(cut[-1], cut[0]), math.radians(angle))
            pieces[:index+1] = [(kind, mm(hinge, m),
                                add(origin, mv(hinge, sub(t, origin))))
                               for kind, m, t in pieces[:index+1]]
    require(len(pieces) == COUNT, 'mixed layout count differs')
    return [(kind, mm(AFFINE, m), add(mv(AFFINE, t), OFFSET)) for kind, m, t in pieces]

def local_cut(donor, high):
    row, local, cut = donor[1], donor[3], donor[4 if high else 5]
    return sorted((v for v in set(v for tri in local for v in tri)
                   if any(math.dist(physics(v, row), p) < 1e-5 for p in cut)),
                  key=lambda v: physics(v, row))


def piece_kinds():
    return [*reversed(TAIL), *('S' for _ in range(RETAINED))]


def collision_ids():
    result, start = [], 0
    for kind in piece_kinds():
        ids = list(range(start, start+(2 if kind == 'C' else 1)))
        result.append(ids)
        start += len(ids)
    return result


def serialized_cuts(roots, rows):
    donors = {'S': geometry(roots), 'C': curve_geometry(roots)}
    high, low = [], []
    for kind, row in zip(piece_kinds(), rows):
        high.append([physics(v, row) for v in local_cut(donors[kind], True)])
        low.append([physics(v, row) for v in local_cut(donors[kind], False)])
    return high, low


def float_up(v):
    f = struct.unpack('<f', struct.pack('<f', v))[0]
    return struct.unpack('<f', struct.pack('<I', u32(struct.pack('<f', f))+1))[0] if f < v else f


def bounds(vertices):
    return (tuple(min(v[k] for v in vertices) for k in range(3)),
            tuple(max(v[k] for v in vertices) for k in range(3)))


def render_row(source, m, t, vertices, model):
    origin = add(mv(m, physics((0., 0., 0.), source)), t)
    basis = []
    for k in range(3):
        v = tuple(float(k == j) for j in range(3))
        basis.extend(render(sub(add(mv(m, physics(v, source)), t), origin)))
    row = bytearray(source)
    struct.pack_into('<3f9f', row, 32, *render(origin), *basis)
    # Bounds use the actual serialized non-rigid matrix and mesh positions.
    lo, hi = bounds([render(physics(v, row)) for v in vertices])
    struct.pack_into('<3f', row, 0, *lo)
    struct.pack_into('<3f', row, 16, *hi)
    struct.pack_into('<h', row, 84, model)
    struct.pack_into('<h', row, 28, 0)
    row[88:96] = bytes(8)
    return bytes(row)


def bake(source, instance, m, t, article_id, move=None):
    """Copy a complete article, quantizing world vertices on the 1/128 m grid.

    move, when given, replaces the affine map (a per-vertex bake)."""
    row = source.instances[instance*64:(instance+1)*64]
    article = source.articles[struct.unpack_from('<H', row, 26)[0]]
    require(article[4:8] == bytes(4), 'link donor carries barriers')
    translation = struct.unpack_from('<3f', row, 48)
    if move is None:
        def move(v):
            return add(mv(m, v), t)
    vertices = [move(v) for f in source.faces(instance) for v in f.vertices]
    lo, hi = bounds(vertices)
    center = tuple(round((a+b)*64)/128 for a, b in zip(lo, hi))
    out, relative = bytearray(article), []
    for strip in range(struct.unpack_from('<H', article)[0]):
        p = 16+16*strip
        c = struct.unpack_from('<3f', article, p)
        start = 16+struct.unpack_from('<H', article, p+14)[0]
        count = struct.unpack_from('<H', article, start+6)[0]
        nc = tuple(round(v*128)/128 for v in sub(move(sub(c, translation)), center))
        struct.pack_into('<3f', out, p, *nc)
        radius = 0.
        for j in range(count):
            v = struct.unpack_from('<3h', article, start+8*j)
            world = move(tuple(c[k]+v[k]/128-translation[k] for k in range(3)))
            q = tuple(round((world[k]-center[k]-nc[k])*128) for k in range(3))
            require(all(-32768 <= v <= 32767 for v in q), 'link strip exceeds s16')
            struct.pack_into('<3h', out, start+8*j, *q)
            relative.append(tuple(nc[k]+q[k]/128 for k in range(3)))
            radius = max(radius, math.hypot(q[0]/128, q[2]/128))
        struct.pack_into('<H', out, p+12, math.ceil(radius*16))
    extent = tuple(max(abs(v[k]) for v in relative) for k in range(3))
    inst = bytearray(64)
    struct.pack_into('<3f', inst, 0, 1., 0., 0.)
    struct.pack_into('<3f', inst, 32, 0., 0., 1.)
    for p, e in zip((12, 20, 44), extent):
        struct.pack_into('<f', inst, p, float_up(e))
    struct.pack_into('<H', inst, 26, article_id)
    struct.pack_into('<3f', inst, 48, *(-v for v in center))
    struct.pack_into('<f', inst, 60, float_up(math.hypot(extent[0], extent[2])))
    return bytes(inst), bytes(out)


def carp(entries):
    """Native one-group Arti directory; an empty co has loader count zero."""
    raw = bytearray(32+16*len(entries))
    struct.pack_into('<4I', raw, 0, 0x43415250, 0x2a, 0, 1)
    struct.pack_into('<4I', raw, 16, grid.ARTI, 0x12, len(entries), 1)
    for i, (key, count, payload) in enumerate(entries):
        raw += bytes(-len(raw) % 16)
        p = 32+16*i
        struct.pack_into('<4I', raw, p, key, len(payload)<<8 | 2, count,
                         len(raw)-p if count else 0)
        raw += payload
    return bytes(raw)


def make_pack(source, placements, key, curve_source):
    copies = []
    for kind, m, t in placements:
        donor, ids = (source, (8,)) if kind == 'S' else (curve_source, (3, 4))
        first = len(copies)
        copies.extend(bake(donor, i, m, t, first+j) for j, i in enumerate(ids))
    body = carp([(grid.CI, len(copies), b''.join(v[0] for v in copies)),
                 (0x636f0000, 0, b''),
                 *((0x63610000+i, 1, v[1]) for i, v in enumerate(copies))])
    return struct.pack('<4I', len(body), key, 0, 0)+body


def tree(instances):
    """A native five-child box tree over the retained/mapped instance boxes."""
    rows = [instances[p:p+96] for p in range(0, len(instances), 96)]
    nodes = []
    def visit(ids):
        index = len(nodes)
        nodes.append(None)
        lows = [struct.unpack_from('<3f', rows[i]) for i in ids]
        highs = [struct.unpack_from('<3f', rows[i], 16) for i in ids]
        lo = tuple(min(v[k] for v in lows) for k in range(3))
        hi = tuple(max(v[k] for v in highs) for k in range(3))
        if len(ids) <= 5:
            refs = ids
        else:
            axis = max(range(3), key=lambda k: hi[k]-lo[k])
            ordered = sorted(ids, key=lambda i: struct.unpack_from('<f', rows[i], 4*axis)[0])
            stride = math.ceil(len(ids)/5)
            refs = [-visit(ordered[p:p+stride]) for p in range(0, len(ids), stride)]
        row = bytearray(48)
        struct.pack_into('<3fI3f', row, 0, *lo, len(refs), *hi)
        struct.pack_into(f'<{len(refs)}h', row, 28, *refs)
        nodes[index] = bytes(row)
        return index
    visit(list(range(len(rows))))
    return b''.join(nodes)


def scene_chunk(scene, position):
    import c1_world as w
    out = Builder(position+8)
    for kind, data, align in ((w.HEADER, scene.header, 16), (w.MODELS, scene.models, 1),
                              (w.INSTANCES, scene.instances, 16),
                              *((c.kind, c.payload, 1) for c in scene.extras),
                              (w.TREE, scene.tree, 16), (w.PRECULL, scene.precull, 1)):
        out.add(kind, data, align)
    return Chunk(w.SCENE, bytes(out.data), position)


def drop_scene(scene, drop):
    keep = [i for i in range(len(scene.instances)//96) if i not in drop]
    instances = b''.join(scene.instances[i*96:(i+1)*96] for i in keep)
    mapping = {old: new for new, old in enumerate(keep)}
    extras = []
    for c in scene.extras:
        if c.kind == 0x3410d:
            require(len(c.payload) == len(scene.instances)//96*32, 'scenery sidecar stride')
            data = b''.join(c.payload[i*32:(i+1)*32] for i in keep)
        elif c.kind == 0x34106:
            data = b''.join(struct.pack('<2H', override, mapping[i])
                            for override, i in struct.iter_unpack('<2H', c.payload) if i in mapping)
        else:
            require(False, 'undecoded dropped scenery sidecar')
        extras.append(Chunk(c.kind, data))
    return replace(scene, instances=instances, tree=tree(instances), extras=tuple(extras))


def overrides(payload):
    """Keep global override IDs stable while rebasing their scene-220 selectors."""
    out = bytearray(payload)
    for p in range(0, len(out)//6*6, 6):
        section, instance = struct.unpack_from('<2h', out, p)
        if section == 220:
            if instance in DROP:
                # Scene zero is absent; its initialized lookup slot is null.
                # Keep override IDs stable for script references (007A2D50).
                struct.pack_into('<2h', out, p, 0, 0)
            else:
                struct.pack_into('<h', out, p+2, instance-sum(i < instance for i in DROP))
    return bytes(out)


def drop_physics(root, override_rows):
    """Remove scenery-bound 64-byte spawns, including their collision bodies.

    008179B0/00817250: native 0x34027 count is +10; each record's +40
    resolves a 6-byte scenery override. These are separate from ci/co floors.
    """
    raw = aligned_payload(root)
    count = struct.unpack_from('<H',raw,10)[0]
    require(len(raw) == 16+64*count, 'scenery physics record stride')
    keep = []
    for p in range(16,len(raw),64):
        row = raw[p:p+64]
        override = u32(row,40)
        require(override < len(override_rows)//6, 'scenery physics override index')
        section,instance = struct.unpack_from('<2H',override_rows,6*override)
        if section != 220 or instance not in DROP:
            keep.append(row)
    header = bytearray(raw[:16])
    struct.pack_into('<H',header,10,len(keep))
    pad = -(root.offset+8)%16
    return Chunk(root.kind,root.payload[:pad]+header+b''.join(keep),root.offset)


def open_bottom_pack(raw, cut):
    """Trim only the three kerb edges crossing the fixed bottom mouth.

    Barrier +28 is inverse XZ length (native DistSq); endpoint Ys are the
    rectangle's vertical limits, not a grade to interpolate when trimming.
    Article +2 locates barriers, +6 locates the following surface table.
    These two articles have no strips; all other pack bytes are retained.
    """
    return trim_barriers(raw, ((6, (0, 7), cut), (26, (6,), cut)))


def open_route_pack(raw, nodes, top_cut):
    """Open the Rockport gate and the rail met by the height-fitted arc."""
    key = u32(raw, 4)
    if key == 134:
        # Edges 4 and 6 cross the copied carriageway; edge 8 meets the arc.
        return trim_barriers(raw, ((10, (4, 6, 8), top_cut),))
    if key == 192:
        aid, edge, a, b, half = 12, 10, 8739, 8740, 16.
    else:
        return raw
    start, end = nodes[a], nodes[b]
    direction = unit((end[0]-start[0], 0., end[2]-start[2]))
    lateral = (direction[2], 0., -direction[0])
    cut = [add(start, tuple(sign*half*v for v in lateral)) for sign in (-1, 1)]
    return trim_barriers(raw, ((aid, (edge,), cut),))


def trim_barriers(raw, cuts):
    """Retain article tails, metadata and every edge outside each road cut."""
    pack = Pack(raw)
    changed = {}
    for aid, edges, cut in cuts:
        left, right = cut[0], cut[-1]
        lateral = unit((right[0]-left[0], 0., right[2]-left[2]))
        width = math.hypot(right[0]-left[0], right[2]-left[2])
        article = pack.articles[aid]
        require(article[:4] == bytes(4), 'gate article carries strips')
        row = pack.instances[aid*64:(aid+1)*64]
        require(struct.unpack_from('<H',row,26)[0] == aid, 'gate selector differs')
        translation = struct.unpack_from('<3f',row,48)
        count = struct.unpack_from('<H',article,4)[0]
        kept = []
        for e in range(count):
            edge = article[16+32*e:16+32*(e+1)]
            if e not in edges:
                kept.append(edge)
                continue
            a,b = (struct.unpack_from('<3f',edge,p) for p in (0,16))
            sa,sb = (dot(sub(sub(v,translation),left),lateral) for v in (a,b))
            lo,hi = sorted(((0.-sa)/(sb-sa),(width-sa)/(sb-sa)))
            lo,hi = max(0.,lo),min(1.,hi)
            require(lo < hi, 'gate no longer crosses road')
            for start,end in ((0.,lo),(hi,1.)):
                if end-start < 1e-7:
                    continue
                out = bytearray(edge)
                pa,pb = (tuple(a[k]+(b[k]-a[k])*t if k != 1 else v[k]
                               for k in range(3)) for t,v in ((start,a),(end,b)))
                struct.pack_into('<3f',out,0,*pa)
                struct.pack_into('<3f',out,16,*pb)
                pa,pb = (struct.unpack_from('<3f',out,p) for p in (0,16))
                struct.pack_into('<f',out,28,1/math.hypot(pb[0]-pa[0],pb[2]-pa[2]))
                kept.append(bytes(out))
        header = bytearray(article[:16])
        struct.pack_into('<2H',header,4,len(kept),32*len(kept))
        changed[0x63610000+aid] = bytes(header)+b''.join(kept)+article[16+32*count:]
    return replace_articles(raw, changed)


def replace_articles(raw, changed):
    """Rebase the native directory after changing article lengths."""
    body = raw[16:]
    tags = collision_tags(body,grid.ARTI)
    replacements = sorted((tags[k][3],tags[k][1]>>8,value,k) for k,value in changed.items())
    out = bytearray(body)
    for offset,size,value,_ in reversed(replacements):
        out[offset:offset+size] = value
    for key,(p,flags,count,offset) in tags.items():
        if count:
            delta = sum(len(value)-size for pos,size,value,_ in replacements if pos < offset)
            size = len(changed[key]) if key in changed else flags>>8
            struct.pack_into('<I',out,p+4,size<<8 | flags&255)
            struct.pack_into('<I',out,p+12,offset+delta-p)
    header = bytearray(raw[:16])
    struct.pack_into('<I',header,0,len(out))
    return bytes(header)+bytes(out)


def cells(tile, descriptor, pack):
    body = tile[16:]
    records = collision_cells(body, collision_tags(body, grid.ARTI)[grid.CGCN])
    bins = {struct.unpack_from('<H', r, 4)[0]:
            (r[:4], [[v[0] for v in struct.iter_unpack('<I', f)] for f in grid.families(r)])
            for r in records}
    origin, size, rows, cols = grid.grid_fields(descriptor)
    additions = {}
    for i in range(len(pack.instances)//64):
        vertices = [v for f in pack.faces(i) for v in f.vertices]
        lo, hi = bounds(vertices)
        # Inclusive upper cell matches native box FindNodes.
        for r in range(math.floor((lo[2]-origin[2])/size), math.floor((hi[2]-origin[2])/size)+1):
            for c in range(math.floor((lo[0]-origin[0])/size), math.floor((hi[0]-origin[0])/size)+1):
                require(0 <= r < rows and 0 <= c < cols, 'link footprint outside grid')
                additions.setdefault(r*cols+c, []).append(pack.key<<16 | i)
    for cid, refs in additions.items():
        prefix, families = bins.setdefault(cid, (bytes(4), [[], [], [], []]))
        families[0].extend(refs)
    result = bytearray(grid.make_tile([grid.cell_record(prefix, cid, 2600, refs)
                                      for cid, (prefix, refs) in sorted(bins.items())]))
    struct.pack_into('<I', result, 4, 2600)
    return bytes(result)


def road_map(raw, centers):
    _, counts, arrays = roads._source(raw)
    require(counts == dict(nodes=8988, segments=12328, profiles=1524, roads=2148), 'link graph base differs')
    nodes, segments = bytearray(arrays[roads.NODES]), bytearray(arrays[roads.SEGMENTS])
    for i, xyz in enumerate(centers, 8988):
        nodes += struct.pack('<3fHhBB7H', *xyz, i, 907, 0, 0xaa, *([0xaaaa]*7))
    # Complete the shipped three-road junction with a fourth road end.
    # All six pairs of road ends have connectors; none has two roads.
    edges = [(8754, 8988), *((8988+i, 8989+i) for i in range(COUNT)),
             (9022, 1534), (9022, 4454), (9022, 4455)]
    for sid, (a, b) in enumerate(edges, 12328):
        pa, pb = struct.unpack_from('<3f', nodes, a*32), struct.unpack_from('<3f', nodes, b*32)
        direction = unit(sub(pb, pa))
        length = round(math.dist(pa, pb)*65535/1000)
        require(length <= 65535, 'link segment length encoding')
        segment = bytearray(arrays[roads.SEGMENTS][11708*22:11709*22])
        # The bridge and link are one plain chain. The final hop joins
        # Palmont's junction as a connector, leaving its road 353 alone.
        connector = sid >= 12363
        struct.pack_into('<3Hh2H', segment, 0, a, b, length,
                         -1 if connector else 989, sid, 0x103 if connector else 0x102)
        # 007EB5F0 / 005D1CA0 / 00404D80: +16 is the control at the
        # END node, +19 at the START; +12/+14 scale lengths by 500/65535.
        handle = round(math.dist(pa,pb)/3*65535/500)
        struct.pack_into('<2H',segment,12,handle,handle)
        struct.pack_into('<6b', segment, 16, *(round(v*127) for v in (*(-v for v in direction), *direction)))
        segments += segment
        for node in (a, b):
            degree = nodes[node*32+16]
            require(degree < 7, 'link connector adjacency full')
            struct.pack_into('<H', nodes, node*32+18+degree*2, sid)
            nodes[node*32+16] += 1
    for i in range(11695, 11710):
        flags = struct.unpack_from('<H', segments, i*22+10)[0]
        struct.pack_into('<H', segments, i*22+10, flags & ~0x40)
    arrays[roads.NODES], arrays[roads.SEGMENTS] = bytes(nodes), bytes(segments)
    arrays[roads.HEADER] = struct.pack('<7H', 1524, 9023, 12366, 0, 2148, 0, 0)
    return replace_road_arrays(raw, arrays)


def replace_road_arrays(raw, arrays):
    tags = collision_tags(raw, roads.RNGP)
    out = bytearray(raw[:roads._suffix_start(raw, tags)])
    strides = {roads.HEADER: 14, **{k: stride for k, _, stride, _ in roads.TABLES}}
    for key, (p, flags, _, _) in tags.items():
        out += bytes(-len(out) % 16)
        payload = arrays[key]
        count = len(payload)//strides[key]
        struct.pack_into('<4I', out, p, key, len(payload)<<8 | (flags & 255), count,
                         len(out)-p if count else 0)
        out += payload
    return bytes(out)+bytes(-len(out) % 16)


def inventory(index, stream):
    from merge import read_section
    return {s.number: list(chunks(read_section(stream, s))) for s in index.sections
            if s.number in (193, 220, 366, 1207, 1247, 1524, 2500, 2600)}


def geometry(roots):
    import c1_world as w
    def scene(n):
        return w.scene_data(next(r for rs in roots.values() for r in rs
                                 if r.kind == w.SCENE and w.scene_data(r).number == n))
    source = scene(1207)
    row = source.instances[185*96:186*96]
    solid = next(s for s in solids(roots[1247]) if solid_key(s) == SOLID)
    local = mesh(solid)
    vertices = sorted(set(physics(v, row) for tri in local for v in tri))
    ymin, ymax = min(v[1] for v in vertices), max(v[1] for v in vertices)
    low = [v for v in vertices if abs(v[1]-ymin) < 1e-5]
    high = [v for v in vertices if abs(v[1]-ymax) < 1e-5]
    require(len(low) == len(high) == 10, 'link donor cut rows differ')
    model = struct.unpack_from('<h', row, 84)[0]
    return source, row, solid, local, high, low, source.models[model*72:(model+1)*72]


def bottom_cut(index, stream):
    import c1_world as w
    roots = inventory(index,stream)
    _,source,_,local,_,low,_ = geometry(roots)
    scene = w.scene_data(next(r for r in roots[366] if r.kind == w.SCENE
                             and w.scene_data(r).number == 366))
    row = scene.instances[(23+COUNT-1)*96:(23+COUNT)*96]
    vertices = sorted(set(v for tri in local for v in tri))
    return [physics(v,row) for v in vertices if abs(physics(v,source)[1]-low[0][1]) < 1e-5]


def rewrite(tracks, index, stream, replacements, parts):
    """Repack changed records, retaining every other byte and metadata field."""
    import c1_world as w
    from merge import read_section
    staged = tracks/'STREAML5RA.BUN.link'
    sections = []
    with staged.open('wb') as out:
        for section in index.sections:
            raw = replacements.get(section.number)
            if raw is None:
                raw = read_section(stream, section)
            out.write(bytes(-out.tell() % 2048))
            record = bytearray(section.raw)
            struct.pack_into('<3I', record, 20, out.tell(), len(raw), len(raw))
            sections.append(bytes(record))
            out.write(raw)
    result = Builder(0)
    for part in index.parts:
        if part.kind == 0x34110:
            result.pad(16)
            result.add(part.kind, b''.join(sections))
        elif part.kind in parts:
            result.pad(16)
            result.add(part.kind, parts[part.kind], 16 if part.kind == w.MAP else 1)
        else:
            w.append_at_residue(result, part)
    staged.replace(tracks/'STREAML5RA.BUN')
    (tracks/'L5RA.BUN').write_bytes(result.data)


def panorama_visibility(payload):
    """Load the shipped college mountains behind the crossing's upper bend."""
    import visibility as vis
    table = vis.read(payload)
    rows = []
    require(sum(r.number == 326 for r in table.rows) == 1, 'link panorama row absent/duplicated')
    for row in table.rows:
        if row.number == 326:
            require(283 not in row.entries, 'link panorama already loaded')
            entries = tuple(sorted((*row.entries, 283)))
            require(len(entries) <= 127, 'link panorama row exceeds signed cap')
            header = bytearray(row.header)
            header[15] = len(entries)
            struct.pack_into('<h', header, 16, len(entries))
            row = replace(row, header=bytes(header), entries=entries)
        rows.append(row.encode())
    out = Builder(8)
    for part in table.parts:
        if part.kind == vis.SELECTORS:
            out.add(part.kind, b''.join(table.selectors), 16)
        else:
            out.add(part.kind, b''.join(rows) if part.kind == vis.ROWS else part.payload)
    return bytes(out.data)


def apply(tracks):
    """Called once, after the ordinary crossing-placement pair is complete."""
    import c1_world as w
    from merge import load_index
    index, stream, _ = load_index(tracks, 'L5RA')
    roots = inventory(index, stream)
    require(all(s.number != 0 for s in index.sections), 'override tombstone scene is occupied')
    source_scene, source_row, solid, local, high, low, model = geometry(roots)
    map_raw = collision_body(one(index.parts, w.MAP))
    target = w.ground.road_nodes(index)[1534]
    donors = {'S': (source_scene, source_row, solid, local, high, low, model),
              'C': curve_geometry(roots)}
    placements = layout(roots, target)
    first_model = len(w.scene_data(next(r for r in roots[366] if r.kind == w.SCENE)).models)//72
    new_rows = [render_row(donors[kind][1], m, t,
                           [v for tri in donors[kind][3] for v in tri],
                           first_model+(kind == 'C')) for kind, m, t in placements]
    hs, ls = serialized_cuts(roots, new_rows)
    centers = [mean(cut) for cut in hs]+[mean(ls[-1])]
    bottom = ls[-1]
    city = grid.read_city(index, stream)
    key = next(i for i in range(1, grid.PACK_LIMIT) if i not in city.packs)
    raw_pack = make_pack(Pack(city.packs[1512]), placements, key, Pack(city.packs[1508]))
    pack = Pack(raw_pack)
    descriptor = grid.tag_data(map_raw, collision_tags(map_raw, grid.CDAT)[grid.CGRD])
    tile_root = next(r for r in roots[2600] if r.kind == w.TILE)
    tile = cells(collision_body(tile_root), descriptor, pack)
    replacements = {}
    nodes = [*w.ground.road_nodes(index), *centers]
    for number in (220, 366, 2600):
        out = Builder(0)
        for root in roots[number]:
            if root.kind == w.SCENE and w.scene_data(root).number == number:
                scene = w.scene_data(root)
                if number == 220:
                    scene = drop_scene(scene, DROP)
                elif number == 366:
                    instances = scene.instances+b''.join(new_rows)
                    scene = replace(scene, models=scene.models+model+donors['C'][6], instances=instances,
                                    tree=tree(instances))
                out.pad(128)
                out.data += scene_chunk(scene, out.position).encode()
            elif number == 2600 and root.kind == w.TILE:
                out.pad(16)
                out.add(w.TILE, tile, 16)
            elif number == 220 and root.kind == 0x34027:
                override_rows = one(index.parts,0x34108).payload
                w.append_at_residue(out,drop_physics(root,override_rows))
            elif number == 2600 and root.kind == w.PACK and u32(collision_body(root),4) == 220:
                out.pad(16)
                out.add(w.PACK,open_bottom_pack(collision_body(root),bottom),16)
            elif number == 2600 and root.kind == w.PACK and u32(collision_body(root),4) in (134,192):
                out.pad(16)
                out.add(w.PACK,open_route_pack(collision_body(root),nodes,hs[1]),16)
            else:
                w.append_at_residue(out, root)
        if number == 366:
            # Both complete donor solids, retaining their nested alignment.
            out.pad(128)
            position = out.position
            body = Builder(position+8)
            template = next(r for r in roots[1247] if r.kind == 0x80134000 and solid in children(r))
            header = one(children(template), 0x80134001)
            hp = children(header)
            info = bytearray(one(hp, 0x134002).payload)
            struct.pack_into('<I', info, 12, 2)
            body.pad(16)
            body.add(0x80134001, b''.join(c.encode() for c in
                     (Chunk(0x134002, bytes(info)), Chunk(0x134003, struct.pack('<4I', SOLID, 0, CURVE, 0)),
                      Chunk(0x80134008, b''))))
            w.append_at_residue(body, solid)
            w.append_at_residue(body, donors['C'][2])
            out.data += Chunk(0x80134000, bytes(body.data), position).encode()
        if number == 2600:
            out.pad(16)
            out.add(w.PACK, raw_pack, 16)
        replacements[number] = bytes(out.data)
    changed_parts = {w.MAP: road_map(map_raw, centers),
                     w.vis.CONTAINER: panorama_visibility(w.vis.payload_of(index))}
    for part in index.parts:
        if part.kind == 0x34108:
            changed_parts[part.kind] = overrides(part.payload)
    rewrite(tracks, index, stream, replacements, changed_parts)
    tidy(tracks)


# Stable selectors keep external scene and collision references valid; empty
# providers have no draws/strips. Only the decoded west branch is edited.
LEG_RAILS = (193, 197, 202, 240)
RAIL = 0x34ba864d


def leg_cut(roots, row):
    """Final curve's actual left boundary, then the old far rail's near point."""
    import c1_world as w
    donor = curve_geometry(roots)
    stations = []
    for v in sorted(set(v for tri in donor[3] for v in tri),
                    key=lambda v: physics(v, donor[1])[1]):
        if not stations or physics(v, donor[1])[1]-physics(stations[-1][0], donor[1])[1] > .02:
            stations.append([])
        stations[-1].append(v)
    cut = [physics(max(vs, key=lambda v: physics(v, donor[1])), row) for vs in stations]
    scene = w.scene_data(next(r for r in roots[366] if r.kind == w.SCENE
                             and w.scene_data(r).number == 326))
    rail = scene.instances[235*96:236*96]
    a, b = (physics((x, 0., 0.), rail) for x in (0., 8.))
    d = sub(b, a)
    f = ((cut[-1][0]-a[0])*d[0]+(cut[-1][2]-a[2])*d[2])/(d[0]**2+d[2]**2)
    require(0 < f < 1, 'left cut no longer meets the old far rail')
    return cut+[add(a, tuple(f*v for v in d))]


def cut_distance(p, a, b):
    dx, dz = b[0]-a[0], b[2]-a[2]
    return ((p[0]-a[0])*dz-(p[2]-a[2])*dx)/math.hypot(dx, dz)


def clip_values(poly, fn):
    """Clip an attribute-carrying polygon without changing its winding."""
    out = []
    for a, b in zip(poly, poly[1:]+poly[:1]):
        da, db = fn(a), fn(b)
        if da >= 0:
            out.append(a)
        if (da < 0) != (db < 0):
            out.append(tuple(x+(y-x)*da/(da-db) for x, y in zip(a, b)))
    return out


def triangle_area(poly):
    return sum(math.sqrt(dot(n, n))/2 for i in range(1, len(poly)-1)
               for n in (cross(sub(poly[i], poly[0]), sub(poly[i+1], poly[0])),))


def leg_fragments(tri, cut, margin=0.):
    """Positive-area portions beyond the finite cut, never the bridge side."""
    cap = lambda p: -cut_distance(p, cut[-2], cut[-1])-margin
    below = clip_values(list(tri), cap)
    return [part for a, b in zip(cut[:-2], cut[1:-1])
            if triangle_area(part := clip_values(below, lambda p: -cut_distance(p, a, b)-margin)) > 1e-7]


def retain_leg(tri, cut, position=lambda v: v):
    """The cap's bridge side union the right side of the curved boundary."""
    if not leg_fragments([position(v) for v in tri], cut):
        return [list(tri)]
    cap = lambda v: cut_distance(position(v), cut[-2], cut[-1])
    bridge = clip_values(list(tri), cap)
    bend = clip_values(list(tri), lambda v: -cap(v))
    for a, b in zip(cut[:-2], cut[1:-1]):
        bend = clip_values(bend, lambda v: cut_distance(position(v), a, b))
    return [poly for poly in (bridge, bend)
            if triangle_area([position(v) for v in poly]) > 1e-7]


def clip_leg_solid(solid, row, cut, position):
    """Clip existing indexed materials; interpolate their normals, UVs and RGBA."""
    from validate import STRIDES
    parts = children(one(children(solid), 0x80134100))
    header = bytearray(aligned_payload(one(parts, 0x134900)))
    records = aligned_payload(one(parts, 0x134b02))
    indices = struct.unpack_from(f'<{u32(header,44)}H', aligned_payload(one(parts, 0x134b03)))
    buffers = iter(aligned_payload(p) for p in parts if p.kind == 0x134b01)
    names = [p for p in parts if p.kind == 0x134c02]
    groups, rows, kept_names, output_indices = [], [], [], []
    previous = None
    for j, offset in enumerate(range(0, len(records), 144)):
        rec = bytearray(records[offset:offset+144])
        effect = u32(rec, 48)
        # The retained source identity uses the same native reflective layout.
        require(effect in (0, 1, 3, 0x00010001), 'left cut vertex declaration differs')
        stride = STRIDES[effect]
        if effect != previous:
            vb = next(buffers)
            groups.append(bytearray())
            previous = effect
        # Float attributes surround the packed four-channel colour at +24.
        def read_vertex(k):
            raw = vb[k*stride:(k+1)*stride]
            return (*struct.unpack_from('<6f', raw), *raw[24:28],
                    *struct.unpack_from(f'<{(stride-28)//4}f', raw, 28))
        output = []
        for k in range(u32(rec, 96)):
            tri = [read_vertex(i) for i in indices[u32(rec,100)+3*k:u32(rec,100)+3*k+3]]
            for poly in retain_leg(tri, cut, lambda v: physics(v[:3], row)):
                for n in range(1, len(poly)-1):
                    output.extend((poly[0], poly[n], poly[n+1]))
        if not output:
            continue
        base = len(groups[-1])//stride
        require(base+len(output) < 65536, 'left cut vertex index width')
        struct.pack_into('<I', rec, 64, len(output))
        struct.pack_into('<2I', rec, 96, len(output)//3, len(output_indices))
        struct.pack_into('<I', rec, 124, len(output))
        output_indices.extend(range(base, base+len(output)))
        for v in output:
            groups[-1] += struct.pack('<6f4B', *v[:6], *(max(0, min(255, round(x))) for x in v[6:10]))
            groups[-1] += struct.pack(f'<{len(v)-10}f', *v[10:])
        rows.append(bytes(rec))
        kept_names.append(names[j])
    groups = [vb for vb in groups if vb]
    struct.pack_into('<3I', header, 16, len(rows), sum(len(vb)//STRIDES[u32(r,48)] for vb, r in
                     zip(groups, [r for i,r in enumerate(rows) if not i or u32(r,48)!=u32(rows[i-1],48)])), len(groups))
    struct.pack_into('<I', header, 44, len(output_indices))
    out = Builder(position+8)
    for part in children(solid):
        if part.kind == 0x80134100:
            mesh_out = Builder(out.position+8)
            mesh_out.add(0x134900, bytes(header), 16)
            mesh_out.add(0x134b02, b''.join(rows), 16)
            ib = struct.pack(f'<{len(output_indices)}H', *output_indices)
            mesh_out.add(0x134b03, ib+bytes(-len(ib)%4), 16)
            for vb in groups:
                mesh_out.add(0x134b01, bytes(vb), 16)
            for name in kept_names:
                mesh_out.add(name.kind, name.payload)
            out.data += Chunk(part.kind, bytes(mesh_out.data), out.position).encode()
        elif part.kind == 0x134011:
            sh = bytearray(aligned_payload(part))
            struct.pack_into('<I', sh, 20, len(output_indices)//3)
            out.add(part.kind, bytes(sh), 16)
        else:
            import c1_world as w
            w.append_at_residue(out, part)
    return Chunk(solid.kind, bytes(out.data), position)


def rail_rows(scene, cut, solid):
    """Reuse the shipped eight-metre rail, including its posts, for each edge."""
    source = scene.instances[193*96:194*96]
    model = struct.unpack_from('<h', source, 84)[0]
    vertices = [v for tri in mesh(solid) for v in tri]
    # Decode the near-side crossing from the existing old-road floor.
    begin = (-2583.643678765, 209.770223969, 6740.140491192)
    path = [begin, *[p for p in cut[1:] if p[2] > begin[2]+.001]]
    # The source's local X follows the rail, local Z is height. Construct
    # physical affine maps of its original world frame, without a new model.
    origin = physics((0., 0., 0.), source)
    axes = [sub(physics(tuple(float(i == j) for i in range(3)), source), origin)
            for j in range(3)]
    determinant = dot(axes[0], cross(axes[1], axes[2]))
    inv = tuple(tuple(v/determinant for v in cross(axes[(i+1)%3], axes[(i+2)%3])) for i in range(3))
    result = []
    for a, b in zip(path, path[1:]):
        along = tuple(v/8 for v in sub(b, a))
        normal = unit((-(b[2]-a[2]), 0., b[0]-a[0]))
        target = transpose((along, normal, (0., 1., 0.)))
        m = mm(target, inv)
        result.append(render_row(source, m, sub(a, mv(m, origin)), vertices, model))
    return result, path


def tidy_render(roots, cut, rail_solid):
    import c1_world as w
    road = w.scene_data(next(r for r in roots if r.kind == w.SCENE and w.scene_data(r).number == 366))
    shadow = w.scene_data(next(r for r in roots if r.kind == w.SCENE and w.scene_data(r).number == 326))
    selectors = {}
    for scene, ids in ((road, (2,4,10,12)), (shadow, (159,171))):
        for i in ids:
            row = scene.instances[i*96:(i+1)*96]
            selectors[u32(scene.models, struct.unpack_from('<h',row,84)[0]*72+24)] = row
    additions, _ = rail_rows(shadow, cut, rail_solid)
    kept = [shadow.instances[p:p+96] for p in range(0,len(shadow.instances),96) if p//96 not in LEG_RAILS]
    # Shorten the straddling far-side rail along its existing local axis.
    p = kept.index(shadow.instances[235*96:236*96])
    original = shadow.instances[235*96:236*96]
    a,b = (physics((x,0.,0.), original) for x in (0.,8.))
    f = -cut_distance(a,cut[-2],cut[-1])/(cut_distance(b,cut[-2],cut[-1])-cut_distance(a,cut[-2],cut[-1]))
    shortened = bytearray(original)
    origin = physics((8*f,0.,0.),original)
    struct.pack_into('<3f', shortened, 32, *render(origin))
    for k in range(3):
        struct.pack_into('<f', shortened, 44+4*k, struct.unpack_from('<f',original,44+4*k)[0]*(1-f))
    kept[p] = bytes(shortened)
    instances = b''.join(kept+additions)
    shadow = replace(shadow, instances=instances, tree=tree(instances))
    out = Builder(0)
    for root in roots:
        if root.kind == w.SCENE and w.scene_data(root).number == 326:
            out.pad(128)
            out.data += scene_chunk(shadow, out.position).encode()
        elif root.kind == 0x80134000 and any(solid_key(s) in selectors for s in solids([root])):
            out.pad(128)
            body = Builder(out.position+8)
            for part in children(root):
                if part.kind == 0x80134010 and solid_key(part) in selectors:
                    body.pad(128)
                    body.data += clip_leg_solid(part, selectors[solid_key(part)], cut, body.position).encode()
                else:
                    w.append_at_residue(body, part)
            out.data += Chunk(root.kind,bytes(body.data),out.position).encode()
        else:
            w.append_at_residue(out, root)
    return list(chunks(bytes(out.data)))


def tidy_collision(raw, cut, path):
    """Clip floor triangles and barrier lines; keep external article IDs stable."""
    pack = Pack(raw)
    changed = {}
    for aid in (26,27,28,29):
        row = pack.instances[aid*64:(aid+1)*64]
        translation = struct.unpack_from('<3f', row, 48)
        article = pack.articles[aid]
        output = []
        for face in pack.faces(aid):
            for poly in retain_leg(list(face.vertices), cut):
                for i in range(1,len(poly)-1):
                    tri = (poly[0],poly[i],poly[i+1])
                    if triangle_area(tri) > 1e-7:
                        output.append((tri,face))
        spheres, strips = bytearray(), bytearray()
        for tri,face in output:
            center = struct.unpack_from('<3f', article, 16+16*face.strip)
            qs = []
            for p in tri:
                q = tuple(round((p[k]+translation[k]-center[k])*128) for k in range(3))
                candidates = []
                for dx in range(-2,3):
                    for dz in range(-2,3):
                        v = (q[0]+dx,q[1],q[2]+dz)
                        world = tuple(center[k]+v[k]/128-translation[k] for k in range(3))
                        if (
                            cut_distance(world,cut[-2],cut[-1]) >= 0 or
                            min(cut_distance(world,a,b) for a,b in zip(cut[:-2],cut[1:-1])) >= 0):
                            candidates.append((math.dist(world,p),v))
                require(candidates, 'left cut quantization has no retained grid point')
                qs.append(min(candidates)[1])
            radius = math.ceil(max(math.hypot(q[0],q[2])/128 for q in qs)*16)
            spheres += struct.pack('<3f2H',*center,radius,16*len(output)+len(strips))
            for q,word in zip(qs,(3,2 if face.two_sided else 0,face.flags)):
                strips += struct.pack('<3hH',*q,word)
        body = spheres+strips
        body += bytes(-len(body)%16)
        header = bytearray(article[:16])
        struct.pack_into('<4H',header,0,len(output),len(body),0,0)
        old_end = 16+struct.unpack_from('<H',article,2)[0]
        changed[0x63610000+aid] = bytes(header)+body+article[old_end:]
    for aid in (10,11):
        article = pack.articles[aid]
        tr = struct.unpack_from('<3f',pack.instances,aid*64+48)
        count = struct.unpack_from('<H',article,4)[0]
        require(article[:4] == bytes(4), 'left rail article acquired strips')
        kept = []
        for i in range(count):
            edge = article[16+32*i:16+32*(i+1)]
            a,b = (sub(struct.unpack_from('<3f',edge,p),tr) for p in (0,16))
            # Partition a line at every cut plane; keep only its right/bridge intervals.
            ts = [0.,1.]
            for p,q in zip(cut,cut[1:]):
                da,db = cut_distance(a,p,q),cut_distance(b,p,q)
                if da*db < 0:ts.append(da/(da-db))
            ts.sort()
            intervals = []
            for lo,hi in zip(ts,ts[1:]):
                mid = add(a,tuple(v*(lo+hi)/2 for v in sub(b,a)))
                if cut_distance(mid,cut[-2],cut[-1]) < 0 and min(
                        cut_distance(mid,p,q) for p,q in zip(cut[:-2],cut[1:-1])) < 0:
                    continue
                if intervals and abs(intervals[-1][1]-lo) < 1e-10:
                    intervals[-1] = (intervals[-1][0],hi)
                else:
                    intervals.append((lo,hi))
            for lo,hi in intervals:
                if lo == 0 and hi == 1:
                    kept.append(edge)
                    continue
                piece = bytearray(edge)
                for offset,t,source in ((0,lo,a),(16,hi,b)):
                    p = add(a,tuple(v*t for v in sub(b,a)))
                    struct.pack_into('<3f',piece,offset,p[0]+tr[0],source[1]+tr[1],p[2]+tr[2])
                struct.pack_into('<f',piece,28,1/(math.hypot(b[0]-a[0],b[2]-a[2])*(hi-lo)))
                kept.append(bytes(piece))
        if aid == 10:
            template = article[16:48]
            for a,b in zip(path,path[1:]):
                piece = bytearray(template)
                bottom,top = min(a[1],b[1])-1.,max(a[1],b[1])+1.35
                struct.pack_into('<3f',piece,0,a[0]+tr[0],bottom+tr[1],a[2]+tr[2])
                struct.pack_into('<3f',piece,16,b[0]+tr[0],top+tr[1],b[2]+tr[2])
                struct.pack_into('<f',piece,28,1/math.hypot(b[0]-a[0],b[2]-a[2]))
                kept.append(bytes(piece))
        header = bytearray(article[:16])
        struct.pack_into('<2H',header,4,len(kept),32*len(kept))
        changed[0x63610000+aid] = bytes(header)+b''.join(kept)+article[16+32*count:]
    return replace_articles(raw,changed)


def without_reflections(roots):
    """Omit authored lake mirrors from the crossing's two scenery scenes.

    The unlabelled treeline has a decoded negative-Y vertex map to its
    upright twin; the other five pieces identify themselves by solid name.
    Instance flags do not distinguish these authored mirrors from terrain.
    """
    import c1_world as w
    names = {solid_key(s): aligned_payload(one(children(s), 0x134011))[160:]
             .split(b'\0', 1)[0].upper() for s in solids(roots)}
    out = Builder(0)
    for root in roots:
        if root.kind == w.SCENE and w.scene_data(root).number in (193, 326):
            scene = w.scene_data(root)
            removed = []
            for i in range(len(scene.instances)//96):
                row = scene.instances[i*96:(i+1)*96]
                key = u32(scene.models, struct.unpack_from('<h', row, 84)[0]*72+24)
                if ((scene.number == 326 and i in DROP_326) or
                        b'REFLECTION' in names.get(key, b'') or key == 0x75513475):
                    removed.append(i)
            if removed:
                # Source scenery bindings now survive the city import. Use
                # the same selector compaction as ordinary scenery removals.
                scene = drop_scene(scene, removed)
                out.pad(128)
                out.data += scene_chunk(scene, out.position).encode()
                continue
        w.append_at_residue(out, root)
    return list(chunks(bytes(out.data)))


def with_pond_copy(roots):
    """Extend the shipped pond beneath the crossing approach by one instance."""
    import c1_world as w
    out = Builder(0)
    for root in roots:
        if root.kind == w.SCENE and w.scene_data(root).number == 366:
            scene = w.scene_data(root)
            pond = bytearray(scene.instances[22*96:23*96])
            require(u32(scene.models, struct.unpack_from('<h', pond, 84)[0]*72+24) == 0xd760e0b2 and
                    u32(pond, 12) == 0x8200 and struct.unpack_from('<h', pond, 28)[0] == 0 and
                    not scene.extras, 'link pond source identity/sidecars differ')
            for offset in (0, 16, 32):
                struct.pack_into('<f', pond, offset, struct.unpack_from('<f', pond, offset)[0]-512.)
            rows = scene.instances+pond
            scene = replace(scene, instances=rows, tree=tree(rows))
            out.pad(128)
            out.data += scene_chunk(scene, out.position).encode()
        else:
            w.append_at_residue(out, root)
    return list(chunks(bytes(out.data)))


def tidy(tracks):
    import c1_world as w
    from merge import load_index, read_section
    index, stream, _ = load_index(tracks,'L5RA')
    roots = inventory(index,stream)
    road = w.scene_data(next(r for r in roots[366] if r.kind == w.SCENE and w.scene_data(r).number == 366))
    cut = leg_cut(roots,road.instances[23*96:24*96])
    rail = next(solid for section in index.sections if section.number == 2100
                for solid in solids(list(chunks(read_section(stream,section)))) if solid_key(solid) == RAIL)
    rendered = with_pond_copy(tidy_render(roots[366],cut,rail))
    shadow = w.scene_data(next(r for r in roots[366] if r.kind == w.SCENE and w.scene_data(r).number == 326))
    _,path = rail_rows(shadow,cut,rail)
    out = Builder(0)
    for root in roots[2600]:
        if root.kind == w.PACK and u32(collision_body(root),4) == 134:
            out.pad(16)
            out.add(w.PACK,tidy_collision(collision_body(root),cut,path),16)
        else:
            w.append_at_residue(out,root)
    # Restored scene-326 bindings end at 141; its first removed instance is
    # 143. Prove that the retained global selectors still match after removal.
    overrides = one(index.parts, 0x34108).payload
    for source_roots in (roots[193], rendered):
        for root in without_reflections(source_roots):
            if root.kind != w.SCENE:
                continue
            scene = w.scene_data(root)
            if scene.number not in (193,326):
                continue
            for extra in scene.extras:
                if extra.kind == 0x34106:
                    for oid, instance in struct.iter_unpack('<2H',extra.payload):
                        require(struct.unpack_from('<2H',overrides,oid*6) == (scene.number,instance),
                                'reflection scene override needs rebase')
    replacements = {n: b''.join(r.encode() for r in without_reflections(rs))
                    for n, rs in ((193, roots[193]), (366, rendered))}
    replacements[2600] = bytes(out.data)
    rewrite(tracks,index,stream,replacements,{})


def height(faces, x, z):
    values = [h for face in faces if (h := face.height(x, z)) is not None]
    return max(values) if values else None


def intersection(a, b):
    """Projected triangle intersection; linear floor differences peak at vertices."""
    poly = [(v[0], v[2]) for v in a.vertices]
    tri = [(v[0], v[2]) for v in b.vertices]
    def side(p, q, r):
        return (q[0]-p[0])*(r[1]-p[1])-(q[1]-p[1])*(r[0]-p[0])
    orient = 1 if side(*tri) > 0 else -1
    for p, q in zip(tri, tri[1:]+tri[:1]):
        result = []
        for s, e in zip(poly, poly[1:]+poly[:1]):
            ds, de = orient*side(p, q, s), orient*side(p, q, e)
            if ds >= -1e-10:
                result.append(s)
            if (ds < 0) != (de < 0):
                result.append(tuple(s[k]+(e[k]-s[k])*ds/(ds-de) for k in range(2)))
        poly = result
        if not poly:
            break
    return poly


def floor_overlap(new, old):
    """Exact maximum signed floor separation on every projected overlap.

    Both heights are affine on a clipped triangle pair, so its vertices
    suffice. Keep the sign and source strip alongside the acceptance number.
    """
    worst = None
    old_boxes = [(f, bounds(f.vertices)) for f in old]
    for nf in new:
        lo, hi = bounds(nf.vertices)
        for ef, (elo, ehi) in old_boxes:
            if any(hi[k] < elo[k] or ehi[k] < lo[k] for k in (0, 2)):
                continue
            for x, z in intersection(nf, ef):
                nh, eh = nf.height(x, z), ef.height(x, z)
                if nh is None or eh is None:
                    continue
                delta = nh-eh
                if worst is None or abs(delta) > worst['maximum']:
                    worst = dict(maximum=abs(delta), new_minus_old=delta,
                                 x=x, z=z, old_pack=ef.pack,
                                 old_instance=ef.instance, old_strip=ef.strip)
    require(worst is not None, 'link has no old-road floor overlap')
    return worst


def join(cut, new, old, top):
    a, b = cut[0], cut[-1]
    nx, nz = b[2]-a[2], -(b[0]-a[0])
    n = math.hypot(nx, nz)
    nx, nz = nx/n, nz/n
    if (top and nz < 0) or (not top and nz > 0):
        nx, nz = -nx, -nz
    steps, holes, inside_misses = [], 0, 0
    for i in range(129):
        x, z = a[0]+(b[0]-a[0])*i/128, a[2]+(b[2]-a[2])*i/128
        outside = height(old, x+.15*nx, z+.15*nz)
        holes += outside is None
        if 0 < i < 128:
            inside = height(new, x-.15*nx, z-.15*nz)
            inside_misses += inside is None
            if outside is not None and inside is not None:
                steps.append(abs(inside-outside))
    overlap = []
    for nf in new:
        for ef in old:
            for x, z in intersection(nf, ef):
                nh, eh = nf.height(x, z), ef.height(x, z)
                if nh is not None and eh is not None:
                    overlap.append((abs(nh-eh), x, z))
    return dict(cut=[a, b], covered=sum(height(old, p[0], p[2]) is not None for p in cut),
                outside_misses=holes, inside_misses=inside_misses, step_samples=len(steps),
                max_step=max(steps, default=math.inf), overlap=max(overlap, default=(math.inf, 0, 0)))


def collision_seams(faces, high, low, expected=None):
    errors, misses, source_misses, added_misses, rounding_misses = [], 0, 0, 0, 0
    for i in range(COUNT-1):
        # Along the run, normal to the shared cut, rather than along world Z.
        d = sub(mean(low[i+1]), mean(high[i]))
        dx, dz = unit((d[0], 0., d[2]))[0::2]
        values = []
        for j in range(1, 6):
            p = tuple(low[i][0][k]+(low[i][-1][k]-low[i][0][k])*j/6 for k in range(3))
            before = height(faces[i], p[0]-.1*dx, p[2]-.1*dz)
            after = height(faces[i+1], p[0]+.1*dx, p[2]+.1*dz)
            source_before = height(expected[i], p[0]-.1*dx, p[2]-.1*dz) if expected else None
            source_after = height(expected[i+1], p[0]+.1*dx, p[2]+.1*dz) if expected else None
            native_miss = expected is not None and (source_before is None or source_after is None)
            source_misses += native_miss
            if before is None or after is None:
                misses += 1
                added_misses += not native_miss
                # A point within one bake quantum of the shipped cut can
                # change triangle membership after vertex rounding. Keep it
                # visible in the report; vertex checks independently bound
                # every displacement to .01 m.
                if expected is not None and not native_miss:
                    edge_before = before is None and height(expected[i], p[0]-.09*dx, p[2]-.09*dz) is None
                    edge_after = after is None and height(expected[i+1], p[0]+.09*dx, p[2]+.09*dz) is None
                    rounding_misses += edge_before or edge_after
            elif expected is None:
                values.append(abs((before-after)-.016))
            elif not native_miss:
                values.append(abs((before-after)-(source_before-source_after)))
        errors.append(max(values, default=0.))
    return dict(max=max(errors), failed=sum(e > .02 for e in errors), misses=misses,
                source_misses=source_misses, added_misses=added_misses,
                rounding_misses=rounding_misses, unexplained_misses=added_misses-rounding_misses,
                samples=5*(COUNT-1))


def render_seams(high, low):
    gaps = [max(math.dist(a, b) for a, b in zip(low[i], high[i+1])) for i in range(COUNT-1)]
    return dict(max=max(gaps), failed=sum(g > .05 for g in gaps), count=len(gaps))


def sample_line(centers):
    """Every 10 m along the full polyline, including the final cut midpoint."""
    lengths = [math.dist(a, b) for a, b in zip(centers, centers[1:])]
    total = sum(lengths)
    samples = []
    segment, start = 0, 0.
    for distance in [*range(0, math.ceil(total), 10), total]:
        while segment < len(lengths)-1 and distance > start+lengths[segment]:
            start += lengths[segment]
            segment += 1
        f = (distance-start)/lengths[segment]
        samples.append(tuple(centers[segment][k]+f*(centers[segment+1][k]-centers[segment][k])
                             for k in range(3)))
    return samples


def ground_samples(world, centers):
    # A query one metre above the rendered centre line is within suspension
    # search range and avoids claiming rounded mesh Y is the collision height.
    samples = sample_line(centers)
    misses = 0
    for x, y, z in samples:
        hit = world.find_face_below(x, z, y+1.)
        misses += hit is None or not 0 <= y+1.-hit.height <= 2.
    return dict(samples=len(samples), misses=misses, query_clearance_m=1.)


def reachable(nodes, segments, missing=None, start=8739, end=1534):
    """Undirected traversal of reciprocal retail adjacency, requiring the new road."""
    missing = {missing} if isinstance(missing, int) else set(missing or ())
    queue, seen = [(start, False)], {(start, False)}
    for node, used in queue:
        if node == end and used:
            return True
        for sid in nodes[node][7:7+nodes[node][5]]:
            if sid in missing:
                continue
            seg = segments[sid]
            other = seg[1] if seg[0] == node else seg[0]
            state = other, used or sid >= 12328
            if state not in seen:
                seen.add(state)
                queue.append(state)
    return False


def scenery_in_way(scene, road_triangles, names, exclude=()):
    from ground import Face
    result = []
    for i in range(len(scene.instances)//96):
        if i in exclude:
            continue
        row = scene.instances[i*96:(i+1)*96]
        a, b = struct.unpack_from('<3f', row), struct.unpack_from('<3f', row, 16)
        lo, hi = (-b[1], a[2], a[0]), (-a[1], b[2], b[0])
        corners = ((lo[0], 0., lo[2]), (hi[0], 0., lo[2]),
                   (hi[0], 0., hi[2]), (lo[0], 0., hi[2]))
        rect = [Face(tuple(corners[j] for j in ids), 0, 0, 0, 0, 0)
                for ids in ((0, 1, 2), (0, 2, 3))]
        if not any(intersection(f, r) for f in road_triangles for r in rect):
            continue
        model = struct.unpack_from('<h', row, 84)[0]
        data = scene.models[model*72:(model+1)*72]
        result.append(dict(instance=i, name=names.get(u32(data,24), data[:22].split(b'\0')[0].decode('ascii', 'replace')),
                           key=f'{u32(data,24):08x}', height=[lo[1], hi[1]],
                           x=[lo[0], hi[0]], z=[lo[2], hi[2]]))
    return result


def old_road_centers(world):
    stations = []
    for i in (24, 25, 26, 27, 28):
        vertices = set(v for f in world.packs[134].faces(i) for v in f.vertices)
        groups = []
        for v in sorted(vertices, key=lambda p: p[1]):
            if not groups or abs(v[1]-groups[-1][0][1]) > .015:
                groups.append([])
            groups[-1].append(v)
        for group in groups:
            a, b = max(((a,b) for a in group for b in group), key=lambda pair: math.dist(*pair))
            if 20 < math.hypot(a[0]-b[0],a[2]-b[2]) < 22:
                p = mean((a,b))
                if not any(math.hypot(p[0]-q[0],p[2]-q[2]) < .1 for q in stations):
                    stations.append(p)
    return (sorted((p for p in stations if p[0] < -2580),key=lambda p:p[0])+
            sorted((p for p in stations if p[0] >= -2580),key=lambda p:-p[1]))


def heading_change(centers, old, destination):
    """Largest heading change over 10 m, sampled every metre in XZ.

    Follow serialized cut centres uphill, then shipped transverse floor
    midpoints through node 8754. The overlap's lateral offset is retained.
    """
    def nearest(p):
        found = []
        for i, (a,b) in enumerate(zip(old,old[1:])):
            d = sub(b,a)
            f = max(0.,min(1.,((p[0]-a[0])*d[0]+(p[2]-a[2])*d[2])/(d[0]**2+d[2]**2)))
            q = add(a,tuple(f*v for v in d))
            found.append((math.hypot(p[0]-q[0],p[2]-q[2]),i,f))
        return min(found)
    _, first, _ = nearest(centers[-1])
    _, last, _ = nearest(destination)
    points = centers+old[first+1:last+1]+[destination]
    lengths = [0.]
    for a,b in zip(points,points[1:]):
        lengths.append(lengths[-1]+math.hypot(b[0]-a[0],b[2]-a[2]))
    sampled, i = [], 0
    for distance in range(math.floor(lengths[-1])+1):
        while i < len(points)-2 and lengths[i+1] < distance:
            i += 1
        f = (distance-lengths[i])/(lengths[i+1]-lengths[i])
        sampled.append(tuple(points[i][k]+f*(points[i+1][k]-points[i][k]) for k in range(3)))
    headings = [math.degrees(math.atan2(b[2]-a[2],b[0]-a[0])) for a,b in zip(sampled,sampled[1:])]
    return max(abs((a-b+180)%360-180) for a,b in zip(headings,headings[10:]))


def measure(index, stream, baseline_index, baseline_stream):
    """Acceptance measurements from final serialized rows, articles and grid cells."""
    import c1_world as w
    roots, before = inventory(index, stream), inventory(baseline_index, baseline_stream)
    _, source_row, original_solid, local, high, low, _ = geometry(before)
    def scene(rs, number):
        return w.scene_data(next(r for r in rs[number] if r.kind == w.SCENE))
    actual = scene(roots, 366)
    count = len(scene(before, 366).instances)//96
    rows = [actual.instances[i*96:(i+1)*96] for i in range(count, count+COUNT)]
    hs, ls = serialized_cuts(before, rows)
    wanted = ((-3090., 103.468, 5443.059), (-3114.004, 104.061, 5445.943))
    require(max(math.dist(a, b) for a, b in zip((ls[-1][0], ls[-1][-1]), wanted)) <= .02,
            'link bottom cut differs from fixed map')
    world, base = w.ground.World(index, stream), w.ground.World(baseline_index, baseline_stream)
    new_keys = world.packs.keys()-base.packs.keys()
    require(len(new_keys) == 1, 'link pack count differs')
    key = next(iter(new_keys))
    require(key == min(set(range(1, 2700))-base.packs.keys()), 'link pack is not lowest free')
    pack = world.packs[key]
    require(len(pack.instances) == sum(map(len, collision_ids()))*64 and
            len(pack.articles) == len(pack.instances)//64, 'link pack arrays differ')
    fs = [[f for j in ids for f in pack.faces(j)] for ids in collision_ids()]
    old_top = [f for i in (24, 25, 26, 27, 28, 29) for f in base.packs[134].faces(i)]
    old_bottom = [f for i in (0, 7, 8, 12) for f in base.packs[220].faces(i)]
    joins = dict(top=join(hs[0], fs[0], old_top, True),
                 bottom=join(ls[-1], fs[-1], old_bottom, False))
    for name,cut,instance,top in (('bottom',ls[-1],collision_ids()[-1][0],False),):
        a,b = cut[0],cut[-1]
        normal = unit((b[2]-a[2],0.,a[0]-b[0]))
        if (top and normal[2]<0) or (not top and normal[2]>0):
            normal = tuple(-v for v in normal)
        holes = missing_ref = 0
        for i in range(129):
            p = tuple(a[k]+(b[k]-a[k])*i/128 for k in range(3))
            outside = add(p,tuple(v*.15 for v in normal))
            hit = base.find_face_below(outside[0],outside[2],p[1]+1.)
            holes += hit is None or not 0 <= p[1]+1.-hit.height <= 2.
            if 0<i<128:
                inside = sub(p,tuple(v*.15 for v in normal))
                missing_ref += (key<<16 | instance) not in world.references(inside[0],inside[2])
        joins[name].update(outside_world_misses=holes,inside_reference_misses=missing_ref)
        require(holes == missing_ref == 0, f'link {name} grid lookup failed')
    for name, result in (('bottom', joins['bottom']),):
        require(result['covered'] == 10 and result['outside_misses'] == 0 and
                result['inside_misses'] == 0 and result['step_samples'] == 127 and
                result['max_step'] <= .10 and result['overlap'][0] <= .127,
                f'link {name} join failed: {result}')
    seams = render_seams(hs, ls)
    require(seams['failed'] == 0, f'link render seams failed: {seams}')
    from ground import Face
    placements = layout(before, base.nodes[1534])
    oracle = []
    for kind, m, t in placements:
        source_pack, ids = (base.packs[1512], (8,)) if kind == 'S' else (base.packs[1508], (3, 4))
        oracle.append([Face(tuple(add(mv(m,v),t) for v in f.vertices), 0, 0, 0, 0, 0)
                       for j in ids for f in source_pack.faces(j)])
    cseams = collision_seams(fs, hs, ls, oracle)
    require(cseams['failed'] == cseams['unexplained_misses'] == 0, f'link collision seams failed: {cseams}')
    centers = [mean(cut) for cut in hs]+[mean(ls[-1])]
    ground = ground_samples(world, centers)
    require(ground['misses'] == 0, f'link ground failed: {ground}')
    # Reread mesh vertices against the one prescribed affine x rigid map.
    placements = layout(before, base.nodes[1534])
    donors = {'S': geometry(before), 'C': curve_geometry(before)}
    bake_error = render_error = 0.
    pitches = []
    from ground import Face
    rendered = []
    for i, (kind, m, t) in enumerate(placements):
        donor = donors[kind]
        source_row, local = donor[1], donor[3]
        stations = []
        for vertex in sorted(set(v for tri in local for v in tri),
                             key=lambda v: physics(v, source_row)[1]):
            if not stations or physics(vertex, source_row)[1]-physics(stations[-1][0], source_row)[1] > .01:
                stations.append([])
            stations[-1].append(vertex)
        station_centers = [mean([physics(v, rows[i]) for v in group]) for group in stations]
        def pitch(a, b):
            direction = sub(b, a)
            return math.degrees(math.atan2(direction[1], math.hypot(direction[0], direction[2])))
        pitches.append((pitch(*station_centers[:2]), pitch(*station_centers[-2:])))
        source_pack, source_ids = (base.packs[1512], (8,)) if kind == 'S' else (base.packs[1508], (3, 4))
        source_faces = [f for j in source_ids for f in source_pack.faces(j)]
        require(len(fs[i]) == len(source_faces) == (72 if kind == 'S' else 126), 'link face topology differs')
        for a, b in zip(fs[i], source_faces):
            require((a.strip, a.triangle, a.flags, a.two_sided) ==
                    (b.strip, b.triangle, b.flags, b.two_sided), 'link face attributes differ')
            bake_error = max(bake_error, *(math.dist(v, add(mv(m, p), t))
                                          for v, p in zip(a.vertices, b.vertices)))
        render_error = max(render_error, *(math.dist(physics(v, rows[i]), add(mv(m, physics(v, source_row)), t))
                                          for tri in local for v in tri))
        rendered.append([Face(tuple(physics(v, rows[i]) for v in tri), 0, 0, 0, 0, 0) for tri in local])
        lo, hi = bounds([render(physics(v, rows[i])) for tri in local for v in tri])
        require(all(abs(a-b) < .001 for a, b in zip((*lo, *hi),
                    (*struct.unpack_from('<3f', rows[i]), *struct.unpack_from('<3f', rows[i],16)))),
                'mapped scenery bounds differ')
        for j, source_id in zip(collision_ids()[i], source_ids):
            article = pack.articles[j]
            row = pack.instances[j*64:(j+1)*64]
            require(row[16:20] == bytes(4) and row[24:26] == bytes(2) and row[28:32] == bytes(4)
                    and struct.unpack_from('<H',row,26)[0] == j, 'link collision instance metadata differs')
            center = tuple(-v for v in struct.unpack_from('<3f',row,48))
            extent = tuple(struct.unpack_from('<f',row,p)[0] for p in (12,20,44))
            require(all(abs(v[k]-center[k]) <= extent[k] for face in pack.faces(j) for v in face.vertices for k in range(3)),
                    'link instance box excludes baked vertices')
            radius = struct.unpack_from('<f',row,60)[0]
            require(0 <= radius-math.hypot(extent[0],extent[2]) < .0001, 'link instance radius not rounded upward')
            source_article = source_pack.articles[source_id]
            require(article[:16] == source_article[:16] and len(article) == len(source_article), 'link article header differs')
            for strip in range(struct.unpack_from('<H', article)[0]):
                p = 16+16*strip
                start = 16+struct.unpack_from('<H', article, p+14)[0]
                count = struct.unpack_from('<H', article, start+6)[0]
                radius = struct.unpack_from('<H', article, p+12)[0]/16
                require(all(math.hypot(*struct.unpack_from('<3h', article, start+8*k)[0::2])/128 <= radius
                            for k in range(count)), 'link strip radius too small')
                require(all(article[start+8*k+6:start+8*k+8] == source_article[start+8*k+6:start+8*k+8]
                            for k in range(count)), 'link strip attributes differ')
    require(bake_error <= .01 and render_error <= .002, 'link mapped vertex error')
    raw = collision_body(one(index.parts, w.MAP))
    counts, arrays, ns, ss, _ = roads._reader(raw)
    require(counts == dict(nodes=9023, segments=12366, profiles=1524, roads=2148), 'link graph counts differ')
    require(reachable(ns, ss), 'link graph path absent')
    require(not reachable(ns, ss, (12363,12364,12365)), 'link graph control still reaches bottom')
    node_error = max(math.dist(n[:3], c) for n, c in zip(ns[8988:], centers))
    require(node_error < .001, 'link graph node positions differ')
    table = w.vis.read(w.vis.payload_of(index))
    sizes = {s.number: s.size for s in index.sections}
    all_rows = {row.number: sum(sizes.get(n, 0) for n in set(row.entries)|{2400,2600} if n != 2500)
                for row in table.rows}
    worst = max((size,number) for number,size in all_rows.items())
    require(worst[0] <= w.POOL_BYTES, 'link resident addition exceeds another row pool')
    row_bytes = {n:all_rows[n] for n in (326,220)}
    require(len(row_bytes) == 2 and max(row_bytes.values()) <= w.POOL_BYTES, 'link rows exceed pool')
    shadow = w.scene_data(next(r for r in roots[366] if r.kind == w.SCENE and w.scene_data(r).number == 326))
    r1_instances = sum(u32(shadow.models, struct.unpack_from('<h', shadow.instances, p+84)[0]*72+24) == 0x534ae112
                       for p in range(0, len(shadow.instances), 96))
    require(r1_instances == 0 and len(shadow.instances)//96 == 428, 'link R1 overhang removal differs')
    # Each complete donor retains its own resident texture references.
    resident = {k for root in roots[2500] if root.kind == 0xb3300000
                for k, _ in struct.iter_unpack('<2I', one(children(one(children(root),0xb3310000)),0x33310002).payload)}
    refs = set()
    for donor in donors.values():
        donor_refs = {v[0] for v in struct.iter_unpack('<2I', one(children(donor[2]), 0x134012).payload)}
        require(len(donor_refs) == 12 and donor_refs <= resident, 'link textures not resident')
        refs.update(donor_refs)
    pitch_changes = [pitches[i][0]-pitches[i+1][1] for i in range(COUNT-1)]
    end_triangles = [sum(rendered[:2], []), sum(rendered[-2:], [])]
    overlap = max((abs(nf.height(x,z)-ef.height(x,z)), x, z)
                  for piece in rendered for nf in piece for ef in old_top
                  for x,z in intersection(nf,ef)
                  if nf.height(x,z) is not None and ef.height(x,z) is not None)
    mixed = next(i for i in range(COUNT-2,-1,-1) if piece_kinds()[i] == 'C' and piece_kinds()[i+1] == 'S')
    profile = [(abs(a[0]-b[0]), abs(a[1]-b[1]), abs(a[2]-b[2]))
               for a,b in zip(ls[mixed],hs[mixed+1])]
    crossline = sub(hs[0][-1], hs[0][0])
    bank = math.degrees(math.atan2(crossline[1], math.hypot(crossline[0],crossline[2])))
    names = {solid_key(s): aligned_payload(one(children(s),0x134011))[160:].split(b'\0')[0].decode('ascii','replace')
             for n in (220,366) for s in solids(before[n])}
    scenery = dict(top=scenery_in_way(scene(before,366), end_triangles[0], names),
                   bottom=scenery_in_way(scene(before,220), end_triangles[1], names, DROP))
    return dict(joins=joins, bake_max=bake_error, render_max=render_error, render_seams=seams,
                collision_seams=cseams, ground=ground, scenery=scenery, pack_id=key,
                pack_bytes=len(grid.read_city(index,stream).packs[key]), rows=row_bytes,
                r1_instances=r1_instances, scene326_instances=len(shadow.instances)//96,
                graph=counts, graph_node_max=node_error, cells=len(world.cells), textures=len(refs),
                worst_row=worst[1], worst_row_bytes=worst[0],
                heading_10m=heading_change([*reversed(centers)], old_road_centers(base), base.nodes[8754]),
                overlap_max=overlap, floor_overlap=floor_overlap(sum(fs, []),
                    [f for i in (24,25,26,27,28,29) for f in world.packs[134].faces(i)]),
                mixed_profile=profile, hinges=(*UPSTREAM_HINGES, *TAIL_HINGES),
                max_hinge=max(map(abs, (*UPSTREAM_HINGES, *TAIL_HINGES))),
                max_pitch_change=max(map(abs, pitch_changes)), pitch_changes=pitch_changes, end_bank=bank)


def check_delta(index, stream, base, base_stream):
    """Prove every archive difference is one of this road's explicit edits.

    The reference pair is independently rebuilt from original archives by the
    existing merger with this feature omitted. No proof sidecar is trusted.
    Geometry checks below read the actual new rows and articles separately.
    """
    import c1_world as w
    from merge import read_section
    aroots, broots = inventory(index, stream), inventory(base, base_stream)
    road = w.scene_data(next(r for r in aroots[366] if r.kind == w.SCENE and w.scene_data(r).number == 366))
    cut = leg_cut(broots, road.instances[23*96:24*96])
    rail = next(solid for section in base.sections if section.number == 2100
                for solid in solids(list(chunks(read_section(base_stream,section)))) if solid_key(solid) == RAIL)
    expected_render = without_reflections(tidy_render(broots[366],cut,rail))
    shadow = w.scene_data(next(r for r in broots[366] if r.kind == w.SCENE and w.scene_data(r).number == 326))
    _, rail_path = rail_rows(shadow,cut,rail)
    require([s.number for s in index.sections] == [s.number for s in base.sections], 'link section set differs')
    position = 0
    for a, b in zip(index.sections, base.sections):
        position = (position+2047)//2048*2048
        require(a.offset == position and a.size == u32(a.raw,28), 'link section alignment/extent differs')
        position += a.size
        require(a.raw[:20]+a.raw[32:] == b.raw[:20]+b.raw[32:], 'link record metadata differs')
        if a.number == 193:
            require(read_section(stream,a) == b''.join(r.encode() for r in without_reflections(broots[193])),
                    'link reflection scenery removal differs')
        elif a.number not in (220, 366, 2600):
            require(read_section(stream,a) == read_section(base_stream,b), f'link changed unrelated section {a.number}')
    require(position == stream.stat().st_size, 'link stream tail differs')
    def scene(roots, n):
        return w.scene_data(next(r for r in roots[n] if r.kind == w.SCENE and w.scene_data(r).number == n))
    original_source, _, donor, _, _, _, model = geometry(broots)
    curve = curve_geometry(broots)
    for number in (220, 366):
        a, b = scene(aroots, number), scene(broots, number)
        w._check_scene_tree(a)
        require(a.header == b.header and a.precull == b.precull, 'link scenery header/precull changed')
        if number == 220:
            ids = [i for i in range(len(b.instances)//96) if i not in DROP]
            require(a.instances == b''.join(b.instances[i*96:(i+1)*96] for i in ids) and a.models == b.models,
                    'link scenery removal differs')
            require([c.kind for c in a.extras] == [c.kind for c in b.extras], 'link scenery sidecar set differs')
            for ac, bc in zip(a.extras, b.extras):
                if bc.kind == 0x3410d:
                    require(ac.payload == b''.join(bc.payload[i*32:(i+1)*32] for i in ids), 'link sidecar removal differs')
                elif bc.kind == 0x34106:
                    expected = []
                    for oid, instance in struct.iter_unpack('<2H', bc.payload):
                        if instance not in DROP:
                            expected.append((oid, instance-sum(d < instance for d in DROP)))
                    require(list(struct.iter_unpack('<2H', ac.payload)) == expected, 'link local overrides differ')
                else:
                    require(False, 'link sidecar not decoded')
        else:
            require(a.instances[:len(b.instances)] == b.instances and len(a.instances) == len(b.instances)+(COUNT+1)*96,
                    'link scene prefix/count differs')
            require(a.models == b.models+model+curve[6] and a.extras == b.extras, 'link model/sidecar differs')
            require(b.precull[:128] == bytes(128), 'link zero precull selector differs')
            pond = bytearray(b.instances[22*96:23*96])
            for offset in (0, 16, 32):
                struct.pack_into('<f', pond, offset, struct.unpack_from('<f', pond, offset)[0]-512.)
            require(a.instances[-96:] == pond, 'link pond copy differs')
            for p in range(len(b.instances), len(a.instances)-96, 96):
                row = a.instances[p:p+96]
                require(struct.unpack_from('<h', row, 84)[0] == len(b.models)//72+(piece_kinds()[(p-len(b.instances))//96] == 'C') and
                        struct.unpack_from('<h', row,28)[0] == 0 and row[88:96] == bytes(8), 'link instance selectors differ')
        def unchanged(roots):
            return [r for r in roots[number] if r.kind and
                    not (r.kind == w.SCENE and w.scene_data(r).number == number) and
                    not (number == 220 and r.kind == 0x34027)]
        unchanged_a, unchanged_b = unchanged(aroots), unchanged(broots)
        if number == 366:
            unchanged_b = unchanged({**broots, 366: expected_render})
        if number == 366:
            extra = unchanged_a.pop()
            require(extra.kind == 0x80134000, 'link solid-list absent')
            content = [c for c in children(extra) if c.kind]
            require([c.kind for c in content] == [0x80134001,0x80134010,0x80134010], 'link solid-list children differ')
            for copied, source_solid in zip(content[1:], (donor, curve[2])):
                require(copied.payload == source_solid.payload and (copied.offset-source_solid.offset) % 128 == 0,
                        'link copied solid bytes/alignment differ')
            hparts = children(content[0])
            require(u32(one(hparts,0x134002).payload,12) == 2 and
                    one(hparts,0x134003).payload == struct.pack('<4I', SOLID,0,CURVE,0) and
                    one(hparts,0x80134008).payload == b'', 'link solid directory differs')
        require([(r.kind,r.payload) for r in unchanged_a] == [(r.kind,r.payload) for r in unchanged_b],
                'link changed unrelated scene providers')
    # Physics spawns have an independent override reference, not a ci selector.
    before = aligned_payload(one(broots[220],0x34027))
    after = aligned_payload(one(aroots[220],0x34027))
    global_overrides = one(base.parts,0x34108).payload
    retained,removed = [],[]
    for p in range(16,len(before),64):
        row = before[p:p+64]
        override = u32(row,40)
        section,instance = struct.unpack_from('<2H',global_overrides,6*override)
        (removed if section == 220 and instance in DROP else retained).append(row)
    require(len(removed) == 1 and u32(removed[0],40) == 18842, 'link removed physics identity differs')
    require(after[:10]+after[12:16] == before[:10]+before[12:16] and
            struct.unpack_from('<H',after,10)[0] == len(retained) and after[16:] == b''.join(retained),
            'link physics spawn removal differs')
    actual_city, base_city = grid.read_city(index,stream), grid.read_city(base,base_stream)
    road_scene = scene(aroots, 366)
    road_rows = [road_scene.instances[i*96:(i+1)*96] for i in range(23,23+COUNT)]
    top_cuts, _ = serialized_cuts(broots, road_rows)
    added = actual_city.packs.keys()-base_city.packs.keys()
    require(len(added) == 1 and all(actual_city.packs[k] ==
            (open_bottom_pack(v,bottom_cut(index,stream)) if k == 220 else
             tidy_collision(open_route_pack(v,w.ground.road_nodes(index),top_cuts[1]),cut,rail_path) if k == 134 else
             open_route_pack(v,w.ground.road_nodes(index),top_cuts[1]) if k == 192 else v)
            for k,v in base_city.packs.items()),
            'link changed old collision packs')
    key = next(iter(added))
    newpack = Pack(actual_city.packs[key])
    require(actual_city.descriptor == base_city.descriptor and actual_city.rectangles == base_city.rectangles,
            'link collision lattice differs')
    bmap = {struct.unpack_from('<H',r,4)[0]:r for r in base_city.cells}
    amap = {struct.unpack_from('<H',r,4)[0]:r for r in actual_city.cells}
    additions = {}
    origin, spacing, rows, columns = grid.grid_fields(actual_city.descriptor)
    for i in range(len(newpack.instances)//64):
        vs = [v for f in newpack.faces(i) for v in f.vertices]
        # Integer cell containment independent of the cell editor's iteration.
        xs = [math.floor((v[0]-origin[0])/spacing) for v in vs]
        zs = [math.floor((v[2]-origin[2])/spacing) for v in vs]
        for r in range(min(zs),max(zs)+1):
            for c in range(min(xs),max(xs)+1):
                additions.setdefault(r*columns+c, []).append(key<<16 | i)
    require(amap.keys() == bmap.keys() | additions.keys(), 'link cell coverage differs')
    for cid, a in amap.items():
        b = bmap.get(cid)
        before = [[v[0] for v in struct.iter_unpack('<I',f)] for f in grid.families(b)] if b else [[],[],[],[]]
        after = [[v[0] for v in struct.iter_unpack('<I',f)] for f in grid.families(a)]
        require(a[:4] == (b[:4] if b else bytes(4)) and struct.unpack_from('<HH',a,4) == (cid,2600),
                'link cell prefix/owner differs')
        require(after == [before[0]+additions.get(cid,[]),*before[1:]], 'link cell references differ')
    def other_resident(roots):
        return [(r.kind,r.payload) for r in roots[2600] if r.kind not in (0,w.TILE) and
                not (r.kind == w.PACK and u32(collision_body(r),4) in (key,220,134,192))]
    require(other_resident(aroots) == other_resident(broots), 'link changed resident providers')
    require([p.kind for p in index.parts if p.kind] == [p.kind for p in base.parts if p.kind], 'link global scaffold differs')
    for a,b in zip([p for p in index.parts if p.kind], [p for p in base.parts if p.kind]):
        if a.kind in (w.MAP,0x34110,0):
            continue
        if a.kind == w.vis.CONTAINER:
            require(a.payload == panorama_visibility(b.payload), 'link panorama visibility differs')
        elif a.kind == 0x34108:
            expected = bytearray(b.payload)
            for p in range(0,len(expected)//6*6,6):
                section,instance = struct.unpack_from('<2h',expected,p)
                if section == 220:
                    if instance in DROP:
                        struct.pack_into('<2h',expected,p,0,0)
                    else:
                        struct.pack_into('<h',expected,p+2,instance-sum(d<instance for d in DROP))
            require(a.payload == expected, 'link global overrides differ')
        else:
            require(a.payload == b.payload, 'link changed unrelated global chunk')
    raw, old = collision_body(one(index.parts,w.MAP)), collision_body(one(base.parts,w.MAP))
    _,aa,ns,ss,at = roads._reader(raw)
    _,ba,bns,bss,bt = roads._reader(old)
    start = min(t[3] for t in bt.values() if t[2])
    prefix = bytearray(raw[:start])
    for k,(p,_,_,_) in at.items():
        prefix[p:p+16] = old[p:p+16]
    require(prefix == old[:start], 'link changed non-road map bytes')
    for i in range(8988):
        a,b = aa[roads.NODES][i*32:(i+1)*32],ba[roads.NODES][i*32:(i+1)*32]
        if i in (8754,1534,4454,4455):
            restored = bytearray(a)
            degree = b[16]
            sid = {8754:12328,1534:12363,4454:12364,4455:12365}[i]
            require(a[16] == degree+1 and struct.unpack_from('<H',a,18+2*degree)[0] == sid,
                    'link old connector adjacency differs')
            restored[16] = b[16]
            restored[18+2*degree:20+2*degree] = b[18+2*degree:20+2*degree]
            a = bytes(restored)
        require(a == b, 'link changed old graph node')
    for i in range(12328):
        a,b = aa[roads.SEGMENTS][i*22:(i+1)*22],ba[roads.SEGMENTS][i*22:(i+1)*22]
        expected = bytearray(b)
        if 11695 <= i <= 11709:
            struct.pack_into('<H',expected,10,struct.unpack_from('<H',b,10)[0] & ~0x40)
        require(a == expected, 'link changed old graph segment')
    require(aa[roads.PROFILES] == ba[roads.PROFILES] and aa[roads.ROADS] == ba[roads.ROADS],
            'link changed old road/profile arrays')
    for i,n in enumerate(ns[8988:]):
        adjacent = (12362,12363,12364,12365) if i == 34 else (12328+i,12329+i)
        require(n[4:7] == (907,len(adjacent),0xaa) and n[7:7+len(adjacent)] == adjacent
                and n[7+len(adjacent):] == (0xaaaa,)*(7-len(adjacent)),
                'link new node profile/adjacency differs')
    edges = [(8754,8988),*((i,i+1) for i in range(8988,9022)),
             (9022,1534),(9022,4454),(9022,4455)]
    for sid,(a,b) in enumerate(edges,12328):
        s = ss[sid]
        require(s[:2] == (a,b) and s[3:6] == ((-1,sid,0x103) if sid >= 12363 else (989,sid,0x102)), 'link added segment fields differ')
        require(s[2] == round(math.dist(ns[a][:3],ns[b][:3])*65535/1000), 'link segment length differs')
        direction = unit(sub(ns[b][:3],ns[a][:3]))
        handle = round(math.dist(ns[a][:3],ns[b][:3])/3*65535/500)
        require(s[6:8] == (handle,handle) and s[8:] ==
                tuple(round(v*127) for v in (*(-v for v in direction),*direction)), 'link spline controls differ')
    tile = collision_body(one(aroots[2600],w.TILE))
    component = grid.Grid(actual_city.descriptor,struct.pack('<5H',*actual_city.rectangles[0]),
                          tile,tuple(actual_city.packs.values()),{},{})
    grid_report = grid.check(component,cell_section=2600,tile_section=2600,segment_limit=12366)
    return dict(new_cells=len(amap.keys()-bmap.keys()), touched_cells=len(additions),
                new_references=sum(len(v) for v in additions.values()),
                tile_bytes=len(tile), grid=grid_report)


def project_base(tracks, index, stream, carbon_root, mw_root):
    """Rebuild the ordinary reference independently from the source archives.

    check_delta compares every output field against this reference, including
    the clipped provider meshes; no removed road fragment is restored by guess.
    """
    import c1_world as w
    carbon, _, _ = w.load_index(carbon_root, 'L5RA')
    # Match the input mode before the exact-delta comparison. Keeping zone
    # kinds in that comparison proves their full source-built bytes as well.
    actual = w.zone_tables.select(index)
    native = w.zone_tables.select(carbon)
    zones = [(c.kind,c.payload) for c in actual] != [(c.kind,c.payload) for c in native]
    w._write_pair(mw_root, carbon_root, tracks.parent, zones=zones,
                  shift=SHIFT, _link=False)


def check(directory, mw_root, carbon_root):
    """Retain all existing provenance checks, then verify the exact road delta."""
    import hashlib
    import tempfile
    import c1_world as w
    from merge import load_index
    tracks = Path(directory)/'TRACKS'
    index,stream,raw_index = load_index(tracks,'L5RA')
    require(index.encode() == raw_index, 'link written index round trip differs')
    with tempfile.TemporaryDirectory(prefix='.c3-link-base-',dir=Path(directory).parent) as tmp:
        stage = Path(tmp)
        project_base(stage/'TRACKS',index,stream,carbon_root,mw_root)
        report = w.check(stage,mw_root,carbon_root,shift=SHIFT,_link=False)
        base,base_stream,_ = load_index(stage/'TRACKS','L5RA')
        delta = check_delta(index,stream,base,base_stream)
        measured = measure(index,stream,base,base_stream)
    report['link'] = {**measured,**delta}
    report['roads'] = dict(counts=measured['graph'],reference_errors=0,duplicate_ids=0,
                           bridge_segments=35,road_id=989,connector_segments=3,nodes=[8988,9022],segments=[12328,12365],
                           profile=907,flags=0x102,route=True,without_bottom_connector=False,
                           base_provenance=report['roads'])
    report['grid'].update(delta['grid'],occupied=measured['cells'],tile_bytes=delta['tile_bytes'],
                           pack_margin=2699-delta['grid']['packs'])
    report['visibility'].update(worst_row=measured['worst_row'],worst_row_bytes=measured['worst_row_bytes'],
                                row_byte_margin=w.POOL_BYTES-measured['worst_row_bytes'])
    report['palmont_bytes'] = dict(base_provenance=report['palmont_bytes'],
                                  link_delta_verified=True,changed_records=[193,220,366,2600])
    report['unverified'] += ['affine surface appearance, walls and live driving']
    report['files'] = {}
    for path in (tracks/'L5RA.BUN',stream):
        digest = hashlib.sha256()
        with path.open('rb') as f:
            for block in iter(lambda:f.read(4<<20),b''):
                digest.update(block)
        report['files'][path.name] = dict(bytes=path.stat().st_size,sha256=digest.hexdigest())
    return report


def clip_sweep(poly, fn):
    out=[]
    for a,b in zip(poly,poly[1:]+poly[:1]):
        va,vb=fn(a),fn(b)
        if va>=-1e-8:out.append(a)
        if (va<0)!=(vb<0):out.append(tuple(a[k]+(b[k]-a[k])*va/(va-vb) for k in range(3)))
    return out

def sweep_prism(tri,a,b,width=1.):
    dx,dz=b[0]-a[0],b[2]-a[2]; length=math.hypot(dx,dz)
    dx,dz=dx/length,dz/length; slope=(b[1]-a[1])/length
    def along(v):return (v[0]-a[0])*dx+(v[2]-a[2])*dz
    def side(v):return (v[0]-a[0])*dz-(v[2]-a[2])*dx
    def up(v):return v[1]-a[1]-slope*along(v)
    p=list(tri)
    for f in (along,lambda v:length-along(v),lambda v:width-side(v),lambda v:width+side(v),lambda v:up(v)-.3,lambda v:1.5-up(v)):
        p=clip_sweep(p,f)
        if not p:return []
    return p

def sweep(index, stream):
    """Grounded native splines, continuous 2 x 1.2 m prisms, bottom +0.3 m.

    The fixed route includes both original bridge approaches. Render solids
    are reported separately: a mesh hit alone does not prove an active body.
    Ground is sampled at <=1 m along splines, then each prism is clipped
    continuously, including vertical triangles and edge-only intersections.
    """
    import ground as g
    import visibility as vis
    import c1_world as w
    from merge import read_section
    idx,st=index,stream
    world=g.World(idx,st)
    ids=[9022,*range(9021,8987,-1),8754,*range(8753,8738,-1)]
    dist=0
    footprints=[]
    _,_,_,segments,_=roads._reader(collision_body(one(idx.parts,w.MAP)))
    pairs={frozenset(s[:2]):s for s in segments}
    expanded=[]
    for na,nb in zip(ids,ids[1:]):
        s=pairs[frozenset((na,nb))];a=world.nodes[s[0]];b=world.nodes[s[1]]
        p1=add(a,tuple(v/127*s[7]*500/65535 for v in s[11:14]))
        p2=add(b,tuple(v/127*s[6]*500/65535 for v in s[8:11]))
        footprints.append(bounds((a,p1,p2,b)))
        n=math.ceil(math.dist(a,p1)+math.dist(p1,p2)+math.dist(p2,b))
        pts=[tuple((1-t)**3*a[k]+3*(1-t)**2*t*p1[k]+3*(1-t)*t*t*p2[k]+t**3*b[k] for k in range(3)) for t in (j/n for j in range(n+1))]
        grounded=[]
        for p in pts:
            fs=[f for ref in world.references(p[0],p[2]) for f in world.faces(ref)]
            hs=[h for f in fs if (h:=f.height(p[0],p[2])) is not None and abs(h-p[1])<10]
            y=min(hs,key=lambda h:abs(h-p[1])) if hs else p[1]
            grounded.append((p[0],y,p[2]))
        pts=grounded
        if na!=s[0]:pts.reverse()
        for aa,bb in zip(pts,pts[1:]):
            expanded.append((aa,bb,dist,na,nb));dist+=math.dist(aa,bb)
    bins={}
    for leg in expanded:
        a,b,*_=leg
        for x in range(math.floor((min(a[0],b[0])-1.01)/16),math.floor((max(a[0],b[0])+1.01)/16)+1):
            for z in range(math.floor((min(a[2],b[2])-1.01)/16),math.floor((max(a[2],b[2])+1.01)/16)+1):bins.setdefault((x,z),[]).append(leg)
    table=vis.read(vis.payload_of(idx));rows={r.number:r for r in table.rows}
    zone_ids=set()
    for boundary in table.boundaries:
        # A cubic stays inside its control-point box. The polygon fan is a
        # conservative row superset for concave rings; geometry is always
        # clipped to the narrow spline corridor below, never to these boxes.
        vertices=[(-p[1],0,p[0]) for p in boundary.vertices]
        blo,bhi=bounds(vertices)
        for lo,hi in footprints:
            if any(bhi[k] < lo[k]-1 or blo[k] > hi[k]+1 for k in (0,2)):
                continue
            corners=[(x,0,z) for x,z in ((lo[0]-1,lo[2]-1),(hi[0]+1,lo[2]-1),
                                        (hi[0]+1,hi[2]+1),(lo[0]-1,hi[2]+1))]
            rect=[g.Face(tuple(corners[i] for i in t),0,0,0,0,0)
                  for t in ((0,1,2),(0,2,3))]
            if any(intersection(g.Face((vertices[0],vertices[j],vertices[j+1]),0,0,0,0,0),r)
                   for j in range(1,len(vertices)-1) for r in rect):
                zone_ids.add(boundary.number)
                break
    loaded={2400,2500,2600}|{n for z in zone_ids if z in rows for n in rows[z].entries}
    roots={s.number:list(chunks(read_section(st,s))) for s in idx.sections if s.number in loaded}
    models={solid_key(s):s for rs in roots.values() for s in solids(rs)}
    hits=[]; candidates=[]
    def test(tri,meta):
        lo,hi=bounds(tri)
        seen=set()
        x0,x1,z0,z1=math.floor(lo[0]/16),math.floor(hi[0]/16),math.floor(lo[2]/16),math.floor(hi[2]/16)
        candidates=[leg for (x,z),ls in bins.items() if x0<=x<=x1 and z0<=z<=z1 for leg in ls]
        for a,b,start,na,nb in candidates:
            if start in seen:continue
            seen.add(start)
            if any(hi[k]<min(a[k],b[k])-margin or lo[k]>max(a[k],b[k])+margin for k,margin in ((0,1.01),(2,1.01),(1,2))):continue
            poly=sweep_prism(tri,a,b)
            if poly:
                p=mean(poly);d=start+math.dist(a,p)
                hits.append(dict(meta,leg=[na,nb],metres=round(d,3),point=p));return
    for section,rs in roots.items():
        for root in rs:
            if root.kind==w.PACK:
                pack=g.Pack(collision_body(root))
                for i in range(len(pack.instances)//64):
                    row=pack.instances[i*64:(i+1)*64];aid=struct.unpack_from('<H',row,26)[0];article=pack.articles[aid];trans=struct.unpack_from('<3f',row,48)
                    for f in pack.faces(i):test(f.vertices,dict(kind='face',section=section,pack=pack.key,instance=i,article=aid,strip=f.strip,triangle=f.triangle))
                    ns,_,ne=struct.unpack_from('<3H',article)
                    for e in range(ne):
                        off=16+struct.unpack_from('<H',article,2)[0]+32*e
                        a=tuple(v-t for v,t in zip(struct.unpack_from('<3f',article,off),trans));b=tuple(v-t for v,t in zip(struct.unpack_from('<3f',article,off+16),trans))
                        vertices=((a[0],a[1],a[2]),(b[0],a[1],b[2]),(b[0],b[1],b[2]),(a[0],b[1],a[2]))
                        for t in ((0,1,2),(0,2,3)):test(tuple(vertices[j] for j in t),dict(kind='barrier',section=section,pack=pack.key,instance=i,article=aid,edge=e))
            elif root.kind==w.SCENE:
                scene=w.scene_data(root)
                for i in range(len(scene.instances)//96):
                    row=scene.instances[i*96:(i+1)*96];mi=struct.unpack_from('<h',row,84)[0];data=scene.models[mi*72:(mi+1)*72];key=u32(data,24)
                    lo=struct.unpack_from('<3f',row);hi=struct.unpack_from('<3f',row,16)
                    plo=(-hi[1],lo[2],lo[0]);phi=(-lo[1],hi[2],hi[0])
                    if not any(x*16 <= phi[0] and (x+1)*16 >= plo[0] and z*16 <= phi[2] and (z+1)*16 >= plo[2] for x,z in bins):continue
                    name= aligned_payload(one(children(models[key]),0x134011))[160:].split(b'\0')[0].decode('ascii','replace') if key in models else data[:22].split(b'\0')[0].decode('ascii','replace')
                    if key not in models:candidates.append((section,i,name,'no solid'));continue
                    try:tris=mesh(models[key])
                    except Exception as e:candidates.append((section,i,name,str(e)));continue
                    for t in tris:test(tuple(physics(v,row) for v in t),dict(kind='solid',section=section,scene=scene.number,instance=i,name=name,key=f'{key:08x}'))
    unique={tuple((k,str(v)) for k,v in h.items() if k not in ('point','metres','leg')):h for h in reversed(hits)}
    result=dict(zones=sorted(zone_ids),sections=sorted(loaded),path=ids,length=sum(math.dist(a,b) for a,b,*_ in expanded),hits=list(unique.values()),undecoded=candidates)
    # The two bottom copies, not an arbitrary distance cutoff. Keep every
    # upper-join/approach hit in the full inventory even when this is clear.
    result['bottom_hits']=[h for h in result['hits']
                           if h['leg'] in ([9022,9021],[9021,9020])]
    return result
