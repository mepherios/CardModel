"""atoms — the operations the engine's math reaches that the IR's basis did not have, as op card data.

Each entry is an op card (``tools/seed_unreal.py`` writes the cards and appends their atoms to the prime ledger):
its reference semantics (``ir.eval``, IEEE binary64 as Python computes it), its types, the domain conformance
draws from, and one template per language card, or ``UNSUPPORTED`` where a language has no exact spelling (a
declared gap of the conformance matrix, never a guess).

  analysis  real functions of the C library (sqrt, the trigonometric, exponential and logarithmic families,
            rounding to integers, fmod), and F32, rounding a double to binary32
  bits      a float's bits as an integer and back, and bit counting: what bit-level code in the engine reads

Honest limits (L1): the languages' libraries may differ from the C library in the last place for the
transcendental functions; conformance compares with a relative tolerance of 1e-12 (engines/values.py).
"""
from __future__ import annotations


def _unary(c: str, java: str, js: str, go: str, rust: str, swift: str, py: str, lua: str, ruby: str) -> dict:
    return {"c": c, "java": java, "javascript": js, "go": go, "rust": rust, "swift": swift, "python": py,
            "lua": lua, "ruby": ruby, "lean": "UNSUPPORTED"}


def _fn(name: str, *, java=None, js=None, go=None, rust=None, swift=None, py=None, lua=None, ruby=None) -> dict:
    """The common spelling of a one-argument C library function in every language card."""
    return _unary(f"{name}({{0}})", java or f"Math.{name}({{0}})", js or f"Math.{name}({{0}})",
                  go or f"math.{name.capitalize()}({{0}})", rust or f"(({{0}}).{name}())", swift or f"{name}({{0}})",
                  py or f"math.{name}({{0}})", lua or f"math.{name}({{0}})", ruby or f"Math.{name}({{0}})")


F = [{"float": [-100.0, 100.0]}]
UNIT = [{"float": [-1.0, 1.0]}]
POS = [{"float": [0.001, 1000.0]}]
NEED_MATH = {"go": ["math"], "python": ["math"]}

