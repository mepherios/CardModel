"""scan — every function of the engine's math, lifted or classified, across its translation units.

Order: (1) the engine's .cpp units give their constants (static members such as ``FVector3d::ZeroVector`` are
defined there); (2) the header unit lifts every function it holds, with those constants; (3) each .cpp unit lifts
the functions defined in it and any header function the header unit did not hold. A function is identified by
its mangled name, so one defined in a header and seen by several units is one function.

The universe is every function with a body in the math files that the programmer wrote (not compiler-generated)
and that is concrete (a template's instantiation, not its pattern). A function whose signature is about something
other than numbers (archives, strings, names, memory images, type layouts) is outside the math universe and counted
as such; every other function is lifted, or carries the cause that stops it (lift.Gap).

The result is saved in the cache (``scan.jsonl``: a header line, then one function per line, so a reader that
needs a few functions streams it instead of holding all of them): it is what distill.py, witness.py and cards.py
read.

Honest limits (L1): the universe is what the units instantiate (the header unit instantiates each class template
for one type, double or int32; float instantiations appear where the engine's own code uses them); a unit clang
cannot dump is reported with its reason.
"""
from __future__ import annotations

import json
import re
import sys
import time
from collections import Counter
from pathlib import Path

from . import clangast as C
from . import engine as E
from . import lift as LF
from . import units as UN

OUTSIDE = re.compile(r"\b(FArchive|FString|FName|FText|TArray|TArrayView|FStructuredArchive\w*|FMemoryImage\w*|"
                     r"FMemoryUnfreezeContent|FTypeLayoutDesc|FPlatformTypeLayoutParameters|FOutputDevice|TCHAR|"
                     r"FSHA1|FCbWriter|FCbFieldView|UObject|FProperty|FArchiveState|TStringBuilder\w*|FStringView|"
                     r"FAnsiStringView|FUtf8StringView|TFunctionRef|TFunction|FSlot|FPointerTableBase|"
                     r"FMemoryToStringContext|FSHAHash|FCompactBinary\w*|FColorList|FLinearColorList|FDateTime|"
                     r"FTimespan|FFrameNumber|FFrameTime|TOptional|FAutomationTestBase|FExpressionTokenConsumer|"
                     r"TTokenDefinitions|FTokenStream|FExpressionNode|FExpressionResult|FExpressionError|"
                     r"TValueOrError|FLogCategory\w*|TStaticBasicLogRecord|FStringFormatArg|TBasicArray)\b")
NOT_MATH_BODY = re.compile(r"FDateTime|FFrameNumber|FFrameTime|FTimespan|TStaticBasicLogRecord|FAutomationTestBase|"
                           r"TTokenDefinitions|FTokenStream|FExpression\w*|FLogCategory|FStringFormat")
CONTAINER = re.compile(r"\bT(Array|Map|Set|ArrayView|SparseArray|BitArray)\b")
# effects: a void call with no body and nothing it could write is an effect at the boundary (logging), not math
EFFECT_NAMES = re.compile(r"ReportError|Log|Printf|Assert|Ensure|Check|Debug|Warn|Trace", re.I)


def _kind(fn: C.Function) -> str:
    k = fn.node.k
    nm = fn.name
    if k == "CXXConstructorDecl":
        return "constructor"
    if k == "CXXConversionDecl":
        return "conversion"
    if nm.startswith("operator"):
        return "operator"
    if k == "CXXMethodDecl":
        return "static" if fn.node.a.get("storageClass") == "static" else "method"
    return "function"


def _outside(fn: C.Function, unit: C.Unit) -> str | None:
    """The non-mathematical type in a function's signature (or record), if any."""
    for t in [fn.type, unit.record_name.get(fn.record) or ""]:
        m = OUTSIDE.search(t or "")
        if m:
            return m.group(1)
    return None


def subjects(unit: C.Unit, eng: E.Engine, only_file: str | None = None):
    for fn in unit.functions:
        if fn.pattern or fn.node.a.get("isImplicit") or not C.has_body(fn.node):
            continue
        f = fn.file or ""
        if not eng.is_math_file(f):
            continue
        if only_file is not None and eng.rel(f) != only_file and not eng.rel(f).startswith(
                "Engine/Source/Runtime/Core/Public/"):
            continue
        yield fn


def spell(L: LF.Layouts, t: str, dt: str | None) -> str:
    """A parameter's type as C++ outside its namespace: the record's qualified name, or the builtin."""
    base = LF._strip(re.sub(r"&&?$|\*$", "", (dt or t or "").strip()))
    q = L.record_qual(base)
    return q or base


