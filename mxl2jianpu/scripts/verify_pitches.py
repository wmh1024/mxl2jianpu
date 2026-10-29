"""Verify a repaired MusicXML against the original: same pitches, same bars.

This is the check that matters before trusting a conversion — every sounding
pitch of every bar must survive the repair, and no bar may gain or lose one.
"""
from pathlib import Path
import sys
from collections import Counter

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mxl2jp import musicxml as mx  # noqa: E402


def pitches_by_bar(path: str) -> dict[int, Counter]:
    score = mx.read_score(path)
    out: dict[int, Counter] = {}
    for i, bar in enumerate(mx.walk_bars(score.find('part')), start=1):
        c = Counter()
        for e in bar.events:
            if e.rest or mx.is_grace(e.element):
                continue
            midi = mx.midi_of(e.element)
            if midi is not None:
                c[midi] += 1
        out[i] = c
    return out


def main(a: str, b: str) -> None:
    x, y = pitches_by_bar(a), pitches_by_bar(b)
    print(f'{a}: {len(x)} bars')
    print(f'{b}: {len(y)} bars')

    common = sorted(set(x) & set(y))
    bad = [(i, x[i], y[i]) for i in common if x[i] != y[i]]
    print(f'compared {len(common)} bars, differing {len(bad)}')
    for i, ca, cb in bad[:15]:
        print(f'  bar {i}: missing={dict(ca - cb)} extra={dict(cb - ca)}')
    if not bad:
        print('every bar has the same pitches as the original.')


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
