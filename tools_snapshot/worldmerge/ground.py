"""Read-only collision-face oracle in physics XYZ (Y is height).

Plan: decode CARP directories and grid references, reconstruct strip faces and
instance transforms, then measure retail road nodes and failure controls.
This is a geometric oracle: it unions streamed tiles, ignores scene activation
and materials, and does not synthesize faces from collision boxes or roads.
It cannot prove that the game has loaded a tile/pack or that a car can drive it.

Examples (redirect reports only into worktree scratch):
  ground.py TRACKS --base L2RA --point -160 2912 --point -86 2970
  ground.py TRACKS --base L5RA --road-nodes --summary
  ground.py TRACKS --base L2RA --road-nodes nodes.csv
CSV rows are physics x,y,z, optionally headed x,y,z; JSON is an array of XYZ
arrays or objects with x/y/z fields. A BUN road-node input uses its RNgp array.
Point queries default to an unbounded ceiling; --below sets a finite ceiling.
"""
import argparse
from collections import Counter
import csv
from dataclasses import asdict, dataclass
from functools import cached_property
import json
import math
from pathlib import Path
import struct
import sys

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(HERE))
from formats import FormatError, TrackIndex, chunks, require, u32
from merge import load_index, read_section
from region import collision_body, collision_cells, collision_tags


def unpack(fmt, raw, offset=0):
    require(0 <= offset <= len(raw) - struct.calcsize(fmt), 'truncated collision record')
    return struct.unpack_from(fmt, raw, offset)


def finite(values):
    require(all(math.isfinite(v) for v in values), 'nonfinite collision coordinate')
    return values


def tag_bytes(raw, tag):
    _, flags, count, offset = tag
    size = flags >> 8
    require(count > 0 and 0 <= offset <= len(raw) - size, 'collision tag extent')
    return raw[offset:offset + size]


def cross(a, b):
    return (a[1]*b[2] - a[2]*b[1], a[2]*b[0] - a[0]*b[2], a[0]*b[1] - a[1]*b[0])


def dot(a, b):
    return sum(x*y for x, y in zip(a, b))


@dataclass(frozen=True)
class Face:
    vertices: tuple
    pack: int
    instance: int
    strip: int
    triangle: int
    flags: int
    two_sided: bool = True

    def height(self, x, z):
        """Projected triangle test with shared edges and native strip sidedness."""
        a, b, c = self.vertices
        ux, uz, vx, vz = b[0]-a[0], b[2]-a[2], c[0]-a[0], c[2]-a[2]
        det = ux*vz - uz*vx
        if abs(det) < 1e-12 or (not self.two_sided and det > 0):
            return None  # Vertical, degenerate, or the back of a one-sided strip.
        dx, dz = x-a[0], z-a[2]
        u, v = (dx*vz-dz*vx)/det, (ux*dz-uz*dx)/det
        if u < -1e-8 or v < -1e-8 or u+v > 1+1e-8:
            return None
        return a[1] + u*(b[1]-a[1]) + v*(c[1]-a[1])


@dataclass(frozen=True)
class Hit:
    height: float
    face: Face
    cell: int


