"""pipeline — every capability runs in the main pipeline, at a stated tier (law CM50).

The main pipeline is what `cardmodel verify` and `cardmodel self run` do to the model's own cards: the verify
sections (``engines/verify.py`` SECTIONS; the quick ones in every self-run cycle, all of them in `verify` and the
cycle's daily ``verify_full``) and the self-run steps (``self_step`` cards naming a function in
``engines/selfrun.py`` STEPS). Each ``capability`` card declares, in its ``pipeline`` field:

  tier     the tier of the evidence its pipeline run gives (CM46: proof, probabilistic, bounded, sample), with
           ``tier_reason``, one sentence on why it is that tier and not a stronger one
  runs     the stages that exercise its engine: ``{"verify": SECTION}`` or ``{"self_step": STEP}``
  gap      when no stage exercises it: ``reason`` (why not yet), ``closes_by`` (what would wire it in) and ``goal``
           (the goal card that counts the gap). A gap is visible and counted, never silent

``check`` reads the declarations and the program's code and fails on:
  undeclared   a capability with no ``pipeline`` field, no tier, or a tier outside CM46's four
  unknown      a run naming a verify section or a self step that does not exist, or a step the cycle never makes
               due (``auto`` off, or no ``every_hours`` and no ``on_change``)
  not counted  a run naming a stage that does not count: the ``capabilities`` smoke checks (every capability is
               there by construction, CM37), the ``verify``/``verify_full`` steps (name the section they run), and
               the ``tests``/``law_witnesses`` steps (they run the witness tests, not the pipeline)
  unexercised  a declared run whose stage does not reach the capability's code: the stage's entry (its branch in
               ``verify.run`` or its function in ``selfrun``, with the helpers it calls in that file) must import
               one of the capability's ``modules``, directly or through one module it imports
  never run    a capability with no counted run and no recorded gap; or a gap without a reason, a way to close it,
               or a goal card that exists; or a gap recorded beside runs (it would hide that the capability runs)

``registry`` gives the whole table: per capability its tier, its runs with the import path that links each to
the capability's code, and its gap. `cardmodel pipeline` prints it.

Honest limits (L1): "reaches" is read from imports, not from a trace: a stage that imports the capability's
module but never calls the part that matters passes, and one that reaches it through two or more modules is not
seen (declare a module of the capability nearer to the stage, or the stage that calls it). The tier is the card's
word, checked only for being one of CM46's; the ``tiers`` section and the witness tests check the claims behind it.
"""
from __future__ import annotations

import ast
from functools import lru_cache
from pathlib import Path

from ..kernel import paths

from .tiers import TIERS  # noqa: E402  (CM46: one list of tiers)
# stages that exist but do not count as running a capability (the docstring says why)
NOT_COUNTED = {("verify", "capabilities"): "the smoke checks run every capability by construction (CM37)",
               ("self_step", "capabilities"): "the smoke checks run every capability by construction (CM37)",
               ("self_step", "verify"): "a container: name the verify section it runs",
               ("self_step", "verify_full"): "a container: name the verify section it runs",
               ("self_step", "tests"): "runs the witness tests, not the pipeline",
               ("self_step", "law_witnesses"): "runs the witness tests, not the pipeline"}
KINDS = ("verify", "self_step", "cycle")


# -- the code: what a stage calls --------------------------------------------------------------------------------
# A node is (module, name): a function or class of the program's own code, or (module, None) for a module used
# as a whole. A stage's entry calls nodes; a node that is a function (or a class: its methods) calls more.
DEPTH = 6


def _modname(rel: Path) -> str:
    return ".".join(rel.with_suffix("").parts).removesuffix(".__init__")


@lru_cache(maxsize=4)
def _modules(home: str) -> dict[str, Path]:
    root = Path(home)
    return {_modname(p.relative_to(root)): p for p in (root / "cardmodel").rglob("*.py")}


