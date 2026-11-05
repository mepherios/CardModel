"""lift_project — lift a whole project: calls across files and modules resolve, and Python methods lift.

One file at a time, a call to a function defined in another file is a gap ("no lifted function"). Here every file
of the project is read first for signatures, then each file is lifted with the others' functions as ``externs``:

* Python follows its imports: ``from pkg.mod import f as g``, ``import pkg.mod as m`` (``m.f(x)``), relative
  imports, and ``C.m(x)`` for a static method of an imported class;
* the text frontends link by name, as a C linker does: a call to a function no file-local definition answers
  resolves to the one other file of the same language that defines it (``Other.f`` for Java/C#/Kotlin, whose class
  is the file name); a name defined in several files stays unresolved;
* Python methods lift as functions named ``Class_method``: ``@staticmethod``, ``@classmethod`` and instance methods
  whose only use of ``self``/``cls`` is calling other methods of the class (``self.m(x)``). A method that reads
  or writes ``self.x`` needs record types and is reported as such.

Every function gets a qualified name ``<module>::<name>`` (``json.decoder::py_scanstring``, ``src/a.c::gcd``); CALLs
inside the lifted IR name callees by it, and :meth:`ProjectLift.module_for` turns one function and everything it
calls, across files, back into an ordinary IR module (bare names, mangled only where two files collide).

The closure is one pass over the reverse call graph of the whole project, so it is linear in calls
(frontend_python.close_calls). A function that did not lift is an opaque boundary (its signature, its cause and the
Python callable ``module.Class.method`` that implements it); its callers lift as ``partial`` with the edge recorded as
a gap, and :meth:`ProjectLift.module_for` with ``opaque=True`` gives their module with the boundary cards, which
only the host witness can run (engines/opaque.py). An instance method is never a boundary (the host would need its
receiver), so a caller of one that did not lift still fails.

Honest limits (L1): Python imports resolve statically (no ``__import__``, no star imports, no re-exports through
``__init__`` assignments); text languages link by name, not by build system or headers (SCALING.md §4.2);
signatures of unannotated callees are taken as ``int`` until their own lift says otherwise (a second round fixes
the callers whose callee result type changed).
"""
from __future__ import annotations

import ast
import copy
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from .context import Ctx

ROUNDS = 3


@dataclass
class ProjectLift:
    functions: dict = field(default_factory=dict)        # qual -> Lifted (Lifted.qual, .lang, .method set)
    unparsed: list = field(default_factory=list)
    cross_calls: int = 0

    def module_for(self, qual: str, opaque: bool = False) -> dict:
        """The IR module of ``qual`` and every function it calls, across files, with bare names. With ``opaque``,
        ``qual`` may be partial, and every callee that did not lift is listed under ``"opaque"`` as its boundary
        card (named as its CALLs name it), not followed."""
        need, order, cards = [qual], [], {}
        while need:
            q = need.pop()
            if q in order or q in cards:
                continue
            lf = self.functions[q]
            if not (lf.ok or (opaque and getattr(lf, "partial", False))):
                if opaque and q != qual and getattr(lf, "boundary", None) is not None:
                    cards[q] = lf.boundary
                    continue
                raise KeyError(f"{q} did not lift: {lf.reasons}")
            order.append(q)
            for c in _callees(lf.ir):
                if c not in order:
                    need.append(c)
        bare = {}
        counts: dict[str, int] = {}
        for q in order:
            counts[self.functions[q].ir["name"]] = counts.get(self.functions[q].ir["name"], 0) + 1
        for q in order:
            name = self.functions[q].ir["name"]
            bare[q] = name if counts[name] == 1 or q == qual else _mangle(q)
        for q in cards:
            bare[q] = _mangle(q)
        fns = [_renamed(self.functions[q].ir, bare[q], bare) for q in order]
        module = {"entry": bare[qual], "functions": fns}
        if opaque:
            module["opaque"] = [dict(c, name=bare[q]) for q, c in cards.items()]
        return module

    def by_name(self, name: str) -> list[str]:
        return [q for q in self.functions if q.rsplit("::", 1)[-1] == name]


def _mangle(qual: str) -> str:
    return re.sub(r"\W", "_", qual).strip("_")


def _callees(ir: dict) -> set[str]:
    from .frontend_python import callees_of
    return callees_of(ir)


def _renamed(ir: dict, name: str, names: dict) -> dict:
    out = copy.deepcopy(ir)
    out["name"] = name

    def fix(e):
        if isinstance(e, list) and e:
            if e[0] == "CALL" and e[1] in names:
                e[1] = names[e[1]]
            if e[0] not in ("var", "int", "float", "bool"):
                for a in e[1:]:
                    fix(a)

    def walk(body):
        for s in body:
            for key in ("value", "cond", "start", "stop", "step", "index"):
                if isinstance(s.get(key), list):
                    fix(s[key])
            for key in ("then", "else", "body", "default"):
                if key in s:
                    walk(s[key])
            for case in s.get("cases") or ():
                walk(case["body"])
    walk(out["body"])
    return out


