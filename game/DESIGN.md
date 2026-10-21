# Game design: the Vector Counter System

Working title: none yet. The story comes later. This document is the design, and every claim in it is
something the card model computes. Run the commands and you get the same numbers.

| Run | What it shows |
|---|---|
| `cardmodel game check` | the design laws on the exact equilibrium of the neutral exchange |
| `cardmodel game play --vs reader` | play it: you against the AI that reads your vectors |
| `cardmodel game tournament --duels 10 --seed 7` | the AIs against each other |
| `cardmodel game sensitivity` | which single number would change the game most |
| `cardmodel game world --impact` | the systemic world: what carried, why, and which action mattered |
| `cardmodel game kernel --lang cpp --out Combat.h` | the combat kernel as C++ (an Unreal module can include it) |

## 1. Pillars

1. **Everything carries.** Nothing resets to neutral for free. Frame advantage, momentum, posture and stamina
   carry from one exchange to the next. In the world, facts carry from tick to tick, and guards remember.
2. **Read the vector, not the button.** Every attack is a vector: a direction on the eight-point plane or a
   thrust, a height, tags, timing and weight. Every answer is a vector too. The relation between the two
   decides the outcome, on a graded scale. There is no universal parry button.
3. **Allowed and forced movement.** Stances form a movement graph. What you may do next comes from your
   stance. What happens to you (a deflect, a redirect, a broken posture) forces you into another stance. Skill
   means steering the opponent's forced movement to where your allowed movement wins.
4. **No dominant option, provably.** Design laws are cards. The engine checks them on the exact equilibrium of
   the exchange game, and a broken law names the move that broke it.
5. **The same rules for everyone.** Enemies and bosses are fighter cards built from the same move cards and the
   same kernel. Difficulty comes from their moveset and their AI's reading of you, never from special cases.
6. **A systemic world.** Fire, water, wind, sight, memory and reputation are logic rules. Any action propagates
   through them. Every consequence carries its proof, so the game can say why the tavern burned.

## 2. The exchange

Both fighters choose a move at the same moment. The fighter with frame advantage starts earlier by that many
frames (60 fps). A move card is frame data plus a vector:

* **attack**: direction 0–7 (0 = from the right, 2 = overhead, 4 = from the left, 6 = rising, odd values are
  diagonals) or 8 = thrust; height; tags; startup, active and recovery frames; reach in distance bands
  (0 close, 1 mid, 2 far); lunge; damage, posture damage, stamina; momentum; poise (armour).
* **guard**: a guard direction, a perfect window and a good window.
* **evade**: invincibility frames and the tags it slips (roll: all; sidestep: linear and vertical; duck:
  high; jump: low, rising and grabs).
* **catch** (`step_in`): pins linear attacks.
* **grab**: goes through guards.
* **feint**: cancels into another move after its tell.
* **step**: changes distance.

The kernel decides every counter. It is `stdlib/combat.card`, written in the card language, so it is exact
integer arithmetic. It is checked as theorems: eight of its ten invariants are proved by exhaustion over their
whole finite domains. It also compiles to every language card.

* **alignment** `align(a, g)` is 2 when the guard faces the attack, 1 at 45°, 0 at 90°, −1 and −2 behind
  that. A thrust aligns only with the centre guard.
* **timing class**: too late (−1), perfect (2), good (1), or just holding guard (0).
* **outcome** = alignment × timing:
  * **redirect** (≥ 4, and only when perfect and fully aligned): the attacker's momentum turns against them.
    They take posture damage of 2·m + 4, recoil for 8 + m frames, and you bank ¾ of m for your next attack.
  * **deflect** (2–3).
  * **block** (0–1): chip damage and posture damage, both worse the worse the alignment.
  * **pierce**: a guard on the wrong side lets ¾ of the damage through.
  * **hit**: the guard came too late.

**Readability is a rule.** If an attack's tell comes at least 12 frames (`reaction` on the payoff card) before
impact, a defender can time a guard or an evade to it. Slow, telegraphed attacks can therefore be redirected,
but only by the right vector. Fast ones can only be met raw. A feint shows an overhead and cancels at frame 13
into a thrust: the reacting defender is wrong in direction and in timing. That is the read inside the read.

