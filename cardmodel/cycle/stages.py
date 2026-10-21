"""stages — what one cycle runs. Each stage takes the run's ``Env`` and returns a dict with a ``status`` (pass,
partial, fail, vacuous, skipped, error), a one-line ``summary`` and the evidence the report reads.

  core      the core ledger (ledger.check); recording accepts growth (a new law, goal, command), never a loss
  verify    every witness: verify's sections (the quick set or all of them), summarised per section, with the
            details the report needs (inconclusive identities, language gaps, functions across languages)
  goals     every goal card's metric against its target (coverage.compute), right after verify
  laws      the witness test of every law card, in a child process with this cycle's seed (CM20)
  learn     the model observing its own code (named fraction, fallback calls, liftable functions) and the
            learning loop on the cycle card's targets, in a sandbox project unless recording; what the language
            cards can and cannot express yet comes from verify's conformance matrix and function cards
  optimize  the arena (verified whole-program optimisation, scored for soundness, recall and speed) and the
            optimizer's verdicts on the op cards' cost anchors, measured on this host
  store     the arcade's catalogue launched through its own service (arcade/client.check_catalog)
  docs      the generated documents in sync with the cards (LAWS.md, GOALS.md's rows, COVERAGE.md's goals, the
            arcade inventory); recording regenerates them
  tests     the whole unit suite, test by test, in a child process

Honest limits (L1): stages share this process except laws and tests (a child each); a stage the budget cannot
fit is skipped and says so; the cycle never promotes the model's own internal calls into the model (names of
its own helpers would only flatter its named fraction), and it keeps arena runs and measurements in its state
instead of writing a card per run.
"""
from __future__ import annotations

import ast
import json
import os
import re
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

from ..kernel import paths, resources


def _home() -> Path:
    return paths.home()


# -- core ------------------------------------------------------------------------------------------------------------
def core(env) -> dict:
    from . import ledger
    r = ledger.check(env.ctx)
    if env.record:
        if r["status"] == "vacuous":
            acc = ledger.accept(env.ctx, reason="first ledger, recorded by the cycle", layer="model")
        else:
            acc = ledger.accept(env.ctx, additions_only=True, layer="model")
        r = dict(ledger.check(env.ctx), accepted_now=acc)
    from ..engines.verify import summary_line
    r["summary"] = summary_line("ledger", r)
    return r


# -- verify ----------------------------------------------------------------------------------------------------------
def _details(rep: dict) -> dict:
    """What the report needs from a verify run, small enough to keep for every run."""
    secs = rep["sections"]
    out: dict = {}
    rd = secs.get("redefinitions")
    if rd:
        out["redefinitions_unsettled"] = {
            q: {k: c.get(k) for k in ("verdict", "valid_points", "examples", "counterexample")}
            for q, c in rd.get("cards", {}).items() if c.get("verdict") not in ("verified", "proved_symbolic")}
    conf = secs.get("conformance")
    if conf:
        out["conformance"] = {
            "summary": conf.get("summary"), "rate": conf.get("rate"),
            "gaps": {lang: sorted(n for n, c in r["cells"].items() if c["status"] == "gap")
                     for lang, r in conf.get("languages", {}).items()},
            "failing": {lang: sorted(n for n, c in r["cells"].items() if c["status"] in ("fail", "error"))
                        for lang, r in conf.get("languages", {}).items()},
            "unavailable": {lang: r.get("probe") for lang, r in conf.get("languages", {}).items()
                            if not r.get("available")}}
    fns = secs.get("functions")
    if fns:
        out["functions"] = {"agreeing": {q: len(r.get("agreeing_languages", []))
                                         for q, r in fns.get("cards", {}).items()},
                            "failing": fns.get("failing", [])}
    for sec, keys in (("forms", ("counts", "hub_claims")), ("theorems", ("counts", "cards", "lean_mismatches")),
                      ("proofs", ("proved", "total", "backend", "reason")), ("lang", ("counts",)),
                      ("machine", ("summary",)), ("game", ("laws_passed", "laws_total", "failing")),
                      ("kernel", ("cards", "registries", "warnings")),
                      ("anyps5", ("declared", "complete", "complete_fraction", "gap_items", "unclassified",
                                  "witness_disagreements", "stale_witnesses", "closable_open"))):
        r = secs.get(sec)
        if r:
            out[sec] = {k: r.get(k) for k in keys if k in r}
    sc = secs.get("selfcheck")
    if sc:
        out["selfcheck"] = {"static_problems": sc.get("static_problems"),
                            "sandbox": (sc.get("sandbox") or {}).get("ok")}
    pt = secs.get("portability")
    if pt:
        out["portability"] = [{k: x.get(k) for k in ("version", "status")} for x in pt.get("runs", [])]
    return out


