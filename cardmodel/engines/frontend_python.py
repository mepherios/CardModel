"""frontend_python — lift Python functions into the card IR (observe -> cards).

Supported subset (everything else is reported, never pasted through):

  def f(a: int, b: float = 1.0, ...) -> int  params int/float/bool; numeric defaults
  @functools.cache / @lru_cache(...)          pure memoization, dropped
  module constants  P = 2**61 - 1             inlined (assigned once, never `global`)
  x = e · x += e · a, b = b, a % b            locals keep one type
  if/elif/else · while · for i in range(a[, b[, step]]) with a constant step
  return e · break · continue · pass · docstrings
  + - * / // % ** (constant exponent >= 0) & | ^ << >> ~ unary - not and or
  == != < <= > >= (chains) · x if c else y
  abs min max (2 args) pow(a, b[, m]) float(x) int(x) math.gcd(a, b)
  math.sqrt exp log(x) sin cos tan asin acos atan atan2 sinh cosh tanh fabs
  floor ceil trunc (-> int) fmod copysign isnan · math.pi math.e math.tau
  calls to other lifted functions of the same module, positional or by keyword,
  missing arguments filled from numeric defaults (L45: the callee must lift)

Each unsupported construct is reported with its line, so a translation gap
is a precise list, not a percentage guess.

Honest limits (L1): no strings, lists, dicts, classes, exceptions, globals,
closures or side effects; ``int`` follows Python's unbounded semantics, so
fixed-width targets agree only inside the declared input domain.
"""
from __future__ import annotations

import ast
import math
from dataclasses import dataclass, field

from .ir import OpSpec

BINOPS = {ast.Add: "ADD", ast.Sub: "SUB", ast.Mult: "MUL", ast.Div: "DIV", ast.FloorDiv: "FLOORDIV",
          ast.Mod: "MOD", ast.Pow: "POW", ast.BitAnd: "BIT_AND", ast.BitOr: "BIT_OR", ast.BitXor: "BIT_XOR",
          ast.LShift: "SHIFT_LEFT", ast.RShift: "SHIFT_RIGHT"}
CMPOPS = {ast.Eq: "CMP_EQ", ast.NotEq: "CMP_NE", ast.Lt: "CMP_LT", ast.LtE: "CMP_LE", ast.Gt: "CMP_GT",
          ast.GtE: "CMP_GE"}
CALLS = {"abs": ("ABS", 1), "min": ("MIN", 2), "max": ("MAX", 2), "float": ("TO_FLOAT", 1),
         "int": ("TRUNC_INT", 1), "math.gcd": ("GCD", 2), "gcd": ("GCD", 2)}
# math.f(x) -> op card; every one takes and returns float (an int argument is promoted, as Python does)
MATH_FLOAT = {"sqrt": "FSQRT", "exp": "EXP", "log": "LOG", "sin": "SIN", "cos": "COS", "tan": "TAN",
              "asin": "ASIN", "acos": "ACOS", "atan": "ATAN", "sinh": "SINH", "cosh": "COSH", "tanh": "TANH",
              "fabs": "ABS", "atan2": "ATAN2", "fmod": "FMOD", "copysign": "COPYSIGN", "isnan": "ISNAN"}
MATH_TO_INT = {"floor": "FLOOR", "ceil": "CEIL", "trunc": "TRUNC"}   # float -> int in Python 3
MATH_CONSTS = {"pi": math.pi, "e": math.e, "tau": math.tau}
PURE_DECORATORS = {"cache", "lru_cache", "functools.cache", "functools.lru_cache"}


class Unsupported(Exception):
    def __init__(self, what: str, node: ast.AST | None = None):
        self.what = what
        self.line = getattr(node, "lineno", None)
        super().__init__(f"line {self.line}: {what}" if self.line else what)


@dataclass
class Lifted:
    name: str
    ok: bool
    ir: dict | None = None
    source: str = ""
    reasons: list[str] = field(default_factory=list)
    inferred_types: bool = False
    lineno: int = 0
    preamble: str = ""     # what the source needs around it to run alone: module constants, functools


def _ann_type(node) -> str | None:
    if node is None:
        return None
    if isinstance(node, ast.Name) and node.id in ("int", "float", "bool"):
        return node.id
    if isinstance(node, ast.Constant) and node.value in ("int", "float", "bool"):
        return node.value
    raise Unsupported(f"type annotation {ast.unparse(node)!r} (only int/float/bool)", node)


