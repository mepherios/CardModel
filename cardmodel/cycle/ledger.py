"""ledger — the core the model must never silently lose (law CM37).

The core ledger (``cards/ledger/core``) names what the model is: every law (a hash of its statement and its
witness test), every goal (metric, direction, target), every registry, every command with its actions, and every
section ``verify`` runs. ``check`` compares the model as it is now with the ledger:

  lost          in the ledger, gone now                                     fails
  changed       a law's statement or witness, a goal's metric or direction  fails
  weakened      a goal's target moved the easy way                          fails
  new           here now, not in the ledger yet                             passes; ``accept`` records it
  strengthened  a goal's target moved the hard way                          passes; ``accept`` records it

``accept`` writes the model as it is into the ledger with a versioned save (the previous ledger is archived,
CM14) and appends one amendment per lost, changed or weakened item, with the reason it was given. Growth can be
accepted alone (``additions_only``): the cycle does that when it records, so a new law is protected from the run
that first sees it, while a loss always needs a person and a reason.

Honest limits (L1): the ledger sees names, statements and targets, not behaviour. A law whose witness test is
gutted keeps its hash (the cycle's ``laws`` stage runs every witness for that); a command that still parses but
no longer works is the tests' business.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

LEDGER = "ledger/core"
KINDS = ("lost", "changed", "weakened", "new", "strengthened")
FAILING = ("lost", "changed", "weakened")
STATEMENT = ("The core the model must never silently lose: every law with its statement and witness, every goal "
             "with its target, every registry, command and verify section. A cycle or verify that finds one "
             "missing, changed or a goal weakened fails until the change is accepted with a reason (CM37).")


def _h(text) -> str:
    return hashlib.sha256(" ".join(str(text or "").split()).encode()).hexdigest()[:16]


def commands() -> dict:
    """Every command of the CLI and the actions it accepts, read from the argument parser."""
    import argparse
    from .. import cli
    out = {}
    for act in cli.build_parser()._actions:
        if isinstance(act, argparse._SubParsersAction):
            for name, sp in act.choices.items():
                acts = []
                for a in sp._actions:
                    if a.dest == "action" and a.choices:
                        acts = sorted(a.choices)
                out[name] = acts
    return dict(sorted(out.items()))


def snapshot(ctx) -> dict:
    """The model's core as it is now (model layer only: a project's own cards are not the model's core)."""
    from ..engines.verify import SECTIONS
    st = ctx.store

    def model(reg):
        return [c for c in st.cards(reg) if c.layer == "model"]
    laws = {c.name: {"statement": _h(c.get("statement")), "witness": c.get("witness")} for c in model("law")}
    goals = {c.name: {"metric": c.get("metric"), "direction": c.get("direction"), "target": c.get("target")}
             for c in model("goal")}
    regs = sorted(n for n, v in st.views.items() if any(r.layer == "model" for r in v.regs))
    return {"laws": dict(sorted(laws.items())), "goals": dict(sorted(goals.items())), "registries": regs,
            "commands": commands(), "verify_sections": list(SECTIONS)}


def _harder(direction: str, old, new) -> bool:
    return new > old if direction == "higher" else new < old


def diff(now: dict, led: dict) -> dict:
    """What changed between the ledger ``led`` and the model ``now``: {kind: [{"item", "detail"}]}."""
    out = {k: [] for k in KINDS}

    def add(kind, item, detail=""):
        out[kind].append({"item": item, "detail": detail})
    old, cur = led.get("laws") or {}, now.get("laws") or {}
    for n, v in old.items():
        w = cur.get(n)
        if w is None:
            add("lost", f"law/{n}", "the law card is gone")
            continue
        if v.get("statement") != w.get("statement"):
            add("changed", f"law/{n}", "its statement changed")
        if v.get("witness") != w.get("witness"):
            add("changed", f"law/{n}", f"its witness moved from {v.get('witness')} to {w.get('witness')}")
    for n in cur:
        if n not in old:
            add("new", f"law/{n}")
    old, cur = led.get("goals") or {}, now.get("goals") or {}
    for n, v in old.items():
        w = cur.get(n)
        if w is None:
            add("lost", f"goal/{n}", "the goal card is gone")
        elif (v.get("metric"), v.get("direction")) != (w.get("metric"), w.get("direction")):
            add("changed", f"goal/{n}", f"{v.get('metric')} ({v.get('direction')}) is now {w.get('metric')} "
                                        f"({w.get('direction')})")
        elif v.get("target") != w.get("target"):
            harder = _harder(v.get("direction"), v.get("target"), w.get("target"))
            add("strengthened" if harder else "weakened", f"goal/{n}",
                f"target {v.get('target')} -> {w.get('target')} ({v.get('direction')} is better)")
    for n in cur:
        if n not in old:
            add("new", f"goal/{n}")
    for key, label in (("registries", "registry"), ("verify_sections", "verify")):
        a, b = set(led.get(key) or []), set(now.get(key) or [])
        for n in sorted(a - b):
            add("lost", f"{label}/{n}", f"the {label} {'section ' if label == 'verify' else ''}{n} is gone")
        for n in sorted(b - a):
            add("new", f"{label}/{n}")
    old, cur = led.get("commands") or {}, now.get("commands") or {}
    for n, acts in old.items():
        if n not in cur:
            add("lost", f"command/{n}", f"`cardmodel {n}` is gone")
            continue
        for a in acts:
            if a not in cur[n]:
                add("lost", f"command/{n} {a}", f"`cardmodel {n} {a}` is gone")
    for n, acts in cur.items():
        if n not in old:
            add("new", f"command/{n}")
        else:
            for a in acts:
                if a not in old[n]:
                    add("new", f"command/{n} {a}")
    return out


