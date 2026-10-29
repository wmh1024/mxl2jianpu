"""MusicXML reading shared by every stage of the pipeline.

Handles both plain ``.musicxml``/``.xml`` and compressed ``.mxl`` (a zip with a
``META-INF/container.xml``), and normalises the pitch spelling used throughout
the tool.
"""
from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator
from xml.etree import ElementTree as ET

STEP_SEMITONE = {'C': 0, 'D': 2, 'E': 4, 'F': 5, 'G': 7, 'A': 9, 'B': 11}
STEP_ORDER = {'C': 0, 'D': 1, 'E': 2, 'F': 3, 'G': 4, 'A': 5, 'B': 6}

# <type> -> length in quarter notes, before dots and time-modification
TYPE_QUARTERS = {
    'breve': 8.0, 'whole': 4.0, 'half': 2.0, 'quarter': 1.0,
    'eighth': 0.5, '16th': 0.25, '32nd': 0.125, '64th': 0.0625,
}


def read_score(path: str | Path) -> ET.Element:
    """Parse a MusicXML file, transparently unzipping ``.mxl``."""
    raw = Path(path).read_bytes()
    if raw[:2] == b'PK':
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            names = [n for n in z.namelist()
                     if n.lower().endswith(('.xml', '.musicxml'))
                     and 'META-INF' not in n]
            if not names:
                raise ValueError(f'{path}: no score part inside the archive')
            data = z.read(names[0])
    else:
        data = raw
    return ET.fromstring(data)


def midi_of(note: ET.Element) -> int | None:
    """Absolute MIDI pitch of a ``<note>`` element, or None for a rest."""
    p = note.find('pitch')
    if p is None:
        return None
    step = p.findtext('step') or 'C'
    octave = int(p.findtext('octave') or 4)
    alter = float(p.findtext('alter') or 0)
    return (octave + 1) * 12 + STEP_SEMITONE[step] + int(round(alter))


def note_type(note: ET.Element) -> str | None:
    return note.findtext('type')


def dots_of(note: ET.Element) -> int:
    return len(note.findall('dot'))


def beats_from_type(note: ET.Element, divisions: int | None = None) -> float | None:
    """Sounding length in quarter notes, from ``<type>`` (+ dots, + tuplet)."""
    ty = note.findtext('type')
    if ty not in TYPE_QUARTERS:
        return None
    b = TYPE_QUARTERS[ty]
    add = b
    for _ in range(dots_of(note)):
        add /= 2
        b += add
    tm = note.find('time-modification')
    if tm is not None:
        try:
            actual = int(tm.findtext('actual-notes') or 1)
            normal = int(tm.findtext('normal-notes') or 1)
            if actual:
                b = b * normal / actual
        except ValueError:
            pass
    return b


def beats_from_divisions(note: ET.Element, divisions: int) -> float:
    """Sounding length in quarter notes, from ``<duration>``."""
    if note.find('grace') is not None:
        return 0.0
    return int(note.findtext('duration') or 0) / divisions


def is_chord(note: ET.Element) -> bool:
    return note.find('chord') is not None


def is_rest(note: ET.Element) -> bool:
    return note.find('rest') is not None


def is_grace(note: ET.Element) -> bool:
    return note.find('grace') is not None


@dataclass
class Event:
    """One sounding thing on a bar's timeline."""
    onset: float          # quarter notes from the bar start
    duration: float
    element: ET.Element
    voice: str = '1'
    rest: bool = False
    chord: bool = False


@dataclass
class BarInfo:
    number: str
    divisions: int
    time: tuple[int, int]
    events: list[Event] = field(default_factory=list)

    @property
    def target(self) -> float:
        """Nominal length of the bar in quarter notes."""
        num, den = self.time
        return num * 4.0 / den


def walk_bars(part: ET.Element) -> Iterator[BarInfo]:
    """Yield each bar with its signature and the events on the global cursor."""
    divisions = 1
    time = (4, 4)
    for measure in part.findall('measure'):
        for attrs in measure.findall('attributes'):
            d = attrs.find('divisions')
            if d is not None:
                divisions = int(d.text)
            t = attrs.find('time')
            if t is not None and t.find('beats') is not None:
                time = (int(t.findtext('beats')), int(t.findtext('beat-type')))

        bar = BarInfo(number=measure.get('number', '?'), divisions=divisions, time=time)
        cursor = 0.0
        chord_onset = 0.0
        for child in measure:
            if child.tag == 'note':
                if is_grace(child):
                    continue
                voice = child.findtext('voice') or '1'
                if is_chord(child):
                    bar.events.append(Event(chord_onset, beats_from_divisions(child, divisions),
                                            child, voice, is_rest(child), True))
                    continue
                d = beats_from_divisions(child, divisions)
                chord_onset = cursor
                bar.events.append(Event(cursor, d, child, voice, is_rest(child), False))
                cursor += d
            elif child.tag == 'backup':
                cursor -= int(child.findtext('duration') or 0) / divisions
            elif child.tag == 'forward':
                cursor += int(child.findtext('duration') or 0) / divisions
        yield bar


def bar_spans(bar: BarInfo) -> dict[str, float]:
    """Total length each voice covers in the bar (its end position)."""
    ends: dict[str, float] = {}
    for e in bar.events:
        if e.chord:
            continue
        voice = e.voice
        ends.setdefault(voice, 0.0)
        ends[voice] = max(ends[voice], round(e.onset + e.duration, 6))
    return ends


def describe(score: ET.Element) -> dict[str, object]:
    """Small summary used by the report files."""
    part_list = score.find('part-list') or []
    names = [sp.findtext('part-name') or '' for sp in part_list.iter('score-part')]
    part = score.find('part')
    bars = len(part.findall('measure')) if part is not None else 0
    return {
        'title': (score.findtext('work/work-title')
                  or score.findtext('movement-title') or ''),
        'composer': (score.findtext('identification/creator') or ''),
        'parts': [n for n in names if n],
        'bars': bars,
    }
