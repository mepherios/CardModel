"""observe — read a source tree and express what it does as cards (the hub's card_catalog walker, card-driven).

Python files are walked with ``ast``. Every node that computes fires one
card, chosen from the store, most specific first:
  fused patterns  op cards with match.python.pattern (SQUARE = x*x, MULADD, CONST_MUL_POW2, ...)
  operators       op cards with match.python.binop / unaryop / cmpop / boolop
  calls           op and call cards with match.python.call (exact dotted name, then ".tail")
  shapes          shape cards (SUBSCRIPT_INT, SLICE_REVERSE, COMPREHENSION_LIST, LAMBDA_PREDICATE, ...)
  fallbacks       CALL_GENERIC, ATTR, SUBSCRIPT, SLICE, LAMBDA_EVAL (counted as unnamed)
Each top-level function is also offered to the IR frontend; the result
(liftable, or the exact unsupported constructs) is part of the observation.

Other languages (by the extensions on language cards) get a token-level
scan: comments and strings are stripped with the card's comment syntax,
``name(`` call sites are counted, and names found in the vendored Pheros
std_library harvest for that language count as named stdlib calls.

The observation is ground truth (Pheros L102): it is written once per
content hash and never edited by rules. Paths are stored relative to the
observed root (L50: no user paths in cards).

Honest limits (L1): static only (no runtime types); non-Python languages
are token-level estimates, not parses; aliases (``from m import f as g``)
are not resolved.
"""
from __future__ import annotations

import ast
import hashlib
import os
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from .context import Ctx
from .exprs import ParseError, _conv
from .frontend_python import lift_source
from .search import match as pmatch

SKIP_DIRS = {".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv", "env", ".tox", "build", "dist",
             ".cardmodel", ".mypy_cache", ".pytest_cache", "target", ".idea", ".vscode", "vendor", ".lake"}
MAX_FILE_BYTES = 2_000_000
PY_FLAVOURS = {"python3": "python", "node": "javascript", "gcc": "c", "rustc": "rust"}


class Tables:
    """Lookup tables built once from the store's op, call and shape cards."""

    def __init__(self, store):
        self.binop, self.unaryop, self.cmpop, self.boolop = {}, {}, {}, {}
        self.calls: dict[str, str] = {}
        self.call_arity: dict[tuple[str, int], str] = {}
        self.patterns: list[tuple[str, list, dict]] = []
        self.shapes: dict[tuple[str, str], str] = {}
        self.fallback: set[str] = set()
        self.costs: dict[str, float] = {}
        self.lang_calls: dict[str, dict[str, str]] = defaultdict(dict)
        for reg in ("op", "call", "shape"):
            for card in store.cards(reg):
                self.costs[card.name] = float(card.get("cost") or 1.0) if isinstance(card.get("cost"), (int, float)) else 1.0
                for lang_name, lm in (card.get("match") or {}).items():
                    if lang_name != "python" and isinstance(lm, dict):
                        for k in lm.get("call", []):
                            self.lang_calls[lang_name].setdefault(k, card.name)
                m = ((card.get("match") or {}).get("python")) or {}
                for k in m.get("binop", []):
                    self.binop.setdefault(k, card.name)
                for k in m.get("unaryop", []):
                    self.unaryop.setdefault(k, card.name)
                for k in m.get("cmpop", []):
                    self.cmpop.setdefault(k, card.name)
                for k in m.get("boolop", []):
                    self.boolop.setdefault(k, card.name)
                for k in m.get("call", []):
                    if "/" in k:
                        n, _, ar = k.partition("/")
                        self.call_arity[(n, int(ar))] = card.name
                    else:
                        self.calls.setdefault(k, card.name)
                if "pattern" in m:
                    self.patterns.append((card.name, m["pattern"], m.get("where", {})))
                for p in m.get("pattern_any", []):
                    self.patterns.append((card.name, p, m.get("where", {})))
                for kind in ("node", "subscript", "slice", "lambda"):
                    for k in m.get(kind, []):
                        self.shapes[(kind, k)] = card.name
                if card.get("fallback"):
                    self.fallback.add(card.name)
        # fused patterns first: longer patterns are more specific
        self.patterns.sort(key=lambda p: -len(repr(p[1])))
        self.fallback |= {"CALL_GENERIC", "ATTR", "SUBSCRIPT", "SLICE", "LAMBDA_EVAL"}


_PREDICATES = {"?pow2": lambda v: isinstance(v, int) and v > 1 and v & (v - 1) == 0,
               "?n": lambda v: isinstance(v, int) and 0 <= v <= 16}


def _fused(t: Tables, node: ast.BinOp) -> str | None:
    try:
        tree = _conv(node, set())
    except ParseError:
        return None
    for name, pattern, _where in t.patterns:
        b = pmatch(pattern, tree)
        if b is None:
            continue
        if all(_PREDICATES[k](v) for k, v in b.items() if k in _PREDICATES):
            return name
    return None


