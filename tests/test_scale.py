"""The scale benchmark (SCALING.md §6): deterministic synthetic projects, every stage timed, goals read the newest run.

Sizes here are 10² so the suite stays fast; `cardmodel scale bench` measures 10³ to 10⁵ (10⁶ optional)."""
import tempfile
import unittest
from pathlib import Path

from helpers import TempProject, model_ctx

from cardmodel.engines import coverage, lift_project, scale


def _files(root: Path) -> dict:
    return {str(p.relative_to(root)): p.read_text(encoding="utf-8") for p in sorted(root.rglob("*.py"))}


class Generate(unittest.TestCase):
    def test_same_seed_same_bytes(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b, \
                tempfile.TemporaryDirectory() as c:
            ka, kb = scale.generate(Path(a), 250, 7), scale.generate(Path(b), 250, 7)
            self.assertEqual(ka, kb)
            self.assertEqual(_files(Path(a)), _files(Path(b)))
            scale.generate(Path(c), 250, 8)
            self.assertNotEqual(_files(Path(a)), _files(Path(c)))

    def test_every_kind_and_the_expected_lift(self):
        ctx = model_ctx()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            key = scale.generate(root, 300, 3)
            self.assertEqual(len(key), 300)
            self.assertEqual({k["kind"] for k in key.values()}, set(scale.KINDS))
            self.assertEqual(len({k["module"] for k in key.values()}), 3)
            lifted = lift_project.lift_files(ctx, [(p, "python") for p in sorted(root.rglob("*.py"))], root=root)
        self.assertEqual(set(lifted.functions), set(key))
        self.assertGreater(lifted.cross_calls, 0)
        for q, k in key.items():
            ok = lifted.functions[q].ok
            if k["kind"] == "fail":
                self.assertFalse(ok, q)                # the deliberate failure stays a failure
            elif k["kind"] != "fail_caller":           # fail_caller: whatever the closure decides (measured)
                self.assertTrue(ok, (q, k, lifted.functions[q].reasons))

    def test_call_depth_is_bounded(self):
        with tempfile.TemporaryDirectory() as tmp:
            key = scale.generate(Path(tmp), 600, 1)
        depth = {}
        for q, k in key.items():                       # callees come first in the key's order
            depth[q] = depth[k["calls"]] + 1 if k["kind"] in ("chain", "cross") else 0
        self.assertLessEqual(max(depth.values()), scale.MAX_DEPTH)


class Bench(unittest.TestCase):
    def test_measure_reports_every_stage(self):
        r = scale.measure(model_ctx(), 100, 5)
        self.assertEqual(r["functions"], 100)
        self.assertEqual(set(r["stage_s"]), set(scale.STAGES))
        self.assertEqual(r["reference_ran"] + r["reference_errors"], r["lifted"])
        self.assertEqual(r["reference_errors"], 0)
        self.assertGreater(r["lift_rate"], 0.5)
        self.assertLess(r["lift_rate"], 1)
        self.assertGreater(r["peak_mb"], 0)

    def test_child_bench_record_and_goals(self):
        p = TempProject()
        try:
            ctx = p.ctx()
            res = scale.bench(ctx, (50, 100), seed=2)            # one child process per size
            self.assertEqual([r["n"] for r in res["rows"]], [50, 100])
            self.assertFalse([r for r in res["rows"] if "error" in r], res["rows"])
            self.assertIsNotNone(res["slope"])
            self.assertEqual(res["slope_between"], [50, 100])
            names = scale.record(ctx, res, layer="project")
            self.assertEqual(names, ["metric/scale__n50", "metric/scale__n100"])
            ctx.store.invalidate()
            card = ctx.store.get("metric/scale__n100")
            self.assertEqual(card["target_card"], "goal/G_A11_scale_slope")
            self.assertEqual(coverage._metric(ctx, "scale_slope", {}, {}), res["slope"])
            self.assertEqual(coverage._metric(ctx, "scale_peak_memory_mb", {}, {}), res["largest_peak_mb"])
            self.assertIn("slope", scale.report_text(res))
        finally:
            p.cleanup()


if __name__ == "__main__":
    unittest.main()
