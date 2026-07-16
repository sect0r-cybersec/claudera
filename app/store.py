"""Plugin-scoped SQLite store for claudera.

Backs the per-user bearer key store (this file) and, later, the run-history log
(step 7). One gitignored SQLite database at ``<plugin>/data/claudera.db`` holds
both, so state survives restarts and is safe under the concurrent access of
parallel MCP sessions.

Key model
---------
Each key is a per-user record: username, group, an argon2 hash of the secret,
created/last-used timestamps, and an active flag. Keys are never stored in
plaintext; argon2 embeds a random per-hash salt. The raw token is shown once at
issue time only.

Token format: ``cald_<key_id>.<secret>``. The ``key_id`` prefix indexes the row
for an O(1) lookup; the ``secret`` is then argon2-verified against that row.

This file is original to the claudera plugin (Apache-2.0).
"""

from __future__ import annotations

import os
import secrets
import sqlite3
import threading
import time
from dataclasses import dataclass

from argon2 import PasswordHasher

# Reuse Caldera's argon2 verification (same PasswordHasher defaults as core auth).
from app.utility.config_util import verify_hash

TOKEN_PREFIX = "cald_"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS mcp_keys (
    key_id       TEXT PRIMARY KEY,
    username     TEXT NOT NULL,
    group_name   TEXT NOT NULL,
    key_hash     TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    last_used_at TEXT,
    active       INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS payload_downloads (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts         TEXT NOT NULL,
    username   TEXT,
    source     TEXT,
    url        TEXT NOT NULL,
    sha256     TEXT,
    size       INTEGER,
    dest_path  TEXT,
    status     TEXT NOT NULL
);
"""


def _utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


@dataclass
class KeyRecord:
    key_id: str
    username: str
    group: str
    created_at: str
    last_used_at: str | None
    active: bool

    def to_dict(self) -> dict:
        return {
            "key_id": self.key_id,
            "username": self.username,
            "group": self.group,
            "created_at": self.created_at,
            "last_used_at": self.last_used_at,
            "active": self.active,
        }


class KeyStore:
    """Per-user bearer key store backed by SQLite."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._hasher = PasswordHasher()
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    # -- issuance / lifecycle --------------------------------------------------

    def issue(self, username: str, group: str) -> tuple[str, str]:
        """Create a key for ``username``/``group``. Returns (key_id, raw_token).

        The raw token is returned once and never stored.
        """
        key_id = secrets.token_hex(6)
        secret = secrets.token_urlsafe(32)
        key_hash = self._hasher.hash(secret)
        token = f"{TOKEN_PREFIX}{key_id}.{secret}"
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO mcp_keys (key_id, username, group_name, key_hash, created_at, active) "
                "VALUES (?, ?, ?, ?, ?, 1)",
                (key_id, username, group, key_hash, _utc_now()),
            )
        return key_id, token

    def rotate(self, key_id: str) -> str | None:
        """Replace a key's secret (same key_id, same user). Returns the new token."""
        secret = secrets.token_urlsafe(32)
        key_hash = self._hasher.hash(secret)
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "UPDATE mcp_keys SET key_hash=?, created_at=?, last_used_at=NULL, active=1 "
                "WHERE key_id=?",
                (key_hash, _utc_now(), key_id),
            )
            if cur.rowcount == 0:
                return None
        return f"{TOKEN_PREFIX}{key_id}.{secret}"

    def set_active(self, key_id: str, active: bool) -> bool:
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "UPDATE mcp_keys SET active=? WHERE key_id=?",
                (1 if active else 0, key_id),
            )
            return cur.rowcount > 0

    def revoke(self, key_id: str) -> bool:
        return self.set_active(key_id, False)

    # -- validation ------------------------------------------------------------

    def validate(self, token: str) -> KeyRecord | None:
        """Resolve a raw bearer token to its active key record, or None.

        Updates ``last_used_at`` on success.
        """
        if not isinstance(token, str) or not token.startswith(TOKEN_PREFIX):
            return None
        body = token[len(TOKEN_PREFIX):]
        key_id, _, secret = body.partition(".")
        if not key_id or not secret:
            return None
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM mcp_keys WHERE key_id=? AND active=1", (key_id,)
            ).fetchone()
        if row is None:
            return None
        if not verify_hash(row["key_hash"], secret):
            return None
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE mcp_keys SET last_used_at=? WHERE key_id=?", (_utc_now(), key_id)
            )
        return _record(row, last_used_at=_utc_now())

    # -- read ------------------------------------------------------------------

    def get(self, key_id: str) -> KeyRecord | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM mcp_keys WHERE key_id=?", (key_id,)).fetchone()
        return _record(row) if row else None

    def list_keys(self, username: str | None = None) -> list[KeyRecord]:
        query = "SELECT * FROM mcp_keys"
        params: tuple = ()
        if username is not None:
            query += " WHERE username=?"
            params = (username,)
        query += " ORDER BY created_at DESC"
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [_record(r) for r in rows]


    # -- payload download log --------------------------------------------------

    def log_download(self, *, username, source, url, sha256, size, dest_path, status) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO payload_downloads (ts, username, source, url, sha256, size, dest_path, status) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (_utc_now(), username, source, url, sha256, size, dest_path, status),
            )

    def list_downloads(self, limit: int = 100) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM payload_downloads ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]


def _record(row: sqlite3.Row, last_used_at: str | None = None) -> KeyRecord:
    return KeyRecord(
        key_id=row["key_id"],
        username=row["username"],
        group=row["group_name"],
        created_at=row["created_at"],
        last_used_at=last_used_at if last_used_at is not None else row["last_used_at"],
        active=bool(row["active"]),
    )
