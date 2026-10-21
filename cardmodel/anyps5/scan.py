"""scan — an AnyPS5 checkout read as observations (read-only), with a file and line for everything.

What is read (paths relative to the checkout root):

  core/libs/prx/<library>/**/*.cpp     APS5_VABI definitions (not under tests/), APS5_EXPORT raw-NID aliases,
                                       APS5_ASM_FUNCTION assembly exports
  docs/dev/TechnicalDebt.md, docs/dev/debt/*.md     technical-debt entries, one per bullet
  core/**/tests/**                     which exports a test file names
  tools/rdna_isa.txt, core/shader/recompiler/**     the shader instruction list, decoder opcodes, translation
  tools/progress.py                    read as data only: its opcode alias tables (``ast.literal_eval``)

The counting rule is AnyPS5's own (docs/dev/PROGRESS.md): a definition is pending when its body calls
``NotImplemented_nid_no_patch`` directly or through a wrapper in the same file; every other definition is
implemented; a name that is both counts as implemented; a library without definitions may share another
library's sources. ``Scan.badge()`` therefore gives the same done/total as the libraries badge, and
``parity()`` compares it, library by library and name by name, with a progress.json AnyPS5 produced.

Beyond the badge, every definition records its line span, parameters, the contents of its string literals
(the messages its throws and logs carry), its direct throws, the calls it makes (resolved later), whether its
body is behaviourally empty (AnyPS5's own "inert" rule) and, in the Agc libraries, the packet it emits.

Honest limits (L1): a lexical reading, not a compiler. Macros are not expanded, every #if branch is seen,
member functions defined out of line are not indexed as helpers, call targets are resolved by name (same
file, then same library, then a unique export anywhere), and a throw counts whether or not its condition
can hold. The scan never runs AnyPS5 code and never writes into the checkout.
"""
from __future__ import annotations

import ast
import hashlib
import re
from bisect import bisect_right
from pathlib import Path

from ..kernel import resources

STUB = "NotImplemented_nid_no_patch"

# C++ lexical classes, in the order the badge's scanner tries them: comments, raw strings, strings,
# characters, then code tokens (pp-numbers with digit separators, identifiers, single characters)
LEX = re.compile(
    r'(?P<comment>//[^\n]*|/\*[\s\S]*?\*/)'
    r'|(?P<raw>(?:u8|u|U|L)?R"(?P<delim>[^\s()\\]{0,16})\([\s\S]*?\)(?P=delim)")'
    r'|(?P<string>(?:u8|u|U|L)?"(?:\\[\s\S]|[^"\\])*")'
    r"|(?P<char>(?:u8|u|U|L)?'(?:\\[\s\S]|[^'\\])*')"
    r"|(?P<code>(?:[0-9]|\.[0-9])[A-Za-z0-9_.']*|[A-Za-z_][A-Za-z0-9_]*|\S)")
DEFINITION = re.compile(r"\bAPS5_VABI\s+(\w+)\s*\(([^;{]*)\)\s*(?:noexcept\s*)?(?:try\s*)?\{")
CALL = re.compile(r"\b(\w+)\s*\(")
KEYWORDS = r"return|else|do|throw|co_return|co_await|co_yield|and|or|not|xor|bitand|bitor|compl"
QUALIFIED = re.compile(rf"(?:\.|->|(?:\b(?!(?:{KEYWORDS})\b)\w+|>)\s*::)\s*$")
MEMBER = re.compile(r"(?:\.|->)\s*$")


def _member(body: str, at: int) -> bool:
    """Is the call at ``at`` a member call (``x.f(`` / ``p->f(``)? Only the text just before it matters."""
    return MEMBER.search(body, max(0, at - 64), at) is not None
LOCAL_FN = re.compile(
    r"^[ \t]*(?:static\s+)?(?:\[\[noreturn\]\]\s+)?(?:(?!APS5_VABI)[\w:<>,\s*&])+?[\s*&]"
    r"(?!(?:if|while|for|switch|catch|return|else)\b)(\w+)\s*\([^;{]*\)\s*"
    r"(?:const\s*)?(?:noexcept\s*)?(?:->\s*[\w:<>*&\s]+?)?\{", re.M)
