"""Lifting at project scale: calls across files and modules resolve, Python methods lift, the closure is linear,
and ``cardmodel lift-sweep`` reports the lift rate with its histogram of first reasons."""
import json
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from helpers import CLI, ROOT, model_ctx

from cardmodel.engines import lift_project as LP
from cardmodel.engines import sweep
from cardmodel.engines.frontend_python import lift_source
from cardmodel.engines.ir import Interpreter


def write(root: Path, files: dict) -> None:
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")


PKG = {
    "pkg/__init__.py": "",
    "pkg/util.py": (
        "def sq(x: int) -> int:\n    return x * x\n\n"
        "def half(x: int):\n    return x / 2\n\n"
        "class M:\n"
        "    @staticmethod\n    def add(a: int, b: int) -> int:\n        return a + b\n\n"
        "    @classmethod\n    def twice(cls, a: int) -> int:\n        return cls.add(a, a)\n\n"
        "    def norm(self, a: int) -> int:\n        return self.twice(a) + 1\n\n"
        "    def state(self, a: int) -> int:\n        return self.k + a\n"),
    "pkg/sub/__init__.py": "",
    "pkg/sub/core.py": (
        "from ..util import sq, M\nfrom .. import util\nimport pkg.util as U\nfrom pkg.util import half as h\n\n"
        "def f(x: int) -> int:\n    return sq(x) + util.sq(x) + U.sq(1) + M.add(x, 2)\n\n"
        "def g(x: int) -> int:\n    return f(x) + 1\n\n"
        "def k(x: int) -> float:\n    return h(x) + 0.5\n\n"
        "def uses_state(x: int) -> int:\n    return U.M.state(x)\n"),
}


class LinearClosure(unittest.TestCase):
    def test_deep_chain_with_a_failed_root_is_linear(self):
        # callers first, the failing root last: the old fixed point spread the failure one function per pass
        # (quadratic: 2,000 functions took ~3 s); the worklist visits each call once
        n = 2000
        src = "".join(f"def f{i}(x: int) -> int:\n    return f{i - 1}(x) + 1\n" for i in range(n - 1, 0, -1))
        # f0 declares its result, so it is an opaque boundary: every caller lifts as partial (SCALING.md §3.3)
        t = time.perf_counter()
        lifted = lift_source(src + "def f0(x: int) -> int:\n    return open(x)\n", model_ctx().ops)
        took = time.perf_counter() - t
        self.assertEqual(sum(lf.ok for lf in lifted), 0)
        self.assertEqual(sum(lf.partial for lf in lifted), n - 1)
        self.assertLess(took, 1.5, f"closure over a {n}-deep chain took {took:.2f} s")
        f1 = next(lf for lf in lifted if lf.name == "f1")
        self.assertEqual(list(f1.opaque), ["f0"])
        # f0 without a declared result cannot be a boundary (callers could not be typed): the failure spreads, linearly
        t = time.perf_counter()
        lifted = lift_source(src + "def f0(x: int):\n    return open(x)\n", model_ctx().ops)
        took = time.perf_counter() - t
        self.assertEqual(sum(lf.ok or lf.partial for lf in lifted), 0)
        self.assertLess(took, 1.5, f"closure over a {n}-deep chain took {took:.2f} s")
        f1 = next(lf for lf in lifted if lf.name == "f1")
        self.assertIn("calls f0 which did not lift", f1.reasons)


