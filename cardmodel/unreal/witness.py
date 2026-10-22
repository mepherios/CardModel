"""witness — every lifted term against the engine's own compiled code, on seeded inputs.

A harness (C++, in the cache) includes the engine's math headers with the flags the engine ships with (NEON on, no
FMA contraction, as UnrealBuildTool compiles for Mac) and links the engine's Core library, so a header function is
the engine's source compiled as the engine compiles it, and an out-of-line function is the engine's own binary.
Access control is opened by the preprocessor (``private`` and ``protected`` read as ``public``, after the standard
headers), since the harness sets and reads every field, as the lift does. For each function and each seeded case it
sets every input slot (the bits of a double or a float, an integer, a bool), calls the function, and prints every
output slot's bits. ``evaluate`` computes the lifted term on the same inputs with IEEE semantics (binary64
arithmetic, binary32 rounding where the term says F32, the platform's own C library for the atoms: a float call such
as ``acosf`` by the float function, which need not be the double one rounded). Inputs where C++ is undefined (an
index outside the object, a shift past the width, integer division by zero) are never run: the term says where they
are, and the rows are drawn again.

Where the shipped build is not bit-exact (or cannot be compiled), the engine's scalar build decides, compiled from
the headers and from every ``.cpp`` file the term reaches (the function's own and those of what it calls across
units), so no part of the term runs as the shipped library's NEON code.

Verdict per function: ``witnessed`` (every output bit-exact on every case), ``witnessed_ulp`` (all within a few
ulps: a C library function computed in another precision, or a NEON path the scalar term rounds differently;
the largest distance is recorded), ``refuted`` (a counterexample: the inputs, the engine's value, the term's), or
why it could not be run (not callable from outside, not exported by the library, a crash). A planted change in a
term is caught (tests/test_unreal.py), so a pass is not vacuous (CM07).

Honest limits (L1): seeded sampling, not proof; inputs are drawn without regard to a function's preconditions (a
quaternion need not be normalized), which is fine for agreement but can visit inputs where both sides are NaN;
inputs where the term is undefined are drawn again and counted (``undefined`` on the verdict).
"""
from __future__ import annotations

import ctypes
import ctypes.util
import math
import random
import re
import struct
import subprocess
from pathlib import Path

from ..kernel import resources
from . import engine as E
from . import units as UN
from .lift import INT_KINDS, f32

CASES = 24
MAX_ROUNDS = 20
DRAWABLE = ("f64", "f32", "b", *INT_KINDS)
BATCH = 160
ULP_OK = {"f64": 64, "f32": 16}
SELF = "&this"              # an output that is the object itself (operator+= returns *this): checked by address
OPS = {"FSQRT": math.sqrt, "SIN": math.sin, "COS": math.cos, "TAN": math.tan, "ASIN": math.asin,
       "ACOS": math.acos, "ATAN": math.atan, "ATAN2": math.atan2, "EXP": math.exp, "LOG": math.log,
       "LOG2": math.log2, "LOG10": math.log10, "SINH": math.sinh, "COSH": math.cosh, "TANH": math.tanh,
       "HYPOT": math.hypot, "FMOD": math.fmod, "POW": math.pow, "COPYSIGN": math.copysign}
# the atoms by the platform's own C library, the one the engine's code calls: double functions, and the float ones
# (acosf, sinf, ...) for an atom rounded to float whose arguments are floats (a float call; Apple's acosf(-1) is the
# float just below pi, not pi rounded)
C_NAMES = {"FSQRT": ("sqrt", 1), "SIN": ("sin", 1), "COS": ("cos", 1), "TAN": ("tan", 1), "ASIN": ("asin", 1),
           "ACOS": ("acos", 1), "ATAN": ("atan", 1), "ATAN2": ("atan2", 2), "EXP": ("exp", 1), "EXP2": ("exp2", 1),
           "LOG": ("log", 1), "LOG2": ("log2", 1), "LOG10": ("log10", 1), "SINH": ("sinh", 1), "COSH": ("cosh", 1),
           "TANH": ("tanh", 1), "HYPOT": ("hypot", 2), "FMOD": ("fmod", 2), "POW": ("pow", 2),
           "COPYSIGN": ("copysign", 2), "CBRT": ("cbrt", 1)}


def _libm():
    try:
        return ctypes.CDLL(ctypes.util.find_library("m") or None)
    except OSError:
        return None


def _bind(lib, name: str, ctype, n: int):
    fn = getattr(lib, name, None) if lib is not None else None
    if fn is not None:
        fn.restype, fn.argtypes = ctype, [ctype] * n
    return fn


_M = _libm()
C_DOUBLE = {op: f for op, (nm, n) in C_NAMES.items() if (f := _bind(_M, nm, ctypes.c_double, n)) is not None}
C_FLOAT = {op: f for op, (nm, n) in C_NAMES.items() if (f := _bind(_M, nm + "f", ctypes.c_float, n)) is not None}


