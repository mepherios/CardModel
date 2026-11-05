"""numeric — the numeric model of a runner, and when two environments agree bit for bit (ENVIRONMENTS.md V-B).

A runner (a language, its compiler and flags, on a device) evaluates binary64 as a *model* of the reference M
(FOUNDATIONS D1: ``float`` is IEEE binary64, every op correctly rounded, in the order the IR writes). Three
components of that model change float results without any change of the program (E12, E13, E14):

  fp_contract      ``a·b ± c`` computed with one rounding (a fused multiply-add) instead of two. Allowed by the
                   flags (``-ffp-contract=fast`` or ``on``, ``-ffast-math``; gcc's GNU modes; clang's default) and
                   *effective* only when the target ISA has an FMA instruction (x86-64's baseline has none, so gcc
                   needs ``-march`` with FMA; ARM64's baseline has one).
  denormal_flush   a subnormal result (FTZ) or operand (DAZ), 0 < |x| < 2⁻¹⁰²², taken as 0. ``-ffast-math`` links
                   start-up code that sets FTZ and DAZ for the whole process on x86-64 (gcc and clang).
  reduction_order  a sum written as a sequential fold computed in another tree (interleaved partial sums of a
                   vectorized loop). Allowed by ``-fassociative-math`` (part of ``-ffast-math``); done when the
                   vectorizer runs (gcc -O3, or -O2 when its cheap cost model accepts the loop).

The *declared* model reads the runner's compile flags against its language card's ``numeric`` block (data: the
compiler's defaults and what each flag permits). The *measured* model compiles a probe with exactly the runner's
compile line and runs it on this host: an FMA-sensitive expression (x·x − 1 at x = 1 + 2⁻²⁷), a multiply with a
subnormal result and one with a subnormal operand, and a sequential sum of 4,096 mixed-magnitude values, each
compared bit for bit with M's answer computed here in Python. Inputs come in on stdin as hex floats, so the
compiler cannot fold them. A component's value is the declared permission or the observed effect, whichever is
stronger, with its evidence (D17): ``measured`` when the probe saw it (or saw strict IEEE where the flags forbid
it), ``declared`` when only the flags say so.

The laws (``LAWS``) state, for each component, when two environments must agree bit for bit and the bound they
agree within otherwise; ``agreement`` applies them to two models and a term, and ``check`` tests them on the
probes. Bit-for-bit agreement needs: both models strict on the three components and otherwise strict IEEE (no
finite-math or reciprocal approximations), and a term built from correctly rounded ops only (IEEE 754 §5.4: +, −,
×, ÷, √, conversions, comparisons; not the libm functions, whose last bit differs between libraries).

The Gödel view (FOUNDATIONS D13, ENVIRONMENTS D16): a numeric model is a translation target, and ``carry_map``
is its carry map, the identity on every op atom whose result the model reproduces bit for bit. ``gap`` is
``godel.carry``'s residual over the term's content: the atoms (libm functions, and the atoms a non-strict
component changes) that keep a term from being carried exactly. It names *where* a term may differ; whether two
runners agree is never read from content: the comparison runs the term (values come from M and the runners).

Honest limits (L1): the probe is C (the language whose flags change the model on this host); other languages'
rows are declared from their card. The measured row says what the probe's loops did, not what every loop does:
a declared permission therefore stays in the model even when the probe did not show it. The bounds are the
standard first-order error analyses (Higham, *Accuracy and Stability of Numerical Algorithms*, 2002, §2.2 and
§4.2) for one op or one sum; a bound is per contracted op or per flushed value, and is not propagated through the
rest of a term (a flushed divisor can still turn a finite quotient into ∞).
"""
from __future__ import annotations

import copy
import functools
import math
import platform
import random
import subprocess
import tempfile
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

from . import values as V

U = 2.0 ** -53                   # unit roundoff of binary64
DBL_MIN = 2.0 ** -1022           # smallest normal binary64
COMPONENTS = ("fp_contract", "denormal_flush", "reduction_order")
FMA_BASELINE = {"x86_64": False, "amd64": False, "i686": False, "aarch64": True, "arm64": True, "ppc64le": True,
                "s390x": True, "riscv64": True}
# IR ops whose result IEEE 754 does not fix to the bit (libm functions, NaN and signed-zero conventions of min/max)
NOT_CORRECTLY_ROUNDED = frozenset({"ACOS", "ASIN", "ATAN", "ATAN2", "COS", "COSH", "EXP", "LOG", "POW", "SIN",
                                   "SINH", "TAN", "TANH", "MIN", "MAX", "FMOD"})


