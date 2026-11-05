"""pipeline — every capability runs in the main pipeline, at a stated tier, true to the Gödel model (law CM50).

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

Gödel purity (GODEL_AUDIT §2, GODEL_TARGET §7, docs/GODEL_PURITY rules 1-3): each card's ``godel`` field holds its
verdict, CORE or KEYED with what it needs from the core (a-e), CONSUMER, or NO with why not (i-v), and ``why``.
The check fails on:
  no verdict   a capability without ``godel``, or a verdict, need or reason outside those lists
  not wired    a CORE or KEYED capability whose own modules never name engines/godel.py, godel1931.py or the identity
               hash (egraph.semantic_hash), unless it records a ``gap`` (reason, closes_by, goal); a gap recorded
               while the code calls the core fails too. The pipeline's drivers (verify, capabilities, selfrun) name
               the core only to run its checks and do not count
  copies       (in the integrity section, ``purity_problems``) code outside godel.py and godel1931.py that does the
               core's algebra itself (``purity_findings``: primes, content, the zigzag, positional tokens, prime
               powers, sieves, similarity over content), unless a capability records it under ``copies`` (at, rule,
               reason, closes_by, owner, goal); a recorded copy the code no longer has fails too
Recorded gaps and copies are counted by goal G_A14 (``godel_impure``).

``registry`` gives the whole table: per capability its tier, its runs with the import path that links each to
the capability's code, and its gap. `cardmodel pipeline` prints it.

Honest limits (L1): "reaches" is read from imports, not from a trace: a stage that imports the capability's
module but never calls the part that matters passes, and one that reaches it through two or more modules is not
seen (declare a module of the capability nearer to the stage, or the stage that calls it). The tier is the card's
word, checked only for being one of CM46's; the ``tiers`` section and the witness tests check the claims behind it.
The Gödel verdict is the audit's word too: the check sees that a CORE or KEYED capability names the core, not that it
uses it for what it needs; and the copy scan reads names and prime powers, so a copy spelled otherwise (a prime table
built by another name, ``by[i] ** e`` with ``by`` mapping indices to primes) is not seen.
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


# -- Gödel purity (GODEL_AUDIT §2, GODEL_TARGET §7) -------------------------------------------------------------
GODEL_CORE = ("cardmodel.engines.godel", "cardmodel.engines.godel1931")
IDENTITY = ("cardmodel.engines.egraph", "semantic_hash")     # the identity hash is the core's too (GODEL_PURITY 1)
VERDICTS = ("CORE", "KEYED", "CONSUMER", "NO")
LEAN_CORE = "formal/GodelCore"
# the pipeline's drivers name the core only to run its checks: that is not their capability using it
DRIVERS = ("cardmodel.engines.verify", "cardmodel.engines.capabilities", "cardmodel.engines.selfrun")
NEEDS = ("a", "b", "c", "d", "e")
REASONS = ("i", "ii", "iii", "iv", "v")
# names of the core's algebra: a definition of one of these outside the core that does not call the core re-implements it
FAMILY = frozenset({"primes", "nth_prime", "zig", "unzig", "term_content", "module_content", "card_content", "content",
                    "tokens", "structural", "exponents", "from_tokens", "valuation", "sieve"})


def _owned_modules(home: str, modules: list[str]) -> list[str]:
    return sorted(m for m in _modules(home) if _owns(m, modules))


def calls_core(home: str, modules: list[str]) -> str | None:
    """How a capability's own code reaches the Gödel core (engines/godel.py, godel1931.py, or the identity hash
    egraph.semantic_hash): ``module -> core`` for the first module that names it, or None. Direct references only."""
    if any(str(p).rstrip("/").startswith(LEAN_CORE) for p in modules):
        return "formal/GodelCore is the core's own proofs"
    owned = _owned_modules(home, modules)
    for m in owned:
        if m in GODEL_CORE or m == IDENTITY[0]:
            return f"{m.removeprefix('cardmodel.')} is the core"
    for m in owned:
        if m in DRIVERS:
            continue
        f = _file(home, m)
        for node in sorted(f.calls(f.tree.body), key=lambda n: (n[0], n[1] or "")):
            if node[0] in GODEL_CORE or node == IDENTITY:
                return f"{m.removeprefix('cardmodel.')} -> {node[0].removeprefix('cardmodel.')}" + \
                    (f".{node[1]}" if node[1] else "")
    return None


def recorded_copies(ctx) -> dict[str, str]:
    """{"path:function": capability} for every known copy of the core's algebra a capability card records."""
    return {c["at"]: cap.name for cap in ctx.store.cards("capability")
            for c in ((cap.get("godel") or {}).get("copies") or []) if isinstance(c, dict) and c.get("at")}


