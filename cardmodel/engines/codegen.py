"""codegen — emit native code from the card IR (L33: algorithm as cards, native as output).

Nothing language-specific lives here. A target is a ``language`` card whose
``codegen`` block holds the syntax as data (types, literals, statement
templates, helper functions, test and bench harnesses); an operator is an
``op`` card whose ``emit`` block holds one template per language (or per
syntax family, e.g. ``c_like``). Adding a language = adding one card;
adding an operator = adding one card. A missing template is a precise
translation gap (``EmitGap``), never a silent fallback.

Template placeholders: {0} {1} {2} operands · {type} result type name ·
{t0} {t1} operand type names · {tc} type code (i/f/b) of the first operand.
An ``emit`` entry may be a dict keyed by the first operand's IR type.

Lowering rules shared by every non-native target:
  * locals are hoisted to the top of the function with zero values;
  * parameters that are reassigned are re-bound when the language has
    immutable parameters (``param_rebind``);
  * ``for i in range(a, b, s)`` becomes: it = a; stop = b;
    while it < stop (> for s < 0): i = it; it += s; body
    (incrementing first keeps ``continue`` correct, and ``i`` keeps
    Python's last-iterated value after the loop).

Machine state (globals, arrays, store/do/switch statements, LOAD, void
functions; see ir.py) uses more ``codegen`` templates, all optional: ``global``
/ ``global_export``, ``global_use`` (languages that must declare the globals a
function assigns), ``array`` / ``array_init`` / ``array_export`` keyed by element
type, ``load`` / ``store`` keyed by element type, ``do``, ``return_void``,
``func_export``, ``export_prefix`` and ``switch`` (head/case/body_open/body_close/
default/tail). Without a ``switch`` block a switch is lowered to a binary search
of ``if`` statements on a temporary.

Honest limits (L1): templates are only as right as the conformance matrix
that checks them; identifiers are renamed only for the language card's
``reserved`` list; emitted code is plain (no formatting pass).
"""
from __future__ import annotations

import re

from .ir import LEAVES, elem_type


class EmitGap(Exception):
    """The target cannot express something (missing template / unsupported type)."""


def resolve_language(store, name: str) -> dict:
    """The language card's codegen + runner with ``extends`` applied (deep for dicts)."""
    card = store.get(f"language/{name}")
    if card is None:
        raise EmitGap(f"no language card {name!r}")
    data = dict(card)
    base_name = data.get("extends")
    if base_name:
        base = resolve_language(store, base_name)
        for key in ("codegen", "runner", "probe", "family", "extensions"):
            if key in base and key not in data:
                data[key] = base[key]
            elif isinstance(base.get(key), dict) and isinstance(data.get(key), dict):
                merged = dict(base[key])
                for k, v in data[key].items():
                    if isinstance(v, dict) and isinstance(merged.get(k), dict):
                        mv = dict(merged[k])
                        mv.update(v)
                        merged[k] = mv
                    else:
                        merged[k] = v
                data[key] = merged
    data.setdefault("family", data.get("name"))
    return data


