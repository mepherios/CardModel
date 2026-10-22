"""codes — how big each code for a card's term would be (Gödel method W-3: Def-9 to Def-16, Ph-2, Ph-3, GM-2, GM-8).

  tokens     a term's prefix tokens, as the structural number reads them (Def-27): atom k -> 3k + 1, integer c ->
             3·zig(c) + 2, the j-th variable -> 3j + 3. A dict (an instruction's registers and effects) is read in
             key order; an effect's op is its ledger atom.
  positional Gödel's prime-power code of the tokens (Def-9): bits = Σ c_i·log2 p_i. It grows linearly with each
             token's code, so with the atom indices and the constants (Ph-2).
  content    the content number ∏ p_k^e (Def-10): bits = Σ e·log2 p_k, logarithmic in the atom index.
  cantor     a tree code by Cantor pairing (Def-11): node = π(head, list), list = 0 | 1 + π(item, rest). Each level
             about doubles the bits, so nesting explodes (Ph-3). Values past CAP_BITS are estimated, never built.
  szudzik    the same tree code by Szudzik pairing (Def-12).
  base_k     the term written over a 16-letter alphabet and read as a bijective base-16 numeral (Def-15): about
             n·log2 16 bits for n letters.
  hash       sha256 of the canonical serialization (Def-16): 256 bits, no arithmetic.
  model      the sizes are predicted without building any integer: the positional and content codes by their exact
             logarithmic formulas (Def-9, Def-10), checked against the built integer wherever it has at most
             BUILD_BITS bits; the pairing codes by a per-node recurrence (each pairing about doubles the larger
             argument), checked against the built code below CAP_BITS; base-k at 4 bits a letter. ``predict`` also
             gives a rougher estimate from a term's statistics alone (token count, mean token code, depth).

Honest limits (L1): only terms are measured (definitions' expression terms, instruction terms, theorem statements,
rewrite-rule sides); a multi-statement function body is read as the expressions in it, in order, which is not a
term code anyone would store. Sizes are bit lengths; the positional and content sizes past CAP_BITS come from the
exact logarithmic formula without building the integer.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections import Counter

from . import godel as G

CAP_BITS = 1 << 20
BUILD_BITS = 1 << 16
ALPHABET = "0123456789 ()vc-"


def _zig(v: int) -> int:
    return 2 * v if v >= 0 else -2 * v - 1


class Reader:
    """Tokens and a tree of one term, over the ledger's index."""

    def __init__(self, ops, index: dict[str, dict]):
        self.ops, self.index = ops, index

    def tree(self, x):
        """(token code, children) nodes; None for what carries no token."""
        if isinstance(x, list) and x:
            head = x[0]
            if head == "var":
                return ("var", x[1]), []
            if head == "int":
                return ("int", int(x[1])), []
            if head == "bool":
                return self.tree(x[1]) if len(x) == 2 else (("tuple",), [self.tree(a) for a in x[1:]])
            if isinstance(head, str) and head in self.ops:
                return ("atom", f"op/{head}"), [t for t in (self.tree(a) for a in x[1:]) if t is not None]
            kids = [t for t in (self.tree(a) for a in x) if t is not None]
            return (("tuple",), kids) if kids else None
        if isinstance(x, dict):
            if "op" in x and isinstance(x["op"], str) and f"effect/{x['op']}" in self.index:
                kids = [t for t in (self.tree(x.get(k)) for k in ("guard", "args")) if t is not None]
                return ("atom", f"effect/{x['op']}"), kids
            kids = [t for t in (self.tree(x[k]) for k in sorted(x)) if t is not None]
            return (("tuple",), kids) if kids else None
        if isinstance(x, (int, float)) and not isinstance(x, bool):
            return ("int", int(x)), []
        return None

    def codes(self, node, varnames: list) -> list[int]:
        """Prefix token codes (Def-27); a tuple node contributes its children only."""
        out = []

        def walk(n):
            (kind, *val), kids = n
            if kind == "atom":
                out.append(3 * self.index[val[0]]["index"] + 1)
            elif kind == "int":
                out.append(3 * _zig(val[0]) + 2)
            elif kind == "var":
                if val[0] not in varnames:
                    varnames.append(val[0])
                out.append(3 * varnames.index(val[0]) + 3)
            for k in kids:
                walk(k)
        walk(node)
        return out


def depth(node) -> int:
    return 1 + max((depth(k) for k in node[1]), default=0)


