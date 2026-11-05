"""scale — the scale benchmark (SCALING.md §6, S-A): time and peak memory per function as a project grows.

``generate(root, n, seed)`` writes a seeded, deterministic synthetic Python package of ``n`` functions, like the
arena's generator but shaped for size rather than for optimization:

  leaf        arithmetic on its parameters
  loop        a ``for`` over a small range
  chain       calls an earlier function of its own module (call chains, depth at most ``MAX_DEPTH``)
  cross       calls a function of an earlier module through ``from ... import ... as ...``
  recursive   general self-recursion (a factorial modulo a prime)
  tail        tail self-recursion (Euclid's gcd)
  mutual      a pair of mutually recursive functions (even/odd)
  fail        a deliberate lift failure (a ``try`` block, which the IR does not have)
  fail_caller calls a ``fail`` function of its module: it lifts as partial, the edge an opaque-boundary gap
              (frontend_python.close_calls); ``lift_rate`` counts closed lifts only, ``lift_rate_with_boundaries``
              adds the partial ones

Modules hold ``MODULE_SIZE`` functions, packages ``PACKAGE_SIZE`` modules, so 10⁶ functions are 10⁴ modules in 100
packages. The same (n, seed) always writes the same bytes.

``measure(ctx, n, seed)`` generates one project into a temporary directory and times the stages that are cheap per
function, each over the whole project:

  lift         ``lift_project.lift_files`` (imports resolved across modules, the closure)
  structure    ``analyse.structure`` over every lifted function at once (signature, calls, recursion, SCCs, effects)
  obligations  ``analyse.obligations`` for every lifted function (the partial ops and their path conditions)
  reference    the IR interpreter runs every lifted function once on a small input

``bench`` runs each size in its own child process, so peak memory (``ru_maxrss``) is that size's own, and returns
time and peak memory per function per size. ``record`` writes one metric card per size (``metric/scale__n<N>``) and
the goal metrics read the newest run: ``scale_slope`` (time per function at the largest size ÷ at the smallest)
and ``scale_peak_memory_mb`` (peak memory at the largest size).

Measurement only: no engine's behaviour depends on this module.

Honest limits (L1): wall-clock time on a shared host is noisy, so one run is one sample; the synthetic functions
are small and int-only, so the per-function cost is a lower bound for real code; ``ru_maxrss`` includes the store
the child loads (reported separately as the baseline); summarize, verify across languages and optimize are not
timed here (each compiles per function and is the subject of its own phase).
"""
from __future__ import annotations

import json
import os
import random
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from .context import Ctx

SIZES = (1_000, 10_000, 100_000)
MODULE_SIZE = 100
PACKAGE_SIZE = 100
MAX_DEPTH = 8
PACKAGE = "scalebench"
CHILD_TIMEOUT_S = 4 * 3600                 # one size; 10⁶ takes tens of minutes
STAGES = ("lift", "structure", "obligations", "reference")

# kind -> weight; every kind but ``mutual`` (two functions) is one function
KINDS = {"leaf": 24, "loop": 14, "chain": 22, "cross": 10, "recursive": 6, "tail": 5, "mutual": 4, "fail": 8,
         "fail_caller": 7}
CALLABLE = ("leaf", "loop", "chain", "cross")          # callees: bounded cost on any input


def _module_path(index: int) -> tuple[str, str]:
    """(dotted module name, relative file path) of module ``index``."""
    pkg, mod = divmod(index, PACKAGE_SIZE)
    return f"{PACKAGE}.p{pkg:03d}.m{mod:03d}", f"{PACKAGE}/p{pkg:03d}/m{mod:03d}.py"


def _function(kind: str, name: str, rng: random.Random, callee: dict | None) -> list[str]:
    a, b, m = rng.randint(2, 9), rng.randint(1, 99), rng.choice((97, 101, 1009, 65537))
    if kind == "leaf":
        return [f"def {name}(x: int, y: int) -> int:", f"    return (x * {a} + y * {b}) % {m} + {b}"]
    if kind == "loop":
        return [f"def {name}(x: int, y: int) -> int:", "    t = y", f"    for i in range({rng.randint(3, 12)}):",
                f"        t = (t + i * x + {a}) % {m}", "    return t"]
    if kind in ("chain", "cross"):
        return [f"def {name}(x: int, y: int) -> int:", f"    return ({callee['as']}(x + {a}, y) + {b}) % {m}"]
    if kind == "recursive":
        return [f"def {name}(n: int) -> int:", "    if n <= 1:", "        return 1",
                f"    return n * {name}(n - 1) % 1000003"]
    if kind == "tail":
        return [f"def {name}(a: int, b: int) -> int:", "    if b == 0:", "        return a",
                f"    return {name}(b, a % b)"]
    if kind == "fail":
        return [f"def {name}(x: int, y: int) -> int:", "    try:", f"        return x // y + {a}",
                "    except ZeroDivisionError:", f"        return {b}"]
    if kind == "fail_caller":
        return [f"def {name}(x: int, y: int) -> int:", f"    return {callee['as']}(x, y + {a}) + {b}"]
    raise ValueError(kind)


