"""mine — decipher the rules behind facts: which logic carries through the data.

Given relations (facts, or a theory's whole model), ``mine`` tests rule
templates and keeps those the data supports:

  symmetric    p(X, Y) -> p(Y, X)              transitive   p(X, Y), p(Y, Z) -> p(X, Z)
  inverse      p(X, Y) -> q(Y, X)              implies      p(X, Y) -> q(X, Y)   (and for unary relations)
  compose      p(X, Y), q(Y, Z) -> r(X, Z)     functional   p(X, Y), p(X, Z) -> Y = Z
  domain/range p(X, _) -> u(X), p(_, Y) -> u(Y)
  irreflexive  never p(X, X)                   antisymmetric p(X, Y), p(Y, X) -> X = Y

For each candidate: support (body instances where the head also holds),
confidence (support / body instances) and head coverage (support / head
facts). A rule with confidence 1 and support >= MIN_SUPPORT is an exact law
of the data (it becomes a logic_rule card with its evidence, CM04); lower
confidences are reported as tendencies with counterexamples.

Honest limits (L1): only these templates (rules of length <= 2 over unary
and binary relations); a law of the data is evidence about this data, not a
proof about the world; quadratic in the number of relations for compose.
"""
from __future__ import annotations

from collections import defaultdict

MIN_SUPPORT = 3
TENDENCY = 0.8


def relations(model, preds: set[str] | None = None) -> dict[str, set]:
    out = {}
    for p, rows in model.db.rel.items():
        if preds is not None and p not in preds:
            continue
        if rows:
            n = len(next(iter(rows)))
            if n in (1, 2):
                out[p] = set(rows)
    return out


def _rule(kind, text, head, body, support, total, head_size, counter, extra=None):
    conf = support / total if total else 0.0
    return {"template": kind, "text": text, "head": head, "body": body, "support": support, "body_instances": total,
            "confidence": round(conf, 4), "head_coverage": round(support / head_size, 4) if head_size else 0.0,
            "counterexamples": counter[:3], **(extra or {})}


def _v(name):
    return {"var": name}


