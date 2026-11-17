"""induce — learning a computation from its behaviour: understanding, not recall.

Every other engine starts from something written down: source code to lift, rule cards to rewrite with, law
templates to instantiate. This engine starts from *behaviour only*. It is shown what a computation does (input and
output examples, or a black box it may question) and it has to find *why*: a program over the op cards that
produces that behaviour, and that keeps producing it on inputs it has never seen. That is what "understanding"
means here, and it is measured, never asserted:

1. **Hypotheses are built, not stored.** The hypothesis space is every term over the op cards with IR semantics
   (``cards/op``, the same table the interpreter, the translators and the laws use) and over the concepts the model
   has learned so far. Nothing about any particular task is written in this file. Terms are enumerated
   bottom-up by size; two terms that behave the same on every example seen are one hypothesis (observational
   equivalence: the behaviour vector is the identity, as in funcalg and the Gödel content of a term).
2. **Occam, as description length (MDL).** The chosen hypothesis minimises ``L(h) + L(data | h)``: the bits to
   write the program plus the bits to correct its mistakes. A program that memorises the examples costs more
   bits than the examples themselves, so it is never chosen. The task is *understood* only when the best
   hypothesis compresses the examples (``compression > 1``); otherwise the honest answer is "not understood", and
   noisy examples are tolerated when a short program explains all but a few of them.
3. **Generalisation is tested, not assumed.** Examples are split: the program is fitted on one part and scored on
   held-out examples it never saw. When the computation is a black box the learner can question, it asks: it
   draws fresh inputs, compares, and adds every counterexample to what it learns from (counterexample-guided
   induction) until its hypothesis survives a round of questions.
4. **Concepts: learning to learn.** After a set of tasks is understood, sub-programs that recur across *different*
   tasks are abstracted (variables become parameters) into concept cards. A concept joins the vocabulary as one
   node, so later tasks that need it are shorter to describe and reachable by the same search budget: a task
   unreachable before becomes solvable after, and a concept can be built from earlier concepts (a hierarchy). The
   concept is structure, not an answer: it stores a program, never input/output pairs.
5. **Carried into the core.** A learned program inlines its concepts into a plain IR function, is re-checked by
   the IR interpreter (the core's reference semantics), and from there is like any lifted function: it can be
   translated to every language card, optimized and given laws.

Honest limits (L1): scalar ``int`` and ``bool`` values (lists, strings and floats come next); programs are
expressions (no loops: funcalg covers linear recurrences, loops through concepts are the next step); search is
exhaustive by size within a budget, so a long program with no concept to shorten it is reported as not found, not
as non-existent; held-out accuracy and passed questions are evidence on the sampled inputs, not proof (a learned
program becomes a theorem only through the laws and Lean, as every other card).
"""
from __future__ import annotations

import hashlib
import json
import math
import random
from dataclasses import dataclass, field

from .ir import SPECIAL, Interpreter
from .laws import DIVISORS, SHIFTS

SCALARS = ("int", "bool")
LIMIT = 1 << 62                   # a value past this is treated as undefined (keeps search finite, fits i64 targets)
CONSTANTS = (0, 1, 2)
DEFAULT_MAX_SIZE = 7
DEFAULT_BUDGET = 6_000_000        # terms considered per search
MIN_CONCEPT_TASKS = 2             # a concept must recur in this many different tasks


class InduceError(Exception):
    pass


# -- the vocabulary -----------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Prim:
    """One way to build a term: an op card at one scalar signature, IF_EXPR, or a learned concept."""
    name: str
    args: tuple
    ret: str
    kind: str = "op"              # op | if | concept


@dataclass
class Concept:
    """A learned sub-program: ``body`` is an IR term over ``["var", "x0"] ..``; it may use other concepts."""
    name: str
    params: list                  # [type, ...]
    ret: str
    body: list
    evidence: dict = field(default_factory=dict)

    def card(self) -> dict:
        return {"name": self.name, "category": "concept", "tier": 3, "params": self.params, "returns": self.ret,
                "body": self.body, "statement": f"{self.name}({', '.join(f'x{i}' for i in range(len(self.params)))})"
                f" = {show(self.body)}", "metadata": {"learned": True, **self.evidence},
                "provenance": {"tool": "cardmodel induce", "engine": "engines/induce.py"}}

    @classmethod
    def from_card(cls, card) -> "Concept":
        return cls(card["name"], list(card["params"]), card["returns"], card["body"],
                   dict(card.get("metadata") or {}))


