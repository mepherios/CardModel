"""runners — execute forms for real: in-process Python, Node, and compiled targets.

Two protocols:

* ``call`` protocol (rich values: bytes, big ints, lists, dicts): a form is
  source code defining an ``entry`` function. Python forms run in-process;
  JavaScript forms run in one Node process per batch (``node:`` built-ins
  only, imported from a ``data:`` URL). Values cross the boundary as JSON
  with two tags: {"$bytes": hex} and {"$int": "decimal"} (|x| >= 2**53).
* ``program`` protocol (IR-generated programs, int/float/bool): codegen
  bakes the inputs into a program; the runner compiles it (cached by source
  hash under the store's state/build directory), runs it with a timeout and
  parses one tagged line per call: ``i:<int>`` ``f:<float>`` ``b:true|false``, or ``l:<n>`` followed by
  the n element lines of a list.

Every subprocess has a timeout; failures come back as data (status, stderr),
never as silent empties (L36/L39).

Honest limits (L1): forms run with the user's privileges (no sandbox): only
run card code you trust; the build cache is keyed by source text, so a new
seed (new baked inputs) means a new compile.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from ..kernel import resources
from . import probes

RUN_TIMEOUT_S = 60
COMPILE_TIMEOUT_S = 180


# -- value encoding (call protocol) -------------------------------------------
def encode(v):
    if isinstance(v, (bytes, bytearray, memoryview)):
        return {"$bytes": bytes(v).hex()}
    if isinstance(v, bool) or v is None or isinstance(v, str):
        return v
    if isinstance(v, int):
        return v if -(2**53) < v < 2**53 else {"$int": str(v)}
    if isinstance(v, float):
        return v
    if isinstance(v, (list, tuple)):
        return [encode(x) for x in v]
    if isinstance(v, dict):
        return {str(k): encode(x) for k, x in v.items()}
    raise TypeError(f"cannot encode {type(v).__name__}")


def decode(v):
    if isinstance(v, dict):
        if set(v) == {"$bytes"}:
            return bytes.fromhex(v["$bytes"])
        if set(v) == {"$int"}:
            return int(v["$int"])
        return {k: decode(x) for k, x in v.items()}
    if isinstance(v, list):
        return [decode(x) for x in v]
    return v


@dataclass
class CallResult:
    ok: bool
    value: object = None
    error: str = ""


def call_python(code: str, entry: str, calls: list[list], lib: dict | None = None) -> list[CallResult]:
    """Run ``entry`` from Python source on each argument list (already decoded)."""
    ns: dict = {"__name__": "cardmodel_form"}
    if lib:
        ns.update(lib)
    exec(compile(code, f"<form {entry}>", "exec"), ns)  # noqa: S102 -- trusted card code
    fn = ns.get(entry)
    if not callable(fn):
        raise RuntimeError(f"python form defines no callable {entry!r}")
    out = []
    for args in calls:
        try:
            out.append(CallResult(True, fn(*args)))
        except Exception as exc:  # noqa: BLE001 -- the error is the result being compared
            out.append(CallResult(False, None, type(exc).__name__))
    return out


NODE_HARNESS = r"""
import { readFileSync } from 'node:fs';
const req = JSON.parse(readFileSync(0, 'utf8'));
const dec = (v) => {
  if (v && typeof v === 'object' && !Array.isArray(v)) {
    const k = Object.keys(v);
    if (k.length === 1 && k[0] === '$bytes') return Uint8Array.from(Buffer.from(v.$bytes, 'hex'));
    if (k.length === 1 && k[0] === '$int') return BigInt(v.$int);
    const o = {}; for (const key of k) o[key] = dec(v[key]); return o;
  }
  if (Array.isArray(v)) return v.map(dec);
  return v;
};
const enc = (v) => {
  if (v instanceof Uint8Array) return { $bytes: Buffer.from(v).toString('hex') };
  if (typeof v === 'bigint') return (v > -(2n ** 53n) && v < 2n ** 53n) ? Number(v) : { $int: v.toString() };
  if (Array.isArray(v)) return v.map(enc);
  if (v && typeof v === 'object') { const o = {}; for (const k of Object.keys(v)) o[k] = enc(v[k]); return o; }
  return v;
};
const mod = await import('data:text/javascript;base64,' + Buffer.from(req.code).toString('base64'));
const fn = mod[req.entry];
if (typeof fn !== 'function') { process.stdout.write(JSON.stringify({ fatal: `no export ${req.entry}` })); process.exit(0); }
const results = [];
for (const args of req.calls) {
  try { results.push({ ok: true, value: enc(await fn(...dec(args))) }); }
  catch (e) { results.push({ ok: false, error: (e && e.constructor && e.constructor.name) || String(e) }); }
}
process.stdout.write(JSON.stringify({ results }));
"""


def call_node(code: str, entry: str, calls: list[list], node: str | None = None,
              timeout: float = RUN_TIMEOUT_S) -> list[CallResult]:
    node = node or probes.executable({"kind": "executable", "name": "node", "version_args": ["--version"]})
    if not node:
        raise RuntimeError("node is not available")
    req = json.dumps({"code": code, "entry": entry, "calls": [encode(list(a)) for a in calls]})
    with tempfile.TemporaryDirectory(prefix="cardmodel_node_") as d:
        h = Path(d) / "harness.mjs"
        h.write_text(NODE_HARNESS, encoding="utf-8")
        p = resources.run([node, str(h)], input=req, timeout=timeout)
    if p.returncode != 0:
        raise RuntimeError(f"node exited {p.returncode}: {p.stderr.strip()[:500]}")
    out = json.loads(p.stdout)
    if "fatal" in out:
        raise RuntimeError(out["fatal"])
    return [CallResult(r["ok"], decode(r.get("value")), r.get("error", "")) for r in out["results"]]


# -- program protocol ---------------------------------------------------------------
@dataclass
class ProgramRun:
    lang: str
    status: str                     # ok | unavailable | compile_error | runtime_error | timeout
    values: list = field(default_factory=list)
    stderr: str = ""
    compile_ms: float = 0.0
    run_ms: float = 0.0
    cached: bool = False
    detail: str = ""


def parse_line(line: str):
    """One tagged value. ``s:`` is a string written as its code points in decimal, space-separated (``s:`` alone
    is the empty string), so no target's console encoding or escaping is involved."""
    tag, _, text = line.partition(":")
    text = text.strip()
    if tag == "i":
        return int(text)
    if tag == "f":
        low = text.lower()
        if low in ("inf", "+inf", "infinity", "+infinity"):
            return math.inf
        if low in ("-inf", "-infinity"):
            return -math.inf
        if low in ("nan", "-nan", "+nan"):
            return math.nan
        return float(text)
    if tag == "b":
        return text.lower() == "true"
    if tag == "s":
        return "".join(chr(int(c)) for c in text.split())
    raise ValueError(f"untagged output line {line!r}")


