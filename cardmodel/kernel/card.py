"""card — the universal card record.

A card is a JSON object. The contract (cards/card_type/card) names a small
set of fields every engine understands; everything else is kept verbatim
and ignored by engines that do not know it (the infinite-extension
guarantee from the hub's CARD_MODEL.md / L25):

  name        unique within its registry                     (required)
  category    the registry it belongs to                     (required)
  tier        0 = foundation; or depends_on: [names]
  cost        scalar or structured cost, comparable within a registry
  cost_vector {dimension: number} with dimension_direction lower|higher
  forms       equivalent implementations (redefinitions): name, cost,
              domain(s), lang, code|file|exec, probe, runnable, notes
  variants    filename -> content or pointer (Pheros variant_contract);
              files next to card.json are variants too
  body        the payload
  metadata    free extension dict
  status      healthy | suspect | broken | quarantined

``Card`` subclasses ``dict`` so a card round-trips through JSON unchanged;
load-time facts (directory, registry, layer) live in attributes, not keys.
"""
from __future__ import annotations

from pathlib import Path

CARD_FILE = "card.json"
STATUS_VALUES = ("healthy", "suspect", "broken", "quarantined")


class Card(dict):
    __slots__ = ("path", "registry", "layer", "source")

    def __init__(self, data=None, *, path=None, registry=None, layer=None, source="memory"):
        super().__init__(data or {})
        self.path = Path(path) if path else None
        self.registry = registry
        self.layer = layer
        self.source = source

    # -- universal contract ------------------------------------------------
    @property
    def name(self) -> str:
        return self.get("name", "")

    @property
    def category(self) -> str:
        return self.get("category") or self.registry or ""

    @property
    def qualified(self) -> str:
        return f"{self.registry or self.category}/{self.name}"

    @property
    def tier(self):
        return self.get("tier")

    @property
    def depends_on(self) -> list[str]:
        out = []
        for key in ("depends_on", "depends"):
            for d in self.get(key) or []:
                if isinstance(d, str) and d not in out:
                    out.append(d)
        return out

    @property
    def forms(self) -> list[dict]:
        return [f for f in (self.get("forms") or []) if isinstance(f, dict)]

    def form(self, name: str) -> dict | None:
        return next((f for f in self.forms if f.get("name") == name), None)

    @property
    def cost(self):
        return self.get("cost")

    @property
    def cost_vector(self) -> dict:
        return dict(self.get("cost_vector") or {})

    @property
    def metadata(self) -> dict:
        m = self.get("metadata")
        return m if isinstance(m, dict) else {}

    @property
    def variants(self) -> dict:
        v = self.get("variants")
        return v if isinstance(v, dict) else {}

    @property
    def body(self):
        return self.get("body")

    @property
    def status(self) -> str:
        return self.get("status", "healthy")

    # -- variant files (variant_contract: files beside card.json) ----------
    def variant_files(self) -> dict[str, Path]:
        if not self.path or not self.path.is_dir():
            return {}
        return {p.name: p for p in sorted(self.path.iterdir())
                if p.is_file() and p.name != CARD_FILE and not p.name.startswith(".")}

    def read_variant(self, filename: str) -> str | None:
        files = self.variant_files()
        if filename in files:
            return files[filename].read_text(encoding="utf-8")
        v = self.variants.get(filename)
        return v if isinstance(v, str) else None

    def copy(self) -> "Card":
        return Card(dict(self), path=self.path, registry=self.registry, layer=self.layer, source=self.source)

    def __repr__(self) -> str:
        return f"Card({self.qualified!r})"
