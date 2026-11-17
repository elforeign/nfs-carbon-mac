"""Check fresh-start evidence without launching or changing the game.

Loaded packages are not control witnesses. A key event needs a control sample
in its own frame; a previous-frame pkg wait cannot prove its recipient. Both
presses and releases are reported and checked. Missing evidence fails closed.
The package allowlist is the measured first title/Return run. Native alias
dialogs are permitted only with their measured fresh-profile label; a generic
FeDialog package name does not identify the dialog. No notice is allowed.

Live proof: native-initializer save log exit 0 (--saved), maximum-registry
menu log exit 0; the same save log with just f44264's key-control record
changed to FeGarageMain.fng exits 1 (one bad recipient, other evidence intact).
Two earlier live-FNG observer logs exit 1 for unproven labels. A third
independent passing game run was not obtained within the four-run budget.
"""
import argparse
from pathlib import Path
import re
import stat
import sys


MENU = 'femainmenu.fng'
PACKAGES = frozenset(name.casefold() for name in (
    'Loading.fng', 'FeBlackScreen.fng', 'FEAnyMovie.fng',
    'FeGarageMain.fng', 'DEMO_SPLASH.fng', 'FeDialog.fng',
))
KEY_PACKAGES = frozenset(('feanymovie.fng', 'demo_splash.fng', 'fedialog.fng'))
FRESH_LABEL = 'Create a new alias? If you do not create a new alias, changes may be lost.'
FRAME = re.compile(r'^f(\d+) t\d+ (.*)$')
LOAD = re.compile(r'PRIVATE CARBON FE package=(\S+)')
WAIT = re.compile(r'script step \d+ pkg:([^ :]+)(?::\S+)? done after \d+ frames \(([^)]+)\)$')
CONTROL = re.compile(r'(?:autodrive: package in control |package in control )([^,)]+)')
SCREEN = re.compile(r'screen: (\S+)$')
DIALOG = re.compile(r'dialog: text=(.*)$')
KEY = re.compile(r'scripted key (\S+) (down|up)\b')
TIMEOUT = re.compile(r'script: package timeout want=\S+ actual=(\S+); input stopped')


def check_events(lines):
    """Stream large import logs, buffering only relevant events in one frame."""
    report = {'menu': None, 'packages': [], 'controls': [], 'keys': [], 'dialogs': [],
              'notices': 0, 'errors': []}
    pending = []
    pending_frame = None
    last_frame = -1
    unlabelled_dialog = None

    def flush(frame, events):
        nonlocal unlabelled_dialog
        # Only control read before the key in its own frame proves a recipient.
        control = None
        labels = [value for kind, value in events if kind == 'dialog']
        dialog_seen = False
        for kind, value in events:
            before_menu = report['menu'] is None
            if kind == 'control':
                control = value
                if before_menu:
                    report['controls'].append((frame, value))
                    if value.casefold() not in PACKAGES | {MENU, 'none'}:
                        report['errors'].append(f'unexpected control f{frame} {value}')
                    if value.casefold() == 'fedialog.fng':
                        dialog_seen = True
                if value.casefold() == MENU and before_menu:
                    if unlabelled_dialog is not None:
                        report['errors'].append(f'missing dialog: text= record; dialog label UNPROVEN after load f{unlabelled_dialog}')
                        unlabelled_dialog = None
                    report['menu'] = frame
            elif kind == 'load':
                if before_menu:
                    report['packages'].append((frame, value))
                    if value.casefold() not in PACKAGES | {MENU}:
                        report['errors'].append(f'unexpected package f{frame} {value}')
                    if value.casefold() == 'fedialog.fng':
                        unlabelled_dialog = frame
                # A load can change control; it never establishes control.
                control = None
            elif kind == 'dialog' and before_menu:
                report['dialogs'].append((frame, value))
                unlabelled_dialog = None
                if value != FRESH_LABEL:
                    report['errors'].append(f'unexpected dialog f{frame} text={value}')
            elif kind == 'notice':
                report['notices'] += 1
            elif kind == 'timeout' and before_menu:
                report['errors'].append(f'package timeout f{frame} actual={value}')
                control = value if value != 'none' else None
            elif kind == 'key':
                name, edge = value
                report['keys'].append((frame, name, edge, control))
                if before_menu and (not control or control.casefold() not in KEY_PACKAGES):
                    if not control:
                        report['errors'].append(f'missing screen: record before key f{frame} {name} {edge}')
                    report['errors'].append(
                        f'key recipient f{frame} {name} {edge} '
                        f'package={control or "UNPROVEN"}')
            elif kind == 'unparsed' and before_menu:
                report['errors'].append(f'unparsed evidence f{frame} {value}')
        if dialog_seen and not labels:
            report['errors'].append(f'missing dialog: text= record; dialog label UNPROVEN f{frame}')
        elif dialog_seen and any(label != FRESH_LABEL for label in labels):
            report['errors'].append(f'dialog label mismatch f{frame}')
        if labels and all(label == FRESH_LABEL for label in labels):
            # Resource lookups can recur after the input that closes a dialog.
            unlabelled_dialog = None

    for line in lines:
        if not any(marker in line for marker in (
                'PRIVATE CARBON FE package=', 'CARBON SCREEN TEXT',
                'scripted key ', 'script step ', 'package in control ',
                'script: package timeout', 'screen: ', 'dialog: text=')):
            continue
        matched = FRAME.match(line.rstrip('\n'))
        if not matched:
            report['errors'].append('relevant event has no frame: ' + line.strip()[:160])
            continue
        frame, message = int(matched[1]), matched[2]
        if frame < last_frame:
            report['errors'].append(f'event frame regressed f{last_frame}->f{frame}')
        last_frame = frame
        if frame != pending_frame:
            if pending:
                flush(pending_frame, pending)
            pending_frame, pending = frame, []
        if 'CARBON SCREEN TEXT' in message:
            pending.append(('notice', None))
        elif (item := LOAD.search(message)):
            pending.append(('load', item[1]))
        elif (item := KEY.search(message)):
            pending.append(('key', (item[1], item[2])))
        elif (item := DIALOG.fullmatch(message)):
            pending.append(('dialog', item[1]))
        elif (item := SCREEN.fullmatch(message)):
            pending.append(('control', item[1]))
        elif (item := WAIT.fullmatch(message)):
            want, actual = item.groups()
            if actual.casefold().startswith(want.casefold()):
                pending.append(('control', actual))
            else:
                pending.append(('unparsed', message))
        elif (item := CONTROL.search(message)):
            pending.append(('control', item[1]))
        elif (item := TIMEOUT.fullmatch(message)):
            pending.append(('timeout', item[1]))
        elif 'scripted key ' in message or 'pkg:' in message or message.startswith(('screen:', 'dialog:')):
            pending.append(('unparsed', message))
    if pending:
        flush(pending_frame, pending)
    if report['menu'] is None:
        report['errors'].append('FeMainMenu.fng never witnessed in control')
    if unlabelled_dialog is not None:
        report['errors'].append(f'missing dialog: text= record; dialog label UNPROVEN after load f{unlabelled_dialog}')
    if report['notices']:
        report['errors'].append(f'notices={report["notices"]}')
    return report


