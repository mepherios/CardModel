"""native — call a function's compiled C form from Python through ctypes, inside its witnessed domain (Phase E3).

``improve`` finds faster Python. For loop-heavy pure functions the fastest Python is still far slower than the
same function compiled: the function card's metrics show C at nanoseconds where Python takes microseconds. This
module makes that speed usable from the Python program itself:

  1. the lifted function (and its callees) is emitted in C by codegen, with one exported entry per function;
  2. it is compiled into a shared library with the host's C compiler (``-O2 -fwrapv``), cached by source digest
     under the state directory;
  3. a Python wrapper of the same name calls the C entry when every argument lies inside the box the candidate
     was verified on (per parameter: the smallest and largest value of the comparison inputs), and the original
     Python otherwise, or when the library cannot be loaded.

The wrapper is plain function definitions (the library is loaded lazily on first call, from ``native/c/`` next
to the module first, then from the build cache), so the module keeps working on a machine without the library:
it simply stays Python. ``improve`` treats the wrapper as one more candidate: it is verified against the original
and measured, and chosen only when it is faster (a ctypes call costs about a microsecond, so only functions that
do real work win).

Honest limits (L1): C integers are 64-bit; inside the verified box a result that would exceed 64 bits wraps
(``-fwrapv``) where Python would not, which the sampled verification and the end-to-end recheck catch only when
an input reaches it. Only int, float and bool parameters and results are bridged.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from pathlib import Path

from .codegen import EmitGap, Emitter

CTYPES = {"int": "c_int64", "float": "c_double", "bool": "c_bool"}
C_TYPES = {"int": "int64_t", "float": "double", "bool": "bool"}


def compiler() -> str | None:
    for cc in (os.environ.get("CC"), "cc", "gcc", "clang"):
        if cc and shutil.which(cc):
            return shutil.which(cc)
    return None


def bridgeable(fn_ir: dict) -> bool:
    return all(p["type"] in CTYPES for p in fn_ir["params"]) and fn_ir.get("returns") in CTYPES


def c_source(ctx, module: dict, names: list[str]) -> str:
    """The module in C plus an exported, non-static entry ``cm_export_<name>`` for each name."""
    body = Emitter(ctx.store, "c", ctx.ops).module_source(module)
    fns = {f["name"]: f for f in module["functions"]}
    exports = []
    for n in names:
        f = fns[n]
        params = ", ".join(f"{C_TYPES[p['type']]} {p['name']}" for p in f["params"]) or "void"
        args = ", ".join(p["name"] for p in f["params"])
        exports.append(f"{C_TYPES[f['returns']]} cm_export_{n}({params}) {{ return {n}({args}); }}")
    return body.rstrip() + "\n\n" + "\n".join(exports) + "\n"


def build(ctx, src: str, name: str) -> tuple[Path | None, str]:
    """Compile ``src`` into a shared library (cached by digest). Returns (path, "") or (None, reason)."""
    cc = compiler()
    if cc is None:
        return None, "no C compiler on this host"
    digest = hashlib.sha256(src.encode()).hexdigest()[:16]
    out_dir = Path(ctx.state_root) / "native"
    out_dir.mkdir(parents=True, exist_ok=True)
    lib = out_dir / f"libcm_{name}_{digest}.so"
    if lib.is_file():
        return lib, ""
    c_file = out_dir / f"cm_{name}_{digest}.c"
    c_file.write_text(src, encoding="utf-8")
    tmp = lib.with_suffix(".so.tmp")
    r = subprocess.run([cc, "-O2", "-fwrapv", "-shared", "-fPIC", "-o", str(tmp), str(c_file), "-lm"],
                       capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        return None, (r.stderr or r.stdout)[-400:]
    os.replace(tmp, lib)
    return lib, ""


def domain_box(inputs: list, ptypes: list[str]) -> list[tuple] | None:
    """Per parameter, the (min, max) of the verification inputs; None when a parameter has no numeric values."""
    box = []
    for i, t in enumerate(ptypes):
        if t == "bool":
            box.append(None)
            continue
        vals = [a[i] for a in inputs if isinstance(a[i], (int, float)) and not isinstance(a[i], bool)]
        if not vals:
            return None
        box.append((min(vals), max(vals)))
    return box


def wrapper_source(fn_ir: dict, lib: Path, box: list, original_src: str, rename_fn) -> str:
    """The Python wrapper: the C entry inside ``box``, the original (renamed) outside it or without the library."""
    name = fn_ir["name"]
    params = ", ".join(f"{p['name']}: {p['type']}" for p in fn_ir["params"])
    call = ", ".join(p["name"] for p in fn_ir["params"])
    guards = []
    for p, b in zip(fn_ir["params"], box):
        if p["type"] == "bool":
            guards.append(f"isinstance({p['name']}, bool)")
        elif p["type"] == "int":
            guards.append(f"type({p['name']}) is int and {b[0]!r} <= {p['name']} <= {b[1]!r}")
        else:
            guards.append(f"isinstance({p['name']}, (int, float)) and {b[0]!r} <= {p['name']} <= {b[1]!r}")
    guard = " and ".join(guards) or "True"
    orig_name = f"{name}__original"
    orig_body = rename_fn(original_src, {}).replace(f"def {name}(", f"def {orig_name}(", 1)
    argtypes = ", ".join(f"ctypes.{CTYPES[p['type']]}" for p in fn_ir["params"])
    loader = f"_cm_native_{name}"
    return (
        f"def {name}({params}) -> {fn_ir['returns']}:\n"
        f"    fast = {loader}()\n"
        f"    if fast is not None and {guard}:\n"
        f"        return fast({call})\n"
        f"    return {orig_name}({call})\n\n\n"
        f"def {loader}():\n"
        f"    cache = {loader}.__dict__\n"
        f"    if 'fn' not in cache:\n"
        f"        cache['fn'] = None\n"
        f"        try:\n"
        f"            import ctypes\n"
        f"            import os\n"
        f"            here = os.path.dirname(globals().get('__file__') or '')\n"
        f"            for path in (os.path.join(here, 'native', 'c', {lib.name!r}), {str(lib)!r}):\n"
        f"                if os.path.isfile(path):\n"
        f"                    fn = getattr(ctypes.CDLL(path), 'cm_export_{name}')\n"
        f"                    fn.argtypes = [{argtypes}]\n"
        f"                    fn.restype = ctypes.{CTYPES[fn_ir['returns']]}\n"
        f"                    cache['fn'] = fn\n"
        f"                    break\n"
        f"        except (OSError, AttributeError):\n"
        f"            cache['fn'] = None\n"
        f"    return cache['fn']\n\n\n"
        f"{orig_body}\n")


def candidate(ctx, fn_ir: dict, module: dict, inputs: list, original_src: str, rename_fn) -> tuple[dict | None, str]:
    """An ``improve`` candidate that calls the C form inside the verified box. Returns (candidate, "") or
    (None, why not)."""
    if not bridgeable(fn_ir):
        return None, "parameters or result are not int, float or bool"
    box = domain_box(inputs, [p["type"] for p in fn_ir["params"]])
    if box is None:
        return None, "no numeric inputs to bound the domain"
    try:
        src = c_source(ctx, module, [fn_ir["name"]])
    except EmitGap as exc:
        return None, f"no C form: {exc}"
    lib, why = build(ctx, src, fn_ir["name"])
    if lib is None:
        return None, f"C build failed: {why}"
    return {"kind": "native", "card": "language/c", "form": "ctypes", "lib": str(lib), "box": box,
            "src": wrapper_source(fn_ir, lib, box, original_src, rename_fn)}, ""
