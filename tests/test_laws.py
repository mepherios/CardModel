"""The laws are cards, and each one is witnessed here or names the test that witnesses it (CM20)."""
import ast
import re
import subprocess
import unittest

from helpers import CLI, ROOT, model_ctx

from cardmodel.engines.docs import laws_md

ENGINES = sorted((ROOT / "cardmodel").rglob("*.py"))
CLAIMING = ["engines/frontend_python.py", "engines/conformance.py", "engines/translate.py", "engines/rewrite.py",
            "engines/search.py", "engines/exprs.py", "engines/witness.py", "engines/redefs.py", "engines/observe.py",
            "engines/learn.py", "engines/optimize.py", "engines/probes.py", "engines/codegen.py", "engines/runners.py",
            "engines/selfcheck.py", "engines/improve.py", "engines/arena.py", "emit/lean.py", "kernel/schema.py",
            "machine/isa.py", "machine/build.py", "machine/native.py", "machine/bench.py", "machine/gb.py",
            "machine/survey.py", "machine/asm.py", "machine/lift.py", "machine/shell.py", "machine/diff.py",
            "machine/testroms.py", "machine/nds.py", "machine/lift_arm.py", "arcade/gen.py", "arcade/game.py",
            "arcade/build.py", "arcade/server.py", "arcade/cli.py", "arcade/client.py", "engines/witness_runner.py",
            "engines/realnorm.py", "unreal/engine.py", "unreal/units.py", "unreal/clangast.py", "unreal/lift.py",
            "unreal/scan.py", "unreal/distill.py", "unreal/witness.py", "unreal/atoms.py", "unreal/metrics.py"]
NO_LANGUAGE_BRANCHES = ["engines/codegen.py", "engines/runners.py", "engines/conformance.py", "engines/translate.py",
                        "engines/witness.py", "engines/verify.py", "engines/optimize.py", "machine/native.py",
                        "machine/build.py", "machine/isa.py", "machine/bench.py", "machine/gb.py", "machine/survey.py",
                        "machine/asm.py", "machine/lift.py", "machine/shell.py", "machine/diff.py",
                        "machine/testroms.py", "machine/nds.py", "machine/lift_arm.py", "arcade/gen.py",
                        "arcade/game.py", "arcade/build.py", "arcade/server.py", "arcade/cli.py", "arcade/client.py",
                        "engines/witness_runner.py"]


class Laws(unittest.TestCase):
    def test_every_law_names_an_existing_witness(self):
        laws = model_ctx().store.cards("law")
        self.assertGreaterEqual(len(laws), 20)
        for law in laws:
            path, _, test = law["witness"].partition("::")
            f = ROOT / path
            self.assertTrue(f.is_file(), law["witness"])
            self.assertRegex(f.read_text(encoding="utf-8"), rf"def {re.escape(test)}\(", law["witness"])

    def test_goals_md_matches_goal_cards(self):
        text = (ROOT / "GOALS.md").read_text(encoding="utf-8")
        for g in model_ctx().store.cards("goal"):
            row = next((l for l in text.splitlines() if f"`{g.name}`" in l), None)
            self.assertIsNotNone(row, f"GOALS.md has no row for {g.name}")
            target = g["target"]
            shown = str(int(target)) if float(target).is_integer() and g["direction"] == "higher" and target > 1 \
                else str(target)
            self.assertIn(shown, row, f"{g.name}: GOALS.md target differs from the card ({target})")

    def test_laws_md_in_sync(self):
        self.assertEqual((ROOT / "LAWS.md").read_text(encoding="utf-8"), laws_md(model_ctx().store),
                         "LAWS.md drifted from cards/law: run `cardmodel docs`")

    def test_engines_state_honest_limits(self):
        for rel in CLAIMING:
            doc = ast.get_docstring(ast.parse((ROOT / "cardmodel" / rel).read_text(encoding="utf-8"))) or ""
            self.assertIn("Honest limits", doc, rel)

    def test_verify_prints_and_accepts_seed(self):
        r = subprocess.run([*CLI, "--no-project", "verify", "--only", "rules", "--seed", "4242"], cwd=ROOT,
                           capture_output=True, text=True, timeout=300)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("seed 4242", r.stdout)

    def test_subprocesses_have_timeouts(self):
        missing = []
        for f in ENGINES:
            for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and \
                        node.func.attr in ("run", "Popen", "check_output", "call") and \
                        isinstance(node.func.value, ast.Name) and node.func.value.id == "subprocess":
                    if not any(k.arg == "timeout" for k in node.keywords):
                        if f.name == "resources.py" and node.func.attr == "Popen":
                            continue    # the governor's Popen is bounded by communicate(timeout=...) and a watchdog;
                            # spawn_detached starts the cycle, which bounds itself (budget, machine-wide lock)
                        missing.append(f"{f.relative_to(ROOT)}:{node.lineno}")
        self.assertEqual(missing, [])

    def test_no_publishing_calls(self):
        pattern = re.compile(r"git\"?,?\s*\"?push|\bgh\s+(pr|repo|gist)|twine upload|npm publish")
        hits = [str(f.relative_to(ROOT)) for f in [*ENGINES, ROOT / "bin" / "cardmodel"]
                if pattern.search(f.read_text(encoding="utf-8"))]
        self.assertEqual(hits, [])

    def test_engines_have_no_language_branches(self):
        names = {c.name for c in model_ctx().store.cards("language")} - {"python"}
        hits = []
        for rel in NO_LANGUAGE_BRANCHES:
            tree = ast.parse((ROOT / "cardmodel" / rel).read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in names:
                    hits.append(f"{rel}:{node.lineno} {node.value!r}")
        self.assertEqual(hits, [], "language knowledge belongs on language cards")


if __name__ == "__main__":
    unittest.main()
