"""lean_import — Lean theorems as cards: import, prove faithfulness, witness, re-prove ("redefine").

For each ``theorem`` in a Lean file (Lean's own core library included) whose statement is in the
arithmetic fragment below, ``import_file``:

1. parses the statement into a theorem card with ``lean`` semantics -- Lean's operators keep Lean's
   meaning: truncated ``Nat`` subtraction, Euclidean ``Int`` division with ``x / 0 = 0`` and
   ``x % 0 = x``, and coercions inserted at the leaves of an operator tree exactly as Lean's ``binop%``
   elaborator does (so ``(n - m : Int)`` is integer subtraction of ``↑n`` and ``↑m``);
2. renders the card back to Lean and lets the kernel check ``example : <our reading> := @Original``
   (faithfulness: only a statement Lean accepts as the same proposition is kept);
3. witnesses it numerically under those semantics (a counterexample to a Lean-proved statement would be a
   bug in the card semantics, so this checks the op cards against Lean);
4. tries the card model's own tactic portfolio on it without the original proof (``reproved_by``).

Fragment: binders over ``Nat``/``Int``/``Bool`` (explicit, implicit, strict-implicit, hypotheses,
``variable`` commands, auto-bound single letters); ``= ≠ < ≤ > ≥ ∣ ∧ ∨ ¬ → ↔ True False``;
``+ - * / % ^``, unary ``-``, ``min max``, ``Nat.succ Nat.pred Int.natAbs Int.toNat Nat.gcd Int.gcd
Nat.lcm``, ``↑``, ``(e : T)``, numerals, ``if then else``. Everything else is skipped with a reason.

Honest limits (L1): statements are reproduced, not proofs (a proof is checked by citing the original);
``∃``, structures, lists, sets, instances and higher-order statements are outside the fragment; the
witness samples values.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from ..engines import theorems as T
from ..engines import values as V

TIMEOUT_S = 900
CORE_FILES = ["Init/Data/Nat/Basic.lean", "Init/Data/Nat/Lemmas.lean", "Init/Data/Nat/MinMax.lean",
              "Init/Data/Nat/Gcd.lean", "Init/Data/Nat/Lcm.lean", "Init/Data/Nat/Dvd.lean",
              "Init/Data/Nat/Div/Basic.lean", "Init/Data/Nat/Mod.lean", "Init/Data/Int/Basic.lean",
              "Init/Data/Int/Lemmas.lean", "Init/Data/Int/Order.lean", "Init/Data/Int/DivMod/Lemmas.lean",
              "Init/Data/Int/Gcd.lean", "Init/Data/Int/Pow.lean"]


class Skip(ValueError):
    pass


# -- lexing -------------------------------------------------------------------------------------------
TOKEN = re.compile(r"""
    (?P<ws>\s+)
  | (?P<num>\d+)
  | (?P<op>→|->|↔|<->|∧|∨|¬|∀|∃|≠|≤|≥|<=|>=|==|!=|&&|\|\||∣|↑|⦃|⦄|⟨|⟩|·|:=|=>|↦|[()\[\]{},:=<>+\-*/%^!.$])
  | (?P<id>[A-Za-z_α-ωΑ-Ωℕℤ][A-Za-z0-9_α-ωΑ-Ω'!?₀-₉ℕℤ]*(?:\.[A-Za-z_][A-Za-z0-9_'!?₀-₉]*)*)
