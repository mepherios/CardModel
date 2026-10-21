# The arcade: native games built from cards, and the launcher that ships them

**Vector Duel** is a complete game whose every rule, number, picture and sound is decided by cards: the move
and fighter cards of the Vector Counter System (game/DESIGN.md), the combat kernel `stdlib/combat.card`, and the
game's own card-language logic. It compiles through the C language card into native code and runs in a native
macOS window. **Cardmodel Arcade** is the launcher: a store, a library and downloads, laid out like the big PC
launchers, that installs builds of the game made by the card model and launches them (law CM35).

```bash
./bin/cardmodel arcade launcher --install        # build Cardmodel Arcade.app into ~/Applications
```

```bash
./bin/cardmodel arcade build vector_duel         # cards -> native package -> depot (the launcher's download)
```

```bash
./bin/cardmodel arcade serve                     # the content service on 127.0.0.1:8770 (the launcher starts it)
```

```bash
./bin/cardmodel arcade run vector_duel           # the latest build, natively, without the launcher
```

```bash
./bin/cardmodel arcade list                      # games, versions, latest builds, whether the cards changed
```

```bash
./bin/cardmodel arcade check                     # every catalogue item launched through the store (CM39)
```

```bash
./bin/cardmodel arcade inventory                 # everything that goes into the store, and what the model gives each
```

## 1. What is a card here

| card | holds |
|---|---|
| `game/vector_duel` | the game's data: title, version, changelog, strings, music, ladder, achievements, store text, the screen / audio / input / save interface; `logic` lists its card-language files next to it |
| `game/vector_duel/*.card` | the game: frame loop, software renderer, duel, AIs, drawing, screens, synth, save (`core`, `gfx`, `duel`, `ai`, `draw`, `screens`, `audio`, `save`) |
| `move/*`, `fighter/*`, `payoff/default`, `stdlib/combat.card` | the rules (the same cards `cardmodel game check` proves laws about) |
| `asset/font_5x7` | the font |
| `platform/macos` | how a module becomes a macOS app: the library's language card, the effect shell (`GameShell.swift`) and its compile command, the bundle layout, the icon tool |
| `app/arcade` | the launcher: `Launcher.swift` (the native client) and `ui/` (its pages) |

The card language has no strings or records, so `cardmodel/arcade/gen.py` turns the data cards into integer tables
the logic reads (one array per move-card field, the glyph rows, the strings as character codes, the music as
step tables, the ladder). It also solves, exactly, the equilibrium of the exchange game for every fighter pair and
distance with the model's own simplex (`cardmodel/game/analysis.py`): the equilibrium AI samples those mixes.

## 2. From cards to a download

```
game card + logic ──gen + card language──▶ one card-IR module (cardmodel/arcade/game.py)
                  ──C card──▶ game.dylib          platform card's shell ──swiftc──▶ executable
the module, headless ──▶ icon, poster, title and duel screenshots (the store's pictures)
                  ──▶ Vector Duel.app ──▶ depot: manifest + 1 MiB chunks named by their SHA-256
```

