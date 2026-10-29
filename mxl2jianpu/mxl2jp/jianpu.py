"""Convert MusicXML note events to jianpu-ly tokens.

Fixed-do to movable-do conversion, with the octave convention jianpu-ly actually
engraves.  That convention matters and is easy to get wrong:

jianpu-ly realises ``1=X`` as ``\\transpose c X`` starting from a bare ``c``,
which is C3.  A figure written without octave marks therefore sounds X3 when X
is G, A or B, and X4 when X is C, D, E or F.  The reference octave used here
follows the same rule, so the marks a person would write by hand are the marks
produced here.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import musicxml as mx
from .marks import bar_marks, marks_of
from .repair import DURATION_TABLE, dur_lookup, split_rests
from .rests import merge_rests

# fifths -> tonic letter, walking the circle of fifths from C
CIRCLE = ['C', 'G', 'D', 'A', 'E', 'B', 'F#']

# key spelling with the accidentals musicians actually write
KEY_SPELLING = {
    0: 'C', 1: 'G', 2: 'D', 3: 'A', 4: 'E', 5: 'B', 6: 'F#', 7: 'C#',
    -1: 'F', -2: 'Bb', -3: 'Eb', -4: 'Ab', -5: 'Db', -6: 'Gb', -7: 'Cb',
}

DURATION_PREFIX = {
    'whole': '', 'half': '', 'quarter': '',
    'eighth': 'q', '16th': 's', '32nd': 'd', '64th': 'h',
}


def tonic_of(fifths: int) -> str:
    """Tonic letter for a key signature (C=0, G=1, D=2, ... F=-1)."""
    return CIRCLE[fifths % 7]


def key_accidentals(fifths: int) -> dict[str, int]:
    """Which steps the key signature alters: {'F': 1, 'C': 1} for D major."""
    out: dict[str, int] = {}
    sharps = ['F', 'C', 'G', 'D', 'A', 'E', 'B']
    flats = ['B', 'E', 'A', 'D', 'G', 'C', 'F']
    if fifths > 0:
        for step in sharps[:fifths]:
            out[step] = 1
    elif fifths < 0:
        for step in flats[:(-fifths)]:
            out[step] = -1
    return out


def to_jianpu(step: str, octave: int, alter: float | None,
              fifths: int) -> tuple[int, str, int]:
    """Return (degree 1-7, accidental ''/'#'/'b', signed octave level)."""
    tonic = tonic_of(fifths)
    key_acc = key_accidentals(fifths).get(step, 0)
    eff = float(key_acc) if alter is None else float(alter)

    # unmarked figures centre on the tonic in octave 3 for G/A/B, else octave 4
    tonic_octave = 3 if tonic in ('G', 'A', 'B') else 4
    d_tone = ((mx.STEP_ORDER[step] + 7 * octave)
              - (mx.STEP_ORDER[tonic] + 7 * tonic_octave))

    degree = d_tone % 7 + 1
    level = d_tone // 7

    if key_acc != 0:
        if abs(eff - key_acc) < 1e-9:
            acc = ''
        elif abs(eff) < 1e-9:
            acc = 'b' if key_acc == 1 else '#'
        else:
            acc = '#' if eff > 0 else 'b'
    else:
        acc = '' if abs(eff) < 1e-9 else ('#' if eff > 0 else 'b')

    return degree, acc, level


def _marks(level: int) -> str:
    return ',' * (-level) if level < 0 else "'" * level


def pitch_token(step: str, octave: int, alter: float | None, fifths: int,
                octaves_before: bool = True) -> str:
    """Pitch part of a token, e.g. ``,6`` / ``3'`` / ``#4``."""
    degree, acc, level = to_jianpu(step, octave, alter, fifths)
    return _marks(level) + acc + str(degree) if octaves_before \
        else acc + str(degree) + _marks(level)


def dashes_for(beats: float, dots: int = 0) -> list[str]:
    """The ``-`` continuation marks that lengthen a note past one beat.

    jianpu writes a half note as ``2 -``, a dotted half as ``2 - -`` and a
    whole note as ``1 - - -``: the figure means one beat and every dash adds
    another.  Shorter values carry a duration letter instead and take no dash.
    """
    return ['-'] * max(0, int(round(beats - 1.0)))