""", re.X)


def lex(text: str) -> list[str]:
    out, i = [], 0
    while i < len(text):
        m = TOKEN.match(text, i)
        if not m:
            raise Skip(f"token {text[i:i + 12]!r}")
        i = m.end()
        if m.lastgroup != "ws":
            out.append(m.group())
    return out


# -- declarations -------------------------------------------------------------------------------------
@dataclass
class LeanDecl:
    name: str
    short: str
    line: int
    binders: list = field(default_factory=list)       # [(kind, names, type_text)]
    statement: str = ""
    section_vars: list = field(default_factory=list)
    opens: list = field(default_factory=list)
    namespace: str = ""


def strip_comments(text: str) -> str:
    out, i, depth = [], 0, 0
    while i < len(text):
        if text.startswith("/-", i):
            depth += 1
            i += 2
            continue
        if depth and text.startswith("-/", i):
            depth -= 1
            i += 2
            continue
        if depth:
            out.append("\n" if text[i] == "\n" else " ")
            i += 1
            continue
        if text.startswith("--", i):
            while i < len(text) and text[i] != "\n":
                i += 1
            continue
        out.append(text[i])
        i += 1
    return "".join(out)


DECL_RE = re.compile(r"^(?:@\[[^\]]*\]\s*)*((?:protected|private|nonrec|noncomputable)\s+)*theorem\s+(\S+)")


def scan(text: str) -> list[LeanDecl]:
    """Theorem declarations with their namespace, open namespaces and section variables in scope."""
    lines = strip_comments(text).split("\n")
    scopes: list[tuple[str, str, list, list]] = []      # (kind, name, variables, opens)
    ns: list[str] = []
    decls = []
    i = 0
    while i < len(lines):
        raw = lines[i]
        line = raw.strip()
        if line.startswith("namespace "):
            name = line.split()[1]
            ns.append(name)
            scopes.append(("namespace", name, [], []))
        elif line.startswith("section") and (line == "section" or line.startswith("section ")):
            scopes.append(("section", line[8:].strip(), [], []))
        elif line == "end" or line.startswith("end "):
            if scopes:
                kind, _name, _v, _o = scopes.pop()
                if kind == "namespace" and ns:
                    ns.pop()
        elif line.startswith("open ") and scopes:
            scopes[-1][3].extend(line[5:].split())
        elif line.startswith("variable ") and scopes:
            scopes[-1][2].append(line[len("variable "):])
        m = DECL_RE.match(line)
        if m and not raw.startswith((" ", "\t")):
            mods = m.group(1) or ""
            name = m.group(2)
            text_block = line[m.end():]
            j = i
            while not _statement_done(text_block) and j + 1 < len(lines):
                j += 1
                nxt = lines[j]
                if re.match(r"^\s*\|", nxt):
                    break
                text_block += "\n" + nxt
            full = ".".join(ns + [name]) if not name.startswith("_root_.") else name[len("_root_."):]
            if "private" not in mods:
                d = LeanDecl(full, name, i + 1, namespace=".".join(ns))
                d.section_vars = [v for s in scopes for v in s[2]]
                d.opens = [o for s in scopes for o in s[3]] + [".".join(ns[:k + 1]) for k in range(len(ns))]
                d.statement = _until_assign(text_block)
                decls.append(d)
            i = j
        i += 1
    return decls


def _statement_done(text: str) -> bool:
    depth = 0
    for k, ch in enumerate(text):
        if ch in "([{⟨⦃":
            depth += 1
        elif ch in ")]}⟩⦄":
            depth -= 1
        elif ch == ":" and depth == 0 and text[k:k + 2] == ":=":
            return True
    return bool(re.search(r"\bwhere\b", text))


def _until_assign(text: str) -> str:
    depth = 0
    for k, ch in enumerate(text):
        if ch in "([{⟨⦃":
            depth += 1
        elif ch in ")]}⟩⦄":
            depth -= 1
        elif ch == ":" and depth == 0 and text[k:k + 2] == ":=":
            return text[:k].strip()
    m = re.search(r"\bwhere\b", text)
    return (text[:m.start()] if m else text).strip()


# -- parsing a signature ----------------------------------------------------------------------------------
TYPE_NAMES = {"Nat": "nat", "ℕ": "nat", "Int": "int", "ℤ": "int", "Bool": "bool"}


class P:
    """Pratt parser over Lean tokens for the arithmetic fragment."""

    def __init__(self, toks):
        self.t = toks
        self.i = 0

    def peek(self, k=0):
        return self.t[self.i + k] if self.i + k < len(self.t) else None

    def next(self):
        tok = self.peek()
        self.i += 1
        return tok

    def expect(self, tok):
        got = self.next()
        if got != tok:
            raise Skip(f"expected {tok!r}, found {got!r}")

    # binders: ( a b : T ) { ... } ⦃ ... ⦄ ; [ ... ] -> instance (unsupported)
    def binders(self):
        out = []
        while self.peek() in ("(", "{", "⦃", "["):
            open_ = self.next()
            close = {"(": ")", "{": "}", "⦃": "⦄", "[": "]"}[open_]
            if open_ == "[":
                raise Skip("instance binder")
            names = []
            while self.peek() not in (":", None, close):
                names.append(self.next())
            if self.peek() == close:                      # {m n}: types come from unification (auto-bound)
                self.next()
                out.append(("untyped", names, None))
                continue
            if self.peek() != ":":
                raise Skip("binder without a type")
            self.next()
            start = self.i
            depth = 0
            while True:
                tok = self.peek()
                if tok is None:
                    raise Skip("unclosed binder")
                if tok in ("(", "{", "[", "⦃", "⟨"):
                    depth += 1
                elif tok in (")", "}", "]", "⦄", "⟩"):
                    if depth == 0 and tok == close:
                        break
                    depth -= 1
                self.next()
            ty = self.t[start:self.i]
            self.next()
            out.append(("implicit" if open_ != "(" else "explicit", names, ty))
        return out

    # expressions
    BIN = {"↔": (20, "R"), "<->": (20, "R"), "→": (25, "R"), "->": (25, "R"), "∨": (30, "R"), "∧": (35, "R"),
           "||": (30, "R"), "&&": (35, "R"), "=": (50, "L"), "≠": (50, "L"), "<": (50, "L"), "≤": (50, "L"),
           "<=": (50, "L"), ">": (50, "L"), "≥": (50, "L"), ">=": (50, "L"), "∣": (50, "L"), "==": (50, "L"),
           "!=": (50, "L"), "+": (65, "L"), "-": (65, "L"), "*": (70, "L"), "/": (70, "L"), "%": (70, "L"),
           "^": (75, "R")}

    def expr(self, prec=0):
        left = self.prefix()
        while True:
            op = self.peek()
            if op not in self.BIN:
                if self._starts_atom(op) and prec < 1024 and left[0] in ("app", "id"):
                    left = ("app", left, self.atom())          # application binds tightest
                    continue
                return left
            p, assoc = self.BIN[op]
            if p < prec or (p == prec and assoc == "L"):
                return left
            self.next()
            right = self.expr(p if assoc == "R" else p + 1)
            left = ("bin", op, left, right)

    def _starts_atom(self, tok):
        return tok is not None and (tok in ("(", "↑", "⟨") or tok.isdigit() or
                                    (re.match(r"[A-Za-z_α-ωℕℤ]", tok) is not None and tok not in ("then", "else", "fun")))

    def prefix(self):
        tok = self.peek()
        if tok == "¬":
            self.next()
            return ("not", self.expr(40))
        if tok == "-":
            self.next()
            return ("neg", self.expr(75))
        if tok == "!":
            self.next()
            return ("bnot", self.expr(1024))
        if tok in ("∀", "∃", "fun", "λ"):
            if tok == "∀":
                self.next()
                bs = []
                if self.peek() in ("(", "{", "⦃"):
                    bs = self.binders()
                else:
                    names = []
                    while self.peek() not in (":", ","):
                        names.append(self.next())
                    ty = []
                    if self.peek() == ":":
                        self.next()
                        while self.peek() != ",":
                            ty.append(self.next())
                    bs = [("explicit", names, ty or ["_"])]
                self.expect(",")
                return ("forall", bs, self.expr(0))
            raise Skip(f"{tok} in the statement")
        if tok == "if":
            self.next()
            c = self.expr(0)
            self.expect("then")
            a = self.expr(0)
            self.expect("else")
            b = self.expr(0)
            return ("ite", c, a, b)
        return self.atom_app()

    def atom_app(self):
        a = self.atom()
        while self._starts_atom(self.peek()):
            a = ("app", a, self.atom())
        return a

    def atom(self):
        tok = self.next()
        if tok is None:
            raise Skip("unexpected end")
        if tok == "(":
            e = self.expr(0)
            if self.peek() == ":":
                self.next()
                ty = []
                depth = 0
                while not (self.peek() == ")" and depth == 0):
                    t = self.next()
                    depth += t in ("(",)
                    depth -= t in (")",)
                    ty.append(t)
                self.expect(")")
                return ("ascribe", e, ty)
            self.expect(")")
            return e
        if tok == "↑":
            return ("coe", self.atom())
        if tok.isdigit():
            return ("num", int(tok))
        if tok in ("True", "False", "true", "false"):
            return ("const", tok)
        if re.match(r"[A-Za-z_α-ωℕℤ]", tok):
            return ("id", tok)
        raise Skip(f"token {tok!r}")


# -- elaboration (mimics Lean's binop%/binrel% leaf coercion) ------------------------------------------------
ARITH = {"+", "-", "*", "/", "%"}
REL = {"=": "eq", "≠": "ne", "<": "lt", "≤": "le", "<=": "le", ">": "gt", "≥": "ge", ">=": "ge"}
FUNS = {"min": "MIN", "max": "MAX", "Nat.min": "MIN", "Nat.max": "MAX", "Nat.succ": "SUCC", "succ": "SUCC",
        "Nat.pred": "PRED", "pred": "PRED", "Int.natAbs": "NATABS", "natAbs": "NATABS", "Int.toNat": "TONAT",
        "toNat": "TONAT", "Nat.gcd": "NGCD", "gcd": "NGCD", "Int.gcd": "IGCD", "Nat.lcm": "NLCM", "lcm": "NLCM",
        "Int.ofNat": "CAST", "Int.neg": "INEG", "Nat.add": "NADD", "Nat.mul": "NMUL", "Nat.sub": "NSUB_F"}


class Elab:
    def __init__(self, var_types: dict, auto: dict, opens: list):
        self.vt = var_types       # name -> nat|int|bool
        self.auto = auto          # auto-bound: name -> type (filled on use)
        self.opens = opens

    def resolve(self, name: str) -> str:
        return name

    # prop level
    def prop(self, e):
        k = e[0]
        if k == "bin" and e[1] in ("∧", "∨", "→", "->", "↔", "<->"):
            head = {"∧": "and", "∨": "or", "→": "imp", "->": "imp", "↔": "iff", "<->": "iff"}[e[1]]
            return [head, self.prop(e[2]), self.prop(e[3])]
        if k == "not":
            return ["not", self.prop(e[1])]
        if k == "const" and e[1] in ("True", "False"):
            return ["true"] if e[1] == "True" else ["false"]
        if k == "bin" and e[1] in REL:
            a, b, _ = self.tree_pair(e[2], e[3])
            return [REL[e[1]], a, b]
        if k == "bin" and e[1] == "∣":
            a, b, _ = self.tree_pair(e[2], e[3])
            return ["dvd", a, b]
        if k == "forall":
            raise Skip("nested ∀ inside the statement")
        if k == "ascribe":
            return self.prop(e[1])
        t, ty = self.term(e, None)
        if ty == "bool":
            return ["bool", t]
        raise Skip(f"proposition {k}")

    # binop tree: collect leaves, take the max type, coerce Nat leaves when the tree is Int
    def leaves(self, e, out):
        if e[0] == "bin" and e[1] in ARITH:
            self.leaves(e[2], out)
            self.leaves(e[3], out)
        elif e[0] == "neg":
            self.leaves(e[1], out)
        else:
            out.append(e)

    def tree_type(self, *es):
        ls = []
        for e in es:
            self.leaves(e, ls)
        types = set()
        for leaf in ls:
            ty = self.leaf_type(leaf)
            if ty:
                types.add(ty)
        if "int" in types:
            return "int"
        if "nat" in types:
            return "nat"
        if "bool" in types:
            return "bool"
        return "nat"

    def leaf_type(self, e):
        k = e[0]
        if k == "num":
            return None
        if k == "id":
            n = e[1]
            if n in self.vt:
                return self.vt[n]
            if n in self.auto:
                return self.auto[n]
            return None
        if k == "ascribe":
            return _type_of(e[2])
        if k == "coe":
            return None
        if k == "app":
            f, args = _spine(e)
            if f[0] == "id":
                fn = self.fun_name(f[1])
                if fn in ("NATABS", "TONAT", "NGCD", "IGCD", "NLCM", "SUCC", "PRED", "NADD", "NMUL", "NSUB_F"):
                    return "nat"
                if fn in ("CAST", "INEG"):
                    return "int"
                if fn in ("MIN", "MAX"):
                    return self.tree_type(*args)
            return None
        if k == "ite":
            return self.tree_type(e[2], e[3])
        if k == "const":
            return "bool" if e[1] in ("true", "false") else None
        if k == "bnot":
            return "bool"
        return None

    def tree_pair(self, a, b):
        ty = self.tree_type(a, b)
        self._fill_auto(a, ty)
        self._fill_auto(b, ty)
        return self.term(a, ty)[0], self.term(b, ty)[0], ty

    def _fill_auto(self, e, ty):
        ls = []
        self.leaves(e, ls)
        for leaf in ls:
            if leaf[0] == "id" and leaf[1] in self.auto and self.auto[leaf[1]] is None:
                self.auto[leaf[1]] = ty

    def fun_name(self, name):
        if name in FUNS:
            return FUNS[name]
        for o in self.opens:
            q = f"{o}.{name}"
            if q in FUNS:
                return FUNS[q]
        return None

    def term(self, e, want):
        """(card term, type) with ``want`` the tree's type (Nat leaves are cast when the tree is Int)."""
        k = e[0]
        if k == "bin" and e[1] in ARITH:
            ty = want or self.tree_type(e)
            a, _ = self.term(e[2], ty)
            b, _ = self.term(e[3], ty)
            op = {"+": "ADD", "*": "MUL", "/": "LEAN_DIV", "%": "LEAN_MOD"}.get(e[1])
            if e[1] == "-":
                op = "LEAN_NSUB" if ty == "nat" else "SUB"
            return [op, a, b], ty
        if k == "bin" and e[1] == "^":
            base, bt = self.term(e[2], want)
            ex, et = self.term(e[3], "nat")
            if et != "nat":
                raise Skip("exponent is not a Nat")
            return ["LEAN_POW", base, ex], bt
        if k == "neg":
            ty = want or self.tree_type(e)
            if ty != "int":
                raise Skip("negation outside Int")
            a, _ = self.term(e[1], ty)
            return ["NEG", a], "int"
        if k == "num":
            ty = want or "nat"
            return ["int", e[1], ty], ty                  # a numeral keeps the type Lean gave it
        if k == "id" and e[1] in ("Nat.zero", "zero") and e[1] not in self.vt:
            return (["LEAN_CAST", ["int", 0]], "int") if want == "int" else (["int", 0], "nat")
        if k == "id":
            n = e[1]
            if n in self.auto and self.auto[n] is None and want in ("nat", "int", "bool"):
                self.auto[n] = want                      # auto-bound implicit: typed by where it is used
            ty = self.vt.get(n) or self.auto.get(n)
            if ty is None:
                if n in self.auto:
                    raise Skip(f"cannot infer the type of auto-bound {n}")
                raise Skip(f"unknown name {n}")
            node = ["var", n]
            if ty == "nat" and want == "int":
                return ["LEAN_CAST", node], "int"
            if ty == "int" and want == "nat":
                raise Skip("an Int where a Nat is expected")
            return node, ty
        if k == "coe":
            inner, ity = self.term(e[1], None)
            if ity == "nat":
                return ["LEAN_CAST", inner], "int"
            return inner, ity
        if k == "ascribe":
            ty = _type_of(e[2])
            inner, ity = self.term(e[1], ty)
            if ity == "nat" and ty == "int":
                return ["LEAN_CAST", inner], "int"
            return inner, ity
        if k == "app":
            f, args = _spine(e)
            if f[0] != "id":
                raise Skip("application of a non-name")
            fn = self.fun_name(f[1])
            if fn is None:
                raise Skip(f"function {f[1]}")
            if fn in ("MIN", "MAX"):
                if len(args) != 2:
                    raise Skip("min/max arity")
                ty = want or self.tree_type(*args)
                for a in args:
                    self._fill_auto(a, ty)
                a, _ = self.term(args[0], ty)
                b, _ = self.term(args[1], ty)
                return [fn, a, b], ty
            unary = {"SUCC": ("nat", "nat"), "PRED": ("nat", "nat"), "NATABS": ("int", "nat"), "TONAT": ("int", "nat"),
                     "CAST": ("nat", "int"), "INEG": ("int", "int")}
            if fn in unary:
                if len(args) != 1:
                    raise Skip(f"{f[1]} arity")
                arg_t, res_t = unary[fn]
                a, _ = self.term(args[0], arg_t)
                node = {"SUCC": ["ADD", a, ["int", 1]], "PRED": ["LEAN_NSUB", a, ["int", 1]],
                        "NATABS": ["LEAN_NATABS", a], "TONAT": ["LEAN_TONAT", a], "CAST": ["LEAN_CAST", a],
                        "INEG": ["NEG", a]}[fn]
                if res_t == "nat" and want == "int":
                    return ["LEAN_CAST", node], "int"
                return node, res_t
            binary = {"NGCD": ("nat", "nat", "LEAN_GCD"), "IGCD": ("int", "nat", "LEAN_IGCD"),
                      "NLCM": ("nat", "nat", "LEAN_LCM"), "NADD": ("nat", "nat", "ADD"), "NMUL": ("nat", "nat", "MUL"),
                      "NSUB_F": ("nat", "nat", "LEAN_NSUB")}
            if fn in binary:
                if len(args) != 2:
                    raise Skip(f"{f[1]} arity")
                arg_t, res_t, op = binary[fn]
                a, _ = self.term(args[0], arg_t)
                b, _ = self.term(args[1], arg_t)
                node = [op, a, b]
                if res_t == "nat" and want == "int":
                    return ["LEAN_CAST", node], "int"
                return node, res_t
        if k == "ite":
            c = self.prop(e[1])
            ty = want or self.tree_type(e[2], e[3])
            a, _ = self.term(e[2], ty)
            b, _ = self.term(e[3], ty)
            return ["LEAN_ITE", ["PROP", c], a, b], ty
        if k == "const" and e[1] in ("true", "false"):
            return ["bool", e[1] == "true"], "bool"
        if k == "bnot":
            a, _ = self.term(e[1], "bool")
            return ["NOT", a], "bool"
        if k == "bin" and e[1] in ("==", "!="):
            a, b, _ = self.tree_pair(e[2], e[3])
            return ["CMP_EQ" if e[1] == "==" else "CMP_NE", a, b], "bool"
        if k == "bin" and e[1] in ("&&", "||"):
            a, _ = self.term(e[2], "bool")
            b, _ = self.term(e[3], "bool")
            return ["AND" if e[1] == "&&" else "OR", a, b], "bool"
        raise Skip(f"term {k}{(' ' + str(e[1])) if len(e) > 1 and isinstance(e[1], str) else ''}")


