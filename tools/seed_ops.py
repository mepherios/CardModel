"""seed_ops — bootstrap data for cards/op/* (run once; the cards are the source of truth).

Provenance: forms and costs from the hub's config/card_redefinitions.py and
config/card_catalog.py, hints from config/language_hints.py (read-only
inputs, 2026-10-21). Each op card adds what the hub kept in code:

  ir.eval    reference semantics (Python lambda) used by the IR interpreter
  ir.types   accepted signatures [arg types..., result type]
  ir.domain  generators for the op-conformance matrix (every op x language)
  emit       per-language / per-family templates used by codegen
  match      how the observer recognises the op in Python source

Where the hub's declared ``domain`` of a form is falsifiable, the claim is
kept in ``metadata.hub_domain`` and ``domain`` holds the domain the witness
actually verifies (tests/test_redefinition_forms.py shows both).
"""

I = {"int": [-1000000, 1000000]}
U32 = {"int": [0, 4294967295], "edges": [2**31 - 1, 2**31, 2**32 - 2]}
BIG = {"int": [-(2**40), 2**40], "edges": [2**31, 2**31 + 1, 2**32 - 1, 2**32, -(2**31) - 1, -(2**32)]}
I32 = {"int": [-(2**31), 2**31 - 1]}
SMALL = {"int": [-5, 5]}
F = {"float": [-1000.0, 1000.0]}
B = {"bool": True}

C_LIKE_SAME = lambda sym: {"python": f"({{0}} {sym} {{1}})", "c_like": f"({{0}} {sym} {{1}})",  # noqa: E731
                           "ruby": f"({{0}} {sym} {{1}})", "lua": f"({{0}} {sym} {{1}})", "lean": f"({{0}} {sym} {{1}})"}


def arith(name, sym, statement, cost, forms, hub_kind="binop", py_ast=None, float_ok=True, lean=True):
    emit = C_LIKE_SAME(sym)
    if not lean:
        emit["lean"] = "UNSUPPORTED"
    types = [["int", "int", "int"]] + ([["float", "float", "float"]] if float_ok else [])
    dom = {"int": [I, I]}
    if float_ok:
        dom["float"] = [F, F]
    return {"name": name, "statement": statement, "cost": cost, "tier": 0,
            "ir": {"arity": 2, "eval": f"lambda a, b: a {sym} b", "types": types, "domain": dom},
            "emit": emit, "forms": forms, "match": {"python": {"binop": [py_ast]}} if py_ast else {},
            "metadata": {"hub_kind": hub_kind}}


def form(name, cost, domain, code=None, lang="python", runnable=True, notes="", libs=None, hub_domain=None,
         str_impl=None):
    f = {"name": name, "cost": cost, "domain": domain, "lang": lang, "runnable": runnable}
    if lang != "python" and code:
        f["role"] = "hint"  # another language's spelling: verified by the witness, not picked by cheapest()
    if code:
        f["code"] = code
    if str_impl:
        f["str_impl"] = str_impl
    if notes:
        f["notes"] = notes
    if libs:
        f["libs"] = libs
    if hub_domain and hub_domain != domain:
        f["hub_domain"] = hub_domain
    return f


BP = ["bit_primitives"]
RH = ["redef_helpers"]

OPS = [
    arith("ADD", "+", "integer/float addition", 1.0, [
        form("native", 1.0, "any", "lambda a, b: a + b"),
        form("bit", 40.0, "u32", "bp.add_via_bits", libs=BP, hub_domain="int", notes="fixed 32-bit ripple-carry"),
        form("nand_via_bit", 200.0, "u32", runnable=False, str_impl="NAND-chain expansion of bit.add_via_bits",
             notes="universality demonstration; not runnable"),
        form("sage", 2.0, "int", lang="sage", runnable=False, code="a + b", notes="sage Integer+; sage is not a dependency"),
        form("rust_hint", 1.0, "u32", lang="rust", code="(({0} as u32).wrapping_add({1} as u32) as i64)",
             notes="rust u32 wrapping; matches bit domain"),
    ], py_ast="Add"),
    arith("SUB", "-", "integer/float subtraction", 1.0, [
        form("native", 1.0, "any", "lambda a, b: a - b"),
        form("bit", 80.0, "u32", "bp.sub_via_bits", libs=BP, hub_domain="int", notes="fixed 32-bit two's complement"),
        form("sage", 2.0, "int", lang="sage", runnable=False, code="a - b"),
        form("rust_hint", 1.0, "u32", lang="rust", code="(({0} as u32).wrapping_sub({1} as u32) as i64)"),
    ], py_ast="Sub"),
    arith("MUL", "*", "integer/float multiplication", 3.0, [
        form("native", 3.0, "any", "lambda a, b: a * b"),
        form("bit", 40.0, "u32", "bp.mul_via_bits", libs=BP, hub_domain="int", notes="shift-and-add, fixed 32-bit"),
        form("sage", 6.0, "int", lang="sage", runnable=False, code="a * b"),
        form("rust_hint", 3.0, "u32", lang="rust", code="(({0} as u32).wrapping_mul({1} as u32) as i64)"),
    ], py_ast="Mult"),
]

