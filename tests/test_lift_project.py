"""Lifting at project scale: calls across files and modules resolve, Python methods lift, the closure is linear,
and ``cardmodel lift-sweep`` reports the lift rate with its histogram of first reasons."""
import json
import subprocess
from collections import Counter
import tempfile
import time
import unittest
from pathlib import Path

from helpers import CLI, ROOT, model_ctx

from cardmodel.engines import lift_project as LP
from cardmodel.engines import sweep
from cardmodel.engines.frontend_python import close_calls, lift_source, lift_status
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
        self.assertIn("calls f0 which did not lift", f1.reasons)
        # partial, not poisoned: every caller keeps its IR, only f0 is a boundary, each edge is one gap
        status = Counter(lift_status(lf) for lf in lifted)
        self.assertEqual(status, {"partial": n - 1, "boundary": 1})
        self.assertEqual(f1.gaps, [{"callee": "f0", "kind": "boundary", "cause": f1.gaps[0]["cause"]}])
        self.assertIn("open()", f1.gaps[0]["cause"])
        f2 = next(lf for lf in lifted if lf.name == "f2")
        self.assertEqual([(g["callee"], g["kind"]) for g in f2.gaps], [("f1", "partial")])
        # on top of the gaps (#52): f0 is host-callable, so f1 is partial with an opaque edge to it
        self.assertEqual(list(f1.opaque), ["f0"])
        self.assertEqual(f1.opaque["f0"]["id"], next(lf for lf in lifted if lf.name == "f0").boundary["id"])
        # f0 without a declared result is still a boundary card, but the host cannot be typed against it: no
        # caller is partial (each keeps its gap)
        t = time.perf_counter()
        lifted = lift_source(src + "def f0(x: int):\n    return open(x)\n", model_ctx().ops)
        took = time.perf_counter() - t
        self.assertLess(took, 1.5, f"closure over a {n}-deep chain took {took:.2f} s")
        by = {lf.name: lf for lf in lifted}
        self.assertNotIn("host", by["f0"].boundary)
        self.assertEqual(sum(lf.partial for lf in lifted), 0)
        self.assertEqual(lift_status(by["f1"]), "partial")


class BoundaryCards(unittest.TestCase):
    SRC = ("def bad(x: int) -> int:\n    return open(x)\n\n"
           "def bad_untyped(x):\n    return open(x)\n\n"
           "def caller(x: int) -> int:\n    return bad(x) + bad_untyped(x) + 1\n\n"
           "def clean(x: int) -> int:\n    return x + 1\n")

    def setUp(self):
        self.by = {lf.name: lf for lf in lift_source(self.SRC, model_ctx().ops)}

    def test_failed_function_is_a_boundary_card_with_its_typed_signature(self):
        b = self.by["bad"].boundary
        self.assertEqual(b["signature"], {"params": ["int"], "returns": "int"})
        self.assertIn("open()", b["cause"])
        self.assertEqual(lift_status(self.by["bad"]), "boundary")

    def test_an_untyped_signature_is_not_guessed_onto_the_card(self):
        self.assertIsNone(self.by["bad_untyped"].boundary["signature"])

    def test_the_caller_lifts_and_records_each_edge_as_a_gap(self):
        c = self.by["caller"]
        self.assertEqual(lift_status(c), "partial")
        self.assertFalse(c.ok)                        # not closed: it cannot run or translate alone
        self.assertIsNotNone(c.ir)
        self.assertEqual(sorted(g["callee"] for g in c.gaps), ["bad", "bad_untyped"])
        self.assertEqual(lift_status(self.by["clean"]), "closed")
        self.assertEqual(self.by["clean"].gaps, [])

    def test_closing_twice_adds_no_edges(self):
        results = {lf.name: lf for lf in self.by.values()}
        close_calls(results)
        self.assertEqual(len(results["caller"].gaps), 2)
        self.assertEqual(lift_status(results["bad"]), "boundary")


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

    def test_a_cross_module_caller_of_a_failed_method_lifts_with_a_gap(self):
        lf = self.res.functions["pkg.sub.core::uses_state"]
        self.assertFalse(lf.ok)
        self.assertIn("did not lift", lf.reasons[-1])
        self.assertEqual(lift_status(lf), "partial")
        self.assertEqual([(g["callee"], g["kind"]) for g in lf.gaps], [("pkg.util::M_state", "boundary")])
        card = self.res.boundaries()["pkg.util::M_state"]
        self.assertEqual(card["signature"], {"params": ["int"], "returns": "int"})
        self.assertIn("self.k", card["cause"])
        self.assertEqual(card["gap_edges"], 1)

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


