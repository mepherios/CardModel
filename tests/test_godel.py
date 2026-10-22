"""The expanding Gödel model's foundation (CM43): an append-only prime ledger, content and structure."""
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
        idx = {"x": {"prime": 2}, "y": {"prime": 3}, "z": {"prime": 5}}
        self.assertEqual(G.number(a, idx), (2 * 2 * 3, []))
        self.assertEqual(G.number(Counter({"q": 1}), idx), (None, ["q"]))
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
            n, varnames = G.structural(t, ctx.ops, idx)
            self.assertEqual(G.decode(n, ctx.ops, entries, varnames), t, seed_note(self))


if __name__ == "__main__":
    unittest.main()
