"""build — assemble a machine card into one card-IR module.

A machine card (``machine/<name>``) names an ISA (``isa``), hardware cards (``components``: ``hardware/<name>``
cards whose ``logic`` lists card-language files next to their card.json) and its own ``logic`` files. The
module is: the ISA's core library + every component's logic + the machine's logic + the generated dispatch,
with the instruction cards' stored IR linked in as already-compiled functions. ``export_state: true`` marks
every global and array exported, so a host can read and set them by name.

The result is cached under the state directory by a hash of everything that went into it.

Honest limits (L1): one ISA per machine (a two-CPU machine such as the DS composes two modules); components
are concatenated in card order and share one namespace, so two components may not define the same name (the
compiler reports it).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ..lang.compile import compile_sources
from . import isa as I


def machine_card(store, name: str):
    card = store.get(f"machine/{name}")
    if card is None:
        raise KeyError(f"no machine card machine/{name}")
    return card


def _files(card, key: str = "logic") -> list[tuple[str, str]]:
    out = []
    for rel in card.get(key) or []:
        if card.path is None:
            raise ValueError(f"{card.qualified}: logic files need a directory card")
        out.append(((card.path / rel).read_text(encoding="utf-8"), f"{card.qualified}/{rel}"))
    return out


def sources(store, name: str) -> tuple[list, dict, dict]:
    """(card-language sources, extern IR functions, the machine card) for a machine."""
    mc = machine_card(store, name)
    srcs: list[tuple[str, str]] = []
    externs: dict = {}
    isa = mc.get("isa")
    if isa:
        ic = I.isa_card(store, isa)
        srcs.append((I.library_text(ic, "core"), f"isa/{isa}/{ic.get('core')}"))
        externs = I.externs(store, isa)
        srcs.append((I.dispatch_source(store, isa), f"isa/{isa} (generated dispatch)"))
    for comp in mc.get("components") or []:
        hc = store.get(comp if "/" in comp else f"hardware/{comp}")
        if hc is None:
            raise KeyError(f"{mc.qualified}: no hardware card {comp}")
        srcs += _files(hc)
    srcs += _files(mc)
    return srcs, externs, mc


def module(ctx, name: str, use_cache: bool = True) -> dict:
    """The machine's IR module (compiled, effect-ordered, exports applied)."""
    srcs, externs, mc = sources(ctx.store, name)
    h = hashlib.sha256()
    for text, label in srcs:
        h.update(label.encode() + b"\0" + text.encode() + b"\0")
    h.update(json.dumps(externs, sort_keys=True).encode())
    h.update(json.dumps({k: mc.get(k) for k in ("export_state", "entry")}, sort_keys=True).encode())
    h.update(Path(__file__).read_bytes())                  # the builder itself (generated functions, exports)
    key = h.hexdigest()[:20]
    cache = ctx.state_root / "machine" / f"{name}-{key}.json"
    if use_cache and cache.is_file():
        return json.loads(cache.read_text(encoding="utf-8"))
    mod = compile_sources(srcs, ctx.ops, ctx.store, name=name, externs=externs)
    ir = mod.ir_module(mc.get("entry"))
    ir["functions"].append(reset_function(ir))
    if mc.get("export_state"):
        for x in (*ir.get("globals", []), *ir.get("arrays", [])):
            x["export"] = True
    ir["machine"] = name
    ir["hash"] = key
    cache.parent.mkdir(parents=True, exist_ok=True)
    tmp = cache.with_suffix(".tmp")
    tmp.write_text(json.dumps(ir, sort_keys=True), encoding="utf-8")
    tmp.replace(cache)
    return ir


RESET_ARRAY_MAX = 1 << 20


def reset_function(ir: dict) -> dict:
    """``reset_all``, generated from the module's declarations: every global back to its initial value and every
    array of at most 1 MiB back to its initial contents (the host refills the big ones: ROM, cartridge). A machine
    that is reset this way starts the same whatever ran in it before."""
    body = []
    for g in ir.get("globals") or []:
        t = g.get("type", "int")
        body.append({"k": "assign", "target": g["name"], "value": [t if t in ("int", "bool") else "int", g.get("init", 0)]})
    n = 0
    for a in ir.get("arrays") or []:
        if a["size"] > RESET_ARRAY_MAX:
            continue
        n += 1
        init = list(a.get("init") or [])
        i, stop = f"cm_ri{n}", f"cm_rs{n}"
        body.append({"k": "for_range", "var": i, "start": ["int", len(init)], "stop": ["int", a["size"]],
                     "step": ["int", 1], "counter": f"cm_rc{n}", "stop_var": stop,
                     "body": [{"k": "store", "array": a["name"], "index": ["var", i], "value": ["int", 0]}]})
        for k, v in enumerate(init):
            body.append({"k": "store", "array": a["name"], "index": ["int", k], "value": ["int", v]})
    locals_ = {}
    for k in range(1, n + 1):
        locals_.update({f"cm_ri{k}": "int", f"cm_rs{k}": "int", f"cm_rc{k}": "int"})
    return {"name": "reset_all", "params": [], "returns": "void", "locals": locals_, "body": body, "export": True}


def stats(ir: dict) -> dict:
    from ..engines.ir import walk_stmts
    return {"functions": len(ir["functions"]), "globals": len(ir.get("globals") or []),
            "arrays": len(ir.get("arrays") or []),
            "array_bytes": sum(a["size"] * (1 if a.get("elem") == "u8" else 8) for a in ir.get("arrays") or []),
            "statements": sum(1 for f in ir["functions"] for _ in walk_stmts(f["body"]))}


__all__ = ["machine_card", "module", "sources", "stats"]