def _spine(e):
    args = []
    while e[0] == "app":
        args.append(e[2])
        e = e[1]
    return e, list(reversed(args))


def _type_of(toks) -> str:
    text = "".join(toks)
    if text not in TYPE_NAMES:
        raise Skip(f"type {text}")
    return TYPE_NAMES[text]


# -- Lean semantics (evaluation of the LEAN_* op nodes) -------------------------------------------------------------
def lean_ops(ops: dict) -> dict:
    """The op table plus Lean-semantic ops (evaluation only; rendering is ``render``)."""
    import math

    from ..engines.ir import OpSpec

    def ediv(a, b):
        if b == 0:
            return 0
        return a // b if b > 0 else -(a // -b)

    def emod(a, b):
        return a if b == 0 else a % abs(b)

    extra = {"LEAN_DIV": (2, ediv), "LEAN_MOD": (2, emod), "LEAN_NSUB": (2, lambda a, b: max(a - b, 0)),
             "LEAN_POW": (2, lambda a, b: a ** b), "LEAN_CAST": (1, lambda a: a), "LEAN_NATABS": (1, abs),
             "LEAN_TONAT": (1, lambda a: max(a, 0)), "LEAN_GCD": (2, math.gcd), "LEAN_IGCD": (2, math.gcd),
             "LEAN_LCM": (2, math.lcm)}
    out = dict(ops)
    for name, (arity, fn) in extra.items():
        out[name] = OpSpec(name, arity, [], fn, {})
    return out


