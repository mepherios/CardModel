"""capabilities — the model's core as cards, each with a smoke check that runs in every verify and every
self-run (law CM37: the core is never lost).

A ``capability`` card names one thing the model can do, the laws it carries, the tests that witness it in
depth, the docs that explain it and the commands that use it. Its ``check`` names a function in ``CHECKS``:
a small, fast run of the real engine on a fixed example (not an import, not a mock) that passes only while
the capability still behaves. ``run`` executes them. A check that cannot run on this host (a missing
toolchain, no AnyPS5 scan) is ``unavailable`` with the reason, never a pass (CM07, CM12). Every check works
on scratch stores or reads the live store; none writes into the model's cards or its verify record.

Honest limits (L1): a smoke check is a canary, not the proof. The witness tests (tests/) and the verify
sections go deep; a passing check says the capability is present and behaves on its example, nothing more.
"""
from __future__ import annotations

import json
import random
import shutil
import sys
import tempfile
import time
import traceback
from pathlib import Path

from .context import Ctx


class Lost(Exception):
    """The capability did not behave: what was expected and what happened."""


class Unavailable(Exception):
    """The capability cannot be exercised on this host (the reason says what is missing)."""


def _need(cond, why: str) -> None:
    if not cond:
        raise Lost(why)


def _tmp(prefix: str = "cardmodel_cap_") -> Path:
    return Path(tempfile.mkdtemp(prefix=prefix))


def _theorem(ctx: Ctx, text: str):
    from ..lang.compile import compile_source
    return compile_source(text, ctx.ops, ctx.store, name="capability").theorems[0]


# -- the checks ---------------------------------------------------------------------------------------------
def card_store(ctx: Ctx, seed: int) -> str:
    from ..kernel.store import Store
    from ..kernel.types import closure
    d = _tmp()
    try:
        st = Store([("model", d)])
        st.save({"name": "w", "category": "widgets", "statement": "one", "carried_field": {"kept": True}})
        again = Store([("model", d)]).get("widgets/w")
        _need(again is not None and again.get("carried_field") == {"kept": True},
              "an unknown field did not survive a save and reload (CM03)")
        st.save({**dict(again), "statement": "two"})
        cur = json.loads((d / "widgets" / "w" / "card.json").read_text(encoding="utf-8"))
        _need(cur["metadata"]["version"] == "1.1.0", f"a changed card was not versioned 1.1.0: {cur['metadata']}")
        _need(list((d / "_versions" / "widgets" / "w").glob("1.0.0__*.json")),
              "the previous version was not archived (CM14)")
        (d / "widgets" / "bad").mkdir()
        (d / "widgets" / "bad" / "card.json").write_text("{not json", encoding="utf-8")
        st2 = Store([("model", d)])
        st2.cards("widgets")
        _need(any("bad" in e for e in st2.load_errors()), "a malformed card was not reported (CM10)")
        st2.save({"name": "x", "category": "widgets", "statement": "x", "depends_on": ["widgets/missing"]})
        st2.invalidate()
        _need(any("missing" in p for p in closure(st2)), "a dangling depends_on was not found (CM11)")
    finally:
        shutil.rmtree(d, ignore_errors=True)
    return (f"scratch store: unknown field kept, version 1.1.0 archived 1.0.0, malformed and dangling cards "
            f"reported; live store {len(ctx.store.ALL)} cards in {len(ctx.store.views)} registries")


def honest_limits(ctx: Ctx, seed: int) -> str:
    from . import probes
    from . import theorems as T
    ok, why = probes.probe({"kind": "executable", "name": "cardmodel-capability-missing-tool"})
    _need(not ok and "not found" in why, f"a missing tool was not reported as missing: {ok} {why!r} (CM12)")
    rare = _theorem(ctx, "theorem rare(a: Int) requires a == 123456789: a > 0")
    st = T.witness(rare, ctx.ops, seed=seed)["status"]
    _need(st == "vacuous", f"a claim checked on too few inputs came out {st!r}, not vacuous (CM07)")
    return "a missing tool is reported with its reason; a claim with too few satisfying inputs is vacuous"


def witnesses(ctx: Ctx, seed: int) -> str:
    from ..kernel.card import Card
    from . import witness
    card = Card({"name": "ADDX", "category": "op", "statement": "capability check",
                 "generators": [{"int": [-50, 50], "edges": [7]}, {"int": [-50, 50]}],
                 "forms": [{"name": "native", "code": "lambda a, b: a + b", "domain": "any"},
                           {"name": "off_by_one", "code": "lambda a, b: a + b + (1 if a == 7 else 0)",
                            "domain": "any"}]}, registry="op")
    res = witness.verify_forms(ctx, card, seed=seed, samples=16)
    bad = res["forms"]["off_by_one"]
    _need(bad["status"] == "fail" and bad["args"][0] == 7,
          f"a form wrong only at a=7 was not caught there: {bad.get('status')} {bad.get('args')} (CM08)")
    rules = sorted(ctx.store.cards("rewrite_rule"), key=lambda c: c.name)
    _need(rules, "no rewrite rule cards to witness")
    rule = rules[seed % len(rules)]
    a, b = witness.verify_rule(rule, seed=seed), witness.verify_rule(rule, seed=seed)
    _need(a == b, f"{rule.qualified}: the same seed gave two different witness runs (CM06)")
    _need(a["status"] != "fail", f"{rule.qualified} failed its witness: {a}")
    return f"a planted off-by-one is caught at its input; {rule.qualified} witnessed twice alike with seed {seed}"