def generate(root: Path, n: int, seed: int) -> dict:
    """Write the synthetic package under ``root``; returns the key: every function's kind and module."""
    rng = random.Random(seed)
    kinds, weights = list(KINDS), list(KINDS.values())
    key: dict[str, dict] = {}
    exported: list[dict] = []                 # callable functions of finished modules (for ``cross``)
    depth: dict[str, int] = {}                # qualified name -> call depth
    made, index = 0, 0
    root = Path(root)
    while made < n:
        mod, rel = _module_path(index)
        path = root / rel
        if not path.parent.exists():
            path.parent.mkdir(parents=True)
            for d in (path.parent, path.parent.parent):
                (d / "__init__.py").write_text("", encoding="utf-8")
        imports, body, local_ok, local_fail = [], [], [], []
        size = min(MODULE_SIZE, n - made)
        i = 0
        while i < size:
            kind = rng.choices(kinds, weights)[0]
            if kind == "mutual" and size - i < 2:
                kind = "leaf"
            name = f"f{made + i:07d}"
            callee = None
            if kind == "chain":
                options = [c for c in local_ok if depth[c["qual"]] < MAX_DEPTH]
                callee = rng.choice(options) if options else None
            elif kind == "cross":
                options = [c for c in exported[-4 * MODULE_SIZE:] if depth[c["qual"]] < MAX_DEPTH]
                if options:
                    c = rng.choice(options)
                    callee = {**c, "as": f"x_{c['name']}"}
                    imports.append(f"from {c['module']} import {c['name']} as {callee['as']}")
            elif kind == "fail_caller":
                callee = rng.choice(local_fail) if local_fail else None
            if kind in ("chain", "cross", "fail_caller") and callee is None:
                kind = "leaf"
            qual = f"{mod}::{name}"
            if kind == "mutual":
                odd = f"f{made + i + 1:07d}"
                body += [[f"def {name}(n: int) -> int:", "    if n <= 0:", "        return 1", f"    return {odd}(n - 1)"],
                         [f"def {odd}(n: int) -> int:", "    if n <= 0:", "        return 0", f"    return {name}(n - 1)"]]
                key[qual] = {"kind": "mutual", "module": mod}
                key[f"{mod}::{odd}"] = {"kind": "mutual", "module": mod}
                i += 2
                continue
            body.append(_function(kind, name, rng, callee))
            key[qual] = {"kind": kind, "module": mod}
            if callee is not None:
                key[qual]["calls"] = callee["qual"]
            depth[qual] = depth[callee["qual"]] + 1 if kind in ("chain", "cross") else 0
            entry = {"qual": qual, "name": name, "module": mod, "as": name}
            if kind in CALLABLE:
                local_ok.append(entry)
            elif kind == "fail":
                local_fail.append(entry)
            i += 1
        text = [f'"""Generated by `cardmodel scale bench` (seed {seed}): module {index}."""', ""]
        text += imports + ([""] if imports else [])
        text += ["\n".join(f) + "\n\n" for f in body]
        path.write_text("\n".join(text).rstrip() + "\n", encoding="utf-8")
        exported += [e for e in local_ok if key[e["qual"]]["kind"] in CALLABLE]
        made += size
        index += 1
    return key


def _args(fn: dict, i: int) -> list:
    return [(i + 3 * k) % 9 + 1 for k in range(len(fn["params"]))]


def _rss_mb() -> float:
    from ..kernel import resources
    return round(resources.peak_mb(), 1)


