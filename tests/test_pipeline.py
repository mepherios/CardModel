"""Every capability in the main pipeline (CM50): declared runs are held to the code, a capability that never runs
fails, a recorded gap is counted, and on the model every capability passes."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from helpers import model_ctx

from cardmodel.engines import pipeline as P
from cardmodel.engines import verify
from cardmodel.engines.context import Ctx
from cardmodel.kernel import paths
from cardmodel.kernel.store import Store

GOAL = "goal/G_A13_pipeline_gaps"


def planted(cards: list[dict]) -> tuple[Ctx, Path]:
    """The model's cards with ``cards`` saved over them in a scratch layer."""
    d = Path(tempfile.mkdtemp(prefix="cardmodel_pipeline_"))
    st = Store([("model", paths.model_cards()), ("scratch", d)], readonly={"model"})
    for c in cards:
        st.save(c, layer="scratch")
    return Ctx(st), d


def capability(name: str, pipeline=None, modules=("cardmodel/engines/witness.py",)) -> dict:
    card = {"name": name, "category": "capability", "statement": "planted", "check": "witnesses",
            "laws": ["law/CM08_executable_claims_have_witnesses"], "tests": [], "core": True,
            "modules": list(modules)}
    if pipeline is not None:
        card["pipeline"] = pipeline
    return card


class OnTheModel(unittest.TestCase):
    def test_every_capability_runs_or_records_its_gap(self):
        ctx = model_ctx()
        r = P.check(ctx)
        self.assertEqual(r["problems"], [])
        self.assertEqual(r["status"], "pass")
        self.assertEqual(r["capabilities"], len(ctx.store.cards("capability")))
        self.assertEqual(r["never_run"], [])
        for name, row in r["registry"].items():
            self.assertIn(row["tier"], P.TIERS, name)
            for run in row["runs"]:
                self.assertNotIn((run["kind"], run["stage"]), P.NOT_COUNTED, name)
                self.assertTrue(run.get("via"), f"{name}: {run}")
        self.assertIn("pipeline", verify.QUICK)
        # the goal counts every recorded gap, and each gap names it
        self.assertEqual(r["gap_count"], len(r["gaps"]))
        for name in r["gaps"]:
            self.assertEqual(r["registry"][name]["gap"]["goal"], GOAL)

    def test_stages_reach_their_engines(self):
        st = P.stages()
        self.assertEqual(P.link(st[("verify", "rules")], ["cardmodel/engines/witness.py"])[-1].split(".")[1],
                         "witness")
        self.assertIsNotNone(P.link(st[("verify", "machine")], ["cardmodel/machine/symbolic.py"]))
        self.assertIsNotNone(P.link(st[("verify", "proofs")], ["cardmodel/emit/lean.py"]))   # through BACKENDS
        self.assertIsNotNone(P.link(st[("self_step", "laws")], ["cardmodel/engines/laws.py"]))
        self.assertIsNone(P.link(st[("verify", "rules")], ["cardmodel/machine/symbolic.py"]))
        # the entry's own file is every stage's, so it is nobody's evidence
        self.assertIsNone(P.link(st[("verify", "rules")], ["cardmodel/engines/verify.py"]))


class Planted(unittest.TestCase):
    def problems(self, cards):
        ctx, d = planted(cards)
        try:
            return P.check(ctx)
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_a_capability_never_run_fails(self):
        r = self.problems([capability("zz_undeclared"),
                           capability("zz_nothing", {"tier": "sample", "tier_reason": "x", "runs": []}),
                           capability("zz_smoke_only", {"tier": "sample", "tier_reason": "x",
                                                        "runs": [{"verify": "capabilities"}]})])
        text = "\n".join(r["problems"])
        self.assertEqual(r["status"], "fail")
        self.assertIn("capability/zz_undeclared: no `pipeline` field", text)
        self.assertIn("capability/zz_nothing: never runs in the main pipeline and records no gap", text)
        self.assertIn("capability/zz_smoke_only: verify 'capabilities' does not count", text)
        self.assertIn("capability/zz_smoke_only: never runs in the main pipeline", text)
        self.assertEqual(set(r["never_run"]), {"zz_undeclared", "zz_nothing", "zz_smoke_only"})

    def test_declared_but_not_exercised_fails(self):
        r = self.problems([
            capability("zz_wrong_stage", {"tier": "sample", "tier_reason": "x", "runs": [{"verify": "kernel"}]},
                       modules=["cardmodel/machine/symbolic.py"]),
            capability("zz_no_stage", {"tier": "sample", "tier_reason": "x", "runs": [{"verify": "nonesuch"},
                                                                                     {"self_step": "nonesuch"}]}),
            capability("zz_container", {"tier": "sample", "tier_reason": "x", "runs": [{"self_step": "verify"}]}),
            capability("zz_tier", {"tier": "certain", "tier_reason": "x", "runs": [{"verify": "rules"}]})])
        text = "\n".join(r["problems"])
        self.assertIn("capability/zz_wrong_stage: engines/verify.py run(): 'kernel' does not reach", text)
        self.assertIn("verify section 'nonesuch' does not exist", text)
        self.assertIn("self step 'nonesuch' has no self_step card", text)
        self.assertIn("capability/zz_container: self_step 'verify' does not count", text)
        self.assertIn("capability/zz_tier: pipeline tier 'certain' is not one of", text)

    def test_a_recorded_gap_is_counted_not_failed(self):
        gap = {"reason": "planted", "closes_by": "a stage that runs it", "goal": GOAL}
        r = self.problems([capability("zz_gap", {"tier": "sample", "tier_reason": "x", "runs": [], "gap": gap}),
                           capability("zz_part", {"tier": "sample", "tier_reason": "x", "runs": [{"verify": "rules"}],
                                                  "gap": gap}),
                           capability("zz_bad_gap", {"tier": "sample", "tier_reason": "x", "runs": [],
                                                     "gap": {"reason": "planted", "goal": "goal/G_Z9_nonesuch"}})])
        text = "\n".join(r["problems"])
        self.assertNotIn("zz_gap", text)
        self.assertNotIn("zz_part", text)
        self.assertIn("capability/zz_bad_gap: its gap has no `closes_by`", text)
        self.assertIn("capability/zz_bad_gap: its gap names goal/G_Z9_nonesuch, which is not a goal card", text)
        self.assertIn("zz_gap", r["gaps"])
        self.assertIn("zz_part", r["partial"])
        self.assertIn("zz_gap", r["never_run"])
        base = P.check(model_ctx())["gap_count"]
        self.assertEqual(r["gap_count"], base + 3)

    def test_the_schema_requires_the_declaration(self):
        ct = json.loads((paths.model_cards() / "card_type" / "capability" / "card.json").read_text(encoding="utf-8"))
        self.assertIn("pipeline", ct["schema"]["required"])
        self.assertEqual(ct["schema"]["properties"]["pipeline"]["properties"]["tier"]["enum"], list(P.TIERS))


if __name__ == "__main__":
    unittest.main()
