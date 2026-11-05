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
                self.assertLessEqual(abs(C.positional_bits(codes) - C.built_positional_bits(node, self.reader)), 1.0,
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


# -- the oracle: codes' own Def-27 token scheme before it called the core (kept only here) -------------------------
def _old_codes(reader, node, varnames):
    out = []

    def walk(n):
        (kind, *val), kids = n
        if kind == "atom":
            out.append(3 * reader.index[val[0]]["index"] + 1)
        elif kind == "int":
            out.append(3 * G.zig(val[0]) + 2)
        elif kind == "var":
            if val[0] not in varnames:
                varnames.append(val[0])
            out.append(3 * varnames.index(val[0]) + 3)
        for k in kids:
            walk(k)
    walk(node)
    return out


def _old_head_code(n, reader, varnames):
    (kind, *val), _ = n
    if kind == "tuple":
        return 0
    if kind == "atom":
        return 3 * reader.index[val[0]]["index"] + 1
    if kind == "int":
        return 3 * G.zig(val[0]) + 2
    return 3 * varnames.index(val[0]) + 3


def _old_built_positional_bits(codes):
    n = 1
    for i, c in enumerate(codes, start=1):
        n *= G.nth_prime(i) ** c
    return n.bit_length()


def _nodes(node):
    yield node
    for k in node[1]:
        yield from _nodes(k)


class SameAnswerAsTheOldScheme(unittest.TestCase):
    """codes now reads tokens through the core (G.tokens / G.structural); on every card ``godel sizes`` measures,
    the tokens, head codes and bit sizes are those of its old private scheme."""

    def test_every_measured_card(self):
        ctx = model_ctx()
        terms = []
        real = C.sizes

        def spy(term, reader, entries):
            terms.append((term, reader))
            return real(term, reader, entries)
        C.sizes = spy
        try:
            rows = C.measure(ctx)["rows"]
        finally:
            C.sizes = real
        self.assertGreater(len(rows), 0)
        checked = 0
        for term, reader in terms:
            try:
                node = reader.tree(term)
            except (KeyError, ValueError, OverflowError):
                continue
            if node is None:
                continue
            try:
                old = _old_codes(reader, node, [])
            except (KeyError, ValueError, OverflowError):
                with self.assertRaises((KeyError, ValueError, OverflowError)):
                    reader.codes(node, [])
                continue
            new = reader.codes(node, [])
            self.assertEqual(new, old, term)
            self.assertEqual(C.positional_bits(new), C.positional_bits(old))
            vs = C._prefix_vars(node, [])
            for n in _nodes(node):
                self.assertEqual(C._head_code(n, reader, vs), _old_head_code(n, reader, vs))
            if old and C.positional_bits(old) <= C.BUILD_BITS:
                self.assertEqual(C.built_positional_bits(node, reader), _old_built_positional_bits(old))
            checked += 1
        self.assertGreaterEqual(checked, len(rows))


if __name__ == "__main__":
    unittest.main()