# ---- the laws ----------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class NumericLaw:
    id: str
    exact_when: str              # the premise under which two environments agree bit for bit
    bound: str                   # what holds when the premise fails
    tier: str                    # tier of the statement (CM46): exactness from IEEE correct rounding, bounds bounded
    source: str


LAWS: dict[str, NumericLaw] = {law.id: law for law in [
    NumericLaw("fp_contract",
               "neither environment contracts a·b ± c into one rounding (fp_contract off, or no FMA instruction in "
               "the target ISA)",
               "|fused − unfused| ≤ u·|a·b|·(1 + u) + 2u·|a·b ± c| for each contracted a·b ± c, u = 2⁻⁵³ "
               "(relative to the result it is unbounded under cancellation)",
               "bounded", "IEEE 754 §5.4.1 (fusedMultiplyAdd); Higham 2002 §2.2"),
    NumericLaw("denormal_flush",
               "neither environment flushes, or no operand or result of a float op lies in (0, 2⁻¹⁰²²)",
               "each flushed value moves by less than 2⁻¹⁰²² (absolute; relative error up to 100 %, and a flushed "
               "divisor turns a finite quotient into ±∞)",
               "bounded", "IEEE 754 §3.4 (subnormals); x86 MXCSR FTZ/DAZ; ENVIRONMENTS.md E13"),
    NumericLaw("reduction_order",
               "both environments sum in the same tree (the sequential fold the IR writes), or every partial sum is "
               "exact (integers of magnitude below 2⁵³)",
               "|S₁ − S₂| ≤ 2·γ₍ₙ₋₁₎·Σ|xᵢ| for two orders of n terms, γₖ = k·u / (1 − k·u)",
               "bounded", "Higham 2002 §4.2; ENVIRONMENTS.md E14"),
    NumericLaw("numeric_exact",
               "both environments are strict on fp_contract, denormal_flush and reduction_order and otherwise strict "
               "IEEE, and the term uses correctly rounded ops only, in the IR's order",
               "the bounds of the component laws whose premise fails (and no claim for non-correctly-rounded ops)",
               "proof", "IEEE 754 §4.3 and §5.4: a correctly rounded op's result is a function of its operands"),
]}


def contract_bound(a: float, b: float, c: float) -> float:
    p = abs(a * b) * (1 + U) ** 2           # ≥ |a·b| from the rounded product
    return U * p * (1 + U) + 2 * U * (abs(a * b + c) + U * p) * (1 + U)


def flush_bound() -> float:
    return DBL_MIN


def gamma(k: int) -> float:
    return k * U / (1 - k * U)


def reduction_bound(xs: list[float]) -> float:
    return 2 * gamma(max(len(xs) - 1, 0)) * math.fsum(abs(x) for x in xs) * (1 + 4 * U)


def subnormal(x) -> bool:
    return isinstance(x, float) and 0.0 < abs(x) < DBL_MIN


def bits(x: float) -> int:
    import struct
    return struct.unpack("<q", struct.pack("<d", x))[0]


def ulps(a: float, b: float) -> int | None:
    """Distance in units in the last place between two finite floats (None for NaN or infinities)."""
    if not (math.isfinite(a) and math.isfinite(b)):
        return None
    def key(x):
        k = bits(x)
        return k if k >= 0 else -(k & 0x7FFFFFFFFFFFFFFF)
    return abs(key(a) - key(b))


def same_bits(a, b, signed_zero: bool = True) -> bool:
    """Bit-for-bit agreement: floats by their binary64 encoding (every NaN equals every NaN; -0.0 differs from
    +0.0 unless ``signed_zero`` is False), everything else as ``values.same``. Used where the numeric models say
    two environments must agree exactly."""
    if isinstance(a, float) and isinstance(b, float):
        if math.isnan(a) or math.isnan(b):
            return math.isnan(a) and math.isnan(b)
        if not signed_zero and a == 0.0 and b == 0.0:
            return True
        return bits(a) == bits(b)
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(same_bits(x, y, signed_zero) for x, y in zip(a, b))
    return V.same(a, b)


# ---- declared models: compile flags read against the language card ----------------------------------------------

REFERENCE = {"runner": "reference", "fp_contract": {"value": False, "evidence": "declared"},
             "denormal_flush": {"value": False, "evidence": "declared"},
             "reduction_order": {"value": "sequential", "evidence": "declared"},
             "strict_ieee": {"value": True, "evidence": "declared"}, "float_text": "roundtrip",
             "note": "M: binary64, each op correctly rounded, in the IR's order (FOUNDATIONS D1, D4)"}


