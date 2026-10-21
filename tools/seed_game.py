"""seed_game — the game as cards: moves, stances, payoff, design laws and the precedents it learned from.

Imported by tools/bootstrap.py (build time only). See game/DESIGN.md for the design these cards express.
Frame data is at 60 fps. Directions: 0..7 around the defender's plane (0 = from the right, 2 = overhead,
4 = from the left, 6 = rising, odd = diagonals), 8 = thrust. Distances: 0 close, 1 mid, 2 far.
"""
from __future__ import annotations

REGISTRIES = {
    "move": ("Combat moves as cards: kind, direction vector, frames, reach, damage, posture, stamina, momentum, "
             "poise, which stances allow them and where they lead (Vector Counter System, game/DESIGN.md).", 1),
    "stance": ("Stances: the movement graph. Allowed moves come from a stance; forced stances (recoil, broken) "
               "are where hits and counters send a fighter.", 1),
    "fighter": ("Fighters (player archetypes, enemies, bosses) as cards: a moveset and stats; everyone obeys the "
                "same move cards and the same kernel.", 1),
    "precedent": ("Combat and systems mechanics from game history: what each got right, its limit, and which part "
                  "of this design generalises it.", 1),
    "design_law": ("Computable design laws: each names an analysis the engine runs (cardmodel game check) and the "
                   "threshold that must hold.", 0),
    "payoff": ("How an exchange is scored for analysis and AI (weights per carried quantity).", 0),
}

ATT_FROM = ["neutral", "flow"]
DEF_FROM = ["neutral", "flow", "recoil"]


def attack(name, d, height, tags, startup, active, recovery, reach, damage, posture, stamina, momentum, poise=0,
           statement="", precedent=(), **extra):
    return {"name": name, "kind": "attack", "dir": d, "height": height, "tags": tags, "startup": startup,
            "active": active, "recovery": recovery, "reach": reach, "damage": damage, "posture": posture,
            "stamina": stamina, "momentum": momentum, "poise": poise, "from": ATT_FROM, "to": "flow",
            "statement": statement, "precedent": list(precedent), **extra}


MOVES = [
    attack("slash_right", 0, "high", ["horizontal", "high"], 12, 3, 14, [0, 1], 14, 10, 10, 6,
           statement="A horizontal cut from the right at head height: the bread-and-butter attack; a duck slips "
                     "it whichever side it comes from.", precedent=["for_honor_guard", "virtua_fighter_duck"], lunge=0),
    attack("slash_left", 4, "high", ["horizontal", "high"], 12, 3, 14, [0, 1], 14, 10, 10, 6,
           statement="A horizontal cut from the left at head height.",
           precedent=["for_honor_guard", "mount_and_blade_directional"], lunge=0),
    attack("overhead", 2, "high", ["vertical", "high"], 16, 4, 18, [0, 1], 22, 18, 16, 10, 4,
           statement="A committed downward cut; poise 4 shrugs off light pokes.", precedent=["dark_souls_poise"], lunge=1),
    attack("rising", 6, "low", ["vertical", "low_start"], 14, 3, 16, [0, 1], 16, 14, 12, 7,
           statement="An upward cut that starts low: beats a high guard, loses to a low one.",
           precedent=["sekiro_perilous"], lunge=1),
    attack("diagonal", 1, "high", ["diagonal", "high"], 13, 3, 15, [0, 1], 17, 12, 12, 7,
           statement="An upper-right diagonal: half-aligned with both the right and the high guard.",
           precedent=["mount_and_blade_directional"], lunge=1),
    attack("thrust", 8, "mid", ["linear", "mid"], 10, 3, 16, [1, 2], 15, 8, 10, 5,
           statement="Long reach, out of the plane: only a centre guard aligns with it; a sidestep slips it.",
           precedent=["sekiro_mikiri", "tekken_sidestep"], lunge=0),
    attack("jab", 8, "mid", ["linear", "mid", "light"], 7, 2, 9, [0, 1], 6, 4, 5, 2,
           statement="The fastest poke: interrupts startups, rewards little.", precedent=["street_fighter_frames"], lunge=0),
    attack("sweep", 0, "low", ["horizontal", "low"], 15, 3, 17, [0, 1], 12, 16, 12, 8,
           statement="A lunging low horizontal: jumpable, heavy on posture, follows a backstep.",
           precedent=["hollow_knight_pogo"], lunge=1),
    attack("heavy_overhead", 2, "high", ["vertical", "high", "heavy"], 26, 5, 24, [0, 1], 38, 30, 24, 18, 14,
           statement="Charged and armoured (poise 14): wins trades, loses everything to a read.", lunge=1,
           precedent=["dark_souls_poise", "elden_ring_charged"]),
    {"name": "feint_overhead", "kind": "feint", "dir": 2, "height": "high", "tags": ["vertical", "feint"],
     "startup": 13, "into": "thrust", "stamina": 8, "momentum": 0, "from": ATT_FROM, "to": "flow",
     "statement": "Shows an overhead, cancels at frame 13 into a thrust: beats guards and rolls timed to the "
                  "overhead, loses to anything fast and to a centre guard.", "precedent": ["for_honor_feint"]},
]
for gd, name, st in ((0, "guard_right", "Guard facing right: aligned with right slashes, half with diagonals."),
                     (2, "guard_high", "Guard high: aligned with overheads."),
                     (4, "guard_left", "Guard facing left."),
                     (6, "guard_low", "Guard low: aligned with rising cuts."),
                     (8, "guard_center", "Centre guard: the only full answer to a thrust.")):
    MOVES.append({"name": name, "kind": "guard", "guard_dir": gd, "startup": 2, "perfect": 4, "good": 9,
                  "recovery": 6, "stamina": 3, "momentum": 0, "from": DEF_FROM, "to": "neutral", "statement": st,
                  "precedent": ["for_honor_guard", "sekiro_deflect", "sf3_parry"]})
