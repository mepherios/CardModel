"""lean_logic — a derivation becomes a Lean proof term; the Lean kernel re-checks every step.

Encoding (faithful, no axioms):

* every symbol is a constructor of one finite type ``Obj`` (``deriving DecidableEq``);
* a predicate with facts only (EDB) is a decidable ``abbrev``: membership of its argument tuple in the
  list of its facts. Its premises (and their negations) are proved by ``decide``;
* a predicate with rules (IDB) is an ``inductive`` Prop: one constructor per rule
  (``∀ vars, premises → head``) and one per fact; mutually recursive predicates share a ``mutual`` block;
* tests and bindings are decidable propositions over ``Int`` (proved by ``decide``);
* a derived fact's proof tree becomes a constructor application, checked by the kernel.

So ``theorem cm_fact_0 : ancestor Obj.«alice» Obj.«dave» := ...`` type-checks only if the derivation
is a real derivation in the encoded theory.

Honest limits (L1): aggregates, function calls, floats and negation of derived (IDB) predicates are not
encoded (reported per fact as ``not_exportable`` with the reason); an argument position must hold either
symbols or integers, not both; existential variables under negation must range over symbols.
"""
from __future__ import annotations

import re
from collections import defaultdict

from ..engines import logic as L

RESERVED = {"id", "max", "min", "and", "or", "not", "true", "false", "True", "False", "List", "Nat", "Int", "Prop",
            "Type", "fun", "let", "in", "if", "then", "else", "do", "by", "at", "from", "have", "show", "match",
            "with", "where", "open", "end", "section", "namespace", "theorem", "def", "abbrev", "inductive",
            "structure", "class", "instance", "example", "variable", "universe", "mutual", "deriving", "calc",
            "obtain", "rfl", "decide", "trivial", "Obj", "Bool", "String", "Option", "some", "none", "this",
            "Sort", "forall", "exists", "local", "private", "protected", "export", "import", "set_option",
            "attribute", "notation", "macro", "syntax", "partial", "unsafe", "noncomputable", "omega", "simp"}
TIMEOUT_S = 300


class NotExportable(ValueError):
    pass


def _ident(name: str) -> str:
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9_']*", name) and name not in RESERVED:
        return name
    return "cm_" + re.sub(r"[^A-Za-z0-9_]", "_", name)


def _sym(s: str) -> str:
    if "»" in s or "«" in s:
        raise NotExportable(f"symbol {s!r} contains a guillemet")
    return f"Obj.«{s}»"


