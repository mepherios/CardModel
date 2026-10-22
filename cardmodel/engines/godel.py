"""godel — the expanding Gödel model's foundation (docs/MATH_CORE.md phase 0, law CM43).

  ledger     the atoms, each with the prime of its index (2, 3, 5, 7, ...) and the Gödel set it entered with, in
             cards/godel/_pack_ledger.jsonl. The basis set B0 holds the core types, the logic primitives and the IR
             ops; other sets extend it (``godel_set`` cards). A new atom takes the next unused prime. The ledger is
             append-only: ``sync`` only appends lines, and the CM43 test compares it with its git history.
  content    a concept's factorization: the atoms of its terms, with multiplicity (an exponent vector). gcd and
             lcm are the minimum and maximum per atom, divides is <= per atom, ``number`` is the product of p^e.
  structure  Gödel's positional numbering of a term's prefix token sequence, prod p_i^code_i, decoded exactly
             given the atoms' arities. Content forgets arrangement; structure keeps it and is the identity.
  carry      a map between sets sends each atom to a content vector. It preserves products; it preserves every
             gcd exactly when distinct atoms go to vectors with disjoint support; what it cannot send is the gap.

Honest limits (L1): content is only as canonical as the terms it is read from. Two equal behaviours written with
different atoms (SQUARE(x), MUL(x, x)) share factors only after a definition or a rewrite reduces them to the same
atoms. Constants and variables are not atoms: content counts operations, not values. A constant's token is an
exponent, so a term with a large constant (an LCG's 1103515245) has no structural number (STRUCTURAL_MAX_BITS).
"""
from __future__ import annotations

import json
from collections import Counter
from datetime import date

REGISTRY = "godel"
PACK = "_pack_ledger.jsonl"
LOGIC = ("logic/true", "logic/false", "logic/not", "logic/and", "logic/or", "logic/implies", "logic/iff",
         "logic/eq", "logic/forall", "logic/exists")
_PRIMES: list[int] = []


def nth_prime(n: int) -> int:
    """The n-th prime, 1-based: nth_prime(1) == 2."""
    if n < 1:
        raise ValueError("primes are numbered from 1")
    cand = _PRIMES[-1] + 1 if _PRIMES else 2
    while len(_PRIMES) < n:
        if all(cand % p for p in _PRIMES if p * p <= cand):
            _PRIMES.append(cand)
        cand += 1
    return _PRIMES[n - 1]


# -- the ledger -----------------------------------------------------------------------------------------------------
def ledger(store) -> list[dict]:
    return sorted((dict(c) for c in store.cards(REGISTRY)), key=lambda c: c["index"])


def index_of(store) -> dict[str, dict]:
    return {e["atom"]: e for e in ledger(store)}


def basis_atoms(store, ops) -> list[str]:
    """B0, in a fixed order: the core types, the logic primitives, then the IR ops by name."""
    types = sorted(f"core_type/{c.name}" for c in store.cards("core_type"))
    return types + list(LOGIC) + [f"op/{k}" for k in sorted(ops)]


def _slug(atom: str) -> str:
    return atom.replace("/", "__").replace(":", "_")


def sync(store, atoms: list[str], set_name: str, layer: str = "model", since: str | None = None) -> list[dict]:
    """Append every atom the ledger lacks, in the order given, each with the next index and its prime. Existing
    lines are never rewritten: the file is opened for appending."""
    have = index_of(store)
    nxt = max((e["index"] for e in have.values()), default=0) + 1
    new = []
    for a in atoms:
        if a in have:
            continue
        e = {"name": f"p{nxt}__{_slug(a)}", "category": REGISTRY, "index": nxt, "prime": nth_prime(nxt), "atom": a,
             "set": set_name, "since": since or date.today().isoformat()}
        new.append(e)
        have[a] = e
        nxt += 1
    if new:
        reg = store.ensure_registry(REGISTRY, layer, description="The prime ledger of the expanding Gödel model "
                                    "(engines/godel.py): append-only, one atom per prime.", tier=0)
        with open(reg / PACK, "a", encoding="utf-8") as f:
            for e in new:
                f.write(json.dumps(e, sort_keys=True, ensure_ascii=False) + "\n")
        store.invalidate()
    return new


