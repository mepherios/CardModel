"""pipeline — every transformation runs every stage that applies to its input, or says why not (law CM50).

The path from an input to an output (``cardmodel translate``, and the engines behind ``improve``, ``run`` and
``analyse``) was hand-written: each command called the engines its author had in mind, and an engine the main
path did not call was silently absent from it. This module makes the path a registry. A ``stage`` card is a
conditional, like a law (docs/FOUNDATIONS.md D5): "for every input whose profile satisfies H, run this step".
H names facts of the input's *profile* (its sorts, its shape, what earlier stages found, what the host has), the
runner evaluates H for every stage on every input, and the set of stages that run is computed, never remembered.
Each card names the function in ``STAGES`` that runs it, the engines that function reaches, the definitions and
rules of FOUNDATIONS.md it rests on, the stages it needs, and its group:

  terms       the input as a term of T_Σ(X) (D3): the lift, the profile (sorts D1, shape), the reference (its
              value in the model M on seeded inputs, D4, and the function card that holds them)
  identity    what the term is: canon_E and its hash (D6, D7), the identity under its named relation (D9), the
              content read from the canonical term (D11), the positional code (D12), the real normal form, the
              behaviour form (a recurrence), each labelled with the relation it is canonical under (A4)
  evidence    what the claims are worth (D10): the class and the theorem that sizes its witness (CM46), a sized
              witness that the canonical term equals the original, the obligations of partial ops and the
              divergence laws of the targets (D14, A6), run in every runner on request
  optimize    a cheaper equal term with its certificate (D8, A5): rule chains and saturation, algorithm and
              algebra substitutions labelled with their tier, costs measured on this host on request (CM09)
  targets     the term read in other models (D14): every language card's form, run and compared (CM16, CM17),
              the source's own toolchain against the lift, the native path through ctypes, mathematical notation,
              and the round trip lift(emit_L(f)) = f for every target with a frontend
  record      the cards the work produces (A7, CM44): the function card with its identity, Gödel record, class,
              certificates and the record of this run, saved on request

A run's record has one entry per stage per function: ``ran`` with its evidence; ``skipped`` with the fact that
failed (``needs straight_line``) or the stage it waited on; ``not_requested`` with the option that would ask for
it; ``unavailable`` with what the host lacks; ``failed`` with the exception and where. A fact's name says what
it is: ``opt:deep`` is an option, ``host:compiler`` a probe of this machine, the rest are read from the IR or set
by an earlier stage (``reduced`` by ``canon``, ``class_known`` by ``class``). ``coverage`` checks the registry
itself (``cardmodel pipeline check``, the ``pipeline`` verify section): every card names a function the program
has and the reverse; every engine under ``cardmodel/engines`` is reached by a stage or named outside the pipeline
with its reason; each card's ``engines`` are exactly what its function imports; every ``needs`` points at an
earlier stage; every cited definition or rule exists in FOUNDATIONS.md; and on the fixture every stage applies
to at least one function when every option and host fact is granted, so no hypothesis is dead.

Honest limits (L1): a ``ran`` entry says the engine ran on this input; the evidence has the tier that engine
gives it (a witness is a sample, a canonical form is an identity under the laws that fired, a sized witness is
a proof only inside its class). The profile's facts are read from the IR, so a hypothesis can hold for an
input on which the engine then finds nothing; that is a ``ran`` with empty evidence, never a pass. Coverage is
of stages and engines, not of lines: a stage that reaches a module may use one function of it. The unit is one
function of one source file; a whole tree (``lift-sweep``, ``learn``), a card-language program (``run``) and a
ROM (``emu``) are other inputs with their own paths, named outside this registry with that reason.
"""
from __future__ import annotations

import ast
import copy
import random
import re
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path

from . import values as V
from .context import Ctx

REFERENCE = "python"            # the language whose own run is the reference (ARCHITECTURE.md: Python semantics)
STATUSES = ("ran", "skipped", "not_requested", "unavailable", "failed")
GROUPS = ("terms", "identity", "evidence", "optimize", "targets", "record")
OPTIONS = ("deep", "measure", "save")
HOST_FACTS = ("compiler",)
# facts the profile stage reads from the IR, and the ones later stages set (each named with the stage that sets it)
PROFILE_FACTS = ("lifted", "pure_function", "straight_line", "has_loops", "recursive", "has_calls", "int_sorted",
                 "float_present", "list_present", "bool_present", "one_int_param", "partial_ops",
                 "source_is_reference")
SET_FACTS = {"canonical": "canon", "reduced": "canon", "class_known": "class", "verified": "witness_targets"}
FACTS = (*PROFILE_FACTS, *SET_FACTS, *(f"opt:{o}" for o in OPTIONS), *(f"host:{h}" for h in HOST_FACTS))
MAX_NODES = 3000


class Unavailable(Exception):
    """The stage cannot run on this host (the reason says what is missing)."""


@dataclass
class Job:
    """One function of one source file on its way through the stages."""
    name: str
    lang: str
    source: str
    label: str
    seed: int
    lifted: list                       # every lifted function of the file (callees resolve through it)
    lf: object                         # this function's Lifted record (ok / ir / reasons / source)
    langs: list | None = None
    options: dict = field(default_factory=dict)
    samples: int = 24
    facts: dict = field(default_factory=dict)
    card: dict | None = None
    module: dict | None = None
    fn: dict | None = None
    term: list | None = None
    canon: dict | None = None
    stages: dict = field(default_factory=dict)
    ref: object = None                 # the reference callable (the original source, or the IR in M)
    report: dict | None = None         # translate.verify_function's report (the translate CLI prints it)

    def evidence(self, stage: str, key: str, default=None):
        e = self.stages.get(stage) or {}
        return e.get(key, default) if e.get("status") == "ran" else default


class Runner:
    """The tables every stage shares, loaded once per run."""

    def __init__(self, ctx: Ctx):
        self.ctx = ctx
        self._rules = self._costs = self._egraph = self._ledger = None

    @property
    def rules(self):
        if self._rules is None:
            from .search import load_rules
            self._rules = load_rules(self.ctx.store)
        return self._rules

    @property
    def costs(self):
        if self._costs is None:
            from .search import op_costs
            self._costs = op_costs(self.ctx.store)
        return self._costs

    @property
    def egraph_rules(self):
        if self._egraph is None:
            from .egraph import rules_from_cards
            self._egraph = rules_from_cards(self.ctx.store)
        return self._egraph

    @property
    def ledger(self):
        if self._ledger is None:
            from . import godel as G
            self._ledger = G.ledger(self.ctx.store)
        return self._ledger


# -- the stages (terms) -----------------------------------------------------------------------------------------
def lift(ctx: Ctx, job: Job, run: Runner) -> dict:
    """The function as a term of T_Σ(X) through its language card's frontend (D3), or the gap with its reasons."""
    from . import frontends
    card = ctx.store.get(f"language/{job.lang}")
    out = {"frontend": (card or {}).get("frontend"), "lifted": bool(job.lf.ok),
           "readable_languages": len(frontends.frontend_languages(ctx.store))}
    if job.lf.ok:
        job.module = _module_for(job.name, job.lifted)
        job.fn = next(f for f in job.module["functions"] if f["name"] == job.name)
        out["functions_in_module"] = len(job.module["functions"])
        job.facts["lifted"] = True
    else:
        out["reasons"] = list(job.lf.reasons)
        job.facts["lifted"] = False
    return out


