"""frontends — any language in: choose a language's frontend, lift its functions, and witness each lift.

A language card names its frontend (``"frontend": "<module>"``): ``frontend_python`` for Python, ``cardmodel.lang``
for the card language, ``frontend_text`` for the fifteen languages it parses. :func:`lift` dispatches on that, so
``translate``, ``emit`` and ``learn`` read any of them the same way, and :func:`frontend_languages` is the list of
languages the model can read.

A lift is a claim ("this IR means what the source means"), so it is witnessed (L1, CM17): :func:`witness_source`
runs the ORIGINAL source through its own toolchain on seeded inputs, inside a harness built from the language
card, and compares every output with the IR interpreter. A language with no toolchain on this host reports
``unavailable``; it never passes silently.

Honest limits (L1): the witness is sampled (seeded); fixed-width sources are compared only on inputs whose IR
values fit the card's ``int_bits``; the harness renames a ``main`` the source defines (it supplies its own).
"""
from __future__ import annotations

import importlib
import random
import re
from pathlib import Path

from . import values as V
from .codegen import EmitGap, Emitter, resolve_language
from .context import Ctx
from .ir import Interpreter, StepLimit
from .runners import run_program

TEXT = "cardmodel.engines.frontend_text"
STEP_BUDGET = 200_000


def frontend_languages(store) -> list[str]:
    """Every language card that names a frontend (the languages the model can read)."""
    return sorted(c.name for c in store.cards("language") if c.get("frontend"))


def language_for_path(store, path: str | Path) -> str | None:
    """The language whose card lists this file's extension and has a frontend."""
    suffix = Path(path).suffix
    if not suffix:
        return None
    for card in store.cards("language"):
        if card.get("frontend") and suffix in (card.get("extensions") or []):
            return card.name
    for card in store.cards("language"):          # case-insensitive second pass (.R / .r)
        if card.get("frontend") and suffix.lower() in [e.lower() for e in card.get("extensions") or []]:
            return card.name
    return None


def lift(ctx: Ctx, source: str, lang: str, only: list[str] | None = None,
         param_hints: dict | None = None) -> list:
    """Lifted functions of ``source`` written in ``lang`` (each with ok / ir / reasons, frontend_python's shape)."""
    card = ctx.store.get(f"language/{lang}")
    if card is None:
        raise KeyError(f"no language card {lang!r}")
    module = card.get("frontend")
    if not module:
        raise KeyError(f"language {lang!r} has no frontend (readable: {', '.join(frontend_languages(ctx.store))})")
    if module == "cardmodel.engines.frontend_python":
        from .frontend_python import lift_source
        return lift_source(source, ctx.ops, only=only, param_hints=param_hints)
    if module == "cardmodel.lang":
        return _lift_cardlang(ctx, source, only)
    mod = importlib.import_module(module)
    return mod.lift_source(source, ctx.ops, lang, only=only, param_hints=param_hints)


def _lift_cardlang(ctx: Ctx, source: str, only):
    from ..lang.compile import CompileError, compile_source
    from .frontend_text import Lifted
    try:
        m = compile_source(source, ctx.ops, ctx.store)
    except (CompileError, SyntaxError, ValueError) as exc:
        return [Lifted("<module>", False, None, source, [str(exc)], False, 0, "cardlang")]
    if m.globals or m.arrays:
        return [Lifted(n, False, None, "", ["module state (globals/arrays) is lifted by `cardmodel run`, not here"],
                       False, 0, "cardlang") for n in m.functions]
    return [Lifted(n, True, f, "", [], False, m.fn_lines.get(n, 0), "cardlang") for n, f in m.functions.items()
            if not only or n in only]


# -- running the original source -------------------------------------------------------------------------------------

def _rename_main(src: str, pattern: str, repl: str) -> str:
    return re.sub(pattern, repl, src, flags=re.M)


def source_program(ctx: Ctx, lang: str, source: str, module: dict, calls: list,
                   src_types: list | None = None) -> str:
    """A complete program: the original ``source`` plus a harness that prints the entry's result for each call
    (the ``i:``/``f:``/``b:`` protocol of runners.run_program)."""
    card = resolve_language(ctx.store, lang)
    fh = card.get("frontend_harness") or {}
    entry = next(f for f in module["functions"] if f["name"] == module["entry"])
    cg = card.get("codegen") or {}
    harness = dict(cg.get("harness") or {})
    harness.update({k: v for k, v in fh.items() if k in ("main", "print")})
    lits = dict(cg.get("lit") or {})
    lits.update(fh.get("lit") or {})
    if not harness.get("main") or not harness.get("print"):
        raise EmitGap(f"{lang}: no harness to run the original source (add frontend_harness to its card)")

    def lit(t, v):
        if t == "bool":
            return lits.get("true" if v else "false", "true" if v else "false")
        if t == "float":
            if v != v or v in (float("inf"), float("-inf")):
                raise EmitGap("non-finite float argument")
            return lits.get("float", "{v}").format(v=repr(float(v)))
        return lits.get("int", "{v}").format(v=int(v))

    text = source
    for pat, pre in fh.get("ensure") or []:
        if not re.search(pat, text, flags=re.M):
            text = pre + text
    for pat, repl in fh.get("replace") or []:
        text = re.sub(pat, repl, text, flags=re.M)
    prefix = ""
    if fh.get("qualify"):                       # Java: call Class.f(...) from the harness class
        m = re.search(fh["qualify"], text)
        if m is None:
            raise EmitGap(f"{lang}: no class around the function")
        prefix = m.group(1) + "."
    name = entry["name"]
    ind = cg.get("indent", "    ")
    lines = []
    cast = fh.get("arg_cast")
    types = list(src_types or [])

    def arg(i, p, a):
        text = lit(p["type"], a)
        if cast and i < len(types) and types[i]:
            text = cast.format(type=types[i], v=text)
        return text

    for args in calls:
        call = f"{prefix}{name}({', '.join(arg(i, p, a) for i, (p, a) in enumerate(zip(entry['params'], args)))})"
        lines.append(ind + harness["print"][entry["returns"]].format(e=call) + "\n")
    main = harness["main"].format(calls="".join(lines))
    prelude = fh.get("prelude")
    if prelude is None:
        prelude = (cg.get("prelude") or "").replace("@imports@", "")
    hoisted = ""
    if fh.get("hoist"):                         # Java: imports before the harness class
        keep = []
        for ln in text.splitlines():
            if re.match(fh["hoist"], ln):
                hoisted += ln + "\n"
            else:
                keep.append(ln)
        text = "\n".join(keep)
    if fh.get("order") == "main_first":
        return hoisted + prelude + main + "\n" + text + "\n"
    return hoisted + prelude + text + "\n" + main


