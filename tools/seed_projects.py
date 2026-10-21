#!/usr/bin/env python3
"""seed_projects — the projects the store's "In development" page follows (cardmodel/arcade/hub.py).

  project        one card per game, program or research line in progress: what to watch (the repository, the
                 paths in it, the games whose builds belong to it, the metrics that measure it, its docs).
                 Nothing on a card says how far along the project is: the hub computes that from git and from
                 the records the model writes (law CM01).
  card_type/project

Run once: ``python3 -B tools/seed_projects.py`` (``--force`` rewrites, with versioning). Reads nothing outside the
repository; the repositories some cards name (Ting, rea-cards, the AnyPS5 copy) are read only by the hub, read-only.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cardmodel.kernel.store import open_store  # noqa: E402

PROV = {"origin": "cardmodel", "tool": "tools/seed_projects.py"}

REGISTRY = ("project", "The games, programs and research lines in progress that the store's In development page "
            "follows. A card says what to watch; the hub (cardmodel/arcade/hub.py) computes the status.")

CARD_TYPE = {
    "required": ["title", "kind", "statement"],
    "properties": {"title": {"type": "string"}, "kind": {"enum": ["game", "program", "research"]},
                   "repo": {"type": "string"}, "paths": {"type": "array", "items": {"type": "string"}},
                   "games": {"type": "array", "items": {"type": "string"}},
                   "metrics": {"type": "array", "items": {"type": "object"}},
                   "docs": {"type": "array", "items": {"type": "string"}}, "order": {"type": "integer"}},
}

PROJECTS = [
    ("vector_duel", "game", "Vector Duel", "The native fighting game made of cards. Its next version is built on "
     "the games branch and offered as early access beside the release.",
     {"paths": ["cards/game/vector_duel", "cardmodel/arcade/gen.py", "cardmodel/arcade/game.py",
                "cardmodel/arcade/build.py"], "games": ["vector_duel"],
      "metrics": [{"verify": "game", "format": "{laws_passed}/{laws_total} design laws hold", "label": "balance"}],
      "docs": ["docs/ARCADE.md", "docs/STORE.md"]}),
    ("gameboy_player", "game", "Game Boy Player", "Game Boy and Game Boy Color games through the lifted card IR, "
     "with the cartridges and players as cards; its store entry is being built on a branch.",
     {"paths": ["cardmodel/machine/gb.py", "cardmodel/machine/lift.py", "cardmodel/machine/shell.py",
                "cardmodel/machine/survey.py", "cardmodel/machine/testroms.py", "cards/hardware", "cards/machine/gameboy",
                "cards/isa/lr35902", "cards/game/gameboy_player", "cards/player", "cards/cartridge"],
      "games": ["gameboy_player"],
      "metrics": [{"goal": "G_M2_roms_boot", "label": "surveyed ROMs that boot"},
                  {"goal": "G_M4_test_roms", "label": "hardware test ROMs passing"},
                  {"state": "emu_testroms", "format": "{passed}/{total}", "label": "test ROMs (count)"}],
      "docs": ["docs/MACHINES.md"]}),
    ("ds_prototype", "game", "Nintendo DS prototype", "Both DS CPUs direct-booted on the ARM instruction cards, the "
     "ARM9's code lifted; no graphics or sound yet.",
     {"paths": ["cardmodel/machine/nds.py", "cardmodel/machine/lift_arm.py", "cards/machine/nds",
                "cards/isa/armv5te", "cards/machine/armv5te_bench", "tools/gen_armv5te.py"],
      "metrics": [{"state": "nds_coverage", "sum": "cpus.*.instructions_executed",
                   "label": "instructions executed by the cards"},
                  {"state": "nds_coverage", "path": "lifted_differential.verdict", "label": "lifted vs interpreter"},
                  {"goal": "G_M5_ds_decoded", "label": "executed instructions no card decodes"}],
      "docs": ["docs/MACHINES.md"]}),
    ("combat", "game", "Vector Counter System", "The combat design: moves, stances and fighters as cards; its design "
     "laws are computed on exact equilibria and its AIs read your vectors (cardmodel game play).",
     {"paths": ["cardmodel/game/combat.py", "cardmodel/game/analysis.py", "cardmodel/game/ai.py", "cards/move",
                "cards/fighter", "cards/stance", "cards/design_law", "cards/payoff", "stdlib/combat.card",
                "game/DESIGN.md"],
      "metrics": [{"verify": "game", "format": "{laws_passed}/{laws_total} design laws hold", "label": "design laws"},
                  {"goal": "G_D2_equilibrium_support", "label": "options the equilibrium mixes"}],
      "docs": ["game/DESIGN.md"]}),
    ("world", "game", "The systemic world", "A world whose events carry between ticks and explain their causes "
     "(cardmodel game world).",
     {"paths": ["cardmodel/game/world.py", "stdlib/world.card"],
      "metrics": [{"verify": "game", "format": "{world_final_facts} facts carried to the end", "label": "world run"}],
      "docs": ["game/DESIGN.md"]}),
    ("cardmodel", "program", "The card model", "This program: cards, the language, logic, proofs, translation, "
     "optimization, machines, the store, and the cycle that runs it all on itself.",
     {"paths": [], "metrics": [{"self": "status", "label": "last self-run"},
                               {"verify": "*", "label": "last verify"},
                               {"goal": "G_A4_capabilities_failing", "label": "core capabilities failing"}],
      "docs": ["README.md", "docs/AUTONOMY.md", "docs/INTEGRATION.md"]}),
    ("anyps5", "program", "AnyPS5 on cards", "AnyPS5 read as cards: its badge reproduced, its real coverage, every "
     "gap with the cause that keeps it open.",
     {"paths": ["cardmodel/anyps5", "stdlib/anyps5.card", "stdlib/ps5_*", "cards/anyps5_*", "docs/ANYPS5*",
                "tools/seed_anyps5.py"],
      "metrics": [{"verify": "anyps5", "format": "{complete}/{declared} exports complete, {witnessed} witnessed",
                   "label": "coverage"},
                  {"goal": "G_P4_anyps5_complete_fraction", "label": "complete fraction"}],
      "docs": ["docs/ANYPS5.md"]}),
    ("anyps5_copy", "program", "AnyPS5 (working copy)", "The copy of AnyPS5 the model's fixes go into "
     "(~/Programmering/AnyPS5-cardmodel; the original is never written).",
     {"repo": "~/Programmering/AnyPS5-cardmodel", "metrics": [{"git_files": "core/libs/prx/", "count": "dirs",
                                                              "label": "system libraries"}]}),
    ("ting", "program", "Ting", "The encrypted community platform (~/Programmering/ting), read here only.",
     {"repo": "~/Programmering/ting", "metrics": [{"git_files": "", "label": "files committed"}]}),
    ("rea_cards", "program", "rea as cards", "rea's reconstruction tooling as cards (~/Programmering/rea-cards), "
     "read here only.",
     {"repo": "~/Programmering/rea-cards", "metrics": [{"git_files": "cards/", "label": "cards committed"},
                                                       {"git_files": "cards/re_flaw/", "count": "dirs",
                                                        "label": "flaws recorded"}]}),
    ("lean_bridge", "research", "The Lean bridge", "Lean as the proof kernel: theorems, derivations and Lean's own "
     "library as cards, re-proved by the model's tactics.",
     {"paths": ["cardmodel/emit/lean.py", "cardmodel/emit/lean_import.py", "cardmodel/emit/lean_logic.py",
                "cardmodel/emit/lean_chain.py", "cardmodel/engines/theorems.py"],
      "metrics": [{"goal": "G_K1_theorems_proved", "label": "theorems proved"},
                  {"goal": "G_K2_lean_imported", "label": "Lean theorems read faithfully"},
                  {"verify": "proofs", "format": "{proved}/{total} rewrite rules proved", "label": "rule proofs"}],
      "docs": ["docs/KNOWLEDGE.md"]}),
    ("godel_functions", "research", "Gödel-numbered functions", "Functions as algebra: canonical forms, Gödel "
     "numbers, the GCD of functions and the identities that carry between them.",
     {"paths": ["cardmodel/engines/funcalg.py", "stdlib/algebra.card", "cards/functional_identity"],
      "metrics": [{"goal": "G_K6_functional_identities", "label": "identities between functions"},
                  {"cards": "functional_identity", "label": "functional identity cards"}],
      "docs": ["docs/KNOWLEDGE.md"]}),
    ("llvm_ir_identity", "research", "LLVM-IR identity", "Identity of functions across languages through LLVM IR "
     "(the Pheros line of work). The card model holds the translation-gap cards for LLVM IR it carried over, and no "
     "LLVM code yet; its nearest working pieces are lifted machine code and the cross-language equivalence cards the "
     "learning step writes.",
     {"paths": ["*llvm*"],
      "metrics": [{"cards": "translation_gap", "match": "*llvm*", "label": "LLVM-IR translation gaps recorded"},
                  {"cards": "xleq", "label": "cross-language equivalences learned"}]}),
    ("lineage", "research", "The lineage cards", "Where the model's methods come from: Servois, Peacock, Boole, "
     "Hankel, Gödel.",
     {"paths": ["cards/lineage", "tools/seed_knowledge.py"],
      "metrics": [{"cards": "lineage", "label": "lineage cards"}], "docs": ["docs/KNOWLEDGE.md"]}),
]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args(argv)
    store = open_store(project=False)
    root = store.layer_root("model")
    d = root / REGISTRY[0]
    d.mkdir(parents=True, exist_ok=True)
    f = d / "_category.json"
    if not f.exists() or args.force:
        meta = {"name": REGISTRY[0], "description": REGISTRY[1], "tier": 1, "defined_by": "tools/seed_projects.py",
                "card_type": REGISTRY[0]}
        f.write_text(json.dumps(meta, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    store.invalidate()
    stats = {"written": 0, "kept": 0}

    def put(card):
        if store.get(f"{card['category']}/{card['name']}") is not None and not args.force:
            stats["kept"] += 1
            return
        _, changed = store.save(card, layer="model")
        stats["written" if changed else "kept"] += 1

    put({"name": "project", "category": "card_type", "tier": 0, "applies_to": ["project"],
         "statement": "A project in progress: what the hub watches, never how far along it is.",
         "metadata": {"version": "1.0.0"}, "provenance": PROV,
         "schema": {"type": "object", "required": CARD_TYPE["required"], "properties": CARD_TYPE["properties"]}})
    for i, (name, kind, title, statement, extra) in enumerate(PROJECTS):
        put({"name": name, "category": "project", "tier": 1, "kind": kind, "title": title, "statement": statement,
             "order": i + 1, "provenance": PROV, **extra})
    print(json.dumps(stats))
    return 0


if __name__ == "__main__":
    sys.exit(main())
