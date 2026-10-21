"""projects — every project keeps a detailed card, and keeps it current (law CM41).

A ``project`` card holds two kinds of fields. What to watch (``repo``, ``paths``, ``games``, ``metrics``, ``docs``)
is read by the hub (cardmodel/arcade/hub.py), which computes the status. The detail is written by the session that
owns the project: ``goal``, ``standing`` (where it stands now; ``status`` is every card's lifecycle field), ``done``, ``in_progress``, ``left``, ``blockers``, ``next_steps``,
``user_actions`` (what the user must do or decide, each with what it unblocks), ``owner`` (the owning session),
``branches`` (where its work lives) and ``updated`` (when the detail was last revised, ISO date and time).

A project kept in another repository (``repo``) may keep its detail there, committed, in ``.cardmodel/project.json``.
It is read with ``git show HEAD:...`` and is the owner's word over the card here.

``check`` fails on:
  missing      a required detail field is absent or of the wrong shape
  stale        a commit touching the project's paths (on the checked-out branch; any commit for another repository)
               is more than GRACE_H hours newer than ``updated``
  unlisted     a branch with unmerged commits from the last 7 days that no card lists in ``branches`` (on main:
               every such branch; on a branch: the branch itself)

``waiting_on_you`` gathers every card's ``user_actions``, ordered by how much each unblocks.

Honest limits (L1): stale means "changed since the card was revised", not "the card is wrong"; a session can revise
``updated`` without revising the content, and only reading the card shows that.
"""
from __future__ import annotations

import fnmatch
import json
import os
import time
from pathlib import Path

from ..kernel import paths

GRACE_H = 24
LISTS = ("done", "in_progress", "left", "blockers", "next_steps", "user_actions", "branches")
TEXTS = ("goal", "standing", "updated")
EXTERNAL_FILE = ".cardmodel/project.json"


def _hub():
    from ..arcade import hub
    return hub


def repo_of(card) -> Path:
    return Path(os.path.expanduser(card["repo"])) if card.get("repo") else paths.home()


def external_detail(card) -> dict | None:
    """The detail a project keeps in its own repository (committed), if it does."""
    if not card.get("repo"):
        return None
    root = repo_of(card)
    if not (root / ".git").exists():
        return None
    text = _hub().git(root, "show", f"HEAD:{EXTERNAL_FILE}")
    if not text:
        return None
    try:
        data = json.loads(text)
    except ValueError:
        return {"_error": f"{root.name}/{EXTERNAL_FILE} is not JSON"}
    return data if isinstance(data, dict) else {"_error": f"{root.name}/{EXTERNAL_FILE} is not an object"}


def detail(card) -> dict:
    """The project's detail: the card's fields, overridden by what the owner keeps in its own repository."""
    out = {k: card.get(k) for k in (*TEXTS, *LISTS, "owner")}
    ext = external_detail(card)
    if ext:
        out.update({k: v for k, v in ext.items() if k in (*TEXTS, *LISTS, "owner", "_error")})
        out["source"] = f"{repo_of(card).name}/{EXTERNAL_FILE}"
    else:
        out["source"] = f"cards/project/{card.name}"
    return out


def shape_problems(name: str, d: dict) -> list[str]:
    out = []
    if d.get("_error"):
        out.append(f"project {name}: {d['_error']}")
    for k in TEXTS:
        if not isinstance(d.get(k), str) or not d[k].strip():
            out.append(f"project {name}: `{k}` is missing")
    for k in LISTS:
        if not isinstance(d.get(k), list):
            out.append(f"project {name}: `{k}` is missing (a list, empty when there is nothing)")
    owner = d.get("owner")
    if not isinstance(owner, dict) or not owner.get("session"):
        out.append(f"project {name}: `owner` is missing (the owning session: {{\"session\": id, \"name\": ...}})")
    for a in d.get("user_actions") or []:
        if not isinstance(a, dict) or not a.get("action") or not isinstance(a.get("unblocks", []), list):
            out.append(f"project {name}: a user action needs `action`, `why` and `unblocks` (a list)")
            break
    if isinstance(d.get("updated"), str) and _hub()._ts(d["updated"]) is None:
        out.append(f"project {name}: `updated` is not an ISO date and time: {d['updated']!r}")
    return out


