"""cards — an AnyPS5 scan as cards: one per export, debt entry, library and shader instruction.

Registries (packed, regenerated whole by every scan; the scan is an observation, never edited by rules):

  anyps5_export       one card per declared export: every APS5_VABI definition (name = library.definition, the
                      ones AnyPS5's badge counts), every assembly export, every raw-NID alias. Fields: library,
                      kind, state (implemented | pending, AnyPS5's rule), symbol (when it differs from the
                      definition), inert, constant, params,
                      param_count, returns, throws, hit_log, messages, uses (exports it reaches through its
                      calls), helper_stub (a cross-file helper chain that ends in NotImplemented), packet (Agc),
                      tests (test files that name it), debt (entries that name it), provenance (file, line).
  anyps5_debt         one card per technical-debt bullet: component, section, text, exports (resolved
                      names), libraries, titles, closes_when, provenance (file, line).
  anyps5_library      one card per core/libs/prx directory: the badge's counts, files, shared sources.
  anyps5_instruction  one card per RDNA instruction in tools/rdna_isa.txt: decoded, translated, executed.
  anyps5_snapshot     ``current``: when, what (sha256 of everything read), the badges, the parity check.

Packs leave out optional fields that hold their default (None, False, 0, empty), so a missing field reads as
its default.

Honest limits (L1): a debt card keeps the bullet's whole text (``text``, quoted from AnyPS5's docs so the
classification can be recomputed from the cards alone); ``uses`` is resolved by name as scan.py describes, so it can include a same-named function
from another file when no closer definition exists.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from .scan import STUB, Scan, strip_symbol

EXCERPT = 320
REGISTRIES = {
    "anyps5_export": "AnyPS5 exports, one card per declared function, assembly export or raw-NID alias, with "
                     "its implementation state under AnyPS5's own counting rule and the file and line it is in.",
    "anyps5_debt": "AnyPS5 technical-debt entries, one card per bullet of docs/dev/TechnicalDebt.md and "
                   "docs/dev/debt/*.md, with the exports it names and its file and line.",
    "anyps5_library": "AnyPS5 system libraries (core/libs/prx directories) with the badge's counts.",
    "anyps5_instruction": "RDNA shader instructions (tools/rdna_isa.txt) with what AnyPS5 decodes, translates "
                          "and runs in an execution test.",
    "anyps5_snapshot": "What an AnyPS5 scan read: content hash, badges, and the parity check against AnyPS5's "
                       "own progress tool.",
}


def export_name(library: str, definition: str) -> str:
    return f"{library}.{definition}"


def definition_of(card) -> str:
    """The C++ name of an export card's definition (the card name is library.definition)."""
    return card.get("target", "").split(".", 1)[-1] if card.get("kind") == "nid_alias" else \
        card["name"][len(card["library"]) + 1:]


def symbol_of(card) -> str:
    """The exported symbol: the definition without AnyPS5's _nid_postfix / _nid_disambigN suffixes."""
    return card.get("symbol") or definition_of(card)


