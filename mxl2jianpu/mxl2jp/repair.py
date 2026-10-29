"""Repair the defects an OMR export usually carries.

Each repair is opt-in and reports exactly what it changed, so a score is never
silently rewritten.  The defaults do only what is safe for any file; the
score-specific fixes (time-signature overrides, tuplet removal) take explicit
arguments.

Repairs, in the order the CLI applies them:

  fill_bars        pad or trim every voice to the time signature
  flatten_voices   fold extra voices into chord tones on one line
  uniform_divs     rewrite every <duration> from <type> on one division grid
  renumber         renumber measures 1..n
  set_metadata     set title / composer / part name
  drop_tuplets     remove a spurious <time-modification> from given bars
"""
from __future__ import annotations

import copy
from pathlib import Path
from xml.etree import ElementTree as ET

from . import musicxml as mx

# (beats, <type>, dots) longest first
DURATION_TABLE = [
    (4.0, 'whole', 0), (3.0, 'half', 1), (2.0, 'half', 0), (1.5, 'quarter', 1),
    (1.0, 'quarter', 0), (0.75, 'eighth', 1), (0.5, 'eighth', 0),
    (0.375, '16th', 1), (0.25, '16th', 0), (0.125, '32nd', 0),
]


def dur_lookup(beats: float) -> tuple[str, int] | tuple[None, None]:
    for b, ty, dots in DURATION_TABLE:
        if abs(b - beats) < 1e-6:
            return ty, dots
    return None, None


def dur_at_most(beats: float) -> tuple[float, str, int] | tuple[None, None, None]:
    for b, ty, dots in DURATION_TABLE:
        if b <= beats + 1e-9:
            return b, ty, dots
    return None, None, None


def split_rests(beats: float, tolerance: float = 1e-3) -> list[float]:
    """Break a rest into writable note values, largest first.

    A tuplet leaves scraps shorter than a 32nd note (a sextuplet in 6/8, for
    instance).  Those cannot be written as one rest, and they carry no musical
    meaning at this scale, so a remainder below `tolerance` beats is folded
    into the previous rest instead of raising.
    """
    out: list[float] = []
    rem = round(beats, 6)
    while rem > 1e-6:
        for b, _, _ in DURATION_TABLE:
            if b <= rem + 1e-9:
                out.append(b)
                rem = round(rem - b, 6)
                break
        else:
            # remainder smaller than the shortest note value
            if rem <= tolerance:
                if out:
                    out[-1] = round(out[-1] + rem, 6)
                else:
                    out.append(rem)
                break
            raise ValueError(f'cannot express a rest of {rem:g} beats')
    return out


def set_length(note: ET.Element, beats: float, divisions: int,
               fit: bool = True) -> None:
    """Give a note the length `beats`, updating <duration>, <type> and dots.

    With `fit`, a length that no single note value can express is rounded down
    to the nearest one that can, because jianpu has no way to write a value
    between the tabulated ones (an OMR double dot lands on such a value).
    """
    ty, dots = dur_lookup(beats)
    if ty is None:
        if not fit:
            raise ValueError(f'{beats:g} beats has no single note value')
        fitted, ty, dots = dur_at_most(beats)
        if fitted is None:
            raise ValueError(f'{beats:g} beats is shorter than a 32nd note')
        beats = fitted
    dur = note.find('duration')
    if dur is None:
        dur = ET.SubElement(note, 'duration')
    dur.text = str(int(round(beats * divisions)))
    t = note.find('type')
    if t is None:
        t = ET.SubElement(note, 'type')
    t.text = ty
    for d in note.findall('dot'):
        note.remove(d)
    for _ in range(dots):
        ET.SubElement(note, 'dot')


def make_rest(beats: float, divisions: int, voice: str = '1') -> ET.Element:
    n = ET.Element('note')
    ET.SubElement(n, 'rest')
    set_length(n, beats, divisions)
    ET.SubElement(n, 'voice').text = voice
    return n


# --------------------------------------------------------------------------
# fill_bars
# --------------------------------------------------------------------------

def fill_bars(score: ET.Element) -> list[str]:
    """Make every voice of every bar exactly as long as its time signature."""
    log: list[str] = []
    part = score.find('part')
    if part is None:
        return log

    divisions, time = 1, (4, 4)
    for measure in part.findall('measure'):
        for attrs in measure.findall('attributes'):
            d = attrs.find('divisions')
            if d is not None:
                divisions = int(d.text)
            t = attrs.find('time')
            if t is not None and t.find('beats') is not None:
                time = (int(t.findtext('beats')), int(t.findtext('beat-type')))
        target = time[0] * 4.0 / time[1]
        log.extend(_fill_measure(measure, divisions, target))
    return log


