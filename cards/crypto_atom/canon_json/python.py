"""Canonical JSON, Python form (identical to cardmodel.kernel.canon; ported from Ting core/encoding.py)."""
import json

MAX_SAFE_INT = 2**53


class CanonError(ValueError):
    pass


def _check_str(text):
    try:
        text.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise CanonError("lone surrogate") from exc


def _encode(value, out, depth):
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
        for i, key in enumerate(sorted(value, key=lambda k: k.encode("utf-16-be", "surrogatepass"))):
            if i:
                out.append(",")
            out.append(json.dumps(key, ensure_ascii=False))
            out.append(":")
            _encode(value[key], out, depth + 1)
        out.append("}")
    else:
        raise CanonError(f"type not allowed: {type(value).__name__}")


def canon_str(value) -> str:
    out = []
    _encode(value, out, 0)
    return "".join(out)