class PythonProject(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        write(cls.root, PKG)
        cls.ctx = model_ctx()
        cls.res = LP.lift_tree(cls.ctx, cls.root)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def run_q(self, qual, args):
        m = self.res.module_for(qual)
        return Interpreter(m, self.ctx.ops).call(m["entry"], args)

    def test_imports_resolve_across_modules(self):
        # from-import, relative imports, `import a.b as U`, and a static method of an imported class
        self.assertTrue(self.res.functions["pkg.sub.core::f"].ok, self.res.functions["pkg.sub.core::f"].reasons)
        self.assertEqual(self.run_q("pkg.sub.core::g", [3]), 9 + 9 + 1 + 5 + 1)
        self.assertGreater(self.res.cross_calls, 0)

    def test_callee_return_type_from_its_lift(self):
        # half() has no return annotation: the first round takes int, the second round re-lifts k with float
        lf = self.res.functions["pkg.sub.core::k"]
        self.assertTrue(lf.ok, lf.reasons)
        self.assertEqual(self.run_q("pkg.sub.core::k", [3]), 2.0)

    def test_methods(self):
        fns = self.res.functions
        for name in ("M_add", "M_twice", "M_norm"):
            self.assertTrue(fns[f"pkg.util::{name}"].ok, fns[f"pkg.util::{name}"].reasons)
            self.assertTrue(fns[f"pkg.util::{name}"].method)
        self.assertEqual(self.run_q("pkg.util::M_norm", [4]), 9)
        state = fns["pkg.util::M_state"]
        self.assertFalse(state.ok)
        self.assertIn("self.k", state.reasons[0])

    def test_a_cross_module_caller_of_a_failed_method_fails(self):
        lf = self.res.functions["pkg.sub.core::uses_state"]
        self.assertFalse(lf.ok)
        self.assertIn("did not lift", lf.reasons[-1])

    def test_without_cross_and_methods_is_the_single_file_lift(self):
        res = LP.lift_tree(self.ctx, self.root, methods=False, cross=False)
        self.assertFalse(res.functions["pkg.sub.core::f"].ok)
        self.assertNotIn("pkg.util::M_add", res.functions)
        self.assertTrue(res.functions["pkg.util::sq"].ok)


class TextProject(unittest.TestCase):
    def test_c_links_by_name_and_java_by_class(self):
        files = {
            "a.c": "long sq(long x) { return x * x; }\nlong dup(long x) { return x; }\n",
            "b.c": "long dup(long x) { return x + 0; }\nlong f(long x) { return sq(x) + 1; }\n",
            "c.c": "long h(long x) { return f(x) * 2; }\nlong k(long x) { return dup(x); }\n",
            "Other.java": "public class Other { public static long tw(long x) { return 2 * x; } }\n",
            "Main.java": "public class Main { public static long u(long x) { return Other.tw(x) + 1; } }\n",
        }
        ctx = model_ctx()
        with tempfile.TemporaryDirectory() as d:
            write(Path(d), files)
            res = LP.lift_tree(ctx, d)
        m = res.module_for("c.c::h")
        self.assertEqual(sorted(f["name"] for f in m["functions"]), ["f", "h", "sq"])
        self.assertEqual(Interpreter(m, ctx.ops).call(m["entry"], [3]), 20)
        self.assertFalse(res.functions["c.c::k"].ok)           # dup is defined twice: ambiguous, stays unresolved
        m = res.module_for("Main.java::u")
        self.assertEqual(Interpreter(m, ctx.ops).call(m["entry"], [3]), 7)

    def test_module_for_mangles_colliding_names(self):
        files = {"a.c": "long dup(long x) { return x + 1; }\nlong g(long x) { return dup(x); }\n",
                 "b.c": "long dup(long x) { return x + 2; }\nlong h(long x) { return dup(x) + g(x); }\n"}
        ctx = model_ctx()
        with tempfile.TemporaryDirectory() as d:
            write(Path(d), files)
            res = LP.lift_tree(ctx, d)
        m = res.module_for("b.c::h")
        names = sorted(f["name"] for f in m["functions"])
        self.assertEqual(len(names), len(set(names)), names)
        self.assertEqual(Interpreter(m, ctx.ops).call(m["entry"], [1]), 3 + 2)


class Sweep(unittest.TestCase):
    def test_normalise_groups_reasons(self):
        self.assertEqual(sweep.normalise("line 12: call to foo() is 'x' 3"), "call to foo() is '_' N")
        self.assertEqual(sweep.normalise("calls a::b, c which did not lift"), "calls a function that did not lift")

    def test_cli_report(self):
        with tempfile.TemporaryDirectory() as d:
            write(Path(d), PKG)
            out = subprocess.run([*CLI, "--json", "lift-sweep", d], cwd=ROOT, capture_output=True, text=True,
                                 timeout=300)
            self.assertEqual(out.returncode, 0, out.stderr)
            rep = json.loads(out.stdout)
            single = sweep.sweep(model_ctx(), d, methods=False, project=False)
        self.assertEqual(rep["languages"]["python"]["functions"], rep["functions"])
        self.assertGreater(rep["lifted"], single["lifted"])
        self.assertEqual(rep["kinds"]["method"], 4)
        self.assertTrue(any("instance state" in r for r, _ in rep["reasons"]))


if __name__ == "__main__":
    unittest.main()
