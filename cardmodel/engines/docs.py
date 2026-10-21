"""docs — documents generated from cards (L38: counts computed, never typed).

``laws_md`` renders LAWS.md from the law cards; ``cardmodel docs --check``
(and tests/test_laws.py) fail when the committed file drifts from the cards.
"""
from __future__ import annotations


def laws_md(store) -> str:
    laws = sorted(store.cards("law"), key=lambda c: c.name)
    lines = ["# LAWS (generated from cards/law by `cardmodel docs`; edit the cards, not this file)", "",
             f"{len(laws)} laws. Each one names the test that witnesses it (CM20); the origins column says which "
             "hub (LAWS.md L-numbers) or Pheros (cards/law) laws it consolidates.", "",
             "| id | law | origins | witness |", "|---|---|---|---|"]
    for c in laws:
        lines.append(f"| {c.name} | {c['statement']} | {', '.join(c['origins'])} | `{c['witness']}` |")
    lines += ["", "Laws from the source sets that are not carried over (hub GUI/hub-folder/process laws, Pheros "
              "wave/daemon/hub-panel laws) are about those projects' own tooling; see ARCHITECTURE.md "
              "§ What was not carried over.", ""]
    return "\n".join(lines)