def vocabulary(ops, concepts=()) -> list[Prim]:
    """Every scalar signature of every op card that has reference semantics, IF_EXPR, and the concepts."""
    out = []
    for name, spec in sorted(ops.items()):
        if spec.fn is None or name in SPECIAL:
            continue
        for sig in spec.types:
            if len(sig) == spec.arity + 1 and all(t in SCALARS for t in sig):
                out.append(Prim(name, tuple(sig[:-1]), sig[-1]))
    out.append(Prim("IF_EXPR", ("bool", "int", "int"), "int", "if"))
    out.append(Prim("AND", ("bool", "bool"), "bool", "and"))
    out.append(Prim("OR", ("bool", "bool"), "bool", "or"))
    for c in concepts:
        out.append(Prim(c.name, tuple(c.params), c.ret, "concept"))
    return out


# -- semantics ----------------------------------------------------------------------------------------------------
def defined(name: str, args) -> bool:
    """Where an op is defined and finite to evaluate: the same hypotheses the laws engine states for every law
    (engines/laws.defined): divisor != 0, shift amount in 0..64, power exponent in 0..8."""
    if name in DIVISORS:
        return args[1] != 0
    if name in SHIFTS:
        return 0 <= args[1] <= 64
    if name == "POW":
        return 0 <= args[1] <= 8
    return True


def _ok(v, t):
    if v is None:
        return None
    if t == "bool":
        return bool(v) if isinstance(v, bool) else None
    if isinstance(v, bool) or not isinstance(v, int) or abs(v) > LIMIT:
        return None
    return v


def evaluate(term, env: dict, ops, concepts: dict):
    """One value of ``term`` (None where it is undefined: an op error, or a value past LIMIT)."""
    head = term[0]
    if head == "var":
        return env[term[1]]
    if head in ("int", "bool"):
        return term[1]
    if head == "IF_EXPR":
        c = evaluate(term[1], env, ops, concepts)
        if c is None:
            return None
        return evaluate(term[2] if c else term[3], env, ops, concepts)
    if head in ("AND", "OR"):
        a = evaluate(term[1], env, ops, concepts)
        if a is None or a == (head == "OR"):
            return a
        return evaluate(term[2], env, ops, concepts)
    args = [evaluate(a, env, ops, concepts) for a in term[1:]]
    if any(a is None for a in args):
        return None
    if head in concepts:
        c = concepts[head]
        return evaluate(c.body, {f"x{i}": a for i, a in enumerate(args)}, ops, concepts)
    if not defined(head, args):
        return None
    try:
        v = ops[head].fn(*args)
    except Exception:                                   # noqa: BLE001 -- an op outside its domain is undefined here
        return None
    if isinstance(v, bool):
        return v
    return v if isinstance(v, int) and abs(v) <= LIMIT else None


def _apply(prim: Prim, vecs, ops, concepts, upto: int | None = None) -> tuple:
    n = len(vecs[0]) if upto is None else upto
    if prim.kind == "if":
        c, a, b = vecs
        return tuple(None if c[i] is None else (a[i] if c[i] else b[i]) for i in range(n))
    if prim.kind in ("and", "or"):
        a, b = vecs
        short = prim.kind == "or"
        return tuple(a[i] if a[i] is None or a[i] == short else b[i] for i in range(n))
    if prim.kind == "concept":
        con = concepts[prim.name]
        out = []
        for i in range(n):
            args = [v[i] for v in vecs]
            out.append(None if None in args else
                       _ok(evaluate(con.body, {f"x{j}": a for j, a in enumerate(args)}, ops, concepts), prim.ret))
        return tuple(out)
    fn = ops[prim.name].fn
    name = prim.name
    out = []
    for i in range(n):
        args = [v[i] for v in vecs]
        if None in args or not defined(name, args):
            out.append(None)
            continue
        try:
            out.append(_ok(fn(*args), prim.ret))
        except Exception:                               # noqa: BLE001
            out.append(None)
    return tuple(out)