**Momentum carries.** After an attack, half its momentum stays with you. A next move that continues the
direction (alignment ≥ 1) starts `residual/3` frames sooner. One that reverses it starts `residual/2` frames
later. That is what *allowed* means. A redirect, or a jump over a sweep, banks the opponent's momentum, and
your next landed attack spends the bank, capped at double damage. Every evade also turns the attacker's
overextension into a bank; the roll banks nothing because it moves you away.

**Forced movement.** Recoil (after being deflected or redirected) allows only guards, evades and steps for one
exchange. A broken posture allows only `endure` for one exchange, and any attack that lands on it is a
critical. Then posture resets. Design law GL6 checks that every forced stance exits.

## 3. The design laws (cards in `cards/design_law`, checked by `cardmodel game check`)

| law | what is computed | now |
|---|---|---|
| GL1 no dominant option | no row of the exchange matrix weakly dominates every other | holds |
| GL2 no dead options | every option survives iterated elimination by mixed strategies in some representative state (distance 0/1/2, advantage −6/0/+6) | holds |
| GL3 two answers per attack | ≥ 2 kinds of answer do not lose to each attack | holds |
| GL4 no universal answer | no defensive option breaks even against every attack | holds |
| GL5 risk scales with reward | Spearman(damage, recovery) ≥ 0.5 over attacks | 0.69 |
| GL6 forced states exit | recoil and broken exit within one exchange | holds |
| GL7 rich equilibrium | exact value 0 (symmetric fighters) and ≥ 6 options mixed | value 0, 8 options |
| GL8 counters are reads | every defensive option loses to some attack | holds |

The equilibrium is computed exactly: a simplex over rational numbers whose certificate is then checked
exactly. The row mix guarantees at least the value against every column, and the column mix concedes at most
the value against every row. At neutral, mid distance, the mix is mostly guards, `guard_high` 0.35 and
`guard_center` 0.21, against a spread of attacks: `jab` 0.15, the two head-height slashes 0.09 and 0.11,
`grab` 0.05, `heavy_overhead` 0.04 and `rising` 0.01. With +6 frames of advantage the value for the
advantaged side is 5.1 per exchange, so tempo carries.

### How the laws shaped the design (the balancing log)

The laws found every one of these problems. Each fix is in the move cards with its reason.

1. **Backstep beat every short attack.** It scored +12 against them, which made duck, jump and roll dead. Fix:
   attacks gained a `lunge`, so committed cuts follow a backstep.
2. **Duck and jump were dead.** Fix: horizontal slashes cut at head height, so a duck answers both sides at
   once. Every evade banks part of the attacker's momentum. Jumping over a low attack punishes it like a
   deflect, and the jump also clears grabs.
3. **`advance` was dead for the warden.** Lunges already close distance. Fix: removed from the warden's
   moveset (it stays on the duelist).
4. **The feint stopped beating a timed roll** after the roll's invincibility grew to frame 14. Fix: the cancel
   moved to frame 13.

`cardmodel game balance` automates this. A seeded local search over the move cards' numbers accepts a change
only if it reduces (failed laws, dead options, −equilibrium support). In one run it took 3 dead options to 1
and widened the equilibrium from 8 to 11 options in 150 steps.

## 4. The vector that changes the structure

`cardmodel game sensitivity` perturbs every number on every move card by ±15% and measures how exploitable the
*current* equilibrium becomes. This does not depend on which equilibrium the solver picks. The top of the
list is the design's centre of gravity: `rising.startup` 14 → 12 makes the balance exploitable by 5.2 per
exchange (via `rising`), then `heavy_overhead.damage` and `diagonal.startup`. A designer touches those
numbers last. An AI that wants to break a player's plan looks there first.

## 5. AIs