def last_change(card) -> tuple[int | None, str]:
    """When the project last changed: the newest commit touching its paths on HEAD (another repository: any)."""
    hub = _hub()
    root = repo_of(card)
    if not (root / ".git").exists():
        return None, ""
    pats = [] if card.get("repo") else (card.get("paths") or [])
    out = hub.git(root, "log", "-1", "--format=%ct%x1f%h%x1f%s", "HEAD", "--", *hub._pathspecs(pats))
    if not out or not out.strip():
        return None, ""
    t, h, title = (out.strip().split("\x1f") + ["", ""])[:3]
    return int(t), f"{h} {title}"


def active_branches(root: Path) -> tuple[str, str, list[str]]:
    """(main, current branch, branches with unmerged commits from the last 7 days)."""
    hub = _hub()
    main = "main" if hub.git(root, "rev-parse", "--verify", "--quiet", "refs/heads/main") else "master"
    head = (hub.git(root, "rev-parse", "--abbrev-ref", "HEAD") or "").strip()
    cut = time.time() - 7 * 86400
    out = []
    for line in (hub.git(root, "for-each-ref", "--format=%(refname:short)%1f%(committerdate:unix)", "refs/heads") or "").splitlines():
        name, _, t = line.partition("\x1f")
        if name == main or not t or int(t) < cut:
            continue
        ahead = (hub.git(root, "rev-list", "--count", f"{main}..{name}") or "0").strip()
        if ahead.isdigit() and int(ahead) > 0:
            out.append(name)
    return main, head, out


def check(ctx, now: float | None = None) -> dict:
    hub = _hub()
    now = time.time() if now is None else now
    problems, rows = [], {}
    cards = sorted(ctx.store.cards("project"), key=lambda c: c.name)
    for card in cards:
        d = detail(card)
        probs = shape_problems(card.name, d)
        changed, what = last_change(card)
        upd = hub._ts(d.get("updated")) if isinstance(d.get("updated"), str) else None
        stale = bool(changed and upd is not None and changed - upd > GRACE_H * 3600)
        if stale:
            probs.append(f"project {card.name}: stale, its card was revised {d['updated']} but `{what}` changed it "
                         f"{time.strftime('%Y-%m-%d %H:%M', time.localtime(changed))} ({d['source']})")
        rows[card.name] = {"source": d["source"], "updated": d.get("updated"), "last_change": changed,
                           "stale": stale, "problems": probs}
        problems += probs
    root = paths.home()
    if (root / ".git").exists():
        main, head, branches = active_branches(root)
        must = branches if head == main else [b for b in branches if b == head]
        pats = [p for c in cards for p in (detail(c).get("branches") or [])]
        for b in must:
            if not any(fnmatch.fnmatch(b, p) for p in pats):
                problems.append(f"branch {b} has unmerged work from the last week that no project card lists in "
                                f"`branches`")
    return {"status": "fail" if problems else ("pass" if cards else "vacuous"), "problems": problems,
            "projects": rows, "cards": len(cards)}


def waiting_on_you(ctx) -> list[dict]:
    """Every user action the project cards name, most unblocking first."""
    out = []
    for card in ctx.store.cards("project"):
        d = detail(card)
        for a in d.get("user_actions") or []:
            if isinstance(a, dict) and a.get("action"):
                out.append({"action": a["action"], "why": a.get("why", ""), "unblocks": list(a.get("unblocks") or []),
                            "project": card.name, "title": card.get("title", card.name),
                            "owner": (d.get("owner") or {}).get("name")})
    return sorted(out, key=lambda a: (-len(a["unblocks"]), a["project"]))


__all__ = ["GRACE_H", "check", "detail", "last_change", "waiting_on_you"]
