"""godel — the Gödel model: the structure every subsystem reads its terms through (docs/GODEL_TARGET.md,
docs/FOUNDATIONS.md D11–D13, laws CM43 and CM45).

  ledger     the atoms, each with the prime of its index (2, 3, 5, 7, ...) and the Gödel set it entered with, in
             cards/godel/_pack_ledger.jsonl. The basis set B0 holds the core types, the logic primitives and the IR
             ops; other sets extend it (``godel_set`` cards). A new atom takes the next unused prime. The ledger is
             append-only: ``sync`` only appends lines, and the CM43 test compares it with its git history.
  content    γ(t): a term's atoms with multiplicity, a vector in ℤ^(ℕ), the free abelian group on the primes. γ is a
             homomorphism: the content of a whole is the sum of its parts' (``add``), so a module's content is the
             sum of its functions', a change is a difference (``sub``), and summaries merge in any order. Under
             divisibility it is a lattice: gcd is the meet, lcm the join (formal/GodelCore T1), ``divides`` the
             order, ``cofactor`` the unique quotient. Substitution only adds content, so an instance of a pattern
             is divisible by the pattern: a failed divisibility test refutes a match before it is tried
             (``ContentIndex``, ``factor``). An additive cost is linear in content (``cost``).
  storage    (law CM45, the research handover's storage rules) a card stores its content as the sparse map
             ledger index -> exponent with the basis version it was read against (``stored``), never the
             content integer prod p^e, which grows with every factor. Its identity is the hash of its structure.
             Gödel's positional number is kept only for small terms (STRUCTURAL_MAX_DIGITS).
  events     the ledger never deletes, reuses or renumbers an index. Two indices found to name one concept are
             merged (``merge``: one moves onto the other); a concept found to be a product of others is
             deprecated with that product (``deprecate``). Both are appended lines; ``resolve`` reads a vector
             through them. An equation between products (a·b = c·d) is not an event: it would end unique
             factorization (formal/GodelCore/T4Free.lean), so it belongs in the transformation layer.
  structure  Gödel's positional numbering of a term's prefix token sequence, prod p_i^code_i, decoded exactly
             given the atoms' arities (``tokens``, ``structural``, ``decode``). Content forgets arrangement;
             structure keeps it.
  carry      a map between sets sends each atom to a content vector. It preserves products; it preserves every
             gcd exactly when distinct atoms go to vectors with disjoint support; what it cannot send is the gap.
  reading    content is read from the canonical term (FOUNDATIONS A4). γ is not invariant under the laws
             (γ(a·(b+c)) ≠ γ(a·b + a·c)), so one function spelled two ways has two contents until distillation
             reaches one term; a card records which term its content was read from (``read_from``).

This module is the only place that computes primes, content and positional tokens (GODEL_TARGET §7); the other
engines call it. Every walk over a term here is iterative, so the depth of a term costs nothing.

Honest limits (L1): content is only as canonical as the terms it is read from. Two equal behaviours written with
different atoms (SQUARE(x), MUL(x, x)) share factors only after a definition or a rewrite reduces them to the same
atoms. Constants and variables are not atoms: content counts operations, not values. Equal content never proves
equal behaviour; it is necessary for equal canonical terms, nothing more.
"""
from __future__ import annotations

import json
import math
from collections import Counter
from fractions import Fraction
from datetime import date

REGISTRY = "godel"
PACK = "_pack_ledger.jsonl"
LOGIC = ("logic/true", "logic/false", "logic/not", "logic/and", "logic/or", "logic/implies", "logic/iff",
         "logic/eq", "logic/forall", "logic/exists")
EVENT_KINDS = ("merge", "deprecate")
STRUCTURAL_MAX_DIGITS = 200          # Gödel's positional number is stored for terms up to this many decimal digits
LEAVES = ("var", "int", "float", "bool", "str")   # not atoms: a constant or a variable carries no content (Rule-23)
SPECIAL = ("CALL", "LOAD")                        # the IR's forms that name a function or a cell: walked, not counted
_PRIMES: list[int] = []


# -- primes and the zigzag ------------------------------------------------------------------------------------------
def primes(n: int) -> list[int]:
    """The first n primes, from one sieve for the whole model (Rosser's bound p_n < n(ln n + ln ln n), n >= 6)."""
    if n > len(_PRIMES):
        m = max(n, 2 * len(_PRIMES), 64)
        bound = int(m * (math.log(m) + math.log(math.log(m)))) + 10
        sieve = bytearray([1]) * (bound + 1)
        sieve[0] = sieve[1] = 0
        for i in range(2, int(bound ** 0.5) + 1):
            if sieve[i]:
                sieve[i * i::i] = bytearray(len(range(i * i, bound + 1, i)))
        _PRIMES[:] = [i for i, is_p in enumerate(sieve) if is_p]
    return _PRIMES[:n]


