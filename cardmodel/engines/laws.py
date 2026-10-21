"""laws — find the mathematical laws that carry through the op cards, prove them, and let them optimize.

Templates (instantiated over every op card with IR semantics and matching types):

  binary f        commutative f(a,b)=f(b,a) · associative · idempotent f(a,a)=a · identity e (0, 1, -1,
                  left/right) · absorbing z · self-cancel f(a,a)=c
  pairs f, g      distributive (left, right) f(a,g(b,c)) = g(f(a,b),f(a,c)) · absorption f(a,g(a,b)) = a
  unary u         involution u(u(a))=a · idempotent u(u(a))=u(a) · homomorphism u(f(a,b)) = f(u(a),u(b)) ·
                  duality u(f(a,b)) = g(u(a),u(b)) (De Morgan) · pull-through u(f(a,b)) = f(u(a),b) ·
                  monotone/antitone a<=b ==> u(a)<=u(b) · bounds u(a)>=0, f(a,b)>=a, f(a,b)<=a
  relations R     reflexive, irreflexive, symmetric, antisymmetric, transitive, total (comparison ops)

Partial ops get their definedness as hypotheses (divisor != 0; shift and power amounts in 0..64 / 0..8),
so a law is about the op where the op is defined. Every candidate is a theorem card: witnessed with a
seed (anti-vacuity: enough inputs must satisfy the hypotheses), then sent to Lean (core tactics). A law
that simplifies (its right side is smaller) becomes a rewrite_rule card, so it carries into
``rewrite --optimize`` and ``improve`` (CM24).

Honest limits (L1): only these templates; witnesses sample the integers (edges included); bit operators
have no Lean form in core, so those laws stay ``witnessed``.
"""
from __future__ import annotations

import itertools

from . import theorems as T
from . import values as V

A, B, C = ["var", "a"], ["var", "b"], ["var", "c"]
CONSTS = (0, 1, -1)
DIVISORS = ("FLOORDIV", "MOD")
SHIFTS = ("SHIFT_LEFT", "SHIFT_RIGHT")
RELATIONS = ("CMP_EQ", "CMP_NE", "CMP_LT", "CMP_LE", "CMP_GT", "CMP_GE")
SKIP_BINARY = {"POW_MOD"}


def _int_ops(ops, arity, rtype="int"):
    out = []
    for name, spec in sorted(ops.items()):
        if spec.fn is None or spec.arity != arity or name in SKIP_BINARY or name in ("TO_FLOAT", "TRUNC_INT"):
            continue
        if any(list(sig) == ["int"] * arity + [rtype] for sig in spec.types):
            out.append(name)
    return out


def defined(term) -> list:
    """Hypotheses under which every op in ``term`` is defined (and finite to evaluate)."""
    hyps = []
    if isinstance(term, list) and term and term[0] not in ("var", "int", "float", "bool"):
        for a in term[1:]:
            hyps += defined(a)
        if term[0] in DIVISORS:
            hyps.append(["ne", term[2], ["int", 0]])
        if term[0] in SHIFTS:
            hyps += [["le", ["int", 0], term[2]], ["le", term[2], ["int", 64]]]
        if term[0] == "POW":
            hyps += [["le", ["int", 0], term[2]], ["le", term[2], ["int", 8]]]
    return hyps


def _dedup(hyps):
    """Drop repeated hypotheses and ground ones that hold (``1 != 0``); a ground false one stays (vacuous)."""
    out, seen = [], set()
    for h in hyps:
        k = repr(h)
        if k in seen:
            continue
        seen.add(k)
        if not T_vars(h):
            try:
                if T.eval_prop(h, {}, _GROUND_OPS):
                    continue
            except Exception:  # noqa: BLE001 -- an undefined ground hypothesis stays and makes the law vacuous
                pass
        out.append(h)
    return out


_GROUND_OPS: dict = {}


def _law(name, template, ops_used, concl, extra_hyps=(), vtype="int"):
    vs = sorted(T_vars(concl) | set().union(*(T_vars(h) for h in extra_hyps)) if extra_hyps else T_vars(concl))
    hyps = list(extra_hyps)
    for side in concl[1:]:
        if isinstance(side, list):
            hyps += defined(side)
    return {"name": name, "category": "theorem", "vars": [{"name": v, "type": vtype} for v in vs],
            "hyps": _dedup(hyps), "concl": concl, "semantics": "card", "status": "conjecture",
            "origin": {"kind": "discovered", "template": template, "ops": list(ops_used)}}


def T_vars(p) -> set[str]:
    out: set[str] = set()
    if isinstance(p, list) and p:
        if p[0] == "var":
            out.add(p[1])
        else:
            for a in p[1:]:
                out |= T_vars(a)
    return out


