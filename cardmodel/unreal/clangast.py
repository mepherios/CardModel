"""clangast — the real compiler as the C++ frontend: a translation unit's typed AST, read compactly.

``dump`` runs ``clang++ -fsyntax-only -Xclang -ast-dump=json`` into the cache (a UE translation unit is about a
gigabyte of JSON). ``read`` streams it: the dump is one TranslationUnitDecl whose top-level declarations are
printed at a fixed indentation, so each is parsed on its own, and only those located in the files ``keep`` accepts
are kept, converted to ``Node``s (kind, the attributes the lifter uses, children). Locations in clang's JSON are
diff-encoded (a file and a line are printed only when they change), so the reader tracks them in printing order,
including the declarations it drops.

``Unit`` indexes what was kept: declarations by id, the definition of every declaration (``previousDecl``
chains), records by qualified name with their constructors, and every function with a body together with its
qualified name, file and line, and whether it is a template pattern (dependent, not liftable) or concrete.

Honest limits (L1): the JSON format is clang's (stable since clang 9, but not a specification); declarations
outside the kept files are known only by the references to them (name and type), so a call into them is an atom
or a gap for the lifter, never guessed.
"""
from __future__ import annotations

import hashlib
import json
import pickle
import re
import subprocess
from pathlib import Path

from ..kernel import resources

FUNCS = ("FunctionDecl", "CXXMethodDecl", "CXXConstructorDecl", "CXXConversionDecl", "CXXDestructorDecl")
RECORDS = ("CXXRecordDecl", "ClassTemplateSpecializationDecl")
SCOPES = ("NamespaceDecl", *RECORDS, "ClassTemplatePartialSpecializationDecl")
ATTRS = ("id", "name", "opcode", "castKind", "value", "isArrow", "isPostfix", "valueCategory", "storageClass",
         "mangledName", "isImplicit", "tagUsed", "explicitlyDefaulted", "hasElse", "hasInit", "hasVar",
         "isConstexpr", "init", "previousDecl", "parentDeclContextId", "constexpr", "inline", "variadic",
         "isBitfield", "completeDefinition", "argType", "isPartOfExplicitCast", "elidable", "list", "zeroing",
         "fixedUnderlyingType",
         "hadMultipleCandidates", "constructionKind", "conversionFunc", "isReferenced")
VERSION = 12  # bump when Node or the index changes (the pickle cache keys on it)


class Node:
    __slots__ = ("k", "a", "c")

    def __init__(self, k, a, c):
        self.k, self.a, self.c = k, a, c

    def get(self, key, default=None):
        return self.a.get(key, default)

    def __repr__(self):
        return f"Node({self.k}, {self.a.get('name') or self.a.get('opcode') or ''}, {len(self.c)} children)"


NULL = Node("<null>", {}, ())


class _Loc:
    """The location state of the dump: clang prints a file or a line only when it differs from the last one."""

    def __init__(self):
        self.file, self.line = None, None

    def see(self, loc):
        if not isinstance(loc, dict):
            return
        if "spellingLoc" in loc or "expansionLoc" in loc:
            self.see(loc.get("spellingLoc"))
            self.see(loc.get("expansionLoc"))
            return
        if "file" in loc:
            self.file = loc["file"]
        if "line" in loc:
            self.line = loc["line"]


def _drop(kind: str) -> bool:
    return kind.endswith("Comment") or kind.endswith("Attr") or kind in ("TemplateArgument", "BuiltinType",
                                                                          "RecordType", "TypedefType")


