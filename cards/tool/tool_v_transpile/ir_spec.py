"""ir.py — minimal language-agnostic IR for v_transpile any->all.

Shape (JSON-serialisable dicts):

    Module = {
      "functions": [Function],
      "classes":   [Class],
      "imports":   [str],
      "constants": [{"name": str, "value": str, "type": str}],
    }

    Function = {
      "name": str,
      "params": [{"name": str, "type": str}],
      "return_type": str,
      "body": [Stmt],
      "is_async": bool,
      "decorators": [str],
      "is_generator": bool,
    }

    Class = {
      "name": str,
      "bases": [str],
      "fields": [{"name": str, "type": str, "value": str}],
      "methods": [Function],
      "decorators": [str],
    }

    Stmt is one of:
      {"kind": "assign",   "target": str, "value": str, "type": str}
      {"kind": "return",   "value": str}
      {"kind": "if",       "cond": str, "then": [Stmt], "else": [Stmt]}
      {"kind": "while",    "cond": str, "body": [Stmt]}
      {"kind": "for",      "var": str, "iter": str, "body": [Stmt]}
      {"kind": "call",     "value": str}
      {"kind": "expr",     "value": str}
      {"kind": "raw",      "language": str, "code": str}
      {"kind": "try",      "body": [Stmt], "handlers": [Handler], "else": [Stmt], "finally": [Stmt]}
      {"kind": "with",     "items": [{"context": str, "var": str}], "body": [Stmt]}
      {"kind": "raise",    "value": str}
      {"kind": "yield",    "value": str, "is_from": bool}
      {"kind": "await",    "value": str}
      {"kind": "break"}
      {"kind": "continue"}
      {"kind": "pass"}
      {"kind": "walrus",   "target": str, "value": str}
      # expression-level lifted: comprehensions and lambdas appear as
      # opaque-but-parsed values inside other Stmt.value strings; we
      # also expose a `comprehension` node so backends can lower them.
      {"kind": "comprehension", "ctype": "list"|"set"|"dict"|"gen",
       "target": str, "source": str, "condition": str, "elt": str,
       "key": str, "value": str}

    Handler = {"exc_type": str, "name": str, "body": [Stmt]}

Anything we cannot normalise becomes a `raw` node; emitters surface it
verbatim with a "# unsupported construct, pasted verbatim" comment.
"""
from __future__ import annotations
import json


# ---------------------------------------------------------------------------
# Module / function / class builders
# ---------------------------------------------------------------------------

def empty_module() -> dict:
    return {"functions": [], "classes": [], "imports": [], "constants": [],
            "traits": [], "generics": []}


def func(name, params=None, return_type="", body=None,
         is_async=False, decorators=None, is_generator=False):
    return {
        "name": name,
        "params": list(params or []),
        "return_type": return_type or "",
        "body": list(body or []),
        "is_async": bool(is_async),
        "decorators": list(decorators or []),
        "is_generator": bool(is_generator),
    }


def cls(name, bases=None, fields=None, methods=None, decorators=None):
    return {
        "name": name,
        "bases": list(bases or []),
        "fields": list(fields or []),
        "methods": list(methods or []),
        "decorators": list(decorators or []),
    }


def param(name, type_=""):
    return {"name": name, "type": type_ or ""}


# ---------------------------------------------------------------------------
# Statement builders
# ---------------------------------------------------------------------------

def s_assign(target, value, type_=""):
    return {"kind": "assign", "target": target, "value": value, "type": type_ or ""}


def s_return(value=""):
    return {"kind": "return", "value": value}


def s_if(cond, then=None, else_=None):
    return {"kind": "if", "cond": cond, "then": list(then or []), "else": list(else_ or [])}


def s_while(cond, body=None):
    return {"kind": "while", "cond": cond, "body": list(body or [])}


def s_for(var, iter_, body=None):
    return {"kind": "for", "var": var, "iter": iter_, "body": list(body or [])}


def s_call(value):
    return {"kind": "call", "value": value}


def s_expr(value):
    return {"kind": "expr", "value": value}


def s_raw(language, code):
    return {"kind": "raw", "language": language, "code": code}


def s_try(body=None, handlers=None, else_=None, finally_=None):
    return {
        "kind": "try",
        "body": list(body or []),
        "handlers": list(handlers or []),
        "else": list(else_ or []),
        "finally": list(finally_ or []),
    }


def s_handler(exc_type="", name="", body=None):
    return {"exc_type": exc_type or "", "name": name or "", "body": list(body or [])}


def s_with(items, body=None):
    """items is a list of {"context": <expr>, "var": <name or "">}."""
    return {"kind": "with", "items": list(items or []), "body": list(body or [])}


def s_raise(value=""):
    return {"kind": "raise", "value": value}


def s_yield(value="", is_from=False):
    return {"kind": "yield", "value": value, "is_from": bool(is_from)}


def s_await(value=""):
    return {"kind": "await", "value": value}


def s_break():
    return {"kind": "break"}


def s_continue():
    return {"kind": "continue"}


def s_pass():
    return {"kind": "pass"}


def s_walrus(target, value):
    return {"kind": "walrus", "target": target, "value": value}


def s_comprehension(ctype, target, source, condition="", elt="", key="", value=""):
    return {
        "kind": "comprehension",
        "ctype": ctype,
        "target": target,
        "source": source,
        "condition": condition or "",
        "elt": elt or "",
        "key": key or "",
        "value": value or "",
    }


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------