DISCARD = re.compile(r"\(void\)\s*\w+\s*;")
EMPTY_RETURN = re.compile(r"return\s*;")
CONST_RETURN = re.compile(r"return\s+(?:[+-]?\s*(?:0[xX][0-9a-fA-F]+|\d+)[uUlL]*|\w+|\"(?:\\.|[^\"\\])*\")\s*;")
WRAPPER_RETURN = re.compile(r"return\s+(\w+)\s*\(([^()]*)\)\s*;")
BARE_THROW = re.compile(r"throw\b[^;]*;")
INT_RETURN = re.compile(r"return\s+(0[xX][0-9a-fA-F]+|\d+)[uUlL]*\s*;")
CMAKE_SHARED = re.compile(r'^\s*include\(\s*"?\$\{CMAKE_CURRENT_SOURCE_DIR\}/\.\./([\w.-]+)/[\w.-]+\.cmake"?\s*\)', re.M)
SOURCE_SHARED = re.compile(r'^\s*#\s*include\s*"prx/([\w.-]+)/[\w./-]+\.cpp"', re.M)
ALIAS = re.compile(r'\bAPS5_EXPORT\s*\(\s*L_{12}\s*,\s*(\w+)\s*\)')
ASM = re.compile(r'\bAPS5_(?:SIGNAL_)?ASM_FUNCTION\s*\(\s*(L_+)\s*\)')
NON_CALLS = {"if", "while", "for", "switch", "return", "sizeof", "catch", "static_cast", "reinterpret_cast",
             "const_cast", "dynamic_cast", "decltype", "alignof", "alignas", "noexcept", "throw", "new", "delete",
             "typeid", "defined", "static_assert", "assert", "__func__"}
PACKET_WRITERS = {"Allocate", "Reserve", "WriteNop", "WriteRegisterRange", "WriteRegisters", "WriteIndirectRegisters"}
TEST_EXTS = (".cpp", ".c", ".hpp", ".h", ".py", ".S", ".s")


def splice(text: str):
    """Remove line continuations as the C++ front end does; return the text and the cut table."""
    parts, pos, removed, cut_pos, cut_total = [], 0, 0, [], []
    for m in re.finditer(r"\\\r?\n", text):
        parts.append(text[pos:m.start()])
        cut_pos.append(m.start() - removed)
        removed += m.end() - m.start()
        cut_total.append(removed)
        pos = m.end()
    parts.append(text[pos:])
    return "".join(parts), cut_pos, cut_total


def mask(text: str, literals: list | None = None) -> str:
    """Comments become spaces and literals same-length words (``L___``), newlines kept: every offset still
    points at the same character, and braces or semicolons inside comments and strings no longer count."""
    def sub(m):
        if m.group("code") is not None:
            return m.group()
        s = m.group()
        if m.group("comment") is not None:
            return re.sub(r"[^\n]", " ", s)
        if literals is not None:
            literals.append((m.start(), m.end(), s))
        return "L" + re.sub(r"[^\n]", "_", s[1:])

    return LEX.sub(sub, text)


class Source:
    """One C++ file: original text, masked text (comments blank, literals replaced by same-length words, so
    every offset still points at the same character) and string literals with their positions."""

    def __init__(self, path: Path, rel: str):
        self.path, self.rel = path, rel
        self.text = path.read_text(encoding="utf-8", errors="ignore")
        spliced, self._cut_pos, self._cut_total = splice(self.text)
        self._starts = [0] + [m.end() for m in re.finditer("\n", self.text)]
        self.literals: list[tuple[int, int, str]] = []
        self.code = mask(spliced, self.literals)
        self._lit_starts = [s for s, _, _ in self.literals]

    def line(self, offset: int) -> int:
        i = bisect_right(self._cut_pos, offset)
        original = offset + (self._cut_total[i - 1] if i else 0)
        return bisect_right(self._starts, original)

    def literal_text(self, start: int, end: int) -> list[str]:
        """Contents of the string literals between two offsets (quotes and prefixes removed)."""
        i = bisect_right(self._lit_starts, start - 1)
        out = []
        while i < len(self.literals) and self.literals[i][0] < end:
            s = self.literals[i][2]
            q = s.find('"')
            if q >= 0 and not s.endswith("'"):
                inner = s[q + 1:-1]
                if q > 0 and s[q - 1] == "R":
                    inner = inner[inner.find("(") + 1:inner.rfind(")")]
                out.append(inner)
            i += 1
        return out