def _is_f32(x) -> bool:
    x = float(x)
    return x != x or f32(x) == x


# -- IEEE evaluation of a term ---------------------------------------------------------------------------------------
class Undefined(Exception):
    """The term has no value here in C++ either (integer division by zero, a shift past the width)."""


def _ieee(fn, *a):
    try:
        return fn(*a)
    except ValueError:
        return _c_edge(fn, *a)
    except OverflowError:
        return math.inf
    except ZeroDivisionError:
        return math.nan


def _c_edge(fn, *a):
    """What C's libm returns where Python raises: log of zero is -inf, pow(0, y < 0) is inf (signed for odd y)."""
    if fn in (math.log, math.log2, math.log10) and a[0] == 0.0:
        return -math.inf
    if fn is math.pow:
        x, y = a
        if x == 0.0 and y < 0:
            odd = float(y).is_integer() and int(y) % 2 == 1
            return math.copysign(math.inf, x) if odd else math.inf
    return math.nan


def _div(a, b):
    if isinstance(a, float) or isinstance(b, float):
        a, b = float(a), float(b)
        if b == 0.0:
            if a != a or a == 0.0:
                return math.nan
            return math.copysign(math.inf, a) * math.copysign(1.0, b)
        return a / b
    if b == 0:
        raise Undefined("division by zero")
    return a / b


def _bits32(x: float) -> int:
    return struct.unpack("<I", struct.pack("<f", f32(x)))[0]


def _round_half_away(x: float) -> float:
    if not math.isfinite(x):
        return x
    r = math.floor(abs(x) + 0.5)
    return math.copysign(float(r), x)


def evaluate(t, env: dict, memo: dict | None = None):
    """The value of a lifted term (IEEE semantics; see the module docstring). A shared subterm is computed once."""
    if memo is None:
        memo = {}
    if isinstance(t, list) and t and t[0] not in ("var", "int", "float", "bool"):
        hit = memo.get(id(t))
        if hit is not None and hit[0] is t:
            return hit[1]
        v = _evaluate(t, env, memo)
        memo[id(t)] = (t, v)
        return v
    return _evaluate(t, env, memo)


