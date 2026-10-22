"""Witness tiers (CM46): classes read from the lifted IR size witnesses that prove; the rest stays sampled."""
import unittest

from helpers import model_ctx

from cardmodel.engines import tiers as T
from cardmodel.engines.frontend_python import lift_source


def fn(ctx, code):
    return [lf.ir for lf in lift_source(code, ctx.ops) if lf.ok][0]


def form(name, code, entry):
    return {"name": name, "lang": "python", "code": code, "entry": entry}


class Classes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = model_ctx()

    def test_polynomials_and_exact_division(self):
        sh = T.shape(fn(self.ctx, "def f(a: int, x: int) -> int:\n    return a * x ** 3 + (x * (x + 1)) // 2\n"))
        self.assertTrue(sh["ok"])
        p = sh["segments"][0]["poly"]
        self.assertEqual((p.degree("x"), p.degree("a")), (3, 1))
        # x(x+1)/4 is not an integer for every x: not a polynomial over Z
        self.assertFalse(T.shape(fn(self.ctx, "def f(x: int) -> int:\n    return x * (x + 1) // 4\n"))["ok"])

    def test_counted_loops_are_c_finite(self):
        sh = T.shape(fn(self.ctx, "def f(n: int) -> int:\n    a = 0\n    b = 1\n    for _ in range(n):\n"
                                  "        a, b = b, a + b\n    return a\n"))
        self.assertTrue(sh["ok"], sh)
        cf = [s for s in sh["segments"] if s["kind"] == "cfinite"]
        self.assertEqual([(s["start"], s["order"]) for s in cf], [(0, 2)])

    def test_what_stays_sampled(self):
        for code in ("def f(b: int, e: int) -> int:\n    r = 1\n    for _ in range(e):\n        r = r * b\n    return r\n",
                     "def f(n: int) -> int:\n    return n % 7\n",
                     "def f(n: int) -> int:\n    s = 0\n    for i in range(n):\n        s = s * s + i\n    return s\n",
                     "def f(n: int) -> int:\n    i = 0\n    while i < n:\n        i += 1\n    return i\n"):
            self.assertFalse(T.shape(fn(self.ctx, code))["ok"], code)

    def test_parameters_changed_before_or_in_a_loop(self):
        # a parameter reassigned before the loop and one updated in it are read as they are, not as the input
        sh = T.shape(fn(self.ctx, "def f(a: int, n: int) -> int:\n    a = a + 1\n    s = 0\n    for _ in range(n):\n"
                                  "        s = s + a\n        a = a + 2\n    return s\n"))
        self.assertTrue(sh["ok"], sh)
        ref = form("r", "def f(a: int, n: int) -> int:\n    a = a + 1\n    s = 0\n    for _ in range(n):\n"
                        "        s = s + a\n        a = a + 2\n    return s\n", "f")
        right = form("c", "def f(a: int, n: int) -> int:\n    if n <= 0:\n        return 0\n"
                          "    return n * (a + 1) + n * (n - 1)\n", "f")
        card = {"precondition": None}
        r = T.prove(self.ctx, _Card(card), ref, right)
        self.assertEqual((r["status"], r["tier"]), ("proved", "proof"), r)


class _Card(dict):
    registry = "algorithm"
    qualified = "algorithm/test"


class SizedWitnesses(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = model_ctx()

    def test_sized_witnesses_prove_and_refute(self):
        card = self.ctx.store.get("algorithm/sum_of_squares")
        forms = {f["name"]: f for f in card.get("forms") or []}
        r = T.prove(self.ctx, card, forms["loop"], forms["closed_form"])
        self.assertEqual((r["status"], r["tier"]), ("proved", "proof"))
        self.assertTrue(any("C-finite" in t for t in r["theorems"]))
        # wrong only from n = 10 on: nine agreeing points would fool a sample of small n; the class sizes past them
        bad = dict(forms["closed_form"], code="def sq_closed(n: int) -> int:\n    if n <= 0:\n        return 0\n"
                   "    return n * (n + 1) * (2 * n + 1) // 6 + (n - 1) * (n - 2) * (n - 3) * (n - 4) * (n - 5) * "
                   "(n - 6) * (n - 7) * (n - 8) * (n - 9)\n")
        r = T.prove(self.ctx, card, forms["loop"], bad)
        self.assertEqual(r["status"], "refuted")
        self.assertEqual(r["at"], [10])
        # a polynomial wrong at one corner of its grid
        cubic = self.ctx.store.get("algorithm/cubic_eval")
        cf = {f["name"]: f for f in cubic.get("forms") or []}
        r = T.prove(self.ctx, cubic, cf["horner"], cf["powers"])
        self.assertEqual(r["status"], "proved")
        off = dict(cf["powers"], code=cf["powers"]["code"].replace("+ d", "+ d + a * b * c * d * (x - 1) * (x - 2) * x"))
        self.assertEqual(T.prove(self.ctx, cubic, cf["horner"], off)["status"], "refuted")

    def test_domains(self):
        self.assertEqual(T.domain_bounds("b >= 0 and m >= 1", ["b", "e", "m"]), {"b": [0, None], "e": [None, None],
                                                                                "m": [1, None]})
        self.assertIsNone(T.domain_bounds("n % 2 == 0", ["n"]))


class Census(unittest.TestCase):
    def test_every_claim_carries_a_tier(self):
        ctx = model_ctx()
        c = T.census(ctx)
        self.assertEqual(c["untiered_count"], 0, c["untiered"])
        self.assertGreater(c["proof"], 0)
        defs = [d for d in ctx.store.cards("definition") if (d.get("subject") or "").startswith("algorithm/")]
        proved = {d["subject"] for d in defs for o in d.get("proof_obligations") or []
                  if o.get("tier") == "proof" and o.get("status") == "proved"}
        self.assertLessEqual({"algorithm/sum_of_squares", "algorithm/cubic_eval", "algorithm/arithmetic_series"},
                             proved)
        for d in ctx.store.cards("definition"):
            for o in d.get("proof_obligations") or []:
                self.assertIn(o.get("tier"), T.TIERS, d.qualified)


if __name__ == "__main__":
    unittest.main()
