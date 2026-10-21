"""syntax — the card language's lexer and parser: source text -> declarations (surface syntax).

One file mixes five kinds of declaration; every one of them becomes cards:

    module family                                -- optional; defaults to the file name
    use geometry                                 -- another module (same folder, or a theory card)

    parent(alice, bob).                          -- a fact ("fact" keyword optional)
    ancestor(X, Z) <- parent(X, Y), ancestor(Y, Z).      -- a rule (also ":-"); "rule name:" labels it
    never: ancestor(X, X).                       -- a constraint (must never hold)
    query ancestor(alice, Who)?                  -- printed by `cardmodel run`

    fn fib(n: Int) -> Int requires n >= 0 {      -- a function: compiles to the card IR, so to every
      var a = 0                                  -- language card (C, Rust, Go, Swift, Java, JS, TS,
      var b = 1                                  -- Ruby, Lua, Lean, Python), conformance-checked
      for i in 0 .. n { (a, b) = (b, a + b) }
      return a
    }
    fn sq(x: Int) -> Int = x * x
    factorial : Int -> Int = match n with | 0 -> 1 | k -> k * factorial(k - 1)    -- Pheros CL v0 form

    theorem add_comm(a: Int, b: Int): a + b == b + a            -- witnessed, then proved in Lean
    theorem pred_lt(n: Nat) requires n > 0: n - 1 < n

    test fib(10) == 55                           -- function tests and logic tests (provable atoms)
    card sword : item { damage: 12, tags: [steel, slash] }      -- any card, in any registry

Lexical: ``--`` and ``#`` line comments, ``(* ... *)`` block comments (CL);
newlines end declarations and statements except inside ( ) and [ ];
logic clauses run to their final ``.``. In logic, a name starting with an
upper-case letter or ``_`` is a variable and any other name is a symbol;
``_`` alone is a fresh anonymous variable.

Machine state (for hardware and CPUs written as cards):

    const LCDC = 0xFF40                          -- a compile-time integer (may read card fields:
    const DOTS = card.hardware.gb_ppu.dots_per_line      --   card.<registry>.<name>.<field>...)
    global ly: Int = 0                           -- module state, visible in every function
    array vram: Byte[0x4000]                     -- Byte (0..255, stores keep the low 8 bits) or Int
    array pal: Int[4] = card.hardware.gb_cgb.dmg_compat_palettes.bg    -- initial values from a card field
    export fn run_frame() { ... }                -- export: the host may call it / read it
    fn tick(n: Int) { cyc += n }                 -- no `-> T` and no value returned: a void function
    vram[a & 0x3FFF] = v                         -- array store (also |= &= ^= <<= >>= += -=)
    tick(4)                                      -- a call as a statement
    switch op { case 0x00 { nop() } case 1, 2 { ... } default { ... } }

Honest limits (L1): no user-defined types, strings, lists or closures in
functions (the IR's int/float/bool subset; see ROADMAP); no operator
overloading; errors stop at the first syntax error in a declaration.
"""
from __future__ import annotations

from dataclasses import dataclass, field

KEYWORDS = {"module", "use", "fn", "let", "var", "if", "elif", "else", "while", "for", "in", "by", "return",
            "break", "continue", "and", "or", "not", "true", "false", "fact", "rule", "never", "constraint",
            "query", "theorem", "law", "requires", "test", "card", "then", "match", "with", "theory", "switch",
            "case", "default", "global", "array", "const", "export"}
EXPR_KEYWORDS = {"if", "then", "else", "match", "with", "and", "or", "not", "true", "false", "in", "by", "let",
                 "var", "return", "while", "for", "elif", "break", "continue", "requires"}
AGG = ("count", "sum", "min", "max")
TYPES = {"Int": "int", "int": "int", "Float": "float", "float": "float", "Bool": "bool", "bool": "bool",
         "Nat": "nat", "nat": "nat"}
ELEM_TYPES = {"Byte": "u8", "Int": "int"}
ASSIGN_OPS = ("=", "+=", "-=", "*=", "//=", "%=", "|=", "&=", "^=", "<<=", ">>=")
OPS = sorted(["==>", "<=>", "//=", "<<=", ">>=", "..", "**", "//", "==", "!=", "<=", ">=", "<-", ":-", "->", "+=",
              "-=", "*=", "%=", "|=", "&=", "^=", "<<", ">>", "&&", "||", "+", "-", "*", "/", "%", "<", ">", "=",
              "(", ")", "{", "}", "[", "]", ",", ":", ";", ".", "?", "!", "|", "&", "^", "~", "@"],
             key=len, reverse=True)