def _segments(measure: ET.Element) -> list[list[ET.Element]]:
    """Split a measure on <backup> into one segment per pass."""
    segs, cur = [], []
    for child in list(measure):
        if child.tag == 'backup':
            segs.append(cur)
            cur = []
        else:
            cur.append(child)
    segs.append(cur)
    return segs


def _events_of(seg: list[ET.Element], divisions: int) -> list[ET.Element]:
    """The note/forward elements of a segment, in order."""
    return [el for el in seg if el.tag in ('note', 'forward')]


def _fill_measure(measure: ET.Element, divisions: int, target: float) -> list[str]:
    log: list[str] = []
    num = measure.get('number', '?')
    segs = _segments(measure)

    # group segments by voice, so a bar whose single voice is split by an
    # internal <backup> is handled as one voice rather than two passes
    per_voice: dict[str, list[ET.Element]] = {}
    order: list[str] = []
    for seg in segs:
        voice = '1'
        for el in seg:
            if el.tag in ('note', 'forward'):
                v = el.findtext('voice')
                if v:
                    voice = v
                    break
        per_voice.setdefault(voice, []).extend(_events_of(seg, divisions))
        if voice not in order:
            order.append(voice)

    for voice in order:
        events = per_voice[voice]

        # a length no note value can express is rounded down first, so the
        # arithmetic below works on writable values
        for el in events:
            if el.tag != 'note' or mx.is_chord(el) or mx.is_grace(el):
                continue
            beats = mx.beats_from_divisions(el, divisions)
            if beats > 0 and dur_lookup(beats)[0] is None:
                fitted, ty, dots = dur_at_most(beats)
                if fitted is not None:
                    log.append(f'  m{num} v{voice}: {beats:g} -> {fitted:g} '
                               f'(no note value for the original)')
                    set_length(el, fitted, divisions)

        total = 0.0
        for el in events:
            if el.tag == 'note':
                if mx.is_chord(el) or mx.is_grace(el):
                    continue
                total += mx.beats_from_divisions(el, divisions)
            else:
                total += int(el.findtext('duration') or 0) / divisions
        total = round(total, 6)

        # too long: drop trailing rests, then shorten the last note
        while total > target + 1e-6 and events:
            last = None
            for el in reversed(events):
                if el.tag == 'note' and not mx.is_chord(el) and not mx.is_grace(el):
                    last = el
                    break
            if last is None:
                break
            if mx.is_rest(last):
                events.remove(last)
                log.append(f'  m{num} v{voice}: removed a trailing rest')
            else:
                beats = mx.beats_from_divisions(last, divisions)
                over = round(total - target, 6)
                try:
                    set_length(last, round(beats - over, 6), divisions)
                    log.append(f'  m{num} v{voice}: shortened the last note by {over:g}')
                except ValueError:
                    events.remove(last)
                    log.append(f'  m{num} v{voice}: removed the final note')
            total = _total_of(events, divisions)

        # too short: pad with rests
        if total < target - 1e-6:
            short = round(target - total, 6)
            for chunk in split_rests(short):
                events.append(make_rest(chunk, divisions, voice))
            log.append(f'  m{num} v{voice}: padded {short:g} beats of rest')

    return log


def _total_of(events: list[ET.Element], divisions: int) -> float:
    total = 0.0
    for el in events:
        if el.tag == 'note':
            if mx.is_chord(el) or mx.is_grace(el):
                continue
            total += mx.beats_from_divisions(el, divisions)
        else:
            total += int(el.findtext('duration') or 0) / divisions
    return round(total, 6)


# --------------------------------------------------------------------------
# flatten_voices
# --------------------------------------------------------------------------

