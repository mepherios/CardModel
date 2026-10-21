"""witness — AnyPS5's own code, compiled next to the card model's derived semantics, on the same inputs.

An ``anyps5_semantics`` card names a card-language program (the semantics, derived from a public standard),
the AnyPS5 sources to compile (included whole, or declarations extracted by pattern when the rest of the file
needs libraries this host lacks), C++ adapters in files next to the card (``before_file`` goes ahead of the
extracted text, ``prelude_file`` after the sources), and checks:

  {"export": card name or null (an internal helper), "call": C++ expression over {0}, {1}, ...,
   "fn": program function, "args": [[lo, hi], ...], "edges": [[...], ...], "where": program predicate,
   "expect": "agree" | "differs" | "throws", "compare": "value" | "truth"}

Inputs: the edges, every corner and small value of each range, values with random bit widths and uniform
values (seeded), kept where the semantics is defined (the function's ``requires`` and the optional ``where``).
The harness prints one line per call (``i:<value>`` or ``x:throw``); the reference is the IR interpreter.
``agree`` must match everywhere; ``differs`` records a documented deviation and must still differ somewhere
(otherwise the debt entry it documents is stale); ``throws`` must throw everywhere. A ``size_law`` check
needs no compiler: every implemented GetSize / emitter pair in the cards must satisfy the program function.

Each run becomes an ``anyps5_witness`` card: seed, snapshot hash, source hash, toolchain, per-check counts and
counterexamples, and per-export agreement (what ``classify`` reads as witness_agrees).

Honest limits (L1): the harness runs AnyPS5's code on this host's compiler and C++ library (the console runs
its own build); unresolved symbols are left to dynamic lookup, so a check that reaches code outside the
included sources fails loudly rather than silently; sampling is evidence on the inputs drawn, not a proof.
"""
from __future__ import annotations

import hashlib
import random
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from ..engines import probes
from ..engines.ir import Interpreter
from ..kernel import paths, resources
from . import scan as S

COMPILE_TIMEOUT_S = 300
RUN_TIMEOUT_S = 120
HARNESS_HEAD = r"""#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <type_traits>
template <class T> static void out(T v) {
    if constexpr (std::is_floating_point_v<T>) std::printf("f:%a\n", static_cast<double>(v));
    else if constexpr (std::is_signed_v<T>) std::printf("i:%lld\n", static_cast<long long>(v));
    else std::printf("i:%llu\n", static_cast<unsigned long long>(v));
}
"""
FLOAT_SPECIAL = [0.0, -0.0, 0.5, -0.5, 1.0, -1.0, 1.5, -1.5, 2.5, -2.5, 3.5, -3.5, 0.49999999999999994,
                 -0.49999999999999994, 4503599627370496.0, 4503599627370497.0, 9007199254740992.0, 1e15 + 0.5,
                 -1e15 - 0.5, 1e300, -1e300, 2.2250738585072014e-308, 5e-324, 123456.75, -98765.25]


def _program(ctx, path: str):
    from ..lang.compile import compile_file
    mod = compile_file(paths.home() / path, ctx.ops, ctx.store)
    return mod, Interpreter(mod.ir_module(), ctx.ops, step_limit=2_000_000)


def _holds(interp, fn: dict, args: list) -> bool:
    interp.steps = 0
    env = {p["name"]: a for p, a in zip(fn["params"], args)}
    try:
        return all(bool(interp._expr(r, env, 0)) for r in fn.get("requires") or [])
    except Exception:  # noqa: BLE001 -- an input the definition cannot even test is outside its domain
        return False


def _f32(x: float) -> float:
    import struct
    try:
        return struct.unpack("f", struct.pack("f", x))[0]
    except OverflowError:
        return 0.0


