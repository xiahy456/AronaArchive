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

"""One row per state key. The hot path reads an in-memory snapshot."""

from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass
from typing import Any

from app.safety import is_crisis_text

from .db import Database
from .util import approx_chars_for_tokens, has_ephemeral_time, valid_state_key

_UPDATE_KEY = "state_update_at"


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
    key: str
    value: str
    created_at: float
    updated_at: float
    active: int


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
                SELECT key, value, created_at, updated_at, active
                FROM states
                """
            ).fetchall()
            return [
                StateRow(
                    key=str(item["key"]),
                    value=str(item["value"]),
                    created_at=float(item["created_at"]),
                    updated_at=float(item["updated_at"]),
                    active=int(item["active"]),
                )
                for item in found
            ]

        rows = self.db.call(_read)
        with self._lock:
            self._rows = rows

    def active(self) -> list[StateRow]:
        with self._lock:
            rows = [row for row in self._rows if row.active == 1]
        rows.sort(key=lambda row: -row.updated_at)
        return rows

    def live(self, now: float | None = None) -> list[str]:
        del now
        return [row.value for row in self.active()]

    def get(self, key: str) -> StateRow | None:
        with self._lock:
            for row in self._rows:
                if row.key == key:
                    return row
        return None

    def last_update_at(self) -> float | None:
        def _read(conn: sqlite3.Connection) -> float | None:
            item = conn.execute(
                "SELECT value FROM scan_state WHERE key = ?",
                (_UPDATE_KEY,),
            ).fetchone()
            if item is None:
                return None
            try:
                return float(item["value"])
            except (TypeError, ValueError):
                return None

        return self.db.call(_read)

    def set_last_update_at(self, when: float) -> None:
        def _write(conn: sqlite3.Connection) -> None:
            conn.execute(
                """
                INSERT INTO scan_state (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (_UPDATE_KEY, str(float(when))),
            )

        self.db.call(_write)

    def apply_ops(self, ops: list[Any], now: float) -> dict[str, list[dict[str, Any]]]:
        """Apply one model response. Later duplicate keys win. created_at is insert-only."""
        moment = float(now)

        def _write(conn: sqlite3.Connection) -> dict[str, list[dict[str, Any]]]:
            found = conn.execute(
                "SELECT key, value, created_at, updated_at, active FROM states"
            ).fetchall()
            existing: dict[str, dict[str, Any]] = {
                str(row["key"]): {
                    "value": str(row["value"]),
                    "created_at": float(row["created_at"]),
                    "updated_at": float(row["updated_at"]),
                    "active": int(row["active"]),
                }
                for row in found
            }
            added: list[dict[str, Any]] = []
            modified: list[dict[str, Any]] = []
            deleted: list[dict[str, Any]] = []
            dropped: list[dict[str, Any]] = []
            chosen: dict[str, dict[str, Any]] = {}
            order: list[str] = []
            for raw in ops:
                if not isinstance(raw, dict):
                    dropped.append({"key": "", "reason": "shape"})
                    continue
                key = str(raw.get("key") or "").strip()
                if key in chosen:
                    dropped.append({"key": key, "reason": "duplicate"})
                else:
                    order.append(key)
                chosen[key] = raw
            active_count = sum(1 for row in existing.values() if int(row["active"]) == 1)
            for key in order:
                raw = chosen[key]
                outcome = self._apply_one(
                    conn,
                    existing,
                    key,
                    raw,
                    moment,
                    active_count,
                )
                kind = outcome["kind"]
                if kind == "dropped":
                    dropped.append({"key": key, "reason": outcome["reason"]})
                    continue
                active_count = int(outcome["active_count"])
                record = {
                    "key": key,
                    "before": outcome.get("before") or "",
                    "after": outcome.get("after") or "",
                }
                if kind == "add":
                    added.append(record)
                elif kind == "modify":
                    modified.append(record)
                else:
                    deleted.append(record)
            return {
                "added": added,
                "modified": modified,
                "deleted": deleted,
                "dropped": dropped,
            }

        result = self.db.call(_write)
        self.reload()
        return result

    def _apply_one(
        self,
        conn: sqlite3.Connection,
        existing: dict[str, dict[str, Any]],
        key: str,
        raw: dict[str, Any],
        now: float,
        active_count: int,
    ) -> dict[str, Any]:
        if not valid_state_key(key, max_chars=self.key_max_chars):
            return {"kind": "dropped", "reason": "key"}
        flag = _active_flag(raw.get("active"))
        if flag is None:
            return {"kind": "dropped", "reason": "active"}
        current = existing.get(key)
        if flag == 0:
            if current is None:
                return {"kind": "dropped", "reason": "missing"}
            before = str(current["value"])
            was_active = int(current["active"]) == 1
            conn.execute(
                "UPDATE states SET active = 0, updated_at = ? WHERE key = ?",
                (now, key),
            )
            current["updated_at"] = now
            current["active"] = 0
            if was_active:
                active_count -= 1
            return {
                "kind": "delete",
                "before": before,
                "after": "",
                "active_count": active_count,
            }
        value = str(raw.get("value") or "").strip().replace("\n", "")
        if (
            not value
            or len(value) > self.max_chars
            or is_crisis_text(value)
            or has_ephemeral_time(value)
        ):
            return {"kind": "dropped", "reason": "value"}
        if current is None:
            if active_count >= self.max_items:
                return {"kind": "dropped", "reason": "cap"}
            conn.execute(
                """
                INSERT INTO states (key, value, created_at, updated_at, active)
                VALUES (?, ?, ?, ?, 1)
                """,
                (key, value, now, now),
            )
            existing[key] = {
                "value": value,
                "created_at": now,
                "updated_at": now,
                "active": 1,
            }
            return {
                "kind": "add",
                "before": "",
                "after": value,
                "active_count": active_count + 1,
            }
        before = str(current["value"])
        was_active = int(current["active"]) == 1
        conn.execute(
            """
            UPDATE states
            SET value = ?, updated_at = ?, active = 1
            WHERE key = ?
            """,
            (value, now, key),
        )
        current["value"] = value
        current["updated_at"] = now
        current["active"] = 1
        return {
            "kind": "modify",
            "before": before,
            "after": value,
            "active_count": active_count if was_active else active_count + 1,
        }


def _active_flag(value: object) -> int | None:
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, int) and not isinstance(value, bool) and value in {0, 1}:
        return value
    if isinstance(value, float) and value in {0.0, 1.0}:
        return int(value)
    text = str(value if value is not None else "").strip()
    if text in {"0", "1"}:
        return int(text)
    return None

