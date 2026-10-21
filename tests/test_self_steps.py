"""The self-run's deep steps (CM38): every law's witness test runs and a broken one is a critical flaw; the model
observes its own code and the named-fraction goal reads that observation, not a corpus's; every store item is
launched through the store (CM42); a step that never returns is stopped by its deadline; and the fixes these steps
needed: learning never calls a source on an input where it hangs, a partial verify keeps the other sections."""
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from helpers import ROOT, SEED, TempProject, model_ctx
from test_self import IsolatedSelf

from cardmodel.engines import probes, selfrun, verify
from cardmodel.kernel import resources


def _cycle(d: Path) -> "selfrun.Cycle":
    return selfrun.Cycle(SEED, dict(selfrun.DEFAULT_CONFIG), {}, lambda m: None)


class LawWitnesses(unittest.TestCase):
    def test_a_broken_law_is_a_critical_flaw(self):
        """Two real laws (their witnesses pass) and a planted one whose witness does not exist: the step runs the
        real witnesses in a child process and the planted law becomes a critical flaw."""
        ctx = model_ctx()
        real = [ctx.store.get("law/CM20_laws_are_cards"), ctx.store.get("law/CM06_random_seeds")]
        planted = dict(real[0], name="CM99_planted", witness="tests/test_laws.py::test_does_not_exist")
        with IsolatedSelf() as d:
            c = _cycle(d)
            fake = type(real[0])(planted, registry="law", layer="model")
            with mock.patch.object(c.ctx.store, "cards", lambda reg: [*real, fake] if reg == "law" else []):
                res = selfrun._law_witnesses(c)
        self.assertEqual(res["failing"], ["CM99_planted"], res["witnesses"])
        self.assertEqual({res["witnesses"][n]["status"] for n in ("CM20_laws_are_cards", "CM06_random_seeds")},
                         {"pass"})
        self.assertEqual(res["status"], "fail")
        flaws = [f for f in selfrun.findings({"steps": {"law_witnesses": res}}) if f["area"] == "law/CM99_planted"]
        self.assertEqual([(f["kind"], f["severity"]) for f in flaws], [("flaw", "critical")])

    def test_the_runner_reports_every_test(self):
        with IsolatedSelf() as d:
            res = selfrun.run_tests(_cycle(d), ["test_laws.Laws.test_laws_md_in_sync", "test_laws.Laws.nothing_here"],
                                    timeout=300)
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["tests"]["test_laws.Laws.test_laws_md_in_sync"]["status"], "pass")
        bad = [r["status"] for t, r in res["tests"].items() if "nothing_here" in t]
        self.assertEqual(bad, ["error"], res["tests"])


class ObserveSelf(unittest.TestCase):
    def test_the_named_fraction_is_the_models_own_code(self):
        """The step saves its observation of cardmodel/ in the self layer; an observation of a corpus made later
        (the examples are almost all named) never stands in for it."""
        from cardmodel.engines import coverage
        with IsolatedSelf() as d:
            c = _cycle(d)
            res = selfrun._observe_self(c)
            self.assertGreater(res["files"], 50)
            corpus = {"name": "obs_corpus", "category": "observation", "root": "examples",
                      "observed_at": "2999-01-01T00:00:00+00:00", "totals": {"named_fraction": 0.99}}
            c.wctx.store.save(corpus, layer="self", category="observation")
            c.refresh()
            self.assertEqual(coverage._metric(c.ctx, "named_fraction", {}, {}), res["named_fraction"])
            again = selfrun._observe_self(c)
            self.assertNotIn("a new observation", again["summary"], "one observation per content hash (CM15)")


