"""gen — the tables a game's card-language logic reads, generated from its cards.

A game card names its fighters (``fighter`` cards, which name ``move`` cards), a font (an ``asset`` card), its
strings, its arcade ladder and its achievements. The logic is card language, which has no strings or records,
so everything it reads becomes integer tables and constants here: one array per move-card field (``mv_*``),
per chain-card field (``ch_*``, the string links), per fighter field (``ft_*``), the glyph rows, the strings as
character codes, the ladder, the boss's phases (``ph_*``), the exact equilibrium mixes the model computes for
every fighter pair and distance (the equilibrium AI samples them), and the duel tree's mixes for every ordered
pair of fighters and abstract state, with its string mixes (``tree_w``, ``ch_w``: the tree AI samples them).
Solving takes seconds, so those tables are cached in the state folder by a hash of every card and line of code
they come from.

Nothing here is typed by hand: every number is read from a card or computed from cards.

Honest limits (L1): strings draw in the font card's upper-case ASCII (anything else is a blank); the
equilibria are solved at neutral frame advantage for each fighter pair and distance, not for every state; the
duel tree covers every state, but of the exchange model's abstraction (``game/tree.py``).
"""
from __future__ import annotations

TAGS = ["high", "mid", "low", "horizontal", "vertical", "linear", "diagonal", "light", "heavy", "low_start",
        "feint", "grab"]
KINDS = {"none": 0, "attack": 1, "guard": 2, "evade": 3, "step": 4, "catch": 5, "grab": 6, "feint": 7}
STANCES = ["neutral", "flow", "recoil", "broken"]
AIS = ["human", "habit", "greedy", "reader", "equilibrium", "boss", "dummy", "tree"]
NO_DIR = 9
OUTCOMES = ["hit", "pierce", "block", "deflect", "redirect", "evaded", "caught"]   # duel.card's impact kinds
EQ_SCALE = 1000
TREE_SCALE = 250                 # tree mixes are bytes
ORBS = ["none", "moon", "sun"]
WEATHER = ["none", "stars", "snow", "embers", "rain", "cards", "tree"]


def _ident(name: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in name).upper()


def _array(name: str, values: list, elem: str = "Int") -> str:
    vals = [int(v) for v in values] or [0]
    rows = [", ".join(str(v) for v in vals[i:i + 24]) for i in range(0, len(vals), 24)]
    return f"array {name}: {elem}[{len(vals)}] = [" + ",\n    ".join(rows) + "]"


def tag_mask(names) -> int:
    out = 0
    for t in names or []:
        if t == "all":
            return (1 << len(TAGS)) - 1
        if t in TAGS:
            out |= 1 << TAGS.index(t)
    return out


def moves_of(store, fighters: list[str]) -> list[str]:
    names: set[str] = set()
    for f in fighters:
        names.update(store.get(f"fighter/{f}")["moves"])
    for n in list(names):
        into = store.get(f"move/{n}").get("into")
        if into:
            names.add(into)
    return sorted(names)


def chains_of(store, moves: list[str]) -> list[dict]:
    """The chain cards (string links) between moves the game's fighters have, in name order."""
    return [dict(c) for c in sorted(store.cards("chain"), key=lambda c: c.name)
            if c["from"] in moves and c["to"] in moves]


def _cached(ctx, label: str, inputs, compute):
    """compute() once per distinct inputs (cards, the code that reads them), kept in the state folder."""
    import hashlib
    import json
    from pathlib import Path
    h = hashlib.sha256(json.dumps(inputs, sort_keys=True, default=str).encode())
    for f in ("gen.py", "../game/tree.py", "../game/combat.py", "../game/analysis.py"):
        h.update((Path(__file__).parent / f).read_bytes())
    path = ctx.state_root / "arcade" / f"{label}-{h.hexdigest()[:20]}.json"
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    out = compute()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out), encoding="utf-8")
    return out


