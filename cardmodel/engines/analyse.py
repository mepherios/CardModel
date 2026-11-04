"""analyse — understand a program the REA way, in the math language: structure, logic, and where runners differ.

The method is the one rea-cards uses on binaries (facts with provenance, witnessed flaws, refuse rather than
guess, name the first diverging input), applied to lifted programs. The IR's reference semantics is the
mathematics of the program (int is ℤ, float is binary64, a partial op is undefined off its domain); a target
language, an optimization level or a device runner is a *model* of that mathematics that agrees with it only
on part of the domain. The analyser makes that part explicit:

  1. structure   facts about every function, each with the rule it came from (``via``): its signature in
                 math notation, calls, recursion class (none / tail / general / mutual), loops, the partial
                 ops it uses, its effects (globals, arrays, void);
  2. logic       an obligation for every partial op (``b ≠ 0`` for ``a mod b``, ``x > 0`` for ``log x`` …)
                 under the path condition that reaches it, discharged by a guard on the path (proved), by the
                 declared domain (``requires``), or left open with a counterexample the reference refuses;
  3. divergence  laws (``LAWS``) that state, in math, the condition under which a runner's model of an op
                 differs from ℤ / binary64: fixed-width overflow, division by zero, a float exception the
                 reference raises and IEEE turns into ±∞/NaN, float→int of a non-finite value, shift counts,
                 negative integer powers, NaN flowing into a result, deep recursion, a step budget (timing),
                 evaluation order of effects, and reassociation under fast-math. The instrumented reference
                 run on boundary and in-domain inputs finds which laws *fire* where, with the first input;
  4. witness     every firing is run in every available runner (each codegen language, and optimization or
                 checking variants: C at -O0/-O2/-ffast-math/UBSan, Rust debug/release, Swift -Onone/-Ounchecked)
                 and compared with the reference. A finding is ``witnessed`` (some runner differs: the
                 difference is real and named), ``guarded`` (every runner agrees: the codegen handles it), or
                 ``predicted`` (no runner could run it here).

A finding inside the function's declared domain (its ``requires``; a Python ``int`` has no bound, so all of ℤ)
is a latent flaw of the *source*: the translation is faithful only on a smaller domain than the source claims.
Outside the declared domain it is boundary behaviour, reported but not counted against the program.

Honest limits (L1): equivalence and agreement are sampled, never proved here; laws are the ones listed (a
difference no law explains is still witnessed, as "unexplained"); machine state (globals, arrays, void
functions) is analysed for structure and logic but not run in the runners; non-finite float arguments and
integers outside 64 bits cannot be written as literals in fixed-width targets, so they are not runner inputs.
"""
from __future__ import annotations

import copy
import math
import random
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from . import values as V
from .codegen import EmitGap, Emitter
from .ir import LEAVES, MAX_INT_BITS, SPECIAL, Interpreter, IRError, StepLimit, to_python_text
from .runners import run_program

STEP_LIMIT = 300_000
DEEP = 400                      # recursion frames: half of Python's default limit, far above a small device stack
INT64 = (-(2 ** 63), 2 ** 63)
TYPE_SYM = {"int": "ℤ", "float": "ℝ", "bool": "𝔹", "void": "()"}
PARTIAL = {"FLOORDIV": "div", "MOD": "div", "TRUNCDIV": "div", "REM": "div", "DIV": "div", "POW_MOD": "mod3",
           "LOG": "pos", "SHIFT_LEFT": "shift", "SHIFT_RIGHT": "shift", "TRUNC_INT": "finite", "POW": "pow",
           "LOAD": "index"}
FLOAT_EXC = (ValueError, OverflowError, ZeroDivisionError)


# ---- the math renderer -------------------------------------------------------------------------------------------

def show(e) -> str:
    """An IR expression in the math language's notation (falls back to infix text where the notation has none)."""
    from .mathlang import Renderer
    try:
        return Renderer().expr(e)
    except Exception:            # noqa: BLE001 -- machine-state forms (LOAD …) have no math notation yet
        return to_python_text(e)


def signature(fn: dict) -> str:
    args = " × ".join(TYPE_SYM.get(p["type"], p["type"]) for p in fn["params"]) or "()"
    return f"{fn['name']} : {args} → {TYPE_SYM.get(fn.get('returns', 'int'), fn.get('returns'))}"


# ---- 1. structure ------------------------------------------------------------------------------------------------

def _exprs(s: dict):
    for key in ("value", "cond", "start", "stop", "step", "index"):
        if isinstance(s.get(key), list):
            yield key, s[key]


def _walk(e, path):
    yield e, path
    if isinstance(e, list) and e and e[0] not in LEAVES:
        start = 2 if e[0] in ("CALL", "LOAD") else 1
        for i, a in enumerate(e[start:], start):
            yield from _walk(a, f"{path}[{i}]")


def _stmts(body, path="body"):
    for i, s in enumerate(body):
        p = f"{path}[{i}]"
        yield s, p
        for key in ("then", "else", "body", "default"):
            if key in s:
                yield from _stmts(s[key], f"{p}.{key}")
        for j, case in enumerate(s.get("cases") or ()):
            yield from _stmts(case["body"], f"{p}.cases[{j}]")


def _sccs(graph: dict[str, set[str]]) -> list[list[str]]:
    """Tarjan's strongly connected components (mutual recursion)."""
    index, low, stack, on, out, n = {}, {}, [], set(), [], [0]

    def visit(v):
        index[v] = low[v] = n[0]
        n[0] += 1
        stack.append(v)
        on.add(v)
        for w in graph.get(v, ()):
            if w not in graph:
                continue
            if w not in index:
                visit(w)
                low[v] = min(low[v], low[w])
            elif w in on:
                low[v] = min(low[v], index[w])
        if low[v] == index[v]:
            comp = []
            while True:
                w = stack.pop()
                on.discard(w)
                comp.append(w)
                if w == v:
                    break
            out.append(sorted(comp))
    for v in sorted(graph):
        if v not in index:
            visit(v)
    return out


