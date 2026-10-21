"""registry — a directory is a registry (Pheros registry_contract).

A registry is any directory holding ``_category.json``. Its cards are the
immediate subdirectories holding ``card.json`` plus, optionally, the lines
of ``_pack*.jsonl`` files (one card per line: the packed storage form used
for bulk vendored data). There is no index: the filesystem is the index.
A directory card wins over a packed card of the same name.

Every registry exposes the L25 surface: ``ALL`` (name -> Card), ``get``,
``all_names``. Loading is lazy and errors are collected, not swallowed
(L36): ``errors`` lists every malformed file and ``strict=True`` raises.
"""
from __future__ import annotations

import json
from pathlib import Path

from .card import CARD_FILE, Card

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
        self.errors: list[str] = []
        self._cards: dict[str, Card] | None = None

    def _fail(self, msg: str) -> None:
        if self.strict:
            raise CardLoadError(msg)
        self.errors.append(msg)

    def _load(self) -> dict[str, Card]:
        cards: dict[str, Card] = {}
        for pack in sorted(self.path.glob(PACK_GLOB)):
            for i, line in enumerate(pack.read_text(encoding="utf-8").splitlines(), 1):
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
                cards[data["name"]] = Card(data, registry=self.name, layer=self.layer, source=f"pack:{pack.name}")
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
        return cards

    @property
    def ALL(self) -> dict[str, Card]:
        if self._cards is None:
            self._cards = self._load()
        return self._cards

    def get(self, name: str) -> Card | None:
        return self.ALL.get(name)

    def all_names(self) -> list[str]:
        return list(self.ALL)

    def invalidate(self) -> None:
        self._cards = None

    def __len__(self) -> int:
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
        return list(self.ALL)

    @property
    def errors(self) -> list[str]:
        return [e for r in self.regs for e in r.errors]

    def __len__(self) -> int:
        return len(self.ALL)

    def __iter__(self):
        return iter(self.ALL.values())