def eval_term(t, env, ops):
    if t[0] == "LEAN_ITE":
        cond = T.eval_prop(t[1][1], env, ops) if t[1][0] == "PROP" else bool(eval_term(t[1], env, ops))
        return eval_term(t[2] if cond else t[3], env, ops)
    from ..engines.logic import eval_expr
    if any(isinstance(a, list) and a and a[0] == "LEAN_ITE" for a in t[1:] if isinstance(a, list)):
        return ops[t[0]].fn(*[eval_term(a, env, ops) for a in t[1:]])
    return eval_expr(t, env, ops)


# -- rendering back to Lean -------------------------------------------------------------------------------------------
LEAN_INFIX = {"ADD": "+", "SUB": "-", "MUL": "*", "LEAN_DIV": "/", "LEAN_MOD": "%", "LEAN_NSUB": "-",
              "LEAN_POW": "^"}
LEAN_RELS = {"eq": "=", "ne": "≠", "lt": "<", "le": "≤", "gt": ">", "ge": "≥"}


def render_term(t, types: dict) -> tuple[str, str]:
    h = t[0]
    if h == "var":
        return t[1], types[t[1]]
    if h == "int":
        if len(t) > 2:
            return f"({t[1]} : {'Int' if t[2] == 'int' else 'Nat'})", t[2]
        return f"{t[1]}", "num"
    if h == "bool":
        return ("true" if t[1] else "false"), "bool"
    if h in LEAN_INFIX:
        a, ta = render_term(t[1], types)
        b, tb = render_term(t[2], types)
        ty = "int" if "int" in (ta, tb) and h != "LEAN_POW" else ("nat" if "nat" in (ta, tb) else "num")
        if h == "LEAN_POW":
            ty = ta
        if h == "LEAN_NSUB" or (h in ("ADD", "MUL", "LEAN_DIV", "LEAN_MOD", "LEAN_POW") and ty in ("nat", "num")):
            a = _annotate(a, ta, "nat")
            b = _annotate(b, tb, "nat")
            return f"({a} {LEAN_INFIX[h]} {b} : Nat)", "nat"
        if h == "LEAN_POW":
            return f"({_annotate(a, ta, ty)} ^ ({b} : Nat))", ty
        a = _annotate(a, ta, "int")
        b = _annotate(b, tb, "int")
        return f"({a} {LEAN_INFIX[h]} {b} : Int)", "int"
    if h == "NEG":
        a, ta = render_term(t[1], types)
        return f"(-{_annotate(a, ta, 'int')} : Int)", "int"
    if h == "LEAN_CAST":
        a, ta = render_term(t[1], types)
        return f"(({_annotate(a, ta, 'nat')} : Nat) : Int)", "int"
    if h in ("MIN", "MAX"):
        a, ta = render_term(t[1], types)
        b, tb = render_term(t[2], types)
        ty = "int" if "int" in (ta, tb) else "nat"
        T_ = "Int" if ty == "int" else "Nat"
        return f"({h.lower()} ({a} : {T_}) ({b} : {T_}))", ty
    if h in ("LEAN_NATABS", "LEAN_TONAT"):
        a, ta = render_term(t[1], types)
        fn = "Int.natAbs" if h == "LEAN_NATABS" else "Int.toNat"
        return f"({fn} ({a} : Int))", "nat"
    if h in ("LEAN_GCD", "LEAN_LCM", "LEAN_IGCD"):
        a, ta = render_term(t[1], types)
        b, tb = render_term(t[2], types)
        fn = {"LEAN_GCD": "Nat.gcd", "LEAN_LCM": "Nat.lcm", "LEAN_IGCD": "Int.gcd"}[h]
        T_ = "Int" if h == "LEAN_IGCD" else "Nat"
        return f"({fn} ({a} : {T_}) ({b} : {T_}))", "nat"
    if h == "LEAN_ITE":
        c = render_prop(t[1][1], types)
        a, ta = render_term(t[2], types)
        b, tb = render_term(t[3], types)
        ty = "int" if "int" in (ta, tb) else ("nat" if "nat" in (ta, tb) else "num")
        T_ = "Int" if ty == "int" else "Nat"
        return f"(if {c} then ({a} : {T_}) else ({b} : {T_}))", ty
    if h == "NOT":
        a, _ = render_term(t[1], types)
        return f"(!{a})", "bool"
    if h in ("AND", "OR"):
        a, _ = render_term(t[1], types)
        b, _ = render_term(t[2], types)
        return f"({a} {'&&' if h == 'AND' else '||'} {b})", "bool"
    if h in ("CMP_EQ", "CMP_NE"):
        a, ta = render_term(t[1], types)
        b, tb = render_term(t[2], types)
        ty = _join(ta, tb)
        return f"({_annotate(a, ta, ty)} {'==' if h == 'CMP_EQ' else '!='} {_annotate(b, tb, ty)})", "bool"
    raise Skip(f"render {h}")


