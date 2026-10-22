#!/usr/bin/env python3
"""goal_floors — record each goal's floor, the hardest target it has been held to (integrity, law CM39).

A floor is raised when a goal's target got stricter, and set for a goal that has none. It is never lowered by this
tool on its own: a goal made easier keeps failing integrity until its card carries an amendment {from, to, reason},
and then this tool records the amended target as the new floor, with the reason.

Run: ``python3 -B tools/goal_floors.py`` (prints what changed; ``--dry-run`` writes nothing).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cardmodel.engines import integrity as I  # noqa: E402
from cardmodel.kernel.store import open_store  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    store = open_store(project=False)
    root = store.layer_root("model")
    d = root / "goal_floor"
    d.mkdir(parents=True, exist_ok=True)
    meta = d / "_category.json"
    if not meta.exists():
        meta.write_text(json.dumps({"name": "goal_floor", "tier": 0, "defined_by": "tools/goal_floors.py",
                                    "description": "The hardest target each goal has been held to: integrity fails "
                                                   "on a goal made easier without an amendment."}, indent=2,
                                   sort_keys=True) + "\n", encoding="utf-8")
        store.invalidate()
    card = dict(store.get("goal_floor/floors") or {"name": "floors", "category": "goal_floor", "tier": 0,
                                                   "statement": "Each goal's floor: the hardest target accepted.",
                                                   "floors": {}})
    floors = dict(card.get("floors") or {})
    now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    changes = []
    for g in sorted(store.cards("goal"), key=lambda c: c.name):
        t, direction = g.get("target"), g.get("direction")
        f = floors.get(g.name)
        if f is None:
            floors[g.name] = {"target": t, "direction": direction, "since": now}
            changes.append(f"{g.name}: floor set at {t} ({direction})")
        elif I.easier(t, f, direction):
            am = g.get("amendment") or {}
            if am.get("from") == f.get("target") and am.get("to") == t and am.get("reason"):
                floors[g.name] = {"target": t, "direction": direction, "since": now, "amended": am}
                changes.append(f"{g.name}: lowered by amendment to {t} ({am['reason']})")
        elif t != f.get("target"):
            floors[g.name] = {"target": t, "direction": direction, "since": now}
            changes.append(f"{g.name}: floor raised from {f.get('target')} to {t}")
    print("\n".join(changes) or "no change")
    if changes and not args.dry_run:
        card["floors"] = floors
        store.save(card, layer="model")
    return 0


if __name__ == "__main__":
    sys.exit(main())