OPS += [
    {"name": "DIV", "statement": "true division (float result)", "cost": 5.0, "tier": 0,
     "ir": {"arity": 2, "eval": "lambda a, b: a / b", "types": [["float", "float", "float"]],
            "domain": {"float": [F, F]}},
     "emit": {"python": "({0} / {1})", "c_like": "({0} / {1})", "ruby": "({0} / {1})", "lua": "({0} / {1})",
              "lean": "UNSUPPORTED"},
     "forms": [form("native", 5.0, "float", "lambda a, b: a / b"),
               form("reciprocal_mul", 6.0, "float", "lambda a, b: a * (1.0 / b)",
                    notes="a * (1/b); can differ from a/b in the last ulp (compared with rel_tol 1e-12)")],
     "match": {"python": {"binop": ["Div"]}}},
    {"name": "FLOORDIV", "statement": "integer floor division (Python semantics: rounds toward -inf)", "cost": 4.0,
     "tier": 0,
     "ir": {"arity": 2, "eval": "lambda a, b: a // b", "types": [["int", "int", "int"]],
            "domain": {"int": [I, {"int": [-1000, 1000]}]}},
     "emit": {"python": "({0} // {1})", "c_like": "cm_floordiv({0}, {1})", "java": "Math.floorDiv({0}, {1})",
              "ruby": "({0} / {1})", "lua": "({0} // {1})", "lean": "(Int.fdiv {0} {1})"},
     "forms": [form("native", 4.0, "int", "lambda a, b: a // b"),
               form("rust_hint", 4.0, "int", lang="rust", code="{0}.div_euclid({1})",
                    notes="hub note: 'matches Python semantics for negative operands' -- the witness checks it")],
     "match": {"python": {"binop": ["FloorDiv"]}}},
    {"name": "MOD", "statement": "integer modulo (Python semantics: sign of the divisor)", "cost": 4.0, "tier": 0,
     "ir": {"arity": 2, "eval": "lambda a, b: a % b", "types": [["int", "int", "int"]],
            "domain": {"int": [I, {"int": [-1000, 1000]}]}},
     "emit": {"python": "({0} % {1})", "c_like": "cm_floormod({0}, {1})", "java": "Math.floorMod({0}, {1})",
              "ruby": "({0} % {1})", "lua": "({0} % {1})", "lean": "(Int.fmod {0} {1})"},
     "forms": [form("native", 4.0, "int", "lambda a, b: a % b"),
               form("pow2_bit", 1.0, "int", "lambda a, b: a & (b - 1) if b and (b & (b - 1)) == 0 else a % b",
                    notes="x mod 2^k -> x & (2^k - 1); exact when b is a power of 2"),
               form("c_naive", 1.0, "nonneg_int", lang="c", code="({0} % {1})",
                    notes="C's % truncates: equal to Python's only when both operands are >= 0")],
     "match": {"python": {"binop": ["Mod"]}}},
    {"name": "POW", "statement": "a ** b (non-negative integer exponent, or float power)", "cost": 20.0, "tier": 0,
     "ir": {"arity": 2, "eval": "lambda a, b: a ** b", "types": [["int", "int", "int"], ["float", "float", "float"]],
            "domain": {"int": [{"int": [-30, 30]}, {"int": [0, 12]}],
                       "float": [{"float": [0.1, 50.0]}, {"float": [-3.0, 3.0]}]}},
     "emit": {"python": "({0} ** {1})", "c_like": {"int": "cm_ipow({0}, {1})", "float": "pow({0}, {1})"},
              "javascript": {"int": "({0} ** {1})", "float": "Math.pow({0}, {1})"},
              "rust": {"int": "cm_ipow({0}, {1})", "float": "(({0}).powf({1}))"},
              "go": {"int": "cm_ipow({0}, {1})", "float": "math.Pow({0}, {1})"},
              "swift": {"int": "cm_ipow({0}, {1})", "float": "pow({0}, {1})"},
              "java": {"int": "cm_ipow({0}, {1})", "float": "Math.pow({0}, {1})"},
              "ruby": "({0} ** {1})", "lua": {"int": "cm_ipow({0}, {1})", "float": "({0} ^ {1})"},
              "lean": {"int": "({0} ^ ({1}).toNat)"}},
     "requires": {"go": {"float": ["math"]}},
     "forms": [form("native", 20.0, "any", "lambda a, b: a ** b"),
               form("square_mul", 8.0, "u32", "lambda a, b: bp.pow_via_bits(a, b) if b >= 0 else a ** b", libs=BP,
                    hub_domain="int", notes="square-and-multiply over 32-bit mul_via_bits")],
     "match": {"python": {"binop": ["Pow"]}}},
    {"name": "NEG", "statement": "unary minus (-x)", "cost": 1.0, "tier": 0,
     "ir": {"arity": 1, "eval": "lambda a: -a", "types": [["int", "int"], ["float", "float"]],
            "domain": {"int": [I], "float": [F]}},
     "emit": {"python": "(-{0})", "c_like": "(-{0})", "ruby": "(-{0})", "lua": "(-{0})", "lean": "(-{0})"},
     "forms": [form("native", 1.0, "any", "lambda a: -a"),
               form("twos", 3.0, "u32", "lambda a: bp.add_via_bits(bp._mask(~a), 1)", libs=BP, hub_domain="int",
                    notes="two's complement via bit_primitives"),
               form("sub_from_0", 1.0, "int", "lambda a: 0 - a")],
     "match": {"python": {"unaryop": ["USub"]}}},
    {"name": "ABS", "statement": "absolute value", "cost": 1.0, "tier": 0,
     "ir": {"arity": 1, "eval": "lambda a: abs(a)", "types": [["int", "int"], ["float", "float"]],
            "domain": {"int": [I], "float": [F]}},
     "emit": {"python": "abs({0})", "c_like": {"int": "cm_abs_i({0})", "float": "fabs({0})"},
              "javascript": {"int": "cm_abs_i({0})", "float": "Math.abs({0})"},
              "rust": {"int": "cm_abs_i({0})", "float": "(({0}).abs())"},
              "go": {"int": "cm_abs_i({0})", "float": "math.Abs({0})"},
              "swift": "abs({0})", "java": "Math.abs({0})", "ruby": "(({0}).abs)", "lua": "math.abs({0})",
              "lean": {"int": "(Int.ofNat (Int.natAbs {0}))"}},
     "requires": {"go": {"float": ["math"]}},
     "forms": [form("native", 1.0, "any", "abs"),
               form("branchless", 3.0, "i32",
                    "lambda a: (a ^ (a >> 31)) - (a >> 31) if a.bit_length() <= 32 else abs(a)", hub_domain="int",
                    notes="branchless 32-bit trick; exact only for -2**31 <= a < 2**31")],
     "match": {"python": {"call": ["abs"]}}},
    {"name": "MIN", "statement": "min(a, b) (Python order: b if b < a else a)", "cost": 0.8, "tier": 0,
     "ir": {"arity": 2, "eval": "lambda a, b: min(a, b)", "types": [["int", "int", "int"], ["float", "float", "float"]],
            "domain": {"int": [SMALL, SMALL], "float": [F, F]}},
     "emit": {"python": "min({0}, {1})", "c_like": {"int": "cm_min_i({0}, {1})", "float": "cm_min_f({0}, {1})"},
              "java": {"int": "Math.min({0}, {1})", "float": "cm_min_f({0}, {1})"},
              "ruby": {"int": "cm_min_i({0}, {1})", "float": "cm_min_f({0}, {1})"},
              "lua": {"int": "cm_min_i({0}, {1})", "float": "cm_min_f({0}, {1})"}, "lean": {"int": "(min {0} {1})"}},
     "forms": [form("native", 0.8, "any", "lambda a, b: min(a, b)"),
               form("branch", 1.0, "any", "lambda a, b: b if b < a else a")],
     "match": {"python": {"call": ["min"]}}},
    {"name": "MAX", "statement": "max(a, b) (Python order: b if b > a else a)", "cost": 0.8, "tier": 0,
     "ir": {"arity": 2, "eval": "lambda a, b: max(a, b)", "types": [["int", "int", "int"], ["float", "float", "float"]],
            "domain": {"int": [SMALL, SMALL], "float": [F, F]}},
     "emit": {"python": "max({0}, {1})", "c_like": {"int": "cm_max_i({0}, {1})", "float": "cm_max_f({0}, {1})"},
              "java": {"int": "Math.max({0}, {1})", "float": "cm_max_f({0}, {1})"},
              "ruby": {"int": "cm_max_i({0}, {1})", "float": "cm_max_f({0}, {1})"},
              "lua": {"int": "cm_max_i({0}, {1})", "float": "cm_max_f({0}, {1})"}, "lean": {"int": "(max {0} {1})"}},
     "forms": [form("native", 0.8, "any", "lambda a, b: max(a, b)"),
               form("branch", 1.0, "any", "lambda a, b: b if b > a else a")],
     "match": {"python": {"call": ["max"]}}},
]


