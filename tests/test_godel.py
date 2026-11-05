"""The expanding Gödel model's foundation: an append-only prime ledger (CM43), content stored as sparse vectors with
their basis version, never as integers (CM45), merges and deprecations as events, and structure."""
import math
import random
import shutil
import subprocess
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from helpers import ROOT, SEED, model_ctx, seed_note

from cardmodel.engines import godel as G

import json as _json


def proposed_atoms():
    """Atoms proposed but not yet minted (GODEL_METHOD rule 1: only the ledger writer mints). Cards that use only
    these are reported as 'proposed, not minted' instead of failing; anything else missing still fails."""
    p = ROOT / "cards" / "proposal" / "prop_godel_str_ops" / "card.json"
    if not p.exists():
        return set()
    return {a["atom"] for a in _json.loads(p.read_text(encoding="utf-8"))["candidate"]["atoms"]}


def _only_proposed(msg, proposed):
    return bool(proposed) and any(msg.startswith(a + ":") for a in proposed)
from cardmodel.engines.context import Ctx
from cardmodel.kernel.store import Store


class Ledger(unittest.TestCase):
    def test_ledger_is_append_only(self):
        ctx = model_ctx()
        entries = G.ledger(ctx.store)
        self.assertGreaterEqual(len(entries), 48)
        self.assertEqual(G.problems(entries), [])
        self.assertEqual([e["prime"] for e in entries[:5]], [2, 3, 5, 7, 11])
        # what the last commit holds is a prefix of what is here now, byte for byte
        rel = "cards/godel/_pack_ledger.jsonl"
        head = subprocess.run(["git", "--no-optional-locks", "show", f"HEAD:{rel}"], cwd=ROOT, capture_output=True,
                              text=True, timeout=60)
        if head.returncode == 0:
            self.assertTrue((ROOT / rel).read_text(encoding="utf-8").startswith(head.stdout), "a committed line changed")
        # appending never rewrites: three atoms, then two more; the first three lines are untouched
        d = Path(tempfile.mkdtemp(prefix="cardmodel_ledger_"))
        try:
            st = Store([("model", d)])
            G.sync(st, ["a/x", "a/y", "a/z"], "S", since="2026-01-01")
            first = (d / "godel" / "_pack_ledger.jsonl").read_text(encoding="utf-8")
            new = G.sync(st, ["a/y", "a/w", "a/v"], "T", since="2026-01-02")
            self.assertEqual([e["atom"] for e in new], ["a/w", "a/v"])
            after = (d / "godel" / "_pack_ledger.jsonl").read_text(encoding="utf-8")
            self.assertTrue(after.startswith(first))
            self.assertEqual([(e["atom"], e["prime"]) for e in G.ledger(st)],
                             [("a/x", 2), ("a/y", 3), ("a/z", 5), ("a/w", 7), ("a/v", 11)])
            self.assertEqual(G.sync(st, ["a/x"], "S"), [])
        finally:
            shutil.rmtree(d, ignore_errors=True)