def verify(env) -> dict:
    from ..engines import verify as V
    sel = env.profile.get("verify")            # "quick", "all", or a list of sections
    secs = list(V.QUICK) if sel == "quick" else [x for x in V.SECTIONS if x in sel] if isinstance(sel, list) \
        else list(V.SECTIONS)
    rep = V.run(env.ctx, seed=env.seed, only=secs, record=env.record_verdicts)
    env.verify_report = rep
    out = {"status": rep["status"], "seed": rep["seed"], "sections": {}, "failures": {},
           "peak_memory_mb": rep.get("peak_memory_mb"), "details": _details(rep)}
    for sec, r in rep["sections"].items():
        out["sections"][sec] = {"status": r.get("status"), "seconds": rep["timings_s"].get(sec),
                                "summary": V.summary_line(sec, r)[:400]}
        if r.get("status") == "fail":
            out["failures"][sec] = json.dumps(V.failures(sec, r), default=str)[:3000]
    n = Counter(s["status"] for s in out["sections"].values())
    out["summary"] = f"{len(out['sections'])} sections: " + ", ".join(f"{v} {k}" for k, v in sorted(n.items()))
    return out


# -- goals -----------------------------------------------------------------------------------------------------------
def goals(env) -> dict:
    from ..engines import coverage
    env.restore_verify()                 # a test may have run a partial verify since (its own last_verify.json)
    rep = coverage.compute(env.ctx)
    rows = rep["goals"]
    met = [g for g in rows if g["met"]]
    unmet = [g for g in rows if g["met"] is False]
    unknown = [g for g in rows if g["met"] is None]
    return {"status": "pass" if not unmet and not unknown else "partial", "goals": rows,
            "met": len(met), "unmet": [g["goal"] for g in unmet], "unknown": [g["goal"] for g in unknown],
            "cards": rep["total_cards"], "registries": len(rep["registries"]),
            "summary": f"{len(met)} of {len(rows)} goals met; unmet: {', '.join(g['goal'] for g in unmet) or 'none'}"
                       + (f"; not measured here: {len(unknown)}" if unknown else "")}


# -- children: law witnesses and the whole suite ----------------------------------------------------------------------
def _test_class(path: Path, test: str) -> str | None:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return None
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            for f in node.body:
                if isinstance(f, ast.FunctionDef) and f.name == test:
                    return node.name
    return None