class CardSyntaxError(ValueError):
    def __init__(self, msg: str, line: int, col: int = 0, path: str | None = None):
        self.msg, self.line, self.col, self.path = msg, line, col, path
        where = f"{path}:" if path else "line "
        super().__init__(f"{where}{line}:{col}: {msg}" if path else f"{where}{line}:{col}: {msg}")


@dataclass
class Tok:
    kind: str          # NAME NUM STR OP NL EOF
    value: object
    line: int
    col: int

    def __repr__(self) -> str:
        return f"{self.kind}:{self.value!r}@{self.line}"


def lex(text: str, path: str | None = None) -> list[Tok]:
    toks: list[Tok] = []
    i, n, line, col, depth = 0, len(text), 1, 1, 0

    def err(msg):
        raise CardSyntaxError(msg, line, col, path)

    while i < n:
        c = text[i]
        if c == "\n":
            if depth == 0:
                toks.append(Tok("NL", None, line, col))
            i += 1
            line += 1
            col = 1
            continue
        if c in " \t\r":
            i += 1
            col += 1
            continue
        if text.startswith("--", i) or c == "#":
            while i < n and text[i] != "\n":
                i += 1
            continue
        if text.startswith("(*", i):
            j = text.find("*)", i + 2)
            if j < 0:
                err("unterminated (* comment")
            line += text.count("\n", i, j)
            i = j + 2
            continue
        if c.isdigit():
            j = i
            if text.startswith(("0x", "0X"), i):
                j = i + 2
                while j < n and (text[j] in "0123456789abcdefABCDEF_"):
                    j += 1
                toks.append(Tok("NUM", int(text[i:j].replace("_", ""), 16), line, col))
            elif text.startswith(("0b", "0B"), i):
                j = i + 2
                while j < n and text[j] in "01_":
                    j += 1
                toks.append(Tok("NUM", int(text[i:j].replace("_", ""), 2), line, col))
            else:
                while j < n and (text[j].isdigit() or text[j] == "_"):
                    j += 1
                is_float = False
                if j + 1 < n and text[j] == "." and text[j + 1].isdigit():
                    is_float = True
                    j += 1
                    while j < n and (text[j].isdigit() or text[j] == "_"):
                        j += 1
                if j < n and text[j] in "eE" and (j + 1 < n and (text[j + 1].isdigit() or
                                                                 (text[j + 1] in "+-" and j + 2 < n and text[j + 2].isdigit()))):
                    is_float = True
                    j += 2
                    while j < n and text[j].isdigit():
                        j += 1
                lit = text[i:j].replace("_", "")
                toks.append(Tok("NUM", float(lit) if is_float else int(lit), line, col))
            col += j - i
            i = j
            continue
        if c.isalpha() or c == "_":
            j = i + 1
            while j < n and (text[j].isalnum() or text[j] == "_"):
                j += 1
            while j + 1 < n and text[j] == "." and (text[j + 1].isalpha() or text[j + 1] == "_"):
                j += 2                                   # a dotted card reference: op.ADD, algorithm.fibonacci
                while j < n and (text[j].isalnum() or text[j] == "_"):
                    j += 1
            toks.append(Tok("NAME", text[i:j], line, col))
            col += j - i
            i = j
            continue
        if c == '"':
            j = i + 1
            out = []
            while j < n and text[j] != '"':
                if text[j] == "\n":
                    err("newline in string")
                if text[j] == "\\" and j + 1 < n:
                    out.append({"n": "\n", "t": "\t", "r": "\r", "0": "\0", '"': '"', "\\": "\\"}.get(text[j + 1], text[j + 1]))
                    j += 2
                    continue
                out.append(text[j])
                j += 1
            if j >= n:
                err("unterminated string")
            toks.append(Tok("STR", "".join(out), line, col))
            col += j + 1 - i
            i = j + 1
            continue
        for op in OPS:
            if text.startswith(op, i):
                if op in ("(", "["):
                    depth += 1
                elif op in (")", "]"):
                    depth = max(0, depth - 1)
                toks.append(Tok("OP", op, line, col))
                i += len(op)
                col += len(op)
                break
        else:
            err(f"unexpected character {c!r}")
    toks.append(Tok("NL", None, line, col))
    toks.append(Tok("EOF", None, line, col))
    return toks


# -- declarations (surface syntax) ----------------------------------------------------------------
@dataclass
class Decl:
    kind: str                      # module use fn clause query theorem test card theory const global array
    line: int
    data: dict = field(default_factory=dict)
    path: str | None = None


