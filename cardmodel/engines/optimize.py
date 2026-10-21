"""optimize — measure real costs on this host, record them as metric cards, update cost anchors.

Form costs on cards start as anchors (estimates inherited from the hub).
``measure`` times every runnable, available form on the card's own inputs:

  Python forms         in-process, ``time.perf_counter_ns`` over repeated batches
  compiled functions   (function cards) the bench harness of each language,
                       run at two repetition counts; per-call time is the slope
                       (startup cancels), arguments pass through the language's
                       opaque template so the compiler cannot fold the calls

Every measurement becomes ``metric/metric__<card>__<form>`` (median, MAD,
samples, seed, input signature, host fingerprint: hub L28 / Pheros L59).
``cheapest(cost="measured")`` uses them. ``apply`` rewrites form costs in
calibrated units: 1 unit = the measured cost of ``op/ADD`` form ``native``
on this host, so anchors and measurements stay comparable; the old anchor is
kept in ``cost_anchor``. A verdict per card says whether the measurement
confirms the anchor ordering (green), contradicts it (red) or cannot tell
apart within noise (white), per hub L4.

Honest limits (L1): timings depend on this machine and its load; Python
in-process timings include call overhead; compiled per-call costs are a
slope over two runs, not a cycle count.
"""
from __future__ import annotations

import hashlib
import json
import platform
import random
import statistics
import sys
import time

from . import values as V
from .codegen import EmitGap, Emitter
from .context import Ctx
from .rewrite import available, forms_of
from .runners import run_program
from .witness import _arity, _generators, _ref_rows, _reference, python_callable

NOISE = 0.15


def host() -> dict:
    return {"system": platform.system(), "machine": platform.machine(), "python": sys.version.split()[0],
            "node": None}


def _mad(xs):
    m = statistics.median(xs)
    return statistics.median([abs(x - m) for x in xs])


def measure_python_forms(ctx: Ctx, card, seed: int, n_inputs: int = 64, repeats: int = 7) -> list[dict]:
    ref = _reference(card)
    if ref is None:
        return []
    ref_fn = python_callable(ctx, ref, card)
    arity = _arity(card, ref_fn)
    rng = random.Random(f"{seed}:{card['name']}")
    out = []
    for f in card.get("forms") or []:
        if f.get("lang", "python") != "python":
            continue
        fv = forms_of({"name": card["name"], "forms": [f]})[0]
        if not fv.runnable or not available(ctx.store, fv)[0]:
            continue
        gens = _generators(ctx, card, f, arity)
        rows = _ref_rows(ref_fn, gens, n_inputs, rng, None)
        if not rows:
            continue
        fn = python_callable(ctx, f, card)
        args = [a for a, _ in rows]
        try:
            for a in args:
                fn(*a)
        except Exception:  # noqa: BLE001 -- a form that raises on its own domain is not measured
            continue
        samples = []
        loops = 20
        for _ in range(repeats):
            t0 = time.perf_counter_ns()
            for _ in range(loops):
                for a in args:
                    fn(*a)
            samples.append((time.perf_counter_ns() - t0) / (loops * len(args)))
        sig = hashlib.sha256(repr(args).encode()).hexdigest()[:16]
        out.append({"target_card": f"{card.registry or card.get('category')}/{card['name']}",
                    "card": card["name"], "form": f["name"], "lang": "python", "median_ns": statistics.median(samples),
                    "mad_ns": _mad(samples), "samples": repeats, "calls_per_sample": loops * len(args),
                    "anchor": f.get("cost"), "seed": seed, "inputs_signature": sig})
    return out