def purity_problems(ctx, home: str | None = None) -> list[str]:
    """Every copy of the core's algebra in the code is recorded on a capability card, and every record is still
    true (GODEL_TARGET §7): the part of the integrity check that keeps the program pure to the Gödel model."""
    found, recorded = purity_findings(home), recorded_copies(ctx)
    out = [f"{at}: {found[at]}, outside engines/godel.py: call the core, or record it under `godel.copies` on the "
           f"capability that owns it (GODEL_TARGET §7, CM50)" for at in sorted(set(found) - set(recorded))]
    out += [f"capability/{recorded[at]}: records a copy of the core at {at}, which the code no longer has: remove "
            f"the record" for at in sorted(set(recorded) - set(found))]
    return out


def _defs(tree) -> list[tuple[str, ast.AST]]:
    """(qualified name, node) for every top-level function and every method: a nested function belongs to the one
    that holds it (``Reader.codes`` holds its ``walk``)."""
    out = []
    for n in tree.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.append((n.name, n))
        elif isinstance(n, ast.ClassDef):
            out += [(f"{n.name}.{m.name}", m) for m in n.body if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))]
    return out


def _is_const(n, values) -> bool:
    return isinstance(n, ast.Constant) and type(n.value) is int and n.value in values


def _token_code(n) -> int | None:
    """c for ``3 * x + c`` (c = 1, 2, 3) in either order, else None. Gödel's Def-27 positional tokens are atom 3k+1,
    integer 3·zig+2, variable 3j+3: a function with two or more of the three forms encodes terms (one alone is a
    stride or an estimate, such as a PNG row of 3w + 1 bytes)."""
    if not (isinstance(n, ast.BinOp) and isinstance(n.op, ast.Add)):
        return None
    for mul, c in ((n.left, n.right), (n.right, n.left)):
        if _is_const(c, (1, 2, 3)) and isinstance(mul, ast.BinOp) and isinstance(mul.op, ast.Mult) and \
                (_is_const(mul.left, (3,)) or _is_const(mul.right, (3,))):
            return c.value
    return None