def _dotted(node) -> str | None:
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


def walk_python(t: Tables, source: str) -> dict:
    tree = ast.parse(source)
    fired: Counter = Counter()
    fallback_calls: Counter = Counter()
    for node in ast.walk(tree):
        if isinstance(node, ast.BinOp):
            name = _fused(t, node) or t.binop.get(type(node.op).__name__)
            if name:
                fired[name] += 1
        elif isinstance(node, ast.UnaryOp):
            name = t.unaryop.get(type(node.op).__name__)
            if name:
                fired[name] += 1
        elif isinstance(node, ast.Compare):
            for op in node.ops:
                name = t.cmpop.get(type(op).__name__)
                if name:
                    fired[name] += 1
        elif isinstance(node, ast.BoolOp):
            name = t.boolop.get(type(node.op).__name__)
            if name:
                fired[name] += max(1, len(node.values) - 1)
        elif isinstance(node, ast.IfExp):
            fired[t.shapes.get(("node", "IfExp"), "IF_EXPR")] += 1
        elif isinstance(node, ast.Call):
            dotted = _dotted(node.func)
            name = None
            if dotted:
                name = t.call_arity.get((dotted, len(node.args))) or t.calls.get(dotted) or \
                    t.calls.get("." + dotted.split(".")[-1])
            if name:
                fired[name] += 1
            else:
                fired["CALL_GENERIC"] += 1
                fallback_calls[dotted or "<expression>"] += 1
        elif isinstance(node, ast.Subscript):
            idx = node.slice
            kind = ("slice" if isinstance(idx, ast.Slice) else
                    "int" if isinstance(idx, ast.Constant) and isinstance(idx.value, int) else
                    "str" if isinstance(idx, ast.Constant) and isinstance(idx.value, str) else
                    "name" if isinstance(idx, ast.Name) else "tuple" if isinstance(idx, ast.Tuple) else None)
            fired[t.shapes.get(("subscript", kind), "SUBSCRIPT")] += 1
        elif isinstance(node, ast.Attribute):
            fired["ATTR"] += 1
        elif isinstance(node, ast.Slice):
            step = node.step
            kind = ("reverse" if isinstance(step, ast.UnaryOp) and isinstance(step.operand, ast.Constant)
                    and step.operand.value == 1 else "step" if step is not None else
                    "prefix" if node.lower is None and node.upper is not None else
                    "suffix" if node.upper is None and node.lower is not None else None)
            fired[t.shapes.get(("slice", kind), "SLICE")] += 1
        elif isinstance(node, (ast.ListComp, ast.DictComp, ast.SetComp, ast.GeneratorExp, ast.Lambda)):
            kind = type(node).__name__
            if kind == "Lambda":
                body, args = node.body, node.args.args
                lk = ("identity" if len(args) == 1 and isinstance(body, ast.Name) and body.id == args[0].arg else
                      "predicate" if isinstance(body, ast.Compare) else
                      "projection" if isinstance(body, (ast.Attribute, ast.Subscript)) else
                      "arithmetic" if isinstance(body, ast.BinOp) else None)
                fired[t.shapes.get(("lambda", lk), "LAMBDA_EVAL")] += 1
            else:
                fired[t.shapes.get(("node", kind), kind.upper())] += 1
    return {"fired": fired, "fallback_calls": fallback_calls}


def stdlib_index(store) -> dict[str, set[str]]:
    """language -> stdlib function names, from the vendored Pheros std_library harvest."""
    idx: dict[str, set[str]] = defaultdict(set)
    view = store.registry("computation")
    if view is None:
        return idx
    for c in view.ALL.values():
        lang = c.get("language")
        fn = c.get("function_name")
        if lang and fn:
            idx[PY_FLAVOURS.get(lang, lang)].add(fn)
    return idx


def strip_comments(text: str, comments: dict) -> str:
    out = text
    for start, end in comments.get("block", []):
        out = re.sub(re.escape(start) + r".*?" + re.escape(end), " ", out, flags=re.S)
    for q in sorted(comments.get("strings", []), key=len, reverse=True):
        eq = re.escape(q)
        out = re.sub(eq + r"(?:\\.|(?!" + eq + r").)*" + eq, '""', out, flags=re.S if len(q) == 3 else 0)
    for lc in comments.get("line", []):
        out = re.sub(re.escape(lc) + r"[^\n]*", " ", out)
    return out