def positional_bits(codes: list[int]) -> float:
    return sum(c * math.log2(G.nth_prime(i)) for i, c in enumerate(codes, start=1))


def content_bits(vec: dict[str, int], entries: list[dict]) -> float:
    by = {e["index"]: e["prime"] for e in entries}
    return sum(e * math.log2(by[int(i)]) for i, e in vec.items())


def _pair_cantor(x: int, y: int) -> int:
    s = x + y
    return s * (s + 1) // 2 + y


def _pair_szudzik(x: int, y: int) -> int:
    return y * y + x if x < y else x * x + x + y


def built_positional_bits(codes: list[int]) -> int:
    """The structural number's bit length, by building it (only for small codes)."""
    n = 1
    for i, c in enumerate(codes, start=1):
        n *= G.nth_prime(i) ** c
    return n.bit_length()


def built_content_bits(vec: dict[str, int], entries: list[dict]) -> int:
    by = {e["index"]: e["prime"] for e in entries}
    n = 1
    for i, e in vec.items():
        n *= by[int(i)] ** e
    return n.bit_length()


def from_base_k(n: int) -> str:
    """The inverse of the bijective base-k numeral."""
    k, out = len(ALPHABET), []
    while n > 0:
        n, r = divmod(n - 1, k)
        out.append(ALPHABET[r])
    return "".join(reversed(out))


def to_base_k(text: str) -> int:
    k, n = len(ALPHABET), 0
    for ch in text:
        n = n * k + ALPHABET.index(ch) + 1
    return n


def _prefix_vars(node, out: list) -> list:
    (kind, *val), kids = node
    if kind == "var" and val[0] not in out:
        out.append(val[0])
    for k in kids:
        _prefix_vars(k, out)
    return out


def _head_code(n, reader: Reader, varnames: list) -> int:
    (kind, *val), _ = n
    if kind == "tuple":
        return 0
    if kind == "atom":
        return 3 * reader.index[val[0]]["index"] + 1
    if kind == "int":
        return 3 * _zig(val[0]) + 2
    return 3 * varnames.index(val[0]) + 3


def tree_code_bits(node, reader: Reader, pair, varnames: list | None = None) -> tuple[float, bool]:
    """(bits, exact) of the pairing tree code (variables numbered in prefix order); past CAP_BITS the size comes
    from tree_code_estimate and nothing that large is built."""
    vs = _prefix_vars(node, [])
    e = tree_code_estimate(node, reader)
    if e > CAP_BITS:
        return e, False

    def code(n) -> int:
        lst = 0
        for k in reversed(n[1]):
            lst = 1 + pair(code(k), lst)
        return pair(_head_code(n, reader, vs), lst)
    return float(code(node).bit_length()), True


def serialize(node, reader: Reader, varnames: list) -> str:
    """The term over ALPHABET: atoms by ledger index, v<j> for variables, c<int> for constants."""
    (kind, *val), kids = node
    if kind == "atom":
        head = str(reader.index[val[0]]["index"])
    elif kind == "int":
        head = f"c{val[0]}"
    elif kind == "var":
        if val[0] not in varnames:
            varnames.append(val[0])
        head = f"v{varnames.index(val[0])}"
    else:
        head = ""
    if not kids:
        return head
    return "(" + " ".join([head] * bool(head) + [serialize(k, reader, varnames) for k in kids]) + ")"


def base_k_bits(text: str) -> float:
    """Bit length of the bijective base-k numeral of text over ALPHABET (k = 16)."""
    return float(to_base_k(text).bit_length())


def sizes(term, reader: Reader, entries: list[dict]) -> dict | None:
    node = reader.tree(term)
    if node is None:
        return None
    codes = reader.codes(node, [])
    vec, missing = G.to_vector(Counter(_atoms(node)), reader.index)
    text = serialize(node, reader, [])
    cantor, exact_c = tree_code_bits(node, reader, _pair_cantor)
    szudzik, exact_s = tree_code_bits(node, reader, _pair_szudzik)
    cantor_est = tree_code_estimate(node, reader)
    atoms = [reader.index[a]["index"] for a in _atoms(node)]
    consts = [abs(v[0]) for v in _ints(node)]
    return {"tokens": len(codes), "depth": depth(node), "max_atom": max(atoms, default=0),
            "max_const": max(consts, default=0), "mean_code": sum(codes) / len(codes) if codes else 0.0,
            "positional": positional_bits(codes), "content": content_bits(vec, entries), "cantor": cantor,
            "cantor_exact": exact_c, "szudzik": szudzik if exact_s else None, "szudzik_exact": exact_s,
            "base_k": base_k_bits(text), "hash": 256.0, "missing_atoms": missing,
            "sha256": hashlib.sha256(text.encode()).hexdigest()[:16], "cantor_estimate": cantor_est,
            "positional_built": built_positional_bits(codes) if positional_bits(codes) <= BUILD_BITS else None,
            "content_built": built_content_bits(vec, entries) if content_bits(vec, entries) <= BUILD_BITS else None}