`cardmodel/arcade/build.py` does this; nothing in it names a language or a platform (the cards do). A build's id
is the hash of its library, shell, interface and version; `build_due` (the service's view) compares the hash of
the game's sources (its cards, logic, the platform shell, the build code) with the latest build's, so any change
to the cards shows up in the launcher as an update.

The service (`cardmodel/arcade/server.py`, stdlib HTTP) serves the catalog, store pages, build progress, manifests,
chunks (optionally at a bandwidth limit), the pictures and the launcher's pages. It re-reads the cards when they
change on disk; code changes need a restart.

## 3. The launcher

`Launcher.swift` is a native window around the pages plus the client a page cannot be:

* **Install / update**: asks the service to build if the cards changed (progress: the six build steps), fetches
  the manifest, downloads only the chunks it does not already have (an update reuses every unchanged chunk of
  the installed build, read back and re-checked), checks each chunk's and each file's SHA-256, assembles the files
  in a staging folder and swaps it in.
* **Verify integrity**: re-hashes every installed file against the manifest and re-acquires what fails.
* **Play**: starts the game's executable, keeps play time and last played; **achievements** come from the game's
  save (one byte each from offset 32, the layout `save.card` documents).
* Everything lives in `~/Library/Application Support/Cardmodel Arcade/` (`library/`, `saves/`, `launcher.json`).

The pages (`cards/app/arcade/ui/`) are Store (featured, store pages with screenshots, about, requirements,
achievements, patch notes), Library (sidebar, hero, the big button: Install / Update / Play / Stop, stats, manage
menu), Downloads (rate graph, progress, pause, cancel), News, a profile, and settings (bandwidth limit).

## 4. The game

* **Controls**: W A S D or the arrows point the vector (and walk); J attack, K heavy, U feint, L guard (hold),
  Space evade, I catch; Esc pause, F full screen. P2: arrows + numpad 1 2 3 0 4 5. Gamepads: stick, A attack,
  X heavy, right shoulder guard, B evade, Y feint, left shoulder catch.
* **The rule on screen**: while an opponent's attack winds up, a red arc around you shows where it comes from; it
  flashes white in the frames where raising the matching guard (L + that direction) makes it come up within the
  guard card's perfect window before the impact: a redirect. Your guard is a blue arc. Every outcome (hit,
  pierce, block, deflect, redirect, evade, catch, grab, posture break, critical) is the kernel's.
* **Modes**: arcade (six opponents from the game card's ladder: habit, opportunist, two readers, the equilibrium,
  the boss), training (a dummy that stands, guards, attacks or reads you), local versus, options (music, sound,
  vector arcs, difficulty).
* **The AIs press buttons** like a player and see what a player sees: the other's tell once it has been up for
  their reaction time, and only readable tells (startup of at least the payoff card's reaction frames). The
  reader counts what you lean on and says so on screen.

## 5. Witnesses

`tests/test_arcade.py`: the tables come from the cards; the module gives the same state in the native and the
Python emission; a scripted versus exchange in which a high guard comes up one frame before an overhead lands is
a redirect, and an early guard only blocks (no HP through when aligned, posture taken); the build's chunks
reassemble its files exactly; the service serves catalog, manifest and chunks; the native package runs headless;
every catalogue item launches from the store (below); the inventory is in sync with the cards; a headless run
never writes the player's save; the launcher is pointed at the main checkout when installed from a worktree.

**The store, end to end** (`cardmodel arcade check`, law CM39, goal G_S1, a stage of every cycle): for every game in
the catalogue, `arcade/client.py` does what `Launcher.swift` does, through the service on a free local port: asks
for a build when the cards changed and waits for it, downloads every chunk and checks its SHA-256 and every file's,
assembles and installs the files in a temporary library, verifies them, damages one file and repairs it (only that
file is fetched again: the launcher's verify -> repair), runs the installed executable headless with its own save
folder, and looks at the frame it drew (more than one colour). It also checks that the launcher's pages are served
and name only API endpoints the service has; `--launcher` compiles the launcher. The player's installation in
~/Library/Application Support is never touched.

**What goes into the store** is docs/ARCADE_INVENTORY.md, generated by `cardmodel arcade inventory --write
docs/ARCADE_INVENTORY.md` from the cards and files: every piece, its size, who made it (`model`, `cards` or `hand`)
and what the model contributes to it. In short: the game, its rules, its kernel, its tables, its font and its
store pictures are cards the model compiles, solves, proves things about and runs; the effect shell, the
launcher and its pages are hand-written and only built, packaged and served by the model.

## 6. Honest limits

* macOS only (one platform card), built for this Mac's architecture, signed only ad hoc by the linker.
* The launcher remembers a checkout's path to start the service: after moving the repository, run
  `cardmodel arcade launcher --install` again. Installed from a linked worktree, it now points at the main checkout
  (`--home` chooses another); the copy installed on 2026-10-21 still points at the worktree it was built in.
* The catalogue holds the games built from game cards (Vector Duel). The Game Boy library (each ROM a library entry
  built from the machine cards) is the ROADMAP's next arcade item, not built.
* The game is a 480 x 270 software renderer with stick-figure fighters; the AIs' strength is tuned by hand in
  `ai.card` (reaction, accuracy, timing per level), not learned.
* The store pictures are fixed moments of a scripted run.
