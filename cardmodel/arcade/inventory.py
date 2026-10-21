"""inventory — everything that goes into the store, and what the model contributes to each piece.

``compute`` walks the cards and files the arcade is made of (the catalogue's game cards and their logic, the rule
cards they play on, the combat kernel, the font, the platform card and its effect shell, the launcher's app card
and pages, the service, the build pipeline, the witnesses) and counts them; ``markdown`` renders the list that
docs/ARCADE_INVENTORY.md holds (generated, like LAWS.md: a test fails when it drifts from the cards).

Each row says who made the piece: ``model`` (the card model computes or compiles it from cards), ``cards``
(data or card-language logic, run and checked by the model), or ``hand`` (written by hand; the model only builds,
packages or serves it). The counts are computed (CM01); the sentences saying what the model contributes are
written here, next to the code that does it.

Honest limits (L1): counts are of cards, lines, functions and declarations, not of quality; a hand-written
piece is named as such even where the model builds it, and nothing here measures how much fun the game is.
"""
from __future__ import annotations

import re
from pathlib import Path

from ..kernel import paths


def _lines(p: Path) -> int:
    try:
        return len(p.read_text(encoding="utf-8").splitlines())
    except OSError:
        return 0


def _rel(p: Path) -> str:
    try:
        return str(Path(p).resolve().relative_to(paths.home()))
    except ValueError:
        return Path(p).name


def _tests(name: str) -> list[str]:
    f = paths.home() / "tests" / name
    return re.findall(r"^\s+def (test_\w+)\(", f.read_text(encoding="utf-8"), re.M) if f.is_file() else []