MOVES += [
    {"name": "roll", "kind": "evade", "bank_div": 0, "evades": ["all"], "iframes": [3, 14], "startup": 1, "recovery": 16,
     "move": 1, "stamina": 18, "momentum": 0, "from": DEF_FROM, "to": "neutral",
     "statement": "Invincible from frame 3 to 14 against anything, then a recovery and a step away: it "
                  "saves you, it does not punish.",
     "precedent": ["dark_souls_roll", "bloodborne_quickstep"]},
    {"name": "sidestep", "kind": "evade", "bank_div": 2, "evades": ["linear", "vertical"], "iframes": [2, 12], "startup": 1,
     "recovery": 8, "move": 0, "stamina": 8, "momentum": 0, "from": DEF_FROM, "to": "neutral",
     "statement": "Slips thrusts and vertical cuts; horizontal cuts track it.", "precedent": ["tekken_sidestep"]},
    {"name": "duck", "kind": "evade", "bank_div": 2, "evades": ["high"], "iframes": [2, 16], "startup": 1, "recovery": 6,
     "move": 0, "stamina": 6, "momentum": 0, "from": DEF_FROM, "to": "neutral",
     "statement": "Under high cuts; anything mid or low still lands.", "precedent": ["virtua_fighter_duck"]},
    {"name": "jump", "kind": "evade", "bank_div": 1, "punish": True, "evades": ["low", "low_start", "grab"], "iframes": [4, 14], "startup": 1,
     "recovery": 8, "move": 0, "stamina": 8, "momentum": 0, "from": DEF_FROM, "to": "neutral",
     "statement": "Over sweeps, rising cuts and grabs; you land on an attacker who swung under you (posture "
                  "as from a deflect) and their momentum carries into your plunge (full bank).", "precedent": ["sekiro_perilous", "hollow_knight_pogo",
                                                                     "fighting_game_throw"]},
    {"name": "step_in", "kind": "catch", "catches": ["linear"], "window": [3, 12], "startup": 3, "recovery": 12,
     "move": -1, "stamina": 6, "momentum": 0, "from": DEF_FROM, "to": "flow",
     "statement": "Steps onto a thrust and pins it: the thrust's momentum breaks the thruster's posture. "
                  "Against anything else it walks into the blade.", "precedent": ["sekiro_mikiri"]},
    {"name": "grab", "kind": "grab", "startup": 18, "active": 3, "recovery": 20, "reach": [0, 1], "lunge": 1, "damage": 10,
     "posture": 26, "stamina": 12, "momentum": 4, "from": ATT_FROM, "to": "flow",
     "statement": "Ignores guards (posture crush); loses to every attack and every evade.",
     "precedent": ["for_honor_guardbreak", "fighting_game_throw"]},
    {"name": "advance", "kind": "step", "startup": 4, "recovery": 4, "move": -1, "stamina": 2, "momentum": 0,
     "from": ["neutral", "flow"], "to": "neutral", "statement": "Close one distance band.", "precedent": []},
    {"name": "backstep", "kind": "step", "startup": 3, "recovery": 10, "move": 1, "stamina": 8, "momentum": 0,
     "from": DEF_FROM, "to": "neutral", "statement": "Open one distance band: attacks that do not lunge (or reach "
     "far) whiff; lunging attacks follow you.", "precedent": ["street_fighter_spacing"]},
    {"name": "endure", "kind": "none", "startup": 0, "recovery": 0, "stamina": 0, "momentum": 0, "from": ["broken"],
     "to": "neutral", "statement": "The only option of a broken posture: take the critical.", "precedent": ["sekiro_deathblow"]},
]