def structure(module: dict) -> dict:
    """Facts about every function of an IR module, each with the rule that produced it (``via``)."""
    funcs = {f["name"]: f for f in module["functions"]}
    globals_ = {g["name"] for g in module.get("globals") or []}
    arrays = {a["name"] for a in module.get("arrays") or []}
    graph: dict[str, set[str]] = {}
    out: dict[str, dict] = {}
    for name, fn in funcs.items():
        locals_ = {p["name"] for p in fn["params"]} | set(fn.get("locals") or {})
        calls, tail_self, other_self, loops, partial, reads, writes, stores, loads = set(), 0, 0, 0, {}, set(), set(), \
            set(), set()
        for s, p in _stmts(fn["body"]):
            if s["k"] in ("while", "for_range"):
                loops += 1
            if s["k"] == "assign" and s["target"] not in locals_:
                writes.add(s["target"])
            if s["k"] == "for_range" and s["var"] not in locals_:
                writes.add(s["var"])
            if s["k"] == "store":
                stores.add(s["array"])
            for key, e in _exprs(s):
                is_tail_pos = s["k"] == "return" and key == "value"
                for sub, _ in _walk(e, f"{p}.{key}"):
                    if not isinstance(sub, list) or not sub:
                        continue
                    if sub[0] == "CALL":
                        calls.add(sub[1])
                        if sub[1] == name:
                            if is_tail_pos and sub is e:
                                tail_self += 1
                            else:
                                other_self += 1
                    elif sub[0] == "LOAD":
                        loads.add(sub[1])
                    elif sub[0] == "var" and sub[1] not in locals_ and sub[1] in globals_:
                        reads.add(sub[1])
                    elif sub[0] in PARTIAL:
                        partial.setdefault(sub[0], 0)
                        partial[sub[0]] += 1
        graph[name] = calls
        out[name] = {
            "signature": {"value": signature(fn), "via": "params and returns of the IR function"},
            "calls": {"value": sorted(calls - {name}), "via": "CALL nodes in the body"},
            "recursion": {"value": "general" if other_self else "tail" if tail_self else "none",
                          "via": "self-CALLs: in return position (tail) or elsewhere (general)"},
            "loops": {"value": loops, "via": "while and for_range statements"},
            "partial_ops": {"value": dict(sorted(partial.items())),
                            "via": "op cards undefined somewhere on their types (PARTIAL)"},
            "effects": {"value": {"reads": sorted(reads), "writes": sorted(writes), "loads": sorted(loads),
                                  "stores": sorted(stores), "void": fn.get("returns") == "void"},
                        "via": "names that are not parameters or locals; LOAD and store statements"},
        }
    for comp in _sccs(graph):
        if len(comp) > 1:
            for n in comp:
                out[n]["recursion"] = {"value": "mutual", "with": [x for x in comp if x != n],
                                       "via": "a strongly connected component of the call graph"}
    for n, f in out.items():
        eff = f["effects"]["value"]
        f["pure"] = {"value": not (eff["writes"] or eff["stores"] or eff["void"] or
                                   any(not out[c]["pure"]["value"] for c in f["calls"]["value"] if c in out
                                       and "pure" in out[c])),
                     "via": "no writes, stores or void results (callees analysed first where known)"}
    _effects_closure(out)
    return {"functions": out, "call_graph": {n: sorted(c) for n, c in sorted(graph.items())}}


def _effects_closure(out: dict) -> None:
    changed = True
    while changed:
        changed = False
        for f in out.values():
            if f["pure"]["value"] and any(c in out and not out[c]["pure"]["value"] for c in f["calls"]["value"]):
                f["pure"] = {"value": False, "via": "calls a function with effects"}
                changed = True


# ---- 2. logic: obligations of partial ops, under their path conditions ------------------------------------------

def _neg(c):
    return c[1] if c[0] == "NOT" else ["NOT", c]


def _returns(body) -> bool:
    return bool(body) and body[-1]["k"] in ("return", "break", "continue")


def _obligation(e) -> list | None:
    """The condition under which op ``e`` is defined, as an IR condition (None: total)."""
    h = e[0]
    kind = PARTIAL.get(h)
    if kind == "div":
        zero = ["float", 0.0] if h == "DIV" else ["int", 0]
        return ["CMP_NE", e[2], zero]
    if kind == "mod3":
        return ["CMP_NE", e[3], ["int", 0]]
    if kind == "pos":
        return ["CMP_GT", e[1], ["float", 0.0]]
    if kind == "shift":
        return ["CMP_GE", e[2], ["int", 0]]
    if kind == "pow":
        return None      # depends on types; the divergence law int_pow_negative covers the int case
    if kind == "finite":
        return None      # finiteness has no comparison in the IR; the law float_to_int covers it
    return None


def _implies(facts: list, goal) -> bool:
    """A cheap, sound check: does a fact on the path state the goal (or a stronger bound) about the same term?"""
    if goal is None:
        return True
    h, x, z = goal
    if x[0] == "TO_FLOAT" and z == ["float", 0.0] and h == "CMP_NE":    # float(i) ≠ 0.0  ⇔  i ≠ 0
        x, z = x[1], ["int", 0]
    if z[0] in ("int", "float") and x[0] in ("int", "float"):
        return {"CMP_NE": x[1] != z[1], "CMP_GT": x[1] > z[1], "CMP_GE": x[1] >= z[1]}[h]
    c0 = z[1]
    for f in facts:
        if f[0] == "NOT" and isinstance(f[1], list) and f[1][0] == "CMP_EQ":
            f = ["CMP_NE", f[1][1], f[1][2]]
        elif f[0] == "NOT" and isinstance(f[1], list) and f[1][0] in ("CMP_LT", "CMP_LE", "CMP_GT", "CMP_GE"):
            flip = {"CMP_LT": "CMP_GE", "CMP_LE": "CMP_GT", "CMP_GT": "CMP_LE", "CMP_GE": "CMP_LT"}
            f = [flip[f[1][0]], f[1][1], f[1][2]]
        if f[0] not in ("CMP_NE", "CMP_GT", "CMP_GE", "CMP_LT", "CMP_LE", "CMP_EQ") or len(f) != 3:
            continue
        a, b = f[1], f[2]
        op = f[0]
        if b == x and a != x:                     # c op x  ->  x op' c
            a, b = b, a
            op = {"CMP_GT": "CMP_LT", "CMP_GE": "CMP_LE", "CMP_LT": "CMP_GT", "CMP_LE": "CMP_GE"}.get(op, op)
        if a != x or b[0] not in ("int", "float"):
            continue
        c = b[1]
        if h == "CMP_NE" and ((op == "CMP_NE" and c == c0) or (op == "CMP_GT" and c >= c0) or
                              (op == "CMP_GE" and c > c0) or (op == "CMP_LT" and c <= c0) or
                              (op == "CMP_LE" and c < c0) or (op == "CMP_EQ" and c != c0)):
            return True
        if h == "CMP_GT" and ((op == "CMP_GT" and c >= c0) or (op == "CMP_GE" and c > c0) or
                              (op == "CMP_EQ" and c > c0)):
            return True
        if h == "CMP_GE" and ((op in ("CMP_GT", "CMP_GE") and c >= c0) or (op == "CMP_EQ" and c >= c0)):
            return True
    return False


