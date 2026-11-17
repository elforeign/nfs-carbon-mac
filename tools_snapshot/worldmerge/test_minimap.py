"""Offline minimap proof: baseline 0 target Rockport tiles -> 512/512 valid.

Native round trips: locked 287104 and unlocked 287232 bytes, byte equal.
Good source/target: 64/64 source tiles; 512/512 full-name target hashes;
RGBA mean absolute error <4/255; 20 spread road nodes, require >=16/20 hits.
Broken controls: row/column transpose (240/256 wrong vs good 0/256);
truncated display hashes (266/512 correct vs good 512/512); missing tile
(255 vs 256); unflipped by (v error >0.1 vs <1e-6); block extent
(1 byte beyond file vs 0). All five must fail check(), not just a helper.
Native stream regression: old first destination 0 decodes 32768/65684 bytes,
record hash absent; corrected order decodes 65684/65684, record hash present.
Old serialization fails the native terminator check; stock identity is pinned.
Synthetic checks run without private inputs, then exit 3.
"""
from contextlib import contextmanager
import json
import hashlib
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(HERE))
import minimap as m
import ground
from merge import DEFAULT_MW, DEFAULT_CARBON, load_index
from formats import FormatError

try:
    SOURCE, TARGETS = m.inputs(DEFAULT_MW, DEFAULT_CARBON)
    ASSETS = all(p.is_file() for p in [SOURCE, *TARGETS, DEFAULT_MW/'L2RA.BUN', DEFAULT_MW/'STREAML2RA.BUN'])
except FileNotFoundError:
    ASSETS = False
# The combined pair is an offline build; the connecting road is drawn only where one is present.
WORLD = next((p for p in (HERE.parents[1]/'recomp/out'/name/'TRACKS' for name in ('c3load-overlay', 'c3route-open'))
              if (p/'L5RA.BUN').is_file()), None)


@contextmanager
def changed_file(path, raw):
    before = path.read_bytes()
    path.write_bytes(raw)
    try:
        yield
    finally:
        path.write_bytes(before)


