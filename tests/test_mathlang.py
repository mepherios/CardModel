"""Mathematical notation as a language: math -> card IR -> every target, and card IR -> math (round trip)."""
import random
import unittest

from helpers import ROOT, SEED, model_ctx, seed_note

from cardmodel.engines import mathlang as M
from cardmodel.engines import translate
from cardmodel.engines import values as V
from cardmodel.engines.codegen import EmitGap
from cardmodel.engines.frontend_python import lift_source, module_for
from cardmodel.engines.ir import Interpreter

BASICS = r"""
T : ℕ → ℕ
T(n) = ⌊n(n + 1)/2⌋
half(n) = n(n + 1)/2

gcd(a, b) = |a|                if b = 0
          = gcd(b, a mod b)    otherwise

fact(0) = 1
fact(n) = n · fact(n − 1)

s(n) = Σ_{i=1}^{n} i²
p(n) = Π_{k=1}^{n} (2k − 1)
h(x) = y² + 1  where y = x + 1
f(x) = { x if x ≥ 0; −x otherwise }
g(x) = \frac{\sqrt{x^{2} + 1}}{2} + \sin x
q(n) = \begin{cases} 1 & n = 0 \\ n \cdot q(n-1) & \text{otherwise} \end{cases}
c(a, b) = if 0 ≤ a < b ∧ ¬(a = 3) then a else b
r(x) = 2x³ − 3x + π
test T(4) = 10
test half(4) = 10.0
test gcd(12, 18) = 6
test fact(5) = 120
test s(3) = 14
test p(3) = 15
test h(2) = 10
test f(-3) = 3
test q(4) = 24
test c(1, 5) = 1
test c(3, 5) = 5
"""

PY = '''
def collatz(n: int) -> int:
    steps = 0
    while n > 1:
        if n % 2 == 0:
            n = n // 2
        else:
            n = 3 * n + 1
        steps += 1
    return steps

def nested(n: int) -> int:
    count = 0
    for i in range(n):
        for j in range(i):
            if (i + j) % 3 == 0:
                continue
            if j > 7:
                break
            count += i ^ j
    return count

def mix(a: int, x: float) -> float:
    return a * x + a / 3 - float(a) * 0.5
'''


class MathLanguageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = model_ctx()

    def lift(self, text):
        return M.lift_text(text, self.ctx.ops)

    def call(self, module, name, *args):
        return Interpreter(module, self.ctx.ops).call(name, list(args))

    def test_notation_lifts_and_tests_pass(self):
        m = self.lift(BASICS)
        res = M.run_tests(m, self.ctx.ops)
        self.assertEqual([r for r in res if not r["ok"]], [])
        types = {f["name"]: f["returns"] for f in m["functions"]}
        self.assertEqual(types["T"], "int")
        self.assertEqual(types["half"], "float")        # / is real division
        self.assertEqual(types["g"], "float")
        self.assertAlmostEqual(self.call(m, "r", 2), 2 * 8 - 6 + 3.141592653589793)

    def test_nat_signature_is_a_domain(self):
        fn = next(f for f in self.lift(BASICS)["functions"] if f["name"] == "T")
        self.assertEqual(fn["nat_params"], ["n"])
        self.assertIn(["CMP_GE", ["var", "n"], ["int", 0]], fn["requires"])

    def test_tail_recursion_becomes_a_loop(self):
        m = self.lift("gcd(a, b) = |a| if b = 0\n = gcd(b, a mod b) otherwise\n")
        fn = m["functions"][0]
        self.assertFalse(any(e[0] == "CALL" for s in M._stmts(fn["body"]) for k in ("value", "cond")
                             if isinstance(s.get(k), list) for e in M._walk(s[k])))
        # deep enough that recursion would exceed the interpreter's call depth
        self.assertEqual(self.call(m, "gcd", 2 ** 3000 + 1, 2 ** 2999 + 7),
                         __import__("math").gcd(2 ** 3000 + 1, 2 ** 2999 + 7))

    def test_errors_are_precise(self):
        for text, want in [("f(x) = x if x > 0\n", "otherwise"),
                           ("T : ℤ → ℤ\nT(n) = n/2\n", "⌊a/b⌋"),
                           ("f(x) = y + 1\n", "'y'"),
                           ("f(x) = 2.0 mod 3\n", "mod"),
                           ("f(x) = \\foo{x}\n", "subset")]:
            with self.assertRaises(M.MathError) as cm:
                self.lift(text)
            self.assertIn(want, str(cm.exception))

    def test_emitted_equations_read_like_math(self):
        lifted = lift_source(PY, self.ctx.ops)
        text = M.emit_module(module_for("collatz", lifted))
        self.assertIn("collatz : ℤ → ℤ", text)
        self.assertIn("collatz_loop1(n, steps)", text)
        self.assertIn("⌊n / 2⌋", text)
        tex = M.emit_module(module_for("collatz", lifted), latex=True)
        self.assertIn(r"\begin{cases}", tex)

    def round_trips(self, module, name, latex=False):
        fn = next(f for f in module["functions"] if f["name"] == name)
        gens = [translate._gen_for(p["name"], p["type"], 1) for p in fn["params"]]
        rng = random.Random(SEED)
        inputs = [list(a) for a in V.inputs(gens, 24, rng)]
        if not latex:
            r = M.round_trip(self.ctx, {"entry": name, "functions": module["functions"]}, inputs)
            self.assertEqual(r["status"], "pass", f"{name}: {r} {seed_note(self)}")
            return
        back = self.lift(M.emit_module({"entry": name, "functions": module["functions"]}, latex=True))
        for a in inputs:
            try:
                want = self.call(module, name, *a)
            except Exception:  # noqa: BLE001 -- outside the domain
                continue
            self.assertTrue(V.same(want, self.call(back, name, *a)), f"{name}{a} {seed_note(self)}")

    def test_round_trip_python_through_math_and_latex(self):
        lifted = lift_source(PY, self.ctx.ops)
        for lf in lifted:
            self.assertTrue(lf.ok, lf.reasons)
            m = module_for(lf.name, lifted)
            self.round_trips(m, lf.name)
            self.round_trips(m, lf.name, latex=True)

    def test_round_trip_examples(self):
        src = (ROOT / "examples/algorithms/algos.py").read_text(encoding="utf-8")
        lifted = lift_source(src, self.ctx.ops)
        n = 0
        for lf in lifted:
            if lf.ok:
                self.round_trips(module_for(lf.name, lifted), lf.name)
                n += 1
        self.assertGreaterEqual(n, 15)

    def test_round_trip_math_source(self):
        m = self.lift(BASICS)
        for f in m["functions"]:
            self.round_trips(m, f["name"])

    def test_machine_state_is_a_gap(self):
        mod = {"entry": "f", "globals": [{"name": "g", "type": "int", "init": 0}],
               "functions": [{"name": "f", "params": [], "returns": "int", "locals": {},
                              "body": [{"k": "return", "value": ["var", "g"]}]}]}
        with self.assertRaises(EmitGap):
            M.emit_module(mod)

    def test_math_translates_to_native_targets(self):
        import tempfile
        from pathlib import Path
        d = Path(tempfile.mkdtemp(prefix="cardmodel_math_"))
        (d / "m.math").write_text("gcd(a, b) = |a| if b = 0\n = gcd(b, a mod b) otherwise\n"
                                  "s(n) = Σ_{i=1}^{n} i² for 0 ≤ n ≤ 30\n", encoding="utf-8")
        cards, gaps = M.function_cards(self.ctx, d / "m.math", SEED)
        self.assertEqual(gaps, {})
        langs = [t for t in ("python", "c", "javascript") if self.ctx.available(t)[0]]
        for card in cards:
            self.assertTrue(card["vectors"])
            rep = translate.verify_function(self.ctx, card, langs=langs, seed=SEED)
            for lang in langs:
                self.assertEqual(rep["languages"][lang]["status"], "pass", f"{lang}: {rep['languages'][lang]} "
                                                                           f"{seed_note(self)}")


if __name__ == "__main__":
    unittest.main()