PORTS = {
    "py/game.py": (
        "def distance_sq(a: int, b: int) -> int:\n    return a * a + b * b\n\n"
        "def in_range(a: int, b: int, r: int) -> int:\n    return distance_sq(a, b) + r\n\n"
        "def fact(n: int) -> int:\n    if n <= 1:\n        return 1\n    return n * fact(n - 1)\n\n"
        "def ping(n: int) -> int:\n    if n == 0:\n        return n\n    return pong(n - 1)\n\n"
        "def pong(n: int) -> int:\n    if n == 0:\n        return n + 1\n    return ping(n - 1)\n\n"
        "def acc(n: int) -> int:\n    s = 0\n    i = 0\n    while i < n:\n        s = s + i\n        i = i + 1\n    return s\n\n"
        "def swapped(a: int, b: int) -> int:\n    return b * b + a * a\n\n"
        "def count(n: int) -> int:\n    if n == 0:\n        return 0\n    return count(n - 1) + 2\n"),
    "c/game.c": (
        "long distance_sq(long x, long y) { return x * x + y * y; }\n"
        "long in_range(long x, long y, long r) { return distance_sq(x, y) + r; }\n"
        "long fact(long n) { if (n <= 1) { return 1; } return n * fact(n - 1); }\n"
        "long ping(long n);\n"
        "long pong(long n) { if (n == 0) { return n + 1; } return ping(n - 1); }\n"
        "long ping(long n) { if (n == 0) { return n; } return pong(n - 1); }\n"
        "long acc(long n) { long s = 0; long i = 0; while (i < n) { s = s + i; i = i + 1; } return s; }\n"
        "long count(long n) { if (n == 0) { return 0; } return count(n - 1) + 1; }\n"),
}


