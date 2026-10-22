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
./bin/cardmodel arcade library --add "path/to/your/cartridges" --system gameboy   # your cartridges, where they are
```

```bash
./bin/cardmodel arcade run gameboy_player --rom "path/to/game.zip"          # one of them, natively
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
  cards change again. The wait for a build always ends: a build the service refuses ends it with the service's
  reason, and one it no longer knows (it restarted) is asked for again after 2 s and ends the wait 10 s later
  (`client.wait_build` is the same steps). Downloads go one at a time, like a store's queue: an Install or Update
  asked for while one runs waits its turn (*Queued*; Downloads lists it under *Up next* with *Remove*).
* **Versions and branches** (`arcade/work.py`): every git worktree of the repository is a branch, a session's work
  in progress. A program's version on a branch is listed on its store and library pages and installs like a
  beta: the service builds it in that worktree with the worktree's own `bin/cardmodel` (its code, its cards) and
  serves that depot from there; whether it needs a build is the branch's own answer (its `arcade list`, asked in
  the background when its cards, its arcade code or its HEAD change). The installation remembers the branch, so
  its updates come from it; a program only a branch has is in the store as *in development*.
* **The service**: the app starts `cardmodel arcade serve` from the checkout it was installed from when it is not
  running, and again whenever the pages lose it (a crash, a restart), then reloads them.
* **Verify integrity**: re-hashes every installed file against the manifest and re-acquires what fails.
* **Controls** (like a store's input settings, so no game needs its own): every program's page (a game, a
  console player, a cartridge) has *Configure controls*: each action of the program's card (`input.bits`) with its
  keys for player 1 and player 2 and its controller button; click + and press a key or a button. The app keeps
  them in `controls/<id>.json` (a cartridge's own, else its player's) and starts the program with
  `--controls FILE`; the shell (`GameShell.swift`) then maps those keys and buttons instead of the card's (any
  section the file gives replaces the card's; `--dump-controls` prints the mapping and quits). Letters, digits,
  punctuation, F1 to F12, the keypad, the arrows and Shift / Control / Option can be given to a game; Command stays
  with macOS. F toggles full screen only while no control uses F. A build made before this shell ignores the file
  until the program is updated.
* **Controllers**: macOS needs no driver for Xbox, PlayStation and MFi controllers (USB or Bluetooth). The
  controller button in the header shows what is connected, live; in the games the first controller is player 1
  and the second player 2 (the shell's GameController); in the launcher the stick or d-pad moves a highlight to
  the nearest thing in that direction, A clicks it (twice on a cover plays), B is Back and Menu is the library
  (the pages' Gamepad API, only while the launcher is in front and nothing it started is running).
* **Play**: starts the game's executable, keeps play time and last played; **achievements** come from the game's
  save (one byte each from offset 32, the layout `save.card` documents). A console player's button is *Your
  cartridges* (its shelf in the library): started on its own it has nothing to play.
* Everything lives in `~/Library/Application Support/Cardmodel Arcade/` (`library/`, `saves/`, `launcher.json`).
  The library folder is the truth of what is installed: at start the launcher checks `launcher.json` against it
  (an installation the record lost comes back from its own manifest, keeping its play time; a record whose folder
  is gone goes; `--check-library` prints the result without a window, in the folder `CARDMODEL_ARCADE_SUPPORT`
  names). One launcher runs at a time: opening the app again only brings it forward, so a second one is a
  reinstall or another copy, and it takes over once the first has saved and quit (two used to save their own
  records over each other's, losing installs).

The pages (`cards/app/arcade/ui/`) are Store (featured, New & Noteworthy, categories, search over games, branch
versions and cartridges, store pages with screenshots, about, requirements, achievements, patch notes, versions
and branches), Library (folding groups, hero, the big button: Install / Update / Play / Stop, stats, manage menu),
In progress (docs/STORE.md section 2b: every project, early access, and *Every branch*: its last commit, the
commits not on main and the files each one changed, the uncommitted changes, the areas it touches, its programs
with their build state and an Install button), Downloads (rate graph,
progress, pause, cancel), News, a profile, and settings (bandwidth limit, cartridge folders). Everything that
shows data opens something: crumbs, tags and developers list their games, a release date or size opens the
build's details, stats go to the profile or the achievements, an achievement opens its card, patch notes and
library groups fold, the service light shows the service's checkout and branch. A cover has its own Play button,
and a second click on a cover or a list entry plays it. The pages are rebuilt only when what they show changed
(a refresh, the app's state reports and the featured picture's turn no longer rebuild them, so a click is never
lost under a rebuild), and an open page reloads itself when the service's pages change (`/api/status` carries
their hash): a reinstalled launcher never keeps old pages on screen.

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
  shell keeps at the Unix time) and `flush` (called before quitting). A game without them runs as before.
* **The library** (`arcade/library.py`): every file in a system's folders, read where it is, nothing copied, with
  its header, the ROM survey's verdict as a compatibility badge (verified, playable, unsupported) and a title
  screen the machine draws headless (ten seconds, no buttons; cached in `state/arcade/covers/`; a screen that stays
  blank gets no picture). The service looks at every new cartridge itself in the background: its picture, and the
  survey's own run for it (`machine/survey.boot_one`: 1200 frames, the scripted taps, the same classification),
  kept by SHA-1 in `state/arcade/verdicts.json`; so no cartridge stays *not checked yet*, and each console's shelf
  says how many run. Its title is its No-Intro file name when it has one (region tags in parentheses), else the
  title in its cartridge header; the cartridge page says which. The folders are the user's (Settings in the
  launcher, or `arcade library --add`), kept in `library.json` beside the saves, so no card carries a user's path
  (CM13). Nothing derived from a cartridge (pictures, the survey, lifted code) leaves `state/`, which git ignores,
  and no depot carries one: the player is the same for every cartridge.
* **The launcher**: Library has a group per console with search, a home of title-screen shelves, and a page per
  cartridge (Play, or Install Game Boy Player first; play time; the verdict; the header; the file). Play starts
  the installed player with `--rom` on the file and a save folder per cartridge.
* **The DS** (`system/nds`) is listed with what the DS machine does so far (its coverage report) and is not
  playable: the DS picture, sound and input hardware have no cards yet.
* **The store check** (`cardmodel arcade check`, CM42; section 6) installs the player through the store like a
  game, plays it on the system card's `check_cartridge` (a program assembled from the instruction cards, no one's
  game: a checkerboard and one byte of battery RAM), then starts every cartridge the library lists in that
  installed player, as the launcher starts it.
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
the native package runs headless; every catalogue item launches from the store (below); a headless run never
writes the player's save; the launcher is pointed at the main checkout when installed from a worktree.
`tests/test_game.py` holds the model side: GL9 and GL10 (and a planted loop and
a planted true combo that they catch), and the duel tree (depth 1 is the exchange matrix, a mirror's states are
worth exactly opposite values, a broken opponent takes the heaviest attack, linking after a hit is an option).

