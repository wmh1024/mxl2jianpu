"""Find the first bar that makes jianpu-ly's bar check fail.

Runs jianpu-ly on successively longer prefixes of the jianpu input, so the first
failing prefix identifies the bar that breaks the arithmetic.  Useful when the
error message points at a bar that looks correct on its own.
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mxl2jp import render  # noqa: E402

HEADER_PREFIXES = ('title=', 'composer=', 'instrument=', 'OctavesBefore',
                   'WithStaff', 'subtitle=', 'subsubtitle=',
                   'poet=', 'arranger=')


def split_input(path: Path):
    """Separate the header/directive lines from the bar lines."""
    head, bars = [], []
    import re
    for ln in path.read_text(encoding='utf-8').splitlines():
        s = ln.strip()
        if not s:
            continue
        if s.startswith(HEADER_PREFIXES):
            head.append(ln)
            continue
        if re.match(r'^\d+/\d+$', s) or re.match(r'^-?\d+=[A-G#b]+$', s):
            head.append(ln)
            continue
        bars.append(ln)
    return head, bars


def run(text: str, jianpu_ly: Path, workdir: Path) -> tuple[int, str]:
    f = workdir / 'prefix.txt'
    f.write_text(text, encoding='utf-8', newline='\n')
    env = dict(os.environ)
    env['PYTHONIOENCODING'] = 'utf-8'
    env['j2ly_sloppy_bars'] = '1'
    r = subprocess.run([sys.executable, str(jianpu_ly), str(f)],
                       capture_output=True, env=env)
    return r.returncode, r.stderr.decode('utf-8', 'replace')


def main(path: str) -> None:
    jianpu_ly = render.find_jianpu_ly()
    if jianpu_ly is None:
        raise SystemExit('jianpu-ly.py not found; set MXL2JP_JIANPULY')

    src = Path(path)
    head, bars = split_input(src)
    print(f'header lines: {len(head)}, bars: {len(bars)}')

    with tempfile.TemporaryDirectory() as td:
        workdir = Path(td)

        def attempt(n: int) -> tuple[int, str]:
            return run('\n'.join(head + bars[:n]) + '\n', jianpu_ly, workdir)

        # exponential probe, then bisect
        bad_at, n = None, 1
        while n <= len(bars):
            code, err = attempt(n)
            if code != 0:
                bad_at = n
                break
            n *= 2

        if bad_at is None:
            code, err = attempt(len(bars))
            if code == 0:
                print('no failure at any prefix; the file converts cleanly')
                return
            bad_at = len(bars)

        lo, hi = max(1, bad_at // 2), bad_at
        while lo < hi:
            mid = (lo + hi) // 2
            code, _ = attempt(mid)
            if code == 0:
                lo = mid + 1
            else:
                hi = mid

        print(f'first failing bar: {lo}')
        print('  bar text : ' + bars[lo - 1].strip())
        if lo >= 2:
            print('  previous : ' + bars[lo - 2].strip())
        code, err = attempt(lo)
        if err.strip():
            print('  message  : ' + err.strip().splitlines()[0][:300])


if __name__ == '__main__':
    if len(sys.argv) < 2:
        raise SystemExit('usage: find_bad_bar.py <file.jianpu.txt>')
    main(sys.argv[1])