def _literal(v):
    if isinstance(v, bool):
        return ["bool", v], "bool"
    if isinstance(v, int):
        return ["int", v], "int"
    return ["float", float(v)], "float"


def _lit_type(v) -> str | None:
    return None if v is None else _literal(v)[1]


def _decorator_name(dec) -> str:
    return ast.unparse(dec.func if isinstance(dec, ast.Call) else dec)


def _const_eval(node, consts: dict):
    """The value of a numeric constant expression (literals, earlier constants, math.pi, arithmetic), or None."""
    ops = {ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b, ast.Mult: lambda a, b: a * b,
           ast.Div: lambda a, b: a / b, ast.FloorDiv: lambda a, b: a // b, ast.Mod: lambda a, b: a % b,
           ast.Pow: lambda a, b: a ** b, ast.LShift: lambda a, b: a << b, ast.RShift: lambda a, b: a >> b,
           ast.BitAnd: lambda a, b: a & b, ast.BitOr: lambda a, b: a | b, ast.BitXor: lambda a, b: a ^ b}
    if isinstance(node, ast.Constant) and isinstance(node.value, (bool, int, float)):
        return node.value
    if isinstance(node, ast.Name):
        return consts.get(node.id)
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "math":
        return MATH_CONSTS.get(node.attr)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd, ast.Invert)):
        v = _const_eval(node.operand, consts)
        if v is None or isinstance(v, bool) or (isinstance(node.op, ast.Invert) and not isinstance(v, int)):
            return None
        return -v if isinstance(node.op, ast.USub) else (~v if isinstance(node.op, ast.Invert) else v)
    if isinstance(node, ast.BinOp) and type(node.op) in ops:
        a, b = _const_eval(node.left, consts), _const_eval(node.right, consts)
        if a is None or b is None or isinstance(a, bool) or isinstance(b, bool):
            return None
        if isinstance(node.op, (ast.Pow, ast.LShift)) and isinstance(b, int) and abs(b) > 4096:
            return None
        try:
            v = ops[type(node.op)](a, b)
        except (ArithmeticError, ValueError, TypeError):
            return None
        return v if isinstance(v, (int, float)) and not isinstance(v, complex) else None
    return None


def _default_value(node, consts: dict):
    v = _const_eval(node, consts)
    if isinstance(v, float) and not math.isfinite(v):
        return None
    return v


def module_constants(tree: ast.Module) -> dict:
    """Top-level names bound exactly once to a finite numeric constant and never declared ``global``."""
    counts: dict[str, int] = {}
    for n in tree.body:
        targets = n.targets if isinstance(n, ast.Assign) else [n.target] if isinstance(n, (ast.AnnAssign, ast.AugAssign)) else []
        for t in targets:
            for x in ast.walk(t):
                if isinstance(x, ast.Name):
                    counts[x.id] = counts.get(x.id, 0) + 1
        if isinstance(n, (ast.For, ast.With, ast.Import, ast.ImportFrom, ast.FunctionDef, ast.ClassDef)):
            for x in ast.walk(n) if isinstance(n, (ast.For, ast.With)) else []:
                if isinstance(x, ast.Name) and isinstance(x.ctx, ast.Store):
                    counts[x.id] = counts.get(x.id, 0) + 2
    declared_global = {name for x in ast.walk(tree) if isinstance(x, ast.Global) for name in x.names}
    consts: dict = {}
    for n in tree.body:
        if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name):
            name, value = n.targets[0].id, n.value
        elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name) and n.value is not None:
            name, value = n.target.id, n.value
        else:
            continue
        if counts.get(name) != 1 or name in declared_global:
            continue
        v = _default_value(value, consts)
        if v is not None:
            consts[name] = v
    return consts


