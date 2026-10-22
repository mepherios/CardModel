"""Gödel's 46 definitions as cards (Gödel method W-1): the forms agree on generated codes, the codes round-trip,
the direct forms equal the paper's bounded searches, and the proof checker accepts a known proof and rejects
corrupted ones."""
import unittest

from helpers import SEED, model_ctx, seed_note

from cardmodel.engines import formal as F
from cardmodel.engines import godel1931 as G


class Definitions(unittest.TestCase):
    def test_46_cards_with_their_forms(self):
        cards = model_ctx().store.cards("godel1931")
        self.assertEqual(sorted(c["number"] for c in cards), list(range(1, 47)))
        for c in cards:
            langs = {f["lang"] for f in c["forms"]}
            self.assertEqual(langs, {"python", "lean"}, c.qualified)
            self.assertEqual(c["primitive_recursive"], c["number"] <= 45)

    def test_codes_round_trip(self):
        r = G.round_trips(SEED)
        self.assertEqual(r["status"], "pass", (r, seed_note(self)))

    def test_direct_forms_equal_the_papers_searches(self):
        r = G.literal_agreement()
        self.assertEqual(r["status"], "pass", r)
        # the literal recursion: past the last prime factor prFactor gives 0, then starts again
        self.assertEqual([G.pr_factor(n, 12) for n in range(7)], [0, 2, 3, 0, 2, 3, 0])

    @unittest.skipIf(F.toolchain() is None, "no Lean toolchain for formal/lean-toolchain")
    def test_python_and_lean_forms_agree(self):
        if G.lean_exe() is None:
            ok, log = F.build()
            self.assertTrue(ok, log)
        r = G.agree(SEED, k=3)
        self.assertEqual(r["status"], "pass", (r.get("disagreements"), seed_note(self)))
        self.assertGreater(r["calls"], 150)


class ProofChecker(unittest.TestCase):
    def test_accepts_a_proof_and_rejects_corruptions(self):
        proof, target = G.p_implies_p()
        self.assertTrue(G.proof_for(proof, target))
        self.assertTrue(all(G.is_fm(x) for x in proof))
        corrupt = [[proof[0], proof[3], proof[2], proof[1], proof[4]],        # the steps out of order
                   [proof[0], proof[2], proof[3], proof[4]],                    # a premise dropped
                   proof[:4] + [G.disj(G.neg(G.el(G.X2, [G.Y1])), G.el(G.X2, [G.X1]))],
                   [G.imp(G.el(G.X2, [G.X1]), G.el(G.Y2, [G.X1]))] + proof[1:]]
        for c in corrupt:
            self.assertFalse(G.proof_for(c, target))
        self.assertFalse(G.proof_for(proof[:-1], target))
        self.assertEqual(G.provable(target, [proof]), True)
        self.assertIsNone(G.provable(target, corrupt))                 # Σ1: not found is not a refutation

    def test_axioms_of_P(self):
        self.assertTrue(all(G.peano_axiom(x) and G.is_fm(x) and G.is_axiom(x) for x in G.PA))
        self.assertTrue(G.set_axiom(G.SA) and G.is_fm(G.SA))
        self.assertAlmostEqual(G.lift_bits(1), G.type_lift(1, G.SA).bit_length(), delta=1)
        self.assertTrue(G.set_axiom(G.type_lift(1, G.SA)))
        p = G.el(G.X2, [G.X1])
        self.assertTrue(G.quantor2_axiom(G.imp(G.forall(G.var("y", 1), G.disj(p, G.el(G.Y2, [G.var("y", 1)]))),
                                               G.disj(p, G.forall(G.var("y", 1), G.el(G.Y2, [G.var("y", 1)]))))))
        # ∀x1 x2(x1) ⇒ x2(0): an instance of III.1
        self.assertTrue(G.quantor1_axiom(G.imp(G.forall(G.X1, p), G.el(G.X2, [G.ZERO]))))


if __name__ == "__main__":
    unittest.main()
