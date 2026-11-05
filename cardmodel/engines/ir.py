"""ir — the card IR: programs as trees of op cards.

A function is data:

    {"name": "gcd", "params": [{"name": "a", "type": "int"}, ...],
     "returns": "int", "locals": {"t": "int"}, "body": [stmt, ...]}

Statements (key "k"): assign {target, value} · return {value} ·
if {cond, then, else} · while {cond, body} ·
for_range {var, start, stop, step(int literal != 0), body} · break · continue.

Machine state (the extension a CPU or a piece of hardware needs; optional, so a
plain function module is unchanged):

    module["globals"] = [{"name": "A", "type": "int", "init": 1, "export": false}, ...]
    module["arrays"]  = [{"name": "vram", "elem": "u8" | "int", "size": 16384,
                          "init": [..optional..], "export": false}, ...]

A name that is not a parameter or a local of the function is a global. More
statements: store {array, index, value} (a u8 element keeps ``value & 0xFF``) ·
do {value} (evaluate a call for its effect) · switch {value, cases: [{match:
[ints], body}], default} (no fall-through; ``break`` may not appear directly in a
case) · return without value (functions declared ``"returns": "void"``). One
more expression: ``["LOAD", array, index]`` (an index outside the array is an
error here and undefined in fixed-size targets, so machine code masks indices).

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

Lists ``list[int]`` and ``list[float]`` have value semantics, so every target
may copy or share them as it likes: ``["LIST_NEW", n, fill]`` (n copies of fill;
n < 0 is an error), ``["LEN", xs]``, ``["GET", xs, i]`` (0 <= i < len, else an
error: no negative indexing), ``["LIST_COPY", xs]`` (op cards), and the
statement ``set {target, index, value}`` that writes one element of a local
list. ``check_lists`` enforces what keeps value semantics in languages that
share lists by reference: a list parameter is never written or re-bound, and a
bare list variable is never assigned to another name or returned from a
parameter (copy it with LIST_COPY).
"""
from __future__ import annotations

from dataclasses import dataclass, field

LEAVES = ("var", "int", "float", "bool")
MAX_INT_BITS = 1 << 22          # 4 Mbit (512 KiB) per integer: far beyond any real input, far below a crash
SPECIAL = ("AND", "OR", "IF_EXPR", "CALL", "LOAD")
LIST_TYPES = ("list[int]", "list[float]")
FIXED_INTS = {"u8": ("WRAPU", 8), "u16": ("WRAPU", 16), "u32": ("WRAPU", 32),
              "i8": ("WRAPS", 8), "i16": ("WRAPS", 16), "i32": ("WRAPS", 32)}
FIXED = (*FIXED_INTS, "f32")    # the subsorts of engines/sorts.py (u8..i32 <= int, f32 <= float)
TYPES = ("int", "float", "bool", *FIXED, *LIST_TYPES)
ELEMS = ("u8", "int")
NESTED = ("then", "else", "body", "default")


class IRError(Exception):
    pass


def carrier(t: str) -> str:
    """The wide type a fixed-width value is carried in: ``u8..i32`` -> ``int``, ``f32`` -> ``float``."""
    return "int" if t in FIXED_INTS else "float" if t == "f32" else t


def wrap_store(e, t: str):
    """Wrap-on-store: the value stored into a ``t`` variable. ``u8`` -> ``WRAPU(e, 8)``, ``i8`` -> ``WRAPS(e, 8)``,
    ``f32`` -> ``F32(e)``; any other type stores ``e`` unchanged."""
    if t in FIXED_INTS:
        op, w = FIXED_INTS[t]
        return [op, e, ["int", w]]
    return ["F32", e] if t == "f32" else e


