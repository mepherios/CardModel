"""cover — the real coverage behind AnyPS5's badges, computed from the cards, and every gap with its cause.

The ladder (each step takes out what the one before still counted, so the steps add up):

  declared             APS5_VABI definitions AnyPS5 counts (its denominator)
  implemented          AnyPS5's own rule: the body never calls NotImplemented (the libraries badge)
  - behaviourally empty    a constant return, bare return or throw and nothing else
  - partial                throws, by its own message, for inputs it does not support
  - reaches a stub         calls (through helpers in other files or other exports) something unimplemented
  - open debt              a technical-debt entry names it: part of its behaviour is assumed or unmeasured
  = complete           nothing in AnyPS5's own records says it is incomplete
    tested             of those, a test file in AnyPS5 names it (a reference: not run here)
    witnessed          of those, the card model ran AnyPS5's code next to derived semantics, and they agree

Then: every gap item (an export's gap, a debt entry, a module with no declared exports) by cause class and
cause, what closes each cause, and examples with file and line; the derivable gaps split by what they still
need; the module graph's ranking of pending exports by what they block; and the shader ladder.

Honest limits (L1): "complete" is relative to AnyPS5's own records, not to the console: a function nobody
wrote a debt entry for can still differ from the PS5. The denominator is what AnyPS5 declares; 202 modules
declare nothing, and the firmware's real export count is not read here (by policy).
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone

from .cards import scan_cards
from .classify import Classification, classify

STEPS = [("inert", "behaviourally empty (a constant, a bare return or a throw)"),
         ("partial", "throws, by its own message, for inputs it does not support"),
         ("reaches_stub", "reaches something unimplemented through a call"),
         ("debt", "named by an open technical-debt entry (behaviour assumed or unmeasured)")]
CLASS_ORDER = ["derivable", "observation", "performance", "boundary"]


def pct(n: int, d: int) -> float:
    return round(100.0 * n / d, 2) if d else 0.0


def report(ctx, cls: Classification | None = None) -> dict:
    cls = cls or classify(ctx)
    st = ctx.store
    causes = {c.name: c for c in st.cards("anyps5_cause")}
    exports = cls.exports
    declared = len(exports)
    implemented = {e for e, c in exports.items() if c["state"] == "implemented"}
    gaps = defaultdict(set)
    for e, k in cls.rel("gap"):
        gaps[k].add(e)
    complete = {t[0] for t in cls.rel("complete")}
    witnessed = {t[0] for t in cls.rel("witnessed")}
    remaining = set(implemented)
    ladder = [{"step": "declared", "count": declared, "percent": 100.0},
              {"step": "implemented (AnyPS5's rule)", "count": len(implemented), "percent": pct(len(implemented), declared)}]
    for kind, label in STEPS:
        out = remaining & gaps[kind]
        remaining -= out
        ladder.append({"step": f"- {label}", "count": -len(out), "percent": pct(len(remaining), declared)})
    assert remaining == complete, "the ladder must end at the logic's complete set"
    tested = {e for e in complete if exports[e].get("test_files")}
    ladder.append({"step": "= complete by AnyPS5's own records", "count": len(complete), "percent": pct(len(complete), declared)})
    ladder.append({"step": "  of which a test file names it (not run here)", "count": len(tested),
                   "percent": pct(len(tested), declared)})
    ladder.append({"step": "  of which witnessed here against derived semantics", "count": len(witnessed),
                   "percent": pct(len(witnessed), declared)})
    agreeing = {t[0] for t in cls.rel("witness_agrees")}
    gap_cause = Counter()
    by_cause = defaultdict(list)
    for e, k, c in cls.rel("cause"):
        gap_cause[c] += 1
        by_cause[c].append((e, k))
    debt_cause = Counter(c for _, c in cls.rel("debt_cause"))
    module_cause = Counter(c for _, c in cls.rel("module_cause"))
    rows = []
    for name, card in causes.items():
        n_e, n_d, n_m = gap_cause.get(name, 0), debt_cause.get(name, 0), module_cause.get(name, 0)
        if not (n_e or n_d or n_m):
            continue
        ex = sorted(by_cause.get(name, []))[:3]
        rows.append({"cause": name, "class": card["class"], "exports": n_e, "debt": n_d, "modules": n_m,
                     "total": n_e + n_d + n_m, "closes_with": card["closes_with"],
                     "examples": [{"export": e, "kind": k, "at": _at(exports[e])} for e, k in ex]})
    rows.sort(key=lambda r: (CLASS_ORDER.index(r["class"]), -r["total"]))
    classes = Counter()
    for r in rows:
        classes[r["class"]] += r["total"]
    items = sum(r["total"] for r in rows)
    pending = {e for e, c in exports.items() if c["state"] == "pending"}
    partial_pending = {e for e in pending if exports[e].get("partial_pending")}
    blocks = sorted(((g, n) for g, n in cls.rel("blocks") if n), key=lambda t: (-t[1], t[0]))
    unblocks = sorted(((x, n) for x, n in cls.rel("unblocks") if n), key=lambda t: (-t[1], t[0]))
    derivable = {r["cause"]: r["total"] for r in rows if r["class"] == "derivable"}
    covered = {e for sem in st.cards("anyps5_semantics") for e in sem.get("covers") or []}
    unwitnessed = sorted(covered - agreeing)
    closable_open = derivable.get("derivable_packet", 0) + len(unwitnessed)
    semantics = cls.semantics or {}
    stale = []
    snap = st.get("anyps5_snapshot/current")
    for w in st.cards("anyps5_witness"):
        if snap is not None and w.get("snapshot") and w["snapshot"] != snap.get("sha256"):
            stale.append(w.name)
    disagree = sum(r.get("disagree", 0) for w in st.cards("anyps5_witness") for r in w.get("checks") or []
                   if r.get("expect") == "agree")
    disagree += sum(1 for w in st.cards("anyps5_witness") for r in w.get("checks") or [] if not r.get("ok"))
    justified = sorted(t[0] for t in cls.rel("justified"))
    cores = [{"semantics": sem.name, **d} for sem in st.cards("anyps5_semantics") for d in sem.get("derives") or []]
    deviations, stub_chains = [], []
    for w in st.cards("anyps5_witness"):
        for r in w.get("checks") or []:
            if r.get("expect") == "differs":
                deviations.append({"witness": w.name, "export": r.get("export"), "differ": r["disagree"],
                                   "inputs": r["inputs"], "examples": r["examples"][:3], "note": r.get("note")})
    for e, c in sorted(exports.items()):
        if c["state"] == "implemented" and c.get("helper_stub"):
            stub_chains.append({"export": e, "chain": c["helper_stub"], "at": _at(c)})
    instr = scan_cards(st, "anyps5_instruction")
    shader = {"isa": len(instr), "decoded": sum(1 for c in instr if c.get("decoded")),
              "translated": sum(1 for c in instr if c.get("translated")),
              "executed": sum(1 for c in instr if c.get("executed"))}
    aliases = [c for c in scan_cards(st, "anyps5_export") if c.get("kind") == "nid_alias"]
    libs = list(cls.libraries.values())
    rep = {"generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "snapshot": {k: snap.get(k) for k in ("sha256", "scanned_at", "root", "badge", "shader_badge", "parity")}
           if snap else None,
           "declared": declared, "implemented": len(implemented), "complete": len(complete),
           "witnessed": len(witnessed), "witness_agreeing_exports": len(agreeing),
           "complete_fraction": round(len(complete) / declared, 4) if declared else None,
           "ladder": ladder, "gap_items": items, "gap_kinds": {k: len(v) for k, v in sorted(gaps.items())},
           "classes": dict(classes), "causes": rows, "derivable": derivable, "closable_open": closable_open,
           "covered_unwitnessed": unwitnessed,
           "unclassified": len(cls.model.violations), "violations": cls.model.violations[:10],
           "pending": len(pending), "partial_pending": len(partial_pending),
           "blocks": [{"export": g, "blocks": n} for g, n in blocks[:15]],
           "unblocks": [{"export": x, "unblocks": n} for x, n in unblocks[:15]],
           "size_law": {"holds": len(cls.rel("size_law_holds")), "fails": len(cls.rel("size_law_fails"))},
           "semantics": semantics, "stale_witnesses": stale, "witness_disagreements": disagree,
           "justified_constants": justified, "derived_cores": cores, "deviations": deviations,
           "stub_chains": stub_chains,
           "shader": shader, "nid_aliases": len(aliases),
           "nid_aliases_unknown_name": sum(1 for c in aliases if c.get("unknown_name")),
           "libraries": len(libs), "empty_libraries": sum(1 for c in libs if c.get("empty")),
           "debt_entries": len(cls.debt), "facts": cls.facts, "derived": cls.model.stats.get("derived")}
    return rep


def _at(card) -> str:
    p = card.get("provenance") or {}
    return f"{p.get('file')}:{p.get('line')}"


def markdown(rep: dict, command: str = "cardmodel anyps5 cover --write docs/ANYPS5_COVERAGE.md") -> str:
    snap = rep.get("snapshot") or {}
    badge = snap.get("badge") or {}
    sb = snap.get("shader_badge") or {}
    par = snap.get("parity") or {}
    L = [f"# AnyPS5 coverage (generated by `{command}`; do not edit)", "",
         f"Generated {rep['generated']} from the anyps5_* cards: snapshot `{(snap.get('sha256') or '')[:16]}` "
         f"scanned {snap.get('scanned_at')}.", ""]
    cl = rep["classes"]
    L += ["## In short", "",
          f"* The libraries badge says {badge.get('percent')}%. Complete by AnyPS5's own records: "
          f"{pct(rep['complete'], rep['declared'])}% ({rep['complete']} of {rep['declared']}). Witnessed here against "
          f"semantics derived from public standards: {rep['witness_agreeing_exports']} exports agree with them on every "
          f"input tried ({rep['witnessed']} of those are complete).",
          f"* {rep['gap_items']} gap items, every one with a cause: derivable {cl.get('derivable', 0)} (closable in the IR "
          f"now and open: {rep['closable_open']}), observation only {cl.get('observation', 0)}, boundary "
          f"{cl.get('boundary', 0)}, performance {cl.get('performance', 0)}.",
          "* Why the rest cannot close by construction, and what would close it: the card model's docs/ANYPS5.md.", ""]
    L += ["## The badges, reproduced", "",
          f"AnyPS5's libraries badge is {badge.get('percent')}% ({badge.get('done')} of {badge.get('total')} declared "
          f"functions implemented) and its shader badge {sb.get('percent')}% ({sb.get('done')} of {sb.get('total')} "
          f"RDNA instructions decoded). There is no 95% figure in the checkout. The card model reads the same rule "
          f"and gets the same numbers: "
          + (f"{par.get('mismatch_count')} mismatches against AnyPS5's own progress.json, library by library and "
             f"name by name." if par else "parity with AnyPS5's own tool was not checked in this scan."), ""]
    L += ["## The real coverage", "", "| step | count | % of declared |", "|---|---:|---:|"]
    for s in rep["ladder"]:
        L.append(f"| {s['step']} | {s['count']} | {s['percent']} |")
    L += ["", f"The badge counts {rep['partial_pending']} of its {rep['pending']} pending functions as unimplemented "
              f"although they are implemented except for named unsupported paths, and counts as implemented the "
              f"functions the ladder takes out. {rep['empty_libraries']} of {rep['libraries']} modules declare no "
              f"exports at all, so the denominator is a lower bound; {rep['nid_aliases']} exports are bound to an "
              f"explicit NID in the source (APS5_EXPORT), {rep['nid_aliases_unknown_name']} of them under a placeholder "
              f"name because the symbol is unknown.", ""]
    L += ["## Every gap, by cause", "",
          f"{rep['gap_items']} gap items (export gaps, debt entries, empty modules), "
          f"{rep['unclassified']} without a cause.", "", "| class | items |", "|---|---:|"]
    for k in CLASS_ORDER:
        if rep["classes"].get(k):
            L.append(f"| {k} | {rep['classes'][k]} |")
    L += ["", "| cause | class | exports | debt | modules | what closes it |", "|---|---|---:|---:|---:|---|"]
    for r in rep["causes"]:
        L.append(f"| {r['cause']} | {r['class']} | {r['exports']} | {r['debt']} | {r['modules']} | {r['closes_with']} |")
    L += ["", "Examples (export, gap kind, file:line):", ""]
    for r in rep["causes"]:
        if r["examples"]:
            L.append(f"* **{r['cause']}**: " + "; ".join(f"`{x['export']}` ({x['kind']}, {x['at']})" for x in r["examples"]))
    L += ["", "## Closed and witnessed in the model", "",
          f"{rep['witness_agreeing_exports']} exports agree with semantics the model derives from public standards "
          f"on every input tried ({rep['witness_disagreements']} disagreements, {len(rep['stale_witnesses'])} stale "
          f"witness cards); {rep['witnessed']} of them are also complete. The packet-size law holds on "
          f"{rep['size_law']['holds']} implemented GetSize / emitter pairs and fails on {rep['size_law']['fails']}.", "",
          "| semantics program | status |", "|---|---|"]
    for name, s in sorted((rep.get("semantics") or {}).items()):
        L.append(f"| {name} | {s.get('status')} |")
    L += ["", f"{len(rep['justified_constants'])} functions AnyPS5's own counting marks behaviourally empty return a "
              f"constant the model derives and AnyPS5's code agrees with, so they are not gaps "
              f"(e.g. {', '.join('`' + x + '`' for x in rep['justified_constants'][:4])})."]
    for c in rep["derived_cores"]:
        L.append(f"* Derived for a gap that stays open: `{c['export']}`: {c['what']}. Remaining: {c['remaining']}.")
    for d in rep["deviations"]:
        L.append(f"* Documented deviation, witnessed ({d['witness']}): `{d['export']}` differs from the standard on "
                 f"{d['differ']} of {d['inputs']} inputs in the documented domain, e.g. {d['examples'][:2]}. {d.get('note') or ''}")
    L += ["", f"Derivable gaps by what they still need: "
              + ", ".join(f"{k} {v}" for k, v in sorted(rep["derivable"].items())) +
          f". Closable in the IR now and still open: {rep['closable_open']} (packet sizes the model derives that "
          f"AnyPS5 lacks, plus exports a semantics card covers without a current agreeing witness"
          + (f": {', '.join(rep['covered_unwitnessed'][:6])}" if rep["covered_unwitnessed"] else "") + ").", ""]
    if rep["stub_chains"]:
        L += ["## Implemented by AnyPS5's rule, but reaching NotImplemented through another file", "",
              "| export | helper chain | at |", "|---|---|---|"]
        L += [f"| {x['export']} | {' -> '.join(x['chain'])} | {x['at']} |" for x in rep["stub_chains"]]
        L.append("")
    if rep["blocks"]:
        L += ["## What a missing export blocks", "", "| pending export | implemented exports that reach it |", "|---|---:|"]
        L += [f"| {b['export']} | {b['blocks']} |" for b in rep["blocks"]]
        L.append("")
    sh = rep["shader"]
    L += ["## Shaders", "", f"{sh['isa']} RDNA instructions; {sh['decoded']} decoded; {sh['translated']} named by a "
          f"translation case (the others go through generic paths a lexical reading cannot follow); {sh['executed']} "
          f"named by an execution test (AnyPS5's GPU tests, not run here).", ""]
    return "\n".join(L) + "\n"


def comparison(base: dict, rep: dict, base_label: str, label: str) -> str:
    """Two scans side by side (the model's scan of upstream and a project's scan of its own checkout)."""
    rows = [("declared exports", "declared"), ("implemented (AnyPS5's rule)", "implemented"),
            ("complete by AnyPS5's own records", "complete"),
            ("agree with derived semantics", "witness_agreeing_exports"), ("gap items", "gap_items"),
            ("gaps without a cause", "unclassified"), ("witness disagreements", "witness_disagreements")]
    L = ["## Before and after", "", f"| | {base_label} | {label} | change |", "|---|---:|---:|---:|"]
    for text, key in rows:
        a, b = base.get(key) or 0, rep.get(key) or 0
        L.append(f"| {text} | {a} | {b} | {b - a:+d} |")
    for k in CLASS_ORDER:
        a, b = base["classes"].get(k, 0), rep["classes"].get(k, 0)
        L.append(f"| gaps: {k} | {a} | {b} | {b - a:+d} |")
    dev_a = sum(d["differ"] for d in base.get("deviations") or [])
    dev_b = sum(d["differ"] for d in rep.get("deviations") or [])
    L.append(f"| documented deviations from a standard (inputs) | {dev_a} | {dev_b} | {dev_b - dev_a:+d} |")
    return "\n".join(L) + "\n"


__all__ = ["comparison", "markdown", "pct", "report"]
