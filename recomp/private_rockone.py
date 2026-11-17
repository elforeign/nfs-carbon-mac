"""Check one zone's simultaneous residency and subsequent count-only draw windows.

Elapsed completion time is bounded by the existing host-clock POSITION samples,
relative to their first observation. Frames are never converted to seconds.
Only groups covering at least 300 consecutive frames after COMPLETE, while the
initial zone remains complete in the census, enter acceptance. Sentinel allowance is deliberately
conservative: at most one count per distinct mesh reference on the proof's
source-missing list, per window. Repeated submissions do not enlarge it.
"""
import argparse
import bisect
import json
import math
from pathlib import Path
import re
import sys

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(HERE))
import private_census

FRAME = re.compile(r'^f(\d+) t\d+ ')
POSITION = re.compile(r'PRIVATE WORLD POSITION time=(\S+) ')


def zone_proof(directory, zone):
    """Read row membership from the written index, not the proof's row counts."""
    sys.path.insert(0, str(HERE.parent / 'tools_snapshot/worldmerge'))
    from formats import TrackIndex
    import visibility
    proof = json.loads((directory / 'proof.json').read_text())
    if (proof['track'] != 2000 or proof['region'] != 'L2RA' or proof['renumbered']
            or any(proof['shift'])):
        raise ValueError('native-coordinate L2RA proof required')
    if proof.get('checker_failure') or any(proof['validation']['dependencies'].values()):
        raise ValueError('proof has new missing dependencies or a checker failure')
    index = TrackIndex((directory / 'TRACKS/L2RA.BUN').read_bytes())
    index.validate((directory / 'TRACKS/STREAML2RA.BUN').stat().st_size)
    rows = [row for row in visibility.read(visibility.payload_of(index)).rows if row.number == zone]
    if len(rows) != 1:
        raise ValueError('zone must have exactly one visibility row')
    sizes = {s.number: s.size for s in index.sections}
    expected = set(rows[0].entries) & sizes.keys()
    if not expected:
        raise ValueError('zone has no entries with records')
    missing = proof['validation']['closure']['all_mesh_textures']['misses']
    meshes = {(r['section'], r['solid'], r['mesh'])
              for key in missing for r in key['references']}
    return dict(zone=zone, entries=sorted(expected), row_entries=len(rows[0].entries),
                bytes=sum(sizes[n] for n in expected), sentinel_allowance=len(meshes))