class SyntheticTests(unittest.TestCase):
    def test_known_full_name_hashes(self):
        self.assertEqual(m.name_hash('MINI_MAP_CASINOTOWN_UNLOCKED_CHOP0'), 0x53593d3a)
        self.assertEqual(m.name_hash('MINI_MAP_CASINOTOWN_LOCKED_CHOP100'), 0x150eeed8)
        for base in m.BASES:
            self.assertEqual(len({m.name_hash(m.tile_name(base, i)) for i in range(256)}), 256)

    def test_native_destination_and_relative_spans(self):
        blob = bytes(range(256))*256 + bytes(range(148))
        raw = m.stream_entry(blob)
        pos, copied, spans = 0, bytearray(len(blob)), []
        while pos < len(raw):
            magic, size, stored, dst, rel, zero = struct.unpack_from('<6I', raw, pos)
            self.assertEqual((magic, rel, zero), (0x55441122, pos, 0))
            self.assertLessEqual(size, 32768)
            self.assertEqual(raw[pos+24:pos+32], b'JDLZ\x02\x10\0\0')
            copied[dst:dst+size] = m.xt.jdlz(raw[pos+24:pos+stored])
            spans.append((dst, size))
            pos += stored
        self.assertEqual(spans, [(32768, 32768), (65536, 148), (0, 32768)])
        self.assertEqual(copied, blob)
        self.assertLessEqual(len(raw), len(blob))

    def test_jdlz_both_match_forms_and_flag_refills(self):
        import random
        rng = random.Random(17)
        for blob in (b'x'*32768, bytes(range(256))*128,
                     rng.randbytes(32768), b'ab', b'x'*100+b'abcde'*200):
            encoded = m.jdlz_encode(blob)
            self.assertEqual(m.xt.jdlz(encoded), blob)
            m.native_jdlz_extent(encoded)

    def test_missing_native_terminal_flag_rejected(self):
        encoded = m.jdlz_encode(b'abcdefgh')  # Eight literals exhaust token flags.
        m.native_jdlz_extent(encoded)
        raw = bytearray(encoded[:-1])
        struct.pack_into('<I',raw,12,len(raw))
        # Output-size-only readers accept the broken envelope.
        self.assertEqual(m.xt.jdlz(bytes(raw)),b'abcdefgh')
        with self.assertRaisesRegex(FormatError,'terminal flag refill'):
            m.native_jdlz_extent(raw)

    def test_old_first_destination_value_rejected(self):
        blob = bytes(range(256))*256 + bytes(range(148))
        raw = bytearray(m.stream_entry(blob))
        struct.pack_into('<I', raw, 12, 0)  # Original writer's first destination.
        with self.assertRaisesRegex(FormatError, 'zero-destination terminator'):
            m.native_stream(raw, (0, 0, len(raw), len(blob), 512, 0))

    def test_in_place_allocation_and_live_source_rejected(self):
        blob = bytes(range(256))*256 + bytes(range(148))
        raw = bytearray(m.stream_entry(blob))
        with self.assertRaisesRegex(FormatError, 'allocation overflow'):
            m.native_stream(raw, (0, 0, len(raw), len(raw)-1, 512, 0))
        struct.pack_into('<I', raw, 12, 4)
        with self.assertRaisesRegex(FormatError, 'live-input overlap'):
            m.native_stream(raw, (0, 0, len(raw), len(blob), 512, 0))

    def test_projection_and_float32_constants(self):
        self.assertAlmostEqual(m.f32(1/m.ROCKPORT[2]), .000150165215018, places=15)
        self.assertAlmostEqual(m.f32(1/m.SHARED[2]), .0000476371933473, places=16)
        self.assertEqual(m.WORLD_SHIFT, (0., 8192.))
        for calibration, shift, expected in ((m.ROCKPORT, (0., 0.), (.6212168932, .7370389700, 185)),
                (m.SHARED, (0., 8192.), (.8767149064, .6592987932, 174))):
            actual = m.project(m.EXAMPLE, calibration, shift)
            self.assertAlmostEqual(actual['u'], expected[0], places=6)
            self.assertAlmostEqual(actual['v'], expected[1], places=6)
            self.assertEqual(actual['tile'], expected[2])
        with self.assertRaisesRegex(FormatError, 'outside atlas'):
            m.project((1e8, 0, 0), m.ROCKPORT)

    def test_output_must_be_external(self):
        with self.assertRaisesRegex(FormatError, 'outside every checkout'):
            m.safe_output(HERE/'output', ())
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaisesRegex(FormatError, 'outside input trees'):
                m.safe_output(Path(root)/'out', (root,))
            game = Path(root)/'game'
            (game/'TRACKS').mkdir(parents=True)
            with self.assertRaisesRegex(FormatError, 'outside input trees'):
                m.safe_output(game/'export', (game/'TRACKS',))

    def test_missing_inputs_exit_three_without_output(self):
        with tempfile.TemporaryDirectory() as root:
            out = Path(root)/'out'
            result = subprocess.run([sys.executable, '-I', str(HERE/'minimap.py'),
                '--mw', str(Path(root)/'absent-mw'), '--carbon', str(Path(root)/'absent-carbon'), '--out', str(out)],
                capture_output=True, text=True)
            self.assertEqual(result.returncode, 3, result.stderr)
            self.assertFalse(out.exists())

    def test_shared_pixel_centres(self):
        # Independent world positions of three coloured source pixels. A transpose
        # or a shift along X instead of physics Z puts these in the wrong regions.
        native = Image.new('RGBA', (160, 160), (0, 0, 0, 255))
        rock = Image.new('RGBA', (64, 64), (0, 0, 0, 255))
        for image, colour in ((native, (255, 0, 0, 255)), (rock, (0, 255, 0, 255))):
            for y in range(20, 44):
                for x in range(20, 44):
                    image.putpixel((x, y), colour)
        canvas = m.composite(native, rock)
        for image, cal, dz, channel in ((native, m.PALMONT, 0, 0), (rock, m.ROCKPORT, 8192, 1)):
            source_x, source_y = 31.5/image.width, 31.5/image.height
            z = cal[0] + source_x*cal[2]+dz
            x = (source_y-1)*cal[2]-cal[1]
            u, v = (z+7300)/20992, (14000+x)/20992
            self.assertGreater(canvas.getpixel((int(u*4096), int(v*4096)))[channel], 240)


