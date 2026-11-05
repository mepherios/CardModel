"""numbering — each Gödel set's numbering and whether it is admissible (Gödel method W-5: GM-4, Rule-1 to Rule-6,
Def-1, Def-4, Ph-6).

  objects    B0 and computation: core terms over the set's op atoms (and those of the sets it extends), integer
             constants and variables; an op beyond the IR takes the arity its set card states (``arities``, read from
             the op card's Python form). machines: effects, an effect atom with a guard slot (logic/true when the
             effect always happens) and its arguments, the argument count fixed per effect (``arities``).
  code       Gödel's positional code of the prefix tokens (Def-9, Def-27): atom k -> 3k + 1, integer c -> 3·zig(c) +
             2, the j-th variable in order of first appearance -> 3j + 3. Variables are named by that order, so an
             object is a term up to the names of its variables.
  conditions (CONDITIONS) drawn from Def-1, Rule-1 to Rule-6, Feferman (1960) and Grabmayr (2021): injective,
             effective both ways, a decidable image, codes start at 1, parts smaller than wholes, and a provability
             predicate built naturally from the proof relation. ``check_set`` tests each on generated objects,
             corrupted codes and random integers; ``check`` runs every godel_set card against what it states.

Honest limits (L1): the tests run on generated objects and on integers up to a bound, so they are witnesses of
conditions whose general proof is the argument stated with each (unique factorization, a total decision procedure,
shifting positions to larger primes). The natural-provability condition is checked as a statement on the card:
that provability is ∃ of the decidable proof relation (Lean's kernel) with no further clause, as Feferman's
deviant predicates would add.
"""
from __future__ import annotations

import random
from collections import Counter

from . import godel as G

CONDITIONS = [
    ("injective", "distinct objects get distinct codes", ["Rule-1", "Def-1"],
     "unique factorization: the exponents of the consecutive primes are the token codes, and the tokens parse in "
     "one way given the arities"),
    ("effective", "encoding and decoding are computable, and decoding an object's code gives the object back",
     ["Rule-2", "Def-1"], "both directions are total programs here (encode, decode)"),
    ("decidable_image", "whether a number codes an object is decidable", ["Rule-2", "Def-1"],
     "is_code: divide out the consecutive primes, check each token and parse by the arities; it stops on every "
     "input"),
    ("codes_start_at_1", "every token code is at least 1", ["Rule-3"],
     "3k + 1, 3·zig(c) + 2 and 3j + 3 are all at least 1, so no trailing position can vanish"),
    ("parts_smaller", "a proper part has a smaller code, and its content divides the whole's", ["Rule-5"],
     "a part's tokens sit at later positions (larger primes, same exponents) inside the whole, beside other factors "
     "of at least 2; and a part's atoms are among the whole's"),
    ("natural_provability", "provability is ∃ of the decidable proof relation over this numbering, with no further "
     "clause", ["Rule-6", "Def-4", "Ph-6"],
     "Feferman (1960) and Grabmayr (2021): a deviant predicate (one that adds, say, a consistency check below the "
     "proof) can make a theory 'prove its own consistency'; the natural one cannot"),
]
NATURAL = {"form": "exists_proof", "relation": "method/lean_kernel"}
LOGIC_ARITY = {"logic/true": 0, "logic/false": 0, "logic/not": 1, "logic/and": 2, "logic/or": 2, "logic/implies": 2,
               "logic/iff": 2, "logic/eq": 2, "logic/forall": 2, "logic/exists": 2}


_zig, _unzig = G.zig, G.unzig


