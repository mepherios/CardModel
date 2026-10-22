"""godel — the expanding Gödel model's foundation (docs/MATH_CORE.md phase 0, law CM43).

  ledger     the atoms, each with the prime of its index (2, 3, 5, 7, ...) and the Gödel set it entered with, in
             cards/godel/_pack_ledger.jsonl. The basis set B0 holds the core types, the logic primitives and the IR
             ops; other sets extend it (``godel_set`` cards). A new atom takes the next unused prime. The ledger is
             append-only: ``sync`` only appends lines, and the CM43 test compares it with its git history.
  content    a concept's factorization: the atoms of its terms, with multiplicity (an exponent vector). gcd and
             lcm are the minimum and maximum per atom, divides is <= per atom; each costs time in the support.
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
             given the atoms' arities. Content forgets arrangement; structure keeps it.
  carry      a map between sets sends each atom to a content vector. It preserves products; it preserves every
             gcd exactly when distinct atoms go to vectors with disjoint support; what it cannot send is the gap.

Honest limits (L1): content is only as canonical as the terms it is read from. Two equal behaviours written with
different atoms (SQUARE(x), MUL(x, x)) share factors only after a definition or a rewrite reduces them to the same
atoms. Constants and variables are not atoms: content counts operations, not values.
"""
from __future__ import annotations

import json
import math
from collections import Counter
from datetime import date

REGISTRY = "godel"
PACK = "_pack_ledger.jsonl"
LOGIC = ("logic/true", "logic/false", "logic/not", "logic/and", "logic/or", "logic/implies", "logic/iff",
         "logic/eq", "logic/forall", "logic/exists")
EVENT_KINDS = ("merge", "deprecate")
STRUCTURAL_MAX_DIGITS = 200          # Gödel's positional number is stored for terms up to this many decimal digits
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


def structural(t, ops, index, max_digits: int | None = STRUCTURAL_MAX_DIGITS) -> tuple[int | None, list[str], int]:
    """Gödel's positional number of a term (None when it would pass max_digits decimal digits: it grows too fast for
    large terms, so the structure hash is the identity), the variable order it used, and its size in digits."""
    varnames: list[str] = []
    toks = _tokens(t, ops, index, varnames)
    digits = int(sum(code * math.log10(nth_prime(i)) for i, code in enumerate(toks, start=1))) + 1
    if max_digits is not None and digits > max_digits:
        return None, varnames, digits
    n = 1
    for i, code in enumerate(toks, start=1):
        n *= nth_prime(i) ** code
    return n, varnames, len(str(n))


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
    return {"status": "fail" if probs else ("pass" if entries else "vacuous"), "problems": probs,
            "atoms": len(entries), "basis": basis_version(entries), "events": len(evs), "sets": dict(sets),
            "coverage": round(done / total, 4) if total else None, "missing": missing[:20]}


__all__ = ["EVENT_KINDS", "LOGIC", "STRUCTURAL_MAX_DIGITS", "basis_atoms", "basis_version", "card_content", "carry",
           "check", "decode", "deprecate", "divides", "events", "from_vector", "gcd", "index_of", "lcm", "ledger", "merge",
           "module_content", "nth_prime", "preserves_gcd", "problems", "resolve", "stored", "structural", "sync",
           "term_content", "to_vector", "vector_problems"]