def _lg_add(a: float, b: float) -> float:
    """log2(2^a + 2^b), with -inf for zero."""
    if a == -math.inf:
        return b
    if b == -math.inf:
        return a
    m = max(a, b)
    return m + math.log2(1 + 2 ** (min(a, b) - m))


def _lg_cantor(lx: float, ly: float) -> float:
    """log2 of π(x, y) = s(s+1)/2 + y, s = x + y, from log2 x and log2 y."""
    ls = _lg_add(lx, ly)
    if ls == -math.inf:
        return -math.inf
    tri = 2 * ls - 1 + math.log2(1 + 2 ** -ls)          # log2(s(s+1)/2)
    return _lg_add(tri, ly)


def tree_code_estimate(node, reader: Reader) -> float:
    """The Cantor tree code's bit length from the tree alone, carrying log2 of each value up the tree (no integer
    is built): exact up to rounding, so it sizes codes far past CAP_BITS."""
    vs = _prefix_vars(node, [])

    def head(n) -> int:
        return _head_code(n, reader, vs)

    def lg(v: int) -> float:
        return math.log2(v) if v > 0 else -math.inf

    def est(n) -> float:
        h = head(n)
        kids = [est(k) for k in n[1]]
        lst = -math.inf                                    # the empty list codes as 0
        for k in reversed(kids):
            lst = _lg_add(0.0, _lg_cantor(k, lst))          # 1 + π(item, rest)
        return _lg_cantor(lg(h), lst)
    v = est(node)
    return math.floor(v) + 1 if v != -math.inf else 0.0


def _atoms(node) -> list[str]:
    (kind, *val), kids = node
    return ([val[0]] if kind == "atom" else []) + [a for k in kids for a in _atoms(k)]


def _ints(node) -> list:
    (kind, *val), kids = node
    return ([val] if kind == "int" else []) + [v for k in kids for v in _ints(k)]


# -- the size model ------------------------------------------------------------------------------------------------
def theta2(n: int) -> float:
    """Σ log2 p_i for the first n primes (Chebyshev's θ in base 2)."""
    return sum(math.log2(G.nth_prime(i)) for i in range(1, n + 1))


def predict(stats: dict) -> dict:
    """Each code's size from a term's statistics alone: the positional code as its mean token code times θ2(n); the
    content code as its atom count times log2 of the prime at its mean atom index; the pairing codes by doubling
    per level; base-k at about 4 bits a letter."""
    n = stats["tokens"]
    pos = stats["mean_code"] * theta2(n)
    atoms = stats.get("atom_count", n)
    content = atoms * log2_prime(max(1, round(stats.get("mean_atom", 1))))
    pairing = 2.0 ** (stats["depth"] + 1) * math.log2(stats["mean_code"] + 2)
    return {"positional": pos, "content": content, "cantor": pairing, "base_k": 4.0 * stats.get("letters", 2 * n)}


def log2_prime(k: int) -> float:
    """log2 of the k-th prime: exact up to the 10,000th, past it from the prime number theorem's
    p_k ≈ k (ln k + ln ln k - 1 + (ln ln k - 2) / ln k), within 0.1 % of the prime from k = 10^4 on."""
    if k <= 10000:
        return math.log2(G.nth_prime(k))
    ln, lnln = math.log(k), math.log(math.log(k))
    return math.log2(k * (ln + lnln - 1 + (lnln - 2) / ln))


def worst_case(n: int, index: int) -> dict:
    """The handover's example: n tokens over atoms near ``index`` (Ph-2)."""
    code = 3 * index + 1
    return {"positional": code * theta2(n), "content": n * log2_prime(index)}


