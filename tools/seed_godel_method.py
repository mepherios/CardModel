#!/usr/bin/env python3
"""seed_godel_method — wave 1 of the Gödel method research program (docs/GODEL_METHOD.md).

  project     one card per wave-1 workstream (W-1, W-2, W-3, W-5, W-12, W-15), kept current with every commit (CM41)
  finding     the registry for results: each finding cites the handover ids it tests or builds (Def-, Rule-, Cap-,
              Ph-, GM-) and states its tier (proof, probabilistic, bounded, sample)

The handover is the Claude Doc "The Gödel Method: Research and Development Handover" (2026-10-22). The user's words,
relayed by the Ting session: "Yes, send the Gödel method handover to the card-model session and have it start the
wave-1 workstreams (W-1, W-2, W-3, W-5, W-12, W-15) under its coordination rules."

Run: ``python3 -B tools/seed_godel_method.py`` (cards are kept unless ``--force``).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cardmodel.kernel.store import open_store  # noqa: E402

PROV = {"origin": "cardmodel", "tool": "tools/seed_godel_method.py",
        "source": "The Gödel Method: Research and Development Handover (2026-10-22)"}
OWNER = {"name": "cardmodel main (integration)", "session": "local_fcae30d2-ac51-4132-b69b-731309e141cc"}
FINDING = ("finding", "Research results of the Gödel method program: each finding cites the handover ids it tests or "
           "builds and states its tier (proof, probabilistic, bounded, sample).")

WORKSTREAMS = [
    ("godel_w1_definitions", "W-1", "Gödel's 46 definitions as cards", "w1",
     "Can every 1931 definition run as a card?",
     ["46 definition cards with Python and Lean forms", "round-trip witnesses on generated codes",
      "a checker for Gödel-coded proofs of a small system"],
     ["cards/godel1931/*", "cardmodel/engines/godel1931.py", "formal/Godel1931/*"]),
    ("godel_w2_formal_core", "W-2", "Formal core in Lean, on Mathlib", "w2",
     "Can the content algebra and the carry-over laws be kernel-checked?",
     ["Rule-19 and Rule-20 over Finsupp and Multiset", "the freeness argument behind GM-3",
      "Foundation's incompleteness and GL results imported as truth cards"],
     ["formal/*"]),
    ("godel_w3_identity_size", "W-3", "Identity and size of codes", "w3",
     "Which code should identify a card?",
     ["sizes of the positional, content, pairing, bijective base-k and hash codes for every card",
      "a size model that predicts them", "a decision record for GM-2 with the size bound for GM-2 and GM-8"],
     ["cardmodel/engines/codes.py", "cards/finding/*"]),
    ("godel_w5_numberings", "W-5", "Admissible numberings", "w5",
     "What makes a numbering admissible in each domain?",
     ["admissibility conditions drawn from Feferman and Grabmayr", "a test for each Gödel set"],
     ["cards/godel_set/*", "cardmodel/engines/numbering.py"]),
    ("godel_w12_arithmetized", "W-12", "Arithmetized execution", "w12",
     "Can instruction terms become polynomial constraints over a prime field?",
     ["the LR35902 instruction terms compiled to constraints over a prime field",
      "equality checked by Schwartz-Zippel", "a comparison with SMT and exhaustive checking"],
     ["cardmodel/machine/arith.py", "cards/finding/*"]),
    ("godel_w15_difficulty", "W-15", "Difficulty census", "w15",
     "Which of the product's questions are decidable?",
     ["an arithmetical rank on every method card (GM-7)", "the questions the product must leave open"],
     ["cards/method/*", "cards/question/*"]),
]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args(argv)
    store = open_store(project=False)
    root = store.layer_root("model")
    d = root / FINDING[0]
    d.mkdir(parents=True, exist_ok=True)
    f = d / "_category.json"
    if not f.exists() or args.force:
        meta = {"name": FINDING[0], "description": FINDING[1], "tier": 1, "defined_by": "tools/seed_godel_method.py"}
        f.write_text(json.dumps(meta, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    store.invalidate()
    stats = {"written": 0, "kept": 0}
    now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    for i, (name, wid, title, slug, question, deliverables, paths) in enumerate(WORKSTREAMS):
        if store.get(f"project/{name}") is not None and not args.force:
            stats["kept"] += 1
            continue
        card = {"name": name, "category": "project", "tier": 1, "kind": "research", "title": f"{wid} {title}",
                "statement": f"Gödel method research program, wave 1: {question}", "order": 40 + i,
                "goal": question, "standing": "Not started; wave 1 runs one workstream at a time on its own branch.",
                "done": [], "in_progress": [], "left": deliverables, "blockers": [],
                "next_steps": [f"start on claude/godel-{slug}-*"], "user_actions": [], "owner": OWNER,
                "branches": [f"claude/godel-{slug}-*"], "paths": paths, "docs": ["docs/GODEL_METHOD.md"],
                "metrics": [], "provenance": PROV, "updated": now}
        if wid == "W-2":
            card["blockers"] = ["Mathlib and Foundation are not installed: downloading them needs the user's yes"]
            card["user_actions"] = [{"action": "Allow downloading Mathlib (with its prebuilt cache) and "
                                               "FormalizedFormalLogic/Foundation for the formal core",
                                     "why": "W-2 proves the content algebra over Finsupp and imports Foundation's "
                                            "incompleteness and GL results; both are multi-gigabyte downloads",
                                     "unblocks": ["W-2", "W-10 and W-11 in wave 2"]}]
        _, changed = store.save(card, layer="model")
        stats["written" if changed else "kept"] += 1
    print(json.dumps(stats))
    return 0


if __name__ == "__main__":
    sys.exit(main())
