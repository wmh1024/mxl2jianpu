"""Diagnose the defects an OMR export usually carries.

Audiveris/PhotoScore exports look plausible but often have bars that do not add
up, because the recogniser dropped a rest, invented a tuplet, or copied a
measure number twice.  Nothing downstream can be trusted until these are known,
so this module reports them before anything is converted.

The checks are deliberately mechanical — every finding is something that can be
proved from the file alone:

  * a voice whose total length differs from the time signature;
  * ``<duration>`` disagreeing with ``<type>``;
  * a ``<divisions>`` value that changes between bars;
  * duplicate measure numbers;
  * ``<chord/>`` notes that do not follow a note;
  * notes that would make a voice exceed its bar.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import musicxml as mx


@dataclass
class Finding:
    kind: str          # short machine-readable tag
    bar: str           # measure number
    detail: str        # human-readable explanation
    severity: str = 'warn'   # 'error' blocks conversion, 'warn' is informational

    def __str__(self) -> str:
        return f'[{self.severity}] bar {self.bar}: {self.kind} — {self.detail}'


def diagnose(path: str | Path) -> tuple[list[Finding], dict]:
    """Return (findings, summary) for a MusicXML file."""
    score = mx.read_score(path)
    summary = mx.describe(score)
    part = score.find('part')
    findings: list[Finding] = []

    if part is None:
        findings.append(Finding('no-part', '-', 'the file has no <part> element', 'error'))
        return findings, summary

    seen_numbers: dict[str, int] = {}
    last_divisions: int | None = None

    for bar in mx.walk_bars(part):
        num = bar.number
        seen_numbers[num] = seen_numbers.get(num, 0) + 1

        # divisions that wander between bars make <duration> values ambiguous
        if last_divisions is not None and bar.divisions != last_divisions:
            findings.append(Finding(
                'divisions-change', num,
                f'<divisions> changed {last_divisions} -> {bar.divisions}; '
                f'note lengths are not comparable across this boundary'
            ))
        last_divisions = bar.divisions

        # every voice must fill the bar exactly
        ends = mx.bar_spans(bar)
        target = bar.target
        for voice, end in ends.items():
            if abs(end - target) > 1e-6:
                over = end > target
                findings.append(Finding(
                    'bar-length', num,
                    f'voice {voice} covers {end:g} of {target:g} beats '
                    f'({"over" if over else "short"} by {abs(end - target):g})',
                    'error'
                ))

        # <duration> should agree with the printed <type>
        for e in bar.events:
            if e.chord or e.rest or e.duration == 0:
                continue
            declared = mx.beats_from_type(e.element, bar.divisions)
            if declared is None:
                continue
            if abs(declared - e.duration) > 1e-6:
                findings.append(Finding(
                    'duration-type', num,
                    f'<type> says {declared:g} beats but <duration> is '
                    f'{e.duration:g} (divisions={bar.divisions})'
                ))

        # a chord note must follow another note
        previous_was_note = False
        for child in bar.events:
            el = child.element
            if mx.is_chord(el) and not previous_was_note:
                findings.append(Finding(
                    'orphan-chord', num, '<chord/> note without a preceding note', 'error'
                ))
            previous_was_note = True

    for num, count in seen_numbers.items():
        if count > 1:
            findings.append(Finding(
                'duplicate-number', num,
                f'measure number {num} appears {count} times', 'error'
            ))

    summary['findings'] = len(findings)
    summary['errors'] = sum(1 for f in findings if f.severity == 'error')
    return findings, summary


def report(path: str | Path) -> str:
    """Human-readable diagnosis, suitable for a log or a console."""
    findings, summary = diagnose(path)
    lines = [
        f'file      : {path}',
        f'title     : {summary.get("title") or "(none)"}',
        f'composer  : {summary.get("composer") or "(none)"}',
        f'parts     : {", ".join(summary.get("parts") or []) or "(none)"}',
        f'bars      : {summary.get("bars")}',
        f'findings  : {summary.get("findings")} ({summary.get("errors")} errors)',
        '',
    ]
    if not findings:
        lines.append('no defects found.')
        return '\n'.join(lines)

    by_kind: dict[str, list[Finding]] = {}
    for f in findings:
        by_kind.setdefault(f.kind, []).append(f)
    for kind in sorted(by_kind):
        group = by_kind[kind]
        bars = [f.bar for f in group]
        shown = ', '.join(bars[:12]) + (' ...' if len(bars) > 12 else '')
        lines.append(f'{kind:<16} {len(group):>3} bars: {shown}')
        lines.append(f'{"":<16} {group[0].detail}')
    return '\n'.join(lines)
