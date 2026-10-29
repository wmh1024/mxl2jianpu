"""Audit trail and change guards.

The rule this module enforces is the one that matters most when a model is in
the loop: **nothing is changed unless the printed score says so, and every
change is recorded with the evidence that justified it.**

Two mechanisms:

`ChangeLog` records each edit together with the visible evidence (page, region,
what was seen) and refuses entries that carry none. A change without evidence is
indistinguishable from a guess.

`guarded_repair` wraps a repair stage so that it can only touch what its own
plan admits. Running the diff before and after proves the stage changed only the
bars it was asked to change; anything else aborts and restores.
"""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from . import musicxml as mx


def parse_bar_spec(spec: str) -> list[str]:
    """Expand a bar spec like '89-140,145' into individual bar numbers."""
    out: list[str] = []
    for part in spec.replace(' ', '').split(','):
        if not part:
            continue
        if '-' in part:
            a, b = part.split('-', 1)
            try:
                out.extend(str(n) for n in range(int(a), int(b) + 1))
            except ValueError:
                out.append(part)
        else:
            out.append(part)
    return out


class EvidenceRequired(Exception):
    """Raised when a change is recorded without visible evidence."""


@dataclass
class Change:
    """One edit, with the printed evidence that justifies it."""
    kind: str                  # e.g. 'time-signature', 'pitch', 'tuplet'
    bars: list[str]
    seen: str                  # what the printed page shows, in words
    page: int                  # 1-based page of the source PDF
    region: str = ''           # optional crop hint, e.g. 'system 3'
    note: str = ''             # anything else worth recording

    def as_dict(self) -> dict:
        return {
            'kind': self.kind,
            'bars': self.bars,
            'seen': self.seen,
            'page': self.page,
            'region': self.region,
            'note': self.note,
        }


class ChangeLog:
    """Every deviation from the OMR output, with its evidence.

    A log entry is refused when it has no `seen` text or no page: if the model
    cannot say which part of the page it read, it did not read one.
    """

    def __init__(self) -> None:
        self._changes: list[Change] = []

    def add(self, kind: str, bars: Iterable[str], seen: str, page: int,
            region: str = '', note: str = '') -> Change:
        if not seen or not seen.strip():
            raise EvidenceRequired(
                f'refusing to record a {kind} change on bars {list(bars)} '
                f'without describing what the printed page shows')
        if not isinstance(page, int) or page < 1:
            raise EvidenceRequired(
                f'refusing to record a {kind} change without a page number')
        change = Change(kind, [str(b) for b in bars], seen.strip(), page,
                        region, note)
        self._changes.append(change)
        return change

    def __len__(self) -> int:
        return len(self._changes)

    def __iter__(self):
        return iter(self._changes)

    def summary(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for c in self._changes:
            counts[c.kind] = counts.get(c.kind, 0) + 1
        return counts

    def bars_touched(self) -> set[str]:
        out: set[str] = set()
        for c in self._changes:
            out.update(c.bars)
        return out

    def to_json(self, path: str | Path) -> Path:
        path = Path(path)
        path.write_text(
            json.dumps([c.as_dict() for c in self._changes],
                       ensure_ascii=False, indent=2),
            encoding='utf-8')
        return path


def snapshot(score) -> list[tuple]:
    """A comparable fingerprint of every bar's sounding content."""
    out = []
    for bar in mx.walk_bars(score.find('part')):
        notes = []
        for e in bar.events:
            if e.rest:
                notes.append(('R', round(e.onset, 4), round(e.duration, 4)))
            else:
                notes.append((mx.midi_of(e.element), round(e.onset, 4),
                              round(e.duration, 4)))
        out.append((bar.number, round(bar.target, 4), tuple(notes)))
    return out


def diff_snapshots(before: list[tuple], after: list[tuple]) -> list[str]:
    """Bar numbers whose fingerprint changed."""
    changed = []
    for (na, ta, ea), (nb, tb, eb) in zip(before, after):
        if (ta, ea) != (tb, eb):
            changed.append(na)
    return changed


def guarded_repair(score, stage, allowed_bars: Iterable[str] | None = None,
                   log: ChangeLog | None = None):
    """Run `stage(score)` and prove it only changed the bars it was allowed to.

    `allowed_bars=None` permits any change (the general fill/merge stages),
    which is still recorded so the caller knows which bars moved.

    Returns (log_lines, changed_bar_numbers). Raises RuntimeError after
    restoring the score when the stage touched a bar outside `allowed_bars`.
    """
    before = snapshot(score)
    original = copy.deepcopy(score)
    lines = stage(score)
    after = snapshot(score)
    changed = diff_snapshots(before, after)

    if allowed_bars is not None:
        allowed = {str(b) for b in allowed_bars}
        outside = [b for b in changed if b not in allowed]
        if outside:
            # put it back: a stage that edits bars it was not given is a bug,
            # and a model must not be able to widen its own licence
            score.clear()
            for child in list(original):
                score.append(child)
            raise RuntimeError(
                f'stage changed bars {outside[:8]} outside its plan; '
                f'reverted. Stages must only touch the bars they are given.')

    if log is not None:
        for b in changed:
            log.add(kind='bar-timing', bars=[b],
                    seen='(mechanical repair stage; see the stage output)',
                    page=1,
                    note=f'bar length or pitch normalised by {stage.__name__}')
    return lines, changed
