"""compile — check and compile card-language declarations into cards.

    fn          -> IR functions (the same IR the Python frontend produces, so codegen,
                   conformance, translate and improve all apply); typed int/float/bool
    facts/rules -> a logic Program (engines/logic.py), constraints included
    theorem     -> theorem cards (engines/theorems.py), ``card`` semantics
    test/query  -> checks that ``cardmodel run`` executes
    card        -> cards for any registry
    algorithm.NAME(...) -> the CL "resolve" stage: the algorithm card's cheapest
                   verified form (lifted through frontend_python) becomes a function

Typing follows the Python frontend: int/float promotion, ``/`` on ints is
float division, ``**`` on ints needs a literal exponent >= 0 (use a loop
or ``algorithm.power``), ``and``/``or``/``not`` and conditions need Bool.

Honest limits (L1): no strings, lists or user types inside functions; the
``Nat`` type is a domain annotation (an int >= 0), not truncating arithmetic;
a ``match`` substitutes the scrutinee into each arm (it is re-evaluated,
which is fine for pure expressions).
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

from ..engines import logic as L
from ..engines.ir import OpSpec
from .syntax import CardSyntaxError, Decl, parse

BIN = {"+": "ADD", "-": "SUB", "*": "MUL", "/": "DIV", "//": "FLOORDIV", "%": "MOD", "**": "POW",
       "&": "BIT_AND", "|": "BIT_OR", "^": "BIT_XOR", "<<": "SHIFT_LEFT", ">>": "SHIFT_RIGHT"}
CMP = {"==": "CMP_EQ", "!=": "CMP_NE", "<": "CMP_LT", "<=": "CMP_LE", ">": "CMP_GT", ">=": "CMP_GE"}
PROP_REL = {"==": "eq", "!=": "ne", "<": "lt", "<=": "le", ">": "gt", ">=": "ge"}
BUILTINS = {"abs": ("ABS", 1), "min": ("MIN", 2), "max": ("MAX", 2), "gcd": ("GCD", 2), "float": ("TO_FLOAT", 1),
            "int": ("TRUNC_INT", 1)}
AUG = {"+=": "+", "-=": "-", "*=": "*", "//=": "//", "%=": "%"}


class CompileError(ValueError):
    def __init__(self, msg: str, line: int | None = None, path: str | None = None):
        self.msg, self.line, self.path = msg, line, path
        where = f"{path}:{line}: " if path and line else f"line {line}: " if line else ""
        super().__init__(where + msg)


@dataclass
class Module:
    name: str
    path: str | None = None
    source_sha: str = ""
    functions: dict = field(default_factory=dict)        # name -> IR function
    fn_lines: dict = field(default_factory=dict)
    program: L.Program = field(default_factory=L.Program)
    theorems: list = field(default_factory=list)
    tests: list = field(default_factory=list)
    queries: list = field(default_factory=list)
    cards: list = field(default_factory=list)
    uses: list = field(default_factory=list)
    resolved: dict = field(default_factory=dict)         # algorithm card -> chosen form

    def ir_module(self, entry: str | None = None) -> dict:
        """Callers before callees (codegen emits in reverse, so callees are defined first: Lean, Lua, C)."""
        order: list[str] = []

        def visit(name, stack=()):
            if name in order or name in stack or name not in self.functions:
                return
            for s in _walk_stmts(self.functions[name]["body"]):
                for e in _walk_exprs(s):
                    if e[0] == "CALL":
                        visit(e[1], (*stack, name))
            order.append(name)

        for n in self.functions:
            visit(n)
        fns = [self.functions[n] for n in reversed(order)]
        if entry is None and fns:
            entry = fns[0]["name"]
        return {"entry": entry, "functions": fns}

    def summary(self) -> dict:
        return {"module": self.name, "functions": sorted(self.functions), "facts": len(self.program.facts),
                "rules": sum(1 for r in self.program.rules if r.head is not None),
                "constraints": sum(1 for r in self.program.rules if r.head is None),
                "theorems": [t["name"] for t in self.theorems], "tests": len(self.tests),
                "queries": len(self.queries), "cards": [f"{c['category']}/{c['name']}" for c in self.cards],
                "resolved": self.resolved}


def _walk_stmts(body):
    for s in body:
        yield s
        for key in ("then", "else", "body"):
            if key in s:
                yield from _walk_stmts(s[key])


def _walk_exprs(s):
    for key in ("value", "cond", "start", "stop", "step"):
        e = s.get(key)
        if isinstance(e, list):
            stack = [e]
            while stack:
                x = stack.pop()
                if isinstance(x, list) and x:
                    yield x
                    if x[0] not in ("var", "int", "float", "bool"):
                        stack.extend(a for a in x[(2 if x[0] == "CALL" else 1):] if isinstance(a, list))


# -- functions -------------------------------------------------------------------------------------
class FnCompiler:
    def __init__(self, decl: Decl, ops: dict[str, OpSpec], sigs: dict, mod: "Compiler"):
        self.d = decl.data
        self.line = decl.line
        self.ops = ops
        self.sigs = sigs
        self.mod = mod
        self.env: dict[str, str] = {}
        self.locals: dict[str, str] = {}
        self.tmp = 0
        self.return_types: set[str] = set()

    def err(self, msg, line=None):
        raise CompileError(f"fn {self.d['name']}: {msg}", line or self.line, self.mod.path)

    def compile(self) -> dict:
        params = []
        for pname, ptype in self.d["params"]:
            t = "int" if ptype == "nat" else ptype
            params.append({"name": pname, "type": t})
            self.env[pname] = t
        requires = [self.cond(r, self.line) for r in self.d.get("requires") or []]
        body = self.block(self.d["body"])
        if not _always_returns(body):
            self.err("a path can reach the end of the function without `return`")
        declared = self.d.get("returns")
        declared = "int" if declared == "nat" else declared
        if declared:
            if self.return_types - {declared}:
                self.err(f"returns {sorted(self.return_types)} but is declared -> {declared}")
            ret = declared
        elif len(self.return_types) == 1:
            ret = next(iter(self.return_types))
        else:
            self.err(f"return types disagree ({sorted(self.return_types)}); declare -> Type")
        fn = {"name": self.d["name"], "params": params, "returns": ret, "locals": dict(self.locals), "body": body}
        if requires:
            fn["requires"] = requires
        nat = [p for p, t in self.d["params"] if t == "nat"]
        if nat:
            fn["nat_params"] = nat
        return fn

    def fresh(self, base: str, typ: str) -> str:
        self.tmp += 1
        name = f"cm_{base}{self.tmp}"
        self.locals[name] = typ
        self.env[name] = typ
        return name

    def declare(self, name: str, typ: str, line) -> None:
        prev = self.env.get(name)
        if prev is not None and prev != typ:
            self.err(f"{name!r} changes type {prev} -> {typ}", line)
        if prev is None:
            self.env[name] = typ
            if name not in [p for p, _ in self.d["params"]]:
                self.locals[name] = typ

    def block(self, stmts) -> list:
        out = []
        for s in stmts:
            out.extend(self.stmt(s))
        return out

    def stmt(self, s) -> list:
        k = s[0]
        if k == "let":
            _, name, typ, e, line = s
            ir, t = self.expr(e, line)
            if typ:
                typ = "int" if typ == "nat" else typ
                if t == "int" and typ == "float":
                    ir, t = ["TO_FLOAT", ir], "float"
                elif t != typ:
                    self.err(f"let {name}: {typ} = <{t}>", line)
            self.declare(name, t, line)
            return [{"k": "assign", "target": name, "value": ir}]
        if k == "assign":
            _, name, op, e, line = s
            if name not in self.env:
                self.err(f"assignment to undeclared {name!r} (use `let {name} = ...`)", line)
            if op != "=":
                e = ("bin", AUG[op], ("name", name), e)
            ir, t = self.expr(e, line)
            want = self.env[name]
            if t != want:
                if t == "int" and want == "float":
                    ir = ["TO_FLOAT", ir]
                else:
                    self.err(f"{name} is {want}, assigned {t}", line)
            return [{"k": "assign", "target": name, "value": ir}]
        if k == "passign":
            _, names, exprs, line = s
            out, temps = [], []
            for n, e in zip(names, exprs):
                ir, t = self.expr(e, line)
                if n not in self.env:
                    self.declare(n, t, line)
                if self.env[n] != t:
                    if t == "int" and self.env[n] == "float":
                        ir, t = ["TO_FLOAT", ir], "float"
                    else:
                        self.err(f"{n} is {self.env[n]}, assigned {t}", line)
                tmp = self.fresh("tmp", t)
                out.append({"k": "assign", "target": tmp, "value": ir})
                temps.append(tmp)
            for n, tmp in zip(names, temps):
                out.append({"k": "assign", "target": n, "value": ["var", tmp]})
            return out
        if k == "if":
            _, branches, other, line = s
            node = self.block(other) if other else []
            for cond, blk in reversed(branches):
                c = self.cond(cond, line)
                node = [{"k": "if", "cond": c, "then": self.block(blk), "else": node}]
            return node
        if k == "while":
            _, cond, body, line = s
            return [{"k": "while", "cond": self.cond(cond, line), "body": self.block(body)}]
        if k == "for":
            _, var, start, stop, step, body, line = s
            a, at = self.expr(start, line)
            b, bt = self.expr(stop, line)
            st, _ = self.expr(step, line)
            if at != "int" or bt != "int":
                self.err("range bounds must be Int", line)
            if not (st[0] == "int" and st[1] != 0):
                self.err("the step (`by`) must be a non-zero integer literal", line)
            self.declare(var, "int", line)
            counter = self.fresh("it", "int")
            stop_var = self.fresh("stop", "int")
            return [{"k": "for_range", "var": var, "start": a, "stop": b, "step": st, "counter": counter,
                     "stop_var": stop_var, "body": self.block(body)}]
        if k == "return":
            _, e, line = s
            ir, t = self.expr(e, line)
            declared = self.d.get("returns")
            declared = "int" if declared == "nat" else declared
            if declared == "float" and t == "int":
                ir, t = ["TO_FLOAT", ir], "float"
            self.return_types.add(t)
            return [{"k": "return", "value": ir}]
        if k in ("break", "continue"):
            return [{"k": k}]
        self.err(f"unknown statement {k}")

    def cond(self, e, line):
        ir, t = self.expr(e, line)
        if t != "bool":
            self.err(f"a condition must be Bool, found {t} (compare explicitly)", line)
        return ir

    # -- expressions --
    def spec(self, op, line) -> OpSpec:
        s = self.ops.get(op)
        if s is None:
            self.err(f"no op card {op!r} with IR semantics", line)
        return s

    def apply(self, op, args, line):
        spec = self.spec(op, line)
        types = [t for _, t in args]
        rt = spec.result_type(types)
        exprs = [e for e, _ in args]
        if rt is None:
            prom = spec.promoted(types)
            if prom is None:
                self.err(f"{op} does not accept ({', '.join(types)})", line)
            exprs = [["TO_FLOAT", e] if t == "int" and p == "float" else e for (e, t), p in zip(args, prom)]
            rt = spec.result_type(prom)
        return [op, *exprs], rt

    def expr(self, e, line):
        k = e[0]
        if k == "num":
            v = e[1]
            return (["float", v], "float") if isinstance(v, float) else (["int", v], "int")
        if k == "bool":
            return ["bool", e[1]], "bool"
        if k == "str":
            self.err("strings are not values inside functions (IR: int/float/bool)", line)
        if k == "name":
            if e[1] not in self.env:
                self.err(f"unknown name {e[1]!r}", line)
            return ["var", e[1]], self.env[e[1]]
        if k == "ref":
            self.err(f"card reference {e[1]} is not a value (call it: {e[1]}(...))", line)
        if k == "un":
            op, x = e[1], e[2]
            ir, t = self.expr(x, line)
            if op == "-":
                if ir[0] in ("int", "float"):
                    return [ir[0], -ir[1]], t
                return self.apply("NEG", [(ir, t)], line)
            if op == "not":
                if t != "bool":
                    self.err("`not` needs Bool", line)
                return ["NOT", ir], "bool"
            if op == "~":
                return self.apply("BIT_NOT", [(ir, t)], line)
        if k == "bin":
            op, a, b = e[1], e[2], e[3]
            if op in ("and", "or"):
                ia, ta = self.expr(a, line)
                ib, tb = self.expr(b, line)
                if ta != "bool" or tb != "bool":
                    self.err(f"`{op}` needs Bool operands", line)
                return ["AND" if op == "and" else "OR", ia, ib], "bool"
            if op in ("==>", "<=>"):
                self.err(f"`{op}` belongs in theorem statements", line)
            ia, ta = self.expr(a, line)
            ib, tb = self.expr(b, line)
            if op in CMP:
                return self.apply(CMP[op], [(ia, ta), (ib, tb)], line)
            if "bool" in (ta, tb):
                self.err(f"arithmetic on Bool ({op})", line)
            if op == "/" and ta == "int" and tb == "int":
                return ["DIV", ["TO_FLOAT", ia], ["TO_FLOAT", ib]], "float"
            if op == "**" and ta == "int" and tb == "int" and not (ib[0] == "int" and ib[1] >= 0):
                self.err("Int ** Int needs a literal exponent >= 0 (use a loop or algorithm.power(x, n))", line)
            return self.apply(BIN[op], [(ia, ta), (ib, tb)], line)
        if k == "if":
            c = self.cond(e[1], line)
            ia, ta = self.expr(e[2], line)
            ib, tb = self.expr(e[3], line)
            if ta != tb:
                if {ta, tb} == {"int", "float"}:
                    ia = ["TO_FLOAT", ia] if ta == "int" else ia
                    ib = ["TO_FLOAT", ib] if tb == "int" else ib
                    ta = tb = "float"
                else:
                    self.err(f"if/else branches are {ta} and {tb}", line)
            return ["IF_EXPR", c, ia, ib], ta
        if k == "match":
            return self.expr(desugar_match(e, lambda m: self.err(m, line)), line)
        if k == "call":
            return self.call(e, line)
        self.err(f"unsupported expression {k}", line)

    def call(self, e, line):
        _, name, args, _ln = e
        if name.startswith("op."):
            op = name[3:]
            spec = self.spec(op, line)
            if len(args) != spec.arity:
                self.err(f"{name} takes {spec.arity} argument(s)", line)
            if op in ("AND", "OR"):
                ia, _ = self.expr(args[0], line)
                ib, _ = self.expr(args[1], line)
                return [op, ia, ib], "bool"
            return self.apply(op, [self.expr(a, line) for a in args], line)
        if name.startswith("algorithm."):
            fname = self.mod.resolve_algorithm(name[len("algorithm."):], line)
            return self.user_call(fname, args, line)
        if name == "pow":
            ir_args = [self.expr(a, line) for a in args]
            if len(ir_args) == 3:
                return self.apply("POW_MOD", ir_args, line)
            if len(ir_args) == 2:
                if ir_args[0][1] == "int" and not (ir_args[1][0][0] == "int" and ir_args[1][0][1] >= 0):
                    self.err("pow(Int, Int) needs a literal exponent >= 0 (pow(a, b, m) is modular)", line)
                return self.apply("POW", ir_args, line)
        if name in BUILTINS:
            op, arity = BUILTINS[name]
            if len(args) != arity:
                self.err(f"{name}() takes {arity} argument(s)", line)
            ir_args = [self.expr(a, line) for a in args]
            if op == "TO_FLOAT" and ir_args[0][1] == "float":
                return ir_args[0]
            if op == "TRUNC_INT" and ir_args[0][1] == "int":
                return ir_args[0]
            return self.apply(op, ir_args, line)
        if name in self.sigs:
            return self.user_call(name, args, line)
        if "." in name:
            self.err(f"card reference {name} is not callable here (op.NAME and algorithm.NAME are)", line)
        self.err(f"unknown function {name}()", line)

    def user_call(self, name, args, line):
        sig = self.sigs[name]
        if len(args) != len(sig["params"]):
            self.err(f"{name}() takes {len(sig['params'])} argument(s)", line)
        fixed = []
        for a, want in zip(args, sig["params"]):
            ir, t = self.expr(a, line)
            if t != want:
                if t == "int" and want == "float":
                    ir = ["TO_FLOAT", ir]
                else:
                    self.err(f"{name}() argument is {t}, expected {want}", line)
            fixed.append(ir)
        ret = sig.get("returns")
        if ret is None:
            self.err(f"{name}() is called before its return type is known; declare -> Type", line)
        return ["CALL", name, *fixed], ret


def desugar_match(e, err):
    """match s with | 0 -> a | k -> b   ==>   if s == 0 then a else b[k := s]."""
    _, scrut, arms = e
    out = None
    for pat, body in reversed(arms):
        if pat[0] == "wild":
            out = body
        elif pat[0] == "bind":
            out = subst(body, pat[1], scrut)
        else:
            if out is None:
                err("match is not exhaustive: end with `| _ -> ...` or a variable pattern")
            lit = ("bool", pat[1]) if isinstance(pat[1], bool) else ("num", pat[1])
            out = ("if", ("bin", "==", scrut, lit), body, out)
    if out is None:
        err("empty match")
    return out


def subst(e, name, rep):
    if not isinstance(e, tuple) or not e:
        return e
    if e[0] == "name":
        return rep if e[1] == name else e
    if e[0] == "match":
        _, s, arms = e
        new_arms = [(p, b if (p[0] == "bind" and p[1] == name) else subst(b, name, rep)) for p, b in arms]
        return ("match", subst(s, name, rep), new_arms)
    if e[0] == "call":
        return ("call", e[1], [subst(a, name, rep) for a in e[2]], e[3])
    return tuple(subst(x, name, rep) if isinstance(x, tuple) else x for x in e)


def _always_returns(body) -> bool:
    if not body:
        return False
    last = body[-1]
    if last["k"] == "return":
        return True
    if last["k"] == "if":
        return _always_returns(last["then"]) and _always_returns(last["else"])
    return False


# -- logic --------------------------------------------------------------------------------------------
def is_var_name(n: str) -> bool:
    return n[0].isupper() or n[0] == "_"


class LogicCompiler:
    def __init__(self, mod: "Compiler"):
        self.mod = mod
        self.anon = 0

    def err(self, msg, line):
        raise CompileError(msg, line, self.mod.path)

    def term(self, t, line):
        k = t[0]
        if k == "var":
            return L.Var(t[1])
        if k in ("sym", "num"):
            return t[1]
        self.err(f"bad term {t}", line)

    def surface_term(self, e, line):
        """An expression used as an atom argument: a variable or a constant."""
        k = e[0]
        if k == "name":
            if e[1] == "_":
                self.anon += 1
                return L.Var(f"_a{self.anon}")
            return L.Var(e[1]) if is_var_name(e[1]) else e[1]
        if k in ("num", "str"):
            return e[1]
        if k == "bool":
            return "true" if e[1] else "false"
        self.err("atom arguments are variables or constants; bind computed values first (`N1 = N + 1`)", line)

    def atom(self, a) -> L.Atom:
        _, pred, args, line = a
        return L.Atom(pred, tuple(self.term(x, line) for x in args))

    def call_atom(self, e, line) -> L.Atom:
        _, name, args, _ln = e
        return L.Atom(name, tuple(self.surface_term(x, line) for x in args))

    def is_function(self, name: str) -> bool:
        return name in self.mod.sigs or name in BUILTINS or name == "pow" or name.startswith(("op.", "algorithm."))

    def literal(self, lit):
        k = lit[0]
        if k == "atom":
            return self.atom(lit)
        if k == "not":
            return L.Neg(self.atom(lit[1]))
        if k == "atom_or_test":
            e, line = lit[1], lit[2]
            if self.is_function(e[1]):
                return L.Test(self.expr(e, line))
            return self.call_atom(e, line)
        if k == "test":
            return L.Test(self.expr(lit[1], lit[2]))
        if k == "eq":
            _, a, b, line = lit
            if a[0] == "name" and is_var_name(a[1]) and a[1] != "_":
                return L.Bind(a[1], self.expr(b, line))
            if b[0] == "name" and is_var_name(b[1]) and b[1] != "_":
                return L.Bind(b[1], self.expr(a, line))
            return L.Test(["CMP_EQ", self.expr(a, line), self.expr(b, line)])
        if k == "agg":
            _, fn, var, over, sub, _line = lit
            return L.Agg(fn, var, over, tuple(self.literal(x) for x in sub))
        raise CompileError(f"unknown literal {k}")

    def expr(self, e, line):
        """Logic expressions are dynamically typed IR (Upper = variable, lower = symbol)."""
        k = e[0]
        if k == "num":
            return ["float", e[1]] if isinstance(e[1], float) else ["int", e[1]]
        if k == "bool":
            return ["sym", "true" if e[1] else "false"]
        if k == "str":
            return ["sym", e[1]]
        if k == "name":
            return ["var", e[1]] if is_var_name(e[1]) else ["sym", e[1]]
        if k == "un":
            x = self.expr(e[2], line)
            if e[1] == "-" and x[0] in ("int", "float"):
                return [x[0], -x[1]]
            return {"-": ["NEG", x], "not": ["NOT", x], "~": ["BIT_NOT", x]}[e[1]]
        if k == "bin":
            op = e[1]
            a, b = self.expr(e[2], line), self.expr(e[3], line)
            if op in ("and", "or"):
                return ["AND" if op == "and" else "OR", a, b]
            if op in CMP:
                return [CMP[op], a, b]
            if op in BIN:
                return [BIN[op], a, b]
            self.err(f"operator {op} in a rule", line)
        if k == "if":
            return ["IF_EXPR", self.expr(e[1], line), self.expr(e[2], line), self.expr(e[3], line)]
        if k == "call":
            _, name, args, _ln = e
            ir_args = [self.expr(a, line) for a in args]
            if name.startswith("op."):
                return [name[3:], *ir_args]
            if name in BUILTINS:
                return [BUILTINS[name][0], *ir_args]
            if name == "pow":
                return ["POW_MOD" if len(ir_args) == 3 else "POW", *ir_args]
            if name.startswith("algorithm."):
                fname = self.mod.resolve_algorithm(name[len("algorithm."):], line)
                return ["CALL", fname, *ir_args]
            if name in self.mod.sigs:
                return ["CALL", name, *ir_args]
            self.err(f"{name}(...) inside an expression: not a function (predicates are literals of their own)",
                     line)
        if k == "match":
            return self.expr(desugar_match(e, lambda m: self.err(m, line)), line)
        self.err(f"unsupported expression {k} in a rule", line)


# -- theorems (math context) ------------------------------------------------------------------------
class TheoremCompiler(FnCompiler):
    """Theorem statements: params are typed variables; comparisons and connectives become propositions."""

    def __init__(self, decl: Decl, ops, sigs, mod):
        super().__init__(Decl("fn", decl.line, {"name": decl.data["name"], "params": decl.data["params"],
                                                "returns": None, "body": []}), ops, sigs, mod)
        self.t = decl.data
        for pname, ptype in self.t["params"]:
            self.env[pname] = "int" if ptype == "nat" else ptype

    def err(self, msg, line=None):
        raise CompileError(f"theorem {self.t['name']}: {msg}", line or self.line, self.mod.path)

    def prop(self, e, line):
        k = e[0]
        if k == "bin" and e[1] in ("==>", "<=>"):
            return ["imp" if e[1] == "==>" else "iff", self.prop(e[2], line), self.prop(e[3], line)]
        if k == "bin" and e[1] in ("and", "or"):
            return [e[1], self.prop(e[2], line), self.prop(e[3], line)]
        if k == "un" and e[1] == "not":
            return ["not", self.prop(e[2], line)]
        if k == "bool":
            return ["true"] if e[1] else ["false"]
        if k == "bin" and e[1] in PROP_REL:
            a, ta = self.expr(e[2], line)
            b, tb = self.expr(e[3], line)
            if ta != tb and {ta, tb} == {"int", "float"}:
                a = ["TO_FLOAT", a] if ta == "int" else a
                b = ["TO_FLOAT", b] if tb == "int" else b
            elif ta != tb:
                self.err(f"comparing {ta} with {tb}", line)
            return [PROP_REL[e[1]], a, b]
        ir, t = self.expr(e, line)
        if t != "bool":
            self.err(f"a statement must be a proposition, found a {t} term", line)
        return ["bool", ir]

    def card(self) -> dict:
        hyps = [self.prop(h, self.line) for h in self.t["hyps"]]
        concl = self.prop(self.t["concl"], self.line)
        return {"name": f"{self.mod.name}.{self.t['name']}", "label": self.t["name"], "category": "theorem",
                "vars": [{"name": n, "type": t} for n, t in self.t["params"]], "hyps": hyps, "concl": concl,
                "semantics": "card", "status": "conjecture",
                "origin": {"kind": "card_source", "module": self.mod.name,
                           "source": f"{self.mod.path_label}:{self.line}"}}


# -- the module compiler ----------------------------------------------------------------------------------
class Compiler:
    def __init__(self, ops, store=None, path: str | None = None, name: str | None = None):
        self.ops = ops
        self.store = store
        self.path = path
        self.path_label = Path(path).name if path else "<source>"
        self.name = name or (Path(path).stem if path else "main")
        self.sigs: dict = {}
        self.module: Module | None = None
        self._alg_funcs: dict = {}

    def compile(self, decls: list[Decl], text: str = "") -> Module:
        mod = Module(self.name, self.path, hashlib.sha256(text.encode()).hexdigest()[:12])
        self.module = mod
        for d in decls:
            if d.kind == "module":
                self.name = mod.name = d.data["name"]
        mod.program.name = mod.name
        fn_decls = [d for d in decls if d.kind == "fn"]
        names = [d.data["name"] for d in fn_decls]
        dup = sorted({n for n in names if names.count(n) > 1})
        if dup:
            raise CompileError(f"function(s) defined twice: {', '.join(dup)}", None, self.path)
        for d in fn_decls:
            r = d.data.get("returns")
            self.sigs[d.data["name"]] = {"params": ["int" if t == "nat" else t for _, t in d.data["params"]],
                                         "returns": "int" if r == "nat" else r}
        pending = list(fn_decls)            # un-annotated return types: compile in passes until stable
        while pending:
            still = []
            for d in pending:
                try:
                    fn = FnCompiler(d, self.ops, self.sigs, self).compile()
                except CompileError as exc:
                    if "return type is known" in exc.msg:
                        still.append(d)
                        continue
                    raise
                mod.functions[fn["name"]] = fn
                mod.fn_lines[fn["name"]] = d.line

                self.sigs[fn["name"]]["returns"] = fn["returns"]
            if len(still) == len(pending):
                FnCompiler(still[0], self.ops, self.sigs, self).compile()     # raises the precise error
            pending = still
        lc = LogicCompiler(self)
        counts: dict[str, int] = {}
        for d in decls:
            if d.kind == "theory":
                mod.program.name = d.data["name"]
            elif d.kind == "use":
                mod.uses.extend(d.data["names"])
            elif d.kind == "clause":
                head = lc.atom(d.data["head"]) if d.data["head"] else None
                body = tuple(lc.literal(x) for x in d.data["body"])
                if head is not None and not body:
                    if not head.ground():
                        raise CompileError(f"fact {head} has variables (a fact must be ground)", d.line, self.path)
                    mod.program.add_fact(head.pred, head.args, f"{self.path_label}:{d.line}")
                    continue
                key = head.pred if head else "never"
                counts[key] = counts.get(key, 0) + 1
                label = d.data["label"] or f"{key}_{counts[key]}"
                mod.program.rules.append(L.Rule(label, head, body, card=f"logic_rule/{mod.name}.{label}",
                                                line=d.line))
            elif d.kind == "query":
                mod.queries.append({"line": d.line, "literals": [lc.literal(x) for x in d.data["body"]]})
            elif d.kind == "test":
                mod.tests.append(self.test(d, lc))
            elif d.kind == "theorem":
                mod.theorems.append(TheoremCompiler(d, self.ops, self.sigs, self).card())
            elif d.kind == "card":
                c = {"name": d.data["name"], "category": d.data["registry"], **d.data["fields"]}
                c.setdefault("provenance", {"origin": f"{self.path_label}:{d.line}", "module": mod.name})
                mod.cards.append(c)
        for name, fn in self._alg_funcs.items():
            mod.functions.setdefault(name, fn)
        labels = [r.name for r in mod.program.rules]
        dup = sorted({n for n in labels if labels.count(n) > 1})
        if dup:
            raise CompileError(f"rule label(s) used twice: {', '.join(dup)}", None, self.path)
        problems = mod.program.check()
        if problems:
            raise CompileError("logic: " + "; ".join(problems), None, self.path)
        return mod

    def test(self, d: Decl, lc: LogicCompiler) -> dict:
        e = d.data["expr"]
        lits, is_logic = [], False
        for c in _flatten_and(e):
            if c[0] == "call" and not lc.is_function(c[1]):
                lits.append(lc.call_atom(c, d.line))
                is_logic = True
            elif c[0] == "un" and c[1] == "not" and c[2][0] == "call" and not lc.is_function(c[2][1]):
                lits.append(L.Neg(lc.call_atom(c[2], d.line)))
                is_logic = True
            elif c[0] == "name" and not is_var_name(c[1]):
                lits.append(L.Atom(c[1], ()))
                is_logic = True
            else:
                lits.append(L.Test(lc.expr(c, d.line)))
        if is_logic:
            return {"line": d.line, "kind": "logic", "literals": lits}
        return {"line": d.line, "kind": "expr", "expr": lc.expr(e, d.line)}

    def resolve_algorithm(self, name: str, line) -> str:
        """CL resolve: an algorithm card's cheapest form with domain 'any' (CM05), lifted into IR."""
        fname = f"alg_{name}"
        if fname in self._alg_funcs:
            return fname
        if self.store is None:
            raise CompileError(f"algorithm.{name}: no card store", line, self.path)
        card = self.store.get(f"algorithm/{name}")
        if card is None:
            raise CompileError(f"no algorithm card {name!r}", line, self.path)
        from ..engines.frontend_python import lift_source, module_for
        forms = [f for f in card.get("forms") or [] if f.get("runnable") and f.get("domain", "any") == "any"
                 and f.get("lang", "python") == "python"]
        forms.sort(key=lambda f: (f.get("cost", 1e9), f["name"]))
        reasons = []
        for form in forms:
            lifted = lift_source(form["code"], self.ops)
            ok = {lf.name: lf for lf in lifted if lf.ok}
            if form["entry"] not in ok:
                reasons.append(f"{form['name']}: " + "; ".join(r for lf in lifted for r in lf.reasons))
                continue
            sub = module_for(form["entry"], lifted)
            rename = {f["name"]: (fname if f["name"] == form["entry"] else f"alg_{name}__{f['name']}")
                      for f in sub["functions"]}
            for f in sub["functions"]:
                g = _rename_calls(f, rename)
                self._alg_funcs[g["name"]] = g
                self.sigs[g["name"]] = {"params": [p["type"] for p in g["params"]], "returns": g["returns"]}
            if self.module is not None:
                self.module.resolved[f"algorithm/{name}"] = {"form": form["name"], "cost": form.get("cost"),
                                                             "complexity": form.get("complexity"),
                                                             "precondition": card.get("precondition")}
            return fname
        raise CompileError(f"algorithm.{name}: no form lifts into the IR ({'; '.join(reasons)[:300]})", line,
                           self.path)


