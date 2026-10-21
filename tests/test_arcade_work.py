"""Work in progress in the arcade: every worktree of the repository is a branch the launcher shows (its commits,
its uncommitted changes, its programs), and a program's version on a branch is served, built and installed from
there. Here the repository is a throwaway one: a main checkout with a game card at 1.0.0 and a worktree whose
branch has it at 1.1.0, with a stand-in for that branch's own ``bin/cardmodel`` (it lists and builds a depot)."""
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from helpers import model_ctx

from cardmodel.arcade import build as B
from cardmodel.arcade import server as SV
from cardmodel.arcade import work as W

FAKE_CLI = r'''#!/usr/bin/env python3
"""A stand-in for the branch's own cardmodel: `--json arcade list` and `--json arcade build demo`."""
import hashlib, json, sys, time
from pathlib import Path
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
from depot import make
if sys.argv[1:] == ["--json", "arcade", "list"]:
    print(json.dumps([{"id": "demo", "title": "Demo", "version": "1.1.0", "built": "1.1.0+aaaaaaaaaaaa",
                       "build_due": (root / "changed").exists()}]))
elif sys.argv[1:3] == ["--json", "arcade"] and sys.argv[3] == "build":
    print("[1/6] compiling the cards", file=sys.stderr, flush=True)
    if (root / "fail").exists():
        print("ValueError: list.index(x): x not in list", file=sys.stderr)
        sys.exit(1)
    time.sleep(0.3)
    print("[6/6] writing the depot", file=sys.stderr, flush=True)
    print(json.dumps(make(root, "bbbbbbbbbbbb", b"demo, built again")))
else:
    sys.exit(2)
'''

DEPOT = r'''import hashlib, json, time
from pathlib import Path


def make(root, build, data):
    """A depot as arcade/build.py writes one: a manifest, its chunks, its pictures, the latest pointer."""
    arc = root / "state" / "arcade"
    sha = hashlib.sha256(data).hexdigest()
    (arc / "chunks").mkdir(parents=True, exist_ok=True)
    (arc / "chunks" / sha).write_bytes(data)
    d = arc / "depots" / "demo" / f"1.1.0+{build}"
    (d / "media").mkdir(parents=True, exist_ok=True)
    (d / "media" / "icon.png").write_bytes(b"\x89PNG demo icon")
    info = {"id": "demo", "title": "Demo", "version": "1.1.0", "build": build, "source": "x", "app": "Demo.app",
            "executable": "Demo.app/Contents/MacOS/Demo", "created": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "seconds": 0.3, "media": ["icon.png"], "size": len(data), "chunks": 1,
            "files": [{"path": "Demo.app/Contents/MacOS/Demo", "size": len(data), "sha256": sha, "executable": True,
                       "chunks": [{"sha256": sha, "size": len(data)}]}]}
    (d / "manifest.json").write_text(json.dumps(info), encoding="utf-8")
    (arc / "depots" / "demo" / "latest").write_text(d.name, encoding="utf-8")
    return info
'''


def git(cwd, *args):
    return subprocess.run(["git", "-c", "user.email=test@example.invalid", "-c", "user.name=test",
                           "-c", "commit.gpgsign=false", *args], cwd=cwd, check=True, capture_output=True,
                          text=True).stdout


def card(version):
    return json.dumps({"name": "demo", "category": "game", "title": "Demo", "version": version, "developer": "t",
                       "changelog": [{"version": version, "title": "v" + version, "notes": ["a note"]}]})