def cost(term, ops, concepts: dict) -> float:
    """The op cards' own cost of a term (concepts count as their bodies): the tie-break between programs of equal
    description length, so ``ADD(SQ(x), 1)`` is preferred over the equal-length ``ABS(BIT_NOT(SQ(x)))``."""
    head = term[0]
    if head in ("var", "int", "bool"):
        return 0.0
    own = cost(concepts[head].body, ops, concepts) if head in concepts else \
        float((ops[head].card.get("cost") if head in ops else None) or 1.0)
    return own + sum(cost(a, ops, concepts) for a in term[1:])


def size(term) -> int:
    return 1 if term[0] in ("var", "int", "bool") else 1 + sum(size(a) for a in term[1:])


def show(term) -> str:
    head = term[0]
    if head == "var":
        return term[1]
    if head in ("int", "bool"):
        return repr(term[1])
    return f"{head}({', '.join(show(a) for a in term[1:])})"


def inline(term, concepts: dict):
    """The term with every concept replaced by its body: a plain IR expression the whole core understands."""
    head = term[0]
    if head in ("var", "int", "bool"):
        return term
    args = [inline(a, concepts) for a in term[1:]]
    if head in concepts:
        c = concepts[head]
        return _subst(inline(c.body, concepts), {f"x{i}": a for i, a in enumerate(args)})
    return [head, *args]


def _subst(term, env):
    if term[0] == "var":
        return env.get(term[1], term)
    if term[0] in ("int", "bool"):
        return term
    return [term[0], *(_subst(a, env) for a in term[1:])]


# -- description length -------------------------------------------------------------------------------------------
def value_bits(v) -> float:
    """Bits to write one output value outright (Elias-gamma-like for integers, 1 bit for a bool)."""
    if isinstance(v, bool):
        return 1.0
    return 2.0 * math.log2(abs(v) + 2) + 1.0


def table_bits(outputs) -> float:
    """What memorising costs: every output written out."""
    return sum(value_bits(y) for y in outputs)


# -- search -------------------------------------------------------------------------------------------------------
def _splits(total: int, parts: int):
    if parts == 1:
        if total >= 1:
            yield (total,)
        return
    for first in range(1, total - parts + 2):
        for rest in _splits(total - first, parts - 1):
            yield (first, *rest)


