"""Every capability in the main pipeline (CM50): declared runs are held to the code, a capability that never runs
fails, a recorded gap is counted, and on the model every capability passes; each capability's Gödel verdict is held
to its code, and a copy of the core's algebra outside engines/godel.py is found."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from helpers import model_ctx

from cardmodel.engines import pipeline as P
from cardmodel.engines import integrity, verify
from cardmodel.engines.context import Ctx
from cardmodel.kernel import paths
from cardmodel.kernel.store import Store

GOAL = "goal/G_A13_pipeline_gaps"
GOAL_G = "goal/G_A14_godel_pure"
RUNS = {"tier": "sample", "tier_reason": "x", "runs": [{"verify": "rules"}]}


def planted(cards: list[dict]) -> tuple[Ctx, Path]:
    """The model's cards with ``cards`` saved over them in a scratch layer."""
    d = Path(tempfile.mkdtemp(prefix="cardmodel_pipeline_"))
    st = Store([("model", paths.model_cards()), ("scratch", d)], readonly={"model"})
    for c in cards:
        st.save(c, layer="scratch")
    return Ctx(st), d


def capability(name: str, pipeline=None, modules=("cardmodel/engines/witness.py",), godel=None) -> dict:
    card = {"name": name, "category": "capability", "statement": "planted", "check": "witnesses",
            "laws": ["law/CM08_executable_claims_have_witnesses"], "tests": [], "core": True,
            "modules": list(modules),
            "godel": godel if godel is not None else {"verdict": "NO", "reason": "i", "why": "planted"}}
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
        self.assertIn("godel", ct["schema"]["required"])
        self.assertEqual(ct["schema"]["properties"]["godel"]["properties"]["verdict"]["enum"], list(P.VERDICTS))