def bitop(name, sym, statement, forms, py_ast, lua=None):
    emit = {"python": f"({{0}} {sym} {{1}})", "c_like": f"({{0}} {sym} {{1}})", "ruby": f"({{0}} {sym} {{1}})",
            "lua": lua or f"({{0}} {sym} {{1}})", "lean": "UNSUPPORTED"}
    return {"name": name, "statement": statement, "cost": 1.0, "tier": 0,
            "ir": {"arity": 2, "eval": f"lambda a, b: a {sym} b", "types": [["int", "int", "int"]],
                   "domain": {"int": [I, I]}},
            "emit": emit, "forms": forms, "match": {"python": {"binop": [py_ast]}}}


OPS += [
    bitop("BIT_AND", "&", "bitwise AND", [
        form("native", 1.0, "int", "lambda a, b: a & b"),
        form("nand", 2.0, "u32", "bp.nand_and", libs=BP, hub_domain="int", notes="~(NAND(a, b)) -- 2 gates"),
        form("rust_hint", 1.0, "int", lang="rust", code="({0} & {1})")], "BitAnd"),
    bitop("BIT_OR", "|", "bitwise OR", [
        form("native", 1.0, "int", "lambda a, b: a | b"),
        form("nand", 3.0, "u32", "bp.nand_or", libs=BP, hub_domain="int", notes="NAND(NAND(a,a), NAND(b,b))"),
        form("demorgan", 3.0, "u32", "lambda a, b: ~((~a) & (~b)) & bp._MASK", libs=BP, hub_domain="int",
             notes="De Morgan: ~(~a & ~b), masked to 32 bits")], "BitOr"),
    bitop("BIT_XOR", "^", "bitwise XOR", [
        form("native", 1.0, "int", "lambda a, b: a ^ b"),
        form("nand", 4.0, "u32", "bp.nand_xor", libs=BP, hub_domain="int", notes="4-gate NAND tree"),
        form("add_sub", 4.0, "int", "lambda a, b: (a | b) - (a & b)", notes="XOR = OR - AND (all integers)")],
          "BitXor", lua="({0} ~ {1})"),
    {"name": "BIT_NOT", "statement": "bitwise NOT (Python: ~a == -a - 1 on unbounded ints)", "cost": 1.0, "tier": 0,
     "ir": {"arity": 1, "eval": "lambda a: ~a", "types": [["int", "int"]], "domain": {"int": [I]}},
     "emit": {"python": "(~{0})", "c_like": "(~{0})", "rust": "(!{0})", "go": "(^{0})", "ruby": "(~{0})",
              "lua": "(~{0})", "lean": "UNSUPPORTED"},
     "reference_form": "python",
     "forms": [form("python", 1.0, "int", "lambda a: ~a", notes="IR semantics (unbounded two's complement)"),
               form("native", 1.0, "u32", "lambda a: (~a) & bp._MASK", libs=BP, hub_domain="int",
                    notes="the hub's native form is 32-bit masked"),
               form("nand", 1.0, "u32", "bp.nand_not", libs=BP, hub_domain="int", notes="NAND(a, a) -- 1 gate"),
               form("xor_mask", 1.0, "u32", "lambda a: a ^ bp._MASK", libs=BP, hub_domain="int",
                    notes="NOT = XOR with all-1s (32-bit)")],
     "match": {"python": {"unaryop": ["Invert"]}}},
    {"name": "SHIFT_LEFT", "statement": "x << k", "cost": 1.0, "tier": 0,
     "ir": {"arity": 2, "eval": "lambda a, b: a << b", "types": [["int", "int", "int"]],
            "domain": {"int": [{"int": [-1000, 1000]}, {"int": [0, 40]}]}},
     "emit": {"python": "({0} << {1})", "c_like": "({0} << {1})", "c": "((int64_t)((uint64_t)({0}) << ({1})))",
              "ruby": "({0} << {1})", "lua": "({0} << {1})", "lean": "UNSUPPORTED"},
     "forms": [form("native", 1.0, "int", "lambda x, k: x << k"),
               form("mul_pow2", 3.0, "int", "lambda x, k: x * (1 << k)",
                    notes="x * 2^k; inverse of the CONST_MUL_POW2 rewrite")],
     "match": {"python": {"binop": ["LShift"]}}, "metadata": {"hub_description": "x 2^k, cheap"}},
    {"name": "SHIFT_RIGHT", "statement": "x >> k (arithmetic: rounds toward -inf)", "cost": 1.0, "tier": 0,
     "ir": {"arity": 2, "eval": "lambda a, b: a >> b", "types": [["int", "int", "int"]],
            "domain": {"int": [{"int": [-1000000000, 1000000000]}, {"int": [0, 40]}]}},
     "emit": {"python": "({0} >> {1})", "c_like": "({0} >> {1})", "ruby": "({0} >> {1})",
              "lua": "({0} // (1 << {1}))", "lean": "UNSUPPORTED"},
     "forms": [form("native", 1.0, "int", "lambda x, k: x >> k"),
               form("floordiv", 4.0, "int", "lambda x, k: x // (1 << k)", hub_domain="nonneg_int",
                    notes="the hub said 'only equal for x >= 0'; floor division by 2**k equals the arithmetic "
                          "shift for every Python int, which the witness checks on negative x too")],
     "match": {"python": {"binop": ["RShift"]}}},
]


