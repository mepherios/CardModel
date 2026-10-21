"""shell — the effect shell around a machine: video, audio, input, saves and the clock (law CM21).

The machine (the card-IR module) is pure: it maps its state and the buttons to the next state, a frame and
some audio samples. Everything that touches the world is here and only here, and none of it is lifted,
specialised or optimised:

* ``Session``: one ROM in one machine; saves battery RAM (+ the MBC3 clock in the common 48-byte trailer)
  every few seconds when it changed and at exit; adds the wall-clock time that passed since the save to the
  RTC; merges the lifter's profile at exit.
* ``run_headless``: N frames with a scripted input; writes PNG, WAV and the frame hash.
* ``serve``: a local web page (stdlib http.server + a minimal WebSocket) that shows the frames on a canvas,
  plays the samples with Web Audio and sends keyboard / gamepad input back. The emulation is paced to
  59.73 frames per second on the host clock.

Keys: arrows = D-pad, X = A, Z = B, Enter = Start, Shift or Backspace = Select (rebindable on the page).

Honest limits (L1): audio is streamed in frame-sized chunks with a small jitter buffer (a late chunk is
dropped, not stretched); one machine per server; the page binds 127.0.0.1 only.
"""
from __future__ import annotations

import base64
import hashlib
import http.server
import json
import os
import socket
import struct
import threading
import time
from pathlib import Path

from . import gb as G

FRAME_HZ = 4194304 / 70224
BUTTONS = {"right": 0x01, "left": 0x02, "up": 0x04, "down": 0x08, "a": 0x10, "b": 0x20, "select": 0x40,
           "start": 0x80}
SAVE_EVERY_S = 5.0


def parse_input(script: str | None) -> dict:
    """``"60:start,66:-,90:a+right"`` -> {frame: mask}: from that frame on, hold those buttons."""
    out = {}
    for part in (script or "").split(","):
        part = part.strip()
        if not part:
            continue
        f, _, keys = part.partition(":")
        mask = 0
        for k in keys.split("+"):
            k = k.strip().lower()
            if k and k != "-":
                if k not in BUTTONS:
                    raise ValueError(f"unknown button {k!r} (one of {', '.join(BUTTONS)})")
                mask |= BUTTONS[k]
        out[int(f)] = mask
    return out


class Session:
    def __init__(self, ctx, rom_path, engine: str = "lifted", model: str = "auto", save_dir: Path | None = None,
                 sample_rate: int = 48000, saves: bool = True, progress=None):
        self.ctx = ctx
        self.rom, self.name = G.open_rom(rom_path)
        self.gb = G.GameBoy(ctx, self.rom, engine, model=model, sample_rate=sample_rate, progress=progress)
        self.info = self.gb.info
        self.saves = saves and self.info["battery"]
        self.save_path = (save_dir or default_save_dir()) / f"{_safe(self.name)}.sav"
        self.rtc_advanced = 0
        self.last_save = time.monotonic()
        if self.saves and self.save_path.is_file():
            self.rtc_advanced = self.gb.load_save(self.save_path.read_bytes())

    def save(self, force: bool = False) -> bool:
        if not self.saves:
            return False
        if not force and not self.gb.m.get("cram_dirty"):
            return False
        data = self.gb.save_bytes()
        self.save_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.save_path.with_suffix(".sav.tmp")
        tmp.write_bytes(data)
        os.replace(tmp, self.save_path)
        self.gb.m.set("cram_dirty", 0)
        self.last_save = time.monotonic()
        return True

    def maybe_save(self) -> None:
        if self.saves and time.monotonic() - self.last_save > SAVE_EVERY_S:
            self.save()

    def close(self) -> dict:
        saved = self.save(force=False)
        prof = {}
        if self.gb.lift_report is not None:
            from . import lift
            prof = lift.save_profile(self.ctx, self.rom, self.gb.m)
        return {"saved": saved, **prof}


def default_save_dir() -> Path:
    from ..kernel import paths
    return paths.home() / "saves"


def _safe(name: str) -> str:
    return "".join(c if c.isalnum() or c in " -_.()," else "_" for c in name).strip() or "game"


def run_headless(session: Session, frames: int, script: dict | None = None) -> dict:
    """Run frames with a scripted input; return the last frame, the audio and timing."""
    g = session.gb
    held = 0
    pcm = bytearray()
    t0 = time.perf_counter()
    for i in range(frames):
        if script and i in script:
            held = script[i]
        g.set_buttons(held)
        g.run_frame()
        pcm += g.drain_audio()
    dt = time.perf_counter() - t0
    f = g.frame()
    return {"frames": frames, "seconds": round(dt, 3), "speed": round(frames / max(dt, 1e-9) / FRAME_HZ, 1),
            "frame_sha1": hashlib.sha1(f).hexdigest(), "frame": f, "pcm": bytes(pcm),
            "stats": G.frame_stats(f), "serial": g.serial_text(), "locked": bool(g.m.get("locked")),
            "pc": g.m.get("PC")}


