"""The model keeps its core (CM37), runs itself (CM38) and stays one program (CM39)."""
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from helpers import CLI, ROOT, SEED, model_ctx, seed_note

from cardmodel.engines import capabilities as K
from cardmodel.engines import integrity, selflogic, selfrun, verify
from cardmodel.engines import logic as L
from cardmodel.engines.context import Ctx
from cardmodel.kernel import paths
from cardmodel.kernel.store import Store

# The core. Removing one of these is a deliberate, visible change: its card, this list and the law's witness.
CORE = ["card_store", "honest_limits", "witnesses", "form_selection", "boundaries", "learning", "translation",
        "rewriting", "law_discovery", "theorems", "lean", "logic", "card_language", "self_theory",
        "function_algebra", "redefinitions", "improve", "resources", "game_design", "world", "machines",
        "emulation", "arcade", "live_hub", "godel_model", "distillation", "anyps5", "self_run", "integration"]


class IsolatedSelf:
    """state/self in a temporary folder: the tests never touch the checkout's own self-run record."""

    def __enter__(self):
        self.dir = Path(tempfile.mkdtemp(prefix="cardmodel_self_"))
        self.patches = [mock.patch.object(selfrun, "self_dir", lambda: self.dir),
                        mock.patch.object(paths, "self_cards", lambda: self.dir / "cards")]
        for p in self.patches:
            p.start()
        return self.dir

    def __exit__(self, *exc):
        for p in self.patches:
            p.stop()
        shutil.rmtree(self.dir, ignore_errors=True)