class Identity(unittest.TestCase):
    """One identity for lifted functions (FOUNDATIONS D7; docs/GODEL_AUDIT.md §4.1): α-normalised, with each CALL
    target replaced by the callee's identity, so a port in another language or file hashes like the original."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        write(cls.root, PORTS)
        cls.res = LP.lift_tree(model_ctx(), cls.root)
        cls.ids = cls.res.identities()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_ports_share_one_identity_through_their_calls(self):
        self.assertTrue(all(lf.ok for lf in self.res.functions.values()), [q for q, lf in self.res.functions.items() if not lf.ok])
        for name in ("distance_sq", "in_range", "fact", "ping", "pong", "acc"):
            py, c = self.ids[f"py.game::{name}"], self.ids[f"c/game.c::{name}"]
            self.assertEqual(py, c, name)                  # parameter names and the callee's file differ, nothing else
            self.assertTrue(py.startswith("sha256:"), py)
        # 15 functions: the 6 ports collapse to 6, swapped and the two counts stay apart: 9 distinct
        self.assertEqual(len(set(self.ids.values())), 9, sorted(self.ids.items()))
        # the recursion placeholder is the callee's structure, not a name: count differs between the ports (+2, +1)
        self.assertNotEqual(self.ids["py.game::count"], self.ids["c/game.c::count"])
        self.assertNotEqual(self.ids["py.game::ping"], self.ids["py.game::pong"])
        self.assertNotEqual(self.ids["py.game::fact"], self.ids["py.game::count"])

    def test_alpha_renames_by_position_and_first_use(self):
        a = LP.alpha(self.res.functions["py.game::acc"].ir)
        self.assertEqual(a["params"], [{"name": "p0", "type": "int"}])
        self.assertEqual(a["locals"], {"l0": "int", "l1": "int"})
        self.assertEqual(a["body"][0], {"k": "assign", "value": ["int", 0], "target": "l0"})
        self.assertEqual(a, LP.alpha(self.res.functions["c/game.c::acc"].ir))
        # the order of the operands is structure: swapped is not distance_sq
        self.assertNotEqual(self.ids["py.game::swapped"], self.ids["py.game::distance_sq"])
        # a CALL keeps its name when no identity is given for it (a callee that did not lift is a gap of the lift)
        self.assertEqual(LP.alpha(self.res.functions["py.game::in_range"].ir)["body"][0]["value"][1][1],
                         "py.game::distance_sq")
        self.assertEqual(LP.alpha(self.res.functions["py.game::in_range"].ir, {"py.game::distance_sq": "ID"})
                         ["body"][0]["value"][1][1], "ID")

    def test_a_module_has_the_identity_of_its_entry(self):
        # the identity of one IR module (what a function card carries) is the project identity of its entry function:
        # module_for renames the callees to bare names, and names are not structure
        for q in ("py.game::in_range", "c/game.c::ping", "py.game::acc"):
            self.assertEqual(LP.module_identity(self.res.module_for(q)), self.ids[q], q)
        self.assertEqual(LP.identity_record(self.res.module_for("py.game::in_range")),
                         {"hash": self.ids["py.game::in_range"], "of": "lifted function", "under": "alpha"})

    def test_sccs_are_callees_first(self):
        graph = {"a": ["b"], "b": ["c", "a"], "c": [], "d": ["d"], "e": []}
        comps = LP._sccs(graph)
        self.assertEqual(sorted(sorted(c) for c in comps), [["a", "b"], ["c"], ["d"], ["e"]])
        self.assertLess(comps.index(next(c for c in comps if c == ["c"])),
                        comps.index(next(c for c in comps if sorted(c) == ["a", "b"])))
        chain = {f"f{i}": [f"f{i - 1}"] if i else [] for i in range(5000)}
        self.assertEqual(len(LP._sccs(chain)), 5000)       # iterative: a deep chain does not recurse


class Sweep(unittest.TestCase):
    def test_sweep_reports_distinct_functions_by_identity(self):
        with tempfile.TemporaryDirectory() as d:
            write(Path(d), PORTS)
            rep = sweep.sweep(model_ctx(), d)
        self.assertEqual((rep["lifted"], rep["distinct"], rep["copies"]), (15, 9, 6))
        self.assertEqual([c["size"] for c in rep["clusters"]], [2] * 6)
        self.assertIn("by identity: 9 distinct of 15 lifted, 6 copies", sweep.report_text(rep))

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
        # uses_state lifts with a gap to the boundary M.state: counted as lifted, not as closed
        self.assertEqual(rep["lifted"], rep["closed"] + rep["partial"])
        self.assertGreaterEqual(rep["partial"], 1)
        self.assertGreaterEqual(rep["gap_edges"], 1)
        self.assertTrue(any("instance state" in r for r, _ in rep["gap_causes"]))

    def test_calls_within_a_card_or_math_file_resolve_in_a_project_lift(self):
        # these frontends lift one file at a time; their calls inside the file used to read as missing
        res = LP.lift_tree(model_ctx(), ROOT / "examples" / "transformer")
        soft = next(lf for q, lf in res.functions.items() if q.endswith("::softmax"))
        self.assertTrue(soft.ok, soft.reasons)


if __name__ == "__main__":
    unittest.main()