def _resolve(mods: dict, cur: str, node) -> dict[str, tuple[str, str | None]]:
    """{local name: (module, name or None)} for one import statement in module ``cur`` (the program's own)."""
    out = {}
    if isinstance(node, ast.ImportFrom):
        parts = cur.split(".")
        if node.level:
            keep = len(parts) - node.level + (1 if mods[cur].name == "__init__.py" else 0)
            prefix = ".".join(parts[:keep] + ([node.module] if node.module else []))
        else:
            prefix = node.module or ""
        for a in node.names:
            full = f"{prefix}.{a.name}"
            if full in mods:
                out[a.asname or a.name] = (full, None)
            elif prefix in mods:
                out[a.asname or a.name] = (prefix, a.name)
    elif isinstance(node, ast.Import):
        for a in node.names:
            if a.name in mods:
                out[a.asname or a.name.split(".")[0]] = (a.name, None)
    return out


class _File:
    """One module of the program: its module-level import names, functions and classes."""

    def __init__(self, home: str, mod: str):
        self.home, self.mod = home, mod
        self.mods = _modules(home)
        self.tree = ast.parse(self.mods[mod].read_text(encoding="utf-8"))
        self.names: dict[str, tuple[str, str | None]] = {}
        self.defs: dict[str, list] = {}
        for n in self.tree.body:
            if isinstance(n, (ast.Import, ast.ImportFrom)):
                self.names.update(_resolve(self.mods, mod, n))
            elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                self.defs[n.name] = n.body
            elif isinstance(n, (ast.Assign, ast.AnnAssign)) and n.value is not None:
                for t in (n.targets if isinstance(n, ast.Assign) else [n.target]):
                    if isinstance(t, ast.Name):            # a module-level table: BACKENDS = [lean]
                        self.defs[t.id] = [ast.Expr(n.value)]

    def calls(self, stmts: list, seen: set | None = None) -> set[tuple[str, str | None]]:
        """The nodes some statements use: their own imports, the module-level import names they read (``X.f`` as
        (X, f)), and, followed within this file, every function or class of this file they name."""
        seen = set() if seen is None else seen
        names = {**self.names, **_local_imports(self, stmts)}
        out: set = set()
        for stmt in stmts:
            for n in ast.walk(stmt):
                if isinstance(n, (ast.Import, ast.ImportFrom)):
                    out.update(_resolve(self.mods, self.mod, n).values())
                elif isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name):
                    tgt = names.get(n.value.id)
                    if tgt and tgt[1] is None:
                        out.add((tgt[0], n.attr))
                elif isinstance(n, ast.Name):
                    if n.id in names:
                        out.add(names[n.id])
                    elif n.id in self.defs and n.id not in seen:
                        seen.add(n.id)
                        out.add((self.mod, n.id))
                        out |= self.calls(self.defs[n.id], seen)
        return out


def _local_imports(f: _File, stmts: list) -> dict:
    out = {}
    for stmt in stmts:
        for n in ast.walk(stmt):
            if isinstance(n, (ast.Import, ast.ImportFrom)):
                out.update(_resolve(f.mods, f.mod, n))
    return out


@lru_cache(maxsize=512)
def _file(home: str, mod: str) -> _File:
    return _File(home, mod)


@lru_cache(maxsize=4096)
def _node_calls(home: str, mod: str, name: str) -> frozenset:
    f = _file(home, mod)
    body = f.defs.get(name)
    return frozenset(f.calls(body, {name})) if body is not None else frozenset()


def _branches(fn, var: str) -> tuple[dict[str, list], list | None]:
    """The ``if var == "x": ... elif ...: ... else: ...`` chain in ``fn``: {x: body}, and the final else body."""
    for n in ast.walk(fn):
        if not isinstance(n, ast.If):
            continue
        t = n.test
        if not (isinstance(t, ast.Compare) and isinstance(t.left, ast.Name) and t.left.id == var
                and isinstance(t.ops[0], ast.Eq)):
            continue
        out, node, rest = {}, n, None
        while True:
            c = node.test
            if isinstance(c, ast.Compare) and isinstance(c.comparators[0], ast.Constant):
                out[c.comparators[0].value] = node.body
            if len(node.orelse) == 1 and isinstance(node.orelse[0], ast.If):
                node = node.orelse[0]
                continue
            rest = node.orelse or None
            break
        return out, rest
    return {}, None