# -- the web shell -------------------------------------------------------------------------------------------
PAGE = r"""<!doctype html>
<html><head><meta charset="utf-8"><title>cardmodel emu</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
:root { --bg: #f4f1ea; --fg: #1d1d1b; --muted: #6b675f; --panel: #fffdf8; }
@media (prefers-color-scheme: dark) { :root { --bg: #161614; --fg: #ece8df; --muted: #9a958a; --panel: #1f1f1c; } }
body { margin: 0; background: var(--bg); color: var(--fg); font: 14px/1.4 ui-sans-serif, system-ui, sans-serif;
       display: flex; flex-direction: column; align-items: center; gap: 12px; padding: 16px; }
canvas { width: min(640px, 100vw - 32px); aspect-ratio: 160 / 144; image-rendering: pixelated;
         background: #000; border-radius: 6px; }
#bar { color: var(--muted); }
#start { padding: 8px 16px; border-radius: 6px; border: 1px solid var(--muted); background: var(--panel);
         color: var(--fg); cursor: pointer; }
kbd { border: 1px solid var(--muted); border-radius: 4px; padding: 0 4px; }
</style></head><body>
<canvas id="lcd" width="160" height="144"></canvas>
<button id="start">Click to start (sound needs a click)</button>
<div id="bar">connecting…</div>
<div style="color:var(--muted)"><kbd>←↑→↓</kbd> pad · <kbd>X</kbd> A · <kbd>Z</kbd> B · <kbd>Enter</kbd> Start ·
<kbd>Shift</kbd> Select · gamepads work too</div>
<script>
const KEYS = {ArrowRight: 1, ArrowLeft: 2, ArrowUp: 4, ArrowDown: 8, KeyX: 16, KeyZ: 32, ShiftLeft: 64,
              ShiftRight: 64, Backspace: 64, Enter: 128};
const cv = document.getElementById('lcd'), cx = cv.getContext('2d'), img = cx.createImageData(160, 144);
const bar = document.getElementById('bar');
let held = 0, pad = 0, sent = -1, ws = null, actx = null, tAudio = 0, frames = 0, t0 = performance.now();
let info = {};
function send() { const m = held | pad; if (ws && ws.readyState === 1 && m !== sent) { ws.send(JSON.stringify({buttons: m})); sent = m; } }
addEventListener('keydown', e => { if (e.code in KEYS) { held |= KEYS[e.code]; send(); e.preventDefault(); } });
addEventListener('keyup', e => { if (e.code in KEYS) { held &= ~KEYS[e.code]; send(); e.preventDefault(); } });
addEventListener('blur', () => { held = 0; send(); });
function pollPad() {
  let m = 0;
  for (const g of navigator.getGamepads ? navigator.getGamepads() : []) {
    if (!g) continue;
    const b = i => g.buttons[i] && g.buttons[i].pressed;
    if (b(15) || g.axes[0] > 0.5) m |= 1; if (b(14) || g.axes[0] < -0.5) m |= 2;
    if (b(12) || g.axes[1] < -0.5) m |= 4; if (b(13) || g.axes[1] > 0.5) m |= 8;
    if (b(0)) m |= 16; if (b(1)) m |= 32; if (b(8)) m |= 64; if (b(9)) m |= 128;
  }
  if (m !== pad) { pad = m; send(); }
  requestAnimationFrame(pollPad);
}
requestAnimationFrame(pollPad);
document.getElementById('start').onclick = () => {
  if (!actx) { actx = new AudioContext({sampleRate: info.rate || 48000}); tAudio = 0; }
  actx.resume(); document.getElementById('start').style.display = 'none';
};
function play(buf) {
  if (!actx || actx.state !== 'running') return;
  const n = buf.byteLength / 4; if (!n) return;
  const v = new DataView(buf), ab = actx.createBuffer(2, n, info.rate || 48000);
  const l = ab.getChannelData(0), r = ab.getChannelData(1);
  for (let i = 0; i < n; i++) { l[i] = v.getInt16(4 * i, true) / 32768; r[i] = v.getInt16(4 * i + 2, true) / 32768; }
  const now = actx.currentTime;
  if (tAudio < now + 0.02 || tAudio > now + 0.25) tAudio = now + 0.06;
  const s = actx.createBufferSource(); s.buffer = ab; s.connect(actx.destination); s.start(tAudio); tAudio += ab.duration;
}
function draw(buf) {
  const src = new Uint8Array(buf), d = img.data;
  for (let i = 0, j = 0; i < 23040; i++, j += 3) { d[4*i] = src[j]; d[4*i+1] = src[j+1]; d[4*i+2] = src[j+2]; d[4*i+3] = 255; }
  cx.putImageData(img, 0, 0); frames++;
  const t = performance.now(); if (t - t0 > 1000) { bar.textContent = `${info.title || ''} · ${info.engine || ''} · ${(frames * 1000 / (t - t0)).toFixed(1)} fps`; frames = 0; t0 = t; }
}
function connect() {
  ws = new WebSocket(`ws://${location.host}/ws`); ws.binaryType = 'arraybuffer';
  ws.onopen = () => { bar.textContent = 'connected'; sent = -1; send(); };
  ws.onclose = () => { bar.textContent = 'disconnected (the emulator stopped)'; };
  ws.onmessage = e => {
    if (typeof e.data === 'string') { info = JSON.parse(e.data); document.title = info.title || 'cardmodel emu'; return; }
    const kind = new Uint8Array(e.data, 0, 1)[0], body = e.data.slice(1);
    if (kind === 1) draw(body); else if (kind === 2) play(body);
  };
}
connect();
</script></body></html>
"""

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