class Parser:
    def __init__(self, text: str, path: str | None = None):
        self.path = path
        self.toks = lex(text, path)
        self.i = 0
        self.anon = 0

    # -- token helpers --
    def peek(self, k: int = 0) -> Tok:
        return self.toks[min(self.i + k, len(self.toks) - 1)]

    def next(self) -> Tok:
        t = self.toks[self.i]
        self.i += 1
        return t

    def at(self, kind: str, value=None, k: int = 0) -> bool:
        t = self.peek(k)
        return t.kind == kind and (value is None or t.value == value)

    def at_op(self, *ops) -> bool:
        t = self.peek()
        return t.kind == "OP" and t.value in ops

    def at_kw(self, *kws) -> bool:
        t = self.peek()
        return t.kind == "NAME" and t.value in kws

    def accept_op(self, op) -> bool:
        if self.at_op(op):
            self.i += 1
            return True
        return False

    def accept_kw(self, kw) -> bool:
        if self.at_kw(kw):
            self.i += 1
            return True
        return False

    def expect_op(self, op) -> Tok:
        if not self.at_op(op):
            self.err(f"expected {op!r}, found {self._show(self.peek())}")
        return self.next()

    def expect_kw(self, kw) -> Tok:
        if not self.at_kw(kw):
            self.err(f"expected {kw!r}, found {self._show(self.peek())}")
        return self.next()

    def expect_name(self, what: str = "a name") -> str:
        t = self.peek()
        if t.kind != "NAME":
            self.err(f"expected {what}, found {self._show(t)}")
        self.i += 1
        return t.value

    def skip_nl(self) -> None:
        while self.at("NL") or self.at_op(";"):
            self.i += 1

    def end_of_line(self) -> None:
        if self.at("EOF"):
            return
        if not (self.at("NL") or self.at_op(";")):
            self.err(f"expected end of line, found {self._show(self.peek())}")
        self.skip_nl()

    def err(self, msg: str, tok: Tok | None = None):
        t = tok or self.peek()
        raise CardSyntaxError(msg, t.line, t.col, self.path)

    @staticmethod
    def _show(t: Tok) -> str:
        if t.kind == "EOF":
            return "end of file"
        if t.kind == "NL":
            return "end of line"
        return repr(t.value)

    # -- program --
    def program(self) -> list[Decl]:
        decls = []
        self.skip_nl()
        while not self.at("EOF"):
            d = self.decl()
            d.path = self.path
            decls.append(d)
            self.skip_nl()
        return decls

    def decl(self) -> Decl:
        t = self.peek()
        line = t.line
        if t.kind == "NAME":
            kw = t.value
            if kw == "module":
                self.next()
                d = Decl("module", line, {"name": self.expect_name("a module name")})
                self.end_of_line()
                return d
            if kw == "theory":
                self.next()
                d = Decl("theory", line, {"name": self.expect_name("a theory name")})
                self.end_of_line()
                return d
            if kw == "use":
                self.next()
                names = [self.expect_name("a module name")]
                while self.accept_op(","):
                    names.append(self.expect_name("a module name"))
                self.end_of_line()
                return Decl("use", line, {"names": names})
            if kw == "export":
                self.next()
                d = self.decl()
                if d.kind not in ("fn", "global", "array"):
                    self.err("`export` goes before fn, global or array")
                d.data["export"] = True
                return d
            if kw == "fn":
                return self.fn_decl()
            if kw == "const":
                self.next()
                name = self.expect_name("a constant name")
                self.expect_op("=")
                e = self.expr(ctx="fn")
                self.end_of_line()
                return Decl("const", line, {"name": name, "expr": e})
            if kw == "global":
                self.next()
                name = self.expect_name("a global name")
                self.expect_op(":")
                typ = self.type_name()
                init = ("num", 0) if typ != "bool" else ("bool", False)
                if self.accept_op("="):
                    init = self.expr(ctx="fn")
                self.end_of_line()
                return Decl("global", line, {"name": name, "type": typ, "init": init})
            if kw == "array":
                self.next()
                name = self.expect_name("an array name")
                self.expect_op(":")
                et = self.peek()
                elem = self.expect_name("an element type (Byte, Int)")
                if elem not in ELEM_TYPES:
                    self.err(f"unknown element type {elem!r} (Byte, Int)", et)
                self.expect_op("[")
                size = self.expr(ctx="fn")
                self.expect_op("]")
                init = None
                if self.accept_op("="):
                    if not self.at_op("["):
                        init = self.expr(ctx="fn")      # a card field holding a list of integers
                    else:
                        self.expect_op("[")
                        init = []
                        self.skip_nl()
                        while not self.at_op("]"):
                            init.append(self.expr(ctx="fn"))
                            self.skip_nl()
                            if not self.accept_op(","):
                                break
                            self.skip_nl()
                        self.expect_op("]")
                self.end_of_line()
                return Decl("array", line, {"name": name, "elem": ELEM_TYPES[elem], "size": size, "init": init})
            if kw in ("fact",):
                self.next()
                return self.clause(line, label=None, fact_only=True)
            if kw == "rule":
                self.next()
                label = self.expect_name("a rule name")
                self.expect_op(":")
                return self.clause(line, label=label)
            if kw in ("never", "constraint"):
                self.next()
                label = None
                if kw == "constraint":
                    label = self.expect_name("a constraint name")
                self.expect_op(":")
                body = self.body(end=(".",))
                self.expect_op(".")
                return Decl("clause", line, {"label": label, "head": None, "body": body})
            if kw == "query":
                self.next()
                body = self.body(end=("?", "."))
                self.next()
                return Decl("query", line, {"body": body})
            if kw in ("theorem", "law"):
                return self.theorem()
            if kw == "test":
                self.next()
                e = self.expr(ctx="logic")
                self.end_of_line()
                return Decl("test", line, {"expr": e})
            if kw == "card":
                self.next()
                name = self.expect_name("a card name")
                self.expect_op(":")
                reg = self.expect_name("a registry name")
                self.skip_nl()
                value = self.value()
                if not isinstance(value, dict):
                    self.err("a card body is an object { key: value, ... }")
                self.end_of_line()
                return Decl("card", line, {"name": name, "registry": reg, "fields": value})
            if self.at_op_k(1, ":") and kw not in KEYWORDS:
                return self.cl_fn(line)
        if t.kind == "OP" and t.value == "?":
            self.next()
            body = self.body(end=(".", "?"))
            self.next()
            return Decl("query", line, {"body": body})
        if t.kind == "NAME" and (t.value[0].islower()) and t.value not in KEYWORDS - {"true", "false"}:
            return self.clause(line, label=None)
        self.err(f"unexpected {self._show(t)} at the start of a declaration")

    def at_op_k(self, k: int, op: str) -> bool:
        t = self.peek(k)
        return t.kind == "OP" and t.value == op

    # -- logic --
    def clause(self, line: int, label: str | None, fact_only: bool = False) -> Decl:
        head = self.atom()
        body = []
        if self.at_op("<-", ":-") or self.at_kw("if"):
            if fact_only:
                self.err("a fact has no body (use a rule)")
            self.next()
            body = self.body(end=(".",))
        self.expect_op(".")
        return Decl("clause", line, {"label": label, "head": head, "body": body})

    def atom(self) -> tuple:
        t = self.peek()
        pred = self.expect_name("a predicate name")
        if not (pred[0].islower() or pred[0].isdigit()):
            self.err(f"predicate {pred!r} must start with a lower-case letter (upper-case names are variables)", t)
        args = []
        if self.accept_op("("):
            self.skip_nl()
            if not self.at_op(")"):
                args.append(self.term())
                self.skip_nl()
                while self.accept_op(","):
                    self.skip_nl()
                    args.append(self.term())
                    self.skip_nl()
            self.expect_op(")")
        return ("atom", pred, args, t.line)

    def term(self) -> tuple:
        t = self.next()
        if t.kind == "NUM":
            return ("num", t.value)
        if t.kind == "STR":
            return ("sym", t.value)
        if t.kind == "OP" and t.value == "-" and self.at("NUM"):
            return ("num", -self.next().value)
        if t.kind == "NAME":
            if t.value == "_":
                self.anon += 1
                return ("var", f"_{self.anon}")
            if t.value in ("true", "false"):
                return ("sym", t.value)
            if t.value[0].isupper() or t.value[0] == "_":
                return ("var", t.value)
            if self.at_op("(") or self.at_op("+", "-", "*", "/"):
                self.err(f"atom arguments are variables or constants; bind a computed value first "
                         f"(e.g. `N1 = N + 1`)", t)
            return ("sym", t.value)
        self.err(f"expected a variable or a constant, found {self._show(t)}", t)

    def body(self, end: tuple) -> list:
        lits = []
        self.skip_nl()
        while True:
            lits.append(self.literal())
            self.skip_nl()
            if self.accept_op(","):
                self.skip_nl()
                continue
            if self.at_op(*end):
                return lits
            self.err(f"expected ',' or {' or '.join(repr(e) for e in end)} in a rule body, found "
                     f"{self._show(self.peek())}")

    def literal(self):
        line = self.peek().line
        if self.accept_kw("not"):
            return ("not", self.atom(), line)
        # aggregate: V = count { ... } / V = sum W { ... }
        if self.at("NAME") and self.at_op_k(1, "=") and self.peek(2).kind == "NAME" and self.peek(2).value in AGG \
                and (self.at_op_k(3, "{") or (self.peek(3).kind == "NAME" and self.at_op_k(4, "{"))):
            var = self.next().value
            self.next()
            fn = self.next().value
            over = None
            if self.at("NAME"):
                over = self.next().value
            self.expect_op("{")
            sub = self.body(end=("}",))
            self.expect_op("}")
            if fn != "count" and over is None:
                self.err(f"{fn} needs the variable to aggregate: {var} = {fn} V {{ ... }}")
            return ("agg", fn, var, over, sub, line)
        # an atom, a test or a binding: parse as an expression and decide
        e = self.expr(ctx="logic")
        if self.accept_op("="):
            rhs = self.expr(ctx="logic")
            return ("eq", e, rhs, line)
        if e[0] == "call" and not e[1].startswith(("op.", "@")):
            return ("atom_or_test", e, line)
        if e[0] == "name" and e[1][0].islower():
            return ("atom", e[1], [], line)
        return ("test", e, line)

    # -- functions --
    def fn_decl(self) -> Decl:
        line = self.next().line
        name = self.expect_name("a function name")
        self.expect_op("(")
        params = []
        if not self.at_op(")"):
            params.append(self.param())
            while self.accept_op(","):
                params.append(self.param())
        self.expect_op(")")
        ret = None
        if self.accept_op("->"):
            ret = self.type_name()
        requires = []
        if self.accept_kw("requires"):                   # the domain contract: verification inputs come from it
            requires.append(self.expr(ctx="fn"))
            while self.accept_op(","):
                requires.append(self.expr(ctx="fn"))
            self.skip_nl()
        if self.accept_op("="):
            self.skip_nl()
            e = self.expr(ctx="fn")
            self.end_of_line()
            body = [("return", e, line)]
        else:
            body = self.block()
            self.end_of_line()
        return Decl("fn", line, {"name": name, "params": params, "returns": ret, "body": body,
                                 "requires": requires})

    def cl_fn(self, line: int) -> Decl:
        """Pheros CL v0: ``name : T -> T = match p with | pat -> e ...`` or ``name : T -> T = (a, b) -> e``."""
        name = self.expect_name()
        self.expect_op(":")
        types = [self.type_name()]
        while self.accept_op("->"):
            types.append(self.type_name())
        self.expect_op("=")
        self.skip_nl()
        if len(types) < 2:
            self.err("a CL function type needs an arrow: name : Int -> Int = ...")
        arg_types, ret = types[:-1], types[-1]
        if self.at_kw("match"):
            self.next()
            pname = self.expect_name("the parameter matched on")
            self.expect_kw("with")
            arms = self.match_arms()
            if len(arg_types) != 1:
                self.err("`match p with` names a single parameter")
            body = [("return", ("match", ("name", pname), arms), line)]
            params = [(pname, arg_types[0])]
        else:
            pnames = []
            if self.accept_op("("):
                pnames.append(self.expect_name())
                while self.accept_op(","):
                    pnames.append(self.expect_name())
                self.expect_op(")")
            else:
                pnames.append(self.expect_name())
            self.expect_op("->")
            if len(pnames) != len(arg_types):
                self.err(f"{len(pnames)} parameter name(s) for {len(arg_types)} argument type(s)")
            body = [("return", self.expr(ctx="fn"), line)]
            params = list(zip(pnames, arg_types))
        self.end_of_line()
        return Decl("fn", line, {"name": name, "params": params, "returns": ret, "body": body, "cl": True})

    def match_arms(self):
        arms = []
        self.skip_nl()
        while self.accept_op("|"):
            pat = self.pattern()
            self.expect_op("->")
            self.skip_nl()
            arms.append((pat, self.expr(ctx="fn")))
            if self.at("NL") and self.at_op_k(1, "|"):
                self.next()
            elif self.at("NL"):
                k = 0
                while self.peek(k).kind == "NL":
                    k += 1
                if self.at_op_k(k, "|"):
                    self.i += k
        if not arms:
            self.err("match needs at least one arm: | pattern -> expr")
        return arms

    def pattern(self):
        t = self.next()
        if t.kind == "NUM":
            return ("lit", t.value)
        if t.kind == "OP" and t.value == "-" and self.at("NUM"):
            return ("lit", -self.next().value)
        if t.kind == "NAME":
            if t.value in ("true", "false"):
                return ("lit", t.value == "true")
            if t.value == "_":
                return ("wild",)
            return ("bind", t.value)
        self.err(f"bad pattern {self._show(t)}", t)

    def param(self):
        name = self.expect_name("a parameter name")
        self.expect_op(":")
        return (name, self.type_name())

    def type_name(self) -> str:
        t = self.peek()
        name = self.expect_name("a type (Int, Float, Bool, Nat)")
        if name not in TYPES:
            self.err(f"unknown type {name!r} (Int, Float, Bool, Nat)", t)
        return TYPES[name]

    def block(self) -> list:
        self.expect_op("{")
        stmts = []
        self.skip_nl()
        while not self.at_op("}"):
            stmts.append(self.stmt())
            self.skip_nl()
        self.expect_op("}")
        return stmts

    def stmt(self):
        t = self.peek()
        line = t.line
        if self.at_kw("let", "var"):
            self.next()
            name = self.expect_name("a variable name")
            typ = None
            if self.accept_op(":"):
                typ = self.type_name()
            self.expect_op("=")
            e = self.expr(ctx="fn")
            self._stmt_end()
            return ("let", name, typ, e, line)
        if self.at_kw("if"):
            self.next()
            branches = [(self.expr(ctx="fn"), self.block())]
            other = []
            while True:
                k = 0
                while self.peek(k).kind == "NL":
                    k += 1
                nt = self.peek(k)
                if nt.kind == "NAME" and nt.value in ("elif", "else"):
                    self.i += k
                    if self.accept_kw("elif"):
                        branches.append((self.expr(ctx="fn"), self.block()))
                        continue
                    self.next()
                    if self.at_kw("if"):
                        self.next()
                        branches.append((self.expr(ctx="fn"), self.block()))
                        continue
                    other = self.block()
                break
            self._stmt_end()
            return ("if", branches, other, line)
        if self.at_kw("while"):
            self.next()
            cond = self.expr(ctx="fn")
            body = self.block()
            self._stmt_end()
            return ("while", cond, body, line)
        if self.at_kw("for"):
            self.next()
            var = self.expect_name("a loop variable")
            self.expect_kw("in")
            start = self.expr(ctx="fn")
            self.expect_op("..")
            stop = self.expr(ctx="fn")
            step = ("num", 1)
            if self.accept_kw("by"):
                step = self.expr(ctx="fn")
            body = self.block()
            self._stmt_end()
            return ("for", var, start, stop, step, body, line)
        if self.at_kw("return"):
            self.next()
            if self.at("NL") or self.at_op("}"):
                self._stmt_end()
                return ("return", None, line)
            e = self.expr(ctx="fn")
            self._stmt_end()
            return ("return", e, line)
        if self.at_kw("switch"):
            self.next()
            value = self.expr(ctx="fn")
            self.expect_op("{")
            cases, default = [], None
            self.skip_nl()
            while not self.at_op("}"):
                ct = self.peek()
                if self.accept_kw("case"):
                    vals = [self.expr(ctx="fn")]
                    while self.accept_op(","):
                        vals.append(self.expr(ctx="fn"))
                    cases.append((vals, self.block(), ct.line))
                elif self.accept_kw("default"):
                    if default is not None:
                        self.err("a switch has one default", ct)
                    default = self.block()
                else:
                    self.err(f"expected `case` or `default` in a switch, found {self._show(ct)}", ct)
                self.skip_nl()
            self.expect_op("}")
            self._stmt_end()
            return ("switch", value, cases, default, line)
        if self.at_kw("break", "continue"):
            k = self.next().value
            self._stmt_end()
            return (k, line)
        if self.at_op("("):
            save = self.i
            self.next()
            names = []
            try:
                names.append(self.expect_name())
                while self.accept_op(","):
                    names.append(self.expect_name())
                self.expect_op(")")
                self.expect_op("=")
            except CardSyntaxError:
                self.i = save
                self.err("a statement starting with '(' must be a parallel assignment: (a, b) = (b, a + b)")
            self.expect_op("(")
            exprs = [self.expr(ctx="fn")]
            while self.accept_op(","):
                exprs.append(self.expr(ctx="fn"))
            self.expect_op(")")
            if len(exprs) != len(names):
                self.err(f"{len(names)} targets but {len(exprs)} values")
            self._stmt_end()
            return ("passign", names, exprs, line)
        if t.kind == "NAME" and t.value not in KEYWORDS:
            if self.at_op_k(1, "("):
                e = self.expr(ctx="fn")
                if e[0] != "call":
                    self.err("a statement that starts with a call must be just the call")
                self._stmt_end()
                return ("call", e, line)
            name = self.next().value
            if self.accept_op("["):
                idx = self.expr(ctx="fn")
                self.expect_op("]")
                for op in ASSIGN_OPS:
                    if self.accept_op(op):
                        e = self.expr(ctx="fn")
                        self._stmt_end()
                        return ("store", name, idx, op, e, line)
                self.err(f"expected an assignment to {name}[...]")
            for op in ASSIGN_OPS:
                if self.accept_op(op):
                    e = self.expr(ctx="fn")
                    self._stmt_end()
                    return ("assign", name, op, e, line)
            self.err(f"expected an assignment to {name!r}")
        self.err(f"unexpected {self._show(t)} at the start of a statement")

    def _stmt_end(self):
        if self.at_op("}"):
            return
        self.end_of_line()

    # -- theorems --
    def theorem(self) -> Decl:
        line = self.next().line
        name = self.expect_name("a theorem name")
        params = []
        if self.accept_op("("):
            if not self.at_op(")"):
                params.append(self.param())
                while self.accept_op(","):
                    params.append(self.param())
            self.expect_op(")")
        hyps = []
        if self.accept_kw("requires"):
            hyps.append(self.expr(ctx="math"))
            while self.accept_op(","):
                hyps.append(self.expr(ctx="math"))
        self.expect_op(":")
        self.skip_nl()
        concl = self.expr(ctx="math")
        self.end_of_line()
        return Decl("theorem", line, {"name": name, "params": params, "hyps": hyps, "concl": concl})

    # -- card values (JSON-like) --
    def value(self):
        self.skip_nl()
        t = self.peek()
        if self.accept_op("{"):
            out = {}
            self.skip_nl()
            while not self.at_op("}"):
                kt = self.next()
                if kt.kind not in ("NAME", "STR"):
                    self.err(f"expected a key, found {self._show(kt)}", kt)
                self.expect_op(":")
                out[kt.value] = self.value()
                self.skip_nl()
                if not self.accept_op(","):
                    self.skip_nl()
                    if not self.at_op("}"):
                        self.err("expected ',' or '}' in an object")
                self.skip_nl()
            self.expect_op("}")
            return out
        if self.accept_op("["):
            out = []
            self.skip_nl()
            while not self.at_op("]"):
                out.append(self.value())
                self.skip_nl()
                if not self.accept_op(","):
                    break
                self.skip_nl()
            self.expect_op("]")
            return out
        if self.accept_op("-"):
            n = self.next()
            if n.kind != "NUM":
                self.err("expected a number after '-'", n)
            return -n.value
        self.next()
        if t.kind in ("NUM", "STR"):
            return t.value
        if t.kind == "NAME":
            return {"true": True, "false": False, "null": None}.get(t.value, t.value)
        self.err(f"expected a value, found {self._show(t)}", t)

    # -- expressions --
    # ctx: "fn" (names are variables), "logic" (Upper = variable, lower = symbol), "math" (theorem statements)
    def expr(self, ctx: str):
        if self.at_kw("if"):
            self.next()
            c = self.expr(ctx)
            self.skip_nl()
            self.expect_kw("then")
            self.skip_nl()
            a = self.expr(ctx)
            self.skip_nl()
            self.expect_kw("else")
            self.skip_nl()
            b = self.expr(ctx)
            return ("if", c, a, b)
        if self.at_kw("match"):
            self.next()
            scrut = self.expr(ctx)
            self.expect_kw("with")
            return ("match", scrut, self.match_arms())
        return self.implication(ctx)

    def implication(self, ctx):
        left = self.disj(ctx)
        if ctx == "math" and self.at_op("==>", "<=>"):
            op = self.next().value
            right = self.implication(ctx)
            return ("bin", op, left, right)
        return left

    def disj(self, ctx):
        left = self.conj(ctx)
        while self.at_kw("or") or self.at_op("||"):
            self.next()
            left = ("bin", "or", left, self.conj(ctx))
        return left

    def conj(self, ctx):
        left = self.neg(ctx)
        while self.at_kw("and") or self.at_op("&&"):
            self.next()
            left = ("bin", "and", left, self.neg(ctx))
        return left

    def neg(self, ctx):
        if self.at_kw("not") or self.at_op("!"):
            self.next()
            return ("un", "not", self.neg(ctx))
        return self.comparison(ctx)

    def comparison(self, ctx):
        left = self.bitor(ctx)
        parts = []
        while self.at_op("==", "!=", "<", "<=", ">", ">="):
            op = self.next().value
            right = self.bitor(ctx)
            parts.append(("bin", op, left, right))
            left = right
        if not parts:
            return left
        e = parts[0]
        for p in parts[1:]:
            e = ("bin", "and", e, p)
        return e

    def bitor(self, ctx):
        left = self.bitxor(ctx)
        while self.at_op("|") and ctx != "logic_term":
            self.next()
            left = ("bin", "|", left, self.bitxor(ctx))
        return left

    def bitxor(self, ctx):
        left = self.bitand(ctx)
        while self.at_op("^"):
            self.next()
            left = ("bin", "^", left, self.bitand(ctx))
        return left

    def bitand(self, ctx):
        left = self.shift(ctx)
        while self.at_op("&"):
            self.next()
            left = ("bin", "&", left, self.shift(ctx))
        return left

    def shift(self, ctx):
        left = self.additive(ctx)
        while self.at_op("<<", ">>"):
            op = self.next().value
            left = ("bin", op, left, self.additive(ctx))
        return left

    def additive(self, ctx):
        left = self.multiplicative(ctx)
        while self.at_op("+", "-"):
            op = self.next().value
            left = ("bin", op, left, self.multiplicative(ctx))
        return left

    def multiplicative(self, ctx):
        left = self.unary(ctx)
        while self.at_op("*", "/", "//", "%"):
            op = self.next().value
            left = ("bin", op, left, self.unary(ctx))
        return left

    def unary(self, ctx):
        if self.at_op("-"):
            self.next()
            x = self.unary(ctx)
            if x[0] == "num":
                return ("num", -x[1])
            return ("un", "-", x)
        if self.at_op("~"):
            self.next()
            return ("un", "~", self.unary(ctx))
        if self.at_op("+"):
            self.next()
            return self.unary(ctx)
        return self.power(ctx)

    def power(self, ctx):
        base = self.postfix(ctx)
        if self.at_op("**"):
            self.next()
            return ("bin", "**", base, self.unary(ctx))
        return base

    def postfix(self, ctx):
        t = self.peek()
        if t.kind == "NUM":
            self.next()
            return ("num", t.value)
        if t.kind == "STR":
            self.next()
            return ("str", t.value)
        if self.accept_op("("):
            self.skip_nl()
            e = self.expr(ctx)
            self.skip_nl()
            self.expect_op(")")
            return e
        if self.at_op("@"):
            self.next()
            name = self.expect_name("an op card name")
            return self.call_args(f"op.{name}", ctx, t)
        if t.kind == "NAME":
            if t.value in ("true", "false"):
                self.next()
                return ("bool", t.value == "true")
            if t.value in EXPR_KEYWORDS:
                self.err(f"unexpected keyword {t.value!r} in an expression", t)
            self.next()
            name = t.value
            if self.at_op("("):
                return self.call_args(name, ctx, t)
            if "." in name:
                return ("ref", name)
            if ctx == "fn" and self.at_op("["):
                self.next()
                idx = self.expr(ctx)
                self.expect_op("]")
                return ("index", name, idx)
            return ("name", name)
        self.err(f"expected an expression, found {self._show(t)}", t)

    def call_args(self, name, ctx, tok):
        self.expect_op("(")
        args = []
        self.skip_nl()
        if not self.at_op(")"):
            args.append(self.expr(ctx))
            self.skip_nl()
            while self.accept_op(","):
                self.skip_nl()
                args.append(self.expr(ctx))
                self.skip_nl()
        self.expect_op(")")
        return ("call", name, args, tok.line)


def parse(text: str, path: str | None = None) -> list[Decl]:
    return Parser(text, path).program()


def parse_body(text: str) -> list:
    """A rule body / query on its own: ``ancestor(alice, X), X != bob``."""
    p = Parser(text.strip().rstrip(".?") + " .")
    lits = p.body(end=(".",))
    return lits


__all__ = ["AGG", "ASSIGN_OPS", "CardSyntaxError", "Decl", "ELEM_TYPES", "KEYWORDS", "Parser", "TYPES", "lex",
           "parse", "parse_body"]