def obligations(fn: dict) -> list[dict]:
    """Every partial op with its definedness condition and the path condition that reaches it."""
    out: list[dict] = []
    requires = list(fn.get("requires") or [])

    def expr(e, path, facts):
        if not isinstance(e, list) or not e or e[0] in LEAVES:
            return
        h = e[0]
        if h == "AND":
            expr(e[1], f"{path}[1]", facts)
            expr(e[2], f"{path}[2]", facts + [e[1]])
            return
        if h == "OR":
            expr(e[1], f"{path}[1]", facts)
            expr(e[2], f"{path}[2]", facts + [_neg(e[1])])
            return
        if h == "IF_EXPR":
            expr(e[1], f"{path}[1]", facts)
            expr(e[2], f"{path}[2]", facts + [e[1]])
            expr(e[3], f"{path}[3]", facts + [_neg(e[1])])
            return
        start = 2 if h in ("CALL", "LOAD") else 1
        for i, a in enumerate(e[start:], start):
            expr(a, f"{path}[{i}]", facts)
        goal = _obligation(e)
        if goal is not None:
            proved_path = _implies(facts, goal)
            proved_dom = not proved_path and _implies(requires, goal)
            out.append({"op": h, "at": path, "term": show(e), "needs": show(goal), "path": [show(f) for f in facts],
                        "goal": goal, "expr_id": id(e),
                        "status": "proved" if proved_path else "domain" if proved_dom else "open",
                        "via": ("a constant" if goal[1][0] in ("int", "float") else "a guard on the path implies it")
                        if proved_path else
                        "the declared domain (requires) implies it" if proved_dom else "not implied by the path"})

    def block(body, path, facts):
        facts = list(facts)
        for i, s in enumerate(body):
            p = f"{path}[{i}]"
            k = s["k"]
            for key, e in _exprs(s):
                expr(e, f"{p}.{key}", facts)
            if k == "if":
                block(s["then"], f"{p}.then", facts + [s["cond"]])
                block(s.get("else") or [], f"{p}.else", facts + [_neg(s["cond"])])
                if _returns(s["then"]) and not s.get("else"):
                    facts.append(_neg(s["cond"]))          # `if c: return …` guards the rest of the block
                elif _returns(s.get("else") or []) and not _returns(s["then"]):
                    facts.append(s["cond"])
            elif k == "while":
                block(s["body"], f"{p}.body", facts + [s["cond"]])
            elif k == "for_range":
                v = ["var", s["var"]]
                step = s["step"][1] if s["step"][0] == "int" else 1
                bounds = [["CMP_GE", v, s["start"]], ["CMP_LT", v, s["stop"]]] if step > 0 else \
                    [["CMP_LE", v, s["start"]], ["CMP_GT", v, s["stop"]]]
                block(s["body"], f"{p}.body", facts + bounds)
            elif k == "switch":
                for j, case in enumerate(s["cases"]):
                    block(case["body"], f"{p}.cases[{j}]", facts)
                block(s.get("default") or [], f"{p}.default", facts)
            if k == "assign":                              # a fact about a re-bound name no longer holds
                facts = [f for f in facts if not _mentions(f, s["target"])]
    block(fn["body"], "body", requires)
    return out


def _mentions(e, name) -> bool:
    return any(isinstance(x, list) and x[:2] == ["var", name] for x, _ in _walk(e, ""))


# ---- 3. divergence laws: where a runner's model of an op differs from ℤ / binary64 --------------------------------

@dataclass
class Law:
    id: str
    title: str
    condition: str                       # the math, with {term} and operand slots {a} {b}
    runners: dict[str, str]              # runner family -> what that runner does there
    fix: str
    static: bool = False