def parse_values(lines: list[str]) -> list:
    """Tagged lines -> values; ``l:<n>`` collects the next n values into one list (a list-valued result)."""
    out, i = [], 0
    while i < len(lines):
        if lines[i].startswith("l:"):
            n = int(lines[i][2:].strip())
            if i + 1 + n > len(lines):
                raise ValueError(f"list of {n} values cut short")
            out.append([parse_line(x) for x in lines[i + 1:i + 1 + n]])
            i += 1 + n
            continue
        out.append(parse_line(lines[i]))
        i += 1
    return out


def _fill(args: list[str], **kw) -> list[str]:
    return [a.format(**kw) for a in args]


def build_dir(state_root: Path, lang: str, source: str) -> Path:
    h = hashlib.sha256(f"{lang}\0{source}".encode()).hexdigest()[:20]
    return state_root / "build" / lang / h


def run_program(lang_card: dict, source: str, state_root: Path, timeout: float = RUN_TIMEOUT_S,
                parse: bool = True) -> ProgramRun:
    """Compile (cached) and run a generated program; parse tagged output lines."""
    name = lang_card["name"]
    runner = lang_card.get("runner") or {}
    ok, exe = probes.probe(lang_card.get("probe"))
    if not ok:
        return ProgramRun(name, "unavailable", detail=exe)
    tools = {"exe": exe}
    for tname, tprobe in (runner.get("tools") or {}).items():
        tok, tdetail = probes.probe(tprobe)
        if not tok:
            return ProgramRun(name, "unavailable", detail=f"{tname}: {tdetail}")
        tools[tname] = tdetail
    d = build_dir(state_root, name, source)
    d.mkdir(parents=True, exist_ok=True)
    src = d / runner.get("file", "main.txt")
    binp = d / "prog"
    kw = {"dir": str(d), "src": str(src), "bin": str(binp), **tools}
    if not src.exists() or src.read_text(encoding="utf-8") != source:
        src.write_text(source, encoding="utf-8")
    env = dict(os.environ)
    env.update({k: v.format(**kw) for k, v in (runner.get("env") or {}).items()})
    res = ProgramRun(name, "ok")
    if runner.get("compile"):
        stamp = d / ".compiled"
        if stamp.exists() and (not runner.get("output") or Path(runner["output"].format(**kw)).exists()):
            res.cached = True
        else:
            t0 = time.perf_counter()
            try:
                p = resources.run(_fill(runner["compile"], **kw), cwd=d, timeout=COMPILE_TIMEOUT_S, env=env,
                                  stdin=subprocess.DEVNULL)
            except subprocess.TimeoutExpired:
                res.status, res.detail = "timeout", "compile timed out"
                return res
            res.compile_ms = (time.perf_counter() - t0) * 1000
            if p.returncode != 0:
                res.status, res.stderr = "compile_error", (p.stderr + p.stdout)[-4000:]
                return res
            stamp.write_text("ok")
    t0 = time.perf_counter()
    try:
        p = resources.run(_fill(runner["run"], **kw), cwd=d, timeout=timeout, env=env, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        res.status, res.detail = "timeout", f"run exceeded {timeout}s"
        return res
    res.run_ms = (time.perf_counter() - t0) * 1000
    res.stderr = p.stderr[-4000:]
    lines = [ln for ln in p.stdout.splitlines() if ln.strip()]
    if parse:
        try:
            res.values = parse_values([ln for ln in lines if ln[:2] in ("i:", "f:", "b:", "s:", "l:")])
        except ValueError as exc:
            res.status, res.detail = "runtime_error", str(exc)
            return res
    else:
        res.values = lines
    if p.returncode != 0:
        res.status = "runtime_error"
        res.detail = f"exit {p.returncode}"
    return res


def clean_build(state_root: Path) -> int:
    """Delete cached builds (safe: they are derived artifacts). Returns bytes freed."""
    d = state_root / "build"
    if not d.exists():
        return 0
    size = sum(f.stat().st_size for f in d.rglob("*") if f.is_file())
    shutil.rmtree(d)
    return size
