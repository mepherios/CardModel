"""units — the translation units the engine's math is read from, built in the cache and dumped through clang.

  headers   one generated unit: every math header, an explicit instantiation of every class template of the
            engine's math (for double, or int32 where the parameter is an integer type), and a call of every function
            template of the math structs (FMath and the platform math it inherits) and of the math namespace, so that
            clang instantiates them; lines clang rejects are removed (each with clang's reason) until it compiles
  sources   the engine's own math .cpp files (Core/Private/Math, and the generic platform math), each a unit as the
            engine compiles it

``build`` writes, compiles and dumps them (cached by content: the unit's text, the flags and the engine version),
and returns, per unit, the dump to read. A unit is read one at a time (lift.py), so memory holds one AST.

Honest limits (L1): the instantiations are this module's choice (double for real-number templates, int32 for
integer ones); a template that does not compile for that choice is reported and left out, not guessed.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

from . import clangast as C
from . import engine as E

SKIP_HEADERS = {"UnrealMathSSE.h", "UnrealMathNeon.h", "UnrealPlatformMathSSE.h", "UnrealPlatformMathSSE4.h",
                "UnrealMathFPU.h", "UnrealMathVectorCommon.h.inl", "UnrealMathVectorConstants.h.inl"}
TEMPLATE_STRUCTS = ("FMath", "FGenericPlatformMath", "FClangPlatformMath", "FApplePlatformMath",
                    "FMacPlatformMath")
MAX_FIX_ROUNDS = 8
KEEP_HEADERS = "math+support+unit"      # what scan.py keeps of each unit (part of the pickle's identity)
KEEP_SOURCES = "math+support"


def _hash(*parts) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(str(p).encode())
        h.update(b"\0")
    return h.hexdigest()[:16]


def compiled_includes(eng: E.Engine, cache: Path) -> list[str]:
    """The include lines the header unit compiled with (the headers that do not compile on their own left out)."""
    import json
    for meta in sorted((cache / "units").glob("headers.*.meta.json")):
        m = json.loads(meta.read_text(encoding="utf-8"))
        if m.get("includes"):
            return m["includes"]
        left_out = {k.split(":", 1)[1] for k in m.get("rejected") or {} if k.startswith("header:")}
        return [i for i in header_includes(eng) if i not in left_out]
    return header_includes(eng)


def header_includes(eng: E.Engine) -> list[str]:
    inc = ['#include "CoreMinimal.h"']
    for p in eng.headers():
        if p.suffix == ".h" and p.name not in SKIP_HEADERS and "/Math/" in str(p):
            inc.append(f'#include "Math/{p.name}"')
    inc.append('#include "Math/VectorRegister.h"')
    return inc


def _write(path: Path, text: str) -> None:
    if not path.is_file() or path.read_text(encoding="utf-8") != text:
        path.write_text(text, encoding="utf-8")


def _templates(unit: C.Unit, eng: E.Engine) -> tuple[list[str], list[str]]:
    """(class template names to instantiate, function-template call stubs) found in a unit's math files."""
    classes, stubs = [], []
    for scope, node in unit.templates:
        if not eng.is_math_file(node.a.get("file") or ""):
            continue
        tparams = [c for c in node.c if c.k in ("TemplateTypeParmDecl", "NonTypeTemplateParmDecl",
                                                 "TemplateTemplateParmDecl")]
        if node.k == "ClassTemplateDecl":
            if len(tparams) == 1 and tparams[0].k == "TemplateTypeParmDecl" and scope.startswith("UE::Math"):
                nm = node.a.get("name")
                arg = "int32" if "Int" in (tparams[0].a.get("name") or "") or nm.startswith("TInt") else "double"
                classes.append(f"{scope}::{nm}<{arg}>")
            continue
        if any(c.k != "TemplateTypeParmDecl" for c in tparams) or not tparams:
            continue
        pattern = next((c for c in node.c if c.k in C.FUNCS), None)
        if pattern is None:
            continue
        owner = scope.split("::")[-1] if scope else ""
        if owner not in TEMPLATE_STRUCTS and not scope.startswith("UE::Math") and scope:
            continue
        if pattern.k != "FunctionDecl" and pattern.a.get("storageClass") != "static":
            continue                                       # member templates of class templates: skipped
        names = [c.a.get("name") or "" for c in tparams]
        decls, args = [], []
        ok = True
        for i, p in enumerate(c for c in pattern.c if c.k == "ParmVarDecl"):
            t = p.a.get("t") or ""
            for nm in names:
                if nm:
                    t = re.sub(rf"\b{re.escape(nm)}\b", "double", t)
            if re.search(r"\.\.\.|\bauto\b|TArray|FString|TFunction|TFunctionRef|TArrayView|TCHAR|decltype", t):
                ok = False
                break
            ptr = t.rstrip().endswith("*")
            base = re.sub(r"&&?$|\*$", "", t.strip()).strip()
            base = re.sub(r"^const\s+|\s+const$", "", base).strip()
            decls.append(f"{base} a{i}{{}};")
            args.append(f"&a{i}" if ptr else f"a{i}")
        if not ok:
            continue
        fname = node.a.get("name") or ""
        callee = f"{scope}::{fname}" if scope else fname
        stubs.append(f"{{ {' '.join(decls)} (void){callee}({', '.join(args)}); }}")
    return sorted(set(classes)), stubs


