"""types — card types are cards (schema-as-data).

``cards/card_type/<type>/card.json`` holds a JSON Schema in ``schema`` and
says which registries it governs in ``applies_to`` ("*" = every card).
A registry's ``_category.json`` may also name its type in ``card_type``.
``card_type/card`` is the universal contract; every card validates against
it plus every type that applies to its registry.

Types are versioned like any card (metadata.version). A card may pin the
type version it was written for in ``metadata.type_version``; a different
MAJOR version is reported as an error (the type changed incompatibly).

Kernel checks beyond the schemas:
  * ``category`` equals the registry name (or one of the registry's
    ``category_aliases``)
  * directory name equals card name (warning only: vendored cards differ)
"""
from __future__ import annotations

from .card import STATUS_VALUES, Card
from .schema import validate
from .store import Store

UNIVERSAL = "card"


def type_cards(store: Store) -> dict[str, Card]:
    v = store.registry("card_type")
    return dict(v.ALL) if v else {}


def types_for(store: Store, registry: str) -> list[Card]:
    types = type_cards(store)
    view = store.registry(registry)
    named = (view.meta.get("card_type") if view else None) or []
    named = [named] if isinstance(named, str) else list(named)
    out = []
    for t in types.values():
        applies = t.get("applies_to") or []
        if "*" in applies or registry in applies or t.name in named:
            out.append(t)
    out.sort(key=lambda t: (t.name != UNIVERSAL, t.name))
    return out


def _major(v: str | None) -> str | None:
    return v.split(".")[0] if isinstance(v, str) and v.count(".") == 2 else None


def validate_card(card: Card, store: Store, types: list[Card] | None = None) -> tuple[list[str], list[str]]:
    """Return (errors, warnings) for one card."""
    errors: list[str] = []
    warnings: list[str] = []
    reg = card.registry or card.get("category", "")
    for t in types if types is not None else types_for(store, reg):
        schema = t.get("schema")
        if not isinstance(schema, dict):
            continue
        for e in validate(dict(card), schema):
            errors.append(f"[{t.name}] {e}")
        pinned = (card.metadata.get("type_versions") or {}).get(t.name)
        if pinned and _major(pinned) != _major((t.metadata or {}).get("version") or t.get("version")):
            errors.append(f"[{t.name}] written for type version {pinned}, type is now "
                          f"{(t.metadata or {}).get('version') or t.get('version')}")
    view = store.registry(reg)
    aliases = set((view.meta.get("category_aliases") if view else None) or [])
    if card.get("category") and card["category"] != reg and card["category"] not in aliases:
        errors.append(f"category {card['category']!r} does not match registry {reg!r}")
    status = card.get("status")
    allowed = (view.meta.get("status_values") if view else None) or STATUS_VALUES
    if status is not None and status not in allowed:
        errors.append(f"status {status!r} not in {list(allowed)} (a registry may declare its own status_values)")
    if card.path is not None and card.path.name != card.name:
        warnings.append(f"directory {card.path.name!r} differs from name {card.name!r}")
    return errors, warnings


def validate_store(store: Store) -> dict[str, dict]:
    """{qualified: {"errors": [...], "warnings": [...]}} for every card with findings."""
    out: dict[str, dict] = {}
    for reg in store.categories():
        types = types_for(store, reg)
        for card in store.cards(reg):
            errs, warns = validate_card(card, store, types)
            if errs or warns:
                out[card.qualified] = {"errors": errs, "warnings": warns}
    return out


def closure(store: Store, include_external: bool = False) -> list[str]:
    """L45 closure under definition: every depends_on name resolves (qualified or unique bare name).

    Registries whose _category.json says ``"references": "external"`` (vendored snapshots whose
    references point into a source corpus that was not copied) are skipped unless ``include_external``."""
    problems = []
    names = store._name_index()
    external = {n for n, v in store.views.items() if v.meta.get("references") == "external"}
    for q, card in store.ALL.items():
        if card.registry in external and not include_external:
            continue
        for dep in card.depends_on:
            if "/" in dep:
                if store.get(dep) is None:
                    problems.append(f"{q}: depends_on {dep!r} does not resolve")
            elif dep not in names:
                problems.append(f"{q}: depends_on {dep!r} does not resolve")
    return problems
