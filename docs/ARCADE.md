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
./bin/cardmodel arcade check                     # every catalogue item launched through the store (CM42)
```

## 1. What is a card here

| card | holds |
|---|---|
| `game/vector_duel` | the game's data: title, version, changelog, strings, music, ladder, arenas, the boss's phases, the duel tree's depth, achievements, store text, the screen / audio / input / save interface; `logic` lists its card-language files next to it |
| `game/vector_duel/*.card` | the game: frame loop, software renderer, duel, AIs, drawing, screens, synth, save (`core`, `gfx`, `duel`, `ai`, `draw`, `screens`, `audio`, `save`) |
| `move/*`, `fighter/*`, `chain/*`, `payoff/default`, `stdlib/combat.card` | the rules (the same cards `cardmodel game check` proves laws about); a chain card is one link of a string |
| `asset/font_5x7` | the font |
| `platform/macos` | how a module becomes a macOS app: the library's language card, the effect shell (`GameShell.swift`) and its compile command, the bundle layout, the icon tool |
| `app/arcade` | the launcher: `Launcher.swift` (the native client) and `ui/` (its pages) |

The card language has no strings or records, so `cardmodel/arcade/gen.py` turns the data cards into integer tables
the logic reads (one array per move-card and chain-card field, the glyph rows, the strings as character codes,
the music as step tables, the ladder, the boss's phases). It also solves, exactly, the equilibrium of the
exchange game for every fighter pair and distance with the model's own simplex (`cardmodel/game/analysis.py`):
the equilibrium AI samples those mixes. And it solves the duel tree (`cardmodel/game/tree.py`) for every pair
of fighters: backward induction over 240 abstract states (distance, frame advantage in five buckets, each
fighter's posture and stance), as deep as the game card's `duel_tree.depth` (6), plus the string sub-game after
every connect. The tree AI samples those mixes. The tables are cached in the state folder by a hash of every card
and line of code they come from (solving them takes a few seconds).

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
* **Strings**: when a cut connects (a hit, a block or a pierce), attack again from a new side inside the chain
  card's window to cancel its recovery into the link (J + the direction; the press is kept through the hit's
  freeze). Links are prorated, show their own red arc, and can be redirected: that breaks the string. The
  counter shows the hits. Every link is answerable (GL10): after a clean hit the struck side is free a few frames
  before the link lands.
* **Modes**: arcade (seven opponents from the game card's ladder: habit, opportunist, two readers, the
  equilibrium, the Oracle, the boss), training (a dummy that stands, guards, attacks, attacks in strings or reads
  you; the frame data shows your last move's cancel window), local versus, options (music, sound, vector arcs,
  difficulty).
* **The AIs press buttons** like a player and see what a player sees: the other's tell once it has been up for
  their reaction time, and only readable tells (startup of at least the payoff card's reaction frames). The
  reader counts what you lean on and says so on screen. The Oracle plays the duel tree: at every decision it
  looks up its abstract state (distance, frame advantage, both postures and stances) and samples the mix the
  model solved six exchanges deep; it still reads tells to guard. Each kind decides strings its own way (the
  habit always the same link, the reader where you guard least, the tree and the equilibrium from the model's
  string mixes).
* **The Architect** fights in three phases written on the game card (`boss.phases`): each starts when its
  health falls to a share (100, 66, 33 %) and names the AI it plays (reader, then the tree), its level, how often
  and how far it strings, its colour, sky, weather, music and tempo. A phase change stops the fight, clears its
  posture and announces itself.
* **Both fighters move, then the frame's impacts are judged**: neither side acts first (two impacts on one frame
  trade, at the distance before either pushes the other back). Before 0.4 the first fighter's impact was judged
  before the second had moved, which favoured player 1 (a reader mirror went 32-8); now it is even (26-34 over 60
  duels).

## 5. Witnesses

`tests/test_arcade.py`: the tables come from the cards (chains, one duel tree per fighter pair at the card's
depth, the boss's phases); the module gives the same state in the native and the Python emission; a scripted
versus exchange in which a high guard comes up one frame before an overhead lands is a redirect, and an early
guard only blocks (no HP through when aligned, posture taken); a slash that hits links into an overhead that
lands at 80 %, a slash that whiffs does not link, and a struck defender holding the high guard redirects the
link (the string breaks); the boss changes phase at the card's share of health, at that phase's level and tempo,
and fights on; the build's chunks reassemble its files exactly; the service serves catalog, manifest and chunks;
the native package runs headless; every catalogue item launches from the store (below); a headless run never writes
the player's save; the launcher is pointed at the main checkout when installed from a worktree. `tests/test_game.py`
holds the model side: GL9 and GL10 (and a planted loop and
a planted true combo that they catch), and the duel tree (depth 1 is the exchange matrix, a mirror's states are
worth exactly opposite values, a broken opponent takes the heaviest attack, linking after a hit is an option).

Measured, not witnessed (warden mirror, level 7, 20 duels a side with the sides swapped and a fresh seed per
duel): the tree AI won 39 of 40 against the reader and 39 of 40 against the equilibrium AI, and split its own
mirror 9-11. The Oracle (a duelist) at level 6 beats the fourth stage's reader (a warden, level 4) 10 of 16; at
level 3 it loses all 16.

**The store, end to end** (`cardmodel arcade check`, law CM42, goal G_S1, the self-run's `store` step): for every
game in the catalogue, `arcade/client.py` does what `Launcher.swift` does, through the service on a free local port:
asks for a build when the cards changed and waits for it, downloads every chunk and checks its SHA-256 and every
file's, assembles and installs the files in a temporary library, verifies them, damages one file and repairs it
(only that file is fetched again: the launcher's verify -> repair), runs the installed executable headless with its
own save folder, and looks at the frame it drew (more than one colour). It also checks that the launcher's pages
are served and name only API endpoints the service has; `--launcher` compiles the launcher. The player's
installation in ~/Library/Application Support is never touched. What goes into the store, and what the model
contributes to each piece, is docs/STORE.md.

## 6. Honest limits

* macOS only (one platform card), built for this Mac's architecture, signed only ad hoc by the linker.
* The launcher remembers a checkout's path to start the service: after moving the repository, run
  `cardmodel arcade launcher --install` again. Installed from a linked worktree, it points at the main checkout
  (`--home` chooses another); the copy installed on 2026-10-21 still points at the worktree it was built in.
* The game is a 480 x 270 software renderer with stick-figure fighters; the AIs' reflexes (reaction, accuracy,
  timing per level) are tuned by hand in `ai.card`; their choices come from the model (the equilibrium, the duel
  tree, the string mixes) or from the reader's counts.
* The duel tree is solved on the exchange model's abstraction of the duel (`cardmodel/game/tree.py`'s honest
  limits), not on the real-time game itself.
* The store pictures are fixed moments of scripted runs (the boss scene sets the boss's health just above its
  second phase before the slash that crosses it).