def measure(ctx) -> dict:
    """Every card with a term: its exact sizes, the model's prediction, and their agreement."""
    from .exprs import parse
    entries = G.ledger(ctx.store)
    reader = Reader(ctx.ops, {e["atom"]: e for e in entries})
    rows = []

    def add(card, kind, term):
        try:
            s = sizes(term, reader, entries)
        except (KeyError, ValueError, OverflowError):     # OverflowError: a constant such as DBL_MAX as a code
            return
        if not s or not s["tokens"]:
            return
        node = reader.tree(term)
        atoms = [reader.index[a]["index"] for a in _atoms(node)]
        stats = {"tokens": s["tokens"], "depth": s["depth"], "mean_code": s["mean_code"], "atom_count": len(atoms),
                 "mean_atom": sum(atoms) / len(atoms) if atoms else 1,
                 "letters": len(serialize(node, reader, []))}
        rows.append({"card": card, "kind": kind, **s, "predicted": predict(stats)})
    for d in ctx.store.cards("definition"):
        t = (d.get("math") or {}).get("term")
        if isinstance(t, (list, dict)) and t:
            add(d.qualified, "instruction" if d.name.startswith("isa__") else "definition",
                t if not (isinstance(t, dict) and "body" in t) else [s.get("value") for s in t.get("body") or []
                                                                     if isinstance(s, dict) and s.get("value")])
    for th in ctx.store.cards("theorem"):
        add(th.qualified, "theorem", [th.get("concl"), *(th.get("hyps") or [])])
    for r in ctx.store.cards("rewrite_rule"):
        try:
            add(r.qualified, "rule", [parse(r["lhs"]), parse(r["rhs"])])
        except Exception:  # noqa: BLE001 -- a rule in a syntax the parser lacks is not measured
            continue
    return {"rows": rows, "summary": summarize(rows)}


def _rel(a: float, b: float) -> float:
    return abs(a - b) / max(1.0, abs(b))


def summarize(rows: list[dict]) -> dict:
    out: dict = {"cards": len(rows), "by_kind": dict(Counter(r["kind"] for r in rows))}
    for code in ("positional", "content", "cantor", "szudzik", "base_k", "hash"):
        vals = sorted(r[code] for r in rows if r[code] is not None)
        if vals:
            out[code] = {"median": vals[len(vals) // 2], "p95": vals[int(len(vals) * 0.95)], "max": vals[-1]}
    # the formulas against the built integers: within one bit wherever the integer could be built
    pb = [abs(r["positional"] - r["positional_built"]) for r in rows if r["positional_built"] is not None]
    cb = [abs(r["content"] - r["content_built"]) for r in rows if r["content_built"] is not None]
    out["formula_vs_built"] = {"positional": {"checked": len(pb), "max_bits_off": round(max(pb, default=0), 3)},
                               "content": {"checked": len(cb), "max_bits_off": round(max(cb, default=0), 3)}}
    ce = sorted(_rel(r["cantor_estimate"], r["cantor"]) for r in rows if r["cantor_exact"])
    if ce:
        out["model_cantor"] = {"checked": len(ce), "median_rel_error": round(ce[len(ce) // 2], 4),
                               "p95_rel_error": round(ce[int(len(ce) * 0.95)], 4)}
    for code in ("positional", "content", "base_k"):
        errs = sorted(_rel(r["predicted"][code], r[code]) for r in rows)
        if errs:
            out[f"statistics_model_{code}"] = {"median_rel_error": round(errs[len(errs) // 2], 4),
                                               "p95_rel_error": round(errs[int(len(errs) * 0.95)], 4)}
    for bound in (256, 664, 1024, 4096, 65536):
        out.setdefault("positional_under", {})[str(bound)] = round(
            sum(1 for r in rows if r["positional"] <= bound) / len(rows), 4) if rows else None
    out["positional_over_content"] = round(sum(1 for r in rows if r["positional"] > r["content"]) / len(rows), 4) \
        if rows else None
    out["cantor_estimated"] = sum(1 for r in rows if not r["cantor_exact"])
    return out


__all__ = ["ALPHABET", "BUILD_BITS", "CAP_BITS", "Reader", "base_k_bits", "built_content_bits",
           "built_positional_bits", "content_bits", "from_base_k", "log2_prime", "measure", "positional_bits",
           "predict", "to_base_k", "tree_code_estimate",
           "serialize", "sizes", "summarize", "theta2", "tree_code_bits", "worst_case"]
