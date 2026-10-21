"""learn — the learning loop: observe -> propose -> verify -> promote (Pheros pheros-learn, L100/L102).

1. observe   the source tree (observe.py); the observation card is written
             once per content hash and never edited afterwards (ground truth).
2. propose   three kinds of new cards, each carrying its evidence:
     call      a frequent fallback call (``CALL_GENERIC``) becomes a named
               call card. Method calls are generalised by their tail
               (``x.get(...)`` / ``self.cfg.get(...)`` -> ``.get``).
     function  every liftable Python function becomes a function card
               with forms in every available language (translate.py).
     rewrite   an expression with a cheaper equivalent under the rule cards
               (search.optimize), checked numerically; advisory only, source
               files are never edited (hub L3).
3. verify    function cards run in every language against the observed
             Python; rewrite suggestions are evaluated on seeded inputs.
4. promote   only with evidence (CM04): calls seen >= 3 times in >= 2 files,
             functions whose lift is faithful and that agree in >= 3
             implementations, rewrites that passed their numeric check.
             Promoted cards cite the observation and the run (seed) they came
             from (CM15: confidence + evidence_count). Everything else stays
             in ``proposal/`` with the reason it is not ready.

Honest limits (L1): call cards learned this way are names with evidence of
use, not semantics; function domains are inferred heuristically; a
rejected proposal is kept, not deleted, so it can be revisited.
"""
from __future__ import annotations

import ast
import hashlib
import random
import re
from collections import Counter, defaultdict
from pathlib import Path

from . import values as V
from .context import Ctx
from .exprs import ParseError, _conv, evaluate, size, to_text, variables
from .frontend_python import lift_source
from .observe import iter_files, observe
from .search import load_rules, op_costs, optimize
from .translate import function_card, verify_function

MIN_EVIDENCE = 3
MIN_FILES = 2
MIN_AGREEING = 3


