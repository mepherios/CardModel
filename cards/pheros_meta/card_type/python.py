"""python.py — Python variant of the Card type.

One of N language variants of the same type. The normative form is
schema.json in this directory. Lean, Rust, TypeScript variants will
live alongside this file once they're written.

L9: this variant exists. Other-language variants are tracked as
`lacking:` cards until they exist too.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

STATUS_VALUES = ("healthy", "suspect", "broken", "quarantined")


@dataclass(frozen=True)
class Card:
    name:           str
    category:       str
    tier:           int = 0
    cost:           float = 0.0
    statement:      str = ""
    rationale:      str = ""
    problem:        str = ""
    solution:       str = ""
    location:       str = ""
    file_refs:      tuple[str, ...] = ()
    depends_on:     tuple[str, ...] = ()
    supersedes:     tuple[str, ...] = ()
    interacts_with: tuple[str, ...] = ()
    tags:           tuple[str, ...] = ()
    status:         str = "healthy"
    flaws:          tuple[str, ...] = ()
    witness:        Optional[Callable[[], bool]] = None
    variants:       dict[str, str] = field(default_factory=dict)
    metadata:       dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if self.status not in STATUS_VALUES:
            raise ValueError(f"status must be one of {STATUS_VALUES}, got {self.status!r}")