def form_selection(ctx: Ctx, seed: int) -> str:
    from . import optimize, rewrite
    fake = {"name": "X", "forms": [{"name": "fast", "cost": 0.1, "code": "x", "probe": {"kind": "never"}},
                                   {"name": "slow", "cost": 9.0, "code": "lambda: 1"}]}
    pick = rewrite.cheapest(ctx.store, fake)
    _need(pick is not None and pick.name == "slow", "an unavailable form was chosen over one that runs (CM05)")
    _need(rewrite.cheapest(ctx.store, fake, available_only=False).name == "fast", "cost order is not respected")
    add = ctx.store.get("op/ADD")
    _need(add is not None, "op/ADD is missing")
    rows = optimize.measure_python_forms(ctx, add, seed, n_inputs=8, repeats=2)
    _need(rows and all(r["median_ns"] > 0 for r in rows), "measuring op/ADD's forms produced no timings (CM09)")
    return f"cheapest available form chosen; {len(rows)} forms of op/ADD measured on this host"


def boundaries(ctx: Ctx, seed: int) -> str:
    from . import integrity, selfcheck
    probs = selfcheck.static_check()
    _need(not probs, f"code names a source folder the runtime must not need: {probs[:3]} (CM13)")
    hits = integrity.publishing_calls()
    _need(not hits, f"publishing calls in the code: {hits[:3]} (CM19)")
    return "no source-folder references and no publishing calls in the program"


def learning(ctx: Ctx, seed: int) -> str:
    from ..kernel.store import open_store
    from .learn import learn
    d = _tmp()
    try:
        (d / ".cardmodel" / "cards").mkdir(parents=True)
        (d / ".cardmodel" / "config.json").write_text('{"name": "capability"}', encoding="utf-8")
        (d / "app").mkdir()
        (d / "app" / "core.py").write_text("def shout(cfg):\n    return cfg.zq_lookup('x') + cfg.zq_lookup('y')\n\n"
                                           "def twice(n: int) -> int:\n    return n + n\n", encoding="utf-8")
        (d / "app" / "util.py").write_text("def pick(cfg):\n    return cfg.zq_lookup('z')\n\n"
                                           "def once(v):\n    return zq_frobnicate(v)\n", encoding="utf-8")
        (d / "web").mkdir()
        (d / "web" / "app.js").write_text("function f(a) { return Math.max(a, 1); }\n", encoding="utf-8")
        pctx = Ctx(open_store(project=d))
        rep = learn(pctx, d, promote=True, seed=seed, max_functions=2, langs=["python"])
        pctx.store.invalidate()
        got = pctx.store.get("call/CALL_METHOD_ZQ_LOOKUP")
        _need(got is not None and got.layer == "project",
              f"a call used 3 times in 2 files was not promoted: {rep['promoted']} (CM04)")
        _need((got.metadata or {}).get("evidence_count", 0) >= 3, "the promoted card does not cite its evidence (CM15)")
        _need(pctx.store.get("call/CALL_ZQ_FROBNICATE") is None, "a call seen once was promoted without evidence (CM04)")
        obs = pctx.store.get(f"observation/{rep['observation']}")
        langs = sorted((obs["totals"].get("by_language") or {}) if obs else {})
        _need(len(langs) >= 2, f"the observation did not read both languages of the tree: {langs}")
    finally:
        shutil.rmtree(d, ignore_errors=True)
    return f"observed {', '.join(langs)}; promoted only what had evidence ({len(rep['promoted'])} cards)"


def translation(ctx: Ctx, seed: int) -> str:
    from ..machine import native as N
    from . import translate
    src = "def f(a: int, b: int) -> int:\n    return a * b + 3 - (a % 5)\n"
    lifted = translate.lift_file_source(ctx, src)
    _need(lifted and lifted[0].ok, "a two-line integer function did not lift to the IR")
    card = translate.function_card(ctx, "f", lifted, "capability check", seed, samples=12)
    langs = ["python"]                       # the host language is the reference
    try:
        langs.append(N.resolve_engine(ctx, "native"))
    except Exception as exc:  # noqa: BLE001 -- no native language here: the check stays honest about it
        raise Unavailable(f"no compiled language available: {exc}") from exc
    r = translate.verify_function(ctx, card, langs=sorted(set(langs)), seed=seed, samples=12)
    _need(r["lift_mismatches"] == 0, f"the lift disagrees with Python on {r['lift_mismatches']} inputs")
    st = {lang: v["status"] for lang, v in r["languages"].items()}
    _need(all(s == "pass" for s in st.values()), f"emitted forms disagree: {st} (CM16, CM17)")
    return f"lifted, emitted and run in {', '.join(sorted(st))}: all agree with the original"