def search(params: list, inputs: list, outputs: list, ops, concepts=(), max_size: int = DEFAULT_MAX_SIZE,
           budget: int = DEFAULT_BUDGET, noise: float = 0.0) -> dict:
    """The minimum-description-length program for ``inputs -> outputs``.

    ``params``: [(name, type)]; ``inputs``: [tuple of values]; ``noise``: the largest fraction of examples the
    program may get wrong (0: exact). Returns the program, its bits, the table's bits, the terms evaluated and the
    distinct behaviours seen."""
    concepts = list(concepts)
    cmap = {c.name: c for c in concepts}
    vocab = vocabulary(ops, concepts)
    n = len(inputs)
    if n == 0:
        raise InduceError("no examples")
    ret = "bool" if all(isinstance(y, bool) for y in outputs) else "int"
    target = tuple(outputs)
    bits_node = math.log2(len(vocab) + len(params) + len(CONSTANTS))
    raw = table_bits(outputs)
    max_err = int(noise * n)
    err_bits = [math.log2(n + 1) + value_bits(y) for y in outputs]

    bank: dict[int, dict[str, list]] = {}
    seen: set = set()
    evaluated = 0
    best = None                       # (bits, size, term, errors)
    exhausted = False

    def consider(term, t, vec, s):
        nonlocal best
        if t != ret:
            return
        if vec == target:
            cand = (s * bits_node, s, term, 0)
        elif max_err:
            wrong = [i for i in range(n) if vec[i] != target[i]]
            if len(wrong) > max_err:
                return
            cand = (s * bits_node + sum(err_bits[i] for i in wrong), s, term, len(wrong))
        else:
            return
        if best is None or cand[:2] < best[:2] or (cand[:2] == best[:2] and
                                                   cost(cand[2], ops, cmap) < cost(best[2], ops, cmap)):
            best = cand               # equal length: the basic form (cheapest by the op cards' costs) wins

    def add(term, t, vec, s):
        key = (t, vec)
        if key in seen or all(v is None for v in vec):
            if vec == target:
                consider(term, t, vec, s)   # an equal-length explanation may be the more basic one
            return
        seen.add(key)
        bank.setdefault(s, {}).setdefault(t, []).append((term, vec))
        consider(term, t, vec, s)

    for name, t in params:
        add(["var", name], t, tuple(x[[p for p, _ in params].index(name)] for x in inputs), 1)
    for k in CONSTANTS:
        add(["int", k], "int", (k,) * n, 1)

    for s in range(2, max_size + 1):
        if best is not None and best[0] <= s * bits_node:
            break                     # no larger program can be shorter to describe
        last = s == max_size and not max_err      # nothing is built on the last level: only test against the goal
        for prim in vocab:
            if last and prim.ret != ret:
                continue
            k = len(prim.args)
            for sizes in _splits(s - 1, k):
                pools = [bank.get(sz, {}).get(t, []) for sz, t in zip(sizes, prim.args)]
                if any(not p for p in pools):
                    continue
                for combo in _product(pools):
                    evaluated += 1
                    if evaluated > budget:
                        exhausted = True
                        break
                    vecs = [c[1] for c in combo]
                    if last:
                        if _apply(prim, vecs, ops, cmap, upto=1)[0] != target[0]:
                            continue
                        vec = _apply(prim, vecs, ops, cmap)
                        if vec == target:
                            consider([prim.name, *(c[0] for c in combo)], prim.ret, vec, s)
                        continue
                    vec = _apply(prim, vecs, ops, cmap)
                    add([prim.name, *(c[0] for c in combo)], prim.ret, vec, s)
                if exhausted:
                    break
            if exhausted:
                break
        if exhausted:
            break
    out = {"evaluated": evaluated, "behaviours": len(seen), "budget_exhausted": exhausted,
           "table_bits": round(raw, 2), "bits_per_node": round(bits_node, 3), "returns": ret}
    if best is None:
        return {**out, "found": False}
    bits, sz, term, errors = best
    return {**out, "found": True, "term": term, "size": sz, "program_bits": round(bits, 2), "errors": errors,
            "compression": round(raw / bits, 3) if bits else None, "understood": bits < raw}


def _product(pools):
    if len(pools) == 1:
        for a in pools[0]:
            yield (a,)
        return
    for a in pools[0]:
        for rest in _product(pools[1:]):
            yield (a, *rest)


# -- tasks, generalisation and questions ---------------------------------------------------------------------------
@dataclass
class Task:
    """A computation to understand: named parameters, and examples and/or a black box (``oracle``) to question.

    ``sample(rng)`` draws one input tuple (the inputs the black box accepts); without it, integers in -20..20."""
    name: str
    params: list                                        # [(name, type)]
    examples: list = field(default_factory=list)        # [(inputs tuple, output)]
    oracle: object = None
    sample: object = None

    def draw(self, rng) -> tuple:
        if self.sample is not None:
            return tuple(self.sample(rng))
        return tuple(rng.choice((True, False)) if t == "bool" else rng.randint(-20, 20) for _, t in self.params)


def _edges(task: Task, rng) -> list:
    if task.sample is not None:
        return []
    out = []
    for v in (0, 1, -1):
        out.append(tuple(v if t == "int" else bool(v) for _, t in task.params))
    return out