def _ident(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_").upper()[:60] or "ANON"


def propose_calls(ctx: Ctx, obs: dict) -> list[dict]:
    out = []
    files_of = obs.get("fallback_call_files") or {}
    existing = {c.name for c in ctx.store.cards("call")}
    for lang, calls in (obs.get("fallback_calls_by_language") or {}).items():
        groups: dict[str, dict] = {}
        for name, count in calls.items():
            if name == "<expression>":
                continue
            key = "." + name.rsplit(".", 1)[-1] if "." in name else name
            g = groups.setdefault(key, {"count": 0, "files": set(), "spellings": Counter()})
            g["count"] += count
            g["files"].update(files_of.get(name, []))
            g["spellings"][name] += count
        for key, g in sorted(groups.items(), key=lambda kv: -kv[1]["count"]):
            card_name = f"CALL_{'METHOD_' if key.startswith('.') else ''}{_ident(key)}"
            if lang != "python":
                card_name += f"__{_ident(lang)}"
            if card_name in existing:
                continue
            ready = g["count"] >= MIN_EVIDENCE and len(g["files"]) >= MIN_FILES
            out.append({
                "kind": "call", "ready": ready,
                "reason": "evidence threshold met" if ready else
                f"needs >= {MIN_EVIDENCE} uses in >= {MIN_FILES} files (have {g['count']} in {len(g['files'])})",
                "candidate": {
                    "name": card_name, "category": "call", "tier": 3, "cost": 1.5,
                    "statement": f"call to {key} ({lang}), learned from observed code",
                    "match": {lang: {"call": [key]}}, "tags": ["learned"],
                    "metadata": {"learned": True, "confidence": "established" if ready else "tentative",
                                 "evidence_count": g["count"], "files": len(g["files"]),
                                 "spellings": dict(g["spellings"].most_common(5))},
                    "provenance": {"learning_loop_refs": [f"observation/{obs['name']}"], "language": lang}}})
            if len(out) >= 200:
                return out
    return out


def propose_functions(ctx: Ctx, obs: dict, base: Path, seed: int, max_functions: int, langs=None,
                      strict: bool = False, known=None) -> list[dict]:
    """``known(card_name)`` true: the card exists already, so it is neither translated again nor proposed."""
    out = []
    by_file = defaultdict(list)
    for f in obs.get("functions") or []:
        if f["liftable"]:
            by_file[f["file"]].append(f["name"])
    done = 0
    for relp, names in sorted(by_file.items()):
        src = (base / relp).read_text(encoding="utf-8")
        lifted = lift_source(src, ctx.ops)
        for name in names:
            if done >= max_functions:
                return out
            card = function_card(ctx, name, lifted, f"{obs['root']}/{relp}", seed=seed)
            if known is not None and known(card["name"]):
                continue
            done += 1
            rep = verify_function(ctx, card, langs=langs, seed=seed)
            agreeing = rep["agreeing_languages"]
            checks = min((r.get("checks", 0) for r in rep["languages"].values() if r["status"] == "pass"),
                         default=0)
            faithful = card["verification"]["lift_fidelity"]["mismatched"] == 0 and rep["lift_mismatches"] == 0
            failing = sorted(k for k, v in rep["languages"].items() if v["status"] in ("fail", "error"))
            ready = (faithful and len(agreeing) >= MIN_AGREEING and checks >= MIN_EVIDENCE
                     and not (strict and failing))
            card["verification"].update({"run": {k: v for k, v in rep.items() if k != "languages"},
                                         "languages": {k: {kk: vv for kk, vv in v.items()
                                                           if kk in ("status", "checks", "out_of_width", "args",
                                                                     "expected", "got", "reason")}
                                                       for k, v in rep["languages"].items()}})
            card["status"] = "healthy" if ready else "suspect"
            card["metadata"] = {"learned": True, "confidence": "established" if ready else "tentative",
                                "evidence_count": checks, "agreeing_languages": agreeing}
            card["provenance"]["learning_loop_refs"] = [f"observation/{obs['name']}"]
            out.append({"kind": "function", "ready": ready, "candidate": card,
                        "reason": "faithful lift; agrees in " + ", ".join(agreeing) if ready else
                        f"faithful={faithful}, agreeing={agreeing}, checks={checks}, failing={failing}",
                        "xleq": {"name": f"xleq_{card['name']}", "category": "xleq", "tier": 3,
                                 "subject": f"function/{card['name']}", "languages": agreeing,
                                 "confidence": "established" if ready and checks >= 3 else "tentative",
                                 "evidence_count": checks, "seed": rep["seed"],
                                 "statement": f"{name}: same outputs in {len(agreeing)} implementations",
                                 "provenance": {"learning_loop_refs": [f"observation/{obs['name']}"],
                                                "tool": "cardmodel learn"}}})
    return out


def propose_rewrites(ctx: Ctx, root: Path, seed: int, limit: int = 60) -> list[dict]:
    rules = load_rules(ctx.store)
    costs = op_costs(ctx.store)
    out, seen = [], set()
    rng = random.Random(seed)
    base = root if root.is_dir() else root.parent
    for p in iter_files(root):
        if p.suffix != ".py":
            continue
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError, OSError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.BinOp):
                continue
            try:
                expr = _conv(node, set())
            except ParseError:
                continue
            if not 3 <= size(expr) <= 9 or any(isinstance(e, list) and e[0] in ("FN", "const", "float")
                                               for e in _nodes(expr)):
                continue
            key = repr(expr)
            if key in seen:
                continue
            seen.add(key)
            res = optimize(expr, rules, costs, max_depth=3, max_nodes=400)
            if res["best_cost"] >= res["input_cost"]:
                continue
            vars_ = sorted(variables(expr))
            checks = 0
            ok = True
            for _ in range(24):
                env = {v: rng.randint(-50, 50) for v in vars_}
                try:
                    a, b = evaluate(expr, env), evaluate(res["best_tree"], env)
                except (ArithmeticError, ValueError):
                    continue
                checks += 1
                if a != b:
                    ok = False
                    break
            out.append({"kind": "rewrite", "ready": ok and checks >= MIN_EVIDENCE,
                        "reason": f"{checks} seeded checks" + ("" if ok else ", MISMATCH"),
                        "candidate": {"name": "sugg_" + hashlib.sha256(
                                          f"{p.relative_to(base)}:{node.lineno}:{key}".encode()).hexdigest()[:12],
                                      "category": "suggestion", "tier": 3,
                                      "statement": f"{res['input']} -> {res['best']}",
                                      "file": str(p.relative_to(base)), "line": node.lineno,
                                      "from": res["input"], "to": res["best"], "steps": res["steps"],
                                      "cost_from": res["input_cost"], "cost_to": res["best_cost"],
                                      "metadata": {"learned": True, "evidence_count": checks,
                                                   "confidence": "established" if ok and checks >= 3 else "tentative",
                                                   "advisory": "the source file is not edited (hub L3)"}}})
            if len(out) >= limit:
                return out
    return out