@lru_cache(maxsize=4)
def purity_findings(home: str | None = None) -> dict[str, str]:
    """Code outside engines/godel.py and godel1931.py that does the core's algebra itself (GODEL_TARGET §7, the
    owner's purity rule 1): {"path:function": the rule it breaks}. Five readings of each function:
      core name     named like the core's algebra (FAMILY, or prime/zig in the name) and never calling the core
      tokens        a positional token scheme: two or more of ``3 * x + 1``, ``3 * x + 2``, ``3 * x + 3`` (Def-27)
      prime power   a power whose base is a prime: ``p ** e`` with p from a list of primes, ``nth_prime(i) ** c``,
                    ``index[a]["prime"] ** e`` (a Gödel number composed by hand)
      sieve         a list named for primes that the function grows while testing divisibility (``%``)
      similarity    a jaccard or similarity over content that does not call the core's ``jaccard``
    A function that calls the core for the same thing (a thin wrapper) is not a copy."""
    home = str(home or paths.home())
    out = {}
    for m, path in sorted(_modules(home).items()):
        if m in GODEL_CORE:
            continue
        f = _file(home, m)
        src = path.read_text(encoding="utf-8")
        rel = str(path.relative_to(home))

        lines = src.encode("utf-8").splitlines(keepends=True)     # ast's column offsets count UTF-8 bytes

        def seg(n) -> str:              # ast.get_source_segment re-splits the whole file on every call
            if not hasattr(n, "lineno"):
                return ""
            if n.lineno == n.end_lineno:
                b = lines[n.lineno - 1][n.col_offset:n.end_col_offset]
            else:
                b = b"".join([lines[n.lineno - 1][n.col_offset:], *lines[n.lineno:n.end_lineno - 1],
                              lines[n.end_lineno - 1][:n.end_col_offset]])
            return b.decode("utf-8", errors="replace")
        for qual, fn in _defs(f.tree):
            name = fn.name.lstrip("_")
            key = f"{rel}:{qual}"
            nodes = list(ast.walk(fn))
            named = name in FAMILY or "prime" in name or "zig" in name
            similar = ("jaccard" in name or "similar" in name) and "content" in seg(fn)
            core = {c for c in f.calls(fn.body, {fn.name}) if c[0] in GODEL_CORE} if named or similar else set()
            pv = set()
            for x in nodes:
                if isinstance(x, (ast.For, ast.comprehension)) and "prime" in seg(x.iter):
                    pv |= {n.id for n in ast.walk(x.target) if isinstance(n, ast.Name)}
            found = None
            if named and not core:
                found = f"core name: defines {qual} without calling the core"
            elif len({_token_code(x) for x in nodes} - {None}) >= 2:
                found = "tokens: a positional token scheme (3k+1, 3·zig+2, 3j+3) outside godel.tokens"
            elif any(isinstance(x, ast.BinOp) and isinstance(x.op, ast.Pow) and
                     ("prime" in seg(x.left) or (isinstance(x.left, ast.Name) and x.left.id in pv)) for x in nodes):
                found = "prime power: a product of primes raised to exponents, composed by hand"
            elif any(isinstance(x, ast.BinOp) and isinstance(x.op, ast.Mod) for x in nodes) and any(
                    isinstance(x, ast.Call) and isinstance(x.func, ast.Attribute) and x.func.attr == "append"
                    and "prime" in seg(x.func.value) for x in nodes):
                found = "sieve: a list of primes grown by trial division"
            elif similar and not any(c[1] == "jaccard" for c in core):
                found = "similarity: a similarity over content outside godel.jaccard"
            if found:
                out[key] = found
    return out


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
            _godel_row(q, cap, row, goals, home)
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
            probs += _gap_problems(q, "gap", gap, goals)
        elif not row["running"]:
            probs.append(f"{q}: never runs in the main pipeline and records no gap (CM50)")
        _godel_row(q, cap, row, goals, home)
    return rows


def _gap_problems(q: str, what: str, gap, goals: set) -> list[str]:
    if not isinstance(gap, dict):
        return [f"{q}: its {what} is not an object with reason, closes_by and goal"]
    out = [f"{q}: its {what} has no `{k}`" for k in ("reason", "closes_by", "goal") if not gap.get(k)]
    if gap.get("goal") and gap["goal"] not in goals:
        out.append(f"{q}: its {what} names {gap['goal']}, which is not a goal card")
    return out


