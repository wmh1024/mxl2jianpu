"""Print the events of selected bars, for debugging the conversion."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mxl2jp import musicxml as mx  # noqa: E402

if len(sys.argv) < 2:
    raise SystemExit('usage: dump_bars.py <score.musicxml> [bar,bar,...]')
path = sys.argv[1]
wanted = set(sys.argv[2].split(',')) if len(sys.argv) > 2 else None

score = mx.read_score(path)
for bar in mx.walk_bars(score.find('part')):
    if wanted and bar.number not in wanted:
        continue
    print(f'=== m{bar.number}  time={bar.time} target={bar.target:g} '
          f'divisions={bar.divisions}')
    for e in bar.events:
        p = e.element.find('pitch')
        name = (p.findtext('step') + p.findtext('octave')) if p is not None else 'REST'
        ty = e.element.findtext('type')
        dots = mx.dots_of(e.element)
        print(f'  onset={e.onset:6.3f} dur={e.duration:6.3f} {name:5} '
              f'type={ty} dots={dots} rest={e.rest} chord={e.chord}')
