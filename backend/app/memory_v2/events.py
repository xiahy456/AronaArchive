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

"""Append-only events. Rows are never updated or deleted."""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass

from .db import Database
from .util import new_id


@dataclass(frozen=True)
class Event:
    id: str
    summary: str
    occurred_at: float
    recorded_at: float
    importance: int
    source_turn: str


class EventLog:
    def __init__(self, db: Database) -> None:
        self.db = db

    def append(
        self,
        *,
        summary: str,
        occurred_at: float,
        importance: int,
        source_turn: str = "",
        recorded_at: float | None = None,
        event_id: str = "",
    ) -> Event:
        text = (summary or "").strip()
        if not text:
            raise ValueError("event summary is empty")
        row_id = event_id or new_id("ev")
        recorded = time.time() if recorded_at is None else float(recorded_at)
        event = Event(
            id=row_id,
            summary=text,
            occurred_at=float(occurred_at),
            recorded_at=recorded,
            importance=int(importance),
            source_turn=source_turn or "",
        )

        def _write(conn: sqlite3.Connection) -> None:
            conn.execute(
                """
                INSERT INTO events (
                    id, summary, occurred_at, recorded_at, importance, source_turn
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    event.id,
                    event.summary,
                    event.occurred_at,
                    event.recorded_at,
                    event.importance,
                    event.source_turn or None,
                ),
            )
            self.db.fts_add(conn, event.id, event.summary)

        self.db.call(_write)
        return event

    def get_many(self, ids: list[str]) -> dict[str, Event]:
        if not ids:
            return {}

        def _read(conn: sqlite3.Connection) -> dict[str, Event]:
            placeholders = ",".join("?" for _ in ids)
            rows = conn.execute(
                f"""
                SELECT id, summary, occurred_at, recorded_at, importance, source_turn
                FROM events WHERE id IN ({placeholders})
                """,
                tuple(ids),
            ).fetchall()
            found: dict[str, Event] = {}
            for item in rows:
                event = Event(
                    id=str(item["id"]),
                    summary=str(item["summary"]),
                    occurred_at=float(item["occurred_at"]),
                    recorded_at=float(item["recorded_at"]),
                    importance=int(item["importance"]),
                    source_turn=str(item["source_turn"] or ""),
                )
                found[event.id] = event
            return found

        return self.db.call(_read)

    def search_ids(self, match: str, limit: int) -> list[str]:
        def _read(conn: sqlite3.Connection) -> list[str]:
            return self.db.fts_search(conn, match, limit)

        return self.db.call(_read)
