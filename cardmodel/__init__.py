"""cardmodel — a self-contained card model: every structure is a card.

The L25 registry surface over the default store (model cards + the nearest
project's ``.cardmodel/cards``):

    import cardmodel
    cardmodel.ALL            # {"category/name": Card}
    cardmodel.get("op/ADD")  # or a unique bare name: cardmodel.get("ADD")
    cardmodel.all_names()
"""
from __future__ import annotations

__version__ = "0.1.0"

from .kernel import Card, Store, default_store, open_store  # noqa: E402


def get(name: str):
    return default_store().get(name)


def all_names() -> list[str]:
    return default_store().all_names()


def __getattr__(attr: str):
    if attr == "ALL":
        return default_store().ALL
    raise AttributeError(attr)


__all__ = ["ALL", "get", "all_names", "Card", "Store", "default_store", "open_store", "__version__"]
