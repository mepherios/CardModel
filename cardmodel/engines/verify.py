"""verify — run every witness the model has, with one seed, and record what happened.

Sections (all on by default; ``only`` selects):
  kernel        load errors, card-type schema validation, closure (CM10/CM11)
  forms         op / call / re_operation forms vs their reference (witness.verify_forms)
  vectors       known-answer vectors (crypto atoms, detect_format, ...)
  rules         rewrite rules on seeded integers
  redefinitions executable Pheros identities (numeric; symbolic if sympy is present)
  conformance   the op x language matrix through real toolchains
  functions     every function card's forms in every language
  proofs        rule theorems checked by a local proof assistant (emit/lean.py; when a toolchain is present)
  selfcheck     no source-folder references in the code; on macOS the CLI re-runs with the source folders
                (read from the vendored registries' provenance) unreadable
  portability   every Python 3 interpreter found on this machine runs `verify --only kernel,rules`
  logic         the model's own laws as logic over its store (stdlib/self.card): zero violations (CM27)
  lang          every card-language program (examples/lang, stdlib) runs and passes (CM26)
  theorems      every theorem card is re-witnessed with this seed; a status must match its evidence (CM23)
  game          the design_law cards on the exact equilibrium of the neutral exchange, and the world (CM28, CM29)

The result is saved to ``state/last_verify.json`` (coverage and goals read
it). ``record=True`` also writes each card's verdict into the card
(``verification`` field, versioned save). Hub-claim refutations are
informational: they document an overstated original claim, while the
card's declared domain is what must pass.

A section that could not run says so (``skipped`` with the reason); a
section that ran zero checks is ``vacuous`` (CM07), never a pass.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

from . import conformance, redefs, translate, witness
from . import values as V
from .context import Ctx

SECTIONS = ("kernel", "logic", "lang", "theorems", "game", "forms", "vectors", "rules", "redefinitions",
            "conformance", "functions", "proofs", "selfcheck", "portability")
QUICK = ["kernel", "logic", "lang", "theorems", "game", "forms", "vectors", "rules", "redefinitions"]


def _kernel(ctx: Ctx) -> dict:
    from ..kernel.types import closure, validate_store
    errors = ctx.store.load_errors()
    findings = validate_store(ctx.store)
    schema_errors = {k: v["errors"] for k, v in findings.items() if v["errors"]}
    unresolved = closure(ctx.store)
    reg_errors = []
    from ..kernel.schema import validate
    reg_type = ctx.store.get("card_type/registry")
    if reg_type is not None:
        for name, view in ctx.store.views.items():
            for r in view.regs:
                for e in validate(r.meta, reg_type["schema"]):
                    reg_errors.append(f"{name}: {e}")
    ok = not errors and not schema_errors and not unresolved and not reg_errors
    return {"status": "pass" if ok else "fail", "load_errors": errors, "schema_errors": schema_errors,
            "schema_error_cards": len(schema_errors), "warnings": sum(len(v["warnings"]) for v in findings.values()),
            "unresolved_references": unresolved, "registry_errors": reg_errors,
            "cards": len(ctx.store.ALL), "registries": len(ctx.store.views)}


def _forms(ctx: Ctx, seed: int, samples: int) -> dict:
    out = {}
    for reg in ("op", "call", "re_operation", "crypto_atom"):
        for card in ctx.store.cards(reg):
            if not any(f.get("code") or f.get("file") for f in card.get("forms") or []):
                continue
            if card.get("vectors") and reg == "crypto_atom":
                continue   # crypto atoms are checked against their vectors instead
            res = witness.verify_forms(ctx, card, seed=seed, samples=samples)
            if res["forms"]:
                out[card.qualified] = res
    statuses = [f["status"] for r in out.values() for f in r["forms"].values()]
    hub = [f["hub_claim"]["status"] for r in out.values() for f in r["forms"].values() if "hub_claim" in f]
    return {"status": "fail" if "fail" in statuses or "error" in statuses else ("pass" if "pass" in statuses else "vacuous"),
            "counts": {s: statuses.count(s) for s in sorted(set(statuses))},
            "hub_claims": {s: hub.count(s) for s in sorted(set(hub))}, "cards": out}


def _vectors(ctx: Ctx) -> dict:
    out = {}
    for reg in ("crypto_atom", "re_operation", "op", "call"):
        for card in ctx.store.cards(reg):
            if card.get("vectors"):
                out[card.qualified] = witness.verify_vectors(ctx, card)
    st = [r["status"] for r in out.values()]
    return {"status": "fail" if "fail" in st else ("pass" if "pass" in st else "vacuous"),
            "counts": {s: st.count(s) for s in sorted(set(st))}, "cards": out}


def _rules(ctx: Ctx, seed: int) -> dict:
    out = {c.qualified: witness.verify_rule(c, seed=seed) for c in ctx.store.cards("rewrite_rule")}
    st = [r["status"] for r in out.values()]
    return {"status": "fail" if "fail" in st else ("pass" if "pass" in st else "vacuous"),
            "counts": {s: st.count(s) for s in sorted(set(st))}, "cards": out}


def _logic(ctx: Ctx) -> dict:
    from . import selflogic
    r = selflogic.evaluate_self(ctx)
    r.pop("model", None)
    return r


def card_programs(ctx: Ctx) -> list:
    from ..kernel import paths
    home = paths.home()
    out = sorted((home / "examples" / "lang").glob("*.card")) + sorted((home / "stdlib").glob("*.card"))
    return [p for p in out if p.name != "self.card"]


def _lang(ctx: Ctx, seed: int) -> dict:
    from ..lang.compile import CompileError, compile_file
    from ..lang.run import run as run_module
    from ..lang.syntax import CardSyntaxError
    out = {}
    for p in card_programs(ctx):
        try:
            mod = compile_file(p, ctx.ops, ctx.store)
            rep = run_module(ctx, mod, seed=seed, samples=120)
            out[p.name] = {"status": rep["status"], "counts": rep["counts"],
                           "failing": [t for t in rep["tests"] if t["status"] != "pass"][:5],
                           "refuted": [t["name"] for t in rep["theorems"] if t["status"] == "refuted"]}
        except (CompileError, CardSyntaxError) as exc:
            out[p.name] = {"status": "fail", "error": str(exc)}
    st = [r["status"] for r in out.values()]
    return {"status": "fail" if "fail" in st else ("pass" if st else "vacuous"),
            "counts": {s: st.count(s) for s in sorted(set(st))}, "programs": out}


def _theorems(ctx: Ctx, seed: int, samples: int) -> dict:
    """Re-witness every theorem card; a refuted proved statement is a semantics bug (fail)."""
    from . import theorems as T
    out = {}
    for card in ctx.store.cards("theorem"):
        sem = card.get("semantics")
        w = T.witness_card(card, ctx.ops, seed, samples)
        claimed = card.get("status")
        has_proof = any(p.get("ok") for p in card.get("proofs") or [])
        problem = None
        if w["status"] == "refuted" and claimed != "refuted":
            problem = f"claimed {claimed} but refuted at {w.get('counterexample')}"
        elif claimed == "proved" and not has_proof:
            problem = "claimed proved without a proof"
        elif claimed == "refuted" and w["status"] == "witnessed":
            problem = "claimed refuted but the witness holds"
        out[card.qualified] = {"claimed": claimed, "witness": w["status"], "problem": problem,
                               "semantics": sem, "imported": T.imported(card)}
    problems = {q: r["problem"] for q, r in out.items() if r["problem"]}
    claimed = [r["claimed"] for r in out.values()]
    return {"status": "fail" if problems else ("pass" if out else "vacuous"), "problems": problems,
            "counts": {s: claimed.count(s) for s in sorted(set(claimed))},
            "lean_mismatches": sum(1 for r in out.values() if r["imported"] and r["witness"] == "refuted"),
            "cards": len(out)}


def _game(ctx: Ctx) -> dict:
    if not ctx.store.cards("move"):
        return {"status": "skipped", "reason": "no move cards"}
    from ..game import analysis as A
    from ..game import world as W
    from ..game.combat import Combat
    r = A.check(Combat(ctx))
    w = W.run(ctx)
    failing = [n for n, law in r["laws"].items() if not law["ok"]]
    return {"status": "fail" if failing else "pass", "laws_passed": r["passed"], "laws_total": r["total"],
            "failing": failing, "equilibrium": r["equilibrium"], "options": r["moves"],
            "world_final_facts": len(w["final"])}


def _redefinitions(ctx: Ctx, seed: int) -> dict:
    out = {c.qualified: redefs.verify(c, seed=seed) for c in ctx.store.cards("redefinition")}
    st = [r["verdict"] for r in out.values()]
    return {"status": "fail" if "refuted" in st else ("pass" if st else "vacuous"),
            "counts": {s: st.count(s) for s in sorted(set(st))}, "cards": out}


def _conformance(ctx: Ctx, seed: int, langs) -> dict:
    rep = conformance.matrix(ctx, langs=langs, seed=seed)
    good, total = conformance.rate(rep)
    rep["status"] = "pass" if total and good == total else ("vacuous" if not total else "fail")
    rep["rate"] = [good, total]
    return rep


def _functions(ctx: Ctx, seed: int, langs) -> dict:
    out = {}
    for card in ctx.store.cards("function"):
        out[card.qualified] = translate.verify_function(ctx, card, langs=langs, seed=seed)
    fails = [q for q, r in out.items() if r["lift_mismatches"] or any(
        l["status"] in ("fail", "error") for l in r["languages"].values())]
    return {"status": "fail" if fails else ("pass" if out else "vacuous"), "failing": fails, "cards": out}


def run(ctx: Ctx, seed: int | None = None, only: list[str] | None = None, langs: list[str] | None = None,
        samples: int = 48, record: bool = False) -> dict:
    seed = V.fresh_seed() if seed is None else seed
    only = list(only or SECTIONS)
    report = {"seed": seed, "started": datetime.now(timezone.utc).isoformat(timespec="seconds"), "sections": {}}
    timings = {}
    for sec in SECTIONS:
        if sec not in only:
            continue
        t0 = time.perf_counter()
        if sec == "kernel":
            res = _kernel(ctx)
        elif sec == "logic":
            res = _logic(ctx)
        elif sec == "lang":
            res = _lang(ctx, seed)
        elif sec == "theorems":
            res = _theorems(ctx, seed, max(40, samples))
        elif sec == "game":
            res = _game(ctx)
        elif sec == "forms":
            res = _forms(ctx, seed, samples)
        elif sec == "vectors":
            res = _vectors(ctx)
        elif sec == "rules":
            res = _rules(ctx, seed)
        elif sec == "redefinitions":
            res = _redefinitions(ctx, seed)
        elif sec == "conformance":
            res = _conformance(ctx, seed, langs)
        elif sec == "functions":
            res = _functions(ctx, seed, langs)
        elif sec == "proofs":
            from ..emit import proofs
            res = proofs.check_rules(ctx)
        elif sec == "selfcheck":
            from . import selfcheck
            res = selfcheck.run(ctx, seed)
        else:
            from . import selfcheck
            res = selfcheck.portability(seed)
        timings[sec] = round(time.perf_counter() - t0, 2)
        report["sections"][sec] = res
    report["timings_s"] = timings
    from ..kernel import resources
    report["peak_memory_mb"] = round(resources.peak_mb(), 1)
    report["status"] = "fail" if any(r.get("status") == "fail" for r in report["sections"].values()) else "pass"
    ctx.save_state("last_verify", report)
    if record:
        record_results(ctx, report)
    return report


def record_results(ctx: Ctx, report: dict) -> int:
    """Write each card's verdict into its ``verification`` field (versioned)."""
    n = 0
    date = report["started"][:10]
    secs = report["sections"]
    updates: dict[str, dict] = {}
    for q, r in (secs.get("redefinitions") or {}).get("cards", {}).items():
        updates.setdefault(q, {})["numeric"] = {k: r.get(k) for k in ("verdict", "seed", "valid_points", "symbolic",
                                                                      "counterexample", "examples") if k in r}
    for q, r in (secs.get("rules") or {}).get("cards", {}).items():
        updates.setdefault(q, {})["numeric"] = r
    for q, r in (secs.get("proofs") or {}).get("rules", {}).items():
        updates.setdefault(q, {})["proof"] = r
    for q, r in (secs.get("forms") or {}).get("cards", {}).items():
        updates.setdefault(q, {})["forms"] = {k: {kk: vv for kk, vv in v.items() if kk != "detail"}
                                              for k, v in r["forms"].items()}
    for q, r in (secs.get("vectors") or {}).get("cards", {}).items():
        updates.setdefault(q, {})["vectors"] = {"status": r["status"],
                                                "forms": {k: v["status"] for k, v in r["forms"].items()}}
    for q, upd in updates.items():
        card = ctx.store.get(q)
        if card is None:
            continue
        data = dict(card)
        ver = dict(data.get("verification") or {})
        ver.update(upd)
        ver["date"] = date
        data["verification"] = ver
        if card.registry == "redefinition":
            verdict = upd.get("numeric", {}).get("verdict")
            data["status"] = {"verified": "healthy", "proved_symbolic": "healthy", "refuted": "broken"}.get(
                verdict, "suspect")
        _, changed = ctx.store.save(data, layer=card.layer, category=card.registry)
        n += changed
    return n
