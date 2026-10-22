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
| `game/vector_duel` | the game's data: title, version, changelog, strings, music, ladder, arenas, the boss's phases, the duel tree's depth, achievements, store text, the screen / audio / input / save interface; `logic` lists its card-language files next to it |
| `game/vector_duel/*.card` | the game: frame loop, software renderer, duel, AIs, drawing, screens, synth, save (`core`, `gfx`, `duel`, `ai`, `draw`, `screens`, `audio`, `save`) |
| `move/*`, `fighter/*`, `chain/*`, `payoff/default`, `stdlib/combat.card` | the rules (the same cards `cardmodel game check` proves laws about); a chain card is one link of a string |
| `asset/font_5x7` | the font |
| `platform/macos` | how a module becomes a macOS app: the library's language card, the effect shell (`GameShell.swift`) and its compile command, the bundle layout, the icon tool |
| `app/arcade` | the launcher: `Launcher.swift` (the native client) and `ui/` (its pages) |
| `system/gameboy`, `system/nds` | consoles your own cartridges play on: the machine card, the card-language player (`player.card`), how the library lists them (section 5) |

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
In progress (docs/STORE.md section 2b: every project, early access, and *Every branch*: its last commit, the
commits not on main and the files each one changed, the uncommitted changes, the areas it touches, its programs
with their build state and an Install button), Downloads (rate graph,
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
  shell keeps at the Unix time), `clockOffset` (an Int64 it keeps at the local time's offset from UTC, in seconds:
  a system card's `clock_offset`, for a console whose clock shows the local time) and `flush` (called before
  quitting). A game without them runs as before.
* **The library** (`arcade/library.py`): every file in a system's folders, read where it is, nothing copied, with
  its header, the ROM survey's verdict as a compatibility badge (verified, playable, unsupported) and a title
  screen the machine draws headless (ten seconds, no buttons; cached in `state/arcade/covers/`). The folders are
  the user's (Settings in the launcher, or `arcade library --add`), kept in `library.json` beside the saves, so no
  card carries a user's path (CM13).
* **The launcher**: Library has a group per console with search, a home of title-screen shelves, and a page per
  cartridge (Play, or Install Game Boy Player first; play time; the verdict; the header; the file). Play starts
  the installed player with `--rom` on the file and a save folder per cartridge.
* **The DS** (`system/nds`) is listed with what the DS machine does so far (its coverage report). Its cartridges
  are playable once its system card has a machine and a player (`machine`, `logic`), and not playable (with the
  card's `playable_note`) until then.
* **One cartridge as its own app** (`arcade/cartapp.py`, `cardmodel arcade app ROM [--install]`): the Game Boy
  Player with the cartridge's own code lifted into card IR (docs/MACHINES.md section 4: every block a long
  profile found or an abstract run of the machine's cards found by reasoning, every instruction also on its own,
  the code the cartridge copies into RAM), compiled
  natively and packed as `<title>.app` (with `--install`: in `~/Applications/Cardmodel Games`). The cartridge is
  read where it is when the app starts; the app shares its save folder with the library's entry for that
  cartridge. Before packing, the lifted player plays the cartridge headless next to the plain one with the same
  buttons (pictures and sound must be equal) and reports its purity: the share of instructions that ran as lifted
  card IR. The app keeps what the interpreter still ran while it was played (`profile-*.bin` beside the save; the
  shell's new `keep` and `globals` fields in game.json), and when anything did, quitting starts the app's own next
  build in the background (`relift` in game.json: at low priority, one at a time, `relift.log` beside the save),
  so the next launch runs that code as cards too.

## 6. Witnesses

`tests/test_arcade.py`: the tables come from the cards (chains, one duel tree per fighter pair at the card's
depth, the boss's phases); the module gives the same state in the native and the Python emission; a scripted
versus exchange in which a high guard comes up one frame before an overhead lands is a redirect, and an early
guard only blocks (no HP through when aligned, posture taken); a slash that hits links into an overhead that
lands at 80 %, a slash that whiffs does not link, and a struck defender holding the high guard redirects the
link (the string breaks); the boss changes phase at the card's share of health, at that phase's level and tempo,
and fights on; the build's chunks reassemble its files exactly; the service serves catalog, manifest and chunks;
the native package runs headless. `tests/test_game.py` holds the model side: GL9 and GL10 (and a planted loop and
a planted true combo that they catch), and the duel tree (depth 1 is the exchange matrix, a mirror's states are
worth exactly opposite values, a broken opponent takes the heaviest attack, linking after a hit is an option).

Measured, not witnessed (warden mirror, level 7, 20 duels a side with the sides swapped and a fresh seed per
duel): the tree AI won 39 of 40 against the reader and 39 of 40 against the equilibrium AI, and split its own
mirror 9-11. The Oracle (a duelist) at level 6 beats the fourth stage's reader (a warden, level 4) 10 of 16; at
level 3 it loses all 16.

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

`tests/test_cartapp.py` (a synthetic cartridge that copies a routine into HRAM and calls it every frame): the
lifted player equals the plain one frame by frame, every instruction it runs (the HRAM routine, HALT, EI) runs as
lifted card IR, and the app plays the cartridge from where it is and keeps what ran beside the save.

## 7. Honest limits

* macOS only (one platform card), built for this Mac's architecture, signed only ad hoc by the linker.
* The launcher remembers this checkout's path to start the service: after moving the repository, run
  `cardmodel arcade launcher --install` again.
* The game is a 480 x 270 software renderer with stick-figure fighters; the AIs' reflexes (reaction, accuracy,
  timing per level) are tuned by hand in `ai.card`; their choices come from the model (the equilibrium, the duel
  tree, the string mixes) or from the reader's counts.
* The duel tree is solved on the exchange model's abstraction of the duel (`cardmodel/game/tree.py`'s honest
  limits), not on the real-time game itself.
* The store pictures are fixed moments of scripted runs (the boss scene sets the boss's health just above its
  second phase before the slash that crosses it).
* A branch is asked about its programs in the background, a few seconds after it changes; until then its version
  says it is asking. A branch's build runs that branch's code, which may be broken mid-edit (then its last good
  build installs). The service only reads the other worktrees and writes under their `state/`; versions compare
  as dotted numbers.
* The Game Boy player runs the machine in the interpreter (native C, far faster than real time) without the lifted
  blocks, which are built per cartridge; a cartridge's title screen is picked by colour from its first ten
  seconds, so some show a company logo; a DMG cartridge plays as a DMG.
