"""pairing — an iPhone or iPad reaches the arcade service over the local network once it is paired.

The service always listens on 127.0.0.1 (this Mac: its launcher, and the iOS Simulator, which shares the Mac's
network). On the local network it listens while a pairing code is out and, on the launcher's port, while a device is
paired. There every request except ``GET /api/status`` and ``POST /api/pair`` needs a paired device's token
(``Authorization: Bearer TOKEN`` or the cookie ``cardmodel_device``, which the iOS launcher sets for its pages), and
a token opens only what the launcher on a device needs (``DEVICE_ROUTES``: the store, its builds, the library and
its cartridges); the work in progress, other branches' builds and the Mac's folders stay on the Mac:

    cardmodel arcade pair            this Mac asks its running service for a code (POST /api/pair/code: loopback
                                     only), and shows it with the addresses a device can reach the service at
    POST /api/pair {code, name}      the device sends the code within ten minutes; it gets a token (32 random bytes)
    cardmodel arcade pair --list     the paired devices; --forget NAME removes one, --off stops the network listener

A code is six digits, good for ten minutes and five tries (typed as the Mac shows it, "123 456", or in any script's
digits). The service keeps each token's SHA-256 only, in devices.json in the arcade's own folder (beside
library.json, so every checkout's service knows the same devices); every change to it is made under a lock this
process and the CLI share. Pairing the same name again replaces that device's token (the launcher sends its own
name with a suffix of its vendor id, so two iPhones stay two devices).

Honest limits (L1): plain HTTP on the local network (a paired token travels in the clear, like the files); macOS's
firewall may ask once whether Python may accept incoming connections.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import secrets
import socket
import threading
import time
import unicodedata
from contextlib import contextmanager
from pathlib import Path

CODE_TTL_S = 600
CODE_TRIES = 5
COOKIE = "cardmodel_device"
LOOPBACK = ("127.0.0.1", "::1", "::ffff:127.0.0.1")
_lock = threading.RLock()
_code: dict = {}
_seen: dict = {}                            # token hash -> when this process last wrote it down as seen
# what a paired device may ask for: the store, its builds and depots, the pages, the library and its cartridges
DEVICE_ROUTES = {
    "GET": (("ui",), ("depot",), ("chunk",), ("media",), ("api", "status"), ("api", "pair"), ("api", "catalog"),
            ("api", "game"), ("api", "build"), ("api", "library"), ("api", "cover"), ("api", "cartridge")),
    "POST": (("api", "build"), ("api", "library", "scan")),
}
DEVICES_OVERRIDE: Path | None = None        # tests point it at a temporary file


def devices_file(ctx) -> Path:
    if DEVICES_OVERRIDE is not None:
        return DEVICES_OVERRIDE
    from . import library as L
    return L.settings_file(ctx).with_name("devices.json")


def load(ctx) -> dict:
    try:
        d = json.loads(devices_file(ctx).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        d = {}
    d.setdefault("devices", [])
    d.setdefault("lan", False)
    return d


def save(ctx, d: dict) -> None:
    p = devices_file(ctx)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f".{p.name}.{os.getpid()}.{threading.get_ident()}.tmp")    # each writer its own
    tmp.write_text(json.dumps(d, indent=1, sort_keys=True), encoding="utf-8")
    tmp.replace(p)


@contextmanager
def _locked(ctx):
    """One change to devices.json at a time: this process's threads, and any other process (the CLI)."""
    p = devices_file(ctx)
    p.parent.mkdir(parents=True, exist_ok=True)
    with _lock, open(p.with_name(f".{p.name}.lock"), "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def update(ctx, change) -> dict:
    """Read devices.json, change it (change(d)), write it back, under the lock; returns what was written."""
    with _locked(ctx):
        d = load(ctx)
        change(d)
        save(ctx, d)
        return d


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_code(ctx) -> dict:
    """A fresh pairing code (the last one stops working). The service listens on the network while it is out; the
    listener stays on (``lan``) only once a device has paired."""
    with _lock:
        _code.clear()
        _code.update(code=f"{secrets.randbelow(10 ** 6):06d}", expires=time.time() + CODE_TTL_S, tries=0)
        return {"code": _code["code"], "expires": _code["expires"]}


def digits(code) -> str:
    """A code as typed: its digits in any script, spaces and the rest left out ("123 456" as the Mac shows it)."""
    return "".join(str(unicodedata.decimal(c)) for c in str(code) if c.isdecimal())


def pair(ctx, code: str, name: str) -> str | None:
    """The device's token when code is the current one (in time, within its tries), else None."""
    with _lock:
        if not _code or time.time() > _code["expires"] or _code["tries"] >= CODE_TRIES:
            _code.clear()
            return None
        _code["tries"] += 1
        if not secrets.compare_digest(digits(code), _code["code"]):
            return None
        _code.clear()
        token = secrets.token_hex(32)
        name = (name or "device").strip()[:60] or "device"

        def add(d):
            d["devices"] = [x for x in d["devices"] if x.get("name") != name]
            d["devices"].append({"name": name, "sha256": _hash(token), "paired": round(time.time()), "seen": 0})
            d["lan"] = True
        update(ctx, add)
        return token


def token_of(headers) -> str:
    auth = headers.get("Authorization") or ""
    if auth.startswith("Bearer "):
        return auth[7:].strip()
    for part in (headers.get("Cookie") or "").split(";"):
        k, _, v = part.strip().partition("=")
        if k == COOKIE:
            return v.strip()
    return ""


def device(ctx, token: str) -> str | None:
    """The paired device a token belongs to (its name), else None."""
    if not token:
        return None
    h = _hash(token)
    for x in load(ctx)["devices"]:
        if secrets.compare_digest(x.get("sha256", ""), h):
            now = time.time()
            if now - _seen.get(h, 0) > 300:                   # when it was last seen, roughly
                _seen[h] = now

                def mark(d):
                    for y in d["devices"]:
                        if y.get("sha256") == h:
                            y["seen"] = round(now)
                try:
                    update(ctx, mark)
                except OSError:
                    pass
            return x["name"]
    return None


def device_route(method: str, parts: list[str], query: dict | None = None) -> bool:
    """Whether a paired device may ask for this: DEVICE_ROUTES, and never another worktree's version."""
    if query and (query.get("branch") or query.get("wt")):
        return False
    return not parts or any(tuple(parts[:len(r)]) == r for r in DEVICE_ROUTES.get(method, ()))


def allowed(ctx, client: str, method: str, parts: list[str], headers, query: dict | None = None) -> bool:
    """Whether a request may be served: this Mac always; a device on the network for the status and the pairing
    itself, otherwise only with a paired device's token and only what the launcher on a device needs."""
    if client in LOOPBACK:
        return True
    if (method, parts) in (("GET", ["api", "status"]), ("POST", ["api", "pair"])):
        return True
    return device_route(method, parts, query) and device(ctx, token_of(headers)) is not None


def forget(ctx, name: str) -> bool:
    """Forget a device; with none left, the service stops listening on the network when it next starts."""
    gone = []

    def drop(d):
        keep = [x for x in d["devices"] if x.get("name") != name]
        gone.append(len(keep) != len(d["devices"]))
        d["devices"] = keep
        if not keep:
            d["lan"] = False
    update(ctx, drop)
    return gone[0]


def set_lan(ctx, on: bool) -> None:
    update(ctx, lambda d: d.update(lan=on))


def addresses(port: int) -> list[str]:
    """Where a device on the local network can reach the service: the Mac's .local name and its IPv4 addresses."""
    out = []
    host = socket.gethostname()
    if host:
        out.append(f"{host if host.endswith('.local') else host + '.local'}:{port}")
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))                  # no packet is sent: this picks the outgoing interface
            ip = s.getsockname()[0]
        if ip and not ip.startswith("127."):
            out.append(f"{ip}:{port}")
    except OSError:
        pass
    return out


__all__ = ["COOKIE", "DEVICE_ROUTES", "addresses", "allowed", "device", "device_route", "devices_file", "digits", "forget",
           "load", "new_code", "pair", "set_lan", "token_of", "update"]