@functools.lru_cache(maxsize=None)
def compiler_family(exe: str) -> str | None:
    """'clang' or 'gcc' from ``exe --version`` (None when it cannot be told)."""
    try:
        r = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    text = (r.stdout + r.stderr).lower()
    return "clang" if "clang" in text else "gcc" if ("gcc" in text or "free software foundation" in text) else None


def host_isa() -> tuple[str, frozenset]:
    from .environment import static
    ident = static()
    return ident["isa"]["machine"].lower(), frozenset(x.lower() for x in ident["isa"]["extensions"])


def declare(lang_card: dict, flags: list[str], compiler: str | None = None, isa: str | None = None,
            host_ext: frozenset | None = None) -> dict:
    """The model a runner's flags permit, from its language card's ``numeric`` block (evidence ``declared``).
    Returns None-valued components when the card has no numeric block (the model is unknown)."""
    spec = lang_card.get("numeric")
    if not spec:
        return {"runner": lang_card.get("name"), **{c: {"value": None, "evidence": "unknown",
                                                         "reason": "the language card has no numeric block"}
                                                     for c in COMPONENTS},
                "strict_ieee": {"value": None, "evidence": "unknown"}, "float_text": None}
    machine = (isa or platform.machine()).lower()
    per = (spec.get("by_compiler") or {}).get(compiler or "", {})
    state = {**(spec.get("default") or {}), **(per.get("default") or {})}
    table = {**(spec.get("flags") or {}), **(per.get("flags") or {})}
    target_isa = "baseline"
    for f in flags:
        eff = table.get(f) or next((v for k, v in table.items() if k.endswith("*") and f.startswith(k[:-1])), None)
        if eff:
            eff = dict(eff)
            if eff.pop("isa", None) == "host":
                target_isa = "host"
            state.update(eff)
    contract = state.get("fp_contract", "off")
    isa_rule = spec.get("contract_isa", "fma")
    if isa_rule == "fma":
        if target_isa == "host":
            ext = host_ext if host_ext is not None else host_isa()[1]
            fma = "fma" in ext or "asimd" in ext or "fp" in ext and machine in ("aarch64", "arm64")
        else:
            fma = FMA_BASELINE.get(machine, False)
    else:                                                     # a list of ISAs where the compiler fuses
        fma = machine in isa_rule
    return {
        "runner": lang_card.get("name"), "flags": list(flags), "compiler": compiler, "isa": machine,
        "target_isa": target_isa,
        "fp_contract": {"value": contract != "off" and fma, "evidence": "declared", "permits": contract,
                        "fma_instruction": fma},
        "denormal_flush": {"value": bool(state.get("denormal_flush")), "evidence": "declared"},
        "reduction_order": {"value": "reassociate" if state.get("reassociate") else "sequential",
                            "evidence": "declared"},
        "strict_ieee": {"value": state.get("strict", True) is not False, "evidence": "declared"},
        "float_text": spec.get("float_text"),
    }


# ---- measured models: the probe, compiled with the runner's own compile line --------------------------------------

PROBE_C = r"""
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
/* cardmodel numeric probe (ENVIRONMENTS.md V-B): inputs are hex floats on stdin, so nothing folds at compile time */
int main(void) {
    double x, m, s, one;
    long n;
    if (scanf("%la %la %la %la %ld", &x, &m, &s, &one, &n) != 5) return 2;
    double contract = x * x - 1.0;                 /* MUL then SUB: one rounding when contracted */
    double ftz = m * 0.5;                          /* a normal operand, a subnormal result */
    double daz = s * one;                          /* a subnormal operand */
    double *v = malloc(sizeof(double) * (size_t)(n > 0 ? n : 1));
    if (!v) return 3;
    for (long i = 0; i < n; i++) if (scanf("%la", &v[i]) != 1) return 4;
    double sum = 0.0;
    for (long i = 0; i < n; i++) sum += v[i];      /* a sequential fold, as written */
    printf("contract %a\nftz %a\ndaz %a\nsum %a\n", contract, ftz, daz, sum);
    free(v);
    return 0;
}
"""

PROBE_X = 1.0 + 2.0 ** -27
PROBE_M = DBL_MIN
PROBE_S = 5e-310
PROBE_N = 4096
PROBE_SEED = 20261105