def model_inputs(ctx) -> dict:
    """Every card the exchange model reads (and the kernel), as data: the tables' cache key."""
    from ..kernel import paths
    store = ctx.store
    cards = {cat: {c.name: dict(c) for c in store.cards(cat)} for cat in ("move", "fighter", "stance", "chain")}
    pay = store.get("payoff/default")
    for cat in cards.values():
        for c in cat.values():
            c.pop("metadata", None)
    return {"cards": cards, "payoff": dict(pay) if pay else {},
            "kernel": (paths.home() / "stdlib" / "combat.card").read_text(encoding="utf-8")}


def duel_tree(ctx, fighters: list[str], moves: list[str], chains: list[dict], params: dict) -> dict:
    """The duel tree's mixes for every ordered fighter pair and abstract state (x TREE_SCALE), and its string
    mixes for every ordered pair, link, outcome (hit, block) and distance (x EQ_SCALE)."""
    from ..game.tree import CENTRES, Tree
    depth, discount = int(params.get("depth", 3)), float(params.get("discount", 0.75))
    centres = list(params.get("advantage", CENTRES))
    nf, nc = len(fighters), len(chains)
    tree_w: dict[tuple, list] = {}
    ch_w = [0] * (nf * nf * nc * 2 * 3)
    report = []
    for i, fi in enumerate(fighters):
        for j, fj in enumerate(fighters):
            if j < i:
                continue
            T = Tree(ctx, fi, fj, centres)
            r = T.solve(depth=depth, discount=discount)
            report.append({**r, "neutral_value": T.V[T.index(1, len(centres) // 2, 0, 0)]})
            for (me, op, side) in ((i, j, "a"), (j, i, "b")) if i != j else ((i, j, "a"),):
                w = []
                for k in range(T.n):
                    mix = T.policy(k, "a") if side == "a" else T.policy(T.mirror(k), "b")
                    row = [0] * len(moves)
                    for m, p in mix.items():
                        row[moves.index(m)] = round(p * TREE_SCALE)
                    w += row
                tree_w[(me, op)] = w
                for c, ch in enumerate(chains):
                    for o, outcome in enumerate(("hit", "block")):
                        for d in range(3):
                            mix = T.string_mix(side, ch["from"], outcome, d)
                            ch_w[(((me * nf + op) * nc + c) * 2 + o) * 3 + d] = round(mix.get(ch["name"], 0) * EQ_SCALE)
    flat = []
    for i in range(nf):
        for j in range(nf):
            flat += tree_w[(i, j)]
    from ..game.tree import cuts
    return {"tree_w": flat, "ch_w": ch_w, "adv_cut": cuts(centres), "centres": centres, "depth": depth,
            "discount": discount, "report": report}


def equilibria(ctx, fighters: list[str], moves: list[str]) -> tuple[list[int], list]:
    """Exact equilibrium row mixes (x EQ_SCALE) for fighter i against fighter j at distance d."""
    from ..game import analysis as A
    from ..game.combat import Combat
    out: list[int] = []
    report = []
    for i, fi in enumerate(fighters):
        for j, fj in enumerate(fighters):
            g = Combat(ctx, fi, fj)
            for d in range(3):
                st = g.start(distance=d)
                rows, _, M = A.matrix(g, st)
                sol = A.solve(M)
                w = [0] * len(moves)
                for name, p in zip(rows, sol["p"]):
                    w[moves.index(name)] = round(float(p) * EQ_SCALE)
                out += w
                report.append({"fighter": fi, "against": fj, "distance": d, "value": float(sol["value"])})
    return out, report


NOTE_NAMES = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
DRUMS = {".": 0, "k": 1, "s": 2, "h": 3}
RATE = 48000


def midi(tok: str) -> int:
    """'A4' -> 69, 'C#5' -> 73, 'Bb1' -> 34; '.' (a rest) -> 0."""
    if tok == ".":
        return 0
    n = NOTE_NAMES[tok[0]]
    rest = tok[1:]
    if rest[:1] == "#":
        n, rest = n + 1, rest[1:]
    elif rest[:1] == "b":
        n, rest = n - 1, rest[1:]
    return 12 * (int(rest) + 1) + n


def music_tables(tracks: list) -> list[str]:
    """The tracks as step tables (MIDI notes, drum hits), with the phase step of every MIDI note at RATE."""
    steps = max([len(t["lead"].split()) for t in tracks] or [1])
    lead, bass, drum = [], [], []
    for t in tracks:
        for name, out, conv in (("lead", lead, midi), ("bass", bass, midi), ("drums", drum, DRUMS.__getitem__)):
            toks = t[name].split()
            out += [conv(x) for x in toks] + [0] * (steps - len(toks))
    inc = [round(440.0 * 2 ** ((n - 69) / 12) * 65536 / RATE) for n in range(128)]
    return [f"const MUS_STEPS = {steps}", f"const N_TRACKS = {len(tracks)}",
            _array("mus_bpm", [t["bpm"] for t in tracks]), _array("mus_len", [len(t["lead"].split()) for t in tracks]),
            _array("mus_lead", lead), _array("mus_bass", bass), _array("mus_drum", drum), _array("note_inc", inc)]


def generate(ctx, game) -> tuple[str, dict]:
    """(card-language source of the game's tables, a report of what went in)."""
    store = ctx.store
    fighters = list(game["fighters"])
    moves = moves_of(store, fighters)
    mv = [dict(store.get(f"move/{n}")) for n in moves]
    L = ["-- generated by `cardmodel arcade` from the game's cards: do not edit (rebuild instead)"]
    L.append(f"const N_MOVES = {len(moves)}")
    L += [f"const MV_{_ident(n)} = {i}" for i, n in enumerate(moves)]
    L += [f"const K_{_ident(k)} = {v}" for k, v in KINDS.items()]
    L += [f"const TAG_{_ident(t)} = {1 << i}" for i, t in enumerate(TAGS)]
    L += [f"const ST_{_ident(s)} = {i}" for i, s in enumerate(STANCES)]
    L += [f"const AI_{_ident(a)} = {i}" for i, a in enumerate(AIS)]
    L.append(f"const NO_DIR = {NO_DIR}")

    def col(field, default=0, f=None):
        return [f(m) if f else m.get(field, default) for m in mv]

    L.append(_array("mv_kind", col("kind", f=lambda m: KINDS.get(m.get("kind", "none"), 0))))
    L.append(_array("mv_dir", col("dir", f=lambda m: m.get("dir", m.get("guard_dir", NO_DIR)))))
    L.append(_array("mv_tags", col("tags", f=lambda m: tag_mask(m.get("tags")) | (tag_mask(["grab"])
                                                                                    if m.get("kind") == "grab" else 0))))
    for field in ("startup", "active", "recovery", "damage", "posture", "stamina", "momentum", "lunge", "poise",
                  "perfect", "good", "move", "bank_div"):
        L.append(_array(f"mv_{field}", col(field, 0)))
    L.append(_array("mv_reach_lo", col("reach", f=lambda m: (m.get("reach") or [0, 1])[0])))
    L.append(_array("mv_reach_hi", col("reach", f=lambda m: (m.get("reach") or [0, 1])[1])))
    L.append(_array("mv_if0", col("iframes", f=lambda m: (m.get("iframes") or [0, -1])[0])))
    L.append(_array("mv_if1", col("iframes", f=lambda m: (m.get("iframes") or [0, -1])[1])))
    L.append(_array("mv_evades", col("evades", f=lambda m: tag_mask(m.get("evades")))))
    L.append(_array("mv_from", col("from", f=lambda m: sum(1 << STANCES.index(s) for s in m.get("from", [])
                                                           if s in STANCES))))
    L.append(_array("mv_to", col("to", f=lambda m: STANCES.index(m.get("to", "neutral")))))
    L.append(_array("mv_into", col("into", f=lambda m: moves.index(m["into"]) if m.get("into") else -1)))

    chains = chains_of(store, moves)
    L.append(f"const N_CHAINS = {len(chains)}")
    L += [f"const CH_{_ident(c['name'])} = {i}" for i, c in enumerate(chains)]
    L.append(_array("ch_from", [moves.index(c["from"]) for c in chains]))
    L.append(_array("ch_to", [moves.index(c["to"]) for c in chains]))
    L.append(_array("ch_lo", [c["window"][0] for c in chains]))
    L.append(_array("ch_hi", [c["window"][1] for c in chains]))
    L.append(_array("ch_pct", [c.get("damage_pct", 100) for c in chains]))
    L.append(_array("ch_on", [sum(1 << OUTCOMES.index(o) for o in c.get("on", []) if o in OUTCOMES) for c in chains]))

    fc = [dict(store.get(f"fighter/{f}")) for f in fighters]
    L.append(f"const N_FIGHTERS = {len(fighters)}")
    L += [f"const FT_{_ident(f)} = {i}" for i, f in enumerate(fighters)]
    L.append(_array("ft_hp", [f["hp"] for f in fc]))
    L.append(_array("ft_posture", [f["posture_max"] for f in fc]))
    L.append(_array("ft_stamina", [f["stamina_max"] for f in fc]))
    L.append(_array("ft_moves", [sum(1 << moves.index(m) for m in f["moves"]) for f in fc]))
    pay = store.get("payoff/default")
    L.append(f"const REACTION = {int((dict(pay) if pay else {}).get('reaction', 12))}")

    font = store.get(game["font"])
    first, last = int(font["first"]), int(font["last"])
    rows = []
    for code in range(first, last + 1):
        g = font["glyphs"].get(chr(code)) or ["....."] * font["height"]
        rows += [int(r.replace("#", "1").replace(".", "0"), 2) for r in g]
    L += [f"const FONT_FIRST = {first}", f"const FONT_LAST = {last}", f"const FONT_W = {font['width']}",
          f"const FONT_H = {font['height']}", f"const FONT_ADV = {font['advance']}", _array("font", rows)]

    depth = str((game.get("duel_tree") or {}).get("depth", 3))
    strings = {k: v.replace("{TREE_DEPTH}", depth) for k, v in game["strings"].items()}
    strings["S_VERSION"] = "V" + game["version"]
    arenas = game.get("arenas") or {}
    arena_ids = list(arenas)
    for a in arena_ids:
        strings["S_AR_" + _ident(a)] = arenas[a]["name"]
    for n in moves:
        strings["S_MV_" + _ident(n)] = n.replace("_", " ")
    for a in game.get("achievements", []):
        strings["S_ACH_" + _ident(a["id"])] = a["name"]
    for st in game.get("ladder", []):
        strings.setdefault(st["name"], st["name"])
    ids = sorted(strings)
    off, chars = [], []
    for k in ids:
        off.append(len(chars))
        chars += [ord(c) for c in strings[k].upper()]
    L += [f"const {k} = {i}" for i, k in enumerate(ids)]
    L += [f"const N_STRINGS = {len(ids)}", _array("str_off", off), _array("str_len", [len(strings[k]) for k in ids]),
          _array("str_chr", chars)]

    lad = game.get("ladder", [])
    L += [f"const N_STAGES = {len(lad)}",
          _array("lad_fighter", [fighters.index(s["fighter"]) for s in lad]),
          _array("lad_ai", [AIS.index(s["ai"]) for s in lad]),
          _array("lad_name", [ids.index(s["name"]) for s in lad]),
          _array("lad_level", [s.get("level", i + 1) for i, s in enumerate(lad)]),
          _array("lad_intro", [ids.index(s["intro"]) if s.get("intro") in ids else -1 for s in lad]),
          _array("lad_arena", [arena_ids.index(s["arena"]) if s.get("arena") in arena_ids else 0 for s in lad])]
    hexes = lambda key, k: [int(arenas[a][key][k] if isinstance(arenas[a][key], list) else arenas[a][key], 16)  # noqa: E731
                            for a in arena_ids] or [0]
    L += [f"const N_ARENAS = {max(1, len(arena_ids))}",
          _array("ar_sky0", hexes("sky", 0)), _array("ar_sky1", hexes("sky", 1)),
          _array("ar_ridge0", hexes("ridge", 0)), _array("ar_ridge1", hexes("ridge", 1)),
          _array("ar_floor0", hexes("floor", 0)), _array("ar_floor1", hexes("floor", 1)),
          _array("ar_lines", hexes("lines", 0)), _array("ar_orb_col", hexes("orb_col", 0)),
          _array("ar_orb", [ORBS.index(arenas[a].get("orb", "none")) for a in arena_ids] or [0]),
          _array("ar_weather", [WEATHER.index(arenas[a].get("weather", "none")) for a in arena_ids] or [0]),
          _array("ar_name", [ids.index("S_AR_" + _ident(a)) for a in arena_ids] or [0]),
          _array("mv_str", [ids.index("S_MV_" + _ident(n)) for n in moves])]
    # the boss's phases: from what share of its health each starts, how it plays, how it looks and sounds
    tracks = [t["name"] for t in game.get("music") or []]
    ph = (game.get("boss") or {}).get("phases") or [{"at": 100}]
    L += [f"const N_PHASES = {len(ph)}",
          _array("ph_at", [x.get("at", 100) for x in ph]),
          _array("ph_title", [ids.index(x["title"]) if x.get("title") in ids else -1 for x in ph]),
          _array("ph_sub", [ids.index(x["subtitle"]) if x.get("subtitle") in ids else -1 for x in ph]),
          _array("ph_ai", [AIS.index(x.get("ai", "reader")) for x in ph]),
          _array("ph_level", [x.get("level", 6) for x in ph]),
          _array("ph_strings", [x.get("strings", 0) for x in ph]),
          _array("ph_links", [x.get("links", 1) for x in ph]),
          _array("ph_aura", [int(x.get("aura", "0xC77DFF"), 16) for x in ph]),
          _array("ph_music", [tracks.index(x["music"]) if x.get("music") in tracks else -1 for x in ph]),
          _array("ph_tempo", [x.get("tempo", 100) for x in ph]),
          _array("ph_sky0", [int(x["sky"][0], 16) if x.get("sky") else -1 for x in ph]),
          _array("ph_sky1", [int(x["sky"][1], 16) if x.get("sky") else -1 for x in ph]),
          _array("ph_weather", [WEATHER.index(x["weather"]) if x.get("weather") else -1 for x in ph])]
    ach = game.get("achievements", [])
    L += [f"const N_ACH = {len(ach)}"] + [f"const ACH_{_ident(a['id'])} = {i}" for i, a in enumerate(ach)]
    L.append(_array("ach_str", [ids.index("S_ACH_" + _ident(a["id"])) for a in ach]))

    L += music_tables(game.get("music") or [])

    params = dict(game.get("duel_tree") or {})
    key = {"model": model_inputs(ctx), "fighters": fighters, "moves": moves, "tree": params}
    eq, eq_report = _cached(ctx, "equilibria", key, lambda: equilibria(ctx, fighters, moves))
    L += [f"const EQ_SCALE = {EQ_SCALE}", _array("eq_w", eq)]
    tree = _cached(ctx, "duel-tree", key, lambda: duel_tree(ctx, fighters, moves, chains, params))
    L += [f"const N_ADV = {len(tree['centres'])}", f"const N_TS = {3 * len(tree['centres']) * 16}",
          f"const TREE_SCALE = {TREE_SCALE}", f"const TREE_DEPTH = {tree['depth']}",
          _array("adv_cut", tree["adv_cut"]), _array("tree_w", tree["tree_w"], "Byte"), _array("ch_w", tree["ch_w"])]
    return "\n".join(L) + "\n", {"moves": moves, "fighters": fighters, "strings": len(ids), "equilibria": eq_report,
                                  "tree": tree["report"]}


__all__ = ["AIS", "KINDS", "STANCES", "TAGS", "generate", "moves_of", "tag_mask"]