class Content(unittest.TestCase):
    def test_content_algebra_and_carry(self):
        a, b = Counter({"x": 2, "y": 1}), Counter({"x": 1, "z": 3})
        self.assertEqual(G.gcd(a, b), Counter({"x": 1}))
        self.assertEqual(G.lcm(a, b), Counter({"x": 2, "y": 1, "z": 3}))
        self.assertTrue(G.divides(G.gcd(a, b), a) and G.divides(G.gcd(a, b), b))
        self.assertFalse(G.divides(a, b))
        idx = {"x": {"index": 1, "prime": 2}, "y": {"index": 2, "prime": 3}, "z": {"index": 3, "prime": 5}}
        self.assertEqual(G.to_vector(a, idx), ({"1": 2, "2": 1}, []))
        self.assertEqual(G.to_vector(Counter({"q": 1}), idx), ({}, ["q"]))
        # a witness for small cases (formal/GodelCore T1 proves it for every basis): the vector operations are the
        # integers' gcd, lcm and divisibility, without the model ever building those integers
        rng = random.Random(SEED)
        primes = [2, 3, 5, 7]
        num = lambda v: math.prod(p ** v[k] for k, p in zip("wxyz", primes))  # noqa: E731
        for _ in range(60):
            u = Counter({k: rng.randint(0, 3) for k in "wxyz"})
            v = Counter({k: rng.randint(0, 3) for k in "wxyz"})
            self.assertEqual(num(G.gcd(u, v)), math.gcd(num(u), num(v)), seed_note(self))
            self.assertEqual(num(G.lcm(u, v)), math.lcm(num(u), num(v)), seed_note(self))
            self.assertEqual(G.divides(u, v), num(v) % num(u) == 0, seed_note(self))
        # a map carries what it can and leaves the rest as the gap; GCD carries when supports are disjoint
        image, gap = G.carry(a, {"x": Counter({"X": 1}), "y": Counter({"Y": 2})})
        self.assertEqual((image, gap), (Counter({"X": 2, "Y": 2}), Counter()))
        image, gap = G.carry(b, {"x": Counter({"X": 1})})
        self.assertEqual((image, gap), (Counter({"X": 1}), Counter({"z": 3})))
        self.assertTrue(G.preserves_gcd({"x": Counter({"X": 1}), "y": Counter({"Y": 1})}))
        self.assertFalse(G.preserves_gcd({"x": Counter({"X": 1}), "y": Counter({"X": 1, "Y": 1})}))

    def test_cards_have_content(self):
        from cardmodel.engines import verify
        tmp = Path(tempfile.mkdtemp(prefix="cardmodel_gstate_"))
        try:
            ctx = _StateIn(model_ctx().store, tmp)
            r, hit = verify.godel_section(ctx)                  # computed, then kept under its input key
            self.assertFalse(hit)
            kept, hit = verify.godel_section(ctx)               # on the model's real cards: the kept result is it
            self.assertTrue(hit)
            self.assertEqual(kept, r)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        proposed = proposed_atoms()
        problems = [x for x in r["problems"] if not _only_proposed(x, proposed)]
        missing = [x for x in r["missing"] if not _only_proposed(x, proposed)]
        skipped = len(r["problems"]) - len(problems) + len(r["missing"]) - len(missing)
        if skipped:
            print(f"\n[test_godel] {skipped} card(s) use proposed, not minted, atoms (prop_godel_str_ops)")
        self.assertEqual(problems, [])
        self.assertEqual(missing, [], r["missing"])
        sq, _ = G.card_content(ctx, ctx.store.get("algorithm/sum_of_squares"))
        self.assertIn("op/MUL", sq)
        th, why = G.card_content(ctx, ctx.store.cards("theorem")[0])
        self.assertGreaterEqual(th["logic/forall"], 1, why)


class _StateIn(Ctx):
    """A context whose state directory (where verify keeps the godel section's cache) is a temporary one."""

    def __init__(self, store, root: Path):
        super().__init__(store)
        self._root = root

    @property
    def state_root(self) -> Path:
        return self._root