def probe_vector(n: int = PROBE_N, seed: int = PROBE_SEED) -> list[float]:
    r = random.Random(seed)
    return [r.uniform(-1.0, 1.0) * 10.0 ** r.randint(-8, 8) for _ in range(n)]


def probe_expected() -> dict:
    """M's answers to the probe, and the answers of each non-strict component, computed exactly here."""
    xs = probe_vector()
    seq = 0.0
    for v in xs:
        seq += v
    fused = float(Fraction(PROBE_X) * Fraction(PROBE_X) - 1)
    return {"contract": PROBE_X * PROBE_X - 1.0, "contract_fused": fused, "ftz": PROBE_M * 0.5,
            "daz": PROBE_S * 1.0, "sum": seq, "sum_exact": math.fsum(xs), "vector": xs}


def probe_stdin() -> str:
    xs = probe_vector()
    return (f"{PROBE_X.hex()} {PROBE_M.hex()} {PROBE_S.hex()} {(1.0).hex()} {len(xs)}\n"
            + " ".join(v.hex() for v in xs) + "\n")


def run_probe(compile_line: list[str], timeout: float = 120.0) -> dict:
    """Compile PROBE_C with ``compile_line`` (a runner's ``compile`` list with {src} and {bin} unfilled, {exe}
    filled) and run it. Returns {"contract": x, "ftz": x, "daz": x, "sum": x} or {"unknown": reason}."""
    from ..kernel import resources
    with tempfile.TemporaryDirectory(prefix="cardmodel_numeric_") as d:
        src, exe = Path(d) / "probe.c", Path(d) / "probe"
        src.write_text(PROBE_C, encoding="utf-8")
        cmd = [a.format(src=str(src), bin=str(exe), dir=d) for a in compile_line]
        try:
            r = resources.run(cmd, timeout=timeout, cwd=d)
        except (OSError, subprocess.SubprocessError) as exc:
            return {"unknown": f"the probe did not compile: {exc}"}
        if r.returncode != 0:
            return {"unknown": f"the probe did not compile: {(r.stderr or r.stdout).strip()[-300:]}"}
        try:
            r = resources.run([str(exe)], timeout=timeout, input=probe_stdin(), cwd=d)
        except (OSError, subprocess.SubprocessError) as exc:
            return {"unknown": f"the probe did not run: {exc}"}
        if r.returncode != 0:
            return {"unknown": f"the probe exited {r.returncode}: {r.stderr.strip()[-300:]}"}
    out = {}
    for line in r.stdout.splitlines():
        k, _, v = line.partition(" ")
        if k in ("contract", "ftz", "daz", "sum"):
            out[k] = float.fromhex(v.strip())
    missing = {"contract", "ftz", "daz", "sum"} - set(out)
    return out if not missing else {"unknown": f"the probe printed no {', '.join(sorted(missing))}"}


def observe(raw: dict, expected: dict | None = None) -> dict:
    """What a probe run shows for each component, bit for bit against M: {component: bool or order}."""
    e = expected or probe_expected()
    return {
        "fp_contract": not same_bits(raw["contract"], e["contract"]),
        "contract_is_fused": same_bits(raw["contract"], e["contract_fused"]),
        "denormal_flush": raw["ftz"] == 0.0 or raw["daz"] == 0.0,
        "ftz": raw["ftz"] == 0.0, "daz": raw["daz"] == 0.0,
        "reduction_order": "sequential" if same_bits(raw["sum"], e["sum"]) else "reassociate",
    }


def combine(declared: dict, raw: dict | None, expected: dict | None = None) -> dict:
    """The model: each component the declared permission or the observed effect, with its evidence (D17).
    A component the flags forbid and the probe shows anyway refutes the declared row, and says so."""
    m = copy.deepcopy(declared)
    if not raw or "unknown" in raw:
        if raw:
            m["probe"] = {"unknown": raw["unknown"]}
        return m
    seen = observe(raw, expected)
    m["probe"] = {"values": {k: v.hex() for k, v in raw.items()}, "observed": seen}
    for c in COMPONENTS:
        d = m[c]
        strict_seen = seen[c] in (False, "sequential")
        d["observed"] = seen[c]
        if d["value"] is None:
            d.update(value=seen[c], evidence="measured")
        elif d["value"] in (False, "sequential"):
            if strict_seen:
                d["evidence"] = "measured"
            else:
                d.update(value=seen[c], evidence="measured", refutes="the declared row (the flags forbid it)")
        elif not strict_seen:
            d["evidence"] = "measured"
        # else: permitted by the flags, not shown by the probe's loop: stays declared
    return m


