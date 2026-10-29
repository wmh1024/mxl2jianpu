"""Check that every generated bar's tokens add up to its time signature.

This mirrors jianpu-ly's own bar arithmetic closely enough to find the first bar
that will make its bar check fail, which is the useful place to start debugging.
Tokens that carry no duration (marks, slurs, dynamics, bar lines) are skipped.
"""
import re
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mxl2jp import musicxml as mx, jianpu as jp          # noqa: E402
from mxl2jp.rests import rest_length                     # noqa: E402

PREFIX = {'q': 0.5, 's': 0.25, 'd': 0.125, 'h': 0.0625}

# marks and punctuation that consume no time
NO_TIME_PREFIX = ('\\', '^', '_', 'Fr=', 'R*')
NO_TIME_EXACT = {'(', ')', '~', '|', '[', ']', '{', '}', 'R{'}
DIRECTIVE = re.compile(r'^-?\d+=\d+$|^\d+/\d+$')
# a note token: optional duration letter, then figures with octave/accidental
NOTE = re.compile(r"^[sqdh]?[,']*[#b]?[0-9][0-9,.'#b]*$")
# a bare word such as letterA, Fine, DC
WORD = re.compile(r'^[A-Za-z]+$')


def token_value(tok: str) -> float:
    """Quarter-note length of one note or rest token."""
    if tok == '-':
        return 1.0
    rl = rest_length(tok)
    if rl is not None:
        return rl
    pre = tok[0] if tok[:1] in PREFIX else ''
    v = PREFIX.get(pre, 1.0)
    if tok.endswith('.'):
        v *= 1.5
    return v


def counts_as_time(tok: str) -> bool:
    """True when the token is a note, rest or continuation dash."""
    if not tok or tok in NO_TIME_EXACT:
        return False
    if tok == '-':
        return True                    # a dash adds one beat to the last note
    if tok.startswith(NO_TIME_PREFIX):
        return False
    if WORD.match(tok) or DIRECTIVE.match(tok):
        return False
    return bool(NOTE.match(tok))


def bar_total(tokens) -> float:
    return sum(token_value(t) for t in tokens if counts_as_time(t))


def main(path: str) -> None:
    score = mx.read_score(path)
    bars = jp.bars_to_jianpu(score)
    cum = 0.0
    off = 0
    for bar in bars:
        tot = bar_total(bar.tokens)
        cum += tot
        if abs(tot - bar.target) > 1e-6:
            off += 1
            print(f'm{bar.number:<4} total={tot:6.2f} target={bar.target:4.1f} '
                  f'cum={cum:8.2f} <-- OFF')
            print('       ' + ' '.join(bar.tokens))
    print(f'bars off: {off} of {len(bars)}')


if __name__ == '__main__':
    if len(sys.argv) < 2:
        raise SystemExit('usage: check_bars.py <score.musicxml>')
    main(sys.argv[1])
