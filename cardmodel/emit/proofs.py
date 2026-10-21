"""proofs — the proof-assistant backends rewrite rules are checked with.

One backend today (``lean``: core Lean 4, grind/omega). A new proof assistant
is a sibling module exposing ``check_rules(ctx)``; this module picks the
first backend whose toolchain is present.
"""
from __future__ import annotations

from . import lean

BACKENDS = [lean]


def check_rules(ctx) -> dict:
    for backend in BACKENDS:
        res = backend.check_rules(ctx)
        if res.get("status") != "skipped":
            res["backend"] = backend.__name__.rsplit(".", 1)[-1]
            return res
    return res
