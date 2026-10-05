from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

from fleet.config import ROOT


class LeaseBusyError(RuntimeError):
    pass


class StateLease:
    def __init__(self, store: StateStore, name: str) -> None:
        self.store, self.name, self.owner = store, name, str(uuid.uuid4())
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM leases WHERE name = ? AND expires < ?", (name, time.time()))
            try:
                db.execute("INSERT INTO leases VALUES (?, ?, ?)", (name, self.owner, time.time() + 60))
            except sqlite3.IntegrityError as error:
                raise LeaseBusyError(f"Another worker owns {name}.") from error

    def renew(self) -> None:
        with self.store.connect() as db:
            changed = db.execute(
                "UPDATE leases SET expires = ? WHERE name = ? AND owner = ? AND expires > ?",
                (time.time() + 60, self.name, self.owner, time.time()),
            ).rowcount
            if changed != 1:
                raise LeaseBusyError(f"The worker lease {self.name} expired.")

    def release(self) -> None:
        with self.store.connect() as db:
            db.execute("DELETE FROM leases WHERE name = ? AND owner = ?", (self.name, self.owner))

    def __enter__(self) -> StateLease:
        return self

    def __exit__(self, *args) -> None:
        self.release()


class StateStore:
    def __init__(self, path: Path | None = None) -> None:
        if path is None:
            path = Path("/home/data/caldova/state.sqlite3") if os.environ.get("WEBSITE_INSTANCE_ID") else ROOT / ".local" / "state.sqlite3"
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS state (name TEXT PRIMARY KEY, value TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS leases (name TEXT PRIMARY KEY, owner TEXT NOT NULL, expires REAL NOT NULL)")

    def connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=30)

    def get(self, name: str, *, connection: sqlite3.Connection | None = None) -> dict[str, Any] | list | None:
        if connection is None:
            with self.connect() as db:
                return self.get(name, connection=db)
        row = connection.execute("SELECT value FROM state WHERE name = ?", (name,)).fetchone()
        return json.loads(row[0]) if row else None

    def put(self, name: str, value: Any, *, connection: sqlite3.Connection | None = None) -> None:
        if connection is None:
            with self.connect() as db:
                self.put(name, value, connection=db)
            return
        payload = json.dumps(value, separators=(",", ":"), allow_nan=False)
        connection.execute("INSERT INTO state VALUES (?, ?) ON CONFLICT(name) DO UPDATE SET value = excluded.value", (name, payload))

    def create(self, name: str, value: Any) -> bool:
        with self.connect() as db:
            return db.execute(
                "INSERT OR IGNORE INTO state VALUES (?, ?)",
                (name, json.dumps(value, allow_nan=False)),
            ).rowcount == 1

    def export(self) -> dict:
        with self.connect() as db:
            return {name: json.loads(value) for name, value in db.execute("SELECT name, value FROM state")}

    def lease(self, name: str) -> StateLease:
        return StateLease(self, name)
