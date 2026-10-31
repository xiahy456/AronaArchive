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

"""Bi-temporal state rows. The hot path reads an in-memory snapshot."""

from __future__ import annotations

import sqlite3
import threading
import time
from dataclasses import dataclass

from .db import Database
from .util import approx_chars_for_tokens, new_id, valid_state_key


class StateBudgetError(SystemExit):
    """Startup refusal: the resident block cannot fit the shared token budget."""


def assert_state_budget(
    *,
    max_items: int,
    max_chars_per_item: int,
    token_budget_state: int,
) -> None:
    needed = int(max_items) * (int(max_chars_per_item) + 4)
    budget = approx_chars_for_tokens(token_budget_state)
    if needed > budget:
        raise StateBudgetError(
            "memory_v2 状态预算装不下："
            f"需要 {needed} 字，token_budget.state={token_budget_state} "
            f"约 {budget} 字。请提高 token_budget.state 或降低 states.max_items。"
        )


@dataclass
class StateRow:
    id: str
    key: str
    value: str
    valid_from: float
    valid_until: float | None
    confidence: float
    source_event: str
    importance: int
    recorded_at: float


class StateBook:
    def __init__(
        self,
        db: Database,
        *,
        max_items: int = 12,
        max_chars: int = 48,
        key_max_chars: int = 24,
    ) -> None:
        self.db = db
        self.max_items = max(1, int(max_items))
        self.max_chars = max(1, int(max_chars))
        self.key_max_chars = max(1, int(key_max_chars))
        self._lock = threading.Lock()
        self._rows: list[StateRow] = []
        self.reload()

    def reload(self) -> None:
        def _read(conn: sqlite3.Connection) -> list[StateRow]:
            found = conn.execute(
                """
                SELECT id, key, value, valid_from, valid_until, confidence,
                       source_event, importance, recorded_at
                FROM states
                """
            ).fetchall()
            rows: list[StateRow] = []
            for item in found:
                rows.append(
                    StateRow(
                        id=str(item["id"]),
                        key=str(item["key"]),
                        value=str(item["value"]),
                        valid_from=float(item["valid_from"]),
                        valid_until=(
                            None
                            if item["valid_until"] is None
                            else float(item["valid_until"])
                        ),
                        confidence=float(item["confidence"]),
                        source_event=str(item["source_event"] or ""),
                        importance=int(item["importance"]),
                        recorded_at=float(item["recorded_at"]),
                    )
                )
            return rows

        rows = self.db.call(_read)
        with self._lock:
            self._rows = rows

    def live(self, now: float | None = None) -> list[str]:
        moment = time.time() if now is None else float(now)
        with self._lock:
            rows = [
                row
                for row in self._rows
                if row.valid_from <= moment
                and (row.valid_until is None or row.valid_until > moment)
            ]
        rows.sort(key=lambda row: (-row.importance, -row.recorded_at))
        return [row.value for row in rows[: self.max_items]]

    def upsert(
        self,
        *,
        key: str,
        value: str,
        valid_from: float,
        valid_until: float | None,
        importance: int,
        confidence: float = 0.8,
        source_event: str = "",
        recorded_at: float | None = None,
    ) -> str | None:
        slot = (key or "").strip()
        text = (value or "").strip()
        if not valid_state_key(slot, max_chars=self.key_max_chars):
            return None
        if not text or len(text) > self.max_chars:
            return None
        row_id = new_id("st")
        recorded = time.time() if recorded_at is None else float(recorded_at)
        opened = float(valid_from)

        def _write(conn: sqlite3.Connection) -> None:
            conn.execute(
                """
                UPDATE states
                SET valid_until = CASE
                    WHEN valid_from > ? THEN valid_from
                    ELSE ?
                END
                WHERE key = ? AND valid_until IS NULL
                """,
                (opened, opened, slot),
            )
            conn.execute(
                """
                INSERT INTO states (
                    id, key, value, valid_from, valid_until, confidence,
                    source_event, importance, recorded_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row_id,
                    slot,
                    text,
                    opened,
                    valid_until,
                    float(confidence),
                    source_event or None,
                    int(importance),
                    recorded,
                ),
            )
            conn.execute(
                """
                INSERT INTO state_keys (id, first_seen_at)
                VALUES (?, ?)
                ON CONFLICT(id) DO NOTHING
                """,
                (slot, recorded),
            )

        self.db.call(_write)
        self.reload()
        return row_id
