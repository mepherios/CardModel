"""The language-pair matrix: every source x every target, round trips, cross-source ports (ROADMAP D2, D3)."""
import tempfile
import unittest
from pathlib import Path

from helpers import ROOT, SEED, SLOW, model_ctx, seed_note

from cardmodel.engines import matrix as M
from cardmodel.engines import translate
from cardmodel.engines.frontend_python import lift_source

PY = '''
from math import gcd

def g(a: int, b: int) -> int:
    return gcd(a, b) + a // 3

def h(n: int) -> int:
    t = 0
    for i in range(n):
        t += i % 5
    return t
'''

CARD = '''module ports
fn g(a: Int, b: Int) -> Int = gcd(a, b) + a // 3
fn h(n: Int) -> Int requires 0 <= n, n <= 30 {
  var t = 0
  for i in 0 .. n { t += i % 5 }
  return t
}
'''

WRONG = '''module ports
fn g(a: Int, b: Int) -> Int = gcd(a, b) + a % 3
'''


def _files(card_src: str) -> list[Path]:
    d = Path(tempfile.mkdtemp(prefix="cardmodel_matrix_"))
    (d / "ports.py").write_text(PY, encoding="utf-8")
    (d / "ports.card").write_text(card_src, encoding="utf-8")
    return [d / "ports.py", d / "ports.card"]


