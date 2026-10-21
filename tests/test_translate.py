"""Observe -> card IR -> native code in other languages -> verified against the original Python."""
import unittest

from helpers import SEED, SLOW, model_ctx, seed_note

from cardmodel.engines import translate
from cardmodel.engines.codegen import EmitGap, emit_module
from cardmodel.engines.frontend_python import lift_source, module_for
from cardmodel.engines.ir import Interpreter

SRC = '''
import math

def gcd(a: int, b: int) -> int:
    while b != 0:
        a, b = b, a % b
    return abs(a)

def fib(n: int) -> int:
    a, b = 0, 1
    for _ in range(n):
        a, b = b, a + b
    return a

def is_prime(n: int) -> bool:
    if n < 2:
        return False
    i = 2
    while i * i <= n:
        if n % i == 0:
            return False
        i += 1
    return True

def count_primes(limit: int) -> int:
    c = 0
    for k in range(2, limit):
        if is_prime(k):
            c += 1
    return c

def tri(n: int) -> int:
    total = 0
    for i in range(n, 0, -1):
        if i % 3 == 0:
            continue
        total += i
    return total

def mean3(a: float, b: float, c: float) -> float:
    return (a + b + c) / 3

def uses_list(xs: list) -> int:
    return len(xs)

def calls_bad(n: int) -> int:
    return uses_list(n)
'''


class Lift(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = model_ctx()
        cls.lifted = {lf.name: lf for lf in lift_source(SRC, cls.ctx.ops)}

    def test_supported_subset_lifts(self):
        for n in ("gcd", "fib", "is_prime", "count_primes", "tri", "mean3"):
            self.assertTrue(self.lifted[n].ok, (n, self.lifted[n].reasons))

    def test_unsupported_is_reported_precisely(self):
        lf = self.lifted["uses_list"]
        self.assertFalse(lf.ok)
        self.assertIn("type annotation 'list'", lf.reasons[0])
        self.assertIn("line", lf.reasons[0])
        self.assertFalse(self.lifted["calls_bad"].ok)       # closure: calls a function that did not lift

    def test_interpreter_matches_python(self):
        ns = {}
        exec(SRC, ns)
        lifted = list(self.lifted.values())
        for name, args in [("gcd", (84, -36)), ("fib", (30,)), ("count_primes", (50,)), ("tri", (17,))]:
            mod = module_for(name, lifted)
            self.assertEqual(Interpreter(mod, self.ctx.ops).call(name, list(args)), ns[name](*args))

    def test_lean_gap_for_floats(self):
        mod = module_for("mean3", list(self.lifted.values()))
        with self.assertRaises(EmitGap):
            emit_module(self.ctx.store, self.ctx.ops, "lean", mod)


class Translate(unittest.TestCase):
    def test_functions_agree_across_languages(self):
        ctx = model_ctx()
        lifted = lift_source(SRC, ctx.ops)
        langs = None if SLOW else [l for l in ("python", "javascript", "c") if ctx.available(l)[0]]
        for name in ("gcd", "fib", "count_primes", "tri", "mean3"):
            card = translate.function_card(ctx, name, lifted, "test_translate.py", seed=SEED)
            self.assertEqual(card["verification"]["lift_fidelity"]["mismatched"], 0, name)
            self.assertGreaterEqual(len(card["vectors"]), 8, name)
            rep = translate.verify_function(ctx, card, langs=langs, seed=SEED)
            bad = {l: r for l, r in rep["languages"].items() if r["status"] in ("fail", "error")}
            self.assertEqual(bad, {}, f"{name} {seed_note(self)}")
            self.assertGreaterEqual(len(rep["agreeing_languages"]), 3, (name, rep["languages"]))


if __name__ == "__main__":
    unittest.main()