_CALL_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*(?:\s*(?:\.|::|->)\s*[A-Za-z_][A-Za-z0-9_]*)*)\s*\(")
_KEYWORDS = {"if", "for", "while", "switch", "return", "sizeof", "catch", "function", "fn", "func", "def", "elif",
             "match", "when", "until", "unless", "foreach", "and", "or", "not", "typeof", "new", "async",
             "await", "super", "this", "catch", "with", "elsif", "assert", "delete", "void", "in", "of"}


def walk_tokens(text: str, lang: dict, stdlib: set[str], cards: dict[str, str] | None = None) -> dict:
    clean = strip_comments(text, lang.get("comments") or {})
    fired: Counter = Counter()
    fallback: Counter = Counter()
    cards = cards or {}
    for m in _CALL_RE.finditer(clean):
        full = re.sub(r"\s+", "", m.group(1))
        tail = re.split(r"\.|::|->", full)[-1]
        if tail in _KEYWORDS:
            continue
        card = cards.get(full) or cards.get("." + tail)
        if card:
            fired[card] += 1
        elif tail in stdlib or full in stdlib:
            fired[f"STDLIB:{tail}"] += 1
        else:
            fired["CALL_GENERIC"] += 1
            fallback[full] += 1
    return {"fired": fired, "fallback_calls": fallback}


def language_by_extension(store) -> dict[str, dict]:
    out = {}
    for card in store.cards("language"):
        for ext in card.get("extensions") or []:
            out.setdefault(ext.lower(), dict(card))
    return out


def iter_files(root: Path):
    if root.is_file():
        yield root
        return
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.startswith("."))
        for fn in sorted(filenames):
            p = Path(dirpath) / fn
            try:
                if p.stat().st_size <= MAX_FILE_BYTES:
                    yield p
            except OSError:
                continue


def observe(ctx: Ctx, root: str | os.PathLike, lift: bool = True) -> dict:
    root = Path(root).resolve()
    if not root.exists():
        raise FileNotFoundError(f"nothing to observe at {root}")
    t = Tables(ctx.store)
    by_ext = language_by_extension(ctx.store)
    stdlib = stdlib_index(ctx.store)
    files, totals, fallbacks = [], Counter(), Counter()
    fallback_files: dict[str, set] = defaultdict(set)
    fallback_by_lang: dict[str, Counter] = defaultdict(Counter)
    functions = []
    digest = hashlib.sha256()
    base = root if root.is_dir() else root.parent
    for p in iter_files(root):
        lang = by_ext.get(p.suffix.lower())
        if lang is None:
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        relp = str(p.relative_to(base))
        digest.update(relp.encode() + b"\0" + hashlib.sha256(text.encode()).digest())
        entry = {"path": relp, "language": lang["name"], "sha256_12": hashlib.sha256(text.encode()).hexdigest()[:12],
                 "lines": text.count("\n") + 1}
        try:
            if lang["name"] == "python":
                res = walk_python(t, text)
                if lift:
                    for lf in lift_source(text, ctx.ops):
                        functions.append({"file": relp, "name": lf.name, "line": lf.lineno, "liftable": lf.ok,
                                          "partial": lf.partial, "reasons": lf.reasons[:3],
                                          "inferred_types": lf.inferred_types})
            else:
                res = walk_tokens(text, lang, stdlib.get(lang["name"], set()), t.lang_calls.get(lang["name"]))
                entry["method"] = "token-level"
        except SyntaxError as exc:
            entry["error"] = f"SyntaxError line {exc.lineno}: {exc.msg}"
            files.append(entry)
            continue
        fired = res["fired"]
        named = sum(n for k, n in fired.items() if k not in t.fallback)
        entry.update(cards=sum(fired.values()), named=named, top=dict(fired.most_common(8)))
        totals.update(fired)
        fallbacks.update(res["fallback_calls"])
        fallback_by_lang[lang["name"]].update(res["fallback_calls"])
        for k in res["fallback_calls"]:
            fallback_files[k].add(relp)
        files.append(entry)
    all_fired = sum(totals.values())
    named_all = sum(n for k, n in totals.items() if k not in t.fallback)
    shape_names = {c.name for c in ctx.store.cards("shape")}
    op_like = sum(n for k, n in totals.items()
                  if k not in t.fallback and (k.startswith("STDLIB:") or (k in t.costs and k not in shape_names)))
    by_lang = Counter(f["language"] for f in files)
    obs = {
        "name": f"obs_{digest.hexdigest()[:16]}", "category": "observation", "tier": 3,
        "root": root.name, "observed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "files": files,
        "totals": {"files": len(files), "by_language": dict(by_lang), "cards_fired": all_fired,
                   "named": named_all, "named_fraction": round(named_all / all_fired, 4) if all_fired else 0.0,
                   "named_calls_and_ops": op_like,
                   "functions": len(functions), "functions_liftable": sum(f["liftable"] for f in functions),
                   "functions_partial": sum(f.get("partial", False) for f in functions)},
        "top_cards": dict(totals.most_common(25)),
        "top_fallback_calls": dict(fallbacks.most_common(40)),
        "fallback_calls_by_language": {lg: dict(c.most_common(200)) for lg, c in fallback_by_lang.items()},
        "functions": functions,
        "fallback_call_files": {k: sorted(fallback_files[k])[:50]
                                for c in fallback_by_lang.values() for k, _ in c.most_common(200)},
        "provenance": {"tool": "cardmodel observe", "method": "ast (python) + token-level (others)"},
    }
    return obs
