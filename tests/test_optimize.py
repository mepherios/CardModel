"""Optimizer: real measurements become metric cards; anchors change only from measurements (CM09)."""
import unittest

from helpers import SEED, TempProject, model_ctx

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


class Verdicts(unittest.TestCase):
    """The anchor verdict compares forms on the same calls, inside the noise, and never on an unresolved slope."""

    @staticmethod
    def row(form, ns, anchor, sig="s", mad=0.0, **kw):
        return {"target_card": "op/X", "card": "X", "form": form, "median_ns": ns, "mad_ns": mad, "anchor": anchor,
                "inputs_signature": sig, **kw}

    def test_forms_on_different_inputs_are_not_compared(self):
        rows = [self.row("native", 100.0, 1.0, sig="a"), self.row("fast", 10.0, 2.0, sig="b")]
        self.assertEqual(optimize.verdicts(rows), [])

    def test_gap_within_spread_is_white(self):
        rows = [self.row("native", 100.0, 1.0, mad=20.0), self.row("fast", 70.0, 2.0, mad=20.0)]
        self.assertEqual(optimize.verdicts(rows)[0]["verdict"], "white")
        rows = [self.row("native", 100.0, 1.0, mad=1.0), self.row("fast", 70.0, 2.0, mad=1.0)]
        self.assertEqual(optimize.verdicts(rows)[0]["verdict"], "red")

    def test_unresolved_slope_is_not_a_free_function(self):
        rows = [self.row("c", 50.0, 1.0), self.row("rust", 0.0, 2.0, resolved=False)]
        self.assertEqual(optimize.verdicts(rows), [])

    def test_python_forms_share_inputs(self):
        p = TempProject()
        try:
            ctx = p.ctx()
            rows = optimize.measure_python_forms(ctx, ctx.store.get("op/MOD"), SEED, n_inputs=24, repeats=2)
        finally:
            p.cleanup()
        forms = {r["form"]: r for r in rows}
        self.assertIn("pow2_bit", forms)
        self.assertTrue(all(r["shared_inputs"] for r in rows), rows)
        self.assertEqual(len({r["inputs_signature"] for r in rows}), 1, "every form timed on the same calls")


class HostCosts(unittest.TestCase):
    """Costs per function x language x host: each host keeps its own measurement, and the ranking answers which
    target a function should run in here."""

    def test_hosts_are_kept_apart_and_ranked(self):
        from unittest import mock
        p = TempProject()
        try:
            ctx = p.ctx()
            card = next(iter(ctx.store.cards("function")))
            forms = [f["name"] for f in card["forms"]][:3]

            def rows(ns):
                return [{"target_card": f"function/{card['name']}", "card": card["name"], "form": f, "lang": f,
                         "median_ns": n, "samples": 3, "seed": SEED, "inputs_signature": "s"}
                        for f, n in zip(forms, ns)]

            with mock.patch.object(optimize, "host_id", return_value="hostA"):
                optimize.write_metrics(ctx, rows([30.0, 10.0, 20.0]))
            with mock.patch.object(optimize, "host_id", return_value="hostB"):
                optimize.write_metrics(ctx, rows([5.0, 50.0, 40.0]))
            m = ctx.store.get(f"metric/metric__{card['name']}__{forms[0]}")
            self.assertEqual(sorted(m["by_host"]), ["hostA", "hostB"], "a second host adds, never overwrites")
            self.assertEqual([r["form"] for r in rewrite.rank_targets(ctx.store, card, host="hostA")],
                             [forms[1], forms[2], forms[0]])
            self.assertEqual(rewrite.rank_targets(ctx.store, card, host="hostB")[0]["form"], forms[0])
            self.assertEqual(rewrite.rank_targets(ctx.store, card, host="hostC"), [], "not measured on hostC")
            with mock.patch.object(optimize, "host_id", return_value="hostA"):
                self.assertEqual(rewrite.cheapest(ctx.store, card, available_only=False, cost="measured").name,
                                 forms[1])
        finally:
            p.cleanup()

    def test_slope_grows_until_it_is_measurable(self):
        from unittest import mock
        calls = []

        class Run:
            def __init__(self, ms):
                self.run_ms = ms

        def fake_run(lang_card, src, root, parse=False):
            reps = int(src)
            calls.append(reps)
            return Run(2.0 + reps * 1e-4)          # 0.1 us per rep: lost in startup until 200000 reps

        class Em:
            def __init__(self, *a):
                pass

            def program(self, module, calls_, mode, reps):
                return str(reps)

        with mock.patch.object(optimize, "run_program", fake_run), mock.patch.object(optimize, "Emitter", Em):
            reps, times = optimize._slope_runs(model_ctx(), {}, "c", {}, [(1,)], (200, 2000))
        self.assertEqual(reps, (200, 200000))
        self.assertGreater(times[1] - times[0], optimize.SLOPE_MIN_MS)
