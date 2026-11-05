"""Admissible numberings (Gödel method W-5, GM-4): every Gödel set states its numbering and passes its conditions,
and a deviant numbering fails them."""
import random
import unittest

from helpers import SEED, model_ctx, seed_note

from cardmodel.engines import numbering as N


class Sets(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = model_ctx()

    def run_set(self, name):
        r = N.check_set(self.ctx, name, seed=SEED)
        bad = {k: v for k, v in r["conditions"].items() if v["status"] != "pass"}
        self.assertEqual(bad, {}, seed_note(self))
        self.assertTrue(all(v["checked"] for v in r["conditions"].values()))
        card = self.ctx.store.get(f"godel_set/{name}")
        self.assertEqual(card["numbering"]["conditions"], [c[0] for c in N.CONDITIONS])

    def test_B0(self):
        self.run_set("B0")

    def test_computation(self):
        self.run_set("computation")

    def test_machines(self):
        self.run_set("machines")

    def test_every_set_states_its_numbering(self):
        r = N.check(self.ctx, seed=SEED)
        self.assertEqual(r["problems"], [], seed_note(self))
        self.assertEqual(set(r["sets"]), {c.name for c in self.ctx.store.cards("godel_set")})


class Deviant(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = model_ctx()

    def with_card(self, name, change):
        """The context with one godel_set card changed in memory."""
        from cardmodel.kernel.card import Card
        real = self.ctx.store

        class Store:
            def get(self, q):
                c = real.get(q)
                if q == f"godel_set/{name}":
                    c = Card(change(dict(c)), registry="godel_set")
                return c

            def __getattr__(self, attr):
                return getattr(real, attr)

        class Ctx:
            store, ops = Store(), self.ctx.ops
        return Ctx()

    def test_a_deviant_provability_predicate_fails(self):
        def feferman(c):
            c["numbering"] = {**c["numbering"], "provability": {"form": "exists_proof_with_consistency_below",
                                                                 "relation": "method/lean_kernel"}}
            return c
        r = N.check_set(self.with_card("B0", feferman), "B0", seed=SEED)
        self.assertEqual(r["conditions"]["natural_provability"]["status"], "fail")

    def test_effects_without_fixed_arities_cannot_be_decoded(self):
        def no_arities(c):
            c.pop("arities", None)
            return c
        r = N.check_set(self.with_card("machines", no_arities), "machines", seed=SEED, samples=10)
        self.assertEqual(r["status"], "fail")

    def test_codes_reject_what_is_not_a_code(self):
        nb = N.Numbering(self.ctx, "B0")
        rng = random.Random(SEED)
        t = N.canonical(nb.generate(rng))
        n = nb.encode(t)
        self.assertTrue(nb.is_code(n))
        self.assertFalse(nb.is_code(n * 101 ** 3 if n % 101 else n * 103))   # a factor no position has
        self.assertFalse(nb.is_code(1))
        self.assertFalse(nb.is_code(3))                                       # skips the prime 2


if __name__ == "__main__":
    unittest.main()


def _tokens_before_core(nb, t, varnames):
    """Numbering.tokens as it was before it called godel.tokens: the reference the core call must reproduce."""
    from cardmodel.engines import godel as G
    if isinstance(t, list) and t and t[0] == "var":
        if t[1] not in varnames:
            varnames.append(t[1])
        return [3 * varnames.index(t[1]) + 3]
    if isinstance(t, list) and t and t[0] == "int":
        return [3 * G.zig(int(t[1])) + 2]
    if isinstance(t, list) and t:
        atom = t[0] if "/" in str(t[0]) else f"op/{t[0]}"
        if atom not in nb.by_atom or len(t) - 1 != nb.arity.get(atom, 0):
            raise ValueError(atom)
        out = [3 * nb.by_atom[atom]["index"] + 1]
        for a in t[1:]:
            out += _tokens_before_core(nb, a, varnames)
        return out
    raise ValueError(t)


class TokensAreTheCore(unittest.TestCase):
    def test_same_tokens_on_every_sets_objects(self):
        ctx = model_ctx()
        rng = random.Random(SEED)
        n = 0
        for c in ctx.store.cards("godel_set"):
            nb = N.Numbering(ctx, c.name)
            for _ in range(60):
                try:
                    t = nb.generate(rng)
                except ValueError:
                    continue
                v_old, v_new = [], []
                self.assertEqual(nb.tokens(t, v_new), _tokens_before_core(nb, t, v_old), seed_note(self))
                self.assertEqual(v_new, v_old)
                n += 1
            for bad in (["no/such_atom"], [next(iter(nb.by_atom)), *[["int", 0]] * 9]):
                with self.assertRaises(ValueError):
                    _tokens_before_core(nb, bad, [])
                with self.assertRaises(ValueError):
                    nb.tokens(bad, [])
        self.assertGreater(n, 0)
