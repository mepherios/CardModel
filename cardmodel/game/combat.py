"""combat — the Vector Counter System engine (game/DESIGN.md): two fighters, one exchange at a time.

An exchange: both fighters pick a move allowed by their stance at the same moment (the one with frame
advantage starts earlier). Each move card is frame data plus a vector (direction 0..8, height, tags); the
resolution is frame-accurate and every counter is decided by the card-language kernel (stdlib/combat.card,
compiled to Python once): alignment of guard and attack vectors, timing class, outcome class, damage
through, posture, momentum carried into recoil, banked into a redirect, or into the next move's startup.

Readability is a rule, not a tuning knob: a defender reacts to an attack whose startup is at least
REACTION frames (the tell is readable), timing its guard or evade to the shown attack -- so slow attacks can
be deflected or redirected by the right *vector*, fast ones only blocked or evaded raw, and feints exploit
the reaction by changing direction and timing after the tell.

Strings are chain cards (one link each: an attack that connected cancels its recovery into the next); the
exchange keeps one move per side, and ``analysis`` plays a link as the next exchange, started early by the
recovery it cancels.

Honest limits (L1): distance is three bands; movement inside an exchange is one band per step; no
projectiles; values are integers (deterministic, replayable).
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace


from ..kernel import paths

NO_DIR = 9


def load_kernel(ctx):
    """The combat kernel: stdlib/combat.card compiled to the card IR and emitted as Python (one source)."""
    from ..engines.codegen import emit_module
    from ..lang.compile import compile_file
    mod = compile_file(paths.home() / "stdlib" / "combat.card", ctx.ops, ctx.store)
    ns: dict = {"__name__": "cardmodel_combat_kernel"}
    exec(compile(emit_module(ctx.store, ctx.ops, "python", mod.ir_module()), "<combat.card>", "exec"), ns)  # noqa: S102
    return ns


@dataclass(frozen=True)
class Fighter:
    name: str
    hp: int
    posture: int = 0
    stamina: int = 100
    stance: str = "neutral"
    bank: int = 0
    residual: int = 0
    last_dir: int = NO_DIR


@dataclass(frozen=True)
class State:
    a: Fighter
    b: Fighter
    distance: int = 1
    advantage: int = 0              # frames fighter a is ahead (negative: b is ahead)
    exchange: int = 0

    def side(self, s: str) -> Fighter:
        return self.a if s == "a" else self.b


@dataclass
class Event:
    a_move: str
    b_move: str
    text: list = field(default_factory=list)
    outcome: dict = field(default_factory=dict)


class Combat:
    def __init__(self, ctx, a: str = "warden", b: str = "warden"):
        self.ctx = ctx
        self.k = load_kernel(ctx)
        self.moves = {c.name: dict(c) for c in ctx.store.cards("move")}
        self.fighters = {c.name: dict(c) for c in ctx.store.cards("fighter")}
        self.chains = {c.name: dict(c) for c in ctx.store.cards("chain")}
        pay = ctx.store.get("payoff/default")
        self.w = dict(pay) if pay else {}
        self.reaction = int(self.w.get("reaction", 12))
        self.names = (a, b)

    # -- setup -----------------------------------------------------------------------------------------------
    def start(self, distance: int = 1) -> State:
        fa, fb = self.fighters[self.names[0]], self.fighters[self.names[1]]
        return State(Fighter(fa["name"], fa["hp"], stamina=fa["stamina_max"]),
                     Fighter(fb["name"], fb["hp"], stamina=fb["stamina_max"]), distance=distance)

    def card(self, fighter: Fighter) -> dict:
        return self.fighters[fighter.name]

    def options(self, state: State, side: str) -> list[str]:
        f = state.side(side)
        if f.stance == "broken":
            return ["endure"]
        out = []
        for m in self.card(f)["moves"]:
            mv = self.moves.get(m)
            if mv is None or f.stance not in mv.get("from", []):
                continue
            if mv.get("stamina", 0) > f.stamina:
                continue
            out.append(m)
        return out or ["endure"]

    # -- timelines -----------------------------------------------------------------------------------------------
    def _attack_like(self, name: str, f: Fighter, start: int, shown: dict | None = None) -> dict:
        mv = self.moves[name]
        startup = self.k["flow_startup"](mv["startup"], f.residual, f.last_dir, mv["dir"]) if mv.get("dir") is not None \
            else mv["startup"]
        return {"kind": mv["kind"], "name": name, "start": start, "impact": start + startup, "dir": mv.get("dir"),
                "tags": set(mv.get("tags", [])), "reach": mv.get("reach", [0, 1]), "lunge": mv.get("lunge", 0),
                "damage": mv.get("damage", 0),
                "posture": mv.get("posture", 0), "momentum": mv.get("momentum", 0), "poise": mv.get("poise", 0),
                "end": start + startup + mv.get("active", 3) + mv.get("recovery", 10),
                "tell": shown or {"start": start, "impact": start + startup, "dir": mv.get("dir")}}

    def timeline(self, name: str, f: Fighter, start: int) -> dict:
        mv = self.moves[name]
        kind = mv["kind"]
        if kind == "attack" or kind == "grab":
            t = self._attack_like(name, f, start)
            if kind == "grab":
                t["tags"] = {"grab"}
                t["dir"] = None
            return t
        if kind == "feint":
            real = self._attack_like(mv["into"], replace(f, residual=0, last_dir=NO_DIR), start + mv["startup"])
            shown = self.moves.get("overhead", {})
            real["tell"] = {"start": start, "impact": start + shown.get("startup", 16), "dir": mv["dir"]}
            real["feint"] = name
            real["tags"] = set(real["tags"]) | {"feint"}
            return real
        t = {"kind": kind, "name": name, "start": start, "move": mv.get("move", 0)}
        if kind == "guard":
            t.update(guard_dir=mv["guard_dir"], up=start + mv["startup"], perfect=mv["perfect"], good=mv["good"],
                     end=start + mv["startup"] + mv.get("recovery", 6))
        elif kind == "evade":
            lo, hi = mv["iframes"]
            t.update(evades=set(mv["evades"]), lo=lo, hi=hi, end=start + mv["startup"] + hi + mv["recovery"])
        elif kind == "catch":
            lo, hi = mv["window"]
            t.update(catches=set(mv["catches"]), lo=start + lo, hi=start + hi,
                     end=start + mv["startup"] + hi + mv["recovery"])
        elif kind == "step":
            t.update(at=start + mv["startup"], end=start + mv["startup"] + mv["recovery"])
        else:
            t.update(end=start)
        return t

    # -- resolution ------------------------------------------------------------------------------------------------
    def resolve(self, state: State, ma: str, mb: str) -> tuple[State, Event]:
        k = self.k
        A, B = state.a, state.b
        sa, sb = (0, state.advantage) if state.advantage >= 0 else (-state.advantage, 0)
        ta, tb = self.timeline(ma, A, sa), self.timeline(mb, B, sb)
        ev = Event(ma, mb)
        d = {"hp": {"a": 0, "b": 0}, "posture": {"a": 0, "b": 0}, "bank": {"a": A.bank, "b": B.bank},
             "recoil": {"a": 0, "b": 0}, "landed": {"a": False, "b": False}, "stance": {},
             "busy": {"a": 0, "b": 0}}                 # hit-stun / block-stun: occupied until this frame
        dist = state.distance
        for t in (ta, tb):
            if t["kind"] == "step":
                dist = max(0, min(2, dist + t["move"]))
        strikers = {"a": ta, "b": tb}

        def strikes(t):
            return t["kind"] in ("attack", "grab")

        def in_reach(t):
            return max(0, dist - t.get("lunge", 0)) in t.get("reach", [0, 1])     # a lunge carries into the swing

        def land(side, t, mult_num=1, mult_den=1, note=""):
            other = "b" if side == "a" else "a"
            dmg = t["damage"] * mult_num // mult_den
            me = A if side == "a" else B
            if d["bank"][side]:
                dmg = k["banked_damage"](dmg, d["bank"][side])
                ev.text.append(f"{side} spends a banked {d['bank'][side]} momentum")
                d["bank"][side] = 0
            d["hp"][other] += dmg
            d["posture"][other] += t["posture"]
            d["landed"][side] = True
            d["busy"][other] = max(d["busy"][other], t["impact"] + 12 + t["posture"] // 4)      # hit-stun
            ev.text.append(f"{t['name']} by {side} lands for {dmg}{note}")
            _ = me

        def against_defense(att_side, att, dfn):
            dfs = "b" if att_side == "a" else "a"
            readable = att["tell"]["impact"] - att["tell"]["start"] >= self.reaction
            if not in_reach(att):
                ev.text.append(f"{att['name']} by {att_side} is out of reach")
                return "whiff"
            if dfn["kind"] == "guard":
                if att["kind"] == "grab":
                    land(att_side, att, note=" (a grab ignores guards)")
                    return "grab"
                al = k["align"](att["dir"], dfn["guard_dir"])
                if readable:                       # the defender times the guard to the tell
                    up = max(dfn["up"], att["tell"]["impact"] - 1)
                else:
                    up = dfn["up"]
                tc = k["timing_class"](att["impact"] - up, dfn["perfect"], dfn["good"])
                oc = k["outcome"](al, tc)
                name = ("hit", "pierce", "block", "deflect", "redirect")[oc]
                through = k["damage_through"](att["damage"], oc, al)
                if oc <= 1:
                    land(att_side, att, through if oc == 1 else 1, att["damage"] if oc == 1 else 1,
                         " through a misaligned guard" if oc == 1 else " (the guard came too late)")
                    if oc == 1:
                        d["hp"][dfs] += 0
                else:
                    d["hp"][dfs] += through
                    if oc == 2:
                        d["posture"][dfs] += k["block_posture"](att["posture"], max(0, al))
                        d["busy"][dfs] = max(d["busy"][dfs], att["impact"] + 6 + att["posture"] // 6)   # block-stun
                    else:
                        d["busy"][dfs] = max(d["busy"][dfs], att["impact"] + 2)
                        d["posture"][att_side] += k["attacker_posture"](att["momentum"], oc)
                        d["recoil"][att_side] += k["recoil_frames"](att["momentum"], oc)
                        if oc == 4:
                            d["bank"][dfs] += k["redirect_bank"](att["momentum"])
                ev.text.append(f"{dfn['name']} by {dfs} vs {att['name']}: alignment {al}, timing {tc} -> {name}"
                               + (f" (chip {through})" if oc == 2 and through else ""))
                return name
            if dfn["kind"] == "evade":
                center = (dfn["lo"] + dfn["hi"]) // 2
                start = att["tell"]["impact"] - center if readable else dfn["start"]
                lo, hi = start + dfn["lo"], start + dfn["hi"]
                if ("all" in dfn["evades"] or dfn["evades"] & att["tags"]) and lo <= att["impact"] <= hi:
                    div = self.moves[dfn["name"]].get("bank_div", 0)
                    gained = att["momentum"] // div if div else 0
                    d["bank"][dfs] += gained               # the attacker's momentum carries them past you
                    if self.moves[dfn["name"]].get("punish"):
                        d["posture"][att_side] += k["attacker_posture"](att["momentum"], 3)
                        d["recoil"][att_side] += k["recoil_frames"](att["momentum"], 3)
                    ev.text.append(f"{dfn['name']} by {dfs} slips {att['name']}"
                                   + (f" (banks {gained} momentum)" if gained else ""))
                    dfn["end"] = start + dfn["hi"] + self.moves[dfn["name"]]["recovery"]
                    return "evaded"
                land(att_side, att, note=f" ({dfn['name']} did not cover it)")
                return "hit"
            if dfn["kind"] == "catch":
                if dfn["catches"] & att["tags"] and dfn["lo"] <= att["impact"] <= dfn["hi"]:
                    d["posture"][att_side] += k["attacker_posture"](att["momentum"] + 6, 4)
                    d["recoil"][att_side] += k["recoil_frames"](att["momentum"], 4)
                    ev.text.append(f"step_in by {dfs} catches {att['name']}: posture crush")
                    return "caught"
                land(att_side, att, 5, 4, " (counter-hit: stepped into it)")
                return "hit"
            if dfn["kind"] == "none":                 # endure: a broken posture takes the critical
                land(att_side, att, 2, 1, " (critical on a broken posture)")
                return "critical"
            land(att_side, att, note="")
            return "hit"

        if strikes(ta) and strikes(tb):
            ra, rb = in_reach(ta), in_reach(tb)
            if ra and rb and abs(ta["impact"] - tb["impact"]) <= 1 and ta["dir"] is not None and tb["dir"] is not None \
                    and k["align"](ta["dir"], tb["dir"]) <= -1:
                diff = ta["momentum"] - tb["momentum"]
                ev.text.append(f"blades clash: {ma} vs {mb}")
                d["recoil"]["a"] += 6
                d["recoil"]["b"] += 6
                if diff >= 4:
                    land("a", ta, 1, 2, " (pushed through the clash)")
                elif diff <= -4:
                    land("b", tb, 1, 2, " (pushed through the clash)")
                ev.outcome["clash"] = True
            else:
                first = "a" if ta["impact"] < tb["impact"] else "b" if tb["impact"] < ta["impact"] else None
                order = [first] if first else ["a", "b"]
                hit_first = {}
                for s in order:
                    t, o = strikers[s], strikers["b" if s == "a" else "a"]
                    if in_reach(t):
                        land(s, t, 5, 4, " (counter-hit)") if first else land(s, t, note=" (trade)")
                        hit_first[s] = True
                if first and hit_first.get(first):
                    other = "b" if first == "a" else "a"
                    o = strikers[other]
                    if o.get("poise", 0) >= strikers[first]["momentum"] and in_reach(o):
                        land(other, o, note=" (armoured through it)")
                    else:
                        ev.text.append(f"{o['name']} by {other} is interrupted")
                elif first and not hit_first.get(first):
                    other = "b" if first == "a" else "a"
                    if in_reach(strikers[other]):
                        land(other, strikers[other], note=" (whiff punish)")
        elif strikes(ta):
            ev.outcome["a"] = against_defense("a", ta, tb)
        elif strikes(tb):
            ev.outcome["b"] = against_defense("b", tb, ta)
        else:
            ev.text.append(f"{ma} and {mb}: no contact")
        return self._commit(state, ta, tb, d, ev, dist)

    def _commit(self, state, ta, tb, d, ev, dist):
        k = self.k
        out = {}
        for side, t, f in (("a", ta, state.a), ("b", tb, state.b)):
            fc = self.card(f)
            mv = self.moves.get(t["name"], {})
            if t.get("feint"):
                mv = self.moves.get(t["feint"], mv)
            hp = f.hp - d["hp"][side]
            posture = f.posture + d["posture"][side]
            stamina = min(fc["stamina_max"], f.stamina - mv.get("stamina", 0) + int(self.w.get("stamina_regen", 10)))
            stance = mv.get("to", "neutral")
            residual, last_dir = 0, NO_DIR
            if t["kind"] in ("attack", "grab") and t.get("dir") is not None:
                residual, last_dir = t["momentum"] // 2, t["dir"]
            if d["recoil"][side]:
                stance = "recoil"
            if f.stance == "broken":
                stance, posture = "neutral", 0
            elif posture >= fc["posture_max"]:
                stance = "broken"
                ev.text.append(f"{side}'s posture breaks")
            elif not d["recoil"][side] and not d["hp"][side] and not d["posture"][side]:
                posture = max(0, posture - int(self.w.get("posture_regen", 6)))
            out[side] = replace(f, hp=hp, posture=min(posture, fc["posture_max"]), stamina=max(0, stamina),
                                stance=stance, bank=d["bank"][side], residual=residual, last_dir=last_dir)
        end_a = max(ta["end"], d["busy"]["a"]) + d["recoil"]["a"]
        end_b = max(tb["end"], d["busy"]["b"]) + d["recoil"]["b"]
        cap = int(self.w.get("adv_cap", 20))
        adv = max(-cap, min(cap, end_b - end_a))
        for t, s in ((ta, "a"), (tb, "b")):
            if t["kind"] in ("evade", "catch") and t.get("move"):
                dist = max(0, min(2, dist + t["move"]))
        ev.outcome.update({"advantage": adv, "distance": dist, "damage": d["hp"], "posture": d["posture"]})
        return State(out["a"], out["b"], dist, adv, state.exchange + 1), ev

    # -- scoring ---------------------------------------------------------------------------------------------------------
    def value(self, before: State, after: State, side: str = "a") -> float:
        w = self.w
        me_b, op_b = (before.a, before.b) if side == "a" else (before.b, before.a)
        me_a, op_a = (after.a, after.b) if side == "a" else (after.b, after.a)
        adv = after.advantage if side == "a" else -after.advantage
        v = w.get("hp", 1.0) * ((op_b.hp - op_a.hp) - (me_b.hp - me_a.hp))
        v += w.get("posture", 0.4) * ((op_a.posture - op_b.posture) - (me_a.posture - me_b.posture))
        v += w.get("advantage", 0.6) * adv
        v += w.get("bank", 0.5) * ((me_a.bank - me_b.bank) - (op_a.bank - op_b.bank))
        v += w.get("stamina", 0.05) * ((me_a.stamina - me_b.stamina) - (op_a.stamina - op_b.stamina))
        for f, sign in ((op_a, 1), (me_a, -1)):
            if f.stance == "broken":
                v += sign * w.get("broken", 25.0)
            if f.stance == "recoil":
                v += sign * w.get("recoil", 4.0)
        return round(v, 6)

    def position(self, after: State, side: str = "a") -> float:
        """The part of ``value`` that is where the exchange left the fighters (frame advantage, forced stances),
        not what it changed: the leaf estimate a deeper search replaces with what follows."""
        w = self.w
        me, op = (after.a, after.b) if side == "a" else (after.b, after.a)
        v = w.get("advantage", 0.6) * (after.advantage if side == "a" else -after.advantage)
        for f, sign in ((op, 1), (me, -1)):
            if f.stance == "broken":
                v += sign * w.get("broken", 25.0)
            if f.stance == "recoil":
                v += sign * w.get("recoil", 4.0)
        return round(v, 6)

    def over(self, state: State) -> bool:
        return state.a.hp <= 0 or state.b.hp <= 0


__all__ = ["Combat", "Event", "Fighter", "NO_DIR", "State", "load_kernel"]