def _join(ta, tb):
    if "int" in (ta, tb):
        return "int"
    if "nat" in (ta, tb):
        return "nat"
    if "bool" in (ta, tb):
        return "bool"
    return "nat"


def _annotate(text, have, want):
    if have == "num":
        return f"({text} : {'Int' if want == 'int' else 'Nat'})"
    return text


def render_prop(p, types: dict) -> str:
    h = p[0]
    if h in LEAN_RELS:
        a, ta = render_term(p[1], types)
        b, tb = render_term(p[2], types)
        ty = _join(ta, tb)
        if ty == "bool":
            return f"{a} {LEAN_RELS[h]} {b}"
        return f"{_annotate(a, ta, ty)} {LEAN_RELS[h]} {_annotate(b, tb, ty)}"
    if h == "dvd":
        a, ta = render_term(p[1], types)
        b, tb = render_term(p[2], types)
        ty = _join(ta, tb)
        return f"{_annotate(a, ta, ty)} ∣ {_annotate(b, tb, ty)}"
    if h in ("and", "or", "imp", "iff"):
        sym = {"and": "∧", "or": "∨", "imp": "→", "iff": "↔"}[h]
        return f"({render_prop(p[1], types)}) {sym} ({render_prop(p[2], types)})"
    if h == "not":
        return f"¬ ({render_prop(p[1], types)})"
    if h == "true":
        return "True"
    if h == "false":
        return "False"
    if h == "bool":
        a, _ = render_term(p[1], types)
        return f"{a} = true"
    raise Skip(f"render proposition {h}")


