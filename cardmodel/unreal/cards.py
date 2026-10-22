"""cards — the engine's math as cards: what was observed, what it means, how it is implemented, what is equal.

  unreal_math      one card per function of the engine's math (its subject): name, kind, type, file and line in
                   the engine, use, status (lifted / outside the math universe / gap with its cause), its inputs and
                   outputs, its atom in the engine's Gödel set and that atom's prime, and the witness verdict
  definition       truth, for every lifted function the witness did not refute (law CM44's format): the lifted
                   terms, the canonical outputs over ℝ, the semantic hash, the Gödel content, number and structural
                   tokens, the proof obligations (the witness against the engine's compiled code; the canonical form,
                   decided), origin and methods
  action           the engine's own code for it (written by its programmers, compiled as the engine ships), linked to
                   the definition by the witness
  transformation   identities: definitions with one canonical form (one function written twice, or its float and
                   double versions)
  unreal_use       what the math is for: the members of each use, and the logic they all share (the GCD of their
                   content) and all need (the LCM)
  unreal_cause     why a function is not lifted, with what would close it
  godel            the engine's Gödel set: every function of the universe is an atom (appended, never renumbered)

Large terms (past TERM_LIMIT nodes) are kept in the cache with their hash and size on the card, so the repository
holds the mathematics of every function without holding megabytes of trees.
"""
from __future__ import annotations

import json
import re
from collections import Counter

from ..engines import godel as G
from ..engines import realnorm as RN
from . import distill as D

PACK = "unreal"
# docs/INTEGRATION.md rule 8 (the user, 2026-10-22): terms lifted from Unreal Engine's source stay on this machine.
# Every card that carries them or what is computed from them goes to the untracked local layer; the ledger keeps the
# engine's atoms (names) and the set card their arities (signatures), which may be tracked.
LOCAL = "local"
LOCAL_REGISTRIES = ("unreal_math", "definition", "action", "transformation", "unreal_use", "unreal_cause")
TERM_LIMIT = 600
TOKEN_LIMIT = 300
CAUSES = {
    "loop": "a closed form for the loop (the function algebra's recurrences) or a bound on its trip count",
    "array index": "an index the inputs choose, written through a reference (a store into a selected slot), or into "
                   "a pointer parameter's array, whose length is the caller's",
    "undefined behaviour": "nothing: the C++ is undefined on every path (a constant shift past the operand's width)",
    "unknown type": "a layout for the type (its record in a unit the scan reads), or the type is outside the math",
    "unknown constant": "the constant's definition in a unit the scan reads",
    "bit-level reinterpretation": "bits atoms for this pair of widths",
    "union type punning": "reading the overlaid member through the bits atoms",
    "bitfield": "bitfield layouts (offsets and widths as BV slices)",
    "random state": "the random stream as an effect boundary with its state as an input (FRandomStream does this)",
    "static state": "the static as state threaded through calls",
    "term too large": "let-bound subterms (the term shared as a DAG) instead of one tree",
    "no body": "the definition (a unit or library the scan reads)",
    "calls a gap": "closing the gap of the function it calls",
    "pointer": "a pointer model beyond references (arithmetic, null)",
    "reference type": "a value shape for the referenced type",
    "uninitialized read": "nothing: the C++ reads a value it never set on some path (undefined)",
    "control flow": "merging the paths it takes (a reference returned on some paths only)",
    "switch": "fallthrough between cases",
    "constructor": "this initializer form",
    "unsupported expression": "this expression kind in the lifter",
    "unsupported lvalue": "this lvalue kind in the lifter",
    "recursion": "a closed form for the recursion",
    "budget": "a larger budget, or a closed form",
    "sizeof": "the layout of the type",
    "memory": "a memory model for the copy",
    "cast": "this conversion",
    "container": "lists and arrays of values in the IR (TArray of keys, as FInterpCurve holds them)",
    "atoms outside the ledger": "an op card for the atom (cardmodel/unreal/atoms.py, then tools/seed_unreal.py)",
    "not mathematics": "nothing: the function is about text, time, logging or tests",
    "default argument": "the default's expression in the AST",
    "call": "this call form",
    "void value": "this call form",
    "dangling reference": "nothing: the C++ reads through a reference to an object that is gone",
    "exceptions": "exceptions are outside the semantic core",
    "inline assembly": "the instructions' semantics (machine instruction cards)",
    "lambda": "lambda expressions in the lifter",
    "string": "strings are outside the math",
    "this": "this call form",
    "shape mismatch": "this conversion between shapes",
    "conditional lvalue": "a write through a choice of objects",
    "unknown enum": "the enum's values in a unit the scan reads",
    "unknown field": "the field's layout",
    "unknown variable": "the variable's declaration",
    "unsupported declaration": "this declaration kind",
    "unsupported operator": "this operator",
    "function pointer": "calls through function pointers",
    "reference without initializer": "nothing: not valid C++",
    "no return": "nothing: the function never returns a value on these paths",
}


