"""probes — capability probes as data (lesson from rea-cards).

A form or language is usable only if its probe passes on this host. Probes
are declared inside cards (``probe`` field), so supporting a new backend is
"add a card", not "edit the runtime". Kinds:

  always                                   always available
  never        reason                      documentation-only
  executable   name, [paths], [glob], [version_args], [version_regex], [min_version]
               glob: "~/..." patterns; the highest sorted match wins. Never
               resolves through installer proxies unless named explicitly.
  path_exists  path
  env          var, [is_dir | is_file]
  platform     system ("Darwin"/"Linux"/"Windows"), [machine]
  python_module module
  all / any    of: [probe, ...]

``probe(spec)`` returns (ok, detail) where detail is the resolved executable
path (or a reason). Results are cached per process; ``clear_cache()`` resets.
Every subprocess a probe starts has a timeout (L20 budget).

Honest limits (L1): a passing probe says the tool starts and reports a
version; it does not prove every feature works. That is what witnesses are for.
"""
from __future__ import annotations

import functools
import glob
import importlib.util
import json
import os
import platform
import re
import shutil
import subprocess

from ..kernel import resources

PROBE_TIMEOUT_S = 20


def _expand(p: str) -> str:
    return os.path.expanduser(os.path.expandvars(p))


def _version_tuple(text: str) -> tuple[int, ...] | None:
    m = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", text)
    if not m:
        return None
    return tuple(int(x) for x in m.groups() if x is not None)


@functools.lru_cache(maxsize=None)
def _run_version(exe: str, args: tuple[str, ...]) -> tuple[int, str]:
    try:
        p = resources.run([exe, *args], timeout=PROBE_TIMEOUT_S, heavy=False, stdin=subprocess.DEVNULL)
        return p.returncode, (p.stdout + p.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return -1, f"{type(exc).__name__}: {exc}"


def _find_executable(p: dict) -> str | None:
    env_override = p.get("env_override")
    if env_override and os.environ.get(env_override):
        cand = _expand(os.environ[env_override])
        if os.path.isfile(cand) and os.access(cand, os.X_OK):
            return cand
    for cand in p.get("paths", []):
        cand = _expand(cand)
        if os.path.isfile(cand) and os.access(cand, os.X_OK):
            return cand
    for pattern in p.get("glob", []):
        hits = [h for h in sorted(glob.glob(_expand(pattern))) if os.access(h, os.X_OK)]
        if hits:
            return hits[-1]
    if p.get("name") and not p.get("glob_only"):
        return shutil.which(p["name"])
    return None


def probe(spec: dict | None) -> tuple[bool, str]:
    return _cached(json.dumps(spec or {"kind": "always"}, sort_keys=True))


@functools.lru_cache(maxsize=None)
def _cached(key: str) -> tuple[bool, str]:
    return _probe(json.loads(key))


def clear_cache() -> None:
    _cached.cache_clear()
    _run_version.cache_clear()


def _probe(p: dict) -> tuple[bool, str]:
    kind = p.get("kind", "always")
    if kind == "always":
        return True, "built-in"
    if kind == "never":
        return False, p.get("reason", "documentation-only")
    if kind == "all":
        details = []
        for sub in p.get("of", []):
            ok, why = probe(sub)
            if not ok:
                return False, why
            details.append(why)
        return True, "; ".join(details)
    if kind == "any":
        fails = []
        for sub in p.get("of", []):
            ok, why = probe(sub)
            if ok:
                return True, why
            fails.append(why)
        return False, " / ".join(fails) or "no alternative"
    if kind == "executable":
        exe = _find_executable(p)
        if not exe:
            return False, f"{p.get('name') or p.get('glob')} not found"
        if p.get("version_args") is not None:
            rc, out = _run_version(exe, tuple(p["version_args"]))
            if rc != 0:
                return False, f"{exe} {' '.join(p['version_args'])} exited {rc}: {out[:120]}"
            if p.get("version_regex") and not re.search(p["version_regex"], out):
                return False, f"{exe}: version output did not match {p['version_regex']!r}"
            if p.get("min_version"):
                have = _version_tuple(out)
                need = _version_tuple(p["min_version"])
                if have is None or need is None or have < need:
                    return False, f"{exe}: version {have} < required {p['min_version']}"
        return True, exe
    if kind == "path_exists":
        path = _expand(p["path"])
        return (os.path.exists(path), path if os.path.exists(path) else f"{path} missing")
    if kind == "env":
        val = os.environ.get(p["var"])
        if not val:
            return False, f"${p['var']} not set"
        if p.get("is_dir") and not os.path.isdir(val):
            return False, f"${p['var']}={val} is not a directory"
        if p.get("is_file") and not os.path.isfile(val):
            return False, f"${p['var']}={val} is not a file"
        return True, val
    if kind == "platform":
        if p.get("system") and platform.system() != p["system"]:
            return False, f"platform is {platform.system()}, need {p['system']}"
        if p.get("machine") and platform.machine() != p["machine"]:
            return False, f"machine is {platform.machine()}, need {p['machine']}"
        return True, f"{platform.system()} {platform.machine()}"
    if kind == "python_module":
        try:
            found = importlib.util.find_spec(p["module"]) is not None
        except (ImportError, ValueError):
            found = False
        return (found, p["module"] if found else f"python module {p['module']} not installed")
    return False, f"unknown probe kind {kind!r}"


def executable(spec: dict | None) -> str | None:
    """The resolved executable of an executable probe (or the first one inside all/any)."""
    if not spec:
        return None
    if spec.get("kind") == "executable":
        ok, detail = probe(spec)
        return detail if ok else None
    for sub in spec.get("of", []):
        exe = executable(sub)
        if exe:
            return exe
    return None
