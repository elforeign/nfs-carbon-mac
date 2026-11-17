"""Summarize read-only streaming samples from a diagnostic events log.

Loads/unloads count section set differences between consecutive samples; the
first set is the initial baseline. Zone changes count changes of the ordered
zone pair, and distinct zones exclude nonpositive sentinel values. Skipped is
the peak native counter (also report its final value and nonzero samples).
"""
import argparse
import json
import math
from pathlib import Path
import re
import sys


SAMPLE = re.compile(
    r'census: zones=(-?\d+),(-?\d+) loaded=(\d+) bytes=(\d+) pool=(\d+) '
    r'largest=(\d+) skipped=(\d+) sections=(\d+(?:,\d+)*)?'
    r'(?: stream=(\S+))?'
    r'(?: vel=(\S+))?'
    r'(?: zone_age=(-?\d+),(-?\d+) wheels=(-?\d+))?'
    r'(?: suspension=([0-9A-F]{8}))?'
    r'(?: loading=(\d+))?\s*$')


def samples(lines):
    for number, line in enumerate(lines, 1):
        if 'census:' not in line:
            continue
        match = SAMPLE.search(line)
        if not match:
            raise ValueError(f'line {number}: malformed census sample')
        a, b, loaded, size, pool, largest, skipped = map(int, match.groups()[:7])
        sections = tuple(map(int, match[8].split(','))) if match[8] else ()
        if loaded != len(sections) or len(set(sections)) != loaded:
            raise ValueError(f'line {number}: loaded count or duplicate section mismatch')
        row = dict(zones=(a, b), loaded=loaded, bytes=size, pool=pool,
                   largest=largest, skipped=skipped, sections=frozenset(sections))
        if match[9]:
            # Slot 0's streaming position: the point the engine classifies.
            row['stream'] = tuple(float(v) for v in match[9].split(','))
            if len(row['stream']) != 3 or not all(math.isfinite(v) for v in row['stream']):
                raise ValueError(f'line {number}: invalid streaming position')
        if match[10]:
            # Slot 0's velocity: the engine's streamer-prediction projection.
            row['velocity'] = tuple(float(v) for v in match[10].split(','))
            if len(row['velocity']) != 3 or not all(math.isfinite(v) for v in row['velocity']):
                raise ValueError(f'line {number}: invalid streaming velocity')
        if match[11] is not None:
            row['zone_age'] = tuple(map(int, match.group(11, 12)))
            row['wheels'] = int(match[13])
            if any(v < -1 for v in row['zone_age']) or not -1 <= row['wheels'] <= 4:
                raise ValueError(f'line {number}: invalid engine state')
        if match[14] is not None:
            # The player's ISuspension vtable +4C getter (00000000: not reached).
            row['suspension'] = int(match[14], 16)
        if match[15] is not None:
            row['loading'] = int(match[15])
        yield row


def summarize(rows):
    result = dict(samples=0, zones=[], distinct_zones=0, zone_changes=0,
                  loads=0, unloads=0, initial_loaded=[], loaded_min=None,
                  loaded_max=None, always_loaded=[], peak_bytes=0,
                  minimum_largest_free=None, pool_min=None, pool_max=None,
                  skipped=0, skipped_final=0, skipped_samples=0, loading=0, loading_samples=0)
    zones, previous, common = set(), None, None
    for row in rows:
        result['samples'] += 1
        zones.update(z for z in row['zones'] if z > 0)
        current = row['sections']
        if previous is None:
            result['initial_loaded'] = sorted(current)
        else:
            result['loads'] += len(current - previous['sections'])
            result['unloads'] += len(previous['sections'] - current)
            result['zone_changes'] += row['zones'] != previous['zones']
        common = current if common is None else common & current
        for name, field, operation in (
                ('loaded_min', 'loaded', min), ('loaded_max', 'loaded', max),
                ('minimum_largest_free', 'largest', min),
                ('pool_min', 'pool', min), ('pool_max', 'pool', max)):
            old = result[name]
            result[name] = row[field] if old is None else operation(old, row[field])
        result['peak_bytes'] = max(result['peak_bytes'], row['bytes'])
        result['skipped'] = max(result['skipped'], row['skipped'])
        result['skipped_final'] = row['skipped']
        result['skipped_samples'] += row['skipped'] > 0
        result['loading'] += row.get('loading', 0)
        result['loading_samples'] += row.get('loading', 0) > 0
        previous = row
    result['zones'] = sorted(zones)
    result['distinct_zones'] = len(zones)
    result['always_loaded'] = sorted(common or ())
    return result


def nonnegative(value):
    value = int(value)
    if value < 0:
        raise argparse.ArgumentTypeError('must be nonnegative')
    return value


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--summary', required=True, type=Path, metavar='EVENTS.LOG')
    parser.add_argument('--expect-loaded', type=nonnegative, metavar='N',
                        help='require exactly N loaded sections in every sample, and at least one sample')
    parser.add_argument('--expect-zone-changes', type=nonnegative, metavar='N',
                        help='require at least N changes of the zone pair, and at least one sample')
    args = parser.parse_args(argv)
    try:
        with args.summary.open() as stream:
            result = summarize(samples(stream))
    except (OSError, ValueError) as error:
        print(f'census FAIL: {error}', file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    failures = []
    if args.expect_loaded is not None and (
            not result['samples'] or result['loaded_min'] != args.expect_loaded or
            result['loaded_max'] != args.expect_loaded):
        failures.append(f'expected loaded={args.expect_loaded} in every sample; '
                        f"observed {result['loaded_min']}..{result['loaded_max']}")
    if args.expect_zone_changes is not None and (
            not result['samples'] or result['zone_changes'] < args.expect_zone_changes):
        failures.append(f"expected zone_changes>={args.expect_zone_changes}; observed {result['zone_changes']}")
    for failure in failures:
        print(f'census FAIL: {failure}', file=sys.stderr)
    return int(bool(failures))


if __name__ == '__main__':
    raise SystemExit(main())