class Numbering:
    """One Gödel set's numbering: its atoms (with those of the sets it extends) and their arities."""

    def __init__(self, ctx, set_name: str):
        st = ctx.store
        self.ctx, self.name = ctx, set_name
        self.card = st.get(f"godel_set/{set_name}")
        chain, s = [], set_name
        while s:
            chain.append(s)
            c = st.get(f"godel_set/{s}")
            s = c.get("extends") if c else None
        self.sets = chain
        self.entries = G.ledger(st)
        self.by_atom = {e["atom"]: e for e in self.entries if e["set"] in chain}
        self.by_index = {e["index"]: e["atom"] for e in self.by_atom.values()}
        arities = (self.card or {}).get("arities") or {}
        self.arity: dict[str, int] = {}
        for a in self.by_atom:
            if a.startswith("op/"):
                op = ctx.ops.get(a[3:])
                if op is not None:
                    self.arity[a] = op.card["ir"]["arity"]
                elif a in arities:                          # an op beyond the IR: its arity is stated on the set
                    self.arity[a] = arities[a]
            elif a.startswith("effect/") and a in arities:
                self.arity[a] = 1 + arities[a]                   # the guard slot, then the arguments
            elif a in LOGIC_ARITY:
                self.arity[a] = LOGIC_ARITY[a]
            elif a.startswith("core_type/"):
                self.arity[a] = 0
            elif a in arities:                                  # any other atom: its arity is stated
                self.arity[a] = arities[a]
        self.true = "logic/true" if "logic/true" in self.by_atom else None

    # -- objects as trees: [atom, child...] | ["var", name] | ["int", value] -------------------------------------
    def from_effect(self, e: dict) -> list:
        guard = e.get("guard")
        return [f"effect/{e['op']}", guard if guard is not None else [self.true], *(e.get("args") or [])]

    def tokens(self, t, varnames: list) -> list[int]:
        """Def-27 prefix tokens of an object (the core's ``godel.tokens``), after checking each atom's arity here."""
        stack = [t]
        while stack:
            x = stack.pop()
            if not (isinstance(x, list) and x):
                raise ValueError(f"not an object: {x!r}")
            if x[0] in ("var", "int"):
                continue
            atom = G.atom(x[0])
            if atom is None or atom not in self.by_atom or len(x) - 1 != self.arity.get(atom, 0):
                raise ValueError(f"{atom or x[0]} with {len(x) - 1} arguments is not an object of {self.name}")
            stack.extend(x[1:])
        return G.tokens(t, self.by_atom, varnames)

    def encode(self, t) -> int:
        n = 1
        for i, c in enumerate(self.tokens(t, []), start=1):
            n *= G.nth_prime(i) ** c
        return n

    def _codes(self, n: int) -> list[int] | None:
        """The exponents of 2, 3, 5, ... in order, when n is a product of the first m primes each to at least 1."""
        return G.exponents(n, gaps=False) if n >= 2 else None    # None on a skipped prime: no position has it

    def decode(self, n: int):
        """The object n codes (variables named x0, x1, ... by first appearance), or None."""
        codes = self._codes(n)
        if codes is None:
            return None
        pos, seen = 0, [0]

        def build():
            nonlocal pos
            if pos >= len(codes):
                raise ValueError("ran out of tokens")
            c = codes[pos]
            pos += 1
            kind = c % 3
            if kind == 2:
                return ["int", _unzig((c - 2) // 3)]
            if kind == 0:
                j = c // 3 - 1
                if j > seen[0]:
                    raise ValueError("a variable out of first-appearance order")
                if j == seen[0]:
                    seen[0] += 1
                return ["var", f"x{j}"]
            atom = self.by_index.get((c - 1) // 3)
            if atom is None or atom not in self.arity:
                raise ValueError("an index that is no atom of this set")
            k = self.arity.get(atom, 0)
            return [atom, *[build() for _ in range(k)]]
        try:
            t = build()
        except ValueError:
            return None
        return t if pos == len(codes) else None

    def is_code(self, n: int) -> bool:
        """Decidable: does n code an object of this set?"""
        return self.decode(n) is not None

    # -- generated objects ---------------------------------------------------------------------------------------
    def generate(self, rng: random.Random, depth: int = 3):
        heads = sorted(a for a in self.arity if not a.startswith("effect/") or self.name == "machines")
        terms = [a for a in heads if a.startswith("op/") and self.arity[a] <= 3]
        if self.name != "machines":
            heads = [a for a in heads if a.startswith("op/") or self.arity[a] == 0]

        own = [a for a in heads if self.by_atom[a]["set"] == self.name]
        # the set's constants, as its card lists them (a base quantity of the physics set): atoms of arity 0
        # that are leaves of its objects
        declared = set((self.card or {}).get("constants") or [])
        consts = [a for a in own if a in declared and self.arity.get(a) == 0]

        def term(d):
            if d == 0 or rng.random() < 0.3 or not terms:
                if consts and rng.random() < 0.4:
                    return [rng.choice(consts)]
                return ["var", rng.choice("abc")] if rng.random() < 0.5 else ["int", rng.randint(-40, 40)]
            a = rng.choice(terms)
            return [a, *[term(d - 1) for _ in range(self.arity[a])]]
        if self.name == "machines":
            eff = rng.choice(own)
            guard = [self.true] if rng.random() < 0.6 else term(1)
            return [eff, guard, *[term(depth - 1) for _ in range(self.arity[eff] - 1)]]
        root = rng.choice([a for a in own if a in terms] or terms)
        return [root, *[term(depth - 1) for _ in range(self.arity[root])]]


def canonical(t, names: dict | None = None):
    """Variables renamed x0, x1, ... by first appearance (what a code can tell apart)."""
    names = {} if names is None else names
    if isinstance(t, list) and t and t[0] == "var":
        names.setdefault(t[1], f"x{len(names)}")
        return ["var", names[t[1]]]
    if isinstance(t, list) and t and t[0] == "int":
        return t
    if isinstance(t, list):
        return [t[0], *[canonical(a, names) for a in t[1:]]]
    return t


def _subterms(t):
    if isinstance(t, list) and t and t[0] not in ("var", "int"):
        for a in t[1:]:
            yield a
            yield from _subterms(a)


def _content(t) -> Counter:
    """The content of an object of any set: every non-leaf head an atom (engines/godel.term_content)."""
    return G.term_content(t, None)


def check_set(ctx, set_name: str, seed: int = 0, samples: int = 120) -> dict:
    """Every condition of CONDITIONS on one set: generated objects, corrupted codes, random integers."""
    nb = Numbering(ctx, set_name)
    rng = random.Random(seed)
    res = {c[0]: {"status": "pass", "checked": 0} for c in CONDITIONS}

    def fail(cond, why):
        if res[cond]["status"] == "pass":
            res[cond] = {"status": "fail", "checked": res[cond]["checked"], "at": why}
    seen: dict[int, list] = {}
    missing = sorted(a for a, e in nb.by_atom.items() if e["set"] == set_name and a not in nb.arity)
    if missing:                                     # a token with no fixed arity cannot be parsed back
        fail("effective", f"atoms without a fixed arity: {missing[:4]}")
        fail("decidable_image", "objects over atoms without a fixed arity cannot be parsed")
        if len(missing) == sum(1 for e in nb.by_atom.values() if e["set"] == set_name):
            samples = 0
    for _ in range(samples):
        t = canonical(nb.generate(rng))
        try:
            n = nb.encode(t)
        except ValueError as exc:
            fail("effective", str(exc))
            continue
        res["effective"]["checked"] += 1
        if nb.decode(n) != t:
            fail("effective", f"decode(encode({t})) = {nb.decode(n)}")
        res["injective"]["checked"] += 1
        if n in seen and seen[n] != t:
            fail("injective", f"{seen[n]} and {t} share a code")
        seen[n] = t
        res["codes_start_at_1"]["checked"] += 1
        if min(nb.tokens(t, [])) < 1:
            fail("codes_start_at_1", f"a token code below 1 in {t}")
        for s in _subterms(t):
            s = canonical(s)
            if not (isinstance(s, list) and s and s[0] not in ("var", "int")):
                continue
            res["parts_smaller"]["checked"] += 1
            if not nb.encode(s) < n:
                fail("parts_smaller", f"{s} is not smaller than {t}")
            if any(_content(t)[a] < e for a, e in _content(s).items()):
                fail("parts_smaller", f"the content of {s} does not divide that of {t}")
        # the decision accepts the code, and agrees with its definition on corruptions of it and on other integers
        res["decidable_image"]["checked"] += 1
        if not nb.is_code(n):
            fail("decidable_image", f"the code of {t} is rejected")
        for m in (n, n * G.nth_prime(len(nb.tokens(t, [])) + 1), n * 2, n // 2 if n % 4 == 0 else n + 1,
                  rng.randrange(2, 1 << 20)):
            res["decidable_image"]["checked"] += 1
            d = nb.decode(m)
            if nb.is_code(m) != (d is not None and nb.encode(d) == m):
                fail("decidable_image", f"is_code({m}) disagrees with decoding")
    prov = (nb.card or {}).get("numbering", {}).get("provability") or {}
    res["natural_provability"]["checked"] = 1
    if {k: prov.get(k) for k in NATURAL} != NATURAL:
        fail("natural_provability", f"the card states provability as {prov or 'nothing'}")
    else:
        lk = ctx.store.get(NATURAL["relation"])
        if lk is None or (lk.get("rank") or {}).get("decides") != "decidable":
            fail("natural_provability", "its proof relation is not a decidable method card")
    return {"set": set_name, "atoms": len(nb.by_atom), "conditions": res,
            "status": "fail" if any(r["status"] == "fail" for r in res.values()) else "pass"}


def check(ctx, seed: int = 0) -> dict:
    """Every godel_set card states its numbering (GM-4) and passes its conditions."""
    problems, sets = [], {}
    for c in ctx.store.cards("godel_set"):
        if not (c.get("numbering") or {}).get("conditions"):
            problems.append(f"{c.qualified}: states no admissible numbering (GM-4)")
            continue
        r = check_set(ctx, c.name, seed, samples=int((c.get("numbering") or {}).get("samples") or 120))
        sets[c.name] = r
        problems += [f"{c.qualified}: {k} fails: {v.get('at')}" for k, v in r["conditions"].items()
                     if v["status"] == "fail"]
    return {"status": "fail" if problems else ("pass" if sets else "vacuous"), "problems": problems, "sets": sets}


__all__ = ["CONDITIONS", "NATURAL", "Numbering", "canonical", "check", "check_set"]
