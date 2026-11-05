"""integrity — the program is one piece (law CM39): what parallel work must not break when it merges.

Checks, each cheap and read-only:
  identifiers   law numbers (CMnn) and goal ids (G_Xn) are unique; a law's number is its identity
  carried       every law is carried by a capability card, and every capability's laws, tests and docs exist
  documented    every command the CLI registers is in its help, every verify section is in verify's docstring,
                every docs/*.md file is linked from README.md
  generated     LAWS.md is what the law cards generate; GOALS.md has a row for every goal card
  floors        no goal is easier than its floor (``floor/goals``: the hardest target each goal has had, recorded by
                ``cardmodel docs``): a lowered target, a changed metric or direction, or a removed goal needs its
                reason written down (an ``amended`` field on the goal card, a ``retired`` entry on the floor card)
  source        every module of the program parses (no leftover merge markers in code, docs or card sources)
  boundaries    no publishing calls (pushes to a remote, package or gist uploads) anywhere in the program (CM19)
  godel         no module outside engines/godel.py and godel1931.py does the core's algebra itself (primes, content,
                the zigzag, positional tokens, prime powers, sieves, similarity over content: GODEL_TARGET §7),
                except the known copies a capability card records with their owner and goal (CM50, G_A14)

Honest limits (L1): these checks see names and text, not meaning: two laws with different numbers that say the
same thing, or a command documented with the wrong arguments, pass. The tests and verify sections check
behaviour; this checks that the pieces are wired into one program and described.
"""
from __future__ import annotations

import argparse
import ast
import re
from pathlib import Path

from ..kernel import paths

MARKERS = re.compile(r"^(<{7}|={7}|>{7})( |$)", re.M)
# the same pattern as tests/test_laws.py::test_no_publishing_calls, spelled so that this line does not match itself
PUBLISHING = re.compile(r"git\"?,?\s*\"?pu[s]h|\bgh\s+(pr|repo|gist)|twin[e] upload|np[m] publish")
LAW_ID = re.compile(r"^(CM\d{2})_[a-z0-9_]+$")
FLOORS = "floor/goals"
FLOORS_STATEMENT = ("The floor of every goal: the hardest target it has had, its metric and direction. A goal may get "
                    "harder or be added freely; easier, changed or removed only with a reason (CM37: the core is "
                    "never lost; `cardmodel docs` records the floors, the integrity check holds them).")
GOAL_ID = re.compile(r"^(G_[A-Z]+\d+)_[a-z0-9_]+$")


def program_files(home: Path | None = None) -> list[Path]:
    home = home or paths.home()
    return sorted((home / "cardmodel").rglob("*.py")) + [home / "bin" / "cardmodel"]


def publishing_calls(home: Path | None = None) -> list[str]:
    home = home or paths.home()
    return [str(f.relative_to(home)) for f in program_files(home)
            if f.is_file() and PUBLISHING.search(f.read_text(encoding="utf-8"))]


def _test_exists(home: Path, ref: str) -> bool:
    path, _, name = ref.partition("::")
    f = home / path
    return f.is_file() and (not name or re.search(rf"def {re.escape(name)}\(", f.read_text(encoding="utf-8")))


def cli_commands() -> tuple[list[str], str]:
    from .. import cli
    parser = cli.build_parser()
    sub = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    return sorted(sub.choices), cli.__doc__ or ""


def _easier(direction: str, floor, target) -> bool:
    try:
        return target < floor if direction == "higher" else target > floor
    except TypeError:
        return True


def goal_rows(st) -> dict:
    return {g.name: {"metric": g.get("metric"), "direction": g.get("direction"), "target": g.get("target"),
                     "amended": g.get("amended")} for g in st.cards("goal")}


def _amended(g: dict, f: dict) -> bool:
    a = g.get("amended") or {}
    return a.get("from") == f and bool(str(a.get("reason") or "").strip())


