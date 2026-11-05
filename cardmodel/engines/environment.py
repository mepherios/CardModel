"""environment — the machine the model runs on, as a card (docs/ENVIRONMENTS.md V-A: E20, E21, E6; D15, D17).

An *environment card* holds what the model knows about one machine: the operating system, the ISA and its
extensions, cores and SMT, memory, the cache levels the system declares, and the cache levels and copy bandwidth
the model measured itself. Every value is a *capability* in D17's sense: a value with the tier of its evidence,
``measured`` (a probe ran here), ``declared`` (the OS said so) or ``unknown``. Declared is not measured: on the
cloud host of 11-04 ``lscpu`` declares a 260 MiB L3 that the pointer chase never sees (ENVIRONMENTS.md §4).

The generator's own card (the environment the model runs in, D15's G) is written by ``cardmodel env`` into the
local layer (``state/local/cards/environment/``, untracked: it describes this machine only). Its name is
``env_<fingerprint>``. The fingerprint is a hash of the declared identity only (OS and release, ISA and
extensions, CPU model, cores, RAM, declared caches, Python), never of timings, so re-measuring the same machine
keeps the name and an OS, CPU or toolchain change gives a new card (a driver update invalidates exactly what cites
the old one, E22).

Probes (E20). ``static()`` reads ``/proc/cpuinfo`` and ``/sys`` on Linux, ``sysctl`` on macOS: milliseconds, no
compiler. ``measure()`` compiles one small C program with the host's ``cc`` and runs it under the resource
governor: a pointer chase over a random cyclic permutation (one dependent load per step, so the time per step is
the latency of the level the working set fits in) at working sets from 4 KiB to 64 MiB, and a streaming copy.
The levels are read off the chase as plateaus: a size whose latency is ``STEP`` times the fastest load of the
current level or more starts the next level.

Honest limits (L1): with no C compiler the measured rows are ``unknown`` with the reason; a hypervisor or a busy
machine adds noise to every timing (the chase reports the median of three passes); the step detection finds the
working-set sizes where latency rises, which are cache boundaries only up to the associativity and the TLB, so the
levels are ``measured`` steps, not declared cache sizes; the copy bandwidth is one thread's.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

CATEGORY = "environment"
STEP = 2.0                       # latency at or above STEP x the current level's fastest load starts a new level
MAX_AGE_DAYS = 30                # the generator's card is re-measured when its measurement is older than this

PROBE_C = r"""
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

static double now(void) { struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t); return t.tv_sec + t.tv_nsec * 1e-9; }
static uint64_t rng = 88172645463325252ull;
static uint64_t next(void) { rng ^= rng << 13; rng ^= rng >> 7; rng ^= rng << 17; return rng; }
static int cmp(const void *a, const void *b) { double x = *(const double *)a, y = *(const double *)b; return (x > y) - (x < y); }

