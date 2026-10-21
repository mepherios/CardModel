"""Witnesses: forms vs reference, known-answer vectors, rules; a witness must be able to fail (CM07/CM08)."""
import unittest

from helpers import SEED, model_ctx, seed_note

from cardmodel.engines import redefs, witness
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
            r = witness.verify_rule(card, seed=SEED)
            self.assertEqual(r["status"], "pass", (card.name, r, seed_note(self)))
            self.assertTrue(r["witness_can_fail"])
        bad = {"name": "bad", "lhs": "(a + b) ** 2", "rhs": "a ** 2 + b ** 2", "vars": ["a", "b"]}
        self.assertEqual(witness.verify_rule(bad, seed=SEED)["status"], "fail")


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


if __name__ == "__main__":
    unittest.main()
