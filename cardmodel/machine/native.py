"""native — run a machine module in an engine, behind one small API.

Engines:
  ``ir``      the reference interpreter (engines/ir.py): the semantics every other engine must match;
  a language card with an ``embed`` block:
     kind ``python`` - the emitted module runs in this process (exec); globals and arrays are names in it;
     kind ``cabi``   - the emitted module is compiled to a shared library (``embed.compile``) and loaded
                       with ctypes; int64 in and out, exported symbols carry the card's ``export_prefix``.
  ``native`` = the first available language whose embed kind is ``cabi``; ``host`` = the first whose kind
  is ``python``. No language is named here: all of it is card data.

``Machine``: ``call(fn, *ints)``, ``get(name)`` / ``set(name, v)`` for globals, ``array(name)`` (indexable,
sliceable; a ctypes array, a bytearray or a list), ``read(name)`` -> bytes, ``write(name, data, start)``.

Shared libraries are cached by source hash under the state directory; ``fresh=True`` loads a private copy so
two machines in one process never share state. The copy is removed when its machine is closed or collected, or
when the process exits; a process killed before that leaves its copies behind, named with its process id
(``cardmodel_machine-<pid>-...``), and the next process that makes a fresh machine removes them. Copies made
before they were named so (``cardmodel_machine_...``) are never touched: mkdtemp's names hold no "-".

Honest limits (L1): a ``cabi`` machine runs with the user's privileges like any compiled code, and an index
out of range is undefined behaviour there (machine code masks every index; the reference interpreter checks).
"""
from __future__ import annotations

import ctypes
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import weakref
from pathlib import Path

from ..engines import probes
from ..engines.codegen import Emitter
from ..engines.ir import Interpreter
from ..kernel import resources

COMPILE_TIMEOUT_S = 900


class EngineError(RuntimeError):
    pass


def embed_languages(ctx, kind: str | None = None) -> list[str]:
    out = []
    for card in ctx.store.cards("language"):
        emb = ctx.language(card.name).get("embed")
        if emb and (kind is None or emb.get("kind") == kind):
            out.append(card.name)
    return sorted(out, key=lambda n: (ctx.store.get(f"language/{n}").get("tier", 1), n))


def resolve_engine(ctx, engine: str) -> str:
    if engine == "ir":
        return "ir"
    if engine in ("native", "host"):
        kind = "cabi" if engine == "native" else "python"
        for lang in embed_languages(ctx, kind):
            if ctx.available(lang)[0]:
                return lang
        raise EngineError(f"no available language card with embed kind {kind!r}")
    if ctx.store.get(f"language/{engine}") is None:
        raise EngineError(f"unknown engine {engine!r} (ir, native, host, or a language card with embed)")
    if not ctx.language(engine).get("embed"):
        raise EngineError(f"language {engine} has no embed block")
    return engine


class Machine:
    def __init__(self, ir: dict, engine: str):
        self.ir = ir
        self.engine = engine
        self.globals = {g["name"]: g for g in ir.get("globals") or []}
        self.arrays_spec = {a["name"]: a for a in ir.get("arrays") or []}
        self.fns = {f["name"]: f for f in ir["functions"]}

    def read(self, name: str, start: int = 0, n: int | None = None) -> bytes:
        a = self.array(name)
        end = len(a) if n is None else start + n
        if self.arrays_spec[name].get("elem", "u8") == "u8":
            return bytes(memoryview(a).cast("B")[start:end]) if not isinstance(a, list) else bytes(a[start:end])
        raise TypeError(f"{name} is an Int array; index it")

    def write(self, name: str, data: bytes, start: int = 0) -> None:
        a = self.array(name)
        if isinstance(a, list):
            a[start:start + len(data)] = list(data)
        else:
            memoryview(a).cast("B")[start:start + len(data)] = data