def rewriting(ctx: Ctx, seed: int) -> str:
    from . import search
    from .exprs import parse
    rules = search.load_rules(ctx.store)
    best = search.optimize(parse("max(x, min(x, y)) + abs(abs(z)) * 1"), rules, search.op_costs(ctx.store),
                           max_depth=4)
    _need(best["best_tree"] == parse("x + abs(z)"),
          f"the rule cards no longer simplify max(x, min(x, y)) + abs(abs(z)) * 1: got {best.get('best')} (CM25)")
    proof = search.prove(parse("(a + 0) * 1"), parse("a"), rules)
    _need(proof is not None, "no rule chain proves (a + 0) * 1 == a")
    return f"{len(rules)} rules: absorption, idempotence and identities simplify and prove"


def law_discovery(ctx: Ctx, seed: int) -> str:
    from . import laws as LW
    from . import theorems as T
    ops = {k: ctx.ops[k] for k in ("MIN", "MAX", "SUB") if k in ctx.ops}
    _need(len(ops) == 3, "op cards MIN, MAX and SUB are needed for the example")
    cands = {c["name"]: c for c in LW.candidates(ops)}
    _need("law_idem_MIN" in cands and "law_comm_SUB" in cands, f"law templates lost: {sorted(cands)[:8]}")
    idem = T.settle(cands["law_idem_MIN"], T.witness(cands["law_idem_MIN"], ctx.ops, seed=seed, samples=60), None, None)
    _need(idem["status"] == "witnessed", f"min(a, a) == a came out {idem['status']}")
    rule = LW.rule_card(idem)
    _need(rule and (rule["lhs"], rule["rhs"]) == ("min(a, a)", "a"), f"the simplifying law became {rule}")
    comm = T.witness(cands["law_comm_SUB"], ctx.ops, seed=seed, samples=60)
    _need(comm["status"] == "refuted", f"a - b == b - a came out {comm['status']}")
    return f"{len(cands)} candidate laws over MIN, MAX, SUB; idempotence witnessed and promoted, a false one refuted"


def theorems(ctx: Ctx, seed: int) -> str:
    from . import theorems as T
    false = _theorem(ctx, "theorem bad(a: Int, b: Int): a % (b * b + 1) == a % (b + 1)")
    w = T.witness(false, ctx.ops, seed=seed)
    _need(w["status"] == "refuted", f"a false statement came out {w['status']} (CM23)")
    settled = T.settle(false, w, {"status": "proved", "tactic": "omega", "lean": "x"}, None)
    _need(settled["status"] == "refuted", "a claimed proof overrode a counterexample (CM23)")
    good = _theorem(ctx, "theorem ok(a: Int, b: Int): max(a, b) >= a")
    st = T.witness(good, ctx.ops, seed=seed)["status"]
    _need(st == "witnessed", f"a true statement came out {st}")
    return f"refuted at {w['counterexample']}; a proof never overrides it; a true statement is witnessed"


def lean(ctx: Ctx, seed: int) -> str:
    from ..emit import lean as LE
    exe = LE.lean_exe()
    if not exe:
        raise Unavailable("no Lean toolchain on this host (elan / lean not found)")
    res = LE.check_batch(exe, [("cm_cap_true", "theorem cm_cap_true : 2 + 2 = 4 := by decide"),
                               ("cm_cap_false", "theorem cm_cap_false : 2 + 2 = 5 := by decide")], timeout_s=300)
    _need(res.get("cm_cap_true") == "ok", f"Lean did not accept 2 + 2 = 4: {res.get('cm_cap_true')}")
    _need(str(res.get("cm_cap_false", "")).startswith("error"), f"Lean accepted 2 + 2 = 5: {res.get('cm_cap_false')}")
    return "the Lean kernel accepts a true statement and rejects a false one (fail-closed batch)"


FAMILY = """module capability_family
parent(ann, bo). parent(bo, cy). parent(cy, di).
ancestor(X, Y) <- parent(X, Y).
ancestor(X, Z) <- parent(X, Y), ancestor(Y, Z).
root(X) <- parent(X, _), not parent(_, X).
size(X, N) <- root(X), N = count { ancestor(X, _) }.
never: ancestor(X, X).
"""


def logic(ctx: Ctx, seed: int) -> str:
    from ..lang.compile import compile_source
    from . import logic as L
    mod = compile_source(FAMILY, ctx.ops, ctx.store, name="capability_family")
    model = L.evaluate(mod.program, ctx.ops)
    _need(("ann", "di") in model.db.rel.get("ancestor", ()), "a two-step derivation is missing (CM24)")
    _need(("ann", 3) in model.db.rel.get("size", ()), "negation plus an aggregate gave the wrong answer")
    _need(not model.violations, f"constraints fired on a consistent theory: {model.violations[:2]}")
    proof = model.proof("ancestor", ["ann", "di"])
    _need(proof and proof.get("premises"), "a derived fact has no proof")
    cyc = compile_source(FAMILY + "parent(di, ann).\n", ctx.ops, ctx.store, name="capability_cycle")
    _need(L.evaluate(cyc.program, ctx.ops).violations, "a constraint did not fire on a planted cycle")
    return "recursion, negation and an aggregate derive with proofs; a planted cycle breaks the constraint"


