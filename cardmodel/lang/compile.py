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

Machine state: ``const`` (compile-time integers, which may read card fields
``card.<registry>.<name>.<field>``), ``global`` and ``array`` declarations (an
array's initial values may be a card field holding a list of integers),
void functions, array stores, call statements and ``switch``. After the
functions compile, an evaluation-order pass gives every effectful call its own
statement, in the left-to-right order Python uses (earlier operands that read
state are saved first). The remaining expressions only read state, so C, which
leaves operand order unspecified, computes the same thing as Python and the
reference interpreter.

Honest limits (L1): no strings, lists or user types inside functions; the
``Nat`` type is a domain annotation (an int >= 0), not truncating arithmetic;
a ``match`` substitutes the scrutinee into each arm (it is re-evaluated,
which is fine for pure expressions); an effectful call may not sit in the lazy
operand of ``and``/``or``/``if-then-else`` (write an ``if`` statement).
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
AUG = {"+=": "+", "-=": "-", "*=": "*", "//=": "//", "%=": "%", "|=": "|", "&=": "&", "^=": "^", "<<=": "<<",
       ">>=": ">>"}


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
    consts: dict = field(default_factory=dict)           # name -> int
    globals: list = field(default_factory=list)          # [{name, type, init, export}]
    arrays: list = field(default_factory=list)           # [{name, elem, size, init, export}]

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
        out = {"entry": entry, "functions": fns}
        if self.globals:
            out["globals"] = list(self.globals)
        if self.arrays:
            out["arrays"] = list(self.arrays)
        return out

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
        for key in ("then", "else", "body", "default"):
            if key in s:
                yield from _walk_stmts(s[key])
        for case in s.get("cases") or ():
            yield from _walk_stmts(case["body"])


def _walk_exprs(s):
    for key in ("value", "cond", "start", "stop", "step", "index"):
        e = s.get(key)
        if isinstance(e, list):
            stack = [e]
            while stack:
                x = stack.pop()
                if isinstance(x, list) and x:
                    yield x
                    if x[0] not in ("var", "int", "float", "bool"):
                        stack.extend(a for a in x[(2 if x[0] in ("CALL", "LOAD") else 1):] if isinstance(a, list))


# -- functions -------------------------------------------------------------------------------------
class FnCompiler:
    def __init__(self, decl: Decl, ops: dict[str, OpSpec], sigs: dict, mod: "Compiler"):
        self.d = decl.data
        self.line = decl.line
        self.path = decl.path or mod.path
        self.ops = ops
        self.sigs = sigs
        self.mod = mod
        self.env: dict[str, str] = {}
        self.locals: dict[str, str] = {}
        self.tmp = 0
        self.return_types: set[str] = set()

    def err(self, msg, line=None):
        raise CompileError(f"fn {self.d['name']}: {msg}", line or self.line, self.path)

    def compile(self) -> dict:
        params = []
        self.void = self.sigs.get(self.d["name"], {}).get("returns") == "void"
        for pname, ptype in self.d["params"]:
            t = "int" if ptype == "nat" else ptype
            if pname in self.mod.global_types or pname in self.mod.array_specs:
                self.err(f"parameter {pname!r} shadows a global")
            params.append({"name": pname, "type": t})
            self.env[pname] = t
        requires = [self.cond(r, self.line) for r in self.d.get("requires") or []]
        body = self.block(self.d["body"])
        if self.void:
            fn = {"name": self.d["name"], "params": params, "returns": "void", "locals": dict(self.locals),
                  "body": body}
            if self.d.get("export"):
                fn["export"] = True
            return fn
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
        if self.d.get("export"):
            fn["export"] = True
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
        if name in self.mod.global_types or name in self.mod.array_specs or name in self.mod.consts:
            self.err(f"{name!r} shadows a global or constant (pick another name)", line)
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
            if name not in self.env and name not in self.mod.global_types:
                if name in self.mod.consts:
                    self.err(f"{name!r} is a constant", line)
                self.err(f"assignment to undeclared {name!r} (use `let {name} = ...`)", line)
            if op != "=":
                e = ("bin", AUG[op], ("name", name), e)
            ir, t = self.expr(e, line)
            want = self.env.get(name) or self.mod.global_types[name]
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
        if k == "store":
            _, name, idx, op, e, line = s
            if name not in self.mod.array_specs:
                self.err(f"{name!r} is not an array", line)
            iir, it = self.expr(idx, line)
            if it != "int":
                self.err(f"an array index must be Int, found {it}", line)
            out = []
            if op != "=":
                if iir[0] not in ("int", "var") or iir[0] == "var" and iir[1] not in self.env:
                    tmp = self.fresh("idx", "int")
                    out.append({"k": "assign", "target": tmp, "value": iir})
                    iir = ["var", tmp]
                vir, vt = self.expr(e, line)
                if vt != "int":
                    self.err(f"array elements are Int, assigned {vt}", line)
                vir, _ = self.apply(BIN[AUG[op]], [(["LOAD", name, iir], "int"), (vir, "int")], line)
            else:
                vir, vt = self.expr(e, line)
                if vt != "int":
                    self.err(f"array elements are Int, assigned {vt}", line)
            out.append({"k": "store", "array": name, "index": iir, "value": vir})
            return out
        if k == "call":
            _, e, line = s
            ir, t = self.call(e, line, statement=True)
            return [{"k": "do", "value": ir}]
        if k == "switch":
            _, value, cases, default, line = s
            vir, vt = self.expr(value, line)
            if vt != "int":
                self.err(f"switch needs an Int, found {vt}", line)
            seen: set = set()
            out_cases = []
            for vals, blk, cline in cases:
                match = []
                for v in vals:
                    c = self.mod.const_eval(v, cline)
                    if c in seen:
                        self.err(f"case {c} appears twice", cline)
                    seen.add(c)
                    match.append(c)
                body = self.block(blk)
                if any(x["k"] == "break" for x in _shallow(body)):
                    self.err("`break` inside a switch case (it would leave the switch in C); restructure", cline)
                out_cases.append({"match": match, "body": body})
            node = {"k": "switch", "value": vir, "cases": out_cases}
            if default is not None:
                node["default"] = self.block(default)
                if any(x["k"] == "break" for x in _shallow(node["default"])):
                    self.err("`break` inside a switch default; restructure", line)
            return [node]
        if k == "return":
            _, e, line = s
            if e is None:
                if not self.void:
                    self.err("`return` without a value in a function that returns one", line)
                return [{"k": "return"}]
            if self.void:
                self.err("a void function returns no value (declare -> Type)", line)
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
            if e[1] in self.env:
                return ["var", e[1]], self.env[e[1]]
            if e[1] in self.mod.global_types:
                return ["var", e[1]], self.mod.global_types[e[1]]
            if e[1] in self.mod.consts:
                return ["int", self.mod.consts[e[1]]], "int"
            if e[1] in self.mod.array_specs:
                self.err(f"array {e[1]!r} is not a value (index it: {e[1]}[i])", line)
            self.err(f"unknown name {e[1]!r}", line)
        if k == "index":
            if e[1] not in self.mod.array_specs:
                self.err(f"{e[1]!r} is not an array", line)
            iir, it = self.expr(e[2], line)
            if it != "int":
                self.err(f"an array index must be Int, found {it}", line)
            return ["LOAD", e[1], iir], "int"
        if k == "ref":
            if e[1].startswith("card."):
                return ["int", self.mod.card_value(e[1], line)], "int"
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

    def call(self, e, line, statement: bool = False):
        _, name, args, _ln = e
        if name in self.sigs and self.sigs[name].get("returns") == "void" and not statement:
            self.err(f"{name}() returns no value; call it as a statement", line)
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
    def __init__(self, ops, store=None, path: str | None = None, name: str | None = None, externs: dict | None = None):
        self.externs = dict(externs or {})            # name -> IR function compiled elsewhere (e.g. on a card)
        self.ops = ops
        self.store = store
        self.path = path
        self.path_label = Path(path).name if path else "<source>"
        self.name = name or (Path(path).stem if path else "main")
        self.sigs: dict = {}
        self.module: Module | None = None
        self._alg_funcs: dict = {}
        self.consts: dict = {}
        self.global_types: dict = {}
        self.array_specs: dict = {}

    # -- machine state ---------------------------------------------------------------------------
    def card_value(self, ref: str, line) -> int:
        """``card.<registry>.<name>.<field>...`` -> the integer stored there (a compile-time constant)."""
        v = self.card_field(ref, line)
        if isinstance(v, bool) or not isinstance(v, int):
            raise CompileError(f"{ref} is {v!r}, not an integer", line, self.path)
        return v

    def card_list(self, e, line) -> list:
        """An array's initial values from ``card.<registry>.<name>.<field>...``: a list of integers there."""
        if e[0] != "ref" or not e[1].startswith("card."):
            raise CompileError("an array's initial values: [v, ...] or card.<registry>.<name>.<field>", line,
                               self.path)
        v = self.card_field(e[1], line)
        if not isinstance(v, list) or any(isinstance(x, bool) or not isinstance(x, int) for x in v):
            raise CompileError(f"{e[1]} is {v!r}, not a list of integers", line, self.path)
        return list(v)

    def card_field(self, ref: str, line):
        parts = ref.split(".")
        if len(parts) < 4:
            raise CompileError(f"{ref}: write card.<registry>.<name>.<field>", line, self.path)
        if self.store is None:
            raise CompileError(f"{ref}: no card store to read", line, self.path)
        card = self.store.get(f"{parts[1]}/{parts[2]}")
        if card is None:
            raise CompileError(f"{ref}: no card {parts[1]}/{parts[2]}", line, self.path)
        v = card
        for key in parts[3:]:
            if not isinstance(v, dict) or key not in v:
                raise CompileError(f"{ref}: the card has no field {key!r}", line, self.path)
            v = v[key]
        return v

    def const_eval(self, e, line) -> int:
        k = e[0]
        if k == "num":
            if isinstance(e[1], float):
                raise CompileError("constants are integers", line, self.path)
            return e[1]
        if k == "bool":
            return int(e[1])
        if k == "name":
            if e[1] in self.consts:
                return self.consts[e[1]]
            raise CompileError(f"{e[1]!r} is not a constant", line, self.path)
        if k == "ref" and e[1].startswith("card."):
            return self.card_value(e[1], line)
        if k == "un":
            x = self.const_eval(e[2], line)
            return {"-": -x, "~": ~x, "not": int(not x)}[e[1]]
        if k == "bin" and e[1] in ("+", "-", "*", "//", "%", "&", "|", "^", "<<", ">>", "**", "==", "!=", "<", "<=",
                                   ">", ">=", "and", "or"):
            a, b = self.const_eval(e[2], line), self.const_eval(e[3], line)
            import operator as o
            f = {"+": o.add, "-": o.sub, "*": o.mul, "//": o.floordiv, "%": o.mod, "&": o.and_, "|": o.or_,
                 "^": o.xor, "<<": o.lshift, ">>": o.rshift, "**": o.pow, "==": o.eq, "!=": o.ne, "<": o.lt,
                 "<=": o.le, ">": o.gt, ">=": o.ge, "and": lambda x, y: x and y, "or": lambda x, y: x or y}[e[1]]
            return int(f(a, b))
        if k == "if":
            return self.const_eval(e[2], line) if self.const_eval(e[1], line) else self.const_eval(e[3], line)
        if k == "call" and e[1] in ("min", "max", "abs") and e[2]:
            vals = [self.const_eval(a, line) for a in e[2]]
            return {"min": min, "max": max, "abs": lambda *v: abs(v[0])}[e[1]](*vals)
        raise CompileError("not a constant expression", line, self.path)

    def state_decls(self, decls: list[Decl], mod: Module) -> None:
        taken: dict = {}
        for d in decls:
            if d.kind not in ("const", "global", "array"):
                continue
            name = d.data["name"]
            path = d.path or self.path
            if name in taken:
                raise CompileError(f"{name!r} is declared twice (also line {taken[name]})", d.line, path)
            taken[name] = d.line
            if d.kind == "const":
                self.consts[name] = self.const_eval(d.data["expr"], d.line)
            elif d.kind == "global":
                typ = "int" if d.data["type"] == "nat" else d.data["type"]
                if typ not in ("int", "bool"):
                    raise CompileError(f"global {name}: Int or Bool", d.line, path)
                init = self.const_eval(d.data["init"], d.line)
                self.global_types[name] = typ
                g = {"name": name, "type": typ, "init": bool(init) if typ == "bool" else init}
                if d.data.get("export"):
                    g["export"] = True
                mod.globals.append(g)
            else:
                size = self.const_eval(d.data["size"], d.line)
                if size <= 0:
                    raise CompileError(f"array {name}: size must be positive", d.line, path)
                a = {"name": name, "elem": d.data["elem"], "size": size}
                if d.data.get("init") is not None:
                    init = d.data["init"]
                    vals = ([self.const_eval(v, d.line) for v in init] if isinstance(init, list)
                            else self.card_list(init, d.line))
                    if len(vals) > size:
                        raise CompileError(f"array {name}: {len(vals)} initial values for size {size}", d.line, path)
                    a["init"] = vals
                if d.data.get("export"):
                    a["export"] = True
                self.array_specs[name] = a
                mod.arrays.append(a)
        mod.consts = dict(self.consts)

    def compile(self, decls: list[Decl], text: str = "") -> Module:
        mod = Module(self.name, self.path, hashlib.sha256(text.encode()).hexdigest()[:12])
        self.module = mod
        for d in decls:
            if d.kind == "module":
                self.name = mod.name = d.data["name"]
        mod.program.name = mod.name
        self.state_decls(decls, mod)
        fn_decls = [d for d in decls if d.kind == "fn"]
        names = [d.data["name"] for d in fn_decls]
        dup = sorted({n for n in names if names.count(n) > 1})
        if dup:
            raise CompileError(f"function(s) defined twice: {', '.join(dup)}", None, self.path)
        for name, fn in self.externs.items():
            self.sigs[name] = {"params": [p["type"] for p in fn["params"]], "returns": fn["returns"]}
        for d in fn_decls:
            r = d.data.get("returns")
            if r is None and not d.data.get("cl") and not _returns_value(d.data["body"]):
                r = "void"
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
        import copy
        for name, fn in self.externs.items():
            if name not in mod.functions:
                mod.functions[name] = copy.deepcopy(fn)
        if mod.globals or mod.arrays:
            order_effects(mod.functions, set(self.global_types), self.ops, self.path)
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
        forms = [f for f in card.get("forms") or [] if f.get("runnable") and f.get("lang", "python") == "python"
                 and f.get("code")]
        # prefer forms valid everywhere, then the card's own domain; never prefer a form the card marks suboptimal
        forms.sort(key=lambda f: (f.get("domain", "any") != "any", f.get("role") == "suboptimal",
                                  f.get("cost", 1e9), f["name"]))
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
                                                             "domain": form.get("domain", "any"),
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


def _returns_value(body) -> bool:
    """Does a surface-syntax body contain ``return <expr>`` anywhere?"""
    for st in body:
        k = st[0]
        if k == "return" and st[1] is not None:
            return True
        if k == "if" and (any(_returns_value(b) for _, b in st[1]) or _returns_value(st[2] or [])):
            return True
        if k in ("while",) and _returns_value(st[2]):
            return True
        if k == "for" and _returns_value(st[5]):
            return True
        if k == "switch" and (any(_returns_value(b) for _, b, _ in st[2]) or _returns_value(st[3] or [])):
            return True
    return False


def _shallow(body):
    """Statements of an IR body, descending into if/else but not into loops (where `break` changes meaning)."""
    for st in body:
        yield st
        if st["k"] == "if":
            yield from _shallow(st.get("then") or [])
            yield from _shallow(st.get("else") or [])


# -- evaluation order: effectful calls get their own statements -----------------------------------
def _effects(functions: dict, global_names: set) -> tuple[set, set]:
    """(functions that change state, functions that read state), transitively over the call graph."""
    writes, reads, calls = set(), set(), {}
    for name, fn in functions.items():
        local = {p["name"] for p in fn["params"]} | set(fn.get("locals") or {})
        cs = set()
        for st in _walk_stmts(fn["body"]):
            if st["k"] == "store" or (st["k"] == "assign" and st["target"] not in local
                                      and st["target"] in global_names) or \
                    (st["k"] == "for_range" and st["var"] in global_names and st["var"] not in local):
                writes.add(name)
            for e in _walk_exprs(st):
                if e[0] == "CALL":
                    cs.add(e[1])
                elif e[0] == "LOAD" or (e[0] == "var" and e[1] in global_names and e[1] not in local):
                    reads.add(name)
        calls[name] = cs
    changed = True
    while changed:
        changed = False
        for name, cs in calls.items():
            if name not in writes and cs & writes:
                writes.add(name)
                changed = True
            if name not in reads and cs & (reads | writes):
                reads.add(name)
                changed = True
    return writes, reads


def _expr_type(e, types: dict, functions: dict, ops) -> str:
    head = e[0]
    if head in ("int", "float", "bool"):
        return head
    if head == "var":
        return types.get(e[1], "int")
    if head == "LOAD":
        return "int"
    if head == "CALL":
        return functions[e[1]]["returns"] if e[1] in functions else "int"
    if head in ("AND", "OR", "NOT"):
        return "bool"
    if head == "IF_EXPR":
        return _expr_type(e[2], types, functions, ops)
    spec = ops.get(head)
    args = [_expr_type(a, types, functions, ops) for a in e[1:]]
    rt = spec.result_type(args) if spec else None
    return rt or "int"


def order_effects(functions: dict, global_names: set, ops, path=None) -> None:
    """Rewrite every function (in place) so each effectful call is its own statement, in Python's order."""
    writes, reads = _effects(functions, global_names)

    for fname, fn in functions.items():
        local = {p["name"] for p in fn["params"]} | set(fn.get("locals") or {})
        types = {p["name"]: p["type"] for p in fn["params"]}
        types.update(fn.get("locals") or {})
        counter = [0]

        def fresh(t):
            counter[0] += 1
            n = f"cm_ev{counter[0]}"
            fn.setdefault("locals", {})[n] = t
            types[n] = t
            local.add(n)
            return n

        def impure(e) -> bool:
            return any(isinstance(x, list) and x and x[0] == "CALL" and x[1] in writes for x in _iter(e))

        def reads_state(e) -> bool:
            for x in _iter(e):
                if x[0] == "LOAD" or (x[0] == "var" and x[1] in global_names and x[1] not in local):
                    return True
                if x[0] == "CALL" and (x[1] in reads or x[1] in writes):
                    return True
            return False

        def anf(e):
            head = e[0]
            if head in ("var", "int", "float", "bool"):
                return [], e
            if head == "CALL":
                pre, args = seq(e[2:])
                call = ["CALL", e[1], *args]
                if e[1] in writes:
                    t = fresh(functions[e[1]]["returns"] if e[1] in functions else "int")
                    if t == "void" or functions.get(e[1], {}).get("returns") == "void":
                        raise CompileError(f"{fname}: {e[1]}() returns no value", None, path)
                    pre.append({"k": "assign", "target": t, "value": call})
                    return pre, ["var", t]
                return pre, call
            if head in ("AND", "OR"):
                pre, a = anf(e[1])
                if impure(e[2]):
                    raise CompileError(f"{fname}: an effectful call in the right operand of and/or; use an if "
                                       "statement", None, path)
                return pre, [head, a, e[2]]
            if head == "IF_EXPR":
                pre, c = anf(e[1])
                if impure(e[2]) or impure(e[3]):
                    raise CompileError(f"{fname}: an effectful call inside if-then-else; use an if statement",
                                       None, path)
                return pre, [head, c, e[2], e[3]]
            if head == "LOAD":
                pre, (i,) = seq([e[2]])
                return pre, ["LOAD", e[1], i]
            pre, args = seq(e[1:])
            return pre, [head, *args]

        def seq(items):
            pre, out = [], []
            for it in items:
                p, x = anf(it)
                if p:
                    for j, o in enumerate(out):
                        if reads_state(o):
                            t = fresh(_expr_type(o, types, functions, ops))
                            pre.append({"k": "assign", "target": t, "value": o})
                            out[j] = ["var", t]
                    pre.extend(p)
                out.append(x)
            return pre, out

        def top(e):
            """The whole right-hand side: an effectful call may stay where it is (its arguments are ordered)."""
            if e[0] == "CALL":
                pre, args = seq(e[2:])
                return pre, ["CALL", e[1], *args]
            return anf(e)

        def block(body):
            out = []
            for st in body:
                k = st["k"]
                if k == "assign":
                    pre, v = top(st["value"])
                    out += pre
                    out.append({**st, "value": v})
                elif k == "store":
                    pre, (i, v) = seq([st["index"], st["value"]])
                    out += pre
                    out.append({**st, "index": i, "value": v})
                elif k == "do":
                    call = st["value"]
                    pre, args = seq(call[2:])
                    out += pre
                    out.append({"k": "do", "value": ["CALL", call[1], *args]})
                elif k == "return":
                    if "value" in st:
                        pre, v = top(st["value"])
                        out += pre
                        out.append({**st, "value": v})
                    else:
                        out.append(st)
                elif k == "if":
                    pre, c = anf(st["cond"])
                    out += pre
                    out.append({**st, "cond": c, "then": block(st.get("then") or []),
                                "else": block(st.get("else") or [])})
                elif k == "while":
                    pre, c = anf(st["cond"])
                    if pre:
                        body2 = pre + [{"k": "if", "cond": ["NOT", c], "then": [{"k": "break"}], "else": []}] + \
                            block(st["body"])
                        out.append({"k": "while", "cond": ["bool", True], "body": body2})
                    else:
                        out.append({**st, "body": block(st["body"])})
                elif k == "for_range":
                    pre, (a, b) = seq([st["start"], st["stop"]])
                    out += pre
                    out.append({**st, "start": a, "stop": b, "body": block(st["body"])})
                elif k == "switch":
                    pre, v = anf(st["value"])
                    out += pre
                    node = {**st, "value": v, "cases": [{**c, "body": block(c["body"])} for c in st["cases"]]}
                    if "default" in st:
                        node["default"] = block(st["default"])
                    out.append(node)
                else:
                    out.append(st)
            return out

        fn["body"] = block(fn["body"])


def _iter(e):
    if isinstance(e, list) and e:
        yield e
        if e[0] not in ("var", "int", "float", "bool"):
            for a in e[(2 if e[0] in ("CALL", "LOAD") else 1):]:
                yield from _iter(a)


def _flatten_and(e) -> list:
    if e[0] == "bin" and e[1] == "and":
        return _flatten_and(e[2]) + _flatten_and(e[3])
    return [e]


def compile_source(text: str, ops, store=None, path: str | None = None, name: str | None = None) -> Module:
    decls = parse(text, path)
    return Compiler(ops, store, path, name).compile(decls, text)


def compile_sources(sources: list[tuple[str, str]], ops, store=None, name: str = "machine",
                    externs: dict | None = None) -> Module:
    """Several card-language sources as ONE module: shared constants, globals, arrays and functions (a machine
    whose pieces live on different cards). ``sources`` is [(text, path label), ...]; ``externs`` are IR functions
    compiled elsewhere (instruction cards) that the sources may call."""
    decls = []
    for text, path in sources:
        decls += [d for d in parse(text, path) if d.kind != "module"]
    return Compiler(ops, store, None, name, externs).compile(decls, "\n".join(t for t, _ in sources))


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


__all__ = ["CardSyntaxError", "CompileError", "Compiler", "Module", "compile_file", "compile_source",
           "compile_sources", "order_effects"]