class _FnLifter:
    def __init__(self, fdef: ast.FunctionDef, ops: dict[str, OpSpec], sigs: dict[str, dict],
                 param_hint: dict[str, str] | None, consts: dict | None = None,
                 externs: dict[str, dict] | None = None):
        self.f = fdef
        self.consts = consts or {}
        self.ops = ops
        self.sigs = sigs                      # name -> {"params": [types], "returns": type|None}
        self.externs = externs or {}          # call text -> {"qual", "params", "returns"} (other files, methods)
        self.hint = param_hint or {}
        self.env: dict[str, str] = {}
        self.locals: dict[str, str] = {}
        self.tmp = 0
        self.inferred = False
        self.return_types: set[str] = set()

    def fresh(self, base: str, typ: str) -> str:
        self.tmp += 1
        name = f"cm_{base}{self.tmp}"
        self.locals[name] = typ
        self.env[name] = typ
        return name

    def lift(self) -> dict:
        f = self.f
        a = f.args
        if a.vararg or a.kwarg or a.kwonlyargs or a.kw_defaults or a.posonlyargs:
            raise Unsupported("varargs or keyword-only parameters", f)
        defaults = dict(zip([x.arg for x in a.args[len(a.args) - len(a.defaults):]], a.defaults))
        for d in defaults.values():
            if _default_value(d, self.consts) is None:
                raise Unsupported(f"default {ast.unparse(d)!r} (only numeric constants)", d)
        for dec in f.decorator_list:
            if _decorator_name(dec) not in PURE_DECORATORS:
                raise Unsupported(f"decorator @{ast.unparse(dec)}", f)
        if isinstance(f, ast.AsyncFunctionDef):
            raise Unsupported("async def", f)
        params = []
        for arg in a.args:
            t = _ann_type(arg.annotation) or self.hint.get(arg.arg)
            if t is None and arg.arg in defaults:
                t = _lit_type(_default_value(defaults[arg.arg], self.consts))
            if t is None:
                t = "int"
                self.inferred = True
            params.append({"name": arg.arg, "type": t})
            self.env[arg.arg] = t
        declared_ret = _ann_type(f.returns)
        body = self.block(f.body)
        if not body or body[-1]["k"] != "return":
            if not _always_returns(body):
                raise Unsupported("a path can reach the end of the function without return", f)
        rts = self.return_types
        if declared_ret:
            ret = declared_ret
            if rts - {declared_ret}:
                raise Unsupported(f"returns {sorted(rts)} but annotated {declared_ret}", f)
        elif len(rts) == 1:
            ret = next(iter(rts))
        else:
            raise Unsupported(f"return types disagree: {sorted(rts)}", f)
        return {"name": f.name, "params": params, "returns": ret, "locals": dict(self.locals), "body": body}

    # -- statements ------------------------------------------------------------
    def block(self, stmts) -> list[dict]:
        out: list[dict] = []
        for i, s in enumerate(stmts):
            if i == 0 and isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant) and isinstance(s.value.value, str):
                continue  # docstring
            out.extend(self.stmt(s))
        return out

    def assign(self, name: str, expr, typ: str, node) -> dict:
        prev = self.env.get(name)
        if prev is not None and prev != typ:
            raise Unsupported(f"variable {name!r} changes type {prev} -> {typ}", node)
        if prev is None:
            self.locals[name] = typ
            self.env[name] = typ
        return {"k": "assign", "target": name, "value": expr}

    def stmt(self, s) -> list[dict]:
        if isinstance(s, ast.Return):
            if s.value is None:
                raise Unsupported("return without a value", s)
            e, t = self.expr(s.value)
            self.return_types.add(t)
            return [{"k": "return", "value": e}]
        if isinstance(s, ast.Pass):
            return []
        if isinstance(s, ast.Assign):
            if len(s.targets) != 1:
                raise Unsupported("chained assignment", s)
            tgt = s.targets[0]
            if isinstance(tgt, ast.Name):
                e, t = self.expr(s.value)
                return [self.assign(tgt.id, e, t, s)]
            if isinstance(tgt, ast.Tuple) and isinstance(s.value, ast.Tuple) and len(tgt.elts) == len(s.value.elts) \
                    and all(isinstance(x, ast.Name) for x in tgt.elts):
                vals = [self.expr(v) for v in s.value.elts]
                out, temps = [], []
                for (e, t) in vals:
                    tmp = self.fresh("t", t)
                    out.append({"k": "assign", "target": tmp, "value": e})
                    temps.append((tmp, t))
                for x, (tmp, t) in zip(tgt.elts, temps):
                    out.append(self.assign(x.id, ["var", tmp], t, s))
                return out
            raise Unsupported(f"assignment target {ast.unparse(tgt)!r}", s)
        if isinstance(s, ast.AnnAssign):
            if not isinstance(s.target, ast.Name) or s.value is None:
                raise Unsupported("annotated assignment without a simple target and value", s)
            want = _ann_type(s.annotation)
            e, t = self.expr(s.value)
            if t != want:
                if t == "int" and want == "float":
                    e, t = ["TO_FLOAT", e], "float"
                else:
                    raise Unsupported(f"{s.target.id}: {want} annotation but value is {t}", s)
            return [self.assign(s.target.id, e, t, s)]
        if isinstance(s, ast.AugAssign):
            if not isinstance(s.target, ast.Name):
                raise Unsupported(f"augmented assignment to {ast.unparse(s.target)!r}", s)
            e, t = self.binop(type(s.op), ["var", s.target.id], self.var_type(s.target.id, s), s.value, s)
            return [self.assign(s.target.id, e, t, s)]
        if isinstance(s, ast.If):
            c = self.cond(s.test)
            return [{"k": "if", "cond": c, "then": self.block(s.body), "else": self.block(s.orelse)}]
        if isinstance(s, ast.While):
            if s.orelse:
                raise Unsupported("while ... else", s)
            return [{"k": "while", "cond": self.cond(s.test), "body": self.block(s.body)}]
        if isinstance(s, ast.For):
            return [self.for_range(s)]
        if isinstance(s, ast.Break):
            return [{"k": "break"}]
        if isinstance(s, ast.Continue):
            return [{"k": "continue"}]
        raise Unsupported(f"statement {type(s).__name__}", s)

    def for_range(self, s: ast.For) -> dict:
        if s.orelse:
            raise Unsupported("for ... else", s)
        if not isinstance(s.target, ast.Name):
            raise Unsupported("for target is not a simple name", s)
        it = s.iter
        if not (isinstance(it, ast.Call) and isinstance(it.func, ast.Name) and it.func.id == "range"
                and 1 <= len(it.args) <= 3 and not it.keywords):
            raise Unsupported(f"for over {ast.unparse(it)!r} (only range(...))", s)
        args = [self.expr(a) for a in it.args]
        if any(t != "int" for _, t in args):
            raise Unsupported("range() arguments must be int", s)
        if len(args) == 1:
            start, stop, step = ["int", 0], args[0][0], ["int", 1]
        elif len(args) == 2:
            start, stop, step = args[0][0], args[1][0], ["int", 1]
        else:
            start, stop, step = args[0][0], args[1][0], args[2][0]
            if step[0] != "int" and not (step[0] == "NEG" and step[1][0] == "int"):
                raise Unsupported("range() step must be an integer literal", s)
            if step[0] == "NEG":
                step = ["int", -step[1][1]]
            if step[1] == 0:
                raise Unsupported("range() step 0", s)
        var = s.target.id
        if self.env.get(var, "int") != "int":
            raise Unsupported(f"loop variable {var!r} is not int", s)
        if var not in self.env:
            self.locals[var] = "int"
            self.env[var] = "int"
        it_name = self.fresh("it", "int")
        stop_name = self.fresh("stop", "int")
        return {"k": "for_range", "var": var, "start": start, "stop": stop, "step": step,
                "counter": it_name, "stop_var": stop_name, "body": self.block(s.body)}

    # -- expressions -------------------------------------------------------------
    def var_type(self, name: str, node) -> str:
        t = self.env.get(name)
        if t is None:
            raise Unsupported(f"name {name!r} is not a parameter or an assigned local", node)
        return t

    def cond(self, node):
        e, t = self.expr(node)
        if t != "bool":
            raise Unsupported(f"condition of type {t} (truthiness of numbers is not lifted; compare explicitly)", node)
        return e

    def spec(self, op: str, node) -> OpSpec:
        s = self.ops.get(op)
        if s is None:
            raise Unsupported(f"op card {op!r} is missing (add cards/op/{op})", node)
        return s

    def apply(self, op: str, args: list[tuple], node):
        spec = self.spec(op, node)
        types = [t for _, t in args]
        rt = spec.result_type(types)
        exprs = [e for e, _ in args]
        if rt is None:
            prom = spec.promoted(types)
            if prom is None:
                raise Unsupported(f"{op} on ({', '.join(types)})", node)
            exprs = [["TO_FLOAT", e] if t == "int" and p == "float" else e for (e, t), p in zip(args, prom)]
            rt = spec.result_type(prom)
        return [op, *exprs], rt

    def binop(self, optype, left_ir, left_t, right_node, node):
        op = BINOPS.get(optype)
        if op is None:
            raise Unsupported(f"operator {optype.__name__}", node)
        r, rt = self.expr(right_node)
        if "bool" in (left_t, rt):
            raise Unsupported(f"arithmetic on bool ({op})", node)
        if op == "DIV" and left_t == "int" and rt == "int":
            return ["DIV", ["TO_FLOAT", left_ir], ["TO_FLOAT", r]], "float"
        if op == "POW" and left_t == "int" and rt == "int":
            if not (r[0] == "int" and r[1] >= 0):
                raise Unsupported("int ** int needs a non-negative integer literal exponent", node)
        return self.apply(op, [(left_ir, left_t), (r, rt)], node)

    def expr(self, n):
        if isinstance(n, ast.Constant):
            v = n.value
            if isinstance(v, bool):
                return ["bool", v], "bool"
            if isinstance(v, int):
                return ["int", v], "int"
            if isinstance(v, float):
                return ["float", v], "float"
            raise Unsupported(f"constant {v!r}", n)
        if isinstance(n, ast.Name):
            if n.id not in self.env and n.id in self.consts:
                return _literal(self.consts[n.id])
            return ["var", n.id], self.var_type(n.id, n)
        if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == "math" \
                and n.attr in MATH_CONSTS:
            return _literal(MATH_CONSTS[n.attr])
        if isinstance(n, ast.BinOp):
            l, lt = self.expr(n.left)
            return self.binop(type(n.op), l, lt, n.right, n)
        if isinstance(n, ast.UnaryOp):
            e, t = self.expr(n.operand)
            if isinstance(n.op, ast.UAdd):
                return e, t
            if isinstance(n.op, ast.USub):
                if e[0] in ("int", "float") and not isinstance(e[1], bool):
                    return [e[0], -e[1]], t
                return self.apply("NEG", [(e, t)], n)
            if isinstance(n.op, ast.Not):
                if t != "bool":
                    raise Unsupported("`not` on a non-bool", n)
                return ["NOT", e], "bool"
            if isinstance(n.op, ast.Invert):
                return self.apply("BIT_NOT", [(e, t)], n)
        if isinstance(n, ast.BoolOp):
            vals = [self.expr(v) for v in n.values]
            if any(t != "bool" for _, t in vals):
                raise Unsupported("and/or on non-bool operands", n)
            head = "AND" if isinstance(n.op, ast.And) else "OR"
            e = vals[0][0]
            for v, _ in vals[1:]:
                e = [head, e, v]
            return e, "bool"
        if isinstance(n, ast.Compare):
            parts = []
            left = self.expr(n.left)
            for op, comp in zip(n.ops, n.comparators):
                name = CMPOPS.get(type(op))
                if name is None:
                    raise Unsupported(f"comparison {type(op).__name__}", n)
                right = self.expr(comp)
                e, _ = self.apply(name, [left, right], n)
                parts.append(e)
                left = right
            e = parts[0]
            for p in parts[1:]:
                e = ["AND", e, p]
            return e, "bool"
        if isinstance(n, ast.IfExp):
            c = self.cond(n.test)
            a, at = self.expr(n.body)
            b, bt = self.expr(n.orelse)
            if at != bt:
                if {at, bt} == {"int", "float"}:
                    a = ["TO_FLOAT", a] if at == "int" else a
                    b = ["TO_FLOAT", b] if bt == "int" else b
                    at = bt = "float"
                else:
                    raise Unsupported(f"conditional expression branches {at} vs {bt}", n)
            return ["IF_EXPR", c, a, b], at
        if isinstance(n, ast.Call):
            return self.call(n)
        raise Unsupported(f"expression {type(n).__name__}", n)

    def call(self, n: ast.Call):
        fname = ast.unparse(n.func)
        if isinstance(n.func, ast.Name) and n.func.id in self.sigs and n.func.id not in self.env:
            return self.call_lifted(n)
        if n.keywords:
            raise Unsupported("keyword arguments in call", n)
        if any(isinstance(a, ast.Starred) for a in n.args):
            raise Unsupported("*args in call", n)
        args = [self.expr(a) for a in n.args]
        short = fname[5:] if fname.startswith("math.") else None
        if short in MATH_FLOAT or short in MATH_TO_INT:
            op = MATH_FLOAT.get(short) or MATH_TO_INT[short]
            arity = self.spec(op, n).arity
            if len(args) != arity:
                raise Unsupported(f"{fname}() with {len(args)} arguments", n)
            if short in MATH_TO_INT and args[0][1] == "int":
                return args[0]
            e, t = self.apply(op, [(["TO_FLOAT", x] if xt == "int" else x, "float" if xt == "int" else xt)
                                   for x, xt in args], n)
            if short in MATH_TO_INT:
                return ["TRUNC_INT", e], "int"
            return e, t
        if fname == "pow":
            if len(args) == 3:
                return self.apply("POW_MOD", args, n)
            if len(args) == 2:
                if args[0][1] == "int" and not (args[1][0][0] == "int" and args[1][0][1] >= 0):
                    raise Unsupported("pow(int, int) needs a non-negative integer literal exponent", n)
                return self.apply("POW", args, n)
        if fname in CALLS:
            op, arity = CALLS[fname]
            if len(args) != arity:
                raise Unsupported(f"{fname}() with {len(args)} arguments", n)
            if op == "TO_FLOAT" and args[0][1] == "float":
                return args[0]
            if op == "TRUNC_INT" and args[0][1] == "int":
                return args[0]
            return self.apply(op, args, n)
        ext = self.externs.get(fname)
        if ext is not None:                   # a function of another module or a method: resolved by lift_project
            if len(args) != len(ext["params"]):
                raise Unsupported(f"{fname}() arity mismatch", n)
            fixed = []
            for (e, t), want in zip(args, ext["params"]):
                if t != want:
                    if t == "int" and want == "float":
                        e = ["TO_FLOAT", e]
                    else:
                        raise Unsupported(f"{fname}() argument {t} where {want} expected", n)
                fixed.append(e)
            if ext.get("returns") is None:
                self.inferred = True
            return ["CALL", ext["qual"], *fixed], ext.get("returns") or "int"
        raise Unsupported(f"call to {fname}() (no op card or lifted function)", n)

    def call_lifted(self, n: ast.Call):
        """A call to another function of the module: keywords bound by name, missing ones from defaults."""
        fname = n.func.id
        sig = self.sigs[fname]
        names = sig.get("names") or []
        if any(isinstance(a, ast.Starred) for a in n.args) or any(k.arg is None for k in n.keywords):
            raise Unsupported(f"{fname}() called with * or ** arguments", n)
        slots: list = list(n.args) + [None] * (len(sig["params"]) - len(n.args))
        if len(slots) != len(sig["params"]):
            raise Unsupported(f"{fname}() arity mismatch", n)
        for k in n.keywords:
            if k.arg not in names or slots[names.index(k.arg)] is not None:
                raise Unsupported(f"{fname}() keyword {k.arg!r} does not match a free parameter", n)
            slots[names.index(k.arg)] = k.value
        args = []
        for pname, node in zip(names, slots):
            if node is None:
                if pname not in sig.get("defaults", {}):
                    raise Unsupported(f"{fname}() arity mismatch (no value for {pname!r})", n)
                args.append(_literal(sig["defaults"][pname]))
            else:
                args.append(self.expr(node))
        if True:
            fixed = []
            for (e, t), want in zip(args, sig["params"]):
                if t != want:
                    if t == "int" and want == "float":
                        e = ["TO_FLOAT", e]
                    else:
                        raise Unsupported(f"{fname}() argument {t} where {want} expected", n)
                fixed.append(e)
            ret = sig.get("returns") or "int"
            if sig.get("returns") is None:
                self.inferred = True
            return ["CALL", n.func.id, *fixed], ret