def lower_stores(fn: dict) -> dict:
    """``fn`` with every store to a fixed-width local and every return of a fixed-width result wrapped
    (``wrap_store``). Idempotent: an already wrapped value is not wrapped twice."""
    types = {p["name"]: p["type"] for p in fn.get("params") or []}
    types.update(fn.get("locals") or {})
    ret = fn.get("returns")
    if not any(t in FIXED for t in (*types.values(), ret)):
        return fn

    def done(v, t):
        w = wrap_store(["var", "_"], t)
        return isinstance(v, list) and isinstance(w, list) and v[:1] == w[:1] and v[2:] == w[2:]

    def stmts(body):
        out = []
        for s in body:
            s = dict(s)
            if s.get("k") == "assign" and types.get(s.get("target")) in FIXED and not done(s["value"], types[s["target"]]):
                s["value"] = wrap_store(s["value"], types[s["target"]])
            elif s.get("k") == "return" and "value" in s and ret in FIXED and not done(s["value"], ret):
                s["value"] = wrap_store(s["value"], ret)
            for key in NESTED:
                if isinstance(s.get(key), list):
                    s[key] = stmts(s[key])
            if isinstance(s.get("cases"), list):
                s["cases"] = [{**c, "body": stmts(c.get("body") or [])} for c in s["cases"]]
            out.append(s)
        return out

    return {**fn, "body": stmts(fn.get("body") or [])}


def elem_type(t: str) -> str | None:
    """``list[float]`` -> ``float``; None for a scalar type."""
    return t[5:-1] if isinstance(t, str) and t.startswith("list[") and t.endswith("]") else None


def _list_get(xs, i):
    if not isinstance(i, int) or not 0 <= i < len(xs):
        raise IRError(f"index {i} outside 0..{len(xs) - 1}")
    return xs[i]


def _list_new(n, v):
    if n < 0:
        raise IRError(f"a list of negative length {n}")
    if n > 1 << 24:
        raise IRError(f"a list of {n} elements (cap {1 << 24})")
    return [v] * n


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
        wide = [carrier(t) for t in arg_types]     # a subsort argument fits the op's rank at its carrier (u8 <= int)
        if wide != list(arg_types):
            for sig in self.types:
                if list(sig[:-1]) == wide:
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
            "math": __import__("math"), "struct": __import__("struct"),
            "list_get": _list_get, "list_new": _list_new, "len": len, "list": list}   # struct: binary32 rounding, float bits


def walk_expr(e):
    yield e
    if isinstance(e, list) and e and e[0] not in LEAVES:
        start = 2 if e[0] in ("CALL", "LOAD") else 1
        for a in e[start:]:
            yield from walk_expr(a)


def walk_stmts(body):
    for s in body:
        yield s
        for key in NESTED:
            if key in s:
                yield from walk_stmts(s[key])
        for case in s.get("cases") or ():
            yield from walk_stmts(case["body"])


EXPR_KEYS = ("value", "cond", "start", "stop", "step", "index")


def ops_used(fn: dict) -> set[str]:
    used: set[str] = set()
    for s in walk_stmts(fn["body"]):
        for key in EXPR_KEYS:
            if key in s and isinstance(s[key], list):
                for e in walk_expr(s[key]):
                    if isinstance(e, list) and e and e[0] not in LEAVES:
                        used.add(e[0])
    return used