def render_statement(card) -> str:
    """∀ (x : T) ..., h1 → ... → concl, binders and hypotheses interleaved in the original order."""
    types = {v["name"]: v["type"] for v in card["vars"]}
    parts = []
    for item in card["order"]:
        if item[0] == "var":
            v = next(x for x in card["vars"] if x["name"] == item[1])
            parts.append(("∀", f"({v['name']} : {'Nat' if v['type'] == 'nat' else 'Int' if v['type'] == 'int' else 'Bool'})"))
        else:
            parts.append(("→", f"({render_prop(card['hyps'][item[1]], types)})"))
    text = render_prop(card["concl"], types)
    for kind, piece in reversed(parts):
        text = f"∀ {piece}, {text}" if kind == "∀" else f"{piece} → ({text})"     # ↔ binds looser than →
    return text


# -- importing a declaration ----------------------------------------------------------------------------------------------
def _section_binders(decl: LeanDecl, statement_toks: set) -> list:
    out = []
    for v in decl.section_vars:
        try:
            p = P(lex(v))
            for kind, names, ty in p.binders():
                keep = [n for n in names if n in statement_toks]
                if keep:
                    out.append((kind, keep, ty))
        except Skip:
            continue
    return out


def card_for(decl: LeanDecl, origin: dict) -> dict:
    toks = lex(decl.statement)
    p = P(toks)
    binders = p.binders()
    p.expect(":")
    body_toks = toks[p.i:]
    stmt_names = set(toks)
    binders = _section_binders(decl, stmt_names) + binders
    var_types: dict = {}
    order: list = []
    hyp_exprs: list = []
    untyped = []
    for kind, names, ty in binders:
        if ty is None:
            for n in names:
                untyped.append(n)
                order.append(("var", n))
            continue
        tyname = "".join(ty)
        if tyname in TYPE_NAMES:
            for n in names:
                var_types[n] = TYPE_NAMES[tyname]
                order.append(("var", n))
        else:
            for _n in names:
                hyp_exprs.append(P(ty).expr(0))
                order.append(("hyp", len(hyp_exprs) - 1))
    q = P(body_toks)
    concl_e = q.expr(0)
    if q.i != len(body_toks):
        raise Skip(f"trailing tokens {body_toks[q.i:q.i + 4]}")
    while concl_e[0] == "forall" or (concl_e[0] == "bin" and concl_e[1] in ("→", "->")):
        if concl_e[0] == "forall":
            for kind, names, ty in concl_e[1]:
                if ty is None:
                    for n in names:
                        untyped.append(n)
                        order.append(("var", n))
                    continue
                tyname = "".join(ty)
                if tyname not in TYPE_NAMES:
                    for _n in names:
                        hyp_exprs.append(P(ty).expr(0))
                        order.append(("hyp", len(hyp_exprs) - 1))
                    continue
                for n in names:
                    var_types[n] = TYPE_NAMES[tyname]
                    order.append(("var", n))
            concl_e = concl_e[2]
        else:
            hyp_exprs.append(concl_e[2])
            order.append(("hyp", len(hyp_exprs) - 1))
            concl_e = concl_e[3]
    auto = {n: None for n in untyped}
    free = _free_names(concl_e) | set().union(*(_free_names(h) for h in hyp_exprs)) if hyp_exprs else _free_names(concl_e)
    for n in sorted(free):
        if n not in var_types and n not in auto and re.fullmatch(r"[a-zα-ω][₀-₉0-9']*", n):
            auto[n] = None
    implicit_auto = [n for n in auto if n not in untyped]
    el = Elab(var_types, auto, decl.opens)
    hyps = [el.prop(h) for h in hyp_exprs]
    concl = el.prop(concl_e)
    for n, ty in auto.items():
        if ty is None:
            raise Skip(f"cannot infer the type of auto-bound {n}")
    if auto:
        first_use = [n for n in _ordered_names(decl.statement) if n in implicit_auto]
        order = [("var", n) for n in first_use] + order
        var_types.update(auto)
    vars_ = [{"name": n, "type": var_types[n]} for kind, n in order if kind == "var"]
    if any(v["type"] not in ("nat", "int", "bool") for v in vars_):
        raise Skip("variable of another type")
    name = "lean." + re.sub(r"[^A-Za-z0-9_.\-]", lambda m: f"_x{ord(m.group()):02x}", decl.name)
    return {"name": name, "category": "theorem", "vars": vars_, "hyps": hyps, "concl": concl, "order": order,
            "semantics": "lean", "status": "conjecture", "original": " ".join(decl.statement.split()),
            "origin": {**origin, "decl": decl.name, "line": decl.line}}


