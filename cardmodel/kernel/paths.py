"""paths — where the model and a project keep their cards (L44 universality).

The model home is this repository: its ``cards/`` directory holds the
built-in registries. A *project store* is a ``.cardmodel/`` directory inside
any project, found by walking up from the current directory (like ``.git``).
Nothing here names a folder outside the repository or the project being
worked on, so the program runs from any directory without other folders.

Overrides (environment):
  CARDMODEL_HOME        model home (default: this repository)
  CARDMODEL_PROJECT     a project directory or its ``.cardmodel`` directory
  CARDMODEL_NO_PROJECT  "1" disables project discovery
"""
from __future__ import annotations

import os
from pathlib import Path

PROJECT_DIR = ".cardmodel"


def home() -> Path:
    env = os.environ.get("CARDMODEL_HOME")
    return Path(env).resolve() if env else Path(__file__).resolve().parents[2]


def model_cards() -> Path:
    return home() / "cards"


def self_cards() -> Path:
    """The self layer: cards the model's own cycles learned (engines/selfrun.py); untracked, under state/."""
    return home() / "state" / "self" / "cards"


def local_cards() -> Path:
    """The local layer: cards derived from data that stays on this machine (terms lifted from Unreal Engine's
    source, docs/INTEGRATION.md rule 8); untracked, under state/, written only when a writer names it."""
    return home() / "state" / "local" / "cards"


def state_dir(store_root: Path) -> Path:
    """Cache directory next to a cards root (not a source of truth; safe to delete)."""
    return store_root.parent / "state"


def find_project(start: str | os.PathLike | None = None) -> Path | None:
    """Return the ``.cardmodel`` directory governing ``start`` (or None)."""
    if os.environ.get("CARDMODEL_NO_PROJECT") == "1":
        return None
    env = os.environ.get("CARDMODEL_PROJECT")
    if env:
        p = Path(env).resolve()
        cand = p if p.name == PROJECT_DIR else p / PROJECT_DIR
        return cand if (cand / "config.json").is_file() else None
    p = Path(start or os.getcwd()).resolve()
    for q in (p, *p.parents):
        if (q / PROJECT_DIR / "config.json").is_file():
            return q / PROJECT_DIR
    return None
