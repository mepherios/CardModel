"""Shared test helpers: the model store, temporary projects, seeds (L28: fresh seed per run, printed, overridable)."""
from __future__ import annotations

import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# tests see the model's cards only: no self layer, no background self-run cycles (CM38), in this process and in
# every CLI subprocess a test starts (they inherit the environment)
os.environ["CARDMODEL_SELF"] = "0"
# the arcade service lists only its own checkout's programs, not the other worktrees' (tests/test_arcade_work.py
# sets up worktrees of its own)
os.environ["CARDMODEL_BRANCHES"] = "0"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cardmodel.engines.context import Ctx  # noqa: E402
from cardmodel.kernel.store import open_store  # noqa: E402

SEED = int(os.environ.get("CARDMODEL_TEST_SEED", random.SystemRandom().randrange(2**32)))
SLOW = os.environ.get("CARDMODEL_SLOW") == "1"
CLI = [sys.executable, "-B", "-m", "cardmodel"]


def model_ctx() -> Ctx:
    return Ctx(open_store(project=False))


class TempProject:
    """A throwaway project with its own .cardmodel/ (model cards stay read-only)."""

    def __init__(self, files: dict[str, str] | None = None):
        self.dir = Path(tempfile.mkdtemp(prefix="cardmodel_test_"))
        (self.dir / ".cardmodel" / "cards").mkdir(parents=True)
        (self.dir / ".cardmodel" / "config.json").write_text(json.dumps({"name": "t"}), encoding="utf-8")
        for rel, text in (files or {}).items():
            p = self.dir / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")

    def ctx(self) -> Ctx:
        return Ctx(open_store(project=self.dir))

    def cli(self, *args, timeout: int = 600, env: dict | None = None) -> subprocess.CompletedProcess:
        e = dict(os.environ, PYTHONPATH=str(ROOT), PYTHONDONTWRITEBYTECODE="1")
        e.update(env or {})
        return subprocess.run([*CLI, *args], cwd=self.dir, capture_output=True, text=True, timeout=timeout, env=e)

    def cleanup(self) -> None:
        shutil.rmtree(self.dir, ignore_errors=True)


def seed_note(test) -> str:
    return f"(seed {SEED}; reproduce with CARDMODEL_TEST_SEED={SEED})"
