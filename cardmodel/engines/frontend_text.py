"""frontend_text — lift functions written in fifteen more languages into the card IR.

One tokenizer, one Pratt expression parser and two statement grammars (brace-delimited and keyword/``end``
delimited) cover the IR subset of every language whose card names this module as its ``frontend``:

  braces  C, C++, C#, Java, Kotlin, Go, Rust, Swift, Zig, JavaScript, TypeScript, PHP
  end     Ruby, Lua, Julia

A :class:`Dialect` holds what differs: operator precedence, what ``/`` and ``%`` mean on integers, which type
names exist, whether newlines end statements, whether the last expression is the return value. The lowering to IR
is shared, and the language's own semantics decide every op: C's ``/`` on integers is ``TRUNCDIV`` (toward zero),
Ruby's is ``FLOORDIV``, Lua's is float division; ``%`` is ``REM`` (sign of the dividend) in the C family and
``MOD`` (sign of the divisor) in Ruby, Lua and Python.

Calls resolve in this order: functions of the same file, the dialect's library table (``Math.abs``, ``fabs``,
``x.abs()``, ``math.floor``, ``Int(x)`` ...), then the op cards' own ``emit`` templates read backwards (so
everything codegen writes, ``cm_floormod(a, b)`` or ``Math.floorMod(a, b)``, lifts back to its op: a new op card
with a call-shaped template is liftable with no code change).

C keeps its own integer semantics: ``uint8_t``..``uint32_t``, ``unsigned``, ``int8_t``, ``short`` and ``int`` have
a kind (signed, bits), expressions take C's kinds (promotion, the usual arithmetic conversions, literal types,
octal), and wherever C reduces a value modulo 2^w the IR gets ``WRAPU``/``WRAPS`` (the u8..i32 subsorts): unsigned
results of + - * << ~ and negation, conversions on assignment, return, casts and calls, and narrow or unsigned
parameters on entry. C arrays read as lists: ``const T *xs`` / ``T xs[]`` parameters (passed with their length,
never written) and local ``T a[n]`` / ``T a[] = {...}`` arrays (LIST_NEW and ``set``).

Honest limits (L1): int/float/bool scalars (and, in C, lists of int or float); no strings, structs, classes as
values, pointer arithmetic or dereference, exceptions or globals (methods of a Java/C#/Kotlin class lift when they
are ``static``-like functions of scalars); 64-bit unsigned integers (``uint64_t``, ``size_t``) and binary32 floats
are reported, not approximated; signed overflow in C is undefined and is not wrapped (the lift is exact there);
integer width is otherwise the language's (fixed-width sources agree with the IR only where no value overflows);
untyped parameters (Ruby, Lua, JavaScript, PHP, Julia) default to ``int`` (JavaScript: ``float`` unless the
function uses BigInt) and are marked ``inferred_types``.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .ir import OpSpec

# -- dialects ------------------------------------------------------------------------------------------------------

INT, FLOAT, BOOL, VOID = "int", "float", "bool", "void"

# precedence levels: (binding power, [operators]); higher binds tighter. Ternary and ranges are handled apart.
_C_PREC = [(1, ["||"]), (2, ["&&"]), (3, ["|"]), (4, ["^"]), (5, ["&"]), (6, ["==", "!=", "===", "!=="]),
           (7, ["<", "<=", ">", ">="]), (8, ["<<", ">>", ">>>"]), (9, ["+", "-"]), (10, ["*", "/", "%"]),
           (12, ["**"])]
_GO_PREC = [(1, ["||"]), (2, ["&&"]), (3, ["==", "!=", "<", "<=", ">", ">="]), (4, ["+", "-", "|", "^"]),
            (5, ["*", "/", "%", "<<", ">>", "&", "&^"])]
_RUST_PREC = [(1, ["||"]), (2, ["&&"]), (3, ["==", "!=", "<", "<=", ">", ">="]), (4, ["|"]), (5, ["^"]),
              (6, ["&"]), (7, ["<<", ">>"]), (8, ["+", "-"]), (9, ["*", "/", "%"])]
_SWIFT_PREC = [(1, ["||"]), (2, ["&&"]), (3, ["==", "!=", "<", "<=", ">", ">="]), (5, ["+", "-", "|", "^"]),
               (6, ["*", "/", "%", "&"]), (7, ["<<", ">>"])]
_KOTLIN_PREC = [(1, ["||"]), (2, ["&&"]), (3, ["==", "!=", "===", "!=="]), (4, ["<", "<=", ">", ">="]),
                (5, ["or", "xor"]), (5.5, ["and"]), (6, ["shl", "shr", "ushr"]), (7, ["+", "-"]),
                (8, ["*", "/", "%"])]
_ZIG_PREC = [(1, ["or"]), (2, ["and"]), (3, ["==", "!=", "<", "<=", ">", ">="]), (4, ["&", "^", "|"]),
             (5, ["<<", ">>"]), (6, ["+", "-"]), (7, ["*", "/", "%"])]
_RUBY_PREC = [(0.5, ["or"]), (0.7, ["and"]), (1, ["||"]), (2, ["&&"]), (3, ["==", "!="]),
              (4, ["<", "<=", ">", ">="]), (5, ["|", "^"]), (6, ["&"]), (7, ["<<", ">>"]), (8, ["+", "-"]),
              (9, ["*", "/", "%"]), (12, ["**"])]
_LUA_PREC = [(1, ["or"]), (2, ["and"]), (3, ["<", ">", "<=", ">=", "~=", "=="]), (4, ["|"]), (5, ["~"]),
             (6, ["&"]), (7, ["<<", ">>"]), (9, ["+", "-"]), (10, ["*", "/", "//", "%"]), (12, ["^"])]
_JULIA_PREC = [(1, ["||"]), (2, ["&&"]), (3, ["==", "!=", "<", "<=", ">", ">=", "==="]),
               (5, ["+", "-", "|", "⊻"]), (6, ["*", "/", "÷", "%", "&"]), (7, ["<<", ">>", ">>>"]), (12, ["^"])]

RIGHT_ASSOC = {"**", "^pow"}

_INT_C = {"int", "long", "short", "int64_t", "int32_t", "int16_t", "int8_t", "intmax_t", "ptrdiff_t", "ssize_t",
          "long long", "long int", "long long int", "signed", "signed int", "signed long", "short int"}
_UNSIGNED_C = {"unsigned", "unsigned int", "unsigned long", "unsigned long long", "uint64_t", "uint32_t",
               "uint16_t", "uint8_t", "size_t", "uintmax_t", "unsigned char", "unsigned short", "char"}

# C's integer types as (signed, bits) on an LP64 host (int 32, long 64): every int-kinded C expression lowers to
# the IR's unbounded int, and the frontend puts C's own conversions back as WRAPU / WRAPS (the u8..i32 subsorts,
# FOUNDATIONS.md D1) wherever C reduces a value modulo 2^w. ``bool`` promotes like a narrow int.
_C_KINDS = {**{t: (True, 32) for t in ("int", "signed", "signed int", "int32_t")},
            **{t: (True, 16) for t in ("short", "short int", "signed short", "int16_t")},
            **{t: (True, 8) for t in ("signed char", "int8_t")},
            **{t: (True, 64) for t in ("long", "long int", "long long", "long long int", "signed long", "int64_t",
                                       "intmax_t", "ptrdiff_t", "ssize_t", "int64")},
            **{t: (False, 32) for t in ("unsigned", "unsigned int", "uint32_t")},
            **{t: (False, 16) for t in ("unsigned short", "unsigned short int", "uint16_t")},
            **{t: (False, 8) for t in ("unsigned char", "uint8_t")},
            "bool": (False, 1), "_Bool": (False, 1)}
_C_FIXED = {t for t, k in _C_KINDS.items() if not k[0] and k[1] > 1}       # the unsigned types that now lift
_C_U64 = "unsigned 64-bit integers wrap modulo 2^64, beyond the targets' signed 64-bit int"


@dataclass
class Dialect:
    name: str
    style: str = "braces"                  # braces | end
    prec: list = field(default_factory=lambda: _C_PREC)
    line_comments: tuple = ("//",)
    block_comments: tuple = (("/*", "*/"),)
    preproc: bool = False                  # a line starting with # is a directive (C, C++, C#)
    newline_ends: bool = False             # newlines end statements (Go, Swift, Kotlin, JS, Ruby, Lua, Julia)
    int_div: str = "trunc"                 # trunc | floor | true
    int_mod: str = "rem"                   # rem | floor
    caret: str = "xor"                     # xor | pow
    truthy_ints: bool = False              # an int is a condition (C, C++, JavaScript, PHP)
    implicit_return: bool = False          # the last expression is the value (Rust, Ruby, Julia, Kotlin `=`)
    ternary: bool = True
    types: dict = field(default_factory=dict)          # type name -> int|float|bool|void
    unsupported_types: dict = field(default_factory=dict)  # type name -> why
    untyped: str | None = None             # default type of an unannotated parameter: int | float | js
    decl_words: tuple = ()                 # let, var, const, val, auto, local, my
    sigils: str = ""                       # $ (PHP), @ (Zig builtins)
    ident_suffix: str = ""                 # ? ! (Ruby method names)
    truediv_float_only: bool = False
    else_if: tuple = ("else if",)          # spellings of else-if
    funcs: dict = field(default_factory=dict)          # library calls (by dotted name)
    methods: dict = field(default_factory=dict)        # x.method(args) / x.method
    casts: dict = field(default_factory=dict)          # call-style casts: name -> int|float
    consts: dict = field(default_factory=dict)         # named constants -> IR literal
    emit_keys: tuple = ()                  # op-card emit keys whose call-shaped templates lift back
    bigint_marker: bool = False            # JavaScript: BigInt literals make untyped params int


_F1 = {"sqrt": "FSQRT", "exp": "EXP", "log": "LOG", "sin": "SIN", "cos": "COS", "tan": "TAN", "asin": "ASIN",
       "acos": "ACOS", "atan": "ATAN", "sinh": "SINH", "cosh": "COSH", "tanh": "TANH", "floor": "FLOOR",
       "ceil": "CEIL", "trunc": "TRUNC"}


def _lib(prefix: str, names: dict, cap: bool = False) -> dict:
    out = {}
    for k, v in names.items():
        key = k[0].upper() + k[1:] if cap else k
        out[f"{prefix}{key}"] = v
    return out


_MATH_COMMON = {**{k: ("op", v) for k, v in _F1.items()}, "abs": ("op", "ABS"), "min": ("op", "MIN"),
                "max": ("op", "MAX"), "pow": ("op", "POW"), "atan2": ("op", "ATAN2")}

_C_FUNCS = {**{k: ("op", v) for k, v in _F1.items()}, "fabs": ("op", "ABS"), "abs": ("op", "ABS"),
            "labs": ("op", "ABS"), "llabs": ("op", "ABS"), "imaxabs": ("op", "ABS"), "fmin": ("op", "MIN"),
            "fmax": ("op", "MAX"), "pow": ("fpow",), "fmod": ("op", "FMOD"), "atan2": ("op", "ATAN2"),
            "copysign": ("op", "COPYSIGN"), "isnan": ("op", "ISNAN"), "INT64_C": ("id",), "INT32_C": ("id",),
            "std::abs": ("op", "ABS"), "std::min": ("op", "MIN"), "std::max": ("op", "MAX"),
            "std::sqrt": ("op", "FSQRT"), "std::floor": ("op", "FLOOR"), "std::ceil": ("op", "CEIL"),
            "std::pow": ("fpow",), "std::fmod": ("op", "FMOD"), "std::gcd": ("op", "GCD"),
            "std::trunc": ("op", "TRUNC"), "std::exp": ("op", "EXP"), "std::log": ("op", "LOG"),
            "std::sin": ("op", "SIN"), "std::cos": ("op", "COS"), "std::fabs": ("op", "ABS"),
            "__builtin_popcountll": ("op", "POPCOUNT"), "__builtin_clzll": ("op", "CLZ64"),
            "__builtin_ctzll": ("op", "CTZ64")}
_JAVA_FUNCS = {**_lib("Math.", _MATH_COMMON), "Math.floorDiv": ("op", "FLOORDIV"), "Math.floorMod": ("op", "MOD"),
               "Math.pow": ("fpow",), "Long.bitCount": ("op", "POPCOUNT"),
               "Long.numberOfLeadingZeros": ("op", "CLZ64"), "Long.numberOfTrailingZeros": ("op", "CTZ64"),
               "Math.IEEEremainder": ("no", "IEEEremainder rounds to nearest, not toward zero")}
_CS_FUNCS = {**_lib("Math.", _MATH_COMMON, cap=True), "Math.Pow": ("fpow",), "Math.Truncate": ("op", "TRUNC"),
             "Math.Sqrt": ("op", "FSQRT")}
_JS_FUNCS = {**_lib("Math.", _MATH_COMMON), "Math.pow": ("fpow",), "Math.trunc": ("op", "TRUNC"),
             "Math.sign": ("no", "Math.sign"), "Math.round": ("no", "Math.round rounds half up, no op card")}
_GO_FUNCS = {**_lib("math.", _MATH_COMMON, cap=True), "math.Pow": ("fpow",), "math.Mod": ("op", "FMOD"),
             "math.Sqrt": ("op", "FSQRT"), "math.Trunc": ("op", "TRUNC"), "math.IsNaN": ("op", "ISNAN"),
             "math.Copysign": ("op", "COPYSIGN"), "bits.OnesCount64": ("u64", "POPCOUNT"),
             "math.Abs": ("op", "ABS"), "min": ("op", "MIN"), "max": ("op", "MAX")}
_SWIFT_FUNCS = {**{k: ("op", v) for k, v in _F1.items()}, "abs": ("op", "ABS"), "min": ("op", "MIN"),
                "max": ("op", "MAX"), "pow": ("fpow",), "fmod": ("op", "FMOD"), "atan2": ("op", "ATAN2"),
                "fabs": ("op", "ABS")}
_KOTLIN_FUNCS = {**{k: ("op", v) for k, v in _F1.items()}, "abs": ("op", "ABS"), "min": ("op", "MIN"),
                 "max": ("op", "MAX"), "Math.floorDiv": ("op", "FLOORDIV"), "Math.floorMod": ("op", "MOD"),
                 "kotlin.math.abs": ("op", "ABS"), "maxOf": ("op", "MAX"), "minOf": ("op", "MIN"),
                 **_lib("Math.", _MATH_COMMON), "Math.pow": ("fpow",)}
_ZIG_FUNCS = {"@divTrunc": ("op", "TRUNCDIV"), "@divFloor": ("op", "FLOORDIV"), "@mod": ("op", "MOD"),
              "@rem": ("op", "REM"), "@divExact": ("op", "TRUNCDIV"), "@sqrt": ("op", "FSQRT"),
              "@floor": ("op", "FLOOR"), "@ceil": ("op", "CEIL"), "@trunc": ("op", "TRUNC"), "@abs": ("op", "ABS"),
              "@min": ("op", "MIN"), "@max": ("op", "MAX"), "@exp": ("op", "EXP"), "@log": ("op", "LOG"),
              "@sin": ("op", "SIN"), "@cos": ("op", "COS"), "@popCount": ("op", "POPCOUNT"),
              "@as": ("zig_as",), "@intCast": ("id",), "@floatFromInt": ("cast", FLOAT),
              "@intFromFloat": ("cast", INT), "@intFromBool": ("bool_int",),
              "std.math.pow": ("zig_pow",), "std.math.absInt": ("op", "ABS"), "std.math.gcd": ("op", "GCD")}
_PHP_FUNCS = {"abs": ("op", "ABS"), "min": ("op", "MIN"), "max": ("op", "MAX"), "intdiv": ("op", "TRUNCDIV"),
              "fmod": ("op", "FMOD"), "pow": ("pow_any",), **{k: ("op", v) for k, v in _F1.items()},
              "floor": ("op", "FLOOR"), "ceil": ("op", "CEIL"), "atan2": ("op", "ATAN2"), "is_nan": ("op", "ISNAN"),
              "gmp_gcd": ("no", "GMP numbers")}
_LUA_FUNCS = {"math.abs": ("op", "ABS"), "math.max": ("op", "MAX"), "math.min": ("op", "MIN"),
              "math.sqrt": ("op", "FSQRT"), "math.floor": ("lua_floor", "FLOOR"), "math.ceil": ("lua_floor", "CEIL"),
              "math.fmod": ("lua_fmod",), "math.exp": ("op", "EXP"), "math.log": ("op", "LOG"),
              "math.sin": ("op", "SIN"), "math.cos": ("op", "COS"), "math.tan": ("op", "TAN"),
              "math.atan": ("op", "ATAN"), "math.tointeger": ("cast", INT)}
_JULIA_FUNCS = {**{k: ("op", v) for k, v in _F1.items()}, "abs": ("op", "ABS"), "min": ("op", "MIN"),
                "max": ("op", "MAX"), "div": ("op", "TRUNCDIV"), "fld": ("op", "FLOORDIV"), "mod": ("op", "MOD"),
                "rem": ("op", "REM"), "gcd": ("op", "GCD"), "atan": ("op", "ATAN"), "xor": ("op", "BIT_XOR"),
                "count_ones": ("op", "POPCOUNT"), "Float64": ("cast", FLOAT), "float": ("cast", FLOAT),
                "isnan": ("op", "ISNAN"), "powermod": ("op", "POW_MOD"), "trunc": ("julia_round", "TRUNC"),
                "floor": ("julia_round", "FLOOR"), "ceil": ("julia_round", "CEIL"), "sqrt": ("op", "FSQRT"),
                "Int": ("no", "Int(x) throws InexactError on a non-integral float")}
_RUBY_FUNCS = {"Math.sqrt": ("op", "FSQRT"), "Math.exp": ("op", "EXP"), "Math.log": ("op", "LOG"),
               "Math.sin": ("op", "SIN"), "Math.cos": ("op", "COS"), "Math.tan": ("op", "TAN"),
               "Math.atan2": ("op", "ATAN2"), "Integer.sqrt": ("no", "Integer.sqrt has no op card")}

# x.method(args): (op | special, arity counting the receiver)
_METHODS_COMMON = {"abs": ("op", "ABS"), "min": ("op", "MIN"), "max": ("op", "MAX"), "sqrt": ("op", "FSQRT"),
                   "floor": ("op", "FLOOR"), "ceil": ("op", "CEIL"), "trunc": ("op", "TRUNC"),
                   "exp": ("op", "EXP"), "sin": ("op", "SIN"), "cos": ("op", "COS"), "tan": ("op", "TAN")}
_RUST_METHODS = {**_METHODS_COMMON, "ln": ("op", "LOG"), "powi": ("fpow",), "powf": ("fpow",), "pow": ("ipow",),
                 "is_nan": ("op", "ISNAN"), "count_ones": ("op", "POPCOUNT"), "leading_zeros": ("op", "CLZ64"),
                 "trailing_zeros": ("op", "CTZ64"), "rem_euclid": ("rem_euclid",), "signum": ("no", "signum"),
                 "atan2": ("op", "ATAN2"), "copysign": ("op", "COPYSIGN"), "clone": ("id",)}
_KOTLIN_METHODS = {**_METHODS_COMMON, "toDouble": ("cast", FLOAT), "toLong": ("cast", INT), "toInt": ("cast", INT),
                   "pow": ("fpow",), "mod": ("op", "MOD"), "rem": ("op", "REM"), "floorDiv": ("op", "FLOORDIV"),
                   "coerceAtLeast": ("op", "MAX"), "coerceAtMost": ("op", "MIN"), "countOneBits": ("op", "POPCOUNT"),
                   "isNaN": ("op", "ISNAN")}
_SWIFT_METHODS = {"squareRoot": ("op", "FSQRT"), "isMultiple": ("no", "isMultiple(of:)"),
                  "magnitude": ("op", "ABS"), "nonzeroBitCount": ("op", "POPCOUNT"), "isNaN": ("op", "ISNAN")}
_RUBY_METHODS = {"abs": ("op", "ABS"), "floor": ("ruby_round", "FLOOR"), "ceil": ("ruby_round", "CEIL"),
                 "truncate": ("ruby_round", "TRUNC"), "to_f": ("cast", FLOAT), "to_i": ("cast", INT),
                 "gcd": ("op", "GCD"), "pow": ("ruby_pow",), "fdiv": ("fdiv",), "div": ("op", "FLOORDIV"),
                 "modulo": ("op", "MOD"), "remainder": ("rem_any",), "even?": ("parity", 0), "odd?": ("parity", 1),
                 "zero?": ("zero",), "positive?": ("sign", ">"), "negative?": ("sign", "<"), "nan?": ("op", "ISNAN"),
                 "bit_length": ("no", "bit_length has no op card")}
_JS_METHODS = {"toString": ("no", "strings")}

_C_TYPES = {**{t: INT for t in _INT_C}, "double": FLOAT, "long double": FLOAT, "bool": BOOL, "_Bool": BOOL,
            "void": VOID, "auto": "auto"}
_C_TYPES.update({t: INT for t, k in _C_KINDS.items() if k[1] > 1})
_C_UNSUP = {**{t: _C_U64 for t in _UNSIGNED_C - _C_FIXED},
            "char": "char (a character; int8_t or uint8_t lift as small integers)",
            "float": "binary32 float (the IR float is binary64)"}


def _dialects() -> dict[str, Dialect]:
    d: dict[str, Dialect] = {}
    d["c"] = Dialect("c", preproc=True, truthy_ints=True, types=dict(_C_TYPES), unsupported_types=dict(_C_UNSUP),
                     funcs=dict(_C_FUNCS), emit_keys=("c", "c_like"))
    d["cpp"] = Dialect("cpp", preproc=True, truthy_ints=True,
                       types={**_C_TYPES, "std::int64_t": INT, "std::int32_t": INT, "int64": INT},
                       unsupported_types=dict(_C_UNSUP), funcs=dict(_C_FUNCS), emit_keys=("cpp", "c", "c_like"))
    d["java"] = Dialect("java", types={"long": INT, "int": INT, "short": INT, "byte": INT, "double": FLOAT,
                                        "boolean": BOOL, "void": VOID, "var": "auto"},
                        unsupported_types={"float": "binary32 float", "char": "char"}, funcs=dict(_JAVA_FUNCS),
                        emit_keys=("java", "c_like"))
    d["csharp"] = Dialect("csharp", preproc=True, types={"long": INT, "int": INT, "short": INT, "double": FLOAT,
                                                          "bool": BOOL, "void": VOID, "var": "auto",
                                                          "Int64": INT, "Int32": INT, "Double": FLOAT},
                          unsupported_types={"float": "binary32 float", "ulong": "unsigned", "uint": "unsigned",
                                             "decimal": "decimal"},
                          funcs=dict(_CS_FUNCS), emit_keys=("csharp", "c_like"))
    d["kotlin"] = Dialect("kotlin", prec=_KOTLIN_PREC, newline_ends=True, ternary=False,
                          types={"Long": INT, "Int": INT, "Short": INT, "Double": FLOAT, "Boolean": BOOL,
                                 "Unit": VOID},
                          unsupported_types={"Float": "binary32 float", "ULong": "unsigned", "UInt": "unsigned"},
                          decl_words=("var", "val"), funcs=dict(_KOTLIN_FUNCS), methods=dict(_KOTLIN_METHODS),
                          emit_keys=("kotlin", "java", "c_like"))
    d["go"] = Dialect("go", prec=_GO_PREC, newline_ends=True, ternary=False,
                      types={"int64": INT, "int": INT, "int32": INT, "int16": INT, "int8": INT, "float64": FLOAT,
                             "bool": BOOL},
                      unsupported_types={"float32": "binary32 float", "uint64": "unsigned", "uint": "unsigned",
                                         "uint32": "unsigned", "uint8": "unsigned", "byte": "unsigned"},
                      decl_words=("var", "const"), funcs=dict(_GO_FUNCS), emit_keys=("go", "c_like"),
                      casts={"float64": FLOAT, "int64": INT, "int": INT, "int32": INT})
    d["rust"] = Dialect("rust", prec=_RUST_PREC, ternary=False, implicit_return=True,
                        types={"i64": INT, "i32": INT, "i16": INT, "i8": INT, "i128": INT, "isize": INT,
                               "f64": FLOAT, "bool": BOOL, "()": VOID},
                        unsupported_types={"f32": "binary32 float", "u64": "unsigned", "u32": "unsigned",
                                           "usize": "unsigned", "u8": "unsigned", "u16": "unsigned",
                                           "u128": "unsigned"},
                        decl_words=("let", "const", "static"), methods=dict(_RUST_METHODS),
                        funcs={"i64::abs": ("op", "ABS"), "f64::sqrt": ("op", "FSQRT"), "i64::min": ("op", "MIN"),
                               "i64::max": ("op", "MAX"), "f64::min": ("op", "MIN"), "f64::max": ("op", "MAX"),
                               "f64::floor": ("op", "FLOOR"), "f64::abs": ("op", "ABS"),
                               "std::cmp::min": ("op", "MIN"), "std::cmp::max": ("op", "MAX"),
                               "min": ("op", "MIN"), "max": ("op", "MAX")},
                        consts={"std::f64::consts::PI": ["float", 3.141592653589793],
                                "std::f64::consts::E": ["float", 2.718281828459045],
                                "f64::consts::PI": ["float", 3.141592653589793]},
                        emit_keys=("rust", "c_like"))
    d["swift"] = Dialect("swift", prec=_SWIFT_PREC, newline_ends=True,
                         types={"Int": INT, "Int64": INT, "Int32": INT, "Double": FLOAT, "Float64": FLOAT,
                                "Bool": BOOL, "Void": VOID},
                         unsupported_types={"Float": "binary32 float", "UInt": "unsigned", "UInt64": "unsigned"},
                         decl_words=("var", "let"), funcs=dict(_SWIFT_FUNCS), methods=dict(_SWIFT_METHODS),
                         casts={"Double": FLOAT, "Int": INT, "Int64": INT, "Float64": FLOAT},
                         consts={"Double.pi": ["float", 3.141592653589793], ".pi": ["float", 3.141592653589793]},
                         emit_keys=("swift", "c_like"))
    d["zig"] = Dialect("zig", prec=_ZIG_PREC, ternary=False,
                       types={"i64": INT, "i32": INT, "i16": INT, "i8": INT, "isize": INT, "comptime_int": INT,
                              "f64": FLOAT, "bool": BOOL, "void": VOID},
                       unsupported_types={"f32": "binary32 float", "u64": "unsigned", "u32": "unsigned",
                                          "usize": "unsigned", "u8": "unsigned"},
                       decl_words=("var", "const"), sigils="@", funcs=dict(_ZIG_FUNCS), emit_keys=("zig", "c_like"))
    d["javascript"] = Dialect("javascript", newline_ends=True, truthy_ints=True, untyped="js", bigint_marker=True,
                              decl_words=("let", "const", "var"), sigils="$", funcs=dict(_JS_FUNCS),
                              methods=dict(_JS_METHODS), casts={"Number": FLOAT, "BigInt": INT},
                              consts={"Math.PI": ["float", 3.141592653589793], "Math.E": ["float", 2.718281828459045]},
                              emit_keys=("javascript", "c_like"))
    d["typescript"] = Dialect("typescript", newline_ends=True, truthy_ints=True, untyped="js", bigint_marker=True,
                              types={"bigint": INT, "number": FLOAT, "boolean": BOOL, "void": VOID},
                              decl_words=("let", "const", "var"), sigils="$", funcs=dict(_JS_FUNCS),
                              methods=dict(_JS_METHODS), casts={"Number": FLOAT, "BigInt": INT},
                              consts=dict(d["javascript"].consts), emit_keys=("typescript", "javascript", "c_like"))
    d["php"] = Dialect("php", line_comments=("//", "#"), int_div="true", truthy_ints=True, untyped=INT,
                       types={"int": INT, "float": FLOAT, "bool": BOOL, "void": VOID},
                       sigils="$", funcs=dict(_PHP_FUNCS), casts={"intval": INT, "floatval": FLOAT},
                       consts={"M_PI": ["float", 3.141592653589793], "PHP_INT_MAX": ["int", 2**63 - 1]},
                       else_if=("else if", "elseif"), emit_keys=("php",))
    d["ruby"] = Dialect("ruby", style="end", prec=_RUBY_PREC, line_comments=("#",), block_comments=(),
                        newline_ends=True, int_div="floor", int_mod="floor", implicit_return=True, untyped=INT,
                        ident_suffix="?!", funcs=dict(_RUBY_FUNCS), methods=dict(_RUBY_METHODS),
                        consts={"Math::PI": ["float", 3.141592653589793], "Math::E": ["float", 2.718281828459045]},
                        else_if=("elsif",), emit_keys=("ruby",))
    d["lua"] = Dialect("lua", style="end", prec=_LUA_PREC, line_comments=("--",), block_comments=(("--[[", "]]"),),
                       newline_ends=True, int_div="true", int_mod="floor", caret="pow", ternary=False, untyped=INT,
                       decl_words=("local",), funcs=dict(_LUA_FUNCS),
                       consts={"math.pi": ["float", 3.141592653589793], "math.maxinteger": ["int", 2**63 - 1],
                               "math.mininteger": ["int", -(2**63)]},
                       else_if=("elseif",), emit_keys=("lua",))
    d["julia"] = Dialect("julia", style="end", prec=_JULIA_PREC, line_comments=("#",), block_comments=(("#=", "=#"),),
                         newline_ends=True, int_div="true", int_mod="rem", caret="pow", implicit_return=True,
                         untyped=INT,
                         types={"Int": INT, "Int64": INT, "Int32": INT, "Integer": INT, "Float64": FLOAT,
                                "Bool": BOOL, "Nothing": VOID, "Real": FLOAT},
                         unsupported_types={"Float32": "binary32 float", "UInt64": "unsigned", "UInt": "unsigned",
                                            "BigInt": "arbitrary precision is not Int64"},
                         decl_words=("local",), ident_suffix="!", funcs=dict(_JULIA_FUNCS),
                         consts={"pi": ["float", 3.141592653589793], "π": ["float", 3.141592653589793]},
                         else_if=("elseif",), emit_keys=("julia",))
    return d


DIALECTS = _dialects()


class Unsupported(Exception):
    def __init__(self, what: str, line: int | None = None):
        self.what = what
        self.line = line
        super().__init__(f"line {line}: {what}" if line else what)


@dataclass
class Lifted:
    """Same shape as frontend_python.Lifted (module_for and translate read name/ok/ir/source/reasons)."""
    name: str
    ok: bool
    ir: dict | None = None
    source: str = ""
    reasons: list[str] = field(default_factory=list)
    inferred_types: bool = False
    lineno: int = 0
    lang: str = ""
    src_types: list = field(default_factory=list)   # parameter types as the source spells them (harness casts)


# -- tokens ----------------------------------------------------------------------------------------------------------

@dataclass
class Tok:
    kind: str          # num | id | op | str | nl | eof
    text: str
    line: int
    value: object = None
    suffix: str = ""
    space_before: bool = False


_OPS = sorted([">>>=", "<<=", ">>=", "**=", "//=", "...", "..<", "..=", "===", "!==", "%/%", "&&=", "||=", "<=>",
               "->", "=>", "::", ":=", "==", "!=", "~=", "<=", ">=", "&&", "||", "<<", ">>", ">>>", "++", "--",
               "+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=", "**", "//", "..", "&^", "%%", "?.", "÷=", "÷", "⊻",
               "+", "-", "*", "/", "%", "&", "|", "^", "~", "!", "<", ">", "=", "?", ":", ";", ",", ".", "(", ")",
               "{", "}", "[", "]", "#", "@", "\\"], key=len, reverse=True)
_NUM = re.compile(r"0[xX][0-9a-fA-F_]+|0[bB][01_]+|0[oO][0-7_]+|(?:\d[\d_]*)(?:\.\d[\d_]*)?(?:[eE][+-]?\d+)?")


def tokenize(src: str, d: Dialect) -> list[Tok]:
    toks: list[Tok] = []
    i, n, line = 0, len(src), 1
    depth = 0                           # () and [] nesting: newlines inside are not statement ends
    space = False
    line_start = True
    ops = list(_OPS)
    if d.name == "lua":
        ops = [o for o in ops if o not in ("~=",)] + ["~="]
        ops.sort(key=len, reverse=True)
    while i < n:
        c = src[i]
        if c == "\n":
            if depth == 0 and d.newline_ends and toks and toks[-1].kind != "nl":
                toks.append(Tok("nl", "\n", line))
            line += 1
            i += 1
            line_start = True
            space = True
            continue
        if c in " \t\r\f":
            i += 1
            space = True
            continue
        if c == "\\" and src.startswith("\\\n", i):       # line continuation
            i += 2
            line += 1
            continue
        if d.preproc and c == "#" and line_start:
            j = src.find("\n", i)
            i = n if j < 0 else j
            continue
        hit = False
        for open_, close in d.block_comments:
            if src.startswith(open_, i):
                j = src.find(close, i + len(open_))
                j = n if j < 0 else j + len(close)
                line += src.count("\n", i, j)
                i = j
                hit = True
                break
        if hit:
            space = True
            continue
        if d.name == "ruby" and line_start and src.startswith("=begin", i):
            j = src.find("=end", i)
            j = n if j < 0 else j + 4
            line += src.count("\n", i, j)
            i = j
            continue
        for lc in d.line_comments:
            if src.startswith(lc, i) and not (d.name == "lua" and lc == "--" and src.startswith("--[[", i)):
                j = src.find("\n", i)
                i = n if j < 0 else j
                hit = True
                break
        if hit:
            space = True
            continue
        line_start = False
        if c.isdigit() or (c == "." and i + 1 < n and src[i + 1].isdigit() and (not toks or toks[-1].text != ".")):
            m = _NUM.match(src, i)
            text = m.group(0) if m and m.group(0) else c
            j = i + len(text)
            k = j
            while k < n and (src[k].isalnum() or src[k] == "_") and d.name not in ("julia",):
                k += 1
            if d.name == "julia":
                k = j
            suffix = src[j:k]
            clean = text.replace("_", "")
            if clean.lower().startswith(("0x", "0b", "0o")):
                value = int(clean, 0)
            elif any(ch in clean for ch in ".eE"):
                value = float(clean)
            elif d.name in ("c", "cpp") and len(clean) > 1 and clean[0] == "0" and clean.isdigit():
                value = int(clean, 8)                     # C's 017 is octal
            else:
                value = int(clean)
            toks.append(Tok("num", src[i:k], line, value, suffix, space))
            i = k
            space = False
            continue
        if c.isalpha() or c == "_" or (c in d.sigils and i + 1 < n and (src[i + 1].isalpha() or src[i + 1] == "_")) \
                or ord(c) > 127 and c not in "÷⊻":
            j = i + 1
            while j < n and (src[j].isalnum() or src[j] == "_" or ord(src[j]) > 127 and src[j] not in "÷⊻"):
                j += 1
            if d.ident_suffix and j < n and src[j] in d.ident_suffix and not src.startswith("=", j + 1) \
                    and not src.startswith("==", j):
                j += 1
            text = src[i:j]
            if d.name == "php" and text.startswith("$"):
                text = text[1:]
            toks.append(Tok("id", text, line, None, "", space))
            i = j
            space = False
            continue
        if c in "\"'`":
            if d.name == "rust" and c == "'" and i + 2 < n and src[i + 2] != "'" and \
                    (src[i + 1].isalpha() or src[i + 1] == "_"):
                i += 1                                    # a lifetime: 'a
                continue
            j = i + 1
            while j < n and src[j] != c:
                if src[j] == "\\":
                    j += 1
                if j < n and src[j] == "\n":
                    line += 1
                j += 1
            toks.append(Tok("str", src[i:j + 1], line, None, "", space))
            i = j + 1
            space = False
            continue
        for op in ops:
            if src.startswith(op, i):
                if op in ("(", "["):
                    depth += 1
                elif op in (")", "]"):
                    depth = max(0, depth - 1)
                toks.append(Tok("op", op, line, None, "", space))
                i += len(op)
                break
        else:
            toks.append(Tok("op", c, line, None, "", space))
            i += 1
        space = False
    toks.append(Tok("eof", "", line))
    return toks


# -- parser ----------------------------------------------------------------------------------------------------------
# expressions: ("num", value, suffix) ("bool", v) ("name", path) ("bin", op, a, b) ("un", op, a)
#              ("call", path, args, labels) ("mcall", recv, name, args) ("tern", c, a, b) ("cast", type, a)
#              ("range", a, b, kind, step) ("tuple", [items]) ("block_if", cond, then_stmts, else_stmts)
# statements:  dicts with "k" and "line"


class ParseError(Exception):
    def __init__(self, what: str, line: int):
        self.what = what
        self.line = line
        super().__init__(f"line {line}: {what}")


class Parser:
    END_OPENERS = {"if", "while", "for", "function", "def", "do", "begin", "case", "class", "module", "unless",
                   "until", "repeat", "let", "struct", "quote", "macro", "try"}

    def __init__(self, toks: list[Tok], d: Dialect):
        self.t = toks
        self.i = 0
        self.d = d
        self.bin = {}
        for bp, ops in d.prec:
            for op in ops:
                self.bin[op] = bp
        self.no_brace_expr = False      # Go/Rust/Swift: `if x {` — a `{` after a name is the block, not a literal
        self.no_colon = False           # Julia: inside `c ? a : b`, `:` is not a range

    # token helpers
    def peek(self, k: int = 0) -> Tok:
        j = min(self.i + k, len(self.t) - 1)
        return self.t[j]

    def next(self) -> Tok:
        tok = self.t[self.i]
        self.i = min(self.i + 1, len(self.t) - 1)
        return tok

    def at(self, *texts) -> bool:
        tok = self.peek()
        return tok.kind in ("op", "id") and tok.text in texts

    def accept(self, *texts) -> Tok | None:
        if self.at(*texts):
            return self.next()
        return None

    def expect(self, text: str) -> Tok:
        tok = self.peek()
        if tok.kind in ("op", "id") and tok.text == text:
            return self.next()
        raise ParseError(f"expected {text!r}, found {tok.text!r}" if tok.kind != "eof" else f"expected {text!r}",
                         tok.line)

    def skip_nl(self) -> None:
        while self.peek().kind == "nl" or (self.peek().kind == "op" and self.peek().text == ";"):
            self.next()

    def skip_newlines(self) -> None:
        while self.peek().kind == "nl":
            self.next()

    def ident(self) -> str:
        tok = self.next()
        if tok.kind != "id":
            raise ParseError(f"expected a name, found {tok.text!r}", tok.line)
        return tok.text

    def end_stmt(self) -> None:
        tok = self.peek()
        if tok.kind == "op" and tok.text == ";":
            self.next()
            return
        if tok.kind in ("nl", "eof") or (tok.kind == "op" and tok.text == "}") or \
                (tok.kind == "id" and tok.text == "else"):
            return
        if self.d.style == "end" and tok.kind == "id" and tok.text in ("end", "else", "elsif", "elseif", "then",
                                                                         "until"):
            return
        if self.d.newline_ends and tok.kind != "nl":
            raise ParseError(f"unexpected {tok.text!r}", tok.line)
        raise ParseError(f"expected ';', found {tok.text!r}", tok.line)

    # -- types -----------------------------------------------------------------------------------------------------
    def type_name(self, ptr_ok: bool = False) -> str:
        """A type as text: `long long`, `std::int64_t`, `i64`, `Int`, `()`, `[]int` (rejected later). ``ptr_ok``: a
        C parameter's `*` / `[]` that follows is left for the caller (arrays lift as lists)."""
        parts = []
        if self.accept("("):
            self.expect(")")
            return "()"
        while self.peek().kind == "id" and self.peek().text in ("const", "mut", "final", "readonly", "constexpr",
                                                                   "volatile", "register", "signed") \
                and not (self.peek().text == "signed" and self.peek(1).kind != "id"):
            if self.peek().text == "signed":
                parts.append(self.next().text)
            else:
                self.next()
        tok = self.next()
        if tok.kind != "id" and not (tok.kind == "op" and tok.text in ("[", "*", "&", "?")):
            raise ParseError(f"expected a type, found {tok.text!r}", tok.line)
        if tok.kind == "op":
            raise ParseError(f"type {tok.text}... (pointers, references, arrays, optionals are not lifted)", tok.line)
        parts.append(tok.text)
        while True:
            if self.at("::") and self.peek(1).kind == "id":
                self.next()
                parts[-1] += "::" + self.next().text
            elif self.at(".") and self.peek(1).kind == "id" and self.d.name in ("java", "csharp", "kotlin", "zig"):
                self.next()
                parts[-1] += "." + self.next().text
            elif self.peek().kind == "id" and parts[-1] in ("long", "unsigned", "signed", "short") and \
                    self.peek().text in ("long", "int", "char", "short", "double") and \
                    not (self.peek(1).kind == "op" and self.peek(1).text in ("(", ",", ")", "=", ";")):
                parts.append(self.next().text)
            else:
                break
        text = " ".join(parts)
        if self.at("<"):
            raise ParseError(f"generic type {text}<...> is not lifted", self.peek().line)
        if ptr_ok and self.d.name == "c" and self.at("*", "**"):
            return text
        if self.at("*", "&", "[", "?") and self.d.name in ("c", "cpp", "csharp", "java", "kotlin", "swift", "typescript"):
            if self.at("[") and self.peek(1).text == "]" or self.at("*", "&", "?"):
                raise ParseError(f"type {text}{self.peek().text} (pointers, references, arrays, nullables)",
                                 self.peek().line)
        return text

    # -- expressions -----------------------------------------------------------------------------------------------
    def expr(self, min_bp: float = 0) -> tuple:
        left = self.unary()
        while True:
            tok = self.peek()
            if tok.kind not in ("op", "id"):
                break
            op = tok.text
            if op == "?" and self.d.ternary and min_bp <= 0.4:
                self.next()
                self.skip_newlines()
                save, self.no_colon = self.no_colon, True
                try:
                    a = self.expr(0.4)
                finally:
                    self.no_colon = save
                self.skip_newlines()
                self.expect(":")
                self.skip_newlines()
                b = self.expr(0.4)
                left = ("tern", left, a, b)
                continue
            if op in ("..", "..<", "...", "..=", "until", "downTo") and min_bp <= 0.45 and self._range_ok(op):
                self.next()
                if op in ("..", "...", "..=", "..<") and self._range_open_end():
                    raise ParseError("open-ended range", tok.line)
                b = self.expr(0.46)
                kind = {"..": "excl" if self.d.name in ("rust", "zig") else "incl", "...": "incl" if
                        self.d.name == "swift" else "excl", "..=": "incl", "..<": "excl", "until": "excl",
                        "downTo": "down"}[op]
                if self.d.name == "ruby" and op == "...":
                    kind = "excl"
                left = ("range", left, b, kind, None)
                continue
            if op == "step" and self.d.name == "kotlin" and left[0] == "range":
                self.next()
                s = self.expr(0.46)
                left = ("range", left[1], left[2], left[3], s)
                continue
            if op == ":" and self.d.name == "julia" and min_bp <= 2.5 and not self.no_colon:
                self.next()
                b = self.expr(2.6)
                if self.at(":"):
                    self.next()
                    c = self.expr(2.6)
                    left = ("range", left, c, "incl", b)
                else:
                    left = ("range", left, b, "incl", None)
                continue
            if op == "as" and self.d.name == "rust":
                self.next()
                left = ("cast", self.type_name(), left)
                continue
            if op in ("as", "is") and self.d.name in ("swift", "kotlin", "typescript", "csharp"):
                raise ParseError(f"`{op}` casts are not lifted", tok.line)
            if op == "::" and self.d.name == "julia":
                self.next()
                left = ("ann", self.type_name(), left)
                continue
            bp = self.bin.get(op)
            if self.d.caret == "pow" and op == "^":
                bp = 12
            if bp is None or bp < min_bp or (tok.kind == "id" and op not in ("and", "or", "xor", "shl", "shr",
                                                                            "ushr")):
                break
            # `*` at the start of a line after a complete expression is never a continuation (Go/Swift/Kotlin/JS)
            self.next()
            self.skip_newlines()
            right_assoc = op in ("**",) or (op == "^" and self.d.caret == "pow")
            right = self.expr(bp if right_assoc else bp + 0.01)
            left = ("bin", op, left, right)
        return left

    def _range_ok(self, op: str) -> bool:
        if op in ("until", "downTo"):
            return self.d.name == "kotlin"
        if op == "...":
            return self.d.name in ("swift", "ruby")
        if op == "..<":
            return self.d.name in ("swift", "kotlin")
        if op == "..=":
            return self.d.name == "rust"
        return self.d.name in ("rust", "kotlin", "ruby", "zig")

    def _range_open_end(self) -> bool:
        tok = self.peek()
        return tok.kind in ("nl", "eof") or tok.kind == "op" and tok.text in (")", "]", "{", ";", ",")

    def unary(self) -> tuple:
        tok = self.peek()
        if tok.kind == "op" and (tok.text in ("-", "+", "!", "~") or tok.text == "^" and self.d.name == "go") \
                or tok.kind == "id" and tok.text == "not":
            self.next()
            bp = 11
            if self.d.name in ("rust", "swift", "go", "zig"):
                bp = 99
            if tok.text == "not" and self.d.name != "lua":
                bp = 2.5
            operand = self.expr(bp)
            op = {"not": "!"}.get(tok.text, tok.text)
            if self.d.name == "lua" and op == "~":
                op = "~"
            return ("un", op, operand)
        if tok.kind == "op" and tok.text in ("++", "--"):
            raise ParseError(f"{tok.text} inside an expression", tok.line)
        return self.postfix(self.primary())

    def args(self, close: str = ")") -> tuple[list, list]:
        args, labels = [], []
        self.skip_newlines()
        while not self.at(close):
            label = None
            if self.peek().kind == "id" and self.peek(1).kind == "op" and self.peek(1).text == ":" \
                    and self.d.name in ("swift", "kotlin", "csharp", "php"):
                label = self.next().text
                self.next()
            elif self.peek().kind == "id" and self.peek(1).kind == "op" and self.peek(1).text == "=" \
                    and self.d.name in ("kotlin",):
                label = self.next().text
                self.next()
            args.append(self.expr())
            labels.append(label)
            self.skip_newlines()
            if not self.accept(","):
                break
            self.skip_newlines()
        self.expect(close)
        return args, labels

    def primary(self) -> tuple:
        tok = self.next()
        if tok.kind == "num":
            return ("num", tok.value, tok.suffix, tok.text)
        if tok.kind == "str":
            raise ParseError("string literal", tok.line)
        if tok.kind == "op" and tok.text == "(":
            self.skip_newlines()
            if self.d.name == "lua" and self.at("function") and self.peek(1).text == "(" and self.peek(2).text == ")":
                ftok = self.next()
                iife = self._iife(ftok)
                if iife is None:
                    raise ParseError("closure", tok.line)
                self.expect(")")
                self.expect("(")
                self.expect(")")
                return iife
            if self.at(")"):
                raise ParseError("empty tuple", tok.line)
            e = self.expr()
            self.skip_newlines()
            if self.at(","):
                items = [e]
                while self.accept(","):
                    self.skip_newlines()
                    if self.at(")"):
                        break
                    items.append(self.expr())
                    self.skip_newlines()
                self.expect(")")
                return ("tuple", items)
            self.expect(")")
            if self._c_cast_follows(e):
                return ("cast", e[1], self.unary())
            return e
        if tok.kind == "op" and tok.text == "[" and self.d.name in ("javascript", "typescript", "php"):
            items, _ = self.args("]")
            return ("tuple", items)
        if tok.kind == "op" and tok.text == "." and self.d.name == "swift" and self.peek().kind == "id":
            return ("name", "." + self.next().text)
        if tok.kind == "op" and tok.text == "@" and self.d.name in ("kotlin", "java", "swift"):
            raise ParseError("annotation inside an expression", tok.line)
        if tok.kind == "id":
            text = tok.text
            if text in ("true", "false", "True", "False", "TRUE", "FALSE"):
                return ("bool", text.lower() == "true")
            if text in ("null", "nil", "None", "nullptr", "undefined", "nothing", "NULL"):
                raise ParseError(f"{text} (no null in the IR)", tok.line)
            if text == "if" and self.d.name in ("rust", "kotlin", "zig", "julia", "ruby"):
                return self.if_expr(tok)
            if text == "new":
                raise ParseError("object construction", tok.line)
            if text in ("static_cast", "std::static_cast") and self.at("<"):
                self.next()
                typ = self.type_name()
                self.expect(">")
                self.expect("(")
                inner = self.expr()
                self.expect(")")
                return ("cast", typ, inner)
            if text == "func" and self.at("(") and self.peek(1).text == ")":
                iife = self._iife(tok)
                if iife is not None:
                    return iife
            if text in ("fn", "func", "function", "lambda", "proc") and self.at("("):
                raise ParseError("closure", tok.line)
            path = text
            while True:
                if self.at("::") and self.peek(1).kind == "id":
                    self.next()
                    path += "::" + self.next().text
                elif self.at(".") and self.peek(1).kind == "id" and self.d.name not in ("php",):
                    self.next()
                    path += "." + self.next().text
                elif self.at("->") and self.d.name == "php" and self.peek(1).kind == "id":
                    raise ParseError("object property access", tok.line)
                else:
                    break
            if self.at("!") and self.d.name == "rust" and self.peek(1).text in ("(", "["):
                raise ParseError(f"macro {path}!", tok.line)
            if self.at("<") and self.d.name in ("rust",) and self.peek(1).kind == "id" and self.peek(2).text == ">":
                raise ParseError("turbofish / generic call", tok.line)
            return ("name", path)
        raise ParseError(f"unexpected {tok.text!r}", tok.line)

    def _iife(self, tok):
        """codegen's conditional expression in Go and Lua: `func() T { if c { return a }; return b }()` and
        `(function() if c then return a else return b end end)()`."""
        save = self.i
        try:
            self.expect("(")
            self.expect(")")
            if self.d.name == "go":
                self.type_name()
                self.expect("{")
                self.expect("if")
                c = self.cond_expr()
                self.expect("{")
                self.expect("return")
                a = self.expr()
                self.skip_nl()
                self.expect("}")
                self.skip_nl()
                self.expect("return")
                b = self.expr()
                self.skip_nl()
                self.expect("}")
            elif self.d.name == "lua":
                self.expect("if")
                c = self.expr()
                self.expect("then")
                self.expect("return")
                a = self.expr()
                self.expect("else")
                self.expect("return")
                b = self.expr()
                self.expect("end")
                self.expect("end")
            else:
                raise ParseError("closure", tok.line)
            if self.d.name == "go":
                self.expect("(")
                self.expect(")")
            return ("tern", c, a, b)
        except ParseError:
            self.i = save
            return None

    def _c_cast_follows(self, e) -> bool:
        if self.d.name not in ("c", "cpp", "java", "csharp") or e[0] != "name":
            return False
        if e[1] not in self.d.types and e[1] not in self.d.unsupported_types:
            return False
        tok = self.peek()
        return tok.kind in ("num", "id") or tok.kind == "op" and tok.text in ("(", "-", "!", "~", "+")

    def postfix(self, e: tuple) -> tuple:
        while True:
            tok = self.peek()
            if tok.kind == "op" and tok.text == "(" and not (tok.space_before and self.d.name == "ruby"):
                self.next()
                args, labels = self.args(")")
                if self.d.name == "kotlin" and self.at("{"):
                    raise ParseError("trailing lambda", self.peek().line)
                if e[0] == "name":
                    e = ("call", e[1], args, labels)
                elif e[0] == "attr":
                    e = ("mcall", e[1], e[2], args)
                else:
                    raise ParseError("call of a computed value", tok.line)
                continue
            if tok.kind == "op" and tok.text == "." and self.peek(1).kind == "id":
                self.next()
                name = self.next().text
                if e[0] == "name":
                    e = ("name", e[1] + "." + name)
                elif e[0] == "call" or e[0] == "mcall" or e[0] in ("num", "bin", "un", "tern", "cast", "tuple"):
                    e = ("attr", e, name)
                    if not self.at("("):
                        e = ("mcall", e[1], e[2], [])
                else:
                    e = ("attr", e, name)
                    if not self.at("("):
                        e = ("mcall", e[1], e[2], [])
                continue
            if tok.kind == "op" and tok.text == "[" and self.d.name == "c":
                self.next()
                idx = self.expr()
                self.expect("]")
                if self.at("["):
                    raise ParseError("multi-dimensional indexing", tok.line)
                e = ("index", e, idx)
                continue
            if tok.kind == "op" and tok.text == "[":
                raise ParseError("indexing (arrays are not lifted)", tok.line)
            if tok.kind == "op" and tok.text == "?" and self.d.name == "rust":
                raise ParseError("? operator", tok.line)
            if tok.kind == "op" and tok.text == "!" and self.d.name in ("kotlin", "swift", "typescript") \
                    and not tok.space_before and self.peek(1).text != "=":
                raise ParseError("non-null assertion", tok.line)
            break
        return e

    def if_expr(self, tok) -> tuple:
        """Rust `if c { a } else { b }`, Kotlin/Zig `if (c) a else b`, Ruby/Julia `if c then a else b end` as a
        value."""
        cond = self.cond_expr()
        if self.d.name == "rust":
            then = self.block()
            self.expect("else")
            if self.at("if"):
                t2 = self.next()
                other = [{"k": "expr", "value": self.if_expr(t2), "line": t2.line}]
            else:
                other = self.block()
            return ("block_if", cond, then, other)
        if self.d.name in ("ruby", "julia"):
            self.accept("then")
            then = self.end_block(("else", "elsif", "elseif", "end"))
            other = []
            if self.accept("else"):
                other = self.end_block(("end",))
            elif self.at("elsif", "elseif"):
                t2 = self.next()
                other = [{"k": "expr", "value": self.if_expr(t2), "line": t2.line}]
                return ("block_if", cond, then, other)
            self.expect("end")
            return ("block_if", cond, then, other)
        self.skip_newlines()
        if self.at("{"):
            then = self.block()
        else:
            then = [{"k": "expr", "value": self.expr(), "line": tok.line}]
        self.skip_newlines()
        self.expect("else")
        self.skip_newlines()
        if self.at("{"):
            other = self.block()
        else:
            other = [{"k": "expr", "value": self.expr(), "line": tok.line}]
        return ("block_if", cond, then, other)

    PAREN_COND = ("c", "cpp", "java", "csharp", "kotlin", "zig", "javascript", "typescript", "php")

    def cond_expr(self) -> tuple:
        """A condition: the C family wraps it in parens (exactly one parenthesised expression, so Kotlin's
        `if (c) -1 else 0` is not `(c) - 1`); Go, Rust and Swift do not and the next `{` opens the block."""
        if self.d.name in self.PAREN_COND:
            self.expect("(")
            self.skip_newlines()
            e = self.expr()
            self.skip_newlines()
            self.expect(")")
            return e
        save = self.no_brace_expr
        self.no_brace_expr = True
        try:
            return self.expr()
        finally:
            self.no_brace_expr = save

    # -- statements: brace languages -------------------------------------------------------------------------------
    def block(self) -> list[dict]:
        self.skip_newlines()
        self.expect("{")
        out: list[dict] = []
        while True:
            self.skip_nl()
            if self.accept("}"):
                return out
            if self.peek().kind == "eof":
                raise ParseError("unclosed block", self.peek().line)
            out.extend(self.statement())

    def body_or_stmt(self) -> list[dict]:
        self.skip_newlines()
        if self.at("{"):
            return self.block()
        return self.statement()

    def statement(self) -> list[dict]:
        if self.d.style == "end":
            return self.end_statement()
        tok = self.peek()
        line = tok.line
        if tok.kind == "op" and tok.text == "{":
            return [{"k": "block", "body": self.block(), "line": line}]
        if tok.kind == "op" and tok.text == "@" and self.d.name in ("kotlin", "java", "swift"):
            self.next()
            self.ident()
            if self.at("("):
                self.next()
                self.args(")")
            return []
        if tok.kind == "op" and tok.text == "#" and self.d.name == "rust":
            self.skip_attribute()
            return []
        if tok.kind == "id":
            w = tok.text
            if w == "if":
                return [self.if_stmt()]
            if w == "while":
                self.next()
                cond = self.cond_expr()
                cont = None
                if self.d.name == "zig" and self.accept(":"):
                    self.expect("(")
                    cont = self.simple_statement(allow_decl=False, allow_end=False)
                    self.expect(")")
                body = self.body_or_stmt()
                if cont:
                    return [{"k": "for_c", "init": [], "cond": cond, "step": cont, "body": body, "line": line}]
                return [{"k": "while", "cond": cond, "body": body, "line": line}]
            if w == "do" and self.d.name not in ("lua",):
                self.next()
                body = self.body_or_stmt()
                self.skip_newlines()
                self.expect("while")
                cond = self.cond_expr()
                self.end_stmt()
                return [{"k": "do_while", "cond": cond, "body": body, "line": line}]
            if w == "repeat" and self.d.name == "swift":
                self.next()
                body = self.block()
                self.expect("while")
                cond = self.cond_expr()
                self.end_stmt()
                return [{"k": "do_while", "cond": cond, "body": body, "line": line}]
            if w == "loop" and self.d.name == "rust":
                self.next()
                return [{"k": "while", "cond": ("bool", True), "body": self.block(), "line": line}]
            if w == "for":
                return [self.for_stmt()]
            if w == "return":
                self.next()
                if self.peek().kind in ("nl", "eof") or self.at(";", "}"):
                    self.end_stmt()
                    return [{"k": "return", "value": None, "line": line}]
                e = self.expr()
                self.end_stmt()
                return [{"k": "return", "value": e, "line": line}]
            if w in ("break", "continue"):
                self.next()
                if self.peek().kind == "id" and self.d.name in ("go", "java", "kotlin", "swift", "javascript",
                                                                "typescript"):
                    raise ParseError(f"labelled {w}", line)
                if self.d.name == "php" and self.peek().kind == "num":
                    raise ParseError(f"{w} N", line)
                self.end_stmt()
                return [{"k": w, "line": line}]
            if w in ("switch", "match", "when", "try", "throw", "goto", "defer", "guard", "unsafe", "select", "go"):
                raise ParseError(f"`{w}` statement", line)
        return self.simple_statement()

    def skip_attribute(self) -> None:
        self.expect("#")
        self.accept("!")
        self.expect("[")
        depth = 1
        while depth and self.peek().kind != "eof":
            t = self.next()
            if t.text == "[":
                depth += 1
            elif t.text == "]":
                depth -= 1

    def if_stmt(self) -> dict:
        line = self.next().line
        cond = self.cond_expr()
        then = self.body_or_stmt()
        other: list[dict] = []
        save = self.i
        self.skip_nl() if self.d.newline_ends else None
        if self.at("else", "elseif"):
            if self.next().text == "elseif" or self.at("if"):
                other = [self.if_stmt()] if self.at("if") else [self._if_rest(line)]
            else:
                other = self.body_or_stmt()
        else:
            self.i = save
        return {"k": "if", "cond": cond, "then": then, "else": other, "line": line}

    def _if_rest(self, line) -> dict:
        cond = self.cond_expr()
        then = self.body_or_stmt()
        other: list[dict] = []
        save = self.i
        self.skip_nl()
        if self.at("else", "elseif"):
            if self.next().text == "elseif" or self.at("if"):
                other = [self.if_stmt()] if self.at("if") else [self._if_rest(line)]
            else:
                other = self.body_or_stmt()
        else:
            self.i = save
        return {"k": "if", "cond": cond, "then": then, "else": other, "line": line}

    def for_stmt(self) -> dict:
        line = self.next().line
        d = self.d.name
        if d == "go":
            if self.at("{"):
                return {"k": "while", "cond": ("bool", True), "body": self.block(), "line": line}
            # for i := range n {   /   for init; cond; post {   /   for cond {
            if self.peek().kind == "id" and self.peek(1).text == ":=" and self.peek(2).text == "range":
                var = self.ident()
                self.next()
                self.next()
                stop = self.cond_expr()
                return {"k": "for_range", "var": var, "start": ("num", 0, ""), "stop": stop, "step": 1,
                        "body": self.block(), "line": line, "decl_type": None}
            first = self.simple_statement(allow_end=False) if not self.at(";") else []
            if self.accept(";"):
                cond = ("bool", True) if self.at(";") else self.cond_expr()
                self.expect(";")
                step = [] if self.at("{") else self.simple_statement(allow_end=False)
                return {"k": "for_c", "init": first, "cond": cond, "step": step, "body": self.block(), "line": line}
            if len(first) == 1 and first[0]["k"] == "expr":
                return {"k": "while", "cond": first[0]["value"], "body": self.block(), "line": line}
            raise ParseError("for clause", line)
        if d in ("rust", "swift", "kotlin", "javascript", "typescript") and (
                (self.peek().kind == "id" and self.peek(1).text == "in") or
                (self.at("(") and self.peek(1).kind == "id" and self.peek(2).text == "in") or
                (self.at("(") and self.peek(1).text in ("let", "const", "var") and self.peek(3).text in ("of", "in"))):
            paren = self.accept("(")
            if paren and self.at("let", "const", "var"):
                raise ParseError("for ... of / for ... in over a collection", line)
            var = self.ident()
            if var == "mut":
                var = self.ident()
            self.expect("in")
            it = self.expr()
            if paren:
                self.expect(")")
            return {"k": "for_iter", "var": var, "iter": it, "body": self.body_or_stmt(), "line": line}
        if d == "zig":
            self.expect("(")
            it = self.expr()
            self.expect(")")
            self.expect("|")
            var = self.ident()
            self.expect("|")
            return {"k": "for_iter", "var": var, "iter": it, "body": self.block(), "line": line}
        self.expect("(")
        if self.peek().kind == "id" and self.peek(1).text == ":" and d in ("java", "cpp"):
            raise ParseError("for-each over a collection", line)
        init = [] if self.at(";") else self.simple_statement(allow_end=False)
        if self.at(":") or self.at("in") or self.at("of"):
            raise ParseError("for-each over a collection", line)
        self.expect(";")
        cond = ("bool", True) if self.at(";") else self.expr()
        self.expect(";")
        step: list[dict] = []
        while not self.at(")"):
            step.extend(self.simple_statement(allow_end=False))
            if not self.accept(","):
                break
        self.expect(")")
        return {"k": "for_c", "init": init, "cond": cond, "step": step, "body": self.body_or_stmt(), "line": line}

    def _is_c_decl(self) -> bool:
        """`Type name ...` at the start of a statement (C, C++, Java, C#)."""
        if self.d.name not in ("c", "cpp", "java", "csharp"):
            return False
        j = self.i
        toks = self.t
        while toks[j].kind == "id" and toks[j].text in ("const", "final", "static", "register", "volatile",
                                                         "constexpr", "unsigned", "signed"):
            if toks[j].text in ("unsigned", "signed") and toks[j + 1].kind != "id":
                return True
            if toks[j].text in ("unsigned", "signed") and toks[j + 1].text not in ("int", "long", "short", "char") \
                    and toks[j + 2].kind == "op" and toks[j + 2].text in ("=", ";", ","):
                return True                                  # unsigned s = 0;
            j += 1
        if toks[j].kind != "id":
            return False
        name = toks[j].text
        j += 1
        while toks[j].kind == "op" and toks[j].text == "::" and toks[j + 1].kind == "id":
            name += "::" + toks[j + 1].text
            j += 2
        if name in ("return", "break", "continue", "else"):
            return False
        while toks[j].kind == "id" and toks[j].text in ("long", "int", "short", "char", "double"):
            j += 1
        if toks[j].kind == "op" and toks[j].text in ("*", "&") and toks[j + 1].kind == "id" and \
                (name in self.d.types or name in self.d.unsupported_types):
            return True
        return toks[j].kind == "id" and (name in self.d.types or name in self.d.unsupported_types or
                                         toks[j + 1].kind == "op" and toks[j + 1].text in ("=", ";", ","))

    def _c_array_decl(self, name: str, typ: str, line: int) -> dict:
        """`T a[n];`, `T a[n] = {0};`, `T a[] = {x, y, z};` (one dimension): a local list."""
        self.expect("[")
        size = None if self.at("]") else self.expr()
        self.expect("]")
        if self.at("["):
            raise ParseError("multi-dimensional array", line)
        init = None
        if self.accept("="):
            if not self.accept("{"):
                raise ParseError("array initialised from an expression", line)
            init = []
            while not self.at("}"):
                if self.at("[") or self.at("."):
                    raise ParseError("designated initialiser", line)
                init.append(self.expr())
                if not self.accept(","):
                    break
            self.expect("}")
        if size is None and init is None:
            raise ParseError("array without a size", line)
        return {"k": "adecl", "name": name, "type": typ, "size": size, "init": init, "line": line}

    def simple_statement(self, allow_decl: bool = True, allow_end: bool = True) -> list[dict]:
        tok = self.peek()
        line = tok.line
        out: list[dict] = []
        if allow_decl and tok.kind == "id" and tok.text in self.d.decl_words:
            self.next()
            mutable = tok.text not in ("const", "val", "let") or self.d.name == "javascript" or \
                self.d.name == "typescript"
            if self.accept("mut"):
                mutable = True
            names = []
            if self.at("("):                          # let (a, b) = (x, y)
                self.next()
                while not self.at(")"):
                    self.accept("mut")
                    names.append(self.ident())
                    if not self.accept(","):
                        break
                self.expect(")")
                self.expect("=")
                value = self.expr()
                if allow_end:
                    self.end_stmt()
                return [{"k": "multi", "targets": names, "value": value, "decl": True, "line": line}]
            while True:
                name = self.ident()
                typ = None
                if self.accept(":"):
                    typ = self.type_name()
                elif self.d.name == "go" and self.peek().kind == "id":
                    typ = self.type_name()
                value = None
                if self.accept("="):
                    self.skip_newlines()
                    value = self.expr()
                out.append({"k": "decl", "name": name, "type": typ, "value": value, "line": line,
                            "mutable": mutable})
                if not self.accept(","):
                    break
            if allow_end:
                self.end_stmt()
            return out
        if allow_decl and self._is_c_decl():
            while self.peek().text in ("const", "final", "static", "register", "volatile", "constexpr"):
                self.next()
            typ = self.type_name()
            while True:
                if self.at("*", "&"):
                    raise ParseError("pointer or reference variable", line)
                name = self.ident()
                if self.at("[") and self.d.name == "c":
                    out.append(self._c_array_decl(name, typ, line))
                    if not self.accept(","):
                        break
                    continue
                if self.at("["):
                    raise ParseError("array variable", line)
                value = None
                if self.accept("="):
                    value = self.expr()
                elif self.at("(") or self.at("{"):
                    raise ParseError("constructor-style initialisation", line)
                out.append({"k": "decl", "name": name, "type": typ, "value": value, "line": line, "mutable": True})
                if not self.accept(","):
                    break
            if allow_end:
                self.end_stmt()
            return out
        if tok.kind == "op" and tok.text in ("++", "--") and self.peek(1).kind == "id":
            self.next()
            name = self.ident()
            if allow_end:
                self.end_stmt()
            return [{"k": "assign", "target": name, "op": tok.text[0] + "=", "value": ("one",), "line": line}]
        e = self.expr()
        tok = self.peek()
        if tok.kind == "op" and tok.text == ":=" and self.d.name == "go":
            self.next()
            value = self.expr()
            if self.at(","):
                values = [value]
                while self.accept(","):
                    values.append(self.expr())
                value = ("tuple", values)
            targets = [e] if e[0] != "tuple" else e[1]
            if allow_end:
                self.end_stmt()
            if len(targets) == 1 and value[0] != "tuple":
                return [{"k": "decl", "name": _name(targets[0], line), "type": None, "value": value, "line": line,
                         "mutable": True}]
            return [{"k": "multi", "targets": [_name(t, line) for t in targets], "value": value, "decl": True,
                     "line": line}]
        if tok.kind == "op" and tok.text == "," and self.d.name in ("go",):
            targets = [e]
            while self.accept(","):
                targets.append(self.expr())
            op = self.next()
            if op.text not in ("=", ":="):
                raise ParseError("multiple targets", line)
            values = [self.expr()]
            while self.accept(","):
                values.append(self.expr())
            if allow_end:
                self.end_stmt()
            return [{"k": "multi", "targets": [_name(t, line) for t in targets], "value": ("tuple", values),
                     "decl": op.text == ":=", "line": line}]
        if tok.kind == "op" and tok.text in ("=", "+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=", "<<=", ">>=",
                                             "**=", "//=", "&&=", "||=", "÷="):
            self.next()
            self.skip_newlines()
            value = self.expr()
            if allow_end:
                self.end_stmt()
            if e[0] == "tuple":
                if tok.text != "=":
                    raise ParseError("augmented tuple assignment", line)
                return [{"k": "multi", "targets": [_name(t, line) for t in e[1]], "value": value, "decl": False,
                         "line": line}]
            if e[0] == "index":
                return [{"k": "aset", "target": e, "op": tok.text, "value": value, "line": line}]
            return [{"k": "assign", "target": _name(e, line), "op": tok.text, "value": value, "line": line}]
        if tok.kind == "op" and tok.text in ("++", "--"):
            self.next()
            if allow_end:
                self.end_stmt()
            if e[0] == "index":
                return [{"k": "aset", "target": e, "op": tok.text[0] + "=", "value": ("one",), "line": line}]
            return [{"k": "assign", "target": _name(e, line), "op": tok.text[0] + "=", "value": ("one",),
                     "line": line}]
        if allow_end:
            self.end_stmt()
        if e[0] == "un" and False:
            pass
        return [{"k": "expr", "value": e, "line": line}]

    # -- statements: end languages (Ruby, Lua, Julia) --------------------------------------------------------------
    def end_block(self, stops: tuple) -> list[dict]:
        out: list[dict] = []
        while True:
            self.skip_nl()
            tok = self.peek()
            if tok.kind == "eof":
                raise ParseError(f"expected {' or '.join(stops)}", tok.line)
            if tok.kind == "id" and tok.text in stops:
                return out
            out.extend(self.end_statement())

    def end_statement(self) -> list[dict]:
        tok = self.peek()
        line = tok.line
        w = tok.text if tok.kind == "id" else None
        d = self.d.name
        if w == "if" or w == "unless":
            self.next()
            cond = self.expr()
            if w == "unless":
                cond = ("un", "!", cond)
            self.accept("then")
            then = self.end_block(("else", "elsif", "elseif", "end"))
            other = self._end_else(line)
            return self._modifiers([{"k": "if", "cond": cond, "then": then, "else": other, "line": line}])
        if w in ("while", "until"):
            self.next()
            cond = self.expr()
            if w == "until":
                cond = ("un", "!", cond)
            self.accept("do")
            body = self.end_block(("end",))
            self.expect("end")
            return [{"k": "while", "cond": cond, "body": body, "line": line}]
        if w == "repeat" and d == "lua":
            self.next()
            body = self.end_block(("until",))
            self.expect("until")
            cond = self.expr()
            return [{"k": "do_while", "cond": ("un", "!", cond), "body": body, "line": line}]
        if w == "for":
            self.next()
            var = self.ident()
            if d == "lua" and self.accept("="):
                start = self.expr()
                self.expect(",")
                stop = self.expr()
                step = None
                if self.accept(","):
                    step = self.expr()
                self.expect("do")
                body = self.end_block(("end",))
                self.expect("end")
                return [{"k": "for_iter", "var": var, "iter": ("range", start, stop, "incl", step), "body": body,
                         "line": line}]
            if not (self.accept("in") or self.accept("=") or self.accept("∈")):
                raise ParseError("for over a collection", line)
            it = self.expr()
            self.accept("do")
            body = self.end_block(("end",))
            self.expect("end")
            return [{"k": "for_iter", "var": var, "iter": it, "body": body, "line": line}]
        if w == "do" and d == "lua":
            self.next()
            body = self.end_block(("end",))
            self.expect("end")
            return [{"k": "block", "body": body, "line": line}]
        if w == "begin" and d == "ruby":
            self.next()
            body = self.end_block(("end",))
            self.expect("end")
            if self.at("while", "until"):
                kw = self.next().text
                cond = self.expr()
                if kw == "until":
                    cond = ("un", "!", cond)
                return [{"k": "do_while", "cond": cond, "body": body, "line": line}]
            return [{"k": "block", "body": body, "line": line}]
        if w == "return":
            self.next()
            if self.peek().kind in ("nl", "eof") or self.at("end", "if", "unless", ";"):
                return self._modifiers([{"k": "return", "value": None, "line": line}])
            e = self.expr()
            if d == "lua" and self.at(","):
                raise ParseError("multiple return values", line)
            return self._modifiers([{"k": "return", "value": e, "line": line}])
        if w in ("break", "next", "continue"):
            self.next()
            k = "continue" if w in ("next", "continue") else "break"
            return self._modifiers([{"k": k, "line": line}])
        if w == "goto" and d == "lua":
            self.next()
            return [{"k": "goto", "label": self.ident(), "line": line}]
        if tok.kind == "op" and tok.text == "::" and d == "lua":
            self.next()
            label = self.ident()
            self.expect("::")
            return [{"k": "label", "label": label, "line": line}]
        if w == "loop" and d == "ruby" and self.peek(1).text == "do":
            self.next()
            self.next()
            self._block_params()
            body = self.end_block(("end",))
            self.expect("end")
            return [{"k": "while", "cond": ("bool", True), "body": body, "line": line}]
        if w in ("puts", "print", "println", "printf") and not (self.peek(1).kind == "op" and
                                                                self.peek(1).text in ("=", "+=", "-=")):
            raise ParseError(f"I/O (`{w}`)", line)
        if w in ("case", "begin", "rescue", "raise", "yield", "error", "assert"):
            raise ParseError(f"`{w}`", line)
        if w == "local" and d == "lua" and self.peek(1).text == "function":
            raise ParseError("nested function", line)
        if w in self.d.decl_words:
            self.next()
            names = [self.ident()]
            types = [None]
            if self.accept("::"):
                types[0] = self.type_name()
            while self.accept(","):
                names.append(self.ident())
                types.append(None)
            if d == "lua" and self.at("<"):
                self.next()
                self.ident()
                self.expect(">")
            value = None
            if self.accept("="):
                value = self.expr()
                if self.at(","):
                    vals = [value]
                    while self.accept(","):
                        vals.append(self.expr())
                    value = ("tuple", vals)
            if len(names) > 1:
                if value is None or value[0] != "tuple":
                    raise ParseError("multiple names", line)
                return [{"k": "multi", "targets": names, "value": value, "decl": True, "line": line}]
            return [{"k": "decl", "name": names[0], "type": types[0], "value": value, "line": line, "mutable": True}]
        e = self.expr()
        if d == "ruby" and (self.at("do") or (self.at("{") and self.peek(1).text == "|")):
            return [self._ruby_iter(e, line)]
        tok = self.peek()
        if tok.kind == "op" and tok.text == "," and d in ("ruby", "lua", "julia"):
            targets = [e]
            while self.accept(","):
                targets.append(self.expr())
            self.expect("=")
            vals = [self.expr()]
            while self.accept(","):
                vals.append(self.expr())
            return self._modifiers([{"k": "multi", "targets": [_name(t, line) for t in targets],
                                     "value": ("tuple", vals) if len(vals) > 1 else vals[0], "decl": False,
                                     "line": line}])
        if tok.kind == "op" and tok.text in ("=", "+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=", "<<=", ">>=",
                                             "**=", "//=", "÷="):
            self.next()
            self.skip_newlines()
            value = self.expr()
            if e[0] == "ann":
                return [{"k": "decl", "name": _name(e[2], line), "type": e[1], "value": value, "line": line,
                         "mutable": True}]
            if e[0] == "tuple":
                return [{"k": "multi", "targets": [_name(t, line) for t in e[1]], "value": value, "decl": False,
                         "line": line}]
            return self._modifiers([{"k": "assign", "target": _name(e, line), "op": tok.text, "value": value,
                                     "line": line}])
        return self._modifiers([{"k": "expr", "value": e, "line": line}])

    def _end_else(self, line) -> list[dict]:
        if self.accept("end"):
            return []
        if self.accept("else"):
            other = self.end_block(("end",))
            self.expect("end")
            return other
        self.next()                                      # elsif / elseif
        cond = self.expr()
        self.accept("then")
        then = self.end_block(("else", "elsif", "elseif", "end"))
        return [{"k": "if", "cond": cond, "then": then, "else": self._end_else(line), "line": line}]

    def _modifiers(self, stmts: list[dict]) -> list[dict]:
        """Ruby: `stmt if cond`, `stmt unless cond`, `stmt while cond`."""
        if self.d.name != "ruby":
            return stmts
        line = stmts[0]["line"]
        if self.at("if", "unless") and self.peek().line == line:
            kw = self.next().text
            cond = self.expr()
            if kw == "unless":
                cond = ("un", "!", cond)
            return [{"k": "if", "cond": cond, "then": stmts, "else": [], "line": line}]
        if self.at("while", "until") and self.peek().line == line:
            kw = self.next().text
            cond = self.expr()
            if kw == "until":
                cond = ("un", "!", cond)
            return [{"k": "while", "cond": cond, "body": stmts, "line": line}]
        return stmts

    def _block_params(self) -> list[str]:
        names = []
        if self.accept("|"):
            while not self.at("|"):
                names.append(self.ident())
                if not self.accept(","):
                    break
            self.expect("|")
        return names

    def _ruby_iter(self, e, line) -> dict:
        brace = self.next().text == "{"
        params = self._block_params()
        body = self.end_block(("}",) if brace else ("end",)) if not brace else self._brace_body()
        if not brace:
            self.expect("end")
        if e[0] == "name" and "." in e[1]:
            head, _, meth = e[1].rpartition(".")
            e = ("mcall", ("name", head), meth, [])
        elif e[0] == "call" and "." in e[1]:
            head, _, meth = e[1].rpartition(".")
            e = ("mcall", ("name", head), meth, e[2])
        if e[0] == "mcall":
            recv, meth, args = e[1], e[2], e[3]
        else:
            raise ParseError("block on a call that is not a counted loop", line)
        var = params[0] if params else "cm_unused"
        if meth == "times" and not args:
            it = ("range", ("num", 0, ""), recv, "excl", None)
        elif meth == "each" and recv[0] == "range" and not args:
            it = recv
        elif meth == "upto" and len(args) == 1:
            it = ("range", recv, args[0], "incl", None)
        elif meth == "downto" and len(args) == 1:
            it = ("range", recv, args[0], "incl", ("num", -1, ""))
        elif meth == "step" and len(args) == 2:
            it = ("range", recv, args[0], "incl", args[1])
        else:
            raise ParseError(f"block on .{meth}", line)
        return {"k": "for_iter", "var": var, "iter": it, "body": body, "line": line}

    def _brace_body(self) -> list[dict]:
        out = []
        while True:
            self.skip_nl()
            if self.accept("}"):
                return out
            out.extend(self.end_statement())