def _evaluate(t, env: dict, memo: dict):
    head = t[0]
    if head == "var":
        if t[1].startswith("<undefined"):
            raise Undefined(t[1].strip("<>"))
        return env[t[1]]
    if head in ("int", "float", "bool"):
        return t[1]
    if head == "F32" and isinstance(t[1], list) and t[1] and t[1][0] in C_FLOAT:
        args = [evaluate(x, env, memo) for x in t[1][1:]]
        if all(_is_f32(x) for x in args):
            return C_FLOAT[t[1][0]](*[float(x) for x in args])
        return f32(C_DOUBLE[t[1][0]](*[float(x) for x in args]) if t[1][0] in C_DOUBLE
                   else _ieee(OPS[t[1][0]], *args))
    if head == "IF_EXPR":
        return evaluate(t[2], env, memo) if evaluate(t[1], env, memo) else evaluate(t[3], env, memo)
    if head == "AND":
        return all(evaluate(a, env, memo) for a in t[1:])
    if head == "OR":
        return any(evaluate(a, env, memo) for a in t[1:])
    a = [evaluate(x, env, memo) for x in t[1:]]
    if head == "ADD":
        return a[0] + a[1]
    if head == "SUB":
        return a[0] - a[1]
    if head == "MUL":
        return a[0] * a[1]
    if head == "DIV":
        return _div(a[0], a[1])
    if head == "NEG":
        return -a[0]
    if head == "F32":
        return f32(a[0])
    if head in C_DOUBLE:
        return C_DOUBLE[head](*[float(x) for x in a])
    if head == "TO_FLOAT":
        return float(a[0])
    if head == "TRUNC_INT":
        if not math.isfinite(a[0]):
            raise Undefined("a float that is not finite converted to an integer")
        return int(a[0])
    if head in ("CMP_LT", "CMP_GT", "CMP_LE", "CMP_GE", "CMP_EQ", "CMP_NE"):
        x, y = a
        return {"CMP_LT": x < y, "CMP_GT": x > y, "CMP_LE": x <= y, "CMP_GE": x >= y, "CMP_EQ": x == y,
                "CMP_NE": x != y}[head]
    if head == "NOT":
        return not a[0]
    if head == "FLOORDIV":
        if a[1] == 0:
            raise Undefined("division by zero")
        return a[0] // a[1]
    if head == "MOD":
        if a[1] == 0:
            raise Undefined("division by zero")
        return a[0] % a[1]
    if head == "BIT_AND":
        return a[0] & a[1]
    if head == "BIT_OR":
        return a[0] | a[1]
    if head == "BIT_XOR":
        return a[0] ^ a[1]
    if head == "BIT_NOT":
        return ~a[0]
    if head == "SHIFT_LEFT":
        if not 0 <= a[1] < 64:              # the lifter guards a count on the inputs by the operand's own width
            raise Undefined("a shift past the width")
        return a[0] << a[1]
    if head == "SHIFT_RIGHT":
        if not 0 <= a[1] < 64:
            raise Undefined("a shift past the width")
        return a[0] >> a[1]
    if head == "ABS":
        return abs(a[0])
    if head in ("MIN", "FMIN"):
        x, y = a
        if head == "FMIN" and (x != x or y != y):
            return y if x != x else x
        return y if y < x else x
    if head in ("MAX", "FMAX"):
        x, y = a
        if head == "FMAX" and (x != x or y != y):
            return y if x != x else x
        return y if y > x else x
    if head == "FLOOR":
        return float(math.floor(a[0])) if math.isfinite(a[0]) else a[0]
    if head == "CEIL":
        return float(math.ceil(a[0])) if math.isfinite(a[0]) else a[0]
    if head == "TRUNC":
        return float(math.trunc(a[0])) if math.isfinite(a[0]) else a[0]
    if head == "ROUND":
        return _round_half_away(a[0])
    if head == "RINT":
        return float(round(a[0])) if math.isfinite(a[0]) else a[0]
    if head == "EXP2":
        return _ieee(lambda x: 2.0 ** x, a[0])
    if head == "CBRT":
        return math.copysign(abs(a[0]) ** (1.0 / 3.0), a[0]) if not hasattr(math, "cbrt") else math.cbrt(a[0])
    if head == "ISNAN":
        return a[0] != a[0]
    if head == "ISFINITE":
        return math.isfinite(a[0])
    if head == "ISINF":
        return math.isinf(a[0])
    if head == "F32_BITS":
        return _bits32(a[0])
    if head == "BITS_F32":
        return struct.unpack("<f", struct.pack("<I", a[0] & 0xFFFFFFFF))[0]
    if head == "F64_BITS":
        return struct.unpack("<Q", struct.pack("<d", a[0]))[0]
    if head == "BITS_F64":
        return struct.unpack("<d", struct.pack("<Q", a[0] & 0xFFFFFFFFFFFFFFFF))[0]
    if head in ("CLZ32", "CLZ64"):
        w = 32 if head == "CLZ32" else 64
        if a[0] == 0:
            raise Undefined("clz of zero")
        return w - (a[0] & ((1 << w) - 1)).bit_length()
    if head in ("CTZ32", "CTZ64"):
        if a[0] == 0:
            raise Undefined("ctz of zero")
        return (a[0] & -a[0]).bit_length() - 1
    if head == "POPCOUNT":
        return bin(a[0] & 0xFFFFFFFFFFFFFFFF).count("1")
    if head in OPS:
        return _ieee(OPS[head], *a)
    raise ValueError(f"no evaluation for {head}")


# -- inputs ------------------------------------------------------------------------------------------------------------
def draw(kind: str, rng: random.Random):
    if kind in ("f64", "f32"):
        r = rng.random()
        if r < 0.15:
            v = rng.uniform(-1.0, 1.0)
        elif r < 0.25:
            v = float(rng.randint(-8, 8))
        elif r < 0.3:
            v = 0.0
        else:
            v = rng.uniform(-100.0, 100.0)
        return f32(v) if kind == "f32" else v
    if kind == "b":
        return rng.random() < 0.5
    bits, signed = INT_KINDS[kind]
    lo, hi = (-(1 << (bits - 1)), (1 << (bits - 1)) - 1) if signed else (0, (1 << bits) - 1)
    r = rng.random()
    if r < 0.15:
        # the edges: an unsigned value's top bit and maximum (wrapping is defined there), small signed values
        edges = [0, 1, -1] if signed else [0, 1, hi, 1 << (bits - 1), (1 << (bits - 1)) - 1]
        return rng.choice(edges)
    if r < 0.5:
        v = rng.randint(0, 31)
    elif r < 0.8:
        v = rng.randint(-1000, 1000) if signed else rng.randint(0, 1000)
    else:
        # wide values, still where the C++ arithmetic of a few operations does not overflow (that is undefined)
        cap = 1 << min(bits - 1, 15)
        v = rng.randint(-cap, cap) if signed else rng.randint(0, min(hi, 1 << 16))
    return max(lo, min(hi, v))


