"""mathlang — mathematical notation as a language: a source (math -> card IR) and a target (card IR -> math).

A ``.math`` file holds functions written the way mathematics writes them. Plain Unicode and a LaTeX subset are
both accepted; the two can be mixed.

    -- triangular numbers                         (comments: --, # or %)
    T : ℕ → ℕ                                     signature (optional): ℤ ℕ ℝ 𝔹, also Int Nat Real Bool, × and →
    T(n) = n(n + 1)/2                             juxtaposition multiplies; / is real division (the result is ℝ)
    tri(n) = ⌊n(n + 1)/2⌋                         ⌊a/b⌋ on integers is exact floor division

    gcd(a, b) = |a|                if b = 0       piecewise: one case per line, `if` guards, `otherwise`
              = gcd(b, a mod b)    otherwise

    fact(0) = 1                                   pattern equations: literal arguments are guards
    fact(n) = n · fact(n − 1)

    s(n) = Σ_{i=1}^{n} i²                         Σ and Π over integer ranges (bounds inclusive), n!
    h(x) = y² + 1  where y = x + 1                where-bindings (sequential, in scope for every case)
    f(x) = { x if x ≥ 0; −x otherwise }           inline piecewise; also `if c then a else b`, `let y = e in b`
    fib(n) = …
      for 0 ≤ n ≤ 90                              the domain (requires); seeds the verification inputs
    test T(4) = 10.0                              a test (`cardmodel math run` checks it)

LaTeX: ``\\frac{a}{b}``, ``\\sqrt{x}``, ``\\cdot``, ``\\times``, ``\\le``, ``\\ge``, ``\\ne``, ``\\sum_{i=1}^{n}``,
``\\prod``, ``\\lfloor``/``\\rfloor``, ``\\lceil``/``\\rceil``, ``\\left``/``\\right``, ``\\begin{cases} a & n = 0 \\\\
b & \\text{otherwise} \\end{cases}``, ``\\operatorname{name}``, ``\\mathbb{N}``, ``\\to``, ``\\bmod``, ``\\pi``,
``x^{2}``.

Semantics (the card IR's, see ir.py): ℤ is the unbounded integer, ℝ is IEEE binary64 (not the real numbers: the
name says what a reader expects, the IR says what runs), 𝔹 the booleans, ℕ an ℤ with the domain n ≥ 0. ``/``
is real division; ``⌊a/b⌋``, ``÷`` and ``//`` are floor division; ``a mod b`` takes the sign of b; ``^`` with an
integer base and exponent is an integer power. ``=`` inside an expression is equality. A name followed by ``(``
is a call when it names a function (one of the file's, a built-in such as sqrt, exp, log, sin, gcd, min, max, or
any op card in lower case, e.g. ``bit_xor(a, b)``); otherwise it is a product (``n(n + 1)``). Multi-letter names
are one variable. ``π`` is binary64 pi; a bare ``e`` is Euler's number unless something named e is in scope.

Emission (target): every IR function without machine state becomes equations. Straight-line code becomes
where-bindings, ``if`` becomes cases, and each loop becomes a recursive equation over the variables it carries
(a loop is a fixpoint; MATH_CORE §4). The frontend turns a function whose only self-calls are tail calls back into
a loop, so a round trip does not deepen the call stack. Emission is checked by a round trip: lift(emit(f)) must
behave like f on f's inputs (``round_trip``).

Honest limits (L1): no lists or strings yet (the IR has none); machine state (globals, arrays, stores, switch,
void functions) is not emitted as math (an EmitGap); a Σ body is evaluated in IR order, so a Σ of floats sums
left to right (binary64 is not associative); the LaTeX reader is a subset, not TeX.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from .codegen import EmitGap
from .ir import LEAVES, OpSpec


class MathError(ValueError):
    def __init__(self, msg: str, line: int | None = None):
        self.line = line
        super().__init__(f"line {line}: {msg}" if line else msg)


# ---- notation tables -------------------------------------------------------------------------------------------

TYPE_NAMES = {"ℤ": "int", "Z": "int", "Int": "int", "int": "int", "ℕ": "nat", "N": "nat", "Nat": "nat",
              "nat": "nat", "ℝ": "float", "R": "float", "Real": "float", "Float": "float", "float": "float",
              "𝔹": "bool", "B": "bool", "Bool": "bool", "bool": "bool"}
TYPE_SYMBOL = {"int": "ℤ", "float": "ℝ", "bool": "𝔹", "nat": "ℕ"}
TYPE_LATEX = {"int": r"\mathbb{Z}", "float": r"\mathbb{R}", "bool": r"\mathbb{B}", "nat": r"\mathbb{N}"}

# function-call names (lower case) -> op card; every other op card is reachable as its own name in lower case
BUILTINS = {"sqrt": "FSQRT", "exp": "EXP", "log": "LOG", "ln": "LOG", "sin": "SIN", "cos": "COS", "tan": "TAN",
            "asin": "ASIN", "arcsin": "ASIN", "acos": "ACOS", "arccos": "ACOS", "atan": "ATAN", "arctan": "ATAN",
            "atan2": "ATAN2", "sinh": "SINH", "cosh": "COSH", "tanh": "TANH", "abs": "ABS", "min": "MIN",
            "max": "MAX", "gcd": "GCD", "floor": "FLOOR", "ceil": "CEIL", "trunc": "TRUNC", "float": "TO_FLOAT",
            "int": "TRUNC_INT"}
# op cards printed by name: the reverse of BUILTINS where the name is the usual one
OP_NAME = {"FSQRT": "sqrt", "EXP": "exp", "LOG": "log", "SIN": "sin", "COS": "cos", "TAN": "tan", "ASIN": "asin",
           "ACOS": "acos", "ATAN": "atan", "ATAN2": "atan2", "SINH": "sinh", "COSH": "cosh", "TANH": "tanh",
           "MIN": "min", "MAX": "max", "GCD": "gcd", "FLOOR": "floor", "CEIL": "ceil", "TRUNC": "trunc",
           "TO_FLOAT": "float", "TRUNC_INT": "int"}
LATEX_FUNCS = {"sqrt", "exp", "log", "ln", "sin", "cos", "tan", "sinh", "cosh", "tanh", "min", "max", "gcd"}

CMP = {"=": "CMP_EQ", "==": "CMP_EQ", "≠": "CMP_NE", "!=": "CMP_NE", "<": "CMP_LT", "≤": "CMP_LE", "<=": "CMP_LE",
       ">": "CMP_GT", "≥": "CMP_GE", ">=": "CMP_GE"}
CMP_SYMBOL = {"CMP_EQ": "=", "CMP_NE": "≠", "CMP_LT": "<", "CMP_LE": "≤", "CMP_GT": ">", "CMP_GE": "≥"}
CMP_LATEX = {"CMP_EQ": "=", "CMP_NE": r"\neq", "CMP_LT": "<", "CMP_LE": r"\leq", "CMP_GT": ">", "CMP_GE": r"\geq"}

SUPERSCRIPT = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹", "0123456789")
SUPERSCRIPT_DIGITS = "⁰¹²³⁴⁵⁶⁷⁸⁹"
CONTINUATION = ("=", "|", "where", "for")
KEYWORDS = {"if", "then", "else", "otherwise", "let", "in", "where", "for", "and", "or", "not", "mod", "true",
            "false", "test", "div"}

# ---- LaTeX subset -> the Unicode notation --------------------------------------------------------------------

_LATEX_SIMPLE = {
    r"\cdot": "·", r"\times": "×", r"\div": "÷", r"\leq": "≤", r"\le": "≤", r"\geq": "≥", r"\ge": "≥",
    r"\neq": "≠", r"\ne": "≠", r"\lt": "<", r"\gt": ">", r"\land": "∧", r"\wedge": "∧", r"\lor": "∨",
    r"\vee": "∨", r"\lnot": "¬", r"\neg": "¬", r"\bmod": " mod ", r"\mod": " mod ", r"\sum": "Σ", r"\prod": "Π",
    r"\pi": "π", r"\lfloor": "⌊", r"\rfloor": "⌋", r"\lceil": "⌈", r"\rceil": "⌉", r"\lvert": "|",
    r"\rvert": "|", r"\vert": "|", r"\mid": "|", r"\to": "→", r"\rightarrow": "→", r"\mapsto": "→",
    r"\left": "", r"\right": "", r"\big": "", r"\Big": "", r"\,": " ", r"\;": " ", r"\!": "", r"\quad": " ",
    r"\qquad": " ", r"\ ": " ", r"\colon": ":", r"\_": "_", "\\\\": " ", r"\in": "∈", r"\infty": "∞",
    r"\{": "{", r"\}": "}",
}


def _brace_arg(s: str, i: int) -> tuple[str, int]:
    """The ``{...}`` group starting at s[i] (whitespace skipped): (inner text, index after the group)."""
    while i < len(s) and s[i].isspace():
        i += 1
    if i >= len(s) or s[i] != "{":
        if i < len(s):                   # \frac12 style: a single character
            return s[i], i + 1
        raise MathError("LaTeX: a command is missing its {argument}")
    depth, j = 0, i
    while j < len(s):
        if s[j] == "{":
            depth += 1
        elif s[j] == "}":
            depth -= 1
            if depth == 0:
                return s[i + 1:j], j + 1
        j += 1
    raise MathError("LaTeX: unbalanced {")


def _split_amp(row: str) -> tuple[str, str, str]:
    """value & condition, at the & outside nested cases."""
    depth = 0
    for j in range(len(row)):
        if row.startswith(r"\begin{cases}", j):
            depth += 1
        elif row.startswith(r"\end{cases}", j):
            depth -= 1
        elif row[j] == "&" and depth == 0:
            return row[:j], "&", row[j + 1:]
    return row, "", ""


def _matching_end(s: str, i: int) -> int:
    """Index of the \\end{cases} that closes the \\begin{cases} at s[i] (nesting counted)."""
    depth, j = 0, i
    while j < len(s):
        if s.startswith(r"\begin{cases}", j):
            depth += 1
            j += len(r"\begin{cases}")
            continue
        if s.startswith(r"\end{cases}", j):
            depth -= 1
            if depth == 0:
                return j
            j += len(r"\end{cases}")
            continue
        j += 1
    raise MathError(r"LaTeX: \begin{cases} without \end{cases}")


def _split_rows(body: str) -> list[str]:
    """The rows of a cases body: split at \\\\ that are not inside a nested cases environment."""
    rows, depth, start, j = [], 0, 0, 0
    while j < len(body):
        if body.startswith(r"\begin{cases}", j):
            depth += 1
        elif body.startswith(r"\end{cases}", j):
            depth -= 1
        elif body.startswith("\\\\", j) and depth == 0:
            rows.append(body[start:j])
            j += 2
            start = j
            continue
        j += 1
    rows.append(body[start:])
    return rows


def latex_to_text(s: str) -> str:
    """Rewrite the LaTeX subset into the Unicode notation (identity on text without backslashes)."""
    if "\\" not in s and "&" not in s:
        return s
    s = re.sub(r"\\\\\[[^\]]*\]", r"\\\\", s)          # \\[1ex] is a line break with spacing
    out, i = [], 0
    while i < len(s):
        env = re.match(r"\\(begin|end)\{(gathered|aligned|align\*?|equation\*?|displaymath|array)\}(\{[^}]*\})?",
                       s[i:])
        if env:
            i += len(env.group(0))
            continue
        if s.startswith(r"\begin{cases}", i):
            j = _matching_end(s, i)
            body = s[i + len(r"\begin{cases}"):j]
            cases = []
            for row in _split_rows(body):
                if not row.strip():
                    continue
                val, amp, cond = _split_amp(row)
                cond = latex_to_text(cond).strip()
                if amp and cond and not re.match(r"(if\b|otherwise\b|,)", cond):
                    cond = "if " + cond
                cases.append(f"{latex_to_text(val).strip()} {cond}".strip().rstrip(","))
            out.append("{ " + "; ".join(c.replace(", if", " if").replace(",if", " if") for c in cases) + " }")
            i = j + len(r"\end{cases}")
            continue
        if s[i] == "\\":
            m = re.match(r"\\([A-Za-z]+|.)", s[i:])
            cmd = "\\" + m.group(1)
            j = i + len(m.group(0))
            if cmd in (r"\frac", r"\dfrac", r"\tfrac"):
                a, j = _brace_arg(s, j)
                b, j = _brace_arg(s, j)
                out.append(f"(({latex_to_text(a)})/({latex_to_text(b)}))")
            elif cmd == r"\sqrt":
                a, j = _brace_arg(s, j)
                out.append(f"√({latex_to_text(a)})")
            elif cmd in (r"\operatorname", r"\mathrm", r"\text", r"\textrm", r"\mathit", r"\mbox"):
                a, j = _brace_arg(s, j)
                out.append(f" {a.replace(chr(92) + '_', '_')} ")
            elif cmd == r"\mathbb":
                a, j = _brace_arg(s, j)
                out.append({"N": "ℕ", "Z": "ℤ", "R": "ℝ", "B": "𝔹"}.get(a.strip(), a))
            elif cmd in _LATEX_SIMPLE:
                out.append(_LATEX_SIMPLE[cmd])
            elif cmd[1:] in LATEX_FUNCS or cmd[1:] in BUILTINS:
                out.append(cmd[1:])
            else:
                raise MathError(f"LaTeX: {cmd} is not in the supported subset")
            i = j
            continue
        if s[i] == "&":
            out.append(" ")
            i += 1
            continue
        out.append(s[i])
        i += 1
    return "".join(out)


# ---- lexer -------------------------------------------------------------------------------------------------------

@dataclass
class Tok:
    kind: str           # num | name | sym | nl | end
    text: str
    line: int
    value: object = None


_SYMS = sorted(["==", "!=", "<=", ">=", "->", "//", "**", "..", "=", "<", ">", "+", "-", "*", "/", "^", "(", ")",
                "{", "}", "[", "]", ",", ";", ":", "|", "!", "_", "·", "×", "÷", "−", "≤", "≥", "≠", "∧", "∨",
                "¬", "√", "⌊", "⌋", "⌈", "⌉", "Σ", "∑", "Π", "∏", "π", "→", "∈", "&", "'"], key=len, reverse=True)


def tokenize(text: str, line0: int = 1) -> list[Tok]:
    toks: list[Tok] = []
    i, line, depth = 0, line0, 0
    n = len(text)
    while i < n:
        c = text[i]
        if c == "\n":
            if depth == 0:
                toks.append(Tok("nl", "\n", line))
            line += 1
            i += 1
            continue
        if c.isspace():
            i += 1
            continue
        if text.startswith("--", i) or c in "#%":
            while i < n and text[i] != "\n":
                i += 1
            continue
        if c in SUPERSCRIPT_DIGITS:
            j = i
            while j < n and text[j] in SUPERSCRIPT_DIGITS:
                j += 1
            toks.append(Tok("sym", "^", line))
            toks.append(Tok("num", text[i:j], line, int(text[i:j].translate(SUPERSCRIPT))))
            i = j
            continue
        if c.isdigit():
            m = re.match(r"\d+(?:_\d+)*(\.\d+)?([eE][+-]?\d+)?", text[i:])
            s = m.group(0).replace("_", "")
            is_float = bool(m.group(1) or m.group(2))
            toks.append(Tok("num", s, line, float(s) if is_float else int(s)))
            i += len(m.group(0))
            continue
        if c.isalpha() and c not in "ΣΠπℤℕℝ𝔹" or c == "_" and i + 1 < n and text[i + 1].isalnum() and \
                (not toks or toks[-1].kind != "sym" or toks[-1].text not in ("Σ", "∑", "Π", "∏")):
            j = i
            while j < n and (text[j].isalnum() or text[j] == "_" and j + 1 < n and text[j + 1] != "{") and \
                    text[j] not in "ΣΠπℤℕℝ𝔹" + SUPERSCRIPT_DIGITS:
                j += 1
            while j < n and text[j] in "′'":
                j += 1
            toks.append(Tok("name", text[i:j].replace("′", "'"), line))
            i = j
            continue
        if c in "ℤℕℝ𝔹":
            toks.append(Tok("name", c, line))
            i += 1
            continue
        for s in _SYMS:
            if text.startswith(s, i):
                t = {"−": "-", "∑": "Σ", "∏": "Π", "**": "^", "->": "→", "×": "·", "*": "·"}.get(s, s)
                if s == "×" and toks and toks[-1].kind == "name" and toks[-1].text in TYPE_NAMES:
                    t = "×"          # a product of types in a signature
                if t in "([{⌊⌈":
                    depth += 1 if t != "{" else 0
                elif t in ")]⌋⌉":
                    depth = max(0, depth - 1)
                toks.append(Tok("sym", t, line))
                i += len(s)
                break
        else:
            raise MathError(f"unexpected character {c!r}", line)
    toks.append(Tok("end", "", line))
    return toks


# ---- surface syntax tree -----------------------------------------------------------------------------------------
# Expressions are tuples:
#   ("num", int) ("real", float) ("bool", b) ("name", s) ("pi",) ("call", name, [args]) ("bin", op, a, b)
#   ("neg", a) ("not", a) ("cmp", [a, b, ...], [ops]) ("and", a, b) ("or", a, b) ("pow", a, b) ("abs", a)
#   ("floor", a) ("ceil", a) ("sqrt", a) ("fact", a) ("sum"|"prod", var, lo, hi, body) ("cases", [(e, cond|None)])
#   ("let", [(name, e)], body)

@dataclass
class Definition:
    name: str
    params: list            # names, or ("lit", value) for a pattern argument
    cases: list             # [(expr, cond | None)]
    where: list             # [(name, expr)]
    domain: list            # [expr]
    line: int


@dataclass
class MathModule:
    name: str
    signatures: dict = field(default_factory=dict)      # name -> ([types], type)
    definitions: list = field(default_factory=list)     # [Definition]
    tests: list = field(default_factory=list)           # [(expr, line)]


def _logical_lines(text: str) -> list[tuple[int, str]]:
    """Physical lines joined into declarations: a line starting with = | where for (after indentation) continues
    the previous one, as does any line inside an open bracket."""
    out: list[list] = []
    depth = 0
    for no, raw in enumerate(text.split("\n"), 1):
        body = re.split(r"--|#|(?<!\\)%", raw, maxsplit=1)[0]
        if not body.strip():
            continue
        stripped = body.strip()
        first = re.match(r"[A-Za-z_]+|.", stripped).group(0)
        if out and (depth > 0 or first in CONTINUATION or out[-1][1].rstrip().endswith((",", "=", "+", "·", "-"))):
            out[-1][1] += "\n" + body
        else:
            out.append([no, body])
        depth += sum(body.count(c) for c in "([{⌊⌈") - sum(body.count(c) for c in ")]}⌋⌉")
        depth = max(depth, 0)
    return [(no, t) for no, t in out]


class Parser:
    def __init__(self, toks: list[Tok], functions: set[str]):
        self.t = toks
        self.i = 0
        self.functions = functions
        self.bound: list[set[str]] = [set()]

    # -- helpers
    @property
    def cur(self) -> Tok:
        return self.t[self.i]

    def peek(self, k: int = 1) -> Tok:
        return self.t[min(self.i + k, len(self.t) - 1)]

    def at(self, *texts: str) -> bool:
        tk = self.cur
        return tk.kind in ("sym", "name") and tk.text in texts

    def eat(self, text: str) -> Tok:
        if not self.at(text):
            raise MathError(f"expected {text!r}, found {self.cur.text or 'end'!r}", self.cur.line)
        tk = self.cur
        self.i += 1
        return tk

    def skip_nl(self) -> None:
        while self.cur.kind == "nl":
            self.i += 1

    def is_bound(self, name: str) -> bool:
        return any(name in s for s in self.bound)

    # -- declarations
    def signature(self) -> tuple[str, list[str], str]:
        name = self.cur.text
        self.i += 1
        self.eat(":")
        types = [self.type_name()]
        while self.at("×", "·", ","):
            self.i += 1
            types.append(self.type_name())
        if self.at("→"):
            self.i += 1
            ret = self.type_name()
        else:
            ret, types = types[-1], []          # a constant: c : ℝ
        if self.cur.kind != "end":
            raise MathError(f"unexpected {self.cur.text!r} after the signature", self.cur.line)
        return name, types, ret

    def type_name(self) -> str:
        tk = self.cur
        if tk.kind != "name" or tk.text not in TYPE_NAMES:
            raise MathError(f"unknown type {tk.text!r} (use ℤ ℕ ℝ 𝔹 or Int Nat Real Bool)", tk.line)
        self.i += 1
        return TYPE_NAMES[tk.text]

    def definition(self) -> Definition:
        line = self.cur.line
        name = self.cur.text
        self.i += 1
        params: list = []
        if self.at("("):
            self.i += 1
            while not self.at(")"):
                if self.cur.kind == "num":
                    params.append(("lit", self.cur.value))
                    self.i += 1
                elif self.at("-") and self.peek().kind == "num":
                    self.i += 1
                    params.append(("lit", -self.cur.value))
                    self.i += 1
                elif self.at("true", "false"):
                    params.append(("lit", self.cur.text == "true"))
                    self.i += 1
                elif self.cur.kind == "name":
                    params.append(self.cur.text)
                    self.i += 1
                else:
                    raise MathError(f"a parameter must be a name or a literal, found {self.cur.text!r}", self.cur.line)
                if not self.at(")"):
                    self.eat(",")
            self.eat(")")
        self.bound.append({p for p in params if isinstance(p, str)})
        self.eat("=")
        cases, where, domain = [], [], []
        while True:
            self.skip_nl()
            e = self.expr()
            cond = None
            if self.at("if"):
                self.i += 1
                cond = self.expr()
            elif self.at("otherwise"):
                self.i += 1
            elif self.at(",") and self.peek().text in ("where", "for"):
                self.i += 1
            elif self.at(","):
                self.i += 1
                if self.at("if"):
                    self.i += 1
                    cond = self.expr()
                else:
                    self.eat("otherwise")
            cases.append((e, cond))
            self.skip_nl()
            if self.at("=", "|"):
                self.i += 1
                continue
            break
        while self.at("where", "for"):
            kw = self.cur.text
            self.i += 1
            while True:
                self.skip_nl()
                if kw == "where":
                    if self.at("("):
                        raise MathError("a where-binding names one variable (write one binding per name)",
                                        self.cur.line)
                    if self.cur.kind != "name":
                        raise MathError("expected a name after `where`", self.cur.line)
                    bname = self.cur.text
                    self.i += 1
                    self.eat("=")
                    where.append((bname, self.expr()))
                    self.bound[-1].add(bname)
                else:
                    domain.append(self.expr())
                self.skip_nl()
                if self.at(",", ";", "and") and kw == "where" or self.at(",", ";") and kw == "for":
                    self.i += 1
                    continue
                break
            self.skip_nl()
        self.bound.pop()
        if self.cur.kind != "end":
            raise MathError(f"unexpected {self.cur.text!r} in the definition of {name}", self.cur.line)
        return Definition(name, params, cases, where, domain, line)

    # -- expressions (lowest precedence first)
    def expr(self):
        if self.at("let"):
            self.i += 1
            binds = []
            self.bound.append(set())
            while True:
                if self.cur.kind != "name":
                    raise MathError("expected a name after `let`", self.cur.line)
                bname = self.cur.text
                self.i += 1
                self.eat("=")
                binds.append((bname, self.expr()))
                self.bound[-1].add(bname)
                if self.at(","):
                    self.i += 1
                    continue
                break
            self.eat("in")
            self.skip_nl()
            body = self.expr()
            self.bound.pop()
            return ("let", binds, body)
        if self.at("if") :
            self.i += 1
            c = self.expr()
            self.eat("then")
            a = self.expr()
            self.eat("else")
            b = self.expr()
            return ("cases", [(a, c), (b, None)])
        return self.or_()

    def or_(self):
        a = self.and_()
        while self.at("∨", "or"):
            self.i += 1
            a = ("or", a, self.and_())
        return a

    def and_(self):
        a = self.not_()
        while self.at("∧", "and"):
            self.i += 1
            a = ("and", a, self.not_())
        return a

    def not_(self):
        if self.at("¬", "not"):
            self.i += 1
            return ("not", self.not_())
        return self.cmp()

    def cmp(self):
        a = self.add()
        items, ops = [a], []
        while self.cur.kind == "sym" and self.cur.text in CMP:
            ops.append(CMP[self.cur.text])
            self.i += 1
            items.append(self.add())
        return a if not ops else ("cmp", items, ops)

    def add(self):
        a = self.mul()
        while self.at("+", "-"):
            op = self.cur.text
            self.i += 1
            a = ("bin", op, a, self.mul())
        return a

    def mul(self):
        a = self.unary()
        while True:
            if self.at("·", "/", "÷", "//", "mod", "div"):
                op = {"div": "÷", "//": "÷"}.get(self.cur.text, self.cur.text)
                self.i += 1
                a = ("bin", op, a, self.unary())
            elif self.starts_atom():
                a = ("bin", "·", a, self.power())
            else:
                return a

    def starts_atom(self) -> bool:
        tk = self.cur
        if tk.kind == "num":
            return True
        if tk.kind == "name":
            return tk.text not in KEYWORDS and tk.text not in "ℤℕℝ𝔹" or self.is_bound(tk.text)
        return tk.kind == "sym" and tk.text in ("(", "√", "⌊", "⌈", "Σ", "Π", "π", "{")

    def unary(self):
        if self.at("-"):
            self.i += 1
            return ("neg", self.unary())
        if self.at("+"):
            self.i += 1
            return self.unary()
        if self.at("Σ", "Π") or self.cur.kind == "name" and self.cur.text in ("sum", "prod") and \
                self.peek().kind == "sym" and self.peek().text == "_":
            return self.big_op()
        return self.power()

    def big_op(self):
        kind = "sum" if self.cur.text in ("Σ", "sum") else "prod"
        line = self.cur.line
        self.i += 1
        self.eat("_")
        close = "}" if self.at("{") else ")"
        if not self.at("{", "("):
            raise MathError(f"{'Σ' if kind == 'sum' else 'Π'} needs _{{i=a}}^{{b}}", line)
        self.i += 1
        if self.cur.kind != "name":
            raise MathError("expected the index variable", line)
        var = self.cur.text
        self.i += 1
        self.eat("=")
        lo = self.expr()
        self.eat(close)
        self.eat("^")
        if self.at("{", "("):
            close = "}" if self.cur.text == "{" else ")"
            self.i += 1
            hi = self.expr()
            self.eat(close)
        else:
            hi = self.atom()
        self.bound.append({var})
        body = self.mul() if not self.at("Σ", "Π") else self.big_op()
        self.bound.pop()
        return (kind, var, lo, hi, body)

    def power(self):
        base = self.postfix()
        if self.at("^"):
            self.i += 1
            if self.at("{"):
                self.i += 1
                exp = self.expr()
                self.eat("}")
            elif self.at("-"):
                self.i += 1
                exp = ("neg", self.power())
            else:
                exp = self.power()
            return ("pow", base, exp)
        return base

    def postfix(self):
        a = self.atom()
        while self.at("!") and not (self.peek().kind == "sym" and self.peek().text == "="):
            self.i += 1
            a = ("fact", a)
        return a

    def atom(self):
        tk = self.cur
        if tk.kind == "num":
            self.i += 1
            return ("real", tk.value) if isinstance(tk.value, float) else ("num", tk.value)
        if tk.kind == "sym":
            if tk.text == "(":
                self.i += 1
                self.skip_nl()
                e = self.expr()
                self.skip_nl()
                self.eat(")")
                return e
            if tk.text == "{":
                return self.brace_cases()
            if tk.text == "|":
                self.i += 1
                e = self.expr()
                self.eat("|")
                return ("abs", e)
            if tk.text in ("⌊", "⌈"):
                self.i += 1
                e = self.expr()
                self.eat("⌋" if tk.text == "⌊" else "⌉")
                return ("floor" if tk.text == "⌊" else "ceil", e)
            if tk.text == "√":
                self.i += 1
                return ("sqrt", self.postfix() if not self.at("{") else self.brace_group())
            if tk.text == "π":
                self.i += 1
                return ("pi",)
            if tk.text in ("Σ", "Π"):
                return self.big_op()
            raise MathError(f"unexpected {tk.text!r}", tk.line)
        if tk.kind == "name":
            if tk.text in ("true", "false"):
                self.i += 1
                return ("bool", tk.text == "true")
            if tk.text in KEYWORDS:
                raise MathError(f"unexpected keyword {tk.text!r}", tk.line)
            self.i += 1
            name = tk.text
            if self.at("(") and not self.is_bound(name) and self.is_function(name):
                self.i += 1
                args = []
                self.skip_nl()
                while not self.at(")"):
                    args.append(self.expr())
                    self.skip_nl()
                    if not self.at(")"):
                        self.eat(",")
                        self.skip_nl()
                self.eat(")")
                return ("call", name, args)
            if name in LATEX_FUNCS and not self.is_bound(name) and self.starts_atom():
                return ("call", name, [self.power()])        # \sin x
            return ("name", name)
        raise MathError(f"unexpected {tk.text or 'end of line'!r}", tk.line)

    def brace_group(self):
        self.eat("{")
        e = self.expr()
        self.eat("}")
        return e

    def is_function(self, name: str) -> bool:
        return name in self.functions or name.lower() in BUILTINS or name.upper() in OP_LOWER_OK

    def brace_cases(self):
        self.eat("{")
        cases = []
        while True:
            while self.cur.kind == "nl" or self.at(";"):
                self.i += 1
            if self.at("}"):
                break
            e = self.expr()
            cond = None
            if self.at(","):
                self.i += 1
            if self.at("if"):
                self.i += 1
                cond = self.expr()
            elif self.at("otherwise"):
                self.i += 1
            cases.append((e, cond))
            if self.at(";") or self.cur.kind == "nl":
                continue
            self.eat("}")
            break
        if not cases:
            raise MathError("empty { }", self.cur.line)
        return cases[0][0] if len(cases) == 1 and cases[0][1] is None else ("cases", cases)


OP_LOWER_OK: set[str] = set()          # filled from the op table when a module is lowered


def parse(text: str, name: str = "math") -> MathModule:
    """Text (Unicode and/or the LaTeX subset) -> a MathModule of signatures, definitions and tests."""
    mod = MathModule(name)
    lines = _logical_lines(text)
    functions = set()
    for _, body in lines:
        m = re.match(r"\s*([A-Za-z_][\w']*)\s*(\(|:(?!=))", latex_to_text(body))
        if m and m.group(1) not in KEYWORDS:
            functions.add(m.group(1))
    for no, body in lines:
        text1 = latex_to_text(body)
        toks = tokenize(text1, no)
        while toks and toks[-1].kind == "nl":
            toks.pop()
        p = Parser(toks, functions)
        first = p.cur
        if first.kind == "end":            # a line of LaTeX layout only (\begin{gathered}, \\[1ex])
            continue
        if first.kind == "name" and first.text == "test":
            p.i += 1
            e = p.expr()
            if p.cur.kind != "end":
                raise MathError(f"unexpected {p.cur.text!r} after the test", p.cur.line)
            mod.tests.append((e, no))
            continue
        if first.kind == "name" and first.text == "module":
            mod.name = p.peek().text
            continue
        if first.kind == "name" and p.peek().kind == "sym" and p.peek().text == ":":
            n, ts, r = p.signature()
            mod.signatures[n] = (ts, r)
            continue
        if first.kind == "name":
            mod.definitions.append(p.definition())
            continue
        raise MathError(f"a line must be a signature, a definition or a test, found {first.text!r}", no)
    return mod


# ---- lowering: surface -> card IR -----------------------------------------------------------------------------------

def _zero(t: str):
    return {"int": ["int", 0], "float": ["float", 0.0], "bool": ["bool", False]}[t]


class _FnLower:
    def __init__(self, low: "Lowerer", name: str, params: list[str], ptypes: list[str], ret: str | None):
        self.low = low
        self.name = name
        self.params = params
        self.ptypes = dict(zip(params, ptypes))
        self.ret = ret
        self.locals: dict[str, str] = {}
        self.scope: list[dict[str, str]] = [{p: p for p in params}]
        self.types: dict[str, str] = dict(self.ptypes)
        self.ret_types: set[str] = set()
        self.tmp = 0

    # -- names
    def fresh(self, base: str, typ: str) -> str:
        self.tmp += 1
        n = f"cm_{re.sub(r'[^A-Za-z0-9_]', '_', base)}{self.tmp}"
        self.locals[n] = typ
        self.types[n] = typ
        return n

    def bind(self, name: str, typ: str) -> str:
        """An IR local for a new binding of ``name``: the name itself the first time, a fresh one after."""
        safe = re.sub(r"[^A-Za-z0-9_]", "_", name)
        if safe in self.types or safe in self.low.fn_names or safe in self.low.reserved_names:
            ir = self.fresh(safe, typ)
        else:
            ir = safe
            self.locals[ir] = typ
            self.types[ir] = typ
        self.scope[-1][name] = ir
        return ir

    def lookup(self, name: str) -> str | None:
        for s in reversed(self.scope):
            if name in s:
                return s[name]
        return None

    # -- typing helpers
    def apply(self, op: str, args: list, line=None) -> tuple[list, str]:
        """``[op, *args]`` with int->float promotion where only a float signature accepts the arguments."""
        spec: OpSpec | None = self.low.ops.get(op)
        if spec is None:
            raise MathError(f"no op card {op}", line)
        ts = [t for _, t in args]
        rt = spec.result_type(ts)
        if rt is None:
            want = spec.promoted(ts) or (["float"] * len(ts) if all(t in ("int", "float") for t in ts) and
                                         spec.result_type(["float"] * len(ts)) else None)
            if want is None:
                raise MathError(f"{op.lower()} does not apply to ({', '.join(TYPE_SYMBOL[t] for t in ts)})", line)
            args = [((["float", float(e[1])] if e[0] == "int" else ["TO_FLOAT", e]), "float")
                    if t == "int" and w == "float" else (e, t) for (e, t), w in zip(args, want)]
            ts = want
            rt = spec.result_type(ts)
        return [op, *[e for e, _ in args]], rt

    @staticmethod
    def unify(a: tuple, b: tuple) -> tuple[tuple, tuple]:
        (ea, ta), (eb, tb) = a, b
        if ta == tb:
            return a, b
        if {ta, tb} == {"int", "float"}:
            return ((["TO_FLOAT", ea], "float") if ta == "int" else a,
                    (["TO_FLOAT", eb], "float") if tb == "int" else b)
        raise MathError(f"the branches have different types ({TYPE_SYMBOL[ta]} and {TYPE_SYMBOL[tb]})")

    # -- tail position: the function's result
    def tail(self, e, line) -> list:
        k = e[0]
        if k == "cases":
            return self.tail_cases(e[1], line)
        if k == "let":
            self.scope.append({})
            out = []
            for name, v in e[1]:
                st, ir, t = self.expr(v, line)
                out += st + [{"k": "assign", "target": self.bind(name, t), "value": ir}]
            out += self.tail(e[2], line)
            self.scope.pop()
            return out
        st, ir, t = self.expr(e, line)
        if self.ret == "float" and t == "int":
            ir, t = ["TO_FLOAT", ir], "float"
        self.ret_types.add(t)
        return st + [{"k": "return", "value": ir}]

    def tail_cases(self, cases, line) -> list:
        if cases[-1][1] is not None:
            raise MathError("the cases are not exhaustive: end them with `otherwise` (a partial function has no "
                            "value outside its cases)", line)
        if len(cases) == 1:
            return self.tail(cases[0][0], line)
        (e, c), rest = cases[0], cases[1:]
        st, cir, ct = self.expr(c, line)
        if ct != "bool":
            raise MathError(f"a case condition must be 𝔹, found {TYPE_SYMBOL[ct]}", line)
        return st + [{"k": "if", "cond": cir, "then": self.tail(e, line), "else": self.tail_cases(rest, line)}]

    # -- expressions: (statements to run first, IR expression, type)
    def expr(self, e, line) -> tuple[list, list, str]:
        k = e[0]
        if k == "num":
            return [], ["int", e[1]], "int"
        if k == "real":
            return [], ["float", e[1]], "float"
        if k == "bool":
            return [], ["bool", e[1]], "bool"
        if k == "pi":
            return [], ["float", math.pi], "float"
        if k == "name":
            ir = self.lookup(e[1])
            if ir is not None:
                return [], ["var", ir], self.types[ir]
            if e[1] == "e":
                return [], ["float", math.e], "float"
            if e[1] in self.low.constants:
                return [], ["CALL", e[1]], self.low.sig_ret(e[1], line)
            raise MathError(f"{e[1]!r} is not a parameter, a binding or a constant", line)
        if k == "neg":
            st, ir, t = self.expr(e[1], line)
            if ir[0] in ("int", "float") and not isinstance(ir[1], bool):
                return st, [ir[0], -ir[1]], t
            node, rt = self.apply("NEG", [(ir, t)], line)
            return st, node, rt
        if k == "not":
            st, ir, t = self.expr(e[1], line)
            if t != "bool":
                raise MathError(f"¬ needs 𝔹, found {TYPE_SYMBOL[t]}", line)
            return st, ["NOT", ir], "bool"
        if k in ("and", "or"):
            sa, a, ta = self.expr(e[1], line)
            sb, b, tb = self.expr(e[2], line)
            if ta != "bool" or tb != "bool":
                raise MathError(f"{'∧' if k == 'and' else '∨'} needs 𝔹 on both sides", line)
            if not sb:
                return sa, [k.upper(), a, b], "bool"
            tmp = self.fresh("b", "bool")         # the right side has statements: keep it lazy
            then = sb + [{"k": "assign", "target": tmp, "value": b}]
            other = [{"k": "assign", "target": tmp, "value": ["bool", k == "or"]}]
            return sa + [{"k": "if", "cond": a, "then": then if k == "and" else other,
                          "else": other if k == "and" else then}], ["var", tmp], "bool"
        if k == "cmp":
            stmts, parts = [], []
            vals = [self.expr(x, line) for x in e[1]]
            for (s_, _, _) in vals:
                stmts += s_
            for i, op in enumerate(e[2]):
                a, b = (vals[i][1], vals[i][2]), (vals[i + 1][1], vals[i + 1][2])
                if a[1] != b[1]:
                    a, b = self.unify(a, b)
                node, _ = self.apply(op, [a, b], line)
                parts.append(node)
            out = parts[0]
            for p in parts[1:]:
                out = ["AND", out, p]
            return stmts, out, "bool"
        if k == "bin":
            return self.binary(e[1], e[2], e[3], line)
        if k == "pow":
            sa, a, ta = self.expr(e[1], line)
            sb, b, tb = self.expr(e[2], line)
            if ta == "int" and tb == "int" and not (b[0] == "int" and b[1] < 0):
                return sa + sb, ["POW", a, b], "int"
            node, rt = self.apply("POW", [(a, ta), (b, tb)], line)
            return sa + sb, node, rt
        if k == "abs":
            st, ir, t = self.expr(e[1], line)
            node, rt = self.apply("ABS", [(ir, t)], line)
            return st, node, rt
        if k in ("floor", "ceil"):
            inner = e[1]
            if k == "floor" and inner[0] == "bin" and inner[1] in ("/", "÷"):
                sa, a, ta = self.expr(inner[2], line)
                sb, b, tb = self.expr(inner[3], line)
                if ta == "int" and tb == "int":
                    return sa + sb, ["FLOORDIV", a, b], "int"
            st, ir, t = self.expr(inner, line)
            if t == "int":
                return st, ir, "int"
            node, _ = self.apply("FLOOR" if k == "floor" else "CEIL", [(ir, t)], line)
            return st, ["TRUNC_INT", node], "int"
        if k == "sqrt":
            st, ir, t = self.expr(e[1], line)
            node, rt = self.apply("FSQRT", [(ir, t)], line)
            return st, node, rt
        if k == "fact":
            return self.expr(("prod", "cm_k", ("num", 1), e[1], ("name", "cm_k")), line)
        if k in ("sum", "prod"):
            return self.big(e, line)
        if k == "call":
            return self.call(e[1], e[2], line)
        if k == "cases":
            return self.expr_cases(e[1], line)
        if k == "let":
            self.scope.append({})
            stmts = []
            for name, v in e[1]:
                st, ir, t = self.expr(v, line)
                stmts += st + [{"k": "assign", "target": self.bind(name, t), "value": ir}]
            st, ir, t = self.expr(e[2], line)
            self.scope.pop()
            return stmts + st, ir, t
        raise MathError(f"cannot lower {k}", line)

    def binary(self, op, x, y, line):
        sa, a, ta = self.expr(x, line)
        sb, b, tb = self.expr(y, line)
        st = sa + sb
        if op == "+":
            node, rt = self.apply("ADD", [(a, ta), (b, tb)], line)
        elif op == "-":
            node, rt = self.apply("SUB", [(a, ta), (b, tb)], line)
        elif op == "·":
            node, rt = self.apply("MUL", [(a, ta), (b, tb)], line)
        elif op == "/":
            node, rt = self.apply("DIV", [(a, ta), (b, tb)], line)
        elif op == "÷":
            if ta == "int" and tb == "int":
                node, rt = ["FLOORDIV", a, b], "int"
            else:
                d, _ = self.apply("DIV", [(a, ta), (b, tb)], line)
                node, rt = ["FLOOR", d], "float"
        elif op == "mod":
            if ta != "int" or tb != "int":
                raise MathError("mod is defined on ℤ here (a float remainder has two conventions; write "
                                "fmod(a, b) for C's)", line)
            node, rt = ["MOD", a, b], "int"
        else:
            raise MathError(f"operator {op}", line)
        return st, node, rt

    def big(self, e, line):
        kind, var, lo, hi, body = e
        sl, lir, lt = self.expr(lo, line)
        sh, hir, ht = self.expr(hi, line)
        if lt != "int" or ht != "int":
            raise MathError(f"{'Σ' if kind == 'sum' else 'Π'} bounds must be ℤ", line)
        self.scope.append({})
        iv = self.bind(var, "int")
        # the body's type decides the accumulator's; it is typed once, with the index bound
        sb, bir, bt = self.expr(body, line)
        self.scope.pop()
        if bt not in ("int", "float"):
            raise MathError(f"{'Σ' if kind == 'sum' else 'Π'} over {TYPE_SYMBOL[bt]}", line)
        acc = self.fresh("sum" if kind == "sum" else "prod", bt)
        start = ["int", 0] if kind == "sum" else ["int", 1]
        if bt == "float":
            start = ["float", float(start[1])]
        stop = hir[1] + 1 if hir[0] == "int" else ["ADD", hir, ["int", 1]]
        stop = ["int", stop] if isinstance(stop, int) else stop
        loop = {"k": "for_range", "var": iv, "start": lir, "stop": stop, "step": ["int", 1],
                "counter": self.fresh("it", "int"), "stop_var": self.fresh("stop", "int"),
                "body": sb + [{"k": "assign", "target": acc,
                               "value": ["ADD" if kind == "sum" else "MUL", ["var", acc], bir]}]}
        return sl + sh + [{"k": "assign", "target": acc, "value": start}, loop], ["var", acc], bt

    def call(self, name, args, line):
        vals = [self.expr(a, line) for a in args]
        stmts = [s for v in vals for s in v[0]]
        typed = [(ir, t) for _, ir, t in vals]
        if name in self.low.fn_names:
            ptypes = self.low.param_types(name)
            if len(ptypes) != len(typed):
                raise MathError(f"{name} takes {len(ptypes)} arguments, given {len(typed)}", line)
            conv = []
            for (ir, t), want in zip(typed, ptypes):
                if t == want:
                    conv.append(ir)
                elif t == "int" and want == "float":
                    conv.append(["TO_FLOAT", ir])
                else:
                    raise MathError(f"{name}: an argument is {TYPE_SYMBOL[t]}, the parameter {TYPE_SYMBOL[want]}", line)
            return stmts, ["CALL", name, *conv], self.low.sig_ret(name, line)
        lname = name.lower()
        op = BUILTINS.get(lname) or (name.upper() if name.upper() in self.low.ops else None)
        if op is None:
            raise MathError(f"unknown function {name!r}", line)
        if op in ("MIN", "MAX") and len(typed) > 2:
            acc = typed[0]
            for x in typed[1:]:
                a, b = self.unify(acc, x)
                acc = tuple(self.apply(op, [a, b], line))
            return stmts, acc[0], acc[1]
        if op in ("MIN", "MAX") and len(typed) == 2:
            typed = list(self.unify(typed[0], typed[1]))
        if op == "TO_FLOAT" and typed and typed[0][1] == "float":
            return stmts, typed[0][0], "float"
        spec = self.low.ops[op]
        if spec.arity != len(typed):
            raise MathError(f"{name} takes {spec.arity} arguments, given {len(typed)}", line)
        node, rt = self.apply(op, typed, line)
        return stmts, node, rt

    def expr_cases(self, cases, line):
        if cases[-1][1] is not None:
            raise MathError("inline cases must end with `otherwise`", line)
        if len(cases) == 1:
            return self.expr(cases[0][0], line)
        (e, c), rest = cases[0], cases[1:]
        sc, cir, ct = self.expr(c, line)
        if ct != "bool":
            raise MathError(f"a case condition must be 𝔹, found {TYPE_SYMBOL[ct]}", line)
        sa, a, ta = self.expr(e, line)
        sb, b, tb = self.expr_cases(rest, line)
        (a, ta), (b, tb) = self.unify((a, ta), (b, tb))
        if not sa and not sb:
            return sc, ["IF_EXPR", cir, a, b], ta
        tmp = self.fresh("v", ta)                # a branch has statements: an if keeps it lazy
        return sc + [{"k": "if", "cond": cir, "then": sa + [{"k": "assign", "target": tmp, "value": a}],
                      "else": sb + [{"k": "assign", "target": tmp, "value": b}]}], ["var", tmp], ta


class Lowerer:
    def __init__(self, mod: MathModule, ops: dict[str, OpSpec]):
        self.mod = mod
        self.ops = ops
        OP_LOWER_OK.update(ops)
        self.defs: dict[str, list[Definition]] = {}
        for d in mod.definitions:
            self.defs.setdefault(d.name, []).append(d)
        self.fn_names = set(self.defs)
        self.constants = {n for n, ds in self.defs.items() if all(not d.params for d in ds)}
        self.reserved_names = set(BUILTINS)
        self.ret_guess: dict[str, str] = {}

    def param_names(self, name: str) -> list[str]:
        ds = self.defs[name]
        arity = {len(d.params) for d in ds}
        if len(arity) != 1:
            raise MathError(f"{name} is defined with different numbers of arguments", ds[0].line)
        out = []
        for i in range(arity.pop()):
            named = [d.params[i] for d in ds if isinstance(d.params[i], str)]
            out.append(named[0] if named else f"x{i + 1}")
        return out

    def param_types(self, name: str) -> list[str]:
        sig = self.mod.signatures.get(name)
        n = len(self.param_names(name))
        if sig and sig[0]:
            if len(sig[0]) != n:
                raise MathError(f"the signature of {name} has {len(sig[0])} arguments, the definition {n}")
            return ["int" if t == "nat" else t for t in sig[0]]
        return [("bool" if any(isinstance(d.params[i], tuple) and isinstance(d.params[i][1], bool)
                               for d in self.defs[name]) else
                 "float" if any(isinstance(d.params[i], tuple) and isinstance(d.params[i][1], float)
                                for d in self.defs[name]) else "int") for i in range(n)]

    def sig_ret(self, name: str, line=None) -> str:
        sig = self.mod.signatures.get(name)
        if sig:
            return "int" if sig[1] == "nat" else sig[1]
        return self.ret_guess.get(name, "int")

    def function(self, name: str) -> dict:
        ds = self.defs[name]
        params = self.param_names(name)
        ptypes = self.param_types(name)
        sig = self.mod.signatures.get(name)
        ret = ("int" if sig[1] == "nat" else sig[1]) if sig else None
        fl = _FnLower(self, name, params, ptypes, ret)
        line = ds[0].line
        # one equation per definition; pattern arguments become guards, so the cases chain in order
        cases = []
        where = []
        domain = []
        for d in ds:
            guards = []
            for p, pn in zip(d.params, params):
                if isinstance(p, tuple):
                    lit = p[1]
                    leaf = ("bool", lit) if isinstance(lit, bool) else ("real", lit) if isinstance(lit, float) \
                        else ("num", lit)
                    guards.append(("cmp", [("name", pn), leaf], ["CMP_EQ"]))
                elif p != pn:
                    raise MathError(f"{name}: argument {p!r} is named {pn!r} in another equation (use one name)",
                                    d.line)
            if d.where and len(ds) > 1:
                raise MathError(f"{name}: `where` with several equations; put the bindings in one equation",
                                d.line)
            where += d.where
            domain += d.domain
            for e, c in d.cases:
                cond = c
                for g in reversed(guards):
                    cond = g if cond is None else ("and", g, cond)
                cases.append((e, cond))
        body = ("cases", cases) if len(cases) > 1 or cases[0][1] is not None else cases[0][0]
        if where:
            body = ("let", where, body)
        stmts = fl.tail(body, line)
        if ret is None:
            if len(fl.ret_types) == 1:
                ret = next(iter(fl.ret_types))
            elif fl.ret_types == {"int", "float"}:
                ret = "float"
                fl2 = _FnLower(self, name, params, ptypes, "float")
                stmts = fl2.tail(body, line)
                fl = fl2
            else:
                raise MathError(f"{name}: the cases have types {sorted(fl.ret_types)}; add a signature", line)
        elif fl.ret_types - {ret}:
            raise MathError(f"{name} is declared → {TYPE_SYMBOL[ret]} but a case is "
                            f"{', '.join(TYPE_SYMBOL[t] for t in sorted(fl.ret_types - {ret}))}"
                            + (" (write ⌊a/b⌋ for integer division)" if ret == "int" else ""), line)
        fn = {"name": name, "params": [{"name": p, "type": t} for p, t in zip(params, ptypes)],
              "returns": ret, "locals": dict(fl.locals), "body": stmts}
        requires = []
        for c in domain:
            st, cir, ct = fl.expr(c, line)
            if st or ct != "bool":
                raise MathError(f"{name}: a domain condition must be a plain 𝔹 expression", line)
            requires += _split_and(cir)
        if requires:
            fn["requires"] = requires
            fn["locals"] = dict(fl.locals)
        if sig and sig[0]:
            nat = [p for p, t in zip(params, sig[0]) if t == "nat"]
            if nat:
                fn["nat_params"] = nat
                fn.setdefault("requires", [])
                fn["requires"] = [["CMP_GE", ["var", p], ["int", 0]] for p in nat] + fn["requires"]
        return _tail_calls_to_loop(fn)

    def module(self) -> dict:
        # return types of unsigned functions: guess int, then lower until the guesses stop changing
        for _ in range(4):
            changed = False
            for n in self.defs:
                if n in self.mod.signatures:
                    continue
                try:
                    r = self.function(n)["returns"]
                except MathError:
                    continue
                if self.ret_guess.get(n, "int") != r:
                    self.ret_guess[n] = r
                    changed = True
            if not changed:
                break
        fns = [self.function(n) for n in self.defs]
        return {"entry": fns[0]["name"] if fns else None, "functions": fns}


def _split_and(e) -> list:
    return _split_and(e[1]) + _split_and(e[2]) if e[0] == "AND" else [e]


def _tail_calls_to_loop(fn: dict) -> dict:
    """A function whose self-calls are all ``return f(...)`` becomes a loop: the parameters are re-bound in
    parallel and the loop goes round again (no stack growth, so a loop emitted as an equation comes back as one)."""
    name = fn["name"]
    tail_sites, other = 0, 0

    def scan(body):
        nonlocal tail_sites, other
        for s in body:
            for key in ("value", "cond", "start", "stop", "step", "index"):
                e = s.get(key)
                if not isinstance(e, list):
                    continue
                top = s["k"] == "return" and key == "value" and e[0] == "CALL" and e[1] == name
                for sub in _walk(e):
                    if sub[0] == "CALL" and sub[1] == name:
                        if top and sub is e:
                            tail_sites += 1
                        else:
                            other += 1
            for key in ("then", "else", "body"):
                if key in s:
                    if key == "body" and s["k"] in ("while", "for_range"):
                        n0 = tail_sites
                        scan(s[key])
                        if tail_sites != n0:          # a return-call inside a loop: continue would hit that loop
                            other += 1
                    else:
                        scan(s[key])

    scan(fn["body"])
    if not tail_sites or other:
        return fn
    locals_ = dict(fn["locals"])
    params = fn["params"]
    temps = []
    for p in params:
        t = f"cm_next_{p['name']}"
        locals_[t] = p["type"]
        temps.append(t)
    go = "cm_go"
    locals_[go] = "bool"

    def rewrite(body):
        out = []
        for s in body:
            if s["k"] == "return" and isinstance(s.get("value"), list) and s["value"][0] == "CALL" \
                    and s["value"][1] == name:
                args = s["value"][2:]
                out += [{"k": "assign", "target": t, "value": a} for t, a in zip(temps, args)]
                out += [{"k": "assign", "target": p["name"], "value": ["var", t]} for p, t in zip(params, temps)]
                out.append({"k": "continue"})
                continue
            s2 = dict(s)
            for key in ("then", "else"):
                if key in s2:
                    s2[key] = rewrite(s2[key])
            out.append(s2)
        return out

    body = [{"k": "assign", "target": go, "value": ["bool", True]},
            {"k": "while", "cond": ["var", go], "body": rewrite(fn["body"])},
            {"k": "return", "value": _zero(fn["returns"])}]
    return {**fn, "locals": locals_, "body": body}


def _walk(e):
    if isinstance(e, list) and e:
        yield e
        if e[0] not in LEAVES:
            for a in e[(2 if e[0] in ("CALL", "LOAD") else 1):]:
                yield from _walk(a)


def lift_text(text: str, ops: dict[str, OpSpec], name: str = "math") -> dict:
    """Math text -> an IR module {"entry", "functions", "tests"}."""
    mod = parse(text, name)
    low = Lowerer(mod, ops)
    module = low.module()
    module["name"] = mod.name
    tests = []
    for e, line in mod.tests:
        fl = _FnLower(low, "cm_test", [], [], "bool")
        st, ir, t = fl.expr(e, line)
        tests.append({"line": line, "text": _test_text(e), "fn": {"name": f"cm_test_{line}", "params": [],
                      "returns": t, "locals": dict(fl.locals), "body": st + [{"k": "return", "value": ir}]}})
    module["tests"] = tests
    return module


def _test_text(e) -> str:
    try:
        return render_surface(e)
    except Exception:  # noqa: BLE001 -- a label only
        return "test"


def run_tests(module: dict, ops) -> list[dict]:
    from .ir import Interpreter, IRError
    out = []
    for t in module.get("tests") or []:
        mod = {"functions": [*module["functions"], t["fn"]]}
        try:
            v = Interpreter(mod, ops).call(t["fn"]["name"], [])
            out.append({"line": t["line"], "test": t["text"], "ok": v is True, "value": v})
        except (IRError, ArithmeticError, ValueError, RecursionError) as exc:
            out.append({"line": t["line"], "test": t["text"], "ok": False, "error": str(exc)})
    return out


# ---- emission: card IR -> math ------------------------------------------------------------------------------------
# Terms for emission: ("ir", expr) an IR expression; ("cases", [(term, cond_ir | None)]); ("let", name, ir, term);
# ("call", fname, [ir]) a tail call to a generated equation.

class _Emit:
    MAX_DUP = 6           # an `if` whose continuation is bigger than this many statements gets its own equation

    def __init__(self, fn: dict, module: dict):
        bad = [s["k"] for s in _stmts(fn["body"]) if s["k"] in ("store", "do", "switch")]
        if fn.get("returns") == "void" or bad or module.get("globals") or module.get("arrays"):
            raise EmitGap("math: machine state (globals, arrays, stores, switch, void functions) is not emitted "
                          "as equations")
        for s in _stmts(fn["body"]):
            for key in ("value", "cond", "start", "stop", "step"):
                if isinstance(s.get(key), list):
                    for e in _walk(s[key]):
                        if e[0] in ("LOAD", "RAW"):
                            raise EmitGap(f"math: {e[0]} has no notation")
        self.fn = fn
        self.name = fn["name"]
        self.types = {p["name"]: p["type"] for p in fn["params"]}
        self.types.update(fn.get("locals") or {})
        read = set()
        for s in _stmts(fn["body"]):
            for key in ("value", "cond", "start", "stop", "step"):
                if isinstance(s.get(key), list):
                    read |= {e[1] for e in _walk(s[key]) if e[0] == "var"}
            if s["k"] == "for_range":
                read |= {s["counter"], s["stop_var"], s["var"]}
        # the state an equation carries: every parameter and every local that is ever read, in a stable order
        self.state = [p["name"] for p in fn["params"]] + [n for n in (fn.get("locals") or {}) if n in read]
        self.eqs: list[tuple[str, list[str], object]] = []
        self.k = 0
        assigns: dict[str, list] = {}
        for s in _stmts(fn["body"]):
            if s["k"] == "assign":
                assigns.setdefault(s["target"], []).append(s["value"])
        self.always_true = {v for v, vals in assigns.items() if all(x == ["bool", True] for x in vals)
                            and v not in self.types or v in assigns and all(x == ["bool", True] for x in vals)
                            and v not in {p["name"] for p in fn["params"]}}

    def new_eq(self, kind: str) -> str:
        self.k += 1
        return f"{self.name}_{kind}{self.k}"

    def call(self, eq: str, bound: set) -> tuple:
        return ("call", eq, [["var", v] if v in bound else _zero(self.types[v]) for v in self.state])

    def run(self) -> list[tuple[str, list[str], object]]:
        bound = {p["name"] for p in self.fn["params"]}
        end = ("ir", _zero(self.fn["returns"]))          # falling off the end is unreachable in a valid IR fn
        term = self.block(self.fn["body"], bound, end, None, None)
        self.eqs.insert(0, (self.name, [p["name"] for p in self.fn["params"]], term))
        return simplify(self.eqs, self.name)

    def block(self, body, bound, nxt, brk, cont):
        """The term that ``body`` computes, given the continuation terms for falling through, break, continue."""
        if not body:
            return nxt
        s, rest = body[0], body[1:]
        k = s["k"]
        if k == "assign":
            b2 = bound | {s["target"]}
            return ("let", s["target"], s["value"], self.block(rest, b2, nxt, brk, cont))
        if k == "return":
            return ("ir", s["value"])
        if k == "break":
            return brk
        if k == "continue":
            return cont
        if k == "if":
            after = self.join(rest, bound, nxt, brk, cont)
            then_b = _assigned(s["then"])
            else_b = _assigned(s.get("else") or [])
            t = self.block(s["then"], bound, after(bound | then_b), brk, cont)
            e = self.block(s.get("else") or [], bound, after(bound | else_b), brk, cont)
            return ("cases", [(t, s["cond"]), (e, None)])
        if k == "while":
            cond = s["cond"]
            if cond == ["bool", True] or cond[0] == "var" and cond[1] in self.always_true:
                cond = None
            return self.loop(cond, s["body"], [], rest, bound, nxt, brk, cont)
        if k == "for_range":
            it, stop = s["counter"], s["stop_var"]
            neg = s["step"][1] < 0
            init = [{"k": "assign", "target": it, "value": s["start"]},
                    {"k": "assign", "target": stop, "value": s["stop"]}]
            body2 = [{"k": "assign", "target": s["var"], "value": ["var", it]},
                     {"k": "assign", "target": it, "value": ["ADD", ["var", it], s["step"]]}, *s["body"]]
            cond = ["CMP_GT" if neg else "CMP_LT", ["var", it], ["var", stop]]
            return self.lets(init, bound, lambda b2: self.loop(cond, body2, [], rest, b2, nxt, brk, cont))
        raise EmitGap(f"math: statement {k!r}")

    def lets(self, assigns, bound, k):
        if not assigns:
            return k(bound)
        a = assigns[0]
        return ("let", a["target"], a["value"], self.lets(assigns[1:], bound | {a["target"]}, k))

    def join(self, rest, bound, nxt, brk, cont):
        """The continuation after an ``if``: the rest inline when it is small, else a call to a new equation."""
        if not rest:
            return lambda b: nxt
        if _size(rest) <= self.MAX_DUP and not any(s["k"] in ("while", "for_range") for s in rest):
            return lambda b: self.block(rest, b, nxt, brk, cont)
        eq = self.new_eq("then")
        everything = set(self.state)
        self.eqs.append((eq, list(self.state), self.block(rest, everything, nxt, brk, cont)))
        return lambda b: self.call(eq, b)

    def loop(self, cond, body, _unused, rest, bound, nxt, brk, cont):
        eq = self.new_eq("loop")
        everything = set(self.state)
        after_eq = None
        if rest or not _is_value(nxt):
            after_eq = self.new_eq("done")
        exit_term = self.call(after_eq, everything) if after_eq else nxt
        again = self.call(eq, everything)
        slot = len(self.eqs)
        self.eqs.append(None)
        inner = self.block(body, everything, again, exit_term, again)
        self.eqs[slot] = (eq, list(self.state), inner if cond is None else
                          ("cases", [(inner, cond), (exit_term, None)]))
        if after_eq:
            self.eqs.append((after_eq, list(self.state), self.block(rest, everything, nxt, brk, cont)))
        return self.call(eq, bound)


# ---- simplification of emitted equations ------------------------------------------------------------------------
# Only rewrites that keep the meaning exactly: parameters no equation reads are dropped (a least fixpoint over the
# calls), lets whose name is never read are dropped when their value cannot fail, a let read once is substituted
# when its value cannot fail and none of its variables is re-bound before the use, equations nothing calls are
# dropped, and a function that only forwards its parameters to a loop equation becomes that equation.

TOTAL_OPS = {"ADD", "SUB", "MUL", "NEG", "ABS", "MIN", "MAX", "CMP_EQ", "CMP_NE", "CMP_LT", "CMP_LE", "CMP_GT",
             "CMP_GE", "AND", "OR", "NOT", "IF_EXPR", "BIT_AND", "BIT_OR", "BIT_XOR", "BIT_NOT", "TO_FLOAT",
             "SQUARE", "GCD"}


def _total(e) -> bool:
    """An IR expression that cannot raise (moving or dropping it cannot change an error into a value)."""
    return all(x[0] in LEAVES or x[0] in TOTAL_OPS for x in _walk(e))


def _vars(e) -> set:
    return {x[1] for x in _walk(e) if x[0] == "var"}


def _fv(t, used: dict) -> set:
    k = t[0]
    if k == "ir":
        return _vars(t[1])
    if k == "call":
        idx = used.get(t[1])
        out = set()
        for i, a in enumerate(t[2]):
            if idx is None or i in idx:
                out |= _vars(a)
        return out
    if k == "let":
        return _vars(t[2]) | (_fv(t[3], used) - {t[1]})
    out = set()
    for v, c in t[1]:
        out |= _fv(v, used)
        if c is not None:
            out |= _vars(c)
    return out


def _map_calls(t, fn):
    k = t[0]
    if k == "call":
        return fn(t)
    if k == "let":
        return ("let", t[1], t[2], _map_calls(t[3], fn))
    if k == "cases":
        return ("cases", [(_map_calls(v, fn), c) for v, c in t[1]])
    return t


def _calls(t) -> set:
    found = set()

    def visit(c):
        found.add(c[1])
        return c
    _map_calls(t, visit)
    return found


def _count(t, name) -> int:
    """Free occurrences of ``name`` in a term (in every argument of a call)."""
    k = t[0]
    if k == "ir":
        return sum(1 for x in _walk(t[1]) if x[0] == "var" and x[1] == name)
    if k == "call":
        return sum(_count(("ir", a), name) for a in t[2])
    if k == "let":
        n = _count(("ir", t[2]), name)
        return n if t[1] == name else n + _count(t[3], name)
    return sum(_count(v, name) + (_count(("ir", c), name) if c is not None else 0) for v, c in t[1])


def _subst_expr(e, name, value):
    if isinstance(e, list) and e:
        if e[0] == "var":
            return value if e[1] == name else e
        if e[0] in LEAVES:
            return e
        start = 2 if e[0] in ("CALL", "LOAD") else 1
        return e[:start] + [_subst_expr(a, name, value) for a in e[start:]]
    return e


def _subst(t, name, value, blocked: set):
    """Substitute ``value`` for ``name``; None when a variable of ``value`` is re-bound before a use."""
    k = t[0]
    if k == "ir":
        return ("ir", _subst_expr(t[1], name, value))
    if k == "call":
        return ("call", t[1], [_subst_expr(a, name, value) for a in t[2]])
    if k == "let":
        v2 = _subst_expr(t[2], name, value)
        if t[1] == name:
            return ("let", t[1], v2, t[3])
        if _count(t[3], name) == 0:
            return ("let", t[1], v2, t[3])
        if t[1] in blocked:
            return None
        body = _subst(t[3], name, value, blocked)
        return None if body is None else ("let", t[1], v2, body)
    cases = []
    for v, c in t[1]:
        v2 = _subst(v, name, value, blocked) if _count(v, name) else v
        if v2 is None:
            return None
        cases.append((v2, _subst_expr(c, name, value) if c is not None else None))
    return ("cases", cases)


def _tidy(t, used):
    k = t[0]
    if k == "let":
        body = _tidy(t[3], used)
        n = _count(body, t[1])
        if n == 0 and _total(t[2]):
            return body
        if n == 1 and len(list(_walk(t[2]))) <= 12 and (
                _total(t[2]) or not any(x[0] == "CALL" for x in _walk(t[2])) and _strict(body, t[1])):
            sub = _subst(body, t[1], t[2], _vars(t[2]))
            if sub is not None:
                return sub
        return ("let", t[1], t[2], body)
    if k == "cases":
        return ("cases", [(_tidy(v, used), c) for v, c in t[1]])
    return t


def _strict(t, name) -> bool:
    """The (single) use of ``name`` is evaluated whenever the term is: not inside a case or a lazy operator."""
    k = t[0]
    if k == "ir":
        return _strict_expr(t[1], name)
    if k == "call":
        return all(_strict_expr(a, name) for a in t[2])
    if k == "let":
        if _count(("ir", t[2]), name):
            return _strict_expr(t[2], name)
        return _strict(t[3], name)
    first_v, first_c = t[1][0]
    if first_c is not None and _count(("ir", first_c), name):
        return _strict_expr(first_c, name)
    return False


def _strict_expr(e, name) -> bool:
    if e[0] == "var":
        return True
    if e[0] in LEAVES:
        return True
    if e[0] in ("AND", "OR", "IF_EXPR"):
        return not any(_count(("ir", a), name) for a in e[2:]) and _strict_expr(e[1], name)
    start = 2 if e[0] in ("CALL", "LOAD") else 1
    return all(_strict_expr(a, name) for a in e[start:])


def _inline_trivial(terms: dict, params: dict, main: str) -> None:
    """``g(x) = <expression>`` (no recursion) is substituted at its call sites when its arguments are call-free."""
    for n in [n for n in terms if n != main]:
        t = terms[n]
        if t[0] == "ir" and any(x[0] == "CALL" for x in _walk(t[1])) or t[0] not in ("ir", "call") or \
                t[0] == "call" and (t[1] == n or any(x[0] == "CALL" for a in t[2] for x in _walk(a))):
            continue

        def inline(c, n=n, t=t):
            if c[1] != n or any(x[0] == "CALL" for a in c[2] for x in _walk(a)):
                return c
            tmp = {p: f"\0{i}" for i, p in enumerate(params[n])}

            def sub(e):
                for p, q in tmp.items():
                    e = _subst_expr(e, p, ["var", q])
                for p, a in zip(params[n], c[2]):
                    e = _subst_expr(e, tmp[p], a)
                return e
            if t[0] == "ir":
                return ("ir", sub(t[1]))
            return ("call", t[1], [sub(a) for a in t[2]])
        for m in list(terms):
            terms[m] = _map_calls(terms[m], inline)


def _rename(t, ren: dict):
    def r(e):
        if isinstance(e, list) and e:
            if e[0] == "var":
                return ["var", ren.get(e[1], e[1])]
            if e[0] in LEAVES:
                return e
            start = 2 if e[0] in ("CALL", "LOAD") else 1
            return e[:start] + [r(a) for a in e[start:]]
        return e
    k = t[0]
    if k == "ir":
        return ("ir", r(t[1]))
    if k == "call":
        return ("call", t[1], [r(a) for a in t[2]])
    if k == "let":
        return ("let", ren.get(t[1], t[1]), r(t[2]), _rename(t[3], ren))
    return ("cases", [(_rename(v, ren), r(c) if c is not None else None) for v, c in t[1]])


def _binders(t) -> set:
    if t[0] == "let":
        return {t[1]} | _binders(t[3])
    if t[0] == "cases":
        return set().union(*(_binders(v) for v, _ in t[1]))
    return set()


def _readable(name: str, params: list, t, taken: set) -> tuple[list, object]:
    """Generated names (cm_it2, cm_next_b) read as it, next_b when that clashes with nothing in the equation."""
    names = set(params) | _binders(t) | _fv(t, {})
    ren = {}
    used = set(names) | taken
    for v in sorted(names):
        m = re.fullmatch(r"cm_([A-Za-z_]+?)_?\d*", v)
        if not m:
            continue
        base = m.group(1).rstrip("_") or "v"
        if base in KEYWORDS or base in BUILTINS or base in used or base in ren.values():
            continue
        ren[v] = base
        used.add(base)
    return [ren.get(p, p) for p in params], _rename(t, ren), ren


def simplify(eqs: list, main: str) -> list:
    eqs = [e for e in eqs if e is not None]
    params = {n: ps for n, ps, _ in eqs}
    terms = {n: t for n, _, t in eqs}
    gen = [n for n in params if n != main]
    used: dict[str, set] = {n: set() for n in gen}
    for _ in range(4):
        for _ in range(len(gen) + 2):
            changed = False
            for n in gen:
                fv = _fv(terms[n], used)
                idx = {i for i, p in enumerate(params[n]) if p in fv}
                if idx - used[n]:
                    used[n] |= idx
                    changed = True
            if not changed:
                break

        def prune(c):
            if c[1] in used:
                return ("call", c[1], [a for i, a in enumerate(c[2]) if i in used[c[1]]])
            return c
        for n in list(terms):
            terms[n] = _tidy(_map_calls(terms[n], prune), used)
        for n in gen:
            params[n] = [p for i, p in enumerate(params[n]) if i in used[n]]
        used = {n: set(range(len(params[n]))) for n in gen}
        # recompute from scratch on the pruned equations (lets may have gone, so fewer reads)
        used = {n: set() for n in gen}
    # forwarders: main(x..) = L(x..) with L's parameters equal to main's -> main takes L's equation
    t = terms[main]
    if t[0] == "call" and t[1] in params and params[t[1]] == params[main] and \
            [a for a in t[2]] == [["var", p] for p in params[main]]:
        loop = t[1]

        def rename(c):
            return ("call", main, c[2]) if c[1] == loop else c
        terms[main] = _map_calls(terms[loop], rename)
        for n in list(terms):
            terms[n] = _map_calls(terms[n], rename)
        del terms[loop]
    _inline_trivial(terms, params, main)
    # keep what the main equation reaches, in the order of first appearance
    order, todo = [], [main]
    while todo:
        n = todo.pop(0)
        if n in order or n not in terms:
            continue
        order.append(n)
        todo += sorted(_calls(terms[n]) - set(order), key=lambda x: [e[0] for e in eqs].index(x)
                       if x in params else 0)
    taken = set(terms) | {"e", "π"}
    out = []
    for n in order:
        if n == main:
            ps = params[n]
            _, t, ren = _readable(n, [], terms[n], taken | set(ps))
        else:
            ps, t, ren = _readable(n, params[n], terms[n], taken)
        out.append((n, ps, t, ren))
    return out


def _is_value(t) -> bool:
    return t is not None and t[0] in ("ir", "call")


def _assigned(body) -> set:
    out = set()
    for s in _stmts(body):
        if s["k"] == "assign":
            out.add(s["target"])
        elif s["k"] == "for_range":
            out |= {s["var"], s["counter"], s["stop_var"]}
    return out


def _size(body) -> int:
    return sum(1 for _ in _stmts(body))


def _stmts(body):
    for s in body:
        yield s
        for key in ("then", "else", "body", "default"):
            if key in s:
                yield from _stmts(s[key])
        for case in s.get("cases") or ():
            yield from _stmts(case["body"])


# ---- rendering ---------------------------------------------------------------------------------------------------
# Precedence (higher binds tighter): 1 or · 2 and · 3 not · 4 cmp · 5 + − · 6 · / ÷ mod · 7 unary − · 8 ^ · 9 atom

class Renderer:
    def __init__(self, latex: bool = False, fn_names: set | None = None):
        self.latex = latex
        self.fn_names = fn_names or set()

    def name(self, n: str) -> str:
        if self.latex and len(n) > 1:
            return r"\mathit{" + n.replace("_", r"\_") + "}"
        return n

    def fname(self, n: str) -> str:
        if self.latex:
            return r"\operatorname{" + n.replace("_", r"\_") + "}"
        return n

    def lit(self, e) -> str:
        if e[0] == "bool":
            return r"\mathrm{true}" if self.latex and e[1] else r"\mathrm{false}" if self.latex else \
                ("true" if e[1] else "false")
        if e[0] == "float":
            v = float(e[1])
            if v == math.pi:
                return r"\pi" if self.latex else "π"
            if v != v or v in (math.inf, -math.inf):
                raise EmitGap("math: a non-finite float literal")
            return repr(v)
        return str(int(e[1]))

    def wrap(self, text: str, mine: int, need: int) -> str:
        if mine >= need:
            return text
        return (r"\left(" + text + r"\right)") if self.latex else f"({text})"

    def sym(self, s: str) -> str:
        if not self.latex:
            return s
        return {"·": r"\cdot", "mod": r"\bmod", "¬": r"\neg ", "∧": r"\land", "∨": r"\lor"}[s]

    def rhs(self, e, need: int) -> str:
        """A right operand: a leading minus is parenthesised (``a - -3`` would read as a comment)."""
        text = self.expr(e, need)
        return self.wrap(text, 0, 1) if text.startswith("-") else text

    def expr(self, e, need: int = 0) -> str:
        """IR expression -> notation, parenthesised when its precedence is below ``need``."""
        t, p = self._expr(e)
        return self.wrap(t, p, need)

    def _expr(self, e) -> tuple[str, int]:
        L = self.latex
        head = e[0]
        if head == "var":
            return self.name(e[1]), 9
        if head in ("int", "float", "bool"):
            neg = head != "bool" and e[1] < 0
            return self.lit(e), 7 if neg else 9
        if head == "CALL":
            return self.fname(e[1]) + (r"\left(" if L else "(") + ", ".join(self.expr(a) for a in e[2:]) + \
                (r"\right)" if L else ")"), 9
        if head == "ADD" and isinstance(e[2], list) and e[2][0] in ("int", "float") and e[2][1] < 0:
            return self._expr(["SUB", e[1], [e[2][0], -e[2][1]]])
        if head == "TO_FLOAT" and isinstance(e[1], list) and e[1][0] == "int":
            return self._expr(["float", float(e[1][1])])
        if head == "ADD":
            return f"{self.expr(e[1], 5)} + {self.rhs(e[2], 6)}", 5
        if head == "SUB":
            return f"{self.expr(e[1], 5)} - {self.rhs(e[2], 6)}", 5
        if head == "MUL":
            return f"{self.expr(e[1], 6)} {self.sym('·')} {self.rhs(e[2], 7)}", 6
        if head == "DIV":
            if L:
                return r"\frac{" + self.expr(e[1]) + "}{" + self.expr(e[2]) + "}", 9
            return f"{self.expr(e[1], 6)} / {self.rhs(e[2], 7)}", 6
        if head == "FLOORDIV":
            if L:
                return r"\left\lfloor \frac{" + self.expr(e[1]) + "}{" + self.expr(e[2]) + r"} \right\rfloor", 9
            return f"⌊{self.expr(e[1], 6)} / {self.rhs(e[2], 7)}⌋", 9
        if head == "MOD":
            return f"{self.expr(e[1], 6)} {self.sym('mod')} {self.rhs(e[2], 7)}", 6
        if head == "POW":
            if L:
                return self.expr(e[1], 9) + "^{" + self.expr(e[2]) + "}", 8
            return f"{self.expr(e[1], 9)}^{self.rhs(e[2], 8)}", 8
        if head == "NEG":
            return f"-{self.rhs(e[1], 8)}", 7
        if head == "NOT":
            return f"{self.sym('¬')}{self.expr(e[1], 4)}", 3
        if head == "AND":
            return f"{self.expr(e[1], 2)} {self.sym('∧')} {self.expr(e[2], 3)}", 2
        if head == "OR":
            return f"{self.expr(e[1], 1)} {self.sym('∨')} {self.expr(e[2], 2)}", 1
        if head in CMP_SYMBOL:
            sym = (CMP_LATEX if L else CMP_SYMBOL)[head]
            return f"{self.expr(e[1], 5)} {sym} {self.rhs(e[2], 5)}", 4
        if head == "ABS":
            if L:
                return r"\left|" + self.expr(e[1]) + r"\right|", 9
            return f"|{self.expr(e[1])}|", 9
        if head == "TRUNC_INT" and isinstance(e[1], list) and e[1][0] in ("FLOOR", "CEIL"):
            lo, hi = (("⌊", "⌋"), ("⌈", "⌉"))[e[1][0] == "CEIL"]
            if L:
                lo, hi = ((r"\left\lfloor ", r" \right\rfloor"), (r"\left\lceil ", r" \right\rceil"))[e[1][0] == "CEIL"]
            return f"{lo}{self.expr(e[1][1])}{hi}", 9
        if head == "FSQRT":
            if L:
                return r"\sqrt{" + self.expr(e[1]) + "}", 9
            return f"√({self.expr(e[1])})", 9
        if head == "IF_EXPR":
            return self.inline_cases([(("ir", e[2]), e[1]), (("ir", e[3]), None)]), 9
        name = OP_NAME.get(head, head.lower())
        if name in self.fn_names:          # a module function with the op's name: spell the op card itself
            name = head
        if L:
            fn = "\\" + name if name in LATEX_FUNCS else r"\operatorname{" + name.replace("_", r"\_") + "}"
            return fn + r"\left(" + ", ".join(self.expr(a) for a in e[1:]) + r"\right)", 9
        return f"{name}({', '.join(self.expr(a) for a in e[1:])})", 9

    # -- terms
    def term(self, t) -> str:
        k = t[0]
        if k == "ir":
            return self.expr(t[1])
        if k == "call":
            return self.expr(["CALL", t[1], *t[2]])
        if k == "let":
            kw = (r"\operatorname{let} ", r" \operatorname{in} ") if self.latex else ("let ", " in ")
            return f"{kw[0]}{self.name(t[1])} = {self.expr(t[2])}{kw[1]}{self.term(t[3])}"
        if k == "cases":
            return self.inline_cases(t[1])
        raise EmitGap(f"math: term {k}")

    def inline_cases(self, cases) -> str:
        flat = _flatten_cases(cases)
        if self.latex:
            rows = [f"{self.term(v)} & " + (r"\text{if } " + self.expr(c) if c is not None else r"\text{otherwise}")
                    for v, c in flat]
            return r"\begin{cases} " + r" \\ ".join(rows) + r" \end{cases}"
        return "{ " + "; ".join(f"{self.term(v)} if {self.expr(c)}" if c is not None else
                                f"{self.term(v)} otherwise" for v, c in flat) + " }"

    def equation(self, name: str, params: list[str], term, types: dict, ret: str) -> str:
        """``name : T × T → T`` and the equation, top-level lets as where-bindings, top-level cases one per line."""
        L = self.latex
        sig_types = [TYPE_LATEX[types[p]] if L else TYPE_SYMBOL[types[p]] for p in params]
        arrow = r" \to " if L else " → "
        times = r" \times " if L else " × "
        sig = f"{self.fname(name) if L else name} : " + (times.join(sig_types) + arrow if params else "") + \
            (TYPE_LATEX[ret] if L else TYPE_SYMBOL[ret])
        head = f"{self.fname(name) if L else name}" + (("(" + ", ".join(self.name(p) for p in params) + ")")
                                                     if params else "")
        where = []
        while term[0] == "let":
            where.append((term[1], term[2]))
            term = term[3]
        # a where-binding may not read a name it shadows later in the same list: keep only a clean prefix
        lines = []
        if term[0] == "cases" and not L:
            flat = _flatten_cases(term[1])
            pad = " " * len(head)
            for i, (v, c) in enumerate(flat):
                lead = f"{head} = " if i == 0 else f"{pad} = "
                lines.append(lead + self.term(v) + (f"   if {self.expr(c)}" if c is not None else "   otherwise"))
        else:
            lines.append(f"{head} = {self.term(term)}")
        if where:
            if L:
                lines[-1] += r", \quad \text{where } " + ", ".join(f"{self.name(n)} = {self.expr(v)}" for n, v in where)
            else:
                lines.append("  where " + ",\n        ".join(f"{n} = {self.expr(v)}" for n, v in where))
        return sig + ("\n" if not L else r" \\" + "\n") + "\n".join(lines)


def _flatten_cases(cases) -> list:
    """{ a if c; { b if d; e otherwise } otherwise } -> [(a, c), (b, d), (e, None)]."""
    out = []
    for i, (v, c) in enumerate(cases):
        if c is None and v[0] == "cases" and i == len(cases) - 1:
            out += _flatten_cases(v[1])
        else:
            out.append((v, c))
    return out


def _where_safe(term) -> object:
    """Top-level lets become where-bindings only while no binding re-binds a name: ``let x = .. in let x = ..``
    stays inline (sequential), since where-bindings are read as one simultaneous block by a person."""
    return term


def emit_function(fn: dict, module: dict | None = None, latex: bool = False) -> str:
    """One IR function -> its equations (the function first, then the equations its loops became)."""
    module = module or {"functions": [fn]}
    em = _Emit(fn, module)
    eqs = em.run()
    names = {e[0] for e in eqs} | {f["name"] for f in module["functions"]}
    r = Renderer(latex, names)
    out = []
    for name, params, term, ren in eqs:
        types = {ren.get(k, k): v for k, v in em.types.items()}
        out.append(r.equation(name, params, term, types, fn["returns"]))
    return ("\n\n" if not latex else "\n").join(out)


def _normalize_lets(term):
    """Where-bindings read sequentially (each sees the ones before it), so a re-binding of a name is fine; but
    a binding that shadows a parameter used by an earlier binding is still sequential. Nothing to rewrite: the
    reader applies bindings in order."""
    return term


def emit_module(module: dict, latex: bool = False, only: list[str] | None = None) -> str:
    """Every function of an IR module as math (a .math file), callees first."""
    parts = []
    for fn in reversed(module["functions"]):
        if only is not None and fn["name"] not in only:
            continue
        parts.append(emit_function(fn, module, latex))
    if latex:
        return "\\begin{gathered}\n" + "\n\\\\[1ex]\n".join(parts) + "\n\\end{gathered}\n"
    return "\n\n".join(parts) + "\n"


def render_surface(e) -> str:
    """A compact rendering of a parsed (surface) expression: used for test labels."""
    k = e[0]
    if k in ("num", "real"):
        return repr(e[1])
    if k == "bool":
        return "true" if e[1] else "false"
    if k == "name":
        return e[1]
    if k == "call":
        return f"{e[1]}({', '.join(render_surface(a) for a in e[2])})"
    if k == "cmp":
        out = render_surface(e[1][0])
        for op, x in zip(e[2], e[1][1:]):
            out += f" {CMP_SYMBOL[op]} {render_surface(x)}"
        return out
    if k == "bin":
        return f"({render_surface(e[2])} {e[1]} {render_surface(e[3])})"
    return k


# ---- the language as a pipeline stage ----------------------------------------------------------------------------

def lift_file(ctx, path) -> dict:
    from pathlib import Path
    p = Path(path)
    return lift_text(p.read_text(encoding="utf-8"), ctx.ops, p.stem)


def function_cards(ctx, path, seed: int, samples: int = 24) -> tuple[list[dict], dict[str, list[str]]]:
    """Function cards for every function of a .math file (the IR is the reference, as for the card language)."""
    from pathlib import Path
    from types import SimpleNamespace

    from ..lang.run import function_cards as cards_from_module
    p = Path(path)
    try:
        module = lift_file(ctx, p)
    except MathError as exc:
        return [], {p.name: [str(exc)]}
    mod = SimpleNamespace(name=module["name"], path=str(p), functions={f["name"]: f for f in module["functions"]})
    cards = cards_from_module(ctx, mod, seed, samples)
    for c in cards:
        c["statement"] = c["statement"].replace("from the card language", "from mathematical notation")
        c["provenance"]["origin"] = f"math source {p.name}"
    return cards, {}


def round_trip(ctx, card_or_module: dict, inputs: list | None = None) -> dict:
    """lift(emit_math(f)) behaves like f: the math target's witness (sampled on f's vectors)."""
    from .ir import Interpreter, IRError, StepLimit
    from . import values as V
    module = card_or_module.get("ir", card_or_module)
    try:
        text = emit_module(module)
    except EmitGap as exc:
        return {"status": "gap", "reason": str(exc)}
    try:
        back = lift_text(text, ctx.ops)
    except MathError as exc:
        return {"status": "not_lifted", "reason": str(exc), "math": text}
    back["entry"] = module.get("entry") or module["functions"][0]["name"]
    if inputs is None:
        inputs = [v["args"] for v in card_or_module.get("vectors", [])]
    checked = 0
    for args in inputs:
        try:
            want = Interpreter(module, ctx.ops, step_limit=200_000).call(module["entry"], list(args))
        except (IRError, StepLimit, ArithmeticError, ValueError, RecursionError, OverflowError):
            continue
        try:
            got = Interpreter(back, ctx.ops, step_limit=2_000_000).call(back["entry"], list(args))
        except (IRError, StepLimit, ArithmeticError, ValueError, RecursionError, OverflowError) as exc:
            return {"status": "fail", "checked": checked, "args": list(args), "expected": want, "error": str(exc),
                    "math": text}
        checked += 1
        if not V.same(want, got):
            return {"status": "fail", "checked": checked, "args": list(args), "expected": want, "got": got,
                    "math": text}
    return {"status": "pass" if checked else "no_inputs", "checked": checked, "math": text}


__all__ = ["MathError", "emit_function", "emit_module", "function_cards", "latex_to_text", "lift_file",
           "lift_text", "parse", "round_trip", "run_tests", "tokenize"]
