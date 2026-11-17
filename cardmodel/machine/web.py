"""web — a machine session as a web page that checks itself against a native run.

A session is recorded on a process engine (the JavaScript module the cards emit, in Node): every request batch it
sends (``native.ProcessMachine.transcript``). The same batches are then answered by a reference engine (the
native C library by default) through ``native.serve_request``, so the expected answers come from native code, not
from JavaScript. ``page`` writes one self-contained HTML file from the hosting platform card's ``page`` and
``page_replay`` templates: the module, its request server, the batches and the expected answers. Opened in any
browser (no server, no network), it replays the session and says whether every answer is the same.

``gameboy_session`` records a Game Boy session through the ordinary ``GameBoy`` effect shell, so the page holds
exactly what the shell asked of the machine. ``check_page`` opens a page in Chromium (the card's ``page_check``
driver) and returns its verdict.

Honest limits (L1): the page replays a recorded session; it does not take input of its own, and it has no display:
the frames are among the checked answers, not drawn.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from ..engines import probes
from ..kernel import resources
from . import native as N


def _script_json(value) -> str:
    """JSON safe inside a <script> element."""
    return json.dumps(value, separators=(",", ":")).replace("</", "<\\/")


def platform_card(ctx, name: str = "browser") -> dict:
    card = N.host_platform(ctx, name)
    if card is None:
        raise N.EngineError(f"no hosting platform card {name!r}")
    return card


def page(ctx, ir: dict, transcript: list, expected: list, *, title: str, reference: str, session: str,
         engine: str = "javascript", platform: str = "browser") -> str:
    """The self-checking HTML page for a recorded session. ``engine``: what runs in the page (``javascript``: the
    module the JavaScript card emits; ``wasm``: the C card's module compiled to WebAssembly)."""
    card = platform_card(ctx, platform)
    parts = N.process_parts(ctx, engine.partition("@")[0])
    if parts is None:
        raise N.EngineError(f"engine {engine} cannot run in a page")
    module, _, _ = N.served_module(ctx, ir, {**parts, "host": card})
    if "</script" in module.lower():
        raise N.EngineError("the emitted module contains '</script'; it cannot be inlined in a page")
    body = (card["page_replay"].replace("@batches@", _script_json(transcript))
            .replace("@expected@", _script_json(expected))
            .replace("@reference@", reference).replace("@machine@", str(ir.get("machine", "?")))
            .replace("@session@", session).replace("@engine@", engine))
    return card["page"].replace("@title@", title).replace("@module@", module).replace("@body@", body)


def record(ctx, ir: dict, run, engine: str = "javascript") -> tuple[list, N.Machine]:
    """Run ``run(machine)`` on a recording process machine; return (transcript, machine)."""
    m = N.load(ctx, ir, engine, record=True)
    if not isinstance(m, N.ProcessMachine):
        raise N.EngineError(f"engine {engine} is not a process engine; it cannot record a session")
    run(m)
    m._flush()
    return m.transcript, m


def expected_answers(ctx, ir: dict, transcript: list, reference: str = "native") -> tuple[list, str]:
    """The answers of a reference engine to every batch (a fresh machine). Returns (answers, engine name)."""
    m = N.load(ctx, ir, reference, fresh=True)
    try:
        return N.replay(m, transcript), m.engine
    finally:
        if hasattr(m, "close"):
            m.close()   # a cabi machine removes its private copy, a process machine stops its process


def gameboy_session(ctx, rom: bytes, frames: int, engine: str = "javascript", sample_rate: int = 0):
    """Record ``frames`` frames of a ROM through the Game Boy shell, then the state hash's reads."""
    from . import build as Bd
    from . import gb
    ir = Bd.module(ctx, "gameboy")
    out = {}

    def run(m):
        g = gb.GameBoy(ctx, rom, sample_rate=sample_rate, machine=m)
        for _ in range(frames):
            g.run_frame()
        out["serial"] = g.serial_text()
        out["state_hash"] = g.state_hash()
        out["title"] = g.info["title"]

    transcript, m = record(ctx, ir, run, engine)
    m.close()
    return ir, transcript, out


def check_page(ctx, path: Path, platform: str = "browser") -> dict:
    """Open a page in Chromium and read its verdict: {"result": "pass"|"fail"|"error", "text": ...}."""
    card = platform_card(ctx, platform)
    chk = card["page_check"]
    ok, why = probes.probe(card["embed"].get("probe"))
    if not ok:
        raise N.EngineError(f"platform {platform} is not available here: {why}")
    exe = probes.executable(ctx.language(card["embed"]["language"]).get("probe"))
    d = ctx.state_root / "build" / platform
    d.mkdir(parents=True, exist_ok=True)
    drv = d / chk["file"]
    drv.write_text(chk["text"], encoding="utf-8")
    args = [a.format(exe=exe, driver=str(drv), page=str(Path(path).resolve())) for a in chk["run"]]
    p = resources.run(args, timeout=900, stdin=subprocess.DEVNULL)
    head, _, text = (p.stdout or "").partition("\n")
    if p.returncode != 0 and head not in ("pass", "fail"):
        return {"result": "error", "text": (p.stdout + p.stderr)[-3000:]}
    return {"result": head.strip(), "text": text.strip()}


__all__ = ["check_page", "expected_answers", "gameboy_session", "page", "record"]