def problems(entries: list[dict]) -> list[str]:
    """The ledger's own shape: indices 1..n with no gap, each prime the index's prime, every atom once."""
    out, seen = [], set()
    for i, e in enumerate(entries, start=1):
        if e.get("index") != i:
            out.append(f"index {e.get('index')} where {i} was due ({e.get('atom')})")
        elif e.get("prime") != nth_prime(i):
            out.append(f"{e.get('atom')}: prime {e.get('prime')} is not the {i}th prime ({nth_prime(i)})")
        if e.get("atom") in seen:
            out.append(f"{e.get('atom')} appears twice")
        seen.add(e.get("atom"))
    return out


# -- content ----------------------------------------------------------------------------------------------------------
def term_content(t, ops) -> Counter:
    """Atoms of one IR expression (or statement list), with multiplicity."""
    out: Counter = Counter()

    def walk(x):
        if isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, list) and x:
            head = x[0]
            if isinstance(head, str) and head in ops:
                out[f"op/{head}"] += 1
                for a in x[1:]:
                    walk(a)
            elif head in ("var", "int", "float", "str"):
                return
            elif head == "bool":
                for a in x[1:]:
                    walk(a)
            else:
                for a in x:
                    walk(a)
    walk(t)
    return +out


def module_content(module: dict, ops) -> Counter:
    total: Counter = Counter()
    for fn in module.get("functions") or [module]:
        total += term_content(fn.get("body") or [], ops)
    return total


def card_content(ctx, card) -> tuple[Counter | None, str]:
    """A card's content vector and where it was read from; None with the reason when it cannot be read."""
    ops = ctx.ops
    reg = card.registry
    if reg == "op":
        return Counter({f"op/{card.name}": 1}), "the op itself"
    if reg == "function" and isinstance(card.get("ir"), dict):
        return module_content(card["ir"], ops), "its IR"
    if reg == "theorem":
        c = term_content(card.get("concl"), ops) + term_content(card.get("hyps") or [], ops)
        c["logic/forall"] += len(card.get("vars") or [])
        if card.get("hyps"):
            c["logic/implies"] += 1
        return +c, "its statement"
    if reg == "algorithm":
        from .frontend_python import lift_source
        forms = {f["name"]: f for f in card.get("forms") or [] if f.get("lang") == "python" and f.get("code")}
        ref = forms.get(card.get("reference_form")) or next(iter(forms.values()), None)
        if ref is None:
            return None, "no Python form to read"
        lifted = [lf for lf in lift_source(ref["code"], ops) if lf.ok]
        if not lifted:
            return None, f"its {ref['name']} form does not lift to the IR"
        return module_content({"functions": [lf.ir for lf in lifted]}, ops), f"its {ref['name']} form"
    return None, f"no content rule for registry {reg}"


def number(content: Counter, index: dict[str, dict]) -> tuple[int | None, list[str]]:
    """prod p^e over the ledger; None and the atoms the ledger lacks, if any."""
    missing = sorted(a for a in content if a not in index)
    if missing:
        return None, missing
    n = 1
    for a, e in content.items():
        n *= index[a]["prime"] ** e
    return n, []


def gcd(a: Counter, b: Counter) -> Counter:
    return Counter({k: min(a[k], b[k]) for k in a if k in b and min(a[k], b[k]) > 0})


def lcm(a: Counter, b: Counter) -> Counter:
    return Counter({k: max(a[k], b[k]) for k in set(a) | set(b)})


def divides(a: Counter, b: Counter) -> bool:
    return all(b[k] >= e for k, e in a.items())


# -- structure ------------------------------------------------------------------------------------------------------
def _tokens(t, ops, index, varnames: list[str]) -> list[int]:
    """Prefix tokens: atom k -> 3k+1, integer constant c -> 3*zig(c)+2, variable j -> 3j+3."""
    if isinstance(t, list) and t and t[0] == "var":
        if t[1] not in varnames:
            varnames.append(t[1])
        return [3 * varnames.index(t[1]) + 3]
    if isinstance(t, list) and t and t[0] == "int":
        v = int(t[1])
        return [3 * (2 * v if v >= 0 else -2 * v - 1) + 2]
    if isinstance(t, list) and t and isinstance(t[0], str) and t[0] in ops:
        k = index.get(f"op/{t[0]}")
        if k is None:
            raise KeyError(f"op/{t[0]} is not in the ledger")
        out = [3 * k["index"] + 1]
        for a in t[1:]:
            out += _tokens(a, ops, index, varnames)
        return out
    raise ValueError(f"not a core term: {t!r}")


