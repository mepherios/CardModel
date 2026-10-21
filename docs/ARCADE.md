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
./bin/cardmodel arcade library --add ~/Downloads/GB_GBC --system gameboy   # your cartridges, where they are
```

```bash
./bin/cardmodel arcade run gameboy_player --rom "path/to/game.zip"          # one of them, natively
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
| `system/gameboy`, `system/nds` | consoles your own cartridges play on: the machine card, the card-language player (`player.card`), how the library lists them (section 5) |

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
  in a staging folder and swaps it in. When the cards in progress do not build, the last good build installs
  instead (a notice says so) and the pages show the build's error with *Try the build again*; a failed build is
  remembered with what it was built from (`state/arcade/build-errors.json`), so Update only comes back when the
  cards change again.
* **Versions and branches** (`arcade/work.py`): every git worktree of the repository is a branch, a session's work
  in progress. A program's version on a branch is listed on its store and library pages and installs like a
  beta: the service builds it in that worktree with the worktree's own `bin/cardmodel` (its code, its cards) and
  serves that depot from there; whether it needs a build is the branch's own answer (its `arcade list`, asked in
  the background when its cards, its arcade code or its HEAD change). The installation remembers the branch, so
  its updates come from it; a program only a branch has is in the store as *in development*.
* **The service**: the app starts `cardmodel arcade serve` from the checkout it was installed from when it is not
  running, and again whenever the pages lose it (a crash, a restart), then reloads them.
* **Verify integrity**: re-hashes every installed file against the manifest and re-acquires what fails.
* **Play**: starts the game's executable, keeps play time and last played; **achievements** come from the game's
  save (one byte each from offset 32, the layout `save.card` documents).
* Everything lives in `~/Library/Application Support/Cardmodel Arcade/` (`library/`, `saves/`, `launcher.json`).

The pages (`cards/app/arcade/ui/`) are Store (featured, New & Noteworthy, categories, search over games, branch
versions and cartridges, store pages with screenshots, about, requirements, achievements, patch notes, versions
and branches), Library (folding groups, hero, the big button: Install / Update / Play / Stop, stats, manage menu),
Work (every branch: its last commit, the commits not on main and the files each one changed, the uncommitted
changes, the areas it touches, its programs with their build state and an Install button), Downloads (rate graph,
progress, pause, cancel), News, a profile, and settings (bandwidth limit, cartridge folders). Everything that
shows data opens something: crumbs, tags and developers list their games, a release date or size opens the
build's details, stats go to the profile or the achievements, an achievement opens its card, patch notes and
library groups fold, the service light shows the service's checkout and branch.

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

## 5. Consoles: your own cartridges (law CM40)

A **system card** makes a console a player the launcher installs like a game. `system/gameboy` names the gameboy
machine card (the LR35902 instruction cards and the hardware cards, checked by the hardware test suites, see
docs/MACHINES.md) and `player.card`, which turns it into an arcade program: it decodes the cartridge header with
the cartridge card's tables (generated into card-language arrays by `arcade/system.py`, the same rules as the
Python host), runs the machine 1/60 s per frame so the sound comes out at exactly the shell's rate, shows the last
picture the PPU finished, and keeps battery RAM and the MBC3 clock in one save (the clock catches up the time the
game was closed). `system.py` builds it through the same pipeline as a game (`gameboy_player`).

* **The shell** gained three optional fields in game.json: `cartridge` (the array the cartridge's bytes go into and
  the function that decodes them; `--rom PATH` names the file, a .zip is read in memory), `clock` (an Int64 the
  shell keeps at the Unix time) and `flush` (called before quitting). A game without them runs as before.
* **The library** (`arcade/library.py`): every file in a system's folders, read where it is, nothing copied, with
  its header, the ROM survey's verdict as a compatibility badge (verified, playable, unsupported) and a title
  screen the machine draws headless (ten seconds, no buttons; cached in `state/arcade/covers/`). The folders are
  the user's (Settings in the launcher, or `arcade library --add`), kept in `library.json` beside the saves, so no
  card carries a user's path (CM13).
* **The launcher**: Library has a group per console with search, a home of title-screen shelves, and a page per
  cartridge (Play, or Install Game Boy Player first; play time; the verdict; the header; the file). Play starts
  the installed player with `--rom` on the file and a save folder per cartridge.
* **The DS** (`system/nds`) is listed with what the DS machine does so far (its coverage report) and is not
  playable: the DS picture, sound and input hardware have no cards yet.

## 6. Witnesses

`tests/test_arcade.py`: the tables come from the cards; the module gives the same state in the native and the
Python emission; a scripted versus exchange in which a high guard comes up one frame before an overhead lands is
a redirect, and an early guard only blocks (no HP through when aligned, posture taken); the build's chunks
reassemble its files exactly; the service serves catalog, manifest and chunks; the native package runs headless.

`tests/test_arcade_systems.py` (synthetic cartridges from the card assembler): the cartridge tables come from the
card; the player configures every board as the Python host does; its picture is the machine's at the same
V-blank, with 1/60 s of sound per frame; battery RAM and the clock survive closing (an hour closed is an hour on
the cartridge's clock); No-Intro names read as titles; a zipped cartridge is listed where it is and gets a title
screen; the native package plays a zipped cartridge and shows what the module computes. On the user's own
library the player configured all 971 cartridges exactly as the host does, and its pictures matched the
machine's over 900 frames in five games.

`tests/test_arcade_work.py` (a throwaway repository with a worktree on a branch and a stand-in for its
`bin/cardmodel`): every worktree is listed with its commits not on main, its uncommitted files, its areas and
programs, and a commit with its files; the branch's program is in the catalog with its build served from the
branch (manifest, chunk, picture; unknown worktrees refused); the branch's own `arcade list` says whether it needs
a build; a build there runs the branch's cardmodel, and a failed one keeps its error (across a restart of the
service) while the last good build stays installable.

## 7. Honest limits

* macOS only (one platform card), built for this Mac's architecture, signed only ad hoc by the linker.
* The launcher remembers this checkout's path to start the service: after moving the repository, run
  `cardmodel arcade launcher --install` again.
* The game is a 480 x 270 software renderer with stick-figure fighters; the AIs' strength is tuned by hand in
  `ai.card` (reaction, accuracy, timing per level), not learned.
* The store pictures are fixed moments of a scripted run.
* A branch is asked about its programs in the background, a few seconds after it changes; until then its version
  says it is asking. A branch's build runs that branch's code, which may be broken mid-edit (then its last good
  build installs). The service only reads the other worktrees and writes under their `state/`; versions compare
  as dotted numbers.
* The Game Boy player runs the machine in the interpreter (native C, far faster than real time) without the lifted
  blocks, which are built per cartridge; a cartridge's title screen is picked by colour from its first ten
  seconds, so some show a company logo; a DMG cartridge plays as a DMG.