def _module_for(name: str, lifted: list) -> dict:
    from .frontend_python import module_for
    return module_for(name, lifted)


def _single_return(fn: dict):
    body = (fn or {}).get("body") or []
    return body[0]["value"] if len(body) == 1 and body[0].get("k") == "return" else None


def _var_sorts(fn: dict) -> dict:
    out = {p["name"]: p.get("type") for p in (fn or {}).get("params") or []}
    out.update((fn or {}).get("locals") or {})
    return out


def profile(ctx: Ctx, job: Job, run: Runner) -> dict:
    """The facts every hypothesis reads: the sorts that occur (D1) and the shape of the function's system of
    equations (D3: a single term, loops as fixpoints, recursion, calls, partial ops)."""
    from . import sorts
    from .analyse import PARTIAL
    from .ir import elem_type, ops_used, walk_expr, walk_stmts
    fn, module = job.fn, job.module
    params = fn.get("params") or []
    types = [p.get("type") for p in params] + [fn.get("returns")] + list((fn.get("locals") or {}).values())
    present = set()
    for t in types:
        if t is None:
            continue
        et = elem_type(t)
        if et is not None:
            present.add("list")
            t = et
        s = sorts.sort_name(t)
        if s is not None:
            present.add(sorts.base(s) or s)
    kinds = {s.get("k") for s in walk_stmts(fn.get("body") or [])}
    calls, recursive = set(), False
    for s in walk_stmts(fn.get("body") or []):
        for key in ("value", "cond", "start", "stop", "step", "index"):
            if isinstance(s.get(key), list):
                for e in walk_expr(s[key]):
                    if isinstance(e, list) and e and e[0] == "CALL":
                        calls.add(e[1])
                        recursive = recursive or e[1] == fn["name"]
    machine = bool(module.get("globals") or module.get("arrays") or fn.get("returns") == "void")
    used = ops_used(fn)
    job.term = _single_return(fn)
    facts = {
        "lifted": True, "pure_function": not machine, "straight_line": job.term is not None,
        "has_loops": bool(kinds & {"for_range", "while"}), "recursive": recursive,
        "has_calls": bool(calls - {fn["name"]}),
        "int_sorted": bool(params) and all(p.get("type") == "int" for p in params) and fn.get("returns") == "int",
        "float_present": "float" in present, "list_present": "list" in present, "bool_present": "bool" in present,
        "one_int_param": len(params) == 1 and params[0].get("type") == "int" and fn.get("returns") == "int",
        "partial_ops": bool(used & set(PARTIAL)), "source_is_reference": job.lang == REFERENCE,
    }
    job.facts.update(facts)
    return {"sorts": sorted(present), "statements": sorted(k for k in kinds if k), "ops": sorted(used),
            "calls": sorted(calls), "facts": {k: v for k, v in facts.items() if v}}


def reference(ctx: Ctx, job: Job, run: Runner) -> dict:
    """The function's value in M (D4): generators narrowed until the reference terminates, known-answer vectors
    from the original source (or the IR when the source is not the reference language), and the function card
    that carries them with a form for every language card (translate.function_card)."""
    from . import translate
    job.card = translate.function_card(ctx, job.name, job.lifted, job.label, seed=job.seed, samples=job.samples,
                                       lang=job.lang)
    fid = job.card["verification"]["lift_fidelity"]
    if job.lang == REFERENCE:
        job.ref, _src = translate.python_reference(job.module, job.lifted)
    else:
        job.ref, _src = translate.ir_reference(ctx, job.module, job.lifted)
    return {"card": job.card["name"], "vectors": len(job.card["vectors"]), "generators": job.card["generators"],
            "lift_fidelity": fid, "reference": "the original source" if job.lang == REFERENCE else "the IR in M",
            "verdict": "pass" if not fid.get("mismatched") else "fail"}


# -- the stages (identity) --------------------------------------------------------------------------------------
def canon(ctx: Ctx, job: Job, run: Runner) -> dict:
    """canon_E of the function's term by equality saturation at the term's sorts (D6, D7, A3): the cheapest
    member of its class, the laws that fired (its certificate) and its hash."""
    from . import egraph as E
    from .exprs import to_text
    from .search import expr_cost
    try:
        r = E.canonical(job.term, run.egraph_rules, run.costs, _var_sorts(job.fn), ctx.ops, max_iter=6,
                        max_nodes=MAX_NODES)
    except ValueError as exc:
        job.facts["canonical"] = job.facts["reduced"] = False
        return {"canonical": None, "why": str(exc)}
    reduced = r["term"] != job.term
    job.canon = {"status": "canonical", "term": r["term"], "hash": r["hash"], "cost": r["cost"],
                 "by": "method/saturate", "certificate": {"equalities": list(r["fired"])[:12],
                                                          "saturated": r["saturated"], "iterations": r["iterations"]}}
    job.facts["canonical"], job.facts["reduced"] = True, reduced
    return {"canonical": to_text(r["term"]), "hash": r["hash"], "cost": r["cost"],
            "lifted_cost": expr_cost(job.term, run.costs), "reduced": reduced, "equalities": list(r["fired"])[:12],
            "saturated": r["saturated"], "iterations": r["iterations"], "nodes": r["nodes"]}


def identity(ctx: Ctx, job: Job, run: Runner) -> dict:
    """The function's identity under a named relation (D7, D9, A4): the hash of its canonical term under the
    laws when saturation reached one, else of its term or whole IR under syntax; beside it the alpha form."""
    from . import numbering
    from .equivalence import RELATIONS
    from .exprs import to_text
    from .sources import identity as ident
    canon_rec = job.canon or {}
    rec = ident(canon_rec, job.term, job.fn)
    alpha = None
    t = canon_rec.get("term") if canon_rec else job.term
    if t is not None:
        alpha = to_text(numbering.canonical(t))
    job.card["identity"] = rec
    return {**rec, "relation": RELATIONS[rec["under"]], "alpha": alpha}


def content(ctx: Ctx, job: Job, run: Runner) -> dict:
    """The Gödel record (D11, D12, CM45): content read from the canonical term where there is one (A4), else from
    the IR with ``read_from`` saying so; a sparse vector over the ledger, the positional code when it is small."""
    from . import godel as G
    canon_rec = job.canon or {}
    if canon_rec.get("term") is not None:
        c, read_from, term = G.term_content(canon_rec["term"], ctx.ops), "its canonical term (method/saturate)", \
            canon_rec["term"]
    else:
        c, read_from, term = G.module_content(job.module, ctx.ops), \
            "its IR (a loop or several statements: no canonical term yet)", job.term
    rec = G.stored(c, read_from, run.ledger, ctx.ops, term)
    job.card["godel"] = rec
    return {"content": dict(c), "read_from": read_from, "basis": rec["basis"],
            "missing_atoms": rec.get("missing_atoms", []), "structural_digits": rec.get("structural_digits"),
            "structural": rec.get("structural") is not None}


def real(ctx: Ctx, job: Job, run: Runner) -> dict:
    """The term's normal form over ℝ (D9 ``real``): equal normal forms mean equal rational functions, which is
    sound for integer polynomials and an approximation on floating point, so it runs on int-sorted terms."""
    from . import realnorm
    from .exprs import to_text
    try:
        nf = realnorm.canonical(job.term)
    except (ValueError, ZeroDivisionError, KeyError, TypeError) as exc:
        return {"normal_form": None, "why": f"outside realnorm's fragment: {exc}", "under": "real"}
    job.card.setdefault("identities", {})["real"] = {"key": realnorm.key(job.term), "under": "real"}
    return {"normal_form": to_text(nf), "key": realnorm.key(job.term), "under": "real"}