def _name(e, line) -> str:
    if e[0] == "name" and "." not in e[1] and "::" not in e[1]:
        return e[1]
    raise ParseError("assignment to something other than a local variable", line)


# -- function discovery ----------------------------------------------------------------------------------------------

@dataclass
class FnDef:
    name: str
    params: list            # [(name, type text | None)]
    ret: str | None
    body: list | None       # statements (None: parse failed)
    line: int
    end_line: int
    error: str | None = None
    expr_body: bool = False


def find_functions(src: str, d: Dialect) -> list[FnDef]:
    toks = tokenize(src, d)
    p = Parser(toks, d)
    out: list[FnDef] = []
    while p.peek().kind != "eof":
        start = p.i
        try:
            fn = _try_function(p, d)
        except ParseError as exc:
            fn = FnDef(_guess_name(toks, start), [], None, None, toks[start].line, exc.line, exc.what)
            p.i = start
            _skip_function(p, d)
            fn.end_line = p.peek(-1).line if p.i else fn.end_line
        if fn is None:
            p.i = start
            p.next()
            continue
        if fn.body is None and fn.error is None:
            continue                            # a prototype
        out.append(fn)
    return out


def _guess_name(toks, start) -> str:
    j = start
    while j < len(toks) - 1 and j < start + 40:
        if toks[j].kind == "op" and toks[j].text == "(" and toks[j - 1].kind == "id":
            return toks[j - 1].text
        j += 1
    return toks[start].text