def _draw_float(lo: float, hi: float, rng: random.Random) -> float:
    r = rng.random()
    if r < 0.2:
        return rng.choice([v for v in FLOAT_SPECIAL if lo <= v <= hi] or [lo])
    if r < 0.45:
        return min(hi, max(lo, rng.randint(-10**6, 10**6) + rng.choice([0.0, 0.25, 0.5, 0.75, 0.125])))
    if r < 0.75:
        return min(hi, max(lo, rng.uniform(-1.0, 1.0) * 2.0 ** rng.randint(-40, 52)))
    return rng.uniform(lo, hi)


def inputs(check: dict, rng: random.Random, samples: int) -> list[tuple]:
    """Edges, corners, small values, random bit widths and uniform values over each argument's range; float
    arguments (``types``: f64, f32) get the values rounding separates (halves, ties, 2**52, subnormals)."""
    ranges = [tuple(r) for r in check.get("args") or []]
    types = check.get("types") or ["i64"] * len(ranges)
    out = [tuple(e) for e in check.get("edges") or []]
    if not ranges:
        return out or [()]
    if any(t.startswith("f") for t in types):
        for _ in range(samples):
            row = []
            for (lo, hi), t in zip(ranges, types):
                if t.startswith("f"):
                    v = _draw_float(float(lo), float(hi), rng)
                    row.append(_f32(v) if t == "f32" else v)
                else:
                    row.append(rng.randint(int(lo), int(hi)))
            out.append(tuple(row))
        return [tuple(_f32(v) if t == "f32" and isinstance(v, float) else v for v, t in zip(r, types)) for r in out]
    total = 1
    for lo, hi in ranges:
        total *= hi - lo + 1
    if total <= max(samples, check.get("exhaustive_max", 4096)):
        import itertools
        return out + list(itertools.product(*[range(lo, hi + 1) for lo, hi in ranges]))

    def special(lo, hi):
        vals = {lo, hi, lo + 1, hi - 1, 0, 1, -1, 2, -2}
        for k in range(0, 65):
            for v in (1 << k, (1 << k) - 1, -(1 << k), -(1 << k) + 1):
                vals.add(v)
        return sorted(v for v in vals if lo <= v <= hi)

    corners = [special(lo, hi) for lo, hi in ranges]
    for i in range(samples):
        row = []
        for (lo, hi), sp in zip(ranges, corners):
            r = rng.random()
            if r < 0.25:
                row.append(rng.choice(sp))
            elif r < 0.6 and hi - lo > 1 << 8:
                width = rng.randint(1, max(1, (hi - lo).bit_length()))
                v = lo + rng.getrandbits(width)
                row.append(min(hi, v))
            else:
                row.append(rng.randint(lo, hi))
        out.append(tuple(row))
    return out


def _literal(v) -> str:
    if isinstance(v, float):
        return v.hex()
    if v == -(1 << 63):
        return "(-9223372036854775807LL - 1)"
    if v < 0:
        return f"({v}LL)"
    if v >= 1 << 63:
        return f"{v}ULL"
    return f"{v}LL"


def _extract(root: Path, spec: dict) -> str:
    """Copy one declaration from an AnyPS5 file: from a pattern to the end of its line or of its braces."""
    f = root / spec["file"]
    text = f.read_text(encoding="utf-8", errors="ignore")
    m = re.search(spec["start"], text, re.M)
    if m is None:
        raise ValueError(f"{spec['file']}: no match for {spec['start']!r} (the source changed: update the semantics card)")
    if spec.get("until", "braces") == "line":
        end = text.find("\n", m.start())
        return text[m.start():end if end >= 0 else len(text)] + "\n"
    masked = S.mask(text)                       # unspliced, so offsets are the original file's
    open_at = masked.find("{", m.start())
    close = S.body_end(masked, open_at)
    tail = close + 1
    if spec.get("until") == "braces;" and masked[tail:tail + 1] == ";":
        tail += 1
    return text[m.start():tail] + "\n"