def measure(ctx: Ctx, n: int, seed: int, workdir: Path | None = None, warm: bool = True) -> dict:
    """Generate one project of ``n`` functions and time each stage over it (in this process). A warm-up run on one
    small module first keeps imports and first-call caches out of the timed stages."""
    _ = ctx.ops                                    # the op table belongs to start-up, not to the first stage
    if warm:
        _stages(ctx, MODULE_SIZE // 2, seed + 1, workdir, _rss_mb())
    return _stages(ctx, n, seed, workdir, _rss_mb())


def _stages(ctx: Ctx, n: int, seed: int, workdir: Path | None, baseline: float) -> dict:
    from . import analyse, lift_project
    from .ir import Interpreter, IRError
    with tempfile.TemporaryDirectory(prefix="cardmodel_scale_", dir=workdir) as tmp:
        root = Path(tmp)
        t0 = time.perf_counter()
        key = generate(root, n, seed)
        files = sorted(root.rglob("*.py"))
        gen_s = time.perf_counter() - t0
        times, peaks = {}, {}

        t0 = time.perf_counter()
        lifted = lift_project.lift_files(ctx, [(p, "python") for p in files], root=root)
        times["lift"] = time.perf_counter() - t0
        peaks["lift"] = _rss_mb()
    ok = {q: lf for q, lf in lifted.functions.items() if lf.ok}
    n_partial = sum(bool(getattr(lf, "partial", False)) for lf in lifted.functions.values())
    fns = [{**lf.ir, "name": q} for q, lf in sorted(ok.items())]

    t0 = time.perf_counter()
    analyse.structure({"functions": fns})
    times["structure"] = time.perf_counter() - t0
    peaks["structure"] = _rss_mb()

    t0 = time.perf_counter()
    n_obl = sum(len(analyse.obligations(fn)) for fn in fns)
    times["obligations"] = time.perf_counter() - t0
    peaks["obligations"] = _rss_mb()

    t0 = time.perf_counter()
    interp = Interpreter({"functions": fns}, ctx.ops)
    ran = errors = 0
    for i, fn in enumerate(fns):
        try:
            interp.call(fn["name"], _args(fn, i))
            ran += 1
        except (IRError, RecursionError, ArithmeticError):
            errors += 1
    times["reference"] = time.perf_counter() - t0
    peaks["reference"] = _rss_mb()

    by_kind: dict[str, dict] = {}
    for q, k in key.items():
        lf = lifted.functions.get(q)
        row = by_kind.setdefault(k["kind"], {"functions": 0, "lifted": 0, "partial": 0})
        row["functions"] += 1
        row["lifted"] += bool(lf and lf.ok)
        row["partial"] += bool(lf and getattr(lf, "partial", False))
    total = sum(times.values())
    peak = max(peaks.values())
    return {"n": n, "seed": seed, "functions": len(key), "modules": len({k["module"] for k in key.values()}),
            "lifted": len(ok), "lift_rate": round(len(ok) / len(key), 4) if key else None,
            "partial": n_partial,
            "lift_rate_with_boundaries": round((len(ok) + n_partial) / len(key), 4) if key else None,
            "cross_calls": lifted.cross_calls, "unparsed": len(lifted.unparsed), "obligations": n_obl,
            "reference_ran": ran, "reference_errors": errors, "by_kind": dict(sorted(by_kind.items())),
            "generate_s": round(gen_s, 3), "stage_s": {s: round(times[s], 3) for s in STAGES},
            "total_s": round(total, 3),
            "us_per_function": {**{s: round(1e6 * times[s] / n, 2) for s in STAGES}, "total": round(1e6 * total / n, 2)},
            "baseline_mb": baseline, "stage_peak_mb": peaks, "peak_mb": peak,
            "peak_over_baseline_mb": round(peak - baseline, 1),
            "kb_per_function": round(1024 * (peak - baseline) / n, 2)}


def _child(n: int, seed: int) -> dict:
    """``measure`` in a fresh interpreter, so ``ru_maxrss`` is this size's alone."""
    code = ("import json, sys\nfrom cardmodel.engines import scale\nfrom cardmodel.engines.context import Ctx\n"
            "from cardmodel.kernel.store import open_store\n"
            f"print(json.dumps(scale.measure(Ctx(open_store(project=False)), {int(n)}, {int(seed)})))\n")
    env = {**os.environ, "CARDMODEL_SELF": "0"}
    pkg_root = str(Path(__file__).resolve().parents[2])
    env["PYTHONPATH"] = pkg_root + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    try:
        proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env,
                              timeout=CHILD_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return {"n": n, "seed": seed, "error": f"timed out after {CHILD_TIMEOUT_S} s"}
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout).strip().splitlines()[-3:]
        return {"n": n, "seed": seed, "error": " | ".join(tail) or f"exit {proc.returncode}"}
    return json.loads(proc.stdout.strip().splitlines()[-1])


