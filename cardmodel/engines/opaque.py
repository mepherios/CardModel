"""opaque — run and witness a partial function: lifted IR whose opaque calls go to the original Python functions.

A function that does not lift is an *opaque boundary* (frontend_python.boundary_card: its signature, its cause, the
Python callable that implements it), and its callers lift as ``partial`` with that call edge recorded as a gap
(SCALING.md §3.3, "partial, not poisoned"). This module decides what such an IR may claim:

* **It runs only here.** :class:`HostInterpreter` is the reference interpreter in which a CALL to a boundary calls
  the original Python function (the *host*). Arguments are deep-copied first (the IR has list value semantics: a
  callee that mutates its argument shows up as a mismatch, not as a silent agreement) and the result must have the
  boundary's declared type, else the call is an IRError.
* **No target runs it.** A partial function is never ``ok``, so translate, improve, the matrix and every emitter keep
  skipping it; :func:`witness` reports ``targets.runnable = False`` with the boundaries that block them. A
  translation of a partial function is never claimed.
* **The witness can fail.** :func:`witness` runs the partial IR through the host and the original source on the same
  seeded inputs and compares them (values.same). Then, per boundary, it re-runs the inputs with that boundary's host
  perturbed (an int or float result + 1, a bool negated): a boundary whose perturbation never changes the output was
  not exercised by the inputs, and the status is ``unexercised``, not ``pass`` (CM07: a witness that cannot fail
  is not a witness).

Gödel model (GODEL_PURITY rule 3): whether a callee lifts and what an opaque call returns are questions about
values, answered by running the op cards' semantics and the original function, never from content. A boundary's
permanent name is the core's identity hash (frontend_python.boundary_card, egraph.semantic_hash); it has no
canonical term and so no Gödel content (its reading is syntax, F4).

Honest limits (L1): the witness executes the original functions, the boundaries included, so it inherits their
effects; it is run only on request (lift, lift-sweep and observe never call the host). :func:`witness_lifted`
builds the namespace from the functions' own sources and the module's constants, as translate's reference does,
without module-level code: a boundary that needs a module global or an import fails on every input and the status
says ``no_inputs``; give ``namespace`` (an executed module) to include them. Boundaries whose result is a list are
not perturbed (reported as not probed). The host's result type is checked at the top level only (a list's elements
are not checked one by one).
"""
from __future__ import annotations

import copy
import random
from collections import Counter

from . import values as V
from .context import Ctx
from .ir import Interpreter, IRError, StepLimit, elem_type

STEP_BUDGET = 200_000


def _has_type(v, t: str) -> bool:
    if t == "bool":
        return isinstance(v, bool)
    if t == "int":
        return type(v) is int
    if t == "float":
        return type(v) is float
    if elem_type(t) is not None:
        return isinstance(v, list)
    return True


class HostInterpreter(Interpreter):
    """The IR interpreter, with every CALL to a function of ``module["opaque"]`` made to ``host[name]``."""

    def __init__(self, module: dict, ops, host: dict, step_limit: int = STEP_BUDGET):
        super().__init__(module, ops, step_limit)
        self.boundaries = {b["name"]: b for b in module.get("opaque") or []}
        self.host = host
        self.host_calls: Counter = Counter()

    def _call(self, name, args, depth):
        b = self.boundaries.get(name)
        if b is None:
            return super()._call(name, args, depth)
        fn = self.host.get(name)
        if fn is None:
            raise IRError(f"opaque {name}: no host function (and no target can run it either)")
        self.host_calls[name] += 1
        out = fn(*copy.deepcopy(args))
        if not _has_type(out, b["returns"]):
            raise IRError(f"opaque {name} returned {type(out).__name__} where its boundary declares {b['returns']}")
        return self._note(out)


def targets(module: dict) -> dict:
    """Whether any target can run ``module``: never while it has an opaque boundary."""
    blocked = [b["name"] for b in module.get("opaque") or []]
    if not blocked:
        return {"runnable": True}
    return {"runnable": False, "why": f"calls opaque {', '.join(blocked)}: only the original Python function "
                                      "implements it, and no target has it"}


def _perturbed(fn, t: str):
    if t == "bool":
        return lambda *a: not fn(*a)
    if t == "int":
        return lambda *a: fn(*a) + 1
    if t == "float":
        return lambda *a: fn(*a) + 1.0
    return None


def _run(interp: Interpreter, entry: str, args):
    try:
        return True, interp.call(entry, list(args))
    except (StepLimit, RecursionError):
        return None, None
    except Exception as exc:  # noqa: BLE001 -- compared with the source below: both failing is agreement
        return False, exc