slug = D.card_name


def _terms(outputs: list[dict], key: str) -> dict:
    total = sum(D._size(o[key]) for o in outputs)
    if total <= TERM_LIMIT:
        return {o["name"]: o[key] for o in outputs}
    return {"in_cache": "state/unreal/<version>/scan.jsonl", "nodes": total,
            "hash": RN.digest([[o["name"], o[key]] for o in outputs])}


def _signature(f: dict) -> str:
    ins = " ".join(sorted({k for _n, k in f.get("inputs") or []}))
    return f"{len(f.get('inputs') or [])} inputs ({ins or '-'}) -> {len(f.get('outputs') or [])} outputs"


def _verdict(v: dict | None) -> dict:
    if not v:
        return {"status": "pending", "reason": "not witnessed yet (cardmodel unreal witness)"}
    out = {k: v[k] for k in ("status", "seed", "checks", "skipped", "max_ulp", "reason") if k in v}
    if v.get("status") == "refuted":
        out.update({k: v[k] for k in ("case", "output", "engine", "term", "ulps") if k in v})
    return out


def _over_reals(outs: list[dict]) -> dict:
    """The claim that the canonical outputs are the lifted terms over ℝ: a proof where every output is a
    polynomial (a sized grid in exact rationals), otherwise it rests on the normalizer's rules (a sample tier)."""
    got = [o.get("over_reals") for o in outs]
    if outs and all(g and g.get("status") == "proved" for g in got):
        return {"claim": "the canonical outputs equal the lifted terms over the reals", "tier": "proof",
                "status": "proved", "by": "method/normal_form",
                "evidence": {"points": sum(g["points"] for g in got), "how": got[0]["by"]}}
    bad = [g for g in got if g and g.get("status") == "refuted"]
    if bad:
        return {"claim": "the canonical outputs equal the lifted terms over the reals", "tier": "proof",
                "status": "refuted", "by": "method/normal_form", "evidence": bad[0]}
    return {"claim": "the canonical outputs equal the lifted terms over the reals", "tier": "sample",
            "status": "derived", "by": "method/normal_form",
            "note": "outside the polynomial class: rests on the normal form's rules (ring laws, parity, comparisons)"}