def params_of(fn: C.Function, L: LF.Layouts) -> list[dict]:
    out = []
    for i, p in enumerate(c for c in fn.node.c if c.k == "ParmVarDecl"):
        t, dt = p.a.get("t") or "", p.a.get("dt")
        L.push(fn.scope if fn.record else None)
        try:
            cpp = spell(L, t, dt)
        except LF.Gap:
            cpp = None
        finally:
            L.pop()
        out.append({"name": p.a.get("name") or f"arg{i}", "type": t, "dt": dt, "cpp": cpp,
                    "default": bool(p.a.get("init"))})
    return out


def _record(fn: C.Function, unit: C.Unit, eng: E.Engine, L: LF.Layouts | None = None) -> dict:
    rq = unit.record_name.get(fn.record) if fn.record else None
    n = fn.node
    params = params_of(fn, L or LF.Layouts(unit))
    targs = [c.a.get("t") or str(c.a.get("value")) for c in n.c if c.k == "TemplateArgument"]
    tail = (fn.type or "").rsplit(")", 1)[-1]
    return {"key": fn.mangled, "qual": fn.qual, "name": fn.name, "record": rq, "file": eng.rel(fn.file or ""),
            "line": fn.line, "unit": unit.name, "type": fn.type, "kind": _kind(fn), "params": params,
            "targs": targs, "const": "const" in tail, "static": n.a.get("storageClass") == "static",
            "scope": fn.scope}


def _statics_of(unit: C.Unit, eng: E.Engine, known: dict) -> int:
    """Constants a unit defines (static members and namespace constants in the math files), evaluated."""
    n = 0
    lf = LF.Lifter(unit, known)
    for q, decl in unit.statics.items():
        if q in known or not eng.is_math_file(decl.a.get("file") or ""):
            continue
        try:
            v = lf.static_value(decl)
        except (LF.Gap, RecursionError, KeyError, IndexError, TypeError, ValueError):
            continue
        if all(LF.const(t) for t in v.slots):
            known[q] = (v.slots, v.shape.kinds, v.shape.names)
            if decl.a.get("mangledName"):                    # the identity every unit agrees on
                known[decl.a["mangledName"]] = known[q]
            n += 1
    return n


def lift_unit(unit: C.Unit, eng: E.Engine, known: dict, seen: dict, only_file: str | None, log) -> Counter:
    stats = Counter()
    L = LF.Layouts(unit)
    for fn in subjects(unit, eng, only_file):
        if fn.mangled in seen and seen[fn.mangled].get("status") == "lifted":
            continue
        rec = _record(fn, unit, eng, L)
        out = _outside(fn, unit)
        if out:
            rec.update(status="outside", cause="not mathematics", detail=out)
        else:
            lf = LF.Lifter(unit, known)
            try:
                r = lf.lift(fn)
                rec.update(status="lifted", inputs=r.inputs,
                           outputs=[{"name": n, "kind": k, "term": t} for n, k, t in r.outputs],
                           calls=dict(r.calls), atoms=dict(r.atoms), effects=list(r.notes), xcalls=r.xcalls)
            except LF.Gap as g:
                rec.update(status="gap", cause=g.cause, detail=g.detail[:240])
            except RecursionError:
                rec.update(status="gap", cause="budget", detail="nesting deeper than the lifter's recursion limit")
        prev = seen.get(fn.mangled)
        if prev is None or prev.get("status") != "lifted":
            seen[fn.mangled] = rec
        stats[rec["status"]] += 1
    return stats


