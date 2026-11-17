"""Offline build-input proof; no executable is launched.

Compact and legacy lists produce identical synthetic starts and names.
Removing one row reports its missing function; wrong image/digest fail closed.
With the image present, all 16 recreated witnesses validate; a changed witness
fails validation. Without it, synthetic checks run before exit 3.
"""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import subprocess
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from build_private import image_functions
import build_private
import private_build_inputs as inputs
import private_world as world


class SyntheticPE:
    base = 0x400000
    sha256 = '0' * 64
    sections = [(b'.text', 256, 0x1000, 256, 0)]


def rejected(call, message):
    try:
        call()
    except ValueError as error:
        assert message in str(error), str(error)
    else:
        raise AssertionError('invalid input accepted: ' + message)


def test_ignored_output_locations():
    """Inspect enclosing repositories and gitfiles; allow copies outside Git."""
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp).resolve()
        standalone = base / 'standalone'
        (standalone / 'recomp').mkdir(parents=True)
        with mock.patch.object(build_private, 'HERE', standalone / 'recomp'):
            assert build_private.ignored_output(standalone / 'recomp/out/private').is_dir()
        repo = base / 'repo'
        repo.mkdir()
        subprocess.run(['git', 'init', '-q', str(repo)], check=True, capture_output=True)
        nested = repo / 'copy'
        (nested / 'recomp').mkdir(parents=True)
        for root in (repo, nested):
            (root / 'recomp').mkdir(exist_ok=True)
            out = root / 'recomp/out/private'
            with mock.patch.object(build_private, 'HERE', root / 'recomp'):
                try:
                    build_private.ignored_output(out)
                except subprocess.CalledProcessError:
                    pass
                else:
                    raise AssertionError('unignored private output accepted')
                assert not out.exists()
        (repo / '.gitignore').write_text('/recomp/out/\n/copy/recomp/out/\n')
        for root in (repo, nested):
            with mock.patch.object(build_private, 'HERE', root / 'recomp'):
                assert build_private.ignored_output(root / 'recomp/out/private').is_dir()
        # A gitfile uses the same discovery as a linked worktree.
        (repo / '.git').rename(repo / 'metadata')
        (repo / '.git').write_text('gitdir: metadata\n')
        with mock.patch.object(build_private, 'HERE', repo / 'recomp'):
            assert build_private.ignored_output(repo / 'recomp/out/ignored').is_dir()
            (repo / '.gitignore').write_text('')
            try:
                build_private.ignored_output(repo / 'recomp/out/refused')
            except subprocess.CalledProcessError:
                pass
            else:
                raise AssertionError('gitfile private output accepted without an ignore rule')
            assert not (repo / 'recomp/out/refused').exists()
    print('OUTPUT LOCATIONS PASS: standalone, nested repository, checkout and gitfile')


def main():
    test_ignored_output_locations()
    pe = SyntheticPE()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        compact = root / 'compact.tsv'
        legacy = root / 'legacy.tsv'
        body = '00401000\n00401020\n'
        header = (f'# image-sha256 {pe.sha256}\n# starts-count 2\n'
                  f'# starts-sum {0x401000 + 0x401020:x}\n'
                  f'# starts-sha256 {hashlib.sha256(body.encode()).hexdigest()}\n')
        compact.write_text(header + body)
        legacy.write_text('address\tname\tsize\tthunk\n'
                          '00401000\tFUN_00401000\t32\tfalse\n'
                          '00401020\tFUN_00401020\t16\tfalse\n'
                          '00401040\tthunk\t8\ttrue\n')
        read = lambda path: image_functions(pe, path, data_starts=False)
        assert read(compact) == read(legacy) == [
            (0x401000, 0x401020, 'FUN_00401000'),
            (0x401020, 0x401100, 'FUN_00401020')]
        compact.write_text(header + '00401020\n')
        rejected(lambda: read(compact), 'missing function FUN_00401000')
        compact.write_text(header + body.replace('00401020', '00401030'))
        rejected(lambda: read(compact), 'starts digest mismatch')
        compact.write_text((header + body).replace(pe.sha256, '1' * 64))
        rejected(lambda: read(compact), 'image SHA mismatch')
        legacy.write_text('00401000\ttested_name\t32\tfalse\n')
        assert read(legacy) == [(0x401000, 0x401100, 'tested_name')]
    print('BUILD INPUTS SYNTHETIC PASS: legacy/compact match; 3 invalid lists rejected')

    image = HERE.parent.parent / 'inputs/NFSC/NFSC.exe'
    if not image.is_file():
        print('SKIP: supported image absent')
        return 3
    assert inputs.FUNCTIONS == HERE / 'functions_nfsc.tsv'
    manifest = inputs.world_manifest(image)
    assert set(manifest['hooks']) == set(world.ALL_HOOKS)
    assert len(manifest['hooks']) == 16
    assert all(len(bytes.fromhex(row['bytes'])) == 32 for row in manifest['hooks'].values())
    assert world.validate_manifest(manifest, image) == manifest
    broken = json.loads(json.dumps(manifest))
    row = broken['hooks']['select']
    raw = bytearray.fromhex(row['bytes'])
    raw[0] ^= 1
    row['bytes'] = raw.hex()
    rejected(lambda: world.validate_manifest(broken, image), 'byte witness differs: select')
    print('BUILD INPUTS IMAGE PASS: 16 witnesses; changed witness rejected')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