def behaviour(ctx: Ctx, job: Job, run: Runner) -> dict:
    """The behaviour form of a one-integer function (D9 ``behaviour``, CM31): the linear recurrence it satisfies
    (Berlekamp–Massey, checked on unused terms), its canonical description and Gödel number."""
    from . import funcalg as FA
    for start in (0, 1):
        try:
            form = FA.fit(job.ref, start)
        except Exception as exc:  # noqa: BLE001 -- a reference that fails to run on the sequence has no form here
            return {"form": None, "why": f"{type(exc).__name__}: {exc}", "under": "behaviour"}
        if form is not None:
            rec = {"kind": form.kind(), "canonical": form.describe(), "order": form.order, "start": start,
                   "checked": form.checked, "godel": str(form.godel()), "under": "behaviour"}
            job.card.setdefault("identities", {})["behaviour"] = rec
            return {"form": rec, "under": "behaviour"}
    return {"form": None, "why": f"no linear recurrence of order <= {FA.MAX_ORDER} fits", "under": "behaviour"}


# -- the stages (evidence) --------------------------------------------------------------------------------------
def _class_text(sh: dict) -> str:
    parts = []
    for s in sh.get("segments") or []:
        where = f"[{'-inf' if s['lo'] is None else s['lo']}, {'inf' if s['hi'] is None else s['hi']}]"
        parts.append(f"{where}: " + ("polynomial" if s["kind"] == "poly" else f"C-finite of order <= {s['order']}"))
    return (f"along {sh['n']}: " if sh.get("n") else "") + "; ".join(parts)


def class_(ctx: Ctx, job: Job, run: Runner) -> dict:
    """The function's class read from its IR (D10, CM46): polynomial, C-finite along one input, guarded regions;
    the class names the theorem that sizes a finite witness, so equality claims about it can reach tier proof."""
    from . import tiers
    sh = tiers.shape(job.fn)
    job.facts["class_known"] = bool(sh.get("ok"))
    rec = {"known": bool(sh.get("ok")), "class": _class_text(sh) if sh.get("ok") else None,
           "why": None if sh.get("ok") else sh.get("why"),
           "tier_reachable": "proof" if sh.get("ok") else "sample"}
    job.card["class"] = rec
    return rec


def sized_witness(ctx: Ctx, job: Job, run: Runner) -> dict:
    """The canonical term equals the original at tier proof (D10): both forms' classes size the witness, and
    every point agrees; a disagreement refutes the laws that fired, which is a finding, never hidden."""
    from . import tiers
    from .codegen import EmitGap, emit_module
    fn = copy.deepcopy(job.fn)
    fn["body"] = [{"k": "return", "value": job.canon["term"]}]
    module = {"entry": job.name, "functions": [fn]}
    try:                 # both sides in the reference language's form of the IR, so the source language is immaterial
        code = emit_module(ctx.store, ctx.ops, REFERENCE, module)
        original = emit_module(ctx.store, ctx.ops, REFERENCE, {**job.module, "entry": job.name})
    except EmitGap as exc:
        return {"verdict": None, "why": f"the term has no form in the reference language: {exc}"}
    ref_form = {"name": "lifted", "entry": job.name, "code": original, "lang": REFERENCE}
    form = {"name": "canonical", "entry": job.name, "code": code, "lang": REFERENCE}
    r = tiers.prove(ctx, {"name": job.name, "precondition": None}, ref_form, form)
    if r is None:
        return {"verdict": None, "why": "no class sizes a witness for both forms (it stays sampled)"}
    job.card.setdefault("certificates", []).append({"claim": "canonical term == lifted term", **r})
    out = {"verdict": r["status"], "tier": r["tier"], "points": r.get("points"), "theorems": r.get("theorems")}
    if r["status"] == "refuted":
        out.update(at=r.get("at"), values=r.get("values"))
    return out


def divergence(ctx: Ctx, job: Job, run: Runner) -> dict:
    """The obligations of every partial op under its path condition and the divergence laws of the targets (D14,
    A6), on the reference's instrumented runs: proved by a guard, discharged by the domain, sampled, or open with
    the first input the reference refuses; findings predicted here, witnessed by ``divergence_witness``."""
    from . import analyse as A
    a = A.analyse_card(ctx, job.card, run=False, seed=job.seed)
    obls = {s: sum(1 for o in a.obligations if o["status"] == s) for s in ("proved", "domain", "sampled", "open")}
    laws = sorted({f["law"] for f in a.findings})
    job.card["analysis"] = {"obligations": a.obligations, "laws": laws, "equations": a.math}
    return {"obligations": obls, "open": [{"at": o["at"], "claim": o.get("claim") or o.get("text"),
                                           "counterexample": o.get("counterexample")}
                                          for o in a.obligations if o["status"] == "open"][:6],
            "laws": laws, "findings": len(a.findings), "in_domain": sum(1 for f in a.findings if f["in_domain"]),
            "equations": a.math}


def divergence_witness(ctx: Ctx, job: Job, run: Runner) -> dict:
    """Every predicted divergence run in every available runner (each language card and its optimization or
    checking variants) and compared with the reference: witnessed, guarded or still predicted."""
    from . import analyse as A
    pool = A.runners(ctx, job.langs)
    if not pool:
        raise Unavailable("no runner is available on this host")
    a = A.analyse_card(ctx, job.card, run=True, seed=job.seed, pool=pool)
    verdicts = {v: sum(1 for f in a.findings if f["verdict"] == v) for v in ("witnessed", "guarded", "predicted")}
    job.card.setdefault("analysis", {})["findings"] = [{k: f[k] for k in ("law", "at", "verdict", "in_domain",
                                                                           "differs", "agrees")}
                                                        for f in a.findings]
    return {"runners": a.runners, "verdicts": verdicts,
            "latent": [{"law": f["law"], "at": f["at"], "differs": f["differs"]}
                       for f in a.findings if f["verdict"] == "witnessed" and f["in_domain"]][:8]}


# -- the stages (optimize) --------------------------------------------------------------------------------------
def _agrees_on_vectors(ctx: Ctx, module: dict, card: dict) -> tuple[int, dict | None]:
    """The module reproduces the card's vectors in M; the first disagreement, if any."""
    from .ir import Interpreter, IRError, StepLimit
    interp = Interpreter(module, ctx.ops, step_limit=200_000)
    checked = 0
    for v in card.get("vectors") or []:
        try:
            got = interp.call(module["entry"], list(v["args"]))
        except (IRError, StepLimit, ArithmeticError, ValueError, RecursionError, OverflowError):
            continue
        if not V.same(v["out"], got):
            return checked, {"args": v["args"], "expected": v["out"], "got": got}
        checked += 1
    return checked, None