def witness(ctx: Ctx, module: dict, host: dict, ref, samples: int = 24, seed: int = 0) -> dict:
    """Run the partial ``module`` through ``host`` and the original ``ref`` on seeded inputs, then probe each
    boundary. Status: pass | fail | unexercised (a boundary never changed the output) | no_inputs."""
    from .frontends import sample_inputs
    entry = module["entry"]
    rows, mismatch = [], None
    calls: Counter = Counter()
    for args in sample_inputs(module, samples, seed):
        interp = HostInterpreter(module, ctx.ops, host)
        ok, got = _run(interp, entry, copy.deepcopy(args))
        if ok is None:
            continue
        try:
            out = ref(*copy.deepcopy(args))
        except Exception:  # noqa: BLE001 -- outside the source's own domain
            continue
        calls.update(interp.host_calls)
        if not ok:
            mismatch = mismatch or {"args": args, "source": out, "ir_error": str(got)}
            continue
        if not V.same(out, got):
            mismatch = mismatch or {"args": args, "source": out, "ir": got}
            continue
        rows.append({"args": args, "out": out})
    boundaries = {}
    for b in module.get("opaque") or []:
        name = b["name"]
        wrong = _perturbed(host[name], b["returns"]) if name in host else None
        exercised = None
        if wrong is not None and rows:
            interp = HostInterpreter(module, ctx.ops, {**host, name: wrong})
            exercised = False
            for r in rows:
                ok, got = _run(interp, entry, copy.deepcopy(r["args"]))
                if ok is None:
                    continue
                if not ok or not V.same(r["out"], got):
                    exercised = True
                    break
        boundaries[name] = {"id": b.get("id"), "calls": calls[name], "exercised": exercised, "cause": b.get("cause"),
                            "line": b.get("line")}
    if mismatch:
        status = "fail"
    elif not rows:
        status = "no_inputs"
    elif any(v["exercised"] is not True for v in boundaries.values()):
        status = "unexercised"
    else:
        status = "pass"
    return {"status": status, "checks": len(rows), "seed": seed, "mismatch": mismatch, "boundaries": boundaries,
            "targets": targets(module)}


def witness_lifted(ctx: Ctx, name: str, lifted: list, samples: int = 24, seed: int = 0,
                   namespace: dict | None = None) -> dict:
    """Witness the partial (or ok) function ``name`` of one file's lift (frontend_python.lift_source). Without
    ``namespace`` the original functions are executed from their own sources (module constants and functools
    first, as translate's reference does, no module-level code)."""
    from .frontend_python import module_for
    module = module_for(name, lifted, opaque=True)
    if namespace is None:
        by = {lf.name: lf for lf in lifted}
        names = [f["name"] for f in module["functions"]] + [b["name"] for b in module["opaque"]]
        src = "import math\nfrom math import gcd\n" + getattr(by[name], "preamble", "") + "\n" + \
            "\n\n".join(by[n].source for n in names)
        namespace = {"__name__": "cardmodel_opaque_witness"}
        exec(compile(src, "<opaque witness>", "exec"), namespace)  # noqa: S102 -- the user's own source, observed
    host = {b["name"]: resolve(namespace, b["host"]) for b in module["opaque"]}
    rep = witness(ctx, module, host, namespace[name], samples=samples, seed=seed)
    rep["module"] = module
    return rep


def resolve(namespace: dict, path: str):
    """``namespace`` + "C.m" -> the callable namespace["C"].m."""
    head, *rest = path.split(".")
    obj = namespace[head]
    for part in rest:
        obj = getattr(obj, part)
    return obj


def witness_project(ctx: Ctx, res, qual: str, root, samples: int = 24, seed: int = 0) -> dict:
    """Witness the partial function ``qual`` of a project lift (lift_project.ProjectLift): the original and every
    boundary are imported from the project under ``root`` (this runs the modules' top-level code, which is why it is
    only done on request)."""
    import importlib
    import sys
    module = res.module_for(qual, opaque=True)
    lf = res.functions[qual]
    sys.path.insert(0, str(root))
    try:
        def find(mod: str, path: str):
            return resolve(vars(importlib.import_module(mod)), path)
        ref = find(qual.split("::", 1)[0], lf.host)
        host = {b["name"]: find(b["module"], b["host"]) for b in module["opaque"]}
    finally:
        sys.path.remove(str(root))
    rep = witness(ctx, module, host, ref, samples=samples, seed=seed)
    rep["module"] = module
    return rep
