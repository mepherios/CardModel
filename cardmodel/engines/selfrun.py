"""selfrun — the model runs itself (law CM38): any use can start a cycle that checks, learns, optimizes and
reports, and the model ranks what to improve next.

A cycle runs the ``self_step`` cards in order. Each names a function in ``STEPS`` and when it is due:
``every_hours`` (0: every cycle) and ``on_change`` (registries whose content changed since the step last ran;
the first sighting only records the baseline). The steps:

  capabilities   the core capability smoke checks (CM37: the core is never lost)
  integrity      one program (CM39): unique law and goal numbers, every law carried, everything described
  verify         verify --quick; when the self layer breaks a section that passes without it, the self layer
                 is quarantined (state/self/quarantine/) and the cycle says so (CM22)
  verify_full    every section, the toolchain-heavy ones too; replaces the quick run when both are due
  learn          learn from source trees (the model's examples, the arena's slow framework, the corpora in
                 state/self/config.json): observe in every recognised language, lift Python functions, verify in
                 every language here, promote with evidence, into the self layer; only trees whose files changed
  laws           discover laws when the op cards changed (witnessed, Lean-proved, simplifying ones as rules)
  algebra        canonical forms and identities of the algorithm cards when they changed
  arena          a small arena run: the optimizer's soundness, recall and speed (goals O2-O4)
  optimize       measure the op cards' forms on this host (metric cards, CM09)
  law_witnesses  every law card's witness test, run test by test in a child process with the cycle's seed (CM20)
  observe_self   the model observes its own code (cardmodel/): the named fraction of the code it is made of
  store          every catalogue item launched through the arcade's store as the launcher does it (CM42)
  tests          the whole unit suite, test by test, in a child process
  goals          every goal's value from the latest result of each verify section, against the last cycle

Every step runs under a deadline (what is left of the cycle's budget): a step that does not return in time is
stopped and reported as crashed, and the cycle goes on (CM30).

Then: findings (strengths, weaknesses, flaws, each with its evidence and the command that acts on it), the
plan (findings ranked: self-determinism), the trend against the previous cycle, the record
(``state/self/runs/``, ``state/self/last.json``) and ``state/self/SELF.md`` (``cardmodel self report``).

Nothing tracked is written. Learned cards go to the self layer (``state/self/cards``), which every command loads
read-only above the model's cards, so every use benefits at once; ``cardmodel self adopt`` moves them into the
model's cards for a commit (docs/INTEGRATION.md). A quick cycle never overwrites ``state/last_verify.json``;
a full one does (it is a complete record).

Automatic cycles: ``maybe_start`` (called by every command except the self-maintenance ones) starts a detached
``cardmodel self run --auto`` through the resource governor (background priority, one machine slot, a 2 GB cap,
nothing while memory is short) when CARDMODEL_SELF is not "0", auto is on and the last start was more than
``interval_hours`` ago. One cycle at a time machine-wide (a lock). Tests set CARDMODEL_SELF=0.

Honest limits (L1): the plan ranks by rules written here (severity, then the size of a goal's gap), not by a
learned model; learning promotes cards with evidence and never edits the program's code; a cycle stops early
when its time budget is spent or memory is short, and says which steps it left.
"""
from __future__ import annotations

import ast
import fcntl
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..kernel import paths
from . import values as V
from .context import Ctx

SEVERITY = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
# store_cartridges: how many of the library's cartridges the store step launches (None: every one, about 0.2 s each)
DEFAULT_CONFIG = {"auto": True, "interval_hours": 6, "budget_minutes": 45, "corpora": [], "learn_max_functions": 12,
                  "arena_count": 24, "store_cartridges": None}
KEEP_RUNS = 60
KEEP_LOGS = 20
QUIET = {"self", "install", "clean", "verify", "cover", "docs", "learn", "laws", "arena", "optimize", "improve", "lean"}
DEFAULT_CORPORA = ("examples", "arena/slowframework")
# what measures an unmeasured goal metric: the command a finding proposes
MEASURED_BY = {
    "languages_fully_conformant": "cardmodel verify", "op_conformance_rate": "cardmodel verify",
    "functions_translated": "cardmodel verify", "python_failures": "cardmodel verify",
    "external_dependencies": "cardmodel verify", "named_fraction": "cardmodel learn PATH --promote",
    "learned_cards": "cardmodel self run --only learn", "measured_forms": "cardmodel self run --only optimize",
    "arena_unsound_runs": "cardmodel self run --only arena", "arena_recall": "cardmodel self run --only arena",
    "arena_geomean_speedup": "cardmodel self run --only arena", "roms_boot_fraction": "cardmodel machine survey DIR",
    "lifted_runs_differing": "cardmodel machine diff ROM", "test_roms_pass_rate": "cardmodel machine testroms DIR",
    "ds_undecodable_executed": "cardmodel machine nds ROM", "lean_imported": "cardmodel lean import --core",
    "law_witnesses_failing": "cardmodel self run --only law_witnesses",
    "store_items_failing": "cardmodel self run --only store (or cardmodel arcade check)",
}
# what moves an unmet goal: the command or place a finding proposes
IMPROVED_BY = {
    "redefinitions_verified": "cardmodel verify --only redefinitions (the inconclusive cards need exact forms)",
    "named_fraction": "cardmodel cover (the top fallback calls are the next cards to write); cardmodel self corpus add PATH",
    "anyps5_complete_fraction": "cardmodel anyps5 blocks (the ranked blockers; docs/ANYPS5.md)",
    "anyps5_closable_open": "cardmodel anyps5 gaps --class derivable",
    "functions_translated": "cardmodel learn PATH --promote on code with liftable functions",
    "learned_cards": "cardmodel self corpus add PATH (more trees to learn from)",
    "measured_forms": "cardmodel self run --only optimize",
    "arena_recall": "add algorithm cards for the planted shapes the arena run missed",
    "arena_geomean_speedup": "add faster forms to the algorithm cards the arena substitutes",
    "theorems_proved": "cardmodel laws --save; cardmodel lean import --core",
    "roms_boot_fraction": "cardmodel machine survey DIR (its failures name the missing bank controllers)",
    "test_roms_pass_rate": "cardmodel machine testroms DIR",
    "capabilities_failing": "cardmodel self capabilities",
    "project_card_problems": "revise the project cards verify names (docs/INTEGRATION.md: project cards)",
    "integrity_problems": "cardmodel verify --only integrity",
    "law_witnesses_failing": "cardmodel self run --only law_witnesses (each failing law names its witness test)",
    "store_items_failing": "cardmodel arcade check GAME (it says which step of the launch fails)",
}