def edge(kind: str, j: int):
    """The first two cases of every function: an unsigned value's maximum and its top bit alone (where a wrong
    conversion shows), small signed values, plain floats, both truth values."""
    if kind in ("f64", "f32"):
        return (0.5, -2.0)[j]
    if kind == "b":
        return (True, False)[j]
    bits, signed = INT_KINDS[kind]
    return (-1, 1)[j] if signed else ((1 << bits) - 1, 1 << (bits - 1))[j]


def defined_rows(f: dict, rng: random.Random, n: int) -> tuple[list[list], list, int]:
    """``n`` seeded input rows on which the C++ is defined (an index inside the object, no division by zero, no
    shift past the width), with the term's values there: the engine's code is never run where C++ leaves it
    undefined. The first two candidates are the edges. Returns (rows, the term's values on each row or None where
    the term cannot be evaluated, how many undefined candidates were left out)."""
    rows, wants, dropped = [], [], 0
    for j in range(n * 8):
        if len(rows) == n:
            break
        row = [edge(k, j) if j < 2 else draw(k, rng) for _nm, k in f["inputs"]]
        env = {nm: v for (nm, _k), v in zip(f["inputs"], row)}
        try:
            memo: dict = {}
            want = [_want(o, env, memo) for o in f["outputs"]]
        except Undefined:
            dropped += 1
            continue
        except (RecursionError, ValueError, TypeError, KeyError, OverflowError):
            want = None                                       # compare reports it
        rows.append(row)
        wants.append(want)
    return rows, wants, dropped


def _want(o: dict, env: dict, memo: dict):
    return True if o["kind"] == SELF else evaluate(o["term"], env, memo)


def to_bits(kind: str, v) -> int:
    if kind == "f64":
        return struct.unpack("<Q", struct.pack("<d", v))[0]
    if kind == "f32":
        return struct.unpack("<I", struct.pack("<f", v))[0]
    if kind == "b":
        return 1 if v else 0
    return v & 0xFFFFFFFFFFFFFFFF


def from_bits(kind: str, text: str):
    if kind == "f64":
        return struct.unpack("<d", struct.pack("<Q", int(text, 16)))[0]
    if kind == "f32":
        return struct.unpack("<f", struct.pack("<I", int(text, 16)))[0]
    if kind == "b":
        return text == "1"
    v = int(text)
    bits, signed = INT_KINDS[kind]
    v &= (1 << bits) - 1
    return v - (1 << bits) if signed and v >> (bits - 1) else v


def ulps(kind: str, a: float, b: float) -> int:
    """The number of representable values between two floats of a kind (0: the same bits)."""
    if a != a and b != b:
        return 0
    if a != a or b != b:
        return 1 << 62
    fmt, ifmt = ("<d", "<q") if kind == "f64" else ("<f", "<i")
    ia = struct.unpack(ifmt, struct.pack(fmt, a))[0]
    ib = struct.unpack(ifmt, struct.pack(fmt, b))[0]
    top = (1 << 63) if kind == "f64" else (1 << 31)
    ia = top - ia if ia < 0 else ia
    ib = top - ib if ib < 0 else ib
    return abs(ia - ib)


# -- the harness -------------------------------------------------------------------------------------------------------
OPEN_ACCESS = r"""
#include <cstdio>
#include <cstring>
#include <cstdint>
#include <cstdlib>
#include <type_traits>
#include <new>
#include <atomic>
#include <string>
#include <vector>
#include <memory>
#include <functional>
#include <utility>
#include <limits>
#include <initializer_list>
#include <tuple>
#include <cmath>
#define private public
#define protected public
"""

PRELUDE = r"""
#include <cstdio>
#include <cstring>
#include <cstdint>
#include <type_traits>
#include <new>
template<class T> static T& cm_blank(void* buf) { std::memset(buf, 0, sizeof(T)); return *reinterpret_cast<T*>(buf); }
static inline void cm_set(double& d, uint64_t b) { std::memcpy(&d, &b, 8); }
static inline void cm_set(float& d, uint64_t b) { uint32_t u = (uint32_t)b; std::memcpy(&d, &u, 4); }
static inline void cm_set(bool& d, uint64_t b) { d = b != 0; }
template<class I> static inline std::enable_if_t<std::is_integral_v<I>> cm_set(I& d, uint64_t b) { d = (I)(int64_t)b; }
template<class I> static inline std::enable_if_t<std::is_enum_v<I>> cm_set(I& d, uint64_t b) { d = (I)(int64_t)b; }
static inline void cm_put(double d) { uint64_t b; std::memcpy(&b, &d, 8); std::printf(" %016llx", (unsigned long long)b); }
static inline void cm_put(float f) { uint32_t u; std::memcpy(&u, &f, 4); std::printf(" %08x", u); }
static inline void cm_put(bool b) { std::printf(" %d", b ? 1 : 0); }
template<class I> static inline std::enable_if_t<std::is_integral_v<I>> cm_put(I i) { std::printf(" %lld", (long long)i); }
template<class I> static inline std::enable_if_t<std::is_enum_v<I>> cm_put(I i) { std::printf(" %lld", (long long)i); }
"""