def candidates(ops) -> list[dict]:
    _GROUND_OPS.clear()
    _GROUND_OPS.update(ops)
    bins = _int_ops(ops, 2)
    uns = _int_ops(ops, 1)
    out = []
    for f in bins:
        out.append(_law(f"law_comm_{f}", "commutative", [f], ["eq", [f, A, B], [f, B, A]]))
        out.append(_law(f"law_assoc_{f}", "associative", [f], ["eq", [f, [f, A, B], C], [f, A, [f, B, C]]]))
        out.append(_law(f"law_idem_{f}", "idempotent", [f], ["eq", [f, A, A], A]))
        for e in CONSTS:
            tag = {0: "0", 1: "1", -1: "m1"}[e]
            out.append(_law(f"law_ident_left_{f}_{tag}", "identity", [f], ["eq", [f, ["int", e], A], A]))
            out.append(_law(f"law_ident_right_{f}_{tag}", "identity", [f], ["eq", [f, A, ["int", e]], A]))
            out.append(_law(f"law_absorb_left_{f}_{tag}", "absorbing", [f], ["eq", [f, ["int", e], A], ["int", e]]))
            out.append(_law(f"law_absorb_right_{f}_{tag}", "absorbing", [f], ["eq", [f, A, ["int", e]], ["int", e]]))
        for c in (0, 1):
            out.append(_law(f"law_selfcancel_{f}_{c}", "self-cancel", [f], ["eq", [f, A, A], ["int", c]]))
        out.append(_law(f"law_upper_{f}", "bound", [f], ["ge", [f, A, B], A]))
        out.append(_law(f"law_lower_{f}", "bound", [f], ["le", [f, A, B], A]))
        out.append(_law(f"law_mono_left_{f}", "monotone", [f], ["le", [f, A, C], [f, B, C]], [["le", A, B]]))
    for f, g in itertools.permutations(bins, 2):
        out.append(_law(f"law_distrib_left_{f}_{g}", "distributive", [f, g],
                        ["eq", [f, A, [g, B, C]], [g, [f, A, B], [f, A, C]]]))
        out.append(_law(f"law_distrib_right_{f}_{g}", "distributive", [f, g],
                        ["eq", [f, [g, A, B], C], [g, [f, A, C], [f, B, C]]]))
        out.append(_law(f"law_absorption_{f}_{g}", "absorption", [f, g], ["eq", [f, A, [g, A, B]], A]))
    for u in uns:
        out.append(_law(f"law_involution_{u}", "involution", [u], ["eq", [u, [u, A]], A]))
        out.append(_law(f"law_idem_{u}", "idempotent", [u], ["eq", [u, [u, A]], [u, A]]))
        out.append(_law(f"law_nonneg_{u}", "bound", [u], ["ge", [u, A], ["int", 0]]))
        out.append(_law(f"law_dominates_{u}", "bound", [u], ["ge", [u, A], A]))
        out.append(_law(f"law_monotone_{u}", "monotone", [u], ["le", [u, A], [u, B]], [["le", A, B]]))
        out.append(_law(f"law_antitone_{u}", "antitone", [u], ["ge", [u, A], [u, B]], [["le", A, B]]))
        for f in bins:
            out.append(_law(f"law_hom_{u}_{f}", "homomorphism", [u, f], ["eq", [u, [f, A, B]], [f, [u, A], [u, B]]]))
            out.append(_law(f"law_pull_{u}_{f}", "pull-through", [u, f], ["eq", [u, [f, A, B]], [f, [u, A], B]]))
            for g in bins:
                if g != f:
                    out.append(_law(f"law_dual_{u}_{f}_{g}", "duality", [u, f, g],
                                    ["eq", [u, [f, A, B]], [g, [u, A], [u, B]]]))
    rels = [r for r in RELATIONS if r in ops]
    for r in rels:
        out.append(_law(f"law_refl_{r}", "reflexive", [r], ["bool", [r, A, A]]))
        out.append(_law(f"law_irrefl_{r}", "irreflexive", [r], ["not", ["bool", [r, A, A]]]))
        out.append(_law(f"law_sym_{r}", "symmetric", [r], ["imp", ["bool", [r, A, B]], ["bool", [r, B, A]]]))
        out.append(_law(f"law_antisym_{r}", "antisymmetric", [r],
                        ["imp", ["and", ["bool", [r, A, B]], ["bool", [r, B, A]]], ["eq", A, B]]))
        out.append(_law(f"law_trans_{r}", "transitive", [r],
                        ["imp", ["and", ["bool", [r, A, B]], ["bool", [r, B, C]]], ["bool", [r, A, C]]]))
        out.append(_law(f"law_total_{r}", "total", [r], ["or", ["bool", [r, A, B]], ["bool", [r, B, A]]]))
    for f in ("AND", "OR"):
        if f in ops:
            out.append(_law(f"law_comm_{f}", "commutative", [f], ["eq", [f, A, B], [f, B, A]], vtype="bool"))
            out.append(_law(f"law_assoc_{f}", "associative", [f], ["eq", [f, [f, A, B], C], [f, A, [f, B, C]]],
                            vtype="bool"))
            out.append(_law(f"law_idem_{f}", "idempotent", [f], ["eq", [f, A, A], A], vtype="bool"))
    if {"AND", "OR", "NOT"} <= set(ops):
        out.append(_law("law_demorgan_AND", "duality", ["NOT", "AND", "OR"],
                        ["eq", ["NOT", ["AND", A, B]], ["OR", ["NOT", A], ["NOT", B]]], vtype="bool"))
        out.append(_law("law_demorgan_OR", "duality", ["NOT", "OR", "AND"],
                        ["eq", ["NOT", ["OR", A, B]], ["AND", ["NOT", A], ["NOT", B]]], vtype="bool"))
        out.append(_law("law_distrib_AND_OR", "distributive", ["AND", "OR"],
                        ["eq", ["AND", A, ["OR", B, C]], ["OR", ["AND", A, B], ["AND", A, C]]], vtype="bool"))
        out.append(_law("law_involution_NOT", "involution", ["NOT"], ["eq", ["NOT", ["NOT", A]], A], vtype="bool"))
    return out


