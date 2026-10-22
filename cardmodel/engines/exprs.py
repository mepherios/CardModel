"""exprs — expression strings <-> op trees, and exact/real evaluation.

Rules, redefinitions and observed code all meet as op trees (the IR's
expression form): ``["ADD", ["var", "a"], ["int", 1]]``. Function calls
that are not op cards become ``["FN", name, *args]`` (math functions).

``evaluate`` has three modes:
  int       Python ints; ``/`` is exact (fractions.Fraction)
  real      floats with the math module (sympy-style names accepted)
  fraction  exact rationals where possible, floats for transcendental calls

Honest limits (L1): no complex numbers (``I``), no symbolic simplification;
names outside the whitelist raise ``UnknownName`` (fail closed).
"""
from __future__ import annotations

import ast
import math
from fractions import Fraction

BIN = {ast.Add: "ADD", ast.Sub: "SUB", ast.Mult: "MUL", ast.Div: "DIV", ast.FloorDiv: "FLOORDIV",
       ast.Mod: "MOD", ast.Pow: "POW", ast.BitAnd: "BIT_AND", ast.BitOr: "BIT_OR", ast.BitXor: "BIT_XOR",
       ast.LShift: "SHIFT_LEFT", ast.RShift: "SHIFT_RIGHT"}
CMP = {ast.Eq: "CMP_EQ", ast.NotEq: "CMP_NE", ast.Lt: "CMP_LT", ast.LtE: "CMP_LE", ast.Gt: "CMP_GT",
       ast.GtE: "CMP_GE"}
SYMPY_ALIASES = {"Abs": "abs", "ceiling": "ceil", "Max": "max", "Min": "min", "Mod": "mod", "ln": "log",
                 "binomial": "comb", "re": "real_part"}
FUNCS = {
    "abs": abs, "sqrt": math.sqrt, "exp": math.exp, "log": math.log, "log2": math.log2, "log10": math.log10,
    "sin": math.sin, "cos": math.cos, "tan": math.tan, "asin": math.asin, "acos": math.acos, "atan": math.atan,
    "atan2": math.atan2, "sinh": math.sinh, "cosh": math.cosh, "tanh": math.tanh, "asinh": math.asinh,
    "acosh": math.acosh, "atanh": math.atanh, "floor": math.floor, "ceil": math.ceil, "factorial": math.factorial,
    "comb": math.comb, "gcd": math.gcd, "lcm": math.lcm, "max": max, "min": min, "mod": lambda a, b: a % b,
    "sec": lambda x: 1 / math.cos(x), "csc": lambda x: 1 / math.sin(x), "cot": lambda x: 1 / math.tan(x),
    "isqrt": math.isqrt, "hypot": math.hypot, "erf": math.erf, "gamma": math.gamma,
    "Ne": lambda a, b: a != b, "Eq": lambda a, b: a == b,
}
CONSTS = {"pi": math.pi, "E": math.e, "e": math.e, "tau": math.tau, "oo": math.inf}


class ParseError(ValueError):
    pass


class UnknownName(ValueError):
    pass


def parse(text: str, pattern_vars: list[str] | None = None) -> list | str:
    """Parse a Python/sympy-style expression. Names in ``pattern_vars`` become "?name" pattern variables."""
    try:
        tree = ast.parse(text.strip(), mode="eval")  # '^' stays XOR (Python syntax); sympy prints powers as '**'
    except SyntaxError as exc:
        raise ParseError(f"cannot parse {text!r}: {exc.msg}") from exc
    pv = set(pattern_vars or [])
    return _conv(tree.body, pv)


