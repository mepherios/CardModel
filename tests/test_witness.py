"""Witnesses: forms vs reference, known-answer vectors, rules; a witness must be able to fail (CM07/CM08)."""
import random
import unittest
from fractions import Fraction

from helpers import SEED, model_ctx, seed_note

from cardmodel.engines import redefs, witness
from cardmodel.engines.exprs import FUNCS, MAX_SUM_TERMS, evaluate, parse, to_text, variables
from cardmodel.kernel.card import Card


class Forms(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = model_ctx()

    def test_builtin_runnable_forms_are_witnessed(self):
        failures = {}
        for reg in ("op", "re_operation"):
            for card in self.ctx.store.cards(reg):
                res = witness.verify_forms(self.ctx, card, seed=SEED, samples=24)
                for name, r in res["forms"].items():
                    if r["status"] in ("fail", "error", "vacuous"):
                        failures[f"{card.qualified}:{name}"] = r
        self.assertEqual(failures, {}, seed_note(self))

    def test_wrong_form_is_caught(self):
        card = Card({"name": "ADDX", "category": "op", "statement": "t", "generators": [{"int": [-50, 50]}] * 2,
                     "forms": [{"name": "native", "code": "lambda a, b: a + b", "domain": "any"},
                               {"name": "off_by_one", "code": "lambda a, b: a + b + (1 if a == 7 else 0)",
                                "domain": "any"}]}, registry="op")
        card["generators"] = [{"int": [-50, 50], "edges": [7]}, {"int": [-50, 50]}]
        res = witness.verify_forms(self.ctx, card, seed=SEED, samples=16)
        self.assertEqual(res["forms"]["off_by_one"]["status"], "fail")
        self.assertEqual(res["forms"]["off_by_one"]["args"][0], 7)
        self.assertTrue(res["comparator_rejects_perturbation"])

    def test_hub_claim_refuted_and_corrected_domain_verified(self):
        res = witness.verify_forms(self.ctx, self.ctx.store.get("op/ABS"), seed=SEED, samples=24)
        b = res["forms"]["branchless"]
        self.assertEqual((b["status"], b["domain"]), ("pass", "i32"))
        self.assertEqual(b["hub_claim"]["status"], "fail")           # the hub said domain "int"
        self.assertGreaterEqual(abs(b["hub_claim"]["args"][0]), 2**31)


class Vectors(unittest.TestCase):
    def test_crypto_vectors_in_two_languages(self):
        ctx = model_ctx()
        two = 0
        for card in ctx.store.cards("crypto_atom"):
            if not card.get("vectors"):
                continue
            r = witness.verify_vectors(ctx, card)
            self.assertEqual(r["status"], "pass", (card.name, r))
            passing = [k for k, v in r["forms"].items() if v["status"] == "pass"]
            two += len(passing) >= 2
        self.assertGreaterEqual(two, 10)          # stdlib python + node:crypto agree on Ting's RFC vectors

    def test_vector_witness_can_fail(self):
        ctx = model_ctx()
        card = ctx.store.get("crypto_atom/sha256").copy()
        card["vectors"] = [{"name": "wrong", "args": [{"$bytes": ""}], "out": {"$bytes": "00" * 32}}]
        r = witness.verify_vectors(ctx, card)
        self.assertEqual(r["status"], "fail")


class Rules(unittest.TestCase):
    def test_rules_pass_and_false_rule_fails(self):
        ctx = model_ctx()
        for card in ctx.store.cards("rewrite_rule"):
            r = witness.verify_rule(card, seed=SEED, ops=ctx.ops)
            self.assertEqual(r["status"], "pass", (card.name, r, seed_note(self)))
            self.assertTrue(r["witness_can_fail"])
        bad = {"name": "bad", "lhs": "(a + b) ** 2", "rhs": "a ** 2 + b ** 2", "vars": ["a", "b"]}
        self.assertEqual(witness.verify_rule(bad, seed=SEED)["status"], "fail")

    def test_rules_hold_in_the_model(self):
        # FOUNDATIONS.md rule A2: a rule is witnessed in the semantics it is applied in, the op cards' own
        ctx = model_ctx()
        for card in ctx.store.cards("rewrite_rule"):
            r = witness.verify_rule(card, seed=SEED, ops=ctx.ops)
            self.assertEqual(r["status"], "pass", (card.name, r, seed_note(self)))
        bad = {"name": "bad", "lhs": "gcd(a, b)", "rhs": "a", "vars": ["a", "b"]}
        self.assertEqual(witness.verify_rule(bad, seed=SEED, ops=ctx.ops)["status"], "fail")

    def test_rule_calls_are_op_cards(self):
        # rule A1: gcd(a, b) in a rule card is the op GCD, so the rule matches the IR's terms
        from cardmodel.engines import search
        ctx = model_ctx()
        rules = {r.name: r for r in search.load_rules(ctx.store)}
        self.assertEqual(rules["rule_absorb_left_GCD_1"].lhs, ["GCD", ["int", 1], "?a"])

    def test_exprs_agrees_with_the_op_cards(self):
        # exprs.evaluate's exact-integer mode is a second reading of the ops; it must not drift from the model
        ctx = model_ctx()
        rng = random.Random(SEED)
        compared = 0
        for name, spec in sorted(ctx.ops.items()):
            dom = ((spec.card.get("ir") or {}).get("domain") or {}).get("int")
            if spec.fn is None or not dom or ["int"] * spec.arity not in [s[:-1] for s in spec.types]:
                continue
            for _ in range(40):
                args = [rng.randint(*g["int"]) for g in dom]
                try:
                    want = spec.fn(*args)
                except (ArithmeticError, ValueError):
                    continue
                try:
                    got = evaluate([name, *[["int", a] for a in args]], {})
                except Exception:  # noqa: BLE001 -- an op exprs does not read is not a disagreement
                    break
                self.assertEqual(got, want, (name, args, seed_note(self)))
                compared += 1
        self.assertGreater(compared, 400)


class Redefinitions(unittest.TestCase):
    def test_true_false_and_unknown(self):
        ok = redefs.verify({"name": "t", "source_form": "(x+1)**2", "target_form": "x**2 + 2*x + 1",
                            "domain": "integer"}, seed=SEED, symbolic=False)
        self.assertEqual(ok["verdict"], "verified")
        bad = redefs.verify({"name": "f", "source_form": "sin(2*x)", "target_form": "2*sin(x)", "domain": "real"},
                            seed=SEED, symbolic=False)
        self.assertEqual(bad["verdict"], "refuted")
        unk = redefs.verify({"name": "u", "source_form": "T(n)", "target_form": "n", "domain": "integer"},
                            seed=SEED, symbolic=False)
        self.assertEqual(unk["verdict"], "inconclusive")

    def test_incomplete_examples_detected(self):
        r = redefs.verify({"name": "e", "source_form": "-x**2*y**2 - 2*x", "target_form": "-x*(x*y**2 + 2)",
                           "domain": "real", "examples": [{"input": {"x": 1}, "source_eval": "1", "target_eval": "1"}]},
                          seed=SEED, symbolic=False)
        self.assertEqual(r["verdict"], "verified")
        self.assertEqual(r["examples"]["incomplete"], 1)       # y was never bound: that example proved nothing

    def test_vendored_redefinitions_hold(self):
        ctx = model_ctx()
        refuted = [c.name for c in ctx.store.cards("redefinition")
                   if redefs.verify(c, seed=SEED, symbolic=False)["verdict"] == "refuted"]
        self.assertEqual(refuted, [], seed_note(self))

    def test_float_cancellation_is_no_counterexample(self):
        # Seed 4292375619 refuted this true identity: its target divides by (2*x**2*y - 4*x - 2)**2, which nearly
        # vanishes where x**2*y - 2*x is near 1, and floats lost six digits there. Rational forms are now exact.
        card = model_ctx().store.get("redefinition/auto_v2_670eead414e1362d")
        r = redefs.verify(card, seed=4292375619, symbolic=False)
        self.assertEqual((r["verdict"], r["decided"]), ("verified", {"exact": 40}))
        lhs, rhs = parse(card["source_form"]), parse(card["target_form"])
        env = {"x": 2.5311382259982365, "y": 0.9461962566039399}
        self.assertFalse(redefs._close(evaluate(lhs, env, "real"), evaluate(rhs, env, "real")))   # floats disagree
        outcome, a, b, how = redefs.compare(lhs, rhs, env, "real")
        self.assertEqual((outcome, how, a == b), ("agree", "exact", True))
        # tan(2x) as a difference of squares cancels the same way near x = -pi/2; high precision decides there
        trig = model_ctx().store.get("redefinition/auto_v2_a137bc0eddb7f5e9")
        self.assertEqual(redefs.verify(trig, seed=562571390, symbolic=False)["verdict"], "verified")
        lhs, rhs = parse(trig["source_form"]), parse(trig["target_form"])
        self.assertEqual(redefs.compare(lhs, rhs, {"_x": -1.5708405367815896}, "real")[0], "agree")

    def test_planted_false_identities_are_still_refuted(self):
        card = model_ctx().store.get("redefinition/auto_v2_670eead414e1362d")
        near = dict(card, target_form=card["target_form"] + " + x/10**12")       # far below the float tolerance
        r = redefs.verify(near, seed=4292375619, symbolic=False)
        self.assertEqual((r["verdict"], r["counterexample"]["decided_by"]), ("refuted", "exact"))
        trig = model_ctx().store.get("redefinition/auto_v2_a137bc0eddb7f5e9")
        lhs, rhs = parse(trig["source_form"]), parse(trig["target_form"] + " + 1/1000")
        outcome, _, _, how = redefs.compare(lhs, rhs, {"_x": -1.5708405367815896}, "real")   # the point floats fail at
        self.assertEqual((outcome, how), ("differ", "60 digits"))
        r = redefs.verify(dict(trig, target_form=trig["target_form"] + " + 1/1000"), seed=SEED, symbolic=False)
        self.assertEqual(r["verdict"], "refuted", seed_note(self))
        for src, dst, dom in (("(x+1)**2", "x**2 + 2*x", "real"), ("x/(x - 1)", "1 + 1/x", "integer"),
                              ("sqrt(x**2)", "x", "real"), ("tan(2*x)", "2*tan(x)/(1 + tan(x)**2)", "real")):
            r = redefs.verify({"name": "planted", "source_form": src, "target_form": dst, "domain": dom},
                              seed=SEED, symbolic=False)
            self.assertEqual(r["verdict"], "refuted", (src, dst, seed_note(self)))

    def test_sums_and_integer_functions_evaluate_exactly(self):
        t = parse("Sum(2*i - 1, (i, 1, x)).doit()")
        self.assertEqual(t[0], "SUM")
        self.assertEqual(variables(t), {"x"})                      # i is bound: no sample point names it
        self.assertEqual(parse(to_text(t)), t)
        # sympy's (Karr's) convention for reversed bounds, so x**2 holds on every integer x, as symbolically
        self.assertEqual([evaluate(t, {"x": x}) for x in (-3, -1, 0, 1, 2, 5)], [9, 1, 0, 1, 4, 25])
        self.assertEqual(redefs.exact_value(t, {"x": Fraction(-4)}), 16)
        with self.assertRaises(ArithmeticError):                   # bounded work (CM18)
            evaluate(t, {"x": MAX_SUM_TERMS + 1})
        self.assertEqual(parse("f(x).doit()")[0], "FN")            # only a sum's .doit() is dropped
        self.assertEqual([evaluate(parse("fibonacci(n)"), {"n": n}) for n in (0, 1, 10, 70)],
                         [0, 1, 55, 190392490709135])
        self.assertEqual([evaluate(parse("multiplicity(2, n)"), {"n": n}) for n in (1, 24, -64)], [0, 3, 6])
        for bad in ("fibonacci(-1)", "multiplicity(2, 0)", "fibonacci(1/2)"):
            with self.assertRaises(ValueError, msg=bad):
                evaluate(parse(bad), {})

    def test_cards_that_named_unknown_functions_verify_and_planted_breaks_fail(self):
        # These four were inconclusive (0 points in the domain): their forms named T, v_2 or a sympy Sum that
        # the evaluator did not know, so every point raised UnknownName. With exact forms they verify, and a
        # one-symbol change to either side is refuted, so the witness can fail (CM07).
        ctx = model_ctx()
        planted = {"collatz_step_binary": ("source_form", "n / 2 if n % 2 == 0 else 3*n + 1"),   # the plain step T
                   "collatz_via_2adic_valuation": ("source_form", "n / 2"),                       # one T step
                   "fibonacci_closed_form": ("target_form", "((1 + sqrt(5))/2)**(_n + 1) / sqrt(5) - "
                                                            "((1 - sqrt(5))/2)**(_n + 1) / sqrt(5)"),   # F(n+1)
                   "square_of_x__odd_sum": ("target_form", "Sum(2*i + 1, (i, 1, x))")}
        for name, (side, wrong) in planted.items():
            card = ctx.store.get(f"redefinition/{name}")
            r = redefs.verify(card, seed=SEED, symbolic=False)
            self.assertEqual(r["verdict"], "verified", (name, r, seed_note(self)))
            self.assertGreaterEqual(r["valid_points"], redefs.MIN_VALID)
            self.assertEqual(r["examples"]["disagree"] + r["examples"]["incomplete"], 0, name)
            r = redefs.verify(dict(card, **{side: wrong}), seed=SEED, symbolic=False)
            self.assertEqual(r["verdict"], "refuted", (name, seed_note(self)))

    def test_every_function_has_an_exact_or_precise_form(self):
        self.assertEqual(set(FUNCS) - redefs.EXACT_FUNCS, set(redefs.PRECISE))   # a new function needs one or the other
        rng = random.Random(SEED)
        ranges = {"sqrt": (0, 50), "log": (1e-3, 50), "log2": (1e-3, 50), "log10": (1e-3, 50), "asin": (-1, 1),
                  "acos": (-1, 1), "acosh": (1, 50), "atanh": (-0.99, 0.99), "gamma": (-9.5, 30), "exp": (-50, 50),
                  "sinh": (-50, 50), "cosh": (-50, 50)}
        for name in sorted(redefs.PRECISE):
            lo, hi = ranges.get(name, (-20, 20))
            for _ in range(12):
                args = [rng.uniform(lo, hi) for _ in range(2 if name in ("atan2", "hypot") else 1)]
                tree = ["FN", name, *(["var", f"a{i}"] for i in range(len(args)))]
                env = {f"a{i}": Fraction(a) for i, a in enumerate(args)}
                ref, got = FUNCS[name](*args), redefs.exact_value(tree, env, 30)
                self.assertLess(abs(float(got) - ref), 1e-13 * max(1.0, abs(ref)), (name, args, seed_note(self)))
                self.assertLess(abs(got - redefs.exact_value(tree, env, 60)), Fraction(1, 10**25) * max(1, abs(got)),
                                (name, args, seed_note(self)))


if __name__ == "__main__":
    unittest.main()
