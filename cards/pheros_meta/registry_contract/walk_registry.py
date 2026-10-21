"""walk_registry.py — Python reference implementation of the registry walk.

One variant. The contract is: 'every immediate subdirectory of a
category directory that contains a card.json is a card in that
category.' Any language can implement the same walk.
"""
from pathlib import Path
import json


def walk(category_path: Path) -> list[dict]:
    """Yield every card.json in the immediate subdirectories of category_path."""
    cards = []
    if not category_path.is_dir():
        return cards
    for sub in sorted(category_path.iterdir()):
        if not sub.is_dir():
            continue
        card_file = sub / "card.json"
        if not card_file.exists():
            continue
        try:
            cards.append(json.loads(card_file.read_text(encoding="utf-8")))
        except Exception as e:
            print(f"  ! malformed card.json at {card_file}: {e}")
    return cards


def walk_all(cards_root: Path) -> dict[str, list[dict]]:
    """Walk every category under cards_root. Returns {category_name: [card, ...]}."""
    out = {}
    for sub in sorted(cards_root.iterdir()):
        if sub.is_dir() and (sub / "_category.json").exists():
            out[sub.name] = walk(sub)
    return out