class Encoder:
    def __init__(self, model: L.Model):
        self.model = model
        self.prog = model.program
        self.rules_by_head = defaultdict(list)
        for r in self.prog.rules:
            if r.head is not None:
                self.rules_by_head[r.head.pred].append(r)
        self.arity = self.prog.predicates()

    # -- which predicates take part ------------------------------------------------------------------
    def closure(self, preds: set[str]) -> set[str]:
        out, todo = set(), list(preds)
        while todo:
            p = todo.pop()
            if p in out:
                continue
            out.add(p)
            for r in self.rules_by_head.get(p, []):
                for lit in r.body:
                    for a in L._atoms_of_lit(lit):
                        todo.append(a.pred)
        return out

    # -- sorts: each (pred, position) holds ints or symbols ----------------------------------------------
    def sorts(self, preds: set[str]) -> dict[tuple[str, int], str]:
        parent: dict = {}

        def find(x):
            while parent.setdefault(x, x) != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(a, b):
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[ra] = rb

        kind: dict = defaultdict(set)

        def note(node, value):
            if isinstance(value, bool):
                kind[node].add("sym")
            elif isinstance(value, int):
                kind[node].add("int")
            elif isinstance(value, float):
                kind[node].add("float")
            else:
                kind[node].add("sym")

        for p in preds:
            for tup in self.model.db.rel.get(p, ()):
                for i, v in enumerate(tup):
                    note((p, i), v)
        for p in preds:
            for r in self.rules_by_head.get(p, []):
                rid = id(r)
                for a in [r.head] + [x for lit in r.body for x in L._atoms_of_lit(lit)]:
                    for i, t in enumerate(a.args):
                        if isinstance(t, L.Var):
                            union((a.pred, i), ("var", rid, t.name))
                        else:
                            note((a.pred, i), t)
                for lit in r.body:
                    if isinstance(lit, (L.Test, L.Bind)):
                        for v in lit.vars() | ({lit.var} if isinstance(lit, L.Bind) else set()):
                            if _arith(lit.expr, v):
                                kind[("var", rid, v)].add("int")
                        if isinstance(lit, L.Bind):
                            kind[("var", rid, lit.var)].add("int" if _numeric(lit.expr) else "any")
        merged: dict = defaultdict(set)
        for node, ks in kind.items():
            merged[find(node)] |= ks
        out = {}
        for node in list(parent) + list(kind):
            ks = merged[find(node)] - {"any"}
            if len(ks) > 1:
                raise NotExportable(f"{_node_name(node)} mixes {sorted(ks)}")
            if "float" in ks:
                raise NotExportable(f"{_node_name(node)} holds floats")
            out[node] = next(iter(ks)) if ks else "sym"
        self._find = find
        self._merged = merged
        return out

    def var_sort(self, rule, name) -> str:
        node = ("var", id(rule), name)
        ks = self._merged.get(self._find(node), set()) - {"any"}
        return next(iter(ks)) if ks else "sym"

    # -- source ------------------------------------------------------------------------------------------
    def blocker(self, preds: set[str]) -> str | None:
        for p in sorted(preds):
            for r in self.rules_by_head.get(p, []):
                for lit in r.body:
                    if isinstance(lit, L.Agg):
                        return f"rule {r.name} uses an aggregate"
                    if isinstance(lit, L.Neg) and lit.atom.pred in self.rules_by_head:
                        return f"rule {r.name} negates the derived predicate {lit.atom.pred}"
                    if isinstance(lit, (L.Test, L.Bind)) and _has_call(lit.expr):
                        return f"rule {r.name} calls a function"
        return None

    def source(self, targets: list[tuple[str, tuple]]) -> tuple[str, list[dict]]:
        thms, ok_targets = [], []
        for k, (pred, args) in enumerate(targets):
            why = self.blocker(self.closure({pred}))
            if why:
                thms.append({"name": f"cm_fact_{k}", "fact": str(L.Atom(pred, tuple(args))),
                             "status": "not_exportable", "detail": why})
            else:
                ok_targets.append((k, pred, args))
        preds = self.closure({p for _, p, _ in ok_targets})
        sorts = self.sorts(preds)
        self.S = sorts
        syms: set[str] = set()
        for p in preds:
            for tup in self.model.db.rel.get(p, ()):
                syms |= {v for v in tup if isinstance(v, str)}
            for r in self.rules_by_head.get(p, []):
                for a in [r.head] + [x for lit in r.body for x in L._atoms_of_lit(lit)]:
                    syms |= {t for t in a.args if isinstance(t, str)}
                for lit in r.body:
                    if isinstance(lit, (L.Test, L.Bind)):
                        syms |= _syms(lit.expr)
        for _, _, args in ok_targets:
            syms |= {v for v in args if isinstance(v, str)}
        lines = ["-- generated by cardmodel (emit/lean_logic.py): a derivation is a proof term", "",
                 "namespace CardLogic", ""]
        if syms:
            lines.append("inductive Obj where")
            for s in sorted(syms):
                lines.append(f"  | «{s}»")
            lines.append("  deriving DecidableEq, Repr")
            lines.append("")
        self.edb = {p for p in preds if p not in self.rules_by_head}
        for p in sorted(self.edb):
            lines.extend(self.edb_def(p))
        comps = [c for c in L.strata(self.prog) if any(p in preds and p in self.rules_by_head for p in c)]
        for comp in comps:
            group = [p for p in comp if p in preds and p in self.rules_by_head]
            if len(group) > 1:
                lines.append("mutual")
            for p in group:
                lines.extend(self.idb_def(p))
            if len(group) > 1:
                lines.append("end")
            lines.append("")
        for k, pred, args in ok_targets:
            name = f"cm_fact_{k}"
            try:
                proof = self.model.proof(pred, list(args))
                term = self.term(proof)
                stmt = self.atom_text(pred, tuple(args))
                thms.append({"name": name, "fact": str(L.Atom(pred, tuple(args))), "line": None,
                             "text": f"theorem {name} : {stmt} :=\n  {term}"})
            except NotExportable as exc:
                thms.append({"name": name, "fact": str(L.Atom(pred, tuple(args))), "status": "not_exportable",
                             "detail": str(exc)})
        thms.sort(key=lambda t: int(t["name"].rsplit("_", 1)[1]))
        for t in thms:
            if "text" in t:
                t["line"] = len(lines) + 1
                lines.extend(t["text"].split("\n"))
                lines.append("")
        lines.append("end CardLogic")
        return "\n".join(lines) + "\n", thms

    def sort_type(self, p: str, i: int) -> str:
        return "Int" if self.S.get((p, i), "sym") == "int" else "Obj"

    def const(self, v) -> str:
        if isinstance(v, bool):
            return _sym("true" if v else "false")
        if isinstance(v, int):
            return f"({v} : Int)"
        if isinstance(v, float):
            raise NotExportable("float constant")
        return _sym(v)

    def atom_text(self, pred: str, args: tuple, names: dict | None = None) -> str:
        parts = [_ident(pred)]
        for t in args:
            if isinstance(t, L.Var):
                parts.append(names[t.name])
            else:
                parts.append(self.const(t))
        return " ".join(parts) if args else _ident(pred)

    def edb_def(self, p: str) -> list[str]:
        n = self.arity.get(p, 0)
        facts = sorted(self.model.db.rel.get(p, ()), key=L._sort_key)
        if n == 0:
            return [f"abbrev {_ident(p)} : Prop := {'True' if facts else 'False'}", ""]
        types = [self.sort_type(p, i) for i in range(n)]
        params = " ".join(f"(x{i} : {t})" for i, t in enumerate(types))
        tup_t = " × ".join(types)
        tup_v = ", ".join(f"x{i}" for i in range(n))
        items = ", ".join("(" + ", ".join(self.const(v) for v in f) + ")" if n > 1 else self.const(f[0])
                          for f in facts)
        lhs = f"({tup_v})" if n > 1 else "x0"
        return [f"abbrev {_ident(p)} {params} : Prop :=", f"  {lhs} ∈ ([{items}] : List ({tup_t}))", ""]

    def idb_def(self, p: str) -> list[str]:
        n = self.arity.get(p, 0)
        types = [self.sort_type(p, i) for i in range(n)]
        sig = " → ".join([*types, "Prop"])
        out = [f"inductive {_ident(p)} : {sig} where"]
        given = sorted((t for t in self.model.db.rel.get(p, ()) if self.model.why.get((p, t), ("",))[0] == "given"),
                       key=L._sort_key)
        self.fact_ctor = getattr(self, "fact_ctor", {})
        for i, t in enumerate(given):
            self.fact_ctor[(p, t)] = f"{_ident(p)}.f_{i}"
            out.append(f"  | f_{i} : {self.atom_text(p, t)}")
        for r in self.rules_by_head[p]:
            out.append(f"  | {self.ctor(r)} : {self.rule_type(r)}")
        return out

    def ctor(self, r) -> str:
        return "r_" + re.sub(r"[^A-Za-z0-9_]", "_", r.name)

    def rule_vars(self, r) -> list[str]:
        seen = []
        for a in [r.head] + [lit for lit in r.body]:
            if isinstance(a, L.Atom):
                vs = [t.name for t in a.args if isinstance(t, L.Var)]
            elif isinstance(a, L.Neg):
                vs = []      # existential locals live inside the premise; shared ones appear elsewhere
            elif isinstance(a, L.Bind):
                vs = sorted(L.expr_vars(a.expr)) + [a.var]
            elif isinstance(a, L.Test):
                vs = sorted(L.expr_vars(a.expr))
            else:
                vs = []
            for v in vs:
                if v not in seen:
                    seen.append(v)
        return seen

    def rule_type(self, r) -> str:
        vs = self.rule_vars(r)
        names = {v: f"v_{re.sub(r'[^A-Za-z0-9_]', '_', v)}" for v in vs}
        binders = " ".join(f"({names[v]} : {'Int' if self.var_sort(r, v) == 'int' else 'Obj'})" for v in vs)
        prem = [self.premise_type(r, lit, names) for lit in r.body]
        head = self.atom_text(r.head.pred, r.head.args, names)
        body = " → ".join([*prem, head])
        return f"∀ {binders}, {body}" if binders else body

    def premise_type(self, r, lit, names) -> str:
        if isinstance(lit, L.Atom):
            return self.atom_text(lit.pred, lit.args, names)
        if isinstance(lit, L.Neg):
            local = [t.name for t in lit.atom.args if isinstance(t, L.Var) and t.name not in names]
            if not local:
                return f"¬ {self.atom_text(lit.atom.pred, lit.atom.args, names)}"
            inner = dict(names)
            binders = []
            for v in dict.fromkeys(local):
                inner[v] = f"z_{re.sub(r'[^A-Za-z0-9_]', '_', v)}"
                pos = [i for i, t in enumerate(lit.atom.args) if isinstance(t, L.Var) and t.name == v]
                if self.sort_type(lit.atom.pred, pos[0]) != "Obj":
                    raise NotExportable(f"rule {r.name}: an existential over integers under negation")
                binders.append(f"({inner[v]} : Obj)")
            return f"(∀ {' '.join(binders)}, ¬ {self.atom_text(lit.atom.pred, lit.atom.args, inner)})"
        if isinstance(lit, L.Test):
            return f"({lean_prop(lit.expr, names)})"
        if isinstance(lit, L.Bind):
            return f"({names[lit.var]} = {lean_term(lit.expr, names)})"
        raise NotExportable(f"rule {r.name}: literal {lit}")

    # -- proof terms -------------------------------------------------------------------------------------
    def term(self, proof: dict) -> str:
        pred = proof["pred"]
        args = tuple(proof["args"])
        if proof["by"] == "given":
            if pred in self.edb:
                return "(by decide)"
            return self.fact_ctor[(pred, args)]
        rule = next(r for r in self.rules_by_head[pred] if r.name == proof["by"])
        vs = self.rule_vars(rule)
        vals = []
        for v in vs:
            if v not in proof["bindings"]:
                raise NotExportable(f"rule {rule.name}: variable {v} has no value in the derivation")
            val = proof["bindings"][v]
            vals.append(self.const(val))
        kids = []
        for k, lit in zip(proof["premises"], rule.body):
            if "fact" in k:
                kids.append(self.term(k))
            elif "absent" in k:
                local = [t for t in lit.atom.args if isinstance(t, L.Var) and t.name not in proof["bindings"]]
                if local:
                    nz = len(set(t.name for t in local))
                    kids.append(f"(by intro {' '.join('z' + str(i) for i in range(nz))}; "
                                + " ".join(f"cases z{i} <;>" for i in range(nz)) + " decide)")
                else:
                    kids.append("(by decide)")
            else:
                kids.append("(by decide)")
        head = f"{_ident(pred)}.{self.ctor(rule)}"
        return "(" + " ".join([head, *vals, *kids]) + ")"