def _free_names(e) -> set:
    out = set()
    if isinstance(e, tuple):
        if e[0] == "id":
            out.add(e[1])
        for x in e[1:]:
            if isinstance(x, tuple):
                out |= _free_names(x)
            elif isinstance(x, list):
                for y in x:
                    if isinstance(y, tuple):
                        out |= _free_names(y)
    return out


def _ordered_names(text: str) -> list[str]:
    seen = []
    for tok in lex(text):
        if tok not in seen:
            seen.append(tok)
    return seen


# -- checking with Lean -------------------------------------------------------------------------------------------------------
def faithful(cards: list[dict], exe: str, prelude: str | None = None) -> dict[str, str]:
    """{card name: 'ok' | reason} -- does the Lean kernel accept our reading as the original theorem?
    ``prelude``: the source that defines the originals (a user's file; core theorems need none)."""
    from . import lean as LE
    out, items = {}, []
    for c in cards:
        try:
            c["lean_statement"] = render_statement(c)
        except Skip as exc:
            out[c["name"]] = f"render: {exc}"
            continue
        items.append((c["name"], f"example : {c['lean_statement']} := @{c['origin']['decl']}"))
    header = (prelude.split("\n") if prelude else []) + ["set_option maxHeartbeats 200000",
                                                         "set_option linter.unusedVariables false"]
    verdict = LE.check_batch(exe, items, header=header, timeout_s=TIMEOUT_S)
    for name, v in verdict.items():
        out[name] = "ok" if v == "ok" else v
    return out