def summarize(lines, proof):
    rows, windows, clocks = [], [], []
    previous_frame = 0
    for number, line in enumerate(lines, 1):
        if not any(tag in line for tag in ('census:', 'PRIVATE WORLD DRAWPATH ',
                                           'PRIVATE WORLD POSITION ')):
            continue
        match = FRAME.match(line)
        if not match:
            raise ValueError(f'line {number}: diagnostic frame prefix missing')
        frame = int(match[1])
        if 'census:' in line:
            row, = private_census.samples([line])
            row.update(frame=frame, line=number)
            rows.append(row)
        elif 'PRIVATE WORLD DRAWPATH ' in line:
            values = dict(re.findall(r'(\w+)=(\S+)', line))
            if values.get('mode') != 'all':
                raise ValueError('count-only mode=all required')
            end = int(values['frame'])
            if end != frame or end <= previous_frame:
                raise ValueError('draw-window frames unordered or mismatched')
            keys = ('add', 'sentinel', 'meshes', 'scenery_add', 'scenery_sentinel',
                    'scenery_meshes', 'scenery_overflow')
            window = dict(start=previous_frame, end=end,
                          **{key: int(values[key]) for key in keys})
            if (any(window[key] < 0 for key in keys) or window['sentinel'] > window['meshes']
                    or window['scenery_sentinel'] > window['scenery_meshes']
                    or any(window['scenery_' + key] > window[key] for key in ('add', 'sentinel', 'meshes'))):
                raise ValueError('invalid mesh counters')
            windows.append(window)
            previous_frame = end
        else:
            match = POSITION.search(line)
            if not match:
                raise ValueError('malformed position clock')
            clock = float(match[1])
            if not math.isfinite(clock) or (clocks and clock <= clocks[-1][1]):
                raise ValueError('position clocks nonfinite or unordered')
            clocks.append((number, clock))
    if any(a['frame'] >= b['frame'] for a, b in zip(rows, rows[1:])):
        raise ValueError('census frames unordered')
    expected = set(proof['entries'])
    complete = next((r for r in rows if proof['zone'] in r['zones'] and expected <= r['sections']), None)
    failures = []
    if not complete:
        failures.append('COMPLETE absent: no census sample contains the entire zone row')
    skipped = max((r['skipped'] for r in rows), default=0)
    if skipped:
        failures.append(f'skipped={skipped}, expected 0')
    accepted = []
    bounds = [None, None]
    if complete:
        # Stop at the first sample which leaves this zone or loses one of its records.
        after = [r for r in rows if r['line'] >= complete['line']]
        stop = next((i for i, r in enumerate(after)
                     if proof['zone'] not in r['zones'] or not expected <= r['sections']), len(after))
        last = after[stop - 1]['frame']
        eligible = [w for w in windows if w['start'] > complete['frame'] and w['end'] <= last]
        group = None
        for window in eligible:
            if group is None or group['end'] != window['start']:
                group = dict(window)
            else:
                group['end'] = window['end']
                for key in window.keys() - {'start', 'end'}:
                    group[key] += window[key]
            if group['end'] - group['start'] >= 300:
                accepted.append(group)
                group = None
        clock_lines = [n for n, _ in clocks]
        i = bisect.bisect_left(clock_lines, complete['line'])
        if clocks:
            epoch = clocks[0][1]
            if i:
                bounds[0] = clocks[i - 1][1] - epoch
            if i < len(clocks):
                bounds[1] = clocks[i][1] - epoch
    totals = {key: sum(w['scenery_' + key] for w in accepted) for key in ('add', 'sentinel', 'meshes')}
    if not accepted:
        failures.append('no whole draw windows after COMPLETE in the first zone')
    if totals['add'] <= 0:
        failures.append('scenery add=0 after COMPLETE')
    if totals['meshes'] <= 0:
        failures.append('scenery meshes=0 after COMPLETE')
    if any(w['scenery_overflow'] for w in windows):
        failures.append('scenery membership table overflow')
    if any(w['scenery_sentinel'] > proof['sentinel_allowance'] for w in accepted):
        failures.append('sentinel exceeds proof missing-mesh allowance')
    return dict(zone=proof['zone'], required=len(expected), row_entries=proof['row_entries'],
                bytes=proof['bytes'], complete=complete is not None,
                complete_frame=complete['frame'] if complete else None,
                seconds_to_complete=bounds[1], seconds_to_complete_bounds=bounds,
                time_origin='first player POSITION host-clock sample; upper bound',
                maximum_loaded_of_required=max((len(expected & r['sections']) for r in rows), default=0),
                census_samples=len(rows), skipped=skipped,
                minimum_largest_free=min((r['largest'] for r in rows), default=None),
                sentinel_allowance=proof['sentinel_allowance'], windows=accepted,
                observed_totals={key: sum(w[key] for w in windows)
                                 for key in ('add', 'sentinel', 'meshes', 'scenery_add',
                                             'scenery_sentinel', 'scenery_meshes')},
                loaded_min=min((r['loaded'] for r in rows), default=None),
                loaded_max=max((r['loaded'] for r in rows), default=None),
                counter_scope='scenery', minimum_window_frames=300,
                evidence_frames=sum(w['end'] - w['start'] for w in accepted),
                totals=totals, passed=not failures, failures=failures)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--summary', required=True, type=Path)
    parser.add_argument('--world', required=True, type=Path)
    parser.add_argument('--zone', required=True, type=int)
    args = parser.parse_args(argv)
    try:
        proof = zone_proof(args.world, args.zone)
        with args.summary.open() as stream:
            result = summarize(stream, proof)
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f'rockone FAIL: {error}', file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True, separators=(',', ':')))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