int main(int argc, char **argv) {
    size_t max_bytes = argc > 1 ? strtoull(argv[1], 0, 10) : (64u << 20);
    void **buf = malloc(max_bytes);
    if (!buf) return 1;
    for (size_t bytes = 4096; bytes <= max_bytes; bytes *= 2) {
        size_t n = bytes / sizeof(void *), i;
        for (i = 0; i < n; i++) buf[i] = &buf[i];
        for (i = n - 1; i > 0; i--) {            /* Sattolo: one cycle through every slot */
            size_t j = next() % i; void *t = buf[i]; buf[i] = buf[j]; buf[j] = t;
        }
        size_t steps = 1u << 20;
        double runs[3];
        void **p = (void **)buf[0];
        for (i = 0; i < n; i++) p = (void **)*p;  /* warm */
        for (int r = 0; r < 3; r++) {
            double t0 = now();
            for (i = 0; i < steps; i++) p = (void **)*p;
            runs[r] = (now() - t0) * 1e9 / steps;
        }
        qsort(runs, 3, sizeof(double), cmp);
        printf("chase %zu %.3f %p\n", bytes, runs[1], (void *)p);
        fflush(stdout);
    }
    free(buf);
    size_t cb = 64u << 20;
    char *a = malloc(cb), *b = malloc(cb);
    if (!a || !b) return 1;
    memset(a, 1, cb); memset(b, 2, cb);
    double best = 1e30;
    for (int r = 0; r < 5; r++) {
        double t0 = now(); memcpy(b, a, cb); double t = now() - t0;
        if (t < best) best = t;
        a[r] = b[cb - 1 - r];
    }
    printf("copy %zu %.3f\n", cb, 2.0 * cb / best / 1e9);
    free(a); free(b);
    return 0;
}
"""


def _read(path: str) -> str | None:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _sysctl(*names: str) -> dict[str, str]:
    exe = shutil.which("sysctl") or ("/usr/sbin/sysctl" if os.path.exists("/usr/sbin/sysctl") else None)
    if not exe:
        return {}
    out = {}
    for n in names:
        try:
            r = subprocess.run([exe, "-n", n], capture_output=True, text=True, timeout=5)
        except (OSError, subprocess.SubprocessError):
            continue
        if r.returncode == 0 and r.stdout.strip():
            out[n] = r.stdout.strip()
    return out


def _sysctl_prefix(prefix: str) -> dict[str, str]:
    exe = shutil.which("sysctl") or ("/usr/sbin/sysctl" if os.path.exists("/usr/sbin/sysctl") else None)
    if not exe:
        return {}
    try:
        r = subprocess.run([exe, prefix], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return {}
    out = {}
    for line in r.stdout.splitlines():
        k, _, v = line.partition(":")
        if v:
            out[k.strip()] = v.strip()
    return out


def _size(text: str) -> int | None:
    m = re.fullmatch(r"\s*(\d+)\s*([KMG]?)B?\s*", text or "", re.I)
    if not m:
        return None
    return int(m.group(1)) * {"": 1, "K": 1 << 10, "M": 1 << 20, "G": 1 << 30}[m.group(2).upper()]


def _linux() -> dict:
    info = _read("/proc/cpuinfo") or ""
    model, flags, cores = None, [], set()
    phys = core = None
    for line in info.splitlines():
        k, _, v = line.partition(":")
        k, v = k.strip(), v.strip()
        if k in ("model name", "Model", "cpu model") and not model:
            model = v
        elif k in ("flags", "Features") and not flags:
            flags = v.split()
        elif k == "physical id":
            phys = v
        elif k == "core id":
            core = v
        elif not k and phys is not None and core is not None:
            cores.add((phys, core))
            phys = core = None
    if phys is not None and core is not None:
        cores.add((phys, core))
    caches = []
    base = Path("/sys/devices/system/cpu/cpu0/cache")
    for d in sorted(base.glob("index*")) if base.is_dir() else []:
        level, kind, size = (_read(str(d / f)) for f in ("level", "type", "size"))
        b = _size(size or "")
        if level and b:
            caches.append({"level": int(level), "type": (kind or "").strip().lower(), "bytes": b})
    return {"cpu_model": model, "extensions": flags, "physical": len(cores) or None, "caches": caches}


def _darwin() -> dict:
    s = _sysctl("machdep.cpu.brand_string", "hw.physicalcpu", "hw.logicalcpu", "machdep.cpu.features",
                "machdep.cpu.leaf7_features", "hw.l1dcachesize", "hw.l1icachesize", "hw.l2cachesize",
                "hw.l3cachesize", "hw.perflevel0.l1dcachesize", "hw.perflevel0.l2cachesize")
    flags = sorted({f.lower() for k in ("machdep.cpu.features", "machdep.cpu.leaf7_features")
                    for f in s.get(k, "").split()})
    if not flags:                                    # Apple Silicon: the features are hw.optional.* = 1
        flags = sorted(k.rsplit(".", 1)[-1].lower() for k, v in _sysctl_prefix("hw.optional").items()
                       if v == "1")
    caches = []
    for level, kind, keys in ((1, "data", ("hw.perflevel0.l1dcachesize", "hw.l1dcachesize")),
                              (1, "instruction", ("hw.l1icachesize",)),
                              (2, "unified", ("hw.perflevel0.l2cachesize", "hw.l2cachesize")),
                              (3, "unified", ("hw.l3cachesize",))):
        v = next((s[k] for k in keys if s.get(k, "0").isdigit() and int(s[k]) > 0), None)
        if v:
            caches.append({"level": level, "type": kind, "bytes": int(v)})
    phys = s.get("hw.physicalcpu")
    return {"cpu_model": s.get("machdep.cpu.brand_string"), "extensions": flags,
            "physical": int(phys) if phys and phys.isdigit() else None, "caches": caches}


def static() -> dict:
    """The declared identity of this machine, from the OS (no compiler, no timing)."""
    from ..kernel import resources
    d = _darwin() if sys.platform == "darwin" else _linux() if sys.platform.startswith("linux") else \
        {"cpu_model": None, "extensions": [], "physical": None, "caches": []}
    logical = os.cpu_count() or 1
    physical = d["physical"] or None
    return {
        "os": {"system": platform.system(), "release": platform.release()},
        "isa": {"machine": platform.machine(), "extensions": sorted(set(d["extensions"]))},
        "cpu": {"model": d["cpu_model"] or platform.processor() or platform.machine(), "logical": logical,
                "physical": physical, "smt": (logical // physical) if physical else None},
        "memory": {"ram_mb": resources.total_ram_mb()},
        "caches": sorted(d["caches"], key=lambda c: (c["level"], c["type"])),
        "python": sys.version.split()[0],
    }


_NAME: str | None = None


def card_name() -> str:
    """``env_<fingerprint>`` of this machine (computed once per process; no probing)."""
    global _NAME
    if _NAME is None:
        _NAME = f"env_{fingerprint(static())}"
    return _NAME


def fingerprint(identity: dict) -> str:
    """Hash of the declared identity (``static()``), 16 hex digits: equal machines get equal names."""
    return hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:16]


def levels_from_curve(curve: list[tuple[int, float]], step: float = STEP) -> list[dict]:
    """The plateaus of the chase: each level is the run of sizes whose latency stays below ``step`` times that
    level's fastest load, reported by its largest size and that fastest load. ``curve`` is [(bytes, ns per load)]
    by increasing size. The last plateau (memory) has no upper bound."""
    out = []
    lo = 0
    for i in range(1, len(curve)):
        floor = min(ns for _, ns in curve[lo:i])
        if floor > 0 and curve[i][1] >= step * floor:
            out.append({"up_to_bytes": curve[i - 1][0], "ns": round(floor, 2)})
            lo = i
    seg = curve[lo:]
    if seg:
        out.append({"up_to_bytes": None, "ns": round(seg[-1][1], 2)})
    return out


def compiler() -> str | None:
    for c in (os.environ.get("CC"), "cc", "clang", "gcc"):
        if c and shutil.which(c):
            return shutil.which(c)
    return None


def measure(max_bytes: int = 64 << 20, timeout: float = 120.0) -> dict:
    """Compile and run the C probe. Returns {"chase": [(bytes, ns)], "copy_gb_s": x} or {"unknown": reason}."""
    from ..kernel import resources
    cc = compiler()
    if not cc:
        return {"unknown": "no C compiler (cc, clang, gcc) on PATH"}
    with tempfile.TemporaryDirectory(prefix="cardmodel_env_") as d:
        src, exe = Path(d) / "probe.c", Path(d) / "probe"
        src.write_text(PROBE_C, encoding="utf-8")
        r = resources.run([cc, "-O2", "-o", str(exe), str(src)], capture_output=True, text=True, timeout=timeout)
        if r.returncode != 0:
            return {"unknown": f"the probe did not compile with {cc}: {r.stderr.strip()[:300]}"}
        r = resources.run([str(exe), str(max_bytes)], capture_output=True, text=True, timeout=timeout,
                          mem_cap_mb=max(256, (3 * max_bytes) >> 20))
        if r.returncode != 0:
            return {"unknown": f"the probe exited {r.returncode}: {r.stderr.strip()[:300]}"}
    chase, copy = [], None
    for line in r.stdout.splitlines():
        parts = line.split()
        if parts[:1] == ["chase"] and len(parts) >= 3:
            chase.append((int(parts[1]), float(parts[2])))
        elif parts[:1] == ["copy"] and len(parts) >= 3:
            copy = float(parts[2])
    if not chase:
        return {"unknown": "the probe printed no chase rows"}
    return {"chase": chase, "copy_gb_s": copy, "compiler": cc}


def _cap(value, evidence: str, **extra) -> dict:
    return {"value": value, "evidence": evidence, **extra}


def build_card(identity: dict | None = None, measured: dict | None = None, role: str = "generator",
               today: str | None = None) -> dict:
    """The environment card for ``identity`` (default: this machine) with the probe results ``measured``."""
    ident = identity if identity is not None else static()
    fp = fingerprint(ident)
    cpu, mem = ident["cpu"], ident["memory"]
    caps = {
        "cores_logical": _cap(cpu["logical"], "declared"),
        "cores_physical": _cap(cpu["physical"], "declared" if cpu["physical"] else "unknown"),
        "smt": _cap(cpu["smt"], "declared" if cpu["smt"] else "unknown"),
        "ram_mb": _cap(mem["ram_mb"], "declared"),
    }
    for c in ident["caches"]:
        if c["type"] in ("data", "unified"):
            caps.setdefault(f"l{c['level']}{'d' if c['level'] == 1 else ''}_bytes", _cap(c["bytes"], "declared"))
    probes: dict = {}
    m = measured or {}
    if m.get("chase"):
        levels = levels_from_curve(m["chase"])
        probes["chase"] = {"ns_per_load": [[b, round(ns, 3)] for b, ns in m["chase"]], "levels": levels,
                           "step_ratio": STEP}
        caps["latency_first_level_ns"] = _cap(levels[0]["ns"], "measured", probe="chase")
        caps["latency_memory_ns"] = _cap(levels[-1]["ns"], "measured", probe="chase")
        for i, lv in enumerate(levels[:-1], 1):
            caps[f"measured_level{i}_bytes"] = _cap(lv["up_to_bytes"], "measured", probe="chase")
    else:
        reason = m.get("unknown", "not measured (run `cardmodel env --measure`)")
        caps["latency_first_level_ns"] = _cap(None, "unknown", reason=reason)
        caps["latency_memory_ns"] = _cap(None, "unknown", reason=reason)
    if m.get("copy_gb_s"):
        probes["copy"] = {"bytes": 64 << 20, "gb_s": round(m["copy_gb_s"], 2), "threads": 1}
        caps["copy_gb_s"] = _cap(round(m["copy_gb_s"], 2), "measured", probe="copy")
    else:
        caps["copy_gb_s"] = _cap(None, "unknown", reason=m.get("unknown", "not measured"))
    from .optimize import host_id
    card = {
        "name": f"env_{fp}",
        "category": CATEGORY,
        "role": role,
        "fingerprint": fp,
        "host_id": host_id(),
        "identity": ident,
        "capabilities": caps,
        "probes": probes,
        "measured_at": today or datetime.date.today().isoformat() if m.get("chase") else None,
        "statement": (f"The {role} environment {ident['os']['system']} {ident['isa']['machine']} "
                      f"({cpu['model']}): its declared identity and the capabilities measured on it."),
        "tier": 1 if m.get("chase") else 2,
        "provenance": {"origin": "cardmodel env", "read_for": "docs/ENVIRONMENTS.md V-A (E20, E21, E6)"},
    }
    if m.get("compiler"):
        card["probes"]["compiler"] = m["compiler"]
    return card


def _stale(card, today: datetime.date) -> bool:
    when = card.get("measured_at")
    if not when:
        return True
    try:
        return (today - datetime.date.fromisoformat(when)).days > MAX_AGE_DAYS
    except ValueError:
        return True


def generator(store, refresh: bool = False, measure_fn=measure) -> tuple[dict, bool]:
    """The generator's card for this machine: read from the store, or probed and saved into the local layer when
    it is missing, stale (older than MAX_AGE_DAYS) or ``refresh``. Returns (card, written)."""
    ident = static()
    name = f"env_{fingerprint(ident)}"
    have = store.get(f"{CATEGORY}/{name}")
    if have is not None and not refresh and not _stale(have, datetime.date.today()):
        return dict(have), False
    card = build_card(ident, measure_fn())
    store.ensure_registry(CATEGORY, "local", description="Environment cards measured on this machine "
                          "(docs/ENVIRONMENTS.md D15, E21); untracked.")
    store.save(card, layer="local")
    return card, True


def cached(store=None) -> dict | None:
    """The generator's card for this machine if one was written (no probing). Without a store, read straight from
    the local layer's file, which is what ``kernel/resources`` does so that it never opens the store."""
    if store is not None:
        c = store.get(f"{CATEGORY}/{card_name()}")
        return dict(c) if c is not None else None
    from ..kernel import paths
    f = paths.local_cards() / CATEGORY / card_name() / "card.json"
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def render(card: dict) -> str:
    ident, caps = card["identity"], card["capabilities"]
    lines = [f"{card['name']}  ({card['role']}, measured {card.get('measured_at') or 'never'})",
             f"  {ident['os']['system']} {ident['os']['release']}  {ident['isa']['machine']}  {ident['cpu']['model']}",
             f"  {len(ident['isa']['extensions'])} ISA extensions; python {ident['python']}"]
    for k in sorted(caps):
        c = caps[k]
        v = c["value"]
        if isinstance(v, int) and k.endswith("_bytes"):
            v = f"{v >> 10} KiB" if v < (1 << 20) else f"{v >> 20} MiB"
        lines.append(f"  {k:<26} {str(v):<12} {c['evidence']}" + (f"  ({c['reason']})" if c.get("reason") else ""))
    if card.get("name") == card_name():
        from ..kernel import resources
        b = resources.budgets(refresh=True)
        lines.append("  budgets: " + ", ".join(f"{k} {b[k]}" for k in ("cpu_workers", "compile_slots", "child_mb",
                                                                        "self_mb")) + f"  (from {b['source']})")
    ch = card.get("probes", {}).get("chase")
    if ch:
        lines.append("  chase (ns per dependent load): " + ", ".join(
            f"{b >> 10 if b < (1 << 20) else b >> 20}{'K' if b < (1 << 20) else 'M'} {ns:g}"
            for b, ns in ch["ns_per_load"]))
    return "\n".join(lines)
