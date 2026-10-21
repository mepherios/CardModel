"""values — seeded input generation and value comparison shared by every witness.

Generator specs (data on cards):
  {"int": [lo, hi], "edges": [...]}   {"float": [lo, hi]}   {"choice": [v, ...]}   {"bool": true}
Int generators always include the edge values 0, 1, -1, lo and hi that lie
in range; a card may add a ``filter`` lambda (rejection sampling).

Comparison: ints and bools exactly (and never equal to each other), floats
with ``math.isclose(rel_tol=1e-12, abs_tol=1e-12)`` with NaN equal to NaN,
bytes/lists/dicts structurally.
"""
from __future__ import annotations

import math
import random

DEFAULT_GEN = {"int": {"int": [-1000, 1000]}, "float": {"float": [-1000.0, 1000.0]}, "bool": {"bool": True}}
REL_TOL = 1e-12


def specials(spec: dict) -> list:
    """Edge values always tried first: 0, 1, -1, the bounds, and any ``edges`` the spec lists."""
    if "int" in spec:
        lo, hi = spec["int"]
        return [v for v in (0, 1, -1, lo, hi, *spec.get("edges", [])) if lo <= v <= hi]
    if "float" in spec:
        lo, hi = spec["float"]
        return [v for v in (0.0, 1.0, -1.0, 0.5) if lo <= v <= hi]
    if "choice" in spec:
        return list(spec["choice"])
    if "bool" in spec:
        return [True, False]
    return []


def draw(spec: dict, rng: random.Random):
    if "int" in spec:
        lo, hi = spec["int"]
        return rng.randint(int(lo), int(hi))
    if "float" in spec:
        lo, hi = spec["float"]
        return rng.uniform(float(lo), float(hi))
    if "choice" in spec:
        return rng.choice(spec["choice"])
    if "bool" in spec:
        return rng.random() < 0.5
    raise ValueError(f"unknown generator {spec!r}")


def inputs(gens: list[dict], n: int, rng: random.Random, filt=None, edge: bool = True,
           max_tries: int = 20000) -> list[tuple]:
    """``n`` random argument tuples (plus edge combinations), deduplicated, in a stable order."""
    out: list[tuple] = []
    seen: set = set()

    def add(t):
        key = repr(t)
        if key in seen:
            return
        if filt is not None:
            try:
                if not filt(*t):
                    return
            except Exception:  # noqa: BLE001 -- a filter that raises rejects the tuple
                return
        seen.add(key)
        out.append(t)

    if edge and gens:
        edges = [specials(g) for g in gens]
        width = max(len(e) for e in edges)
        for i in range(width):
            add(tuple(e[i % len(e)] if e else draw(g, rng) for e, g in zip(edges, gens)))
    tries = 0
    target = len(out) + n
    while len(out) < target and tries < max_tries:
        tries += 1
        add(tuple(draw(g, rng) for g in gens))
    return out


def same(a, b) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if isinstance(a, float) or isinstance(b, float):
        if not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
            return False
        a, b = float(a), float(b)
        if math.isnan(a) or math.isnan(b):
            return math.isnan(a) and math.isnan(b)
        return math.isclose(a, b, rel_tol=REL_TOL, abs_tol=REL_TOL)
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b))
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(same(a[k], b[k]) for k in a)
    return a == b


def finite(v) -> bool:
    return not (isinstance(v, float) and (math.isnan(v) or math.isinf(v)))


def fits(v, bits: int | None) -> bool:
    if bits is None or isinstance(v, bool) or not isinstance(v, int):
        return True
    return -(2 ** (bits - 1)) <= v < 2 ** (bits - 1)


def fresh_seed() -> int:
    return random.SystemRandom().randrange(2**32)


def key(v):
    """A hashable identity for a value that never converts huge ints to text (Python limits int->str)."""
    if isinstance(v, int) and not isinstance(v, bool):
        return ("int", v % (2**61 - 1), v.bit_length(), v < 0)
    try:
        return ("h", hash(v))
    except TypeError:
        return ("r", repr(v)[:200])


def short(v):
    """A JSON-safe, size-bounded rendering of a value for reports."""
    if isinstance(v, int) and not isinstance(v, bool) and v.bit_length() > 256:
        return f"<int: {v.bit_length()} bits, ends ...{v % 10**12}>"
    if isinstance(v, (list, tuple)):
        return [short(x) for x in v[:20]]
    if isinstance(v, str) and len(v) > 300:
        return v[:300] + "..."
    return v