class IRMachine(Machine):
    def __init__(self, ctx, ir: dict, step_limit: int = 10**12):
        super().__init__(ir, "ir")
        self.interp = Interpreter(ir, ctx.ops, step_limit=step_limit)

    def call(self, fn: str, *args):
        return self.interp.call(fn, list(args))

    def get(self, name: str):
        return self.interp.globals[name]

    def set(self, name: str, value) -> None:
        self.interp.globals[name] = value

    def array(self, name: str):
        return self.interp.arrays[name]


class HostMachine(Machine):
    def __init__(self, ctx, ir: dict, lang: str):
        super().__init__(ir, lang)
        em = Emitter(ctx.store, lang, ctx.ops)
        src = em.module_source(ir)
        self.source = src
        self.ident = em.ident
        self.ns: dict = {"__name__": f"cardmodel_machine_{ir.get('machine', 'm')}"}
        exec(compile(src, f"<machine {ir.get('machine')} {lang}>", "exec"), self.ns)  # noqa: S102 -- card code

    def call(self, fn: str, *args):
        return self.ns[self.ident(fn)](*args)

    def get(self, name: str):
        return self.ns[self.ident(name)]

    def set(self, name: str, value) -> None:
        self.ns[self.ident(name)] = value

    def array(self, name: str):
        return self.ns[self.ident(name)]


def _lib_suffix() -> str:
    return ".dylib" if sys.platform == "darwin" else ".so"


def build_library(ctx, ir: dict, lang: str, flags: list[str] | None = None,
                  env: dict | None = None) -> tuple[Path, str]:
    """Emit + compile (cached by source hash). Returns (library path, source). ``flags`` go right after the
    compiler (a platform card's target and SDK, for another operating system), ``env`` is the compiler's."""
    em = Emitter(ctx.store, lang, ctx.ops)
    src = em.module_source(ir)
    card = ctx.language(lang)
    emb = card["embed"]
    ok, exe = probes.probe(card.get("probe"))
    if not ok:
        raise EngineError(f"{lang} is not available here: {exe}")
    key = f"{lang}\0{src}\0{emb.get('compile')}" + (f"\0{flags}" if flags else "")
    h = hashlib.sha256(key.encode()).hexdigest()[:20]
    d = ctx.state_root / "build" / lang / f"machine-{h}"
    lib = d / f"machine{_lib_suffix()}"
    if lib.is_file():
        return lib, src
    d.mkdir(parents=True, exist_ok=True)
    srcp = d / emb.get("file", "machine.src")
    srcp.write_text(src, encoding="utf-8")
    tmp_lib = d / f".building-{os.getpid()}{_lib_suffix()}"
    args = [a.format(exe=exe, src=str(srcp), lib=str(tmp_lib), dir=str(d)) for a in emb["compile"]]
    if flags:
        args = args[:1] + list(flags) + args[1:]
    try:
        p = resources.run(args, cwd=d, timeout=COMPILE_TIMEOUT_S, stdin=subprocess.DEVNULL, env=env)
    except subprocess.TimeoutExpired as exc:
        raise EngineError(f"{lang}: compiling the machine timed out after {COMPILE_TIMEOUT_S}s") from exc
    if p.returncode != 0:
        raise EngineError(f"{lang}: compile failed ({p.returncode}): {(p.stderr or p.stdout)[-3000:]}")
    tmp_lib.replace(lib)
    return lib, src


COPY_PREFIX = "cardmodel_machine-"
_swept = False


def sweep_copies(tmp: Path | None = None) -> int:
    """Remove the private library copies of processes that no longer run (a fresh machine's process killed before
    it could clean up): folders named COPY_PREFIX<pid>-... whose pid is gone. Returns how many went."""
    gone = 0
    try:
        entries = list(Path(tmp or tempfile.gettempdir()).iterdir())
    except OSError:
        return 0
    for d in entries:
        if not d.name.startswith(COPY_PREFIX):
            continue
        pid, sep, _ = d.name[len(COPY_PREFIX):].partition("-")
        if not sep or not pid.isdigit() or int(pid) == os.getpid():
            continue
        try:
            os.kill(int(pid), 0)
        except ProcessLookupError:
            shutil.rmtree(d, ignore_errors=True)
            gone += 1
        except OSError:
            pass                                    # alive (another user's process): not ours to judge
    return gone