def note_token(event: mx.Event, fifths: int, octaves_before: bool = True) -> tuple[str, list[str]]:
    """A full token plus any continuation dashes: (token, ['-', ...])."""
    el = event.element
    ntype = el.findtext('type') or 'quarter'
    dots = mx.dots_of(el)
    pref = DURATION_PREFIX.get(ntype, '')
    token = pref + pitch_token(
        el.findtext('pitch/step'), int(el.findtext('pitch/octave')),
        float(el.findtext('pitch/alter')) if el.findtext('pitch/alter') else None,
        fifths, octaves_before) + ('.' if dots else '')
    dashes = [] if pref else dashes_for(event.duration, dots)
    return token, dashes


def chord_token(events: list[mx.Event], fifths: int,
                octaves_before: bool = True) -> tuple[str, list[str]]:
    """One token for simultaneous notes: ``q3,6`` (jianpu-ly's chord spelling)."""
    el = events[0].element
    ntype = el.findtext('type') or 'quarter'
    dots = mx.dots_of(el)
    pref = DURATION_PREFIX.get(ntype, '')
    figs = []
    for e in events:
        e_el = e.element
        alt = e_el.findtext('pitch/alter')
        figs.append(pitch_token(
            e_el.findtext('pitch/step'), int(e_el.findtext('pitch/octave')),
            float(alt) if alt else None, fifths, octaves_before))
    # a chord is written with one duration; take the longest tone so nothing is
    # cut short, and keep the dot only when that tone really is dotted
    longest = max(events, key=lambda e: e.duration)
    beats = longest.duration
    dotted = mx.dots_of(longest.element) > 0
    dashes = [] if pref else dashes_for(beats, 1 if dotted else 0)
    return pref + ''.join(figs) + ('.' if dotted else ''), dashes

def rest_tokens(beats: float) -> list[str]:
    """Rests covering `beats`, written the way jianpu writes rests.

    A rest of one beat is ``0``; each extra beat is another ``-``, so two beats
    read ``0 -`` and a whole-bar rest reads ``0 - - -``.  Anything that does
    not land on a beat boundary is split into exact note values first, so a
    half-beat remainder becomes ``q0`` rather than being rounded away.
    """
    out: list[str] = []
    rem = round(beats, 6)
    while rem > 1e-6:
        # a whole number of beats is written as 0 followed by dashes; a dotted
        # value is only used when the remainder genuinely needs it
        whole = int(rem)
        if whole >= 1 and abs(rem - whole) < 1e-6:
            out.append('0')
            out.extend(['-'] * (whole - 1))
            rem = 0.0
            continue
        ty, dots = dur_lookup(rem)
        if ty is not None and not DURATION_PREFIX.get(ty, ''):
            out.append('0' + ('.' if dots else ''))
            rem = 0.0
            continue
        # shorter values take a duration letter and no dash
        chunk = None
        for value, ty2, dots2 in DURATION_TABLE:
            if value <= rem + 1e-9 and DURATION_PREFIX.get(ty2, ''):
                chunk = (value, ty2, dots2)
                break
        if chunk is None:
            # only a beat-or-longer value is left
            chunk = (rem, None, 0)
        value, ty2, dots2 = chunk
        if ty2 is None:
            whole = int(round(value))
            out.append('0')
            out.extend(['-'] * max(0, whole - 1))
        else:
            out.append(DURATION_PREFIX.get(ty2, '') + '0' + ('.' if dots2 else ''))
        rem = round(rem - value, 6)
    return out


def rest_token(beats: float) -> str:
    ty, dots = dur_lookup(beats)
    return DURATION_PREFIX.get(ty or '', '') + '0' + ('.' if dots else '')


@dataclass
class BarTokens:
    number: str
    fifths: int
    time: tuple[int, int]
    tokens: list[str]

    @property
    def target(self) -> float:
        """Nominal length of the bar in quarter notes."""
        return self.time[0] * 4.0 / self.time[1]


