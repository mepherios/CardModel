"""detect_format form (port of rea-cards domains.detect, driven by cards/format/*)."""
import json
import os

_CARDS = None


def _formats():
    global _CARDS
    if _CARDS is None:
        here = os.path.dirname(os.path.abspath(__file__))
        reg = os.path.join(os.path.dirname(os.path.dirname(here)), "format")
        out = {}
        for name in sorted(os.listdir(reg)):
            f = os.path.join(reg, name, "card.json")
            if os.path.isfile(f):
                with open(f, encoding="utf-8") as fh:
                    out[name] = json.load(fh)
        _CARDS = out
    return _CARDS


def detect_format(path: str) -> str:
    best, best_pri = "unknown", -1
    if os.path.isdir(path):
        for name, card in _formats().items():
            d = card.get("detect") or {}
            if not d.get("directory"):
                continue
            ok = (not d.get("suffix") or path.rstrip("/").endswith(d["suffix"])) and \
                 (not d.get("contains") or os.path.exists(os.path.join(path, d["contains"])))
            if ok and d.get("priority", 0) > best_pri:
                best, best_pri = name, d.get("priority", 0)
        return best
    with open(path, "rb") as f:
        head = f.read(4096)
    for name, card in _formats().items():
        d = card.get("detect") or {}
        for m in d.get("magic") or []:
            want = bytes.fromhex(m["hex"])
            off = int(m.get("offset", 0))
            if head[off:off + len(want)] == want and d.get("priority", 0) > best_pri:
                best, best_pri = name, d.get("priority", 0)
    return best
