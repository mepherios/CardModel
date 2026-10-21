"""lean — Lean 4 emission and checking (hub lean_emitter, now with a real toolchain when one is present).

* Functions: function cards are emitted through the ``lean`` language card
  (codegen: ``partial def`` in ``Id.run do``), and run by the conformance /
  translation witnesses like any other language.
* Rules: every rewrite rule card becomes ``theorem <name> (vars : Int) :
  lhs = rhs := by <tactic>``. Tactics tried in order: ``grind`` (core Lean's
  commutative-ring solver), ``omega`` (linear integer arithmetic). Checked
  by the local ``lean`` binary; status per rule: proved | unproved |
  not_expressible (an operator without a Lean form) | no_toolchain.
* ``lint`` is the hub's pure-Python syntax check, kept as the fallback when
  no toolchain is installed (balanced brackets, no stray ``sorry``).

Honest limits (L1): without Mathlib, nonlinear facts beyond ``grind``'s ring
normaliser stay unproved; a statement is emitted for every rule regardless.
"""
from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path

from ..engines import probes
from ..engines.exprs import parse

LEAN_INFIX = {"ADD": "+", "SUB": "-", "MUL": "*", "POW": "^", "FLOORDIV": "/", "MOD": "%"}
TACTICS = ("grind", "omega")
TIMEOUT_S = 120


class NotExpressible(ValueError):
    pass


def to_lean(tree) -> str:
    if isinstance(tree, list):
        head = tree[0]
        if head == "var":
            return tree[1]
        if head == "int":
            return f"({tree[1]} : Int)" if tree[1] < 0 else str(tree[1])
        if head == "NEG":
            return f"(-{to_lean(tree[1])})"
        if head == "POW":
            if tree[2][0] != "int" or tree[2][1] < 0:
                raise NotExpressible("Lean Int ^ needs a natural-number literal exponent")
            return f"({to_lean(tree[1])} ^ {tree[2][1]})"
        if head in ("FLOORDIV", "MOD"):
            fn = "Int.fdiv" if head == "FLOORDIV" else "Int.fmod"
            return f"({fn} {to_lean(tree[1])} {to_lean(tree[2])})"
        if head in ("MIN", "MAX"):
            return f"({head.lower()} {to_lean(tree[1])} {to_lean(tree[2])})"
        if head == "ABS":
            return f"(((Int.natAbs {to_lean(tree[1])}) : Nat) : Int)"
        if head in LEAN_INFIX:
            return f"({to_lean(tree[1])} {LEAN_INFIX[head]} {to_lean(tree[2])})"
    raise NotExpressible(f"no Lean form for {tree[0] if isinstance(tree, list) else tree}")


def rule_theorem(card, tactic: str) -> str:
    vars_ = card.get("vars") or []
    lhs, rhs = to_lean(parse(card["lhs"])), to_lean(parse(card["rhs"]))
    binders = f" ({' '.join(vars_)} : Int)" if vars_ else ""
    return f"theorem cm_{card['name']}{binders} : {lhs} = {rhs} := by {tactic}"


def lean_exe() -> str | None:
    ok, exe = probes.probe({"kind": "executable", "name": "lean", "glob": ["~/.elan/toolchains/*/bin/lean"],
                            "glob_only": True, "env_override": "CARDMODEL_LEAN", "version_args": ["--version"]})
    return exe if ok else None