def build(scan: dict, dist: dict, verdicts: dict, index: dict, entries: list | None = None) -> dict:
    eng = scan["engine"]
    rows = dist["rows"]
    fns = [f for f in scan["functions"]]
    names = {f["key"]: slug(f) for f in fns}
    subjects, defs, acts, trans = [], [], [], []
    def_of: dict[str, str] = {}
    for f in fns:
        nm = names[f["key"]]
        r = rows.get(f["key"]) or {}
        v = verdicts.get(f["key"])
        card = {"name": nm, "qual": f["qual"], "kind": f["kind"], "record": f.get("record"), "type": f["type"],
                "file": f["file"], "line": f["line"], "engine": eng["version"], "status": f["status"],
                "use": r.get("use") or D.use_of(f)}
        if f["status"] != "outside":
            card["atom"] = D.atom_name(f)
            card["arity"] = D.call_arity(f)
        if f["status"] == "lifted":
            card.update(inputs=[n for n, _k in f["inputs"]], outputs=[o["name"] for o in f["outputs"]],
                        signature=_signature(f), effects=f.get("effects") or [], witness=_verdict(v))
            missing = sorted(a for a in (r.get("content") or {}) if a not in index)
            if (v or {}).get("status") == "refuted":
                card["status"] = "refuted"
                card["cause"] = "the lifted term disagrees with the engine's compiled code"
            elif missing:
                card["status"] = "gap"
                card.update(cause="atoms outside the ledger", detail=", ".join(missing))
            elif f["outputs"] and r.get("content") is not None:
                card["definition"] = f"definition/ue__{nm}"
                def_of[f["key"]] = f"ue__{nm}"
        else:
            card.update(cause=f.get("cause"), detail=f.get("detail"))
        subjects.append(card)
    for f in fns:
        if f["key"] not in def_of:
            continue
        nm, dn = names[f["key"]], def_of[f["key"]]
        r, v = rows[f["key"]], verdicts.get(f["key"])
        godel = G.stored(Counter(r["content"]), "the canonical outputs", entries or [])
        godel["digits"] = r.get("digits")                  # the size of the content integer, never the integer
        godel["positional"] = {o["name"]: {"tokens": o["tokens"], "variables": o["variables"]}
                               for o in r["outputs"] if o["tokens"] is not None and len(o["tokens"]) <= TOKEN_LIMIT}
        ver = _verdict(v)
        wstatus = {"witnessed": "witnessed", "witnessed_ulp": "witnessed"}.get(ver["status"], "pending")
        obligations = [
            {"claim": f"the term equals the engine's compiled code (Unreal Engine {eng['version']}, as shipped)",
             "tier": "sample", "status": wstatus, "evidence": ver},
            _over_reals(r["outputs"])]
        outs = r["outputs"]
        defs.append({
            "name": dn, "category": "definition", "subject": f"unreal_math/{nm}",
            "math": {"text": f"{f['qual']}: {_signature(f)}", "type": _signature(f),
                     "term": _terms([o for o in f["outputs"] if o["term"] is not None], "term"),
                     "inputs": f["inputs"],
                     **({"returns": "the object itself (*this), whose fields are the other outputs"}
                        if any(o["kind"] == "&this" for o in f["outputs"]) else {})},
            "explanation": (f"{f['qual']} from Unreal Engine {eng['version']} ({f['file']}:{f['line']}), lifted from "
                            "the engine's scalar path through clang's typed AST: each output a term over the inputs. "
                            "The canonical outputs read it over the reals, with the inputs named by position."),
            "canonical": {"status": "canonical", "by": "method/normal_form", "hash": r["hash"],
                          "outputs": _terms([{"name": o["name"], "canonical": o["canonical"]} for o in outs],
                                            "canonical")},
            "godel": godel, "identity": {"hash": r["hash"], "of": "the canonical outputs, inputs by position"},
            "proof_obligations": obligations, "actions": [f"action/{dn}__engine"],
            "transformations": [], "use": r["use"],
            "origin": {"kind": "lifted", "from": f"unreal_math/{nm}", "engine": eng["version"],
                       "file": f["file"], "line": f["line"]},
            "methods": ["method/lift_cpp", "method/normal_form", "method/witness"]})
        acts.append({"name": f"{dn}__engine", "category": "action", "truth": f"definition/{dn}", "lang": "cpp",
                     "code": f"unreal_math/{nm}#engine", "method": "method/human_written",
                     "link": {"kind": "witness", "status": wstatus, "tier": "sample",
                              **{k: ver[k] for k in ("seed", "checks", "max_ulp", "reason") if k in ver},
                              "against": ("the engine's scalar build: its headers and the .cpp files the term "
                                          "reaches, compiled into the harness" if ver.get("build") == "truth" else
                                          "the engine's headers and Core library as shipped")}})
    by_def = {d["name"]: d for d in defs}
    for cls in dist["identities"]:
        members = [def_of[k] for k in cls["members"] if k in def_of]
        for i in range(len(members) - 1):
            tn = f"ue_identity__{cls['hash'][7:19]}__{i}"
            # equal canonical forms: as strong as the weaker of the two claims that each form is its term's
            tiers = [by_def[m]["proof_obligations"][1]["tier"] for m in (members[i], members[i + 1])]
            tier = "proof" if all(t == "proof" for t in tiers) else "sample"
            trans.append({"name": tn, "category": "transformation", "from": f"definition/{members[i]}",
                          "to": f"definition/{members[i + 1]}", "kind": ["identity"],
                          "statement": "one canonical form over the reals",
                          "evidence": {"kind": "normal_form", "by": "method/normal_form", "hash": cls["hash"],
                                       "tier": tier}})
            by_def[members[i]]["transformations"].append(f"transformation/{tn}")
            by_def[members[i + 1]]["transformations"].append(f"transformation/{tn}")
    uses = []
    for u, info in sorted(dist["uses"].items()):
        uses.append({"name": u, "category": "unreal_use", "statement": f"the engine's math for {u.replace('.', ' ')}",
                     "members": len(info["members"]), "lifted": info["lifted"],
                     "gcd": info["gcd"], "lcm": info["lcm"], "common": info.get("common") or {},
                     "atoms": dict(list(info["atoms"].items())[:12]),
                     "examples": sorted({names[k] for k in info["members"]})[:12]})
    causes = Counter(f.get("cause") for f in fns if f["status"] == "gap")
    cause_cards = [{"name": re.sub(r"[^a-z0-9]+", "_", c.lower()).strip("_"), "category": "unreal_cause",
                    "statement": c, "functions": n, "closes_by": CAUSES.get(c, "work on the lifter for this case")}
                   for c, n in sorted(causes.items(), key=lambda kv: (-kv[1], kv[0] or "")) if c]
    carry = dist.get("carry") or {}
    summary = {"to": ["B0", "analysis", "bits"], "image": len(carry.get("image") or {}),
               "gap": len(carry.get("gap") or {}), "preserves_gcd": carry.get("preserves_gcd"),
               "statement": "each lifted function's atom goes to its definition's content; a gap has no image"}
    return {"unreal_math": subjects, "definition": defs, "action": acts, "transformation": trans,
            "unreal_use": uses, "unreal_cause": cause_cards, "carry": summary}


