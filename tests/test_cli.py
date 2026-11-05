"""The CLI from a project folder: every command runs and reports honestly."""
import json
import unittest

from helpers import SEED, TempProject

SRC = {"lib/calc.py": "def tri(n: int) -> int:\n    t = 0\n    for i in range(n):\n        t += i\n    return t\n\n"
                      "def scale(x: int) -> int:\n    return x * 2 + 0\n\ndef bad(xs: list) -> int:\n    return 0\n"}


class CLI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = TempProject(SRC)

    @classmethod
    def tearDownClass(cls):
        cls.p.cleanup()

    def run_ok(self, *args, code=0):
        r = self.p.cli(*args)
        self.assertEqual(r.returncode, code, (args, r.stdout[-2000:], r.stderr[-2000:]))
        return r.stdout

    def test_distill_sorts_and_parse_errors(self):
        r = self.p.cli("distill", "expr:(a+")
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("error: cannot parse expression:", r.stderr)
        self.assertNotIn("Traceback", r.stderr)
        out = self.run_ok("distill", "(a+b)+c", "a+(b+c)", "--seed", str(SEED))
        self.assertIn("equal under laws at sorts {a: int, b: int, c: int}", out)
        out = self.run_ok("distill", "(a+b)+c", "a+(b+c)", "--seed", str(SEED), "--sort", "float", code=1)
        self.assertIn("not shown equal at sorts {a: float, b: float, c: float}", out)
        out = self.run_ok("distill", "(a+b)+c", "a+(b+c)", "--seed", str(SEED), "--var", "a:float", code=1)
        self.assertIn("a: float, b: int", out)
        self.assertEqual(json.loads(self.run_ok("--json", "distill", "a+b"))["var_sorts"], {"a": "int", "b": "int"})

    def test_commands(self):
        out = self.run_ok("init")
        self.assertIn(".cardmodel", out)
        self.assertIn("layers", self.run_ok("status"))
        out = json.loads(self.run_ok("--json", "observe", "lib", "--save"))
        self.assertEqual(out["totals"]["functions_liftable"], 2)
        self.assertIn("seed", self.run_ok("verify", "--quick", "--seed", str(SEED), "--samples", "8"))
        self.assertIn("Goals", self.run_ok("cover"))
        self.assertIn("pow2_bit", self.run_ok("rewrite", "op/MOD", "--domain", "int"))
        self.assertIn("binomial_square_expand", self.run_ok("rewrite", "--prove", "(a + b) ** 2",
                                                            "a ** 2 + 2 * (a * b) + b ** 2"))
        self.run_ok("rewrite", "--prove", "a + b", "a - b", "--depth", "3", code=1)
        self.assertIn("(x << 1)", self.run_ok("rewrite", "--optimize", "x * 2 + 0"))
        self.assertIn("c25519", self.run_ok("rewrite", "--rank", "cipher_suite", "--weights", "sig_bytes=1"))
        c = self.run_ok("emit", "--lang", "c", "lib/calc.py")
        self.assertIn("static int64_t tri(int64_t n)", c)
        self.assertIn("not lifted", c)
        self.assertIn("cm_floormod", self.run_ok("emit", "--hints", "op/MOD"))
        self.assertIn("theorem cm_binomial_square_expand", self.run_ok("emit", "--rules"))
        out = self.run_ok("translate", "lib/calc.py", "--to", "python,javascript,c", "--seed", str(SEED))
        self.assertIn("tri", out)
        self.assertIn("agrees in 4", out)
        out = self.run_ok("learn", "lib", "--promote", "--langs", "python,javascript,c", "--seed", str(SEED))
        self.assertIn("promoted", out)
        self.assertIn("metric cards written", self.run_ok("optimize", "--card", "op/ADD", "--seed", str(SEED)))
        self.assertIn('"name": "ADD"', self.run_ok("show", "op/ADD"))
        self.assertIn("op", self.run_ok("list"))
        self.assertIn("python", self.run_ok("probe"))
        self.assertIn("created", self.run_ok("new", "widget", "w1", "--statement", "a widget"))
        self.run_ok("show", "nope/none", code=2)
        self.run_ok("observe", "does-not-exist", code=2)


if __name__ == "__main__":
    unittest.main()
