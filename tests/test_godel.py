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
        ctx = model_ctx()
        r = G.check(ctx)
        self.assertEqual(r["problems"], [])
        self.assertEqual(r["coverage"], 1.0, r["missing"])
        sq, _ = G.card_content(ctx, ctx.store.get("algorithm/sum_of_squares"))
        self.assertIn("op/MUL", sq)
        th, why = G.card_content(ctx, ctx.store.cards("theorem")[0])
        self.assertGreaterEqual(th["logic/forall"], 1, why)


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
        ctx = model_ctx()
        idx, entries = G.index_of(ctx.store), G.ledger(ctx.store)
        rng = random.Random(SEED)
        ops = [k for k in ctx.ops if (ctx.ops[k].card.get("ir") or {}).get("arity") in (1, 2)]

        def term(depth):
            if depth == 0 or rng.random() < 0.3:
                return ["var", rng.choice("abc")] if rng.random() < 0.5 else ["int", rng.randint(-9, 9)]
            op = rng.choice(ops)
            return [op, *[term(depth - 1) for _ in range(ctx.ops[op].card["ir"]["arity"])]]
        for _ in range(40):
            t = term(3)
            n, varnames, digits = G.structural(t, ctx.ops, idx, max_digits=None)
            self.assertEqual(G.decode(n, ctx.ops, entries, varnames), t, seed_note(self))
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


if __name__ == "__main__":
    unittest.main()