OPERATORS = {"operator+", "operator-", "operator*", "operator/", "operator^", "operator|", "operator==",
             "operator!=", "operator<", "operator>", "operator<=", "operator>=", "operator+=", "operator-=",
             "operator*=", "operator/=", "operator%", "operator&", "operator<<", "operator>>", "operator!"}


def _cpp_type(t: str | None) -> str:
    t = (t or "").strip()
    t = re.sub(r"&&?$|\*$", "", t).strip()
    t = re.sub(r"^const\s+", "", t)
    t = re.sub(r"\s+const$", "", t)
    return t.strip()


def _path(var: str, slot_name: str) -> str:
    """A slot's place in C++: the variable, then the slot's member path (X, M[0][1], Origin.X, [3])."""
    if not slot_name:
        return var
    return var + (slot_name if slot_name.startswith("[") else "." + slot_name)


def _split_slot(name: str, prefixes: list[str]) -> tuple[str, str] | None:
    for p in sorted(prefixes, key=len, reverse=True):
        if name == p:
            return p, ""
        if name.startswith(p + ".") or name.startswith(p + "["):
            rest = name[len(p):]
            return p, rest[1:] if rest.startswith(".") else rest
    return None


def function_code(i: int, f: dict, cases: list[list[int]]) -> str | None:
    """The harness function for one engine function, or None (with no way to call it from outside)."""
    kind = f["kind"]
    if kind == "conversion" or f["name"].startswith("operator new") or f["name"].startswith("operator delete"):
        return None
    params = f.get("params") or []
    pnames = [p["name"] for p in params]
    prefixes = ["this", *pnames]
    lines = [f"__attribute__((noinline)) static void w{i}() {{",
             f"  static const uint64_t V[{len(cases)}][{max(1, len(f['inputs']))}] = {{"]
    for row in cases:
        lines.append("    {" + ", ".join(f"0x{v:x}ull" for v in row) + "},")
    lines.append("  };")
    lines.append(f"  for (int c = 0; c < {len(cases)}; c++) {{")
    lines.append("    const uint64_t* v = V[c];")
    rec = f.get("record")
    decl = []
    for j, p in enumerate(params):
        t = p.get("dt") or p["type"]
        base = p.get("cpp") or _cpp_type(t)
        if not base or "(" in base or base == "void":
            return None
        if t.rstrip().endswith("*"):
            decl.append(f"    alignas(16) static unsigned char b{j}[sizeof({base}) * 64]; std::memset(b{j}, 0, "
                        f"sizeof b{j}); {base}* a{j} = reinterpret_cast<{base}*>(b{j});")
        else:
            decl.append(f"    alignas(16) static unsigned char b{j}[sizeof({base})]; "
                        f"{base}& a{j} = cm_blank<{base}>(b{j});")
    if f["kind"] in ("method", "operator") and not f.get("static") and rec:
        decl.append(f"    alignas(16) static unsigned char bs[sizeof({rec})]; {rec}& self = cm_blank<{rec}>(bs);")
    lines += decl
    var = {"this": "self", **{p["name"]: f"a{j}" for j, p in enumerate(params)}}
    for k, (nm, _kind) in enumerate(f["inputs"]):
        sp = _split_slot(nm, prefixes)
        if sp is None:
            return None
        lines.append(f"    cm_set({_path(var[sp[0]], sp[1])}, v[{k}]);")
    args = ", ".join(f"a{j}" for j in range(len(params)))
    targs = f.get("targs") or []
    ta = f"<{', '.join(targs)}>" if targs else ""
    name, qual = f["name"], f["qual"]
    has_ret = any(o["name"] == "return" or o["name"].startswith("return.") for o in f["outputs"])
    if kind == "constructor":
        if not rec:
            return None
        call = f"    {rec} r({args});" if args else f"    {rec} r;"
        var["this"] = "r"
    elif kind in ("method", "operator") and not f.get("static") and rec:
        call = f"    auto&& r = self.{name}{ta}({args});" if has_ret else f"    self.{name}{ta}({args});"
    elif name in OPERATORS:
        call = f"    auto&& r = {name}({args});" if has_ret else f"    {name}({args});"
    else:
        call = f"    auto&& r = {qual}{ta}({args});" if has_ret else f"    {qual}{ta}({args});"
    lines.append(call)
    var["return"] = "r"
    lines.append(f'    std::printf("{i} %d", c);')
    for o in f["outputs"]:
        if o["kind"] == SELF:
            if var["this"] != "self":
                return None
            lines.append("    cm_put((bool)((const void*)&r == (const void*)&self));")
            continue
        sp = _split_slot(o["name"], ["return", *prefixes])
        if sp is None:
            return None
        lines.append(f"    cm_put({_path(var[sp[0]], sp[1])});")
    lines.append('    std::printf("\\n");')
    lines.append("  }")
    lines.append("}")
    return "\n".join(lines)