def nth_prime(n: int) -> int:
    """The n-th prime, 1-based: nth_prime(1) == 2."""
    if n < 1:
        raise ValueError("primes are numbered from 1")
    if n > len(_PRIMES):
        primes(n)
    return _PRIMES[n - 1]


def zig(v: int) -> int:
    """ℤ -> ℕ, one to one: 0, -1, 1, -2, 2, ... -> 0, 1, 2, 3, 4, ... (the integer constants' token code)."""
    return 2 * v if v >= 0 else -2 * v - 1


def unzig(z: int) -> int:
    return z // 2 if z % 2 == 0 else -(z + 1) // 2


# -- the ledger -----------------------------------------------------------------------------------------------------
def ledger(store) -> list[dict]:
    """The atoms, by index (the ledger's events are apart: ``events``)."""
    return sorted((dict(c) for c in store.cards(REGISTRY) if "index" in c), key=lambda c: c["index"])


def events(store) -> list[dict]:
    """The ledger's merges and deprecations, in the order they were appended."""
    return sorted((dict(c) for c in store.cards(REGISTRY) if "event" in c), key=lambda c: c.get("seq", 0))


def basis_version(entries: list[dict]) -> int:
    """The ledger's version: how many atoms it holds. The ledger only appends, so version n is exactly its first n
    atoms, and a vector read against version n reads the same in every later version
    (formal/GodelCore/T3Ledger.lean: enc_append)."""
    return len(entries)


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


def problems(entries: list[dict], evs: list[dict] | None = None) -> list[str]:
    """The ledger's own shape: indices 1..n with no gap, each prime the index's prime, every atom once; every event
    a merge or a deprecation of a known index into known, live indices, with no cycle."""
    out, seen = [], set()
    for i, e in enumerate(entries, start=1):
        if e.get("index") != i:
            out.append(f"index {e.get('index')} where {i} was due ({e.get('atom')})")
        elif e.get("prime") != nth_prime(i):
            out.append(f"{e.get('atom')}: prime {e.get('prime')} is not the {i}th prime ({nth_prime(i)})")
        if e.get("atom") in seen:
            out.append(f"{e.get('atom')} appears twice")
        seen.add(e.get("atom"))
    n, gone = len(entries), {}
    for ev in evs or []:
        kind, of = ev.get("event"), ev.get("of")
        if kind not in EVENT_KINDS:
            out.append(f"ledger event {ev.get('name')}: {kind!r} is not a merge or a deprecation (an equation between "
                       f"products belongs in the transformation layer, CM45)")
            continue
        if not isinstance(of, int) or not 1 <= of <= n:
            out.append(f"ledger event {ev.get('name')}: index {of!r} is not in the ledger")
            continue
        if of in gone:
            out.append(f"ledger event {ev.get('name')}: index {of} was already {gone[of]}")
        to = {int(k): v for k, v in (ev.get("to") or {}).items()} if kind == "deprecate" else {ev.get("into"): 1}
        bad = [k for k in to if not isinstance(k, int) or not 1 <= k <= n or k == of]
        if bad or not to or any(not isinstance(v, int) or v < 1 for v in to.values()):
            out.append(f"ledger event {ev.get('name')}: its target {to} is not a product of other ledger indices")
        gone[of] = "merged" if kind == "merge" else "deprecated"
    try:
        for i in gone:
            resolve({str(i): 1}, evs or [])
    except ValueError as exc:
        out.append(str(exc))
    return out


def merge(store, atom: str, into: str, reason: str, layer: str = "model") -> dict:
    """Record that ``atom`` names the same concept as ``into``: its index moves onto ``into``'s from now on. Merging
    generators keeps the monoid free (formal/GodelCore/T4Free.lean: gen_basis_iff)."""
    idx = index_of(store)
    return _append_event(store, {"event": "merge", "of": idx[atom]["index"], "into": idx[into]["index"],
                                 "reason": reason}, layer)


def deprecate(store, atom: str, product: dict[str, int], reason: str, layer: str = "model") -> dict:
    """Record that ``atom`` is the product of other atoms (atom -> exponent): its index is read as that product."""
    idx = index_of(store)
    return _append_event(store, {"event": "deprecate", "of": idx[atom]["index"],
                                 "to": {str(idx[a]["index"]): e for a, e in product.items()}, "reason": reason}, layer)


def _append_event(store, ev: dict, layer: str) -> dict:
    evs = events(store)
    seq = max((e.get("seq", 0) for e in evs), default=0) + 1
    ev = {"name": f"e{seq}__{ev['event']}__{ev['of']}", "category": REGISTRY, "seq": seq,
          "since": date.today().isoformat(), **ev}
    probs = problems(ledger(store), evs + [ev])
    if probs:
        raise ValueError("; ".join(probs[:3]))
    reg = store.ensure_registry(REGISTRY, layer, description="The prime ledger of the expanding Gödel model "
                                "(engines/godel.py): append-only, one atom per prime.", tier=0)
    with open(reg / PACK, "a", encoding="utf-8") as f:
        f.write(json.dumps(ev, sort_keys=True, ensure_ascii=False) + "\n")
    store.invalidate()
    return ev