def run(eng: E.Engine, cache: Path, log=print) -> dict:
    """Build the units, lift everything, save ``scan.jsonl``; returns the scan."""
    sys.setrecursionlimit(max(sys.getrecursionlimit(), 100000))
    clang, why = E.clang()
    if clang is None:
        raise E.NotFound(why)
    t0 = time.perf_counter()
    head = UN.header_unit(eng, cache, clang, log)
    srcs = UN.source_units(eng, cache, clang, log)
    d = cache / "units"
    keep = lambda f: bool(f) and (eng.is_math_file(f) or eng.is_support_file(eng.rel(f)))  # noqa: E731
    known: dict = {}
    for s in srcs:
        if not s["dump"]:
            continue
        u = C.load(Path(s["dump"]), Path(s["source"]).name, keep, d, UN.KEEP_SOURCES, drop_json=True)
        n = _statics_of(u, eng, known)
        log(f"  constants from {Path(s['source']).name}: {n}")
        del u
    seen: dict[str, dict] = {}
    u = C.load(Path(head["dump"]), "headers", lambda f: bool(f) and (keep(f) or f.endswith("/headers.cpp")), d,
               UN.KEEP_HEADERS, drop_json=True)
    _statics_of(u, eng, known)
    st = lift_unit(u, eng, known, seen, None, log)
    log(f"  header unit: {dict(st)}")
    del u
    for s in srcs:
        if not s["dump"]:
            continue
        u = C.load(Path(s["dump"]), Path(s["source"]).name, keep, d, UN.KEEP_SOURCES, drop_json=True)
        st = lift_unit(u, eng, known, seen, s["source"], log)
        log(f"  {Path(s['source']).name}: {dict(st)}")
        del u
    res = resolve(seen)
    log(f"  calls across units: {res}")
    reclassify(list(seen.values()))
    fns = sorted(seen.values(), key=lambda r: (r["file"], r["line"] or 0, r["qual"], r["key"]))
    scan = {"engine": {"version": eng.tag, "changelist": eng.changelist, "branch": eng.version.get("BranchName")},
            "units": {"headers": {k: head[k] for k in ("classes", "stubs", "rejected")},
                      "sources": [{"source": s["source"], "dumped": bool(s["dump"]), "errors": s["errors"]}
                                  for s in srcs]},
            "constants": len(known), "functions": fns,
            "counts": dict(Counter(r["status"] for r in fns)), "seconds": round(time.perf_counter() - t0, 1)}
    save(cache, scan)
    return scan


def save(cache: Path, scan: dict) -> None:
    """The scan as ``scan.jsonl``: its header (everything but the functions), then one function per line."""
    p = cache / "scan.jsonl"
    tmp = p.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps({k: v for k, v in scan.items() if k != "functions"}, separators=(",", ":")) + "\n")
        for f in scan["functions"]:
            fh.write(json.dumps(f, separators=(",", ":")) + "\n")
    tmp.replace(p)
    (cache / "scan.json").unlink(missing_ok=True)             # the earlier format, one JSON object


def functions(cache: Path):
    """The scan's functions one at a time (None when there is no scan)."""
    p = cache / "scan.jsonl"
    if p.is_file():
        with p.open(encoding="utf-8") as fh:
            next(fh, None)
            for line in fh:
                if line.strip():
                    yield json.loads(line)
    elif (cache / "scan.json").is_file():
        yield from json.loads((cache / "scan.json").read_text(encoding="utf-8"))["functions"]


def _substitute(t, env, memo=None):
    """Variables replaced by terms; a shared subterm is rewritten once (memo by identity)."""
    memo = {} if memo is None else memo
    if isinstance(t, list) and t and t[0] == "var":
        return env.get(t[1], t)
    if isinstance(t, list) and t and isinstance(t[0], str) and t[0] not in ("int", "float", "bool"):
        hit = memo.get(id(t))
        if hit is not None and hit[0] is t:
            return hit[1]
        out = LF.fold([t[0], *[_substitute(a, env, memo) for a in t[1:]]])
        memo[id(t)] = (t, out)
        return out
    return t


def resolve(seen: dict) -> dict:
    """Replace every XCALL by the callee's lifted term (its inputs bound to the call's arguments); a caller of a
    gap becomes a gap that names it. Repeats until nothing changes (calls through several units)."""
    stats = Counter()
    by_key = seen

    def expand(t, stack, memo):
        if isinstance(t, list) and id(t) in memo and memo[id(t)][0] is t:
            return memo[id(t)][1]
        out = _expand(t, stack, memo)
        if isinstance(t, list):
            memo[id(t)] = (t, out)
        return out

    def _expand(t, stack, memo):
        if isinstance(t, list) and t and t[0] == "XCALL":
            key, j, args = t[1], t[2], [expand(a, stack, memo) for a in t[3:]]
            callee = by_key.get(key)
            if callee is None:
                raise LF.Gap("no body", f"{key} (defined in no unit read)")
            if callee.get("status") != "lifted":
                raise LF.Gap("calls a gap", f"{callee['qual']}: {callee.get('cause')}")
            if key in stack:
                raise LF.Gap("recursion", callee["qual"])
            rets = [o for o in callee["outputs"] if o["name"] == "return" or o["name"].startswith("return.")]
            if j >= len(rets) or len(args) != len(callee["inputs"]):
                raise LF.Gap("call", f"{callee['qual']}: the call and the lift disagree on its shape")
            env = {nm: a for (nm, _k), a in zip(callee["inputs"], args)}
            body = expand(rets[j]["term"], stack | {key}, {})
            out = _substitute(body, env)
            if LF.size(out) > LF.MAX_NODES:
                raise LF.Gap("term too large", f"inlining {callee['qual']}")
            return out
        if isinstance(t, list) and t and isinstance(t[0], str) and t[0] not in ("var", "int", "float", "bool"):
            return LF.fold([t[0], *[expand(a, stack, memo) for a in t[1:]]])
        return t

    pending = [r for r in seen.values() if r.get("status") == "lifted" and r.get("xcalls")]
    for r in pending:
        try:
            memo: dict = {}
            for o in r["outputs"]:
                o["term"] = expand(o["term"], {r["key"]}, memo)
                if LF.size(o["term"]) > LF.MAX_NODES:
                    raise LF.Gap("term too large", f"{o['name']} after the calls across units are inlined")
            stats["resolved"] += 1
        except LF.Gap as g:
            r.update(status="gap", cause=g.cause, detail=g.detail[:240])
            r.pop("outputs", None)
            stats["gap"] += 1
    return dict(stats)


