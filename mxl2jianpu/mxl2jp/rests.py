"""Collapse adjacent rests in a jianpu token list.

Two consecutive rests must not be written as ``0 q0``; they are one longer
rest, which may itself need dashes (``0 -`` for two beats).  Rests also accept
the dash continuation exactly like notes do.
"""
from __future__ import annotations

REST_BEATS = {'': 1.0, 'q': 0.5, 's': 0.25, 'd': 0.125, 'h': 0.0625}


def rest_length(tok: str) -> float | None:
    """Length in quarter notes of a rest token, or None if it is not a rest."""
    body = tok.rstrip('.')
    if not body.endswith('0'):
        return None
    pref = body[:-1]
    if pref not in REST_BEATS:
        return None
    v = REST_BEATS[pref]
    if tok.endswith('.'):
        v *= 1.5
    return v


def merge_rests(tokens: list[str], emit) -> list[str]:
    """Merge consecutive rests (and dashes that extend them).

    `emit` is called with a total length and returns the tokens for it, so the
    caller keeps control of the dash rule.
    """
    out: list[str] = []
    pending = 0.0

    def flush():
        nonlocal pending
        if pending > 1e-9:
            out.extend(emit(pending))
            pending = 0.0

    i = 0
    n = len(tokens)
    while i < n:
        tok = tokens[i]
        length = rest_length(tok)
        if length is None:
            flush()
            out.append(tok)
            i += 1
            continue
        pending += length
        i += 1
        # absorb dashes that continue this rest
        while i < n and tokens[i] == '-':
            pending += 1.0
            i += 1
    flush()
    return out