def witness_source(ctx: Ctx, lang: str, source: str, module: dict, inputs: list,
                   src_types: list | None = None) -> dict:
    """Run the original source on ``inputs`` and compare with the IR interpreter (the lift's witness)."""
    entry = module["entry"]
    card = resolve_language(ctx.store, lang)
    interp = Interpreter(module, ctx.ops, step_limit=STEP_BUDGET)
    rows = []
    for args in inputs:
        try:
            out = interp.call(entry, list(args))
        except (StepLimit, RecursionError):
            continue
        except Exception:  # noqa: BLE001 -- outside the IR's domain (division by zero, ...)
            continue
        if V.finite(out):
            rows.append({"args": list(args), "out": out, "bits": interp.max_bits})
    bits = card.get("int_bits")
    usable = [r for r in rows if (bits is None or r["bits"] < bits - 1) and V.fits(r["out"], bits)
              and all(V.fits(a, bits) for a in r["args"])]
    res = {"lang": lang, "inputs": len(rows), "out_of_width": len(rows) - len(usable)}
    if not usable:
        return {**res, "status": "no_inputs"}
    try:
        src = source_program(ctx, lang, source, module, [r["args"] for r in usable], src_types)
    except EmitGap as exc:
        return {**res, "status": "no_harness", "reason": str(exc)}
    if not card.get("runner"):
        return {**res, "status": "unavailable", "reason": f"{lang} card has no runner"}
    run = run_program(card, src, ctx.state_root)
    if run.status == "unavailable":
        return {**res, "status": "unavailable", "reason": run.detail}
    if run.status != "ok" or len(run.values) != len(usable):
        return {**res, "status": "error", "run": run.status,
                "detail": (run.detail or run.stderr or f"{len(run.values)}/{len(usable)} values")[-800:]}
    bad = next(((r["args"], r["out"], g) for r, g in zip(usable, run.values) if not V.same(r["out"], g)), None)
    res.update(status="pass" if bad is None else "fail", checks=len(usable))
    if bad:
        res.update(args=bad[0], ir=bad[1], source=bad[2])
    return res


def sample_inputs(module: dict, n: int, seed: int) -> list:
    """Seeded arguments for the entry, the translate engine's generators (edges included)."""
    from .translate import _gen_for
    entry = next(f for f in module["functions"] if f["name"] == module["entry"])
    gens = [_gen_for(p["name"], p["type"], 1) for p in entry["params"]]
    return [list(a) for a in V.inputs(gens, n, random.Random(seed))]


# -- the source x target matrix (engines/matrix.py) ------------------------------------------------------------------

def register_matrix(matrix) -> None:
    """Give every text-frontend language a row (and every codegen language a round-trip column) in the matrix."""
    from .frontend_python import module_for
    from .frontend_text import DIALECTS, lift_source as text_lift

    def cards_for(lang):
        def cards(ctx: Ctx, path: Path, seed: int):
            from . import translate
            src = path.read_text(encoding="utf-8")
            lifted = lift(ctx, src, lang)
            out, gaps = [], {}
            for lf in lifted:
                if not lf.ok:
                    gaps[lf.name] = lf.reasons
                    continue
                card = translate.function_card(ctx, lf.name, lifted, path.name, seed=seed, lang=lang)
                card["verification"]["source_witness"] = witness_source(
                    ctx, lang, src, card["ir"], [v["args"] for v in card["vectors"]], lf.src_types)
                out.append(card)
            return out, gaps
        return cards

    def lift_text_for(lang):
        def lift_text(ctx: Ctx, text: str) -> dict:
            lifted = text_lift(text, ctx.ops, lang)
            return {lf.name: module_for(lf.name, lifted) for lf in lifted if lf.ok}
        return lift_text

    exts = {"c": (".c",), "cpp": (".cpp", ".cc", ".cxx"), "csharp": (".cs",), "go": (".go",), "java": (".java",),
            "javascript": (".js", ".mjs", ".cjs"), "julia": (".jl",), "kotlin": (".kt", ".kts"), "lua": (".lua",),
            "php": (".php",), "ruby": (".rb",), "rust": (".rs",), "swift": (".swift",), "typescript": (".ts", ".mts"),
            "zig": (".zig",)}
    for lang in DIALECTS:
        matrix.register(matrix.Frontend(lang, exts[lang], cards_for(lang), lift_text_for(lang)))
