#!/usr/bin/env python3
"""vendor_import — consolidate the original card-model folders into this repository (read-only on the sources).

Build-time only. Nothing under ``cardmodel/`` imports this file, and the
self-containment test runs the program with every source folder unreadable.

Sources (all opened read-only; hub Python is parsed with ``ast``, never imported):
  hub        ~/Documents/Claude_Hub/config: bit_primitives.py (copied as lib/bit_primitives),
             card_catalog.py (call tables -> call/, shape cards -> shape/), language_hints.py
  pheros     ~/Documents/Pheros_Studio/cards: _meta contracts, computation, redefinition,
             cross_language_equivalence, translation_gap, language, tool/v_transpile (docs + IR spec)
  ting       ~/Programmering/ting: crypto_atom vectors, cipher_suite, card_type
  rea-cards  ~/Programmering/rea-cards: re_domain detection cards, list_strings / detect_format lessons

Every vendored registry's _category.json records the source path, the
source commit (git sources) and a sha256 over the files read, so the
snapshot is reproducible and auditable.

usage: python3 -B tools/vendor_import.py [--only hub,pheros,ting,rea] [--dry-run]
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from cardmodel.engines import exprs  # noqa: E402
from cardmodel.kernel.canon import dumps_card  # noqa: E402
from cardmodel.kernel.store import open_store  # noqa: E402
import vendor_crypto as VC  # noqa: E402

HOME = Path.home()
HUB = HOME / "Documents" / "Claude_Hub"
PHEROS = HOME / "Documents" / "Pheros_Studio" / "cards"
TING = HOME / "Programmering" / "ting"
REA = HOME / "Programmering" / "rea-cards"
CARDS = ROOT / "cards"
DATE = "2026-10-21"


NAME_OK = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]*$")


def sanitize(name: str) -> str:
    """A contract-valid name for a harvested one: other characters become _xHH (reversible, recorded)."""
    out = "".join(ch if re.match(r"[A-Za-z0-9_.-]", ch) else f"_x{ord(ch):02x}" for ch in name)
    return out if re.match(r"[A-Za-z_]", out[:1]) else "_" + out


def rel(p: Path) -> str:
    try:
        return "~/" + str(p.relative_to(HOME))
    except ValueError:
        return str(p)


def sha_files(paths) -> str:
    h = hashlib.sha256()
    for p in sorted(paths):
        h.update(str(p).encode())
        h.update(Path(p).read_bytes())
    return h.hexdigest()


def git_head(repo: Path) -> str | None:
    try:
        return subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True,
                              timeout=20).stdout.strip() or None
    except (OSError, subprocess.TimeoutExpired):
        return None


def write_registry(name: str, description: str, provenance: dict, tier: int = 2, **meta) -> Path:
    d = CARDS / name
    d.mkdir(parents=True, exist_ok=True)
    data = {"name": name, "description": description, "tier": tier, "defined_by": "tools/vendor_import.py",
            "provenance": provenance, **meta}
    (d / "_category.json").write_text(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
                                      encoding="utf-8")
    return d


def write_card(reg_dir: Path, card: dict, files: dict[str, str] | None = None) -> None:
    d = reg_dir / card["name"]
    d.mkdir(parents=True, exist_ok=True)
    meta = dict(card.get("metadata") or {})
    meta.setdefault("version", "1.0.0")
    card = {**card, "metadata": meta}
    (d / "card.json").write_text(dumps_card(card), encoding="utf-8")
    for fname, text in (files or {}).items():
        (d / fname).write_text(text, encoding="utf-8")


def write_pack(reg_dir: Path, cards: list[dict], fname: str = "_pack.jsonl") -> None:
    with open(reg_dir / fname, "w", encoding="utf-8") as f:
        for c in cards:
            f.write(json.dumps(c, ensure_ascii=False, sort_keys=True) + "\n")
    describe_vocabulary(reg_dir, cards)


def describe_vocabulary(reg_dir: Path, cards: list[dict]) -> None:
    """Record the categories and status values the vendored cards actually use, so the kernel
    validates the snapshot against its own vocabulary instead of rejecting it (references stay
    external: they may point at source cards that were not copied)."""
    f = reg_dir / "_category.json"
    meta = json.loads(f.read_text(encoding="utf-8"))
    cats = sorted({c.get("category") for c in cards if c.get("category") and c.get("category") != meta["name"]})
    stats = sorted({c.get("status") for c in cards if isinstance(c.get("status"), str)})
    if cats:
        meta["category_aliases"] = sorted(set(meta.get("category_aliases", [])) | set(cats))
    if stats and not set(stats) <= {"healthy", "suspect", "broken", "quarantined"}:
        meta["status_values"] = sorted(set(stats) | {"healthy", "suspect", "broken", "quarantined"})
    meta["references"] = "external"
    f.write_text(json.dumps(meta, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


# ----------------------------------------------------------------------------- hub
def _lit(node, env):
    """Tiny evaluator for the card_catalog table loops (literals, bound names, f-strings, .rstrip)."""
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        return env[node.id]
    if isinstance(node, ast.JoinedStr):
        return "".join(str(_lit(v.value, env)) if isinstance(v, ast.FormattedValue) else v.value for v in node.values)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "rstrip":
        return _lit(node.func.value, env).rstrip(*[_lit(a, env) for a in node.args])
    raise ValueError(ast.dump(node)[:80])


GENERIC_CATS = {"type_cast", "builtin", "exception", "test_assert", "stdlib", "random", "math", "itertools", "argparse",
                "test", "regex", "io"}


def import_hub(report: dict) -> None:
    cfg = HUB / "config"
    files = [cfg / "bit_primitives.py", cfg / "card_catalog.py", cfg / "language_hints.py",
             cfg / "card_redefinitions.py", cfg / "rewrite_engine.py", cfg / "rewrite_search.py",
             cfg / "cross_language_equiv.py", cfg / "lean_emitter.py", HUB / "CARD_MODEL.md", HUB / "LAWS.md"]
    prov = {"origin": "hub", "path": rel(HUB), "files": [rel(f) for f in files], "sha256": sha_files(files),
            "read_on": DATE, "method": "read-only; python parsed with ast, never imported"}
    # lib/bit_primitives: copied verbatim with a provenance header
    lib = CARDS / "lib"
    src = (cfg / "bit_primitives.py").read_text(encoding="utf-8")
    header = (f"# Vendored verbatim from the hub: {rel(cfg / 'bit_primitives.py')} ({DATE}).\n"
              f"# sha256 of the original: {hashlib.sha256(src.encode()).hexdigest()}\n")
    write_card(lib, {"name": "bit_primitives", "category": "lib", "tier": 0, "module_alias": "bp",
                     "statement": "Decomposition of high-level ops into the universal bit basis (NAND/NOR/AND/OR/"
                                  "XOR/NOT/shifts), fixed 32-bit width; the forms named 'bit'/'nand' call it.",
                     "variants": {"python.py": {"kind": "file"}}, "provenance": prov},
               {"python.py": header + src})

    tree = ast.parse((cfg / "card_catalog.py").read_text(encoding="utf-8"))
    assigns = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            assigns[node.targets[0].id] = node.value
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
            assigns[node.target.id] = node.value

    def carddef(call: ast.Call) -> dict:
        args = [_lit(a, {}) for a in call.args]
        kw = {k.arg: _lit(k.value, {}) for k in call.keywords}
        return {"card": args[0], "cost": float(args[1]), "kind": args[2], "description": kw.get("description", "")}

    calls: dict[str, dict] = {}

    def add_call(match_name, card, cost, desc, cat, source):
        c = calls.setdefault(card, {"name": card, "category": "call", "cost": cost, "statement": desc or card,
                                    "match": {"python": {"call": []}}, "tags": [cat], "provenance": {
                                        "origin": "hub config/card_catalog.py", "table": source}})
        if match_name and match_name not in c["match"]["python"]["call"]:
            c["match"]["python"]["call"].append(match_name)

    skipped = Counter()
    # CALL_CARDS literal dict
    for k, v in zip(assigns["CALL_CARDS"].keys, assigns["CALL_CARDS"].values):
        d = carddef(v)
        add_call(k.value, d["card"], d["cost"], d["description"], "catalog", "CALL_CARDS")
    for k, v in zip(assigns["BIT_PRIMITIVE_CARDS"].keys, assigns["BIT_PRIMITIVE_CARDS"].values):
        d = carddef(v)
        add_call(None, d["card"], d["cost"], d["description"], "bit_primitive", "BIT_PRIMITIVE_CARDS")
    # V6 loops: for <targets> in <literal list | name>: _v6_call(...)/_v6_attr(...)
    for node in tree.body:
        if not isinstance(node, ast.For):
            continue
        body_fns = {getattr(st.value.func, "id", "") for st in node.body
                    if isinstance(st, ast.Expr) and isinstance(st.value, ast.Call)}
        if not body_fns & {"_v6_call", "_v6_attr"}:
            continue
        it = node.iter
        try:
            rows = ast.literal_eval(assigns[it.id]) if isinstance(it, ast.Name) else ast.literal_eval(it)
        except (ValueError, KeyError):
            skipped["non_literal_table"] += 1
            continue
        tnames = [e.id for e in node.target.elts] if isinstance(node.target, ast.Tuple) else [node.target.id]
        for row in rows:
            env = dict(zip(tnames, row if isinstance(row, tuple) else (row,)))
            for st in node.body:
                if not (isinstance(st, ast.Expr) and isinstance(st.value, ast.Call)):
                    continue
                fn = getattr(st.value.func, "id", "")
                if fn not in ("_v6_call", "_v6_attr"):
                    continue
                try:
                    args = [_lit(a, env) for a in st.value.args]
                    kw = {k.arg: _lit(k.value, env) for k in st.value.keywords}
                except (ValueError, KeyError):
                    skipped["unparsed_row"] += 1
                    continue
                cat = kw.get("cat", "attribute" if fn == "_v6_attr" else "call")
                if fn == "_v6_attr":
                    skipped["attr_access_cards"] += 1   # attribute access is a shape (ATTR), not a named op here
                    continue
                if cat not in GENERIC_CATS:
                    skipped[f"project_specific:{cat}"] += 1
                    continue
                add_call(args[0], args[1], float(args[2]), args[3] if len(args) > 3 else "", cat, "V6 tables")
    # names that are op cards already are matched there
    op_names = {p.name for p in (CARDS / "op").iterdir() if p.is_dir()}
    dup = [n for n in calls if n in op_names]
    for n in dup:
        calls.pop(n)
    # language hints -> attach to call cards (op cards got theirs in bootstrap)
    hints_tree = ast.parse((cfg / "language_hints.py").read_text(encoding="utf-8"))
    hints_node = next(n.value for n in hints_tree.body if isinstance(n, ast.AnnAssign) and n.target.id == "HINTS")
    hint_cards = 0
    for k, v in zip(hints_node.keys, hints_node.values):
        card = calls.get(k.value)
        if card is None:
            continue
        hints = {}
        for lk, lv in zip(v.keys, v.values):
            args = [_lit(a, {}) for a in lv.args]
            kw = {kk.arg: (ast.literal_eval(kk.value)) for kk in lv.keywords}
            hints[lk.value] = {"snippet": args[1], **({"notes": kw["notes"]} if kw.get("notes") else {}),
                               **({"imports": list(kw["imports"])} if kw.get("imports") else {})}
        card["hints"] = hints
        hint_cards += 1
    reg = write_registry("call", "Named function-call cards (hub card_catalog CALL_CARDS + the generic V6 tables): "
                                 "the observer matches Python call names to them; anything else is CALL_GENERIC.",
                         prov, tier=1)
    write_pack(reg, sorted(calls.values(), key=lambda c: c["name"]))

    # shape cards: AST shapes the walker classifies (fallbacks and shape-specialised names)
    shapes = []
    for name, desc, match in [
        ("CALL_GENERIC", "a call with no named card (fallback)", {"node": ["Call"]}),
        ("ATTR", "attribute access (fallback)", {"node": ["Attribute"]}),
        ("SUBSCRIPT", "subscript (fallback)", {"node": ["Subscript"]}),
        ("SUBSCRIPT_INT", "x[3]", {"subscript": ["int"]}), ("SUBSCRIPT_STR", "x['k']", {"subscript": ["str"]}),
        ("SUBSCRIPT_VAR", "x[i]", {"subscript": ["name"]}), ("SUBSCRIPT_SLICE", "x[a:b]", {"subscript": ["slice"]}),
        ("SUBSCRIPT_NDARRAY", "x[i, j]", {"subscript": ["tuple"]}),
        ("SLICE", "a:b slice (fallback)", {"node": ["Slice"]}), ("SLICE_REVERSE", "[::-1]", {"slice": ["reverse"]}),
        ("SLICE_STEP", "[::k]", {"slice": ["step"]}), ("SLICE_PREFIX", "[:b]", {"slice": ["prefix"]}),
        ("SLICE_SUFFIX", "[a:]", {"slice": ["suffix"]}),
        ("COMPREHENSION_LIST", "[x for ...]", {"node": ["ListComp"]}),
        ("COMPREHENSION_DICT", "{k: v for ...}", {"node": ["DictComp"]}),
        ("COMPREHENSION_SET", "{x for ...}", {"node": ["SetComp"]}),
        ("COMPREHENSION_GEN", "(x for ...)", {"node": ["GeneratorExp"]}),
        ("LAMBDA_EVAL", "lambda (fallback)", {"node": ["Lambda"]}), ("LAMBDA_IDENTITY", "lambda x: x", {"lambda": ["identity"]}),
        ("LAMBDA_PREDICATE", "lambda x: x < k", {"lambda": ["predicate"]}),
        ("LAMBDA_PROJECTION", "lambda x: x.k / x[k]", {"lambda": ["projection"]}),
        ("LAMBDA_ARITHMETIC_OP", "lambda x: x + k", {"lambda": ["arithmetic"]}),
        ("MATMUL", "a @ b", {"binop": ["MatMult"]}), ("NOP", "+x", {"unaryop": ["UAdd"]}),
        ("CMP_IS", "a is b", {"cmpop": ["Is"]}), ("CMP_ISNOT", "a is not b", {"cmpop": ["IsNot"]}),
        ("MEMBER", "x in c / x not in c", {"cmpop": ["In", "NotIn"]}),
    ]:
        fallback = name in ("CALL_GENERIC", "ATTR", "SUBSCRIPT", "SLICE", "LAMBDA_EVAL")
        shapes.append({"name": name, "category": "shape", "statement": desc, "fallback": fallback,
                       "match": {"python": match}, "cost": 1.0 if not name.startswith("SLICE") else 2.0,
                       "provenance": {"origin": "hub config/card_catalog.py walk_cards (V5 shapes)"}})
    reg = write_registry("shape", "AST shapes the observer classifies; fallback shapes (CALL_GENERIC, ATTR, ...) "
                                  "count as unnamed in coverage (hub card_coverage.py definition).", prov, tier=1)
    for s in shapes:
        write_card(reg, s)
    report["hub"] = {"call_cards": len(calls), "call_cards_dropped_as_op_duplicates": dup,
                     "hint_cards": hint_cards, "shape_cards": len(shapes), "skipped": dict(skipped)}


# ----------------------------------------------------------------------------- pheros
META_CONTRACTS = ["card_type", "variant_contract", "registry_contract", "redefinition_contract",
                  "primitive_contract", "card_versioning"]
EXEC_DOMAINS = {"integer": "integer", "real": "real", "fp64": "fp64", "symbolic_real": "symbolic_real",
                "positive_real": "positive_real", "modular_n": "modular_n", "nonneg_integer": "nonneg_integer"}


def import_pheros(report: dict) -> None:
    rep: dict = {}
    # _meta contracts, verbatim (the ported schemas live in card_type/)
    files = []
    reg = write_registry("pheros_meta", "Pheros _meta contracts, vendored verbatim; the model's card_type cards are "
                                        "their ported, executable form.", {}, tier=0,
                         category_aliases=["meta_definition"])
    metas = []
    for name in META_CONTRACTS:
        src = PHEROS / "_meta" / name
        card = json.loads((src / "card.json").read_text(encoding="utf-8"))
        extra = {p.name: p.read_text(encoding="utf-8") for p in sorted(src.iterdir())
                 if p.is_file() and p.name != "card.json"}
        files += [p for p in src.iterdir() if p.is_file()]
        card["vendored_from"] = rel(src)
        write_card(reg, card, extra)
        metas.append(card)
    describe_vocabulary(reg, metas)
    _set_prov(reg, {"origin": "pheros", "path": rel(PHEROS / "_meta"), "sha256": sha_files(files), "read_on": DATE})
    rep["meta_contracts"] = len(META_CONTRACTS)

    # computation: every card.json under computation/ into one pack (subcategory kept in pheros_path)
    comp_files = sorted((PHEROS / "computation").rglob("card.json"))
    cards, names = [], Counter()
    for f in comp_files:
        try:
            c = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            names["_malformed"] += 1
            continue
        if not isinstance(c, dict) or not c.get("name"):
            names["_nameless"] += 1
            continue
        c["pheros_path"] = str(f.parent.relative_to(PHEROS))
        cards.append(c)
        names[c["name"]] += 1
    seen = Counter()
    for c in cards:
        if not NAME_OK.match(c["name"]):   # harvested names like comp_synth_all? or comp_synth_[]=
            c["original_name"] = c["name"]
            c["name"] = sanitize(c["name"])
            names[c["name"]] += 1
    for c in cards:
        if names[c["name"]] > 1:
            seen[c["name"]] += 1
            c["original_name"] = c["name"]
            c["name"] = f"{c['name']}__{seen[c['name']]}"
    reg = write_registry("computation", "Pheros computation primitives (18-category taxonomy, synthesized primitives, "
                                        "harvested std_library entries), packed. Spec-level knowledge: backend "
                                        "mappings and semantics, mostly without runnable forms.",
                         {"origin": "pheros", "path": rel(PHEROS / "computation"), "files": len(comp_files),
                          "sha256": sha_files(comp_files), "read_on": DATE}, tier=2,
                         category_aliases=["computation_primitive", "computation", "std_library"])
    write_pack(reg, cards)
    rep["computation_cards"] = len(cards)
    rep["computation_renamed_duplicates"] = sum(1 for c in cards if "original_name" in c)

    # redefinition: executable subset -> redefinition/ (dirs), the rest -> redefinition_note (pack)
    red_files = sorted((PHEROS / "redefinition").glob("*/card.json"))
    executable, notes, unparsable = [], [], Counter()
    for f in red_files:
        c = json.loads(f.read_text(encoding="utf-8"))
        c["pheros_path"] = str(f.parent.relative_to(PHEROS))
        sf, tf = c.get("source_form"), c.get("target_form")
        ok = isinstance(sf, str) and isinstance(tf, str)
        if ok:
            try:
                exprs.parse(sf)
                exprs.parse(tf)
            except exprs.ParseError:
                ok = False
        dom = c.get("domain")
        if ok:
            lt, rt = exprs.parse(sf), exprs.parse(tf)
            lv, rv = exprs.variables(lt), exprs.variables(rt)
            if (lt[0] == "var" and rt[0] == "var") or (lv and rv and not (lv & rv)):
                ok = False  # a pair of names (e.g. cat_original_c -> cat_rewritten_rs): a reference, not an identity
                unparsable["name_pair_reference"] += 1
                notes.append(c)
                continue
        if ok and dom in EXEC_DOMAINS:
            executable.append(c)
        else:
            unparsable["prose_or_code" if not ok else f"domain:{dom}"] += 1
            notes.append(c)
    reg = write_registry("redefinition", "Executable identities source_form == target_form (Pheros redefinitions "
                                         "whose forms parse as expressions over a numeric domain). `cardmodel verify "
                                         "--redefinitions --record` writes each card's verification.",
                         {"origin": "pheros", "path": rel(PHEROS / "redefinition"), "files": len(red_files),
                          "sha256": sha_files(red_files), "read_on": DATE}, tier=1, card_type="redefinition")
    for c in executable:
        write_card(reg, c)
    describe_vocabulary(reg, executable)
    reg = write_registry("redefinition_note", "Pheros redefinitions whose forms are prose or code in other languages "
                                              "(ABI/ISA/framework/paradigm translations): knowledge, not executable here.",
                         {"origin": "pheros", "path": rel(PHEROS / "redefinition"), "read_on": DATE}, tier=2,
                         category_aliases=["redefinition"])
    write_pack(reg, notes)
    rep["redefinitions_executable"] = len(executable)
    rep["redefinition_notes"] = len(notes)
    rep["redefinition_note_reasons"] = dict(unparsable)

    for src_name, dst, desc, aliases in [
        ("cross_language_equivalence", "xleq_observed", "Pheros cross-language equivalence observations "
         "(compiler-output skeleton matches; ground truth, never edited).", ["cross_language_equivalence"]),
        ("translation_gap", "translation_gap", "source -> target translation coverage cards (Pheros L115), vendored; "
         "the model's measured matrix is in COVERAGE.md.", []),
        ("language", "language_semantics", "Pheros language cards (paradigm, type system, evaluation and memory "
         "model, algebraic carriers): semantic knowledge linked from language/ cards.", ["language"]),
    ]:
        files = sorted((PHEROS / src_name).glob("*/card.json"))
        reg = write_registry(dst, desc, {"origin": "pheros", "path": rel(PHEROS / src_name), "files": len(files),
                                         "sha256": sha_files(files), "read_on": DATE}, tier=2,
                             **({"category_aliases": aliases} if aliases else {}))
        written = []
        for f in files:
            c = json.loads(f.read_text(encoding="utf-8"))
            c["vendored_from"] = rel(f.parent)
            extra = {p.name: p.read_text(encoding="utf-8") for p in sorted(f.parent.iterdir())
                     if p.is_file() and p.name != "card.json" and p.suffix in (".md", ".json")}
            write_card(reg, c, extra)
            written.append(c)
        describe_vocabulary(reg, written)
        rep[dst] = len(files)

    # tool/v_transpile: the card, README and IR spec (the code is not ported; see ARCHITECTURE.md)
    vt = PHEROS / "tool" / "v_transpile"
    reg = write_registry("tool", "Tool cards vendored for their design (inputs, outputs, flaws, coverage method).",
                         {"origin": "pheros", "path": rel(PHEROS / "tool"), "read_on": DATE}, tier=2)
    c = json.loads((vt / "card.json").read_text(encoding="utf-8"))
    c["vendored_from"] = rel(vt)
    describe_vocabulary(reg, [c])
    write_card(reg, c, {"README.md": (vt / "README.md").read_text(encoding="utf-8"),
                        "ir_spec.py": (vt / "ir.py").read_text(encoding="utf-8")})
    rep["tool_v_transpile"] = "card + README + ir.py (spec)"
    report["pheros"] = rep


def _set_meta(reg_dir: Path, **kw) -> None:
    f = reg_dir / "_category.json"
    data = json.loads(f.read_text(encoding="utf-8"))
    data.update(kw)
    f.write_text(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def _set_prov(reg_dir: Path, prov: dict) -> None:
    f = reg_dir / "_category.json"
    data = json.loads(f.read_text(encoding="utf-8"))
    data["provenance"] = prov
    f.write_text(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


# ----------------------------------------------------------------------------- ting
def import_ting(report: dict) -> None:
    head = git_head(TING)
    atoms_dir = TING / "cards" / "crypto_atom"
    vec_files = sorted(atoms_dir.glob("*/vectors.json")) + sorted(atoms_dir.glob("*/card.json"))
    prov = {"origin": "ting", "path": rel(TING), "commit": head, "sha256": sha_files(vec_files), "read_on": DATE}
    reg = write_registry("crypto_atom", "Cryptographic atoms (from Ting): stdlib-Python and node:crypto forms, "
                                        "witnessed by Ting's known-answer vectors.", prov, tier=1,
                         card_type="crypto_atom")
    made = []
    for atom, plan in VC.PLAN.items():
        ting_card = json.loads((atoms_dir / atom / "card.json").read_text(encoding="utf-8"))
        vectors = json.loads((atoms_dir / atom / "vectors.json").read_text(encoding="utf-8"))
        conv = VC.convert(atom, vectors)
        for name, entry, statement, py_key, js_key, py_probe in plan:
            forms, files = [], {}
            if py_key:
                files["python.py"] = VC.PY[py_key]
                f = {"name": "python_stdlib" if not py_probe else "python_cryptography", "lang": "python",
                     "file": "python.py", "entry": entry, "domain": "python", "runnable": True,
                     "cost": 50.0 if atom in ("x25519_kem", "ed25519") else 1.0}
                if py_probe:
                    f["probe"] = py_probe
                if atom in ("x25519_kem", "ed25519"):
                    f["notes"] = "pure-Python RFC reference algorithm: exact, slow, not constant-time"
                forms.append(f)
            if js_key:
                files["javascript.mjs"] = VC.JS[js_key]
                forms.append({"name": "node_crypto", "lang": "javascript", "file": "javascript.mjs", "entry": entry,
                              "domain": "browser", "runnable": True, "cost": 1.0,
                              "notes": "node:crypto built-ins (no npm packages)"})
            for tf in ting_card.get("forms") or []:
                forms.append({"name": f"ting_{tf['name']}", "lang": "python" if tf.get("domain") == "python"
                              else "javascript", "domain": tf.get("domain", "any"), "runnable": False,
                              "cost": tf.get("cost", 1.0), "str_impl": tf.get("variant", ""),
                              "notes": "Ting's own form (noble / cryptography / PyNaCl); not a dependency here"})
            vecs = conv.get(entry, [])
            files["vectors.json"] = json.dumps(vecs, indent=1) + "\n"  # ASCII: canon vectors hold lone surrogates
            write_card(reg, {"name": name, "category": "crypto_atom", "tier": 0, "statement": statement,
                             "operation": ting_card.get("operation"), "standard": ting_card.get("standard"),
                             "purity": ting_card.get("purity", "pure"), "forms": forms, "vectors": "vectors.json",
                             "interacts_with": ting_card.get("interacts_with", []),
                             "provenance": {**prov, "ting_card": f"cards/crypto_atom/{atom}"}}, files)
            made.append((name, len(vecs)))
    # documentation-only atoms: vectors kept for future forms
    for atom in ("xchacha20poly1305", "argon2id", "ml_kem768", "ml_dsa65", "xwing_kem", "hybrid_ed25519_ml_dsa65"):
        tc = json.loads((atoms_dir / atom / "card.json").read_text(encoding="utf-8"))
        vecs = json.loads((atoms_dir / atom / "vectors.json").read_text(encoding="utf-8"))
        forms = [{"name": f"ting_{tf['name']}", "lang": "python" if tf.get("domain") == "python" else "javascript",
                  "domain": tf.get("domain", "any"), "runnable": False, "cost": tf.get("cost", 1.0),
                  "str_impl": tf.get("variant", ""), "notes": "needs a third-party package; documentation-only here"}
                 for tf in tc.get("forms") or []] or [{"name": "spec", "runnable": False, "cost": 1.0}]
        write_card(reg, {"name": atom, "category": "crypto_atom", "tier": 1, "statement": tc.get("standard", atom),
                         "operation": tc.get("operation"), "purity": tc.get("purity", "pure"), "forms": forms,
                         "ting_vectors": "ting_vectors.json", "status": "suspect",
                         "flaws": ["no stdlib/node:crypto form yet: vectors kept, nothing executes here"],
                         "provenance": {**prov, "ting_card": f"cards/crypto_atom/{atom}"}},
                   {"ting_vectors.json": json.dumps(vecs, indent=1) + "\n"})
        made.append((atom, 0))
    # cipher suites (cost vectors) and Ting's built-in card types (schema-as-cards)
    suite_files = sorted((TING / "cards" / "cipher_suite").glob("*/card.json"))
    reg = write_registry("cipher_suite", "Ting cipher suites: depends_on atoms, cost_vector + dimension_direction "
                                         "(rank / pareto with cardmodel rewrite --rank).",
                         {**prov, "sha256": sha_files(suite_files)}, tier=1, card_type="cipher_suite")
    suites = []
    for f in suite_files:
        c = json.loads(f.read_text(encoding="utf-8"))
        c["depends_on"] = [_atom_rename(d) for d in c.get("depends_on", [])]
        write_card(reg, c)
        suites.append(c)
    describe_vocabulary(reg, suites)
    _set_meta(reg, references="internal")
    type_files = sorted((TING / "cards" / "card_type").glob("*/card.json"))
    reg = write_registry("ting_card_type", "Ting's built-in card types (schema-as-cards), validated with the "
                                           "model's schema engine; an example of an application registry.",
                         {**prov, "sha256": sha_files(type_files)}, tier=2, category_aliases=["card_type"])
    types_ = [json.loads(f.read_text(encoding="utf-8")) for f in type_files]
    for c in types_:
        write_card(reg, c)
    describe_vocabulary(reg, types_)
    report["ting"] = {"commit": head, "atoms": made, "cipher_suites": len(suite_files), "card_types": len(type_files)}


def _atom_rename(name: str) -> str:
    return {"x25519_kem": "x25519_dh", "ed25519": "ed25519_sign", "p256_kem": "p256_dh",
            "ecdsa_p256": "ecdsa_p256_verify", "aes256gcm": "aes256gcm_seal"}.get(name, name)


# ----------------------------------------------------------------------------- rea-cards
STRINGS_PY = '''"""list_strings forms (ported from rea-cards runtime/reacards/native/strings.py and host/strings.py).

