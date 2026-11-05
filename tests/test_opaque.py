"""Failed callees do not fail their callers (SCALING.md §3.3, "partial, not poisoned"): a function that does not lift
is an opaque boundary card, its callers lift as partial with the call edge recorded as a gap, the witness runs the
partial IR through the original Python callee and can fail, and no target is ever claimed for it."""
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

from helpers import model_ctx

from cardmodel.engines import lift_project as LP
from cardmodel.engines import opaque, sweep
from cardmodel.engines.frontend_python import lift_source, module_for

CALLEE = '''
def safe_div(a: int, b: int) -> int:
    try:
        return a // b
    except ZeroDivisionError:
        return 0
'''
CALLERS = '''
def mean_step(x: int, y: int) -> int:
    return safe_div(x * 3, y - 2) + x

def twice(x: int, y: int) -> int:
    return mean_step(x, y) * 2

def ignores(x: int) -> int:
    t = safe_div(x, 3)
    return x + 1
'''
UNRELATED = '''
def sq(x: int) -> int:
    return x * x

def poly(x: int) -> int:
    return sq(x) + 3 * x + 1

def gcd(a: int, b: int) -> int:
    while b != 0:
        a, b = b, a % b
    return a
'''


class SingleFile(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = model_ctx()
        cls.lifted = {lf.name: lf for lf in lift_source(CALLEE + CALLERS + UNRELATED, cls.ctx.ops)}

    def test_the_failed_callee_is_an_opaque_boundary_card(self):
        b = self.lifted["safe_div"]
        self.assertFalse(b.ok)
        self.assertFalse(b.partial)
        card = b.boundary
        self.assertEqual(card["category"], "opaque_boundary")
        self.assertEqual(card["params"], [{"name": "a", "type": "int"}, {"name": "b", "type": "int"}])
        self.assertEqual(card["returns"], "int")
        self.assertIn("Try", card["cause"])
        self.assertEqual(card["host"], "safe_div")
        # a permanent name through the core's identity hash; no Gödel content (no canonical term: syntax, F4)
        from cardmodel.engines.egraph import semantic_hash
        self.assertEqual(card["id"], semantic_hash(["OPAQUE", "safe_div", ["int", "int"], "int", b.source]))
        self.assertIsNone(card["content"])
        self.assertEqual(card["identity"], {"hash": card["id"], "of": "opaque boundary (name, signature, source)",
                                            "under": "syntax"})                  # F5: the identity names its relation
        again = {lf.name: lf for lf in lift_source(CALLEE + CALLERS, self.ctx.ops)}["safe_div"].boundary
        self.assertEqual(again["id"], card["id"])

    def test_a_caller_lifts_with_the_edge_recorded_as_a_gap(self):
        lf = self.lifted["mean_step"]
        self.assertIsNotNone(lf.ir)
        self.assertTrue(lf.partial)
        self.assertFalse(lf.ok, "a partial function is never ok: no target can run it")
        line = CALLERS.splitlines().index("    return safe_div(x * 3, y - 2) + x") + 1 + CALLEE.count("\n")
        self.assertEqual(lf.opaque, {"safe_div": {"line": line, "id": self.lifted["safe_div"].boundary["id"]}})
        self.assertTrue(any("an opaque boundary" in r for r in lf.reasons), lf.reasons)
        # the caller of a partial function is partial through it, with no gap of its own
        up = self.lifted["twice"]
        self.assertTrue(up.partial)
        self.assertEqual(up.opaque, {})
        m = module_for("twice", list(self.lifted.values()), opaque=True)
        self.assertEqual(sorted(f["name"] for f in m["functions"]), ["mean_step", "twice"])
        self.assertEqual([b["name"] for b in m["opaque"]], ["safe_div"])

    def test_no_translation_is_claimed(self):
        with self.assertRaises(KeyError):
            module_for("twice", list(self.lifted.values()))          # what translate and the emitters use
        m = module_for("twice", list(self.lifted.values()), opaque=True)
        self.assertFalse(opaque.targets(m)["runnable"])
        self.assertIn("safe_div", opaque.targets(m)["why"])

    def test_the_witness_runs_the_original_callee_and_passes(self):
        rep = opaque.witness_lifted(self.ctx, "twice", list(self.lifted.values()), seed=11)
        self.assertEqual(rep["status"], "pass", rep)
        self.assertGreater(rep["checks"], 10)
        self.assertGreater(rep["boundaries"]["safe_div"]["calls"], 0)
        self.assertTrue(rep["boundaries"]["safe_div"]["exercised"])
        self.assertFalse(rep["targets"]["runnable"])

    def test_the_witness_catches_a_wrong_host(self):
        m = module_for("twice", list(self.lifted.values()), opaque=True)
        ns: dict = {}
        exec(CALLEE + CALLERS, ns)
        good = opaque.witness(self.ctx, m, {"safe_div": ns["safe_div"]}, ns["twice"], seed=5)
        self.assertEqual(good["status"], "pass", good)
        bad = opaque.witness(self.ctx, m, {"safe_div": lambda a, b: a // b if b else 1}, ns["twice"], seed=5)
        self.assertEqual(bad["status"], "fail", bad)
        wrong_type = opaque.witness(self.ctx, m, {"safe_div": lambda a, b: 0.5}, ns["twice"], seed=5)
        self.assertEqual(wrong_type["status"], "fail")
        self.assertIn("declares int", wrong_type["mismatch"]["ir_error"])

    def test_an_unused_boundary_is_not_a_pass(self):
        rep = opaque.witness_lifted(self.ctx, "ignores", list(self.lifted.values()), seed=2)
        self.assertEqual(rep["status"], "unexercised")
        self.assertFalse(rep["boundaries"]["safe_div"]["exercised"])

    def test_unrelated_lifts_are_unchanged(self):
        alone = {lf.name: lf for lf in lift_source(UNRELATED, self.ctx.ops)}
        for name, lf in alone.items():
            self.assertTrue(lf.ok)
            self.assertTrue(self.lifted[name].ok)
            self.assertFalse(self.lifted[name].partial)
            self.assertEqual(self.lifted[name].ir, lf.ir)


class NotABoundary(unittest.TestCase):
    def test_a_callee_without_a_declared_result_still_fails_its_callers(self):
        src = "def g(x: int):\n    print(x)\n    return x\n\ndef f(x: int) -> int:\n    return g(x) + 1\n"
        by = {lf.name: lf for lf in lift_source(src, model_ctx().ops)}
        self.assertNotIn("host", by["g"].boundary)       # a boundary card (#51), but not host-callable
        self.assertFalse(by["f"].ok or by["f"].partial)
        self.assertEqual([g["callee"] for g in by["f"].gaps], ["g"])
        self.assertIn("calls g which did not lift", by["f"].reasons)

    def test_a_mutated_list_argument_is_a_mismatch_not_an_agreement(self):
        src = ("def bump(xs: list[int]) -> int:\n    xs.append(1)\n    return 0\n\n"
               "def size_after(xs: list[int]) -> int:\n    n = bump(xs)\n    return n + len(xs)\n")
        ctx = model_ctx()
        lifted = lift_source(src, ctx.ops)
        by = {lf.name: lf for lf in lifted}
        self.assertTrue(by["size_after"].partial, by["size_after"].reasons)
        rep = opaque.witness_lifted(ctx, "size_after", lifted, seed=1)
        self.assertEqual(rep["status"], "fail", rep)


class Project(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        cls.pkg = f"opq_{uuid.uuid4().hex[:8]}"
        files = {
            f"{cls.pkg}/__init__.py": "",
            f"{cls.pkg}/low.py": CALLEE + (
                "class K:\n"
                "    @staticmethod\n    def clamp(x: int) -> int:\n        try:\n            return min(x, 9)\n"
                "        except ValueError:\n            return 0\n\n"
                "    def st(self, x: int) -> int:\n        return self.k + x\n\n"
                "    def via(self, x: int) -> int:\n        return self.st(x) + 1\n"),
            f"{cls.pkg}/high.py": (
                "from .low import safe_div, K\n\n"
                "def h(x: int, y: int) -> int:\n    return safe_div(x, y) + K.clamp(x)\n\n"
                "def clean(x: int) -> int:\n    return x + 1\n"),
        }
        for rel, text in files.items():
            p = cls.root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
        cls.ctx = model_ctx()
        cls.res = LP.lift_tree(cls.ctx, cls.root)

    @classmethod
    def tearDownClass(cls):
        for m in [m for m in sys.modules if m.startswith(cls.pkg)]:
            del sys.modules[m]
        cls.tmp.cleanup()

    def test_a_cross_module_caller_lifts_against_boundaries(self):
        lf = self.res.functions[f"{self.pkg}.high::h"]
        self.assertTrue(lf.partial, lf.reasons)
        self.assertEqual(set(lf.opaque), {f"{self.pkg}.low::safe_div", f"{self.pkg}.low::K_clamp"})
        m = self.res.module_for(f"{self.pkg}.high::h", opaque=True)
        hosts = {b["host"]: b["module"] for b in m["opaque"]}
        self.assertEqual(hosts, {"safe_div": f"{self.pkg}.low", "K.clamp": f"{self.pkg}.low"})
        self.assertTrue(self.res.functions[f"{self.pkg}.high::clean"].ok)

    def test_an_instance_method_is_not_a_boundary(self):
        lf = self.res.functions[f"{self.pkg}.low::K_via"]
        self.assertFalse(lf.ok or lf.partial)
        self.assertNotIn("host", self.res.functions[f"{self.pkg}.low::K_st"].boundary)

    def test_the_project_witness_imports_the_originals(self):
        rep = opaque.witness_project(self.ctx, self.res, f"{self.pkg}.high::h", self.root, seed=4)
        self.assertEqual(rep["status"], "pass", rep)

    def test_sweep_reports_both_rates(self):
        rep = sweep.sweep(self.ctx, self.root)
        self.assertEqual(rep["host_partial"], 1)
        self.assertEqual(rep["partial"], 2)                 # #51: every lifted body with gaps (K_via too)
        self.assertEqual(rep["closed_with_boundaries"], rep["closed"] + 1)
        self.assertGreater(rep["rate_with_boundaries"], rep["closed_rate"])
        self.assertEqual(rep["boundaries_reached"], 2)
        self.assertIn("host-partial", sweep.report_text(rep))


if __name__ == "__main__":
    unittest.main()
