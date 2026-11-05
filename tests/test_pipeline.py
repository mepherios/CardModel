"""Every applicable stage runs or says why (CM50): the stage registry (cards/stage), the runner and the coverage
check of engines/pipeline.py."""
import copy
import unittest
from unittest import mock

from helpers import SEED, TempProject, model_ctx, seed_note

from cardmodel.engines import pipeline as P


class Pipeline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = model_ctx()
        cls.plan = P.stages(cls.ctx)
        cls.rec = P.run_source(cls.ctx, P.FIXTURE, P.REFERENCE, label="fixture", langs=[P.REFERENCE], seed=SEED)
        cls.second = P._second_fixture(cls.ctx, P.FIXTURE)      # the same functions, not in the reference language
        cls.rec2 = (P.run_source(cls.ctx, cls.second[1], cls.second[0], label=f"fixture.{cls.second[0]}",
                                 langs=[P.REFERENCE], seed=SEED) if cls.second else None)

    def functions(self) -> dict:
        out = dict(self.rec["functions"])
        if self.rec2 is not None:
            out.update({f"{self.second[0]}:{n}": f for n, f in self.rec2["functions"].items()})
        return out

    def test_every_applicable_stage_runs_or_says_why(self):
        """CM50's witness: one entry per stage per function; a stage whose hypothesis holds on the function's facts
        ran (or was attempted: unavailable, failed) unless it waited on a stage that did not run; every entry that
        did not run names its reason, and the reason is the fact or the stage that failed."""
        self.assertGreaterEqual(len(self.plan), 20)
        names = [s["name"] for s in self.plan]
        self.assertEqual(self.rec["stages"], names)
        for fname, f in self.rec["functions"].items():
            self.assertEqual(list(f["stages"]), names, fname)
            self.assertEqual(f["summary"]["problems"], [], f"{fname} {seed_note(self)}")
            for s in self.plan:
                e = f["stages"][s["name"]]
                self.assertIn(e["status"], P.STATUSES, f"{fname}/{s['name']}")
                if e["status"] != "ran":
                    self.assertTrue(e.get("reason"), f"{fname}/{s['name']}: no reason")
                waiting = next((n for n in s["needs"] if f["stages"][n]["status"] != "ran"), None)
                status, reason = P.applies(s, f["facts"])
                if waiting is not None:
                    self.assertEqual(e["status"], "skipped", f"{fname}/{s['name']}: {e}")
                    self.assertIn(f"needs stage {waiting}", e["reason"])
                elif status == "ran":
                    self.assertIn(e["status"], ("ran", "unavailable", "failed"), f"{fname}/{s['name']}: {e}")
                else:
                    self.assertEqual((e["status"], e["reason"]), (status, reason), f"{fname}/{s['name']}: {e}")
        # a plain polynomial goes through every group: terms, identity, evidence, optimize, targets, record
        poly = self.rec["functions"]["poly"]
        ran = {s["name"] for s in self.plan if poly["stages"][s["name"]]["status"] == "ran"}
        for g in P.GROUPS:
            self.assertTrue(any(s["group"] == g and s["name"] in ran for s in self.plan), g)
        self.assertIn("sized_witness", ran, seed_note(self))
        self.assertEqual(poly["stages"]["sized_witness"].get("verdict"), "proved", poly["stages"]["sized_witness"])
        self.assertEqual(self.rec["coverage"]["status"], "pass", self.rec["coverage"]["problems"])

    def test_registry_matches_the_program_and_the_mathematics(self):
        problems, reach = P.registry_problems(self.ctx, self.plan)
        self.assertEqual(problems, [])
        self.assertEqual(reach["unreached"], [])
        self.assertEqual(reach["reached"] + reach["outside"], reach["engines"])
        for s in self.plan:
            self.assertIn(s["run"], P.STAGES, s["name"])
            self.assertIn(s["group"], P.GROUPS, s["name"])
            self.assertTrue(s["foundations"], f"stage/{s['name']} rests on nothing in docs/FOUNDATIONS.md")

    def test_coverage_catches_an_unnamed_stage_function(self):
        def orphan(ctx, job, run):
            return {}
        with mock.patch.dict(P.STAGES, {"orphan": orphan}):
            problems, _ = P.registry_problems(self.ctx, self.plan)
        self.assertTrue(any("'orphan'" in p and "no stage card names it" in p for p in problems), problems)
        ghost = dict(self.plan[0], name="ghost", run="no_such_function", needs=[], engines=[], foundations=[], laws=[])
        problems, _ = P.registry_problems(self.ctx, self.plan + [ghost])
        self.assertTrue(any("ghost" in p and "no stage function" in p for p in problems), problems)
        wrong = dict(self.plan[0], engines=self.plan[0]["engines"] + ["cardmodel/engines/arena.py"])
        problems, _ = P.registry_problems(self.ctx, [wrong] + self.plan[1:])
        self.assertTrue(any("arena.py" in p and "does not import" in p for p in problems), problems)

    def test_coverage_catches_a_dead_hypothesis(self):
        functions = self.functions()
        self.assertEqual(P.fixture_problems(self.plan, functions), [])
        dead = dict(self.plan[1], name="ghost", when=["lifted", "recursive"], unless=[], needs=[])
        problems = P.fixture_problems(self.plan + [dead], functions)
        self.assertTrue(any("ghost" in p and "dead hypothesis" in p for p in problems), problems)
        # an entry that did not run and gives no reason is a problem of the run itself
        rec = copy.deepcopy(self.rec)
        rec["functions"]["poly"]["stages"]["canon"] = {"status": "skipped"}
        rec["functions"]["poly"]["summary"] = P._summary(rec["functions"]["poly"]["stages"])
        cov = P.coverage_of(rec)
        self.assertEqual(cov["status"], "fail")
        self.assertTrue(any("canon" in p and "without a reason" in p for p in cov["problems"]), cov["problems"])

    def test_options_ask_for_the_stages_that_are_off_by_default(self):
        rec = P.run_source(self.ctx, P.FIXTURE, P.REFERENCE, names=["poly"], langs=[P.REFERENCE], seed=SEED,
                           options={"deep": True, "measure": True})
        st = rec["functions"]["poly"]["stages"]
        self.assertEqual(rec["coverage"]["problems"], [], seed_note(self))
        self.assertIn(st["divergence_witness"]["status"], ("ran", "unavailable"), st["divergence_witness"])
        self.assertIn(st["measure"]["status"], ("ran", "unavailable"), st["measure"])
        rec = P.run_source(self.ctx, P.FIXTURE, P.REFERENCE, names=["poly"], langs=[P.REFERENCE], seed=SEED,
                           only=["lift", "profile", "reference", "canon"])
        st = rec["functions"]["poly"]["stages"]
        self.assertEqual(st["canon"]["status"], "ran", st["canon"])
        self.assertEqual(st["emit"]["status"], "not_requested")
        self.assertIn("--only", st["emit"]["reason"])

    def test_the_second_fixture_is_not_in_the_reference_language(self):
        self.assertIsNotNone(self.second, "no language card with a frontend and its own emitter besides the reference")
        lang, _text = self.second
        self.assertNotEqual(lang, P.REFERENCE)
        rec = self.rec2
        self.assertEqual(rec["coverage"]["problems"], [], seed_note(self))
        ws = {n: f["stages"]["witness_source"] for n, f in rec["functions"].items() if f["facts"].get("lifted")}
        self.assertTrue(ws)
        for n, e in ws.items():
            self.assertIn(e["status"], ("ran", "unavailable"), f"{n}: {e}")
            self.assertNotEqual(e["status"] == "unavailable" and not e.get("reason"), True, f"{n}: {e}")


class Cli(unittest.TestCase):
    def test_translate_runs_the_registry(self):
        p = TempProject({"f.py": P.FIXTURE})
        try:
            r = p.cli("translate", "f.py", "--to", P.REFERENCE, "--seed", str(SEED), "--stages")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("coverage pass", r.stdout)
            self.assertIn("not when source_is_reference", r.stdout)
            self.assertIn("option --deep", r.stdout)
            r = p.cli("translate", "f.py", "--to", P.REFERENCE, "--seed", str(SEED), "--only",
                      "lift,profile,reference,emit,witness_targets")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("agrees in", r.stdout)
            self.assertIn("not lifted", r.stdout)
            r = p.cli("pipeline", "stages")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("sized_witness", r.stdout)
        finally:
            p.cleanup()


if __name__ == "__main__":
    unittest.main()