def _conv(n, pv):
    if isinstance(n, ast.Constant):
        v = n.value
        if isinstance(v, bool):
            return ["bool", v]
        if isinstance(v, int):
            return ["int", v]
        if isinstance(v, float):
            return ["float", v]
        raise ParseError(f"constant {v!r}")
    if isinstance(n, ast.Name):
        if n.id in pv:
            return f"?{n.id}"
        if n.id in CONSTS:
            return ["const", n.id]
        return ["var", n.id]
    if isinstance(n, ast.BinOp):
        op = BIN.get(type(n.op))
        if not op:
            raise ParseError(f"operator {type(n.op).__name__}")
        return [op, _conv(n.left, pv), _conv(n.right, pv)]
    if isinstance(n, ast.UnaryOp):
        x = _conv(n.operand, pv)
        if isinstance(n.op, ast.USub):
            if isinstance(x, list) and x[0] in ("int", "float"):
                return [x[0], -x[1]]
            return ["NEG", x]
        if isinstance(n.op, ast.UAdd):
            return x
        if isinstance(n.op, ast.Invert):
            return ["BIT_NOT", x]
        if isinstance(n.op, ast.Not):
            return ["NOT", x]
    if isinstance(n, ast.Compare) and len(n.ops) == 1:
        op = CMP.get(type(n.ops[0]))
        if not op:   # in, not in, is, is not: no op card (a ParseError, so callers fall back instead of crashing)
            raise ParseError(f"comparison {type(n.ops[0]).__name__}")
        return [op, _conv(n.left, pv), _conv(n.comparators[0], pv)]
    if isinstance(n, ast.BoolOp):
        head = "AND" if isinstance(n.op, ast.And) else "OR"
        e = _conv(n.values[0], pv)
        for v in n.values[1:]:
            e = [head, e, _conv(v, pv)]
        return e
    if isinstance(n, ast.IfExp):
        return ["IF_EXPR", _conv(n.test, pv), _conv(n.body, pv), _conv(n.orelse, pv)]
    if isinstance(n, ast.Call) and not n.keywords:
        name = ast.unparse(n.func)
        name = name.split(".")[-1] if name.startswith(("math.", "sympy.", "sp.")) else name
        name = SYMPY_ALIASES.get(name, name)
        args = [_conv(a, pv) for a in n.args]
        if name == "pow" and len(args) == 3:
            return ["POW_MOD", *args]
        if name in ("pow", "Pow") and len(args) == 2:
            return ["POW", *args]
        if name == "abs" and len(args) == 1:
            return ["ABS", *args]
        if name in ("min", "max") and len(args) == 2:
            return [name.upper(), *args]
        if name == "Rational" and len(args) == 2:
            return ["DIV", *args]
        if name in ("Integer", "Float", "S", "sympify") and len(args) == 1:
            return args[0]
        return ["FN", name, *args]
    raise ParseError(f"unsupported syntax {type(n).__name__}")


def variables(tree) -> set[str]:
    out: set[str] = set()
    if isinstance(tree, list):
        if tree[0] == "var":
            out.add(tree[1])
        else:
            for a in tree[(2 if tree[0] == "FN" else 1):]:
                out |= variables(a)
    return out


def size(tree) -> int:
    if isinstance(tree, list) and tree and tree[0] not in ("var", "int", "float", "bool", "const"):
        return 1 + sum(size(a) for a in tree[(2 if tree[0] == "FN" else 1):])
    return 1


class EvalError(ArithmeticError):
    pass