PROGRAM = """module capability_program
fn tri(n: Int) -> Int requires 0 <= n, n <= 1000 {
  var t = 0
  for i in 0 .. n + 1 {
    t += i
  }
  return t
}
small(N) <- num(N), N < 10.
num(3). num(30).
theorem tri_closed(n: Nat) requires n <= 300: tri(n) * 2 == n * (n + 1)
test tri(10) == 55
test small(3) and not small(30)
"""


def card_language(ctx: Ctx, seed: int) -> str:
    from ..lang.compile import compile_source
    from ..lang.run import run as run_module
    mod = compile_source(PROGRAM, ctx.ops, ctx.store, name="capability_program")
    rep = run_module(ctx, mod, seed=seed, samples=60)
    _need(rep["status"] == "pass", f"a function, rule, theorem and tests in one file failed: {rep['counts']} (CM26)")
    return f"one file: a function, a rule, a theorem ({rep['counts']['theorems']}) and {rep['counts']['tests']} tests pass"


def self_theory(ctx: Ctx, seed: int) -> str:
    from . import selflogic
    r = selflogic.evaluate_self(ctx)
    _need(r["status"] == "pass", f"the store breaks its own laws: {r['violations'][:3]} (CM27)")
    return f"{r['rules']} rules over {(r.get('stats') or {}).get('given')} facts about the store: no violations"