def resolve(vec: dict[str, int], evs: list[dict], depth: int = 0) -> dict[str, int]:
    """A stored vector read through the ledger's events: a merged index counts as its target, a deprecated one as
    its product, until only live indices are left."""
    if depth > 64:
        raise ValueError("the ledger's events form a cycle")
    rule = {}
    for ev in evs:
        if ev.get("event") == "merge":
            rule[str(ev["of"])] = {str(ev["into"]): 1}
        elif ev.get("event") == "deprecate":
            rule[str(ev["of"])] = {str(k): v for k, v in ev["to"].items()}
    out: Counter = Counter()
    moved = False
    for i, e in vec.items():
        if i in rule:
            moved = True
            for j, f in rule[i].items():
                out[j] += e * f
        else:
            out[i] += e
    out = +out
    return resolve(dict(out), evs, depth + 1) if moved else dict(out)


# -- content ----------------------------------------------------------------------------------------------------------
def atom(head, ops=None) -> str | None:
    """The ledger atom a term's head names: ``op/NAME`` for an op of the signature ``ops`` (every non-leaf head when
    ops is None, as a numbering over any Gödel set reads them; a qualified name such as ``effect/WRITE`` is its own
    atom); None for a leaf, a CALL or a LOAD, or a head outside the signature."""
    if not isinstance(head, str) or head in LEAVES:
        return None
    if ops is not None:
        return f"op/{head}" if head in ops else None
    if head in SPECIAL:
        return None
    return head if "/" in head else f"op/{head}"


def _parts(x, ops, holes):
    """(atom, parts to walk) of one node; parts None for a leaf. A statement list or an unknown head is walked
    whole; a CALL or LOAD walks its arguments; a CALL to a name in ``holes`` is a leaf."""
    if isinstance(x, dict):
        return None, [v for v in x.values() if isinstance(v, (list, dict))]
    if not (isinstance(x, list) and x):
        return None, None
    head = x[0]
    a = atom(head, ops)
    if a is not None:
        return a, [v for v in x[1:] if isinstance(v, (list, dict))]
    if isinstance(head, str):
        if head in LEAVES:
            return None, None
        if head in SPECIAL:
            if head == "CALL" and len(x) > 1 and isinstance(x[1], str) and x[1] in holes:
                return None, None
            return None, [v for v in x[2:] if isinstance(v, (list, dict))]
    return None, [v for v in x if isinstance(v, (list, dict))]


def term_content(t, ops=None, holes=()) -> Counter:
    """γ(t): the atoms of a term (or a statement list, or a dict of terms) with multiplicity, as the tree has it: a
    subterm shared by reference counts once per reference, computed once. Iterative, so depth costs nothing.
    ``ops`` is the signature (ctx.ops); None reads every non-leaf head as an atom. A CALL to a name in ``holes`` is
    a leaf, which is how ``factor`` reads the content of a context."""
    memo: dict[int, Counter] = {}
    stack: list[tuple] = [(t, None, None)]
    while stack:
        x, a, parts = stack.pop()
        if parts is not None:                                  # second visit: every part is in memo
            c = Counter() if a is None else Counter({a: 1})
            for p in parts:
                c.update(memo[id(p)])
            memo[id(x)] = c
            continue
        if id(x) in memo:
            continue
        a, parts = _parts(x, ops, holes)
        if parts is None:
            memo[id(x)] = Counter()
            continue
        stack.append((x, a, parts))
        stack.extend((p, None, None) for p in parts if id(p) not in memo)
    return +memo[id(t)]


def module_content(module: dict, ops) -> Counter:
    """A module's content is the sum of its functions' (γ is a homomorphism)."""
    return add(*(term_content(fn.get("body") or [], ops) for fn in module.get("functions") or [module]))


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


def to_vector(content: Counter, index: dict[str, dict]) -> tuple[dict[str, int], list[str]]:
    """The sparse map ledger index -> exponent (string keys, as JSON keeps them), and the atoms the ledger lacks."""
    missing = sorted(a for a in content if a not in index)
    vec = {str(index[a]["index"]): e for a, e in sorted((kv for kv in content.items() if kv[0] in index and kv[1]),
                                                         key=lambda kv: index[kv[0]]["index"])}
    return vec, missing


def from_vector(vec: dict[str, int], entries: list[dict]) -> Counter:
    """The readable view of a stored vector: atom -> exponent."""
    by = {e["index"]: e["atom"] for e in entries}
    return Counter({by[int(i)]: e for i, e in vec.items()})