def rewrite(ctx: Ctx, job: Job, run: Runner) -> dict:
    """Every int-sorted expression replaced by its cheapest equivalent under the rule cards and saturation (D8,
    A3, CM25), the chain of laws as the certificate, the result verified against the vectors in M."""
    from .improve import rewrite_candidate
    cand, changes = rewrite_candidate(ctx, job.fn, run.rules, run.costs, run.egraph_rules)
    if cand is None:
        return {"changes": [], "verdict": None, "why": "no int-sorted expression has a cheaper equivalent"}
    module = {**job.module, "functions": [cand if f["name"] == job.name else f for f in job.module["functions"]]}
    checked, bad = _agrees_on_vectors(ctx, module, job.card)
    rec = {"changes": [{"from": a, "to": b, "certificate": list(c)} for a, b, c in changes],
           "verdict": "fail" if bad else ("pass" if checked else "no_inputs"), "checked": checked}
    if bad:
        rec["counterexample"] = bad
    job.card.setdefault("certificates", []).append({"claim": "rewritten function == source", "kind": "rewrite",
                                                    "tier": "sample", **rec})
    return rec


def algorithm(ctx: Ctx, job: Job, run: Runner) -> dict:
    """Labelled substitutions (A5): algorithm cards whose reference form agrees with the function on probe inputs
    (exactly or as an affine image), and a closed or matrix-power form from the function's own recurrence; each
    carries its tier (sample) and precondition, and is never presented as a rewrite."""
    from .improve import algebra_candidates, algorithm_candidates
    rng = random.Random(job.seed)
    inputs = [list(v["args"]) for v in job.card.get("vectors") or []]
    inputs += [list(a) for a in V.inputs(job.card.get("generators") or [], 24, rng, edge=False)]
    found = algorithm_candidates(ctx, job.fn, job.ref, inputs)
    if job.facts.get("one_int_param"):
        found += algebra_candidates(ctx, job.fn, job.ref)
    subs = [{k: c.get(k) for k in ("kind", "card", "form", "scale", "shift", "complexity", "precondition",
                                   "canonical", "godel") if c.get(k) is not None} | {"tier": "sample"}
            for c in found]
    job.card["substitutions"] = subs
    return {"substitutions": subs, "probe_inputs": len(inputs)}


def measure(ctx: Ctx, job: Job, run: Runner) -> dict:
    """Costs measured on this host (CM09, D8): every available generated form run on the vectors, the per-call
    time from the slope of two run lengths; the fastest target and each one's factor against it."""
    from . import optimize
    rows = optimize.measure_function(ctx, job.card, langs=job.langs, seed=job.seed)
    timed = sorted((r for r in rows if r.get("median_ns")), key=lambda r: r["median_ns"])
    if not timed:
        return {"targets": [], "why": "no form gave a resolved timing"}
    fastest = timed[0]["median_ns"]
    ranked = [{"lang": r["lang"], "form": r["form"], "ns": round(r["median_ns"], 1),
               "x_vs_fastest": round(r["median_ns"] / fastest, 2) if fastest else None,
               "resolved": r.get("resolved", True)} for r in timed]
    job.card["measured"] = {"host": optimize.host_id(), "targets": ranked, "rows": rows}
    return {"host": optimize.host_id(), "targets": ranked}


# -- the stages (targets) ---------------------------------------------------------------------------------------
def emit(ctx: Ctx, job: Job, run: Runner) -> dict:
    """The term read in every language card with codegen (D14, CM16): one form per card, and the gap (an op the
    card has no template for) named per language instead of patched."""
    from .codegen import EmitGap, emit_module
    forms = {f["lang"]: len(f["code"]) for f in job.card["forms"] if f.get("generated")}
    gaps = dict(job.card.get("emit_gaps") or {})
    for lang in ctx.codegen_languages():               # the card's forms re-derived: emission is deterministic
        if lang in forms:
            try:
                emit_module(ctx.store, ctx.ops, lang, job.module)
            except EmitGap as exc:
                gaps[lang] = str(exc)
    return {"languages": sorted(forms), "gaps": gaps}