def learn_task(task: Task, ops, concepts=(), seed: int = 0, n_examples: int = 12, holdout: float = 0.3,
               questions: int = 24, rounds: int = 4, max_size: int = DEFAULT_MAX_SIZE,
               budget: int = DEFAULT_BUDGET, noise: float = 0.0) -> dict:
    """Understand one task: fit on part of the examples, score on the held-out rest, then question the black box
    (when there is one) and learn again from every counterexample."""
    rng = random.Random(seed)
    cmap = {c.name: c for c in concepts}
    examples = list(task.examples)
    if task.oracle is not None and len(examples) < n_examples:
        pool = _edges(task, rng) + [task.draw(rng) for _ in range(n_examples)]
        for x in pool[:n_examples - len(examples)]:
            examples.append((x, task.oracle(*x)))
    if not examples:
        raise InduceError(f"task {task.name}: no examples and no black box")
    order = list(range(len(examples)))
    rng.shuffle(order)
    n_hold = int(len(examples) * holdout) if len(examples) >= 8 else 0
    held = [examples[i] for i in order[:n_hold]]
    train = [examples[i] for i in order[n_hold:]]
    history = []
    res = None
    for r in range(rounds):
        res = search(task.params, [x for x, _ in train], [y for _, y in train], ops, concepts, max_size, budget, noise)
        step = {"round": r, "train": len(train), "found": res["found"], "evaluated": res["evaluated"]}
        if not res["found"] or task.oracle is None:
            history.append(step)
            break
        term = res["term"]
        counter = None
        for _ in range(questions):
            x = task.draw(rng)
            y = task.oracle(*x)
            if evaluate(term, dict(zip([p for p, _ in task.params], x)), ops, cmap) != y:
                counter = (x, y)
                break
        step["counterexample"] = list(counter[0]) + [counter[1]] if counter else None
        history.append(step)
        if counter is None:
            break
        train.append(counter)
    out = {"task": task.name, "params": task.params, "rounds": history, **{k: v for k, v in res.items()}}
    if not res["found"]:
        return {**out, "understood": False}
    term = res["term"]
    names = [p for p, _ in task.params]

    def score(rows):
        return sum(evaluate(term, dict(zip(names, x)), ops, cmap) == y for x, y in rows)

    out["held_out"] = {"examples": len(held), "correct": score(held)} if held else None
    fresh = []
    if task.oracle is not None:
        fresh = [task.draw(rng) for _ in range(questions)]
        out["fresh"] = {"examples": len(fresh), "correct": sum(
            evaluate(term, dict(zip(names, x)), ops, cmap) == task.oracle(*x) for x in fresh)}
    out["program"] = show(term)
    out["ir"] = ir_function(task, term, res["returns"], cmap)
    out["ir_checked"] = _check_ir(out["ir"], [x for x, _ in examples], ops, term, names, cmap)
    gen = [v for v in (out["held_out"], out.get("fresh")) if v]
    out["generalises"] = all(v["correct"] == v["examples"] for v in gen) if gen else None
    # understood = the program generalises and is shorter than everything it explains written out: the examples
    # it learned from, the held-out ones and the answers to its questions (memorising them would cost more bits)
    seen_outputs = [y for _, y in train + held] + [task.oracle(*x) for x in fresh] if task.oracle else \
        [y for _, y in train + held]
    out["explained_bits"] = round(table_bits(seen_outputs), 2)
    out["compression"] = round(out["explained_bits"] / res["program_bits"], 3) if res["program_bits"] else None
    out["understood"] = out["generalises"] is not False and res["program_bits"] < out["explained_bits"]
    return out


def ir_function(task: Task, term, ret: str, cmap: dict) -> dict:
    """The learned program as a card-IR function (concepts inlined): translate, optimize and laws take it from here."""
    return {"name": task.name, "params": [{"name": p, "type": t} for p, t in task.params], "returns": ret,
            "locals": {}, "body": [{"k": "return", "value": inline(term, cmap)}]}


def _check_ir(fn: dict, inputs, ops, term, names, cmap) -> bool:
    """The core's own interpreter agrees with the search's semantics on every example (where defined)."""
    it = Interpreter({"functions": [fn]}, ops)
    for x in inputs:
        want = evaluate(term, dict(zip(names, x)), ops, cmap)
        if want is None:
            continue
        try:
            if it.call(fn["name"], list(x)) != want:
                return False
        except Exception:                               # noqa: BLE001
            return False
    return True


