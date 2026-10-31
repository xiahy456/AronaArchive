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

"""Commitments. `active` is written only by the time-expiry check."""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass

from .db import Database
from .util import new_id


@dataclass
class Commitment:
    id: str
    what: str
    current: str
    created_at: float
    active: int
    last_injected_at: float | None
    last_helpful_injected_at: float | None
    inject_count: int
    retired_at: float | None
    source_event: str


def _row(item: sqlite3.Row) -> Commitment:
    def _optional(name: str) -> float | None:
        value = item[name]
        return None if value is None else float(value)

    return Commitment(
        id=str(item["id"]),
        what=str(item["what"]),
        current=str(item["current"] or ""),
        created_at=float(item["created_at"]),
        active=int(item["active"]),
        last_injected_at=_optional("last_injected_at"),
        last_helpful_injected_at=_optional("last_helpful_injected_at"),
        inject_count=int(item["inject_count"]),
        retired_at=_optional("retired_at"),
        source_event=str(item["source_event"] or ""),
    )


_COLUMNS = """
    id, what, current, created_at, active, last_injected_at,
    last_helpful_injected_at, inject_count, retired_at, source_event
"""


class CommitmentBook:
    def __init__(self, db: Database) -> None:
        self.db = db

    def insert(
        self,
        *,
        what: str,
        current: str,
        source_event: str = "",
        created_at: float | None = None,
        commitment_id: str = "",
    ) -> Commitment:
        row_id = commitment_id or new_id("cm")
        created = time.time() if created_at is None else float(created_at)
        text = (what or "").strip()
        status = (current or "").strip()
        if not text or not status:
            raise ValueError("commitment what and current are required")

        def _write(conn: sqlite3.Connection) -> None:
            conn.execute(
                """
                INSERT INTO commitments (
                    id, what, current, created_at, active, inject_count, source_event
                ) VALUES (?, ?, ?, ?, 1, 0, ?)
                """,
                (row_id, text, status, created, source_event or None),
            )

        self.db.call(_write)
        loaded = self.get(row_id)
        if loaded is None:
            raise RuntimeError("commitment insert disappeared")
        return loaded

    def get(self, commitment_id: str) -> Commitment | None:
        def _read(conn: sqlite3.Connection) -> Commitment | None:
            item = conn.execute(
                f"SELECT {_COLUMNS} FROM commitments WHERE id = ?",
                (commitment_id,),
            ).fetchone()
            if item is None:
                return None
            return _row(item)

        return self.db.call(_read)

    def active(self) -> list[Commitment]:
        def _read(conn: sqlite3.Connection) -> list[Commitment]:
            rows = conn.execute(
                f"""
                SELECT {_COLUMNS} FROM commitments
                WHERE active = 1
                ORDER BY id
                """
            ).fetchall()
            return [_row(item) for item in rows]

        return self.db.call(_read)

    def active_whats(self) -> list[str]:
        return [item.what for item in self.active()]

    def update_fields(
        self,
        commitment_id: str,
        *,
        what: str | None = None,
        current: str | None = None,
        last_helpful_injected_at: float | None = None,
        clear_helpful: bool = False,
    ) -> Commitment | None:
        """Overwrite only the fields that were provided. Never touches `active`."""
        before = self.get(commitment_id)
        if before is None or not before.active:
            return None

        def _write(conn: sqlite3.Connection) -> None:
            if what is not None:
                conn.execute(
                    "UPDATE commitments SET what = ? WHERE id = ?",
                    (what, commitment_id),
                )
            if current is not None:
                conn.execute(
                    "UPDATE commitments SET current = ? WHERE id = ?",
                    (current, commitment_id),
                )
            if clear_helpful:
                conn.execute(
                    """
                    UPDATE commitments
                    SET last_helpful_injected_at = NULL
                    WHERE id = ?
                    """,
                    (commitment_id,),
                )
            elif last_helpful_injected_at is not None:
                conn.execute(
                    """
                    UPDATE commitments
                    SET last_helpful_injected_at = ?
                    WHERE id = ?
                    """,
                    (float(last_helpful_injected_at), commitment_id),
                )

        self.db.call(_write)
        return before

    def mark_injected(self, ids: list[str], now: float) -> None:
        if not ids:
            return

        def _write(conn: sqlite3.Connection) -> None:
            for commitment_id in ids:
                conn.execute(
                    """
                    UPDATE commitments
                    SET last_injected_at = ?,
                        inject_count = inject_count + 1
                    WHERE id = ? AND active = 1
                    """,
                    (float(now), commitment_id),
                )

        self.db.call(_write)

    def expire(self, now: float, stale_after_sec: float) -> list[dict[str, object]]:
        """The only writer of active=0. Never-injected rows are skipped."""
        moment = float(now)
        limit = float(stale_after_sec)
        expired: list[dict[str, object]] = []

        def _write(conn: sqlite3.Connection) -> None:
            rows = conn.execute(
                f"""
                SELECT {_COLUMNS} FROM commitments
                WHERE active = 1
                ORDER BY id
                """
            ).fetchall()
            for item in rows:
                row = _row(item)
                if row.inject_count <= 0:
                    continue
                base = row.last_helpful_injected_at
                if base is None:
                    base = row.last_injected_at if row.last_injected_at is not None else row.created_at
                idle = moment - float(base)
                if idle <= limit:
                    continue
                conn.execute(
                    """
                    UPDATE commitments
                    SET active = 0, retired_at = ?
                    WHERE id = ? AND active = 1
                    """,
                    (moment, row.id),
                )
                expired.append(
                    {
                        "id": row.id,
                        "idle_sec": idle,
                        "inject_count": row.inject_count,
                        "last_helpful_injected_at": row.last_helpful_injected_at,
                    }
                )

        self.db.call(_write)
        return expired

    def set_next_scan_at(self, when: float) -> None:
        def _write(conn: sqlite3.Connection) -> None:
            conn.execute(
                """
                INSERT INTO scan_state (key, value) VALUES ('next_scan_at', ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (str(float(when)),),
            )

        self.db.call(_write)

    def next_scan_at(self) -> float | None:
        def _read(conn: sqlite3.Connection) -> float | None:
            item = conn.execute(
                "SELECT value FROM scan_state WHERE key = 'next_scan_at'"
            ).fetchone()
            if item is None:
                return None
            try:
                return float(item["value"])
            except (TypeError, ValueError):
                return None

        return self.db.call(_read)
