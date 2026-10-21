"""report — a cycle's evidence turned into what to do next: the weakness report (WEAKNESSES.md).

``analyse(run, prev)`` reads the stages of this run and the last one and returns:

  findings      every weakness with a severity (critical, high, medium, low, info), the item, what was seen and
                the action that would address it (a command; ``auto`` when the cycle may run it itself while
                recording): lost or changed core, broken laws, failing or vacuous witnesses, regressions against
                the last run, unmet and unmeasured goals with what would move them, store items that do not
                launch, language gaps, stale documents
  improvements  what got better since the last run
  strengths     what passes, with its numbers: what the model can lean on
  shortfalls    where development falls short: every engine's own declared limits and the ROADMAP's open items
  actions       the next steps the cycle chooses, most severe first, deduplicated

``markdown`` renders it. Severity decides the run's status: a critical or high finding fails the cycle.

Honest limits (L1): regressions compare with the previous run only (not a trend), and seeded witnesses differ
between runs by design, so a moved count is a regression only where the metric is deterministic; the shortfall
lists are read from the engines' docstrings and the ROADMAP, so they are as current as those texts.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

from ..kernel import paths

SEVERITY = ("critical", "high", "medium", "low", "info")
FAILING = ("critical", "high")
HINTS = {
    "roms_boot_fraction": "cardmodel machine survey DIR",
    "lifted_runs_differing": "cardmodel machine diff ROM --frames 3000",
    "test_roms_pass_rate": "cardmodel machine testroms DIR",
    "ds_undecodable_executed": "cardmodel machine nds ROM --frames 600",
    "arena_unsound_runs": "cardmodel arena --count 60",
    "arena_recall": "cardmodel arena --count 60",
    "arena_geomean_speedup": "cardmodel arena --count 60",
    "external_dependencies": "cardmodel verify --only selfcheck",
    "python_failures": "cardmodel verify --only portability",
    "languages_fully_conformant": "cardmodel verify --only conformance",
    "op_conformance_rate": "cardmodel verify --only conformance",
    "functions_translated": "cardmodel verify --only functions",
    "law_witnesses_failing": "cardmodel cycle run --profile standard",
    "store_items_failing": "cardmodel arcade check",
    "cycle_regressions": "cardmodel cycle run",
    "core_ledger_breaks": "cardmodel cycle ledger --accept --reason 'first ledger'",
}
WHY_UNMEASURED = {
    "roms_boot_fraction": "the ROM collection lives outside the model",
    "test_roms_pass_rate": "the hardware test suites live outside the model",
    "lifted_runs_differing": "differential runs need ROMs from outside the model",
    "ds_undecodable_executed": "the DS image lives outside the model",
}


def _f(out, severity, kind, item, message, command=None, auto=False):
    out.append({"severity": severity, "kind": kind, "item": item, "message": message,
                "action": {"command": command, "auto": auto} if command else None})


def _last_line(text) -> str:
    lines = [x for x in str(text or "").strip().splitlines() if x.strip()]
    return lines[-1].strip()[:300] if lines else "no detail"


def _stage(run, name) -> dict:
    return (run.get("stages") or {}).get(name) or {}


def _goal_hint(g: dict, run: dict) -> str:
    v = _stage(run, "verify").get("details") or {}
    if g["metric"] == "redefinitions_verified":
        un = v.get("redefinitions_unsettled") or {}
        if un:
            return "unsettled: " + ", ".join(f"{q.split('/')[-1]} ({c.get('verdict')}, {c.get('valid_points')} valid "
                                             f"points)" for q, c in list(un.items())[:8])
    if g["metric"] == "named_fraction":
        me = _stage(run, "learn").get("self") or {}
        calls = me.get("top_fallback_calls") or []
        if calls:
            return (f"the model's own code ({me.get('files')} files): top unnamed calls "
                    + ", ".join(f"{k}x{n}" for k, n in calls[:8] if k != "<expression>"))
    return ""


def honest_limits() -> list[dict]:
    """Every module's own 'Honest limits' paragraph: where the engines say they fall short."""
    out = []
    root = paths.home() / "cardmodel"
    for f in sorted(root.rglob("*.py")):
        try:
            doc = ast.get_docstring(ast.parse(f.read_text(encoding="utf-8"))) or ""
        except (OSError, SyntaxError):
            continue
        m = re.search(r"Honest limits(?: \(L1\))?:\s*(.+?)(?:\n\s*\n|$)", doc, re.S)
        if m:
            out.append({"module": str(f.relative_to(root.parent)), "limit": " ".join(m.group(1).split())})
    return out