def stored(content: Counter | None, read_from: str, entries: list[dict], ops=None, term=None) -> dict:
    """What a card stores of its Gödel model (CM45): the sparse vector with the basis version it was read against,
    the readable atom view beside it, and Gödel's positional number only for a small term. Never the content
    integer."""
    index = {e["atom"]: e for e in entries}
    out = {"content": dict(content) if content is not None else None, "read_from": read_from,
           "basis": basis_version(entries)}
    if content is not None:
        out["vector"], missing = to_vector(content, index)
        if missing:
            out["missing_atoms"] = missing
    if term is not None and ops is not None:
        try:
            s, varnames, digits = structural(term, ops, index)
            out["structural"], out["structural_digits"], out["variables"] = (str(s) if s is not None else None,
                                                                              digits, varnames)
        except (KeyError, ValueError):
            out["structural"] = None
    return out


def vector_problems(godel: dict, entries: list[dict]) -> list[str]:
    """A stored Gödel record against the storage rules: no content integer, a vector over indices no later than its
    basis version, a basis version the ledger has reached, and the vector agreeing with its atom view."""
    out = []
    if "number" in godel:
        out.append("stores a content integer (CM45: store the sparse vector)")
    vec, basis = godel.get("vector"), godel.get("basis")
    if godel.get("content") is not None and vec is None:
        out.append("has content but no vector")
    if not isinstance(basis, int) or not 0 < basis <= len(entries):
        out.append(f"basis version {basis!r} is not one the ledger has reached ({len(entries)})")
    elif vec:
        late = [i for i in vec if int(i) > basis]
        if late:
            out.append(f"indices {late[:3]} are later than its basis version {basis}")
        elif godel.get("content") is not None and dict(from_vector(vec, entries)) != {k: v for k, v in
                                                                                      godel["content"].items() if v}:
            out.append("its vector and its atom view disagree")
    return out


# -- the algebra of content: a lattice under divisibility, a group under addition ------------------------------------
def _strip(c: Counter) -> Counter:
    """Zero exponents dropped; negative ones kept (``+c`` would drop them, and a ratio of dimensions needs them)."""
    return Counter({k: e for k, e in c.items() if e})


def add(*vectors) -> Counter:
    """The sum in the free abelian group: the content of a whole from its parts, a summary from its units, from any
    number of workers in any order (commutative and associative)."""
    out: Counter = Counter()
    for v in vectors:
        for k, e in v.items():
            out[k] += e
    return _strip(out)


def sub(a, b) -> Counter:
    """a − b, signed: the delta of a change, or a ratio of dimensions (negative exponents are kept)."""
    out = Counter(a)
    for k, e in b.items():
        out[k] -= e
    return _strip(out)


def scale(a, k: "int | Fraction") -> Counter:
    """k copies of a content (the content of k occurrences); a rational k (fractions.Fraction) scales exactly, as a
    square root halves a dimension. A float is refused: exponents stay exact."""
    if isinstance(k, float):
        raise TypeError("scale takes an int or a Fraction, not a float")
    return _strip(Counter({x: e * k for x, e in a.items()}))


def norm(a) -> int:
    """How many atom occurrences a content counts (|e| summed over the support)."""
    return sum(abs(e) for e in a.values())


def support(a) -> set[str]:
    """The atoms a content has (the set of its prime factors)."""
    return {k for k, e in a.items() if e}


def divides(a, b) -> bool:
    """a ≤ b at every atom: the order of divisibility (for non-negative vectors, exactly ∏p^a | ∏p^b)."""
    return all(a.get(k, 0) <= b.get(k, 0) for k in set(a) | set(b))


def cofactor(whole, part) -> Counter | None:
    """whole / part when part divides whole, else None. The cofactor is unique (formal/GodelCore: dvd_iff_exists_mul
    and mul_left_cancel): what is left of a concept once a known one is factored out of it."""
    return sub(whole, part) if divides(part, whole) else None


def gcd(a, b) -> Counter:
    """The meet: the logic two concepts share, per atom the smaller exponent."""
    return _strip(Counter({k: min(a.get(k, 0), b.get(k, 0)) for k in set(a) | set(b)}))


def lcm(a, b) -> Counter:
    """The join: everything either concept needs, per atom the larger exponent."""
    return _strip(Counter({k: max(a.get(k, 0), b.get(k, 0)) for k in set(a) | set(b)}))


def cost(a, costs: dict[str, float], default: float = 1.0) -> float:
    """⟨γ, c⟩: an additive cost is linear in content, so a term's cost is known from its content alone. Costs are
    keyed by op name (search.op_costs); an atom with no cost costs ``default``, as egraph.extract and
    search.expr_cost have it."""
    return float(sum(e * costs.get(k[3:] if k.startswith("op/") else k, default) for k, e in a.items()))


def jaccard(a, b) -> float:
    """|gcd| / |lcm|: the share of logic two concepts have in common, 1 when they are one content, 0 when they share
    no atom (two empty contents count as one)."""
    denom = norm(lcm(a, b))
    return 1.0 if denom == 0 else norm(gcd(a, b)) / denom


