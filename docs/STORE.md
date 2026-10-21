# The store: what is in Cardmodel Arcade, and what the model does for each piece

Cardmodel Arcade (docs/ARCADE.md) is the model's Steam-like store: a native launcher with a store, a library and
downloads, a content service, and games compiled from cards. This page lists everything that goes into it, what
the card model contributes to each piece, and which of the products the model makes run through it today. It is
checked by the `arcade` capability (CM35, CM37) in every `cardmodel verify` and every self-run.

Checked on main on 2026-10-21: `arcade build vector_duel` made build 0e79b9000ec8 in 3.4 s (465,705 bytes in 5
chunks, 10 store pictures); `arcade serve` answered the catalog, the store page, the manifest, all 5 chunks (each
equal to its SHA-256 name), the pictures and the launcher's pages; `arcade run vector_duel --frames 240` ran the
built game natively; `arcade launcher` compiled the app in 4.5 s.

## 1. Products

| product | what it is | how it runs | in the store |
|---|---|---|---|
| **Vector Duel** (`game/vector_duel`, v0.3.0) | a 1-v-1 fighting game: 3 fighters, 25 moves, 6 arenas, a 6-opponent arcade ladder, training, local versus, 10 achievements | compiled from cards to a native library + the macOS shell; `cardmodel arcade run vector_duel` without the launcher | yes: store page, screenshots, install / update / verify / play, achievements from its save |
| **Cardmodel Arcade** (`app/arcade`) | the launcher itself | `cardmodel arcade launcher [--install]` builds the app; it starts `cardmodel arcade serve` | it is the store |
| **Game Boy Player** (`system/gameboy`, v1.0.0) and the user's Game Boy / Color games | the gameboy machine card plus a card-language player (CM40); the user's own cartridges, read where they are (never copied into the repository, a depot or the library) | built and installed like a game; `cardmodel arcade run gameboy_player --rom FILE`; `cardmodel emu ROM` is the browser shell | yes: the player is a store entry; every cartridge in the user's folders is in the library with the survey's verdict and a title screen the machine draws, and Play runs it in the installed player |
| The DS prototype | both DS CPUs direct-booted, ARM9 code lifted, coverage measured | `cardmodel machine nds ROM` | listed: DS cartridges are in the library with their coverage, not playable (no graphics or sound yet) |
| Work in progress | every session's branch of the repository and the programs on it | the launcher's Work tab; each program's Versions and branches card | yes: a branch's version installs like a beta, built there with the branch's own code and cards |
| The combat prototype | the Vector Counter System in a terminal, against the model's AIs | `cardmodel game play`, `game duel`, `game tournament` | no: a terminal program (the native game is its successor) |
| The systemic world | a world whose events carry and explain themselves | `cardmodel game world` | no: a simulation, not a game yet |

Any new `game` card appears in the store by itself: the service lists every card of the `game` registry, and
`cardmodel arcade build ID` turns it into a download (section 3).

## 2. Everything that goes into it, and what the model does there

| piece | cards / code | what the model contributes |
|---|---|---|
| the rules | `move/*` (25), `fighter/*` (3), `payoff/default`, `stdlib/combat.card` | the same cards `cardmodel game check` proves the 8 design laws on (exact equilibrium with a checked certificate, CM28): the balance that ships is the balance that was proved; a planted imbalance is caught before anyone plays |
| the opponents | `game/vector_duel/ai.card`, the ladder on the game card | the equilibrium AI plays mixes the model solved exactly (rational simplex) for every fighter pair and distance (`arcade/gen.py`), so it cannot be exploited; the reader AI sees only readable tells (the payoff card's 12-frame reaction rule) |
| the game logic | `core`, `gfx`, `duel`, `draw`, `screens`, `audio`, `save` `.card` files | written in the card language (CM26) and compiled through the C language card: one module that also runs as a Python emission with the same state (tests/test_arcade.py) |
| the data | strings, music, arenas, ladder, achievements, store text on the game card; `asset/font_5x7` | `arcade/gen.py` turns the cards into integer tables the logic reads: changing a card changes the game, and the store marks a build due |
| the platform | `platform/macos` (`GameShell.swift`, its compile command, the bundle layout, the icon tool) | the only effect boundary (CM21, CM34): screen, sound, input and save cross it as arrays; nothing in the build code names a language or a platform |
| the build and the depot | `arcade/build.py` | content-addressed: the build id hashes the library, shell, interface and version; files are cut into 1 MiB chunks named by their SHA-256, so an update downloads only changed chunks and every file is checked |
| the store pictures | rendered headless from the module | screenshots, header, capsule, hero and icon come from the game itself, not by hand |
| the service | `arcade/server.py` (standard-library HTTP) | catalog, store pages, build progress, manifests, chunks with an optional bandwidth limit, pictures, the launcher's pages; it re-reads the cards when they change |
| the launcher | `app/arcade` (`Launcher.swift`, `ui/`) | install / update / verify integrity / play, play time, achievements read from the game's save; installs from a branch; falls back to the last good build when the cards in progress do not build |
| the players and the library | `system/*`, `arcade/system.py`, `arcade/library.py` | a console player is the machine cards plus card-language glue built through the same pipeline; the library reads every cartridge where it is and draws its title screen headless |
| the branches | `arcade/work.py` | every worktree's commits, changes, areas and programs; a branch's build state from its own `arcade list`; builds there by its own `bin/cardmodel`, served from its state folder |
| the guarantees | tests/test_arcade.py, capability `arcade`, the resource governor | a scripted redirect is a theorem of the kernel (CM35's witness); builds and compiles take machine slots and memory caps (CM30); the self-run checks the store on every cycle |

## 3. How a product gets into the store

1. A `game` card (title, version, store text, achievements, the screen / audio / input / save interface) and its
   card-language files next to it; the rules it names (`kernel`, move and fighter cards).
2. `cardmodel arcade build ID`: cards -> one card-IR module -> native library (language card) + shell (platform
   card) -> store pictures -> app bundle -> depot.
3. The service lists it; the launcher shows Install. Changing any card makes `build_due` true and the launcher
   offers the update.

## 4. Open problems (from the self-run and this check)

* The installed `~/Applications/Cardmodel Arcade.app` was installed from the games session's worktree and records
  that folder as its home: it breaks when the worktree is cleaned up. Once that branch is merged, run
  `cardmodel arcade launcher --install` from main. The self-run reports this (`app/arcade` finding) until it is fixed.
* macOS only (one platform card), ad-hoc signed, this Mac's architecture (docs/ARCADE.md section 6).