class SectionCache(unittest.TestCase):
    def test_godel_section_recomputes_exactly_when_an_input_changes(self):
        from cardmodel.engines import verify
        tmp = Path(tempfile.mkdtemp(prefix="cardmodel_gcache_"))
        try:
            st = Store([("model", tmp / "cards")])
            G.sync(st, ["op/ADD", "op/MUL"], "S", since="2026-01-01")
            ctx = Ctx(st)
            self.assertEqual(ctx.state_root, tmp / "state")
            first, hit = verify.godel_section(ctx)
            self.assertFalse(hit)
            for _ in range(2):                                  # unchanged inputs: a hit, equal to a fresh check
                kept, hit = verify.godel_section(ctx)
                self.assertTrue(hit)
                self.assertEqual(kept, first)
                self.assertEqual(kept, G.check(ctx))
            rep = verify.run(ctx, seed=SEED, only=["godel"], save=False)
            self.assertEqual((rep["cached"], rep["sections"]["godel"]), (["godel"], first))
            # each kind of input it reads, changed once: a new key, the section recomputes and equals a fresh check
            changes = [lambda: G.sync(st, ["op/SUB"], "S", since="2026-01-02"),                       # the ledger
                       lambda: st.save({"name": "S", "numbering": {"conditions": ["effective"]}},
                                       category="godel_set"),                                          # a set
                       lambda: st.save({"name": "f", "ir": {"functions": []}}, category="function"),     # a card read
                       lambda: st.save({"name": "f", "ir": {"functions": [], "note": 1}}, category="function")]
            for change in changes:
                before = G.check_key(ctx)
                change()
                self.assertNotEqual(G.check_key(ctx), before)
                res, hit = verify.godel_section(ctx)
                self.assertFalse(hit)
                self.assertEqual(res, G.check(ctx))
                self.assertTrue(verify.godel_section(ctx)[1])
            # the engines' code is part of the key: another engine in it gives another key
            key, code = G.check_key(ctx), G.CHECK_CODE
            try:
                G.CHECK_CODE = code + ("codes",)
                self.assertNotEqual(G.check_key(ctx), key)
            finally:
                G.CHECK_CODE = code
            self.assertEqual(G.check_key(ctx), key)
            # a corrupt cache is a miss, never an error
            (tmp / "state" / f"{verify.GODEL_CACHE}.json").write_text("{", encoding="utf-8")
            self.assertFalse(verify.godel_section(ctx)[1])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class Structure(unittest.TestCase):
    def test_a_term_with_a_huge_constant_has_no_structural_number(self):
        """A constant's token is an exponent: 1103515245 (an LCG's multiplier, as in a learned function card) would
        make a number of about 10^11 bits, and computing it ran verify for 40 minutes where a learned card met
        four_sources. structural gives no number for it, at once; a small constant still numbers."""
        import time
        ctx = model_ctx()
        idx = G.index_of(ctx.store)
        t0 = time.perf_counter()
        n, _, digits = G.structural(["ADD", ["MUL", ["var", "x"], ["int", 1103515245]], ["int", 12345]], ctx.ops, idx)
        self.assertIsNone(n)
        self.assertGreater(digits, 10 ** 9)
        self.assertLess(time.perf_counter() - t0, 5.0)
        n, _, _ = G.structural(["ADD", ["var", "x"], ["int", 3]], ctx.ops, idx)
        self.assertIsNotNone(n)

    def test_structural_numbers_decode_exactly(self):
        # valuation is defined only for n != 0 (0 is divisible by every power: it would never return)
        with self.assertRaises(ValueError):
            G.valuation(0, 2)
        self.assertEqual(G.valuation(-24, 2), (3, -3))
        ctx = model_ctx()
        idx, entries = G.index_of(ctx.store), G.ledger(ctx.store)
        rng = random.Random(SEED)
        ops = [k for k in ctx.ops if (ctx.ops[k].card.get("ir") or {}).get("arity") in (1, 2)
               and f"op/{k}" not in proposed_atoms()]          # proposed, not minted: no prime yet

        def term(depth):
            if depth == 0 or rng.random() < 0.3:
                return ["var", rng.choice("abc")] if rng.random() < 0.5 else ["int", rng.randint(-9, 9)]
            op = rng.choice(ops)
            return [op, *[term(depth - 1) for _ in range(ctx.ops[op].card["ir"]["arity"])]]
        for _ in range(40):
            t = term(3)
            n, varnames, digits = G.structural(t, ctx.ops, idx, max_digits=None)
            self.assertEqual(G.decode(n, ctx.ops, entries, varnames), t, seed_note(self))
            self.assertEqual(digits, G.decimal_digits(n))
            if digits < 4000:
                self.assertEqual(digits, len(str(n)))

    def test_large_terms_keep_only_their_hash(self):
        ctx = model_ctx()
        idx = G.index_of(ctx.store)
        t = ["var", "x"]
        for i in range(40):
            t = ["ADD", t, ["int", i]]
        n, _, digits = G.structural(t, ctx.ops, idx)
        self.assertIsNone(n)                               # too large to store: the structure hash is the identity
        self.assertGreater(digits, G.STRUCTURAL_MAX_DIGITS)