def harness_source(ctx, sem, root: Path, plan: list[dict]) -> tuple[str, str]:
    """The C++ program, and a hash of the AnyPS5 text it compiles."""
    h = sem.get("harness") or {}
    digest = hashlib.sha256()
    parts = [HARNESS_HEAD]
    for inc in h.get("system_includes") or []:
        parts.append(f"#include <{inc}>")
    for inc in h.get("include") or []:
        f = root / inc
        digest.update(f.read_bytes())
        parts.append(f'#include "{f}"')
    if h.get("before_file") and sem.path is not None:
        parts.append((sem.path / h["before_file"]).read_text(encoding="utf-8"))
    for spec in h.get("extract") or []:
        text = _extract(root, spec)
        digest.update(text.encode())
        parts.append(text)
    if h.get("prelude"):
        parts.append(h["prelude"])
    if h.get("prelude_file") and sem.path is not None:
        parts.append((sem.path / h["prelude_file"]).read_text(encoding="utf-8"))
    parts.append("int main() {")
    for i, p in enumerate(plan):
        rows = p["inputs"]
        arity = max((len(r) for r in rows), default=0)
        if not rows:
            continue
        if arity == 0:
            call = p["call"]
            parts.append(f"  for (int n_{i} = 0; n_{i} < {len(rows)}; ++n_{i}) {{ try {{ out({call}); }} "
                         f"catch (...) {{ std::printf(\"x:throw\\n\"); }} }}")
            continue
        names = []
        for k in range(arity):                  # one typed array per argument
            col = [r[k] for r in rows]
            ctype = "double" if any(isinstance(v, float) for v in col) else \
                ("unsigned long long" if any(v >= 1 << 63 for v in col) else "long long")
            parts.append(f"  static const {ctype} a{i}_{k}[] = {{{','.join(_literal(v) for v in col)}}};")
            names.append(f"a{i}_{k}[n]")
        call = p["call"].format(*names)
        parts.append(f"  for (std::size_t n = 0; n < {len(rows)}; ++n) {{ try {{ out({call}); }} "
                     f"catch (...) {{ std::printf(\"x:throw\\n\"); }} }}")
    parts.append("  return 0;\n}\n")
    return "\n".join(parts), digest.hexdigest()


def _compiler(ctx, lang: str):
    card = ctx.store.get(f"language/{lang}")
    if card is None:
        return None, f"no language card {lang}"
    ok, exe = probes.probe(card.get("probe"))
    return (exe, None) if ok else (None, exe)


def _compare(expect: str, how: str, ref, got) -> bool:
    if got == "throw" or ref is None:
        return False
    if how == "truth":
        return bool(ref) == bool(int(got))
    if isinstance(got, float) or isinstance(ref, float):
        return float(ref) == float(got)          # value equality: the IR's floats do not carry the sign of zero
    return int(ref) == int(got)