def compute(ctx) -> dict:
    from . import game as G
    from . import server as S
    from . import build as B
    st = ctx.store
    rows = []

    def row(piece, where, numbers, made_by, model, witness=""):
        rows.append({"piece": piece, "where": where, "numbers": numbers, "made_by": made_by, "model": model,
                     "witness": witness})
    games = sorted(st.cards("game"), key=lambda c: c.name)
    fighters, moves = set(), set()
    from .gen import moves_of
    for g in games:
        logic = [g.path / rel for rel in g.get("logic") or []]
        ir = G.module(ctx, g.name)
        tables = ir.get("tables") or {}
        row(f"{g.get('title', g.name)}: the game card", _rel(g.path / "card.json"),
            f"{len(g.get('strings') or {})} strings, {len(g.get('music') or [])} tunes, {len(g.get('ladder') or [])} "
            f"ladder opponents, {len(g.get('arenas') or {})} arenas, {len(g.get('achievements') or [])} achievements, "
            f"{len(g.get('changelog') or [])} versions (now {g.get('version')})", "cards",
            "Holds every number, word, tune and store text as data. gen.py turns it into the integer tables the "
            "logic reads; a change to the card is a new build, which the launcher offers as an update.",
            "tests/test_arcade.py::test_tables_come_from_the_cards")
        row(f"{g.get('title', g.name)}: its logic", ", ".join(_rel(p) for p in logic),
            f"{len(logic)} card-language files, {sum(_lines(p) for p in logic):,} lines; one module of "
            f"{len(ir['functions'])} functions, {len(ir.get('globals') or [])} globals, {len(ir.get('arrays') or [])} "
            f"arrays", "cards",
            "The whole game (frame loop, software renderer, duel, AIs, screens, synth, save) is card language: the "
            "model's compiler turns it into card IR, the C language card emits it, and the same module runs in the "
            "Python emission for the witnesses.", "tests/test_arcade.py::test_module_runs_the_same_in_two_engines")
        row(f"{g.get('title', g.name)}: equilibrium tables", "computed at build time (arcade/gen.py)",
            f"{len(tables.get('equilibria') or [])} exact mixes over {len(tables.get('moves') or [])} moves and "
            f"{len(tables.get('fighters') or [])} fighters", "model",
            "The equilibrium AI plays mixes the model solves exactly (rational simplex with a checked certificate, "
            "game/analysis.py) for every fighter pair and distance.", "tests/test_game.py")
        fighters.update(g.get("fighters") or [])
        moves.update(moves_of(st, list(g.get("fighters") or [])))
    laws = st.cards("design_law")
    row("The rules: move, fighter, stance and payoff cards", "cards/move, cards/fighter, cards/stance, cards/payoff",
        f"{len(moves)} moves and {len(fighters)} fighters used by the catalogue ({len(st.cards('move'))} move cards, "
        f"{len(st.cards('stance'))} stances); {len(laws)} design laws", "cards",
        "Every outcome on screen is decided by these cards. The model proves the design laws on them (no dominant "
        "option, two answers per attack, ...) on the exact equilibrium of the exchange.",
        "tests/test_game.py::test_design_laws_hold_and_catch_imbalance")
    kernels = sorted({g.get("kernel") for g in games if g.get("kernel")})
    for k in kernels:
        text = (paths.home() / k).read_text(encoding="utf-8")
        fns = len(re.findall(r"^fn ", text, re.M))
        ths = len(re.findall(r"^theorem ", text, re.M))
        row("The combat kernel", k, f"{fns} functions, {ths} theorems, {_lines(paths.home() / k)} lines", "cards",
            "Alignment, timing classes and outcomes as card language: its theorems are witnessed on every verify "
            "(and proved where Lean can), and the game calls these functions for every hit.",
            "tests/test_arcade.py::test_a_timed_guard_redirects")
    fonts = sorted({g.get("font") for g in games if g.get("font")})
    for fq in fonts:
        f = st.get(fq)
        glyphs = f.get("glyphs") if f is not None else None
        row("The font", fq, f"{len(glyphs) if isinstance(glyphs, (dict, list)) else 0} glyphs", "cards",
            "Glyph rows as data; the game draws every letter itself.", "")
    plats = sorted({g.get("platform", "macos") for g in games})
    for pn in plats:
        p = st.get(f"platform/{pn}")
        if p is None:
            continue
        srcs = [p.path / s for s in (p.get("effect_shell") or {}).get("sources", [])]
        row(f"Platform {pn}: the effect shell", ", ".join(_rel(s) for s in srcs),
            f"{sum(_lines(s) for s in srcs):,} lines of Swift; library through the "
            f"{(p.get('library') or {}).get('language')} language card; bundle layout and icon tool as data", "hand",
            "Hand-written and deliberately game-blind (CM21, CM35): it moves pixels, samples, buttons and save bytes "
            "for whatever module game.json names. The model compiles it from the platform card and lays out the "
            "bundle from the card's data.", "tests/test_arcade.py::test_native_package_runs_headless")
    app = st.get("app/arcade")
    if app is not None:
        srcs = [app.path / s for s in app.get("sources") or []]
        ui = sorted((app.path / app.get("ui", "ui")).glob("*")) if app.get("ui") else []
        row("The launcher (native client)", ", ".join(_rel(s) for s in srcs),
            f"{sum(_lines(s) for s in srcs):,} lines of Swift", "hand",
            "Hand-written: downloads with every chunk's SHA-256 checked, delta updates, verify and repair, play "
            "time, achievements. The model builds it from the app card (compile command, bundle, an icon drawn by "
            "code); `arcade check` replays its protocol step for step.",
            "tests/test_arcade.py::test_every_catalogue_item_launches_from_the_store")
        row("The launcher's pages", ", ".join(_rel(u) for u in ui),
            f"{len(ui)} files, {sum(_lines(u) for u in ui):,} lines", "hand",
            "Store, library, downloads, news, profile and settings. Every word and picture they show about a game "
            "comes from its card and from pictures the game drew.", "")
    srv = Path(S.__file__)
    row("The arcade service", _rel(srv), f"{len(S.ENDPOINTS)} API endpoints plus depots, chunks, media and pages",
        "model", "Builds a game from its cards on demand when they changed (the hash of its sources), and serves "
        "the catalogue, manifests and content-addressed chunks.",
        "tests/test_arcade.py::test_service_serves_catalog_manifest_and_chunks")
    row("The build pipeline and depots", _rel(Path(B.__file__)),
        f"6 steps; chunks of {B.CHUNK // (1 << 20)} MiB named by SHA-256", "model",
        "Cards -> card IR -> C card -> shared library; the platform card's shell; store pictures drawn by the game "
        "itself, headless; a bundle; a depot whose chunks rebuild every file exactly.",
        "tests/test_arcade.py::test_manifest_chunks_rebuild_the_files")
    tests = _tests("test_arcade.py")
    row("Witnesses", "tests/test_arcade.py, laws CM35 and CM39, goal G_S1_store_launches",
        f"{len(tests)} tests", "model",
        "The cycle runs `arcade check` on every run: each catalogue item installed, verified, repaired and played "
        "through the store.", "")
    return {"games": [g.name for g in games], "rows": rows}


def markdown(inv: dict) -> str:
    L = ["# ARCADE INVENTORY (generated by `cardmodel arcade inventory --write docs/ARCADE_INVENTORY.md`; do not "
         "edit)", "",
         f"Everything that goes into Cardmodel Arcade and its catalogue ({', '.join(inv['games']) or 'empty'}), and "
         "what the card model contributes to each piece. **made by**: `model` = computed or compiled by the model "
         "from cards; `cards` = data or card-language logic the model runs and checks; `hand` = written by hand, "
         "only built, packaged or served by the model.", "",
         "| piece | where | size | made by | what the model contributes | witness |", "|---|---|---|---|---|---|"]
    for r in inv["rows"]:
        w = f"`{r['witness']}`" if r["witness"] else ""
        L.append(f"| {r['piece']} | {r['where']} | {r['numbers']} | {r['made_by']} | {r['model']} | {w} |")
    by = {}
    for r in inv["rows"]:
        by[r["made_by"]] = by.get(r["made_by"], 0) + 1
    L += ["", f"Pieces by maker: {', '.join(f'{k} {v}' for k, v in sorted(by.items()))}.", ""]
    return "\n".join(L)


__all__ = ["compute", "markdown"]