def _compact(n: dict, L: _Loc) -> Node | None:
    """One JSON node to a Node, updating the location state in printing order (loc, range, then children)."""
    if not n:
        return NULL
    L.see(n.get("loc"))
    file, line = L.file, L.line
    rng = n.get("range")
    if isinstance(rng, dict):
        L.see(rng.get("begin"))
        L.see(rng.get("end"))
    kind = n.get("kind", "?")
    inner = n.get("inner") or ()
    typedef_record = _record_ref(inner) if kind in ("TypedefDecl", "TypeAliasDecl") else None
    align = None
    if kind in ("FieldDecl", "CXXRecordDecl", "ClassTemplateSpecializationDecl", "VarDecl"):
        for c in inner:
            if isinstance(c, dict) and c.get("kind") == "AlignedAttr":
                ce = next((y for y in c.get("inner") or () if isinstance(y, dict) and "value" in y), None)
                if ce is not None:
                    try:
                        align = max(align or 0, int(ce["value"]))
                    except (TypeError, ValueError):
                        pass
    if _drop(kind):
        if kind == "TemplateArgument":                 # kept as a type name only: it names a specialization
            for c in inner:                            # (still walked, for the location state)
                _compact(c, L)
            t = (n.get("type") or {}).get("qualType")
            return Node("TemplateArgument", {"t": t, "value": n.get("value")}, ())
        for c in inner:
            _compact(c, L)
        return None
    a = {k: n[k] for k in ATTRS if k in n}
    t = n.get("type")
    if isinstance(t, dict):
        a["t"] = t.get("qualType")
        if "desugaredQualType" in t:
            a["dt"] = t["desugaredQualType"]
    ref = n.get("referencedDecl")
    if isinstance(ref, dict):
        a["ref"] = (ref.get("id"), ref.get("kind"), ref.get("name"), (ref.get("type") or {}).get("qualType"))
    if "referencedMemberDecl" in n:
        a["mref"] = n["referencedMemberDecl"]
    if "ctorType" in n:
        a["ctor"] = (n["ctorType"] or {}).get("qualType")
    ai = n.get("anyInit")
    if isinstance(ai, dict):
        a["init_field"] = (ai.get("id"), ai.get("name"), (ai.get("type") or {}).get("qualType"))
    bi = n.get("baseInit")
    if isinstance(bi, dict):
        a["init_base"] = bi.get("qualType")
        if bi.get("desugaredQualType"):
            a["init_base_dt"] = bi["desugaredQualType"]
    for key in ("computeLHSType", "computeResultType"):
        if isinstance(n.get(key), dict):
            a[key] = n[key].get("qualType")
    if isinstance(n.get("bases"), list):
        a["bases"] = [(b.get("type") or {}).get("desugaredQualType") or (b.get("type") or {}).get("qualType")
                      for b in n["bases"]]
    if typedef_record:
        a["typedef_record"] = typedef_record
    if align:
        a["align"] = align
    if isinstance(a.get("fixedUnderlyingType"), dict):
        a["fixedUnderlyingType"] = a["fixedUnderlyingType"].get("qualType")
    if "lookups" in n:
        a["lookups"] = [(x.get("id"), x.get("kind"), x.get("name")) for x in n["lookups"]]
    if kind in FUNCS or kind in RECORDS or kind in ("VarDecl", "FieldDecl", "EnumConstantDecl", "CXXRecordDecl",
                                                    "ClassTemplateDecl", "FunctionTemplateDecl", "TypedefDecl",
                                                    "TypeAliasDecl"):
        a["file"], a["line"] = file, line
    kids = []
    for c in inner:
        x = _compact(c, L) if isinstance(c, dict) else NULL
        if x is not None:
            kids.append(x)
    return Node(kind, a, tuple(kids))


def _record_ref(inner) -> str | None:
    """The record a typedef names: the ``decl`` of the first RecordType in its type."""
    stack = list(inner)
    while stack:
        x = stack.pop()
        if isinstance(x, dict):
            if x.get("kind") == "RecordType" and isinstance(x.get("decl"), dict):
                return x["decl"].get("id")
            stack.extend(x.get("inner") or ())
    return None