@unittest.skipUnless(probes.probe({"kind": "executable", "name": "swiftc"})[0], "needs swiftc (macOS)")
class Store(unittest.TestCase):
    def test_the_store_step_launches_the_catalogue(self):
        from cardmodel.arcade import build as B
        old = B.ROOT_OVERRIDE
        B.ROOT_OVERRIDE = Path(tempfile.mkdtemp(prefix="cardmodel_store_step_"))   # not the checkout's depots
        try:
            with IsolatedSelf() as d:
                c = _cycle(d)
                res = selfrun._store(c)
                section = c.state["sections"]["store"]["result"]
        finally:
            shutil.rmtree(B.ROOT_OVERRIDE, ignore_errors=True)
            B.ROOT_OVERRIDE = old
        self.assertEqual(res["status"], "pass", res)
        self.assertEqual(res["failing"], [])
        self.assertIn("vector_duel", res["launched"])
        self.assertIn("gameboy_player", res["launched"])
        self.assertEqual(section["failing"], [])
        from cardmodel.engines import coverage
        self.assertEqual(coverage._metric(model_ctx(), "store_items_failing", {}, {"store": section}), 0)


class Deadlines(unittest.TestCase):
    def test_a_step_that_never_returns_is_stopped(self):
        def spin(c):
            while True:
                time.sleep(0.01)
        with IsolatedSelf(), mock.patch.dict(selfrun.STEPS, {"observe_self": spin}), \
                mock.patch.object(selfrun.Cycle, "remaining", lambda self, cap=None: 1.0):
            rep = selfrun.cycle(only=["observe_self"], say=lambda m: None)
        step = rep["steps"]["observe_self"]
        self.assertEqual(step["status"], "error")
        self.assertIn("deadline", step["summary"])
        self.assertLess(step["seconds"], 30)

    def test_an_interrupted_run_kills_its_children(self):
        """resources.run interrupted by a deadline leaves no process behind."""
        marker = f"cardmodel-deadline-{os.getpid()}-{SEED}"
        with self.assertRaises(resources.Deadline):
            with resources.deadline(1):
                resources.run([sys.executable, "-c", f"import time; time.sleep(60)  # {marker}"], timeout=120,
                              heavy=False)
        time.sleep(0.5)
        left = subprocess.run(["pgrep", "-f", marker], capture_output=True, text=True, timeout=30).stdout.split()
        for pid in left:
            os.kill(int(pid), signal.SIGKILL)
        self.assertEqual(left, [], "the interrupted child was left running")


class Fixes(unittest.TestCase):
    def test_learning_never_calls_a_source_on_an_input_where_it_hangs(self):
        """`while n != 0: n >>= 1` never returns for a negative n: the step-bounded interpreter drops those inputs
        before the original source is called (a learning run once hung on the arena framework's set_bits)."""
        from cardmodel.engines.frontend_python import lift_source, module_for
        from cardmodel.engines.translate import reference_rows
        src = ("def set_bits(n: int) -> int:\n    c = 0\n    while n != 0:\n        c += n & 1\n        n >>= 1\n"
               "    return c\n")
        ctx = model_ctx()
        ns: dict = {}
        exec(src, ns)  # noqa: S102 -- the test's own source
        with resources.deadline(30):
            rows = reference_rows(ctx, module_for("set_bits", lift_source(src, ctx.ops)), ns["set_bits"],
                                  [[5], [-3], [0], [1 << 40]])
        self.assertEqual([r["args"][0] for r in rows], [5, 0, 1 << 40])

    def test_the_model_can_observe_its_own_code(self):
        from cardmodel.engines.exprs import ParseError, parse
        from cardmodel.engines.observe import observe
        with self.assertRaises(ParseError):
            parse("a in b")
        obs = observe(model_ctx(), ROOT / "cardmodel")
        self.assertGreater(obs["totals"]["files"], 50)

    def test_a_partial_verify_keeps_the_other_sections(self):
        tp = TempProject()
        try:
            ctx = tp.ctx()
            verify.run(ctx, seed=SEED, only=["rules", "kernel"])
            verify.run(ctx, seed=SEED + 1, only=["rules"])
            saved = ctx.load_state("last_verify")
            self.assertEqual(saved["seed"], SEED + 1)
            self.assertEqual(saved["sections"]["kernel"]["carried"]["seed"], SEED)
            self.assertNotIn("carried", saved["sections"]["rules"])
        finally:
            tp.cleanup()


if __name__ == "__main__":
    unittest.main()
