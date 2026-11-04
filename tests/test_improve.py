"""improve: verified algorithm substitution, affine matching, rewrites, the effect boundary (CM21) and
self-correction (CM22)."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from helpers import SEED, model_ctx, seed_note

from cardmodel.engines import improve

SENTINEL = Path(tempfile.gettempdir()) / f"cardmodel_improve_sentinel_{SEED}"

SLOW = f'''"""module under test"""
import json
import socket

open({str(SENTINEL)!r}, "w").write("module-level code ran")


def fib(n: int) -> int:
    if n < 2:
        return n
    return fib(n - 1) + fib(n - 2)


def xp(level: int) -> int:
    total = 0
    for i in range(1, level + 1):
        total += i * i * 10
    return total


def looks_prime(n: int) -> bool:
    if n < 2:
        return False
    for d in range(2, n):
        if n % d == 0:
            return d > 7
    return True


def closed(n: int) -> int:
    return n * (n + 1) // 2


def login(user, password):
    s = socket.create_connection(("example.invalid", 443))
    s.send(json.dumps({{"u": user, "p": password}}).encode())
    return s


SETTINGS = {{"server": "example.invalid"}}
'''


class Improve(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        SENTINEL.unlink(missing_ok=True)
        cls.ctx = model_ctx()
        cls.rep = improve.improve_source(cls.ctx, SLOW, "slow.py", seed=SEED, samples=16, native=False)

    def test_substitution_verified_and_faster(self):
        f = self.rep["functions"]["fib"]
        self.assertTrue(f["action"].startswith("algorithm:algorithm/fibonacci#"), (f, seed_note(self)))
        self.assertGreater(f["speedup"], 10)
        self.assertGreaterEqual(f["checks"], 8)
        self.assertEqual(self.rep["end_to_end"]["status"], "pass")
        self.assertIn("if n >= 0:", f["new_source"])                    # guarded by the card's precondition
        self.assertIn("def fib__original(", f["new_source"])            # the original still runs elsewhere

    def test_affine_match(self):
        f = self.rep["functions"]["xp"]
        # 10 * sum of squares is matched as an affine use of the algorithm card; the function algebra's polynomial
        # closed form is an equally verified candidate, and whichever measures faster on this machine is used
        affine = [c for c in f["candidates"] if c["kind"] == "algorithm_affine"
                  and c["card"] == "algorithm/sum_of_squares"]
        self.assertEqual([(c["scale"], c["shift"]) for c in affine], [(10, 0)], (f, seed_note(self)))
        self.assertTrue(f["action"].startswith(("algorithm_affine:algorithm/sum_of_squares#", "algebra:")),
                        (f, seed_note(self)))
        if f["action"].startswith("algorithm_affine:"):
            self.assertIn("10 * xp__sum_of_squares", f["new_source"])

    def test_decoy_and_lookalike_not_substituted(self):
        self.assertEqual(self.rep["functions"]["looks_prime"]["action"], "kept", seed_note(self))
        # n*(n+1)//2 differs from the 0-for-negative card on negative n: wide inputs must catch that
        self.assertEqual(self.rep["functions"]["closed"]["action"], "kept", seed_note(self))

    def test_effect_shell_is_byte_identical(self):
        out = self.rep["optimized_source"]
        self.assertTrue(self.rep["effect_shell_identical"])
        for chunk in ('def login(user, password):\n    s = socket.create_connection(("example.invalid", 443))',
                      'SETTINGS = {"server": "example.invalid"}', "import socket", f"open({str(SENTINEL)!r}"):
            self.assertIn(chunk, out)
        self.assertEqual([e["name"] for e in self.rep["effect_shell"]], ["login"])
        self.assertFalse(SENTINEL.exists(), "module-level code must never be executed by the optimizer")

    def test_refuted_substitution_is_reverted(self):
        calls = {"n": 0}
        real = improve.end_to_end

        def first_refutes(ctx, source, optimized, changed, seed):
            calls["n"] += 1
            if calls["n"] == 1 and changed:
                return {"status": "fail", "checks": 1, "mismatches": {changed[0]: {"args": [3], "expected": 2,
                                                                                    "got": 3}}}
            return real(ctx, source, optimized, changed, seed)

        src = "def tri(n: int) -> int:\n    t = 0\n    for i in range(n):\n        t += i\n    return t\n"
        with mock.patch.object(improve, "end_to_end", side_effect=first_refutes):
            rep = improve.improve_source(self.ctx, src, "t.py", seed=SEED, samples=12, native=False)
        f = rep["functions"]["tri"]
        self.assertEqual(f["action"], "kept")
        self.assertIn("reverted", f["reason"])
        self.assertIn("tri", rep["reverted"])
        self.assertEqual(rep["optimized_source"], src)               # back to the original, byte for byte
        self.assertGreaterEqual(calls["n"], 2)

    def test_native_forms_for_every_language(self):
        rep = improve.improve_source(self.ctx, "def tri(n: int) -> int:\n    t = 0\n    for i in range(n):\n"
                                               "        t += i\n    return t\n", "t.py", seed=SEED, samples=12)
        nat = rep["native"]
        self.assertIn("c", nat)
        self.assertIn("tri", nat["c"]["source"])
        self.assertEqual(nat["rust"]["gaps"], [])


if __name__ == "__main__":
    unittest.main()


class EGraphRewrites(unittest.TestCase):
    """The e-graph reaches cheaper forms than the depth-3 rule search, and improve offers both as candidates."""

    def test_egraph_finds_what_the_bounded_search_misses(self):
        from cardmodel.engines.egraph import rules_from_cards
        from cardmodel.engines.exprs import parse
        from cardmodel.engines.improve import cheapest_rewrite
        from cardmodel.engines.search import load_rules, op_costs
        ctx = model_ctx()
        rules, costs, eg = load_rules(ctx.store), op_costs(ctx.store), rules_from_cards(ctx.store)
        e = parse("((-(-n)) * 1) + 0")
        alone = cheapest_rewrite(e, rules, costs)
        both = cheapest_rewrite(e, rules, costs, eg)
        self.assertEqual(both[2], ["var", "n"])
        self.assertNotEqual(alone[2], ["var", "n"], "the bounded search alone stops short (depth 3)")
        self.assertTrue(any(s.startswith("egraph:") for s in both[3]))
        self.assertIsNone(cheapest_rewrite(parse("n"), rules, costs, eg), "nothing cheaper than a variable")

    def test_improve_offers_the_egraph_candidate(self):
        src = "def f(n: int) -> int:\n    return ((-(-n)) * 1) + 0\n"
        rep = improve.improve_source(model_ctx(), src, seed=SEED, native=False)
        forms = {c.get("form") for c in rep["functions"]["f"].get("candidates", []) if c["kind"] == "rewrite"}
        self.assertIn("egraph", forms, rep["functions"]["f"])


class NativeCall(unittest.TestCase):
    """E3: a loop-heavy function calls its compiled C form through ctypes inside the verified box, Python outside
    it, and the module still works without the library."""

    SRC = ("def collatz(n: int) -> int:\n    steps = 0\n    while n > 1:\n        if n % 2 == 0:\n"
           "            n = n // 2\n        else:\n            n = 3 * n + 1\n        steps += 1\n    return steps\n")

    def test_native_candidate_is_verified_and_falls_back(self):
        from cardmodel.engines import native
        if native.compiler() is None:
            self.skipTest("no C compiler")
        rep = improve.improve_source(model_ctx(), self.SRC, seed=SEED, native=False, native_call=True)
        f = rep["functions"]["collatz"]
        kinds = {c["kind"]: c for c in f["candidates"]}
        self.assertIn("native", kinds, f)
        self.assertNotIn("rejected", kinds["native"], kinds["native"])
        self.assertEqual(rep["end_to_end"]["status"], "pass" if rep["changed"] else "nothing_changed")
        ns = improve._load(rep["optimized_source"])
        orig = improve._load(self.SRC)
        for n in (1, 7, 27, 97, 10 ** 30):       # 10**30 is outside the box (and 64 bits): Python answers
            self.assertEqual(ns["collatz"](n), orig["collatz"](n), (n, seed_note(self)))
        if f.get("native_lib"):
            self.assertEqual(f["action"], "native:language/c#ctypes")
            with tempfile.TemporaryDirectory() as d:
                written = improve.write_outputs(rep, Path(d), "m")
                self.assertTrue(any(p.suffix == ".so" for p in written))

    def test_wrapper_without_library_stays_python(self):
        from cardmodel.engines import native
        fn_ir = {"name": "collatz", "params": [{"name": "n", "type": "int"}], "returns": "int"}
        src = native.wrapper_source(fn_ir, Path("/nonexistent/libcm_x.so"), [(0, 100)], self.SRC, improve.rename)
        ns = improve._load(src)
        self.assertEqual(ns["collatz"](27), 111)
        self.assertIsNone(ns["_cm_native_collatz"]())