# -- where it lives --------------------------------------------------------------------------------------------------
def self_dir() -> Path:
    return paths.home() / "state" / "self"


def layer_dir() -> Path:
    return paths.self_cards()


def active() -> bool:
    """The self layer and automatic cycles are on unless CARDMODEL_SELF=0 (tests, sandboxes)."""
    return os.environ.get("CARDMODEL_SELF", "1") != "0"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(t: datetime) -> str:
    return t.isoformat(timespec="seconds")


def _read(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=1, sort_keys=True, default=str) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def config() -> dict:
    return {**DEFAULT_CONFIG, **(_read(self_dir() / "config.json", {}) or {})}


def save_config(cfg: dict) -> None:
    _write(self_dir() / "config.json", {k: v for k, v in cfg.items() if k in DEFAULT_CONFIG})


class Lock:
    """One cycle at a time, machine-wide for this checkout: a non-blocking flock on state/self/run.lock."""

    def __init__(self):
        self.f = None

    def acquire(self) -> bool:
        self_dir().mkdir(parents=True, exist_ok=True)
        self.f = open(self_dir() / "run.lock", "a")  # noqa: SIM115 -- held for the cycle's lifetime
        try:
            fcntl.flock(self.f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            self.f.close()
            self.f = None
            return False

    def release(self) -> None:
        if self.f is not None:
            fcntl.flock(self.f, fcntl.LOCK_UN)
            self.f.close()
            self.f = None


def busy() -> bool:
    lk = Lock()
    if lk.acquire():
        lk.release()
        return False
    return True


# -- the stores a cycle uses ----------------------------------------------------------------------------------------
def read_ctx() -> Ctx:
    from ..kernel.store import open_store
    return Ctx(open_store(project=False, include_self=True))


def write_ctx() -> Ctx:
    """The model read-only, the self layer writable: everything a cycle learns lands in state/self/cards."""
    from ..kernel.store import Store
    layer_dir().mkdir(parents=True, exist_ok=True)
    return Ctx(Store([("model", paths.model_cards()), ("self", layer_dir())], readonly={"model"}))


def layer_files() -> list[Path]:
    root = layer_dir()
    return sorted(p for p in root.rglob("*") if p.is_file()) if root.is_dir() else []


def registry_hash(ctx: Ctx, registry: str) -> str:
    h = hashlib.sha256()
    for c in sorted(ctx.store.cards(registry), key=lambda c: c.name):
        h.update(json.dumps(dict(c), sort_keys=True, default=str).encode())
    return h.hexdigest()[:16]


def tree_hash(root: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root)
        if p.is_file() and not any(part.startswith(".") or part == "__pycache__" for part in rel.parts):
            st = p.stat()
            h.update(f"{rel}\0{st.st_size}\0{st.st_mtime_ns}\n".encode())
    return h.hexdigest()[:16]


# -- the steps -------------------------------------------------------------------------------------------------------
class Cycle:
    def __init__(self, seed: int, cfg: dict, state: dict, say):
        self.seed, self.cfg, self.state, self.say = seed, cfg, state, say
        self.ctx = read_ctx()
        self._w: Ctx | None = None
        self.deadline = time.monotonic() + float(cfg.get("budget_minutes", 45)) * 60

    def remaining(self, cap: float | None = None) -> float:
        """Seconds left of the cycle's budget (at least a minute, so a step that starts can finish its setup)."""
        left = max(60.0, self.deadline - time.monotonic())
        return min(left, cap) if cap else left

    @property
    def wctx(self) -> Ctx:
        if self._w is None:
            self._w = write_ctx()
        return self._w

    def refresh(self) -> None:
        """After a step wrote into the self layer, later steps see it."""
        sync_registry_meta()
        self.ctx = read_ctx()
        self._w = None


def sync_registry_meta() -> None:
    """A registry the self layer shares with the model gets the model's _category.json, so the merged view's
    metadata (description, tier, status values, references) stays the model's."""
    root, model = layer_dir(), paths.model_cards()
    if not root.is_dir():
        return
    for meta in root.rglob("_category.json"):
        twin = model / meta.relative_to(root)
        if twin.is_file() and twin.read_bytes() != meta.read_bytes():
            meta.write_bytes(twin.read_bytes())


def _capabilities(c: Cycle) -> dict:
    from . import capabilities as K
    r = K.run(c.ctx, c.seed)
    c.state.setdefault("sections", {})["capabilities"] = {"at": _iso(_now()), "seed": c.seed, "result": r}
    caps = {n: {k: v for k, v in x.items() if k in ("status", "seconds", "reason", "evidence", "core", "laws")}
            for n, x in r["capabilities"].items()}
    return {"status": r["status"], "summary": f"{r['counts']}", "failing": r["failing"],
            "unavailable": r["unavailable"], "capabilities": caps}


def _integrity(c: Cycle) -> dict:
    from . import integrity
    r = integrity.check(c.ctx)
    c.state.setdefault("sections", {})["integrity"] = {"at": _iso(_now()), "seed": c.seed, "result": r}
    return {**r, "summary": f"{len(r['problems'])} problems over {r['laws']} laws, {r['goals']} goals, "
                            f"{r['commands']} commands, {r['sections']} sections"}


def _run_verify(c: Cycle, full: bool) -> dict:
    from . import verify
    only = list(verify.SECTIONS) if full else list(verify.QUICK)
    if not full:
        only = [x for x in only if x not in ("capabilities", "integrity")]     # the cycle ran them as steps
    rep = verify.run(c.ctx, seed=c.seed, only=only, save=full)
    secs = c.state.setdefault("sections", {})
    for name, res in rep["sections"].items():
        secs[name] = {"at": rep["started"], "seed": rep["seed"], "result": res}
    c.state["peak_memory_mb"] = rep.get("peak_memory_mb")
    failing = sorted(s for s, r in rep["sections"].items() if r.get("status") == "fail")
    out = {"status": "fail" if failing else "pass", "full": full, "failing": failing, "seed": c.seed,
           "sections": {s: {"status": r.get("status"), **({"reason": r["reason"]} if r.get("reason") else {})}
                        for s, r in rep["sections"].items()},
           "peak_memory_mb": rep.get("peak_memory_mb"), "timings_s": rep.get("timings_s"),
           "summary": f"{len(rep['sections'])} sections, failing {failing or 'none'}"}
    moved = quarantine_if_cause(c, failing)
    if moved:
        out.update(quarantined=str(moved), status="quarantined",
                   summary=f"the self layer broke {failing}; moved to {moved.name} (the model alone passes)")
    return out


def quarantine_if_cause(c: Cycle, failing: list[str]) -> Path | None:
    """If verify sections fail with the self layer and pass without it, the learned cards are the cause:
    move the whole self layer aside (state/self/quarantine/<time>) with the reason. Returns where, or None."""
    from . import verify
    if not failing or not layer_files():
        return None
    from ..kernel.store import open_store
    alone = verify.run(Ctx(open_store(project=False)), seed=c.seed, only=failing, save=False)
    if any(r.get("status") == "fail" for r in alone["sections"].values()):
        return None
    dest = self_dir() / "quarantine" / _now().strftime("%Y%m%dT%H%M%SZ")
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(layer_dir()), str(dest))
    _write(dest / "why.json", {"failing_with_self_layer": failing, "seed": c.seed})
    c.refresh()
    return dest