STANCES = [
    {"name": "neutral", "forced": False, "statement": "Everything is allowed."},
    {"name": "flow", "forced": False, "statement": "After an attack: the residual momentum carries into the next "
     "move (faster if it continues the direction, slower if it reverses)."},
    {"name": "recoil", "forced": True, "exits_to": "neutral", "max_exchanges": 1,
     "statement": "Forced by a deflect or redirect: guards, evades and steps only, for one exchange."},
    {"name": "broken", "forced": True, "exits_to": "neutral", "max_exchanges": 1,
     "statement": "Forced when posture fills: the next exchange is `endure` (a critical lands), then posture resets."},
]

FIGHTERS = [
    {"name": "warden", "statement": "The player archetype: the full sword moveset except advance (design law GL2 "
     "found it dead for this moveset: lunging attacks already close distance).", "hp": 200, "posture_max": 100,
     "stamina_max": 100, "moves": [m["name"] for m in MOVES if m["name"] not in ("endure", "advance")] + ["endure"]},
    {"name": "brute", "statement": "An enemy built from the same cards: heavy and armoured, no feint, no step_in.",
     "hp": 260, "posture_max": 130, "stamina_max": 90,
     "moves": ["overhead", "heavy_overhead", "sweep", "slash_right", "slash_left", "grab", "guard_high",
               "guard_right", "guard_left", "roll", "advance", "backstep", "endure"]},
    {"name": "duelist", "statement": "An enemy built from the same cards: fast, thrusts and feints, little armour.",
     "hp": 170, "posture_max": 90, "stamina_max": 120,
     "moves": ["thrust", "jab", "feint_overhead", "diagonal", "slash_right", "slash_left", "guard_center",
               "guard_high", "guard_right", "guard_left", "sidestep", "duck", "step_in", "backstep", "advance",
               "endure"]},
]

PAYOFF = {"name": "default", "statement": "Exchange value for the row fighter (the game is zero-sum: the column "
          "fighter's value is the negative).", "hp": 1.0, "posture": 0.4, "advantage": 0.6, "bank": 0.5,
          "stamina": 0.05, "broken": 25.0, "recoil": 4.0}

DESIGN_LAWS = [
    ("GL1_no_dominant_option", "No option weakly dominates every other option in the neutral exchange.",
     "dominance", None),
    ("GL2_no_dead_options", "Every option survives iterated elimination of strictly dominated strategies (by "
     "any mix of the others) in at least one representative state (distance 0/1/2, advantage -6/0/+6): nothing "
     "is dead weight.", "best_response_coverage", 1.0),
    ("GL3_two_answers_per_attack", "Every attack has at least two different kinds of answer (guard, evade, catch, "
     "attack, step) that do not lose to it.", "answers_per_attack", 2),
    ("GL4_no_universal_answer", "No defensive option breaks even against every attack.", "universal_answers", 0),
    ("GL5_risk_scales_with_reward", "Rank correlation between an attack's damage and its whiff punish window "
     "(recovery) is at least 0.5.", "risk_reward", 0.5),
    ("GL6_forced_states_exit", "Every forced stance exits within one exchange (no infinite forced loops).",
     "forced_exits", 1),
    ("GL7_rich_equilibrium", "The neutral equilibrium mixes at least 6 options, and the game value is 0 "
     "(symmetric fighters: neither side wins by construction).", "equilibrium_support", 6),
    ("GL8_counters_are_reads", "No answer is safe by itself: every defensive option loses to at least one attack.",
     "answer_risk", 1),
]