def evaluate(tree, env: dict, mode: str = "int"):
    """Evaluate an op tree. Raises EvalError (or ArithmeticError/ValueError) outside the domain."""
    if isinstance(tree, str):
        raise EvalError(f"unbound pattern variable {tree}")
    head = tree[0]
    if head == "var":
        if tree[1] not in env:
            raise UnknownName(tree[1])
        return env[tree[1]]
    if head in ("int", "bool"):
        return tree[1]
    if head == "float":
        v = tree[1]
        return Fraction(v) if mode in ("int", "fraction") and float(v).is_integer() else v
    if head == "const":
        return CONSTS[tree[1]]
    args = [evaluate(a, env, mode) for a in tree[(2 if head == "FN" else 1):]]
    if head == "FN":
        fn = FUNCS.get(tree[1])
        if fn is None:
            raise UnknownName(f"function {tree[1]!r}")
        if mode in ("int", "fraction") and tree[1] not in ("abs", "max", "min", "gcd", "lcm", "factorial", "comb",
                                                           "mod", "floor", "ceil", "isqrt", "Ne", "Eq"):
            args = [float(a) for a in args]
        return fn(*args)
    a = args[0] if args else None
    b = args[1] if len(args) > 1 else None
    if head == "ADD":
        return a + b
    if head == "SUB":
        return a - b
    if head == "MUL":
        return a * b
    if head == "DIV":
        if mode in ("int", "fraction") and not isinstance(a, float) and not isinstance(b, float):
            return Fraction(a) / Fraction(b)
        return a / b
    if head == "FLOORDIV":
        return a // b
    if head == "MOD":
        return a % b
    if head == "POW":
        if isinstance(b, Fraction) and b.denominator == 1:
            b = int(b)
        if isinstance(a, (int, Fraction)) and isinstance(b, int):
            if abs(b) > 4096:
                raise EvalError("exponent too large")
            return Fraction(a) ** b if b < 0 or isinstance(a, Fraction) else a ** b
        return float(a) ** float(b)
    if head == "NEG":
        return -a
    if head == "ABS":
        return abs(a)
    if head in ("MIN", "MAX"):
        return min(a, b) if head == "MIN" else max(a, b)
    if head == "POW_MOD":
        return pow(int(a), int(b), int(args[2]))
    if head in ("BIT_AND", "BIT_OR", "BIT_XOR") and all(isinstance(x, bool) for x in args):
        return {"BIT_AND": a and b, "BIT_OR": a or b, "BIT_XOR": a != b}[head]  # sympy-style & | on predicates
    if head in ("BIT_AND", "BIT_OR", "BIT_XOR", "SHIFT_LEFT", "SHIFT_RIGHT", "BIT_NOT"):
        ints = [int(x) if isinstance(x, Fraction) and x.denominator == 1 else x for x in args]
        if not all(isinstance(x, int) for x in ints):
            raise EvalError(f"{head} on non-integers")
        a, b = ints[0], (ints[1] if len(ints) > 1 else None)
        if head in ("SHIFT_LEFT", "SHIFT_RIGHT") and (b < 0 or b > 4096):
            raise EvalError("shift out of range")
        return {"BIT_AND": lambda: a & b, "BIT_OR": lambda: a | b, "BIT_XOR": lambda: a ^ b,
                "SHIFT_LEFT": lambda: a << b, "SHIFT_RIGHT": lambda: a >> b, "BIT_NOT": lambda: ~a}[head]()
    if head in ("CMP_EQ", "CMP_NE", "CMP_LT", "CMP_LE", "CMP_GT", "CMP_GE"):
        return {"CMP_EQ": a == b, "CMP_NE": a != b, "CMP_LT": a < b, "CMP_LE": a <= b, "CMP_GT": a > b,
                "CMP_GE": a >= b}[head]
    if head == "AND":
        return bool(a) and bool(b)
    if head == "OR":
        return bool(a) or bool(b)
    if head == "NOT":
        return not a
    if head == "IF_EXPR":
        return args[1] if a else args[2]
    raise EvalError(f"no evaluator for {head}")


def to_text(tree) -> str:
    from .ir import to_python_text
    if isinstance(tree, list) and tree and tree[0] == "FN":
        return f"{tree[1]}({', '.join(to_text(a) for a in tree[2:])})"
    if isinstance(tree, list) and tree and tree[0] == "const":
        return tree[1]
    if isinstance(tree, list) and tree and tree[0] not in ("var", "int", "float", "bool"):
        head = tree[0]
        inner = [to_text(a) for a in tree[1:]]
        sym = {"ADD": "+", "SUB": "-", "MUL": "*", "DIV": "/", "FLOORDIV": "//", "MOD": "%", "POW": "**",
               "BIT_AND": "&", "BIT_OR": "|", "BIT_XOR": "^", "SHIFT_LEFT": "<<", "SHIFT_RIGHT": ">>"}.get(head)
        if sym and len(inner) == 2:
            return f"({inner[0]} {sym} {inner[1]})"
        if head == "NEG":
            return f"(-{inner[0]})"
        return f"{head}({', '.join(inner)})"
    if isinstance(tree, str):
        return tree
    return to_python_text(tree)
