"""frontend_python — lift Python functions into the card IR (observe -> cards).

Supported subset (everything else is reported, never pasted through):

  def f(a: int, b: float, ...) -> int        params int/float/bool, no defaults
  x = e · x += e · a, b = b, a % b            locals keep one type
  if/elif/else · while · for i in range(a[, b[, step]]) with a constant step
  return e · break · continue · pass · docstrings
  + - * / // % ** (constant exponent >= 0) & | ^ << >> ~ unary - not and or
  == != < <= > >= (chains) · x if c else y
  abs min max (2 args) pow(a, b[, m]) float(x) int(x) math.gcd(a, b)
  calls to other lifted functions of the same module (L45: the callee must lift)

Each unsupported construct is reported with its line, so a translation gap
is a precise list, not a percentage guess.

Honest limits (L1): no strings, lists, dicts, classes, exceptions, globals,
closures or side effects; ``int`` follows Python's unbounded semantics, so
fixed-width targets agree only inside the declared input domain.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass, field

from .ir import OpSpec, check_lists, elem_type

BINOPS = {ast.Add: "ADD", ast.Sub: "SUB", ast.Mult: "MUL", ast.Div: "DIV", ast.FloorDiv: "FLOORDIV",
          ast.Mod: "MOD", ast.Pow: "POW", ast.BitAnd: "BIT_AND", ast.BitOr: "BIT_OR", ast.BitXor: "BIT_XOR",
          ast.LShift: "SHIFT_LEFT", ast.RShift: "SHIFT_RIGHT"}
CMPOPS = {ast.Eq: "CMP_EQ", ast.NotEq: "CMP_NE", ast.Lt: "CMP_LT", ast.LtE: "CMP_LE", ast.Gt: "CMP_GT",
          ast.GtE: "CMP_GE"}
CALLS = {"abs": ("ABS", 1), "min": ("MIN", 2), "max": ("MAX", 2), "float": ("TO_FLOAT", 1),
         "int": ("TRUNC_INT", 1), "math.gcd": ("GCD", 2), "gcd": ("GCD", 2), "len": ("LEN", 1),
         "math.sqrt": ("FSQRT", 1), "math.exp": ("EXP", 1), "math.log": ("LOG", 1), "math.tanh": ("TANH", 1),
         "math.sin": ("SIN", 1), "math.cos": ("COS", 1), "math.tan": ("TAN", 1), "math.atan": ("ATAN", 1),
         "math.atan2": ("ATAN2", 2), "math.sinh": ("SINH", 1), "math.cosh": ("COSH", 1),
         "math.asin": ("ASIN", 1), "math.acos": ("ACOS", 1), "math.fabs": ("ABS", 1)}
# functions whose arguments are promoted to float (math.sqrt(4) is 2.0)
FLOAT_ARGS = {"FSQRT", "EXP", "LOG", "TANH", "SIN", "COS", "TAN", "ATAN", "ATAN2", "SINH", "COSH", "ASIN", "ACOS"}


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


def _ann_type(node) -> str | None:
    if node is None:
        return None
    if isinstance(node, ast.Name) and node.id in ("int", "float", "bool"):
        return node.id
    if isinstance(node, ast.Constant) and node.value in ("int", "float", "bool"):
        return node.value
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        try:
            return _ann_type(ast.parse(node.value, mode="eval").body)
        except SyntaxError:
            pass
    if isinstance(node, ast.Subscript) and ast.unparse(node.value) in ("list", "List", "typing.List") and \
            isinstance(node.slice, ast.Name) and node.slice.id in ("int", "float"):
        return f"list[{node.slice.id}]"
    raise Unsupported(f"type annotation {ast.unparse(node)!r} (only int/float/bool, list[int], list[float])", node)


class _FnLifter:
    def __init__(self, fdef: ast.FunctionDef, ops: dict[str, OpSpec], sigs: dict[str, dict],
                 param_hint: dict[str, str] | None):
        self.f = fdef
        self.ops = ops
        self.sigs = sigs                      # name -> {"params": [types], "returns": type|None}
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
        if a.vararg or a.kwarg or a.kwonlyargs or a.defaults or a.kw_defaults or a.posonlyargs:
            raise Unsupported("varargs, defaults or keyword-only parameters", f)
        if f.decorator_list:
            raise Unsupported("decorators", f)
        if isinstance(f, ast.AsyncFunctionDef):
            raise Unsupported("async def", f)
        params = []
        for arg in a.args:
            t = _ann_type(arg.annotation) or self.hint.get(arg.arg)
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
        fn = {"name": f.name, "params": params, "returns": ret, "locals": dict(self.locals), "body": body}
        problems = check_lists(fn)
        if problems:
            raise Unsupported(f"list value semantics: {problems[0]}", f)
        return fn

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
            if isinstance(s.value, (ast.ListComp, ast.List)):
                tmp_stmts, e, t = self.list_build(s.value)
                self.return_types.add(t)
                return tmp_stmts + [{"k": "return", "value": e}]
            e, t = self.expr(s.value)
            self.return_types.add(t)
            return [{"k": "return", "value": e}]
        if isinstance(s, ast.Pass):
            return []
        if isinstance(s, ast.Assign):
            if len(s.targets) != 1:
                raise Unsupported("chained assignment", s)
            tgt = s.targets[0]
            if isinstance(tgt, ast.Name) and isinstance(s.value, (ast.ListComp, ast.List)):
                uses = {x.id for x in ast.walk(s.value) if isinstance(x, ast.Name)}
                pre, e, t = self.list_build(s.value)
                if tgt.id in uses:          # x = [f(x[i]) ...]: the new list is a copy, never x's old storage
                    return pre + [self.assign(tgt.id, ["LIST_COPY", e], t, s)]
                # build straight into the target: assigning the temporary would alias it under two names
                out = []
                for st in _rename(pre, e[1], tgt.id):
                    if st.get("k") == "assign" and st["target"] == tgt.id:
                        st = self.assign(tgt.id, st["value"], t, s)
                    out.append(st)
                return out
            if isinstance(tgt, ast.Name):
                e, t = self.expr(s.value)
                return [self.assign(tgt.id, e, t, s)]
            if isinstance(tgt, ast.Subscript):
                return [self.store(tgt, self.expr(s.value), s)]
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
        if isinstance(s, ast.AugAssign) and isinstance(s.target, ast.Subscript):
            cur = self.expr(s.target)
            e, t = self.binop(type(s.op), cur[0], cur[1], s.value, s)
            return [self.store(s.target, (e, t), s)]
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
            if isinstance(s.target, ast.Name) and not s.orelse and not (
                    isinstance(s.iter, ast.Call) and isinstance(s.iter.func, ast.Name) and s.iter.func.id == "range"):
                try:
                    is_list = elem_type(self.expr(s.iter)[1]) is not None
                except Unsupported:
                    is_list = False
                if is_list:
                    return self.for_each(s)
            return [self.for_range(s)]
        if isinstance(s, ast.Break):
            return [{"k": "break"}]
        if isinstance(s, ast.Continue):
            return [{"k": "continue"}]
        raise Unsupported(f"statement {type(s).__name__}", s)

    def store(self, tgt: ast.Subscript, value: tuple, node) -> dict:
        """``xs[i] = v``: one element of a local list."""
        if not isinstance(tgt.value, ast.Name):
            raise Unsupported(f"assignment to {ast.unparse(tgt)!r} (only name[index])", node)
        lt = self.var_type(tgt.value.id, node)
        et = elem_type(lt)
        if et is None:
            raise Unsupported(f"{tgt.value.id!r} is {lt}, not a list", node)
        idx, it = self.expr(tgt.slice)
        if it != "int":
            raise Unsupported("a list index must be int", node)
        if idx[0] == "int" and idx[1] < 0:
            raise Unsupported("negative index (the IR has no wrap-around indexing)", node)
        v, vt = value
        if vt != et:
            if vt == "int" and et == "float":
                v = ["TO_FLOAT", v]
            else:
                raise Unsupported(f"storing {vt} into {lt}", node)
        return {"k": "set", "target": tgt.value.id, "index": idx, "value": v}

    def list_build(self, n) -> tuple[list, list, str]:
        """``[e for i in range(...)]`` and ``[a, b, c]`` -> (statements, the new list, its type)."""
        if isinstance(n, ast.List):
            vals = [self.expr(x) for x in n.elts]
            if not vals:
                raise Unsupported("an empty list literal has no element type (write [0.0] * 0)", n)
            ts = {t for _, t in vals}
            et = "float" if ts == {"int", "float"} else ts.pop() if len(ts) == 1 else None
            if et not in ("int", "float"):
                raise Unsupported(f"a list of {sorted({t for _, t in vals})}", n)
            tmp = self.fresh("l", f"list[{et}]")
            zero = ["float", 0.0] if et == "float" else ["int", 0]
            out = [{"k": "assign", "target": tmp, "value": ["LIST_NEW", ["int", len(vals)], zero]}]
            for i, (e, t) in enumerate(vals):
                out.append({"k": "set", "target": tmp, "index": ["int", i],
                            "value": ["TO_FLOAT", e] if t == "int" and et == "float" else e})
            return out, ["var", tmp], f"list[{et}]"
        if len(n.generators) != 1 or n.generators[0].ifs or n.generators[0].is_async:
            raise Unsupported("a comprehension with conditions or several for clauses", n)
        g = n.generators[0]
        it = g.iter
        if not (isinstance(g.target, ast.Name) and isinstance(it, ast.Call) and isinstance(it.func, ast.Name)
                and it.func.id == "range" and len(it.args) == 1 and not it.keywords):
            raise Unsupported(f"a comprehension over {ast.unparse(it)!r} (only range(n))", n)
        count, ct = self.expr(it.args[0])
        if ct != "int":
            raise Unsupported("range() argument must be int", n)
        # the comprehension's variable is its own (Python scopes it to the comprehension): a fresh local
        var = self.fresh("c", "int")
        old = g.target.id

        class _Rename(ast.NodeTransformer):
            def visit_Name(self, node):
                return ast.copy_location(ast.Name(id=var, ctx=node.ctx), node) if node.id == old else node
        e, et = self.expr(_Rename().visit(ast.parse(ast.unparse(n.elt), mode="eval")).body)
        if et not in ("int", "float"):
            raise Unsupported(f"a list of {et}", n)
        lt = f"list[{et}]"
        tmp = self.fresh("l", lt)
        size = self.fresh("n", "int")
        zero = ["float", 0.0] if et == "float" else ["int", 0]
        loop = {"k": "for_range", "var": var, "start": ["int", 0], "stop": ["var", size], "step": ["int", 1],
                "counter": self.fresh("it", "int"), "stop_var": self.fresh("stop", "int"),
                "body": [{"k": "set", "target": tmp, "index": ["var", var], "value": e}]}
        return ([{"k": "assign", "target": size, "value": count},
                 {"k": "assign", "target": tmp, "value": ["LIST_NEW", ["MAX", ["var", size], ["int", 0]], zero]},
                 loop], ["var", tmp], lt)

    def for_each(self, s: ast.For) -> list[dict]:
        """``for x in xs`` -> a loop over the indices (xs keeps its length: the IR lists have no append)."""
        lst, lt = self.expr(s.iter)
        et = elem_type(lt)
        var = s.target.id
        if self.env.get(var, et) != et:
            raise Unsupported(f"loop variable {var!r} changes type", s)
        self.env[var] = et
        self.locals.setdefault(var, et)
        src = lst
        out = []
        if lst[0] != "var":
            tmp = self.fresh("l", lt)
            out.append({"k": "assign", "target": tmp, "value": lst})
            src = ["var", tmp]
        idx = self.fresh("i", "int")
        body = [{"k": "assign", "target": var, "value": ["GET", src, ["var", idx]]}, *self.block(s.body)]
        out.append({"k": "for_range", "var": idx, "start": ["int", 0], "stop": ["LEN", src], "step": ["int", 1],
                    "counter": self.fresh("it", "int"), "stop_var": self.fresh("stop", "int"), "body": body})
        return out

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
        if optype is ast.Mult and (isinstance(right_node, ast.List) or elem_type(left_t) is not None):
            # [v] * n  and  n * [v]: a list of n copies
            if elem_type(left_t) is not None and left_ir[0] == "LIST_NEW" and left_ir[1] == ["int", 1]:
                n, nt = self.expr(right_node)
                if nt != "int":
                    raise Unsupported("list * non-int", node)
                return ["LIST_NEW", ["MAX", n, ["int", 0]], left_ir[2]], left_t
            if isinstance(right_node, ast.List) and len(right_node.elts) == 1 and left_t == "int":
                v, vt = self.expr(right_node.elts[0])
                if vt not in ("int", "float"):
                    raise Unsupported(f"a list of {vt}", node)
                return ["LIST_NEW", ["MAX", left_ir, ["int", 0]], v], f"list[{vt}]"
            raise Unsupported("list repetition other than [v] * n", node)
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
        if isinstance(n, ast.List) and len(n.elts) == 1:
            v, vt = self.expr(n.elts[0])          # [v]: only as the left side of [v] * n (binop checks)
            if vt not in ("int", "float"):
                raise Unsupported(f"a list of {vt}", n)
            return ["LIST_NEW", ["int", 1], v], f"list[{vt}]"
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
            return ["var", n.id], self.var_type(n.id, n)
        if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == "math" \
                and n.attr in ("pi", "e", "tau"):
            import math
            return ["float", getattr(math, n.attr)], "float"
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
        if isinstance(n, ast.Subscript):
            xs, lt = self.expr(n.value)
            if elem_type(lt) is None:
                raise Unsupported(f"indexing a {lt}", n)
            if isinstance(n.slice, ast.Slice):
                if n.slice.lower is None and n.slice.upper is None and n.slice.step is None:
                    return ["LIST_COPY", xs], lt
                raise Unsupported("slices other than xs[:]", n)
            i, it = self.expr(n.slice)
            if it != "int":
                raise Unsupported("a list index must be int", n)
            if i[0] == "int" and i[1] < 0:
                raise Unsupported("negative index (the IR has no wrap-around indexing)", n)
            return ["GET", xs, i], elem_type(lt)
        raise Unsupported(f"expression {type(n).__name__}", n)

    def call(self, n: ast.Call):
        if n.keywords:
            raise Unsupported("keyword arguments in call", n)
        fname = ast.unparse(n.func)
        if isinstance(n.func, ast.Attribute) and n.func.attr == "copy" and not n.args:
            xs, lt = self.expr(n.func.value)
            if elem_type(lt) is not None:
                return ["LIST_COPY", xs], lt
        if fname == "list" and len(n.args) == 1:
            xs, lt = self.expr(n.args[0])
            if elem_type(lt) is None:
                raise Unsupported(f"list() of {lt}", n)
            return ["LIST_COPY", xs], lt
        if fname in ("sum", "max", "min") and len(n.args) == 1:
            raise Unsupported(f"{fname}() over a list (write the loop: Python's float sum is compensated "
                              "since 3.12, so a plain loop is a different function)", n)
        args = [self.expr(a) for a in n.args]
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
            if op in FLOAT_ARGS:
                args = [(["TO_FLOAT", e], "float") if t == "int" else (e, t) for e, t in args]
            return self.apply(op, args, n)
        if isinstance(n.func, ast.Name) and n.func.id in self.sigs:
            sig = self.sigs[n.func.id]
            if len(args) != len(sig["params"]):
                raise Unsupported(f"{fname}() arity mismatch", n)
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
        raise Unsupported(f"call to {fname}() (no op card or lifted function)", n)


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
    lines = source.splitlines()
    fdefs = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    sigs: dict[str, dict] = {}
    for f in fdefs:
        try:
            ptypes = [(_ann_type(a.annotation) or (param_hints or {}).get(f.name, {}).get(a.arg) or "int")
                      for a in f.args.args]
            sigs[f.name] = {"params": ptypes, "returns": _ann_type(f.returns)}
        except Unsupported:
            continue
    results: dict[str, Lifted] = {}
    for f in fdefs:
        src = "\n".join(lines[f.lineno - 1 - len(f.decorator_list): f.end_lineno])
        lifter = _FnLifter(f, ops, sigs, (param_hints or {}).get(f.name))
        try:
            ir = lifter.lift()
            sigs[f.name]["returns"] = ir["returns"]
            results[f.name] = Lifted(f.name, True, ir, src, [], lifter.inferred, f.lineno)
        except Unsupported as exc:
            results[f.name] = Lifted(f.name, False, None, src, [str(exc)], lifter.inferred, f.lineno)
    # closure: a lifted function calling a failed one fails too (iterate to a fixed point)
    changed = True
    while changed:
        changed = False
        for name, lf in results.items():
            if not lf.ok:
                continue
            callees = {e[1] for s in _stmts(lf.ir["body"]) for e in _exprs_of(s) if e[0] == "CALL"}
            bad = [c for c in callees if c in results and not results[c].ok or c not in results]
            if bad:
                lf.ok = False
                lf.reasons.append(f"calls {', '.join(sorted(bad))} which did not lift")
                changed = True
    return [lf for lf in results.values() if not only or lf.name in only]


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


def _rename(x, old: str, new: str):
    """A copy of statements/expressions with every occurrence of the (fresh, unique) name ``old`` replaced."""
    if isinstance(x, str):
        return new if x == old else x
    if isinstance(x, list):
        return [_rename(v, old, new) for v in x]
    if isinstance(x, dict):
        return {k: _rename(v, old, new) for k, v in x.items()}
    return x


def _stmts(body):
    for s in body:
        yield s
        for key in ("then", "else", "body"):
            if key in s:
                yield from _stmts(s[key])


def _exprs_of(s):
    for key in ("value", "cond", "start", "stop", "step", "index"):
        if key in s and isinstance(s[key], list):
            yield from _walk(s[key])


def _walk(e):
    if isinstance(e, list) and e:
        yield e
        if e[0] not in ("var", "int", "float", "bool"):
            for a in e[(2 if e[0] == "CALL" else 1):]:
                yield from _walk(a)