def _requalify(ir: dict, local: dict[str, str]) -> None:
    """In place: CALLs to functions of the same file (bare names) name their qualified names."""
    def fix(e):
        if isinstance(e, list) and e:
            if e[0] == "CALL" and e[1] in local:
                e[1] = local[e[1]]
            if e[0] not in ("var", "int", "float", "bool"):
                for a in e[1:]:
                    fix(a)

    def walk(body):
        for s in body:
            for key in ("value", "cond", "start", "stop", "step", "index"):
                if isinstance(s.get(key), list):
                    fix(s[key])
            for key in ("then", "else", "body", "default"):
                if key in s:
                    walk(s[key])
            for case in s.get("cases") or ():
                walk(case["body"])
    walk(ir["body"])


# -- Python --------------------------------------------------------------------------------------------------------

def module_name(path: Path, root: Path) -> str:
    rel = path.relative_to(root).with_suffix("")
    parts = list(rel.parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts) or path.stem


@dataclass
class _PyFile:
    path: Path
    mod: str
    is_pkg: bool
    tree: ast.Module
    lines: list
    defs: list = field(default_factory=list)            # prepared FunctionDefs (methods renamed Class_m)
    method_of: dict = field(default_factory=dict)        # irname -> class name
    method_kind: dict = field(default_factory=dict)      # irname -> static | class | instance
    pre_fail: dict = field(default_factory=dict)         # irname -> reason found before lifting (self state)
    classes: set = field(default_factory=set)


class _MethodCalls(ast.NodeTransformer):
    """self.m(...), cls.m(...) and C.m(...) for a class C of this file -> C_m(...)."""

    def __init__(self, cls: str | None, receivers: set, methods: dict):
        self.cls = cls
        self.receivers = receivers
        self.methods = methods                           # class -> set of method names

    def visit_Call(self, node):
        self.generic_visit(node)
        f = node.func
        if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name):
            owner = f.value.id
            if owner in self.receivers and self.cls and f.attr in self.methods.get(self.cls, ()):
                node.func = ast.copy_location(ast.Name(id=f"{self.cls}_{f.attr}", ctx=ast.Load()), f)
            elif owner in self.methods and f.attr in self.methods[owner]:
                node.func = ast.copy_location(ast.Name(id=f"{owner}_{f.attr}", ctx=ast.Load()), f)
        return node


def _decorator_name(d) -> str:
    return ast.unparse(d)


def _self_use(fdef, recv: str, cls: str, methods: dict) -> str | None:
    """Why a method cannot lift without record types (a use of self other than calling a method), else None."""
    allowed = set()
    for node in ast.walk(fdef):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and \
                isinstance(node.func.value, ast.Name) and node.func.value.id == recv and \
                node.func.attr in methods.get(cls, ()):
            allowed.add(id(node.func.value))
    for node in ast.walk(fdef):
        if isinstance(node, ast.Name) and node.id == recv and id(node) not in allowed:
            parent_attr = next((p.attr for p in ast.walk(fdef) if isinstance(p, ast.Attribute) and p.value is node),
                               None)
            what = f"{recv}.{parent_attr}" if parent_attr else recv
            return f"line {node.lineno}: uses {what} (instance state needs record types)"
    return None


def _prepare_python(pf: _PyFile, methods: bool) -> None:
    methods_of: dict[str, set] = {}
    for node in pf.tree.body:
        if isinstance(node, ast.ClassDef):
            pf.classes.add(node.name)
            methods_of[node.name] = {n.name for n in node.body if isinstance(n, (ast.FunctionDef,
                                                                                ast.AsyncFunctionDef))}
    for node in pf.tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            f = _MethodCalls(None, set(), methods_of).visit(copy.deepcopy(node))
            pf.defs.append(f)
        elif methods and isinstance(node, ast.ClassDef):
            for m in node.body:
                if not isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                f = copy.deepcopy(m)
                decos = [_decorator_name(d) for d in f.decorator_list]
                irname = f"{node.name}_{m.name}"
                kind = "static" if "staticmethod" in decos else "class" if "classmethod" in decos else "instance"
                f.decorator_list = [d for d in f.decorator_list if _decorator_name(d) not in
                                    ("staticmethod", "classmethod")]
                recv = None
                if kind != "static":
                    if not f.args.args:
                        pf.pre_fail[irname] = f"line {m.lineno}: method without a self parameter"
                    else:
                        recv = f.args.args[0].arg
                        f.args.args = f.args.args[1:]
                        why = _self_use(f, recv, node.name, methods_of)
                        if why:
                            pf.pre_fail[irname] = why
                f = _MethodCalls(node.name, {recv} if recv else set(), methods_of).visit(f)
                f.name = irname
                pf.method_of[irname] = node.name
                pf.method_kind[irname] = kind
                pf.defs.append(f)


