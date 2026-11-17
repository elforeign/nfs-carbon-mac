"""Check the last live AA observation against the F10 row and actual back buffer.

Input: events.log and settings_rows.txt from the same diagnostic run. Native
levels 0/1/2 must agree with Off/2x/4x and actual samples 1/2/4. No inference from
requested present quality is accepted. Missing evidence is a failure.
"""
import argparse
from pathlib import Path
import re

MODES = {'off': ('Off', 0, 1), '2x': ('2x', 1, 2), '4x': ('4x', 2, 4)}
EVENT = re.compile(r'\bPRIVATE CARBON AA level=(\d+) samples=(\d+)\b')


def check(events, rows, want):
    values = [fields[2] for line in rows.splitlines()
              if len(fields := line.split('\t')) == 3
              and fields[1] == 'graphics.antialiasing']
    observation = None
    for line in events:
        if match := EVENT.search(line):
            observation = tuple(map(int, match.groups()))
    label, level, samples = MODES[want]
    passed = values == [label] and observation == (level, samples)
    actual = 'missing' if observation is None else f'level={observation[0]} samples={observation[1]}'
    return passed, (f'AA {"PASS" if passed else "FAIL"}: want={label} '
                    f'row={values!r} {actual}; expected level={level} samples={samples}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--events', type=Path, required=True)
    parser.add_argument('--rows', type=Path, required=True)
    parser.add_argument('--want', choices=MODES, required=True)
    args = parser.parse_args()
    try:
        with args.events.open() as events:
            passed, message = check(events, args.rows.read_text(), args.want)
    except (OSError, UnicodeError) as error:
        print(f'AA FAIL: {error}')
        return 1
    print(message)
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
