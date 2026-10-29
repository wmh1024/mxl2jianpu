"""Compare two jianpu inputs and mark the differences on the engraving.

The comparison works on musical content, not text: each bar becomes a list of
(figures, octave levels, dots, duration letter) per note group, so a bar that
merely changes spelling is not reported as a change.

Marking is done in LilyPond rather than by drawing on the PDF, because
jianpu-ly writes a ``%{ bar N: %}`` comment before every bar, which lets the
injection be exact.  A marked bar gets red notes, thick red bar lines and a red
boxed caption.
"""
from __future__ import annotations

import io
import re
from pathlib import Path

MARK = re.compile(r'^-?\d+=[A-Ga-g#b]{1,2}$|^-?\d+/\d+$|^\d+=\d+$')
SKIP = {'(', ')', '~', '|', '-', '[', ']', 'NextPart', 'OnePage',
        'NoBarNums', 'NoIndent', 'WithStaff', 'RaggedLast'}
TOKEN = re.compile(r"^(s|q|d|h)?([0-9,.'#b]+)$")
HEADER = ('title=', 'composer=', 'instrument=', 'OctavesBefore', 'WithStaff',
          'subtitle=', 'subsubtitle=', 'poet=', 'arranger=')


def parse_bars(path: str | Path) -> dict[int, list[tuple]]:
    """Canonical musical content of every bar in a jianpu-ly input file."""
    bars: dict[int, list[tuple]] = {}
    n = 0
    for ln in io.open(path, encoding='utf-8'):
        s = ln.strip()
        if not s or s.startswith(HEADER):
            continue
        if re.match(r'^\d+/\d+$', s) or MARK.match(s):
            continue
        n += 1
        groups = []
        for tok in s.split():
            if tok.startswith(('\\', '^', '_', 'Fr=', 'R*')) or tok in SKIP:
                continue
            if re.match(r'^[A-Za-z]+$', tok) or MARK.match(tok):
                continue
            m = TOKEN.match(tok)
            if not m:
                continue
            body = m.group(2)
            figs, levels, lvl = [], [], 0
            for ch in body:
                if ch == ',':
                    lvl -= 1
                elif ch == "'":
                    lvl += 1
                elif ch.isdigit():
                    figs.append(ch)
                    levels.append(lvl)
                    lvl = 0
            groups.append((tuple(figs), tuple(levels), body.count('.'), m.group(1) or ''))
        bars[n] = groups
    return bars


PREFIX_BEATS = {'q': 0.5, 's': 0.25, 'd': 0.125, 'h': 0.0625}


def bar_duration(groups) -> float:
    """Total length of a bar's parsed note groups, in quarter notes."""
    total = 0.0
    for figs, levels, dots, dur in groups:
        pre = dur if dur in PREFIX_BEATS else ''
        v = PREFIX_BEATS.get(pre, 1.0)
        if dots:
            v *= 1.5
        total += v
    return round(total, 4)


def sounding(groups) -> tuple:
    """The notes of a bar, ignoring rests and how they are spelled.

    Two spellings of the same bar (``q0 q0`` versus ``q0. q0. 0 -``) describe the
    same silence; what a review should report is a difference in the sounding
    notes, so rests are stripped here.
    """
    return tuple((figs, levels, dots, dur)
                 for figs, levels, dots, dur in groups if figs != ('0',))


def changed_bars(old: str | Path, new: str | Path,
                 notes_only: bool = False) -> list[int]:
    """Bar numbers whose content differs between two jianpu files.

    With `notes_only`, only the sounding notes are compared, so a bar that
    merely spells its rests differently is not reported.
    """
    a, b = parse_bars(old), parse_bars(new)
    if notes_only:
        return [i for i in sorted(set(a) | set(b))
                if sounding(a.get(i, [])) != sounding(b.get(i, []))]
    return [i for i in sorted(set(a) | set(b)) if a.get(i) != b.get(i)]


RED_OVERRIDES = (
    r'\once \override Staff.NoteHead.color = #red '
    r'\once \override Staff.Rest.color = #red '
    r'\once \override Staff.Stem.color = #red '
    r'\once \override Staff.Beam.color = #red '
    r'\once \override Staff.Slur.color = #red '
    r'\once \override Staff.Tie.color = #red '
    r'\once \override Staff.Dots.color = #red '
    r'\once \override Staff.Script.color = #red '
    r'\once \override Staff.TextScript.color = #red '
    r'\once \override Staff.Accidental.color = #red '
    r'\once \override Staff.BarLine.color = #red '
)

BAR_LINES = (r'\once \override Staff.BarLine.color = #red '
             r'\once \override Staff.BarLine.thickness = #3 ')


def _caption(text: str) -> str:
    return (r'\tweak X-offset #1 \mark \markup { \with-color #red \box '
            r'\fontsize #-3 \sans "' + text.replace('"', "'") + r'" } ')


def annotate(in_ly: str | Path, out_ly: str | Path, bars, label='已修正') -> int:
    """Write `out_ly`: a copy of `in_ly` with the listed bars highlighted."""
    wanted = set(bars)
    text = io.open(in_ly, encoding='utf-8').read()
    marker = re.compile(r'%\{\s*bar\s+(\d+):\s*%\}')
    pieces = marker.split(text)
    prefix, rest = pieces[0], pieces[1:]

    out = [prefix]
    marked = 0
    for i in range(0, len(rest) - 1, 2):
        num = int(rest[i])
        body = rest[i + 1]
        if num in wanted:
            marked += 1
            body = _caption(label) + BAR_LINES + RED_OVERRIDES + body
        out.append(f'%{{ bar {num}: %}}')
        out.append(body)

    io.open(out_ly, 'w', encoding='utf-8', newline='\n').write(''.join(out))
    return marked


def summary_line(bars: list[int]) -> str:
    """Compact description of a bar list, e.g. ``17,21,33-52``."""
    if not bars:
        return '(none)'
    runs, start, prev = [], bars[0], bars[0]
    for b in bars[1:]:
        if b == prev + 1:
            prev = b
            continue
        runs.append((start, prev))
        start = prev = b
    runs.append((start, prev))
    return ','.join(f'{a}-{b}' if b > a else f'{a}' for a, b in runs)