class Target:
    """What a harness compiles against: include lines, compiler flags, link arguments, and where it builds."""

    def __init__(self, includes: list[str], flags: list[str], link: list[str], workdir: Path):
        self.includes, self.flags, self.link, self.workdir = includes, flags, link, workdir

    @classmethod
    def truth(cls, eng: E.Engine, cache: Path, sources: tuple[str, ...] = ()) -> Target:
        """The engine's scalar path (its FPU fallback), compiled from its headers and from the .cpp files a term
        reaches (``sources``, relative to the engine root: the function's own, and those of what it calls across
        units), compiled into the harness, so no part of the term runs as the shipped library's NEON code; the Core
        library is linked for the rest."""
        lib = eng.core_library()
        link = [f"-L{lib.parent}", "-lUnrealEditor-Core", f"-Wl,-rpath,{lib.parent}"] if lib else []
        inc = list(UN.compiled_includes(eng, cache)) + [f'#include "{eng.root / s}"' for s in sorted(sources)]
        tag = "+".join(Path(s).stem for s in sorted(sources)) or "headers"
        return cls(inc, E.flags(eng, cache, "truth"), link, cache / "witness_truth" / tag)

    @classmethod
    def engine(cls, eng: E.Engine, cache: Path) -> Target:
        """The engine as it ships: its headers with its Mac flags, and its Core library."""
        lib = eng.core_library()
        link = [f"-L{lib.parent}", "-lUnrealEditor-Core", f"-Wl,-rpath,{lib.parent}"] if lib else []
        return cls(UN.compiled_includes(eng, cache), E.flags(eng, cache, "shipped"), link, cache / "witness")


def build_harness(target: Target, clang: str, items: list[tuple[int, dict, list]], tag: str,
                  log=print) -> tuple[Path | None, dict]:
    """Compile one harness; functions clang or the linker rejects are left out with the reason."""
    d = target.workdir
    d.mkdir(parents=True, exist_ok=True)
    src, exe = d / f"h_{tag}.cpp", d / f"h_{tag}"
    flags, link = target.flags, target.link
    rejected: dict[int, str] = {}
    codes = {i: function_code(i, f, cases) for i, f, cases in items}
    for i, c in codes.items():
        if c is None:
            rejected[i] = "not callable from outside (its inputs or its call cannot be written)"
    for _round in range(MAX_ROUNDS):
        live = [i for i in codes if i not in rejected]
        if not live:
            return None, rejected
        parts = [OPEN_ACCESS, "\n".join(target.includes), PRELUDE]
        spans = {}
        line = sum(p.count("\n") + 1 for p in parts)
        for i in live:
            spans[i] = (line + 1, line + codes[i].count("\n") + 1)
            parts.append(codes[i])
            line += codes[i].count("\n") + 1
        main = ["int main(int argc, char** argv) {", "  int only = argc > 1 ? std::atoi(argv[1]) : -1;"]
        main += [f"  if (only < 0 || only == {i}) {{ w{i}(); std::fflush(stdout); }}" for i in live]
        main += ["  return 0;", "}"]
        parts.append("\n".join(["#include <cstdlib>", *main]))
        src.write_text("\n".join(parts) + "\n", encoding="utf-8")
        p = resources.run([clang, *flags, "-O1", "-w", "-ferror-limit=0", str(src), "-o", str(exe), *link],
                          timeout=900, heavy=True, stdin=subprocess.DEVNULL, mem_cap_mb=4096)
        if p.returncode == 0:
            return exe, rejected
        err = p.stderr or ""
        bad = set()
        # an error is the fault of the harness function whose lines it, or one of its notes ('in instantiation
        # of ... requested here'), points at
        name = re.escape(str(src))
        block_msg = None
        for ln_text in err.splitlines():
            m = re.match(rf"^{name}:(\d+):\d+: (fatal error|error|note|warning): (.*)$", ln_text)
            m2 = re.match(r"^.*?:\d+:\d+: (fatal error|error): (.*)$", ln_text)
            if m2 and not m:
                block_msg = m2.group(2)
                continue
            if not m:
                continue
            kind, msg = m.group(2), m.group(3)
            if kind in ("error", "fatal error"):
                block_msg = msg
            elif kind != "note" or block_msg is None:
                continue
            ln = int(m.group(1))
            for i, (a, b) in spans.items():
                if a <= ln <= b and i not in bad:
                    bad.add(i)
                    rejected[i] = "does not compile when called from outside: " + (block_msg or msg)[:160]
        for m in re.finditer(r"referenced from:\s*\n\s*w(\d+)\(\)", err):
            i = int(m.group(1))
            bad.add(i)
            rejected[i] = "not exported by the engine's Core library (an internal symbol)"
        if not bad:
            log(f"  harness {tag}: does not build: {err[-400:]}")
            return None, {**rejected, **{i: "the harness does not build" for i in live}}
    live = [i for i in codes if i not in rejected]
    log(f"  harness {tag}: still failing after {MAX_ROUNDS} rounds")
    return None, {**rejected, **{i: "the harness does not build (too many rounds)" for i in live}}