_MODIFIERS = {"static", "inline", "public", "private", "protected", "internal", "extern", "export", "pub", "final",
              "override", "open", "constexpr", "noexcept", "unsafe", "async", "default", "partial", "fileprivate",
              "@inlinable", "local", "tailrec", "operator", "infix", "virtual", "sealed", "abstract", "const",
              "nodiscard", "mutating", "nonmutating", "friend"}


def _try_function(p: Parser, d: Dialect) -> FnDef | None:
    """At p.i: a function definition of this dialect, or None (not a function start)."""
    tok = p.peek()
    if tok.kind == "op" and tok.text == "#" and d.name == "rust":
        p.skip_attribute()
        return None
    if tok.kind == "op" and tok.text == "@" and d.name in ("java", "kotlin", "swift", "csharp"):
        return None
    if tok.kind != "id":
        return None
    line = tok.line
    j = p.i
    while p.t[j].kind == "id" and p.t[j].text in _MODIFIERS:
        j += 1
    w = p.t[j].text
    kw = {"go": "func", "swift": "func", "rust": "fn", "zig": "fn", "kotlin": "fun", "javascript": "function",
          "typescript": "function", "php": "function", "ruby": "def", "lua": "function", "julia": "function"}.get(d.name)
    if kw is not None:
        if w != kw:
            if d.name == "julia" and p.t[j].kind == "id" and p.t[j + 1].text == "(" and _julia_short(p, j):
                p.i = j
                return _julia_short_fn(p, line)
            return None
        p.i = j + 1
        if d.name == "go" and p.at("("):
            raise ParseError("method with a receiver", line)
        name = p.ident()
        if d.name == "lua":
            while p.at(".", ":"):
                p.next()
                name += "_" + p.ident()
        if d.name == "ruby" and p.at("."):
            p.next()
            name = p.ident()                     # def self.f
        if p.at("<"):
            raise ParseError("generic function", line)
        params = _params(p, d)
        ret = None
        if d.name in ("rust", "swift") and p.accept("->"):
            ret = p.type_name()
        elif d.name in ("kotlin", "typescript") and p.accept(":"):
            ret = p.type_name()
        elif d.name == "php" and p.accept(":"):
            ret = p.type_name()
        elif d.name == "julia" and p.accept("::"):
            ret = p.type_name()
        elif d.name == "go" and not p.at("{"):
            if p.at("("):
                raise ParseError("multiple results", line)
            ret = p.type_name()
        elif d.name == "zig":
            if p.at("!"):
                raise ParseError("error union result", line)
            ret = p.type_name()
        if d.name == "swift" and p.at("throws", "rethrows", "async"):
            raise ParseError("throwing or async function", line)
        if d.name == "kotlin" and p.accept("="):
            p.skip_newlines()
            e = p.expr()
            return FnDef(name, params, ret, [{"k": "return", "value": e, "line": line}], line, p.peek().line,
                         expr_body=True)
        if d.style == "end":
            stops = ("end",)
            body = p.end_block(stops)
            p.expect("end")
        else:
            if d.name == "rust" and p.at("where"):
                raise ParseError("where clause", line)
            body = p.block()
        return FnDef(name, params, ret, body, line, p.peek(-1).line)
    # C, C++, Java, C#: Type name(params) { ... } — possibly inside a class
    if d.name in ("java", "csharp", "cpp", "kotlin") and w in ("class", "struct", "object", "namespace",
                                                               "interface", "enum", "record"):
        p.i = j + 1
        while not p.at("{") and p.peek().kind != "eof":
            if p.at(";"):
                return None
            p.next()
        p.next()                                       # enter the body: its members are scanned as top level
        return None
    if w in ("typedef", "using", "import", "package", "struct", "enum", "union", "template", "namespace", "class"):
        if w == "template":
            raise ParseError("template", line)
        return None
    if d.name not in ("c", "cpp", "java", "csharp"):
        return None
    p.i = j
    try:
        ret = p.type_name()
    except ParseError:
        return None
    if p.peek().kind != "id" or p.peek(1).text != "(":
        return None
    name = p.ident()
    open_at = p.i
    try:
        params = _params(p, d)
    except ParseError:
        p.i = open_at
        depth = 0
        while p.peek().kind != "eof":
            t = p.next()
            if t.text == "(":
                depth += 1
            elif t.text == ")":
                depth -= 1
                if depth == 0:
                    break
        while p.peek().kind == "id" and p.peek().text in ("const", "noexcept", "override"):
            p.next()
        if p.at("{"):
            p.i = open_at
            raise
        return None
    while p.peek().kind == "id" and p.peek().text in ("const", "noexcept", "override", "throws"):
        if p.next().text == "throws":
            raise ParseError("throws clause", line)
    if p.accept(";"):
        return FnDef(name, params, ret, None, line, line)  # prototype
    if not p.at("{"):
        return None
    if name == "main":
        _skip_function(p, d)
        return FnDef("main", [], "int", None, line, line)
    body = p.block()
    return FnDef(name, params, ret, body, line, p.peek(-1).line)