def _node_name(node) -> str:
    if node[0] == "var":
        return f"variable {node[2]}"
    return f"{node[0]} argument {node[1] + 1}"


def _arith(e, v) -> bool:
    """Does variable v occur under an arithmetic or order op in e (so it must be an integer)?"""
    if isinstance(e, list) and e:
        if e[0] in ("ADD", "SUB", "MUL", "FLOORDIV", "MOD", "NEG", "ABS", "MIN", "MAX", "POW", "CMP_LT", "CMP_LE",
                    "CMP_GT", "CMP_GE"):
            return v in L.expr_vars(e)
        return any(_arith(a, v) for a in e[1:] if isinstance(a, list))
    return False


def _numeric(e) -> bool:
    return isinstance(e, list) and e[0] in ("int", "ADD", "SUB", "MUL", "FLOORDIV", "MOD", "NEG", "ABS", "MIN", "MAX",
                                            "POW")


def _has_call(e) -> bool:
    return isinstance(e, list) and bool(e) and (e[0] == "CALL" or any(_has_call(a) for a in e[1:]))


def _syms(e) -> set[str]:
    out: set[str] = set()
    if isinstance(e, list) and e:
        if e[0] == "sym":
            out.add(e[1])
        elif e[0] not in ("var", "int", "float", "bool"):
            for a in e[1:]:
                out |= _syms(a)
    return out


