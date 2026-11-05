"""optimize — measure real costs on this host, record them as metric cards, update cost anchors.

Form costs on cards start as anchors (estimates inherited from the hub).
``measure`` times every runnable, available form on the card's own inputs:

  Python forms         in-process, ``time.perf_counter_ns`` over repeated batches, every form
                       on one shared input set when the forms' domains overlap enough
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
apart within noise (white: under NOISE or within twice the summed MADs), per hub L4.
Only forms timed on the same calls are compared, and a compiled slope at or below
zero (``resolved: False``) is never taken as the cheapest.

Costs are per function x language x host: a metric card keeps one entry per host id (OS, architecture, CPU,
Python) in ``by_host``; ``rewrite.measured_ns`` and ``rewrite.rank_targets`` read this host's entry, so the
ranking answers which target a function should run in here. A compiled slope whose two runs differ by less than
``SLOPE_MIN_MS`` is re-run with ten times the calls (up to ``SLOPE_MAX_REPS``); the card's own Python source is
timed in-process on the same calls as the baseline.

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
    """The host block on every metric card. ``env`` names the environment card of this machine
    (``environment/env_<fingerprint>``, docs/ENVIRONMENTS.md E21), so a measurement says which machine's full
    identity it was taken on; ``id`` stays the short cost-model key the ``by_host`` rows are filed under."""
    from .environment import card_name
    return {"system": platform.system(), "machine": platform.machine(), "python": sys.version.split()[0],
            "node": None, "cpu": _cpu_model(), "id": host_id(), "env": card_name()}


def _cpu_model() -> str:
    try:
        with open("/proc/cpuinfo", encoding="utf-8") as f:       # Linux
            for line in f:
                if line.startswith("model name"):
                    return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or platform.machine()


def host_id() -> str:
    """A short, stable name for this machine's cost model: OS, architecture, CPU and Python version. Two hosts
    with the same id are expected to rank forms the same way; the machine's name is not part of it."""
    key = f"{platform.system()}|{platform.machine()}|{_cpu_model()}|{sys.version.split()[0]}"
    return hashlib.sha256(key.encode()).hexdigest()[:12]


def _mad(xs):
    m = statistics.median(xs)
    return statistics.median([abs(x - m) for x in xs])


MIN_SHARED = 8


def measure_python_forms(ctx: Ctx, card, seed: int, n_inputs: int = 64, repeats: int = 7) -> list[dict]:
    """Every runnable Python form of ``card``, timed per call. Forms are timed on one shared input set when they
    can be: the union of each form's own generated inputs, kept where every form returns the reference's value.
    A form whose domain is narrower (``pow2_bit`` for MOD, small exponents for ``square_mul``) is then timed
    on the same calls as ``native``, so the verdict compares like with like. When fewer than ``MIN_SHARED``
    inputs are shared, each form is timed on its own inputs and its row says ``shared_inputs: False``."""
    ref = _reference(card)
    if ref is None:
        return []
    ref_fn = python_callable(ctx, ref, card)
    arity = _arity(card, ref_fn)
    rng = random.Random(f"{seed}:{card['name']}")
    forms = []
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
        forms.append((f, fn, rows))
    shared = _shared_inputs(forms)
    out = []
    for f, fn, rows in forms:
        args = shared if len(shared) >= MIN_SHARED else [a for a, _ in rows]
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
                    "anchor": f.get("cost"), "seed": seed, "inputs_signature": sig,
                    "shared_inputs": len(shared) >= MIN_SHARED})
    return out


def _shared_inputs(forms: list) -> list[tuple]:
    """The inputs on which every form agrees with the reference (in first-seen order)."""
    pool: dict[str, tuple] = {}
    for _, _, rows in forms:
        for a, e in rows:
            pool.setdefault(repr(a), (a, e))
    shared = []
    for a, e in pool.values():
        try:
            if all(_same(fn(*a), e) for _, fn, _ in forms):
                shared.append(a)
        except Exception:  # noqa: BLE001 -- outside some form's domain: not shared
            continue
    return shared


def _same(got, exp) -> bool:
    if isinstance(exp, float) or isinstance(got, float):
        try:
            return abs(got - exp) <= 1e-9 * max(1.0, abs(exp))
        except TypeError:
            return False
    return got == exp


def measure_function(ctx: Ctx, card, langs: list[str] | None = None, seed: int = 0, reps=(200, 2000),
                     n_inputs: int = 16, python_source: bool = True) -> list[dict]:
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
        try:
            reps_used, times = _slope_runs(ctx, lang_card, lang, module, calls, reps)
        except EmitGap:
            continue
        # the slope is the per-call cost only when the longer run took measurably longer: a slope at or below
        # zero is noise (startup jitter larger than the extra calls), not a free function
        resolved = times[1] > times[0]
        per_call_ns = max(0.0, (times[1] - times[0]) * 1e6 / ((reps_used[1] - reps_used[0]) * len(calls)))
        startup_ms = max(0.0, times[0] - per_call_ns * reps_used[0] * len(calls) / 1e6)
        out.append({"target_card": f"function/{card['name']}", "card": card["name"], "form": f["name"], "lang": lang,
                    "median_ns": per_call_ns, "resolved": resolved,
                    "startup_ms": round(startup_ms, 2), "samples": 3 * len(reps_used),
                    "calls_per_sample": list(reps_used), "seed": seed, "anchor": f.get("cost"),
                    "inputs_signature": hashlib.sha256(repr(calls).encode()).hexdigest()[:16]})
    if python_source and (not langs or "python" in langs):
        out += _measure_python_source(ctx, card, vecs, seed)
    return out