def _nodes(e):
    if isinstance(e, list):
        yield e
        if e and e[0] not in ("var", "int", "float", "bool", "const"):
            for a in e[(2 if e[0] == "FN" else 1):]:
                yield from _nodes(a)


def learn(ctx: Ctx, root, promote: bool = False, layer: str | None = None, seed: int | None = None,
          max_functions: int = 25, langs: list[str] | None = None, kinds: set[str] | None = None,
          keep_pending: bool = True, skip_existing: bool = False, strict: bool = False) -> dict:
    """``kinds`` limits what is promoted (call, function, rewrite; default all); ``keep_pending=False`` does not
    write the proposals that are not promoted, and ``skip_existing`` leaves cards the store already has as they
    are (the cycle re-derives both every run instead of rewriting them with a new seed); ``strict`` promotes a
    function only when no language it ran in disagreed (verify checks every function card in every language,
    so a card that fails one would make the model fail its own verify)."""
    seed = V.fresh_seed() if seed is None else seed
    root = Path(root).resolve()
    obs = observe(ctx, root)
    store = ctx.store
    layer = layer or store.writable_layer()
    if store.get(f"observation/{obs['name']}") is None:   # ground truth: written once, never edited
        store.save(obs, layer=layer, category="observation")
    base = root if root.is_dir() else root.parent
    known_fn = (lambda n: store.get(f"function/{n}") is not None) if skip_existing else None
    proposals = propose_calls(ctx, obs) + \
        propose_functions(ctx, obs, base, seed, max_functions, langs, strict, known_fn) + \
        propose_rewrites(ctx, root, seed)
    promoted, pending, known = [], [], []
    for p in proposals:
        cand = p["candidate"]
        if skip_existing and store.get(f"{cand['category']}/{cand['name']}") is not None:
            known.append(f"{cand['category']}/{cand['name']}")
            continue
        if promote and p["ready"] and (kinds is None or p["kind"] in kinds):
            store.save(cand, layer=layer, category=cand["category"])
            if p.get("xleq"):
                store.save(p["xleq"], layer=layer, category="xleq")
            promoted.append(f"{cand['category']}/{cand['name']}")
        else:
            pending.append(p)
            if not keep_pending:
                continue
            store.save({"name": f"prop_{cand['category']}_{cand['name']}"[:120], "category": "proposal", "tier": 3,
                        "statement": f"proposed {cand['category']} card {cand['name']}",
                        "proposal_kind": p["kind"], "ready": p["ready"], "reason": p["reason"],
                        "candidate": cand, "xleq": p.get("xleq"), "seed": seed,
                        "provenance": {"learning_loop_refs": [f"observation/{obs['name']}"]}},
                       layer=layer, category="proposal")
    return {"seed": seed, "observation": obs["name"], "totals": obs["totals"],
            "proposals": Counter(p["kind"] for p in proposals),
            "ready": Counter(p["kind"] for p in proposals if p["ready"]),
            "promoted": promoted, "pending": len(pending), "known": len(known), "layer": layer}