@lru_cache(maxsize=4)
def stages(home: str | None = None) -> dict[tuple[str, str], dict]:
    """{(kind, name): {"calls": the nodes its entry uses, "entry": where}} for every verify section and every
    function the self-run cycle can call (by its STEPS name)."""
    from . import selfrun, verify
    home = str(home or paths.home())
    out = {}
    vf = _File(home, "cardmodel.engines.verify")
    by, rest = _branches(_fn(vf, "run"), "sec")
    unnamed = [s for s in verify.SECTIONS if s not in by]
    for sec in verify.SECTIONS:
        body = by.get(sec, rest if len(unnamed) == 1 else None)
        out[("verify", sec)] = {"calls": frozenset(vf.calls(body or [])), "entry": f"engines/verify.py run(): {sec!r}",
                                  "module": vf.mod}
    sf = _File(home, "cardmodel.engines.selfrun")
    out[("cycle", "self run")] = {"calls": frozenset(sf.calls(sf.defs.get("cycle") or [], {"cycle"})),
                                  "entry": "engines/selfrun.py cycle()", "module": None}
    for name, fn in selfrun.STEPS.items():
        out[("self_step", name)] = {"calls": frozenset(sf.calls(sf.defs.get(fn.__name__) or [], {fn.__name__})),
                                    "entry": f"engines/selfrun.py {fn.__name__}()", "module": sf.mod}
    return out


def _fn(f: _File, name: str):
    return next(n for n in f.tree.body if isinstance(n, ast.FunctionDef) and n.name == name)


def _owns(mod: str, paths_: list[str]) -> bool:
    """Is module ``mod`` (dotted) one of a capability's ``modules`` (files or folders, repository-relative)?"""
    rel = mod.replace(".", "/")
    for p in paths_:
        p = p.rstrip("/")
        if p.endswith(".py"):
            if rel + ".py" == p or rel + "/__init__.py" == p:
                return True
        elif rel == p or rel.startswith(p + "/"):
            return True
    return False


def link(stage: dict, modules: list[str], home: str | None = None) -> list[str] | None:
    """The call path from a stage's entry to the capability's code (``module.name`` per hop, at most DEPTH hops,
    breadth first, so the shortest), or None when the stage never reaches it. The entry's own file (verify.py,
    selfrun.py) does not count as the capability's code: every stage is in it."""
    home = str(home or paths.home())
    start = sorted(stage["calls"], key=lambda n: (n[0], n[1] or ""))
    parent: dict = {n: None for n in start}
    frontier = start
    for _ in range(DEPTH):
        nxt = []
        for node in frontier:
            if node[0] != stage["module"] and _owns(node[0], modules):
                path = []
                while node is not None:
                    path.append(f"{node[0].removeprefix('cardmodel.')}" + (f".{node[1]}" if node[1] else ""))
                    node = parent[node]
                return path[::-1]
            if node[1] is None:
                continue
            for m in sorted(_node_calls(home, node[0], node[1]), key=lambda n: (n[0], n[1] or "")):
                if m not in parent:
                    parent[m] = node
                    nxt.append(m)
        frontier = nxt
    return None


# -- the cards ----------------------------------------------------------------------------------------------------
def _step_due_ever(card) -> bool:
    return card is not None and card.get("auto", True) and (card.get("every_hours") is not None
                                                            or bool(card.get("on_change")))