def roadmap_open() -> list[dict]:
    """The ROADMAP's ready-but-not-built items (🟢), with their section."""
    p = paths.home() / "ROADMAP.md"
    if not p.is_file():
        return []
    out, section = [], ""
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            section = line[3:].strip()
        m = re.match(r"\*\s+🟢\s+(?:\*\*(.+?)\*\*|(.+))", line)
        if m:
            out.append({"section": section, "item": (m.group(1) or m.group(2) or "").strip().rstrip(".")})
    return out


def _cmp_status(prev_s, cur_s) -> str | None:
    good = ("pass",)
    if prev_s in good and cur_s in ("fail", "error"):
        return "worse"
    if prev_s in ("fail", "error") and cur_s in good:
        return "better"
    return None


def regressions(run: dict, prev: dict | None, cfg: dict) -> tuple[list, list]:
    """(regressions, improvements) of this run against the previous one."""
    reg, imp = [], []
    if not prev:
        return reg, imp
    tol = float((cfg.get("regression") or {}).get("metric_tolerance", 1e-9))
    for name, cur in (run.get("stages") or {}).items():
        old = _stage(prev, name)
        if not old:
            continue
        c = _cmp_status(old.get("status"), cur.get("status"))
        if c == "worse":
            reg.append(("high", f"stage/{name}", f"the {name} stage passed last run and is {cur.get('status')} now"))
        elif c == "better":
            imp.append(f"the {name} stage passes again")
    vs, vo = _stage(run, "verify").get("sections") or {}, _stage(prev, "verify").get("sections") or {}
    for sec, r in vs.items():
        o = vo.get(sec)
        if o and o.get("status") == "pass" and r.get("status") != "pass":
            reg.append(("high", f"verify/{sec}", f"verify {sec} passed last run and is {r.get('status')} now: "
                                                  f"{r.get('summary', '')[:200]}"))
        elif o and o.get("status") != "pass" and r.get("status") == "pass":
            imp.append(f"verify {sec} passes now (was {o.get('status')})")
    gs = {g["goal"]: g for g in _stage(run, "goals").get("goals") or []}
    go = {g["goal"]: g for g in _stage(prev, "goals").get("goals") or []}
    for n, g in gs.items():
        o = go.get(n)
        if not o or g["value"] is None or o["value"] is None:
            continue
        if o["met"] and g["met"] is False:
            reg.append(("high", f"goal/{n}", f"{n} was met ({o['value']}) and is not now ({g['value']}, "
                                             f"{g['direction']} {g['target']})"))
            continue
        if not o["met"] and g["met"]:
            imp.append(f"{n} is met now ({o['value']} -> {g['value']})")
            continue
        try:
            dv = float(g["value"]) - float(o["value"])
        except (TypeError, ValueError):
            continue
        worse = dv < -tol if g["direction"] == "higher" else dv > tol
        better = dv > tol if g["direction"] == "higher" else dv < -tol
        if worse and n != "G_A3_memory_bounded":
            reg.append(("medium", f"goal/{n}", f"{n} slipped from {o['value']} to {g['value']} "
                                               f"({g['direction']} is better; target {g['target']})"))
        elif better:
            imp.append(f"{n} moved from {o['value']} to {g['value']}")
    ls, lo = _stage(run, "laws").get("laws") or {}, _stage(prev, "laws").get("laws") or {}
    for n, r in ls.items():
        o = lo.get(n)
        if o and o.get("status") == "pass" and r.get("status") in ("fail", "error", "missing"):
            reg.append(("critical", f"law/{n}", f"the witness of {n} passed last run and is {r['status']} now"))
    ts, to = _stage(run, "tests").get("tests") or {}, _stage(prev, "tests").get("tests") or {}
    for t, r in ts.items():
        o = to.get(t)
        if o and o.get("status") == "pass" and r.get("status") in ("fail", "error"):
            reg.append(("high", f"test/{t}", f"{t} passed last run and {r['status']}s now"))
    if to and ts:
        gone = sorted(set(to) - set(ts))
        if gone:
            reg.append(("medium", "tests", f"{len(gone)} tests that ran last time did not run now: "
                                           + ", ".join(gone[:6])))
    ss, so = (_stage(run, "store").get("items") or {}), (_stage(prev, "store").get("items") or {})
    for gid, r in ss.items():
        o = so.get(gid)
        if o and o.get("ok") and not r.get("ok"):
            reg.append(("high", f"store/{gid}", f"{gid} launched through the store last run and fails now"))
    a, ao = _stage(run, "optimize").get("arena") or {}, _stage(prev, "optimize").get("arena") or {}
    if ao.get("sound") and a and not a.get("sound"):
        reg.append(("critical", "arena", "the arena was sound last run and is not now"))
    me, mo = _stage(run, "learn").get("self") or {}, _stage(prev, "learn").get("self") or {}
    if me.get("named_fraction") is not None and mo.get("named_fraction") is not None:
        d = me["named_fraction"] - mo["named_fraction"]
        if d < -0.005:
            reg.append(("medium", "self/named_fraction", f"the named fraction of the model's own code fell from "
                                                         f"{mo['named_fraction']} to {me['named_fraction']}"))
        elif d > 0.005:
            imp.append(f"the named fraction of the model's own code rose to {me['named_fraction']}")
    rc = cfg.get("regression") or {}
    fac, floor = float(rc.get("timing_factor", 2.5)), float(rc.get("min_timing_s", 5.0))
    if prev.get("profile") == run.get("profile"):          # a quick run's stages are not a full run's
        for name, cur in (run.get("stages") or {}).items():
            o, s = _stage(prev, name).get("seconds"), cur.get("seconds")
            if o and s and s > floor and s > fac * o:
                reg.append(("low", f"time/{name}", f"the {name} stage took {s:.0f} s (last run {o:.0f} s)"))
    return reg, imp


