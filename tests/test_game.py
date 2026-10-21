"""The Vector Counter System (CM28, CM29): counters decided by the card-language kernel, design laws computed
on exact equilibria (strings included: chain cards end and every link can be answered), the duel tree solved by
backward induction, AIs measured, and a world where effects carry and can be explained."""
import unittest

from helpers import SEED, model_ctx, seed_note

from cardmodel.game import ai
from cardmodel.game import analysis as A
from cardmodel.game import world as W
from cardmodel.game.combat import Combat
from cardmodel.game.tree import Tree


class CombatTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = model_ctx()
        cls.g = Combat(cls.ctx)
        cls.s = cls.g.start()

    def outcome(self, a, b):
        s2, ev = self.g.resolve(self.s, a, b)
        return s2, " ".join(ev.text)

    def test_kernel_comes_from_the_card_language(self):
        k = self.g.k
        self.assertEqual([k["align"](2, x) for x in (2, 3, 4, 6, 8)], [2, 1, 0, -2, 0])
        self.assertEqual(k["outcome"](2, 2), 4)
        self.assertEqual(k["outcome"](-1, 2), 1)

    def test_counters_are_vector_reads(self):
        _, t = self.outcome("overhead", "guard_high")
        self.assertIn("redirect", t)                       # right vector, readable timing
        _, t = self.outcome("overhead", "guard_left")
        self.assertIn("block", t)                          # wrong vector: only a block
        _, t = self.outcome("feint_overhead", "guard_high")
        self.assertIn("block", t)                          # the feint changes the vector after the tell
        _, t = self.outcome("feint_overhead", "roll")
        self.assertIn("lands", t)                          # and the timing: the roll was timed to the tell
        _, t = self.outcome("thrust", "step_in")
        self.assertIn("catches", t)
        _, t = self.outcome("grab", "guard_high")
        self.assertIn("ignores guards", t)
        s2, t = self.outcome("sweep", "jump")
        self.assertIn("slips", t)
        self.assertGreater(s2.a.posture, 0)                # the jump lands on the sweeper

    def test_momentum_carries(self):
        s2, _ = self.g.resolve(self.s, "overhead", "guard_high")
        self.assertEqual(s2.a.stance, "recoil")
        self.assertGreater(s2.b.bank, 0)                   # the redirect banked the attacker's momentum
        self.assertLess(s2.advantage, 0)
        s3, ev = self.g.resolve(s2, "guard_right", "overhead")
        self.assertIn("banked", " ".join(ev.text))

    def test_broken_posture_takes_a_critical(self):
        from dataclasses import replace
        st = replace(self.s, a=replace(self.s.a, stance="broken"))
        self.assertEqual(self.g.options(st, "a"), ["endure"])
        s2, ev = self.g.resolve(st, "endure", "slash_right")
        self.assertIn("critical", " ".join(ev.text))
        self.assertEqual(s2.a.stance, "neutral")


class DesignTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = model_ctx()
        cls.g = Combat(cls.ctx)

    def test_exact_equilibrium_has_a_certificate(self):
        rows, cols, M = A.matrix(self.g, self.g.start())
        sol = A.solve(M)
        self.assertTrue(sol["certificate"]["ok"])
        self.assertEqual(sol["value"], 0)                  # symmetric fighters: exactly zero
        self.assertEqual(A.solve([[1, -1], [-1, 1]])["value"], 0)
        self.assertEqual(A.solve([[3, 0], [0, 1]])["value"], A.solve([[3, 0], [0, 1]])["value"])

    def test_design_laws_hold_and_catch_imbalance(self):
        r = A.check(self.g)
        self.assertEqual(r["passed"], r["total"], {n: l for n, l in r["laws"].items() if not l["ok"]})
        g2 = Combat(self.ctx)
        g2.moves["jab"] = {**g2.moves["jab"], "damage": 60, "posture": 40}
        r2 = A.check(g2)
        self.assertLess(r2["passed"], r2["total"])         # a planted imbalance breaks a law
        sv = A.sensitivity(Combat(self.ctx))
        self.assertTrue(sv["top"] and sv["top"][0]["exploitability"] > 0)

    def test_reader_exploits_a_habit(self):
        import random
        reader = ai.ReaderAgent(epsilon=0.0)
        for _ in range(10):
            reader.observe(self.g, "guard_high", "overhead")       # the opponent keeps swinging overheads
        self.assertIn(("dir:2", 7.07), [(k, round(v, 2)) for k, v in reader.focus()])
        s = self.g.start()
        pick = reader.choose(self.g, s, "a", random.Random(SEED))
        after, _ = self.g.resolve(s, pick, "overhead")
        self.assertGreater(self.g.value(s, after, "a"), 0, f"{pick} does not beat the habit")
        # statistically, on fixed seeds (a win rate is a measurement, not a seeded witness): 11 of 12 at last count
        wins = sum(ai.duel(self.g, ai.ReaderAgent(), ai.HabitAgent(), seed=k)["winner"] == "a" for k in range(12))
        self.assertGreaterEqual(wins, 9, seed_note(self))


class StringsAndTreeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = model_ctx()

    def test_strings_end_and_every_link_is_answerable(self):
        r = A.check(Combat(self.ctx))
        self.assertTrue(r["laws"]["GL9_strings_end"]["ok"], r["laws"]["GL9_strings_end"])
        self.assertTrue(r["laws"]["GL10_links_answerable"]["ok"], r["laws"]["GL10_links_answerable"])
        self.assertEqual(r["laws"]["GL9_strings_end"]["longest_string"], 3)        # jab, slash, overhead
        # a planted loop (overhead back into jab) never ends
        g = Combat(self.ctx)
        g.chains = {**g.chains, "loop": {"name": "loop", "from": "overhead", "to": "jab", "window": [0, 4],
                                         "on": ["hit"], "damage_pct": 80}}
        self.assertFalse(A.strings_end(g, 3)["ok"])
        self.assertTrue(A.strings_end(g, 3)["cycles"])
        # a jab linked at its first recovery frame: the slash lands as the struck defender's hit-stun ends,
        # with no frame to raise a guard (kernel hit_stun(6) = 12; 2 active + 0 + 12 startup = 14 = 12 + guard 2)
        g = Combat(self.ctx)
        g.chains = {**g.chains, "jab_to_slash_left": {**g.chains["jab_to_slash_left"], "window": [0, 8]}}
        bad = A.links_answerable(g, 2)
        self.assertFalse(bad["ok"])
        self.assertEqual(bad["spare_frames"]["jab_to_slash_left"], 0)

    def test_the_duel_tree(self):
        t = Tree(self.ctx, "warden", "warden")
        t.solve(depth=1)
        k = t.index(1, len(t.centres) // 2, 0, 0)          # mid distance, even frames, both postures low
        rows, cols, M = A.matrix(t.g, t.state(k))
        self.assertAlmostEqual(t.V[k], float(A.solve(M)["value"]), places=6)     # depth 1 is the exchange
        r = t.solve(depth=4)
        self.assertLess(r["last_change"], 2.0)              # deeper exchanges matter less and less (discount)
        for s in range(t.n):                               # a mirror match: a state and its mirror are opposite
            self.assertAlmostEqual(t.V[s], -t.V[t.mirror(s)], places=6)
        broken = t.policy(t.index(0, len(t.centres) // 2, 0, 3))
        self.assertEqual(max(broken, key=broken.get), "heavy_overhead")   # a broken opponent takes the heaviest
        mix = t.string_mix("a", "slash_left", "hit", 0)
        self.assertEqual(set(mix), {"slash_left_to_overhead", "slash_left_to_rising"})
        self.assertTrue(0 < sum(mix.values()) < 1, mix)     # after a hit, linking is an option, not a rule


class WorldTest(unittest.TestCase):
    def test_world_effects_carry_and_explain(self):
        ctx = model_ctx()
        r = W.run(ctx)
        final = set(r["final"])
        self.assertIn(("ash", "tavern"), final)
        self.assertIn(("suspects", "warden_ann", "player"), final)
        why = "\n".join(W.explain(r, ("ash", "tavern"), r["ticks"]))
        self.assertIn("act(ignite, cart)", why)
        ranking = W.impact(ctx)
        self.assertEqual(ranking[0]["action"], "ignite cart @ tick 1")
        self.assertGreater(ranking[1]["changed"], 0)       # the dousing changed the world too


if __name__ == "__main__":
    unittest.main()
