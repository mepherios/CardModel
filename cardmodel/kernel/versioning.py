"""versioning — the card_versioning protocol (ported from Pheros _meta/card_versioning).

Every save of an existing card that changes it:
  1. archives the previous bytes to <cards root>/_versions/<category>/<name>/<version>__<hash12>.json
     and re-reads the archive to verify it before anything is overwritten (L35);
  2. bumps metadata.version and records metadata.previous_content_hash.

Bump rule (adapted, L22 reasoned preference): MAJOR = a field removed or
retyped (breaks consumers); MINOR = a field added or a semantic field
changed (adding a field never breaks a consumer, because unknown fields are
ignored); PATCH = anything else (metadata, tags, wording outside SEMANTIC).
Pheros counted "field added" as MAJOR; reconsider if a consumer ever
depends on the absence of a field.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from .canon import card_hash, dumps_card

SEMANTIC = {"statement", "rationale", "forms", "body", "schema", "source_form", "target_form",
            "condition", "semantics", "signature", "vectors", "examples", "domain", "code", "ir",
            "lhs", "rhs", "applies_to", "detect", "equivalence", "generators"}
BOOKKEEPING = ("version", "previous_content_hash", "version_bump_reason", "version_base_layer")


def _strip(card: dict) -> dict:
    c = dict(card)
    meta = dict(c.get("metadata") or {})
    for k in BOOKKEEPING:
        meta.pop(k, None)
    if meta:
        c["metadata"] = meta
    else:
        c.pop("metadata", None)
    return c


def _numeric(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def bump_kind(old: dict, new: dict) -> str:
    o, n = _strip(old), _strip(new)
    removed = set(o) - set(n)
    retyped = {k for k in set(o) & set(n)
               if type(o[k]) is not type(n[k]) and not (_numeric(o[k]) and _numeric(n[k]))}
    if removed or retyped:
        return "major"
    if set(n) - set(o) or any(o[k] != n[k] for k in SEMANTIC & set(o) & set(n)):
        return "minor"
    return "patch"


def next_version(version: str, kind: str) -> str:
    try:
        major, minor, patch = (int(x) for x in version.split("."))
    except ValueError:
        major, minor, patch = 1, 0, 0
    if kind == "major":
        return f"{major + 1}.0.0"
    if kind == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp{os.getpid()}")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def save(card_dir: Path, card: dict, cards_root: Path, base: dict | None = None,
         base_layer: str | None = None) -> tuple[dict, bool]:
    """Write card.json with versioning. Returns (written card, changed?).

    ``base`` is the same card in a lower layer (e.g. the model card a project overrides): the new
    file then continues that card's version line instead of restarting at 1.0.0."""
    f = card_dir / "card.json"
    new = dict(card)
    meta = dict(new.get("metadata") or {})
    if not f.is_file() and base is not None:
        if _strip(base) == _strip(new):
            pass  # an unchanged copy: keep the base version
        else:
            base_meta = base.get("metadata") or {}
            kind = bump_kind(base, new)
            meta.update(version=next_version(base_meta.get("version", "1.0.0"), kind),
                        previous_content_hash=card_hash(base), version_bump_reason=kind)
            if base_layer:
                meta["version_base_layer"] = base_layer
        new["metadata"] = meta
        _atomic_write(f, dumps_card(new))
        return new, True
    if f.is_file():
        old_text = f.read_text(encoding="utf-8")
        old = json.loads(old_text)
        if _strip(old) == _strip(new):
            return old, False
        old_meta = old.get("metadata") or {}
        old_ver = old_meta.get("version", "1.0.0")
        h = card_hash(old)
        kind = bump_kind(old, new)
        archive = cards_root / "_versions" / str(old.get("category", "_")) / str(old.get("name", f.parent.name)) \
            / f"{old_ver}__{h[:12]}.json"
        _atomic_write(archive, old_text)
        if card_hash(json.loads(archive.read_text(encoding="utf-8"))) != h:  # L35: verify before destroy
            raise OSError(f"version archive {archive} did not verify; refusing to overwrite {f}")
        meta.update(version=next_version(old_ver, kind), previous_content_hash=h, version_bump_reason=kind)
    else:
        meta.setdefault("version", "1.0.0")
    new["metadata"] = meta
    _atomic_write(f, dumps_card(new))
    return new, True
