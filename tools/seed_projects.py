#!/usr/bin/env python3
"""seed_projects — the projects the store's "In development" page follows (cardmodel/arcade/hub.py).

  project        one card per game, program or research line in progress: what to watch (the repository, the
                 paths in it, the games whose builds belong to it, the metrics that measure it, its docs), which
                 the hub turns into computed status (law CM01); and the detail its owning session keeps current
                 (law CM41): goal, status, done / in progress / left, blockers, next steps, the user's actions,
                 owner, branches, when it was last revised
  card_type/project
  law/CM41, goal/G_A8

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
    "required": ["title", "kind", "statement", "goal", "standing", "done", "in_progress", "left", "blockers",
                 "next_steps", "user_actions", "owner", "branches", "updated"],
    "properties": {"title": {"type": "string"}, "kind": {"enum": ["game", "program", "research"]},
                   "goal": {"type": "string"}, "standing": {"type": "string"}, "updated": {"type": "string"},
                   "done": {"type": "array"}, "in_progress": {"type": "array"}, "left": {"type": "array"},
                   "blockers": {"type": "array"}, "next_steps": {"type": "array"}, "branches": {"type": "array"},
                   "user_actions": {"type": "array", "items": {"type": "object", "required": ["action", "unblocks"]}},
                   "owner": {"type": "object", "required": ["session"]},
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


UPDATED = "2026-10-22T00:55:00+02:00"
ME = {"session": "local_fcae30d2-ac51-4132-b69b-731309e141cc", "name": "cardmodel main (integration)"}
GAMES = {"session": "local_ebd0314c-c068-4425-ab7c-dc023b36278b", "name": "cardmodel-games"}
OAM = {"session": "local_978e773c-d0b7-4c45-9824-80cad4f52163", "name": "model-the-dmg-oam-corrup"}
ANY = {"session": "local_cae4df41-9d25-4898-9bd6-d52bfafb23ba", "name": "cardmodel-anyps5"}
TING = {"session": "local_4c2cfa52-7ff4-4dca-b7c1-a768d03ad476", "name": "Ting"}
REA = {"session": "local_15d5214f-47df-4362-a79d-79a9516cef94", "name": "rea-cards"}


def act(action, why, *unblocks):
    return {"action": action, "why": why, "unblocks": list(unblocks)}


# law CM41: the detail every project card keeps current (engines/projects.py); its owner revises it with its work
DETAIL = {
    "vector_duel": dict(
        owner=GAMES, branches=["claude/sad-sanderson-*"],
        goal="A complete native fighting game whose every rule, number, picture and sound is a card, shipped "
             "through the store.",
        standing="0.3.0 is the release on main; 0.4.0 is built on the games branch and offered as early access.",
        done=["the combat kernel, moves and fighters as cards, compiled natively",
              "arcade ladder, training, versus, options, saves, achievements",
              "0.4.0 (strings as chain cards, the duel-tree AI, the Architect's phases) committed as e096446"],
        in_progress=["0.4.0 waits to be merged into main"],
        left=["make 0.4.0 the release", "more of the game (ROADMAP: Arcade next)"],
        blockers=["the merge needs the user's go-ahead"],
        next_steps=["merge claude/sad-sanderson-482207 into main", "rebuild the release from main's cards"],
        user_actions=[act("Approve merging claude/sad-sanderson-482207 into main",
                          "it makes Vector Duel 0.4.0 the release instead of early access",
                          "Vector Duel 0.4.0 as the release", "the launcher's Update to 0.4.0")]),
    "gameboy_player": dict(
        owner=OAM, branches=["claude/festive-margulis-*", "claude/strange-dewdney-*"],
        goal="Every Game Boy and Game Boy Color cartridge in the user's folders is a store entry that plays through "
             "the model's cards.",
        standing="The cartridge library, the system player and a WORK tab are on claude/festive-margulis-43fde7; its "
               "store work is still uncommitted there.",
        done=["960 of 971 surveyed ROMs boot", "every runnable hardware test ROM passes (OAM bug, CGB DMG mode)",
              "on the branch: library.json cartridge folders, headers, covers, the Game Boy Player build"],
        in_progress=["the launcher's library UI and update fallback (uncommitted on the branch)"],
        left=["commit the store work", "merge it into main", "one store entry per cartridge on main"],
        blockers=["the branch's store work is uncommitted", "the merge needs the user's go-ahead"],
        next_steps=["commit the work in progress", "renumber CM36_players_are_cards to CM40", "merge into main"],
        user_actions=[act("Approve merging claude/festive-margulis-43fde7 into main once its store work is committed",
                          "it brings every cartridge into the store as an entry, the DS shown as unplayable, and the "
                          "system players",
                          "Game Boy / Color cartridges as store entries", "the DS listed as unplayable",
                          "one In progress tab instead of two")]),
    "ds_prototype": dict(
        owner=GAMES, branches=[],
        goal="Nintendo DS games running on the ARM instruction cards, lifted like the Game Boy.",
        standing="Both CPUs boot directly and the ARM9 code is lifted (identical to the interpreter over 300 frames); "
               "no graphics or sound yet, so nothing is playable.",
        done=["ARMv5TE/ARMv4T instruction cards, conformant in every engine", "direct boot of both CPUs, measured",
              "ARM9 code lifted, identical to the interpreter"],
        in_progress=[], left=["SPI devices, RTC, sound channel status", "VRAM banks and the 2D engines",
                              "3D", "Thumb and the ARM7 in the lifter"],
        blockers=["no graphics yet: the store can only list it as unplayable"],
        next_steps=["the 2D engines, for a first picture"], user_actions=[]),
    "combat": dict(
        owner=ME, branches=[],
        goal="A fighting design whose balance is computed: every design law holds on the exact equilibrium.",
        standing="8 of 8 design laws hold on the exact equilibrium; its rules ship as Vector Duel's.",
        done=["moves, stances and fighters as cards", "exact rational simplex with a checked certificate",
              "equilibrium and reader AIs, the terminal prototype (cardmodel game play)"],
        in_progress=[], left=["a store entry that launches the terminal prototype"],
        blockers=["waits on the merged store (entries that launch a program)"],
        next_steps=["after the cartridge merge: a terminal-launch store entry"], user_actions=[]),
    "world": dict(
        owner=ME, branches=[],
        goal="A systemic world where every consequence carries and explains its cause.",
        standing="Facts carry between ticks, every event explains its cause, each action's impact is measured.",
        done=["world rules in the card language", "explanations back to the actions", "counterfactual impact"],
        in_progress=[], left=["a campaign map in Vector Duel", "a store entry that launches it"],
        blockers=["waits on the merged store (entries that launch a program)"],
        next_steps=["after the cartridge merge: a store entry"], user_actions=[]),
    "cardmodel": dict(
        owner=ME, branches=["claude/jolly-liskov-*", "claude/compassionate-margulis-*"],
        goal="One self-contained program in which everything is a card: a universal Gödel model that keeps "
             "expanding (GOALS.md).",
        standing="On main: 40 laws carried by 27 capabilities, verify passes, the self-run on every use, the live "
               "store page; docs/MATH_CORE.md is being written for the user's approval.",
        done=["consolidation, knowledge layer, card language, Lean bridge", "resource governor, function algebra",
              "every session branch merged as of 7e4323a", "self-run (CM38), capabilities (CM37), one program (CM39)",
              "the live In progress page with early access (bb480fb)"],
        in_progress=["law CM41: detailed project cards", "docs/MATH_CORE.md"],
        left=["the semantic core migration, after the user's yes", "one In progress tab after the cartridge merge",
              "the prime ledger and Gödel vectors"],
        blockers=["MATH_CORE.md needs the user's yes before anything existing is restructured"],
        next_steps=["finish CM41", "write MATH_CORE.md and its summary", "merge the waiting branches"],
        user_actions=[
            act("Read the MATH_CORE summary and say yes, or what to change",
                "moving from imitation (emulation, tests) to understanding (one semantic core, definitions, Gödel "
                "factors) changes how everything is built",
                "the semantic core migration", "definition cards for every function",
                "sessions stop adding imitation-only paths"),
            act("Decide what happens to claude/jolly-liskov-2d97a8",
                "a second self-run built in parallel; its laws CM37-CM39 collide with main's",
                "merging or retiring that branch")]),
    "anyps5": dict(
        owner=ANY, branches=["claude/recursing-williams-*"],
        goal="AnyPS5's real coverage, every gap's cause, and its code witnessed against semantics from public "
             "standards.",
        standing="2467 of 6903 exports complete (36%), every gap classified; on its branch: the master plan "
               "(docs/VISION.md) and 23 compiled library functions lifted from machine code into cards.",
        done=["the badge reproduced", "every gap with its cause", "witnesses against public standards",
              "on the branch: VISION.md, the machine-code lifter (9db0861)"],
        in_progress=["the plan's next steps on its branch"],
        left=["close the derivable gaps", "host mappings", "the string/list IR", "console observations"],
        blockers=[], next_steps=["its session asks for the merge when a step is ready"], user_actions=[]),
    "anyps5_copy": dict(
        owner=ANY, branches=[],
        goal="A copy of AnyPS5 the model's fixes go into, never the original.",
        standing="Builds on macOS; its relinker tests pass with Ninja installed.",
        done=["all 226 relinker tests pass", "the MP3 check runs natively"], in_progress=["host mappings"],
        left=["titles that need Rosetta"], blockers=[], next_steps=["host mappings for the full build"],
        user_actions=[]),
    "ting": dict(
        owner=TING, branches=[],
        goal="The encrypted community platform.",
        standing="Kept by its own session; its detail belongs in ~/Programmering/ting/.cardmodel/project.json.",
        done=[], in_progress=[], left=[], blockers=[], next_steps=["publish .cardmodel/project.json"],
        user_actions=[]),
    "rea_cards": dict(
        owner=REA, branches=[],
        goal="rea's reconstruction tooling as cards.",
        standing="Kept by its own session; its detail belongs in ~/Programmering/rea-cards/.cardmodel/project.json.",
        done=[], in_progress=[], left=[], blockers=[], next_steps=["publish .cardmodel/project.json"],
        user_actions=[]),
    "lean_bridge": dict(
        owner=ME, branches=[],
        goal="Lean as the proof kernel of the model, with proofs a person can read.",
        standing="1579 theorem cards proved, 1489 Lean core theorems read faithfully, 47 of 114 rewrite rules proved.",
        done=["fail-closed batch checking", "faithful import with Lean semantics", "derivations as Lean terms"],
        in_progress=[], left=["the other 67 rewrite rules", "readable proofs (MATH_CORE.md)",
                              "proofs linking emitted code to definitions"],
        blockers=["the readable-proof and definition work waits on MATH_CORE.md's approval"],
        next_steps=["prove the remaining rewrite rules"], user_actions=[]),
    "godel_functions": dict(
        owner=ME, branches=[],
        goal="Functions as algebra: canonical forms with Gödel numbers, and the common factors that carry logic.",
        standing="Canonical forms, exact Gödel numbering, the GCD of functions and their identities are built; "
               "the expanding Gödel model (GOALS.md) is the next layer.",
        done=["canonical forms from behaviour", "exact Gödel encode/decode", "GCD of functions, cofactor identities"],
        in_progress=["the expanding Gödel model's definition (GOALS.md)"],
        left=["the prime ledger", "Gödel vectors on every card", "homomorphism cards", "the physics set"],
        blockers=["the restructuring waits on MATH_CORE.md's approval"],
        next_steps=["the prime ledger (append-only)"], user_actions=[]),
    "llvm_ir_identity": dict(
        owner=ME, branches=[],
        goal="Identity of functions across languages through LLVM IR.",
        standing="Not started in the card model: three translation-gap cards record what LLVM IR lacks.",
        done=["translation-gap cards for go, python and rust to LLVM IR"], in_progress=[],
        left=["decide whether MATH_CORE's semantic core replaces this line"],
        blockers=["MATH_CORE.md decides its place"], next_steps=[], user_actions=[]),
    "lineage": dict(
        owner=ME, branches=[],
        goal="Where the model's methods come from, as cards.",
        standing="Five lineage cards: Servois, Peacock, Boole, Hankel, Gödel.",
        done=["the five lineage cards"], in_progress=[], left=["the lineage of the four sources (MATH_CORE.md)"],
        blockers=[], next_steps=[], user_actions=[]),
}

LAWS = [
    ("CM41_projects_keep_their_cards_current", "Every project in progress keeps a detailed project card: its goal, "
     "status, what is done, in progress and left, blockers, next steps, what the user must do or decide (each with "
     "what it unblocks), its owning session, its branches and when the detail was last revised. A commit touching "
     "the project more than a day after that revision makes the card stale, and a branch with unmerged work that no "
     "card lists is missing one; verify fails on either. The store's hub reads these cards and gathers every user "
     "action into one list, most unblocking first. Our model keeps them current; other tools never have to.",
     ["user requirement 2026-10-22 (force every project by law to keep its detail for later updates)"],
     "tests/test_projects.py::test_missing_or_stale_project_cards_fail"),
]
GOALS = [
    ("G_A8_project_cards_current", "autonomy", "Project cards missing detail, stale, or missing for a branch with "
     "unmerged work (CM41).", "project_card_problems", 0, "lower"),
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
             "order": i + 1, "provenance": PROV, **extra, **DETAIL.get(name, {}), "updated": UPDATED})
    for name, statement, origins, witness in LAWS:
        put({"name": name, "category": "law", "tier": 0, "statement": statement, "origins": origins,
             "witness": witness, "provenance": PROV})
    for name, axis, statement, metric, target, direction in GOALS:
        put({"name": name, "category": "goal", "tier": 0, "axis": axis, "statement": statement, "metric": metric,
             "target": target, "direction": direction, "provenance": PROV})
    print(json.dumps(stats))
    return 0


if __name__ == "__main__":
    sys.exit(main())
