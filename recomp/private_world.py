"""Manifest-driven private region diagnostic and hash-bound mode wrapper.

Instrument a copied private guest archive, never the source archive or an
installation. Image SHA and per-hook byte witnesses are mandatory. Generated
manifests, headers, guest C and rebuilt archives stay in ignored output.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from build_private import ignored_output
from private_render import function_span
import private_resolution
import private_audio

HOOKS = {'select': 1, 'request': 2, 'complete': 3, 'camera': 4,
         'position': 5, 'predict': 6, 'stream_ready': 7}
# Optional draw-path counters: section picker, scenery tree walk, instance draw.
DIAG_HOOKS = {'section_pick': 8, 'scenery_tree': 9, 'scenery_draw': 10, 'model_submit': 11, 'mesh_add': 12}
DIAG_HOOKS.update(prop_factory=13, prop_spawn=14, prop_position=15, prop_tick=16)
# Optional globals read by the draw-path diagnostic (0 when absent).
DIAG_GLOBALS = {'texture_sentinel_global': 'WORLD_TEXTURE_SENTINEL', 'mesh_count_global': 'WORLD_MESH_COUNT'}
ALL_HOOKS = {**HOOKS, **DIAG_HOOKS}

# Sample at the witnessed player streaming hooks. The predict argument itself
# is the camera position, so read the local car's rigid-body state instead.
POSITION_PROBE = r'''
extern uint64_t host_ticks(void);
extern void diag_event(const char *, ...);
extern int private_carbon_player_position(float *);
extern int diag_on;
extern void private_world_prop_player(const float *);
static void private_world_position_sample(Cpu *c) {
    static uint64_t last;
    if (!diag_on) return;
    uint8_t *const G = guest_base();
    uint32_t slot = M32(c->esp + 4);
    uint64_t now = host_ticks();
    if (slot) return;
    float position[3];
    if (!private_carbon_player_position(position)) return;
    private_world_prop_player(position);
    if (last && now - last < 1000000000ull) return;
    last = now;
    diag_event("PRIVATE WORLD POSITION time=%.6f render=%.6f,%.6f,%.6f source=player0",
               now / 1e9, position[0], position[1], position[2]);
}
'''


def validate_manifest(manifest, image):
    from recomp import PE
    if hashlib.sha256(image.read_bytes()).hexdigest() != manifest['sha256']:
        raise ValueError('world probe image SHA mismatch')
    pe = PE(str(image), expected_sha256=manifest['sha256'])
    if not set(HOOKS) <= set(manifest['hooks']) <= set(ALL_HOOKS):
        raise ValueError('world probe requires every lifecycle hook')
    addresses = []
    for name, row in manifest['hooks'].items():
        address = int(row['address'])
        witness = bytes.fromhex(row['bytes'])
        if len(witness) < 16 or pe.read(address, len(witness)) != witness:
            raise ValueError('world hook byte witness differs: ' + name)
        addresses.append(address)
    if len(set(addresses)) != len(addresses):
        raise ValueError('world hook addresses must be distinct')
    for key in ('track_global', 'descriptor_global', *(k for k in DIAG_GLOBALS if k in manifest)):
        address = manifest[key]
        if not any(name.rstrip(b'\0') == b'.data' and pe.base + va <= address < pe.base + va + vs - 4
                   for name, vs, va, _, _ in pe.sections):
            raise ValueError('world state address outside image data: ' + key)
    return manifest


def configuration(manifest, proof):
    if proof['track'] != 2000 or proof['region'] != 'L2RA' or proof['renumbered'] or any(proof['shift']):
        raise ValueError('world diagnostic requires native-coordinate L2RA proof')
    if any(proof['validation']['dependencies'].values()):
        raise ValueError('world diagnostic requires closed region dependencies')
    vectors = [proof['camera'][k] for k in ('render_eye', 'render_target')]
    if any(len(v) != 3 for v in vectors) or not all(math.isfinite(x) for v in vectors for x in v):
        raise ValueError('world camera vectors invalid')
    if sum((a - b)**2 for a, b in zip(vectors[0][:2], vectors[1][:2])) < .001:
        raise ValueError('world camera horizontal direction is degenerate')
    fields = {'WORLD_TRACK_GLOBAL': manifest['track_global'],
              'WORLD_DESCRIPTOR_GLOBAL': manifest['descriptor_global'],
              'WORLD_TRACK_OFFSET': manifest['track_offset'], 'WORLD_SECTION': proof['number'],
              **{name: manifest.get(key, 0) for key, name in DIAG_GLOBALS.items()}}
    result = '#pragma once\n#define PRIVATE_WORLD_CONFIGURED 1\n'
    result += ''.join(f'#define {key} {value}u\n' for key, value in fields.items())
    for name, key in [('world_eye', 'render_eye'), ('world_target', 'render_target')]:
        result += f'static const float {name}[3] = {{' + ','.join(format(float(v), '.9e') + 'f' for v in proof['camera'][key]) + '};\n'
    return result


def instrument(source, hooks):
    """Wrap only witnessed functions, leaving their translated bodies intact."""
    additions = []
    for name, row in hooks.items():
        symbol = f'f_{row["address"]:08X}'
        begin, end = function_span(source, symbol)
        declaration = source.rfind('void ', 0, begin)
        if declaration < 0 or symbol not in source[declaration:begin]:
            raise ValueError('world hook function declaration absent')
        old = source[declaration:end]
        rewritten = old.replace(symbol + '(', symbol + '_world_original(', 1)
        sample = '    private_world_position_sample(c);\n' if name in ('position', 'predict') else ''
        disabled = '!private_world_on || !diag_on' if name.startswith('prop_') else '!private_world_on'
        wrapper = f'''\nvoid {symbol}(Cpu *c) {{
    if ({disabled}) {{ {symbol}_world_original(c); return; }}
    uint32_t sp=c->esp, self=c->ecx;
{sample}    private_world_before(c, {ALL_HOOKS[name]});
    {symbol}_world_original(c);
    private_world_after(c, {ALL_HOOKS[name]}, sp, self);
}}'''
        source = source[:declaration] + rewritten + wrapper + source[end:]
        additions.append(name)
    return ('extern int private_world_on, diag_on;\n'
            'extern void private_world_before(Cpu *, unsigned);\n'
            'extern void private_world_after(Cpu *, unsigned, uint32_t, uint32_t);\n' +
            (POSITION_PROBE if any(n in hooks for n in ('position', 'predict')) else '') + source), additions


def prepare_archive(base, out, manifest_path, proof_path):
    out = ignored_output(out)
    image = json.loads((base / 'image.json').read_text())
    if manifest_path is None:
        from private_build_inputs import world_manifest
        manifest = world_manifest(Path(image['exe']))
    else:
        manifest = json.loads(manifest_path.read_text())
    manifest = validate_manifest(manifest, Path(image['exe']))
    private_audio.validate(image)
    # The release build has no diagnostic proof: the runtime then uses its inert default configuration.
    header = configuration(manifest, json.loads(proof_path.read_text())) if proof_path else None
    prefix = manifest.get('prefix', 'NFSC')
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', prefix):
        raise ValueError('invalid private archive prefix')
    if out == base.resolve():
        raise ValueError('use a separate private archive output')
    for name in ('image.json', 'imports.c', 'funcs.h', 'table.c'):
        shutil.copy2(base / name, out / name)
    archive = out / (prefix + '.a')
    archive.unlink(missing_ok=True)
    pending = out / (prefix + '.a.pending')
    shutil.copy2(base / (prefix + '.a'), pending)
    found = []
    resolution_found = []
    audio_found = []
    from recomp import CFLAGS
    objects = []
    for path in sorted(base.glob(prefix + '_*.c')):
        source = path.read_text()
        selected = {name: row for name, row in manifest['hooks'].items()
                    if re.search(r'void f_' + f'{row["address"]:08X}' + r'\(', source)}
        source, resolution_names = private_resolution.instrument(source, image['sha256'])
        source, audio_names = private_audio.instrument(source, image['sha256'])
        if not selected and not resolution_names and not audio_names: continue
        source, names = instrument(source, selected)
        dst = out / path.name
        # funcs.h supplies Cpu before the external hook declarations.
        dst.write_text('#include "funcs.h"\n' + source)
        obj = dst.with_suffix('.o')
        r = subprocess.run(['clang', '-c', *CFLAGS, '-frounding-math', '-I', str(HERE), '-I', str(out),
                            str(dst), '-o', str(obj)], capture_output=True, text=True)
        dst.with_suffix('.log').write_text(r.stdout + r.stderr)
        if r.returncode: raise RuntimeError(r.stderr[-1500:])
        objects.append(obj); found.extend(names); resolution_found.extend(resolution_names); audio_found.extend(audio_names)
    if sorted(found) != sorted(manifest['hooks']):
        raise ValueError('not all world hook bodies present in private translated sources')
    if image['sha256'] == private_resolution.CARBON_SHA256 and set(resolution_found) != set(private_resolution.HOOKS):
        raise ValueError('not all private resolution hook bodies present')
    if image['sha256'] == private_audio.CARBON_SHA256 and set(audio_found) != private_audio.HOOKS:
        raise ValueError('not all private audio hook bodies present')
    r = subprocess.run(['ar', 'r', str(pending), *map(str, objects)], capture_output=True, text=True)
    (out / 'world_archive.log').write_text(r.stdout + r.stderr)
    if r.returncode: raise RuntimeError(r.stderr[-1500:])
    config = out / 'world_config.h'
    config.unlink(missing_ok=True)
    if header: config.write_text(header)
    (out / 'world_manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    pending.replace(archive)
    (out / 'world_archive.json').write_text(json.dumps({
        'sha256': manifest['sha256'], 'hooks': sorted(found), 'resolution_hooks': sorted(resolution_found), 'audio_hooks': sorted(audio_found),
        'archive_sha256': hashlib.sha256(archive.read_bytes()).hexdigest(),
        'config_sha256': hashlib.sha256(header.encode()).hexdigest() if header else None}, indent=2) + '\n')
    print(f'PRIVATE WORLD ARCHIVE PASS hooks={len(found)} objects={len(objects)} archive={archive}')
    return archive


def verify_world(inventory):
    required = {'private_world_init', 'private_world_before', 'private_world_after',
                'private_world_active', 'private_world_scratch', 'private_world_matrix',
                'private_world_prop_before', 'private_world_prop_after', 'private_world_prop_player',
                'private_world_prop_target'}
    lost = required & {r['name'] for r in inventory['boot.c']}
    if lost: raise ValueError('world diagnostic quarantined: ' + ', '.join(sorted(lost)))


def check_log(text, section, camera=None):
    patterns = [r'PRIVATE WORLD SELECT track=2000', r'PRIVATE WORLD REGION track=2000',
                r'PRIVATE TRACK OPEN TRACKS/L2RA\.BUN status=ok', r'PRIVATE TRACK OPEN TRACKS/STREAML2RA\.BUN status=ok',
                rf'PRIVATE WORLD REQUEST track=2000 section={section} detail=full',
                rf'PRIVATE WORLD COMPLETE track=2000 section={section} status=[34]',
                rf'PRIVATE WORLD CAMERA track=2000 section={section} eye=([-+0-9.eE,]+) target=([-+0-9.eE,]+) height=geometry']
    matches = [re.search(p, text) for p in patterns]
    missing = [p for p, m in zip(patterns, matches) if m is None]
    if missing: raise ValueError('world proof log missing: ' + '; '.join(missing))
    values = [float(v) for group in matches[-1].groups() for v in group.split(',')]
    if len(values) != 6 or not all(math.isfinite(v) for v in values):
        raise ValueError('world camera coordinates invalid')
    if camera and any(abs(a - b) > .02 for a, b in zip(values, camera['render_eye'] + camera['render_target'])):
        raise ValueError('world camera differs from geometry proof')
    if (any(matches[0].start() >= m.start() for m in matches[1:]) or
        any(matches[i].start() >= matches[5].start() for i in (2, 3, 4)) or
        matches[5].start() >= matches[6].start()):
        raise ValueError('world proof lifecycle order differs')
    return len(patterns)


def height_summary(text):
    samples = [tuple(float(v) for v in m) for m in re.findall(
        r'PRIVATE WORLD POSITION time=([-+0-9.eE]+) render=([-+0-9.eE]+),([-+0-9.eE]+),([-+0-9.eE]+) source=player0', text)]
    if not samples: raise ValueError('no player position samples')
    if not all(math.isfinite(v) for s in samples for v in s): raise ValueError('nonfinite player position')
    if any(a[0] >= b[0] for a, b in zip(samples, samples[1:])): raise ValueError('position times unordered')
    end = samples[-1][0]
    window = [s for s in samples if s[0] >= end - 20]
    lo, hi = min(s[3] for s in window), max(s[3] for s in window)
    duration = end - window[0][0]
    if duration < 19 or len(window) < 20: raise ValueError('player height needs 20 seconds of samples')
    return {'min': lo, 'max': hi, 'span': hi - lo, 'samples': len(window), 'seconds': duration,
            'flat': hi - lo <= .5}


def load_ground_world(tracks, base):
    """Import the read-only collision oracle only for ground-check mode."""
    if not re.fullmatch(r'[A-Za-z0-9_]+', str(base)):
        raise ValueError('ground track base must be a name without a path or extension')
    sys.path.insert(0, str(HERE.parent / 'tools_snapshot/worldmerge'))
    from ground import World
    return World.load(tracks, str(base))


def ground_jumps(samples, lower, upper):
    """Classify bounded excursions using interval vertical velocities.

    The eleven recorded elevated samples give minimum interval deceleration
    4.976818 m/s^2 (about one fifth of the interior descent's 24.3 m/s^2).
    Round that minimum down to 4.9; round the longest bracket, 2.636546 s,
    up to 3 seconds. Compare velocities at interval midpoints, hence mean dt.
    Landing includes contact: the long descent changes from -19.289 to
    -6.306 m/s there. Compare intervals ending above the band; a single
    elevated sample needs its landing interval for a second velocity.

    Stepped terrain (recorded, 5 m terraces): the sample before the arc is in
    band at 3.726 m but still falling from the terrace above; the car lands
    and rolls off the next edge within one interval, so the first elevated
    sample sits 0.721 m over the terrace it left (5.334 m over the one below)
    and then falls 0.491 m in 0.203 s (23.8 m/s^2). Interval velocities
    -8.893, -2.416, -6.201 m/s: 2 samples failed the leading comparison and
    pass from the edge sample on. The same samples as a steady descent
    (-4.527, -4.047 m/s) still fail, 2 samples.
    """
    jumps, accepted = [], set()
    i = 0
    def grounded(s):
        return s['below'] and lower <= s['gap'] <= upper
    while i < len(samples):
        if samples[i]['gap'] is None or samples[i]['gap'] <= upper:
            i += 1
            continue
        start = i
        while i < len(samples) and samples[i]['gap'] is not None and samples[i]['gap'] > upper:
            i += 1
        if start == 0 or i == len(samples):
            continue
        arc = samples[start-1:i+1]
        if not grounded(arc[0]) or not grounded(arc[-1]) or not all(s['below'] for s in arc):
            continue
        intervals = [b['dt'] for b in arc[1:]]
        if any(dt is None or dt <= 0 for dt in intervals):
            continue
        duration = sum(intervals)
        if duration > 3.:
            continue
        velocities = [(b['y']-a['y']) / dt for a, b, dt in zip(arc, arc[1:], intervals)]
        def falling(v, d):
            return all(a-b >= 4.9 * (da+db)/2 for a, b, da, db in zip(v, v[1:], d, d[1:]))
        # The final contact interval is not another free-flight observation.
        count = max(2, i-start)
        passed = falling(velocities[:count], intervals[:count])
        # A first elevated sample still in band over the previous sample's
        # face has only just left that ledge. Its interval is ground travel,
        # which on stepped terrain holds the landing of the drop before, so
        # the flight starts after it and ends with the landing interval.
        if (not passed and i-start >= 2
                and lower <= arc[1]['y'] - arc[0]['face'] <= upper):
            passed = falling(velocities[1:], intervals[1:])
        if not passed:
            continue
        accepted.update(range(start, i))
        jumps.append(dict(time=samples[start]['time'],
                          peak=max(s['gap'] for s in samples[start:i]), seconds=duration))
    return jumps, accepted


def ground_summary(text, world, lower=0., upper=2., source='world', allow_jumps=False):
    """Check every player sample in physics XYZ.

    World-probe render XYZ converts to (-render.y, render.z, render.x).
    Autodrive logs rigid-body physics XYZ directly.

    Distance is the sum of horizontal sample chords, not the simulated odometer.
    The default band is provisional until calibrated on a stock driven trace.
    A projected face above the car is used only to diagnose a failed below query.
    Autodrive samples use the events.log frame counter as their ordering key;
    their reported times are frames, while world-probe times are seconds.
    """
    if not all(math.isfinite(v) for v in (lower, upper)) or not 0 <= lower <= upper:
        raise ValueError('ground band requires finite 0 <= lower <= upper')
    if source not in ('world', 'autodrive'):
        raise ValueError('unknown ground position source')
    samples = []
    for line in text.splitlines():
        if source == 'world':
            if 'PRIVATE WORLD POSITION ' not in line:
                continue
            match = re.search(r'PRIVATE WORLD POSITION time=(\S+) render=(\S+) source=player0(?:\s|$)', line)
        else:
            if 'autodrive:' not in line or not ('position=' in line or 'autodrive: speed=' in line):
                continue
            match = re.search(r'^f([0-9]+) t[0-9]+ autodrive:[^\n]*?\bposition=(\S+)(?:\s|$)', line)
        if not match:
            raise ValueError('malformed player position sample')
        values = tuple(float(v) for v in (match[1], *match[2].split(',')))
        if len(values) != 4 or not all(math.isfinite(v) for v in values):
            raise ValueError('invalid or nonfinite player position sample')
        t, a, b, c = values
        if samples and t <= samples[-1]['time']:
            raise ValueError('position times unordered')
        if source == 'world':
            x, height, z = -b, c, a
        else:
            x, height, z = a, b, c
        hit = world.find_face_below(x, z, height)
        projected = hit if hit is not None else world.find_face_below(x, z)
        samples.append(dict(time=t, x=x, y=height, z=z,
                            face=projected.height if projected is not None else None,
                            gap=height-projected.height if projected is not None else None,
                            below=hit is not None))
        if allow_jumps:
            sample = samples[-1]
            sample['dt'] = None
            if source == 'world':
                if len(samples) > 1:
                    sample['dt'] = t - samples[-2]['time']
            else:
                motion = re.search(r'\bspeed=(\S+)_mps\b.*?\bdistance=(\S+)_m\b', line)
                if not motion:
                    raise ValueError('jump check requires autodrive speed and odometer')
                speed, odometer = map(float, motion.groups())
                if not all(math.isfinite(v) and v >= 0 for v in (speed, odometer)):
                    raise ValueError('invalid jump speed or odometer')
                sample.update(speed=speed, odometer=odometer)
                if len(samples) > 1:
                    previous = samples[-2]
                    delta = odometer - previous['odometer']
                    if delta < 0:
                        raise ValueError('jump odometer decreasing')
                    mean = (speed + previous['speed']) / 2
                    if mean > 0:
                        sample['dt'] = delta / mean
    if not samples:
        raise ValueError('no player position samples')
    distance = sum(math.hypot(b['x']-a['x'], b['z']-a['z'])
                   for a, b in zip(samples, samples[1:]))
    gaps = [s['gap'] for s in samples if s['gap'] is not None]
    missing = [s for s in samples if not s['below']]
    low = [s for s in samples if s['gap'] is not None and s['gap'] < lower]
    high = [s for s in samples if s['gap'] is not None and s['gap'] > upper]
    if allow_jumps:
        jumps, accepted = ground_jumps(samples, lower, upper)
        high = [s for i, s in enumerate(samples) if i not in accepted and
                s['gap'] is not None and s['gap'] > upper]
    failures = []
    if distance < 5000:
        failures.append(f'distance {distance:.3f} m < 5000 m')
    if missing:
        failures.append(f'no face below: {len(missing)}/{len(samples)} samples; first time={missing[0]["time"]:.6f}')
    if low:
        failures.append(f'height below band: {len(low)} samples < {lower:g} m; first time={low[0]["time"]:.6f}')
    if high:
        failures.append(f'height above band: {len(high)} samples > {upper:g} m; first time={high[0]["time"]:.6f}')
    # Missing projected geometry ranks first, then the greatest band violation.
    worst = max(samples, key=lambda s: (s['gap'] is None,
                max(lower-s['gap'], s['gap']-upper) if s['gap'] is not None else math.inf))
    autodrive = re.findall(r'autodrive:[^\n]*?\bdistance=([-+0-9.eE]+)_m\b', text)
    result = dict(passed=not failures, samples=len(samples), distance=distance,
                lower=lower, upper=upper, min=min(gaps) if gaps else None,
                max=max(gaps) if gaps else None, worst=worst, failures=failures,
                missing=len(missing), low=len(low), high=len(high),
                autodrive=autodrive[-1] if autodrive else None)
    if allow_jumps:
        result['jumps'] = jumps
    return result


def print_ground_summary(result):
    status = 'PASS' if result['passed'] else 'FAIL'
    print(f'PRIVATE WORLD GROUND {status} samples={result["samples"]} '
          f'distance={result["distance"]:.3f}_m required=5000_m '
          f'band={result["lower"]:g}..{result["upper"]:g}_m' +
          (f' jumps={len(result["jumps"])}' if 'jumps' in result else ''))
    for jump in result.get('jumps', []):
        print(f'PRIVATE WORLD GROUND JUMP time={jump["time"]:.6f} '
              f'peak_clearance={jump["peak"]:.6f}_m seconds={jump["seconds"]:.6f}')
    if result['autodrive'] is not None:
        print(f'autodrive: distance={result["autodrive"]}_m (reported odometer)')
    def metres(value):
        return 'none' if value is None else f'{value:.6f}_m'
    worst = result['worst']
    print(f'PRIVATE WORLD GROUND HEIGHT min={metres(result["min"])} max={metres(result["max"])} '
          f'worst_time={worst["time"]:.6f} physics={worst["x"]:.6f},{worst["y"]:.6f},{worst["z"]:.6f} '
          f'face={metres(worst["face"])} above_face={metres(worst["gap"])} below_face_found={worst["below"]}')
    for failure in result['failures']:
        print('PRIVATE WORLD GROUND FAIL: ' + failure)


def prop_summary(text, target='rockport', *, control=False):
    """Require a nearby player and native contact-created body displacement.

    No-body control reports zero observed displacement; it does not invent a
    position sample for a body that does not exist. Read each body's initial
    native position independently of the diagnostic's printed maximum.
    """
    summaries, factories, bodies, spawns, spawn_results = [], [], {}, [], []
    for line in text.splitlines():
        marker = 'PRIVATE WORLD PROP '
        if marker not in line:
            continue
        event, _, fields = line.split(marker, 1)[1].partition(' ')
        row = dict(part.split('=', 1) for part in fields.split() if '=' in part)
        if row.get('target') != target:
            continue
        if event == 'SUMMARY':
            summaries.append(row)
        elif event == 'SPAWN':
            spawns.append(row)
        elif event == 'SPAWN_RESULT':
            spawn_results.append(row)
        elif event == 'FACTORY' and int(row['body'], 16):
            factories.append(row)
        elif event == 'BODY':
            p = tuple(map(float, row['position'].split(',')))
            if len(p) != 3 or not all(math.isfinite(x) for x in p):
                raise ValueError('invalid prop position')
            bodies.setdefault(row['body'], []).append(p)
    if not summaries:
        raise ValueError('prop summary absent')
    distances = [float(row['car_distance']) for row in summaries]
    if not all(math.isfinite(d) and d >= 0 for d in distances) or min(distances) > 2:
        raise ValueError('player never reached prop')
    maximum = max((math.dist(p, positions[0]) for positions in bodies.values()
                   for p in positions), default=0.)
    result = dict(target=target, factories=len(factories), bodies=len(bodies),
                  samples=sum(map(len, bodies.values())), maximum=maximum,
                  closest=min(distances), control=control)
    if control:
        unresolved = target == 'metalpost'
        if unresolved and (not spawns or not spawn_results or
                           any(int(r['result']) or int(r['scenery'], 16) for r in spawn_results)):
            raise ValueError('unresolved prop control created a trigger or lacks lookup evidence')
        if (spawns and not unresolved) or factories or bodies or any(
                int(r[k]) for r in summaries for k in (('factories', 'samples') if unresolved else
                                                      ('spawns', 'factories', 'samples'))):
            raise ValueError('removed prop control still has a spawn/body')
        if any(int(r['body'], 16) or float(r['maximum']) != 0 for r in summaries):
            raise ValueError('removed prop control moved')
    elif not spawns or not factories or not bodies or maximum <= .5:
        raise ValueError(f'prop contact displacement not proven: {result}')
    elif any(body not in {r['body'] for r in factories} for body in bodies):
        raise ValueError('body not linked to contact factory')
    elif target == 'rockport' and any(r.get('attributes') != 'EB88E132' or r.get('bounds') != '2D5373CD'
                                     or r.get('override') != '29310' for r in spawns):
        raise ValueError('different converted prop observed')
    if target == 'metalpost' and any(r.get('attributes') != '014A1C7D' or
                                    r.get('bounds') != 'C8F94D11' or
                                    r.get('override') != '29018' for r in spawns):
        raise ValueError('different metal post observed')
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--base', type=Path)
    ap.add_argument('--out', type=Path, default=HERE / 'out/carbon')
    ap.add_argument('--manifest', type=Path, help='world manifest (default: recreate from the base image)')
    ap.add_argument('--proof', type=Path)
    ap.add_argument('--check-log', type=Path)
    ap.add_argument('--check-prop', type=Path, help='native prop contact event log')
    ap.add_argument('--prop-target', choices=('rockport', 'palmont', 'metalpost'), default='rockport')
    ap.add_argument('--prop-control', action='store_true', help='require zero bodies/displacement (metalpost retains its unresolved spawn)')
    ap.add_argument('--check-ground', type=Path, help='check every player position against collision faces')
    ap.add_argument('--tracks', type=Path, help='source track directory for --check-ground')
    ap.add_argument('--source', choices=('world', 'autodrive'), default='world',
                    help='ground position source (default: world; autodrive times are frames)')
    ap.add_argument('--ground-min', type=float, default=0., help='minimum height above face in metres (default: 0)')
    ap.add_argument('--ground-max', type=float, default=2., help='maximum height above face in metres (provisional default: 2)')
    ap.add_argument('--allow-jumps', action='store_true', help='classify bounded falling-velocity excursions above the band')
    ap.add_argument('--section', type=int, default=1503)
    args = ap.parse_args()
    if args.check_ground and args.check_log:
        ap.error('--check-ground and --check-log are separate modes')
    try:
        if args.check_prop:
            with args.check_prop.open() as log:
                text = ''.join(line for line in log if 'PRIVATE WORLD PROP ' in line)
            try:
                result = prop_summary(text, args.prop_target, control=args.prop_control)
            except ValueError as exc:
                print(f'PRIVATE WORLD PROP FAIL: {exc}'); return 1
            print('PRIVATE WORLD PROP PASS ' + ' '.join(f'{k}={v}' for k,v in result.items()))
            return 0
        elif args.check_ground:
            if not all((args.tracks, args.base)):
                ap.error('--check-ground requires --tracks and --base')
            try:
                world = load_ground_world(args.tracks, args.base)
                with args.check_ground.open() as log:
                    text = ''.join(line for line in log if 'PRIVATE WORLD POSITION ' in line or 'autodrive:' in line)
                result = ground_summary(text, world, args.ground_min, args.ground_max, args.source, args.allow_jumps)
            except ValueError as exc:
                print(f'PRIVATE WORLD GROUND FAIL: {exc}'); return 1
            print_ground_summary(result)
            return 0 if result['passed'] else 1
        elif args.check_log:
            camera=json.loads(args.proof.read_text())['camera'] if args.proof else None
            # events.log can contain hundreds of MB of unrelated diagnostics.
            with args.check_log.open() as log:
                text = ''.join(line for line in log if 'PRIVATE WORLD ' in line or 'PRIVATE TRACK OPEN ' in line)
            print(f'PRIVATE WORLD PROOF PASS signals={check_log(text, args.section, camera)}')
            try:
                height = height_summary(text)
                print('PRIVATE WORLD HEIGHT last=20s ' + ' '.join(f'{k}={v}' for k, v in height.items()))
            except ValueError as exc:
                print(f'PRIVATE WORLD HEIGHT UNPROVEN: {exc}')
        else:
            if not args.base: ap.error('--base required')
            prepare_archive(args.base.resolve(), args.out, args.manifest, args.proof)
    except FileNotFoundError as exc:
        print(f'SKIP: private assets absent: {exc}'); return 3
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
