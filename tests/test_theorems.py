"""Crystallised knowledge (CM23): a theorem's status follows its evidence and nothing else."""
import unittest

from helpers import SEED, model_ctx, seed_note

from cardmodel.emit import lean as LE
from cardmodel.engines import theorems as T
from cardmodel.lang.compile import compile_source


def thm(ctx, src):
    return compile_source(src, ctx.ops, ctx.store, name="t").theorems[0]


class TheoremTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = model_ctx()

    def test_status_follows_evidence(self):
        ctx = self.ctx
        false = thm(ctx, "theorem bad(a: Int, b: Int): a % (b * b + 1) == a % (b + 1)")
        w = T.witness(false, ctx.ops, seed=SEED)
        self.assertEqual(w["status"], "refuted", seed_note(self))
        self.assertLessEqual(max(abs(v) for v in w["counterexample"].values()), 64)   # the small phase finds it
        settled = T.settle(false, w, {"status": "proved", "tactic": "omega", "lean": "x"}, None)
        self.assertEqual(settled["status"], "refuted")                                  # a proof never overrides
        pinned = thm(ctx, "theorem pin(a: Int) requires a >= 0, a <= 0: a * a == 0")
        self.assertEqual(T.witness(pinned, ctx.ops, seed=SEED)["status"], "vacuous")
        rare = thm(ctx, "theorem rare(a: Int) requires a == 123456789: a > 0")
        self.assertEqual(T.witness(rare, ctx.ops, seed=SEED)["status"], "vacuous")
        good = thm(ctx, "theorem ok(a: Int, b: Int): max(a, b) >= a")
        w = T.witness(good, ctx.ops, seed=SEED)
        self.assertEqual(w["status"], "witnessed")
        self.assertEqual(T.settle(good, w, None, None)["status"], "witnessed")
        undefined = thm(ctx, "theorem div(a: Int, b: Int): (a // b) * b + a % b == a")
        r = T.witness(undefined, ctx.ops, seed=SEED)
        self.assertEqual(r["status"], "refuted")
        self.assertIn("undefined", r["reason"])

    def test_nat_is_rendered_faithfully(self):
        card = thm(self.ctx, "theorem sub(n: Nat, m: Nat): n - m + m >= n")
        text = T.lean_theorem(card, self.ctx.store, self.ctx.ops, "omega")
        self.assertIn("(n m : Int)", text.replace("(n : Int) (m : Int)", "(n m : Int)"))
        self.assertIn("0 ≤ n", text)                     # Nat = an Int >= 0, so `-` keeps integer meaning

    @unittest.skipIf(LE.lean_exe() is None, "no Lean toolchain")
    def test_lean_proves_and_rejects(self):
        good = thm(self.ctx, "theorem g(a: Int, b: Int): a + b == b + a")
        bad = thm(self.ctx, "theorem b(a: Int, b: Int): a - b == b - a")
        res = T.prove([good, bad], self.ctx.store, self.ctx.ops, tactics=("omega", "grind"))["results"]
        self.assertEqual(res[good["name"]]["status"], "proved")
        self.assertEqual(res[bad["name"]]["status"], "unproved")


if __name__ == "__main__":
    unittest.main()