def flatten_voices(score: ET.Element) -> list[str]:
    """Reduce multi-voice bars to one line, keeping every sounding pitch.

    A note of another voice becomes a chord tone of the melody note sounding
    at that moment; if the melody is silent there it becomes its own event.
    """
    log: list[str] = []
    part = score.find('part')
    if part is None:
        return log

    for measure in part.findall('measure'):
        bar = next((b for b in mx.walk_bars(part) if b.number == measure.get('number')), None)
        if bar is None:
            continue
        voices = {e.voice for e in bar.events}
        if len(voices) <= 1:
            continue

        melody = [e for e in bar.events if e.voice == '1' and not e.rest and not e.chord]
        if not melody:
            melody = [e for e in bar.events if not e.rest and not e.chord]
        spans = [(e.onset, e.onset + e.duration) for e in melody]

        # Notes that are not the melody head: either an explicit <chord/> tone,
        # or a note of another voice, or a note that starts where a melody note
        # of the same voice is already sounding.  All of them must survive as
        # chord tones of whatever sounds at that moment.
        others: list[mx.Event] = []
        for e in bar.events:
            if e.rest:
                continue
            if e in melody:
                continue
            others.append(e)

        extras: list[mx.Event] = []
        chords: dict[tuple[float, float], list[tuple[ET.Element, float]]] = {}
        for e in others:
            host = None
            for mel, (a, b) in zip(melody, spans):
                if a - 1e-6 <= e.onset < b - 1e-6:
                    host = mel
                    break
            if host is None:
                extras.append(e)
            else:
                room = host.onset + host.duration - e.onset
                take = min(e.duration, room) if room > 1e-6 else e.duration
                key = (round(host.onset, 6), round(host.duration, 6))
                chords.setdefault(key, []).append((e.element, round(take, 6)))

        # rebuild the bar: melody events in order, each followed by the notes
        # folded into it, with the bar's <attributes>/<print> kept in front
        timeline = sorted(melody + extras, key=lambda e: e.onset)
        built: list[ET.Element] = []
        cursor = 0.0
        for ev in timeline:
            if ev.onset > cursor + 1e-6:
                for chunk in split_rests(round(ev.onset - cursor, 6)):
                    built.append(make_rest(chunk, bar.divisions))
                cursor = ev.onset
            if ev.onset < cursor - 1e-6:
                # starts inside a note that is still sounding: keep the pitch by
                # making it a chord tone of that note rather than dropping it
                anchor = None
                for back in reversed(built):
                    if back.find('rest') is None and back.find('chord') is None:
                        anchor = back
                        break
                if anchor is not None:
                    tone = copy.deepcopy(ev.element)
                    for c in tone.findall('chord'):
                        tone.remove(c)
                    tone.insert(0, ET.Element('chord'))
                    if tone.find('voice') is not None:
                        tone.find('voice').text = '1'
                    built.append(tone)
                continue
            el = ev.element
            for c in el.findall('chord'):
                el.remove(c)
            if el.find('voice') is not None:
                el.find('voice').text = '1'
            built.append(el)
            beats = mx.beats_from_divisions(el, bar.divisions)
            key = (round(ev.onset, 6), round(ev.duration, 6))
            for src, take in chords.get(key, []):
                tone = copy.deepcopy(src)
                for c in tone.findall('chord'):
                    tone.remove(c)
                tone.insert(0, ET.Element('chord'))
                for d in tone.findall('dot'):
                    tone.remove(d)
                # a chord tone may be longer than the head; keep the longest
                # value that still fits, never dropping the pitch
                want = min(take, beats)
                if dur_lookup(want)[0] is None:
                    fitted = dur_at_most(want)
                    if fitted[0] is None:
                        continue
                    want = fitted[0]
                try:
                    set_length(tone, want, bar.divisions)
                except ValueError:
                    continue
                if tone.find('voice') is not None:
                    tone.find('voice').text = '1'
                built.append(tone)
            cursor = round(ev.onset + beats, 6)

        head = [el for el in measure if el.tag in ('print', 'attributes')]
        tail = [el for el in measure if el.tag in ('barline', 'direction', 'sound')]
        for child in list(measure):
            measure.remove(child)
        for el in head + built + tail:
            measure.append(el)

        log.append(f'  m{bar.number}: {len(voices)} voices merged, '
                   f'{sum(len(v) for v in chords.values())} notes folded in')

    return log


# --------------------------------------------------------------------------
# uniform_divs
# --------------------------------------------------------------------------

def uniform_divisions(score: ET.Element, divisions: int = 96) -> list[str]:
    """Rewrite every <duration> from <type> on one division grid."""
    log: list[str] = []
    part = score.find('part')
    if part is None:
        return log
    measures = part.findall('measure')
    if not measures:
        return log

    # gap elements still use each bar's own divisions, so convert them first
    gaps = _rescale_gaps(part, divisions)

    first = measures[0]
    attrs = first.find('attributes')
    if attrs is None:
        attrs = ET.Element('attributes')
        first.insert(1 if first.find('print') is not None else 0, attrs)
    d = attrs.find('divisions')
    if d is None:
        d = ET.SubElement(attrs, 'divisions')
    d.text = str(divisions)
    attrs.remove(d)
    attrs.insert(0, d)

    for measure in measures[1:]:
        for a in measure.findall('attributes'):
            existing = a.find('divisions')
            if existing is not None:
                a.remove(existing)

    changed = 0
    for note in part.iter('note'):
        if mx.is_grace(note):
            continue
        beats = mx.beats_from_type(note)
        if beats is None:
            continue
        dur = note.find('duration')
        if dur is None:
            dur = ET.SubElement(note, 'duration')
        new = str(int(round(beats * divisions)))
        if dur.text != new:
            changed += 1
        dur.text = new
    log.append(f'  rewrote {changed} durations on a {divisions}/quarter grid')
    if gaps:
        log.append(f'  rescaled {gaps} backup/forward gaps')
    return log