# -- concepts -----------------------------------------------------------------------------------------------------
def _types(term, var_types: dict, vocab_by_name: dict):
    head = term[0]
    if head == "var":
        return var_types.get(term[1])
    if head in ("int", "bool"):
        return head
    args = [_types(a, var_types, vocab_by_name) for a in term[1:]]
    for p in vocab_by_name.get(head, []):
        if list(p.args) == args:
            return p.ret
    return None


def _abstract(term):
    """The term up to its variables: each distinct variable becomes x0, x1, .. by first appearance."""
    names: dict = {}

    def walk(e):
        if e[0] == "var":
            names.setdefault(e[1], f"x{len(names)}")
            return ["var", names[e[1]]]
        if e[0] in ("int", "bool"):
            return e
        return [e[0], *(walk(a) for a in e[1:])]
    return walk(term), list(names)


def _holes(term):
    """The term, and the term with each non-leaf direct child made a hole (a parameter of the concept): the
    concept ``POW(x0, 2)`` is seen inside ``POW(SUB(a, b), 2)``."""
    yield term
    if term[0] in ("var", "int", "bool"):
        return
    kids = [i for i, a in enumerate(term[1:], 1) if a[0] not in ("var", "int", "bool")]
    for mask in range(1, 1 << len(kids)):
        t = list(term)
        for j, i in enumerate(kids):
            if mask >> j & 1:
                t[i] = ["var", f"?hole{i}"]
        yield t


def _subterms(term):
    yield term
    if term[0] not in ("var", "int", "bool"):
        for a in term[1:]:
            yield from _subterms(a)


def discover_concepts(solved: dict, params_of: dict, ops, concepts=(), min_tasks: int = MIN_CONCEPT_TASKS,
                      limit: int = 4) -> list[Concept]:
    """Sub-programs that recur across different understood tasks, abstracted over their variables.

    Utility = (tasks using it - 1) x (nodes saved per use): the compression the concept buys the corpus. A
    fragment that is just one op applied to distinct variables saves nothing and is skipped."""
    vocab = vocabulary(ops, concepts)
    by_name: dict = {}
    for p in vocab:
        by_name.setdefault(p.name, []).append(p)
    known = {json.dumps(c.body) for c in concepts}
    found: dict[str, dict] = {}
    for task, term in solved.items():
        vt0 = dict(params_of[task])
        for whole in _subterms(term):
            if whole[0] in ("var", "int", "bool"):
                continue
            for sub in _holes(whole):
                vt = dict(vt0)
                for i, a in enumerate(whole[1:], 1):
                    if sub[i] is not a:
                        vt[sub[i][1]] = _types(a, vt0, by_name)
                body, var_names = _abstract(sub)
                arity = len(var_names)
                saved = size(sub) - 1 - arity
                if arity == 0 or saved <= 0:
                    continue
                ptypes = [vt.get(v) for v in var_names]
                rt = _types(sub, vt, by_name)
                if rt is None or None in ptypes:
                    continue
                key = json.dumps(body)
                if key in known:
                    continue
                f = found.setdefault(key, {"body": body, "params": ptypes, "ret": rt, "tasks": set(), "uses": 0,
                                           "saved": saved})
                f["tasks"].add(task)
                f["uses"] += 1
    ranked = sorted((f for f in found.values() if len(f["tasks"]) >= min_tasks),
                    key=lambda f: (-(len(f["tasks"]) - 1) * f["saved"], -f["saved"], json.dumps(f["body"])))
    out = []
    for f in ranked:
        if any(json.dumps(f["body"]) in json.dumps(c.body) for c in out):
            continue                                    # a fragment inside one already chosen this round
        digest = hashlib.sha256(json.dumps(f["body"]).encode()).hexdigest()[:8].upper()
        out.append(Concept(f"CONCEPT_{digest}", f["params"], f["ret"], f["body"], {
            "abstracted_from": sorted(f["tasks"]), "uses": f["uses"], "nodes_saved_per_use": f["saved"],
            "utility": (len(f["tasks"]) - 1) * f["saved"]}))
        if len(out) >= limit:
            break
    return out


