"""Check that the rendering chain works, without needing a score file.

Runs a tiny hand-written jianpu line through jianpu-ly and LilyPond and confirms
a PDF comes out. This is the environment self-check: it proves the two external
tools are wired up, and nothing about musical content.

    python mxl2jianpu/scripts/smoke_test.py
    python mxl2jianpu/scripts/smoke_test.py my-line.txt

Exit code 0 and `SMOKE PASS` on success; 1 with the failing stage otherwise.
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mxl2jp import render  # noqa: E402

DEFAULT = 'title=smoke\nOctavesBefore\n1=D\n4/4\n1 2 3 4 | 5 6 7 1 |\n'


def main(src: str | None) -> int:
    text = Path(src).read_text(encoding='utf-8') if src else DEFAULT

    jianpu_ly = render.find_jianpu_ly()
    lilypond = render.find_lilypond()

    print(f'lilypond : {lilypond}')
    print(f'jianpu-ly: {jianpu_ly}')

    if jianpu_ly is None:
        print('SMOKE FAIL: jianpu-ly not found (set MXL2JP_JIANPULY)', file=sys.stderr)
        return 1
    if lilypond is None:
        print('SMOKE FAIL: lilypond not found (set MXL2JP_LILYPOND)', file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        txt = tmp / 'smoke.jianpu.txt'
        txt.write_text(text, encoding='utf-8', newline='\n')

        ly = tmp / 'smoke.ly'
        ok, msg = render.run_jianpu_ly(jianpu_ly, txt, ly)
        if not ok:
            print('SMOKE FAIL: jianpu-ly rejected the sample', file=sys.stderr)
            print(msg[:600], file=sys.stderr)
            return 1
        print(f'jianpu-ly ok, {ly.stat().st_size} bytes of LilyPond')

        stem = tmp / 'smoke'
        ok, msg = render.run_lilypond(lilypond, ly, stem)
        pdf = stem.with_name(stem.name + '.pdf')
        if not ok or not pdf.exists():
            print('SMOKE FAIL: LilyPond did not produce a PDF', file=sys.stderr)
            print(msg[-800:], file=sys.stderr)
            return 1
        print(f'lilypond ok, {pdf.stat().st_size} bytes of PDF')

    print('SMOKE PASS')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else None))