def _resolve_relative(pf: _PyFile, module: str | None, level: int) -> str:
    if not level:
        return module or ""
    base = pf.mod.split(".") if pf.is_pkg else pf.mod.split(".")[:-1]
    if level > 1:
        base = base[: len(base) - (level - 1)]
    return ".".join([*base, module] if module else base)


def _py_externs(pf: _PyFile, sigs: dict[str, dict], modules: set[str]) -> dict:
    """Call text -> extern entry, from this file's imports (only names that are lifted functions elsewhere)."""
    out: dict[str, dict] = {}
    by_mod: dict[str, list[str]] = {}
    for q in sigs:
        m, _, name = q.partition("::")
        by_mod.setdefault(m, []).append(name)

    def add(text, qual):
        if qual in sigs:
            out[text] = {"qual": qual, **sigs[qual]}

    def alias_module(alias, mod):
        for name in by_mod.get(mod, ()):
            if "_" in name and name.split("_", 1)[0] in _classes.get(mod, ()):
                cls, meth = name.split("_", 1)
                add(f"{alias}.{cls}.{meth}", f"{mod}::{name}")
            else:
                add(f"{alias}.{name}", f"{mod}::{name}")

    for node in ast.walk(pf.tree):
        if isinstance(node, ast.ImportFrom):
            src = _resolve_relative(pf, node.module, node.level)
            for a in node.names:
                local = a.asname or a.name
                if f"{src}.{a.name}" in modules:
                    alias_module(local, f"{src}.{a.name}")
                elif a.name in _classes.get(src, ()):
                    for name in by_mod.get(src, ()):
                        if name.startswith(a.name + "_"):
                            add(f"{local}.{name[len(a.name) + 1:]}", f"{src}::{name}")
                else:
                    add(local, f"{src}::{a.name}")
        elif isinstance(node, ast.Import):
            for a in node.names:
                if a.name in modules:
                    alias_module(a.asname or a.name, a.name)
    return out


_classes: dict[str, set] = {}


def _lift_python(ctx: Ctx, lang: str, files: list[Path], root: Path, methods: bool, cross: bool,
                 result: ProjectLift):
    from .frontend_python import Unsupported, _ann_type, lift_defs, module_constants
    pfs: list[_PyFile] = []
    for p in files:
        try:
            text = p.read_text(encoding="utf-8")
            tree = ast.parse(text)
        except (SyntaxError, UnicodeDecodeError, ValueError) as exc:
            result.unparsed.append(f"{p}: {type(exc).__name__}")
            continue
        pf = _PyFile(p, module_name(p, root), p.name == "__init__.py", tree, text.splitlines())
        _prepare_python(pf, methods)
        _classes[pf.mod] = pf.classes
        pfs.append(pf)
    modules = {pf.mod for pf in pfs}
    sigs: dict[str, dict] = {}
    for pf in pfs:
        for f in pf.defs:
            try:
                sigs[f"{pf.mod}::{f.name}"] = {"params": [_ann_type(a.annotation) or "int" for a in f.args.args],
                                                "returns": _ann_type(f.returns)}
            except Unsupported:
                continue
    externs = {pf.mod: (_py_externs(pf, sigs, modules) if cross else {}) for pf in pfs}
    consts = {pf.mod: module_constants(pf.tree) for pf in pfs}
    todo = list(pfs)
    for _round in range(ROUNDS):
        changed_quals = set()
        for pf in todo:
            lifted = lift_defs(pf.defs, pf.lines, ctx.ops, externs=externs[pf.mod], close=False, consts=consts[pf.mod])
            local = {lf.name: f"{pf.mod}::{lf.name}" for lf in lifted}
            for lf in lifted:
                qual = local[lf.name]
                lf.qual, lf.lang, lf.method = qual, lang, lf.name in pf.method_of
                lf.host_module = pf.mod
                if lf.method:              # the host calls Class.method; an instance method needs its receiver
                    kind = pf.method_kind[lf.name]
                    meth = lf.name[len(pf.method_of[lf.name]) + 1:]
                    lf.host = None if kind == "instance" else f"{pf.method_of[lf.name]}.{meth}"
                lf.call_lines = {local.get(c, c): line for c, line in lf.call_lines.items()}
                if lf.name in pf.pre_fail:
                    lf.ok, lf.ir, lf.reasons = False, None, [pf.pre_fail[lf.name]]
                if lf.ok:
                    _requalify(lf.ir, local)
                    old = sigs.get(qual, {}).get("returns")
                    if qual in sigs and old != lf.ir["returns"]:
                        sigs[qual]["returns"] = lf.ir["returns"]
                        changed_quals.add(qual)
                result.functions[qual] = lf
        if not cross or not changed_quals:
            break
        externs = {pf.mod: _py_externs(pf, sigs, modules) for pf in pfs}
        todo = [pf for pf in pfs if any(e["qual"] in changed_quals for e in externs[pf.mod].values())]
        if not todo:
            break