class Core(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = model_ctx()

    def test_core_capabilities_are_never_lost(self):
        cards = {c.name: c for c in self.ctx.store.cards("capability")}
        self.assertEqual(sorted(set(CORE) - set(cards)), [], "a core capability card was removed")
        for name in CORE:
            self.assertTrue(cards[name].get("core"), name)
            self.assertIn(cards[name]["check"], K.CHECKS, name)
        r = K.run(self.ctx, SEED)
        self.assertEqual(r["failing"], [], {n: c.get("reason") for n, c in r["capabilities"].items()
                                            if c["status"] == "fail"} | {"seed": SEED})
        self.assertEqual(r["status"], "pass")
        # a capability that stops behaving fails the run, by name
        def broken(ctx, seed):
            raise K.Lost("planted: the derivation is gone")
        with mock.patch.dict(K.CHECKS, {"logic": broken}):
            r = K.run(self.ctx, SEED, names=["logic"])
        self.assertEqual((r["status"], r["failing"]), ("fail", ["logic"]))
        self.assertIn("planted", r["capabilities"]["logic"]["reason"])
        # every law is carried by a capability; drop the carrier of one law and the self theory names it
        prog = selflogic.store_facts(self.ctx.store)
        from cardmodel.lang.compile import compile_file
        mod = compile_file(selflogic.self_source(), self.ctx.ops, self.ctx.store)
        prog.facts = [f for f in prog.facts if not (f[0] == "carries" and f[1][1] == "law/CM24_logic_carries")]
        prog.rules.extend(mod.program.rules)
        model = L.evaluate(prog, self.ctx.ops)
        self.assertTrue(any("CM24_logic_carries" in json.dumps(v, default=str) for v in model.violations))

    def test_verify_runs_the_capabilities(self):
        self.assertIn("capabilities", verify.QUICK)
        self.assertIn("integrity", verify.QUICK)


class SelfRun(unittest.TestCase):
    def test_self_run_finds_flaws_and_ranks_them(self):
        def broken(ctx, seed):
            raise K.Lost("planted: no world")
        with IsolatedSelf() as d, mock.patch.dict(K.CHECKS, {"world": broken}):
            rep = selfrun.cycle(only=["capabilities", "integrity", "goals"], say=lambda m: None)
            self.assertEqual(rep["status"], "fail", seed_note(self))
            world = next(p for p in rep["plan"] if p["area"] == "capability/world")
            self.assertEqual((world["severity"], world["kind"]), ("critical", "flaw"))
            self.assertIn("planted", world["evidence"])
            later = [p["rank"] for p in rep["plan"] if p["severity"] != "critical"]
            self.assertTrue(all(world["rank"] < r for r in later), "a lost capability ranks above every weakness")
            kinds = {f["kind"] for f in rep["findings"]}
            self.assertEqual(kinds, {"flaw", "weakness", "strength"})
            self.assertTrue((d / "SELF.md").read_text(encoding="utf-8").count("capability/world"))
            self.assertEqual(len(list((d / "runs").glob("*.json"))), 1)
            state = json.loads((d / "state.json").read_text(encoding="utf-8"))
            self.assertEqual(state["steps"]["capabilities"]["status"], "fail")
            # the next cycle compares goals with this one
            again = selfrun.cycle(only=["goals"], say=lambda m: None)
            self.assertEqual(again["trend"]["previous"], rep["started"])
            # one cycle at a time
            lock = selfrun.Lock()
            self.assertTrue(lock.acquire())
            try:
                self.assertEqual(selfrun.cycle(only=["goals"], say=lambda m: None)["status"], "busy")
            finally:
                lock.release()

    def test_steps_are_due_by_time_and_by_change(self):
        ctx = model_ctx()
        steps = {s["name"]: s for s in selfrun.steps(ctx)}
        self.assertEqual(sorted(s["run"] for s in steps.values() if s["run"] not in selfrun.STEPS), [])
        now = selfrun._now()
        state = {}
        self.assertTrue(selfrun.due(steps["capabilities"], state, ctx, now)[0])
        state = {"steps": {"verify_full": {"at": selfrun._iso(now)}}}
        self.assertFalse(selfrun.due(steps["verify_full"], state, ctx, now)[0])
        state = {}
        ok, why = selfrun.due(steps["laws"], state, ctx, now)
        self.assertFalse(ok)
        self.assertIn("baseline", why)
        state = {"steps": {"laws": {"hashes": {"op": "something else"}}}}
        ok, why = selfrun.due(steps["laws"], state, ctx, now)
        self.assertTrue(ok)
        self.assertIn("op changed", why)

    def test_learned_cards_that_break_verify_are_quarantined(self):
        with IsolatedSelf() as d:
            w = selfrun.write_ctx()
            w.store.save({"name": "bad_link", "category": "fact", "theory": "t", "pred": "p", "args": [1],
                          "depends_on": ["fact/no_such_card_anywhere"]}, layer="self")
            c = selfrun.Cycle(SEED, selfrun.config(), {}, lambda m: None)
            self.assertIsNotNone(c.ctx.store.get("fact/bad_link"))
            rep = verify.run(c.ctx, seed=SEED, only=["kernel"], save=False)
            self.assertEqual(rep["sections"]["kernel"]["status"], "fail")
            moved = selfrun.quarantine_if_cause(c, ["kernel"])
            self.assertIsNotNone(moved)
            self.assertTrue((moved / "why.json").is_file())
            self.assertFalse((d / "cards").exists())
            self.assertIsNone(c.ctx.store.get("fact/bad_link"))

    def test_use_starts_a_background_cycle_when_due(self):
        started = []
        with IsolatedSelf(), mock.patch.dict(os.environ, {"CARDMODEL_SELF": "1"}), \
                mock.patch("cardmodel.kernel.resources.spawn_background",
                           side_effect=lambda args, **kw: started.append(args) or 4242):
            self.assertIsNone(selfrun.maybe_start("verify"))          # self-maintenance commands never start one
            self.assertEqual(selfrun.maybe_start("run"), 4242)
            self.assertEqual(started[0][-3:], ["self", "run", "--auto"])
            self.assertIsNone(selfrun.maybe_start("run"))             # not again within the interval
        with mock.patch.dict(os.environ, {"CARDMODEL_SELF": "0"}):
            self.assertIsNone(selfrun.maybe_start("run"))

    def test_status_cli(self):
        import subprocess
        r = subprocess.run([*CLI, "self", "status"], cwd=ROOT, capture_output=True, text=True, timeout=300)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("self layer off", r.stdout)


class OneProgram(unittest.TestCase):
    def test_one_program_integrity(self):
        ctx = model_ctx()
        r = integrity.check(ctx)
        self.assertEqual(r["problems"], [])
        self.assertGreaterEqual(r["laws"], 39)
        # planted: a second law with an existing number, carried by nothing; a command missing from the help
        d = Path(tempfile.mkdtemp(prefix="cardmodel_integrity_"))
        try:
            st = Store([("model", paths.model_cards()), ("scratch", d)], readonly={"model"})
            st.save({"name": "CM05_a_second_cm05", "category": "law", "statement": "x", "origins": ["planted"],
                     "witness": "tests/test_self.py::test_one_program_integrity"}, layer="scratch")
            commands, doc = integrity.cli_commands()
            with mock.patch.object(integrity, "cli_commands", return_value=(commands + ["undocumented_cmd"], doc)):
                problems = integrity.check(Ctx(st))["problems"]
        finally:
            shutil.rmtree(d, ignore_errors=True)
        text = "\n".join(problems)
        self.assertIn("law number CM05 is used twice", text)
        self.assertIn("law/CM05_a_second_cm05 is carried by no capability", text)
        self.assertIn("'undocumented_cmd' is registered but not in the CLI help", text)
        self.assertTrue(integrity.MARKERS.search("text\n<<<<<<< HEAD\nmine\n"))
        self.assertTrue(integrity.PUBLISHING.search('subprocess.run(["git", "push"])'))


if __name__ == "__main__":
    unittest.main()
