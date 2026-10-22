"""formal — the Gödel model's formal core in Lean (formal/GodelCore; the research handover's agenda R1).

  library    formal/GodelCore: content vectors, the divisibility lattice (T1), carry-over maps and gcd (T2), the
             append-only ledger and its inclusions (T3), merging versus relating generators (T4), transport of
             upward- and downward-closed properties (T5), rewrite invariants of balanced rules (T6). Plain Lean 4
             with the installed toolchain and no Mathlib.
  cards      one ``formal_theorem`` card per handover theorem, naming the Lean theorems that prove it.
  check      builds the library with lake, rejects any ``sorry``, ``admit`` or ``axiom`` in its sources, and asks
             Lean (``#print axioms``) that every theorem a card names exists and rests only on Lean's standard
             axioms (propext, Classical.choice, Quot.sound). Truth is fixed by Lean's kernel, outside the model.

Honest limits (L1): the theorems are about the model's mathematics (vectors over a basis, lists as ledgers, binary
terms), not about the Python that implements it; their link to the code is the cards and the tests. Mathlib's
Finsupp version the handover names needs Mathlib, which is not installed; T7 (each finite-witness theorem) and T8
(Parikh) are not formalized yet.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from ..kernel import paths, resources

REGISTRY = "formal_theorem"
STANDARD_AXIOMS = {"propext", "Classical.choice", "Quot.sound"}
_FORBIDDEN = re.compile(r"\b(sorry|admit)\b|^\s*axiom\s", re.M)


def root() -> Path:
    return paths.home() / "formal"


def toolchain(where: Path | None = None) -> Path | None:
    """The bin folder of the toolchain formal/lean-toolchain names, when it is installed."""
    f = (where or root()) / "lean-toolchain"
    if not f.is_file():
        return None
    name = f.read_text(encoding="utf-8").strip().replace("/", "--").replace(":", "---")
    b = Path(os.path.expanduser("~/.elan/toolchains")) / name / "bin"
    return b if (b / "lake").is_file() and (b / "lean").is_file() else None


def strip_comments(src: str) -> str:
    """Lean source without its comments (nested block comments included), for the scan."""
    out, i, depth = [], 0, 0
    while i < len(src):
        if src.startswith("/-", i):
            depth, i = depth + 1, i + 2
        elif depth and src.startswith("-/", i):
            depth, i = depth - 1, i + 2
        elif not depth and src.startswith("--", i):
            j = src.find("\n", i)
            i = len(src) if j < 0 else j
        else:
            if not depth:
                out.append(src[i])
            i += 1
    return "".join(out)


def scan(where: Path | None = None) -> list[str]:
    """Every sorry, admit or axiom declaration in the library's sources."""
    out = []
    for f in sorted((where or root()).rglob("*.lean")):
        if ".lake" in f.parts:
            continue
        for m in _FORBIDDEN.finditer(strip_comments(f.read_text(encoding="utf-8"))):
            out.append(f"{f.relative_to(where or root())}: {m.group(0).strip()}")
    return out


def build(where: Path | None = None, timeout: float = 900) -> tuple[bool, str]:
    where = where or root()
    tc = toolchain(where)
    if tc is None:
        return False, "no Lean toolchain for formal/lean-toolchain"
    env = {**os.environ, "PATH": f"{tc}:{os.environ.get('PATH', '')}"}
    try:
        p = resources.run([str(tc / "lake"), "build"], cwd=where, timeout=timeout, stdin=subprocess.DEVNULL, env=env)
    except subprocess.TimeoutExpired:
        return False, f"lake build ran past {timeout:.0f} s"
    text = (p.stdout or "") + (p.stderr or "")
    errors = [ln for ln in text.splitlines() if "error:" in ln]
    return p.returncode == 0 and not errors, "\n".join(errors[-12:]) or text[-1500:]


def axioms(names: list[str], where: Path | None = None, timeout: float = 300) -> dict[str, list[str] | None]:
    """{Lean name: the axioms it rests on, or None when Lean does not know it}."""
    where = where or root()
    tc = toolchain(where)
    if tc is None or not names:
        return {n: None for n in names}
    probe = paths.home() / "state" / "formal" / "axioms.lean"
    probe.parent.mkdir(parents=True, exist_ok=True)
    probe.write_text("import GodelCore\n" + "".join(f"#print axioms {n}\n" for n in names), encoding="utf-8")
    env = {**os.environ, "LEAN_PATH": str(where / ".lake" / "build" / "lib" / "lean")}
    try:
        p = resources.run([str(tc / "lean"), str(probe)], cwd=where, timeout=timeout, stdin=subprocess.DEVNULL,
                          env=env)
    except subprocess.TimeoutExpired:
        return {n: None for n in names}
    text = (p.stdout or "") + (p.stderr or "")
    out: dict[str, list[str] | None] = {n: None for n in names}
    for m in re.finditer(r"'([\w.]+)' depends on axioms: \[([^\]]*)\]", text):
        out[m.group(1)] = [a.strip() for a in m.group(2).split(",") if a.strip()]
    for m in re.finditer(r"'([\w.]+)' does not depend on any axioms", text):
        out[m.group(1)] = []
    return out


def check(ctx) -> dict:
    """Build the core, scan it, and check every formal_theorem card against Lean."""
    cards = ctx.store.cards(REGISTRY)
    if not root().is_dir():
        return {"status": "skipped", "reason": "no formal/ folder"}
    if toolchain() is None:
        return {"status": "skipped", "reason": "no Lean toolchain for formal/lean-toolchain"}
    problems = [f"{x} (the formal core admits nothing)" for x in scan()]
    ok, log = build()
    if not ok:
        return {"status": "fail", "problems": problems + [f"lake build failed: {log}"], "theorems": len(cards)}
    names = sorted({n for c in cards for n in c.get("lean") or []})
    ax = axioms(names)
    proved = 0
    rows = {}
    for c in cards:
        bad = []
        for n in c.get("lean") or []:
            a = ax.get(n)
            if a is None:
                bad.append(f"{n} is not a theorem Lean knows")
            elif set(a) - STANDARD_AXIOMS:
                bad.append(f"{n} rests on {sorted(set(a) - STANDARD_AXIOMS)}")
        if not c.get("lean"):
            bad.append("names no Lean theorem")
        rows[c.qualified] = {"lean": c.get("lean"), "problems": bad}
        problems += [f"{c.qualified}: {b}" for b in bad]
        proved += not bad
    return {"status": "fail" if problems else ("pass" if cards else "vacuous"), "problems": problems,
            "theorems": len(cards), "proved": proved, "lean_names": len(names), "cards": rows,
            "toolchain": toolchain().parent.name}


__all__ = ["REGISTRY", "STANDARD_AXIOMS", "axioms", "build", "check", "root", "scan", "strip_comments", "toolchain"]