def _godel_row(q: str, cap, row: dict, goals: set, home: str) -> None:
    """The capability's Gödel verdict (GODEL_AUDIT §2) held to its code: a CORE or KEYED capability must call the
    core, or record why not yet (``gap``); a NO names its reason (i-v); copies of the core's algebra it records."""
    probs = row["problems"]
    g = cap.get("godel")
    row["godel"] = g if isinstance(g, dict) else None
    if not isinstance(g, dict):
        probs.append(f"{q}: no `godel` field: its Gödel verdict, CORE, KEYED, CONSUMER or NO (GODEL_AUDIT §2, CM50)")
        return
    v = g.get("verdict")
    if v not in VERDICTS:
        probs.append(f"{q}: Gödel verdict {v!r} is not one of {', '.join(VERDICTS)}")
        return
    if not g.get("why"):
        probs.append(f"{q}: its Gödel verdict {v} has no `why`")
    if v in ("CORE", "KEYED"):
        needs = [x.strip() for x in str(g.get("needs") or "").split(",") if x.strip()]
        if not needs or any(x not in NEEDS for x in needs):
            probs.append(f"{q}: a {v} verdict names what it needs from the core, some of a-e (GODEL_AUDIT §2): "
                         f"{g.get('needs')!r}")
        via = calls_core(home, list(cap.get("modules") or []))
        row["godel_calls"] = via
        if via is None and not g.get("gap"):
            probs.append(f"{q}: its card says {v} but its code does not call engines/godel.py (or the identity hash), "
                         f"and it records no gap (CM50)")
        elif via is not None and g.get("gap"):
            probs.append(f"{q}: records a Gödel gap but its code calls the core ({via}): remove the gap")
    elif v == "NO" and g.get("reason") not in REASONS:
        probs.append(f"{q}: a NO verdict names its reason, one of {', '.join(REASONS)} (GODEL_AUDIT §2): "
                     f"{g.get('reason')!r}")
    if g.get("gap"):
        probs += _gap_problems(q, "Gödel gap", g["gap"], goals)
    for c in g.get("copies") or []:
        probs += _gap_problems(q, f"copy {c.get('at') if isinstance(c, dict) else c!r}", c, goals)


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
    # Gödel purity: the copies of the core's algebra the cards record (the integrity check holds them to the code)
    recorded = recorded_copies(ctx)
    verdicts = {v: sum(1 for r in rows.values() if (r.get("godel") or {}).get("verdict") == v) for v in VERDICTS}
    unwired = sorted(n for n, r in rows.items() if (r.get("godel") or {}).get("gap"))
    status = "fail" if problems else ("pass" if rows else "vacuous")
    return {"status": status, "problems": problems, "capabilities": len(rows), "running": len(running),
            "never_run": never, "partial": sorted(set(gaps) & set(running)), "gaps": gaps, "gap_count": len(gaps),
            "idle_here": idle, "tiers": tiers, "godel_verdicts": verdicts, "godel_unwired": unwired,
            "godel_copies": sorted(recorded), "godel_impure": len(unwired) + len(recorded),
            "registry": {n: {"tier": r["tier"], "running": r["running"],
                             "runs": [{k: v for k, v in x.items()
                                       if k in ("kind", "stage", "where", "via", "last", "problem")} for x in r["runs"]],
                             **({"gap": r["gap"]} if r["gap"] else {}),
                             "godel": r.get("godel"), "godel_calls": r.get("godel_calls")} for n, r in rows.items()}}


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
        g = r.get("godel") or {}
        if g:
            what = g.get("needs") if g.get("verdict") in ("CORE", "KEYED") else g.get("reason")
            lines.append(f"  {'':<22} Gödel {g.get('verdict')}" + (f" ({what})" if what else "")
                         + (f", calls the core: {r['godel_calls']}" if r.get("godel_calls") else "")
                         + (f"; NOT WIRED: {g['gap']['closes_by']}" if g.get("gap") else "")
                         + "".join(f"; copy at {c.get('at')}" for c in g.get("copies") or []))
    lines.insert(1, f"Gödel verdicts {res['godel_verdicts']}; {len(res['godel_unwired'])} CORE/KEYED not calling the "
                    f"core, {len(res['godel_copies'])} recorded copies of its algebra (G_A14: {res['godel_impure']})")
    if res.get("idle_here"):
        lines.append(f"  a declared stage skipped or ran nothing in its latest run on this host: {', '.join(res['idle_here'])}")
    for p in res["problems"]:
        lines.append(f"  problem: {p}")
    return "\n".join(lines)


__all__ = ["DRIVERS", "FAMILY", "GODEL_CORE", "NOT_COUNTED", "TIERS", "VERDICTS", "calls_core", "check", "link",
           "purity_findings", "purity_problems", "recorded_copies", "registry", "stages", "table"]
