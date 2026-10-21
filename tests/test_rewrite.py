"""Rewrite engine (cheapest form, suggestions, cost vectors) and rewrite search (proofs, optimisation)."""
import unittest

from helpers import model_ctx

from cardmodel.engines import rewrite, search
from cardmodel.engines.exprs import parse, to_text


class Cheapest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.st = model_ctx().store

    def test_cheapest_respects_domain_and_availability(self):
        st = self.st
        mod = st.get("op/MOD")
        self.assertEqual(rewrite.cheapest(st, mod, "int").name, "pow2_bit")       # cost 1 beats native 4
        self.assertIsNone(rewrite.cheapest(st, st.get("op/MODINV"), "int"))       # coprime-only forms don't serve int
        self.assertEqual(rewrite.cheapest(st, st.get("op/MODINV"), "coprime_mod").name, "xgcd")
        add = st.get("op/ADD")
        self.assertEqual(rewrite.cheapest(st, add, "u32").name, "native")         # tie: declaration order
        self.assertNotEqual(rewrite.cheapest(st, add).name, "rust_hint")          # hints only when asked for
        self.assertEqual(rewrite.cheapest(st, add, lang="rust", available_only=False).name, "rust_hint")
        rust_ok = rewrite.available(st, next(f for f in rewrite.forms_of(add) if f.name == "rust_hint"))[0]
        self.assertEqual(rewrite.cheapest(st, add, lang="rust") is not None, rust_ok)   # only if rustc works here
        ec = st.get("op/EC_ADD")                                                  # sage forms: documentation only
        self.assertIsNone(rewrite.cheapest(st, ec))
        self.assertIsNotNone(rewrite.cheapest(st, ec, runnable_only=False, available_only=False))
        fake = {"name": "X", "forms": [{"name": "fast", "cost": 0.1, "code": "x", "probe": {"kind": "never"}},
                                       {"name": "slow", "cost": 9.0, "code": "lambda: 1"}]}
        self.assertEqual(rewrite.cheapest(st, fake).name, "slow")                 # unavailable form skipped
        self.assertEqual(rewrite.cheapest(st, fake, available_only=False).name, "fast")

    def test_suggest_and_all(self):
        st = self.st
        s = rewrite.suggest_rewrite(st, st.get("op/SQUARE"), "native_mul")
        self.assertEqual((s["to"], s["speedup"]), ("half_cost", 1.2))
        self.assertIsNone(rewrite.suggest_rewrite(st, st.get("op/MOD"), "pow2_bit", "int"))
        cards = {r["card"] for r in rewrite.all_rewrites(st, "int")}
        self.assertIn("MOD", cards)

    def test_rank_and_pareto_on_cipher_suites(self):
        st = self.st
        suites = st.cards("cipher_suite")
        self.assertEqual(len(suites), 3)
        small = rewrite.rank(st, suites, {"sig_bytes": 1.0, "kem_pk_bytes": 1.0})
        self.assertEqual(small[0][1].name, "c25519")
        pq = rewrite.rank(st, suites, {"post_quantum": 1.0})
        self.assertEqual(pq[0][1].name, "hybrid_pq")
        front = {c.name for c in rewrite.pareto(st, suites, ["kem_pk_bytes", "post_quantum"])}
        self.assertEqual(front, {"c25519", "hybrid_pq"})                          # p256 is dominated on these
        tie = {c.name for c in rewrite.pareto(st, suites, ["sig_bytes", "post_quantum"])}
        self.assertEqual(tie, {"c25519", "p256", "hybrid_pq"})                    # equal is not dominated


class Search(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        st = model_ctx().store
        cls.rules = search.load_rules(st)
        cls.costs = search.op_costs(st)

    def test_proves_hub_identities(self):
        for lhs, rhs in [("(x + y) ** 2", "x ** 2 + 2 * (x * y) + y ** 2"), ("x ** 2 - y ** 2", "(x + y) * (x - y)"),
                         ("(a + b) * c", "c * b + c * a")]:
            p = search.prove(lhs, rhs, self.rules, max_depth=5)
            self.assertIsNotNone(p, f"{lhs} = {rhs}")
            self.assertEqual(to_text(p["steps"][0][1]), to_text(parse(lhs)))
            self.assertEqual(to_text(p["steps"][-1][1]), to_text(parse(rhs)))

    def test_false_identity_not_proved(self):
        self.assertIsNone(search.prove("x ** 2 - y ** 2", "x - y", self.rules, max_depth=4, max_nodes=5000))

    def test_optimize_finds_cheaper(self):
        r = search.optimize("x * 2 + 0", self.rules, self.costs)
        self.assertEqual(r["best"], "(x << 1)")
        self.assertLess(r["best_cost"], r["input_cost"])
        self.assertEqual(search.optimize("q", self.rules, self.costs)["best"], "q")

    def test_budget_is_respected(self):
        r = search.optimize("(a + b) * (c + d) * (e + f)", self.rules, self.costs, max_depth=6, max_nodes=300)
        self.assertLessEqual(r["nodes"], 300 + 50)


if __name__ == "__main__":
    unittest.main()
