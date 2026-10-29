"""Extract the markings a jianpu line needs beyond notes and rests.

jianpu-ly accepts articulations, dynamics, slurs, ties and rehearsal marks as
separate tokens on the same line.  An OMR export stores them inside
``<notations>`` and ``<direction>``, so they are collected here and emitted in
the order they occur in the bar.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from xml.etree import ElementTree as ET

from . import musicxml as mx

# <articulations> children -> jianpu token
ARTICULATION = {
    'staccato': 'Fr=▼',
    'staccatissimo': r'\staccatissimo',
    'accent': 'Fr=>',
    'strong-accent': r'\accent',
    'tenuto': 'Fr=_',
    'marcato': r'\marcato',
    'fermata': r'\fermata',
    'breath-mark': r'\breathe',
    'up-bow': r'\upbow',
    'down-bow': r'\downbow',
}

# <technical> children -> jianpu token
TECHNICAL = {
    'open': 'Fr=0',
    'snap-pizzicato': 'Fr=up',
    'stopped': r'\stopped',
}

# <dynamics> children -> lilypond dynamic
DYNAMIC = {'p', 'pp', 'ppp', 'pppp', 'f', 'ff', 'fff', 'ffff',
           'mp', 'mf', 'sf', 'sfz', 'fp'}


@dataclass
class NoteMarks:
    """Everything attached to one note."""
    articulation: list[str] = field(default_factory=list)
    technical: list[str] = field(default_factory=list)
    dynamic: str | None = None
    slur_start: bool = False
    slur_stop: bool = False
    tie_start: bool = False
    tie_stop: bool = False

    def tokens_start(self) -> list[str]:
        """Tokens that go before the note."""
        out: list[str] = []
        if self.slur_start:
            out.append('(')
        return out

    def tokens_end(self) -> list[str]:
        """Tokens that go after the note."""
        out: list[str] = []
        if self.tie_start:
            out.append('~')
        if self.slur_stop:
            out.append(')')
        return out

    def extras(self) -> list[str]:
        """Articulation / technique / dynamic marks written after the figure."""
        out = list(self.articulation) + list(self.technical)
        if self.dynamic:
            out.append(self.dynamic)
        return out


def marks_of(note: ET.Element) -> NoteMarks:
    """Collect the markings of one ``<note>``."""
    m = NoteMarks()
    for notations in note.findall('notations'):
        for art in notations.findall('articulations'):
            for child in art:
                tok = ARTICULATION.get(child.tag)
                if tok and tok not in m.articulation:
                    m.articulation.append(tok)
        for tech in notations.findall('technical'):
            for child in tech:
                if child.tag == 'fingering' and child.text:
                    tok = f'Fr={child.text.strip()}'
                    if tok not in m.technical:
                        m.technical.append(tok)
                elif child.tag in TECHNICAL:
                    tok = TECHNICAL[child.tag]
                    if tok not in m.technical:
                        m.technical.append(tok)
        for t in notations.findall('tied'):
            if t.get('type') == 'start':
                m.tie_start = True
            elif t.get('type') == 'stop':
                m.tie_stop = True
        for s in notations.findall('slur'):
            if s.get('type') == 'start':
                m.slur_start = True
            elif s.get('type') == 'stop':
                m.slur_stop = True
    for t in note.findall('tie'):
        if t.get('type') == 'start':
            m.tie_start = True
        elif t.get('type') == 'stop':
            m.tie_stop = True
    for dyn in note.findall('notations/dynamics'):
        for child in dyn:
            if child.tag in DYNAMIC:
                m.dynamic = '\\' + child.tag
    return m


RESTART_TEXT = {'Segno': 'Segno', 'Coda': 'ToCoda', 'Fine': 'Fine'}


@dataclass
class BarMarks:
    """Direction-level marks placed at the start of a bar."""
    tempo: str | None = None
    dynamics: list[str] = field(default_factory=list)
    words: list[str] = field(default_factory=list)
    wedges: list[str] = field(default_factory=list)
    rehearsal: str | None = None
    repeat_start: bool = False
    repeat_end: bool = False
    final: bool = False


def bar_marks(measure: ET.Element) -> BarMarks:
    """Collect ``<direction>`` and ``<barline>`` information for one bar."""
    out = BarMarks()
    for direction in measure.findall('direction'):
        for dt in direction.findall('direction-type'):
            met = dt.find('metronome')
            if met is not None:
                unit = met.findtext('beat-unit') or 'quarter'
                per = met.findtext('per-minute')
                if per:
                    dur = {'whole': '1', 'half': '2', 'quarter': '4',
                           'eighth': '8', '16th': '16'}.get(unit, '4')
                    out.tempo = f'{dur}={per}'
            dyn = dt.find('dynamics')
            if dyn is not None:
                for child in dyn:
                    if child.tag in DYNAMIC:
                        tok = '\\' + child.tag
                        if tok not in out.dynamics:
                            out.dynamics.append(tok)
            words = dt.find('words')
            if words is not None and (words.text or '').strip():
                text = words.text.strip().replace('"', "'")
                place = direction.get('placement', 'above')
                out.words.append(f'_{chr(34)}{text}{chr(34)}' if place == 'below'
                                 else f'^{chr(34)}{text}{chr(34)}')
            wedge = dt.find('wedge')
            if wedge is not None:
                kind = wedge.get('type')
                out.wedges.append({'crescendo': r'\<', 'diminuendo': r'\>',
                                   'stop': r'\!'}.get(kind, ''))
        rehearsal = direction.find('direction-type/rehearsal')
        if rehearsal is not None and rehearsal.text:
            out.rehearsal = _rehearsal_token(rehearsal.text.strip())

    for barline in measure.findall('barline'):
        repeat = barline.find('repeat')
        if repeat is not None:
            if repeat.get('direction') == 'forward':
                out.repeat_start = True
            elif repeat.get('direction') == 'backward':
                out.repeat_end = True
        style = barline.findtext('bar-style')
        if style in ('light-heavy', 'final'):
            out.final = True

    out.wedges = [w for w in out.wedges if w]
    return out


def _rehearsal_token(text: str) -> str:
    """A rehearsal mark as jianpu-ly spells it: letterA, letterB, letter3..."""
    cleaned = ''.join(ch for ch in text if ch.isalnum())
    if not cleaned:
        return ''
    if cleaned[0].isdigit():
        return 'letter' + cleaned
    return 'letter' + cleaned.upper()
