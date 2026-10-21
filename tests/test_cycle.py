"""The model as one unit: the core ledger keeps every law, goal, registry, command and verify section (CM37); one
bounded cycle runs every part of the model, keeps the evidence, compares it with the last run and reports what got
worse (CM38); using the model starts a cycle only when one is due, and never from a nested process."""
import copy
import json
import os
import plistlib
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from helpers import ROOT, SEED, TempProject, model_ctx

from cardmodel.cycle import hook, ledger, report
from cardmodel.cycle import run as R
from cardmodel.cycle import stages as S
from cardmodel.engines import verify
from cardmodel.kernel import resources

os.environ["CARDMODEL_CYCLE_LOCK"] = f"cardmodel-cycle-test-{os.getpid()}.lock"   # never a real cycle's lock


def _project_with(cards: dict) -> TempProject:
    """A throwaway project whose layer overrides model cards (category/name -> card dict)."""
    tp = TempProject()
    for q, card in cards.items():
        d = tp.dir / ".cardmodel" / "cards" / q
        d.mkdir(parents=True, exist_ok=True)
        reg = d.parent / "_category.json"
        if not reg.exists():
            reg.write_text(json.dumps({"name": q.split("/")[0], "description": "a test override of the model"}),
                           encoding="utf-8")
        (d / "card.json").write_text(json.dumps(card), encoding="utf-8")
    return tp