def measure_function(ctx: Ctx, card, langs: list[str] | None = None, seed: int = 0, reps=(200, 2000),
                     n_inputs: int = 16) -> list[dict]:
    module = card["ir"]
    vecs = [v["args"] for v in card.get("vectors", [])][:n_inputs]
    if not vecs:
        return []
    out = []
    for f in card.get("forms") or []:
        lang = f.get("lang")
        if not f.get("generated") or (langs and lang not in langs):
            continue
        ok, _ = ctx.available(lang)
        if not ok:
            continue
        lang_card = ctx.language(lang)
        bits = lang_card.get("int_bits")
        calls = [a for a in vecs if all(V.fits(x, bits) for x in a)]
        if not calls:
            continue
        times = []
        try:
            for r in reps:
                src = Emitter(ctx.store, lang, ctx.ops).program(module, calls, mode="bench", reps=r)
                run_program(lang_card, src, ctx.state_root, parse=False)   # warm the build cache
                best = min((run_program(lang_card, src, ctx.state_root, parse=False).run_ms for _ in range(3)))
                times.append(best)
        except EmitGap:
            continue
        per_call_ns = max(0.0, (times[1] - times[0]) * 1e6 / ((reps[1] - reps[0]) * len(calls)))
        startup_ms = max(0.0, times[0] - per_call_ns * reps[0] * len(calls) / 1e6)
        out.append({"target_card": f"function/{card['name']}", "card": card["name"], "form": f["name"], "lang": lang,
                    "median_ns": per_call_ns, "startup_ms": round(startup_ms, 2), "samples": 3 * len(reps),
                    "calls_per_sample": list(reps), "seed": seed, "anchor": f.get("cost"),
                    "inputs_signature": hashlib.sha256(repr(calls).encode()).hexdigest()[:16]})
    return out


def write_metrics(ctx: Ctx, rows: list[dict], layer: str | None = None) -> list[str]:
    h = host()
    names = []
    for r in rows:
        name = f"metric__{r['card']}__{r['form']}"
        card = {"name": name, "category": "metric", "tier": 3,
                "statement": f"{r['target_card']} form {r['form']}: {r['median_ns']:.1f} ns per call on this host",
                "target_card": r["target_card"], "form": r["form"], "lang": r.get("lang"),
                "median_ns": round(r["median_ns"], 3), "mad_ns": round(r.get("mad_ns", 0.0), 3),
                "samples": r["samples"], "calls_per_sample": r.get("calls_per_sample"),
                "startup_ms": r.get("startup_ms"), "anchor": r.get("anchor"),
                "host": h, "metadata": {"seed": r["seed"], "run_conditions": h,
                                        "inputs_signature": r["inputs_signature"]},
                "provenance": {"tool": "cardmodel optimize"}}
        ctx.store.save(card, layer=layer, category="metric")
        names.append(f"metric/{name}")
    return names


def unit_ns(ctx: Ctx) -> float | None:
    m = ctx.store.get("metric/metric__ADD__native")
    return float(m["median_ns"]) if m else None


def verdicts(rows: list[dict]) -> list[dict]:
    """Per card: does the measured ordering of forms confirm the anchor ordering? (hub L4)"""
    by_card: dict[str, list[dict]] = {}
    for r in rows:
        by_card.setdefault(r["target_card"], []).append(r)
    out = []
    for card, rs in by_card.items():
        rs = [r for r in rs if isinstance(r.get("anchor"), (int, float))]
        if len(rs) < 2:
            continue
        cheap_anchor = min(rs, key=lambda r: r["anchor"])
        cheap_meas = min(rs, key=lambda r: r["median_ns"])
        if cheap_anchor is cheap_meas:
            verdict = "green"
        else:
            ratio = cheap_anchor["median_ns"] / max(cheap_meas["median_ns"], 1e-9)
            verdict = "white" if ratio < 1 + NOISE else "red"
        out.append({"card": card, "verdict": verdict, "anchor_pick": cheap_anchor["form"],
                    "measured_pick": cheap_meas["form"],
                    "measured_ns": {r["form"]: round(r["median_ns"], 1) for r in rs}})
    return out


def apply_costs(ctx: Ctx, rows: list[dict], layer: str | None = None) -> list[str]:
    """Rewrite python-form costs in calibrated units (1 unit = op/ADD native here); keeps cost_anchor."""
    unit = unit_ns(ctx)
    if not unit:
        raise RuntimeError("no metric for op/ADD native yet: run `cardmodel optimize --card op/ADD` first")
    changed = []
    by_card: dict[str, dict[str, float]] = {}
    for r in rows:
        if r.get("lang") == "python":
            by_card.setdefault(r["target_card"], {})[r["form"]] = r["median_ns"]
    for qname, forms in by_card.items():
        card = ctx.store.get(qname)
        if card is None:
            continue
        data = json.loads(json.dumps(dict(card)))
        touched = False
        for f in data.get("forms") or []:
            if f.get("name") in forms:
                f.setdefault("cost_anchor", f.get("cost"))
                f["cost"] = round(forms[f["name"]] / unit, 3)
                f["cost_basis"] = "measured (1 unit = op/ADD native on this host)"
                touched = True
        if touched:
            _, did = ctx.store.save(data, layer=layer or card.layer, category=card.registry)
            if did:
                changed.append(qname)
    return changed
