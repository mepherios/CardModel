"""sorts — the sorts of terms, and the sorts a law holds at (docs/FOUNDATIONS.md D1, D5, D6, rule A3).

The card IR is a many-sorted term algebra: ``int`` (ℤ), ``float`` (IEEE binary64) and ``bool``. An op card's
``ir.types`` are its ranks. A law is an equation that holds at the sorts of its variables: associativity of ADD
holds on ``int`` and fails on ``float`` ((0.1 + 0.2) + 0.3 != 0.1 + (0.2 + 0.3)). Equational reasoning is sound
(Birkhoff) only when every law is instantiated at its own sorts, so every rewriting engine asks this module two
questions: what sort is this term, and at which sorts does this law hold.

  term_sort     the sort of a term, from the op cards' ranks (``ops``: ``ir.op_table``) and the variables' sorts
  result_sort   the sort an op returns for its arguments' sorts
  law_sorts     the sort each pattern variable of a law must have, from a rule card's ``domain`` or a theorem's
                ``vars[].type``
  admits        whether a match binds every pattern variable to a term of its sort

Honest limits (L1): without an op table, the sort of an application falls back to a fixed reading (comparisons
and logic are bool; any float argument makes the result float; otherwise the arguments' common sort). Calls of
named functions (FN, CALL) have unknown sort, and a law never fires on a term of unknown sort. That is
conservative: it can miss a rewrite, but it cannot make a false one.
"""
from __future__ import annotations

SORTS = ("int", "float", "bool")
ALIASES = {"nat": "int", "Int": "int", "Nat": "int", "real": "float", "Bool": "bool"}
LOGIC = ("AND", "OR", "NOT")
FLOAT_RESULT = ("DIV", "TO_FLOAT")       # fallback only: the op cards say this when an op table is given
DEFAULT = "int"                         # an untyped variable reads as int, the IR's and the rule cards' default


def sort_name(s) -> str | None:
    s = ALIASES.get(s, s)
    return s if s in SORTS else None


def leaf_sort(term, var_sorts: dict | None = None, default: str | None = DEFAULT) -> str | None:
    head = term[0]
    if head == "var":
        return sort_name((var_sorts or {}).get(term[1], default))
    if head in ("int", "float", "bool"):
        return head
    if head == "const":
        return "float"
    return None


def result_sort(head: str, args: list, ops: dict | None = None) -> str | None:
    """The sort ``head`` returns on arguments of sorts ``args`` (None: unknown or ill-sorted)."""
    if head in LOGIC:
        return "bool"
    if head == "IF_EXPR":
        return args[1] if len(args) == 3 and args[1] == args[2] else None
    if head in ("FN", "CALL") or ":" in head or any(a is None for a in args):
        return None
    spec = (ops or {}).get(head)
    if spec is not None and getattr(spec, "types", None):
        got = spec.result_type(list(args))
        if got is None and spec.promoted(list(args)):
            got = spec.result_type(spec.promoted(list(args)))
        return got
    if head.startswith("CMP_"):
        return "bool"
    if "float" in args or head in FLOAT_RESULT:
        return "float"
    return args[0] if args and all(a == args[0] for a in args) else None


def term_sort(t, var_sorts: dict | None = None, ops: dict | None = None, default: str | None = DEFAULT):
    if not isinstance(t, list) or not t:
        return None
    if t[0] in ("var", "int", "float", "bool", "const"):
        return leaf_sort(t, var_sorts, default)
    start = 2 if t[0] in ("FN", "CALL") else 1
    return result_sort(t[0], [term_sort(a, var_sorts, ops, default) for a in t[start:]], ops)


def law_sorts(pvars, domain=None, types: dict | None = None) -> dict | None:
    """The sort of each pattern variable (``?a``): from ``types`` (name -> type, a theorem's vars) or else one
    ``domain`` for all (a rule card's). None when the law states no sort: it claims to hold at every sort."""
    if not types and sort_name(domain) is None:
        return None
    # a variable whose sort is not one of SORTS keeps None, and admits() then never lets the law fire on it
    return {v: sort_name((types or {}).get(v[1:] if v.startswith("?") else v, domain)) for v in pvars}


def admits(sorts: dict | None, binding: dict, sort_of) -> bool:
    """Every pattern variable is bound to something of its sort (``sort_of`` maps a bound value to its sort)."""
    if not sorts:
        return True
    return all(v not in binding or (s is not None and sort_of(binding[v]) == s) for v, s in sorts.items())


__all__ = ["SORTS", "admits", "law_sorts", "leaf_sort", "result_sort", "sort_name", "term_sort"]
