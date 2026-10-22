"""Goal floors (integrity, CM39): a goal made easier than the hardest target it was held to fails, unless its card
says from what, to what and why."""
import unittest

from helpers import model_ctx

from cardmodel.engines import integrity as I
from cardmodel.kernel.card import Card


class Floors(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = model_ctx()

    def test_no_goal_is_easier_than_its_floor(self):
        goals = self.ctx.store.cards("goal")
        floors = self.ctx.store.get("goal_floor/floors")["floors"]
        self.assertTrue(set(floors) & {g.name for g in goals})      # a new goal gets its floor at the next recording
        self.assertEqual(I.floor_problems(goals, self.ctx.store), [])

    def test_easier_means_a_lower_bar(self):
        self.assertTrue(I.easier(0.4, {"target": 0.5, "direction": "higher"}, "higher"))
        self.assertFalse(I.easier(0.6, {"target": 0.5, "direction": "higher"}, "higher"))
        self.assertTrue(I.easier(2, {"target": 0, "direction": "lower"}, "lower"))
        self.assertFalse(I.easier(0, {"target": 3, "direction": "lower"}, "lower"))
        self.assertTrue(I.easier(0.5, {"target": 0.5, "direction": "higher"}, "lower"))      # a changed direction

    def test_a_lowered_goal_fails_until_it_is_amended(self):
        g = self.ctx.store.get("goal/G_U9_algorithm_forms_proved")
        floor = self.ctx.store.get("goal_floor/floors")["floors"][g.name]["target"]
        lowered = Card({**g, "target": floor / 2}, registry="goal")
        problems = I.floor_problems([lowered], self.ctx.store)
        self.assertEqual(len(problems), 1)
        self.assertIn("easier than its floor", problems[0])
        amended = Card({**g, "target": floor / 2, "amendment": {"from": floor, "to": floor / 2,
                                                                  "reason": "the classes were overcounted"}},
                       registry="goal")
        self.assertEqual(I.floor_problems([amended], self.ctx.store), [])


if __name__ == "__main__":
    unittest.main()
