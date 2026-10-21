"""canon — deterministic encodings used by the kernel.

Two encodings, deliberately separate:

* ``canon(value)`` is the Python form of the ``crypto_atom/canon_json`` card
  (ported from Ting's ``core/encoding.py``): keys sorted by UTF-16 code
  units, no whitespace, UTF-8, only str / safe int / bool / null / list /
  dict, no lone surrogates. Its JavaScript twin lives in the card's
  ``javascript.mjs`` variant; the known-answer vectors are the witness.
* ``card_hash(card)`` is the kernel's content address for versioning. It
  must accept floats (form costs are floats), so it uses Python's sorted,
  compact ``json.dumps``. It is Python-only by design; nothing outside the
  kernel needs to reproduce it.
"""
from __future__ import annotations

import hashlib
import json

MAX_SAFE_INT = 2**53


class CanonError(ValueError):
    pass


def _check_str(text: str) -> None:
    try:
        text.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise CanonError("lone surrogate") from exc


def _utf16_key(text: str) -> bytes:
    return text.encode("utf-16-be", "surrogatepass")


def _encode(value, out: list, depth: int) -> None:
    if depth > 64:
        raise CanonError("nesting too deep")
    if value is None:
        out.append("null")
    elif value is True:
        out.append("true")
    elif value is False:
        out.append("false")
    elif type(value) is int:
        if not -MAX_SAFE_INT < value < MAX_SAFE_INT:
            raise CanonError("integer out of range")
        out.append(str(value))
    elif type(value) is str:
        _check_str(value)
        out.append(json.dumps(value, ensure_ascii=False))
    elif type(value) in (list, tuple):
        out.append("[")
        for i, item in enumerate(value):
            if i:
                out.append(",")
            _encode(item, out, depth + 1)
        out.append("]")
    elif type(value) is dict:
        for key in value:
            if type(key) is not str:
                raise CanonError("object keys must be strings")
            _check_str(key)
        out.append("{")
        for i, key in enumerate(sorted(value, key=_utf16_key)):
            if i:
                out.append(",")
            out.append(json.dumps(key, ensure_ascii=False))
            out.append(":")
            _encode(value[key], out, depth + 1)
        out.append("}")
    else:
        raise CanonError(f"type not allowed: {type(value).__name__}")


def canon(value) -> bytes:
    out: list[str] = []
    _encode(value, out, 0)
    return "".join(out).encode("utf-8")


def canon_str(value) -> str:
    return canon(value).decode("utf-8")


def compact(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def card_hash(card: dict) -> str:
    """sha256 over the sorted compact JSON of a card (floats allowed)."""
    return hashlib.sha256(compact(dict(card)).encode("utf-8")).hexdigest()


def dumps_card(card: dict) -> str:
    """The on-disk form of card.json: sorted keys, 2-space indent, trailing newline."""
    return json.dumps(dict(card), indent=2, ensure_ascii=False, sort_keys=True) + "\n"
