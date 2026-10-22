"""difficulty — the arithmetical rank of every question the product asks (Gödel method W-15: Cap-18, Ph-15, GM-7).

  ranks      where a yes/no question about codes sits in the arithmetical hierarchy, as an upper bound proved from
             its form: decidable (a total computable test), Σ1 (∃ of a decidable relation: it can be confirmed by a
             witness, never refuted in general, like provable or halts), Π1 (∀ of a decidable relation: refuted by
             one counterexample, never confirmed by finitely many checks, like consistency or the equality of two
             total programs), Π2 (∀∃, like totality), beyond (no arithmetical definition: truth, by Tarski).
  methods    every method card carries the rank of the question it decides and of the general question it serves.
  questions  ``question`` cards: what the product asks, its rank, and whether the product may promise to answer it
             (only decidable questions, Ph-15). The rest are left open, and each names what the product does
             instead: a proof-tier class, a search that confirms, a witness that refutes, a label.

Honest limits (L1): a rank here is an upper bound shown from the question's logical form (Def-4: Prov is ∃y of the
decidable Proof). Completeness for its level (that nothing simpler decides it) is cited from the literature
(Rice, Turing, Post-Markov, Gödel), not proved here.
"""
from __future__ import annotations

from collections import Counter

RANKS = ("decidable", "Σ1", "Π1", "Π2", "beyond")
FULL = "decidable"


def check(ctx) -> dict:
    """Every method card ranked; every question ranked, and only decidable questions promised in full."""
    problems = []
    methods = ctx.store.cards("method")
    for m in methods:
        r = m.get("rank") or {}
        if r.get("decides") not in RANKS + ("none",):
            problems.append(f"{m.qualified}: no arithmetical rank for what it decides (GM-7)")
        elif r.get("decides") != "none" and not r.get("question"):
            problems.append(f"{m.qualified}: a rank with no question")
    questions = ctx.store.cards("question")
    for q in questions:
        if q.get("rank") not in RANKS:
            problems.append(f"{q.qualified}: no rank")
        if q.get("promise") == "answered" and q.get("rank") != FULL:
            problems.append(f"{q.qualified}: a {q.get('rank')} question promised as answered (Ph-15)")
        if not q.get("cites"):
            problems.append(f"{q.qualified}: cites no handover id")
    by_m = Counter((m.get("rank") or {}).get("decides", "missing") for m in methods)
    by_q = Counter(q.get("rank") for q in questions)
    open_q = sorted(q.name for q in questions if q.get("promise") != "answered")
    return {"status": "fail" if problems else ("pass" if methods else "vacuous"), "problems": problems,
            "methods": len(methods), "methods_by_rank": dict(by_m), "questions": len(questions),
            "questions_by_rank": dict(by_q), "open": open_q}


__all__ = ["FULL", "RANKS", "check"]