def floor_problems(goals: dict, floor: dict | None) -> list[str]:
    """What the floors refuse: a goal easier than its floor, with another metric or direction, or gone, without a
    written reason; a goal with no floor yet (run ``cardmodel docs``)."""
    if floor is None:
        return [f"no goal floors ({FLOORS}): run `cardmodel docs` to record them"]
    floors = floor.get("floors") or {}
    retired = {r.get("goal") for r in floor.get("retired") or [] if str(r.get("reason") or "").strip()}
    out = []
    for name, f in sorted(floors.items()):
        g = goals.get(name)
        if g is None:
            if name not in retired:
                out.append(f"goal {name} was removed: a goal leaves only with a reason ({FLOORS} retired list)")
            continue
        same = (g.get("metric"), g.get("direction")) == (f.get("metric"), f.get("direction"))
        if (same and not _easier(f["direction"], f["target"], g.get("target"))) or _amended(g, f):
            continue
        what = (f"its target moved from {f['target']} to {g.get('target')} ({f['direction']} is better)" if same else
                f"its metric or direction changed ({f.get('metric')}, {f.get('direction')} -> {g.get('metric')}, "
                f"{g.get('direction')})")
        out.append(f"goal {name}: {what} without a reason: give its card \"amended\": {{\"from\": <its floor>, "
                   f"\"reason\": ...}} (docs/INTEGRATION.md, goal floors)")
    for name in sorted(set(goals) - set(floors)):
        out.append(f"goal {name} has no floor yet: run `cardmodel docs`")
    return out


def raised_floors(goals: dict, floor: dict | None, today: str) -> tuple[dict, list[str]]:
    """The floor card ``cardmodel docs`` writes: new goals and harder targets raise their floor, an amended goal
    moves it (the history keeps from, to and the reason), a retired goal leaves it; nothing else lowers a floor."""
    old = dict(floor or {})
    floors = {k: dict(v) for k, v in (old.get("floors") or {}).items()}
    history = list(old.get("history") or [])
    retired = list(old.get("retired") or [])
    gone = {r.get("goal") for r in retired if str(r.get("reason") or "").strip()}
    changes = []
    for name, g in sorted(goals.items()):
        cur = {"metric": g.get("metric"), "direction": g.get("direction"), "target": g.get("target")}
        f = floors.get(name)
        if f is None:
            floors[name] = cur
            changes.append(f"{name}: floor {cur['target']} ({cur['direction']} is better)")
        elif cur != f and _amended(g, f):
            floors[name] = cur
            history.append({"goal": name, "from": f, "to": cur, "reason": str(g["amended"]["reason"]).strip(),
                            "date": today})
            changes.append(f"{name}: moved by its amendment")
        elif cur != f and (cur["metric"], cur["direction"]) == (f["metric"], f["direction"]) and \
                not _easier(f["direction"], f["target"], cur["target"]):
            floors[name] = cur
            changes.append(f"{name}: raised {f['target']} -> {cur['target']}")
    for name in sorted(set(floors) - set(goals)):
        if name in gone:
            del floors[name]
            changes.append(f"{name}: retired")
    card = {"name": "goals", "category": "floor", "tier": 0, "statement": FLOORS_STATEMENT,
            "floors": dict(sorted(floors.items())), "history": history, "retired": retired,
            "provenance": {"origin": "cardmodel docs", "check": "engines/integrity.py floor_problems"}}
    return card, changes


