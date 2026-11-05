"""sources — the four sources: truth, transformation, action, method (docs/MATH_CORE.md phase 1, law CM44).

  definition      truth: what a function means. Its term (the reference form lifted into the semantic core), its
                  canonical form when distillation reaches one (an e-graph's cheapest term, or a recurrence's
                  canonical form for one-integer functions), its identity (the hash of its structure), its Gödel
                  content as a sparse vector with its basis version (CM45: never the content integer), its proof
                  obligations (every implementation equals it), its origin and the methods that made it.
  action          code that does what a definition says: an implementation in a language, linked to its truth by a
                  proof or a witness. Algorithm forms and function forms are actions.
  transformation  an equivalence between truths with its evidence: the identities between functions found from
                  behaviour. Rewrite rules, redefinitions and laws already are transformations of terms; their
                  registries count as transformation sources.
  method          a procedure the model runs from one source to another (lift, saturate, fit a recurrence, emit,
                  witness, prove), with what it decides and its limits.

``build`` derives definitions, actions and transformations from the algorithm, function and functional identity
cards, and ``write`` saves them as packs. ``check`` holds the law: every action names a definition and a method and
links to it by a proof, a witness or as its source, none refuted; every transformation names two truths and its
evidence; every definition names its origin and carries atoms of the ledger; every method states what it decides
and its limits.

Honest limits (L1): the definitions are derived from the cards that hold code today, not yet the other way round
(code emitted from definitions is phase 3); a witness is seeded sampling, not a proof; a loop with no closed form
keeps its lifted term with its canonical form pending.
"""
from __future__ import annotations

import random

from . import equivalence as EQ
from . import values as V

REGISTRIES = ("definition", "action", "transformation", "method")
TRANSFORMATION_SOURCES = ("transformation", "rewrite_rule", "redefinition", "functional_identity", "xleq")
PACK = "generated"


def _type(sig: dict) -> str:
    params = sig.get("params") or []
    return " -> ".join([p.get("type", "?") for p in params] + [sig.get("returns", "?")]) if params else \
        sig.get("returns", "?")


def _single_return(fn: dict):
    body = (fn or {}).get("body") or []
    return body[0]["value"] if len(body) == 1 and body[0].get("k") == "return" else None


def _godel(ctx, card, entries, term, canon: dict | None = None, single: bool = False) -> dict:
    """The definition's Gödel record. Content is not invariant under the laws (a(b + c) and ab + ac have different
    factors), so when distillation reached a canonical term and that term is the whole definition (one function),
    content and structure are read from it, and equal definitions share their content (FOUNDATIONS.md D11, A4).
    Otherwise they are read from the lifted code, and ``read_from`` says so."""
    from . import godel as G
    if single and (canon or {}).get("status") == "canonical" and canon.get("term") is not None:
        return G.stored(G.term_content(canon["term"], ctx.ops), "its canonical term (method/saturate)", entries,
                        ctx.ops, canon["term"])
    content, why = G.card_content(ctx, card)
    return G.stored(content, why, entries, ctx.ops, term)


def identity(canon: dict, term, whole) -> dict:
    """A definition's identity: the hash of its structure, the canonical term's when distillation reached one."""
    from .egraph import semantic_hash
    if canon.get("status") == "canonical":
        return {"hash": canon["hash"], "of": "canonical term", "under": "laws"}
    if term is not None:
        return {"hash": semantic_hash(term), "of": "lifted term", "under": "syntax"}
    return {"hash": semantic_hash(whole), "of": "lifted function", "under": "syntax"}


def _var_sorts(fn) -> dict:
    """The sorts of a function's parameters and locals: the laws distillation may use depend on them (A3)."""
    out = {p["name"]: p.get("type") for p in (fn or {}).get("params") or []}
    out.update((fn or {}).get("locals") or {})
    return out


def _canonical(term, rules, costs, fn=None, ops=None) -> dict:
    from . import egraph as E
    if term is None:
        return {"status": "pending", "why": "a loop or several statements: its closed form waits for distillation"}
    try:
        r = E.canonical(term, rules, costs, _var_sorts(fn), ops, max_iter=6, max_nodes=3000)
    except ValueError as exc:
        return {"status": "pending", "why": str(exc)}
    return {"status": "canonical", "term": r["term"], "hash": r["hash"], "cost": r["cost"], "by": "method/saturate",
            "certificate": {"equalities": sorted(r["fired"]), "saturated": r["saturated"],
                            "iterations": r["iterations"]}}