def dump(clang: str, flags: list[str], tu: Path, out: Path, timeout: int = 900, tries: int = 6) -> dict:
    """Run the frontend; the JSON goes to ``out``. Returns {"ok", "errors", "seconds", "tries"}. Apple clang's
    JSON dumper sometimes crashes on a unit it dumps fine the next time, so a crash (a signal, no diagnostics) is
    retried."""
    import time
    t0 = time.perf_counter()
    out.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(1, tries + 1):
        with open(out, "w", encoding="utf-8") as fh:
            p = resources.run([clang, *flags, "-fsyntax-only", "-Xclang", "-ast-dump=json", str(tu)],
                              timeout=timeout, heavy=True, capture_output=False, stdout=fh, stderr=subprocess.PIPE,
                              stdin=subprocess.DEVNULL, mem_cap_mb=4096)
        errors = [ln for ln in (p.stderr or "").splitlines() if ": error:" in ln or ": fatal error:" in ln]
        crashed = any("Segmentation fault" in e or "failed due to signal" in e for e in errors)
        if not crashed:
            break
    return {"ok": p.returncode == 0 and not errors, "errors": errors[:40], "returncode": p.returncode,
            "seconds": round(time.perf_counter() - t0, 1), "tries": attempt}


def syntax(clang: str, flags: list[str], tu: Path, timeout: int = 900) -> list[tuple[int, str]]:
    """Errors of a syntax-only compile of ``tu``, each attributed to a line of ``tu`` itself: the error's own line
    when it is in ``tu``; else the outermost 'in instantiation ... requested here' note in ``tu`` (the line that
    instantiated the failing template); else the line of ``tu`` whose #include leads to it."""
    p = resources.run([clang, *flags, "-fsyntax-only", "-ferror-limit=0", str(tu)], timeout=timeout, heavy=True,
                      stdin=subprocess.DEVNULL, mem_cap_mb=3072)
    name = str(tu)
    diag = re.compile(r"^(.*?):(\d+):\d+: (fatal error|error|warning|note): (.*)$")
    blocks, chain, cur = [], [], None
    for ln in (p.stderr or "").splitlines():
        if ln.startswith("In file included from "):
            chain.append(ln)
            continue
        m = diag.match(ln)
        if not m:
            continue
        f, line, kind, msg = m.group(1), int(m.group(2)), m.group(3), m.group(4)
        if kind in ("error", "fatal error"):
            cur = {"file": f, "line": line, "msg": msg, "chain": chain, "notes": []}
            blocks.append(cur)
        elif kind == "warning":
            cur = None
        elif cur is not None:
            cur["notes"].append((f, line, msg))
        chain = []
    out = []
    for b in blocks:
        if b["file"] == name:
            out.append((b["line"], b["msg"]))
            continue
        inst = [ln for f, ln, msg in b["notes"] if f == name]
        if inst:
            out.append((inst[-1], b["msg"]))
            continue
        inc = next((int(m.group(1)) for c in b["chain"]
                    for m in [re.match(rf"^In file included from {re.escape(name)}:(\d+)", c)] if m), None)
        out.append((inc or 0, b["msg"]))
    if p.returncode != 0 and not out:
        out.append((0, (p.stderr or "")[-600:]))
    return out


def _scan_enums(n: dict, values: dict, names: dict) -> None:
    """Every enumerator's value (by id) and every enum's underlying type (by name), kept or not: an enumerator
    without an initializer is the previous one plus one."""
    stack = [n]
    while stack:
        x = stack.pop()
        if not isinstance(x, dict):
            continue
        inner = x.get("inner") or ()
        if x.get("kind") == "EnumDecl":
            if x.get("name"):
                names.setdefault(x["name"], (x.get("fixedUnderlyingType") or {}).get("qualType") or "int")
            v = -1
            for c in inner:
                if isinstance(c, dict) and c.get("kind") == "EnumConstantDecl":
                    ce = next((y for y in c.get("inner") or () if isinstance(y, dict) and "value" in y), None)
                    try:
                        v = int(ce["value"]) if ce is not None else v + 1
                    except (TypeError, ValueError):
                        v = v + 1
                    values[c.get("id")] = v
            continue
        stack.extend(inner)


