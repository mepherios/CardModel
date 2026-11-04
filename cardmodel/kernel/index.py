"""index — a SQLite index over registries, so a lookup costs one card, not the whole store (docs/SCALING.md S-B).

The filesystem stays the source of truth. The index only records, per registry directory, where each card is
(a card directory, or a byte offset in a ``_pack*.jsonl``), the order of the names, and the load errors. A
registry's entry carries a *fingerprint*: the size and mtime of ``_category.json``, of every pack file and of
every ``card.json``. A registry whose fingerprint changed is re-read whole and re-indexed, so the index can't go
stale silently, and deleting it is always safe. The fingerprint is a cache key over files, not a card's
identity: identity hashes stay canonical hashes of terms (docs/FOUNDATIONS.md A4), and the index computes none.

SQLite is in Python's standard library, so the model still needs no third-party package.

Environment:
  CARDMODEL_INDEX   a file for the index (default <home>/state/index/cards.sqlite), or "0" to switch it off
"""
from __future__ import annotations

import atexit
import fnmatch
import hashlib
import json
import os
import sqlite3
import threading
from pathlib import Path

from . import paths

SCHEMA = """
CREATE TABLE IF NOT EXISTS regs (path TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, errors TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS cards (path TEXT NOT NULL, seq INTEGER NOT NULL, name TEXT NOT NULL,
                                  source TEXT NOT NULL, ref TEXT NOT NULL, PRIMARY KEY (path, name));
CREATE INDEX IF NOT EXISTS cards_by_name ON cards (name);
"""
VERSION = 1


def fingerprint(path: Path, card_file: str, category_file: str, pack_glob: str) -> str:
    """What a registry's index entry depends on: O(files in the directory), no file is read."""
    h = hashlib.sha1(f"v{VERSION}".encode())
    try:
        entries = sorted(os.scandir(path), key=lambda e: e.name)
    except OSError:
        return "missing"
    for e in entries:
        try:
            if e.name == category_file or fnmatch.fnmatchcase(e.name, pack_glob):
                st = e.stat()
            elif not e.name.startswith(("_", ".")) and e.is_dir():
                st = os.stat(os.path.join(e.path, card_file))
            else:
                continue
        except OSError:
            continue
        h.update(f"{e.name}\0{st.st_size}\0{st.st_mtime_ns}\n".encode())
    return h.hexdigest()


class CardIndex:
    def __init__(self, file: Path):
        self.file = Path(file)
        self.file.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(self.file), timeout=30, isolation_level=None, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.executescript(SCHEMA)

    def fresh(self, path: str, fp: str) -> list[str] | None:
        """The registry's recorded load errors when its entry is current, else None."""
        row = self.db.execute("SELECT fingerprint, errors FROM regs WHERE path=?", (path,)).fetchone()
        return json.loads(row[1]) if row and row[0] == fp else None

    def put(self, path: str, fp: str, rows: list[tuple[str, str, str]], errors: list[str]) -> None:
        """Replace one registry's entry; rows are (name, source, ref) in the registry's name order."""
        with self._tx():
            self.db.execute("DELETE FROM cards WHERE path=?", (path,))
            self.db.executemany("INSERT INTO cards (path, seq, name, source, ref) VALUES (?, ?, ?, ?, ?)",
                                ((path, i, n, s, r) for i, (n, s, r) in enumerate(rows)))
            self.db.execute("INSERT OR REPLACE INTO regs (path, fingerprint, errors) VALUES (?, ?, ?)",
                            (path, fp, json.dumps(errors)))

    def forget(self, path: str) -> None:
        with self._tx():
            self.db.execute("DELETE FROM cards WHERE path=?", (path,))
            self.db.execute("DELETE FROM regs WHERE path=?", (path,))

    def entry(self, path: str, name: str) -> tuple[str, str] | None:
        return self.db.execute("SELECT source, ref FROM cards WHERE path=? AND name=?", (path, name)).fetchone()

    def names(self, path: str) -> list[str]:
        return [r[0] for r in self.db.execute("SELECT name FROM cards WHERE path=? ORDER BY seq", (path,))]

    def count(self, path: str) -> int:
        return self.db.execute("SELECT COUNT(*) FROM cards WHERE path=?", (path,)).fetchone()[0]

    def where(self, name: str) -> list[str]:
        """Every indexed registry directory holding a card of this name."""
        return [r[0] for r in self.db.execute("SELECT path FROM cards WHERE name=?", (name,))]

    def _tx(self):
        db = self.db

        class _T:
            def __enter__(self):
                db.execute("BEGIN IMMEDIATE")

            def __exit__(self, exc_type, *_):
                db.execute("ROLLBACK" if exc_type else "COMMIT")
        return _T()


# one lock for the index and the registries' lazy state: engines read the store from thread pools
LOCK = threading.RLock()
_INDEX: CardIndex | None | bool = False      # False: not opened yet; None: off or unusable


def index_file() -> Path | None:
    env = os.environ.get("CARDMODEL_INDEX")
    if env == "0":
        return None
    return Path(env).expanduser() if env else paths.home() / "state" / "index" / "cards.sqlite"


def get_index() -> CardIndex | None:
    """The process's index, or None when it is switched off or can't be opened (the store then reads files)."""
    global _INDEX
    with LOCK:
        if _INDEX is False:
            f = index_file()
            try:
                _INDEX = CardIndex(f) if f else None
            except (OSError, sqlite3.Error):
                _INDEX = None
            if _INDEX:
                atexit.register(_INDEX.db.close)
        return _INDEX


def reset_index() -> None:
    global _INDEX
    with LOCK:
        if _INDEX:
            _INDEX.db.close()
        _INDEX = False