INFIX = {"ADD": "+", "SUB": "-", "MUL": "*"}
REL = {"CMP_EQ": "=", "CMP_NE": "≠", "CMP_LT": "<", "CMP_LE": "≤", "CMP_GT": ">", "CMP_GE": "≥"}


def lean_term(e, names) -> str:
    h = e[0]
    if h == "var":
        return names[e[1]]
    if h == "int":
        return f"({e[1]} : Int)"
    if h == "sym":
        return _sym(e[1])
    if h in INFIX:
        return f"({lean_term(e[1], names)} {INFIX[h]} {lean_term(e[2], names)})"
    if h == "NEG":
        return f"(-{lean_term(e[1], names)})"
    if h == "FLOORDIV":
        return f"(Int.fdiv {lean_term(e[1], names)} {lean_term(e[2], names)})"
    if h == "MOD":
        return f"(Int.fmod {lean_term(e[1], names)} {lean_term(e[2], names)})"
    if h in ("MIN", "MAX"):
        return f"({h.lower()} {lean_term(e[1], names)} {lean_term(e[2], names)})"
    if h == "ABS":
        x = lean_term(e[1], names)
        return f"(if {x} < 0 then -{x} else {x})"
    if h == "POW" and e[2][0] == "int" and e[2][1] >= 0:
        return f"({lean_term(e[1], names)} ^ {e[2][1]})"
    if h == "IF_EXPR":
        return f"(if {lean_prop(e[1], names)} then {lean_term(e[2], names)} else {lean_term(e[3], names)})"
    raise NotExportable(f"no Lean form for {h} in a rule")