def witness_targets(ctx: Ctx, job: Job, run: Runner) -> dict:
    """Every generated form compiled and run on the vectors plus fresh seeded inputs and compared with the
    reference (CM17, tier sample); fixed-width targets only on inputs that fit (D14's domain)."""
    from . import translate
    rep = translate.verify_function(ctx, job.card, langs=job.langs, seed=job.seed, samples=max(8, job.samples // 2))
    job.report = rep
    st = {k: v["status"] for k, v in rep["languages"].items()}
    bad = sorted(k for k, s in st.items() if s in ("fail", "error"))
    job.facts["verified"] = not bad and rep["inputs"] > 0 and not rep["lift_mismatches"]
    job.card["verification"]["run"] = {k: v for k, v in rep.items() if k != "languages"}
    return {"inputs": rep["inputs"], "lift_mismatches": rep["lift_mismatches"], "languages": st,
            "agreeing": rep["agreeing_languages"], "verdict": "fail" if bad or not rep["inputs"] else "pass",
            "report": rep}


def witness_source(ctx: Ctx, job: Job, run: Runner) -> dict:
    """The lift itself witnessed: the original source run by its own toolchain on the vectors and seeded inputs,
    against the IR in M (CM17); unavailable, never silent, when the toolchain is missing."""
    from . import frontends
    rows = [v["args"] for v in job.card["vectors"]] + frontends.sample_inputs(job.card["ir"], 12, job.seed)
    wit = frontends.witness_source(ctx, job.lang, job.source, job.card["ir"], rows, getattr(job.lf, "src_types", None),
                                   getattr(job.lf, "src_labels", None))
    job.card["verification"]["source_witness"] = wit
    if wit["status"] in ("unavailable", "no_harness"):
        raise Unavailable(wit.get("reason") or f"no toolchain or harness for {job.lang}")
    out = {("witness" if k == "status" else "why" if k == "reason" else k): v for k, v in wit.items()}
    return {**out, "verdict": "fail" if wit["status"] == "fail" else "pass" if wit["status"] == "pass" else None}


def native(ctx: Ctx, job: Job, run: Runner) -> dict:
    """The native path (Phase E3): the function's compiled form called through ctypes inside the box of verified
    inputs, the original outside it; the wrapper is run on the vectors and compared with the reference."""
    from ..machine import native as N
    from . import native as NV
    from .improve import rename
    try:
        engine_lang = N.resolve_engine(ctx, "native")
    except Exception as exc:  # noqa: BLE001 -- no compiled engine language here: the stage is unavailable
        raise Unavailable(str(exc)) from exc
    inputs = [list(v["args"]) for v in job.card.get("vectors") or []]
    cand, why = NV.candidate(ctx, job.fn, job.module, inputs, job.lf.source, rename)
    if cand is None:
        return {"candidate": None, "why": why, "engine": engine_lang}
    ns: dict = {"__name__": "cardmodel_native_check"}
    exec(compile(cand["src"], "<native wrapper>", "exec"), ns)  # noqa: S102 -- the wrapper the model just emitted
    fn, checked, bad = ns[job.name], 0, None
    for v in job.card.get("vectors") or []:
        try:
            got = fn(*v["args"])
        except Exception as exc:  # noqa: BLE001 -- a wrapper that raises where the reference does not: a finding
            bad = {"args": v["args"], "expected": v["out"], "error": f"{type(exc).__name__}: {exc}"}
            break
        if not V.same(v["out"], got):
            bad = {"args": v["args"], "expected": v["out"], "got": got}
            break
        checked += 1
    rec = {"candidate": {"card": cand["card"], "form": cand["form"], "box": cand["box"], "lib": cand["lib"]},
           "engine": engine_lang, "checked": checked, "verdict": "fail" if bad else "pass"}
    if bad:
        rec["counterexample"] = bad
    job.card.setdefault("certificates", []).append({"claim": "native form == source inside its box",
                                                    "kind": "native", "tier": "sample", **rec})
    return rec


def notation(ctx: Ctx, job: Job, run: Runner) -> dict:
    """Mathematical notation as a target (D3: a concrete syntax that adds no meaning): the function written as
    equations, read back, and compared with the IR on the vectors."""
    from . import mathlang
    from .matrix import math_round_trip
    r = math_round_trip(ctx, job.card)                 # lift(emit(f)) against f on the vectors, no toolchain
    try:
        text = mathlang.emit_module(job.card["ir"])
    except Exception as exc:  # noqa: BLE001 -- a function the notation cannot write: the round trip says which gap
        text = None
        r.setdefault("reason", str(exc))
    job.card["notation"] = text
    out = {("outcome" if k == "status" else "why" if k == "reason" else k): v for k, v in r.items()}
    return {**out, "notation": text,
            "verdict": "fail" if r["status"] == "fail" else "pass" if r["status"] == "pass" else None}


def round_trip(ctx: Ctx, job: Job, run: Runner) -> dict:
    """lift ∘ emit_L ≈ id on the vectors for every target that also has a frontend (D14: a frontend is a partial
    inverse of codegen); no toolchain is needed, the frontends read the emitted text."""
    from . import matrix as M
    out = {}
    for target in sorted(M.FRONTENDS):
        fe = M.FRONTENDS[target]
        if fe.lift_text is None or target not in (job.langs or ctx.codegen_languages()):
            continue
        if target not in ctx.codegen_languages():
            continue
        out[target] = M.round_trip(ctx, job.card, target)
    bad = sorted(t for t, r in out.items() if r.get("status") in ("fail", "differ"))
    return {"targets": {t: r.get("status") for t, r in out.items()},
            "verdict": "fail" if bad else ("pass" if out else None), "differing": bad}


# -- the stages (record) ----------------------------------------------------------------------------------------
def record(ctx: Ctx, job: Job, run: Runner) -> dict:
    """The function card with everything this run found (A7, CM44): its identity, Gödel record, class,
    certificates and the stage record; healthy when three or more models agree and the lift is faithful; saved
    to the store on request."""
    card = job.card
    card["pipeline"] = {n: {k: v for k, v in e.items() if k in ("status", "reason", "verdict")}
                        for n, e in job.stages.items()}
    agreeing = job.evidence("witness_targets", "agreeing", [])
    card["status"] = "healthy" if len(agreeing) >= 3 and not card["verification"]["lift_fidelity"].get("mismatched") \
        else "suspect"
    saved = None
    if job.options.get("save"):
        st, _ = ctx.store.save(card, category="function")
        saved = f"{st.registry}/{st.name}" if hasattr(st, "registry") else card["name"]
    return {"card": card["name"], "health": card["status"], "saved": saved, "fields": sorted(card)}


STAGES = {f.__name__.rstrip("_"): f for f in (lift, profile, reference, canon, identity, content, real, behaviour,
                                              class_, sized_witness, divergence, divergence_witness, rewrite,
                                              algorithm, measure, emit, witness_targets, witness_source, native,
                                              notation, round_trip, record)}


# -- the registry and the runner --------------------------------------------------------------------------------
def stages(ctx: Ctx) -> list[dict]:
    """The stage cards in order: name, group, order, hypothesis, needs, run, engines, foundations."""
    out = []
    for c in ctx.store.cards("stage"):
        out.append({"name": c.name, "group": c.get("group"), "order": c.get("order", 999), "run": c.get("run", c.name),
                    "when": list(c.get("when") or []), "unless": list(c.get("unless") or []),
                    "needs": list(c.get("needs") or []), "engines": list(c.get("engines") or []),
                    "foundations": list(c.get("foundations") or []), "laws": list(c.get("laws") or []),
                    "scope": c.get("scope", "function"), "statement": c.get("statement", "")})
    return sorted(out, key=lambda s: (s["order"], s["name"]))


def host_facts(ctx: Ctx) -> dict:
    from . import native as NV
    return {"host:compiler": NV.compiler() is not None}


def applies(stage: dict, facts: dict) -> tuple[str, str]:
    """(status, reason) of a stage's hypothesis on ``facts``: ``ran`` when every ``when`` fact holds and no
    ``unless`` fact does; else the first failing fact decides: an option is ``not_requested``, a host fact
    ``unavailable``, any other ``skipped``."""
    for f in stage["when"]:
        if not facts.get(f):
            if f.startswith("opt:"):
                return "not_requested", f"option --{f[4:]}"
            if f.startswith("host:"):
                return "unavailable", f"this host has no {f[5:]}"
            return "skipped", f"needs {f}"
    for f in stage["unless"]:
        if facts.get(f):
            return "skipped", f"not when {f}"
    return "ran", ""


RESERVED = ("status", "reason", "seconds")      # the runner's keys of an entry; a stage's evidence never sets them


def _entry(status: str, reason: str = "", evidence: dict | None = None) -> dict:
    e = {"status": status}
    if reason:
        e["reason"] = reason
    e.update({k: v for k, v in (evidence or {}).items() if k not in RESERVED})
    return e


def run_job(ctx: Ctx, job: Job, plan: list[dict], run: Runner, only: list[str] | None = None) -> dict:
    """Every stage of ``plan`` on one function, in order; one entry per stage, each with a status and a reason."""
    for s in plan:
        name = s["name"]
        if only and name not in only:
            job.stages[name] = _entry("not_requested", "--only did not name it")
            continue
        waiting = next((n for n in s["needs"] if (job.stages.get(n) or {}).get("status") != "ran"), None)
        if waiting is not None:
            w = job.stages.get(waiting) or {"status": "missing", "reason": "no such stage ran"}
            job.stages[name] = _entry("skipped", f"needs stage {waiting} ({w['status']}: {w.get('reason', '')})")
            continue
        status, reason = applies(s, job.facts)
        if status != "ran":
            job.stages[name] = _entry(status, reason)
            continue
        fn = STAGES.get(s["run"])
        t0 = time.perf_counter()
        if fn is None:
            job.stages[name] = _entry("failed", f"the program has no stage function {s['run']!r}")
            continue
        try:
            ev = fn(ctx, job, run)
            e = _entry("ran", evidence=ev)
        except Unavailable as exc:
            e = _entry("unavailable", str(exc))
        except Exception as exc:  # noqa: BLE001 -- a crashed stage is a finding of this run, not its end
            tb = traceback.extract_tb(exc.__traceback__)[-1]
            e = _entry("failed", f"{type(exc).__name__}: {exc} ({Path(tb.filename).name}:{tb.lineno})")
        e["seconds"] = round(time.perf_counter() - t0, 3)
        job.stages[name] = e
    return job.stages


def _summary(entries: dict) -> dict:
    counts = {s: sum(1 for e in entries.values() if e["status"] == s) for s in STATUSES}
    problems = []
    for n, e in entries.items():
        if e["status"] == "failed":
            problems.append(f"{n}: {e.get('reason')}")
        elif e["status"] == "ran" and e.get("verdict") in ("fail", "refuted"):
            problems.append(f"{n}: {e['verdict']}")
        elif e["status"] != "ran" and not e.get("reason"):
            problems.append(f"{n}: {e['status']} without a reason (CM50)")
    return {"counts": counts, "problems": problems}


def run_source(ctx: Ctx, source: str, lang: str, label: str = "<source>", names: list[str] | None = None,
               langs: list[str] | None = None, seed: int | None = None, only: list[str] | None = None,
               options: dict | None = None, samples: int = 24, progress=None) -> dict:
    """Every function of ``source`` through every stage that applies. The record: one entry per stage per function,
    the per-function summary, and the run's coverage counts."""
    from . import frontends
    seed = V.fresh_seed() if seed is None else seed
    options = {k: bool(v) for k, v in (options or {}).items()}
    plan = stages(ctx)
    runner = Runner(ctx)
    host = host_facts(ctx)
    lifted = frontends.lift(ctx, source, lang)
    rec = {"seed": seed, "source": label, "lang": lang, "options": options, "langs": langs,
           "stages": [s["name"] for s in plan], "functions": {}}
    for lf in lifted:
        if names and lf.name not in names:
            continue
        if progress:
            progress(lf.name)
        job = Job(lf.name, lang, source, label, seed, lifted, lf, langs=langs, options=options, samples=samples)
        job.facts.update(host)
        job.facts.update({f"opt:{o}": bool(options.get(o)) for o in OPTIONS})
        run_job(ctx, job, plan, runner, only=only)
        rec["functions"][lf.name] = {"stages": job.stages, "facts": {k: v for k, v in job.facts.items() if v},
                                     "card": job.card["name"] if job.card else None, "summary": _summary(job.stages),
                                     "report": job.report}
    rec["coverage"] = coverage_of(rec)
    return rec


def run_file(ctx: Ctx, path, lang: str | None = None, **kw) -> dict:
    from . import frontends
    p = Path(path)
    lang = lang or frontends.language_for_path(ctx.store, p)
    if lang is None:
        raise ValueError(f"cannot tell the language of {p}; readable: {', '.join(frontends.frontend_languages(ctx.store))}")
    return run_source(ctx, p.read_text(encoding="utf-8"), lang, label=p.name, **kw)


def coverage_of(rec: dict) -> dict:
    """Per stage, how many functions it ran on and why it did not on the rest; the run's problems."""
    per: dict[str, dict] = {}
    problems = []
    for fname, f in rec["functions"].items():
        for s, e in f["stages"].items():
            d = per.setdefault(s, {st: 0 for st in STATUSES})
            d[e["status"]] = d.get(e["status"], 0) + 1
        problems += [f"{fname}: {p}" for p in f["summary"]["problems"]]
    return {"stages": per, "problems": problems, "functions": len(rec["functions"]),
            "status": "fail" if problems else ("pass" if rec["functions"] else "vacuous")}


def report_text(rec: dict, verbose: bool = False) -> str:
    lines = [f"seed {rec['seed']} · {rec['source']} ({rec['lang']}) · {len(rec['stages'])} stages"]
    for fname, f in rec["functions"].items():
        c = f["summary"]["counts"]
        lines.append(f"  {fname}: {c['ran']} ran, {c['skipped']} not applicable, {c['not_requested']} not requested, "
                     f"{c['unavailable']} unavailable, {c['failed']} failed")
        for s in rec["stages"]:
            e = f["stages"].get(s) or {}
            if e.get("status") == "ran" and not verbose:
                v = e.get("verdict")
                brief = _brief(s, e)
                lines.append(f"    {s:<18} ran {('[' + v + '] ') if v else ''}{brief}")
            else:
                lines.append(f"    {s:<18} {e.get('status', '?'):<13} {e.get('reason', '')}" if e.get("status") != "ran"
                             else f"    {s:<18} ran  {_jsonish(e)}")
        for p in f["summary"]["problems"]:
            lines.append(f"    PROBLEM {p}")
    cov = rec["coverage"]
    lines.append(f"coverage {cov['status']}: " + ("every applicable stage ran or says why" if not cov["problems"]
                                                  else "; ".join(cov["problems"][:6])))
    return "\n".join(lines)


def _brief(stage: str, e: dict) -> str:
    if stage == "lift":
        return "lifted" if e.get("lifted") else "not lifted: " + "; ".join(e.get("reasons") or [])
    if stage == "profile":
        return ", ".join(sorted(e.get("facts") or {}))
    if stage == "reference":
        return f"{e.get('vectors')} vectors from {e.get('reference')}"
    if stage == "canon":
        return (f"{e.get('canonical')} (cost {e.get('cost')} from {e.get('lifted_cost')}; "
                f"{len(e.get('equalities') or [])} laws)" if e.get("canonical") is not None else e.get("why", ""))
    if stage == "identity":
        return f"{e.get('hash')} under {e.get('under')}"
    if stage == "content":
        return ", ".join(f"{k.split('/')[-1]}^{v}" if v != 1 else k.split("/")[-1]
                         for k, v in sorted((e.get("content") or {}).items())) or "(empty)"
    if stage == "real":
        return e.get("normal_form") or e.get("why", "")
    if stage == "behaviour":
        f = e.get("form")
        return f"{f['kind']}: {f['canonical']} (#{f['godel'][:18]}{'…' if len(f['godel']) > 18 else ''})" if f \
            else e.get("why", "")
    if stage == "class":
        return e.get("class") or f"sampled: {e.get('why')}"
    if stage == "sized_witness":
        return f"{e.get('points')} points, {'; '.join(e.get('theorems') or [])}" if e.get("verdict") else e.get("why", "")
    if stage == "divergence":
        o = e.get("obligations") or {}
        return f"obligations {o}; laws {', '.join(e.get('laws') or []) or 'none'}"
    if stage == "divergence_witness":
        return f"{e.get('verdicts')} in {len(e.get('runners') or [])} runners"
    if stage == "rewrite":
        ch = e.get("changes") or []
        return f"{len(ch)} cheaper: " + "; ".join(f"{c['from']} -> {c['to']}" for c in ch[:3]) if ch else e.get("why", "")
    if stage == "algorithm":
        subs = e.get("substitutions") or []
        return ", ".join(f"{s['card']}:{s.get('form')}" for s in subs[:4]) or "no substitution matches"
    if stage == "measure":
        t = e.get("targets") or []
        return ", ".join(f"{r['lang']} {r['ns']} ns" for r in t[:5]) or e.get("why", "")
    if stage == "emit":
        return f"{len(e.get('languages') or [])} languages" + (f", gaps {sorted(e['gaps'])}" if e.get("gaps") else "")
    if stage == "witness_targets":
        return f"agrees in {len(e.get('agreeing') or [])}: {', '.join(e.get('agreeing') or [])}"
    if stage == "witness_source":
        return f"{e.get('witness')} ({e.get('checks', 0)} checks)"
    if stage == "native":
        c = e.get("candidate")
        return f"{c['form']} inside {c['box']} ({e.get('checked')} checks)" if c else e.get("why", "")
    if stage == "notation":
        return f"{e.get('outcome')}: {(e.get('notation') or '').strip().splitlines()[0] if e.get('notation') else ''}"
    if stage == "round_trip":
        return ", ".join(f"{t} {s}" for t, s in sorted((e.get("targets") or {}).items())) or "no target has a frontend"
    if stage == "record":
        return f"{e.get('card')} {e.get('health')}" + (f", saved {e['saved']}" if e.get("saved") else "")
    return _jsonish(e)


def _jsonish(e: dict) -> str:
    import json
    return json.dumps({k: v for k, v in e.items() if k not in ("status", "seconds", "report")}, default=str)[:160]


# -- the coverage check ------------------------------------------------------------------------------------------
FIXTURE = '''
def poly(a: int, b: int) -> int:
    return (a + 0) * 1 + (b - b)


def tri(n: int) -> int:
    t = 0
    for i in range(n + 1):
        t += i
    return t


def ratio(x: float, y: float) -> float:
    return x / y


def safe_mod(a: int, m: int) -> int:
    if m == 0:
        return 0
    return a % m


def uses_list(xs: list) -> int:
    return len(xs)
'''

ENGINES_DIR = "cardmodel/engines"
HOME = Path(__file__).resolve().parents[2]


def _module_path(name: str, home: Path) -> str | None:
    """``cardmodel.engines.egraph`` -> ``cardmodel/engines/egraph.py`` (or the package's __init__)."""
    parts = name.split(".")
    f = home.joinpath(*parts).with_suffix(".py")
    if f.is_file():
        return str(f.relative_to(home))
    d = home.joinpath(*parts) / "__init__.py"
    return str(d.relative_to(home)) if d.is_file() else None


def _top_level(tree) -> list:
    """The statements a module runs when it loads: its body, descending into if/try blocks but not into functions
    or classes (an import inside a function is that function's, and counts only when a stage calls it)."""
    out, todo = [], list(tree.body)
    while todo:
        n = todo.pop(0)
        out.append(n)
        if isinstance(n, (ast.If, ast.Try)):
            todo += list(n.body) + list(getattr(n, "orelse", [])) + list(getattr(n, "finalbody", []))
            for h in getattr(n, "handlers", []):
                todo += list(h.body)
    return out


def _imports(path: Path, home: Path, node=None, top_only: bool = False) -> set[str]:
    """Paths of the program's own modules a file (or one of its functions) imports, resolved from relative imports;
    ``top_only`` keeps to what the module imports when it loads."""
    tree = node if node is not None else ast.parse(path.read_text(encoding="utf-8"))
    pkg = path.relative_to(home).with_suffix("").parts
    pkg = pkg[:-1] if path.name != "__init__.py" else pkg
    out = set()
    for n in _top_level(tree) if top_only else ast.walk(tree):
        if isinstance(n, ast.ImportFrom):
            if n.level:
                base = list(pkg[:len(pkg) - (n.level - 1)]) if n.level > 1 else list(pkg)
                mod = ".".join(base + ([n.module] if n.module else []))
            elif n.module and n.module.startswith("cardmodel"):
                mod = n.module
            else:
                continue
            for a in n.names:
                p = _module_path(f"{mod}.{a.name}", home) or _module_path(mod, home)
                if p:
                    out.add(p)
        elif isinstance(n, ast.Import):
            for a in n.names:
                p = _module_path(a.name, home) if a.name.startswith("cardmodel") else None
                if p:
                    out.add(p)
    return out


def _closure(seeds: set[str], home: Path) -> set[str]:
    """The seeds and every module they load, transitively (module-level imports: what loading them needs; an
    import inside a function of a reached module is not followed, so a module a stage reaches only through such a
    call must be named by a stage or named outside)."""
    seen, todo = set(), list(seeds)
    while todo:
        p = todo.pop()
        if p in seen or not (home / p).is_file():
            continue
        seen.add(p)
        todo += list(_imports(home / p, home, top_only=True))
    return seen


def stage_imports(home: Path | None = None) -> dict[str, set[str]]:
    """What each stage function (and the helpers it calls) imports, by stage name, read from this file."""
    home = home or HOME
    me = Path(__file__).resolve()
    tree = ast.parse(me.read_text(encoding="utf-8"))
    funcs = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    out = {}
    for name, fn in STAGES.items():
        node = funcs.get(fn.__name__)
        imports = _imports(me, home, node) if node is not None else set()
        for sub in ast.walk(node) if node is not None else ():
            if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name) and sub.func.id in funcs \
                    and sub.func.id.startswith("_"):
                imports |= _imports(me, home, funcs[sub.func.id])
        out[name] = imports
    return out


def registry_problems(ctx: Ctx, plan: list[dict] | None = None, home: Path | None = None) -> tuple[list[str], dict]:
    """The stage cards against the program and the mathematics, without running anything: every card names a stage
    function and the reverse, groups, facts and laws exist, ``needs`` point earlier, every cited definition or rule
    is in docs/FOUNDATIONS.md, each card's ``engines`` are what its function imports, and every engine is reached
    by a stage or named outside the pipeline with a reason. Returns the problems and the reach counts."""
    home = home or HOME
    plan = stages(ctx) if plan is None else plan
    problems: list[str] = []
    meta = (ctx.store.registry("stage").meta if ctx.store.registry("stage") is not None else {}) or {}
    outside = dict(meta.get("outside") or {})
    for s in plan:
        if s["run"] not in STAGES:
            problems.append(f"stage/{s['name']}: the program has no stage function {s['run']!r}")
        if s["group"] not in GROUPS:
            problems.append(f"stage/{s['name']}: group {s['group']!r} is not one of {GROUPS}")
        for f in s["when"] + s["unless"]:
            if f not in FACTS:
                problems.append(f"stage/{s['name']}: hypothesis names an unknown fact {f!r}")
        for n in s["needs"]:
            dep = next((x for x in plan if x["name"] == n), None)
            if dep is None:
                problems.append(f"stage/{s['name']}: needs {n!r}, which is no stage")
            elif (dep["order"], dep["name"]) >= (s["order"], s["name"]):
                problems.append(f"stage/{s['name']}: needs {n!r}, which runs after it")
        for ref in s["foundations"]:
            if not _foundation_exists(ref, home):
                problems.append(f"stage/{s['name']}: cites {ref}, which docs/FOUNDATIONS.md does not define")
        for q in s["laws"]:
            if ctx.store.get(q) is None:
                problems.append(f"stage/{s['name']}: law {q} does not exist")
    for run_name in sorted(set(STAGES) - {s["run"] for s in plan}):
        problems.append(f"stage function {run_name!r} exists in the program but no stage card names it (unreachable)")
    imports = stage_imports(home)
    reached: set[str] = set()
    for s in plan:
        got = {p for p in imports.get(s["run"], set()) if "/" in p}
        listed = set(s["engines"])
        for p in sorted(listed - got):
            problems.append(f"stage/{s['name']}: lists {p}, which its function does not import")
        for p in sorted(got - listed):
            if p.startswith(ENGINES_DIR) or p.startswith("cardmodel/machine"):
                problems.append(f"stage/{s['name']}: its function imports {p}, which the card does not list")
        reached |= got
    me = Path(__file__).resolve()
    reached = _closure(reached | _imports(me, home, top_only=True) | {str(me.relative_to(home))}, home)
    if f"{ENGINES_DIR}/frontends.py" in reached:          # frontends are reached through the language cards (A1)
        for c in ctx.store.cards("language"):
            p = _module_path(c["frontend"], home) if c.get("frontend") else None
            if p:
                reached |= _closure({p}, home)
    engines = sorted(str(p.relative_to(home)) for p in (home / ENGINES_DIR).glob("*.py") if p.name != "__init__.py")
    for p in engines:
        if p in reached and p in outside:
            problems.append(f"{p} is named outside the pipeline but a stage reaches it: drop it from `outside`")
        elif p not in reached and p not in outside:
            problems.append(f"{p} is reached by no stage and is not named outside the pipeline with a reason "
                            f"(cards/stage/_category.json `outside`)")
        elif p in outside and not str(outside[p]).strip():
            problems.append(f"{p} is outside the pipeline with no reason")
    for p in sorted(set(outside) - set(engines)):
        problems.append(f"`outside` names {p}, which is not an engine")
    return problems, {"engines": len(engines), "reached": sum(1 for p in engines if p in reached),
                      "outside": sum(1 for p in engines if p in outside),
                      "unreached": sorted(set(engines) - reached - set(outside))}


def fixture_problems(plan: list[dict], functions: dict) -> list[str]:
    """The fixtures' records against the registry: every function has an entry with a known status for every
    stage, and every stage applies to at least one function once every option and host fact is granted (else its
    hypothesis is dead, or the fixtures lack its case)."""
    problems: list[str] = []
    granted = {**{f"opt:{o}": True for o in OPTIONS}, **{f"host:{h}": True for h in HOST_FACTS}}
    for s in plan:
        if s["scope"] == "file":
            continue
        hit = any(applies(s, {**f["facts"], **granted})[0] == "ran" for f in functions.values())
        if not hit:
            problems.append(f"stage/{s['name']}: applies to no function of the fixtures even with every option and "
                            f"host fact granted (a dead hypothesis, or the fixtures lack its case)")
    for fname, f in functions.items():
        for s in plan:
            e = f["stages"].get(s["name"])
            if e is None:
                problems.append(f"{fname}: no entry for stage {s['name']} (CM50)")
            elif e["status"] not in STATUSES:
                problems.append(f"{fname}: stage {s['name']} has status {e['status']!r}")
    return problems


def coverage(ctx: Ctx, seed: int = 0, langs: list[str] | None = None, fixture: str | None = None,
             home: Path | None = None) -> dict:
    """The registry against the program and the mathematics, and the fixtures through every stage (CM50): the
    reference fixture, and the same functions written in a language that is not the reference and needs no
    toolchain to lift, so the stages conditioned on the source language have their case."""
    plan = stages(ctx)
    problems, reach = registry_problems(ctx, plan, home)
    quick = langs or _quick_langs(ctx)
    runs = [run_source(ctx, fixture or FIXTURE, REFERENCE, label="fixture", langs=quick, seed=seed, options={})]
    second = _second_fixture(ctx, fixture or FIXTURE) if fixture is None else None
    if second is not None:
        lang2, text2 = second
        runs.append(run_source(ctx, text2, lang2, label=f"fixture.{lang2}", langs=quick, seed=seed, options={}))
    functions = {f"{r['source']}:{n}": f for r in runs for n, f in r["functions"].items()}
    for r in runs:
        problems += [f"{r['source']}: {p}" for p in r["coverage"]["problems"]]
    problems += fixture_problems(plan, functions)
    ran = {s["name"]: sum(r["coverage"]["stages"].get(s["name"], {}).get("ran", 0) for r in runs) for s in plan}
    return {"status": "fail" if problems else "pass", "problems": problems, "stages": len(plan),
            "groups": {g: sum(1 for s in plan if s["group"] == g) for g in GROUPS}, **reach,
            "fixtures": [r["coverage"] for r in runs], "functions": len(functions), "ran_per_stage": ran,
            "seed": seed}


def _second_fixture(ctx: Ctx, source: str) -> tuple[str, str] | None:
    """The fixture in a language that is not the reference, so the stages conditioned on the source language have
    a case: the first language card (by name) with a frontend and its own emitter module (read and written by the
    card's modules, no toolchain), given the reference fixture's lifted functions to write."""
    import importlib
    from . import frontends
    lifted = [lf for lf in frontends.lift(ctx, source, REFERENCE) if lf.ok]
    for c in sorted(ctx.store.cards("language"), key=lambda c: c.name):
        if c.name == REFERENCE or not c.get("frontend") or not c.get("emitter"):
            continue
        try:
            emit = importlib.import_module(c["emitter"]).emit_module
        except (ImportError, AttributeError):
            continue
        texts = []
        for lf in lifted:
            try:
                texts.append(emit({"entry": lf.name, "functions": [lf.ir]}))
            except Exception:  # noqa: BLE001 -- a function the card cannot write is left out of its fixture
                continue
        if texts:
            return c.name, "\n\n".join(texts)
    return None


def _quick_langs(ctx: Ctx) -> list[str]:
    """The reference language and one compiled engine language when the host has one: enough to witness the
    target stages without compiling every language (the ``functions`` verify section does that)."""
    from ..machine import native as N
    langs = [REFERENCE]
    try:
        langs.append(N.resolve_engine(ctx, "native"))
    except Exception:  # noqa: BLE001 -- no compiled language on this host
        pass
    return sorted(set(langs))


def _foundation_exists(ref: str, home: Path) -> bool:
    text = (home / "docs" / "FOUNDATIONS.md").read_text(encoding="utf-8")
    return re.search(rf"\*\*{re.escape(ref)}\.", text) is not None


__all__ = ["FACTS", "FIXTURE", "GROUPS", "OPTIONS", "REFERENCE", "STAGES", "STATUSES", "Job", "Runner",
           "Unavailable", "applies", "coverage", "coverage_of", "fixture_problems", "host_facts", "registry_problems",
           "report_text", "run_file", "run_job", "run_source", "stage_imports", "stages"]


# -- Gödel purity (GODEL_AUDIT §2, GODEL_TARGET §7; goal G_A14), ported from the coverage branch ----------------
from functools import lru_cache  # noqa: E402
from ..kernel import paths  # noqa: E402

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


GODEL_CORE = ("cardmodel.engines.godel", "cardmodel.engines.godel1931")
FAMILY = frozenset({"primes", "nth_prime", "zig", "unzig", "term_content", "module_content", "card_content", "content",
                    "tokens", "structural", "exponents", "from_tokens", "valuation", "sieve"})

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



# The known copies of the core's algebra outside engines/godel.py, as of the port. This list may only shrink: a new
# copy fails the integrity check, and a copy the code no longer has must be removed from it. Its length is goal
# G_A14's metric (``godel_impure``).
KNOWN_COPIES = frozenset({
    "cardmodel/engines/codes.py:Reader.codes",
    "cardmodel/engines/codes.py:built_positional_bits",
    "cardmodel/engines/codes.py:_head_code",
    "cardmodel/engines/funcalg.py:godel_encode",
    "cardmodel/engines/numbering.py:Numbering.tokens",
    "cardmodel/engines/numbering.py:Numbering.encode",
    "cardmodel/unreal/distill.py:number",
})


def godel_impure() -> int:
    """Goal G_A14's metric: the known copies of the core's algebra still recorded."""
    return len(KNOWN_COPIES)


def purity_problems(ctx=None, home: str | None = None) -> list[str]:
    """Every copy of the core's algebra in the code is a known one, and every known one is still in the code (the
    list only shrinks): the part of the integrity check that keeps the program pure to the Gödel model."""
    found = purity_findings(home)
    out = [f"{at}: {found[at]}, outside engines/godel.py: call the core (GODEL_TARGET §7, G_A14); the known-copies "
           f"list in engines/pipeline.py may only shrink" for at in sorted(set(found) - KNOWN_COPIES)]
    out += [f"{at}: listed in pipeline.KNOWN_COPIES, but the code no longer has it: remove it from the list"
            for at in sorted(KNOWN_COPIES - set(found))]
    return out


__all__ += ["KNOWN_COPIES", "godel_impure", "purity_findings", "purity_problems"]