def atoms_in_order(scan: dict) -> list[str]:
    fns = [f for f in scan["functions"] if f["status"] != "outside"]
    fns.sort(key=lambda f: (f["file"], f["line"] or 0, f["qual"], f["key"]))
    return [D.atom_name(f) for f in fns]


def arities(scan: dict) -> dict[str, int]:
    """Each engine atom's arity: its function's arguments (a signature, which may be tracked)."""
    return {D.atom_name(f): D.call_arity(f) for f in scan["functions"] if f["status"] != "outside"}


def write(ctx, built: dict, scan: dict, layer: str = LOCAL) -> dict:
    """Append the engine's atoms to the tracked ledger (never renumbering) with their arities on the set card,
    give each subject card its prime, and save the packs (each regenerated whole) in ``layer``: the untracked
    local layer, since they carry terms lifted from the engine's source."""
    st = ctx.store
    new = G.sync(st, atoms_in_order(scan), "unreal", layer="model")
    idx = G.index_of(st)
    for card in built["unreal_math"]:
        a = card.get("atom")
        if a and a in idx:
            card["prime"] = idx[a]["prime"]
    for reg in LOCAL_REGISTRIES:
        view = st.registry(reg)                 # a View with no cards is falsy: test for None
        meta: dict = {}
        for r in view.regs if view is not None else []:
            if r.layer != layer:                # the registry as the tracked layers define it
                meta.update(r.meta)
        local = st.layer_root(layer) / reg / "_category.json"
        if meta and local.is_file() and json.loads(local.read_text(encoding="utf-8")) != meta:
            local.unlink()                      # the local copy says less than the tracked registry: written again
            st.invalidate()
        st.ensure_registry(reg, layer, description=meta.pop("description", ""),
                           **{k: v for k, v in meta.items() if k != "name"})
        st.save_pack(reg, PACK, built[reg], layer=layer)
    gs = st.get("godel_set/unreal")
    ar = arities(scan)
    if gs is not None and gs.get("arities") != ar:
        st.save({**{k: v for k, v in dict(gs).items() if k not in ("carry", "engine")}, "arities": ar},
                layer="model", category="godel_set")
    st.invalidate()
    return {"atoms_appended": len(new), **{k: len(v) for k, v in built.items() if isinstance(v, list)}}


__all__ = ["LOCAL", "LOCAL_REGISTRIES", "arities", "build", "slug", "write"]