def _julia_short(p: Parser, j: int) -> bool:
    """Julia `f(x, y) = expr` at the start of a line."""
    if j > 0 and p.t[j - 1].kind not in ("nl",) and j != 0:
        return False
    depth, k = 0, j + 1
    while k < len(p.t):
        t = p.t[k]
        if t.text == "(":
            depth += 1
        elif t.text == ")":
            depth -= 1
            if depth == 0:
                nxt = p.t[k + 1]
                if nxt.text == "::":
                    nxt = p.t[k + 3]
                return nxt.kind == "op" and nxt.text == "="
        elif t.kind in ("nl", "eof"):
            return False
        k += 1
    return False


def _julia_short_fn(p: Parser, line) -> FnDef:
    name = p.ident()
    params = _params(p, p.d)
    ret = p.type_name() if p.accept("::") else None
    p.expect("=")
    e = p.expr()
    return FnDef(name, params, ret, [{"k": "return", "value": e, "line": line}], line, line, expr_body=True)


def _params(p: Parser, d: Dialect) -> list:
    if d.name == "ruby" and not p.at("("):
        params = []
        while p.peek().kind == "id":
            params.append((p.ident(), None))
            if not p.accept(","):
                break
        return params
    p.expect("(")
    params: list = []
    pending: list = []                                  # Go: a, b int64
    while not p.at(")"):
        p.skip_newlines()
        if d.name in ("c", "cpp") and p.at("void") and p.peek(1).text == ")":
            p.next()
            break
        if d.name in ("java", "csharp", "kotlin", "swift") and p.at("@"):
            raise ParseError("annotated parameter", p.peek().line)
        if p.at("...") or p.at("*") or p.at("&") and d.name in ("ruby", "php", "rust"):
            raise ParseError("variadic, pointer or by-reference parameter", p.peek().line)
        if d.name in ("c", "cpp", "java", "csharp"):
            while p.at("const", "final"):
                p.next()
            typ = p.type_name(ptr_ok=True)
            if d.name == "c" and p.at("**"):
                raise ParseError("pointer to pointer parameter", p.peek().line)
            if d.name == "c" and p.at("*"):                  # const T *xs: an array, read as a list
                p.next()
                while p.at("const", "restrict", "__restrict"):
                    p.next()
                if p.at("*", "**"):
                    raise ParseError("pointer to pointer parameter", p.peek().line)
                typ += "*"
            if p.at("*", "&", "["):
                raise ParseError("pointer, reference or array parameter", p.peek().line)
            name = p.ident()
            if d.name == "c" and p.at("[") and not typ.endswith("*"):     # T xs[] / T xs[n] / T xs[static n]
                p.next()
                while not p.at("]"):
                    if p.peek().kind == "eof":
                        raise ParseError("unterminated array parameter", p.peek().line)
                    p.next()
                p.expect("]")
                if p.at("["):
                    raise ParseError("multi-dimensional array parameter", p.peek().line)
                typ += "*"
            if p.at("["):
                raise ParseError("pointer, reference or array parameter", p.peek().line)
            params.append((name, typ))
        elif d.name == "go":
            name = p.ident()
            if p.at(",", ")"):
                pending.append(name)
            else:
                typ = p.type_name()
                for n in pending:
                    params.append((n, typ))
                pending = []
                params.append((name, typ))
        elif d.name == "swift":
            first = p.ident()
            name = first
            if p.peek().kind == "id":
                name = p.ident()                         # external label, internal name
            p.expect(":")
            if p.at("inout"):
                raise ParseError("inout parameter", p.peek().line)
            params.append((name, p.type_name()))
        elif d.name == "rust":
            p.accept("mut")
            name = p.ident()
            p.expect(":")
            if p.at("&"):
                raise ParseError("reference parameter", p.peek().line)
            params.append((name, p.type_name()))
        elif d.name == "php":
            typ = None
            if p.peek().kind == "id" and p.peek(1).kind == "id":
                typ = p.type_name()
            params.append((p.ident(), typ))
        elif d.name == "julia":
            name = p.ident()
            typ = p.type_name() if p.accept("::") else None
            params.append((name, typ))
        else:                                            # kotlin, typescript, zig, javascript, ruby, lua
            if d.name == "zig" and p.at("comptime"):
                raise ParseError("comptime parameter", p.peek().line)
            name = p.ident()
            typ = p.type_name() if p.accept(":") else None
            params.append((name, typ))
        if p.at("="):
            raise ParseError("default parameter value", p.peek().line)
        p.skip_newlines()
        if not p.accept(","):
            break
        p.skip_newlines()
    if pending:
        raise ParseError("parameter without a type", p.peek().line)
    p.expect(")")
    return params


