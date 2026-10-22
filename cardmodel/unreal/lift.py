"""lift — a C++ function's meaning as core terms, by symbolic execution of its clang AST.

Values are scalar slots. A record is the list of its scalar slots in layout order (bases first, then fields; an
array expands, a union overlays its members, which must agree slot by slot); a scalar is one slot. Every slot is a
core term over the function's inputs (``["var", "A.X"]``), and its kind is ``f64``, ``f32``, ``b``, or an integer
kind (``i32``, ``u32``, ...). Memory is a set of cells (one per variable or temporary); a reference or a pointer is
a cell, an offset and a length, so writes through references and out-parameters land where C++ puts them.

Execution:
  * a condition that folds to a constant takes one side; a condition on inputs runs both sides and merges every
    slot that differs as ``IF_EXPR``; a return on one side makes the rest of the function conditional on not
    having returned;
  * a loop runs while its condition folds to a constant (unrolled within a budget);
  * a call to a function with a body is inlined (recursion and depth are bounded); a call to the C library
    (sqrt, sin, atan2, floor, fmod, ...) is an atom; anything else is a gap with its cause;
  * conversions are explicit: double -> float is ``F32`` (round to binary32), float -> double is exact, int ->
    float is ``TO_FLOAT``, float -> int is ``TRUNC_INT``, a narrowing or unsigned integer conversion wraps;
    arithmetic in ``float`` is done in double and rounded (exact for + - * / and sqrt), unsigned arithmetic
    wraps, C's truncating division and remainder are written over FLOORDIV and MOD.

The result (``Lifted``) has the inputs (every scalar slot of the parameters and of ``this``), the outputs (the
return value, every slot written through a non-const reference or pointer, and ``this`` for a non-const method),
each as a term, and the named calls the function made (its vocabulary in the engine's own Gödel set).

Honest limits (L1): no pointer arithmetic, unions only where members agree slot by slot (type punning is a gap),
bitfields, lambdas, exceptions and loops whose condition depends on the inputs are gaps; signed integer overflow is
undefined in C++ and assumed absent; ``check`` and ``ensure`` are compiled out (they are diagnostics); the terms are
not simplified beyond constant folding (distill.py normalizes them).
"""
from __future__ import annotations

import math
import re
import struct
from collections import Counter

from .clangast import FUNCS, NULL, Node, has_body

INT_KINDS = {"i8": (8, True), "u8": (8, False), "i16": (16, True), "u16": (16, False), "i32": (32, True),
             "u32": (32, False), "i64": (64, True), "u64": (64, False)}
BUILTIN = {"double": "f64", "long double": "f64", "float": "f32", "bool": "b", "_Bool": "b", "char": "i8",
           "signed char": "i8", "unsigned char": "u8", "short": "i16", "unsigned short": "u16", "int": "i32",
           "unsigned int": "u32", "long": "i64", "unsigned long": "u64", "long long": "i64",
           "unsigned long long": "u64", "char16_t": "u16", "char32_t": "u32", "wchar_t": "i32", "char8_t": "u8",
           # the engine's own integer names, for the places clang does not desugar them
           "uint8": "u8", "int8": "i8", "uint16": "u16", "int16": "i16", "uint32": "u32", "int32": "i32",
           "uint64": "u64", "int64": "i64", "SIZE_T": "u64", "SSIZE_T": "i64", "UPTRINT": "u64", "PTRINT": "i64"}
# C library functions (and clang builtins) that are atoms: name -> (op, arity); an `f` suffix is the float version
LIBM = {"sqrt": ("FSQRT", 1), "sin": ("SIN", 1), "cos": ("COS", 1), "tan": ("TAN", 1), "asin": ("ASIN", 1),
        "acos": ("ACOS", 1), "atan": ("ATAN", 1), "atan2": ("ATAN2", 2), "exp": ("EXP", 1), "exp2": ("EXP2", 1),
        "log": ("LOG", 1), "log2": ("LOG2", 1), "log10": ("LOG10", 1), "floor": ("FLOOR", 1), "ceil": ("CEIL", 1),
        "trunc": ("TRUNC", 1), "round": ("ROUND", 1), "rint": ("RINT", 1), "nearbyint": ("RINT", 1),
        "fmod": ("FMOD", 2), "pow": ("POW", 2), "fabs": ("ABS", 1), "copysign": ("COPYSIGN", 2),
        "fmin": ("FMIN", 2), "fmax": ("FMAX", 2), "isnan": ("ISNAN", 1), "isfinite": ("ISFINITE", 1),
        "isinf": ("ISINF", 1), "sinh": ("SINH", 1), "cosh": ("COSH", 1), "tanh": ("TANH", 1), "cbrt": ("CBRT", 1),
        "hypot": ("HYPOT", 2), "modf": None, "frexp": None, "ldexp": None}
BOOL_ATOMS = ("ISNAN", "ISFINITE", "ISINF")
COMPARE_MACROS = {"isgreater": "CMP_GT", "isgreaterequal": "CMP_GE", "isless": "CMP_LT", "islessequal": "CMP_LE",
                  "isunordered": None, "islessgreater": None}
# bit counting builtins: atoms of the integer domain (undefined at 0 for clz/ctz, as in C)
BITCOUNT = {"clz": ("CLZ32", 1), "clzll": ("CLZ64", 1), "clzl": ("CLZ64", 1), "ctz": ("CTZ32", 1),
            "ctzll": ("CTZ64", 1), "ctzl": ("CTZ64", 1), "popcount": ("POPCOUNT", 1), "popcountll": ("POPCOUNT", 1),
            "popcountl": ("POPCOUNT", 1)}
EXACT_FOLD = ("ADD", "SUB", "MUL", "DIV", "NEG", "F32", "FSQRT", "ABS", "FLOOR", "CEIL", "TRUNC", "FMOD", "COPYSIGN")
CMP = {"<": "CMP_LT", ">": "CMP_GT", "<=": "CMP_LE", ">=": "CMP_GE", "==": "CMP_EQ", "!=": "CMP_NE"}
BITS = {"f32": 32, "f64": 64, "b": 8, **{k: v[0] for k, v in INT_KINDS.items()}}
# reinterpreting the bits of a float as an integer and back: atoms of the bits domain
TO_BITS = {"f32": "F32_BITS", "f64": "F64_BITS"}
FROM_BITS = {"f32": "BITS_F32", "f64": "BITS_F64"}
MAX_STEPS = 200_000
POINTER_SLOTS = 64            # a pointer parameter points into an array of this many scalar slots
MAX_DEPTH = 48
MAX_NODES = 60_000
UNINIT = ["var", "<uninit>"]
# where C++ is undefined: the witness never runs the engine's code there, and any value refines it (emitted code
# takes the other side of the IF_EXPR that leads here)
UNDEFINED_INDEX = ["var", "<undefined: an index outside the object>"]
UNDEFINED_SHIFT = ["var", "<undefined: a shift count outside the operand's width>"]


def undefined(t) -> bool:
    """A leaf where C++ is undefined."""
    return isinstance(t, list) and len(t) == 2 and t[0] == "var" and str(t[1]).startswith("<undefined")


class Gap(Exception):
    """What stops a lift, said precisely: ``cause`` is a short class (it becomes a cause card), ``detail`` the
    specific thing."""

    def __init__(self, cause: str, detail: str = ""):
        super().__init__(f"{cause}: {detail}" if detail else cause)
        self.cause, self.detail = cause, detail


class _Break(Exception):
    pass


class _Continue(Exception):
    pass


# -- scalar helpers -------------------------------------------------------------------------------------------------
def f32(x: float) -> float:
    """Round a double to the nearest binary32 (ties to even), keeping its sign, infinities and NaN."""
    if x != x or x in (math.inf, -math.inf):
        return x
    try:
        return struct.unpack("f", struct.pack("f", x))[0]
    except OverflowError:
        # beyond the largest float: round-to-nearest gives infinity past 2^128 * (1 - 2^-25)
        lim = math.ldexp(1.0 - math.ldexp(1.0, -25), 128)
        return math.copysign(math.inf, x) if abs(x) >= lim else math.copysign(3.4028234663852886e38, x)


def const(t) -> bool:
    return isinstance(t, list) and len(t) == 2 and t[0] in ("int", "float", "bool")


def is_true(t) -> bool:
    return t == ["bool", True]


def is_false(t) -> bool:
    return t == ["bool", False]


def lit(kind: str, v):
    if kind == "b":
        return ["bool", bool(v)]
    if kind in ("f64", "f32"):
        return ["float", float(v)]
    return ["int", int(v)]


def wrap_int(v: int, kind: str) -> int:
    bits, signed = INT_KINDS[kind]
    v &= (1 << bits) - 1
    return v - (1 << bits) if signed and v >> (bits - 1) else v


def _c_div(a: int, b: int) -> int:
    q = abs(a) // abs(b)
    return q if (a < 0) == (b < 0) else -q


def _c_rem(a: int, b: int) -> int:
    return a - b * _c_div(a, b)


def fold(t):
    """Constant folding: exact arithmetic on constants, IF_EXPR on a constant condition, IF_EXPR(c, x, x) -> x."""
    if not isinstance(t, list) or not t or t[0] in ("var", "int", "float", "bool"):
        return t
    head, args = t[0], t[1:]
    if head == "IF_EXPR":
        c, a, b = args
        if is_true(c):
            return a
        if is_false(c):
            return b
        if a == b:
            return a
        if is_true(a) and is_false(b):                  # a condition chosen as a truth value is the condition
            return c
        if is_false(a) and is_true(b):
            return fold(["NOT", c])
        return t
    if head == "AND":
        if any(is_false(x) for x in args):
            return ["bool", False]
        rest = [x for x in args if not is_true(x)]
        return ["bool", True] if not rest else rest[0] if len(rest) == 1 else ["AND", *rest]
    if head == "OR":
        if any(is_true(x) for x in args):
            return ["bool", True]
        rest = [x for x in args if not is_false(x)]
        return ["bool", False] if not rest else rest[0] if len(rest) == 1 else ["OR", *rest]
    if head == "NOT" and len(args) == 1 and isinstance(args[0], list) and args[0][:1] == ["NOT"]:
        return args[0][1]
    if not all(const(a) for a in args):
        return t
    v = [a[1] for a in args]
    try:
        r = _fold_value(head, v, args)
    except (ArithmeticError, ValueError):
        return t
    if r is None:
        return t
    if isinstance(r, bool):
        return ["bool", r]
    if isinstance(r, int):
        return ["int", r]
    return ["float", r]


def _fold_value(head, v, args):
    isf = any(a[0] == "float" for a in args)
    if head == "ADD":
        return float(v[0] + v[1]) if isf else v[0] + v[1]
    if head == "SUB":
        return float(v[0] - v[1]) if isf else v[0] - v[1]
    if head == "MUL":
        return float(v[0] * v[1]) if isf else v[0] * v[1]
    if head == "DIV":
        return v[0] / v[1] if v[1] != 0 else None
    if head == "NEG":
        return -v[0]
    if head == "F32":
        return f32(v[0])
    if head == "FSQRT":
        return math.sqrt(v[0]) if v[0] >= 0 else None
    if head == "ABS":
        return abs(v[0])
    if head == "FLOOR":
        return float(math.floor(v[0])) if math.isfinite(v[0]) else None
    if head == "CEIL":
        return float(math.ceil(v[0])) if math.isfinite(v[0]) else None
    if head == "TRUNC":
        return float(math.trunc(v[0])) if math.isfinite(v[0]) else None
    if head == "FMOD":
        return math.fmod(v[0], v[1]) if v[1] != 0 else None
    if head == "COPYSIGN":
        return math.copysign(v[0], v[1])
    if head == "FLOORDIV":
        return v[0] // v[1] if v[1] != 0 else None
    if head == "MOD":
        return v[0] % v[1] if v[1] != 0 else None
    if head == "TO_FLOAT":
        return float(v[0])
    if head == "TRUNC_INT":
        return int(v[0]) if math.isfinite(v[0]) else None
    if head in ("CMP_LT", "CMP_GT", "CMP_LE", "CMP_GE", "CMP_EQ", "CMP_NE"):
        a, b = v
        return {"CMP_LT": a < b, "CMP_GT": a > b, "CMP_LE": a <= b, "CMP_GE": a >= b, "CMP_EQ": a == b,
                "CMP_NE": a != b}[head]
    if head == "NOT":
        return not v[0]
    if head == "BIT_AND":
        return v[0] & v[1]
    if head == "BIT_OR":
        return v[0] | v[1]
    if head == "BIT_XOR":
        return v[0] ^ v[1]
    if head == "BIT_NOT":
        return ~v[0]
    if head == "SHIFT_LEFT":
        return v[0] << v[1] if 0 <= v[1] < 128 else None
    if head == "SHIFT_RIGHT":
        return v[0] >> v[1] if 0 <= v[1] < 128 else None
    if head == "MIN":
        return min(v[0], v[1])
    if head == "MAX":
        return max(v[0], v[1])
    return None


def mk(head, *args):
    return fold([head, *args])


def size(t) -> int:
    """The number of nodes of a term as a tree. Terms share subterms (a merge reuses both sides), so the tree can
    be exponentially larger than the term in memory: counted once per shared node, iteratively."""
    memo: dict[int, int] = {}
    stack = [(t, False)]
    while stack:
        x, done = stack.pop()
        if not (isinstance(x, list) and x and isinstance(x[0], str) and x[0] not in ("var", "int", "float", "bool")):
            continue
        if id(x) in memo:
            continue
        kids = [a for a in x[1:] if isinstance(a, list)]
        if done:
            memo[id(x)] = 1 + sum(memo.get(id(a), 1) for a in kids) + sum(1 for a in x[1:] if not isinstance(a, list))
        else:
            stack.append((x, True))
            stack.extend((a, False) for a in kids if id(a) not in memo)
    if isinstance(t, list) and id(t) in memo:
        return memo[id(t)]
    return 1


# -- types and layouts ------------------------------------------------------------------------------------------------
class Shape:
    """A type as slots: ``kinds`` (one per scalar slot), ``names`` (a path per slot), and for records the record."""
    __slots__ = ("kinds", "names", "record", "text", "fields")

    def __init__(self, kinds, names, record=None, text="", fields=None):
        self.kinds, self.names, self.record, self.text, self.fields = kinds, names, record, text, fields or {}

    def __len__(self):
        return len(self.kinds)