def _witness_forms(ctx, card, ref_form, form, seed: int, samples: int = 24) -> dict:
    """The form agrees with the reference form on seeded inputs inside the form's domain."""
    from . import witness as W
    try:
        ref, f = W.python_callable(ctx, ref_form, card), W.python_callable(ctx, form, card)
    except Exception as exc:  # noqa: BLE001 -- a form that does not load is reported as such
        return {"kind": "witness", "status": "error", "reason": f"{type(exc).__name__}: {exc}"}
    arity = len((card.get("signature") or {}).get("params") or [])
    try:
        gens = W._generators(ctx, card, form, arity, form.get("domain"))
    except Exception:  # noqa: BLE001 -- no generator for this domain
        gens = card.get("generators") or [{"int": [-50, 50]}] * arity
    rng = random.Random(seed)
    checks = 0
    for args in V.inputs(gens, samples, rng):
        try:
            with W.time_limit(2.0):
                a, b = ref(*args), f(*args)
        except Exception:  # noqa: BLE001 -- outside the form's domain: not compared
            continue
        if not V.same(a, b):
            return {"kind": "witness", "status": "refuted", "seed": seed, "at": list(args), "values": [a, b]}
        checks += 1
    return {"kind": "witness", "status": "witnessed" if checks else "vacuous", "seed": seed, "checks": checks}