class GodelPurity(unittest.TestCase):
    def check(self, cards):
        ctx, d = planted(cards)
        try:
            return P.check(ctx)
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_on_the_model_every_verdict_is_held_to_the_code(self):
        r = P.check(model_ctx())
        self.assertEqual(r["problems"], [])
        self.assertEqual(sum(r["godel_verdicts"].values()), r["capabilities"])
        for name, row in r["registry"].items():
            g = row["godel"]
            self.assertIn(g["verdict"], P.VERDICTS, name)
            if g["verdict"] in ("CORE", "KEYED"):
                self.assertTrue(row["godel_calls"] or g.get("gap"), name)
        self.assertEqual(r["godel_impure"], len(r["godel_unwired"]) + len(r["godel_copies"]))
        self.assertEqual(set(r["godel_copies"]), set(P.purity_findings()))
        self.assertIn("godel_model", {n for n, x in r["registry"].items() if x["godel"]["verdict"] == "CORE"})

    def test_core_or_keyed_without_the_core_fails(self):
        r = self.check([
            capability("zz_core", RUNS, godel={"verdict": "CORE", "needs": "a", "why": "planted"}),
            capability("zz_keyed_gap", RUNS, godel={"verdict": "KEYED", "needs": "d", "why": "planted",
                                                    "gap": {"reason": "r", "closes_by": "c", "goal": GOAL_G}}),
            capability("zz_wired_gap", {**RUNS, "runs": [{"verify": "sources"}]},
                       modules=["cardmodel/engines/sources.py"],
                       godel={"verdict": "CORE", "needs": "a", "why": "planted",
                              "gap": {"reason": "r", "closes_by": "c", "goal": GOAL_G}}),
            capability("zz_bad", RUNS, godel={"verdict": "NO", "reason": "vii", "why": "planted"}),
            capability("zz_needs", RUNS, godel={"verdict": "KEYED", "needs": "z", "why": "planted",
                                                "gap": {"reason": "r", "closes_by": "c", "goal": GOAL_G}}),
            capability("zz_none", RUNS, godel={})])
        text = "\n".join(r["problems"])
        self.assertIn("capability/zz_core: its card says CORE but its code does not call engines/godel.py", text)
        self.assertNotIn("zz_keyed_gap", text)
        self.assertIn("capability/zz_wired_gap: records a Gödel gap but its code calls the core", text)
        self.assertIn("capability/zz_bad: a NO verdict names its reason", text)
        self.assertIn("capability/zz_needs: a KEYED verdict names what it needs", text)
        self.assertIn("capability/zz_none: Gödel verdict None is not one of", text)
        self.assertIn("zz_keyed_gap", r["godel_unwired"])
        self.assertNotIn("zz_wired_gap: never runs", text)

    def test_a_copy_of_the_core_outside_godel_py_is_found(self):
        d = Path(tempfile.mkdtemp(prefix="cardmodel_purity_"))
        try:
            pkg = d / "cardmodel" / "engines"
            pkg.mkdir(parents=True)
            (d / "cardmodel" / "__init__.py").write_text("", encoding="utf-8")
            (pkg / "__init__.py").write_text("", encoding="utf-8")
            (pkg / "godel.py").write_text("def primes(n):\n    return [2, 3, 5][:n]\n", encoding="utf-8")
            (pkg / "fine.py").write_text("from . import godel as G\n\ndef primes(n):\n    return G.primes(n)\n",
                                         encoding="utf-8")
            (pkg / "copy.py").write_text(
                "def nth_prime(k):\n    return [2, 3, 5][k - 1]\n\n"
                "def code(kind, k):\n    return 3 * k + 1 if kind == 'atom' else 3 * k + 3\n\n"
                "def stride(w):\n    return 3 * w + 1\n\n"
                "def small(n):\n    found = []\n    for k in range(2, n):\n"
                "        if all(k % p for p in found):\n            found.append(k)\n    return found\n\n"
                "def first(n):\n    primes = []\n    k = 2\n    while len(primes) < n:\n"
                "        if all(k % p for p in primes):\n            primes.append(k)\n        k += 1\n"
                "    return primes\n\n"
                "def jaccard_of(a, b):\n    ca, cb = a['content'], b['content']\n"
                "    return sum((ca & cb).values()) / sum((ca | cb).values())\n\n"
                "def zig(n):\n    return 2 * n if n >= 0 else -2 * n - 1\n\n"
                "def number(c, index):\n    n = 1\n    for a, e in c.items():\n"
                "        n *= index[a]['prime'] ** e\n    return n\n\n"
                "def square(x):\n    return x ** 2\n", encoding="utf-8")
            found = P.purity_findings(str(d))
        finally:
            shutil.rmtree(d, ignore_errors=True)
        self.assertEqual(set(found), {f"cardmodel/engines/copy.py:{n}" for n in
                                      ("nth_prime", "zig", "number", "code", "first", "jaccard_of")})

    def test_an_unrecorded_or_stale_copy_fails_integrity(self):
        ctx = model_ctx()
        self.assertEqual(P.purity_problems(ctx), [])
        self.assertEqual(integrity.check(ctx)["problems"], [])
        gm = dict(ctx.store.get("capability/godel_model"))
        g = dict(gm["godel"])
        g["copies"] = [c for c in g["copies"] if not c["at"].endswith("Numbering.tokens")] + [
            {"at": "cardmodel/engines/witness.py:primes", "rule": "core name", "reason": "r", "closes_by": "c",
             "owner": "planted", "goal": GOAL_G}]
        pctx, d = planted([{**gm, "godel": g}])
        try:
            text = "\n".join(integrity.check(pctx)["problems"])
        finally:
            shutil.rmtree(d, ignore_errors=True)
        self.assertIn("cardmodel/engines/numbering.py:Numbering.tokens: core name: defines Numbering.tokens without "
                      "calling the core, outside engines/godel.py", text)
        self.assertIn("records a copy of the core at cardmodel/engines/witness.py:primes, which the code no longer has",
                      text)

    def test_the_known_copies_only_shrink(self):
        """The copies recorded on 2026-11-05 (files of the owner's Gödel thread, GODEL_AUDIT §6 follow-up). A copy
        may leave this list when the thread moves it onto the core; nothing may join it: a new copy calls the core."""
        known = {"cardmodel/engines/codes.py:Reader.codes", "cardmodel/engines/codes.py:_head_code",
                 "cardmodel/engines/codes.py:built_positional_bits", "cardmodel/engines/funcalg.py:godel_encode",
                 "cardmodel/engines/numbering.py:Numbering.tokens", "cardmodel/engines/numbering.py:Numbering.encode",
                 "cardmodel/unreal/distill.py:number"}
        recorded = P.recorded_copies(model_ctx())
        self.assertLessEqual(set(recorded), known, "a new copy of the Gödel core's algebra was recorded instead of "
                                                   "calling engines/godel.py")
        for cap in model_ctx().store.cards("capability"):
            for c in (cap.get("godel") or {}).get("copies") or []:
                self.assertTrue(c.get("rule") and c.get("owner") and c.get("closes_by"), c)


if __name__ == "__main__":
    unittest.main()