def body_end(text: str, start: int) -> int:
    depth = 0
    for i in range(start, len(text)):
        c = text[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i
    return len(text)


def statements(body: str) -> list[str]:
    depth, start, parts = 0, 1, []
    for i, c in enumerate(body[1:], 1):
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
        elif c == ";" and not depth:
            parts.append(body[start:i + 1])
            start = i + 1
    parts.append(body[start:])
    return parts


def _inert_statement(st: str, wrappers: set) -> bool:
    if EMPTY_RETURN.fullmatch(st) or CONST_RETURN.fullmatch(st) or BARE_THROW.fullmatch(st):
        return True
    call = WRAPPER_RETURN.fullmatch(st)
    return bool(call) and call.group(1) in wrappers


def inert_body(body: str, wrappers: set) -> bool:
    """AnyPS5's "behaviourally empty": only (void) discards and at most one constant return, bare return,
    throw, or return of an inert local wrapper."""
    terminals = 0
    for st in statements(body):
        st = st.strip()
        if not st or DISCARD.fullmatch(st):
            continue
        if terminals or not _inert_statement(st, wrappers):
            return False
        terminals += 1
    return True


def _top_level_split(s: str) -> list[str]:
    depth, start, out = 0, 0, []
    for i, c in enumerate(s):
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
        elif c == "," and depth == 0:
            out.append(s[start:i])
            start = i + 1
    out.append(s[start:])
    return [x.strip() for x in out]


def _param_count(params: str) -> int:
    p = " ".join(params.split())
    if p in ("", "void"):
        return 0
    return len(_top_level_split(p))


def _matching(text: str, i: int, open_c: str, close_c: str) -> int:
    depth = 0
    for j in range(i, len(text)):
        if text[j] == open_c:
            depth += 1
        elif text[j] == close_c:
            depth -= 1
            if depth == 0:
                return j
    return -1


def _int(literal: str) -> int | None:
    m = re.fullmatch(r"(0[xX][0-9a-fA-F]+|\d+)[uUlL]*", literal.strip())
    if not m:
        return None
    return int(m.group(1), 16) if m.group(1).lower().startswith("0x") else int(m.group(1))


def _packet(body: str) -> dict | None:
    """The PM4 packet a body emits when it emits exactly one through Emit(buffer, opcode, {payload}, ...)."""
    emits = [m for m in re.finditer(r"\bEmit\s*\(", body) if not _member(body, m.start())]
    calls = {m.group(1) for m in CALL.finditer(body)}
    if len(emits) != 1 or calls & PACKET_WRITERS:
        return None
    start = emits[0].end() - 1
    end = _matching(body, start, "(", ")")
    if end < 0:
        return None
    args = _top_level_split(body[start + 1:end])
    if len(args) < 3 or not (args[2].startswith("{") and args[2].endswith("}")):
        return None
    inner = args[2][1:-1].strip()
    payload = 0 if not inner else len(_top_level_split(inner))
    return {"opcode": _int(args[1]), "payload": payload}


RETURN_CALL = re.compile(r"return\s+((?:\w+\s*::\s*)*)(\w+)\s*\(")


def _delegate(body: str) -> str | None:
    """The function a body hands its packet to: its last statement returns a call, and nothing before it
    writes to the command buffer (checks only)."""
    sts = [st.strip() for st in statements(body) if st.strip()]
    if not sts:
        return None
    m = RETURN_CALL.match(sts[-1])
    if not m or m.group(2) == "Emit":
        return None
    for st in sts[:-1]:
        names = {c.group(1) for c in CALL.finditer(st)}
        if names & (PACKET_WRITERS | {"Emit"}) or re.match(r"return\b", st):
            return None
    return m.group(2)


def _calls(body: str) -> list[str]:
    out = set()
    for m in CALL.finditer(body):
        name = m.group(1)
        if name in NON_CALLS or _member(body, m.start()):
            continue
        out.add(name)
    return sorted(out)


def _stub_calls(src: Source, text: str, b0: int, b1: int) -> tuple[int, list[str]]:
    """NotImplemented calls in a body: how many name the whole function (``__func__`` or no message) and the
    messages of those that name one unsupported path (a partial implementation names what it lacks)."""
    generic, paths = 0, []
    for m in re.finditer(rf"\b{STUB}\s*\(", text[b0:b1]):
        if QUALIFIED.search(text, b0, b0 + m.start()):
            continue
        a0 = b0 + m.end()
        arg = text[a0:a0 + 200].lstrip()
        if arg.startswith("L_"):
            lit = src.literal_text(a0, a0 + 200)
            paths.append(lit[0][:160] if lit else "")
        else:
            generic += 1
    return generic, paths


def _statement_literals(src: Source, text: str, b0: int, b1: int, start: str) -> list[str]:
    """The string literals of the statements in a body that begin with a pattern (a throw, a log call)."""
    out = []
    for m in re.finditer(start, text[b0:b1]):
        s0 = b0 + m.start()
        end = text.find(";", s0, b1)
        out += [x[:160] for x in src.literal_text(s0, end if end > 0 else b1)]
    return out[:6]


def strip_symbol(name: str) -> str:
    return re.sub(r"_nid_disambig[0-9]+$", "", name.removesuffix("_nid_postfix"))


class Library:
    """One core/libs/prx/<library> directory, scanned with the badge's rule and with the extra facts."""

    def __init__(self, root: Path, path: Path):
        self.name = path.name
        self.done, self.todo, self.inert, self.live = set(), set(), set(), set()
        self.defs: list[dict] = []
        self.helpers: list[dict] = []
        self.aliases: list[dict] = []
        self.asm: list[dict] = []
        self.files = 0
        self.shared_sources = None
        digest = hashlib.sha256()
        for f in sorted(path.rglob("*.cpp")):
            if "tests" in f.relative_to(path).parts:
                continue
            resources.guard("anyps5 scan")
            rel = f.relative_to(root).as_posix()
            src = Source(f, rel)
            digest.update(rel.encode() + b"\0" + src.text.encode("utf-8", "ignore"))
            self.files += 1
            self._scan(src)
        self.todo -= self.done
        self.inert -= self.live
        self.sha256 = digest.hexdigest()
        if not (self.done or self.todo):
            cmake = path / "CMakeLists.txt"
            texts = [(CMAKE_SHARED, cmake.read_text(encoding="utf-8", errors="ignore"))] if cmake.is_file() else []
            texts += [(SOURCE_SHARED, s.read_text(encoding="utf-8", errors="ignore")) for s in sorted(path.glob("*.cpp"))]
            owners = [m[1] for pattern, content in texts for m in pattern.finditer(content)]
            owners = [o for o in owners if o != path.name and (path.parent / o).is_dir()]
            self.shared_sources = owners[0] if owners else None

    def _scan(self, src: Source) -> None:
        text = src.code
        local = []
        for m in LOCAL_FN.finditer(text):
            b0 = m.end() - 1
            b1 = body_end(text, b0)
            local.append((m.group(1), b0, b1, m.start()))
        targets = {}
        for name, b0, b1, _ in local:
            targets.setdefault(name, set()).update(c.group(1) for c in CALL.finditer(text, b0, b1))
        stubs = {STUB}
        while True:
            found = {n for n, t in targets.items() if n not in stubs and t & stubs}
            if not found:
                break
            stubs |= found
        bodies = {name: text[b0:b1] for name, b0, b1, _ in local}
        wrappers = set()
        while True:
            found = {n for n, body in bodies.items() if n not in wrappers and inert_body(body, wrappers)}
            if not found:
                break
            wrappers |= found
        for name, b0, b1, start in local:
            body = text[b0:b1]
            generic, paths = _stub_calls(src, text, b0, b1)
            self.helpers.append({"name": name, "file": src.rel, "line": src.line(start), "calls": _calls(body),
                                 "packet": _packet(body), "delegate": _delegate(body),
                                 "direct_stub": bool(generic or paths), "stub_generic": generic, "stub_paths": paths,
                                 "throws": len(re.findall(r"\bthrow\b", body)),
                                 "messages": [x[:160] for x in src.literal_text(b0, b1)][:6]})
        for m in DEFINITION.finditer(text):
            name = m.group(1)
            if name.endswith(("_nid_no_patch", "_nid_no_patch_cut")):
                continue
            b0 = m.end() - 1
            b1 = body_end(text, b0)
            body = text[b0:b1]
            pending = any(c.group(1) in stubs and not QUALIFIED.search(body, 0, c.start()) for c in CALL.finditer(body))
            line_start = text.rfind("\n", 0, m.start()) + 1
            returns = re.sub(r"^\s*extern\s+L_+\s*", "", text[line_start:m.start()]).strip()
            ret_int = None
            sts = [s.strip() for s in statements(body) if s.strip() and not DISCARD.fullmatch(s.strip())]
            if len(sts) == 1 and INT_RETURN.fullmatch(sts[0]):
                ret_int = _int(INT_RETURN.fullmatch(sts[0]).group(1))
            generic, paths = _stub_calls(src, text, b0, b1)
            rec = {"name": name, "file": src.rel, "line": src.line(m.start()), "end_line": src.line(b1),
                   "pending": pending, "stub_generic": generic, "stub_paths": paths,
                   "throw_messages": _statement_literals(src, text, b0, b1, r"\bthrow\b"),
                   "hit_messages": _statement_literals(src, text, b0, b1, r"\bAPS5_HIT\s*\("), "params": " ".join(m.group(2).split()), "param_count": _param_count(m.group(2)),
                   "returns": " ".join(returns.split()), "calls": _calls(body),
                   "throws": len(re.findall(r"\bthrow\b", body)), "hit": "APS5_HIT" in body,
                   "messages": [x[:160] for x in src.literal_text(b0, b1)][:8],
                   "inert": (not pending) and inert_body(body, wrappers), "constant": ret_int,
                   "packet": _packet(body), "delegate": _delegate(body),
                   "body_sha": hashlib.sha1(body.encode()).hexdigest()[:12]}
            self.defs.append(rec)
            if pending:
                self.todo.add(name)
            else:
                self.done.add(name)
                (self.inert if rec["inert"] else self.live).add(name)
        for m in ALIAS.finditer(text):
            lit = src.literal_text(m.start(), m.end())
            if lit:
                self.aliases.append({"nid": lit[0], "target": m.group(1), "file": src.rel, "line": src.line(m.start())})
        for m in ASM.finditer(text):
            lit = src.literal_text(m.start(), m.end())
            if lit and re.fullmatch(r"[A-Za-z_]\w*", lit[0]):
                self.asm.append({"name": lit[0], "file": src.rel, "line": src.line(m.start())})


# -- technical debt --------------------------------------------------------------------------------
LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
TICKED = re.compile(r"`([A-Za-z_][A-Za-z0-9_]*)`")
TITLE = re.compile(r"\b(?:PPSA|CUSA|NPXS)\d{5}\b")


def read_debt(root: Path) -> list[dict]:
    out = []
    files = [root / "docs" / "dev" / "TechnicalDebt.md"] + sorted((root / "docs" / "dev" / "debt").glob("*.md"))
    for f in files:
        if not f.is_file():
            continue
        rel = f.relative_to(root).as_posix()
        component = "project" if f.name == "TechnicalDebt.md" else f.stem
        section, cur = None, None
        lines = f.read_text(encoding="utf-8", errors="ignore").splitlines()
        for i, line in enumerate(lines, 1):
            if line.startswith("#"):
                cur = None
                if line.startswith("###"):
                    section = line.lstrip("#").strip()
                continue
            if line.startswith("- "):
                cur = {"file": rel, "line": i, "component": component, "section": section, "text": line[2:].strip()}
                out.append(cur)
            elif line.strip() and cur is not None:
                cur["text"] += " " + line.strip()
            elif not line.strip():
                cur = None
    for d in out:
        t = d["text"]
        names = []
        for label, _ in LINK.findall(t):
            names += [x.strip(" `") for x in re.split(r",| and ", label)]
        names += TICKED.findall(t)
        d["names"] = sorted({n for n in names if re.fullmatch(r"[A-Za-z_]\w*", n)})
        d["links"] = sorted({target for _, target in LINK.findall(t) if not target.startswith("http")})
        d["titles"] = sorted(set(TITLE.findall(t)))
        m = re.search(r"Closes when:\s*(.+?)(?:$|(?<=\.)\s)", t)
        d["closes_when"] = m.group(1).strip() if m else None
        d["sha"] = hashlib.sha1(t.encode()).hexdigest()[:12]
    return out


# -- tests and shaders -----------------------------------------------------------------------------
def test_references(root: Path, symbols: set[str]) -> dict[str, list[str]]:
    """Which test files name each symbol (a reference, not a run)."""
    refs: dict[str, list[str]] = {}
    ident = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
    for d in sorted((root / "core").rglob("tests")):
        if not d.is_dir() or "3rdparty" in d.parts:
            continue
        for f in sorted(d.rglob("*")):
            if not f.is_file() or f.suffix not in TEST_EXTS:
                continue
            resources.guard("anyps5 test references")
            rel = f.relative_to(root).as_posix()
            text = f.read_text(encoding="utf-8", errors="ignore")
            for s in set(ident.findall(text)) & symbols:
                refs.setdefault(s, []).append(rel)
    return refs


def _literal_tables(progress_py: Path) -> dict:
    """Read AnyPS5's opcode alias tables as data: top-level literal assignments, never executed."""
    want = {"OPCODE_ALIASES", "OPCODE_VARIANTS", "OPCODE_SENTINELS", "FLAT_SEGMENTS"}
    out = {}
    if not progress_py.is_file():
        return out
    for node in ast.parse(progress_py.read_text(encoding="utf-8", errors="ignore")).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) \
                and node.targets[0].id in want:
            try:
                out[node.targets[0].id] = ast.literal_eval(node.value)
            except ValueError:
                pass
    return out