LAWS: dict[str, Law] = {law.id: law for law in [
    Law("int_width", "integer leaves the 64-bit range",
        "{term} ∉ [−2⁶³, 2⁶³) while every operand is inside it",
        {"c": "signed overflow is undefined behaviour in ISO C: -O0 usually wraps, -O2 may assume it never happens "
              "and fold or remove the code, UBSan stops the program",
         "cpp": "as C", "rust": "debug builds panic on overflow; release builds (-O) wrap modulo 2⁶⁴",
         "swift": "traps (the arithmetic is checked) except under -Ounchecked, where it is undefined",
         "go": "wraps modulo 2⁶⁴", "java": "wraps modulo 2⁶⁴", "lua": "integers wrap modulo 2⁶⁴",
         "javascript": "BigInt: exact, agrees with ℤ", "ruby": "Integer: exact, agrees with ℤ",
         "python": "int: exact, agrees with ℤ"},
        "declare the domain that keeps every intermediate in range (requires / `for … ≤ n ≤ …`), reorder the "
        "arithmetic so intermediates stay small (a + ⌊(b − a)/2⌋ instead of ⌊(a + b)/2⌋), or ask for a wider "
        "type"),
    Law("int_div_zero", "integer division or remainder by zero",
        "{b} = 0 in {term}",
        {"c": "undefined behaviour: SIGFPE on x86-64, a silent 0 on ARM64 (so it differs by device)",
         "cpp": "as C", "rust": "panics", "swift": "traps", "go": "panics", "java": "throws ArithmeticException",
         "javascript": "RangeError", "lua": "error ('attempt to perform n//0')", "ruby": "ZeroDivisionError",
         "python": "ZeroDivisionError, as the reference"},
        "guard the divisor (`if b = 0 …`) or declare b ≠ 0 in the domain"),
    Law("float_div_zero", "binary64 division by zero",
        "{b} = 0 in {term}",
        {"*": "IEEE 754 gives ±∞ or NaN and carries on", "python": "ZeroDivisionError, as the reference"},
        "decide what x/0 means for this program and write it as a case; the reference refuses it"),
    Law("float_exception", "a float op the reference refuses (domain or overflow)",
        "{term} is outside the op's domain or overflows binary64",
        {"*": "IEEE 754 returns NaN or ±∞ (log 0 = −∞, log −1 = NaN, exp 1000 = ∞)",
         "python": "ValueError or OverflowError, as the reference"},
        "make the domain explicit (x > 0 for log), or write the IEEE result as a case"),
    Law("float_to_int", "binary64 → integer of a non-finite or out-of-range value",
        "{a} is NaN, ±∞ or ∉ [−2⁶³, 2⁶³) in {term}",
        {"c": "undefined behaviour (ARM64 saturates, x86-64 gives −2⁶³)", "cpp": "as C",
         "rust": "saturates (NaN → 0)", "java": "saturates (NaN → 0)", "go": "implementation-specific",
         "swift": "traps", "javascript": "RangeError from BigInt", "python": "ValueError / OverflowError"},
        "guard with isnan / a range check before converting"),
    Law("shift_count", "shift by a negative count or by 64 or more",
        "{b} < 0 ∨ {b} ≥ 64 in {term}",
        {"c": "undefined behaviour; x86-64 and ARM64 hardware use the count mod 64", "cpp": "as C",
         "java": "uses the count mod 64", "rust": "debug builds panic; release builds use the count mod 64",
         "go": "a negative count panics; ≥ 64 gives 0 or −1", "lua": "≥ 64 gives 0",
         "python": "ℤ: exact for b ≥ 0, ValueError for b < 0"},
        "bound the count (0 ≤ b < 64) in the domain, or use multiplication by 2^b on ℤ"),
    Law("int_pow_negative", "integer power with a negative exponent",
        "{b} < 0 in {term}",
        {"*": "the generated integer power loop returns 1 (no iterations)",
         "python": "a float (2 ** −1 = 0.5): the result type changes"},
        "declare b ≥ 0, or write the power on ℝ"),
    Law("nan_result", "NaN produced and carried on",
        "{term} = NaN",
        {"*": "IEEE: every comparison with NaN is false, min/max depend on operand order and on the library; "
              "-ffast-math assumes NaN never occurs and may remove isnan checks"},
        "test isnan where it arises, or keep the op inside its domain"),
    Law("deep_recursion", "recursion deeper than a small device stack allows",
        "call depth ≥ " + str(DEEP),
        {"*": "native stacks are 512 KiB on secondary threads (iOS, macOS) to 8 MiB; depth × frame size decides",
         "python": "RecursionError past 1000 frames"},
        "a tail call is lowered to a loop; turn the recursion into an accumulator (a tail call) or an explicit "
        "loop"),
    Law("step_budget", "the reference needs more than the step budget (timing)",
        "steps > " + str(STEP_LIMIT),
        {"*": "a loop whose trip count grows with the input: runners differ by orders of magnitude in time, and a "
              "device watchdog or timeout decides the outcome"},
        "bound the input in the domain, or replace the loop by its closed form (cardmodel improve)"),
    Law("eval_order", "two calls with effects in one expression",
        "{term} evaluates two effectful calls whose order the language may choose",
        {"c": "the order of operands is unspecified", "cpp": "unspecified before C++17 for most operators",
         "*": "left to right"},
        "bind each call to a name first (one statement each)", static=True),
    Law("float_assoc", "a float sum or product of three or more terms",
        "{term}: binary64 + and · are not associative",
        {"c_fast": "-ffast-math reassociates and vectorizes, so the low bits (and NaN handling) change",
         "*": "evaluated left to right as written; agrees"},
        "keep strict IEEE (no -ffast-math) where the order matters, or sum compensated (Kahan)", static=True),
]}


def family(runner: str) -> str:
    base, _, variant = runner.partition("@")
    return f"{base}_fast" if variant == "fastmath" else base


def law_note(law: Law, runner: str) -> str:
    fam = family(runner)
    return law.runners.get(fam) or law.runners.get(fam.split("_")[0]) or law.runners.get("*", "")


class Instrumented(Interpreter):
    """The reference interpreter, reporting each law that fires (with the op, its operands and the result)."""

    def __init__(self, module, ops, step_limit=STEP_LIMIT):
        super().__init__(module, ops, step_limit=step_limit)
        self.fired: list[dict] = []
        self.depth = 0

    def call(self, name, args):
        self.fired, self.depth = [], 0
        return super().call(name, args)

    def _call(self, name, args, depth):
        self.depth = max(self.depth, depth)
        if depth == DEEP:
            self.fired.append({"law": "deep_recursion", "expr": None, "function": name, "args": []})
        return super()._call(name, args, depth)

    def _fire(self, law, e, args, result=None):
        self.fired.append({"law": law, "expr": id(e), "args": args, "result": result})

    def _expr(self, e, env, depth):
        head = e[0]
        if head in LEAVES or head in SPECIAL:
            return super()._expr(e, env, depth)
        spec = self.ops.get(head)
        if spec is None or spec.fn is None:
            return super()._expr(e, env, depth)
        args = [self._expr(a, env, depth) for a in e[1:]]
        ints = all(isinstance(a, int) and not isinstance(a, bool) for a in args)
        if head in ("FLOORDIV", "MOD", "TRUNCDIV", "REM") and ints and args[1] == 0:
            self._fire("int_div_zero", e, args)
        if head == "POW_MOD" and ints and args[2] == 0:
            self._fire("int_div_zero", e, args)
        if head == "DIV" and args[1] == 0:
            self._fire("float_div_zero", e, args)
        if head in ("SHIFT_LEFT", "SHIFT_RIGHT") and (args[1] < 0 or args[1] >= 64):
            self._fire("shift_count", e, args)
        if head == "POW" and ints and args[1] < 0:
            self._fire("int_pow_negative", e, args)
        if head == "TRUNC_INT" and (not math.isfinite(args[0]) or not INT64[0] <= args[0] < INT64[1]):
            self._fire("float_to_int", e, args)
        if ints and ((head == "SHIFT_LEFT" and args[1] > MAX_INT_BITS) or
                     (head in ("POW", "CONST_POW") and abs(args[0]) > 1 and args[1] > MAX_INT_BITS)):
            if all(INT64[0] <= a < INT64[1] for a in args):
                self._fire("int_width", e, args, "huge")
            raise IRError(f"{head}: the result has more than {MAX_INT_BITS} bits")
        try:
            r = spec.fn(*args)
        except FLOAT_EXC as exc:
            if not any(isinstance(a, int) and not isinstance(a, bool) for a in args) and head not in (
                    "DIV",):
                self._fire("float_exception", e, args, type(exc).__name__)
            raise
        if (isinstance(r, int) and not isinstance(r, bool) and ints and head != "TRUNC_INT"
                and all(INT64[0] <= a < INT64[1] for a in args) and not INT64[0] <= r < INT64[1]):
            self._fire("int_width", e, args, r)
        if isinstance(r, float) and r != r and not any(isinstance(a, float) and a != a for a in args):
            self._fire("nan_result", e, args, r)
        return self._note(r)


