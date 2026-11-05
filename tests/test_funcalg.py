"""Functions as algebra (CM31): canonical forms from behaviour, Gödel numbers, the GCD of functions, and verified
fast forms that carry into improve."""
import unittest

from helpers import SEED, TempProject, model_ctx, seed_note

from cardmodel.engines import funcalg as F
from cardmodel.engines.improve import improve_source


def fib_loop(n):
    a, b = 0, 1
    for _ in range(n):
        a, b = b, a + b
    return a


def lucas(n):
    a, b = 2, 1
    for _ in range(n):
        a, b = b, a + b
    return a


def T(n):
    return n * (n + 1) // 2


def S_loop(n):
    return sum(k * k for k in range(n + 1))


class FuncAlgTest(unittest.TestCase):
    def test_canonical_forms_carry_between_functions(self):
        # behaviour, not code: two implementations, one canonical form, one Gödel number
        closed = F.fit(lambda n: n * (n + 1) * (2 * n + 1) // 6)
        loop = F.fit(S_loop)
        self.assertEqual(closed.code(), loop.code())
        self.assertEqual(closed.godel(), loop.godel())
        self.assertEqual(F.godel_decode(loop.godel()), loop.code())
        # a number that is not a code decodes to its prefix at once, never factoring past the first absent prime
        # (2 * a large prime used to factor the large prime first)
        import time
        t0 = time.monotonic()
        self.assertEqual(F.godel_decode(2 * 1000000007), [0])
        self.assertEqual(F.godel_decode(1), [])
        self.assertLess(time.monotonic() - t0, 1.0)
        # the GCD of functions and what carries
        r = F.gcd_functions(F.fit(T), loop)
        self.assertEqual(r["values"]["common_factor"], "n^2 + n")
        self.assertEqual(r["values"]["cross_identity"], "(2*n + 1) * f(n) == (3) * g(n)")
        fl = F.gcd_functions(F.fit(fib_loop), F.fit(lucas))
        self.assertEqual(fl["operators"]["gcd"], "E^2 - E - 1")              # shared dynamics
        self.assertIn("2*f(n+1)", fl["basis_change"])                         # Lucas = 2 F(n+1) - F(n)
        cubes = F.fit(lambda n: sum(k ** 3 for k in range(n + 1)))
        self.assertEqual(str(F.composition(F.fit(T), cubes)), "Poly(x^2)")    # sum of cubes = T(n)^2
        self.assertEqual(F.shift_relation(F.fit(T), F.fit(lambda n: n * (n - 1) // 2)), -1)
        self.assertEqual(F.fixed_divisor(F.fit(lambda n: n * (n + 1) * (n + 2))), 6)
        self.assertEqual(F.total(F.fit(lambda n: n ** 3)).code(), cubes.code())

    def test_no_form_when_behaviour_is_not_a_recurrence(self):
        primes = [2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47, 53, 59, 61, 67, 71, 73, 79, 83, 89, 97]
        self.assertIsNone(F.fit(lambda n: primes[n]))
        self.assertIsNone(F.fit(lambda n: 1 if n == 0 else n * __import__("math").factorial(n - 1)))

    def test_fast_forms_are_exact(self):
        for fn in (fib_loop, lucas, S_loop, lambda n: 3 ** n - n, lambda n: n * 2 ** n):
            form = F.fit(fn)
            ns = {}
            exec(F.python_source(form, "fast", "n"), ns)  # noqa: S102 -- generated in this test
            self.assertEqual([ns["fast"](n) for n in range(60)], [fn(n) for n in range(60)])
            self.assertEqual(ns["fast"](300), fn(300))

    def test_improve_derives_fast_forms_without_cards(self):
        src = ("def pell(n: int) -> int:\n    a = 0\n    b = 1\n    for _ in range(n):\n        a, b = b, 2 * b + a\n"
               "    return a\n\n\ndef tetra(n: int) -> int:\n    total = 0\n    for i in range(n + 1):\n"
               "        for j in range(i + 1):\n            total += j\n    return total\n\n\n"
               "def log_it(n: int) -> int:\n    print(n)\n    return n\n")
        rep = improve_source(model_ctx(), src, "t.py", seed=SEED, native=False)
        self.assertTrue(rep["functions"]["tetra"]["action"].startswith("algebra:"), seed_note(self))
        self.assertTrue(rep["effect_shell_identical"])
        self.assertEqual(rep["end_to_end"]["status"], "pass")

    def test_algorithm_cards_have_one_number_per_card(self):
        r = F.scan_algorithms(model_ctx())
        self.assertEqual(r["problems"], [])
        self.assertIn("fibonacci", r["forms"])
        self.assertTrue(any(rel.get("composition") for rel in r["relations"]))

    def test_cli(self):
        proj = TempProject()
        try:
            out = proj.cli("algebra", "gcd", "expr:6*n+12", "expr:4*n+8")
            self.assertEqual(out.returncode, 0, out.stderr)
            self.assertIn("common factor n + 2", out.stdout)
            out = proj.cli("algebra", "godel", "2 0 1 1")
            self.assertIn("decodes back to [2, 0, 1, 1]", out.stdout)
        finally:
            proj.cleanup()


if __name__ == "__main__":
    unittest.main()
