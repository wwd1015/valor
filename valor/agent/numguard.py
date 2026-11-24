"""Numbers in model-written text must come from the engine. This finds figures in a text that
do not appear, at the precision written, in the structured payload the model was given."""

from __future__ import annotations

import re

NUM = re.compile(r"(?<![\w.])[-+]?\$?\d{1,3}(?:,\d{3})+(?:\.\d+)?|(?<![\w.])[-+]?\$?\d+(?:\.\d+)?")
IGNORE = {0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 100}


def _parse(m: str) -> tuple[float, int] | None:
    raw = m.replace(",", "").replace("$", "").lstrip("+-")
    try:
        return float(raw), (len(raw.split(".")[1]) if "." in raw else 0)
    except ValueError:
        return None


def _collect(obj, out: list) -> None:
    if isinstance(obj, bool) or obj is None:
        return
    if isinstance(obj, (int, float)):
        out.extend((abs(obj), abs(obj) * 100))
    elif isinstance(obj, dict):
        for v in obj.values():
            _collect(v, out)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _collect(v, out)
    elif isinstance(obj, str):
        for m in NUM.findall(obj):
            p = _parse(m)
            if p:
                out.append(p[0])


def unverified_numbers(text: str, payload) -> list[str]:
    allowed: list = []
    _collect(payload, allowed)
    bad = []
    for m in NUM.findall(text or ""):
        p = _parse(m)
        if not p:
            continue
        v, d = p
        if v in IGNORE or (1990 <= v <= 2100 and d == 0):     # small counts and years
            continue
        # a figure may be written rounded (or truncated by one unit of its last decimal)
        tol = 10 ** -d
        if any(abs(round(a, d) - v) < 1e-9 or abs(a - v) < tol for a in allowed):
            continue
        bad.append(m.strip())
    return sorted(set(bad))
