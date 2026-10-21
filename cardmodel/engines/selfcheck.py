"""selfcheck — prove the program needs no folder outside its own tree (CM13).

Two checks:
  static   the runtime package and the CLI shim contain no reference to the
           original card-model folders and no user-specific paths, and
           nothing in ``cardmodel/`` imports the build-time ``tools/``;
  sandbox  on macOS, ``sandbox-exec`` runs the CLI with read access to the
           source folders denied (a probe read inside the sandbox must fail,
           so a broken sandbox cannot produce a vacuous pass).

The source folders are passed in by the caller (the test computes them from
the user's home directory at run time); the program itself never names them.

Honest limits (L1): the sandbox check needs macOS ``sandbox-exec``; elsewhere
only the static check runs and the result says so.
"""
from __future__ import annotations

import ast
import os
import shutil
import subprocess
import sys
from pathlib import Path

from ..kernel import paths

# path fragments, not names: docstrings may credit where an idea came from, code may not point there
FORBIDDEN = ("Claude_Hub/", "Pheros_Studio/", "rea-main/", "Programmering/", "~/Documents", "/Users/", "/home/")


def static_check(home: Path | None = None) -> list[str]:
    home = home or paths.home()
    problems = []
    files = sorted((home / "cardmodel").rglob("*.py")) + [home / "bin" / "cardmodel"]
    for f in files:
        text = f.read_text(encoding="utf-8")
        for bad in FORBIDDEN:
            if bad in text and f.name != "selfcheck.py":
                problems.append(f"{f.relative_to(home)} mentions {bad!r}")
        if f.suffix == ".py":
            for node in ast.walk(ast.parse(text)):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    mod = node.module if isinstance(node, ast.ImportFrom) else node.names[0].name
                    if mod and (mod == "tools" or mod.startswith("tools.") or mod in ("vendor_import", "bootstrap")):
                        problems.append(f"{f.relative_to(home)} imports build-time module {mod}")
    return problems


def sandbox_profile(deny: list[Path]) -> str:
    rules = "\n".join(f'(deny file-read* (subpath "{p}"))' for p in deny)
    return f"(version 1)\n(allow default)\n{rules}\n"


def run_sandboxed(cmd: list[str], deny: list[Path], cwd: Path, timeout: int = 900, env: dict | None = None):
    exe = shutil.which("sandbox-exec")
    if exe is None:
        return None
    prof = Path(cwd) / ".cm_sandbox.sb"
    prof.write_text(sandbox_profile(deny), encoding="utf-8")
    try:
        return subprocess.run([exe, "-f", str(prof), *cmd], cwd=cwd, capture_output=True, text=True, timeout=timeout,
                              env=env or os.environ.copy(), stdin=subprocess.DEVNULL)
    finally:
        prof.unlink(missing_ok=True)


def sandbox_check(deny: list[Path], workdir: Path, commands: list[list[str]]) -> dict:
    """Run each command with ``deny`` unreadable. Returns {"ok", "effective", "runs": [...]}."""
    deny = [p for p in deny if p.exists()]
    probe = run_sandboxed([sys.executable, "-c", "import sys, os; sys.exit(0 if all(not os.access(p, os.R_OK) or "
                           "not os.path.exists(p) for p in sys.argv[1:]) else 3)", *map(str, deny)], deny, workdir)
    if probe is None:
        return {"ok": None, "reason": "sandbox-exec not available on this platform", "runs": []}
    effective = probe.returncode == 0
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=str(paths.home()))
    runs = []
    for cmd in commands:
        r = run_sandboxed(cmd, deny, workdir, env=env)
        runs.append({"cmd": cmd[-4:], "code": r.returncode, "stderr": r.stderr[-600:]})
    return {"ok": effective and all(r["code"] == 0 for r in runs), "effective": effective,
            "denied": [str(p) for p in deny], "runs": runs}


def source_folders(store) -> list[Path]:
    """The folders this model was consolidated from, read from the vendored registries' provenance
    (``provenance.path``), so the deny list is data, not code."""
    out = []
    for view in store.views.values():
        for r in view.regs:
            prov = r.meta.get("provenance") or {}
            p = prov.get("path") if isinstance(prov, dict) else None
            if isinstance(p, str) and p.startswith("~/"):
                parts = Path(p[2:]).parts
                root = Path.home().joinpath(*parts[:2]) if len(parts) >= 2 else Path.home().joinpath(*parts)
                if root not in out:
                    out.append(root)
    return out


def run(ctx, seed: int) -> dict:
    """verify section: static scan + (macOS) a sandboxed `cardmodel verify --only kernel,rules`."""
    import tempfile
    static = static_check()
    deny = source_folders(ctx.store)
    res: dict = {"static_problems": static, "denied": [str(p) for p in deny]}
    with tempfile.TemporaryDirectory(prefix="cardmodel_selfcheck_") as d:
        cmd = [sys.executable, "-B", "-m", "cardmodel", "--no-project", "verify", "--only", "kernel,rules",
               "--seed", str(seed)]
        sb = sandbox_check(deny, Path(d), [cmd])
    res["sandbox"] = sb
    ok = not static and (sb["ok"] is not False)
    res["status"] = "pass" if ok and sb["ok"] else ("fail" if not ok else "partial")
    ctx.save_state("self_contained_check", {"ok": ok and bool(sb["ok"]), "denied": res["denied"],
                                            "sandbox": sb.get("ok"), "static_problems": static})
    return res