class Storage(unittest.TestCase):
    """CM45: a card stores its content as index -> exponent with its basis version, never as the content integer."""

    def test_stored_records_follow_the_rules(self):
        ctx = model_ctx()
        entries = G.ledger(ctx.store)
        a, why = G.card_content(ctx, ctx.store.get("algorithm/sum_of_squares"))
        rec = G.stored(a, why, entries)
        self.assertNotIn("number", rec)
        self.assertEqual(rec["basis"], G.basis_version(entries))
        self.assertEqual(G.from_vector(rec["vector"], entries), +a)
        self.assertEqual(G.vector_problems(rec, entries), [])
        self.assertTrue(G.vector_problems({**rec, "number": "4489"}, entries))
        late = {**rec, "vector": {**rec["vector"], str(rec["basis"] + 1): 1}}
        self.assertTrue(any("later than" in x for x in G.vector_problems(late, entries)))
        wrong = {**rec, "content": {**rec["content"], "op/ADD": 99}}
        self.assertTrue(any("disagree" in x for x in G.vector_problems(wrong, entries)))

    def test_every_definition_stores_a_vector(self):
        ctx = model_ctx()
        entries = G.ledger(ctx.store)
        defs = ctx.store.cards("definition")
        self.assertTrue(defs)
        for d in defs:
            self.assertEqual(G.vector_problems(d.get("godel") or {}, entries), [], d.qualified)
            self.assertTrue(str((d.get("identity") or {}).get("hash", "")).startswith("sha256:"), d.qualified)

    def test_merges_and_deprecations_never_relate_products(self):
        d = Path(tempfile.mkdtemp(prefix="cardmodel_events_"))
        try:
            st = Store([("model", d)])
            G.sync(st, ["c/a", "c/b", "c/c", "c/d", "c/sq"], "S", since="2026-01-01")
            before = (d / "godel" / "_pack_ledger.jsonl").read_text(encoding="utf-8")
            G.merge(st, "c/b", "c/a", "the same concept, minted twice")
            G.deprecate(st, "c/sq", {"c/c": 2}, "a square is c times c")
            self.assertTrue((d / "godel" / "_pack_ledger.jsonl").read_text(encoding="utf-8").startswith(before))
            evs = G.events(st)
            self.assertEqual([e["event"] for e in evs], ["merge", "deprecate"])
            self.assertEqual(G.problems(G.ledger(st), evs), [])
            self.assertEqual(len(G.ledger(st)), 5)                    # no index is deleted, reused or renumbered
            self.assertEqual(G.resolve({"2": 1, "5": 1, "4": 3}, evs), {"1": 1, "3": 2, "4": 3})
            with self.assertRaises(ValueError):                       # a cycle: a -> b while b -> a
                G.merge(st, "c/a", "c/b", "back again")
            bad = [{"name": "x", "event": "relation", "of": 1, "to": {"2": 1}}]
            self.assertTrue(any("transformation layer" in x for x in G.problems(G.ledger(st), bad)))
        finally:
            shutil.rmtree(d, ignore_errors=True)


def _random_term(ctx, rng, depth=3, names="abc", leaf=0.3):
    ops = [k for k in ctx.ops if (ctx.ops[k].card.get("ir") or {}).get("arity") in (1, 2)]

    def term(d):
        if d == 0 or rng.random() < leaf:
            return ["var", rng.choice(names)] if rng.random() < 0.6 else ["int", rng.randint(-9, 9)]
        op = rng.choice(ops)
        return [op, *[term(d - 1) for _ in range(ctx.ops[op].card["ir"]["arity"])]]
    return term(depth)


def _random_vector(rng, atoms="wxyz", lo=0, hi=3) -> Counter:
    return G._strip(Counter({k: rng.randint(lo, hi) for k in atoms}))


