"""coverage — what the model represents, can run here, and has witnessed: computed, never claimed (L38).

Questions answered (rea-cards coverage.py style: one number per question):
  1. representation  cards per registry (dir vs packed), card types, laws, goals
  2. forms           runnable / available here / witnessed, per language
  3. translation     the op x language conformance matrix (last verify) and
                     function cards agreeing in >= 3 implementations
  4. witnesses       vectors, rules (numeric + Lean), redefinitions
  5. contracts       how many vendored computation cards satisfy primitive_contract
  6. machines        instruction cards per ISA and their conformance (last verify), the last ROM survey, lifted
                     differential runs, test ROMs and the DS coverage report (state files written by the
                     `cardmodel machine ...` commands; ROM titles never leave the state directory)
  7. goals           every goal card's metric against its target (the cycle's numbers -- law witnesses, the store,
                     regressions, the model observing its own code -- come from cycle/evidence.py)

Inputs: the store and ``state/last_verify.json`` (written by ``cardmodel
verify``). Numbers that need a verify run say "not run yet" instead of 0.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone

from ..kernel.schema import validate
from . import conformance
from .context import Ctx
from .rewrite import available, forms_of


def compute(ctx: Ctx) -> dict:
    st = ctx.store
    last = ctx.load_state("last_verify") or {}
    secs = last.get("sections", {})
    rep: dict = {"generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                 "verify_seed": last.get("seed"), "verify_started": last.get("started")}
    regs = {}
    for name, view in st.views.items():
        cards = list(view.ALL.values())
        regs[name] = {"cards": len(cards), "packed": sum(1 for c in cards if c.source.startswith("pack:")),
                      "layers": sorted({r.layer for r in view.regs})}
    rep["registries"] = regs
    rep["total_cards"] = sum(r["cards"] for r in regs.values())

    by_lang = Counter()
    runnable = avail = 0
    total_forms = 0
    for reg in ("op", "call", "crypto_atom", "re_operation", "function"):
        for card in st.cards(reg):
            for f in forms_of(card):
                total_forms += 1
                if f.runnable:
                    runnable += 1
                    ok = available(st, f)[0] if not f.raw.get("file") or f.lang == "python" else \
                        ctx.available(f.lang)[0] if st.get(f"language/{f.lang}") else False
                    avail += ok
                    by_lang[f.lang] += 1
    rep["form_inventory"] = {"total": total_forms, "runnable": runnable, "available_here": avail,
                             "by_language": dict(by_lang)}

    langs = {}
    for card in st.cards("language"):
        ok, why = ctx.available(card.name) if card.get("probe") else (False, "no probe")
        langs[card.name] = {"codegen": card.get("codegen") is not None, "available": ok,
                            "toolchain": why if ok else None, "reason": None if ok else why}
    rep["languages"] = langs

    conf = secs.get("conformance")
    if conf:
        good, total = conformance.rate(conf)
        rep["conformance"] = {"rate": [good, total], "summary": conf.get("summary"), "seed": conf.get("seed")}
    else:
        rep["conformance"] = "not run yet (cardmodel verify)"
    fns = secs.get("functions")
    if fns:
        agree = {q: len(r.get("agreeing_languages", [])) for q, r in fns.get("cards", {}).items()}
        rep["functions"] = {"cards": len(agree), "agreeing_3_plus": sum(1 for v in agree.values() if v >= 3),
                            "max_agreeing": max(agree.values(), default=0)}
    else:
        rep["functions"] = {"cards": len(st.cards("function")), "agreeing_3_plus": "not run yet"}
    for sec in ("forms", "vectors", "rules", "redefinitions"):
        r = secs.get(sec)
        rep[sec] = {"status": r["status"], "counts": r.get("counts"), **({"hub_claims": r["hub_claims"]}
                                                                         if "hub_claims" in r else {})} \
            if r else "not run yet"
    pr = secs.get("proofs")
    rep["proofs"] = {k: pr.get(k) for k in ("status", "proved", "total", "reason", "backend")} if pr else "not run yet"
    k = secs.get("kernel")
    rep["kernel"] = {kk: (len(v) if isinstance(v, (list, dict)) else v) for kk, v in k.items()} if k else "not run yet"

    prim = st.get("card_type/primitive")
    comp = st.cards("computation")
    if prim is not None and comp:
        ok = sum(1 for c in comp if not validate(dict(c), prim["schema"]))
        rep["primitive_contract"] = {"computation_cards": len(comp), "satisfy": ok}
    rep["machines"] = machines(ctx, secs)
    rep["goals"] = goals(ctx, rep, secs)
    return rep


def machines(ctx: Ctx, secs: dict) -> dict:
    st = ctx.store
    out: dict = {"isas": {}}
    for card in st.cards("isa"):
        if card.get("kind") == "isa":
            n = sum(1 for c in st.cards("isa") if c.get("kind") == "instruction" and c.get("isa") == card.name)
            v = ((secs.get("machine") or {}).get("isas") or {}).get(card.name) or {}
            out["isas"][card.name] = {"instruction_cards": n, "passed": v.get("passed"), "failed": v.get("failed"),
                                      "engines": v.get("engines"), "runs": v.get("runs")}
    out["machines"] = sorted(c.name for c in st.cards("machine"))
    out["hardware_cards"] = len(st.cards("hardware"))
    sv = ctx.load_state("emu_survey")
    if sv:
        out["survey"] = {k: sv.get(k) for k in ("folder_files", "frames", "engine", "counts", "unsupported_mappers",
                                                "runs_fraction")}
    diffs = ctx.load_state("emu_diffs") or {}
    if diffs:
        out["lifted_differential"] = {"runs": len(diffs),
                                      "identical": sum(1 for d in diffs.values() if d.get("verdict") == "identical"),
                                      "frames": sum(d.get("frames_compared", 0) for d in diffs.values())}
    tr = ctx.load_state("emu_testroms")
    if tr:
        out["test_roms"] = {"total": tr.get("total"), "passed": tr.get("passed"), "skipped": tr.get("skipped"),
                            "suites": tr.get("suites") or {},
                            "failing": [r["file"].rsplit("/", 1)[-1] for r in tr.get("rows", [])
                                        if r.get("verdict") not in ("pass", "skipped")][:12]}
    nds = ctx.load_state("nds_coverage")
    if nds:
        ld = nds.get("lifted_differential") or {}
        if ld:
            out["nds_lifted"] = {k: ld.get(k) for k in ("verdict", "frames_compared", "blocks", "instructions_lifted",
                                                        "speedup")}
        out["nds"] = {"frames": nds.get("frames"), "cpus": {
            n: {k: c.get(k) for k in ("instructions_executed", "distinct_instruction_addresses", "cards_used",
                                      "undecodable_executed", "unmodelled_hardware_touched", "swi_unmodelled")}
            for n, c in (nds.get("cpus") or {}).items()}}
    return out


def _metric(ctx: Ctx, name: str, rep: dict, secs: dict):
    st = ctx.store
    if name == "languages_fully_conformant":
        conf = secs.get("conformance")
        if not conf:
            return None
        n = 0
        for lang, r in conf["languages"].items():
            cells = [c["status"] for c in r["cells"].values()]
            if r.get("available") and cells and all(c in ("pass", "gap") for c in cells) and "pass" in cells:
                n += 1
        return n
    if name == "op_conformance_rate":
        conf = secs.get("conformance")
        if not conf:
            return None
        good, total = conformance.rate(conf)
        return round(good / total, 4) if total else None
    if name == "forms_witnessed_rate":
        f = secs.get("forms")
        if not f:
            return None
        c = f.get("counts") or {}
        done = c.get("pass", 0) + c.get("fail", 0) + c.get("error", 0)
        return round(c.get("pass", 0) / done, 4) if done else None
    if name == "redefinitions_verified":
        r = secs.get("redefinitions")
        if not r:
            return None
        c = r.get("counts") or {}
        return c.get("verified", 0) + c.get("proved_symbolic", 0)
    if name == "functions_translated":
        fns = secs.get("functions")
        if not fns:
            return None
        return sum(1 for r in fns["cards"].values() if len(r.get("agreeing_languages", [])) >= 3)
    if name == "unresolved_references":
        k = secs.get("kernel")
        return len(k["unresolved_references"]) if k else None
    if name == "rules_witnessed":
        r = secs.get("rules")
        return (r.get("counts") or {}).get("pass") if r else None
    if name == "named_fraction":
        # the model's own code: the newest observation of cardmodel/ (a card, or the cycle's, which observes it
        # on every run); an observation of some other folder never stands in for it while one exists
        obs = sorted(st.cards("observation"), key=lambda c: c.get("observed_at", ""))
        seen = [(c.get("observed_at", ""), c["totals"]["named_fraction"]) for c in obs if c.get("root") == "cardmodel"]
        from ..cycle import evidence
        mine = evidence.self_observation(ctx)
        if mine.get("named_fraction") is not None:
            seen.append((mine.get("observed_at") or "", mine["named_fraction"]))
        if not seen and obs:
            return obs[-1]["totals"]["named_fraction"]
        return max(seen)[1] if seen else None
    if name == "core_ledger_breaks":
        from ..cycle import ledger
        r = ledger.check(ctx)
        return None if r["status"] == "vacuous" else sum(r["counts"][k] for k in ledger.FAILING)
    if name in ("law_witnesses_failing", "store_items_failing", "cycle_regressions"):
        from ..cycle import evidence
        return evidence.summary(ctx).get({"cycle_regressions": "regressions"}.get(name, name))
    if name == "schema_errors":
        k = secs.get("kernel")
        return k["schema_error_cards"] if k else None
    if name == "learned_cards":
        return sum(1 for q, c in st.ALL.items() if (c.metadata or {}).get("learned") and
                   c.registry not in ("proposal", "observation"))
    if name == "measured_forms":
        return len(st.cards("metric"))
    if name == "external_dependencies":
        return 0 if ctx.load_state("self_contained_check", {}).get("ok") else None
    if name == "python_failures":
        pr = secs.get("portability")
        return len(pr.get("failures", [])) if pr else None
    if name == "theorems_proved":
        return sum(1 for c in st.cards("theorem") if c.get("status") == "proved")
    if name == "lean_imported":
        return sum(1 for c in st.cards("theorem") if (c.get("origin") or {}).get("kind") == "lean_core"
                   and any(p.get("method") == "lean:original" and p.get("ok") for p in c.get("proofs") or []))
    if name == "lean_mismatches":
        t = secs.get("theorems")
        return t.get("lean_mismatches") if t else None
    if name == "self_violations":
        lg = secs.get("logic")
        return lg.get("violation_count") if lg else None
    if name == "functional_identities":
        return sum(1 for c in st.cards("functional_identity") if c.get("kind") != "canonical_form")
    if name == "peak_memory_mb":
        return rep.get("peak_memory_mb") if isinstance(rep, dict) and rep.get("peak_memory_mb") else \
            (ctx.load_state("last_verify") or {}).get("peak_memory_mb")
    if name == "design_laws_failing":
        gm = secs.get("game")
        return len(gm.get("failing", [])) if gm and "failing" in gm else None
    if name == "equilibrium_support":
        gm = secs.get("game")
        return len((gm.get("equilibrium") or {}).get("row_mix", {})) if gm and gm.get("equilibrium") else None
    if name.startswith("anyps5_"):
        a = secs.get("anyps5")
        if not a or a.get("status") == "skipped":
            return None
        key = {"anyps5_parity_mismatches": "parity_mismatches", "anyps5_gaps_unclassified": "unclassified",
               "anyps5_closable_open": "closable_open", "anyps5_complete_fraction": "complete_fraction",
               "anyps5_witness_disagreements": "witness_disagreements"}.get(name)
        return a.get(key) if key else None
    if name == "card_programs_passing":
        lang = secs.get("lang")
        return sum(1 for p in lang["programs"].values() if p["status"] == "pass") if lang else None
    if name == "isa_cards_failing":
        m = secs.get("machine")
        return sum(v.get("failed", 0) or 0 for v in (m.get("isas") or {}).values()) if m else None
    if name == "roms_boot_fraction":
        sv = ctx.load_state("emu_survey")
        return sv.get("runs_fraction") if sv else None
    if name == "lifted_runs_differing":
        diffs = ctx.load_state("emu_diffs") or {}
        nds_l = (ctx.load_state("nds_coverage") or {}).get("lifted_differential")
        runs = list(diffs.values()) + ([nds_l] if nds_l else [])
        return sum(1 for d in runs if d.get("verdict") != "identical") if runs else None
    if name == "test_roms_pass_rate":
        tr = ctx.load_state("emu_testroms")
        return round(tr["passed"] / tr["total"], 4) if tr and tr.get("total") else None
    if name == "ds_undecodable_executed":
        nds = ctx.load_state("nds_coverage")
        return sum(c.get("undecodable_executed", 0) for c in (nds.get("cpus") or {}).values()) if nds else None
    runs = sorted(st.cards("arena_run"), key=lambda c: c["score"].get("finished", ""))
    if name == "arena_unsound_runs":
        return sum(1 for r in runs if not r["score"].get("sound")) if runs else None
    if name == "arena_recall":
        return runs[-1]["score"].get("recall") if runs else None
    if name == "arena_geomean_speedup":
        return runs[-1]["score"].get("geomean_speedup") if runs else None
    return None


def goals(ctx: Ctx, rep: dict, secs: dict) -> list[dict]:
    out = []
    for g in sorted(ctx.store.cards("goal"), key=lambda c: c.name):
        value = _metric(ctx, g["metric"], rep, secs)
        met = None if value is None else (value >= g["target"] if g["direction"] == "higher" else value <= g["target"])
        out.append({"goal": g.name, "axis": g["axis"], "metric": g["metric"], "value": value, "target": g["target"],
                    "direction": g["direction"], "met": met})
    return out


def markdown(rep: dict) -> str:
    L = ["# COVERAGE (generated by `cardmodel cover --write`; do not edit)", "",
         f"Generated {rep['generated']} from the cards and the last `cardmodel verify` "
         f"(seed {rep.get('verify_seed')}, {rep.get('verify_started')}).", ""]
    L += ["## Goals", "", "| goal | axis | metric | value | target | met |", "|---|---|---|---:|---:|:---:|"]
    for g in rep["goals"]:
        met = "—" if g["met"] is None else ("yes" if g["met"] else "no")
        val = "not run yet" if g["value"] is None else g["value"]
        L.append(f"| {g['goal']} | {g['axis']} | {g['metric']} | {val} | {g['direction']} {g['target']} | {met} |")
    L += ["", "## Registries", "", f"{rep['total_cards']} cards in {len(rep['registries'])} registries.", "",
          "| registry | cards | packed | layers |", "|---|---:|---:|---|"]
    for name, r in sorted(rep["registries"].items()):
        L.append(f"| {name} | {r['cards']} | {r['packed']} | {', '.join(r['layers'])} |")
    f = rep["form_inventory"]
    L += ["", "## Forms", "", f"{f['total']} forms on op/call/crypto_atom/re_operation/function cards: "
          f"{f['runnable']} runnable, {f['available_here']} available on this host.", "",
          "| language | runnable forms |", "|---|---:|"]
    for lang, n in sorted(f["by_language"].items(), key=lambda kv: -kv[1]):
        L.append(f"| {lang} | {n} |")
    L += ["", "## Languages on this host", "", "| language | codegen | available | toolchain / reason |",
          "|---|:---:|:---:|---|"]
    for lang, r in sorted(rep["languages"].items()):
        L.append(f"| {lang} | {'yes' if r['codegen'] else 'no'} | {'yes' if r['available'] else 'no'} | "
                 f"{r['toolchain'] or r['reason'] or ''} |")
    conf = rep["conformance"]
    L += ["", "## Op x language conformance", ""]
    if isinstance(conf, dict):
        g, t = conf["rate"]
        L += [f"{g} of {t} cells pass (seed {conf['seed']}); gaps are ops a language card declares UNSUPPORTED.", "",
              "| language | pass | fail | error | gap | unavailable |", "|---|---:|---:|---:|---:|---:|"]
        for lang, s in sorted(conf["summary"].items()):
            L.append(f"| {lang} | {s['pass']} | {s['fail']} | {s['error']} | {s['gap']} | {s['unavailable']} |")
    else:
        L.append(conf)
    L += ["", "## Witnesses", ""]
    for sec in ("forms", "vectors", "rules", "redefinitions", "proofs", "functions", "kernel"):
        L.append(f"* **{sec}**: {rep.get(sec)}")
    mc = rep.get("machines") or {}
    if mc:
        L += ["", "## Machines", "", f"Machine cards: {', '.join(mc.get('machines') or [])}; "
              f"{mc.get('hardware_cards')} hardware cards.", "",
              "| ISA | instruction cards | pass | fail | engines | one-instruction runs |", "|---|---:|---:|---:|---|---:|"]
        for name, v in sorted((mc.get("isas") or {}).items()):
            L.append(f"| {name} | {v['instruction_cards']} | {v['passed'] if v['passed'] is not None else 'not run'} | "
                     f"{v['failed'] if v['failed'] is not None else '—'} | {', '.join(v['engines'] or [])} | "
                     f"{v['runs'] if v['runs'] is not None else '—'} |")
        if mc.get("survey"):
            sv = mc["survey"]
            L += ["", f"* **ROM survey** ({sv['folder_files']} ROMs, {sv['frames']} frames each, engine {sv['engine']}): "
                  f"{sv['counts']}; runs {sv['runs_fraction']:.1%}; unsupported bank controllers "
                  f"{sv['unsupported_mappers']}."]
        if mc.get("lifted_differential"):
            d = mc["lifted_differential"]
            L.append(f"* **lifted vs interpreter**: {d['identical']} of {d['runs']} differential runs identical "
                     f"({d['frames']} frames compared).")
        if mc.get("test_roms"):
            t = mc["test_roms"]
            per = ", ".join(f"{k} {v['passed']}/{v['total']}" for k, v in (t.get("suites") or {}).items())
            L.append(f"* **test ROMs**: {t['passed']} of {t['total']} pass ({per}); {t.get('skipped') or 0} skipped "
                     f"(for other hardware revisions, or not self-checking)"
                     + (f"; failing: {', '.join(t['failing'])}." if t.get("failing") else "."))
        else:
            L.append("* **test ROMs**: not run yet (`cardmodel machine testroms DIR`; the suites are not on this "
                     "machine).")
        if mc.get("nds"):
            n = mc["nds"]
            for cpu, c in n["cpus"].items():
                L.append(f"* **DS {cpu}** ({n['frames']} frames): {c['instructions_executed']} instructions, "
                         f"{c['distinct_instruction_addresses']} distinct, {c['cards_used']} cards used, "
                         f"{c['undecodable_executed']} undecodable; not modelled yet: "
                         f"{', '.join(c['unmodelled_hardware_touched'] or {}) or 'nothing'}.")
        if mc.get("nds_lifted"):
            d = mc["nds_lifted"]
            L.append(f"* **DS ARM9 lifted code**: {d['blocks']} blocks ({d['instructions_lifted']} instructions), "
                     f"{d['verdict']} to the interpreter over {d['frames_compared']} frames ({d['speedup']}x).")
    if "primitive_contract" in rep:
        p = rep["primitive_contract"]
        L.append(f"* **primitive_contract**: {p['satisfy']} of {p['computation_cards']} vendored computation cards "
                 f"carry every required field (the rest are spec-level knowledge).")
    return "\n".join(L) + "\n"