def _skip_function(p: Parser, d: Dialect) -> None:
    """Resynchronise after a parse error: skip to the end of the function that starts at p.i."""
    if d.style == "end":
        depth = 0
        while p.peek().kind != "eof":
            t = p.next()
            if t.kind != "id":
                continue
            if t.text in ("def", "function", "while", "for", "begin", "case", "class", "module", "do", "repeat",
                          "let", "struct", "macro", "quote", "try") or \
                    (t.text in ("if", "unless", "until") and _starts_statement(p, p.i - 1)):
                if t.text == "do" and d.name == "lua" and _lua_loop_do(p, p.i - 1):
                    continue
                if t.text == "while" and d.name == "ruby" and not _starts_statement(p, p.i - 1):
                    continue
                if t.text == "repeat" and d.name == "lua":
                    depth += 1
                    continue
                depth += 1
            elif t.text == "end" or (t.text == "until" and d.name == "lua"):
                depth -= 1
                if depth <= 0:
                    return
        return
    depth = 0
    seen = False
    while p.peek().kind != "eof":
        t = p.next()
        if t.kind == "op" and t.text == "{":
            depth += 1
            seen = True
        elif t.kind == "op" and t.text == "}":
            depth -= 1
            if seen and depth <= 0:
                return
        elif t.kind == "op" and t.text == ";" and not seen:
            return


def _starts_statement(p: Parser, j: int) -> bool:
    if j == 0:
        return True
    prev = p.t[j - 1]
    return prev.kind == "nl" or prev.kind == "op" and prev.text in (";", "=", "(") or \
        prev.kind == "id" and prev.text in ("then", "else", "do", "return")


def _lua_loop_do(p: Parser, j: int) -> bool:
    """`do` that belongs to a `while`/`for` header on the same line (not a block of its own)."""
    k = j - 1
    while k >= 0 and p.t[k].kind != "nl":
        if p.t[k].kind == "id" and p.t[k].text in ("while", "for"):
            return True
        k -= 1
    return False


# -- reverse emit: op-card templates read backwards -----------------------------------------------------------------

def emit_patterns(ops: dict[str, OpSpec], d: Dialect) -> dict[str, list]:
    """{callee path or .method: [(op, [placeholder positions], arg_type|None)]} from call-shaped emit templates."""
    out: dict[str, list] = {}
    if not d.emit_keys:
        return out
    for name, spec in ops.items():
        emit = (spec.card.get("emit") or {})
        for key in d.emit_keys:
            tpl = emit.get(key)
            if tpl is None:
                continue
            items = tpl.items() if isinstance(tpl, dict) else [(None, tpl)]
            for typ, text in items:
                if not isinstance(text, str) or text == "UNSUPPORTED":
                    continue
                pat = _call_pattern(text, d)
                if pat is not None:
                    out.setdefault(pat[0], []).append((name, pat[1], typ))
            break
    return out


_PH = re.compile(r"\{(\d)\}")


def _call_pattern(text: str, d: Dialect):
    """`cm_floormod({0}, {1})` -> ("cm_floormod", [0, 1]); `(({0}).abs)` -> (".abs", [0]); else None."""
    if "{type}" in text or "{t0}" in text or "{tc}" in text or "{{" in text:
        return None
    src = _PH.sub(lambda m: f"cmph{m.group(1)}", text)
    try:
        toks = tokenize(src, d)
        p = Parser(toks, d)
        e = p.expr()
        if p.peek().kind != "eof":
            return None
    except (ParseError, IndexError, ValueError):
        return None

    def ph(x):
        return int(x[1][4:]) if x[0] == "name" and x[1].startswith("cmph") and x[1][4:].isdigit() else None

    if e[0] == "call" and all(ph(a) is not None for a in e[2]) and not e[1].startswith("cmph"):
        return e[1], [ph(a) for a in e[2]]
    if e[0] == "mcall" and ph(e[1]) is not None and all(ph(a) is not None for a in e[3]):
        return "." + e[2], [ph(e[1])] + [ph(a) for a in e[3]]
    if e[0] == "name" and e[1].startswith("cmph") and "." in e[1]:
        head, _, meth = e[1].partition(".")
        if head[4:].isdigit() and "." not in meth:
            return "." + meth, [int(head[4:])]
    return None


# -- lowering to the IR -----------------------------------------------------------------------------------------------

class Widen(Exception):
    """Restart the lowering with ``name`` typed ``typ`` (untyped languages: inference by retrying)."""
    def __init__(self, name: str, typ: str = FLOAT):
        self.name = name
        self.typ = typ
        super().__init__(name)