def analyse(run: dict, prev: dict | None, cfg: dict) -> dict:
    F: list = []
    st = run.get("stages") or {}
    rec = bool(run.get("record"))
    # the core
    c = st.get("core") or {}
    for kind, sev in (("lost", "critical"), ("changed", "critical"), ("weakened", "critical")):
        for x in c.get(kind) or []:
            _f(F, sev, f"core_{kind}", x["item"], f"{x['item']} {kind}: {x.get('detail', '')}",
               "restore it, or accept the change: cardmodel cycle ledger --accept --reason '...'")
    if c.get("status") == "vacuous":
        _f(F, "high", "core_unprotected", "ledger/core", "there is no core ledger: nothing protects the laws yet",
           "cardmodel cycle ledger --accept --reason 'first ledger'", auto=True)
    new = c.get("new") or []
    if new and not rec:
        _f(F, "low", "core_unrecorded", "ledger/core", f"{len(new)} item(s) not in the core ledger yet: "
           + ", ".join(x["item"] for x in new[:8]), "cardmodel cycle ledger --accept --additions", auto=True)
    # every witness
    v = st.get("verify") or {}
    for sec, r in (v.get("sections") or {}).items():
        s = r.get("status")
        if s == "fail":
            _f(F, "high", "witness_failed", f"verify/{sec}", f"verify {sec} fails: "
               + (v.get("failures") or {}).get(sec, r.get("summary", ""))[:600], f"cardmodel verify --only {sec}")
        elif s == "vacuous":
            _f(F, "medium", "vacuous_section", f"verify/{sec}",
               f"verify {sec} ran no checks (CM07): {r.get('summary')}")
        elif s in ("skipped", "partial"):
            _f(F, "low", "section_not_run", f"verify/{sec}", f"verify {sec} is {s}: {r.get('summary')}")
    for q, r in ((v.get("details") or {}).get("redefinitions_unsettled") or {}).items():
        if not r.get("valid_points"):
            ex = r.get("examples") or {}
            _f(F, "medium", "vacuous_witness", q, f"{q}: the witness found 0 valid points"
               + (f" and {ex.get('incomplete', 0)} of {ex.get('total', 0)} examples could not be evaluated"
                  if ex else "") + " (inconclusive, so it does not count; CM07)",
               f"cardmodel verify --only redefinitions; fix the card's domain or forms so it can be evaluated")
        else:
            _f(F, "low", "inconclusive", q, f"{q}: {r.get('verdict')} on {r.get('valid_points')} points")
    # laws
    lw = st.get("laws") or {}
    for n, r in (lw.get("laws") or {}).items():
        if r.get("status") in ("fail", "error"):
            _f(F, "critical", "law_broken", f"law/{n}", f"{n}: its witness {r.get('witness')} {r['status']}s: "
               f"{_last_line(r.get('detail'))}", f"cd tests && python3 -B -m unittest {r.get('test')}")
        elif r.get("status") == "missing":
            _f(F, "critical", "law_unwitnessed", f"law/{n}", f"{n} names {r.get('witness')}, which does not exist")
        elif r.get("status") == "skip":
            _f(F, "low", "law_unchecked_here", f"law/{n}", f"{n}: its witness is skipped on this machine "
                                                            f"({(r.get('detail') or '')[:160]})")
    # goals
    for g in (st.get("goals") or {}).get("goals") or []:
        if g["met"] is False:
            hint = _goal_hint(g, run)
            _f(F, "medium", "goal_unmet", f"goal/{g['goal']}", f"{g['goal']}: {g['value']} against {g['direction']} "
               f"{g['target']}" + (f" — {hint}" if hint else ""))
        elif g["met"] is None:
            why = WHY_UNMEASURED.get(g["metric"])
            _f(F, "low", "goal_unmeasured", f"goal/{g['goal']}", f"{g['goal']} ({g['metric']}) has no value in this "
               "checkout yet" + (f" ({why})" if why else ""), HINTS.get(g["metric"]))
    # learning
    ln = st.get("learn") or {}
    if (ln.get("self") or {}).get("error"):
        _f(F, "high", "self_learning_broken", "learn/self", f"the learning loop fails on the model's own code: "
           f"{ln['self']['error']}")
    for t, r in (ln.get("targets") or {}).items():
        if r.get("status") in ("error", "missing"):
            _f(F, "high", "learning_broken", f"learn/{t}", f"learning on {t}: {r.get('error') or r.get('status')}")
    for lang, why in (ln.get("unavailable_languages") or {}).items():
        _f(F, "low", "language_unavailable", f"language/{lang}", f"{lang} has no toolchain here ({why}): its "
           "conformance row and function translations are not checked on this machine")
    gaps = ((v.get("details") or {}).get("conformance") or {}).get("gaps") or {}
    for lang, ops in sorted(gaps.items(), key=lambda kv: -len(kv[1])):
        if ops:
            _f(F, "low", "language_gap", f"language/{lang}", f"{lang} cannot express {len(ops)} op(s) yet (declared "
               f"UNSUPPORTED): {', '.join(ops[:10])}{' ...' if len(ops) > 10 else ''}",
               f"add the templates to cards/language/{lang} (or the op cards' emit), then cardmodel verify --only "
               "conformance")
    me = ln.get("self") or {}
    if me.get("ready"):
        _f(F, "info", "learning_ready", "learn/self", "the learning loop has evidence for "
           + ", ".join(f"{n} {k} card(s)" for k, n in me["ready"].items())
           + " in the model's own code (call names stay unpromoted: they would only flatter the named fraction)")
    # optimisation
    op = st.get("optimize") or {}
    a = op.get("arena") or {}
    if a and not a.get("sound"):
        _f(F, "critical", "unsound_optimization", "arena", f"the arena run (seed {a.get('seed')}) was not sound: "
           f"end-to-end {a.get('end_to_end')}, effect shell identical {a.get('effect_shell_identical')}, decoys "
           f"wrongly substituted {a.get('decoys_wrongly_substituted')}", f"cardmodel arena --count {a.get('count')} "
           f"--seed {a.get('seed')}")
    elif a and a.get("planted") and a.get("planted_improved", 0) < a["planted"]:
        _f(F, "low", "arena_missed", "arena", f"{a['planted'] - a['planted_improved']} of {a['planted']} planted slow "
           f"functions were not improved (seed {a.get('seed')})", "add algorithm cards (HANDOVER 3b)")
    for x in (op.get("anchors") or {}).get("contradicted") or []:
        _f(F, "low", "cost_anchor_contradicted", x.get("card"), f"{x.get('card')}: the anchors pick "
           f"{x.get('anchor_pick')}, the measurement picks {x.get('measured_pick')}", "cardmodel optimize --apply")
    # the store
    so = st.get("store") or {}
    for gid, r in (so.get("items") or {}).items():
        if not r.get("ok"):
            _f(F, "high", "store_item_fails", f"store/{gid}", f"{gid} does not launch through the store: "
               f"{r.get('error') or r.get('play')}", f"cardmodel arcade check {gid}")
    if so.get("status") == "skipped":
        _f(F, "low", "store_unchecked", "store", f"the store was not checked here: {so.get('reason')}")
    pg = so.get("pages") or {}
    if pg and not pg.get("ok"):
        _f(F, "high", "store_pages", "store/pages", f"the launcher's pages: missing {pg.get('missing')}, unknown "
                                                    f"endpoints {pg.get('unknown_endpoints')}")
    if so.get("launcher") and not so["launcher"].get("ok"):
        _f(F, "high", "launcher_broken", "app/arcade",
           f"the launcher does not compile: {so['launcher']['error'][:400]}")
    # documents
    dc = st.get("docs") or {}
    if dc:
        if dc.get("laws_md") is False and "LAWS.md" not in (dc.get("written") or []):
            _f(F, "medium", "doc_stale", "LAWS.md", "LAWS.md drifted from the law cards", "cardmodel docs", auto=True)
        if dc.get("goals_md_missing"):
            _f(F, "medium", "doc_stale", "GOALS.md", f"GOALS.md has no row for {', '.join(dc['goals_md_missing'])}")
        if dc.get("coverage_stale") and "COVERAGE.md" not in (dc.get("written") or []):
            _f(F, "low", "doc_stale", "COVERAGE.md", f"COVERAGE.md differs from the computed values on "
               f"{len(dc['coverage_stale'])} goal(s): {', '.join(dc['coverage_stale'][:8])}",
               "cardmodel cover --write COVERAGE.md", auto=True)
        if dc.get("inventory") is False and "docs/ARCADE_INVENTORY.md" not in (dc.get("written") or []):
            _f(F, "low", "doc_stale", "docs/ARCADE_INVENTORY.md", "the arcade inventory drifted from the cards",
               "cardmodel arcade inventory --write docs/ARCADE_INVENTORY.md", auto=True)
    # the suite
    for t, d in list(((st.get("tests") or {}).get("failing") or {}).items())[:20]:
        _f(F, "high", "test_failed", f"test/{t}", f"{t}: {_last_line(d)}", f"cd tests && python3 -B -m unittest {t}")
    # stages that did not run
    for name, r in st.items():
        if r.get("status") == "error" and (r.get("error") or r.get("reason")):   # learn's own errors are above
            _f(F, "high", "stage_error", f"stage/{name}",
               f"the {name} stage stopped: {r.get('error') or r.get('reason')}")
        elif r.get("status") == "skipped" and r.get("reason", "").startswith("budget"):
            _f(F, "low", "stage_skipped", f"stage/{name}", f"the {name} stage was skipped: {r['reason']}")
    reg, imp = regressions(run, prev, cfg)
    for sev, item, msg in reg:
        _f(F, sev, "regression", item, msg)
    order = {s: i for i, s in enumerate(SEVERITY)}
    F.sort(key=lambda x: (order[x["severity"]], x["kind"], str(x["item"])))
    actions, seen = [], set()
    for x in F:
        a_ = x.get("action")
        if a_ and a_["command"] not in seen and x["severity"] != "info":
            seen.add(a_["command"])
            actions.append({"command": a_["command"], "why": x["message"][:240], "severity": x["severity"],
                            "auto": a_["auto"]})
    return {"findings": F, "regressions": len(reg), "improvements": imp, "actions": actions,
            "strengths": strengths(run), "counts": {s: sum(1 for x in F if x["severity"] == s) for s in SEVERITY},
            "status": "fail" if any(x["severity"] in FAILING for x in F) else "pass"}


