"""The card language (CM26): one source for functions, logic, theorems, tests and cards; functions verify
in every available language through the same IR."""
import unittest

from helpers import SEED, TempProject, model_ctx, seed_note

from cardmodel.engines import translate
from cardmodel.engines.ir import Interpreter
from cardmodel.lang import run as R
from cardmodel.lang.compile import CompileError, compile_source
from cardmodel.lang.syntax import CardSyntaxError

SOURCE = """
module demo
fn fib(n: Int) -> Int requires 0 <= n, n <= 60 {
  var a = 0
  var b = 1
  for i in 0 .. n { (a, b) = (b, a + b) }
  return a
}
fn gcd2(a: Int, b: Int) -> Int requires 0 <= a, a <= 1000, 0 <= b, b <= 1000 {
  while b != 0 { (a, b) = (b, a % b) }
  return a
}
fn clamp(x: Int, lo: Int, hi: Int) -> Int requires lo <= hi = if x < lo then lo else if x > hi then hi else x
factorial : Int -> Int = match n with
  | 0 -> 1
  | k -> k * factorial(k - 1)
fn fast(n: Int) -> Int requires 0 <= n, n <= 60 = algorithm.fibonacci(n)
edge(a, b). edge(b, c).
path(X, Y) <- edge(X, Y).
path(X, Z) <- edge(X, Y), path(Y, Z).
theorem clamp_in(x: Int, lo: Int, hi: Int) requires lo <= hi: lo <= clamp(x, lo, hi) and clamp(x, lo, hi) <= hi
theorem add_comm(a: Int, b: Int): a + b == b + a
test fib(20) == 6765
test fast(50) == fib(50)
test factorial(6) == 720
test path(a, c)
test not path(c, a)
card blade : item { damage: 12, tags: [steel, slash] }
"""


class LangTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = model_ctx()
        cls.mod = compile_source(SOURCE, cls.ctx.ops, cls.ctx.store, name="demo")

    def test_module_compiles_to_every_kind(self):
        s = self.mod.summary()
        self.assertIn("fib", s["functions"])
        self.assertIn("alg_fibonacci", s["functions"])           # CL resolve: the algorithm card's form
        self.assertEqual(self.mod.resolved["algorithm/fibonacci"]["form"], "fast_doubling")
        self.assertEqual(s["rules"], 2)
        self.assertEqual(s["cards"], ["item/blade"])
        self.assertEqual(len(self.mod.theorems), 2)

    def test_run_passes(self):
        rep = R.run(self.ctx, self.mod, seed=SEED, samples=80)
        self.assertEqual(rep["status"], "pass", seed_note(self) + str([t for t in rep["tests"] if t["status"] != "pass"]))
        self.assertEqual({t["status"] for t in rep["theorems"]}, {"witnessed"})

    def test_failing_test_fails(self):
        mod = compile_source("fn f(x: Int) -> Int = x + 1\ntest f(1) == 3", self.ctx.ops, self.ctx.store)
        rep = R.run(self.ctx, mod, seed=SEED)
        self.assertEqual(rep["status"], "fail")

    def test_errors_are_precise(self):
        with self.assertRaises(CardSyntaxError) as e:
            compile_source("fn f(x: Int) -> Int {\n  return x +\n}", self.ctx.ops, self.ctx.store)
        self.assertIn("2:", str(e.exception))
        with self.assertRaises(CompileError) as e:
            compile_source("fn f(x: Int) -> Int = x ** x", self.ctx.ops, self.ctx.store)
        self.assertIn("literal exponent", str(e.exception))
        with self.assertRaises(CompileError):
            compile_source("fn f(x: Int) -> Bool = x", self.ctx.ops, self.ctx.store)
        with self.assertRaises(CompileError):
            compile_source("parent(X, bob).", self.ctx.ops, self.ctx.store)        # facts are ground

    def test_machine_state_reads_card_data(self):
        """A constant, and an array's initial values, may come from card fields (the hardware cards' data)."""
        src = ("const LINE = card.hardware.gb_ppu.timing.dots_per_line\n"
               "array pal: Int[4] = card.hardware.gb_cgb.dmg_compat.palettes.bg\n")
        mod = compile_source(src, self.ctx.ops, self.ctx.store)
        bg = self.ctx.store.get("hardware/gb_cgb").get("dmg_compat")["palettes"]["bg"]
        self.assertEqual([a["init"] for a in mod.arrays if a["name"] == "pal"], [bg])
        self.assertEqual(mod.consts["LINE"], 456)
        for bad in ("array p: Int[2] = card.hardware.gb_cgb.dmg_compat.palettes.bg",     # 4 values, size 2
                    "array p: Int[4] = card.hardware.gb_cgb.dmg_compat.statement",       # not a list
                    "array p: Int[4] = card.hardware.gb_cgb.no_such_field",
                    "array p: Int[4] = 3"):
            with self.assertRaises(CompileError, msg=bad):
                compile_source(bad, self.ctx.ops, self.ctx.store)

    def test_ir_is_the_reference(self):
        interp = Interpreter(self.mod.ir_module("factorial"), self.ctx.ops)
        self.assertEqual(interp.call("factorial", [10]), 3628800)
        interp = Interpreter(self.mod.ir_module("clamp"), self.ctx.ops)
        self.assertEqual([interp.call("clamp", [x, 0, 10]) for x in (-5, 5, 50)], [0, 5, 10])

    def test_function_cards_verify_in_languages(self):
        cards = R.function_cards(self.ctx, self.mod, SEED)
        by = {c["name"]: c for c in cards}
        card = by["demo.gcd2"]
        self.assertTrue(card["vectors"])
        res = translate.verify_function(self.ctx, card, langs=["python", "c", "javascript"], seed=SEED)
        self.assertEqual(res["lift_mismatches"], 0)
        for lang, r in res["languages"].items():
            if r["status"] == "unavailable":
                continue
            self.assertEqual(r["status"], "pass", f"{lang}: {r} {seed_note(self)}")
        self.assertGreaterEqual(len(res["agreeing_languages"]), 2)

    def test_build_and_save_cards(self):
        proj = TempProject()
        try:
            ctx = proj.ctx()
            rep = R.run(ctx, self.mod, seed=SEED, samples=60)
            cards = R.build_cards(ctx, self.mod, rep)
            written = R.save_cards(ctx, cards, ctx.store.writable_layer())
            self.assertGreaterEqual(written["function"], 4)
            self.assertIsNotNone(ctx.store.get("logic_rule/demo.path_1"))
            self.assertIsNotNone(ctx.store.get("item/blade"))
            from cardmodel.engines import logic as L
            prog = L.program_from_store(ctx.store, "demo")
            m = L.evaluate(prog, ctx.ops)
            self.assertTrue(m.holds("path", ["a", "c"]))
        finally:
            proj.cleanup()

    def test_cli_run(self):
        proj = TempProject({"m.card": "fn sq(x: Int) -> Int = x * x\ntest sq(12) == 144\n"})
        try:
            r = proj.cli("run", "m.card", "--seed", str(SEED))
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            r = proj.cli("run", "m.card", "--call", "sq", "9")
            self.assertEqual(r.stdout.strip(), "81")
            r = proj.cli("lang", "emit", "m.card", "--lang", "rust")
            self.assertIn("fn sq", r.stdout)
        finally:
            proj.cleanup()


if __name__ == "__main__":
    unittest.main()