def sizes(core: dict) -> dict:
    return {k: len(core.get(k) or []) for k in ("laws", "goals", "registries", "commands", "verify_sections")}


def check(ctx, now: dict | None = None) -> dict:
    """The verify section and the cycle's first stage: fail when anything in the ledger was lost, changed or
    weakened; vacuous when there is no ledger yet (a check that cannot fail is not a pass, CM07)."""
    now = now if now is not None else snapshot(ctx)
    card = ctx.store.get(LEDGER)
    if card is None:
        return {"status": "vacuous", "reason": "no core ledger yet: cardmodel cycle ledger --accept --reason ...",
                "now": sizes(now), **{k: [] for k in KINDS}, "counts": {k: 0 for k in KINDS}}
    d = diff(now, card.get("core") or {})
    bad = sum(len(d[k]) for k in FAILING)
    return {"status": "fail" if bad else "pass", **d, "counts": {k: len(v) for k, v in d.items()},
            "protected": sizes(card.get("core") or {}), "now": sizes(now), "accepted": card.get("accepted"),
            "amendments": len(card.get("amendments") or []), "layer": card.layer}


def _grow(old: dict, now: dict) -> dict:
    """The old ledger plus everything new and every strengthened target (nothing removed, nothing weakened)."""
    core = {"laws": dict(old.get("laws") or {}), "goals": dict(old.get("goals") or {}),
            "registries": sorted(set(old.get("registries") or []) | set(now.get("registries") or [])),
            "commands": {n: list(a) for n, a in (old.get("commands") or {}).items()},
            "verify_sections": list(old.get("verify_sections") or [])}
    for n, v in (now.get("laws") or {}).items():
        core["laws"].setdefault(n, v)
    for n, v in (now.get("goals") or {}).items():
        o = core["goals"].get(n)
        if o is None:
            core["goals"][n] = v
        elif (o.get("metric"), o.get("direction")) == (v.get("metric"), v.get("direction")) and \
                v.get("target") != o.get("target") and _harder(o.get("direction"), o.get("target"), v.get("target")):
            core["goals"][n] = v
    for s in now.get("verify_sections") or []:
        if s not in core["verify_sections"]:
            core["verify_sections"].append(s)
    for n, acts in (now.get("commands") or {}).items():
        core["commands"][n] = sorted(set(core["commands"].get(n, [])) | set(acts))
    core["laws"] = dict(sorted(core["laws"].items()))
    core["goals"] = dict(sorted(core["goals"].items()))
    core["commands"] = dict(sorted(core["commands"].items()))
    return core


def accept(ctx, reason: str | None = None, additions_only: bool = False, layer: str = "model",
           now: dict | None = None) -> dict:
    """Write the model's core into the ledger (versioned). A loss needs a reason and becomes an amendment."""
    now = now if now is not None else snapshot(ctx)
    card = ctx.store.get(LEDGER)
    old = dict(card.get("core") or {}) if card is not None else {}
    d = diff(now, old) if card is not None else {k: [] for k in KINDS}
    losses = [(k, x) for k in FAILING for x in d[k]]
    if losses and not additions_only and not (reason or "").strip():
        raise ValueError(f"{len(losses)} item(s) lost, changed or weakened "
                         f"({', '.join(x['item'] for _, x in losses[:5])}): accepting that needs --reason")
    grown = len(d["new"]) + len(d["strengthened"])
    if card is not None and grown == 0 and (additions_only or not losses):
        return {"changed": False, "grown": 0, "amended": 0, "still_failing": len(losses) if additions_only else 0,
                "path": str(card.path), "protected": sizes(old)}
    date = datetime.now(timezone.utc).isoformat(timespec="seconds")
    amendments = list(card.get("amendments") or []) if card is not None else []
    if additions_only:
        core = _grow(old, now)
    else:
        core = now
        for kind, x in losses:
            amendments.append({"date": date, "item": x["item"], "change": kind, "detail": x["detail"],
                               "reason": reason.strip()})
    data = dict(card) if card is not None else {}
    data.update({"name": "core", "category": "ledger", "tier": 0, "statement": STATEMENT, "core": core,
                 "amendments": amendments, "accepted": date,
                 "accepted_reason": (reason or "").strip() or "growth recorded by the cycle",
                 "provenance": {"origin": "cardmodel cycle ledger", "witness": "tests/test_cycle.py"}})
    saved, changed = ctx.store.save(data, layer=layer, category="ledger")
    return {"changed": changed, "grown": grown, "amended": 0 if additions_only else len(losses),
            "still_failing": len(losses) if additions_only else 0, "path": str(saved.path), "protected": sizes(core)}


__all__ = ["FAILING", "KINDS", "LEDGER", "accept", "check", "commands", "diff", "sizes", "snapshot"]