PRECEDENTS = [
    ("dark_souls_roll", "Dark Souls", 2011, "Roll with invincibility frames.", "One answer to everything; "
     "spacing and patience over reading.", "Evades cover classes of attack; only the roll covers all, at the "
     "price of the longest recovery (GL4/GL8)."),
    ("dark_souls_poise", "Dark Souls", 2011, "Poise: heavy armour keeps you from being staggered.", "Opaque "
     "numbers; trading becomes the dominant strategy when poise is high.", "Poise is a move property compared "
     "with the incoming momentum, so armour is a choice per move, visible on its card."),
    ("bloodborne_quickstep", "Bloodborne", 2015, "Short quickstep and rally (regain health by attacking back).",
     "Rally rewards aggression but not reading.", "Momentum bank: a redirected attack's momentum is banked and "
     "spent on your next attack."),
    ("sekiro_deflect", "Sekiro: Shadows Die Twice", 2019, "Timing-based deflect builds the enemy's posture.",
     "One button: direction never matters, so every attack is answered the same way.", "Deflect quality = "
     "alignment x timing: the guard must face the attack's vector and come up in time; graded outcomes."),
    ("sekiro_mikiri", "Sekiro", 2019, "Mikiri counter: step onto a thrust.", "A scripted special case for one "
     "attack type.", "step_in is an ordinary move card: it catches linear attacks and loses to everything else."),
    ("sekiro_perilous", "Sekiro", 2019, "Perilous attacks (thrust, sweep, grab) each need a specific answer.",
     "Three hard-coded kanji.", "Every attack carries tags; every evade lists the tags it slips (jump: low, duck: "
     "high, sidestep: linear/vertical)."),
    ("sekiro_deathblow", "Sekiro", 2019, "Posture break opens a deathblow.", "Binary.", "broken is a forced "
     "stance in the movement graph with its own exit law (GL6)."),
    ("for_honor_guard", "For Honor", 2017, "Directional guard (left, right, top).", "Three directions; reading "
     "is a guess between three.", "Eight plane directions plus thrust; alignment is graded (2..-2), so "
     "near-misses block instead of failing."),
    ("for_honor_feint", "For Honor", 2017, "Feints cancel an attack into another.", "Feint-spam with fast "
     "cancels.", "A feint is a move card with a cancel frame and a target move; it is slower than a direct "
     "attack, so speed beats it (GL8)."),
    ("for_honor_guardbreak", "For Honor", 2017, "Guard break beats turtling.", "Becomes a reflex test.",
     "grab: posture crush through any guard, loses to every attack and evade."),
    ("mount_and_blade_directional", "Mount & Blade", 2008, "Directional attacks and blocks; chambering.",
     "Chamber timing is hidden and hard to read.", "Opposed swings within one frame clash (alignment <= -1): "
     "both recoil, the heavier momentum pushes through."),
    ("sf3_parry", "Street Fighter III: 3rd Strike", 1999, "Parry: press toward the attack in a tiny window.",
     "High/low only.", "Timing classes (perfect/good/held) multiplied by alignment: a perfect aligned guard "
     "redirects."),
    ("street_fighter_frames", "Street Fighter II", 1991, "Frame data: startup, active, recovery, advantage.",
     "Invisible to most players.", "Every move card is frame data; advantage carries into the next exchange."),
    ("street_fighter_spacing", "Street Fighter", 1987, "Spacing and whiff punishing.", "", "Distance bands and "
     "reach on every attack; a backstep makes late attacks whiff."),
    ("tekken_sidestep", "Tekken 3", 1997, "Sidestep beats linear moves; tracking moves catch it.", "",
     "sidestep evades linear and vertical; horizontal cuts track."),
    ("virtua_fighter_duck", "Virtua Fighter", 1993, "Duck under high attacks.", "", "duck evades the high tag."),
    ("fighting_game_throw", "Fighting games", 1991, "Throws beat blocks; strikes beat throws.", "", "grab vs "
     "guard and attack vs grab are entries of the same interaction matrix."),
    ("hollow_knight_pogo", "Hollow Knight", 2017, "Downward strikes and vertical play.", "", "Height tags (high, "
     "low, low_start) make vertical position part of the vector."),
    ("elden_ring_charged", "Elden Ring", 2022, "Charged heavy attacks and guard counters.", "Guard counter is "
     "one input after any block.", "A redirect banks momentum; the counter is whatever move you choose next, "
     "boosted by the bank."),
    ("dmc_royal_guard", "Devil May Cry 3", 2005, "Royal Guard stores damage for a release.", "A meter separate "
     "from movement.", "The bank is momentum: it lives in the same quantity that speeds or slows your next move."),
    ("absolver_stances", "Absolver", 2017, "Stance-based combat decks: each move starts in one stance and ends "
     "in another.", "Decks are static.", "Stances are cards; allowed moves come from the stance, forced stances "
     "from what happened to you (the movement graph)."),
    ("nioh_ki_pulse", "Nioh", 2017, "Ki pulse: timing recovers stamina.", "", "Stamina carries between "
     "exchanges; flow continues direction for a startup discount."),
    ("exanima_physics", "Exanima / Hellish Quart", 2015, "Physically simulated momentum.", "Hard to read and "
     "to balance.", "Integer momentum on every move: deterministic, provable, and still carried."),
    ("zelda_botw_chemistry", "Zelda: Breath of the Wild", 2017, "Chemistry engine: fire, wind, water, "
     "electricity interact systemically.", "Interactions are hand-coded per system.", "World rules are logic "
     "cards; every consequence has a proof (stdlib/world.card)."),
    ("divinity_surfaces", "Divinity: Original Sin 2", 2017, "Surfaces and elements combine.", "", "Materials "
     "and elements are facts; combination rules are cards."),
    ("nemesis_system", "Middle-earth: Shadow of Mordor", 2014, "Enemies remember you and change.", "Memory is "
     "scripted per enemy type.", "Memory is facts that persist across ticks; grudges and fear are rules over "
     "them."),
    ("dwarf_fortress", "Dwarf Fortress", 2006, "Simulation where everything carries consequences.", "Opaque "
     "causes.", "Every derived event carries its proof tree: the game can explain why the gate burned."),
    ("arkham_freeflow", "Batman: Arkham Asylum", 2009, "One-button counters in freeflow combat.", "Counters "
     "need no read: trivial once learned.", "Anti-pattern this design forbids (GL4, GL8)."),
    ("assassins_creed_counter", "Assassin's Creed", 2007, "Counter-kill on a timed block.", "Same.",
     "Anti-pattern this design forbids."),
]