def lift_source(path: Path, flags: list[str], workdir: Path, keep=None) -> list[dict]:
    """Every function a C++ file defines (any C++, not only the engine's), lifted: the same frontend and lifter,
    for tests and smoke checks that must not need an engine install."""
    sys.setrecursionlimit(max(sys.getrecursionlimit(), 100000))
    clang, why = E.clang()
    if clang is None:
        raise E.NotFound(why)
    workdir.mkdir(parents=True, exist_ok=True)
    dump = workdir / f"{path.stem}.ast.json"
    r = C.dump(clang, flags, path, dump)
    if not r["ok"]:
        raise E.NotFound(f"{path.name} does not compile: {r['errors'][:2]}")
    own = keep or (lambda f: bool(f) and Path(f).resolve().parent == path.resolve().parent)
    unit = C.Unit(path.name, C.read(dump, own))
    L = LF.Layouts(unit)
    seen: dict = {}
    for fn in unit.functions:
        if fn.pattern or fn.node.a.get("isImplicit") or not C.has_body(fn.node) or not own(fn.file or ""):
            continue
        rec = {"key": fn.mangled, "qual": fn.qual, "name": fn.name,
               "record": unit.record_name.get(fn.record) if fn.record else None, "file": Path(fn.file or "").name,
               "line": fn.line, "unit": unit.name, "type": fn.type, "kind": _kind(fn),
               "params": params_of(fn, L),
               "targs": [c.a.get("t") or str(c.a.get("value")) for c in fn.node.c if c.k == "TemplateArgument"],
               "static": fn.node.a.get("storageClass") == "static", "scope": fn.scope}
        try:
            out = LF.Lifter(unit, {}).lift(fn)
            rec.update(status="lifted", inputs=out.inputs, xcalls=out.xcalls, calls=dict(out.calls),
                       outputs=[{"name": n, "kind": k, "term": t} for n, k, t in out.outputs], atoms=dict(out.atoms))
        except LF.Gap as g:
            rec.update(status="gap", cause=g.cause, detail=g.detail)
        seen[fn.mangled] = rec
    resolve(seen)
    return list(seen.values())


def reclassify(fns: list[dict]) -> None:
    """A type met only in a function's body says what the function is about: time, logging, tests and text are
    outside the math universe; a container (TArray, ...) is a gap of its own (lists in the IR)."""
    for f in fns:
        if f.get("status") != "gap" or f.get("cause") not in ("unknown type", "reference type"):
            continue
        d = f.get("detail") or ""
        if NOT_MATH_BODY.search(d):
            f.update(status="outside", cause="not mathematics", detail=d)
        elif CONTAINER.search(d):
            f.update(cause="container")
        elif "(lambda at" in d:
            f.update(cause="lambda")


def load(cache: Path) -> dict | None:
    p = cache / "scan.jsonl"
    if p.is_file():
        with p.open(encoding="utf-8") as fh:
            sc = json.loads(next(fh))
        sc["functions"] = list(functions(cache))
    elif (cache / "scan.json").is_file():
        sc = json.loads((cache / "scan.json").read_text(encoding="utf-8"))
    else:
        return None
    reclassify(sc["functions"])
    sc["counts"] = dict(Counter(f["status"] for f in sc["functions"]))
    return sc


__all__ = ["functions", "load", "run", "save", "subjects"]