def check_source(source: str, exe: str) -> tuple[bool, str]:
    with tempfile.TemporaryDirectory(prefix="cardmodel_lean_") as d:
        f = Path(d) / "Check.lean"
        f.write_text(source, encoding="utf-8")
        try:
            p = subprocess.run([exe, str(f)], capture_output=True, text=True, timeout=TIMEOUT_S,
                               stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            return False, "timeout"
    return p.returncode == 0 and "error" not in p.stdout, (p.stdout + p.stderr)[-800:]


def check_batch(exe: str, items: list[tuple[str, str]], header: list[str] | None = None,
                timeout_s: int = 900, rounds: int = 4) -> dict[str, str]:
    """Check many independent declarations in one Lean file per round; fail closed.

    Returns {key: "ok" | "error: <message>" | "unchecked: <why>"}. A declaration counts as ok only when
    Lean processed it without an error: errors are attributed by line range; if Lean stops early
    (maxErrors, a crash, a timeout) every declaration it may not have reached is re-checked in a new
    round, and anything still unreached is "unchecked", never "ok"."""
    result: dict[str, str] = {}
    pending = list(items)
    for _ in range(rounds):
        if not pending:
            break
        head = list(header or [])
        imports = [h for h in head if h.startswith("import ")]          # Lean wants imports first
        lines = [*imports, "set_option maxErrors 1000000", *[h for h in head if not h.startswith("import ")]]
        spans = []
        for key, text in pending:
            start = len(lines) + 1
            lines.extend(text.split("\n"))
            spans.append((start, len(lines), key))
        with tempfile.TemporaryDirectory(prefix="cardmodel_lean_") as d:
            f = Path(d) / "Batch.lean"
            f.write_text("\n".join(lines) + "\n", encoding="utf-8")
            try:
                p = subprocess.run([exe, str(f)], capture_output=True, text=True, timeout=timeout_s,
                                   stdin=subprocess.DEVNULL)
                log, code = p.stdout + p.stderr, p.returncode
            except subprocess.TimeoutExpired:
                log, code = "timeout", -1
        errors: dict[str, str] = {}
        last_line = 0
        for m in re.finditer(r":(\d+):\d+: error[^:]*: ?(.*)", log):
            ln = int(m.group(1))
            last_line = max(last_line, ln)
            for start, end, key in spans:
                if start <= ln <= end:
                    errors.setdefault(key, m.group(2)[:300])
                    break
        stopped = code == -1 or "maximum number of errors" in log or (code != 0 and not errors)
        retry = []
        for start, end, key in spans:
            if key in errors:
                result[key] = "error: " + errors[key]
            elif stopped and start > last_line:
                retry.append((key, dict(pending)[key]))
            elif stopped and code == -1:
                retry.append((key, dict(pending)[key]))
            else:
                result[key] = "ok"
        if retry and len(retry) == len(pending) and not errors:
            for key, _ in retry:
                result[key] = "unchecked: " + ("timeout" if code == -1 else "Lean stopped before reaching it")
            return result
        pending = retry
    for key, _ in pending:
        result[key] = "unchecked: Lean stopped before reaching it"
    return result


def check_rules(ctx) -> dict:
    """Emit every rule as a theorem and let Lean check it (all tactics, one file per tactic round)."""
    exe = lean_exe()
    rules = list(ctx.store.cards("rewrite_rule"))
    out: dict[str, dict] = {}
    pending = []
    for card in rules:
        try:
            rule_theorem(card, "grind")
            pending.append(card)
        except NotExpressible as exc:
            out[card.qualified] = {"status": "not_expressible", "detail": str(exc)}
    if exe is None:
        for card in pending:
            out[card.qualified] = {"status": "no_toolchain", "statement": rule_theorem(card, "sorry")}
        return {"status": "skipped", "reason": "no Lean toolchain found", "rules": out}
    for tactic in TACTICS:
        if not pending:
            break
        verdict = check_batch(exe, [(c.qualified, rule_theorem(c, tactic)) for c in pending])
        still = []
        for card in pending:
            v = verdict.get(card.qualified, "unchecked")
            if v == "ok":
                out[card.qualified] = {"status": "proved", "tactic": tactic, "statement": rule_theorem(card, tactic)}
            elif v.startswith("unchecked"):
                out[card.qualified] = {"status": "unchecked", "detail": v}
            else:
                still.append(card)
        pending = still
    for card in pending:
        out[card.qualified] = {"status": "unproved", "tried": list(TACTICS), "statement": rule_theorem(card, "sorry")}
    proved = sum(1 for r in out.values() if r["status"] == "proved")
    return {"status": "pass" if proved else "vacuous", "proved": proved, "total": len(rules), "toolchain": exe,
            "rules": out}


def emit_rules(ctx, tactic: str = "grind") -> str:
    lines = ["-- generated by cardmodel emit --lang lean --rules (core Lean 4, no Mathlib)", ""]
    for card in ctx.store.cards("rewrite_rule"):
        try:
            lines.append(rule_theorem(card, tactic))
        except NotExpressible as exc:
            lines.append(f"-- {card['name']}: not expressible ({exc})")
    return "\n".join(lines) + "\n"


def lint(source: str) -> tuple[bool, list[str]]:
    """Hub lean_emitter.lint_lean: balanced (), [], {} outside comments/strings; no stray sorry."""
    problems = []
    depth = {"(": 0, "[": 0, "{": 0}
    pairs = {")": "(", "]": "[", "}": "{"}
    text = re.sub(r"/-.*?-/", " ", source, flags=re.S)
    text = re.sub(r"--[^\n]*", " ", text)
    text = re.sub(r'"(?:\\.|[^"\\])*"', '""', text)
    for ch in text:
        if ch in depth:
            depth[ch] += 1
        elif ch in pairs:
            depth[pairs[ch]] -= 1
    for k, v in depth.items():
        if v:
            problems.append(f"unbalanced {k}: {v:+d}")
    for m in re.finditer(r"\bsorry\b", text):
        line = text[text.rfind("\n", 0, m.start()) + 1: text.find("\n", m.start())]
        if "by" not in line and ":=" not in line:
            problems.append(f"stray sorry at {m.start()}")
    return not problems, problems
