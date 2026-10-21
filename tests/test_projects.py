"""Every project keeps a detailed, current card (CM41): missing detail, a stale card, an unlisted branch fail."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from test_hub import World, sh

from cardmodel.engines import projects as PJ

DETAIL = {"goal": "g", "standing": "s", "done": [], "in_progress": [], "left": [], "blockers": [], "next_steps": [],
          "user_actions": [], "owner": {"session": "local_x", "name": "x"}, "branches": ["feature"],
          "updated": "2099-01-01T00:00:00+00:00"}


class ProjectCards(unittest.TestCase):
    def save(self, w, name, **fields):
        w.store.save({"name": name, "category": "project", "title": name.upper(), "kind": "game", "statement": "s",
                      "paths": ["proj"], **fields})
        w.store.invalidate()

    def test_missing_or_stale_project_cards_fail(self):
        with World() as w:
            # the World's cards have no detail at all: every field is reported, and the feature branch is unlisted
            r = PJ.check(w.ctx)
            self.assertEqual(r["status"], "fail")
            text = "\n".join(r["problems"])
            for field in ("goal", "standing", "done", "user_actions", "owner", "updated"):
                self.assertIn(f"project p: `{field}` is missing", text)
            self.assertIn("branch feature has unmerged work", text)
            # complete, revised after the last change: nothing to report for p
            self.save(w, "p", **DETAIL)
            self.save(w, "q", **{**DETAIL, "branches": []})
            self.assertEqual(PJ.check(w.ctx)["problems"], [])
            # revised before a change to its paths, by more than the grace: stale
            self.save(w, "p", **{**DETAIL, "updated": "2001-01-01T00:00:00+00:00"})
            r = PJ.check(w.ctx)
            self.assertTrue(r["projects"]["p"]["stale"])
            self.assertTrue(any("project p: stale" in x for x in r["problems"]))
            # a change elsewhere does not make it stale; a branch no card lists does fail
            self.save(w, "p", **{**DETAIL, "branches": []})
            self.assertIn("branch feature has unmerged work from the last week that no project card lists in "
                          "`branches`", PJ.check(w.ctx)["problems"])

    def test_detail_in_another_repository_is_read_committed(self):
        with World() as w:
            other = Path(tempfile.mkdtemp(prefix="cardmodel_other_"))
            try:
                sh(other, "init", "-q", "-b", "main")
                (other / ".cardmodel").mkdir()
                (other / ".cardmodel" / "project.json").write_text(json.dumps({**DETAIL, "standing": "committed"}))
                sh(other, "add", "-A")
                sh(other, "commit", "-q", "-m", "detail")
                (other / ".cardmodel" / "project.json").write_text(json.dumps({**DETAIL, "standing": "not committed"}))
                self.save(w, "ext", repo=str(other), **{k: v for k, v in DETAIL.items() if k != "standing"},
                          standing="ours")
                d = PJ.detail(w.store.get("project/ext"))
                self.assertEqual(d["standing"], "committed")
                self.assertEqual(d["source"], f"{other.name}/.cardmodel/project.json")
            finally:
                shutil.rmtree(other, ignore_errors=True)

    def test_waiting_on_you_is_ordered_by_what_it_unblocks(self):
        with World() as w:
            one = {"action": "small", "why": "w", "unblocks": ["a"]}
            three = {"action": "big", "why": "w", "unblocks": ["a", "b", "c"]}
            self.save(w, "p", **{**DETAIL, "user_actions": [one]})
            self.save(w, "q", **{**DETAIL, "user_actions": [three]})
            self.assertEqual([a["action"] for a in PJ.waiting_on_you(w.ctx)], ["big", "small"])


if __name__ == "__main__":
    unittest.main()