class _Graph:
    """Calls resolved by name across one checkout: same file, then same library, then a unique export."""

    def __init__(self, scan: Scan):
        self.nodes: dict[tuple, dict] = {}
        self.by_file: dict[tuple, list] = {}
        self.by_lib: dict[tuple, list] = {}
        self.global_exports: dict[str, list] = {}
        for lib in scan.libraries:
            for h in lib.helpers:
                key = ("h", lib.name, h["file"], h["name"])
                n = self.nodes.setdefault(key, {"calls": set(), "stub": False, "file": h["file"], "lib": lib.name,
                                                "name": h["name"], "generic": 0, "paths": [], "packets": [],
                                                "delegates": []})
                n["packets"].append(h["packet"])
                n["delegates"].append(h["delegate"])
                n["calls"] |= set(h["calls"])
                n["stub"] = n["stub"] or h["direct_stub"]
                n["generic"] += h["stub_generic"]
                n["paths"] += h["stub_paths"]
            for d in lib.defs:
                key = ("e", lib.name, d["name"])
                n = self.nodes.setdefault(key, {"calls": set(), "stub": False, "files": set(), "lib": lib.name,
                                                "name": d["name"], "generic": 0, "paths": [], "packets": [],
                                                "delegates": []})
                n["packets"].append(d["packet"])
                n["delegates"].append(d["delegate"])
                n["calls"] |= set(d["calls"])
                n["files"].add(d["file"])
                n["generic"] += d["stub_generic"]
                n["paths"] += d["stub_paths"]
        for key, n in self.nodes.items():
            files = [n["file"]] if key[0] == "h" else sorted(n["files"])
            for f in files:
                self.by_file.setdefault((n["lib"], f, n["name"]), []).append(key)
            self.by_lib.setdefault((n["lib"], n["name"]), []).append(key)
            if key[0] == "e":
                self.global_exports.setdefault(n["name"], []).append(key)
                sym = strip_symbol(n["name"])
                if sym != n["name"]:
                    self.global_exports.setdefault(sym, []).append(key)
        self._memo: dict[tuple, tuple] = {}

    def packet(self, key: tuple, depth: int = 0) -> tuple[dict | None, list]:
        """The one fixed packet a function writes, directly or through the function it hands it to; every
        definition of the name must agree (overloads and #if branches included), else None."""
        n = self.nodes[key]
        if len(n["packets"]) != 1 or depth > 4:
            return None, []
        if n["packets"][0] is not None:
            return n["packets"][0], []
        d = n["delegates"][0]
        if d is None:
            return None, []
        hits = [t for t in self.resolve(n["lib"], self._files(key), d) if t != key]
        if len(hits) != 1:
            return None, []
        pk, via = self.packet(hits[0], depth + 1)
        return (pk, [self.nodes[hits[0]]["name"]] + via) if pk else (None, [])

    def resolve(self, lib: str, files, name: str) -> list[tuple]:
        for f in files:
            hit = self.by_file.get((lib, f, name))
            if hit:
                return hit
        hit = self.by_lib.get((lib, name))
        if hit:
            return hit
        g = self.global_exports.get(name)
        return g if g and len({k[1] for k in g}) == 1 else []

    def _files(self, key):
        n = self.nodes[key]
        return [n["file"]] if key[0] == "h" else sorted(n["files"])

    def helper(self, key: tuple, depth: int = 0) -> tuple:
        """(exports reachable without passing another export, a helper chain to NotImplemented or None,
        whole-function stub calls reached, named unsupported paths reached)."""
        if key in self._memo:
            return self._memo[key]
        self._memo[key] = (frozenset(), None, 0, ())          # cycles contribute nothing new
        n = self.nodes[key]
        exports, chain = set(), (n["name"],) if n["stub"] else None
        generic, paths = n["generic"], list(n["paths"])
        if depth < 40:
            for c in sorted(n["calls"]):
                if c == STUB:
                    continue
                for t in self.resolve(n["lib"], self._files(key), c):
                    if t == key:
                        continue
                    if t[0] == "e":
                        exports.add(t)
                    else:
                        ex, ch, g, ps = self.helper(t, depth + 1)
                        exports |= ex
                        generic += g
                        paths += [x for x in ps if x not in paths]
                        if chain is None and ch is not None:
                            chain = (n["name"],) + ch
        self._memo[key] = (frozenset(exports), chain, generic, tuple(paths))
        return self._memo[key]

    def export(self, lib: str, name: str) -> tuple:
        """(exports it reaches, a cross-file helper chain to NotImplemented, whole-function stub calls reached,
        named unsupported paths reached)."""
        key = ("e", lib, name)
        n = self.nodes[key]
        exports, chain = set(), None
        generic, paths = n["generic"], list(n["paths"])
        for c in sorted(n["calls"]):
            if c == STUB:
                continue
            for t in self.resolve(lib, self._files(key), c):
                if t == key:
                    continue
                if t[0] == "e":
                    exports.add(t)
                else:
                    ex, ch, g, ps = self.helper(t)
                    exports |= ex
                    generic += g
                    paths += [x for x in ps if x not in paths]
                    if chain is None and ch is not None and self.nodes[t]["file"] not in n["files"]:
                        chain = ch
        return exports, chain, generic, paths


