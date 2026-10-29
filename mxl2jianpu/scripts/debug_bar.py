"""Debug one bar's token arithmetic by hand."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import check_bars as cb

LINE = sys.argv[1] if len(sys.argv) > 1 else 'q,6 q1 q,5 q,6 ,6 -'
toks = LINE.split()
total = 0.0
for t in toks:
    counted = cb.counts_as_time(t)
    val = cb.token_value(t) if counted else 0.0
    total += val
    print(f'  {t!r:12} counted={counted!s:5} value={val:g}')
print('total', total)