def reprove(cards: list[dict], exe: str, tactics=("omega", "grind", "simp", "decide")) -> dict[str, list[str]]:
    """Which of the card model's tactics prove each statement without the original proof (fail closed)."""
    from . import lean as LE
    out: dict[str, list[str]] = {c["name"]: [] for c in cards}
    for tac in tactics:
        items = [(c["name"], f"theorem cm_re_{k} : {c['lean_statement']} := by intros; {tac}")
                 for k, c in enumerate(cards)]
        verdict = LE.check_batch(exe, items, header=["set_option maxHeartbeats 100000"], timeout_s=TIMEOUT_S)
        for name, v in verdict.items():
            if v == "ok":
                out[name].append(tac)
    return out


def import_source(ctx, text: str, origin: dict, check: bool = True, reprove_tactics=None, seed: int | None = None,
                  samples: int = 120, limit: int | None = None, cube: int = 600, chains_too: bool = True) -> dict:
    from ..emit import lean as LE
    seed = V.fresh_seed() if seed is None else seed
    decls = scan(text)
    cards, skipped = [], {}
    for d in decls:
        try:
            cards.append(card_for(d, origin))
        except Skip as exc:
            reason = str(exc).split(" ")[0] if str(exc) else "skip"
            skipped[d.name] = str(exc)
            _ = reason
        if limit and len(cards) >= limit:
            break
    report = {"declarations": len(decls), "in_fragment": len(cards), "skipped": len(skipped),
              "skip_reasons": _top_reasons(skipped), "seed": seed}
    exe = LE.lean_exe() if check else None
    if check and exe is None:
        report["status"] = "no_toolchain"
    if exe:
        verdict = faithful(cards, exe, prelude=text if origin.get("kind") == "lean_file" else None)
        report["unfaithful"] = {n: v for n, v in verdict.items() if v != "ok"}
        cards = [c for c in cards if verdict.get(c["name"]) == "ok"]
        report["faithful"] = len(cards)
    ops = lean_ops(ctx.ops)
    refuted = []
    for c in cards:
        w = _witness(c, ops, seed, samples, cube)
        c["evidence"] = {k: w[k] for k in ("status", "seed", "checks", "counterexample", "reason") if k in w}
        if w["status"] == "refuted":
            refuted.append(c["name"])
    report["witness_refuted"] = refuted
    report["witnessed"] = sum(1 for c in cards if c["evidence"]["status"] == "witnessed")
    if exe and reprove_tactics is not False:
        tactics = reprove_tactics or ("omega", "grind", "simp", "decide")
        again = reprove(cards, exe, tactics)
        for c in cards:
            c["reproved_by"] = again.get(c["name"], [])
        report["reproved"] = sum(1 for c in cards if c.get("reproved_by"))
        report["reproved_by_tactic"] = {t: sum(1 for c in cards if t in c.get("reproved_by", [])) for t in tactics}
    chains = {}
    if exe and chains_too:
        from . import lean_chain
        eligible = [c for c in cards if lean_chain.eligible(c)]
        if eligible:
            chains = lean_chain.certify(ctx, eligible, max_depth=5, max_nodes=8000)["results"]
        report["chain_checked"] = sum(1 for r in chains.values() if r.get("status") == "checked")
        report["chain_eligible"] = len(eligible)
    tool = T.toolchain_version(exe) if exe else None
    for c in cards:
        proofs = []
        if exe:
            proofs.append({"method": "lean:original", "ok": True, "toolchain": tool,
                           "lean": f"example : {c['lean_statement']} := @{c['origin']['decl']}"})
            for t in c.get("reproved_by", []):
                proofs.append({"method": f"lean:{t}", "ok": True, "toolchain": tool})
            ch = chains.get(c["name"])
            if ch and ch.get("status") == "checked":
                c["reproved_by"] = c.get("reproved_by", []) + ["card_chain"]
                proofs.append({"method": "card_chain", "ok": True, "toolchain": tool, "rules": ch["rules"],
                               "steps": ch["steps"], "lean": ch["source"]})
        c["proofs"] = proofs
        c["status"] = "refuted" if c["evidence"]["status"] == "refuted" else ("proved" if proofs else
                                                                               c["evidence"]["status"])
        c["statement"] = T.statement(c)
    report["cards"] = cards
    return report


def _witness(card, ops, seed, samples, cube):
    """theorems.witness with Lean-semantic term evaluation (LEAN_ITE needs the prop evaluator)."""
    orig, orig_cube = T.eval_term, T.SMALL_CUBE

    def ev(t, env, ops_, call=None):
        return eval_term(t, env, ops_)

    T.eval_term, T.SMALL_CUBE = ev, cube
    try:
        return T.witness(card, ops, seed=seed, samples=samples)
    finally:
        T.eval_term, T.SMALL_CUBE = orig, orig_cube


def _top_reasons(skipped: dict) -> dict:
    counts: dict[str, int] = {}
    for why in skipped.values():
        key = re.sub(r"'[^']*'|\"[^\"]*\"|\b[a-zA-Z_.]*\d[\w.]*\b", "…", why)[:60]
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: -kv[1])[:12])


def core_root(exe: str | None) -> Path | None:
    if not exe:
        return None
    root = Path(exe).parent.parent / "src" / "lean"
    return root if root.is_dir() else None


__all__ = ["CORE_FILES", "Skip", "card_for", "core_root", "faithful", "import_source", "lean_ops", "render_statement",
           "reprove", "scan"]
