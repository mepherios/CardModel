"""The store's In progress page: status computed from git and records, read-only, pushed live, early access apart."""
import hashlib
import json
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

from helpers import ROOT  # noqa: F401  (puts the repository on sys.path)

from cardmodel.arcade import hub as H
from cardmodel.arcade import server
from cardmodel.engines.context import Ctx
from cardmodel.kernel import paths
from cardmodel.kernel.store import Store


def sh(cwd, *args):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd, check=True,
                          capture_output=True, text=True, timeout=60).stdout


class World:
    """A repository with a main branch, a feature branch checked out in a worktree under .claude/worktrees, an
    uncommitted change there, and a scratch card store holding one project card."""

    def __enter__(self):
        self.root = Path(tempfile.mkdtemp(prefix="cardmodel_hub_"))
        r = self.root
        sh(r, "init", "-q", "-b", "main")
        for rel, text in {"proj/a.py": "a = 1\n", "other/b.py": "b = 1\n", ".gitignore": "state/\n"}.items():
            (r / rel).parent.mkdir(parents=True, exist_ok=True)
            (r / rel).write_text(text)
        sh(r, "add", "-A")
        sh(r, "commit", "-q", "-m", "start")
        self.wt = r / ".claude" / "worktrees" / "wt1"
        sh(r, "worktree", "add", "-q", "-b", "feature", str(self.wt))
        (self.wt / "proj" / "a.py").write_text("a = 2\n")
        sh(self.wt, "commit", "-q", "-am", "feature work on proj")
        (self.wt / "proj" / "new.py").write_text("x = 1\n")          # uncommitted: someone is at work
        cards = r / "cards"
        self.store = Store([("model", cards)])
        self.store.save({"name": "p", "category": "project", "title": "P", "kind": "game", "statement": "s",
                         "paths": ["proj"], "games": ["g1"]})
        self.store.save({"name": "q", "category": "project", "title": "Q", "kind": "research", "statement": "s",
                         "paths": ["nothing_here/*"]})
        self.ctx = Ctx(self.store)
        self.patch = mock.patch.object(paths, "home", lambda: r)
        self.patch.start()
        return self

    def __exit__(self, *exc):
        self.patch.stop()
        shutil.rmtree(self.root, ignore_errors=True)


class Status(unittest.TestCase):
    def test_status_is_computed_from_git_and_state(self):
        with World() as w:
            h = H.Hub(w.ctx)
            h.refresh(force=True)
            snap = h.current()
            p = next(x for x in snap["projects"] if x["id"] == "p")
            self.assertEqual(p["phase"], "active now")
            self.assertEqual(p["last"]["title"], "start")
            self.assertEqual([(b["branch"], b["ahead"], b["worktree"]) for b in p["branches"]], [("feature", 1, "wt1")])
            self.assertEqual(p["changes"][0]["worktree"], "wt1")
            self.assertIn("proj/new.py", p["changes"][0]["sample"])
            q = next(x for x in snap["projects"] if x["id"] == "q")
            self.assertEqual(q["phase"], "not started here")
            kinds = {e["kind"] for e in snap["activity"]}
            self.assertEqual(kinds, {"commit"})
            self.assertEqual(sorted(e["title"] for e in snap["activity"]), ["feature work on proj", "start"])

    def test_git_reads_never_write(self):
        with World() as w:
            (w.wt / "proj" / "a.py").touch()             # a stale index entry: a plain `git status` would rewrite it
            def gitdir_state():
                out = {}
                for f in sorted((w.root / ".git").rglob("*")):
                    if f.is_file():
                        out[str(f)] = (f.stat().st_mtime_ns, hashlib.sha256(f.read_bytes()).hexdigest())
                return out
            before = gitdir_state()
            h = H.Hub(w.ctx)
            h.refresh(force=True)
            h.refresh(dirty=True)
            self.assertEqual(gitdir_state(), before, "the hub changed something under .git")


class Live(unittest.TestCase):
    def test_changes_are_pushed(self):
        with World() as w, mock.patch.object(H, "POLL_S", 0.2):
            h = H.Hub(w.ctx).start()
            try:
                seen = h.current()["version"]
                sh(w.root, "commit", "-q", "--allow-empty", "-m", "a new commit on main")
                snap = h.wait(seen, timeout=20)
                deadline = time.time() + 20
                while snap is not None and "a new commit on main" not in [e["title"] for e in snap["activity"]] \
                        and time.time() < deadline:
                    snap = h.wait(snap["version"], timeout=5)
                self.assertIsNotNone(snap)
                self.assertIn("a new commit on main", [e["title"] for e in snap["activity"]])
            finally:
                h.stop.set()


class EarlyAccess(unittest.TestCase):
    def test_early_access_is_separate_and_installable(self):
        with World() as w:
            depot = w.wt / "state" / "arcade" / "depots" / "g1" / "0.2.0+abc123"
            depot.mkdir(parents=True)
            data = b"early bytes"
            sha = hashlib.sha256(data).hexdigest()
            chunks = w.wt / "state" / "arcade" / "chunks"
            chunks.mkdir(parents=True)
            (chunks / sha).write_bytes(data)
            (depot / "manifest.json").write_text(json.dumps({
                "id": "g1", "title": "G One", "version": "0.2.0", "build": "abc123", "created": "2026-10-22T00:00:00+0000",
                "size": len(data), "executable": "G", "app": "G.app", "files": [{"path": "f", "size": len(data),
                "sha256": sha, "chunks": [{"sha256": sha, "size": len(data)}]}], "media": []}))
            (depot.parent / "latest").write_text("0.2.0+abc123")
            h = H.Hub(w.ctx)
            h.refresh(force=True)
            with mock.patch.object(H, "_HUB", h):
                server.Handler.ctx, server.Handler.ui_dir = w.ctx, None
                httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
                threading.Thread(target=httpd.serve_forever, daemon=True).start()
                base = f"http://127.0.0.1:{httpd.server_address[1]}"
                get = lambda path: urllib.request.urlopen(base + path, timeout=30).read()  # noqa: E731
                try:
                    entry = json.loads(get("/api/game/g1.early.wt1"))
                    self.assertTrue(entry["early_access"])
                    self.assertFalse(entry["build_due"])
                    man = json.loads(get(entry["build"]["manifest"]))
                    self.assertEqual(man["build"], "abc123")
                    self.assertEqual(get(f"/chunk/{sha}"), data)
                    self.assertEqual(json.loads(get("/api/catalog")), [])          # the release channel is apart
                    dev = json.loads(get("/api/dev"))
                    self.assertEqual([e["id"] for e in dev["early"]], ["g1.early.wt1"])
                    p = next(x for x in dev["projects"] if x["id"] == "p")
                    self.assertEqual([b["channel"] for b in p["builds"]], ["early access"])
                    with self.assertRaises(urllib.error.HTTPError):
                        get("/early/wt1/g1/..%2F..%2Fsecrets/manifest.json")
                finally:
                    httpd.shutdown()
                    httpd.server_close()


if __name__ == "__main__":
    unittest.main()
