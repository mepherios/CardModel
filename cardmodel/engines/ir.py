"""ir — the card IR: programs as trees of op cards.

A function is data:

    {"name": "gcd", "params": [{"name": "a", "type": "int"}, ...],
     "returns": "int", "locals": {"t": "int"}, "body": [stmt, ...]}

Statements (key "k"): assign {target, value} · return {value} ·
if {cond, then, else} · while {cond, body} ·
for_range {var, start, stop, step(int literal != 0), body} · break · continue.

Expressions are JSON lists ``[op, *args]``. Leaves: ``["var", name]``,
``["int", v]``, ``["float", v]``, ``["bool", v]``. Every other head names an
op card (``cards/op/<name>``): the card's ``eval`` is the reference
semantics (a Python lambda), ``types`` the accepted signatures and ``emit``
the per-language templates. Special forms the interpreter handles itself:
AND, OR (short-circuit), IF_EXPR (lazy), CALL (user functions).

Types: ``int`` (mathematical integer: Python semantics), ``float`` (IEEE
binary64), ``bool``. Fixed-width targets are equivalent only where no value
exceeds their width; the interpreter reports the widest intermediate so
mismatches can be classified as overflow rather than as wrong semantics.
"""
from __future__ import annotations

from dataclasses import dataclass, field

LEAVES = ("var", "int", "float", "bool")
SPECIAL = ("AND", "OR", "IF_EXPR", "CALL")
TYPES = ("int", "float", "bool")


class IRError(Exception):
    pass


class StepLimit(IRError):
    pass


@dataclass
class OpSpec:
    name: str
    arity: int
    types: list[list[str]]          # [[arg types..., result type], ...]
    fn: object = None               # compiled eval lambda
    card: dict = field(default_factory=dict)

    def result_type(self, arg_types: list[str]) -> str | None:
        for sig in self.types:
            if list(sig[:-1]) == list(arg_types):
                return sig[-1]
        return None

    def promoted(self, arg_types: list[str]) -> list[str] | None:
        """Arg types after int->float promotion, if some float signature accepts them."""
        if "float" not in arg_types:
            return None
        want = ["float" if t == "int" else t for t in arg_types]
        return want if self.result_type(want) else None


def op_table(store) -> dict[str, OpSpec]:
    """Build the op table from the store's op cards (cards with ir: true)."""
    table: dict[str, OpSpec] = {}
    view = store.registry("op")
    if not view:
        return table
    for card in view.ALL.values():
        ir = card.get("ir")
        if not isinstance(ir, dict):
            continue
        fn = None
        if ir.get("eval"):
            fn = eval(compile(ir["eval"], f"<op {card.name}>", "eval"), _EVAL_NS)  # noqa: S307 -- trusted card data
        table[card.name] = OpSpec(card.name, int(ir.get("arity", 2)), [list(s) for s in ir.get("types", [])],
                                  fn, dict(card))
    return table


def _floor_div(a, b):
    return a // b


_EVAL_NS = {"__builtins__": {"abs": abs, "min": min, "max": max, "pow": pow, "float": float, "int": int,
                             "bool": bool, "round": round, "divmod": divmod, "ZeroDivisionError": ZeroDivisionError,
                             "ValueError": ValueError},
            "math": __import__("math")}


def walk_expr(e):
    yield e
    if isinstance(e, list) and e and e[0] not in LEAVES:
        start = 2 if e[0] == "CALL" else 1
        for a in e[start:]:
            yield from walk_expr(a)


def walk_stmts(body):
    for s in body:
        yield s
        for key in ("then", "else", "body"):
            if key in s:
                yield from walk_stmts(s[key])


def ops_used(fn: dict) -> set[str]:
    used: set[str] = set()
    for s in walk_stmts(fn["body"]):
        for key in ("value", "cond", "start", "stop", "step"):
            if key in s and isinstance(s[key], list):
                for e in walk_expr(s[key]):
                    if isinstance(e, list) and e and e[0] not in LEAVES:
                        used.add(e[0])
    return used


class _Return(Exception):
    def __init__(self, value):
        self.value = value


class _Break(Exception):
    pass


class _Continue(Exception):
    pass