EXTRA_MODES = [                      # compile modes measured beside the analyse runner variants
    ("native", {"add": ["-march=native"]}),
    ("native_contract", {"add": ["-march=native", "-ffp-contract=fast"]}),
    ("O3_fast_native", {"replace": {"-O2": "-O3"}, "add": ["-ffast-math", "-march=native"]}),
]
PROBED = "c"                         # the language PROBE_C is written in


def models(ctx, measure: bool = True, extra: bool = True) -> dict:
    """The numeric model of every available analyse runner (``analyse.runners``) and the extra C modes: declared
    from the flags, measured by the probe for the C runners when ``measure``."""
    from . import analyse, probes
    out: dict[str, dict] = {}
    expected = probe_expected() if measure else None
    isa, ext = host_isa()
    rs = analyse.runners(ctx)
    if extra and ctx.available(PROBED)[0]:
        base = ctx.language(PROBED)
        rs += [(f"{PROBED}@{s}", PROBED, analyse._variant(base, spec, s)) for s, spec in EXTRA_MODES]
    for name, base, card in rs:
        comp = (card.get("runner") or {}).get("compile") or []
        ok, exe = probes.probe(card.get("probe"))
        fam = compiler_family(exe) if ok and comp else None
        m = declare(card, [a for a in comp if a.startswith("-")], fam, isa, ext)
        m["runner"] = name
        if measure and base == PROBED and ok and comp:
            m = combine(m, run_probe([a.format(exe=exe) if "{exe}" in a else a for a in comp]), expected)
        out[name] = m
    return out


def model_of(ctx, name: str, card: dict, env: dict | None = None) -> dict:
    """The model the comparison uses for runner ``name``: the measured one on the environment card when there is
    one, else the declared one from the runner's flags."""
    if name in ("python", "reference"):
        return REFERENCE
    have = ((env or {}).get("numeric") or {}).get("models", {}).get(name)
    if have:
        return have
    from . import probes
    comp = (card.get("runner") or {}).get("compile") or []
    ok, exe = probes.probe(card.get("probe"))
    m = declare(card, [a for a in comp if a.startswith("-")], compiler_family(exe) if ok and comp else None)
    m["runner"] = name
    return m


# ---- the laws applied: agreement of two models, and the laws checked on the probes --------------------------------

def strict(m: dict) -> bool | None:
    vals = [m[c]["value"] for c in COMPONENTS] + [m["strict_ieee"]["value"]]
    if any(v is None for v in vals):
        return None
    return m["fp_contract"]["value"] is False and m["denormal_flush"]["value"] is False and \
        m["reduction_order"]["value"] == "sequential" and m["strict_ieee"]["value"] is True


# atoms whose binary64 result a non-strict component changes (the component's part of the carry map's gap)
COMPONENT_ATOMS = {
    "fp_contract": ("MUL", "ADD", "SUB"),
    "denormal_flush": ("ADD", "SUB", "MUL", "DIV", "FSQRT", "F32", "TO_FLOAT"),
    "reduction_order": ("ADD", "SUB"),
}


def carry_map(model: dict, ops) -> dict:
    """The numeric model as a translation target (ENVIRONMENTS.md D16, FOUNDATIONS D13): the carry map that sends
    each op atom whose result the model reproduces bit for bit to itself. The atoms left out (the libm functions,
    and the atoms a non-strict component changes) form the gap of carrying a term to that model."""
    out_ = set(NOT_CORRECTLY_ROUNDED)
    for c in COMPONENTS:
        if model[c]["value"] not in (False, "sequential"):
            out_ |= set(COMPONENT_ATOMS[c])
    from collections import Counter
    return {f"op/{o}": Counter({f"op/{o}": 1}) for o in ops if o not in out_}


def gap(model: dict, module: dict, ops) -> list[str]:
    """The atoms of ``module`` outside the model's exact carry map (godel.carry's gap), sorted. Reported beside the
    agreement; the comparison itself always runs the term (values come from M and the runners, never content)."""
    from . import godel
    _image, g = godel.carry(godel.module_content(module, ops), carry_map(model, ops))
    return sorted(g)