def _static_findings(module: dict, struct: dict) -> list[dict]:
    """Laws decided by the program's shape: effect order, float reassociation."""
    out = []
    pure = {n: f["pure"]["value"] for n, f in struct["functions"].items()}
    for fn in module["functions"]:
        for s, p in _stmts(fn["body"]):
            for key, e in _exprs(s):
                for sub, sp in _walk(e, f"{p}.{key}"):
                    if not isinstance(sub, list) or not sub or sub[0] in LEAVES:
                        continue
                    start = 2 if sub[0] in ("CALL", "LOAD") else 1
                    eff = [a for a in sub[start:] if isinstance(a, list) and any(
                        isinstance(x, list) and x and x[0] == "CALL" and not pure.get(x[1], True)
                        for x, _ in _walk(a, ""))]
                    if len(eff) >= 2 and sub[0] not in ("AND", "OR", "IF_EXPR"):
                        out.append({"law": "eval_order", "function": fn["name"], "at": sp, "term": show(sub),
                                    "expr_id": id(sub)})
                    if sub[0] in ("ADD", "MUL") and any(isinstance(a, list) and a and a[0] == sub[0]
                                                         for a in sub[1:]) and _floaty(sub, fn):
                        out.append({"law": "float_assoc", "function": fn["name"], "at": sp, "term": show(sub),
                                    "expr_id": id(sub)})
    return out


def _floaty(e, fn) -> bool:
    """Does the expression compute in binary64? (a float literal, a float parameter, or a float-returning op)"""
    ftypes = {p["name"] for p in fn["params"] if p["type"] == "float"} | {
        n for n, t in (fn.get("locals") or {}).items() if t == "float"}
    for x, _ in _walk(e, ""):
        if isinstance(x, list) and x and (x[0] == "float" or (x[0] == "var" and x[1] in ftypes)
                                           or x[0] in ("TO_FLOAT", "DIV", "FSQRT", "EXP", "LOG", "SIN", "COS")):
            return True
    return False


# ---- inputs ------------------------------------------------------------------------------------------------------

INT_EDGES = [0, 1, -1, 2, -3, 7, 2 ** 31 - 1, -(2 ** 31), 2 ** 32 + 1, 2 ** 53 + 1, 2 ** 62, -(2 ** 62),
             2 ** 63 - 1, -(2 ** 63 - 1), 64, 65, -64]
FLOAT_EDGES = [0.0, -0.0, 1.0, -1.0, 0.5, -2.5, 1e-310, 1e308, -1e308, 710.0, 9.3e18, -9.3e18, 1e19]


def boundary_inputs(fn: dict, rng: random.Random, n: int = 160) -> list[list]:
    """Per-parameter edge values (64-bit limits, 2⁵³, shift widths, signed zero, overflow thresholds): every
    one-parameter variation of a neutral point, then a seeded sample of the product."""
    pools = []
    for p in fn["params"]:
        pools.append(INT_EDGES if p["type"] == "int" else FLOAT_EDGES if p["type"] == "float" else [True, False])
    if not pools:
        return [[]]
    neutral = [pool[1] for pool in pools]
    out, seen = [], set()

    def add(args):
        k = repr(args)
        if k not in seen:
            seen.add(k)
            out.append(args)
    for i, pool in enumerate(pools):
        for v in pool:
            args = list(neutral)
            args[i] = v
            add(args)
    tries = 0
    while len(out) < n and tries < n * 4:
        tries += 1
        add([rng.choice(pool) for pool in pools])
    return out


def in_domain(ctx, module: dict, fn: dict, args: list) -> bool:
    """Inside the declared domain (requires). A function without requires is defined on all of its types."""
    req = fn.get("requires") or []
    if not req:
        return True
    interp = Interpreter(module, ctx.ops)
    env = {p["name"]: a for p, a in zip(fn["params"], args)}
    env["\0locals"] = set(env)
    try:
        return all(bool(interp._expr(c, env, 0)) for c in req)
    except (IRError, ArithmeticError, ValueError, OverflowError):
        return False


def _outcome(ctx, module: dict, args: list) -> tuple[dict, list[dict], int]:
    it = Instrumented(module, ctx.ops)
    try:
        v = it.call(module["entry"], list(args))
        out = {"value": v}
    except StepLimit:
        it.fired.append({"law": "step_budget", "expr": None, "args": []})
        out = {"error": "step budget"}
    except RecursionError:
        out = {"error": "RecursionError"}
    except IRError as exc:
        out = {"error": str(exc)[:80]}
    except (ArithmeticError, ValueError, OverflowError, TypeError, MemoryError) as exc:
        out = {"error": type(exc).__name__}
    return out, it.fired, it.depth


# ---- 4. runners: every codegen language, and optimization / checking variants ------------------------------------

VARIANTS: dict[str, list[tuple[str, dict]]] = {
    "c": [("O0", {"replace": {"-O2": "-O0"}}), ("O2", {}), ("fastmath", {"add": ["-ffast-math"]}),
          ("ubsan", {"replace": {"-O2": "-O1"}, "add": ["-fsanitize=undefined", "-fno-sanitize-recover=all"]})],
    "rust": [("debug", {"drop": ["-O"]}), ("release", {})],
    "swift": [("Onone", {"replace": {"-O": "-Onone"}}), ("Ounchecked", {"replace": {"-O": "-Ounchecked"}})],
}


def _variant(card: dict, spec: dict, suffix: str) -> dict:
    c = copy.deepcopy(card)
    c["name"] = f"{card['name']}@{suffix}" if suffix else card["name"]
    comp = (c.get("runner") or {}).get("compile")
    if comp and spec:
        comp = [spec.get("replace", {}).get(a, a) for a in comp if a not in spec.get("drop", [])]
        if spec.get("add"):
            i = next((k for k, a in enumerate(comp) if a == "{src}"), len(comp))
            comp = comp[:i] + spec["add"] + comp[i:]
        c["runner"]["compile"] = comp
    return c