REQUIRED = {"name", "library", "kind", "state", "provenance", "component", "text"}


def _compact(card: dict) -> dict:
    """Leave out optional fields that hold their default (None, False, 0, empty): a pack line says what is."""
    return {k: v for k, v in card.items() if k in REQUIRED or v not in (None, False, 0, [], {}, "")}


def excerpt(card: dict, n: int = EXCERPT) -> str:
    t = card.get("text") or ""
    return t if len(t) <= n else t[:n - 1] + "…"


def build(scan: Scan, parity: dict | None = None) -> dict[str, list[dict]]:
    graph = _Graph(scan)
    tests = scan.tests
    exports, by_symbol = [], {}
    for lib in scan.libraries:
        groups: dict[str, list] = {}
        for d in lib.defs:
            groups.setdefault(d["name"], []).append(d)
        for name, defs in groups.items():
            implemented = name in lib.done
            first = next((d for d in defs if not d["pending"]), defs[0]) if implemented else defs[0]
            uses, chain, generic, paths = graph.export(lib.name, name)
            packet, via = graph.packet(("e", lib.name, name))
            sym = strip_symbol(name)
            test_files = sorted(set(tests.get(name, [])) | set(tests.get(sym, [])))
            card = {"name": export_name(lib.name, name), "library": lib.name, "symbol": sym if sym != name else None,
                    "kind": "function", "state": "implemented" if implemented else "pending",
                    "inert": name in lib.inert, "constant": first["constant"], "params": first["params"],
                    "param_count": first["param_count"], "returns": first["returns"], "throws": first["throws"],
                    "hit_log": first["hit"], "throw_messages": [m[:120] for m in first["throw_messages"][:3]],
                    "hit_messages": [m[:120] for m in first["hit_messages"][:2]],
                    "uses": sorted(export_name(k[1], k[2]) for k in uses),
                    "helper_stub": list(chain) if chain else None, "packet": packet, "packet_via": via,
                    "stub_paths": paths[:6],
                    "partial_pending": (not implemented) and generic == 0 and bool(paths),
                    "tests": test_files[:1], "test_files": len(test_files),
                    "unknown_name": "unknown" in name.lower(),
                    "provenance": {"file": first["file"], "line": first["line"], "end_line": first["end_line"],
                                   **({"also": [f"{d['file']}:{d['line']}" for d in defs if d is not first]}
                                      if len(defs) > 1 else {})}}
            exports.append(card)
            by_symbol.setdefault(sym, []).append(card)
            if sym != name:
                by_symbol.setdefault(name, []).append(card)
        seen = {export_name(lib.name, n) for n in groups}
        for a in lib.asm:
            nm = export_name(lib.name, a["name"])
            if nm in seen:
                continue
            seen.add(nm)
            card = {"name": nm, "library": lib.name, "kind": "asm", "state": "implemented",
                    "tests": sorted(tests.get(a["name"], []))[:1], "test_files": len(tests.get(a["name"], [])),
                    "provenance": {"file": a["file"], "line": a["line"]}}
            exports.append(card)
            by_symbol.setdefault(a["name"], []).append(card)
        for a in lib.aliases:
            target = export_name(lib.name, a["target"])
            state = "implemented" if a["target"] in lib.done else ("pending" if a["target"] in lib.todo else "unknown")
            nm = f"{lib.name}.nid_{a['nid'].replace('+', '_p')}"
            if nm in seen:
                continue
            seen.add(nm)
            exports.append({"name": nm, "library": lib.name, "kind": "nid_alias", "nid": a["nid"], "target": target,
                            "state": state, "unknown_name": "unknown" in a["target"].lower(),
                            "provenance": {"file": a["file"], "line": a["line"]}})
    exports = [_compact(c) for c in exports]
    names = {c["name"] for c in exports}
    assert len(names) == len(exports), "export card names must be unique"
    libraries = {lib.name for lib in scan.libraries}
    debt = []
    debt_on: dict[str, list] = {}
    for d in scan.debt:
        comp = d["component"]
        found, libs, unresolved = [], [], []
        for n in d["names"]:
            if n in libraries:
                libs.append(n)
                continue
            local = [c for c in by_symbol.get(n, []) if c["library"] == comp]
            hits = local or by_symbol.get(n, [])
            if len({c["library"] for c in hits}) > 1 and not local:
                hits = []
            if hits:
                found += [c["name"] for c in hits]
            elif re.match(r"(sce|_?Z|[a-z]\w*_)", n):
                unresolved.append(n)
        for link in d["links"]:
            m = re.search(r"core/libs/prx/([\w.-]+)", link)
            if m and m.group(1) in libraries:
                libs.append(m.group(1))
        name = f"{comp}.L{d['line']}"
        text = d["text"]
        card = {"name": name, "component": comp, "section": d["section"], "text": text,
                "exports": sorted(set(found)), "libraries": sorted(set(libs) | ({comp} if comp in libraries else set())),
                "unresolved_names": sorted(set(unresolved))[:12], "titles": d["titles"],
                "closes_when": d["closes_when"],
                "provenance": {"origin": "anyps5", "file": d["file"], "line": d["line"], "sha": d["sha"]}}
        debt.append(_compact(card))
        for e in card["exports"]:
            debt_on.setdefault(e, []).append(name)
    for c in exports:
        c["debt"] = sorted(debt_on.get(c["name"], []))
    lib_cards = []
    debt_files = {d["component"] for d in scan.debt}
    for lib in scan.libraries:
        lib_cards.append({"name": lib.name, "done": len(lib.done), "todo": len(lib.todo), "inert": len(lib.inert),
                          "files": lib.files, "definitions": len({d["name"] for d in lib.defs}),
                          "aliases": len(lib.aliases), "asm": len(lib.asm), "shared_sources": lib.shared_sources,
                          "empty": not (lib.done or lib.todo) and not lib.shared_sources,
                          "debt_file": f"docs/dev/debt/{lib.name}.md" if lib.name in debt_files else None,
                          "provenance": {"origin": "anyps5", "path": f"core/libs/prx/{lib.name}", "sha256": lib.sha256}})
    instructions = []
    sh = scan.shader
    if sh.get("available"):
        dec, tr, ex = set(sh["decoded"]), set(sh["translated"]), set(sh["executed"])
        for n, meta in sh["isa"].items():
            instructions.append({"name": n, "encoding": meta["encoding"], "decoded": n in dec, "translated": n in tr,
                                 "executed": n in ex,
                                 "provenance": {"origin": "anyps5", "file": "tools/rdna_isa.txt", "line": meta["line"]}})
    home = str(Path.home())
    root = str(scan.root)
    snapshot = {"name": "current", "root": "~" + root[len(home):] if root.startswith(home + "/") else root,
                "scanned_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "sha256": scan.sha256,
                "badge": scan.badge(), "shader_badge": scan.shader_badge(),
                "counts": {"exports": len(exports), "debt": len(debt), "libraries": len(lib_cards),
                           "instructions": len(instructions)},
                "rule": "AnyPS5 docs/dev/PROGRESS.md (tools/progress.py), reproduced in cardmodel/anyps5/scan.py",
                "provenance": {"origin": "anyps5", "tool": "cardmodel anyps5 scan"}}
    if parity is not None:
        snapshot["parity"] = {k: v for k, v in parity.items() if k != "mismatches"} | \
                             {"mismatch_count": len(parity["mismatches"]), "mismatches": parity["mismatches"][:20]}
    return {"anyps5_export": exports, "anyps5_debt": debt, "anyps5_library": lib_cards,
            "anyps5_instruction": instructions, "anyps5_snapshot": [snapshot]}


def save(store, cards: dict[str, list[dict]], layer: str | None = None) -> dict[str, int]:
    out = {}
    for reg, items in cards.items():
        if reg == "anyps5_snapshot":
            for c in items:
                store.save({**c, "category": reg}, layer=layer)
        else:
            store.save_pack(reg, "anyps5", items, layer=layer, description=REGISTRIES[reg])
        out[reg] = len(items)
    return out


__all__ = ["REGISTRIES", "build", "definition_of", "excerpt", "export_name", "save", "symbol_of"]