class ContentIndex:
    """An inverted index from atoms to the concepts whose content has them. ``divisors(c)`` answers "which known
    concepts can occur in a term of content c" and ``multiples(c)`` "which concepts contain this logic" by touching
    only the postings of c's atoms, never the whole library (every card inheriting a property of a part, by
    divisibility). Contents here are non-negative."""

    def __init__(self, items=None):
        self.contents: dict[str, Counter] = {}
        self.postings: dict[str, dict[str, int]] = {}
        for key, c in (items.items() if isinstance(items, dict) else (items or [])):
            self.add(key, c)

    def __len__(self) -> int:
        return len(self.contents)

    def __contains__(self, key) -> bool:
        return key in self.contents

    def __iter__(self):
        return iter(self.contents)

    def add(self, key: str, content) -> None:
        if key in self.contents:
            self.remove(key)
        c = _strip(Counter(content))
        self.contents[key] = c
        for a, e in c.items():
            self.postings.setdefault(a, {})[key] = e

    def remove(self, key: str) -> None:
        c = self.contents.pop(key, None)
        for a in c or ():
            p = self.postings.get(a)
            if p:
                p.pop(key, None)
                if not p:
                    del self.postings[a]

    def divisors(self, c, empty: bool = False) -> list[str]:
        """Keys whose content divides c: every atom of theirs is in c at no higher exponent. A key with no content
        divides everything and is listed only when ``empty``."""
        hits: Counter = Counter()
        for a, e in c.items():
            for key, f in self.postings.get(a, {}).items():
                if f <= e:
                    hits[key] += 1
        out = [key for key, n in hits.items() if n == len(self.contents[key])]
        if empty:
            out += [key for key, v in self.contents.items() if not v]
        return sorted(out)

    def multiples(self, c) -> list[str]:
        """Keys whose content c divides: every atom of c is in theirs at no lower exponent."""
        keys = None
        for a, e in c.items():
            have = {key for key, f in self.postings.get(a, {}).items() if f >= e}
            keys = have if keys is None else keys & have
            if not keys:
                return []
        return sorted(self.contents) if keys is None else sorted(keys)

    def similar(self, c, k: int = 10) -> list[tuple[str, float]]:
        """The k concepts sharing most logic with c, by |gcd| / |lcm|, among those sharing an atom with it."""
        cands = {key for a in c for key in self.postings.get(a, {})}
        scored = sorted(((key, jaccard(c, self.contents[key])) for key in cands), key=lambda kv: (-kv[1], kv[0]))
        return scored[:k]


# -- matching and factoring: a term over the concepts it contains ---------------------------------------------------
def variables(t) -> list[str]:
    """A term's variables in order of first appearance (the order a positional code and a CALL use)."""
    out: list[str] = []
    stack = [t]
    while stack:
        x = stack.pop()
        if isinstance(x, dict):
            stack.extend(reversed(list(x.values())))
        elif isinstance(x, list) and x:
            if x[0] == "var":
                if x[1] not in out:
                    out.append(x[1])
            elif not (isinstance(x[0], str) and x[0] in LEAVES):
                start = 2 if isinstance(x[0], str) and x[0] in SPECIAL else 1
                stack.extend(reversed(x[start:]))
    return out


def match(pattern, term, binds: dict | None = None) -> dict | None:
    """First-order matching: the substitution σ with σ(pattern) == term, or None. A pattern's variables bind any
    subterm, the same subterm wherever a variable repeats; constants match only themselves. Iterative."""
    binds = {} if binds is None else dict(binds)
    stack = [(pattern, term)]
    while stack:
        p, t = stack.pop()
        if isinstance(p, list) and p and p[0] == "var":
            if p[1] in binds:
                if binds[p[1]] != t:
                    return None
            else:
                binds[p[1]] = t
            continue
        if not (isinstance(p, list) and isinstance(t, list)):
            if p != t:
                return None
            continue
        if not p or len(p) != len(t) or p[0] != t[0]:
            return None
        start = 2 if isinstance(p[0], str) and p[0] in SPECIAL else 1
        if start == 2 and p[1] != t[1]:
            return None
        stack.extend(zip(p[start:], t[start:]))
    return binds


def substitute(term, binds: dict):
    """σ(term): each variable replaced by what binds it."""
    if isinstance(term, list) and term:
        if term[0] == "var":
            return binds.get(term[1], term)
        if isinstance(term[0], str) and term[0] in LEAVES:
            return term
        start = 2 if isinstance(term[0], str) and term[0] in SPECIAL else 1
        return [*term[:start], *(substitute(a, binds) for a in term[start:])]
    return term