| agent | how it plays |
|---|---|
| `equilibrium` | samples the exact equilibrium of the current exchange; unexploitable per exchange |
| `reader` | tracks which vector features you lean on (kind, direction, height, tags; decaying counts), predicts your next move from them, best-responds, and mixes in the equilibrium 25% of the time so it cannot be farmed. It tells you what it thinks you lean on (`game play`). |
| `greedy` | best one-step value against a uniform opponent |
| `habit` | a predictable player (overheads and high guards) |
| `random` | uniform |

Tournament, 10 duels per pair with sides alternating, seed 7:

| agent | score |
|---|---|
| equilibrium | 32 |
| reader | 29.5 |
| greedy | 21 |
| habit | 16.5 |
| random | 1 |

The reader beats the habit 8–2 and greedy 6–1–3. It loses 4–6 to the equilibrium player, which is what
reading should do against an opponent with no habit to read.

## 6. The world: everything carries (`stdlib/world.card`)

The world is facts plus rules over a map: materials, adjacency, wind, factions. Each tick is one logic
evaluation that derives the next tick's facts.

* Fire burns three ticks, spreads to nearby wood, and is carried at once by wind.
* Water stops it and stays for four ticks.
* Guards see their post and its neighbours. They raise the alarm, run to the nearest fire, and put out fires
  they reach.
* Guards remember who they saw start a fire.
* Each new suspicion costs standing with the guard's faction, once.

In the scenario, the player lights a cart at tick 1 and douses the granary at tick 4. What follows:

1. The tavern guard sees the fire and suspects the player.
2. The guard runs to the cart and then the stable, putting out the cart, the stable and the barn.
3. The tavern burns down, because nobody was there.
4. The fire stops short of the granary and the gate.
5. The watch's standing with the player drops from 50 to 40.

`--explain 'ash(tavern)'` prints the cause chain back to `act(ignite, cart)`. `--impact` removes each action
in turn and counts how much of the final world changes:

* lighting the cart: 9 facts;
* dousing the granary: 4 facts, because without it the granary and the gate catch fire.

Every rule here is a card-language rule. The same derivation machinery gives Lean-checked proofs for the
logic theories elsewhere in the model.

## 7. Precedents (cards in `cards/precedent`)

Each precedent card records what a game got right, its limit, and which part of this design generalises it.
Twenty-nine are recorded:

* **Souls lineage**: Dark Souls (roll, poise), Bloodborne (quickstep, rally), Sekiro (deflect and posture,
  Mikiri, perilous attacks, deathblow), Elden Ring (charged attacks, guard counters), Nioh (Ki pulse).
* **Fighting games**: Street Fighter (frame data, spacing), Street Fighter III (parry), Tekken (sidestep),
  Virtua Fighter (duck), throws.
* **Directional duelling**: For Honor (guard, feint, guard break), Mount & Blade (directional blocks,
  chambering), Absolver (stances).
* **Action**: Hollow Knight (vertical play), Devil May Cry (Royal Guard).
* **Physical combat**: Exanima and Hellish Quart.
* **Systemic worlds**: Breath of the Wild (chemistry), Divinity (surfaces), Shadow of Mordor (nemesis
  memory), Dwarf Fortress (consequences).
* **Anti-patterns this design forbids** (GL4, GL8): Batman Arkham's freeflow counters and Assassin's Creed's
  counter-kill.

## 8. Building on it

* **A new move** is one card in `cards/move` (or a `card ... : move { ... }` declaration in a `.card` file).
  Then run `cardmodel game check`. If a law breaks, the report names the move. `game balance` proposes the
  numbers.
* **A new enemy** is a fighter card listing moves. Same rules, different moveset and stats.
* **The engine side.** The kernel is integer and deterministic, so every client computes the same result from
  the same inputs. That is the property lockstep and rollback netcode need, which matters for online play.
  `game kernel --lang cpp` gives the C++ to drop into an Unreal module; the move cards are JSON data the
  engine loads.
* **Next design steps.** Multi-hit strings (cancel windows as move-card edges), weapons as move sets, bosses
  as fighter cards with phase stances, a duel-tree search AI (several exchanges deep), and the world's
  factions feeding the story.
* **Story.** Deliberately not written yet: design first, story after. The world's factions, memory and
  standing are the hooks it will hang on.