def lean_prop(e, names) -> str:
    h = e[0]
    if h in REL:
        return f"{lean_term(e[1], names)} {REL[h]} {lean_term(e[2], names)}"
    if h == "AND":
        return f"({lean_prop(e[1], names)}) ∧ ({lean_prop(e[2], names)})"
    if h == "OR":
        return f"({lean_prop(e[1], names)}) ∨ ({lean_prop(e[2], names)})"
    if h == "NOT":
        return f"¬ ({lean_prop(e[1], names)})"
    if h == "sym" and e[1] in ("true", "false"):
        return "True" if e[1] == "true" else "False"
    raise NotExportable(f"no Lean proposition for {h}")


def certify(model: L.Model, targets: list[tuple[str, tuple]], check: bool = True) -> dict:
    """Lean source proving each target fact from the model's theory; with ``check`` the kernel verifies it."""
    from . import lean as LE
    enc = Encoder(model)
    try:
        src, thms = enc.source(targets)
    except NotExportable as exc:
        return {"status": "not_exportable", "detail": str(exc), "theorems": []}
    out = {"source": src, "theorems": thms, "status": "emitted"}
    if not check:
        return out
    exe = LE.lean_exe()
    if exe is None:
        out["status"] = "no_toolchain"
        return out
    lines = src.split("\n")
    first = min((t["line"] for t in thms if t.get("line")), default=None)
    if first is None:
        out["status"] = "nothing_to_check"
        return out
    header = lines[:first - 1]
    items = [(t["name"], t["text"]) for t in thms if t.get("text")]
    items[-1] = (items[-1][0], items[-1][1] + "\n\nend CardLogic")
    verdict = LE.check_batch(exe, items, header=header, timeout_s=TIMEOUT_S)
    for t in thms:
        if t.get("status") == "not_exportable":
            continue
        v = verdict.get(t["name"], "unchecked")
        t["status"] = "checked" if v == "ok" else ("unchecked" if v.startswith("unchecked") else "rejected")
        if v != "ok":
            t["detail"] = v
    statuses = {t.get("status") for t in thms if t.get("text")}
    out["status"] = "checked" if statuses == {"checked"} else ("rejected" if "rejected" in statuses else "unchecked")
    out["toolchain"] = exe
    return out


__all__ = ["Encoder", "NotExportable", "certify", "lean_prop", "lean_term"]