def _size(t) -> int:
    if isinstance(t, list) and t and t[0] not in ("var", "int", "float", "bool"):
        return 1 + sum(_size(a) for a in t[1:])
    return 1


PY = {"ADD": "+", "SUB": "-", "MUL": "*", "FLOORDIV": "//", "MOD": "%", "BIT_AND": "&", "BIT_OR": "|",
      "BIT_XOR": "^", "SHIFT_LEFT": "<<", "SHIFT_RIGHT": ">>", "POW": "**"}
PY_CALL = {"MIN": "min", "MAX": "max", "ABS": "abs", "GCD": "gcd"}


def pytext(t) -> str:
    """The rewrite engine's expression syntax (exprs.parse) for an IR term."""
    h = t[0]
    if h == "var":
        return t[1]
    if h == "int":
        return str(t[1]) if t[1] >= 0 else f"({t[1]})"
    if h in PY:
        return f"({pytext(t[1])} {PY[h]} {pytext(t[2])})"
    if h == "NEG":
        return f"(-{pytext(t[1])})"
    if h == "BIT_NOT":
        return f"(~{pytext(t[1])})"
    if h in PY_CALL:
        return f"{PY_CALL[h]}({', '.join(pytext(a) for a in t[1:])})"
    raise ValueError(f"no rewrite syntax for {h}")


def rule_card(law: dict) -> dict | None:
    """A simplifying equational law as a rewrite rule (left side larger than the right)."""
    concl = law["concl"]
    if concl[0] != "eq" or law["status"] not in ("proved", "witnessed") or any(v["type"] != "int" for v in law["vars"]):
        return None
    lhs, rhs = concl[1], concl[2]
    if _size(rhs) >= _size(lhs):
        lhs, rhs = rhs, lhs
        if _size(rhs) >= _size(lhs):
            return None
    try:
        l_text, r_text = pytext(lhs), pytext(rhs)
    except ValueError:
        return None
    cond = " and ".join(_cond_text(h) for h in law.get("hyps") or []) or None
    return {"name": law["name"].replace("law_", "rule_", 1), "category": "rewrite_rule", "tier": 1, "lhs": l_text,
            "rhs": r_text, "vars": [v["name"] for v in law["vars"]], "domain": "int", "condition": cond,
            "bidirectional": False, "statement": f"{l_text} == {r_text}" + (f" when {cond}" if cond else ""),
            "depends_on": [f"theorem/{law['name']}"],
            "metadata": {"learned": True, "confidence": law["status"], "evidence_count":
                         (law.get("evidence") or {}).get("checks", 0)},
            "provenance": {"origin": "cardmodel laws (discovered, simplifying)", "theorem": law["name"]}}


def _cond_text(h) -> str:
    rel = {"eq": "==", "ne": "!=", "lt": "<", "le": "<=", "gt": ">", "ge": ">="}
    if h[0] in rel:
        return f"{pytext(h[1])} {rel[h[0]]} {pytext(h[2])}"
    return T.prop_text(h)


def discover(ctx, seed: int | None = None, samples: int = 200, lean: bool = True, deep: bool = False) -> dict:
    seed = V.fresh_seed() if seed is None else seed
    cands = candidates(ctx.ops)
    witnessed, refuted, vacuous = [], 0, 0
    results = []
    for card in cands:
        w = T.witness(card, ctx.ops, seed=seed, samples=samples)
        if w["status"] == "witnessed":
            witnessed.append((card, w))
        elif w["status"] == "vacuous":
            vacuous += 1
        else:
            refuted += 1
    proofs, exe = {}, None
    if lean and witnessed:
        res = T.prove([c for c, _ in witnessed], ctx.store, ctx.ops, deep=deep)
        proofs, exe = res["results"], res["toolchain"]
    for card, w in witnessed:
        results.append(T.settle(card, w, proofs.get(card["name"]), exe))
    rules = [r for r in (rule_card(c) for c in results) if r]
    by_template: dict[str, int] = {}
    for c in results:
        by_template[c["origin"]["template"]] = by_template.get(c["origin"]["template"], 0) + 1
    return {"seed": seed, "candidates": len(cands), "refuted": refuted, "vacuous": vacuous, "laws": results,
            "witnessed": sum(1 for c in results if c["status"] == "witnessed"),
            "proved": sum(1 for c in results if c["status"] == "proved"), "by_template": by_template,
            "rules": rules, "toolchain": T.toolchain_version(exe)}


__all__ = ["candidates", "discover", "pytext", "rule_card"]