def _verify(c: Cycle) -> dict:
    return _run_verify(c, full=False)


def _verify_full(c: Cycle) -> dict:
    return _run_verify(c, full=True)


def _slim(res: dict) -> dict:
    """What later cycles need of a step's result to report on it (no per-card details, no goal lists)."""
    keep = ("status", "summary", "failing", "unavailable", "problems", "sections", "quarantined", "promoted",
            "learned", "score", "disagreeing_anchors", "capabilities", "seed", "skipped", "witnesses", "errors",
            "pages", "reason", "details", "named_fraction")
    out = {k: res[k] for k in keep if k in res}
    for r in (out.get("learned") or {}).values():
        r.pop("promoted", None)
    return out


def corpora(cfg: dict) -> list[Path]:
    home = paths.home()
    out = [home / p for p in DEFAULT_CORPORA]
    out += [Path(p).expanduser() for p in cfg.get("corpora") or []]
    return [p.resolve() for p in out if p.exists()]


def _learn(c: Cycle) -> dict:
    from .learn import learn
    seen = c.state.setdefault("corpora", {})
    done, skipped = {}, []
    for root in corpora(c.cfg):
        h = tree_hash(root)
        if seen.get(str(root)) == h and not c.cfg.get("_force"):
            skipped.append(str(root))
            continue
        c.say(f"learning from {root}")
        rep = learn(c.wctx, root, promote=True, layer="self", seed=c.seed,
                    max_functions=int(c.cfg.get("learn_max_functions", 12)))
        done[str(root)] = {"observation": rep["observation"], "proposals": dict(rep["proposals"]),
                           "ready": dict(rep["ready"]), "promoted": rep["promoted"], "pending": rep["pending"]}
        seen[str(root)] = h
    if done:
        c.refresh()
    promoted = sum(len(r["promoted"]) for r in done.values())
    return {"status": "pass" if done else "unchanged", "learned": done, "unchanged": skipped,
            "promoted": promoted, "summary": f"{len(done)} trees learned ({promoted} cards promoted), "
                                             f"{len(skipped)} unchanged"}


def _laws(c: Cycle) -> dict:
    from . import laws as LW
    rep = LW.discover(c.ctx, seed=c.seed, samples=200, lean=True)
    c.wctx.store.save_pack("theorem", "laws", rep["laws"], layer="self")
    c.wctx.store.save_pack("rewrite_rule", "laws", rep["rules"], layer="self")
    c.refresh()
    return {"status": "pass", "candidates": rep["candidates"], "witnessed": rep["witnessed"], "proved": rep["proved"],
            "rules": len(rep["rules"]), "refuted": rep["refuted"],
            "summary": f"{rep['candidates']} candidates: {rep['proved']} proved, {rep['witnessed']} witnessed, "
                       f"{len(rep['rules'])} simplifying rules"}


def _algebra(c: Cycle) -> dict:
    from . import funcalg as FA
    r = FA.scan_algorithms(c.ctx)
    cards = FA.identity_cards(r)
    c.wctx.store.save_pack("functional_identity", "algorithms", cards, layer="self")
    c.refresh()
    return {"status": "fail" if r["problems"] else "pass", "problems": r["problems"], "forms": len(r["forms"]),
            "relations": len(r["relations"]),
            "summary": f"{len(r['forms'])} canonical forms, {len(r['relations'])} identities"
                       + (f"; problems: {r['problems'][:3]}" if r["problems"] else "")}


def _arena(c: Cycle) -> dict:
    from . import arena
    res = arena.run(c.ctx, count=int(c.cfg.get("arena_count", 24)), seed=c.seed)
    name = arena.record(c.wctx, res, layer="self")
    c.refresh()
    sc = res.get("score") or {}
    return {"status": "pass" if sc.get("sound") else "fail", "card": name,
            "score": {k: sc.get(k) for k in ("sound", "recall", "geomean_speedup", "planted", "planted_improved")},
            "summary": f"sound {sc.get('sound')}, recall {sc.get('recall')}, speedup x{sc.get('geomean_speedup')}"}


def _optimize(c: Cycle) -> dict:
    from . import optimize
    rows = []
    for card in c.ctx.store.cards("op"):
        rows += optimize.measure_python_forms(c.ctx, card, c.seed)
    names = optimize.write_metrics(c.wctx, rows, layer="self")
    vs = optimize.verdicts(rows)
    c.refresh()
    red = [v["card"] for v in vs if v["verdict"] == "red"]
    return {"status": "pass", "metrics": len(names), "disagreeing_anchors": red,
            "summary": f"{len(names)} forms measured; cost anchors disagreeing with measurement: {len(red)}"}


def _goals(c: Cycle) -> dict:
    from . import coverage
    secs = {k: v["result"] for k, v in (c.state.get("sections") or {}).items()}
    goals = coverage.goals(c.ctx, {"peak_memory_mb": c.state.get("peak_memory_mb")}, secs)
    for g in goals:
        if g["metric"] == "self_run_age_hours":            # this cycle is running now
            g["value"] = 0.0
            g["met"] = g["value"] <= g["target"]
    met = sum(1 for g in goals if g["met"])
    unmeasured = sum(1 for g in goals if g["met"] is None)
    return {"status": "pass", "goals": goals, "met": met, "total": len(goals), "unmeasured": unmeasured,
            "summary": f"{met} of {len(goals)} goals met, {unmeasured} not measured yet"}


def _test_class(path: Path, test: str) -> str | None:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return None
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and any(isinstance(f, ast.FunctionDef) and f.name == test
                                                   for f in node.body):
            return node.name
    return None


