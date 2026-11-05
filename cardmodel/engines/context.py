"""context — one object carrying the store and the derived tables engines share."""
from __future__ import annotations

import json
import os
from functools import cached_property
from pathlib import Path

from ..kernel import paths
from ..kernel.store import Store, default_store
from . import probes
from .codegen import carry_map, map_gap, resolve_language
from .ir import op_table


class Ctx:
    def __init__(self, store: Store | None = None):
        self.store = store or default_store()

    @cached_property
    def ops(self):
        return op_table(self.store)

    @property
    def state_root(self) -> Path:
        d = paths.state_dir(self.store.layer_root(self.store.writable_layer()))
        d.mkdir(parents=True, exist_ok=True)
        return d

    def language(self, name: str) -> dict:
        return resolve_language(self.store, name)

    def codegen_languages(self) -> list[str]:
        out = []
        for card in self.store.cards("language"):
            if card.get("codegen") is not None:
                out.append(card.name)
        return sorted(out, key=lambda n: (self.store.get(f"language/{n}").get("tier", 1), n))

    def carry_map(self, lang: str) -> dict[str, dict[str, str | None]]:
        """The language as a carry map on the atoms at every rank (codegen.carry_map), computed once per language:
        conformance reads its gap cells from it, translate and matrix refuse a term from its content before trying
        to emit it."""
        cache = self.__dict__.setdefault("_carry_maps", {})
        if lang not in cache:
            cache[lang] = carry_map(self.store, self.ops, lang)
        return cache[lang]

    def language_gap(self, lang: str) -> set[str]:
        """The atoms ``lang`` has no emit template for (codegen.map_gap of its carry map)."""
        cache = self.__dict__.setdefault("_language_gaps", {})
        if lang not in cache:
            cache[lang] = map_gap(self.carry_map(lang))
        return cache[lang]

    def available(self, lang: str) -> tuple[bool, str]:
        return probes.probe(self.language(lang).get("probe"))

    def save_state(self, name: str, data) -> Path:
        p = self.state_root / f"{name}.json"
        tmp = p.with_name(f".{p.name}.tmp{os.getpid()}")
        tmp.write_text(json.dumps(data, indent=1, sort_keys=True, default=str), encoding="utf-8")
        os.replace(tmp, p)
        return p

    def load_state(self, name: str, default=None):
        p = self.state_root / f"{name}.json"
        if not p.is_file():
            return default
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"state file {p} is corrupt: {exc}") from exc
