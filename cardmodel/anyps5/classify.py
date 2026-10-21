"""classify — every AnyPS5 gap with its cause, decided by stdlib/anyps5.card over facts from the cards.

Facts (one predicate per property; E an export card name, D a debt card name, L a library):

  export(E) library_of(E, L) implemented(E) pending(E) inert(E) unknown_name(E) no_params(E) helper_stub(E)
  uses(E, G) unsupported_input(E, C) size_of(E, X) packet(X, N) constant(E, B) standard(E, S)
  export_override(E, C) debt_on(D, E) closed(E) witness_agrees(E) remaining(E, C)
  debt(D) debt_section(D, S) debt_library(D, L) debt_cue(D, C) debt_title(D, T) debt_closed(D)
  library(L) empty_library(L) domain(L, Dm)
  priority(C, P) debt_priority(C, P) cause_class(C, K) standard_cause(S, C) domain_cause(Dm, C)

The knowledge is data: cause cards carry the cue patterns a debt entry is read with and both priorities,
domain cards the library pattern and default cause, standard cards the symbol pattern, and a semantics card
that derives part of a gap names the cause of what remains (``remaining``, which outranks the heuristics).
Witness cards count only when they belong to the current scan. The rules derive every
candidate cause and keep the strongest; the constraints say no gap is left without one and no library without
a domain. ``Classification.why`` returns the proof the logic engine kept for any derived fact.

Honest limits (L1): a debt entry's cause comes from cue words in its text (the cards record which pattern
matched), so a sentence that negates a cue ("measured, not inferred") can mislead it; the domain table is a
judgement recorded in cards, not something read from AnyPS5.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..engines import logic as L
from ..kernel import paths, resources
from .cards import scan_cards, symbol_of

PARTIAL_CUES = re.compile(r"\b(unsupported|not supported|not implemented|unimplemented|not modell?ed|not handled|"
                          r"unknown|other than|outside)\b", re.I)
SIGNATURE_CUES = re.compile(r"\bsignature (is )?unknown\b|\bunknown signature\b|\bassumed signature\b", re.I)
SECTIONS = {"unknown function info": "unknown_function_info", "functional": "functional",
            "silent stubs": "silent_stubs", "build": "build"}


def _theory(ctx):
    from ..lang.compile import compile_file
    return compile_file(paths.home() / "stdlib" / "anyps5.card", ctx.ops, ctx.store)


@dataclass
class Classification:
    model: L.Model
    facts: int
    exports: dict = field(default_factory=dict)        # name -> card (counted function exports)
    debt: dict = field(default_factory=dict)
    libraries: dict = field(default_factory=dict)
    cue_hits: dict = field(default_factory=dict)       # debt name -> {cause: pattern}
    semantics: dict = field(default_factory=dict)      # semantics card name -> program status

    def rel(self, pred: str) -> set:
        return set(self.model.db.rel.get(pred, ()))

    def why(self, pred: str, args) -> str:
        if not self.model.holds(pred, tuple(args)):
            return f"{pred}({', '.join(map(str, args))}) does not follow"
        return L.proof_text(self.model.proof(pred, tuple(args)))


def domain_of(library: str, domains: list) -> str | None:
    """The first domain (by priority) whose pattern matches the library, read without AnyPS5's variant suffixes
    (``.native``, ``-module``: the same library built another way)."""
    base = re.sub(r"(\.native|-module)$", "", library)
    for d in domains:
        if re.search(d["match"], base):
            return d.name
    return None


def run_program(ctx, program: str, seed: int = 20261021) -> dict:
    """Compile and run a semantics program (tests, theorems, constraints): the closure counts only if it passes."""
    from ..lang.compile import CompileError, compile_file
    from ..lang.run import run as run_module
    from ..lang.syntax import CardSyntaxError
    try:
        mod = compile_file(paths.home() / program, ctx.ops, ctx.store)
        rep = run_module(ctx, mod, seed=seed, samples=60)
        return {"status": rep["status"], "counts": rep["counts"]}
    except (CompileError, CardSyntaxError, OSError) as exc:
        return {"status": "fail", "error": str(exc)}


def facts(ctx, run_programs: bool = True, program_status: dict | None = None) -> tuple[L.Program, dict]:
    st = ctx.store
    prog = L.Program(name="anyps5")
    add = prog.add_fact
    info: dict = {"exports": {}, "debt": {}, "libraries": {}, "cue_hits": {}, "semantics": {}}
    causes = {c.name: c for c in st.cards("anyps5_cause")}
    for c in causes.values():
        add("priority", [c.name, int(c["priority"])])
        add("debt_priority", [c.name, int(c["debt_priority"])])
        add("cause_class", [c.name, c["class"]])
    domains = sorted(st.cards("anyps5_domain"), key=lambda d: d["priority"])
    for d in domains:
        add("domain_cause", [d.name, d["cause"]])
    standards = st.cards("anyps5_standard")
    for s in standards:
        add("standard_cause", [s.name, s["cause"]])
    lib_domain = {}
    for lib in scan_cards(st, "anyps5_library"):
        info["libraries"][lib.name] = lib
        add("library", [lib.name])
        if lib.get("empty"):
            add("empty_library", [lib.name])
        dm = domain_of(lib.name, domains)
        if dm:
            add("domain", [lib.name, dm])
            lib_domain[lib.name] = dm
    overrides = {d.name: d.get("exports") or [] for d in domains}
    closes, closes_debt, agrees = set(), set(), set()
    known = program_status or {}
    for sem in st.cards("anyps5_semantics"):
        prog_name = sem["program"].rsplit("/", 1)[-1]
        if prog_name in known:
            status = {"status": known[prog_name]}
        else:
            status = run_program(ctx, sem["program"]) if run_programs else {"status": "not run"}
        info["semantics"][sem.name] = status
        if status["status"] == "pass":
            closes |= set(sem.get("closes") or [])
            closes_debt |= set(sem.get("closes_debt") or [])
    disagree = set()
    snap = st.get("anyps5_snapshot/current")
    current = snap.get("sha256") if snap is not None else None
    remaining = {}
    for sem in st.cards("anyps5_semantics"):
        for d in sem.get("derives") or []:
            if d.get("remaining_cause"):
                remaining[d["export"]] = d["remaining_cause"]
    for w in st.cards("anyps5_witness"):
        if w.get("snapshot") != current:
            continue                        # evidence about an older scan of AnyPS5 does not count now
        for e, r in (w.get("exports") or {}).items():
            if r.get("agree") and r.get("checks", 0) > 0 and not r.get("disagree"):
                agrees.add(e)
            elif r.get("disagree"):
                disagree.add(e)
    agrees -= disagree
    exports = [c for c in scan_cards(st, "anyps5_export") if c.get("kind") == "function"]
    by_lib_symbol = {(c["library"], symbol_of(c)): c for c in exports}
    for c in exports:
        resources.guard("anyps5 facts")
        e = c.name
        info["exports"][e] = c
        add("export", [e])
        add("library_of", [e, c["library"]])
        add("implemented" if c["state"] == "implemented" else "pending", [e])
        if c.get("inert"):
            add("inert", [e])
        if c.get("unknown_name"):
            add("unknown_name", [e])
        if c["state"] == "pending" and c.get("param_count") == 0:
            add("no_params", [e])
        if c.get("helper_stub"):
            add("helper_stub", [e])
        for g in c.get("uses") or []:
            add("uses", [e, g])
        if c["state"] == "implemented":
            msgs = (c.get("throw_messages") or []) + (c.get("stub_paths") or [])
            if any(SIGNATURE_CUES.search(m) for m in (c.get("hit_messages") or []) + msgs):
                add("unsupported_input", [e, "observation_unknown_signature"])
            elif any(PARTIAL_CUES.search(m) for m in msgs):
                add("unsupported_input", [e, "none"])
        if c.get("constant") is not None:
            add("constant", [e, int(c["constant"])])
        if c.get("packet"):
            add("packet", [e, int(c["packet"]["payload"])])
        sym = symbol_of(c)
        if sym.endswith("GetSize"):
            base = by_lib_symbol.get((c["library"], sym[:-len("GetSize")]))
            if base is not None:
                add("size_of", [e, base.name])
        for s in standards:
            if re.search(s["match"], sym):
                add("standard", [e, s.name])
        for o in overrides.get(lib_domain.get(c["library"]), []):
            if re.search(o["match"], sym):
                add("export_override", [e, o["cause"]])
        if e in closes:
            add("closed", [e])
        if e in remaining:
            add("remaining", [e, remaining[e]])
        if e in agrees:
            add("witness_agrees", [e])
    cue_tables = {name: [re.compile(p, re.I) for p in (c.get("cues") or [])] for name, c in causes.items()}
    for d in scan_cards(st, "anyps5_debt"):
        resources.guard("anyps5 facts")
        info["debt"][d.name] = d
        add("debt", [d.name])
        add("debt_section", [d.name, SECTIONS.get((d.get("section") or "").lower(), "none")])
        for lib in d.get("libraries") or []:
            add("debt_library", [d.name, lib])
        for e in d.get("exports") or []:
            if e in info["exports"]:
                add("debt_on", [d.name, e])
        for t in d.get("titles") or []:
            add("debt_title", [d.name, t])
        text = d.get("text") or d.get("excerpt") or ""
        hits = {}
        for cname, pats in cue_tables.items():
            for p in pats:
                m = p.search(text)
                if m:
                    hits[cname] = m.group(0)
                    add("debt_cue", [d.name, cname])
                    break
        info["cue_hits"][d.name] = hits
        if d.name in closes_debt:
            add("debt_closed", [d.name])
    theory = _theory(ctx)
    prog.rules.extend(theory.program.rules)
    prog.facts.extend(theory.program.facts)
    return prog, info


def classify(ctx, run_programs: bool = True, program_status: dict | None = None) -> Classification:
    """``program_status``: {program file name: status} from a run that already happened (verify's lang)."""
    prog, info = facts(ctx, run_programs=run_programs, program_status=program_status)
    model = L.evaluate(prog, ctx.ops)
    return Classification(model=model, facts=len(prog.facts), exports=info["exports"], debt=info["debt"],
                          libraries=info["libraries"], cue_hits=info["cue_hits"], semantics=info["semantics"])


__all__ = ["Classification", "classify", "domain_of", "facts", "run_program"]