def run_tests(c: Cycle, ids: list[str] | None, timeout: float) -> dict:
    """The witness runner in a child (tests/ as its folder, the cycle's seed, no self layer). It holds no machine
    slot itself: the compilers it starts take theirs."""
    from ..kernel import resources
    from .witness_runner import MARK
    home = paths.home()
    env = dict(os.environ, PYTHONPATH=str(home), PYTHONDONTWRITEBYTECODE="1", CARDMODEL_SELF="0",
               CARDMODEL_TEST_SEED=str(c.seed))
    args = [sys.executable, "-B", "-m", "cardmodel.engines.witness_runner", *(ids or ["--discover"])]
    try:
        p = resources.run(args, cwd=str(home / "tests"), env=env, timeout=timeout, heavy=False,
                          mem_cap_mb=max(2048, resources.policy()["child_mb"]), stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return {"ok": False, "reason": f"the tests did not finish within {timeout:.0f} s", "tests": {}}
    line = next((x for x in reversed((p.stdout or "").splitlines()) if x.startswith(MARK)), None)
    if line is None:
        return {"ok": False, "tests": {},
                "reason": f"the runner reported nothing (exit {p.returncode}): {(p.stderr or p.stdout or '')[-600:]}"}
    return dict(json.loads(line[len(MARK):]), ok=True)


def _outcome(tests: dict, tid: str) -> dict:
    """A test's outcome, or its class's (setUpClass) or module's failure when the test itself never ran."""
    if tid in tests:
        return tests[tid]
    mod, _, rest = tid.partition(".")
    for k in (f"setUpClass ({mod}.{rest.partition('.')[0]})", f"setUpModule ({mod})"):
        if k in tests:
            return dict(tests[k], detail="fixture failed: " + tests[k].get("detail", ""))
    return {"status": "error", "seconds": 0.0, "detail": "not reported by the runner"}


def _law_witnesses(c: Cycle) -> dict:
    home = paths.home()
    rows, ids = {}, {}
    for law in sorted(c.ctx.store.cards("law"), key=lambda x: x.name):
        w = law.get("witness") or ""
        path, _, test = w.partition("::")
        cls = _test_class(home / path, test) if path and test else None
        if cls is None:
            rows[law.name] = {"witness": w, "status": "missing", "detail": "no such test"}
            continue
        tid = f"{Path(path).stem}.{cls}.{test}"
        ids.setdefault(tid, []).append(law.name)
        rows[law.name] = {"witness": w, "test": tid}
    res = run_tests(c, sorted(ids), timeout=c.remaining(cap=1800)) if ids else {"ok": True, "tests": {}}
    for tid, names in ids.items():
        o = _outcome(res["tests"], tid) if res.get("ok") else {"status": "error", "detail": res.get("reason")}
        for n in names:
            rows[n].update(status=o["status"], seconds=o.get("seconds"), detail=(o.get("detail") or "")[-600:])
    failing = sorted(n for n, r in rows.items() if r["status"] in ("fail", "error", "missing"))
    skipped = sorted(n for n, r in rows.items() if r["status"] == "skip")
    result = {"status": "fail" if failing else ("pass" if rows else "vacuous"), "failing": failing,
              "skipped": skipped, "laws": len(rows)}
    c.state.setdefault("sections", {})["law_witnesses"] = {"at": _iso(_now()), "seed": c.seed, "result": result}
    return {**result, "witnesses": rows, "seconds_child": res.get("seconds"),
            "summary": f"{len(rows) - len(failing) - len(skipped)} of {len(rows)} law witnesses pass"
                       + (f"; failing: {', '.join(failing)}" if failing else "")
                       + (f"; skipped on this host: {', '.join(skipped)}" if skipped else "")}


def _observe_self(c: Cycle) -> dict:
    """The model observes its own code; the observation goes to the self layer once per content hash (CM15), so the
    named-fraction goal measures the code the model is made of, not a corpus it learned from."""
    from .observe import observe
    obs = observe(c.ctx, paths.home() / "cardmodel")
    t = obs["totals"]
    new = c.ctx.store.get(f"observation/{obs['name']}") is None
    if new:
        c.wctx.store.save(obs, layer="self", category="observation")
        c.refresh()
    top = [f"{k} x{n}" for k, n in list(obs["top_fallback_calls"].items())[:8] if k != "<expression>"]
    return {"status": "pass", "named_fraction": t["named_fraction"], "files": t["files"],
            "functions": t["functions"], "liftable": t["functions_liftable"], "observation": obs["name"],
            "summary": f"{t['files']} files, named fraction {t['named_fraction']}"
                       + (" (a new observation)" if new else "") + (f"; top unnamed calls {', '.join(top)}" if top else "")}


def _store(c: Cycle) -> dict:
    from ..arcade import client
    limit = c.cfg.get("store_cartridges")            # None: every cartridge the library lists
    rep = client.check_catalog(c.ctx, frames=int(c.cfg.get("store_frames", 60)),
                               progress=lambda m: c.say(f"[self]   store: {m}"),
                               cartridges=None if limit is None else int(limit))
    ok = sorted(g for g, r in rep["items"].items() if r.get("ok"))
    carts = rep.get("cartridges") or {}
    # every entry the store lists that does not launch: its programs, then its cartridges (G_S1 counts both)
    failing = list(rep.get("failing", [])) + [f"cartridge/{i}" for i in carts.get("failed_ids") or []]
    result = {"status": rep["status"], "failing": failing, "items": len(rep["items"]),
              "launched": ok, "pages": (rep.get("pages") or {}).get("ok"), "reason": rep.get("reason"),
              "cartridges": {k: carts.get(k) for k in ("listed", "checked", "launched", "failed", "unplayable")}
              if carts else None}
    c.state.setdefault("sections", {})["store"] = {"at": _iso(_now()), "seed": c.seed, "result": result}
    errors = {g: r.get("error") or r.get("play") for g, r in rep["items"].items() if not r.get("ok")}
    cart_errors = [f"{f['title']}: {f['error']}" for f in carts.get("failing") or []]
    return {**result, "errors": errors, "cartridge_errors": cart_errors[:20],
            "summary": rep.get("reason") or (f"{len(ok)} of {len(rep['items'])} catalogue items installed, "
                                             f"verified, repaired and played through the store"
                                             + (f"; {carts['launched']} of {carts['checked']} listed cartridges "
                                                f"launched in their store-installed player" if carts else "")
                                             + ("" if result["pages"] else "; the launcher's pages are broken"))}


def _tests(c: Cycle) -> dict:
    res = run_tests(c, None, timeout=c.remaining(cap=3600))
    if not res.get("ok"):
        return {"status": "error", "summary": res.get("reason")}
    rows = res["tests"]
    failing = sorted(t for t, r in rows.items() if r["status"] in ("fail", "error"))
    n = {s_: sum(1 for r in rows.values() if r["status"] == s_) for s_ in ("pass", "fail", "error", "skip")}
    return {"status": "fail" if failing else "pass", "failing": failing, "ran": res.get("ran"),
            "details": {t: rows[t].get("detail", "")[-400:] for t in failing[:20]},
            "summary": f"{res.get('ran')} tests: " + ", ".join(f"{v} {k}" for k, v in n.items() if v)}


STEPS = {"capabilities": _capabilities, "integrity": _integrity, "verify": _verify, "verify_full": _verify_full,
         "learn": _learn, "laws": _laws, "algebra": _algebra, "arena": _arena, "optimize": _optimize,
         "law_witnesses": _law_witnesses, "observe_self": _observe_self, "store": _store, "tests": _tests,
         "goals": _goals}


def steps(ctx: Ctx) -> list[dict]:
    out = []
    for c in ctx.store.cards("self_step"):
        out.append({"name": c.name, "run": c.get("run", c.name), "order": c.get("order", 999),
                    "every_hours": c.get("every_hours"), "on_change": list(c.get("on_change") or []),
                    "auto": c.get("auto", True), "statement": c.get("statement", "")})
    return sorted(out, key=lambda s: (s["order"], s["name"]))


def due(step: dict, state: dict, ctx: Ctx, now: datetime) -> tuple[bool, str]:
    last = (state.get("steps") or {}).get(step["name"]) or {}
    reasons = []
    if step["on_change"]:
        hashes = {r: registry_hash(ctx, r) for r in step["on_change"]}
        before = last.get("hashes")
        if before is None:
            state.setdefault("baseline", {})[step["name"]] = hashes
            if step["every_hours"] is None:
                return False, "baseline recorded (runs when these registries change)"
        elif before != hashes:
            reasons.append(f"{', '.join(r for r in hashes if before.get(r) != hashes[r])} changed")
    if step["every_hours"] is not None:
        at = last.get("at")
        if at is None or now - datetime.fromisoformat(at) >= timedelta(hours=float(step["every_hours"])):
            reasons.append("every cycle" if not step["every_hours"] else f"every {step['every_hours']} h")
    return (bool(reasons), "; ".join(reasons) or "not due")


# -- one cycle -------------------------------------------------------------------------------------------------------
def cycle(only: list[str] | None = None, auto: bool = False, force: bool = False, say=print) -> dict:
    lock = Lock()
    if not lock.acquire():
        return {"status": "busy", "reason": "another cycle holds state/self/run.lock"}
    try:
        return _cycle(only, auto, force, say)
    finally:
        lock.release()


def _cycle(only, auto, force, say) -> dict:
    from ..kernel import resources
    t0, started = time.monotonic(), _now()
    cfg = config()
    if force:
        cfg["_force"] = True
    state = _read(self_dir() / "state.json", {}) or {}
    seed = V.fresh_seed()
    c = Cycle(seed, cfg, state, say)
    budget = float(cfg.get("budget_minutes", 45)) * 60
    plan_steps = steps(c.ctx)
    rep = {"started": _iso(started), "seed": seed, "auto": auto, "steps": {}, "skipped": {}, "left": []}
    due_now = {}
    for s in plan_steps:
        if only and s["name"] not in only:
            continue
        if auto and not s["auto"]:
            rep["skipped"][s["name"]] = "manual only"
            continue
        ok, why = (True, "asked for") if (force or only) else due(s, state, c.ctx, started)
        if ok:
            due_now[s["name"]] = why
        else:
            rep["skipped"][s["name"]] = why
    if "verify_full" in due_now and "verify" in due_now:
        rep["skipped"]["verify"] = "covered by verify_full"
        del due_now["verify"]
    for s in plan_steps:
        if s["name"] not in due_now:
            continue
        if time.monotonic() - t0 > budget:
            rep["left"].append({"step": s["name"], "why": "time budget spent"})
            continue
        avail = resources.available_mb()
        if avail is not None and avail < resources.policy()["min_free_mb"]:
            rep["left"].append({"step": s["name"], "why": f"memory short ({avail} MB available)"})
            continue
        fn = STEPS.get(s["run"])
        say(f"[self] {s['name']} ({due_now[s['name']]})")
        t1 = time.monotonic()
        try:
            resources.guard(f"self-run step {s['name']}")
            with resources.deadline(c.remaining()):
                res = fn(c) if fn else {"status": "fail", "summary": f"no step function {s['run']!r} in the program"}
        except Exception as exc:  # noqa: BLE001 -- a crashed step is a finding, not the end of the cycle
            tb = traceback.extract_tb(exc.__traceback__)[-1]
            res = {"status": "error", "summary": f"{type(exc).__name__}: {exc} ({Path(tb.filename).name}:{tb.lineno})"}
        res["seconds"] = round(time.monotonic() - t1, 1)
        res["why"] = due_now[s["name"]]
        rep["steps"][s["name"]] = res
        st = state.setdefault("steps", {}).setdefault(s["name"], {})
        st.update(at=_iso(_now()), status=res.get("status"))
        state.setdefault("results", {})[s["name"]] = {**_slim(res), "at": st["at"]}
        if s["on_change"]:
            st["hashes"] = {r: registry_hash(c.ctx, r) for r in s["on_change"]}
        say(f"[self]   {res.get('status')}: {res.get('summary', '')}  [{res['seconds']} s]")
    for name, hashes in (state.pop("baseline", None) or {}).items():
        state.setdefault("steps", {}).setdefault(name, {}).setdefault("hashes", hashes)
    if "goals" not in rep["steps"] and (not only or "goals" in only):
        rep["steps"]["goals"] = _goals(c)
    rep["goals"] = (rep["steps"].get("goals") or {}).get("goals") or []
    prev = _read(self_dir() / "last.json")
    rep["trend"] = trend(prev, rep)
    latest = {n: {**r, "carried_from": r.get("at")} for n, r in (state.get("results") or {}).items()
              if n not in rep["steps"] and (not only or n in only)}
    rep["findings"] = findings({**rep, "steps": {**latest, **rep["steps"]}}, c.ctx)
    rep["plan"] = plan(rep["findings"])
    rep["self_layer"] = {"files": len(layer_files()), "path": str(layer_dir())}
    rep["finished"] = _iso(_now())
    rep["seconds"] = round(time.monotonic() - t0, 1)
    rep["status"] = "fail" if any(f["severity"] == "critical" for f in rep["findings"]) else "pass"
    state["last_cycle"] = rep["finished"]
    _write(self_dir() / "state.json", state)
    _write(self_dir() / "last.json", rep)
    runs = self_dir() / "runs"
    _write(runs / (started.strftime("%Y%m%dT%H%M%SZ") + ".json"),
           {k: v for k, v in rep.items() if k != "goals"} | {"goals": [
               {k: g[k] for k in ("goal", "value", "met")} for g in rep["goals"]]})
    for old in sorted(runs.glob("*.json"))[:-KEEP_RUNS]:
        old.unlink()
    (self_dir() / "SELF.md").write_text(markdown(rep), encoding="utf-8")
    return rep


# -- what the cycle learned about the model ----------------------------------------------------------------------------
def _finding(kind, severity, area, what, evidence="", action="", auto=False) -> dict:
    return {"kind": kind, "severity": severity, "area": area, "what": what, "evidence": evidence,
            "action": action, "auto": auto}


def findings(rep: dict, ctx: Ctx | None = None) -> list[dict]:
    """Strengths, weaknesses and flaws from a cycle's report, each with its evidence and a next action. Steps
    that did not run this cycle report their latest result (``carried_from`` says from when)."""
    out = _findings(rep)
    for f in out:
        head = f["area"].split("/")[0]
        r = (rep.get("steps") or {}).get({"capability": "capabilities"}.get(head, head)) or {}
        if r.get("carried_from") and f["kind"] != "strength":
            f["evidence"] = (f["evidence"] + "; " if f["evidence"] else "") + f"measured {r['carried_from']}"
    if ctx is not None:
        out += environment_findings(ctx)
    return out


def _findings(rep: dict) -> list[dict]:
    out = []
    steps_ = rep.get("steps") or {}
    caps = steps_.get("capabilities")
    if caps:
        for n, r in (caps.get("capabilities") or {}).items():
            if r["status"] == "fail":
                out.append(_finding("flaw", "critical" if r.get("core", True) else "high", f"capability/{n}",
                                    f"core capability {n} no longer behaves", r.get("reason", ""),
                                    f"cardmodel self capabilities --only {n}; then its witness tests"))
            elif r["status"] == "unavailable":
                out.append(_finding("weakness", "medium", f"capability/{n}", f"{n} cannot run on this host",
                                    r.get("reason", ""), "install what the reason names, then cardmodel probe"))
        passing = sorted(n for n, r in (caps.get("capabilities") or {}).items() if r["status"] == "pass")
        if passing:
            out.append(_finding("strength", "info", "capabilities", f"{len(passing)} core capabilities behave",
                                ", ".join(passing)))
        if not caps.get("capabilities"):
            out.append(_finding("flaw", "critical", "capabilities", "the capability check did not run",
                                caps.get("summary", ""), "cardmodel self capabilities"))
    integ = steps_.get("integrity")
    for p in (integ or {}).get("problems") or []:
        out.append(_finding("flaw", "high", "integrity", "the program is not one piece", p,
                            "fix it, then cardmodel verify --only integrity (docs/INTEGRATION.md)"))
    for name in ("verify", "verify_full"):
        v = steps_.get(name)
        if not v:
            continue
        for sec, r in (v.get("sections") or {}).items():
            if r["status"] == "fail":
                seed = v.get("seed", rep.get("seed"))
                out.append(_finding("flaw", "critical", f"{name}/{sec}", f"verify section {sec} fails",
                                    f"seed {seed}", f"cardmodel verify --only {sec} --seed {seed}"))
            elif r["status"] in ("skipped", "vacuous"):
                out.append(_finding("weakness", "medium", f"{name}/{sec}", f"verify section {sec} is {r['status']}",
                                    r.get("reason", ""), f"cardmodel verify --only {sec}"))
        if v.get("quarantined"):
            out.append(_finding("flaw", "high", "self layer", "learned cards broke verify and were quarantined",
                                v["quarantined"], "inspect the quarantine folder; cardmodel self status"))
        if v.get("status") == "pass":
            out.append(_finding("strength", "info", name, "verify passes", v.get("summary", "")))
    for name, r in steps_.items():
        if r.get("status") == "error":
            out.append(_finding("flaw", "high", f"self/{name}", f"self-run step {name} crashed", r.get("summary", ""),
                                f"cardmodel self run --only {name}"))
    learn = steps_.get("learn") or {}
    if learn.get("promoted"):
        out.append(_finding("strength", "info", "learn", f"learned {learn['promoted']} cards with evidence",
                            learn.get("summary", "")))
    pending = sum(r.get("pending", 0) for r in (learn.get("learned") or {}).values())
    if pending:
        out.append(_finding("weakness", "low", "learn", f"{pending} proposals lack the evidence to be promoted",
                            "registry proposal/ in the self layer", "cardmodel list proposal"))
    arena = steps_.get("arena") or {}
    if arena.get("score"):
        if not arena["score"].get("sound"):
            out.append(_finding("flaw", "critical", "arena", "the optimizer changed a program's behaviour",
                                str(arena["score"]), "cardmodel arena --seed SEED (see the arena_run card)"))
    alg = steps_.get("algebra") or {}
    for p in alg.get("problems") or []:
        out.append(_finding("flaw", "high", "algebra", "an algorithm card's forms do not share one canonical form",
                            p, "cardmodel algebra scan"))
    opt = steps_.get("optimize") or {}
    if opt.get("disagreeing_anchors"):
        out.append(_finding("weakness", "low", "optimize",
                            f"{len(opt['disagreeing_anchors'])} cost anchors disagree with this host's measurements",
                            ", ".join(opt["disagreeing_anchors"][:8]), "cardmodel optimize --apply"))
    lw = steps_.get("law_witnesses") or {}
    for n in lw.get("failing") or []:
        w = (lw.get("witnesses") or {}).get(n) or {}
        out.append(_finding("flaw", "critical", f"law/{n}", f"law {n} is not upheld: its witness test "
                            f"{w.get('status', 'fails')}", (w.get("detail") or "").strip().splitlines()[-1:][0][:300]
                            if (w.get("detail") or "").strip() else w.get("witness", ""),
                            f"cd tests && python3 -B -m unittest {w.get('test', '')}".rstrip()))
    for n in lw.get("skipped") or []:
        out.append(_finding("weakness", "low", f"law/{n}", f"law {n}'s witness is skipped on this host",
                            ((lw.get("witnesses") or {}).get(n) or {}).get("detail", "")[:200]))
    if lw.get("status") == "pass":
        out.append(_finding("strength", "info", "law_witnesses", "every law is upheld by its witness test",
                            lw.get("summary", "")))
    st = steps_.get("store") or {}
    for g in [x for x in st.get("failing") or [] if not x.startswith("cartridge/")]:
        out.append(_finding("flaw", "high", f"store/{g}", f"{g} does not launch through the store",
                            str((st.get("errors") or {}).get(g, ""))[:400], f"cardmodel arcade check {g}"))
    bad = [x for x in st.get("failing") or [] if x.startswith("cartridge/")]
    if bad:
        out.append(_finding("flaw", "high", "store/cartridges", f"{len(bad)} listed cartridges do not launch "
                            "through the store", "; ".join(st.get("cartridge_errors") or [])[:400],
                            "cardmodel arcade check gameboy_player"))
    if st.get("pages") is False:
        out.append(_finding("flaw", "high", "store/pages", "the launcher's pages are missing files or name "
                            "endpoints the service does not have", "", "cardmodel arcade check"))
    if st.get("status") == "skipped":
        out.append(_finding("weakness", "medium", "store", "the store cannot be checked on this host",
                            st.get("reason") or "", "cardmodel probe"))
    elif st.get("status") == "pass":
        out.append(_finding("strength", "info", "store", "the store launches its catalogue", st.get("summary", "")))
    ts = steps_.get("tests") or {}
    for t in (ts.get("failing") or [])[:20]:
        detail = ((ts.get("details") or {}).get(t) or "").strip().splitlines()[-1:]
        out.append(_finding("flaw", "high", f"test/{t}", f"test {t} fails", detail[0][:300] if detail else "",
                            f"cd tests && python3 -B -m unittest {t}"))
    if ts.get("status") == "pass":
        out.append(_finding("strength", "info", "tests", "the whole test suite passes", ts.get("summary", "")))
    for g in rep.get("goals") or []:
        if g["met"] is None:
            out.append(_finding("weakness", "low", f"goal/{g['goal']}", f"{g['goal']} is not measured yet",
                                f"metric {g.get('metric')}", MEASURED_BY.get(g.get("metric"), "cardmodel verify")))
        elif not g["met"]:
            gap = _gap(g)
            out.append(_finding("weakness", "high" if gap >= 0.5 else "medium", f"goal/{g['goal']}",
                                f"{g['goal']} unmet: {g['value']} vs {g['direction']} {g['target']}",
                                f"{g.get('axis')}; gap {round(gap, 3)}",
                                IMPROVED_BY.get(g.get("metric"), MEASURED_BY.get(g.get("metric"), "see GOALS.md"))))
    met = [g["goal"] for g in rep.get("goals") or [] if g["met"]]
    if met:
        out.append(_finding("strength", "info", "goals", f"{len(met)} goals met", ", ".join(met)))
    for t in (rep.get("trend") or {}).get("regressed", []):
        out.append(_finding("flaw", "high", f"goal/{t['goal']}", f"{t['goal']} is no longer met since the last cycle",
                            f"{t['before']} -> {t['now']}", "find the change since the last cycle (git log)"))
    for t in (rep.get("trend") or {}).get("worse", []):
        out.append(_finding("weakness", "medium", f"goal/{t['goal']}", f"{t['goal']} moved further from its target",
                            f"{t['before']} -> {t['now']}", "find the change since the last cycle (git log)"))
    for t in (rep.get("trend") or {}).get("improved", []):
        out.append(_finding("strength", "info", f"goal/{t['goal']}", f"{t['goal']} improved",
                            f"{t['before']} -> {t['now']}"))
    for item in rep.get("left") or []:
        out.append(_finding("weakness", "low", f"self/{item['step']}", f"step {item['step']} did not run",
                            item["why"], f"cardmodel self run --only {item['step']}"))
    return out


def environment_findings(ctx: Ctx) -> list[dict]:
    """What outside the repository depends on this checkout: an installed app (an ``app`` card with an install
    folder) whose bundle records another checkout as its home breaks when that checkout goes away."""
    import plistlib
    out = []
    for app in ctx.store.cards("app"):
        b = app.get("bundle") or {}
        key = next((k for k, v in (b.get("info_plist") or {}).items() if v == "{home}"), None)
        if not key or not app.get("install_dir"):
            continue
        dest = Path(os.path.expanduser(app["install_dir"])) / (app["title"] + b.get("suffix", ""))
        plist = dest / "Contents" / "Info.plist"
        try:
            home = plistlib.loads(plist.read_bytes()).get(key) if plist.is_file() else None
        except (OSError, ValueError):
            home = None
        if home and Path(home).resolve() != paths.home().resolve():
            out.append(_finding("weakness", "high", f"app/{app.name}", f"the installed {app['title']} runs another "
                                "checkout, not this one", f"{dest} -> {home}" + ("" if Path(home).exists() else
                                                                                  " (that folder is gone)"),
                                "cardmodel arcade launcher --install (once that checkout's work is merged here)"))
    return out


def _gap(g: dict) -> float:
    v, t = g["value"], g["target"]
    if not isinstance(v, (int, float)):
        return 1.0
    if g["direction"] == "higher":
        return (t - v) / t if t else 1.0
    return (v - t) / max(abs(t), 1.0)


def plan(found: list[dict], limit: int = 15) -> list[dict]:
    """Self-determinism: what to improve next, most severe first (flaws before weaknesses at equal severity)."""
    todo = [f for f in found if f["kind"] != "strength"]
    todo.sort(key=lambda f: (SEVERITY[f["severity"]], 0 if f["kind"] == "flaw" else 1, f["area"]))
    return [{"rank": i + 1, **f} for i, f in enumerate(todo[:limit])]


def trend(prev: dict | None, rep: dict) -> dict:
    """Goals against the previous cycle. A move that stays within the target is not news (seeds and timings
    vary); a goal that stopped being met regressed, and an unmet goal that got further from its target got worse."""
    if not prev:
        return {"previous": None, "improved": [], "regressed": [], "worse": []}
    before = {g["goal"]: g for g in prev.get("goals") or []}
    improved, regressed, worse = [], [], []
    for g in rep.get("goals") or []:
        b = before.get(g["goal"])
        if not b or b.get("value") is None or g["value"] is None or b["value"] == g["value"]:
            continue
        row = {"goal": g["goal"], "before": b["value"], "now": g["value"]}
        better = (g["value"] > b["value"]) == (g["direction"] == "higher")
        if b.get("met") and not g["met"]:
            regressed.append(row)
        elif not b.get("met") and g["met"]:
            improved.append(row)
        elif not g["met"]:
            (improved if better else worse).append(row)
    return {"previous": prev.get("started"), "improved": improved, "regressed": regressed, "worse": worse}


def markdown(rep: dict) -> str:
    L = ["# SELF — what the model found about itself", "",
         f"Generated by `cardmodel self run` (engines/selfrun.py) at {rep.get('finished')} · seed {rep.get('seed')} · "
         f"{rep.get('seconds')} s · {'automatic' if rep.get('auto') else 'manual'} cycle · status "
         f"**{rep.get('status')}**. Law CM38; how it works: docs/AUTONOMY.md.", ""]

    def block(title, kind):
        rows = [f for f in rep.get("findings") or [] if f["kind"] == kind]
        L.extend([f"## {title}", ""])
        if not rows:
            L.extend(["none", ""])
            return
        for f in sorted(rows, key=lambda f: (SEVERITY[f["severity"]], f["area"])):
            ev = f" — {f['evidence']}" if f["evidence"] else ""
            L.append(f"* **{f['severity']}** `{f['area']}`: {f['what']}{ev}")
        L.append("")

    L.extend(["## Next (ranked)", "", "| # | severity | area | what | action |", "|---:|---|---|---|---|"])
    for p in rep.get("plan") or []:
        L.append(f"| {p['rank']} | {p['severity']} | `{p['area']}` | {p['what']} | `{p['action']}` |")
    L.append("")
    block("Flaws", "flaw")
    block("Weaknesses", "weakness")
    block("Strengths", "strength")
    t = rep.get("trend") or {}
    L.extend(["## Trend", "", f"Against the cycle of {t.get('previous') or '(none yet)'}: "
              f"{len(t.get('improved') or [])} goals improved, {len(t.get('regressed') or [])} stopped being met, "
              f"{len(t.get('worse') or [])} unmet ones got worse (moves within a met target are not counted).", ""])
    L.extend(["## Steps", "", "| step | status | why it ran | seconds | summary |", "|---|---|---|---:|---|"])
    for name, r in (rep.get("steps") or {}).items():
        L.append(f"| {name} | {r.get('status')} | {r.get('why', '')} | {r.get('seconds', '')} | {r.get('summary', '')} |")
    for name, why in (rep.get("skipped") or {}).items():
        L.append(f"| {name} | not run | {why} | | |")
    for item in rep.get("left") or []:
        L.append(f"| {item['step']} | left | {item['why']} | | |")
    caps = ((rep.get("steps") or {}).get("capabilities") or {}).get("capabilities") or {}
    if caps:
        L.extend(["", "## Capabilities (CM37)", "", "| capability | status | laws | evidence |", "|---|---|---|---|"])
        for n, r in caps.items():
            laws = ", ".join(x.split("/")[-1].split("_")[0] for x in r.get("laws") or [])
            L.append(f"| {n} | {r['status']} | {laws} | {r.get('evidence') or r.get('reason', '')} |")
    if rep.get("goals"):
        L.extend(["", "## Goals", "", "| goal | value | target | met |", "|---|---:|---:|:---:|"])
        for g in rep["goals"]:
            met = "—" if g["met"] is None else ("✅" if g["met"] else "❌")
            L.append(f"| {g['goal']} | {g['value'] if g['value'] is not None else 'not run yet'} | "
                     f"{g['direction']} {g['target']} | {met} |")
    L.extend(["", f"Self layer: {(rep.get('self_layer') or {}).get('files', 0)} files in "
              "`state/self/cards` (loaded by every command; `cardmodel self adopt` moves them into `cards/`).", ""])
    return "\n".join(L)


# -- automatic cycles ------------------------------------------------------------------------------------------------
def maybe_start(command: str | None) -> int | None:
    """Start a background cycle if one is due; returns its pid. Never raises (a command must not fail for this)."""
    try:
        if not active() or command in QUIET or os.environ.get("CARDMODEL_SELF_AUTO") == "1":
            return None
        cfg = config()
        if not cfg.get("auto", True):
            return None
        mark = self_dir() / "last_start.json"
        last = (_read(mark, {}) or {}).get("at")
        if last and _now() - datetime.fromisoformat(last) < timedelta(hours=float(cfg.get("interval_hours", 6))):
            return None
        if busy():
            return None
        from ..kernel import resources
        logs = self_dir() / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        for old in sorted(logs.glob("*.log"))[:-KEEP_LOGS]:
            old.unlink()
        env = dict(os.environ, CARDMODEL_SELF_AUTO="1", CARDMODEL_MAX_PARALLEL="1", CARDMODEL_SELF_MB="2048",
                   PYTHONDONTWRITEBYTECODE="1")
        pid = resources.spawn_background([sys.executable, "-B", "-m", "cardmodel", "--no-project", "self", "run",
                                          "--auto"], log_path=logs / (_now().strftime("%Y%m%dT%H%M%SZ") + ".log"),
                                         env=env, cwd=str(paths.home()))
        if pid:
            _write(mark, {"at": _iso(_now()), "pid": pid, "by": command})
        return pid
    except Exception:  # noqa: BLE001 -- best effort by design: the command the user ran comes first
        return None


def status() -> dict:
    last = _read(self_dir() / "last.json") or {}
    state = _read(self_dir() / "state.json", {}) or {}
    cfg = config()
    ctx = read_ctx()
    now = _now()
    due_now = {}
    for s in steps(ctx):
        ok, why = due(s, dict(state), ctx, now)
        due_now[s["name"]] = why if ok else f"not due ({why})"
    started = (_read(self_dir() / "last_start.json", {}) or {})
    return {"active": active(), "auto": cfg.get("auto"), "interval_hours": cfg.get("interval_hours"),
            "busy": busy(), "last_cycle": last.get("finished"), "last_status": last.get("status"),
            "last_auto_start": started.get("at"), "self_layer_files": len(layer_files()),
            "corpora": [str(p) for p in corpora(cfg)], "due": due_now, "plan": (last.get("plan") or [])[:5]}


def adopt(dry_run: bool = False) -> dict:
    """Move the self layer's cards into the model's cards (versioned saves; packs replaced whole), for a commit."""
    from ..kernel.store import Store
    src = layer_dir()
    if not src.is_dir():
        return {"moved": [], "packs": []}
    model = Store([("model", paths.model_cards())])
    learned = Store([("self", src)])
    moved, packs = [], []
    for reg in learned.categories():
        for r in learned.views[reg].regs:
            for pack in sorted(r.path.glob("_pack_*.jsonl")):
                cards = [json.loads(line) for line in pack.read_text(encoding="utf-8").splitlines() if line.strip()]
                packs.append(f"{reg}/{pack.name} ({len(cards)} cards)")
                if not dry_run:
                    model.save_pack(reg, pack.stem[len("_pack_"):], cards, layer="model")
        for card in learned.cards(reg):
            if card.source.startswith("pack:"):
                continue
            moved.append(card.qualified)
            if not dry_run:
                model.save({k: v for k, v in dict(card).items()}, layer="model", category=reg)
    if not dry_run:
        dest = self_dir() / "adopted" / _now().strftime("%Y%m%dT%H%M%SZ")
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dest))
    return {"moved": moved, "packs": packs, "dry_run": dry_run}


__all__ = ["STEPS", "adopt", "busy", "config", "cycle", "due", "environment_findings", "findings", "layer_dir",
           "markdown", "maybe_start", "plan", "save_config", "self_dir", "status", "steps", "trend"]
