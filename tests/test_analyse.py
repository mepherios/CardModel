"""The REA analyser (engines/analyse.py): structure facts, logic obligations, divergence laws in the reference, and
behaviour differences witnessed across runners and optimization levels."""
import tempfile
import unittest
from pathlib import Path

from helpers import SEED, model_ctx, seed_note

from cardmodel.engines import analyse as A
from cardmodel.engines import matrix as M

PY = '''
def midpoint(a: int, b: int) -> int:
    return (a + b) // 2

def scale(x: float, y: float) -> float:
    return x / y

def safe_div(a: int, b: int) -> int:
    if b == 0:
        return 0
    return a // b

def bits(a: int, n: int) -> int:
    return a << n
'''

CARD = '''module shapes
fn fact(n: Int) -> Int requires 0 <= n, n <= 20 {
  if n == 0 { return 1 }
  return n * fact(n - 1)
}
fn loop_sum(n: Int, acc: Int) -> Int requires 0 <= n, n <= 50 {
  if n == 0 { return acc }
  return loop_sum(n - 1, acc + n)
}
fn ev(n: Int) -> Bool requires 0 <= n, n <= 50 {
  if n == 0 { return true }
  return od(n - 1)
}
fn od(n: Int) -> Bool requires 0 <= n, n <= 50 {
  if n == 0 { return false }
  return ev(n - 1)
}
'''


def _file(name: str, text: str) -> Path:
    d = Path(tempfile.mkdtemp(prefix="cardmodel_analyse_"))
    p = d / name
    p.write_text(text, encoding="utf-8")
    return p


def _cards(ctx, path):
    cards, gaps = M.frontend_for(path).cards(ctx, path, SEED)
    return {c["ir"]["entry"]: c for c in cards}


class AnalyseTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = model_ctx()
        cls.py = _cards(cls.ctx, _file("latent.py", PY))
        cls.card = _cards(cls.ctx, _file("shapes.card", CARD))

    def test_structure_classifies_recursion(self):
        rec = {n: A.structure(c["ir"])["functions"][n]["recursion"]["value"] for n, c in self.card.items()}
        self.assertEqual(rec["fact"], "general")
        self.assertEqual(rec["loop_sum"], "tail")
        self.assertEqual(rec["ev"], "mutual")
        sig = A.structure(self.card["fact"]["ir"])["functions"]["fact"]["signature"]
        self.assertEqual(sig["value"], "fact : ℤ → ℤ")
        self.assertTrue(sig["via"])                              # every fact names its rule

    def test_obligations_proved_by_guard_or_open_with_counterexample(self):
        safe = A.analyse_card(self.ctx, self.py["safe_div"], run=False, seed=SEED)
        self.assertEqual([o["status"] for o in safe.obligations], ["proved"], seed_note(self))
        scale = A.analyse_card(self.ctx, self.py["scale"], run=False, seed=SEED)
        o = scale.obligations[0]
        self.assertEqual((o["status"], o["needs"]), ("open", "y ≠ 0.0"))
        self.assertEqual(o["counterexample"]["args"][1], 0.0)

    def test_laws_fire_in_the_reference(self):
        laws = {n: {f["law"] for f in A.analyse_card(self.ctx, c, run=False, seed=SEED).findings}
                for n, c in self.py.items()}
        self.assertIn("int_width", laws["midpoint"], seed_note(self))
        self.assertIn("float_div_zero", laws["scale"])
        self.assertIn("shift_count", laws["bits"])
        self.assertNotIn("int_div_zero", laws["safe_div"])       # guarded in the source: no law fires
        fact = A.analyse_card(self.ctx, self.card["fact"], run=False, seed=SEED)
        width = [f for f in fact.findings if f["law"] == "int_width"]
        self.assertTrue(width and not any(f["in_domain"] for f in width))   # 20! fits: outside the domain only

    def test_explain_names_the_law_at_an_input(self):
        why = A.explain(self.ctx, self.py["midpoint"]["ir"], [2 ** 62, 2 ** 62])
        self.assertEqual([w["law"] for w in why], ["int_width"])
        self.assertEqual(why[0]["term"], "a + b")
        self.assertEqual(A.explain(self.ctx, self.py["midpoint"]["ir"], [3, 5]), [])

    def test_runners_include_optimization_levels(self):
        names = {r[0] for r in A.runners(self.ctx, ["c", "rust"])}
        if self.ctx.available("c")[0]:
            self.assertTrue({"c@O0", "c@O2", "c@ubsan", "c@fastmath"} <= names)
            card = next(r[2] for r in A.runners(self.ctx, ["c@O0"]))
            self.assertIn("-O0", card["runner"]["compile"])
        if self.ctx.available("rust")[0]:
            self.assertTrue({"rust@debug", "rust@release"} <= names)

    def test_overflow_is_witnessed_across_runners(self):
        want = [r for r in ("python", "c@O0", "java", "javascript") if self.ctx.available(r.split("@")[0])[0]]
        if not any(r.startswith(("c", "java@")) or r == "java" for r in want):
            self.skipTest("no fixed-width runner on this machine")
        a = A.analyse_card(self.ctx, self.py["midpoint"], run=True, seed=SEED, pool=A.runners(self.ctx, want))
        width = next(f for f in a.findings if f["law"] == "int_width")
        self.assertEqual(width["verdict"], "witnessed", seed_note(self))
        self.assertTrue(width["in_domain"])                      # a Python int has no bound: a latent flaw
        fixed = {r for r in want if r.split("@")[0] in ("c", "java")}
        self.assertTrue(fixed <= set(width["differs"]))
        for exact in ("python", "javascript"):
            if exact in want:
                self.assertIn(exact, width["agrees"])
        self.assertTrue(all(width["why"][n] for n in width["differs"]))

    def test_matrix_failures_are_explained(self):
        card = self.py["midpoint"]
        fails = [{"kind": "pair", "source": "python", "target": "c", "function": "midpoint",
                  "detail": {"status": "fail", "args": [2 ** 62, 2 ** 62]}}]
        M.explain_failures(self.ctx, fails, {"python": {"midpoint": card}})
        self.assertEqual(fails[0]["explanation"], ["int_width at a + b"])

    def test_cli_report(self):
        rep = A.analyse_files(self.ctx, [_file("latent.py", PY)], run=False, seed=SEED)
        text = A.report_text(rep, show_all=True)
        self.assertIn("midpoint : ℤ × ℤ → ℤ", text)
        self.assertIn("int_width", text)
        self.assertEqual(rep["summary"]["functions"], 4)
        self.assertIn("int_width", A.laws_text())


if __name__ == "__main__":
    unittest.main()