class Emitter:
    def __init__(self, store, lang: str, ops: dict):
        self.lang_name = lang
        self.lang = resolve_language(store, lang)
        self.cg = self.lang.get("codegen") or {}
        if not self.cg:
            raise EmitGap(f"language {lang!r} has no codegen block")
        self.family = self.lang.get("family") or lang
        self.lineage = self._lineage(store, lang)
        self.ops = ops
        self.requires: set[str] = set()
        self.loop_id = 0
        self.exports: set[str] = set()
        self.arrays: dict[str, dict] = {}
        self.global_names: set[str] = set()
        self.fn_returns: dict[str, str] = {}
        self.tmp_id = 0

    @staticmethod
    def _lineage(store, lang):
        out = [lang]
        card = store.get(f"language/{lang}")
        while card is not None and card.get("extends"):
            out.append(card["extends"])
            card = store.get(f"language/{card['extends']}")
        return out

    # -- small helpers ---------------------------------------------------------
    def T(self, ir_type: str) -> str:
        t = (self.cg.get("types") or {}).get(ir_type)
        if t is None:
            raise EmitGap(f"{self.lang_name}: no type for {ir_type!r}")
        return t

    def tmpl(self, key: str, **kw) -> str:
        t = self.cg.get(key)
        if t is None:
            raise EmitGap(f"{self.lang_name}: codegen template {key!r} missing")
        return t.format(**kw)

    def lit(self, kind: str, v) -> str:
        if elem_type(kind) is not None:
            t = (self.cg.get("list_lit") or {}).get(kind)
            if t is None:
                raise EmitGap(f"{self.lang_name}: no list literal for {kind}")
            items = [self.lit(elem_type(kind), x) for x in v]
            # raw: the bare values, comma-separated (for a target that parses a long literal from one string)
            raw = ",".join(repr(float(x)) if elem_type(kind) == "float" else str(int(x)) for x in v)
            return t.format(items=", ".join(items), items_z=", ".join([*items, self.lit(elem_type(kind), 0)]),
                            n=len(items), n_lit=self.lit("int", len(items)), raw=raw)
        lits = self.cg.get("lit") or {}
        if kind == "bool":
            return lits.get("true" if v else "false", "true" if v else "false")
        if kind == "float":
            if v != v or v in (float("inf"), float("-inf")):
                raise EmitGap(f"{self.lang_name}: non-finite float literal")
            text = repr(float(v))
            return lits.get("float", "{v}").format(v=text)
        bits = self.lang.get("int_bits")
        if bits and not -(2 ** (bits - 1)) <= int(v) < 2 ** (bits - 1):
            raise EmitGap(f"{self.lang_name}: integer constant {int(v)} does not fit {bits}-bit int")
        return lits.get("int", "{v}").format(v=int(v))

    def ident(self, name: str) -> str:
        """A safe identifier: "_" and the language card's ``reserved`` words get a suffix; exported names get the
        card's ``export_prefix`` (so a symbol never collides with the platform's own)."""
        if name in self.exports and self.cg.get("export_prefix"):
            return self.cg["export_prefix"] + name
        reserved = self.lang.get("reserved") or []
        if name == "_" and self.cg.get("underscore_ok") is not True:
            return "cm_u"
        if name in reserved or name in self.platform_names():
            return f"{name}_cm"
        if self.cg.get("lowercase_idents") and name[:1].isupper():
            return f"cm_{name}"   # e.g. Ruby: a capitalized name is a constant, not a variable
        return name

    def platform_names(self) -> set[str]:
        """Names this language's op templates call (``tanh`` in C, ``cm_powmod``...) and its helpers: a user
        function or variable with one of these names would shadow or clash with the platform's own."""
        if getattr(self, "_platform", None) is None:
            names: set[str] = set()
            keys = (*self.lineage, self.family, "default")
            for spec in self.ops.values():
                emit = (spec.card or {}).get("emit") or {}
                for tmpl in (emit.get(k) for k in keys):   # this language's templates only
                    if isinstance(tmpl, str):
                        names.update(re.findall(r"(?<![.\w:])([A-Za-z_]\w*)\s*\(", tmpl))   # free functions, not methods
            names.update(self.cg.get("helpers") or {})
            self._platform = names
        return self._platform

    def state(self, module: dict) -> None:
        """Note the module's globals, arrays and exports (machine state) before emitting its functions."""
        self.exports = {x["name"] for x in (*(module.get("globals") or []), *(module.get("arrays") or []),
                                            *module["functions"]) if x.get("export")}
        self.arrays = {a["name"]: a for a in module.get("arrays") or []}
        self.global_names = {g["name"] for g in module.get("globals") or []}
        self.global_types = {g["name"]: g.get("type", "int") for g in module.get("globals") or []}

    def state_source(self, module: dict) -> str:
        """Definitions of the module's globals and arrays."""
        out = []
        for g in module.get("globals") or []:
            key = "global_export" if g.get("export") and "global_export" in self.cg else "global"
            out.append(self.tmpl(key, name=self.ident(g["name"]), type=self.T(g.get("type", "int")),
                                 value=self.lit(g.get("type", "int"), g.get("init", 0))))
        for a in module.get("arrays") or []:
            elem = a.get("elem", "u8")
            init = a.get("init")
            key = "array_export" if a.get("export") and "array_export" in self.cg else "array"
            if init:
                key = "array_init"
            t = (self.cg.get(key) or {}).get(elem)
            if t is None:
                raise EmitGap(f"{self.lang_name}: no {key} template for {elem} arrays")
            padded = list(init or []) + [0] * (int(a["size"]) - len(init or [])) if init else []
            values = ", ".join(str(int(v) & 0xFF if elem == "u8" else int(v)) for v in padded)
            out.append(t.format(name=self.ident(a["name"]), size=int(a["size"]), values=values))
        return "".join(x if x.endswith("\n") else x + "\n" for x in out)

    def var(self, name: str) -> str:
        return self.cg.get("var", "{name}").format(name=self.ident(name))

    # -- expressions -----------------------------------------------------------
    def op_template(self, op: str, arg_types: list[str], rtype: str | None = None) -> str:
        spec = self.ops.get(op)
        emit = (spec.card.get("emit") if spec else None) or {}
        if op in ("AND", "OR", "NOT", "IF_EXPR") and not emit:
            raise EmitGap(f"op card {op} has no emit block")
        for key in (*self.lineage, self.family, "default"):
            t = emit.get(key)
            if t is None:
                continue
            if isinstance(t, dict):
                t = (rtype and t.get("->" + rtype)) or t.get(arg_types[0] if arg_types else "int") or t.get("any")
                if t is None:
                    continue
            if t == "UNSUPPORTED":
                break
            req = (spec.card.get("requires") or {}) if spec else {}
            for key2 in (*self.lineage, self.family):
                if key2 in req:
                    need = req[key2]
                    if isinstance(need, dict):  # keyed by the first operand's type
                        need = need.get(arg_types[0] if arg_types else "int", [])
                    self.requires.update(need)
                    break
            return t
        raise EmitGap(f"{self.lang_name}: op {op} on ({', '.join(arg_types)}) has no template")

    def expr(self, e, types: dict[str, str]) -> tuple[str, str]:
        head = e[0]
        if head == "var":
            if e[1] in types:
                return self.var(e[1]), types[e[1]]
            if e[1] in self.global_names:
                return self.var(e[1]), self.global_types[e[1]]
            raise EmitGap(f"unknown variable {e[1]!r}")
        if head in ("int", "float", "bool"):
            return self.lit(head, e[1]), head
        if head == "RAW":
            # ["RAW", lang, template, result_type, *args]: one language's own spelling (a hint form under test)
            if e[1] not in self.lineage:
                raise EmitGap(f"RAW {e[1]} code cannot be emitted as {self.lang_name}")
            subs = [self.expr(a, types)[0] for a in e[4:]]
            return e[2].format(*subs), e[3]
        if head == "CALL":
            args = [self.arg(*self.expr(a, types)) for a in e[2:]]
            sep = self.cg.get("call_sep", ", ")
            text = self.cg.get("call", "{name}({args})").format(name=self.ident(e[1]), args=sep.join(args))
            return text, self.fn_returns[e[1]]
        if head == "LOAD":
            spec = self.arrays.get(e[1])
            if spec is None:
                raise EmitGap(f"LOAD from unknown array {e[1]!r}")
            t = (self.cg.get("load") or {}).get(spec.get("elem", "u8"))
            if t is None:
                raise EmitGap(f"{self.lang_name}: no load template")
            idx, _ = self.expr(e[2], types)
            return t.format(arr=self.ident(e[1]), idx=idx), "int"
        subs = [self.expr(a, types) for a in e[1:]]
        arg_types = [t for _, t in subs]
        rtype = self.result_type(head, arg_types)
        tpl = self.op_template(head, arg_types, rtype)
        fields = {"type": self.T(rtype), "tc": (arg_types[0][0] if arg_types else "i")}
        for i, (code, t) in enumerate(subs):
            fields[f"t{i}"] = self.T(t)
        try:
            text = tpl.format(*[c for c, _ in subs], **fields)
        except (IndexError, KeyError) as exc:
            raise EmitGap(f"{self.lang_name}: bad template for {head}: {exc}") from exc
        return text, rtype

    def arg(self, text: str, t: str) -> str:
        """A call argument: a list passes through the card's ``list_arg`` template (Rust borrows: ``&{e}``)."""
        if elem_type(t) is not None and self.cg.get("list_arg"):
            return self.cg["list_arg"].format(e=text)
        return text

    def PT(self, ir_type: str) -> str:
        """A parameter's type: the card's ``param_types`` entry (Rust: ``&[f64]``) or the plain type."""
        return (self.cg.get("param_types") or {}).get(ir_type) or self.T(ir_type)

    def result_type(self, op: str, arg_types: list[str]) -> str:
        if op in ("AND", "OR", "NOT"):
            return "bool"
        if op == "IF_EXPR":
            return arg_types[1]
        spec = self.ops.get(op)
        rt = spec.result_type(arg_types) if spec else None
        if rt is None:
            raise EmitGap(f"op {op} has no signature for ({', '.join(arg_types)})")
        return rt

    # -- statements ------------------------------------------------------------
    def block(self, body, types, depth, loop=None) -> list[str]:
        ind = self.cg.get("indent", "    ") * depth
        out: list[str] = []
        for s in body:
            k = s["k"]
            if k == "assign":
                v, _ = self.expr(s["value"], types)
                out.append(ind + self.tmpl("assign", name=self.var(s["target"]), value=v))
            elif k == "return":
                if "value" not in s:
                    out.append(ind + self.tmpl("return_void"))
                    continue
                v, _ = self.expr(s["value"], types)
                out.append(ind + self.tmpl("return", value=v))
            elif k == "store":
                spec = self.arrays.get(s["array"])
                if spec is None:
                    raise EmitGap(f"store to unknown array {s['array']!r}")
                t = (self.cg.get("store") or {}).get(spec.get("elem", "u8"))
                if t is None:
                    raise EmitGap(f"{self.lang_name}: no store template")
                idx, _ = self.expr(s["index"], types)
                v, _ = self.expr(s["value"], types)
                out.append(ind + t.format(arr=self.ident(s["array"]), idx=idx, value=v))
            elif k == "do":
                v, _ = self.expr(s["value"], types)
                out.append(ind + self.tmpl("do", value=v))
            elif k == "set":
                lt = types.get(s["target"])
                t = self.cg.get("set")
                if isinstance(t, dict):
                    t = t.get(lt) or t.get("any")
                if t is None or elem_type(lt or "") is None:
                    raise EmitGap(f"{self.lang_name}: no set template for {lt}")
                idx, _ = self.expr(s["index"], types)
                v, _ = self.expr(s["value"], types)
                out.append(ind + t.format(name=self.var(s["target"]), idx=idx, value=v))
            elif k == "switch":
                out += self.switch(s, types, depth, loop)
            elif k == "if":
                c, _ = self.expr(s["cond"], types)
                out.append(ind + self.tmpl("if", cond=c))
                out += self.block(s["then"], types, depth + 1, loop) or [ind + self.cg.get("indent", "    ")
                                                                         + self.cg.get("empty", "").format()]
                if s.get("else"):
                    out.append(ind + self.tmpl("else"))
                    out += self.block(s["else"], types, depth + 1, loop)
                end = self.cg.get("end_if", "").format()
                if end:
                    out.append(ind + end)
            elif k == "while":
                self.loop_id += 1
                lid = self.loop_id
                c, _ = self.expr(s["cond"], types)
                out.append(ind + self.tmpl("while", cond=c))
                inner = self.block(s["body"], types, depth + 1, lid)
                out += inner or [ind + self.cg.get("indent", "    ") + self.cg.get("empty", "").format()]
                if self.cg.get("loop_end_label"):
                    out.append(ind + self.cg.get("indent", "    ") + self.cg["loop_end_label"].format(loop=lid))
                end = self.cg.get("end_while", "").format()
                if end:
                    out.append(ind + end)
            elif k == "for_range":
                out += self.for_range(s, types, depth)
            elif k == "break":
                out.append(ind + self.tmpl("break"))
            elif k == "continue":
                out.append(ind + self.tmpl("continue", loop=loop))
            else:
                raise EmitGap(f"statement {k!r}")
        return out

    def switch(self, s, types, depth, loop) -> list[str]:
        sw = self.cg.get("switch")
        for case in [*s["cases"], {"body": s.get("default") or []}]:
            if any(x["k"] == "break" for x in _shallow(case["body"])):
                raise EmitGap("`break` directly inside a switch case (it would leave the switch in some languages)")
        if not sw:
            return self.block(self.lower_switch(s, types), types, depth, loop)
        ind = self.cg.get("indent", "    ") * depth
        v, _ = self.expr(s["value"], types)
        out = [ind + sw["head"].format(value=v)]
        for case in s["cases"]:
            for m in case["match"]:
                out.append(ind + sw["case"].format(v=self.lit("int", m)))
            out.append(ind + sw["body_open"].format())
            out += self.block(case["body"], types, depth + 1, loop)
            out.append(ind + sw["body_close"].format())
        if s.get("default"):
            out.append(ind + sw["default"].format())
            out.append(ind + sw["body_open"].format())
            out += self.block(s["default"], types, depth + 1, loop)
            out.append(ind + sw["body_close"].format())
        out.append(ind + sw["tail"].format())
        return out

    def lower_switch(self, s, types) -> list:
        """A switch as a binary search of ``if`` statements on a temporary (declared on the fly)."""
        self.tmp_id += 1
        tmp = f"cm_sw{self.tmp_id}"
        types[tmp] = "int"
        self.extra_locals[tmp] = "int"
        pairs = sorted((m, i) for i, c in enumerate(s["cases"]) for m in c["match"])
        bodies = [c["body"] for c in s["cases"]]
        default = s.get("default") or []

        def tree(lo, hi):
            if lo >= hi:
                return default
            if hi - lo <= 3:
                node = default
                for m, i in reversed(pairs[lo:hi]):
                    node = [{"k": "if", "cond": ["CMP_EQ", ["var", tmp], ["int", m]], "then": bodies[i],
                             "else": node}]
                return node
            mid = (lo + hi) // 2
            return [{"k": "if", "cond": ["CMP_LT", ["var", tmp], ["int", pairs[mid][0]]], "then": tree(lo, mid),
                     "else": tree(mid, hi)}]

        return [{"k": "assign", "target": tmp, "value": s["value"]}, *tree(0, len(pairs))]

    def for_range(self, s, types, depth) -> list[str]:
        ind = self.cg.get("indent", "    ") * depth
        if self.cg.get("native_for_range"):
            self.loop_id += 1
            start, _ = self.expr(s["start"], types)
            stop, _ = self.expr(s["stop"], types)
            step, _ = self.expr(s["step"], types)
            out = [ind + self.cg["native_for_range"].format(var=self.var(s["var"]), start=start, stop=stop,
                                                            step=step)]
            out += self.block(s["body"], types, depth + 1, self.loop_id) or [
                ind + self.cg.get("indent", "    ") + self.cg.get("empty", "").format()]
            return out
        it, stop_v = s["counter"], s["stop_var"]
        neg = s["step"][1] < 0
        lowered = [
            {"k": "assign", "target": it, "value": s["start"]},
            {"k": "assign", "target": stop_v, "value": s["stop"]},
            {"k": "while", "cond": ["CMP_GT" if neg else "CMP_LT", ["var", it], ["var", stop_v]],
             "body": [{"k": "assign", "target": s["var"], "value": ["var", it]},
                      {"k": "assign", "target": it, "value": ["ADD", ["var", it], s["step"]]},
                      *s["body"]]},
        ]
        return self.block(lowered, types, depth)

    # -- functions and programs ------------------------------------------------
    def function(self, fn: dict) -> str:
        types = {p["name"]: p["type"] for p in fn["params"]}
        types.update(fn.get("locals") or {})
        ind = self.cg.get("indent", "    ")
        assigned = {s["target"] for s in _stmts(fn["body"]) if s["k"] == "assign"} | \
                   {s["var"] for s in _stmts(fn["body"]) if s["k"] == "for_range"}
        self.extra_locals: dict[str, str] = {}
        body_lines = self.block(fn["body"], types, 1)
        lines: list[str] = []
        global_assigned = sorted(n for n in assigned if n not in types and n in self.global_names)
        if global_assigned and self.cg.get("global_use"):
            lines.append(ind + self.cg["global_use"].format(names=", ".join(self.ident(n) for n in global_assigned)))
        if self.cg.get("param_rebind"):
            for p in fn["params"]:
                if p["name"] in assigned:
                    lines.append(ind + self.cg["param_rebind"].format(name=self.var(p["name"]), type=self.T(p["type"])))
        if self.cg.get("hoist", True):
            for name, t in {**(fn.get("locals") or {}), **self.extra_locals}.items():
                if self.cg.get("native_for_range") and name.startswith(("cm_it", "cm_stop")):
                    continue
                zero = (self.cg.get("zero") or {}).get(t, "0")
                lines.append(ind + self.tmpl("declare", name=self.var(name), type=self.T(t), value=zero))
        lines += body_lines
        if not body_lines and self.cg.get("empty"):
            lines.append(ind + self.cg["empty"].format())
        sep = self.cg.get("param_sep", ", ")
        params = sep.join(self.cg.get("param", "{type} {name}").format(name=self.var(p["name"]), type=self.PT(p["type"]))
                          for p in fn["params"])
        body = "\n".join(lines) + "\n"
        key = "func_export" if fn.get("export") and "func_export" in self.cg else "func"
        return self.tmpl(key, name=self.ident(fn["name"]), params=params, ret=self.T(fn["returns"]), body=body)

    def program(self, module: dict, calls: list, mode: str = "test", reps: int = 1) -> str:
        """A complete program: helpers + functions + a harness.

        ``calls`` items are argument lists for the module entry, or
        ``(function_name, args)`` pairs (one program can test many functions).
        mode "test":  print one tagged line per call (i:/f:/b:)
        mode "bench": loop ``reps`` times over the calls, print one checksum;
                      arguments pass through the language's ``opaque``
                      template so the compiler cannot constant-fold the calls."""
        self.requires = set()
        self.state(module)
        fns = {f["name"]: f for f in module["functions"]}
        self.fn_returns = {n: f["returns"] for n, f in fns.items()}
        protos = self.state_source(module) + self.prototypes(module)
        funcs = [self.function(f) for f in reversed(module["functions"])]
        entry_name = module.get("entry", module["functions"][0]["name"])
        sep = self.cg.get("call_sep", ", ")
        call_tpl = self.cg.get("harness_call", self.cg.get("call", "{name}({args})"))
        opaque = (self.cg.get("opaque") or {}) if mode == "bench" else {}
        harness = self.cg.get("harness") or {}
        ind2 = self.cg.get("indent", "    ")
        lines = []
        for item in calls:
            name, args = (item[0], item[1]) if isinstance(item, tuple) else (entry_name, item)
            fn = fns[name]
            parts = []
            for p, a in zip(fn["params"], args):
                text = self.lit(p["type"], a)
                if p["type"] in opaque:
                    text = opaque[p["type"]].format(v=text)
                parts.append(self.arg(text, p["type"]))
            text = call_tpl.format(name=self.ident(name), args=sep.join(parts))
            rt = fn["returns"]
            if mode == "test":
                pr = (harness.get("print") or {}).get(rt)
                if pr is None:
                    raise EmitGap(f"{self.lang_name}: no print template for {rt}")
                lines.append(ind2 + pr.format(e=text) + "\n")
            else:
                tr = (harness.get("truthy") or {}).get(rt)
                if tr is None or "bench_main" not in harness:
                    raise EmitGap(f"{self.lang_name}: no bench harness")
                lines.append(ind2 * 2 + harness["bench_call"].format(truthy=tr.format(e=text)) + "\n")
        if "main" not in harness:
            raise EmitGap(f"{self.lang_name}: no test harness")
        main = harness["main"].format(calls="".join(lines)) if mode == "test" else \
            harness["bench_main"].format(calls="".join(lines), reps=reps)
        code_body = protos + "\n".join(funcs) + "\n" + main
        helpers = self.helpers_for(code_body)
        return self._prelude("prelude") + helpers + code_body

    def _prelude(self, key: str) -> str:
        """Prelude text with ``@imports@`` replaced by the import lines the emitted ops require."""
        imports = "".join(self.cg.get("import", "").replace("@name@", r) for r in sorted(self.requires)) \
            if self.cg.get("import") else ""
        text = self.cg.get(key, self.cg.get("prelude", ""))
        return text.replace("@imports@", imports)

    def prototypes(self, module: dict, only: list[str] | None = None) -> str:
        """Forward declarations, for languages whose card has a ``prototype`` template (C, C++)."""
        if not self.cg.get("prototype"):
            return ""
        sep0 = self.cg.get("param_sep", ", ")
        out = []
        for f in module["functions"]:
            if only is not None and f["name"] not in only:
                continue
            key = "prototype_export" if f.get("export") and "prototype_export" in self.cg else "prototype"
            out.append(self.tmpl(key, name=self.ident(f["name"]), ret=self.T(f["returns"]), params=sep0.join(
                self.cg.get("param", "{type} {name}").format(name=self.var(p["name"]), type=self.PT(p["type"]))
                for p in f["params"])) + "\n")
        return "".join(out) + "\n"

    def module_source(self, module: dict, only: list[str] | None = None) -> str:
        """Just the functions (+ helpers), without a harness: what a translation emits.
        ``only``: emit just these functions; the others are known callees defined elsewhere."""
        self.requires = set()
        self.state(module)
        self.fn_returns = {f["name"]: f["returns"] for f in module["functions"]}
        funcs = "\n".join(self.function(f) for f in reversed(module["functions"])
                           if only is None or f["name"] in only)
        protos = self.prototypes(module, only) if len([f for f in module["functions"]
                                                        if only is None or f["name"] in only]) > 1 else ""
        state = self.state_source(module)
        helpers = self.helpers_for(state + funcs)
        return self._prelude("lib_prelude") + helpers + state + protos + funcs + self.cg.get("lib_epilogue", "")

    def split_sources(self, module: dict, groups: list[list[str]]) -> list[str]:
        """The module as several compile units: part 0 holds the state and every function not in a group, part
        k the functions of group k-1. Every symbol must be exported (so the parts link); each part declares the
        state (``global_extern`` / ``array_extern``) and the functions (``prototype_export``) it uses."""
        if not self.cg.get("global_extern") or not self.cg.get("array_extern"):
            raise EmitGap(f"{self.lang_name}: no extern templates; this language cannot split a module")
        self.requires = set()
        self.state(module)
        self.fn_returns = {f["name"]: f["returns"] for f in module["functions"]}
        grouped = {n for g in groups for n in g}
        by = {f["name"]: f for f in module["functions"]}
        externs = []
        for g in module.get("globals") or []:
            externs.append(self.cg["global_extern"].format(name=self.ident(g["name"]), type=self.T(g.get("type", "int"))))
        for a in module.get("arrays") or []:
            t = self.cg["array_extern"].get(a.get("elem", "u8"))
            if t is None:
                raise EmitGap(f"{self.lang_name}: no array_extern for {a.get('elem')}")
            externs.append(t.format(name=self.ident(a["name"]), size=int(a["size"])))
        extern_text = "".join(x + "\n" for x in externs)
        core = {"functions": [f for f in module["functions"] if f["name"] not in grouped]}
        funcs0 = "\n".join(self.function(f) for f in reversed(core["functions"]))
        state0 = self.state_source(module)
        core_called = {e[1] for f in core["functions"] for st in _stmts(f["body"])
                       for key in ("value", "cond", "index", "start", "stop") if isinstance(st.get(key), list)
                       for e in _walk(st[key]) if e[0] == "CALL"}
        protos_all = self.prototypes({"functions": [f for f in module["functions"]
                                                    if f["name"] not in grouped or f["name"] in core_called]})
        parts = []
        req0 = set(self.requires)
        parts.append((state0 + protos_all + funcs0, req0))
        for g in groups:
            self.requires = set()
            fs = [by[n] for n in g]
            body = "\n".join(self.function(f) for f in fs)
            called = {e[1] for f in fs for st in _stmts(f["body"]) for key in ("value", "cond", "index", "start", "stop")
                      if isinstance(st.get(key), list) for e in _walk(st[key]) if e[0] == "CALL"}
            protos = self.prototypes({"functions": [by[n] for n in sorted(called | set(g)) if n in by]})
            parts.append((extern_text + protos + body, set(self.requires)))
        out = []
        for code, req in parts:
            self.requires = req
            out.append(self._prelude("lib_prelude") + self.helpers_for(code) + code)
        return out

    def helpers_for(self, code: str) -> str:
        """Helper functions referenced by ``code``, dependencies first.

        Helpers are written as plain target code; ``@int@``, ``@float@`` and
        ``@bool@`` are replaced by the language's type names (no brace escaping)."""
        helpers = self.cg.get("helpers") or {}
        ordered: list[str] = []

        def uses(text: str, name: str) -> bool:
            return re.search(rf"\b{re.escape(name)}\b", text) is not None

        def visit(n: str, stack: tuple = ()) -> None:
            if n in ordered or n in stack:
                return
            for m in helpers:
                if m != n and uses(helpers[n], m):
                    visit(m, (*stack, n))
            ordered.append(n)

        for n in helpers:
            if uses(code, n):
                visit(n)
        types = self.cg.get("types") or {}
        out = []
        for n in ordered:
            text = helpers[n]
            for t in ("int", "float", "bool"):
                text = text.replace(f"@{t}@", types.get(t, t))
            out.append(text if text.endswith("\n") else text + "\n")
        return "".join(out)