def dumps(module):
    return json.dumps(module, indent=2, sort_keys=False)


def loads(text):
    return json.loads(text)


_TYPE_ALIASES = {
    "int": "int", "int32_t": "int", "int64_t": "int", "long": "int",
    "i32": "int", "i64": "int", "isize": "int", "size_t": "int", "uint": "int",
    "u32": "int", "u64": "int",
    "float": "float", "double": "float", "f32": "float", "f64": "float",
    "char *": "str", "char*": "str", "string": "str", "String": "str",
    "&str": "str", "str": "str",
    "bool": "bool", "boolean": "bool",
    "void": "void", "unit": "void", "None": "void", "": "",
}


def canon_type(t):
    t = (t or "").strip().rstrip(",;")
    return _TYPE_ALIASES.get(t, t)


def is_well_formed(mod):
    if not isinstance(mod, dict):
        return False
    if "functions" not in mod:
        return False
    return isinstance(mod["functions"], list)


# ---------------------------------------------------------------------------
# UB5-A extensions: closures, generics, pattern match, async, traits/protocols,
# error propagation, tuples / destructuring, modules / namespacing.
# ---------------------------------------------------------------------------

def s_lambda(params, body=None, expr=""):
    """Lambda/closure literal. Either `expr` (single expression) or `body`
    (statement list) but not both. params is list of {name,type}."""
    return {
        "kind": "lambda",
        "params": list(params or []),
        "body": list(body or []),
        "expr": expr or "",
    }


def s_match(value, arms=None):
    """Pattern match / switch.  arms = list of {"pattern": str,
    "guard": str, "body": [Stmt]}.  pattern '_' or '' is the default."""
    return {"kind": "match", "value": value, "arms": list(arms or [])}


def s_match_arm(pattern, body=None, guard=""):
    return {"pattern": pattern, "guard": guard or "", "body": list(body or [])}


def s_trait(name, methods=None, bases=None, kind="trait"):
    """Trait / interface / protocol / abstract class.  `kind` is one of
    'trait' | 'interface' | 'protocol' | 'abstract'."""
    return {
        "kind": "trait",
        "name": name,
        "trait_kind": kind,
        "bases": list(bases or []),
        "methods": list(methods or []),
    }


def s_destructure(targets, value, type_=""):
    """Tuple / array destructuring assignment.  `targets` is a list of
    names; `value` is the source expression."""
    return {
        "kind": "destructure",
        "targets": list(targets or []),
        "value": value,
        "type": type_ or "",
    }


def s_tuple(elements):
    """Tuple literal — emitted as expression, but exposed as a node so
    backends can lower it to language-native multi-value returns."""
    return {"kind": "tuple", "elements": list(elements or [])}


def s_try_propagate(value, error_var=""):
    """Rust `expr?` / Swift `try expr` / JS-Promise `await expr`-style
    propagation.  Lowers to a try-block with re-raise in backends that
    lack the sugar."""
    return {
        "kind": "try_propagate",
        "value": value,
        "error_var": error_var or "",
    }


def trait(name, methods=None, bases=None, kind="trait"):
    """Module-level trait/interface/protocol — added to mod['traits']."""
    return {
        "name": name,
        "trait_kind": kind,
        "bases": list(bases or []),
        "methods": list(methods or []),
    }


# Extend empty_module with the new collections (back-compat: callers
# that read missing keys via .get(...) still work).
def empty_module_v2() -> dict:
    return {
        "functions": [],
        "classes":   [],
        "imports":   [],
        "constants": [],
        "traits":    [],
        "generics":  [],
    }


# ---------------------------------------------------------------------------
# T1 extensions: Erlang/Elixir actor model + Haskell IO effect + OCaml refs.
# ---------------------------------------------------------------------------

def s_spawn(target, args=None):
    """`spawn(F)` / `Process.spawn(fn)` — fork a process running `target`.
    `target` is a function-reference expression; `args` is a list of expr
    strings (may be empty)."""
    return {
        "kind": "spawn",
        "target": target,
        "args": list(args or []),
    }


def s_send(pid, message):
    """Actor send: `Pid ! Msg` (Erlang) / `send(pid, msg)` (Elixir)."""
    return {"kind": "send", "pid": pid, "message": message}


def s_receive(arms=None, after=""):
    """Actor receive: list of pattern arms (like match_arm), with an
    optional `after` timeout-expression (Erlang's `after T -> ...`).
    `arms` are reused match_arm dicts."""
    return {
        "kind": "receive",
        "arms": list(arms or []),
        "after": after or "",
    }


def s_effect(effect_kind, value):
    """Generic monadic effect — `IO`, `ST`, `Either`, etc.  Used for
    Haskell IO-monad lifting.  `effect_kind` is e.g. 'IO'."""
    return {
        "kind": "effect",
        "effect_kind": effect_kind,
        "value": value,
    }


def s_mut(target, op, value=""):
    """Mutable reference op.  `op` is one of 'ref' | 'deref' | 'set'.
    `ref x`  -> `target = ref(x)` style;
    `deref` -> read of `!target` in OCaml;
    `set`    -> `target := value` in OCaml."""
    return {
        "kind": "mut",
        "target": target,
        "op": op,
        "value": value or "",
    }