def cmp(name, sym, py_ast, js=None, lua=None, lean=None):
    return {"name": name, "statement": f"comparison {sym}", "cost": 1.0, "tier": 0,
            "ir": {"arity": 2, "eval": f"lambda a, b: a {sym} b",
                   "types": [["int", "int", "bool"], ["float", "float", "bool"]] + (
                       [["bool", "bool", "bool"]] if sym in ("==", "!=") else []),
                   "domain": {"int": [SMALL, SMALL],
                              "float": [{"choice": [-1.5, 0.0, 2.5, 3.0]}, {"choice": [-1.5, 0.0, 2.5, 3.0]}],
                              "bool": [B, B]}},
            "emit": {"python": f"({{0}} {sym} {{1}})", "c_like": f"({{0}} {sym} {{1}})",
                     "javascript": js or f"({{0}} {sym} {{1}})", "ruby": f"({{0}} {sym} {{1}})",
                     "lua": lua or f"({{0}} {sym} {{1}})", "lean": lean or f"(decide ({{0}} {sym} {{1}}))"},
            "forms": [form("native", 1.0, "any", f"lambda a, b: a {sym} b")],
            "match": {"python": {"cmpop": [py_ast]}}}


OPS += [
    cmp("CMP_EQ", "==", "Eq", js="({0} === {1})", lean="({0} == {1})"),
    cmp("CMP_NE", "!=", "NotEq", js="({0} !== {1})", lua="({0} ~= {1})", lean="({0} != {1})"),
    cmp("CMP_LT", "<", "Lt"), cmp("CMP_LE", "<=", "LtE"), cmp("CMP_GT", ">", "Gt"), cmp("CMP_GE", ">=", "GtE"),
    {"name": "AND", "statement": "short-circuit boolean and", "cost": 0.5, "tier": 0,
     "ir": {"arity": 2, "special": True, "types": [["bool", "bool", "bool"]], "domain": {"bool": [B, B]}},
     "emit": {"python": "({0} and {1})", "c_like": "({0} && {1})", "ruby": "({0} && {1})", "lua": "({0} and {1})",
              "lean": "({0} && {1})"},
     "forms": [form("native", 0.5, "any", "lambda a, b: a and b")], "match": {"python": {"boolop": ["And"]}},
     "metadata": {"hub_names": ["LOGIC_AND", "LOGIC_AND_PAIR", "LOGIC_AND_CHAIN"]}},
    {"name": "OR", "statement": "short-circuit boolean or", "cost": 0.5, "tier": 0,
     "ir": {"arity": 2, "special": True, "types": [["bool", "bool", "bool"]], "domain": {"bool": [B, B]}},
     "emit": {"python": "({0} or {1})", "c_like": "({0} || {1})", "ruby": "({0} || {1})", "lua": "({0} or {1})",
              "lean": "({0} || {1})"},
     "forms": [form("native", 0.5, "any", "lambda a, b: a or b")], "match": {"python": {"boolop": ["Or"]}},
     "metadata": {"hub_names": ["LOGIC_OR", "LOGIC_OR_PAIR", "LOGIC_OR_CHAIN"]}},
    {"name": "NOT", "statement": "boolean not", "cost": 0.5, "tier": 0,
     "ir": {"arity": 1, "eval": "lambda a: not a", "types": [["bool", "bool"]], "domain": {"bool": [B]}},
     "emit": {"python": "(not {0})", "c_like": "(!{0})", "ruby": "(!{0})", "lua": "(not {0})", "lean": "(!{0})"},
     "forms": [form("native", 0.5, "any", "lambda a: not a")], "match": {"python": {"unaryop": ["Not"]}}},
    {"name": "IF_EXPR", "statement": "lazy conditional expression (x if c else y)", "cost": 1.0, "tier": 0,
     "ir": {"arity": 3, "special": True,
            "types": [["bool", "int", "int", "int"], ["bool", "float", "float", "float"], ["bool", "bool", "bool", "bool"]],
            "domain": {"int": [B, I, I]}},
     "emit": {"python": "({1} if {0} else {2})", "c_like": "({0} ? {1} : {2})",
              "rust": "(if {0} {{ {1} }} else {{ {2} }})",
              "go": "func() {type} {{ if {0} {{ return {1} }}; return {2} }}()",
              "ruby": "({0} ? {1} : {2})", "lua": "(function() if {0} then return {1} else return {2} end end)()",
              "lean": "(if {0} then {1} else {2})"},
     "forms": [form("native", 1.0, "any", "lambda c, a, b: a if c else b")], "match": {"python": {"node": ["IfExp"]}}},
    {"name": "POW_MOD", "statement": "pow(a, b, m) -- modular exponentiation (b >= 0, m > 0)", "cost": 15.0,
     "tier": 1,
     "ir": {"arity": 3, "eval": "lambda a, b, m: pow(a, b, m)", "types": [["int", "int", "int", "int"]],
            "domain": {"int": [I, {"int": [0, 200]}, {"int": [2, 3000000]}]}},
     "emit": {"python": "pow({0}, {1}, {2})", "c_like": "cm_powmod({0}, {1}, {2})",
              "ruby": "(({0}).pow({1}, {2}))", "lua": "cm_powmod({0}, {1}, {2})", "lean": "(cm_powmod {0} {1} {2})"},
     "forms": [form("native", 15.0, "modular", "lambda a, b, n: pow(a, b, n)"),
               form("square_mul", 15.0, "modular", "lambda a, b, n: pow(a, b, n)",
                    notes="CPython already uses square-and-multiply internally"),
               form("rust_hint", 15.0, "modular", lang="rust", runnable=False,
                    str_impl="num_modular::ModularPow::powm(a, b, n)", notes="needs the num_modular crate")],
     "match": {"python": {"call": ["pow/3"]}}, "metadata": {"hub_card": "POW_MOD", "hub_cost": 15.0}},
    {"name": "GCD", "statement": "greatest common divisor (non-negative, gcd(0, 0) = 0)", "cost": 6.0, "tier": 1,
     "ir": {"arity": 2, "eval": "lambda a, b: math.gcd(a, b)", "types": [["int", "int", "int"]],
            "domain": {"int": [I, I]}},
     "emit": {"python": "math.gcd({0}, {1})", "c_like": "cm_gcd({0}, {1})", "ruby": "(({0}).gcd({1}))",
              "lua": "cm_gcd({0}, {1})", "lean": "(Int.ofNat (Int.gcd {0} {1}))"},
     "requires": {"python": ["math"]},
     "forms": [form("native_math", 6.0, "int", "math.gcd"),
               form("euclidean", 8.0, "int", "lambda a, b: a if b == 0 else math.gcd(b, a % b)",
                    notes="recursive Euclid -- pedagogical; builtin is faster"),
               form("binary_gcd", 10.0, "int", runnable=False, str_impl="Stein's algorithm -- shifts + subtractions",
                    notes="avoids modulo; wins on hardware without fast div")],
     "match": {"python": {"call": ["math.gcd", "gcd"]}}},
    {"name": "TO_FLOAT", "statement": "int -> float conversion", "cost": 0.8, "tier": 0,
     "ir": {"arity": 1, "eval": "lambda a: float(a)", "types": [["int", "float"]], "domain": {"int": [I]}},
     "emit": {"python": "float({0})", "c": "((double)({0}))", "javascript": "Number({0})", "rust": "(({0}) as f64)",
              "go": "float64({0})", "swift": "Double({0})", "java": "((double)({0}))", "ruby": "(({0}).to_f)",
              "lua": "({0} + 0.0)", "lean": "UNSUPPORTED"},
     "forms": [form("native", 0.8, "int", "float")], "match": {"python": {"call": ["float"]}},
     "metadata": {"hub_names": ["TYPE_FLOAT_CAST"]}},
    {"name": "TRUNC_INT", "statement": "float -> int conversion, truncating toward zero (Python int(x))",
     "cost": 0.8, "tier": 0,
     "ir": {"arity": 1, "eval": "lambda a: int(a)", "types": [["float", "int"]],
            "domain": {"float": [{"float": [-1000000.0, 1000000.0]}]}},
     "emit": {"python": "int({0})", "c": "((int64_t)({0}))", "javascript": "cm_trunc_int({0})",
              "rust": "(({0}) as i64)", "go": "int64({0})", "swift": "Int({0})", "java": "((long)({0}))",
              "ruby": "(({0}).to_i)", "lua": "(({0}) >= 0 and math.floor({0}) or math.ceil({0}))",
              "lean": "UNSUPPORTED"},
     "forms": [form("native", 0.8, "float", "int")], "match": {"python": {"call": ["int"]}},
     "metadata": {"hub_names": ["TYPE_INT_CAST"]}},
]