def bars_to_jianpu(score, octaves_before: bool = True) -> list[BarTokens]:
    """Every bar of the first part, as jianpu tokens."""
    part = score.find('part')
    if part is None:
        return []

    measures = part.findall('measure')
    fifths = 0

    out: list[BarTokens] = []
    for index, bar in enumerate(mx.walk_bars(part)):
        measure = measures[index]
        for attrs in measure.findall('attributes'):
            k = attrs.find('key')
            if k is not None and k.find('fifths') is not None:
                fifths = int(k.findtext('fifths'))

        # direction-level marks belong at the head of the bar: tempo, dynamics,
        # wedges, text and the rehearsal letter
        bm = bar_marks(measure)
        head: list[str] = []
        if bm.rehearsal:
            head.append(bm.rehearsal)
        if bm.tempo:
            head.append(bm.tempo)
        head.extend(bm.words)
        head.extend(bm.wedges)
        head.extend(bm.dynamics)
        if bm.repeat_start:
            head.append('R{')

        # group simultaneous events so they become one chord token; an event
        # that starts inside a still-sounding note is folded into it, which
        # keeps one rhythm on the line and avoids phantom gaps.
        # A note without an explicit <chord/> may still begin where another
        # note is already sounding (OMR exports do this for a second voice
        # inside the same <voice>), so grouping is by onset, not by the flag.
        starts: dict[float, list[mx.Event]] = {}
        for e in bar.events:
            if e.rest or mx.is_grace(e.element):
                continue
            starts.setdefault(round(e.onset, 6), []).append(e)

        tokens: list[str] = list(head)
        cursor = 0.0
        for onset in sorted(starts):
            group = starts[onset]

            # silence before this onset
            if onset > cursor + 1e-6:
                tokens.extend(rest_tokens(round(onset - cursor, 6)))
                cursor = onset

            if len(group) > 1:
                tok, dashes = chord_token(group, fifths, octaves_before)
                marks = marks_of(group[0].element)
            else:
                tok, dashes = note_token(group[0], fifths, octaves_before)
                marks = marks_of(group[0].element)

            # a note starting inside a still-sounding one is a chord tone of it
            if onset < cursor - 1e-6 and tokens and not _is_rest_token(tokens[-1]):
                prev = tokens[-1]
                pref, body = _split_prefix(prev)
                extra_pref, extra_body = _split_prefix(tok)
                dots = '.' if body.endswith('.') else ''
                tokens[-1] = pref + body.rstrip('.') + extra_body.rstrip('.') + dots
                continue

            # slurs open before the note; ties and slurs close after it
            tokens.extend(marks.tokens_start())
            tokens.append(tok)
            extras = marks.extras()
            if extras:
                tokens.extend(extras)
            tokens.extend(dashes)
            tokens.extend(marks.tokens_end())
            cursor = round(onset + group[0].duration, 6)

        # a bar's trailing silence still has to be written, or the bar comes up
        # short and jianpu-ly's own bar check fails on the next one
        if cursor < bar.target - 1e-6:
            tokens.extend(rest_tokens(round(bar.target - cursor, 6)))

        # adjacent rests are written as one longer rest, not as two tokens
        tokens = merge_rests(tokens, rest_tokens)

        if bm.repeat_end:
            tokens.append('}')
        if bm.final:
            tokens.append(r'\bar "|."')

        out.append(BarTokens(bar.number, fifths, bar.time, tokens))
    return out


def _is_rest_token(tok: str) -> bool:
    return '0' in tok.split('.')[0][-1:]


def _split_prefix(tok: str) -> tuple[str, str]:
    """Split a token into its duration letter and the rest."""
    if tok[:1] in ('s', 'q', 'd', 'h'):
        return tok[0], tok[1:]
    return '', tok


def key_line(fifths: int) -> str:
    return f'1={KEY_SPELLING.get(fifths, tonic_of(fifths))}'


def render_jianpu(score, title: str = '', composer: str = '',
                  instrument: str = '', octaves_before: bool = True) -> str:
    """Full jianpu-ly input for the first part of a score."""
    bars = bars_to_jianpu(score, octaves_before)
    lines: list[str] = []
    if title:
        lines.append(f'title={title}')
    if composer:
        lines.append(f'composer={composer}')
    if instrument:
        lines.append(f'instrument={instrument}')
    lines.append('OctavesBefore' if octaves_before else 'OctavesAfter')

    fifths = None
    time = None
    for bar in bars:
        if bar.fifths != fifths:
            fifths = bar.fifths
            lines.append(key_line(fifths))
        if bar.time != time:
            time = bar.time
            lines.append(f'{time[0]}/{time[1]}')
        lines.append(' '.join(bar.tokens) if bar.tokens else 'R*1')
    return '\n'.join(lines) + '\n'