def read(path: Path, keep, enums: dict | None = None, wanted: frozenset = frozenset()) -> list[Node]:
    """The top-level declarations of a dump whose own file ``keep(file)`` accepts (streamed, one at a time).
    ``enums``, when given, collects {"values": id -> int, "names": name -> underlying type} from every chunk."""
    L = _Loc()
    kept: list[Node] = []
    buf: list[str] = []
    inside = False
    with open(path, encoding="utf-8") as f:
        for line in f:
            if not inside:
                if line.startswith("    {") and len(line.rstrip()) == 5:
                    buf, inside = [line], True
                continue
            buf.append(line)
            if line.startswith("    }"):
                inside = False
                text = "".join(buf).rstrip().rstrip(",")
                buf = []
                n = json.loads(text)
                if enums is not None and '"EnumDecl"' in text:
                    _scan_enums(n, enums.setdefault("values", {}), enums.setdefault("names", {}))
                own = _Loc()
                own.file, own.line = L.file, L.line
                own.see(n.get("loc"))
                if keep(own.file):
                    x = _compact(n, L)
                    if x is not None:
                        x.a["file"] = x.a.get("file") or own.file
                        kept.append(x)
                else:
                    if wanted and any(f'"name": "{w}"' in text for w in wanted):
                        _track_only(n, L, wanted, kept)
                    else:
                        _track_only(n, L)
                resources.guard("reading the AST")
    return kept


def _track_only(n: dict, L: _Loc, wanted=None, extra=None) -> None:
    """Advance the location state through a node that is not kept (iterative, in printing order). A class template
    ``wanted`` names is compacted into ``extra`` on the way (its specializations are printed under its first
    declaration, which may sit in a file that is not kept)."""
    stack = [n]
    while stack:
        x = stack.pop()
        if not isinstance(x, dict):
            continue
        if wanted and x.get("kind") == "ClassTemplateDecl" and x.get("name") in wanted:
            got = _compact(x, L)
            if got is not None and extra is not None:
                extra.append(got)
            continue
        L.see(x.get("loc"))
        rng = x.get("range")
        if isinstance(rng, dict):
            L.see(rng.get("begin"))
            L.see(rng.get("end"))
        inner = x.get("inner")
        if inner:
            stack.extend(reversed(inner))


class Function:
    __slots__ = ("node", "qual", "scope", "file", "line", "pattern", "record", "unit")

    def __init__(self, node, qual, scope, file, line, pattern, record, unit):
        self.node, self.qual, self.scope, self.file, self.line = node, qual, scope, file, line
        self.pattern, self.record, self.unit = pattern, record, unit

    @property
    def name(self) -> str:
        return self.node.a.get("name") or "?"

    @property
    def type(self) -> str:
        return self.node.a.get("t") or ""

    @property
    def mangled(self) -> str:
        return self.node.a.get("mangledName") or f"{self.qual}|{self.type}"