class WorkInProgress(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = model_ctx()
        cls.tmp = Path(tempfile.mkdtemp(prefix="cardmodel_work_"))
        main = cls.tmp / "repo"
        (main / "cards" / "game" / "demo").mkdir(parents=True)
        (main / "cards" / "game" / "demo" / "card.json").write_text(card("1.0.0"))
        (main / ".gitignore").write_text("state/\n__pycache__/\nchanged\nfail\n")
        git(main, "init", "-q", "-b", "main")
        git(main, "add", "-A")
        git(main, "commit", "-q", "-m", "Demo 1.0.0")
        git(main, "worktree", "add", "-q", "-b", "claude/demo-branch", str(cls.tmp / "wt2"))
        wt = cls.tmp / "wt2"
        (wt / "cards" / "game" / "demo" / "card.json").write_text(card("1.1.0"))
        (wt / "bin").mkdir()
        (wt / "bin" / "cardmodel").write_text(FAKE_CLI)
        (wt / "bin" / "cardmodel").chmod(0o755)
        (wt / "depot.py").write_text(DEPOT)
        git(wt, "add", "-A")
        git(wt, "commit", "-q", "-m", "Demo 1.1.0: a newer version on a branch")
        cls.hash = git(wt, "rev-parse", "--short", "HEAD").strip()
        (wt / "notes.txt").write_text("not committed yet")
        ns: dict = {}
        exec(DEPOT, ns)  # noqa: S102 -- the same depot writer the stand-in uses
        cls.first = ns["make"](wt, "aaaaaaaaaaaa", b"demo, first build")
        cls.main, cls.wt = main, wt
        cls.env = {k: os.environ.get(k) for k in ("CARDMODEL_HOME", "CARDMODEL_BRANCHES")}
        os.environ["CARDMODEL_HOME"] = str(main)
        os.environ.pop("CARDMODEL_BRANCHES", None)
        W._cache.update(trees=None, data=None)
        W._status.clear()
        cls.old_root = B.ROOT_OVERRIDE
        B.ROOT_OVERRIDE = cls.tmp / "service-state"        # the service's own depots, errors and build logs
        SV.Handler.ctx = cls.ctx
        SV.Handler.ui_dir = None
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), SV.Handler)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        for k, v in cls.env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        W._cache.update(trees=None, data=None)
        W._status.clear()
        B.ROOT_OVERRIDE = cls.old_root
        SV._seen["mark"] = None
        cls.ctx.store.invalidate()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def get(self, path, raw=False):
        with urllib.request.urlopen(self.base + path, timeout=30) as r:
            data = r.read()
        return data if raw else json.loads(data)

    def refused(self, path):
        with self.assertRaises(urllib.error.HTTPError) as cm:
            self.get(path)
        self.assertEqual(cm.exception.code, 404, path)
        cm.exception.close()

    def post(self, path):
        req = urllib.request.Request(self.base + path, method="POST")
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())

    def wait_build(self, path):
        for _ in range(200):
            st = self.get(path)
            if st["state"] != "building":
                return st
            time.sleep(0.1)
        self.fail("the branch build did not finish")

    def test_reading_the_branches_writes_nothing_in_git(self):
        """Other sessions commit in these worktrees: reading them must not touch an index or take index.lock."""
        git_dir = self.main / ".git"
        before = {p: p.stat().st_mtime_ns for p in git_dir.rglob("*") if p.is_file()}
        W.overview(force=True)
        self.get("/api/work?force=1")
        W.commit("wt2", self.hash)
        after = {p: p.stat().st_mtime_ns for p in git_dir.rglob("*") if p.is_file()}
        self.assertEqual(before, after)

    def test_every_worktree_is_a_branch_with_its_work(self):
        trees = {w["name"]: w for w in W.worktrees()}
        self.assertEqual(set(trees), {"repo", "wt2"})
        self.assertTrue(trees["repo"]["own"])
        self.assertEqual(trees["wt2"]["branch"], "claude/demo-branch")
        work = {w["name"]: w for w in self.get("/api/work?force=1")["worktrees"]}
        w2 = work["wt2"]
        self.assertEqual(w2["ahead_count"], 1)
        self.assertEqual(w2["ahead"][0]["subject"], "Demo 1.1.0: a newer version on a branch")
        self.assertIn("notes.txt", w2["uncommitted_files"])
        self.assertIn("game demo", w2["areas"])
        self.assertEqual([(p["id"], p["version"]) for p in w2["programs"]], [("demo", "1.1.0")])
        c = self.get(f"/api/work/wt2/commit/{self.hash}")
        self.assertIn("cards/game/demo/card.json", [f["path"] for f in c["files"]])
        for bad in ("/api/work/nope/commit/" + self.hash, "/api/work/wt2/commit/not-a-hash"):
            self.refused(bad)

    def test_areas_name_what_changed(self):
        self.assertEqual(W.areas(["cards/game/demo/card.json", "cards/game/demo/logic.card", "cardmodel/arcade/x.py",
                                  "README.md", "cards/_versions/demo/1.json"]), ["game demo", "engine arcade", "docs"])

    def test_a_branch_version_is_listed_served_and_asked(self):
        cat = {g["id"]: g for g in self.get("/api/catalog")}
        demo = cat["demo"]                       # only the branch has it (the service's own store does not)
        self.assertEqual(demo["worktree"], "wt2")
        self.assertEqual(demo["branch"], "claude/demo-branch")
        self.assertEqual(demo["build"]["build"], W.latest_manifest(self.wt, "demo")["build"])
        self.assertTrue(demo["build"]["manifest"].endswith("?wt=wt2"))
        self.assertEqual(cat["vector_duel"]["branches"], [], "the throwaway branch has no Vector Duel")
        W.refresh_status(wait=True)            # the branch's own `arcade list`
        g = self.get("/api/game/demo?branch=wt2")
        self.assertTrue(g["status_known"])
        self.assertIs(g["build_due"], False)
        man = self.get(g["build"]["manifest"])
        sha = man["files"][0]["chunks"][0]["sha256"]
        data = self.get("/chunk/" + sha, raw=True)          # found in the branch's chunk store
        self.assertEqual(hashlib.sha256(data).hexdigest(), sha)
        self.assertTrue(self.get(g["media"]["icon"], raw=True).startswith(b"\x89PNG"))
        for bad in ("/media/demo/1.1.0+aaaaaaaaaaaa/icon.png?wt=../repo", "/depot/demo/x/manifest.json?wt=nope"):
            self.refused(bad)

    def test_a_branch_builds_with_its_own_cardmodel_and_a_failure_is_kept(self):
        st = self.post("/api/build/demo?branch=wt2")
        self.assertEqual(st["worktree"], "wt2")
        st = self.wait_build("/api/build/demo?branch=wt2")
        self.assertEqual(st["state"], "done", st)
        self.assertEqual(st["build"], "bbbbbbbbbbbb")
        self.assertEqual(self.get("/api/game/demo?branch=wt2")["build"]["build"], "bbbbbbbbbbbb")
        self.assertTrue((B.ROOT_OVERRIDE / "branch-builds" / "wt2-demo.log").is_file())
        (self.wt / "fail").write_text("")
        try:
            self.post("/api/build/demo?branch=wt2")
            st = self.wait_build("/api/build/demo?branch=wt2")
            self.assertEqual(st["state"], "error")
            self.assertIn("ValueError", st["error"])
            g = self.get("/api/game/demo?branch=wt2")
            self.assertIn("ValueError", g["build_error"])
            self.assertEqual(g["build"]["build"], "bbbbbbbbbbbb", "the last good build stays installable")
            kept = json.loads((B.ROOT_OVERRIDE / "build-errors.json").read_text())
            self.assertIn("demo@wt2", kept)
            SV._builds.pop("demo@wt2", None)       # as after a restart of the service: the file remembers it
            self.assertIn("ValueError", self.get("/api/game/demo?branch=wt2")["build_error"])
        finally:
            (self.wt / "fail").unlink()


if __name__ == "__main__":
    unittest.main()