def mine(rels: dict[str, set], min_support: int = MIN_SUPPORT, tendency: float = TENDENCY,
         max_compose: int = 40) -> dict:
    binary = {p: r for p, r in rels.items() if r and len(next(iter(r))) == 2}
    unary = {p: {t[0] for t in r} for p, r in rels.items() if r and len(next(iter(r))) == 1}
    found = []
    X, Y, Z = _v("X"), _v("Y"), _v("Z")
    by_first = {p: _index(r, 0) for p, r in binary.items()}
    for p, r in binary.items():
        # symmetric
        sup = sum(1 for (a, b) in r if (b, a) in r)
        bad = [[a, b] for (a, b) in r if (b, a) not in r]
        found.append(_rule("symmetric", f"{p}(Y, X) <- {p}(X, Y).", {"pred": p, "args": [Y, X]},
                           [{"pred": p, "args": [X, Y]}], sup, len(r), len(r), bad))
        # transitive
        tot = sup = 0
        bad = []
        for (a, b) in r:
            for c in by_first[p].get(b, ()):
                tot += 1
                if (a, c) in r:
                    sup += 1
                elif len(bad) < 3:
                    bad.append([a, b, c])
        if tot:
            found.append(_rule("transitive", f"{p}(X, Z) <- {p}(X, Y), {p}(Y, Z).", {"pred": p, "args": [X, Z]},
                               [{"pred": p, "args": [X, Y]}, {"pred": p, "args": [Y, Z]}], sup, tot, len(r), bad))
        # functional / irreflexive / antisymmetric (constraints: support = instances that respect them)
        firsts = defaultdict(set)
        for a, b in r:
            firsts[a].add(b)
        multi = [[a, sorted(map(str, bs))[:3]] for a, bs in firsts.items() if len(bs) > 1]
        found.append(_rule("functional", f"never: {p}(X, Y), {p}(X, Z), Y != Z.", None,
                           [{"pred": p, "args": [X, Y]}, {"pred": p, "args": [X, Z]}],
                           len(firsts) - len(multi), len(firsts), len(r), multi, {"constraint": True}))
        refl = [[a, b] for (a, b) in r if a == b]
        found.append(_rule("irreflexive", f"never: {p}(X, X).", None, [{"pred": p, "args": [X, X]}],
                           len(r) - len(refl), len(r), len(r), refl, {"constraint": True}))
        both = [(a, b) for (a, b) in r if a != b and (b, a) in r]
        found.append(_rule("antisymmetric", f"never: {p}(X, Y), {p}(Y, X), X != Y.", None,
                           [{"pred": p, "args": [X, Y]}, {"pred": p, "args": [Y, X]}],
                           len(r) - len(both), len(r), len(r), [list(x) for x in both], {"constraint": True}))
        for q, s in binary.items():
            if q == p:
                continue
            sup = sum(1 for (a, b) in r if (b, a) in s)
            found.append(_rule("inverse", f"{q}(Y, X) <- {p}(X, Y).", {"pred": q, "args": [Y, X]},
                               [{"pred": p, "args": [X, Y]}], sup, len(r), len(s),
                               [[a, b] for (a, b) in r if (b, a) not in s]))
            sup = len(r & s)
            found.append(_rule("implies", f"{q}(X, Y) <- {p}(X, Y).", {"pred": q, "args": [X, Y]},
                               [{"pred": p, "args": [X, Y]}], sup, len(r), len(s), [list(t) for t in r - s]))
        for u, members in unary.items():
            dom = {a for a, _ in r}
            rng = {b for _, b in r}
            found.append(_rule("domain", f"{u}(X) <- {p}(X, _).", {"pred": u, "args": [X]},
                               [{"pred": p, "args": [X, _v("_")]}], len(dom & members), len(dom), len(members),
                               [[a] for a in dom - members]))
            found.append(_rule("range", f"{u}(Y) <- {p}(_, Y).", {"pred": u, "args": [Y]},
                               [{"pred": p, "args": [_v("_"), Y]}], len(rng & members), len(rng), len(members),
                               [[b] for b in rng - members]))
    names = sorted(binary)[:max_compose]
    for p in names:
        for q in names:
            pairs = set()
            for (a, b) in binary[p]:
                for c in by_first[q].get(b, ()):
                    pairs.add((a, c))
            if not pairs:
                continue
            for r_name in names:
                if r_name in (p, q) and not (p == q == r_name):
                    continue
                if p == q == r_name:
                    continue                       # that is transitivity, tested above
                rr = binary[r_name]
                sup = len(pairs & rr)
                if sup == 0:
                    continue
                found.append(_rule("compose", f"{r_name}(X, Z) <- {p}(X, Y), {q}(Y, Z).",
                                   {"pred": r_name, "args": [X, Z]},
                                   [{"pred": p, "args": [X, Y]}, {"pred": q, "args": [Y, Z]}], sup, len(pairs),
                                   len(rr), [list(t) for t in sorted(pairs - rr, key=str)]))
    for u, mu in unary.items():
        for w, mw in unary.items():
            if u != w:
                found.append(_rule("implies", f"{w}(X) <- {u}(X).", {"pred": w, "args": [X]},
                                   [{"pred": u, "args": [X]}], len(mu & mw), len(mu), len(mw),
                                   [[x] for x in mu - mw]))
    laws = [f for f in found if f["confidence"] == 1.0 and f["support"] >= min_support]
    tendencies = [f for f in found if tendency <= f["confidence"] < 1.0 and f["support"] >= min_support]
    laws.sort(key=lambda f: (-f["support"], f["text"]))
    tendencies.sort(key=lambda f: (-f["confidence"], -f["support"], f["text"]))
    return {"relations": {p: len(r) for p, r in rels.items()}, "candidates": len(found), "laws": laws,
            "tendencies": tendencies, "min_support": min_support}


def _index(rows, col):
    ix = defaultdict(list)
    for t in rows:
        ix[t[col]].append(t[1 - col])
    return ix


def rule_cards(result: dict, theory: str, source: str) -> list[dict]:
    """Exact laws as logic_rule cards (learned, with evidence); constraints become never-rules."""
    out = []
    for k, f in enumerate(result["laws"]):
        body = list(f["body"])
        if f.get("constraint"):
            extra = {"functional": [{"test": ["CMP_NE", ["var", "Y"], ["var", "Z"]]}],
                     "antisymmetric": [{"test": ["CMP_NE", ["var", "X"], ["var", "Y"]]}]}.get(f["template"], [])
            body = body + extra
        name = f"{theory}.mined_{f['template']}_{k}"
        out.append({"name": name, "category": "logic_rule", "theory": theory, "label": f"mined_{f['template']}_{k}",
                    "head": f["head"], "body": body, "text": f["text"],
                    "kind": "constraint" if f.get("constraint") else "rule",
                    "evidence": {k2: f[k2] for k2 in ("support", "body_instances", "confidence", "head_coverage")},
                    "metadata": {"learned": True, "confidence": "exact on the observed data",
                                 "evidence_count": f["support"]},
                    "provenance": {"origin": source, "tool": "cardmodel logic mine"}})
    return out


__all__ = ["MIN_SUPPORT", "mine", "relations", "rule_cards"]