OPS = {
    "FSQRT": dict(set="analysis", statement="square root of a real (IEEE: correctly rounded; NaN below 0)",
                  eval="lambda a: math.sqrt(a) if a >= 0 else float('nan')", domain=[{"float": [0.0, 1000.0]}],
                  emit=_fn("sqrt"), cost=4.0),
    "SIN": dict(set="analysis", statement="sine (radians)", eval="lambda a: math.sin(a)", domain=F, emit=_fn("sin"),
                cost=20.0),
    "COS": dict(set="analysis", statement="cosine (radians)", eval="lambda a: math.cos(a)", domain=F, emit=_fn("cos"),
                cost=20.0),
    "TAN": dict(set="analysis", statement="tangent (radians)", eval="lambda a: math.tan(a)",
                domain=[{"float": [-1.5, 1.5]}], emit=_fn("tan"), cost=25.0),
    "ASIN": dict(set="analysis", statement="arcsine (NaN outside [-1, 1])",
                 eval="lambda a: math.asin(a) if -1.0 <= a <= 1.0 else float('nan')", domain=UNIT,
                 emit=_fn("asin", lua="math.asin({0})"), cost=25.0),
    "ACOS": dict(set="analysis", statement="arccosine (NaN outside [-1, 1])",
                 eval="lambda a: math.acos(a) if -1.0 <= a <= 1.0 else float('nan')", domain=UNIT,
                 emit=_fn("acos"), cost=25.0),
    "ATAN": dict(set="analysis", statement="arctangent", eval="lambda a: math.atan(a)", domain=F, emit=_fn("atan"),
                 cost=25.0),
    "ATAN2": dict(set="analysis", statement="atan2(y, x): the angle of (x, y)", arity=2,
                  eval="lambda a, b: math.atan2(a, b)", domain=F * 2, cost=30.0,
                  emit={"c": "atan2({0}, {1})", "java": "Math.atan2({0}, {1})", "javascript": "Math.atan2({0}, {1})",
                        "go": "math.Atan2({0}, {1})", "rust": "(({0}).atan2({1}))", "swift": "atan2({0}, {1})",
                        "python": "math.atan2({0}, {1})", "lua": "math.atan({0}, {1})", "ruby": "Math.atan2({0}, {1})",
                        "lean": "UNSUPPORTED"}),
    "EXP": dict(set="analysis", statement="e ** x", eval="lambda a: math.exp(a)", domain=[{"float": [-20.0, 20.0]}],
                emit=_fn("exp"), cost=20.0),
    "EXP2": dict(set="analysis", statement="2 ** x", eval="lambda a: 2.0 ** a", domain=[{"float": [-20.0, 20.0]}],
                 cost=20.0, emit=_unary("exp2({0})", "Math.pow(2.0, {0})", "Math.pow(2, {0})", "math.Exp2({0})",
                                        "(({0}).exp2())", "exp2({0})", "(2.0 ** {0})", "(2.0 ^ {0})",
                                        "(2.0 ** {0})")),
    "LOG": dict(set="analysis", statement="natural logarithm", eval="lambda a: math.log(a)", domain=POS, cost=20.0,
                emit=_fn("log", go="math.Log({0})", rust="(({0}).ln())")),
    "LOG2": dict(set="analysis", statement="logarithm in base 2", eval="lambda a: math.log2(a)", domain=POS, cost=20.0,
                 emit=_fn("log2", java="UNSUPPORTED", go="math.Log2({0})", lua="math.log({0}, 2)")),
    "LOG10": dict(set="analysis", statement="logarithm in base 10", eval="lambda a: math.log10(a)", domain=POS,
                  cost=20.0, emit=_fn("log10", go="math.Log10({0})", lua="math.log({0}, 10)")),
    "SINH": dict(set="analysis", statement="hyperbolic sine", eval="lambda a: math.sinh(a)",
                 domain=[{"float": [-10.0, 10.0]}], cost=25.0, emit=_fn("sinh", lua="UNSUPPORTED")),
    "COSH": dict(set="analysis", statement="hyperbolic cosine", eval="lambda a: math.cosh(a)",
                 domain=[{"float": [-10.0, 10.0]}], cost=25.0, emit=_fn("cosh", lua="UNSUPPORTED")),
    "TANH": dict(set="analysis", statement="hyperbolic tangent", eval="lambda a: math.tanh(a)", domain=F, cost=25.0,
                 emit=_fn("tanh", lua="UNSUPPORTED")),
    "FLOOR": dict(set="analysis", statement="the largest integer not above x, as a float",
                  eval="lambda a: float(math.floor(a))", domain=F, cost=2.0,
                  emit=_unary("floor({0})", "Math.floor({0})", "Math.floor({0})", "math.Floor({0})", "(({0}).floor())",
                              "floor({0})", "float(math.floor({0}))", "(math.floor({0}) + 0.0)", "(({0}).floor.to_f)")),
    "CEIL": dict(set="analysis", statement="the smallest integer not below x, as a float",
                 eval="lambda a: float(math.ceil(a))", domain=F, cost=2.0,
                 emit=_unary("ceil({0})", "Math.ceil({0})", "Math.ceil({0})", "math.Ceil({0})", "(({0}).ceil())",
                             "ceil({0})", "float(math.ceil({0}))", "(math.ceil({0}) + 0.0)", "(({0}).ceil.to_f)")),
    "TRUNC": dict(set="analysis", statement="x rounded toward zero, as a float", eval="lambda a: float(math.trunc(a))",
                  domain=F, cost=2.0,
                  emit=_unary("trunc({0})", "UNSUPPORTED", "Math.trunc({0})", "math.Trunc({0})", "(({0}).trunc())",
                              "trunc({0})", "float(math.trunc({0}))", "UNSUPPORTED", "(({0}).truncate.to_f)")),
    "FMOD": dict(set="analysis", statement="C's fmod: x - n*y with n = trunc(x / y), the sign of x", arity=2,
                 eval="lambda a, b: math.fmod(a, b) if b != 0 else float('nan')",
                 domain=[{"float": [-100.0, 100.0]}, {"float": [0.5, 20.0]}], cost=10.0,
                 emit={"c": "fmod({0}, {1})", "java": "({0} % {1})", "javascript": "({0} % {1})",
                       "go": "math.Mod({0}, {1})", "rust": "({0} % {1})", "swift": "fmod({0}, {1})",
                       "python": "math.fmod({0}, {1})", "lua": "math.fmod({0}, {1})", "ruby": "(({0}).remainder({1}))",
                       "lean": "UNSUPPORTED"}),
    "COPYSIGN": dict(set="analysis", statement="the magnitude of x with the sign of y", arity=2,
                     eval="lambda a, b: math.copysign(a, b)", domain=F * 2, cost=1.0,
                     emit={"c": "copysign({0}, {1})", "java": "Math.copySign({0}, {1})", "javascript": "UNSUPPORTED",
                           "go": "math.Copysign({0}, {1})", "rust": "(({0}).copysign({1}))",
                           "swift": "copysign({0}, {1})", "python": "math.copysign({0}, {1})", "lua": "UNSUPPORTED",
                           "ruby": "UNSUPPORTED", "lean": "UNSUPPORTED"}),
    "ISNAN": dict(set="analysis", statement="x is NaN", eval="lambda a: a != a", domain=F, types=[["float", "bool"]],
                  cost=1.0, emit=_unary("(isnan({0}) != 0)", "Double.isNaN({0})", "Number.isNaN({0})",
                                        "math.IsNaN({0})", "(({0}).is_nan())", "({0}).isNaN",
                                        "math.isnan({0})", "({0} ~= {0})", "(({0}).nan?)")),
    "ISFINITE": dict(set="analysis", statement="x is neither infinite nor NaN", eval="lambda a: math.isfinite(a)",
                     domain=F, types=[["float", "bool"]], cost=1.0,
                     emit=_unary("(isfinite({0}) != 0)", "Double.isFinite({0})", "Number.isFinite({0})",
                                 "(!math.IsInf({0}, 0) && !math.IsNaN({0}))", "(({0}).is_finite())",
                                 "({0}).isFinite", "math.isfinite({0})", "UNSUPPORTED", "(({0}).finite?)")),
    "F32": dict(set="analysis", statement="x rounded to the nearest binary32 (ties to even): float precision",
                eval="lambda a: struct.unpack('f', struct.pack('f', a))[0]",
                domain=[{"float": [-1000000.0, 1000000.0]}], cost=1.0,
                emit=_unary("((double)(float)({0}))", "((double)(float)({0}))", "Math.fround({0})",
                            "float64(float32({0}))", "(({0}) as f32 as f64)", "Double(Float({0}))",
                            "struct.unpack('f', struct.pack('f', {0}))[0]", "(string.unpack('f', string.pack('f', {0})))",
                            "([{0}].pack('f').unpack1('f'))"),
                requires={"python": ["struct"]}),
    "F32_BITS": dict(set="bits", statement="the bits of a binary32 as an unsigned integer",
                     eval="lambda a: struct.unpack('<I', struct.pack('<f', a))[0]", domain=F, types=[["float", "int"]],
                     cost=1.0, emit=dict(_unary(*["UNSUPPORTED"] * 6, "struct.unpack('<I', struct.pack('<f', {0}))[0]",
                                                 "UNSUPPORTED", "UNSUPPORTED")), requires={"python": ["struct"]}),
    "BITS_F32": dict(set="bits", statement="an unsigned 32-bit integer's bits read as a binary32",
                     eval="lambda a: struct.unpack('<f', struct.pack('<I', a & 0xFFFFFFFF))[0]",
                     domain=[{"int": [0, 2139095039]}], types=[["int", "float"]], cost=1.0,
                     emit=dict(_unary(*["UNSUPPORTED"] * 6, "struct.unpack('<f', struct.pack('<I', ({0}) & 0xFFFFFFFF))[0]",
                                      "UNSUPPORTED", "UNSUPPORTED")), requires={"python": ["struct"]}),
    "F64_BITS": dict(set="bits", statement="the bits of a binary64 as an unsigned integer",
                     eval="lambda a: struct.unpack('<Q', struct.pack('<d', a))[0]", domain=F, types=[["float", "int"]],
                     cost=1.0, emit=dict(_unary(*["UNSUPPORTED"] * 6, "struct.unpack('<Q', struct.pack('<d', {0}))[0]",
                                                 "UNSUPPORTED", "UNSUPPORTED")), requires={"python": ["struct"]}),
    "BITS_F64": dict(set="bits", statement="an unsigned 64-bit integer's bits read as a binary64",
                     eval="lambda a: struct.unpack('<d', struct.pack('<Q', a & 0xFFFFFFFFFFFFFFFF))[0]",
                     domain=[{"int": [0, 9218868437227405311]}], types=[["int", "float"]], cost=1.0,
                     emit=dict(_unary(*["UNSUPPORTED"] * 6,
                                      "struct.unpack('<d', struct.pack('<Q', ({0}) & 0xFFFFFFFFFFFFFFFF))[0]",
                                      "UNSUPPORTED", "UNSUPPORTED")), requires={"python": ["struct"]}),
    "CLZ32": dict(set="bits", statement="leading zero bits of a nonzero 32-bit integer",
                  eval="lambda a: 32 - (a & 0xFFFFFFFF).bit_length()", domain=[{"int": [1, 4294967295]}],
                  types=[["int", "int"]], cost=1.0,
                  emit=dict(_unary("((int64_t)__builtin_clz((uint32_t)({0})))", *["UNSUPPORTED"] * 5,
                                   "(32 - (({0}) & 0xFFFFFFFF).bit_length())", "UNSUPPORTED", "UNSUPPORTED"))),
    "CLZ64": dict(set="bits", statement="leading zero bits of a nonzero 64-bit integer",
                  eval="lambda a: 64 - (a & 0xFFFFFFFFFFFFFFFF).bit_length()", domain=[{"int": [1, 1 << 62]}],
                  types=[["int", "int"]], cost=1.0,
                  emit=dict(_unary("((int64_t)__builtin_clzll((uint64_t)({0})))", *["UNSUPPORTED"] * 5,
                                   "(64 - (({0}) & 0xFFFFFFFFFFFFFFFF).bit_length())", "UNSUPPORTED", "UNSUPPORTED"))),
    "CTZ32": dict(set="bits", statement="trailing zero bits of a nonzero 32-bit integer",
                  eval="lambda a: ((a & 0xFFFFFFFF) & -(a & 0xFFFFFFFF)).bit_length() - 1",
                  domain=[{"int": [1, 4294967295]}], types=[["int", "int"]], cost=1.0,
                  emit=dict(_unary("((int64_t)__builtin_ctz((uint32_t)({0})))", *["UNSUPPORTED"] * 5,
                                   "((({0}) & 0xFFFFFFFF) & -(({0}) & 0xFFFFFFFF)).bit_length() - 1", "UNSUPPORTED",
                                   "UNSUPPORTED"))),
    "CTZ64": dict(set="bits", statement="trailing zero bits of a nonzero 64-bit integer",
                  eval="lambda a: ((a & 0xFFFFFFFFFFFFFFFF) & -(a & 0xFFFFFFFFFFFFFFFF)).bit_length() - 1",
                  domain=[{"int": [1, 1 << 62]}], types=[["int", "int"]], cost=1.0,
                  emit=dict(_unary("((int64_t)__builtin_ctzll((uint64_t)({0})))", *["UNSUPPORTED"] * 5,
                                   "((({0}) & 0xFFFFFFFFFFFFFFFF) & -(({0}) & 0xFFFFFFFFFFFFFFFF)).bit_length() - 1",
                                   "UNSUPPORTED", "UNSUPPORTED"))),
    "POPCOUNT": dict(set="bits", statement="the number of one bits of a 64-bit integer",
                     eval="lambda a: (a & 0xFFFFFFFFFFFFFFFF).bit_count()", domain=[{"int": [0, 1 << 62]}],
                     types=[["int", "int"]], cost=1.0,
                     emit=dict(_unary("((int64_t)__builtin_popcountll((uint64_t)({0})))", *["UNSUPPORTED"] * 5,
                                      "bin(({0}) & 0xFFFFFFFFFFFFFFFF).count('1')", "UNSUPPORTED", "UNSUPPORTED"))),
}


def card(name: str) -> dict:
    """The op card for one atom."""
    o = OPS[name]
    arity = o.get("arity", 1)
    types = o.get("types") or [["float"] * arity + ["float"]]
    dom_key = types[0][0]
    req = {k: v for k, v in NEED_MATH.items()}
    for k, v in (o.get("requires") or {}).items():
        req[k] = sorted(set(req.get(k, [])) | set(v))
    return {"name": name, "category": "op", "tier": 1, "statement": o["statement"], "cost": o.get("cost", 1.0),
            "ir": {"arity": arity, "eval": o["eval"], "types": types, "domain": {dom_key: o["domain"]}},
            "emit": o["emit"], "requires": req, "godel_set": o["set"],
            "provenance": {"origin": "cardmodel", "tool": "tools/seed_unreal.py",
                           "observed_in": "Unreal Engine's math (cardmodel unreal scan)"}}


__all__ = ["OPS", "card"]