STRUCTURAL_MAX_BITS = 1 << 20      # a constant's token is an exponent: 1103515245 alone would need ~10^11 bits


def structural(t, ops, index) -> tuple[int, list[str]]:
    """Gödel's positional number of a term, and the variable order it used. A term whose number would pass
    STRUCTURAL_MAX_BITS (an integer constant in the millions makes an exponent in the millions) has none: ValueError,
    raised before any of it is computed."""
    varnames: list[str] = []
    toks = _tokens(t, ops, index, varnames)
    bits = sum(code * nth_prime(i).bit_length() for i, code in enumerate(toks, start=1))
    if bits > STRUCTURAL_MAX_BITS:
        raise ValueError(f"the term's positional number would have about {bits:,} bits (over {STRUCTURAL_MAX_BITS:,}):"
                         f" a constant too large to be an exponent")
    n = 1
    for i, code in enumerate(toks, start=1):
        n *= nth_prime(i) ** code
    return n, varnames


def decode(n: int, ops, entries: list[dict], varnames: list[str]):
    """The term back from its structural number."""
    by_index = {e["index"]: e["atom"] for e in entries}
    toks, i = [], 1
    while n > 1:
        p, e = nth_prime(i), 0
        while n % p == 0:
            n //= p
            e += 1
        toks.append(e)
        i += 1
    pos = 0

    def build():
        nonlocal pos
        code = toks[pos]
        pos += 1
        kind, k = code % 3, code // 3
        if kind == 2:
            return ["int", k // 2 if k % 2 == 0 else -(k + 1) // 2]
        if kind == 0:
            return ["var", varnames[k - 1]]
        op = by_index[k].split("/", 1)[1]
        return [op, *[build() for _ in range(ops[op].card["ir"]["arity"])]]
    return build()


# -- carrying between sets ------------------------------------------------------------------------------------------
def carry(content: Counter, mapping: dict[str, Counter]) -> tuple[Counter, Counter]:
    """(image, gap): the image of the mapped atoms, and the residual factor of atoms the map cannot send."""
    image, gap = Counter(), Counter()
    for a, e in content.items():
        if a in mapping:
            for b, f in mapping[a].items():
                image[b] += e * f
        else:
            gap[a] += e
    return +image, +gap


def preserves_gcd(mapping: dict[str, Counter]) -> bool:
    """True exactly when distinct atoms go to vectors with disjoint support."""
    seen: set[str] = set()
    for v in mapping.values():
        sup = {k for k, e in v.items() if e}
        if sup & seen:
            return False
        seen |= sup
    return True


# -- the check verify runs -------------------------------------------------------------------------------------------
def check(ctx) -> dict:
    """The ledger's shape, that it only grew since the last commit, and how many cards' content is read."""
    from ..arcade.hub import git
    from ..kernel import paths
    st = ctx.store
    entries = ledger(st)
    probs = problems(entries)
    rel = f"cards/{REGISTRY}/{PACK}"
    head = git(paths.home(), "show", f"HEAD:{rel}")
    current = (paths.home() / rel).read_text(encoding="utf-8") if (paths.home() / rel).is_file() else ""
    if head and not current.startswith(head):
        probs.append(f"{rel} changed lines the last commit had: the ledger only appends (CM43)")
    done, missing = 0, []
    for reg in ("op", "function", "algorithm"):
        for c in st.cards(reg):
            v, why = card_content(ctx, c)
            if v is None:
                missing.append(f"{c.qualified}: {why}")
                continue
            done += 1
            absent = sorted(a for a in v if a not in {e["atom"] for e in entries})
            if absent:
                probs.append(f"{c.qualified}: atoms not in the ledger: {absent[:4]}")
    total = done + len(missing)
    sets = Counter(e["set"] for e in entries)
    return {"status": "fail" if probs else ("pass" if entries else "vacuous"), "problems": probs,
            "atoms": len(entries), "sets": dict(sets), "coverage": round(done / total, 4) if total else None,
            "missing": missing[:20]}


__all__ = ["LOGIC", "basis_atoms", "check", "card_content", "carry", "decode", "divides", "gcd", "index_of", "lcm", "ledger",
           "module_content", "nth_prime", "number", "preserves_gcd", "problems", "structural", "sync", "term_content"]