# -- non-IR cards from the hub's catalog / redefinitions (forms, costs, observe matchers) ---------
OPS += [
    {"name": "SQUARE", "statement": "x * x", "cost": 2.5, "tier": 1,
     "forms": [form("native_mul", 3.0, "any", "lambda x: x * x"),
               form("half_cost", 2.5, "any", "lambda x: x * x", notes="per vebjornic/cards.py -- same op, cheaper card label"),
               form("pow2", 20.0, "any", "lambda x: x ** 2", notes="slower than direct mul"),
               form("bit", 40.0, "u32", "bp.square_via_bits", libs=BP, hub_domain="int", notes="fixed 32-bit shift-and-add")],
     "match": {"python": {"pattern": ["MUL", "?x", "?x"]}}, "metadata": {"hub_kind": "fused"},
     "generators": [{"int": [-100000, 100000]}]},
    {"name": "MULADD", "statement": "a*b + c (FMA)", "cost": 3.5, "tier": 1,
     "forms": [form("native", 3.5, "any", "lambda a, b, c: a * b + c"),
               form("decomp", 4.0, "any", "lambda a, b, c: (a * b) + c", notes="explicit decomp; CPython already fuses"),
               form("rust_hint", 3.0, "float", lang="rust", runnable=False, str_impl="a.mul_add(b, c)",
                    notes="rust f32/f64 single-rounding FMA")],
     "match": {"python": {"pattern_any": [["ADD", ["MUL", "?a", "?b"], "?c"], ["ADD", "?c", ["MUL", "?a", "?b"]]]}},
     "metadata": {"hub_kind": "fused"}},
    {"name": "CONST_MUL", "statement": "x * N where N is a constant int", "cost": 2.0, "tier": 1,
     "forms": [form("native", 2.0, "int", "lambda x, n: x * n"),
               form("booth_hint", 1.5, "int", runnable=False, str_impl="signed-digit recoding of N; shifts + adds",
                    notes="wins when bit_length(N) is small and Hamming weight low")],
     "match": {"python": {"pattern_any": [["MUL", "?x", ["int", "?n"]], ["MUL", ["int", "?n"], "?x"]]}},
     "metadata": {"hub_kind": "fused"}},
    {"name": "CONST_MUL_POW2", "statement": "x * 2^k -> x << k", "cost": 1.0, "tier": 1,
     "forms": [form("shift", 1.0, "int", "lambda x, k: x << k", notes="k is bit_length(N) - 1"),
               form("mul", 2.0, "int", "lambda x, k: x * (1 << k)", notes="baseline the shift replaces")],
     "generators": [{"int": [-1000000, 1000000]}, {"int": [0, 30]}],
     "match": {"python": {"pattern_any": [["MUL", "?x", ["int", "?pow2"]], ["MUL", ["int", "?pow2"], "?x"]]}},
     "metadata": {"hub_kind": "fused"}},
    {"name": "CONST_POW", "statement": "x ** N where N is a small int", "cost": 3.0, "tier": 1,
     "forms": [form("native", 3.0, "int", "lambda x, n: x ** n"),
               form("chain", 2.5, "int", "lambda x, n: _const_pow_chain(x, n)", libs=RH,
                    notes="unrolled chain of MULs; wins for small n")],
     "generators": [{"int": [-1000, 1000]}, {"int": [0, 16]}],
     "match": {"python": {"pattern": ["POW", "?x", ["int", "?n"]]}}, "metadata": {"hub_kind": "fused"}},
    {"name": "LCM", "statement": "least common multiple", "cost": 8.0, "tier": 1,
     "generators": [{"int": [-100000, 100000]}, {"int": [-100000, 100000]}],
     "forms": [form("native_math", 8.0, "int", "math.lcm"),
               form("gcd_based", 9.0, "int", "lambda a, b: abs(a * b) // math.gcd(a, b) if a and b else 0",
                    notes="LCM(a,b) = |ab|/GCD(a,b)")],
     "match": {"python": {"call": ["math.lcm"]}}},
    {"name": "SQRT", "statement": "integer square root", "cost": 8.0, "tier": 1,
     "generators": [{"int": [0, 10**12], "edges": [2**31, 2**52 + 1]}],
     "forms": [form("isqrt", 8.0, "nonneg_int", "math.isqrt"),
               form("newton", 12.0, "nonneg_int",
                    "lambda n: (lambda x: x if x*x <= n < (x+1)*(x+1) else None)(math.isqrt(n))",
                    notes="Newton-Raphson (collapsed to isqrt for correctness)")],
     "match": {"python": {"call": ["math.isqrt", "math.sqrt"]}}},
    {"name": "MODINV", "statement": "modular inverse a^{-1} mod n (requires gcd(a, n) = 1)", "cost": 25.0, "tier": 1,
     "forms": [form("native_pow", 25.0, "coprime_mod", "lambda a, n: pow(a, -1, n)",
                    notes="Python 3.8+ pow(a, -1, n); raises ValueError if no inverse"),
               form("xgcd", 12.0, "coprime_mod",
                    "lambda a, n: (lambda g, x, _: x % n if g == 1 else None)(*_xgcd(a, n))", libs=RH,
                    notes="extended Euclidean; identical result when the inverse exists")],
     "generators": [{"int": [-100000, 100000]}, {"int": [2, 100000]}], "filter": "lambda a, n: math.gcd(a, n) == 1",
     "match": {"python": {"call": ["inverse_mod"]}}},
    {"name": "MODINV_PRIME", "statement": "modular inverse a^{-1} mod p where p is known prime", "cost": 15.0,
     "tier": 1,
     "forms": [form("fermat", 15.0, "prime_mod", "lambda a, p: pow(a, p - 2, p)", notes="Fermat; requires p prime"),
               form("native_pow", 25.0, "prime_mod", "lambda a, p: pow(a, -1, p)", notes="same result when p is prime")],
     "generators": [{"int": [1, 1000000]}, {"choice": [3, 5, 7, 11, 13, 101, 1009, 10007, 65537, 1000003]}],
     "filter": "lambda a, p: a % p != 0",
     "match": {"python": {"pattern": ["POW_MOD", "?a", ["SUB", ["var", "?p"], ["int", 2]], ["var", "?p"]]}},
     "metadata": {"hub_names": ["MODINV_FERMAT"]}},
    {"name": "EC_ADD", "statement": "elliptic-curve point addition", "cost": 12.0, "tier": 2,
     "forms": [form("native", 12.0, "ec", lang="sage", runnable=False, str_impl="G + P (sage EllipticCurvePoint)",
                    notes="requires sage; 4 MULs + 1 INV + misc in affine form"),
               form("projective", 8.0, "ec", lang="sage", runnable=False, str_impl="Jacobian-projective addition",
                    notes="no inverse; 12 MULs + 4 SQRs")],
     "metadata": {"hub_kind": "fused", "domain_specific": "elliptic curves (hub/Pheros research)"}},
    {"name": "EC_SCALAR_MUL", "statement": "k * G -- scalar multiplication", "cost": 200.0, "tier": 2,
     "forms": [form("double_add", 200.0, "ec", lang="sage", runnable=False, str_impl="double-and-add O(bit_length(k))"),
               form("window_naf", 160.0, "ec", lang="sage", runnable=False, str_impl="width-w NAF",
                    notes="typically 25% faster than double-add")],
     "metadata": {"hub_kind": "fused", "domain_specific": "elliptic curves (hub/Pheros research)"}},
    {"name": "BIT_NAND", "statement": "NAND -- universal gate (32-bit)", "cost": 1.0, "tier": 0,
     "forms": [form("native", 1.0, "u32", "bp.bit_nand", libs=BP),
               form("nor_based", 5.0, "u32",
                    "lambda a, b: (lambda na, nb: bp.bit_nor(bp.bit_nor(na, nb), bp.bit_nor(na, nb)))(bp.bit_nor(a, a), bp.bit_nor(b, b))",
                    libs=BP, notes="NAND from NOR: 5 NOR gates")],
     "generators": [{"int": [0, 4294967295]}, {"int": [0, 4294967295]}]},
    {"name": "BIT_NOR", "statement": "NOR -- universal alternate basis (32-bit)", "cost": 1.0, "tier": 0,
     "forms": [form("native", 1.0, "u32", "bp.bit_nor", libs=BP)],
     "generators": [{"int": [0, 4294967295]}, {"int": [0, 4294967295]}]},
]