def _stmts(body):
    for s in body:
        yield s
        for key in ("then", "else", "body", "default"):
            if key in s:
                yield from _stmts(s[key])
        for case in s.get("cases") or ():
            yield from _stmts(case["body"])


def _walk(e):
    if isinstance(e, list) and e:
        yield e
        if e[0] not in LEAVES:
            for a in e[(2 if e[0] in ("CALL", "LOAD") else 1):]:
                yield from _walk(a)


def _shallow(body):
    """Statements of a body, descending into if/else and nested switch cases but not into loops."""
    for s in body:
        yield s
        if s["k"] == "if":
            yield from _shallow(s.get("then") or [])
            yield from _shallow(s.get("else") or [])


def emit_module(store, ops, lang: str, module: dict, only: list[str] | None = None) -> str:
    return Emitter(store, lang, ops).module_source(module, only)


def emit_program(store, ops, lang: str, module: dict, calls: list[list], mode: str = "test", reps: int = 1) -> str:
    return Emitter(store, lang, ops).program(module, calls, mode, reps)


def carry_map(store, ops, lang: str) -> dict[str, dict[str, str | None]]:
    """The language as a carry map on the atoms (FOUNDATIONS D13, D14; docs/GODEL_TARGET.md G11): for each op of
    the signature, its template at each rank, keyed by the first operand's sort as the emit blocks are, and None
    where the language has none."""
    em = Emitter(store, lang, ops)
    out: dict[str, dict[str, str | None]] = {}
    for name, spec in ops.items():
        ranks: dict[str, str | None] = {}
        for sig in spec.types or [["int", "int"]]:
            key = sig[0] if len(sig) > 1 else "any"
            try:
                ranks[key] = em.op_template(name, list(sig[:-1]), sig[-1])   # resolved as expr() resolves it
            except EmitGap:
                ranks[key] = None
        out[name] = ranks
    return out


def language_gap(store, ops, lang: str) -> set[str]:
    """The atoms the language cannot write at any rank: the gap of its carry map. A term whose content has one of
    them cannot be emitted, and that is known from the content alone, before anything is emitted. A gap at one
    rank only (a template for int but not for float) is still found by emitting, since content is rank-blind."""
    return {f"op/{name}" for name, ranks in carry_map(store, ops, lang).items() if not any(ranks.values())}


def predicted_gap(content, gap: set[str]) -> list[str]:
    """support(γ) ∩ gap: the atoms of a content that the language has no template for, sorted."""
    return sorted(a for a, e in content.items() if e and a in gap)


def supported_ops(store, ops, lang: str) -> dict[str, bool]:
    """Which ops the language has a template for, at some rank (the complement of its gap)."""
    return {name: any(ranks.values()) for name, ranks in carry_map(store, ops, lang).items()}


__all__ = ["EmitGap", "Emitter", "carry_map", "emit_module", "emit_program", "language_gap", "predicted_gap",
           "resolve_language", "supported_ops", "LEAVES"]