def registry(ctx, home: str | None = None) -> dict:
    """Per capability: its tier, its runs (each with its stage's entry and the import path to its code, or the
    problem), its gap, and the problems found."""
    from . import verify
    home = str(home or paths.home())
    st = stages(home)
    step_cards = {c.name: c for c in ctx.store.cards("self_step")}
    goals = {c.qualified for c in ctx.store.cards("goal")}
    last = _last(ctx)
    rows = {}
    for cap in sorted(ctx.store.cards("capability"), key=lambda c: (c.get("order", 999), c.name)):
        q = f"capability/{cap.name}"
        decl = cap.get("pipeline")
        probs: list[str] = []
        row = {"tier": None, "runs": [], "gap": None, "running": False, "problems": probs}
        rows[cap.name] = row
        if not isinstance(decl, dict):
            probs.append(f"{q}: no `pipeline` field: where it runs in the main pipeline and at what tier (CM50)")
            continue
        tier = decl.get("tier")
        row["tier"] = tier
        if tier not in TIERS:
            probs.append(f"{q}: pipeline tier {tier!r} is not one of {', '.join(TIERS)} (CM46, CM50)")
        elif not decl.get("tier_reason"):
            probs.append(f"{q}: pipeline tier {tier!r} has no `tier_reason`")
        mods = list(cap.get("modules") or [])
        for run in decl.get("runs") or []:
            kinds = [k for k in KINDS if k in (run if isinstance(run, dict) else {})]
            if len(kinds) != 1:
                probs.append(f"{q}: a run must name one of {KINDS}: {run!r}")
                continue
            kind, name = kinds[0], run[kinds[0]]
            r = {"kind": kind, "stage": name, "counted": False}
            row["runs"].append(r)
            if (kind, name) in NOT_COUNTED:
                r["problem"] = f"{kind} {name!r} does not count: {NOT_COUNTED[(kind, name)]}"
            elif kind == "verify" and name not in verify.SECTIONS:
                r["problem"] = f"verify section {name!r} does not exist"
            elif kind == "cycle" and name != "self run":
                r["problem"] = f"the only cycle is 'self run', not {name!r}"
            elif kind == "self_step" and name not in step_cards:
                r["problem"] = f"self step {name!r} has no self_step card"
            elif kind == "self_step" and ("self_step", step_cards[name].get("run", name)) not in st:
                r["problem"] = f"self step {name!r} runs {step_cards[name].get('run')!r}, which selfrun.STEPS lacks"
            elif kind == "self_step" and not _step_due_ever(step_cards[name]):
                r["problem"] = f"self step {name!r} is never due (auto off, or no every_hours and no on_change)"
            else:
                key = (kind, step_cards[name].get("run", name) if kind == "self_step" else name)
                r["entry"] = st[key]["entry"]
                if kind == "verify":
                    r["where"] = ("verify --quick, every self-run cycle" if name in verify.QUICK
                                  else "full verify, the self-run's daily verify_full")
                elif kind == "cycle":
                    r["where"] = "self run, every cycle (findings, plan, record)"
                else:
                    c = step_cards[name]
                    r["where"] = ("self run, every cycle" if c.get("every_hours") == 0 else
                                  f"self run, every {c.get('every_hours')} h" if c.get("every_hours") else
                                  f"self run, when {', '.join(c.get('on_change') or [])} cards change")
                path = link(st[key], mods, home)
                if path is None:
                    r["problem"] = (f"{r['entry']} does not reach the capability's code ({', '.join(mods) or 'no modules'}) "
                                    f"within {DEPTH} calls")
                else:
                    r["via"] = path
                    r["counted"] = True
                    r["last"] = last.get((kind, name))
            if "problem" in r:
                probs.append(f"{q}: {r['problem']} (declared but not exercised)")
        row["running"] = any(r["counted"] for r in row["runs"])
        gap = decl.get("gap")
        row["gap"] = gap
        if gap is not None:
            if not isinstance(gap, dict):
                probs.append(f"{q}: its gap is not an object with reason, closes_by and goal")
            else:
                for k in ("reason", "closes_by", "goal"):
                    if not gap.get(k):
                        probs.append(f"{q}: its gap has no `{k}`")
                if gap.get("goal") and gap["goal"] not in goals:
                    probs.append(f"{q}: its gap names {gap['goal']}, which is not a goal card")
        elif not row["running"]:
            probs.append(f"{q}: never runs in the main pipeline and records no gap (CM50)")
    return rows