def _rename_calls(fn: dict, rename: dict) -> dict:
    import copy
    g = copy.deepcopy(fn)
    g["name"] = rename.get(g["name"], g["name"])

    def fix(e):
        if isinstance(e, list) and e:
            if e[0] == "CALL":
                e[1] = rename.get(e[1], e[1])
                for a in e[2:]:
                    fix(a)
            elif e[0] not in ("var", "int", "float", "bool"):
                for a in e[1:]:
                    fix(a)

    def walk(body):
        for s in body:
            for key in ("value", "cond", "start", "stop", "step"):
                if key in s:
                    fix(s[key])
            for key in ("then", "else", "body"):
                if key in s:
                    walk(s[key])

    walk(g["body"])
    return g


def _flatten_and(e) -> list:
    if e[0] == "bin" and e[1] == "and":
        return _flatten_and(e[2]) + _flatten_and(e[3])
    return [e]


def compile_source(text: str, ops, store=None, path: str | None = None, name: str | None = None) -> Module:
    decls = parse(text, path)
    return Compiler(ops, store, path, name).compile(decls, text)


def compile_file(path, ops, store=None, _seen: set | None = None) -> Module:
    """Compile a .card file and every module it ``use``s (same folder), merging their logic and functions."""
    p = Path(path)
    seen = _seen if _seen is not None else set()
    seen.add(p.resolve())
    mod = compile_source(p.read_text(encoding="utf-8"), ops, store, str(p))
    for dep in mod.uses:
        dp = p.parent / f"{dep}.card"
        if dp.resolve() in seen:
            continue
        if not dp.is_file():
            raise CompileError(f"use {dep}: no {dp.name} next to {p.name}", None, str(p))
        sub = compile_file(dp, ops, store, seen)
        for n, f in sub.functions.items():
            mod.functions.setdefault(n, f)
        mod.program.rules = sub.program.rules + mod.program.rules
        mod.program.facts = sub.program.facts + mod.program.facts
    problems = mod.program.check()
    if problems:
        raise CompileError("logic: " + "; ".join(problems), None, str(p))
    return mod


__all__ = ["CardSyntaxError", "CompileError", "Compiler", "Module", "compile_file", "compile_source"]
