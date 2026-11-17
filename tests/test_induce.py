"""induce: learning a computation from its behaviour alone (understanding, not recall)."""
import json
import random
import unittest

from helpers import SEED, TempProject, model_ctx, seed_note

from cardmodel.engines import induce as I

OPS = model_ctx().ops
X = [("x", "int")]
AB = [("a", "int"), ("b", "int")]


def examples(fn, params, n, seed):
    rng = random.Random(seed)
    xs = [tuple(rng.randint(-20, 20) for _ in params) for _ in range(n)]
    return xs, [fn(*x) for x in xs]


class Search(unittest.TestCase):
    def test_learns_a_program_that_compresses_its_examples(self):
        xs, ys = examples(lambda x: x * x + 1, X, 10, SEED)
        r = I.search(X, xs, ys, OPS, max_size=5)
        self.assertTrue(r["found"], seed_note(self))
        self.assertEqual(I.size(r["term"]), 5)
        self.assertTrue(r["understood"])
        self.assertGreater(r["compression"], 1)

    def test_structureless_data_is_not_understood(self):
        rng = random.Random(SEED)
        xs = [(i,) for i in range(8)]
        ys = [rng.randint(-10 ** 6, 10 ** 6) for _ in xs]
        r = I.search(X, xs, ys, OPS, max_size=4, budget=50_000)
        self.assertFalse(r.get("understood", False), seed_note(self))

    def test_noise_is_tolerated_by_description_length(self):
        xs, ys = examples(lambda x: x * x, X, 12, SEED)
        ys[3] += 7                                          # one wrong example
        exact = I.search(X, xs, ys, OPS, max_size=4, budget=100_000)
        noisy = I.search(X, xs, ys, OPS, max_size=4, budget=100_000, noise=0.2)
        self.assertTrue(noisy["found"], seed_note(self))
        self.assertEqual(I.show(noisy["term"]), "MUL(x, x)")
        self.assertEqual(noisy["errors"], 1)
        self.assertNotEqual(exact.get("term"), noisy["term"])

    def test_undefined_ops_are_not_errors_of_the_search(self):
        xs, ys = examples(lambda a, b: (a + b) // 2, AB, 10, SEED)
        r = I.search(AB, xs, ys, OPS, max_size=5)
        self.assertTrue(r["found"], seed_note(self))


class Generalisation(unittest.TestCase):
    def test_questions_correct_an_underdetermined_guess(self):
        task = I.Task("abs_difference", AB, oracle=lambda a, b: abs(a - b))
        r = I.learn_task(task, OPS, seed=SEED, n_examples=3, max_size=4)
        self.assertTrue(r["understood"], seed_note(self))
        self.assertTrue(r["generalises"])
        self.assertEqual(r["fresh"]["correct"], r["fresh"]["examples"])

    def test_held_out_examples_score_the_program(self):
        xs, ys = examples(lambda a, b: max(a, b) - min(a, b), AB, 12, SEED)
        task = I.Task("spread", AB, list(zip(xs, ys)))
        r = I.learn_task(task, OPS, seed=SEED, max_size=5)
        self.assertEqual(r["held_out"]["correct"], r["held_out"]["examples"], seed_note(self))

    def test_the_learned_program_is_core_ir(self):
        task = I.Task("square_plus_one", X, oracle=lambda x: x * x + 1)
        r = I.learn_task(task, OPS, seed=SEED, max_size=5)
        self.assertTrue(r["ir_checked"], seed_note(self))
        self.assertEqual(r["ir"]["body"][0]["k"], "return")


class Concepts(unittest.TestCase):
    def setUp(self):
        solved = {"square": ["MUL", ["var", "x"], ["var", "x"]],
                  "square_plus_one": ["ADD", ["MUL", ["var", "x"], ["var", "x"]], ["int", 1]]}
        self.concepts = I.discover_concepts(solved, {"square": X, "square_plus_one": X}, OPS)

    def test_a_concept_recurs_across_tasks(self):
        bodies = [I.show(c.body) for c in self.concepts]
        self.assertIn("MUL(x0, x0)", bodies)
        sq = next(c for c in self.concepts if I.show(c.body) == "MUL(x0, x0)")
        self.assertEqual(sq.evidence["abstracted_from"], ["square", "square_plus_one"])

    def test_one_task_is_no_concept(self):
        none = I.discover_concepts({"square": ["MUL", ["var", "x"], ["var", "x"]]}, {"square": X}, OPS)
        self.assertEqual(none, [])

    def test_a_concept_makes_an_unreachable_task_reachable(self):
        xs, ys = examples(lambda a, b: a * a + b * b, AB, 10, SEED)
        before = I.search(AB, xs, ys, OPS, max_size=5)
        after = I.search(AB, xs, ys, OPS, self.concepts, max_size=5)
        self.assertFalse(before["found"], seed_note(self))
        self.assertTrue(after["found"], seed_note(self))
        cmap = {c.name: c for c in self.concepts}
        plain = I.inline(after["term"], cmap)
        self.assertEqual(I.size(plain), 7)              # the same program, written without the concept
        for x, y in zip(xs, ys):
            self.assertEqual(I.evaluate(plain, dict(zip("ab", x)), OPS, {}), y)

    def test_concepts_are_cards_and_come_back(self):
        p = TempProject()
        ctx = p.ctx()
        I.save_concepts(ctx.store, self.concepts)
        back = I.load_concepts(p.ctx().store)
        self.assertEqual({c.name for c in back}, {c.name for c in self.concepts})
        self.assertEqual(back[0].card()["metadata"]["learned"], True)


class Cli(unittest.TestCase):
    def test_fit_from_a_file(self):
        xs, ys = examples(lambda a, b: abs(a - b), AB, 12, SEED)
        p = TempProject({"ex.json": json.dumps({"name": "gap", "params": AB,
                                                "examples": [[list(x), y] for x, y in zip(xs, ys)]})})
        r = p.cli("--json", "induce", "fit", str(p.dir / "ex.json"), "--max-size", "4", "--seed", str(SEED))
        self.assertEqual(r.returncode, 0, r.stderr + seed_note(self))
        rep = json.loads(r.stdout)
        self.assertTrue(rep["understood"])
        self.assertEqual(rep["program"], "ABS(SUB(a, b))")


if __name__ == "__main__":
    unittest.main()