def cards() -> dict[str, list[dict]]:
    prov = {"origin": "cardmodel game design (game/DESIGN.md)", "tool": "tools/seed_game.py"}
    out = {"move": [], "stance": [], "fighter": [], "precedent": [], "design_law": [], "payoff": []}
    for m in MOVES:
        out["move"].append({**m, "category": "move", "tier": 1, "provenance": prov,
                            "depends_on": [f"precedent/{p}" for p in m.get("precedent", [])]})
    for s in STANCES:
        out["stance"].append({**s, "category": "stance", "tier": 1, "provenance": prov})
    for f in FIGHTERS:
        out["fighter"].append({**f, "category": "fighter", "tier": 1, "provenance": prov,
                               "depends_on": [f"move/{m}" for m in f["moves"]]})
    for name, game, year, mechanic, limit, ours in PRECEDENTS:
        out["precedent"].append({"name": name, "category": "precedent", "tier": 1, "game": game, "year": year,
                                 "statement": mechanic, "limit": limit, "generalised_by": ours, "provenance": prov})
    for name, statement, check, threshold in DESIGN_LAWS:
        out["design_law"].append({"name": name, "category": "design_law", "tier": 0, "statement": statement,
                                  "check": check, "threshold": threshold, "provenance": prov})
    out["payoff"].append({**PAYOFF, "category": "payoff", "tier": 0, "provenance": prov})
    return out
