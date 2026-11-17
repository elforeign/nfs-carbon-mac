"""Check diagnostic player pursuit and active native cop evidence.

Active means the witnessed 006D80C0 getter's A8 field is nonzero;
vehicle destruction is deliberately not asserted.
"""
import argparse
from pathlib import Path
import re
import sys

REQUEST = re.compile(r'carbon_pursuit: request t=([\d.]+) attempt=(\d+) enabled=([01])\s*$')
SAMPLE = re.compile(
    r'carbon_pursuit: t=(-?[\d.]+) attempt=(\d+) pursuits=(\d+) player=([0-9a-fA-F]+) '
    r'live=(\d+) unknown=(\d+) onroad=(\d+) pool=(\d+) heat=(na|-?[\d.]+) '
    r'disabled=(\d+) nonew=(\d+)'
    r'(?: status=(\d+) busts=(na|\d+) evades=(na|\d+) cash=(na|\d+))?\s*$')


def check(lines, expect_off=False):
    requests, samples = [], []
    for number, line in enumerate(lines, 1):
        if 'carbon_pursuit:' not in line:
            continue
        request, sample = REQUEST.search(line), SAMPLE.search(line)
        if request:
            requests.append((float(request[1]), int(request[2])))
        elif sample:
            t, attempt, pursuits, player, live, unknown, road, pool, heat, disabled, nonew, status, busts, evades, cash = sample.groups()
            def value(field):
                return None if field in (None, 'na') else int(field)
            samples.append(dict(t=float(t), attempt=int(attempt), pursuits=int(pursuits),
                                player=int(player, 16), live=int(live), requested=bool(requests),
                                status=value(status), busts=value(busts), evades=value(evades),
                                cash=value(cash), line=number))
        else:
            raise ValueError(f'line {number}: malformed pursuit diagnostic')
    first = next((r for r in samples if r['requested'] and r['t'] >= 0 and r['player'] and r['live'] >= 1), None)
    start = first['t'] if first else None
    lasted = 0.
    if first:
        for row in samples[samples.index(first):]:
            lasted = max(0., row['t'] - start)
            if not row['player']:
                break
    attempts = max((r[1] for r in requests), default=0)
    attempts = max(attempts, max((r['attempt'] for r in samples), default=0))
    passed = (not requests and all(r['pursuits'] == 0 and
                      r['attempt'] == 0 and not r['player'] and not r['live'] for r in samples)
                      if expect_off else bool(samples) and len(requests) == 1 and requests[0][1] == 1 and
                      attempts == 1 and first is not None and 0 <= start <= 15 and first['attempt'] == 1)
    end, ending, previous = 'none', None, {}
    for row in samples:
        if row['requested'] and row['attempt'] and row['t'] >= 0:
            for field, reason, status in (('busts', 'bust', 3), ('evades', 'evade', 4)):
                fresh = (row[field] is not None and previous.get(field) is not None
                         and row[field] > previous[field])
                if fresh or (row['player'] and row['status'] == status):
                    end, ending = reason, row
                    break
        if ending:
            break
        for field in ('busts', 'evades'):
            if row[field] is not None:
                previous[field] = row[field]
    def seconds(value):
        return 'na' if value is None else f'{value:.3f}'
    return passed, (f'PURSUIT {"PASS" if passed else "FAIL"} '
                    f'request_t={seconds(requests[0][0] if requests else None)} '
                    f'start_after={seconds(start)} peak_live={max((r["live"] for r in samples), default=0)} '
                    f'lasted={lasted:.3f} attempts={attempts} end={end} '
                    f'end_t={seconds(ending["t"] if ending else None)} '
                    f'end_line={ending["line"] if ending else "na"}')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('log', type=Path)
    parser.add_argument('--expect-off', action='store_true')
    args = parser.parse_args(argv)
    try:
        with args.log.open() as stream:
            passed, result = check(stream, args.expect_off)
    except (OSError, ValueError) as error:
        print(f'PURSUIT FAIL: {error}')
        return 1
    print(result)
    return 0 if passed else 1


if __name__ == '__main__':
    sys.exit(main())
