"""codefacts — a Python code base as logic facts, so rules can reason about it (stdlib/program.card).

Facts per top-level function F (qualified ``module.name``): function(F), in_module(F, M), calls(F, G)
(G qualified when it is defined in the scanned tree, else ``ext:<dotted name>``), effect(F, KIND) for direct
effects (io, net, time, random, process, global, mutation, raise), pure_core(F) when the IR frontend lifts it
(the optimizer's pure core), shell(F) otherwise, and loc(F, N) (source lines).

Honest limits (L1): syntactic: calls through variables, decorators and dynamic dispatch are not resolved;
effects are recognised by name (open/print/socket/requests/time/random/os/subprocess, global statements,
attribute and subscript assignment); classes contribute their methods as ``Class.method``.
"""
from __future__ import annotations

import ast
from pathlib import Path

from . import logic as L
from .frontend_python import lift_source

EFFECT_CALLS = {
    "print": "io", "open": "io", "input": "io", "write": "io", "read": "io",
    "socket": "net", "requests": "net", "urllib": "net", "http": "net", "urlopen": "net", "connect": "net",
    "send": "net", "recv": "net", "sendall": "net",
    "time": "time", "sleep": "time", "datetime": "time", "perf_counter": "time",
    "random": "random", "randint": "random", "choice": "random", "shuffle": "random", "uniform": "random",
    "os": "process", "subprocess": "process", "sys": "process", "exit": "process",
}


def _dotted(n) -> str | None:
    if isinstance(n, ast.Name):
        return n.id
    if isinstance(n, ast.Attribute):
        base = _dotted(n.value)
        return f"{base}.{n.attr}" if base else n.attr
    return None


def facts_for(root: str | Path) -> L.Program:
    root = Path(root)
    files = [root] if root.is_file() else sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)
    prog = L.Program(name="code")
    defs: dict[str, str] = {}                      # bare name -> qualified (first definition wins)
    parsed = []
    for f in files:
        try:
            tree = ast.parse(f.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        mod = f.stem if root.is_file() else ".".join(f.relative_to(root).with_suffix("").parts)
        funcs = []
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                funcs.append((f"{mod}.{node.name}", node))
            elif isinstance(node, ast.ClassDef):
                for sub in node.body:
                    if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        funcs.append((f"{mod}.{node.name}.{sub.name}", sub))
        for q, node in funcs:
            defs.setdefault(q.rsplit(".", 1)[1], q)
        parsed.append((f, mod, tree, funcs))
    for f, mod, tree, funcs in parsed:
        src = f.read_text(encoding="utf-8")
        try:
            lifted = {lf.name: lf.ok for lf in lift_source(src, {} if False else _ops())}
        except SyntaxError:
            lifted = {}
        for q, node in funcs:
            name = q.rsplit(".", 1)[1]
            prog.add_fact("function", [q])
            prog.add_fact("in_module", [q, mod])
            prog.add_fact("loc", [q, (node.end_lineno or node.lineno) - node.lineno + 1])
            if lifted.get(name) and q.count(".") == mod.count(".") + 1:
                prog.add_fact("pure_core", [q])
            else:
                prog.add_fact("shell", [q])
            seen_calls, seen_effects = set(), set()
            for n in ast.walk(node):
                if isinstance(n, ast.Call):
                    d = _dotted(n.func)
                    if not d:
                        continue
                    head, last = d.split(".")[0], d.split(".")[-1]
                    target = defs.get(last) if (d == last or head in ("self", "cls")) else None
                    callee = target or f"ext:{d}"
                    if callee not in seen_calls:
                        seen_calls.add(callee)
                        prog.add_fact("calls", [q, callee])
                    kind = EFFECT_CALLS.get(head) or (EFFECT_CALLS.get(last) if target is None else None)
                    if kind and kind not in seen_effects:
                        seen_effects.add(kind)
                        prog.add_fact("effect", [q, kind])
                elif isinstance(n, (ast.Global, ast.Nonlocal)) and "global" not in seen_effects:
                    seen_effects.add("global")
                    prog.add_fact("effect", [q, "global"])
                elif isinstance(n, (ast.Assign, ast.AugAssign)):
                    targets = n.targets if isinstance(n, ast.Assign) else [n.target]
                    if any(isinstance(t, (ast.Attribute, ast.Subscript)) for t in targets) and "mutation" not in seen_effects:
                        seen_effects.add("mutation")
                        prog.add_fact("effect", [q, "mutation"])
                elif isinstance(n, ast.Raise) and "raise" not in seen_effects:
                    seen_effects.add("raise")
                    prog.add_fact("effect", [q, "raise"])
    return prog


_OPS_CACHE: dict = {}


def _ops():
    if not _OPS_CACHE:
        from ..kernel.store import default_store
        from .ir import op_table
        _OPS_CACHE.update(op_table(default_store()))
    return _OPS_CACHE


def as_card_source(prog: L.Program) -> str:
    lines = ["-- generated by `cardmodel logic code --facts`: the code base as facts", "module code_facts", ""]
    for pred, args, _ in prog.facts:
        lines.append(f"{L.Atom(pred, args)}.")
    return "\n".join(lines) + "\n"


__all__ = ["as_card_source", "facts_for"]
