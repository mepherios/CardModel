"""integrity — the program is one piece (law CM39): what parallel work must not break when it merges.

Checks, each cheap and read-only:
  identifiers   law numbers (CMnn) and goal ids (G_Xn) are unique; a law's number is its identity
  floors        no goal's target is easier than its recorded floor (cards/goal_floor, the hardest target accepted)
                unless the goal card carries an amendment {from, to, reason}; tools/goal_floors.py records the
                floors, raising each when its target got stricter and never lowering one by itself
  carried       every law is carried by a capability card, and every capability's laws, tests and docs exist
  documented    every command the CLI registers is in its help, every verify section is in verify's docstring,
                every docs/*.md file is linked from README.md
  generated     LAWS.md is what the law cards generate; GOALS.md has a row for every goal card
  source        every module of the program parses (no leftover merge markers in code, docs or card sources)
  boundaries    no publishing calls (pushes to a remote, package or gist uploads) anywhere in the program (CM19)

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
GOAL_ID = re.compile(r"^(G_[A-Z]+\d+)_[a-z0-9_]+$")


def easier(target, floor: dict, direction) -> bool:
    """Whether ``target`` asks less than the floor: a lower bar for a 'higher' goal, a higher one for 'lower', any
    change for 'equal', or a changed direction."""
    if direction != floor.get("direction"):
        return True
    f = floor.get("target")
    if not isinstance(target, (int, float)) or not isinstance(f, (int, float)):
        return target != f
    return target < f if direction == "higher" else target > f if direction == "lower" else target != f


def floor_problems(goals, store) -> list[str]:
    """A goal made easier than its floor, without an amendment saying from what, to what and why."""
    floors = ((store.get("goal_floor/floors") or {}).get("floors")) or {}
    out = []
    for g in goals:
        f = floors.get(g.name)
        if not f or not easier(g.get("target"), f, g.get("direction")):
            continue
        am = g.get("amendment") or {}
        if am.get("from") == f.get("target") and am.get("to") == g.get("target") and am.get("reason"):
            continue
        out.append(f"goal {g.name}: target {g.get('target')} ({g.get('direction')}) is easier than its floor "
                   f"{f.get('target')} ({f.get('direction')}); lowering a goal needs an amendment "
                   f"{{from, to, reason}} on its card")
    return out


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
    problems += floor_problems(goals, st)

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

    return {"status": "fail" if problems else "pass", "problems": problems, "laws": len(laws), "goals": len(goals),
            "capabilities": len(caps), "commands": len(commands), "sections": len(verify.SECTIONS),
            "docs": len(docs)}


__all__ = ["check", "cli_commands", "program_files", "publishing_calls"]