def run_tests(env, ids: list[str] | None, timeout: float) -> dict:
    """The witness runner in a child (its own compilers take the machine-wide slots, so it holds none itself)."""
    from .witness_runner import MARK
    home = _home()
    child_env = dict(os.environ, PYTHONPATH=str(home), PYTHONDONTWRITEBYTECODE="1", CARDMODEL_AUTO_CYCLE="0",
                     CARDMODEL_TEST_SEED=str(env.seed))
    args = [sys.executable, "-B", "-m", "cardmodel.cycle.witness_runner", *(ids or ["--discover"])]
    try:
        p = resources.run(args, cwd=str(home / "tests"), env=child_env, timeout=timeout, heavy=False,
                          mem_cap_mb=max(2048, resources.policy()["child_mb"]), stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return {"ok": False, "reason": f"the tests did not finish within {timeout:.0f} s", "tests": {}}
    line = next((l for l in reversed((p.stdout or "").splitlines()) if l.startswith(MARK)), None)
    if line is None:
        return {"ok": False, "reason": f"the runner reported nothing (exit {p.returncode}): "
                                       f"{(p.stderr or p.stdout or '')[-800:]}", "tests": {}}
    data = json.loads(line[len(MARK):])
    data["ok"] = True
    return data


def _outcome(tests: dict, tid: str) -> dict:
    if tid in tests:
        return tests[tid]
    mod, _, rest = tid.partition(".")
    cls = rest.partition(".")[0]
    for k in (f"setUpClass ({mod}.{cls})", f"setUpModule ({mod})"):
        if k in tests:
            return dict(tests[k], detail="fixture failed: " + tests[k].get("detail", ""))
    return {"status": "error", "seconds": 0.0, "detail": "not reported by the runner"}


def laws(env) -> dict:
    home = _home()
    rows, ids = {}, {}
    only = set((env.cfg.get("laws") or {}).get("only") or [])      # a narrowed run (tests of the cycle itself)
    for law in sorted(env.ctx.store.cards("law"), key=lambda c: c.name):
        if only and law.name not in only:
            continue
        w = law.get("witness") or ""
        path, _, test = w.partition("::")
        cls = _test_class(home / path, test) if path and test else None
        if cls is None:
            rows[law.name] = {"witness": w, "status": "missing", "detail": "no such test"}
            continue
        tid = f"{Path(path).stem}.{cls}.{test}"
        ids.setdefault(tid, []).append(law.name)
        rows[law.name] = {"witness": w, "test": tid}
    res = run_tests(env, sorted(ids), timeout=env.remaining(cap=1800)) if ids else {"ok": True, "tests": {}}
    for tid, names in ids.items():
        o = _outcome(res.get("tests") or {}, tid) if res.get("ok") else {"status": "error", "detail": res.get("reason")}
        for n in names:
            rows[n].update(status=o["status"], seconds=o.get("seconds"), detail=(o.get("detail") or "")[-800:])
    st = Counter(r["status"] for r in rows.values())
    bad = [n for n, r in rows.items() if r["status"] in ("fail", "error", "missing")]
    env.note(law_witnesses_failing=len(bad))
    return {"status": "fail" if bad else ("pass" if st.get("pass") else "vacuous"), "laws": rows, "failing": bad,
            "counts": dict(st), "seconds_child": res.get("seconds"),
            "summary": f"{st.get('pass', 0)} of {len(rows)} law witnesses pass" +
                       (f"; failing: {', '.join(bad)}" if bad else "") +
                       (f"; skipped here: {st['skip']}" if st.get("skip") else "")}


def tests(env) -> dict:
    only = (env.cfg.get("tests") or {}).get("only") or None       # a narrowed run (tests of the cycle itself)
    res = run_tests(env, only, timeout=env.remaining(cap=3600))
    if not res.get("ok"):
        return {"status": "error", "reason": res.get("reason"), "summary": res.get("reason")}
    rows = res["tests"]
    st = Counter(r["status"] for r in rows.values())
    bad = sorted(t for t, r in rows.items() if r["status"] in ("fail", "error"))
    slow = sorted(((r.get("seconds") or 0, t) for t, r in rows.items()), reverse=True)[:5]
    return {"status": "fail" if bad else "pass", "tests": {t: {"status": r["status"], "seconds": r.get("seconds")}
                                                         for t, r in rows.items()},
            "failing": {t: rows[t].get("detail", "")[-1200:] for t in bad}, "counts": dict(st), "ran": res.get("ran"),
            "seconds_child": res.get("seconds"), "slowest": [[t, s] for s, t in slow],
            "summary": f"{res.get('ran')} tests: " + ", ".join(f"{v} {k}" for k, v in sorted(st.items()))}


# -- learn -----------------------------------------------------------------------------------------------------------
def _sandbox(env):
    """A throwaway project layer under state/cycle: the learning loop writes there unless the cycle records."""
    from ..engines.context import Ctx
    from ..kernel.store import open_store
    d = env.state / "sandbox"
    shutil.rmtree(d, ignore_errors=True)
    (d / ".cardmodel" / "cards").mkdir(parents=True)
    (d / ".cardmodel" / "config.json").write_text(json.dumps({"name": "cycle sandbox"}), encoding="utf-8")
    return Ctx(open_store(project=d))


def learn(env) -> dict:
    from ..engines.learn import learn as learn_loop
    from ..engines.observe import observe
    cfg = env.cfg.get("learn") or {}
    home = _home()
    prof = env.profile_name
    maxf = (cfg.get("max_functions") or {}).get(prof, 6)
    langs = (cfg.get("langs") or {}).get(prof)
    out: dict = {"targets": {}}
    me = cfg.get("self")
    if me:
        obs = observe(env.ctx, home / me)
        t = obs["totals"]
        env.self_observation = {"root": me, "files": t["files"], "named_fraction": t["named_fraction"],
                                "functions": t["functions"], "liftable": t["functions_liftable"],
                                "observed_at": obs.get("observed_at")}
        from . import evidence
        evidence.save_self_observation(env.ctx, env.self_observation)        # the named_fraction goal reads it
        out["self"] = dict(env.self_observation, top_fallback_calls=list(obs["top_fallback_calls"].items())[:15])
    sandbox = _sandbox(env)
    if me:
        try:
            r = learn_loop(sandbox, home / me, promote=True, layer="project", seed=env.seed, max_functions=maxf,
                           langs=langs)
            out["self"].update(proposals=dict(r["proposals"]), ready=dict(r["ready"]))
        except Exception as exc:  # noqa: BLE001 -- the loop failing on the model's own code is a finding
            out["self"]["error"] = f"{type(exc).__name__}: {exc}"
    errors = []
    kinds = set(cfg.get("promote_kinds") or ["function"])
    for target in cfg.get("targets") or []:
        p = home / target
        if not p.exists():
            out["targets"][target] = {"status": "missing"}
            continue
        try:
            if env.record:      # every language, and none may disagree: verify checks a function card in all
                r = learn_loop(env.ctx, p, promote=True, layer="model", seed=env.seed, max_functions=maxf,
                               langs=None, kinds=kinds, keep_pending=False, skip_existing=True, strict=True)
            else:
                r = learn_loop(sandbox, p, promote=True, layer="project", seed=env.seed, max_functions=maxf,
                               langs=langs, kinds=kinds)
            out["targets"][target] = {"status": "pass", "proposals": dict(r["proposals"]), "ready": dict(r["ready"]),
                                      "promoted": r["promoted"][:20], "promoted_count": len(r["promoted"]),
                                      "known": r.get("known", 0), "pending": r["pending"],
                                      "named_fraction": r["totals"]["named_fraction"],
                                      "into": "model" if env.record else "sandbox"}
        except Exception as exc:  # noqa: BLE001 -- reported, the other targets still run
            errors.append(target)
            out["targets"][target] = {"status": "error", "error": f"{type(exc).__name__}: {exc}"[:800]}
    vdet = (env.results.get("verify") or {}).get("details") or {}
    conf = vdet.get("conformance") or {}
    if conf:
        out["languages"] = {lang: {"gaps": len(conf["gaps"].get(lang, [])),
                                   "failing": len(conf["failing"].get(lang, [])),
                                   **(conf.get("summary") or {}).get(lang, {})}
                            for lang in sorted(conf.get("summary") or {})}
        out["unavailable_languages"] = conf.get("unavailable") or {}
    fns = vdet.get("functions") or {}
    if fns.get("agreeing"):
        a = list(fns["agreeing"].values())
        out["functions_across_languages"] = {"cards": len(a), "min_agreeing": min(a), "max_agreeing": max(a)}
    bad = errors + (["self"] if (out.get("self") or {}).get("error") else [])
    nf = (out.get("self") or {}).get("named_fraction")
    out["status"] = "error" if bad else "pass"
    out["summary"] = (f"self-observation {out['self']['files']} files, named fraction {nf:.4f}; " if nf is not None
                      else "") + ", ".join(
        f"{t}: {r.get('promoted_count', 0)} promoted into the {r.get('into', '?')}" if r.get("status") == "pass"
        else f"{t}: {r.get('status')}" for t, r in out["targets"].items()) + \
        (f"; errors in {', '.join(bad)}" if bad else "")
    return out


# -- optimize --------------------------------------------------------------------------------------------------------
def optimize(env) -> dict:
    from ..engines import arena
    from ..engines import optimize as O
    cfg = env.cfg.get("optimize") or {}
    prof = env.profile_name
    out: dict = {}
    count = (cfg.get("arena_count") or {}).get(prof, 8)
    if count:
        res = arena.run(env.ctx, count=count, seed=env.seed)
        sc = res["score"]
        out["arena"] = {k: sc.get(k) for k in ("seed", "count", "functions", "sound", "planted", "planted_improved",
                                                "recall", "geomean_speedup", "max_speedup", "end_to_end",
                                                "effect_shell_identical", "decoys_wrongly_substituted",
                                                "reverted_by_recheck")}
    if (cfg.get("measure_ops") or {}).get(prof):
        rows = []
        for card in env.ctx.store.cards("op"):
            rows += O.measure_python_forms(env.ctx, card, env.seed)
            resources.guard("cycle optimize")
        vs = O.verdicts(rows)
        n = Counter(v["verdict"] for v in vs)
        out["anchors"] = {"measured_forms": len(rows), "verdicts": dict(n),
                          "contradicted": [{k: v.get(k) for k in ("card", "anchor_pick", "measured_pick")}
                                           for v in vs if v["verdict"] == "red"][:20]}
    a = out.get("arena") or {}
    unsound = a and not a.get("sound")
    out["status"] = "fail" if unsound else ("pass" if out else "vacuous")
    parts = []
    if a:
        parts.append(f"arena {a.get('count')} functions: sound={a.get('sound')}, {a.get('planted_improved')}/"
                     f"{a.get('planted')} planted improved, geomean x{a.get('geomean_speedup')}")
    if out.get("anchors"):
        v = out["anchors"]["verdicts"]
        parts.append(f"cost anchors: {v.get('green', 0)} confirmed, {v.get('white', 0)} within noise, "
                     f"{v.get('red', 0)} contradicted by measurement")
    out["summary"] = "; ".join(parts) or "nothing to optimise in this profile"
    return out


# -- the store -------------------------------------------------------------------------------------------------------
def store(env) -> dict:
    from ..arcade import client
    cfg = env.cfg.get("store") or {}
    rep = client.check_catalog(env.ctx, frames=int(cfg.get("frames", 120)), build=bool(cfg.get("build_when_due", True)),
                               progress=lambda m: env.say(f"store: {m}"))
    if (cfg.get("launcher") or {}).get(env.profile_name) and rep["status"] != "skipped":
        from ..arcade.build import BuildError
        from ..arcade.cli import build_launcher
        try:
            build_launcher(env.ctx, False, say=lambda m: None)
            rep["launcher"] = {"ok": True}
        except (BuildError, OSError, KeyError) as exc:
            rep["launcher"] = {"ok": False, "error": str(exc)[-1500:]}
            rep["status"] = "fail"
    ok = [g for g, r in rep["items"].items() if r.get("ok")]
    if rep["status"] != "skipped":
        env.note(store_items_failing=len(rep["items"]) - len(ok))
    rep["summary"] = (rep.get("reason") or f"{len(ok)} of {len(rep['items'])} catalogue items installed, verified, "
                      f"repaired and played through the store") + \
        ("" if (rep.get("pages") or {}).get("ok", True) else "; the launcher's pages name unknown endpoints") + \
        ("; the launcher does not compile" if rep.get("launcher") and not rep["launcher"]["ok"] else "")
    return rep


# -- documents -------------------------------------------------------------------------------------------------------
def _coverage_goal_values(text: str) -> dict:
    out = {}
    for line in text.splitlines():
        m = re.match(r"\| (G_\w+) \| [^|]+\| [^|]+\| ([^|]+) \|", line)
        if m:
            out[m.group(1)] = m.group(2).strip()
    return out


def docs(env) -> dict:
    from ..arcade import inventory
    from ..engines import coverage
    from ..engines.docs import laws_md
    home, st = _home(), env.ctx.store
    out: dict = {}
    laws_text = laws_md(st)
    out["laws_md"] = (home / "LAWS.md").is_file() and (home / "LAWS.md").read_text(encoding="utf-8") == laws_text
    gtext = (home / "GOALS.md").read_text(encoding="utf-8") if (home / "GOALS.md").is_file() else ""
    out["goals_md_missing"] = [g.name for g in st.cards("goal")
                               if not any(f"`{g.name}`" in line for line in gtext.splitlines())]
    rows = (env.results.get("goals") or {}).get("goals") or []
    have = _coverage_goal_values((home / "COVERAGE.md").read_text(encoding="utf-8")) \
        if (home / "COVERAGE.md").is_file() else {}
    out["coverage_stale"] = sorted(g["goal"] for g in rows
                                   if have.get(g["goal"]) != ("not run yet" if g["value"] is None else str(g["value"])))
    inv_text = inventory.markdown(inventory.compute(env.ctx))
    inv_path = home / "docs" / "ARCADE_INVENTORY.md"
    out["inventory"] = inv_path.is_file() and inv_path.read_text(encoding="utf-8") == inv_text
    written = []
    if env.record:
        if not out["laws_md"]:
            (home / "LAWS.md").write_text(laws_text, encoding="utf-8")
            written.append("LAWS.md")
        if out["coverage_stale"]:
            (home / "COVERAGE.md").write_text(coverage.markdown(coverage.compute(env.ctx)), encoding="utf-8")
            written.append("COVERAGE.md")
        if not out["inventory"]:
            inv_path.write_text(inv_text, encoding="utf-8")
            written.append("docs/ARCADE_INVENTORY.md")
    out["written"] = written
    hard = (not out["laws_md"] and "LAWS.md" not in written) or out["goals_md_missing"]
    soft = (out["coverage_stale"] and "COVERAGE.md" not in written) or (not out["inventory"] and not written)
    out["status"] = "fail" if hard else ("partial" if soft else "pass")
    out["summary"] = "; ".join(x for x in [
        "LAWS.md " + ("in sync" if out["laws_md"] else ("regenerated" if "LAWS.md" in written else "STALE")),
        f"GOALS.md misses {', '.join(out['goals_md_missing'])}" if out["goals_md_missing"]
        else "GOALS.md has every goal",
        (f"COVERAGE.md differs from the computed values on {len(out['coverage_stale'])} goals"
         + (" (regenerated)" if "COVERAGE.md" in written else "")) if out["coverage_stale"] else "COVERAGE.md current",
        "arcade inventory " + ("in sync" if out["inventory"] else
                               ("regenerated" if "docs/ARCADE_INVENTORY.md" in written else "stale"))] if x)
    return out


STAGES = {"core": core, "verify": verify, "goals": goals, "laws": laws, "learn": learn, "optimize": optimize,
          "store": store, "docs": docs, "tests": tests}

__all__ = ["STAGES", "run_tests"]
