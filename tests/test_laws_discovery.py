"""Laws that carry (CM25): discovered from templates, refuted or witnessed, proved, promoted to the optimizer."""
import unittest

from helpers import SEED, model_ctx, seed_note

from cardmodel.engines import laws, search
from cardmodel.engines import theorems as T
from cardmodel.engines.exprs import parse


class LawsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = model_ctx()
        cls.rep = laws.discover(cls.ctx, seed=SEED, lean=False)
        cls.by = {c["name"]: c for c in cls.rep["laws"]}

    def test_known_laws_hold_and_look_alikes_fall(self):
        for name in ("law_comm_ADD", "law_assoc_MUL", "law_distrib_left_MUL_ADD", "law_absorption_MAX_MIN",
                     "law_dual_NEG_MAX_MIN", "law_trans_CMP_LT", "law_demorgan_AND", "law_idem_ABS"):
            self.assertIn(name, self.by, seed_note(self))
        for name in ("law_comm_SUB", "law_distrib_left_MOD_MAX", "law_assoc_SUB", "law_hom_NEG_SHIFT_LEFT"):
            self.assertNotIn(name, self.by, seed_note(self))
        cand = {c["name"]: c for c in laws.candidates(self.ctx.ops)}
        w = T.witness(cand["law_distrib_left_MOD_MAX"], self.ctx.ops, seed=SEED)
        self.assertEqual(w["status"], "refuted")

    def test_simplifying_laws_become_rules(self):
        rules = {r["name"]: r for r in self.rep["rules"]}
        r = rules["rule_idem_MIN"]
        self.assertEqual((r["lhs"], r["rhs"]), ("min(a, a)", "a"))
        self.assertIn("theorem/law_idem_MIN", r["depends_on"])
        self.assertNotIn("rule_comm_ADD", rules)                    # not simplifying: stays a theorem only
        loaded = [search.Rule(n, parse(c["lhs"], c["vars"]), parse(c["rhs"], c["vars"]), n)
                  for n, c in rules.items() if not c.get("condition")]
        best = search.optimize(parse("max(x, min(x, y)) + abs(abs(z)) * 1"), loaded, {"MIN": 2, "MAX": 2, "ABS": 2},
                               max_depth=4)
        self.assertEqual(best["best_tree"], parse("x + abs(z)"))


if __name__ == "__main__":
    unittest.main()
