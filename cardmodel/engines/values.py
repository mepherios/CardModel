"""values — seeded input generation and value comparison shared by every witness.

Generator specs (data on cards):
  {"int": [lo, hi], "edges": [...]}   {"float": [lo, hi]}   {"choice": [v, ...]}   {"bool": true}
  {"list": <element spec>, "len": [lo, hi]}   a list of random length
  {"list": <element spec>, "len_of": [i, j]}  a list whose length is the product of the int arguments at
                                              positions i, j (a matrix with dimensions passed beside it)
  {"list": <element spec>, "len_like": i}     a list as long as the list argument at position i
Int generators always include the edge values 0, 1, -1, lo and hi that lie
in range; a card may add a ``filter`` lambda (rejection sampling).

Comparison: ints and bools exactly (and never equal to each other), floats
with ``math.isclose(rel_tol=1e-12, abs_tol=1e-12)`` with NaN equal to NaN,
bytes/lists/dicts structurally. ``signed_zero=True`` also tells -0.0 from +0.0
when both sides are zero (they differ observably: 1/x, atan2, copysign); the op
x language matrix compares that way, so a target that drops the sign of a zero
(Go's constant -0.0 is +0) fails a cell instead of passing unnoticed.
"""
from __future__ import annotations

import math
import random

DEFAULT_GEN = {"int": {"int": [-1000, 1000]}, "float": {"float": [-1000.0, 1000.0]}, "bool": {"bool": True},
               # the fixed-width sorts: their whole range, so overflow is sampled at the edges
               "u8": {"int": [0, 255]}, "u16": {"int": [0, 65535]}, "u32": {"int": [0, 2 ** 32 - 1]},
               "i8": {"int": [-128, 127]}, "i16": {"int": [-32768, 32767]}, "i32": {"int": [-2 ** 31, 2 ** 31 - 1]},
               "f32": {"float": [-1000.0, 1000.0]}}
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
    return []           # lists: drawn, never edge-enumerated (their length may depend on other arguments)


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
    if "list" in spec:
        if "len_of" in spec or "len_like" in spec:
            return None                     # filled by _lists once the other arguments are drawn
        lo, hi = spec.get("len", [0, 6])
        return [draw(spec["list"], rng) for _ in range(rng.randint(int(lo), int(hi)))]
    raise ValueError(f"unknown generator {spec!r}")


def _lists(t: tuple, gens: list[dict], rng: random.Random) -> tuple:
    """Fill the lists whose length is a product of other (int) arguments."""
    if not any("len_of" in g or "len_like" in g for g in gens):
        return t
    out = list(t)
    for i, g in enumerate(gens):
        if "len_of" in g:
            n = 1
            for j in g["len_of"]:
                n *= out[j] if isinstance(out[j], int) else 0
            out[i] = [draw(g["list"], rng) for _ in range(max(0, min(n, 4096)))]
    for i, g in enumerate(gens):
        if "len_like" in g:
            other = out[g["len_like"]]
            out[i] = [draw(g["list"], rng) for _ in range(len(other) if isinstance(other, list) else 0)]
    return tuple(out)


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
            add(_lists(tuple(e[i % len(e)] if e else draw(g, rng) for e, g in zip(edges, gens)), gens, rng))
    tries = 0
    target = len(out) + n
    while len(out) < target and tries < max_tries:
        tries += 1
        add(_lists(tuple(draw(g, rng) for g in gens), gens, rng))
    return out


def same(a, b, signed_zero: bool = False) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if type(a) is int and isinstance(b, float):
        return False   # an int result came back as a float: the target lost the type (and maybe precision)
    if isinstance(a, float) or isinstance(b, float):
        if not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
            return False
        a, b = float(a), float(b)
        if math.isnan(a) or math.isnan(b):
            return math.isnan(a) and math.isnan(b)
        if signed_zero and a == 0 and b == 0:
            return math.copysign(1.0, a) == math.copysign(1.0, b)
        return math.isclose(a, b, rel_tol=REL_TOL, abs_tol=REL_TOL)
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(same(x, y, signed_zero) for x, y in zip(a, b))
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(same(a[k], b[k], signed_zero) for k in a)
    return a == b


def finite(v) -> bool:
    if isinstance(v, complex):   # Python's float ** float leaves the reals (a negative base): no target has it
        return False
    if isinstance(v, (list, tuple)):
        return all(finite(x) for x in v)
    return not (isinstance(v, float) and (math.isnan(v) or math.isinf(v)))


def fits(v, bits: int | None) -> bool:
    if isinstance(v, (list, tuple)):
        return all(fits(x, bits) for x in v)
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