def run_harness(exe: Path, live: list[int], timeout: int = 300, cases: int | dict = CASES) -> tuple[dict, dict]:
    """Run it; a function that crashes is run alone so the others still report (``cases``: the rows each
    function runs, one count or by function). Returns (lines by function, crashed functions)."""
    out: dict[int, list[str]] = {}
    crashed: dict[int, str] = {}

    def once(only=None):
        args = [str(exe)] + ([str(only)] if only is not None else [])
        try:
            p = resources.run(args, timeout=timeout, heavy=False, stdin=subprocess.DEVNULL)
            return p.returncode, p.stdout or ""
        except subprocess.TimeoutExpired:
            return -999, ""

    rc, text = once()
    for ln in text.splitlines():
        parts = ln.split()
        if parts and parts[0].isdigit():
            out.setdefault(int(parts[0]), []).append(ln)
    if rc != 0:
        for i in live:
            if i in out and len(out[i]) == (cases.get(i, CASES) if isinstance(cases, dict) else cases):
                continue
            rc1, t1 = once(i)
            out[i] = [ln for ln in t1.splitlines() if ln.split() and ln.split()[0] == str(i)]
            if rc1 != 0:
                crashed[i] = "crashed" if rc1 != -999 else "timed out"
    return out, crashed


def compare(f: dict, cases: list[list], lines: list[str], wants: list | None = None) -> dict:
    """The engine's outputs against the term's, case by case (``wants``: the term's values, when known)."""
    kinds = ["b" if o["kind"] == SELF else o["kind"] for o in f["outputs"]]
    checked, skipped, max_ulp, max_rel = 0, 0, 0, 0.0
    for ln in lines:
        parts = ln.split()
        c = int(parts[1])
        got = parts[2:]
        if len(got) != len(kinds):
            return {"status": "error", "reason": f"the harness printed {len(got)} values for {len(kinds)} outputs"}
        env = {nm: v for (nm, _k), v in zip(f["inputs"], cases[c])}
        try:
            want = wants[c] if wants is not None and wants[c] is not None else None
            if want is None:
                memo: dict = {}
                want = [_want(o, env, memo) for o in f["outputs"]]
        except Undefined:
            skipped += 1
            continue
        except (RecursionError, ValueError, TypeError, KeyError, OverflowError) as exc:
            return {"status": "error", "reason": f"the term cannot be evaluated: {type(exc).__name__}: {exc}"}
        for o, k, g, w in zip(f["outputs"], kinds, got, want):
            ev = from_bits(k, g)
            if k in ("f64", "f32"):
                w = float(w)
                if k == "f32":
                    w = f32(w)
                d = ulps(k, ev, w)
                rel = abs(ev - w) / max(abs(w), 1e-300) if math.isfinite(ev) and math.isfinite(w) else (
                    0.0 if d == 0 else math.inf)
                if d > ULP_OK[k] and not (abs(ev - w) <= 1e-300):
                    return {"status": "refuted", "case": c, "output": o["name"], "engine": ev, "term": w,
                            "inputs": dict(env), "ulps": d, "rel": rel}
                max_ulp = max(max_ulp, d)
                max_rel = max(max_rel, rel)
            else:
                w = bool(w) if k == "b" else int(w)
                if k in INT_KINDS:
                    bits, signed = INT_KINDS[k]
                    w &= (1 << bits) - 1
                    w = w - (1 << bits) if signed and w >> (bits - 1) else w
                if ev != w:
                    return {"status": "refuted", "case": c, "output": o["name"], "engine": ev, "term": w,
                            "inputs": dict(env)}
        checked += 1
    if not checked:
        return {"status": "vacuous", "skipped": skipped}
    return {"status": "witnessed" if max_ulp == 0 else "witnessed_ulp", "checks": checked, "skipped": skipped,
            "max_ulp": max_ulp, "max_rel": max_rel}


