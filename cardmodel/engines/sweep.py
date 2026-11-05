"""sweep — how much of a source tree lifts into the card IR, and why the rest does not (ROADMAP B6).

``cardmodel lift-sweep PATH`` lifts every file of every readable language under PATH (a project lift: calls
between files and modules resolve, engines/lift_project.py) and prints the lift rate, the rate per language, and a
histogram of the first reason each function failed, with the reasons normalised (names, numbers and line numbers
become placeholders) so they group. The self-run can track the rate as a goal.

A function lifts when its own body does (SCALING.md §3.3: partial, not poisoned); it is *closed* when everything it
calls lifted too, so it runs and translates alone. A function that does not lift is a boundary card; the call edges
it leaves as gaps in its callers are counted by the boundary's cause.

Honest limits (L1): a function counts once, by its first reason; methods count as functions; a file that does not
parse counts as one failure of the file, not of its functions.
"""
from __future__ import annotations

import re
import time
from collections import Counter
from fnmatch import fnmatch
from pathlib import Path

from .context import Ctx

SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", "build", "dist", "target", ".cardmodel",
             "site-packages"}


def normalise(reason: str) -> str:
    """'line 12: name 'x' is not a parameter' -> "name '_' is not a parameter" (groups the histogram)."""
    r = re.sub(r"^line \d+: ", "", reason)
    r = re.sub(r"'[^']*'", "'_'", r)
    r = re.sub(r"\"[^\"]*\"", "'_'", r)
    r = re.sub(r"`[^`]*`", "`_`", r)
    r = re.sub(r"\b\d+\b", "N", r)
    r = re.sub(r"uses (\w+)\.\w+", r"uses \1._", r)
    r = re.sub(r"calls .* which did not lift", "calls a function that did not lift", r)
    return r[:120]


def files_under(root: Path, exts: dict[str, str], exclude: list[str]) -> list[tuple[Path, str]]:
    out = []
    paths = [root] if root.is_file() else sorted(root.rglob("*"))
    for p in paths:
        if not p.is_file() or any(part in SKIP_DIRS for part in p.parts):
            continue
        rel = str(p.relative_to(root)) if root.is_dir() else p.name
        if any(fnmatch(rel, pat) or fnmatch(p.name, pat) for pat in exclude):
            continue
        lang = exts.get(p.suffix)
        if lang:
            out.append((p, lang))
    return out


def sweep(ctx: Ctx, root: str | Path, exclude: list[str] | None = None, langs: list[str] | None = None,
          methods: bool = True, project: bool = True, top: int = 25) -> dict:
    from . import frontends, lift_project
    root = Path(root)
    exts = {}
    for lang in frontends.frontend_languages(ctx.store):
        if langs and lang not in langs:
            continue
        for e in ctx.store.get(f"language/{lang}").get("extensions") or []:
            exts.setdefault(e, lang)
    files = files_under(root, exts, exclude or [])
    t0 = time.perf_counter()
    res = lift_project.lift_files(ctx, files, methods=methods, cross=project,
                                  root=root.resolve() if root.is_dir() else root.resolve().parent)
    seconds = time.perf_counter() - t0
    from .frontend_python import lift_status
    reasons: Counter = Counter()
    blockers: Counter = Counter()
    per_lang: dict[str, list[int]] = {}
    total = lifted = closed = 0
    kinds = Counter()
    for lf in res.functions.values():
        lang = lf.lang
        c = per_lang.setdefault(lang, [0, 0, 0])
        c[0] += 1
        total += 1
        kinds["method" if getattr(lf, "method", False) else "function"] += 1
        status = lift_status(lf)
        if status != "boundary":
            c[1] += 1
            lifted += 1
        if status == "closed":
            c[2] += 1
            closed += 1
        if status == "boundary":
            reasons[normalise(lf.reasons[0] if lf.reasons else "unknown")] += 1
        for g in lf.gaps:
            if g["kind"] == "boundary":
                blockers[normalise(g["cause"])] += 1
    bounds = res.boundaries()
    return {
        "root": str(root), "files": len(files), "unparsed_files": res.unparsed, "functions": total,
        "lifted": lifted, "rate": round(lifted / total, 4) if total else 0.0,
        "closed": closed, "closed_rate": round(closed / total, 4) if total else 0.0, "partial": lifted - closed,
        "boundaries": len(bounds), "typed_boundaries": sum(1 for b in bounds.values() if b["signature"]),
        "gap_edges": sum(b["gap_edges"] for b in bounds.values()), "kinds": dict(kinds),
        "cross_module_calls": res.cross_calls, "seconds": round(seconds, 2),
        "languages": {k: {"functions": v[0], "lifted": v[1], "closed": v[2],
                          "rate": round(v[1] / v[0], 4) if v[0] else 0.0} for k, v in sorted(per_lang.items())},
        "reasons": reasons.most_common(top),
        "gap_causes": blockers.most_common(top),
    }


def report_text(rep: dict) -> str:
    lines = [f"{rep['root']}: {rep['lifted']} of {rep['functions']} functions lift ({100 * rep['rate']:.2f} %), "
             f"{rep['closed']} closed ({100 * rep['closed_rate']:.2f} %) and {rep['partial']} with gaps · "
             f"{rep['boundaries']} boundary cards ({rep['typed_boundaries']} typed) leave {rep['gap_edges']} call "
             f"edges as gaps · {rep['files']} files ({len(rep['unparsed_files'])} unparsed) · {rep['kinds']} · "
             f"{rep['cross_module_calls']} calls across files · {rep['seconds']} s"]
    for lang, r in rep["languages"].items():
        lines.append(f"  {lang:<12} {r['lifted']:>7} / {r['functions']:<7} {100 * r['rate']:6.2f} %"
                     f"   closed {r['closed']}")
    lines.append("why a function is a boundary (its own first reason):")
    for reason, n in rep["reasons"]:
        lines.append(f"  {n:>7}  {reason}")
    if rep["gap_causes"]:
        lines.append("gap edges, by the boundary's cause:")
        for reason, n in rep["gap_causes"]:
            lines.append(f"  {n:>7}  {reason}")
    return "\n".join(lines)
