"""game — a game card compiled into one card-IR module, and that module run in any engine.

The sources are the tables ``gen.generate`` derives from the game's cards, the combat kernel the game names
(``stdlib/combat.card``), and the card-language logic files listed on the game card. They compile into one
module exactly as a machine does (``machine/build.py``): globals, arrays, functions, a generated ``reset_all``,
every global and array exported so a shell can reach the screen, sound, input and save arrays the game card
describes. The module is cached by a hash of everything that went into it.

``Game`` drives a module headless (tests, screenshots, the build's store media): ``frame(input)`` advances
one frame and returns whether the game asked to quit.

Honest limits (L1): the reference interpreter is far too slow for a software renderer's frames, so the
engines compared on whole frames are the native and the Python emissions (short runs).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ..kernel import paths
from ..lang.compile import compile_sources
from ..machine import build as Bd
from ..machine import native as N
from . import gen


def game_card(store, name: str):
    card = store.get(name if "/" in name else f"game/{name}")
    if card is None:
        raise KeyError(f"no game card game/{name}")
    return card


def sources(ctx, card) -> tuple[list[tuple[str, str]], dict]:
    tables, report = gen.generate(ctx, card)
    srcs = [(tables, f"{card.qualified} (generated tables)")]
    if card.get("kernel"):
        p = paths.home() / card["kernel"]
        srcs.append((p.read_text(encoding="utf-8"), card["kernel"]))
    for rel in card.get("logic") or []:
        srcs.append(((card.path / rel).read_text(encoding="utf-8"), f"{card.qualified}/{rel}"))
    return srcs, report


def module(ctx, name: str, use_cache: bool = True) -> dict:
    card = game_card(ctx.store, name)
    srcs, report = sources(ctx, card)
    h = hashlib.sha256()
    for text, label in srcs:
        h.update(label.encode() + b"\0" + text.encode() + b"\0")
    h.update(Path(__file__).read_bytes())
    key = h.hexdigest()[:20]
    cache = ctx.state_root / "arcade" / f"{card.name}-{key}.json"
    if use_cache and cache.is_file():
        return json.loads(cache.read_text(encoding="utf-8"))
    mod = compile_sources(srcs, ctx.ops, ctx.store, name=card.name)
    ir = mod.ir_module((card.get("entry") or {}).get("frame"))
    ir["functions"].append(Bd.reset_function(ir))
    for x in (*ir.get("globals", []), *ir.get("arrays", [])):
        x["export"] = True
    ir["game"] = card.name
    ir["hash"] = key
    ir["tables"] = report
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(ir), encoding="utf-8")
    return ir


class Game:
    """One running instance of a game module (headless): the screen as RGBA bytes, the sound as PCM."""

    def __init__(self, ctx, name: str, engine: str = "native", fresh: bool = False):
        self.ctx = ctx
        self.card = game_card(ctx.store, name)
        self.ir = module(ctx, name)
        self.m = N.load(ctx, self.ir, engine, fresh=fresh)
        entry = self.card.get("entry") or {}
        self.f_init, self.f_frame = entry.get("init", "game_init"), entry.get("frame", "game_frame")
        self.quit_flag = entry.get("quit", "quit_req")
        scr = self.card["screen"]
        self.w, self.h, self.fb = int(scr["width"]), int(scr["height"]), scr["array"]
        self.m.call("reset_all")
        self.m.call(self.f_init)

    def frame(self, input1: int = 0, input2: int = 0) -> int:
        return self.m.call(self.f_frame, input1, input2)

    def screen(self) -> bytes:
        return self.m.read(self.fb)

    def rgb(self) -> bytes:
        px = self.screen()
        return b"".join(px[i:i + 3] for i in range(0, len(px), 4))

    def png(self, scale: int = 1) -> bytes:
        from ..machine.gb import png
        return png(self.rgb(), self.w, self.h, scale)

    def drain_audio(self) -> bytes:
        a = self.card["audio"]
        n = self.m.get(a["count"])
        data = self.m.read(a["array"], 0, n) if n else b""
        self.m.set(a["count"], 0)
        return data

    def state_hash(self) -> str:
        h = hashlib.sha256()
        h.update(self.screen())
        for g in self.ir.get("globals") or []:
            h.update(str(self.m.get(g["name"])).encode())
        return h.hexdigest()[:16]


def bits(card, names) -> int:
    """An input mask from button names (the game card's ``input.bits`` order)."""
    order = card["input"]["bits"]
    out = 0
    for n in names:
        out |= 1 << order.index(n)
    return out


__all__ = ["Game", "bits", "game_card", "module", "sources"]