def new_array(spec: dict):
    """A fresh array for the reference interpreter: bytearray for u8, list for int."""
    size = int(spec["size"])
    init = list(spec.get("init") or [])
    if spec.get("elem", "u8") == "u8":
        a = bytearray(size)
        a[:len(init)] = bytes(v & 0xFF for v in init)
        return a
    return init + [0] * (size - len(init))


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
        self.funcs = {f["name"]: lower_stores(f) for f in module["functions"]}
        self.ops = ops
        self.step_limit = step_limit
        self.steps = 0
        self.max_bits = 0
        self.globals = {g["name"]: g.get("init", 0) for g in module.get("globals") or []}
        self.arrays = {a["name"]: new_array(a) for a in module.get("arrays") or []}
        self.elems = {a["name"]: a.get("elem", "u8") for a in module.get("arrays") or []}
        self._locals = {n: {p["name"] for p in f["params"]} | set(f.get("locals") or {})
                        for n, f in self.funcs.items()}

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
        env["\0locals"] = self._locals[name]
        try:
            self._block(fn["body"], env, depth)
        except _Return as r:
            return r.value
        if fn.get("returns") == "void":
            return None
        raise IRError(f"{name}: fell off the end without return")

    def _assign(self, target, v, env):
        if target in env["\0locals"]:
            env[target] = v
        elif target in self.globals:
            self.globals[target] = v
        else:
            raise IRError(f"assignment to {target!r}: neither a local nor a global")

    def _tick(self):
        self.steps += 1
        if self.steps > self.step_limit:
            raise StepLimit(f"step limit {self.step_limit} exceeded")

    def _note(self, v):
        if isinstance(v, int) and not isinstance(v, bool):
            b = abs(v).bit_length()
            if b > self.max_bits:
                self.max_bits = b
                if b > MAX_INT_BITS:
                    raise IRError(f"an intermediate integer has {b} bits (cap {MAX_INT_BITS}): stopped before it "
                                  "exhausts memory")
        return v

    def _block(self, body, env, depth):
        for s in body:
            self._tick()
            k = s["k"]
            if k == "assign":
                self._assign(s["target"], self._expr(s["value"], env, depth), env)
            elif k == "return":
                raise _Return(self._expr(s["value"], env, depth) if "value" in s else None)
            elif k == "store":
                arr = self.arrays.get(s["array"])
                if arr is None:
                    raise IRError(f"store to unknown array {s['array']!r}")
                i = self._expr(s["index"], env, depth)
                v = self._expr(s["value"], env, depth)
                if not 0 <= i < len(arr):
                    raise IRError(f"store {s['array']}[{i}] outside 0..{len(arr) - 1}")
                arr[i] = v & 0xFF if self.elems[s["array"]] == "u8" else self._note(v)
            elif k == "set":
                xs = env.get(s["target"]) if s["target"] in env["\0locals"] else None
                if not isinstance(xs, list):
                    raise IRError(f"set {s['target']}[...]: not a local list")
                i = self._expr(s["index"], env, depth)
                v = self._expr(s["value"], env, depth)
                if not 0 <= i < len(xs):
                    raise IRError(f"set {s['target']}[{i}] outside 0..{len(xs) - 1}")
                xs[i] = self._note(v)
            elif k == "do":
                self._expr(s["value"], env, depth)
            elif k == "switch":
                v = self._expr(s["value"], env, depth)
                for case in s["cases"]:
                    if v in case["match"]:
                        self._block(case["body"], env, depth)
                        break
                else:
                    self._block(s.get("default") or [], env, depth)
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
                    self._assign(s["var"], self._note(i), env)
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
            if e[1] in env:
                return env[e[1]]
            if e[1] in self.globals and e[1] not in env["\0locals"]:
                return self.globals[e[1]]
            raise IRError(f"variable {e[1]!r} read before assignment")
        if head == "LOAD":
            arr = self.arrays.get(e[1])
            if arr is None:
                raise IRError(f"load from unknown array {e[1]!r}")
            i = self._expr(e[2], env, depth)
            if not 0 <= i < len(arr):
                raise IRError(f"load {e[1]}[{i}] outside 0..{len(arr) - 1}")
            return arr[i]
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


def check_lists(fn: dict) -> list[str]:
    """Why ``fn`` would break list value semantics in a target that shares lists by reference (empty: it holds)."""
    params = {p["name"]: p["type"] for p in fn["params"]}
    types = {**params, **(fn.get("locals") or {})}
    out = []
    for s in walk_stmts(fn["body"]):
        k = s["k"]
        if k == "set" and s["target"] in params:
            out.append(f"writes an element of the parameter {s['target']!r} (copy it first: list(...))")
        if k == "assign" and elem_type(types.get(s["target"], "")) is not None:
            if s["target"] in params:
                out.append(f"re-binds the list parameter {s['target']!r}")
            v = s["value"]
            if isinstance(v, list) and v and v[0] == "var":
                out.append(f"{s['target']} = {v[1]} would share one list under two names (copy it: list(...))")
        if k == "return" and isinstance(s.get("value"), list) and s["value"][:1] == ["var"] \
                and s["value"][1] in params and elem_type(params[s["value"][1]]) is not None:
            out.append(f"returns the parameter {s['value'][1]!r} itself (return a copy)")
        if k == "for_range" and elem_type(types.get(s["var"], "")) is not None:
            out.append("a list as a loop variable")
    return out
