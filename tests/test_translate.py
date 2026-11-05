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

def uses_list(xs: dict) -> int:
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
        self.assertIn("type annotation 'dict'", lf.reasons[0])
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


# Constructs found in real programs (firstlaw, rea-cards' pheros configs): module constants, numeric defaults,
# keyword calls, math.*, a memoizing decorator, pow with a negative exponent, capitalized parameter names.
REAL = '''
import math
from functools import lru_cache

P = 2**31 - 1
SCALE = 2.5

def addmod(a: int, b: int, m: int = P) -> int:
    return (a + b) % m

def hyp(x: float, y: float) -> float:
    return math.sqrt(x * x + y * y) + math.pi

def floors(x: float) -> int:
    return math.floor(x) + math.ceil(x * SCALE)

@lru_cache(maxsize=None)
def fibm(n: int) -> int:
    a, b = 0, 1
    for _ in range(n):
        a, b = b, addmod(a, b)
    return a

def damp(x: float, k: float = 0.5) -> float:
    return math.exp(-k * x) * math.cos(x)

def caller(x: float) -> float:
    return damp(x) + damp(x, k=2.0) + damp(k=1.0, x=x)

def inv_pow(a: int, b: int, m: int) -> int:
    return pow(a, b, m)

def attack_rate(R_final: float, N: float) -> float:
    return R_final / N if N > 0 else 0.0

def lifetime(M: float) -> float:
    return 1e10 * (1.0 / M) ** 2.5

BIG = 2**255 - 19

def red(a: int) -> int:
    return a % BIG
'''


class RealPrograms(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = model_ctx()
        cls.lifted = lift_source(REAL, cls.ctx.ops)

    def test_everything_lifts(self):
        bad = {lf.name: lf.reasons for lf in self.lifted if not lf.ok}
        self.assertEqual(bad, {})

    def test_defaults_and_keywords_bind_by_name(self):
        ns = {}
        exec(REAL, ns)
        mod = module_for("caller", self.lifted)
        self.assertAlmostEqual(Interpreter(mod, self.ctx.ops).call("caller", [1.5]), ns["caller"](1.5))

    def test_reassigned_or_global_names_are_not_constants(self):
        src = "K = 1\nK = 2\nJ = 3\ndef f(x: int) -> int:\n    return x + K\n" \
              "def g(x: int) -> int:\n    return x + J\ndef h() -> int:\n    global J\n    J = 4\n    return J\n"
        by = {lf.name: lf for lf in lift_source(src, self.ctx.ops)}
        self.assertFalse(by["f"].ok)
        self.assertFalse(by["g"].ok)

    def test_too_wide_constant_is_a_gap_not_a_compile_error(self):
        with self.assertRaises(EmitGap):
            emit_module(self.ctx.store, self.ctx.ops, "c", module_for("red", self.lifted))

    def test_agree_across_languages(self):
        ctx = self.ctx
        langs = None if SLOW else [l for l in ("python", "javascript", "c", "ruby") if ctx.available(l)[0]]
        for name in ("addmod", "hyp", "floors", "fibm", "caller", "inv_pow", "attack_rate", "lifetime"):
            card = translate.function_card(ctx, name, self.lifted, "real.py", seed=SEED)
            self.assertEqual(card["verification"]["lift_fidelity"]["mismatched"], 0, name)
            rep = translate.verify_function(ctx, card, langs=langs, seed=SEED)
            bad = {l: r for l, r in rep["languages"].items() if r["status"] in ("fail", "error")}
            self.assertEqual(bad, {}, f"{name} {seed_note(self)}")


if __name__ == "__main__":
    unittest.main()