class Algebra(unittest.TestCase):
    """The content group and lattice (docs/GODEL_TARGET.md §2), each identity on random vectors and terms."""

    def test_group_laws_and_the_cofactor(self):
        rng = random.Random(SEED)
        for _ in range(60):
            a, b, c = (_random_vector(rng) for _ in range(3))
            self.assertEqual(G.add(a, b), G.add(b, a), seed_note(self))
            self.assertEqual(G.add(G.add(a, b), c), G.add(a, G.add(b, c)), seed_note(self))
            self.assertEqual(G.add(G.sub(a, b), b), a, seed_note(self))               # inverses, signed
            self.assertEqual(G.scale(a, 3), G.add(a, a, a), seed_note(self))
            self.assertEqual(G.norm(G.add(a, b)), G.norm(a) + G.norm(b), seed_note(self))
            self.assertEqual(G.divides(a, b), G.cofactor(b, a) is not None, seed_note(self))
            if G.divides(a, b):
                self.assertEqual(G.add(G.cofactor(b, a), a), b, seed_note(self))      # the cofactor is exact
            g, l = G.gcd(a, b), G.lcm(a, b)
            self.assertTrue(G.divides(g, a) and G.divides(g, b) and G.divides(a, l) and G.divides(b, l), seed_note(self))
            self.assertEqual(G.add(g, l), G.add(a, b), seed_note(self))             # min + max = a + b per atom
            self.assertEqual(G.gcd(a, G.lcm(a, b)), a, seed_note(self))             # absorption
            self.assertLessEqual(0.0, G.jaccard(a, b), seed_note(self))
            self.assertLessEqual(G.jaccard(a, b), 1.0, seed_note(self))
            self.assertEqual(G.jaccard(a, a), 1.0)
        ratio = G.sub(Counter({"m": 1}), Counter({"s": 2}))                           # a dimension: m / s^2
        self.assertEqual(ratio, Counter({"m": 1, "s": -2}))
        self.assertEqual(G.add(ratio, Counter({"s": 2})), Counter({"m": 1}))
        self.assertEqual(G.support(ratio), {"m", "s"})
        self.assertIsNone(G.cofactor(Counter({"x": 1}), Counter({"y": 1})))

    def test_substitution_only_adds_content(self):
        """An instance of a pattern is divisible by the pattern, with the exact cofactor Σ m_v·γ(σ(v)): what lets
        a divisibility test refute a match before it is tried."""
        ctx = model_ctx()
        rng = random.Random(SEED)
        for _ in range(60):
            p = _random_term(ctx, rng, depth=3, names="uvw")
            binds = {v: _random_term(ctx, rng, depth=2) for v in "uvw"}
            inst = G.substitute(p, binds)
            cp, ci = G.term_content(p, ctx.ops), G.term_content(inst, ctx.ops)
            self.assertTrue(G.divides(cp, ci), seed_note(self))
            counts = Counter(x[1] for x in _leaves(p) if x[0] == "var")
            expect = G.add(cp, *(G.scale(G.term_content(binds[v], ctx.ops), m) for v, m in counts.items()))
            self.assertEqual(ci, expect, seed_note(self))
            self.assertEqual(G.match(p, inst) is not None, True, seed_note(self))
            self.assertEqual(G.cofactor(ci, cp), G.sub(expect, cp), seed_note(self))

    def test_cost_is_linear_in_content(self):
        """<γ(t), c> is search.expr_cost(t): the cost of a term from its content alone."""
        from cardmodel.engines import search
        ctx = model_ctx()
        costs = search.op_costs(ctx.store)
        self.assertTrue(costs)
        rng = random.Random(SEED)
        for _ in range(60):
            t = _random_term(ctx, rng, depth=4)
            self.assertAlmostEqual(G.cost(G.term_content(t, ctx.ops), costs), search.expr_cost(t, costs),
                                   msg=seed_note(self))

    def test_a_module_is_the_sum_of_its_functions_in_any_order(self):
        ctx = model_ctx()
        rng = random.Random(SEED)
        fns = [{"name": f"f{i}", "body": [{"k": "return", "value": _random_term(ctx, rng, depth=3)}]} for i in range(12)]
        whole = G.module_content({"functions": fns}, ctx.ops)
        parts = [G.term_content(f["body"], ctx.ops) for f in fns]
        self.assertEqual(whole, G.add(*parts))
        rng.shuffle(parts)
        self.assertEqual(whole, G.add(*parts))                                        # merge from any worker order
        self.assertEqual(whole, G.add(G.add(*parts[:5]), G.add(*parts[5:])))
        changed = {**fns[3], "body": [{"k": "return", "value": _random_term(ctx, rng, depth=3)}]}
        delta = G.sub(G.term_content(changed["body"], ctx.ops), G.term_content(fns[3]["body"], ctx.ops))
        self.assertEqual(G.add(whole, delta), G.module_content({"functions": [*fns[:3], changed, *fns[4:]]}, ctx.ops))

    def test_carry_is_a_homomorphism(self):
        rng = random.Random(SEED)
        for _ in range(40):
            mapping = {k: _random_vector(rng, "XYZ", 0, 2) for k in "wxy" if rng.random() < 0.8}
            a, b = _random_vector(rng), _random_vector(rng)
            ia, ga = G.carry(a, mapping)
            ib, gb = G.carry(b, mapping)
            self.assertEqual(G.carry(G.add(a, b), mapping), (G.add(ia, ib), G.add(ga, gb)), seed_note(self))
            self.assertEqual(G.preserves_gcd(mapping), all(
                not (G.support(u) & G.support(v)) for i, u in enumerate(mapping.values())
                for v in list(mapping.values())[i + 1:]), seed_note(self))

    def test_matching(self):
        sq = ["MUL", ["var", "a"], ["var", "a"]]
        self.assertEqual(G.match(sq, ["MUL", ["ADD", ["var", "x"], ["int", 1]], ["ADD", ["var", "x"], ["int", 1]]]),
                         {"a": ["ADD", ["var", "x"], ["int", 1]]})
        self.assertIsNone(G.match(sq, ["MUL", ["var", "x"], ["var", "y"]]))
        self.assertIsNone(G.match(["ADD", ["var", "a"], ["int", 1]], ["ADD", ["var", "x"], ["int", 2]]))
        self.assertEqual(G.match(["ADD", ["var", "a"], ["int", 1]], ["ADD", ["var", "x"], ["int", 1]]), {"a": ["var", "x"]})
        self.assertEqual(G.match(["int", 3], ["int", 3]), {})
        self.assertEqual(G.match(["CALL", "f", ["var", "a"]], ["CALL", "f", ["int", 2]]), {"a": ["int", 2]})
        self.assertIsNone(G.match(["CALL", "f", ["var", "a"]], ["CALL", "g", ["int", 2]]))
        self.assertEqual(G.variables(["ADD", ["MUL", ["var", "y"], ["var", "x"]], ["var", "y"]]), ["y", "x"])

    def test_factoring_over_a_library(self):
        """A term over the concepts it contains: the largest concept first, its bindings factored in turn, the
        cofactor what no concept covers, and the vector equation γ(t) = γ(context) + Σ γ(instance)."""
        ctx = model_ctx()
        lib = {"sq": ["MUL", ["var", "a"], ["var", "a"]],
               "sumsq": ["ADD", ["MUL", ["var", "a"], ["var", "a"]], ["MUL", ["var", "b"], ["var", "b"]]]}
        t = ["SUB", ["ADD", ["MUL", ["ADD", ["var", "p"], ["int", 1]], ["ADD", ["var", "p"], ["int", 1]]],
                     ["MUL", ["var", "q"], ["var", "q"]]], ["MUL", ["MUL", ["var", "z"], ["var", "z"]], ["var", "w"]]]
        r = G.factor(t, lib, ctx.ops)
        self.assertEqual(r["term"], ["SUB", ["CALL", "sumsq", ["ADD", ["var", "p"], ["int", 1]], ["var", "q"]],
                                     ["MUL", ["CALL", "sq", ["var", "z"]], ["var", "w"]]])
        self.assertEqual([u["key"] for u in r["uses"]], ["sumsq", "sq"])
        self.assertEqual(r["cofactor"], Counter({"op/SUB": 1, "op/MUL": 1}))
        self.assertTrue(r["check"])
        self.assertEqual(G.expand(r["term"], lib), t)
        # excluding a concept, or factoring a concept over the others: a definition does not use itself
        self.assertEqual(G.factor(lib["sumsq"], lib, ctx.ops, exclude=["sumsq"])["term"],
                         ["ADD", ["CALL", "sq", ["var", "a"]], ["CALL", "sq", ["var", "b"]]])
        # random: every factoring satisfies the equation and unfolds back to the term; the index never refutes a
        # pattern that matches (G3 at the index)
        rng = random.Random(SEED)
        for _ in range(40):
            library = {}
            while len(library) < 4:
                p = _random_term(ctx, rng, depth=2, names="uv", leaf=0.2)
                if G.term_content(p, ctx.ops):
                    library[f"c{len(library)}"] = p
            index = G.ContentIndex({k: G.term_content(p, ctx.ops) for k, p in library.items()})
            term = _random_term(ctx, rng, depth=3)
            for _ in range(3):                                   # plant instances of the library in it
                key = rng.choice(list(library))
                inst = G.substitute(library[key], {v: _random_term(ctx, rng, depth=1) for v in "uv"})
                term = [rng.choice([k for k in ctx.ops if ctx.ops[k].card["ir"].get("arity") == 2]), term, inst]
            r = G.factor(term, library, ctx.ops, index=index)
            self.assertTrue(r["check"], seed_note(self))
            self.assertEqual(G.expand(r["term"], library), term, seed_note(self))
            self.assertTrue(r["uses"], seed_note(self))
            for s in _subterms(term):
                c = G.term_content(s, ctx.ops)
                for k, p in library.items():
                    if G.match(p, s) is not None:
                        self.assertIn(k, index.divisors(c), seed_note(self))

    def test_the_index_agrees_with_the_definitions(self):
        rng = random.Random(SEED)
        items = {f"k{i}": _random_vector(rng, "vwxyz", 0, 2) for i in range(30)}
        index = G.ContentIndex(items)
        self.assertEqual(len(index), 30)
        for _ in range(40):
            c = _random_vector(rng, "vwxyz", 0, 3)
            self.assertEqual(index.divisors(c), sorted(k for k, v in items.items() if v and G.divides(v, c)), seed_note(self))
            self.assertEqual(index.divisors(c, empty=True), sorted(k for k, v in items.items() if G.divides(v, c)),
                             seed_note(self))
            self.assertEqual(index.multiples(c), sorted(k for k, v in items.items() if G.divides(c, v)), seed_note(self))
            brute = sorted(((k, G.jaccard(c, v)) for k, v in items.items() if G.support(v) & G.support(c)),
                           key=lambda kv: (-kv[1], kv[0]))[:5]
            self.assertEqual(index.similar(c, 5), brute, seed_note(self))
        index.remove("k0")
        index.add("k1", Counter())
        self.assertNotIn("k0", index)
        self.assertEqual(index.divisors(Counter({"v": 1}), empty=True)[:1], ["k1"])

    def test_every_walk_is_iterative(self):
        """Depth costs nothing: content, tokens, parsing and matching of a term 5000 deep."""
        ctx = model_ctx()
        idx, entries = G.index_of(ctx.store), G.ledger(ctx.store)
        t = ["var", "x"]
        for i in range(5000):
            t = ["ADD", t, ["int", i % 7]]
        self.assertEqual(G.term_content(t, ctx.ops), Counter({"op/ADD": 5000}))
        names: list[str] = []
        toks = G.tokens(t, idx, names, ops=ctx.ops)
        self.assertEqual(len(toks), 10001)
        self.assertEqual(G.from_tokens(toks, ctx.ops, entries, names), t)
        self.assertEqual(G.variables(t), ["x"])
        self.assertEqual(G.match(t, t), {"x": ["var", "x"]})
        shared = ["ADD", ["var", "x"], ["int", 1]]
        for _ in range(60):                                      # a DAG whose tree is 2^60 nodes
            shared = ["MUL", shared, shared]
        self.assertEqual(G.term_content(shared, ctx.ops)["op/MUL"], 2 ** 60 - 1)

    def test_the_structure_is_computed_in_one_place(self):
        """No module outside godel.py (and Gödel's own 1931 definitions) defines primes, content or the zigzag."""
        import re
        own = {"godel.py", "godel1931.py"}
        pattern = re.compile(r"^\s*def (_?zig|_?unzig|_?primes|nth_prime|_?content_of|term_content)\b", re.M)
        found = sorted(str(p.relative_to(ROOT)) for p in (ROOT / "cardmodel").rglob("*.py")
                       if p.name not in own and pattern.search(p.read_text(encoding="utf-8")))
        self.assertEqual(found, [])
        self.assertEqual(G.primes(5), [2, 3, 5, 7, 11])
        self.assertEqual(G.nth_prime(1000), 7919)
        for v in range(-50, 50):
            self.assertEqual(G.unzig(G.zig(v)), v)
        self.assertEqual(sorted(G.zig(v) for v in range(-5, 5)), list(range(10)))