class Ledger(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = model_ctx()
        cls.now = ledger.snapshot(cls.ctx)

    def test_the_core_is_everything_the_model_has(self):
        laws = {c.name for c in self.ctx.store.cards("law")}
        self.assertEqual(set(self.now["laws"]), laws)
        self.assertIn("cycle", self.now["commands"])
        self.assertIn("check", self.now["commands"]["arcade"])
        self.assertEqual(self.now["verify_sections"], list(verify.SECTIONS))
        self.assertIn("ledger", self.now["registries"])
        self.assertFalse(any(ledger.diff(self.now, self.now)[k] for k in ledger.KINDS))

    def test_a_lost_law_fails_the_cycle(self):
        """A ledger that names a law the model no longer has: verify's ledger section and the cycle's core stage
        fail and name it; a changed statement, a weakened goal and a lost command action fail too; accepting the
        loss needs a reason, archives the old ledger and records the amendment."""
        led = copy.deepcopy(self.now)
        led["laws"]["CM99_planted"] = {"statement": "0" * 16, "witness": "tests/test_cycle.py::nothing"}
        some = sorted(led["laws"])[0]
        led["laws"][some] = dict(led["laws"][some], statement="f" * 16)
        led["goals"]["G_C4_redefinitions_verified"] = dict(led["goals"]["G_C4_redefinitions_verified"], target=10 ** 6)
        led["commands"]["arcade"] = led["commands"]["arcade"] + ["teleport"]
        d = ledger.diff(self.now, led)
        self.assertEqual([x["item"] for x in d["lost"]], ["law/CM99_planted", "command/arcade teleport"])
        self.assertEqual([x["item"] for x in d["changed"]], [f"law/{some}"])
        self.assertEqual([x["item"] for x in d["weakened"]], ["goal/G_C4_redefinitions_verified"])
        led2 = copy.deepcopy(self.now)
        led2["goals"]["G_C4_redefinitions_verified"]["target"] = 1
        self.assertEqual([x["item"] for x in ledger.diff(self.now, led2)["strengthened"]],
                         ["goal/G_C4_redefinitions_verified"])
        card = {"name": "core", "category": "ledger", "tier": 0, "statement": ledger.STATEMENT, "core": led,
                "amendments": []}
        tp = _project_with({"ledger/core": card})
        try:
            ctx = tp.ctx()
            r = ledger.check(ctx)
            self.assertEqual(r["status"], "fail")
            self.assertIn("law/CM99_planted", [x["item"] for x in r["lost"]])
            v = verify.run(ctx, seed=SEED, only=["ledger"])
            self.assertEqual(v["status"], "fail")
            out = R.run(stages=["core"], ctx=ctx, seed=SEED)
            self.assertEqual(out["status"], "fail")
            crit = [x for x in out["analysis"]["findings"] if x["severity"] == "critical"]
            self.assertIn("law/CM99_planted", [x["item"] for x in crit])
            self.assertIn("CM99_planted", (ctx.state_root / "cycle" / "report.md").read_text(encoding="utf-8"))
            with self.assertRaises(ValueError):
                ledger.accept(ctx, layer="project")
            grown = ledger.accept(ctx, additions_only=True, layer="project")
            self.assertGreater(grown["still_failing"], 0, "growth alone never accepts a loss")
            self.assertEqual(ledger.check(ctx)["status"], "fail")
            res = ledger.accept(ctx, reason="the planted law was removed on purpose", layer="project")
            self.assertTrue(res["changed"])
            self.assertEqual(ledger.check(ctx)["status"], "pass")
            led_now = ctx.store.get("ledger/core")
            self.assertTrue(any(a["item"] == "law/CM99_planted" and a["reason"] for a in led_now["amendments"]))
            self.assertTrue(list((tp.dir / ".cardmodel" / "cards" / "_versions" / "ledger" / "core").glob("*.json")),
                            "the previous ledger is archived (CM14)")
        finally:
            tp.cleanup()

    def test_the_committed_ledger_holds(self):
        r = ledger.check(self.ctx)
        self.assertEqual(r["status"], "pass", {k: r[k] for k in ledger.FAILING})


class Cycle(unittest.TestCase):
    def _fake_stages(self, calls, boom=None, memory=None):
        def make(name):
            def stage(env):
                calls.append(name)
                if name == boom:
                    raise RuntimeError("planted")
                if name == memory:
                    raise resources.MemoryBudget("planted")
                return {"status": "pass", "summary": name}
            return stage
        return {n: make(n) for n in S.STAGES}

    def test_a_failing_stage_does_not_hide_the_others(self):
        tp = TempProject()
        calls = []
        old = dict(S.STAGES)              # run.STAGES is the same dict
        try:
            S.STAGES.update(self._fake_stages(calls, boom="learn"))
            out = R.run(profile="standard", ctx=tp.ctx(), seed=SEED)
            prof = out["stages"]
            self.assertEqual(list(prof), R.config(tp.ctx())["profiles"]["standard"]["stages"])
            self.assertEqual(prof["learn"]["status"], "error")
            self.assertTrue(all(r["status"] == "pass" for n, r in prof.items() if n != "learn"))
            self.assertIn("stage/learn", [x["item"] for x in out["analysis"]["findings"]])
            calls.clear()
            S.STAGES.update(self._fake_stages(calls, memory="laws"))
            out = R.run(profile="standard", ctx=tp.ctx(), seed=SEED)
            after = list(out["stages"])[list(out["stages"]).index("laws") + 1:]
            self.assertTrue(all(out["stages"][n]["status"] == "skipped" for n in after), "the machine comes first")
            out = R.run(profile="standard", ctx=tp.ctx(), seed=SEED, budget_s=1e-6)
            self.assertTrue(all(r["status"] == "skipped" and "budget" in r["reason"] for r in out["stages"].values()))
        finally:
            S.STAGES.clear()
            S.STAGES.update(old)
            tp.cleanup()

    def test_a_hanging_stage_is_stopped_and_the_next_one_runs(self):
        tp = TempProject()
        old = dict(S.STAGES)

        def spin(env):
            while True:
                pass
        try:
            S.STAGES.update(self._fake_stages([]))
            S.STAGES["learn"] = spin
            cfg_card = dict(R.config(tp.ctx()), stage_limits_s={"learn": 1})
            ctx = tp.ctx()
            ctx.store.save(cfg_card, layer="project", category="cycle")
            out = R.run(profile="standard", ctx=ctx, seed=SEED)
            self.assertEqual(out["stages"]["learn"]["status"], "error")
            self.assertIn("deadline", out["stages"]["learn"]["error"])
            self.assertEqual(out["stages"]["optimize"]["status"], "pass", "the next stage still ran")
        finally:
            S.STAGES.clear()
            S.STAGES.update(old)
            tp.cleanup()

    def test_learning_never_calls_a_source_on_an_input_where_it_hangs(self):
        """`while n != 0: n >>= 1` never returns for a negative n: the step-bounded interpreter drops those inputs
        before the original source is called (a cycle once hung here on the arena framework's set_bits)."""
        from cardmodel.engines.frontend_python import lift_source, module_for
        from cardmodel.engines.translate import reference_rows
        src = "def set_bits(n: int) -> int:\n    c = 0\n    while n != 0:\n        c += n & 1\n        n >>= 1\n" \
              "    return c\n"
        ctx = model_ctx()
        lifted = lift_source(src, ctx.ops)
        ns: dict = {}
        exec(src, ns)  # noqa: S102 -- the test's own source
        with R.deadline_after(30):
            rows = reference_rows(ctx, module_for("set_bits", lifted), ns["set_bits"], [[5], [-3], [0], [1 << 40]])
        self.assertEqual([r["args"][0] for r in rows], [5, 0, 1 << 40])

    def test_one_cycle_at_a_time(self):
        with R.machine_lock({"pid": os.getpid(), "test": True}):
            self.assertIsNotNone(R.running())
            with self.assertRaises(R.Busy):
                R.run(stages=["core"], ctx=model_ctx(), seed=SEED)
        self.assertIsNone(R.running())

    def test_the_cycle_runs_every_stage_and_finds_regressions(self):
        """Every stage of the model, for real, narrowed by a project's cycle card so it fits a unit test: the core,
        five verify sections, two law witnesses, learning on the examples, a small arena, the store (when this
        machine can build it), the goals, the documents, one test of the suite. A planted earlier run had G_C4 met
        and one law witness failing: the cycle reports the goal as a regression and the law as an improvement,
        keeps the run in its state and writes the weakness report."""
        cfg = dict(model_ctx().store.get("cycle/default"))
        cfg["profiles"] = {"test": {"budget_s": 1500, "verify": ["kernel", "ledger", "lang", "rules", "game"],
                                    "stages": ["core", "verify", "laws", "learn", "optimize", "store", "goals", "docs",
                                               "tests"]}}
        cfg["laws"] = {"only": ["CM20_laws_are_cards", "CM37_the_core_is_kept"]}
        cfg["tests"] = {"only": ["test_laws.Laws.test_goals_md_matches_goal_cards"]}
        cfg["learn"] = dict(cfg["learn"], self=None, targets=["examples/algorithms"], max_functions={"test": 1},
                            langs={"test": ["python", "javascript", "c"]})
        cfg["optimize"] = {"arena_count": {"test": 2}, "measure_ops": {"test": False}}
        cfg["store"] = dict(cfg["store"], frames=30)
        tp = _project_with({"cycle/default": cfg})
        try:
            ctx = tp.ctx()
            state = ctx.state_root / "cycle"
            state.mkdir(parents=True, exist_ok=True)
            prev = {"started": "2026-10-20T00:00:00+00:00", "finished": "2026-10-20T00:10:00+00:00",
                    "profile": "test", "seed": 1, "seconds": 600.0, "status": "pass",
                    "stages": {"goals": {"status": "pass", "goals": [
                        {"goal": "G_C4_redefinitions_verified", "metric": "redefinitions_verified", "value": 111,
                         "target": 111, "direction": "higher", "met": True}]},
                        "laws": {"status": "fail", "laws": {"CM20_laws_are_cards": {"status": "fail"}}}}}
            (state / "last.json").write_text(json.dumps(prev), encoding="utf-8")
            out = R.run(profile="test", ctx=ctx, seed=SEED)
            st = out["stages"]
            self.assertEqual(list(st), cfg["profiles"]["test"]["stages"])
            for name, r in st.items():
                self.assertNotIn(r["status"], ("error",), f"{name}: {r.get('error')} {r.get('trace', '')[-800:]}")
            self.assertEqual(st["laws"]["counts"].get("pass"), 2, st["laws"])
            self.assertEqual(st["tests"]["counts"].get("pass"), 1, st["tests"])
            self.assertTrue(st["optimize"]["arena"]["sound"])
            self.assertEqual(sorted(st["verify"]["sections"]), ["game", "kernel", "lang", "ledger", "rules"])
            self.assertEqual(st["learn"]["targets"]["examples/algorithms"]["into"], "sandbox")
            g = {x["goal"]: x for x in st["goals"]["goals"]}
            if g["G_C4_redefinitions_verified"]["met"] is False:
                self.assertIn("goal/G_C4_redefinitions_verified",
                              [x["item"] for x in out["analysis"]["findings"] if x["kind"] == "regression"])
            self.assertTrue(any("the laws stage passes again" in x for x in out["analysis"]["improvements"]))
            self.assertTrue((state / "report.md").read_text(encoding="utf-8").startswith("# WEAKNESSES"))
            self.assertEqual(len((state / "history.jsonl").read_text(encoding="utf-8").splitlines()), 1)
            self.assertEqual(len(list((state / "runs").glob("*.json"))), 1)
            self.assertEqual(R.load_last(state)["seed"], SEED)
            rerun = R.run(profile="test", ctx=ctx, seed=SEED, stages=["core", "goals"])
            self.assertEqual(rerun["analysis"]["regressions"], 0, rerun["analysis"]["findings"])
            g6 = next(g for g in rerun["stages"]["goals"]["goals"] if g["metric"] == "cycle_regressions")
            self.assertEqual((g6["value"], g6["met"]), (0, True), "the regressions goal holds this run's own count")
        finally:
            tp.cleanup()

    def test_commit_takes_only_what_the_cycle_wrote(self):
        """--commit: a local commit of the cycle's cards and generated documents, only when the tree was clean
        before the cycle; code and other files are never swept in; nothing is pushed (there is no remote)."""
        import subprocess
        repo = Path(tempfile.mkdtemp(prefix="cardmodel_commit_"))
        try:
            git = lambda *a: subprocess.run(["git", *a], cwd=repo, capture_output=True, text=True, timeout=60)  # noqa
            if git("init", "-q").returncode != 0:
                self.skipTest("git is not available")
            git("config", "user.email", "cycle@example.invalid")
            git("config", "user.name", "cycle test")
            (repo / "README.md").write_text("x\n")
            git("add", "README.md")
            git("commit", "-qm", "init")
            run = {"started": "2026-10-21T00:00:00+00:00", "profile": "full", "seed": 1, "status": "pass",
                   "analysis": {"counts": {"low": 2}, "regressions": 0}}
            self.assertFalse(R.commit(repo, run, False)["committed"], "a dirty tree is never committed")
            (repo / "cards" / "x").mkdir(parents=True)
            (repo / "cards" / "x" / "card.json").write_text("{}\n")
            (repo / "WEAKNESSES.md").write_text("# W\n")
            (repo / "code.py").write_text("print(1)\n")
            out = R.commit(repo, run, True)
            self.assertTrue(out["committed"], out)
            self.assertEqual(out["files"], 2)
            shown = git("show", "--name-only", "--format=%s", "HEAD").stdout
            self.assertIn("cards/x/card.json", shown)
            self.assertIn("WEAKNESSES.md", shown)
            self.assertNotIn("code.py", shown)
            self.assertIn("?? code.py", git("status", "--porcelain").stdout)
        finally:
            shutil.rmtree(repo, ignore_errors=True)

    def test_vacuous_witness_is_a_weakness(self):
        run = {"started": "x", "profile": "test", "seed": 1, "seconds": 1.0, "stages": {
            "verify": {"status": "pass", "sections": {"redefinitions": {"status": "pass"}},
                       "details": {"redefinitions_unsettled": {
                           "redefinition/x": {"verdict": "inconclusive", "valid_points": 0,
                                              "examples": {"incomplete": 3, "total": 3}}}}}}}
        an = report.analyse(run, None, {})
        kinds = {(x["kind"], x["severity"]) for x in an["findings"]}
        self.assertIn(("vacuous_witness", "medium"), kinds)
        self.assertEqual(an["status"], "pass", "a vacuous witness is a weakness, not a failure")

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

    def test_recorded_learning_never_rewrites_what_it_knows(self):
        """The cycle's recording learner promotes a function once; the next run finds it known and leaves it alone
        (no new version, no pending proposals written), so a recording cycle does not churn the cards."""
        from cardmodel.engines.learn import learn
        tp = TempProject({"m.py": "def tri(n: int) -> int:\n    t = 0\n    for i in range(n + 1):\n"
                                  "        t += i\n    return t\n"})
        try:
            ctx = tp.ctx()
            langs = ["python", "javascript", "c"]
            a = learn(ctx, tp.dir / "m.py", promote=True, layer="project", seed=SEED, max_functions=3, langs=langs,
                      kinds={"function"}, keep_pending=False, skip_existing=True, strict=True)
            self.assertEqual(len(a["promoted"]), 1, a)
            card = ctx.store.get(a["promoted"][0])
            b = learn(ctx, tp.dir / "m.py", promote=True, layer="project", seed=SEED + 1, max_functions=3,
                      langs=langs, kinds={"function"}, keep_pending=False, skip_existing=True, strict=True)
            self.assertEqual(b["promoted"], [])
            again = ctx.store.get(a["promoted"][0])
            self.assertEqual(again.get("metadata"), card.get("metadata"), "the known card was not rewritten")
            self.assertEqual([c for c in ctx.store.cards("proposal") if c.layer == "project"], [],
                             "no pending proposals are written")
        finally:
            tp.cleanup()

    def test_the_model_can_observe_its_own_code(self):
        from cardmodel.engines.exprs import ParseError, parse
        from cardmodel.engines.observe import observe
        with self.assertRaises(ParseError):
            parse("a in b")
        obs = observe(model_ctx(), ROOT / "cardmodel")
        self.assertGreater(obs["totals"]["files"], 50)
        self.assertGreater(obs["totals"]["named_fraction"], 0)


class Hook(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp(prefix="cardmodel_hook_"))
        (self.home / "cards" / "cycle" / "default").mkdir(parents=True)
        shutil.copy(ROOT / "cards" / "cycle" / "default" / "card.json",
                    self.home / "cards" / "cycle" / "default" / "card.json")
        self.env = dict(os.environ)
        self.depth = hook._ENTERED["depth"]
        self.free, self.load = resources.available_mb, os.getloadavg
        resources.available_mb = lambda: 64000
        os.getloadavg = lambda: (0.0, 0.0, 0.0)
        hook._ENTERED["depth"] = 1
        os.environ.pop("CARDMODEL_AUTO_CYCLE", None)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.env)
        hook._ENTERED["depth"] = self.depth
        resources.available_mb, os.getloadavg = self.free, self.load
        shutil.rmtree(self.home, ignore_errors=True)

    def test_a_cycle_starts_only_when_due(self):
        verify_args = SimpleNamespace(cmd="verify", action=None)
        self.assertEqual(hook.decide(verify_args, self.home), (True, "due"))
        os.environ["CARDMODEL_AUTO_CYCLE"] = "0"
        self.assertFalse(hook.decide(verify_args, self.home)[0])
        os.environ.pop("CARDMODEL_AUTO_CYCLE")
        hook._ENTERED["depth"] = 2
        self.assertFalse(hook.decide(verify_args, self.home)[0], "a nested cardmodel process never starts one")
        hook._ENTERED["depth"] = 1
        self.assertFalse(hook.decide(SimpleNamespace(cmd="arcade", action="serve"), self.home)[0])
        self.assertFalse(hook.decide(SimpleNamespace(cmd="cycle", action="run"), self.home)[0])
        (self.home / "state" / "cycle").mkdir(parents=True)
        (self.home / "state" / "cycle" / "auto.json").write_text(json.dumps({"last_start": 10 ** 12}))
        self.assertEqual(hook.decide(verify_args, self.home), (False, "not due yet"))
        hook.set_auto(self.home, False)
        self.assertFalse(hook.decide(verify_args, self.home)[0])
        (self.home / "state" / "cycle" / "auto.json").write_text(json.dumps({"last_start": 0}))
        resources.available_mb = lambda: 100
        self.assertIn("free", hook.decide(verify_args, self.home)[1])
        resources.available_mb = lambda: 64000
        os.getloadavg = lambda: (1000.0, 0.0, 0.0)
        self.assertIn("busy", hook.decide(verify_args, self.home)[1])
        os.getloadavg = lambda: (0.0, 0.0, 0.0)
        (self.home / ".git").write_text("gitdir: /somewhere/.git/worktrees/x\n")
        self.assertFalse(hook.decide(verify_args, self.home)[0], "a linked worktree cycles only when asked")
        os.environ["CARDMODEL_AUTO_CYCLE"] = "1"
        self.assertTrue(hook.decide(verify_args, self.home)[0])
        with R.machine_lock({"pid": os.getpid()}):
            self.assertEqual(hook.decide(verify_args, self.home), (False, "a cycle is running"))

    def test_the_notice_shows_once(self):
        (self.home / "state" / "cycle").mkdir(parents=True)
        (self.home / "state" / "cycle" / "auto.json").write_text(json.dumps({"last_run": {
            "started": "2026-10-21T10:00:00+00:00", "counts": {"critical": 1, "high": 2}, "regressions": 1}}))
        self.assertIn("1 critical and 2 high", hook.notice(self.home))
        self.assertIsNone(hook.notice(self.home))

    def test_the_schedule_runs_a_profile(self):
        p = plistlib.loads(hook.plist(self.home, "full", record=True, commit=True, every_hours=6))
        self.assertEqual(p["Label"], hook.LABEL)
        self.assertEqual(p["ProgramArguments"][-6:], ["cycle", "run", "--profile", "full", "--record", "--commit"])
        self.assertEqual(p["StartInterval"], 6 * 3600)
        self.assertEqual(p["Nice"], 10)
        self.assertEqual(p["EnvironmentVariables"]["CARDMODEL_AUTO_CYCLE"], "0")
        self.assertTrue(p["StandardOutPath"].endswith("state/cycle/schedule.log"))
        p = plistlib.loads(hook.plist(self.home, "standard", at="03:30"))
        self.assertEqual(p["StartCalendarInterval"], {"Hour": 3, "Minute": 30})
        self.assertNotIn("--record", p["ProgramArguments"])
        self.assertTrue(hook.cron_line(self.home, at="03:30").startswith("30 3 * * * cd "))


if __name__ == "__main__":
    unittest.main()