def check(ctx) -> dict:
    home = paths.home()
    st = ctx.store
    problems: list[str] = []

    laws = sorted(st.cards("law"), key=lambda c: c.name)
    seen: dict[str, str] = {}
    for law in laws:
        m = LAW_ID.match(law.name)
        if not m:
            problems.append(f"law {law.name}: the name is not CMnn_words")
            continue
        if m.group(1) in seen:
            problems.append(f"law number {m.group(1)} is used twice: {seen[m.group(1)]} and {law.name}")
        seen[m.group(1)] = law.name
        if not law.get("witness") or not _test_exists(home, law["witness"]):
            problems.append(f"law {law.name}: its witness {law.get('witness')!r} does not exist")
    goals = sorted(st.cards("goal"), key=lambda c: c.name)
    gseen: dict[str, str] = {}
    for g in goals:
        m = GOAL_ID.match(g.name)
        if not m:
            problems.append(f"goal {g.name}: the name is not G_<axis><n>_words")
            continue
        if m.group(1) in gseen:
            problems.append(f"goal id {m.group(1)} is used twice: {gseen[m.group(1)]} and {g.name}")
        gseen[m.group(1)] = g.name

    caps = st.cards("capability")
    carried = {law for c in caps for law in c.get("laws") or []}
    law_names = {f"law/{law.name}" for law in laws}
    for q in sorted(law_names - carried):
        problems.append(f"{q} is carried by no capability card (CM37: a law that nothing runs can be forgotten)")
    for c in caps:
        for q in c.get("laws") or []:
            if q not in law_names:
                problems.append(f"capability/{c.name}: law {q} does not exist")
        for t in c.get("tests") or []:
            if not _test_exists(home, t):
                problems.append(f"capability/{c.name}: test {t} does not exist")
        for d in c.get("docs") or []:
            if not (home / d).is_file():
                problems.append(f"capability/{c.name}: doc {d} does not exist")

    commands, help_text = cli_commands()
    for c in commands:
        if not re.search(rf"(?:cardmodel\s+|\|\s*){re.escape(c)}\b", help_text):
            problems.append(f"command {c!r} is registered but not in the CLI help (cardmodel/cli.py docstring)")
    from . import verify
    vdoc = verify.__doc__ or ""
    for sec in verify.SECTIONS:
        if not re.search(rf"^\s+{re.escape(sec)}\s", vdoc, re.M):
            problems.append(f"verify section {sec!r} is not described in engines/verify.py's docstring")
    readme = (home / "README.md").read_text(encoding="utf-8")
    docs = sorted((home / "docs").glob("*.md"))
    for d in docs:
        if f"(docs/{d.name})" not in readme:
            problems.append(f"docs/{d.name} is not linked from README.md")

    from .docs import laws_md
    if (home / "LAWS.md").read_text(encoding="utf-8") != laws_md(st):
        problems.append("LAWS.md drifted from cards/law (run `cardmodel docs`)")
    goals_md = (home / "GOALS.md").read_text(encoding="utf-8")
    for g in goals:
        if f"`{g.name}`" not in goals_md:
            problems.append(f"GOALS.md has no row for {g.name}")
    floor = st.get(FLOORS)
    problems += floor_problems(goal_rows(st), dict(floor) if floor is not None else None)

    for f in program_files(home):
        if f.suffix == ".py":
            try:
                ast.parse(f.read_text(encoding="utf-8"))
            except SyntaxError as exc:
                problems.append(f"{f.relative_to(home)}:{exc.lineno}: does not parse ({exc.msg})")
    texts = [*home.glob("*.md"), *(home / "docs").glob("*.md"), *(home / "stdlib").glob("*.card"),
             *(home / "examples").rglob("*.card"), *(home / "cards").rglob("*.card")]
    for f in sorted(set(texts)):
        if MARKERS.search(f.read_text(encoding="utf-8", errors="replace")):
            problems.append(f"{f.relative_to(home)}: merge conflict markers")
    for hit in publishing_calls(home):
        problems.append(f"{hit}: a publishing call (CM19)")
    from .pipeline import purity_problems
    problems += purity_problems(ctx, str(home))

    return {"status": "fail" if problems else "pass", "problems": problems, "laws": len(laws), "goals": len(goals),
            "capabilities": len(caps), "commands": len(commands), "sections": len(verify.SECTIONS),
            "docs": len(docs)}


__all__ = ["FLOORS", "check", "cli_commands", "floor_problems", "goal_rows", "program_files", "publishing_calls",
           "raised_floors"]
