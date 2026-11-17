"""Live AA proof: good row=4x / level=2 / samples=4 exits 0;
broken row=4x / level=2 / samples=2 exits 1 (expected 4, observed 2).
Also rejects missing/stale/duplicate row evidence and a final reset mismatch.
"""
from pathlib import Path
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent


def main():
    with tempfile.TemporaryDirectory(prefix='private-aa-live-') as directory:
        root = Path(directory)
        events, rows = root/'events.log', root/'settings_rows.txt'
        def run(want, value, level, samples, expected, prefix=''):
            rows.write_text(f'Picture\tgraphics.antialiasing\t{value}\n')
            events.write_text(prefix + f'f42 t1 PRIVATE CARBON AA level={level} samples={samples}\n')
            result = subprocess.run([sys.executable, '-I', str(HERE/'private_aa_live.py'),
                '--events', str(events), '--rows', str(rows), '--want', want],
                capture_output=True, text=True)
            assert result.returncode == expected, (result.returncode, result.stdout, result.stderr)
            print(f'exit={result.returncode} {result.stdout.strip()}')
            return result
        for want, value, level, samples in [('off','Off',0,1),('2x','2x',1,2),('4x','4x',2,4)]:
            run(want, value, level, samples, 0)
        bad = run('4x','4x',2,2,1)
        assert 'samples=2' in bad.stdout and 'samples=4' in bad.stdout
        run('4x','2x',2,4,1)
        run('4x','4x',1,4,1)
        run('4x','4x',2,2,1, 'f1 t1 PRIVATE CARBON AA level=2 samples=4\n')
        for row_text, event_text in [('', 'PRIVATE CARBON AA level=2 samples=4\n'),
                ('Picture\tgraphics.antialiasing\t4x\n', ''),
                ('Picture\tgraphics.antialiasing\t4x\n'*2, 'PRIVATE CARBON AA level=2 samples=4\n')]:
            rows.write_text(row_text); events.write_text(event_text)
            result = subprocess.run([sys.executable, '-I', str(HERE/'private_aa_live.py'),
                '--events', str(events), '--rows', str(rows), '--want', '4x'], capture_output=True, text=True)
            assert result.returncode == 1, result.stdout
    print('LIVE AA PASS: 3 modes; 7 rejected fixtures; expected4/observed2 exit=1')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