class Lowerer:
    def __init__(self, fn: FnDef, d: Dialect, ops: dict[str, OpSpec], sigs: dict, patterns: dict,
                 widened: set, hints: dict | None):
        self.fn = fn
        self.d = d
        self.ops = ops
        self.sigs = sigs
        self.patterns = patterns
        self.widened = widened
        self.hints = hints or {}
        self.env: dict[str, str] = {}
        self.locals: dict[str, str] = {}
        self.tmp = 0
        self.inferred = False
        self.return_types: set[str] = set()
        self.ret: str | None = None
        self.loop_steps: list = []          # per enclosing loop: statements a `continue` must run first
        self.line = fn.line
        self.untyped_params: set[str] = set()
        self.externs: dict = {}
        self.cur_type: str | None = None
        self.signed_cast = 0
        self.c_mode = d.name in ("c", "cpp")
        self.ckinds: dict[str, tuple] = {}       # C: each int variable's (signed, bits)
        self.cdefs: dict = {}                    # C: name -> FnDef of the file (parameter and result kinds)
        self.ret_kind = None
        self.celems: dict[str, tuple] = {}        # C: each array's element kind
        self.params_seen: set[str] = set()

    def err(self, what: str):
        raise Unsupported(what, self.line)

    # C's fixed-width integers: kinds are (signed, bits); every int-kinded value is kept inside its kind's range
    def ckind_text(self, text: str | None):
        if text is None:
            return None
        if text.startswith("std::"):
            text = text[5:]
        if text in _C_KINDS:
            return _C_KINDS[text]
        return (True, 64) if self.d.types.get(text) == INT else None

    @staticmethod
    def cpromote(k):
        return (True, 32) if k is not None and k[1] < 32 else k

    def cusual(self, a, b):
        """C's usual arithmetic conversions on two int kinds (after promotion)."""
        a, b = self.cpromote(a), self.cpromote(b)
        if a is None or b is None:
            return None
        if a == b:
            return a
        if a[0] == b[0]:
            return a if a[1] >= b[1] else b
        u, sg = (a, b) if not a[0] else (b, a)
        return u if u[1] >= sg[1] else sg

    def ckind(self, n):
        """The C integer kind of an expression node (None: not an integer)."""
        kind = n[0]
        if kind == "num":
            v, suffix = n[1], n[2].lower()
            raw = (n[3] if len(n) > 3 else str(v)).lower()
            if isinstance(v, float) or "f" in suffix and not raw.startswith("0x"):
                return None
            based = raw.startswith("0x") or raw.startswith("0b") or (len(raw) > 1 and raw[0] == "0")
            order = [(True, 32), (False, 32), (True, 64), (False, 64)] if based else [(True, 32), (True, 64)]
            if "u" in suffix:
                order = [(False, 32), (False, 64)]
            if "l" in suffix:
                order = [k for k in order if k[1] == 64]
            for k in order:
                lo, hi = (-(1 << (k[1] - 1)), (1 << (k[1] - 1)) - 1) if k[0] else (0, (1 << k[1]) - 1)
                if lo <= v <= hi:
                    return k
            return (False, 64)
        if kind in ("one", "bool"):
            return (True, 32)
        if kind == "cconv":
            return n[1]
        if kind == "name":
            if n[1] in self.ckinds:
                return self.ckinds[n[1]]
            return (True, 64) if self.env.get(n[1]) == INT else None
        if kind == "bin":
            op = n[1]
            if op in ("==", "!=", "<", "<=", ">", ">=", "&&", "||"):
                return (True, 32)
            if op in ("<<", ">>"):
                return self.cpromote(self.ckind(n[2]))
            return self.cusual(self.ckind(n[2]), self.ckind(n[3]))
        if kind == "un":
            return (True, 32) if n[1] == "!" else self.cpromote(self.ckind(n[2]))
        if kind == "tern":
            return self.cusual(self.ckind(n[2]), self.ckind(n[3]))
        if kind == "cast":
            return self.ckind_text(n[1])
        if kind == "call":
            f = self.cdefs.get(n[1])
            if f is not None and n[1] not in self.env:
                return self.ckind_text(f.ret)
            ext = self.externs.get(n[1])
            if ext is not None and ext.get("c_ret"):
                return self.ckind_text(ext["c_ret"])
        if kind == "index":
            return self.celem_kind(n[1])
        return (True, 64)

    def celem_kind(self, arr_node):
        if arr_node[0] == "name" and arr_node[1] in self.celems:
            return self.celems[arr_node[1]]
        return (True, 64)

    def index(self, n):
        """``xs[i]`` in C: GET (an index outside the list is an error in every target, as it is undefined in C)."""
        arr, idx = n[1], n[2]
        if arr[0] != "name" or arr[1] not in self.env or not self.env[arr[1]].startswith("list["):
            self.err("indexing something other than an array parameter or local array")
        i, ti = self.expr(idx)
        if ti != INT:
            self.err(f"array index of type {ti}")
        et = self.env[arr[1]][5:-1]
        e = ["GET", ["var", arr[1]], i]
        k = self.celems.get(arr[1])
        if et == INT and arr[1] in self.params_seen and k is not None and (k[1] < 32 or not k[0]):
            e = self.cconv(e, (True, 64), k)     # the caller's elements, as the array's type holds them
        return e, et

    def array_decl(self, s: dict) -> list[dict]:
        name = s["name"]
        et = self.ir_type(s["type"])
        if et not in (INT, FLOAT):
            self.err(f"array of {s['type']} (lists hold int or float)")
        k = self.ckind_text(s["type"]) if et == INT else None
        init = s["init"] or []
        if s["size"] is not None:
            n, tn = self.expr(s["size"])
            if tn != INT:
                self.err("array size is not an int")
            if n[0] == "int" and len(init) > n[1]:
                self.err("more initialisers than elements")
            if init and n[0] != "int":
                self.err("initialised variable-length array")
        else:
            n = ["int", len(init)]
        lt = f"list[{et}]"
        if name in self.env and self.env[name] != lt:
            self.err(f"variable {name!r} is {self.env[name]} and {lt} (rename one)")
        self.declare(name, lt)
        self.celems[name] = k
        out = [{"k": "assign", "target": name, "value": ["LIST_NEW", n, _zero(et)]}]
        for i, node in enumerate(init):
            v, tv = self.expr(node)
            if et == INT and tv == INT:
                v = self.cconv(v, self.ckind(node), k)
            out.append({"k": "set", "target": name, "index": ["int", i], "value": self.coerce(v, tv, et)})
        return out

    def array_set(self, s: dict) -> list[dict]:
        tgt = s["target"]
        arr = tgt[1]
        if arr[0] != "name" or arr[1] not in self.env or not self.env[arr[1]].startswith("list["):
            self.err("writing through something other than a local array")
        name = arr[1]
        if name in self.params_seen:
            self.err(f"writes an element of the parameter {name!r} (output through a pointer is not lifted)")
        et = self.env[name][5:-1]
        i, ti = self.expr(tgt[2])
        if ti != INT:
            self.err(f"array index of type {ti}")
        if s["op"] == "=":
            v, tv = self.expr(s["value"])
            node = s["value"]
        else:
            op = s["op"][:-1]
            self.cur_type = et
            node = ("bin", op, tgt, s["value"])
            v, tv = self.binop(op, tgt, s["value"])
        if et == INT and tv == INT:
            v = self.cconv(v, self.ckind(node), self.celems.get(name))
        if et == INT and tv == FLOAT:
            self.err("a float stored into an int array")
        return [{"k": "set", "target": name, "index": i, "value": self.coerce(v, tv, et)}]

    def cconv(self, e, kfrom, kto):
        """C's conversion of an int value of kind ``kfrom`` to kind ``kto``: reduced modulo 2^w unless it fits."""
        if kto is None or kfrom is None or kto[1] <= 1 or kto == (True, 64):
            return e
        if kto[1] >= 64:
            self.err(_C_U64)
        if kfrom[1] <= 1:
            return e
        if kfrom[0] == kto[0] and kfrom[1] <= kto[1] or not kfrom[0] and kto[0] and kfrom[1] < kto[1]:
            return e
        w = kto[1]
        if e[0] == "int":
            v = e[1] & ((1 << w) - 1)
            return ["int", v - (1 << w) if kto[0] and v >> (w - 1) else v]
        return ["WRAPS" if kto[0] else "WRAPU", e, ["int", w]]

    def cconv_node(self, e, node, kto):
        return self.cconv(e, self.ckind(node), kto) if self.c_mode else e

    # types
    def ir_type(self, text: str | None) -> str | None:
        if text is None:
            return None
        if text.endswith("*") and self.d.name == "c":       # a C array parameter: a list the function only reads
            elem = self.ir_type(text[:-1])
            if elem not in (INT, FLOAT):
                self.err(f"array of {text[:-1]} (lists hold int or float)")
            return f"list[{elem}]"
        t = self.d.types.get(text)
        if t is None and self.d.name in ("c", "cpp") and text.startswith("std::"):
            t = self.d.types.get(text[5:])
        if t is None:
            why = self.d.unsupported_types.get(text)
            if why:
                self.err(f"type {text}: {why}")
            self.err(f"type {text!r} (only int, float and bool scalars lift)")
        if t == "auto":
            return None
        return t

    def fresh(self, base: str, typ: str) -> str:
        self.tmp += 1
        name = f"cm_{base}{self.tmp}"
        self.locals[name] = typ
        self.env[name] = typ
        return name

    def lower(self) -> dict:
        fn = self.fn
        params = []
        js_int = self.d.bigint_marker and _uses_bigint(fn)
        for pname, ptext in fn.params:
            t = self.ir_type(ptext) if ptext is not None else None
            if t is None:
                t = self.hints.get(pname)
                if t is None:
                    if pname in self.widened:
                        t = self.widened[pname]
                    elif self.d.untyped == "js":
                        t = INT if js_int else FLOAT
                    else:
                        t = self.d.untyped or INT
                    self.inferred = True
                self.untyped_params.add(pname)
            if t == VOID:
                self.err("void parameter")
            params.append({"name": pname, "type": t})
            self.env[pname] = t
        entry_wraps = []
        self.params_seen = {p["name"] for p in params}
        if self.c_mode:
            for pname, ptext in fn.params:
                if ptext and ptext.endswith("*"):
                    self.celems[pname] = self.ckind_text(ptext[:-1])
                k = self.ckind_text(ptext)
                if k is None or self.env.get(pname) != INT:
                    continue
                self.ckinds[pname] = k
                if k[1] < 32 or not k[0]:          # the caller's argument, converted as C converts it
                    entry_wraps.append({"k": "assign", "target": pname,
                                        "value": self.cconv(["var", pname], (True, 64), k)})
            self.ret_kind = self.ckind_text(fn.ret)
        self.ret = self.ir_type(fn.ret) if fn.ret is not None else None
        if self.ret == VOID:
            self.err("a function without a result (void) is not lifted")
        if self.ret is None and fn.ret is None and self.d.name in ("go", "swift", "rust", "zig", "kotlin") \
                and not fn.expr_body:
            self.err("a function without a result is not lifted")
        if self.ret is None and self.d.name in ("c", "cpp", "java", "csharp") and fn.ret not in ("auto", "var"):
            self.err(f"result type {fn.ret!r}")
        body_src = list(fn.body or [])
        if self.d.implicit_return:
            body_src = _implicit_return(body_src)
        body = entry_wraps + self.block(body_src) if self.c_mode else self.block(body_src)
        if not _always_returns(body):
            self.err("a path can reach the end of the function without return")
        rts = self.return_types
        if self.ret is None:
            if "cm_return" in self.widened and rts <= {INT, FLOAT}:
                self.ret = FLOAT
            elif len(rts) == 1:
                self.ret = next(iter(rts))
            elif rts == {INT, FLOAT}:
                raise Widen("cm_return")
            else:
                self.err(f"return types disagree: {sorted(rts)}")
        body = _coerce_returns(body, self.ret, self)
        out = {"name": fn.name, "params": params, "returns": self.ret, "locals": dict(self.locals), "body": body}
        if any(t.startswith("list[") for t in [*self.locals.values(), *(p["type"] for p in params)]):
            from .ir import check_lists
            why = check_lists(out)
            if why:
                self.err(why[0])
        return out

    # statements
    def block(self, stmts: list[dict]) -> list[dict]:
        out: list[dict] = []
        for s in stmts:
            out.extend(self.stmt(s))
        return out

    def declare(self, name: str, typ: str) -> None:
        prev = self.env.get(name)
        if prev is not None and prev != typ:
            if {prev, typ} == {INT, FLOAT} and (self.d.untyped or name in self.untyped_params):
                raise Widen(name)
            self.err(f"variable {name!r} is {prev} and {typ} (rename one)")
        if prev is None:
            if self.widened.get(name) == FLOAT and typ == INT:
                typ = FLOAT
            self.locals[name] = typ
            self.env[name] = typ

    def coerce(self, e, t: str, want: str, implicit_trunc: bool = False):
        if t == want:
            return e
        if t == INT and want == FLOAT:
            return ["float", float(e[1])] if e[0] == "int" else ["TO_FLOAT", e]
        if t == FLOAT and want == INT and (implicit_trunc or self.d.name in ("c", "cpp")):
            return ["TRUNC_INT", e]
        if t == BOOL and want == INT and self.d.name in ("c", "cpp"):
            return ["IF_EXPR", e, ["int", 1], ["int", 0]]
        if t == INT and want == BOOL and self.d.name in ("c", "cpp"):
            return ["CMP_NE", e, ["int", 0]]
        self.err(f"a {t} value where {want} is expected")

    def assign_to(self, name: str, e, t: str) -> dict:
        if name not in self.env:
            self.declare(name, t)
        want = self.env[name]
        if want == INT and t == FLOAT and (self.d.untyped or name in self.untyped_params):
            raise Widen(name)
        return {"k": "assign", "target": name, "value": self.coerce(e, t, want)}

    def stmt(self, s: dict) -> list[dict]:
        self.line = s.get("line", self.line)
        k = s["k"]
        if k == "block":
            return self.block(s["body"])
        if k == "adecl":
            return self.array_decl(s)
        if k == "aset":
            return self.array_set(s)
        if k == "decl":
            name = s["name"]
            want = self.ir_type(s["type"]) if s.get("type") else None
            if s["value"] is None:
                if want is None:
                    self.err(f"declaration of {name!r} without a type or a value")
                self.declare(name, want)
                if self.c_mode and want == INT:
                    self.ckinds[name] = self.ckind_text(s["type"])
                return [{"k": "assign", "target": name, "value": _zero(want)}] if self.d.name not in ("c", "cpp") \
                    else []
            e, t = self.expr(s["value"])
            if want is None:
                want = t
            if self.widened.get(name) == FLOAT and want == INT:
                want = FLOAT
            e = self.coerce(e, t, want, implicit_trunc=False)
            if self.c_mode and want == INT:
                k = self.ckind_text(s["type"]) if s.get("type") not in (None, "auto") else self.ckind(s["value"])
                if t == INT:
                    e = self.cconv(e, self.ckind(s["value"]), k)
                if name not in self.env:
                    self.ckinds[name] = k
            if name in self.env and name == _var_of(s["value"]) and self.env[name] == want:
                return []                                     # let mut a = a;
            self.declare(name, want)
            return [{"k": "assign", "target": name, "value": e}]
        if k == "assign":
            name = s["target"]
            if name == "_" and s["op"] == "=":
                return []
            if name not in self.env:
                if s["op"] != "=":
                    self.err(f"name {name!r} is not a parameter or an assigned local")
                if self.d.name in ("c", "cpp", "java", "csharp", "go", "rust", "swift", "kotlin", "zig",
                                   "typescript") and name not in self.env:
                    self.err(f"assignment to {name!r}, which is not a local (globals are not lifted)")
            if s["op"] == "=":
                e, t = self.expr(s["value"])
                if t == INT and self.env.get(name) == INT:
                    e = self.cconv_node(e, s["value"], self.ckinds.get(name))
                return [self.assign_to(name, e, t)]
            op = s["op"][:-1]
            if op in ("&&", "||"):
                self.err(f"{s['op']}")
            self.cur_type = self.env.get(name)
            e, t = self.binop(op, ("name", name), s["value"])
            if t == INT and self.env.get(name) == INT:
                e = self.cconv_node(e, ("bin", op, ("name", name), s["value"]), self.ckinds.get(name))
            return [self.assign_to(name, e, t)]
        if k == "multi":
            value = s["value"]
            if value[0] != "tuple" or len(value[1]) != len(s["targets"]):
                self.err("multiple assignment from something other than a tuple of the same length")
            vals = [self.expr(v) for v in value[1]]
            out, temps = [], []
            for e, t in vals:
                tmp = self.fresh("t", t)
                out.append({"k": "assign", "target": tmp, "value": e})
                temps.append((tmp, t))
            for x, (tmp, t) in zip(s["targets"], temps):
                if x == "_":
                    continue
                out.append(self.assign_to(x, ["var", tmp], t))
            return out
        if k == "return":
            if s["value"] is None:
                self.err("return without a value")
            e, t = self.expr(s["value"])
            if self.c_mode and t == INT and self.ret == INT:
                e = self.cconv(e, self.ckind(s["value"]), self.ret_kind)
            if self.ret is not None:
                e = self.coerce(e, t, self.ret, implicit_trunc=self.d.name in ("c", "cpp"))
                t = self.ret
            self.return_types.add(t)
            return [{"k": "return", "value": e, "t": t}]
        if k == "if":
            then = self.block(s["then"])
            other = self.block(s["else"])
            self.line = s["line"]
            return [{"k": "if", "cond": self.cond(s["cond"]), "then": then, "else": other}]
        if k == "while":
            self.loop_steps.append([])
            body = self.block(s["body"])
            self.loop_steps.pop()
            self.line = s["line"]
            return [{"k": "while", "cond": self.cond(s["cond"]), "body": body}]
        if k == "do_while":
            cond = s["cond"]
            exit_ = {"k": "if", "cond": ("un", "!", cond), "then": [{"k": "break", "line": s["line"]}], "else": [],
                     "line": s["line"]}
            self.loop_steps.append([exit_])
            body = self.block(s["body"])
            tail = self.stmt(exit_)
            self.loop_steps.pop()
            return [{"k": "while", "cond": ["bool", True], "body": body + tail}]
        if k == "for_c":
            init = self.block(s["init"])
            self.loop_steps.append(s["step"])
            body = self.block(s["body"])
            self.loop_steps.pop()
            step = self.block(s["step"])
            self.line = s["line"]
            return init + [{"k": "while", "cond": self.cond(s["cond"]), "body": body + step}]
        if k == "for_iter":
            return [self.for_iter(s)]
        if k == "for_range":
            it = ("range", s["start"], s["stop"], "excl", None)
            return [self.for_iter({**s, "iter": it})]
        if k == "break":
            return [{"k": "break"}]
        if k == "continue":
            steps = self.loop_steps[-1] if self.loop_steps else []
            return self.block(steps) + [{"k": "continue"}] if steps else [{"k": "continue"}]
        if k == "goto":
            if s["label"].startswith("cm_continue") or s["label"] == "continue":
                return self.stmt({"k": "continue", "line": s["line"]})
            self.err("goto")
        if k == "label":
            return []
        if k == "expr":
            e = s["value"]
            if e[0] == "block_if":
                self.err("if-expression whose value is unused")
            if e[0] == "call" and e[1] in ("print", "println", "printf", "puts", "console.log", "fmt.Println",
                                          "System.out.println", "echo", "assert"):
                self.err(f"I/O ({e[1]})")
            self.err("an expression statement with no effect on a local (calls for their effect are not lifted)")
        self.err(f"statement {k}")

    def for_iter(self, s: dict) -> dict:
        it = s["iter"]
        if it[0] == "mcall" and it[2] in ("rev",) and it[1][0] == "range" and not it[3]:
            r = it[1]
            # (a..b).rev(): b-1 down to a
            start, stop, kind = r[1], r[2], r[3]
            hi = ("bin", "-", stop, ("num", 1, "")) if kind == "excl" else stop
            it = ("range", hi, start, "incl", ("num", -1, ""))
        elif it[0] == "mcall" and it[2] == "step_by" and it[1][0] == "range" and len(it[3]) == 1:
            r = it[1]
            it = ("range", r[1], r[2], r[3], it[3][0])
        elif it[0] == "call" and it[1] == "stride" and self.d.name == "swift":
            labels = dict(zip(it[3], it[2]))
            if set(labels) not in ({"from", "to", "by"}, {"from", "through", "by"}):
                self.err("stride(...) form")
            it = ("range", labels["from"], labels.get("to", labels.get("through")),
                  "excl" if "to" in labels else "incl", labels["by"])
        elif it[0] == "call" and it[1] == "range" and self.d.name == "julia":
            self.err("range(...) in Julia; use a:b")
        if it[0] != "range":
            self.err("for over something other than an integer range")
        _, a, b, kind, step = it
        sv = 1
        if kind == "down":
            sv = -1
        if step is not None:
            se, st = self.expr(step)
            if se[0] == "NEG" and se[1][0] == "int":
                se = ["int", -se[1][1]]
            if se[0] != "int" or se[1] == 0:
                self.err("loop step must be a non-zero integer literal")
            sv = se[1] * (-1 if kind == "down" else 1)
        start, ta = self.expr(a)
        stop, tb = self.expr(b)
        if ta != INT or tb != INT:
            self.err("range bounds must be int")
        if kind in ("incl", "down"):
            stop = ["ADD", stop, ["int", 1]] if sv > 0 else ["SUB", stop, ["int", 1]]
            if stop[0] == "ADD" and stop[1][0] == "int":
                stop = ["int", stop[1][1] + 1]
            elif stop[0] == "SUB" and stop[1][0] == "int":
                stop = ["int", stop[1][1] - 1]
        if self.d.name == "lua" and kind == "incl" and step is not None:
            pass
        var = s["var"]
        if var == "_":
            var = self.fresh("u", INT)
        if self.env.get(var, INT) != INT:
            self.err(f"loop variable {var!r} is not int")
        if var not in self.env:
            self.locals[var] = INT
            self.env[var] = INT
        it_name = self.fresh("it", INT)
        stop_name = self.fresh("stop", INT)
        self.loop_steps.append([])
        body = self.block(s["body"])
        self.loop_steps.pop()
        return {"k": "for_range", "var": var, "start": start, "stop": stop, "step": ["int", sv],
                "counter": it_name, "stop_var": stop_name, "body": body}

    # expressions
    def retype_float(self, e, t) -> None:
        """An untyped parameter that is floored, ceiled or truncated was not an integer."""
        if t == INT and e[0] == "var" and e[1] in self.untyped_params and e[1] not in self.widened:
            raise Widen(e[1], FLOAT)

    def retype_bool(self, e, t) -> None:
        """An untyped parameter used as a condition is a bool."""
        if t != BOOL and e[0] == "var" and e[1] in self.untyped_params and e[1] not in self.widened:
            raise Widen(e[1], BOOL)

    def cond(self, node):
        e, t = self.expr(node)
        if t == BOOL:
            return e
        if not self.d.truthy_ints:
            self.retype_bool(e, t)
        if self.d.truthy_ints and t == INT:
            return ["CMP_NE", e, ["int", 0]]
        if self.d.truthy_ints and t == FLOAT:
            return ["CMP_NE", e, ["float", 0.0]]
        self.err(f"condition of type {t}")

    def spec(self, op: str) -> OpSpec:
        s = self.ops.get(op)
        if s is None:
            self.err(f"op card {op!r} is missing (add cards/op/{op})")
        return s

    def apply(self, op: str, args: list[tuple]):
        spec = self.spec(op)
        types = [t for _, t in args]
        rt = spec.result_type(types)
        exprs = [e for e, _ in args]
        if rt is None:
            prom = spec.promoted(types)
            if prom is None:
                self.err(f"{op} on ({', '.join(types)})")
            exprs = [self.coerce(e, t, p) for (e, t), p in zip(args, prom)]
            rt = spec.result_type(prom)
        if op in ("MIN", "MAX", "ABS") and False:
            pass
        return [op, *exprs], rt

    def binop(self, op: str, a_node, b_node):
        """C: the usual arithmetic conversions, and the wrap of an unsigned result (``_binop`` lowers the op)."""
        if not self.c_mode or op in ("&&", "||"):
            return self._binop(op, a_node, b_node)
        ka, kb = self.ckind(a_node), self.ckind(b_node)
        if ka is None or kb is None:
            return self._binop(op, a_node, b_node)
        if op in ("<<", ">>"):
            k = self.cpromote(ka)
            e, t = self._binop(op, a_node, b_node)
            if not k[0] and k[1] >= 64:
                self.err(_C_U64)
            if op == "<<" and not k[0] and t == INT:
                e = ["WRAPU", e, ["int", k[1]]]
            return e, t
        common = self.cusual(ka, kb)
        if common[0]:
            return self._binop(op, a_node, b_node)        # signed: exact (an overflow is undefined in C)
        if common[1] >= 64:
            self.err(_C_U64)
        e, t = self._binop(op, ("cconv", common, a_node), ("cconv", common, b_node))
        if op in ("+", "-", "*") and t == INT:
            e = ["WRAPU", e, ["int", common[1]]]
        return e, t

    def _binop(self, op: str, a_node, b_node):
        d = self.d
        if op == "or" and d.name == "lua" and a_node[0] == "bin" and a_node[1] == "and":
            x, tx = self.expr(a_node[3])
            if tx != BOOL:                     # `c and x or y` with a number x (never falsy in Lua): if c then x else y
                c = self.cond(a_node[2])
                y, ty = self.expr(b_node)
                return self.if_expr(c, x, tx, y, ty)
        if op in ("&&", "and", "||", "or"):
            a, ta = self.expr(a_node)
            b, tb = self.expr(b_node)
            if d.truthy_ints:
                a, ta = (self.cond(a_node), BOOL) if ta != BOOL else (a, ta)
                b, tb = (self.cond(b_node), BOOL) if tb != BOOL else (b, tb)
            if ta != BOOL or tb != BOOL:
                if not d.truthy_ints:
                    self.retype_bool(a, ta)
                    self.retype_bool(b, tb)
                if op in ("and", "or") and d.name == "kotlin" and ta == tb == INT:
                    return self.apply("BIT_AND" if op == "and" else "BIT_OR", [(a, ta), (b, tb)])
                self.err(f"{op} on {ta}, {tb} (the IR's and/or take bools)")
            return ["AND" if op in ("&&", "and") else "OR", a, b], BOOL
        a, ta = self.expr(a_node)
        b, tb = self.expr(b_node)
        if BOOL in (ta, tb) and op not in ("==", "!=", "===", "!==", "~=", "&", "|", "^"):
            self.err(f"arithmetic on bool ({op})")
        if BOOL in (ta, tb) and op in ("&", "|", "^"):
            if ta == tb == BOOL and d.name in ("rust", "java", "csharp", "swift", "kotlin", "zig"):
                if op == "^":
                    return ["CMP_NE", a, b], BOOL
                return ["AND" if op == "&" else "OR", a, b], BOOL
            self.err(f"bitwise {op} on bool")
        cmp = {"==": "CMP_EQ", "===": "CMP_EQ", "!=": "CMP_NE", "!==": "CMP_NE", "~=": "CMP_NE", "<": "CMP_LT",
               "<=": "CMP_LE", ">": "CMP_GT", ">=": "CMP_GE"}
        if op in cmp:
            self.js_mix(a, ta, b, tb)
            if op in ("==", "!=") and d.name in ("javascript", "php") and ta != tb:
                self.err(f"loose {op} between {ta} and {tb}")
            if d.name == "javascript" and ta != tb and op in ("<", "<=", ">", ">="):
                pass
            return self.apply(cmp[op], [(a, ta), (b, tb)])
        if op == "^" and d.caret == "pow":
            op = "**"
        if op in ("⊻", "xor") or (op == "~" and d.name == "lua"):
            op = "^"
        if op in ("shl", "shr"):
            op = {"shl": "<<", "shr": ">>"}[op]
        simple = {"+": "ADD", "-": "SUB", "*": "MUL", "&": "BIT_AND", "|": "BIT_OR", "^": "BIT_XOR",
                  "<<": "SHIFT_LEFT", ">>": "SHIFT_RIGHT"}
        if op in simple:
            if op in ("&", "|", "^", "<<", ">>") and FLOAT in (ta, tb):
                self.retype_int([(a, ta), (b, tb)])
                self.err(f"bitwise {op} on float")
            self.js_mix(a, ta, b, tb)
            return self.apply(simple[op], [(a, ta), (b, tb)])
        if op in (">>>", "ushr", "&^"):
            self.err(f"operator {op}")
        if op == "**":
            if ta == INT and tb == INT:
                if not (b[0] == "int" and b[1] >= 0):
                    if d.caret == "pow" and d.name == "lua":
                        return self.apply("POW", [(self.coerce(a, ta, FLOAT), FLOAT), (self.coerce(b, tb, FLOAT),
                                                                                         FLOAT)])
                    self.err("int ** int needs a non-negative integer literal exponent")
                if d.name == "lua":                       # Lua's ^ is always float
                    return self.apply("POW", [(self.coerce(a, ta, FLOAT), FLOAT), (self.coerce(b, tb, FLOAT), FLOAT)])
            return self.apply("POW", [(a, ta), (b, tb)])
        if op in ("/", "÷", "//", "%/%"):
            mode = d.int_div if op == "/" else ("trunc" if op == "÷" else "floor")
            if ta == INT and tb == INT:
                if mode == "trunc":
                    return self.apply("TRUNCDIV", [(a, ta), (b, tb)])
                if mode == "floor":
                    return self.apply("FLOORDIV", [(a, ta), (b, tb)])
                return ["DIV", self.coerce(a, ta, FLOAT), self.coerce(b, tb, FLOAT)], FLOAT
            if op == "//" and FLOAT in (ta, tb):
                e, _ = self.apply("DIV", [(a, ta), (b, tb)])
                return ["FLOOR", e], FLOAT
            if op == "÷":
                self.err("÷ on floats")
            self.js_mix(a, ta, b, tb)
            return self.apply("DIV", [(a, ta), (b, tb)])
        if op in ("%", "%%"):
            mode = d.int_mod if op == "%" else "floor"
            if ta == INT and tb == INT:
                return self.apply("REM" if mode == "rem" else "MOD", [(a, ta), (b, tb)])
            if mode == "rem":
                self.js_mix(a, ta, b, tb)
                return self.apply("FMOD", [(a, ta), (b, tb)])
            self.err("floored % on floats has no op card")
        self.err(f"operator {op}")

    def retype_int(self, args) -> None:
        """An untyped parameter used where only an integer fits (bitwise ops) is an integer."""
        for e, t in args:
            if t == FLOAT and e[0] == "var" and e[1] in self.untyped_params and self.widened.get(e[1]) != FLOAT:
                raise Widen(e[1], INT)

    def js_mix(self, a, ta, b, tb) -> None:
        """JavaScript never mixes BigInt and Number: an untyped parameter met with a Number is a Number."""
        if self.d.bigint_marker and {ta, tb} == {INT, FLOAT}:
            for e, t in ((a, ta), (b, tb)):
                if t == INT:
                    for x in _vars_in(e):
                        if x in self.untyped_params and self.env.get(x) == INT:
                            raise Widen(x, FLOAT)
            self.err("mixing BigInt and Number")

    def expr(self, n):
        kind = n[0]
        if kind == "cconv":
            e, t = self.expr(n[2])
            return (self.cconv(e, self.ckind(n[2]), n[1]) if t == INT else e), t
        if kind == "num":
            v, suffix = n[1], n[2]
            s = suffix.lower()
            if self.c_mode and "u" in s and isinstance(v, int):
                if self.ckind(n)[1] >= 64:
                    self.err(f"literal {v}{suffix}: {_C_U64}")
                return ["int", int(v)], INT
            if self.c_mode and isinstance(v, int) and self.ckind(n) == (False, 64):
                self.err(f"literal {n[3] if len(n) > 3 else v}: {_C_U64}")
            if s in ("u", "ul", "ull", "lu", "llu") or s.startswith("u") and self.d.name in ("rust", "zig"):
                self.err(f"unsigned literal {v}{suffix}")
            if s in ("f",) and self.d.name in ("c", "cpp", "java", "csharp", "kotlin") or s == "f32":
                self.err(f"binary32 literal {v}{suffix}")
            if s == "m":
                self.err("decimal literal")
            if isinstance(v, float) or s in ("d", "f64") or (s == "f" and self.d.name == "go"):
                return ["float", float(v)], FLOAT
            if s == "n" and self.d.name in ("javascript", "typescript"):
                return ["int", int(v)], INT
            if self.d.name in ("javascript", "typescript") and not s:
                return ["float", float(v)], FLOAT
            return ["int", int(v)], INT
        if kind == "bool":
            return ["bool", n[1]], BOOL
        if kind == "one":                                  # the 1 of x++ / x--: the variable's own type
            return (["float", 1.0], FLOAT) if self.cur_type == FLOAT else (["int", 1], INT)
        if kind == "name":
            path = n[1]
            if path in self.env:
                return ["var", path], self.env[path]
            if path in self.d.consts:
                c = self.d.consts[path]
                return list(c), c[0]
            if path in ("M_PI",) and self.d.name in ("c", "cpp"):
                return ["float", 3.141592653589793], FLOAT
            if path in ("Math.PI", "math.Pi", "Double.pi", "kotlin.math.PI", "PI"):
                return ["float", 3.141592653589793], FLOAT
            if path in ("INT64_MAX", "Long.MAX_VALUE", "math.MaxInt64", "i64::MAX", "Int.max", "Int64.max"):
                return ["int", 2**63 - 1], INT
            if path in ("INT64_MIN", "Long.MIN_VALUE", "math.MinInt64", "i64::MIN", "Int.min", "Int64.min"):
                return ["int", -(2**63)], INT
            parts = path.split(".")
            if len(parts) > 1 and parts[0] in self.env:      # x.abs / x.to_i.to_f: methods without parentheses
                e = ("name", parts[0])
                for m in parts[1:-1]:
                    e = ("mcall", e, m, [])
                return self.method(e, parts[-1], [])
            self.err(f"name {path!r} is not a parameter or an assigned local")
        if kind == "bin":
            return self.binop(n[1], n[2], n[3])
        if kind == "un":
            op = n[1]
            if op == "-":
                e, t = self.expr(n[2])
                if t == BOOL:
                    self.err("negating a bool")
                if self.c_mode and t == INT and not (self.cpromote(self.ckind(n[2])) or (True,))[0]:
                    k = self.cpromote(self.ckind(n[2]))
                    neg = ["int", -e[1]] if e[0] == "int" else self.apply("NEG", [(e, t)])[0]
                    return self.cconv(neg, (True, 64), k), t
                if e[0] in ("int", "float"):
                    return [e[0], -e[1]], t
                return self.apply("NEG", [(e, t)])
            if op == "+":
                return self.expr(n[2])
            if op == "!":
                e, t = self.expr(n[2])
                if t == BOOL:
                    return ["NOT", e], BOOL
                if self.d.truthy_ints and t == INT:
                    return ["CMP_EQ", e, ["int", 0]], BOOL
                if self.d.name in ("rust",) and t == INT:
                    return self.apply("BIT_NOT", [(e, t)])
                self.retype_bool(e, t)
                self.err(f"! on {t}")
            if op == "~" or (op == "^" and self.d.name == "go"):
                e, t = self.expr(n[2])
                if t == FLOAT:
                    self.retype_int([(e, t)])
                if self.c_mode and t == INT and not (self.cpromote(self.ckind(n[2])) or (True,))[0]:
                    k = self.cpromote(self.ckind(n[2]))
                    return self.cconv(self.apply("BIT_NOT", [(e, t)])[0], (True, 64), k), t
                return self.apply("BIT_NOT", [(e, t)])
            self.err(f"unary {op}")
        if kind == "tern":
            c = self.cond(n[1])
            a, ta = self.expr(n[2])
            b, tb = self.expr(n[3])
            return self.if_expr(c, a, ta, b, tb)
        if kind == "block_if":
            c = self.cond(n[1])
            a, ta = self.block_value(n[2])
            b, tb = self.block_value(n[3])
            return self.if_expr(c, a, ta, b, tb)
        if kind == "cast":
            if n[1] in self.d.unsupported_types and self.signed_cast and n[1] in _UNSIGNED_C | {"u64", "UInt64"}:
                return self.expr(n[2])         # (int64_t)((uint64_t)x << k): the wrap is the target width's
            want = self.ir_type(n[1])
            self.signed_cast += want == INT
            try:
                e, t = self.expr(n[2])
            finally:
                self.signed_cast -= want == INT
            if self.c_mode and want == INT and t == INT:
                e = self.cconv(e, self.ckind(n[2]), self.ckind_text(n[1]))
            return self.cast(e, t, want)
        if kind == "ann":
            want = self.ir_type(n[1])
            e, t = self.expr(n[2])
            if t != want:
                self.err(f"type assertion {n[1]} on a {t}")
            return e, t
        if kind == "index":
            return self.index(n)
        if kind == "call":
            return self.call(n[1], n[2], n[3])
        if kind == "mcall":
            return self.method(n[1], n[2], n[3])
        if kind == "tuple":
            self.err("tuple value")
        if kind == "range":
            self.err("range outside a for loop")
        self.err(f"expression {kind}")

    def block_value(self, stmts):
        if len(stmts) != 1 or stmts[0]["k"] != "expr":
            self.err("an if-expression branch that is not a single value")
        return self.expr(stmts[0]["value"])

    def if_expr(self, c, a, ta, b, tb):
        if ta != tb:
            if {ta, tb} == {INT, FLOAT}:
                a, b = self.coerce(a, ta, FLOAT), self.coerce(b, tb, FLOAT)
                ta = tb = FLOAT
            else:
                self.err(f"conditional branches {ta} vs {tb}")
        return ["IF_EXPR", c, a, b], ta

    def cast(self, e, t: str, want: str):
        if want is None or want == t:
            return e, t
        if want == FLOAT and t == INT:
            return self.coerce(e, t, FLOAT), FLOAT
        if want == INT and t == FLOAT:
            return ["TRUNC_INT", e], INT
        if want == INT and t == BOOL:
            return ["IF_EXPR", e, ["int", 1], ["int", 0]], INT
        self.err(f"cast from {t} to {want}")

    def call(self, path: str, arg_nodes: list, labels: list):
        d = self.d
        if path.startswith("self.") and path[5:] in self.sigs:
            path = path[5:]
        if "." in path and path not in self.sigs and path.replace(".", "_") in self.sigs \
                and path.split(".")[0] not in self.env:
            path = path.replace(".", "_")
        if path in self.sigs and path not in self.env:
            sig = self.sigs[path]
            args = [self.expr(a) for a in arg_nodes]
            if len(args) != len(sig["params"]):
                self.err(f"{path}() arity mismatch")
            fixed = []
            cdef = self.cdefs.get(path) if self.c_mode else None
            for i, ((e, t), want) in enumerate(zip(args, sig["params"])):
                if want is None:
                    want = t
                if t != want and e[0] == "var" and e[1] in self.untyped_params and e[1] not in self.widened:
                    raise Widen(e[1], want)           # passed to a typed parameter: that is its type
                if cdef is not None and t == INT and i < len(cdef.params) and \
                        self.ckind_text(cdef.params[i][1]) == (True, 32):
                    e = self.cconv(e, self.ckind(arg_nodes[i]), (True, 32))   # narrower params wrap on entry
                fixed.append(self.coerce(e, t, want))
            ret = sig.get("returns")
            if ret is None:
                self.inferred = True
                ret = INT
            return ["CALL", path, *fixed], ret
        ext = self.externs.get(path) if path not in self.env else None
        if ext is not None:                      # a function of another file (lift_project resolves it)
            args = [self.expr(a) for a in arg_nodes]
            if len(args) != len(ext["params"]):
                self.err(f"{path}() arity mismatch")
            fixed = []
            for (e, t), want in zip(args, ext["params"]):
                fixed.append(self.coerce(e, t, want or t))
            if ext.get("returns") is None:
                self.inferred = True
            return ["CALL", ext["qual"], *fixed], ext.get("returns") or INT
        parts = path.split(".")
        if len(parts) > 1 and parts[0] in self.env:
            e = ("name", parts[0])
            for m in parts[1:-1]:
                e = ("mcall", e, m, [])
            return self.method(e, parts[-1], arg_nodes)
        if path in d.casts or (d.name == "julia" and path in ("Float64", "float")):
            want = d.casts.get(path, FLOAT)
            if len(arg_nodes) != 1:
                self.err(f"{path}() with {len(arg_nodes)} arguments")
            e, t = self.expr(arg_nodes[0])
            if path == "BigInt" and t == FLOAT:
                self.err("BigInt(x) of a non-integral number throws")
            return self.cast(e, t, want)
        entry = d.funcs.get(path)
        if entry is not None:
            return self.library(path, entry, arg_nodes)
        if path in self.patterns:
            return self.pattern_call(path, self.patterns[path], [self.expr(a) for a in arg_nodes])
        if d.name in ("c", "cpp", "java", "csharp") and path in d.types:
            if len(arg_nodes) == 1:                       # C++ functional cast: double(x)
                e, t = self.expr(arg_nodes[0])
                return self.cast(e, t, self.ir_type(path))
        self.err(f"call to {path}() (no op card, library entry or function of this file)")

    def library(self, path: str, entry: tuple, arg_nodes: list):
        kind = entry[0]
        if kind == "no":
            self.err(f"{path}: {entry[1]}")
        args = [self.expr(a) for a in arg_nodes]
        if kind == "op":
            op = entry[1]
            spec = self.spec(op)
            if len(args) != spec.arity:
                if op in ("MIN", "MAX") and len(args) > 2:
                    e, t = args[0]
                    for nxt in args[1:]:
                        e, t = self.apply(op, [(e, t), nxt])
                    return e, t
                self.err(f"{path}() with {len(args)} arguments")
            if op in ("FSQRT", "EXP", "LOG", "SIN", "COS", "TAN", "FLOOR", "CEIL", "TRUNC", "ATAN2", "FMOD",
                      "ASIN", "ACOS", "ATAN", "SINH", "COSH", "TANH", "COPYSIGN") and \
                    self.d.name in ("c", "cpp", "java", "csharp", "go", "javascript", "typescript", "swift",
                                    "kotlin", "php", "ruby", "lua", "julia", "zig"):
                args = [(self.coerce(e, t, FLOAT), FLOAT) for e, t in args]
            if op == "ABS" and path in ("fabs", "std::fabs") :
                args = [(self.coerce(e, t, FLOAT), FLOAT) for e, t in args]
            if op == "ABS" and path in ("abs", "labs", "llabs", "imaxabs") and self.d.name in ("c",) and \
                    args[0][1] == FLOAT:
                self.err(f"{path}() of a double truncates in C")
            return self.apply(op, args)
        if kind == "id":
            if len(args) != 1:
                self.err(f"{path}() with {len(args)} arguments")
            return args[0]
        if kind == "cast":
            e, t = args[0]
            return self.cast(e, t, entry[1])
        if kind == "fpow":
            if len(args) != 2:
                self.err(f"{path}() with {len(args)} arguments")
            return self.apply("POW", [(self.coerce(e, t, FLOAT), FLOAT) for e, t in args])
        if kind == "pow_any":
            (a, ta), (b, tb) = args
            if ta == tb == INT and b[0] == "int" and b[1] >= 0:
                return self.apply("POW", args)
            return self.apply("POW", [(self.coerce(a, ta, FLOAT), FLOAT), (self.coerce(b, tb, FLOAT), FLOAT)])
        if kind == "zig_pow":
            if len(args) != 3:
                self.err("std.math.pow(T, a, b)")
            return self.apply("POW", args[1:])
        if kind == "zig_as":
            if len(arg_nodes) != 2 or arg_nodes[0][0] != "name":
                self.err("@as(T, x)")
            want = self.ir_type(arg_nodes[0][1])
            e, t = args[1]
            return self.coerce(e, t, want), want
        if kind == "lua_floor":
            e, t = args[0]
            self.retype_float(e, t)
            if t == INT:
                return e, INT
            f, _ = self.apply(entry[1], [(e, t)])
            return ["TRUNC_INT", f], INT
        if kind == "lua_fmod":
            (a, ta), (b, tb) = args
            if ta == tb == INT:
                return self.apply("REM", args)
            return self.apply("FMOD", [(self.coerce(a, ta, FLOAT), FLOAT), (self.coerce(b, tb, FLOAT), FLOAT)])
        if kind == "julia_round":
            if len(arg_nodes) == 2 and arg_nodes[0][0] == "name":
                want = self.ir_type(arg_nodes[0][1])
                e, t = self.expr(arg_nodes[1])
                if t == INT:
                    return self.coerce(e, t, want), want
                f, _ = self.apply(entry[1], [(e, t)])
                return (["TRUNC_INT", f], INT) if want == INT else (f, FLOAT)
            e, t = args[0]
            if t == INT:
                return e, INT
            return self.apply(entry[1], [(e, t)])
        if kind == "bool_int":
            e, t = args[0]
            return self.cast(e, t, INT)
        if kind == "u64":
            self.err(f"{path} takes an unsigned integer")
        self.err(f"{path}()")

    def method(self, recv_node, name: str, arg_nodes: list):
        r, rt = self.expr(recv_node)
        args = [self.expr(a) for a in arg_nodes]
        d = self.d
        entry = d.methods.get(name)
        if entry is None and ("." + name) in self.patterns:
            return self.pattern_call("." + name, self.patterns["." + name], [(r, rt), *args])
        if entry is None:
            self.err(f"method .{name}()")
        kind = entry[0]
        if kind == "no":
            self.err(f".{name}: {entry[1]}")
        if kind == "op":
            op = entry[1]
            allargs = [(r, rt), *args]
            if op in ("FSQRT", "EXP", "LOG", "SIN", "COS", "TAN", "FLOOR", "CEIL", "TRUNC", "ATAN2") and rt == INT:
                if d.name in ("rust", "swift"):
                    self.err(f".{name}() on an integer")
            return self.apply(op, allargs)
        if kind == "cast":
            if entry[1] == INT and rt == INT and r[0] == "var" and r[1] in self.untyped_params \
                    and r[1] not in self.widened:
                raise Widen(r[1], FLOAT)       # x.to_i / x.toLong(): x was not an integer
            return self.cast(r, rt, entry[1])
        if kind == "id":
            return r, rt
        if kind == "fpow":
            if len(args) != 1:
                self.err(f".{name}() arity")
            if d.name == "kotlin" and rt == INT:
                self.err("Long.pow does not exist; use Double.pow")
            (b, tb), = args
            if name == "powi" and tb != INT:
                self.err(".powi() with a non-integer exponent")
            return self.apply("POW", [(self.coerce(r, rt, FLOAT), FLOAT), (self.coerce(b, tb, FLOAT), FLOAT)])
        if kind == "ipow":
            (b, tb), = args
            if rt != INT or not (b[0] == "int" and b[1] >= 0):
                self.err(".pow() needs an integer receiver and a non-negative literal exponent")
            return self.apply("POW", [(r, rt), (b, tb)])
        if kind == "ruby_pow":
            if len(args) == 2:
                return self.apply("POW_MOD", [(r, rt), *args])
            (b, tb), = args
            if rt == tb == INT and not (b[0] == "int" and b[1] >= 0):
                self.err(".pow() with a negative or variable exponent returns a Rational")
            return self.apply("POW", [(r, rt), (b, tb)])
        if kind == "rem_euclid":
            (b, tb), = args
            if rt != INT or tb != INT:
                self.err(".rem_euclid() on floats")
            m, _ = self.apply("MOD", [(r, rt), (b, tb)])
            ab, _ = self.apply("ABS", [(b, tb)])
            # rem_euclid(a, b) = a mod |b| (always >= 0)
            return ["MOD", r, ab], INT
        if kind == "fdiv":
            (b, tb), = args
            return ["DIV", self.coerce(r, rt, FLOAT), self.coerce(b, tb, FLOAT)], FLOAT
        if kind == "rem_any":
            (b, tb), = args
            if rt == tb == INT:
                return self.apply("REM", [(r, rt), (b, tb)])
            return self.apply("FMOD", [(self.coerce(r, rt, FLOAT), FLOAT), (self.coerce(b, tb, FLOAT), FLOAT)])
        if kind == "ruby_round":
            if args:
                self.err(f".{name}(digits)")
            self.retype_float(r, rt)
            if rt == INT:
                return r, INT
            f, _ = self.apply(entry[1], [(r, rt)])
            return ["TRUNC_INT", f], INT
        if kind == "parity":
            if rt != INT:
                self.err(f".{name} on {rt}")
            return ["CMP_EQ", ["MOD", r, ["int", 2]], ["int", entry[1]]], BOOL
        if kind == "zero":
            return self.apply("CMP_EQ", [(r, rt), (["int", 0], INT) if rt == INT else (["float", 0.0], FLOAT)])
        if kind == "sign":
            z = (["int", 0], INT) if rt == INT else (["float", 0.0], FLOAT)
            return self.apply("CMP_GT" if entry[1] == ">" else "CMP_LT", [(r, rt), z])
        self.err(f".{name}()")

    def pattern_call(self, key: str, cands: list, args: list):
        for op, slots, typ in cands:
            if len(slots) != len(args) or sorted(slots) != list(range(len(slots))):
                continue
            ordered = [None] * len(args)
            for pos, slot in enumerate(slots):
                ordered[slot] = args[pos]
            spec = self.ops.get(op)
            if spec is None:
                continue
            types = [t for _, t in ordered]
            if typ is not None and types and types[0] != typ:
                continue
            if spec.result_type(types) is None:
                continue
            return self.apply(op, ordered)
        # an untyped parameter passed to a typed helper (cm_min_i) takes the helper's type
        for op, slots, typ in cands:
            spec = self.ops.get(op)
            if typ is None and spec is not None and len({sig[0] for sig in spec.types}) == 1:
                typ = spec.types[0][0]                # GCD: every signature takes ints
            if typ is None or len(slots) != len(args):
                continue
            for e, t in args:
                if t != typ and e[0] == "var" and e[1] in self.untyped_params and e[1] not in self.widened:
                    raise Widen(e[1], typ)
        self.err(f"{key.lstrip('.')}() matches no op card signature for these argument types")


