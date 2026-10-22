"""The difficulty census (Gödel method W-15): every method carries the rank of what it decides, and only decidable
questions are promised."""
import unittest

from helpers import model_ctx

from cardmodel.engines import difficulty as D


class Census(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = model_ctx()

    def test_every_method_carries_a_rank(self):
        r = D.check(self.ctx)
        self.assertEqual(r["problems"], [])
        for m in self.ctx.store.cards("method"):
            rk = m.get("rank") or {}
            self.assertIn(rk.get("decides"), D.RANKS + ("none",), m.qualified)
            self.assertIn(rk.get("general_rank"), D.RANKS, m.qualified)
            self.assertTrue(rk.get("cites"), m.qualified)

    def test_only_decidable_questions_are_promised(self):
        qs = {q.name: q for q in self.ctx.store.cards("question")}
        for q in qs.values():
            if q.get("promise") == "answered":
                self.assertEqual(q.get("rank"), D.FULL, q.qualified)
        # the classic open questions sit where the theorems put them
        expect = {"provable": "Σ1", "halts": "Σ1", "programs_equal": "Π1", "consistent": "Π1", "total": "Π2",
                  "true": "beyond"}
        self.assertEqual({k: qs[k].get("rank") for k in expect}, expect)
        self.assertTrue(all(qs[k].get("promise") == "open" for k in expect))

    def test_a_question_promised_beyond_its_rank_fails(self):
        from cardmodel.kernel.card import Card
        bad = Card({"name": "x", "category": "question", "rank": "Π1", "promise": "answered", "cites": ["Ph-15"]},
                   registry="question")

        class Store:
            def __init__(self, inner):
                self.inner = inner

            def cards(self, reg):
                return self.inner.cards(reg) + ([bad] if reg == "question" else [])

        class Ctx:
            store = Store(self.ctx.store)
        self.assertTrue(any("promised as answered" in p for p in D.check(Ctx())["problems"]))


if __name__ == "__main__":
    unittest.main()