def _always_returns(body: list[dict]) -> bool:
    if not body:
        return False
    last = body[-1]
    if last["k"] == "return":
        return True
    if last["k"] == "if":
        return _always_returns(last["then"]) and _always_returns(last["else"])
    return False


def lift_source(source: str, ops: dict[str, OpSpec], only: list[str] | None = None,
                param_hints: dict[str, dict[str, str]] | None = None) -> list[Lifted]:
    """Lift every top-level function in ``source``. Calls between lifted functions resolve;
    a function that calls a non-liftable one fails with that reason (closure, L45)."""
    tree = ast.parse(source)
    fdefs = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    return lift_defs(fdefs, source.splitlines(), ops, only, param_hints, consts=module_constants(tree))


def lift_defs(fdefs: list, lines: list[str], ops: dict[str, OpSpec], only: list[str] | None = None,
              param_hints: dict[str, dict[str, str]] | None = None, externs: dict[str, dict] | None = None,
              close: bool = True, consts: dict | None = None) -> list[Lifted]:
    """Lift these function definitions (top-level functions, or methods prepared by lift_project) of one file.
    ``externs`` resolves calls to functions defined elsewhere (their CALL names the qualified name); the closure
    treats them as lifted, and lift_project re-checks them across files. ``consts`` are the module's constants
    (module_constants)."""
    consts = consts or {}
    sigs: dict[str, dict] = {}
    for f in fdefs:
        try:
            a = f.args
            defaults = {x.arg: _default_value(d, consts)
                        for x, d in zip(a.args[len(a.args) - len(a.defaults):], a.defaults)}
            ptypes = [(_ann_type(x.annotation) or (param_hints or {}).get(f.name, {}).get(x.arg)
                       or _lit_type(defaults.get(x.arg)) or "int") for x in a.args]
            sigs[f.name] = {"params": ptypes, "returns": _ann_type(f.returns), "names": [x.arg for x in a.args],
                            "defaults": {k: v for k, v in defaults.items() if v is not None}}
        except Unsupported:
            continue
    results: dict[str, Lifted] = {}
    preamble = "import functools\nfrom functools import cache, lru_cache\n" + \
        "".join(f"{k} = {v!r}\n" for k, v in consts.items())
    for f in fdefs:
        src = "\n".join(lines[f.lineno - 1 - len(f.decorator_list): f.end_lineno])
        lifter = _FnLifter(f, ops, sigs, (param_hints or {}).get(f.name), consts, externs)
        try:
            ir = lifter.lift()
            sigs[f.name]["returns"] = ir["returns"]
            results[f.name] = Lifted(f.name, True, ir, src, [], lifter.inferred, f.lineno, preamble)
        except Unsupported as exc:
            results[f.name] = Lifted(f.name, False, None, src, [str(exc)], lifter.inferred, f.lineno, preamble)
    if close:
        external = {e["qual"] for e in (externs or {}).values()}
        close_calls(results, lambda c: c in external)
    return [lf for lf in results.values() if not only or lf.name in only]