HINTS = {
    "ADD": {"python": ["a + b"], "rust": ["a.wrapping_add(b)", "use .checked_add / .saturating_add for overflow policy"],
            "c": ["a + b", "signed overflow is UB; use unsigned or __builtin_add_overflow"], "go": ["a + b"],
            "js": ["a + b", "BigInt for >2^53; number is IEEE 754 double"], "swift": ["a &+ b", "&+ wraps; + traps on overflow"]},
    "MUL": {"python": ["a * b"], "rust": ["a.wrapping_mul(b)"], "c": ["a * b"], "go": ["a * b"],
            "js": ["Math.imul(a, b)", "32-bit multiply; for >32 use BigInt"], "swift": ["a &* b"]},
    "SQUARE": {"python": ["x * x"], "rust": ["x.wrapping_mul(x)"], "c": ["x * x"], "go": ["x * x"], "js": ["x * x"],
               "swift": ["x &* x"]},
    "POW_MOD": {"python": ["pow(a, b, n)"], "rust": ["modpow(a, b, n)", "", ["num_bigint::ModPow"]],
                "c": ["mpz_powm(r, a, b, n)", "", ["gmp.h"]], "go": ["new(big.Int).Exp(a, b, n)"],
                "js": ["(a ** b) % n  /* BigInt */"], "swift": ["pow(a, b, mod: n)", "requires Numerics package"]},
    "MODINV_PRIME": {"python": ["pow(a, p - 2, p)"], "rust": ["a.modpow(&(p - 2), &p)", "", ["num_bigint::BigInt"]],
                     "c": ["mpz_powm(inv, a, p_minus_2, p)", "", ["gmp.h"]], "sage": ["a^(p - 2) % p"]},
    "SHIFT_LEFT": {"python": ["x << k"], "rust": ["x.wrapping_shl(k)"], "c": ["x << k", "shift count >= bit_width is UB"],
                   "go": ["x << k"], "js": ["x << k", "operates on 32-bit signed"]},
    "BIT_XOR": {"python": ["a ^ b"], "rust": ["a ^ b"], "c": ["a ^ b"], "go": ["a ^ b"], "js": ["a ^ b"], "swift": ["a ^ b"]},
    "BIT_NAND": {"python": ["~(a & b)"], "rust": ["!(a & b)"], "c": ["~(a & b)"],
                 "verilog": ["~(a & b)", "gate-level target -- useful for HDL emission"]},
    "CMP_EQ": {"python": ["a == b"], "rust": ["a == b", "requires PartialEq; floats: use approx crate"],
               "c": ["a == b", "for strings use strcmp(a,b) == 0"], "go": ["a == b"],
               "js": ["a === b", "prefer === over == to avoid coercion"]},
    "GCD": {"python": ["math.gcd(a, b)"], "rust": ["num::integer::gcd(a, b)", "", ["num::integer"]],
            "c": ["__gcd(a, b)", "C++ STL; use mpz_gcd for big ints"], "go": ["new(big.Int).GCD(nil, nil, a, b)", "", ["math/big"]]},
}