def build(ctx, seed: int | None = None) -> dict:
    from . import egraph as E
    from . import godel as G
    from . import search
    from . import tiers as T
    from .frontend_python import lift_source
    seed = V.fresh_seed() if seed is None else seed
    rules, costs, entries = E.rules_from_cards(ctx.store), search.op_costs(ctx.store), G.ledger(ctx.store)
    forms_canon = {c.name[len("form__"):]: c for c in ctx.store.cards("functional_identity")
                   if c.get("kind") == "canonical_form"}
    lv = ctx.load_state("last_verify") or {}
    fn_results = ((lv.get("sections") or {}).get("functions") or {}).get("cards") or {}
    defs, acts, trans = [], [], []
    for card in sorted(ctx.store.cards("algorithm"), key=lambda c: c.name):
        name = f"alg__{card.name}"
        forms = [f for f in card.get("forms") or [] if f.get("lang") == "python" and f.get("code")]
        ref = next((f for f in forms if f["name"] == card.get("reference_form")), forms[0] if forms else None)
        lifted = [lf for lf in lift_source(ref["code"], ctx.ops) if lf.ok] if ref else []
        entry = next((lf.ir for lf in lifted if lf.name == (ref or {}).get("entry")), lifted[0].ir if lifted else None)
        term = _single_return(entry)
        canon = _canonical(term, rules, costs, entry, ctx.ops)
        fc = forms_canon.get(card.name)
        if canon["status"] == "pending" and fc:
            canon = {"status": "recurrence", "canonical": fc["canonical"], "godel": fc["godel"],
                     "by": "method/fit_recurrence", "certificate": {"checked": fc.get("checked")}}
        actions, obligations = [], []
        for f in card.get("forms") or []:
            aname = f"alg__{card.name}__{f['name']}"
            if ref is not None and f is ref:
                link = {"kind": "source", "status": "source"}
            elif ref is not None and f.get("lang") == "python" and f.get("code"):
                # a witness sized by the forms' class proves (tiers.py); otherwise seeded inputs sample
                link = T.prove(ctx, card, ref, f) or {**_witness_forms(ctx, card, ref, f, seed), "tier": "sample"}
            else:
                link = {"kind": "witness", "status": "pending", "reason": "no runnable Python form to compare",
                        "tier": "sample"}
            acts.append({"name": aname, "category": "action", "truth": f"definition/{name}", "lang": f.get("lang"),
                         "code": f"algorithm/{card.name}#{f['name']}", "method": "method/human_written", "link": link,
                         "complexity": f.get("complexity")})
            actions.append(f"action/{aname}")
            if link["kind"] != "source":
                obligations.append({"claim": f"form {f['name']} == the definition", "status": link["status"],
                                    "tier": link["tier"],
                                    "evidence": {k: link[k] for k in ("seed", "checks", "at", "points", "theorems",
                                                                      "classes", "by") if k in link}})
        defs.append({"name": name, "category": "definition", "subject": f"algorithm/{card.name}",
                     "math": {"text": card.get("statement", ""), "type": _type(card.get("signature") or {}),
                              "term": term if term is not None else entry, "form": (ref or {}).get("name")},
                     "explanation": f"{card.get('statement', '')}. Its term is the {(ref or {}).get('name')} form "
                                    f"lifted into the core; every other form is an action checked against it.",
                     "canonical": canon, "identity": identity(canon, term, entry),
                     "godel": _godel(ctx, card, entries, term, canon, len(lifted) == 1),
                     "proof_obligations": obligations,
                     "actions": actions, "transformations": [],
                     "origin": {"kind": "written", "from": (card.get("provenance") or {}).get("origin", "cardmodel")},
                     "methods": ["method/lift_python", canon.get("by", "method/saturate")]})
    for card in sorted(ctx.store.cards("function"), key=lambda c: c.name):
        name = f"fn__{card.name}"
        mod = card.get("ir") or {}
        entry = next((f for f in mod.get("functions") or [] if f.get("name") == mod.get("entry")), None)
        term = _single_return(entry)
        canon = _canonical(term, rules, costs, entry, ctx.ops)
        res = (fn_results.get(card.qualified) or {}).get("languages") or {}
        actions, obligations = [], []
        for f in card.get("forms") or []:
            aname = f"fn__{card.name}__{f['name']}"
            if f["name"] == "python_source":
                link = {"kind": "source", "status": "source"}
                method = "method/human_written"
            else:
                st = (res.get(f.get("lang")) or {}).get("status")
                link = {"kind": "witness", "status": {"pass": "witnessed", "fail": "refuted"}.get(st, st or "pending"),
                        "by": "verify --only functions", "tier": "sample"}
                method = "method/emit"
            acts.append({"name": aname, "category": "action", "truth": f"definition/{name}", "lang": f.get("lang"),
                         "code": f"function/{card.name}#{f['name']}", "method": method, "link": link})
            actions.append(f"action/{aname}")
            if link["kind"] != "source":
                obligations.append({"claim": f"the {f.get('lang')} form == the definition", "status": link["status"],
                                    "tier": link["tier"]})
        prov = card.get("provenance") or {}
        defs.append({"name": name, "category": "definition", "subject": card.qualified,
                     "math": {"text": card.get("statement", ""), "type": _type(card.get("signature") or {}),
                              "term": term if term is not None else mod},
                     "explanation": f"{card.get('statement', '')}. Lifted from its source; every language form is "
                                    f"emitted from the term and witnessed against it.",
                     "canonical": canon, "identity": identity(canon, term, mod),
                     "godel": _godel(ctx, card, entries, term, canon, len(mod.get("functions") or []) == 1),
                     "proof_obligations": obligations,
                     "actions": actions, "transformations": [],
                     "origin": {"kind": "lifted", "from": prov.get("origin", "")},
                     "methods": ["method/lift_python", "method/emit", canon.get("by", "method/saturate")]})
    by_subject = {d["subject"]: d for d in defs}
    for c in sorted(ctx.store.cards("functional_identity"), key=lambda c: c.name):
        if c.get("kind") == "canonical_form" or c.get("f") not in by_subject or c.get("g") not in by_subject:
            continue
        tname = f"identity__{c.name}"
        kinds = [k for k in ("shift", "composition", "composition_rev", "cross_identity", "basis_change",
                             "shared_operator") if c.get(k)]
        trans.append({"name": tname, "category": "transformation", "from": f"definition/{by_subject[c['f']]['name']}",
                      "to": f"definition/{by_subject[c['g']]['name']}", "kind": kinds, "statement": c.get("statement"),
                      "evidence": {"kind": "witness", "by": "method/fit_recurrence", "tier": "sample",
                                   "from": f"functional_identity/{c.name}"}})
        for side in ("f", "g"):
            by_subject[c[side]]["transformations"].append(f"transformation/{tname}")
    return {"seed": seed, "definitions": defs, "actions": acts, "transformations": trans}


def write(ctx, built: dict, layer: str = "model") -> dict:
    st = ctx.store
    for reg, key in (("definition", "definitions"), ("action", "actions"), ("transformation", "transformations")):
        st.save_pack(reg, PACK, built[key], layer=layer)
    st.invalidate()
    return {k: len(built[k]) for k in ("definitions", "actions", "transformations")}