def callees_of(ir: dict) -> set[str]:
    return {e[1] for s in _stmts(ir["body"]) for e in _exprs_of(s) if e[0] == "CALL"}


def close_calls(results: dict, known_ok=lambda name: False) -> None:
    """A lifted function that calls a failed or missing one fails too (L45), linear in calls: one pass builds the
    reverse call graph, then a worklist spreads each failure to its callers once (the old fixed-point loop re-scanned
    every function per pass: quadratic in the depth of a call chain)."""
    callers: dict[str, list[str]] = {}
    work: list[str] = []
    for name, lf in results.items():
        if not lf.ok:
            work.append(name)
            continue
        missing = []
        for c in callees_of(lf.ir):
            if c in results:
                callers.setdefault(c, []).append(name)
            elif not known_ok(c):
                missing.append(c)
        if missing:
            lf.ok = False
            lf.reasons.append(f"calls {', '.join(sorted(missing))} which did not lift")
            work.append(name)
    while work:
        bad = work.pop()
        for name in callers.get(bad, ()):
            lf = results[name]
            if lf.ok:
                lf.ok = False
                lf.reasons.append(f"calls {bad} which did not lift")
                work.append(name)


def module_for(name: str, lifted: list[Lifted]) -> dict:
    """The IR module containing ``name`` and every function it (transitively) calls."""
    by = {lf.name: lf for lf in lifted if lf.ok}
    need, order = [name], []
    while need:
        n = need.pop()
        if n in order:
            continue
        order.append(n)
        for s in _stmts(by[n].ir["body"]):
            for e in _exprs_of(s):
                if e[0] == "CALL" and e[1] not in order:
                    need.append(e[1])
    return {"entry": name, "functions": [by[n].ir for n in order]}


def _stmts(body):
    for s in body:
        yield s
        for key in ("then", "else", "body"):
            if key in s:
                yield from _stmts(s[key])


def _exprs_of(s):
    for key in ("value", "cond", "start", "stop", "step"):
        if key in s and isinstance(s[key], list):
            yield from _walk(s[key])


def _walk(e):
    if isinstance(e, list) and e:
        yield e
        if e[0] not in ("var", "int", "float", "bool"):
            for a in e[(2 if e[0] == "CALL" else 1):]:
                yield from _walk(a)
