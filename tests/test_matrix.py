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
        if "python" in (self.targets or ["python"]):
            self.assertTrue(all(c["status"] == "pass" for f in rep["functions"] for c in f["round_trip"].values()))
        self.assertIn("python", M.report_text(rep))
        self.assertIn("| source \\ target |", M.markdown(rep))

    def test_ports_that_differ_are_caught(self):
        rep = M.run(self.ctx, _files(WRONG), targets=["python"], seed=SEED)
        kinds = {(f["kind"], f["function"]) for f in rep["failures"]}
        self.assertIn(("cross_source", "g"), kinds, seed_note(self))

    def test_shared_corpus_lifts_in_both_sources(self):
        files = M.default_corpus(ROOT)
        self.assertIn(ROOT / "examples/matrix/corpus.card", files)
        self.assertIn(ROOT / "examples/matrix/corpus.py", files)


if __name__ == "__main__":
    unittest.main()
