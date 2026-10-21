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
        lines.append(f"| {c.name} | {c['statement']} | {', '.join(c.get('origins') or [])} | `{c.get('witness')}` |")
    lines += ["", "Laws from the source sets that are not carried over (hub GUI/hub-folder/process laws, Pheros "
              "wave/daemon/hub-panel laws) are about those projects' own tooling; see ARCHITECTURE.md "
              "§ What was not carried over.", ""]
    caps = sorted(store.cards("capability"), key=lambda c: (c.get("order", 999), c.name))
    if caps:
        lines += ["## The core: capabilities that carry the laws (CM37)", "",
                  f"{len(caps)} capability cards (cards/capability). Each one's smoke check runs in every "
                  "`cardmodel verify` and every self-run (`cardmodel self capabilities`); a core capability that "
                  "stops behaving fails verify, and every law above is carried by at least one of them.", "",
                  "| capability | what the model can do | laws it carries | smoke check | witness tests |",
                  "|---|---|---|---|---|"]
        for c in caps:
            laws_ = ", ".join(q.split("/")[-1].split("_")[0] for q in c.get("laws") or [])
            tests = ", ".join(f"`{t.split('::')[-1]}`" for t in c.get("tests") or [])
            lines.append(f"| {c.name} | {c['statement']} | {laws_} | `{c['check']}` | {tests} |")
        lines.append("")
    return "\n".join(lines)