def check(ctx) -> dict:
    from . import godel as G
    from . import tiers as T
    st = ctx.store
    entries = G.ledger(st)
    atoms = {e["atom"] for e in entries}
    problems = []
    defs = {c.qualified: c for c in st.cards("definition")}
    acts = {c.qualified: c for c in st.cards("action")}
    methods = {c.qualified: c for c in st.cards("method")}
    for q, d in defs.items():
        if not (d.get("origin") or {}).get("kind"):
            problems.append(f"{q}: no origin")
        for o in d.get("proof_obligations") or []:
            if o.get("tier") not in T.TIERS:
                problems.append(f"{q}: the claim '{o.get('claim')}' carries no tier (CM46)")
        if st.get(d.get("subject") or "") is None:
            problems.append(f"{q}: its subject {d.get('subject')} does not exist")
        content = (d.get("godel") or {}).get("content")
        if content is None:                          # {} is content too: a move has no operations (the unit)
            problems.append(f"{q}: no Gödel content")
        elif set(content) - atoms:
            problems.append(f"{q}: atoms outside the ledger: {sorted(set(content) - atoms)[:3]}")
        else:
            problems += [f"{q}: {x}" for x in G.vector_problems(d.get("godel") or {}, entries)]
        if not str((d.get("identity") or {}).get("hash", "")).startswith("sha256:"):
            problems.append(f"{q}: no identity (the hash of its structure, CM45)")
        elif (d.get("identity") or {}).get("under") not in EQ.RELATIONS:
            problems.append(f"{q}: its identity names no equivalence it was taken under (FOUNDATIONS.md A4)")
        for a in d.get("actions") or []:
            if a not in acts:
                problems.append(f"{q}: action {a} does not exist")
        for m in d.get("methods") or []:
            if m not in methods:
                problems.append(f"{q}: method {m} does not exist")
    refuted = []
    for q, a in acts.items():
        if a.get("truth") not in defs:
            problems.append(f"{q}: its truth {a.get('truth')} is not a definition")
        if a.get("method") not in methods:
            problems.append(f"{q}: its method {a.get('method')} does not exist")
        link = a.get("link") or {}
        if link.get("kind") not in ("proof", "witness", "source"):
            problems.append(f"{q}: no link to its truth (proof, witness or source)")
        elif link.get("kind") != "source" and link.get("tier") not in T.TIERS:
            problems.append(f"{q}: its link carries no tier (CM46)")
        if link.get("status") == "refuted":
            refuted.append(q)
            problems.append(f"{q}: its witness refutes it ({link.get('at')})")
    for c in st.cards("transformation"):
        for side in ("from", "to"):
            if c.get(side) not in defs:
                problems.append(f"{c.qualified}: `{side}` {c.get(side)} is not a definition")
        if not c.get("evidence"):
            problems.append(f"{c.qualified}: no evidence")
    for q, m in methods.items():
        if not m.get("decides") or not m.get("limits"):
            problems.append(f"{q}: a method states what it decides and its limits")
    subjects = [c.qualified for reg in ("algorithm", "function") for c in st.cards(reg)]
    covered = {d.get("subject") for d in defs.values()}
    fdefs = [d for d in defs.values() if (d.get("subject") or "").split("/")[0] in ("algorithm", "function")]
    canon = sum(1 for d in fdefs if (d.get("canonical") or {}).get("status") in ("canonical", "recurrence"))
    symbolic = sum(1 for d in defs.values() if (d.get("origin") or {}).get("kind") == "symbolic"
                   and all(o.get("status") == "witnessed" for o in d.get("proof_obligations") or []))
    return {"status": "fail" if problems else ("pass" if defs else "vacuous"), "problems": problems,
            "definitions": len(defs), "actions": len(acts), "transformations": len(st.cards("transformation")),
            "methods": len(methods), "refuted": refuted,
            "coverage": round(sum(1 for s in subjects if s in covered) / len(subjects), 4) if subjects else None,
            "canonical": round(canon / len(fdefs), 4) if fdefs else None, "symbolic_instructions": symbolic,
            "proof_tier": sum(1 for d in defs.values() for o in d.get("proof_obligations") or []
                              if o.get("tier") == "proof" and o.get("status") == "proved"),
            "actions_without_truth": sum(1 for a in acts.values() if a.get("truth") not in defs)}


__all__ = ["REGISTRIES", "TRANSFORMATION_SOURCES", "build", "check", "write"]