def factor(term, library: dict, ops=None, index: ContentIndex | None = None, exclude=()) -> dict:
    """The term over the concepts it contains. Top down: at each subterm, the library concepts whose content divides
    the subterm's (``index.divisors``; every other concept is refuted without a match, since an instance is
    divisible by its pattern) are matched largest first; a match becomes ``["CALL", key, σ(v1), ..., σ(vk)]`` over
    the pattern's variables in order, and its bindings are factored in turn. ``cofactor`` is the content no concept
    covers: that of the context with the matched instances as holes. ``check`` is the equation
    γ(t) = γ(context) + Σ γ(instance), each side read from its own term."""
    index = ContentIndex({k: term_content(p, ops) for k, p in library.items()}) if index is None else index
    excluded = set(exclude)
    contents = _content_map(term, ops)
    uses: list[dict] = []
    top: list = []

    def go(t, path, inside):
        if not (isinstance(t, list) and t) or (isinstance(t[0], str) and t[0] in LEAVES):
            return t
        c = contents.get(id(t))
        if c is None:
            c = term_content(t, ops)
        if c:
            cands = [k for k in index.divisors(c) if k not in excluded and k in library]
            cands.sort(key=lambda k: (-norm(index.contents[k]), k))
            for k in cands:
                binds = match(library[k], t)
                if binds is None:
                    continue
                vs = variables(library[k])
                uses.append({"key": k, "path": path, "bindings": {v: binds[v] for v in vs}, "nested": inside})
                if not inside:
                    top.append(t)
                return ["CALL", k, *(go(binds[v], [*path, i], True) for i, v in enumerate(vs))]
        start = 2 if isinstance(t[0], str) and t[0] in SPECIAL else 1
        return [*t[:start], *(go(a, [*path, i], inside) for i, a in enumerate(t[start:]))]

    out = go(term, [], False)
    used = {u["key"] for u in uses}
    whole = term_content(term, ops)
    context = term_content(out, ops, holes=used)
    covered = add(*(term_content(s, ops) for s in top))
    return {"term": out, "uses": uses, "content": whole, "cofactor": context, "covered": covered,
            "check": whole == add(context, covered)}


def expand(term, library: dict):
    """The inverse of ``factor``: every CALL to a library concept unfolded into the concept's term over its
    arguments."""
    if isinstance(term, list) and term:
        if term[0] == "CALL" and len(term) > 1 and isinstance(term[1], str) and term[1] in library:
            p = library[term[1]]
            args = [expand(a, library) for a in term[2:]]
            return substitute(p, dict(zip(variables(p), args)))
        if isinstance(term[0], str) and term[0] in LEAVES:
            return term
        start = 2 if isinstance(term[0], str) and term[0] in SPECIAL else 1
        return [*term[:start], *(expand(a, library) for a in term[start:])]
    return term


def _content_map(t, ops) -> dict[int, Counter]:
    """The content of every node of a term, by id, in one bottom-up pass."""
    memo: dict[int, Counter] = {}
    stack: list[tuple] = [(t, None, None)]
    while stack:
        x, a, parts = stack.pop()
        if parts is not None:
            c = Counter() if a is None else Counter({a: 1})
            for p in parts:
                c.update(memo[id(p)])
            memo[id(x)] = c
            continue
        if id(x) in memo:
            continue
        a, parts = _parts(x, ops, ())
        if parts is None:
            memo[id(x)] = Counter()
            continue
        stack.append((x, a, parts))
        stack.extend((p, None, None) for p in parts if id(p) not in memo)
    return memo


# -- structure ------------------------------------------------------------------------------------------------------
def tokens(t, index: dict, varnames: list[str], ops=None, max_tokens: int | None = None,
           bools_as_ints: bool = False) -> list[int] | None:
    """Prefix tokens of a term (Def-27): atom k -> 3k+1, integer constant c -> 3·zig(c)+2, variable j -> 3j+3 by
    first appearance (appended to ``varnames``). Iterative. None past ``max_tokens``. KeyError for an atom the
    ledger lacks; ValueError for a term outside the scheme (a float, a bool, a call). ``bools_as_ints`` reads a bool
    constant as the integer it converts to, which unreal's real view does; the core scheme refuses it."""
    out: list[int] = []
    stack = [t]
    while stack:
        x = stack.pop()
        if not (isinstance(x, list) and x):
            raise ValueError(f"not a core term: {x!r}")
        head = x[0]
        if head == "var":
            if x[1] not in varnames:
                varnames.append(x[1])
            out.append(3 * varnames.index(x[1]) + 3)
        elif head == "int" or (bools_as_ints and head == "bool"):
            out.append(3 * zig(int(x[1])) + 2)
        else:
            a = atom(head, ops)
            if a is None:
                raise ValueError(f"not a core term: {x!r}")
            e = index.get(a)
            if e is None:
                raise KeyError(f"{a} is not in the ledger")
            out.append(3 * e["index"] + 1)
            stack.extend(reversed(x[1:]))
        if max_tokens is not None and len(out) > max_tokens:
            return None
    return out