SLOPE_MIN_MS = 5.0       # the long run must take this much longer than the short one to give a slope
SLOPE_MAX_REPS = 200000


def _slope_runs(ctx: Ctx, lang_card, lang: str, module, calls, reps) -> tuple[tuple, list]:
    """Best-of-3 wall times of the bench program at two repetition counts. When the difference is lost in startup
    noise (fast code: a C function at 2000 reps is microseconds), the long count grows tenfold, up to
    ``SLOPE_MAX_REPS``, so the slope is a measurement and not jitter."""
    def best(r):
        src = Emitter(ctx.store, lang, ctx.ops).program(module, calls, mode="bench", reps=r)
        run_program(lang_card, src, ctx.state_root, parse=False)   # warm the build cache
        return min(run_program(lang_card, src, ctx.state_root, parse=False).run_ms for _ in range(3))

    lo, hi = reps
    t_lo, t_hi = best(lo), best(hi)
    while t_hi - t_lo < max(SLOPE_MIN_MS, 0.2 * t_lo) and hi * 10 <= SLOPE_MAX_REPS:
        hi *= 10
        t_hi = best(hi)
    return (lo, hi), [t_lo, t_hi]


def _measure_python_source(ctx: Ctx, card, vecs, seed: int, repeats: int = 7) -> list[dict]:
    """The card's own Python source, timed in-process on the same calls as the compiled forms: the per-call cost
    of staying in Python, the baseline every native target is compared with."""
    f = next((x for x in card.get("forms") or [] if x.get("name") == "python_source"), None)
    if f is None:
        return []
    try:
        fn = python_callable(ctx, f, card)
        for a in vecs:
            fn(*a)
    except Exception:  # noqa: BLE001 -- a source that does not run here is not measured
        return []
    loops = max(1, 2000 // len(vecs))
    samples = []
    for _ in range(repeats):
        t0 = time.perf_counter_ns()
        for _ in range(loops):
            for a in vecs:
                fn(*a)
        samples.append((time.perf_counter_ns() - t0) / (loops * len(vecs)))
    return [{"target_card": f"function/{card['name']}", "card": card["name"], "form": f["name"], "lang": "python",
             "in_process": True, "median_ns": statistics.median(samples), "mad_ns": _mad(samples),
             "samples": repeats, "calls_per_sample": loops * len(vecs), "seed": seed, "anchor": f.get("cost"),
             "inputs_signature": hashlib.sha256(repr(vecs).encode()).hexdigest()[:16]}]
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
                "shared_inputs": r.get("shared_inputs"), "resolved": r.get("resolved", True),
                "host": h, "metadata": {"seed": r["seed"], "run_conditions": h,
                                        "inputs_signature": r["inputs_signature"]},
                "provenance": {"tool": "cardmodel optimize"}}
        # every host keeps its own measurement: the card's top-level fields are the latest run, ``by_host`` holds
        # the latest run per host id, so a second machine adds to the cost model instead of overwriting it
        prev = ctx.store.get(f"metric/{name}")
        by_host = dict((prev.get("by_host") or {}) if prev else {})
        by_host[h["id"]] = {k: card[k] for k in ("median_ns", "mad_ns", "startup_ms", "resolved", "samples")}
        by_host[h["id"]].update(host=h, seed=r["seed"], inputs_signature=r["inputs_signature"])
        card["by_host"] = by_host
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
        rs = [r for r in rs if isinstance(r.get("anchor"), (int, float)) and r.get("resolved", True)]
        # forms are compared only on the same calls: the largest group sharing one input signature
        groups: dict[str, list[dict]] = {}
        for r in rs:
            groups.setdefault(r.get("inputs_signature"), []).append(r)
        rs = max(groups.values(), key=len, default=[])
        if len(rs) < 2:
            continue
        cheap_anchor = min(rs, key=lambda r: r["anchor"])
        cheap_meas = min(rs, key=lambda r: r["median_ns"])
        if cheap_anchor is cheap_meas:
            verdict = "green"
        else:
            gap = cheap_anchor["median_ns"] - cheap_meas["median_ns"]
            ratio = cheap_anchor["median_ns"] / max(cheap_meas["median_ns"], 1e-9)
            spread = 2 * ((cheap_anchor.get("mad_ns") or 0.0) + (cheap_meas.get("mad_ns") or 0.0))
            verdict = "white" if ratio < 1 + NOISE or gap <= spread else "red"
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