class Unit:
    """An index over the kept declarations of one translation unit."""

    def __init__(self, name: str, tops: list[Node], enums: dict | None = None):
        self.name = name
        self.enum_values: dict[str, int] = dict((enums or {}).get("values") or {})
        self.enum_names: dict[str, str] = dict((enums or {}).get("names") or {})
        self.decls: dict[str, Node] = {}
        self.parent: dict[str, str] = {}             # decl id -> enclosing record id
        self.defs: dict[str, Node] = {}              # any declaration id -> its definition (a node with a body)
        self.records: dict[str, Node] = {}           # qualified record name -> record node
        self.record_name: dict[str, str] = {}        # record id -> qualified name
        self.pattern_records: set[str] = set()       # records of a template's pattern (dependent)
        self.scope_name: dict[str, str] = {}         # namespace or record id -> qualified name
        self.functions: list[Function] = []
        self.statics: dict[str, Node] = {}           # qualified static/global variable -> its defining VarDecl
        self.templates: list[tuple[str, Node]] = []  # (scope, ClassTemplateDecl or FunctionTemplateDecl)
        self.typedefs: dict[str, str] = {}           # typedef / alias name (qualified, and bare) -> its type
        self.template_params: dict[str, list[str]] = {}   # qualified class template -> its parameter names
        self._static_refs: list[tuple] = []
        for t in tops:
            self._walk(t, [], None, False)
        # a specialization may first appear as a bare reference (no template arguments); the names of what is in
        # it are settled once the full node has been seen
        for fn in self.functions:
            if fn.record and fn.record in self.record_name:
                fn.scope = self.record_name[fn.record]
                fn.qual = f"{fn.scope}::{fn.name}" if fn.scope else fn.name
        self.var_defs: dict[str, Node] = {}          # any declaration id of a variable -> its definition with init
        for pdc, sc, nm, n in self._static_refs:
            if pdc and pdc in self.pattern_records:
                continue
            scope = self.scope_name.get(pdc, sc) if pdc else sc
            self.statics.setdefault(f"{scope}::{nm}" if scope else nm, n)
            i, seen = n.a.get("id"), set()
            while i and i not in seen:
                seen.add(i)
                self.var_defs.setdefault(i, n)
                i = (self.decls.get(i) or NULL).a.get("previousDecl")
        del self._static_refs
        for fn in self.functions:
            body = has_body(fn.node)
            if body:
                ids = [fn.node.a.get("id")]
                prev = fn.node.a.get("previousDecl")
                while prev and prev not in ids:
                    ids.append(prev)
                    prev = (self.decls.get(prev) or NULL).a.get("previousDecl")
                for i in ids:
                    if i:
                        self.defs[i] = fn.node

    def _walk(self, n: Node, scope: list[str], record: str | None, pattern: bool) -> None:
        k = n.k
        i = n.a.get("id")
        if i:
            # clang prints a declaration fully once and as a bare reference ({id, kind, name}) elsewhere: a
            # reference never replaces the full node
            old = self.decls.get(i)
            if old is not None and not n.c and old.c:
                return
            self.decls[i] = n
            if record:
                self.parent[i] = record
        if k == "ClassTemplateDecl" or k == "FunctionTemplateDecl":
            if not pattern:
                self.templates.append(("::".join(scope), n))
            if k == "ClassTemplateDecl" and n.a.get("name"):
                self.template_params.setdefault("::".join([*scope, n.a["name"]]),
                                                [c.a.get("name") or "" for c in n.c
                                                 if c.k in ("TemplateTypeParmDecl", "NonTypeTemplateParmDecl")])
            first = True
            for c in n.c:
                if c.k in FUNCS or c.k == "CXXRecordDecl":
                    # the first function / record of a template is its pattern (dependent); the rest are its
                    # specializations, which carry TemplateArgument children
                    spec = any(x.k == "TemplateArgument" for x in c.c) and not first
                    self._walk(c, scope, record, pattern or not spec)
                    first = False
                else:
                    self._walk(c, scope, record, pattern)
            return
        if k == "ClassTemplatePartialSpecializationDecl":
            pattern = True
        if k in SCOPES:
            nm = n.a.get("name") or ""
            if k == "ClassTemplateSpecializationDecl":
                args = [x.a.get("t") or str(x.a.get("value")) for x in n.c if x.k == "TemplateArgument"]
                nm = f"{nm}<{', '.join(args)}>"
            pdc = n.a.get("parentDeclContextId")
            if pdc and pdc in self.scope_name:          # declared elsewhere (an explicit instantiation at file
                scope = self.scope_name[pdc].split("::") if self.scope_name[pdc] else []   # scope)
            sub = scope + [nm] if nm else scope
            if n.c or i not in self.scope_name:
                self.scope_name[i] = "::".join(sub)
            if k in RECORDS or k == "ClassTemplatePartialSpecializationDecl":
                q = "::".join(sub)
                if n.c or i not in self.record_name:
                    self.record_name[i] = q
                if pattern:
                    self.pattern_records.add(i)
                if not pattern and n.a.get("completeDefinition", True) and any(c.k in ("FieldDecl", *FUNCS)
                                                                               for c in n.c):
                    self.records.setdefault(q, n)
                for c in n.c:
                    self._walk(c, sub, i, pattern)
                return
            for c in n.c:
                self._walk(c, sub, record, pattern)
            return
        if k in FUNCS:
            nm = n.a.get("name") or "?"
            sc = "::".join(scope)
            pdc = n.a.get("parentDeclContextId")
            if pdc and pdc in self.record_name:        # a member defined out of line: it belongs to its record
                sc, record = self.record_name[pdc], pdc
                pattern = pattern or pdc in self.pattern_records
                self.parent[i] = pdc
            self.functions.append(Function(n, f"{sc}::{nm}" if sc else nm, sc, n.a.get("file"), n.a.get("line"),
                                           pattern, record, self.name))
            return
        if k in ("TypedefDecl", "TypeAliasDecl") and not pattern and record is None and n.a.get("name"):
            target = n.a.get("dt") or n.a.get("t")
            if target:
                self.typedefs.setdefault("::".join([*scope, n.a["name"]]), target)
                self.typedefs.setdefault(n.a["name"], target)
        if k in ("TypedefDecl", "TypeAliasDecl") and n.a.get("typedef_record") and not pattern:
            target = self.decls.get(n.a["typedef_record"])
            nm = n.a.get("name")
            if target is not None and nm and any(c.k == "FieldDecl" for c in target.c):
                q = "::".join([*scope, nm])
                self.records.setdefault(q, target)
                if not target.a.get("name"):
                    self.record_name[n.a["typedef_record"]] = q
            return
        if k == "VarDecl" and n.a.get("init") and not pattern:
            nm = n.a.get("name")
            if nm:
                self._static_refs.append((n.a.get("parentDeclContextId") or record, "::".join(scope), nm, n))
        for c in n.c:
            if isinstance(c, Node):
                self._walk(c, scope, record, pattern)

    def definition(self, decl_id: str) -> Node | None:
        return self.defs.get(decl_id)

    def record_of(self, qual: str) -> Node | None:
        return self.records.get(_norm_type(qual))

    def constructors(self, record_qual: str) -> list[Node]:
        r = self.record_of(record_qual)
        return [c for c in (r.c if r else ()) if c.k == "CXXConstructorDecl"]