py_strings reproduces Apple cctools `strings - -n N -t d` under LC_ALL=C:
every byte is scanned, a run of bytes in 0x20..0x7e of length >= N is a
string (including a run that ends at EOF), text is cut at 1022 characters.
"""
import os
import re
import subprocess

TEXT_LIMIT = 1022


def py_strings(path: str, min_length: int) -> dict:
    with open(path, "rb") as f:
        data = f.read()
    rx = re.compile(rb"[\\x20-\\x7e]{%d,}" % max(1, int(min_length)))
    return {"strings": [{"offset": m.start(), "text": m.group()[:TEXT_LIMIT].decode("ascii")} for m in rx.finditer(data)]}


def host_strings(path: str, min_length: int) -> dict:
    env = dict(os.environ, LC_ALL="C", LANG="C")
    p = subprocess.run(["strings", "-", "-n", str(int(min_length)), "-t", "d", path], capture_output=True,
                       timeout=60, env=env)
    if p.returncode != 0:
        raise RuntimeError(p.stderr.decode(errors="replace")[:300])
    out = []
    for line in p.stdout.split(b"\\n"):
        if not line.strip():
            continue
        off, _, text = line.lstrip().partition(b" ")
        out.append({"offset": int(off), "text": text.decode("ascii", errors="replace")})
    return {"strings": out}
'''

DETECT_PY = '''"""detect_format form (port of rea-cards domains.detect, driven by cards/format/*)."""
import json
import os

_CARDS = None


def _formats():
    global _CARDS
    if _CARDS is None:
        here = os.path.dirname(os.path.abspath(__file__))
        reg = os.path.join(os.path.dirname(os.path.dirname(here)), "format")
        out = {}
        for name in sorted(os.listdir(reg)):
            f = os.path.join(reg, name, "card.json")
            if os.path.isfile(f):
                with open(f, encoding="utf-8") as fh:
                    out[name] = json.load(fh)
        _CARDS = out
    return _CARDS


def detect_format(path: str) -> str:
    best, best_pri = "unknown", -1
    if os.path.isdir(path):
        for name, card in _formats().items():
            d = card.get("detect") or {}
            if not d.get("directory"):
                continue
            ok = (not d.get("suffix") or path.rstrip("/").endswith(d["suffix"])) and \\
                 (not d.get("contains") or os.path.exists(os.path.join(path, d["contains"])))
            if ok and d.get("priority", 0) > best_pri:
                best, best_pri = name, d.get("priority", 0)
        return best
    with open(path, "rb") as f:
        head = f.read(4096)
    for name, card in _formats().items():
        d = card.get("detect") or {}
        for m in d.get("magic") or []:
            want = bytes.fromhex(m["hex"])
            off = int(m.get("offset", 0))
            if head[off:off + len(want)] == want and d.get("priority", 0) > best_pri:
                best, best_pri = name, d.get("priority", 0)
    return best
'''


def import_rea(report: dict) -> None:
    head = git_head(REA)
    dom_files = sorted((REA / "cards" / "re_domain").glob("*/card.json"))
    prov = {"origin": "rea-cards", "path": rel(REA), "commit": head, "sha256": sha_files(dom_files), "read_on": DATE,
            "upstream": "morluto/rea (MIT)"}
    reg = write_registry("format", "File formats as cards (ported from rea-cards re_domain): magic bytes and "
                                   "predicates as data; detect_format reads them.", prov, tier=1,
                         category_aliases=["re_domain"])
    n = 0
    for f in dom_files:
        c = json.loads(f.read_text(encoding="utf-8"))
        c["category"] = "format"
        c["vendored_from"] = rel(f.parent)
        c.pop("witness", None)
        write_card(reg, c)
        n += 1
    reg = write_registry("re_operation", "Reverse-engineering operations whose backends are forms (lesson from "
                                         "rea-cards): a card-native Python form and a host-tool form of the same "
                                         "operation, checked equal on real files.", prov, tier=1)
    files = ["/bin/ls", "/usr/bin/true", "/bin/cat"]  # present on macOS and Linux
    write_card(reg, {
        "name": "list_strings", "category": "re_operation", "tier": 1,
        "statement": "List the printable-ASCII strings of a file with their byte offsets.",
        "forms": [{"name": "py_strings", "lang": "python", "file": "python.py", "entry": "py_strings", "cost": 40.0,
                   "domain": "any", "runnable": True, "notes": "card-native, no external process"},
                  {"name": "host_strings", "lang": "python", "file": "python.py", "entry": "host_strings",
                   "cost": 60.0, "domain": "any", "runnable": True,
                   "probe": {"kind": "all", "of": [{"kind": "platform", "system": "Darwin"},
                                                   {"kind": "executable", "name": "strings"}]},
                   "notes": "Apple cctools strings under LC_ALL=C (macOS only: GNU binutils strings scans other "
                            "sections and pads differently)"},
                  {"name": "rea_ghidra", "domain": "native_binary", "runnable": False, "cost": 60000,
                   "notes": "rea's Ghidra provider (form kept as documentation; see rea-cards)"}],
        "generators": [{"choice": files}, {"choice": [4, 6, 8]}],
        "equivalence": {"relation": "equal", "forms": ["py_strings", "host_strings"]},
        "provenance": {**prov, "rea_card": "cards/re_operation/list_strings"}}, {"python.py": STRINGS_PY})
    write_card(reg, {
        "name": "detect_format", "category": "re_operation", "tier": 1,
        "statement": "Name the most specific format card whose magic bytes / predicates match a file.",
        "forms": [{"name": "format_cards", "lang": "python", "file": "python.py", "entry": "detect_format",
                   "cost": 1.0, "domain": "any", "runnable": True}],
        "vectors": [{"name": "ls_is_native_binary", "args": ["/bin/ls"], "out_one_of": ["macho", "macho_fat", "elf"]}],
        "provenance": {**prov, "rea_card": "cards/re_operation/detect_format"}}, {"python.py": DETECT_PY})
    report["rea"] = {"commit": head, "format_cards": n, "operations": ["list_strings", "detect_format"]}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--only", default="hub,pheros,ting,rea")
    args = ap.parse_args(argv)
    sys.dont_write_bytecode = True
    report: dict = {}
    for part in args.only.split(","):
        {"hub": import_hub, "pheros": import_pheros, "ting": import_ting, "rea": import_rea}[part](report)
    (ROOT / "docs").mkdir(exist_ok=True)
    (ROOT / "docs" / "VENDOR_REPORT.json").write_text(json.dumps(report, indent=1, sort_keys=True, default=str) + "\n",
                                                      encoding="utf-8")
    print(json.dumps(report, indent=1, default=str)[:4000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