def bench(ctx: Ctx, sizes=SIZES, seed: int = 0, isolate: bool = True, progress=None) -> dict:
    """Measure every size (smallest first); the slope is time per function at the largest ÷ at 10³ (or the
    smallest size, when no size reaches 10³)."""
    from .optimize import host
    rows = []
    for n in sorted(sizes):
        row = _child(n, seed) if isolate else measure(ctx, n, seed)
        rows.append(row)
        if progress:
            progress(row)
    good = [r for r in rows if "error" not in r]
    base = next((r for r in good if r["n"] >= SIZES[0]), good[0]) if good else None   # 10³ when measured (§6)
    slope = None
    if base is not None and base is not good[-1] and base["us_per_function"]["total"]:
        slope = round(good[-1]["us_per_function"]["total"] / base["us_per_function"]["total"], 3)
    return {"seed": seed, "sizes": [r["n"] for r in rows], "rows": rows, "slope": slope,
            "slope_between": [base["n"], good[-1]["n"]] if slope is not None else None,
            "largest_peak_mb": good[-1]["peak_mb"] if good else None, "host": host(), "isolated": isolate,
            "finished": datetime.now(timezone.utc).isoformat(timespec="seconds")}


def record(ctx: Ctx, result: dict, layer: str | None = None) -> list[str]:
    """One metric card per measured size; each carries the run's slope so the newest run answers the goals."""
    out = []
    run = {k: result[k] for k in ("seed", "sizes", "slope", "slope_between", "largest_peak_mb", "finished")}
    for r in result["rows"]:
        if "error" in r:
            continue
        name = f"scale__n{r['n']}"
        ctx.store.save({
            "name": name, "category": "metric", "tier": 3, "target_card": "goal/G_A11_scale_slope",
            "form": "lift+structure+obligations+reference", "lang": "python",
            "median_ns": round(r["us_per_function"]["total"] * 1000, 1), "samples": 1, "host": result["host"],
            "statement": f"scale bench at {r['n']} synthetic functions: {r['us_per_function']['total']} µs and "
                         f"{r['kb_per_function']} KB per function, peak {r['peak_mb']} MB, lift rate {r['lift_rate']}",
            "scale": r, "run": run, "metadata": {"seed": result["seed"]},
            "provenance": {"tool": "cardmodel scale bench"}}, layer=layer, category="metric")
        out.append(f"metric/{name}")
    return out


def latest(store) -> dict | None:
    """The ``run`` block of the newest scale bench recorded in the store."""
    runs = [c.get("run") for c in store.cards("metric") if c.name.startswith("scale__n") and c.get("run")]
    return max(runs, key=lambda r: r.get("finished") or "") if runs else None


def goal_metric(store, name: str):
    run = latest(store)
    if not run:
        return None
    return {"scale_slope": run.get("slope"), "scale_peak_memory_mb": run.get("largest_peak_mb")}.get(name)


def report_text(result: dict) -> str:
    L = [f"scale bench · seed {result['seed']} · {result['host'].get('cpu') or result['host'].get('machine')} · "
         f"Python {result['host'].get('python')}",
         f"{'functions':>10} {'lifted':>7} {'lift':>8} {'struct':>8} {'oblig':>8} {'ref':>8} {'total':>9} "
         f"{'KB/fn':>7} {'peak MB':>8}   (µs per function)"]
    for r in result["rows"]:
        if "error" in r:
            L.append(f"{r['n']:>10}  failed: {r['error']}")
            continue
        u = r["us_per_function"]
        L.append(f"{r['n']:>10} {r['lift_rate']:>7} {u['lift']:>8} {u['structure']:>8} {u['obligations']:>8} "
                 f"{u['reference']:>8} {u['total']:>9} {r['kb_per_function']:>7} {r['peak_mb']:>8}")
    if result["slope"] is not None:
        a, b = result["slope_between"]
        L.append(f"slope {result['slope']} (time per function at {b} ÷ at {a}; goal G_A11 ≤ 2) · "
                 f"peak {result['largest_peak_mb']} MB at {b} (goal G_A12 ≤ 2048)")
    return "\n".join(L)