def runners(ctx, langs: list[str] | None = None) -> list[tuple[str, str, dict]]:
    """(runner name, base language, language card) for every available codegen language and its variants."""
    out = []
    for lang in langs or ctx.codegen_languages():
        base, _, want = lang.partition("@")
        ok, _why = ctx.available(base)
        if not ok:
            continue
        card = ctx.language(base)
        variants = VARIANTS.get(base) or [("", {})]
        for suffix, spec in variants:
            if want and suffix != want:
                continue
            out.append((f"{base}@{suffix}" if suffix else base, base, _variant(card, spec, suffix)))
    return out


def _emittable(fn: dict, args: list, bits: int | None) -> bool:
    for p, a in zip(fn["params"], args):
        if p["type"] == "float" and not math.isfinite(a):
            return False
        if p["type"] == "int" and bits is not None and not V.fits(a, bits):
            return False
    return True


SLOW_TIMEOUT = 5.0           # seconds a runner gets on an input the reference could not finish (timing law)


def _run_one(ctx, runner: tuple[str, str, dict], module: dict, inputs: list[list],
             slow: bool = False) -> list[dict]:
    """The runner's outcome for each input: {"value": v} or {"error": text}; one program for all inputs, and one
    per input when the batch stops early (a crash ends a program)."""
    name, base, card = runner
    try:
        em = Emitter(ctx.store, base, ctx.ops)
    except EmitGap as exc:
        return [{"gap": str(exc)}] * len(inputs)

    def program(calls):
        return em.program(module, calls)
    try:
        src = program(inputs)
    except EmitGap as exc:
        return [{"gap": str(exc)}] * len(inputs)
    if slow:                     # each on its own, with a short clock: whether it finishes is the finding
        out = []
        for args in inputs:
            r = run_program(card, program([args]), ctx.state_root, timeout=SLOW_TIMEOUT)
            out.append({"value": r.values[0]} if r.status == "ok" and len(r.values) == 1 else
                       {"error": _first_line(r)})
        return out
    run = run_program(card, src, ctx.state_root, timeout=20)
    if run.status == "ok" and len(run.values) == len(inputs):
        return [{"value": v} for v in run.values]
    if run.status in ("compile_error", "unavailable"):
        return [{"gap": f"{run.status}: {(run.stderr or run.detail)[-160:]}"}] * len(inputs)
    out = []
    for args in inputs:
        r = run_program(card, program([args]), ctx.state_root, timeout=10)
        if r.status == "ok" and len(r.values) == 1:
            out.append({"value": r.values[0]})
        else:
            out.append({"error": _first_line(r)})
    return out


def _first_line(r) -> str:
    """The first informative stderr line of a failed run, paths shortened (the panic, trap or sanitizer report)."""
    import re
    lines = [ln.strip() for ln in (r.stderr or r.detail or "").splitlines() if ln.strip()]
    pick = next((ln for ln in lines if re.search(r"panic|error|overflow|trap|exception|fatal", ln, re.I)),
                lines[0] if lines else "")
    pick = re.sub(r"(/[^\s:/]+)+/", "", pick)
    return f"{r.status}: {pick[:90]}" if pick else r.status


def _agree(ref: dict, got: dict) -> bool | None:
    if "gap" in got or ref.get("error") == "step budget":     # no reference value to compare with
        return None
    if "error" in ref:
        return "error" in got
    return "value" in got and V.same(ref["value"], got["value"])


# ---- the analysis ------------------------------------------------------------------------------------------------

@dataclass
class Analysis:
    function: str
    source: str
    structure: dict
    obligations: list = field(default_factory=list)
    findings: list = field(default_factory=list)
    runners: list = field(default_factory=list)
    inputs: int = 0
    math: str = ""


