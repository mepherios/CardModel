"""registry — a directory is a registry (Pheros registry_contract).

A registry is any directory holding ``_category.json``. Its cards are the
immediate subdirectories holding ``card.json`` plus, optionally, the lines
of ``_pack*.jsonl`` files (one card per line: the packed storage form used
for bulk vendored data). The filesystem is the source of truth; kernel/index.py keeps\nan index over it so one lookup reads one card (a stale index is rebuilt, never trusted).
A directory card wins over a packed card of the same name.

Every registry exposes the L25 surface: ``ALL`` (name -> Card), ``get``,
``all_names``. Loading is lazy and errors are collected, not swallowed
(L36): ``errors`` lists every malformed file and ``strict=True`` raises.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .card import CARD_FILE, Card
from .index import LOCK, fingerprint, get_index

CATEGORY_FILE = "_category.json"
PACK_GLOB = "_pack*.jsonl"


class CardLoadError(ValueError):
    pass


class Registry:
    def __init__(self, path: Path, layer: str = "model", strict: bool = False):
        self.path = Path(path)
        self.layer = layer
        self.strict = strict
        meta_file = self.path / CATEGORY_FILE
        try:
            self.meta = json.loads(meta_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CardLoadError(f"{meta_file}: {type(exc).__name__}: {exc}") from exc
        if not isinstance(self.meta, dict):
            raise CardLoadError(f"{meta_file}: expected a JSON object")
        self.name = self.meta.get("name") or self.path.name
        self._errors: list[str] = []
        self._cards: dict[str, Card] | None = None
        self._one: dict[str, Card | None] = {}          # cards read one at a time through the index
        self._indexed: bool | None = None               # None: not checked yet

    def _fail(self, msg: str) -> None:
        if self.strict:
            raise CardLoadError(msg)
        self._errors.append(msg)

    @property
    def errors(self) -> list[str]:
        with LOCK:
            if self._cards is None and self._index_ready():
                return self._index_errors
            return self._errors

        # -- the index (kernel/index.py): one card costs one card ------------------
    def _index_ready(self) -> bool:
        """True when the index holds this registry's current contents (indexing it now if it was stale)."""
        with LOCK:
            if self._indexed is None:
                self._indexed = False
                idx = None if self.strict else get_index()
                if idx is not None:
                    try:
                        key = str(self.path.resolve())
                        fp = fingerprint(self.path, CARD_FILE, CATEGORY_FILE, PACK_GLOB)
                        errs = idx.fresh(key, fp)
                        if errs is None:
                            rows: list[tuple[str, str, str]] = []
                            cards = self._load(rows)
                            self._cards = cards
                            errs = list(self._errors)
                            idx.put(key, fp, rows, errs)
                        self._index_errors = errs
                        self._key = key
                        self._indexed = True
                    except sqlite3.Error:
                        self._indexed = False
            return self._indexed

    def _read_one(self, name: str) -> Card | None:
        e = get_index().entry(self._key, name)
        if e is None:
            return None
        source, ref = e
        if source == "dir":
            sub = self.path / ref
            data = json.loads((sub / CARD_FILE).read_text(encoding="utf-8"))
            card = Card(data, path=sub, registry=self.name, layer=self.layer, source="dir")
        else:
            with open(self.path / source[len("pack:"):], "rb") as f:
                f.seek(int(ref))
                data = json.loads(f.readline().decode("utf-8"))
            card = Card(data, registry=self.name, layer=self.layer, source=source)
        if not isinstance(data, dict) or data.get("name") != name:
            raise ValueError("index entry out of date")
        return card

    # -- reading the files -----------------------------------------------------
    def _load(self, rows: list | None = None) -> dict[str, Card]:
        """Read every card. ``rows``, when given, receives (name, source, ref) per card, in name order."""
        cards: dict[str, Card] = {}
        where: dict[str, tuple[str, str]] = {}
        for pack in sorted(self.path.glob(PACK_GLOB)):
            source = f"pack:{pack.name}"
            with open(pack, "rb") as fh:
                offset = 0
                for i, raw in enumerate(fh, 1):
                    at, offset = offset, offset + len(raw)
                    line = raw.decode("utf-8", errors="replace")
                    if not line.strip():
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError as exc:
                        self._fail(f"{pack}:{i}: {exc}")
                        continue
                    if not isinstance(data, dict) or not data.get("name"):
                        self._fail(f"{pack}:{i}: card without a name")
                        continue
                    cards[data["name"]] = Card(data, registry=self.name, layer=self.layer, source=source)
                    where[data["name"]] = (source, str(at))
        for sub in sorted(self.path.iterdir()):
            if not sub.is_dir() or sub.name.startswith(("_", ".")):
                continue
            f = sub / CARD_FILE
            if not f.is_file():
                continue
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                self._fail(f"{f}: {type(exc).__name__}: {exc}")
                continue
            if not isinstance(data, dict) or not data.get("name"):
                self._fail(f"{f}: card without a name")
                continue
            prev = cards.get(data["name"])
            if prev is not None and prev.source == "dir":
                self._fail(f"{f}: duplicate card name {data['name']!r} (also {prev.path})")
                continue
            cards[data["name"]] = Card(data, path=sub, registry=self.name, layer=self.layer, source="dir")
            where[data["name"]] = ("dir", sub.name)
        if rows is not None:
            rows.extend((n, *where[n]) for n in cards)
        return cards

    @property
    def ALL(self) -> dict[str, Card]:
        with LOCK:
            if self._cards is None:
                self._errors = []
                cards = self._load()
                for n, c in self._one.items():          # a card already handed out stays the same object
                    if c is not None and n in cards:
                        cards[n] = c
                self._cards = cards
            return self._cards

    def get(self, name: str) -> Card | None:
        with LOCK:
            if self._cards is None and self._index_ready():
                if name not in self._one:
                    try:
                        self._one[name] = self._read_one(name)
                    except (OSError, ValueError, sqlite3.Error):
                        self._indexed = False              # the files moved under us: read them all
                        return self.ALL.get(name)
                return self._one[name]
            return self.ALL.get(name)

    def all_names(self) -> list[str]:
        with LOCK:
            if self._cards is None and self._index_ready():
                return get_index().names(self._key)
            return list(self.ALL)

    def invalidate(self) -> None:
        with LOCK:
            self._cards = None
            self._one = {}
            self._indexed = None

    def __len__(self) -> int:
        with LOCK:
            if self._cards is None and self._index_ready():
                return get_index().count(self._key)
            return len(self.ALL)

    def __iter__(self):
        return iter(self.ALL.values())

    def __repr__(self) -> str:
        return f"Registry({self.name!r}, layer={self.layer!r}, path={str(self.path)!r})"


class View:
    """One registry name merged across layers (model < project): later layers override by name."""

    def __init__(self, name: str, regs: list[Registry]):
        self.name = name
        self.regs = regs

    @property
    def meta(self) -> dict:
        out: dict = {}
        for r in self.regs:
            out.update(r.meta)
        return out

    @property
    def ALL(self) -> dict[str, Card]:
        out: dict[str, Card] = {}
        for r in self.regs:
            out.update(r.ALL)
        return out

    def get(self, name: str) -> Card | None:
        for r in reversed(self.regs):
            c = r.get(name)
            if c is not None:
                return c
        return None

    def all_names(self) -> list[str]:
        if len(self.regs) == 1:
            return self.regs[0].all_names()
        out: dict[str, None] = {}
        for r in self.regs:
            out.update(dict.fromkeys(r.all_names()))
        return list(out)

    @property
    def errors(self) -> list[str]:
        return [e for r in self.regs for e in r.errors]

    def __len__(self) -> int:
        return len(self.regs[0]) if len(self.regs) == 1 else len(self.all_names())

    def __iter__(self):
        return iter(self.ALL.values())
