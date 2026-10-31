# AronaArchive - 自循环 AI
# Copyright (C) 2026 xia_hy456
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later

"""SQLite schema, WAL, and the FTS5 sidecar for memory_v2.

FTS5 external-content tables cannot point at a table in another database file.
The sidecar therefore holds its own FTS5 index (summary copied on insert),
which keeps the shadow tables out of any leftover v1 `memories_fts`.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

from .util import fts_document

logger = logging.getLogger(__name__)

T = TypeVar("T")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id            TEXT PRIMARY KEY,
    summary       TEXT NOT NULL,
    occurred_at   REAL NOT NULL,
    recorded_at   REAL NOT NULL,
    importance    INTEGER NOT NULL DEFAULT 5,
    source_turn   TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_occurred ON events(occurred_at);

CREATE TABLE IF NOT EXISTS states (
    id            TEXT PRIMARY KEY,
    key           TEXT NOT NULL,
    value         TEXT NOT NULL,
    valid_from    REAL NOT NULL,
    valid_until   REAL,
    confidence    REAL NOT NULL DEFAULT 0.8,
    source_event  TEXT,
    importance    INTEGER NOT NULL DEFAULT 5,
    recorded_at   REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_states_live ON states(key, valid_until);

CREATE TABLE IF NOT EXISTS commitments (
    id                       TEXT PRIMARY KEY,
    what                     TEXT NOT NULL,
    current                  TEXT NOT NULL,
    created_at               REAL NOT NULL,
    active                   INTEGER NOT NULL DEFAULT 1,
    last_injected_at         REAL,
    last_helpful_injected_at REAL,
    inject_count             INTEGER NOT NULL DEFAULT 0,
    retired_at               REAL,
    source_event             TEXT
);
CREATE INDEX IF NOT EXISTS idx_commit_live
    ON commitments(active, last_helpful_injected_at);

CREATE TABLE IF NOT EXISTS state_keys (
    id            TEXT PRIMARY KEY,
    first_seen_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS scan_state (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class Database:
    def __init__(self, db_path: Path, fts_path: Path) -> None:
        self.db_path = Path(db_path)
        self.fts_path = Path(fts_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.fts_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(
            str(self.db_path), check_same_thread=False
        )
        self._conn.row_factory = sqlite3.Row
        self.fts_ready = False
        self.fts_tokenize = ""
        self.legacy_v1 = self._detect_legacy()
        if self.legacy_v1:
            return
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self.ensure_schema()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def call(self, fn: Callable[[sqlite3.Connection], T]) -> T:
        """Run fn under the write lock and commit. Callers from asyncio use to_thread."""
        with self._lock:
            try:
                result = fn(self._conn)
                self._conn.commit()
                return result
            except Exception:
                self._conn.rollback()
                raise

    def table_names(self) -> set[str]:
        def _read(conn: sqlite3.Connection) -> set[str]:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
            return {str(row[0]) for row in rows}

        return self.call(_read)

    def _detect_legacy(self) -> bool:
        rows = self._conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
        names = {str(row[0]) for row in rows}
        v1 = "memories" in names or "state_items" in names
        return v1 and "events" not in names

    def has_v1_without_v2(self) -> bool:
        return self.legacy_v1

    def ensure_schema(self) -> None:
        def _create(conn: sqlite3.Connection) -> None:
            conn.executescript(_SCHEMA)
            self._ensure_fts(conn)

        self.call(_create)

    def _ensure_fts(self, conn: sqlite3.Connection) -> None:
        conn.commit()
        try:
            conn.execute("ATTACH DATABASE ? AS ftsdb", (str(self.fts_path),))
        except sqlite3.OperationalError as exc:
            if "already" not in str(exc).lower():
                logger.warning("memory_v2 fts attach failed: %s", exc)
                self.fts_ready = False
                return
        try:
            conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS ftsdb.events_fts
                USING fts5(event_id UNINDEXED, summary, tokenize='unicode61')
                """
            )
        except sqlite3.OperationalError as exc:
            logger.warning("memory_v2 events_fts create failed: %s", exc)
            self.fts_ready = False
            return
        self.fts_ready = True
        self.fts_tokenize = "unicode61"
        logger.info("memory_v2 events_fts ready path=%s", self.fts_path)

    def fts_add(self, conn: sqlite3.Connection, event_id: str, summary: str) -> None:
        if not self.fts_ready:
            return
        conn.execute(
            "INSERT INTO ftsdb.events_fts(event_id, summary) VALUES (?, ?)",
            (event_id, fts_document(summary)),
        )

    def fts_search(self, conn: sqlite3.Connection, match: str, limit: int) -> list[str]:
        if not self.fts_ready or not match.strip():
            return []
        try:
            rows = conn.execute(
                """
                SELECT event_id FROM ftsdb.events_fts
                WHERE events_fts MATCH ?
                LIMIT ?
                """,
                (match, max(1, int(limit))),
            ).fetchall()
        except sqlite3.OperationalError:
            logger.info("memory_v2 fts match failed query=%r", match)
            return []
        return [str(row[0]) for row in rows if row[0]]