def _compose(includes: list[str], classes: list[str], stubs: list[str]) -> tuple[str, dict[int, str]]:
    """The unit's text, and which line holds which instantiation or stub (for removing what clang rejects)."""
    lines = list(includes) + ["", "// explicit instantiations of the engine's math class templates"]
    owner: dict[int, str] = {}
    for c in classes:
        lines.append(f"template struct {c};")
        owner[len(lines)] = f"class:{c}"
    lines += ["", "// calls that instantiate the function templates (never run)", "static void cm_instantiate() {"]
    for s in stubs:
        lines.append("    " + s)
        owner[len(lines)] = f"stub:{s}"
    lines += ["}", ""]
    return "\n".join(lines), owner


def header_unit(eng: E.Engine, cache: Path, clang: str, log=print) -> dict:
    """Write, fix and dump the generated header unit; returns {"dump", "tu", "rejected", "classes", "stubs"}."""
    flags = E.flags(eng, cache, "truth")
    d = cache / "units"
    d.mkdir(parents=True, exist_ok=True)
    includes = header_includes(eng)
    key = _hash(eng.tag, eng.changelist, flags, includes, "headers-v1")
    done = d / f"headers.{key}.json"
    meta_path = d / f"headers.{key}.meta.json"
    if meta_path.is_file() and C.ready(done, d, KEEP_HEADERS):
        import json
        return json.loads(meta_path.read_text(encoding="utf-8"))
    # pass 1: the includes alone, to find the templates (a header that does not compile on its own is left out)
    tu1 = d / "headers_pass1.cpp"
    rejected: dict[str, str] = {}
    for _round in range(MAX_FIX_ROUNDS):
        _write(tu1, "\n".join(includes) + "\n")
        errs = C.syntax(clang, flags, tu1)
        if not errs:
            break
        bad = {includes[line - 1]: msg for line, msg in errs if 1 <= line <= len(includes) and line > 1}
        if not bad:
            raise E.NotFound(f"the engine's math headers do not compile with these flags: {errs[:3]}")
        for inc, msg in bad.items():
            rejected[f"header:{inc}"] = msg[:200]
        includes = [i for i in includes if i not in bad]
        log(f"  pass 1: left out {len(bad)} headers that do not compile on their own")
    else:
        raise E.NotFound("the math headers still fail after removing the failing ones")
    dump1 = d / f"headers_pass1.{key}.ast.json"
    if not dump1.is_file():
        r = C.dump(clang, flags, tu1, dump1)
        if not r["ok"]:
            raise E.NotFound(f"pass 1 failed: {r['errors'][:3]}")
    log(f"  pass 1: {tu1.name} dumped")
    u1 = C.load(dump1, "headers_pass1", lambda f: bool(f) and eng.is_math_file(f), d)
    classes, stubs = _templates(u1, eng)
    del u1
    dump1.unlink(missing_ok=True)
    for old in d.glob("headers_pass1.*.pickle"):
        old.unlink(missing_ok=True)
    # pass 2: instantiate; drop what clang rejects
    tu = d / "headers.cpp"
    for _round in range(MAX_FIX_ROUNDS):
        text, owner = _compose(includes, classes, stubs)
        _write(tu, text)
        errs = C.syntax(clang, flags, tu)
        if not errs:
            break
        bad = {}
        for line, msg in errs:
            if line in owner:
                bad.setdefault(owner[line], msg)
        if not bad:
            raise E.NotFound(f"the generated unit fails outside its instantiations: {errs[:3]}")
        for what, msg in bad.items():
            rejected[what] = msg[:200]
            kind, _, val = what.partition(":")
            if kind == "class":
                classes = [c for c in classes if c != val]
            else:
                stubs = [s for s in stubs if s != val]
        log(f"  pass 2: clang rejected {len(bad)} instantiations; retrying")
    else:
        raise E.NotFound(f"the generated unit still fails after {MAX_FIX_ROUNDS} rounds")
    r = C.dump(clang, flags, tu, done)
    if not r["ok"]:
        raise E.NotFound(f"the header unit's dump failed: {r['errors'][:3]}")
    meta = {"dump": str(done), "tu": str(tu), "rejected": rejected, "classes": classes, "stubs": len(stubs),
            "seconds": r["seconds"], "includes": includes}
    import json
    meta_path.write_text(json.dumps(meta, indent=1), encoding="utf-8")
    for old in d.glob("headers.*"):
        if old.name.startswith(f"headers.{key}."):
            continue
        old.unlink(missing_ok=True)
    return meta


def source_units(eng: E.Engine, cache: Path, clang: str, log=print) -> list[dict]:
    """Dump each of the engine's math .cpp files as its own unit (cached by its content and the flags)."""
    flags = E.flags(eng, cache, "truth")
    d = cache / "units"
    d.mkdir(parents=True, exist_ok=True)
    out = []
    srcs = list(eng.sources())
    gpm = eng.runtime / "Core" / "Private" / "GenericPlatform" / "GenericPlatformMath.cpp"
    if gpm.is_file():
        srcs.append(gpm)
    for src in srcs:
        key = _hash(eng.tag, eng.changelist, flags, src.read_bytes())
        dump = d / f"{src.stem}.{key}.json"
        if not C.ready(dump, d, KEEP_SOURCES):
            for old in d.glob(f"{src.stem}.*"):
                old.unlink(missing_ok=True)
            r = C.dump(clang, flags, src, dump)
            if not r["ok"]:
                dump.unlink(missing_ok=True)
                out.append({"source": eng.rel(src), "dump": None, "errors": r["errors"][:5]})
                log(f"  {src.name}: does not compile with these flags ({r['errors'][:1]})")
                continue
            log(f"  {src.name}: dumped in {r['seconds']} s")
        out.append({"source": eng.rel(src), "dump": str(dump), "errors": []})
    return out


__all__ = ["header_includes", "header_unit", "source_units"]