def structural(t, ops, index, max_digits: int | None = STRUCTURAL_MAX_DIGITS) -> tuple[int | None, list[str], int]:
    """Gödel's positional number of a term (None when it would pass max_digits decimal digits: it grows too fast for
    large terms, so the structure hash is the identity), the variable order it used, and its size in digits."""
    varnames: list[str] = []
    toks = tokens(t, index, varnames, ops=ops)
    digits = int(sum(code * math.log10(nth_prime(i)) for i, code in enumerate(toks, start=1))) + 1
    if max_digits is not None and digits > max_digits:
        return None, varnames, digits
    n = number(toks)
    return n, varnames, decimal_digits(n)


def number(toks: list[int]) -> int:
    """Gödel's positional number of a token list, ∏ p_i^c_i (p_1 = 2), iterative. The token list may be a forest's
    (several terms' tokens concatenated, sharing one variable order), which ``structural`` cannot take. It builds the
    integer, so callers bound its size first (``structural``'s max_digits; codes' BUILD_BITS)."""
    n = 1
    for i, code in enumerate(toks, start=1):
        n *= nth_prime(i) ** code
    return n


def decimal_digits(n: int) -> int:
    """len(str(n)) for n >= 1, without str(): CPython refuses to print integers past 4300 digits, and an atom with a
    late ledger index (3k+1 for k in the thousands) makes even a small term's number that long."""
    k = max(1, int(n.bit_length() * 0.30102999566398120))
    while 10 ** k <= n:
        k += 1
    while k > 1 and 10 ** (k - 1) > n:
        k -= 1
    return k


def valuation(n: int, p: int) -> tuple[int, int]:
    """The p-adic valuation e of n, and n / p^e, by repeated squaring: O(log e) divisions of n instead of e. A
    token code is an exponent of a prime, and a late atom's code is in the thousands (3k + 1 for ledger index k),
    so dividing e times made decoding 98 % of the godel verify section."""
    if n == 0 or p < 2:
        raise ValueError(f"valuation is defined for n != 0 and p >= 2, got n={n}, p={p}")
    if n % p:
        return 0, n
    powers = [p]                                     # p, p^2, p^4, ... while the next square still divides n
    while True:
        sq = powers[-1] * powers[-1]
        if n % sq:
            break
        powers.append(sq)
    e = 0
    for i in range(len(powers) - 1, -1, -1):
        if n % powers[i] == 0:
            n //= powers[i]
            e += 1 << i
    return e, n


def exponents(n: int, gaps: bool = True) -> list[int] | None:
    """The exponents of 2, 3, 5, ... in n, up to the last prime that divides it: the tokens of a positional code,
    each by its valuation. With ``gaps`` False, None as soon as a prime is skipped while n > 1, which no positional
    code does (every token code is at least 1, Rule-3), so a number that codes nothing is refused early."""
    toks, i = [], 1
    while n > 1:
        e, n = valuation(n, nth_prime(i))
        if e == 0 and not gaps:
            return None
        toks.append(e)
        i += 1
    return toks


def from_tokens(toks: list[int], ops, entries: list[dict], varnames: list[str]):
    """The term of a prefix token sequence, parsed by the ops' arities (iterative); tokens after the first complete
    term are ignored."""
    by_index = {e["index"]: e["atom"] for e in entries}
    frames: list[tuple[list, int]] = []                    # the open applications and their arities
    for code in toks:
        kind, k = code % 3, code // 3
        if kind == 2:
            node = ["int", unzig(k)]
        elif kind == 0:
            node = ["var", varnames[k - 1]]
        else:
            op = by_index[k].split("/", 1)[1]
            node = [op]
            arity = ops[op].card["ir"]["arity"]
            if arity:
                frames.append((node, arity))
                continue
        while True:
            if not frames:
                return node
            parent, arity = frames[-1]
            parent.append(node)
            if len(parent) - 1 < arity:
                break
            frames.pop()
            node = parent
    raise ValueError("the tokens end inside a term" if frames else "no tokens")


def decode(n: int, ops, entries: list[dict], varnames: list[str]):
    """The term back from its structural number."""
    return from_tokens(exponents(n), ops, entries, varnames)


# -- carrying between sets ------------------------------------------------------------------------------------------
def carry(content: Counter, mapping: dict[str, Counter]) -> tuple[Counter, Counter]:
    """(image, gap): the image of the mapped atoms, and the residual factor of atoms the map cannot send. A
    homomorphism: carry(a + b) is carry(a) + carry(b) in both parts."""
    image, gap = Counter(), Counter()
    for a, e in content.items():
        if a in mapping:
            for b, f in mapping[a].items():
                image[b] += e * f
        else:
            gap[a] += e
    return +image, +gap


RANK = "@"      # op/ADD@int,int->int: the atom at one rank of the signature (FOUNDATIONS D1: an op card's ranks)