def strengths(run: dict) -> list[str]:
    st = run.get("stages") or {}
    out = []
    goals = (st.get("goals") or {}).get("goals") or []
    met = [g for g in goals if g["met"]]
    if goals:
        out.append(f"{len(met)} of {len(goals)} goals met, among them: " + "; ".join(
            f"{g['goal']} {g['value']} ({g['direction']} {g['target']})" for g in met[:12]))
    v = st.get("verify") or {}
    passing = [s for s, r in (v.get("sections") or {}).items() if r.get("status") == "pass"]
    if passing:
        out.append(f"{len(passing)} verify sections pass with seed {v.get('seed')}: {', '.join(passing)}")
    lw = st.get("laws") or {}
    if lw.get("counts", {}).get("pass"):
        out.append(f"{lw['counts']['pass']} of {len(lw.get('laws') or {})} laws are upheld by their witness tests")
    c = st.get("core") or {}
    if c.get("status") == "pass":
        p = c.get("protected") or {}
        out.append(f"the core is intact: {p.get('laws')} laws, {p.get('goals')} goals, {p.get('commands')} commands, "
                   f"{p.get('registries')} registries and {p.get('verify_sections')} verify sections kept")
    langs = (st.get("learn") or {}).get("languages") or {}
    full = [l for l, r in langs.items() if r.get("pass") and not r.get("fail") and not r.get("error")]
    if full:
        out.append(f"{len(full)} languages pass every op template they declare ({', '.join(full)})")
    fl = (st.get("learn") or {}).get("functions_across_languages")
    if fl:
        out.append(f"{fl['cards']} function cards agree across {fl['min_agreeing']}-{fl['max_agreeing']} "
                   "implementations each")
    a = (st.get("optimize") or {}).get("arena") or {}
    if a.get("sound"):
        out.append(f"optimisation is sound: the arena improved {a.get('planted_improved')} of {a.get('planted')} "
                   f"planted functions (geomean x{a.get('geomean_speedup')}) with no wrong substitution")
    so = st.get("store") or {}
    ok = [g for g, r in (so.get("items") or {}).items() if r.get("ok")]
    if ok:
        out.append(f"the store launches {', '.join(ok)}: built from cards, downloaded and checked chunk by chunk, "
                   "repaired, played natively")
    ts = st.get("tests") or {}
    if ts.get("counts", {}).get("pass"):
        out.append(f"{ts['counts']['pass']} unit tests pass")
    return out


