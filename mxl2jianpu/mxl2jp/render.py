"""Run jianpu-ly and LilyPond, and locate the external tools.

Tool discovery order: an explicit path, then ``$MXL2JP_<TOOL>``, then PATH, then
the usual install locations on Windows.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

WIN_ENTRY = SYSTEM = None  # placeholder kept for clarity


def _find_in_packages(root: Path, pattern: str) -> Path | None:
    if not root.exists():
        return None
    for hit in sorted(root.glob(pattern)):
        if hit.is_file():
            return hit
    return None


def find_lilypond() -> Path | None:
    """Locate lilypond.exe / lilypond."""
    env = os.environ.get('MXL2JP_LILYPOND')
    if env and Path(env).exists():
        return Path(env)

    found = shutil.which('lilypond')
    if found:
        return Path(found)

    local = Path(os.environ.get('LOCALAPPDATA', ''))
    winget = local / 'Microsoft' / 'WinGet' / 'Packages'
    hit = _find_in_packages(winget, 'LilyPond*/**/bin/lilypond.exe')
    if hit:
        return hit

    for base in (Path('C:/Program Files'), Path('C:/Program Files (x86)')):
        for name in ('LilyPond', 'lilypond'):
            direct = base / name / 'bin' / 'lilypond.exe'
            if direct.exists():
                return direct
    return None


def find_jianpu_ly() -> Path | None:
    """Locate jianpu-ly.py.

    Order: explicit env var, the copy vendored in this package, a `jianpu-ly` on
    PATH, then a sibling checkout used during development.
    """
    env = os.environ.get('MXL2JP_JIANPULY')
    if env and Path(env).exists():
        return Path(env)

    here = Path(__file__).resolve().parent
    vendored = here.parent / 'vendor' / 'jianpu-ly' / 'jianpu-ly.py'
    if vendored.exists():
        return vendored

    found = shutil.which('jianpu-ly')
    if found:
        return Path(found)

    for rel in ('../../work/jianpu-ly_src/jianpu-ly-master/jianpu-ly.py',
                '../../work/jianpu-ly_src/jianpu-ly-master/jianpu-ly.py'):
        cand = (here / rel).resolve()
        if cand.exists():
            return cand
    return None


def run_jianpu_ly(jianpu_ly: Path, txt: Path, out_ly: Path,
                  sloppy_bars: bool = True) -> tuple[bool, str]:
    """Convert a jianpu input file to a .ly file.  Returns (ok, message)."""
    env = dict(os.environ)
    env['PYTHONIOENCODING'] = 'utf-8'
    if sloppy_bars:
        env['j2ly_sloppy_bars'] = '1'

    cmd = ([sys.executable, str(jianpu_ly), str(txt)]
           if jianpu_ly.suffix == '.py' else [str(jianpu_ly), str(txt)])
    r = subprocess.run(cmd, capture_output=True, env=env)
    msg = r.stderr.decode('utf-8', 'replace').strip()
    if r.returncode != 0:
        return False, msg
    out_ly.write_bytes(r.stdout)
    return True, msg


def run_lilypond(lilypond: Path, ly: Path, stem: Path) -> tuple[bool, str]:
    """Engrave a .ly file to PDF.  Returns (ok, message)."""
    cmd = [str(lilypond), '-dno-point-and-click', '--pdf',
           '-o', str(stem), str(ly)]
    r = subprocess.run(cmd, capture_output=True)
    both = (r.stdout + r.stderr).decode('utf-8', 'replace')
    return 'Success' in both, both