class _WS:
    """A minimal server-side WebSocket (RFC 6455): binary/text out, masked text in."""

    def __init__(self, sock: socket.socket):
        self.sock = sock
        self.lock = threading.Lock()
        self.open = True

    def send(self, data: bytes, text: bool = False) -> None:
        head = bytearray([0x81 if text else 0x82])
        n = len(data)
        if n < 126:
            head.append(n)
        elif n < 65536:
            head += bytes([126]) + struct.pack(">H", n)
        else:
            head += bytes([127]) + struct.pack(">Q", n)
        try:
            with self.lock:
                self.sock.sendall(bytes(head) + data)
        except OSError:
            self.open = False

    def recv(self) -> str | None:
        try:
            h = self._exact(2)
            if not h:
                return None
            op, n = h[0] & 0x0F, h[1] & 0x7F
            if n == 126:
                n = struct.unpack(">H", self._exact(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", self._exact(8))[0]
            mask = self._exact(4) if h[1] & 0x80 else b"\0\0\0\0"
            body = bytes(b ^ mask[i % 4] for i, b in enumerate(self._exact(n)))
            if op == 8:
                return None
            if op == 9:
                self.send(body)
                return ""
            return body.decode("utf-8", "replace") if op == 1 else ""
        except OSError:
            return None

    def _exact(self, n: int) -> bytes:
        buf = b""
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise OSError("closed")
            buf += chunk
        return buf


def serve(session: Session, port: int = 0, open_browser: bool = True, log=print) -> int:
    """Run the game behind a local page until Ctrl-C (or the page says quit). Returns the port used."""
    clients: list[_WS] = []
    state = {"buttons": 0, "quit": False}
    title = session.info["title"] or session.name
    hello = json.dumps({"title": title, "engine": session.gb.engine, "rate": session.gb.sample_rate}).encode()

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):     # quiet
            return

        def do_GET(self):
            if self.path.split("?")[0] == "/ws" and self.headers.get("Upgrade", "").lower() == "websocket":
                key = self.headers.get("Sec-WebSocket-Key", "")
                accept = base64.b64encode(hashlib.sha1((key + GUID).encode()).digest()).decode()
                self.send_response(101)
                self.send_header("Upgrade", "websocket")
                self.send_header("Connection", "Upgrade")
                self.send_header("Sec-WebSocket-Accept", accept)
                self.end_headers()
                ws = _WS(self.connection)
                ws.send(hello, text=True)
                clients.append(ws)
                while not state["quit"]:
                    msg = ws.recv()
                    if msg is None:
                        break
                    if msg:
                        try:
                            data = json.loads(msg)
                        except json.JSONDecodeError:
                            continue
                        if "buttons" in data:
                            state["buttons"] = int(data["buttons"]) & 0xFF
                        if data.get("cmd") == "quit":
                            state["quit"] = True
                ws.open = False
                return
            body = PAGE.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)
    srv.daemon_threads = True
    used = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{used}/"
    log(f"{title}: open {url}  (Ctrl-C to stop; saves go to {session.save_path if session.saves else 'nowhere'})")
    if open_browser:
        import webbrowser
        webbrowser.open(url)
    g = session.gb
    period = 1.0 / FRAME_HZ
    try:
        while not clients and not state["quit"]:
            time.sleep(0.05)
        next_t = time.perf_counter()
        while not state["quit"]:
            g.set_buttons(state["buttons"])
            g.run_frame()
            pcm = g.drain_audio()
            frame = g.frame()
            live = [c for c in clients if c.open]
            clients[:] = live
            for c in live:
                c.send(b"\x01" + frame)
                if pcm:
                    c.send(b"\x02" + pcm)
            session.maybe_save()
            if g.m.get("locked"):
                log(f"the CPU locked up (an illegal opcode near PC {g.m.get('PC'):#06x}); stopping")
                break
            next_t += period
            delay = next_t - time.perf_counter()
            if delay > 0:
                time.sleep(delay)
            elif delay < -0.25:
                next_t = time.perf_counter()        # far behind (the machine was paused): do not race to catch up
    except KeyboardInterrupt:
        pass
    finally:
        srv.shutdown()
        out = session.close()
        log(f"stopped; {'saved' if out.get('saved') else 'nothing new to save'}"
            + (f"; {out['new_entries']} new code entries for the next lift" if "new_entries" in out else ""))
    return used


__all__ = ["BUTTONS", "Session", "default_save_dir", "parse_input", "run_headless", "serve"]