def has_body(fn: Node) -> Node | None:
    return next((c for c in fn.c if c.k in ("CompoundStmt", "CXXTryStmt")), None)


def _norm_type(t: str) -> str:
    t = re.sub(r"\b(const|volatile|struct|class|union)\b", "", t or "")
    t = t.replace("&", "").replace("*", "")
    return re.sub(r"\s+", " ", t).strip().replace(" <", "<").replace("< ", "<").replace(" >", ">")


WANTED = frozenset({"TEnumAsByte"})


def _pickle_path(dump_path: Path, cache_dir: Path, keep_tag: str) -> Path:
    """A dump's name carries the hash of what clang read; the pickle's adds this reader's VERSION and what it keeps."""
    key = hashlib.sha256(f"{VERSION}|{dump_path.name}|{keep_tag}".encode()).hexdigest()[:16]
    return cache_dir / f"{dump_path.stem}.{key}.pickle"


def ready(dump_path: Path, cache_dir: Path, keep_tag: str) -> bool:
    """The unit can be loaded: its dump is there, or its pickle for this reader is."""
    return dump_path.is_file() or _pickle_path(dump_path, cache_dir, keep_tag).is_file()


def load(dump_path: Path, name: str, keep, cache_dir: Path, keep_tag: str = "", drop_json: bool = False) -> Unit:
    """A Unit from a dump, through a pickle cache. With ``drop_json`` the dump (a gigabyte of JSON) is deleted once
    its pickle is written; the pickle is all a later run reads."""
    pk = _pickle_path(dump_path, cache_dir, keep_tag)
    if pk.is_file():
        with open(pk, "rb") as f:
            return pickle.load(f)
    for old in cache_dir.glob(f"{dump_path.stem}.*.pickle"):
        old.unlink(missing_ok=True)
    enums: dict = {}
    unit = Unit(name, read(dump_path, keep, enums, WANTED), enums)
    tmp = pk.with_name(pk.name + ".tmp")
    with open(tmp, "wb") as f:
        pickle.dump(unit, f, protocol=pickle.HIGHEST_PROTOCOL)
    tmp.replace(pk)
    if drop_json:
        dump_path.unlink(missing_ok=True)
    return unit


__all__ = ["FUNCS", "Function", "NULL", "Node", "Unit", "dump", "has_body", "load", "read", "ready", "syntax"]