def sources_of(functions: list[dict]):
    """key -> the .cpp files its term was lifted from: its own, and those of every function it calls across units
    (whose terms scan.resolve inlined)."""
    by_key = {f["key"]: f for f in functions}
    memo: dict[str, frozenset] = {}

    def of(k: str, stack: tuple = ()) -> frozenset:
        if k in memo:
            return memo[k]
        f = by_key.get(k)
        if f is None or k in stack:
            return frozenset()
        s = {f["file"]} if f["file"].endswith(".cpp") else set()
        for x in f.get("xcalls") or {}:
            s |= of(x, (*stack, k))
        memo[k] = frozenset(s)
        return memo[k]
    return of


def run_engine(eng: E.Engine, cache: Path, functions: list[dict], seed: int, only=None, log=print,
               cases: int | None = None) -> dict:
    """The shipped build first; where it is not bit-exact, the truth build (the scalar source the term was lifted
    from) decides whether the term is right, and the shipped distance is kept as the engine's own."""
    v = run(Target.engine(eng, cache), functions, seed, only=only, log=log, cases=cases)
    again = {k for k, x in v.items() if x["status"] in ("refuted", "witnessed_ulp")
             or "does not compile" in (x.get("reason") or "") or "does not build" in (x.get("reason") or "")}
    if not again:
        return v
    log(f"  {len(again)} not settled on the shipped build: witnessing the scalar build")
    src_of = sources_of(functions)
    groups: dict[frozenset, set] = {}
    for k in again:
        groups.setdefault(src_of(k), set()).add(k)
    t: dict = {}
    for srcs, keys in sorted(groups.items(), key=lambda kv: sorted(kv[0])):
        t.update(run(Target.truth(eng, cache, tuple(sorted(srcs))), functions, seed, only=keys, log=log,
                     cases=cases))
    for k in again:
        tv = t.get(k) or {}
        shipped = {kk: v[k][kk] for kk in ("status", "max_ulp", "max_rel", "ulps", "rel", "output", "case")
                   if kk in v[k]}
        if tv.get("status") in ("witnessed", "witnessed_ulp"):
            v[k] = {**tv, "build": "truth", "shipped": shipped}
        elif tv.get("status") == "refuted":
            v[k] = {**tv, "build": "truth", "shipped": shipped}
        else:
            v[k] = {**v[k], "build": "shipped", "truth": tv.get("reason") or tv.get("status")}
    return v


def run(target: Target, functions: list[dict], seed: int, only=None, log=print, cases: int | None = None) -> dict:
    """Witness every lifted function (or the keys in ``only``) against ``target``; returns {key: verdict}."""
    clang, why = E.clang()
    if clang is None:
        raise E.NotFound(why)
    n_cases = cases or CASES
    fns = [f for f in functions if f["status"] == "lifted" and f.get("outputs")
           and (only is None or f["key"] in only)]
    rng = random.Random(seed)
    items = []
    verdicts: dict[str, dict] = {}
    for f in fns:
        if not (all(k in DRAWABLE for _nm, k in f["inputs"])
                and all(o["kind"] in DRAWABLE or o["kind"] == SELF for o in f["outputs"])):
            verdicts[f["key"]] = {"status": "unavailable", "reason": "an input or output is a pointer"}
            continue
        rows, wants, dropped = defined_rows(f, rng, n_cases)
        if not rows:
            verdicts[f["key"]] = {"status": "vacuous", "skipped": dropped, "seed": seed,
                                  "reason": "C++ leaves it undefined on every input drawn"}
            continue
        items.append((len(items), f, rows, wants, dropped))
    for b in range(0, len(items), BATCH):
        batch = items[b:b + BATCH]
        bits = [(i, f, [[to_bits(k, v) for (_nm, k), v in zip(f["inputs"], row)] or [0] for row in rows])
                for i, f, rows, _w, _d in batch]
        exe, rejected = build_harness(target, clang, bits, f"{seed}_{b // BATCH}", log)
        for i, why in rejected.items():
            verdicts[items[i][1]["key"]] = {"status": "unavailable", "reason": why}
        if exe is None:
            log(f"  batch {b // BATCH + 1}/{(len(items) + BATCH - 1) // BATCH}: no harness")
            continue
        live = [i for i, *_ in batch if i not in rejected]
        out, crashed = run_harness(exe, live, cases={i: len(items[i][2]) for i in live})
        for i, f, rows, wants, dropped in batch:
            if i in rejected:
                continue
            if i in crashed:
                verdicts[f["key"]] = {"status": "unavailable", "reason": f"the engine's code {crashed[i]} here"}
                continue
            verdicts[f["key"]] = {**compare(f, rows, out.get(i, []), wants), "seed": seed,
                                  **({"undefined": dropped} if dropped else {})}
        log(f"  batch {b // BATCH + 1}/{(len(items) + BATCH - 1) // BATCH}: {len(live)} run")
    return verdicts


__all__ = ["CASES", "compare", "defined_rows", "evaluate", "from_bits", "run", "to_bits", "ulps"]