def _md_escape(s: str) -> str:
    return str(s).replace("|", "\\|").replace("\n", " ")


def markdown(run: dict, an: dict, prev: dict | None) -> str:
    L = ["# WEAKNESSES (generated by `cardmodel cycle`; do not edit)", "",
         f"Cycle of {run['started']} · profile {run['profile']} · seed {run['seed']} · {run['seconds']:.0f} s · "
         f"{'recorded' if run.get('record') else 'not recorded'} · **{an['status']}** "
         f"({', '.join(f'{n} {s}' for s, n in an['counts'].items() if n)})."]
    L.append(f"Compared with the run of {prev['started']} (profile {prev['profile']})." if prev else
             "No earlier run to compare with.")
    L += ["", "## Stages", "", "| stage | status | seconds | what it found |", "|---|---|---:|---|"]
    for name, r in (run.get("stages") or {}).items():
        L.append(f"| {name} | {r.get('status')} | {r.get('seconds', 0):.1f} | "
                 f"{_md_escape(r.get('summary', ''))[:400]} |")
    groups = [("critical", "Critical: the core, the laws, soundness"), ("high", "High: failing, broken or regressed"),
              ("medium", "Medium: vacuous witnesses, unmet goals, slipping numbers"),
              ("low", "Low: unmeasured, unavailable, gaps, stale documents"), ("info", "Notes")]
    for sev, title in groups:
        xs = [x for x in an["findings"] if x["severity"] == sev]
        if not xs:
            continue
        L += ["", f"## {title} ({len(xs)})", ""]
        for x in xs[:60]:
            act = x.get("action")
            L.append(f"* **{x['kind']}** `{x['item']}`: {x['message']}"
                     + (f" → `{act['command']}`" if act and act.get("command") else ""))
        if len(xs) > 60:
            L.append(f"* … and {len(xs) - 60} more in state/cycle/last.json")
    if an["improvements"]:
        L += ["", "## Better since the last run", ""] + [f"* {x}" for x in an["improvements"]]
    L += ["", "## Strengths (what to lean on)", ""] + [f"* {x}" for x in an["strengths"]]
    L += ["", "## Next actions (chosen by the cycle)", "", "| # | severity | action | why | the cycle runs it |",
          "|---:|---|---|---|---|"]
    for i, a in enumerate(an["actions"][:25], 1):
        L.append(f"| {i} | {a['severity']} | `{_md_escape(a['command'])}` | {_md_escape(a['why'])[:200]} | "
                 f"{'yes, when recording' if a['auto'] else 'no: needs a person'} |")
    sl = run.get("shortfalls") or {}
    if sl:
        L += ["", "## Where development falls short", "",
              f"### Open on the ROADMAP ({len(sl.get('roadmap') or [])} items marked ready but not built)", ""]
        L += [f"* {x['section']}: {x['item']}" for x in sl.get("roadmap") or []]
        L += ["", f"### Declared by the engines themselves ({len(sl.get('limits') or [])} modules state their limits)",
              ""]
        L += [f"* `{x['module']}`: {x['limit'][:400]}" for x in sl.get("limits") or []]
    L.append("")
    return "\n".join(L)


__all__ = ["SEVERITY", "analyse", "honest_limits", "markdown", "regressions", "roadmap_open", "strengths"]
