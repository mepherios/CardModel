"""native — run a machine module in an engine, behind one small API.

Engines:
  ``ir``      the reference interpreter (engines/ir.py): the semantics every other engine must match;
  a language card with an ``embed`` block:
     kind ``python`` - the emitted module runs in this process (exec); globals and arrays are names in it;
     kind ``cabi``   - the emitted module is compiled to a shared library (``embed.compile``) and loaded
                       with ctypes; int64 in and out, exported symbols carry the card's ``export_prefix``;
     kind ``process`` - the emitted module, the card's request server (``embed.serve``) and its ``transport`` run
                       in a long-lived process (``embed.run``); one JSON request line in, one answer line out.
  a platform card with an ``embed`` block hosts a language's module somewhere else (``platform/browser``: the
  JavaScript module in a web page); its embed block overrides the language's (transport, driver, run, probe).
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
import base64
import hashlib
import json
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


def host_platform(ctx, engine: str) -> dict | None:
    """A platform card with an ``embed`` block (``browser``, ``wasm``), or None."""
    card = ctx.store.get(f"platform/{engine}")
    return dict(card) if card is not None and (card.get("embed") or {}).get("language") else None


def process_parts(ctx, engine: str) -> dict | None:
    """How a process engine is made, or None for another kind of engine. An engine name is ``CODE`` or
    ``CODE@HOST``: CODE is a language card whose embed kind is ``process`` (``javascript``), a platform card that
    compiles a language's module and names the ``server`` language that serves it (``wasm``), or a hosting
    platform alone (``browser``, which means its own language); HOST is a platform card that runs the served text
    somewhere else (``browser``). Returns {"lang", "code", "host", "server"} (code and host are cards or None)."""
    code_name, _, host_name = engine.partition("@")
    host = host_platform(ctx, host_name) if host_name else None
    if host_name and host is None:
        raise EngineError(f"unknown hosting platform {host_name!r}")
    code = host_platform(ctx, code_name)
    if code is not None and ctx.store.get(f"language/{code_name}") is None:
        if code["embed"].get("server"):
            return {"lang": code["embed"]["language"], "code": code, "host": host, "server": code["embed"]["server"]}
        if host is None:                      # a hosting platform alone runs its own language's module
            return {"lang": code["embed"]["language"], "code": None, "host": code, "server": code["embed"]["language"]}
        raise EngineError(f"platform {code_name} hosts a module; it cannot be hosted by {host_name}")
    if ctx.store.get(f"language/{code_name}") is None:
        return None
    if (ctx.language(code_name).get("embed") or {}).get("kind") != "process":
        if host is not None:
            raise EngineError(f"language {code_name} has no process embed block; {host_name} cannot host it")
        return None
    return {"lang": code_name, "code": None, "host": host, "server": code_name}


def resolve_engine(ctx, engine: str) -> str:
    if engine == "ir":
        return "ir"
    parts = process_parts(ctx, engine)
    if parts is not None:
        server = ctx.language(parts["server"])
        checks = [(parts["server"], server.get("probe"))]
        if parts["code"]:
            checks.append((parts["code"]["name"], (parts["code"]["embed"].get("compiler") or {}).get("probe")))
        if parts["host"]:
            checks.append((parts["host"]["name"], parts["host"]["embed"].get("probe")))
        for name, spec in checks:
            ok, why = probes.probe(spec)
            if not ok:
                raise EngineError(f"{name} is not available here: {why}")
        return engine
    if engine in ("native", "host"):
        kind = "cabi" if engine == "native" else "python"
        for lang in embed_languages(ctx, kind):
            if ctx.available(lang)[0]:
                return lang
        raise EngineError(f"no available language card with embed kind {kind!r}")
    if ctx.store.get(f"language/{engine}") is None:
        raise EngineError(f"unknown engine {engine!r} (ir, native, host, a language card with embed, or a "
                          f"platform card with embed, optionally @ a hosting platform)")
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


def _decode(value, t: str):
    if value is None or t == "void":
        return None
    if t == "bool":
        return bool(value)
    if t == "float":
        return float(value)
    return int(value)


def _encode(value, t: str):
    if t == "bool":
        return bool(value)
    if t == "float":
        return float(value)
    return str(int(value))


class _ArrayView:
    """An array of a process machine: read whole on first use and kept until the machine runs again; a store
    goes to the process (batched) and to the copy."""

    def __init__(self, m: "ProcessMachine", name: str):
        self.m, self.name = m, name
        self.u8 = m.arrays_spec[name].get("elem", "u8") == "u8"

    def _data(self):
        d = self.m._arr_cache.get(self.name)
        if d is None:
            d = self.m._fetch_array(self.name)
            self.m._arr_cache[self.name] = d
        return d

    def __len__(self):
        return int(self.m.arrays_spec[self.name]["size"])

    def __getitem__(self, i):
        return self._data()[i]

    def __setitem__(self, i, v):
        if isinstance(i, slice):
            start = i.start or 0
            vals = list(v)
            self.m._write_values(self.name, vals, start)
            return
        self.m._write_values(self.name, [v], int(i) % len(self))

    def __iter__(self):
        return iter(self._data())


def _compile_artifact(ctx, emb: dict, code_name: str, src: str) -> bytes:
    """Compile a module's source with a code platform's ``compile`` command (cached by hash); the artifact's bytes."""
    exe = probes.executable({"kind": "executable", "name": (emb.get("compiler") or {}).get("name", "cc")})
    if not exe:
        raise EngineError(f"{code_name}: no compiler here")
    key = json.dumps([src, emb.get("compile"), emb.get("headers")], sort_keys=True)
    d = ctx.state_root / "build" / code_name / f"module-{hashlib.sha256(key.encode()).hexdigest()[:20]}"
    out = d / emb.get("artifact_file", "module.bin")
    if out.is_file():
        return out.read_bytes()
    inc = d / "include"
    inc.mkdir(parents=True, exist_ok=True)
    for name, text in (emb.get("headers") or {}).items():
        (inc / name).write_text(text, encoding="utf-8")
    srcp = d / emb.get("source_file", "module.src")
    srcp.write_text(src, encoding="utf-8")
    tmp = out.with_name(f".building-{os.getpid()}-{out.name}")
    args = [a.format(exe=exe, src=str(srcp), out=str(tmp), include=str(inc), dir=str(d)) for a in emb["compile"]]
    try:
        p = resources.run(args, cwd=d, timeout=COMPILE_TIMEOUT_S, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired as exc:
        raise EngineError(f"{code_name}: compiling the machine timed out after {COMPILE_TIMEOUT_S}s") from exc
    if p.returncode != 0:
        raise EngineError(f"{code_name}: compile failed ({p.returncode}): {(p.stderr or p.stdout)[-3000:]}")
    tmp.replace(out)
    return out.read_bytes()


def served_module(ctx, ir: dict, parts: dict) -> tuple[str, dict, object]:
    """The module as a process engine runs it: the emitted module (or, for a code platform, its compiled artifact
    inlined by the platform's ``preamble``), the server language's request server with the module's names filled
    in from the ``entry`` templates, and the transport (the hosting platform's, if any). Returns (text, embed
    block, the emitter's identifier function)."""
    emb = dict(ctx.language(parts["server"]).get("embed") or {})
    if emb.get("kind") != "process":
        raise EngineError(f"language {parts['server']} has no embed block of kind process")
    for card in (parts["code"], parts["host"]):
        if card:
            emb.update({k: v for k, v in card["embed"].items() if k not in ("language", "statement", "server")})
    em = Emitter(ctx.store, parts["lang"], ctx.ops)
    src = em.module_source(ir)
    code_text = src
    preamble = emb.get("preamble") or ""
    if parts["code"] and emb.get("compile"):
        art = _compile_artifact(ctx, emb, parts["code"]["name"], src)
        preamble = preamble.replace("@wasm_b64@", base64.b64encode(art).decode("ascii"))
        code_text = ""
    entry = emb.get("entry") or {}
    only_exported = bool(emb.get("exported_only"))

    def entries(kind: str, items: list, key_of) -> str:
        out = []
        for x in items:
            if only_exported and not x.get("export"):
                continue
            t = entry[kind]
            if isinstance(t, dict):
                t = t.get(key_of(x)) or t.get("default")
                if t is None:
                    raise EngineError(f"no {kind} entry template for {key_of(x)}")
            out.append(t.replace("@key@", x["name"]).replace("@name@", em.ident(x["name"]))
                       .replace("@size@", str(int(x.get("size", 0)))))
        return "\n".join(out)

    serve = (emb.get("serve") or "") \
        .replace("@functions@", entries("function", ir["functions"], lambda f: f["returns"])) \
        .replace("@globals@", entries("global", ir.get("globals") or [], lambda g: g.get("type", "int"))) \
        .replace("@arrays@", entries("array", ir.get("arrays") or [], lambda a: a.get("elem", "u8")))
    return code_text + preamble + serve + (emb.get("transport") or ""), emb, em.ident


class ProcessMachine(Machine):
    """A machine module running in another process: the language card's ``embed`` block (kind ``process``) gives
    the request server and how to run it; a hosting platform card (``browser``) may replace the transport, add a
    driver file and change the command. Stores and writes are batched and sent with the next request that needs
    an answer; globals are read all at once and kept until the machine runs again."""

    def __init__(self, ctx, ir: dict, engine: str, record: bool = False):
        super().__init__(ir, engine)
        parts = process_parts(ctx, engine)
        self.transcript: list | None = [] if record else None
        exe = probes.executable(ctx.language(parts["server"]).get("probe"))
        if not exe:
            raise EngineError(f"{parts['server']} is not available here")
        text, emb, self.ident = served_module(ctx, ir, parts)
        self.exported_only = bool(emb.get("exported_only"))
        self.source = text
        h = hashlib.sha256(f"{self.engine}\0{text}\0{emb.get('driver')}".encode()).hexdigest()[:20]
        d = ctx.state_root / "build" / self.engine.replace("@", "_at_") / f"machine-{h}"
        d.mkdir(parents=True, exist_ok=True)
        srcp = d / emb.get("file", "machine.src")
        srcp.write_text(text, encoding="utf-8")
        driver = ""
        if emb.get("driver"):
            dp = d / emb["driver"]["file"]
            dp.write_text(emb["driver"]["text"], encoding="utf-8")
            driver = str(dp)
        args = [a.format(exe=exe, src=str(srcp), driver=driver, dir=str(d)) for a in emb["run"]]
        self._err = tempfile.TemporaryFile()
        self.proc = subprocess.Popen(args, cwd=d, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self._err,
                                     text=True, encoding="utf-8", bufsize=1)
        self._cleanup = weakref.finalize(self, _stop_process, self.proc, self._err)
        self._pending: list = []
        self._vars: dict | None = None
        self._arr_cache: dict = {}

    # -- requests --------------------------------------------------------------
    def _rpc(self, reqs: list) -> list:
        reqs = self._pending + reqs
        self._pending = []
        if not reqs:
            return []
        if self.transcript is not None:
            self.transcript.append(reqs)
        try:
            self.proc.stdin.write(json.dumps(reqs, separators=(",", ":")) + "\n")
            self.proc.stdin.flush()
            line = self.proc.stdout.readline()
        except (BrokenPipeError, OSError):
            line = ""
        if not line:
            self._err.seek(0)
            raise EngineError(f"{self.engine}: the machine process stopped: "
                              f"{self._err.read().decode('utf-8', 'replace')[-3000:]}")
        out = json.loads(line)
        for r in out:
            if "error" in r:
                raise EngineError(f"{self.engine}: {r['error'][:3000]}")
        return [r["ok"] for r in out]

    def _flush(self) -> None:
        if self._pending:
            self._rpc([])

    def _served(self, spec: dict | None, what: str, name: str) -> dict:
        if spec is None or (self.exported_only and not spec.get("export")):
            raise EngineError(f"{name} is not an exported {what} of this machine")
        return spec

    def call(self, fn: str, *args):
        spec = self._served(self.fns.get(fn), "function", fn)
        a = [_encode(v, p["type"]) for v, p in zip(args, spec["params"])]
        self._vars = None
        self._arr_cache.clear()
        return _decode(self._rpc([{"op": "call", "name": fn, "args": a}])[-1], spec["returns"])

    def _load_vars(self) -> dict:
        if self._vars is None:
            names = [n for n, g in self.globals.items() if g.get("export") or not self.exported_only]
            vals = self._rpc([{"op": "get", "name": n} for n in names])[-len(names):] if names else []
            self._vars = {n: _decode(v, self.globals[n].get("type", "int")) for n, v in zip(names, vals)}
        return self._vars

    def get(self, name: str):
        self._served(self.globals.get(name), "global", name)
        return self._load_vars()[name]

    def set(self, name: str, value) -> None:
        t = self._served(self.globals.get(name), "global", name).get("type", "int")
        self._pending.append({"op": "set", "name": name, "value": _encode(value, t)})
        if self._vars is not None:
            self._vars[name] = _decode(_encode(value, t), t)

    def _fetch_array(self, name: str):
        v = self._rpc([{"op": "read", "name": name}])[-1]
        return bytearray(bytes.fromhex(v)) if isinstance(v, str) else [int(x) for x in v]

    def _write_values(self, name: str, vals: list, start: int) -> None:
        if self.arrays_spec[name].get("elem", "u8") == "u8":
            data = bytes(int(x) & 0xFF for x in vals)
            self._pending.append({"op": "write", "name": name, "start": start, "data": data.hex()})
        else:
            data = [int(x) for x in vals]
            self._pending.append({"op": "write", "name": name, "start": start, "data": [str(x) for x in data]})
        cached = self._arr_cache.get(name)
        if cached is not None:
            cached[start:start + len(data)] = data

    def array(self, name: str):
        self._served(self.arrays_spec.get(name), "array", name)
        return _ArrayView(self, name)

    def read(self, name: str, start: int = 0, n: int | None = None) -> bytes:
        if self.arrays_spec[name].get("elem", "u8") != "u8":
            raise TypeError(f"{name} is an Int array; index it")
        cached = self._arr_cache.get(name)
        if cached is not None:
            return bytes(cached[start:None if n is None else start + n])
        req = {"op": "read", "name": name, "start": start}
        if n is not None:
            req["n"] = n
        return bytes.fromhex(self._rpc([req])[-1])

    def write(self, name: str, data: bytes, start: int = 0) -> None:
        self._write_values(name, list(data), start)

    def close(self) -> None:
        self._cleanup()


def serve_request(m: Machine, r: dict):
    """One request of the process protocol answered by any machine (the reference, a cabi library, the host), in
    the protocol's own values: so a transcript recorded on one engine can be checked against another."""
    op, name = r["op"], r["name"]
    if op == "call":
        spec = m.fns[name]
        return _encode_answer(m.call(name, *[_decode(_value(a), p["type"]) for a, p in zip(r["args"], spec["params"])]))
    if op == "get":
        return _encode_answer(m.get(name))
    if op == "set":
        m.set(name, _decode(_value(r["value"]), m.globals[name].get("type", "int")))
        return None
    start = r.get("start") or 0
    u8 = m.arrays_spec[name].get("elem", "u8") == "u8"
    if op == "read":
        if u8:
            return m.read(name, start, r.get("n")).hex()
        a = m.array(name)
        end = len(a) if r.get("n") is None else min(len(a), start + r["n"])
        return [str(int(a[i])) for i in range(start, end)]
    if op == "write":
        if u8:
            m.write(name, bytes.fromhex(r["data"]), start)
        else:
            a = m.array(name)
            for i, v in enumerate(r["data"]):
                a[start + i] = int(v)
        return None
    raise EngineError(f"unknown request {op!r}")


def _value(v):
    return int(v) if isinstance(v, str) else v


def _encode_answer(v):
    if v is None or isinstance(v, (bool, float)):
        return v
    return str(int(v))


def replay(m: Machine, transcript: list) -> list:
    """Answer every batch of a transcript on machine ``m``: a list of answer lists."""
    if isinstance(m, ProcessMachine):
        return [m._rpc(list(batch)) for batch in transcript]
    return [[serve_request(m, r) for r in batch] for batch in transcript]


def _stop_process(proc, err=None) -> None:
    try:
        if proc.stdin:
            proc.stdin.close()
        proc.wait(timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        proc.kill()
        proc.wait()
    for f in (proc.stdout, err):
        if f is not None:
            f.close()


def load(ctx, ir: dict, engine: str = "native", fresh: bool = False, record: bool = False) -> Machine:
    """``record``: a process machine keeps every request batch it sends (``transcript``), to replay elsewhere."""
    lang = resolve_engine(ctx, engine)
    if lang == "ir":
        return IRMachine(ctx, ir)
    if process_parts(ctx, lang) is not None:
        return ProcessMachine(ctx, ir, lang, record=record)
    kind = ctx.language(lang)["embed"]["kind"]
    if kind == "python":
        return HostMachine(ctx, ir, lang)
    if kind == "cabi":
        return CABIMachine(ctx, ir, lang, fresh=fresh)
    raise EngineError(f"embed kind {kind!r} is not supported")


__all__ = ["CABIMachine", "EngineError", "HostMachine", "IRMachine", "Machine", "ProcessMachine", "build_library",
           "embed_languages", "host_platform", "load", "process_parts", "served_module", "replay", "serve_request", "resolve_engine", "sweep_copies"]