def base_atom(a: str) -> str:
    """The atom without its rank: op/ADD@int,int->int is op/ADD."""
    return a.split(RANK, 1)[0]


def ranked_atom(a: str, rank: str) -> str:
    return f"{a}{RANK}{rank}"


def forget_ranks(content: Counter) -> Counter:
    """The carry map that forgets ranks, op/ADD@int,int->int -> op/ADD: a homomorphism onto the rank-blind content,
    so forgetting the ranks of a term's ranked content (codegen.ranked_content) gives term_content of it, and a gap
    at one rank refines the rank-blind gap."""
    return carry(content, {a: Counter({base_atom(a): 1}) for a in content})[0]


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
CHECK_REGISTRIES = ("godel", "godel_set", "op", "function", "algorithm", "physics_law")   # every registry ``check`` reads
CHECK_CODE = ("godel", "numbering", "dimensions", "frontend_python", "ir")               # every engine ``check`` runs


def check_key(ctx) -> str:
    """The key of exactly what ``check`` reads, so verify and the self-run skip it when nothing changed (GODEL_AUDIT
    §6 step 1): each card's content hash (``kernel.canon.card_hash``, CM02) in the registries it reads (the physics
    laws among them, whose dimension check it runs) and of the provability method its numberings name; git's id of the committed ledger and the bytes of the current one (the
    append-only check); and the source of the engines it runs, with the interpreter's version. ``check`` takes no
    seed (``numbering`` uses seed 0), so equal keys give equal results and any changed input gives a new key."""
    import hashlib
    import importlib
    import sys
    from pathlib import Path
    from ..arcade.hub import git
    from ..kernel import paths
    from ..kernel.canon import card_hash
    from . import numbering
    st = ctx.store
    h = hashlib.sha256(f"python {sys.version_info[0]}.{sys.version_info[1]}\n".encode())
    for reg in CHECK_REGISTRIES:
        for c in sorted(st.cards(reg), key=lambda c: c.qualified):
            h.update(f"{c.qualified} {card_hash(c)}\n".encode())
    m = st.get(numbering.NATURAL["relation"])
    h.update(f"{numbering.NATURAL['relation']} {card_hash(m) if m is not None else '-'}\n".encode())
    rel = f"cards/{REGISTRY}/{PACK}"
    h.update(f"HEAD:{rel} {(git(paths.home(), 'rev-parse', f'HEAD:{rel}') or '-').strip()}\n".encode())
    cur = paths.home() / rel
    h.update(f"{rel} {hashlib.sha256(cur.read_bytes()).hexdigest() if cur.is_file() else '-'}\n".encode())
    for mod in CHECK_CODE:
        src = importlib.import_module(f"{__package__}.{mod}").__file__
        h.update(f"{mod} {hashlib.sha256(Path(src).read_bytes()).hexdigest()}\n".encode())
    return h.hexdigest()


def check(ctx) -> dict:
    """The ledger's shape, that it only grew since the last commit, and how many cards' content is read."""
    from ..arcade.hub import git
    from ..kernel import paths
    st = ctx.store
    entries, evs = ledger(st), events(st)
    probs = problems(entries, evs)
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
    from . import dimensions, numbering
    nb = numbering.check(ctx)                      # GM-4 is a proposal: reported here, not yet a failure
    laws = {}
    if dimensions.set_card(ctx) is not None:       # a domain that joined as a set: its laws must be consistent
        dims = dimensions.check(ctx)
        probs += dims["problems"]
        laws = {q: r["consistent"] for q, r in dims["laws"].items()}
    return {"status": "fail" if probs else ("pass" if entries else "vacuous"), "problems": probs,
            "numberings": {s: v["status"] for s, v in nb["sets"].items()}, "numbering_problems": nb["problems"],
            "atoms": len(entries), "basis": basis_version(entries), "events": len(evs), "sets": dict(sets),
            "physics_laws": laws,
            "coverage": round(done / total, 4) if total else None, "missing": missing[:20]}


__all__ = ["ContentIndex", "EVENT_KINDS", "LEAVES", "LOGIC", "RANK", "SPECIAL", "STRUCTURAL_MAX_DIGITS", "add",
           "atom", "base_atom", "basis_atoms", "basis_version", "card_content", "carry", "check", "check_key",
           "cofactor", "cost", "decimal_digits", "decode", "deprecate", "divides", "events", "expand", "exponents",
           "factor", "forget_ranks", "from_tokens", "from_vector", "gcd", "index_of", "jaccard", "lcm", "ledger",
           "match", "merge", "module_content", "norm", "nth_prime", "preserves_gcd", "primes", "problems",
           "ranked_atom", "resolve", "scale", "stored", "structural", "sub", "substitute", "support", "sync",
           "term_content", "to_vector", "tokens", "unzig", "valuation", "variables", "vector_problems", "zig"]
