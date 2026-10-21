"""The arena: generated suboptimal programs, scored for soundness, recall and speed."""
import math
import random
import unittest

from helpers import SEED, TempProject, model_ctx, seed_note

from cardmodel.engines import arena, improve
from cardmodel.engines.frontend_python import lift_source, module_for

# seeds that once failed: run every time, next to the fresh SEED
REGRESSION_SEEDS = {
    2837705631: "its triangular decoy (t = 1) was triangular + 1: improve replaced it, correctly, by the affine "
                "form 1 * triangular + 1 and the score counted that as a wrongly substituted decoy",
}


def _matched_cards(ctx, source: str, name: str, inputs: list) -> tuple[set, list]:
    """The algorithm cards improve's behavioural matcher proposes for ``name`` on ``inputs`` (kept, as improve
    keeps them, only where the function finishes quickly) and those inputs."""
    fn_ir = next(f for f in module_for(name, lift_source(source, ctx.ops))["functions"] if f["name"] == name)
    ref = improve._load(source)[name]
    inputs = improve._cheap_inputs(ref, inputs)
    return {c["card"] for c in improve.algorithm_candidates(ctx, fn_ir, ref, inputs)}, inputs


class Arena(unittest.TestCase):
    def _sound_run(self, seed: int, note: str) -> None:
        p = TempProject()
        try:
            ctx = p.ctx()
            res = arena.run(ctx, count=14, seed=seed, samples=12)
            sc = res["score"]
            self.assertTrue(sc["sound"], (sc, note))
            self.assertEqual(sc["decoys_wrongly_substituted"], [], note)
            self.assertTrue(sc["shell_preserved"])
            if sc["planted"]:
                self.assertGreater(sc["planted_improved"], 0, (sc, note))
            name = arena.record(ctx, res, layer="project")
            ctx.store.invalidate()
            self.assertEqual(ctx.store.get(name)["score"]["seed"], seed)
        finally:
            p.cleanup()

    def test_arena_run_is_sound_and_improves(self):
        self._sound_run(SEED, seed_note(self))

    def test_regression_seeds(self):
        for seed, why in REGRESSION_SEEDS.items():
            with self.subTest(seed=seed):
                self._sound_run(seed, f"(regression seed {seed}: {why})")

    def test_decoys_are_refuted_by_the_matcher(self):
        """No decoy equals a * card + b for the card it imitates: on the small inputs every comparison includes,
        the matcher refutes each decoy, while the card's own reference form matches on those same inputs (so the
        refutation is evidence, not too few pairs). A decoy the matcher accepts is replaced correctly and would be
        scored as a wrongly substituted decoy, so this is checked for every template, independent of seeds."""
        ctx = model_ctx()
        small = [r for r in improve.structured_inputs(["int"], random.Random(SEED)) if abs(r[0]) <= 1000]
        for card_name, tpl in arena.DECOYS:
            with self.subTest(decoy=card_name):
                card = ctx.store.get(f"algorithm/{card_name}")
                matched, inputs = _matched_cards(ctx, tpl.format(name="decoy", p0="n"), "decoy", small)
                self.assertNotIn(card.qualified, matched)
                form = next(f for f in card["forms"] if f["name"] == card["reference_form"])
                if card.get("filter"):    # pairs come only from inside the filter, and outside it the reference
                    filt = eval(card["filter"], {"__builtins__": {}, "math": math})  # noqa: S307 -- card data
                    inputs = [a for a in inputs if filt(*a)]   # form may not halt (Kernighan popcount, n < 0)
                param = card["signature"]["params"][0]["name"]
                own = improve.rename(form["code"], {form["entry"]: "decoy", param: "n"})
                self.assertIn(card.qualified, _matched_cards(ctx, own, "decoy", inputs)[0])

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
