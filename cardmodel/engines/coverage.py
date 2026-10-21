"""coverage — what the model represents, can run here, and has witnessed: computed, never claimed (L38).

Questions answered (rea-cards coverage.py style: one number per question):
  1. representation  cards per registry (dir vs packed), card types, laws, goals
  2. forms           runnable / available here / witnessed, per language
  3. translation     the op x language conformance matrix (last verify) and
                     function cards agreeing in >= 3 implementations
  4. witnesses       vectors, rules (numeric + Lean), redefinitions
  5. contracts       how many vendored computation cards satisfy primitive_contract
  6. goals           every goal card's metric against its target

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
    rep["goals"] = goals(ctx, rep, secs)
    return rep


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
        obs = sorted(st.cards("observation"), key=lambda c: c.get("observed_at", ""))
        return obs[-1]["totals"]["named_fraction"] if obs else None
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
    if "primitive_contract" in rep:
        p = rep["primitive_contract"]
        L.append(f"* **primitive_contract**: {p['satisfy']} of {p['computation_cards']} vendored computation cards "
                 f"carry every required field (the rest are spec-level knowledge).")
    return "\n".join(L) + "\n"