def run_semantics(ctx, sem, root: Path, seed: int, samples: int = 300) -> dict:
    """Run one semantics card's checks; returns the witness card (not yet saved)."""
    root = Path(root).expanduser().resolve()
    rng = random.Random(f"{seed}:{sem.name}")
    mod, interp = _program(ctx, sem["program"])
    plan, statics = [], []
    for check in sem.get("checks") or []:
        if check.get("kind") == "size_law":
            statics.append(check)
            continue
        fn = mod.functions.get(check["fn"]) if check.get("fn") else None
        if check.get("fn") and fn is None:
            raise ValueError(f"{sem['program']} has no function {check['fn']}")
        where = mod.functions.get(check["where"]) if check.get("where") else None
        rows, refs = [], []
        for args in inputs(check, rng, check.get("samples", samples)):
            resources.guard("anyps5 witness")
            if check.get("expect") == "throws":
                rows.append(args)
                refs.append(None)
                continue
            if fn is not None and not _holds(interp, fn, list(args)):
                continue
            if where is not None:
                try:
                    if not interp.call(check["where"], list(args)):
                        continue
                except Exception:  # noqa: BLE001
                    continue
            try:
                refs.append(interp.call(check["fn"], list(args)))
            except Exception:  # noqa: BLE001 -- the definition is undefined here: not a comparable input
                continue
            rows.append(args)
        plan.append({**check, "inputs": rows, "refs": refs})
    results = []
    toolchain = None
    if plan:
        lang = (sem.get("harness") or {}).get("language", "cpp")
        exe, why = _compiler(ctx, lang)
        if exe is None:
            return _card(sem, seed, "skipped", [], {}, None, None, reason=f"no {lang} compiler: {why}")
        source, src_hash = harness_source(ctx, sem, root, plan)
        d = ctx.state_root / "build" / "anyps5" / hashlib.sha256((source + src_hash).encode()).hexdigest()[:20]
        d.mkdir(parents=True, exist_ok=True)
        (d / "harness.cpp").write_text(source, encoding="utf-8")
        h = sem.get("harness") or {}
        flags = list(h.get("flags") or ["-std=c++20", "-O1", "-w"])
        flags += [f"-I{root / inc}" for inc in h.get("include_dirs") or ["core/libs"]]
        flags += list((h.get("link") or {}).get(sys.platform, []))
        flags += list((h.get("platform_flags") or {}).get(sys.platform, []))
        cmd = [exe, *flags, "-o", str(d / "harness"), str(d / "harness.cpp")]
        try:
            vp = resources.run([exe, "--version"], timeout=30, heavy=False, stdin=subprocess.DEVNULL)
            toolchain = (vp.stdout or "").splitlines()[0] if vp.stdout else exe
            if not (d / "harness").exists():
                p = resources.run(cmd, timeout=COMPILE_TIMEOUT_S, cwd=d, stdin=subprocess.DEVNULL)
                if p.returncode != 0:
                    return _card(sem, seed, "error", [], {}, toolchain, src_hash,
                                 reason="compile failed: " + (p.stderr or p.stdout)[-1500:])
            p = resources.run([str(d / "harness")], timeout=RUN_TIMEOUT_S, cwd=d, stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired as exc:
            return _card(sem, seed, "error", [], {}, toolchain, src_hash, reason=f"timed out: {exc}")
        lines = [ln for ln in (p.stdout or "").splitlines() if ln[:2] in ("i:", "x:", "f:")]
        expected = sum(len(x["inputs"]) for x in plan)
        if p.returncode != 0 or len(lines) != expected:
            return _card(sem, seed, "error", [], {}, toolchain, src_hash,
                         reason=f"harness exit {p.returncode}, {len(lines)} of {expected} results: "
                                + (p.stderr or "")[-800:])
        k = 0
        for check in plan:
            got = lines[k:k + len(check["inputs"])]
            k += len(check["inputs"])
            results.append(_settle(check, got))
    else:
        src_hash = None
    for check in statics:
        results.append(_size_law(ctx, interp, check))
    exports: dict = {}
    compared: dict = {}                     # inputs compared against the semantics (agree checks only)
    for r in results:
        if not r.get("export"):
            continue
        e = exports.setdefault(r["export"], {"checks": 0, "agree": True, "disagree": 0})
        e["checks"] += r["inputs"]
        if r["expect"] == "agree":
            e["disagree"] += r["disagree"]
            e["agree"] = e["agree"] and r["disagree"] == 0
            compared[r["export"]] = compared.get(r["export"], 0) + r["inputs"]
        if not r["ok"]:
            e["agree"] = False
    for item in (r.get("witnessed_exports") for r in results):
        for e, ok in (item or {}).items():
            x = exports.setdefault(e, {"checks": 0, "agree": True, "disagree": 0})
            x["checks"] += 1
            x["agree"] = x["agree"] and ok
            x["disagree"] += 0 if ok else 1
            compared[e] = compared.get(e, 0) + 1
    for e, x in exports.items():            # a throws or differs check alone witnesses no semantics
        x["agree"] = x["agree"] and compared.get(e, 0) > 0
    status = "agree" if all(r["ok"] for r in results) and results else ("vacuous" if not results else "disagree")
    return _card(sem, seed, status, results, exports, toolchain, src_hash)


def _settle(check: dict, got: list[str]) -> dict:
    expect = check.get("expect", "agree")
    how = check.get("compare", "value")
    agree = disagree = threw = 0
    examples = []
    for args, ref, line in zip(check["inputs"], check["refs"], got):
        value = "throw" if line.startswith("x:") else (float.fromhex(line[2:]) if line.startswith("f:") else line[2:])
        if value == "throw":
            threw += 1
        if expect == "throws":
            ok = value == "throw"
        else:
            ok = _compare(expect, how, ref, value)
        if ok:
            agree += 1
        else:
            disagree += 1
            if len(examples) < 5:
                examples.append({"args": list(args), "model": ref, "anyps5": value})
    n = len(check["inputs"])
    if expect == "agree":
        ok = n > 0 and disagree == 0
    elif expect == "throws":
        ok = n > 0 and disagree == 0
    else:                                   # a documented deviation must still be one
        ok = n > 0 and disagree > 0
    return {"export": check.get("export"), "call": check["call"], "fn": check.get("fn"), "expect": expect,
            "inputs": n, "agree": agree, "disagree": disagree, "threw": threw, "ok": ok,
            "examples": examples, **({"note": check["note"]} if check.get("note") else {})}


def _size_law(ctx, interp, check: dict) -> dict:
    """Every implemented GetSize export returning a constant, whose emitter writes one fixed packet."""
    from .cards import symbol_of
    exports = {c.name: c for c in ctx.store.cards("anyps5_export") if c.get("kind") == "function"}
    by_symbol = {(c["library"], symbol_of(c)): c for c in exports.values()}
    agree = disagree = 0
    examples, witnessed = [], {}
    for c in exports.values():
        sym = symbol_of(c)
        if not sym.endswith("GetSize") or c["state"] != "implemented" or c.get("constant") is None:
            continue
        base = by_symbol.get((c["library"], sym[:-len("GetSize")]))
        if base is None or base["state"] != "implemented" or not base.get("packet"):
            continue
        want = interp.call(check["fn"], [int(base["packet"]["payload"])])
        ok = want == c["constant"]
        witnessed[c.name] = ok
        if ok:
            agree += 1
        else:
            disagree += 1
            examples.append({"export": c.name, "model": want, "anyps5": c["constant"], "emitter": base.name})
    return {"export": None, "call": "GetSize constant vs the emitter's packet", "fn": check["fn"],
            "expect": "agree", "inputs": agree + disagree, "agree": agree, "disagree": disagree, "threw": 0,
            "ok": disagree == 0 and agree > 0, "examples": examples[:5], "witnessed_exports": witnessed}


def _card(sem, seed, status, results, exports, toolchain, src_hash, reason=None) -> dict:
    return {"name": sem.name, "semantics": sem.name, "program": sem["program"], "status": status, "seed": seed,
            "ran_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "toolchain": toolchain,
            "source_sha256": src_hash, "checks": results, "exports": exports,
            **({"reason": reason} if reason else {}),
            "provenance": {"origin": "cardmodel", "tool": "cardmodel anyps5 witness"}}


def run(ctx, root, names: list[str] | None = None, seed: int | None = None, samples: int = 300,
        save: bool = True, layer: str | None = None) -> list[dict]:
    from ..engines import values as V
    seed = V.fresh_seed() if seed is None else seed
    snap = ctx.store.get("anyps5_snapshot/current")
    out = []
    for sem in sorted(ctx.store.cards("anyps5_semantics"), key=lambda c: c.name):
        if names and sem.name not in names:
            continue
        card = run_semantics(ctx, sem, root, seed, samples)
        card["snapshot"] = snap.get("sha256") if snap else None
        out.append(card)
        if save:
            ctx.store.save({**card, "category": "anyps5_witness"}, layer=layer)
    return out


__all__ = ["harness_source", "inputs", "run", "run_semantics"]