def _vars_in(e) -> list[str]:
    if not isinstance(e, list) or not e:
        return []
    if e[0] == "var":
        return [e[1]]
    if e[0] in ("int", "float", "bool"):
        return []
    return [v for a in e[(2 if e[0] == "CALL" else 1):] for v in _vars_in(a)]


def _zero(t: str):
    return {"int": ["int", 0], "float": ["float", 0.0], "bool": ["bool", False]}[t]


def _var_of(e) -> str | None:
    return e[1] if e[0] == "name" else None


def _uses_bigint(fn: FnDef) -> bool:
    found = []

    def walk(x):
        if isinstance(x, tuple):
            if x and x[0] == "num" and x[2] == "n":
                found.append(1)
            if x and x[0] == "call" and x[1] == "BigInt":
                found.append(1)
            for y in x:
                walk(y)
        elif isinstance(x, list):
            for y in x:
                walk(y)
        elif isinstance(x, dict):
            for y in x.values():
                walk(y)
    walk(fn.body or [])
    return bool(found)


def _implicit_return(stmts: list[dict]) -> list[dict]:
    if not stmts:
        return stmts
    last = stmts[-1]
    if last["k"] == "expr":
        v = last["value"]
        if v[0] == "block_if":
            return stmts[:-1] + [{"k": "if", "cond": v[1], "then": _implicit_return(v[2]),
                                  "else": _implicit_return(v[3]), "line": last["line"]}]
        return stmts[:-1] + [{"k": "return", "value": v, "line": last["line"]}]
    if last["k"] == "if" and last["else"]:
        return stmts[:-1] + [{**last, "then": _implicit_return(last["then"]),
                              "else": _implicit_return(last["else"])}]
    return stmts