@unittest.skipUnless(ASSETS, 'private minimap inputs absent')
class PrivateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='minimap-proof-')
        cls.addClassCleanup(cls.temp.cleanup)
        cls.root = Path(cls.temp.name)
        cls.packs = [m.read_stock(p, b) for p, b in zip(TARGETS, m.BASES)]
        cls.source = m.source_canvas(SOURCE)
        cls.results = {}
        for layout in ('rockport', 'shared'):
            cls.results[layout] = m.convert(DEFAULT_MW, DEFAULT_CARBON, cls.root/layout, layout, WORLD)

    def pack_path(self, base=m.BASES[0], layout='rockport'):
        return self.root/layout/'TRACKS'/m.REGION[layout]/(base+'.bin')

    def test_source_and_stock_roundtrip(self):
        self.assertEqual(self.source.size, (1024, 1024))
        self.assertEqual([len(p.raw) for p in self.packs], [287104, 287232])
        for pack, sha in zip(self.packs, (
                'd75e494c945bcbdf83db53ef105ddfc4c73676b597a0f0e69a82659b0213f5b9',
                '2bee7f1a3d4ca6ef53d79ce9ae5b855ba931ed9557eb578f79642760f7ab2d39')):
            self.assertEqual(m.write_pack(pack), pack.raw)
            self.assertEqual(hashlib.sha256(m.write_pack(pack)).hexdigest(), sha)
            tiles = m.checked_pack(m.write_pack(pack), pack.base)
            self.assertEqual(len(tiles), 256)
            for i, pixels in tiles.items():
                self.assertEqual(pixels, pack.blobs[m.name_hash(m.tile_name(pack.base, i))][:65536])
        print('SOURCE 64/64; HASH 512/512; ROUNDTRIP 287104/287232 byte-equal')

    def test_output_child_symlink_cannot_escape(self):
        out, other = self.root/'symlink-export', self.root/'outside-export'
        out.mkdir()
        other.mkdir()
        (out/'TRACKS').symlink_to(other, target_is_directory=True)
        with self.assertRaisesRegex(FormatError, 'child escapes export tree'):
            m.convert(DEFAULT_MW, DEFAULT_CARBON, out)
        self.assertEqual(list(other.iterdir()), [])

    def test_written_canvas_error_and_projection(self):
        for layout, result in self.results.items():
            self.assertEqual(sum(p['tiles'] for p in result['packs'].values()), 512)
            for base, pack in result['packs'].items():
                self.assertLess(max(pack['mae_rgba']), 4)
                print(f'{layout} {base}: RGBA MAE={pack["mae_rgba"]}')
            print(f'{layout} projections: {result["examples"]}')

    def test_twenty_spread_road_nodes(self):
        nodes = ground.road_nodes(load_index(DEFAULT_MW, 'L2RA')[0])
        # No brightness-based selection: inclusive, uniform indices over all nodes.
        ids = [i*(len(nodes)-1)//19 for i in range(20)]
        for layout in ('rockport', 'shared'):
            cal, shift = (m.ROCKPORT, (0, 0)) if layout == 'rockport' else (m.SHARED, (0, 8192))
            canvas = np.asarray(m.decoded_canvas(m.checked_pack(self.pack_path(layout=layout).read_bytes(), m.BASES[0])))
            brightness = canvas[:, :, :3].astype(np.float32).mean(2)
            median = float(np.median(brightness))
            hits = 0
            for i in ids:
                x, _, z = nodes[i]
                # Direct world -> atlas, independent of m.project().
                u = (z+shift[1]-cal[0])/cal[2]
                v = 1+(cal[1]+x+shift[0])/cal[2]
                hits += float(brightness[int(v*4096), int(u*4096)]) > median
            self.assertGreaterEqual(hits, 16)
            print(f'{layout} roads: {hits}/20 brighter than median {median:.6f}; node count={len(nodes)}')

    def test_palmont_region_error(self):
        for pack in self.packs:
            native = m.stock_canvas(pack)
            # Native left/top coincide with the shared left/top; its 16 km side
            # occupies 3121.95 pixels. Compare at that region's resolution, up
            # to the column where Rockport's square begins.
            side = round(16000*4096/20992)
            edge = int((m.ROCKPORT[0]+8192+7300)/20992*4096)
            native_small = np.asarray(native.resize((side, side), Image.Resampling.BILINEAR)).astype(np.int16)[:, :edge]
            canvas = m.decoded_canvas(m.checked_pack(self.pack_path(pack.base, 'shared').read_bytes(), pack.base))
            region = np.asarray(canvas.crop((0, 0, edge, side))).astype(np.int16)
            error = np.abs(region-native_small).mean((0, 1)).tolist()
            self.assertLess(max(error), 4)
            print(f'shared {pack.base} Palmont {edge}x{side} region MAE={error}')

    def test_three_world_points_on_a_road(self):
        # Physics (X, Z): the Palmont end of the connecting road (graph node
        # 9022), its middle (node 9005), and the Rockport road 713 m before the
        # old bridge. Stock map with stock constants: 1 of 3. With no combined
        # pair to draw the road from, the middle point is left out (1 of 2).
        points = ((-3102.0, 5444.5), (-2862.0, 6085.0), (-3001.7, 7827.2))[::1 if WORLD else 2]
        hud = HERE.parents[1]/'recomp/private_runtime/carbon_minimap.h'
        cal = m.SHARED
        if hud.is_file():  # the row the game applies in atlas mode
            row = hud.read_text().split('carbon_minimap_calibration[] = {')[1].split('},')[1]
            bx, by, k = (float.fromhex(v.strip(' {\n').rstrip('f')) for v in row.split(','))
            cal = (bx, by, 1/k)

        def on_road(canvas, cal):
            hits = 0
            for x, z in points:
                u, v = (z-cal[0])/cal[2], 1+(cal[1]+x)/cal[2]
                hits += 0 <= u < 1 and 0 <= v < 1 and max(canvas.getpixel((int(u*4096), int(v*4096)))[:3]) > 100
            return hits
        stock = on_road(m.stock_canvas(self.packs[0]), m.PALMONT)
        merged = on_road(m.decoded_canvas(m.checked_pack(self.pack_path(layout='shared').read_bytes(), m.BASES[0])), cal)
        print(f'world points on a road: merged atlas {merged}/{len(points)}, stock map {stock}/{len(points)}')
        self.assertEqual((stock, merged), (1, len(points)))

    def test_broken_transposed_rows_columns(self):
        path = self.pack_path()
        pack = m.read_stock(path, m.BASES[0])
        original = m.checked_pack(path.read_bytes(), pack.base)
        transposed = {m.name_hash(m.tile_name(pack.base, i)): original[(i%16)*16+i//16] for i in range(256)}
        wrong = sum(transposed[m.name_hash(m.tile_name(pack.base, i))] != original[i] for i in range(256))
        self.assertGreater(wrong, 0)
        with changed_file(path, m.write_pack(pack, transposed)):
            with self.assertRaisesRegex(FormatError, 'tile spatial witness'):
                m.check(self.root/'rockport')
        print(f'BROKEN transpose: {wrong}/256 tile witnesses differ; check rejected (good 0/256)')

    def test_broken_truncated_display_hashes(self):
        matches = []
        for pack in self.packs:
            matches.extend(m.name_hash(blob[-59:-24].split(b'\0')[0].decode('ascii')) == hs for hs, blob in pack.blobs.items())
        self.assertEqual(sum(matches), 266)
        path = self.pack_path(m.BASES[1])
        pack = m.read_stock(path, m.BASES[1])
        raw = bytearray(path.read_bytes())
        for i, entry in enumerate(pack.entries):
            display = pack.blobs[entry[0]][-59:-24].split(b'\0')[0].decode('ascii')
            struct.pack_into('<I', raw, pack.index_offset+8+24*i, m.name_hash(display))
        with changed_file(path, raw):
            with self.assertRaisesRegex(FormatError, 'full-name hashes/order'):
                m.check(self.root/'rockport')
        print('BROKEN truncated names: 266/512 correct vs good 512/512; check rejected')

    def test_broken_missing_tile(self):
        path = self.pack_path()
        pack = m.read_stock(path, m.BASES[0])
        raw = bytearray(path.read_bytes())
        # Preserve parent extents with a zero-padding chunk in the vacated row.
        struct.pack_into('<I', raw, pack.index_offset+4, 255*24)
        raw[pack.index_offset+8+255*24:pack.index_offset+8+256*24] = struct.pack('<2I', 0, 16)+bytes(16)
        with changed_file(path, raw):
            with self.assertRaisesRegex(FormatError, 'tile count differs from 256'):
                m.check(self.root/'rockport')
        print('BROKEN missing tile: 255 vs good 256; check rejected')

    def test_broken_by_without_vertical_flip(self):
        path = self.root/'rockport'/'calibration.json'
        manifest = json.loads(path.read_text())
        hud = manifest['hud']
        correct = 1+(hud['by']-160)*hud['k']
        hud['by'] = manifest['world_map']['+B0']
        wrong = 1+(hud['by']-160)*hud['k']
        self.assertGreater(abs(wrong-correct), .1)
        with changed_file(path, json.dumps(manifest).encode()):
            with self.assertRaisesRegex(FormatError, 'vertical flip'):
                m.check(self.root/'rockport')
        print(f'BROKEN unflipped by: v error {abs(wrong-correct):.9f} vs good <1e-6; check rejected')

    def test_broken_block_extent_one_byte_past_file(self):
        path = self.pack_path()
        pack = m.read_stock(path, m.BASES[0])
        raw = bytearray(path.read_bytes())
        struct.pack_into('<I', raw, pack.index_offset+8+8, len(raw)-pack.entries[0][1]+1)
        with changed_file(path, raw):
            with self.assertRaisesRegex(FormatError, 'block extent'):
                m.check(self.root/'rockport')
        print('BROKEN block extent: file end +1 byte vs good +0; check rejected')

    def test_broken_stream_destination_overlap(self):
        path = self.pack_path()
        pack = m.read_stock(path, m.BASES[0])
        raw = bytearray(path.read_bytes())
        off = pack.entries[0][1]
        first_size = struct.unpack_from('<I', raw, off+8)[0]
        struct.pack_into('<I', raw, off+first_size+12, 32768)
        with changed_file(path, raw):
            with self.assertRaisesRegex(FormatError, 'destination hole/overlap'):
                m.check(self.root/'rockport')

    def test_broken_format(self):
        path = self.pack_path()
        pack = m.read_stock(path, m.BASES[0])
        hs = pack.entries[0][0]
        blob = bytearray(pack.blobs[hs])
        blob[-12:-8] = b'DXT1'
        pack.blobs[hs] = bytes(blob)
        pixels = {key: value[:m.PIXELS] for key, value in pack.blobs.items()}
        with changed_file(path, m.write_pack(pack, pixels)):
            with self.assertRaisesRegex(FormatError, 'tile format/mips'):
                m.check(self.root/'rockport')

    def test_broken_old_field_fails_full_export_check(self):
        path = self.pack_path()
        pack = m.read_stock(path, m.BASES[0])
        raw = bytearray(path.read_bytes())
        entry = next(e for e in pack.entries if e[0] == m.name_hash(m.tile_name(pack.base, 183)))
        struct.pack_into('<I', raw, entry[1]+12, 0)
        with changed_file(path, raw):
            with self.assertRaisesRegex(FormatError, 'zero-destination terminator'):
                m.check(self.root/'rockport')
        print('BROKEN old first-destination=0: full export rejected; good=32768')


if __name__ == '__main__':
    result = unittest.main(exit=False, verbosity=2).result
    sys.exit(1 if not result.wasSuccessful() else 0 if ASSETS else 3)
