"""store — every registry the program can see, layered.

Layers, lowest priority first:
  model    <home>/cards                (built-in, versioned in this repository)
  project  <project>/.cardmodel/cards  (cards of the program being developed)

A registry name present in several layers is one merged ``View``; a card
in a higher layer overrides the same name below it. Registries may nest
(any directory with ``_category.json``); directories starting with ``_`` or
``.`` (``_versions``, ``_locks``) are never registries.

The store exposes the L25 surface over all registries:
  ALL            "category/name" -> Card
  get(name)      "category/name" or a bare name that is unique
  all_names()    qualified names
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from . import paths, versioning
from .card import CARD_FILE, Card
from .registry import CATEGORY_FILE, CardLoadError, Registry, View


class AmbiguousName(KeyError):
    pass


def _walk_registries(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        rel = Path(dirpath).relative_to(root)
        if any(p.startswith(("_", ".")) for p in rel.parts):
            dirnames[:] = []
            continue
        if CARD_FILE in filenames and CATEGORY_FILE not in filenames:
            dirnames[:] = []  # a card directory: its subfolders (tests/, examples/) are not registries
            continue
        dirnames[:] = sorted(d for d in dirnames if not d.startswith(("_", ".")))
        if CATEGORY_FILE in filenames:
            yield Path(dirpath)


class Store:
    def __init__(self, layers: list[tuple[str, Path]], strict: bool = False, readonly: set[str] | None = None):
        self.layers = [(name, Path(p)) for name, p in layers]
        self.strict = strict
        self.readonly = set(readonly or ())
        self._views: dict[str, View] | None = None
        self._index: dict[str, list[str]] | None = None
        self.errors: list[str] = []

    # -- discovery ---------------------------------------------------------
    def _discover(self) -> dict[str, View]:
        regs: dict[str, list[Registry]] = {}
        for layer, root in self.layers:
            if not root.is_dir():
                continue
            seen: dict[str, Path] = {}
            for d in _walk_registries(root):
                try:
                    reg = Registry(d, layer=layer, strict=self.strict)
                except CardLoadError as exc:
                    if self.strict:
                        raise
                    self.errors.append(str(exc))
                    continue
                if reg.name in seen:
                    msg = f"registry name {reg.name!r} defined twice in layer {layer}: {seen[reg.name]} and {d}"
                    if self.strict:
                        raise CardLoadError(msg)
                    self.errors.append(msg)
                    continue
                seen[reg.name] = d
                regs.setdefault(reg.name, []).append(reg)
        return {name: View(name, rs) for name, rs in sorted(regs.items())}

    @property
    def views(self) -> dict[str, View]:
        if self._views is None:
            self._views = self._discover()
        return self._views

    def invalidate(self) -> None:
        self._views = None
        self._index = None

    def registry(self, name: str) -> View | None:
        return self.views.get(name)

    def categories(self) -> list[str]:
        return list(self.views)

    def cards(self, category: str) -> list[Card]:
        v = self.registry(category)
        return list(v.ALL.values()) if v else []

    # -- L25 surface ---------------------------------------------------------
    @property
    def ALL(self) -> dict[str, Card]:
        out: dict[str, Card] = {}
        for v in self.views.values():
            for c in v.ALL.values():
                out[f"{v.name}/{c.name}"] = c
        return out

    def _name_index(self) -> dict[str, list[str]]:
        if self._index is None:
            idx: dict[str, list[str]] = {}
            for v in self.views.values():
                for n in v.ALL:
                    idx.setdefault(n, []).append(v.name)
            self._index = idx
        return self._index

    def get(self, name: str) -> Card | None:
        if "/" in name:
            cat, _, short = name.rpartition("/")
            v = self.registry(cat)
            return v.get(short) if v else None
        cats = self._name_index().get(name, [])
        if len(cats) > 1:
            raise AmbiguousName(f"{name!r} is in {len(cats)} registries: {', '.join(cats)} -- use category/name")
        return self.views[cats[0]].get(name) if cats else None

    def all_names(self) -> list[str]:
        return list(self.ALL)

    def load_errors(self) -> list[str]:
        out = list(self.errors)
        for v in self.views.values():
            out += v.errors
        return out

    # -- writing -------------------------------------------------------------
    def writable_layer(self) -> str:
        for name, _ in reversed(self.layers):
            if name not in self.readonly:
                return name
        raise PermissionError("every layer of this store is read-only")

    def layer_root(self, layer: str | None = None) -> Path:
        layer = layer or self.writable_layer()
        if layer in self.readonly:
            raise PermissionError(f"layer {layer!r} is read-only (an --cards tree, or the self layer outside a "
                                  "self-run)")
        for name, root in self.layers:
            if name == layer:
                return root
        raise KeyError(f"no layer {layer!r} (have {[n for n, _ in self.layers]})")

    def ensure_registry(self, category: str, layer: str | None = None, description: str = "",
                        **meta) -> Path:
        root = self.layer_root(layer)
        v = self.registry(category)
        if v:
            for r in v.regs:
                if r.path.is_relative_to(root):
                    return r.path
        d = root / category
        d.mkdir(parents=True, exist_ok=True)
        f = d / CATEGORY_FILE
        if not f.exists():
            data = {"name": category, "description": description or f"Cards of category {category}.",
                    "tier": meta.pop("tier", 1), "defined_by": meta.pop("defined_by", "cardmodel")}
            data.update(meta)
            f.write_text(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
        self.invalidate()
        return d

    def save_pack(self, category: str, pack: str, cards: list[dict], layer: str | None = None,
                  description: str = "") -> Path:
        """Write bulk cards as one ``_pack_<pack>.jsonl`` (sorted, one card per line), replacing that pack whole.

        Packs hold regenerated bulk data (imported theorems, discovered laws, facts): the pack is the unit of
        change, so it is rewritten, not versioned card by card (directory cards keep CM14 versioning)."""
        reg = self.ensure_registry(category, layer, description=description)
        out = reg / f"_pack_{pack}.jsonl"
        lines = sorted(json.dumps({**c, "category": category}, sort_keys=True, ensure_ascii=False, default=str)
                       for c in cards)
        tmp = out.with_name(f".{out.name}.tmp")
        tmp.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        tmp.replace(out)
        self.invalidate()
        return out

    def save(self, card: dict, layer: str | None = None, category: str | None = None) -> tuple[Card, bool]:
        """Create or update a card directory (with versioning). Returns (card, changed)."""
        category = category or card.get("category")
        if not category or not card.get("name"):
            raise ValueError("a card needs name and category")
        data = dict(card)
        data.setdefault("category", category)
        target = layer or self.writable_layer()
        base = self.get(f"{category}/{data['name']}")
        base_dict = dict(base) if base is not None and base.layer != target else None
        reg_dir = self.ensure_registry(category, layer)
        card_dir = reg_dir / data["name"]
        written, changed = versioning.save(card_dir, data, self.layer_root(layer), base=base_dict,
                                           base_layer=base.layer if base_dict is not None else None)
        self.invalidate()
        return Card(written, path=card_dir, registry=category, layer=layer or self.writable_layer(), source="dir"), changed


def open_store(project: Path | str | None | bool = True, strict: bool = False,
               home_cards: Path | None = None, extra: list[str | Path] | None = None,
               include_self: bool = False) -> Store:
    """project=True: discover from cwd; a path: use it; False/None: model layer only.

    ``extra``: other card trees (any directory of registries, e.g. another program's cards/) loaded
    READ-ONLY between the model and the project; nothing is ever written into them.
    ``include_self``: also the self layer (what the model's own cycles learned, engines/selfrun.py), READ-ONLY,
    above the model and the extras and below the project; only the self-run writes it."""
    layers: list[tuple[str, Path]] = [("model", Path(home_cards) if home_cards else paths.model_cards())]
    readonly = set()
    for i, e in enumerate(extra or []):
        layers.append((f"extra{i}", Path(e).expanduser().resolve()))
        readonly.add(f"extra{i}")
    if include_self and paths.self_cards().is_dir():
        layers.append(("self", paths.self_cards()))
        readonly.add("self")
    proj: Path | None = None
    if project is True:
        proj = paths.find_project()
    elif project:
        p = Path(project).resolve()
        proj = p if p.name == paths.PROJECT_DIR else p / paths.PROJECT_DIR
    if proj is not None:
        layers.append(("project", proj / "cards"))
    return Store(layers, strict=strict, readonly=readonly)


_DEFAULT: Store | None = None


def default_store() -> Store:
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = open_store()
    return _DEFAULT


def reset_default_store() -> None:
    global _DEFAULT
    _DEFAULT = None