def _always_returns(body: list[dict]) -> bool:
    if not body:
        return False
    last = body[-1]
    if last["k"] == "return":
        return True
    if last["k"] == "if":
        return _always_returns(last["then"]) and _always_returns(last["else"])
    if last["k"] == "while" and last["cond"] == ["bool", True]:
        return not _breaks(last["body"])
    return False


def _breaks(body) -> bool:
    for s in body:
        if s["k"] == "break":
            return True
        if s["k"] == "if" and (_breaks(s["then"]) or _breaks(s["else"])):
            return True
    return False


def _coerce_returns(body: list[dict], ret: str, low: Lowerer) -> list[dict]:
    out = []
    for s in body:
        s = dict(s)
        if s["k"] == "return":
            t = s.pop("t", ret)
            s["value"] = low.coerce(s["value"], t, ret)
        for key in ("then", "else", "body"):
            if key in s:
                s[key] = _coerce_returns(s[key], ret, low)
        out.append(s)
    return out


# -- public API -------------------------------------------------------------------------------------------------------

def dialect(lang: str) -> Dialect:
    d = DIALECTS.get(lang)
    if d is None:
        raise KeyError(f"no text frontend for {lang!r} (have: {', '.join(sorted(DIALECTS))})")
    return d


def lift_source(source: str, ops: dict[str, OpSpec], lang: str, only: list[str] | None = None,
                param_hints: dict[str, dict[str, str]] | None = None, externs: dict[str, dict] | None = None,
                close: bool = True) -> list[Lifted]:
    """Lift every function of ``source`` (written in ``lang``). Same contract as frontend_python.lift_source:
    calls between lifted functions resolve, and a function that calls one that did not lift fails too."""
    d = dialect(lang)
    lines = source.splitlines()
    patterns = emit_patterns(ops, d)
    fns = find_functions(source, d)
    helper_names = {k for k in patterns if not k.startswith(".")}
    sigs: dict[str, dict] = {}
    for f in fns:
        if f.body is None or (f.name in helper_names and f.name.startswith("cm_")):
            continue
        try:
            low = Lowerer(f, d, ops, {}, patterns, {}, (param_hints or {}).get(f.name))
            ptypes = []
            for pname, ptext in f.params:
                t = low.ir_type(ptext) if ptext else (param_hints or {}).get(f.name, {}).get(pname)
                ptypes.append(t)
            ret = low.ir_type(f.ret) if f.ret else None
            sigs[f.name] = {"params": ptypes, "returns": ret}
        except Unsupported:
            continue
    results: dict[str, Lifted] = {}
    for _round in range(3):                   # untyped callees: their inferred result types feed the callers
        before = {n: dict(s) for n, s in sigs.items()}
        results = _lift_all(fns, d, ops, sigs, patterns, helper_names, lines, lang, param_hints, externs)
        if before == sigs:
            break
    if close:
        from .frontend_python import close_calls
        external = {e["qual"] for e in (externs or {}).values()}
        close_calls(results, lambda c: c in external)
    return [lf for lf in results.values() if not only or lf.name in only]


def param_range(lang: str, type_text: str):
    """The values a parameter of this source type holds where the lift does not wrap them on entry (C: ``int`` and
    ``int32_t``, and the elements of an ``int *`` array; narrower and unsigned ones are wrapped as C converts them):
    (lo, hi), or None when every IR int is a faithful argument."""
    if lang not in ("c", "cpp") or not type_text:
        return None
    t = type_text.rstrip("*").strip()
    t = t[5:] if t.startswith("std::") else t
    k = _C_KINDS.get(t)
    if k is None or k[1] <= 1:
        return None
    return (-(1 << 31), (1 << 31) - 1) if k == (True, 32) else None


def signatures(source: str, ops: dict[str, OpSpec], lang: str) -> dict[str, dict]:
    """Each function's declared signature {name: {"params": [type|None], "returns": type|None}} without lifting
    bodies (lift_project gives them to the other files of a project)."""
    d = dialect(lang)
    out = {}
    for f in find_functions(source, d):
        if f.body is None or f.name == "main":
            continue
        low = Lowerer(f, d, ops, {}, {}, {}, None)
        try:
            out[f.name] = {"params": [low.ir_type(t) if t else (d.untyped if d.untyped in (INT, FLOAT) else INT)
                                      for _, t in f.params],
                           "returns": low.ir_type(f.ret) if f.ret else None}
            if lang in ("c", "cpp"):
                out[f.name]["c_ret"] = f.ret          # the result's C kind (an unsigned result keeps wrapping)
        except Unsupported:
            continue
    return out


def _lift_all(fns, d, ops, sigs, patterns, helper_names, lines, lang, param_hints, externs=None) -> dict:
    results: dict[str, Lifted] = {}
    cdefs = {f.name: f for f in fns if f.body is not None}
    for f in fns:
        if f.name in helper_names and f.name.startswith("cm_"):
            continue                          # codegen's own helpers: their calls lift to the op card
        if f.name == "main":
            continue
        src = "\n".join(lines[f.line - 1: f.end_line])
        if f.body is None:
            results[f.name] = Lifted(f.name, False, None, src, [f"line {f.end_line}: {f.error}"], False, f.line, lang)
            continue
        widened: dict = {}
        for _ in range(8 + 2 * len(f.params)):
            low = Lowerer(f, d, ops, sigs, patterns, widened, (param_hints or {}).get(f.name))
            low.externs = externs or {}
            low.cdefs = cdefs
            try:
                ir = low.lower()
                sig = sigs.setdefault(f.name, {"params": [], "returns": None})
                sig["params"] = [p["type"] for p in ir["params"]]
                sig["returns"] = ir["returns"]
                results[f.name] = Lifted(f.name, True, ir, src, [], low.inferred, f.line, lang,
                                         [t for _, t in f.params])
                break
            except Widen as w:
                if widened.get(w.name) == w.typ:
                    results[f.name] = Lifted(f.name, False, None, src, [f"{w.name} is both int and float"],
                                             True, f.line, lang)
                    break
                widened[w.name] = w.typ
            except Unsupported as exc:
                results[f.name] = Lifted(f.name, False, None, src, [str(exc)], low.inferred, f.line, lang)
                break
        else:
            results[f.name] = Lifted(f.name, False, None, src, ["type inference did not settle"], True, f.line, lang)
    return results