def analyse_card(ctx, card: dict, run: bool = True, langs: list[str] | None = None, seed: int = 0,
                 per_law: int = 2, pool: list | None = None) -> Analysis:
    module = card["ir"]
    entry = module["entry"]
    fns = {f["name"]: f for f in module["functions"]}
    fn = fns[entry]
    struct = structure(module)
    loc: dict[int, dict] = {}
    for f in module["functions"]:
        for s, p in _stmts(f["body"]):
            for key, e in _exprs(s):
                for sub, sp in _walk(e, f"{p}.{key}"):
                    if isinstance(sub, list):
                        loc[id(sub)] = {"function": f["name"], "at": sp, "term": show(sub), "e": sub}
    from . import mathlang
    try:
        text = mathlang.emit_module(module)
    except Exception as exc:     # noqa: BLE001 -- machine state has no math notation yet: say so, keep going
        text = f"(no math notation: {exc})"
    a = Analysis(entry, card.get("provenance", {}).get("origin", ""), struct["functions"], math=text)

    # 2. obligations, discharged by a guard or the domain, else checked on inputs
    obls = []
    for f in module["functions"]:
        for o in obligations(f):
            o["function"] = f["name"]
            obls.append(o)

    # 3. instrumented reference runs on in-domain and boundary inputs
    rng = random.Random(seed)
    vec = [list(v["args"]) for v in card.get("vectors", [])]
    gen = [list(x) for x in V.inputs(card.get("generators") or [], 16, random.Random(seed), edge=False)]
    candidates = vec + gen + boundary_inputs(fn, rng)
    seen, rows = set(), []
    for args in candidates:
        k = repr(args)
        if k in seen:
            continue
        seen.add(k)
        out, fired, depth = _outcome(ctx, module, args)
        rows.append({"args": args, "ref": out, "fired": fired, "depth": depth,
                     "in_domain": in_domain(ctx, module, fn, args)})
    a.inputs = len(rows)

    groups: dict[tuple, dict] = {}
    for r in rows:
        for fz in r["fired"]:
            where = loc.get(fz["expr"]) if fz["expr"] else {"function": fz.get("function", entry), "at": "(call)",
                                                              "term": fz.get("function", entry)}
            key = (fz["law"], where["function"], where["at"])
            g = groups.setdefault(key, {"law": fz["law"], **{k: v for k, v in where.items() if k != "e"},
                                        "e": where.get("e"), "triggers": [], "in_domain_triggers": 0})
            if r["in_domain"]:
                g["in_domain_triggers"] += 1
            g["triggers"].append({"args": r["args"], "ref": r["ref"], "in_domain": r["in_domain"],
                                  "operands": fz["args"]})
    for o in obls:                                  # an open obligation a refused input reaches is a counterexample
        if o["status"] == "open":
            hits = [g for g in groups.values() if g.get("at") == o["at"] and g.get("function") == o["function"]
                    and g["law"] in ("int_div_zero", "float_div_zero", "float_exception", "shift_count")]
            if hits:
                t = next((t for t in hits[0]["triggers"] if t["in_domain"]), hits[0]["triggers"][0])
                o["counterexample"] = {"args": t["args"], "ref": t["ref"], "in_domain": t["in_domain"]}
            else:
                o["status"] = "sampled"
                o["via"] = f"no refusal on {len(rows)} inputs (sampled, not proved)"
        o.pop("goal", None)
        o.pop("expr_id", None)
    a.obligations = obls

    static = _static_findings(module, struct)
    inputs_ok = [r for r in rows if r["in_domain"] and "value" in r["ref"]][:3]
    for s in static:
        key = (s["law"], s["function"], s["at"])
        groups.setdefault(key, {"law": s["law"], "function": s["function"], "at": s["at"], "term": s["term"],
                                "triggers": [{"args": r["args"], "ref": r["ref"], "in_domain": True, "operands": []}
                                             for r in inputs_ok],
                                "in_domain_triggers": len(inputs_ok), "static": True})

    # 4. run the triggers in every runner
    chosen: list[list] = []
    for g in groups.values():
        g["triggers"].sort(key=lambda t: (not t["in_domain"], t["ref"].get("error") == "step budget"
                                          and g["law"] != "step_budget"))
        if g["law"] != "step_budget" and any(t["ref"].get("error") != "step budget" for t in g["triggers"]):
            g["triggers"] = [t for t in g["triggers"] if t["ref"].get("error") != "step budget"]
        g["triggers"] = g["triggers"][:1 if g["law"] == "step_budget" else per_law]
        for t in g["triggers"]:
            if t["args"] not in chosen:
                chosen.append(t["args"])
    control = next((r["args"] for r in rows if r["in_domain"] and not r["fired"] and "value" in r["ref"]), None)
    if control is not None and control not in chosen:
        chosen.append(control)
    budget = {repr(r["args"]) for r in rows if r["ref"].get("error") == "step budget"}
    machine = bool(module.get("globals") or module.get("arrays") or fn.get("returns") == "void")
    results: dict[str, dict[str, dict]] = {}
    if run and chosen and not machine:
        rs = pool if pool is not None else runners(ctx, langs)
        a.runners = [r[0] for r in rs]

        def one(r):
            bits = r[2].get("int_bits")
            ok_inputs = [x for x in chosen if _emittable(fn, x, bits)]
            fast = [x for x in ok_inputs if repr(x) not in budget]
            slow = [x for x in ok_inputs if repr(x) in budget]
            got = (_run_one(ctx, r, module, fast) if fast else []) + \
                (_run_one(ctx, r, module, slow, slow=True) if slow else [])
            return r[0], {repr(x): g for x, g in zip(fast + slow, got)}
        with ThreadPoolExecutor(max_workers=4) as ex:
            for name, res in ex.map(one, rs):
                results[name] = res
    if control is not None and results:
        a.control = {"args": control, "disagree": sorted(n for n, res in results.items()
                                                         if repr(control) in res and
                                                         _agree(_outcome(ctx, module, control)[0],
                                                                res[repr(control)]) is False)}
    for key, g in sorted(groups.items()):
        law = LAWS[g["law"]]
        runs = []
        for t in g["triggers"]:
            per = {}
            for name, res in results.items():
                got = res.get(repr(t["args"]))
                if got is None:
                    continue
                ag = _agree(t["ref"], got)
                per[name] = {**got, "agrees": ag}
            runs.append({**t, "runners": per})
        if law.id == "step_budget":          # timing: the runners split into those that finish and those that don't
            for r in runs:
                for x in r["runners"].values():
                    x["agrees"] = None if "gap" in x else "value" in x
        differs = sorted({n for r in runs for n, x in r["runners"].items() if x["agrees"] is False})
        agrees = sorted({n for r in runs for n, x in r["runners"].items() if x["agrees"] is True} - set(differs))
        if law.id == "step_budget":
            differs, agrees = (differs, agrees) if differs and agrees else ([], [])
        verdict = "witnessed" if differs else "guarded" if agrees else "predicted"
        fz = runs[0]["operands"] if runs else []
        names = {"a": show(g["e"][1]) if g.get("e") and len(g["e"]) > 1 and isinstance(g["e"][1], list) else "",
                 "b": show(g["e"][2]) if g.get("e") and len(g["e"]) > 2 and isinstance(g["e"][2], list) else ""}
        a.findings.append({
            "law": law.id, "title": law.title, "function": g["function"], "at": g["at"], "term": g["term"],
            "condition": law.condition.format(term=g["term"], **names), "verdict": verdict,
            "in_domain": g["in_domain_triggers"] > 0, "static": bool(g.get("static")),
            "first": runs[0] if runs else None, "operands": fz, "triggers": runs,
            "differs": differs, "agrees": agrees,
            "why": {n: law_note(law, n) for n in differs}, "fix": law.fix,
        })
    a.findings.sort(key=lambda f: (not f["in_domain"], {"witnessed": 0, "predicted": 1, "guarded": 2}[f["verdict"]],
                                   f["function"], f["at"]))
    return a


def explain(ctx, module: dict, args: list) -> list[dict]:
    """Which laws fire when the reference runs ``args``: the explanation of a runner that differs there."""
    loc = {}
    for f in module["functions"]:
        for s, p in _stmts(f["body"]):
            for key, e in _exprs(s):
                for sub, sp in _walk(e, f"{p}.{key}"):
                    if isinstance(sub, list):
                        loc[id(sub)] = (f["name"], sp, show(sub))
    ref, fired, depth = _outcome(ctx, module, args)
    out = []
    for fz in fired:
        fn, at, term = loc.get(fz["expr"], (fz.get("function", module["entry"]), "(call)", ""))
        law = LAWS[fz["law"]]
        out.append({"law": law.id, "title": law.title, "function": fn, "at": at, "term": term,
                    "operands": [V.short(x) for x in fz["args"]], "fix": law.fix})
    return out