**The store, end to end** (`cardmodel arcade check`, law CM42, goal G_S1, the self-run's `store` step): for every game in
the catalogue, `arcade/client.py` does what `Launcher.swift` does, through the service on a free local port: asks
for a build when the cards changed and waits for it, downloads every chunk and checks its SHA-256 and every file's,
assembles and installs the files in a temporary library, verifies them, damages one file and repairs it (only that
file is fetched again: the launcher's verify -> repair), runs the installed executable headless with its own save
folder, and looks at the frame it drew (more than one colour). A console player is played the way the launcher
plays a cartridge (`--rom`, its title, a save folder of its own) on its system card's check cartridge: its picture
must be the one the player module computes in the check's own process for the same bytes and frames, and the
card's byte must be in the save it left. Then every cartridge the library lists (`GET /api/library`) is started
as `Launcher.playRom` starts it: the store-installed player, the file where it is (a missing file is refused, as
the launcher refuses it), its title, a save folder per cartridge; it must run its frames, exit cleanly, keep that
folder and show exactly the picture its cards compute. A console without a player (the DS) is counted as listed,
not launchable; `--cartridges N` checks only the first N. It also checks that the launcher's pages are served
and name only API endpoints the service has; `--launcher` compiles the launcher. The player's installation in
~/Library/Application Support and the user's saves are never touched.

**What goes into the store**, and what the model contributes to each piece, is docs/STORE.md.

Measured, not witnessed (warden mirror, level 7, 20 duels a side with the sides swapped and a fresh seed per
duel): the tree AI won 39 of 40 against the reader and 39 of 40 against the equilibrium AI, and split its own
mirror 9-11. The Oracle (a duelist) at level 6 beats the fourth stage's reader (a warden, level 4) 10 of 16; at
level 3 it loses all 16.

`tests/test_arcade_systems.py` (synthetic cartridges from the card assembler): the cartridge tables come from the
card; the player configures every board as the Python host does; its picture is the machine's at the same
V-blank, with 1/60 s of sound per frame; battery RAM and the clock survive closing (an hour closed is an hour on
the cartridge's clock); No-Intro names read as titles; a zipped cartridge is listed where it is and gets a title
screen; the native package plays a zipped cartridge and shows what the module computes; a file without a No-Intro
name is titled by its header; the check cartridge comes from the system card (its board, picture and save); a
player reused for cartridge after cartridge starts each as a fresh one (and fails when the old cartridge's bytes
are left behind); every cartridge of a synthetic library (a plain file, a zip, a battery cartridge whose save
lands in its own folder, a DS file with no player) launches through the store; a cartridge moved after the
listing does not, a picture one pixel off what the cards compute fails, and no cartridge launches when its player
failed its own check; no tracked file is or zips a cartridge (checked against planted ones), and state/ and
saves/ are ignored by git. On the user's own library the player configured all 971 cartridges exactly as the host
does, its pictures matched the machine's over 900 frames in five games, and `arcade check` launched all 971
through the store with the pictures their cards compute (2026-10-22, 224 s; docs/STORE.md).

`tests/test_arcade_work.py` (a throwaway repository with a worktree on a branch and a stand-in for its
`bin/cardmodel`): every worktree is listed with its commits not on main, its uncommitted files, its areas and
programs, and a commit with its files; the branch's program is in the catalog with its build served from the
branch (manifest, chunk, picture; unknown worktrees refused); the branch's own `arcade list` says whether it needs
a build; a build there runs the branch's cardmodel, and a failed one keeps its error (across a restart of the
service) while the last good build stays installable.

`tests/test_cartapp.py` (a synthetic cartridge that copies a routine into HRAM and calls it every frame): the
lifted player equals the plain one frame by frame, every instruction it runs (the HRAM routine, HALT, EI) runs as
lifted card IR, and the app plays the cartridge from where it is and keeps what ran beside the save.

**The store, end to end** (`cardmodel arcade check`, law CM42, goal G_S1, the self-run's `store` step): for every
item in the release catalogue (the games, and the Game Boy Player, which plays a cartridge assembled from the
instruction cards: never one of your ROMs), `arcade/client.py` does what `Launcher.swift` does, through the service
on a free local port:
asks for a build when the cards changed and waits for it, downloads every chunk and checks its SHA-256 and every
file's, assembles and installs the files in a temporary library, verifies them, damages one file and repairs it
(only that file is fetched again: the launcher's verify -> repair), runs the installed executable headless with its
own save folder, and looks at the frame it drew (more than one colour). It also checks that the launcher's pages
are served and name only API endpoints the service has; `--launcher` compiles the launcher. The player's
installation in ~/Library/Application Support is never touched. What goes into the store, and what the model
contributes to each piece, is docs/STORE.md.

## 7. Honest limits

* macOS only (one platform card), built for this Mac's architecture, signed only ad hoc by the linker (an iPhone
  and iPad platform is being built in its own session).
* Controls are per program (or per cartridge), not per player profile; the stick and the d-pad always move.
* The launcher remembers a checkout's path to start the service: after moving the repository, run
  `cardmodel arcade launcher --install` again. Installed from a linked worktree, it points at the main checkout
  (`--home` chooses another).
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
* The store check's "launched" means the store's path works for that cartridge (listed, its player installed, the
  file read where it is, the picture the cards compute): it says nothing about how far the game gets, which is
  the ROM survey's verdict. After the check's 120 frames, 44 of the user's 971 cartridges still show one flat
  colour (a white or blank start), and the DS cartridge has no player.
