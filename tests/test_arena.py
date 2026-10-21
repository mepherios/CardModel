"""The arena: generated suboptimal programs, scored for soundness, recall and speed."""
import unittest

from helpers import SEED, TempProject, seed_note

from cardmodel.engines import arena


class Arena(unittest.TestCase):
    def test_arena_run_is_sound_and_improves(self):
        p = TempProject()
        try:
            ctx = p.ctx()
            res = arena.run(ctx, count=14, seed=SEED, samples=12)
            sc = res["score"]
            self.assertTrue(sc["sound"], (sc, seed_note(self)))
            self.assertEqual(sc["decoys_wrongly_substituted"], [])
            self.assertTrue(sc["shell_preserved"])
            if sc["planted"]:
                self.assertGreater(sc["planted_improved"], 0, (sc, seed_note(self)))
            name = arena.record(ctx, res, layer="project")
            ctx.store.invalidate()
            self.assertEqual(ctx.store.get(name)["score"]["seed"], SEED)
        finally:
            p.cleanup()

    def test_generator_is_deterministic(self):
        ctx = TempProject().ctx()
        a, ka = arena.generate(ctx, 20, SEED)
        b, kb = arena.generate(ctx, 20, SEED)
        self.assertEqual(a, b)
        self.assertEqual(ka, kb)
        self.assertEqual(len(ka), 20)
        compile(a, "<arena>", "exec")


if __name__ == "__main__":
    unittest.main()