# per-domain generators: forms whose claim depends on bit width are exercised at that width, and the
# hub's original (wider) claims are exercised on wide inputs, so an overstated domain shows as refuted.
DOMAIN_GENERATORS = {
    "ADD": {"u32": [U32, U32], "int": [BIG, BIG]},
    "SUB": {"u32": [U32, U32], "int": [BIG, BIG]},
    "MUL": {"u32": [U32, U32], "int": [BIG, BIG]},
    "POW": {"u32": [U32, {"int": [0, 20]}], "int": [{"int": [-1000, 1000]}, {"int": [0, 20]}]},
    "NEG": {"u32": [U32], "int": [BIG]},
    "ABS": {"i32": [I32], "int": [BIG]},
    "SQUARE": {"u32": [U32], "int": [BIG]},
    "BIT_AND": {"u32": [U32, U32], "int": [BIG, BIG]},
    "BIT_OR": {"u32": [U32, U32], "int": [BIG, BIG]},
    "BIT_XOR": {"u32": [U32, U32], "int": [BIG, BIG]},
    "BIT_NOT": {"u32": [U32], "int": [BIG]},
    "SHIFT_RIGHT": {"nonneg_int": [{"int": [0, 1000000000]}, {"int": [0, 40]}]},
    "MOD": {"nonneg_int": [{"int": [0, 1000000]}, {"int": [1, 1000]}]},
    "FLOORDIV": {"nonneg_int": [{"int": [0, 1000000]}, {"int": [1, 1000]}]},
}
for _op in OPS:
    if _op["name"] in DOMAIN_GENERATORS:
        _op["domain_generators"] = DOMAIN_GENERATORS[_op["name"]]
for _op in OPS:
    if _op["name"] == "FLOORDIV":
        for _f in _op["forms"]:
            if _f["name"] == "rust_hint":
                _f.update(domain="nonneg_int", hub_domain="int",
                          notes="div_euclid equals floor division when the divisor is positive; the hub note "
                                "('matches Python semantics for negative operands') is checked on negative divisors too")
