"""Optimizer: real measurements become metric cards; anchors change only from measurements (CM09)."""
import unittest

from helpers import SEED, TempProject

from cardmodel.engines import optimize, rewrite


class Optimize(unittest.TestCase):
    def test_measure_writes_metric_cards(self):
        p = TempProject()
        try:
            ctx = p.ctx()
            rows = []
            for name in ("op/ADD", "op/SQUARE"):
                rows += optimize.measure_python_forms(ctx, ctx.store.get(name), SEED, n_inputs=16, repeats=3)
            forms = {(r["card"], r["form"]) for r in rows}
            self.assertIn(("ADD", "native"), forms)
            self.assertIn(("ADD", "bit"), forms)
            names = optimize.write_metrics(ctx, rows, layer="project")
            ctx.store.invalidate()
            m = ctx.store.get("metric/metric__ADD__bit")
            self.assertIsNotNone(m)
            self.assertEqual(m.layer, "project")
            self.assertGreater(m["median_ns"], 0)
            self.assertEqual(m["metadata"]["seed"], SEED)
            self.assertIn("machine", m["host"])
            self.assertEqual(len(names), len(rows))
            # the bit form is far slower than native: the measured ordering confirms the anchors
            v = {x["card"]: x for x in optimize.verdicts(rows)}
            self.assertEqual(v["op/ADD"]["measured_pick"], "native")
            best = rewrite.cheapest(ctx.store, ctx.store.get("op/ADD"), "u32", cost="measured")
            self.assertEqual(best.name, "native")
        finally:
            p.cleanup()

    def test_apply_keeps_anchor_and_versions(self):
        p = TempProject()
        try:
            ctx = p.ctx()
            base_version = ctx.store.get("op/ADD")["metadata"]["version"]
            rows = optimize.measure_python_forms(ctx, ctx.store.get("op/ADD"), SEED, n_inputs=8, repeats=3)
            optimize.write_metrics(ctx, rows, layer="project")
            ctx.store.invalidate()
            changed = optimize.apply_costs(ctx, rows, layer="project")
            self.assertEqual(changed, ["op/ADD"])
            ctx.store.invalidate()
            add = ctx.store.get("op/ADD")
            native = add.form("native")
            self.assertEqual(native["cost"], 1.0)                 # the calibration unit
            self.assertEqual(native["cost_anchor"], 1.0)
            self.assertGreater(add.form("bit")["cost"], 1.0)
            self.assertEqual(add.layer, "project")                # model card untouched; project overrides
            major, minor, _ = (int(x) for x in base_version.split("."))
            self.assertEqual(add["metadata"]["version"], f"{major}.{minor + 1}.0")   # continues the model's line
            self.assertEqual(add["metadata"]["version_base_layer"], "model")
        finally:
            p.cleanup()


if __name__ == "__main__":
    unittest.main()