class MatrixTest(unittest.TestCase):
    def setUp(self):
        self.ctx = model_ctx()
        self.targets = None if SLOW else [t for t in ("python", "javascript", "c") if self.ctx.available(t)[0]]

    def test_frontends_on_main_are_registered(self):
        self.assertIn("python", M.FRONTENDS)
        self.assertIn("cardlang", M.FRONTENDS)
        self.assertEqual(M.frontend_for(Path("x.card")).lang, "cardlang")
        self.assertIsNone(M.frontend_for(Path("x.unknown")))

    def test_bare_gcd_reference_is_verified_on_inputs(self):
        # a bare gcd(...) lifts; the reference must define it, or every input is silently dropped
        lifted = lift_source(PY, self.ctx.ops)
        card = translate.function_card(self.ctx, "g", lifted, "ports.py", seed=SEED)
        self.assertGreater(len(card["vectors"]), 0, seed_note(self))

    def test_pairs_round_trips_and_ports(self):
        rep = M.run(self.ctx, _files(CARD), targets=self.targets, seed=SEED)
        self.assertEqual(rep["sources"], ["cardlang", "python"])
        self.assertEqual(rep["failures"], [], seed_note(self))
        for f in rep["functions"]:
            self.assertGreater(f["inputs"], 0)
        self.assertEqual({(c["function"], c["status"]) for c in rep["cross_source"]}, {("g", "pass"), ("h", "pass")})
        # the ports are the same function up to names: one identity decides each pair with no run (FOUNDATIONS D7),
        # and the second port of each takes the cells and round trips of the first; its own lift is still checked
        self.assertEqual({c["function"]: c.get("by") for c in rep["cross_source"]}, {"g": "identity", "h": "identity"})
        self.assertEqual({f["function"]: f["same_as"] for f in rep["functions"] if f["same_as"]},
                         {"g": "python:g", "h": "python:h"})
        self.assertEqual(M.by_identity(rep), {"functions": 2, "cells": 2 * len(rep["targets"]), "cross_source": 2})
        self.assertTrue(all(c.get("by") == "identity" for f in rep["functions"] if f["same_as"]
                            for c in [*f["targets"].values(), *f["round_trip"].values()]))
        self.assertIn("by identity", M.report_text(rep))
        self.assertIn("2 by identity", M.markdown(rep))
        if "python" in (self.targets or ["python"]):
            self.assertTrue(all(c["status"] == "pass" for f in rep["functions"] for c in f["round_trip"].values()))
        self.assertIn("python", M.report_text(rep))
        self.assertIn("| source \\ target |", M.markdown(rep))
        # every function records the atoms each target has no template for, read from the carry maps: a target
        # with such atoms is a gap cell, never run (docs/GODEL_AUDIT.md §4.1, step 3)
        for f in rep["functions"]:
            self.assertIn("gaps", f)
            for t, atoms in f["gaps"].items():
                self.assertTrue(atoms and f["targets"][t]["status"] == "gap", (f["function"], t, atoms))

    def test_translation_gaps_are_atoms_of_the_carry_map(self):
        """The gaps are counted by atom from the functions' records (no emission); a gap found only by emitting
        keeps its reason in words."""
        rep = {"functions": [
            {"targets": {"lean": {"status": "gap", "reason": "lean: no template for op/ADD@float,float->float "
                                                            "(predicted from the content)"},
                         "c": {"status": "pass"}},
             "gaps": {"lean": ["op/ADD@float,float->float"]}},
            {"targets": {"lean": {"status": "gap", "reason": "lean: no template for op/ADD@float,float->float, "
                                                            "op/REM@int,int->int (predicted from the content)"},
                         "c": {"status": "gap", "reason": "c: integer constant 1267650600228229401496703205376 does "
                                                         "not fit 64-bit int"}},
             "gaps": {"lean": ["op/ADD@float,float->float", "op/REM@int,int->int"]}}]}
        self.assertEqual(M.translation_gaps(rep), {
            "c": {"integer constant 1267650600228229401496703205376 does not fit 64-bit int": 1},
            "lean": {"op/ADD@float,float->float": 2, "op/REM@int,int->int": 1}})

    def test_ports_that_differ_are_caught(self):
        rep = M.run(self.ctx, _files(WRONG), targets=["python"], seed=SEED)
        kinds = {(f["kind"], f["function"]) for f in rep["failures"]}
        self.assertIn(("cross_source", "g"), kinds, seed_note(self))
        g = next(c for c in rep["cross_source"] if c["function"] == "g")   # different identities: run, not decided
        self.assertEqual((g["status"], g.get("by")), ("fail", None))
        self.assertEqual([f["same_as"] for f in rep["functions"]], [None] * len(rep["functions"]))

    def test_shared_corpus_lifts_in_both_sources(self):
        files = M.default_corpus(ROOT)
        self.assertIn(ROOT / "examples/matrix/corpus.card", files)
        self.assertIn(ROOT / "examples/matrix/corpus.py", files)
        self.assertIn(ROOT / "tests/frontends/algos.go", files)

    def test_same_name_in_unrelated_files_is_not_a_port(self):
        d = Path(tempfile.mkdtemp(prefix="cardmodel_matrix_"))
        (d / "one.py").write_text("def k(a: int) -> int:\n    return a + 1\n", encoding="utf-8")
        (d / "two.card").write_text("module two\nfn k(a: Int) -> Int = a * 2\n", encoding="utf-8")
        rep = M.run(self.ctx, [d / "one.py", d / "two.card"], targets=["python"], seed=SEED)
        self.assertEqual(rep["cross_source"], [])

    def test_domain_edges_give_nan_not_a_crash(self):
        # sqrt/acos/asin outside their domain and fmod by 0: the IR says NaN; Python's math and Ruby's Math raise
        d = Path(tempfile.mkdtemp(prefix="cardmodel_matrix_"))
        (d / "edge.card").write_text(
            "module edge\nfn s(x: Float) -> Float = op.FSQRT(x)\nfn c(x: Float) -> Float = op.ACOS(x)\n"
            "fn m(x: Float) -> Float = op.FMOD(x, 0.0)\n", encoding="utf-8")
        targets = [t for t in ("python", "ruby") if self.ctx.available(t)[0]]
        rep = M.run(self.ctx, [d / "edge.card"], targets=targets, seed=SEED)
        self.assertEqual([f for f in rep["failures"] if f["kind"] == "pair"], [], seed_note(self))
        for f in rep["functions"]:
            for t in targets:
                self.assertEqual(f["targets"][t]["status"], "pass", (f["function"], t, f["targets"][t]))


if __name__ == "__main__":
    unittest.main()