def _strip(t: str) -> str:
    t = re.sub(r"\b(const|volatile|struct|class|union|enum|typename)\b", " ", t or "")
    t = re.sub(r"\s+", " ", t).strip()
    return t.replace(" <", "<").replace("< ", "<").replace(" >", ">").replace(" ,", ",")


def ref_kind(t: str) -> str | None:
    """'&', '&&', '*' or None for a type string (top level only)."""
    t = (t or "").strip()
    if re.search(r"\(\s*\*\s*\)", t):
        return "fnptr"
    if t.endswith("&&"):
        return "&&"
    if t.endswith("&"):
        return "&"
    if t.endswith("*") or t.endswith("* const") or t.endswith("*const"):
        return "*"
    return None


def pointee(t: str) -> str:
    t = (t or "").strip()
    t = re.sub(r"\*\s*const$", "*", t)
    return t[:-2].strip() if t.endswith("&&") else t[:-1].strip()


class Layouts:
    """Shapes of the types one translation unit uses, from its record declarations."""

    def __init__(self, unit):
        self.unit = unit
        self.cache: dict[str, Shape] = {}
        self.anon_at: dict[tuple, str] = {}
        self.ctx: list[dict] = []                     # alias maps of the records being read (innermost last)
        self.suffix: dict[str, list[str]] = {}
        for q in unit.records:
            self.suffix.setdefault(q.split("::")[-1], []).append(q)

    def record_qual(self, name: str) -> str | None:
        name = _strip(name)
        if name in self.unit.records:
            return name
        canon = _canon_args(name)
        if canon != name:
            got = self.record_qual(canon)
            if got is not None:
                return got
        tail = name.split("::")[-1]
        cands = [q for q in self.suffix.get(tail, []) if q == name or q.endswith("::" + name)]
        if len(cands) == 1:
            return cands[0]
        return None

    def shape(self, t: str, dt: str | None = None) -> Shape:
        key = f"{t}|{dt}|{id(self.ctx[-1]) if self.ctx else 0}"
        if key in self.cache:
            return self.cache[key]
        s = self._shape(dt or t, t)
        self.cache[key] = s
        return s

    def size_align(self, t: str) -> tuple[int, int]:
        """C++'s sizeof and alignof of a type: scalars by width, arrays by count, records with padding to each
        member's alignment, unions as their widest member, alignas where the AST records it."""
        base = _strip(t)
        if ref_kind(t) == "*":
            return 8, 8
        m = re.match(r"^(.*?)\s*((?:\[\d+\])+)$", base)
        if m:
            sz, al = self.size_align(m.group(1))
            for d in re.findall(r"\[(\d+)\]", m.group(2)):
                sz *= int(d)
            return sz, al
        if base in BUILTIN:
            b = BITS[BUILTIN[base]] // 8
            return b, b
        q = self.record_qual(base)
        if q is None:
            for amap in reversed(self.ctx):
                if base in amap and amap[base] != base:
                    return self.size_align(amap[base])
            td = self.unit.typedefs.get(base) or self.unit.typedefs.get(base.split("::")[-1])
            if td and _strip(td) != base:
                return self.size_align(td)
            if self.shape(t).kinds == ["i32"]:
                return 4, 4                                   # an enum
            raise Gap("sizeof", f"of {base}")
        return self._record_size(self.unit.records[q], q)

    def _record_size(self, rec: Node, q: str) -> tuple[int, int]:
        key = f"size:{q}"
        if key in self.cache:
            return self.cache[key]
        self.push(q)
        try:
            union = rec.a.get("tagUsed") == "union"
            off, align = 0, 1
            for b in rec.a.get("bases") or []:
                bq = self.record_qual(b)
                if bq is None:
                    raise Gap("sizeof", f"base {b}")
                bs, ba = self._record_size(self.unit.records[bq], bq)
                off = _round_up(off, ba) + bs
                align = max(align, ba)
            pending = None
            for c in rec.c:
                if c.k == "CXXRecordDecl" and not c.a.get("name") and any(x.k == "FieldDecl" for x in c.c):
                    pending = c
                    continue
                if c.k != "FieldDecl":
                    continue
                if not c.a.get("name") and pending is not None:
                    fs, fa = self._record_size(pending, f"{q}::<anon@{pending.a.get('id')}>")
                    pending = None
                else:
                    fs, fa = self.size_align(c.a.get("dt") or c.a.get("t") or "")
                fa = max(fa, c.a.get("align") or 1)
                align = max(align, fa)
                off = max(off, fs) if union else _round_up(off, fa) + fs
            align = max(align, rec.a.get("align") or 1)
            out = (_round_up(max(off, 1 if not rec.c else off), align), align)
        finally:
            self.pop()
        self.cache[key] = out
        return out

    def aliases_of(self, rq: str | None) -> dict:
        """A record's own names for types: its member typedefs, and its template parameters bound to the
        arguments of this specialization."""
        if not rq:
            return {}
        key = f"aliases:{rq}"
        if key in self.cache:
            return self.cache[key]
        out: dict = {}
        rec = self.unit.records.get(rq)
        if "<" in rq and rq.endswith(">"):
            tname, args = rq[:rq.index("<")], _split_args(rq[rq.index("<") + 1:-1])
            params = self.unit.template_params.get(tname) or []
            out.update({p: a for p, a in zip(params, args) if p})
        for c in (rec.c if rec is not None else ()):
            if c.k in ("TypedefDecl", "TypeAliasDecl") and c.a.get("name"):
                out[c.a["name"]] = c.a.get("dt") or c.a.get("t") or ""
        self.cache[key] = out
        return out

    def push(self, rq: str | None) -> None:
        self.ctx.append(self.aliases_of(rq))

    def local_alias(self, name: str | None, target: str) -> None:
        """A typedef inside a function: it shadows for the rest of that frame (a fresh map, so caches keyed on
        the frame's map never mix two functions' local names)."""
        if not name or not self.ctx:
            return
        top = dict(self.ctx[-1])
        top[name] = target
        self.ctx[-1] = top

    def pop(self) -> None:
        self.ctx.pop()

    def _shape(self, t: str, written: str) -> Shape:
        rk = ref_kind(t)
        if rk == "*":
            return Shape(["ptr"], [""], None, t)
        if rk in ("&", "&&"):
            raise Gap("reference type", f"{t} has no value shape")
        if rk == "fnptr":
            raise Gap("function pointer", t)
        base = _strip(t)
        m = re.match(r"^(.*?)\s*((?:\[\d+\])+)$", base)
        if m:
            inner = self._shape(m.group(1), m.group(1))
            dims = [int(x) for x in re.findall(r"\[(\d+)\]", m.group(2))]
            kinds, names = list(inner.kinds), list(inner.names)
            for d in reversed(dims):
                kinds = kinds * d
                names = [f"[{i}]{n}" for i in range(d) for n in names]
            return Shape(kinds, names, None, base)
        if base in BUILTIN:
            return Shape([BUILTIN[base]], [""], None, base)
        m = re.search(r"\(anonymous (?:struct |union |class )?at (.+?):(\d+):\d+\)", base)
        if m:
            akey = self.anon_at.get((m.group(1), int(m.group(2))))
            if akey is None:
                raise Gap("unknown type", base)
            return self.cache[akey]
        if base in ("void",):
            return Shape([], [], None, base)
        q = self.record_qual(base)
        if q is None:
            for amap in reversed(self.ctx):              # a name the enclosing record gives a type
                if base in amap and amap[base] != base:
                    return self._shape(amap[base], amap[base])
            td = self.unit.typedefs.get(base) or self.unit.typedefs.get(base.split("::")[-1])
            if td and _strip(td) != base:
                return self._shape(td, td)
            tail = base.split("::")[-1]
            under = self.unit.enum_names.get(tail)
            if under is None and tail == "Type" and "::" in base:      # UE's namespaced enums: EAxis::Type
                under = self.unit.enum_names.get("Type")
            if under is not None:
                k = BUILTIN.get(_strip(under), "i32")
                return Shape([k], [""], None, base)
            raise Gap("unknown type", base)
        return self.record_shape(q)

    def record_shape(self, q: str) -> Shape:
        if q in self.cache:
            return self.cache[q]
        rec = self.unit.records[q]
        self.cache[q] = Shape([], [], q, q)               # recursion guard: a record containing itself is a gap
        self.push(q)
        try:
            kinds, names, fields = self._fields(rec, q, "")
        finally:
            self.pop()
        s = Shape(kinds, names, q, q, fields)
        self.cache[q] = s
        return s

    def _fields(self, rec: Node, q: str, prefix: str):
        """(kinds, names, field id -> (offset, Shape)) of a record's slots: its bases, then its fields."""
        kinds, names, fields = [], [], {}
        for b in rec.a.get("bases") or []:
            bq = self.record_qual(b)
            if bq is None:
                raise Gap("unknown type", f"base {b} of {q}")
            bs = self.record_shape(bq)
            fields[f"base:{bq}"] = (len(kinds), bs)
            kinds += bs.kinds
            names += [f"{prefix}{n}" for n in bs.names]
        union = rec.a.get("tagUsed") == "union"
        pending_anon = None
        members = []
        for c in rec.c:
            if c.k == "CXXRecordDecl" and not c.a.get("name") and c.a.get("completeDefinition", True) is not False \
                    and any(x.k == "FieldDecl" for x in c.c):
                pending_anon = c
                continue
            if c.k != "FieldDecl":
                continue
            if c.a.get("isBitfield"):
                raise Gap("bitfield", f"{q}.{c.a.get('name')}")
            if not c.a.get("name") and pending_anon is not None:
                akey = f"{q}::<anon@{pending_anon.a.get('id')}>"
                k2, n2, f2 = self._fields(pending_anon, akey, prefix)
                fs = Shape(k2, n2, akey, "<anon>", f2)
                self.cache[akey] = fs
                self.anon_at[(pending_anon.a.get("file"), pending_anon.a.get("line"))] = akey
                pending_anon = None
            else:
                fs = self.shape(c.a.get("t") or "", c.a.get("dt"))
                nm = c.a.get("name") or ""
                fs = Shape(fs.kinds, [f"{prefix}{nm}{'.' if n and not n.startswith('[') else ''}{n}"
                                      for n in fs.names], fs.record, fs.text, fs.fields)
            members.append((c, fs))
        if union:
            first = members[0][1] if members else Shape([], [], None, "")
            for c, fs in members:
                common = min(len(fs), len(first))
                if fs.kinds[:common] != first.kinds[:common]:
                    # the same bits read as another type: allowed to exist, a gap where it is read
                    fs = Shape(fs.kinds, fs.names, None, f"<punned:{first.text} as {fs.text}>")
                fields[c.a.get("id")] = (len(kinds), fs)
                fields.setdefault(f"name:{c.a.get('name')}", (len(kinds), fs))
                self._inherit(fields, fs, len(kinds))
            kinds += first.kinds
            names += first.names
            return kinds, names, fields
        for c, fs in members:
            fields[c.a.get("id")] = (len(kinds), fs)
            fields.setdefault(f"name:{c.a.get('name')}", (len(kinds), fs))
            self._inherit(fields, fs, len(kinds))
            kinds += fs.kinds
            names += fs.names
        return kinds, names, fields

    @staticmethod
    def _inherit(fields, fs: Shape, off: int) -> None:
        """Anonymous members' fields are reachable from the enclosing record (C++ injects their names)."""
        if fs.text == "<anon>":
            for fid, (o, s) in fs.fields.items():
                fields.setdefault(fid, (off + o, s))

    def field(self, rec_q: str, field_id: str) -> tuple[int, Shape]:
        s = self.cache.get(rec_q) if "<anon@" in rec_q else self.record_shape(rec_q)
        got = s.fields.get(field_id) if s else None
        if got is None and s:
            decl = self.unit.decls.get(field_id)          # an IndirectFieldDecl: the anonymous member's field
            if decl is not None and decl.a.get("name"):
                got = s.fields.get(f"name:{decl.a['name']}")
        if got is None:
            raise Gap("unknown field", f"{rec_q} has no field {field_id}")
        if got[1].text.startswith("<punned:"):
            raise Gap("union type punning", got[1].text[8:-1])
        return got


# -- memory ------------------------------------------------------------------------------------------------------------
class Ref:
    """An lvalue: a cell, an offset into it, and the shape at that place."""
    __slots__ = ("cell", "off", "shape")

    def __init__(self, cell: int, off: int, shape: Shape):
        self.cell, self.off, self.shape = cell, off, shape

    def at(self, off: int, shape: Shape) -> Ref:
        return Ref(self.cell, self.off + off, shape)


class Val:
    """An rvalue: its slots' terms and its shape."""
    __slots__ = ("slots", "shape")

    def __init__(self, slots, shape: Shape):
        self.slots, self.shape = list(slots), shape


class Callee:
    __slots__ = ("decl_id", "name", "this", "kind", "type")

    def __init__(self, decl_id, name, this=None, kind=None, type_=None):
        self.decl_id, self.name, self.this, self.kind, self.type = decl_id, name, this, kind, type_


class State:
    __slots__ = ("mem", "done", "ret")

    def __init__(self, mem, done, ret):
        self.mem, self.done, self.ret = mem, done, ret

    def fork(self) -> State:
        return State({k: list(v) for k, v in self.mem.items()}, self.done, None if self.ret is None else
                     (list(self.ret[0]), self.ret[1]) if isinstance(self.ret, tuple) else self.ret)


class Lifted:
    def __init__(self, fn, inputs, outputs, calls, atoms, notes):
        self.fn, self.inputs, self.outputs, self.calls, self.atoms, self.notes = fn, inputs, outputs, calls, atoms, notes
        self.xcalls: dict = {}


