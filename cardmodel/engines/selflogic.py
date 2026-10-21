"""selflogic — the card store as facts, and the model's laws (stdlib/self.card) as logic over them.

Facts (one per card property): card(Q), registry(R), external_registry(R), in_registry(Q, R),
depends_on(Q, D) (bare names resolved like the kernel's closure), status(Q, S),
learned(Q), law(L), law_witness(L, T), goal(G), goal_metric(G, M), theorem_status(T, S), has_proof(T),
has_evidence(T), op_ir(O), op_eval(O), special_op(O), rewrite_rule(R), rule_vars(R), logic_rule(Q),
language(L), codegen(L), capability(C), core_capability(C), capability_check(C, K), capability_test(C, T),
carries(C, L), self_step(S), step_runs(S, F). Card names are qualified (``category/name``) so every fact is
unambiguous.

Honest limits (L1): these facts cover the fields above, not every field of every card; the theory checks
what its rules say and nothing else (the kernel's schema validation is still the authority on shapes).
"""
from __future__ import annotations

from pathlib import Path

from ..kernel import paths
from . import logic as L

SPECIAL = {"AND", "OR", "IF_EXPR"}


def store_facts(store) -> L.Program:
    prog = L.Program(name="self")
    add = prog.add_fact
    names = store._name_index()
    for reg in store.categories():
        add("registry", [reg])
        if store.views[reg].meta.get("references") == "external":
            add("external_registry", [reg])
    for q, c in store.ALL.items():
        add("card", [q])
        add("in_registry", [q, c.registry])
        for d in c.depends_on or []:
            targets = [d] if "/" in d else [f"{r}/{d}" for r in (names.get(d) or [])] or [d]
            for t in targets:                       # a bare name resolves like the kernel's closure (L45)
                add("depends_on", [q, t if "/" in t else t])
        if isinstance(c.get("status"), str):
            add("status", [q, c["status"]])
        if (c.metadata or {}).get("learned"):
            add("learned", [q])
    for c in store.cards("law"):
        add("law", [c.qualified])
        if c.get("witness"):
            add("law_witness", [c.qualified, c["witness"]])
    for c in store.cards("goal"):
        add("goal", [c.qualified])
        if c.get("metric"):
            add("goal_metric", [c.qualified, c["metric"]])
    for c in store.cards("theorem"):
        add("theorem_status", [c.qualified, c.get("status", "conjecture")])
        if any(p.get("ok") for p in c.get("proofs") or []):
            add("has_proof", [c.qualified])
        if (c.get("evidence") or {}).get("checks"):
            add("has_evidence", [c.qualified])
    for c in store.cards("op"):
        ir = c.get("ir")
        if isinstance(ir, dict):
            add("op_ir", [c.qualified])
            if ir.get("eval"):
                add("op_eval", [c.qualified])
            if c.name in SPECIAL:
                add("special_op", [c.qualified])
    for c in store.cards("rewrite_rule"):
        add("rewrite_rule", [c.qualified])
        if c.get("vars"):
            add("rule_vars", [c.qualified])
    for c in store.cards("logic_rule"):
        add("logic_rule", [c.qualified])
    for c in store.cards("language"):
        add("language", [c.qualified])
        if c.get("codegen") is not None:
            add("codegen", [c.qualified])
    for c in store.cards("capability"):
        add("capability", [c.qualified])
        if c.get("core"):
            add("core_capability", [c.qualified])
        if c.get("check"):
            add("capability_check", [c.qualified, c["check"]])
        for t in c.get("tests") or []:
            add("capability_test", [c.qualified, t])
        for law in c.get("laws") or []:
            add("carries", [c.qualified, law])
    for c in store.cards("self_step"):
        add("self_step", [c.qualified])
        if c.get("run"):
            add("step_runs", [c.qualified, c["run"]])
    return prog


def self_source() -> Path:
    return paths.home() / "stdlib" / "self.card"


def evaluate_self(ctx) -> dict:
    """Evaluate stdlib/self.card over the store's facts. Violations are law breaks, each with its proof."""
    from ..lang.compile import compile_file
    mod = compile_file(self_source(), ctx.ops, ctx.store)
    prog = store_facts(ctx.store)
    prog.rules.extend(mod.program.rules)
    prog.facts.extend(mod.program.facts)
    model = L.evaluate(prog, ctx.ops)
    cyclic = sorted(t[0] for t in model.db.rel.get("cyclic", ()))
    sizes = {t[0]: t[1] for t in model.db.rel.get("registry_size", ())}
    return {"status": "fail" if model.violations else ("pass" if model.stats["given"] else "vacuous"),
            "stats": model.stats, "violations": model.violations[:50], "violation_count": len(model.violations),
            "cyclic": cyclic[:20], "registries": len(sizes), "rules": len(mod.program.rules), "model": model}


__all__ = ["evaluate_self", "self_source", "store_facts"]