# -- text languages ---------------------------------------------------------------------------------------------------

def _lift_text(ctx: Ctx, lang: str, files: list[Path], root: Path, cross: bool, result: ProjectLift):
    from .frontend_text import lift_source, signatures
    texts, sigs_by_file = {}, {}
    for p in files:
        try:
            texts[p] = p.read_text(encoding="utf-8")
            sigs_by_file[p] = signatures(texts[p], ctx.ops, lang)
        except (UnicodeDecodeError, ValueError, RecursionError) as exc:
            result.unparsed.append(f"{p}: {type(exc).__name__}")
    keys = {p: str(p.relative_to(root)) if root in p.parents or p == root else p.name for p in texts}
    defined: dict[str, list] = {}
    for p, sigs in sigs_by_file.items():
        for name, sig in sigs.items():
            defined.setdefault(name, []).append((p, sig))
    classy = ctx.store.get(f"language/{lang}").get("frontend_link") == "class_per_file"   # Other.f(x)
    for p, text in texts.items():
        externs = {}
        if cross:
            for name, where in defined.items():
                others = [(q, sig) for q, sig in where if q != p]
                if name in sigs_by_file[p] or len(others) != 1:
                    continue
                q, sig = others[0]
                entry = {"qual": f"{keys[q]}::{name}", **sig}
                externs[name] = entry
                if classy:
                    externs[f"{q.stem}.{name}"] = entry
        try:
            lifted = lift_source(text, ctx.ops, lang, externs=externs, close=False)
        except (RecursionError, IndexError) as exc:
            result.unparsed.append(f"{p}: {type(exc).__name__}")
            continue
        local = {lf.name: f"{keys[p]}::{lf.name}" for lf in lifted}
        for lf in lifted:
            lf.qual, lf.method = local[lf.name], False
            if lf.ok:
                _requalify(lf.ir, local)
            result.functions[lf.qual] = lf


def lift_files(ctx: Ctx, files: list[tuple[Path, str]], methods: bool = True, cross: bool = True,
               root: Path | None = None) -> ProjectLift:
    """Lift every (path, language) of a project together."""
    from .frontend_python import close_calls
    result = ProjectLift()
    if not files:
        return result
    paths = [p.resolve() for p, _ in files]
    if root is None:
        root = Path(os.path.commonpath([str(p.parent) for p in paths]))
    by_lang: dict[str, list[Path]] = {}
    for (p, lang), rp in zip(files, paths):
        by_lang.setdefault(lang, []).append(rp)
    for lang, ps in by_lang.items():
        module = ctx.store.get(f"language/{lang}").get("frontend")
        if module == "cardmodel.engines.frontend_python":
            _lift_python(ctx, lang, ps, root, methods, cross, result)
        elif module != "cardmodel.engines.frontend_text":          # cardlang, math: one file at a time
            from . import frontends
            for p in ps:
                for lf in frontends.lift(ctx, p.read_text(encoding="utf-8"), lang):
                    lf.qual, lf.lang, lf.method = f"{p.name}::{lf.name}", lang, False
                    if lf.ok:
                        _requalify(lf.ir, {lf.name: lf.qual})
                    result.functions[lf.qual] = lf
        else:
            _lift_text(ctx, lang, ps, root, cross, result)
    close_calls(result.functions)
    for q, lf in result.functions.items():
        if lf.ok:
            home = q.split("::", 1)[0]
            result.cross_calls += sum(1 for c in _callees(lf.ir) if c.split("::", 1)[0] != home)
    return result


def lift_tree(ctx: Ctx, root: str | Path, methods: bool = True, cross: bool = True) -> ProjectLift:
    from . import frontends, sweep
    root = Path(root).resolve()
    exts = {}
    for lang in frontends.frontend_languages(ctx.store):
        for e in ctx.store.get(f"language/{lang}").get("extensions") or []:
            exts.setdefault(e, lang)
    files = sweep.files_under(root, exts, [])
    return lift_files(ctx, files, methods=methods, cross=cross, root=root if root.is_dir() else root.parent)
