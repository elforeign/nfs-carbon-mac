"""Fresh-start fixtures: good 0; five bad logs exit 1/1/1/1/1.

Six CLI fixtures: notice, old-save, wrong-key, wrong-dialog, missing-records.
Additional missing-control, loaded-menu,
stale-control/label, late-control, unexpected-package and symlink probes fail.
No game, GPU, emulation or private assets.
"""
from pathlib import Path
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from private_fresh_start import FRESH_LABEL, check_events, check_user


GOOD = '''f2 t1 PRIVATE CARBON FE package=Loading.fng resource=123 caller=005b0ed1
f20 t1 PRIVATE CARBON FE package=FeBlackScreen.fng resource=123 caller=005b0ed1
f21 t1 PRIVATE CARBON FE package=FEAnyMovie.fng resource=456 caller=005b0ed1
f40 t1 PRIVATE CARBON FE package=FeGarageMain.fng resource=123 caller=005b0ed1
f41 t1 PRIVATE CARBON FE package=DEMO_SPLASH.fng resource=456 caller=005b0ed1
f59 t1 screen: FEAnyMovie.fng
f60 t1 screen: DEMO_SPLASH.fng
f60 t1 scripted key RETURN down
f62 t1 PRIVATE CARBON FE package=FeDialog.fng resource=789 caller=005b0ed1
f64 t1 screen: FeDialog.fng
f64 t1 dialog: text=LABEL
f64 t1 scripted key RETURN up
f68 t1 screen: FeDialog.fng
f68 t1 dialog: text=LABEL
f68 t1 scripted key RETURN down
f72 t1 screen: FeDialog.fng
f72 t1 dialog: text=LABEL
f72 t1 scripted key RETURN up
f80 t1 PRIVATE CARBON FE package=FeMainMenu.fng resource=123 caller=005b0ed1
f90 t1 screen: FeMainMenu.fng
'''.replace('LABEL', FRESH_LABEL)


def main():
    with tempfile.TemporaryDirectory(prefix='fresh-start-') as temp:
        root = Path(temp)
        exits = []
        for name in ('good', 'notice', 'old-save', 'wrong-key', 'wrong-dialog', 'missing-records'):
            case = root / name
            case.mkdir()
            user = case / 'user'
            save = user / ('NFS Carbon' if name == 'old-save' else 'Carbon/NFS Carbon') / 'Player/Player'
            save.parent.mkdir(parents=True)
            save.write_bytes(b'fixture save')
            events = GOOD
            if name == 'notice':
                events = events.replace('f80 t1 ', 'f70 t1 CARBON SCREEN TEXT hash=8D824D60 notice=fixture\nf80 t1 ', 1)
            elif name == 'wrong-key':
                events = events.replace('f60 t1 screen: DEMO_SPLASH.fng',
                                        'f60 t1 screen: FeGarageMain.fng')
            elif name == 'wrong-dialog':
                events = events.replace(FRESH_LABEL,
                    'You must create a new alias to start a new Career. Do you want to create a new alias?')
            elif name == 'missing-records':
                events = '\n'.join(line for line in events.splitlines()
                                   if 'screen: ' not in line and 'dialog: text=' not in line)
                events += '\nf90 t1 script step 4 pkg:FeMainMenu.fng done after 40 frames (FeMainMenu.fng)\n'
            log = case / 'events.log'
            log.write_text(events)
            result = subprocess.run([sys.executable, '-I', str(HERE / 'private_fresh_start.py'),
                                     '--events', str(log), '--user', str(user), '--saved'],
                                    capture_output=True, text=True)
            expected = 0 if name == 'good' else 1
            assert result.returncode == expected, (name, result.returncode, result.stdout, result.stderr)
            if name == 'good':
                assert 'menu control: f90' in result.stdout
                assert 'key f60 RETURN down package=DEMO_SPLASH.fng' in result.stdout
                assert 'key f64 RETURN up package=FeDialog.fng' in result.stdout
                assert 'key f68 RETURN down package=FeDialog.fng' in result.stdout
                assert 'saved: Carbon/NFS Carbon/Player/Player' in result.stdout
            elif name == 'notice':
                assert 'notices: 1' in result.stdout
            elif name == 'old-save':
                assert 'outside: NFS Carbon' in result.stdout
                assert 'no regular save file' in result.stdout
            elif name == 'wrong-key':
                assert 'key f60 RETURN down package=FeGarageMain.fng' in result.stdout
            elif name == 'wrong-dialog':
                assert 'unexpected dialog f68' in result.stdout
            else:
                assert 'missing screen: record' in result.stdout
                assert 'missing dialog: text= record' in result.stdout
                assert 'menu control: f90' in result.stdout
            exits.append(result.returncode)

        assert not check_events(GOOD.splitlines())['errors']
        closing_lookup = GOOD.replace('f72 t1 scripted key RETURN up',
            'f72 t1 scripted key RETURN up\n'
            'f72 t1 PRIVATE CARBON FE package=FeDialog.fng resource=789 caller=005984c1')
        assert not check_events(closing_lookup.splitlines())['errors']
        # A load, a previous-frame wait, or a timed-out wait cannot prove control.
        for broken in (
            GOOD[:GOOD.index('f90')],
            GOOD.replace('f60 t1 screen: DEMO_SPLASH.fng\n', ''),
            GOOD.replace('f60 t1 screen: DEMO_SPLASH.fng\nf60 t1 scripted key RETURN down',
                         'f60 t1 scripted key RETURN down\nf60 t1 screen: DEMO_SPLASH.fng'),
            GOOD.replace(f'f68 t1 dialog: text={FRESH_LABEL}\n', ''),
            GOOD.replace('f80 t1 PRIVATE CARBON FE package=FeMainMenu.fng',
                         'f79 t1 PRIVATE CARBON FE package=FeDialog.fng resource=987 caller=005b0ed1\n'
                         'f80 t1 PRIVATE CARBON FE package=FeMainMenu.fng'),
            GOOD.replace('f90 t1 screen: FeMainMenu.fng',
                         'f90 t1 script: package timeout want=FeMainMenu.fng actual=FeMainMenu.fng; input stopped'),
            GOOD.replace('package=Loading.fng', 'package=Unexpected.fng'),
        ):
            assert check_events(broken.splitlines())['errors']
        after_menu = GOOD + 'f101 t1 screen: FeMainMenu_Sub.fng\nf101 t1 scripted key RETURN down\n'
        assert not check_events(after_menu.splitlines())['errors']
        assert check_events((GOOD + 'f100 t1 CARBON SCREEN TEXT fixture\n').splitlines())['errors']
        for package in ('FEAnyMovie.fng', 'DEMO_SPLASH.fng'):
            assert not check_events(GOOD.replace('DEMO_SPLASH.fng', package).splitlines())['errors']

        user = root / 'links'
        carbon = user / 'Carbon'
        carbon.mkdir(parents=True)
        (carbon / 'NFS Carbon').symlink_to(root / 'good/user/Carbon/NFS Carbon', target_is_directory=True)
        saves, outside, errors = check_user(user, True)
        assert not saves and not outside and errors
        print('PRIVATE FRESH START PASS fixtures=6 exits=' + '/'.join(map(str, exits)) +
              ' bad=5 missing/stale/late/label/load/timeout/package/link guards=PASS')
    return 0


if __name__ == '__main__':
    sys.exit(main())