class Pack:
    """Serialized pointers are ignored; article ids resolve through CARP tags."""
    def __init__(self, raw):
        require(u32(raw) == len(raw)-16, 'collision pack size')
        self.key = u32(raw, 4)
        require(0 < self.key < 2700, 'collision pack id out of range')
        body = raw[16:]
        tags = collision_tags(body, 0x41727469)
        ci = tags[0x63690000]
        self.instances = tag_bytes(body, ci)
        require(len(self.instances) == 64*ci[2], 'collision instance stride')
        self.articles = {k & 0xffff: tag_bytes(body, v) for k, v in tags.items()
                         if k >> 16 == 0x6361 and v[2]}

    def faces(self, instance):
        raw = self.instances
        require(0 <= instance < len(raw)//64, 'collision instance index')
        p = instance*64
        f = finite(unpack('<3f', raw, p))
        g = finite(unpack('<3f', raw, p+32))
        flags, article = unpack('<H', raw, p+18)[0], unpack('<H', raw, p+26)[0]
        # Carbon 00813290 emits centre+s16/128-T, ignoring the basis that
        # 007FC360 uses. Only identity, unflagged rows agree on both paths.
        require(f == (1., 0., 0.) and g == (0., 0., 1.) and flags == 0,
                'nonidentity or flagged collision instance unsupported by triangle cache')
        translation = finite(unpack('<3f', raw, p+48))
        require(article in self.articles, 'collision article id unresolved')
        a = self.articles[article]
        nstrips = unpack('<H', a)[0]
        require(16+16*nstrips <= len(a), 'collision strip spheres truncated')
        for strip in range(nstrips):
            sphere = 16+16*strip
            center = finite(unpack('<3f', a, sphere))
            # Offsets are relative to article+16, NOT the sphere itself.
            start = 16+unpack('<H', a, sphere+14)[0]
            count = unpack('<H', a, start+6)[0]
            require(count >= 3 and start >= 16+16*nstrips and start+8*count <= len(a),
                    'collision strip vertices outside article')
            strip_flags = unpack('<H', a, start+14)[0]
            vertices = []
            for j in range(count):
                v = unpack('<3h', a, start+8*j)
                local = tuple(v[k]/128.+center[k]-translation[k] for k in range(3))
                vertices.append(local)
            for tri in range(count-2):
                attr = unpack('<H', a, start+8*(tri+2)+6)[0]
                if attr & 0x0800:
                    continue  # Native MakeNextFace's disabled triangle flag.
                ids = (tri, tri+1, tri+2)
                if bool(strip_flags & 1) ^ bool(tri & 1):
                    ids = (tri+1, tri, tri+2)
                yield Face(tuple(vertices[j] for j in ids), self.key, instance, strip, tri,
                           attr, bool(strip_flags & 2))


def road_nodes(index):
    top = [c for c in index.parts if c.kind == 0x3b800]
    require(len(top) == 1, 'road world map missing/duplicate')
    raw = collision_body(top[0])
    tag = collision_tags(raw, 0x524e6770)[0x524e6e64]
    data = tag_bytes(raw, tag)
    require(len(data) == 32*tag[2], 'road node stride')
    nodes = []
    for i in range(tag[2]):
        xyz = finite(unpack('<3f', data, 32*i))
        require(unpack('<H', data, 32*i+12)[0] == i, 'road node self index')
        nodes.append(xyz)
    return nodes


class World:
    """All source tiles, indexed by global cell id; queries never scan other cells.

    Overlapping tiles contribute the union of their references. Pass section to
    find_face_below to restrict a query to one Carbon tile's region. Missing
    referenced packs/articles are errors, rather than silently returning void.
    """
    def __init__(self, index, stream):
        self.index = index
        top = [c for c in index.parts if c.kind == 0x3b800]
        require(len(top) == 1, 'collision map missing/duplicate')
        raw = collision_body(top[0])
        tags = collision_tags(raw, 0x43446174)
        desc = tag_bytes(raw, tags[0x43477264])
        require(len(desc) in (36, 40), 'collision grid descriptor stride')
        self.origin = finite(unpack('<3f', desc))
        self.cell_size = finite(unpack('<f', desc, 16))[0]
        self.rows, self.columns = unpack('<2I', desc, 24)
        require(self.cell_size > 0 and 0 < self.rows*self.columns <= 65536,
                'collision grid dimensions')
        self.cells, self.packs, self._faces = {}, {}, {}
        self.rectangles = []
        for key, t in tags.items():
            if key >> 16 != 0x636c:
                continue
            data = tag_bytes(raw, t)
            require(len(data) == 10*t[2], 'collision rectangle stride')
            self.rectangles.extend(struct.iter_unpack('<5H', data))
        if 0x4347636e in tags:
            self._add_cells(collision_cells(raw, tags[0x4347636e]))
        for s in index.sections:
            for c in chunks(read_section(stream, s)):
                if c.kind == 0x3b801:
                    pack = Pack(collision_body(c))
                    require(pack.key not in self.packs, 'duplicate collision pack')
                    self.packs[pack.key] = pack
                elif c.kind == 0x3b802:
                    tile = collision_body(c)
                    require(u32(tile) == len(tile)-16, 'collision tile size')
                    section = u32(tile, 4)
                    b = tile[16:]
                    self._add_cells(collision_cells(b, collision_tags(b, 0x41727469)[0x4347636e]), section)
        for entries in self.cells.values():
            for refs in entries.values():
                for ref in refs:
                    key, inst = ref >> 16, ref & 0xffff
                    require(key in self.packs and inst < len(self.packs[key].instances)//64,
                            'grid collision reference unresolved')

    @classmethod
    def load(cls, tracks, base):
        index, stream, _ = load_index(tracks, base)
        return cls(index, stream)

    def _add_cells(self, cells, section=None):
        for c in cells:
            cid, region = unpack('<HH', c, 4)
            require(cid < self.rows*self.columns, 'cell id outside grid')
            if section is not None:
                row, col = divmod(cid, self.columns)
                require(region == section, 'tile/cell region mismatch')
                require(any(s in (section, 65535) and r <= row < r+h and x <= col < x+w
                            for s, r, x, w, h in self.rectangles), 'cell outside tile rectangle')
            entries = self.cells.setdefault(cid, {})
            require(region not in entries, 'duplicate cell in collision region')
            entries[region] = tuple(unpack('<I', c, p)[0] for p in range(20, 20+4*c[8], 4))

    def cell_id(self, x, z):
        finite((x, z))
        col = math.floor((x-self.origin[0])/self.cell_size)
        row = math.floor((z-self.origin[2])/self.cell_size)
        return row*self.columns+col if 0 <= row < self.rows and 0 <= col < self.columns else None

    def references(self, x, z, section=None):
        entries = self.cells.get(self.cell_id(x, z), {})
        return sorted({r for s, refs in entries.items() if section is None or s == section for r in refs})

    def faces(self, ref):
        if ref not in self._faces:
            self._faces[ref] = tuple(self.packs[ref >> 16].faces(ref & 0xffff))
        return self._faces[ref]

    def find_face_below(self, x, z, below=math.inf, *, section=None):
        require(not math.isnan(below), 'NaN query ceiling')
        best = None
        for ref in self.references(x, z, section):
            for face in self.faces(ref):
                height = face.height(x, z)
                if height is not None and height <= below and (best is None or height > best.height):
                    best = Hit(height, face, self.cell_id(x, z))
        return best

    def height(self, x, z, below=math.inf, *, section=None):
        hit = self.find_face_below(x, z, below, section=section)
        return hit.height if hit else None

    @cached_property
    def nodes(self):
        return road_nodes(self.index)


def measure_nodes(world, nodes=None):
    """Literal 0 <= node Y - face Y <= 2 m; no hidden ceiling epsilon.

    Authored road nodes can be microscopically below a face. Classify those
    separately, including when strict lookup instead hits a much lower layer.
    near_surface_1mm is supplementary, not added to the strict grounded count.
    """
    records, counts = [], Counter()
    near_surface = 0
    for i, (x, y, z) in enumerate(world.nodes if nodes is None else nodes):
        finite((x, y, z))
        hit = world.find_face_below(x, z, y)
        gap = y-hit.height if hit else None
        nearby = world.find_face_below(x, z, y+.001)
        if nearby and -.001 <= y-nearby.height <= 2.:
            near_surface += 1
        if gap is not None and gap <= 2.:
            cause = 'grounded'
        elif nearby and y < nearby.height <= y+.001:
            cause = 'surface_above_node_within_1mm'
        elif gap is not None:
            cause = 'face_more_than_2m_below'
        elif not world.cells.get(world.cell_id(x, z)):
            cause = 'no_grid_cell'
        elif world.height(x, z) is not None:
            cause = 'faces_only_above_node'
        else:
            cause = 'no_projected_face'
        counts[cause] += 1
        record = dict(node=i, x=x, y=y, z=z, height=hit.height if hit else None,
                      gap=gap, cause=cause, cell=world.cell_id(x, z),
                      near_height=nearby.height if nearby else None)
        if hit:
            record['face'] = {k: v for k, v in asdict(hit.face).items() if k != 'vertices'}
        records.append(record)
    grounded = counts['grounded']
    return dict(total=len(records), grounded=grounded,
                share=grounded/len(records) if records else 0., tolerance=2.,
                near_surface_1mm=near_surface,
                classes=dict(sorted(counts.items())), records=records)


def read_nodes(path):
    path = Path(path)
    require(path.stat().st_size <= 8 << 20, 'road node input exceeds size budget')
    if path.suffix.lower() == '.bun':
        return road_nodes(TrackIndex(path.read_bytes()))
    if path.suffix.lower() == '.json':
        rows = json.loads(path.read_text())
        nodes = [tuple(float(r[k]) for k in ('x', 'y', 'z')) if isinstance(r, dict)
                 else tuple(float(v) for v in r) for r in rows]
        require(all(len(r) == 3 for r in nodes), 'expected physics x,y,z road nodes')
        return [finite(r) for r in nodes]
    with path.open(newline='') as f:
        rows = list(csv.reader(f))
    if rows and [s.strip().lower() for s in rows[0]] == ['x', 'y', 'z']:
        rows = rows[1:]
    require(all(len(r) == 3 for r in rows), 'expected physics x,y,z road nodes')
    return [finite(tuple(float(v) for v in r)) for r in rows]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('tracks', type=Path)
    parser.add_argument('--base', required=True, help='track basename, e.g. L2RA or L5RA')
    parser.add_argument('--point', nargs=2, type=float, action='append', metavar=('X', 'Z'))
    parser.add_argument('--below', type=float, default=math.inf)
    parser.add_argument('--road-nodes', nargs='?', const='', metavar='FILE')
    parser.add_argument('--summary', action='store_true', help='omit individual road-node records')
    args = parser.parse_args(argv)
    try:
        require(args.point or args.road_nodes is not None, 'supply --point or --road-nodes')
        world = World.load(args.tracks, args.base)
        for x, z in args.point or []:
            print(json.dumps(dict(x=x, z=z, height=world.height(x, z, args.below))))
        if args.road_nodes is not None:
            report = measure_nodes(world, read_nodes(args.road_nodes) if args.road_nodes else None)
            if not args.summary:
                for record in report['records']:
                    print(json.dumps(record))
            print(json.dumps({k: v for k, v in report.items() if k != 'records'}))
    except (OSError, ValueError, KeyError, struct.error) as exc:
        print(f'FAIL: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