def analyse_files(ctx, files, run: bool = True, langs: list[str] | None = None, seed: int | None = None,
                  only: list[str] | None = None, progress=None) -> dict:
    from .matrix import frontend_for
    seed = V.fresh_seed() if seed is None else seed
    pool = runners(ctx, langs) if run else []
    out, not_lifted = [], []
    for path in files:
        fe = frontend_for(path)
        if fe is None:
            not_lifted.append({"file": str(path), "function": None, "reasons": ["no frontend for this extension"]})
            continue
        cards, gaps = fe.cards(ctx, path, seed)
        not_lifted += [{"file": str(path), "function": n, "reasons": r} for n, r in gaps.items()]
        for card in cards:
            if only and card["ir"]["entry"] not in only:
                continue
            if progress:
                progress(f"{fe.lang}:{card['ir']['entry']}")
            an = analyse_card(ctx, card, run=run, seed=seed, pool=pool)
            d = an.__dict__.copy()
            d["file"], d["source"] = str(path), fe.lang
            out.append(_jsonable(d))
    return {"seed": seed, "runners": [r[0] for r in pool], "functions": out, "not_lifted": not_lifted,
            "summary": summary(out)}


def _jsonable(x):
    if isinstance(x, dict):
        return {k: _jsonable(v) for k, v in x.items() if k != "e"}
    if isinstance(x, (list, tuple)):
        return [_jsonable(v) for v in x]
    if isinstance(x, int) and not isinstance(x, bool):
        return V.short(x)
    if isinstance(x, float) and not math.isfinite(x):
        return repr(x)
    return x


def summary(functions: list[dict]) -> dict:
    s = {"functions": len(functions), "latent": 0, "boundary": 0, "guarded": 0, "predicted": 0,
         "obligations": {"proved": 0, "domain": 0, "sampled": 0, "open": 0}, "by_law": {}}
    for f in functions:
        for o in f["obligations"]:
            s["obligations"][o["status"]] += 1
        for x in f["findings"]:
            if x["verdict"] == "witnessed":
                s["latent" if x["in_domain"] else "boundary"] += 1
                s["by_law"][x["law"]] = s["by_law"].get(x["law"], 0) + 1
            else:
                s[x["verdict"]] += 1
    return s


# ---- text --------------------------------------------------------------------------------------------------------

def _val(o: dict) -> str:
    if "value" in o:
        v = o["value"]
        return str(v) if not isinstance(v, str) else v
    if "error" in o:
        return "⊥ " + o["error"]
    return "gap"


def report_text(rep: dict, show_all: bool = False) -> str:
    lines = [f"seed {rep['seed']} · runners: {', '.join(rep['runners']) or 'none (--no-run)'}"]
    for f in rep["functions"]:
        st = f["structure"][f["function"]]
        lines += ["", f"{st['signature']['value']}    ({f['source']}: {f['file']})",
                  f"  structure: recursion {st['recursion']['value']}, loops {st['loops']['value']}, "
                  f"calls {', '.join(st['calls']['value']) or '—'}, {'pure' if st['pure']['value'] else 'effects'}"]
        for o in f["obligations"]:
            mark = {"proved": "✓", "domain": "✓", "sampled": "~", "open": "✗"}[o["status"]]
            ce = o.get("counterexample")
            tail = f"; fails at {f['function']}({', '.join(map(str, ce['args']))}) → {_val(ce['ref'])}" if ce else ""
            lines.append(f"  {mark} {o['term']} needs {o['needs']}: {o['status']} ({o['via']}){tail}")
        shown = [x for x in f["findings"] if show_all or x["verdict"] == "witnessed"]
        hidden = len(f["findings"]) - len(shown)
        for x in shown:
            where = "in domain" if x["in_domain"] else "outside the declared domain"
            lines.append(f"  {'✗' if x['verdict'] == 'witnessed' else '·'} {x['law']} — {x['condition']} "
                         f"[{x['verdict']}, {where}]")
            t = x["first"]
            if t:
                lines.append(f"      {f['function']}({', '.join(map(str, t['args']))}): reference {_val(t['ref'])}")
                if x["law"] == "step_budget":
                    done = [n for n, r in t["runners"].items() if r["agrees"] is True]
                    late = [f"{n} ({_val(r)})" for n, r in t["runners"].items() if r["agrees"] is False]
                    lines.append(f"      finished: {', '.join(done) or '—'}; did not finish: {', '.join(late) or '—'}")
                else:
                    diff = [f"{n} {_val(r)}" for n, r in t["runners"].items() if r["agrees"] is False]
                    same = [n for n, r in t["runners"].items() if r["agrees"] is True]
                    if diff:
                        lines.append("      differs: " + "; ".join(diff))
                    if same:
                        lines.append("      agrees: " + ", ".join(same))
            notes: dict[str, list[str]] = {}
            for n, why in x["why"].items():
                if why:
                    notes.setdefault(why, []).append(n)
            for why, ns in notes.items():
                lines.append(f"      why {', '.join(ns)}: {why}")
            if x["verdict"] == "witnessed":
                lines.append(f"      fix: {x['fix']}")
        if hidden:
            lines.append(f"  ({hidden} guarded or predicted findings; --all shows them)")
    s = rep["summary"]
    lines += ["", f"{s['functions']} functions · latent flaws (witnessed in domain) {s['latent']} · boundary "
                  f"differences {s['boundary']} · guarded {s['guarded']} · predicted {s['predicted']} · obligations "
                  + ", ".join(f"{k} {v}" for k, v in s["obligations"].items())]
    if rep["not_lifted"]:
        lines.append("not lifted: " + "; ".join(f"{x['function']} ({x['reasons'][0] if x['reasons'] else '?'})"
                                                for x in rep["not_lifted"][:8]))
    return "\n".join(lines)


def laws_text() -> str:
    out = []
    for law in LAWS.values():
        out.append(f"{law.id}: {law.title}\n  when {law.condition.format(term='t', a='a', b='b')}\n  fix: {law.fix}")
        out += [f"    {k}: {v}" for k, v in law.runners.items()]
    return "\n".join(out)


__all__ = ["LAWS", "VARIANTS", "Analysis", "analyse_card", "analyse_files", "explain", "laws_text", "obligations",
           "report_text", "runners", "structure"]