def curriculum(tasks: list[Task], ops, concepts=(), seed: int = 0, max_rounds: int = 3, **kw) -> dict:
    """Learn a set of tasks, abstract concepts from what was understood, and learn again with them, until nothing
    new is understood. Each round is one point on the learning curve."""
    concepts = list(concepts)
    params_of = {t.name: t.params for t in tasks}
    curve, last = [], {}
    for r in range(max_rounds):
        reports = {t.name: learn_task(t, ops, concepts, seed=seed + i, **kw) for i, t in enumerate(tasks)}
        solved = {n: _term_of(rep) for n, rep in reports.items() if rep.get("understood") and rep.get("generalises")
                  is not False}
        curve.append({"round": r, "concepts": [c.name for c in concepts], "understood": sorted(solved),
                      "evaluated": sum(rep["evaluated"] for rep in reports.values())})
        last = reports
        new = discover_concepts(solved, params_of, ops, concepts)
        if not new:
            break                                       # nothing recurs that is not known: the curve is flat
        concepts += new
    return {"curve": curve, "concepts": concepts, "reports": last}


def _term_of(rep):
    return rep.get("term")


# -- the built-in curriculum: black boxes the learner only questions ----------------------------------------------
def _clamp_sample(rng):
    lo = rng.randint(-20, 10)
    return (rng.randint(-30, 30), lo, lo + rng.randint(0, 20))


def bench_tasks() -> list[Task]:
    """Black boxes for the learning curve. The learner sees only the answers to its questions, never these
    lambdas; they stand for the world (a running program, an instrument, a user)."""
    I2 = [("a", "int"), ("b", "int")]
    return [
        Task("square", [("x", "int")], oracle=lambda x: x * x),
        Task("square_plus_one", [("x", "int")], oracle=lambda x: x * x + 1),
        Task("sum_of_squares", I2, oracle=lambda a, b: a * a + b * b),
        Task("square_of_difference", I2, oracle=lambda a, b: (a - b) ** 2),
        Task("scaled_square_error", [("a", "int"), ("b", "int"), ("k", "int")],
             oracle=lambda a, b, k: k * (a - b) ** 2),
        Task("distance_squared", [("a", "int"), ("b", "int"), ("c", "int"), ("d", "int")],
             oracle=lambda a, b, c, d: (a - c) ** 2 + (b - d) ** 2),
        Task("abs_difference", I2, oracle=lambda a, b: abs(a - b)),
        Task("manhattan", [("a", "int"), ("b", "int"), ("c", "int"), ("d", "int")],
             oracle=lambda a, b, c, d: abs(a - c) + abs(b - d)),
        Task("max3", [("a", "int"), ("b", "int"), ("c", "int")], oracle=lambda a, b, c: max(a, b, c)),
        Task("clamp", [("x", "int"), ("lo", "int"), ("hi", "int")], oracle=lambda x, lo, hi: min(max(x, lo), hi),
             sample=_clamp_sample),
        Task("within_tolerance", [("a", "int"), ("b", "int"), ("t", "int")],
             oracle=lambda a, b, t: abs(a - b) <= t),
        Task("is_even", [("x", "int")], oracle=lambda x: x % 2 == 0),
        Task("midpoint_floor", I2, oracle=lambda a, b: (a + b) // 2),
    ]


def save_concepts(store, concepts, layer=None) -> list[str]:
    names = []
    for c in concepts:
        store.save(c.card(), layer=layer, category="concept")
        names.append(c.name)
    return names


def load_concepts(store) -> list[Concept]:
    try:
        cards = list(store.cards("concept"))
    except Exception:                                   # noqa: BLE001 -- no concept registry yet
        return []
    out = [Concept.from_card(c) for c in cards]
    order, done = [], set()
    while out:                                          # a concept after the concepts its body uses
        progressed = False
        for c in list(out):
            used = {s[0] for s in _subterms(c.body)} & {o.name for o in out if o is not c}
            if not used - done:
                order.append(c)
                done.add(c.name)
                out.remove(c)
                progressed = True
        if not progressed:
            order += out
            break
    return order