# -- the executor ----------------------------------------------------------------------------------------------------
class Lifter:
    def __init__(self, unit, known_statics: dict | None = None, is_engine_fn=None):
        self.u = unit
        self.L = Layouts(unit)
        self.known_statics = known_statics or {}
        self.is_engine_fn = is_engine_fn or (lambda node: True)
        self.next_cell = 0
        self.steps = 0
        self.stack: list[str] = []
        self.calls: Counter = Counter()
        self.atoms: Counter = Counter()
        self.notes: list[str] = []
        self.cell_kinds: dict[int, list[str]] = {}
        self.xcalls: Counter = Counter()
        self.outer: set[int] = set()      # the lifted function's outputs: this, non-const references and pointers
        self.floors: list[int] = [0]      # per call frame: cells at or below were made before the frame
        self.static_cache: dict[str, Val] = {}

    # cells -----------------------------------------------------------------------------------------------------
    def new_cell(self, st: State, slots, kinds=None) -> int:
        self.next_cell += 1
        st.mem[self.next_cell] = list(slots)
        if kinds is not None:
            self.cell_kinds[self.next_cell] = list(kinds)
        return self.next_cell

    def cell_ref(self, st: State, v, shape: Shape) -> Ref:
        """A new cell holding ``v``'s slots, typed by ``shape``."""
        return Ref(self.new_cell(st, v, shape.kinds), 0, shape)

    def load(self, st: State, r: Ref) -> Val:
        cell = st.mem.get(r.cell)
        if cell is None:
            raise Gap("dangling reference", "a reference outlived its object")
        vals = cell[r.off:r.off + len(r.shape)]
        if len(vals) != len(r.shape):
            raise Gap("array index", "a read outside the object")
        for v in vals:
            if v == ["var", "<uninit>"]:
                raise Gap("uninitialized read", "reads a value the code never set")
        stored = self.cell_kinds.get(r.cell)
        if stored is not None:
            vals = [self.rebits(t, stored[r.off + i], k) for i, (t, k) in enumerate(zip(vals, r.shape.kinds))]
        return Val(vals, r.shape)

    def rebits(self, t, src: str, dst: str):
        """The same bits read as another kind of the same width (a view through a reinterpreting cast)."""
        if src == dst or src == "ptr" or dst == "ptr" or isinstance(t, tuple):
            return t
        if BITS.get(src) != BITS.get(dst):
            raise Gap("bit-level reinterpretation", f"{src} read as {dst} (different widths)")
        if src in INT_KINDS and dst in INT_KINDS:
            return self.convert(Val([t], Shape([src], [""])), Shape([dst], [""])).slots[0]
        if src in TO_BITS:                                    # float -> integer bits
            self.atoms[TO_BITS[src]] += 1
            u = ["u32", "u64"][src == "f64"]
            x = mk(TO_BITS[src], t)
            return self.convert(Val([x], Shape([u], [""])), Shape([dst], [""])).slots[0] if dst != u else x
        if dst in FROM_BITS:                                  # integer bits -> float
            self.atoms[FROM_BITS[dst]] += 1
            u = ["u32", "u64"][dst == "f64"]
            x = self.convert(Val([t], Shape([src], [""])), Shape([u], [""])).slots[0] if src != u else t
            return mk(FROM_BITS[dst], x)
        raise Gap("bit-level reinterpretation", f"{src} read as {dst}")

    def store(self, st: State, r: Ref, v: Val) -> None:
        cell = st.mem[r.cell]
        if len(v.slots) != len(r.shape):
            raise Gap("shape mismatch", f"storing {len(v.slots)} slots into {len(r.shape)}")
        if r.off < 0 or r.off + len(v.slots) > len(cell):
            raise Gap("array index", "a write outside the object")
        stored = self.cell_kinds.get(r.cell)
        if stored is not None:
            v = Val([self.rebits(t, k, stored[r.off + i]) for i, (t, k) in enumerate(zip(v.slots, r.shape.kinds))],
                    v.shape)
        guard = self.guarded(st, r.cell)
        for i, t in enumerate(v.slots):
            old = cell[r.off + i]
            cell[r.off + i] = mk("IF_EXPR", st.done, old, t) if guard and old != UNINIT else t

    def guarded(self, st: State, cell: int) -> bool:
        """A write after a conditional return is itself conditional only where it can be seen after the frame
        returns: the function's outputs, and cells older than the current call. A local of the frame is dead once
        the frame has returned, so its writes need no guard (guarding them would copy terms on every write)."""
        if is_false(st.done):
            return False
        return cell in self.outer or cell <= self.floors[-1]

    def tick(self):
        self.steps += 1
        if self.steps > MAX_STEPS:
            raise Gap("budget", f"more than {MAX_STEPS} steps (a long unrolled loop?)")

    # entry -----------------------------------------------------------------------------------------------------
    def lift(self, fn) -> Lifted:
        self.L.push(self.u.record_name.get(fn.record) if fn.record else None)
        try:
            return self._lift(fn)
        finally:
            self.L.pop()

    def _lift(self, fn) -> Lifted:
        node = fn.node
        st = State({}, ["bool", False], None)
        params = [c for c in node.c if c.k == "ParmVarDecl"]
        env: dict[str, Ref] = {}
        inputs, outs = [], []
        pointer_params: dict = {}
        self.open_cells: set = set()
        this = None
        if node.k in ("CXXMethodDecl", "CXXConstructorDecl", "CXXConversionDecl") and \
                node.a.get("storageClass") != "static" and fn.record:
            rq = self.u.record_name.get(fn.record)
            rshape = self.L.record_shape(self.L.record_qual(rq) or rq)
            if node.k == "CXXConstructorDecl":
                this = Ref(self.new_cell(st, [["var", "<uninit>"]] * len(rshape), rshape.kinds), 0, rshape)
            else:
                this = Ref(self.new_cell(st, [["var", f"this{_dot(n)}"] for n in rshape.names], rshape.kinds), 0, rshape)
                inputs += [(f"this{_dot(n)}", k) for n, k in zip(rshape.names, rshape.kinds)]
            const_method = "const" in (node.a.get("t") or "").rsplit(")", 1)[-1]
            if node.k == "CXXConstructorDecl" or not const_method:
                outs.append(("this", this))
        for i, p in enumerate(params):
            nm = p.a.get("name") or f"arg{i}"
            t = p.a.get("t") or ""
            rk = ref_kind(t)
            if rk in ("&", "&&", "*"):
                inner = pointee(t)
                s = self.L.shape(inner, _pointee_dt(p.a.get("dt")))
                if rk == "*" and _strip(inner) != "void" and len(s):
                    ext = max(1, POINTER_SLOTS // len(s))     # a pointer reads an array: Ptr[0], Ptr[1], ...
                    names = [f"[{j}]{_dot(n)}" for j in range(ext) for n in s.names]
                    kinds = list(s.kinds) * ext
                    env[p.a["id"]] = r = Ref(self.new_cell(st, [["var", f"{nm}{n}"] for n in names], kinds), 0, s)
                    inputs += [(f"{nm}{n}", k) for n, k in zip(names, kinds)]
                    pointer_params[nm] = (r, names, kinds)
                    self.open_cells.add(r.cell)
                else:
                    env[p.a["id"]] = r = Ref(self.new_cell(st, [["var", f"{nm}{_dot(n)}"] for n in s.names],
                                                           s.kinds), 0, s)
                    inputs += [(f"{nm}{_dot(n)}", k) for n, k in zip(s.names, s.kinds)]
                if not inner.startswith("const ") and " const" not in inner.split("<")[0]:
                    outs.append((nm, r))
                if rk == "*":
                    env[p.a["id"]] = Ref(self.new_cell(st, [("ptr", r)]), 0, Shape(["ptr"], [""]))
            elif rk == "fnptr":
                raise Gap("function pointer", f"parameter {nm}")
            else:
                s = self.L.shape(t, p.a.get("dt"))
                env[p.a["id"]] = Ref(self.new_cell(st, [["var", f"{nm}{_dot(n)}"] for n in s.names], s.kinds), 0, s)
                inputs += [(f"{nm}{_dot(n)}", k) for n, k in zip(s.names, s.kinds)]
        body = has_body(node)
        if body is None:
            raise Gap("no body", fn.qual)
        self.outer = {r.cell for _nm, r in outs}
        self.floors = [0]
        self.stack = [node.a.get("id")]
        frame = {"env": env, "this": this, "fn": node, "ret_shape": None}
        ret_t = _return_type(node.a.get("t") or "")
        if node.k == "CXXConstructorDecl":
            self._construct_into(st, node, this, frame)
        else:
            self._exec(st, body, frame)
        outputs = []
        if node.k not in ("CXXConstructorDecl", "CXXDestructorDecl") and ret_t not in ("void", ""):
            if st.ret is None:
                raise Gap("no return", "the function never returns a value")
            rv = st.ret
            if isinstance(rv, Ref):
                if this is not None and rv.cell == this.cell:
                    outputs.append(("return", "&this", None))
                else:
                    v = self.load(st, rv)
                    outputs += [(f"return{_dot(n)}", k, t) for n, k, t in zip(v.shape.names, v.shape.kinds, v.slots)]
            else:
                outputs += [(f"return{_dot(n)}", k, t) for n, k, t in zip(rv.shape.names, rv.shape.kinds, rv.slots)]
        for nm, r in outs:
            if nm in pointer_params:
                pr, names, kinds = pointer_params[nm]
                for n, k, t in zip(names, kinds, st.mem[pr.cell]):
                    if t != UNINIT and t != ["var", f"{nm}{n}"]:
                        outputs.append((f"{nm}{n}", k, t))
                continue
            v = self.load(st, r) if nm != "this" or node.k != "CXXConstructorDecl" else Val(st.mem[r.cell], r.shape)
            for n, k, t in zip(r.shape.names, r.shape.kinds, v.slots):
                if t == ["var", "<uninit>"]:
                    continue
                if t != ["var", f"{nm}{_dot(n)}"]:
                    outputs.append((f"{nm}{_dot(n)}", k, t))
        for name, k, t in outputs:
            if t is not None and size(t) > MAX_NODES:
                raise Gap("term too large", f"{name} has {size(t)} nodes")
        outputs = [(n_, k, t) for n_, k, t in outputs if t != UNINIT]       # padding the code never sets
        for name, k, t in outputs:
            if t is not None and _has_uninit(t):
                raise Gap("uninitialized read", f"{name} depends on a value the code never set")
            if t is not None and _has_ptr(t):
                raise Gap("pointer", f"{name} is a pointer")
        out = Lifted(fn, inputs, outputs, Counter(self.calls), Counter(self.atoms), sorted(set(self.notes)))
        out.xcalls = dict(self.xcalls)
        return out

    # statements --------------------------------------------------------------------------------------------------
    def _exec(self, st: State, s: Node, fr) -> None:
        self.tick()
        if is_true(st.done):
            return
        k = s.k
        if k == "CompoundStmt":
            for c in s.c:
                self._exec(st, c, fr)
                if is_true(st.done):
                    return
            return
        if k in ("NullStmt", "<null>"):
            return
        if k == "AttributedStmt":
            for c in s.c:
                self._exec(st, c, fr)
            return
        if k == "DeclStmt":
            for d in s.c:
                if d.k == "VarDecl":
                    self._declare(st, d, fr)
                elif d.k in ("TypedefDecl", "TypeAliasDecl"):
                    self.L.local_alias(d.a.get("name"), d.a.get("dt") or d.a.get("t") or "")
                elif d.k in ("UsingDecl", "StaticAssertDecl", "CXXRecordDecl", "UsingDirectiveDecl", "UsingShadowDecl"):
                    continue
                else:
                    raise Gap("unsupported declaration", d.k)
            return
        if k == "ReturnStmt":
            if not s.c:
                self._return(st, None)
                return
            e = s.c[0]
            ret_t = _return_type(fr["fn"].a.get("t") or "")
            if ref_kind(ret_t) in ("&", "&&") and pointee(ret_t).startswith("const ") and \
                    fr["fn"].a.get("name") not in ("operator=",):
                self._return(st, self.rvalue(st, e, fr))
            elif ref_kind(ret_t) in ("&", "&&"):
                try:
                    self._return(st, self.lvalue(st, e, fr))
                except Gap as g:
                    if g.cause != "array index" or not pointee(ret_t).startswith("const "):
                        raise
                    self._return(st, self.rvalue(st, e, fr))      # a const reference read through a selection
            else:
                self._return(st, self.rvalue(st, e, fr))
            return
        if k == "IfStmt":
            self._if(st, s, fr)
            return
        if k in ("ForStmt", "WhileStmt", "DoStmt", "CXXForRangeStmt"):
            self._loop(st, s, fr)
            return
        if k == "BreakStmt":
            if not is_false(st.done):
                raise Gap("control flow", "break after a conditional return")
            raise _Break()
        if k == "ContinueStmt":
            if not is_false(st.done):
                raise Gap("control flow", "continue after a conditional return")
            raise _Continue()
        if k == "SwitchStmt":
            self._switch(st, s, fr)
            return
        if k in ("CXXTryStmt", "CXXThrowExpr"):
            raise Gap("exceptions", k)
        if k in ("GotoStmt", "LabelStmt", "IndirectGotoStmt"):
            raise Gap("control flow", k)
        if k == "GCCAsmStmt" or k == "MSAsmStmt":
            raise Gap("inline assembly", k)
        self.eval_effect(st, s, fr)

    def _return(self, st: State, v) -> None:
        if is_false(st.done) or st.ret is None:
            st.ret = v
        elif isinstance(v, Val) and isinstance(st.ret, Val):
            st.ret = Val([mk("IF_EXPR", st.done, a, b) for a, b in zip(st.ret.slots, v.slots)], v.shape)
        elif not (isinstance(v, Ref) and isinstance(st.ret, Ref) and v.cell == st.ret.cell and v.off == st.ret.off):
            raise Gap("control flow", "a reference returned on some paths only")
        st.done = ["bool", True]

    def _declare(self, st: State, d: Node, fr) -> None:
        t = d.a.get("t") or ""
        init = next((c for c in d.c if c.k != "<null>"), None) if d.a.get("init") else None
        rk = ref_kind(t)
        if d.a.get("storageClass") == "static" and not d.a.get("constexpr") and "const" not in t:
            raise Gap("static state", f"a static local {d.a.get('name')}")
        if rk in ("&", "&&"):
            if init is None:
                raise Gap("reference without initializer", d.a.get("name") or "")
            fr["env"][d.a["id"]] = self.lvalue(st, init, fr)
            return
        if rk == "*":
            if init is None:
                raise Gap("pointer", "an uninitialized pointer")
            p = self.rvalue(st, init, fr)
            fr["env"][d.a["id"]] = Ref(self.new_cell(st, p.slots, p.shape.kinds), 0, p.shape)
            return
        s = self.L.shape(t, d.a.get("dt"))
        r = Ref(self.new_cell(st, [["var", "<uninit>"]] * len(s), s.kinds), 0, s)
        fr["env"][d.a["id"]] = r
        if init is not None:
            self.init_into(st, r, init, fr)

    def _if(self, st: State, s: Node, fr) -> None:
        if "pre" in s.a:
            cond, then, els = s.a["pre"], s.c[0], s.c[1]
            return self._branch(st, cond, then, els, fr)
        kids = list(s.c)
        i = 0
        if s.a.get("hasInit"):
            self._exec(st, kids[i], fr)
            i += 1
        if s.a.get("hasVar"):
            self._exec(st, Node("DeclStmt", {}, (kids[i],)), fr)
            i += 1
        cond = self.cond(st, kids[i], fr)
        then = kids[i + 1]
        els = kids[i + 2] if s.a.get("hasElse") and len(kids) > i + 2 else None
        self._branch(st, cond, then, els, fr)

    def _branch(self, st: State, cond, then: Node, els: Node | None, fr) -> None:
        if is_true(cond):
            self._exec(st, then, fr)
            return
        if is_false(cond):
            if els is not None:
                self._exec(st, els, fr)
            return
        a, b = st.fork(), st.fork()
        self._exec(a, then, fr)
        if els is not None:
            self._exec(b, els, fr)
        self._merge(st, cond, a, b)

    def _merge(self, st: State, cond, a: State, b: State) -> None:
        """Join the two sides of a condition: every slot, the `done` flag and the return value become
        IF_EXPR(cond, then-side, else-side) where they differ."""
        mem = {}
        for cell in set(a.mem) | set(b.mem):
            x, y = a.mem.get(cell), b.mem.get(cell)
            if x is None or y is None:
                mem[cell] = x if y is None else y
                continue
            mem[cell] = [p if p is q or p == q else mk("IF_EXPR", cond, p, q) for p, q in zip(x, y)]
        st.mem.clear()
        st.mem.update(mem)
        st.done = mk("IF_EXPR", cond, a.done, b.done)
        ra, rb = a.ret, b.ret
        if ra is None or rb is None:
            st.ret = ra if rb is None else rb
            return
        if isinstance(ra, Val) and isinstance(rb, Val):
            st.ret = Val([p if p == q else mk("IF_EXPR", cond, p, q) for p, q in zip(ra.slots, rb.slots)], ra.shape)
            return
        if isinstance(ra, Ref) and isinstance(rb, Ref) and ra.cell == rb.cell and ra.off == rb.off:
            st.ret = ra
            return
        raise Gap("control flow", "different references returned on two paths")

    def _switch(self, st: State, s: Node, fr) -> None:
        """A switch: on a constant, run from the matching label until a break; on the inputs, a chain of
        conditions, one per group of labels, when no group falls through into the next."""
        kids = [c for c in s.c if c.k != "<null>"]
        if s.a.get("hasInit") or s.a.get("hasVar") or len(kids) != 2 or kids[1].k != "CompoundStmt":
            raise Gap("switch", "a switch with an initializer or without a block")
        cv = self.rvalue(st, kids[0], fr)
        c = cv.slots[0]
        segs: list[tuple[list, bool, list[Node]]] = []      # (case values, has default, statements)
        for x in kids[1].c:
            labels, dflt = [], False
            while x.k in ("CaseStmt", "DefaultStmt"):
                if x.k == "CaseStmt":
                    ce = x.c[0]
                    if "value" not in ce.a:
                        raise Gap("switch", "a case label without a constant value")
                    labels.append(int(ce.a["value"]))
                    x = x.c[-1]
                else:
                    dflt = True
                    x = x.c[0]
            if labels or dflt:
                segs.append((labels, dflt, [x]))
            elif segs:
                segs[-1][2].append(x)
            else:
                raise Gap("switch", "statements before the first label")
        if const(c):
            start = next((i for i, (ls, _d, _b) in enumerate(segs) if c[1] in ls), None)
            if start is None:
                start = next((i for i, (_l, d, _b) in enumerate(segs) if d), None)
            if start is None:
                return
            try:
                for _ls, _d, body in segs[start:]:
                    for stmt in body:
                        self._exec(st, stmt, fr)
                        if is_true(st.done):
                            return
            except _Break:
                pass
            return
        chain = []
        for ls, d, body in segs:
            ends = body[-1].k if body else None
            if ends == "BreakStmt":
                body = body[:-1]
            elif ends != "ReturnStmt":
                raise Gap("switch", "a case that falls through into the next")
            cond = ["bool", False]
            for v in ls:
                cond = mk("OR", cond, mk("CMP_EQ", c, lit(cv.shape.kinds[0], v)))
            chain.append((cond, d, Node("CompoundStmt", {}, tuple(body))))
        default = next((b for _c, d, b in chain if d), None)
        node = default if default is not None else Node("NullStmt", {}, ())
        for cond, d, body in reversed([x for x in chain if not x[1]]):
            node = _IfNode(cond, body, node)
        try:
            self._exec(st, node, fr)
        except _Break:
            raise Gap("switch", "a break nested inside a case") from None

    def _loop(self, st: State, s: Node, fr) -> None:
        k = s.k
        if k == "CXXForRangeStmt":
            raise Gap("loop", "a range-for over a container")
        kids = list(s.c)
        if k == "ForStmt":
            init, _cv, cond, inc, body = (kids + [NULL] * 5)[:5]
            if init.k != "<null>":
                self._exec(st, init, fr)
        elif k == "WhileStmt":
            cond, body, inc = kids[0], kids[1], NULL
        else:
            body, cond, inc = kids[0], kids[1], NULL
        first = True
        while True:
            self.tick()
            if not (k == "DoStmt" and first):
                if cond.k != "<null>":
                    c = self.cond(st, cond, fr)
                    if not (is_true(c) or is_false(c)):
                        raise Gap("loop", "its condition depends on the inputs (no closed form here)")
                    if is_false(c):
                        return
            first = False
            try:
                self._exec(st, body, fr)
            except _Break:
                return
            except _Continue:
                pass
            if is_true(st.done):
                return
            if inc.k != "<null>":
                self.eval_effect(st, inc, fr)

    # expressions ---------------------------------------------------------------------------------------------------
    def eval_effect(self, st: State, e: Node, fr) -> None:
        k = e.k
        if k in ("ExprWithCleanups", "ParenExpr", "ConstantExpr", "CXXBindTemporaryExpr", "MaterializeTemporaryExpr"):
            for c in e.c:
                self.eval_effect(st, c, fr)
            return
        if k in ("ImplicitCastExpr", "CStyleCastExpr", "CXXStaticCastExpr", "CXXFunctionalCastExpr") \
                and e.a.get("castKind") == "ToVoid":
            self.eval_effect(st, e.c[0], fr)
            return
        if k == "BinaryOperator" and e.a.get("opcode") == ",":
            self.eval_effect(st, e.c[0], fr)
            self.eval_effect(st, e.c[1], fr)
            return
        if k in ("BinaryOperator", "CompoundAssignOperator", "UnaryOperator", "CallExpr", "CXXMemberCallExpr",
                 "CXXOperatorCallExpr", "CXXConstructExpr", "CXXTemporaryObjectExpr", "ConditionalOperator"):
            t = e.a.get("t") or ""
            if k in ("CallExpr", "CXXMemberCallExpr", "CXXOperatorCallExpr") and _strip(t) == "void":
                self.call_expr(st, e, fr)
                return
            if e.a.get("valueCategory") == "lvalue":
                self.lvalue(st, e, fr)
            else:
                self.rvalue(st, e, fr)
            return
        if k in ("DeclRefExpr", "IntegerLiteral", "FloatingLiteral", "CXXBoolLiteralExpr", "MemberExpr",
                 "StringLiteral", "UnaryExprOrTypeTraitExpr"):
            return
        raise Gap("unsupported expression", f"{k} as a statement")

    def cond(self, st: State, e: Node, fr):
        v = self.rvalue(st, e, fr)
        if len(v.slots) != 1:
            raise Gap("shape mismatch", "a condition with several slots")
        return self.to_bool(v.slots[0], v.shape.kinds[0])

    def to_bool(self, t, kind):
        if kind == "b":
            return t
        if kind in ("f64", "f32"):
            return mk("CMP_NE", t, ["float", 0.0])
        if kind == "ptr":
            return ["bool", True]
        return mk("CMP_NE", t, ["int", 0])

    def rvalue(self, st: State, e: Node, fr) -> Val:
        self.tick()
        k = e.k
        if k in ("ParenExpr", "ExprWithCleanups", "CXXBindTemporaryExpr", "ConstantExpr",
                 "SubstNonTypeTemplateParmExpr", "CXXFunctionalCastExpr") and \
                not (k == "CXXFunctionalCastExpr" and e.a.get("castKind") not in ("NoOp", "ConstructorConversion",
                                                                                   None)):
            if k == "ConstantExpr" and "value" in e.a and _strip(e.a.get("t") or "") in BUILTIN:
                kind = BUILTIN[_strip(e.a.get("t"))]
                return Val([lit(kind, _num(e.a["value"], kind))], Shape([kind], [""]))
            return self.rvalue(st, e.c[0], fr)
        if k == "MaterializeTemporaryExpr":
            return self.rvalue(st, e.c[0], fr)
        if k in ("ImplicitCastExpr", "CStyleCastExpr", "CXXStaticCastExpr", "CXXFunctionalCastExpr",
                 "CXXConstCastExpr", "CXXReinterpretCastExpr"):
            return self.cast(st, e, fr)
        if k == "IntegerLiteral":
            kind = self.kind(e)
            return Val([lit(kind, int(e.a["value"]))], Shape([kind], [""]))
        if k == "CharacterLiteral":
            kind = self.kind(e)
            return Val([lit(kind, int(e.a["value"]))], Shape([kind], [""]))
        if k == "FloatingLiteral":
            kind = self.kind(e)
            v = float(e.a["value"])
            return Val([lit(kind, f32(v) if kind == "f32" else v)], Shape([kind], [""]))
        if k == "CXXBoolLiteralExpr":
            return Val([["bool", bool(e.a.get("value"))]], Shape(["b"], [""]))
        if k in ("CXXScalarValueInitExpr", "ImplicitValueInitExpr"):
            s = self.shape_of(e)
            return Val([lit(kk, 0) for kk in s.kinds], s)
        if k == "ArraySubscriptExpr":
            return self._select(st, e, fr)
        if k in ("DeclRefExpr", "MemberExpr", "CXXThisExpr"):
            if k == "DeclRefExpr" and (e.a.get("ref") or (None, None))[1] == "EnumConstantDecl":
                return self.enum_value(e)
            if k == "CXXThisExpr":
                return Val([("ptr", fr["this"])], Shape(["ptr"], [""]))
            return self.load(st, self.lvalue(st, e, fr))
        if k == "UnaryOperator":
            return self.unary(st, e, fr)
        if k == "BinaryOperator":
            return self.binary(st, e, fr)
        if k == "CompoundAssignOperator":
            r = self.compound(st, e, fr)
            return self.load(st, r)
        if k == "ConditionalOperator":
            c = self.cond(st, e.c[0], fr)
            if is_true(c):
                return self.rvalue(st, e.c[1], fr)
            if is_false(c):
                return self.rvalue(st, e.c[2], fr)
            a, b = st.fork(), st.fork()
            va, vb = self.rvalue(a, e.c[1], fr), self.rvalue(b, e.c[2], fr)
            self._merge(st, c, a, b)
            return Val([p if p == q else mk("IF_EXPR", c, p, q) for p, q in zip(va.slots, vb.slots)], va.shape)
        if k in ("CallExpr", "CXXMemberCallExpr", "CXXOperatorCallExpr"):
            r = self.call_expr(st, e, fr)
            if isinstance(r, Ref):
                return self.load(st, r)
            if r is None:
                raise Gap("void value", "a void call used as a value")
            return r
        if k in ("CXXConstructExpr", "CXXTemporaryObjectExpr"):
            s = self.shape_of(e)
            r = Ref(self.new_cell(st, [["var", "<uninit>"]] * len(s), s.kinds), 0, s)
            self.construct(st, r, e, fr)
            return Val(st.mem[r.cell], s)
        if k == "InitListExpr":
            s = self.shape_of(e)
            r = Ref(self.new_cell(st, [["var", "<uninit>"]] * len(s), s.kinds), 0, s)
            self.init_list(st, r, e, fr)
            return Val(st.mem[r.cell], s)
        if k == "CXXRewrittenBinaryOperator" and e.c:
            return self.rvalue(st, e.c[0], fr)
        if k == "ArrayInitLoopExpr":
            src = next((c for c in e.c if c.k == "OpaqueValueExpr"), None)
            if src is None or not src.c:
                raise Gap("unsupported expression", "an array copy without its source")
            v = self.load(st, self.lvalue(st, src.c[0], fr))
            return Val(v.slots, self.shape_of(e))
        if k == "OpaqueValueExpr" and e.c:
            return self.rvalue(st, e.c[0], fr)
        if k == "CXXDefaultArgExpr":
            raise Gap("default argument", "outside a call")
        if k == "UnaryExprOrTypeTraitExpr":
            nm = e.a.get("name")
            at = e.a.get("argType")
            t = (at.get("desugaredQualType") or at.get("qualType")) if isinstance(at, dict) else None
            if t is None and e.c:
                t = e.c[0].a.get("dt") or e.c[0].a.get("t")
            if nm not in ("sizeof", "alignof", "__alignof") or not t:
                raise Gap("sizeof", f"{nm} of an expression")
            size, align = self.L.size_align(t)
            kind = self.kind(e)
            return Val([lit(kind, size if nm == "sizeof" else align)], Shape([kind], [""]))
        if k == "BuiltinBitCastExpr":
            return self.bitcast_value(self.rvalue(st, e.c[0], fr), self.shape_of(e))
        if k in ("TypeTraitExpr", "CXXNoexceptExpr") and "value" in e.a:
            return Val([["bool", bool(e.a["value"])]], Shape(["b"], [""]))
        if k == "LambdaExpr":
            raise Gap("lambda", "a lambda expression")
        if k in ("CXXNullPtrLiteralExpr", "GNUNullExpr"):
            raise Gap("pointer", "a null pointer")
        if k == "StringLiteral":
            raise Gap("string", "a string literal")
        raise Gap("unsupported expression", k)

    def kind(self, e: Node) -> str:
        s = self.shape_of(e)
        if len(s) != 1:
            raise Gap("shape mismatch", f"expected a scalar, got {s.text}")
        return s.kinds[0]

    def shape_of(self, e: Node) -> Shape:
        t = e.a.get("t") or ""
        rk = ref_kind(t)
        if rk in ("&", "&&"):
            t = pointee(t)
        return self.L.shape(t, e.a.get("dt"))

    def enum_value(self, e: Node) -> Val:
        did = e.a["ref"][0]
        if did in self.u.enum_values:
            s = self.shape_of(e)
            return Val([lit(s.kinds[0], self.u.enum_values[did])], s)
        raise Gap("unknown enum", f"{e.a['ref'][2]} has no recorded value")

    # lvalues -------------------------------------------------------------------------------------------------------
    def lvalue(self, st: State, e: Node, fr) -> Ref:
        self.tick()
        k = e.k
        if k in ("ParenExpr", "ExprWithCleanups", "CXXBindTemporaryExpr", "ConstantExpr"):
            return self.lvalue(st, e.c[0], fr)
        if k == "MaterializeTemporaryExpr":
            inner = e.c[0]
            if inner.a.get("valueCategory") == "lvalue":
                return self.lvalue(st, inner, fr)
            v = self.rvalue(st, inner, fr)
            return Ref(self.new_cell(st, v.slots, v.shape.kinds), 0, v.shape)
        if k in ("ImplicitCastExpr", "CStyleCastExpr", "CXXStaticCastExpr", "CXXConstCastExpr",
                 "CXXFunctionalCastExpr"):
            ck = e.a.get("castKind")
            if ck in ("NoOp", "LValueToRValue") or ck is None:
                return self.lvalue(st, e.c[0], fr)
            if ck in ("DerivedToBase", "UncheckedDerivedToBase"):
                r = self.lvalue(st, e.c[0], fr)
                return self.base_of(r, e)
            if ck == "LValueBitCast":
                return self.view(self.lvalue(st, e.c[0], fr), e)
            if ck == "BaseToDerived":
                return self.derived_of(st, self.lvalue(st, e.c[0], fr), e)
            raise Gap("cast", f"{ck} on an lvalue")
        if k == "DeclRefExpr":
            ref = e.a.get("ref") or (None, None, None, None)
            if ref[0] in fr["env"]:
                r = fr["env"][ref[0]]
                return r
            if ref[1] == "VarDecl":
                return self.static_ref(st, ref)
            raise Gap("unknown variable", f"{ref[2]} ({ref[1]})")
        if k == "CXXThisExpr":
            if fr["this"] is None:
                raise Gap("this", "no object")
            return fr["this"]
        if k == "MemberExpr":
            base = e.c[0]
            if e.a.get("isArrow"):
                pv = self.rvalue(st, base, fr)
                br = self._deref(pv)
            elif base.a.get("valueCategory") == "prvalue" and base.k != "CXXThisExpr":
                v = self.rvalue(st, base, fr)
                br = Ref(self.new_cell(st, v.slots, v.shape.kinds), 0, v.shape)
            else:
                br = self.lvalue(st, base, fr)
            mid = e.a.get("mref")
            decl = self.u.decls.get(mid)
            if decl is not None and decl.k == "VarDecl":                 # a static member through an object
                return self.static_ref(st, (mid, "VarDecl", decl.a.get("name"), decl.a.get("t")))
            rq = br.shape.record
            if rq is None:
                raise Gap("member of a non-record", f"{e.a.get('name')} of {br.shape.text}")
            off, fs = self.L.field(rq, mid)
            return br.at(off, fs)
        if k == "ArraySubscriptExpr":
            base, idx = e.c[0], e.c[1]
            pv = self.rvalue(st, base, fr)
            arr = self._deref(pv)
            iv = self.rvalue(st, idx, fr).slots[0]
            if iv[0] != "int":
                raise Gap("array index", "an index that depends on the inputs")
            es = self.shape_of(e)
            off = iv[1] * len(es)
            cell = st.mem.get(arr.cell) or []
            if off < 0 or arr.off + off + len(es) > len(cell):
                raise Gap("array index", f"index {iv[1]} outside the object")
            return Ref(arr.cell, arr.off + off, es)
        if k == "UnaryOperator" and e.a.get("opcode") == "*":
            return self._deref(self.rvalue(st, e.c[0], fr))
        if k == "UnaryOperator" and e.a.get("opcode") in ("++", "--") and not e.a.get("isPostfix"):
            r = self.lvalue(st, e.c[0], fr)
            self._incdec(st, r, e.a["opcode"])
            return r
        if k == "BinaryOperator" and e.a.get("opcode") == "=":
            return self.assign(st, e, fr)
        if k == "BinaryOperator" and e.a.get("opcode") == ",":
            self.eval_effect(st, e.c[0], fr)
            return self.lvalue(st, e.c[1], fr)
        if k == "CompoundAssignOperator":
            return self.compound(st, e, fr)
        if k in ("CallExpr", "CXXMemberCallExpr", "CXXOperatorCallExpr"):
            r = self.call_expr(st, e, fr)
            if isinstance(r, Ref):
                return r
            if isinstance(r, Val):
                return Ref(self.new_cell(st, r.slots, r.shape.kinds), 0, r.shape)
            raise Gap("void value", "a void call used as an object")
        if k == "ConditionalOperator":
            c = self.cond(st, e.c[0], fr)
            if is_true(c):
                return self.lvalue(st, e.c[1], fr)
            if is_false(c):
                return self.lvalue(st, e.c[2], fr)
            a, b = st.fork(), st.fork()
            ra, rb = self.lvalue(a, e.c[1], fr), self.lvalue(b, e.c[2], fr)
            va, vb = self.load(a, ra), self.load(b, rb)
            self._merge(st, c, a, b)
            # an object chosen on the inputs: read through a merged copy (a write through it would be lost)
            return Ref(self.new_cell(st, [p if p == q else mk("IF_EXPR", c, p, q)
                                          for p, q in zip(va.slots, vb.slots)], va.shape.kinds), 0, va.shape)
        if k in ("CXXConstructExpr", "CXXTemporaryObjectExpr", "InitListExpr", "CXXFunctionalCastExpr"):
            v = self.rvalue(st, e, fr)
            return Ref(self.new_cell(st, v.slots, v.shape.kinds), 0, v.shape)
        raise Gap("unsupported lvalue", k)

    def _select(self, st: State, e: Node, fr) -> Val:
        """``A[i]`` read (the base, then the index, each evaluated once). A constant index reads its element; an
        index on the inputs is IF_EXPR over every element of the object it can name, and an index outside the object
        is undefined in C++: the leaf UNDEFINED_INDEX (the witness never runs the engine's code there; emitted code
        may read anything there). Into a pointer parameter's array, whose length is the caller's, it is a gap."""
        arr = self._deref(self.rvalue(st, e.c[0], fr))
        iv = self.rvalue(st, e.c[1], fr).slots[0]
        es = self.shape_of(e)
        w = max(1, len(es))
        cell = st.mem.get(arr.cell) or []
        if iv[0] == "int":
            off = iv[1] * len(es)
            if arr.off + off < 0 or arr.off + off + len(es) > len(cell):
                raise Gap("array index", f"index {iv[1]} outside the object")
            return self.load(st, Ref(arr.cell, arr.off + off, es))
        if arr.cell in self.open_cells:
            raise Gap("array index", "an index on the inputs into an array whose length is the caller's")
        lo, hi = -(arr.off // w), (len(cell) - arr.off) // w
        if hi - lo < 1 or hi - lo > 64:
            raise Gap("array index", "an index that depends on the inputs, over an object too large to select")
        out = [UNDEFINED_INDEX] * len(es)
        for j in range(hi - 1, lo - 1, -1):
            el = self.load(st, Ref(arr.cell, arr.off + j * len(es), es)).slots
            c = mk("CMP_EQ", iv, ["int", j])
            out = [mk("IF_EXPR", c, a, b) for a, b in zip(el, out)]
        self.notes.append("select: an index on the inputs")
        return Val(out, es)

    def view(self, r: Ref, e: Node) -> Ref:
        """``reinterpret_cast<U&>(x)``: the same storage, read as U."""
        t = e.a.get("dt") or e.a.get("t") or ""
        return Ref(r.cell, r.off, self.L.shape(pointee(t) if ref_kind(t) in ("&", "&&") else t))

    def bitcast_value(self, v: Val, target: Shape) -> Val:
        """``BitCast<To>(From)`` / ``std::bit_cast``: the same bits as another type, slot by slot."""
        if len(v.slots) != len(target):
            raise Gap("bit-level reinterpretation", f"{v.shape.text} as {target.text} (different slot counts)")
        return Val([self.rebits(t, a, b) for t, a, b in zip(v.slots, v.shape.kinds, target.kinds)], target)

    def memcpy(self, st: State, args: list[Node], fr):
        """Memcpy(dst, src, n) between two objects whose slots pair up by width: a bitwise copy."""
        if len(args) != 3:
            raise Gap("memory", "a memcpy with other arguments")
        dst = self._deref(self.rvalue(st, args[0], fr))
        src = self._deref(self.rvalue(st, args[1], fr))
        n = self.rvalue(st, args[2], fr).slots[0]
        if not const(n):
            raise Gap("memory", "a memcpy of a size that depends on the inputs")
        dk, sk = self._kinds_at(st, dst), self._kinds_at(st, src)
        dn, sn, db, sb = 0, 0, 0, 0
        pairs = []
        while db < n[1] * 8:
            if dn >= len(dk) or sn >= len(sk) or BITS[dk[dn]] != BITS[sk[sn]]:
                raise Gap("bit-level reinterpretation", "a memcpy between slots of different widths")
            pairs.append((dn, sn))
            db += BITS[dk[dn]]
            sb += BITS[sk[sn]]
            dn += 1
            sn += 1
        cells, cellr = st.mem[src.cell], st.mem[dst.cell]
        for d_i, s_i in pairs:
            t = cells[src.off + s_i]
            v = self.rebits(t, sk[s_i], dk[d_i])
            old = cellr[dst.off + d_i]
            guard = self.guarded(st, dst.cell)
            cellr[dst.off + d_i] = mk("IF_EXPR", st.done, old, v) if guard and old != UNINIT else v
        return ("ptr", dst)

    def memset(self, st: State, name: str, args: list[Node], fr):
        """Memzero(p, n) / Memset(p, v, n): constant sizes, slots set to the byte pattern's value (0 only)."""
        dst = self._deref(self.rvalue(st, args[0], fr))
        if name == "Memzero":
            if len(args) != 2:
                raise Gap("memory", "Memzero with other arguments")
            n, v = self.rvalue(st, args[1], fr).slots[0], ["int", 0]
        else:
            if len(args) != 3:
                raise Gap("memory", f"{name} with other arguments")
            v, n = self.rvalue(st, args[1], fr).slots[0], self.rvalue(st, args[2], fr).slots[0]
        if not (const(n) and v == ["int", 0]):
            raise Gap("memory", f"{name} of a size or byte that depends on the inputs")
        kinds = self._kinds_at(st, dst)
        bits, i = 0, 0
        while bits < n[1] * 8:
            if i >= len(kinds):
                raise Gap("array index", f"{name} past the object")
            self.store(st, Ref(dst.cell, dst.off + i, Shape([kinds[i]], [""])), Val([lit(kinds[i], 0)],
                                                                                     Shape([kinds[i]], [""])))
            bits += BITS.get(kinds[i], 64)
            i += 1
        return ("ptr", dst)

    def _kinds_at(self, st: State, r: Ref) -> list[str]:
        stored = self.cell_kinds.get(r.cell)
        n = len(st.mem[r.cell]) - r.off
        if stored is not None:
            return stored[r.off:r.off + n]
        return list(r.shape.kinds) + [r.shape.kinds[-1]] * max(0, n - len(r.shape.kinds)) if r.shape.kinds else []

    def _deref(self, pv: Val) -> Ref:
        if len(pv.slots) == 1 and isinstance(pv.slots[0], tuple) and pv.slots[0][0] == "ptr":
            return pv.slots[0][1]
        raise Gap("pointer", "a pointer the lifter cannot follow")

    def base_of(self, r: Ref, e: Node, tt: str | None = None) -> Ref:
        tt = tt or e.a.get("dt") or e.a.get("t") or ""
        target = self.L.record_qual(pointee(tt) if ref_kind(tt) else tt)
        if target is None or r.shape.record is None:
            raise Gap("cast", f"a base class that is not a record ({r.shape.text} -> {tt})")
        key = f"base:{target}"
        s = self.L.record_shape(r.shape.record)
        if key in s.fields:
            off, bs = s.fields[key]
            return r.at(off, bs)
        for k2, (off, bs) in s.fields.items():      # an indirect base: through the direct one
            if k2.startswith("base:") and bs.record:
                sub = self.L.record_shape(bs.record)
                if key in sub.fields:
                    o2, b2 = sub.fields[key]
                    return r.at(off + o2, b2)
        raise Gap("cast", f"{target} is not a base of {r.shape.record}")

    def derived_of(self, st: State, r: Ref, e: Node) -> Ref:
        tt = e.a.get("dt") or e.a.get("t") or ""
        dq = self.L.record_qual(pointee(tt) if ref_kind(tt) else tt)
        if dq is None or r.shape.record is None:
            raise Gap("cast", f"a derived class that is not a record ({tt})")
        ds = self.L.record_shape(dq)
        key = f"base:{r.shape.record}"
        if key not in ds.fields:
            raise Gap("cast", f"{r.shape.record} is not a direct base of {dq}")
        off = r.off - ds.fields[key][0]
        if off < 0 or off + len(ds) > len(st.mem[r.cell]):
            raise Gap("cast", f"the {r.shape.record} is not inside a {dq}")
        return Ref(r.cell, off, ds)

    def static_ref(self, st: State, ref) -> Ref:
        """A static or global variable: its initializer, evaluated once (a constant of the engine)."""
        did = ref[0]
        if did in self.static_cache:
            v = self.static_cache[did]
            return Ref(self.new_cell(st, v.slots, v.shape.kinds), 0, v.shape)
        decl = self.u.decls.get(did)
        init = None
        if decl is not None and not decl.a.get("init"):
            decl = self.u.var_defs.get(did, decl)            # its definition elsewhere in the unit (with init)
        if decl is not None and decl.a.get("init"):
            init = next((c for c in decl.c if c.k != "<null>"), None)
        if init is None:
            q = self._static_qual(did, ref)
            mangled = (decl.a.get("mangledName") if decl is not None else None) or ""
            got = (self.known_statics.get(mangled) or self.known_statics.get(q)
                   or self.known_statics.get(_unqual_static(q)))
            if got is None:
                raise Gap("unknown constant", f"{q or ref[2]} (its definition is not in this unit)")
            v = Val(got[0], Shape(list(got[1]), list(got[2])))
            if decl is not None:
                want = self.L.shape(decl.a.get("t") or "", decl.a.get("dt"))
                if len(want) != len(v.slots):
                    raise Gap("unknown constant", f"{q}: its definition has another shape")
                v = Val(v.slots, want)
        else:
            fr = {"env": {}, "this": None, "fn": decl, "ret_shape": None}
            s = self.L.shape(decl.a.get("t") or "", decl.a.get("dt"))
            tmp = State({}, ["bool", False], None)
            r = Ref(self.new_cell(tmp, [["var", "<uninit>"]] * len(s), s.kinds), 0, s)
            self.init_into(tmp, r, init, fr)
            v = Val(tmp.mem[r.cell], s)
        for t in v.slots:
            if not (const(t)):
                raise Gap("unknown constant", f"{ref[2]} is not a constant")
        self.static_cache[did] = v
        return Ref(self.new_cell(st, v.slots, v.shape.kinds), 0, v.shape)

    def static_value(self, decl: Node) -> Val:
        init = next((c for c in decl.c if c.k != "<null>"), None) if decl.a.get("init") else None
        if init is None:
            raise Gap("unknown constant", decl.a.get("name") or "")
        fr = {"env": {}, "this": None, "fn": decl, "ret_shape": None}
        s = self.L.shape(decl.a.get("t") or "", decl.a.get("dt"))
        tmp = State({}, ["bool", False], None)
        r = Ref(self.new_cell(tmp, [UNINIT] * len(s), s.kinds), 0, s)
        self.init_into(tmp, r, init, fr)
        return Val(tmp.mem[r.cell], s)

    def _static_qual(self, did, ref) -> str:
        rec = self.u.parent.get(did)
        if rec is None:
            pdc = (self.u.decls.get(did) or NULL).a.get("parentDeclContextId")
            rec = pdc if pdc in self.u.record_name else None
        rq = self.u.record_name.get(rec) if rec else None
        return f"{rq}::{ref[2]}" if rq else (ref[2] or "")

    # initialization ------------------------------------------------------------------------------------------------
    def init_into(self, st: State, r: Ref, init: Node, fr) -> None:
        k = init.k
        if k in ("ExprWithCleanups", "ParenExpr"):
            return self.init_into(st, r, init.c[0], fr)
        if k in ("CXXConstructExpr", "CXXTemporaryObjectExpr"):
            return self.construct(st, r, init, fr)
        if k == "InitListExpr":
            return self.init_list(st, r, init, fr)
        v = self.rvalue(st, init, fr)
        if len(v.slots) != len(r.shape):
            raise Gap("shape mismatch", f"initializing {r.shape.text} with {v.shape.text}")
        self.store(st, r, v)

    def init_list(self, st: State, r: Ref, e: Node, fr) -> None:
        items = [c for c in e.c if c.k != "<null>"]
        s = r.shape
        if len(items) == 1 and len(s) and self.shape_of(items[0]).text == s.text:
            return self.init_into(st, r, items[0], fr)
        off = 0
        for it in items:
            if it.k in ("InitListExpr", "CXXConstructExpr"):
                ss = self.shape_of(it)
                self.init_into(st, Ref(r.cell, r.off + off, ss), it, fr)
                off += len(ss)
            else:
                v = self.rvalue(st, it, fr)
                self.store(st, Ref(r.cell, r.off + off, v.shape), v)
                off += len(v.slots)
        if off < len(s):                                     # the rest is value-initialized
            self.store(st, Ref(r.cell, r.off + off, Shape(s.kinds[off:], s.names[off:])),
                       Val([lit(kk, 0) for kk in s.kinds[off:]], Shape(s.kinds[off:], s.names[off:])))

    def construct(self, st: State, r: Ref, e: Node, fr) -> None:
        """Run a constructor into ``r``: its initializers, then its body (``this`` is ``r``)."""
        s = r.shape
        ctor_t = e.a.get("ctor") or ""
        args = [c for c in e.c if c.k != "<null>"]
        if e.a.get("zeroing"):
            self.store(st, r, Val([lit(kk, 0) for kk in s.kinds], s))
        if s.record is None:                                 # a scalar "constructed" (T(x))
            if args:
                v = self.rvalue(st, args[0], fr)
                self.store(st, r, self.convert(v, s))
            else:
                self.store(st, r, Val([lit(kk, 0) for kk in s.kinds], s))
            return
        ctor = self._find_ctor(s.record, ctor_t)
        params = ctor_t.split("(", 1)[1].rsplit(")", 1)[0] if "(" in ctor_t else ""
        if len(args) == 1 and (ctor is None or ctor.a.get("isImplicit") or ctor.a.get("explicitlyDefaulted")) \
                and _is_self_param(params, s, self.L):
            v = self._arg_value(st, args[0], fr)
            if len(v.slots) == len(s):
                self.store(st, r, Val(v.slots, s))                  # a trivial copy or move: the same slots
                return
        if ctor is None or not has_body(ctor):
            p = _strip(params.replace("&", "").replace("&&", ""))
            if len(args) == 1 and (p == _strip(s.record.split("::")[-1]) or self.L.record_qual(p) == s.record):
                src = self.lvalue(st, args[0], fr) if args[0].a.get("valueCategory") != "prvalue" else None
                v = self.load(st, src) if src is not None else self.rvalue(st, args[0], fr)
                self.store(st, r, Val(v.slots, s))               # an implicit copy or move
                return
            if not args and (ctor is None or ctor.a.get("isImplicit") or ctor.a.get("explicitlyDefaulted")):
                if ctor is not None:
                    self._ctor_inits(st, r, ctor, {"env": {}, "this": r, "fn": ctor, "ret_shape": None})
                return                                           # trivial default: indeterminate values
            raise Gap("no body", f"constructor {s.record}({params})")
        self.calls[_engine_name(self.u, ctor)] += 1
        self._call(st, ctor, r, args, fr, construct=True)

    def _arg_value(self, st: State, a: Node, fr) -> Val:
        if a.a.get("valueCategory") == "prvalue":
            return self.rvalue(st, a, fr)
        return self.load(st, self.lvalue(st, a, fr))

    def _find_ctor(self, rq: str, ctor_t: str) -> Node | None:
        want = _norm_sig(ctor_t)
        rec = self.u.records.get(rq)
        if rec is None:
            return None
        cands = []
        for c in rec.c:
            if c.k == "CXXConstructorDecl" and _norm_sig(c.a.get("t") or "") == want:
                cands.append(c)
            elif c.k == "FunctionTemplateDecl":
                cands += [x for x in c.c if x.k == "CXXConstructorDecl" and _norm_sig(x.a.get("t") or "") == want
                          and any(y.k == "TemplateArgument" for y in x.c)]
        for c in cands:
            d = self.u.definition(c.a.get("id")) or c
            if has_body(d):
                return d
        return cands[0] if cands else None

    def _construct_into(self, st: State, ctor: Node, this: Ref, fr) -> None:
        self._ctor_inits(st, this, ctor, fr)
        body = has_body(ctor)
        if body is not None:
            self._exec(st, body, fr)

    def _ctor_inits(self, st: State, this: Ref, ctor: Node, fr) -> None:
        for c in ctor.c:
            if c.k != "CXXCtorInitializer":
                continue
            init = c.c[0] if c.c else None
            if "init_field" in c.a:
                fid = c.a["init_field"][0]
                off, fs = self.L.field(this.shape.record, fid)
                target = this.at(off, fs)
            elif "init_base" in c.a:
                bq = self.L.record_qual(c.a.get("init_base_dt") or c.a["init_base"])
                key = f"base:{bq}"
                sh = self.L.record_shape(this.shape.record)
                if key not in sh.fields:
                    raise Gap("constructor", f"base {c.a['init_base']}")
                off, bs = sh.fields[key]
                target = this.at(off, bs)
            elif init is not None and _unwrap(init).k in ("CXXConstructExpr", "CXXTemporaryObjectExpr"):
                self.construct(st, this, _unwrap(init), fr)            # a delegating constructor
                continue
            else:
                raise Gap("constructor", "a delegating or unknown initializer")
            if init is None:
                continue
            if init.k == "CXXDefaultInitExpr":
                fdecl = self.u.decls.get(c.a.get("init_field", (None,))[0])
                dinit = next((x for x in (fdecl.c if fdecl else ()) if x.k != "<null>"), None)
                if dinit is None:
                    raise Gap("constructor", "a default member initializer the AST does not hold")
                self.init_into(st, target, dinit, fr)
            else:
                self.init_into(st, target, init, fr)

    # operators -----------------------------------------------------------------------------------------------------
    def unary(self, st: State, e: Node, fr) -> Val:
        op = e.a.get("opcode")
        if op in ("++", "--"):
            r = self.lvalue(st, e.c[0], fr)
            old = self.load(st, r)
            self._incdec(st, r, op)
            return old if e.a.get("isPostfix") else self.load(st, r)
        if op == "&":
            return Val([("ptr", self.lvalue(st, e.c[0], fr))], Shape(["ptr"], [""]))
        if op == "*":
            return self.load(st, self._deref(self.rvalue(st, e.c[0], fr)))
        v = self.rvalue(st, e.c[0], fr)
        kind = v.shape.kinds[0]
        t = v.slots[0]
        if op == "-":
            res = mk("NEG", t)
            return Val([self.wrap(res, kind)], v.shape)
        if op == "+":
            return v
        if op == "!":
            return Val([mk("NOT", self.to_bool(t, kind))], Shape(["b"], [""]))
        if op == "~":
            return Val([self.wrap(mk("BIT_NOT", t), kind)], v.shape)
        if op in ("__extension__",):
            return v
        raise Gap("unsupported operator", op)

    def _incdec(self, st: State, r: Ref, op: str) -> None:
        v = self.load(st, r)
        kind = v.shape.kinds[0]
        one = lit(kind, 1)
        res = mk("ADD" if op == "++" else "SUB", v.slots[0], one)
        self.store(st, r, Val([self.round(res, kind)], v.shape))

    def round(self, t, kind):
        """The result of an arithmetic operation in ``kind``: f32 rounds, unsigned wraps."""
        if kind == "f32":
            return mk("F32", t)
        return self.wrap(t, kind)

    def wrap(self, t, kind):
        if kind not in INT_KINDS:
            return t
        bits, signed = INT_KINDS[kind]
        if const(t):
            return ["int", wrap_int(t[1], kind)]
        if signed:
            return t                                       # signed overflow is undefined: assumed absent
        return mk("BIT_AND", t, ["int", (1 << bits) - 1])

    def binary(self, st: State, e: Node, fr) -> Val:
        op = e.a.get("opcode")
        if op == "=":
            r = self.assign(st, e, fr)
            return self.load(st, r)
        if op == ",":
            self.eval_effect(st, e.c[0], fr)
            return self.rvalue(st, e.c[1], fr)
        if op in ("&&", "||"):
            a = self.cond(st, e.c[0], fr)
            if (op == "&&" and is_false(a)) or (op == "||" and is_true(a)):
                return Val([a], Shape(["b"], [""]))
            b = self.cond(st, e.c[1], fr)
            return Val([mk("AND" if op == "&&" else "OR", a, b)], Shape(["b"], [""]))
        va, vb = self.rvalue(st, e.c[0], fr), self.rvalue(st, e.c[1], fr)
        if len(va.slots) != 1 or len(vb.slots) != 1:
            raise Gap("shape mismatch", f"{op} on records")
        a, b = va.slots[0], vb.slots[0]
        ka, kb = va.shape.kinds[0], vb.shape.kinds[0]
        if ka == "ptr" or kb == "ptr":
            raise Gap("pointer", f"pointer arithmetic ({op})")
        rk = self.kind(e)
        if op in CMP:
            return Val([mk(CMP[op], a, b)], Shape(["b"], [""]))
        isf = ka in ("f64", "f32")
        if op in ("+", "-", "*"):
            res = mk({"+": "ADD", "-": "SUB", "*": "MUL"}[op], a, b)
            return Val([self.round(res, rk)], Shape([rk], [""]))
        if op == "/":
            if isf:
                return Val([self.round(mk("DIV", a, b), rk)], Shape([rk], [""]))
            return Val([self.wrap(self.c_div(a, b), rk)], Shape([rk], [""]))
        if op == "%":
            if isf:
                raise Gap("unsupported operator", "% on floats")
            return Val([self.wrap(self.c_rem(a, b), rk)], Shape([rk], [""]))
        if op in ("&", "|", "^"):
            if rk == "b":
                return Val([mk({"&": "AND", "|": "OR", "^": "CMP_NE"}[op], a, b)], Shape(["b"], [""]))
            return Val([self.wrap(mk({"&": "BIT_AND", "|": "BIT_OR", "^": "BIT_XOR"}[op], a, b), rk)],
                       Shape([rk], [""]))
        if op in ("<<", ">>"):
            return Val([self.shift(op, a, b, rk)], Shape([rk], [""]))
        raise Gap("unsupported operator", op)

    def shift(self, op: str, a, b, kind: str):
        """``a << b`` or ``a >> b`` in ``kind`` (the promoted left operand's): a count outside 0..width-1 is
        undefined in C++, so a count on the inputs leads to UNDEFINED_SHIFT there."""
        res = self.wrap(mk("SHIFT_LEFT" if op == "<<" else "SHIFT_RIGHT", a, b), kind)
        width = INT_KINDS[kind][0] if kind in INT_KINDS else 32
        if const(b):
            if not 0 <= b[1] < width:
                raise Gap("undefined behaviour", f"a shift by {b[1]} of a {width}-bit operand")
            return res
        inside = mk("AND", mk("CMP_GE", b, ["int", 0]), mk("CMP_LT", b, ["int", width]))
        return mk("IF_EXPR", inside, res, UNDEFINED_SHIFT)

    @staticmethod
    def c_div(a, b):
        """C's truncating integer division, over FLOORDIV."""
        if const(a) and const(b) and b[1] != 0:
            return ["int", _c_div(a[1], b[1])]
        q = mk("FLOORDIV", a, b)
        fix = mk("AND", mk("CMP_NE", mk("MOD", a, b), ["int", 0]),
                 mk("CMP_NE", mk("CMP_LT", a, ["int", 0]), mk("CMP_LT", b, ["int", 0])))
        return mk("IF_EXPR", fix, mk("ADD", q, ["int", 1]), q)

    @classmethod
    def c_rem(cls, a, b):
        if const(a) and const(b) and b[1] != 0:
            return ["int", _c_rem(a[1], b[1])]
        return mk("SUB", a, mk("MUL", b, cls.c_div(a, b)))

    def assign(self, st: State, e: Node, fr) -> Ref:
        r = self.lvalue(st, e.c[0], fr)
        rhs = e.c[1]
        if r.shape.record is not None and rhs.k in ("CXXConstructExpr", "InitListExpr", "CXXTemporaryObjectExpr"):
            tmp = Ref(self.new_cell(st, [["var", "<uninit>"]] * len(r.shape), r.shape.kinds), 0, r.shape)
            self.init_into(st, tmp, rhs, fr)
            v = Val(st.mem[tmp.cell], r.shape)
        else:
            v = self.rvalue(st, rhs, fr)
        if len(v.slots) != len(r.shape):
            raise Gap("shape mismatch", "an assignment between different shapes")
        self.store(st, r, Val(v.slots, r.shape))
        return r

    def compound(self, st: State, e: Node, fr) -> Ref:
        op = e.a.get("opcode")[:-1]
        r = self.lvalue(st, e.c[0], fr)
        cur = self.load(st, r)
        if len(cur.slots) != 1:
            raise Gap("shape mismatch", f"{op}= on a record")
        lk = cur.shape.kinds[0]
        ck = BUILTIN.get(_strip(e.a.get("computeLHSType") or ""), lk)
        rv = self.rvalue(st, e.c[1], fr)
        a = self.convert(cur, Shape([ck], [""])).slots[0]
        b = rv.slots[0]
        if op in ("+", "-", "*"):
            res = self.round(mk({"+": "ADD", "-": "SUB", "*": "MUL"}[op], a, b), ck)
        elif op == "/":
            res = self.round(mk("DIV", a, b), ck) if ck in ("f64", "f32") else self.wrap(self.c_div(a, b), ck)
        elif op == "%":
            res = self.wrap(self.c_rem(a, b), ck)
        elif op in ("&", "|", "^"):
            if ck == "b":
                res = mk({"&": "AND", "|": "OR", "^": "CMP_NE"}[op], a, b)
            else:
                res = self.wrap(mk({"&": "BIT_AND", "|": "BIT_OR", "^": "BIT_XOR"}[op], a, b), ck)
        elif op in ("<<", ">>"):
            res = self.shift(op, a, b, ck)
        else:
            raise Gap("unsupported operator", op + "=")
        out = self.convert(Val([res], Shape([ck], [""])), Shape([lk], [""]))
        self.store(st, r, Val(out.slots, cur.shape))
        return r

    # conversions -------------------------------------------------------------------------------------------------
    def cast(self, st: State, e: Node, fr) -> Val:
        ck = e.a.get("castKind")
        child = e.c[0]
        if ck in ("LValueToRValue", "NoOp", None, "ConstructorConversion", "UserDefinedConversion",
                  "FunctionToPointerDecay", "AtomicToNonAtomic", "NonAtomicToAtomic"):
            if ck == "LValueToRValue":
                inner = child
                while inner.k == "ParenExpr" and inner.c:
                    inner = inner.c[0]
                if inner.k == "ArraySubscriptExpr":
                    return self._select(st, inner, fr)
                return self.load(st, self.lvalue(st, child, fr))
            if ck == "NoOp" and child.a.get("valueCategory") == "lvalue" and e.a.get("valueCategory") != "prvalue":
                return self.load(st, self.lvalue(st, child, fr))
            return self.rvalue(st, child, fr)
        if ck == "ToVoid":
            self.eval_effect(st, child, fr)
            return Val([], Shape([], []))
        if ck in ("ArrayToPointerDecay",):
            return Val([("ptr", self.lvalue(st, child, fr))], Shape(["ptr"], [""]))
        if ck in ("DerivedToBase", "UncheckedDerivedToBase"):
            tt = e.a.get("dt") or e.a.get("t") or ""
            if ref_kind(tt) == "*":                         # a pointer to the derived object as one to its base
                r = self._deref(self.rvalue(st, child, fr))
                return Val([("ptr", self.base_of(r, e, pointee(tt)))], Shape(["ptr"], [""]))
            if child.a.get("valueCategory") == "prvalue":
                v = self.rvalue(st, child, fr)
                r = Ref(self.new_cell(st, v.slots, v.shape.kinds), 0, v.shape)
            else:
                r = self.lvalue(st, child, fr)
            return self.load(st, self.base_of(r, e))
        v = self.rvalue(st, child, fr)
        target = self.shape_of(e)
        if ck in ("FloatingCast", "IntegralToFloating", "FloatingToIntegral", "IntegralCast", "IntegralToBoolean",
                  "FloatingToBoolean", "BooleanToSignedIntegral"):
            return self.convert(v, target, signed_bool=ck == "BooleanToSignedIntegral")
        if ck == "BitCast" and ref_kind(e.a.get("t") or "") == "*" and v.shape.kinds == ["ptr"]:
            r = self._deref(v)                                # a pointer read as a pointer to another type
            tt = e.a.get("dt") or e.a.get("t") or ""
            pt = pointee(tt)
            if _strip(pt) == "void":
                return Val([("ptr", r)], Shape(["ptr"], [""]))
            return Val([("ptr", Ref(r.cell, r.off, self.L.shape(pt)))], Shape(["ptr"], [""]))
        if ck in ("BitCast", "LValueBitCast", "IntegralToPointer", "PointerToIntegral", "NullToPointer",
                  "ReinterpretMemberPointer", "BaseToDerived"):
            raise Gap("bit-level reinterpretation", f"{ck} {child.a.get('t')} -> {e.a.get('t')}")
        raise Gap("cast", ck or "?")

    def convert(self, v: Val, target: Shape, signed_bool: bool = False) -> Val:
        if len(v.slots) != 1 or len(target) != 1:
            if len(v.slots) == len(target):
                return Val(v.slots, target)
            raise Gap("shape mismatch", f"converting {v.shape.text} to {target.text}")
        t, src, dst = v.slots[0], v.shape.kinds[0], target.kinds[0]
        if src == dst:
            return Val([t], target)
        if dst == "b":
            return Val([self.to_bool(t, src)], target)
        if src == "b":
            one = -1 if signed_bool else 1
            return Val([mk("IF_EXPR", t, lit(dst, one), lit(dst, 0))], target)
        if src in ("f64", "f32") and dst in ("f64", "f32"):
            return Val([mk("F32", t) if dst == "f32" else t], target)
        if src in INT_KINDS and dst in ("f64", "f32"):
            x = mk("TO_FLOAT", t)
            return Val([mk("F32", x) if dst == "f32" else x], target)
        if src in ("f64", "f32") and dst in INT_KINDS:
            return Val([self.wrap(mk("TRUNC_INT", t), dst)], target)
        if src in INT_KINDS and dst in INT_KINDS:
            bs, ss = INT_KINDS[src]
            bd, sd = INT_KINDS[dst]
            # every value of the source fits: the same signedness and no narrower, or unsigned into wider signed
            if (ss == sd and bd >= bs) or (not ss and sd and bd > bs):
                return Val([t], target)
            if const(t):
                return Val([["int", wrap_int(t[1], dst)]], target)
            m = mk("BIT_AND", t, ["int", (1 << bd) - 1])
            if sd:
                half = 1 << (bd - 1)
                m = mk("SUB", mk("BIT_AND", mk("ADD", t, ["int", half]), ["int", (1 << bd) - 1]), ["int", half])
            return Val([m], target)
        if src == "ptr" or dst == "ptr":
            raise Gap("pointer", f"converting {src} to {dst}")
        raise Gap("cast", f"{src} -> {dst}")

    # calls ------------------------------------------------------------------------------------------------------------
    def callee(self, st: State, e: Node, fr) -> tuple[Callee, list[Node]]:
        k = e.k
        kids = [c for c in e.c if c.k != "<null>"]
        if k == "CXXMemberCallExpr":
            m = _unwrap(kids[0])
            if m.k != "MemberExpr":
                raise Gap("call", f"a member call through {m.k}")
            base = m.c[0]
            if m.a.get("isArrow"):
                this = self._deref(self.rvalue(st, base, fr))
            elif base.a.get("valueCategory") == "prvalue" and base.k != "CXXThisExpr":
                v = self.rvalue(st, base, fr)
                this = Ref(self.new_cell(st, v.slots, v.shape.kinds), 0, v.shape)
            else:
                this = self.lvalue(st, base, fr)
            return Callee(m.a.get("mref"), m.a.get("name"), this), kids[1:]
        if k == "CXXOperatorCallExpr":
            fn = _unwrap(kids[0])
            ref = fn.a.get("ref") or (None, None, None, None)
            decl = self.u.decls.get(ref[0])
            if ref[1] == "CXXMethodDecl" or (decl is not None and decl.k == "CXXMethodDecl"
                                              and decl.a.get("storageClass") != "static"):
                obj = kids[1]
                if obj.a.get("valueCategory") == "prvalue":
                    v = self.rvalue(st, obj, fr)
                    this = Ref(self.new_cell(st, v.slots, v.shape.kinds), 0, v.shape)
                else:
                    this = self.lvalue(st, obj, fr)
                return Callee(ref[0], ref[2], this, "CXXMethodDecl", ref[3]), kids[2:]
            return Callee(ref[0], ref[2], None, ref[1], ref[3]), kids[1:]
        fn = _unwrap(kids[0])
        if fn.k == "MemberExpr":                              # a static member called through an object
            return Callee(fn.a.get("mref"), fn.a.get("name"), None), kids[1:]
        if fn.k != "DeclRefExpr":
            raise Gap("call", f"an indirect call through {fn.k}")
        ref = fn.a.get("ref") or (None, None, None, None)
        return Callee(ref[0], ref[2], None, ref[1], ref[3]), kids[1:]

    def call_expr(self, st: State, e: Node, fr):
        c, args = self.callee(st, e, fr)
        decl = self.u.decls.get(c.decl_id)
        name = c.name or ""
        if decl is None or not has_body(decl):
            d2 = self.u.definition(c.decl_id) if c.decl_id else None
            if d2 is not None:
                decl = d2
        if decl is not None and name == "operator=" and len(args) == 1 and c.this is not None and \
                (decl.a.get("isImplicit") or decl.a.get("explicitlyDefaulted") or not has_body(decl)):
            v = self._arg_value(st, args[0], fr)                 # an implicit assignment copies the slots
            if len(v.slots) != len(c.this.shape):
                raise Gap("shape mismatch", "an implicit assignment between different shapes")
            self.store(st, c.this, Val(v.slots, c.this.shape))
            return c.this
        if decl is None or not has_body(decl):
            atom = self.libm(name, decl, c)
            if atom == "COMPOSITE":
                return self.classify_cmp(st, name, args, fr)
            if atom is not None:
                return self.apply_atom(st, atom, args, fr, e)
            if name in ("__builtin_expect", "__builtin_assume", "__builtin_unreachable"):
                if name == "__builtin_expect":
                    return self.rvalue(st, args[0], fr)
                return None
            if _is_move(name, decl):
                inner = args[0]
                if inner.a.get("valueCategory") == "prvalue":
                    v = self.rvalue(st, inner, fr)
                    return Ref(self.new_cell(st, v.slots, v.shape.kinds), 0, v.shape)
                return self.lvalue(st, inner, fr)
            if name in ("rand", "srand", "random", "FRand", "Rand"):
                raise Gap("random state", f"{name}() reads or changes the C library's random state")
            if name in ("modf", "modff") and len(args) == 2:
                x = self.rvalue(st, args[0], fr).slots[0]
                kind = self.kind(e)
                whole = self.round(mk("TRUNC", x), kind)
                self.atoms["TRUNC"] += 1
                dst = self._deref(self.rvalue(st, args[1], fr))
                self.store(st, dst, Val([whole], dst.shape))
                return Val([self.round(mk("SUB", x, whole), kind)], Shape([kind], [""]))
            if name in ("Memzero", "Memset", "memset", "__builtin_memset"):
                return Val([self.memset(st, name, args, fr)], Shape(["ptr"], [""]))
            if name in ("IntCastChecked", "IntFitsIn") and len(args) == 1:
                return self.convert(self.rvalue(st, args[0], fr), self.shape_of(e))
            if name in ("BitCast", "bit_cast") and len(args) == 1:
                return self.bitcast_value(self.rvalue(st, args[0], fr), self.shape_of(e))
            if name in ("Memcpy", "memcpy", "__builtin_memcpy", "Memmove", "memmove", "__builtin_memmove"):
                return Val([self.memcpy(st, args, fr)], Shape(["ptr"], [""]))
            if self._is_effect(decl, c):
                self.notes.append(f"effect: {_qual_of(self.u, c.decl_id, name)}")
                return None
            x = self.external(st, decl, c, args, fr, e)
            if x is not None:
                return x
            raise Gap("no body", f"{_qual_of(self.u, c.decl_id, name)}")
        if decl.a.get("id") in self.stack:
            raise Gap("recursion", _qual_of(self.u, decl.a.get("id"), name))
        if len(self.stack) >= MAX_DEPTH:
            raise Gap("budget", f"calls nested deeper than {MAX_DEPTH}")
        self.calls[_engine_name(self.u, decl)] += 1
        if _is_move(name, decl) and len(args) == 1:
            inner = args[0]
            if inner.a.get("valueCategory") == "prvalue":
                v = self.rvalue(st, inner, fr)
                return Ref(self.new_cell(st, v.slots, v.shape.kinds), 0, v.shape)
            return self.lvalue(st, inner, fr)
        return self._call(st, decl, c.this, args, fr)

    def _call(self, st: State, decl: Node, this, args: list[Node], fr, construct: bool = False):
        rid0 = self.u.parent.get(decl.a.get("id"))
        self.L.push(self.u.record_name.get(rid0) if rid0 else None)
        try:
            return self._call_in(st, decl, this, args, fr, construct)
        finally:
            self.L.pop()

    def _call_in(self, st: State, decl: Node, this, args: list[Node], fr, construct: bool = False):
        self.floors.append(self.next_cell)
        try:
            return self._call_frame(st, decl, this, args, fr, construct)
        finally:
            self.floors.pop()

    def _call_frame(self, st: State, decl: Node, this, args: list[Node], fr, construct: bool = False):
        params = [c for c in decl.c if c.k == "ParmVarDecl"]
        env: dict = {}
        if len(args) > len(params) and not decl.a.get("variadic"):
            raise Gap("call", f"{len(args)} arguments for {len(params)} parameters")
        for i, p in enumerate(params):
            a = args[i] if i < len(args) else None
            if a is None or a.k == "CXXDefaultArgExpr":
                dinit = next((x for x in p.c if x.k != "<null>"), None) if p.a.get("init") else None
                if dinit is None:
                    raise Gap("default argument", f"{p.a.get('name')} has no default in the AST")
                a, afr = dinit, {"env": {}, "this": None, "fn": decl, "ret_shape": None}
            else:
                afr = fr
            t = p.a.get("t") or ""
            rk = ref_kind(t)
            if rk in ("&", "&&"):
                if a.a.get("valueCategory") == "prvalue" or a.k == "MaterializeTemporaryExpr" and \
                        a.c and a.c[0].a.get("valueCategory") == "prvalue":
                    inner = a.c[0] if a.k == "MaterializeTemporaryExpr" else a
                    s = self.L.shape(pointee(t), _pointee_dt(p.a.get("dt")))
                    r = Ref(self.new_cell(st, [["var", "<uninit>"]] * len(s), s.kinds), 0, s)
                    self.init_into(st, r, inner, afr)
                    env[p.a["id"]] = r
                else:
                    env[p.a["id"]] = self.lvalue(st, a, afr)
            elif rk == "*":
                pv = self.rvalue(st, a, afr)
                env[p.a["id"]] = Ref(self.new_cell(st, pv.slots, pv.shape.kinds), 0, pv.shape)
            else:
                s = self.L.shape(t, p.a.get("dt"))
                r = Ref(self.new_cell(st, [["var", "<uninit>"]] * len(s), s.kinds), 0, s)
                self.init_into(st, r, a, afr)
                env[p.a["id"]] = r
        frame = {"env": env, "this": this, "fn": decl, "ret_shape": None}
        sub = State(st.mem, st.done, None)
        rid = self.u.parent.get(decl.a.get("id"))
        self.L.push(self.u.record_name.get(rid) if rid else None)
        guard = st.done
        self.stack.append(decl.a.get("id"))
        try:
            if construct:
                self._construct_into(sub, decl, this, frame)
                ret = None
            else:
                sub.done = ["bool", False] if is_false(guard) else guard
                self._exec(sub, has_body(decl), frame)
                ret = sub.ret
        finally:
            self.stack.pop()
            self.L.pop()
        st.mem = sub.mem
        if construct:
            return None
        rt = _return_type(decl.a.get("t") or "")
        if _strip(rt) == "void" or rt == "":
            return None
        if ret is None:
            raise Gap("no return", _qual_of(self.u, decl.a.get("id"), decl.a.get("name")))
        return ret

    def external(self, st: State, decl, c: Callee, args: list[Node], fr, e: Node):
        """A call to a function defined in another unit: ``["XCALL", mangled, j, *inputs]`` for each slot j of its
        result, its inputs in the order the callee's own lift lists them (this, then the parameters).
        scan.resolve replaces it by the callee's term. Only for calls that write nothing of ours."""
        if decl is None or not decl.a.get("mangledName"):
            return None
        t = decl.a.get("t") or ""
        rt = _return_type(t)
        if ref_kind(rt) in ("&", "&&", "*") or _strip(rt) == "void":
            return None
        const_method = "const" in t.rsplit(")", 1)[-1]
        if c.this is not None and not const_method:
            return None
        params = [x for x in decl.c if x.k == "ParmVarDecl"]
        if len(params) != len(args):
            return None
        flat = []
        if c.this is not None:
            flat += self.load(st, c.this).slots
        for p_, a in zip(params, args):
            pt = p_.a.get("t") or ""
            rk = ref_kind(pt)
            inner = pointee(pt) if rk else pt
            if rk in ("&", "&&", "*") and not inner.startswith("const "):
                return None
            if rk == "*":
                return None
            if a.k == "CXXDefaultArgExpr":
                return None
            shape = self.L.shape(inner, _pointee_dt(p_.a.get("dt")) if rk else p_.a.get("dt"))
            if a.a.get("valueCategory") == "prvalue" or rk is None:
                if shape.record is not None and a.k in ("CXXConstructExpr", "InitListExpr", "CXXTemporaryObjectExpr"):
                    tmp = Ref(self.new_cell(st, [UNINIT] * len(shape), shape.kinds), 0, shape)
                    self.init_into(st, tmp, a, fr)
                    v = Val(st.mem[tmp.cell], shape)
                else:
                    v = self.convert(self.rvalue(st, a, fr), shape) if len(shape) == 1 else self.rvalue(st, a, fr)
            else:
                v = self.load(st, self.lvalue(st, a, fr))
            if len(v.slots) != len(shape):
                return None
            flat += v.slots
        rs = self.shape_of(e)
        key = decl.a["mangledName"]
        self.calls[_engine_name(self.u, decl)] += 1
        self.xcalls[key] += 1
        return Val([["XCALL", key, j, *flat] for j in range(len(rs))], rs)

    def _is_effect(self, decl, c: Callee) -> bool:
        """A void function without a body that can write nothing of ours (no non-const reference or pointer
        parameter, not a method on our object): it can only act outside (log, report), so its call is an effect."""
        t = (decl.a.get("t") if decl is not None else c.type) or ""
        if _strip(_return_type(t)) != "void" or c.this is not None:
            return False
        params = t.split("(", 1)[1].rsplit(")", 1)[0] if "(" in t else ""
        for p in [x.strip() for x in params.split(",") if x.strip()]:
            if (p.endswith("&") or p.endswith("*")) and not p.startswith("const "):
                return False
        name = (decl.a.get("name") if decl is not None else c.name) or ""
        return bool(re.search(r"ReportError|Log|Printf|Assert|Ensure|Warn|Trace|Report", name))

    def libm(self, name: str, decl, c: Callee):
        n = name[len("__builtin_"):] if name.startswith("__builtin_") else name
        n = n.split("::")[-1]
        if n in COMPARE_MACROS:
            return "COMPOSITE"
        if n in BITCOUNT:
            return (BITCOUNT[n], "int")
        if n in LIBM and LIBM[n] is not None:
            return (LIBM[n], "f64")
        if n.endswith("f") and n[:-1] in LIBM and LIBM[n[:-1]] is not None:
            return (LIBM[n[:-1]], "f32")
        if n.endswith("l") and n[:-1] in LIBM and LIBM[n[:-1]] is not None:
            return (LIBM[n[:-1]], "f64")
        return None

    def classify_cmp(self, st: State, name: str, args: list[Node], fr) -> Val:
        """C99's quiet comparisons: the same truth values as the operators (false on NaN); isunordered is
        "either is NaN"."""
        n = (name[len("__builtin_"):] if name.startswith("__builtin_") else name).split("::")[-1]
        a, b = (self.rvalue(st, x, fr).slots[0] for x in args)
        if n == "isunordered":
            return Val([mk("OR", mk("ISNAN", a), mk("ISNAN", b))], Shape(["b"], [""]))
        if n == "islessgreater":
            return Val([mk("OR", mk("CMP_LT", a, b), mk("CMP_GT", a, b))], Shape(["b"], [""]))
        return Val([mk(COMPARE_MACROS[n], a, b)], Shape(["b"], [""]))

    def apply_atom(self, st: State, atom, args: list[Node], fr, e: Node) -> Val:
        (op, arity), _prec = atom
        if len(args) != arity:
            raise Gap("call", f"{op} with {len(args)} arguments")
        vals = [self.rvalue(st, a, fr) for a in args]
        rk = self.kind(e)
        ts = []
        for v in vals:
            if len(v.slots) != 1:
                raise Gap("shape mismatch", f"{op} of a record")
            ts.append(v.slots[0])
        self.atoms[op] += 1
        if op in BOOL_ATOMS:
            return Val([mk(op, *ts)], Shape(["b"], [""]))
        res = mk(op, *ts) if op in EXACT_FOLD else [op, *ts]
        return Val([self.round(res, rk) if rk == "f32" else res], Shape([rk], [""]))


# -- helpers -----------------------------------------------------------------------------------------------------------
UE_INTS = {"int32": "int", "uint32": "unsigned int", "int64": "long long", "uint64": "unsigned long long",
           "int16": "short", "uint16": "unsigned short", "int8": "signed char", "uint8": "unsigned char"}


def _canon_args(name: str) -> str:
    """The engine's integer type names inside template arguments, spelled as clang prints specializations."""
    if "<" not in name:
        return name
    head, rest = name.split("<", 1)
    return head + "<" + re.sub(r"\b(u?int(?:8|16|32|64))\b", lambda m: UE_INTS[m.group(1)], rest)


def _round_up(n: int, a: int) -> int:
    return (n + a - 1) // a * a


def _split_args(text: str) -> list[str]:
    """Top-level comma-separated template arguments."""
    out, depth, cur = [], 0, ""
    for ch in text:
        if ch in "<([":
            depth += 1
        elif ch in ">)]":
            depth -= 1
        if ch == "," and depth == 0:
            out.append(cur.strip())
            cur = ""
        else:
            cur += ch
    if cur.strip():
        out.append(cur.strip())
    return out


def _IfNode(cond, then: Node, els: Node) -> Node:
    return Node("IfStmt", {"pre": cond}, (then, els))


def _is_self_param(params: str, s: Shape, L) -> bool:
    """Is a constructor's one parameter the record itself (a copy or a move)?"""
    p = _strip(params.replace("&&", "").replace("&", ""))
    if s.text == "<anon>" or "(anonymous" in p:
        return True
    return p == _strip((s.record or "").split("::")[-1]) or L.record_qual(p) == s.record


def _dot(n: str) -> str:
    return "" if not n else (n if n.startswith("[") else "." + n)


def _has_uninit(t) -> bool:
    seen, stack = set(), [t]
    while stack:
        x = stack.pop()
        if x == UNINIT:
            return True
        if isinstance(x, list) and id(x) not in seen:
            seen.add(id(x))
            stack.extend(x[1:] if x and isinstance(x[0], str) else x)
    return False


def _has_ptr(t) -> bool:
    seen, stack = set(), [t]
    while stack:
        x = stack.pop()
        if isinstance(x, tuple):
            return True
        if isinstance(x, list) and id(x) not in seen:
            seen.add(id(x))
            stack.extend(x)
    return False


def _unwrap(e: Node) -> Node:
    while e.k in ("ImplicitCastExpr", "ParenExpr", "MaterializeTemporaryExpr", "CXXBindTemporaryExpr") and e.c:
        e = e.c[0]
    return e


def _num(v, kind):
    return float(v) if kind in ("f64", "f32") else (v in (True, "true", 1) if kind == "b" else int(v))


def _return_type(fn_type: str) -> str:
    """The return type of a function type string 'R (A, B) const'."""
    depth = 0
    for i, ch in enumerate(fn_type):
        if ch == "<":
            depth += 1
        elif ch == ">":
            depth -= 1
        elif ch == "(" and depth == 0:
            return fn_type[:i].strip()
    return fn_type.strip()


def _norm_sig(t: str) -> str:
    t = re.sub(r"\bnoexcept\b(\([^)]*\))?", "", t or "")
    t = re.sub(r"\b(struct|class)\s+", "", t)
    return re.sub(r"\s+", "", t)


def _pointee_dt(dt: str | None) -> str | None:
    return pointee(dt) if dt and ref_kind(dt) in ("&", "&&", "*") else None


def _unqual_static(q: str) -> str:
    """UE::Math::TVector<double>::ZeroVector and TVector<double>::ZeroVector name one constant."""
    return q.split("UE::Math::", 1)[-1]


def _is_move(name: str, decl) -> bool:
    return name in ("MoveTemp", "MoveTempIfPossible", "Forward", "move", "forward", "CopyTemp")


def _qual_of(unit, decl_id, name) -> str:
    rec = unit.parent.get(decl_id)
    rq = unit.record_name.get(rec) if rec else None
    return f"{rq}::{name}" if rq else (name or "?")


def _engine_name(unit, decl: Node) -> str:
    """A called function's name in the engine's vocabulary: Record::name or namespace-free name."""
    return _qual_of(unit, decl.a.get("id"), decl.a.get("name"))


__all__ = ["Gap", "Lifted", "Lifter", "Shape", "f32", "fold", "mk", "size"]