def _last(ctx) -> dict:
    """{(kind, stage): status} of the latest recorded run of every stage on this host: the saved verify report and the
    self-run's state. Informational: a fresh checkout has none, and a host without a toolchain skips."""
    out = {}
    lv = (ctx.load_state("last_verify") or {}).get("sections") or {}
    for sec, r in lv.items():
        if isinstance(r, dict):
            out[("verify", sec)] = r.get("status")
    try:
        from . import selfrun
        res = ((selfrun._read(selfrun.self_dir() / "state.json") or {}).get("results")) or {}
    except Exception:  # noqa: BLE001 -- no self-run state on this host
        res = {}
    for step, r in res.items():
        if isinstance(r, dict):
            out[("self_step", step)] = r.get("status")
    return out


def check(ctx) -> dict:
    """The verify section: fail on any problem the registry finds; count what runs and what is a recorded gap."""
    rows = registry(ctx)
    problems = [p for r in rows.values() for p in r["problems"]]
    running = sorted(n for n, r in rows.items() if r["running"])
    gaps = sorted(n for n, r in rows.items() if isinstance(r["gap"], dict))
    never = sorted(n for n, r in rows.items() if not r["running"])
    idle = sorted({n for n, r in rows.items() for x in r["runs"]
                   if x.get("last") in ("skipped", "vacuous", "unavailable")})
    tiers = {t: sum(1 for r in rows.values() if r["tier"] == t) for t in TIERS}
    status = "fail" if problems else ("pass" if rows else "vacuous")
    return {"status": status, "problems": problems, "capabilities": len(rows), "running": len(running),
            "never_run": never, "partial": sorted(set(gaps) & set(running)), "gaps": gaps, "gap_count": len(gaps),
            "idle_here": idle, "tiers": tiers,
            "registry": {n: {"tier": r["tier"], "running": r["running"],
                             "runs": [{k: v for k, v in x.items()
                                       if k in ("kind", "stage", "where", "via", "last", "problem")} for x in r["runs"]],
                             **({"gap": r["gap"]} if r["gap"] else {})} for n, r in rows.items()}}


def table(res: dict) -> str:
    """The registry as text for `cardmodel pipeline`."""
    lines = [f"{res['running']} of {res['capabilities']} capabilities run in the main pipeline "
             f"({len(res['partial'])} of them in part); {res['gap_count']} recorded gaps; tiers {res['tiers']}"]
    for n, r in res["registry"].items():
        runs = ", ".join(f"{x['kind'].replace('self_step', 'step')} {x['stage']}"
                         + (" (!)" if "problem" in x else f" [last here: {x['last']}]" if x.get("last") else "")
                         for x in r["runs"]) or "-"
        state = ("part" if r.get("gap") else "runs") if r["running"] else ("GAP" if r.get("gap") else "NONE")
        lines.append(f"  {n:<22} {str(r['tier']):<9} {state:<5} {runs}")
        if r.get("gap"):
            lines.append(f"  {'':<22} gap: {r['gap'].get('reason')}")
            lines.append(f"  {'':<22}   closes by: {r['gap'].get('closes_by')} ({r['gap'].get('goal')})")
    if res.get("idle_here"):
        lines.append(f"  a declared stage skipped or ran nothing in its latest run on this host: {', '.join(res['idle_here'])}")
    for p in res["problems"]:
        lines.append(f"  problem: {p}")
    return "\n".join(lines)


__all__ = ["NOT_COUNTED", "TIERS", "check", "link", "registry", "stages", "table"]
