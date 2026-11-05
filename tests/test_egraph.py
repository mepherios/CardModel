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

    def test_fixed_width_and_binary32_subsorts(self):
        # FOUNDATIONS.md D1: u8 ... i32 are subsorts of int, f32 of float; a subsort's laws fire only on its terms
        ops = self.ctx.ops
        x, y = ["var", "x"], ["var", "y"]
        wrapped = ["WRAPU", ["ADD", ["WRAPU", x, ["int", 8]], y], ["int", 8]]
        got = E.canonical(wrapped, self.rules, self.costs, {"x": "int", "y": "int"}, ops)
        self.assertEqual(got["term"], ["WRAPU", ["ADD", x, y], ["int", 8]])
        masked = ["BIT_AND", x, ["int", 255]]
        self.assertEqual(E.canonical(masked, self.rules, self.costs, {"x": "u8"}, ops)["term"], x)   # a byte's mask
        self.assertNotEqual(E.canonical(masked, self.rules, self.costs, {"x": "int"}, ops)["term"], x)
        self.assertEqual(E.canonical(["WRAPU", x, ["int", 16]], self.rules, self.costs, {"x": "u8"}, ops)["term"], x)
        self.assertNotEqual(E.canonical(["WRAPU", x, ["int", 8]], self.rules, self.costs, {"x": "u16"}, ops)["term"], x)
        self.assertEqual(E.canonical(["F32", ["F32", y]], self.rules, self.costs, {"y": "float"}, ops)["term"],
                         ["F32", y])
        self.assertEqual(E.canonical(["F32", y], self.rules, self.costs, {"y": "f32"}, ops)["term"], y)
        # the sort of a WRAPU term is read from its card: an int term proved equal to it is a u8
        from cardmodel.engines import sorts as S
        self.assertEqual(S.term_sort(["WRAPU", x, ["int", 8]], {"x": "int"}, ops), "u8")
        self.assertEqual(S.term_sort(["WRAPS", x, ["int", 32]], {"x": "int"}, ops), "i32")
        self.assertTrue(S.leq("u8", "i16") and not S.leq("i8", "u16") and S.leq("f32", "float"))

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


class Identity(unittest.TestCase):
    """The equalities keyed by identity, and canonical forms memoized (docs/GODEL_AUDIT.md §4.2 (1, 2))."""

    @classmethod
    def setUpClass(cls):
        cls.ctx = model_ctx()
        cls.rules = E.rules_from_cards(cls.ctx.store)
        cls.costs = search.op_costs(cls.ctx.store)

    def test_rule_key_is_the_law_up_to_its_names(self):
        comm = (["ADD", "?a", "?b"], ["ADD", "?b", "?a"])
        self.assertEqual(E.rule_key(*comm), E.rule_key(["ADD", "?x", "?y"], ["ADD", "?y", "?x"]))
        self.assertNotEqual(E.rule_key(*comm), E.rule_key(["ADD", "?a", "?b"], ["ADD", "?a", "?b"]))
        ident = (["ADD", "?a", ["int", 0]], "?a")
        self.assertNotEqual(E.rule_key(*ident), E.rule_key(ident[1], ident[0]))     # the direction is the rule's
        self.assertEqual(E.rule_key(*comm), E.rule_key(comm[1], comm[0]))           # unless the law is its own reverse
        self.assertNotEqual(E.rule_key(*comm, {"?a": "int", "?b": "int"}), E.rule_key(*comm))   # so are the sorts
        self.assertEqual(E.rule_key(*comm, {"?a": "int", "?b": "int"}),
                         E.rule_key(["ADD", "?x", "?y"], ["ADD", "?y", "?x"], {"?x": "int", "?y": "int"}))

    def test_one_rule_per_law_and_the_same_canonical_terms(self):
        every = E.rules_from_cards(self.ctx.store, deduped=False)
        keys = [E.rule_key(r.lhs, r.rhs, r.sorts) for r in self.rules]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertLess(len(self.rules), len(every))            # the store states laws twice (rule and theorem)
        also = {o for r in self.rules for o in r.also}
        self.assertTrue(also, "no duplicate law found in the store")
        self.assertTrue(all(o.startswith(("rewrite_rule/", "theorem/")) for o in also))
        self.assertEqual({r.origin for r in every}, {r.origin for r in self.rules} | also)
        # the duplicates union what their representative unions: the canonical term is the same on every side
        sides = []
        for card in self.ctx.store.cards("theorem"):
            concl = card.get("concl")
            if not card.get("hyps") and isinstance(concl, list) and len(concl) == 3 and concl[0] == "eq":
                sides += [concl[1], concl[2]]
            if len(sides) >= 24:
                break
        for t in [*sides, parse("(a + 0) * 1 - b * 0"), parse("c + a * b")]:
            with_ = E.canonical(t, every, self.costs, None, self.ctx.ops, memo=False, max_iter=4, max_nodes=800)
            without = E.canonical(t, self.rules, self.costs, None, self.ctx.ops, memo=False, max_iter=4, max_nodes=800)
            self.assertEqual(with_["hash"], without["hash"], t)

    def test_canonical_is_memoized_by_its_input(self):
        E.clear_memo()
        t = parse("b * a + c")
        first = E.canonical(t, self.rules, self.costs, max_iter=4, max_nodes=800)
        again = E.canonical(parse("b * a + c"), self.rules, self.costs, max_iter=4, max_nodes=800)
        self.assertEqual(first, again)
        self.assertEqual((E.STATS["misses"], E.STATS["hits"]), (1, 1))
        again["term"][0] = "changed"                                  # the caller got a copy
        self.assertEqual(E.canonical(t, self.rules, self.costs, max_iter=4, max_nodes=800), first)
        # another budget, another sort of a variable, another rule list: computed again
        E.canonical(t, self.rules, self.costs, max_iter=3, max_nodes=800)
        E.canonical(t, self.rules, self.costs, {"a": "float"}, self.ctx.ops, max_iter=4, max_nodes=800)
        E.canonical(t, self.rules[:-1], self.costs, max_iter=4, max_nodes=800)
        self.assertEqual(E.STATS["misses"], 4)
        E.canonical(t, self.rules, self.costs, memo=False, max_iter=4, max_nodes=800)
        self.assertEqual(E.STATS["misses"], 4)                        # memo=False neither reads nor counts


if __name__ == "__main__":
    unittest.main()