def read_shader(root: Path) -> dict:
    isa_file = root / "tools" / "rdna_isa.txt"
    rec = root / "core" / "shader" / "recompiler"
    enum_file = rec / "RdnaDecoder" / "include" / "RdnaDecoder" / "RdnaOpcode.hpp"
    if not isa_file.is_file() or not enum_file.is_file():
        return {"available": False}
    isa = {}
    for i, line in enumerate(isa_file.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
        if line and not line.startswith("#"):
            name, encoding = line.split()[:2]
            isa[name] = {"encoding": encoding, "line": i}
    tables = _literal_tables(root / "tools" / "progress.py")
    aliases = tables.get("OPCODE_ALIASES", {})
    variants = tables.get("OPCODE_VARIANTS", {})
    sentinels = set(tables.get("OPCODE_SENTINELS", {"Invalid", "Count", "Unknown", "Unsupported"}))
    flat = tuple(tables.get("FLAT_SEGMENTS", ("GLOBAL_", "SCRATCH_")))
    by_camel = {"".join(p.capitalize() for p in n.split("_")): n for n in isa}
    m = re.search(r"enum class RdnaOpcode[^{]*\{(.*?)\};", enum_file.read_text(encoding="utf-8", errors="ignore"), re.S)
    opcodes = [o for o in re.findall(r"^\s*([A-Z]\w*)\s*[,=]", m.group(1), re.M) if o not in sentinels] if m else []

    def names_of(opcode):
        out = {n for n in variants.get(opcode, ()) if n in isa}
        name = aliases.get(opcode) or by_camel.get(opcode)
        if name in isa:
            out.add(name)
            if name.startswith("FLAT_"):
                out |= {s + name.removeprefix("FLAT_") for s in flat} & set(isa)
        return out

    decoded, extra = set(), []
    for op in opcodes:
        got = names_of(op)
        decoded |= got
        if (aliases.get(op) or by_camel.get(op)) not in isa:
            extra.append(op)
    translated = set()
    for f in sorted((rec / "Translation").rglob("*.cpp")):
        for op in set(re.findall(r"RdnaOpcode::(\w+)", f.read_text(encoding="utf-8", errors="ignore"))):
            translated |= names_of(op)
    executed = set()
    exe = root / "core" / "libs" / "prx" / "libSceAgcDriver" / "tests" / "execution"
    mnemonic = re.compile(r"\b((?:s|v|ds|buffer|tbuffer|image|global|flat|scratch)_[a-z0-9_]+|exp)\b")
    for f in sorted(exe.glob("*.cpp")) if exe.is_dir() else []:
        executed |= {x.upper() for x in mnemonic.findall(f.read_text(encoding="utf-8", errors="ignore"))} & set(isa)
    return {"available": True, "isa": isa, "opcodes": len(opcodes), "decoded": sorted(decoded),
            "translated": sorted(translated), "executed": sorted(executed), "extra": extra,
            "tables_read": sorted(tables)}


# -- the whole checkout ----------------------------------------------------------------------------
class Scan:
    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser().resolve()
        prx = self.root / "core" / "libs" / "prx"
        if not prx.is_dir():
            raise ValueError(f"{self.root} has no core/libs/prx: not an AnyPS5 checkout")
        self.libraries = [Library(self.root, p) for p in sorted(prx.iterdir()) if p.is_dir()]
        self.debt = read_debt(self.root)
        symbols = {strip_symbol(d["name"]) for lib in self.libraries for d in lib.defs} | \
                  {d["name"] for lib in self.libraries for d in lib.defs} | \
                  {a["name"] for lib in self.libraries for a in lib.asm}
        self.tests = test_references(self.root, symbols)
        self.shader = read_shader(self.root)
        h = hashlib.sha256()
        for lib in self.libraries:
            h.update(lib.name.encode() + b"\0" + lib.sha256.encode())
        for d in self.debt:
            h.update(d["sha"].encode())
        self.sha256 = h.hexdigest()

    def badge(self) -> dict:
        """The libraries badge, computed with AnyPS5's own rule."""
        done = sum(len(lib.done) for lib in self.libraries)
        total = done + sum(len(lib.todo) for lib in self.libraries)
        return {"done": done, "total": total, "percent": round(100 * done / total, 2) if total else 0}

    def shader_badge(self) -> dict:
        if not self.shader.get("available"):
            return {"available": False}
        done, total = len(self.shader["decoded"]), len(self.shader["isa"])
        return {"done": done, "total": total, "percent": round(100 * done / total, 2) if total else 0}


def parity(scan: Scan, progress: dict) -> dict:
    """Compare the reproduced counts with a progress.json AnyPS5's own tool wrote: every library's
    implemented and pending names must be the same sets."""
    theirs = {g["name"]: g for g in progress.get("libraries", {}).get("groups", [])}
    mismatches = []
    for lib in scan.libraries:
        g = theirs.get(lib.name)
        if g is None:
            mismatches.append({"library": lib.name, "problem": "missing in progress.json"})
            continue
        for key, ours in (("done_names", lib.done), ("todo_names", lib.todo), ("inert_names", lib.inert)):
            if set(g.get(key, [])) != ours:
                mismatches.append({"library": lib.name, "field": key,
                                   "only_ours": sorted(ours - set(g.get(key, [])))[:5],
                                   "only_theirs": sorted(set(g.get(key, [])) - ours)[:5]})
        if g.get("shared_sources") != lib.shared_sources:
            mismatches.append({"library": lib.name, "field": "shared_sources",
                               "ours": lib.shared_sources, "theirs": g.get("shared_sources")})
    for name in set(theirs) - {lib.name for lib in scan.libraries}:
        mismatches.append({"library": name, "problem": "missing in the scan"})
    lt = progress.get("libraries", {})
    st = progress.get("shaders", {})
    ours, sh = scan.badge(), scan.shader_badge()
    return {"libraries": {"ours": [ours["done"], ours["total"]], "theirs": [lt.get("done"), lt.get("total")]},
            "shaders": {"ours": [sh.get("done"), sh.get("total")], "theirs": [st.get("done"), st.get("total")]},
            "mismatches": mismatches,
            "agree": not mismatches and [ours["done"], ours["total"]] == [lt.get("done"), lt.get("total")]
            and [sh.get("done"), sh.get("total")] == [st.get("done"), st.get("total")]}


__all__ = ["Library", "Scan", "Source", "mask", "parity", "read_debt", "read_shader", "strip_symbol"]
