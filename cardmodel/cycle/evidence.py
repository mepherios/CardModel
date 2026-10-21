"""evidence — the few numbers the cycle leaves for the goals to read, in the store's state folder.

``note(ctx, **numbers)`` merges into state/cycle_summary.json: law_witnesses_failing (the laws stage),
store_items_failing (the store stage and ``cardmodel arcade check``), regressions (the end of every cycle).
``self_observation(ctx)`` is the cycle's latest observation of the model's own code
(state/cycle_self_observation.json), which the ``named_fraction`` goal prefers when it is newer than the last
observation card.

Honest limits (L1): state is a cache (gitignored): a fresh checkout has none of these numbers until a cycle or a
check has run there, and the goals that read them say "not run yet" until then.
"""
from __future__ import annotations

from datetime import datetime, timezone


def _read(ctx, name: str) -> dict:
    try:
        return ctx.load_state(name) or {}
    except ValueError:
        return {}


def note(ctx, **numbers) -> dict:
    s = _read(ctx, "cycle_summary")
    s.update(numbers)
    s["updated"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    ctx.save_state("cycle_summary", s)
    return s


def summary(ctx) -> dict:
    return _read(ctx, "cycle_summary")


def save_self_observation(ctx, obs: dict) -> None:
    ctx.save_state("cycle_self_observation", obs)


def self_observation(ctx) -> dict:
    return _read(ctx, "cycle_self_observation")


__all__ = ["note", "save_self_observation", "self_observation", "summary"]