def agreement(a: dict, b: dict, module: dict | None = None, ops=None) -> dict:
    """How two environments must agree on ``module``: ``exact`` (bit for bit, the numeric_exact law) or ``bounded``
    with the component laws whose premise fails; ``unknown`` when either model is. With ``module`` and ``ops``,
    ``gap`` lists the module's atoms that either model does not carry exactly (libm functions are never exact)."""
    sa, sb = strict(a), strict(b)
    if sa is None or sb is None:
        return {"mode": "unknown", "laws": [], "because": "a numeric model is unknown", "tier": "none", "gap": []}
    g = sorted(set(gap(a, module, ops)) | set(gap(b, module, ops))) if module is not None and ops is not None \
        else []
    failing = [c for c in COMPONENTS
               if a[c]["value"] not in (False, "sequential") or b[c]["value"] not in (False, "sequential")]
    if not failing and a["strict_ieee"]["value"] and b["strict_ieee"]["value"]:
        if g:
            return {"mode": "bounded", "laws": [], "gap": g, "tier": "sample",
                    "because": "the term uses ops that are not correctly rounded: " + ", ".join(g)}
        ev = {a[c]["evidence"] for c in COMPONENTS} | {b[c]["evidence"] for c in COMPONENTS}
        return {"mode": "exact", "laws": ["numeric_exact"], "because": "both models strict", "gap": [],
                "tier": "proof" if ev == {"measured"} else "declared"}
    return {"mode": "bounded", "laws": failing or ["numeric_exact"], "gap": g,
            "because": "premise fails: " + ", ".join(failing or ["strict_ieee"]), "tier": "bounded"}


def compare(x, y, agree: dict) -> bool:
    """Two results under an agreement: bit for bit when exact, ``values.same``'s tolerance otherwise."""
    return same_bits(x, y) if agree["mode"] == "exact" else V.same(x, y)


def check(a: dict, b: dict) -> list[dict]:
    """The laws tested on two measured models' probe values: for each probe, the law that governs it, what it
    predicts (exact or a bound) and whether the two runs satisfy it. A law whose premise holds and whose
    prediction fails is ``refuted``; a premise that fails moves the prediction to the bound."""
    pa, pb = a.get("probe", {}).get("values"), b.get("probe", {}).get("values")
    if not pa or not pb:
        return []
    e = probe_expected()
    rows = []
    for probe, law, bound in (("contract", "fp_contract", contract_bound(PROBE_X, PROBE_X, -1.0)),
                              ("ftz", "denormal_flush", flush_bound()), ("daz", "denormal_flush", flush_bound()),
                              ("sum", "reduction_order", reduction_bound(e["vector"]))):
        x, y = float.fromhex(pa[probe]), float.fromhex(pb[probe])
        premise = a[law]["value"] in (False, "sequential") and b[law]["value"] in (False, "sequential") \
            and a["strict_ieee"]["value"] and b["strict_ieee"]["value"]
        diff = abs(x - y)
        if premise:
            verdict = "holds" if same_bits(x, y) else "refuted"
            pred = "exact"
        else:
            verdict = "holds" if diff <= bound else "refuted"
            pred = f"|Δ| ≤ {bound:.3g}"
        rows.append({"probe": probe, "law": law if not premise else "numeric_exact", "premise": premise,
                     "predicts": pred, "a": x.hex(), "b": y.hex(), "diff": diff, "ulps": ulps(x, y),
                     "bit_equal": same_bits(x, y), "verdict": verdict})
    return rows


PAIRS = [("c@O0", "c@O2"), ("c@O2", "c@ubsan"), ("c@O2", "c@native"), ("c@O2", "c@fastmath"),
         ("c@O2", "c@native_contract"), ("c@O2", "c@O3_fast_native")]     # the pairs `cardmodel env --numeric` checks


def render(models_: dict) -> str:
    def v(c):
        return f"{c['value']}{'' if c['evidence'] == 'measured' else ' (' + c['evidence'] + ')'}"
    lines = ["numeric models (fp_contract · denormal_flush · reduction_order · strict IEEE):"]
    for name, m in models_.items():
        if m["fp_contract"]["value"] is None:
            lines.append(f"  {name:<22} unknown (no numeric block on the language card)")
            continue
        lines.append(f"  {name:<22} {v(m['fp_contract']):<20} {v(m['denormal_flush']):<20} "
                     f"{v(m['reduction_order']):<24} {m['strict_ieee']['value']}"
                     + (f"   probe: {m['probe']['unknown']}" if "unknown" in m.get("probe", {}) else ""))
    return "\n".join(lines)


__all__ = ["LAWS", "agreement", "check", "compare", "declare", "models", "model_of", "observe", "run_probe",
           "same_bits", "strict"]
