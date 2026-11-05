"""Laws that carry (CM25): discovered from templates, refuted or witnessed, proved, promoted to the optimizer."""
import unittest

from unittest import mock

from helpers import SEED, TempProject, model_ctx, seed_note

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

    def test_settled_laws_are_taken_from_the_store(self):
        print(f"\n  candidates: {self.rep['candidates']}, settled in the store already: {self.rep['known']}")
        self.assertGreater(self.rep["known"], 0, seed_note(self))
        comm = self.by["law_comm_ADD"]
        self.assertTrue(comm["origin"]["known"].startswith("theorem/"), comm["origin"])
        self.assertIn(comm["status"], ("proved", "witnessed"))

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


class KnownLaws(unittest.TestCase):
    """A candidate whose statement the store already settles (the same theorem up to its names) takes that card's
    status, evidence and proofs and is not witnessed or sent to Lean again (docs/GODEL_AUDIT.md step 2)."""

    def test_a_settled_statement_is_not_witnessed_or_proved_again(self):
        v = lambda n: ["var", n]  # noqa: E731
        stored = {"name": "my_comm", "category": "theorem", "semantics": "card", "status": "proved", "hyps": [],
                  "vars": [{"name": "x", "type": "int"}, {"name": "y", "type": "int"}],
                  "concl": ["eq", ["ADD", v("x"), v("y")], ["ADD", v("y"), v("x")]],
                  "evidence": {"status": "witnessed", "seed": 7, "checks": 99},
                  "proofs": [{"method": "lean:omega", "ok": True, "lean": "theorem my_comm … := by omega"}]}
        proj = TempProject()
        try:
            ctx = proj.ctx()
            ctx.store.save(stored, category="theorem")
            ctx.store.invalidate()
            cands = {c["name"]: c for c in laws.candidates(ctx.ops)}
            two = [cands["law_comm_ADD"], cands["law_idem_MIN"]]
            mine = {T.identity(stored): [ctx.store.get("theorem/my_comm")]}      # the store's other theorems aside
            with mock.patch.object(laws, "candidates", return_value=two), \
                    mock.patch.object(T, "by_identity", return_value=mine), \
                    mock.patch.object(T, "witness", wraps=T.witness) as witness:
                rep = laws.discover(ctx, seed=SEED, lean=False)
                self.assertEqual(rep["known"], 1)
                by = {c["name"]: c for c in rep["laws"]}
                comm = by["law_comm_ADD"]
                self.assertEqual(comm["origin"]["known"], "theorem/my_comm")
                self.assertEqual((comm["status"], comm["proofs"], comm["evidence"]),
                                 ("proved", stored["proofs"], stored["evidence"]))
                self.assertEqual(comm["origin"]["template"], "commutative")          # its own name and origin
                self.assertEqual(by["law_idem_MIN"]["status"], "witnessed")
                self.assertNotIn("known", by["law_idem_MIN"]["origin"])
                self.assertEqual([c["name"] for c in rep["laws"]], ["law_comm_ADD", "law_idem_MIN"])
                self.assertEqual([c["name"] for c, *_ in [a.args for a in witness.call_args_list]],
                                 ["law_idem_MIN"], "only the new candidate is witnessed")
                rep2 = laws.discover(ctx, seed=SEED, lean=False, known=False)
                self.assertEqual(rep2["known"], 0)
                again = {c["name"]: c for c in rep2["laws"]}["law_comm_ADD"]
                self.assertEqual(again["status"], "witnessed")
                self.assertNotIn("known", again["origin"])
        finally:
            proj.cleanup()


if __name__ == "__main__":
    unittest.main()