class Commands(unittest.TestCase):
    """cardmodel godel factor | similar | cofactor | decode: the structure's own commands (GODEL_TARGET §6, step 3)."""

    def test_factor_similar_cofactor_decode(self):
        import json
        from helpers import TempProject
        from cardmodel import cli_ext as X
        from cardmodel.engines.exprs import parse, to_text
        ctx = model_ctx()
        lib, _ = X._library(ctx)
        usable = []
        for k, t in lib.items():                        # definitions whose text parses back to their term
            try:
                if parse(to_text(t)) == t:
                    usable.append((k, t))
            except Exception:  # noqa: BLE001
                pass
        proj = TempProject()
        try:
            if usable[:2]:
                expr = " + ".join(f"({to_text(t)})" for _, t in usable[:2])
                r = proj.cli("godel", "factor", "--expr", expr)
                self.assertEqual(r.returncode, 0, r.stderr)
                for k, _ in usable[:2]:
                    self.assertIn(f"uses {k}", r.stdout)
                self.assertIn("Σ γ(instance): True", r.stdout)
            r = proj.cli("godel", "factor", "definition/alg__cubic_eval")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("Σ γ(instance): True", r.stdout)
            r = proj.cli("--json", "godel", "similar", "definition/alg__cubic_eval", "--limit", "3")
            self.assertEqual(r.returncode, 0, r.stderr)
            rows = json.loads(r.stdout)["definition/alg__cubic_eval"]
            self.assertEqual(len(rows), 3)
            self.assertTrue(all(0 < x["jaccard"] <= 1 and x["shared"] for x in rows), rows)
            r = proj.cli("godel", "cofactor", "definition/alg__cubic_eval", "--expr", "x*y+1")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("cofactor definition/alg__cubic_eval / x*y+1: {'op/ADD': 2, 'op/MUL': 2}", r.stdout)
            r = proj.cli("godel", "cofactor", "definition/alg__cubic_eval", "--expr", "x // y")
            self.assertIn("none: the part has", r.stdout)
            idx = G.index_of(ctx.store)
            n, names, _ = G.structural(["ADD", ["var", "p"], ["int", 3]], ctx.ops, idx, max_digits=None)
            r = proj.cli("godel", "decode", str(n), "--vars", ",".join(names))
            self.assertEqual(r.stdout.strip(), "(p + 3)", r.stderr)
            self.assertEqual(proj.cli("godel", "factor").returncode, 2)
        finally:
            proj.cleanup()

    def test_a_source_function_is_a_target(self):
        """FILE.py:FUNC lifts and canonicalizes like a definition card, and agrees with --expr on that term."""
        import json
        from helpers import TempProject
        from cardmodel.engines.exprs import to_text
        proj = TempProject()
        d = Path(tempfile.mkdtemp())
        try:
            src = d / "poly.py"
            src.write_text("def f(x, y):\n    return x * x * y + 3 * x * y + 1\n\n"
                           "def g(n):\n    s = 0\n    while n > 0:\n        s += n\n        n -= 1\n    return s\n",
                           encoding="utf-8")
            from cardmodel import cli_ext as X
            ctx = model_ctx()
            name, term, why = X._source_term(ctx, f"{src}:f")
            self.assertTrue(why.startswith("canonical term"), why)
            expr = to_text(term)
            a = proj.cli("--json", "godel", "similar", f"{src}:f", "--limit", "3")
            b = proj.cli("--json", "godel", "similar", "--expr", expr, "--limit", "3")
            self.assertEqual(a.returncode, 0, a.stderr)
            self.assertEqual(b.returncode, 0, b.stderr)
            self.assertEqual(json.loads(a.stdout)[f"{src}:f"], json.loads(b.stdout)[expr])
            a = proj.cli("--json", "godel", "cofactor", f"{src}:f", "--expr", "x*y+1")
            self.assertEqual(a.returncode, 0, a.stderr)
            r = json.loads(a.stdout)
            self.assertEqual(r["whole"], dict(G.term_content(term, ctx.ops)))
            self.assertIsNotNone(r["cofactor"])
            r = proj.cli("godel", "similar", f"{src}:g")
            self.assertEqual(r.returncode, 1, r.stderr)
            self.assertIn("no closed term", r.stderr)
            r = proj.cli("godel", "similar", f"{src}:nope")
            self.assertIn("no function 'nope'", r.stderr)
        finally:
            proj.cleanup()
            shutil.rmtree(d, ignore_errors=True)


def _leaves(t):
    stack = [t]
    while stack:
        x = stack.pop()
        if isinstance(x, list) and x:
            if x[0] in G.LEAVES:
                yield x
            else:
                stack.extend(x[1:])


def _subterms(t):
    stack = [t]
    while stack:
        x = stack.pop()
        if isinstance(x, list) and x and x[0] not in G.LEAVES:
            yield x
            stack.extend(x[1:])


if __name__ == "__main__":
    unittest.main()