class Interpreter:
    """Reference semantics of the IR (Python semantics), with a step budget."""

    def __init__(self, module: dict, ops: dict[str, OpSpec], step_limit: int = 2_000_000):
        self.funcs = {f["name"]: f for f in module["functions"]}
        self.ops = ops
        self.step_limit = step_limit
        self.steps = 0
        self.max_bits = 0

    def call(self, name: str, args: list):
        self.steps = 0
        self.max_bits = 0
        return self._call(name, list(args), depth=0)

    def _call(self, name, args, depth):
        if depth > 900:
            raise IRError("recursion too deep")
        fn = self.funcs.get(name)
        if fn is None:
            raise IRError(f"unknown function {name!r}")
        env = {p["name"]: a for p, a in zip(fn["params"], args)}
        try:
            self._block(fn["body"], env, depth)
        except _Return as r:
            return r.value
        raise IRError(f"{name}: fell off the end without return")

    def _tick(self):
        self.steps += 1
        if self.steps > self.step_limit:
            raise StepLimit(f"step limit {self.step_limit} exceeded")

    def _note(self, v):
        if isinstance(v, int) and not isinstance(v, bool):
            b = abs(v).bit_length()
            if b > self.max_bits:
                self.max_bits = b
        return v

    def _block(self, body, env, depth):
        for s in body:
            self._tick()
            k = s["k"]
            if k == "assign":
                env[s["target"]] = self._expr(s["value"], env, depth)
            elif k == "return":
                raise _Return(self._expr(s["value"], env, depth))
            elif k == "if":
                self._block(s["then"] if self._expr(s["cond"], env, depth) else s.get("else", []), env, depth)
            elif k == "while":
                while self._expr(s["cond"], env, depth):
                    self._tick()
                    try:
                        self._block(s["body"], env, depth)
                    except _Break:
                        break
                    except _Continue:
                        continue
            elif k == "for_range":
                start = self._expr(s["start"], env, depth)
                stop = self._expr(s["stop"], env, depth)
                step = self._expr(s["step"], env, depth)
                for i in range(start, stop, step):
                    self._tick()
                    env[s["var"]] = self._note(i)
                    try:
                        self._block(s["body"], env, depth)
                    except _Break:
                        break
                    except _Continue:
                        continue
            elif k == "break":
                raise _Break()
            elif k == "continue":
                raise _Continue()
            else:
                raise IRError(f"unknown statement {k!r}")

    def _expr(self, e, env, depth):
        head = e[0]
        if head == "var":
            if e[1] not in env:
                raise IRError(f"variable {e[1]!r} read before assignment")
            return env[e[1]]
        if head in ("int", "float", "bool"):
            return e[1]
        if head == "AND":
            return bool(self._expr(e[1], env, depth)) and bool(self._expr(e[2], env, depth))
        if head == "OR":
            return bool(self._expr(e[1], env, depth)) or bool(self._expr(e[2], env, depth))
        if head == "IF_EXPR":
            return self._expr(e[2] if self._expr(e[1], env, depth) else e[3], env, depth)
        if head == "CALL":
            args = [self._expr(a, env, depth) for a in e[2:]]
            return self._note(self._call(e[1], args, depth + 1))
        spec = self.ops.get(head)
        if spec is None or spec.fn is None:
            raise IRError(f"op {head!r} has no reference semantics (no op card with ir.eval)")
        args = [self._expr(a, env, depth) for a in e[1:]]
        return self._note(spec.fn(*args))


def to_python_text(e) -> str:
    """Human-readable infix rendering of an expression (for reports and proofs)."""
    head = e[0] if isinstance(e, list) and e else None
    if head == "var":
        return str(e[1])
    if head in ("int", "float"):
        return repr(e[1])
    if head == "bool":
        return "True" if e[1] else "False"
    infix = {"ADD": "+", "SUB": "-", "MUL": "*", "DIV": "/", "FLOORDIV": "//", "MOD": "%", "POW": "**",
             "BIT_AND": "&", "BIT_OR": "|", "BIT_XOR": "^", "SHIFT_LEFT": "<<", "SHIFT_RIGHT": ">>",
             "CMP_EQ": "==", "CMP_NE": "!=", "CMP_LT": "<", "CMP_LE": "<=", "CMP_GT": ">", "CMP_GE": ">=",
             "AND": "and", "OR": "or"}
    if head in infix and len(e) == 3:
        return f"({to_python_text(e[1])} {infix[head]} {to_python_text(e[2])})"
    if head == "NEG":
        return f"(-{to_python_text(e[1])})"
    if head == "NOT":
        return f"(not {to_python_text(e[1])})"
    if head == "BIT_NOT":
        return f"(~{to_python_text(e[1])})"
    if head == "IF_EXPR":
        return f"({to_python_text(e[2])} if {to_python_text(e[1])} else {to_python_text(e[3])})"
    if head == "CALL":
        return f"{e[1]}({', '.join(to_python_text(a) for a in e[2:])})"
    if isinstance(e, str):
        return e
    if isinstance(e, list) and e:
        return f"{head}({', '.join(to_python_text(a) for a in e[1:])})"
    return repr(e)
