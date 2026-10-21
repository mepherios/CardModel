"""Lean proofs as cards (CM23): a reading is kept only if the kernel accepts it as the original; Lean's
semantics (truncated Nat subtraction, Euclidean division, x / 0 = 0, leaf coercions) survive the import."""
import unittest

from helpers import SEED, model_ctx, seed_note

from cardmodel.emit import lean as LE
from cardmodel.emit import lean_import as LI

SRC = """
namespace CMTest
theorem cast_sub (n m : Nat) : ((n - m : Nat) : Int) ≥ 0 := by omega
theorem leaf_coercion (n m : Nat) : (n - m : Int) = (n : Int) - (m : Int) := by omega
theorem nat_sub_le (n m : Nat) : n - m ≤ n := Nat.sub_le n m
theorem ediv_zero' (a : Int) : a / 0 = 0 := Int.ediv_zero a
theorem emod_zero' (a : Int) : a % 0 = a := Int.emod_zero a
theorem euclid (a b : Int) (h : b ≠ 0) : 0 ≤ a % b := Int.emod_nonneg a h
theorem right_comm (a b c : Int) : a + b + c = a + c + b := by omega
theorem min_self' (n : Nat) : min n n = n := Nat.min_self n
theorem implicit_hyp {a b : Nat} (h : a ≤ b) : a - b = 0 := Nat.sub_eq_zero_of_le h
end CMTest
"""


@unittest.skipIf(LE.lean_exe() is None, "no Lean toolchain")
class LeanImportTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = model_ctx()
        cls.rep = LI.import_source(cls.ctx, SRC, {"kind": "lean_file", "file": "Test.lean"}, seed=SEED)
        cls.by = {c["name"]: c for c in cls.rep["cards"]}

    def test_faithful_and_witnessed(self):
        r = self.rep
        self.assertEqual(r["declarations"], 9)
        self.assertEqual(r["faithful"], 9, r.get("unfaithful"))
        self.assertEqual(r["witness_refuted"], [], seed_note(self))
        for c in r["cards"]:
            self.assertEqual(c["status"], "proved")
            self.assertTrue(any(p["method"] == "lean:original" for p in c["proofs"]))

    def test_lean_semantics_survive(self):
        lc = self.by["lean.CMTest.leaf_coercion"]["concl"]
        self.assertEqual(lc[1][0], "SUB")                                 # Int subtraction of casts, not Nat
        cs = self.by["lean.CMTest.cast_sub"]["concl"]
        self.assertEqual(cs[1][0], "LEAN_CAST")
        self.assertEqual(cs[1][1][0], "LEAN_NSUB")                        # truncated, then cast
        ops = LI.lean_ops(self.ctx.ops)
        self.assertEqual(ops["LEAN_DIV"].fn(7, -2), -3)
        self.assertEqual(ops["LEAN_MOD"].fn(-7, 2), 1)
        self.assertEqual(ops["LEAN_DIV"].fn(5, 0), 0)

    def test_misreading_is_rejected(self):
        bad = dict(self.by["lean.CMTest.cast_sub"])
        concl = list(bad["concl"])
        concl[1] = ["SUB", ["var", "n"], ["var", "m"]]                    # read Nat subtraction as Int: wrong
        bad["concl"] = concl
        bad["name"] = "lean.CMTest.cast_sub_misread"
        verdict = LI.faithful([bad], LE.lean_exe(), prelude=SRC)
        self.assertNotEqual(verdict[bad["name"]], "ok")

    def test_reproved_by_the_card_model(self):
        self.assertIn("omega", self.by["lean.CMTest.right_comm"].get("reproved_by", []))
        chain = [p for p in self.by["lean.CMTest.right_comm"]["proofs"] if p["method"] == "card_chain"]
        self.assertTrue(chain, "the right-commutativity lemma should be re-derived from the rule cards")
        self.assertIn("commutative_add", chain[0]["rules"])


if __name__ == "__main__":
    unittest.main()
