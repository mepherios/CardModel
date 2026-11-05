"""compiler_goals — the general compiler's goals, computed (docs/GENERAL_COMPILER.md §6).

* ``core_forms_in_ir`` (G_C6): how many ``core_form`` cards the IR has, each checked against the IR's own tables
  (ir.TYPES, ir.LEAVES, ir.SPECIAL, ir.STATEMENTS, the op cards, importable modules); a construct counts only
  when everything it requires is there.
* ``stdlib_lift_closed_rate`` (G_C7): the share of the Python standard library's functions (tests, idlelib and
  site-packages excluded) that lift with no gap (engines/sweep.py), kept in state under a key of the stdlib's
  path and Python version and the lifting code's bytes, so it is measured again only when either changes.
* ``doors_witnessed`` (G_C8): instruction sets (``isa/*``; later LLVM IR, CPython bytecode) whose every card
  agrees with its bench in the latest verify's machine section.
"""
from __future__ import annotations

import hashlib
import importlib.util
import sys
import sysconfig
from pathlib import Path

from .context import Ctx

STDLIB_EXCLUDE = ["*test*", "idlelib/*", "site-packages/*"]
_LIFT_CODE = ("frontend_python.py", "lift_project.py", "sweep.py", "ir.py", "opaque.py")


def core_form_status(ctx: Ctx) -> dict[str, list[str]]:
    """Each core_form card -> what it requires that the IR lacks (empty: the IR has the construct)."""
    from . import ir
    have = {"types": set(ir.TYPES), "leaves": set(ir.LEAVES), "special": set(ir.SPECIAL),
            "statements": set(ir.STATEMENTS), "ops": set(ctx.ops)}
    out = {}
    for c in sorted(ctx.store.cards("core_form"), key=lambda c: c.get("order", 0)):
        missing = []
        for kind, names in (c.get("requires") or {}).items():
            for n in names:
                if kind == "modules":
                    if importlib.util.find_spec(n) is None:
                        missing.append(f"module {n}")
                elif n not in have.get(kind, set()):
                    missing.append(f"{kind[:-1] if kind.endswith('s') else kind} {n}")
        out[c.name] = missing
    return out


def core_forms_in_ir(ctx: Ctx) -> int | None:
    st = core_form_status(ctx)
    return sum(1 for m in st.values() if not m) if st else None


def _stdlib_key(stdlib: Path) -> str:
    h = hashlib.sha256(f"{stdlib}\0{sys.version}".encode())
    here = Path(__file__).parent
    for f in _LIFT_CODE:
        h.update((here / f).read_bytes())
    return h.hexdigest()[:20]


def stdlib_lift(ctx: Ctx, measure: bool = True) -> dict | None:
    """The stdlib sweep's totals, from state when its key still holds; measured (about 10 s) when ``measure``."""
    stdlib = Path(sysconfig.get_paths()["stdlib"])
    if not stdlib.is_dir():
        return None
    key = _stdlib_key(stdlib)
    kept = ctx.load_state("stdlib_lift") or {}
    if kept.get("key") == key:
        return kept
    if not measure:
        return None
    from . import sweep
    rep = sweep.sweep(ctx, stdlib, exclude=STDLIB_EXCLUDE, top=10)
    rec = {"key": key, "root": str(stdlib), "python": sys.version.split()[0], "functions": rep["functions"],
           "lifted": rep["lifted"], "closed": rep["closed"], "rate": rep["rate"], "closed_rate": rep["closed_rate"],
           "reasons": rep["reasons"]}
    ctx.save_state("stdlib_lift", rec)
    return rec


def stdlib_lift_closed_rate(ctx: Ctx) -> float | None:
    r = stdlib_lift(ctx)
    return r["closed_rate"] if r else None


def doors_witnessed(secs: dict) -> int | None:
    m = secs.get("machine")
    if not m or "isas" not in m:
        return None
    return sum(1 for r in m["isas"].values() if r.get("cards") and r.get("passed") == r.get("cards"))
