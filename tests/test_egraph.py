"""Equality saturation over the model's equalities: congruence, proofs, canonical terms (MATH_CORE phase 0)."""
import unittest

from helpers import SEED, model_ctx, seed_note

from cardmodel.engines import egraph as E
from cardmodel.engines import search
from cardmodel.engines.exprs import parse


class EGraph(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = model_ctx()
        cls.rules = E.rules_from_cards(cls.ctx.store)
        cls.costs = search.op_costs(cls.ctx.store)

    def test_congruence(self):
        g = E.EGraph()
        fa, fb = g.add(parse("abs(a) + 1")), g.add(parse("abs(b) + 1"))
        self.assertNotEqual(g.find(fa), g.find(fb))
        g.union(g.add(parse("a")), g.add(parse("b")))
        g.rebuild()
        self.assertEqual(g.find(fa), g.find(fb))

    def test_saturation_proves_and_canonicalizes(self):
        self.assertTrue(any(r.origin.startswith("theorem/") for r in self.rules))
        self.assertFalse(any(isinstance(r.lhs, str) for r in self.rules))
        r = E.equal(parse("max(a, b) + min(b, a)"), parse("a + b"), self.rules)
        self.assertTrue(r["equal"])
        self.assertEqual(E.witness(parse("max(a, b) + min(b, a)"), parse("a + b"), SEED)["status"], "witnessed",
                         seed_note(self))
        c1 = E.canonical(parse("b * a + c"), self.rules, self.costs)
        c2 = E.canonical(parse("c + a * b"), self.rules, self.costs)
        self.assertEqual(c1["hash"], c2["hash"])
        best = E.canonical(parse("max(x, min(x, y)) + abs(abs(z)) * 1"), self.rules, self.costs)
        self.assertEqual(best["cost"], 2.0)
        self.assertIn(best["term"], (parse("x + abs(z)"), parse("abs(z) + x")))

    def test_laws_fire_only_at_their_sorts(self):
        # FOUNDATIONS.md rule A3: associativity holds on int and fails on binary64, so the e-graph must not use it there
        self.assertNotEqual((0.1 + 0.2) + 0.3, 0.1 + (0.2 + 0.3))
        self.assertTrue(all(r.sorts for r in self.rules), "every law carries the sorts of its variables")
        left, right = parse("(x + y) + z"), parse("x + (y + z)")
        ops = self.ctx.ops
        self.assertTrue(E.equal(left, right, self.rules, {"x": "int", "y": "int", "z": "int"}, ops)["equal"])
        self.assertFalse(E.equal(left, right, self.rules, {"x": "float", "y": "float", "z": "float"}, ops)["equal"])
        lits = ["ADD", ["ADD", ["float", 0.1], ["float", 0.2]], ["float", 0.3]]
        relit = ["ADD", ["float", 0.1], ["ADD", ["float", 0.2], ["float", 0.3]]]
        self.assertFalse(E.equal(lits, relit, self.rules, ops=ops)["equal"])
        # the bounded search obeys the same rule
        got = search.optimize(parse("x * 1"), search.load_rules(self.ctx.store), self.costs, var_sorts={"x": "float"},
                              ops=ops)
        self.assertEqual(got["best_tree"], parse("x * 1"))
        got = search.optimize(parse("x * 1"), search.load_rules(self.ctx.store), self.costs, var_sorts={"x": "int"},
                              ops=ops)
        self.assertEqual(got["best_tree"], parse("x"))

    def test_not_shown_is_not_a_disproof(self):
        # no rule cancels (a + b) - b, so this stays unproved within the budget, and the witness still agrees
        r = E.equal(parse("(a + b) * c - c * b"), parse("a * c"), self.rules, max_iter=4, max_nodes=800)
        self.assertFalse(r["equal"])
        self.assertEqual(E.witness(parse("(a + b) * c - c * b"), parse("a * c"), SEED)["status"], "witnessed")
        self.assertEqual(E.witness(parse("a - b"), parse("b - a"), SEED)["status"], "refuted")

    def test_budget_is_respected(self):
        r = E.canonical(parse("((a + b) + (c + d)) * ((e + f) + (g + h))"), self.rules, self.costs, max_iter=50,
                        max_nodes=300)
        self.assertLessEqual(r["nodes"], 300 + 400)        # one iteration may overshoot by its own additions


if __name__ == "__main__":
    unittest.main()
