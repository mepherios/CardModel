"""Arithmetized execution (Gödel method W-12, Cap-11): the instruction terms as polynomial constraints over a prime
field agree with the terms on every input; Schwartz-Zippel holds over F_p and fails over Z/2^w."""
import random
import unittest

from helpers import SEED, model_ctx, seed_note

from cardmodel.machine import arith as A


class Constraints(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = model_ctx()
        cls.outs = A.outputs(cls.ctx)

    def test_gates_are_their_boolean_gates_on_bits(self):
        self.assertTrue(A.gate_lemma())

    def test_a_sample_of_terms_agrees_on_every_input(self):
        rng = random.Random(SEED)
        narrow = [o for o in self.outs if sum(A.width(n) for n in A.variables(o[2])) <= 12]
        for ins, name, term in rng.sample(narrow, 25):
            r = A.exhaustive(term)
            self.assertEqual(r["status"], "pass", (ins, name, r, seed_note(self)))
            c = A.Circuit()
            c.compile(term)
            for n in A.variables(term):
                c.input(n)
            w = c.eval_field({n: rng.randrange(1 << A.width(n)) for n in A.variables(term)})
            self.assertFalse(any(c.residuals(w)), (ins, name))                       # every constraint holds

    @unittest.skipIf(A.z3_exe() is None, "z3 is not installed")
    def test_z3_proves_agreement_and_catches_a_wrong_circuit(self):
        rng = random.Random(SEED)
        sample = [t for _, _, t in rng.sample(self.outs, 40)]
        self.assertEqual(set(A.smt(sample)), {"unsat"})
        # a wrong term (one constant off) against the right circuit: z3 finds an input where they differ
        ins, name, term = next(o for o in self.outs if o[1] == "A" and "BIT_AND" in str(o[2]))
        query = A.smt_query(term).replace("(_ bv255 40)", "(_ bv254 40)", 1)
        import subprocess
        out = subprocess.run([A.z3_exe(), "-in", "-smt2"], input=query, capture_output=True, text=True).stdout
        self.assertIn("sat", out.split()[0])
        self.assertNotIn("unsat", out.split()[0])


class SchwartzZippel(unittest.TestCase):
    def test_the_trace_identity_accepts_honest_and_rejects_tampered_traces(self):
        ctx = model_ctx()
        term = next(t for i, o, t in A.outputs(ctx) if i == "LR35902_CB_37" and o == "F")
        rng = random.Random(SEED)
        honest = A.trace(term, rng)
        self.assertTrue(honest["divisible"] and honest["accepted"], seed_note(self))
        bad = A.trace(term, rng, tamper=True)
        self.assertFalse(bad["divisible"] or bad["accepted"], seed_note(self))

    def test_the_bound_fails_modulo_2_to_the_w(self):
        r = A.mod2w_unsound(8, 4000, random.Random(SEED))
        self.assertGreater(r["accepted_mod_2w"], 1500)          # about half: 2^7·x vanishes for every even x
        self.assertEqual(r["accepted_mod_p"], 0)

    def test_ntt_round_trip(self):
        rng = random.Random(SEED)
        a = [rng.randrange(A.P) for _ in range(64)]
        self.assertEqual(A.ntt(A.ntt(a), invert=True), a)


if __name__ == "__main__":
    unittest.main()
