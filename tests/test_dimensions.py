"""Physics as a Gödel set (docs/GODEL_TARGET.md G13, §6 step 4): the base quantities are atoms, a dimension is signed
content, the IR's ops act on dimensions through the model the set card states, and a law is consistent exactly when
its two sides have one dimension. The algebra is engines/godel's; nothing here is physics-specific code."""
import json
import random
import unittest
from collections import Counter
from fractions import Fraction

from helpers import SEED, TempProject, model_ctx, seed_note

from cardmodel.engines import dimensions as D
from cardmodel.engines import godel as G
from cardmodel.engines import numbering as N


class Physics(unittest.TestCase):
    def test_the_set_is_admissible(self):
        """The same six conditions every Gödel set meets (W-5), with the quantities as leaves of its objects."""
        ctx = model_ctx()
        samples = int(D.set_card(ctx)["numbering"]["samples"])  # fewer than other sets: its codes are huge (the card says why)
        r = N.check_set(ctx, D.SET, seed=0, samples=samples)
        self.assertEqual(r["status"], "pass", r)
        self.assertGreater(r["conditions"]["injective"]["checked"], 0)
        nb = N.Numbering(ctx, D.SET)
        rng = random.Random(SEED)
        objs = [nb.generate(rng) for _ in range(60)]
        self.assertTrue(any("quantity/" in json.dumps(o) for o in objs), seed_note(self))
        t = ["op/MUL", ["quantity/mass"], ["op/DIV", ["quantity/length"], ["op/POW", ["quantity/time"], ["int", 2]]]]
        self.assertEqual(nb.decode(nb.encode(t)), t)
        self.assertEqual(G.term_content(t, None), Counter({"op/MUL": 1, "op/DIV": 1, "op/POW": 1, "quantity/mass": 1,
                                                           "quantity/length": 1, "quantity/time": 1}))

    def test_atoms_model_and_laws_are_cards(self):
        ctx = model_ctx()
        r = D.check(ctx)
        self.assertEqual(r["problems"], [])
        self.assertEqual(r["status"], "pass")
        self.assertGreaterEqual(len(r["laws"]), 10)
        self.assertTrue(all(x["consistent"] for x in r["laws"].values()), r["laws"])
        self.assertEqual(r["laws"]["physics_law/newton_second"]["name"], "force")
        self.assertEqual(r["laws"]["physics_law/pendulum_period"]["dimension"], "time")
        self.assertTrue(r["base_preserves_gcd"])                # the base quantities are the free generators
        self.assertFalse(r["derived_preserves_gcd"])            # derived ones are products: supports overlap
        idx = G.index_of(ctx.store)
        self.assertTrue(all(idx[a]["set"] == D.SET for a in D.ATOMS))
        card = D.set_card(ctx)
        self.assertTrue(set(card["model"]) >= {"MUL", "DIV", "ADD", "POW", "FSQRT", "CMP_LT", "EXP", "IF_EXPR"})
        self.assertTrue(all(v in D.ACTIONS for v in card["model"].values()))

    def test_text_and_parse_round_trip(self):
        derived = {"force": D.parse("mass*length/time^2")}
        for s in ("1", "mass", "mass*length*time^-2", "length^1/2", "time^-1", "length^3*mass^-1*time^-2"):
            d = D.parse(s)
            self.assertEqual(D.parse(D.text(d)), d, s)
        self.assertEqual(D.parse("force", derived), derived["force"])
        self.assertEqual(D.parse("force/mass", derived), D.parse("length/time^2"))
        self.assertEqual(D.parse("length*time**-2"), Counter({"quantity/length": 1, "quantity/time": -2}))
        self.assertEqual(D.parse("time^(1/2)"), Counter({"quantity/time": Fraction(1, 2)}))
        self.assertEqual(D.name_of(D.parse("mass*length/time^2"), derived), "force")
        self.assertEqual(D.name_of(D.parse("mass"), derived), "mass")
        self.assertEqual(D.name_of(Counter(), derived), "1")
        self.assertIsNone(D.name_of(D.parse("mass^2"), derived))
        with self.assertRaises(ValueError):
            D.parse("mass*apples")
        with self.assertRaises(ValueError):
            D.parse("mass ^^ 2")

    def test_the_ops_act_as_the_group(self):
        """MUL adds, DIV subtracts, POW scales, FSQRT halves, ADD keeps one dimension or refuses: the content group."""
        ctx = model_ctx()
        model = D.model_of(ctx)
        rng = random.Random(SEED)

        def dim():
            return G._strip(Counter({a: rng.randint(-2, 2) for a in D.ATOMS[:3]}))
        for _ in range(40):
            env = {"x": dim(), "y": dim()}
            x, y = D.of(["var", "x"], env, model), D.of(["var", "y"], env, model)
            self.assertEqual(D.of(["MUL", ["var", "x"], ["var", "y"]], env, model), G.add(x, y), seed_note(self))
            self.assertEqual(D.of(["DIV", ["var", "x"], ["var", "y"]], env, model), G.sub(x, y), seed_note(self))
            n = rng.randint(-3, 3)
            self.assertEqual(D.of(["POW", ["var", "x"], ["int", n]], env, model), G.scale(x, n), seed_note(self))
            self.assertEqual(D.of(["FSQRT", ["POW", ["var", "x"], ["int", 2]]], env, model), x, seed_note(self))
            self.assertEqual(D.of(["ADD", ["var", "x"], ["MUL", ["int", 3], ["var", "x"]]], env, model), x,
                             seed_note(self))
            self.assertEqual(D.of(["CMP_LT", ["var", "x"], ["var", "x"]], env, model), Counter(), seed_note(self))
            if x != y:
                probs: list[str] = []
                self.assertIsNone(D.of(["ADD", ["var", "x"], ["var", "y"]], env, model, probs), seed_note(self))
                self.assertTrue(probs and probs[0].startswith("ADD:"), probs)
        self.assertEqual(D.of(["MUL", ["quantity/mass"], ["int", 2]], {}, model), Counter({"quantity/mass": 1}))
        self.assertEqual(D.of(["FSQRT", ["quantity/time"]], {}, model), Counter({"quantity/time": Fraction(1, 2)}))
        probs = []
        self.assertIsNone(D.of(["EXP", ["quantity/time"]], {}, model, probs))
        self.assertIn("EXP needs dimensionless", probs[0])
        probs = []
        self.assertIsNone(D.of(["CALL", "f", ["int", 1]], {}, model, probs))
        self.assertIn("no dimension rule", probs[0])
        probs = []
        self.assertIsNone(D.of(["POW", ["quantity/time"], ["var", "n"]], {"n": "1"}, model, probs))
        self.assertIn("variable exponent", probs[0])

    def test_an_inconsistent_law_is_refused(self):
        ctx = model_ctx()
        model, derived = D.model_of(ctx), D.derived_of(ctx)
        env = {"E": "energy", "m": "mass", "v": "velocity"}
        bad = D.check_equation(["var", "E"], ["MUL", ["var", "m"], ["var", "v"]], env, model, derived)
        self.assertFalse(bad["consistent"])
        self.assertIn("the sides differ", bad["problems"][0])
        good = D.check_equation(["var", "E"], ["MUL", ["var", "m"], ["POW", ["var", "v"], ["int", 2]]], env, model,
                                derived)
        self.assertTrue(good["consistent"])
        self.assertEqual(good["name"], "energy")

    def test_command(self):
        proj = TempProject()
        try:
            r = proj.cli("godel", "dimension", "physics_law/newton_second", "physics_law/pendulum_period")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("consistent, force", r.stdout)
            self.assertIn("physics_law/pendulum_period", r.stdout)
            r = proj.cli("godel", "dimension", "--expr", "m*a/2", "--dims", "m=mass,a=length/time^2")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("length*mass*time^-2 (force)", r.stdout)
            r = proj.cli("godel", "dimension", "--expr", "m+a", "--dims", "m=mass,a=length/time^2")
            self.assertIn("no dimension: ADD:", r.stdout)
            self.assertEqual(proj.cli("godel", "dimension", "--expr", "m", "--dims", "m=apples").returncode, 2)
        finally:
            proj.cleanup()


if __name__ == "__main__":
    unittest.main()