class CABIMachine(Machine):
    def __init__(self, ctx, ir: dict, lang: str, fresh: bool = False, lib_path: Path | None = None):
        super().__init__(ir, lang)
        em = Emitter(ctx.store, lang, ctx.ops)
        em.state(ir)
        self.ident = em.ident
        self.lib_path, self.source = (lib_path, None) if lib_path else build_library(ctx, ir, lang)
        path = self.lib_path
        self._tmpdir = None
        self._cleanup = None
        if fresh:
            global _swept
            if not _swept:
                _swept = True
                sweep_copies()
            self._tmpdir = tempfile.mkdtemp(prefix=f"{COPY_PREFIX}{os.getpid()}-")
            # the copy goes with this machine (closed, collected, or the process exiting); the loaded library stays
            # mapped, so removing its file never disturbs the machine
            self._cleanup = weakref.finalize(self, shutil.rmtree, self._tmpdir, True)
            path = Path(self._tmpdir) / self.lib_path.name
            shutil.copy(self.lib_path, path)
        self.lib = ctypes.CDLL(str(path))
        self._fn: dict = {}
        self._var: dict = {}
        self._arr: dict = {}

    def _function(self, name: str):
        f = self._fn.get(name)
        if f is None:
            spec = self.fns.get(name)
            if spec is None or not spec.get("export"):
                raise EngineError(f"{name} is not an exported function of this machine")
            f = getattr(self.lib, self.ident(name))
            f.restype = None if spec["returns"] == "void" else (ctypes.c_bool if spec["returns"] == "bool"
                                                                  else ctypes.c_int64)
            f.argtypes = [ctypes.c_bool if p["type"] == "bool" else ctypes.c_int64 for p in spec["params"]]
            self._fn[name] = f
        return f

    def call(self, fn: str, *args):
        return self._function(fn)(*args)

    def _variable(self, name: str):
        v = self._var.get(name)
        if v is None:
            g = self.globals.get(name)
            if g is None or not g.get("export"):
                raise EngineError(f"{name} is not an exported global of this machine")
            t = ctypes.c_bool if g.get("type") == "bool" else ctypes.c_int64
            v = t.in_dll(self.lib, self.ident(name))
            self._var[name] = v
        return v

    def get(self, name: str):
        return self._variable(name).value

    def set(self, name: str, value) -> None:
        self._variable(name).value = value

    def array(self, name: str):
        a = self._arr.get(name)
        if a is None:
            spec = self.arrays_spec.get(name)
            if spec is None or not spec.get("export"):
                raise EngineError(f"{name} is not an exported array of this machine")
            t = (ctypes.c_uint8 if spec.get("elem", "u8") == "u8" else ctypes.c_int64) * int(spec["size"])
            a = t.in_dll(self.lib, self.ident(name))
            self._arr[name] = a
        return a

    def close(self) -> None:
        if self._cleanup is not None:
            self._cleanup()


def load(ctx, ir: dict, engine: str = "native", fresh: bool = False) -> Machine:
    lang = resolve_engine(ctx, engine)
    if lang == "ir":
        return IRMachine(ctx, ir)
    kind = ctx.language(lang)["embed"]["kind"]
    if kind == "python":
        return HostMachine(ctx, ir, lang)
    if kind == "cabi":
        return CABIMachine(ctx, ir, lang, fresh=fresh)
    raise EngineError(f"embed kind {kind!r} is not supported")


__all__ = ["CABIMachine", "EngineError", "HostMachine", "IRMachine", "Machine", "build_library", "embed_languages",
           "load", "resolve_engine", "sweep_copies"]
