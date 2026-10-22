"""Identity and size of codes (Gödel method W-3): every size is predicted without building the integer, and the
predictions match the built codes."""
import math
import random
import unittest

from helpers import SEED, model_ctx, seed_note

from cardmodel.engines import codes as C
from cardmodel.engines import godel as G


class Sizes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = model_ctx()
        cls.entries = G.ledger(cls.ctx.store)
        cls.reader = C.Reader(cls.ctx.ops, {e["atom"]: e for e in cls.entries})
        cls.ops = [k for k in cls.ctx.ops if (cls.ctx.ops[k].card.get("ir") or {}).get("arity") in (1, 2)]

    def term(self, rng, depth):
        if depth == 0 or rng.random() < 0.3:
            return ["var", rng.choice("abc")] if rng.random() < 0.5 else ["int", rng.randint(-300, 300)]
        op = rng.choice(self.ops)
        return [op, *[self.term(rng, depth - 1) for _ in range(self.ctx.ops[op].card["ir"]["arity"])]]

    def test_the_handovers_example(self):
        ex = C.worst_case(10, 10 ** 6)
        self.assertAlmostEqual(ex["positional"] / 9.78e7, 1.0, delta=0.01)      # about 12 MB (Ph-2)
        self.assertAlmostEqual(ex["content"], 239, delta=2)                      # about 240 bits

    def test_formulas_predict_the_built_codes(self):
        rng = random.Random(SEED)
        for _ in range(60):
            t = self.term(rng, 4)
            node = self.reader.tree(t)
            codes = self.reader.codes(node, [])
            if C.positional_bits(codes) <= C.BUILD_BITS:
                self.assertLessEqual(abs(C.positional_bits(codes) - C.built_positional_bits(codes)), 1.0,
                                     seed_note(self))
            vec, _ = G.to_vector(G.term_content(t, self.ctx.ops), self.reader.index)
            self.assertLessEqual(abs(C.content_bits(vec, self.entries) - C.built_content_bits(vec, self.entries)), 1.0)
            bits, exact = C.tree_code_bits(node, self.reader, C._pair_cantor)
            if exact:
                self.assertEqual(C.tree_code_estimate(node, self.reader), bits, (t, seed_note(self)))

    def test_nesting_explodes_pairing_codes_but_not_positional_ones(self):
        t = ["var", "x"]
        rows = []
        for d in range(1, 13):
            t = ["NEG", t]
            node = self.reader.tree(t)
            rows.append((C.positional_bits(self.reader.codes(node, [])), C.tree_code_estimate(node, self.reader)))
        self.assertLess(rows[-1][0], 12 * rows[0][0] * math.log2(G.nth_prime(13)))   # about linear
        self.assertGreater(rows[-1][1], 2 ** 11)                                          # doubles per level (Ph-3)

    def test_base_k_round_trip(self):
        for text in ("(52 (64 v0 c3) c-2)", "v0", "c-12345"):
            self.assertEqual(C.from_base_k(C.to_base_k(text)), text)

    def test_the_store(self):
        sm = C.measure(self.ctx)["summary"]
        self.assertEqual(sm["positional_over_content"], 1.0)
        self.assertLessEqual(sm["formula_vs_built"]["positional"]["max_bits_off"], 1.0)
        self.assertLessEqual(sm["formula_vs_built"]["content"]["max_bits_off"], 1.0)
        self.assertEqual(sm["model_cantor"]["p95_rel_error"], 0.0)


if __name__ == "__main__":
    unittest.main()