def check_user(user, saved):
    saves, outside, errors = [], [], []
    if not user.is_dir() or user.is_symlink():
        return saves, outside, ['user directory missing or a symlink']
    for entry in sorted(user.iterdir()):
        if entry.name != 'Carbon':
            outside.append(entry.relative_to(user).as_posix())
            if entry.is_dir() and not entry.is_symlink():
                outside.extend(p.relative_to(user).as_posix() for p in sorted(entry.rglob('*')))
    carbon = user / 'Carbon'
    if carbon.is_symlink():
        errors.append('Carbon directory is a symlink')
    elif carbon.is_dir():
        for path in sorted(carbon.rglob('*')):
            if path.is_symlink():
                errors.append('symlink inside Carbon: ' + path.relative_to(user).as_posix())
            elif stat.S_ISREG(path.lstat().st_mode) and (carbon / 'NFS Carbon') in path.parents:
                saves.append(path.relative_to(user).as_posix())
    if outside:
        errors.append(f'files or folders outside Carbon={len(outside)}')
    if saved and not saves:
        errors.append('no regular save file under Carbon/NFS Carbon/')
    return saves, outside, errors


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--events', required=True, type=Path)
    parser.add_argument('--user', required=True, type=Path)
    parser.add_argument('--saved', action='store_true')
    args = parser.parse_args(argv)
    try:
        with args.events.open(errors='replace') as stream:
            report = check_events(stream)
        saves, outside, errors = check_user(args.user, args.saved)
    except OSError as error:
        print(f'FRESH START FAIL: {error}')
        return 1
    report['errors'].extend(errors)
    print('allowed packages: ' + ', '.join(sorted(PACKAGES)))
    for frame, package in report['packages']:
        print(f'loaded f{frame} {package}')
    for frame, package in report['controls']:
        print(f'control f{frame} {package}')
    print('menu control: ' + (f'f{report["menu"]}' if report['menu'] is not None else 'UNPROVEN'))
    for frame, name, edge, package in report['keys']:
        print(f'key f{frame} {name} {edge} package={package or "UNPROVEN"}')
    for frame, label in report['dialogs']:
        print(f'dialog f{frame} text={label}')
    print(f'notices: {report["notices"]}')
    print(f'saved paths: {len(saves)}')
    for path in saves:
        print('saved: ' + path)
    print(f'outside Carbon: {len(outside)}')
    for path in outside:
        print('outside: ' + path)
    for error in report['errors']:
        print('FAIL: ' + error)
    print('FRESH START ' + ('FAIL' if report['errors'] else 'PASS'))
    return int(bool(report['errors']))


if __name__ == '__main__':
    sys.exit(main())