def function_algebra(ctx: Ctx, seed: int) -> str:
    from . import funcalg as F

    def loop(n):
        s = 0
        for k in range(n + 1):
            s += k * k
        return s

    closed = F.fit(lambda n: n * (n + 1) * (2 * n + 1) // 6)
    looped = F.fit(loop)
    _need(closed is not None and looped is not None, "no canonical form for the sum of squares")
    _need(closed.godel() == looped.godel(), "two implementations of one behaviour got different Gödel numbers (CM31)")
    _need(F.godel_decode(looped.godel()) == looped.code(), "the Gödel number does not decode to the form")
    r = F.gcd_functions(F.fit(lambda n: n * (n + 1) // 2), looped)
    _need(r["values"]["common_factor"] == "n^2 + n", f"the GCD of functions changed: {r['values']}")
    primes = [p for p in range(2, 400) if all(p % q for q in range(2, int(p ** 0.5) + 1))]
    _need(F.fit(lambda n: primes[n]) is None, "a sequence with no recurrence got a form")
    return f"one Gödel number for two implementations ({looped.godel()}); GCD of functions n^2 + n"


def redefinitions(ctx: Ctx, seed: int) -> str:
    from . import redefs
    cards = sorted(ctx.store.cards("redefinition"), key=lambda c: c.name)
    _need(cards, "no redefinition cards")
    pick = random.Random(seed).sample(cards, min(4, len(cards)))
    verdicts = {c.name: redefs.verify(c, seed=seed, samples=8)["verdict"] for c in pick}
    _need("refuted" not in verdicts.values(), f"a redefinition is refuted: {verdicts} (CM08)")
    return f"{len(pick)} of {len(cards)} redefinitions re-verified: {sorted(set(verdicts.values()))}"


IMPROVABLE = '''import os


def tri(n: int) -> int:
    t = 0
    for i in range(n):
        t += i
    return t


def save(path, n):
    with open(path, "w") as f:
        f.write(str(tri(n)))
    return os.path.getsize(path)
'''


def improve(ctx: Ctx, seed: int) -> str:
    from . import improve as I
    rep = I.improve_source(ctx, IMPROVABLE, "capability.py", seed=seed, samples=12, native=False)
    _need(rep["effect_shell_identical"], "effectful code was changed (CM21)")
    _need([e["name"] for e in rep["effect_shell"]] == ["save"], f"the effect shell is {rep['effect_shell']}")
    act = rep["functions"].get("tri", {}).get("action", "")
    _need(act and act != "kept", f"the triangular loop was not replaced by a verified form: {rep['functions'].get('tri')}")
    _need((rep.get("end_to_end") or {}).get("status") != "fail", f"the end-to-end recheck failed: {rep['end_to_end']} (CM22)")
    return f"tri replaced by {act} (x{rep['functions']['tri'].get('speedup')}), rechecked end to end; save() byte-identical"


def resources(ctx: Ctx, seed: int) -> str:
    from ..kernel import resources as R
    pol = R.policy()
    _need(pol["max_parallel"] >= 1 and pol["child_mb"] > 0 and pol["self_mb"] > 0, f"no bounds: {pol} (CM30)")
    p = R.run([sys.executable, "-c", "print(6 * 7)"], timeout=60, heavy=False)
    _need(p.returncode == 0 and p.stdout.strip() == "42", f"a governed child did not run: {p.returncode} {p.stderr!r}")
    R.guard("capabilities")
    return (f"{pol['max_parallel']} machine-wide slots, {pol['child_mb']} MB per child, this process capped at "
            f"{pol['self_mb']} MB (peak so far {round(R.peak_mb())} MB)")


def game_design(ctx: Ctx, seed: int) -> str:
    if not ctx.store.cards("move"):
        raise Unavailable("no move cards")
    from ..game import analysis as A
    from ..game.combat import Combat
    r = A.check(Combat(ctx))
    failing = [n for n, law in r["laws"].items() if not law["ok"]]
    _need(not failing and r["equilibrium"]["certificate"], f"design laws failing: {failing} (CM28)")
    return f"{r['passed']}/{r['total']} design laws on the exact equilibrium (certificate checked)"


def world(ctx: Ctx, seed: int) -> str:
    from ..game import world as W
    r = W.run(ctx)
    _need(r["final"], "the world ends empty")
    fact = sorted(r["final"], key=str)[0]
    why = W.explain(r, fact, r["ticks"])
    _need(why, f"no explanation for {fact}")
    ranking = W.impact(ctx)
    _need(ranking and ranking[0]["changed"] > 0, "no action changed the world (CM29)")
    return f"{len(r['final'])} facts after {r['ticks']} ticks; '{ranking[0]['action']}' changes {ranking[0]['changed']}"


def machines(ctx: Ctx, seed: int) -> str:
    from ..machine import bench
    r = bench.conformance(ctx, "lr35902", seed=seed, samples=1)
    bad = {k: v["problems"][:2] for k, v in r["per_card"].items() if v["status"] != "pass"}
    _need(not bad, f"instruction cards disagree between engines: {dict(list(bad.items())[:3])} (CM32)")
    return f"{len(r['per_card'])} LR35902 instruction cards agree in {', '.join(r['engines'])}"


def _graphics_rom(ctx: Ctx) -> bytes:
    from ..machine import asm
    tile = bytes([0xAA, 0x55] * 8)
    prog = [("LD SP,nn", 0xFFFE), ("LD A,n", 0), ("LDH (n),A", 0x40),
            ("LD HL,nn", 0x8010), ("LD DE,nn", "tile"), ("LD B,n", 16),
            ("label", "copy"), ("LD A,(DE)",), ("LD (HL+),A",), ("INC DE",), ("DEC B",), ("JR NZ,e", "copy"),
            ("LD HL,nn", 0x9800), ("LD BC,nn", 0x0400),
            ("label", "fill"), ("LD A,n", 1), ("LD (HL+),A",), ("DEC BC",), ("LD A,B",), ("OR C",),
            ("JR NZ,e", "fill"),
            ("LD A,n", 0xE4), ("LDH (n),A", 0x47), ("LD A,n", 0x01), ("LDH (n),A", 0xFF),
            ("LD A,n", 0x93), ("LDH (n),A", 0x40), ("EI",),
            ("label", "idle"), ("HALT",), ("JR e", "idle"),
            ("label", "tile"), ("db", tile)]
    vblank = asm.assemble(ctx.store, [("RETI",)], org=0x40)
    return asm.rom(ctx.store, prog, title="CAPCHECK", extra={0x40: vblank})


def emulation(ctx: Ctx, seed: int) -> str:
    from ..machine import gb, shell
    rom = _graphics_rom(ctx)
    d = _tmp()
    try:
        (d / "cap.gb").write_bytes(rom)
        s = shell.Session(ctx, d / "cap.gb", engine="lifted", sample_rate=0, save_dir=d, saves=False)
        r = shell.run_headless(s, 8)
        s.close()
        ref = gb.GameBoy(ctx, rom, "native", sample_rate=0, fresh=True)
        for _ in range(8):
            ref.run_frame()
        _need(r["frame"] == ref.frame(), "the lifted run's screen differs from the interpreter's (CM33)")
        _need(len(set(r["frame"])) > 1, "the screen is blank: the ROM's tiles were not drawn")
    finally:
        shutil.rmtree(d, ignore_errors=True)
    return "a ROM assembled from the instruction cards runs lifted through the shell; its frames equal the interpreter's"


def arcade(ctx: Ctx, seed: int) -> str:
    if ctx.store.get("game/vector_duel") is None:
        raise Unavailable("no game card game/vector_duel")
    from ..arcade import game as G
    from ..arcade import gen, server
    card = G.game_card(ctx.store, "vector_duel")
    tables, rep = gen.generate(ctx, card)
    _need(tables and rep, "no tables generated from the game's cards (CM35)")
    g = G.Game(ctx, "vector_duel", "native")
    for _ in range(30):
        g.frame(0, 0)
    entry = server.game_entry(ctx, card)
    _need(entry["id"] == "vector_duel" and entry["title"], f"the store entry is {entry}")
    player = ""
    if ctx.store.get("system/gameboy") is not None:
        from ..arcade import system as S
        sysc = S.system_card(ctx.store, "gameboy")
        _need("array cart_kind: Int[256]" in S.tables(ctx, sysc), "no cartridge tables from the cartridge card (CM40)")
        pe = server.game_entry(ctx, sysc)
        _need(pe["id"] == "gameboy_player" and pe["kind"] == "system", f"the player's store entry is {pe} (CM40)")
        player = f"; {pe['title']} v{pe['version']} with the cartridge tables from its cards"
    return (f"tables from the cards, 30 native frames of {entry['title']}, store entry v{entry['version']}"
            f" ({'build due' if entry['build_due'] else 'build current'}){player}")


def live_hub(ctx: Ctx, seed: int) -> str:
    import hashlib
    import subprocess
    from unittest import mock

    from ..arcade import hub as H
    from ..kernel import paths as P
    from ..kernel.store import Store
    if shutil.which("git") is None:
        raise Unavailable("git is not on this host")
    d = _tmp()

    def sh(cwd, *args):
        subprocess.run(["git", "-c", "user.name=c", "-c", "user.email=c@c", *args], cwd=cwd, check=True,
                       capture_output=True, timeout=60)
    try:
        (d / "proj").mkdir()
        (d / "proj" / "a.py").write_text("a = 1\n", encoding="utf-8")
        sh(d, "init", "-q", "-b", "main")
        sh(d, "add", "-A")
        sh(d, "commit", "-q", "-m", "start")
        (d / "proj" / "a.py").write_text("a = 2\n", encoding="utf-8")         # work in progress, uncommitted
        st = Store([("model", d / "cards")])
        st.save({"name": "p", "category": "project", "title": "P", "kind": "game", "statement": "s", "paths": ["proj"]})
        index = d / ".git" / "index"
        before = hashlib.sha256(index.read_bytes()).hexdigest()
        with mock.patch.object(P, "home", lambda: d):
            hub = H.Hub(Ctx(st))
            hub.refresh(force=True)
            snap = hub.current()
        proj = snap["projects"][0]
        _need(proj["last"] and proj["last"]["title"] == "start", f"the last commit was not read: {proj['last']}")
        _need(proj["phase"] == "active now" and proj["changes"], f"uncommitted work was not seen: {proj['phase']}")
        _need(hashlib.sha256(index.read_bytes()).hexdigest() == before, "reading the repository wrote its index")
        from . import projects as PJ
        detail = {"goal": "g", "standing": "s", "done": [], "in_progress": [], "left": [], "blockers": [],
                  "next_steps": [], "user_actions": [], "owner": {"session": "s"}, "branches": [],
                  "updated": "2001-01-01T00:00:00+00:00"}
        st.save({"name": "p", "category": "project", "title": "P", "kind": "game", "statement": "s",
                 "paths": ["proj"], **detail})
        st.invalidate()
        with mock.patch.object(P, "home", lambda: d):
            stale = PJ.check(Ctx(st))
        _need(stale["projects"]["p"]["stale"], "a card revised before its project's last change was not stale (CM41)")
    finally:
        shutil.rmtree(d, ignore_errors=True)
    return ("a project's phase, last commit and uncommitted work computed from git without writing to it; a card "
            "revised before the project's last change is stale")


def symbolic_instructions(ctx: Ctx, seed: int) -> str:
    from ..machine import symbolic as SY
    some = ["LR35902_80", "LR35902_D8", "LR35902_C5", "LR35902_CB_11", "LR35902_27", "LR35902_E8"]
    r = SY.check(ctx, "lr35902", seed=seed, samples=2, only=some)
    _need(r["counts"].get("pass") == len(some), f"symbolic terms disagree with the semantics: {r['counts']} "
          f"{ {k: v.get('problems') or v.get('reason') for k, v in r['cards'].items() if v['status'] != 'pass'} }")
    res = r["results"]["LR35902_80"]
    wrong = {**res, "state": {**res["state"], "A": ["BIT_AND", ["ADD", res["state"]["A"], ["int", 1]], ["int", 255]]}}
    got = SY.evaluate(wrong, {"A": 1, "B": 2, "F": 0}, bytes(0x10000))
    _need(got["regs"]["A"] == 4, "a planted wrong term was not evaluated as written")
    return (f"{len(some)} instructions (ALU, conditional return, push, a CB rotate, DAA, ADD SP) agree with their "
            f"executable semantics as terms")


def four_sources(ctx: Ctx, seed: int) -> str:
    from . import sources as SO
    r = SO.check(ctx)
    _need(r["definitions"] and r["actions"] and r["methods"], "the four source registries are empty (CM44)")
    _need(not r["problems"], f"an artifact does not trace back: {r['problems'][:3]} (CM44)")
    alg = ctx.store.get("algorithm/triangular")
    built = SO.build(ctx, seed=seed)
    d = next((x for x in built["definitions"] if x["subject"] == alg.qualified), None)
    _need(d is not None and d["actions"] and d["godel"]["content"], "a definition was not derived for an algorithm")
    links = [a["link"]["status"] for a in built["actions"] if a["truth"] == f"definition/{d['name']}"]
    _need("refuted" not in links and {"witnessed", "proved"} & set(links),
          f"its forms are not linked to it by a witness or a proof: {links}")
    return (f"{r['definitions']} definitions, {r['actions']} actions, {r['transformations']} transformations, "
            f"{r['methods']} methods trace back; triangular's forms are {', '.join(sorted(set(links)))} against "
            f"its definition")


def witness_tiers(ctx: Ctx, seed: int) -> str:
    from . import tiers as T
    card = ctx.store.get("algorithm/sum_of_squares")
    forms = {f["name"]: f for f in card.get("forms") or []}
    r = T.prove(ctx, card, forms["loop"], forms["closed_form"])
    _need(r and r["status"] == "proved" and r["tier"] == "proof",
          f"a C-finite claim was not proved by its sized witness: {r} (CM46)")
    # a closed form that agrees with the loop on n = 1..9 and nowhere after is refuted, never proved
    bad = dict(forms["closed_form"], code="def sq_closed(n: int) -> int:\n    if n <= 0:\n        return 0\n"
               "    return n * (n + 1) * (2 * n + 1) // 6 + (n - 1) * (n - 2) * (n - 3) * (n - 4) * (n - 5) * "
               "(n - 6) * (n - 7) * (n - 8) * (n - 9)\n")
    r2 = T.prove(ctx, card, forms["loop"], bad)
    _need(r2 is not None and r2["status"] == "refuted", f"a wrong closed form was not refuted: {r2}")
    c = T.census(ctx)
    _need(c["untiered_count"] == 0, f"claims without a tier: {c['untiered'][:3]} (CM46)")
    return (f"sum_of_squares proved on {r['points']} points ({'; '.join(r['theorems'][-1:])}); a closed form wrong "
            f"from n = 10 refuted at {r2['at']}; {c['proof']} of {c['claims']} claims at tier proof")


def formal_core(ctx: Ctx, seed: int) -> str:
    from . import formal as F
    if F.toolchain() is None:
        raise Unavailable("no Lean toolchain for formal/lean-toolchain")
    r = F.check(ctx)
    _need(r["status"] == "pass", f"the formal core does not hold: {r.get('problems', [])[:3]}")
    return (f"{r['proved']} of {r['theorems']} theorem cards proved by Lean's kernel ({r['lean_names']} theorems, "
            f"standard axioms only, no sorry)")


def distillation(ctx: Ctx, seed: int) -> str:
    from . import egraph as E
    from . import search
    from .exprs import parse
    rules, costs = E.rules_from_cards(ctx.store), search.op_costs(ctx.store)
    _need(rules, "no equalities to saturate with")
    r = E.equal(parse("max(a, b) + min(b, a)"), parse("a + b"), rules)
    _need(r["equal"], "max(a, b) + min(b, a) == a + b is no longer proved by saturation")
    c1 = E.canonical(parse("b * a + c"), rules, costs)
    c2 = E.canonical(parse("c + a * b"), rules, costs)
    _need(c1["hash"] == c2["hash"], "two equal terms got different canonical forms")
    w = E.witness(parse("max(a, b) + min(b, a)"), parse("a + b"), seed)
    _need(w["status"] == "witnessed", f"the witness disagrees: {w}")
    return (f"{len(rules)} equalities saturate; a law-level identity is proved; equal terms share one canonical term "
            f"({c1['hash'][:19]})")


def godel_model(ctx: Ctx, seed: int) -> str:
    from collections import Counter

    from ..kernel.store import Store
    from . import godel as G
    entries = G.ledger(ctx.store)
    _need(entries and not G.problems(entries), f"the prime ledger is empty or malformed: {G.problems(entries)[:3]}")
    d = _tmp()
    try:
        st = Store([("model", d)])
        G.sync(st, ["s/a", "s/b"], "S")
        before = (d / "godel" / "_pack_ledger.jsonl").read_text(encoding="utf-8")
        G.sync(st, ["s/c"], "S")
        _need((d / "godel" / "_pack_ledger.jsonl").read_text(encoding="utf-8").startswith(before),
              "appending to the ledger rewrote a line (CM43)")
    finally:
        shutil.rmtree(d, ignore_errors=True)
    a, _ = G.card_content(ctx, ctx.store.get("algorithm/sum_of_squares"))
    b, _ = G.card_content(ctx, ctx.store.get("algorithm/triangular"))
    common = G.gcd(a, b)
    _need(common and G.divides(common, a) and G.divides(common, b), f"no common factor: {a} {b}")
    idx = G.index_of(ctx.store)
    t = ["ADD", ["MUL", ["var", "n"], ["int", 3]], ["int", -2]]
    n, vs, _ = G.structural(t, ctx.ops, idx)
    _need(G.decode(n, ctx.ops, entries, vs) == t, "a structural number did not decode to its term")
    rec = G.stored(a, "test", entries)
    _need("number" not in rec and rec["vector"] and not G.vector_problems(rec, entries),
          f"a stored Gödel record breaks the storage rules: {G.vector_problems(rec, entries)} (CM45)")
    image, gap = G.carry(Counter({"x": 1, "y": 2}), {"x": Counter({"X": 1})})
    _need(gap == Counter({"y": 2}), "a map's gap is wrong")
    return (f"{len(entries)} atoms with their primes; gcd(sum_of_squares, triangular) = {dict(common)}; structural "
            f"numbers decode exactly; a map leaves its gap")


def anyps5(ctx: Ctx, seed: int) -> str:
    if not ctx.store.cards("anyps5_export"):
        raise Unavailable("no AnyPS5 scan in the store (cardmodel anyps5 scan PATH --save)")
    from ..anyps5 import classify as K
    cls = K.classify(ctx, run_programs=False)
    _need(not cls.model.violations, f"the classification breaks its rules: {cls.model.violations[:2]} (CM36)")
    causes = {c.name: c["class"] for c in ctx.store.cards("anyps5_cause")}
    wrong = [(e, c) for e, _k, c in cls.rel("cause") if cls.exports[e].get("unknown_name") and causes.get(c) != "observation"]
    _need(not wrong, f"unknown names given a non-observation cause: {wrong[:3]} (CM36)")
    return f"{len(cls.exports)} AnyPS5 exports classified; every unknown name is an observation obligation"


def self_run(ctx: Ctx, seed: int) -> str:
    from . import selfrun
    steps = selfrun.steps(ctx)
    _need(steps, "no self_step cards (CM38)")
    missing = [s["name"] for s in steps if s["run"] not in selfrun.STEPS]
    _need(not missing, f"self_step cards name steps the program does not have: {missing}")
    rep = {"steps": {"verify": {"status": "fail", "failing": ["rules"]}, "capabilities": {"status": "pass"}},
           "goals": [{"goal": "G_X", "met": False, "value": 1, "target": 2, "direction": "higher", "axis": "a",
                      "metric": "m"}]}
    plan = selfrun.plan(selfrun.findings(rep))
    _need(plan and plan[0]["severity"] == "critical", f"a failing verify did not rank first: {plan[:2]}")
    return f"{len(steps)} steps; findings rank a failing verify above an unmet goal"


def integration(ctx: Ctx, seed: int) -> str:
    from . import integrity
    r = integrity.check(ctx)
    _need(not r["problems"], f"the program is not one piece: {r['problems'][:4]} (CM39)")
    return (f"{r['laws']} laws and {r['goals']} goals with unique numbers, {r['commands']} commands and "
            f"{r['sections']} verify sections documented, generated docs in sync")


CHECKS = {f.__name__: f for f in (card_store, honest_limits, witnesses, form_selection, boundaries, learning,
                                  translation, rewriting, law_discovery, theorems, lean, logic, card_language,
                                  self_theory, function_algebra, redefinitions, improve, resources, game_design,
                                  world, machines, symbolic_instructions, emulation, arcade, live_hub, godel_model,
                                  distillation, four_sources, witness_tiers, formal_core, anyps5, self_run,
                                  integration)}


def run(ctx: Ctx, seed: int = 0, names: list[str] | None = None) -> dict:
    """Run the smoke check of every capability card (or ``names``); fail if a core capability is lost."""
    cards = sorted(ctx.store.cards("capability"), key=lambda c: (c.get("order", 999), c.name))
    if names:
        cards = [c for c in cards if c.name in names]
    out = {}
    for card in cards:
        fn = CHECKS.get(card.get("check"))
        t0 = time.perf_counter()
        if fn is None:
            res = {"status": "fail", "reason": f"check {card.get('check')!r} does not exist in the program"}
        else:
            try:
                res = {"status": "pass", "evidence": fn(ctx, seed)}
            except Unavailable as exc:
                res = {"status": "unavailable", "reason": str(exc)}
            except Lost as exc:
                res = {"status": "fail", "reason": str(exc)}
            except Exception as exc:  # noqa: BLE001 -- a crash is a lost capability, reported with where
                tb = traceback.extract_tb(exc.__traceback__)[-1]
                res = {"status": "fail", "reason": f"{type(exc).__name__}: {exc} ({Path(tb.filename).name}:{tb.lineno})"}
        res.update(seconds=round(time.perf_counter() - t0, 2), core=bool(card.get("core")),
                   laws=list(card.get("laws") or []))
        out[card.name] = res
    failing = sorted(n for n, r in out.items() if r["status"] == "fail" and r["core"])
    st = [r["status"] for r in out.values()]
    return {"status": "fail" if failing else ("pass" if "pass" in st else "vacuous"), "seed": seed,
            "failing": failing, "unavailable": sorted(n for n, r in out.items() if r["status"] == "unavailable"),
            "counts": {s: st.count(s) for s in sorted(set(st))}, "capabilities": out}


__all__ = ["CHECKS", "Lost", "Unavailable", "run"]
