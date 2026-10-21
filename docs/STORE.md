# The store: what is in Cardmodel Arcade, and what the model does for each piece

Cardmodel Arcade (docs/ARCADE.md) is the model's Steam-like store: a native launcher with a store, a library and
downloads, a content service, and games compiled from cards. This page lists everything that goes into it, what
the card model contributes to each piece, and which of the products the model makes run through it today. It is
checked by the `arcade` capability (CM35, CM37) in every `cardmodel verify` and every self-run, and launched end to
end by the self-run's `store` step (CM42, `cardmodel arcade check`): every catalogue item downloaded through the
service with every chunk checked, verified, a damaged file repaired, and run natively until it draws a frame; then
every cartridge the library lists, started in its store-installed player as the launcher starts it, until it
shows the picture its cards compute.

Checked on main on 2026-10-21: `arcade build vector_duel` made build 0e79b9000ec8 in 3.4 s (465,705 bytes in 5
chunks, 10 store pictures); `arcade serve` answered the catalog, the store page, the manifest, all 5 chunks (each
equal to its SHA-256 name), the pictures and the launcher's pages; `arcade run vector_duel --frames 240` ran the
built game natively; `arcade launcher` compiled the app in 4.5 s.

Checked on `claude/frosty-lumiere-98e2b7` on 2026-10-22, with the user's library (971 Game Boy / Color cartridges
in one folder, one DS cartridge in another): `arcade check` installed, verified and repaired Vector Duel 0.4.0 and
the Game Boy Player through the store, played the player on its check cartridge (the picture its cards compute,
the save kept), then launched 971 of 971 cartridges in the installed player as the launcher does, each showing
exactly the picture its cards compute after 120 frames (927 of them more than one colour; 224 s in all, about
0.23 s a cartridge); the DS cartridge is listed and has no player yet.

## 1. Products

| product | what it is | how it runs | in the store |
|---|---|---|---|
| **Vector Duel** (`game/vector_duel`, v0.4.0) | a 1-v-1 fighting game: 3 fighters, 24 moves, 7 arenas, a 7-opponent arcade ladder, training, local versus, 13 achievements | compiled from cards to a native library + the macOS shell; `cardmodel arcade run vector_duel` without the launcher | yes: store page, screenshots, install / update / verify / play, achievements from its save |
| **Cardmodel Arcade** (`app/arcade`) | the launcher itself | `cardmodel arcade launcher [--install]` builds the app; it starts `cardmodel arcade serve` | it is the store |
| **Game Boy Player** (`system/gameboy`, v1.0.0) and the user's Game Boy / Color games | the gameboy machine card plus a card-language player (CM40); the user's own cartridges, read where they are (never copied into the repository, a depot or the library) | built and installed like a game; `cardmodel arcade run gameboy_player --rom FILE`; `cardmodel emu ROM` is the browser shell | yes: the player is a store entry; every cartridge in the user's folders is in the library (titled by its No-Intro name or its header) with the survey's verdict and a title screen the machine draws, and Play runs it in the installed player; `arcade check` launches every one through the store |
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
| the players and the library | `system/*`, `arcade/system.py`, `arcade/library.py` | a console player is the machine cards plus card-language glue built through the same pipeline; the library reads every cartridge where it is and draws its title screen headless; the system card carries a check cartridge the model assembles from the instruction cards, so the player is checked on no one's game; nothing derived from a cartridge leaves `state/` |
| the store check | `arcade/client.py` (`cardmodel arcade check`, the self-run's `store` step) | the launcher's protocol replayed in Python: install, verify, repair, play for every program; every listed cartridge started as `Launcher.playRom` starts it and compared with the picture the player module computes in the check's own process |
| the branches | `arcade/work.py` | every worktree's commits, changes, areas and programs; a branch's build state from its own `arcade list`; builds there by its own `bin/cardmodel`, served from its state folder |
| the guarantees | tests/test_arcade.py, capability `arcade`, the resource governor | a scripted redirect is a theorem of the kernel (CM35's witness); builds and compiles take machine slots and memory caps (CM30); the self-run checks the store on every cycle |

## 2b. In progress: the live page

The store's **IN PROGRESS** tab shows everything being built, while it is being built (`cardmodel/arcade/hub.py`,
`cards/app/arcade/ui/dev.js`). The projects are cards (`cards/project`, written by `tools/seed_projects.py`):

* games: Vector Duel's next version, the Game Boy Player, the DS prototype, the combat design, the systemic world;
* programs: the card model, AnyPS5 on cards and its working copy, Ting, rea-cards;
* research: the Lean bridge, Gödel-numbered functions, LLVM-IR identity, the lineage cards.

A card says what to watch (the repository, the paths in it, the games, the metrics), never how far along a
project is. The hub computes each project's status:

* its phase (active now, active today, in development, dormant, not started here, not on this machine);
* the last commit that touches its paths;
* the branches with unmerged work on it, ahead/behind main, with the worktree each is checked out in;
* the files changing right now in any worktree;
* its metrics, from the latest record of whichever checkout measured them, and the page says which;
* its builds.

Beside the projects runs an activity feed: commits and merges in every repository watched, verify runs,
self-run cycles and new builds from the last 7 days.

**Live.** The service watches the git refs and the records it reads (file times, every 2 s). When something
moves, it pushes the new snapshot to the page as a server-sent event (`/api/events`), with no reload. A verify
run in any checkout shows up in the feed within seconds. Uncommitted work is re-read every 60 s, and every
5 minutes in the other repositories.

**Detail and what waits on you (law CM41).** Each project card also carries its owner's detail: goal, where it stands,
what is in progress and left, blockers, next steps, the owning session, and when the card was last revised. A
card is marked STALE when the project changed since then. The page opens with **Waiting on you**: every user
action the cards name, ordered by how much each unblocks. The format is in docs/INTEGRATION.md section 4b.

**Early access.** A worktree's latest build of a game, when it differs from the release, is offered under its
own library id (`<game>.early.<worktree>`). It is labelled with its branch and installs beside the release. The
release channel (`/api/catalog`, the Store and Library tabs) never lists it. Its manifest and pictures come from
that worktree's depot. Its chunks come from whichever store has them, since chunks are named by their SHA-256.

**Versions and branches** (`cardmodel/arcade/work.py`, docs/ARCADE.md section 3) is the second way in, from the
Store and Library: each program's page lists its version on every branch, the Store has an *In development* row,
and the WORK tab lists every branch with its commits, uncommitted changes and programs. Installing a branch's
version replaces the program's installed build (same library id, like a beta) and is built in that worktree by
its own `bin/cardmodel` when its cards changed. Early access and branch versions are two answers to the same
question for now; they are to become one.

**Read-only.** The hub runs git with `--no-optional-locks`, so `status` never rewrites an index a session might
be committing to. It runs only `log`, `status`, `rev-list`, `for-each-ref`, `ls-files` and `worktree list`.
Ting, rea-cards and the AnyPS5 copy are read the same way; nothing is written there (`tests/test_hub.py`
checks every file under `.git`).

```bash
./bin/cardmodel arcade serve
```

Then open `http://127.0.0.1:8770/ui/index.html` (or Cardmodel Arcade) and choose IN PROGRESS.

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