def _rescale_gaps(part: ET.Element, new_divisions: int) -> int:
    """Convert <backup>/<forward> durations to the new division grid."""
    rescaled = 0
    divisions = 1
    for measure in part.findall('measure'):
        for a in measure.findall('attributes'):
            d = a.find('divisions')
            if d is not None:
                divisions = int(d.text)
        for el in measure:
            if el.tag not in ('backup', 'forward'):
                continue
            dur = el.find('duration')
            if dur is None or divisions == new_divisions:
                continue
            beats = int(dur.text or 0) / divisions
            dur.text = str(int(round(beats * new_divisions)))
            rescaled += 1
    return rescaled


# --------------------------------------------------------------------------
# small structural repairs
# --------------------------------------------------------------------------

def renumber(score: ET.Element) -> list[str]:
    part = score.find('part')
    if part is None:
        return []
    measures = part.findall('measure')
    for i, m in enumerate(measures, start=1):
        m.set('number', str(i))
        m.attrib.pop('implicit', None)
    return [f'  renumbered {len(measures)} measures']


def set_metadata(score: ET.Element, title: str | None = None,
                 composer: str | None = None,
                 part_name: str | None = None) -> list[str]:
    log: list[str] = []
    if title:
        work = score.find('work')
        if work is None:
            work = ET.Element('work')
            score.insert(0, work)
        wt = work.find('work-title')
        if wt is None:
            wt = ET.SubElement(work, 'work-title')
        wt.text = title
        log.append(f'  title = {title}')
    if composer:
        ident = score.find('identification')
        if ident is None:
            ident = ET.SubElement(score, 'identification')
        comp = next((c for c in ident.findall('creator')
                     if c.get('type') == 'composer'), None)
        if comp is None:
            comp = ET.Element('creator', {'type': 'composer'})
            ident.insert(0, comp)
        comp.text = composer
        log.append(f'  composer = {composer}')
    if part_name:
        for sp in score.iter('score-part'):
            for tag in ('part-name', 'part-abbreviation'):
                el = sp.find(tag)
                if el is not None:
                    el.text = part_name
        log.append(f'  part name = {part_name}')
    return log


def drop_tuplets(score: ET.Element, bars: list[str]) -> list[str]:
    """Remove spurious tuplet markings in the given bars and lengthen the notes.

    The stored <duration> is the compressed tuplet value; dropping the marking
    without rewriting it would leave the note sounding a third of a beat while
    claiming to be an eighth note, so the length is recomputed from <type>.
    """
    log: list[str] = []
    part = score.find('part')
    if part is None:
        return log
    wanted = {str(b).strip() for b in bars}
    for measure in part.findall('measure'):
        if str(measure.get('number')).strip() not in wanted:
            continue
        divisions = _divisions_of(measure, part)
        removed = 0
        for note in measure.findall('note'):
            tm = note.find('time-modification')
            if tm is None:
                continue
            note.remove(tm)
            removed += 1
            for nt in note.findall('notations'):
                for tp in nt.findall('tuplet'):
                    nt.remove(tp)
            ty = note.findtext('type')
            if ty in mx.TYPE_QUARTERS:
                beats = mx.TYPE_QUARTERS[ty]
                add = beats
                for _ in range(mx.dots_of(note)):
                    add /= 2
                    beats += add
                dur = note.find('duration')
                if dur is not None:
                    dur.text = str(int(round(beats * divisions)))
        if removed:
            log.append(f'  m{measure.get("number")}: '
                       f'tuplet removed from {removed} notes')
    return log


def _divisions_of(measure: ET.Element, part: ET.Element) -> int:
    """The divisions in force at this measure."""
    divisions = 1
    for m in part.findall('measure'):
        for a in m.findall('attributes'):
            d = a.find('divisions')
            if d is not None:
                divisions = int(d.text)
        if m is measure:
            return divisions
    return divisions


def save(score: ET.Element, path: str | Path) -> None:
    doctype = ('<!DOCTYPE score-partwise PUBLIC "-//Recordare//DTD MusicXML 4.0 '
               'Partwise//EN" "http://www.musicxml.org/dtds/partwise.dtd">')
    body = ET.tostring(score, encoding='unicode')
    Path(path).write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n' + doctype + '\n' + body + '\n',
        encoding='utf-8')
